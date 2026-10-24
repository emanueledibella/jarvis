from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


def now() -> str:
    return datetime.now(UTC).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS conversations(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'personal',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 role TEXT NOT NULL, content TEXT NOT NULL, task_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, conversation_id TEXT, title TEXT NOT NULL, prompt TEXT NOT NULL,
 state TEXT NOT NULL, profile TEXT NOT NULL, scope TEXT NOT NULL, private INTEGER NOT NULL DEFAULT 0,
 channel TEXT NOT NULL DEFAULT 'text', result TEXT NOT NULL DEFAULT '', error TEXT,
 model TEXT, steps INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 schedule_id TEXT, checkpoint_id TEXT, usage TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS events(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, type TEXT NOT NULL,
 task_id TEXT, data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_task ON events(task_id,sequence);
CREATE TABLE IF NOT EXISTS approvals(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL, tool TEXT NOT NULL, arguments TEXT NOT NULL,
 arguments_hash TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, decided_at TEXT);
CREATE TABLE IF NOT EXISTS effects(
 operation_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, tool TEXT NOT NULL,
 arguments_hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT, provider_id TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL, kind TEXT NOT NULL,
 expression TEXT NOT NULL, timezone TEXT NOT NULL, next_run_at TEXT, enabled INTEGER NOT NULL DEFAULT 1,
 mode TEXT NOT NULL DEFAULT 'reminder', monitor TEXT NOT NULL DEFAULT '{}',
 profile TEXT NOT NULL, scope TEXT NOT NULL, misfire_policy TEXT NOT NULL,
 grace_seconds INTEGER NOT NULL DEFAULT 300, notify TEXT NOT NULL DEFAULT 'desktop',
 call_authorized INTEGER NOT NULL DEFAULT 0, last_fingerprint TEXT,
 last_run_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_runs(
 schedule_id TEXT NOT NULL, due_at TEXT NOT NULL, task_id TEXT, state TEXT NOT NULL,
 UNIQUE(schedule_id,due_at));
CREATE TABLE IF NOT EXISTS memory_outbox(
 id TEXT PRIMARY KEY, task_id TEXT, payload TEXT NOT NULL, state TEXT NOT NULL,
 source_id TEXT, revision INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(
 id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 body TEXT NOT NULL, task_id TEXT, read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls(
 id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, task_id TEXT,
 direction TEXT NOT NULL, state TEXT NOT NULL, provider_id TEXT UNIQUE,
 auth_verified INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 reservation_usd REAL NOT NULL DEFAULT 0, detail TEXT, created_at TEXT NOT NULL, ended_at TEXT);
CREATE TABLE IF NOT EXISTS artifacts(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
 sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_usage(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL, month TEXT NOT NULL, state TEXT NOT NULL,
 reservation_usd REAL NOT NULL, actual_usd REAL, input_tokens INTEGER, output_tokens INTEGER,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS controls(name TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()
        self.changed = asyncio.Condition()
        self.volatile: OrderedDict[str, dict] = OrderedDict()

    async def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        os.chmod(self.path, 0o600)

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def execute(self, sql: str, params=()):
        assert self.conn
        async with self.lock:
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cursor.rowcount

    async def fetchone(self, sql: str, params=()) -> dict | None:
        assert self.conn
        async with self.lock:
            cursor = await self.conn.execute(sql, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, sql: str, params=()) -> list[dict]:
        assert self.conn
        async with self.lock:
            cursor = await self.conn.execute(sql, params)
            return [dict(row) for row in await cursor.fetchall()]

    async def emit(self, event_type: str, data: dict, task_id: str | None = None, *, private=False):
        event_id = uid()
        if private:
            self.volatile[event_id] = data
            while len(self.volatile) > 1000:
                self.volatile.popitem(last=False)
        await self.execute(
            "INSERT INTO events(id,type,task_id,data,created_at) VALUES(?,?,?,?,?)",
            (
                event_id,
                event_type,
                task_id,
                json.dumps({} if private else data, ensure_ascii=False),
                now(),
            ),
        )
        async with self.changed:
            self.changed.notify_all()

    async def events(self, after: int, limit=200) -> list[dict]:
        rows = await self.fetchall(
            "SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit)
        )
        for row in rows:
            row["data"] = self.volatile.get(row["id"], json.loads(row["data"]))
        return rows

    async def wait_events(self, after: int, timeout: float = 20) -> list[dict]:
        # Hold the condition while inspecting, so an event cannot be missed between
        # SELECT and wait. emit commits before taking this condition.
        async with self.changed:
            rows = await self.events(after)
            if rows:
                return rows
            try:
                await asyncio.wait_for(self.changed.wait(), timeout)
            except TimeoutError:
                pass
        return await self.events(after)

    async def notification(self, title: str, body: str, fingerprint: str, task_id=None):
        inserted = await self.execute(
            "INSERT OR IGNORE INTO notifications(id,fingerprint,title,body,task_id,created_at) VALUES(?,?,?,?,?,?)",
            (uid(), fingerprint, title, body, task_id, now()),
        )
        if inserted:
            await self.emit("notification.created", {"title": title, "body": body}, task_id)
