#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
JARVIS_NATIVE_TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-native-tests.XXXXXX")"
trap 'rm -rf "$JARVIS_NATIVE_TEST_DIR"' EXIT
swiftc -swift-version 5 native/RecognitionRecovery.swift tests/native/RecognitionRecoveryTests.swift -o "$JARVIS_NATIVE_TEST_DIR/recognition-tests"
"$JARVIS_NATIVE_TEST_DIR/recognition-tests"
swiftc -swift-version 5 -framework AVFoundation native/Client.swift native/LiveAudio.swift tests/native/LiveAudioBufferTests.swift -o "$JARVIS_NATIVE_TEST_DIR/audio-tests"
"$JARVIS_NATIVE_TEST_DIR/audio-tests"
