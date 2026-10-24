from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import webbrowser

import httpx

from .config import ConfigStore


def main():
    os.umask(0o077)
    # Tracing is opt-in product work; never inherit an unrelated agent's tracing secrets.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    parser = argparse.ArgumentParser(prog="jarvis", description="Assistente personale Jarvis")
    parser.add_argument("--env-file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Avvia il servizio locale")
    sub.add_parser("status", help="Stato del servizio")
    sub.add_parser("doctor", help="Diagnostica e configurazione senza segreti")
    sub.add_parser("open", help="Apri la dashboard nel browser")
    sub.add_parser("desktop-info", help=argparse.SUPPRESS)
    sub.add_parser("mute", help="Disattiva il microfono della shell nativa")
    sub.add_parser("unmute", help="Riattiva il microfono già autorizzato")
    sub.add_parser("listen", help="Apri un turno vocale")
    sub.add_parser("tasks", help="Elenca le attività")
    ask = sub.add_parser("ask", help="Invia una richiesta e attendi il risultato")
    ask.add_argument("text")
    ask.add_argument("--profile", choices=["local_strict", "local_connected", "cloud", "hybrid"])
    config_parser = sub.add_parser("config", help="Valida o aggiorna impostazioni")
    config_parser.add_argument("action", choices=["validate", "show", "set"])
    config_parser.add_argument("key", nargs="?")
    config_parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    config = ConfigStore(args.env_file)
    url = f"http://127.0.0.1:{config.settings.api_port}"
    if args.command == "desktop-info":
        # Private IPC with the native launcher, never used by a public HTTP endpoint.
        print(json.dumps({"url": url, "token": config.token, "data_dir": str(config.data_dir)}))
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
        )
        return
    if args.command == "config":
        if args.action == "set":
            if not args.key or args.value is None:
                parser.error("config set richiede chiave e valore")
            try:
                value = json.loads(args.value)
            except json.JSONDecodeError:
                value = args.value
            config.update({args.key: value})
            print("Impostazione salvata. Riavvia il servizio se è già attivo.")
        elif args.action == "show":
            print(json.dumps(config.settings.public(), indent=2, ensure_ascii=False))
        else:
            print("Configurazione valida.")
        return
    if args.command == "open":
        webbrowser.open(url + "/#token=" + config.token)
        return

    async def call():
        async with httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": "Bearer " + config.token},
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
                            or "Il task attende una decisione nella dashboard."
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
            "Operazione non riuscita: avvia Jarvis e verifica la configurazione. "
            + type(error).__name__,
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
