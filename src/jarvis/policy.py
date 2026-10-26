from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from langgraph.types import interrupt

from .db import Database, now, uid
from .memory_retrieval import is_second_brain_read


@dataclass
class TaskContext:
    id: str
    prompt: str
    profile: str
    scope: str
    private: bool = False
    external_authorized: bool = False
    schedule_id: str | None = None
    private_results: dict = field(default_factory=dict)
    memory_blocked: bool = False
    sensitive_context: bool = False
    untrusted_context: bool = False
    routine_context_only: bool = False
    memory_recalls: dict = field(default_factory=dict)

    def __post_init__(self):
        self.sensitive_context = self.sensitive_context or self.private
        self.memory_blocked = self.memory_blocked or bool(
            re.search(
                r"\b(non\s+(?:lo\s+)?(?:ricordare|memorizzare|salvare)|do\s+not\s+remember|don't\s+remember)\b",
                self.prompt,
                re.IGNORECASE,
            )
        )

    def mark_untrusted(self, *, routine: bool = False):
        # Prior conversation and bounded weather data still protect private
        # exports and critical actions, but do not revoke a scoped light grant.
        self.routine_context_only = routine and (
            not self.untrusted_context or self.routine_context_only
        )
        self.untrusted_context = True


active_task: ContextVar[TaskContext] = ContextVar("jarvis_active_task")


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


