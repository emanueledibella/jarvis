#!/bin/zsh
set -euo pipefail
JARVIS_PROJECT_DIR="${0:A:h:h}"
cd "$JARVIS_PROJECT_DIR"
JARVIS_NATIVE_TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-native-tests.XXXXXX")"
trap 'rm -rf "$JARVIS_NATIVE_TEST_DIR"' EXIT
swiftc -swift-version 5 native/RecognitionRecovery.swift tests/native/RecognitionRecoveryTests.swift -o "$JARVIS_NATIVE_TEST_DIR/recognition-tests"
"$JARVIS_NATIVE_TEST_DIR/recognition-tests"
swiftc -swift-version 5 native/RecognitionRecovery.swift tests/native/WakeRecoveryGuardTests.swift -o "$JARVIS_NATIVE_TEST_DIR/wake-recovery-tests"
"$JARVIS_NATIVE_TEST_DIR/wake-recovery-tests"
swiftc -swift-version 5 -framework AVFoundation -framework CoreAudio -framework AudioToolbox native/AudioInput.swift tests/native/AudioInputTests.swift -o "$JARVIS_NATIVE_TEST_DIR/audio-input-tests"
"$JARVIS_NATIVE_TEST_DIR/audio-input-tests"
swiftc -swift-version 5 -framework AVFoundation native/Client.swift native/LiveAudio.swift tests/native/LiveAudioBufferTests.swift -o "$JARVIS_NATIVE_TEST_DIR/audio-tests"
"$JARVIS_NATIVE_TEST_DIR/audio-tests"
swiftc -swift-version 5 -framework NaturalLanguage native/SpokenLanguage.swift tests/native/SpokenLanguageTests.swift -o "$JARVIS_NATIVE_TEST_DIR/language-tests"
"$JARVIS_NATIVE_TEST_DIR/language-tests"
swiftc -swift-version 5 -framework AVFoundation native/Client.swift native/PlaybackAudio.swift tests/native/PlaybackAudioTests.swift -o "$JARVIS_NATIVE_TEST_DIR/playback-tests"
"$JARVIS_NATIVE_TEST_DIR/playback-tests"
swiftc -swift-version 5 native/Client.swift tests/native/ServiceTrustTests.swift -o "$JARVIS_NATIVE_TEST_DIR/service-trust-tests"
"$JARVIS_NATIVE_TEST_DIR/service-trust-tests"
swiftc -swift-version 5 native/InterfaceLanguage.swift tests/native/InterfaceLanguageTests.swift -o "$JARVIS_NATIVE_TEST_DIR/interface-language-tests"
"$JARVIS_NATIVE_TEST_DIR/interface-language-tests" web/src/locales/it.json

swiftc -swift-version 5 native/WakeAcknowledgement.swift tests/native/WakeAcknowledgementTests.swift -o "$JARVIS_NATIVE_TEST_DIR/wake-tests"
"$JARVIS_NATIVE_TEST_DIR/wake-tests"
swiftc -swift-version 5 native/BargeInPolicy.swift tests/native/BargeInPolicyTests.swift -o "$JARVIS_NATIVE_TEST_DIR/barge-in-tests"
"$JARVIS_NATIVE_TEST_DIR/barge-in-tests"
swiftc -swift-version 5 native/HueLightProtocol.swift tests/native/HueLightProtocolTests.swift -o "$JARVIS_NATIVE_TEST_DIR/hue-tests"
"$JARVIS_NATIVE_TEST_DIR/hue-tests"
