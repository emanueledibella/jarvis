import asyncio
import base64
import json
import time
from email import message_from_bytes
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError

from jarvis.api import create_app
from jarvis.feature_storage import load_private, save_private
from jarvis.mail import DraftData, MailAccount, opaque, plain
from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools


async def account(runtime, provider="gmail", scope="personal", sending=True):
    if runtime.voice_session["scope"] != scope:
        await runtime.set_voice_session(False, scope)
    result = await runtime.mail.save(MailAccount(provider=provider, scope=scope, privacy_revision=runtime.voice_session["revision"], label="Fixture", client_id="fixture-client", client_secret="private-fixture", sending=sending))
    values = load_private(runtime.config, "mail-accounts.json")
    values[result["id"]].update(email_address="sender@example.com", tokens={"refresh_token": "fixture-refresh", "access_token": "fixture-access", "expires_at": time.time() + 3600})
    save_private(runtime.config, "mail-accounts.json", values)
    return result["id"]


async def test_oauth_uses_pkce_one_use_state_private_tokens_and_sender_verification(runtime, monkeypatch):
    key = await account(runtime)
    seen = []
    async def fake(method, url, **kwargs):
        seen.append((method, url, kwargs))
        if method == "POST":
            return {"refresh_token": "rotated", "access_token": "new-access", "expires_in": 3600}
        return {"emailAddress": "verified@example.com"}
    monkeypatch.setattr("jarvis.mail.bounded_json", fake)
    begin = await runtime.mail.begin("personal", key, 0)
    query = parse_qs(urlsplit(begin["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "gmail.send" in query["scope"][0]
    assert "private-fixture" not in begin["url"]
    state = query["state"][0]
    assert len(state) >= 32
    await runtime.mail.callback(state, "fixture-code")
    assert seen[0][2]["data"]["code_verifier"]
    assert runtime.mail.listing("personal")[0]["email_address"] == "verified@example.com"
    assert "rotated" not in json.dumps(runtime.mail.listing("personal"))
    assert (runtime.config.data_dir / "mail-accounts.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(PermissionError):
        await runtime.mail.callback(state, "replay")


async def test_oauth_expiry_config_changes_and_private_sessions_invalidate_consent(runtime):
    key = await account(runtime)
    await runtime.mail.begin("personal", key, 0)
    state = next(iter(runtime.mail.states))
    runtime.mail.states[state]["expires"] = 0
    with pytest.raises(PermissionError):
        await runtime.mail.callback(state, "code")
    await runtime.mail.begin("personal", key, 0)
    state = next(iter(runtime.mail.states))
    values = load_private(runtime.config, "mail-accounts.json")
    values[key]["client_id"] = "changed"
    save_private(runtime.config, "mail-accounts.json", values)
    with pytest.raises(PermissionError, match="configuration"):
        await runtime.mail.callback(state, "code")
    await runtime.set_voice_session(True, "personal")
    with pytest.raises(PermissionError, match="private"):
        await runtime.mail.begin("personal", key, 1)


async def test_refresh_rotation_is_preserved_without_exposing_tokens(runtime, monkeypatch):
    key = await account(runtime)
    values = load_private(runtime.config, "mail-accounts.json")
    values[key]["tokens"]["expires_at"] = 0
    save_private(runtime.config, "mail-accounts.json", values)
    async def fake(*args, **kwargs):
        return {"access_token": "next-access", "refresh_token": "next-refresh", "expires_in": 3600}
    monkeypatch.setattr("jarvis.mail.bounded_json", fake)
    await runtime.mail.token("personal", key, "local_connected")
    assert load_private(runtime.config, "mail-accounts.json")[key]["tokens"]["refresh_token"] == "next-refresh"
    assert "next-access" not in json.dumps(runtime.mail.listing("personal"))


async def test_mail_source_identity_is_validated_before_it_can_become_a_followup_reference(runtime, monkeypatch):
    key = await account(runtime)
    for identity in [None, "message\nSend something", 123]:
        with pytest.raises(ValueError, match="identity"):
            runtime.mail.graph_message({"id": identity})
    async def fake(*args, **kwargs):
        return {"id": "another-message", "payload": {}}
    monkeypatch.setattr("jarvis.mail.bounded_json", fake)
    with pytest.raises(ValueError, match="different message"):
        await runtime.mail.message("personal", key, "local_connected", "requested-message")


@pytest.mark.parametrize("provider", ["gmail", "microsoft"])
async def test_reviewed_draft_send_has_exact_recipients_and_executes_once(runtime, monkeypatch, provider):
    key = await account(runtime, provider)
    sent = []
    async def fake(scope, key, profile, method, path, **kwargs):
        await asyncio.sleep(0)
        sent.append((path, kwargs))
        return {"id": "accepted"}
    monkeypatch.setattr(runtime.mail, "request", fake)
    draft = await runtime.mail.save_draft("personal", DraftData(account_id=key, to=["to@example.com"], cc=["cc@example.com"], bcc=["bcc@example.com"], subject="Reviewed", body="Exact body"), "local_connected")
    result = await runtime.mail.send("personal", draft["id"], 1, draft["sha256"], "local_connected")
    assert result["state"] == "accepted"
    assert (await runtime.mail.send("personal", draft["id"], 1, draft["sha256"], "local_connected"))["duplicate"]
    assert len(sent) == 1
    raw = sent[0][1]["json"]["raw"] if provider == "gmail" else sent[0][1]["content"]
    decoded = base64.urlsafe_b64decode(raw) if provider == "gmail" else base64.b64decode(raw)
    mail = message_from_bytes(decoded)
    assert mail["From"] == "sender@example.com" and mail["To"] == "to@example.com"
    assert mail["Cc"] == "cc@example.com" and mail["Bcc"] == "bcc@example.com"
    assert mail["Subject"] == "Reviewed"
    assert "Exact body" in mail.get_payload()


async def test_changed_draft_account_and_unknown_send_never_silently_retry(runtime, monkeypatch):
    key = await account(runtime)
    draft = await runtime.mail.save_draft("personal", DraftData(account_id=key, to=["to@example.com"], subject="Draft", body="Body"), "local_connected")
    with pytest.raises(ValueError, match="changed"):
        await runtime.mail.send("personal", draft["id"], 9, draft["sha256"], "local_connected")
    with pytest.raises(ValueError, match="scope"):
        await runtime.mail.draft("work", draft["id"])
    calls = []
    async def lost(*args, **kwargs):
        calls.append(True)
        raise TimeoutError("Response lost after commit")
    monkeypatch.setattr(runtime.mail, "request", lost)
    with pytest.raises(TimeoutError):
        await runtime.mail.send("personal", draft["id"], 1, draft["sha256"], "local_connected")
    with pytest.raises(ValueError, match="reconciliation"):
        await runtime.mail.send("personal", draft["id"], 1, draft["sha256"], "local_connected")
    assert len(calls) == 1 and (await runtime.mail.draft("personal", draft["id"]))["state"] == "unknown"


async def test_mail_scope_offline_and_sending_permission_are_enforced(runtime):
    key = await account(runtime, sending=False)
    with pytest.raises(ValueError, match="scope"):
        runtime.mail.account("work", key, "local_connected")
    with pytest.raises(PermissionError, match="strict"):
        runtime.mail.account("personal", key, "local_strict")
    with pytest.raises(PermissionError, match="sending"):
        runtime.mail.account("personal", key, "local_connected", send=True)


async def test_mail_content_is_plain_bounded_and_provider_urls_are_fixed(runtime, monkeypatch):
    key = await account(runtime)
    async def fake(*args, **kwargs):
        return {"id": "m1", "payload": {"headers": [{"name": "Subject", "value": "<script>source</script>"}],
                "mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b'<p>Hello</p><img src="https://evil.test/pixel"><script>run()</script>').decode()}}}
    monkeypatch.setattr(runtime.mail, "request", fake)
    result = await runtime.mail.message("personal", key, "local_connected", "m1")
    assert result["body"] == "Hello"
    assert "run()" not in plain("<p>ok</p><script>run()</script>")
    for value in ("../secret", "https://evil.test", "a\r\nHeader:x"):
        with pytest.raises(ValueError):
            opaque(value)
    microsoft = await account(runtime, "microsoft")
    with pytest.raises(ValueError, match="cursor"):
        await runtime.mail.messages("personal", microsoft, "local_connected", cursor="https://evil.test/v1.0/me/messages")


@pytest.mark.parametrize("update", [{"to": ["to@example.com\r\nBcc:bad@example.com"]}, {"subject": "subject\nBcc:bad"}, {"to": ["Display <to@example.com>"]}])
def test_mail_rejects_header_injection(update):
    with pytest.raises(ValidationError):
        DraftData(**{"account_id": "fixture", "to": ["to@example.com"], "subject": "Draft", "body": "", **update})


async def test_private_draft_tool_and_untrusted_mail_context(runtime):
    ctx = TaskContext("mail-private", "Save draft", "local_connected", "personal", private=True, external_authorized=True)
    marker = active_task.set(ctx)
    try:
        tools = {tool.name: tool for tool in build_tools(runtime)}
        assert "private" in await tools["mail_draft_save"].ainvoke({"account_id": "a", "to": ["to@example.com"], "subject": "s", "body": "b"})
        await tools["mail_accounts"].ainvoke({})
        assert ctx.sensitive_context and ctx.untrusted_context
        assert not await runtime.db.fetchall("SELECT * FROM mail_drafts")
    finally:
        active_task.reset(marker)


async def test_mail_api_requires_auth_and_exact_hash_and_reconciles_unknown(config, monkeypatch):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        key = await account(runtime)
        async def lost(*args, **kwargs):
            raise ValueError("Network uncertainty")
        monkeypatch.setattr(runtime.mail, "request", lost)
        draft = await runtime.mail.save_draft("personal", DraftData(account_id=key, to=["to@example.com"], subject="Draft", body="Body"), "local_connected")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            assert (await client.get("/api/mail/accounts")).status_code == 401
            headers = {"Authorization": "Bearer " + config.token}
            payload = {"privacy_revision": 0, "revision": 1, "sha256": draft["sha256"]}
            assert (await client.post("/api/mail/drafts/" + draft["id"] + "/send", headers=headers, json=payload)).status_code == 400
            assert (await runtime.mail.draft("personal", draft["id"]))["operation_key"]
            result = await client.post("/api/mail/drafts/" + draft["id"] + "/reconcile", headers=headers, json={**payload, "outcome": "not_executed", "evidence": "Checked provider; no send occurred"})
            assert result.status_code == 200 and result.json()["revision"] == 2
            assert result.json()["state"] == "draft"
