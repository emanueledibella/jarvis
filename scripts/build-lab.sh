#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker build -f deploy/lab.Dockerfile --target python-sandbox -t jarvis-python-sandbox:local .
docker build -f deploy/lab.Dockerfile --target browser-sandbox -t jarvis-browser-sandbox:local .
docker build -f deploy/lab.Dockerfile --target broker -t jarvis-sandbox-broker:local .
