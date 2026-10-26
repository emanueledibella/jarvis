"""Authenticated Twilio audio uses the desktop Live voice without a second TTS voice."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import re
import time
import uuid

import numpy as np
from openai import AsyncOpenAI

from .db import now, uid
from .live_voice import excerpt
from .phone_prompts import phone_language, phone_message
from .telephony import decode_mulaw
from .voice_style import voice_api_key, voice_instructions, voice_reference

PHONE_PROMPT = """You are Jarvis, the owner's personal voice assistant, on an authenticated phone call.
Use the same vocal identity and conversational style as the desktop assistant.
The application has already checked the PIN. Never ask for, repeat, or infer it.
Open with the supplied greeting, then listen. Before the caller's first substantive request,
keep the configured fallback language even when the call reason is written in another language.
Let the caller finish. Stop speaking when interrupted and do not fill pauses with backchannels.
For a simple request, reply directly and briefly without a stock preamble.
Delegate requests requiring facts, reasoning, memory, time, weather, calendar, web, files,
commands, lights, or other actions by generating <|SpawnThinking|>.
Never invent tool results or claim an action succeeded before the backend confirms it.
Only the application can authorize effects. A spoken yes never authorizes a proposal.
When the application supplies a phone approval readback, read its tool and all parameters
verbatim before the instructions to press one or two. Never omit, summarize, or modify them.
Only the application can process those keypad digits. Do not infer approval from speech.
For ordinary verified results, explain them in the caller's language.
"""


def readback_text(value: str) -> str:
    return "".join(re.findall(r"\w", value.casefold())).replace("_", "")


class PhoneLive:
    def __init__(self, telephony, websocket, row, stream_sid, conversation_id, scope):
        self.telephony, self.runtime = telephony, telephony.runtime
        self.websocket, self.row, self.stream_sid = websocket, row, stream_sid
        self.conversation_id, self.scope = conversation_id, scope
        self.settings = self.runtime.config.settings
        self.profile = self.settings.profile
        self.private = self.runtime.voice_session["private"]
        self.privacy_revision = self.runtime.voice_session["revision"]
        self.stop, self.closed, self.started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.carrier_open = True
        self.write_lock = asyncio.Lock()
        self.fragments: list[dict] = []
        self.processed: set[str] = set()
        self.last_offset = -1
        self.pending = None
        self.output_ms = 0.0
        self.last_speech = 0.0
        self.voiced_frames = 0
        self.jobs: set[asyncio.Task] = set()
        self.job_error = None
        self.final_seconds = None

    def validate(self):
        current = self.runtime.config.settings
        if (
            self.runtime.gateway.blocked
            or not current.telephony_enabled
            or current.profile == "local_strict"
            or current.profile != self.profile
            or not self.row["auth_verified"]
            or current.desktop_voice_provider != "openai_live"
            or self.runtime.voice_session["revision"] != self.privacy_revision
            or self.row["id"] not in self.telephony.active
        ):
            raise PermissionError("The phone voice session is no longer authorized.")

    async def send(self, event):
        if self.carrier_open:
            async with self.write_lock:
                await self.websocket.send_json({"streamSid": self.stream_sid, **event})

    def launch(self, awaitable):
        task = asyncio.create_task(awaitable)
        self.jobs.add(task)

        def finished(done):
            self.jobs.discard(done)
            if not done.cancelled() and done.exception():
                self.job_error = done.exception()
                self.stop.set()

        task.add_done_callback(finished)

    async def commentary(self, connection, text, delegation_id=None):
        await connection.session.commentary.append(
            delegation_id=delegation_id, content=excerpt(text)
        )

    async def wait_task(self, connection, task, delegation_id=None):
        while not self.stop.is_set():
            self.validate()
            row = await self.runtime.db.fetchone(
                "SELECT state,result,error FROM tasks WHERE id=?", (task["id"],)
            )
            if row["state"] == "succeeded":
                result = self.runtime.tasks.private_tasks.get(task["id"], {}).get(
                    "result", row["result"]
                )
                await self.commentary(connection, result, delegation_id)
                return
            if row["state"] == "waiting_user":
                proposals = await self.runtime.db.fetchall(
                    "SELECT * FROM approvals WHERE task_id=? AND state='pending' AND expires_at>?",
                    (task["id"], now()),
                )
                if len(proposals) != 1:
                    await self.commentary(
                        connection, phone_message(self.settings, "dashboard"), delegation_id
                    )
                    return
                proposal = proposals[0]
                brief = json.dumps(json.loads(proposal["arguments"]), ensure_ascii=False)
                text = phone_message(
                    self.settings, "approval", tool=proposal["tool"], arguments=brief
                )
                # Do not truncate an approval into a different proposal. An exact,
                # bounded readback must be transcribed AND acknowledged as played.
                if len(text.encode()) > 1000:
                    await self.commentary(
                        connection, phone_message(self.settings, "long_proposal"), delegation_id
                    )
                    return
                self.pending = {
                    "id": proposal["id"],
                    "task_id": task["id"],
                    "expires_at": proposal["expires_at"],
                    "expected": readback_text(proposal["tool"] + brief),
                    "transcript": "",
                    "audio_end": None,
                    "mark": None,
                    "heard": False,
                }
                await connection.session.instructions.append(
                    delegation_id=delegation_id,
                    content="Read this exact approval in full, without changing its tool or parameters: "
                    + text,
                )
                return
            if row["state"] in {"failed", "cancelled", "paused"}:
                await self.commentary(
                    connection, phone_message(self.settings, "failed"), delegation_id
                )
                return
            await asyncio.sleep(0.2)

    async def delegate(self, connection, event):
        if self.pending:
            await self.commentary(connection, phone_message(self.settings, "pending"))
            return
        offset = event["offset_ms"]
        if not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise ValueError("Invalid phone delegation offset.")
        selected = [
            item
            for item in self.fragments
            if item["end_ms"] > self.last_offset and item["start_ms"] <= offset
        ]
        text = "".join(item["delta"] for item in selected).strip()
        if not text:
            await self.commentary(
                connection,
                "The request was not transcribed. Ask the caller to repeat it in their language.",
                event["delegation"]["id"],
            )
            return
        self.last_offset = max(item["end_ms"] for item in selected)
        if text.casefold().strip(" .!?") in {
            "riaggancia",
            "chiudi la chiamata",
            "arrivederci",
            "hang up",
            "end the call",
            "goodbye",
        }:
            self.stop.set()
            return
        task = await self.runtime.tasks.create(
            text[:20000],
            request_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL, f"jarvis-phone:{self.row['id']}:{event['delegation']['id']}"
                )
            ),
            conversation_id=self.conversation_id,
            profile=self.profile,
            scope=self.scope,
            private=self.private,
            channel="phone",
        )
        self.conversation_id = task["conversation_id"]
        await self.wait_task(connection, task, event["delegation"]["id"])

    async def mark_readback(self):
        proposal = self.pending
        if (
            proposal
            and proposal["audio_end"] is not None
            and not proposal["mark"]
            and self.output_ms >= proposal["audio_end"]
        ):
            proposal["mark"] = "approval-" + uid()
            await self.send({"event": "mark", "mark": {"name": proposal["mark"]}})

    async def receive_provider(self, connection):
        async for raw in connection:
            event = raw.model_dump() if hasattr(raw, "model_dump") else raw
            kind = event["type"]
            if kind == "session.closed":
                self.final_seconds = float(event["usage"]["seconds"])
                self.closed.set()
                self.stop.set()
                return
            if self.stop.is_set():
                continue  # Keep draining to collect final usage without playing more audio.
            self.validate()
            if kind == "session.started":
                self.started.set()
                greeting = phone_message(self.settings, "verified")
                if self.row["detail"]:
                    greeting += " " + phone_message(
                        self.settings, "reason", reason=self.row["detail"][:400]
                    )
                await self.commentary(connection, greeting)
            elif kind == "session.output_audio.delta":
                data = base64.b64decode(event["delta"], validate=True)
                if not data or len(data) > 128000:
                    raise ValueError("Invalid phone output audio.")
                self.output_ms += len(data) / 8
                pcm = decode_mulaw(data)
                if np.max(np.abs(pcm.astype(np.int32))) > 550:
                    self.last_speech = time.monotonic()
                await self.send({"event": "media", "media": {"payload": event["delta"]}})
                await self.mark_readback()
            elif kind == "session.input_transcript.delta":
                self.fragments.append({key: event[key] for key in ("delta", "start_ms", "end_ms")})
                if sum(len(item["delta"]) for item in self.fragments) > 50000:
                    raise ValueError("Phone conversation exceeds the transcript limit.")
            elif kind == "session.output_transcript.delta" and self.pending:
                self.pending["transcript"] = (self.pending["transcript"] + event["delta"])[-5000:]
                if self.pending["expected"] in readback_text(self.pending["transcript"]):
                    self.pending["audio_end"] = float(event["end_ms"]) + 200
                    await self.mark_readback()
            elif kind == "session.delegation.created" and event["delegation"]["target"] == "client":
                delegation_id = event["delegation"]["id"]
                if delegation_id not in self.processed:
                    self.processed.add(delegation_id)
                    self.launch(self.delegate(connection, event))
            elif kind == "error":
                raise ValueError("OpenAI rejected a phone voice command.")
        if not self.closed.is_set():
            raise ConnectionError("Phone voice closed without final usage.")

    async def receive_phone(self, connection, events):
        await asyncio.wait_for(self.started.wait(), 10)
        async for raw in events:
            self.validate()
            if len(raw) > 100000:
                raise ValueError("Phone frame exceeds the size limit.")
            event = json.loads(raw)
            kind = event.get("event")
            if kind == "start":
                raise PermissionError("Media session has already started.")
            if kind == "media":
                payload = event["media"]["payload"]
                data = base64.b64decode(payload, validate=True)
                if not data or len(data) > 8000:
                    raise ValueError("Invalid phone input audio.")
                pcm = decode_mulaw(data)
                level = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
                self.voiced_frames = self.voiced_frames + 1 if level > 550 else 0
                if self.voiced_frames == 3 and time.monotonic() - self.last_speech < 1:
                    if self.pending and not self.pending["heard"]:
                        self.pending.update(transcript="", audio_end=None, mark=None)
                    await self.send({"event": "clear"})
                await connection.session.input_audio.append(audio=payload)
            elif kind == "mark" and self.pending:
                if (
                    self.pending["mark"]
                    and event.get("mark", {}).get("name") == self.pending["mark"]
                ):
                    self.pending["heard"] = True
            elif kind == "dtmf" and self.pending:
                digit = event.get("dtmf", {}).get("digit")
                if digit not in {"1", "2"}:
                    continue
                if digit == "1" and not self.pending["heard"]:
                    await self.commentary(connection, phone_message(self.settings, "not_read"))
                    continue
                proposal, self.pending = self.pending, None
                await self.send({"event": "clear"})
                try:
                    task_id = await self.runtime.gateway.decide(proposal["id"], digit == "1")
                    await self.runtime.tasks.resume(task_id)
                    self.launch(self.wait_task(connection, {"id": task_id}))
                except ValueError:
                    await self.commentary(connection, phone_message(self.settings, "expired"))
            elif kind == "stop":
                break
        self.carrier_open = False
        self.stop.set()

    async def run(self, events, *, client_factory=None):
        self.validate()
        reservation, rate = uid(), self.settings.desktop_voice_rate_usd_per_minute
        await self.runtime.budget.reserve_voice(
            reservation, self.settings.phone_max_call_seconds + 15, rate
        )
        jobs = []
        try:
            async with (client_factory or AsyncOpenAI)(
                api_key=voice_api_key(self.settings),
                base_url="https://api.openai.com/v1",
                organization="",
                project="",
                max_retries=0,
                timeout=20,
            ) as client:
                async with client.live.connect(max_retries=0) as connection:

                    async def watch():
                        while not self.stop.is_set():
                            self.validate()
                            await asyncio.sleep(0.25)

                    try:
                        await connection.session.start(
                            session={
                                "model": self.settings.desktop_voice_model,
                                "store": False,
                                "instructions": PHONE_PROMPT + voice_instructions(self.settings),
                                "input": [
                                    {
                                        "type": "message",
                                        "role": "developer",
                                        "content": [
                                            {
                                                "type": "input_text",
                                                "text": "Greet the caller immediately in "
                                                + phone_language(self.settings)
                                                + ", using the application's verified greeting. Then pause and listen.",
                                            }
                                        ],
                                    }
                                ],
                                "audio": {
                                    "format": {"type": "audio/pcmu", "rate": 8000},
                                    "output": {
                                        "voice": voice_reference(self.settings.desktop_voice_name)
                                    },
                                },
                                "delegation": {"type": "client"},
                            }
                        )
                        reader = asyncio.create_task(self.receive_provider(connection))
                        jobs = [
                            reader,
                            asyncio.create_task(self.receive_phone(connection, events)),
                            asyncio.create_task(watch()),
                            asyncio.create_task(self.stop.wait()),
                        ]
                        done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            if not task.cancelled() and task.exception():
                                raise task.exception()
                        if self.job_error is not None:
                            raise self.job_error
                    finally:
                        self.stop.set()
                        if jobs and not jobs[0].done():
                            with contextlib.suppress(Exception):
                                await connection.session.close()
                                await asyncio.wait_for(self.closed.wait(), 5)
        finally:
            self.stop.set()
            cleanup = [*jobs, *self.jobs]
            for task in cleanup:
                task.cancel()
            await asyncio.gather(*cleanup, return_exceptions=True)
            await self.runtime.budget.finish_voice(reservation, self.final_seconds, rate)
