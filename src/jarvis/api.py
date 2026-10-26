from __future__ import annotations

import asyncio
import hmac
import json
import re
import time
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .config import ConfigStore, Profile
from .db import now
from .lighting import LightChange, LightRegistration
from .runtime import Runtime
from .scheduler import ScheduleInput, next_due


class ChatInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = None
    profile: Profile | None = None
    scope: Literal["personal", "work"] = "personal"
    private: bool = False
    channel: Literal["text", "voice"] = "text"
    external_authorized: bool = False
    privacy_revision: int | None = Field(default=None, ge=0)
    request_id: UUID | None = None


class Decision(BaseModel):
    approved: bool


class MemoryInput(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    scope: Literal["personal", "work"] = "personal"


class NativeStatus(BaseModel):
    voice_state: str = "unavailable"
    microphone: str = "unknown"
    speech: str = "unknown"
    on_device: bool = False
    version: str = "0.1.0"
    error: str | None = None
    muted: bool = True
    locked: bool = False
    input_buffers: int = Field(default=0, ge=0)
    recognition_callbacks: int = Field(default=0, ge=0)
    wake_matches: int = Field(default=0, ge=0)
    echo_cancellation: Literal["active", "fallback", "off"] = "off"
    barge_in: bool = False
    interruptions: int = Field(default=0, ge=0)


class LightGrant(BaseModel):
    voice_control: bool = Field(strict=True)


def create_app(
    config: ConfigStore | None = None, *, start_scheduler=True, process_lock=True
) -> FastAPI:
    config = config or ConfigStore()
    runtime = Runtime(config)

    @asynccontextmanager
    async def lifespan(app):
        await runtime.start(scheduler=start_scheduler, process_lock=process_lock)
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(
        title="Jarvis",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        public_phone = (
            request.url.path.startswith("/telephony/")
            and host == urlsplit(config.settings.telephony_public_base_url).hostname
        )
        if not public_phone and host not in {
            "127.0.0.1",
            "localhost",
            "testserver" if not process_lock else "127.0.0.1",
        }:
            return JSONResponse({"detail": "Host is not allowed."}, status_code=400)
        origin = request.headers.get("origin")
        allowed_origins = {
            f"http://127.0.0.1:{config.settings.api_port}",
            f"http://localhost:{config.settings.api_port}",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }
        if origin and origin not in allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed."}, status_code=403)
        if request.url.path.startswith("/api/"):
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(token.encode(), config.token.encode()):
                return JSONResponse(
                    {"detail": "Local authentication is required."}, status_code=401
                )
        if request.method in {"POST", "PUT", "PATCH"}:
            if not request.url.path.startswith(("/api/", "/telephony/")):
                return JSONResponse({"detail": "Method is not allowed."}, status_code=405)
            size = 0
            chunks = []
            limit = 16384 if request.url.path.startswith("/telephony/") else 512000
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > limit:
                            return JSONResponse(
                                {"detail": "Request exceeds its size limit."}, status_code=413
                            )
                        chunks.append(chunk)
            except TimeoutError:
                return JSONResponse({"detail": "Request body timed out."}, status_code=408)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid_fields(request, error):
        # Pydantic's default errors include input values, including passwords.
        fields = [".".join(str(p) for p in e["loc"]) or "configuration" for e in error.errors()]
        return JSONResponse(
            {"detail": "Invalid fields: " + ", ".join(fields[:10])}, status_code=422
        )

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)[:1000]}, status_code=400)

    @app.exception_handler(PermissionError)
    async def denied(request, error):
        return JSONResponse({"detail": str(error)[:1000]}, status_code=403)

    @app.get("/health")
    async def health(challenge: str = ""):
        result = {"status": "ok", "service": "jarvis", "version": "0.1.0"}
        if challenge:
            from .desktop import health_proof

            if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", challenge):
                raise ValueError("Invalid health challenge.")
            result["proof"] = health_proof(config.token, config.settings.api_port, challenge)
        return result

    @app.get("/api/status")
    async def status():
        return await runtime.status()

    @app.post("/api/control/emergency")
    async def emergency(data: dict):
        if not isinstance(data.get("stopped"), bool):
            raise ValueError("Specify stopped: true or false.")
        return await runtime.emergency(data["stopped"])

    @app.get("/api/settings")
    async def settings():
        return {"values": config.settings.public(), "locked": config.locked_fields()}

    @app.patch("/api/settings")
    async def save_settings(changes: dict):
        # Blank password fields are never an instruction to erase an existing secret.
        changes = {
            key: value
            for key, value in changes.items()
            if not (
                key in type(config.settings).model_fields
                and hasattr(getattr(config.settings, key), "get_secret_value")
                and value == ""
            )
        }
        config.update(changes)
        if any(
            key in changes
            for key in (
                "profile",
                "voice_enabled",
                "language",
                "response_language",
                "desktop_voice_provider",
                "desktop_voice_model",
                "desktop_voice_name",
                "desktop_voice_style",
                "desktop_voice_duplex",
            )
        ):
            runtime.live_voice.stop_all()
        if changes.get("profile") == "local_strict":
            for key in list(runtime.tasks.running):
                context = runtime.tasks.contexts.get(key)
                if context and context.profile != "local_strict":
                    await runtime.tasks.pause(key)
        if changes.get("profile") == "local_strict" or changes.get("telephony_enabled") is False:
            await runtime.telephony.stop_all()
        if set(changes) - {"ui_language"}:
            runtime.productivity.weather_cache.clear()
            runtime.productivity.calendar_cache.clear()
        await runtime.db.emit("settings.updated", {"fields": list(changes)})
        return {"values": config.settings.public(), "locked": config.locked_fields()}

    @app.get("/api/models")
    async def models():
        return await runtime.tasks.models()

    @app.get("/api/usage")
    async def model_usage():
        return await runtime.budget.status()

    @app.post("/api/models/test")
    async def test_model(data: dict):
        model, spec = runtime.tasks.model(data.get("profile", config.settings.profile))
        from langchain_core.tools import tool

        from .agent import TokenEvents
        from .policy import TaskContext

        callbacks = TokenEvents(
            runtime.db,
            TaskContext(
                "model-test",
                "Capability check",
                data.get("profile", config.settings.profile),
                "personal",
            ),
            runtime.budget,
            spec["kind"] == "cloud",
        )

        @tool
        def jarvis_probe(value: str) -> str:
            """Verify model tool calling. Call with value='ready'."""
            return value

        result = await model.bind_tools([jarvis_probe]).ainvoke(
            "Call jarvis_probe exactly once with value ready. Do not reply with ordinary text.",
            config={"callbacks": [callbacks]},
        )
        valid = False
        for call in result.tool_calls:
            if (
                len(result.tool_calls) == 1
                and call["name"] == "jarvis_probe"
                and call["args"].get("value") == "ready"
            ):
                valid = await jarvis_probe.ainvoke(call["args"]) == "ready"
        return {
            "state": "passed" if valid else "failed",
            "model": spec["model"],
            "tool_calling": valid,
        }

    @app.get("/api/dashboard")
    async def dashboard():
        async def result(function):
            try:
                return await asyncio.wait_for(function(), 12)
            except Exception as error:
                return {
                    "state": "error",
                    "message": str(error)[:200]
                    if isinstance(error, (ValueError, PermissionError))
                    else type(error).__name__,
                }

        weather, calendar = await asyncio.gather(
            result(lambda: runtime.productivity.weather(config.settings.profile)),
            result(lambda: runtime.productivity.calendar(config.settings.profile)),
        )
        return {"weather": weather, "calendar": calendar}

    @app.post("/api/chat", status_code=202)
    async def chat(data: ChatInput):
        if (
            data.privacy_revision is not None
            and data.privacy_revision != runtime.voice_session["revision"]
        ):
            raise HTTPException(
                409, "Privacy or scope changed: wait for the conversation to refresh."
            )
        privacy = data.private or bool(runtime.voice_session["private"])
        scope = data.scope if "scope" in data.model_fields_set else runtime.voice_session["scope"]
        profile = data.profile
        if data.channel == "voice":
            privacy = privacy or bool(runtime.voice_session["private"])
            if config.settings.profile == "local_strict" or (
                config.settings.profile == "local_connected" and profile in {"cloud", "hybrid"}
            ):
                profile = config.settings.profile
            normalized = data.text.strip().casefold().strip(" .!?")
            if normalized in {"stop", "fermati", "silenzio"}:
                await runtime.db.emit("speech.stop", {})
                return {"state": "stopped"}
        return await runtime.tasks.create(
            data.text,
            request_id=str(data.request_id) if data.request_id else None,
            conversation_id=data.conversation_id,
            profile=profile,
            scope=scope,
            private=privacy,
            channel=data.channel,
            external_authorized=data.external_authorized,
        )

    @app.get("/api/tasks")
    async def tasks():
        rows = await runtime.db.fetchall("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")
        for row in rows:
            row["usage"] = json.loads(row["usage"])
            if row["private"]:
                row.update(
                    {
                        k: v
                        for k, v in runtime.tasks.private_tasks.get(row["id"], {}).items()
                        if k != "checkpoint_view"
                    }
                )
        return rows

    @app.post("/api/tasks/{key}/cancel")
    async def cancel(key: str):
        if not await runtime.db.fetchone("SELECT id FROM tasks WHERE id=?", (key,)):
            raise HTTPException(404, "Task not found.")
        await runtime.tasks.cancel(key)
        return {"state": "cancelling"}

    @app.get("/api/tasks/{key}/detail")
    async def task_detail(key: str):
        row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (key,))
        if not row:
            raise HTTPException(404, "Task not found.")
        if row["private"]:
            row.update(
                {
                    k: v
                    for k, v in runtime.tasks.private_tasks.get(key, {}).items()
                    if k != "checkpoint_view"
                }
            )
        events = await runtime.db.fetchall(
            "SELECT * FROM events WHERE task_id=? ORDER BY sequence LIMIT 500", (key,)
        )
        for event in events:
            event["data"] = runtime.db.volatile.get(event["id"], json.loads(event["data"]))
        row["usage"] = json.loads(row["usage"])
        values = (
            runtime.tasks.private_tasks.get(key, {}).get("checkpoint_view", {})
            if row["private"]
            else {}
        )
        if row["private"]:
            graph = runtime.tasks.graphs.get(key)
            if graph:
                snapshot = await graph.aget_state({"configurable": {"thread_id": key}})
                values = snapshot.values
        else:
            checkpoint = await runtime.tasks.checkpointer.aget_tuple(
                {"configurable": {"thread_id": key}}
            )
            if checkpoint:
                values = checkpoint.checkpoint.get("channel_values", {})
        tool_results = [
            {"name": getattr(m, "name", "tool"), "content": str(m.content)[:16000]}
            for m in values.get("messages", [])
            if getattr(m, "type", None) == "tool"
        ][-20:]
        tool_results = values.get("tool_results", tool_results)
        return {
            "task": row,
            "events": events,
            "effects": await runtime.db.fetchall("SELECT * FROM effects WHERE task_id=?", (key,)),
            "plan": values.get("todos", []),
            "tool_results": tool_results,
            "artifacts": await runtime.db.fetchall(
                "SELECT * FROM artifacts WHERE task_id=?", (key,)
            ),
        }

    @app.post("/api/effects/{key}/reconcile")
    async def reconcile_effect(key: str, data: dict):
        if data.get("verified") is not True:
            raise ValueError(
                "Confirm that you verified the outcome in the original service or file."
            )
        await runtime.gateway.reconcile(key, data.get("outcome"), data.get("result", {}))
        return {"state": "reconciled"}

    @app.post("/api/tasks/{key}/resume")
    async def resume(key: str):
        await runtime.tasks.resume(key)
        return {"state": "queued"}

    @app.post("/api/tasks/{key}/pause")
    async def pause_task(key: str):
        await runtime.tasks.pause(key)
        return {"state": "pausing"}

    @app.get("/api/conversations")
    async def conversations():
        return await runtime.db.fetchall(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 50"
        )

    @app.get("/api/conversations/{key}/messages")
    async def messages(key: str):
        return await runtime.db.fetchall(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (key,)
        )

    @app.get("/api/approvals")
    async def approvals():
        rows = await runtime.db.fetchall(
            "SELECT * FROM approvals WHERE state='pending' AND expires_at>? ORDER BY created_at",
            (now(),),
        )
        for row in rows:
            row["arguments"] = runtime.gateway.private_approvals.get(
                row["id"], json.loads(row["arguments"])
            )
        return rows

    @app.post("/api/approvals/{key}")
    async def decide(key: str, decision: Decision):
        task_id = await runtime.gateway.decide(key, decision.approved)
        await runtime.tasks.resume(task_id)
        return {"state": "queued", "task_id": task_id}

    @app.get("/api/events")
    async def events(request: Request, after: int = 0):
        async def stream():
            cursor, audio_revision = after, -1
            while not await request.is_disconnected():
                rows = await runtime.db.wait_events(
                    cursor,
                    timeout=0.25
                    if runtime.native.status.get("voice_state") in {"listening", "speaking"}
                    else 2,
                )
                for row in rows:
                    cursor = row["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
                if runtime.audio["revision"] != audio_revision:
                    audio_revision = runtime.audio["revision"]
                    yield (
                        "data: "
                        + json.dumps({"type": "audio.level", "data": runtime.audio})
                        + "\n\n"
                    )
                if not rows:
                    yield ": keepalive\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/schedules")
    async def schedules():
        return await runtime.db.fetchall("SELECT * FROM schedules ORDER BY created_at DESC")

    @app.post("/api/schedules", status_code=201)
    async def create_schedule(data: ScheduleInput):
        return await runtime.scheduler.create(data)

    @app.patch("/api/schedules/{key}")
    async def update_schedule(key: str, changes: dict):
        row = await runtime.db.fetchone("SELECT * FROM schedules WHERE id=?", (key,))
        if not row:
            raise HTTPException(404, "Routine not found.")
        if set(changes) == {"enabled"} and isinstance(changes["enabled"], bool):
            if changes["enabled"] and row["next_run_at"] is None:
                raise ValueError(
                    "This reminder has already completed. Change its due date to schedule it again."
                )
            await runtime.db.execute(
                "UPDATE schedules SET enabled=? WHERE id=?", (int(changes["enabled"]), key)
            )
        else:
            row["monitor"] = json.loads(row["monitor"]) or None
            data = ScheduleInput.model_validate({**row, **changes})
            due = next_due(data.kind, data.expression, data.timezone)
            await runtime.db.execute(
                "UPDATE schedules SET title=?,prompt=?,kind=?,expression=?,timezone=?,mode=?,monitor=?,profile=?,scope=?,misfire_policy=?,grace_seconds=?,notify=?,call_authorized=?,next_run_at=? WHERE id=?",
                (
                    data.title,
                    data.prompt,
                    data.kind,
                    data.expression,
                    data.timezone,
                    data.mode,
                    data.monitor.model_dump_json() if data.monitor else "{}",
                    data.profile,
                    data.scope,
                    data.misfire_policy,
                    data.grace_seconds,
                    data.notify,
                    int(data.call_authorized),
                    due.isoformat(),
                    key,
                ),
            )
        await runtime.db.emit("schedule.updated", {"id": key})
        return {"state": "updated"}

    @app.delete("/api/schedules/{key}")
    async def delete_schedule(key: str):
        await runtime.db.execute("DELETE FROM schedules WHERE id=?", (key,))
        await runtime.db.emit("schedule.updated", {"id": key})
        return {"state": "deleted"}

    @app.get("/api/notifications")
    async def notifications():
        return await runtime.db.fetchall(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 50"
        )

    @app.post("/api/notifications/read")
    async def mark_notifications():
        await runtime.db.execute("UPDATE notifications SET read=1")
        return {"state": "read"}

    @app.get("/api/memory/status")
    async def memory_status():
        rows = await runtime.db.fetchall(
            "SELECT id,task_id,state,source_id,revision,attempts,detail,created_at FROM memory_outbox ORDER BY created_at DESC LIMIT 50"
        )
        for row in rows:
            row["detail"] = json.loads(row["detail"]) if row["detail"] else None
        return {
            "configured": bool(config.settings.second_brain_url),
            "outbox": rows,
            "connection": runtime.mcp.statuses.get("second_brain", {"state": "not_connected"}),
        }

    @app.post("/api/memory/recall")
    async def memory_recall(data: MemoryInput):
        return await runtime.memory.recall(data.text, data.scope, config.settings.profile)

    @app.post("/api/memory/remember", status_code=202)
    async def remember(data: MemoryInput):
        if config.settings.profile == "local_strict":
            raise PermissionError("Writes are suspended in the strict local profile.")
        return await runtime.memory.enqueue(data.text, data.scope)

    @app.get("/api/memory/source/{key}")
    async def memory_source(key: str, revision: int | None = None):
        return await runtime.mcp.call(
            "second_brain",
            "read_source",
            {"source_id": key, "revision": revision},
            config.settings.profile,
        )

    @app.post("/api/memory/{key}/retry")
    async def retry_memory(key: str):
        await runtime.memory.retry(key)
        return {"state": "pending"}

    @app.get("/api/integrations")
    async def integrations():
        return await runtime.integrations()

    @app.post("/api/integrations/{name}/connect")
    async def connect_integration(name: str, interactive: bool = True):
        if name not in runtime.mcp.specs():
            raise ValueError("Server is not configured.")
        return await runtime.connect(name, interactive=interactive)

    @app.put("/api/integrations/mcp/config")
    async def mcp_configuration(data: dict):
        from .mcp_config import save_mcp_config

        save_mcp_config(config, data)
        runtime.mcp.statuses.clear()
        return {"state": "saved"}

    @app.get("/api/calls")
    async def calls():
        return await runtime.db.fetchall("SELECT * FROM calls ORDER BY created_at DESC LIMIT 50")

    @app.post("/api/calls/owner")
    async def call_owner(data: dict):
        if data.get("authorized") is not True:
            raise PermissionError("Authorize the call to your number before starting it.")
        return await runtime.telephony.call_owner(
            "manual:" + str(data.get("request_id", "")),
            str(data.get("reason", "Test call requested by the owner")),
            authorized=True,
        )

    @app.post("/api/calls/{key}/reconcile")
    async def reconcile_call(key: str, data: dict):
        if data.get("verified") is not True:
            raise ValueError("Confirm that you checked the carrier call log.")
        return await runtime.telephony.reconcile(
            key,
            provider_id=str(data.get("provider_id", "")),
            not_created=data.get("not_created") is True,
            note=str(data.get("note", "")),
        )

    @app.post("/api/voice/control")
    async def voice_control(data: dict):
        operation = data.get("action")
        if operation not in {
            "enable",
            "mute",
            "unmute",
            "listen",
            "stop",
            "calendar_authorize",
            "autostart_enable",
            "autostart_disable",
        }:
            raise ValueError("Native action is not allowed.")
        if runtime.gateway.blocked and operation in {"enable", "unmute", "listen"}:
            raise PermissionError("Emergency stop is active: re-enable the service first.")
        if not config.settings.voice_enabled and operation in {"enable", "unmute", "listen"}:
            raise PermissionError("Voice is disabled. Enable it in Voice settings.")
        arguments = (
            {k: runtime.voice_session[k] for k in ("private", "scope")}
            if operation == "listen" and runtime.voice_session["private"] is not None
            else {}
        )
        if operation == "listen" and any(name in data for name in ("private", "scope")):
            arguments = {
                "private": bool(runtime.voice_session["private"]),
                "scope": runtime.voice_session["scope"] or "personal",
            }
            for name in ("private", "scope"):
                if name in data:
                    arguments[name] = data[name]
            if not isinstance(arguments["private"], bool) or arguments["scope"] not in {
                "personal",
                "work",
            }:
                raise ValueError("Invalid voice session.")
        return await runtime.native.invoke(
            "control." + operation,
            arguments,
            timeout=120 if operation in {"enable", "calendar_authorize"} else 10,
        )

    @app.get("/api/voice/session")
    async def current_voice_session():
        return runtime.voice_session

    @app.get("/api/lights")
    async def lights():
        from .platforms import capabilities
        return {"enabled": config.settings.lighting_enabled,
                "bluetooth_available": capabilities()["os"] == "darwin" and runtime.native.connected,
                "devices": runtime.lighting.list()}

    @app.post("/api/lights/discover")
    async def lights_discover():
        return await runtime.lighting.scan()

    @app.post("/api/lights")
    async def light_add(data: LightRegistration):
        return await runtime.lighting.add(data)

    @app.delete("/api/lights/{key}")
    async def light_remove(key: str):
        return await runtime.lighting.remove(key)

    @app.get("/api/lights/{key}/configuration")
    async def light_configuration(key: str):
        return runtime.lighting.configuration(key)

    @app.put("/api/lights/{key}")
    async def light_update(key: str, data: LightRegistration):
        return await runtime.lighting.add(data, existing_id=key)

    @app.patch("/api/lights/{key}/grant")
    async def light_grant(key: str, data: LightGrant):
        return await runtime.lighting.grant(key, data.voice_control)

    @app.get("/api/lights/{key}/state")
    async def light_read(key: str):
        return await runtime.lighting.state(key)

    @app.post("/api/lights/{key}/state")
    async def light_write(key: str, data: LightChange):
        return await runtime.lighting.set(key, data)

    @app.websocket("/api/voice/live")
    async def live_voice(websocket: WebSocket):
        await runtime.live_voice.endpoint(websocket)

    @app.post("/api/voice/session")
    async def voice_session(data: dict):
        if not isinstance(data.get("private"), bool) or data.get("scope") not in {
            "personal",
            "work",
        }:
            raise ValueError("Invalid voice session.")
        return await runtime.set_voice_session(data["private"], data["scope"])

    @app.post("/api/native/status")
    async def native_status(data: NativeStatus):
        old = runtime.native.status
        runtime.native.status = data.model_dump()
        runtime.native.last_seen = time.monotonic()
        if old != runtime.native.status:
            await runtime.db.emit("voice.state", runtime.native.status)
        return {"state": "ok"}

    @app.post("/api/native/level")
    async def native_level(data: dict):
        runtime.audio = {
            "input": min(max(float(data.get("input", 0)), 0), 1),
            "output": min(max(float(data.get("output", 0)), 0), 1),
            "revision": runtime.audio["revision"] + 1,
        }
        return {"state": "ok"}

    @app.get("/api/native/poll")
    async def native_poll(after: int = -1):
        runtime.native.last_seen = time.monotonic()
        if after < 0:
            row = await runtime.db.fetchone(
                "SELECT COALESCE(MAX(sequence),0) AS cursor FROM events"
            )
            cursor, batch = row["cursor"], []
        else:
            cursor, batch = after, await runtime.db.wait_events(after)
        if batch:
            cursor = max(event["sequence"] for event in batch)
        batch = [
            event
            for event in batch
            if event["type"] != "native.operation"
            or event["data"].get("id") in {"voice-session", "emergency-mute"}
            or event["data"].get("id") in runtime.native.pending
        ]
        return {
            "cursor": cursor,
            "events": batch,
            "settings": {
                "ui_language": config.settings.ui_language,
                "language": config.settings.language,
                "response_language": config.settings.response_language,
                "wake_phrase": config.settings.wake_phrase,
                "wake_enabled": config.settings.wake_enabled,
                "voice_enabled": config.settings.voice_enabled and not runtime.gateway.blocked,
                "lighting_enabled": config.settings.lighting_enabled and not runtime.gateway.blocked,
                "private_session": runtime.voice_session["private"],
                "voice_scope": runtime.voice_session["scope"],
                "profile": config.settings.profile,
                "followup_seconds": config.settings.followup_seconds,
                "end_of_turn_ms": config.settings.end_of_turn_ms,
                "listen_timeout_seconds": config.settings.listen_timeout_seconds,
                "tts_voice": config.settings.tts_voice,
                "voice_on_lock_screen": config.settings.voice_on_lock_screen,
                "privacy_revision": runtime.voice_session["revision"],
                "desktop_voice_provider": config.settings.desktop_voice_provider,
                "desktop_voice_model": config.settings.desktop_voice_model,
                "desktop_voice_name": config.settings.desktop_voice_name,
                "desktop_voice_duplex": config.settings.desktop_voice_duplex,
                "desktop_voice_max_session_seconds": config.settings.desktop_voice_max_session_seconds,
            },
        }

    @app.post("/api/native/claim/{key}")
    async def claim_native(key: str):
        if key == "voice-session":
            return {
                "operation": "control.session",
                "arguments": {k: runtime.voice_session[k] for k in ("private", "scope")},
            }
        if key == "emergency-mute" and runtime.gateway.blocked:
            return {"operation": "control.mute", "arguments": {}}
        operation = runtime.native.claim(key, stopped=runtime.gateway.blocked)
        if operation["operation"].startswith("hue."):
            try:
                runtime.lighting.authorize_native(operation)
            except PermissionError as error:
                runtime.native.complete(key, {"error": str(error)})
                raise
        return operation

    @app.post("/api/native/result/{key}")
    async def native_result(key: str, data: dict):
        runtime.native.complete(key, data)
        return {"state": "received"}

    app.include_router(runtime.telephony.router())
    ui = config.settings.ui_dir
    if (ui / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=ui / "assets"), name="assets")

    @app.get("/{path:path}")
    async def index(path: str):
        if path.startswith(("api/", "telephony/")):
            raise HTTPException(404)
        if not (ui / "index.html").is_file():
            return JSONResponse(
                {"detail": "Build the dashboard with npm run build in the web directory."},
                status_code=503,
            )
        return FileResponse(ui / "index.html")

    return app
