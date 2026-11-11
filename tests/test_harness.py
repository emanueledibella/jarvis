import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from jarvis.harness import CODING_PLAYBOOK, route_request
from jarvis.harness_context import HarnessRun
from jarvis.policy import TaskContext, active_task


class HarnessModel(BaseChatModel):
    respond: Callable
    requests: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "harness-fixture"

    def bind_tools(self, tools, **kwargs):
        schemas = [convert_to_openai_tool(item) for item in tools]
        return self.bind(schemas=schemas, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, schemas=(), **kwargs):
        names = {schema["function"]["name"] for schema in schemas}
        self.requests.append((messages, names, schemas, kwargs.get("prompt_cache_key")))
        response = self.respond(messages, names)
        response.usage_metadata = {
            "input_tokens": 100, "output_tokens": 5, "total_tokens": 105,
            "input_token_details": {"cache_read": 40, "cache_write": 10},
        }
        return ChatResult(generations=[ChatGeneration(message=response)])


def call(name, args, ident):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": ident}])


def use_model(runtime, monkeypatch, respond, *, cloud=False):
    model = HarnessModel(respond=respond)
    if cloud:
        runtime.config.update({
            "model_input_usd_per_million": 1,
            "model_output_usd_per_million": 2,
            "monthly_budget_usd": 10,
        })
    monkeypatch.setattr(runtime.tasks, "model", lambda *args, **kwargs: (
        model, {
            "kind": "cloud" if cloud else "local",
            "provider": "openai" if cloud else "test",
            "base_url": "",
            "model": "harness-fixture",
        },
    ))
    return model


async def run_task(runtime, prompt, **kwargs):
    task = await runtime.tasks.create(prompt, **kwargs)
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    return task, row["result"], json.loads(row["usage"])


async def test_normal_turn_has_stable_small_prefix_and_measures_provider_cache(runtime, monkeypatch):
    model = use_model(runtime, monkeypatch, lambda *_: AIMessage(content="Ciao!"), cloud=True)
    task, _, usage = await run_task(runtime, "Ciao")
    await run_task(runtime, "Buongiorno", conversation_id=task["conversation_id"])
    first, second = model.requests
    assert first[0][0].content == second[0][0].content
    assert first[2] == second[2] and first[3] == second[3] and first[3].startswith("jarvis-v1-")
    assert len(first[1]) < len(runtime.tasks.tools()) / 4
    assert "delegate_tasks" in first[1] and not usage.get("delegated_tasks")
    assert {"task", "write_todos", "workspace_edit", "consult_specialist"}.isdisjoint(first[1])
    assert CODING_PLAYBOOK not in first[0][0].content
    assert usage["input_tokens"] == 100 and usage["cached_input_tokens"] == 40
    status = await runtime.budget.status()
    assert (status["input_tokens"], status["cached_input_tokens"], status["cache_write_tokens"]) == (200, 80, 20)


async def test_harness_prefix_footprint(runtime, monkeypatch):
    model = use_model(runtime, monkeypatch, lambda *_: AIMessage(content="Risposta di prova."))

    def footprint(request):
        messages, names, schemas, _ = request
        system = sum(len(m.text.encode()) for m in messages if m.type == "system")
        return len(names), system + len(json.dumps(schemas, ensure_ascii=False).encode())

    for prompt in ("Ciao", "Che tempo fa a Torino?", "Prossimo evento in calendario?", "Correggi il bug in app.py"):
        await run_task(runtime, prompt)
        compact = footprint(model.requests[-1])
        # Old rows have no harness version; hold the scheduler until we create one.
        runtime.tasks.semaphore = asyncio.Semaphore(0)
        task = await runtime.tasks.create(prompt)
        row = await runtime.db.fetchone("SELECT usage FROM tasks WHERE id=?", (task["id"],))
        usage = json.loads(row["usage"])
        usage.pop("harness_version")
        await runtime.db.execute("UPDATE tasks SET usage=? WHERE id=?", (json.dumps(usage), task["id"]))
        runtime.tasks.semaphore.release()
        await runtime.tasks.running[task["id"]]
        legacy = footprint(model.requests[-1])
        assert compact[0] < legacy[0] and compact[1] < legacy[1] * 0.6
        print(f"{prompt}: {legacy[0]} -> {compact[0]} tools; {legacy[1]} -> {compact[1]} prefix bytes")


