"""Exercise the frozen app using a local model fixture, never a paid provider."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


class ModelFixture(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls += 1
        completed = any(message.get("role") == "tool" for message in body["messages"])
        delta = (
            {"role": "assistant", "content": "Portable build check passed."}
            if completed
            else {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "build-clock",
                        "type": "function",
                        "function": {"name": "current_time", "arguments": "{}"},
                    }
                ],
            }
        )
        ending = "stop" if completed else "tool_calls"
        if body.get("stream"):
            chunks = [
                {
                    "id": "build-fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "build-fixture",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                {
                    "id": "build-fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "build-fixture",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": ending}],
                },
            ]
            content = (
                "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                + "data: [DONE]\n\n"
            ).encode()
            content_type = "text/event-stream"
        else:
            for call in delta.get("tool_calls", []):
                call.pop("index", None)
            content = json.dumps(
                {
                    "id": "build-fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "build-fixture",
                    "choices": [{"index": 0, "message": delta, "finish_reason": ending}],
                }
            ).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    executable = args.executable or ROOT / "dist/portable/Jarvis" / (
        "Jarvis.exe" if os.name == "nt" else "Jarvis"
    )
    assert executable.is_file(), executable
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix="jarvis-frozen-smoke-") as directory:
        scratch = Path(directory)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env_file = scratch / "isolated.env"
        env_file.write_text(
            f"JARVIS_DATA_DIR={scratch / 'data'}\nJARVIS_API_PORT={port}\nJARVIS_PROFILE=local_connected\nJARVIS_LOCAL_PROVIDER=openai_compatible\nJARVIS_LOCAL_BASE_URL=http://127.0.0.1:{provider.server_port}/v1\nJARVIS_LOCAL_MODEL=build-fixture\nJARVIS_VOICE_ENABLED=false\nJARVIS_MEMORY_CAPTURE=off\nJARVIS_WORKSPACE_ROOTS=[]\n",
            encoding="utf-8",
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "SystemRoot",
                "WINDIR",
                "PATHEXT",
                "HOME",
                "USERPROFILE",
                "TEMP",
                "TMP",
                "LANG",
            }
        }
        with (scratch / "service.log").open("w+") as log:
            process = subprocess.Popen(
                [str(executable), "--env-file", str(env_file), "desktop", "--no-browser"],
                cwd=scratch,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False
                ) as client:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        assert process.poll() is None, "Frozen service exited during startup"
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.2)
                    else:
                        raise AssertionError("Frozen service startup timed out")
                    token = (scratch / "data/api-token").read_text().strip()
                    assert client.get("/api/status").status_code == 401
                    client.headers["Authorization"] = "Bearer " + token
                    status = client.get("/api/status").json()
                    assert status["platform"]["distribution"] == "portable"
                    assert status["platform"]["os"] == sys.platform
                    assert (
                        client.get(
                            "/api/status", headers={"Origin": "https://attacker.example"}
                        ).status_code
                        == 403
                    )
                    values = client.get("/api/settings").json()["values"]
                    assert (
                        values["workspace_roots"] == [] and not values["cloud_api_key_configured"]
                    )
                    html = client.get("/").text
                    for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html):
                        response = client.get(asset)
                        assert response.status_code == 200 and response.content, asset
                    request = client.post(
                        "/api/chat",
                        json={
                            "text": "Use current_time for this offline build check.",
                            "request_id": str(uuid4()),
                        },
                    )
                    request.raise_for_status()
                    task_id = request.json()["id"]
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        detail = client.get(f"/api/tasks/{task_id}/detail").json()
                        if detail["task"]["state"] in {"succeeded", "failed", "waiting_user"}:
                            break
                        time.sleep(0.2)
                    assert detail["task"]["state"] == "succeeded", detail["task"].get("error")
                    assert "Portable build check passed" in detail["task"]["result"]
                    assert any(
                        event["type"] == "tool.completed"
                        and event["data"]["tool"] == "current_time"
                        for event in detail["events"]
                    )
                    assert ModelFixture.calls >= 2
                    print(
                        json.dumps(
                            {
                                "frozen_app": "passed",
                                "os": sys.platform,
                                "authentication": "passed",
                                "UI_assets": "passed",
                                "DeepAgents_and_actual_time_tool": "passed",
                                "model_fixture_calls": ModelFixture.calls,
                                "external_provider_calls": 0,
                            }
                        )
                    )
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read()[-5000:], file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=10)
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                provider.shutdown()
                provider.server_close()


if __name__ == "__main__":
    main()
