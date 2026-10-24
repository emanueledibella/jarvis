from __future__ import annotations

import asyncio
import hmac
import json
import time
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ConfigStore, Profile
from .db import now
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
            return JSONResponse({"detail": "Host non ammesso."}, status_code=400)
        origin = request.headers.get("origin")
        allowed_origins = {
            f"http://127.0.0.1:{config.settings.api_port}",
            f"http://localhost:{config.settings.api_port}",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }
        if origin and origin not in allowed_origins:
            return JSONResponse({"detail": "Origin non ammessa."}, status_code=403)
        if request.url.path.startswith("/api/"):
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(token, config.token):
                return JSONResponse({"detail": "Autenticazione locale richiesta."}, status_code=401)
        if request.method in {"POST", "PUT", "PATCH"}:
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 512000:
                    return JSONResponse({"detail": "Richiesta oltre 512 KB."}, status_code=413)
                chunks.append(chunk)
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

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)[:1000]}, status_code=400)

    @app.exception_handler(PermissionError)
    async def denied(request, error):
        return JSONResponse({"detail": str(error)[:1000]}, status_code=403)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "jarvis", "version": "0.1.0"}

    @app.get("/api/status")
    async def status():
        return await runtime.status()

    @app.post("/api/control/emergency")
    async def emergency(data: dict):
        if not isinstance(data.get("stopped"), bool):
            raise ValueError("Specifica stopped: true o false.")
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
        if changes.get("profile") == "local_strict":
            for key in list(runtime.tasks.running):
                context = runtime.tasks.contexts.get(key)
                if context and context.profile != "local_strict":
                    await runtime.tasks.pause(key)
        if changes.get("profile") == "local_strict" or changes.get("telephony_enabled") is False:
            await runtime.telephony.stop_all()
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
                "Verifica capacità",
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
                409, "Privacy o ambito sono cambiati: attendi l'aggiornamento della conversazione."
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
            raise HTTPException(404, "Task non trovato.")
        await runtime.tasks.cancel(key)
        return {"state": "cancelling"}

    @app.get("/api/tasks/{key}/detail")
    async def task_detail(key: str):
        row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (key,))
        if not row:
            raise HTTPException(404, "Task non trovato.")
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
                "Conferma di aver verificato l'esito sul servizio o sul file originale."
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
            raise HTTPException(404, "Routine non trovata.")
        if set(changes) == {"enabled"} and isinstance(changes["enabled"], bool):
            if changes["enabled"] and row["next_run_at"] is None:
                raise ValueError(
                    "Il promemoria è già concluso. Modifica la scadenza per programmarlo nuovamente."
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
            raise PermissionError("Le scritture sono sospese nel profilo locale rigoroso.")
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
    async def connect_integration(name: str):
        if name not in runtime.mcp.specs():
            raise ValueError("Server non configurato.")
        return await runtime.connect(name)

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
            raise PermissionError("Autorizza la chiamata al tuo numero prima di avviarla.")
        return await runtime.telephony.call_owner(
            "manual:" + str(data.get("request_id", "")),
            str(data.get("reason", "Chiamata di prova richiesta dal proprietario")),
            authorized=True,
        )

    @app.post("/api/calls/{key}/reconcile")
    async def reconcile_call(key: str, data: dict):
        if data.get("verified") is not True:
            raise ValueError("Conferma la verifica del registro dell'operatore.")
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
            raise ValueError("Azione nativa non ammessa.")
        if runtime.gateway.blocked and operation in {"enable", "unmute", "listen"}:
            raise PermissionError("Arresto di emergenza attivo: riabilita prima il servizio.")
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
                raise ValueError("Sessione vocale non valida.")
        return await runtime.native.invoke(
            "control." + operation,
            arguments,
            timeout=120 if operation in {"enable", "calendar_authorize"} else 10,
        )

    @app.get("/api/voice/session")
    async def current_voice_session():
        return runtime.voice_session

    @app.post("/api/voice/session")
    async def voice_session(data: dict):
        if not isinstance(data.get("private"), bool) or data.get("scope") not in {
            "personal",
            "work",
        }:
            raise ValueError("Sessione vocale non valida.")
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
        return {
            "cursor": cursor,
            "events": batch,
            "settings": {
                "language": config.settings.language,
                "wake_phrase": config.settings.wake_phrase,
                "wake_enabled": config.settings.wake_enabled,
                "voice_enabled": config.settings.voice_enabled and not runtime.gateway.blocked,
                "private_session": runtime.voice_session["private"],
                "voice_scope": runtime.voice_session["scope"],
                "profile": config.settings.profile,
                "followup_seconds": config.settings.followup_seconds,
                "end_of_turn_ms": config.settings.end_of_turn_ms,
                "listen_timeout_seconds": config.settings.listen_timeout_seconds,
                "tts_voice": config.settings.tts_voice,
                "voice_on_lock_screen": config.settings.voice_on_lock_screen,
            },
        }

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
                {"detail": "Compila la dashboard con npm run build nella cartella web."},
                status_code=503,
            )
        return FileResponse(ui / "index.html")

    return app
