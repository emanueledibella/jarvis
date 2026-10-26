# Jarvis — analysis and implementation

Analysis started **October 24, 2026**, with subsequent voice, language, interface, portable build, and security updates. Version **0.1.0** includes the native Mac app and a portable Windows/Linux service/dashboard preview. Start with the [project README](../README.md) and [operations guide](11-implementazione-e-verifica.md). Chapters 01–09 preserve the initial dossier; 10–24 describe implemented choices and verification.

## Confirmed decisions

- **Initial Mac-only installation**, extended to portable Windows/Linux builds at the owner's request. No external server required for the core; native wake/desktop voice still requires the Mac app.
- **Both cloud and local models**, configurable and selectable for work.
- Voice activation by saying **“Jarvis”**, without opening a window each time.
- Local/MCP tools, web research, programming, everyday tasks, existing Second Brain memory.
- Real-time two-way phone dialogue as a complete-product capability.
- Futuristic HUD-inspired interface, central audio-reactive orb, quick weather/calendar information.
- Analysis followed by implementation at the owner's request. Future work remains explicitly identified in coverage.
- English/Italian interface selection with **Italian conversation retained** and automatic response-language adaptation.

**Local availability:** The Mac app works with its window closed while logged in. Portable Windows/Linux keeps running while its service console remains open. Shutdown, sleep, or missing connectivity limit timely work/calls. Apply explicit recovery rules on wake. A server is a later evolution.

## Recommendation and implementation

The service uses **Python + LangGraph + Deep Agents**, a common policy/tool gateway, Second Brain MCP memory, persistent scheduling, and separate voice handling. **AppKit/WebKit + React** replaced the initial Tauri candidate and assigns macOS permissions directly to the bundle. Apple on-device Speech handles wake detection; OpenAI Live optionally handles post-activation conversation; Twilio has its own adapter. Rationale: [implementation design](10-progetto-esecutivo.md).

This selection follows documented comparisons/product constraints. Pipecat and LiveKit remain evaluated alternatives, not mandatory dependencies. Actual implementation experiments are recorded separately. Sources: [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview), [Pipecat](https://github.com/pipecat-ai/pipecat), [LiveKit Agents](https://github.com/livekit/agents).

## Reading the dossier

| Document | Contents |
| --- | --- |
| [01 — Vision and requirements](01-visione-e-requisiti.md) | Scenarios, identified functional requirements, priorities, acceptance |
| [02 — GitHub/framework research](02-ricerca-github-e-framework.md) | Projects, reusable ideas, limitations, licenses |
| [03 — Architecture](03-architettura.md) | Mac processes, flows, agents, persistence, contracts, technical decisions |
| [04 — Voice, presence, telephony](04-voce-presenza-e-telefonia.md) | Wake phrase, interruption, audio, calls, availability, failures |
| [05 — Memory and integrations](05-memoria-e-integrazioni.md) | Existing Second Brain, adoption, calendar, tools, search |
| [06 — Interface and dashboard](06-interfaccia-e-dashboard.md) | Screens, orb, widgets, accessibility, onboarding, application icon |
| [07 — Configuration/security/operations](07-configurazione-sicurezza-e-operativita.md) | Proposed env contract, local/cloud profiles, authorization, lifecycle |
| [08 — Roadmap/validation/costs](08-roadmap-validazione-e-costi.md) | Phases, experiments, targets, dependencies, cost model |
| [09 — Sources and decisions](09-fonti-e-decisioni.md) | Primary sources, inspected revisions, local evidence, open decisions |
| [10 — Implementation design](10-progetto-esecutivo.md) | Implemented choices, components, invariants |
| [11 — Implementation and verification](11-implementazione-e-verifica.md) | Operations, real/automated tests, coverage, remaining checks |
| [12 — Environment configuration](12-configurazione-env.md) | All 93 implemented settings |
| [13 — OpenAI voice](13-voce-openai.md) | GPT-Live, multilingual policy, delegation, RAM audio, privacy, budget |
| [14 — Audio quality and vocal style](14-audio-quality-and-voice.md) | Continuous playback, Italian companion profile, custom voice IDs, selective spoken citations |
| [15 — Command-center interface](15-command-center-interface.md) | Original HUD composition, live states, responsive layout, shared theme, asset delivery, verification |
| [17 — Security audit](17-security-audit.md) | Publication privacy, corrected security boundaries, regression evidence and residual trust limits |
| [18 — Interface language](18-interface-language.md) | English/Italian UI, persistence, native menus, independent voice language |
| [19 — Wake response timing](19-wake-response-timing.md) | Local listening cues, cancellation during requests, expired greetings, bounded audio, verification limits |
| [20 — Spoken interruption](20-spoken-interruption.md) | Shared echo cancellation, local speech detection, protected fallback, fresh playback generation and RAM-only conversation handoff |
| [21 — Lighting integrations](21-lighting-integrations.md) | Configurable models and connections, native Hue Bluetooth, MCP field mapping, scoped grants and state verification |
| [22 — Default memory retrieval](22-default-memory-retrieval.md) | Automatic Second Brain reads, personal-question prefetch, shared text/voice policy, scope and privacy boundaries |
| [23 — Automatic wake recovery](23-automatic-wake-recovery.md) | Local watchdog, guarded native audio restarts, backoff, mute/lock/activity protections and publication checks |
| [24 — Microphone selection](24-microphone-selection.md) | Per-app input choice, persistent local UIDs, device changes, reconnect behavior and private metadata |
| [16 — Cross-platform builds](16-cross-platform-builds.md) | Windows/Linux portable packages, OS boundaries, universal dependencies, native CI, build and verification procedures |

The catalog has **132 functional requirements**: 96 P0, 34 P1, two P2. Priorities describe product completeness; the roadmap distinguishes first demo from later delivery. Existing numbered filenames are stable to preserve links.

## Five conclusions

1. **Continuous presence belongs to the macOS service.** A browser page alone does not fulfill it.
2. **Reasoning and voice have different timing.** Dialogue must remain usable while long work continues with separate state/cancellation.
3. **Personal memory needs clear authority.** Second Brain stores facts; agent checkpoints store execution state.
4. **Changing models does not ensure compatibility.** Test tools, Italian, context, audio, and supported parameters on the actual model.
5. **Calls need a carrier.** Voice models do not assign a number or keep a sleeping Mac available.

## Initial research evidence

- Empty initial Jarvis project.
- Web research and direct GitHub metadata/README/documentation/source inspection.
- Read-only Second Brain `recall`/`memory_status`.
- Local Second Brain MCP/OAuth contract inspection, distinguishing uncommitted local evidence from published sources.

Later implementation ran models, tests, and the Mac bundle as described in chapter 11. No competitors were installed, numbers purchased, paid calls placed, or existing Second Brain data altered.

## Remaining decisions and verification

Hardware/runtime/architecture were established in chapter 10. Personal calendar, phone account/rates, escalation rules, and remaining permissions need configuration. Connect Second Brain and model providers using dedicated local credentials. Personal account state and credential checks are deliberately omitted from this public dossier.

Remaining tests include real OpenAI multilingual audio, acoustic interruption/echo, authorized calendar behavior, test-source memory writes, and telephony on a real line. Their absence is not counted as a passing test.
