# Microphone selection

Open **Settings → Voice → Microphone**, use **Refresh microphones**, choose an input,
and **Save changes**. The input list contains available recording devices reported by
Core Audio, including the built-in microphone, connected Bluetooth headsets, and USB
inputs. The interface is available in English and Italian.

**Follow macOS default input** is the initial setting. Choosing a specific device pins
Jarvis to that microphone while other apps retain their own audio routing. Saving a
new choice ends an active voice conversation and rebuilds capture with that input.
Mute, disabled voice, emergency stop, lock-screen policy, and macOS permissions still
apply: changing the choice cannot enable a microphone the user has muted.

## Device changes and recovery

The private `microphone_device_uid` setting identifies a microphone across app launches
and hardware-ID changes. It can also be set with `JARVIS_MICROPHONE_DEVICE_UID`; an empty
value follows the system default, and an environment-specified value locks the GUI field.

An explicitly selected device never falls back to another microphone. If it disconnects,
listening pauses and the interface explains how to reconnect it or choose another input.
The saved UID remains selected in the menu even while unavailable. Reconnecting the same
device resumes capture, subject to the existing mute/lock/permission controls. Following
the system default instead follows changes made in macOS. Device availability is checked
locally every two seconds while voice is enabled and unmuted.

When the chosen microphone differs from the system default, a device-bound
[`AVCaptureDeviceInput`](https://developer.apple.com/documentation/avfoundation/avcapturedeviceinput)
captures its audio directly. PCM buffers feed the existing local recognition and voice
transport without changing the system input or output. This independent route uses
protected playback and manual interruption. When following the default, or when a pinned
device matches the default, the existing shared echo-processing graph remains available.
Changing the system default rebuilds the appropriate capture path while preserving a
pinned microphone. The interface reports actual echo cancellation/interruption availability;
the global shortcut remains available in protected mode.

Private processing aggregates are excluded from the picker. Audio is copied out of capture
sample buffers before entering the common pipeline, preserving channel layout and sample
rate while avoiding retained pointers into a recycled capture buffer.

The [wake watchdog](23-automatic-wake-recovery.md) still recovers a stalled recognizer or
capture graph. A disconnected pinned input waits for reconnection rather than repeatedly
resetting the graph or activating another physical microphone.

## Local-only metadata

The authenticated `GET /api/voice/inputs` endpoint retrieves a bounded native catalog
through `audio.inputs`. Listing devices requires no recording, permission request, model
call, or voice session. Device names and UIDs are returned only to the local settings UI;
they are not written into event history or sent to a model or Second Brain. The selected
UID is stored in private app settings. Public examples and tests use synthetic identifiers.
Native status exposes only route state and capture-running flags, without hardware IDs.

The selector requires the native Mac app. The Windows/Linux portable preview explicitly
reports the feature as unavailable and does not queue native operations.

## Verification

Native tests cover default versus pinned inputs, missing devices, duplicate names, exact
UID matching, disconnect/reconnect, hardware-ID changes, and unrelated default/name
changes, and when to use independent capture. PCM tests verify frame/channel fidelity,
owned buffer memory, and rejection of unready samples. Python tests exercise environment precedence, validation, authenticated catalog
retrieval through the actual bridge, settings synchronization, event redaction, and the
portable boundary. UI tests verify English/Italian labels, an unavailable saved selection,
disabled controls, and HTML escaping of device names. The full native bundle and web UI
are compiled as part of validation.
