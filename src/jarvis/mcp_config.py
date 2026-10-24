import json
import os
import re

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

    @model_validator(mode="after")
    def valid(self):
        from urllib.parse import urlsplit

        if bool(self.url) == bool(self.command):
            raise ValueError("Scegli un URL HTTP oppure un comando stdio.")
        if self.url and (
            urlsplit(self.url).scheme not in {"http", "https"}
            or not urlsplit(self.url).hostname
            or urlsplit(self.url).username
        ):
            raise ValueError("Endpoint MCP non valido.")
        if self.command and not os.path.isabs(self.command):
            raise ValueError("Il comando MCP deve avere un percorso assoluto.")
        if self.auth not in {"none", "bearer", "oauth"}:
            raise ValueError("Autenticazione MCP non supportata.")
        if set(self.read_tools) & set(self.write_tools):
            raise ValueError("Un tool deve avere una sola classificazione di rischio.")
        return self


def save_mcp_config(config, data):
    if "mcp_config_path" in config.locked_fields():
        raise PermissionError(
            "Il file MCP è gestito da env. Modifica quel file oppure rimuovi il relativo parametro env per usare la GUI."
        )
    servers = {}
    current_path = config.settings.mcp_config_path
    previous = (
        json.loads(current_path.read_text()).get("servers", {})
        if current_path and current_path.exists()
        else {}
    )
    for name, spec in data.get("servers", {}).items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) or name == "second_brain":
            raise ValueError(
                "Nome server non ammesso; configura Second Brain nella sezione dedicata."
            )
        # Listings omit secrets. Permission edits preserve existing credentials.
        servers[name] = Server.model_validate({**previous.get(name, {}), **spec}).model_dump()
    path = config.data_dir / "mcp-servers.json"
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump({"servers": servers}, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temp.replace(path)
    config.update({"mcp_config_path": str(path)})
