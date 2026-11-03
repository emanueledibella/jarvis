"""Explicit companion audio. Validate canonical PCM before any paid request."""

import base64
import io
import math
import wave

from fastapi import Request

from .db import uid


def validated_audio(content):
    if not isinstance(content, str) or len(content) > 2_600_000:
        raise ValueError("Record at most one minute of audio.")
    try:
        data = base64.b64decode(content, validate=True)
        with wave.open(io.BytesIO(data), "rb") as reader:
            if (
                reader.getnchannels(),
                reader.getsampwidth(),
                reader.getframerate(),
                reader.getcomptype(),
            ) != (1, 2, 16000, "NONE"):
                raise ValueError("Use mono PCM16 WAV at 16 kHz.")
            frames = reader.getnframes()
            if not 1600 <= frames <= 960000:
                raise ValueError("Record between 0.1 and 60 seconds.")
            pcm = reader.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError("Incomplete audio frames.")
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(pcm)
        return output.getvalue(), frames / 16000
    except (wave.Error, EOFError, TypeError, base64.binascii.Error):
        raise ValueError("Invalid audio recording.") from None


def audio_key(settings):
    key = settings.secret("desktop_voice_api_key")
    if (
        not key
        and settings.cloud_provider == "openai"
        and settings.cloud_base_url.rstrip("/") in {"", "https://api.openai.com/v1"}
    ):
        key = settings.secret("cloud_api_key")
    if not key:
        raise ValueError(
            "Configure a dedicated OpenAI voice key or an official OpenAI model key on the core."
        )
    return key


def install_audio(app, remote):
    runtime = remote.runtime

    @app.post("/remote/v1/voice/transcribe")
    async def transcribe(request: Request):
        if runtime.gateway.blocked:
            raise PermissionError("Emergency stop is active.")
        if "chat" not in request.state.remote_device["scopes"]:
            raise PermissionError("Voice requires the chat grant.")
        remote.limit("audio:" + request.state.remote_device["id"], 10)
        payload = await request.json()
        data, seconds = validated_audio(payload.get("content"))
        key = audio_key(runtime.config.settings)
        run_id, rate = uid(), remote.options.transcription_usd_per_minute
        await runtime.budget.reserve_voice(run_id, seconds, rate)
        if runtime.gateway.blocked:
            await runtime.budget.finish_voice(run_id, 0, rate)
            raise PermissionError("Emergency stop is active.")
        try:
            from openai import AsyncOpenAI, DefaultAsyncHttpxClient

            async with AsyncOpenAI(
                api_key=key,
                base_url="https://api.openai.com/v1",
                organization="",
                project="",
                max_retries=0,
                timeout=45,
                http_client=DefaultAsyncHttpxClient(trust_env=False),
            ) as client:
                result = await client.audio.transcriptions.create(
                    model=runtime.config.settings.phone_stt_model,
                    file=("request.wav", data, "audio/wav"),
                )
            await runtime.budget.finish_voice(run_id, seconds, rate)
            return {"text": result.text[:20000], "seconds": seconds}
        except Exception:
            await runtime.budget.finish_voice(run_id, None, rate)
            raise ValueError(
                "Voice transcription failed. Its budget reservation was retained; no automatic retry was made."
            ) from None

    @app.post("/remote/v1/voice/speak")
    async def speak(request: Request):
        if runtime.gateway.blocked:
            raise PermissionError("Emergency stop is active.")
        if "chat" not in request.state.remote_device["scopes"]:
            raise PermissionError("Voice requires the chat grant.")
        payload = await request.json()
        text = payload.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= 4000:
            raise ValueError("Read between one and 4000 characters.")
        remote.limit("speech:" + request.state.remote_device["id"], 10)
        key = audio_key(runtime.config.settings)
        run_id = uid()
        cost = len(text) * remote.options.tts_usd_per_million_characters / 1_000_000
        if not math.isfinite(cost):
            raise ValueError("Invalid voice rate.")
        await runtime.budget.reserve_voice(run_id, 60, cost)
        if runtime.gateway.blocked:
            await runtime.budget.finish_voice(run_id, 0, cost)
            raise PermissionError("Emergency stop is active.")
        try:
            from openai import AsyncOpenAI, DefaultAsyncHttpxClient

            async with AsyncOpenAI(
                api_key=key,
                base_url="https://api.openai.com/v1",
                organization="",
                project="",
                max_retries=0,
                timeout=45,
                http_client=DefaultAsyncHttpxClient(trust_env=False),
            ) as client:
                result = await client.audio.speech.create(
                    model=runtime.config.settings.phone_tts_model,
                    voice=runtime.config.settings.phone_tts_voice,
                    input=text,
                    response_format="mp3",
                )
                data = result.content
            if len(data) > 4_000_000:
                raise ValueError("Speech exceeds its size limit.")
            await runtime.budget.finish_voice(run_id, 60, cost)
            return {"content": base64.b64encode(data).decode(), "mime": "audio/mpeg"}
        except Exception:
            await runtime.budget.finish_voice(run_id, None, cost)
            raise ValueError("Speech generation failed; no automatic retry was made.") from None
