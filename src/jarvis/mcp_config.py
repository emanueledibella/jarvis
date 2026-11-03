import json
import os
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Server(BaseModel):
    url: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    auth: str = "none"
    token: str = ""
    read_tools: list[str] = Field(default_factory=list)
    write_tools: list[str] = Field(default_factory=list)
    scope: Literal["personal", "work"] | None = None
    adapter: Literal["", "jira", "home_assistant"] = ""
    allow_insecure_lan: bool = False
    tls_ca_file: str = ""
    oauth_client_id: str = ""
    oauth_client_metadata_url: str = ""
    oauth_callback_port: int | None = Field(default=None, ge=1024, le=65535)

    @model_validator(mode="after")
    def valid(self):
        from urllib.parse import urlsplit

        if bool(self.url) == bool(self.command):
            raise ValueError("Choose an HTTP URL or a stdio command.")
        if self.url and (
            urlsplit(self.url).scheme not in {"http", "https"}
            or not urlsplit(self.url).hostname
            or urlsplit(self.url).username
        ):
            raise ValueError("Invalid MCP endpoint.")
        if self.url:
            from .network import home_assistant_endpoint, secure_endpoint

            self.url = (
                home_assistant_endpoint(self.url, self.allow_insecure_lan)
                if self.adapter == "home_assistant"
                else secure_endpoint(self.url)
            )
        if self.allow_insecure_lan and self.adapter != "home_assistant":
            raise ValueError(
                "The explicit LAN exception is only available to the Home Assistant adapter."
            )
        if self.tls_ca_file and (
            not os.path.isabs(self.tls_ca_file) or not os.path.isfile(self.tls_ca_file)
        ):
            raise ValueError("Choose an existing absolute CA certificate file.")
        if self.oauth_client_metadata_url:
            from .network import secure_endpoint

            self.oauth_client_metadata_url = secure_endpoint(self.oauth_client_metadata_url)
            if not self.oauth_client_metadata_url.startswith("https://") or urlsplit(
                self.oauth_client_metadata_url
            ).path in {"", "/"}:
                raise ValueError("OAuth client metadata requires an HTTPS document URL.")
        if self.command and not os.path.isabs(self.command):
            raise ValueError("The MCP command requires an absolute path.")
        if self.auth not in {"none", "bearer", "oauth"}:
            raise ValueError("Unsupported MCP authentication.")
        if set(self.read_tools) & set(self.write_tools):
            raise ValueError("Each tool must have exactly one risk classification.")
        return self


def load_mcp_config(config):
    path = config.settings.mcp_config_path
    if not path or not path.exists():
        return {"servers": {}}
    value = json.loads(path.read_text())
    if "encrypted_mcp_v1" in value:
        if not config._secret_cipher:
            raise PermissionError("The MCP credential encryption key is unavailable.")
        return json.loads(config._secret_cipher.decrypt(value["encrypted_mcp_v1"].encode()))
    if config.server_mode and config._secret_cipher and path.is_relative_to(config.data_dir):
        write_mcp_config(config, path, value)
    return value


def write_mcp_config(config, path, value):
    if config.server_mode and config._secret_cipher:
        value = {
            "encrypted_mcp_v1": config._secret_cipher.encrypt(json.dumps(value).encode()).decode()
        }
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(value, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temp.replace(path)


def save_mcp_config(config, data):
    if "mcp_config_path" in config.locked_fields():
        raise PermissionError(
            "The MCP file is managed by the environment. Edit that file or remove its environment setting to use the GUI."
        )
    servers = {}
    previous = load_mcp_config(config).get("servers", {})
    for name, spec in data.get("servers", {}).items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) or name == "second_brain":
            raise ValueError(
                "Server name is not allowed; configure Second Brain in its dedicated section."
            )
        # Listings omit secrets. Permission edits preserve existing credentials.
        old = previous.get(name, {})
        if config.server_mode and spec.get("command"):
            raise PermissionError("The remote core accepts HTTP MCP endpoints, not host commands.")
        if (
            config.server_mode
            and old.get("token")
            and spec.get("url", old.get("url")) != old.get("url")
            and not spec.get("token")
        ):
            raise PermissionError("Changing an MCP endpoint requires a new dedicated token.")
        servers[name] = Server.model_validate({**old, **spec}).model_dump()
    path = config.data_dir / "mcp-servers.json"
    write_mcp_config(config, path, {"servers": servers})
    config.update({"mcp_config_path": str(path)})
