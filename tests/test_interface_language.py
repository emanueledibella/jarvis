import json

import httpx
import pytest
from pydantic import ValidationError

from jarvis.api import create_app
from jarvis.config import ConfigStore, Settings


def test_interface_language_defaults_to_english_without_changing_speech():
    settings = Settings(_env_file=None)
    assert settings.ui_language == "en"
    assert settings.language == "it-IT" and settings.response_language == "auto"


@pytest.mark.parametrize("value", ["fr", "it-IT", "../it", "it; ignore permissions"])
def test_interface_language_accepts_only_supported_codes(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ui_language=value)


def test_interface_language_obeys_environment_precedence(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "absent.env", tmp_path / "data")
    store.update({"ui_language": "it"})
    assert ConfigStore(store.env_file, store.data_dir).settings.ui_language == "it"
    monkeypatch.setenv("JARVIS_UI_LANGUAGE", "en")
    restored = ConfigStore(store.env_file, store.data_dir)
    assert restored.settings.ui_language == "en"
    assert "ui_language" in restored.locked_fields()


async def test_language_api_persists_and_syncs_native_without_interrupting_voice(config, monkeypatch):
    app = create_app(config, start_scheduler=False, process_lock=False)
    runtime = app.state.runtime
    interruptions = []
    monkeypatch.setattr(runtime.live_voice, "stop_all", lambda: interruptions.append(True))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        runtime.productivity.weather_cache["fixture"] = {"state": "ready"}
        runtime.productivity.calendar_cache["fixture"] = {"state": "ready"}
        before = (await client.get("/api/settings")).json()["values"]
        response = await client.patch("/api/settings", json={"ui_language": "it"})
        assert response.status_code == 200
        after = response.json()["values"]
        assert after["ui_language"] == "it"
        assert {k: v for k, v in before.items() if k != "ui_language"} == {
            k: v for k, v in after.items() if k != "ui_language"
        }
        assert not interruptions
        assert "fixture" in runtime.productivity.weather_cache
        assert "fixture" in runtime.productivity.calendar_cache
        native = (await client.get("/api/native/poll")).json()["settings"]
        assert native["ui_language"] == "it"
        assert native["language"] == before["language"]
        assert native["response_language"] == before["response_language"]
        assert json.loads(config.path.read_text())["ui_language"] == "it"
        restored = ConfigStore(config.env_file, config.data_dir)
        assert restored.settings.ui_language == "it"
        invalid = await client.patch("/api/settings", json={"ui_language": "unsupported-fixture"})
        assert invalid.status_code == 422 and "unsupported-fixture" not in invalid.text
        assert config.settings.ui_language == "it"
        assert (await client.patch("/api/settings", json={"ui_language": "en"})).status_code == 200
        assert config.settings.language == before["language"]
