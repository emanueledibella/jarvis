import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from test_agent_policy import model_factory

from jarvis.calendar_assistant import CALENDAR_POLICY, CALENDAR_VOICE_POLICY, calendar_briefing

NOW = datetime(2026, 10, 27, 8, tzinfo=UTC)


def event(title, start, end, **extra):
    return {"id": title, "title": title, "start": start, "end": end, **extra}


def briefing(events, **extra):
    return calendar_briefing({"state": "ready", "events": events, **extra}, "Europe/Rome", now=NOW)


def test_next_event_is_distinct_from_ongoing_and_reports_simultaneous_starts():
    result = briefing([
        event("In corso", "2026-10-27T07:30:00Z", "2026-10-27T08:30:00Z"),
        event("Riunione", "2026-10-27T09:00:00Z", "2026-10-27T10:00:00Z"),
        event("Lezione", "2026-10-27T09:00:00Z", "2026-10-27T09:30:00Z"),
    ])
    analysis = result["analysis"]
    assert analysis["ongoing_event_indexes"] == [0]
    assert analysis["next_event_indexes"] == analysis["imminent_event_indexes"] == [1, 2]
    assert analysis["now"] == "2026-10-27T09:00:00+01:00"
    assert result["events"][1]["start"] == "2026-10-27T10:00:00+01:00"
    assert analysis["minutes_until_start"] == {"0": -30, "1": 60, "2": 60}
    assert analysis["conflicts"] == [{
        "event_indexes": [1, 2], "start": "2026-10-27T10:00:00+01:00",
        "end": "2026-10-27T10:30:00+01:00", "tentative": False,
    }]


def test_touching_events_and_short_gaps_are_not_overlaps():
    result = briefing([
        event("Primo", "2026-10-27T09:00:00Z", "2026-10-27T10:00:00Z", location="Roma"),
        event("Secondo", "2026-10-27T10:00:00Z", "2026-10-27T11:00:00Z", location="Milano"),
        event("Terzo", "2026-10-27T11:10:00Z", "2026-10-27T12:00:00Z"),
    ])
    assert result["analysis"]["conflicts"] == []
    assert result["analysis"]["short_gaps"] == [
        {"event_indexes": [0, 1], "minutes": 0, "different_locations": True},
        {"event_indexes": [1, 2], "minutes": 10, "different_locations": False},
    ]


def test_all_day_free_declined_canceled_and_duplicate_entries_do_not_create_false_conflicts():
    first = event("Occupato", "2026-10-27T09:00:00Z", "2026-10-27T10:00:00Z")
    overlapping = [
        event("Libero", first["start"], first["end"], availability="free"),
        event("Trasparente", first["start"], first["end"], transparency="transparent"),
        event("Rifiutato", first["start"], first["end"], response_status="declined"),
        event("Cancellato", first["start"], first["end"], status="cancelled"),
        event("Tutto il giorno", "2026-10-27", "2026-10-28", all_day=True),
    ]
    result = briefing([first, first.copy(), *overlapping])
    assert len(result["events"]) == 6
    assert result["analysis"]["conflict_count"] == 0
    assert result["analysis"]["next_event_indexes"] == [0, 1, 2]
    assert result["analysis"]["all_day_event_indexes"] == [5]


def test_tentative_conflict_and_nested_intervals_are_preserved():
    result = briefing([
        event("Lungo", "2026-10-27T08:00:00Z", "2026-10-27T12:00:00Z"),
        event("Breve", "2026-10-27T09:00:00Z", "2026-10-27T09:30:00Z", availability="tentative"),
        event("Successivo", "2026-10-27T11:00:00Z", "2026-10-27T12:30:00Z"),
    ])
    assert [c["event_indexes"] for c in result["analysis"]["conflicts"]] == [[0, 1], [0, 2]]
    assert [c["tentative"] for c in result["analysis"]["conflicts"]] == [True, False]


def test_google_and_microsoft_time_shapes_normalize_to_the_same_local_interval():
    result = briefing([
        event("Google", "2026-10-27T10:00:00+01:00", {"dateTime": "2026-10-27T11:00:00+01:00"}),
        event("Microsoft", {"dateTime": "2026-10-27T09:00:00.0000000", "timeZone": "UTC"},
              {"dateTime": "2026-10-27T10:00:00.0000000", "timeZone": "UTC"}),
    ])
    assert result["events"][0]["start"] == result["events"][1]["start"]
    assert result["events"][0]["end"] == result["events"][1]["end"]
    assert result["analysis"]["next_event_indexes"] == [0, 1]
    assert result["analysis"]["conflict_count"] == 1


@pytest.mark.parametrize("start", [
    "2026-10-27T10:00:00", "bad-date",
    {"dateTime": "2026-10-25T02:30:00", "timeZone": "Europe/Rome"},
    {"dateTime": "2026-03-29T02:30:00", "timeZone": "Europe/Rome"},
    {"dateTime": "2026-10-27T10:00:00", "timeZone": "Unknown/Zone"},
])
def test_unverified_floating_ambiguous_and_invalid_times_never_become_confirmed_availability(start):
    result = briefing([event("Orario incerto", start, None)])
    assert result["analysis"]["state"] == "partial"
    assert result["analysis"]["unverified_event_indexes"] == [0]
    assert result["analysis"]["conflicts"] == []


def test_dst_fold_uses_elapsed_minutes_instead_of_wall_clock_subtraction():
    result = calendar_briefing({"state": "ready", "events": [
        event("Dopo il cambio", "2026-10-25T02:15:00+01:00", "2026-10-25T03:00:00+01:00"),
    ]}, "Europe/Rome", now=datetime(2026, 10, 25, 0, 45, tzinfo=UTC))
    assert result["analysis"]["now"] == "2026-10-25T02:45:00+02:00"
    assert result["analysis"]["minutes_until_start"] == {"0": 30}
    assert result["analysis"]["imminent_event_indexes"] == [0]


