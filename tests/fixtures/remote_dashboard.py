"""Manual browser fixture: no model, account, carrier or private data is contacted."""

import asyncio
import json
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from test_agent_policy import model_factory  # noqa: E402

from jarvis.api import create_app  # noqa: E402
from jarvis.config import ConfigStore  # noqa: E402
from jarvis.policy import active_task  # noqa: E402
from jarvis.remote import ServerOptions  # noqa: E402
from jarvis.remote_store import RemoteStore  # noqa: E402


async def prepare(directory):
    store = RemoteStore(directory)
    await store.open()
    try:
        code = await store.pairing_code(owner=True)
        (ROOT / "output/remote-ui-code.txt").write_text(code)
    finally:
        await store.close()


def main():
    directory = ROOT / "output/remote-ui-fixture"
    directory.mkdir(parents=True, exist_ok=True)
    config = ConfigStore(env_file=directory / "empty.env", data_dir=directory / "data")
    asyncio.run(prepare(config.data_dir))
    app = create_app(config, start_scheduler=False, process_lock=False,
        remote_options=ServerOptions(public_url="http://127.0.0.1:5174", development_http=True))
    runtime = app.state.runtime

    async def weather(*args, **kwargs):
        return {"state": "not_configured"}

    async def calendar(*args, **kwargs):
        return {"state": "not_configured", "events": []}

    def model(*args, **kwargs):
        ctx = active_task.get()
        if "activity" in ctx.prompt.lower() or "attività" in ctx.prompt.lower():
            return model_factory("activity_save", {"title": "Synthetic companion activity"})()
        return model_factory()()

    runtime.productivity.weather, runtime.productivity.calendar = weather, calendar
    runtime.tasks.model = model
    print(json.dumps({"fixture": "remote", "api": "127.0.0.1:8781", "ui": "127.0.0.1:5174"}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8781, access_log=False, log_level="error")


if __name__ == "__main__":
    main()
