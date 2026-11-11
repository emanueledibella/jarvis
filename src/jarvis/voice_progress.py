"""One brief spoken status per turn, while the task is still running."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from .retrieval import PUBLIC_PAGE_TOOLS

EVENT = "task.progress"
DELAY_SECONDS = 1.5
KINDS = {
    "weather": "weather",
    "web_search": "web",
    **dict.fromkeys(PUBLIC_PAGE_TOOLS, "web"),
    "calendar_events": "calendar",
}
MESSAGES = {
    "it": {
        "weather": "Un attimo, controllo il meteo.",
        "web": "Un attimo, cerco online.",
        "calendar": "Un attimo, controllo il calendario.",
        "working": "Un attimo, ci sto lavorando.",
    },
    "en": {
        "weather": "One moment, I’ll check the weather.",
        "web": "One moment, I’ll look that up online.",
        "calendar": "One moment, I’ll check the calendar.",
        "working": "One moment, I’m working on it.",
    },
}

LIVE_PROGRESS_POLICY = """
After the user finishes, delegate promptly without announcing a separate preamble.
The backend can send a brief update beginning with "Progress:". Say it once in the
user's language as a natural statement about what you are doing. It is not a
question, a request for permission, or a result. Then wait for the verified
answer. If the answer is already available before you speak, go straight to it.
Do not read the label or repeat the update. If the user starts speaking again, listen.
"""


@asynccontextmanager
async def voice_progress(db, ctx, settings):
    sent = False
    locale = settings.language if settings.response_language == "auto" else settings.response_language
    messages = MESSAGES.get(locale.split("-")[0].lower(), MESSAGES["en"])

    async def announce(kind):
        nonlocal sent
        if not sent:
            sent = True
            await db.emit(EVENT, {"kind": kind, "text": messages[kind]}, ctx.id, private=ctx.private)

    async def tool_started(tool):
        if tool in KINDS:
            await announce(KINDS[tool])

    async def delayed():
        await asyncio.sleep(DELAY_SECONDS)
        await announce("working")

    ctx.voice_progress = tool_started
    fallback = asyncio.create_task(delayed())
    try:
        yield
    finally:
        ctx.voice_progress = None
        fallback.cancel()
        await asyncio.gather(fallback, return_exceptions=True)


async def task_progress(db, task_id):
    row = await db.fetchone(
        "SELECT id,data FROM events WHERE task_id=? AND type=? ORDER BY sequence DESC LIMIT 1",
        (task_id, EVENT),
    )
    return db.volatile.get(row["id"], json.loads(row["data"])) if row else {}


def live_progress(kind):
    return "Progress: " + MESSAGES["en"][kind]
