from datetime import UTC, datetime, timedelta

import httpx
import pytest
from icalendar import Calendar, Event
from langchain_core.messages import HumanMessage

from jarvis.agent import TokenEvents
from jarvis.api import create_app
from jarvis.policy import TaskContext, active_task
from jarvis.speech import speech_text
from jarvis.tools import build_tools, calendar_payload


def test_microsoft_dates_are_converted_to_utc():
    payload = calendar_payload(
        "microsoft", "Riunione", "2026-10-24T15:00:00+02:00", "2026-10-24T16:00:00+02:00"
    )
    assert payload["start"] == {"dateTime": "2026-10-24T13:00:00", "timeZone": "UTC"}
    with pytest.raises(ValueError):
        calendar_payload("google", "Invalid", "2026-10-24T15:00:00", "2026-10-24T16:00:00")


async def test_ics_expands_exceptions_without_duplicates(runtime, monkeypatch):
    first = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    calendar = Calendar()
    event = Event()
    event.add("uid", "series-1")
    event.add("summary", "Standup")
    event.add("dtstart", first)
    event.add("dtend", first + timedelta(hours=1))
    event.add("rrule", {"freq": "daily", "count": 3})
    event.add("exdate", first + timedelta(days=1))
    calendar.add_component(event)
    moved = Event()
    moved.add("uid", "series-1")
    moved.add("recurrence-id", first + timedelta(days=2))
    moved.add("summary", "Orario spostato")
    moved.add("dtstart", first + timedelta(days=2, hours=4))
    moved.add("dtend", first + timedelta(days=2, hours=5))
    calendar.add_component(moved)

    async def fetch(*args, **kwargs):
        return "https://example.com/feed.ics", calendar.to_ical(), "text/calendar"

    monkeypatch.setattr("jarvis.productivity.fetch_public", fetch)
    runtime.config.update(
        {"calendar_provider": "ics", "calendar_ics_url": "https://example.com/feed.ics"}
    )
    result = await runtime.productivity.calendar("local_connected")
    assert len(result["events"]) == 2
    assert [e["title"] for e in result["events"]] == ["Standup", "Orario spostato"]
    assert datetime.fromisoformat(result["events"][1]["start"]) == first + timedelta(
        days=2, hours=4
    )


async def test_do_not_remember_is_enforced_by_tool(runtime):
    context = TaskContext(
        "task", "Non ricordare questo: il dato personale", "local_connected", "personal"
    )
    marker = active_task.set(context)
    try:
        tool = next(t for t in build_tools(runtime) if t.name == "memory_remember")
        result = await tool.ainvoke({"text": "il dato personale"})
        assert "does not allow" in result
        assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")
    finally:
        active_task.reset(marker)


def test_spoken_code_and_urls_are_removed_without_changing_language():
    text = speech_text(
        "Risultato.\n```python\nprint('hello')\n```\nFonte: [documentazione](https://example.com)."
    )
    assert "print" not in text and "https://" not in text
    assert text == "Risultato. Fonte: documentazione."


async def test_cloud_callback_enforces_budget_before_generation(runtime):
    from test_agent_policy import ScriptedToolModel

    runtime.config.update(
        {
            "monthly_budget_usd": 0.01,
            "model_input_usd_per_million": 100,
            "model_output_usd_per_million": 100,
        }
    )
    callback = TokenEvents(
        runtime.db, TaskContext("task", "test", "cloud", "personal"), runtime.budget, cloud=True
    )
    with pytest.raises(ValueError, match="budget"):
        await ScriptedToolModel().ainvoke(
            [HumanMessage(content="test")], config={"callbacks": [callback]}
        )
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_retention_removes_task_content_and_checkpoints(runtime, monkeypatch):
    from test_agent_policy import model_factory

    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    task = await runtime.tasks.create("Prompt storico da rimuovere")
    await runtime.tasks.running[task["id"]]
    assert await runtime.tasks.checkpointer.aget_tuple({"configurable": {"thread_id": task["id"]}})
    await runtime.db.execute("UPDATE tasks SET updated_at='2020-01-01T00:00:00+00:00'")
    await runtime.db.execute("UPDATE messages SET created_at='2020-01-01T00:00:00+00:00'")
    await runtime.maintenance()
    row = await runtime.db.fetchone("SELECT * FROM tasks")
    assert row["prompt"] == row["result"] == ""
    assert not await runtime.db.fetchall("SELECT * FROM messages")
    assert not await runtime.tasks.checkpointer.aget_tuple(
        {"configurable": {"thread_id": task["id"]}}
    )


