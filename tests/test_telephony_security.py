import asyncio
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from starlette.datastructures import Headers
from test_telephony_integrations import phone_config, signed

from jarvis.api import create_app
from jarvis.db import now


class Socket:
    def __init__(self, config, events):
        self.url = SimpleNamespace(path="/telephony/media", query="")
        self.headers = Headers(signed(config, self.url.path, {}))
        self.events = events
        self.accepted = self.closed = False

    async def accept(self):
        self.accepted = True

    async def close(self, **kwargs):
        self.closed = True

    async def send_json(self, event):
        pass

    async def iter_text(self):
        for event in self.events:
            yield json.dumps(event)


def start_event(config, **changes):
    return {
        "event": "start",
        "start": {
            "accountSid": config.settings.telephony_account_id,
            "callSid": "CA" + "a" * 32,
            "streamSid": "MZ" + "b" * 32,
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"call_id": "victim", "token": "wrong-token"},
            **changes,
        },
    }


@pytest.mark.parametrize("already_active", [False, True])
async def test_rejected_media_cannot_end_or_release_another_call(runtime, already_active):
    phone_config(runtime.config)
    await runtime.db.execute(
        "INSERT INTO calls(id,event_key,direction,state,provider_id,auth_verified,created_at) "
        "VALUES('victim','fixture','outbound','connected',?,1,?)",
        ("CA" + "a" * 32, now()),
    )
    runtime.telephony.media_tokens["victim"] = "real-token"
    if already_active:
        runtime.telephony.active.add("victim")
    socket = Socket(runtime.config, [start_event(runtime.config)])
    if already_active:
        socket.events[0]["start"]["customParameters"]["token"] = "real-token"
    await runtime.telephony.media(socket)
    row = await runtime.db.fetchone("SELECT state,ended_at FROM calls WHERE id='victim'")
    assert row == {"state": "connected", "ended_at": None}
    assert ("victim" in runtime.telephony.active) is already_active
    assert runtime.telephony.media_tokens["victim"] == "real-token"
    assert socket.closed
    runtime.telephony.active.clear()


@pytest.mark.parametrize(
    "event",
    [None, [], {"event": "start", "start": None}, {"event": "start", "start": {"mediaFormat": []}}],
)
async def test_malformed_media_is_closed_without_unhandled_errors(runtime, event):
    phone_config(runtime.config)
    socket = Socket(runtime.config, [event])
    await runtime.telephony.media(socket)
    assert socket.closed and not runtime.telephony.active
    assert not await runtime.db.fetchall("SELECT * FROM calls")


async def test_inbound_caller_id_is_insufficient_when_outbound_pin_is_disabled(config):
    phone_config(config)
    config.update({"phone_pin_enabled": False})
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        params = {"CallSid": "CA" + "c" * 32, "From": config.settings.owner_phone_number}
        path = "/telephony/voice"
        response = await client.post(path, data=params, headers=signed(config, path, params))
        assert response.status_code == 200 and "<Gather" in response.text
        assert "<Stream" not in response.text
        row = await app.state.runtime.db.fetchone("SELECT * FROM calls")
        assert row["auth_verified"] == 0
        path += "?call_id=" + row["id"]
        verified = {**params, "Digits": "123456"}
        response = await client.post(path, data=verified, headers=signed(config, path, verified))
        assert "<Stream" in response.text and "<Gather" not in response.text
        await app.state.runtime.db.execute("UPDATE calls SET state='completed'")


