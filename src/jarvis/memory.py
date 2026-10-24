from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from .db import Database, now, uid


class Memory:
    def __init__(self, config, db: Database, mcp):
        self.config, self.db, self.mcp = config, db, mcp
        self.suspended = False

    async def enqueue(
        self, text: str, scope: str, task_id=None, *, title="Conversazione con Jarvis"
    ):
        if self.config.settings.memory_capture == "off":
            raise PermissionError("La memoria è disattivata.")
        if not self.config.settings.second_brain_url:
            raise ValueError("Collega il Second Brain prima di salvare memorie.")
        if scope not in {"personal", "work", "test-mcp"}:
            raise ValueError("Ambito memoria non valido.")
        key = uid()
        payload = {
            "text": text,
            "title": title,
            "scope": scope,
            "observed_at": now(),
            "request_id": key,
            "background": True,
        }
        await self.db.execute(
            "INSERT INTO memory_outbox(id,task_id,payload,state,next_attempt,created_at) VALUES(?,?,?,?,?,?)",
            (key, task_id, json.dumps(payload, ensure_ascii=False), "pending", now(), now()),
        )
        await self.db.emit("memory.status", {"id": key, "state": "pending"}, task_id)
        return {
            "outbox_id": key,
            "state": "pending",
            "message": "Richiesta di salvataggio nella coda locale; il Second Brain non l'ha ancora confermata.",
        }

    async def recall(self, query: str, scope: str, profile: str):
        if not query.strip() or len(query) > 2000:
            raise ValueError("La ricerca nei ricordi richiede da 1 a 2000 caratteri.")
        return await self.mcp.call(
            "second_brain",
            "recall",
            {
                "query": query,
                "scope": scope,
                "limit": 5,
                "token_budget": self.config.settings.memory_recall_token_budget,
            },
            profile,
        )

    async def tick(self):
        if self.suspended:
            return
        if (
            not self.config.settings.second_brain_url
            or self.config.settings.profile == "local_strict"
        ):
            return
        rows = await self.db.fetchall(
            "SELECT * FROM memory_outbox WHERE state IN ('pending','queued','stored_pending_extraction','stored_with_warnings') AND next_attempt<=? ORDER BY created_at LIMIT 3",
            (now(),),
        )
        for row in rows:
            try:
                if row["source_id"]:
                    result = await self.mcp.call(
                        "second_brain",
                        "source_status",
                        {"source_id": row["source_id"], "revision": row["revision"]},
                        self.config.settings.profile,
                    )
                else:
                    result = await self.mcp.call(
                        "second_brain",
                        "remember",
                        json.loads(row["payload"]),
                        self.config.settings.profile,
                    )
                status = result.get("status", "stored_pending_extraction")
                if status not in {
                    "queued",
                    "indexed",
                    "stored_pending_extraction",
                    "needs_review",
                    "stored_with_warnings",
                    "superseded",
                }:
                    raise ValueError("Stato Second Brain non riconosciuto.")
                next_attempt = (
                    datetime.now(UTC) + timedelta(seconds=min(300, 10 * (row["attempts"] + 1)))
                ).isoformat()
                await self.db.execute(
                    "UPDATE memory_outbox SET state=?,source_id=?,revision=?,attempts=attempts+1,next_attempt=?,detail=? WHERE id=?",
                    (
                        status,
                        result.get("source_id", row["source_id"]),
                        result.get("revision", row["revision"]),
                        next_attempt,
                        json.dumps(result, ensure_ascii=False),
                        row["id"],
                    ),
                )
                await self.db.emit(
                    "memory.status",
                    {
                        "id": row["id"],
                        "state": status,
                        "source_id": result.get("source_id"),
                        "revision": result.get("revision"),
                    },
                    row["task_id"],
                )
            except Exception as error:
                attempts = row["attempts"] + 1
                state = "delivery_error" if attempts >= 6 and not row["source_id"] else row["state"]
                delay = min(1800, 10 * 2 ** min(attempts, 8))
                await self.db.execute(
                    "UPDATE memory_outbox SET state=?,attempts=?,next_attempt=?,detail=? WHERE id=?",
                    (
                        state,
                        attempts,
                        (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(),
                        json.dumps(
                            {
                                "error": type(error).__name__,
                                "message": "Consegna o adozione non confermata; la richiesta originale è conservata.",
                            }
                        ),
                        row["id"],
                    ),
                )

    async def retry(self, key: str):
        row = await self.db.fetchone("SELECT * FROM memory_outbox WHERE id=?", (key,))
        if not row:
            raise ValueError("Fonte in coda non trovata.")
        await self.db.execute(
            "UPDATE memory_outbox SET state=?,attempts=0,next_attempt=? WHERE id=?",
            ("queued" if row["source_id"] else "pending", now(), key),
        )
