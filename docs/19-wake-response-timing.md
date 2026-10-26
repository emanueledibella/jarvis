# Wake response timing

## Expected behavior

Saying only “Jarvis” can produce a brief local “Dimmi” or “Yes?” after a short pause. Continuing directly with a question suppresses this invitation. If wake recognition arrives late, the invitation expires instead of interrupting the question. OpenAI answers the substantive request without an additional activation greeting.

The listening invitation uses bundled, synthetic Cedar clips. It requires no network connection or per-wake generation request. These clips contain generic words, not microphone recordings or a person's cloned voice. Their provenance is recorded in the [resource notes](../native/Resources/README.md).

## Local timing and cancellation

`WakeAcknowledgement` uses microphone/recognizer timing rather than provider readiness:

- Wait at least 300 ms after the estimated end of the wake word and require 200 ms of microphone quiet.
- Never start the cue more than 800 ms after that boundary. A missed window remains silent.
- Suppress the cue for a command already included in the wake transcript, subsequent command text, or new microphone activity after the wake tail.
- Cancel it on mute, capture stop, recognition failure, profile/provider/language changes, and scope/privacy revocation. Lock handling retains the existing capture policy.

Apple transcription segment timestamps are mapped to the captured 24 kHz audio frame position. Wake trimming retains a 50 ms safety margin for adjacent syllables. Merged transcription segments preserve the command instead of trimming through it. Missing timing falls back to the detection time; actual acoustic detection delay still depends on the device.

## Audio and provider boundary

A wake-only pause keeps a rolling queue of at most 480,000 PCM bytes (10 seconds) in RAM. The existing listening timeout closes this local opening without starting a provider session. Once a substantive local transcript starts the cloud connection, the same queue retains the request onset. After streaming begins, overflow fails closed rather than silently losing speech.

The short local cue gates its own audio out of the provider stream. If the user begins during it, recognized request text stops playback and supplies a bounded, incomplete user prefix at Live startup. Backend delegation joins that prefix with the provider transcript, removing overlapping words. Cue-only partial transcripts do not start a cloud session. Private-mode prefix data follows the existing RAM-only task/transcript policy.

The Live prompt delegates activation feedback to the application and excludes delayed wake greetings. Startup text uses the documented user-input history contract; the implementation does not depend on invented response-cancellation or output-boundary events. See the [OpenAI Live conversation guide](https://developers.openai.com/api/docs/guides/live-conversations).

## Verification and practical limits

Automated checks use synthetic PCM and mock providers. They cover early/expired windows, silence and speech cancellation, language selection, cue echoes, bounded deferred buffering, timestamp trimming, delivery overflow, user-prefix deduplication, and private-session persistence. They neither capture the microphone nor play audio through the speakers.

Device validation should compare a wake-only pause, a continuous “Jarvis, che ore sono?”, and speech beginning during the cue. Recognition latency, room noise, speaker echo, and the perceived cue onset require listening on the actual Mac. A sufficiently noisy room may suppress the optional invitation; Jarvis can still accept the request. This change does not claim to remove model or network latency from the substantive answer.
