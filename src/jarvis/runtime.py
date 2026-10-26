from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

from .agent import TaskManager
from .budget import ModelBudget
from .config import ConfigStore
from .db import Database, now
from .integrations import MCPHub, NativeBridge
from .lighting import Lighting
from .live_voice import LiveVoice
from .memory import Memory
from .platforms import ServiceLock, capabilities
from .policy import Gateway
from .productivity import Productivity
from .scheduler import Scheduler
from .telephony import Telephony


class Runtime:
    def __init__(self, config: ConfigStore):
        self.config = config
        self.db = Database(config.data_dir / "jarvis.sqlite3")
        self.native = NativeBridge(self.db)
        self.mcp = MCPHub(config)
        self.memory = Memory(config, self.db, self.mcp)
        self.productivity = Productivity(config, self.native)
        self.gateway = Gateway(self.db)
        self.lighting = Lighting(self)
        self.budget = ModelBudget(config, self.db)
        self.tasks = TaskManager(self)
        self.telephony = Telephony(self)
        self.live_voice = LiveVoice(self)
        self.scheduler = Scheduler(self)
        self.started_at = time.monotonic()
        self.audio = {"input": 0.0, "output": 0.0, "revision": 0}
        # Initialized from operational preferences once storage is open. Dialogue
        # contents never belong in this preference record.
        self.voice_session = {"private": None, "scope": None}
        self.voice_session_lock = asyncio.Lock()
        self.lock_file = None
        self.connect_jobs: dict[str, asyncio.Task] = {}

    async def start(self, *, scheduler=True, process_lock=True):
        if process_lock:
            self.lock_file = await asyncio.to_thread(
                ServiceLock, self.config.data_dir / "service.lock"
            )
        await self.db.open()
        voice = await self.db.fetchone("SELECT value FROM controls WHERE name='voice_session'")
        self.voice_session = (
            json.loads(voice["value"])
            if voice
            else {"private": False, "scope": "personal", "revision": 0}
        )
        await self.db.execute(
            "UPDATE calls SET state='unknown' WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected')"
        )
        blocked = await self.db.fetchone("SELECT value FROM controls WHERE name='emergency_stop'")
        self.gateway.blocked = bool(blocked and blocked["value"] == "1")
        self.memory.suspended = self.gateway.blocked
        await self.tasks.start()
        if scheduler:
            await self.scheduler.start()
        settings = self.config.settings
        cached_oauth = (self.config.data_dir / "oauth" / "second_brain").exists()
        if (
            settings.second_brain_url
            and settings.profile != "local_strict"
            and (
                (settings.second_brain_auth == "oauth" and cached_oauth)
                or (
                    settings.second_brain_auth == "bearer" and settings.secret("second_brain_token")
                )
            )
        ):
            await self.connect("second_brain", interactive=False)
        await self.db.emit("service.status", {"state": "ready"})

    async def close(self):
        self.scheduler.stop()
        self.live_voice.stop_all()
        await self.telephony.stop_all()
        for job in self.connect_jobs.values():
            job.cancel()
        await asyncio.gather(*self.connect_jobs.values(), return_exceptions=True)
        await self.tasks.close()
        await self.db.close()
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    async def status(self):
        settings = self.config.settings
        ready, missing = self.telephony.ready()
        return {
            "version": "0.1.0",
            "platform": capabilities(),
            "emergency_stop": self.gateway.blocked,
            "state": "ready",
            "uptime_seconds": int(time.monotonic() - self.started_at),
            "profile": settings.profile,
            "native": {**self.native.status, "connected": self.native.connected},
            "audio": self.audio,
            "models": {
                "local": settings.local_model,
                "cloud": settings.cloud_model,
                "cloud_configured": bool(settings.cloud_model and settings.secret("cloud_api_key")),
            },
            "memory": {
                "configured": bool(settings.second_brain_url),
                "capture": settings.memory_capture,
                "connection": self.mcp.statuses.get("second_brain", {"state": "not_connected"})[
                    "state"
                ],
            },
            "telephony": {
                "enabled": settings.telephony_enabled,
                "ready": ready,
                "missing": missing,
            },
            "mcp": self.mcp.statuses,
            "timezone": settings.timezone,
            "availability": "The service requires an awake computer and a running Jarvis process.",
        }

    async def set_voice_session(self, private: bool, scope: str):
        async with self.voice_session_lock:
            if self.voice_session["private"] == private and self.voice_session["scope"] == scope:
                return {**self.voice_session, "state": "unchanged"}
            self.voice_session = {
                "private": private,
                "scope": scope,
                "revision": self.voice_session["revision"] + 1,
            }
            await self.db.execute(
                "INSERT INTO controls(name,value) VALUES('voice_session',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (json.dumps(self.voice_session),),
            )
            await self.db.emit(
                "native.operation",
                {
                    "id": "voice-session",
                    "operation": "control.session",
                    "arguments": {"private": private, "scope": scope},
                },
                private=True,
            )
            await self.db.emit(
                "voice.session.updated", {"revision": self.voice_session["revision"]}, private=True
            )
            return {**self.voice_session, "state": "updated"}

    async def maintenance(self):
        settings = self.config.settings
        before = (
            datetime.now(UTC) - timedelta(days=settings.operation_log_retention_days)
        ).isoformat()
        await self.db.execute("DELETE FROM events WHERE created_at<?", (before,))
        transcripts = (
            datetime.now(UTC) - timedelta(days=settings.transcript_retention_days)
        ).isoformat()
        await self.db.execute("DELETE FROM messages WHERE created_at<?", (transcripts,))
        expired = await self.db.fetchall(
            "SELECT id FROM tasks WHERE updated_at<? AND state IN ('succeeded','failed','cancelled') AND prompt!=''",
            (transcripts,),
        )
        for task in expired:
            await self.tasks.checkpointer.adelete_thread(task["id"])
            await self.db.execute(
                "UPDATE tasks SET title='Archived task',prompt='',result='',error=NULL WHERE id=?",
                (task["id"],),
            )
            await self.db.execute(
                "UPDATE approvals SET arguments='{}' WHERE task_id=?", (task["id"],)
            )
            await self.db.execute("UPDATE effects SET result=NULL WHERE task_id=?", (task["id"],))
            self.tasks.graphs.pop(task["id"], None)
            self.tasks.contexts.pop(task["id"], None)
        await self.db.execute(
            "DELETE FROM conversations WHERE updated_at<? AND NOT EXISTS(SELECT 1 FROM messages WHERE conversation_id=conversations.id)",
            (transcripts,),
        )
        await self.db.execute(
            "UPDATE approvals SET state='expired' WHERE state='pending' AND expires_at<?", (now(),)
        )

    async def emergency(self, stopped: bool):
        self.gateway.blocked = stopped
        self.memory.suspended = stopped
        await self.db.execute(
            "INSERT INTO controls(name,value) VALUES('emergency_stop',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            ("1" if stopped else "0",),
        )
        if stopped:
            self.live_voice.stop_all()
            jobs = list(self.tasks.running)
            for key in jobs:
                await self.tasks.cancel(key)
            await self.db.execute("UPDATE approvals SET state='cancelled' WHERE state='pending'")
            await self.db.emit("speech.stop", {})
            await self.db.emit(
                "native.operation",
                {"id": "emergency-mute", "operation": "control.mute", "arguments": {}},
                private=True,
            )
            await self.telephony.stop_all()
        await self.db.emit("service.status", {"state": "stopped" if stopped else "ready"})
        return {"emergency_stop": stopped}

    async def integrations(self):
        return [
            {
                "name": name,
                "transport": "stdio" if spec.get("command") else "http",
                "auth": spec.get("auth", "none"),
                "url": spec.get("url", ""),
                "command": spec.get("command", ""),
                "args": spec.get("args", []),
                "read_tools": spec.get("read_tools", []),
                "write_tools": spec.get("write_tools", []),
                "status": self.mcp.statuses.get(name, {"state": "not_connected"}),
            }
            for name, spec in self.mcp.specs().items()
        ]

    async def connect(self, name, *, interactive=True):
        if name in self.connect_jobs and not self.connect_jobs[name].done():
            return {"state": "connecting"}

        async def work():
            try:
                await self.mcp.discover(name, self.config.settings.profile, interactive=interactive)
                await self.db.emit("integration.updated", {"name": name, "state": "connected"})
            except Exception as error:
                await self.db.emit(
                    "integration.updated",
                    {"name": name, "state": "error", "error": type(error).__name__},
                )

        self.mcp.statuses[name] = {"state": "connecting"}
        self.connect_jobs[name] = asyncio.create_task(work())
        return {"state": "connecting"}
