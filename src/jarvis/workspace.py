from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import signal
import sys
import tempfile
from pathlib import Path, PureWindowsPath

from .platforms import process_environment

SENSITIVE = {".env", "api-token", "settings.json", "credentials.json", "secrets.json"}


class Workspace:
    def __init__(self, roots: list[str]):
        self.roots = [Path(p).expanduser().resolve() for p in roots]

    def resolve(self, value: str, *, directory=False) -> tuple[Path, Path]:
        path = Path(value).expanduser()
        if not path.is_absolute():
            if not self.roots:
                raise ValueError("No workspace is configured.")
            path = self.roots[0] / path
        absolute = Path(os.path.abspath(path))
        for root in self.roots:
            if absolute.is_relative_to(root):
                rel = absolute.relative_to(root)
                if os.name == "nt" and any(
                    ":" in part or part.rstrip(" .") != part or PureWindowsPath(part).is_reserved()
                    for part in rel.parts
                ):
                    raise PermissionError(
                        "Windows device names, alternate streams and ambiguous paths are not allowed."
                    )
                if any(
                    part.casefold() in {".git", ".runtime", ".ssh", ".aws", ".venv", "node_modules"}
                    for part in rel.parts
                ):
                    raise PermissionError("Restricted path or excluded dependency.")
                if any(
                    part.casefold() in SENSITIVE
                    or part.casefold().startswith(".env.")
                    or part.casefold().endswith((".pem", ".key", ".p12"))
                    for part in rel.parts
                ):
                    raise PermissionError("Restricted file: the tool does not read secrets.")
                if not absolute.resolve().is_relative_to(root):
                    raise PermissionError("The symlink leaves the workspace.")
                if directory and not absolute.is_dir():
                    raise ValueError("Directory does not exist.")
                return root, rel
        raise PermissionError("The path is outside the enabled workspaces.")

    @contextlib.contextmanager
    def parent_fd(self, root: Path, relative: Path):
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def read(self, path: str) -> str:
        root, relative = self.resolve(path)
        if not relative.parts:
            raise ValueError("Specify a file.")
        if os.name == "nt":
            from .windows import read_text

            return read_text(root / relative)
        with self.parent_fd(root, relative) as parent:
            fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                import stat

                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 256_000:
                    raise ValueError("A regular text file up to 256 KB is required.")
                with os.fdopen(fd, "r", encoding="utf-8") as file:
                    fd = -1
                    return file.read(256_001)
            finally:
                if fd != -1:
                    os.close(fd)

    def write(self, path: str, content: str, expected_sha256: str | None = None) -> dict:
        import hashlib
        import stat

        if len(content.encode()) > 256_000:
            raise ValueError("Content exceeds 256 KB.")
        root, relative = self.resolve(path)
        target = root / relative
        old = self.read(path) if target.exists() else ""
        old_hash = hashlib.sha256(old.encode()).hexdigest()
        if target.exists() and expected_sha256 != old_hash:
            raise ValueError(
                "The file exists: read its current revision and supply expected_sha256."
            )
        if os.name == "nt":
            from .windows import locked_directory, replace_file

            with locked_directory(target.parent):
                fd, name = tempfile.mkstemp(prefix=".jarvis-write-", dir=target.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as file:
                        file.write(content)
                        file.flush()
                        os.fsync(file.fileno())
                    replace_file(Path(name), target)
                finally:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(name)
            return self.write_result(target, old, content, old_hash)
        with self.parent_fd(root, relative) as parent:
            mode = (
                stat.S_IMODE(os.stat(relative.name, dir_fd=parent, follow_symlinks=False).st_mode)
                if target.exists()
                else 0o600
            )
            name = ".jarvis-write-" + os.urandom(8).hex()
            fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    os.fchmod(file.fileno(), mode & 0o777)
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, relative.name, src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=parent)
        return self.write_result(target, old, content, old_hash)

    @staticmethod
    def write_result(target, old, content, old_hash):
        import difflib
        import hashlib

        return {
            "path": str(target),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "previous_sha256": old_hash,
            "diff": "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=str(target),
                    tofile=str(target),
                )
            )[:16000],
        }

    def mkdir(self, path: str):
        root, relative = self.resolve(path)
        if os.name == "nt":
            from .windows import locked_directory

            with contextlib.ExitStack() as locks:
                locks.enter_context(locked_directory(root))
                current = root
                for part in relative.parts:
                    current = current / part
                    current.mkdir(exist_ok=True)
                    locks.enter_context(locked_directory(current))
            return {"path": str(root / relative), "state": "created"}
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
        finally:
            os.close(fd)
        return {"path": str(root / relative), "state": "created"}

    def list(self, path: str = ".", limit=100) -> list[dict]:
        root, relative = self.resolve(path, directory=True)
        rows = []
        for entry in sorted((root / relative).iterdir()):
            try:
                self.resolve(str(entry))
            except PermissionError:
                continue
            rows.append(
                {"name": entry.name, "directory": entry.is_dir(), "symlink": entry.is_symlink()}
            )
            if len(rows) >= limit:
                break
        return rows

    def search(self, query: str, path=".", limit=50) -> list[dict]:
        root, relative = self.resolve(path, directory=True)
        rows = []
        examined = 0
        for base, directories, files in os.walk(root / relative, followlinks=False):
            directories[:] = [
                d
                for d in directories
                if not d.startswith(".")
                and d not in {"node_modules", "dist", "build", "vendor"}
                and not (Path(base) / d).is_symlink()
                and not (os.name == "nt" and (Path(base) / d).is_junction())
            ]
            for name in files:
                examined += 1
                if examined > 3000:
                    return rows
                file = Path(base) / name
                try:
                    content = self.read(str(file))
                except (ValueError, PermissionError, OSError, UnicodeError):
                    continue
                for line_number, line in enumerate(content.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        rows.append({"path": str(file), "line": line_number, "text": line[:500]})
                        if len(rows) >= limit:
                            return rows
        return rows

    async def command(self, command: str, cwd: str, mode: str, timeout: int) -> dict:
        root, relative = self.resolve(cwd, directory=True)
        if mode == "disabled":
            raise PermissionError("Command execution is disabled.")
        with tempfile.TemporaryDirectory(prefix="jarvis-worker-") as scratch:
            env = {
                **process_environment(),
                "JARVIS_WORKER_DIR": scratch,
                "TMPDIR": scratch,
                "LANG": "en_US.UTF-8",
                "PYTHONNOUSERSITE": "1",
            }
            env["TEMP"] = env["TMP"] = scratch
            if os.name == "nt":
                from .windows import system_executable

                args = [
                    system_executable("WindowsPowerShell/v1.0/powershell.exe"),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    base64.b64encode(command.encode("utf-16le")).decode("ascii"),
                ]
            else:
                args = (
                    ["/bin/zsh", "-f", "-c", command]
                    if sys.platform == "darwin"
                    else ["/bin/sh", "-c", command]
                )
            if mode == "sandbox":
                if sys.platform != "darwin" or not await asyncio.to_thread(
                    Path("/usr/bin/sandbox-exec").exists
                ):
                    raise PermissionError(
                        "The macOS sandbox is unavailable; there is no host fallback."
                    )

                def quoted(value):
                    return json.dumps(str(value))

                reads = " ".join(
                    f"(subpath {quoted(p)})"
                    for p in [
                        "/System",
                        "/usr",
                        "/bin",
                        "/sbin",
                        "/opt/homebrew",
                        "/Library/Developer",
                        sys.base_prefix,
                        sys.prefix,
                        root,
                        scratch,
                    ]
                )
                profile = f'(version 1)(deny default)(allow process-exec)(allow process-fork)(allow sysctl-read)(allow file-read* (literal "/"))(allow file-read-metadata)(allow file-read* {reads})(allow file-write* (subpath {quoted(root)}) (subpath {quoted(scratch)}))(allow file-read* file-write* (literal "/dev/null"))(deny network*)'
                args = ["/usr/bin/sandbox-exec", "-p", profile, *args]
            process_options = (
                {"creationflags": 0x200} if os.name == "nt" else {"start_new_session": True}
            )
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=root / relative,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **process_options,
            )
            output = bytearray()
            try:
                async with asyncio.timeout(timeout):
                    assert process.stdout
                    while chunk := await process.stdout.read(8192):
                        output.extend(chunk)
                        if len(output) > 65536:
                            raise ValueError("Output exceeds 64 KB: command stopped.")
                    await process.wait()
            finally:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        if os.name == "nt":
                            killer = await asyncio.create_subprocess_exec(
                                system_executable("taskkill.exe"),
                                "/PID",
                                str(process.pid),
                                "/T",
                                "/F",
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                            )
                            await asyncio.wait_for(killer.wait(), 5)
                            if process.returncode is None:
                                process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
            return {
                "exit_code": process.returncode,
                "output": output.decode(errors="replace"),
                "cwd": str(root / relative),
                "isolation": mode,
            }