async def test_capability_discovery_exposes_an_initially_deferred_group(runtime, monkeypatch):
    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            assert "mail_accounts" not in names
            return call("load_tools", {"group": "mail"}, "open-mail")
        if len(results) == 1:
            assert "mail_accounts" in names
            return call("mail_accounts", {}, "get-mail")
        return AIMessage(content="Ho controllato gli account disponibili.")

    use_model(runtime, monkeypatch, respond)
    task, _, usage = await run_task(runtime, "Controlla i collegamenti disponibili")
    assert usage["peak_tool_count"] > usage["initial_tool_count"]
    assert await runtime.db.fetchone(
        "SELECT id FROM events WHERE task_id=? AND type='tool.completed' AND data LIKE '%mail_accounts%'",
        (task["id"],),
    )


async def test_conversation_recall_cannot_return_messages_from_another_thread(runtime, monkeypatch):
    use_model(runtime, monkeypatch, lambda *_: AIMessage(content="Ricevuto."))
    main, _, _ = await run_task(runtime, "Orion del nostro thread: azzurro")
    await run_task(runtime, "Orion di un altro thread: rosso")

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            return call("recall_conversation", {"phrase": "Orion"}, "old-context")
        assert "azzurro" in results[-1].text and "rosso" not in results[-1].text
        return AIMessage(content="Il dettaglio era azzurro.")

    use_model(runtime, monkeypatch, respond)
    _, result, _ = await run_task(runtime, "Riprendi quel dettaglio", conversation_id=main["conversation_id"])
    assert result == "Il dettaglio era azzurro."


async def test_repeated_web_reads_share_the_result_and_end_before_recursion_limit(runtime, monkeypatch):
    searches = []

    async def search(query, profile, limit):
        searches.append(query)
        return {"results": [{"url": "https://example.com/", "title": "Fonte"}]}

    def respond(messages, names):
        if "web_search" not in names:
            return AIMessage(content="Ho trovato una fonte. Non ci sono altri riscontri.")
        count = sum(isinstance(message, ToolMessage) for message in messages)
        return call("web_search", {"query": "Torino"}, f"search-{count}")

    monkeypatch.setattr(runtime.productivity, "search", search)
    use_model(runtime, monkeypatch, respond)
    _, result, usage = await run_task(runtime, "Cerca online Torino")
    assert searches == ["Torino"]
    assert usage["tool_reads_reused"] == 2
    assert usage["model_calls"] == 4 and usage["harness_stop_reason"] == "repeated_tool_results"
    assert result.startswith("Ho trovato una fonte")


async def test_public_reads_after_an_effect_fetch_fresh_evidence(runtime):
    url = "https://example.com/status"
    ctx = TaskContext("cache-invalidation", "Leggi " + url, "cloud", "personal", harness_run=HarnessRun())
    marker = active_task.set(ctx)
    published = False
    reads = 0

    async def fetch():
        nonlocal reads
        reads += 1
        return {"text": "after" if published else "before"}

    async def change():
        nonlocal published
        published = True
        return {"state": "accepted"}

    try:
        async def read():
            return await runtime.gateway.invoke("read_web_page", {"url": url}, "network_read", fetch)

        assert (await read())["text"] == (await read())["text"] == "before"
        # Use the same scoped, preconfigured grant path as a registered light.
        await runtime.gateway.invoke("light_set", {"device": "fixture"}, "lighting_direct", change)
        assert (await read())["text"] == "after" and reads == 2
    finally:
        active_task.reset(marker)


