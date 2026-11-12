import asyncio
import base64
import json
import os
from uuid import uuid4

import httpx
import pytest

from jarvis.api import create_app
from jarvis.lab import source_identity
from jarvis.policy import TaskContext, active_task
from jarvis.remote_context import ClientContext, active_client
from jarvis.sandbox import RPC, DockerWorker
from jarvis.tools import build_tools


async def test_files_are_scoped_private_session_bound_and_expire(runtime):
    session = str(uuid4())
    identity = ("personal", True, session)
    file = await runtime.lab.save_file(identity, "input.csv", b"a,b\n1,2")
    assert not await runtime.db.fetchall("SELECT * FROM lab_files")
    assert (await runtime.lab.file(identity, file["id"]))["content"] == b"a,b\n1,2"
    for other in [("work", True, session), ("personal", True, str(uuid4())), ("personal", False, session)]:
        with pytest.raises(PermissionError):
            await runtime.lab.file(other, file["id"])
    runtime.lab.private_files[file["id"]]["deadline"] = 0
    with pytest.raises(ValueError, match="expired"):
        await runtime.lab.file(identity, file["id"])


async def test_file_paths_and_cross_scope_reads_are_rejected(runtime):
    identity = ("personal", False, str(uuid4()))
    for name in ["../token", "/data/key", "a\\b", ".", ".."]:
        with pytest.raises(ValueError):
            await runtime.lab.save_file(identity, name, b"fixture")
    file = await runtime.lab.save_file(identity, "result.txt", b"fixture")
    with pytest.raises(ValueError):
        await runtime.lab.file(("work", False, identity[2]), file["id"])
    await runtime.db.execute("UPDATE lab_files SET expires_at='2000-01-01' WHERE id=?", (file["id"],))
    with pytest.raises(ValueError):
        await runtime.lab.file(identity, file["id"])


def test_private_identity_includes_device_not_only_session():
    session = str(uuid4())
    values = []
    for device in ["one", "two"]:
        token = active_client.set(ClientContext(device, session, frozenset({"read"}), {}))
        try:
            values.append(source_identity("personal", True, session))
        finally:
            active_client.reset(token)
    assert values[0] != values[1]


