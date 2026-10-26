# Implementation design

This document turns the dossier into an implementation structure: one Mac with local/cloud models, MCP memory, persistent work, voice, and telephony.

## Decisions for the available Mac

The native host targets macOS 14 or later with Swift tools. Source builds require Python 3.12 and Node.js 22.12 or later. Hardware inventories and personal account configuration are not part of the public implementation record.

The desktop host uses **native AppKit/WebKit** with a shared React UI. This replaces the proposed Tauri candidate: no additional Rust/Chromium, and microphone/Speech/EventKit permissions belong directly to the macOS bundle. Python runs separately under host supervision; closing the window does not terminate it.

Apple Speech handles desktop wake detection exclusively on-device for the configured recognition language. “Jarvis” is matched in local text with word boundaries, keeping pre-activation audio on the device. This is not a dedicated trained acoustic detector; measure consumption, false triggers, and quality. OpenAI Live is an optional post-activation conversation path. Phone audio has its own adapter, optional local/configured cloud STT, and transport-compatible TTS. Pipecat is not mandatory where these paths already have clear ownership.

## Structure

```text
src/jarvis/        API, orchestration, policy, tools, data, scheduler, memory, telephony
web/               React dashboard and authenticated event client
native/            AppKit host, microphone/Speech, playback, EventKit, menu bar
scripts/           Setup, bundle/icon builds, phone proxy, checks
tests/             Persistence, policy, integration, and language regressions
docs/              Analysis, decisions, coverage state
assets/            Rendered app icon preview
```

## Main contracts

- Local API authenticated by a generated private-file token. Validate Host/Origin. The UI never receives provider credentials.
- `POST /api/chat`: create a task and return its ID; text/tools arrive through events.
- `/api/events`: authenticated stream with resume from observed sequence. Ephemeral audio levels are separate from persistent events.
- `/api/tasks`: read state, cancel, resume checkpoints, inspect pending decisions.
- `/api/schedules`: structured jobs with time zone, due time, misfire policy, separate escalation authority.
- `/api/memory`: recall, async ingestion, source status; no direct vault access.
- `/api/native`: heartbeat, native operations, correlated outcomes. Timeout does not imply success.
- `/api/voice/live`: authenticated loopback audio WebSocket; the Python backend alone holds the OpenAI key.
- `/telephony`: the only publicly proxied routes; signatures, identity, media-session checks required.

## Invariants

1. Success comes from a tool result, not just model prose.
2. Strict local forbids remote networking for memory, search, STT, and TTS too.
3. Coding processes do not inherit credentials; sensitive actions stop at a concrete proposal when authority is missing.
4. Effects use stable keys and become `unknown` when remote outcomes are unknown. Never blindly retry calls.
5. Private sessions persist no messages, checkpoints, or event content. Private work cannot resume after shutdown.
6. Second Brain remains the memory authority; adoption is checked separately from saving a source.
7. One coordinator owns database/scheduler, using a process lock and crash reconciliation.
8. Missing capabilities are explicit while independent capabilities remain available.
9. English product text does not force English conversations. A shared response-language policy applies to reasoning and OpenAI Live; the recognition locale is independent.

Installed versions are pinned in project/lock files. The dossier remains a requirements baseline. Record implementation/tests separately without claiming accounts/devices that were never exercised as verified.
