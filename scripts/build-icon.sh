#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
JARVIS_ICON_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-icon.XXXXXX")"
trap 'rm -rf "$JARVIS_ICON_DIR"' EXIT
mkdir -p "$JARVIS_ICON_DIR/Jarvis.iconset" native/Resources assets
swift scripts/render-icon.swift web/public/jarvis.svg assets/jarvis-icon.png
for JARVIS_ICON_SIZE in 16 32 128 256 512; do
  sips -z "$JARVIS_ICON_SIZE" "$JARVIS_ICON_SIZE" assets/jarvis-icon.png --out "$JARVIS_ICON_DIR/Jarvis.iconset/icon_${JARVIS_ICON_SIZE}x${JARVIS_ICON_SIZE}.png" >/dev/null
  JARVIS_RETINA_SIZE=$((JARVIS_ICON_SIZE * 2))
  sips -z "$JARVIS_RETINA_SIZE" "$JARVIS_RETINA_SIZE" assets/jarvis-icon.png --out "$JARVIS_ICON_DIR/Jarvis.iconset/icon_${JARVIS_ICON_SIZE}x${JARVIS_ICON_SIZE}@2x.png" >/dev/null
done
iconutil --convert icns --output native/Resources/Jarvis.icns "$JARVIS_ICON_DIR/Jarvis.iconset"
print "App icon generated from web/public/jarvis.svg."
