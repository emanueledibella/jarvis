import io
import os
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from defusedxml.common import DefusedXmlException

from jarvis.api import create_app
from jarvis.apple_health import HealthConsent, NativeHealthImport
from jarvis.health_parser import parse_export
from jarvis.policy import TaskContext, active_task


def native_snapshot():
    day = datetime.now(UTC).date().isoformat()
    return {"scope": "personal", "privacy_revision": 0, "revision": 0, "snapshot": {
        "version": 1, "first_date": day, "last_date": day, "timezone": "UTC",
        "collected_at": datetime.now(UTC).isoformat(), "metrics": ["steps"], "records_scanned": 2,
        "rows": [{"date": day, "metric": "steps", "source": "Synthetic iPhone", "source_id": "1" * 24,
                  "value": 100.0, "min": 40.0, "max": 60.0, "count": 2, "unit": "count", "aggregation": "sum"}]}}


async def test_native_sharing_is_revisioned_idempotent_and_preserves_cloud_guard(runtime):
    request = NativeHealthImport.model_validate(native_snapshot())
    result = await runtime.apple_health.import_native(request)
    assert result["source"] == "Apple HealthKit (iOS companion)"
    assert result["revision"] == 1 and result["allow_cloud"] is False
    with pytest.raises(ValueError, match="changed"):
        await runtime.apple_health.import_native(request)
    assert (await runtime.apple_health.import_native(request.model_copy(update={"revision": 1})))["state"] == "unchanged"
    ctx = TaskContext(str(uuid4()), "Steps", "cloud", "personal")
    token = active_task.set(ctx)
    try:
        day = request.snapshot.first_date
        with pytest.raises(PermissionError, match="cloud models"):
            await runtime.apple_health.summary("personal", day, day, model_access=True)
    finally:
        active_task.reset(token)
    await runtime.set_voice_session(True, "personal")
    with pytest.raises(PermissionError, match="private"):
        await runtime.apple_health.import_native(request.model_copy(update={"revision": 1}))
    assert runtime.apple_health.load()["revision"] == 1


@pytest.mark.parametrize("change", ["unit", "metric", "window", "duplicate", "nan", "negative", "timezone", "raw", "empty", "old", "aggregate"])
def test_native_snapshot_rejects_unbounded_or_inconsistent_evidence(change):
    from pydantic import ValidationError

    data = native_snapshot()
    snapshot = data["snapshot"]
    row = snapshot["rows"][0]
    if change == "unit":
        row["unit"] = "miles"
    elif change == "metric":
        row["metric"] = "heart_rate"
    elif change == "window":
        snapshot["first_date"] = "2020-01-01"
    elif change == "duplicate":
        snapshot["rows"].append(dict(row))
    elif change == "nan":
        row["value"] = float("nan")
    elif change == "negative":
        row["value"] = -1.0
    elif change == "timezone":
        snapshot["timezone"] = "Not/A_Zone"
    elif change == "raw":
        snapshot["raw_samples"] = []
    elif change == "empty":
        snapshot["rows"] = []
    elif change == "old":
        snapshot["collected_at"] = "2020-01-01T00:00:00Z"
    elif change == "aggregate":
        row["min"] = 200.0
    with pytest.raises(ValidationError):
        NativeHealthImport.model_validate(data)


