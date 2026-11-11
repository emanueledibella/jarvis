"""Container entry point: never run untrusted Python directly on the core host."""
import base64
import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def safe_name(value):
    if not isinstance(value, str) or not value or len(value) > 120 or value in {".", ".."} or any(x in value for x in ("/", "\\", "\x00")):
        raise ValueError("Use a plain file name of at most 120 characters.")
    return value


def execute(payload):
    code = payload.get("code", "")
    if not isinstance(code, str) or not 1 <= len(code) <= 100_000:
        raise ValueError("Python code must contain 1–100000 characters.")
    inputs = payload.get("files", [])
    if not isinstance(inputs, list) or len(inputs) > 10:
        raise ValueError("Attach at most ten files.")
    timeout = min(max(int(payload.get("timeout", 20)), 1), 60)
    with tempfile.TemporaryDirectory(prefix="job-", dir="/tmp") as scratch:
        folder = Path(scratch)
        total = 0
        names = set()
        input_hashes = {}
        for item in inputs:
            name = safe_name(item["name"])
            if name in names:
                raise ValueError("Input file names must be unique.")
            names.add(name)
            raw = base64.b64decode(item["content"], validate=True)
            total += len(raw)
            if total > 12_000_000:
                raise ValueError("Attached files exceed 12 MB.")
            (folder / name).write_bytes(raw)
            input_hashes[name] = hashlib.sha256(raw).digest()
        with tempfile.TemporaryFile() as logs:
            process = subprocess.Popen(
                [sys.executable, "-I", "-u", "-c", code], cwd=folder,
                env={"PATH": os.defpath, "HOME": scratch, "TMPDIR": scratch,
                     "MPLBACKEND": "Agg", "MPLCONFIGDIR": scratch + "/.matplotlib",
                     "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                stdout=logs, stderr=subprocess.STDOUT, start_new_session=True,
            )
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            logs.seek(0)
            output = logs.read(16001)
        files, total = [], 0
        # No symlinks, device files, nested paths or host mounts.
        for path in sorted(folder.iterdir()):
            if path.name.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > 3_000_000 or len(files) >= 10:
                continue
            raw = path.read_bytes()
            if path.name in input_hashes and hashlib.sha256(raw).digest() == input_hashes[path.name]:
                continue
            total += len(raw)
            if total > 8_000_000:
                break
            files.append({"name": safe_name(path.name), "content": base64.b64encode(raw).decode()})
        return {"state": "timed_out" if timed_out else "succeeded" if process.returncode == 0 else "failed",
                "exit_code": process.returncode, "stdout": output[:16000].decode(errors="replace"),
                "truncated": len(output) > 16000, "files": files}


def main():
    raw = sys.stdin.buffer.readline(96_000_000)
    payload = json.loads(raw)
    key = payload.get("id")
    try:
        if payload.get("op") == "health":
            import importlib.util
            spec = importlib.util.spec_from_file_location("health_parser", Path(__file__).with_name("health_parser.py"))
            parser = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(parser)
            parse_export = parser.parse_export
            result = parse_export(base64.b64decode(payload["content"], validate=True),
                                  payload["timezone"], payload.get("days", 90))
        else:
            result = execute(payload)
        response = {"id": key, "result": result}
    except Exception as error:
        response = {"id": key, "error": str(error)[:300] if isinstance(error, ValueError) else "Sandbox processing failed."}
    print(json.dumps(response))


if __name__ == "__main__":
    main()
