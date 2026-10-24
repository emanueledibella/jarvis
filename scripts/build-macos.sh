#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
if [[ ! -x .venv/bin/jarvis ]]; then
  print -u2 "Esegui prima scripts/setup.sh."
  exit 1
fi
if [[ ! -f web/dist/index.html ]]; then
  npm --prefix web run build
fi
mkdir -p dist/Jarvis.app/Contents/MacOS dist/Jarvis.app/Contents/Resources
cp native/Info.plist dist/Jarvis.app/Contents/Info.plist
print -rn -- "$JARVIS_PROJECT_DIR" > dist/Jarvis.app/Contents/Resources/project-root.txt
JARVIS_BUILD_ARCH="$(uname -m)"
swiftc -swift-version 5 -target "${JARVIS_BUILD_ARCH}-apple-macos14.0" -O -framework AppKit -framework WebKit -framework Speech -framework AVFoundation -framework EventKit -framework ServiceManagement -framework UserNotifications -framework Carbon -framework Accelerate native/Client.swift native/CalendarBridge.swift native/VoiceEngine.swift native/App.swift -o dist/Jarvis.app/Contents/MacOS/Jarvis
codesign --force --deep --sign - --identifier it.jarvis.personal dist/Jarvis.app
print "Bundle creato: $JARVIS_PROJECT_DIR/dist/Jarvis.app"
print "Aprilo con: open dist/Jarvis.app"
