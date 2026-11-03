from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit

from bs4 import BeautifulSoup
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import now, uid
from .feature_context import Scope, check_write, owner_write
from .feature_storage import bounded_json, load_private, save_private
from .policy import TaskContext, active_task, digest


def opaque(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+=.@:-]{1,1000}", value):
        raise ValueError("Invalid provider message identity.")
    return quote(value, safe="")


def plain(value):
    soup = BeautifulSoup(value[:200000], "html.parser")
    for tag in soup(["script", "style", "iframe", "object"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)[:50000]


class MailAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    provider: Literal["gmail", "microsoft"]
    label: str = Field(min_length=1, max_length=100)
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(default="", max_length=1000)
    sending: bool = False


class MailContext(BaseModel):
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)


class DraftData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(max_length=100)
    to: list[str] = Field(min_length=1, max_length=20)
    cc: list[str] = Field(default_factory=list, max_length=20)
    bcc: list[str] = Field(default_factory=list, max_length=20)
    subject: str = Field(max_length=300)
    body: str = Field(max_length=50000)
    reply_message_id: str | None = Field(default=None, max_length=1000)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def recipients(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_\x60{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", x)
               or len(x) > 254 or "\r" in x or "\n" in x for x in values):
            raise ValueError("Use complete email addresses without display names or newlines.")
        return values

    @field_validator("subject")
    @classmethod
    def header(cls, value):
        if "\r" in value or "\n" in value:
            raise ValueError("The subject cannot contain newlines.")
        return value


class DraftWrite(DraftData):
    scope: Scope = "personal"
    privacy_revision: int = Field(ge=0)
    revision: int | None = Field(default=None, ge=1)

    def draft(self):
        return DraftData.model_validate(self.model_dump(exclude={"scope", "privacy_revision", "revision"}))


class DraftAction(MailContext):
    revision: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DraftReconcile(DraftAction):
    outcome: Literal["accepted", "not_executed"]
    evidence: str = Field(min_length=10, max_length=1000)


class Mail:
    def __init__(self, runtime):
        self.runtime = runtime
        self.db = runtime.db
        self.lock = asyncio.Lock()
        self.states = {}

    def account(self, scope, key, profile, *, send=False):
        if self.runtime.gateway.blocked or profile == "local_strict" or self.runtime.config.settings.profile == "local_strict":
            raise PermissionError("Mail is unavailable while stopped or in strict local mode.")
        item = load_private(self.runtime.config, "mail-accounts.json").get(key)
        if not item or item["scope"] != scope:
            raise ValueError("Mail account not found in this scope.")
        if send and not item["sending"]:
            raise PermissionError("Enable sending and complete separate mail consent.")
        return item

    def listing(self, scope):
        return [{**{k: v for k, v in value.items() if k not in {"client_secret", "tokens"}},
                 "connected": bool(value.get("tokens", {}).get("refresh_token"))}
                for value in load_private(self.runtime.config, "mail-accounts.json").values() if value["scope"] == scope]

    async def save(self, data: MailAccount):
        async with self.lock:
            owner_write(self.runtime, data.scope, data.privacy_revision)
            values = load_private(self.runtime.config, "mail-accounts.json")
            key = data.id or uid()
            old = values.get(key)
            if data.id and (not old or old["scope"] != data.scope):
                raise ValueError("Mail account not found in this scope.")
            if not old and len(values) >= 10:
                raise ValueError("At most ten mail accounts can be connected.")
            value = data.model_dump(exclude={"privacy_revision"})
            value["id"] = key
            if old and not value["client_secret"]:
                value["client_secret"] = old.get("client_secret", "")
            if old and all(old.get(k) == value[k] for k in ("provider", "client_id", "client_secret", "sending")):
                value["tokens"] = old.get("tokens", {})
                value["email_address"] = old.get("email_address", "")
            values[key] = value
            save_private(self.runtime.config, "mail-accounts.json", values)
            return next(x for x in self.listing(data.scope) if x["id"] == key)

    async def disconnect(self, scope, key):
        async with self.lock:
            check_write(self.runtime)
            values = load_private(self.runtime.config, "mail-accounts.json")
            if key not in values or values[key]["scope"] != scope:
                raise ValueError("Mail account not found in this scope.")
            pending = await self.db.fetchone("SELECT id FROM mail_drafts WHERE scope=? AND account_id=? AND state IN ('sending','unknown')", (scope, key))
            if pending:
                raise ValueError("Reconcile pending mail before disconnecting this account.")
            values.pop(key)
            save_private(self.runtime.config, "mail-accounts.json", values)
            self.states = {s: v for s, v in self.states.items() if v["id"] != key}
            await self.db.execute("DELETE FROM mail_drafts WHERE scope=? AND account_id=?", (scope, key))
            return {"state": "disconnected", "message": "Local credentials and drafts removed. Revoke provider consent in your account if required."}

    def endpoints(self, provider):
        if provider == "gmail":
            return "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token"
        return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def scopes(self, account):
        if account["provider"] == "gmail":
            return "https://www.googleapis.com/auth/gmail.readonly" + (" https://www.googleapis.com/auth/gmail.send" if account["sending"] else "")
        return "offline_access User.Read Mail.Read" + (" Mail.Send" if account["sending"] else "")

    async def begin(self, scope, key, revision):
        owner_write(self.runtime, scope, revision)
        account = self.account(scope, key, self.runtime.config.settings.profile)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        self.states = {s: v for s, v in self.states.items() if v["expires"] > time.monotonic()}
        if len(self.states) >= 10:
            raise ValueError("Too many pending mail connections.")
        self.states[state] = {"id": key, "scope": scope, "revision": revision, "verifier": verifier,
                              "fingerprint": digest(account), "expires": time.monotonic() + 300}
        if self.runtime.remote:
            from .remote_context import active_client
            self.states[state]["remote_client"] = active_client.get()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params = {"client_id": account["client_id"], "response_type": "code",
                  "redirect_uri": self.redirect(), "scope": self.scopes(account), "state": state,
                  "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "consent"}
        if account["provider"] == "gmail":
            params["access_type"] = "offline"
        return {"url": self.endpoints(account["provider"])[0] + "?" + urlencode(params), "expires_in": 300}

    def redirect(self):
        if self.runtime.remote:
            return self.runtime.remote.options.public_url + "/oauth/mail/callback"
        return f"http://127.0.0.1:{self.runtime.config.settings.api_port}/oauth/mail/callback"

    async def callback(self, state, code):
        from .remote_context import active_client
        client = self.states.get(state, {}).get("remote_client")
        token = None
        if client:
            device = await self.runtime.remote.store.fetchone("SELECT revoked FROM devices WHERE id=?", (client.device_id,))
            if not device or device["revoked"]:
                raise PermissionError("The initiating device was revoked.")
            token = active_client.set(client)
        try:
            return await self.complete_callback(state, code)
        finally:
            if token is not None:
                active_client.reset(token)

    async def complete_callback(self, state, code):
        pending = self.states.pop(state, None)
        if not pending or pending["expires"] < time.monotonic() or not code or len(code) > 4096:
            raise PermissionError("Mail consent expired or was already used. Connect again.")
        async with self.lock:
            owner_write(self.runtime, pending["scope"], pending["revision"])
            account = self.account(pending["scope"], pending["id"], self.runtime.config.settings.profile)
            if digest(account) != pending["fingerprint"]:
                raise PermissionError("Mail configuration changed. Connect again.")
            payload = {"grant_type": "authorization_code", "code": code, "client_id": account["client_id"],
                       "redirect_uri": self.redirect(), "code_verifier": pending["verifier"]}
            if account.get("client_secret"):
                payload["client_secret"] = account["client_secret"]
            tokens = await bounded_json("POST", self.endpoints(account["provider"])[1], data=payload)
            if not tokens.get("refresh_token") or not tokens.get("access_token"):
                raise ValueError("Mail consent did not provide offline access. Connect again.")
            identity_url = ("https://gmail.googleapis.com/gmail/v1/users/me/profile"
                            if account["provider"] == "gmail" else "https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName")
            identity = await bounded_json("GET", identity_url, headers={"Authorization": "Bearer " + tokens["access_token"]})
            address = identity.get("emailAddress") if account["provider"] == "gmail" else identity.get("mail") or identity.get("userPrincipalName")
            DraftData.recipients([address or ""])
            owner_write(self.runtime, pending["scope"], pending["revision"])
            values = load_private(self.runtime.config, "mail-accounts.json")
            if pending["id"] not in values or digest(values[pending["id"]]) != pending["fingerprint"]:
                raise PermissionError("Mail configuration changed. Connect again.")
            tokens["expires_at"] = time.time() + min(int(tokens.get("expires_in", 3600)), 86400)
            values[pending["id"]]["tokens"] = tokens
            values[pending["id"]]["email_address"] = address
            save_private(self.runtime.config, "mail-accounts.json", values)

    async def token(self, scope, key, profile, *, send=False):
        async with self.lock:
            account = self.account(scope, key, profile, send=send)
            tokens = account.get("tokens", {})
            if tokens.get("expires_at", 0) > time.time() + 60 and tokens.get("access_token"):
                return account, tokens["access_token"]
            if not tokens.get("refresh_token"):
                raise PermissionError("Connect this mail account with browser consent.")
            payload = {"grant_type": "refresh_token", "client_id": account["client_id"], "refresh_token": tokens["refresh_token"]}
            if account.get("client_secret"):
                payload["client_secret"] = account["client_secret"]
            refreshed = await bounded_json("POST", self.endpoints(account["provider"])[1], data=payload)
            if not refreshed.get("access_token"):
                raise PermissionError("Mail authorization expired. Connect again.")
            tokens = {**tokens, **refreshed, "expires_at": time.time() + min(int(refreshed.get("expires_in", 3600)), 86400)}
            values = load_private(self.runtime.config, "mail-accounts.json")
            if key not in values or values[key] != account:
                raise PermissionError("Mail configuration changed.")
            values[key]["tokens"] = tokens
            save_private(self.runtime.config, "mail-accounts.json", values)
            return values[key], tokens["access_token"]

    async def request(self, scope, key, profile, method, path, *, send=False, account_fingerprint=None, **kwargs):
        account, token = await self.token(scope, key, profile, send=send)
        if account_fingerprint and digest({k: v for k, v in account.items() if k != "tokens"}) != account_fingerprint:
            raise PermissionError("Mail account changed. Review and save a new draft.")
        if send:
            check_write(self.runtime)
        base = "https://gmail.googleapis.com/gmail/v1/users/me/" if account["provider"] == "gmail" else "https://graph.microsoft.com/v1.0/me/"
        if path.startswith(("/", "http")) or ".." in path:
            raise ValueError("Invalid mail operation.")
        headers = {"Authorization": "Bearer " + token, "Prefer": 'outlook.body-content-type="text"', **kwargs.pop("headers", {})}
        return await bounded_json(method, base + path, headers=headers, **kwargs)

    async def messages(self, scope, key, profile, query="", cursor=""):
        account = self.account(scope, key, profile)
        if len(query) > 500 or len(cursor) > 4000:
            raise ValueError("Mail search or cursor is too long.")
        if account["provider"] == "gmail":
            params = {"maxResults": 10, "q": query or "in:inbox"}
            if cursor:
                params["pageToken"] = cursor
            result = await self.request(scope, key, profile, "GET", "messages", params=params)
            messages = await asyncio.gather(*[
                self.message(scope, key, profile, item["id"], metadata=True) for item in result.get("messages", [])[:10]
            ])
            return {"messages": messages, "next": result.get("nextPageToken", ""), "limit": 10}
        params = {"$top": 10, "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,internetMessageId", "$orderby": "receivedDateTime desc"}
        if query:
            params.pop("$orderby")
            params["$search"] = '"' + query.replace('"', "") + '"'
        path = "messages"
        if cursor:
            parsed = urlsplit(cursor)
            if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or parsed.path != "/v1.0/me/messages" or parsed.fragment:
                raise ValueError("Invalid mail pagination cursor.")
            path, params = "messages?" + parsed.query, None
        result = await self.request(scope, key, profile, "GET", path, params=params)
        return {"messages": [self.graph_message(item) for item in result.get("value", [])[:10]],
                "next": result.get("@odata.nextLink", ""), "limit": 10}

    def graph_message(self, item):
        opaque(item.get("id"))
        body = item.get("body", {})
        return {"id": item["id"], "subject": item.get("subject", ""), "from": item.get("from", {}).get("emailAddress", {}).get("address", ""),
                "to": [x.get("emailAddress", {}).get("address", "") for x in item.get("toRecipients", [])],
                "date": item.get("receivedDateTime", ""), "unread": not item.get("isRead", True),
                "body": plain(body.get("content", "")) if body.get("contentType", "").casefold() == "html" else body.get("content", "")[:50000],
                "snippet": item.get("bodyPreview", "")[:1000], "internet_message_id": item.get("internetMessageId", ""),
                "truncated": len(body.get("content", "")) > 50000}

    async def message(self, scope, key, profile, message_id, *, metadata=False):
        account = self.account(scope, key, profile)
        path = "messages/" + opaque(message_id)
        result = await self.request(scope, key, profile, "GET", path, params={"format": "metadata" if metadata else "full"} if account["provider"] == "gmail" else None)
        opaque(result.get("id"))
        if result["id"] != message_id:
            raise ValueError("The provider returned a different message identity.")
        if account["provider"] == "microsoft":
            return self.graph_message(result)
        payload = result.get("payload", {})
        headers = {x["name"].casefold(): x["value"] for x in payload.get("headers", [])[:100]}
        texts, attachments = [], []
        queue = [(payload, 0)]
        visited = 0
        while queue and visited < 100:
            part, depth = queue.pop()
            visited += 1
            if depth > 16:
                continue
            if part.get("filename"):
                attachments.append({"name": part["filename"][:300], "size": part.get("body", {}).get("size", 0)})
            encoded = part.get("body", {}).get("data", "")
            if encoded and len(encoded) <= 300000 and part.get("mimeType") in {"text/plain", "text/html"}:
                try:
                    text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", errors="replace")
                    texts.append(plain(text) if part["mimeType"] == "text/html" else text)
                except ValueError:
                    pass
            queue.extend((child, depth + 1) for child in part.get("parts", [])[:100])
        body = "\n".join(texts)
        return {"id": result["id"], "thread_id": result.get("threadId", ""), "subject": headers.get("subject", ""),
                "from": headers.get("from", ""), "to": headers.get("to", ""), "date": headers.get("date", ""),
                "body": body[:50000], "snippet": result.get("snippet", "")[:1000], "internet_message_id": headers.get("message-id", ""),
                "unread": "UNREAD" in result.get("labelIds", []), "attachments": attachments, "truncated": len(body) > 50000 or bool(queue)}

    async def drafts(self, scope):
        rows = await self.db.fetchall("SELECT * FROM mail_drafts WHERE scope=? ORDER BY updated_at DESC LIMIT 100", (scope,))
        return [{**row, "content": json.loads(row["content"])} for row in rows]

    async def draft(self, scope, key):
        row = await self.db.fetchone("SELECT * FROM mail_drafts WHERE scope=? AND id=?", (scope, key))
        if not row:
            raise ValueError("Mail draft not found in this scope.")
        return {**row, "content": json.loads(row["content"])}

    async def save_draft(self, scope, data: DraftData, profile, key=None, revision=None):
        account = self.account(scope, data.account_id, profile)
        content = data.model_dump()
        content["account_fingerprint"] = digest({k: v for k, v in account.items() if k != "tokens"})
        content["message_id"] = make_msgid(domain="jarvis.local")
        if data.reply_message_id:
            original = await self.message(scope, data.account_id, profile, data.reply_message_id)
            internet_id = original.get("internet_message_id", "")
            if not re.fullmatch(r"<[^\r\n<>]{1,500}>", internet_id):
                raise ValueError("The original message lacks a verified reply identity.")
            content["in_reply_to"] = internet_id
            content["thread_id"] = original.get("thread_id", "")
        encoded = json.dumps(content, sort_keys=True)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        async with self.lock:
            check_write(self.runtime)
            if key:
                changed = await self.db.execute(
                    "UPDATE mail_drafts SET content=?,sha256=?,account_id=?,revision=revision+1,updated_at=? WHERE id=? AND scope=? AND revision=? AND state='draft'",
                    (encoded, fingerprint, data.account_id, now(), key, scope, revision),
                )
                if not changed:
                    raise ValueError("Draft changed or is no longer editable.")
            else:
                key = uid()
                await self.db.execute("INSERT INTO mail_drafts(id,scope,account_id,content,sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                      (key, scope, data.account_id, encoded, fingerprint, now(), now()))
        return await self.draft(scope, key)

    async def send(self, scope, key, revision, sha256, profile):
        row = await self.draft(scope, key)
        if row["revision"] != revision or row["sha256"] != sha256:
            raise ValueError("Draft changed. Review its current recipients and content.")
        if row["state"] == "accepted":
            return {"state": "accepted", "id": key, "duplicate": True}
        if row["state"] != "draft":
            raise ValueError("Mail outcome requires reconciliation before retrying.")
        content = row["content"]
        account = self.account(scope, row["account_id"], profile, send=True)
        if digest({k: v for k, v in account.items() if k != "tokens"}) != content["account_fingerprint"]:
            raise PermissionError("Mail account changed. Review and save a new draft.")
        message = EmailMessage()
        if not account.get("email_address"):
            raise PermissionError("Connect again to verify the mailbox sender identity.")
        message["From"] = account["email_address"]
        for header, field in (("To", "to"), ("Cc", "cc"), ("Bcc", "bcc")):
            if content[field]:
                message[header] = ", ".join(content[field])
        message["Subject"], message["Message-ID"] = content["subject"], content["message_id"]
        if content.get("in_reply_to"):
            message["In-Reply-To"] = message["References"] = content["in_reply_to"]
        message.set_content(content["body"])
        ctx = active_task.get(None)
        effect = await self.db.fetchone("SELECT operation_key FROM effects WHERE task_id=? AND tool='mail_send' AND state='running' ORDER BY created_at DESC LIMIT 1", (ctx.id,)) if ctx else None
        check_write(self.runtime)
        changed = await self.db.execute("UPDATE mail_drafts SET state='sending',operation_key=?,updated_at=? WHERE id=? AND scope=? AND revision=? AND sha256=? AND state='draft'",
                                        (effect["operation_key"] if effect else "", now(), key, scope, revision, sha256))
        if not changed:
            raise ValueError("Mail is already sending or requires reconciliation.")
        try:
            if account["provider"] == "gmail":
                payload = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
                if content.get("thread_id"):
                    payload["threadId"] = content["thread_id"]
                await self.request(scope, row["account_id"], profile, "POST", "messages/send", send=True, account_fingerprint=content["account_fingerprint"], json=payload)
            else:
                await self.request(scope, row["account_id"], profile, "POST", "sendMail", send=True, account_fingerprint=content["account_fingerprint"],
                                   content=base64.b64encode(message.as_bytes()).decode(), headers={"Content-Type": "text/plain"})
        except BaseException:
            await self.db.execute("UPDATE mail_drafts SET state='unknown',updated_at=? WHERE id=? AND scope=?", (now(), key, scope))
            raise
        await self.db.execute("UPDATE mail_drafts SET state='accepted',updated_at=? WHERE id=? AND scope=?", (now(), key, scope))
        return {"state": "accepted", "id": key, "message": "The provider accepted the message; delivery is not yet verified."}


def install_mail_routes(app, runtime):
    @app.get("/api/mail/accounts")
    async def accounts(scope: Scope = "personal"):
        return runtime.mail.listing(scope)

    @app.post("/api/mail/accounts")
    async def save_account(data: MailAccount):
        return await runtime.mail.save(data)

    @app.post("/api/mail/accounts/{key}/connect")
    async def connect(key: str, data: MailContext):
        return await runtime.mail.begin(data.scope, key, data.privacy_revision)

    @app.delete("/api/mail/accounts/{key}")
    async def disconnect(key: str, data: MailContext):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.mail.disconnect(data.scope, key)

    @app.get("/oauth/mail/callback")
    async def callback(state: str = "", code: str = ""):
        await runtime.mail.callback(state, code)
        return HTMLResponse("<h1>Mail connected</h1><p>Return to Jarvis. You can close this window.</p>")

    @app.get("/api/mail/accounts/{key}/messages")
    async def messages(key: str, scope: Scope = "personal", query: str = "", cursor: str = ""):
        return await runtime.mail.messages(scope, key, runtime.config.settings.profile, query, cursor)

    @app.get("/api/mail/accounts/{key}/messages/{message_id}")
    async def message(key: str, message_id: str, scope: Scope = "personal"):
        return await runtime.mail.message(scope, key, runtime.config.settings.profile, message_id)

    @app.get("/api/mail/drafts")
    async def drafts(scope: Scope = "personal"):
        return await runtime.mail.drafts(scope)

    @app.post("/api/mail/drafts")
    async def create(data: DraftWrite):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.mail.save_draft(data.scope, data.draft(), runtime.config.settings.profile)

    @app.put("/api/mail/drafts/{key}")
    async def update(key: str, data: DraftWrite):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.mail.save_draft(data.scope, data.draft(), runtime.config.settings.profile, key, data.revision)

    @app.post("/api/mail/drafts/{key}/send")
    async def send(key: str, data: DraftAction):
        owner_write(runtime, data.scope, data.privacy_revision)
        ctx = TaskContext(f"mail-send:{key}:{data.revision}", "Send this exact reviewed draft", runtime.config.settings.profile, data.scope, external_authorized=True)
        marker = active_task.set(ctx)
        try:
            row = await runtime.mail.draft(data.scope, key)
            arguments = {"draft_id": key, "revision": data.revision, "sha256": data.sha256,
                         **{k: row["content"][k] for k in ("to", "cc", "bcc", "subject", "body")}}
            return await runtime.gateway.invoke("mail_send", arguments, "external",
                lambda: runtime.mail.send(data.scope, key, data.revision, data.sha256, ctx.profile))
        finally:
            active_task.reset(marker)

    @app.post("/api/mail/drafts/{key}/reconcile")
    async def reconcile(key: str, data: DraftReconcile):
        owner_write(runtime, data.scope, data.privacy_revision)
        async with runtime.mail.lock:
            check_write(runtime)
            row = await runtime.mail.draft(data.scope, key)
            if row["revision"] != data.revision or row["sha256"] != data.sha256 or row["state"] != "unknown":
                raise ValueError("Only the exact uncertain draft can be reconciled.")
            statements = [(
                "UPDATE mail_drafts SET state=?,revision=revision+1,updated_at=? WHERE id=? AND scope=? AND state='unknown'",
                ("accepted" if data.outcome == "accepted" else "draft", now(), key, data.scope),
            )]
            if row["operation_key"]:
                statements.append((
                    "UPDATE effects SET state=?,result=?,updated_at=? WHERE operation_key=? AND state IN ('unknown','running')",
                    ("succeeded" if data.outcome == "accepted" else "retry_allowed",
                     json.dumps({"state": data.outcome, "evidence": data.evidence}), now(), row["operation_key"]),
                ))
            await runtime.db.batch(statements)
            return await runtime.mail.draft(data.scope, key)

    @app.delete("/api/mail/drafts/{key}")
    async def delete(key: str, data: DraftAction):
        owner_write(runtime, data.scope, data.privacy_revision)
        row = await runtime.mail.draft(data.scope, key)
        if row["revision"] != data.revision or row["sha256"] != data.sha256 or row["state"] in {"sending", "unknown"}:
            raise ValueError("Draft changed or requires reconciliation.")
        await runtime.db.execute("DELETE FROM mail_drafts WHERE id=? AND scope=? AND revision=? AND sha256=?", (key, data.scope, data.revision, data.sha256))
        return {"state": "deleted"}
