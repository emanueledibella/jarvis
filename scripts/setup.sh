#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
JARVIS_PYTHON="${JARVIS_PYTHON:-python3.12}"
if ! command -v "$JARVIS_PYTHON" >/dev/null; then
  print -u2 "Install Python 3.12 and Node.js 22 before setup."
  exit 1
fi
if [[ ! -d .bootstrap-venv ]]; then "$JARVIS_PYTHON" -m venv .bootstrap-venv; fi
.bootstrap-venv/bin/python -m pip install --upgrade pip==26.2.2 uv==0.13.5
.bootstrap-venv/bin/python -m uv sync --locked --managed-python --extra dev --inexact
npm --prefix web ci --no-audit --no-fund
chmod +x scripts/build-macos.sh
scripts/build-macos.sh
