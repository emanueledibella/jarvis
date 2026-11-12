"""Small shared wire primitives; executors do not import the model harness."""

import hashlib
import json

NATIVE_OPERATIONS = frozenset(
    {
        "calendar.list",
        "calendar.create",
        "calendar.update",
        "calendar.delete",
        "screen.capture",
        "window.list",
        "window.action",
    }
)
OPERATIONS = NATIVE_OPERATIONS | frozenset(
    {
        "workspace_list",
        "workspace_read",
        "workspace_search",
        "workspace_write",
        "workspace_mkdir",
        "workspace_command",
    }
)


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
