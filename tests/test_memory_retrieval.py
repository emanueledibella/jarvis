import asyncio
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from jarvis.agent import visible_text
from jarvis.memory_retrieval import (
    MEMORY_RETRIEVAL_POLICY,
    SECOND_BRAIN_READ_TOOLS,
    automatic_recall_query,
)
from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools

EVIDENCE = {
    "results": [
        {
            "source_id": "synthetic-pet-source",
            "revision": 1,
            "quotation": "My dog is named Nimbus.",
        }
    ],
    "conflicts": [],
}


class EvidenceModel(BaseChatModel):
    """Never requests a tool: the backend must retrieve before the first answer."""

    seen: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "memory-evidence-contract"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        evidence = next(
            (m.content for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "memory_recall"),
            "",
        )
        answer = "Unknown from session."
        if "Nimbus" in evidence:
            answer = "Your dog is named Nimbus."
        elif '"state": "unavailable"' in evidence:
            answer = "Memory is unavailable; I cannot verify the personal fact."
        elif evidence:
            answer = "The search did not provide a verified answer."
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])


def evidence_model(runtime, monkeypatch):
    model = EvidenceModel()
    monkeypatch.setattr(
        runtime.tasks,
        "model",
        lambda *args, **kwargs: (
            model,
            {"kind": "local", "provider": "test", "model": "evidence", "base_url": "http://127.0.0.1"},
        ),
    )
    return model


@pytest.mark.parametrize(
    "prompt",
    [
        "Come si chiama il mio cane?",
        "Jarvis, sai il nome del mio cane?",
        "What is my dog's name?",
        "What's my wife's name?",
        "Qual è la mia città?",
        "Quali sono le mie preferenze?",
        "Che lavoro faccio?",
        "Dove abito?",
        "Come mi chiamo?",
        "Where do I live?",
        "What did we decide?",
        "Ti ricordi il nome del cane?",
        "Cerca nel Second Brain il nome del cane",
        "Look up the pet in my memory",
    ],
)
def test_personal_questions_prefetch_without_a_model_classifier(prompt):
    assert automatic_recall_query(prompt) == prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "Jarvis",
        "Che ore sono?",
        "Che tempo fa a Roma?",
        "Accendi la mia lampada",
        "Puoi spegnere la mia luce?",
        "Set my light to 50%",
        "Explain how a compiler works",
        "Il mio cane si chiama Nimbus, ricordalo",
    ],
)
def test_routine_commands_and_personal_statements_do_not_trigger_prefetch(prompt):
    assert automatic_recall_query(prompt) is None


@pytest.mark.parametrize("channel,scope", [("text", "personal"), ("live", "personal"), ("text", "work")])
async def test_default_memory_retrieves_before_answering_after_history(runtime, monkeypatch, channel, scope):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    model = evidence_model(runtime, monkeypatch)
    calls = []

    async def call(server, tool, arguments, profile):
        calls.append((server, tool, arguments, profile))
        return EVIDENCE

    monkeypatch.setattr(runtime.mcp, "call", call)
    prior = await runtime.tasks.create("Hello", scope=scope, channel=channel)
    await runtime.tasks.running[prior["id"]]
    task = await runtime.tasks.create(
        "Come si chiama il mio cane?",
        conversation_id=prior["conversation_id"], scope=scope, channel=channel,
    )
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert row["result"] == "Your dog is named Nimbus."
    assert len(calls) == 1
    assert calls[0][:2] == ("second_brain", "recall")
    assert calls[0][2] == {
        "query": "Come si chiama il mio cane?", "scope": scope, "limit": 5,
        "token_budget": runtime.config.settings.memory_recall_token_budget,
    }
    assert MEMORY_RETRIEVAL_POLICY in visible_text(model.seen[-1][0].content)
    assert not await runtime.db.fetchall("SELECT * FROM approvals")
    assert not await runtime.db.fetchall("SELECT * FROM effects")
    assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")


