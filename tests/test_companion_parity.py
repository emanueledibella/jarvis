import asyncio
import json
from uuid import uuid4

import pytest
from test_remote_core import enroll
from test_remote_core import server as remote_server

from jarvis.live_voice import LiveStart
from jarvis.remote_context import active_client
from jarvis.remote_voice import voice_socket

server = remote_server


async def test_shared_telephony_and_voice_settings_are_encrypted_revisioned_and_admin_only(server, config):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    _, companion = await enroll(app, http)
    snapshot = (await http.get("/api/settings", headers=owner)).json()
    assert snapshot["values"]["response_personality"]["enabled"] is False
    personality = {
        "enabled": True, "humor": 0, "irony": 65,
        "professionalism": 90, "warmth": 60, "conciseness": 100,
    }
    changes = {
        "telephony_account_id": "AC" + "1" * 32,
        "telephony_auth_token": "synthetic-companion-twilio-token",
        "telephony_from_number": "+390212345678",
        "owner_phone_number": "+393331234567",
        "phone_pin": "123456",
        "phone_inbound_enabled": True,
        "phone_pin_enabled": True,
        "phone_max_call_seconds": 120,
        "desktop_voice_provider": "openai_live",
        "desktop_voice_name": "cedar",
        "desktop_voice_style": "A calm voice",
        "response_personality": personality,
        "voice_enabled": True,
        "wake_enabled": True,
        "wake_phrase": "Jarvis",
        "followup_seconds": 6,
    }
    assert not set(changes) & set(snapshot["locked"])
    headers = {**owner, "If-Match": '"' + snapshot["revision"] + '"'}
    saved = await http.patch("/api/settings", headers=headers, json=changes)
    assert saved.status_code == 200, saved.text
    assert config.settings.secret("telephony_auth_token") == changes["telephony_auth_token"]
    assert config.settings.voice_enabled and config.settings.wake_enabled
    assert saved.json()["values"]["response_personality"] == personality
    assert config.load().response_personality.model_dump() == personality
    assert changes["telephony_auth_token"] not in config.path.read_text()
    assert saved.json()["values"]["telephony_auth_token"] == ""
    assert saved.json()["values"]["telephony_auth_token_configured"] is True
    assert saved.json()["values"]["phone_pin"] == ""
    assert (await http.patch("/api/settings", headers=headers, json={"wake_phrase": "Other"})).status_code == 409
    assert config.settings.wake_phrase == "Jarvis"
    for endpoint in ("/api/telephony/start", "/api/telephony/stop"):
        assert (await http.post(endpoint, headers=companion)).status_code == 403
    assert (await http.patch("/api/settings", headers=companion, json=changes)).status_code == 403
    read_only = (await http.get("/api/settings", headers=companion)).json()
    assert set(changes) <= set(read_only["locked"])
    current = (await http.get("/api/settings", headers=owner)).json()
    current_headers = {**owner, "If-Match": '"' + current["revision"] + '"'}
    for invalid in (-1, 101, 25.5, "30", True):
        rejected = await http.patch("/api/settings", headers=current_headers, json={
            "response_personality": {**personality, "humor": invalid},
        })
        assert rejected.status_code == 422
    assert config.load().response_personality.model_dump() == personality
    assert {"workspace_roots", "command_execution", "profile", "microphone_device_uid"} <= set(current["locked"])
    assert (await http.patch("/api/settings", headers={**owner, "If-Match": '"' + current["revision"] + '"'}, json={"workspace_roots": ["/"]})).status_code == 403
    assert not app.state.runtime.telephony.active


class VoicePeer:
    def __init__(self, auth=None, metadata=None, *, origin="jarvis://app"):
        self.headers = {"host": "jarvis.example", "origin": origin}
        self.incoming = asyncio.Queue()
        self.sent = []
        self.accepted = False
        self.closed = False
        for message in (auth, metadata):
            if message is not None:
                self.incoming.put_nowait(json.dumps(message))

    async def accept(self):
        self.accepted = True

    async def close(self, code=None):
        self.closed = True

    async def receive_text(self):
        return await self.incoming.get()

    async def send_json(self, data):
        self.sent.append(data)


async def test_live_socket_authenticates_before_provider_and_binds_client_identity(server, config):
    app, http = server
    remote = app.state.runtime.remote
    credentials, _ = await enroll(app, http)
    executor, _ = await enroll(app, http, kind="executor")
    config.update({"desktop_voice_provider": "openai_live"})
    accepted = []

    async def serve(peer, metadata):
        accepted.append((active_client.get(), metadata))

    app.state.runtime.live_voice.serve = serve
    session_id = str(uuid4())
    metadata = LiveStart(profile="cloud", privacy_revision=0, client_device_id="forged", client_session_id="forged").model_dump()
    auth = {"type": "authenticate", "access_token": credentials["access_token"], "session_id": session_id}
    for peer in (
        VoicePeer(auth, metadata, origin="https://untrusted.example"),
        VoicePeer({**auth, "access_token": config.token}, metadata),
        VoicePeer({**auth, "access_token": executor["access_token"]}, metadata),
        VoicePeer({**auth, "type": "start"}, metadata),
        VoicePeer(auth, {**metadata, "scope": "work"}),
        VoicePeer(auth, {**metadata, "private": True}),
    ):
        await voice_socket(remote, peer)
        assert peer.closed and not accepted
    peer = VoicePeer(auth, metadata)
    await voice_socket(remote, peer)
    assert peer.accepted and peer.closed and len(accepted) == 1
    client, bound = accepted[0]
    assert client.device_id == credentials["device_id"]
    assert bound.client_device_id == credentials["device_id"]
    assert bound.client_session_id == session_id
    assert active_client.get() is None


@pytest.mark.parametrize("change", ["revocation", "privacy", "emergency"])
async def test_open_live_socket_stops_on_revocation_privacy_change_or_emergency(server, config, change):
    app, http = server
    runtime, remote = app.state.runtime, app.state.runtime.remote
    credentials, headers = await enroll(app, http)
    config.update({"desktop_voice_provider": "openai_live"})
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def serve(peer, metadata):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    runtime.live_voice.serve = serve
    peer = VoicePeer({"type": "authenticate", "access_token": credentials["access_token"]}, LiveStart(profile="cloud", privacy_revision=0).model_dump())
    running = asyncio.create_task(voice_socket(remote, peer))
    await asyncio.wait_for(started.wait(), 2)
    if change == "revocation":
        await remote.revoke_device(credentials["device_id"])
    elif change == "privacy":
        assert (await http.post("/api/voice/session", headers=headers, json={"scope": "work", "private": True})).status_code == 200
    else:
        runtime.gateway.blocked = True
    await asyncio.wait_for(running, 2)
    assert cancelled.is_set() and peer.closed


async def test_live_handoff_cannot_cross_companion_devices_or_sessions():
    from jarvis.voice_context import VoiceContextStore

    store = VoiceContextStore()
    metadata = LiveStart(profile="cloud", privacy_revision=0, client_device_id="device-a", client_session_id="session-a")
    key, context = store.create(metadata, asyncio.Event())
    for changes in ({"client_device_id": "device-b"}, {"client_session_id": "session-b"}):
        with pytest.raises(PermissionError, match="boundary"):
            store.resume(key, metadata.model_copy(update=changes))
    assert not context.stop.is_set()
    store.clear()
