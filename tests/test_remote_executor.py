import asyncio
import contextlib
import hashlib
import json
import socket
import time

import httpx
import pytest
import uvicorn
from cryptography.fernet import Fernet

from jarvis.api import create_app
from jarvis.executor import DesktopExecutor, EffectJournal
from jarvis.remote import ServerOptions
from jarvis.remote_protocol import digest


class MemoryVault:
    def __init__(self, credentials):
        self.credentials = credentials

    def load(self):
        return dict(self.credentials)

    def save(self, value):
        self.credentials = dict(value)


def executor_config(tmp_path, *, origin="http://127.0.0.1:8765", device="device"):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    return {
        "server_url": origin,
        "development": True,
        "device_id": device,
        "workspaces": [
            {
                "id": "project",
                "label": "Project",
                "path": str(root),
                "scope": "work",
                "read": True,
                "write": True,
                "command": True,
                "commands": ["git status"],
            }
        ],
    }


def job(config, operation, **arguments):
    arguments = {"workspace": "project", **arguments}
    return {
        "id": "test-effect",
        "operation": operation,
        "arguments": arguments,
        "scope": "work",
        "argument_hash": digest([config["device_id"], operation, arguments]),
        "expires": time.time() + 30,
    }


def executor(config, tmp_path):
    journal = EffectJournal(tmp_path / "agent" / "effects.sqlite3", Fernet(Fernet.generate_key()))
    return DesktopExecutor(config, tmp_path / "agent", MemoryVault({}), journal)


async def test_local_grants_scope_traversal_and_shell_chains(tmp_path):
    config = executor_config(tmp_path)
    worker = executor(config, tmp_path)
    try:
        for path in ["../secret", "/etc/passwd", "C:\\Windows\\secret", "workspace://2/file"]:
            with pytest.raises(PermissionError):
                worker.authorize(job(config, "workspace_read", path=path))
        wrong_scope = job(config, "workspace_read", path="file")
        wrong_scope["scope"] = "personal"
        with pytest.raises(PermissionError):
            worker.authorize(wrong_scope)
        for command in [
            "git status; whoami",
            "git status && whoami",
            "git status $(whoami)",
            "python -c evil",
        ]:
            with pytest.raises(PermissionError):
                worker.authorize(job(config, "workspace_command", command=command))
        config["workspaces"][0]["write"] = False
        with pytest.raises(PermissionError):
            worker.authorize(job(config, "workspace_write", path="file", content="new"))
    finally:
        worker.journal.conn.close()


async def test_native_grants_are_local_scoped_and_hash_bound(tmp_path):
    config = executor_config(tmp_path)
    config.update(native=["calendar.list"], native_scope="personal")
    worker = executor(config, tmp_path)
    try:
        request = job(config, "calendar.list", days=2)
        with pytest.raises(PermissionError):
            worker.authorize(request)
        request["scope"] = "personal"
        assert worker.authorize(request) == (None, None)
        request["arguments"]["days"] = 3
        with pytest.raises(PermissionError):
            worker.authorize(request)
        config["native"] = []
        with pytest.raises(PermissionError):
            worker.authorize(job(config, "calendar.delete", event_id="not-authorized"))
    finally:
        worker.journal.conn.close()


async def test_duplicate_delivery_reuses_result_without_second_write(tmp_path):
    config = executor_config(tmp_path)
    worker = executor(config, tmp_path)
    target = tmp_path / "project" / "file.txt"
    target.write_text("before")
    request = job(
        config,
        "workspace_write",
        path="file.txt",
        content="after",
        expected_sha256=hashlib.sha256(b"before").hexdigest(),
    )
    try:
        await worker.handle(request)
        first = worker.journal.get(request["id"])
        assert first["state"] == "succeeded"
        assert target.read_text() == "after"
        target.write_text("owner edited after first execution")
        await worker.handle(request)
        assert target.read_text() == "owner edited after first execution"
        assert worker.journal.get(request["id"])["state"] == "succeeded"
        assert "after" not in first["result"]
    finally:
        worker.journal.conn.close()


async def test_restart_unknown_is_not_reexecuted_and_private_results_do_not_persist(tmp_path):
    config = executor_config(tmp_path)
    worker = executor(config, tmp_path)
    request = job(config, "workspace_write", path="file.txt", content="private-data")
    request["private"] = True
    worker.journal.start(request)
    cipher, path = worker.journal.cipher, tmp_path / "agent" / "effects.sqlite3"
    worker.journal.conn.close()
    worker.journal = EffectJournal(path, cipher)
    try:
        await worker.handle(request)
        assert worker.journal.get(request["id"])["state"] == "unknown"
        assert not (tmp_path / "project" / "file.txt").exists()
        assert "private-data" not in path.read_bytes().decode(errors="ignore")
    finally:
        worker.journal.conn.close()


async def test_real_outbound_websocket_file_read_and_revoke(config, tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    app = create_app(
        config,
        start_scheduler=False,
        process_lock=False,
        remote_options=ServerOptions(public_url=origin, development_http=True),
    )
    started = asyncio.Event()

    class FixtureServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            started.set()

    service = FixtureServer(
        uvicorn.Config(app, log_level="critical", access_log=False, ws_max_size=64000)
    )
    server_task = asyncio.create_task(service.serve(sockets=[listener]))
    worker_task = None
    worker = None
    try:
        async with asyncio.timeout(10):
            await started.wait()
        remote = app.state.runtime.remote
        code = await remote.store.pairing_code("executor")
        async with httpx.AsyncClient(base_url=origin, trust_env=False) as http:
            response = await http.post(
                "/remote/v1/pair", json={"code": code, "name": "Fixture Mac", "platform": "macos"}
            )
        credentials = response.json()
        cfg = executor_config(tmp_path, origin=origin, device=credentials["device_id"])
        (tmp_path / "project" / "file.txt").write_text("outbound connection works")
        worker = executor(cfg, tmp_path)
        worker.vault = MemoryVault(credentials)
        worker_task = asyncio.create_task(worker.run())
        async with asyncio.timeout(10):
            async with remote.device_changes:
                await remote.device_changes.wait_for(
                    lambda: cfg["device_id"] in remote.capabilities
                )
        result = await remote.jobs.submit(
            cfg["device_id"],
            "workspace_read",
            {"workspace": "project", "path": "file.txt"},
            scope="work",
            ttl=10,
        )
        assert result["text"] == "outbound connection works"
        assert result["sha256"] == hashlib.sha256(result["text"].encode()).hexdigest()
        rows = await remote.store.fetchall("SELECT * FROM executor_jobs")
        assert len(rows) == 1 and rows[0]["state"] == "succeeded"
        assert "outbound connection works" not in json.dumps(rows)
        await remote.store.revoke(cfg["device_id"])
        with pytest.raises(PermissionError):
            await remote.jobs.submit(
                cfg["device_id"],
                "workspace_read",
                {"workspace": "project", "path": "file.txt"},
                scope="work",
            )
    finally:
        if worker:
            worker.stopping = True
        if worker_task:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        service.should_exit = True
        await asyncio.wait_for(server_task, 10)
        if worker:
            worker.journal.conn.close()