@pytest.mark.parametrize("variant", ["form", "query", "signature", "account"])
async def test_ambiguous_or_wrong_account_webhooks_are_rejected(config, variant):
    phone_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        params = {"CallSid": "CA" + "d" * 32, "From": config.settings.owner_phone_number}
        path = "/telephony/voice"
        if variant == "query":
            path += "?call_id=one&call_id=two"
        if variant == "account":
            params["AccountSid"] = "AC" + "9" * 32
        headers = {
            **signed(config, path, params),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = urlencode(
            [("CallSid", "CA" + "e" * 32), *params.items()] if variant == "form" else params
        )
        if variant == "signature":
            headers = [*headers.items(), ("X-Twilio-Signature", headers["X-Twilio-Signature"])]
        response = await client.post(path, content=payload, headers=headers)
        assert response.status_code == 403
        assert not await app.state.runtime.db.fetchall("SELECT * FROM calls")


async def test_media_account_must_match_before_claiming_a_call(runtime):
    phone_config(runtime.config)
    await runtime.db.execute(
        "INSERT INTO calls(id,event_key,direction,state,provider_id,auth_verified,created_at) "
        "VALUES('victim','fixture','outbound','answered',?,1,?)",
        ("CA" + "a" * 32, now()),
    )
    runtime.telephony.media_tokens["victim"] = "real-token"
    event = start_event(runtime.config, accountSid="AC" + "9" * 32)
    event["start"]["customParameters"]["token"] = "real-token"
    socket = Socket(runtime.config, [event])
    await runtime.telephony.media(socket)
    row = await runtime.db.fetchone("SELECT state,ended_at FROM calls WHERE id='victim'")
    assert row == {"state": "answered", "ended_at": None}
    assert runtime.telephony.media_tokens["victim"] == "real-token"
    assert socket.closed


async def test_missing_pin_never_opens_inbound_access_in_hands_free_mode(config):
    phone_config(config)
    config.update({"phone_pin_enabled": False, "phone_pin": ""})
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        params = {"CallSid": "CA" + "c" * 32, "From": config.settings.owner_phone_number}
        response = await client.post(
            "/telephony/voice", data=params, headers=signed(config, "/telephony/voice", params)
        )
        assert response.status_code == 403
        assert "<Stream" not in response.text
        assert not await app.state.runtime.db.fetchall("SELECT * FROM calls")


async def test_inbound_telephony_is_opt_in_and_rejects_before_answering(config):
    from jarvis.config import Settings

    assert Settings(_env_file=None).phone_inbound_enabled is False
    phone_config(config)
    config.update({"phone_inbound_enabled": False})
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        params = {"CallSid": "CA" + "c" * 32, "From": config.settings.owner_phone_number}
        response = await client.post(
            "/telephony/voice", data=params, headers=signed(config, "/telephony/voice", params)
        )
        assert response.status_code == 200 and "<Reject" in response.text
        assert "<Say" not in response.text and "<Hangup" not in response.text
        assert not await app.state.runtime.db.fetchall("SELECT * FROM calls")


async def test_unsigned_webhooks_are_rejected_without_reading_the_body():
    from jarvis.telephony_ingress import TelephonyIngress

    async def forbidden(*args):
        raise AssertionError("An unsigned webhook must not reach body reading or the application")

    sent = []

    async def send(event):
        sent.append(event)

    await TelephonyIngress(forbidden)(
        {"type": "http", "path": "/telephony/voice", "headers": []}, forbidden, send
    )
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 403


async def test_invalid_transport_signatures_cannot_reach_voice_provider_setup(config, monkeypatch):
    phone_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    phone = app.state.runtime.telephony

    def forbidden():
        raise AssertionError("Invalid signatures cannot trigger voice-provider/keychain setup")

    monkeypatch.setattr(phone, "ready", forbidden)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        headers = {"Host": "phone.example.com", "X-Twilio-Signature": "A" * 27 + "="}
        response = await client.post(
            "/telephony/voice", data={"CallSid": "CA" + "f" * 32}, headers=headers
        )
        assert response.status_code == 403
        socket = Socket(config, [])
        socket.headers = Headers(headers)
        await phone.media(socket)
        assert socket.closed and not socket.accepted


async def test_slow_public_webhooks_cannot_fill_the_private_api_admission(config):
    phone_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    ready, release = asyncio.Event(), asyncio.Event()
    waiting = 0

    async def body():
        nonlocal waiting
        waiting += 1
        if waiting == 8:
            ready.set()
        yield b"CallSid=fixture"
        await release.wait()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        headers = {
            "Host": "phone.example.com",
            "X-Twilio-Signature": "A" * 27 + "=",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        requests = [
            asyncio.create_task(client.post("/telephony/status", headers=headers, content=body()))
            for _ in range(8)
        ]
        try:
            await asyncio.wait_for(ready.wait(), 2)
            refused = await client.post("/telephony/status", headers=headers, content=b"")
            assert refused.status_code == 429
            private = await client.get(
                "/api/status", headers={"Authorization": "Bearer " + config.token}
            )
            assert private.status_code == 200
        finally:
            release.set()
            results = await asyncio.gather(*requests)
        assert all(result.status_code == 403 for result in results)


async def test_only_two_unclaimed_media_handshakes_can_wait(runtime):
    phone_config(runtime.config)
    release = asyncio.Event()

    class WaitingSocket(Socket):
        def __init__(self, config, events):
            super().__init__(config, events)
            self.began = asyncio.Event()

        async def accept(self):
            await super().accept()
            self.began.set()

        async def iter_text(self):
            await release.wait()
            for event in []:
                yield event

    sockets = [WaitingSocket(runtime.config, []) for _ in range(3)]
    running = [asyncio.create_task(runtime.telephony.media(socket)) for socket in sockets[:2]]
    try:
        await asyncio.wait_for(asyncio.gather(*(socket.began.wait() for socket in sockets[:2])), 2)
        await runtime.telephony.media(sockets[2])
        assert sockets[2].closed and not sockets[2].accepted
    finally:
        release.set()
        await asyncio.gather(*running)
    assert not runtime.telephony.sockets
