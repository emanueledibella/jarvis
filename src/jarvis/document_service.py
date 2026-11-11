"""Unix-socket parser broker, deployed without network or the core data volume."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import struct
import sys
import tempfile
from pathlib import Path


async def parse_connection(reader, writer):
    process = None
    try:
        async with asyncio.timeout(30):
            size = struct.unpack("!I", await reader.readexactly(4))[0]
            if not 1 <= size <= 4_100_000:
                raise ValueError("Invalid document request size.")
            raw = await reader.readexactly(size)
            payload = json.loads(raw)
            if payload == {"health": True}:
                result = b'{"status":"ok"}'
            else:
                if set(payload) != {"name", "content"}:
                    raise ValueError("Unsupported worker operation.")
                with tempfile.TemporaryDirectory(prefix="document-worker-") as scratch:
                    process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "jarvis.document_worker",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        cwd=scratch,
                        start_new_session=True,
                        env={
                            "PATH": os.defpath,
                            "TMPDIR": scratch,
                            "PYTHONNOUSERSITE": "1",
                            "PYTHONDONTWRITEBYTECODE": "1",
                            "OMP_THREAD_LIMIT": "1",
                        },
                    )
                    result, _ = await process.communicate(raw)
                    if process.returncode != 0 or len(result) > 12_000_000:
                        raise ValueError("Document processing failed or exceeded its limits.")
            writer.write(struct.pack("!I", len(result)) + result)
            await writer.drain()
    except Exception:
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
        result = b'{"error":"Isolated document processing failed."}'
        writer.write(struct.pack("!I", len(result)) + result)
        with __import__("contextlib").suppress(Exception):
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def worker_request(socket_path, payload):
    async with asyncio.timeout(30):
        reader, writer = await asyncio.open_unix_connection(socket_path)
        try:
            data = json.dumps(payload).encode()
            writer.write(struct.pack("!I", len(data)) + data)
            await writer.drain()
            size = struct.unpack("!I", await reader.readexactly(4))[0]
            if not 1 <= size <= 12_000_000:
                raise ValueError("Invalid document result size.")
            result = json.loads(await reader.readexactly(size))
            if result.get("error"):
                raise ValueError("Isolated document processing failed.")
            return result
        finally:
            writer.close()
            await writer.wait_closed()


async def serve(socket_path):
    path = Path(socket_path)

    def prepare():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists():
            path.unlink()

    await asyncio.to_thread(prepare)
    semaphore = asyncio.Semaphore(1)

    async def bounded(reader, writer):
        async with semaphore:
            await parse_connection(reader, writer)

    server = await asyncio.start_unix_server(bounded, str(path), limit=4_100_000)
    await asyncio.to_thread(path.chmod, 0o600)
    async with server:
        await server.serve_forever()


def main():
    os.umask(0o077)
    asyncio.run(
        serve(os.environ.get("JARVIS_DOCUMENT_WORKER_SOCKET", "/run/jarvis-worker/parser.sock"))
    )


if __name__ == "__main__":
    main()
