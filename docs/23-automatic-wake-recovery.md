# Automatic wake recognition recovery

The native recognizer already retries ended or stalled Speech tasks. Some failures need
the audio capture graph to be rebuilt as well. A local service watchdog now escalates
those failures automatically, using a dedicated native operation rather than an AI task.

## Detection and recovery

The service observes fresh native counters and state once per second. After a native
liveness retry, 12 seconds without further recognition progress can trigger a complete
capture restart. An idle/ended recognition task must remain unhealthy for 45 seconds;
stopped audio-buffer progress has a 60-second grace period. Fresh audio in a quiet,
lazily starting recognizer is healthy and does not trigger recovery.

Recovery is limited to one attempt at a time. Repeated unresolved failures back off for
30, 60, 120, 240, then at most 300 seconds between attempts, continuing at that bounded
cadence rather than requiring a manual retry. Recognition progress, including a wake
detected as a conversation starts, resets the failure backoff. Missing language assets,
disabled Dictation, or revoked permissions require their actual setup and are not
treated as software stalls that repeated resets could solve.

The watchdog starts and stops with the local service, independently of model calls. It
does not start listening invitations, play a cue, call a provider, write memories, or
record audio/transcripts. `GET /api/status` exposes counter-only `wake_recovery`
diagnostics; private local events record only the recovery state and reason.

## Execution safety

The watchdog requires fresh telemetry, a compatible native app, configured voice/wake
activation, and existing microphone/speech permission. It defers during voice dialogue,
phone media, playback, or processing. Mute, disabled voice, emergency stop, and the
owner's lock-screen preference remain authoritative.

Native operation claims recheck the current state and expected recognition/wake counters.
The Mac app then checks its own state again on the voice engine's main actor immediately
before the synchronous restart. A local mute, lock, permission change, resumed recognizer,
new wake, or new conversation after the server's check cancels recovery. The dedicated
`control.recover_wake` operation never changes the microphone-mute preference. A stale,
cancelled, timed-out, or already claimed operation cannot be replayed.

Older app bundles do not advertise `wake_recovery_supported` and cannot accidentally
interpret recovery as a manual unmute. An app update may require the owner's normal
macOS consent once for the changed bundle; automatic recoveries themselves never request
or bypass consent. Signing requirements and TCC data are not weakened or reset.

## Verification and publication privacy

Python tests exercise stalled/quiet listeners, stopped capture, transient and permanent
failures, bounded retries, progress recovery, queued-action races, cancellation, and
diagnostic redaction using fake clocks and the actual native bridge. Swift tests exercise
the production guard against changes in local voice state after the server check.
Full native compilation and signature verification check integration of that guard.

The public repository inventory additionally rejects private light registries, native
bundle/resource paths, credential dotfiles, and non-example dotenv files. Publication
checks scan staged source and public Git history with redacted secret scanning and
comparisons against locally configured credential/private-path values. A fresh public
clone is inspected separately; local configuration, credentials, diagnostic records, and
app build artifacts remain outside Git. Account values and raw matches are never included
in the public tests or this document.
