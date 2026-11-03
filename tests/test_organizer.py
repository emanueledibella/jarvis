import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from jarvis.api import create_app
from jarvis.organizer import ActivityData, PlanInput, ProjectData
from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools


async def test_activities_are_scoped_revisioned_and_cycle_safe(runtime):
    project = await runtime.organizer.project("work", ProjectData(name="Work project"))
    parent = await runtime.organizer.save("work", ActivityData(title="Parent", project_id=project["id"]))
    with pytest.raises(ValueError, match="scope"):
        await runtime.organizer.save("personal", ActivityData(title="Cross scope", project_id=project["id"]))
    with pytest.raises(ValueError, match="scope"):
        await runtime.organizer.save("personal", ActivityData(title="Cross scope", parent_id=parent["id"]))
    child = await runtime.organizer.save("work", ActivityData(title="Child", parent_id=parent["id"]))
    with pytest.raises(ValueError, match="cycle"):
        await runtime.organizer.save("work", ActivityData(title="Parent", parent_id=child["id"]), parent["id"], 1)
    assert not (await runtime.organizer.listing("personal"))["activities"]
    results = await asyncio.gather(*[
        runtime.organizer.save("work", ActivityData(title=title), child["id"], 1)
        for title in ("First", "Second")
    ], return_exceptions=True)
    assert sum(isinstance(x, ValueError) for x in results) == 1
    assert (await runtime.organizer.record("work", child["id"]))["revision"] == 2


async def test_activity_deletion_requires_cascade_and_project_deletion_keeps_work(runtime):
    project = await runtime.organizer.project("personal", ProjectData(name="Project"))
    parent = await runtime.organizer.save("personal", ActivityData(title="Parent", project_id=project["id"]))
    child = await runtime.organizer.save("personal", ActivityData(title="Child", parent_id=parent["id"], project_id=project["id"]))
    with pytest.raises(ValueError, match="cascade"):
        await runtime.organizer.remove("personal", parent["id"], 1)
    await runtime.organizer.remove("personal", project["id"], 1, project=True)
    assert (await runtime.organizer.record("personal", child["id"]))["project_id"] is None
    await runtime.organizer.remove("personal", parent["id"], 2, cascade=True)
    assert not (await runtime.organizer.listing("personal"))["activities"]


@pytest.mark.parametrize("field,value", [
    ("title", " "), ("due_at", "2026-11-01T10:00:00"), ("priority", 99),
    ("source_url", "javascript:alert(1)"), ("source_url", "https://secret:password@example.com"),
    ("estimated_minutes", 0),
])
def test_activity_inputs_reject_unsafe_or_ambiguous_values(field, value):
    with pytest.raises(ValidationError):
        ActivityData(**{"title": "Valid", field: value})


async def test_activities_plan_uses_verified_busy_intervals_and_never_creates_events(runtime, monkeypatch):
    first = (datetime.now(UTC) + timedelta(hours=1)).replace(second=0, microsecond=0)
    async def calendar(*args, **kwargs):
        return {"state": "ready", "events": [
            {"title": "Busy", "start": (first + timedelta(minutes=20)).isoformat(), "end": (first + timedelta(minutes=50)).isoformat()},
            {"title": "Free", "start": first.isoformat(), "end": (first + timedelta(hours=2)).isoformat(), "availability": "free"},
        ]}
    monkeypatch.setattr(runtime.productivity, "calendar", calendar)
    item = await runtime.organizer.save("personal", ActivityData(title="Work", estimated_minutes=30))
    data = PlanInput(start=first, end=first + timedelta(hours=2), activity_ids=[item["id"]])
    result = await runtime.organizer.plan(data, "local_connected")
    assert result["state"] == "proposed"
    assert datetime.fromisoformat(result["proposals"][0]["start"]) == first + timedelta(minutes=50)
    assert not await runtime.db.fetchall("SELECT * FROM effects")
    async def partial(*args, **kwargs):
        return {"state": "ready", "truncated": True, "events": []}
    monkeypatch.setattr(runtime.productivity, "calendar", partial)
    assert (await runtime.organizer.plan(data, "local_connected"))["state"] == "unverified"
    with pytest.raises(ValueError, match="scope"):
        await runtime.organizer.plan(data.model_copy(update={"scope": "work"}), "local_connected")


async def test_private_activity_tool_cannot_persist_and_scoped_list_marks_untrusted(runtime):
    ctx = TaskContext("private-organizer", "Create task", "local_connected", "personal", private=True, external_authorized=True)
    marker = active_task.set(ctx)
    try:
        tools = {tool.name: tool for tool in build_tools(runtime)}
        result = await tools["activity_save"].ainvoke({"title": "Do not persist"})
        assert "private" in result
        assert not await runtime.db.fetchall("SELECT * FROM activities")
        await tools["organizer_list"].ainvoke({})
        assert ctx.sensitive_context and ctx.untrusted_context
    finally:
        active_task.reset(marker)


async def test_activity_tool_effect_is_not_repeated(runtime):
    ctx = TaskContext("organizer-write", "Create an activity", "local_connected", "work", external_authorized=True)
    marker = active_task.set(ctx)
    try:
        tool = next(tool for tool in build_tools(runtime) if tool.name == "activity_save")
        first = json.loads(await tool.ainvoke({"title": "One activity"}))
        second = json.loads(await tool.ainvoke({"title": "One activity"}))
        assert first["id"] == second["id"]
        assert len((await runtime.organizer.listing("work"))["activities"]) == 1
    finally:
        active_task.reset(marker)


async def test_organizer_api_checks_auth_private_scope_revision_and_emergency(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            assert (await client.get("/api/organizer")).status_code == 401
            headers = {"Authorization": "Bearer " + config.token}
            payload = {"title": "Activity", "privacy_revision": 0}
            response = await client.post("/api/organizer/activities", headers=headers, json=payload)
            assert response.status_code == 200
            item = response.json()
            assert (await client.get("/api/organizer?scope=work", headers=headers)).json()["activities"] == []
            await app.state.runtime.set_voice_session(True, "personal")
            assert (await client.post("/api/organizer/activities", headers=headers, json=payload)).status_code == 403
            await app.state.runtime.set_voice_session(False, "personal")
            assert (await client.request("DELETE", "/api/organizer/activities/" + item["id"], headers=headers, json={"privacy_revision": 0, "revision": 1})).status_code == 403
            app.state.runtime.gateway.blocked = True
            assert (await client.post("/api/organizer/activities", headers=headers, json={**payload, "privacy_revision": 2})).status_code == 403
