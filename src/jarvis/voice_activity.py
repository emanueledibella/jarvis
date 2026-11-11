"""Audio activity for Live timeouts, independent of transcript delivery."""

from __future__ import annotations

import sys
from array import array
from dataclasses import dataclass


def has_signal(pcm: bytes, threshold: float) -> bool:
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return bool(samples) and sum(sample * sample for sample in samples) >= len(samples) * (32768 * threshold) ** 2


@dataclass
class VoiceActivity:
    last_activity: float
    last_input: float = float("-inf")
    playback_until: float = float("-inf")
    output_cursor: float = float("-inf")

    def input_transcript(self, now: float):
        self.last_input = now
        self.last_activity = now

    def input_audio(self, pcm: bytes, now: float):
        # Match the native processed-input threshold (RMS * 8 >= 0.1).
        # Silence packets must advance the provider clock without keeping an
        # abandoned connection open indefinitely. PCM on the wire is little endian.
        if has_signal(pcm, 0.0125):
            self.input_transcript(now)

    def output_audio(self, pcm: bytes, now: float):
        # Output may arrive faster than it plays. Include queued playback in
        # inactivity accounting rather than closing at the last transcript delta.
        self.output_cursor = max(now, self.output_cursor) + len(pcm) / 48000
        if has_signal(pcm, 0.00125):
            self.playback_until = self.output_cursor
            self.last_activity = now

    def input_quiet_for(self, now: float) -> float:
        return max(0, now - self.last_input)

    def idle_for(self, now: float) -> float:
        return max(0, now - max(self.last_activity, self.playback_until))
