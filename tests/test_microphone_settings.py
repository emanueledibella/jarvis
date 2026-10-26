import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from jarvis.api import create_app
from jarvis.config import ConfigStore, Settings


@pytest.mark.parametrize("value", ["x" * 513, "fixture\nuid", "fixture\x00uid", 1, [], {}])
def test_microphone_uid_rejects_invalid_types_size_and_control_characters(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, microphone_device_uid=value)


def test_microphone_choice_persists_with_environment_precedence(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "absent.env", tmp_path / "data")
    assert store.settings.microphone_device_uid == ""
    store.update({"microphone_device_uid": "fixture-built-in"})
    assert ConfigStore(store.env_file, store.data_dir).settings.microphone_device_uid == "fixture-built-in"
    monkeypatch.setenv("JARVIS_MICROPHONE_DEVICE_UID", "fixture-usb")
    restored = ConfigStore(store.env_file, store.data_dir)
    assert restored.settings.microphone_device_uid == "fixture-usb"
    assert "microphone_device_uid" in restored.locked_fields()


async def test_microphone_settings_and_catalog_remain_local_and_require_no_audio_or_model_calls(config, monkeypatch):
    app = create_app(config, start_scheduler=False, process_lock=False)
    runtime = app.state.runtime
    monkeypatch.setattr("jarvis.api.capabilities", lambda: {"native_voice": True})
    interruptions = []
    monkeypatch.setattr(runtime.live_voice, "stop_all", lambda: interruptions.append(True))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver",
                          headers={"Authorization": "Bearer " + config.token}) as client,
    ):
        assert (await client.get("/api/voice/inputs")).json() == {"state": "app_required", "devices": []}
        runtime.native.update_status({"audio_input_selection_supported": False})
        assert (await client.get("/api/voice/inputs")).json()["state"] == "update_required"
        runtime.native.update_status({"audio_input_selection_supported": True})
        query = asyncio.create_task(client.get("/api/voice/inputs"))
        for _ in range(100):
            if runtime.native.operations:
                break
            await asyncio.sleep(0.001)
        assert len(runtime.native.operations) == 1
        key = next(iter(runtime.native.operations))
        operation = runtime.native.claim(key)
        assert operation["operation"] == "audio.inputs" and operation["arguments"] == {}
        fixture = {"uid": "fixture-private-device", "name": "Fixture private microphone", "is_default": True, "bluetooth": False}
        runtime.native.complete(key, {"devices": [fixture]})
        response = await query
        assert response.status_code == 200 and response.json() == {"state": "ready", "devices": [fixture]}
        assert not interruptions
        saved = await client.patch("/api/settings", json={"microphone_device_uid": fixture["uid"]})
        assert saved.status_code == 200 and interruptions == [True]
        native = (await client.get("/api/native/poll")).json()["settings"]
        assert native["microphone_device_uid"] == fixture["uid"]
        assert ConfigStore(config.env_file, config.data_dir).settings.microphone_device_uid == fixture["uid"]
        events = json.dumps(await runtime.db.fetchall("SELECT * FROM events"))
        assert fixture["uid"] not in events and fixture["name"] not in events
        assert not await runtime.db.fetchall("SELECT * FROM model_usage")
        assert not await runtime.db.fetchall("SELECT * FROM tasks")
        assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")
        bad = await client.patch("/api/settings", json={"microphone_device_uid": "fixture\x00bad"})
        assert bad.status_code == 422 and "fixture" not in bad.text
        assert config.settings.microphone_device_uid == fixture["uid"]
        assert (await client.get("/api/voice/inputs", headers={"Authorization": "Bearer invalid-fixture"})).status_code == 401
        assert not runtime.native.pending
        await client.patch("/api/settings", json={"microphone_device_uid": ""})
        assert config.settings.microphone_device_uid == ""


async def test_portable_microphone_catalog_does_not_queue_a_native_operation(config, monkeypatch):
    app = create_app(config, start_scheduler=False, process_lock=False)
    monkeypatch.setattr("jarvis.api.capabilities", lambda: {"native_voice": False})
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver",
                          headers={"Authorization": "Bearer " + config.token}) as client,
    ):
        result = await client.get("/api/voice/inputs")
        assert result.status_code == 200 and result.json() == {"state": "unsupported", "devices": []}
        assert not app.state.runtime.native.operations
