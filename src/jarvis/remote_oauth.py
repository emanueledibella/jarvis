"""Relay standards-based SDK OAuth consent to a companion, never a server browser."""

import asyncio
import time
from urllib.parse import parse_qs, urlsplit

from fastapi import Request
from fastapi.responses import HTMLResponse
from mcp.shared.auth import AuthorizationCodeResult
from pydantic import AnyHttpUrl

from .remote_context import active_client


class RemoteOAuth:
    def __init__(self, remote):
        self.remote = remote
        self.pending = {}

    def bind(self, auth, name, spec, *, interactive):
        callback = self.remote.options.public_url + "/oauth/mcp/" + name + "/callback"
        auth.context.client_metadata.redirect_uris = [AnyHttpUrl(callback)]
        if auth._static_client_info:
            auth._static_client_info.redirect_uris = [AnyHttpUrl(callback)]
        auth.token_storage_adapter._cache_namespace = "remote:" + self.remote.options.public_url
        future = asyncio.get_running_loop().create_future()
        client = active_client.get()
        state_holder = {}

        async def redirect(url):
            if not interactive or not client or "admin" not in client.scopes:
                raise PermissionError("Complete this connection from an administrator companion.")
            parsed = urlsplit(str(url))
            if parsed.scheme != "https" or parsed.username or parsed.password:
                raise PermissionError("OAuth consent requires an HTTPS authorization endpoint.")
            state = parse_qs(parsed.query).get("state", [""])[0]
            if not state or len(state) > 512:
                raise PermissionError("OAuth provider did not supply a bounded state.")
            self.pending = {
                key: value
                for key, value in self.pending.items()
                if value["expires"] > time.monotonic() and not value["future"].done()
            }
            if len(self.pending) >= 10:
                raise ValueError("Too many pending authorization requests.")
            state_holder["state"] = state
            self.pending[state] = {
                "name": name,
                "url": str(url),
                "device_id": client.device_id,
                "expires": time.monotonic() + 180,
                "future": future,
            }

        async def receive():
            try:
                return await asyncio.wait_for(future, 180)
            finally:
                self.pending.pop(state_holder.get("state", ""), None)

        auth.redirect_handler = redirect
        auth.callback_handler = receive
        auth.context.redirect_handler = redirect
        auth.context.callback_handler = receive
        return auth

    def install(self, app):
        @app.get("/remote/v1/authorizations")
        async def pending(request: Request):
            device = request.state.remote_device
            if "admin" not in device["scopes"]:
                raise PermissionError("Authorization setup requires an administrator device.")
            return [
                {
                    "name": value["name"],
                    "url": value["url"],
                    "expires_in": max(0, int(value["expires"] - time.monotonic())),
                }
                for value in self.pending.values()
                if value["device_id"] == device["id"]
                and value["expires"] > time.monotonic()
                and not value["future"].done()
            ]

        @app.get("/oauth/mcp/{name}/callback")
        async def callback(
            name: str, state: str = "", code: str = "", error: str = "", iss: str = ""
        ):
            flow = self.pending.get(state)
            if (
                not flow
                or flow["name"] != name
                or flow["expires"] <= time.monotonic()
                or flow["future"].done()
            ):
                raise PermissionError("Authorization expired or was already used.")
            device = await self.remote.store.fetchone(
                "SELECT revoked FROM devices WHERE id=?", (flow["device_id"],)
            )
            if not device or device["revoked"]:
                raise PermissionError("The initiating device was revoked.")
            if error or not code or len(code) > 4096 or len(iss) > 2048:
                flow["future"].set_exception(
                    PermissionError("OAuth consent was denied or returned an invalid code.")
                )
                raise PermissionError("OAuth consent was not completed.")
            flow["future"].set_result(
                AuthorizationCodeResult(code=code, state=state, iss=iss or None)
            )
            return HTMLResponse(
                "<h1>Authorization received</h1><p>Return to Jarvis to check the connection. You may close this window.</p>"
            )
