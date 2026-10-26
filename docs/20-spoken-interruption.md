# Spoken interruption with echo protection

## Using it

The native Mac app offers **Settings → Voice → Microphone during playback → Automatic · interrupt by speaking**. Its environment value is `JARVIS_DESKTOP_VOICE_DUPLEX=echo_cancelled`, now the default for new configurations. Existing saved `gated` and `full` preferences remain valid. This feature applies to OpenAI Live desktop conversation; Windows/Linux remain text-only, and the Apple synthesis path retains manual interruption.

While Jarvis speaks, begin your next request without repeating the wake phrase. The app detects speech locally, stops the old playback, retains the beginning of the new request, and listens for its continuation. Normal conversation language and the selected voice/model remain unchanged. The optional wake-only invitation retains its separate timing policy.

`gated` keeps the existing manual interruption with ⌘⇧J. `full` sends input during playback for acoustically isolated headphones; it does not provide the automatic cut-in policy described here. Unsupported local processing falls back to protected, gated input instead of exposing speaker echo to the model. Settings and the orb use actual native capability reports when describing interruption availability.

## Echo cancellation and local speech detection

Automatic mode puts microphone capture and the response player in the **same AVAudioEngine** with VoiceProcessingIO enabled on its I/O nodes. The player therefore supplies the far-end audio reference used by the system echo canceller. Automatic gain control is disabled, and additional audio ducking is kept minimal. A separate capture-only voice-processing engine would lack this playback reference. Apple documents the required shared I/O processing and stopped-engine configuration in [What's New in AVAudioEngine](https://developer.apple.com/videos/play/wwdc2019/510/).

The already-processed microphone stream is converted once to mono PCM16 at 24 kHz. The local Apple SoundAnalysis classifier checks 500 ms overlapping windows for speech; loudness alone never triggers interruption. The model is supplied by macOS, without an external model download or cloud classification request. See [SNClassifySoundRequest](https://developer.apple.com/documentation/soundanalysis/snclassifysoundrequest).

Voice-processing capture may also expose auxiliary/reference channels. Conversion explicitly selects microphone channel zero with [AVAudioConverter.channelMap](https://developer.apple.com/documentation/avfaudio/avaudioconverter/channelmap), disabling implicit downmix. Tests check multichannel inputs, opposing auxiliary signals, and a silent microphone with a loud auxiliary channel. Input meters and recognition-liveness checks measure the converted PCM that both local recognition and OpenAI receive. Local diagnostics additionally expose raw/converted level scalars; no recording is needed to distinguish a routing problem from an unresponsive recognizer. Echo cancellation and speaker gating remain enabled.

The policy requires at least 0.80 speech confidence, active playback, enabled echo processing, and a fresh window captured after playback began. It rejects delayed results from the original question, malformed timestamps, and results more than 750 ms behind capture. Overlapping classifications can interrupt the same answer only once. A one-second recovery window also accepts speech that began during the gated playback tail; fully ungated follow-ups keep the existing connection. Analysis work runs away from the audio tap and has a bounded one-second queue; overload or classifier failure preserves the gated fallback.

The provider uplink stays silent during playback. A 1.5-second, processed microphone history remains local so the user's onset can be recovered when an interruption is confirmed. Playback is stopped immediately after that local confirmation. The audio snapshot seeds both the local recognizer and the new provider connection. Gating stays in place until actual queued playback and its trailing echo interval have finished; a gap between network packets alone is insufficient to reopen the uplink.

Stopping playback keeps a shared capture graph running. Muting or disabling capture stops and releases that graph, replacing it with output-only playback so a later spoken notification cannot restart the microphone. Privacy/scope changes clear local audio history and recognition seeds.

## Provider lifecycle and conversation continuity

GPT-Live WebSocket output has no response IDs, per-packet playback timestamps, or output-done boundary. Its documented playback controls require application-side queue handling. Jarvis therefore invalidates the old connection and clears queued output before accepting new audio, rather than guessing which late packets belong to the interrupted answer. The next request starts a fresh Live connection with the same configured model and voice. This follows the [Live session](https://developers.openai.com/api/docs/guides/live-conversations) and [playback control](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live) contracts.

An explicit handoff carries a random, single-use handle to recent text context held only in service RAM. It is bound to profile, scope, private mode, and privacy revision. Context is limited to twelve messages, 2,000 UTF-8 bytes per message, and 6,000 bytes in total. At most four handles are retained. An abandoned handoff expires automatically after 120 seconds. Connections closed without a requested handoff, plus service/emergency stop, discard it. Local mute drops the pending handle; an already detached handoff expires on the service timer. If the provider session has already ended, stopping its playback tail starts a fresh conversation.

Restored assistant text is marked incomplete and is explicitly described as context, not proof that it was heard. Startup history does not execute tools. Already accepted tasks keep their identity and may continue; stopping speech does not claim to undo an action. Dashboard approval rules remain in force. Raw microphone audio and private dialogue are never written by this handoff feature. Provider sessions still use `store=false` and the existing session duration, admission, and spending checks.

Interruption opens another voice connection only when recognized user speech starts a substantive request. Closing the previous connection uses normal usage reconciliation; no extra text-model call, synthetic greeting, or cloud VAD request is introduced.

## Verification and remaining device check

The current suite collects 138 Python tests and runs 84 native Swift scenarios. Added cases cover stale speech windows, protected fallback, single-trigger behavior, preserved audio onset, gated wire samples, bounded buffers, single-use context, privacy boundaries, timed RAM cleanup, and non-replay of accepted tasks. Frontend checks retain full English/Italian copy coverage.

An offline probe also exercised the actual Apple classifier with a bundled synthetic cue, without microphone capture or speaker playback. It identified speech and preserved absolute stream frame positions. That probe does not validate acoustic echo removal.

Actual speaker/microphone behavior requires a device check: request a multi-sentence answer, speak a new request during playback, and verify both that speech stops and that no follow-up command is generated from Jarvis's own voice. Room echo, volume, input/output devices, and very short or quiet speech affect detection. The classifier window and processing time add latency; an instantaneous stop is not promised. If the system cannot activate voice processing or local classification, manual interruption remains available and unprotected speaker input is not enabled automatically.
