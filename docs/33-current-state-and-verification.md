# Current state and verification

Reviewed November 3, 2026 against committed baseline `6ff2d65` and the subsequent
voice-continuity workspace changes described in [chapter 34](34-voice-listening-continuity.md). This is the current
capability map. Earlier dated experiments and proposals retain their original
scope; their test totals, prices and package results do not describe a new release.
Recent changes are listed in the [changelog](../CHANGELOG.md).

November 4 addition: [chapter 37](37-browser-python-apple-health.md) records the
interactive browser, isolated Python, direct iOS HealthKit sharing, installed
development companions and the verified remote deployment. Those newer results
extend this dated baseline; physical HealthKit consent remains an owner action.

## Deployment modes

| Mode | Authority and lifecycle | Clients and availability |
| --- | --- | --- |
| Local native macOS | AppKit supervises the local Python core; one private data directory and scheduler | React in WebKit, on-device wake, Apple/OpenAI Live voice, EventKit, Hue Bluetooth and chosen-window context; needs an awake, logged-in Mac |
| Local portable Windows/Linux | The launcher owns a local Python core and opens the system browser | Text dashboard and shared assistant features; console must remain open; Apple native capabilities are unavailable |
| Remote core | `jarvis server`, one SQLite/scheduler authority, external model APIs | Authenticated browser, Electron macOS/Windows and Capacitor iOS/Android; server-side work can continue with the desktop off |
| Remote desktop executor | Separate device identity, local grants and effect journal; outbound WSS | Authorized workspace files/commands on macOS/Windows; EventKit and a locally chosen window on macOS; needs the target computer online |

The local app and remote companion are separate modes. There is no automatic
offline failover, shared live database or bidirectional synchronization of two
cores. The remote core forces the cloud profile, disables host workspace commands
and local wake capture, and disallows server-side stdio MCP. A local model on a
desktop is not currently a remote inference backend. Linux portable support does
not imply a packaged Linux Electron companion.

