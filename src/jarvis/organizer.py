from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .calendar_assistant import calendar_briefing
from .db import now, uid
from .feature_context import Scope, check_write, owner_write


class ProjectData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def name_text(cls, value):
        if not value.strip():
            raise ValueError("A project name is required.")
        return value.strip()


class ActivityData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=8000)
    state: Literal["open", "in_progress", "completed"] = "open"
    priority: int = Field(default=2, ge=1, le=4)
    estimated_minutes: int | None = Field(default=None, ge=5, le=1440)
    due_at: datetime | None = None
    project_id: str | None = Field(default=None, max_length=100)
    parent_id: str | None = Field(default=None, max_length=100)
    source_url: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def title_text(cls, value):
        if not value.strip():
            raise ValueError("An activity title is required.")
        return value.strip()

    @field_validator("due_at")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Due times require an explicit time zone.")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("source_url")
    @classmethod
    def safe_link(cls, value):
        if value:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("Use an HTTP(S) source link without credentials.")
        return value


class ActivityWrite(ActivityData):
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    revision: int | None = Field(default=None, ge=1)

    def activity(self):
        return ActivityData.model_validate(self.model_dump(exclude={"scope", "privacy_revision", "revision"}))


class ProjectWrite(ProjectData):
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    revision: int | None = Field(default=None, ge=1)


class RemoveInput(BaseModel):
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    revision: int = Field(ge=1)
    cascade: bool = False


class PlanInput(BaseModel):
    scope: Scope = "personal"
    start: datetime
    end: datetime
    activity_ids: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def window(self):
        if not self.start.tzinfo or not self.end.tzinfo or not timedelta(0) < self.end.astimezone(UTC) - self.start.astimezone(UTC) <= timedelta(days=1):
            raise ValueError("Use an aware planning window of at most 24 hours.")
        if self.start < datetime.now(UTC) - timedelta(minutes=1) or self.end > datetime.now(UTC) + timedelta(days=30):
            raise ValueError("Plan within the next 30 days.")
        return self


