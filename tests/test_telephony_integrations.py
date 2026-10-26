import asyncio
import base64
import json

import httpx
import numpy as np
import pytest
from fastmcp import Client, FastMCP
from twilio.request_validator import RequestValidator

from jarvis.api import create_app
from jarvis.db import now
from jarvis.mcp_config import save_mcp_config
from jarvis.telephony import decode_mulaw, encode_mulaw


def phone_config(config):
    config.update(
        {
            "telephony_enabled": True,
            "telephony_account_id": "AC" + "1" * 32,
            "telephony_auth_token": "test-carrier-secret",
            "telephony_from_number": "+12025550101",
            "owner_phone_number": "+12025550102",
            "telephony_public_base_url": "https://phone.example.com",
            "phone_pin": "123456",
            "phone_api_key": "test-audio-secret",
            "quiet_hours": "",
        }
    )


def signed(config, path, params):
    url = config.settings.telephony_public_base_url + path
    return {
        "X-Twilio-Signature": RequestValidator(
            config.settings.secret("telephony_auth_token")
        ).compute_signature(url, params),
        "Host": "phone.example.com",
    }


@pytest.mark.parametrize("language,locale,prompt", [
    ("auto", "it-IT", "Digita il tuo codice personale"),
    ("en", "en-GB", "Enter your personal code"),
])
async def test_phone_signature_pin_and_no_data_before_identity(config, language, locale, prompt):
    phone_config(config)
    config.update({"response_language": language})
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        params = {"CallSid": "CA" + "a" * 32, "From": config.settings.owner_phone_number}
        assert (await client.post("/telephony/voice", data=params)).status_code == 403
        response = await client.post(
            "/telephony/voice", data=params, headers=signed(config, "/telephony/voice", params)
        )
        assert response.status_code == 200
        assert "<Gather" in response.text and "<Stream" not in response.text
        assert f'language="{locale}"' in response.text and prompt in response.text
        runtime = app.state.runtime
        row = await runtime.db.fetchone("SELECT * FROM calls")
        path = "/telephony/voice?call_id=" + row["id"]
        wrong = {**params, "Digits": "000000"}
        response = await client.post(path, data=wrong, headers=signed(config, path, wrong))
        assert "<Gather" in response.text and "<Stream" not in response.text
        correct = {**params, "Digits": "123456"}
        response = await client.post(path, data=correct, headers=signed(config, path, correct))
        assert (
            "<Stream" in response.text
            and "wss://phone.example.com/telephony/media" in response.text
        )
        assert (await runtime.db.fetchone("SELECT auth_verified FROM calls"))["auth_verified"] == 1
        assert (
            await client.get(
                "/api/status",
                headers={"Host": "phone.example.com", "Authorization": "Bearer " + config.token},
            )
        ).status_code == 400
        await runtime.db.execute("UPDATE calls SET state='completed'")
        another = {**params, "CallSid": "CA" + "d" * 32}
        denied = await client.post(
            "/telephony/voice", data=another, headers=signed(config, "/telephony/voice", another)
        )
        assert "<Hangup" in denied.text and "<Gather" not in denied.text
        assert len(await runtime.db.fetchall("SELECT * FROM calls")) == 1


async def test_call_callbacks_cannot_reopen_terminal_state(config):
    phone_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        runtime = app.state.runtime
        sid = "CA" + "b" * 32
        await runtime.db.execute(
            "INSERT INTO calls(id,event_key,direction,state,provider_id,created_at) VALUES('call','test','outbound','connected',?,?)",
            (sid, now()),
        )
        for status, expected in zip(
            ["ringing", "completed", "in-progress", "ringing"],
            ["connected", "completed", "completed", "completed"],
            strict=True,
        ):
            params = {"CallSid": sid, "CallStatus": status}
            path = "/telephony/status?call_id=call"
            assert (
                await client.post(path, data=params, headers=signed(config, path, params))
            ).status_code == 204
            row = await runtime.db.fetchone("SELECT state FROM calls")
            assert row["state"] == expected
        assert row["state"] == "completed"


