import asyncio
import base64
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastmcp.client.auth import OAuth
from test_remote_core import enroll
from test_remote_core import server as remote_server

from jarvis.backup import backup, restore
from jarvis.document_service import serve, worker_request
from jarvis.integrations import oauth_store
from jarvis.platforms import ServiceLock
from jarvis.remote_audio import audio_key, validated_audio
from jarvis.remote_context import active_client
from jarvis.remote_protocol import digest
from jarvis.remote_push import signed_jwt
from jarvis.remote_store import RemoteStore


async def test_offline_queue_cancel_and_exact_job_never_replays(server):
    from jarvis.policy import TaskContext

    app, http = server
    remote = app.state.runtime.remote
    credentials, _ = await enroll(app, http, kind="executor")
    device = credentials["device_id"]
    caps = {"workspaces": [{"id": "project", "scope": "personal", "read": True}]}
    await remote.store.execute(
        "UPDATE devices SET capabilities=? WHERE id=?", (json.dumps(caps), device)
    )
    arguments = {"workspace": "project", "path": "file.txt"}
    context = TaskContext("synthetic-task", "Read my file", "cloud", "personal")
    with pytest.raises(ValueError, match="offline"):
        await remote.jobs.submit(device, "workspace_read", arguments, scope="personal", ctx=context)
    task = asyncio.create_task(
        remote.jobs.submit(
            device,
            "workspace_read",
            arguments,
            scope="personal",
            ctx=context,
            queue_if_offline=True,
        )
    )
    try:
        for _ in range(100):
            row = await remote.store.fetchone(
                "SELECT * FROM executor_jobs WHERE device_id=?", (device,)
            )
            if row:
                break
            await asyncio.sleep(0.005)
        assert row["state"] == "queued"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert (
        await remote.store.fetchone("SELECT state FROM executor_jobs WHERE id=?", (row["id"],))
    )["state"] == "cancelled"
    with pytest.raises(ValueError, match="cancelled"):
        await remote.jobs.submit(
            device,
            "workspace_read",
            arguments,
            scope="personal",
            ctx=context,
            queue_if_offline=True,
        )
    context.private = True
    with pytest.raises(ValueError, match="private operations cannot be queued"):
        await remote.jobs.submit(
            device,
            "workspace_read",
            arguments,
            scope="personal",
            ctx=context,
            queue_if_offline=True,
        )


async def test_server_restart_marks_delivered_jobs_unknown(tmp_path):
    store = RemoteStore(tmp_path)
    await store.open()
    await store.execute(
        "INSERT INTO executor_jobs(id,device_id,operation,arguments,argument_hash,state,created,expires,updated) VALUES('receipt-lost','executor','workspace_write','encrypted','hash','delivered',?,?,?)",
        (time.time(), time.time() + 60, time.time()),
    )
    await store.close()
    await store.open(recover_jobs=True)
    try:
        assert (await store.fetchone("SELECT state FROM executor_jobs WHERE id='receipt-lost'"))[
            "state"
        ] == "unknown"
    finally:
        await store.close()


async def test_remote_chat_approval_and_resume_use_real_agent(server):
    from test_agent_policy import model_factory

    app, http = server
    runtime = app.state.runtime
    _, headers = await enroll(app, http)
    runtime.tasks.model = model_factory("activity_save", {"title": "Synthetic approved activity"})
    response = await http.post(
        "/api/chat", headers=headers, json={"text": "Create my synthetic activity"}
    )
    assert response.status_code == 202, response.text
    key = response.json()["id"]
    await runtime.tasks.running[key]
    task = await runtime.db.fetchone("SELECT state FROM tasks WHERE id=?", (key,))
    assert task["state"] == "waiting_user"
    assert (await runtime.organizer.listing("personal"))["activities"] == []
    approval = (await http.get("/api/approvals", headers=headers)).json()[0]
    assert (
        await http.post(
            "/api/approvals/" + approval["id"], headers=headers, json={"approved": True}
        )
    ).status_code == 200
    await runtime.tasks.running[key]
    assert (await runtime.db.fetchone("SELECT state FROM tasks WHERE id=?", (key,)))[
        "state"
    ] == "succeeded"
    assert (await runtime.organizer.listing("personal"))["activities"][0][
        "title"
    ] == "Synthetic approved activity"


