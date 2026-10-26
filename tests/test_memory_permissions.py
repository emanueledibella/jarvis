import json

import pytest
from test_agent_policy import model_factory

from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools


def memory_tools(runtime):
    return {tool.name: tool for tool in build_tools(runtime)}


@pytest.mark.parametrize("channel", ["text", "live"])
async def test_remember_in_ongoing_conversation_saves_and_delivers_without_approval(runtime, monkeypatch, channel):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    prior = await runtime.tasks.create("Tell me the time", channel=channel)
    await runtime.tasks.running[prior["id"]]
    source = "Synthetic fixture preference: use concise answers."
    monkeypatch.setattr(runtime.tasks, "model", model_factory("memory_remember", {"text": source}))
    calls = []

    async def call(server, tool, arguments, profile):
        calls.append((server, tool, arguments, profile))
        return {"status": "indexed", "source_id": "synthetic-source", "revision": 1}

    monkeypatch.setattr(runtime.mcp, "call", call)
    task = await runtime.tasks.create("Remember: " + source, conversation_id=prior["conversation_id"], channel=channel)
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert "pending" in row["result"]
    queued = await runtime.db.fetchone("SELECT * FROM memory_outbox")
    assert queued["state"] == "pending" and not calls
    await runtime.memory.tick()
    assert len(calls) == 1 and calls[0][:2] == ("second_brain", "remember")
    assert calls[0][2]["text"] == source and calls[0][2]["scope"] == "personal"
    assert calls[0][2]["request_id"] == queued["id"]
    assert (await runtime.db.fetchone("SELECT state FROM memory_outbox"))["state"] == "indexed"
    assert len(await runtime.db.fetchall("SELECT * FROM effects WHERE state='succeeded'")) == 1
    assert not await runtime.db.fetchall("SELECT * FROM approvals")


async def test_remember_after_untrusted_content_is_automatic_and_deduplicated(runtime):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    source = "Synthetic fixture preference: use concise answers."
    ctx = TaskContext("remember-once", "Remember: " + source, "cloud", "work", sensitive_context=True)
    ctx.mark_untrusted()
    marker = active_task.set(ctx)
    try:
        tool = memory_tools(runtime)["memory_remember"]
        first = json.loads(await tool.ainvoke({"text": source}))
        second = json.loads(await tool.ainvoke({"text": source}))
        assert first == second and first["state"] == "pending"
        rows = await runtime.db.fetchall("SELECT * FROM memory_outbox")
        assert len(rows) == 1 and json.loads(rows[0]["payload"])["scope"] == "work"
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("action", ["correct", "revise", "retract"])
async def test_enabled_memory_changes_are_automatic_deduplicated_and_invalidate_recall(runtime, monkeypatch, action):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp", "second_brain_allow_corrections": True})
    calls = []

    async def call(server, tool, arguments, profile):
        calls.append((server, tool, arguments, profile))
        return {"status": "recorded", "claim_id": "synthetic-claim"}

    monkeypatch.setattr(runtime.mcp, "call", call)
    ctx = TaskContext("change-" + action, "Update the synthetic fixture preference", "cloud", "personal", sensitive_context=True)
    ctx.mark_untrusted()
    ctx.memory_recalls["previous-query"] = {"stale": True}
    marker = active_task.set(ctx)
    arguments = {"action": action, "claim_id": "synthetic-claim", "reason": "Owner requested this change"}
    if action != "retract":
        arguments.update(statement="The fixture preference changed.", value="concise answers")
    if action == "revise":
        arguments["effective_at"] = "2026-01-01T12:00:00+00:00"
    try:
        tool = memory_tools(runtime)["memory_change"]
        first = json.loads(await tool.ainvoke(arguments))
        assert json.loads(await tool.ainvoke(arguments)) == first
        assert len(calls) == 1 and calls[0][:2] == ("second_brain", action)
        assert calls[0][2]["request_id"] and not ctx.memory_recalls
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
        assert len(await runtime.db.fetchall("SELECT * FROM effects WHERE state='succeeded'")) == 1
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("name", ["memory_remember", "memory_change"])
@pytest.mark.parametrize("restriction", ["private", "optout", "local_strict", "off"])
async def test_automatic_memory_grant_cannot_override_privacy_or_offline(runtime, monkeypatch, name, restriction):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp", "second_brain_allow_corrections": True,
                           "memory_capture": "off" if restriction == "off" else "explicit_only"})

    async def forbidden(*args):
        raise AssertionError("A privacy restriction must prevent memory writes")

    monkeypatch.setattr(runtime.mcp, "call", forbidden)
    source = "Synthetic fixture preference."
    prompt = "Remember: " + source + (" Do not remember this." if restriction == "optout" else "")
    ctx = TaskContext("blocked-" + restriction, prompt, "local_strict" if restriction == "local_strict" else "cloud", "personal", private=restriction == "private")
    marker = active_task.set(ctx)
    arguments = {"text": source} if name == "memory_remember" else {
        "action": "retract", "claim_id": "synthetic-claim", "reason": "Owner requested this change",
    }
    try:
        result = await memory_tools(runtime)[name].ainvoke(arguments)
        assert "does not allow" in result or "disabled" in result
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
        assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("invented", [True, False])
