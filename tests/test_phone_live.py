import asyncio
import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from test_agent_policy import model_factory
from test_live_voice import Connection, Context
from test_telephony_integrations import phone_config, signed

from jarvis.db import now
from jarvis.language import language_instructions
from jarvis.phone_live import PhoneLive
from jarvis.telephony import encode_mulaw


def configure(runtime, **changes):
    phone_config(runtime.config)
    runtime.config.update(
        {
            "desktop_voice_provider": "openai_live",
            "desktop_voice_api_key": "desktop-voice-test-key",
            "desktop_voice_name": "voice_saved_desktop_test",
            "desktop_voice_style": "Native standard Italian, warm and conversational.",
            "desktop_voice_max_session_seconds": 15,
            "phone_max_call_seconds": 60,
            **changes,
        }
    )


async def call_row(runtime, *, authenticated=True):
    await runtime.db.execute(
        "INSERT INTO calls(id,event_key,direction,state,provider_id,auth_verified,detail,created_at) "
        "VALUES('call','test','outbound','answered',?,?,'Test call requested by the owner',?)",
        ("CA" + "c" * 32, int(authenticated), now()),
    )
    runtime.telephony.media_tokens["call"] = "one-use-test-token"
    return await runtime.db.fetchone("SELECT * FROM calls WHERE id='call'")


class PhoneSocket:
    def __init__(self, runtime):
        self.runtime = runtime
        self.url = SimpleNamespace(path="/telephony/media", query="")
        self.headers = {
            "x-twilio-signature": signed(runtime.config, "/telephony/media", {})[
                "X-Twilio-Signature"
            ]
        }
        self.events = []
        self.incoming = asyncio.Queue()
        self.marked = asyncio.Event()
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def close(self, **kwargs):
        self.closed = True

    async def send_json(self, event):
        self.events.append(event)
        if event["event"] == "mark":
            self.marked.set()

    async def iter_text(self):
        yield json.dumps(
            {
                "event": "start",
                "start": {
                    "streamSid": "MZtest",
                    "callSid": "CA" + "c" * 32,
                    "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                    "customParameters": {"call_id": "call", "token": "one-use-test-token"},
                },
            }
        )
        while True:
            event = await self.incoming.get()
            yield json.dumps(event)
            if event.get("event") == "stop":
                return


class PhoneConnection(Connection):
    def __init__(self, socket, *, delegate=True):
        super().__init__(delegate=delegate)
        self.socket = socket
        self.instructions = []
        self.session.instructions = SimpleNamespace(append=self.append_instructions)

    async def start(self, *, session):
        await super().start(session=session)
        await self.events.put(
            {
                "type": "session.output_audio.delta",
                "delta": base64.b64encode(b"\xfe" * 160).decode(),
            }
        )

    async def append_commentary(self, **update):
        await super().append_commentary(**update)
        if update.get("delegation_id"):
            await self.socket.incoming.put({"event": "stop"})

    async def append_instructions(self, **update):
        self.instructions.append(update)


def install_provider(monkeypatch, connection, captured):
    def construct(**kwargs):
        captured.update(kwargs)
        return Context(
            SimpleNamespace(live=SimpleNamespace(connect=lambda **kwargs: Context(connection)))
        )

    monkeypatch.setattr("jarvis.phone_live.AsyncOpenAI", construct)