def test_mulaw_round_trip_and_silence():
    samples = (np.sin(np.arange(800) * 2 * np.pi * 440 / 8000) * 10000).astype("<i2")
    decoded = decode_mulaw(encode_mulaw(samples))
    assert np.max(np.abs(decoded.astype(int) - samples)) < 300
    assert np.max(np.abs(decode_mulaw(b"\xff" * 160))) == 0


async def test_real_mcp_discovery_and_structured_results(runtime, monkeypatch):
    server = FastMCP("Jarvis contract server")

    @server.tool
    def status(message: str) -> dict:
        return {"state": "ok", "message": message}

    save_mcp_config(
        runtime.config,
        {"servers": {"demo": {"url": "http://127.0.0.1:9000/mcp", "read_tools": ["status"]}}},
    )
    monkeypatch.setattr(runtime.mcp, "client", lambda *a, **kw: Client(server))
    tools = await runtime.mcp.discover("demo", "local_connected")
    assert tools[0]["name"] == "status" and tools[0]["enabled"]
    assert tools[0]["schema"]["properties"]["message"]["type"] == "string"
    assert (
        await runtime.mcp.call("demo", "status", {"message": "actual transport"}, "local_connected")
    )["message"] == "actual transport"
    with pytest.raises(PermissionError):
        await runtime.mcp.call("demo", "unapproved", {}, "local_connected")


async def test_strict_mode_rejects_remote_and_arbitrary_stdio(runtime):
    for spec in [
        {"url": "https://example.com/mcp"},
        {"url": "http://127.0.0.1:8000/mcp"},
        {"command": "/usr/bin/python3"},
    ]:
        with pytest.raises(PermissionError):
            runtime.mcp.allowed(spec, "local_strict")


async def test_outbound_timeout_does_not_create_a_second_call(runtime, monkeypatch):
    phone_config(runtime.config)
    attempts = []

    class Calls:
        def create(self, **kwargs):
            attempts.append(kwargs)
            raise TimeoutError("response lost")

    class Carrier:
        def __init__(self, *args, **kwargs):
            self.calls = Calls()

    monkeypatch.setattr("twilio.rest.Client", Carrier)
    with pytest.raises(ValueError, match="uncertain"):
        await runtime.telephony.call_owner("incident-one", "Evento autorizzato", authorized=True)
    repeated = await runtime.telephony.call_owner(
        "incident-one", "Evento autorizzato", authorized=True
    )
    assert repeated["state"] == "unknown" and len(attempts) == 1
    with pytest.raises(ValueError, match="reconciliation"):
        await runtime.telephony.call_owner("incident-two", "Altro evento", authorized=True)
    assert len(attempts) == 1


async def test_emergency_stop_is_durable_and_blocks_new_work(runtime):
    await runtime.emergency(True)
    with pytest.raises(PermissionError):
        await runtime.tasks.create("New work")
    with pytest.raises(PermissionError):
        await runtime.telephony.call_owner("test", "test", authorized=True)
    assert (await runtime.db.fetchone("SELECT value FROM controls WHERE name='emergency_stop'"))[
        "value"
    ] == "1"
    assert runtime.memory.suspended
    await runtime.emergency(False)
    assert not runtime.gateway.blocked and not runtime.memory.suspended


async def test_stdio_mcp_uses_explicit_environment_and_closes(runtime, monkeypatch):
    import sys
    from pathlib import Path

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    runtime.config.env_file.write_text("JARVIS_FIXTURE_VALUE=from-dotenv\n")
    save_mcp_config(
        runtime.config,
        {
            "servers": {
                "subprocess": {
                    "command": sys.executable,
                    "args": [str(Path(__file__).parent / "fixtures/mcp_demo.py")],
                    "env": {"JARVIS_TEST_VALUE": "${JARVIS_FIXTURE_VALUE}"},
                    "read_tools": ["environment_check"],
                }
            }
        },
    )
    result = await runtime.mcp.call("subprocess", "environment_check", {}, "local_connected")
    assert result == {"explicit_value": "from-dotenv", "provider_key_present": False}


