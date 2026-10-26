"""Bounded, short-lived RAM handoffs between interrupted voice connections."""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass, field

from .db import uid


@dataclass
class VoiceContext:
    boundary: tuple
    stop: asyncio.Event
    history: list[dict] = field(default_factory=list)
    conversation_id: str | None = None
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    expiry: asyncio.TimerHandle | None = None

    def append(self, role: str, text: str):
        if not text:
            return
        kind = "input_text" if role == "user" else "output_text"
        if self.history and self.history[-1]["role"] == role:
            part = self.history[-1]["content"][0]
            part["text"] = (part["text"] + text).encode()[-2000:].decode(errors="ignore")
        else:
            self.history.append({
                "role": role, "status": "completed",
                "content": [{"type": kind, "text": text.encode()[-2000:].decode(errors="ignore")}],
            })
        self.history = self.history[-12:]
        while len(self.history) > 1 and sum(len(item["content"][0]["text"].encode()) for item in self.history) > 6000:
            self.history.pop(0)


class VoiceContextStore:
    def __init__(self, ttl: float = 120):
        self.ttl = ttl
        self.entries: dict[str, VoiceContext] = {}
        self.deadlines: dict[str, float] = {}

    @staticmethod
    def boundary(metadata) -> tuple:
        return (metadata.profile, metadata.scope, metadata.private, metadata.privacy_revision)

    def discard(self, key: str):
        context = self.entries.pop(key, None)
        self.deadlines.pop(key, None)
        if context and context.expiry:
            context.expiry.cancel()

    def clear(self):
        for key in list(self.entries):
            self.discard(key)

    def resume(self, key: str, metadata) -> VoiceContext:
        context = self.entries.get(key)
        if not context or self.deadlines.get(key, float("inf")) <= time.monotonic():
            self.discard(key)
            raise ValueError("Voice context expired. Start a new conversation.")
        if context.boundary != self.boundary(metadata):
            raise PermissionError("Voice context cannot cross a profile or privacy boundary.")
        self.discard(key)  # Handoff handles are single-use.
        context.stop.set()
        return context

    def create(self, metadata, stop: asyncio.Event, previous: VoiceContext | None = None):
        # Two active connections plus two recently closed conversations at most.
        if len(self.entries) >= 4:
            for key, item in list(self.entries.items()):
                if item.closed.is_set():
                    self.discard(key)
                    break
            else:
                raise ValueError("Too many active voice contexts.")
        context = VoiceContext(
            self.boundary(metadata), stop,
            history=copy.deepcopy(previous.history) if previous else [],
            conversation_id=previous.conversation_id if previous else metadata.conversation_id,
        )
        if previous and context.history and context.history[-1]["role"] == "assistant":
            context.history[-1]["status"] = "incomplete"
        key = uid()
        self.entries[key] = context
        return key, context

    def close(self, key: str, context: VoiceContext):
        context.closed.set()
        if self.entries.get(key) is context:
            self.deadlines[key] = time.monotonic() + self.ttl
            context.expiry = asyncio.get_running_loop().call_later(self.ttl, self.discard, key)