class Gateway:
    def __init__(self, db: Database):
        self.db = db
        self.private_approvals: dict[str, dict] = {}
        self.blocked = False
        self.approval_locks = {}

    async def approval(self, ctx: TaskContext, tool: str, arguments: dict) -> bool:
        key = digest([ctx.id, tool, arguments])
        async with self.approval_locks.setdefault(key, asyncio.Lock()):
            return await self._approval(ctx, tool, arguments)

    async def _approval(self, ctx: TaskContext, tool: str, arguments: dict) -> bool:
        argument_hash = digest(arguments)
        row = await self.db.fetchone(
            "SELECT * FROM approvals WHERE task_id=? AND tool=? AND arguments_hash=? ORDER BY created_at DESC LIMIT 1",
            (ctx.id, tool, argument_hash),
        )
        current = now()
        if row and row["state"] in {"approved", "rejected"} and row["expires_at"] > current:
            return row["state"] == "approved"
        if not row or row["expires_at"] <= current:
            row = {
                "id": uid(),
                "task_id": ctx.id,
                "tool": tool,
                "arguments": json.dumps({} if ctx.private else arguments, ensure_ascii=False),
                "arguments_hash": argument_hash,
                "state": "pending",
                "created_at": current,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            }
            await self.db.execute(
                "INSERT INTO approvals(id,task_id,tool,arguments,arguments_hash,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                tuple(
                    row[key]
                    for key in [
                        "id",
                        "task_id",
                        "tool",
                        "arguments",
                        "arguments_hash",
                        "state",
                        "created_at",
                        "expires_at",
                    ]
                ),
            )
            if ctx.private:
                self.private_approvals[row["id"]] = arguments
            await self.db.emit(
                "approval.requested",
                {
                    "id": row["id"],
                    "tool": tool,
                    "arguments": arguments,
                    "expires_at": row["expires_at"],
                },
                ctx.id,
                private=ctx.private,
            )
        # The decision is authoritative in our DB and bound to the hash. A bare resume
        # payload is never itself permission to execute a changed operation.
        interrupt({"approval_id": row["id"], "tool": tool})
        row = await self.db.fetchone("SELECT * FROM approvals WHERE id=?", (row["id"],))
        return bool(row and row["state"] == "approved" and row["expires_at"] > now())

    async def invoke(self, name: str, arguments: dict, risk: str, function):
        if self.blocked:
            raise PermissionError(
                "Emergency stop is active. Re-enable the service from the dashboard."
            )
        ctx = active_task.get()
        if risk == "lighting_direct" and name != "light_set":
            raise PermissionError("A direct lighting grant cannot authorize another tool.")
        if name in {"memory_remember", "memory_change"} and (ctx.private or ctx.memory_blocked):
            raise PermissionError("This session does not allow memory writes.")
        was_sensitive = ctx.sensitive_context
        was_untrusted = ctx.untrusted_context
        was_routine = ctx.routine_context_only
        memory_read = risk == "network_read" and is_second_brain_read(name)
        # Dedicated memory writes keep their source/privacy/connection checks and
        # effect ledger, but the owner does not need to approve each operation.
        memory_write = (name, risk) in {
            ("memory_remember", "memory"),
            ("memory_change", "external"),
        }
        if memory_read or memory_write or name.startswith("workspace_") or name in {
            "calendar_events",
            "memory_recall",
            "tasks_list",
            "schedules_list",
            "weather",
            "list_mcp_tools",
            "lights_list",
            "light_state",
            "light_set",
        }:
            ctx.sensitive_context = True
        if memory_read or memory_write or name in {
            "workspace_read",
            "workspace_list",
            "workspace_search",
            "calendar_events",
            "memory_recall",
            "web_search",
            "read_web_page",
            "call_mcp_tool",
            "list_mcp_tools",
            "tasks_list",
            "schedules_list",
            "workspace_command",
        }:
            ctx.mark_untrusted()
        if name == "weather":
            ctx.mark_untrusted(routine=True)
        needs_approval = (
            risk in {"external", "command", "workspace", "schedule", "task", "memory"}
            or (risk == "lighting" and was_untrusted and not was_routine)
            or (
                risk == "network_read"
                and was_sensitive
                and not memory_read
                and not (
                    name == "weather"
                    and (not arguments.get("location") or not was_untrusted or was_routine)
                )
            )
            or (ctx.untrusted_context and risk in {"workspace", "schedule", "task", "memory"})
        )
        # lighting_direct is supplied only after matching the complete current
        # owner request to this registered light and its exact normalized change.
        # Conversation history cannot revoke that narrow, already configured grant.
        # A broad owner grant cannot let later tool/page content authorize its
        # own effects, or authorize private data export through a new query.
        preauthorized = (
            ctx.external_authorized
            and not was_untrusted
            and not (risk == "network_read" and was_sensitive)
        )
        if needs_approval and not (preauthorized or memory_write):
            if not await self.approval(ctx, name, arguments):
                return {
                    "state": "rejected",
                    "message": "The owner did not authorize this operation.",
                }
        if self.blocked:
            raise PermissionError("Emergency stop is active.")
        argument_hash = digest(arguments)
        operation_key = digest([ctx.id, name, argument_hash])
        mutating = risk not in {"read", "network_read"}
        if mutating:
            if operation_key in ctx.private_results:
                return ctx.private_results[operation_key]
            claimed = await self.db.execute(
                "INSERT OR IGNORE INTO effects(operation_key,task_id,tool,arguments_hash,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (operation_key, ctx.id, name, argument_hash, "running", now(), now()),
            )
            if not claimed:
                previous = await self.db.fetchone(
                    "SELECT * FROM effects WHERE operation_key=?", (operation_key,)
                )
                if previous["state"] == "succeeded" and previous["result"]:
                    return json.loads(previous["result"])
                retry = 0
                if previous["state"] == "retry_allowed":
                    retry = await self.db.execute(
                        "UPDATE effects SET state='running',updated_at=? WHERE operation_key=? AND state='retry_allowed'",
                        (now(), operation_key),
                    )
                if not retry:
                    raise ValueError(
                        "The operation outcome is uncertain: reconcile it before retrying."
                    )
        await self.db.emit("tool.started", {"tool": name}, ctx.id, private=ctx.private)
        started = False
        try:
            if self.blocked:
                raise PermissionError("Emergency stop is active.")
            started = True
            result = await function()
        except BaseException:
            if mutating:
                # A failed/aborted network mutation may have committed remotely. The
                # reconciliation action is explicit; failed effects are not silently replayed.
                await self.db.execute(
                    "UPDATE effects SET state=?,updated_at=? WHERE operation_key=?",
                    ("unknown" if started else "retry_allowed", now(), operation_key),
                )
            raise
        if mutating:
            ctx.private_results[operation_key] = result
            await self.db.execute(
                "UPDATE effects SET state='succeeded',result=?,updated_at=? WHERE operation_key=?",
                (
                    None if ctx.private else json.dumps(result, ensure_ascii=False, default=str),
                    now(),
                    operation_key,
                ),
            )
        await self.db.emit(
            "tool.completed", {"tool": name, "state": "succeeded"}, ctx.id, private=ctx.private
        )
        return result

    async def decide(self, approval_id: str, approved: bool) -> str:
        row = await self.db.fetchone("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row or row["state"] != "pending" or row["expires_at"] < now():
            raise ValueError("The proposal has expired or has already been decided.")
        task = await self.db.fetchone("SELECT state FROM tasks WHERE id=?", (row["task_id"],))
        if not task or task["state"] != "waiting_user":
            raise ValueError("The task is no longer waiting for this decision.")
        changed = await self.db.execute(
            "UPDATE approvals SET state=?,decided_at=? WHERE id=? AND state='pending'",
            ("approved" if approved else "rejected", now(), approval_id),
        )
        if not changed:
            raise ValueError("The proposal has already been decided.")
        return row["task_id"]

    async def reconcile(self, operation_key: str, outcome: str, result: dict):
        if outcome not in {"succeeded", "not_executed"}:
            raise ValueError("Specify a verified outcome: succeeded or not_executed.")
        changed = await self.db.execute(
            "UPDATE effects SET state=?,result=?,updated_at=? WHERE operation_key=? AND state='unknown'",
            (
                "succeeded" if outcome == "succeeded" else "retry_allowed",
                json.dumps(result),
                now(),
                operation_key,
            ),
        )
        if not changed:
            raise ValueError("The operation does not require reconciliation.")