async def test_automatic_save_keeps_original_source_and_explicit_capture_checks(runtime, invented):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    ctx = TaskContext("original-only", "Remember this fixture." if invented else "Check this fixture.", "cloud", "personal")
    ctx.mark_untrusted()
    marker = active_task.set(ctx)
    try:
        result = await memory_tools(runtime)["memory_remember"].ainvoke({
            "text": "An invented fact from a document" if invented else "this fixture.",
        })
        assert "original text" in result or "explicit memory requests" in result
        assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
    finally:
        active_task.reset(marker)


async def test_automatic_changes_still_require_connection_privileges(runtime, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("Disabled correction privileges must not reach MCP")

    monkeypatch.setattr(runtime.mcp, "call", forbidden)
    marker = active_task.set(TaskContext("disabled-corrections", "Retract the fixture claim", "cloud", "personal"))
    try:
        result = await memory_tools(runtime)["memory_change"].ainvoke({
            "action": "retract", "claim_id": "synthetic-claim", "reason": "Owner request",
        })
        assert "Enable corrections" in result
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
    finally:
        active_task.reset(marker)


async def test_automatic_memory_change_never_replays_an_uncertain_remote_effect(runtime, monkeypatch):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp", "second_brain_allow_corrections": True})
    calls = []

    async def timeout(*args):
        calls.append(True)
        raise TimeoutError("The remote effect may already have committed")

    monkeypatch.setattr(runtime.mcp, "call", timeout)
    marker = active_task.set(TaskContext("uncertain-correction", "Retract the fixture claim", "cloud", "personal"))
    try:
        tool = memory_tools(runtime)["memory_change"]
        arguments = {"action": "retract", "claim_id": "synthetic-claim", "reason": "Owner request"}
        with pytest.raises(TimeoutError):
            await tool.ainvoke(arguments)
        assert "uncertain" in await tool.ainvoke(arguments)
        assert len(calls) == 1 and not await runtime.db.fetchall("SELECT * FROM approvals")
        assert (await runtime.db.fetchone("SELECT state FROM effects"))["state"] == "unknown"
    finally:
        active_task.reset(marker)


async def test_automatic_memory_grant_does_not_extend_to_other_tools_or_risks(runtime, monkeypatch):
    requested = []

    async def reject(ctx, name, arguments):
        requested.append(name)
        return False

    async def forbidden():
        raise AssertionError("A memory grant cannot authorize a different effect")

    monkeypatch.setattr(runtime.gateway, "approval", reject)
    ctx = TaskContext("bounded-memory", "Remember the fixture", "cloud", "personal", external_authorized=True)
    ctx.mark_untrusted()
    marker = active_task.set(ctx)
    try:
        for name, risk in [
            ("send_message", "external"), ("workspace_command", "command"),
            ("memory_remember", "external"), ("memory_change", "command"),
            ("mcp__second_brain__remember", "external"), ("mcp__other__remember", "external"),
        ]:
            assert (await runtime.gateway.invoke(name, {}, risk, forbidden))["state"] == "rejected"
        assert len(requested) == 6
    finally:
        active_task.reset(marker)