async def test_calendar_rotation_survives_restart_with_env_seed(config, monkeypatch):
    from jarvis.productivity import Productivity

    config.env_file.write_text("JARVIS_CALENDAR_REFRESH_TOKEN=original-env-token\n")
    config.update({"calendar_provider": "microsoft", "calendar_client_id": "client-fixture"})
    seen = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, data):
            seen.append(data["refresh_token"])
            return httpx.Response(
                200,
                json={
                    "access_token": f"access-{len(seen)}",
                    "refresh_token": f"rotated-{len(seen)}",
                    "expires_in": 3600,
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("jarvis.productivity.httpx.AsyncClient", Client)
    assert await Productivity(config, None).calendar_token() == "access-1"
    assert await Productivity(config, None).calendar_token() == "access-2"
    assert seen == ["original-env-token", "rotated-1"]
    assert config.settings.secret("calendar_refresh_token") == "original-env-token"
    from test_platforms import assert_private_file

    assert_private_file(config.data_dir / "calendar-oauth.json")


@pytest.mark.parametrize(
    ("credential", "provider_status", "provider_error", "dashboard_state", "today_state"),
    [
        ("refresh", 400, "invalid_grant", "reauthorization_required", "reauthorization_required"),
        ("access", 401, "authError", "reauthorization_required", "reauthorization_required"),
        ("refresh", 400, "invalid_client", "error", "unavailable"),
        ("refresh", 503, "temporarily_unavailable", "error", "unavailable"),
    ],
)
async def test_calendar_views_distinguish_unauthorized_access_from_provider_failures(
    config, monkeypatch, credential, provider_status, provider_error, dashboard_state, today_state
):
    config.update({"calendar_provider": "google", f"calendar_{credential}_token": "fixture-calendar-token"})
    app = create_app(config, start_scheduler=False, process_lock=False)
    http_client = httpx.AsyncClient

    def google(request):
        if credential == "refresh":
            assert (request.method, request.url.host) == ("POST", "oauth2.googleapis.com")
        else:
            assert (request.method, request.url.host) == ("GET", "www.googleapis.com")
        return httpx.Response(provider_status, json={
            "error": provider_error, "error_description": "private-provider-diagnostics",
        })

    monkeypatch.setattr(
        "jarvis.productivity.httpx.AsyncClient",
        lambda **kwargs: http_client(transport=httpx.MockTransport(google), **kwargs),
    )
    async with app.router.lifespan_context(app):
        async with http_client(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client:
            for path, expected in (("/api/dashboard", dashboard_state), ("/api/today", today_state)):
                response = await client.get(path)
                assert response.status_code == 200
                calendar = response.json()["calendar"]
                assert calendar["state"] == expected
                assert "private-provider-diagnostics" not in response.text
                assert "fixture-calendar-token" not in response.text
                if expected == "reauthorization_required":
                    assert calendar["events"] == []
                    assert "Authorize the calendar again" in calendar["message"]


async def test_calendar_refreshes_a_rejected_access_token_and_retries_read(runtime, monkeypatch):
    runtime.config.update({"calendar_provider": "google", "calendar_refresh_token": "fixture-refresh"})
    http_client = httpx.AsyncClient
    reads = []
    refreshes = 0

    def google(request):
        nonlocal refreshes
        if request.method == "POST":
            refreshes += 1
            return httpx.Response(200, json={"access_token": f"fixture-access-{refreshes}"})
        reads.append(request.headers["Authorization"])
        if reads[-1] == "Bearer fixture-access-1":
            return httpx.Response(401)
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(
        "jarvis.productivity.httpx.AsyncClient",
        lambda **kwargs: http_client(transport=httpx.MockTransport(google), **kwargs),
    )
    result = await runtime.productivity.calendar("local_connected")
    assert result["state"] == "ready"
    assert reads == ["Bearer fixture-access-1", "Bearer fixture-access-2"]
    assert await runtime.productivity.calendar_token() == "fixture-access-2"
