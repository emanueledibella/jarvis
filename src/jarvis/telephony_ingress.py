"""Reject malformed public webhook admission before buffering request bodies."""

import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def webhook_signature(headers) -> str:
    values = (
        headers.getlist("x-twilio-signature")
        if hasattr(headers, "getlist")
        else [headers.get("x-twilio-signature", "")]
    )
    if len(values) != 1 or not isinstance(values[0], str):
        return ""
    return values[0] if re.fullmatch(r"[A-Za-z0-9+/]{27}=", values[0]) else ""


class TelephonyIngress:
    def __init__(self, app):
        self.app = app
        self.pending = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/telephony/"):
            await self.app(scope, receive, send)
            return
        if not webhook_signature(Headers(scope=scope)):
            await JSONResponse({"detail": "Invalid telephony signature."}, status_code=403)(
                scope, receive, send
            )
            return
        if self.pending >= 8:
            await JSONResponse({"detail": "Too many pending webhooks."}, status_code=429)(
                scope, receive, send
            )
            return
        self.pending += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.pending -= 1
