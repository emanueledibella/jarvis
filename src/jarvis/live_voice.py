from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import time
import uuid
from contextlib import suppress
from typing import Literal

from fastapi import WebSocket
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError
from starlette.websockets import WebSocketDisconnect

from .config import Profile
from .db import uid
from .language import language_instructions
from .speech import speech_text

LIVE_PROMPT = """You are Jarvis, the Mac owner's AI voice assistant.
Speak naturally, calmly, and directly. Use one or two sentences for simple questions.
Backchannel policy: Briefly acknowledge that you are listening without talking over the user.
Interruption policy: Let the user speak when they interrupt. Do not mistake your own voice for a new request.
Delegation policy:
Backend tools: actual time and dates, personal Second Brain memory, calendar, weather, web search,
coding, files, commands, routines, and actions with permission checks.
Generate <|SpawnThinking|> when a request needs information, reasoning, or a backend tool.
Generate <|SpawnThinking|> before giving the time, a personal fact, or confirming an action.
Do not invent results while waiting. Report only verified outcomes received from the backend.
Do not generate <|SpawnThinking|> for greetings, clarification, or repeating a just-verified result.
Actions require dashboard approval: a spoken yes does not grant permission.
If you hear only 'Jarvis', briefly invite the user to continue in the conversation language and wait.
"""


class LiveStart(BaseModel):
    type: Literal["start"] = "start"
    profile: Profile
    scope: Literal["personal", "work"] = "personal"
    private: bool = False
    privacy_revision: int = Field(ge=0)
    conversation_id: str | None = None


def excerpt(text: str) -> str:
    return speech_text(text).encode()[:1000].decode(errors="ignore")


