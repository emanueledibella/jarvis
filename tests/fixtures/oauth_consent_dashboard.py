"""Disposable OAuth UI regression fixture: synthetic consent, no external account."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastmcp.client.auth import OAuth

from jarvis.api import create_app
from jarvis.config import ConfigStore
from jarvis.integrations import oauth_store
from jarvis.remote import ServerOptions
from jarvis.remote_store import RemoteStore


def main():
    for key in tuple(os.environ):
        if key.startswith(("JARVIS_", "OPENAI_", "ANTHROPIC_", "LANGCHAIN_", "LANGSMITH_")):
            os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="jarvis-oauth-ui-") as temporary:
        config = ConfigStore(Path(temporary)/"absent.env", Path(temporary)/"data")
        config.update({"ui_language": "it", "second_brain_url": "https://memory.example/mcp", "second_brain_auth": "oauth"})
        state = "synthetic-" + uuid4().hex
        app = create_app(config, start_scheduler=False, process_lock=False,
                         remote_options=ServerOptions(public_url="http://127.0.0.1:5174", development_http=True))
        runtime = app.state.runtime

        async def prepare():
            store = RemoteStore(config.data_dir)
            await store.open()
            try:
                code = await store.pairing_code(owner=True)
                await asyncio.to_thread(Path("output/oauth-consent-fixture.json").write_text, json.dumps({"code": code, "state": state}))
            finally:
                await store.close()

        async def discover(name, profile, *, interactive=False):
            if not interactive:
                raise PermissionError("Start the synthetic connection from the fixture UI.")
            auth = OAuth("https://memory.example/mcp", token_storage=oauth_store(Path(temporary)/"oauth"))
            runtime.remote.oauth.bind(auth, name, {}, interactive=True)
            await auth.context.redirect_handler("https://memory.example/authorize?state=" + state + "&code_challenge=fixture")
            await auth.context.callback_handler()
            runtime.mcp.statuses[name] = {"state": "connected", "tools": []}
            return []

        runtime.mcp.discover = discover
        asyncio.run(prepare())
        uvicorn.run(app, host="127.0.0.1", port=8783, access_log=False, log_level="error")


if __name__ == "__main__":
    main()
