"""Durable, generic APNs/FCM notifications. Provider keys are server configuration."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi import Request

from .db import uid


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def signed_jwt(header, payload, pem):
    key = serialization.load_pem_private_key(pem, password=None)
    message = (
        b64(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64(json.dumps(payload, separators=(",", ":")).encode())
    ).encode()
    if header["alg"] == "ES256":
        der = key.sign(message, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return message.decode() + "." + b64(signature)


class RemotePush:
    def __init__(self, remote):
        self.remote, self.store, self.options = remote, remote.store, remote.options
        self.cache = {}
        self.last_error = ""

    def configured(self, platform):
        if platform == "ios":
            return bool(
                self.options.apns_team_id
                and self.options.apns_key_id
                and self.options.apns_private_key
            )
        return bool(self.options.fcm_service_account)

    async def enqueue(self, event_id, task_id=None):
        private_device = None
        if task_id:
            bound = await self.store.fetchone(
                "SELECT * FROM task_sessions WHERE task_id=?", (task_id,)
            )
            if bound and bound["private"]:
                private_device = bound["device_id"]
            if not bound:
                task = await self.remote.runtime.db.fetchone("SELECT private FROM tasks WHERE id=?", (task_id,))
                if task and task["private"]:
                    return
        rows = await self.store.fetchall(
            "SELECT p.device_id FROM push_devices p JOIN devices d ON d.id=p.device_id WHERE d.revoked IS NULL"
        )
        for row in rows:
            if private_device and row["device_id"] != private_device:
                continue
            await self.store.execute(
                "INSERT OR IGNORE INTO push_outbox(id,device_id,event_id,next_attempt,created) VALUES(?,?,?,?,?)",
                (uid(), row["device_id"], event_id, time.time(), time.time()),
            )

    async def authorization(self, platform, http):
        cached = self.cache.get(platform)
        if cached and cached[1] > time.time():
            return cached[0]
        if platform == "ios":
            token = signed_jwt(
                {"alg": "ES256", "kid": self.options.apns_key_id},
                {"iss": self.options.apns_team_id, "iat": int(time.time())},
                await asyncio.to_thread(Path(self.options.apns_private_key).read_bytes),
            )
        else:
            credentials = json.loads(
                await asyncio.to_thread(Path(self.options.fcm_service_account).read_text)
            )
            assertion = signed_jwt(
                {"alg": "RS256", "typ": "JWT"},
                {
                    "iss": credentials["client_email"],
                    "scope": "https://www.googleapis.com/auth/firebase.messaging",
                    "aud": "https://oauth2.googleapis.com/token",
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 3600,
                },
                credentials["private_key"].encode(),
            )
            response = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            if response.status_code != 200:
                raise ValueError("FCM authorization failed.")
            token = response.json()["access_token"]
        self.cache[platform] = (token, time.time() + 3000)
        return token

    async def send(self, row, http):
        platform = row["platform"]
        token = self.store.decrypt(row["token"])
        authorization = await self.authorization(platform, http)
        if platform == "ios":
            host = (
                "https://api.sandbox.push.apple.com"
                if self.options.apns_sandbox
                else "https://api.push.apple.com"
            )
            response = await http.post(
                host + "/3/device/" + token,
                headers={
                    "authorization": "bearer " + authorization,
                    "apns-topic": self.options.apns_topic,
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                    "apns-expiration": str(int(time.time()) + 3600),
                },
                json={
                    "aps": {
                        "alert": {"title": "Jarvis", "body": "Hai un aggiornamento."},
                        "sound": "default",
                    },
                    "event_id": row["event_id"],
                },
            )
            stale = response.status_code == 410 or (
                response.status_code == 400 and response.json().get("reason") == "BadDeviceToken"
            )
        else:
            project = json.loads(
                await asyncio.to_thread(Path(self.options.fcm_service_account).read_text)
            )["project_id"]
            if (
                not isinstance(project, str)
                or not project
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-:" for c in project)
            ):
                raise ValueError("Invalid FCM project identifier.")
            response = await http.post(
                f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
                headers={"authorization": "Bearer " + authorization},
                json={
                    "message": {
                        "token": token,
                        "notification": {"title": "Jarvis", "body": "Hai un aggiornamento."},
                        "data": {"event_id": row["event_id"]},
                        "android": {"ttl": "3600s"},
                    }
                },
            )
            stale = response.status_code == 404 and any(
                item.get("errorCode") == "UNREGISTERED"
                for item in response.json().get("error", {}).get("details", [])
            )
        if stale:
            await self.store.execute(
                "DELETE FROM push_devices WHERE device_id=?", (row["device_id"],)
            )
            return "expired"
        if response.status_code in {401, 403}:
            self.cache.pop(platform, None)
        if not 200 <= response.status_code < 300:
            raise ValueError("Push provider rejected the notification.")
        return "sent"

    async def run(self):
        recovery_at = 0
        async with httpx.AsyncClient(
            http2=True, timeout=15, trust_env=False, follow_redirects=False
        ) as http:
            while not self.remote.stopping:
                try:
                    if time.time() > recovery_at:
                        rows = await self.remote.runtime.db.fetchall(
                            "SELECT id,task_id FROM notifications WHERE created_at>datetime('now','-1 day') ORDER BY created_at DESC LIMIT 100"
                        )
                        for row in rows:
                            await self.enqueue(row["id"], row["task_id"])
                        recovery_at = time.time() + 60
                    await self.store.execute(
                        "UPDATE push_outbox SET state='expired' WHERE state='queued' AND created<?",
                        (time.time() - 86400,),
                    )
                    rows = await self.store.fetchall(
                        "SELECT o.*,p.platform,p.token FROM push_outbox o JOIN push_devices p ON p.device_id=o.device_id JOIN devices d ON d.id=o.device_id WHERE o.state='queued' AND o.next_attempt<? AND d.revoked IS NULL ORDER BY o.next_attempt LIMIT 20",
                        (time.time(),),
                    )
                    for row in rows:
                        if not self.configured(row["platform"]):
                            continue
                        try:
                            state = await self.send(row, http)
                            await self.store.execute(
                                "UPDATE push_outbox SET state=? WHERE id=?", (state, row["id"])
                            )
                            self.last_error = ""
                        except Exception as error:
                            self.last_error = type(error).__name__
                            attempts = row["attempts"] + 1
                            await self.store.execute(
                                "UPDATE push_outbox SET attempts=?,next_attempt=?,state=? WHERE id=?",
                                (
                                    attempts,
                                    time.time() + min(3600, 2**attempts * 15),
                                    "failed" if attempts >= 6 else "queued",
                                    row["id"],
                                ),
                            )
                except Exception as error:
                    self.last_error = type(error).__name__
                await asyncio.sleep(5)

    def install(self, app):
        @app.post("/remote/v1/push")
        async def register(request: Request):
            data = await request.json()
            platform, token = data.get("platform"), data.get("token")
            device = request.state.remote_device
            if (
                platform not in {"ios", "android"}
                or device["platform"] != platform
                or not isinstance(token, str)
                or not 16 <= len(token) <= 4096
                or any(c.isspace() for c in token)
            ):
                raise ValueError("Invalid push registration for this device.")
            if platform == "ios" and (
                len(token) > 256 or any(c not in "0123456789abcdefABCDEF" for c in token)
            ):
                raise ValueError("Invalid APNs token.")
            await self.store.execute(
                "INSERT INTO push_devices VALUES(?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET platform=excluded.platform,token=excluded.token,updated=excluded.updated",
                (device["id"], platform, self.store.encrypt(token), time.time()),
            )
            return {"state": "registered", "provider_configured": self.configured(platform)}

        @app.get("/remote/v1/push/status")
        async def status():
            return {
                "ios_configured": self.configured("ios"),
                "android_configured": self.configured("android"),
                "last_error": self.last_error,
            }
