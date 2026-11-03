import asyncio
import base64
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from test_phone_live import PhoneConnection, PhoneSocket, call_row, configure, install_provider
from test_telephony_integrations import signed


async def webhook(runtime, endpoint, data, *, valid_signature=True):
    path = "/telephony/" + endpoint + "?call_id=call"
    app = FastAPI()
    app.include_router(runtime.telephony.router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(
            path,
            data=data,
            headers=signed(runtime.config, path, data) if valid_signature else {},
        )


async def prepare(runtime, monkeypatch, *, pin_enabled=False):
    configure(runtime, phone_pin_enabled=pin_enabled)
    await call_row(runtime, authenticated=False)
    socket = PhoneSocket(runtime)

    class AudibleConnection(PhoneConnection):
        async def start(self, *, session):
            await super().start(session=session)
            await self.events.put(
                {
                    "type": "session.output_audio.delta",
                    "delta": base64.b64encode(b"\x00" * 160).decode(),
                }
            )

    connection = AudibleConnection(socket, delegate=False)
    install_provider(monkeypatch, connection, {})
    return socket, connection


async def answered(runtime, **changes):
    return await webhook(
        runtime,
        "status",
        {
            "CallSid": "CA" + "c" * 32,
            "CallStatus": "in-progress",
            **changes,
        },
    )


async def test_voice_is_ready_before_media_and_reused_without_a_second_start(runtime, monkeypatch):
    socket, connection = await prepare(runtime, monkeypatch)
    timing_written = asyncio.Event()
    original_emit = runtime.db.emit

    async def emit(kind, *args, **kwargs):
        result = await original_emit(kind, *args, **kwargs)
        if kind == "call.voice_started":
            timing_written.set()
        return result

    monkeypatch.setattr(runtime.db, "emit", emit)
    start = AsyncMock(wraps=connection.session.start)
    connection.session.start = start
    assert (await answered(runtime)).status_code == 204
    voice = runtime.telephony.prepared_voice["call"]
    await asyncio.wait_for(voice.audio_ready.wait(), 1)
    assert voice.first_audio_at is not None and not socket.events
    assert not await runtime.db.fetchall("SELECT * FROM tasks")
    assert len(await runtime.db.fetchall("SELECT * FROM model_usage")) == 1
    assert (await answered(runtime)).status_code == 204
    assert runtime.telephony.prepared_voice["call"] is voice
    start.assert_awaited_once()

    output = asyncio.Event()
    original_send = socket.send_json

    async def send(event):
        await original_send(event)
        if event["event"] == "media":
            output.set()

    socket.send_json = send
    media = asyncio.create_task(runtime.telephony.media(socket))
    try:
        await asyncio.wait_for(output.wait(), 1)
        assert voice.first_audio_at <= voice.attached_at
        assert voice.prepare_timeout.when() is None
        await asyncio.wait_for(timing_written.wait(), 1)
    finally:
        await socket.incoming.put({"event": "stop"})
        await asyncio.wait_for(media, 2)
    start.assert_awaited_once()
    usage = await runtime.db.fetchall("SELECT * FROM model_usage")
    assert len(usage) == 1 and usage[0]["state"] == "complete"
    assert not runtime.telephony.prepared_voice and not runtime.telephony.active


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
async def test_required_pin_gates_preparation_until_verified(runtime, monkeypatch, direction):
    socket, connection = await prepare(runtime, monkeypatch, pin_enabled=True)
    await runtime.db.execute("UPDATE calls SET direction=?", (direction,))
    assert (await answered(runtime)).status_code == 204
    assert not runtime.telephony.prepared_voice and connection.configuration is None
    params = {"CallSid": "CA" + "c" * 32}
    response = await webhook(runtime, "voice", params)
    assert "<Gather" in response.text and "<Stream" not in response.text
    assert not runtime.telephony.prepared_voice and connection.configuration is None
    response = await webhook(runtime, "voice", {**params, "Digits": "123456"})
    assert "<Stream" in response.text
    voice = runtime.telephony.prepared_voice["call"]
    await asyncio.wait_for(voice.started.wait(), 1)
    assert not socket.events
    await runtime.telephony.close_prepared_voice("call")
    assert not runtime.telephony.prepared_voice


@pytest.mark.parametrize(
    "reason", ["completed", "timeout", "privacy", "pin", "profile", "shutdown"]
)
async def test_unused_preparation_closes_and_accounts_usage(runtime, monkeypatch, reason):
    socket, connection = await prepare(runtime, monkeypatch)
    if reason == "timeout":
        monkeypatch.setattr("jarvis.phone_live.PREPARE_TIMEOUT_SECONDS", 0.05)
    await answered(runtime)
    voice = runtime.telephony.prepared_voice["call"]
    await asyncio.wait_for(voice.started.wait(), 1)
    if reason == "completed":
        await answered(runtime, CallStatus="completed", CallDuration="1")
    elif reason == "privacy":
        runtime.voice_session["revision"] += 1
    elif reason == "pin":
        runtime.config.update({"phone_pin_enabled": True})
    elif reason == "profile":
        runtime.config.update({"profile": "local_strict"})
    elif reason == "shutdown":
        await runtime.telephony.stop_all()
    await asyncio.wait_for(asyncio.gather(voice.job, return_exceptions=True), 2)
    assert not runtime.telephony.prepared_voice
    assert not socket.events
    assert all(base64.b64decode(frame) == b"\xff" * 160 for frame in connection.audio)
    usage = await runtime.db.fetchall("SELECT state FROM model_usage")
    assert usage == [{"state": "complete"}]


async def test_failed_preparation_falls_back_to_normal_startup(runtime, monkeypatch):
    socket, connection = await prepare(runtime, monkeypatch)
    original_start = connection.session.start
    connection.session.start = AsyncMock(side_effect=RuntimeError("synthetic startup failure"))
    await answered(runtime)
    voice = runtime.telephony.prepared_voice["call"]
    await asyncio.gather(voice.job, return_exceptions=True)
    assert not runtime.telephony.prepared_voice
    connection.session.start = original_start
    output = asyncio.Event()
    original_send = socket.send_json

    async def send(event):
        await original_send(event)
        output.set()

    socket.send_json = send
    media = asyncio.create_task(runtime.telephony.media(socket))
    try:
        await asyncio.wait_for(output.wait(), 1)
    finally:
        await socket.incoming.put({"event": "stop"})
        await asyncio.wait_for(media, 2)
    assert any(event["event"] == "media" for event in socket.events)
    usage = await runtime.db.fetchall("SELECT state FROM model_usage ORDER BY created_at")
    assert usage == [{"state": "unknown"}, {"state": "complete"}]


async def test_unsigned_or_mismatched_answer_cannot_prepare_voice(runtime, monkeypatch):
    socket, connection = await prepare(runtime, monkeypatch)
    data = {"CallSid": "CA" + "c" * 32, "CallStatus": "in-progress"}
    assert (await webhook(runtime, "status", data, valid_signature=False)).status_code == 403
    assert (await answered(runtime, CallSid="CA" + "d" * 32)).status_code == 204
    assert not runtime.telephony.prepared_voice and connection.configuration is None
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_preparation_discards_startup_silence_with_bounded_speech_lead_in(
    runtime, monkeypatch
):
    from test_live_voice import Connection

    socket, connection = await prepare(runtime, monkeypatch)

    async def start(*, session):
        await Connection.start(connection, session=session)
        for packet in [b"\xff" * 160] * 40 + [b"\x00" * 160]:
            await connection.events.put(
                {
                    "type": "session.output_audio.delta",
                    "delta": base64.b64encode(packet).decode(),
                }
            )

    connection.session.start = start
    await answered(runtime)
    voice = runtime.telephony.prepared_voice["call"]
    await asyncio.wait_for(voice.audio_ready.wait(), 1)
    assert not socket.events
    output = asyncio.Event()
    original_send = socket.send_json

    async def send(event):
        await original_send(event)
        output.set()

    socket.send_json = send
    media = asyncio.create_task(runtime.telephony.media(socket))
    try:
        await asyncio.wait_for(output.wait(), 1)
        packet = base64.b64decode(socket.events[0]["media"]["payload"])
        assert packet == b"\xff" * 800 + b"\x00" * 160
    finally:
        await socket.incoming.put({"event": "stop"})
        await asyncio.wait_for(media, 2)
