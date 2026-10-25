"""Package on the destination OS. Only public assets enter the distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web", action="store_true", help="Use an already-built web/dist")
    args = parser.parse_args()
    if not args.skip_web:
        npm = shutil.which("npm")
        if not npm:
            raise SystemExit("Install Node.js 22.12+ and npm to build the dashboard.")
        if sys.platform == "win32":
            # Execute npm's JS entrypoint directly, without cmd.exe quoting/.cmd rules.
            node = shutil.which("node")
            entrypoint = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
            if not node or not entrypoint.is_file():
                raise SystemExit(
                    "Use a standard Node.js installation, or build web and pass --skip-web."
                )
            npm_command = [node, str(entrypoint)]
        else:
            npm_command = [npm]
        subprocess.run(
            [*npm_command, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "web", check=True
        )
        subprocess.run([*npm_command, "run", "build"], cwd=ROOT / "web", check=True)
    if not (ROOT / "web/dist/index.html").is_file():
        raise SystemExit("web/dist is missing; build the dashboard first.")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "dist/portable"),
            "--workpath",
            str(ROOT / "build/portable"),
            str(ROOT / "packaging/jarvis.spec"),
        ],
        cwd=ROOT,
        check=True,
    )
    bundle = ROOT / "dist/portable/Jarvis"
    shutil.copyfile(ROOT / "packaging/PORTABLE-README.txt", bundle / "README.txt")
    shutil.copyfile(ROOT / ".env.example", bundle / "jarvis.env.example")
    shutil.copyfile(ROOT / "assets/jarvis-icon.png", bundle / "Jarvis.png")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    info = {
        "revision": revision,
        "os": sys.platform,
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    }
    (bundle / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n")
    for file in bundle.rglob("*"):
        if file.name in {
            ".env",
            "settings.json",
            "api-token",
            "jarvis.sqlite3",
            "checkpoints.sqlite3",
        }:
            raise SystemExit(f"Refusing to archive a private runtime file: {file.name}")
    system = {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}[sys.platform]
    architecture = {"AMD64": "x86_64", "aarch64": "arm64"}.get(
        platform.machine(), platform.machine()
    )
    name = f"Jarvis-{system}-{architecture}"
    releases = ROOT / "dist/releases"
    releases.mkdir(parents=True, exist_ok=True)
    extension = "zip" if sys.platform == "win32" else "gztar"
    archive = Path(
        shutil.make_archive(
            str(releases / name), extension, root_dir=bundle.parent, base_dir=bundle.name
        )
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Portable archive: {archive.name}")


if __name__ == "__main__":
    main()
