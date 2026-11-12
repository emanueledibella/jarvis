# Implementation design

Updated November 3, 2026. The shared FastAPI/LangGraph/Deep Agents engine now
supports the original local installation and a separate remote core with companion
apps and desktop executors. See the [architecture](03-architettura.md) and
[current capability matrix](33-current-state-and-verification.md).

## Local implementation

The native host targets macOS 14+ and uses AppKit/WebKit with React. It supervises
Python, keeps the menu-bar service alive with the window hidden and owns native
microphone/Speech/EventKit permissions. This replaced the initial Tauri candidate.
Apple Speech handles local wake detection; optional OpenAI Live starts after
activation. Native code supplies playback, echo protection, microphone selection,
Hue Bluetooth, OCR and chosen-window context.

Windows/Linux portable mode packages the Python core and dashboard, opens the
system browser and retains its console lifecycle. It does not include the native
Mac voice/calendar stack. Local mode supports local/cloud models and dedicated
MCP credentials; no model weights or accounts ship in a package.

## Remote implementation

One server owns state, schedules, policy and model configuration. The core uses
external model APIs; keys stay on the server. Electron macOS/Windows companions
and Capacitor iOS/Android companions share React views and device contracts.
Their explicit record/transcribe/review/TTS flow is separate from native Live voice.

A separately paired desktop executor opens outbound WSS and applies local
workspace/read/write/command grants in addition to core approvals. EventKit and a
locally chosen window are supported through the macOS helper. The original AppKit
mode remains separate; it is not a remote companion or automatic offline fallback.

## Structure

```text
src/jarvis/        Shared core, assistant features, remote protocol, executor and backup
web/               Shared React dashboard, remote session/audio clients and mobile layout
native/            AppKit host and native audio/calendar/Bluetooth/OCR/window adapters
companions/        Electron desktop and Capacitor iOS/Android shells, vaults and sharing
deploy/            Linux Docker/Compose, isolated parser, Caddy and configuration examples
packaging/         Portable-core and executor PyInstaller specifications
scripts/           Setup/build, smoke, publication/security and native checks
tests/             Core/feature/device/privacy/protocol regressions and synthetic fixtures
docs/              Requirements, current operations, historical analysis and verification
assets/            Public application identity
```

## Contracts and invariants

- Local API uses its private owner token and HMAC peer verification. Remote API
  uses distinct short-lived device credentials, grants and `X-Jarvis-Session`.
- `POST /api/chat` accepts a stable request ID and creates a task. Approvals,
  task state and results stay in the common gateway/checkpoint/effect path.
- Local events use `/api/events`; remote clients poll `/remote/v1/events`.
  The local native bridge and Live WebSocket are denied remotely.
- Remote model/secret changes require administrator authority and current
  `ETag` / `If-Match`; stale settings are rejected.
- Core and executor both validate destination, scope, exact arguments and expiry.
  Existing-file writes require a current hash. Commands are not a code sandbox.
- Unknown effects require reconciliation, including after socket loss or restore.
  Transport receipt recovery does not replay an uncertain command.
- Private content remains in RAM; retained minimal metadata does not permit
  recovery of a private conversation after shutdown.
- Second Brain is the fact/evidence authority. Saved source and adopted memory
  are separate states. It needs independent server reachability in remote mode.
- Persistent assistant records, mail, integrations and event analysis share scope,
  privacy-revision and gateway checks. Event analysis is read-only.
- One core owns each database and scheduler. No active database is synchronized
  with the Mac; local standalone and remote mode have separate data/lifecycles.
- The remote parser has no network or core data/credentials. Encrypted age backup
  and conservative restore are implemented; signing/updating remain release work.
- English/Italian interface selection is independent of conversation language and
  recognition locale.

Tool results establish success; model prose alone does not. Installed versions
are pinned in manifests/lockfiles. Synthetic tests, historical portable releases,
development companion packages and real account/device acceptance are reported
separately in [the verification record](33-current-state-and-verification.md).
