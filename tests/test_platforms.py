import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from jarvis.api import create_app
from jarvis.desktop import existing_service, health_proof
from jarvis.platforms import ServiceLock, capabilities, data_directory
from jarvis.workspace import Workspace


def python_command(script):
    args = [sys.executable, "-c", script]
    return (
        "& " + " ".join("'" + value.replace("'", "''") + "'" for value in args)
        if os.name == "nt"
        else shlex.join(args)
    )


def assert_private_file(path):
    if os.name == "nt":
        permissions = subprocess.check_output(["icacls", str(path)], text=True)
        assert "Everyone" not in permissions and "BUILTIN\\Users" not in permissions
    else:
        assert path.stat().st_mode & 0o777 == 0o600


def test_platform_paths_are_user_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "linux"))
    assert data_directory("win32") == tmp_path / "windows/Jarvis"
    assert data_directory("linux") == tmp_path / "linux/Jarvis"
    assert data_directory("darwin") == Path.home() / "Library/Application Support/Jarvis"
    monkeypatch.setenv("XDG_DATA_HOME", "relative-data")
    with pytest.raises(ValueError, match="absolute"):
        data_directory("linux")


def test_process_lock_excludes_a_second_owner_and_releases(tmp_path):
    first = ServiceLock(tmp_path / "service.lock")
    try:
        with pytest.raises(RuntimeError, match="Another Jarvis"):
            ServiceLock(tmp_path / "service.lock")
    finally:
        first.close()
    ServiceLock(tmp_path / "service.lock").close()


async def test_health_proof_authenticates_the_port_without_disclosing_token(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        nonce = "nonce-for-launcher-check"
        result = (await client.get("/health", params={"challenge": nonce})).json()
        assert result["proof"] == health_proof(config.token, config.settings.api_port, nonce)
        assert result["proof"] != health_proof(config.token, config.settings.api_port + 1, nonce)
        assert config.token not in str(result)
        assert (await client.get("/health", params={"challenge": "bad"})).status_code == 400
        assert "proof" not in (await client.get("/health")).json()


def test_launcher_does_not_send_token_to_an_unverified_listener(config, monkeypatch):
    observed = []

    def handle(request):
        observed.append(request)
        return httpx.Response(200, json={"status": "ok", "service": "jarvis", "proof": "forged"})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr("jarvis.desktop.httpx.Client", lambda **kwargs: client)
    with pytest.raises(RuntimeError, match="unverified service"):
        existing_service(config)
    assert config.token not in str(observed[0].url)
    assert "authorization" not in observed[0].headers


async def test_approved_commands_are_portable_and_do_not_receive_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    result = await Workspace([str(tmp_path)]).command(
        python_command("import os; print('worker-ok'); assert 'OPENAI_API_KEY' not in os.environ"),
        ".",
        "approval",
        10,
    )
    assert result["exit_code"] == 0 and "worker-ok" in result["output"], result["output"]


async def test_unavailable_confinement_has_no_host_fallback(tmp_path):
    if sys.platform == "darwin":
        pytest.skip("The native confinement test covers macOS")
    with pytest.raises(PermissionError, match="no host fallback"):
        await Workspace([str(tmp_path)]).command(
            python_command("raise AssertionError('must not execute')"), ".", "sandbox", 5
        )


def test_workspace_creation_and_revision_work_on_the_host(tmp_path):
    workspace = Workspace([str(tmp_path)])
    workspace.mkdir("nested/child")
    first = workspace.write("nested/child/example.txt", "first")
    assert workspace.read("nested/child/example.txt") == "first"
    assert (
        workspace.write("nested/child/example.txt", "second", first["sha256"])["previous_sha256"]
        == hashlib.sha256(b"first").hexdigest()
    )
    assert workspace.read("nested/child/example.txt") == "second"


@pytest.mark.skipif(os.name != "nt", reason="Win32 reparse-point and path semantics")
def test_windows_aliases_and_junctions_cannot_escape_the_workspace(tmp_path):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside")
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(root / "junction"), str(outside)],
        check=True,
        capture_output=True,
    )
    workspace = Workspace([str(root)])
    for name in [
        "junction/secret.txt",
        ".ENV",
        "API-TOKEN",
        "notes.txt:secret",
        "NUL",
        "settings.json.",
    ]:
        with pytest.raises(PermissionError):
            workspace.read(name)
    with pytest.raises(PermissionError):
        workspace.write("junction/new.txt", "must-not-write")
    assert not (outside / "new.txt").exists()


def test_platform_capabilities_do_not_promise_apple_apis_elsewhere():
    value = capabilities()
    assert value["dashboard"] and value["agents"] and value["workspace_tools"]
    assert value["native_voice"] == (sys.platform == "darwin")
