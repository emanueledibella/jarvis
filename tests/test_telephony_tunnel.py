import asyncio
import socket
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_telephony_integrations import phone_config
from twilio.request_validator import RequestValidator

from jarvis.api import create_app
from jarvis.platforms import process_environment
from jarvis.runtime import Runtime
from jarvis.telephony_process import child_command
from jarvis.telephony_tunnel import caddy_config, executable

PUBLIC_URL = "https://fixture-jarvis.trycloudflare.com"


class Child:
    def __init__(self, output=b""):
        self.returncode = None
        self.pid = 999999
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(output)
        self.exited = asyncio.Event()
        self.stdin = SimpleNamespace(close=self.finish)

    def finish(self, code=0):
        if self.returncode is None:
            self.returncode = code
            self.stdout.feed_eof()
            self.exited.set()

    async def wait(self):
        await self.exited.wait()
        return self.returncode


@pytest.fixture
def children(monkeypatch):
    created = []

    async def spawn(*arguments, **options):
        caddy = "/fixture/caddy" in arguments
        child = Child(
            b"serving initial configuration\n"
            if caddy
            else (PUBLIC_URL + "\nRegistered tunnel connection\n").encode()
        )
        created.append((child, arguments, options))
        return child

    monkeypatch.setattr("jarvis.telephony_tunnel.executable", lambda name: "/fixture/" + name)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return created


def managed_config(config):
    phone_config(config)
    config.update({"telephony_enabled": False, "phone_inbound_enabled": False})


async def state(tunnel, expected):
    async with asyncio.timeout(3):
        while tunnel.state != expected:  # noqa: ASYNC110 - observe an independent lifecycle job.
            await asyncio.sleep(0.01)


async def test_concurrent_start_owns_exactly_two_children_and_stop_removes_everything(
    runtime, children, monkeypatch
):
    managed_config(runtime.config)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-must-not-reach-child")
    probe = AsyncMock()
    monkeypatch.setattr(runtime.telephony, "check_reachability", probe)
    tunnel = runtime.telephony.tunnel
    results = await asyncio.gather(*(tunnel.start() for _ in range(6)))
    assert all(result["state"] == "starting" for result in results)
    await state(tunnel, "running")
    assert len(children) == 2 and runtime.telephony.ready() == (True, [])
    assert runtime.telephony.public_base_url == PUBLIC_URL
    assert runtime.config.settings.telephony_public_base_url == "https://phone.example.com"
    assert PUBLIC_URL not in runtime.config.path.read_text()
    probe.assert_awaited_once()
    directory = Path(tunnel.directory.name)
    assert await asyncio.to_thread(directory.is_dir)
    for _, _, options in children:
        assert "OPENAI_API_KEY" not in options["env"]
        assert "JARVIS_TELEPHONY_AUTH_TOKEN" not in options["env"]
        assert options["stdin"] == asyncio.subprocess.PIPE
    await tunnel.start()
    assert len(children) == 2
    await tunnel.stop()
    assert all(child.returncode == 0 for child, *_ in children)
    assert not await asyncio.to_thread(directory.exists)
    assert not tunnel.processes and not tunnel.readers
    assert not runtime.telephony.public_base_url
    assert not runtime.telephony.ready()[0]


async def test_cancel_during_proxy_start_closes_the_only_child(runtime, children, monkeypatch):
    managed_config(runtime.config)
    tunnel = runtime.telephony.tunnel
    waiting = asyncio.Event()

    async def wait_ready(*args):
        await waiting.wait()

    monkeypatch.setattr(tunnel, "_wait_ready", wait_ready)
    await tunnel.start()
    async with asyncio.timeout(3):
        while not children:  # noqa: ASYNC110 - observe OS child creation.
            await asyncio.sleep(0.01)
    await tunnel.stop()
    assert len(children) == 1 and children[0][0].returncode == 0
    assert tunnel.state == "stopped" and not tunnel.url and tunnel.directory is None


