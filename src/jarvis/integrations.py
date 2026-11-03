from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from fastmcp import Client
from fastmcp.client.auth import OAuth
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from .config import ConfigStore
from .memory_retrieval import SECOND_BRAIN_READ_TOOLS
from .platforms import process_environment


def oauth_store(directory, cipher=None):
    from key_value.aio._utils.sanitization import AlwaysHashStrategy
    from key_value.aio.stores.filetree import FileTreeStore

    # OAuth uses complete resource URLs as keys. Raw file names would interpret
    # URL slashes as directories; hashing also keeps keys within this store.
    store = FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=AlwaysHashStrategy(),
        collection_sanitization_strategy=AlwaysHashStrategy(),
    )
    if cipher:
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
        return FernetEncryptionWrapper(store, fernet=cipher)
    return store


class MCPHub:
    def __init__(self, config: ConfigStore):
        self.config = config
        self.statuses: dict[str, dict] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    def specs(self) -> dict[str, dict]:
        settings = self.config.settings
        value = {}
        if settings.mcp_config_path and settings.mcp_config_path.exists():
            from .mcp_config import load_mcp_config
            value = load_mcp_config(self.config).get("servers", {})
        if settings.second_brain_url:
            value["second_brain"] = {
                "url": settings.second_brain_url,
                "auth": settings.second_brain_auth,
                "token": settings.secret("second_brain_token"),
                "read_tools": sorted(SECOND_BRAIN_READ_TOOLS),
                "write_tools": ["remember"]
                + (
                    ["correct", "revise", "retract"]
                    if settings.second_brain_allow_corrections
                    else []
                ),
            }
        return value

    def allowed(self, spec: dict, profile: str):
        if self.config.server_mode and (spec.get("command") or spec.get("type") == "stdio"):
            raise PermissionError("The remote core does not launch stdio MCP commands. Configure an authenticated HTTP MCP endpoint.")
        from .policy import active_task
        ctx = active_task.get(None)
        if spec.get("scope") and ctx and spec["scope"] != ctx.scope:
            raise PermissionError("This MCP connection belongs to another scope.")
        if profile == "local_strict":
            # An arbitrary stdio server can itself call the network: do not claim strict
            # offline isolation unless its process is separately constrained.
            raise PermissionError("The strict local profile does not allow this MCP server.")

    def client(self, name: str, profile: str, *, interactive=False) -> Client:
        from dotenv import dotenv_values

        environment = {**dotenv_values(self.config.env_file), **os.environ}
        spec = self.specs().get(name)
        if not spec:
            raise ValueError("MCP server is not configured.")
        self.allowed(spec, profile)
        if spec.get("command"):
            minimal = {
                **process_environment(),
                "JARVIS_MCP_DIR": str(self.config.data_dir / "mcp" / name),
            }
            Path(minimal["JARVIS_MCP_DIR"]).mkdir(parents=True, exist_ok=True, mode=0o700)
            for key, value in spec.get("env", {}).items():
                match = re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*)\}", str(value))
                minimal[key] = environment.get(match[1], "") if match else str(value)
            transport = StdioTransport(
                spec["command"],
                spec.get("args", []),
                env=minimal,
                cwd=spec.get("cwd") or minimal["JARVIS_MCP_DIR"],
                keep_alive=False,
            )
            return Client(transport, timeout=30, init_timeout=10)
        auth = None
        client_factory = None
        if spec.get("adapter") == "home_assistant":
            from urllib.parse import urlsplit

            import httpx2
            origin = urlsplit(spec["url"])
            async def pinned_request(request):
                destination = urlsplit(str(request.url))
                if (destination.scheme, destination.hostname, destination.port) != (origin.scheme, origin.hostname, origin.port):
                    raise PermissionError("Home Assistant credentials cannot leave the configured origin.")
            def client_factory(*args, **kwargs):
                kwargs.update(trust_env=False, follow_redirects=False)
                if spec.get("tls_ca_file"):
                    import ssl
                    kwargs["verify"] = ssl.create_default_context(cafile=spec["tls_ca_file"])
                hooks = kwargs.pop("event_hooks", {})
                hooks["request"] = [*hooks.get("request", []), pinned_request]
                return httpx2.AsyncClient(*args, event_hooks=hooks, **kwargs)
        if spec.get("auth") == "oauth":
            directory = self.config.data_dir / "oauth" / name
            if self.config.server_mode:
                directory = directory / "remote"
            if name == "second_brain":
                directory = directory / (
                    "corrections"
                    if self.config.settings.second_brain_allow_corrections
                    else "ingest"
                )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            # OAuth browser interaction is only initiated by the explicit connect action.
            # Noninteractive clients use cached tokens; the browser callback is disabled
            # unless the owner deliberately starts the connection flow.
            auth = OAuth(
                spec["url"],
                client_name="Jarvis",
                scopes=(
                    ["memory:read", "memory:ingest"]
                    + (
                        ["memory:write"]
                        if self.config.settings.second_brain_allow_corrections
                        else []
                    )
                )
                if name == "second_brain"
                else None,
                token_storage=oauth_store(directory, self.config._secret_cipher),
                callback_timeout=180 if interactive else 1,
                **({"httpx_client_factory": client_factory} if client_factory else {}),
                **({"client_id": (self.remote_oauth.remote.options.public_url + "/" if self.config.server_mode and spec.get("adapter") == "home_assistant" and not spec.get("oauth_client_metadata_url") else spec["oauth_client_id"])} if spec.get("oauth_client_id") else {}),
                **({"client_metadata_url": spec["oauth_client_metadata_url"]} if spec.get("oauth_client_metadata_url") else {}),
                **({"callback_host": "127.0.0.1", "callback_port": spec["oauth_callback_port"]} if spec.get("oauth_callback_port") else {}),
            )
            if self.config.server_mode:
                auth = self.remote_oauth.bind(auth, name, spec, interactive=interactive)
            if not interactive:

                async def no_browser(*args, **kwargs):
                    raise PermissionError("Complete OAuth in Settings → Connect.")

                auth.redirect_handler = no_browser
                auth.context.redirect_handler = no_browser
            elif spec.get("adapter") == "home_assistant":
                original_redirect = auth.redirect_handler
                async def pinned_redirect(url):
                    destination = urlsplit(str(url))
                    if (destination.scheme, destination.hostname, destination.port) != (origin.scheme, origin.hostname, origin.port):
                        raise PermissionError("Home Assistant consent must use the configured server origin.")
                    await original_redirect(url)
                auth.redirect_handler = pinned_redirect
                auth.context.redirect_handler = pinned_redirect
        elif spec.get("auth") == "bearer":
            token = spec.get("token", "")
            if token.startswith("env:"):
                token = environment.get(token[4:], "")
            if not token:
                raise PermissionError("Configure this MCP server's dedicated token.")
            auth = token
        if client_factory:
            transport = StreamableHttpTransport(spec["url"], auth=auth, httpx_client_factory=client_factory)
            return Client(transport, timeout=30, init_timeout=180 if interactive else 10)
        return Client(spec["url"], auth=auth, timeout=30, init_timeout=180 if interactive else 10)

    async def discover(self, name: str, profile: str, *, interactive=False) -> list[dict]:
        try:
            async with self.locks.setdefault(name, asyncio.Lock()):
                async with self.client(name, profile, interactive=interactive) as client:
                    tools = await client.list_tools()
            spec = self.specs()[name]
            allowed = set(spec.get("read_tools", [])) | set(spec.get("write_tools", []))
            result = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "schema": t.input_schema,
                    "enabled": t.name in allowed,
                    "risk": "write" if t.name in spec.get("write_tools", []) else "read",
                }
                for t in tools
            ]
            self.statuses[name] = {"state": "connected", "tools": result}
            return result
        except Exception as error:
            self.statuses[name] = {"state": "error", "error": type(error).__name__}
            raise

    async def call(self, server: str, tool: str, arguments: dict, profile: str, *, expected_spec=None) -> dict:
        spec = self.specs().get(server, {})
        if tool not in set(spec.get("read_tools", [])) | set(spec.get("write_tools", [])):
            raise PermissionError("MCP tool is not included in the server policy.")
        async with self.locks.setdefault(server, asyncio.Lock()):
            from .policy import digest
            current = self.specs().get(server, {})
            if expected_spec is not None and digest(current) != expected_spec:
                raise PermissionError("MCP connection or permissions changed.")
            if tool not in set(current.get("read_tools", [])) | set(current.get("write_tools", [])):
                raise PermissionError("MCP tool permission was revoked.")
            async with self.client(server, profile) as client:
                result = await client.call_tool(
                    tool, arguments, timeout=self.config.settings.tool_timeout_seconds
                )
        self.statuses[server] = {**self.statuses.get(server, {}), "state": "connected"}
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            raise ValueError("The MCP service reported a tool failure. Verify the remote outcome before retrying a write.")
        data = getattr(result, "structured_content", None) or getattr(
            result, "structuredContent", None
        )
        if data is not None:
            return data
        if getattr(result, "data", None) is not None:
            return result.data
        texts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
        text = "\n".join(texts)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text[:64000]}


