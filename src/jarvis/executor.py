"""Desktop executor: outbound WSS, OS credential vault, local grants and effect journal."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import shlex
import sqlite3
import sys
import time
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet

from .platforms import ServiceLock, data_directory, protect_path
from .remote_protocol import NATIVE_OPERATIONS, OPERATIONS, digest
from .workspace import Workspace


def server_url(value, *, development=False):
    p = urlsplit(value)
    if (
        not p.hostname
        or p.username
        or p.password
        or p.path not in {"", "/"}
        or p.query
        or p.fragment
    ):
        raise ValueError("Use the HTTPS origin of your Jarvis server.")
    if p.scheme != "https" and not (
        development and p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValueError(
            "The executor requires HTTPS; HTTP is available only for explicit loopback development."
        )
    try:
        port = None if p.port == {"https": 443, "http": 80}[p.scheme] else p.port
        return str(httpx.URL(value).copy_with(scheme=p.scheme, port=port)).rstrip("/")
    except httpx.InvalidURL:
        raise ValueError("Use a valid HTTPS origin and port.") from None


class CredentialVault:
    def __init__(self, account):
        self.account = account

    def load(self):
        import keyring

        value = keyring.get_password("JarvisExecutor", self.account)
        if not value:
            raise ValueError("Pair the executor before starting it.")
        return json.loads(value)

    def save(self, value):
        import keyring

        backend = keyring.get_keyring()
        if any(word in type(backend).__module__.lower() for word in ("fail", "plaintext", "null")):
            raise PermissionError("An operating-system credential vault is required.")
        keyring.set_password("JarvisExecutor", self.account, json.dumps(value))


class EffectJournal:
    def __init__(self, path, cipher):
        self.cipher = cipher
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.conn = sqlite3.connect(path)
        protect_path(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,hash TEXT NOT NULL,state TEXT NOT NULL,result TEXT NOT NULL DEFAULT '',private INTEGER NOT NULL,expires REAL NOT NULL,updated REAL NOT NULL)"
        )
        self.conn.execute("UPDATE jobs SET state='unknown' WHERE state='running'")
        self.conn.commit()

    def get(self, key):
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        return dict(row) if row else None

    def start(self, job):
        self.conn.execute(
            "INSERT INTO jobs(id,hash,state,private,expires,updated) VALUES(?,?,'running',?,?,?)",
            (
                job["id"],
                job["argument_hash"],
                int(job.get("private", False)),
                job["expires"],
                time.time(),
            ),
        )
        self.conn.commit()

    def finish(self, key, state, result):
        row = self.get(key)
        encoded = (
            ""
            if row["private"]
            else self.cipher.encrypt(json.dumps(result, ensure_ascii=False).encode()).decode()
        )
        self.conn.execute(
            "UPDATE jobs SET state=?,result=?,updated=? WHERE id=?",
            (state, encoded, time.time(), key),
        )
        self.conn.commit()

    def result(self, row):
        return (
            json.loads(self.cipher.decrypt(row["result"].encode()))
            if row["result"]
            else {"message": "Private result was not persisted."}
        )

    def receipts(self):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM jobs WHERE state!='running' ORDER BY updated DESC LIMIT 200"
            )
        ]


class DesktopExecutor:
    def __init__(self, config, directory, vault, journal):
        self.config, self.directory, self.vault, self.journal = config, directory, vault, journal
        self.origin = server_url(config["server_url"], development=config.get("development", False))
        self.connection = None
        self.running = {}
        self.private_results = {}
        self.private_expiries = {}
        self.pending_receipts = set()
        self.effect_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.stopping = False
        self.locked = True
        self.http = None
        self.access = ""

    def capabilities(self):
        return {
            "protocol": 1,
            "native": self.config.get("native", []),
            "native_scope": self.config.get("native_scope", "personal"),
            "locked": self.locked,
            "workspaces": [
                {k: w.get(k) for k in ("id", "label", "scope", "read", "write", "command")}
                for w in self.config.get("workspaces", [])
            ],
        }

    def authorize(self, job):
        if job.get("operation") not in OPERATIONS or time.time() >= job["expires"]:
            raise PermissionError("Operation is unsupported or expired.")
        args = job["arguments"]
        if digest([self.config["device_id"], job["operation"], args]) != job["argument_hash"]:
            raise PermissionError("Operation arguments changed.")
        if job["operation"] in NATIVE_OPERATIONS:
            if job["scope"] != self.config.get("native_scope") or job[
                "operation"
            ] not in self.config.get("native", []):
                raise PermissionError("Native capability was not granted locally in this scope.")
            return None, None
        grant = next(
            (
                w
                for w in self.config.get("workspaces", [])
                if w["id"] == args.get("workspace") and w["scope"] == job["scope"]
            ),
            None,
        )
        permission = (
            "command"
            if job["operation"] == "workspace_command"
            else "write"
            if job["operation"] in {"workspace_write", "workspace_mkdir"}
            else "read"
        )
        if not grant or grant.get(permission) is not True:
            raise PermissionError("Local workspace permission was not granted.")
        for field in ("path", "cwd"):
            value = args.get(field, ".")
            if (
                not isinstance(value, str)
                or "\x00" in value
                or Path(value).is_absolute()
                or PureWindowsPath(value).is_absolute()
                or ".." in re.split(r"[/\\]", value)
                or value.startswith("workspace:")
            ):
                raise PermissionError("Device paths must stay relative to the granted workspace.")
        workspace = Workspace([grant["path"]], protected=[self.directory])
        if job["operation"] == "workspace_command":
            command = args.get("command", "")
            if not isinstance(command, str) or re.search(r"[\r\n;&|<>`$]", command):
                raise PermissionError("Shell chains and substitutions are not permitted.")
            argv = shlex.split(command)
            allowed = [shlex.split(prefix) for prefix in grant.get("commands", [])]
            if not argv or not any(argv[: len(prefix)] == prefix for prefix in allowed if prefix):
                raise PermissionError(
                    "This command is outside the locally configured command prefixes."
                )
        return workspace, grant

    async def execute(self, job):
        workspace, grant = self.authorize(job)
        args, operation = job["arguments"], job["operation"]
        if operation in NATIVE_OPERATIONS:
            return await self.native_call(operation, args, job["expires"])
        path = args.get("path", ".")
        if operation == "workspace_read":
            import hashlib

            text = await asyncio.to_thread(workspace.read, path)
            return {
                "path": path,
                "text": text[:16000],
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "truncated": len(text) > 16000,
            }
        if operation == "workspace_list":
            return await asyncio.to_thread(workspace.list, path)
        if operation == "workspace_search":
            return await asyncio.to_thread(workspace.search, str(args.get("query", ""))[:500], path)
        if operation == "workspace_write":
            return await asyncio.to_thread(
                workspace.write, path, args.get("content", ""), args.get("expected_sha256")
            )
        if operation == "workspace_mkdir":
            return await asyncio.to_thread(workspace.mkdir, path)
        return await workspace.command(
            args["command"],
            args.get("cwd", "."),
            grant.get("command_mode", "approval"),
            min(600, max(1, int(job["expires"] - time.time()))),
        )

    def _win32_window_operation(self, operation: str, arguments: dict) -> dict:
        if operation == "window.list":
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            windows = []

            def enum_proc(hwnd, _lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buffer, length + 1)
                        title = buffer.value
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        windows.append({
                            "id": hwnd,
                            "app": title,
                            "title": title,
                            "bounds": {
                                "x": rect.left,
                                "y": rect.top,
                                "width": rect.right - rect.left,
                                "height": rect.bottom - rect.top,
                            },
                            "active": hwnd == user32.GetForegroundWindow(),
                        })
                return True

            enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(enum_type(enum_proc), 0)
            return {"frontmost": "", "apps": [], "windows": windows, "count": len(windows)}

        if operation == "window.action":
            action = str(arguments.get("action", "focus")).lower()
            url = arguments.get("url", "")
            if action == "open_url" and url:
                import webbrowser

                webbrowser.open(url)
                return {"action": "open_url", "url": url, "success": True}
            import ctypes

            user32 = ctypes.windll.user32
            app = arguments.get("app", "")
            hwnd = arguments.get("window_id")
            if not hwnd and app:
                hwnd = user32.FindWindowW(None, app)
            if hwnd:
                if action in {"focus", "activate"}:
                    user32.SetForegroundWindow(hwnd)
                    return {"action": "focus", "window_id": hwnd, "success": True}
                if action in {"close", "terminate"}:
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    return {"action": "close", "window_id": hwnd, "success": True}
            return {"action": action, "success": False, "message": "Target window not found."}
        raise ValueError(f"Unsupported Win32 operation: {operation}")

    async def native_call(self, operation, arguments=None, expires=None):
        if sys.platform == "win32" and operation in {"window.list", "window.action"}:
            return await asyncio.to_thread(self._win32_window_operation, operation, arguments or {})

        import hashlib

        helper = self.config.get("native_helper", "")
        if sys.platform != "darwin" or not helper:
            raise PermissionError("This native capability requires the configured macOS helper.")
        actual = await asyncio.to_thread(
            lambda: hashlib.sha256(Path(helper).read_bytes()).hexdigest()
        )
        if actual != self.config.get("native_helper_hash"):
            raise PermissionError("The native helper changed. Grant access again locally.")
        process = await asyncio.create_subprocess_exec(
            helper,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG"}},
        )
        try:
            deadline = expires or time.time() + 8
            async with asyncio.timeout(max(0.01, min(600, deadline - time.time()))):
                output, _ = await process.communicate(
                    json.dumps(
                        {"operation": operation, "arguments": arguments or {}, "expires": deadline}
                    ).encode()
                )
            if process.returncode or len(output) > 900_000:
                raise ValueError("Native helper failed or exceeded its output limit.")
            result = json.loads(output)
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError(str(result.get("error", "Invalid native result."))[:500])
            return result
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def update_native_status(self):
        if not self.config.get("native"):
            return
        try:
            self.locked = (await self.native_call("native.status")).get("locked", True)
        except Exception:
            self.locked = True

    async def send(self, value):
        async with self.send_lock:
            if self.connection:
                with contextlib.suppress(Exception):
                    await self.connection.send(json.dumps(value, ensure_ascii=False))

    async def receipt(self, row, kind="result"):
        for key, expires in list(self.private_expiries.items()):
            if expires < time.time():
                self.private_expiries.pop(key, None)
                self.private_results.pop(key, None)
        result = self.private_results.get(row["id"], self.journal.result(row))
        state = (
            "unknown" if row["private"] and row["id"] not in self.private_results else row["state"]
        )
        self.pending_receipts.add(row["id"])
        value = {
            "type": kind,
            "id": row["id"],
            "argument_hash": row["hash"],
            "state": state,
            "result": result,
        }
        if len(json.dumps(value).encode()) > 60_000:
            if self.http and self.access:
                try:
                    response = await self.http.post(
                        "/remote/v1/executor-results/" + row["id"],
                        json=value,
                        headers={"Authorization": "Bearer " + self.access},
                    )
                    response.raise_for_status()
                    self.acknowledge(row["id"])
                except httpx.HTTPError:
                    self.status("receipt_pending")
        else:
            await self.send(value)

    def acknowledge(self, key):
        self.pending_receipts.discard(key)
        self.private_results.pop(key, None)
        self.private_expiries.pop(key, None)

    async def handle(self, job):
        async with self.effect_lock:
            row = self.journal.get(job["id"])
            if row:
                if row["hash"] != job["argument_hash"]:
                    raise PermissionError("Job identifier reused with different arguments.")
                await self.receipt(row)
                return
            result, state = {}, "failed"
            try:
                self.authorize(job)
                self.journal.start(job)
                await self.send(
                    {"type": "claimed", "id": job["id"], "argument_hash": job["argument_hash"]}
                )
                async with asyncio.timeout(max(0.01, job["expires"] - time.time())):
                    result = await self.execute(job)
                if len(json.dumps(result, ensure_ascii=False).encode()) > (
                    850_000 if job["operation"] in NATIVE_OPERATIONS else 45_000
                ):
                    result = {"truncated": True, "preview": str(result)[:16000]}
                state = "succeeded"
            except (asyncio.CancelledError, TimeoutError):
                state, result = (
                    "unknown",
                    {"message": "Execution interrupted; verify its effects before retrying."},
                )
            except Exception as error:
                result = {"error": str(error)[:500]}
            if not self.journal.get(job["id"]):
                self.journal.start(job)
            if job.get("private"):
                self.private_results[job["id"]] = result
                self.private_expiries[job["id"]] = job["expires"] + 30
            self.journal.finish(job["id"], state, result)
            await self.receipt(self.journal.get(job["id"]))

    async def token(self, http):
        credentials = await asyncio.to_thread(self.vault.load)
        response = await http.post(
            "/remote/v1/refresh", json={"refresh_token": credentials["refresh_token"]}
        )
        if response.status_code != 200:
            raise PermissionError("Executor session expired or revoked. Pair again.")
        credentials.update(response.json())
        await asyncio.to_thread(self.vault.save, credentials)
        return credentials["access_token"]

    async def run(self):
        runner = asyncio.create_task(self.connect_loop())
        if os.getenv("JARVIS_EXECUTOR_MANAGED") == "1":
            import threading

            loop = asyncio.get_running_loop()

            def stop():
                self.stopping = True
                runner.cancel()

            def read_parent():
                try:
                    line = sys.stdin.readline()
                    if not line or json.loads(line).get("type") == "shutdown":
                        loop.call_soon_threadsafe(stop)
                except (ValueError, RuntimeError):
                    pass

            threading.Thread(target=read_parent, daemon=True).start()
        try:
            await runner
        finally:
            self.stopping = True
            for task in list(self.running.values()):
                task.cancel()
            if self.running:
                await asyncio.gather(*list(self.running.values()), return_exceptions=True)

    async def connect_loop(self):
        from websockets.asyncio.client import connect

        delay = 1
        async with httpx.AsyncClient(
            base_url=self.origin, trust_env=False, follow_redirects=False, timeout=15
        ) as http:
            self.http = http
            while not self.stopping:
                try:
                    token = await self.token(http)
                    self.access = token
                    url = (
                        self.origin.replace("https://", "wss://").replace("http://", "ws://")
                        + "/remote/v1/executor"
                    )
                    async with connect(
                        url,
                        max_size=64_000,
                        ping_interval=20,
                        ping_timeout=20,
                        open_timeout=10,
                        proxy=None,
                    ) as connection:
                        await connection.send(json.dumps({"type": "auth", "access_token": token}))
                        welcome = json.loads(await asyncio.wait_for(connection.recv(), 10))
                        if (
                            welcome.get("device_id") != self.config["device_id"]
                            or welcome.get("protocol") != 1
                        ):
                            raise PermissionError("Server device identity or protocol mismatch.")
                        self.connection, delay = connection, 1
                        self.status("connected")
                        await self.update_native_status()
                        await self.send({"type": "hello", "capabilities": self.capabilities()})
                        for row in self.journal.receipts():
                            await self.receipt(row, "reconcile")
                        refreshed = time.monotonic()
                        last_status = time.monotonic()
                        while not self.stopping:
                            if time.monotonic() - last_status > 15:
                                await self.update_native_status()
                                await self.send(
                                    {"type": "hello", "capabilities": self.capabilities()}
                                )
                                last_status = time.monotonic()
                                for key in list(self.pending_receipts):
                                    row = self.journal.get(key)
                                    if row:
                                        await self.receipt(row, "reconcile")
                            if time.monotonic() - refreshed > 200:
                                token = await self.token(http)
                                self.access = token
                                await self.send({"type": "auth", "access_token": token})
                                refreshed = time.monotonic()
                            try:
                                data = json.loads(await asyncio.wait_for(connection.recv(), 20))
                            except TimeoutError:
                                await self.send({"type": "ping"})
                                continue
                            if data.get("type") == "job":
                                key = data["id"]
                                if key not in self.running:
                                    self.running[key] = asyncio.create_task(self.handle(data))
                                    self.running[key].add_done_callback(
                                        lambda _, k=key: self.running.pop(k, None)
                                    )
                            elif data.get("type") == "cancel" and data.get("id") in self.running:
                                self.running[data["id"]].cancel()
                            elif data.get("type") == "receipt" and data.get("kind") in {
                                "result",
                                "reconcile",
                            }:
                                self.acknowledge(data["id"])
                except PermissionError:
                    self.status("pairing_required")
                    return
                except Exception:
                    if self.stopping:
                        break
                    self.status("reconnecting")
                finally:
                    self.connection = None
                    for task in list(self.running.values()):
                        task.cancel()
                    if self.running:
                        await asyncio.gather(*list(self.running.values()), return_exceptions=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    @staticmethod
    def status(state):
        print(json.dumps({"type": "executor.status", "state": state}), flush=True)


async def configure(directory, data):
    from .db import uid

    origin = server_url(data["server_url"], development=data.get("development", False))
    workspaces = []
    for value in data.get("workspaces", []):
        path = await asyncio.to_thread(
            lambda value=value: Path(value["path"]).expanduser().resolve(strict=True)
        )
        if (
            not path.is_dir()
            or path == Path.home()
            or path.parent == path
            or path == directory.resolve()
        ):
            raise ValueError(
                "Choose specific project directories, not the home, filesystem root or executor data."
            )
        if value.get("scope") not in {"personal", "work"}:
            raise ValueError("Choose a scope for every workspace.")
        command = value.get("command") is True
        if command and data.get("acknowledge_host_commands") is not True:
            raise PermissionError(
                "Host commands can execute project code with your user permissions. Explicit local acknowledgement is required."
            )
        workspaces.append(
            {
                "id": uid(),
                "label": str(value.get("label", path.name))[:80],
                "path": str(path),
                "scope": value["scope"],
                "read": value.get("read") is True,
                "write": value.get("write") is True,
                "command": command,
                "commands": value.get("commands", []),
                "command_mode": value.get("command_mode", "approval"),
            }
        )
    if not workspaces or len(workspaces) > 32:
        if len(workspaces) > 32 or not data.get("native"):
            raise ValueError(
                "Grant at least one workspace or native capability, with at most 32 workspaces."
            )
    native = data.get("native", [])
    if (
        not isinstance(native, list)
        or not set(native) <= NATIVE_OPERATIONS
        or data.get("native_scope", "personal") not in {"personal", "work"}
    ):
        raise ValueError("Invalid native grants.")
    native_config = {}
    if native:
        import hashlib

        helper = data.get("native_helper", "")
        if sys.platform != "darwin" or not helper:
            if not (sys.platform == "win32" and set(native) <= {"window.list", "window.action"}):
                raise PermissionError("Native calendar and window capabilities require macOS.")
        native_config = {
            "native": native,
            "native_scope": data.get("native_scope", "personal"),
            "native_helper": helper,
            "native_helper_hash": (
                await asyncio.to_thread(
                    lambda: hashlib.sha256(Path(helper).read_bytes()).hexdigest()
                )
                if helper and Path(helper).is_file()
                else ""
            ),
        }
        setup = DesktopExecutor(
            {"server_url": origin, "development": data.get("development", False), **native_config},
            directory,
            None,
            None,
        )
        if any(op.startswith("calendar.") for op in native):
            result = await setup.native_call("calendar.authorize", expires=time.time() + 120)
            if result.get("state") != "authorized":
                raise PermissionError("Calendar access was not granted locally.")
    async with httpx.AsyncClient(
        base_url=origin, trust_env=False, follow_redirects=False, timeout=15
    ) as http:
        response = await http.post(
            "/remote/v1/pair",
            json={
                "code": data["code"],
                "name": data.get("name", "Desktop executor"),
                "platform": "macos"
                if sys.platform == "darwin"
                else "windows"
                if os.name == "nt"
                else "linux",
            },
        )
        response.raise_for_status()
        credentials = response.json()
    if credentials.get("kind") != "executor":
        raise PermissionError("Use a pairing code issued specifically for an executor.")
    credentials["journal_key"] = Fernet.generate_key().decode()
    await asyncio.to_thread(CredentialVault(credentials["device_id"]).save, credentials)
    config = {
        "server_url": origin,
        "device_id": credentials["device_id"],
        "development": data.get("development", False),
        "workspaces": workspaces,
        **native_config,
    }
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "executor.json"
    path.write_text(json.dumps(config, indent=2))
    protect_path(path)
    return config


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Jarvis outbound desktop executor")
    parser.add_argument("--data-dir", type=Path, default=data_directory() / "executor")
    parser.add_argument(
        "--configure", action="store_true", help="Read enrollment and local grants from stdin JSON"
    )
    args = parser.parse_args()
    directory = args.data_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = ServiceLock(directory / "executor.lock")
    try:
        run_configured(directory, args.configure)
    finally:
        lock.close()


def run_configured(directory, setup):
    if setup:
        asyncio.run(configure(directory, json.load(sys.stdin)))
        print(json.dumps({"state": "configured"}))
        return
    config = json.loads((directory / "executor.json").read_text())
    vault = CredentialVault(config["device_id"])
    credentials = vault.load()
    journal = EffectJournal(
        directory / (config["device_id"] + ".sqlite3"), Fernet(credentials["journal_key"].encode())
    )
    executor = DesktopExecutor(config, directory, vault, journal)
    try:
        asyncio.run(executor.run())
    except KeyboardInterrupt:
        pass
    finally:
        journal.conn.close()


if __name__ == "__main__":
    main()
