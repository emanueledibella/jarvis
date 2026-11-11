"""Trusted Docker broker. Only fixed worker kinds; no host paths, flags or images in RPC."""
import asyncio
import contextlib
import json
import os
from pathlib import Path

from .sandbox import MAX_LINE, DockerWorker, small_host


async def serve(path):
    target = Path(path)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True, mode=0o700)
    await asyncio.to_thread(target.unlink, missing_ok=True)
    slots = asyncio.Semaphore(1 if small_host() else 4)

    async def connection(reader, writer):
        worker = None
        jobs = []
        try:
            if slots.locked():
                writer.write(b'{"error":"Sandbox host is busy. Close an open browser or wait for the current job to finish."}\n')
                await writer.drain()
                return
            async with slots, asyncio.timeout(900):
                async with asyncio.timeout(5):
                    hello = json.loads(await reader.readline())
                if set(hello) != {"kind"}:
                    raise ValueError("Invalid sandbox request.")
                worker = await DockerWorker.start(hello["kind"])
                writer.write(b'{"ready":true}\n')
                await writer.drain()

                async def copy(source, destination):
                    while raw := await source.readline():
                        if len(raw) > MAX_LINE:
                            raise ValueError("Sandbox input exceeds its limit.")
                        destination.write(raw)
                        await destination.drain()

                jobs = [asyncio.create_task(copy(reader, worker.writer)),
                        asyncio.create_task(copy(worker.reader, writer))]
                await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        except Exception:
            pass
        finally:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            if worker:
                await worker.close()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_unix_server(connection, path, limit=MAX_LINE)
    if os.getuid() == 0:
        await asyncio.to_thread(os.chown, target, 10001, 10001)
    await asyncio.to_thread(target.chmod, 0o660)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    os.umask(0o077)
    asyncio.run(serve(os.environ.get("JARVIS_SANDBOX_BROKER_SOCKET", "/run/jarvis-sandbox/broker.sock")))