async def test_python_cancellation_reaps_worker(runtime, monkeypatch):
    started, closed = asyncio.Event(), asyncio.Event()
    class Worker:
        async def request(self, *args):
            started.set()
            await asyncio.Future()
        async def close(self):
            closed.set()
    async def open_worker(*args, **kwargs):
        return Worker()
    monkeypatch.setattr(runtime.lab, "open_worker", open_worker)
    task = asyncio.create_task(runtime.lab.python(("personal", False, str(uuid4())), "print(1)"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert not runtime.lab.jobs


async def test_browser_rejects_internal_urls_cross_session_and_stale_revision(runtime, monkeypatch):
    class Worker:
        closed = False
        async def request(self, payload, *args):
            return {"url": "https://example.com/", "text": "fixture", "elements": [], "files": [], "dom_sha256": "fixture"}
        async def close(self):
            self.closed = True
    async def open_worker(*args, **kwargs):
        return Worker()
    monkeypatch.setattr(runtime.lab, "open_worker", open_worker)
    identity = ("personal", False, str(uuid4()))
    for url in ["http://127.0.0.1", "http://169.254.169.254", "file:///etc/passwd", "http://example.com:8765"]:
        with pytest.raises(ValueError):
            await runtime.lab.browser(identity, "", "navigate", url=url)
    result = await runtime.lab.browser(identity, "", "navigate", url="https://example.com")
    with pytest.raises(PermissionError, match="another session"):
        await runtime.lab.browser(("personal", False, str(uuid4())), result["browser_id"], "snapshot", revision=1)
    with pytest.raises(ValueError, match="changed"):
        await runtime.lab.browser(identity, result["browser_id"], "click", selector="button", revision=0)
    assert not (await runtime.lab.browser(identity, result["browser_id"], "snapshot", revision=1))["files"]


async def test_browser_egress_rejects_private_targets_and_unapproved_posts(runtime):
    for message in [
        {"url": "http://127.0.0.1", "method": "GET"},
        {"url": "https://example.com", "method": "POST", "body": base64.b64encode(b"secret").decode()},
    ]:
        with pytest.raises((PermissionError, ValueError)):
            await runtime.lab.fetch({"active": True, "write": False, "requests": 0}, message)


async def assert_manual_lab_routes_unavailable(client, context, headers=None):
    requests = [
        ("POST", "/api/lab/python", {**context, "code": "print(1)"}),
        ("POST", "/api/lab/browser/new", {**context, "op": "navigate", "url": "https://example.com"}),
        ("DELETE", f"/api/lab/browser/{uuid4()}", context),
    ]
    for method, path, body in requests:
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code in {404, 405}, (path, response.text)


async def test_lab_api_auth_scope_privacy_and_private_file_download(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/api/lab")).status_code == 401
        client.headers["Authorization"] = "Bearer " + config.token
        session = str(uuid4())
        context = {"scope": "personal", "private": False, "privacy_revision": 0, "session_id": session}
        await assert_manual_lab_routes_unavailable(client, context)
        upload = {**context, "name": "test.txt", "content": "aGk="}
        response = await client.post("/api/lab/files", json=upload)
        assert response.status_code == 200, response.text
        key = response.json()["id"]
        assert (await client.get(f"/api/lab/files/{key}?scope=work")).status_code == 400
        stale = await client.post("/api/lab/files", json={**upload, "privacy_revision": 99})
        assert stale.status_code == 403
        await app.state.runtime.set_voice_session(True, "personal")
        private_upload = {**upload, "private": True, "privacy_revision": 1, "name": "secret.txt"}
        response = await client.post("/api/lab/files", json=private_upload)
        assert response.status_code == 200
        key = response.json()["id"]
        read = await client.get(f"/api/lab/files/{key}", params={"private": "true", "session_id": session})
        assert read.status_code == 200 and read.json()["content"] == "aGk="
        await app.state.runtime.emergency(True)
        assert (await client.post("/api/lab/files", json=private_upload)).status_code == 403


async def test_isolated_python_tool_does_not_use_host_command_grants(runtime, monkeypatch):
    calls = []
    async def execute(identity, code, file_ids, timeout):
        calls.append((identity, code))
        return {"state": "succeeded", "stdout": "2"}
    monkeypatch.setattr(runtime.lab, "python", execute)
    ctx = TaskContext(str(uuid4()), "Calculate one plus one", "local_strict", "personal")
    token = active_task.set(ctx)
    try:
        tool = next(t for t in build_tools(runtime) if t.name == "python_execute")
        result = json.loads(await tool.ainvoke({"code": "print(1+1)"}))
        assert result["stdout"] == "2"
        assert calls and ctx.sensitive_context and ctx.untrusted_context
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
    finally:
        active_task.reset(token)


@pytest.mark.skipif(os.environ.get("JARVIS_TEST_LAB_DOCKER") != "1", reason="Opt-in real Docker sandbox checks")
async def test_real_python_isolation_artifacts_and_timeout(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PROVIDER_SECRET", "must-not-enter-worker")
    worker = await RPC.open("python")
    try:
        result = await worker.request({"code": """import os,socket,pathlib
import pandas as pd
import matplotlib.pyplot as plt
assert pd.DataFrame({"value":[2]}).value.sum() == 2
plt.plot([1,2],[3,4]);plt.savefig("plot.png")
assert os.getuid() == 10001
assert "SYNTHETIC_PROVIDER_SECRET" not in os.environ
assert not pathlib.Path("/data").exists()
try:
    socket.create_connection(("1.1.1.1",443),timeout=1)
    raise AssertionError("network accessible")
except OSError:
    print("network blocked")
open("result.csv","w").write("value\\n2\\n")
""", "files": []}, 30)
        assert result["state"] == "succeeded", result
        assert "network blocked" in result["stdout"]
        files = {f["name"]: base64.b64decode(f["content"]) for f in result["files"]}
        assert files["result.csv"] == b"value\n2\n"
        assert files["plot.png"].startswith(b"\x89PNG")
    finally:
        await worker.close()
    worker = await RPC.open("python")
    try:
        result = await worker.request({"code": "while True: pass", "files": [], "timeout": 1}, 15)
        assert result["state"] == "timed_out"
    finally:
        await worker.close()


@pytest.mark.skipif(os.environ.get("JARVIS_TEST_LAB_DOCKER") != "1", reason="Opt-in real Chromium sandbox checks")
async def test_real_browser_dom_fill_click_and_network_broker():
    requests = []
    html = b'<html><body><h1>Fixture</h1><input id="name"><input id="password" type="password"><button onclick="document.querySelector(\'h1\').textContent=document.querySelector(\'#name\').value">Apply</button></body></html>'
    async def fetch(message):
        requests.append(message["url"])
        return {"status": 200, "headers": {"Content-Type": "text/html"}, "body": base64.b64encode(html).decode()}
    worker = await RPC.open("browser", fetch=fetch)
    try:
        result = await worker.request({"op": "navigate", "url": "https://example.com"}, 45)
        assert "Fixture" in result["text"] and requests
        assert base64.b64decode(result["files"][0]["content"]).startswith(b"\x89PNG")
        with pytest.raises(ValueError, match="Password fields are unavailable"):
            await worker.request({"op": "fill", "selector": "#password", "text": "fixture",
                                  "dom_sha256": result["dom_sha256"], "allow_password": True})
        result = await worker.request({"op": "fill", "selector": "#name", "text": "Verified",
                                       "dom_sha256": result["dom_sha256"]})
        result = await worker.request({"op": "click", "selector": "button", "dom_sha256": result["dom_sha256"]})
        assert "Verified" in result["text"]
        with pytest.raises(ValueError, match="exactly one"):
            await worker.request({"op": "fill", "selector": "#missing", "text": "fixture",
                                  "dom_sha256": result["dom_sha256"]})
        assert not worker.closed
        assert "Verified" in (await worker.request({"op": "snapshot"}))["text"]
    finally:
        await worker.close()


async def test_docker_start_has_no_host_mounts_or_inherited_secrets(monkeypatch):
    commands = []
    class Process:
        stdout = stdin = None
    async def spawn(*args, **kwargs):
        commands.append(args)
        return Process()
    monkeypatch.setattr("jarvis.sandbox.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("jarvis.sandbox.asyncio.create_subprocess_exec", spawn)
    await DockerWorker.start("python")
    args = commands[0]
    assert "--network=none" in args and "--read-only" in args and "--pull=never" in args
    assert "--user=10001:10001" in args and "--cap-drop=ALL" in args
    assert "-v" not in args and "--mount" not in args and "--env" not in args


async def test_remote_private_files_bind_device_and_health_import_checks_scope(config, monkeypatch):
    from test_apple_health import export_xml

    from jarvis.health_parser import parse_export
    from jarvis.remote import ServerOptions

    app = create_app(config, start_scheduler=False, process_lock=False,
                     remote_options=ServerOptions(public_url="https://jarvis.example"))
    runtime = app.state.runtime
    async def parser(raw, days):
        return parse_export(raw, "Europe/Rome", days)
    monkeypatch.setattr(runtime.lab, "parse_health", parser)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://jarvis.example"
    ) as client:
        session = str(uuid4())
        headers = []
        devices = []
        for admin in [True, False]:
            code = await runtime.remote.store.pairing_code("companion", owner=admin)
            enrolled = (await client.post("/remote/v1/pair", json={"code": code, "name": "Fixture", "platform": "ios"})).json()
            devices.append(enrolled["device_id"])
            header = {"Authorization": "Bearer " + enrolled["access_token"], "X-Jarvis-Session": session if admin else str(uuid4())}
            headers.append(header)
            assert (await client.post("/api/voice/session", headers=header, json={"private": True, "scope": "personal"})).status_code == 200
        context = {"scope": "personal", "private": True, "privacy_revision": 1, "session_id": session}
        await assert_manual_lab_routes_unavailable(client, context, headers[0])
        response = await client.post("/api/lab/files", headers=headers[0],
                                     json={**context, "name": "private.txt", "content": "aGk="})
        assert response.status_code == 200, response.text
        key = response.json()["id"]
        path = f"/api/lab/files/{key}?scope=personal&private=true&session_id={session}"
        other_path = path.replace(session, headers[1]["X-Jarvis-Session"])
        assert (await client.get(other_path, headers=headers[1])).status_code == 403
        assert (await client.get(path, headers=headers[0])).status_code == 200
        await client.post("/api/voice/session", headers=headers[0], json={"private": False, "scope": "personal"})
        response = await client.post("/api/apple-health/import?privacy_revision=2&scope=personal",
                                     headers=headers[0], files={"export": ("export.xml", export_xml())})
        assert response.status_code == 200, response.text
        denied = await client.post("/api/apple-health/consent", headers=headers[1],
                                   json={"scope": "personal", "privacy_revision": 1, "revision": 1, "allow_cloud": True})
        assert denied.status_code == 403
        await runtime.remote.revoke_device(devices[1])
        assert (await client.get("/api/lab", headers=headers[1])).status_code != 200


@pytest.mark.skipif(os.environ.get("JARVIS_TEST_LAB_DOCKER") != "1", reason="Opt-in actual broker deployment check")
async def test_real_broker_socket_works_from_nonroot_core_uid():
    import subprocess

    suffix = uuid4().hex[:12]
    name, volume = "jarvis-broker-test-" + suffix, "jarvis-broker-test-" + suffix
    def docker(*args, check=True):
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=45, check=check)
    try:
        await asyncio.to_thread(docker, "run", "-d", "--name", name, "--network=none",
                                "--user=10001:10001", "--group-add=0", "--cap-drop=ALL", "--read-only",
                                "-e", "JARVIS_SANDBOX_PROFILE=small",
                                "-v", "/var/run/docker.sock:/var/run/docker.sock",
                                "-v", volume + ":/run/jarvis-sandbox", "jarvis-sandbox-broker:local")
        # Wait for the actual socket rather than assuming container startup time.
        for _ in range(30):
            probe = await asyncio.to_thread(docker, "exec", name, "test", "-S", "/run/jarvis-sandbox/broker.sock", check=False)
            if probe.returncode == 0:
                break
            await asyncio.sleep(.1)
        script = """import socket,json
s=socket.socket(socket.AF_UNIX);s.connect('/run/jarvis-sandbox/broker.sock')
f=s.makefile('rwb',buffering=0)
f.write(b'{"kind":"python"}\\n')
assert json.loads(f.readline()) == {'ready': True}
s2=socket.socket(socket.AF_UNIX);s2.connect('/run/jarvis-sandbox/broker.sock')
f2=s2.makefile('rwb',buffering=0);f2.write(b'{"kind":"python"}\\n')
assert 'busy' in json.loads(f2.readline())['error']
f2.close();s2.close()
f.write(b'{"kind":"action","id":"probe","code":"print(42)","files":[]}\\n')
r=json.loads(f.readline())
assert r['result']['stdout'].strip()=='42',r
print('verified nonroot core to broker to isolated worker')
f.close();s.close()
"""
        result = await asyncio.to_thread(docker, "run", "--rm", "--network=none", "--user=10001:10001",
                                         "-v", volume + ":/run/jarvis-sandbox",
                                         "--entrypoint", "python", "jarvis-sandbox-broker:local", "-c", script)
        assert "verified nonroot" in result.stdout
    finally:
        await asyncio.to_thread(docker, "rm", "-f", name, check=False)
        await asyncio.to_thread(docker, "volume", "rm", volume, check=False)
