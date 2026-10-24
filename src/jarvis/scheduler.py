from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import dateparser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter
from pydantic import BaseModel, Field, model_validator

from .db import now, uid
from .network import fetch_public, public_url
from .speech import speech_text


class MonitorSpec(BaseModel):
    url: str
    json_path: str = ""
    operator: Literal["changed", "equals", "contains", "gte", "lte"] = "changed"
    expected: str | float | bool | None = None

    @model_validator(mode="after")
    def valid(self):
        public_url(self.url)
        if self.operator != "changed" and self.expected is None:
            raise ValueError("La condizione richiede un valore atteso.")
        return self


class ScheduleInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=16000)
    kind: Literal["at", "interval", "cron"] = "at"
    expression: str = Field(min_length=1, max_length=200)
    timezone: str = "Europe/Rome"
    mode: Literal["reminder", "agent", "monitor"] = "reminder"
    profile: Literal["local_strict", "local_connected", "cloud", "hybrid"] = "local_connected"
    scope: Literal["personal", "work"] = "personal"
    misfire_policy: Literal["skip", "coalesce", "run_once"] = "coalesce"
    grace_seconds: int = Field(default=300, ge=0, le=86400)
    notify: Literal["desktop", "voice", "phone"] = "desktop"
    call_authorized: bool = False
    monitor: MonitorSpec | None = None

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except KeyError:
            raise ValueError("Fuso orario IANA non riconosciuto.") from None
        if self.notify == "phone" and not self.call_authorized:
            raise ValueError("Le chiamate richiedono autorizzazione esplicita della routine.")
        if self.notify == "phone" and self.profile == "local_strict":
            raise ValueError("La telefonia non è disponibile nel profilo locale rigoroso.")
        if self.mode == "monitor" and not self.monitor:
            raise ValueError("Configura URL e condizione del monitor.")
        if self.mode == "monitor" and self.profile == "local_strict":
            raise ValueError("Un monitor web non è compatibile con locale rigorso.")
        if self.kind == "interval" and not 60 <= int(self.expression) <= 31_536_000:
            raise ValueError("Intervallo ammesso: da 60 secondi a un anno.")
        if self.kind == "cron" and not croniter.is_valid(self.expression):
            raise ValueError("Espressione cron non valida.")
        return self


def next_due(kind: str, expression: str, timezone: str, base: datetime | None = None) -> datetime:
    base = base or datetime.now(UTC)
    if kind == "interval":
        return base + timedelta(seconds=int(expression))
    if kind == "cron":
        value = croniter(expression, base.astimezone(ZoneInfo(timezone))).get_next(datetime)
        return value.astimezone(UTC)
    value = dateparser.parse(
        expression,
        languages=["it", "en"],
        settings={
            "TIMEZONE": timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base.astimezone(ZoneInfo(timezone)).replace(tzinfo=None),
        },
    )
    if not value:
        raise ValueError(
            "Data non riconosciuta. Usa una data ISO con fuso o una frase come 'tra 20 minuti'."
        )
    return value.astimezone(UTC)