async def test_memory_scope_source_handles_and_private_write_boundaries(server):
    app, http = server
    runtime = app.state.runtime
    _, headers = await enroll(app, http)
    runtime.config.update({"second_brain_url": "https://memory.example/mcp"})
    calls = []

    async def recalled(*args):
        return {"memories": [{"evidence": [{"source_id": "known-personal-source", "revision": 1}]}]}

    async def mcp_call(*args):
        calls.append(args)
        return {"text": "synthetic source"}

    runtime.memory.recall = recalled
    runtime.mcp.call = mcp_call
    assert (await http.get("/api/memory/source/guessed", headers=headers)).status_code == 403
    assert (
        await http.post(
            "/api/memory/recall", headers=headers, json={"text": "fixture", "scope": "personal"}
        )
    ).status_code == 200
    assert (
        await http.get("/api/memory/source/known-personal-source", headers=headers)
    ).status_code == 200
    await http.post("/api/voice/session", headers=headers, json={"scope": "work", "private": True})
    assert (
        await http.get("/api/memory/source/known-personal-source", headers=headers)
    ).status_code == 403
    assert (
        await http.post(
            "/api/memory/remember",
            headers=headers,
            json={"text": "must not persist", "scope": "work"},
        )
    ).status_code == 403
    assert not await runtime.db.fetchone("SELECT * FROM memory_outbox")
    assert len(calls) == 1


async def test_server_mcp_tokens_are_encrypted_and_stdio_is_never_started(server):
    app, http = server
    runtime = app.state.runtime
    _, owner = await enroll(app, http, owner=True)
    _, companion = await enroll(app, http)
    value = {
        "servers": {
            "fixture": {
                "url": "https://mcp.example/mcp",
                "auth": "bearer",
                "token": "synthetic-mcp-secret",
                "read_tools": ["read"],
            }
        }
    }
    assert (
        await http.put("/api/integrations/mcp/config", headers=companion, json=value)
    ).status_code == 403
    response = await http.put("/api/integrations/mcp/config", headers=owner, json=value)
    assert response.status_code == 200, response.text
    assert "synthetic-mcp-secret" not in runtime.config.settings.mcp_config_path.read_text()
    assert runtime.mcp.specs()["fixture"]["token"] == "synthetic-mcp-secret"
    changed = {"servers": {"fixture": {"url": "https://different.example/mcp"}}}
    assert (
        await http.put("/api/integrations/mcp/config", headers=owner, json=changed)
    ).status_code == 403
    with pytest.raises(PermissionError):
        runtime.mcp.allowed({"command": "/usr/bin/true"}, "cloud")
    command = {"servers": {"fixture": {"command": "/usr/bin/true", "url": ""}}}
    assert (
        await http.put("/api/integrations/mcp/config", headers=owner, json=command)
    ).status_code == 403


server = remote_server


