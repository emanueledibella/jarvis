"""Consistent stopped-core backups encrypted with the standard age format."""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

from .platforms import ServiceLock


def backup(directory: Path, destination: Path, recipient: str):
    directory, destination = directory.resolve(), destination.resolve()
    if not shutil.which("age"):
        raise ValueError("Install age before creating an encrypted backup.")
    if (
        not (directory / "jarvis.sqlite3").is_file()
        or destination.exists()
        or not recipient.startswith("age1")
    ):
        raise ValueError("Choose existing core data, a new backup filename and an age recipient.")
    if destination.is_relative_to(directory):
        raise ValueError("Backups must be written outside the core data directory.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = ServiceLock(directory / "service.lock")
    partial = destination.with_name(destination.name + ".partial")
    try:
        with tempfile.TemporaryDirectory(
            prefix=".jarvis-backup-", dir=destination.parent
        ) as scratch:
            files = []
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ValueError("Backup source must not contain symlinks.")
                if (
                    not path.is_file()
                    or path.name == "service.lock"
                    or path.name.endswith(("-wal", "-shm", ".tmp"))
                ):
                    continue
                relative = path.relative_to(directory)
                if path.suffix == ".sqlite3":
                    snapshot = Path(scratch) / relative
                    snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with (
                        sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source,
                        sqlite3.connect(snapshot) as target,
                    ):
                        source.backup(target)
                    files.append((snapshot, str(relative)))
                else:
                    files.append((path, str(relative)))
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                process = subprocess.Popen(
                    ["age", "-r", recipient],
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    with tarfile.open(fileobj=process.stdin, mode="w|gz") as archive:
                        for path, name in files:
                            archive.add(path, arcname=name, recursive=False)
                    process.stdin.close()
                    if process.wait(timeout=30) != 0:
                        raise ValueError("Backup encryption failed.")
                    output.flush()
                    os.fsync(output.fileno())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            partial.replace(destination)
    finally:
        lock.close()
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()


def restore(source: Path, destination: Path, identity: Path, *, max_bytes=20_000_000_000):
    if not shutil.which("age"):
        raise ValueError("Install age before restoring a backup.")
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Restore requires an empty destination, never an active data directory.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".jarvis-restore-", dir=destination.parent))
    process = subprocess.Popen(
        ["age", "-d", "-i", str(identity), str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        total, count = 0, 0
        with tarfile.open(fileobj=process.stdout, mode="r|gz") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                count += 1
                total += member.size
                if (
                    count > 100000
                    or total > max_bytes
                    or name.is_absolute()
                    or ".." in name.parts
                    or "\\" in member.name
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError("Backup contains unsafe or excessive archive entries.")
                member.mode = 0o700 if member.isdir() else 0o600
                archive.extract(member, staging, filter="data")
        if process.wait(timeout=30) != 0 or not (staging / "jarvis.sqlite3").is_file():
            raise ValueError("Backup authentication failed or the archive is incomplete.")
        freeze_restored_core(staging)
        if destination.exists():
            destination.rmdir()
        staging.replace(destination)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if staging.exists():
            shutil.rmtree(staging)


def freeze_restored_core(directory):
    """A historical snapshot must not resurrect device access or repeat old jobs."""
    with sqlite3.connect(directory / "jarvis.sqlite3") as database:
        tables = {
            row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "controls" in tables:
            database.execute(
                "INSERT INTO controls(name,value) VALUES('emergency_stop','1') ON CONFLICT(name) DO UPDATE SET value='1'"
            )
        if "schedules" in tables:
            database.execute("UPDATE schedules SET enabled=0")
    remote = directory / "remote.sqlite3"
    if remote.exists():
        with sqlite3.connect(remote) as database:
            database.execute("UPDATE devices SET revoked=?", (time.time(),))
            database.execute("DELETE FROM access_tokens")
            database.execute("UPDATE refresh_tokens SET revoked=1")
            database.execute("UPDATE pairing_codes SET used=?", (time.time(),))
            database.execute(
                "UPDATE executor_jobs SET state='unknown' WHERE state IN ('queued','delivered','claimed','running')"
            )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Stopped-core age-encrypted backup and restore")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("backup")
    create.add_argument("--data-dir", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--recipient", required=True)
    recover = sub.add_parser("restore")
    recover.add_argument("--archive", type=Path, required=True)
    recover.add_argument("--destination", type=Path, required=True)
    recover.add_argument("--identity", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        backup(args.data_dir, args.output, args.recipient)
    else:
        restore(args.archive, args.destination, args.identity)
    print("Completed.")


if __name__ == "__main__":
    main()