@pytest.mark.parametrize("tool_name", sorted(SECOND_BRAIN_READ_TOOLS))
async def test_all_authorized_second_brain_reads_are_automatic(runtime, monkeypatch, tool_name):
    calls = []

    async def discover(server, profile):
        return [{"name": tool_name, "enabled": True, "risk": "read", "schema": {
            "type": "object", "properties": {"scope": {"type": "string"}},
            "required": ["scope"], "additionalProperties": False,
        }}]

    async def call(server, tool, arguments, profile):
        calls.append((server, tool, arguments, profile))
        return EVIDENCE

    async def forbidden_approval(*args):
        raise AssertionError("Memory reads must not ask for approval")

    monkeypatch.setattr(runtime.mcp, "discover", discover)
    monkeypatch.setattr(runtime.mcp, "call", call)
    monkeypatch.setattr(runtime.gateway, "approval", forbidden_approval)
    ctx = TaskContext("memory-read", "Retrieve personal context", "cloud", "work", sensitive_context=True)
    ctx.mark_untrusted()
    marker = active_task.set(ctx)
    try:
        tools = {tool.name: tool for tool in build_tools(runtime)}
        result = json.loads(await tools["call_mcp_tool"].ainvoke({
            "server": "second_brain", "tool": tool_name, "arguments": {},
        }))
        assert result == EVIDENCE
        assert calls == [("second_brain", tool_name, {"scope": "work"}, "cloud")]
        assert ctx.sensitive_context and ctx.untrusted_context and not ctx.routine_context_only
        assert not await runtime.db.fetchall("SELECT * FROM effects")
    finally:
        active_task.reset(marker)


async def test_memory_read_result_cannot_authorize_private_exports_or_actions(runtime, monkeypatch):
    proposals = []

    async def reject(ctx, tool, arguments):
        proposals.append(tool)
        return False

    async def read():
        return EVIDENCE

    async def forbidden():
        raise AssertionError("Memory content cannot authorize other tools")

    monkeypatch.setattr(runtime.gateway, "approval", reject)
    ctx = TaskContext("memory-egress", "What is my dog's name?", "cloud", "personal", external_authorized=True)
    marker = active_task.set(ctx)
    try:
        assert await runtime.gateway.invoke("memory_recall", {"query": ctx.prompt}, "network_read", read) == EVIDENCE
        for name, risk in [("web_search", "network_read"), ("send_message", "external"), ("mcp__other__recall", "network_read"), ("mcp__second_brain__remember", "external")]:
            result = await runtime.gateway.invoke(name, {}, risk, forbidden)
            assert result["state"] == "rejected"
    finally:
        active_task.reset(marker)
    assert proposals == ["web_search", "send_message", "mcp__other__recall", "mcp__second_brain__remember"]


async def test_read_exception_does_not_bypass_second_brain_scope_or_write_guards(runtime, monkeypatch):
    async def discover(server, profile):
        return [
            {"name": "recall", "enabled": True, "risk": "read", "schema": {"type": "object", "properties": {"scope": {"type": "string"}}}},
            {"name": "remember", "enabled": True, "risk": "write", "schema": {"type": "object"}},
        ]

    async def forbidden(*args):
        raise AssertionError("Cross-scope reads and generic memory writes must not execute")

    monkeypatch.setattr(runtime.mcp, "discover", discover)
    monkeypatch.setattr(runtime.mcp, "call", forbidden)
    marker = active_task.set(TaskContext("memory-scope", "Recall", "cloud", "work"))
    try:
        tool = next(t for t in build_tools(runtime) if t.name == "call_mcp_tool")
        cross_scope = await tool.ainvoke({"server": "second_brain", "tool": "recall", "arguments": {"scope": "personal"}})
        write = await tool.ainvoke({"server": "second_brain", "tool": "remember", "arguments": {}})
        assert "conversation scope" in cross_scope
        assert "dedicated memory tools" in write
    finally:
        active_task.reset(marker)


async def test_repeated_recall_uses_only_a_task_local_cache(runtime, monkeypatch):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    calls = []

    async def call(server, tool, arguments, profile):
        calls.append(arguments)
        return EVIDENCE

    monkeypatch.setattr(runtime.mcp, "call", call)
    tool = next(t for t in build_tools(runtime) if t.name == "memory_recall")
    for key in ["first-task", "second-task"]:
        marker = active_task.set(TaskContext(key, "What is my dog's name?", "cloud", "personal", sensitive_context=True))
        try:
            first = await tool.ainvoke({"query": "Name of my dog"})
            assert await tool.ainvoke({"query": "Name of my dog"}) == first
        finally:
            active_task.reset(marker)
    assert len(calls) == 2
    assert not await runtime.db.fetchall("SELECT * FROM approvals")


