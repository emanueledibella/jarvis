import json
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.db import now
from jarvis.scheduler import ScheduleInput, next_due


async def test_private_events_only_exist_in_memory(runtime):
    secret = "private-transcript-example"
    await runtime.db.emit("assistant.delta", {"text": secret}, private=True)
    row = await runtime.db.fetchone("SELECT * FROM events WHERE type='assistant.delta'")
    assert secret not in row["data"]
    assert (await runtime.db.events(0))[-1]["data"]["text"] == secret
    runtime.db.volatile.clear()
    assert (await runtime.db.events(0))[-1]["data"] == {}


async def test_memory_delivery_reuses_id_after_ambiguous_failure(runtime, monkeypatch):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    seen = []

    async def call(server, tool, arguments, profile):
        seen.append((tool, arguments))
        if len(seen) == 1:
            raise TimeoutError("Response lost after remote commit")
        if tool == "remember":
            return {"status": "stored_pending_extraction", "source_id": "source-1", "revision": 2}
        return {"status": "indexed", "source_id": "source-1", "revision": 2}

    monkeypatch.setattr(runtime.mcp, "call", call)
    result = await runtime.memory.enqueue("Dato originale fornito dall'utente", "personal")
    await runtime.memory.tick()
    await runtime.db.execute("UPDATE memory_outbox SET next_attempt=?", (now(),))
    await runtime.memory.tick()
    assert seen[0][1]["request_id"] == seen[1][1]["request_id"] == result["outbox_id"]
    await runtime.db.execute("UPDATE memory_outbox SET next_attempt=?", (now(),))
    await runtime.memory.tick()
    assert seen[2][0] == "source_status"
    assert (await runtime.db.fetchone("SELECT state FROM memory_outbox"))["state"] == "indexed"


async def test_strict_profile_suspends_memory_delivery(runtime, monkeypatch):
    runtime.config.update({"second_brain_url": "http://127.0.0.1:8000/mcp"})
    await runtime.memory.enqueue("Dato in coda", "work")
    runtime.config.update({"profile": "local_strict"})

    async def forbidden(*args, **kwargs):
        pytest.fail("Strict mode must not deliver memory")

    monkeypatch.setattr(runtime.mcp, "call", forbidden)
    await runtime.memory.tick()
    assert (await runtime.db.fetchone("SELECT state FROM memory_outbox"))["state"] == "pending"


async def test_monitor_establishes_baseline_and_only_notifies_changes(runtime, monkeypatch):
    values = [3, 3, 4, 4]

    async def fetch(*args, **kwargs):
        return (
            "https://example.com",
            json.dumps({"value": values.pop(0)}).encode(),
            "application/json",
        )

    monkeypatch.setattr("jarvis.scheduler.fetch_public", fetch)
    created = await runtime.scheduler.create(
        ScheduleInput(
            title="Monitor",
            kind="interval",
            expression="60",
            mode="monitor",
            monitor={"url": "https://example.com", "json_path": "value", "operator": "changed"},
        )
    )
    results = []
    for _ in range(4):
        row = await runtime.db.fetchone("SELECT * FROM schedules WHERE id=?", (created["id"],))
        results.append((await runtime.scheduler.monitor(row))[1])
    assert results == [False, False, True, False]


async def test_reminder_is_claimed_once_without_a_model(runtime):
    created = await runtime.scheduler.create(
        ScheduleInput(title="Bere acqua", expression="tra 1 minuto")
    )
    due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await runtime.db.execute("UPDATE schedules SET next_run_at=? WHERE id=?", (due, created["id"]))
    await runtime.scheduler.tick()
    await runtime.scheduler.tick()
    runs = await runtime.db.fetchall("SELECT * FROM schedule_runs")
    assert len(runs) == 1 and runs[0]["state"] == "notified"
    assert len(await runtime.db.fetchall("SELECT * FROM notifications")) == 1
    assert not await runtime.db.fetchall("SELECT * FROM tasks")


async def test_missed_phone_call_is_never_replayed(runtime):
    created = await runtime.scheduler.create(
        ScheduleInput(
            title="Chiamata", expression="tra 1 minuto", notify="phone", call_authorized=True
        )
    )
    due = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    await runtime.db.execute("UPDATE schedules SET next_run_at=? WHERE id=?", (due, created["id"]))
    await runtime.scheduler.tick()
    assert (await runtime.db.fetchone("SELECT state FROM schedule_runs"))["state"] == "skipped"
    assert not await runtime.db.fetchall("SELECT * FROM calls")


def test_relative_date_and_dst():
    base = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    assert next_due("at", "tra 20 minuti", "Europe/Rome", base) == base + timedelta(minutes=20)
    # Daylight saving changes from UTC+2 to UTC+1 on 25 October 2026.
    due = next_due("cron", "0 9 * * *", "Europe/Rome", datetime(2026, 10, 25, 1, 1, tzinfo=UTC))
    assert due == datetime(2026, 10, 25, 8, tzinfo=UTC)


def test_phone_routine_requires_explicit_consent():
    with pytest.raises(ValueError):
        ScheduleInput(title="Call", expression="domani", notify="phone")