async def test_oauth_url_keys_survive_private_file_store_restart(tmp_path):
    from jarvis.integrations import oauth_store

    store = oauth_store(tmp_path / "oauth")
    keys = ["https://example.com/mcp", "https://example.com/mcp/../../other?token=x"]
    for index, key in enumerate(keys):
        await store.put(
            key=key, collection="mcp-oauth-client-info", value={"client_id": f"client-{index}"}
        )
    restored = oauth_store(tmp_path / "oauth")
    for index, key in enumerate(keys):
        assert await restored.get(key=key, collection="mcp-oauth-client-info") == {
            "client_id": f"client-{index}"
        }
    assert all("https:" not in str(path) for path in (tmp_path / "oauth").rglob("*"))


async def test_phone_dtmf_approves_only_the_proposal_read_back(runtime, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_agent_policy import model_factory

    phone_config(runtime.config)
    runtime.config.update({"workspace_roots": [str(tmp_path)]})
    monkeypatch.setattr(
        runtime.tasks,
        "model",
        model_factory("workspace_command", {"command": "echo approved", "cwd": "."}),
    )
    utterances = []

    async def tts(text):
        utterances.append(text)
        return b""

    async def stt(samples):
        return "Esegui il comando echo approved"

    monkeypatch.setattr(runtime.telephony, "tts", tts)
    monkeypatch.setattr(runtime.telephony, "stt", stt)
    sid = "CA" + "c" * 32
    await runtime.db.execute(
        "INSERT INTO calls(id,event_key,direction,state,provider_id,auth_verified,created_at) VALUES('call','test','outbound','answered',?,1,?)",
        (sid, now()),
    )
    runtime.telephony.media_tokens["call"] = "one-use-session-token"

    class Socket:
        url = SimpleNamespace(path="/telephony/media", query="")
        headers = {
            "x-twilio-signature": signed(runtime.config, "/telephony/media", {})[
                "X-Twilio-Signature"
            ]
        }

        async def accept(self):
            pass

        async def close(self, **kwargs):
            pass

        async def send_json(self, event):
            pass

        async def iter_text(self):
            yield json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": "MZtest",
                        "callSid": sid,
                        "mediaFormat": {
                            "encoding": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "channels": 1,
                        },
                        "customParameters": {"call_id": "call", "token": "one-use-session-token"},
                    },
                }
            )
            voice = encode_mulaw(np.full(160, 10000, dtype="<i2"))
            for frame in [voice] * 9 + [b"\xff" * 160] * 35:
                yield json.dumps(
                    {"event": "media", "media": {"payload": base64.b64encode(frame).decode()}}
                )
                await asyncio.sleep(0)
            for _ in range(200):
                row = await runtime.db.fetchone("SELECT * FROM approvals WHERE state='pending'")
                if row and any("Premi uno" in text for text in utterances):
                    break
                await asyncio.sleep(0.01)
            assert row and "echo approved" in next(
                text for text in utterances if "Premi uno" in text
            )
            assert not await runtime.db.fetchall("SELECT * FROM effects")
            yield json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})
            # Includes native shell startup, which can exceed two seconds on Windows.
            async with asyncio.timeout(30):
                while True:
                    task = await runtime.db.fetchone(
                        "SELECT * FROM tasks WHERE id=?", (row["task_id"],)
                    )
                    if task["state"] in {"succeeded", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(0.02)
            assert task["state"] == "succeeded", task["error"]
            yield json.dumps({"event": "stop"})

    await runtime.telephony.media(Socket())
    assert (await runtime.db.fetchone("SELECT state FROM approvals"))["state"] == "approved"
    assert len(await runtime.db.fetchall("SELECT * FROM effects WHERE state='succeeded'")) == 1
