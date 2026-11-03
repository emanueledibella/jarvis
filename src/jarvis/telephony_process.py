"""Keep a telephony child alive only while its parent holds the stdin pipe open."""

from __future__ import annotations

import contextlib
import signal
import subprocess
import sys
import threading


def child_command(arguments: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "_telephony_child", *arguments]
    return [sys.executable, "-m", "jarvis.telephony_process", *arguments]


def run(arguments: list[str]) -> int:
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())

    def watch_parent():
        # EOF also arrives when the backend crashes or is killed. The native
        # child gets DEVNULL instead, so it cannot consume this lifetime pipe.
        try:
            sys.stdin.buffer.read()
        finally:
            stopped.set()

    threading.Thread(target=watch_parent, daemon=True).start()
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL)
    try:
        while process.poll() is None and not stopped.wait(0.1):
            pass
        return process.returncode or 0
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
