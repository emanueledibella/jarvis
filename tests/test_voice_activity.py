import struct

import pytest

from jarvis.voice_activity import VoiceActivity

SPEECH = struct.pack("<h", 2000) * 2400
SILENCE = bytes(4800)


def test_long_speech_keeps_voice_alive_without_transcript_callbacks():
    activity = VoiceActivity(0)
    for second in range(1, 181):
        activity.input_audio(SPEECH, second)
        assert activity.idle_for(second + 0.5) == 0.5
        assert activity.input_quiet_for(second + 0.5) == 0.5


def test_silence_and_low_background_noise_do_not_keep_idle_sessions_open():
    activity = VoiceActivity(0)
    for second in range(1, 61):
        activity.input_audio(SILENCE, second)
        activity.input_audio(struct.pack("<h", 30) * 2400, second)
        activity.output_audio(SILENCE, second)
    assert activity.idle_for(60) == 60


def test_output_playback_remains_active_after_audio_and_transcripts_arrive():
    activity = VoiceActivity(0)
    activity.output_audio(SPEECH * 20, 1)
    activity.output_audio(SPEECH * 30, 1.1)
    assert activity.playback_until == pytest.approx(6)
    assert activity.idle_for(5.9) == 0
    assert activity.idle_for(36) == pytest.approx(30)


def test_playback_timeline_includes_silent_packets_between_spoken_chunks():
    activity = VoiceActivity(0)
    activity.output_audio(SPEECH, 1)
    activity.output_audio(SILENCE * 10, 1)
    activity.output_audio(SPEECH, 1)
    assert activity.playback_until == pytest.approx(2.2)


def test_transcript_continuation_postpones_dispatch_without_raw_audio():
    activity = VoiceActivity(0)
    activity.input_transcript(40)
    assert activity.input_quiet_for(40.5) == 0.5
    assert activity.idle_for(40.5) == 0.5


def test_signed_pcm_activity_is_independent_of_polarity():
    activity = VoiceActivity(0)
    activity.input_audio(struct.pack("<h", -2000) * 2400, 5)
    assert activity.last_input == 5
