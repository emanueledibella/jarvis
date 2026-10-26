import pytest
from test_agent_policy import model_factory

from jarvis.policy import TaskContext, active_task


@pytest.mark.parametrize("channel", ["text", "live"])
async def test_named_city_weather_does_not_require_approval_after_conversation_history(runtime, monkeypatch, channel):
    seen = []

    async def weather(profile, location=None):
        seen.append((profile, location))
        return {"state": "ready", "current": {"temperature_2m": 18}}

    monkeypatch.setattr(runtime.productivity, "weather", weather)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    prior = await runtime.tasks.create("Tell me the time", channel=channel)
    await runtime.tasks.running[prior["id"]]
    monkeypatch.setattr(runtime.tasks, "model", model_factory("weather", {"location": "Fixture City"}))
    task = await runtime.tasks.create("What is the weather in Fixture City?", conversation_id=prior["conversation_id"], channel=channel)
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT state,error FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert len(seen) == 1 and seen[0][1] == "Fixture City"
    assert not await runtime.db.fetchall("SELECT * FROM approvals")


async def test_routine_context_does_not_remove_critical_action_or_export_approval(runtime, monkeypatch):
    requested = []

    async def deny(ctx, tool, arguments):
        requested.append(tool)
        return False

    async def harmless_weather():
        return {"temperature": 18}

    async def forbidden():
        raise AssertionError("Routine weather cannot authorize critical effects or private exports")

    monkeypatch.setattr(runtime.gateway, "approval", deny)
    ctx = TaskContext("fixture-routine", "Check the weather", "cloud", "personal", external_authorized=True)
    ctx.sensitive_context = True
    ctx.mark_untrusted(routine=True)
    marker = active_task.set(ctx)
    try:
        assert await runtime.gateway.invoke("weather", {"location": "Fixture City"}, "network_read", harmless_weather) == {"temperature": 18}
        assert ctx.untrusted_context and ctx.routine_context_only
        assert (await runtime.gateway.invoke("send_message", {}, "external", forbidden))["state"] == "rejected"
        assert (await runtime.gateway.invoke("web_search", {"query": "private fixture"}, "network_read", forbidden))["state"] == "rejected"
    finally:
        active_task.reset(marker)
    assert requested == ["send_message", "web_search"]


async def test_new_external_content_does_not_become_trusted_after_a_weather_result(runtime, monkeypatch):
    seen = []

    async def deny(ctx, tool, arguments):
        seen.append(tool)
        return False

    async def no_network():
        raise AssertionError("New external content cannot export private data through a city query")

    monkeypatch.setattr(runtime.gateway, "approval", deny)
    ctx = TaskContext("fixture-source", "Read a document", "cloud", "personal", sensitive_context=True, external_authorized=True)
    ctx.mark_untrusted(routine=True)
    ctx.mark_untrusted()
    ctx.mark_untrusted(routine=True)
    assert ctx.untrusted_context and not ctx.routine_context_only
    marker = active_task.set(ctx)
    try:
        result = await runtime.gateway.invoke("weather", {"location": "private fixture"}, "network_read", no_network)
        assert result["state"] == "rejected" and not ctx.routine_context_only
    finally:
        active_task.reset(marker)
    assert seen == ["weather"]


@pytest.mark.parametrize("location", ["https://example.invalid/?data=fixture", "Fixture\nprivate document", "X" * 121])
async def test_weather_city_argument_is_bounded_and_cannot_be_an_arbitrary_export(runtime, monkeypatch, location):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Invalid place labels must never reach a network service")

    monkeypatch.setattr("jarvis.productivity.fetch_public", forbidden)
    with pytest.raises(ValueError, match="Location not found"):
        await runtime.productivity.weather("cloud", location)
