# Native voice resources

`WakeReady-it.wav` (“Dimmi.”) and `WakeReady-en.wav` (“Yes?”) are generic, AI-generated Cedar listening cues created on October 26, 2026. They are application assets, not microphone recordings, personal data, or a cloned actor's voice.

Each file is mono, 24 kHz, signed 16-bit little-endian PCM in a WAV container with only format/audio chunks. Leading/trailing silence was trimmed and the edges faded to avoid clicks. Native playback uses a fixed 1.15 rate and the local timing/cancellation policy; no runtime speech-generation call is needed for these cues.

The two source clips were generated once with OpenAI's `gpt-4o-mini-tts` model, Cedar voice, and PCM output. Credentials, API responses, and intermediate audio are excluded from the repository. The conversation provider remains configured independently. Static playback does not depend on the generation model remaining available. Format and voice references: [OpenAI text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech).

See [wake response timing](../../docs/19-wake-response-timing.md) for behavior, tests, and acoustic validation limits.