class NativeBridge:
    def __init__(self, db):
        self.db = db
        self.remote = None
        self.status: dict = {"connected": False, "voice_state": "unavailable"}
        self.last_seen = 0.0
        self.status_received_at = 0.0
        self.pending: dict[str, asyncio.Future] = {}
        self.operations: dict[str, dict] = {}
        self.claimed: set[str] = set()
        self.guards = {}
        self.calendar: dict = {"events": [], "state": "not_connected"}

    @property
    def connected(self):
        if self.remote:
            return self.remote.native_device() is not None
        return self.last_seen > 0 and time.monotonic() - self.last_seen < 45

    @property
    def status(self):
        return self.remote.native_status() if self.remote else self._status

    @status.setter
    def status(self, value):
        self._status = value

    def update_status(self, status: dict):
        self.status = status
        self.last_seen = self.status_received_at = time.monotonic()

    def claim(self, key: str, *, stopped=False):
        future = self.pending.get(key)
        operation = self.operations.get(key)
        if not future or future.done() or not operation or key in self.claimed:
            raise PermissionError(
                "The native operation expired, was cancelled, or was already claimed."
            )
        if stopped and operation["operation"] not in {"control.mute", "control.stop"}:
            raise PermissionError("Emergency stop is active.")
        guard = self.guards.get(key)
        if guard is not None:
            try:
                allowed = guard()
            except Exception:
                allowed = False
            if not allowed:
                error = PermissionError("Automatic voice recovery cancelled: listening state changed.")
                future.set_exception(error)
                raise error
        self.claimed.add(key)
        return operation

    async def invoke(self, operation: str, arguments: dict, timeout=30, *, guard=None):
        from .db import uid

        if self.remote:
            return await self.remote.invoke_native(operation, arguments, timeout, guard)
        if not self.connected:
            raise ValueError("Open the Jarvis app to use this native capability.")
        key = uid()
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        self.operations[key] = {"id": key, "operation": operation, "arguments": arguments}
        if guard is not None:
            self.guards[key] = guard
        try:
            await self.db.emit(
                "native.operation",
                {"id": key, "operation": operation, "arguments": {} if operation in {"document.ocr", "screen.capture"} else arguments},
                private=True,
            )
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(key, None)
            self.operations.pop(key, None)
            self.claimed.discard(key)
            self.guards.pop(key, None)

    def complete(self, key: str, result: dict):
        future = self.pending.get(key)
        if future and not future.done():
            guard = self.guards.get(key)
            if guard is not None and not guard():
                future.set_exception(PermissionError("Native operation discarded after authority changed."))
                return
            if result.get("error"):
                future.set_exception(ValueError(result["error"]))
            else:
                future.set_result(result)
