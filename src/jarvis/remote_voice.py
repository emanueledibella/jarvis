"""Companion Live transport: first-frame authentication, client-bound context."""

import asyncio
import contextlib
import json
from urllib.parse import urlsplit

from starlette.websockets import WebSocketDisconnect

from .feature_context import owner_session_guard
from .live_voice import LiveStart
from .remote_context import active_client


async def voice_socket(remote, websocket):
    origin = websocket.headers.get("origin")
    if (
        websocket.headers.get("host") != urlsplit(remote.options.public_url).netloc
        or origin not in {remote.options.public_url, *remote.options.allowed_origins}
    ):
        await websocket.close(code=1008)
        return
    marker = None
    guard = None
    monitor = None
    running = None
    await websocket.accept()
    try:
        remote.limit("voice-handshake", 60)
        raw = await asyncio.wait_for(websocket.receive_text(), 8)
        if len(raw) > 8192:
            raise ValueError("Invalid voice authentication.")
        auth = json.loads(raw)
        if not isinstance(auth, dict) or auth.get("type") != "authenticate":
            raise PermissionError("Voice authentication is required.")
        token = auth.get("access_token", "")
        device = await remote.store.authenticate(token)
        if device["kind"] != "companion" or not {"chat", "control"} <= set(device["scopes"]):
            raise PermissionError("Voice requires a companion with chat and control grants.")
        remote.limit("live:" + device["id"], 10)
        client = await remote.context(device, auth.get("session_id", ""))
        marker = active_client.set(client)
        guard = owner_session_guard.set((client.session["scope"], client.session["revision"]))
        raw = await asyncio.wait_for(websocket.receive_text(), 8)
        if len(raw) > 16384:
            raise ValueError("Invalid voice session.")
        metadata = LiveStart.model_validate_json(raw).model_copy(update={
            "client_device_id": client.device_id, "client_session_id": client.session_id,
        })
        remote.runtime.live_voice.validate(metadata)

        async def watch_authorization():
            while True:
                # Recheck rotation/expiry and device revocation during an open socket.
                await remote.store.authenticate(token)
                remote.runtime.live_voice.validate(metadata)
                await asyncio.sleep(.5)

        monitor = asyncio.create_task(watch_authorization())
        running = asyncio.create_task(remote.runtime.live_voice.serve(websocket, metadata))
        done, _ = await asyncio.wait({monitor, running}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except (ValueError, PermissionError, TimeoutError) as error:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json({"type": "error", "message": str(error)[:300]})
    except Exception:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json({"type": "error", "message": "Voice connection interrupted."})
    finally:
        for task in (monitor, running):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (monitor, running) if task), return_exceptions=True)
        if marker is not None:
            active_client.reset(marker)
        if guard is not None:
            owner_session_guard.reset(guard)
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close()
