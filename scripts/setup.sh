#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
JARVIS_PYTHON="${JARVIS_PYTHON:-python3.12}"
if ! command -v "$JARVIS_PYTHON" >/dev/null; then
  print -u2 "Installa Python 3.12 e Node.js 22 prima del setup."
  exit 1
fi
if [[ ! -d .venv ]]; then "$JARVIS_PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
npm --prefix web ci --no-audit --no-fund
npm --prefix web run build
chmod +x scripts/build-macos.sh
scripts/build-macos.sh