def test_urgency_requires_an_explicit_signal_and_proximity_is_separate():
    events = [event(title, "2026-10-27T08:30:00Z", "2026-10-27T09:00:00Z", **extra)
              for title, extra in [
                  ("Riunione", {}), ("Esame", {}), ("Non urgente", {}),
                  ("[URGENTE] Scadenza", {}), ("Pratica", {"importance": "high"}),
              ]]
    result = briefing(events)["analysis"]
    assert result["imminent_event_indexes"] == [0, 1, 2, 3, 4]
    assert result["urgent_events"] == [
        {"event_index": 3, "evidence": "urgent_title_label"},
        {"event_index": 4, "evidence": "provider_priority"},
    ]


def test_unavailable_empty_and_partial_calendars_remain_distinct():
    assert briefing([])["analysis"]["state"] == "ready"
    for state in ("not_configured", "unavailable", "error"):
        assert calendar_briefing({"state": state, "events": []}, "Europe/Rome", now=NOW)["analysis"]["state"] == "unavailable"
    for flags in ({"truncated": True}, {"stale": True}):
        assert briefing([], **flags)["analysis"]["state"] == "partial"
    result = briefing([event("Senza fine", "2026-10-27T08:30:00Z", None)])
    assert result["analysis"]["next_event_indexes"] == [0]
    assert result["analysis"]["state"] == "partial"


def test_large_agenda_retains_analysis_instead_of_a_clipped_json_preview():
    events = [event(str(i), (NOW + timedelta(minutes=i)).isoformat(),
                    (NOW + timedelta(minutes=i + 60)).isoformat(), location="x" * 1000)
              for i in range(200)]
    result = briefing(events)
    assert len(json.dumps(result, ensure_ascii=False)) <= 30000
    preview = json.dumps(result, ensure_ascii=False)[:16000]
    prefix = '{"analysis": '
    assert preview.startswith(prefix)
    visible_analysis, _ = json.JSONDecoder().raw_decode(preview[len(prefix):])
    assert visible_analysis == result["analysis"]
    assert result["truncated"] is True
    assert result["analysis"]["state"] == "partial"
    assert result["analysis"]["conflict_count"] > len(result["analysis"]["conflicts"]) == 20
    assert result["analysis"]["next_event_indexes"] == [1]
    for conflict in result["analysis"]["conflicts"]:
        assert all(index < len(result["events"]) for index in conflict["event_indexes"])


def test_existing_apple_bridge_limit_is_treated_as_partial_coverage():
    events = [event(str(i), "2026-10-27", "2026-10-28", all_day=True) for i in range(200)]
    result = briefing(events, provider="apple")
    assert result["truncated"] is True
    assert result["analysis"]["state"] == "partial"


@pytest.mark.parametrize("channel", ["text", "live", "phone"])
async def test_calendar_specialist_policy_and_real_tool_analysis_are_shared_across_channels(runtime, monkeypatch, channel):
    from jarvis import agent
    from jarvis.voice_style import voice_instructions

    runtime.config.update({"calendar_provider": "apple"})
    start = datetime.now(UTC) + timedelta(minutes=30)
    end = start + timedelta(hours=1)
    native = AsyncMock(return_value={"state": "ready", "events": [
        event("Primo", start.isoformat(), end.isoformat()),
        event("Secondo", start.isoformat(), end.isoformat()),
    ]})
    monkeypatch.setattr(runtime.native, "invoke", native)
    monkeypatch.setattr(runtime.tasks, "model", model_factory("calendar_events", {"days": 1}))
    captured = []
    create_agent = agent.create_deep_agent

    def capture_agent(**kwargs):
        captured.append(kwargs["system_prompt"])
        return create_agent(**kwargs)

    monkeypatch.setattr(agent, "create_deep_agent", capture_agent)
    task = await runtime.tasks.create("Qual è il prossimo evento in calendario?", channel=channel)
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    result = json.loads(row["result"].removeprefix("Verified outcome: "))
    assert result["analysis"]["next_event_indexes"] == [0, 1]
    assert result["analysis"]["imminent_event_indexes"] == [0, 1]
    assert result["analysis"]["conflict_count"] == 1
    assert CALENDAR_POLICY in captured[0]
    assert CALENDAR_VOICE_POLICY in voice_instructions(runtime.config.settings)
    native.assert_awaited_once_with("calendar.list", {"days": 1})


@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_cloud_calendar_preserves_free_declined_and_priority_metadata(runtime, monkeypatch, provider):
    runtime.config.update({"calendar_provider": provider, "calendar_access_token": "synthetic-test-token"})
    item = {
        "id": "fixture", "summary": "Google", "subject": "Microsoft",
        "start": {"dateTime": "2026-10-27T09:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-27T10:00:00", "timeZone": "UTC"},
        "transparency": "transparent", "showAs": "free", "importance": "high",
        "attendees": [{"self": True, "responseStatus": "declined"}],
        "responseStatus": {"response": "declined"},
    }

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return httpx.Response(200, json={"items" if provider == "google" else "value": [item]},
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr("jarvis.productivity.httpx.AsyncClient", Client)
    result = await runtime.productivity.calendar("cloud")
    saved = result["events"][0]
    assert saved["availability"] == "free" and saved["transparency"] == "transparent"
    assert saved["response_status"] == "declined" and saved["importance"] == "high"
