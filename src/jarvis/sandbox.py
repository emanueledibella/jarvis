"""Bounded JSON-lines transport to disposable, network-disabled containers."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from uuid import uuid4

MAX_LINE = 96_000_000
IMAGES = {"python": "jarvis-python-sandbox:local", "browser": "jarvis-browser-sandbox:local"}


def small_host():
    profile = os.environ.get("JARVIS_SANDBOX_PROFILE", "standard")
    if profile not in {"standard", "small"}:
        raise ValueError("Sandbox profile must be standard or small.")
    return profile == "small"


class WorkerRejected(ValueError):
    """An operation rejected before any browser effect; a fresh snapshot can recover."""


class DockerWorker:
    def __init__(self, process, name, executable):
        self.process, self.name, self.executable = process, name, executable
        self.reader, self.writer = process.stdout, process.stdin

    @classmethod
    async def start(cls, kind):
        if kind not in IMAGES:
            raise ValueError("Unsupported sandbox.")
        executable = shutil.which("docker")
        if not executable:
            raise ValueError("Docker is unavailable. Configure the sandbox broker.")
        name = "jarvis-sandbox-" + uuid4().hex
        # Images/flags are operator configuration, never model-supplied arguments.
        image = os.environ.get("JARVIS_SANDBOX_" + kind.upper() + "_IMAGE", IMAGES[kind])
        memory, temporary, cpu = (384, 128, "0.6") if small_host() else (768, 256, "1")
        process = await asyncio.create_subprocess_exec(
            executable, "run", "--rm", "--pull=never", "--name", name,
            "--label", "it.jarvis.sandbox=true", "--network=none", "--read-only",
            "--user=10001:10001", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            f"--memory={memory}m", f"--memory-swap={memory}m", "--cpus=" + cpu, "--pids-limit=96",
            f"--tmpfs=/tmp:rw,nosuid,nodev,size={temporary}m,mode=1777", "-i", image,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=MAX_LINE,
        )
        return cls(process, name, executable)

    async def close(self):
        if self.writer:
            self.writer.close()
        # Killing the Docker client alone does not stop its container.
        with contextlib.suppress(Exception):
            async with asyncio.timeout(10):
                cleanup = await asyncio.create_subprocess_exec(
                    self.executable, "rm", "-f", self.name,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await cleanup.wait()
        if self.process.returncode is None:
            self.process.kill()
        await self.process.wait()


class RPC:
    def __init__(self, reader, writer, worker=None, fetch=None):
        self.reader, self.writer, self.worker, self.fetch = reader, writer, worker, fetch
        self.pending = {}
        self.fetches = set()
        self.write_lock = asyncio.Lock()
        self.lock = asyncio.Lock()
        self.closed = False
        self.pump = asyncio.create_task(self._pump())

    @classmethod
    async def open(cls, kind, socket_path="", fetch=None):
        if socket_path:
            reader, writer = await asyncio.open_unix_connection(socket_path, limit=MAX_LINE)
            try:
                writer.write(json.dumps({"kind": kind}).encode() + b"\n")
                await writer.drain()
                async with asyncio.timeout(10):
                    hello = json.loads(await reader.readline())
                if hello.get("ready") is not True:
                    raise ValueError(str(hello.get("error", "Sandbox broker is unavailable."))[:300])
                return cls(reader, writer, fetch=fetch)
            except BaseException:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                raise
        worker = await DockerWorker.start(kind)
        return cls(worker.reader, worker.writer, worker, fetch)

    async def send(self, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        if len(raw) > MAX_LINE - 1:
            raise ValueError("Sandbox input exceeds its limit.")
        async with self.write_lock:
            self.writer.write(raw + b"\n")
            await self.writer.drain()

    async def _fetch(self, message):
        try:
            if not self.fetch:
                raise PermissionError("Network access is disabled.")
            result = await self.fetch(message)
        except Exception:
            result = {"error": "Request blocked or unavailable."}
        if not self.closed:
            with contextlib.suppress(Exception):
                await self.send({"kind": "fetch_result", "id": message["id"], **result})

    async def _pump(self):
        try:
            while raw := await self.reader.readline():
                if len(raw) > MAX_LINE:
                    raise ValueError("Sandbox response exceeds its limit.")
                message = json.loads(raw)
                if message.get("kind") == "fetch":
                    if len(self.fetches) >= 8:
                        await self.send({"kind": "fetch_result", "id": message["id"], "error": "Too many requests."})
                    else:
                        job = asyncio.create_task(self._fetch(message))
                        self.fetches.add(job)
                        job.add_done_callback(self.fetches.discard)
                elif message.get("id") in self.pending:
                    future = self.pending[message["id"]]
                    if not future.done():
                        future.set_result(message)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ValueError("Sandbox stopped. Build the worker images and check Docker/broker availability."))

    async def request(self, payload, timeout=30):
        async with self.lock:
            if self.closed:
                raise ValueError("The sandbox session is closed.")
            key = uuid4().hex
            future = asyncio.get_running_loop().create_future()
            self.pending[key] = future
            try:
                async with asyncio.timeout(timeout):
                    await self.send({"kind": "action", "id": key, **payload})
                    result = await future
                if result.get("error"):
                    error = WorkerRejected if result.get("safe") is True else ValueError
                    raise error(result["error"][:300])
                return result.get("result", {})
            except WorkerRejected:
                raise
            except BaseException:
                await self.close()
                raise
            finally:
                self.pending.pop(key, None)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.pump.cancel()
        for job in list(self.fetches):
            job.cancel()
        await asyncio.gather(self.pump, *list(self.fetches), return_exceptions=True)
        if self.worker:
            await self.worker.close()
        else:
            self.writer.close()
            with contextlib.suppress(Exception):
                await self.writer.wait_closed()
