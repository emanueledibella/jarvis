"""Durable server-side dispatch. Unknown effects require reconciliation, never replay."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from .db import uid
from .remote_context import active_client
from .remote_protocol import NATIVE_OPERATIONS, OPERATIONS, digest

TERMINAL = {"succeeded", "failed", "cancelled", "expired", "unknown"}


class ExecutorJobs:
    def __init__(self, remote):
        self.remote, self.store, self.runtime = remote, remote.store, remote.runtime

    async def devices(self, scope):
        rows = await self.store.fetchall(
            "SELECT id,name,platform,capabilities,last_seen FROM devices WHERE kind='executor' AND revoked IS NULL"
        )
        for row in rows:
            caps = json.loads(row["capabilities"])
            row["workspaces"] = [w for w in caps.get("workspaces", []) if w.get("scope") == scope]
            row["native"] = caps.get("native", []) if caps.get("native_scope") == scope else []
            row.pop("capabilities")
            row["connected"] = row["id"] in self.remote.connections
        return rows

    async def submit(
        self, device_id, operation, arguments, *, scope, ctx=None, ttl=120, queue_if_offline=False
    ):
        if operation not in OPERATIONS or not isinstance(arguments, dict):
            raise ValueError("Unsupported executor operation.")
        encoded = json.dumps(arguments, ensure_ascii=False)
        if len(encoded.encode()) > 48_000:
            raise ValueError("Narrow the operation: executor arguments exceed their limit.")
        device = await self.store.fetchone(
            "SELECT * FROM devices WHERE id=? AND kind='executor' AND revoked IS NULL", (device_id,)
        )
        if not device:
            raise PermissionError("Executor is unavailable.")
        capabilities = json.loads(device["capabilities"])
        workspace = next(
            (
                w
                for w in capabilities.get("workspaces", [])
                if w.get("id") == arguments.get("workspace") and w.get("scope") == scope
            ),
            None,
        )
        permission = (
            "command"
            if operation == "workspace_command"
            else "write"
            if operation in {"workspace_write", "workspace_mkdir"}
            else "read"
        )
        native_granted = (
            operation in NATIVE_OPERATIONS
            and capabilities.get("native_scope") == scope
            and operation in capabilities.get("native", [])
        )
        if (operation in NATIVE_OPERATIONS and not native_granted) or (
            operation not in NATIVE_OPERATIONS
            and (not workspace or workspace.get(permission) is not True)
        ):
            raise PermissionError(
                "The device has not granted this operation in this workspace and scope."
            )
        client = active_client.get()
        private = bool(
            (ctx and ctx.private)
            or (client and client.session["private"])
            or operation == "screen.capture"
        )
        connected = device_id in self.remote.connections
        if not connected and (private or not queue_if_offline):
            raise ValueError(
                "The device is offline. Waiting requires an explicit expiring request; private operations cannot be queued offline."
            )
        ttl = max(5, min(int(ttl), 600))
        fingerprint = digest([device_id, operation, arguments])
        key = digest([ctx.id, fingerprint]) if ctx else uid()
        session_id = client.session_id if client else None
        clock = time.time()
        row = await self.store.fetchone("SELECT * FROM executor_jobs WHERE id=?", (key,))
        if not row:
            payload = {"arguments": arguments, "scope": scope}
            if private:
                self.remote.private_jobs[key] = payload
            await self.store.execute(
                "INSERT INTO executor_jobs(id,device_id,task_id,session_id,operation,arguments,argument_hash,private,state,created,expires,updated,scope) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    device_id,
                    ctx.id if ctx else None,
                    session_id,
                    operation,
                    "" if private else self.store.encrypt(payload),
                    fingerprint,
                    int(private),
                    "queued",
                    clock,
                    clock + ttl,
                    clock,
                    scope,
                ),
            )
        try:
            while True:
                row = await self.store.fetchone("SELECT * FROM executor_jobs WHERE id=?", (key,))
                if row["state"] in TERMINAL:
                    if row["state"] == "succeeded":
                        result = (
                            self.remote.private_jobs.get(key, {}).get("result")
                            if private
                            else self.store.decrypt(row["result"])
                            if row["result"]
                            else {
                                "state": "succeeded",
                                "result_expired": True,
                                "message": "The result retention period ended. The completed operation was not repeated.",
                            }
                        )
                        if result is None:
                            raise ValueError("Private result expired; it cannot be replayed.")
                        return result
                    raise ValueError(
                        f"Device job {key}: {row['state']}. Inspect or reconcile its recorded outcome before starting a replacement."
                    )
                if time.time() > row["expires"]:
                    state = "expired" if row["state"] == "queued" else "unknown"
                    await self.store.execute(
                        "UPDATE executor_jobs SET state=?,updated=? WHERE id=? AND state NOT IN ('succeeded','failed','cancelled')",
                        (state, time.time(), key),
                    )
                    continue
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            await self.store.execute(
                "UPDATE executor_jobs SET state=CASE WHEN state='queued' THEN 'cancelled' ELSE 'unknown' END,updated=? WHERE id=? AND state NOT IN ('succeeded','failed','cancelled','expired','unknown')",
                (time.time(), key),
            )
            connection = self.remote.connections.get(device_id)
            if connection:
                with contextlib.suppress(Exception):
                    await connection.send_json({"type": "cancel", "id": key})
            raise
        finally:
            if private:
                self.remote.private_jobs.pop(key, None)

    async def socket(self, websocket):
        options = self.remote.options
        if websocket.headers.get("host") != options.public_url.split("://", 1)[
            1
        ] or websocket.headers.get("origin") not in {
            None,
            options.public_url,
            *options.allowed_origins,
        }:
            await websocket.close(code=1008)
            return
        if self.remote.pending_executors >= 8 or len(self.remote.connections) >= 16:
            await websocket.close(code=1013)
            return
        self.remote.pending_executors += 1
        await websocket.accept()
        device = None
        pending = True
        try:
            async with asyncio.timeout(5):
                raw = await websocket.receive_text()
            if len(raw.encode()) > 1024:
                raise PermissionError("Invalid authentication frame.")
            auth = json.loads(raw)
            token = auth.get("access_token", "")
            device = await self.store.authenticate(token)
            if (
                auth.get("type") != "auth"
                or device["kind"] != "executor"
                or device["scopes"] != {"executor"}
            ):
                raise PermissionError("Executor authentication required.")
            old = self.remote.connections.get(device["id"])
            if old:
                await old.close(code=1008)
            self.remote.connections[device["id"]] = websocket
            self.remote.pending_executors -= 1
            pending = False
            await websocket.send_json({"type": "ready", "protocol": 1, "device_id": device["id"]})
            hello = False
            while not self.remote.stopping:
                await self.store.authenticate(token)
                if hello:
                    await self.deliver(device["id"], websocket)
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), 1)
                except TimeoutError:
                    continue
                if len(raw.encode()) > 64_000:
                    raise ValueError("Executor message exceeds its limit.")
                data = json.loads(raw)
                kind = data.get("type")
                if kind == "hello":
                    capabilities = data.get("capabilities", {})
                    if (
                        len(json.dumps(capabilities).encode()) > 12000
                        or not isinstance(capabilities.get("workspaces"), list)
                        or len(capabilities["workspaces"]) > 32
                    ):
                        raise ValueError("Invalid device capabilities.")
                    if (
                        not isinstance(capabilities.get("native", []), list)
                        or not set(capabilities.get("native", [])) <= NATIVE_OPERATIONS
                        or capabilities.get("native_scope", "personal") not in {"personal", "work"}
                    ):
                        raise ValueError("Invalid native capability grant.")
                    for workspace in capabilities["workspaces"]:
                        if not isinstance(workspace.get("id"), str) or workspace.get(
                            "scope"
                        ) not in {"personal", "work"}:
                            raise ValueError("Invalid workspace grant.")
                    await self.store.execute(
                        "UPDATE devices SET capabilities=?,last_seen=? WHERE id=?",
                        (json.dumps(capabilities), time.time(), device["id"]),
                    )
                    hello = True
                    self.remote.capabilities[device["id"]] = capabilities
                    self.remote.capability_seen[device["id"]] = time.monotonic()
                    async with self.remote.device_changes:
                        self.remote.device_changes.notify_all()
                elif kind == "ping":
                    await self.store.execute(
                        "UPDATE devices SET last_seen=? WHERE id=?", (time.time(), device["id"])
                    )
                    await websocket.send_json({"type": "pong"})
                elif kind in {"claimed", "running", "result", "reconcile"}:
                    await self.receipt(device["id"], data)
                    await websocket.send_json({"type": "receipt", "id": data["id"], "kind": kind})
                elif kind == "auth":
                    candidate = await self.store.authenticate(data.get("access_token", ""))
                    if candidate["id"] != device["id"]:
                        raise PermissionError("Device identity cannot change on an open channel.")
                    token = data["access_token"]
                else:
                    raise ValueError("Unknown executor message.")
        except (Exception, asyncio.CancelledError):
            with contextlib.suppress(Exception):
                await websocket.close(code=1008)
        finally:
            if pending:
                self.remote.pending_executors -= 1
            if device and self.remote.connections.get(device["id"]) is websocket:
                self.remote.connections.pop(device["id"], None)
                self.remote.capabilities.pop(device["id"], None)
                self.remote.capability_seen.pop(device["id"], None)
                await self.store.execute(
                    "UPDATE executor_jobs SET state='unknown',updated=? WHERE device_id=? AND state IN ('delivered','claimed','running')",
                    (time.time(), device["id"]),
                )

    async def deliver(self, device_id, websocket):
        await self.store.execute(
            "UPDATE executor_jobs SET state='expired',updated=? WHERE device_id=? AND state='queued' AND expires<?",
            (time.time(), device_id, time.time()),
        )
        busy = await self.store.fetchone(
            "SELECT id FROM executor_jobs WHERE device_id=? AND state IN ('delivered','claimed','running') LIMIT 1",
            (device_id,),
        )
        if busy:
            return
        row = await self.store.fetchone(
            "SELECT * FROM executor_jobs WHERE device_id=? AND state='queued' ORDER BY created LIMIT 1",
            (device_id,),
        )
        if not row:
            return
        payload = (
            self.remote.private_jobs.get(row["id"])
            if row["private"]
            else self.store.decrypt(row["arguments"])
        )
        if not payload or self.runtime.gateway.blocked:
            await self.store.execute(
                "UPDATE executor_jobs SET state='cancelled',updated=? WHERE id=?",
                (time.time(), row["id"]),
            )
            return
        await self.store.execute(
            "UPDATE executor_jobs SET state='delivered',updated=? WHERE id=? AND state='queued'",
            (time.time(), row["id"]),
        )
        await websocket.send_json(
            {
                "type": "job",
                "id": row["id"],
                "operation": row["operation"],
                "arguments": payload["arguments"],
                "scope": payload["scope"],
                "argument_hash": row["argument_hash"],
                "expires": row["expires"],
                "private": bool(row["private"]),
            }
        )

    async def receipt(self, device_id, data):
        row = await self.store.fetchone(
            "SELECT * FROM executor_jobs WHERE id=? AND device_id=?", (data.get("id"), device_id)
        )
        if not row or data.get("argument_hash") != row["argument_hash"]:
            raise PermissionError("Receipt does not match an assigned operation.")
        if row["state"] in {"succeeded", "failed", "cancelled", "expired"}:
            return
        kind = data["type"]
        if kind in {"claimed", "running"}:
            if row["state"] == "unknown":
                return
            if row["expires"] <= time.time():
                raise PermissionError("Job authority expired.")
            await self.store.execute(
                "UPDATE executor_jobs SET state=?,updated=? WHERE id=?",
                (kind, time.time(), row["id"]),
            )
        else:
            state = data.get("state")
            if state not in {"succeeded", "failed", "unknown", "cancelled"}:
                raise ValueError("Invalid executor outcome.")
            result = data.get("result", {})
            if len(json.dumps(result).encode()) > 1_000_000:
                raise ValueError("Executor result exceeds its limit.")
            if row["private"]:
                if row["id"] in self.remote.private_jobs:
                    self.remote.private_jobs[row["id"]]["result"] = result
            await self.store.execute(
                "UPDATE executor_jobs SET state=?,result=?,updated=? WHERE id=?",
                (
                    state,
                    "" if row["private"] else self.store.encrypt(result),
                    time.time(),
                    row["id"],
                ),
            )
