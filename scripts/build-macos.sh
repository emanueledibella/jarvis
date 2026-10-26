#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
if [[ ! -x .venv/bin/jarvis ]]; then
  print -u2 "Run scripts/setup.sh first."
  exit 1
fi
npm --prefix web run build
mkdir -p dist/Jarvis.app/Contents/MacOS dist/Jarvis.app/Contents/Resources
scripts/build-icon.sh
cp native/Info.plist dist/Jarvis.app/Contents/Info.plist
cp native/Resources/Jarvis.icns dist/Jarvis.app/Contents/Resources/Jarvis.icns
cp web/src/locales/it.json dist/Jarvis.app/Contents/Resources/Interface.it.json
cp native/Resources/WakeReady-*.wav dist/Jarvis.app/Contents/Resources/
print -rn -- "$JARVIS_PROJECT_DIR" > dist/Jarvis.app/Contents/Resources/project-root.txt
JARVIS_BUILD_ARCH="$(uname -m)"
swiftc -swift-version 5 -target "${JARVIS_BUILD_ARCH}-apple-macos14.0" -O -framework AppKit -framework WebKit -framework Speech -framework AVFoundation -framework CoreAudio -framework AudioToolbox -framework EventKit -framework ServiceManagement -framework UserNotifications -framework Carbon -framework Accelerate -framework NaturalLanguage -framework SoundAnalysis -framework CoreBluetooth native/Client.swift native/CalendarBridge.swift native/HueLightProtocol.swift native/HueBluetooth.swift native/RecognitionRecovery.swift native/AudioInput.swift native/SelectedAudioInput.swift native/LiveAudio.swift native/PlaybackAudio.swift native/SpokenLanguage.swift native/InterfaceLanguage.swift native/WakeAcknowledgement.swift native/BargeInPolicy.swift native/SpeechActivityDetector.swift native/VoiceEngine.swift native/App.swift -o dist/Jarvis.app/Contents/MacOS/Jarvis
codesign --force --deep --sign - --identifier it.jarvis.personal dist/Jarvis.app
print "Bundle created: $JARVIS_PROJECT_DIR/dist/Jarvis.app"
print "Open it with: open dist/Jarvis.app"