async def test_native_api_requires_auth_and_never_imports_in_work_scope(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        data = native_snapshot()
        assert (await client.post("/api/apple-health/native", json=data)).status_code == 401
        client.headers["Authorization"] = "Bearer " + config.token
        assert (await client.post("/api/apple-health/native", json={**data, "scope": "work"})).status_code == 403
        response = await client.post("/api/apple-health/native", json=data)
        assert response.status_code == 200, response.text
        assert (await client.post("/api/apple-health/native", json=data)).status_code == 400
        day = data["snapshot"]["first_date"]
        result = (await client.get(f"/api/apple-health/summary?start={day}&end={day}")).json()
        assert result["rows"][0]["value"] == 100


def export_xml():
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    def record(kind, source, value, unit="count", begin="12:00:00", end="12:01:00"):
        return f'<Record type="{kind}" sourceName="{source}" value="{value}" unit="{unit}" startDate="{day} {begin} +0000" endDate="{day} {end} +0000"/>'
    step = record("HKQuantityTypeIdentifierStepCount", "Phone", 100)
    return ("<HealthData>" + step + step
            + record("HKQuantityTypeIdentifierStepCount", "Watch", 200)
            + record("HKQuantityTypeIdentifierHeartRate", "Watch", 70, "count/min")
            + record("HKQuantityTypeIdentifierHeartRate", "Watch", 90, "count/min", end="12:02:00")
            + record("HKCategoryTypeIdentifierSleepAnalysis", "Watch", "HKCategoryValueSleepAnalysisAsleepCore", "", "01:00:00", "04:00:00")
            + record("HKCategoryTypeIdentifierSleepAnalysis", "Watch", "HKCategoryValueSleepAnalysisAsleepDeep", "", "02:00:00", "03:00:00")
            + "</HealthData>").encode()


def test_export_separates_sources_deduplicates_and_unions_sleep():
    data = parse_export(export_xml(), "Europe/Rome")
    steps = [r for r in data["rows"] if r["metric"] == "steps"]
    assert [(r["source"], r["value"]) for r in steps] == [("Phone", 100), ("Watch", 200)]
    heart = next(r for r in data["rows"] if r["metric"] == "heart_rate")
    assert (heart["value"], heart["min"], heart["max"], heart["count"]) == (80, 70, 90, 2)
    assert next(r for r in data["rows"] if r["metric"] == "sleep_minutes")["value"] == 180
    assert data["records_skipped"] == 1
    assert len(data["warnings"]) == 2


def test_zip_xml_entities_wrong_root_and_ambiguous_exports():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apple_health_export/export.xml", export_xml())
    assert parse_export(data.getvalue(), "Europe/Rome")["rows"]
    with pytest.raises(DefusedXmlException):
        parse_export(b'<!DOCTYPE HealthData [<!ENTITY x SYSTEM "file:///etc/passwd">]><HealthData>&x;</HealthData>', "UTC")
    with pytest.raises(ValueError, match="not an Apple"):
        parse_export(b"<notHealth/>", "UTC")
    with pytest.raises(ValueError, match="No supported"):
        parse_export(b"<HealthData/>", "UTC")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("../../export.xml", export_xml())
    with pytest.raises(ValueError, match="exactly one"):
        parse_export(data.getvalue(), "UTC")


async def test_import_consent_cloud_reads_revision_and_delete(runtime, monkeypatch):
    async def parser(raw, days):
        return parse_export(raw, "Europe/Rome", days)
    monkeypatch.setattr(runtime.lab, "parse_health", parser)
    imported = await runtime.apple_health.import_export(export_xml(), 90, 0)
    assert imported["revision"] == 1 and imported["allow_cloud"] is False
    assert (await runtime.apple_health.import_export(export_xml(), 90, 0))["state"] == "unchanged"
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    with pytest.raises(PermissionError):
        await runtime.apple_health.summary("work", day, day)
    ctx = TaskContext(str(uuid4()), "My steps", "cloud", "personal")
    token = active_task.set(ctx)
    try:
        with pytest.raises(PermissionError, match="cloud models"):
            await runtime.apple_health.summary("personal", day, day, model_access=True)
        await runtime.apple_health.consent(HealthConsent(privacy_revision=0, revision=1, allow_cloud=True))
        result = await runtime.apple_health.summary("personal", day, day, "steps", model_access=True)
        assert len(result["rows"]) == 2 and result["source_id"] == imported["id"]
        with pytest.raises(ValueError, match="changed"):
            await runtime.apple_health.consent(HealthConsent(privacy_revision=0, revision=1, allow_cloud=False))
    finally:
        active_task.reset(token)
    await runtime.apple_health.delete("personal", 0, 2)
    assert runtime.apple_health.status("personal") == {"revision": 3, "allow_cloud": False}


async def test_private_stale_and_emergency_import_never_persists(runtime, monkeypatch):
    async def parser(*args):
        await runtime.set_voice_session(True, "personal")
        return parse_export(export_xml(), "UTC")
    monkeypatch.setattr(runtime.lab, "parse_health", parser)
    with pytest.raises(PermissionError):
        await runtime.apple_health.import_export(export_xml(), 90, 0)
    assert not (runtime.config.data_dir / "apple-health.json").exists()


async def test_multipart_health_api_auth_and_personal_scope(config, monkeypatch):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async def parser(raw, days):
        return parse_export(raw, "Europe/Rome", days)
    monkeypatch.setattr(app.state.runtime.lab, "parse_health", parser)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/api/apple-health")).status_code == 401
        client.headers["Authorization"] = "Bearer " + config.token
        response = await client.post("/api/apple-health/import?privacy_revision=0&days=90&scope=personal",
                                     files={"export": ("export.xml", export_xml(), "application/xml")})
        assert response.status_code == 200, response.text
        assert (await client.get("/api/apple-health?scope=work")).status_code == 403
        assert (await client.post("/api/apple-health/import?privacy_revision=0&days=9999",
                                 files={"export": ("export.xml", export_xml())})).status_code == 400


@pytest.mark.skipif(os.environ.get("JARVIS_TEST_LAB_DOCKER") != "1", reason="Opt-in real Health export sandbox")
async def test_real_health_import_worker(runtime):
    result = await runtime.apple_health.import_export(export_xml(), 90, 0)
    assert result["state"] == "imported" and result["metrics"]
    stored = (runtime.config.data_dir / "apple-health.json").read_text()
    assert "<HealthData" not in stored and "rows" in stored


async def test_cloud_consent_blocks_a_previously_local_health_conversation_before_request(runtime, monkeypatch):
    from jarvis.agent import TokenEvents
    from jarvis.db import now

    async def parser(raw, days):
        return parse_export(raw, "Europe/Rome", days)
    monkeypatch.setattr(runtime.lab, "parse_health", parser)
    await runtime.apple_health.import_export(export_xml(), 90, 0)
    conversation, local_task, cloud_task = str(uuid4()), str(uuid4()), str(uuid4())
    await runtime.db.execute("INSERT INTO conversations(id,title,scope,created_at,updated_at) VALUES(?,?,'personal',?,?)",
                             (conversation, "Health fixture", now(), now()))
    for task in [local_task, cloud_task]:
        await runtime.db.execute("INSERT INTO tasks(id,conversation_id,title,prompt,state,profile,scope,created_at,updated_at) VALUES(?,?,?,?,'running','local_connected','personal',?,?)",
                                 (task, conversation, "Fixture", "Fixture", now(), now()))
    ctx = TaskContext(local_task, "My steps", "local_connected", "personal")
    token = active_task.set(ctx)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        await runtime.apple_health.summary("personal", day, day, "steps", model_access=True)
    finally:
        active_task.reset(token)
    next_ctx = TaskContext(cloud_task, "Continue", "cloud", "personal")
    callbacks = TokenEvents(runtime.db, next_ctx, runtime.budget, cloud=True, health=runtime.apple_health)
    with pytest.raises(PermissionError, match="conversation contains"):
        await callbacks.on_chat_model_start({}, [], run_id=uuid4())
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")
    await runtime.apple_health.consent(HealthConsent(privacy_revision=0, revision=1, allow_cloud=True))
    await runtime.apple_health.check_model(next_ctx, True)
    await runtime.apple_health.consent(HealthConsent(privacy_revision=0, revision=2, allow_cloud=False))
    with pytest.raises(PermissionError):
        await runtime.apple_health.check_model(next_ctx, True)


async def test_private_health_conversation_taint_stays_in_ram_and_blocks_cloud(runtime, monkeypatch):
    async def parser(raw, days):
        return parse_export(raw, "Europe/Rome", days)
    monkeypatch.setattr(runtime.lab, "parse_health", parser)
    await runtime.apple_health.import_export(export_xml(), 90, 0)
    first, second, conversation = str(uuid4()), str(uuid4()), str(uuid4())
    runtime.tasks.private_tasks[first] = {"conversation_id": conversation}
    runtime.tasks.private_tasks[second] = {"conversation_id": conversation}
    local = TaskContext(first, "My steps", "local_connected", "personal", private=True)
    token = active_task.set(local)
    try:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        await runtime.apple_health.summary("personal", day, day, "steps", model_access=True)
    finally:
        active_task.reset(token)
    cloud = TaskContext(second, "Continue", "cloud", "personal", private=True)
    with pytest.raises(PermissionError, match="conversation contains"):
        await runtime.apple_health.check_model(cloud, True)
    assert not await runtime.db.fetchall("SELECT name FROM controls WHERE name LIKE 'health-conversation:%'")