async def test_research_specialist_is_isolated_and_counted_in_parent_budget(runtime, monkeypatch):
    queries = []

    async def search(query, profile, limit):
        queries.append(query)
        return {"results": [{"url": "https://example.com/geotermia"}]}

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if "public research specialist" in messages[0].text:
            assert names == {"current_time", "web_search", "read_web_page", "read_evidence"}
            assert [m.text for m in messages if m.type == "human"] == ["geotermia"]
            assert not any("PRIVATE-MARKER" in m.text for m in messages)
            if not results:
                return call("web_search", {"query": "PRIVATE-MARKER"}, "blocked")
            if len(results) == 1:
                return call("web_search", {"query": "geotermia"}, "research")
            return AIMessage(content="Fonte pubblica: https://example.com/geotermia")
        if "consult_specialist" not in names:
            return AIMessage(content="Contesto.")
        if not results:
            return call("consult_specialist", {"brief": "geotermia"}, "delegate")
        assert "example.com/geotermia" in results[-1].text
        return AIMessage(content="Ho verificato una fonte sulla geotermia.")

    monkeypatch.setattr(runtime.productivity, "search", search)
    use_model(runtime, monkeypatch, respond, cloud=True)
    prior, _, _ = await run_task(runtime, "Riferimento riservato PRIVATE-MARKER")
    task, _, usage = await run_task(
        runtime, "Fai una ricerca approfondita sulla geotermia", conversation_id=prior["conversation_id"],
    )
    assert queries == ["geotermia"]
    assert usage["harness_mode"] == "research" and usage["specialist_calls"] == 1
    assert usage["model_calls"] == 5
    assert len(await runtime.db.fetchall("SELECT id FROM model_usage WHERE task_id=?", (task["id"],))) == 5
    assert not await runtime.db.fetchall("SELECT * FROM approvals")


@pytest.mark.parametrize("failure", [None, "calendar", "research"])
async def test_delegation_runs_independent_reads_concurrently_with_isolated_input(runtime, monkeypatch, failure):
    agenda = "Dimmi cosa ho sul mio calendario per Venere"
    brief = "cerca sul web le novità sul fotovoltaico"
    prompt = f"{agenda} e {brief}"
    calendar_started, search_started = asyncio.Event(), asyncio.Event()
    queries = []
    start = datetime.now(UTC) + timedelta(hours=1)

    async def calendar(profile, days):
        assert days == 2
        ctx = active_task.get()
        assert ctx.prompt == agenda and ctx.private_sources_read and ctx.delegated
        calendar_started.set()
        await asyncio.wait_for(search_started.wait(), timeout=5)
        if failure == "calendar":
            raise PermissionError("CALENDAR-PROVIDER-DETAIL")
        return {"state": "ready", "events": [{
            "id": "1", "title": "AGENDA-DETAIL", "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
        }]}

    async def search(query, profile, limit):
        ctx = active_task.get()
        assert ctx.prompt == brief and not ctx.private_sources_read and ctx.delegated
        queries.append(query)
        search_started.set()
        await asyncio.wait_for(calendar_started.wait(), timeout=5)
        return {"results": [{"url": "https://example.com/fotovoltaico"}]}

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if "general-purpose Jarvis subagent" in messages[0].text:
            assert names == {"current_time", "calendar_events", "read_evidence"}
            assert [m.text for m in messages if m.type == "human"] == [agenda]
            if not results:
                return call("calendar_events", {"days": 2}, "calendar")
            if failure == "calendar":
                assert results[-1].status == "error"
                raise RuntimeError("CALENDAR-PROVIDER-DETAIL")
            evidence = json.loads(results[-1].text)
            assert evidence["events"][0]["title"] == "AGENDA-DETAIL"
            assert evidence["analysis"]["next_event_indexes"] == [0]
            return AIMessage(content="Prossimo impegno: AGENDA-DETAIL.")
        if "public research specialist" in messages[0].text:
            assert names == {"current_time", "web_search", "read_web_page", "read_evidence"}
            assert [m.text for m in messages if m.type == "human"] == [brief]
            assert not any("AGENDA-DETAIL" in m.text or "PRIOR-DETAIL" in m.text for m in messages)
            if not results:
                return call("web_search", {"query": "Venere"}, "blocked")
            if len(results) == 1:
                return call("web_search", {"query": "fotovoltaico"}, "research")
            if failure == "research":
                raise RuntimeError("RESEARCH-PROVIDER-DETAIL")
            return AIMessage(content="Fonte pubblica: https://example.com/fotovoltaico")
        assert "delegate_tasks" in names and "consult_specialist" not in names
        if not results:
            return call("delegate_tasks", {"assignments": [
                {"request": agenda, "groups": ["calendar"]},
                {"request": brief, "groups": ["web"]},
            ]}, "both")
        assert "PROVIDER-DETAIL" not in results[-1].text
        calendar_result, web_result = json.loads(results[-1].text)["results"]
        assert calendar_result["worker"] == "jarvis-subagent"
        assert web_result["worker"] == "jarvis-public-research"
        assert ("AGENDA-DETAIL" in calendar_result["result"]) == (failure != "calendar")
        assert ("https://example.com/fotovoltaico" in web_result["result"]) == (failure != "research")
        assert [result["state"] for result in (calendar_result, web_result)] == [
            "unavailable" if failure == kind else "finished" for kind in ("calendar", "research")
        ]
        return AIMessage(content="Ho verificato i risultati disponibili.")

    use_model(runtime, monkeypatch, lambda *_: AIMessage(content="Ricevuto."))
    prior, _, _ = await run_task(runtime, "Dettaglio riservato PRIOR-DETAIL")
    runtime.config.update({"second_brain_url": "https://example.com/mcp"})

    async def recall(*_args):
        pytest.fail("A request for two independent reads should not prefetch memory.")

    monkeypatch.setattr(runtime.memory, "recall", recall)
    monkeypatch.setattr(runtime.productivity, "calendar", calendar)
    monkeypatch.setattr(runtime.productivity, "search", search)
    use_model(runtime, monkeypatch, respond, cloud=True)
    task, _, usage = await run_task(runtime, prompt, conversation_id=prior["conversation_id"])
    assert calendar_started.is_set() and search_started.is_set()
    assert queries == ["fotovoltaico"]
    assert usage["specialist_calls"] == 1 and usage["delegated_tasks"] == 2
    assert usage["model_calls"] == 7
    assert len(await runtime.db.fetchall("SELECT id FROM model_usage WHERE task_id=?", (task["id"],))) == 7
    assert not await runtime.db.fetchall("SELECT id FROM approvals")


