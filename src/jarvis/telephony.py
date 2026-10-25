from __future__ import annotations

import asyncio
import base64
import contextlib
import hmac
import io
import json
import math
import re
import secrets
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Connect, Gather, VoiceResponse

from .db import now, uid
from .speech import speech_text


def decode_mulaw(data: bytes) -> np.ndarray:
    values = np.frombuffer(data, dtype=np.uint8).astype(np.int32)
    values = ~values & 0xFF
    samples = (((values & 0x0F) << 3) + 0x84) << ((values >> 4) & 7)
    return np.where(values & 0x80, 0x84 - samples, samples - 0x84).astype("<i2")


def encode_mulaw(pcm: np.ndarray) -> bytes:
    samples = pcm.astype(np.int32)
    sign = np.where(samples < 0, 0x80, 0)
    magnitude = np.minimum(np.abs(samples), 32635) + 0x84
    exponent = np.maximum(np.floor(np.log2(np.maximum(magnitude, 1))).astype(np.int32) - 7, 0)
    exponent = np.minimum(exponent, 7)
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa) & 0xFF).astype(np.uint8).tobytes()


def wav_bytes(samples: np.ndarray, sample_rate=8000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(samples.astype("<i2").tobytes())
    return output.getvalue()


class Telephony:
    def __init__(self, runtime):
        self.runtime, self.db, self.config = runtime, runtime.db, runtime.config
        self.media_tokens: dict[str, str] = {}
        self.active: set[str] = set()
        self.lock = asyncio.Lock()
        self.local_stt = None
        self.sockets = set()

    def ready(self) -> tuple[bool, list[str]]:
        settings = self.config.settings
        missing = []
        for name in [
            "telephony_account_id",
            "telephony_from_number",
            "owner_phone_number",
            "telephony_public_base_url",
        ]:
            if not getattr(settings, name):
                missing.append(name)
        for name in ["telephony_auth_token", "phone_pin"]:
            if not settings.secret(name):
                missing.append(name)
        for name in ["telephony_from_number", "owner_phone_number"]:
            if getattr(settings, name) and not re.fullmatch(
                r"\+[1-9][0-9]{6,14}", getattr(settings, name)
            ):
                missing.append(name + "_e164")
        if settings.phone_stt_provider == "openai" and not self.audio_key():
            missing.append("phone_api_key")
        if settings.phone_stt_provider == "faster_whisper":
            from importlib.util import find_spec

            if find_spec("faster_whisper") is None:
                missing.append("extra_voice")
        if settings.telephony_public_base_url and (
            urlsplit(settings.telephony_public_base_url).scheme != "https"
            or not urlsplit(settings.telephony_public_base_url).hostname
        ):
            missing.append("public_https_url")
        pin = settings.secret("phone_pin")
        if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
            missing.append("phone_pin_4_to_8_digits")
        return bool(settings.telephony_enabled and not missing), missing

    def audio_key(self) -> str:
        settings = self.config.settings
        return settings.secret("phone_api_key")

    async def reservation(self, *, inbound=False):
        settings = self.config.settings
        spent = await self.db.fetchone(
            "SELECT COALESCE(SUM(reservation_usd),0) AS total FROM calls WHERE created_at>=?",
            (datetime.now(UTC).date().isoformat(),),
        )
        reservation = (
            math.ceil((settings.phone_max_call_seconds + (30 if inbound else 0)) / 60)
            * settings.phone_minute_rate_usd
        )
        if spent["total"] + reservation > settings.phone_daily_budget_usd:
            raise ValueError("The daily budget cannot cover the maximum call duration.")
        return reservation

    def quiet(self) -> bool:
        from datetime import time as clock
        from zoneinfo import ZoneInfo

        hours = self.config.settings.quiet_hours
        if not hours:
            return False
        begin, end = [clock.fromisoformat(x) for x in hours.split("-")]
        current = datetime.now(ZoneInfo(self.config.settings.timezone)).time().replace(tzinfo=None)
        return begin <= current < end if begin < end else current >= begin or current < end

    async def call_owner(self, event_key: str, reason: str, task_id=None, *, authorized=False):
        if self.runtime.gateway.blocked:
            raise PermissionError("Emergency stop is active.")
        if not authorized:
            raise PermissionError("The call is not authorized.")
        ready, missing = self.ready()
        if not ready:
            raise ValueError("Complete telephony setup: " + ", ".join(missing))
        if self.config.settings.profile == "local_strict":
            raise PermissionError("Telephony is disabled by the strict local profile.")
        if self.quiet():
            raise ValueError("The call falls within the configured quiet hours.")
        async with self.lock:
            existing = await self.db.fetchone(
                "SELECT id,state,provider_id FROM calls WHERE event_key=?", (event_key,)
            )
            if existing:
                return existing
            active = await self.db.fetchone(
                "SELECT id FROM calls WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown') LIMIT 1"
            )
            if active:
                raise ValueError("A call is already active or awaiting reconciliation.")
            settings = self.config.settings
            reservation = await self.reservation()
            key = uid()
            await self.db.execute(
                "INSERT INTO calls(id,event_key,task_id,direction,state,reservation_usd,detail,created_at) VALUES(?,?,?,'outbound','creating',?,?,?)",
                (key, event_key, task_id, reservation, reason[:1000], now()),
            )
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client

            client = Client(
                settings.telephony_account_id,
                settings.secret("telephony_auth_token"),
                http_client=TwilioHttpClient(timeout=20),
            )
            base = settings.telephony_public_base_url.rstrip("/")
            try:
                result = await asyncio.to_thread(
                    client.calls.create,
                    to=settings.owner_phone_number,
                    from_=settings.telephony_from_number,
                    url=f"{base}/telephony/voice?call_id={key}",
                    status_callback=f"{base}/telephony/status?call_id={key}",
                    status_callback_event=["initiated", "ringing", "answered", "completed"],
                    timeout=25,
                    time_limit=settings.phone_max_call_seconds,
                    record=False,
                )
                await self.db.execute(
                    "UPDATE calls SET provider_id=?,state=CASE WHEN state='creating' THEN 'ringing' ELSE state END WHERE id=?",
                    (result.sid, key),
                )
                await self.db.emit("call.status", {"id": key, "state": "ringing"}, task_id)
                return {"id": key, "state": "ringing", "provider_id": result.sid}
            except BaseException as error:
                # Even a network timeout can follow a successful POST at the carrier.
                await self.db.execute("UPDATE calls SET state='unknown' WHERE id=?", (key,))
                await self.db.emit("call.status", {"id": key, "state": "unknown"}, task_id)
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ValueError(
                    "Call creation outcome is uncertain. Do not redial: check the carrier call log and reconcile."
                ) from None

    def signed(
        self, path: str, query: str, signature: str, params: dict, *, websocket=False
    ) -> bool:
        settings = self.config.settings
        if (
            not settings.telephony_enabled
            or not settings.secret("telephony_auth_token")
            or not settings.telephony_public_base_url.startswith("https://")
        ):
            return False
        url = settings.telephony_public_base_url.rstrip("/") + path + ("?" + query if query else "")
        validator = RequestValidator(settings.secret("telephony_auth_token"))
        variants = [url, url.replace("https://", "wss://", 1)] if websocket else [url]
        return any(validator.validate(candidate, params, signature) for candidate in variants)

    async def stop_all(self):
        for socket in list(self.sockets):
            with contextlib.suppress(Exception):
                await socket.close(code=1000)
        rows = await self.db.fetchall(
            "SELECT id,provider_id FROM calls WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown')"
        )
        for row in rows:
            if not row["provider_id"]:
                await self.db.execute("UPDATE calls SET state='unknown' WHERE id=?", (row["id"],))
                continue
            if row["provider_id"]:
                try:
                    from twilio.http.http_client import TwilioHttpClient
                    from twilio.rest import Client

                    client = Client(
                        self.config.settings.telephony_account_id,
                        self.config.settings.secret("telephony_auth_token"),
                        http_client=TwilioHttpClient(timeout=8),
                    )
                    await asyncio.to_thread(
                        client.calls(row["provider_id"]).update, status="completed"
                    )
                    await self.db.execute(
                        "UPDATE calls SET state='completed',ended_at=? WHERE id=?",
                        (now(), row["id"]),
                    )
                except Exception:
                    await self.db.execute(
                        "UPDATE calls SET state='unknown' WHERE id=?", (row["id"],)
                    )

    async def reconcile(
        self, key: str, *, provider_id: str = "", not_created: bool = False, note: str = ""
    ):
        row = await self.db.fetchone("SELECT * FROM calls WHERE id=?", (key,))
        if not row or row["state"] != "unknown":
            raise ValueError("The call does not require reconciliation.")
        if len(note.strip()) < 5:
            raise ValueError("Describe the verification performed in the carrier call log.")
        if not_created and not provider_id:
            await self.db.execute(
                "UPDATE calls SET state='verified_not_created',reservation_usd=0,detail=?,ended_at=? WHERE id=?",
                (note[:1000], now(), key),
            )
            return {"state": "verified_not_created"}
        if not re.fullmatch(r"CA[0-9a-fA-F]{32}", provider_id):
            raise ValueError("Enter the Call SID observed in the carrier log.")
        if self.config.settings.profile == "local_strict":
            raise PermissionError(
                "Remote call verification is unavailable in the strict local profile."
            )
        from twilio.http.http_client import TwilioHttpClient
        from twilio.rest import Client

        settings = self.config.settings
        client = Client(
            settings.telephony_account_id,
            settings.secret("telephony_auth_token"),
            http_client=TwilioHttpClient(timeout=10),
        )
        call = await asyncio.to_thread(client.calls(provider_id).fetch)
        if call.to != settings.owner_phone_number or call.from_ != settings.telephony_from_number:
            raise ValueError("The SID does not match the call's authorized numbers.")
        if (
            call.date_created
            and abs((call.date_created - datetime.fromisoformat(row["created_at"])).total_seconds())
            > 300
        ):
            raise ValueError("The SID does not match the request time.")
        await self.db.execute(
            "UPDATE calls SET provider_id=?,state=?,detail=? WHERE id=?",
            (provider_id, call.status, note[:1000], key),
        )
        return {"state": call.status, "provider_id": provider_id}

    async def stt(self, samples: np.ndarray) -> str:
        settings = self.config.settings
        data = wav_bytes(samples)
        if settings.phone_stt_provider == "openai":
            from openai import AsyncOpenAI

            async with AsyncOpenAI(api_key=self.audio_key(), max_retries=0, timeout=30) as client:
                result = await client.audio.transcriptions.create(
                    model=settings.phone_stt_model,
                    file=("turn.wav", data, "audio/wav"),
                )
            return result.text

        def recognize():
            from faster_whisper import WhisperModel

            if self.local_stt is None:
                self.local_stt = WhisperModel(
                    settings.phone_local_stt_model,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
            segments, _ = self.local_stt.transcribe(
                io.BytesIO(data), language=None, vad_filter=True
            )
            return " ".join(segment.text for segment in segments)

        return await asyncio.to_thread(recognize)

    async def tts(self, text: str) -> bytes:
        settings = self.config.settings
        if self.audio_key():
            from openai import AsyncOpenAI

            async with AsyncOpenAI(api_key=self.audio_key(), timeout=40, max_retries=0) as client:
                response = await client.audio.speech.create(
                    model=settings.phone_tts_model,
                    voice=settings.phone_tts_voice,
                    input=text[:4000],
                    response_format="pcm",
                )
                pcm = np.frombuffer(response.content, dtype="<i2")
            # Provider PCM is 24 kHz; decimate with a low-pass average to 8 kHz.
            pcm = (
                pcm[: len(pcm) // 3 * 3]
                .astype(np.float64)
                .reshape(-1, 3)
                .mean(axis=1)
                .astype("<i2")
            )
            return encode_mulaw(pcm)
        with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as directory:
            aiff, wav = Path(directory) / "voice.aiff", Path(directory) / "voice.wav"
            args = ["/usr/bin/say", "-o", str(aiff)]
            if settings.phone_local_tts_voice:
                args += ["-v", settings.phone_local_tts_voice]
            args += [text[:4000]]
            process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                await asyncio.wait_for(process.wait(), 30)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if process.returncode:
                raise ValueError("Local speech synthesis failed.")
            convert = await asyncio.create_subprocess_exec(
                "/usr/bin/afconvert",
                "-f",
                "WAVE",
                "-d",
                "LEI16@8000",
                "-c",
                "1",
                str(aiff),
                str(wav),
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(convert.wait(), 10)
            if convert.returncode:
                raise ValueError("Phone audio conversion failed.")
            with wave.open(str(wav), "rb") as file:
                return encode_mulaw(np.frombuffer(file.readframes(file.getnframes()), dtype="<i2"))

    async def media(self, websocket: WebSocket):
        if (
            not self.ready()[0]
            or self.config.settings.profile == "local_strict"
            or self.runtime.gateway.blocked
        ):
            await websocket.close(code=1008)
            return
        if not self.signed(
            websocket.url.path,
            websocket.url.query,
            websocket.headers.get("x-twilio-signature", ""),
            {},
            websocket=True,
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        self.sockets.add(websocket)
        key = stream_sid = conversation_id = None
        session_scope = "personal"
        answer = None
        speaking = False
        frames = []
        voiced_frames = quiet_frames = 0
        pending_approval = None

        async def speak(text):
            nonlocal speaking
            data = await self.tts(text)
            speaking = True
            try:
                for offset in range(0, len(data), 160):
                    await websocket.send_json(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": base64.b64encode(data[offset : offset + 160]).decode()
                            },
                        }
                    )
                    await asyncio.sleep(0.02)
                await websocket.send_json(
                    {"event": "mark", "streamSid": stream_sid, "mark": {"name": "reply-complete"}}
                )
            finally:
                speaking = False

        async def wait_task(task):
            nonlocal pending_approval
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                row = await self.db.fetchone(
                    "SELECT state,result,error FROM tasks WHERE id=?", (task["id"],)
                )
                if row["state"] == "succeeded":
                    await speak(speech_text(row["result"]))
                    return
                if row["state"] == "waiting_user":
                    proposals = await self.db.fetchall(
                        "SELECT * FROM approvals WHERE task_id=? AND state='pending' AND expires_at>?",
                        (task["id"], now()),
                    )
                    if len(proposals) != 1:
                        await speak("The proposal requires review in the Mac dashboard.")
                        return
                    proposal = proposals[0]
                    brief = json.dumps(json.loads(proposal["arguments"]), ensure_ascii=False)
                    if len(brief) > 1000:
                        await speak(
                            "The proposal is too long for phone confirmation. Review it in the dashboard."
                        )
                        return
                    # Read the exact gateway proposal. Never let model prose authorize it.
                    pending_approval = {
                        "id": proposal["id"],
                        "task_id": task["id"],
                        "expires_at": proposal["expires_at"],
                    }
                    await speak(
                        f"Confirmation required for {proposal['tool']}. Parameters: {brief}. Press one to approve this action or two to reject it."
                    )
                    return
                if row["state"] in {"failed", "cancelled"}:
                    await speak(
                        "I did not complete the operation. Details are available in the dashboard."
                    )
                    return
                await asyncio.sleep(0.2)
            await speak(
                "Work continues in the background. The result will be available on the Mac."
            )

        async def respond(samples):
            nonlocal conversation_id
            try:
                text = (await self.stt(samples)).strip()
                if not text:
                    return
                if text.casefold().strip(" .!?") in {
                    "riaggancia",
                    "chiudi la chiamata",
                    "arrivederci",
                    "hang up",
                    "end the call",
                    "goodbye",
                }:
                    await speak("Goodbye.")
                    await websocket.close()
                    return
                if pending_approval and pending_approval["expires_at"] > now():
                    await speak(
                        "Press one to approve the proposal you just heard or two to reject it."
                    )
                    return
                task = await self.runtime.tasks.create(
                    text,
                    conversation_id=conversation_id,
                    profile=self.config.settings.profile,
                    scope=session_scope,
                    channel="phone",
                )
                conversation_id = task["conversation_id"]
                await wait_task(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                await speak("The voice request failed. Check connections in the dashboard.")

        try:
            async with asyncio.timeout(self.config.settings.phone_max_call_seconds):
                async for raw in websocket.iter_text():
                    if len(raw) > 100_000:
                        raise ValueError("Phone frame exceeds the size limit.")
                    event = json.loads(raw)
                    if event.get("event") == "start":
                        if stream_sid:
                            raise PermissionError("Media session has already started.")
                        start = event["start"]
                        fmt = start.get("mediaFormat", {})
                        if (
                            fmt.get("encoding") != "audio/x-mulaw"
                            or int(fmt.get("sampleRate", 0)) != 8000
                            or int(fmt.get("channels", 0)) != 1
                        ):
                            raise ValueError("Unsupported phone audio format.")
                        params = start.get("customParameters", {})
                        key = params.get("call_id")
                        secret = self.media_tokens.pop(key, "")
                        row = await self.db.fetchone("SELECT * FROM calls WHERE id=?", (key,))
                        if (
                            not row
                            or not row["auth_verified"]
                            or not secret
                            or not hmac.compare_digest(secret, params.get("token", ""))
                            or row["provider_id"] != start.get("callSid")
                            or key in self.active
                        ):
                            raise PermissionError("Unauthorized media session.")
                        self.active.add(key)
                        if row["task_id"]:
                            origin = await self.db.fetchone(
                                "SELECT conversation_id,scope FROM tasks WHERE id=?",
                                (row["task_id"],),
                            )
                            if origin:
                                conversation_id, session_scope = (
                                    origin["conversation_id"],
                                    origin["scope"],
                                )
                        stream_sid = start["streamSid"]
                        await self.db.execute(
                            "UPDATE calls SET state='connected' WHERE id=?", (key,)
                        )
                        await self.db.emit(
                            "call.status", {"id": key, "state": "connected"}, row["task_id"]
                        )
                        answer = asyncio.create_task(
                            speak(
                                "I am Jarvis. Identity verified. "
                                + (
                                    "I am calling about " + row["detail"][:400] + ". "
                                    if row["detail"]
                                    else ""
                                )
                                + "Tell me how I can help."
                            )
                        )
                    elif event.get("event") == "dtmf" and stream_sid and pending_approval:
                        digit = event.get("dtmf", {}).get("digit")
                        if digit not in {"1", "2"}:
                            continue
                        proposal, pending_approval = pending_approval, None
                        if answer:
                            answer.cancel()
                        await websocket.send_json({"event": "clear", "streamSid": stream_sid})
                        try:
                            task_id = await self.runtime.gateway.decide(
                                proposal["id"], digit == "1"
                            )
                            await self.runtime.tasks.resume(task_id)
                            answer = asyncio.create_task(wait_task({"id": task_id}))
                        except ValueError:
                            answer = asyncio.create_task(
                                speak("This proposal has expired or has already been decided.")
                            )
                    elif event.get("event") == "media" and stream_sid:
                        pcm = decode_mulaw(
                            base64.b64decode(event["media"]["payload"], validate=True)
                        )
                        level = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
                        voice = level > 550
                        if voice:
                            voiced_frames += 1
                            quiet_frames = 0
                            if speaking and voiced_frames >= 3:
                                if answer:
                                    answer.cancel()
                                await websocket.send_json(
                                    {"event": "clear", "streamSid": stream_sid}
                                )
                        elif frames:
                            quiet_frames += 1
                        if voice or frames:
                            frames.append(pcm)
                        if frames and (quiet_frames >= 35 or len(frames) >= 1500):
                            if voiced_frames >= 8:
                                if answer:
                                    answer.cancel()
                                answer = asyncio.create_task(respond(np.concatenate(frames)))
                            frames, voiced_frames, quiet_frames = [], 0, 0
                    elif event.get("event") == "stop":
                        break
        except (TimeoutError, ValueError, PermissionError):
            with contextlib.suppress(Exception):
                await websocket.close(code=1008)
        finally:
            self.sockets.discard(websocket)
            if answer:
                answer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await answer
            if key:
                self.active.discard(key)
                await self.db.execute(
                    "UPDATE calls SET state='completed',ended_at=? WHERE id=? AND state='connected'",
                    (now(), key),
                )

    def router(self):
        router = APIRouter()

        async def signed_form(request):
            if int(request.headers.get("content-length", "0")) > 16384:
                raise PermissionError("Request is too large.")
            params = dict(await request.form())
            if not self.signed(
                request.url.path,
                request.url.query,
                request.headers.get("x-twilio-signature", ""),
                params,
            ):
                raise PermissionError("Invalid telephony signature.")
            return params

        @router.post("/telephony/voice")
        async def voice(request: Request):
            if (
                not self.ready()[0]
                or self.config.settings.profile == "local_strict"
                or self.runtime.gateway.blocked
            ):
                return Response(status_code=403)
            try:
                params = await signed_form(request)
            except PermissionError:
                return Response(status_code=403)
            settings = self.config.settings
            key = request.query_params.get("call_id")
            row = await self.db.fetchone("SELECT * FROM calls WHERE id=?", (key,)) if key else None
            sid = params.get("CallSid", "")
            result = VoiceResponse()
            if not re.fullmatch(r"CA[0-9a-fA-F]{32}", sid):
                return Response(status_code=403)
            if row is None:
                if key or params.get("From") != settings.owner_phone_number:
                    result.hangup()
                    return Response(str(result), media_type="text/xml")
                async with self.lock:
                    row = await self.db.fetchone("SELECT * FROM calls WHERE provider_id=?", (sid,))
                    if row is None:
                        active = await self.db.fetchone(
                            "SELECT id FROM calls WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown') LIMIT 1"
                        )
                        if active:
                            result.hangup()
                            return Response(str(result), media_type="text/xml")
                        try:
                            reserve = await self.reservation(inbound=True)
                        except ValueError:
                            result.hangup()
                            return Response(str(result), media_type="text/xml")
                        key = uid()
                        await self.db.execute(
                            "INSERT INTO calls(id,event_key,direction,state,provider_id,reservation_usd,created_at) VALUES(?,?,'inbound','answered',?,?,?)",
                            (key, "inbound:" + sid, sid, reserve, now()),
                        )
                        row = await self.db.fetchone(
                            "SELECT * FROM calls WHERE provider_id=?", (sid,)
                        )
                key = row["id"]
            if row["state"] in {
                "completed",
                "failed",
                "busy",
                "no-answer",
                "canceled",
                "verified_not_created",
            }:
                result.hangup()
                return Response(str(result), media_type="text/xml")
            if row["provider_id"] and row["provider_id"] != sid:
                return Response(status_code=403)
            await self.db.execute("UPDATE calls SET provider_id=? WHERE id=?", (sid, key))
            if not row["auth_verified"]:
                digits = params.get("Digits", "")
                pin = settings.secret("phone_pin")
                if digits and pin and hmac.compare_digest(digits, pin):
                    await self.db.execute("UPDATE calls SET auth_verified=1 WHERE id=?", (key,))
                elif row["attempts"] >= 3:
                    await self.db.execute(
                        "UPDATE calls SET state='failed',ended_at=? WHERE id=?", (now(), key)
                    )
                    result.hangup()
                    return Response(str(result), media_type="text/xml")
                else:
                    await self.db.execute("UPDATE calls SET attempts=attempts+1 WHERE id=?", (key,))
                    gather = Gather(
                        action_on_empty_result=True,
                        input="dtmf",
                        num_digits=len(pin),
                        timeout=8,
                        action=settings.telephony_public_base_url.rstrip("/")
                        + "/telephony/voice?call_id="
                        + key,
                        method="POST",
                    )
                    gather.say(
                        "I am Jarvis. Enter your personal code to continue.",
                        language="en-GB",
                    )
                    result.append(gather)
                    result.hangup()
                    return Response(str(result), media_type="text/xml")
            token = secrets.token_urlsafe(32)
            self.media_tokens[key] = token
            connect = Connect()
            stream = connect.stream(
                url=settings.telephony_public_base_url.rstrip("/").replace("https://", "wss://", 1)
                + "/telephony/media"
            )
            stream.parameter(name="call_id", value=key)
            stream.parameter(name="token", value=token)
            result.append(connect)
            return Response(str(result), media_type="text/xml")

        @router.post("/telephony/status")
        async def status(request: Request):
            try:
                params = await signed_form(request)
            except PermissionError:
                return Response(status_code=403)
            sid = params.get("CallSid")
            key = request.query_params.get("call_id")
            row = await self.db.fetchone(
                "SELECT * FROM calls WHERE id=? OR provider_id=? LIMIT 1", (key, sid)
            )
            if row and (not row["provider_id"] or row["provider_id"] == sid):
                state = params.get("CallStatus", "unknown")
                terminal = {"completed", "failed", "busy", "no-answer", "canceled"}
                rank = {
                    "creating": 0,
                    "queued": 1,
                    "initiated": 1,
                    "ringing": 2,
                    "answered": 3,
                    "in-progress": 3,
                    "connected": 4,
                    "unknown": 0,
                }
                if row["state"] not in terminal and (
                    state in terminal or rank.get(state, -1) >= rank.get(row["state"], 0)
                ):
                    await self.db.execute(
                        "UPDATE calls SET provider_id=?,state=?,ended_at=? WHERE id=?",
                        (sid, state, now() if state in terminal else None, row["id"]),
                    )
                    await self.db.emit(
                        "call.status", {"id": row["id"], "state": state}, row["task_id"]
                    )
            return Response(status_code=204)

        @router.websocket("/telephony/media")
        async def media(websocket: WebSocket):
            await self.media(websocket)

        return router