async def test_cancellation_during_os_spawn_still_claims_and_stops_child(
    runtime, children, monkeypatch
):
    managed_config(runtime.config)
    entered, release = asyncio.Event(), asyncio.Event()
    original = asyncio.create_subprocess_exec

    async def deferred(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", deferred)
    tunnel = runtime.telephony.tunnel
    await tunnel.start()
    await asyncio.wait_for(entered.wait(), timeout=3)
    stopping = asyncio.create_task(tunnel.stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(stopping, timeout=3)
    assert len(children) == 1 and children[0][0].returncode == 0
    assert tunnel.directory is None and not tunnel.processes


@pytest.mark.parametrize("proxy_exits", [False, True])
async def test_public_probe_waits_for_registered_cloudflare_connection(
    runtime, children, monkeypatch, proxy_exits
):
    managed_config(runtime.config)
    original = asyncio.create_subprocess_exec
    cloud_started = asyncio.Event()
    probe = AsyncMock()
    monkeypatch.setattr(runtime.telephony, "check_reachability", probe)

    async def unregistered(*args, **kwargs):
        child = await original(*args, **kwargs)
        if "/fixture/cloudflared" in args:
            child.stdout = asyncio.StreamReader()
            child.stdout.feed_data((PUBLIC_URL + "\n").encode())
            cloud_started.set()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unregistered)
    tunnel = runtime.telephony.tunnel
    await tunnel.start()
    await asyncio.wait_for(cloud_started.wait(), timeout=3)
    await asyncio.sleep(0)
    assert tunnel.state == "starting"
    probe.assert_not_awaited()
    if proxy_exits:
        children[0][0].finish(1)
        await state(tunnel, "error")
        assert all(child.returncode is not None for child, *_ in children)
    else:
        children[-1][0].stdout.feed_data(b"Registered tunnel connection\n")
        await state(tunnel, "running")
        probe.assert_awaited_once()


async def test_public_probe_retries_temporary_dns_failures(runtime, monkeypatch):
    probe = AsyncMock(side_effect=[ValueError("DNS pending"), ValueError("DNS cached"), None])
    monkeypatch.setattr(runtime.telephony, "check_reachability", probe)
    real_sleep = asyncio.sleep

    async def next_tick(delay):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", next_tick)
    await runtime.telephony.tunnel._verify_public_url()
    assert probe.await_count == 3


async def test_tunnel_lost_during_call_probe_never_creates_or_reserves_a_call(
    runtime, children, monkeypatch
):
    managed_config(runtime.config)
    phone = runtime.telephony
    monkeypatch.setattr(phone, "check_reachability", AsyncMock())
    await phone.tunnel.start()
    await state(phone.tunnel, "running")

    async def lose_connection():
        children[-1][0].finish(1)
        await state(phone.tunnel, "error")

    monkeypatch.setattr(phone, "check_reachability", lose_connection)
    with pytest.raises(ValueError, match="settings changed"):
        await phone.call_owner("fixture-call", "Authorized test", authorized=True)
    assert not await runtime.db.fetchall("SELECT * FROM calls")


async def test_stop_closes_proxy_then_waits_for_inflight_carrier_creation_to_end_call(
    runtime, children, monkeypatch
):
    managed_config(runtime.config)
    phone = runtime.telephony
    monkeypatch.setattr(phone, "check_reachability", AsyncMock())
    await phone.tunnel.start()
    await state(phone.tunnel, "running")
    entered, release = threading.Event(), threading.Event()
    completed = []

    class Calls:
        def create(self, **kwargs):
            assert kwargs["url"].startswith(PUBLIC_URL + "/telephony/voice?")
            entered.set()
            if not release.wait(timeout=3):
                raise TimeoutError("Fixture carrier was not released")
            return SimpleNamespace(sid="CA" + "b" * 32)

        def __call__(self, sid):
            return SimpleNamespace(update=lambda **kwargs: completed.append((sid, kwargs)))

    monkeypatch.setattr(
        "twilio.rest.Client", lambda *args, **kwargs: SimpleNamespace(calls=Calls())
    )
    calling = asyncio.create_task(
        phone.call_owner("fixture-call", "Authorized test", authorized=True)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        stopping = asyncio.create_task(phone.stop_all())
        await state(phone.tunnel, "stopped")
        assert not stopping.done()
        assert all(child.returncode == 0 for child, *_ in children)
        release.set()
        await asyncio.wait_for(calling, timeout=3)
        await asyncio.wait_for(stopping, timeout=3)
        assert completed == [("CA" + "b" * 32, {"status": "completed"})]
        assert (await runtime.db.fetchone("SELECT state FROM calls"))["state"] == "completed"
    finally:
        release.set()
        await asyncio.gather(calling, return_exceptions=True)


@pytest.mark.parametrize("failure", ["proxy", "public-probe", "incoming-webhooks", "process-exit"])
async def test_failed_activation_or_child_exit_closes_the_whole_pair(
    runtime, children, monkeypatch, failure
):
    managed_config(runtime.config)
    tunnel = runtime.telephony.tunnel
    monkeypatch.setattr(runtime.telephony, "check_reachability", AsyncMock())
    if failure == "proxy":
        monkeypatch.setattr(
            tunnel, "_wait_ready", AsyncMock(side_effect=ValueError("proxy failed"))
        )
    elif failure == "public-probe":
        monkeypatch.setattr(
            tunnel, "_verify_public_url", AsyncMock(side_effect=ValueError("probe failed"))
        )
    elif failure == "incoming-webhooks":
        monkeypatch.setattr(
            runtime.telephony,
            "configure_inbound_webhooks",
            AsyncMock(side_effect=ValueError("incoming failed")),
        )
    await tunnel.start()
    if failure == "process-exit":
        await state(tunnel, "running")
        children[-1][0].finish(1)
    await state(tunnel, "error")
    assert all(child.returncode is not None for child, *_ in children)
    assert tunnel.directory is None and not tunnel.url
    assert not runtime.telephony.ready()[0]
    assert tunnel.status()["error"]
    await tunnel.stop()
    assert tunnel.state == "stopped" and not tunnel.error


@pytest.mark.parametrize(
    "reason", ["credentials", "dependencies", "local-only", "emergency", "locked", "active-call"]
)
async def test_preflight_refuses_start_without_creating_processes(
    runtime, children, monkeypatch, reason
):
    managed_config(runtime.config)
    if reason == "credentials":
        runtime.config.update({"telephony_account_id": ""})
    elif reason == "dependencies":
        monkeypatch.setattr("jarvis.telephony_tunnel.executable", lambda name: None)
    elif reason == "local-only":
        runtime.config.update({"profile": "local_strict"})
    elif reason == "emergency":
        runtime.gateway.blocked = True
    elif reason == "locked":
        monkeypatch.setattr(runtime.config, "locked_fields", lambda: ["telephony_enabled"])
    else:
        await runtime.db.execute(
            "INSERT INTO calls(id,event_key,direction,state,created_at) VALUES('fixture','fixture','outbound','unknown','2026-10-28')"
        )
    with pytest.raises((ValueError, PermissionError)):
        await runtime.telephony.tunnel.start()
    assert not children and not runtime.config.settings.telephony_enabled


async def test_runtime_close_and_emergency_stop_close_tunnel_and_restart_is_opt_in(
    config, children, monkeypatch
):
    managed_config(config)
    first = Runtime(config)
    await first.start(scheduler=False, process_lock=False)
    monkeypatch.setattr(first.telephony, "check_reachability", AsyncMock())
    await first.telephony.tunnel.start()
    await state(first.telephony.tunnel, "running")
    await first.emergency(True)
    assert all(child.returncode == 0 for child, *_ in children)
    await first.emergency(False)
    await first.telephony.tunnel.start()
    await state(first.telephony.tunnel, "running")
    await first.close()
    assert len(children) == 4 and all(child.returncode == 0 for child, *_ in children)
    second = Runtime(config)
    await second.start(scheduler=False, process_lock=False)
    try:
        assert second.telephony.tunnel.state == "stopped"
        assert not second.telephony.public_base_url
        assert not second.telephony.ready()[0]
        assert len(children) == 4
    finally:
        await second.close()


async def test_control_api_authenticates_and_signatures_use_current_managed_url(
    config, children, monkeypatch
):
    managed_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    phone = app.state.runtime.telephony
    monkeypatch.setattr(phone, "check_reachability", AsyncMock())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        for method, path in [("GET", "status"), ("POST", "start"), ("POST", "stop")]:
            assert (await client.request(method, "/api/telephony/" + path)).status_code == 401
        assert not children
        auth = {"Authorization": "Bearer " + config.token}
        assert (
            await client.post(
                "/api/telephony/start", headers={**auth, "Origin": "https://attacker.example"}
            )
        ).status_code == 403
        assert (await client.post("/api/telephony/start", headers=auth)).json()[
            "state"
        ] == "starting"
        await state(phone.tunnel, "running")
        assert (await client.get("/api/telephony/status", headers=auth)).json()[
            "public_url"
        ] == PUBLIC_URL
        data = {"JarvisProbe": "fixture-challenge"}
        signature = RequestValidator(
            config.settings.secret("telephony_auth_token")
        ).compute_signature(PUBLIC_URL + "/telephony/status", data)
        headers = {"Host": "fixture-jarvis.trycloudflare.com", "X-Twilio-Signature": signature}
        response = await client.post("/telephony/status", data=data, headers=headers)
        assert response.status_code == 200
        assert response.json()["proof"] == phone.probe_proof(data["JarvisProbe"])
        assert (
            await client.post(
                "/telephony/status", data=data, headers={**headers, "Host": "phone.example.com"}
            )
        ).status_code == 400
        assert (
            await client.get(
                "/api/status", headers={**auth, "Host": "fixture-jarvis.trycloudflare.com"}
            )
        ).status_code == 400
        assert not await phone.db.fetchall("SELECT * FROM calls")
        assert (await client.post("/api/telephony/stop", headers=auth)).json()["state"] == "stopped"
        assert not config.settings.telephony_enabled
        assert all(child.returncode == 0 for child, *_ in children)
        assert (
            await client.post("/telephony/status", data=data, headers=headers)
        ).status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        {"telephony_enabled": False},
        {"profile": "local_strict"},
        {"telephony_tunnel_mode": "external"},
        {"phone_inbound_enabled": True},
    ],
)
async def test_settings_changes_close_managed_transport(config, children, monkeypatch, change):
    managed_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    phone = app.state.runtime.telephony
    monkeypatch.setattr(phone, "check_reachability", AsyncMock())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        await phone.tunnel.start()
        await state(phone.tunnel, "running")
        assert (await client.patch("/api/settings", json=change)).status_code == 200
        assert phone.tunnel.state == "stopped"
        assert all(child.returncode == 0 for child, *_ in children)


