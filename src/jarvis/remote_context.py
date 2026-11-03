"""Request identity is separate from the service's local/native voice state."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class ClientContext:
    device_id: str
    session_id: str
    scopes: frozenset[str]
    session: dict


active_client: ContextVar[ClientContext | None] = ContextVar("jarvis_remote_client", default=None)


def session_state(fallback: dict) -> dict:
    client = active_client.get()
    return client.session if client else fallback