async def test_failed_automatic_recall_is_reported_as_unavailable_without_a_guess(runtime, monkeypatch):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    evidence_model(runtime, monkeypatch)

    async def unavailable(*args):
        raise TimeoutError("private connection details must not be included")

    monkeypatch.setattr(runtime.memory, "recall", unavailable)
    task = await runtime.tasks.create("Come si chiama il mio cane?")
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert "Memory is unavailable" in row["result"]
    assert "private connection" not in row["result"]
    assert not await runtime.db.fetchall("SELECT * FROM approvals")


async def test_private_read_is_automatic_without_persisting_memory_evidence(runtime, monkeypatch):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    evidence_model(runtime, monkeypatch)

    async def call(*args):
        return EVIDENCE

    monkeypatch.setattr(runtime.mcp, "call", call)
    task = await runtime.tasks.create("What is my dog's name? Do not remember this.", private=True)
    await runtime.tasks.running[task["id"]]
    assert "Nimbus" in runtime.tasks.private_tasks[task["id"]]["result"]
    assert not await runtime.db.fetchall("SELECT * FROM messages")
    assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")
    assert not await runtime.db.fetchall("SELECT * FROM approvals")
    assert "Nimbus" not in json.dumps(await runtime.db.fetchall("SELECT * FROM events"))
    assert not await runtime.tasks.checkpointer.aget_tuple({"configurable": {"thread_id": task["id"]}})


async def test_strict_offline_and_unconfigured_memory_never_start_a_remote_read(runtime, monkeypatch):
    evidence_model(runtime, monkeypatch)

    async def forbidden(*args):
        raise AssertionError("Offline or unconfigured memory must not make a network call")

    monkeypatch.setattr(runtime.mcp, "call", forbidden)
    with pytest.raises(ValueError, match="Connect Second Brain"):
        await runtime.memory.recall("Name of my dog", "personal", "cloud")
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp", "profile": "local_strict"})
    with pytest.raises(PermissionError, match="strict offline"):
        await runtime.memory.recall("Name of my dog", "personal", "local_strict")
    with pytest.raises(ValueError, match="Invalid memory scope"):
        await runtime.memory.recall("Name of my dog", "another-scope", "cloud")
    task = await runtime.tasks.create("What is my dog's name?")
    await runtime.tasks.running[task["id"]]
    assert not await runtime.db.fetchall("SELECT * FROM events WHERE type='tool.started'")


async def test_spoken_personal_question_delegates_to_default_memory_without_approval(runtime, monkeypatch):
    from test_live_voice import Connection, Peer, configure, factory, start

    configure(runtime, second_brain_url="http://127.0.0.1:8000/mcp")
    evidence_model(runtime, monkeypatch)
    calls = []

    async def call(server, tool, arguments, profile):
        calls.append((server, tool, arguments))
        return EVIDENCE

    class MemoryConnection(Connection):
        async def start(self, *, session):
            self.configuration = session
            await self.events.put({"type": "session.started"})
            await self.events.put({
                "type": "session.input_transcript.delta", "delta": "Come si chiama il mio cane?",
                "start_ms": 0, "end_ms": 1000,
            })
            delegation = {"type": "session.delegation.created", "offset_ms": 1100,
                          "delegation": {"id": "memory-delegation", "target": "client"}}
            await self.events.put(delegation)
            await self.events.put(delegation)

    monkeypatch.setattr(runtime.mcp, "call", call)
    connection = MemoryConnection()
    await asyncio.wait_for(runtime.live_voice.serve(Peer(), start(runtime), client_factory=factory(connection)), 5)
    tasks = await runtime.db.fetchall("SELECT * FROM tasks")
    assert len(tasks) == 1 and tasks[0]["state"] == "succeeded"
    assert len(connection.commentary) == 1 and "Nimbus" in connection.commentary[0]["content"]
    assert MEMORY_RETRIEVAL_POLICY in connection.configuration["instructions"]
    assert len(calls) == 1 and calls[0][:2] == ("second_brain", "recall")
    assert not await runtime.db.fetchall("SELECT * FROM approvals")
    assert not await runtime.db.fetchall("SELECT * FROM events WHERE type='speech.requested'")