def wav(*, rate=16000, seconds=0.25, channels=1):
    import wave

    data = io.BytesIO()
    with wave.open(data, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x00\x00" * int(rate * seconds) * channels)
    return base64.b64encode(data.getvalue()).decode()


@pytest.mark.parametrize(
    "content", ["not-base64", wav(rate=44100), wav(channels=2), wav(seconds=0.01), wav(seconds=61)]
)
def test_audio_rejects_before_any_provider_call(content):
    with pytest.raises(ValueError):
        validated_audio(content)


def test_audio_canonicalization_and_provider_key_boundary(config):
    data, seconds = validated_audio(wav())
    assert seconds == 0.25 and data.startswith(b"RIFF")
    config.update({"cloud_provider": "anthropic", "cloud_api_key": "synthetic-anthropic"})
    with pytest.raises(ValueError):
        audio_key(config.settings)
    config.update({"cloud_provider": "openai", "cloud_base_url": "https://other.example/v1"})
    with pytest.raises(ValueError):
        audio_key(config.settings)
    config.update({"desktop_voice_api_key": "synthetic-voice"})
    assert audio_key(config.settings) == "synthetic-voice"


async def test_transcription_uses_validated_audio_no_retry_and_budget(server, monkeypatch):
    app, http = server
    _, headers = await enroll(app, http)
    runtime = app.state.runtime
    runtime.config.update({"desktop_voice_api_key": "synthetic-voice"})
    calls = []

    class FixtureOpenAI:
        def __init__(self, **options):
            assert options["api_key"] == "synthetic-voice" and options["max_retries"] == 0
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.transcribe))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def transcribe(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="synthetic transcription")

    monkeypatch.setattr("openai.AsyncOpenAI", FixtureOpenAI)
    response = await http.post(
        "/remote/v1/voice/transcribe", headers=headers, json={"content": "bad"}
    )
    assert response.status_code == 400 and calls == []
    response = await http.post(
        "/remote/v1/voice/transcribe", headers=headers, json={"content": wav()}
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "synthetic transcription"
    assert len(calls) == 1 and calls[0]["file"][1].startswith(b"RIFF")
    runtime.gateway.blocked = True
    assert (
        await http.post("/remote/v1/voice/transcribe", headers=headers, json={"content": wav()})
    ).status_code == 403
    assert (
        await http.post("/remote/v1/voice/speak", headers=headers, json={"text": "do not send"})
    ).status_code == 403
    assert len(calls) == 1


def test_apns_signature_is_valid_raw_es256():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    jwt = signed_jwt({"alg": "ES256", "kid": "fixture"}, {"iss": "fixture", "iat": 1}, pem)
    header, payload, signature = jwt.split(".")
    raw = base64.urlsafe_b64decode(signature + "==")
    assert len(raw) == 64
    key.public_key().verify(
        encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:])),
        (header + "." + payload).encode(),
        ec.ECDSA(hashes.SHA256()),
    )


async def test_push_registration_is_device_bound_encrypted_and_generic(server):
    app, http = server
    device, headers = await enroll(app, http)
    token = "ab" * 32
    assert (
        await http.post(
            "/remote/v1/push", headers=headers, json={"platform": "android", "token": token}
        )
    ).status_code == 400
    result = await http.post(
        "/remote/v1/push", headers=headers, json={"platform": "ios", "token": token}
    )
    assert result.status_code == 200 and result.json()["provider_configured"] is False
    push = app.state.runtime.remote.push
    row = await push.store.fetchone(
        "SELECT * FROM push_devices WHERE device_id=?", (device["device_id"],)
    )
    assert token not in row["token"] and push.store.decrypt(row["token"]) == token
    sent = []

    async def authorization(*args):
        return "synthetic-jwt"

    push.authorization = authorization

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as provider:
        assert await push.send({**row, "event_id": "fixture-event"}, provider) == "sent"
    assert sent == [
        {
            "aps": {
                "alert": {"title": "Jarvis", "body": "Hai un aggiornamento."},
                "sound": "default",
            },
            "event_id": "fixture-event",
        }
    ]
    await push.enqueue("fixture-event")
    assert await push.store.fetchone(
        "SELECT id FROM push_outbox WHERE device_id=?", (device["device_id"],)
    )
    await push.store.revoke(device["device_id"])
    assert not await push.store.fetchone(
        "SELECT * FROM push_devices WHERE device_id=?", (device["device_id"],)
    )


