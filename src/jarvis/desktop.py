"""Portable launcher: supervised local service and authenticated browser UI."""

from __future__ import annotations

import hashlib
import hmac
import json
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
            with client.stream(
                "GET", f"http://127.0.0.1:{config.settings.api_port}/health",
                params={"challenge": challenge},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 4096:
                        raise ValueError("Local service proof exceeds its size limit.")
                received = json.loads(body).get("proof", "")
                expected = health_proof(config.token, config.settings.api_port, challenge)
                if isinstance(received, str) and hmac.compare_digest(
                    received.encode(), expected.encode()
                ):
                    return True
    except httpx.ConnectError:
        return False
    except httpx.TimeoutException as error:
        raise RuntimeError(
            "Timed out verifying the local Jarvis port. Check JARVIS_API_PORT and the local listener; no token was sent."
        ) from error
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    raise RuntimeError(
        "The configured port is occupied by an unverified service. Stop it or configure another JARVIS_API_PORT; no token was sent."
    )


async def authorize_local_request(request: httpx.Request, *, config):
    """Verify a fresh peer proof before adding credentials to every CLI request."""
    port = config.settings.api_port
    if (request.url.scheme, request.url.host, request.url.port) != ("http", "127.0.0.1", port):
        raise ValueError("A local service request cannot leave its configured origin.")
    nonce = secrets.token_urlsafe(24)
    async with httpx.AsyncClient(timeout=6, trust_env=False) as probe:
        async with probe.stream(
            "GET", f"http://127.0.0.1:{port}/health", params={"challenge": nonce}
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 4096:
                    raise ValueError("Local service proof exceeds its size limit.")
    try:
        proof = json.loads(body).get("proof", "")
        valid = isinstance(proof, str) and hmac.compare_digest(
            proof.encode(), health_proof(config.token, port, nonce).encode()
        )
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Local service verification failed; no token was sent.")
    request.headers["Authorization"] = "Bearer " + config.token


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
            limit_concurrency=128,
            backlog=128,
            timeout_keep_alive=3,
            ws_max_size=128000,
            ws_max_queue=4,
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
