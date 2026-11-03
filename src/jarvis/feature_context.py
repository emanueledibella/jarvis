"""Shared boundaries for explicitly requested assistant features."""
from contextvars import ContextVar
from typing import Literal

Scope = Literal["personal", "work"]
owner_session_guard = ContextVar("jarvis_owner_feature_write", default=None)


def owner_write(runtime, scope: str, privacy_revision: int):
    session = runtime.voice_session
    if runtime.gateway.blocked:
        raise PermissionError("Emergency stop is active.")
    if session["private"]:
        raise PermissionError("Persistent changes are unavailable in a private session.")
    if scope != session["scope"] or privacy_revision != session["revision"]:
        raise PermissionError("Privacy or scope changed. Refresh before saving.")


def task_write(runtime, ctx):
    if runtime.gateway.blocked:
        raise PermissionError("Emergency stop is active.")
    if ctx.private:
        raise PermissionError("Persistent changes are unavailable in a private session.")


def check_write(runtime):
    """Recheck a direct UI action after awaits/locks, immediately before its effect."""
    if runtime.gateway.blocked:
        raise PermissionError("Emergency stop is active.")
    guard = owner_session_guard.get()
    if guard is not None:
        owner_write(runtime, guard[0], guard[1])
