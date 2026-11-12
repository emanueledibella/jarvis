"""Disposable UI fixture: real sandbox workers, synthetic website and Health export."""
import base64
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from jarvis.api import create_app
from jarvis.config import ConfigStore


def main():
    for key in tuple(os.environ):
        if key.startswith(("JARVIS_", "OPENAI_", "ANTHROPIC_", "LANGCHAIN_", "LANGSMITH_")):
            os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="jarvis-lab-ui-") as directory:
        config = ConfigStore(Path(directory) / "absent.env", Path(directory) / "data")
        config.token = "jarvis-lab-ui-fixture-no-personal-secret"
        config.update({"ui_language": "it", "profile": "local_connected"})
        config.settings.api_port = 8779
        app = create_app(config, start_scheduler=False, process_lock=False)
        original = app.state.runtime.lab.fetch
        async def fetch(session, message):
            if message["url"].startswith("https://jarvis-fixture.example"):
                html = b'<html><body><h1>Synthetic website</h1><label>Name<input id="name"></label><button onclick="document.querySelector(\'h1\').textContent=document.querySelector(\'#name\').value">Apply</button></body></html>'
                return {"status": 200, "headers": {"Content-Type": "text/html"}, "body": base64.b64encode(html).decode()}
            return await original(session, message)
        app.state.runtime.lab.fetch = fetch
        target = Path("output/playwright")
        target.mkdir(parents=True, exist_ok=True)
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        target.joinpath("health-fixture.xml").write_text(
            f'<HealthData><Record type="HKQuantityTypeIdentifierStepCount" sourceName="Fixture Watch" unit="count" value="4321" startDate="{day} 10:00:00 +0000" endDate="{day} 10:01:00 +0000"/></HealthData>')
        uvicorn.run(app, host="127.0.0.1", port=8779, access_log=False, log_level="error")


if __name__ == "__main__":
    main()
