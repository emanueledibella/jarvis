"""Single-owner device enrollment and rotating sessions. Only token hashes persist."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet

from .db import Database, uid
from .platforms import protect_path

REMOTE_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,platform TEXT NOT NULL,
 scopes TEXT NOT NULL,capabilities TEXT NOT NULL DEFAULT '{}',created REAL NOT NULL,
 revoked REAL,last_seen REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pairing_codes(
 hash TEXT PRIMARY KEY,kind TEXT NOT NULL,scopes TEXT NOT NULL,expires REAL NOT NULL,used REAL);
CREATE TABLE IF NOT EXISTS refresh_tokens(
 hash TEXT PRIMARY KEY,family TEXT NOT NULL,device_id TEXT NOT NULL,expires REAL NOT NULL,
 used INTEGER NOT NULL DEFAULT 0,revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS access_tokens(
 hash TEXT PRIMARY KEY,family TEXT NOT NULL,device_id TEXT NOT NULL,expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS access_device ON access_tokens(device_id);
CREATE TABLE IF NOT EXISTS client_sessions(
 id TEXT PRIMARY KEY,device_id TEXT NOT NULL,scope TEXT NOT NULL,private INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL,executor_id TEXT);
CREATE TABLE IF NOT EXISTS task_sessions(
 task_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,device_id TEXT NOT NULL,scope TEXT NOT NULL,private INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS executor_jobs(
 id TEXT PRIMARY KEY,device_id TEXT NOT NULL,task_id TEXT,session_id TEXT,operation TEXT NOT NULL,
 arguments TEXT NOT NULL,argument_hash TEXT NOT NULL,private INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL,result TEXT NOT NULL DEFAULT '',created REAL NOT NULL,expires REAL NOT NULL,updated REAL NOT NULL,scope TEXT NOT NULL DEFAULT 'personal');
CREATE INDEX IF NOT EXISTS jobs_device ON executor_jobs(device_id,state);
CREATE TABLE IF NOT EXISTS push_devices(
 device_id TEXT PRIMARY KEY,platform TEXT NOT NULL,token TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS push_outbox(
 id TEXT PRIMARY KEY,device_id TEXT NOT NULL,event_id TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',
 attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL,created REAL NOT NULL DEFAULT 0,UNIQUE(device_id,event_id));
"""

