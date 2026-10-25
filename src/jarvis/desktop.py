"""Portable launcher: supervised local service and authenticated browser UI."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import webbrowser

import httpx


def health_proof(token: str, port: int, challenge: str) -> str:
    return hmac.new(
        token.encode(), f"jarvis-health:{port}:{challenge}".encode(), hashlib.sha256
    ).hexdigest()


def existing_service(config) -> bool:
    """Authenticate an existing listener without sending it the bearer token."""
    challenge = secrets.token_urlsafe(24)
    try:
        # Windows can take over a second to reject a closed loopback port.
        with httpx.Client(timeout=httpx.Timeout(2, connect=5), trust_env=False) as client:
            response = client.get(
                f"http://127.0.0.1:{config.settings.api_port}/health",
                params={"challenge": challenge},
            )
    except httpx.ConnectError:
        return False
    except httpx.TimeoutException as error:
        raise RuntimeError(
            "Timed out verifying the local Jarvis port. Check JARVIS_API_PORT and the local listener; no token was sent."
        ) from error
    try:
        response.raise_for_status()
        received = response.json().get("proof", "")
        expected = health_proof(config.token, config.settings.api_port, challenge)
        if isinstance(received, str) and hmac.compare_digest(received, expected):
            return True
    except (httpx.HTTPError, ValueError):
        pass
    raise RuntimeError(
        "The configured port is occupied by an unverified service. Stop it or configure another JARVIS_API_PORT; no token was sent."
    )


def open_dashboard(config):
    webbrowser.open(f"http://127.0.0.1:{config.settings.api_port}/#token={config.token}")


def launch(config, *, browser=True):
    import uvicorn

    from .api import create_app

    if not (config.settings.ui_dir / "index.html").is_file():
        raise ValueError(
            "The dashboard is missing. Build web with npm ci and npm run build before launching."
        )
    if existing_service(config):
        if browser:
            open_dashboard(config)
        print("Jarvis is already running with this configuration.")
        return
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host="127.0.0.1",
            port=config.settings.api_port,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    )

    def ready():
        deadline = time.monotonic() + 60
        while not server.should_exit and time.monotonic() < deadline:
            if server.started:
                if existing_service(config):
                    if browser:
                        open_dashboard(config)
                    return
            time.sleep(0.1)

    if browser:
        threading.Thread(target=ready, name="jarvis-dashboard", daemon=True).start()
    print("Jarvis is starting locally. Keep this window open; press Ctrl+C to quit.")
    server.run()