async def test_changing_carrier_credentials_ends_existing_call_with_previous_credentials(
    config, children, monkeypatch
):
    managed_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    phone = app.state.runtime.telephony
    monkeypatch.setattr(phone, "check_reachability", AsyncMock())
    authenticated = []
    completed = []

    def carrier(account, token, **kwargs):
        authenticated.append((account, token))
        return SimpleNamespace(
            calls=lambda sid: SimpleNamespace(update=lambda **values: completed.append(sid))
        )

    monkeypatch.setattr("twilio.rest.Client", carrier)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        await phone.tunnel.start()
        await state(phone.tunnel, "running")
        sid = "CA" + "c" * 32
        await phone.db.execute(
            "INSERT INTO calls(id,event_key,direction,state,provider_id,created_at) VALUES('fixture','fixture','outbound','ringing',?,'2026-10-28')",
            (sid,),
        )
        response = await client.patch(
            "/api/settings", json={"telephony_auth_token": "replacement-fixture-secret"}
        )
        assert response.status_code == 200
        assert authenticated == [(config.settings.telephony_account_id, "test-carrier-secret")]
        assert completed == [sid]
        assert config.settings.secret("telephony_auth_token") == "replacement-fixture-secret"
        assert (await phone.db.fetchone("SELECT state FROM calls"))["state"] == "completed"
        assert all(child.returncode == 0 for child, *_ in children)