async def test_local_strict_runs_unrelated_assignments_with_only_local_tools(runtime, monkeypatch):
    requests = ["Dimmi che ore sono", "Converti 2 km in metri", "Cerca online notizie di Roma"]

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if "delegate_tasks" in names:
            if not results:
                return call("delegate_tasks", {"assignments": [
                    {"request": requests[0]}, {"request": requests[1]},
                    {"request": requests[2], "groups": ["web"]},
                ]}, "local")
            evidence = json.loads(results[-1].text)["results"]
            assert [item["result"] for item in evidence] == [
                "Orario verificato.", "2000 metri.", "Ricerca web indisponibile.",
            ]
            return AIMessage(content="Ecco l'orario e la conversione. Il web è indisponibile.")
        assert names == {"current_time", "read_evidence"}
        user, = [message.text for message in messages if message.type == "human"]
        if user == requests[0]:
            if not results:
                return call("current_time", {}, "time")
            assert "timezone" in results[-1].text
            return AIMessage(content="Orario verificato.")
        if user == requests[1]:
            return AIMessage(content="2000 metri.")
        assert user == requests[2] and "no available subagent tools: web" in messages[0].text
        return AIMessage(content="Ricerca web indisponibile.")

    use_model(runtime, monkeypatch, respond)
    _, _, usage = await run_task(
        runtime, ". ".join(requests), profile="local_strict",
    )
    assert usage["delegated_tasks"] == 3


