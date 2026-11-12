"""Explicit, supervised Caddy / Cloudflare Quick Tunnel lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
import socket
import tempfile
from pathlib import Path

from .platforms import process_environment, protect_path
from .telephony_process import child_command
from .telephony_settings import configuration_error, requirement_labels

QUICK_URL = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com(?=[\s|\"/]|$)")
PUBLIC_READY_TIMEOUT = 90


def executable(name: str) -> str | None:
    # Finder-launched apps do not normally inherit the Homebrew PATH.
    path = os.pathsep.join(
        [os.environ.get("PATH", os.defpath), "/opt/homebrew/bin", "/usr/local/bin"]
    )
    return shutil.which(name, path=path)


def caddy_config(api_port: int, proxy_port: int) -> str:
    return """{
	admin off
	auto_https off
	grace_period 2s
	servers {
		timeouts {
			read_header 5s
			read_body 10s
			idle 30s
		}
	}
}

:PROXY_PORT {
	bind 127.0.0.1
	@phone {
		path /telephony/voice /telephony/status
		method POST
	}
	handle @phone {
		request_body {
			max_size 16KB
		}
		reverse_proxy 127.0.0.1:API_PORT {
			transport http {
				max_conns_per_host 8
				response_header_timeout 10s
			}
		}
	}
	@media {
		path /telephony/media
		method GET
	}
	handle @media {
		reverse_proxy 127.0.0.1:API_PORT {
			transport http {
				max_conns_per_host 8
				response_header_timeout 10s
			}
		}
	}
	handle {
		respond "Not found" 404
	}
}
""".replace("API_PORT", str(api_port)).replace("PROXY_PORT", str(proxy_port))


class TelephonyTunnel:
    def __init__(self, phone):
        self.phone = phone
        self.runtime = phone.runtime
        self.state = "stopped"
        # A remote core keeps its stable HTTPS ingress across restarts. Local
        # Quick Tunnels must still be explicitly recreated on every launch.
        settings = self.runtime.config.settings
        if (
            self.runtime.config.server_mode
            and settings.telephony_tunnel_mode == "managed"
            and settings.telephony_enabled
            and not phone.ready(transport=False)[1]
        ):
            self.state = "running"
        self.url = ""
        self.error = ""
        self.inbound_configured = self.state == "running" and settings.phone_inbound_enabled
        self.proxy_port: int | None = None
        self.lock = asyncio.Lock()
        self.job: asyncio.Task | None = None
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.readers: list[asyncio.Task] = []
        self.directory = None
        self.caddy_ready = asyncio.Event()
        self.url_ready = asyncio.Event()
        self.cloud_connected = False

    def status(self):
        settings = self.runtime.config.settings
        return {
            "mode": settings.telephony_tunnel_mode,
            "hosting": "remote" if self.runtime.remote else "local",
            "state": self.state,
            "public_url": self.phone.public_base_url,
            "error": self.error,
            "dependencies": None if self.runtime.remote else {
                name: bool(executable(name)) for name in ("caddy", "cloudflared")
            },
            "requirements": requirement_labels(
                self.phone.ready(transport=False)[1], settings.ui_language
            ),
            "inbound_configured": self.inbound_configured,
        }

    async def start(self):
        async with self.lock, self.phone.lock:
            if self.job and not self.job.done():
                return self.status()
            config = self.runtime.config
            if self.runtime.gateway.blocked or config.settings.profile == "local_strict":
                raise PermissionError(
                    "Telephony is unavailable while stopped or in the local-only profile."
                )
            if self.runtime.remote and self.state == "running" and self.phone.ready()[0]:
                return self.status()
            changes = {"telephony_tunnel_mode": "managed", "telephony_enabled": True}
            if any(
                key in config.locked_fields() and getattr(config.settings, key) != value
                for key, value in changes.items()
            ):
                raise PermissionError("Telephony controls are locked by the environment.")
            _, missing = self.phone.ready(transport=False)
            if self.runtime.remote and not self.runtime.remote.options.public_url.startswith("https://"):
                missing.append("public_https_url")
            if missing:
                raise configuration_error(missing, config.settings.ui_language)
            if await self.phone.db.fetchone(
                "SELECT id FROM calls WHERE state IN ('creating','queued','initiated','ringing','answered','in-progress','connected','unknown') LIMIT 1"
            ):
                raise ValueError("End or reconcile the current call before starting the tunnel.")
            if self.runtime.remote:
                config.update(changes)
                self.state, self.error = "starting", ""
                self.inbound_configured = False
                self.job = asyncio.create_task(self._run_remote())
                return self.status()
            binaries = {name: executable(name) for name in ("caddy", "cloudflared")}
            if not all(binaries.values()):
                raise ValueError(
                    "Install Caddy and cloudflared before activating managed telephony."
                )
            config.update(changes)
            self.state, self.error, self.url = "starting", "", ""
            self.inbound_configured = False
            self.caddy_ready.clear()
            self.url_ready.clear()
            self.cloud_connected = False
            self.job = asyncio.create_task(self._run(binaries))
            return self.status()

    async def _run_remote(self):
        try:
            await self.phone.check_reachability()
            self.inbound_configured = await self.phone.configure_inbound_webhooks()
            self.state, self.error = "running", ""
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.state = "error"
            self.error = str(error) if isinstance(error, ValueError) else (
                "Could not activate telephony on the remote core. Check its public HTTPS connection."
            )
            self.inbound_configured = False
            config = self.runtime.config
            if "telephony_enabled" not in config.locked_fields():
                config.update({"telephony_enabled": False})
        await self.runtime.db.emit(
            "telephony.updated", {"state": self.state, "error": self.error}
        )

    async def stop(self) -> None:
        async with self.lock:
            if self.job and not self.job.done():
                self.state, self.url = "stopping", ""
                self.job.cancel()
                await asyncio.gather(self.job, return_exceptions=True)
            self.job = None
            self.state, self.url, self.error = "stopped", "", ""
            self.inbound_configured = False

    async def _spawn(self, name: str, arguments: list[str]):
        environment = process_environment()
        environment["XDG_DATA_HOME"] = str(Path(self.directory.name) / "data")
        environment["XDG_CONFIG_HOME"] = str(Path(self.directory.name) / "config")
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *child_command(arguments),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.directory.name,
                env=environment,
                start_new_session=os.name != "nt",
            )
        )
        try:
            process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            # Claim a child even if cancellation arrives during OS process creation.
            self.processes[name] = await spawning
            raise
        self.processes[name] = process
        self.readers.append(asyncio.create_task(self._read_output(name, process)))
        return process

    async def _read_output(self, name, process):
        while line := await process.stdout.readline():
            # Drain continuously, but retain neither raw logs nor request data.
            text = line.decode("utf-8", errors="replace")
            if name == "caddy" and "serving initial configuration" in text:
                self.caddy_ready.set()
            if name == "cloudflared" and self.state == "starting":
                if not self.url:
                    match = QUICK_URL.search(text)
                    if match:
                        self.url = match[0]
                if "Registered tunnel connection" in text:
                    self.cloud_connected = True
                if self.url and self.cloud_connected:
                    self.url_ready.set()

    async def _wait_ready(self, event, process, timeout, message):
        ready = asyncio.create_task(event.wait())
        exited = [asyncio.create_task(child.wait()) for child in self.processes.values()]
        try:
            done, _ = await asyncio.wait(
                [ready, *exited], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if ready not in done or any(
                child.returncode is not None for child in self.processes.values()
            ):
                raise ValueError(message)
        finally:
            ready.cancel()
            for wait in exited:
                wait.cancel()
            await asyncio.gather(ready, *exited, return_exceptions=True)

    async def _verify_public_url(self):
        try:
            # Quick Tunnel DNS may lag the printed URL; macOS can retain the
            # first negative lookup for longer than the tunnel handshake.
            async with asyncio.timeout(PUBLIC_READY_TIMEOUT):
                while True:
                    if any(process.returncode is not None for process in self.processes.values()):
                        raise ValueError(
                            "A telephony process stopped unexpectedly. Activate telephony again."
                        )
                    try:
                        await self.phone.check_reachability()
                        return
                    except ValueError:
                        await asyncio.sleep(1)
        except TimeoutError:
            raise ValueError(
                "The new Cloudflare tunnel could not reach this Jarvis instance."
            ) from None

    async def _run(self, binaries):
        failure = ""
        waits = []
        try:
            self.directory = tempfile.TemporaryDirectory(
                prefix="telephony-", dir=self.runtime.config.data_dir
            )
            directory = Path(self.directory.name)
            protect_path(directory, directory=True)
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                self.proxy_port = available.getsockname()[1]
            caddyfile = directory / "Caddyfile"
            caddyfile.write_text(
                caddy_config(self.runtime.config.settings.api_port, self.proxy_port)
            )
            protect_path(caddyfile)
            cloud_config = directory / "cloudflared.yml"
            cloud_config.write_text("{}\n")
            protect_path(cloud_config)
            caddy = await self._spawn(
                "caddy",
                [binaries["caddy"], "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
            )
            await self._wait_ready(
                self.caddy_ready, caddy, 15, "Caddy could not start the local telephony proxy."
            )
            cloud = await self._spawn(
                "cloudflared",
                [
                    binaries["cloudflared"],
                    "tunnel",
                    "--config",
                    str(cloud_config),
                    "--no-autoupdate",
                    "--metrics",
                    "127.0.0.1:0",
                    "--grace-period",
                    "2s",
                    "--url",
                    f"http://127.0.0.1:{self.proxy_port}",
                ],
            )
            await self._wait_ready(
                self.url_ready,
                cloud,
                45,
                "Cloudflare did not create a public tunnel. Check your connection and try again.",
            )
            await self._verify_public_url()
            self.inbound_configured = await self.phone.configure_inbound_webhooks()
            if any(process.returncode is not None for process in self.processes.values()):
                raise ValueError(
                    "A telephony process stopped unexpectedly. Activate telephony again."
                )
            self.state = "running"
            await self.runtime.db.emit("telephony.updated", {"state": self.state})
            waits = [asyncio.create_task(process.wait()) for process in self.processes.values()]
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            failure = "A telephony process stopped unexpectedly. Activate telephony again."
        except asyncio.CancelledError:
            raise
        except ValueError as error:
            failure = str(error)
        except Exception:
            failure = "Could not start the telephony processes. Check Caddy and cloudflared."
        finally:
            self.state = "stopping"
            self.url = ""
            for wait in waits:
                wait.cancel()
            await asyncio.gather(*waits, return_exceptions=True)
            await self._cleanup()
            self.inbound_configured = False
            self.state, self.error = ("error", failure) if failure else ("stopped", "")
            await self.runtime.db.emit(
                "telephony.updated", {"state": self.state, "error": self.error}
            )

    async def _cleanup(self):
        async def close(process):
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                await process.wait()

        await asyncio.gather(*(close(process) for process in self.processes.values()))
        self.processes.clear()
        for reader in self.readers:
            reader.cancel()
        await asyncio.gather(*self.readers, return_exceptions=True)
        self.readers.clear()
        self.proxy_port = None
        if self.directory:
            self.directory.cleanup()
            self.directory = None
