from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .platforms import (
    SOURCE_ROOT,
    data_directory,
    default_env_file,
    frozen,
    protect_path,
    ui_directory,
)
from .voice_style import ITALIAN_COMPANION

ROOT = SOURCE_ROOT
Profile = Literal["local_strict", "local_connected", "cloud", "hybrid"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_", extra="ignore", env_file_encoding="utf-8"
    )
    data_dir: Path = Field(default_factory=data_directory)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8765, ge=1024, le=65535)
    timezone: str = "Europe/Rome"
    language: str = "it-IT"
    response_language: str = Field(
        default="auto", pattern=r"^(?:auto|[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*)$"
    )
    profile: Profile = "local_connected"
    cloud_provider: Literal["openai", "anthropic", "openai_compatible"] = "openai"
    cloud_model: str = ""
    cloud_base_url: str = ""
    cloud_api_key: SecretStr = SecretStr("")
    cloud_reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    local_provider: Literal["ollama", "openai_compatible"] = "ollama"
    local_base_url: str = "http://127.0.0.1:11434"
    local_model: str = ""
    local_reasoning: bool = False
    local_context_tokens: int = Field(default=16384, ge=4096, le=131072)
    local_api_key: SecretStr = SecretStr("")
    allow_cloud_fallback: bool = False
    model_request_timeout_seconds: int = Field(default=90, ge=5, le=600)
    max_output_tokens: int = Field(default=4000, ge=128, le=32000)
    max_agent_steps: int = Field(default=40, ge=5, le=200)
    max_parallel_tasks: int = Field(default=2, ge=1, le=8)
    task_timeout_seconds: int = Field(default=1800, ge=30, le=14400)
    tool_timeout_seconds: int = Field(default=30, ge=1, le=600)
    workspace_roots: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [] if frozen() else [str(ROOT)]
    )
    command_execution: Literal["disabled", "approval", "sandbox"] = "approval"
    command_timeout_seconds: int = Field(default=120, ge=1, le=600)
    mcp_config_path: Path | None = None
    second_brain_url: str = ""
    second_brain_token: SecretStr = SecretStr("")
    second_brain_auth: Literal["bearer", "oauth", "none"] = "bearer"
    second_brain_allow_corrections: bool = False
    memory_capture: Literal["explicit_only", "explicit_facts", "off"] = "explicit_only"
    memory_recall_token_budget: int = Field(default=2000, ge=256, le=10000)
    voice_enabled: bool = True
    desktop_voice_provider: Literal["apple", "openai_live"] = "apple"
    desktop_voice_model: str = "gpt-live-1"
    desktop_voice_name: str = "cedar"
    desktop_voice_style: str = Field(default=ITALIAN_COMPANION, max_length=2000)
    desktop_voice_duplex: Literal["gated", "full"] = "gated"
    desktop_voice_api_key: SecretStr = SecretStr("")
    desktop_voice_max_session_seconds: int = Field(default=120, ge=15, le=900)
    desktop_voice_idle_seconds: int = Field(default=30, ge=5, le=120)
    desktop_voice_rate_usd_per_minute: float = Field(default=0.05, gt=0, le=5)
    wake_enabled: bool = True
    wake_phrase: str = Field(default="Jarvis", min_length=2, max_length=40)
    followup_seconds: int = Field(default=8, ge=0, le=60)
    listen_timeout_seconds: int = Field(default=10, ge=2, le=120)
    end_of_turn_ms: int = Field(default=900, ge=300, le=4000)
    tts_voice: str = ""
    voice_on_lock_screen: bool = False
    weather_location: str = ""
    weather_latitude: float | None = Field(default=None, ge=-90, le=90)
    weather_longitude: float | None = Field(default=None, ge=-180, le=180)
    weather_refresh_minutes: int = Field(default=20, ge=5, le=180)
    calendar_provider: Literal["disabled", "apple", "ics", "google", "microsoft"] = "disabled"
    calendar_ics_url: str = ""
    calendar_access_token: SecretStr = SecretStr("")
    calendar_refresh_token: SecretStr = SecretStr("")
    calendar_client_id: str = ""
    calendar_client_secret: SecretStr = SecretStr("")
    calendar_tenant_id: str = "common"
    search_provider: Literal["duckduckgo", "brave", "tavily"] = "duckduckgo"
    search_api_key: SecretStr = SecretStr("")
    quiet_hours: str = "22:00-08:00"
    transcript_retention_days: int = Field(default=30, ge=0, le=365)
    operation_log_retention_days: int = Field(default=30, ge=1, le=365)
    record_audio: Literal[False] = False
    monthly_budget_usd: float = Field(default=50, gt=0, le=10000)
    model_input_usd_per_million: float = Field(default=0, ge=0)
    model_output_usd_per_million: float = Field(default=0, ge=0)
    telephony_enabled: bool = False
    telephony_public_base_url: str = ""
    telephony_account_id: str = ""
    telephony_auth_token: SecretStr = SecretStr("")
    telephony_from_number: str = ""
    owner_phone_number: str = ""
    phone_pin: SecretStr = SecretStr("")
    phone_api_key: SecretStr = SecretStr("")
    phone_max_call_seconds: int = Field(default=180, ge=30, le=3600)
    phone_max_attempts: Literal[1] = 1
    phone_daily_budget_usd: float = Field(default=2, gt=0, le=100)
    phone_minute_rate_usd: float = Field(default=0.36, gt=0, le=10)
    phone_stt_provider: Literal["openai", "faster_whisper"] = "openai"
    phone_stt_model: str = "whisper-1"
    phone_tts_model: str = "tts-1"
    phone_tts_voice: str = "onyx"
    phone_local_tts_voice: str = ""
    phone_local_stt_model: str = "small"
    ui_dir: Path = Field(default_factory=ui_directory)

    @field_validator("data_dir", "ui_dir", "mcp_config_path", mode="before")
    @classmethod
    def expand_path(cls, value):
        return Path(value).expanduser().resolve() if value else None

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except KeyError:
            raise ValueError("Unknown time zone: use an IANA name such as Europe/Rome.") from None
        return value

    @field_validator("cloud_base_url", "second_brain_url")
    @classmethod
    def secure_endpoint(cls, value):
        from urllib.parse import urlsplit

        from .network import loopback_url

        if value:
            parts = urlsplit(value)
            if (
                not parts.hostname
                or parts.username
                or parts.password
                or parts.fragment
                or (parts.scheme != "https" and not loopback_url(value))
            ):
                raise ValueError("Use HTTPS for remote servers or HTTP on loopback.")
        return value

    @field_validator("api_host")
    @classmethod
    def local_bind(cls, value):
        if value != "127.0.0.1":
            raise ValueError("Jarvis binds only to 127.0.0.1; use the dedicated telephony proxy.")
        return value

    @field_validator("allow_cloud_fallback")
    @classmethod
    def no_implicit_fallback(cls, value):
        if value:
            raise ValueError(
                "Automatic fallback is disabled. The hybrid profile selects its provider when the task starts."
            )
        return value

    @field_validator("workspace_roots", mode="before")
    @classmethod
    def parse_roots(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value.startswith("[") else value.split(",")
        return value

    @field_validator("quiet_hours")
    @classmethod
    def valid_quiet_hours(cls, value):
        from datetime import time

        if value:
            start, end = value.split("-")
            time.fromisoformat(start)
            time.fromisoformat(end)
        return value

    @model_validator(mode="after")
    def validate_location(self):
        if (self.weather_latitude is None) != (self.weather_longitude is None):
            raise ValueError("Set both weather coordinates.")
        return self

    def secret(self, field: str) -> str:
        value = getattr(self, field)
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        if raw.startswith("keychain:"):
            if sys.platform != "darwin":
                raise ValueError(
                    "macOS Keychain references are unavailable on this OS. Configure a key locally in Settings or the environment."
                )
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", "Jarvis", "-a", raw[9:], "-w"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        if not raw and field == "cloud_api_key":
            return os.getenv(
                "ANTHROPIC_API_KEY" if self.cloud_provider == "anthropic" else "OPENAI_API_KEY", ""
            )
        return raw

    def public(self) -> dict:
        value = self.model_dump(mode="json")
        for name in type(self).model_fields:
            if isinstance(getattr(self, name), SecretStr):
                value[name] = ""
                value[name + "_configured"] = bool(self.secret(name))
        return value


class ConfigStore:
    def __init__(self, env_file: str | Path | None = None, data_dir: Path | None = None):
        self.env_file = Path(env_file or os.getenv("JARVIS_ENV_FILE", default_env_file()))
        base = Settings(_env_file=self.env_file)
        self.data_dir = (data_dir or base.data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        protect_path(self.data_dir, directory=True)
        self.path = self.data_dir / "settings.json"
        if self.path.exists():
            protect_path(self.path)
        self.settings = self.load()
        self.token_path = self.data_dir / "api-token"
        try:
            fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
        protect_path(self.token_path)
        self.token = self.token_path.read_text().strip()
        if len(self.token) < 32:
            raise ValueError("Invalid local API token; remove its file to regenerate it.")

    def load(self) -> Settings:
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        # Process env > .env > private UI settings > defaults. Pydantic init kwargs normally
        # win over env, therefore merge saved settings only where no explicit environment value is present.
        env_settings = Settings(_env_file=self.env_file)
        explicit = env_settings.model_fields_set
        merged = {**saved, **{key: getattr(env_settings, key) for key in explicit}}
        merged["data_dir"] = self.data_dir
        return Settings(_env_file=None, **merged)

    def update(self, changes: dict) -> Settings:
        forbidden = {"data_dir", "api_host", "api_port", "ui_dir", "record_audio"}
        unknown = set(changes) - set(Settings.model_fields)
        if unknown or forbidden.intersection(changes):
            raise ValueError("Unknown setting or setting that cannot be changed while running.")
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        candidate = {**saved, **changes}
        Settings(_env_file=None, **{**self.settings.model_dump(), **changes})
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(candidate, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        temp.replace(self.path)
        protect_path(self.path)
        self.settings = self.load()
        return self.settings

    def locked_fields(self) -> list[str]:
        return sorted(Settings(_env_file=self.env_file).model_fields_set - {"data_dir"})