Start with [server deployment](../deploy/README.md), [companion builds and
pairing](../companions/README.md), or [local installation](../README.md#native-macos-app).
The [architecture](03-architettura.md) and [remote implementation record](32-remote-implementation.md)
describe the shared engine and its distinct trust boundaries.

## Delivered assistant features

| Area | Implemented behavior | Code and verification |
| --- | --- | --- |
| Today and briefings | Scoped priorities, agenda/weather warnings, morning/evening schedules and meeting preparation | `daily.py`; `test_daily.py`, `test_calendar_assistant.py` |
| Personal organization | Projects, nested activities, revisions, due dates, estimates and proposed calendar work blocks | `organizer.py`; `test_organizer.py` |
| Mail | Gmail/Graph consent, ten-item pages, text rendering, local drafts, exact reviewed sends and uncertain-send reconciliation | `mail.py`; `test_mail.py` |
| Event automations | Quiet baseline, bounded polling, cooldown, seven-day history and read-only event analysis | `automations.py`; `test_automations.py` |
| Documents | PDF/DOCX/text/Markdown/CSV/PNG/JPEG extraction, cited parts, hashes, comparison, retention and temporary private sources | `documents.py`, `document_worker.py`, `document_service.py`; `test_documents.py`, `test_remote_services.py` |
| Screen context | One-shot macOS window picker, local OCR, session-bound preview and ten-minute RAM expiry | `screen.py`, `native/ScreenContext.swift`; `test_screen.py`, native OCR scenarios |
| Jira and GitHub | Scoped target allowlists, Jira Rovo OAuth, ten-result searches, PR head/CI evidence, optional approved issue/comment writes | `development.py`; `test_development.py`, `test_assistant_protocol.py` |
| Home Assistant | Dedicated MCP setup, discovery, default-denied tools, read/action grants, exact proposals and separate state readback | `home_assistant.py`; `test_home_assistant.py`, protocol fixtures |
| Calendar | Apple/Google/Microsoft/ICS adapters; deterministic ongoing/imminent/urgent/conflict/gap analysis | `calendar_assistant.py`, `integrations.py`; `test_calendar_assistant.py` |
| Memory and public research | Automatic scoped Second Brain reads and authorized dedicated writes; date-aware weather and bounded web recovery | `memory*.py`, `retrieval.py`, `integrations.py`; memory/weather/web recovery regressions |
| Native voice and lighting | Wake cues/recovery, spoken interruption, microphone selection, latest listening continuity and registered Hue Bluetooth/MCP lights | `native/`, `voice_activity.py`, `wake_watchdog.py`, `lighting.py`; Python and Swift regressions; [chapter 34](34-voice-listening-continuity.md) |
| Telephony | Managed local Caddy/Cloudflare lifecycle or external ingress, owner calling, opt-in PIN-protected inbound calls and Live/legacy audio | `telephony*.py`, `phone_live.py`; telephony/startup/recovery/security regressions |

Python modules are under [`src/jarvis/`](../src/jarvis/), regression files under
[`tests/`](../tests/). Account setup and functional acceptance are in the
[assistant setup guide](29-assistant-setup.md); the dated feature gates are in
[chapter 27](27-assistant-expansion.md).

Server-side sources work independently of the Mac only if their dependencies do.
Second Brain needs its own available host. Home Assistant needs a route from the
server to the home network. Apple Calendar, selected windows and desktop files
need their granted executor. Native Hue Bluetooth remains in the local AppKit
mode; it is not an operation of the remote executor.

Directory automations and `document_read_workspace` inspect the core host's
authorized workspace, not the paired desktop's folders. The remote core has no
host workspace grant by default. Use explicit device tools for desktop work and
upload/share a document for server extraction; a paired folder does not turn
into a remote filesystem mount or a background directory watcher.

## Remote contracts

The browser and companion use device access tokens, never the local owner bearer.
Pairing codes expire after ten minutes; access tokens after five minutes; rotating
refresh tokens after thirty days. Reusing a refresh token revokes its family.
An administrator companion can configure core models/keys and issue device codes.
An executor identity cannot administer the core or read conversations.

| Surface | Purpose |
| --- | --- |
| `/remote/v1/info`, `/remote/v1/pair`, `/remote/v1/refresh` | Protocol discovery, one-use enrollment and token rotation |
| `/api/*` with bearer and `X-Jarvis-Session` | Shared assistant operations, filtered by device grant, session, scope and privacy |
| `/api/settings` with `ETag` / `If-Match` | Versioned administrator settings; a stale save returns HTTP 409 |
| `/remote/v1/events?after=...` | Filtered event polling; local `/api/events` is not exposed remotely |
| `/remote/v1/devices`, `/remote/v1/pairing-codes`, `/remote/v1/devices/{id}/revoke` | Device inventory, enrollment and revocation |
| `/remote/v1/session/executor`, `/remote/v1/jobs`, `/remote/v1/jobs/{id}/cancel` | Executor selection and job visibility/cancellation |
| `/remote/v1/executor` | Outbound executor WebSocket |
| `/remote/v1/voice/transcribe`, `/remote/v1/voice/speak` | Explicit STT/TTS |
| `/remote/v1/authorizations`, `/oauth/mcp/{name}/callback`, `/oauth/mail/callback` | Initiating-device consent and public integration callbacks |
| `/remote/v1/push`, `/remote/v1/push/status` | Mobile push registration and configured-provider status |

Remote voice records 0.1–60 seconds as mono PCM16 WAV at 16 kHz. It transcribes,
lets the owner review/send the text, and optionally synthesizes up to 4,000
characters. It uses the configured `phone_stt_model`, `phone_tts_model` and
`phone_tts_voice`; it does not reuse a saved Live voice ID or provide ambient wake,
continuous Realtime dialogue or the native Mac echo/interruption pipeline.

Ordinary conversations can be continued across the owner's devices in the same
scope. Private tasks/sources require their originating session and keep content
in RAM. Push and desktop notices carry generic updates; opening one retrieves
details after authentication and does not approve an action.

Workspace reads, writes and commands are checked on the core and again against
local executor grants. Existing-file writes require the previously read SHA-256.
Commands require allowed prefixes and explicit local consent; they execute project
code with the OS user's authority. They are not a code sandbox. Offline queuing is
explicit, expires within ten minutes and is unavailable for private work.
Interrupted work can remain `unknown`; reconnection retransmits receipts, not an
unverified command. See [the executor guide](../companions/README.md#esecutore-e-permessi).

## Verification on November 3

The review first checked committed baseline `6ff2d65` (617 Python passes/two
skips, 14 web, two bridge and 181 native scenarios). Voice continuity changes then
appeared in the shared workspace, including new activity/listening-turn tests.
The affected complete Python, web and native suites were rerun; code fingerprints
were unchanged during that run. Current workspace results are:

| Check | Result | Reproduce from repository root |
| --- | --- | --- |
| Python | 631 passed, 2 skipped | `.venv/bin/pytest -q` |
| Web | 14 passed | `npm --prefix web test` |
| Desktop bridge | 2 passed | `npm --prefix companions test` |
| Native macOS | 191 scenarios passed, including ten listening-turn and two synthetic Vision OCR checks | `./scripts/test-native.sh` |

These tests use temporary data and synthetic providers. They do not exercise
personal accounts, paid model inference, physical device actions or live push.
The documentation review logs remain in ignored `output/documentation-review/`.

Documentation checks cover all 44 repository documents, local links/anchors,
balanced fences, the 97 shared and 12 remote option rows against the Python
schemas, documented remote routes against source decorators, and preservation of
the 132 baseline requirement IDs/priorities. The report is
`output/documentation-review/documentation-validation.json`. Dated external links,
vendor prices and old CI URLs were retained as historical references, not
revalidated as current external claims.

The earlier development build record, `dist/companions/verification.json`, reports
Linux ARM64 core/parser smoke tests, browser pairing/chat/approval/settings,
macOS ARM64 DMG/ZIP startup, Android debug `assembleDebug`/`lintDebug`, and an iOS
simulator build with share extension. It records a dirty development source
snapshot and artifact hashes; it is not a signed release manifest for this commit.
Those packaging/browser checks were not rerun merely to edit documentation.
Build commands and release limits are in [chapter 32](32-remote-implementation.md),
[deploy](../deploy/README.md) and [companions](../companions/README.md).

The October portable binaries belong to the [older portable baseline](16-cross-platform-builds.md#verification-results).
They do not establish current companion or expanded-feature coverage on Windows/Linux.
The remote Windows NSIS builder is configured in CI; local evidence does not show
an executed Windows companion build.

## Remaining deployment and product work

- Provision the chosen server/domain, configure independent service reachability,
  register public OAuth callbacks and test the selected model with real credentials.
- Sign/notarize desktop distributions, build for physical iOS devices and complete
  Android/iOS microphone, vault, share, background and push delivery checks.
- Verify macOS helper TCC/calendar/window consent with a stable signed identity;
  check revocation, sleep and reconnect on the actual computers.
- Run the configured Windows companion CI/build and retain its native results.
- Exercise real mail/calendar/Jira/GitHub/Home Assistant permissions and effects,
  phone routing/billing and acoustic voice behavior with intended accounts/devices.
- Schedule encrypted off-host backups and test restore: old devices/pairing are
  revoked, routines disabled, emergency stop enabled and pending dispatch uncertain.

Signed updates, remote desktop offline failover, arbitrary mouse/keyboard control,
delegated local inference, multi-user tenancy and core
high availability remain outside the delivered scope. No VM purchase, production
deployment, app-store publication or new account authorization is implied by the
source implementation or this documentation review.
