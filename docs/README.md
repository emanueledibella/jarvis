# Jarvis documentation

Updated November 4, 2026. The repository contains a local assistant and an
implemented remote core with desktop/mobile companions. Begin with
[Current state and verification](33-current-state-and-verification.md) and
[the changelog](../CHANGELOG.md) for delivered functionality, platform boundaries,
test results and remaining release work.

## Start here

| Goal | Guide |
| --- | --- |
| Install the local Mac app or Windows/Linux portable service | [Repository README](../README.md) |
| Deploy one always-on remote core | [Server operations](../deploy/README.md) |
| Build/pair macOS, Windows, iOS or Android companions and desktop executors | [Companion guide](../companions/README.md) |
| Configure companion wake/Live voice and Twilio with the native settings UI | [Companion parity and checks](35-companion-native-parity.md) |
| Configure Today, activities, mail, automations, documents, Jira/GitHub and Home Assistant | [Assistant setup](29-assistant-setup.md) |
| Set up the interactive browser, Python sandbox and Apple Health/HealthKit sharing | [Browser, Python and Health](37-browser-python-apple-health.md) |
| Find actual environment settings/defaults | [Configuration reference](12-configurazione-env.md) |
| Understand local/remote boundaries and data ownership | [Architecture](03-architettura.md), [remote implementation](32-remote-implementation.md) |
| Inspect delivered coverage and reproducible checks | [Current state](33-current-state-and-verification.md), [implementation/operations](11-implementazione-e-verifica.md) |
| Review authorization, credentials, privacy and publication | [Security policy](../SECURITY.md), [operations](07-configurazione-sicurezza-e-operativita.md), [dated audit](17-security-audit.md) |

Local AppKit/WebKit and the Mac companion support wake/audio in an awake user
session; mobile companions listen while open, with separate local consent.
Remote mode has one server authority, Electron macOS/Windows companions,
Capacitor iOS/Android companions and a separate outbound-WSS executor.
Server-side work can continue with the desktop off; its local files and Apple
capabilities cannot. Second Brain and Home Assistant need independently available
service/network paths.

## Complete document catalog

