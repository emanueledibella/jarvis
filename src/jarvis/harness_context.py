"""Bound the model's working view without rewriting the original evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, ToolMessage

PREVIEW_LIMIT = 700
HISTORY_LIMIT = 12_000
READ_CACHE_TTL = 45
READ_CACHE_SIZE = 24


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def excerpt(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:max(0, limit - 4)].decode("utf-8", errors="ignore").rstrip() + " …"


def recent_history(history: list[dict], limit: int = HISTORY_LIMIT) -> list[dict]:
    """Keep a contiguous suffix of complete turns; the current request is separate."""
    turns: list[list[dict]] = []
    for message in history:
        if message["role"] == "user":
            turns.append([message])
        elif turns:
            turns[-1].append(message)
    selected: list[list[dict]] = []
    remaining = limit
    for turn in reversed(turns):
        weight = sum(size(message["content"]) + 32 for message in turn)
        if weight <= remaining:
            selected.append(turn)
            remaining -= weight
        elif not selected:
            share = max(16, remaining // len(turn) - 32)
            selected.append([
                {**message, "content": excerpt(message["content"], share)} for message in turn
            ])
            break
        else:
            break
    return [message for turn in reversed(selected) for message in turn]


def _content(message) -> str:
    return message.content if isinstance(message.content, str) else json.dumps(
        message.content, ensure_ascii=False, default=str,
    )


def _compact_result(message: ToolMessage, text: str, limit: int) -> ToolMessage:
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    # Keep common evidence coordinates visible even when the text was long.
    keys = ("state", "source_id", "revision", "path", "sha256", "url", "title", "truncated")
    source = {
        key: excerpt(value, 250) if isinstance(value, str) else value
        for key in keys
        if isinstance(data, dict) and isinstance(value := data.get(key), (str, int, bool))
    }
    compact = {
        **source, "evidence_ref": message.tool_call_id,
        "excerpt": excerpt(text, limit),
        "note": "Tool output excerpt. Use read_evidence with evidence_ref for the original.",
    }
    return message.model_copy(update={"content": json.dumps(compact, ensure_ascii=False)})


def project_evidence(messages: list, budget: int, *, emergency=False) -> tuple[list, int]:
    """Compress older complete tool batches first; never cut the user's input."""
    rendered = [_content(message) for message in messages]
    total = sum(size(text) + 32 for text in rendered)
    total += sum(
        size(json.dumps(message.tool_calls, ensure_ascii=False, default=str))
        for message in messages if isinstance(message, AIMessage) and message.tool_calls
    )
    if total <= budget:
        return messages, 0
    recent_calls = [
        index for index, message in enumerate(messages)
        if isinstance(message, AIMessage) and message.tool_calls
    ]
    latest = recent_calls[-1] if recent_calls else len(messages)
    if latest == len(messages):
        return messages, 0
    projection = list(messages)
    removed = 0
    for index, (message, text) in enumerate(zip(messages, rendered, strict=True)):
        if total - removed <= budget:
            break
        # Keep the latest batch verbatim unless it alone keeps the request too
        # large, and then give it a larger excerpt than earlier evidence.
        limit = PREVIEW_LIMIT if index < latest or emergency else PREVIEW_LIMIT * 4
        if isinstance(message, ToolMessage) and size(text) > limit * 2:
            compact = _compact_result(message, text, limit)
            saved = size(text) - size(compact.content)
            if saved > 0:
                projection[index] = compact
                removed += saved
    return projection, removed


def _result_signature(message: ToolMessage):
    text = _content(message)
    try:
        value = json.loads(text)
    except ValueError:
        return text
    if isinstance(value, dict):
        # These transport markers can change even when the lookup learned nothing.
        return {k: v for k, v in value.items() if k not in {"retrieved_at", "cached"}}
    return value


def tool_rounds(messages: list) -> list[str]:
    """Fingerprint finished call/result pairs in this turn, not only their names."""
    rounds: list[str] = []
    pending = {}
    results = {}
    for message in messages:
        if message.type == "human":
            rounds.clear()
            pending, results = {}, {}
        elif isinstance(message, AIMessage):
            pending = {
                call["id"]: (call["name"], call["args"]) for call in message.tool_calls
                if call["id"] and not call["id"].startswith(("attachment-", "memory-"))
            }
            results = {}
        elif isinstance(message, ToolMessage) and message.tool_call_id in pending:
            results[message.tool_call_id] = _result_signature(message)
            if results.keys() == pending.keys():
                paired = sorted(
                    json.dumps([name, args, results[key]], sort_keys=True, ensure_ascii=False, default=str)
                    for key, (name, args) in pending.items()
                )
                rounds.append(hashlib.sha256("\n".join(paired).encode()).hexdigest())
                pending, results = {}, {}
    return rounds


def stopping_reason(rounds: list[str], limit: int) -> str | None:
    for period in (1, 2):
        length = 3 * period
        if len(rounds) >= length and rounds[-length:] == rounds[-period:] * 3:
            return "repeated_tool_results"
    return "tool_round_limit" if len(rounds) >= limit else None


@dataclass
class HarnessRun:
    """Per-attempt state; no private results, queries or cache keys are persisted here."""

    read_cache: OrderedDict = field(default_factory=OrderedDict)
    read_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    reused_reads: int = 0
    initial_tool_count: int | None = None
    peak_tool_count: int = 0
    compacted_bytes: int = 0
    specialist_calls: int = 0
    delegated_tasks: int = 0
    stopped: str | None = None

    def invalidate_reads(self):
        self.read_cache.clear()

    async def read(self, key, function, guard):
        # A single lock protects the bounded index, never the network. Reuse an
        # in-flight identical read without serializing independent lookups.
        async with self.read_lock:
            entry = self.read_cache.get(key)
            if entry and (not entry[1].done() or entry[0] > time.monotonic()):
                work = entry[1]
                reused = True
                self.read_cache.move_to_end(key)
            else:
                reused = False
                self.read_cache.pop(key, None)
                if len(self.read_cache) >= READ_CACHE_SIZE:
                    old = next((k for k, (_, future) in self.read_cache.items() if future.done()), None)
                    if old is not None:
                        self.read_cache.pop(old)
                work = None
                if len(self.read_cache) < READ_CACHE_SIZE:
                    work = asyncio.get_running_loop().create_future()
                    self.read_cache[key] = (float("inf"), work)
        if reused:
            result = await asyncio.shield(work)
            guard()
            if _cacheable(result):
                self.reused_reads += 1
            return result
        if work is None:
            return await function()
        # Cancellation of the caller that owns the read stops the actual I/O.
        try:
            result = await function()
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                work.cancel()
            else:
                work.set_exception(error)
                work.exception()  # Also consume it when no duplicate waiter exists.
            if (entry := self.read_cache.get(key)) and entry[1] is work:
                self.read_cache.pop(key, None)
            raise
        work.set_result(result)
        if (entry := self.read_cache.get(key)) and entry[1] is work:
            if _cacheable(result):
                self.read_cache[key] = (time.monotonic() + READ_CACHE_TTL, work)
            else:
                self.read_cache.pop(key, None)
        return result


def _cacheable(result) -> bool:
    text = result.get("text") if isinstance(result, dict) else None
    return isinstance(result, dict) and result.get("state") not in ("failed", "unavailable", "rejected") and (
        bool(result.get("results")) or (isinstance(text, str) and bool(text.strip()))
    )
