import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from test_phone_live import PhoneConnection, PhoneSocket, configure, install_provider
from test_telephony_integrations import signed

from jarvis.scheduler import ScheduleInput


@pytest.mark.parametrize("live", [True, False])
@pytest.mark.parametrize("pin_enabled", [True, False])
@pytest.mark.parametrize("language", ["auto", "en"])
@pytest.mark.parametrize("with_body", [True, False])
async def test_due_phone_reminder_announces_content_at_start(
    runtime, monkeypatch, live, pin_enabled, language, with_body
):
    configure(
        runtime,
        desktop_voice_provider="openai_live" if live else "apple",
        phone_pin_enabled=pin_enabled,
        response_language=language,
    )
    # Include important content after every former 400/1000-character or byte cutoff.
    body = (
        ("Ricordati di ritirare il pacco. " * 45 + "Porta con te la delega e l’identità.")
        if with_body
        else ""
    )
    title = "Promemoria consegna"
    content = body or title
    carrier_create = Mock(return_value=SimpleNamespace(sid="CA" + "c" * 32))
    monkeypatch.setattr(
        "twilio.rest.Client",
        lambda *args, **kwargs: SimpleNamespace(calls=SimpleNamespace(create=carrier_create)),
    )
    monkeypatch.setattr(runtime.telephony, "check_reachability", AsyncMock())
    created = await runtime.scheduler.create(
        ScheduleInput(
            title=title,
            prompt=body,
            expression="tra 1 minuto",
            notify="phone",
            call_authorized=True,
        )
    )
    due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await runtime.db.execute("UPDATE schedules SET next_run_at=? WHERE id=?", (due, created["id"]))
    await runtime.scheduler.tick()
    await runtime.scheduler.tick()
    carrier_create.assert_called_once()
    row = await runtime.db.fetchone("SELECT * FROM calls")
    assert row["detail"] == content

    class ReminderSocket(PhoneSocket):
        async def iter_text(self):
            async for raw in super().iter_text():
                event = json.loads(raw)
                if event["event"] == "start":
                    event["start"]["customParameters"] = {"call_id": row["id"], "token": token}
                yield json.dumps(event)

    socket = ReminderSocket(runtime)
    utterances = []

    if live:

        class ReminderConnection(PhoneConnection):
            async def start(self, *, session):
                await super().start(session=session)
                await socket.incoming.put({"event": "stop"})

        connection = ReminderConnection(socket, delegate=False)
        install_provider(monkeypatch, connection, {})
    else:

        async def tts(text):
            utterances.append(text)
            await socket.incoming.put({"event": "stop"})
            return b""

        monkeypatch.setattr(runtime.telephony, "tts", tts)

    # Exercise the signed webhook and PIN gate before the announcement is available.
    app = FastAPI()
    app.include_router(runtime.telephony.router())
    path = "/telephony/voice?call_id=" + row["id"]
    params = {"CallSid": row["provider_id"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            path, data=params, headers=signed(runtime.config, path, params)
        )
        if pin_enabled:
            assert "<Gather" in response.text and "<Stream" not in response.text
            assert title not in response.text and content not in response.text
            params["Digits"] = "123456"
            response = await client.post(
                path, data=params, headers=signed(runtime.config, path, params)
            )
        assert response.status_code == 200 and "<Stream" in response.text

    token = runtime.telephony.media_tokens[row["id"]]

    await asyncio.wait_for(runtime.telephony.media(socket), 5)
    if live:
        # The provider must have the full announcement in the session.start request;
        # waiting for session.started lets it generate an unrelated generic greeting.
        opening = connection.configuration["input"][0]["content"][0]["text"]
        assert not connection.commentary  # No duplicate/late opening after startup.
    else:
        assert len(utterances) == 1
        opening = utterances[0]
    assert content in opening
    assert "Come posso aiutarti" not in opening and "How can I help" not in opening
    assert ("Identità verificata" in opening or "Identity verified" in opening) is pin_enabled
    assert ("Motivo della chiamata" if language == "auto" else "Reason for the call") in opening
    assert not await runtime.db.fetchall("SELECT * FROM tasks")
    assert (await runtime.db.fetchone("SELECT state FROM schedule_runs"))["state"] == "notified"
    assert not runtime.telephony.active
    if live:
        assert socket.closed