class Scheduler:
    def __init__(self, runtime):
        self.runtime = runtime
        self.db = runtime.db
        self.timer = AsyncIOScheduler(timezone="UTC")

    async def start(self):
        self.timer.add_job(
            self.tick, "interval", seconds=1, coalesce=True, max_instances=1, misfire_grace_time=5
        )
        self.timer.add_job(
            self.runtime.memory.tick, "interval", seconds=10, coalesce=True, max_instances=1
        )
        self.timer.add_job(
            self.runtime.maintenance, "interval", hours=1, coalesce=True, max_instances=1
        )
        self.timer.start()
        await self.db.execute(
            "UPDATE schedule_runs SET state='unknown' WHERE state='claimed' AND task_id IS NULL"
        )

    def stop(self):
        if self.timer.running:
            self.timer.shutdown(wait=False)

    async def create(self, data: ScheduleInput) -> dict:
        due = next_due(data.kind, data.expression, data.timezone)
        if due < datetime.now(UTC):
            raise ValueError("La scadenza è già trascorsa.")
        key = uid()
        await self.db.execute(
            "INSERT INTO schedules(id,title,prompt,kind,expression,timezone,next_run_at,mode,monitor,profile,scope,misfire_policy,grace_seconds,notify,call_authorized,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                data.title,
                data.prompt,
                data.kind,
                data.expression,
                data.timezone,
                due.isoformat(),
                data.mode,
                data.monitor.model_dump_json() if data.monitor else "{}",
                data.profile,
                data.scope,
                data.misfire_policy,
                data.grace_seconds,
                data.notify,
                int(data.call_authorized),
                now(),
            ),
        )
        await self.db.emit("schedule.updated", {"id": key})
        return {
            "id": key,
            "next_run_at": due.isoformat(),
            "local_time": due.astimezone(ZoneInfo(data.timezone)).isoformat(),
            "state": "scheduled",
        }

    async def tick(self):
        if self.runtime.gateway.blocked:
            return
        moment = datetime.now(UTC)
        rows = await self.db.fetchall(
            "SELECT * FROM schedules WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at LIMIT 10",
            (moment.isoformat(),),
        )
        for row in rows:
            due = datetime.fromisoformat(row["next_run_at"])
            claimed = await self.db.execute(
                "INSERT OR IGNORE INTO schedule_runs(schedule_id,due_at,state) VALUES(?,?,'claimed')",
                (row["id"], due.isoformat()),
            )
            if not claimed:
                continue
            following = (
                None
                if row["kind"] == "at"
                else next_due(row["kind"], row["expression"], row["timezone"], moment).isoformat()
            )
            await self.db.execute(
                "UPDATE schedules SET next_run_at=?,enabled=?,last_run_at=? WHERE id=?",
                (following, 0 if following is None else 1, moment.isoformat(), row["id"]),
            )
            stale = (moment - due).total_seconds() > row["grace_seconds"]
            if stale and (row["misfire_policy"] == "skip" or row["notify"] == "phone"):
                await self.db.execute(
                    "UPDATE schedule_runs SET state='skipped' WHERE schedule_id=? AND due_at=?",
                    (row["id"], due.isoformat()),
                )
                await self.db.notification(
                    "Attività non eseguita durante lo stop",
                    row["title"],
                    f"missed:{row['id']}:{due.isoformat()}",
                )
                continue
            try:
                if self.runtime.config.settings.profile == "local_strict" and (
                    row["mode"] == "monitor"
                    or row["notify"] == "phone"
                    or row["profile"] in {"cloud", "hybrid"}
                ):
                    raise PermissionError("Routine sospesa dal profilo locale rigoroso.")
                if row["mode"] == "agent":
                    task = await self.runtime.tasks.create(
                        row["prompt"] or row["title"],
                        profile=row["profile"],
                        scope=row["scope"],
                        schedule_id=row["id"],
                    )
                    await self.db.execute(
                        "UPDATE schedule_runs SET state=(SELECT state FROM tasks WHERE id=?),task_id=? WHERE schedule_id=? AND due_at=?",
                        (task["id"], task["id"], row["id"], due.isoformat()),
                    )
                else:
                    if row["mode"] == "monitor":
                        summary, notify = await self.monitor(row)
                    else:
                        summary, notify = row["prompt"] or row["title"], True
                    if notify:
                        await self.deliver(row, summary, f"schedule:{row['id']}:{due.isoformat()}")
                    await self.db.execute(
                        "UPDATE schedule_runs SET state=? WHERE schedule_id=? AND due_at=?",
                        ("notified" if notify else "no_change", row["id"], due.isoformat()),
                    )
            except Exception as error:
                await self.db.execute(
                    "UPDATE schedule_runs SET state='failed' WHERE schedule_id=? AND due_at=?",
                    (row["id"], due.isoformat()),
                )
                await self.db.notification(
                    "Routine da verificare",
                    f"{row['title']}: {type(error).__name__}",
                    f"schedule-error:{row['id']}:{type(error).__name__}",
                )

    async def monitor(self, row: dict) -> tuple[str, bool]:
        spec = MonitorSpec.model_validate_json(row["monitor"])
        _, raw, _ = await fetch_public(spec.url, max_bytes=256000)
        value = json.loads(raw)
        for part in filter(None, spec.json_path.split(".")):
            value = value[int(part)] if isinstance(value, list) else value[part]
        serial = json.dumps(value, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(serial.encode()).hexdigest()
        previous = row["last_fingerprint"]
        condition = {
            "changed": lambda: previous is not None and previous != fingerprint,
            "equals": lambda: value == spec.expected,
            "contains": lambda: str(spec.expected) in str(value),
            "gte": lambda: float(value) >= float(spec.expected),
            "lte": lambda: float(value) <= float(spec.expected),
        }[spec.operator]()
        state = fingerprint if spec.operator == "changed" or condition else "false:" + fingerprint
        await self.db.execute(
            "UPDATE schedules SET last_fingerprint=? WHERE id=?", (state, row["id"])
        )
        notify = bool(condition and previous != state)
        return f"{row['title']}: {serial[:1000]}", notify

    async def deliver(self, row: dict, summary: str, fingerprint: str):
        if row["notify"] == "phone" and row["profile"] == "local_strict":
            raise PermissionError("Il profilo della routine non consente telefonate.")
        await self.db.notification(row["title"], summary, fingerprint)
        if row["notify"] == "voice":
            await self.db.emit("speech.requested", {"text": speech_text(summary)})
        if row["notify"] == "phone" and row["call_authorized"]:
            await self.runtime.telephony.call_owner(
                fingerprint, row["title"], row.get("task_id"), authorized=True
            )
