"""Remote control surface. The local bearer and native bridge never become public."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from httpx import URL, InvalidURL
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .feature_context import owner_session_guard
from .remote_context import ClientContext, active_client
from .remote_store import RemoteStore


class ServerOptions(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_REMOTE_", extra="ignore")
    public_url: str
    allowed_origins: list[str] = ["capacitor://localhost", "https://localhost", "jarvis://app"]
    development_http: bool = False
    transcription_usd_per_minute: float = Field(default=0.006, gt=0, le=10)
    tts_usd_per_million_characters: float = Field(default=15, gt=0, le=1000)
    apns_team_id: str = ""
    apns_key_id: str = ""
    apns_private_key: str = ""
    apns_topic: str = "it.jarvis.companion"
    apns_sandbox: bool = False
    fcm_service_account: str = ""
    document_worker_socket: str = ""

    @field_validator("public_url")
    @classmethod
    def origin_only(cls, value):
        p = urlsplit(value)
        if (
            not p.hostname
            or p.username
            or p.password
            or p.query
            or p.fragment
            or p.path not in {"", "/"}
        ):
            raise ValueError(
                "Configure a single public HTTPS origin without a path or credentials."
            )
        if p.scheme != "https" and not (
            p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("Remote Jarvis requires HTTPS.")
        try:
            port = None if p.port == {"https": 443, "http": 80}[p.scheme] else p.port
            return str(URL(value).copy_with(scheme=p.scheme, port=port)).rstrip("/")
        except InvalidURL:
            raise ValueError("Configure a valid HTTPS origin and port.") from None


class Enrollment(BaseModel):
    code: str = Field(min_length=16, max_length=128)
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")
    platform: str = Field(max_length=20)


class RequestLimited(ValueError):
    pass


class RemoteService:
    def __init__(self, runtime, options):
        self.runtime, self.options = runtime, options
        if options.public_url.startswith("http:") and not options.development_http:
            raise ValueError("Loopback HTTP requires the explicit development option.")
        self.store = RemoteStore(runtime.config.data_dir)
        self.sessions = {}
        self.memory_sources = {}
        self.session_lock = asyncio.Lock()
        self.attempts = defaultdict(deque)
        self.connections = {}
        self.capabilities = {}
        self.capability_seen = {}
        self.device_changes = asyncio.Condition()
        self.private_jobs = {}
        self.tasks = set()
        self.stopping = False
        self.pending_executors = 0
        from .remote_push import RemotePush

        self.push = RemotePush(self)
        from .remote_oauth import RemoteOAuth

        self.oauth = RemoteOAuth(self)
        runtime.mcp.remote_oauth = self.oauth
        runtime.native.remote = self

    async def start(self):
        await self.store.open(recover_jobs=True)
        self.runtime.config.enable_secret_encryption(self.store.cipher)
        from .remote_jobs import ExecutorJobs

        self.jobs = ExecutorJobs(self)
        self.runtime.db.notification_sink = self.push.enqueue
        task = asyncio.create_task(self.push.run())
        self.tasks.add(task)
        self.tasks.add(asyncio.create_task(self.maintain()))

    async def maintain(self):
        while not self.stopping:
            clock = time.time()
            cutoff = clock - self.runtime.config.settings.operation_log_retention_days * 86400
            await self.store.execute("DELETE FROM access_tokens WHERE expires<?", (clock,))
            await self.store.execute("DELETE FROM refresh_tokens WHERE expires<?", (clock,))
            await self.store.execute("DELETE FROM pairing_codes WHERE expires<?", (clock - 86400,))
            await self.store.execute(
                "DELETE FROM push_outbox WHERE state!='queued' AND created<?", (cutoff,)
            )
            await self.store.execute(
                "UPDATE executor_jobs SET arguments='',result='' WHERE updated<? AND state IN ('succeeded','failed','cancelled','expired','unknown')",
                (cutoff,),
            )
            await asyncio.sleep(600)

    async def close(self, *, close_storage=True):
        self.stopping = True
        self.runtime.db.notification_sink = None
        for connection in list(self.connections.values()):
            with contextlib.suppress(Exception):
                await connection.close(code=1001)
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if close_storage:
            await self.store.close()

    async def revoke_device(self, key):
        await self.store.revoke(key)
        await self.runtime.lab.close_device(key)
        if key in self.connections:
            await self.connections[key].close(code=1008)
        rows = await self.store.fetchall(
            "SELECT task_id FROM task_sessions WHERE device_id=?", (key,)
        )
        for row in rows:
            await self.runtime.tasks.cancel(row["task_id"])
        jobs = await self.store.fetchall(
            "SELECT id,device_id FROM executor_jobs WHERE session_id IN (SELECT id FROM client_sessions WHERE device_id=?) AND state IN ('queued','delivered','claimed','running')",
            (key,),
        )
        for job in jobs:
            await self.store.execute(
                "UPDATE executor_jobs SET state=CASE WHEN state='queued' THEN 'cancelled' ELSE 'unknown' END,updated=? WHERE id=? AND state IN ('queued','delivered','claimed','running')",
                (time.time(), job["id"]),
            )
            connection = self.connections.get(job["device_id"])
            if connection:
                with contextlib.suppress(Exception):
                    await connection.send_json({"type": "cancel", "id": job["id"]})
        for flow in list(self.oauth.pending.values()):
            if flow["device_id"] == key and not flow["future"].done():
                flow["future"].cancel()

    def limit(self, key, count=20, window=60):
        clock = time.monotonic()
        bucket = self.attempts[key]
        while bucket and bucket[0] < clock - window:
            bucket.popleft()
        if len(bucket) >= count:
            raise RequestLimited("Too many requests. Wait before trying again.")
        bucket.append(clock)

    async def context(self, device, session_id):
        async with self.session_lock:
            return await self._context(device, session_id)

    async def _context(self, device, session_id):
        try:
            session_id = str(UUID(session_id or device["id"]))
        except ValueError:
            raise ValueError("Invalid client session.") from None
        key = (device["id"], session_id)
        if key not in self.sessions:
            row = await self.store.fetchone(
                "SELECT * FROM client_sessions WHERE id=?", (session_id,)
            )
            if row and row["device_id"] != device["id"]:
                raise PermissionError("Session belongs to another device.")
            if not row:
                count = await self.store.fetchone(
                    "SELECT COUNT(*) AS n FROM client_sessions WHERE device_id=?", (device["id"],)
                )
                if count["n"] >= 4096:
                    raise ValueError(
                        "This device has too many sessions. Reuse an existing session."
                    )
                await self.store.execute(
                    "INSERT INTO client_sessions(id,device_id,scope,private,revision,updated) VALUES(?,?,'personal',0,0,?)",
                    (session_id, device["id"], time.time()),
                )
                row = {"scope": "personal", "private": False, "revision": 0, "executor_id": None}
            self.sessions[key] = {
                k: row[k] for k in ("scope", "private", "revision", "executor_id")
            }
            self.sessions[key]["private"] = bool(self.sessions[key]["private"])
        return ClientContext(device["id"], session_id, device["scopes"], self.sessions[key])

    async def save_session(self, client):
        s = client.session
        await self.store.execute(
            "UPDATE client_sessions SET scope=?,private=?,revision=?,executor_id=?,updated=? WHERE id=? AND device_id=?",
            (
                s["scope"],
                int(s["private"]),
                s["revision"],
                s.get("executor_id"),
                time.time(),
                client.session_id,
                client.device_id,
            ),
        )

    def native_device(self):
        client = active_client.get()
        if not client:
            return None
        selected = client.session.get("executor_id")
        candidates = [
            key
            for key, caps in self.capabilities.items()
            if key in self.connections
            and caps.get("native_scope") == client.session["scope"]
            and caps.get("native")
            and time.monotonic() - self.capability_seen.get(key, 0) < 45
        ]
        if selected:
            return selected if selected in candidates else None
        return candidates[0] if len(candidates) == 1 else None

    def native_status(self):
        key = self.native_device()
        caps = self.capabilities.get(key, {})
        return {
            "connected": bool(key),
            "locked": caps.get("locked", True),
            "voice_state": "unavailable",
            "executor_id": key,
            "screen_capture_granted": "screen.capture" in caps.get("native", []),
            "calendar_state": "authorized"
            if "calendar.list" in caps.get("native", [])
            else "unavailable",
        }

    async def invoke_native(self, operation, arguments, timeout, guard):
        from .policy import active_task

        client = active_client.get()
        key = self.native_device()
        if not client or not key:
            raise ValueError(
                "Select one connected desktop executor with the required local grants."
            )
        context = active_task.get(None)
        expected = dict(client.session)
        if context and (
            context.scope != expected["scope"] or context.private != expected["private"]
        ):
            raise PermissionError(
                "The originating session changed scope or privacy. Start a new native request."
            )

        def allowed():
            return (
                client.session == expected
                and self.native_device() == key
                and (guard is None or guard())
            )

        if not allowed():
            raise PermissionError("Native authority changed.")
        job = asyncio.create_task(
            self.jobs.submit(
                key,
                operation,
                arguments,
                scope=client.session["scope"],
                ctx=context,
                ttl=timeout,
            )
        )
        try:
            while not job.done():
                if self.runtime.gateway.blocked or not allowed():
                    raise PermissionError("Native authority changed; the operation was cancelled.")
                await asyncio.wait({job}, timeout=0.1)
            result = await job
            if not allowed():
                raise PermissionError("Native result discarded after authority changed.")
            if isinstance(result, dict) and result.get("error"):
                raise ValueError(str(result["error"])[:500])
            return result
        finally:
            if not job.done():
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)

    def secured(self, response, origin=None):
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization,Content-Type,X-Jarvis-Session,If-Match"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            if origin == self.options.public_url:
                response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    async def boundary(self, request: Request, call_next):
        origin = request.headers.get("origin")
        path = request.url.path
        allowed = {self.options.public_url, *self.options.allowed_origins}
        if request.headers.get("host", "") != urlsplit(self.options.public_url).netloc:
            return self.secured(JSONResponse({"detail": "Host is not allowed."}, status_code=400))
        if origin and origin not in allowed:
            return self.secured(JSONResponse({"detail": "Origin is not allowed."}, status_code=403))
        if request.method == "OPTIONS":
            return self.secured(JSONResponse({}), origin)
        if path == "/health":
            return self.secured(
                JSONResponse({"status": "ok", "service": "jarvis-remote", "protocol": 1}), origin
            )
        if (
            path.startswith(("/api/native", "/api/voice/live", "/api/events"))
            or path == "/api/voice/control"
        ):
            return self.secured(
                JSONResponse({"detail": "Use the authenticated device protocol."}, status_code=403),
                origin,
            )
        if path.startswith("/telephony/"):
            # Existing telephony ingress and provider-signature checks remain authoritative.
            return self.secured(await call_next(request), origin)
        public = path in {
            "/remote/v1/info",
            "/remote/v1/pair",
            "/remote/v1/refresh",
        } or path.startswith("/oauth/")
        protected = path.startswith(("/api/", "/remote/")) and not public
        executor_result = bool(
            request.method == "POST"
            and re.fullmatch(r"/remote/v1/executor-results/[a-zA-Z0-9-]{1,128}", path)
        )
        client_token = guard_token = None
        try:
            if protected:
                authorization = request.headers.get("authorization", "")
                early_device = await self.store.authenticate(
                    authorization[7:] if authorization.startswith("Bearer ") else ""
                )
                self.limit("device:" + early_device["id"], 600)
                if path == "/api/chat":
                    self.limit("chat:" + early_device["id"], 20)
                if path in {"/api/documents", "/api/apple-health/import", "/api/apple-health/native"} and request.method == "POST":
                    self.limit("documents:" + early_device["id"], 10)
                if early_device["kind"] != ("executor" if executor_result else "companion"):
                    raise PermissionError("Executor credentials cannot administer the core.")
            if public and path in {"/remote/v1/pair", "/remote/v1/refresh"}:
                self.limit("enrollment", 40)
                if request.cookies.get("jarvis_refresh") and origin != self.options.public_url:
                    raise PermissionError("Browser refresh requires the same origin.")
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                chunks, size = [], 0
                limit = (
                    65_000_000
                    if path == "/api/apple-health/import"
                    else 8192
                    if public
                    else 1_000_000
                    if executor_result
                    else 4_100_000
                    if path in {"/api/documents", "/api/lab/files", "/remote/v1/voice/transcribe"}
                    else 512_000
                )
                async with asyncio.timeout(120 if path == "/api/apple-health/import" else 15):
                    async for part in request.stream():
                        size += len(part)
                        if size > limit:
                            return self.secured(
                                JSONResponse(
                                    {"detail": "Request exceeds its size limit."}, status_code=413
                                ),
                                origin,
                            )
                        chunks.append(part)
                request._body = b"".join(chunks)
            if executor_result:
                request.state.remote_device = early_device
                return self.secured(await call_next(request), origin)
            if protected:
                authorization = request.headers.get("authorization", "")
                device = await self.store.authenticate(
                    authorization[7:] if authorization.startswith("Bearer ") else ""
                )
                if device["kind"] != "companion":
                    raise PermissionError("Executor credentials cannot administer the core.")
                required = "read" if request.method == "GET" else "control"
                if path == "/api/chat":
                    required = "chat"
                if (
                    path.startswith("/remote/v1/pairing-codes")
                    or (path.startswith("/api/settings") and request.method != "GET")
                    or path in {"/api/models/test", "/api/apple-health/consent"}
                    or path in {"/api/telephony/start", "/api/telephony/stop"}
                ):
                    required = "admin"
                if request.method != "GET" and re.match(
                    r"^/api/(?:mail/accounts|development/config|home-assistant/config|integrations/(?:mcp/config|[^/]+/connect))",
                    path,
                ):
                    required = "admin"
                if required not in device["scopes"]:
                    raise PermissionError("This device does not have the required grant.")
                client = await self.context(device, request.headers.get("x-jarvis-session", ""))
                request.state.remote_device = device
                client_token = active_client.set(client)
                scope = request.query_params.get("scope")
                if scope and scope != client.session["scope"]:
                    raise PermissionError("Source scope does not match the current session.")
                for key in ("session_id", "attachment_session"):
                    if (
                        request.query_params.get(key)
                        and request.query_params[key] != client.session_id
                    ):
                        raise PermissionError("Private sources belong to their client session.")
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    guard_token = owner_session_guard.set(
                        (client.session["scope"], client.session["revision"])
                    )
                await self.authorize_object(request, client)
            response = await call_next(request)
            return self.secured(response, origin)
        except PermissionError as error:
            detail = str(error)
            return self.secured(
                JSONResponse(
                    {"detail": detail},
                    status_code=401
                    if "session expired" in detail.lower() or "authentication" in detail.lower()
                    else 403,
                ),
                origin,
            )
        except (ValueError, TimeoutError, json.JSONDecodeError) as error:
            return self.secured(
                JSONResponse(
                    {"detail": str(error)[:300] or "Invalid request."},
                    status_code=429 if isinstance(error, RequestLimited) else 400,
                ),
                origin,
            )
        finally:
            if guard_token is not None:
                owner_session_guard.reset(guard_token)
            if client_token is not None:
                active_client.reset(client_token)

    async def authorize_object(self, request, client):
        path = request.url.path
        match = re.fullmatch(r"/api/tasks/([^/]+)(?:/[^/]+)?", path)
        if match:
            await self.runtime.require_task(match[1])
        match = re.fullmatch(r"/api/calls/([^/]+)/reconcile", path)
        if match:
            row = await self.runtime.db.fetchone(
                "SELECT task_id FROM calls WHERE id=?", (match[1],)
            )
            if not row:
                raise PermissionError("Call is unavailable.")
            if row["task_id"]:
                await self.runtime.require_task(row["task_id"])
            elif client.session["scope"] != "personal":
                raise PermissionError("Manual calls belong to the personal scope.")
        match = re.fullmatch(r"/api/(approvals|effects)/([^/]+)(?:/reconcile)?", path)
        if match:
            query = (
                "SELECT task_id FROM approvals WHERE id=?"
                if match[1] == "approvals"
                else "SELECT task_id FROM effects WHERE operation_key=?"
            )
            row = await self.runtime.db.fetchone(query, (match[2],))
            if not row:
                raise PermissionError("Operation is unavailable.")
            await self.runtime.require_task(row["task_id"])
        match = re.fullmatch(r"/api/schedules/([^/]+)", path)
        if match:
            row = await self.runtime.db.fetchone(
                "SELECT scope FROM schedules WHERE id=?", (match[1],)
            )
            if not row or row["scope"] != client.session["scope"]:
                raise PermissionError("Routine is unavailable in this scope.")
        if path == "/api/settings" and request.method != "GET":
            changes = json.loads(await request.body())
            from .remote_settings import COMPANION_SETTINGS
            if not isinstance(changes, dict) or set(changes) - COMPANION_SETTINGS:
                raise PermissionError("These settings require server administration on the host.")
            settings = self.runtime.config.settings
            changed_destination = any(
                k in changes and changes[k] != getattr(settings, k)
                for k in ("cloud_provider", "cloud_base_url")
            )
            if (
                changed_destination
                and settings.secret("cloud_api_key")
                and not changes.get("cloud_api_key")
            ):
                raise PermissionError(
                    "Changing the provider or endpoint requires a new dedicated key."
                )
            if (
                changes.get("second_brain_url", settings.second_brain_url)
                != settings.second_brain_url
                and settings.second_brain_auth == "bearer"
                and settings.secret("second_brain_token")
                and not changes.get("second_brain_token")
            ):
                raise PermissionError(
                    "Changing the memory endpoint requires a new dedicated token."
                )
        # FastAPI accepts JSON without a Content-Type and with application/*+json
        # or mixed-case media types. Authority checks must inspect those bodies
        # too, before a route can create work in another scope or profile.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/api/apple-health/import":
            body = json.loads(await request.body() or b"{}")
            if isinstance(body, dict):
                if (
                    "scope" in body
                    and path != "/api/voice/session"
                    and body["scope"] != client.session["scope"]
                ):
                    raise PermissionError("Request scope does not match this session.")
                if path in {"/api/chat", "/api/models/test"} and body.get("profile") not in {
                    None,
                    "cloud",
                }:
                    raise PermissionError("The remote core uses the configured cloud model.")
                for key in ("session_id", "attachment_session"):
                    if body.get(key) and str(body[key]) != client.session_id:
                        raise PermissionError("Private attachments belong to their client session.")

    async def visible_events(self, rows, client):
        result = []
        for row in rows:
            if row["task_id"]:
                task = await self.runtime.db.fetchone(
                    "SELECT * FROM tasks WHERE id=?", (row["task_id"],)
                )
                if await self.store.task_visible(task, client):
                    if row["type"] not in {"native.operation", "speech.requested", "speech.stop"}:
                        result.append(row)
            elif row["type"] in {"settings.updated", "service.status", "schedule.updated"}:
                result.append({**row, "data": {}})
            elif row["type"] == "notification.created":
                result.append(
                    {**row, "data": {"title": "Jarvis", "body": "A notification is available."}}
                )
        return result

    def install(self, app):
        @app.exception_handler(RequestLimited)
        async def rate_limited(request, error):
            return JSONResponse(
                {"detail": str(error)}, status_code=429, headers={"Retry-After": "60"}
            )

        self.push.install(app)
        self.oauth.install(app)
        from .remote_audio import install_audio

        install_audio(app, self)

        @app.websocket("/remote/v1/voice/live")
        async def companion_voice(websocket: WebSocket):
            from .remote_voice import voice_socket
            await voice_socket(self, websocket)

        @app.get("/remote/v1/info")
        async def info():
            return {
                "service": "jarvis-remote",
                "protocol": 1,
                "public_url": self.options.public_url,
            }

        @app.post("/remote/v1/pair")
        async def pair(data: Enrollment):
            result = await self.store.enroll(data.code, data.name, data.platform)
            response = JSONResponse(
                result
                if data.platform != "web"
                else {k: v for k, v in result.items() if k != "refresh_token"}
            )
            if data.platform == "web":
                response.set_cookie(
                    "jarvis_refresh",
                    result["refresh_token"],
                    max_age=30 * 86400,
                    secure=not self.options.development_http,
                    httponly=True,
                    samesite="strict",
                    path="/remote/",
                )
            return response

        @app.post("/remote/v1/refresh")
        async def refresh(request: Request):
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("refresh_token", ""), str):
                raise ValueError("Invalid refresh request.")
            browser = bool(request.cookies.get("jarvis_refresh"))
            result = await self.store.refresh(
                request.cookies.get("jarvis_refresh") if browser else body.get("refresh_token", "")
            )
            response = JSONResponse(
                {k: v for k, v in result.items() if not browser or k != "refresh_token"}
            )
            if browser:
                response.set_cookie(
                    "jarvis_refresh",
                    result["refresh_token"],
                    max_age=30 * 86400,
                    secure=not self.options.development_http,
                    httponly=True,
                    samesite="strict",
                    path="/remote/",
                )
            return response

        @app.get("/remote/v1/devices")
        async def devices():
            rows = await self.store.fetchall(
                "SELECT id,name,kind,platform,capabilities,created,revoked,last_seen FROM devices ORDER BY created"
            )
            for row in rows:
                row["capabilities"] = json.loads(row["capabilities"])
                scope = active_client.get().session["scope"]
                caps = row["capabilities"]
                caps["workspaces"] = [
                    w for w in caps.get("workspaces", []) if w.get("scope") == scope
                ]
                if caps.get("native_scope") != scope:
                    caps.pop("native", None)
                row["connected"] = row["id"] in self.connections
            return rows

        @app.post("/remote/v1/session/executor")
        async def select_executor(request: Request):
            data = await request.json()
            client = active_client.get()
            key = data.get("device_id")
            if key:
                row = await self.store.fetchone(
                    "SELECT id FROM devices WHERE id=? AND kind='executor' AND revoked IS NULL",
                    (key,),
                )
                if not row:
                    raise PermissionError("Executor is unavailable.")
            client.session["executor_id"] = key
            client.session["revision"] += 1
            await self.save_session(client)
            return {"executor_id": key}

        @app.post("/remote/v1/executor-results/{key}")
        async def executor_result_upload(key: str, request: Request):
            data = await request.json()
            if data.get("id") != key or data.get("type") not in {"result", "reconcile"}:
                raise ValueError("Invalid executor receipt.")
            await self.jobs.receipt(request.state.remote_device["id"], data)
            return {"accepted": True}

        @app.post("/remote/v1/pairing-codes")
        async def pairing_code(request: Request):
            data = await request.json()
            return {
                "code": await self.store.pairing_code(
                    data.get("kind", "companion"), owner=data.get("owner") is True
                ),
                "expires_in": 600,
            }

        @app.post("/remote/v1/devices/{key}/revoke")
        async def revoke(key: str, request: Request):
            device = request.state.remote_device
            if "admin" not in device["scopes"] and key != device["id"]:
                raise PermissionError("Only an administrator can revoke another device.")
            await self.revoke_device(key)
            response = JSONResponse({"state": "revoked"})
            if key == device["id"]:
                response.delete_cookie("jarvis_refresh", path="/remote/")
            return response

        @app.get("/remote/v1/events")
        async def events(after: int = 0):
            if after < 0:
                raise ValueError("Invalid event cursor.")
            rows = await self.runtime.db.wait_events(after, timeout=10)
            return {
                "cursor": rows[-1]["sequence"] if rows else after,
                "events": await self.visible_events(rows, active_client.get()),
            }

        @app.websocket("/remote/v1/executor")
        async def executor(websocket: WebSocket):
            await self.jobs.socket(websocket)

        @app.get("/remote/v1/jobs")
        async def jobs():
            client = active_client.get()
            rows = await self.store.fetchall(
                "SELECT id,device_id,task_id,operation,state,created,expires,updated,private,session_id FROM executor_jobs WHERE scope=? ORDER BY created DESC LIMIT 100",
                (client.session["scope"],),
            )
            return [
                row for row in rows if not row["private"] or row["session_id"] == client.session_id
            ]

        @app.post("/remote/v1/jobs/{key}/cancel")
        async def cancel_job(key: str):
            client = active_client.get()
            row = await self.store.fetchone(
                "SELECT * FROM executor_jobs WHERE id=? AND scope=?", (key, client.session["scope"])
            )
            if not row or (row["private"] and row["session_id"] != client.session_id):
                raise PermissionError("Job is unavailable in this session.")
            if row["state"] not in {"queued", "delivered", "claimed", "running"}:
                return {"state": row["state"]}
            state = "cancelled" if row["state"] == "queued" else "unknown"
            await self.store.execute(
                "UPDATE executor_jobs SET state=?,updated=? WHERE id=? AND state IN ('queued','delivered','claimed','running')",
                (state, time.time(), key),
            )
            connection = self.connections.get(row["device_id"])
            if connection:
                with contextlib.suppress(Exception):
                    await connection.send_json({"type": "cancel", "id": key})
            return {"state": state}
