"""Owner-imported Apple Health exports; aggregate evidence, scoped reads and cloud consent."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import File, UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import now, uid
from .feature_context import Scope, owner_write
from .feature_storage import load_private, save_private
from .policy import active_task

STORE = "apple-health.json"
METRICS = {"steps", "heart_rate", "resting_heart_rate", "active_energy", "distance", "sleep_minutes", "workout_minutes"}
HealthMetric = Literal["steps", "heart_rate", "resting_heart_rate", "active_energy", "distance", "sleep_minutes", "workout_minutes"]
UNITS = {"steps": "count", "heart_rate": "count/min", "resting_heart_rate": "count/min",
         "active_energy": "kcal", "distance": "km", "sleep_minutes": "min", "workout_minutes": "min"}
HEALTH_WARNINGS = ["Daily values are separated by source; overlapping devices/apps must not be added together.",
                   "Missing records are unknown, not zero. Summaries describe recorded data, not diagnoses."]


class NativeHealthRow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    metric: HealthMetric
    source: str = Field(min_length=1, max_length=100)
    source_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    unit: str
    aggregation: Literal["sum", "mean"]
    value: float = Field(ge=0, le=1_000_000_000)
    min: float = Field(ge=0, le=1_000_000_000)
    max: float = Field(ge=0, le=1_000_000_000)
    count: int = Field(ge=1, le=100_000)

    @model_validator(mode="after")
    def valid_aggregation(self):
        method = "mean" if self.metric in {"heart_rate", "resting_heart_rate"} else "sum"
        if self.unit != UNITS[self.metric] or self.aggregation != method:
            raise ValueError("Health units and aggregation must match the selected metric.")
        if self.min > self.max or self.value < self.min or (method == "mean" and self.value > self.max):
            raise ValueError("Inconsistent health aggregate.")
        return self


class NativeHealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    first_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    last_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str = Field(min_length=1, max_length=100)
    collected_at: str = Field(max_length=40)
    metrics: list[HealthMetric] = Field(min_length=1, max_length=7)
    records_scanned: int = Field(ge=1, le=700_000)
    rows: list[NativeHealthRow] = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def valid_window(self):
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Choose a valid health time zone.") from None
        begin, end = date.fromisoformat(self.first_date), date.fromisoformat(self.last_date)
        collected = datetime.fromisoformat(self.collected_at)
        if collected.tzinfo is None or abs(datetime.now(UTC) - collected) > timedelta(hours=24):
            raise ValueError("Read a fresh HealthKit preview before sharing.")
        if end != collected.astimezone(zone).date() or not 0 <= (end - begin).days < 90:
            raise ValueError("Choose 1–90 days ending on the HealthKit reading date.")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("Choose each health metric once.")
        keys = set()
        for row in self.rows:
            date.fromisoformat(row.date)
            key = row.date, row.metric, row.source_id
            if row.metric not in self.metrics or not self.first_date <= row.date <= self.last_date or key in keys:
                raise ValueError("Health groups must be unique, within the period and selected metrics.")
            keys.add(key)
        return self


class NativeHealthImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    revision: int = Field(ge=0)
    snapshot: NativeHealthSnapshot


class HealthConsent(BaseModel):
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    revision: int = Field(ge=0)
    allow_cloud: bool


class AppleHealth:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = asyncio.Lock()
        self.private_conversations = set()

    def personal(self, scope):
        if scope != "personal":
            raise PermissionError("Apple Health is available only in the personal scope.")

    def load(self):
        return load_private(self.runtime.config, STORE) or {"revision": 0, "allow_cloud": False}

    def status(self, scope):
        self.personal(scope)
        data = self.load()
        return {k: v for k, v in data.items() if k != "rows"}

    async def import_export(self, raw, days, privacy_revision):
        owner_write(self.runtime, "personal", privacy_revision)
        parsed = await self.runtime.lab.parse_health(raw, days)
        async with self.lock:
            owner_write(self.runtime, "personal", privacy_revision)
            data = self.load()
            digest = hashlib.sha256(raw).hexdigest()
            if data.get("sha256") == digest and data.get("last_date") == parsed["last_date"] and data.get("days") == days:
                return {**self.status("personal"), "state": "unchanged"}
            result = {**parsed, "id": uid(), "revision": data["revision"] + 1,
                      "allow_cloud": data.get("allow_cloud", False), "sha256": digest,
                      "imported_at": now(), "source": "Apple Health export",
                      "metrics": sorted({r["metric"] for r in parsed["rows"]}),
                      "sources": sorted({r["source"] for r in parsed["rows"]})}
            if len(json.dumps(result).encode()) > 1_900_000:
                raise ValueError("Health summary exceeds its storage limit; choose fewer days.")
            save_private(self.runtime.config, STORE, result)
            return {**self.status("personal"), "state": "imported"}

    async def import_native(self, request: NativeHealthImport):
        self.personal(request.scope)
        async with self.lock:
            owner_write(self.runtime, request.scope, request.privacy_revision)
            current = self.load()
            if current["revision"] != request.revision:
                raise ValueError("Health settings changed. Refresh before sharing.")
            snapshot = request.snapshot.model_dump()
            # A new reading timestamp alone must not create a second copy of the same snapshot.
            evidence = {k: v for k, v in snapshot.items() if k != "collected_at"}
            evidence["rows"] = sorted(evidence["rows"], key=lambda r: (r["date"], r["metric"], r["source_id"]))
            evidence["metrics"] = sorted(evidence["metrics"])
            digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
            if current.get("sha256") == digest:
                return {**self.status("personal"), "state": "unchanged"}
            result = {**snapshot, "rows": evidence["rows"], "id": uid(), "revision": current["revision"] + 1,
                      "allow_cloud": current.get("allow_cloud", False), "sha256": digest,
                      "imported_at": now(), "source": "Apple HealthKit (iOS companion)",
                      "days": (date.fromisoformat(snapshot["last_date"]) - date.fromisoformat(snapshot["first_date"])).days + 1,
                      "sources": sorted({r["source"] for r in snapshot["rows"]}),
                      "warnings": [*HEALTH_WARNINGS, "HealthKit read permissions may hide samples; an empty category does not establish that permission was denied."]}
            save_private(self.runtime.config, STORE, result)
            return {**self.status("personal"), "state": "imported"}

    async def consent(self, data):
        self.personal(data.scope)
        async with self.lock:
            owner_write(self.runtime, data.scope, data.privacy_revision)
            current = self.load()
            if current["revision"] != data.revision:
                raise ValueError("Health settings changed. Refresh before saving.")
            current.update(allow_cloud=data.allow_cloud, revision=current["revision"] + 1)
            save_private(self.runtime.config, STORE, current)
            if not data.allow_cloud:
                self.runtime.live_voice.stop_all()
            return self.status(data.scope)

    async def delete(self, scope, privacy_revision, revision):
        self.personal(scope)
        async with self.lock:
            owner_write(self.runtime, scope, privacy_revision)
            current = self.load()
            if current["revision"] != revision:
                raise ValueError("Health settings changed. Refresh before deleting.")
            # Keep the revision monotonic; disconnect also revokes cloud consent.
            save_private(self.runtime.config, STORE, {"revision": revision + 1, "allow_cloud": False})
            self.runtime.live_voice.stop_all()
            return {"state": "deleted", "revision": revision + 1}

    async def check_model(self, ctx, cloud):
        if not cloud:
            return
        row = await self.runtime.db.fetchone("SELECT conversation_id FROM tasks WHERE id=?", (ctx.id,))
        private_conversation = self.runtime.tasks.private_tasks.get(ctx.id, {}).get("conversation_id")
        tainted = ctx.health_context or private_conversation in self.private_conversations
        if row and row["conversation_id"]:
            flag = await self.runtime.db.fetchone("SELECT value FROM controls WHERE name=?", ("health-conversation:" + row["conversation_id"],))
            tainted = tainted or bool(flag)
        if tainted and not self.load().get("allow_cloud"):
            raise PermissionError("This conversation contains Apple Health evidence. Enable health cloud consent, use a local model, or start a new conversation.")

    async def summary(self, scope, start, end, metric="", *, model_access=False):
        self.personal(scope)
        begin, finish = date.fromisoformat(start), date.fromisoformat(end)
        if finish < begin or (finish - begin).days >= 31:
            raise ValueError("Choose a period of at most 31 days.")
        start, end = begin.isoformat(), finish.isoformat()
        if metric and metric not in METRICS:
            raise ValueError("Unsupported health metric.")
        data = self.load()
        if model_access:
            ctx = active_task.get()
            row = await self.runtime.db.fetchone("SELECT model,channel,conversation_id FROM tasks WHERE id=?", (ctx.id,))
            cloud = bool(row and ((row.get("model") or "").startswith("cloud/") or row["channel"] in {"live", "phone"}))
            cloud = cloud or ctx.profile == "cloud" or (
                ctx.profile == "hybrid" and self.runtime.config.settings.cloud_model
                and self.runtime.config.settings.secret("cloud_api_key"))
            if cloud and not data.get("allow_cloud"):
                raise PermissionError("Health summaries are disabled for cloud models. The owner can enable access in Apple Health settings.")
            ctx.health_context = True
            if ctx.private:
                alive = {task.get("conversation_id") for task in self.runtime.tasks.private_tasks.values()}
                self.private_conversations.intersection_update(alive)
                private_conversation = self.runtime.tasks.private_tasks.get(ctx.id, {}).get("conversation_id")
                if private_conversation:
                    self.private_conversations.add(private_conversation)
            if row and row["conversation_id"] and not ctx.private:
                await self.runtime.db.execute("INSERT INTO controls(name,value) VALUES(?,'1') ON CONFLICT(name) DO UPDATE SET value='1'", ("health-conversation:" + row["conversation_id"],))
        rows = [row for row in data.get("rows", []) if start <= row["date"] <= end and (not metric or row["metric"] == metric)]
        if len(rows) > 200:
            raise ValueError("Narrow the dates or choose one health metric.")
        return {"source_id": data.get("id"), "revision": data["revision"], "sha256": data.get("sha256"),
                "source": data.get("source"), "timezone": data.get("timezone"),
                "imported_at": data.get("imported_at"), "first_date": data.get("first_date"),
                "last_date": data.get("last_date"), "rows": rows, "warnings": data.get("warnings", []),
                "trust": "Imported health evidence. Missing samples are unknown. Do not diagnose or save these readings as owner testimony."}


def install_health_routes(app, runtime):
    @app.get("/api/apple-health")
    async def status(scope: Scope = "personal"):
        return runtime.apple_health.status(scope)

    @app.get("/api/apple-health/summary")
    async def summary(start: str, end: str, metric: str = "", scope: Scope = "personal"):
        return await runtime.apple_health.summary(scope, start, end, metric)

    @app.post("/api/apple-health/import")
    async def import_export(privacy_revision: int, export: Annotated[UploadFile, File()],
                            days: int = 90, scope: Scope = "personal"):
        runtime.apple_health.personal(scope)
        owner_write(runtime, scope, privacy_revision)
        if not 1 <= days <= 365:
            raise ValueError("Choose 1–365 days.")
        try:
            raw = await export.read(64_000_001)
            if len(raw) > 64_000_000:
                raise ValueError("Choose an Apple Health export of at most 64 MB.")
            return await runtime.apple_health.import_export(raw, days, privacy_revision)
        finally:
            await export.close()

    @app.post("/api/apple-health/consent")
    async def consent(data: HealthConsent):
        return await runtime.apple_health.consent(data)

    @app.post("/api/apple-health/native")
    async def import_native(data: NativeHealthImport):
        return await runtime.apple_health.import_native(data)

    @app.delete("/api/apple-health")
    async def delete(data: HealthConsent):
        return await runtime.apple_health.delete(data.scope, data.privacy_revision, data.revision)
