from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from fastmcp import Client
from fastmcp.client.auth import OAuth
from fastmcp.client.transports import StdioTransport

from .config import ConfigStore


def oauth_store(directory):
    from key_value.aio._utils.sanitization import AlwaysHashStrategy
    from key_value.aio.stores.filetree import FileTreeStore

    # OAuth uses complete resource URLs as keys. Raw file names would interpret
    # URL slashes as directories; hashing also keeps keys within this store.
    return FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=AlwaysHashStrategy(),
        collection_sanitization_strategy=AlwaysHashStrategy(),
    )


class MCPHub:
    def __init__(self, config: ConfigStore):
        self.config = config
        self.statuses: dict[str, dict] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    def specs(self) -> dict[str, dict]:
        settings = self.config.settings
        value = {}
        if settings.mcp_config_path and settings.mcp_config_path.exists():
            value = json.loads(settings.mcp_config_path.read_text()).get("servers", {})
        if settings.second_brain_url:
            value["second_brain"] = {
                "url": settings.second_brain_url,
                "auth": settings.second_brain_auth,
                "token": settings.secret("second_brain_token"),
                "read_tools": [
                    "recall",
                    "find_entities",
                    "read_source",
                    "explain",
                    "memory_status",
                    "source_status",
                    "recovery_jobs",
                    "history",
                    "knowledge_schema",
                    "reason_memory",
                ],
                "write_tools": ["remember"]
                + (
                    ["correct", "revise", "retract"]
                    if settings.second_brain_allow_corrections
                    else []
                ),
            }
        return value

    def allowed(self, spec: dict, profile: str):
        if profile == "local_strict":
            # An arbitrary stdio server can itself call the network: do not claim strict
            # offline isolation unless its process is separately constrained.
            raise PermissionError("Il profilo locale rigoroso non abilita questo server MCP.")

    def client(self, name: str, profile: str, *, interactive=False) -> Client:
        from dotenv import dotenv_values

        environment = {**dotenv_values(self.config.env_file), **os.environ}
        spec = self.specs().get(name)
        if not spec:
            raise ValueError("Server MCP non configurato.")
        self.allowed(spec, profile)
        if spec.get("command"):
            minimal = {
                "PATH": os.getenv("PATH", "/usr/bin:/bin"),
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
        if spec.get("auth") == "oauth":
            directory = self.config.data_dir / "oauth" / name
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
                token_storage=oauth_store(directory),
                callback_timeout=180 if interactive else 1,
            )
            if not interactive:

                async def no_browser(*args, **kwargs):
                    raise PermissionError("OAuth da completare in Impostazioni → Connetti.")

                auth.redirect_handler = no_browser
        elif spec.get("auth") == "bearer":
            token = spec.get("token", "")
            if token.startswith("env:"):
                token = environment.get(token[4:], "")
            if not token:
                raise PermissionError("Configura il token dedicato di questo server MCP.")
            auth = token
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

    async def call(self, server: str, tool: str, arguments: dict, profile: str) -> dict:
        spec = self.specs().get(server, {})
        if tool not in set(spec.get("read_tools", [])) | set(spec.get("write_tools", [])):
            raise PermissionError("Tool MCP non incluso nella policy del server.")
        async with self.locks.setdefault(server, asyncio.Lock()):
            async with self.client(server, profile) as client:
                result = await client.call_tool(
                    tool, arguments, timeout=self.config.settings.tool_timeout_seconds
                )
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
        self.status: dict = {"connected": False, "voice_state": "unavailable"}
        self.last_seen = 0.0
        self.pending: dict[str, asyncio.Future] = {}
        self.calendar: dict = {"events": [], "state": "not_connected"}

    @property
    def connected(self):
        import time

        return time.monotonic() - self.last_seen < 45

    async def invoke(self, operation: str, arguments: dict, timeout=30):
        from .db import uid

        if not self.connected:
            raise ValueError("Apri l'app Jarvis per utilizzare questa capacità nativa.")
        key = uid()
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            await self.db.emit(
                "native.operation",
                {"id": key, "operation": operation, "arguments": arguments},
                private=True,
            )
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(key, None)

    def complete(self, key: str, result: dict):
        future = self.pending.get(key)
        if future and not future.done():
            if result.get("error"):
                future.set_exception(ValueError(result["error"]))
            else:
                future.set_result(result)
