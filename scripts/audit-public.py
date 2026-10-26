"""Fail closed on private runtime files and identifying Git author metadata.

Secrets and free-text privacy review are complementary checks, not replaced here.
Output intentionally never prints an email, a home path, or a matched secret.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import PurePosixPath

PRIVATE_FILES = {
    ".env",
    "settings.json",
    "api-token",
    "mcp-servers.json",
    "calendar-oauth.json",
    "credentials.json",
    "secrets.json",
    "auth.json",
    ".netrc",
    ".npmrc",
    "lights.json",
    "project-root.txt",
    "requirements.lock",
}


def git(*args):
    return subprocess.check_output(["git", *args], text=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    errors = []
    names = git("ls-files").splitlines()
    if args.history:
        names += [
            row.partition(" ")[2]
            for row in git(
                "rev-list", "--objects", "--branches", "--tags", "--remotes=origin"
            ).splitlines()
        ]
        for line in git(
            "log", "--branches", "--tags", "--remotes=origin", "--format=%an%x00%ae%x00%cn%x00%ce"
        ).splitlines():
            parts = line.split("\0")
            for name, email in (parts[:2], parts[2:]):
                neutral = (name, email) == ("Jarvis Maintainers", "maintainers@example.invalid")
                handle = email.split("@", 1)[0].split("+")[-1]
                public_alias = (
                    email.endswith("@users.noreply.github.com")
                    and name == handle
                    and re.fullmatch(r"[A-Za-z0-9-]+", name)
                )
                if not neutral and not public_alias:
                    errors.append("Identifying author/committer metadata is present.")
    for value in names:
        path = PurePosixPath(value)
        if not value:
            continue
        if (
            path.name.casefold() in PRIVATE_FILES
            or (path.name.casefold().startswith(".env.") and path.name.casefold() != ".env.example")
            or path.suffix.lower()
            in {".db", ".sqlite", ".sqlite3", ".pem", ".p12", ".pfx", ".key", ".log", ".bundle"}
            or any(
                p in {"output", ".runtime", "oauth", ".venv", ".build-venv", ".bootstrap-venv"}
                or p.casefold().endswith(".app")
                for p in path.parts
            )
        ):
            errors.append("A private runtime file or local environment snapshot is tracked.")
    if errors:
        print("\n".join(sorted(set(errors))))
        raise SystemExit(1)
    print("Public-file inventory and Git identity policy passed.")


if __name__ == "__main__":
    main()
