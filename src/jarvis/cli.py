from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import webbrowser
from functools import partial

import httpx
from pydantic import ValidationError

from .config import ConfigStore


def main():
    os.umask(0o077)
    # Tracing is opt-in product work; never inherit an unrelated agent's tracing secrets.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis personal assistant")
    parser.add_argument("--env-file")
    parser.add_argument("--version", action="version", version="Jarvis 0.1.0")
    sub = parser.add_subparsers(dest="command")
    desktop = sub.add_parser(
        "desktop", help="Start the portable service and open its dashboard (default)"
    )
    desktop.add_argument(
        "--no-browser", action="store_true", help="Start without opening a browser"
    )
    sub.add_parser("serve", help="Start the local service")
    sub.add_parser("status", help="Service status")
    sub.add_parser("doctor", help="Diagnostics and configuration without secrets")
    sub.add_parser("open", help="Open the dashboard in the browser")
    sub.add_parser("desktop-info", help=argparse.SUPPRESS)
    sub.add_parser("mute", help="Mute the native app microphone")
    sub.add_parser("unmute", help="Unmute the authorized microphone")
    sub.add_parser("listen", help="Start a voice turn")
    sub.add_parser("tasks", help="List tasks")
    ask = sub.add_parser("ask", help="Submit a request and wait for the result")
    ask.add_argument("text")
    ask.add_argument("--profile", choices=["local_strict", "local_connected", "cloud", "hybrid"])
    config_parser = sub.add_parser("config", help="Validate or update settings")
    config_parser.add_argument("action", choices=["validate", "show", "set"])
    config_parser.add_argument("key", nargs="?")
    config_parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    args.command = args.command or "desktop"
    try:
        config = ConfigStore(args.env_file)
    except (ValidationError, json.JSONDecodeError):
        print(
            "Configuration is invalid. Check field types and endpoint settings; input values are omitted for privacy.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    url = f"http://127.0.0.1:{config.settings.api_port}"
    if args.command == "desktop-info":
        # Private IPC with the native launcher, never used by a public HTTP endpoint.
        print(json.dumps({
            "url": url, "token": config.token, "data_dir": str(config.data_dir),
            "ui_language": config.settings.ui_language,
        }))
        return
    if args.command == "desktop":
        from .desktop import launch

        try:
            launch(config, browser=not getattr(args, "no_browser", False))
        except (ValueError, RuntimeError, httpx.HTTPError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None
        return
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(
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
        return
    if args.command == "config":
        if args.action == "set":
            if not args.key or args.value is None:
                parser.error("config set requires a key and value")
            try:
                value = json.loads(args.value)
            except json.JSONDecodeError:
                value = args.value
            config.update({args.key: value})
            print("Setting saved. Restart the service if it is already running.")
        elif args.action == "show":
            print(json.dumps(config.settings.public(), indent=2, ensure_ascii=False))
        else:
            print("Configuration is valid.")
        return
    if args.command == "open":
        from .desktop import existing_service

        try:
            if not existing_service(config):
                raise RuntimeError("Start Jarvis before opening the dashboard.")
        except (RuntimeError, httpx.HTTPError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None
        webbrowser.open(url + "/#token=" + config.token)
        return

    async def call():
        from .desktop import authorize_local_request

        async with httpx.AsyncClient(
            base_url=url,
            event_hooks={"request": [partial(authorize_local_request, config=config)]},
            timeout=130,
            trust_env=False,
        ) as client:
            if args.command == "doctor":
                state = {
                    "config": "valid",
                    "data_dir": str(config.data_dir),
                    "ui_built": (config.settings.ui_dir / "index.html").exists(),
                }
                try:
                    for name in ["status", "models"]:
                        response = await client.get("/api/" + name)
                        response.raise_for_status()
                        state[name] = response.json()
                except httpx.HTTPError:
                    state["service"] = "not_running"
                print(json.dumps(state, indent=2, ensure_ascii=False))
            elif args.command == "ask":
                response = await client.post(
                    "/api/chat", json={"text": args.text, "profile": args.profile}
                )
                response.raise_for_status()
                key = response.json()["id"]
                while True:
                    response = await client.get("/api/tasks")
                    response.raise_for_status()
                    row = next(x for x in response.json() if x["id"] == key)
                    if row["state"] in {"succeeded", "failed", "cancelled", "waiting_user"}:
                        print(
                            row["result"]
                            or row["error"]
                            or "The task is waiting for a decision in the dashboard."
                        )
                        return
                    await asyncio.sleep(0.3)
            elif args.command in {"mute", "unmute", "listen"}:
                response = await client.post("/api/voice/control", json={"action": args.command})
                response.raise_for_status()
                print(json.dumps(response.json(), ensure_ascii=False))
            else:
                response = await client.get("/api/" + args.command)
                response.raise_for_status()
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))

    try:
        asyncio.run(call())
    except (httpx.HTTPError, ValueError) as error:
        print(
            "Operation failed: start Jarvis and check the configuration. " + type(error).__name__,
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
