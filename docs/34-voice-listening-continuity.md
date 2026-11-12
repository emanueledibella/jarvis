# Voice listening continuity

November 3, 2026.

Several independent boundaries used to look like a stopped or restarted microphone:

- The local command timer submitted the available transcript after ten seconds,
  even if microphone activity continued. An Apple recognition task's `isFinal`
  callback also submitted it immediately. A recoverable recognition error erased
  the partial command.
- Desktop Live inactivity used transcript arrival times. Missing or delayed text
  events could close a session during audio input or playback.
- Spoken interruption waited for a second local transcription before reconnecting.
  Recognition delay plus connection startup could exceed the ten-second audio queue.
- The explicit instruction against listening interjections applied only to the
  `gated` microphone mode. A short model interjection could start playback gating
  while the user still had more to say.
- Wake recovery escalated a past local recognition stall into a complete capture
  restart even when the replacement recognizer had received only quiet audio.

Local recognition now preserves the accepted prefix across task renewals and
replaces only the current task's partial hypothesis. It replays microphone input
captured during the short renewal gap. A recognition final event renews the
recognizer; the configured quiet period determines when to submit the command.
`listen_timeout_seconds` now measures inactivity while waiting for speech.
Mute, capture stop, and privacy/scope changes clear the retained prefix.

Live tracks audible PCM input, transcript progress, and the duration of queued
output separately. Silent keepalive packets do not keep an abandoned session
open. Backend delegation waits for the configured `end_of_turn_ms` quiet period,
includes transcript continuation received during that wait, and serializes request
selection so overlapping delegations do not submit the same request twice.
An incomplete request waiting at the duration cap is not dispatched.

Confident local interruption opens the replacement Live connection immediately
with the preserved audio onset and RAM conversation context. It does not wait for
another Apple transcript or briefly advertise a fresh idle wake state.
The Live prompt forbids listening interjections in every microphone mode.
Wake recovery now requires fresh, sustained audible input after the soft retry
before escalating a recognition stall. Quiet input, brief noise and stale audio
evidence cannot authorize that restart. An ended task, stopped capture, or
exhausted transient service error retains its separate recovery path.

These changes follow official OpenAI guidance on [audio-based inactivity and
session recovery](https://developers.openai.com/api/docs/guides/live-conversations#close-idle-sessions-and-resume)
and [backchannel policies](https://developers.openai.com/api/docs/guides/live-prompting#backchannels).
The model's turn-taking behavior remains probabilistic; prompt instructions do
not certify acoustic behavior on a physical device.

## Limits and diagnostics

The separately configured OpenAI maximum session duration remains enforced
(120 seconds by default, configurable up to 900). The idle timeout remains
30 seconds by default. Neither budget reservations nor privacy controls change.
Normal closure now reports `duration_limit`, `idle_timeout`, `provider_closed`,
`client_close`, `handoff`, or `stopped` to the native client, which logs the reason.
Recognition renewals and failures log operational state without transcripts or
recordings. Idle wake recognition still renews its local task approximately every
45 seconds; this is distinct from rebuilding microphone capture.

## Verification

Synthetic PCM and mocked-provider regressions cover long input without
transcripts, silent input/output, queued playback, premature overlapping
delegations, the duration cap during an incomplete request, conversation privacy,
budget accounting, and interruption context. Native tests cover multi-task
dictation, partial revisions, quiet periods, audio buffering and playback.

Run:

```sh
.venv/bin/pytest -q tests/test_voice_activity.py tests/test_live_voice.py tests/test_phone_live.py tests/test_voice_context.py tests/test_wake_watchdog.py tests/test_microphone_settings.py
./scripts/test-native.sh
./scripts/build-macos.sh
npm --prefix web test
```

Tests do not record the microphone, play through the speakers, or make paid voice
requests. Device listening should check a continuous request longer than ten
seconds, a thinking pause, a spoken interruption, and a quiet idle period. A
physical click or truncated model sound still requires that acoustic check.