async def test_oauth_uses_sdk_handlers_public_callback_and_device_binding(server, tmp_path):
    app, http = server
    owner, headers = await enroll(app, http, owner=True)
    _, other = await enroll(app, http, owner=True, name="Other")
    remote = app.state.runtime.remote
    client = await remote.context(
        await remote.store.authenticate(owner["access_token"]), owner["device_id"]
    )
    marker = active_client.set(client)
    try:
        auth = OAuth(
            "https://mcp.example/mcp",
            token_storage=oauth_store(tmp_path / "oauth"),
            client_id="https://jarvis.example/",
        )
        remote.oauth.bind(auth, "fixture", {}, interactive=True)
        assert (
            str(auth.context.client_metadata.redirect_uris[0])
            == "https://jarvis.example/oauth/mcp/fixture/callback"
        )
        await auth.context.redirect_handler(
            "https://mcp.example/authorize?state=synthetic-state&code_challenge=fixture"
        )
        assert len((await http.get("/remote/v1/authorizations", headers=headers)).json()) == 1
        assert (await http.get("/remote/v1/authorizations", headers=other)).json() == []
        assert (
            await http.get("/oauth/mcp/fixture/callback?state=wrong&code=fixture")
        ).status_code == 403
        callback = await http.get(
            "/oauth/mcp/fixture/callback?state=synthetic-state&code=fixture&iss=https://mcp.example"
        )
        assert callback.status_code == 200
        result = await auth.context.callback_handler()
        assert (
            result.code == "fixture"
            and result.state == "synthetic-state"
            and result.iss == "https://mcp.example"
        )
        assert (
            await http.get("/oauth/mcp/fixture/callback?state=synthetic-state&code=fixture")
        ).status_code == 403
    finally:
        active_client.reset(marker)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="The isolated document server deploys on Linux with a Unix socket",
)
async def test_isolated_worker_real_subprocess_and_protocol_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CLOUD_API_KEY", "synthetic-never-in-worker")
    spawn = asyncio.create_subprocess_exec
    environments = []

    async def launch(*arguments, **kwargs):
        environments.append(kwargs["env"])
        assert "JARVIS_CLOUD_API_KEY" not in kwargs["env"]
        return await spawn(*arguments, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    scratch = tempfile.TemporaryDirectory(prefix="jarvis-worker-", dir="/tmp")
    socket = Path(scratch.name) / "parser.sock"
    task = asyncio.create_task(serve(str(socket)))
    try:
        for _ in range(100):
            if socket.exists():
                break
            await asyncio.sleep(0.01)
        assert await worker_request(str(socket), {"health": True}) == {"status": "ok"}
        value = await worker_request(
            str(socket),
            {"name": "fixture.txt", "content": base64.b64encode(b"chosen source text").decode()},
        )
        assert value["parts"][0]["text"] == "chosen source text"
        assert len(environments) == 1
        with pytest.raises(ValueError):
            await worker_request(
                str(socket), {"name": "bad.exe", "content": "AAAA", "command": "forbidden"}
            )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        scratch.cleanup()


@pytest.fixture
def age_identity(tmp_path):
    if not shutil.which("age") or not shutil.which("age-keygen"):
        pytest.skip("age tools are required for the real encryption round trip")
    identity = tmp_path / "identity.txt"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    recipient = subprocess.check_output(["age-keygen", "-y", str(identity)], text=True).strip()
    return identity, recipient


def test_encrypted_backup_restore_and_active_core_lock(tmp_path, age_identity):
    identity, recipient = age_identity
    data = tmp_path / "core"
    data.mkdir()
    with sqlite3.connect(data / "jarvis.sqlite3") as conn:
        conn.execute("CREATE TABLE fixture(value TEXT)")
        conn.execute("INSERT INTO fixture VALUES('synthetic-private-text')")
    (data / "server-secret.key").write_text("synthetic-master-key")
    archive = tmp_path / "backup.age"
    lock = ServiceLock(data / "service.lock")
    try:
        with pytest.raises((RuntimeError, OSError)):
            backup(data, archive, recipient)
    finally:
        lock.close()
    backup(data, archive, recipient)
    assert b"synthetic" not in archive.read_bytes()
    destination = tmp_path / "restored"
    restore(archive, destination, identity)
    assert (destination / "server-secret.key").read_text() == "synthetic-master-key"
    with sqlite3.connect(destination / "jarvis.sqlite3") as conn:
        assert conn.execute("SELECT value FROM fixture").fetchone()[0] == "synthetic-private-text"
    with pytest.raises(ValueError):
        restore(archive, destination, identity)
    damaged = tmp_path / "damaged.age"
    damaged.write_bytes(archive.read_bytes()[:-30])
    with pytest.raises((ValueError, tarfile.TarError, EOFError)):
        restore(damaged, tmp_path / "invalid", identity)
    assert not (tmp_path / "invalid").exists()


def test_restore_rejects_authenticated_archive_traversal(tmp_path, age_identity):
    identity, recipient = age_identity
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        entry = tarfile.TarInfo("../escaped.txt")
        entry.size = 4
        tar.addfile(entry, io.BytesIO(b"evil"))
    archive = tmp_path / "unsafe.age"
    encrypted = subprocess.run(
        ["age", "-r", recipient], input=raw.getvalue(), capture_output=True, check=True
    )
    archive.write_bytes(encrypted.stdout)
    with pytest.raises(ValueError, match="unsafe"):
        restore(archive, tmp_path / "restore", identity)
    assert not (tmp_path / "escaped.txt").exists()


async def test_restore_revokes_historical_credentials_and_freezes_schedules(tmp_path, age_identity):
    identity, recipient = age_identity
    data = tmp_path / "core"
    store = RemoteStore(data)
    await store.open()
    credentials = await store.enroll(
        await store.pairing_code(owner=True), "Synthetic device", "android"
    )
    await store.close()
    with sqlite3.connect(data / "jarvis.sqlite3") as database:
        database.executescript(
            "CREATE TABLE controls(name TEXT PRIMARY KEY,value TEXT); CREATE TABLE schedules(id TEXT,enabled INTEGER); INSERT INTO schedules VALUES('routine',1)"
        )
    archive, destination = tmp_path / "backup.age", tmp_path / "restored"
    await asyncio.to_thread(backup, data, archive, recipient)
    await asyncio.to_thread(restore, archive, destination, identity)
    with sqlite3.connect(destination / "jarvis.sqlite3") as database:
        assert (
            database.execute("SELECT value FROM controls WHERE name='emergency_stop'").fetchone()[0]
            == "1"
        )
        assert database.execute("SELECT enabled FROM schedules").fetchone()[0] == 0
    restored = RemoteStore(destination)
    await restored.open()
    try:
        with pytest.raises(PermissionError):
            await restored.authenticate(credentials["access_token"])
        with pytest.raises(PermissionError):
            await restored.refresh(credentials["refresh_token"])
    finally:
        await restored.close()


async def test_native_selection_and_large_receipt_never_persist_image(server):
    app, http = server
    remote = app.state.runtime.remote
    first, headers = await enroll(app, http)
    worker, executor_headers = await enroll(app, http, kind="executor")
    client = await remote.context(
        await remote.store.authenticate(first["access_token"]), first["device_id"]
    )
    marker = active_client.set(client)
    try:
        key = worker["device_id"]
        caps = {
            "native": ["screen.capture"],
            "native_scope": "personal",
            "locked": False,
            "workspaces": [],
        }
        remote.capabilities[key] = caps
        remote.capability_seen[key] = time.monotonic()
        remote.connections[key] = SimpleNamespace()
        assert remote.native_device() == key and remote.native_status()["locked"] is False
        remote.capabilities["second"] = caps
        remote.capability_seen["second"] = time.monotonic()
        remote.connections["second"] = SimpleNamespace()
        assert remote.native_device() is None
        response = await http.post(
            "/remote/v1/session/executor", headers=headers, json={"device_id": key}
        )
        assert response.status_code == 200
        assert remote.native_device() == key
        argument_hash = digest([key, "screen.capture", {}])
        await remote.store.execute(
            "INSERT INTO executor_jobs(id,device_id,operation,arguments,argument_hash,private,state,created,expires,updated) VALUES('large',?,'screen.capture','',?,1,'claimed',?,?,?)",
            (key, argument_hash, time.time(), time.time() + 30, time.time()),
        )
        remote.private_jobs["large"] = {}
        receipt = {
            "type": "result",
            "id": "large",
            "argument_hash": argument_hash,
            "state": "succeeded",
            "result": {"image": "synthetic-image" * 10000},
        }
        assert (
            await http.post("/remote/v1/executor-results/large", headers=headers, json=receipt)
        ).status_code == 403
        assert (
            await http.post(
                "/remote/v1/executor-results/large", headers=executor_headers, json=receipt
            )
        ).status_code == 200
        row = await remote.store.fetchone("SELECT * FROM executor_jobs WHERE id='large'")
        assert row["result"] == "" and row["state"] == "succeeded"
        assert remote.private_jobs["large"]["result"] == receipt["result"]
    finally:
        remote.connections.clear()
        active_client.reset(marker)
