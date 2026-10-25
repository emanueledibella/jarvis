"""Operating-system boundaries shared by source and frozen distributions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def data_directory(system: str | None = None) -> Path:
    system = system or sys.platform
    if system == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif system == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    if not base.is_absolute():
        raise ValueError("The application data location must be absolute.")
    return base / "Jarvis"


def ui_directory() -> Path:
    if frozen():
        return Path(sys._MEIPASS) / "web/dist"
    return SOURCE_ROOT / "web/dist"


def default_env_file() -> Path:
    # A downloaded executable never adopts a random working directory's .env.
    return (
        Path(os.environ.get("JARVIS_DATA_DIR", data_directory())).expanduser() / ".env"
        if frozen()
        else SOURCE_ROOT / ".env"
    )


def protect_path(path: Path, *, directory=False):
    if os.name == "nt":
        from .windows import protect_path as protect_windows_path

        protect_windows_path(path, directory=directory)
    else:
        path.chmod(0o700 if directory else 0o600)


def process_environment() -> dict[str, str]:
    """Keep OS/tool discovery variables, never provider keys or unrelated secrets."""
    env = {"PATH": os.environ.get("PATH", os.defpath)}
    if os.name == "nt":
        for name in ("SystemRoot", "WINDIR", "PATHEXT"):
            if name in os.environ:
                env[name] = os.environ[name]
    return env


class ServiceLock:
    def __init__(self, path: Path):
        self.file = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.file.tell() == 0:
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another Jarvis instance owns this data directory.") from None

    def close(self):
        if not self.file.closed:
            if os.name == "nt":
                import msvcrt

                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


def capabilities() -> dict:
    mac = sys.platform == "darwin"
    return {
        "os": sys.platform,
        "distribution": "portable" if frozen() else "source",
        "native_voice": mac,
        "apple_calendar": mac,
        "command_sandbox": mac,
        "dashboard": True,
        "agents": True,
        "workspace_tools": True,
    }