class LiveVoice:
    def __init__(self, runtime):
        self.runtime = runtime
        self.sessions: set[asyncio.Event] = set()

    def stop_all(self):
        for stop in list(self.sessions):
            stop.set()

    def key(self):
        settings = self.runtime.config.settings
        key = settings.secret("desktop_voice_api_key")
        if (
            not key
            and settings.cloud_provider == "openai"
            and settings.cloud_base_url.rstrip("/") in {"", "https://api.openai.com/v1"}
        ):
            key = settings.secret("cloud_api_key")
        if not key:
            raise ValueError("Configure an OpenAI voice API key in Settings.")
        return key

    def validate(self, metadata: LiveStart):
        settings = self.runtime.config.settings
        preference = self.runtime.voice_session
        if self.runtime.gateway.blocked or not settings.voice_enabled:
            raise PermissionError("Voice is suspended.")
        if settings.profile == "local_strict" or metadata.profile == "local_strict":
            raise PermissionError("The strict offline profile does not send audio to OpenAI.")
        if metadata.profile != settings.profile:
            raise PermissionError("The profile changed: reopen the voice conversation.")
        if settings.desktop_voice_provider != "openai_live":
            raise PermissionError("OpenAI voice is not selected.")
        if (
            metadata.privacy_revision != preference["revision"]
            or metadata.scope != preference["scope"]
        ):
            raise PermissionError("Privacy or scope changed: reopen the voice conversation.")
        if preference["private"] and not metadata.private:
            raise PermissionError("This connection cannot disable the private session.")

    async def endpoint(self, websocket: WebSocket):
        token = websocket.headers.get("authorization", "").removeprefix("Bearer ")
        host = websocket.headers.get("host", "").split(":")[0]
        origin = websocket.headers.get("origin")
        allowed_origins = {
            f"http://127.0.0.1:{self.runtime.config.settings.api_port}",
            f"http://localhost:{self.runtime.config.settings.api_port}",
        }
        if (
            host not in {"127.0.0.1", "localhost"}
            or (origin and origin not in allowed_origins)
            or not hmac.compare_digest(token, self.runtime.config.token)
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            metadata = LiveStart.model_validate(
                await asyncio.wait_for(websocket.receive_json(), 10)
            )
            self.validate(metadata)
            await self.serve(websocket, metadata)
        except ValidationError:
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json(
                    {"type": "error", "message": "Invalid voice session metadata."}
                )
        except (ValueError, PermissionError) as error:
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json({"type": "error", "message": str(error)[:500]})
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as error:
            # Provider errors can include request details. Never forward full payloads,
            # transcripts, headers, credentials, or raw exceptions to native clients.
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "OpenAI voice connection interrupted.",
                        "code": type(error).__name__,
                    }
                )
        finally:
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()

    async def serve(self, websocket, metadata: LiveStart, *, client_factory=AsyncOpenAI):
        self.validate(metadata)
        key = self.key()
        if len(self.sessions) >= 2:
            raise ValueError("A voice conversation is already open. Close it before trying again.")
        settings = self.runtime.config.settings
        maximum = settings.desktop_voice_max_session_seconds
        rate = settings.desktop_voice_rate_usd_per_minute
        reservation = uid()
        stop, closed = asyncio.Event(), asyncio.Event()
        self.sessions.add(stop)
        write_lock = asyncio.Lock()
        disconnected = False
        final_seconds = None
        started = time.monotonic()
        last_activity = started
        fragments: list[dict] = []
        processed_ids: set[str] = set()
        last_offset = -1
        conversation_id = metadata.conversation_id
        delegations: set[asyncio.Task] = set()
        tasks: list[asyncio.Task] = []
        completed_normally = False
        delegation_error = None

        async def send(data):
            nonlocal disconnected
            if disconnected:
                return
            try:
                async with write_lock:
                    await websocket.send_json(data)
            except (RuntimeError, WebSocketDisconnect, OSError):
                disconnected = True
                stop.set()

        try:
            # Claim the session slot before the first await so concurrent callers
            # cannot all pass the admission limit while the budget query runs.
            await self.runtime.budget.reserve_voice(reservation, maximum + 20, rate)
            self.validate(metadata)
            if stop.is_set():
                raise PermissionError("The voice session was stopped before it started.")
            async with client_factory(
                api_key=key, base_url="https://api.openai.com/v1", max_retries=0, timeout=20
            ) as client:
                async with client.live.connect(max_retries=0) as connection:

                    async def delegate(event):
                        nonlocal conversation_id, last_offset, last_activity
                        delegation_id = event["delegation"]["id"]
                        if delegation_id in processed_ids:
                            return
                        processed_ids.add(delegation_id)
                        self.validate(metadata)
                        offset = event["offset_ms"]
                        selected = [
                            p
                            for p in fragments
                            if p["end_ms"] > last_offset and p["start_ms"] <= offset
                        ]
                        text = "".join(p["delta"] for p in selected).strip()
                        if not text:
                            await connection.session.commentary.append(
                                delegation_id=delegation_id,
                                content="The request was not transcribed: ask the user to repeat it in their language.",
                            )
                            return
                        last_offset = max(p["end_ms"] for p in selected)
                        task = await self.runtime.tasks.create(
                            text[:20000],
                            request_id=str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL, f"jarvis-live:{reservation}:{delegation_id}"
                                )
                            ),
                            conversation_id=conversation_id,
                            profile=metadata.profile,
                            scope=metadata.scope,
                            private=metadata.private,
                            channel="live",
                        )
                        conversation_id = task["conversation_id"]
                        await send({"type": "task", **task})
                        while not stop.is_set():
                            row = await self.runtime.db.fetchone(
                                "SELECT state,result,error FROM tasks WHERE id=?", (task["id"],)
                            )
                            if row and row["state"] in {
                                "succeeded",
                                "failed",
                                "cancelled",
                                "paused",
                                "waiting_user",
                            }:
                                if row["state"] == "succeeded":
                                    result = self.runtime.tasks.private_tasks.get(
                                        task["id"], {}
                                    ).get("result", row["result"])
                                elif row["state"] == "waiting_user":
                                    result = "The action requires a dashboard decision and has not been executed. Ask the user to review the proposal in Jarvis, using their language."
                                else:
                                    result = f"Task state: {row['state']}. Do not claim that the action is complete. {row['error'] or ''}"
                                await connection.session.commentary.append(
                                    delegation_id=delegation_id, content=excerpt(result)
                                )
                                await send({"type": "task", **task, "state": row["state"]})
                                last_activity = time.monotonic()
                                return
                            await asyncio.sleep(0.2)

                    async def receive_provider():
                        nonlocal final_seconds, last_activity
                        async for raw in connection:
                            event = raw.model_dump() if hasattr(raw, "model_dump") else raw
                            kind = event["type"]
                            if kind == "session.started":
                                await send(
                                    {
                                        "type": "ready",
                                        "model": settings.desktop_voice_model,
                                        "voice": settings.desktop_voice_name,
                                    }
                                )
                            elif kind == "session.output_audio.delta":
                                self.validate(metadata)
                                await send({"type": "audio", "audio": event["delta"]})
                            elif kind == "session.input_transcript.delta":
                                last_activity = time.monotonic()
                                if (
                                    sum(len(p["delta"]) for p in fragments) + len(event["delta"])
                                    > 50000
                                ):
                                    raise ValueError(
                                        "Voice conversation is too long; open a new session."
                                    )
                                fragments.append(
                                    {k: event[k] for k in ("delta", "start_ms", "end_ms")}
                                )
                                await send({"type": "input_text", "text": event["delta"]})
                            elif kind == "session.output_transcript.delta":
                                last_activity = time.monotonic()
                                await send({"type": "output_text", "text": event["delta"]})
                            elif (
                                kind == "session.delegation.created"
                                and event["delegation"]["target"] == "client"
                            ):
                                job = asyncio.create_task(delegate(event))
                                delegations.add(job)
                                job.add_done_callback(delegations.discard)

                                def finished(done):
                                    nonlocal delegation_error
                                    if not done.cancelled() and done.exception():
                                        delegation_error = done.exception()
                                        stop.set()

                                job.add_done_callback(finished)
                            elif kind == "session.closed":
                                final_seconds = float(event["usage"]["seconds"])
                                closed.set()
                                stop.set()
                                return
                            elif kind == "error":
                                await send(
                                    {
                                        "type": "error",
                                        "message": "OpenAI rejected a voice session command.",
                                        "code": str(
                                            event.get("error", {}).get("code", "provider_error")
                                        )[:100],
                                    }
                                )
                                stop.set()
                        if not closed.is_set():
                            raise ConnectionError("OpenAI session closed without a final event.")

                    async def receive_native():
                        nonlocal disconnected
                        try:
                            while not stop.is_set():
                                data = await websocket.receive_json()
                                self.validate(metadata)
                                if data.get("type") == "close":
                                    stop.set()
                                    return
                                if data.get("type") == "say" and isinstance(data.get("text"), str):
                                    await connection.session.commentary.append(
                                        delegation_id=None, content=excerpt(data["text"])
                                    )
                                    continue
                                if (
                                    data.get("type") != "audio"
                                    or not isinstance(data.get("audio"), str)
                                    or len(data["audio"]) > 65536
                                ):
                                    raise ValueError("Invalid audio packet.")
                                try:
                                    pcm = base64.b64decode(data["audio"], validate=True)
                                except (binascii.Error, ValueError):
                                    raise ValueError("Invalid PCM audio.") from None
                                if not pcm or len(pcm) % 2:
                                    raise ValueError("PCM must contain complete 16-bit samples.")
                                await connection.session.input_audio.append(audio=data["audio"])
                        except WebSocketDisconnect:
                            disconnected = True
                            stop.set()

                    async def watch():
                        while not stop.is_set():
                            self.validate(metadata)
                            elapsed = time.monotonic() - started
                            if elapsed >= maximum or (
                                not delegations
                                and time.monotonic() - last_activity
                                >= settings.desktop_voice_idle_seconds
                            ):
                                stop.set()
                                return
                            await asyncio.sleep(0.25)

                    await connection.session.start(
                        session={
                            "model": settings.desktop_voice_model,
                            "store": False,
                            "instructions": LIVE_PROMPT
                            + language_instructions(settings.response_language, settings.language)
                            + (
                                "\nWhen using speakers, wait until the user finishes before speaking. Avoid spoken backchannels while they are still making their request."
                                if settings.desktop_voice_duplex == "gated"
                                else ""
                            ),
                            "audio": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "output": {"voice": settings.desktop_voice_name},
                            },
                            "delegation": {"type": "client"},
                        }
                    )
                    reader = asyncio.create_task(receive_provider())
                    tasks = [
                        reader,
                        asyncio.create_task(receive_native()),
                        asyncio.create_task(watch()),
                        asyncio.create_task(stop.wait()),
                    ]
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        if not task.cancelled() and task.exception():
                            raise task.exception()
                    if delegation_error is not None:
                        raise delegation_error
                    stop.set()
                    with suppress(Exception):
                        await connection.session.close()
                        await asyncio.wait_for(closed.wait(), 5)
            completed_normally = True
        finally:
            stop.set()
            cleanup = [*tasks, *delegations]
            for task in cleanup:
                task.cancel()
            await asyncio.gather(*cleanup, return_exceptions=True)
            self.sessions.discard(stop)
            await self.runtime.budget.finish_voice(reservation, final_seconds, rate)
            if completed_normally:
                await send({"type": "closed"})