class Organizer:
    def __init__(self, runtime):
        self.runtime = runtime
        self.db = runtime.db
        self.lock = asyncio.Lock()

    async def listing(self, scope):
        activities = await self.db.fetchall(
            "SELECT * FROM activities WHERE scope=? ORDER BY state='completed',priority DESC,due_at IS NULL,due_at,created_at LIMIT 500",
            (scope,),
        )
        moment = now()
        for item in activities:
            item["overdue"] = bool(item["due_at"] and item["due_at"] < moment and item["state"] != "completed")
        return {"scope": scope, "activities": activities, "projects": await self.db.fetchall(
            "SELECT * FROM projects WHERE scope=? ORDER BY name LIMIT 200", (scope,)
        ), "limit": 500}

    async def record(self, scope, key):
        row = await self.db.fetchone("SELECT * FROM activities WHERE id=? AND scope=?", (key, scope))
        if not row:
            raise ValueError("Activity not found in this scope.")
        return row

    async def project(self, scope, data: ProjectData, key=None, revision=None):
        async with self.lock:
            check_write(self.runtime)
            if key:
                changed = await self.db.execute(
                    "UPDATE projects SET name=?,description=?,revision=revision+1,updated_at=? WHERE id=? AND scope=? AND revision=?",
                    (data.name, data.description, now(), key, scope, revision),
                )
                if not changed:
                    raise ValueError("Project missing or changed. Refresh before saving.")
            else:
                key = uid()
                await self.db.execute(
                    "INSERT INTO projects(id,scope,name,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (key, scope, data.name, data.description, now(), now()),
                )
            await self.db.emit("organizer.updated", {"scope": scope})
            return await self.db.fetchone("SELECT * FROM projects WHERE id=? AND scope=?", (key, scope))

    async def save(self, scope, data: ActivityData, key=None, revision=None):
        async with self.lock:
            check_write(self.runtime)
            if data.project_id and not await self.db.fetchone(
                "SELECT id FROM projects WHERE id=? AND scope=?", (data.project_id, scope)
            ):
                raise ValueError("Project not found in this scope.")
            parent = data.parent_id
            visited = {key} if key else set()
            for _ in range(32):
                if not parent:
                    break
                if parent in visited:
                    raise ValueError("Activities cannot form a cycle.")
                visited.add(parent)
                ancestor = await self.record(scope, parent)
                parent = ancestor["parent_id"]
            else:
                raise ValueError("Activity nesting exceeds its limit.")
            values = (data.project_id, data.parent_id, data.title, data.notes, data.state, data.priority,
                      data.estimated_minutes, data.due_at.isoformat() if data.due_at else None, data.source_url)
            if key:
                changed = await self.db.execute(
                    "UPDATE activities SET project_id=?,parent_id=?,title=?,notes=?,state=?,priority=?,estimated_minutes=?,due_at=?,source_url=?,revision=revision+1,updated_at=? "
                    "WHERE id=? AND scope=? AND revision=?", (*values, now(), key, scope, revision),
                )
                if not changed:
                    raise ValueError("Activity missing or changed. Refresh before saving.")
            else:
                key = uid()
                await self.db.execute(
                    "INSERT INTO activities(id,scope,project_id,parent_id,title,notes,state,priority,estimated_minutes,due_at,source_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, scope, *values, now(), now()),
                )
            await self.db.emit("organizer.updated", {"scope": scope})
            return await self.record(scope, key)

    async def remove(self, scope, key, revision, *, project=False, cascade=False):
        async with self.lock:
            check_write(self.runtime)
            query = ("SELECT id FROM projects WHERE id=? AND scope=? AND revision=?" if project
                     else "SELECT id FROM activities WHERE id=? AND scope=? AND revision=?")
            row = await self.db.fetchone(query, (key, scope, revision))
            if not row:
                raise ValueError("Record missing or changed. Refresh before deleting.")
            if project:
                await self.db.batch([
                    ("UPDATE activities SET project_id=NULL,revision=revision+1,updated_at=? WHERE project_id=? AND scope=?", (now(), key, scope)),
                    ("DELETE FROM projects WHERE id=? AND scope=?", (key, scope)),
                ])
            else:
                children = await self.db.fetchone("SELECT id FROM activities WHERE parent_id=? AND scope=?", (key, scope))
                if children and not cascade:
                    raise ValueError("Activity has children. Explicitly choose cascade deletion.")
                await self.db.execute(
                    "WITH RECURSIVE descendants(id) AS (SELECT id FROM activities WHERE id=? AND scope=? "
                    "UNION SELECT a.id FROM activities a JOIN descendants d ON a.parent_id=d.id WHERE a.scope=?) "
                    "DELETE FROM activities WHERE scope=? AND id IN (SELECT id FROM descendants)", (key, scope, scope, scope),
                )
            await self.db.emit("organizer.updated", {"scope": scope})
            return {"state": "deleted", "id": key}

    async def plan(self, data: PlanInput, profile):
        if self.runtime.gateway.blocked:
            raise PermissionError("Emergency stop is active.")
        activities = [await self.record(data.scope, key) for key in dict.fromkeys(data.activity_ids)]
        horizon = max(1, (data.end.astimezone(UTC) - datetime.now(UTC)).days + 1)
        raw = await self.runtime.productivity.calendar(profile, min(horizon, 30))
        calendar = calendar_briefing(raw, self.runtime.config.settings.timezone, horizon)
        if calendar["analysis"]["state"] != "ready":
            return {"state": "unverified", "proposals": [], "calendar": calendar,
                    "message": "Complete verified calendar coverage is required to propose free time."}
        busy = []
        for event in calendar["events"]:
            if event.get("response_status") == "declined" or event.get("availability") == "free" or event.get("transparency") == "transparent":
                continue
            if event.get("all_day"):
                return {"state": "unverified", "proposals": [], "calendar": calendar,
                        "message": "Review all-day commitments before planning work blocks."}
            start, end = datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"])
            busy.append((start.astimezone(UTC), end.astimezone(UTC)))
        busy.sort()
        cursor, finish = max(data.start.astimezone(UTC), datetime.now(UTC)), data.end.astimezone(UTC)
        proposals, missing = [], []
        for activity in sorted(activities, key=lambda a: (-a["priority"], a["due_at"] or "9999")):
            if activity["state"] == "completed":
                continue
            minutes = activity["estimated_minutes"]
            if minutes is None:
                missing.append(activity["id"])
                continue
            duration = timedelta(minutes=minutes)
            for start, end in busy:
                if end <= cursor:
                    continue
                if cursor + duration <= start:
                    break
                cursor = max(cursor, end)
            if cursor + duration > finish:
                missing.append(activity["id"])
                continue
            proposals.append({"activity_id": activity["id"], "title": activity["title"],
                              "start": cursor.isoformat(), "end": (cursor + duration).isoformat(),
                              "past_due_time": bool(activity["due_at"] and cursor + duration > datetime.fromisoformat(activity["due_at"]))})
            cursor += duration
        return {"state": "proposed", "proposals": proposals, "unscheduled": missing,
                "calendar": calendar, "message": "No calendar events were created. Recheck the agenda before authorizing a block."}


def install_organizer_routes(app, runtime):
    @app.get("/api/organizer")
    async def listing(scope: Scope = "personal"):
        return await runtime.organizer.listing(scope)

    @app.post("/api/organizer/projects")
    async def project(data: ProjectWrite):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.organizer.project(data.scope, ProjectData(name=data.name, description=data.description))

    @app.put("/api/organizer/projects/{key}")
    async def update_project(key: str, data: ProjectWrite):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.organizer.project(data.scope, ProjectData(name=data.name, description=data.description), key, data.revision)

    @app.post("/api/organizer/activities")
    async def create(data: ActivityWrite):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.organizer.save(data.scope, data.activity())

    @app.put("/api/organizer/activities/{key}")
    async def update(key: str, data: ActivityWrite):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.organizer.save(data.scope, data.activity(), key, data.revision)

    @app.delete("/api/organizer/{kind}/{key}")
    async def remove(kind: Literal["activities", "projects"], key: str, data: RemoveInput):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.organizer.remove(data.scope, key, data.revision, project=kind == "projects", cascade=data.cascade)

    @app.post("/api/organizer/plan")
    async def plan(data: PlanInput):
        return await runtime.organizer.plan(data, runtime.config.settings.profile)
