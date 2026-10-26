"""Owner-configured lights, adapter boundaries, and scoped local control grants."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .db import uid
from .light_intent import matches_light_target, requested_light_change
from .platforms import protect_path
from .policy import digest


class LightChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool | None = Field(default=None, strict=True)
    brightness: int | None = Field(default=None, ge=0, le=100, strict=True)
    temperature_kelvin: int | None = Field(default=None, ge=1000, le=20000, strict=True)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def check(self):
        if all(getattr(self, field) is None for field in type(self).model_fields):
            raise ValueError("Specify power, brightness, white temperature, or a color.")
        if self.color is not None and self.temperature_kelvin is not None:
            raise ValueError("Choose color or white temperature for one change.")
        if self.brightness == 0 and self.on is True:
            raise ValueError("Zero brightness means off; it cannot also be on.")
        if self.color == "#000000" and self.on is True:
            raise ValueError("Black means off; it cannot also be on.")
        return self

    def normalized(self):
        values = self.model_dump(exclude_none=True)
        if values.get("brightness") == 0:
            values.pop("brightness")
            values["on"] = False
        elif values.get("color") == "#000000":
            values.pop("color")
            values["on"] = False
        elif self.on is None and values:
            values["on"] = True
        return values


class LightState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    on: bool = Field(strict=True)
    brightness: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    temperature_kelvin: float | None = Field(default=None, ge=1000, le=20000, allow_inf_nan=False)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    xy: list[float] | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("xy")
    @classmethod
    def valid_xy(cls, value):
        if value is not None and any(not math.isfinite(v) or not 0 <= v <= 1 for v in value):
            raise ValueError("Invalid reported color coordinates.")
        return value


def color_xy(color: str):
    value = int(color[1:], 16)
    channels = [((value >> shift) & 255) / 255 for shift in (16, 8, 0)]
    r, g, b = [((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in channels]
    x = r * 0.664511 + g * 0.154324 + b * 0.162028
    y = r * 0.283881 + g * 0.668433 + b * 0.047685
    z = r * 0.000088 + g * 0.072310 + b * 0.986039
    return [x / (x + y + z), y / (x + y + z)]


def parse_state(raw):
    try:
        return LightState.model_validate(raw).model_dump(exclude_none=True)
    except (ValidationError, TypeError, ValueError):
        raise ValueError("The lighting adapter returned an invalid state. No verified result is available.") from None


class MCPConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: str = Field(min_length=1, max_length=80)
    read_tool: str = Field(min_length=1, max_length=100)
    set_tool: str = Field(min_length=1, max_length=100)
    target: dict = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=lambda: {
        "on": "on", "brightness": "brightness", "temperature_kelvin": "temperature_kelvin", "color": "color",
    })
    state_fields: dict[str, str] = Field(default_factory=lambda: {
        "on": "on", "brightness": "brightness", "temperature_kelvin": "temperature_kelvin", "color": "color",
    })

    @model_validator(mode="after")
    def check(self):
        allowed = {"on", "brightness", "temperature_kelvin", "color"}
        if len(json.dumps(self.target)) > 2000 or len(self.target) > 10:
            raise ValueError("The MCP target configuration is too large.")
        for mapping in (self.fields, self.state_fields):
            if not set(mapping) <= allowed or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,79}", value) for value in mapping.values()):
                raise ValueError("Invalid lighting field mapping.")
        if len(set(self.fields.values())) != len(self.fields) or set(self.target) & set(self.fields.values()):
            raise ValueError("Lighting fields must be unique and cannot overwrite the configured target.")
        return self


class LightRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w .'-]+$")
    model: str = Field(default="", max_length=100)
    light_profile: Literal["white", "white_ambiance", "color_ambiance"] = "white_ambiance"
    connection: Literal["hue_bluetooth", "mcp"] = "hue_bluetooth"
    scope: Literal["personal", "work"] = "personal"
    voice_control: bool = False
    candidate_id: str | None = None
    mcp: MCPConnection | None = None
    min_kelvin: int = Field(default=2200, ge=1000, le=20000)
    max_kelvin: int = Field(default=6500, ge=1000, le=20000)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("Enter a light name.")
        return value.strip()

    @field_validator("model")
    @classmethod
    def valid_model(cls, value):
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value):
            raise ValueError("Use a model label without line breaks or control characters.")
        return value.strip()

    @model_validator(mode="after")
    def valid_range(self):
        if self.min_kelvin >= self.max_kelvin:
            raise ValueError("The minimum white temperature must be below the maximum.")
        return self


class Lighting:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path: Path = runtime.config.data_dir / "lights.json"
        self.devices: list[dict] = []
        self.candidates: dict[str, dict] = {}
        self.authorizations: dict[str, str] = {}
        self.revision = 0
        self.lock = asyncio.Lock()
        self.native_lock = asyncio.Lock()
        if self.path.exists():
            protect_path(self.path)
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(saved, list) or len(saved) > 50:
                raise ValueError("Invalid local lighting configuration.")
            for item in saved:
                # Validate private persisted data before it can reach any adapter.
                registration = LightRegistration.model_validate(item["registration"])
                UUID(item["id"])
                if registration.connection == "hue_bluetooth":
                    UUID(item["native_id"])
                self.devices.append({**item, "registration": registration.model_dump()})

    def _save(self):
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(self.devices, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)
        protect_path(self.path)
        self.revision += 1

    def _guard(self):
        if not self.runtime.config.settings.lighting_enabled:
            raise PermissionError("Lighting is disabled in Settings.")
        if self.runtime.gateway.blocked:
            raise PermissionError("Emergency stop is active.")

    @staticmethod
    def public(device):
        config = device["registration"]
        return {
            "id": device["id"], "name": config["name"], "model": config["model"],
            "light_profile": config["light_profile"], "connection": config["connection"],
            "scope": config["scope"], "voice_control": config["voice_control"],
            "capabilities": device["capabilities"],
        }

    def list(self, scope: str | None = None):
        return [self.public(item) for item in self.devices if scope is None or item["registration"]["scope"] == scope]

    def resolve(self, name: str = "", scope: str | None = None):
        choices = [item for item in self.devices if scope is None or item["registration"]["scope"] == scope]
        if not name.strip() and len(choices) == 1:
            return choices[0]
        match = [item for item in choices if item["id"] == name or item["registration"]["name"].casefold() == name.strip().casefold()]
        if len(match) != 1:
            raise ValueError("Choose a configured light by its exact name or ID. Nearby lights are not registered automatically.")
        return match[0]

    def tool_risk(self, device: str, scope: str, *, prompt: str = "", change: LightChange | None = None):
        self._guard()
        selected = self.resolve(device, scope)
        if not selected["registration"]["voice_control"]:
            return "external"
        requested = requested_light_change(prompt, self.runtime.config.settings.wake_phrase)
        if requested and change is not None:
            target, fields = requested
            choices = [item for item in self.devices if item["registration"]["scope"] == scope]
            matches = [item for item in choices if matches_light_target(target, item["registration"]["name"], only_light=len(choices) == 1)]
            try:
                expected, actual = LightChange(**fields).normalized(), change.normalized()
                if "color" in actual:
                    actual["color"] = actual["color"].upper()
                if len(matches) == 1 and matches[0]["id"] == selected["id"] and expected == actual:
                    return "lighting_direct"
            except ValidationError:
                pass
        return "lighting"

    async def _native(self, operation: str, arguments: dict, *, timeout=25):
        self._guard()
        revision = self.revision
        async with self.native_lock:
            self._guard()
            if revision != self.revision:
                raise PermissionError("The lighting operation was revoked or expired.")
            nonce = uid()
            payload = {**arguments, "lighting_authorization": nonce, "lighting_revision": self.revision}
            self.authorizations[nonce] = digest([operation, payload])
            try:
                return await self.runtime.native.invoke(operation, payload, timeout=timeout)
            finally:
                self.authorizations.pop(nonce, None)

    def authorize_native(self, operation: dict):
        self._guard()
        args = operation["arguments"]
        nonce = args.get("lighting_authorization")
        if args.get("lighting_revision") != self.revision or self.authorizations.get(nonce) != digest([operation["operation"], args]):
            raise PermissionError("The lighting operation was revoked or expired.")

    async def scan(self):
        response = await self._native("hue.scan", {}, timeout=50)
        self.candidates.clear()
        found = []
        for item in response.get("lights", [])[:30]:
            native_id = str(UUID(item["id"]))
            key = uid()
            name = str(item.get("name", "Hue light"))[:80].replace("\n", " ")
            self.candidates[key] = {"native_id": native_id, "expires": time.monotonic() + 300}
            found.append({"candidate_id": key, "name": name})
        return {"lights": found}

    def _mcp_policy(self, connection: MCPConnection):
        spec = self.runtime.mcp.specs().get(connection.server, {})
        if connection.read_tool not in spec.get("read_tools", []) or connection.set_tool not in spec.get("write_tools", []):
            raise PermissionError("Enable the selected MCP read and write tools in Connections first.")

    def configuration(self, device_id: str):
        device = self.resolve(device_id)
        return {"id": device["id"], **device["registration"]}

    async def add(self, registration: LightRegistration, existing_id: str | None = None):
        self._guard()
        async with self.lock:
            existing = self.resolve(existing_id) if existing_id else None
            others = [item for item in self.devices if item is not existing]
            if len(others) >= 50 or any(item["registration"]["name"].casefold() == registration.name.strip().casefold() for item in others):
                raise ValueError("Choose a unique light name; at most 50 lights can be configured.")
            native_id = None
            if registration.connection == "hue_bluetooth":
                candidate = self.candidates.get(registration.candidate_id, {})
                if registration.candidate_id and candidate.get("expires", 0) <= time.monotonic():
                    raise ValueError("Find nearby Hue lights again before pairing.")
                native_id = candidate.get("native_id") or (existing or {}).get("native_id")
                if not native_id:
                    raise ValueError("Find nearby Hue lights again before pairing.")
                if any(item.get("native_id") == native_id for item in others):
                    raise ValueError("This light is already configured.")
                result = await self._native("hue.inspect", {"device_id": native_id}, timeout=60)
                detected = result.get("capabilities", {})
            else:
                if registration.mcp is None:
                    raise ValueError("Configure the MCP connection and lighting tools.")
                self._mcp_policy(registration.mcp)
                for item in others:
                    previous = item["registration"].get("mcp")
                    if previous and all(previous.get(key) == getattr(registration.mcp, key) for key in ("server", "read_tool", "set_tool", "target")):
                        raise ValueError("This MCP lighting target is already configured. Edit its existing entry.")
                detected = {key: key in registration.mcp.fields for key in ("on", "brightness", "temperature_kelvin", "color")}
            profile = registration.light_profile
            capabilities = {
                "on": bool(detected.get("on")), "brightness": bool(detected.get("brightness")),
                "temperature_kelvin": profile != "white" and bool(detected.get("temperature_kelvin")),
                "color": profile == "color_ambiance" and bool(detected.get("color")),
                "min_kelvin": max(2000, registration.min_kelvin) if native_id else registration.min_kelvin,
                "max_kelvin": min(6500, registration.max_kelvin) if native_id else registration.max_kelvin,
            }
            if not capabilities["on"]:
                raise ValueError("The selected device does not expose a supported lighting control.")
            if capabilities["temperature_kelvin"] and capabilities["min_kelvin"] >= capabilities["max_kelvin"]:
                raise ValueError("The selected white temperature range is not supported by this connection.")
            registration.name = registration.name.strip()
            device = {"id": existing["id"] if existing else uid(), "registration": registration.model_dump(), "capabilities": capabilities}
            device["registration"]["candidate_id"] = None
            if native_id:
                device["native_id"] = native_id
            else:
                await self._mcp(device, None, self.runtime.config.settings.profile)
            if existing:
                self.devices[self.devices.index(existing)] = device
            else:
                self.devices.append(device)
            self._save()
            return self.public(device)

    async def remove(self, device_id: str):
        async with self.lock:
            device = self.resolve(device_id)
            self.devices.remove(device)
            self._save()
        return {"state": "removed"}

    async def grant(self, device_id: str, enabled: bool):
        async with self.lock:
            device = self.resolve(device_id)
            device["registration"]["voice_control"] = enabled
            self._save()
        return self.public(device)

    async def _mcp(self, device: dict, changes: dict | None, profile: str):
        connection = MCPConnection.model_validate(device["registration"]["mcp"])
        self._mcp_policy(connection)
        if changes is not None:
            if not set(changes) <= set(connection.fields):
                raise ValueError("The MCP mapping does not support the requested light settings.")
            payload = {**connection.target, **{connection.fields[key]: value for key, value in changes.items()}}
            result = await self._mcp_call(connection.server, connection.set_tool, payload, profile)
            if isinstance(result, dict) and (result.get("isError") or result.get("error")):
                raise ValueError("The MCP lighting tool reported an error; the light state is unconfirmed.")
        raw = await self._mcp_call(connection.server, connection.read_tool, connection.target, profile)
        if not isinstance(raw, dict):
            raise ValueError("The MCP state tool must return a JSON object with mapped state fields.")
        state = {}
        for key, path in connection.state_fields.items():
            value = raw
            for part in path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value is not None:
                state[key] = value
        # Arbitrary MCP text never becomes part of the trusted device result.
        return parse_state(state)

    async def _mcp_call(self, server, tool, arguments, profile):
        try:
            return await self.runtime.mcp.call(server, tool, arguments, profile)
        except Exception:
            # A remote exception is untrusted content and can contain credentials
            # or instructions. Only typed, validated light state reaches agents.
            raise ValueError("MCP lighting connection failed. Check the connection, profile, and tool policy.") from None

    async def state(self, name: str = "", scope: str | None = None, profile: str | None = None):
        self._guard()
        device = self.resolve(name, scope)
        if device["registration"]["connection"] == "hue_bluetooth":
            result = await self._native("hue.read", {"device_id": device["native_id"]})
            state = parse_state(result.get("light", {}))
        else:
            state = await self._mcp(device, None, profile or self.runtime.config.settings.profile)
        return {"device": self.public(device), "light": state}

    async def set(self, name: str, change: LightChange, scope: str | None = None, profile: str | None = None):
        self._guard()
        device = self.resolve(name, scope)
        values = change.normalized()
        caps = device["capabilities"]
        if any(not caps.get(key) for key in values):
            raise ValueError("This light model does not support the requested setting. White lights cannot change color; White Ambiance supports white temperature only.")
        if "temperature_kelvin" in values and not caps["min_kelvin"] <= values["temperature_kelvin"] <= caps["max_kelvin"]:
            raise ValueError("The white temperature is outside this light profile's supported range.")
        if device["registration"]["connection"] == "hue_bluetooth":
            result = await self._native("hue.write", {"device_id": device["native_id"], "changes": values})
            state = parse_state(result.get("light", {}))
        else:
            state = await self._mcp(device, values, profile or self.runtime.config.settings.profile)
        for field, expected in values.items():
            if field == "color":
                reported = state.get("xy")
                matches_xy = reported is not None and all(abs(a - b) <= 0.03 for a, b in zip(color_xy(expected), reported, strict=True))
                if not matches_xy and state.get("color", "").casefold() != expected.casefold():
                    raise ValueError("The color change is unconfirmed. Read the light state before trying again.")
            elif field in {"brightness", "temperature_kelvin"}:
                tolerance = 2 if field == "brightness" else 50
                if not isinstance(state.get(field), (int, float)) or abs(state[field] - expected) > tolerance:
                    raise ValueError("The light did not confirm the requested setting. Read its state before trying again.")
            elif state.get(field) is not expected:
                raise ValueError("The light did not confirm the requested power state.")
        return {"state": "verified", "device": self.public(device), "light": state}
