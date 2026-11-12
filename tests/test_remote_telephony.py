import asyncio
from unittest.mock import AsyncMock

import pytest
from test_remote_core import enroll
from test_remote_core import server as remote_server
from test_telephony_integrations import phone_config
from twilio.request_validator import RequestValidator

from jarvis.api import create_app
from jarvis.remote import ServerOptions

server = remote_server


async def settled(phone):
    await asyncio.wait_for(asyncio.shield(phone.tunnel.job), timeout=2)


async def test_remote_preflight_names_missing_settings_without_enabling_or_exposing_secrets(server, config):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    config.update({"ui_language": "it", "telephony_tunnel_mode": "managed"})
    result = await http.post("/api/telephony/start", headers=owner)
    assert result.status_code == 400
    detail = result.json()["detail"]
    assert detail.startswith("Invalid fields:")
    for label in ("SID account Twilio", "Token di autenticazione Twilio", "PIN personale", "Chiave API OpenAI"):
        assert label in detail
    assert "telephony_account_id" not in detail
    status = (await http.get("/api/telephony/status", headers=owner)).json()
    assert status["hosting"] == "remote" and status["dependencies"] is None
    assert len(status["requirements"]) == 6
    assert status["public_url"] == "https://jarvis.example"
    assert not config.settings.telephony_enabled
    assert app.state.runtime.telephony.tunnel.job is None


async def test_remote_managed_activation_uses_core_ingress_and_validates_signed_callbacks(server, config, monkeypatch):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    _, reader = await enroll(app, http)
    phone_config(config)
    config.update({"telephony_enabled": False, "telephony_tunnel_mode": "managed"})
    phone = app.state.runtime.telephony
    probe, inbound = AsyncMock(), AsyncMock(return_value=True)
    monkeypatch.setattr(phone, "check_reachability", probe)
    monkeypatch.setattr(phone, "configure_inbound_webhooks", inbound)
    monkeypatch.setattr("jarvis.telephony_tunnel.executable", lambda name: None)
    assert (await http.post("/api/telephony/start", headers=reader)).status_code == 403
    result = await http.post("/api/telephony/start", headers=owner)
    assert result.status_code == 200, result.text
    await settled(phone)
    status = (await http.get("/api/telephony/status", headers=owner)).json()
    assert status["ready"] and status["state"] == "running"
    assert status["inbound_configured"] and not status["requirements"]
    assert status["public_url"] == "https://jarvis.example"
    assert not phone.tunnel.processes
    probe.assert_awaited_once()
    inbound.assert_awaited_once()
    # Repeated activation is idempotent and does not update Twilio again.
    assert (await http.post("/api/telephony/start", headers=owner)).json()["state"] == "running"
    inbound.assert_awaited_once()
    params = {"JarvisProbe": "synthetic-public-ingress-challenge"}
    signature = RequestValidator(config.settings.secret("telephony_auth_token")).compute_signature(
        "https://jarvis.example/telephony/status", params
    )
    assert (await http.post("/telephony/status", data=params)).status_code == 403
    callback = await http.post("/telephony/status", data=params, headers={"X-Twilio-Signature": signature})
    assert callback.status_code == 200, callback.text
    assert callback.json()["proof"] == phone.probe_proof(params["JarvisProbe"])
    assert not await phone.db.fetchall("SELECT * FROM calls")
    stopped = await http.post("/api/telephony/stop", headers=owner)
    assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
    assert not config.settings.telephony_enabled and not phone.ready()[0]
    assert (await http.post("/telephony/status", data=params, headers={"X-Twilio-Signature": signature})).status_code == 403


@pytest.mark.parametrize("failure", ["probe", "webhooks"])
async def test_remote_activation_failure_turns_off_telephony_and_creates_no_call(server, config, monkeypatch, failure):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    phone_config(config)
    config.update({"telephony_enabled": False, "telephony_tunnel_mode": "managed"})
    phone = app.state.runtime.telephony
    probe = AsyncMock(side_effect=ValueError("Synthetic unreachable core") if failure == "probe" else None)
    inbound = AsyncMock(side_effect=ValueError("Synthetic invalid account") if failure == "webhooks" else None)
    monkeypatch.setattr(phone, "check_reachability", probe)
    monkeypatch.setattr(phone, "configure_inbound_webhooks", inbound)
    assert (await http.post("/api/telephony/start", headers=owner)).status_code == 200
    await settled(phone)
    assert phone.tunnel.state == "error" and phone.tunnel.error.startswith("Synthetic")
    assert not config.settings.telephony_enabled and not phone.ready()[0]
    assert not phone.tunnel.processes and not await phone.db.fetchall("SELECT * FROM calls")
    if failure == "probe":
        inbound.assert_not_awaited()


async def test_remote_inbound_requires_pin_even_when_outbound_pin_is_disabled(server, config):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    phone_config(config)
    config.update({"telephony_enabled": False, "phone_pin_enabled": False, "phone_pin": ""})
    result = await http.post("/api/telephony/start", headers=owner)
    assert result.status_code == 400 and "Personal PIN" in result.json()["detail"]
    assert not config.settings.telephony_enabled


async def test_enabled_remote_ingress_survives_core_restart_without_launching_tunnels(config, monkeypatch):
    phone_config(config)
    config.update({"telephony_tunnel_mode": "managed"})
    monkeypatch.setattr("jarvis.telephony_tunnel.executable", lambda name: None)
    for _ in range(2):
        app = create_app(config, start_scheduler=False, process_lock=False,
                         remote_options=ServerOptions(public_url="https://jarvis.example"))
        async with app.router.lifespan_context(app):
            phone = app.state.runtime.telephony
            assert phone.ready() == (True, [])
            assert phone.tunnel.state == "running" and phone.tunnel.inbound_configured
            assert phone.public_base_url == "https://jarvis.example"
            assert not phone.tunnel.processes and phone.tunnel.job is None
