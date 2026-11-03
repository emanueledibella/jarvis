"""Run on each desktop target; the bundle contains no private runtime data."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run(
    [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(root / "dist/executor"),
        "--workpath",
        str(root / "build/executor"),
        str(root / "packaging/executor.spec"),
    ],
    cwd=root,
    check=True,
)
