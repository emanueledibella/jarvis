import asyncio
import json
import time

import pytest

from jarvis.wake_watchdog import WakeWatchdog


@pytest.fixture
async def watchdog(runtime):
    await runtime.wake_watchdog.close()
    clock = [100.0]
    monitor = WakeWatchdog(runtime, clock=lambda: clock[0])
    runtime.wake_watchdog = monitor

    def report(**changes):
        status = {
            "voice_state": "armed", "muted": False, "locked": False,
            "microphone": "authorized", "speech": "authorized", "on_device": True,
            "wake_recovery_supported": True, "barge_in": False,
            "recognition_task": "starting", "recognition_callbacks": 10,
            "wake_matches": 2, "input_buffers": 100, "recognition_recoveries": 0,
            **changes,
        }
        runtime.native.update_status(status)
        runtime.native.status_received_at = clock[0]

    report()
    return monitor, clock, report


async def queued_recovery(runtime, monitor):
    job = asyncio.create_task(monitor.tick())
    for _ in range(100):
        if runtime.native.operations:
            return job, next(iter(runtime.native.operations))
        if job.done():
            await job
            raise AssertionError("Expected a queued wake recovery")
        await asyncio.sleep(0.001)
    job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    raise AssertionError("Recovery did not reach the native bridge")


async def stalled(watchdog):
    monitor, clock, report = watchdog
    await monitor.tick()
    clock[0] += 5
    report(recognition_recoveries=1, input_buffers=200)
    await monitor.tick()
    clock[0] += monitor.stall_grace
    report(recognition_recoveries=1, input_buffers=300)


async def acknowledge(runtime, job, key):
    operation = runtime.native.claim(key)
    assert operation["operation"] == "control.recover_wake"
    assert operation["arguments"] == {"recognition_callbacks": 10, "wake_matches": 2}
    runtime.native.complete(key, {"state": "armed"})
    await job


async def test_failed_soft_recognition_retry_escalates_to_guarded_capture_restart(runtime, watchdog):
    monitor, clock, report = watchdog
    await stalled(watchdog)
    job, key = await queued_recovery(runtime, monitor)
    await acknowledge(runtime, job, key)
    assert monitor.restarts == monitor.attempts == 1
    assert monitor.last_reason == "recognition_stalled"
    assert not runtime.native.pending and not runtime.native.guards
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")
    assert not await runtime.db.fetchall("SELECT * FROM tasks")
    assert not await runtime.db.fetchall("SELECT * FROM memory_outbox")
    assert all(event["data"] == "{}" for event in await runtime.db.fetchall("SELECT * FROM events WHERE type IN ('voice.recovery','native.operation')"))
    clock[0] += 1
    report(recognition_recoveries=1, input_buffers=400)
    await monitor.tick()
    assert monitor.attempts == 1


async def test_quiet_starting_recognizer_with_fresh_audio_never_triggers_recovery(runtime, watchdog):
    monitor, clock, report = watchdog
    for index in range(100):
        clock[0] += 20
        report(input_buffers=100 + index * 100)
        await monitor.tick()
    assert not runtime.native.operations and monitor.attempts == 0


@pytest.mark.parametrize("problem,grace", [("idle", 45), ("capture", 60), ("unavailable", 12)])
async def test_stopped_task_capture_or_exhausted_transient_errors_recover(runtime, watchdog, problem, grace):
    monitor, clock, report = watchdog

    def observe():
        report(recognition_task="idle" if problem == "idle" else "starting",
               voice_state="unavailable" if problem == "unavailable" else "armed",
               error="The local speech service keeps stopping. (synthetic:1)" if problem == "unavailable" else None,
               input_buffers=100 if problem == "capture" else 100 + int(clock[0]))

    observe()
    await monitor.tick()
    for _ in range(grace - 1):
        clock[0] += 1
        observe()
        await monitor.tick()
    assert not runtime.native.operations
    clock[0] += 1
    observe()
    job, key = await queued_recovery(runtime, monitor)
    await acknowledge(runtime, job, key)
    assert monitor.restarts == 1


async def test_native_progress_resolves_a_stall_before_escalation(runtime, watchdog):
    monitor, clock, report = watchdog
    await monitor.tick()
    clock[0] += 5
    report(recognition_recoveries=1, input_buffers=200)
    await monitor.tick()
    clock[0] += 5
    report(recognition_recoveries=1, recognition_callbacks=11, wake_matches=3, input_buffers=300)
    await monitor.tick()
    clock[0] += 10
    report(recognition_recoveries=1, recognition_callbacks=11, wake_matches=3, input_buffers=400)
    await monitor.tick()
    assert monitor.attempts == 0 and not runtime.native.operations


