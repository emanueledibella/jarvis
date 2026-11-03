import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from jarvis.api import create_app
from jarvis.config import ConfigStore
from jarvis.remote import ServerOptions
from jarvis.remote_store import RemoteStore


@pytest.fixture
async def server(config):
    app = create_app(
        config,
        start_scheduler=False,
        process_lock=False,
        remote_options=ServerOptions(public_url="https://jarvis.example"),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://jarvis.example"
        ) as http:
            yield app, http


async def enroll(app, http, *, owner=False, kind="companion", name="Phone"):
    code = await app.state.runtime.remote.store.pairing_code(kind, owner=owner)
    response = await http.post(
        "/remote/v1/pair", json={"code": code, "name": name, "platform": "ios"}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    return result, {"Authorization": "Bearer " + result["access_token"]}


async def test_no_default_or_local_owner_credential(server, config):
    from jarvis.executor import server_url

    assert (
        ServerOptions(public_url="https://JARVIS.example:443/").public_url
        == "https://jarvis.example"
    )
    assert server_url("HTTPS://JARVIS.example:443/") == "https://jarvis.example"
    assert (
        ServerOptions(public_url="HTTPS://JARVIS.example:443/").public_url
        == "https://jarvis.example"
    )
    _, http = server
    assert (await http.get("/api/tasks")).status_code == 401
    assert (
        await http.get("/api/tasks", headers={"Authorization": "Bearer " + config.token})
    ).status_code == 401
    assert (await http.get("/health")).json()["service"] == "jarvis-remote"


async def test_explicit_device_revocation_cancels_its_accepted_work(server):
    app, http = server
    runtime = app.state.runtime
    phone, headers = await enroll(app, http)
    _, owner = await enroll(app, http, owner=True)
    started = asyncio.Event()

    async def wait_for_cancel(key, **kwargs):
        started.set()
        await asyncio.Event().wait()

    runtime.tasks.run = wait_for_cancel
    task = (
        await http.post("/api/chat", headers=headers, json={"text": "Synthetic pending work"})
    ).json()
    await started.wait()
    response = await http.post(
        "/remote/v1/devices/" + phone["device_id"] + "/revoke", headers=owner, json={}
    )
    assert response.status_code == 200
    assert (await runtime.db.fetchone("SELECT state FROM tasks WHERE id=?", (task["id"],)))[
        "state"
    ] == "cancelled"


async def test_authenticated_chat_limit_returns_429_before_creating_work(server):
    app, http = server
    device, headers = await enroll(app, http)
    for _ in range(20):
        app.state.runtime.remote.limit("chat:" + device["device_id"], 20)
    response = await http.post("/api/chat", headers=headers, json={"text": "Not accepted"})
    assert response.status_code == 429
    assert not await app.state.runtime.db.fetchone("SELECT id FROM tasks")


async def test_parallel_initial_requests_share_one_device_session(server):
    app, http = server
    _, headers = await enroll(app, http)
    key = str(uuid4())
    headers["X-Jarvis-Session"] = key
    replies = await asyncio.gather(
        *(http.get("/api/voice/session", headers=headers) for _ in range(12))
    )
    assert all(reply.status_code == 200 for reply in replies)
    assert all(reply.json()["client_session_id"] == key for reply in replies)
    row = await app.state.runtime.remote.store.fetchone(
        "SELECT COUNT(*) AS n FROM client_sessions WHERE id=?", (key,)
    )
    assert row["n"] == 1


async def test_pairing_single_use_and_rotation_replay_revokes_family(server):
    app, http = server
    code = await app.state.runtime.remote.store.pairing_code()
    body = {"code": code, "name": "Phone", "platform": "android"}
    first = await http.post("/remote/v1/pair", json=body)
    assert first.status_code == 200
    assert (await http.post("/remote/v1/pair", json=body)).status_code == 403
    old = first.json()["refresh_token"]
    fresh = await http.post("/remote/v1/refresh", json={"refresh_token": old})
    assert fresh.status_code == 200
    assert (await http.post("/remote/v1/refresh", json={"refresh_token": old})).status_code == 403
    assert (
        await http.get(
            "/api/status", headers={"Authorization": "Bearer " + fresh.json()["access_token"]}
        )
    ).status_code == 401


async def test_scopes_revocation_and_executor_separation(server):
    app, http = server
    device, headers = await enroll(app, http)
    assert (
        await http.patch("/api/settings", headers=headers, json={"cloud_model": "test"})
    ).status_code == 403
    assert (
        await http.post("/remote/v1/pairing-codes", headers=headers, json={})
    ).status_code == 403
    assert (
        await http.post("/api/models/test", headers=headers, json={"profile": "cloud"})
    ).status_code == 403
    _, owner = await enroll(app, http, owner=True)
    assert (
        await http.post("/api/models/test", headers=owner, json={"profile": "local_strict"})
    ).status_code == 403
    _, executor = await enroll(app, http, kind="executor")
    assert (await http.get("/api/tasks", headers=executor)).status_code == 403
    assert (
        await http.post(
            f"/remote/v1/devices/{device['device_id']}/revoke", headers=headers, json={}
        )
    ).status_code == 200
    assert (await http.get("/api/tasks", headers=headers)).status_code == 401


async def test_separate_device_privacy_and_scope(server):
    app, http = server
    _, phone = await enroll(app, http)
    desktop_device, desktop = await enroll(app, http, name="Desktop")
    response = await http.post(
        "/api/voice/session", headers=phone, json={"scope": "work", "private": True}
    )
    assert response.status_code == 200, response.text
    assert (await http.get("/api/voice/session", headers=desktop)).json() == {
        "scope": "personal",
        "private": False,
        "revision": 0,
        "executor_id": None,
        "client_session_id": desktop_device["device_id"],
    }
    assert app.state.runtime.voice_session["scope"] == "personal"
    assert (await http.get("/api/organizer?scope=work", headers=desktop)).status_code == 403


async def test_browser_refresh_cookie_origin_and_untrusted_origins(server):
    app, http = server
    code = await app.state.runtime.remote.store.pairing_code()
    response = await http.post(
        "/remote/v1/pair", json={"code": code, "name": "Browser", "platform": "web"}
    )
    assert "refresh_token" not in response.json()
    assert "httponly" in response.headers["set-cookie"].lower()
    assert (await http.post("/remote/v1/refresh", json={})).status_code == 403
    assert (
        await http.post("/remote/v1/refresh", headers={"Origin": "https://jarvis.example"}, json={})
    ).status_code == 200
    assert (
        await http.get("/health", headers={"Origin": "https://evil.example"})
    ).status_code == 403
    assert (await http.get("https://evil.example/health")).status_code == 400


async def test_server_secrets_encrypted_and_endpoint_binding(server, config):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    snapshot = await http.get("/api/settings", headers=owner)
    response = await http.patch(
        "/api/settings",
        headers={**owner, "If-Match": snapshot.headers["etag"]},
        json={"cloud_api_key": "synthetic-secret-not-real", "cloud_model": "fixture"},
    )
    assert response.status_code == 200, response.text
    assert "synthetic-secret-not-real" not in config.path.read_text()
    assert config.settings.secret("cloud_api_key") == "synthetic-secret-not-real"
    loaded = ConfigStore(env_file=config.env_file, data_dir=config.data_dir)
    assert loaded.settings.secret("cloud_api_key") == "synthetic-secret-not-real"
    assert (
        await http.patch(
            "/api/settings", headers=owner, json={"cloud_base_url": "https://other.example/v1"}
        )
    ).status_code == 403
    assert (
        await http.patch("/api/settings", headers=owner, json={"workspace_roots": ["/"]})
    ).status_code == 403
    assert config.settings.profile == "cloud"
    assert config.settings.workspace_roots == []


async def test_settings_require_current_revision_without_overwriting_newer_changes(server, config):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    snapshot = await http.get("/api/settings", headers=owner)
    revision = snapshot.json()["revision"]
    assert snapshot.headers["etag"] == '"' + revision + '"'
    assert (await http.patch(
        "/api/settings", headers=owner, json={"cloud_model": "must-not-save"}
    )).status_code == 409
    headers = {**owner, "If-Match": snapshot.headers["etag"]}
    saved = await http.patch("/api/settings", headers=headers, json={"cloud_model": "new-model"})
    assert saved.status_code == 200, saved.text
    stale = await http.patch("/api/settings", headers=headers, json={"cloud_model": "stale-model"})
    assert stale.status_code == 409
    assert config.settings.cloud_model == "new-model"
    current = await http.get("/api/settings", headers=owner)
    assert current.json()["revision"] != revision
    assert (await http.patch(
        "/api/settings", headers={**owner, "If-Match": current.headers["etag"]},
        json={"cloud_model": "reviewed-model"},
    )).status_code == 200
    assert config.settings.cloud_model == "reviewed-model"


async def test_concurrent_key_save_cannot_attach_it_to_previously_authorized_endpoint(
    server, config, monkeypatch
):
    app, http = server
    remote = app.state.runtime.remote
    _, owner = await enroll(app, http, owner=True)
    snapshot = await http.get("/api/settings", headers=owner)
    headers = {**owner, "If-Match": snapshot.headers["etag"]}
    original_endpoint = config.settings.cloud_base_url
    ready, release = asyncio.Event(), asyncio.Event()
    authorize = remote.authorize_object

    async def delayed_authorize(request, client):
        await authorize(request, client)
        if (request.method == "PATCH" and request.url.path == "/api/settings"
                and (await request.json()).get("cloud_base_url") == "https://raced.example/v1"):
            ready.set()
            await release.wait()

    monkeypatch.setattr(remote, "authorize_object", delayed_authorize)
    pending = asyncio.create_task(http.patch(
        "/api/settings", headers=headers, json={"cloud_base_url": "https://raced.example/v1"}
    ))
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
        saved = await http.patch(
            "/api/settings", headers=headers, json={"cloud_api_key": "synthetic-concurrency-key"}
        )
        assert saved.status_code == 200, saved.text
    finally:
        release.set()
    stale = await asyncio.wait_for(pending, timeout=5)
    assert stale.status_code == 409, stale.text
    assert config.settings.cloud_base_url == original_endpoint
    assert config.settings.secret("cloud_api_key") == "synthetic-concurrency-key"


async def test_expired_pair_code_and_no_secret_payloads(tmp_path):
    store = RemoteStore(tmp_path)
    await store.open()
    try:
        code = await store.pairing_code(ttl=-1)
        with pytest.raises(PermissionError):
            await store.enroll(code, "Phone", "ios")
        rows = await store.fetchall("SELECT * FROM pairing_codes")
        assert code not in json.dumps(rows)
    finally:
        await store.close()


def test_migrated_mac_keychain_references_can_be_reconfigured_on_the_server(config, monkeypatch):
    monkeypatch.setattr("jarvis.config.sys.platform", "linux")
    config.update({"cloud_api_key": "keychain:synthetic-unavailable-account"})
    with pytest.raises(ValueError, match="Keychain"):
        config.settings.secret("cloud_api_key")
    config.enable_server_mode()
    assert config.settings.secret("cloud_api_key") == ""
    public = config.settings.public()
    assert public["cloud_api_key"] == ""
    assert public["cloud_api_key_configured"] is False
    assert public["cloud_api_key_unavailable"] is True
    config.update({"cloud_api_key": "synthetic-server-key"})
    assert config.settings.secret("cloud_api_key") == "synthetic-server-key"


async def test_private_task_approval_events_and_attachments_do_not_cross_sessions(server):
    app, http = server
    runtime = app.state.runtime

    async def finish_without_provider(key, **kwargs):
        await runtime.db.execute("UPDATE tasks SET state='succeeded' WHERE id=?", (key,))

    runtime.tasks.run = finish_without_provider
    _, first = await enroll(app, http)
    _, second = await enroll(app, http)
    await http.post(
        "/api/voice/session", headers=first, json={"private": True, "scope": "personal"}
    )
    result = await http.post(
        "/api/chat", headers=first, json={"text": "private fixture content", "private": True}
    )
    assert result.status_code == 202, result.text
    key = result.json()["id"]
    assert any(row["id"] == key for row in (await http.get("/api/tasks", headers=first)).json())
    assert not any(
        row["id"] == key for row in (await http.get("/api/tasks", headers=second)).json()
    )
    assert (await http.get(f"/api/tasks/{key}/detail", headers=second)).status_code == 403
    await runtime.db.execute(
        "INSERT INTO approvals(id,task_id,tool,arguments,arguments_hash,state,created_at,expires_at) VALUES('private-approval',?,'fixture','{}','hash','pending','2026-01-01','2099-01-01')",
        (key,),
    )
    assert (await http.get("/api/approvals", headers=second)).json() == []
    assert (
        await http.post("/api/approvals/private-approval", headers=second, json={"approved": True})
    ).status_code == 403
    events = (await http.get("/remote/v1/events", headers=second)).json()["events"]
    assert not any(row["task_id"] == key for row in events)
    first_id = (
        await runtime.remote.store.fetchone(
            "SELECT session_id FROM task_sessions WHERE task_id=?", (key,)
        )
    )["session_id"]
    assert (
        await http.get(f"/api/documents?private=true&session_id={first_id}", headers=second)
    ).status_code == 403