@pytest.mark.parametrize("invalid", ["overlap", "foreign"])
async def test_delegation_rejects_assignments_without_distinct_owner_excerpts(runtime, monkeypatch, invalid):
    prompt = "Mostra la mia agenda e controlla le luci"
    second = "controlla le luci" if invalid == "overlap" else "Appunto da un'altra conversazione"

    def respond(messages, names):
        assert "delegate_tasks" in names
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            return call("delegate_tasks", {"assignments": [
                {"request": prompt, "groups": ["calendar"]},
                {"request": second, "groups": ["home"]},
            ]}, "invalid")
        assert "distinct, nonoverlapping excerpts" in results[-1].text
        return AIMessage(content="Rivedo il piano.")

    use_model(runtime, monkeypatch, respond)
    _, _, usage = await run_task(runtime, prompt)
    assert not usage.get("delegated_tasks")
    assert usage["model_calls"] == 2


async def test_delegated_change_uses_the_main_tasks_approval_and_checkpoint(runtime, monkeypatch):
    change, conversion = "Salva la nota Alba tramite MCP", "converti 2 km in metri"
    arguments = {"server": "demo", "tool": "save_note", "arguments": {"title": "Alba"}}
    writes = []

    async def discover(server, profile):
        assert server == "demo"
        return [{
            "name": "save_note", "enabled": True, "risk": "write",
            "schema": {"type": "object", "properties": {"title": {"type": "string"}}},
        }]

    async def save(server, tool, payload, profile):
        writes.append((server, tool, payload))
        return {"state": "saved", "title": payload["title"]}

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if "general-purpose Jarvis subagent" in messages[0].text:
            if "call_mcp_tool" not in names:
                return AIMessage(content="2000 metri.")
            if not results:
                return call("call_mcp_tool", arguments, "worker-write")
            assert "main task" in results[-1].text
            return AIMessage(content="Proposta di nota Alba in attesa del coordinatore.")
        if not results:
            return call("delegate_tasks", {"assignments": [
                {"request": change, "groups": ["integrations"]}, {"request": conversion},
            ]}, "prepare")
        if results[-1].name == "delegate_tasks":
            assert "2000 metri" in results[-1].text
            return call("call_mcp_tool", arguments, "main-write")
        assert json.loads(results[-1].text)["state"] == "saved"
        return AIMessage(content="Nota Alba salvata. La conversione è 2000 metri.")

    monkeypatch.setattr(runtime.mcp, "discover", discover)
    monkeypatch.setattr(runtime.mcp, "call", save)
    use_model(runtime, monkeypatch, respond)
    task = await runtime.tasks.create(f"{change} e {conversion}")
    key = task["id"]
    await runtime.tasks.running[key]
    row = await runtime.db.fetchone("SELECT state,error FROM tasks WHERE id=?", (key,))
    assert row["state"] == "waiting_user", row["error"]
    approvals = await runtime.db.fetchall("SELECT id,tool FROM approvals WHERE task_id=?", (key,))
    approval, = approvals
    assert approval["tool"] == "mcp__demo__save_note"
    assert not writes

    await runtime.gateway.decide(approval["id"], True)
    await runtime.tasks.resume(key)
    await runtime.tasks.running[key]
    row = await runtime.db.fetchone("SELECT state,result,usage FROM tasks WHERE id=?", (key,))
    assert row["state"] == "succeeded" and "Nota Alba salvata" in row["result"]
    assert json.loads(row["usage"])["delegated_tasks"] == 2
    assert writes == [("demo", "save_note", {"title": "Alba"})]