async def test_incoming_webhooks_follow_new_url_without_placing_calls(runtime, monkeypatch):
    phone_config(runtime.config)
    runtime.config.update({"telephony_tunnel_mode": "managed"})
    phone = runtime.telephony
    phone.tunnel.url = PUBLIC_URL
    update = AsyncMock()
    number = SimpleNamespace(
        phone_number=runtime.config.settings.telephony_from_number, update_async=update
    )
    lookup = AsyncMock(return_value=[number])
    monkeypatch.setattr(
        "twilio.rest.Client",
        lambda *args, **kwargs: SimpleNamespace(
            incoming_phone_numbers=SimpleNamespace(list_async=lookup)
        ),
    )
    assert await phone.configure_inbound_webhooks()
    lookup.assert_awaited_once_with(phone_number=number.phone_number, limit=2)
    update.assert_awaited_once_with(
        voice_url=PUBLIC_URL + "/telephony/voice",
        voice_method="POST",
        voice_application_sid="",
        status_callback=PUBLIC_URL + "/telephony/status",
        status_callback_method="POST",
    )
    assert not await runtime.db.fetchall("SELECT * FROM calls")
    lookup.return_value = []
    with pytest.raises(ValueError, match="Could not update incoming"):
        await phone.configure_inbound_webhooks()
    assert update.await_count == 1


