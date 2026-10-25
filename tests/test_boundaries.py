import hashlib
import json
import os

import httpx
import pytest

from jarvis.api import create_app
from jarvis.config import ConfigStore
from jarvis.mcp_config import save_mcp_config
from jarvis.network import loopback_url, public_url
from jarvis.workspace import Workspace


async def test_api_auth_origin_host_and_size(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/api/status")).status_code == 401
        headers = {"Authorization": "Bearer " + config.token}
        assert (await client.get("/api/status", headers=headers)).status_code == 200
        assert (
            await client.get("/api/status", headers={**headers, "Host": "attacker.example"})
        ).status_code == 400
        assert (
            await client.get(
                "/api/status", headers={**headers, "Origin": "https://attacker.example"}
            )
        ).status_code == 403
        assert (
            await client.post("/api/chat", content=b"x" * 512001, headers=headers)
        ).status_code == 413
        assert (await client.get("/api/missing", headers=headers)).status_code == 404


async def test_disabled_voice_cannot_be_reactivated_through_native_actions(config, monkeypatch):
    config.update({"voice_enabled": False})
    app = create_app(config, start_scheduler=False, process_lock=False)

    async def forbidden(*args, **kwargs):
        raise AssertionError("A disabled voice path must never reach the microphone")

    monkeypatch.setattr(app.state.runtime.native, "invoke", forbidden)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        for action in ("enable", "unmute", "listen"):
            response = await client.post("/api/voice/control", json={"action": action})
            assert response.status_code == 403


async def test_voice_session_privacy_and_scope_are_forwarded_without_transcript(
    config, monkeypatch
):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        runtime = app.state.runtime
        seen = []

        async def invoke(operation, arguments, **kwargs):
            seen.append((operation, arguments))
            return {"state": "listening"}

        monkeypatch.setattr(runtime.native, "invoke", invoke)
        assert (
            await client.post("/api/voice/session", json={"private": True, "scope": "work"})
        ).status_code == 200
        assert (
            await client.post("/api/voice/control", json={"action": "listen"})
        ).status_code == 200
        assert seen == [("control.listen", {"private": True, "scope": "work"})]
        assert runtime.voice_session == {"private": True, "scope": "work", "revision": 1}
        assert (
            await client.post("/api/voice/session", json={"private": "yes", "scope": "work"})
        ).status_code == 400
        events = await runtime.db.fetchall("SELECT data FROM events WHERE type='native.operation'")
        assert all(event["data"] == "{}" for event in events)
    assert "private_session" not in config.settings.public()


async def test_privacy_mode_survives_restart_without_conversation_content(config):
    from jarvis.runtime import Runtime

    first = Runtime(config)
    await first.start(scheduler=False, process_lock=False)
    await first.set_voice_session(True, "work")
    await first.close()
    second = Runtime(config)
    await second.start(scheduler=False, process_lock=False)
    try:
        assert second.voice_session == {"private": True, "scope": "work", "revision": 1}
        result = await second.set_voice_session(True, "work")
        assert result["revision"] == 1 and result["state"] == "unchanged"
        assert not await second.db.fetchall("SELECT * FROM messages")
    finally:
        await second.close()


async def test_stale_privacy_revision_is_rejected_and_default_is_private(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        runtime = app.state.runtime
        assert (await client.get("/api/voice/session")).json()["revision"] == 0
        await client.post("/api/voice/session", json={"private": True, "scope": "work"})
        stale = await client.post(
            "/api/chat",
            json={
                "text": "Dati di prova privati",
                "private": False,
                "scope": "personal",
                "privacy_revision": 0,
            },
        )
        assert stale.status_code == 409
        assert not await runtime.db.fetchall("SELECT * FROM tasks")
        current = await client.post("/api/chat", json={"text": "Dati di prova privati"})
        assert current.status_code == 202
        key = current.json()["id"]
        if key in runtime.tasks.running:
            await runtime.tasks.running[key]
        row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (key,))
        assert row["private"] == 1 and row["scope"] == "work" and row["prompt"] == ""
        assert not await runtime.db.fetchall("SELECT * FROM messages")


def test_config_precedence_and_secret_redaction(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_LOCAL_MODEL=from-dotenv\n")
    c = ConfigStore(env_file=env_file, data_dir=tmp_path / "data")
    c.update({"local_model": "from-ui", "cloud_api_key": "test-secret"})
    assert c.settings.local_model == "from-dotenv"
    monkeypatch.setenv("JARVIS_LOCAL_MODEL", "from-process")
    assert c.load().local_model == "from-process"
    assert c.settings.public()["cloud_api_key"] == ""
    assert c.settings.public()["cloud_api_key_configured"] is True
    if os.name == "nt":
        import subprocess

        permissions = subprocess.check_output(["icacls", str(c.token_path)], text=True)
        assert "Everyone" not in permissions and "BUILTIN\\Users" not in permissions
    else:
        assert os.stat(c.path).st_mode & 0o777 == 0o600
        assert os.stat(c.token_path).st_mode & 0o777 == 0o600
    assert "local_model" in c.locked_fields()


def test_mcp_permission_edit_preserves_private_fields(config):
    save_mcp_config(
        config,
        {
            "servers": {
                "demo": {
                    "url": "http://127.0.0.1:9000/mcp",
                    "token": "private",
                    "auth": "bearer",
                    "env": {"API_KEY": "env:KEY"},
                    "read_tools": ["read"],
                }
            }
        },
    )
    save_mcp_config(
        config,
        {
            "servers": {
                "demo": {
                    "url": "http://127.0.0.1:9000/mcp",
                    "auth": "bearer",
                    "read_tools": ["read", "list"],
                }
            }
        },
    )
    spec = json.loads(config.settings.mcp_config_path.read_text())["servers"]["demo"]
    assert spec["token"] == "private"
    assert spec["env"] == {"API_KEY": "env:KEY"}
    assert spec["read_tools"] == ["read", "list"]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest",
        "http://[::1]/",
        "file:///etc/passwd",
        "https://user:password@example.com",
        "https://example.com:8000",
        "http://device.local/",
    ],
)
def test_web_blocks_internal_destinations(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_local_endpoint_validation():
    assert loopback_url("http://127.0.0.1:11434")
    assert not loopback_url("http://user:secret@localhost")
    assert not loopback_url("https://models.example.com")


def test_workspace_secrets_symlinks_and_optimistic_write(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (root / "escape").symlink_to(outside)
    (root / ".env").write_text("PRIVATE=1")
    (root / "sample.py").write_text("original")
    w = Workspace([str(root)])
    for path in [".env", "escape", "../outside.txt"]:
        with pytest.raises(PermissionError):
            w.read(path)
    with pytest.raises(ValueError):
        w.write("sample.py", "overwrite")
    result = w.write("sample.py", "updated", hashlib.sha256(b"original").hexdigest())
    assert result["sha256"] == hashlib.sha256(b"updated").hexdigest()
    assert w.read("sample.py") == "updated"
    with pytest.raises(ValueError):
        w.write("sample.py", "stale", hashlib.sha256(b"original").hexdigest())


async def test_commands_do_not_inherit_provider_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "never-inherit-this")
    result = await Workspace([str(tmp_path)]).command(
        "set" if os.name == "nt" else "env", ".", "approval", 5
    )
    assert "never-inherit-this" not in result["output"]
    assert "OPENAI_API_KEY" not in result["output"]


async def test_command_timeout_kills_worker(tmp_path):
    with pytest.raises(TimeoutError):
        from test_platforms import python_command

        await Workspace([str(tmp_path)]).command(
            python_command("import time; time.sleep(10)"), ".", "approval", 1
        )


async def test_macos_sandbox_runs_python_and_denies_external_file_and_network(tmp_path):
    import asyncio
    import shlex
    import shutil
    import sys
    from pathlib import Path

    if (
        sys.platform != "darwin"
        or not await asyncio.to_thread(Path("/usr/bin/sandbox-exec").exists)
        or not shutil.which("python3.12")
    ):
        pytest.skip("Requires the macOS toolchain")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "inside.txt").write_text("inside")
    outside = tmp_path / "outside.txt"
    outside.write_text("must-not-read")
    script = f"""from pathlib import Path
import socket
assert Path('inside.txt').read_text() == 'inside'
try:
    Path({str(outside)!r}).read_text()
except PermissionError:
    print('file-denied')
else:
    raise AssertionError('outside file readable')
try:
    socket.create_connection(('127.0.0.1', 9), timeout=1)
except PermissionError:
    print('network-denied')
else:
    raise AssertionError('network allowed')
"""
    result = await Workspace([str(root)]).command(
        "python3.12 -c " + shlex.quote(script), ".", "sandbox", 5
    )
    assert result["exit_code"] == 0, result["output"]
    assert "file-denied" in result["output"] and "network-denied" in result["output"]
