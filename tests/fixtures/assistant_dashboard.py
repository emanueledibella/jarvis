"""Isolated browser QA: synthetic accounts, local MCP, no real provider calls."""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import uvicorn

from jarvis.api import create_app
from jarvis.config import ConfigStore
from jarvis.platforms import process_environment
from jarvis.policy import active_task

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def main():
    from test_agent_policy import model_factory

    directory = Path(tempfile.mkdtemp(prefix="jarvis-assistant-qa-"))
    env_file = directory / "fixture.env"
    env_file.write_text("JARVIS_API_PORT=8777\nJARVIS_UI_DIR=" + str(ROOT / "web/dist") + "\n")
    config = ConfigStore(env_file=env_file, data_dir=directory / "data")
    config.token = "assistant-browser-fixture-token-no-real-credential"
    config.token_path.write_text(config.token)
    workspace = directory / "workspace"
    workspace.mkdir()
    (workspace / "source.txt").write_text("Synthetic document: delivery is due Friday. No owner facts.")
    config.update({"ui_language": "it", "workspace_roots": [str(workspace)]})
    app = create_app(config, start_scheduler=False, process_lock=False)
    runtime = app.state.runtime

    async def weather(*args, **kwargs):
        return {"state": "ready", "current": {"temperature_2m": 20, "weather_code": 0, "apparent_temperature": 19, "wind_speed_10m": 4}}

    async def calendar(*args, **kwargs):
        start = datetime.now(UTC) + timedelta(hours=1)
        return {"state": "ready", "events": [{"id": "fixture-meeting", "title": "Synthetic review meeting", "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat()}]}
    runtime.productivity.weather = weather
    runtime.productivity.calendar = calendar

    def model(*args, **kwargs):
        ctx = active_task.get()
        if ctx.attachment_ids:
            if len(ctx.attachment_ids) == 2 and any(word in ctx.prompt.casefold() for word in ("compare", "confronta")):
                return model_factory("documents_compare", {"first_id": ctx.attachment_ids[0], "second_id": ctx.attachment_ids[1]})()
            return model_factory("document_read", {"document_id": ctx.attachment_ids[0]})()
        if "stand-up" in ctx.prompt:
            return model_factory("development_summary")()
        if any(word in ctx.prompt.casefold() for word in ("briefing", "recap", "riepilogo")):
            return model_factory("today_overview")()
        return model_factory()()
    runtime.tasks.model = model

    import jarvis.development as development
    development.JIRA_URL = "http://127.0.0.1:8790/mcp"
    async def github_http(method, url, **kwargs):
        assert url.startswith("https://api.github.com/repos/fixture/repository/")
        suffix = url.split("/fixture/repository/", 1)[1]
        if suffix == "pulls":
            return [{"number": 3, "title": "BVTL-1 synthetic feature", "state": "open", "body": "Synthetic PR, no real code.", "head": {"sha": "a" * 40, "ref": "fixture/BVTL-1"}, "user": {"login": "fixture-owner"}}]
        if suffix == "pulls/3":
            return {"number": 3, "title": "Synthetic PR", "head": {"sha": "a" * 40}, "changed_files": 1}
        if suffix.endswith("check-runs"):
            return {"check_runs": [{"name": "Synthetic check", "status": "completed", "conclusion": "success"}], "total_count": 1}
        if suffix.endswith("/status"):
            return {"state": "success"}
        if suffix.endswith("/files"):
            return [{"filename": "fixture.py", "status": "modified", "patch": "@@ -1 +1 @@\n-old\n+new"}]
        if suffix.endswith("/reviews"):
            return []
        return {"number": 4}
    development.bounded_json = github_http

    import jarvis.mail as mail
    async def mail_http(method, url, **kwargs):
        if "oauth2.googleapis.com/token" in url:
            return {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600}
        if url.endswith("/profile"):
            return {"emailAddress": "sender@example.com"}
        if url.endswith("/messages/send"):
            return {"id": "synthetic-sent"}
        if url.endswith("/messages"):
            return {"messages": [{"id": "fixture-message"}]}
        if url.endswith("/messages/fixture-message"):
            return {"id": "fixture-message", "threadId": "fixture-thread", "labelIds": ["INBOX", "UNREAD"],
                    "snippet": "Synthetic request for a Friday update.",
                    "payload": {"mimeType": "text/plain", "headers": [{"name": "Subject", "value": "Synthetic project update"}, {"name": "From", "value": "colleague@example.com"}, {"name": "Message-ID", "value": "<fixture@example.com>"}],
                                "body": {"data": base64.urlsafe_b64encode(b"Please prepare an update by Friday. This is synthetic source data.").decode()}}}
        raise AssertionError("Unmodeled mail fixture request")
    mail.bounded_json = mail_http
    begin = runtime.mail.begin
    async def fixture_consent(scope, key, revision):
        result = await begin(scope, key, revision)
        state = parse_qs(urlsplit(result["url"]).query)["state"][0]
        return {"url": "http://127.0.0.1:8777/oauth/mail/callback?state=" + state + "&code=fixture-consent", "expires_in": 300}
    runtime.mail.begin = fixture_consent

    mcp = subprocess.Popen([sys.executable, str(Path(__file__).with_name("assistant_mcp.py"))],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=process_environment())
    try:
        print("Synthetic dashboard on 127.0.0.1:8777; local MCP on 127.0.0.1:8790", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=8777, access_log=False, log_level="error")
    finally:
        mcp.terminate()
        try:
            mcp.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mcp.kill()
            mcp.wait()
        shutil.rmtree(directory)


if __name__ == "__main__":
    main()