@pytest.mark.parametrize("voice", ["cedar", "voice_saved_desktop_test"])
async def test_phone_inherits_desktop_voice_key_language_and_delegates(runtime, monkeypatch, voice):
    configure(runtime, desktop_voice_name=voice)
    await call_row(runtime)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    socket = PhoneSocket(runtime)
    connection, captured = PhoneConnection(socket), {}
    install_provider(monkeypatch, connection, captured)
    payload = base64.b64encode(b"\xff" * 160).decode()
    await socket.incoming.put({"event": "media", "media": {"payload": payload}})

    await asyncio.wait_for(runtime.telephony.media(socket), 5)

    assert captured["api_key"] == "desktop-voice-test-key"
    assert captured["base_url"] == "https://api.openai.com/v1"
    session = connection.configuration
    assert session["model"] == runtime.config.settings.desktop_voice_model
    assert session["audio"] == {
        "format": {"type": "audio/pcmu", "rate": 8000},
        "output": {"voice": {"id": voice} if voice.startswith("voice_") else voice},
    }
    assert runtime.config.settings.desktop_voice_style in session["instructions"]
    assert language_instructions("auto", "it-IT") in session["instructions"]
    assert session["store"] is False and session["delegation"] == {"type": "client"}
    assert "it-IT" in session["input"][0]["content"][0]["text"]
    assert "Sono Jarvis" in connection.commentary[0]["content"]
    assert "123456" not in json.dumps(session)
    assert connection.audio == [payload]
    assert any(event["event"] == "media" for event in socket.events)
    tasks = await runtime.db.fetchall("SELECT * FROM tasks")
    assert len(tasks) == 1 and tasks[0]["state"] == "succeeded"
    assert tasks[0]["channel"] == "phone"
    usage = await runtime.db.fetchone("SELECT * FROM model_usage")
    assert usage["state"] == "complete"
    assert usage["reservation_usd"] == pytest.approx(75 * 0.05 / 60)
    assert usage["actual_usd"] == pytest.approx(2 * 0.05 / 60)
    assert socket.closed and not runtime.telephony.active


def test_phone_reuses_desktop_key_without_requiring_legacy_audio_key(config, monkeypatch):
    from jarvis.runtime import Runtime

    phone_config(config)
    config.update(
        {
            "desktop_voice_provider": "openai_live",
            "cloud_api_key": "existing-openai-provider-key",
            "phone_api_key": "",
            "phone_stt_provider": "faster_whisper",
        }
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert Runtime(config).telephony.ready() == (True, [])
    config.update(
        {"cloud_provider": "openai_compatible", "cloud_base_url": "https://gateway.example.com/v1"}
    )
    assert "desktop_voice_api_key" in Runtime(config).telephony.ready()[1]


async def test_phone_never_connects_to_live_before_pin_verification(runtime, monkeypatch):
    configure(runtime)
    await call_row(runtime, authenticated=False)

    def forbidden(**kwargs):
        raise AssertionError("No audio provider connection before PIN verification")

    monkeypatch.setattr("jarvis.phone_live.AsyncOpenAI", forbidden)
    socket = PhoneSocket(runtime)
    await asyncio.wait_for(runtime.telephony.media(socket), 2)
    assert socket.closed and not socket.events
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_phone_reserves_budget_before_live_connection(runtime, monkeypatch):
    configure(runtime, monthly_budget_usd=0.001)
    await call_row(runtime)
    connected = []

    def forbidden(**kwargs):
        connected.append(True)
        raise AssertionError("No provider connection after budget exhaustion")

    monkeypatch.setattr("jarvis.phone_live.AsyncOpenAI", forbidden)
    await asyncio.wait_for(runtime.telephony.media(PhoneSocket(runtime)), 2)
    assert not connected
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_phone_audio_waits_for_live_startup(runtime):
    configure(runtime)
    row = await call_row(runtime)
    runtime.telephony.active.add("call")
    socket = PhoneSocket(runtime)
    connection = PhoneConnection(socket, delegate=False)
    session = PhoneLive(runtime.telephony, socket, row, "MZtest", None, "personal")
    payload = base64.b64encode(b"\xff" * 160).decode()

    async def events():
        yield json.dumps({"event": "media", "media": {"payload": payload}})
        yield json.dumps({"event": "stop"})

    sender = asyncio.create_task(session.receive_phone(connection, events()))
    try:
        await asyncio.sleep(0.01)
        assert connection.audio == []
        session.started.set()
        await asyncio.wait_for(sender, 1)
        assert connection.audio == [payload]
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        runtime.telephony.active.discard("call")


async def test_phone_privacy_change_stops_input_before_next_provider_append(runtime):
    configure(runtime)
    row = await call_row(runtime)
    runtime.telephony.active.add("call")
    connection = PhoneConnection(PhoneSocket(runtime), delegate=False)
    session = PhoneLive(runtime.telephony, connection.socket, row, "MZtest", None, "personal")
    session.started.set()

    async def events():
        await runtime.set_voice_session(True, "personal")
        yield json.dumps({"event": "media", "media": {"payload": "/w=="}})

    try:
        with pytest.raises(PermissionError):
            await session.receive_phone(connection, events())
        assert connection.audio == []
    finally:
        runtime.telephony.active.discard("call")


async def test_phone_interruption_invalidates_unheard_approval_mark(runtime, monkeypatch):
    configure(runtime)
    row = await call_row(runtime)
    runtime.telephony.active.add("call")
    socket = PhoneSocket(runtime)
    connection = PhoneConnection(socket, delegate=False)
    session = PhoneLive(runtime.telephony, socket, row, "MZtest", None, "personal")
    session.started.set()
    session.last_speech = time.monotonic()
    session.pending = {"id": "proposal", "heard": False, "mark": "interrupted-mark"}
    decide = AsyncMock()
    monkeypatch.setattr(runtime.gateway, "decide", decide)
    payload = base64.b64encode(encode_mulaw(np.full(160, 10000, dtype="<i2"))).decode()

    async def events():
        for _ in range(3):
            yield json.dumps({"event": "media", "media": {"payload": payload}})
        yield json.dumps({"event": "mark", "mark": {"name": "interrupted-mark"}})
        yield json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})
        yield json.dumps({"event": "stop"})

    try:
        await session.receive_phone(connection, events())
        assert any(event["event"] == "clear" for event in socket.events)
        assert session.pending["heard"] is False
        decide.assert_not_awaited()
    finally:
        runtime.telephony.active.discard("call")


