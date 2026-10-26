from __future__ import annotations

import asyncio
import math
import time


class WakeWatchdog:
    """Recover local wake listening without inference, audio capture, or new consent.

    Native recognition first performs its own soft retries. A failed retry with
    no subsequent progress escalates to a guarded capture restart.
    Silence alone is not a failure. Native action claims recheck safety just
    before execution, so a queued recovery cannot override mute/lock/a new call.
    """

    stall_grace = 12.0
    idle_grace = 45.0
    capture_grace = 60.0
    status_max_age = 40.0
    minimum_interval = 30.0
    maximum_interval = 300.0

    def __init__(self, runtime, *, clock=time.monotonic):
        self.runtime = runtime
        self.clock = clock
        self.job: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.previous: tuple | None = None
        self.last_wake_count: int | None = None
        self.stall_since: float | None = None
        self.idle_since: float | None = None
        self.audio_progress_at: float | None = None
        self.next_attempt_at = 0.0
        self.failures = 0
        self.attempts = 0
        self.restarts = 0
        self.outcome = "monitoring"
        self.last_reason: str | None = None

    def start(self):
        if self.job is None or self.job.done():
            self.closed = False
            self.job = asyncio.create_task(self.run(), name="jarvis-wake-watchdog")

    async def close(self):
        self.closed = True
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)
            self.job = None

    async def run(self):
        while not self.closed:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Keep the monitor alive, without recording provider errors,
                # transcripts, account state, or arbitrary exception messages.
                self.outcome = "monitoring_error"
            await asyncio.sleep(1)

    @staticmethod
    def transient_unavailable(status):
        return status.get("voice_state") == "unavailable" and str(status.get("error", "")).startswith(
            "The local speech service keeps stopping."
        )

    def eligible(self, now):
        runtime = self.runtime
        settings, native = runtime.config.settings, runtime.native
        status = native.status
        age = now - native.status_received_at
        output = runtime.audio.get("output", 0)
        return bool(
            not self.closed and math.isfinite(now)
            and settings.voice_enabled and settings.wake_enabled
            and not runtime.gateway.blocked and native.connected
            and native.status_received_at > 0 and 0 <= age <= self.status_max_age
            and not status.get("muted", True)
            and (not status.get("locked", True) or settings.voice_on_lock_screen)
            and status.get("microphone") == "authorized" and status.get("speech") == "authorized"
            and status.get("on_device") is True and not status.get("barge_in", False)
            and status.get("wake_recovery_supported") is True
            and not runtime.live_voice.sessions and not runtime.telephony.active
            and not runtime.telephony.sockets
            and math.isfinite(output) and output <= 0.01
            and (status.get("voice_state") in {"armed", "recovering"} or self.transient_unavailable(status))
        )

    def reset_observation(self):
        self.previous = None
        self.stall_since = self.idle_since = self.audio_progress_at = None

    def reason(self, now):
        status = self.runtime.native.status
        values = tuple(status.get(key, 0) for key in (
            "recognition_callbacks", "wake_matches", "input_buffers", "recognition_recoveries"
        ))
        previous = self.previous
        self.previous = values
        if previous is None or any(current < before for current, before in zip(values, previous, strict=True)):
            self.stall_since = self.idle_since = None
            self.audio_progress_at = now
        else:
            if values[0] > previous[0] or values[1] > previous[1]:
                self.stall_since = None
                if status.get("voice_state") == "armed":
                    self.failures = 0
                    self.next_attempt_at = min(self.next_attempt_at, now + self.minimum_interval)
            elif values[3] > previous[3] and self.stall_since is None:
                self.stall_since = now
            if values[2] > previous[2]:
                self.audio_progress_at = now
        if self.transient_unavailable(status):
            if self.stall_since is None:
                self.stall_since = now
        idle = status.get("recognition_task") in {"idle", "completed", "finishing", "canceling", "unknown"}
        if status.get("voice_state") == "armed" and idle:
            if self.idle_since is None:
                self.idle_since = now
        else:
            self.idle_since = None
        if self.stall_since is not None and now - self.stall_since >= self.stall_grace:
            return "recognition_stalled"
        if self.idle_since is not None and now - self.idle_since >= self.idle_grace:
            return "recognition_ended"
        if status.get("voice_state") == "armed" and self.audio_progress_at is not None and now - self.audio_progress_at >= self.capture_grace:
            return "capture_stalled"
        return None

    async def tick(self):
        async with self.lock:
            current = self.clock()
            native = self.runtime.native
            if math.isfinite(current) and 0 <= current - native.status_received_at <= self.status_max_age:
                wake_count = native.status.get("wake_matches", 0)
                if self.last_wake_count is not None and wake_count > self.last_wake_count:
                    self.failures = 0
                    self.next_attempt_at = min(self.next_attempt_at, current + self.minimum_interval)
                self.last_wake_count = wake_count
            if not self.eligible(current):
                self.reset_observation()
                return
            reason = self.reason(current)
            if reason is None or current < self.next_attempt_at:
                return
            expected = tuple(native.status.get(key, 0) for key in ("recognition_callbacks", "wake_matches"))
            input_floor = native.status.get("input_buffers", 0)

            def still_safe():
                return (
                    self.eligible(self.clock())
                    and tuple(native.status.get(key, 0) for key in ("recognition_callbacks", "wake_matches")) == expected
                    and native.status.get("input_buffers", 0) >= input_floor
                )

            self.attempts += 1
            self.failures = min(self.failures + 1, 5)
            delay = min(self.maximum_interval, self.minimum_interval * 2 ** (self.failures - 1))
            self.next_attempt_at = current + delay
            self.last_reason, self.outcome = reason, "recovering"
            try:
                await self.runtime.db.emit("voice.recovery", {"state": "recovering", "reason": reason}, private=True)
                result = await native.invoke(
                    "control.recover_wake", {"recognition_callbacks": expected[0], "wake_matches": expected[1]},
                    timeout=8, guard=still_safe,
                )
                if result.get("state") == "armed":
                    self.restarts += 1
                    self.outcome = "restarted"
                elif result.get("state") == "cancelled":
                    self.outcome = "cancelled"
                else:
                    self.outcome = "retry_pending"
            except PermissionError:
                self.outcome = "cancelled"
            except Exception:
                self.outcome = "retry_pending"
            finally:
                self.reset_observation()
            await self.runtime.db.emit("voice.recovery", {"state": self.outcome, "reason": reason}, private=True)

    def status(self):
        return {
            "state": self.outcome, "attempts": self.attempts, "audio_restarts": self.restarts,
            "supported": self.runtime.native.status.get("wake_recovery_supported") is True,
            "last_reason": self.last_reason,
            "retry_in_seconds": max(0, math.ceil(self.next_attempt_at - self.clock())),
        }
