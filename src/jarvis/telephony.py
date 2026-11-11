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
import sys
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import numpy as np
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Connect, Gather, VoiceResponse

from .db import now, uid
from .phone_prompts import phone_language, phone_message, phone_opening
from .speech import speech_text
from .telephony_ingress import webhook_signature
from .telephony_tunnel import TelephonyTunnel
from .voice_progress import task_progress
from .voice_style import voice_api_key

TERMINAL_CALL_STATES = {
    "completed",
    "failed",
    "busy",
    "no-answer",
    "canceled",
    "verified_not_created",
}
CALL_RANK = {
    "creating": 0,
    "unknown": 0,
    "queued": 1,
    "initiated": 1,
    "ringing": 2,
    "answered": 3,
    "in-progress": 3,
    "connected": 4,
}


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
        self.prepared_voice: dict = {}
        self.lock = asyncio.Lock()
        self.refresh_lock = asyncio.Lock()
        self.last_refresh = 0.0
        self.local_stt = None
        self.sockets = set()
        self.tunnel = TelephonyTunnel(self)

    @property
    def public_base_url(self) -> str:
        if self.config.settings.telephony_tunnel_mode == "managed":
            if self.runtime.remote:
                return self.runtime.remote.options.public_url
            return self.tunnel.url
        return self.config.settings.telephony_public_base_url

    def ready(self, *, transport=True) -> tuple[bool, list[str]]:
        settings = self.config.settings
        missing = []
        for name in [
            "telephony_account_id",
            "telephony_from_number",
            "owner_phone_number",
        ]:
            if not getattr(settings, name):
                missing.append(name)
        required_secrets = ["telephony_auth_token"]
        if settings.phone_pin_enabled or settings.phone_inbound_enabled:
            required_secrets.append("phone_pin")
        for name in required_secrets:
            if not settings.secret(name):
                missing.append(name)
        for name in ["telephony_from_number", "owner_phone_number"]:
            if getattr(settings, name) and not re.fullmatch(
                r"\+[1-9][0-9]{6,14}", getattr(settings, name)
            ):
                missing.append(name + "_e164")
        if self.uses_desktop_voice():
            if not voice_api_key(settings):
                missing.append("desktop_voice_api_key")
        elif settings.phone_stt_provider == "openai" and not self.audio_key():
            missing.append("phone_api_key")
        elif settings.phone_stt_provider == "faster_whisper":
            from importlib.util import find_spec

            if find_spec("faster_whisper") is None:
                missing.append("extra_voice")
        if transport and not self.public_base_url:
            missing.append("telephony_public_base_url")
        if transport and self.public_base_url and (
            urlsplit(self.public_base_url).scheme != "https"
            or not urlsplit(self.public_base_url).hostname
        ):
            missing.append("public_https_url")
        if transport and settings.telephony_tunnel_mode == "managed" and self.tunnel.state != "running":
            missing.append("telephony_tunnel")
        if settings.phone_pin_enabled or settings.phone_inbound_enabled:
            pin = settings.secret("phone_pin")
            if pin and not re.fullmatch(r"[0-9]{6,8}", pin):
                missing.append("phone_pin_6_to_8_digits")
        return bool(settings.telephony_enabled and not missing), missing

    def audio_key(self) -> str:
        settings = self.config.settings
        return settings.secret("phone_api_key")

    def uses_desktop_voice(self) -> bool:
        return self.config.settings.desktop_voice_provider == "openai_live"

    def message(self, name: str, **values) -> str:
        return phone_message(self.config.settings, name, **values)

    def requires_pin(self, direction: str) -> bool:
        # Caller ID can be spoofed. Only an owner-authorized outbound call may
        # waive the PIN; inbound access always needs the configured secret.
        return direction == "inbound" or self.config.settings.phone_pin_enabled

    def prepare_voice(self, row: dict):
        if (
            not self.uses_desktop_voice()
            or not row["auth_verified"]
            or row["id"] in self.active
            or row["id"] in self.prepared_voice
            or self.runtime.gateway.blocked
            or self.config.settings.profile == "local_strict"
        ):
            return
        from .phone_live import PhoneLive

        voice = PhoneLive(self, None, row, None, None, "personal")
        self.prepared_voice[row["id"]] = voice
        voice.job = asyncio.create_task(voice.prepare())

        def finished(job):
            if self.prepared_voice.get(row["id"]) is voice:
                self.prepared_voice.pop(row["id"], None)
            if not job.cancelled():
                job.exception()  # A failed preparation falls back to normal startup.

        voice.job.add_done_callback(finished)

    async def close_prepared_voice(self, key: str):
        voice = self.prepared_voice.pop(key, None)
        if voice:
            voice.stop.set()
            voice.attached.set()
            voice.job.cancel()
            await asyncio.gather(voice.job, return_exceptions=True)

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

    def probe_proof(self, challenge: str) -> str:
        return hmac.new(
            self.config.token.encode(), ("jarvis-telephony:" + challenge).encode(), "sha256"
        ).hexdigest()

    async def check_reachability(self):
        """Prove the public proxy reaches this instance before making a paid call."""
        settings = self.config.settings
        url = self.public_base_url.rstrip("/") + "/telephony/status"
        challenge = secrets.token_urlsafe(24)
        params = {"JarvisProbe": challenge}
        signature = RequestValidator(settings.secret("telephony_auth_token")).compute_signature(
            url, params
        )
        try:
            async with (
                asyncio.timeout(8),
                httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client,
            ):
                async with client.stream(
                    "POST", url, data=params, headers={"X-Twilio-Signature": signature}
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 4096:
                            raise ValueError("Proxy response exceeds its size limit.")
                proof = json.loads(body).get("proof", "")
                if isinstance(proof, str) and hmac.compare_digest(
                    proof.encode(), self.probe_proof(challenge).encode()
                ):
                    return
        except (httpx.HTTPError, TimeoutError, ValueError, AttributeError):
            pass
        raise ValueError(
            "The public telephony proxy is unreachable or does not reach this Jarvis instance. Check the tunnel URL before calling."
        )

    def verify_carrier_call(self, row: dict, call):
        settings = self.config.settings
        expected_to, expected_from = settings.owner_phone_number, settings.telephony_from_number
        if row["direction"] == "inbound":
            expected_to, expected_from = expected_from, expected_to
        if (
            (row["provider_id"] and row["provider_id"] != call.sid)
            or call.to != expected_to
            or call._from != expected_from
        ):
            raise ValueError("The SID does not match the call's authorized numbers.")
        if (
            call.date_created
            and abs((call.date_created - datetime.fromisoformat(row["created_at"])).total_seconds())
            > 300
        ):
            raise ValueError("The SID does not match the request time.")

    def settled_reservation(self, state: str, duration=None, price=None) -> float | None:
        if state not in TERMINAL_CALL_STATES:
            return None
        # Use rounded actual minutes at the configured conservative rate. Keep
        # the full reservation when the carrier has not reported usage yet.
        amount = None
        if duration is not None and str(duration).isdecimal():
            amount = (
                max(1, math.ceil(int(duration) / 60)) * self.config.settings.phone_minute_rate_usd
            )
        if price is not None:
            try:
                price = abs(float(price))
                if math.isfinite(price):
                    amount = max(amount or 0, price)
            except (TypeError, ValueError):
                pass
        return amount

    async def update_status(
        self, row: dict, sid: str, state: str, *, ended_at=None, reservation=None
    ):
        if state not in CALL_RANK and state not in TERMINAL_CALL_STATES:
            return
        if row["state"] in TERMINAL_CALL_STATES:
            if row["state"] != state:
                return
        elif state not in TERMINAL_CALL_STATES and CALL_RANK[state] < CALL_RANK.get(
            row["state"], 0
        ):
            return
        terminal = state in TERMINAL_CALL_STATES
        ended = (ended_at or row["ended_at"] or now()) if terminal else None
        reserved = row["reservation_usd"] if reservation is None or not terminal else reservation
        if (row["state"], row["ended_at"], row["reservation_usd"]) == (state, ended, reserved):
            return
        changed = await self.db.execute(
            "UPDATE calls SET provider_id=?,state=?,ended_at=?,reservation_usd=? WHERE id=? AND state=? AND (provider_id IS NULL OR provider_id=?)",
            (sid, state, ended, reserved, row["id"], row["state"], sid),
        )
        if changed:
            if terminal:
                self.active.discard(row["id"])
                self.media_tokens.pop(row["id"], None)
                await self.close_prepared_voice(row["id"])
            await self.db.emit("call.status", {"id": row["id"], "state": state}, row["task_id"])
            if (
                state in {"answered", "in-progress"}
                and row["direction"] == "outbound"
                and not self.requires_pin("outbound")
                and self.uses_desktop_voice()
            ):
                # A signed/carrier-verified answer to an owner-authorized outbound
                # call can prepare the voice while Twilio finishes its own preamble.
                await self.db.execute("UPDATE calls SET auth_verified=1 WHERE id=?", (row["id"],))
                self.prepare_voice({**row, "auth_verified": 1, "state": state, "provider_id": sid})

    async def refresh_calls(self, *, force=False):
        settings = self.config.settings
        if (
            settings.profile == "local_strict"
            or not settings.telephony_enabled
            or not settings.telephony_account_id
            or not settings.secret("telephony_auth_token")
        ):
            return
        async with self.refresh_lock:
            if not force and time.monotonic() - self.last_refresh < 15:
                return
            rows = await self.db.fetchall(
                "SELECT * FROM calls WHERE provider_id IS NOT NULL AND state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown') LIMIT 10"
            )
            if not rows:
                return
            self.last_refresh = time.monotonic()
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client

            client = Client(
                settings.telephony_account_id,
                settings.secret("telephony_auth_token"),
                http_client=TwilioHttpClient(timeout=8),
            )
            for row in rows:
                try:
                    call = await asyncio.to_thread(client.calls(row["provider_id"]).fetch)
                    self.verify_carrier_call(row, call)
                except Exception:
                    # A failed lookup is not evidence the call ended. In particular,
                    # an uncertain creation without a SID still needs manual review.
                    continue
                ended = call.end_time.astimezone(UTC).isoformat() if call.end_time else None
                await self.update_status(
                    row,
                    call.sid,
                    call.status,
                    ended_at=ended,
                    reservation=self.settled_reservation(call.status, call.duration, call.price),
                )

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
            await self.refresh_calls(force=True)
            active = await self.db.fetchone(
                "SELECT id FROM calls WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown') LIMIT 1"
            )
            if active:
                raise ValueError("A call is already active or awaiting reconciliation.")
            settings = self.config.settings
            if self.runtime.gateway.blocked or settings.profile == "local_strict":
                raise PermissionError("Telephony is unavailable for this session.")
            reservation = await self.reservation()
            base = self.public_base_url.rstrip("/")
            await self.check_reachability()
            if (
                settings is not self.config.settings
                or base != self.public_base_url.rstrip("/")
                or not self.ready()[0]
            ):
                raise ValueError("Telephony settings changed. Review them before calling again.")
            if self.runtime.gateway.blocked or settings.profile == "local_strict":
                raise PermissionError("Telephony is unavailable for this session.")
            key = uid()
            await self.db.execute(
                "INSERT INTO calls(id,event_key,task_id,direction,state,reservation_usd,detail,created_at) VALUES(?,?,?,'outbound','creating',?,?,?)",
                (key, event_key, task_id, reservation, reason, now()),
            )
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client

            client = Client(
                settings.telephony_account_id,
                settings.secret("telephony_auth_token"),
                http_client=TwilioHttpClient(timeout=20),
            )
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
            or not re.fullmatch(r"[A-Za-z0-9+/]{27}=", signature)
            or not settings.secret("telephony_auth_token")
            or not self.public_base_url.startswith("https://")
        ):
            return False
        url = self.public_base_url.rstrip("/") + path + ("?" + query if query else "")
        validator = RequestValidator(settings.secret("telephony_auth_token"))
        variants = [url, url.replace("https://", "wss://", 1)] if websocket else [url]
        return any(validator.validate(candidate, params, signature) for candidate in variants)

    async def configure_inbound_webhooks(self) -> bool:
        """Point the explicitly enabled incoming line at this activation's URL."""
        settings = self.config.settings
        if not settings.phone_inbound_enabled:
            return False
        from twilio.http.async_http_client import AsyncTwilioHttpClient
        from twilio.rest import Client

        http_client = AsyncTwilioHttpClient(timeout=8)
        try:
            async with asyncio.timeout(20):
                client = Client(
                    settings.telephony_account_id,
                    settings.secret("telephony_auth_token"),
                    http_client=http_client,
                )
                numbers = await client.incoming_phone_numbers.list_async(
                    phone_number=settings.telephony_from_number, limit=2
                )
                if len(numbers) != 1 or numbers[0].phone_number != settings.telephony_from_number:
                    raise ValueError("The incoming Twilio number could not be found.")
                base = self.public_base_url.rstrip("/")
                await numbers[0].update_async(
                    voice_url=base + "/telephony/voice", voice_method="POST",
                    voice_application_sid="",
                    status_callback=base + "/telephony/status", status_callback_method="POST",
                )
            return True
        except Exception:
            raise ValueError("Could not update incoming call webhooks. Check the Twilio account and number.") from None
        finally:
            await http_client.close()

    async def stop_all(self, *, carrier_settings=None):
        await self.tunnel.stop()
        async with self.lock:
            await self._stop_calls(carrier_settings or self.config.settings)

    async def _stop_calls(self, settings):
        for key in list(self.prepared_voice):
            await self.close_prepared_voice(key)
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
                        settings.telephony_account_id,
                        settings.secret("telephony_auth_token"),
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
        self.verify_carrier_call(row, call)
        await self.db.execute(
            "UPDATE calls SET detail=? WHERE id=?",
            (note[:1000], key),
        )
        await self.update_status(
            row,
            provider_id,
            call.status,
            ended_at=call.end_time.astimezone(UTC).isoformat() if call.end_time else None,
            reservation=self.settled_reservation(call.status, call.duration, call.price),
        )
        return {"state": call.status, "provider_id": provider_id}

    async def stt(self, samples: np.ndarray) -> str:
        settings = self.config.settings
        data = wav_bytes(samples)
        if settings.phone_stt_provider == "openai":
            from openai import AsyncOpenAI

            async with AsyncOpenAI(
                api_key=self.audio_key(),
                base_url="https://api.openai.com/v1",
                organization="",
                project="",
                max_retries=0,
                timeout=30,
            ) as client:
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

            async with AsyncOpenAI(
                api_key=self.audio_key(),
                base_url="https://api.openai.com/v1",
                organization="",
                project="",
                timeout=40,
                max_retries=0,
            ) as client:
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
        if sys.platform != "darwin":
            raise ValueError(
                "Local Apple phone synthesis requires macOS. Configure an OpenAI phone API key on Windows or Linux."
            )
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
        signature = webhook_signature(websocket.headers)
        if (
            not signature
            or self.config.settings.profile == "local_strict"
            or self.runtime.gateway.blocked
        ):
            await websocket.close(code=1008)
            return
        if not self.signed(
            websocket.url.path,
            websocket.url.query,
            signature,
            {},
            websocket=True,
        ):
            await websocket.close(code=1008)
            return
        if not self.ready()[0]:
            await websocket.close(code=1008)
            return
        if len(self.sockets) >= 2:
            await websocket.close(code=1008)
            return
        # Reserve admission before the handshake yields to another connection.
        self.sockets.add(websocket)
        key = claimed_key = stream_sid = conversation_id = None
        session_scope = "personal"
        session_direction = "outbound"
        answer = None
        speaking = False
        frames = []
        voiced_frames = quiet_frames = 0
        pending_approval = None

        async def speak(text, *, approval_mark=None):
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
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": approval_mark or "reply-complete"},
                    }
                )
            finally:
                speaking = False

        async def wait_task(task):
            nonlocal pending_approval
            deadline = time.monotonic() + 120
            announced = False
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
                        await speak(self.message("dashboard"))
                        return
                    proposal = proposals[0]
                    brief = json.dumps(json.loads(proposal["arguments"]), ensure_ascii=False)
                    if len(brief) > 1000:
                        await speak(self.message("long_proposal"))
                        return
                    # Read the exact gateway proposal. Never let model prose authorize it.
                    pending_approval = {
                        "id": proposal["id"],
                        "task_id": task["id"],
                        "expires_at": proposal["expires_at"],
                        "mark": "approval-" + secrets.token_urlsafe(16),
                        "heard": False,
                    }
                    await speak(
                        self.message("approval", tool=proposal["tool"], arguments=brief),
                        approval_mark=pending_approval["mark"],
                    )
                    return
                if row["state"] in {"failed", "cancelled"}:
                    await speak(self.message("failed"))
                    return
                if row["state"] == "running" and not announced:
                    update = await task_progress(self.db, task["id"])
                    if update:
                        announced = True
                        with contextlib.suppress(Exception):
                            await speak(update["text"])
                await asyncio.sleep(0.2)
            await speak(self.message("background"))

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
                    await speak(self.message("goodbye"))
                    await websocket.close()
                    return
                if pending_approval and pending_approval["expires_at"] > now():
                    await speak(self.message("pending"))
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
                await speak(self.message("request_failed"))

        async def incoming():
            source = websocket.iter_text()
            deadline = time.monotonic() + 5
            while True:
                try:
                    async with asyncio.timeout_at(None if claimed_key else deadline):
                        raw = await anext(source)
                except StopAsyncIteration:
                    return
                yield raw

        try:
            await websocket.accept()
            async with asyncio.timeout(self.config.settings.phone_max_call_seconds):
                events = incoming()
                async for raw in events:
                    if len(raw) > 100_000:
                        raise ValueError("Phone frame exceeds the size limit.")
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError("Invalid phone event.")
                    if (
                        claimed_key
                        and session_direction == "inbound"
                        and not self.config.settings.phone_inbound_enabled
                    ):
                        raise PermissionError("Inbound phone access was disabled.")
                    if event.get("event") == "start":
                        if stream_sid:
                            raise PermissionError("Media session has already started.")
                        start = event["start"]
                        if not isinstance(start, dict):
                            raise ValueError("Invalid phone start event.")
                        fmt = start.get("mediaFormat", {})
                        if (
                            not isinstance(fmt, dict)
                            or fmt.get("encoding") != "audio/x-mulaw"
                            or int(fmt.get("sampleRate", 0)) != 8000
                            or int(fmt.get("channels", 0)) != 1
                        ):
                            raise ValueError("Unsupported phone audio format.")
                        params = start.get("customParameters", {})
                        if not isinstance(params, dict):
                            raise ValueError("Invalid phone parameters.")
                        key = params.get("call_id")
                        if not isinstance(key, str) or not 1 <= len(key) <= 128:
                            raise PermissionError("Unauthorized media session.")
                        if start.get("accountSid") != self.config.settings.telephony_account_id:
                            raise PermissionError("Unauthorized media account.")
                        if (
                            not isinstance(start.get("streamSid"), str)
                            or not 1 <= len(start["streamSid"]) <= 64
                        ):
                            raise ValueError("Invalid media stream identifier.")
                        secret = self.media_tokens.get(key, "")
                        row = await self.db.fetchone("SELECT * FROM calls WHERE id=?", (key,))
                        if (
                            not row
                            or not row["auth_verified"]
                            or not secret
                            or not isinstance(params.get("token"), str)
                            or not hmac.compare_digest(
                                secret.encode(), params.get("token", "").encode()
                            )
                            or row["provider_id"] != start.get("callSid")
                            or key in self.active
                            or row["state"]
                            not in {
                                "creating",
                                "queued",
                                "initiated",
                                "ringing",
                                "answered",
                                "in-progress",
                                "connected",
                            }
                        ):
                            raise PermissionError("Unauthorized media session.")
                        self.media_tokens.pop(key, None)
                        self.active.add(key)
                        claimed_key = key
                        session_direction = row["direction"]
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
                        if self.uses_desktop_voice():
                            from .phone_live import PhoneLive

                            try:
                                prepared = self.prepared_voice.get(key)
                                if prepared:
                                    try:
                                        prepared.attach(
                                            websocket, stream_sid, conversation_id, session_scope, events
                                        )
                                    except (PermissionError, ValueError):
                                        await self.close_prepared_voice(key)
                                        prepared = None
                                if prepared:
                                    self.prepared_voice.pop(key, None)
                                    await prepared.job
                                else:
                                    await PhoneLive(
                                        self, websocket, row, stream_sid, conversation_id, session_scope
                                    ).run(events)
                            except Exception as error:
                                await self.db.emit(
                                    "call.voice_error", {"id": key, "code": type(error).__name__}
                                )
                                raise ValueError(
                                    "The phone voice connection was interrupted."
                                ) from None
                            finally:
                                with contextlib.suppress(Exception):
                                    await websocket.close()
                            break
                        answer = asyncio.create_task(
                            speak(
                                phone_opening(
                                    self.config.settings,
                                    row,
                                    verified=self.requires_pin(row["direction"]),
                                )
                            )
                        )
                    elif event.get("event") == "mark" and pending_approval:
                        if (
                            pending_approval["mark"]
                            and event.get("mark", {}).get("name") == pending_approval["mark"]
                        ):
                            pending_approval["heard"] = True
                    elif event.get("event") == "dtmf" and stream_sid and pending_approval:
                        digit = event.get("dtmf", {}).get("digit")
                        if digit not in {"1", "2"}:
                            continue
                        if digit == "1" and not pending_approval["heard"]:
                            # Keep the readback playing; only the matching carrier
                            # playback acknowledgment can authorize keypad approval.
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
                            answer = asyncio.create_task(speak(self.message("expired")))
                    elif event.get("event") == "media" and stream_sid:
                        data = base64.b64decode(event["media"]["payload"], validate=True)
                        if not data or len(data) > 8000:
                            raise ValueError("Invalid phone input audio.")
                        pcm = decode_mulaw(data)
                        level = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
                        voice = level > 550
                        if voice:
                            voiced_frames += 1
                            quiet_frames = 0
                            if speaking and voiced_frames >= 3:
                                if pending_approval:
                                    pending_approval["heard"] = False
                                    pending_approval["mark"] = None
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
                    elif not claimed_key and event.get("event") != "connected":
                        raise PermissionError("Media session has not started.")
        except (TimeoutError, ValueError, PermissionError, TypeError, KeyError, AttributeError):
            with contextlib.suppress(Exception):
                await websocket.close(code=1008)
        finally:
            self.sockets.discard(websocket)
            if answer:
                answer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await answer
            if claimed_key:
                self.active.discard(claimed_key)
                await self.db.execute(
                    "UPDATE calls SET state='completed',ended_at=? WHERE id=? AND state='connected'",
                    (now(), claimed_key),
                )

    def router(self):
        router = APIRouter()

        async def signed_form(request):
            if len(await request.body()) > 16384:
                raise PermissionError("Request is too large.")
            form = await request.form(max_files=0, max_fields=64, max_part_size=16384)
            if len(form.multi_items()) != len(form):
                raise PermissionError("Duplicate webhook fields are not allowed.")
            if len(request.query_params.multi_items()) != len(request.query_params):
                raise PermissionError("Duplicate webhook parameters are not allowed.")
            params = dict(form)
            if not self.signed(
                request.url.path,
                request.url.query,
                webhook_signature(request.headers),
                params,
            ):
                raise PermissionError("Invalid telephony signature.")
            if (
                params.get("AccountSid", self.config.settings.telephony_account_id)
                != self.config.settings.telephony_account_id
            ):
                raise PermissionError("Invalid telephony account.")
            return params

        @router.post("/telephony/voice")
        async def voice(request: Request):
            try:
                params = await signed_form(request)
            except PermissionError:
                return Response(status_code=403)
            if (
                not self.ready()[0]
                or self.config.settings.profile == "local_strict"
                or self.runtime.gateway.blocked
            ):
                return Response(status_code=403)
            settings = self.config.settings
            key = request.query_params.get("call_id")
            row = await self.db.fetchone("SELECT * FROM calls WHERE id=?", (key,)) if key else None
            sid = params.get("CallSid", "")
            result = VoiceResponse()
            if not re.fullmatch(r"CA[0-9a-fA-F]{32}", sid):
                return Response(status_code=403)
            if row is None:
                if (
                    key
                    or not settings.phone_inbound_enabled
                    or params.get("From") != settings.owner_phone_number
                    or params.get("Direction", "inbound") != "inbound"
                ):
                    if key:
                        result.hangup()
                    else:
                        result.reject()
                    return Response(str(result), media_type="text/xml")
                # Outbound hands-free mode must not authenticate spoofable inbound
                # caller ID. Without an inbound PIN there is no remote entry.
                if not re.fullmatch(r"[0-9]{6,8}", settings.secret("phone_pin")):
                    result.reject()
                    return Response(str(result), media_type="text/xml")
                async with self.lock:
                    row = await self.db.fetchone("SELECT * FROM calls WHERE provider_id=?", (sid,))
                    if row is None:
                        active = await self.db.fetchone(
                            "SELECT id FROM calls WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown') LIMIT 1"
                        )
                        if active:
                            result.reject(reason="busy")
                            return Response(str(result), media_type="text/xml")
                        try:
                            reserve = await self.reservation(inbound=True)
                        except ValueError:
                            result.reject(reason="busy")
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
            if row["direction"] == "inbound" and not settings.phone_inbound_enabled:
                result.hangup()
                return Response(str(result), media_type="text/xml")
            if row["state"] not in CALL_RANK or row["state"] == "unknown":
                result.hangup()
                return Response(str(result), media_type="text/xml")
            if row["provider_id"] and row["provider_id"] != sid:
                return Response(status_code=403)
            await self.db.execute("UPDATE calls SET provider_id=? WHERE id=?", (sid, key))
            if not row["auth_verified"] and not self.requires_pin(row["direction"]):
                # The owner has waived the PIN gate. The signed webhook, allowed
                # caller/recipient, Call SID and one-use media token still apply.
                await self.db.execute("UPDATE calls SET auth_verified=1 WHERE id=?", (key,))
                row["auth_verified"] = 1
            elif not row["auth_verified"]:
                digits = params.get("Digits", "")
                pin = settings.secret("phone_pin")
                if digits and pin and hmac.compare_digest(digits.encode(), pin.encode()):
                    await self.db.execute("UPDATE calls SET auth_verified=1 WHERE id=?", (key,))
                    row["auth_verified"] = 1
                elif row["attempts"] >= 3:
                    await self.db.execute(
                        "UPDATE calls SET state='failed',ended_at=? WHERE id=?", (now(), key)
                    )
                    result.hangup()
                    return Response(str(result), media_type="text/xml")
                else:
                    admitted = await self.db.execute(
                        "UPDATE calls SET attempts=attempts+1 WHERE id=? AND attempts<3 AND auth_verified=0",
                        (key,),
                    )
                    if not admitted:
                        result.hangup()
                        return Response(str(result), media_type="text/xml")
                    gather = Gather(
                        action_on_empty_result=True,
                        input="dtmf",
                        num_digits=len(pin),
                        timeout=8,
                        action=self.public_base_url.rstrip("/")
                        + "/telephony/voice?call_id="
                        + key,
                        method="POST",
                    )
                    italian = phone_language(settings).lower().startswith("it")
                    gather.say(
                        self.message("pin"),
                        language="it-IT" if italian else "en-GB",
                        voice="Polly.Giorgio" if italian else "Polly.Brian",
                    )
                    result.append(gather)
                    result.hangup()
                    return Response(str(result), media_type="text/xml")
            if key in self.active:
                result.hangup()
                return Response(str(result), media_type="text/xml")
            token = self.media_tokens.get(key) or secrets.token_urlsafe(32)
            self.media_tokens[key] = token
            self.prepare_voice(row)
            connect = Connect()
            stream = connect.stream(
                url=self.public_base_url.rstrip("/").replace("https://", "wss://", 1)
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
            # Reuse an already proxied webhook path; a signed probe has no call
            # fields and cannot create, end, or authorize a phone conversation.
            if set(params) == {"JarvisProbe"}:
                challenge = params["JarvisProbe"]
                if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", challenge):
                    return Response(status_code=400)
                return JSONResponse({"proof": self.probe_proof(challenge)})
            sid = params.get("CallSid")
            if not isinstance(sid, str) or not re.fullmatch(r"CA[0-9a-fA-F]{32}", sid):
                return Response(status_code=403)
            key = request.query_params.get("call_id")
            row = await self.db.fetchone(
                "SELECT * FROM calls WHERE id=? OR provider_id=? LIMIT 1", (key, sid)
            )
            if (
                row
                and row["state"] not in TERMINAL_CALL_STATES
                and (not row["provider_id"] or row["provider_id"] == sid)
            ):
                state = params.get("CallStatus", "unknown")
                await self.update_status(
                    row,
                    sid,
                    state,
                    reservation=self.settled_reservation(state, params.get("CallDuration")),
                )
            return Response(status_code=204)

        @router.websocket("/telephony/media")
        async def media(websocket: WebSocket):
            await self.media(websocket)

        return router
