import json
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from jarvis.api import create_app
from jarvis.daily import DailyPreferences
from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools


async def no_calendar(*args, **kwargs):
    return {"state": "not_configured", "events": []}


async def no_weather(*args, **kwargs):
    return {"state": "not_configured"}


async def test_today_is_read_only_scoped_and_keeps_source_failures(runtime, monkeypatch):
    monkeypatch.setattr(runtime.productivity, "calendar", no_calendar)

    async def broken(*args, **kwargs):
        raise RuntimeError("private provider credentials must not escape")

    monkeypatch.setattr(runtime.productivity, "weather", broken)
    for scope in ("personal", "work"):
        await runtime.db.execute(
            "INSERT INTO schedules(id,title,prompt,kind,expression,timezone,next_run_at,profile,scope,misfire_policy,created_at) "
            "VALUES(?,?,?,'at','fixture','UTC',?,'local_connected',?,'skip',?)",
            (scope, scope + " reminder", "", datetime.now(UTC).isoformat(), scope, datetime.now(UTC).isoformat()),
        )
    result = await runtime.daily.overview("work")
    assert [x["title"] for x in result["reminders"]] == ["work reminder"]
    assert result["calendar"]["state"] == "not_configured"
    assert result["weather"] == {"state": "unavailable", "error": "RuntimeError"}
    assert "credentials" not in json.dumps(result)
    assert not await runtime.db.fetchall("SELECT * FROM tasks")
    assert not await runtime.db.fetchall("SELECT * FROM daily_preferences")


async def test_today_strict_profile_never_contacts_remote_sources(runtime, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Strict local view contacted a remote source")
    monkeypatch.setattr(runtime.productivity, "weather", forbidden)
    monkeypatch.setattr(runtime.productivity, "calendar", forbidden)
    runtime.config.update({"calendar_provider": "google"})
    ctx = TaskContext("today-tool", "My day", "local_strict", "work", private=True)
    marker = active_task.set(ctx)
    try:
        tool = next(t for t in build_tools(runtime) if t.name == "today_overview")
        result = json.loads(await tool.ainvoke({}))
        assert result["calendar"]["state"] == result["weather"]["state"] == "offline"
        assert ctx.sensitive_context and ctx.untrusted_context
    finally:
        active_task.reset(marker)


async def test_daily_settings_create_update_delete_schedules_once_and_reject_stale(runtime):
    data = DailyPreferences(privacy_revision=0, morning=True, priorities=["Owner priority"])
    saved = await runtime.daily.save(data)
    assert saved["revision"] == 1
    with pytest.raises(ValueError, match="changed"):
        await runtime.daily.save(data)
    saved = await runtime.daily.save(data.model_copy(update={"revision": 1, "morning_time": "09:45"}))
    schedules = await runtime.db.fetchall("SELECT * FROM schedules")
    assert len(schedules) == 1 and schedules[0]["expression"] == "45 9 * * *"
    assert schedules[0]["misfire_policy"] == "skip" and not schedules[0]["call_authorized"]
    await runtime.daily.save(data.model_copy(update={"revision": 2, "morning": False}))
    assert not await runtime.db.fetchall("SELECT * FROM schedules")
    assert (await runtime.daily.preferences("work"))["priorities"] == []


async def test_daily_write_observes_private_emergency_and_scope_revision(runtime):
    data = DailyPreferences(privacy_revision=0)
    await runtime.set_voice_session(True, "personal")
    with pytest.raises(PermissionError, match="private"):
        await runtime.daily.save(data)
    await runtime.set_voice_session(False, "work")
    with pytest.raises(PermissionError, match="changed"):
        await runtime.daily.save(data)
    runtime.gateway.blocked = True
    with pytest.raises(PermissionError, match="Emergency"):
        await runtime.daily.save(data)
    assert not await runtime.db.fetchall("SELECT * FROM daily_preferences")


async def test_daily_sources_preserve_partial_calendar_and_exclude_tomorrow(runtime, monkeypatch):
    current = datetime.now(UTC)
    async def calendar(*args, **kwargs):
        return {"state": "ready", "truncated": True, "events": [{
            "id": "tomorrow", "title": "Tomorrow", "start": (current + timedelta(days=2)).isoformat(),
            "end": (current + timedelta(days=2, hours=1)).isoformat(),
        }, {"id": "uncertain", "title": "Uncertain", "start": "missing"}]}
    monkeypatch.setattr(runtime.productivity, "calendar", calendar)
    monkeypatch.setattr(runtime.productivity, "weather", no_weather)
    result = await runtime.daily.overview("personal")
    assert [e["id"] for e in result["calendar"]["events"]] == ["uncertain"]
    assert result["calendar"]["truncated"]


async def test_batch_rolls_back_all_changes_on_failure(runtime):
    with pytest.raises(sqlite3.OperationalError):
        await runtime.db.batch([
            ("INSERT INTO controls(name,value) VALUES('atomic-fixture','1')", ()),
            ("INSERT INTO absent_table VALUES(1)", ()),
        ])
    assert not await runtime.db.fetchone("SELECT * FROM controls WHERE name='atomic-fixture'")


async def test_today_api_authenticates_and_validates_scope(config, monkeypatch):
    app = create_app(config, start_scheduler=False, process_lock=False)
    monkeypatch.setattr(app.state.runtime.productivity, "calendar", no_calendar)
    monkeypatch.setattr(app.state.runtime.productivity, "weather", no_weather)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            assert (await client.get("/api/today")).status_code == 401
            headers = {"Authorization": "Bearer " + config.token}
            assert (await client.get("/api/today?scope=invalid", headers=headers)).status_code == 422
            assert (await client.get("/api/today?scope=work", headers=headers)).json()["scope"] == "work"
            assert (await client.put("/api/today/preferences", headers=headers, json={"privacy_revision": 0, "priorities": ["x"] * 4})).status_code == 422
