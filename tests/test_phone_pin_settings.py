import httpx
import pytest
from test_telephony_integrations import phone_config, signed

from jarvis.api import create_app
from jarvis.config import ConfigStore, Settings
from jarvis.db import now


@pytest.mark.parametrize("pin", ["", "invalid"])
async def test_pin_is_only_required_and_validated_when_enabled(runtime, pin):
    phone_config(runtime.config)
    runtime.config.update({"phone_pin_enabled": False, "phone_pin": pin})
    assert runtime.telephony.ready() == (True, [])
    runtime.config.update({"phone_pin_enabled": True})
    ready, missing = runtime.telephony.ready()
    assert not ready
    assert ("phone_pin" if not pin else "phone_pin_6_to_8_digits") in missing


async def test_pin_checkbox_persists_without_erasing_or_disclosing_the_saved_pin(config):
    phone_config(config)
    assert Settings(_env_file=None).phone_pin_enabled is True
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        for enabled in [False, True]:
            response = await client.patch("/api/settings", json={"phone_pin_enabled": enabled})
            assert response.status_code == 200
            values = response.json()["values"]
            assert values["phone_pin_enabled"] is enabled
            assert values["phone_pin"] == "" and values["phone_pin_configured"] is True
            assert "123456" not in response.text
            restored = ConfigStore(config.env_file, config.data_dir)
            assert restored.settings.phone_pin_enabled is enabled
            assert restored.settings.secret("phone_pin") == "123456"


async def test_disabling_pin_starts_outbound_conversation_without_keypad_input(config):
    phone_config(config)
    config.update({"phone_pin_enabled": False, "phone_pin": ""})
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        runtime = app.state.runtime
        sid = "CA" + "c" * 32
        path = "/telephony/voice?call_id=call"
        await runtime.db.execute(
            "INSERT INTO calls(id,event_key,direction,state,provider_id,created_at) "
            "VALUES('call','test','outbound','ringing',?,?)",
            (sid, now()),
        )
        wrong = {"CallSid": "CA" + "d" * 32}
        assert (
            await client.post(path, data=wrong, headers=signed(config, path, wrong))
        ).status_code == 403
        params = {"CallSid": sid, "From": config.settings.owner_phone_number}
        assert (await client.post(path, data=params)).status_code == 403
        response = await client.post(path, data=params, headers=signed(config, path, params))
        assert response.status_code == 200
        assert "<Stream" in response.text and "<Gather" not in response.text
        row = await runtime.db.fetchone("SELECT * FROM calls")
        assert row["auth_verified"] == 1 and row["attempts"] == 0
        assert runtime.telephony.media_tokens[row["id"]]
        await runtime.db.execute("UPDATE calls SET state='completed'")


async def test_inbound_always_reserves_pin_time_while_outbound_can_be_hands_free(runtime):
    phone_config(runtime.config)
    assert await runtime.telephony.reservation(inbound=True) == pytest.approx(1.44)
    runtime.config.update({"phone_pin_enabled": False})
    assert await runtime.telephony.reservation(inbound=True) == pytest.approx(1.44)
    assert await runtime.telephony.reservation() == pytest.approx(1.08)