async def test_cancelling_main_task_cancels_both_delegated_reads(runtime, monkeypatch):
    agenda, documents = "Controlla il calendario", "elenca i documenti caricati"
    started = {name: asyncio.Event() for name in ("calendar", "documents")}
    stopped = set()

    async def pending(name):
        started[name].set()
        try:
            await asyncio.Future()
        finally:
            stopped.add(name)

    async def calendar(*args):
        return await pending("calendar")

    async def listing(*args, **kwargs):
        return await pending("documents")

    def respond(messages, names):
        if "calendar_events" in names and "delegate_tasks" not in names:
            return call("calendar_events", {"days": 1}, "calendar")
        if "documents_list" in names and "delegate_tasks" not in names:
            return call("documents_list", {}, "documents")
        return call("delegate_tasks", {"assignments": [
            {"request": agenda, "groups": ["calendar"]},
            {"request": documents, "groups": ["documents"]},
        ]}, "both")

    monkeypatch.setattr(runtime.productivity, "calendar", calendar)
    monkeypatch.setattr(runtime.documents, "listing", listing)
    use_model(runtime, monkeypatch, respond)
    task = await runtime.tasks.create(f"{agenda} e {documents}")
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=5)
    finally:
        await runtime.tasks.cancel(task["id"])
    row = await runtime.db.fetchone("SELECT state FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "cancelled"
    assert stopped == set(started)


async def test_compaction_keeps_original_tool_result_recoverable(runtime, monkeypatch):
    marker = "Original evidence beyond the preview"

    async def fetch(url, profile):
        return {"url": url, "text": ("A" if "first" in url else "B") * 19_000 + marker}

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            return call("read_web_page", {"url": "https://example.com/first"}, "first")
        if len(results) == 1:
            return call("read_web_page", {"url": "https://example.com/second"}, "second")
        if len(results) == 2:
            assert "evidence_ref" in results[0].text and marker not in results[0].text
            assert marker in results[1].text
            return call("read_evidence", {"evidence_ref": "first", "offset": 18_000}, "reread")
        assert marker in results[-1].text
        return AIMessage(content="Ho recuperato il passaggio dalla prima fonte.")

    monkeypatch.setattr(runtime.productivity, "fetch", fetch)
    use_model(runtime, monkeypatch, respond)
    _, _, usage = await run_task(runtime, "Leggi le due fonti sul web")
    assert usage["max_evidence_bytes_omitted"] > 15_000


@pytest.mark.parametrize(("text", "mode"), [
    ("Spiegami come scrivere codice Python", "assistant"),
    ("Scrivi una mail sul bug del repository", "assistant"),
    ("Esegui npm test", "assistant"),
    ("Non scrivere codice, fai una revisione", "assistant"),
    ("Puoi scrivere una funzione in Python?", "coding"),
    ("Fix the bug in app.ts", "coding"),
    ("Fai una ricerca approfondita sulla geotermia", "research"),
    ("Fai una ricerca approfondita nella mia posta", "assistant"),
])
def test_intent_routes_coding_only_on_explicit_request(text, mode):
    assert route_request(text).mode == mode


async def test_coding_exact_edit_uses_line_range_and_keeps_unrelated_file_content(runtime, monkeypatch, tmp_path):
    runtime.config.update({"workspace_roots": [str(tmp_path)]})
    target = tmp_path / "math.py"
    original = "a = 1\nreturn_value = 2\nb = 3\n"
    target.write_text(original)

    def respond(messages, names):
        results = [message for message in messages if isinstance(message, ToolMessage)]
        assert "workspace_edit" in names
        if not results:
            return call("workspace_read", {"path": "math.py", "start_line": 2, "line_count": 1}, "read-line")
        if len(results) == 1:
            view = json.loads(results[0].text)
            assert view["text"] == "return_value = 2\n"
            assert view["sha256"] == hashlib.sha256(original.encode()).hexdigest()
            return call("workspace_edit", {
                "path": "math.py", "old_text": "return_value = 2", "new_text": "return_value = 4",
                "expected_sha256": view["sha256"],
            }, "edit-line")
        return AIMessage(content="Ho aggiornato il valore.")

    use_model(runtime, monkeypatch, respond)
    task = await runtime.tasks.create("Correggi il codice in math.py")
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT state,error FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "waiting_user", row["error"]
    assert target.read_text() == original
    approval = await runtime.db.fetchone("SELECT id,tool FROM approvals")
    assert approval["tool"] == "workspace_edit"
    await runtime.gateway.decide(approval["id"], True)
    await runtime.tasks.resume(task["id"])
    await runtime.tasks.running[task["id"]]
    assert target.read_text() == "a = 1\nreturn_value = 4\nb = 3\n"
