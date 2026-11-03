from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_telephony_integrations import phone_config, signed
from twilio.rest.api.v2010.account.call import CallInstance

from jarvis.api import create_app
from jarvis.db import now


def carrier_call(config, **changes):
    moment = datetime.now(UTC).replace(microsecond=0)
    return CallInstance(
        None,
        {
            "sid": "CA" + "a" * 32,
            "to": config.settings.owner_phone_number,
            "from": config.settings.telephony_from_number,
            "direction": "outbound-api",
            "status": "completed",
            "date_created": format_datetime(moment),
            "end_time": format_datetime(moment + timedelta(seconds=16)),
            "duration": "16",
            "price": "-0.04760",
            **changes,
        },
        config.settings.telephony_account_id,
    )


def install_carrier(monkeypatch, call, *, unavailable=False):
    class Calls:
        def __init__(self):
            self.lookups = 0
            self.created = []

        def __call__(self, sid):
            assert sid in {call.sid, "CA" + "b" * 32}
            return SimpleNamespace(fetch=self.fetch, update=lambda **kwargs: None)

        def fetch(self):
            self.lookups += 1
            if unavailable:
                raise TimeoutError("Carrier status unavailable")
            return call

        def create(self, **kwargs):
            self.created.append(kwargs)
            return SimpleNamespace(sid="CA" + "b" * 32)

    calls = Calls()
    monkeypatch.setattr("twilio.rest.Client", lambda *args, **kwargs: SimpleNamespace(calls=calls))
    return calls


async def insert_call(runtime, state="ringing"):
    await runtime.db.execute(
        "INSERT INTO calls(id,event_key,direction,state,provider_id,reservation_usd,created_at) "
        "VALUES('stale','previous','outbound',?,?,1.08,?)",
        (state, "CA" + "a" * 32, now()),
    )


async def test_public_probe_authenticates_the_same_instance_without_creating_calls(
    config, monkeypatch
):
    phone_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    real_client = httpx.AsyncClient
    transport = httpx.ASGITransport(app=app)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    async with app.router.lifespan_context(app):
        await app.state.runtime.telephony.check_reachability()
        async with real_client(transport=transport, base_url="https://phone.example.com") as client:
            unsigned = await client.post("/telephony/status", data={"JarvisProbe": "a" * 32})
        assert unsigned.status_code == 403
        assert not await app.state.runtime.db.fetchall("SELECT * FROM calls")


@pytest.mark.parametrize("status,body", [(502, {}), (200, {"proof": "wrong-instance"}), (307, {})])
async def test_bad_tunnel_never_creates_or_reserves_a_paid_call(runtime, monkeypatch, status, body):
    phone_config(runtime.config)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    with pytest.raises(ValueError, match="public telephony proxy"):
        await runtime.telephony.call_owner("new", "Owner's request", authorized=True)
    assert not await runtime.db.fetchall("SELECT * FROM calls")


@pytest.mark.parametrize("state", ["ringing", "connected", "unknown"])
async def test_call_list_recovers_a_missing_terminal_callback(config, monkeypatch, state):
    phone_config(config)
    call = carrier_call(config)
    calls = install_carrier(monkeypatch, call)
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        await insert_call(app.state.runtime, state)
        response = await client.get("/api/calls")
        assert response.status_code == 200
        row = response.json()[0]
        assert row["state"] == "completed"
        assert row["ended_at"] == call.end_time.isoformat()
        assert row["reservation_usd"] == pytest.approx(0.36)
        await client.get("/api/calls")
        assert calls.lookups == 1 and not calls.created


async def test_next_call_recovers_the_old_call_and_its_unused_budget(runtime, monkeypatch):
    phone_config(runtime.config)
    calls = install_carrier(monkeypatch, carrier_call(runtime.config))
    probe = AsyncMock()
    monkeypatch.setattr(runtime.telephony, "check_reachability", probe)
    await insert_call(runtime)
    result = await runtime.telephony.call_owner("new", "Owner's request", authorized=True)
    assert result["state"] == "ringing"
    assert len(calls.created) == 1
    assert (await runtime.db.fetchone("SELECT state FROM calls WHERE id='stale'"))[
        "state"
    ] == "completed"
    assert (await runtime.db.fetchone("SELECT SUM(reservation_usd) AS total FROM calls"))[
        "total"
    ] == pytest.approx(1.44)
    probe.assert_awaited_once()


@pytest.mark.parametrize("problem", ["unavailable", "wrong-number", "wrong-time", "still-active"])
async def test_failed_or_nonterminal_verification_keeps_the_call_blocked(
    runtime, monkeypatch, problem
):
    phone_config(runtime.config)
    changes = {}
    if problem == "wrong-number":
        changes["to"] = "+12025550999"
    elif problem == "wrong-time":
        changes["date_created"] = format_datetime(datetime.now(UTC) - timedelta(hours=1))
    elif problem == "still-active":
        changes["status"] = "in-progress"
    calls = install_carrier(
        monkeypatch, carrier_call(runtime.config, **changes), unavailable=problem == "unavailable"
    )
    await insert_call(runtime)
    with pytest.raises(ValueError, match="already active"):
        await runtime.telephony.call_owner("new", "Owner's request", authorized=True)
    assert not calls.created
    assert (await runtime.db.fetchone("SELECT state FROM calls WHERE id='stale'"))["state"] not in {
        "completed",
        "failed",
    }


async def test_manual_reconciliation_uses_real_sdk_fields_and_preserves_unknown_usage(
    runtime, monkeypatch
):
    phone_config(runtime.config)
    call = carrier_call(runtime.config, duration=None, price=None)
    install_carrier(monkeypatch, call)
    await insert_call(runtime, "unknown")
    result = await runtime.telephony.reconcile(
        "stale", provider_id=call.sid, note="Verified in carrier log"
    )
    row = await runtime.db.fetchone("SELECT * FROM calls WHERE id='stale'")
    assert result["state"] == row["state"] == "completed"
    assert row["ended_at"] == call.end_time.isoformat()
    assert row["reservation_usd"] == 1.08


async def test_status_refresh_does_not_overwrite_a_newer_terminal_callback(runtime):
    phone_config(runtime.config)
    await insert_call(runtime)
    previous = await runtime.db.fetchone("SELECT * FROM calls WHERE id='stale'")
    await runtime.db.execute(
        "UPDATE calls SET state='completed',ended_at=? WHERE id='stale'", (now(),)
    )
    await runtime.telephony.update_status(previous, previous["provider_id"], "in-progress")
    assert (await runtime.db.fetchone("SELECT state FROM calls WHERE id='stale'"))[
        "state"
    ] == "completed"


async def test_terminal_callback_settles_rounded_usage(config):
    phone_config(config)
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        await insert_call(app.state.runtime)
        params = {"CallSid": "CA" + "a" * 32, "CallStatus": "completed", "CallDuration": "16"}
        path = "/telephony/status?call_id=stale"
        response = await client.post(path, data=params, headers=signed(config, path, params))
        assert response.status_code == 204
        row = await app.state.runtime.db.fetchone("SELECT * FROM calls WHERE id='stale'")
        assert row["state"] == "completed" and row["reservation_usd"] == pytest.approx(0.36)
        # A delayed duplicate must not overwrite a higher verified carrier cost.
        await app.state.runtime.db.execute("UPDATE calls SET reservation_usd=0.80 WHERE id='stale'")
        await client.post(path, data=params, headers=signed(config, path, params))
        row = await app.state.runtime.db.fetchone("SELECT * FROM calls WHERE id='stale'")
        assert row["reservation_usd"] == pytest.approx(0.80)