@pytest.mark.parametrize("restriction", [
    "muted", "locked", "voice_disabled", "wake_disabled", "microphone_denied", "speech_denied",
    "missing_assets", "dictation_disabled", "legacy_app", "live_voice", "phone", "playback",
    "barge_in", "emergency", "disconnected", "stale_status", "listening", "processing",
])
async def test_recovery_respects_voice_privacy_activity_and_permanent_failures(runtime, watchdog, restriction):
    monitor, clock, report = watchdog
    await stalled(watchdog)
    status = runtime.native.status
    if restriction in {"muted", "locked", "barge_in"}:
        status[restriction] = True
    elif restriction in {"voice_disabled", "wake_disabled"}:
        runtime.config.update({"voice_enabled" if restriction == "voice_disabled" else "wake_enabled": False})
    elif restriction.endswith("_denied"):
        status["microphone" if restriction == "microphone_denied" else "speech"] = "not_authorized"
    elif restriction in {"missing_assets", "dictation_disabled"}:
        status.update(voice_state="unavailable", error="The selected language's local speech model is missing." if restriction == "missing_assets" else "macOS reports that Siri or Dictation is disabled.")
    elif restriction == "legacy_app":
        status["wake_recovery_supported"] = False
    elif restriction == "live_voice":
        runtime.live_voice.sessions.add(asyncio.Event())
    elif restriction == "phone":
        runtime.telephony.active.add("synthetic-call")
    elif restriction == "playback":
        runtime.audio["output"] = 0.5
    elif restriction == "emergency":
        runtime.gateway.blocked = True
    elif restriction == "disconnected":
        runtime.native.last_seen = 0
    elif restriction == "stale_status":
        runtime.native.status_received_at = clock[0] - monitor.status_max_age - 1
    else:
        status["voice_state"] = restriction
    await monitor.tick()
    assert monitor.attempts == 0 and not runtime.native.operations


@pytest.mark.parametrize("change", ["muted", "locked", "live_voice", "callbacks", "wake", "emergency", "assets", "new_instance"])
async def test_queued_recovery_is_cancelled_if_safety_or_progress_changes_before_claim(runtime, watchdog, change):
    monitor, _, _ = watchdog
    await stalled(watchdog)
    job, key = await queued_recovery(runtime, monitor)
    status = runtime.native.status
    if change in {"muted", "locked"}:
        status[change] = True
    elif change == "live_voice":
        runtime.live_voice.sessions.add(asyncio.Event())
    elif change == "callbacks":
        status["recognition_callbacks"] += 1
    elif change == "wake":
        status["wake_matches"] += 1
    elif change == "emergency":
        runtime.gateway.blocked = True
    elif change == "assets":
        status.update(voice_state="unavailable", error="The selected language's local speech model is missing.")
    else:
        status["input_buffers"] = 0
    with pytest.raises(PermissionError, match="cancelled"):
        runtime.native.claim(key)
    await job
    assert monitor.outcome == "cancelled" and monitor.restarts == 0
    assert not runtime.native.pending and not runtime.native.guards


async def test_repeated_transient_failures_keep_retrying_with_bounded_backoff(runtime, watchdog):
    monitor, clock, report = watchdog
    for index, delay in enumerate([30, 60, 120, 240, 300, 300]):
        report(voice_state="unavailable", error="The local speech service keeps stopping. (synthetic:1)")
        await monitor.tick()
        clock[0] += monitor.stall_grace
        report(voice_state="unavailable", error="The local speech service keeps stopping. (synthetic:1)")
        job, key = await queued_recovery(runtime, monitor)
        runtime.native.claim(key)
        runtime.native.complete(key, {"state": "unavailable"})
        await job
        assert monitor.attempts == index + 1
        assert monitor.next_attempt_at == clock[0] + delay
        assert monitor.outcome == "retry_pending"
        clock[0] = monitor.next_attempt_at


async def test_shutdown_cancels_unclaimed_recovery_and_removes_its_authority(runtime, watchdog):
    monitor, _, _ = watchdog
    await stalled(watchdog)
    job, key = await queued_recovery(runtime, monitor)
    job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    await monitor.close()
    with pytest.raises(PermissionError, match="expired"):
        runtime.native.claim(key)
    assert not runtime.native.pending and not runtime.native.guards


async def test_recovery_diagnostics_never_store_arbitrary_error_text(runtime, watchdog):
    monitor, clock, report = watchdog
    secret = "private-audio-fixture-must-not-be-logged"
    report(voice_state="unavailable", error="The local speech service keeps stopping. " + secret)
    await monitor.tick()
    clock[0] += monitor.stall_grace
    report(voice_state="unavailable", error="The local speech service keeps stopping. " + secret)
    job, key = await queued_recovery(runtime, monitor)
    await acknowledge(runtime, job, key)
    assert secret not in json.dumps(monitor.status())
    assert secret not in json.dumps(await runtime.db.fetchall("SELECT * FROM events"))


async def test_native_status_freshness_is_separate_from_poll_connectivity(runtime):
    runtime.native.update_status({"voice_state": "armed"})
    received = runtime.native.status_received_at
    assert 0 < received <= time.monotonic() and runtime.native.connected
    runtime.native.last_seen = time.monotonic()
    assert runtime.native.status_received_at == received


async def test_a_real_wake_resets_backoff_even_while_the_conversation_is_active(runtime, watchdog):
    monitor, clock, report = watchdog
    await monitor.tick()
    monitor.failures = 5
    monitor.next_attempt_at = clock[0] + monitor.maximum_interval
    clock[0] += 1
    report(voice_state="listening", recognition_callbacks=11, wake_matches=3, input_buffers=200)
    await monitor.tick()
    assert monitor.failures == 0
    assert monitor.next_attempt_at <= clock[0] + monitor.minimum_interval
    assert monitor.attempts == 0 and not runtime.native.operations