async def test_guardian_releases_real_listener_when_lifetime_pipe_closes():
    code = "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(60)"
    guardian = await asyncio.create_subprocess_exec(
        *child_command([sys.executable, "-u", "-c", code]),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=process_environment(),
    )
    try:
        port = int(await asyncio.wait_for(guardian.stdout.readline(), timeout=5))
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        guardian.stdin.close()
        assert await asyncio.wait_for(guardian.wait(), timeout=5) == 0
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)
    finally:
        if guardian.returncode is None:
            guardian.stdin.close()
            await asyncio.wait_for(guardian.wait(), timeout=5)


async def test_guardian_closes_listener_when_backend_is_killed():
    native_code = "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(60)"
    command = child_command([sys.executable, "-u", "-c", native_code])
    parent_code = f"import subprocess,sys,time; p=subprocess.Popen({command!r},stdin=subprocess.PIPE,stdout=sys.stdout); time.sleep(60)"
    parent = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        parent_code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=process_environment(),
    )
    port = None
    try:
        port = int(await asyncio.wait_for(parent.stdout.readline(), timeout=5))
        parent.kill()
        await asyncio.wait_for(parent.wait(), timeout=5)
        async with asyncio.timeout(5):
            while True:
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                except OSError:
                    break
                await asyncio.sleep(0.05)
    finally:
        if parent.returncode is None:
            parent.kill()
            await parent.wait()


@pytest.mark.skipif(executable("caddy") is None, reason="Caddy is not installed")
async def test_real_caddy_exposes_only_allowed_phone_methods_and_routes(tmp_path):
    seen = []

    async def backend(reader, writer):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            seen.append(request.split(b"\r\n")[0].decode())
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(backend, "127.0.0.1", 0)
    api_port = server.sockets[0].getsockname()[1]
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    path = tmp_path / "Caddyfile"
    path.write_text(caddy_config(api_port, port))
    proxy = await asyncio.create_subprocess_exec(
        executable("caddy"),
        "run",
        "--config",
        str(path),
        "--adapter",
        "caddyfile",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env={
            **process_environment(),
            "XDG_DATA_HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path),
        },
    )
    try:
        async with asyncio.timeout(5):
            while True:
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    await asyncio.sleep(0.05)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False
        ) as client:
            for method, route in [
                ("POST", "/telephony/voice"),
                ("POST", "/telephony/status"),
                ("GET", "/telephony/media"),
            ]:
                assert (await client.request(method, route)).status_code == 200
            for method, route in [
                ("GET", "/"),
                ("GET", "/health"),
                ("GET", "/api/settings"),
                ("GET", "/assets/test.js"),
                ("GET", "/telephony/voice"),
                ("POST", "/telephony/media"),
                ("GET", "/telephony/../api/settings"),
                ("GET", "/%61pi/settings"),
            ]:
                assert (await client.request(method, route)).status_code == 404
        assert seen == [
            "POST /telephony/voice HTTP/1.1",
            "POST /telephony/status HTTP/1.1",
            "GET /telephony/media HTTP/1.1",
        ]
    finally:
        proxy.terminate()
        await asyncio.wait_for(proxy.wait(), timeout=5)
        server.close()
        await server.wait_closed()