async def test_live_phone_dtmf_requires_exact_readback_and_playback_ack(runtime, monkeypatch):
    configure(runtime)
    row = await call_row(runtime)
    runtime.telephony.active.add("call")
    socket = PhoneSocket(runtime)
    connection = PhoneConnection(socket, delegate=False)
    session = PhoneLive(runtime.telephony, socket, row, "MZtest", None, "personal")
    session.pending = {
        "id": "proposal",
        "task_id": "task",
        "expires_at": "9999",
        "expected": "workspacecommandcommandechoapproved",
        "transcript": "",
        "audio_end": None,
        "mark": None,
        "heard": False,
    }
    decide, resume = AsyncMock(return_value="task"), AsyncMock()
    monkeypatch.setattr(runtime.gateway, "decide", decide)
    monkeypatch.setattr(runtime.tasks, "resume", resume)
    monkeypatch.setattr(session, "wait_task", AsyncMock())
    session.started.set()
    reader = asyncio.create_task(session.receive_provider(connection))

    async def events():
        yield json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})
        decide.assert_not_awaited()
        await connection.events.put(
            {
                "type": "session.output_transcript.delta",
                "delta": "Approve something else",
                "start_ms": 0,
                "end_ms": 100,
            }
        )
        await connection.events.put(
            {
                "type": "session.output_audio.delta",
                "delta": base64.b64encode(b"\xff" * 8000).decode(),
            }
        )
        await asyncio.sleep(0)
        assert not socket.marked.is_set()
        yield json.dumps({"event": "mark", "mark": {"name": "unknown-mark"}})
        yield json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})
        decide.assert_not_awaited()
        await connection.events.put(
            {
                "type": "session.output_transcript.delta",
                "delta": ' workspace_command {"command":"echo approved"}',
                "start_ms": 100,
                "end_ms": 200,
            }
        )
        await asyncio.wait_for(socket.marked.wait(), 2)
        yield json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})
        decide.assert_not_awaited()
        mark = next(event["mark"] for event in socket.events if event["event"] == "mark")
        yield json.dumps({"event": "mark", "mark": mark})
        yield json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})
        decide.assert_awaited_once_with("proposal", True)
        yield json.dumps({"event": "stop"})

    try:
        await asyncio.wait_for(session.receive_phone(connection, events()), 3)
        resume.assert_awaited_once_with("task")
    finally:
        reader.cancel()
        await asyncio.gather(reader, *session.jobs, return_exceptions=True)
        runtime.telephony.active.discard("call")
