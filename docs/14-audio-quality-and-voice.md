# Playback quality, vocal identity, and spoken sources

October 25, 2026. This update addresses packet-boundary crackling, a more conversational Italian vocal style, and unnecessary source narration in everyday answers.

## Reproduced audio defect

The previous player constructed a new `AVAudioConverter` for every audio packet. Each instance repeated resampler initialization and discarded its trailing filter samples. A synthetic one-second, 440 Hz PCM16 stream at 24 kHz, split into 29 irregular packets, produced only 47,072 output frames instead of 48,000. The largest packet-boundary amplitude step was about 0.676 on a normalized scale.

`PlaybackPCMConverter` now retains its converter across packets and drains its tail at normal end-of-stream. Stop, cancellation, privacy changes, and a new stream discard filter history. Tests compare fragmented conversion with a single continuous conversion, including tiny packets and a noninteger Apple synthesis sample-rate ratio. Output is 48,000 frames with zero sample error in the 24→48 kHz comparison; no microphone or hardware playback is required for these tests.

The player also starts with a 120 ms prebuffer and re-buffers after its queue drains. A bounded timer/end-of-stream starts shorter utterances. Incoming live playback is limited to eight seconds of queued frames. Mute/stop cancels pending startup and invalidates old completion callbacks. This reduces sensitivity to packet-arrival jitter; it cannot certify every physical output device or network.

References: [Apple AVAudioConverter sample-rate conversion](https://developer.apple.com/documentation/technotes/tn3136-avaudioconverter-performing-sample-rate-conversions), [OpenAI WebSocket PCM format](https://developers.openai.com/api/docs/guides/voice-websockets).

## Italian companion profile

The requested reference is the Italian film dialogue. The configurable profile describes an original adult male voice with a warm medium-low register, clear standard Italian, composed confidence, conversational emphasis, and natural pauses. It preserves its identity when switching languages. Its full default description is the `ITALIAN_COMPANION` constant in `src/jarvis/voice_style.py`.

Configure `JARVIS_DESKTOP_VOICE_STYLE` or Voice → Vocal style. Conversation rules and language switching remain separate from vocal qualities. Routine replies are brief and direct, without repeated stock preambles or formal completion announcements.

Cedar remains the default built-in voice. `JARVIS_DESKTOP_VOICE_NAME` also accepts a saved `voice_…` ID. Live sends a custom ID as `{"id": "voice_…"}` and includes the original description in session instructions. Private saved IDs must not be committed to a public repository.

A separate, explicit OpenAI prompt-to-voice request can create a dedicated timbre without uploading an actor or user recording. The API key needs `api.voices.write`. Creation does not run automatically on startup or consume a succession of trial voices. According to [OpenAI custom voice documentation](https://developers.openai.com/api/docs/guides/custom-voices), prompt-based creation is free, while using the saved voice is billed at normal Live rates. Check account permissions and current terms before creation. A rejected creation request does not change the working built-in voice.

Naturalness and resemblance remain listening judgments. Offline waveform tests verify audio continuity, not the quality or identity of provider-generated speech.

A saved original voice can be selected by its ID in local settings. Voice IDs, account permissions, provider responses, and personal acoustic-test records stay in private application data. The public repository contains only the general vocal profile and mock-provider regression tests.

Live probes must keep paced input audio running, including silence for a greeting. Without an advancing input timeline, a context append can remain pending and fail when the session closes. See [Managing GPT-Live sessions](https://developers.openai.com/api/docs/guides/live-conversations#start-with-a-greeting).

## The same voice on phone calls

When desktop voice is OpenAI Live, Twilio conversations now use the same model, built-in or saved voice, vocal description, response-language instructions and API-key selection. A prompt-generated `voice_…` ID requires Live; copying it into the older `tts-1` speech endpoint cannot reproduce that voice. The phone audio settings identify the shared voice and hide separate legacy STT/TTS fields while Live is selected.

The carrier verifies its signed webhook and PIN before opening any Live connection. Its initial PIN prompt uses an Italian or English carrier voice according to the response language, falling back to the recognition language in automatic mode. The conversation after verification uses the selected desktop voice. Phone μ-law audio passes through at 8 kHz with `audio/pcmu`; no second speech-recognition or synthesis model changes the voice or accent. Audio waits for `session.started` before being forwarded. See [OpenAI WebSocket audio formats](https://developers.openai.com/api/docs/guides/voice-websockets?api=live#choose-the-audio-format).

Backend requests still run through the phone task channel and existing permission gateway. A keypad approval requires the exact proposed tool/arguments in the outgoing transcript and a Twilio playback mark acknowledgment; an interrupted or altered readback cannot authorize an effect. Keypad digits remain in application code. Profile/privacy changes and shutdown stop the bridge, while accepted tasks retain their normal lifecycle. Phone Live reserves the phone duration plus a closing margin in the monthly voice ledger, finalizes provider-reported seconds and retains the reservation when usage is unknown. Carrier reservations remain separate.

## Citations appropriate to the request

The reasoning and voice models share `SOURCE_POLICY`:

- Weather, current time, simple calendar lookups, and task status: give the useful answer directly; do not automatically name the provider or recite citations.
- If the user asks for a source, a conflict matters, or uncertainty affects the answer: explain the relevant provenance.
- Substantial research, technical comparisons, and consequential claims: cite sources actually read and distinguish evidence from inference.
- Spoken answers do not read raw URLs, source IDs, or citation markup unless requested.

Tool results retain source metadata and remain inspectable in Tasks. Changing presentation does not remove verification or make the model invent facts. Private memory continues to preserve evidence and revisions.

An actual private, text-only request, “Che tempo fa a Roma?”, completed through GPT-6.1 Sol and the weather tool in 7.14 seconds, without naming the provider or adding an unsolicited source. No spoken provider audio was generated for that check. The 72-case Python suite and 31 native scenarios passed; the latter run without microphone access or speaker playback. Device listening remains the acceptance check for the new vocal delivery.
