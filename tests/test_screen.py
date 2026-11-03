import asyncio
import json
import time
from uuid import uuid4

import pytest

from jarvis.policy import TaskContext, active_task
from jarvis.screen import requested
from jarvis.tools import build_tools


def connected(runtime):
    runtime.native.update_status({"locked": False, "muted": False})


async def test_screen_capture_is_session_scoped_ephemeral_and_not_in_database(runtime, monkeypatch):
    connected(runtime)
    async def capture(operation, arguments, **kwargs):
        assert operation == "screen.capture" and kwargs["guard"]()
        return {"image": "fixture-image", "text": "Visible source", "confidence": .9}
    monkeypatch.setattr(runtime.native, "invoke", capture)
    session = uuid4()
    value = await runtime.screen.capture("personal", session, 0)
    assert "image" not in runtime.screen.read("personal", value["id"], session)
    for scope, identity in [("work", session), ("personal", uuid4())]:
        with pytest.raises(PermissionError):
            runtime.screen.read(scope, value["id"], identity)
    for table in ("documents", "messages", "events", "tasks"):
        assert "fixture-image" not in json.dumps(await runtime.db.fetchall("SELECT * FROM " + table))
    runtime.screen.captures[value["id"]]["expires"] = time.monotonic() - 1
    with pytest.raises(PermissionError, match="expired"):
        runtime.screen.read("personal", value["id"], session)


async def test_screen_discards_results_after_lock_privacy_and_emergency_changes(runtime, monkeypatch):
    connected(runtime)
    async def lock(*args, **kwargs):
        runtime.native.status["locked"] = True
        return {"image": "private", "text": "private"}
    monkeypatch.setattr(runtime.native, "invoke", lock)
    with pytest.raises(PermissionError, match="discarded"):
        await runtime.screen.capture("personal", uuid4(), 0)
    assert not runtime.screen.captures
    connected(runtime)
    async def change(*args, **kwargs):
        await runtime.set_voice_session(True, "personal")
        return {"image": "private", "text": "private"}
    monkeypatch.setattr(runtime.native, "invoke", change)
    with pytest.raises(PermissionError, match="discarded"):
        await runtime.screen.capture("personal", uuid4(), 0)
    runtime.gateway.blocked = True
    with pytest.raises(PermissionError):
        await runtime.screen.capture("personal", uuid4(), 1)


async def test_screen_tool_requires_current_owner_intent_and_rejects_background_tasks(runtime):
    tools = {tool.name: tool for tool in build_tools(runtime)}
    for prompt, event_id in [("Read my mail", None), ("Capture my screen", "event")]:
        ctx = TaskContext("screen-task", prompt, "local_connected", "personal", automation_run_id=event_id)
        marker = active_task.set(ctx)
        try:
            assert "foreground owner request" in await tools["screen_capture"].ainvoke({})
        finally:
            active_task.reset(marker)
    assert requested("Spiegami questo errore")
    assert requested("Explain this page on my screen")
    assert not requested("Read my agenda")


async def test_native_claim_and_completion_recheck_capture_authority(runtime):
    connected(runtime)
    allowed = True
    task = asyncio.create_task(runtime.native.invoke("screen.capture", {"secret": "image"}, guard=lambda: allowed))
    await asyncio.sleep(.02)
    key = next(iter(runtime.native.pending))
    operation = runtime.native.claim(key)
    assert operation["arguments"]["secret"] == "image"
    events = await runtime.db.events(0)
    assert all("image" not in json.dumps(event["data"]) for event in events)
    allowed = False
    runtime.native.complete(key, {"text": "private screen"})
    with pytest.raises(PermissionError, match="discarded"):
        await task
    assert not runtime.native.pending
