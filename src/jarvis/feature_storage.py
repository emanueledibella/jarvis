"""Private atomic storage and bounded HTTP for optional integrations."""
from __future__ import annotations

import json
import os
import tempfile

import httpx


def load_private(config, name):
    path = config.data_dir / name
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise PermissionError("Invalid private integration storage.")
    value = json.loads(path.read_text())
    if isinstance(value, dict) and set(value) == {"__jarvis_cipher_v1"}:
        from cryptography.fernet import Fernet
        cipher = config._secret_cipher or Fernet((config.data_dir / "server-secret.key").read_bytes())
        return json.loads(cipher.decrypt(value["__jarvis_cipher_v1"].encode()))
    if config._secret_cipher:
        save_private(config, name, value)
    return value


def save_private(config, name, value):
    if config._secret_cipher:
        value = {"__jarvis_cipher_v1": config._secret_cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()}
    fd, filename = tempfile.mkstemp(prefix=".feature-", dir=config.data_dir)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(filename, config.data_dir / name)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


async def bounded_json(method, url, **kwargs):
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, url, **kwargs) as response:
                if not 200 <= response.status_code < 300:
                    raise ValueError(f"Integration request failed (HTTP {response.status_code}).")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError("Integration response exceeds its size limit.")
                return json.loads(raw) if raw else {}
    except httpx.HTTPError:
        raise ValueError("Integration connection failed; verify the account and network.") from None
