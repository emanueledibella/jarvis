# OpenAI voice conversation

Desktop voice has two selectable paths. Apple keeps recognition/synthesis on the Mac. OpenAI Live uses `gpt-live-1` for audio dialogue and delegates reasoning/tools to Deep Agents. Text-model selection is independent and configured separately from voice. No personal model selection, account state, or provider credentials are published.

## Activation and audio

Apple Speech recognizes “Jarvis” on-device. ⌘⇧J also starts a conversation. A wake-only pause stays local; a short cached listening cue can play only in the initial quiet window. Beginning a request cancels that cue. Once request speech is recognized, the native client opens an authenticated loopback WebSocket to Python; only the service holds the OpenAI key. See [wake response timing](19-wake-response-timing.md).

Convert microphone input to mono 24 kHz PCM16. A 1.5-second pre-roll preserves the command onset despite local detection delay. Wake-word timestamps trim this buffer with a 50 ms safety margin. After activation, a bounded rolling RAM queue waits for a request before any cloud stream opens; input then continues during the open session. Buffers are cleared on mute, profile/scope/privacy change, or closure. Jarvis writes no microphone recording files; bundled synthetic listening cues are static application resources.

Play response audio as it arrives, deriving orb levels from actual buffers. This is AI-generated speech. OpenAI errors do not silently fall back to Apple synthesis; show the error.

Default `gated` mode suppresses microphone audio during playback and a short trailing interval, preventing speaker echo from generating another request. Already-captured command audio is preserved. ⌘⇧J lets the owner take the floor again. Isolating headphones can use `full` for listening during speech; verify acoustic isolation on the actual device.

Keep the MacBook lid open for the built-in microphone. Closed-lid use requires external input. Apple Silicon laptops physically disconnect that microphone: [Apple documentation](https://support.apple.com/en-gb/guide/security/secbbd20b00b/1/web/1).

## Independent interface and conversation languages

The interface can be English or Italian, independently of conversation language. Source comments and documentation are English. `response_language=auto` applies one shared language policy to Deep Agents and OpenAI Live. Complete Italian requests produce Italian replies; complete English requests switch to English. Fillers, accents, names, and English tool results do not change the conversation language. Before a substantive request, use the configured recognition locale as fallback.

Apple wake recognition still uses `language`, initially `it-IT`; it does not continuously auto-switch transcription locales. After activation OpenAI receives audio and can identify the spoken language independently. With the Apple synthesis path, local `NLLanguageRecognizer` chooses the response voice; an explicit voice ID takes precedence. Phone STT no longer pins transcription to Italian; fixed phone authentication/service prompts are English.

Set a preferred response tag, such as `it-IT` or `en-GB`, in Voice settings or `JARVIS_RESPONSE_LANGUAGE`; explicit requests can still switch language. Prompt design follows [OpenAI Live prompting](https://developers.openai.com/api/docs/guides/live-prompting) and the [multilingual voice policy guidance](https://developers.openai.com/api/docs/guides/voice-prompting).

## Reasoning and permissions

GPT-Live uses `client` delegation. Associate bounded transcript fragments with delegation offsets and create a Deep Agents task with a stable delegation ID. Capture model, scope, and privacy at startup. Duplicate delegation does not create another task.

Return results to voice only after the backend records outcomes. Local tools, Second Brain, and actions still use the gateway. A spoken “yes” does not approve mutations; proposals remain in the dashboard. Closing dialogue stops audio; accepted work may continue and remains visible in Tasks.

`local_strict` rejects cloud sessions. Profile/scope/privacy-revision changes block subsequent transmission. Private mode keeps task contents in RAM without persistent dialogue messages/checkpoints. Live sessions use `store=false`; this does not replace provider data-processing terms.

Architecture/delegation follow the [OpenAI Live guide](https://developers.openai.com/api/docs/guides/live) and [delegation contract](https://developers.openai.com/api/docs/guides/live-delegation). Transport follows the [official WebSocket guide](https://developers.openai.com/api/docs/guides/voice-websockets).

## Spending and availability limits

Configurable sessions default to a maximum 120 seconds and close after 30 seconds without conversational activity when no task is pending. Waiting for the wake phrase opens no OpenAI connection.

Reserve maximum duration plus closing margin in the monthly budget before connecting. On `session.closed`, record provider-reported cumulative seconds; without confirmation, retain the reservation. Text reasoning reserves separately in the same monthly ledger. Do not add cumulative usage updates together.

Initial voice rate: USD 0.05/minute. Configured GPT-6.1 Sol rates: USD 2 input / USD 10 output per million tokens, without cache/discount deductions. Recheck prices when changing model/service tier: [official pricing](https://developers.openai.com/api/docs/pricing), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## Configuration and verification

`JARVIS_DESKTOP_VOICE_*`, `JARVIS_RESPONSE_LANGUAGE`, and `JARVIS_CLOUD_REASONING_EFFORT` are in the [complete env schema](12-configurazione-env.md). A dedicated voice key is optional; the service can reuse the text key only for OpenAI at its official endpoint.

Automated simulated-provider checks cover actual Deep Agents delegation, deduplication, private sessions, budget, auth/Origin, malformed PCM, privacy revocation before the next send, and configured language instructions. Native tests cover bounded buffers, activation, overflow, resampler cleanup, Italian/English voice selection, explicit preference, fallback. These do not open microphones or generate provider audio.

Account-specific API and acoustic checks belong in private local records. The public regression suite uses mock providers and tests language instructions, privacy, interruption, and delegation without a real provider key.

Playback continuity, the Italian vocal profile, saved voice IDs, and selective spoken citations are documented in [chapter 14](14-audio-quality-and-voice.md).