| Document | Contents and status |
| --- | --- |
| [01 — Vision and requirements](01-visione-e-requisiti.md) | Original 132-requirement baseline and subsequent assistant/remote scope additions; requirements are not all passed acceptance tests |
| [02 — GitHub/framework research](02-ricerca-github-e-framework.md) | Dated October 24 research; candidate frameworks are distinct from the delivered stack |
| [03 — Architecture](03-architettura.md) | Current local/remote topology, identities, tasks, device dispatch, data and availability |
| [04 — Voice, presence, telephony](04-voce-presenza-e-telefonia.md) | Initial voice/call design, with current native/companion/phone boundaries |
| [05 — Memory and integrations](05-memoria-e-integrazioni.md) | Second Brain authority, retrieval/adoption, implemented integration map and server reachability |
| [06 — Interface and dashboard](06-interfaccia-e-dashboard.md) | Design principles, command center, expanded assistant pages and responsive remote surfaces |
| [07 — Configuration/security/operations](07-configurazione-sicurezza-e-operativita.md) | Current configuration precedence, profiles, local/remote authority, privacy and recovery |
| [08 — Roadmap/validation/costs](08-roadmap-validazione-e-costi.md) | Original phases/targets, delivered milestones and remaining real-device/account acceptance; dated cost examples |
| [09 — Sources and decisions](09-fonti-e-decisioni.md) | Historical primary sources plus implemented decisions and source revision |
| [10 — Implementation design](10-progetto-esecutivo.md) | Current components, repository layout, contracts and invariants |
| [11 — Implementation and verification](11-implementazione-e-verifica.md) | Shared/local runtime operations, coverage and current remote extension |
| [12 — Environment configuration](12-configurazione-env.md) | All 99 shared settings, 12 remote server options, Compose/worker configuration and ownership |
| [13 — OpenAI voice](13-voce-openai.md) | Local Mac Live activation, delegation, language, RAM audio, budget; distinct from companion STT/TTS |
| [14 — Audio quality and vocal style](14-audio-quality-and-voice.md) | Native playback, vocal style, custom voice IDs, phone Live voice and source presentation |
| [15 — Command-center interface](15-command-center-interface.md) | HUD composition, real state, shared theme and dated UI checks |
| [16 — Cross-platform builds](16-cross-platform-builds.md) | Local Windows/Linux portable baseline, OS boundaries and build checks; separate from companion packages |
| [17 — Security audit](17-security-audit.md) | Dated findings/remediation, publication controls and remote trust boundaries |
| [18 — Interface language](18-interface-language.md) | English/Italian UI and local/remote preference ownership, independent of speech language |
| [19 — Wake response timing](19-wake-response-timing.md) | Local Mac listening cues, manual Live startup, bounded audio and timing checks |
| [20 — Spoken interruption](20-spoken-interruption.md) | Local Mac echo cancellation, speech detection and bounded RAM handoff |
| [21 — Lighting integrations](21-lighting-integrations.md) | Local Hue Bluetooth and MCP mappings/grants; remote home-control boundary |
| [22 — Default memory retrieval](22-default-memory-retrieval.md) | Automatic scoped Second Brain reads/writes, privacy and remote sessions |
| [23 — Automatic wake recovery](23-automatic-wake-recovery.md) | Local AppKit watchdog, guarded restarts, backoff and counter-only diagnostics |
| [24 — Microphone selection](24-microphone-selection.md) | Local Mac input choice/reconnect and private metadata; separate from companion microphones |
| [25 — Calendar specialist](25-calendar-assistant.md) | Shared deterministic calendar analysis, voice policy and Apple executor availability |
| [26 — Managed telephony](26-managed-telephony.md) | Local Caddy/Cloudflare lifecycle, reminder/Live preparation and remote external-ingress limits |
| [27 — Assistant expansion](27-assistant-expansion.md) | Eight feature groups, dated implementation gates and subsequent remote delivery |
| [28 — Companion architecture](28-companion-architecture.md) | Current client/identity overview and superseded Mac-first/React Native proposal |
| [29 — Assistant setup](29-assistant-setup.md) | Local/remote setup, OAuth callbacks, documents/screen/workspace limits and acceptance |
| [30 — Cloud feasibility](30-cloud-deployment-feasibility.md) | Dated VM benchmark/prices and current Compose sizing/deployment guidance |
| [31 — Core and device-agent analysis](31-remote-core-and-device-agents.md) | Historical alternatives and requirements; delivered choices explicitly mapped to chapter 32 |
| [32 — Remote implementation](32-remote-implementation.md) | Remote decisions, security, device jobs, packaging evidence and remaining release checks |
| [33 — Current state and verification](33-current-state-and-verification.md) | Consolidated modes, capabilities, API contracts, rerun regression totals and outstanding work |
| [34 — Voice listening continuity](34-voice-listening-continuity.md) | Latest workspace: retained dictation across recognition renewal, audio-aware Live inactivity/delegation and guarded wake recovery |
| [35 — Companion/native parity](35-companion-native-parity.md) | Shared settings and Twilio, local wake recognition, companion Live, device boundaries and current checks |
| [36 — OpenJarvis comparison](36-confronto-openjarvis.md) | Static comparison before implementing the selected extensions |
| [37 — Browser, Python and Apple Health](37-browser-python-apple-health.md) | Worker setup, permissions, Health imports, platform limits and verification |
| [38 — Harness review](38-harness-review.md) | Eight upstream harnesses, tool discovery, context limits, caching, loop guards and explicit coding mode |
| [39 — Window automation and WhatsApp shortcuts](39-automazione-finestre-e-scorciatoie-whatsapp.md) | Desktop window management, WhatsApp deep links, and zero-touch background sending via Apple Shortcuts |

The baseline catalog has 132 unique functional requirements: 96 P0, 34 P1 and two
P2. It predates the expanded assistant and remote delivery. Their acceptance
criteria are documented in chapters 01, 27, 32 and 33; this count is not a count of
tests or a claim that every original P0 has passed real-device acceptance.
Existing numbered filenames are retained to preserve links.

## Reading evidence correctly

Research chapters retain dated source snapshots; they do not establish current
competitor capabilities, prices or account eligibility. Early proposals are
identified where later implementation chose a different stack or delivery order.
The November 3 committed baseline is `6ff2d65`; subsequent voice-listening work
is present in the workspace and described in chapter 34. Documentation updates
do not turn either state into a signed production release.

Synthetic regressions verify contracts, scopes, effect handling and framework
execution. Dated native/container/browser/package checks have their own limits.
Personal OAuth consent, paid model quality, physical audio/device behavior,
carrier billing and push delivery require separate intended-account/device checks.
The earlier portable preview does not include all later source changes.

Keep account-specific outcomes and local diagnostic artifacts private. Deployment
requires real server/domain/credentials; iOS physical installs and push need
appropriate developer/project setup. One server owns scheduling; local and remote
cores never synchronize a live database or automatically fail over.
