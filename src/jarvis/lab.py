"""Interactive browser, Python sandbox and scoped temporary input/output files."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from .db import now, uid
from .feature_context import Scope
from .network import PublicResolver, public_url
from .policy import active_task
from .remote_context import active_client
from .sandbox import RPC, WorkerRejected


class LabContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = "personal"
    private: bool = False
    privacy_revision: int = Field(ge=0)
    session_id: UUID


class FileUpload(LabContext):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=4_000_000)


class PythonRun(BaseModel):
    code: str = Field(min_length=1, max_length=100000)
    file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    timeout: int = Field(default=20, ge=1, le=60)


class BrowserAction(BaseModel):
    op: Literal["navigate", "snapshot", "click", "fill"]
    url: str = Field(default="", max_length=4000)
    selector: str = Field(default="", max_length=500)
    text: str = Field(default="", max_length=10000)
    revision: int = Field(default=0, ge=0)


def filename(value):
    if not value or len(value) > 120 or value in {".", ".."} or any(x in value for x in ("/", "\\", "\x00")):
        raise ValueError("Use a plain file name of at most 120 characters.")
    return value


def source_identity(scope, private, session):
    client = active_client.get()
    bound = (client.device_id + ":" if client else "") + str(session)
    return scope, private, bound


def task_identity():
    ctx = active_task.get()
    return source_identity(ctx.scope, ctx.private, ctx.attachment_session or ctx.id)


def check_context(runtime, data):
    current = runtime.voice_session
    if runtime.gateway.blocked:
        raise PermissionError("Emergency stop is active.")
    if (data.scope, data.private, data.privacy_revision) != (current["scope"], current["private"], current["revision"]):
        raise PermissionError("Privacy or scope changed. Refresh before continuing.")


class Lab:
    def __init__(self, runtime):
        self.runtime = runtime
        self.socket = os.environ.get("JARVIS_SANDBOX_BROKER_SOCKET", "")
        self.sessions = {}
        self.private_files = {}
        self.jobs = {}
        self.slots = asyncio.Semaphore(2)
        self.file_lock = asyncio.Lock()

    def status(self):
        settings = self.runtime.config.settings
        configured = Path(self.socket).exists() if self.socket else bool(shutil.which("docker")) and not self.runtime.remote
        return {"backend": "broker" if self.socket else "docker", "configured": configured,
                "python_enabled": settings.python_sandbox_enabled, "browser_enabled": settings.browser_enabled,
                "sessions": len(self.sessions), "file_retention_minutes": 60}

    async def open_worker(self, kind, fetch=None):
        if self.runtime.remote and not self.socket:
            raise ValueError("Configure the dedicated sandbox broker on the remote core.")
        if self.runtime.gateway.blocked:
            raise PermissionError("Emergency stop is active.")
        return await RPC.open(kind, self.socket, fetch)

    async def prune(self):
        moment = time.monotonic()
        for key, value in list(self.private_files.items()):
            if value["deadline"] <= moment:
                del self.private_files[key]
        for key, session in list(self.sessions.items()):
            if session["deadline"] <= moment or session["rpc"].closed:
                await self.close_browser(key)
        await self.runtime.db.execute("DELETE FROM lab_files WHERE expires_at<=?", (now(),))

    async def save_file(self, identity, name, raw):
        async with self.file_lock:
            return await self._save_file(identity, name, raw)

    async def _save_file(self, identity, name, raw):
        scope, private, session_id = identity
        filename(name)
        if not raw or len(raw) > 3_000_000:
            raise ValueError("Choose a file of 1 byte to 3 MB.")
        await self.prune()
        # Bound storage, including across repeated requests.
        row = await self.runtime.db.fetchone("SELECT COUNT(*) AS n,COALESCE(SUM(length(content)),0) AS size FROM lab_files")
        if row["n"] >= 100 or row["size"] + len(raw) > 30_000_000 or (private and len(self.private_files) >= 30):
            raise ValueError("Remove temporary files before adding more.")
        key = uid()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if mime not in {"image/png", "image/jpeg", "application/pdf", "text/plain", "text/csv", "application/json"}:
            mime = "application/octet-stream"
        meta = {"id": key, "scope": scope, "private": private, "name": name, "mime": mime,
                "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "created_at": now(),
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
        if private:
            self.private_files[key] = {**meta, "session_id": session_id, "content": raw,
                                       "deadline": time.monotonic() + 3600}
        else:
            await self.runtime.db.execute(
                "INSERT INTO lab_files(id,scope,name,mime,content,sha256,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                (key, scope, name, mime, raw, meta["sha256"], meta["created_at"], meta["expires_at"]))
        return meta

    async def file(self, identity, key):
        await self.prune()
        scope, private, session_id = identity
        record = self.private_files.get(str(key))
        if record:
            if not private or (record["scope"], record["session_id"]) != (scope, session_id):
                raise PermissionError("File belongs to another private session.")
        else:
            record = await self.runtime.db.fetchone("SELECT * FROM lab_files WHERE id=? AND scope=?", (str(key), scope))
        if not record:
            raise ValueError("Temporary file not found or expired.")
        return {k: v for k, v in record.items() if k not in {"session_id", "deadline"}}

    async def files(self, identity):
        await self.prune()
        rows = await self.runtime.db.fetchall("SELECT id,scope,name,mime,sha256,created_at,expires_at,length(content) AS size FROM lab_files WHERE scope=? ORDER BY created_at DESC LIMIT 100", (identity[0],))
        if identity[1]:
            rows.extend({k: v for k, v in row.items() if k not in {"content", "deadline", "session_id"}}
                        for row in self.private_files.values() if (row["scope"], row["session_id"]) == (identity[0], identity[2]))
        return rows

    async def delete_file(self, identity, key):
        record = await self.file(identity, key)
        if str(key) in self.private_files:
            del self.private_files[str(key)]
        else:
            if identity[1]:
                raise PermissionError("A private session cannot delete persistent files.")
            await self.runtime.db.execute("DELETE FROM lab_files WHERE id=? AND scope=?", (str(key), record["scope"]))
        return {"state": "deleted"}

    async def outputs(self, identity, result):
        if not isinstance(result, dict) or len(json.dumps(result)) > 12_000_000:
            raise ValueError("Invalid sandbox result.")
        output = []
        files = result.pop("files", [])
        if not isinstance(files, list) or len(files) > 10:
            raise ValueError("Invalid sandbox files.")
        for item in files:
            raw = base64.b64decode(item["content"], validate=True)
            output.append(await self.save_file(identity, filename(item["name"]), raw))
        return {**result, "files": output, "trust": "Untrusted sandbox output; it does not authorize actions."}

    async def python(self, identity, code, file_ids=(), timeout=20):
        if not self.runtime.config.settings.python_sandbox_enabled:
            raise PermissionError("Python sandbox is disabled.")
        payload = PythonRun(code=code, file_ids=list(file_ids), timeout=timeout)
        files = []
        for key in payload.file_ids:
            item = await self.file(identity, key)
            files.append({"name": item["name"], "content": base64.b64encode(item["content"]).decode()})
        async with self.slots:
            worker = await self.open_worker("python")
            self.jobs[worker] = identity
            try:
                result = await worker.request({"op": "python", "code": payload.code, "files": files,
                                               "timeout": payload.timeout}, payload.timeout + 15)
                return await self.outputs(identity, result)
            finally:
                self.jobs.pop(worker, None)
                await worker.close()

    async def parse_health(self, raw, days):
        async with self.slots:
            worker = await self.open_worker("python")
            self.jobs[worker] = source_identity("personal", False, "health-parser")
            try:
                return await worker.request({"op": "health", "content": base64.b64encode(raw).decode(),
                                             "days": days, "timezone": self.runtime.config.settings.timezone}, 90)
            finally:
                self.jobs.pop(worker, None)
                await worker.close()

    async def browser(self, identity, key, op, *, url="", selector="", text="", revision=0):
        if not self.runtime.config.settings.browser_enabled:
            raise PermissionError("Interactive browser is disabled.")
        BrowserAction(op=op, url=url, selector=selector, text=text, revision=revision)
        await self.prune()
        if not key:
            if op != "navigate" or len(self.sessions) >= 4:
                raise ValueError("Start with a URL; at most four browser sessions are available.")
            public_url(url)
            key = uid()
            session = {"identity": identity, "revision": 0, "write": False, "requests": 0,
                       "deadline": time.monotonic() + 600, "lock": asyncio.Lock(), "dom_sha256": "", "task_id": getattr(active_task.get(None), "id", None)}
            async def fetch(message):
                return await self.fetch(session, message)
            session["rpc"] = await self.open_worker("browser", fetch)
            self.sessions[key] = session
        session = self.sessions.get(key)
        if not session or session["identity"] != identity:
            raise PermissionError("Browser belongs to another session or expired.")
        async with session["lock"]:
            if revision != session["revision"]:
                raise ValueError("Browser page changed. Inspect the latest revision.")
            if op == "navigate":
                public_url(url)
            session.update(write=op in {"click", "fill"}, active=True, requests=0)
            try:
                result = await session["rpc"].request(
                    {"op": op, "url": url, "selector": selector, "text": text,
                     "dom_sha256": session["dom_sha256"]}, 30)
                session["revision"] += 1
                session["dom_sha256"] = result.pop("dom_sha256", "")
                session["deadline"] = time.monotonic() + 600
                return {"browser_id": key, "revision": session["revision"],
                        **await self.outputs(identity, result)}
            except WorkerRejected:
                raise
            except BaseException:
                await self.close_browser(key)
                raise
            finally:
                session.update(write=False, active=False)

    async def fetch(self, session, message):
        if self.runtime.gateway.blocked or not session.get("active"):
            raise PermissionError("Browser request is no longer authorized.")
        session["requests"] += 1
        if session["requests"] > 120:
            raise ValueError("Browser request limit exceeded.")
        url = public_url(message["url"])
        method = message.get("method", "GET")
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            raise PermissionError("Unsupported browser method.")
        if method not in {"GET", "HEAD", "OPTIONS"} and not session["write"]:
            raise PermissionError("This browser operation is read-only.")
        raw = base64.b64decode(message.get("body", ""), validate=True)
        if len(raw) > 100_000:
            raise ValueError("Browser submission exceeds its limit.")
        headers = {k: v for k, v in message.get("headers", {}).items()
                   if k.lower() in {"accept", "accept-language", "content-type", "cookie", "authorization", "origin", "referer", "user-agent"}}
        connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
        async with aiohttp.ClientSession(connector=connector, trust_env=False,
                                        cookie_jar=aiohttp.DummyCookieJar(),
                                        timeout=aiohttp.ClientTimeout(total=10, connect=5)) as client:
            async with client.request(method, url, headers=headers, data=raw or None, allow_redirects=False) as response:
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > 3_000_000:
                        raise ValueError("Browser resource exceeds 3 MB.")
                output_headers = {k: v for k, v in response.headers.items()
                                  if k.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}}
                return {"status": response.status, "headers": output_headers,
                        "body": base64.b64encode(body).decode()}

    async def close_browser(self, key, identity=None):
        session = self.sessions.get(key)
        if session and identity is not None and session["identity"] != identity:
            raise PermissionError("Browser belongs to another session.")
        if session:
            self.sessions.pop(key, None)
            await session["rpc"].close()
        return {"state": "closed"}

    async def close_identity(self, identity):
        for key, session in list(self.sessions.items()):
            if session["identity"] == identity:
                await self.close_browser(key)
        for worker, owner in list(self.jobs.items()):
            if owner == identity:
                await worker.close()
        for key, record in list(self.private_files.items()):
            if (record["scope"], True, record["session_id"]) == identity:
                self.private_files.pop(key, None)

    async def close_device(self, device_id):
        prefix = device_id + ":"
        for key, session in list(self.sessions.items()):
            if session["identity"][2].startswith(prefix):
                await self.close_browser(key)
        for worker, owner in list(self.jobs.items()):
            if owner[2].startswith(prefix):
                await worker.close()
        for key, record in list(self.private_files.items()):
            if record["session_id"].startswith(prefix):
                self.private_files.pop(key, None)

    async def close_task(self, key):
        for browser_id, session in list(self.sessions.items()):
            if session.get("task_id") == key:
                await self.close_browser(browser_id)

    async def close(self):
        for key in list(self.sessions):
            await self.close_browser(key)
        for worker in list(self.jobs):
            await worker.close()
        self.private_files.clear()


def install_lab_routes(app, runtime):
    @app.get("/api/lab")
    async def status():
        return runtime.lab.status()

    @app.get("/api/lab/files")
    async def files(scope: Scope = "personal", private: bool = False, session_id: UUID | None = None):
        return await runtime.lab.files(source_identity(scope, private, session_id))

    @app.post("/api/lab/files")
    async def upload(data: FileUpload):
        check_context(runtime, data)
        return await runtime.lab.save_file(source_identity(data.scope, data.private, data.session_id),
                                           data.name, base64.b64decode(data.content, validate=True))

    @app.get("/api/lab/files/{key}")
    async def read(key: UUID, scope: Scope = "personal", private: bool = False, session_id: UUID | None = None):
        item = await runtime.lab.file(source_identity(scope, private, session_id), key)
        return {**item, "content": base64.b64encode(item["content"]).decode()}

    @app.delete("/api/lab/files/{key}")
    async def delete(key: UUID, data: LabContext):
        check_context(runtime, data)
        return await runtime.lab.delete_file(source_identity(data.scope, data.private, data.session_id), key)