COMPANION_SCOPES = frozenset({"read", "chat", "control"})
OWNER_SCOPES = COMPANION_SCOPES | {"admin"}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RemoteStore(Database):
    def __init__(self, directory: Path):
        super().__init__(directory / "remote.sqlite3")
        self.directory = directory
        self.cipher = None

    async def open(self, *, recover_jobs=False):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        protect_path(self.directory, directory=True)
        key_path = self.directory / "server-secret.key"
        try:
            import os

            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(Fernet.generate_key())
        except FileExistsError:
            pass
        protect_path(key_path)
        self.cipher = Fernet(key_path.read_bytes())
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(REMOTE_SCHEMA)
        session_columns = await (
            await self.conn.execute("PRAGMA table_info(client_sessions)")
        ).fetchall()
        if "executor_id" not in {row[1] for row in session_columns}:
            await self.conn.execute("ALTER TABLE client_sessions ADD COLUMN executor_id TEXT")
        job_columns = await (await self.conn.execute("PRAGMA table_info(executor_jobs)")).fetchall()
        if "scope" not in {row[1] for row in job_columns}:
            await self.conn.execute(
                "ALTER TABLE executor_jobs ADD COLUMN scope TEXT NOT NULL DEFAULT 'personal'"
            )
        columns = await (await self.conn.execute("PRAGMA table_info(push_outbox)")).fetchall()
        if "created" not in {row[1] for row in columns}:
            await self.conn.execute(
                "ALTER TABLE push_outbox ADD COLUMN created REAL NOT NULL DEFAULT 0"
            )
        await self.conn.commit()
        protect_path(self.path)
        if recover_jobs:
            await self.execute(
                "UPDATE executor_jobs SET state='unknown',updated=? WHERE state IN ('delivered','claimed','running')",
                (time.time(),),
            )
            await self.execute(
                "UPDATE executor_jobs SET state='expired',updated=? WHERE private=1 AND state='queued'",
                (time.time(),),
            )

    def encrypt(self, value) -> str:
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

    def decrypt(self, value: str):
        return json.loads(self.cipher.decrypt(value.encode()))

    async def pairing_code(self, kind="companion", *, owner=False, ttl=600) -> str:
        if kind not in {"companion", "executor"} or (owner and kind != "companion"):
            raise ValueError("Invalid device kind.")
        scopes = (
            OWNER_SCOPES if owner else COMPANION_SCOPES if kind == "companion" else {"executor"}
        )
        code = secrets.token_urlsafe(24)
        await self.execute(
            "INSERT INTO pairing_codes(hash,kind,scopes,expires) VALUES(?,?,?,?)",
            (token_hash(code), kind, json.dumps(sorted(scopes)), time.time() + ttl),
        )
        return code

    async def _issue(self, device_id, family):
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        await self.conn.execute(
            "INSERT INTO access_tokens VALUES(?,?,?,?)",
            (token_hash(access), family, device_id, time.time() + 300),
        )
        await self.conn.execute(
            "INSERT INTO refresh_tokens(hash,family,device_id,expires) VALUES(?,?,?,?)",
            (token_hash(refresh), family, device_id, time.time() + 30 * 86400),
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 300,
            "device_id": device_id,
        }

    async def enroll(self, code, name, platform):
        if platform not in {"web", "macos", "windows", "android", "ios", "linux"}:
            raise ValueError("Invalid platform.")
        async with self.lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = await (
                    await self.conn.execute(
                        "SELECT * FROM pairing_codes WHERE hash=? AND used IS NULL AND expires>?",
                        (token_hash(code), time.time()),
                    )
                ).fetchone()
                if not row:
                    raise PermissionError("Pairing code is invalid, expired, or already used.")
                device_id = uid()
                await self.conn.execute(
                    "UPDATE pairing_codes SET used=? WHERE hash=?", (time.time(), row["hash"])
                )
                await self.conn.execute(
                    "INSERT INTO devices(id,name,kind,platform,scopes,created) VALUES(?,?,?,?,?,?)",
                    (device_id, name, row["kind"], platform, row["scopes"], time.time()),
                )
                result = await self._issue(device_id, uid())
                await self.conn.commit()
                return {**result, "kind": row["kind"], "scopes": json.loads(row["scopes"])}
            except BaseException:
                await self.conn.rollback()
                raise

    async def refresh(self, token):
        async with self.lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = await (
                    await self.conn.execute(
                        "SELECT r.*,d.revoked AS device_revoked,d.scopes,d.kind FROM refresh_tokens r JOIN devices d ON d.id=r.device_id WHERE hash=?",
                        (token_hash(token),),
                    )
                ).fetchone()
                if (
                    not row
                    or row["device_revoked"]
                    or row["revoked"]
                    or row["expires"] <= time.time()
                ):
                    raise PermissionError("Session expired or revoked. Pair the device again.")
                if row["used"]:
                    await self.conn.execute(
                        "UPDATE refresh_tokens SET revoked=1 WHERE family=?", (row["family"],)
                    )
                    await self.conn.execute(
                        "DELETE FROM access_tokens WHERE family=?", (row["family"],)
                    )
                    await self.conn.commit()
                    raise PermissionError("Refresh replay detected. This session was revoked.")
                await self.conn.execute(
                    "UPDATE refresh_tokens SET used=1 WHERE hash=?", (row["hash"],)
                )
                result = await self._issue(row["device_id"], row["family"])
                await self.conn.commit()
                return {**result, "scopes": json.loads(row["scopes"]), "kind": row["kind"]}
            except BaseException:
                await self.conn.rollback()
                raise

    async def authenticate(self, token):
        if not token or len(token) > 256:
            raise PermissionError("Device authentication required.")
        row = await self.fetchone(
            "SELECT d.*,a.family FROM access_tokens a JOIN devices d ON d.id=a.device_id WHERE a.hash=? AND a.expires>? AND d.revoked IS NULL",
            (token_hash(token), time.time()),
        )
        if not row:
            raise PermissionError("Device session expired or revoked.")
        row["scopes"] = frozenset(json.loads(row["scopes"]))
        row["capabilities"] = json.loads(row["capabilities"])
        return row

    async def revoke(self, device_id):
        await self.execute("UPDATE devices SET revoked=? WHERE id=?", (time.time(), device_id))
        await self.execute("DELETE FROM access_tokens WHERE device_id=?", (device_id,))
        await self.execute("UPDATE refresh_tokens SET revoked=1 WHERE device_id=?", (device_id,))
        await self.execute("DELETE FROM push_devices WHERE device_id=?", (device_id,))
        await self.execute(
            "UPDATE executor_jobs SET state='cancelled',updated=? WHERE device_id=? AND state='queued'",
            (time.time(), device_id),
        )

    async def bind_task(self, task_id, client, scope, private):
        prior = await self.fetchone("SELECT * FROM task_sessions WHERE task_id=?", (task_id,))
        if prior and prior["private"] and prior["session_id"] != client.session_id:
            raise PermissionError("Task belongs to another private session.")
        await self.execute(
            "INSERT OR IGNORE INTO task_sessions VALUES(?,?,?,?,?)",
            (task_id, client.session_id, client.device_id, scope, int(private)),
        )

    async def task_visible(self, task, client):
        if not client:
            return True
        if not task or task.get("scope") != client.session["scope"]:
            return False
        if not task.get("private"):
            return True
        bound = await self.fetchone(
            "SELECT session_id FROM task_sessions WHERE task_id=?", (task["id"],)
        )
        return bool(
            client.session["private"] and bound and bound["session_id"] == client.session_id
        )
