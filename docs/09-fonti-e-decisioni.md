# Sources, evidence, and decision register

Research date: **October 24, 2026**, reference zone Europe/Rome. GitHub timestamps below are UTC. Project capabilities were assessed from documentation, not complete competitor installations.

## 1. Interpreting evidence

- **Confirmed request:** owner statement in this conversation.
- **Technical observation:** tool/source/metadata result, bounded by that check.
- **Project claim:** maintainer-described capability, not an independent benchmark.
- **Proposal:** recommended Jarvis architecture/feature.
- **To verify:** requires actual hardware, credentials, or behavior.

Research used web search, official pages, GitHub APIs, and raw content. Some repositories were inspected at pinned revisions. READMEs were not imported; the dossier retains summaries and links.

## 2. Assistant repositories

| ID | Primary source | Observed license / note | Use in analysis |
| --- | --- | --- | --- |
| G01 | [OpenJarvis](https://github.com/open-jarvis/OpenJarvis), [Stanford site](https://openjarvis.stanford.edu/) | Apache-2.0 | Local primitives, monitors, briefings, efficiency evaluation |
| G02 | [Dodaios](https://github.com/Dodaios/Dodaios) | Apache-2.0; previous PersonalJarvis URL redirects | Desktop, routines, coding, telephony |
| G03 | [Omnigentx Jarvis](https://github.com/omnigentx/jarvis) | MIT | MCP, dashboard, orchestration |
| G04 | [ndunl075/Jarvis](https://github.com/ndunl075/Jarvis) | MIT | Local voice, HUD, onboarding, diagnostics |
| G05 | [justsubway/Jarvis](https://github.com/justsubway/Jarvis) | API license field unidentified | HUD/overlay concept; no inferred reuse permission |
| G06 | [Leon](https://github.com/leon-ai/leon) | MIT; `develop` in Developer Preview | Skills, tools, progressive context |
| G07 | [OpenClaw](https://github.com/openclaw/openclaw) | MIT | Gateway, presence, clients, telephony |
| G08 | [Hermes Agent](https://github.com/NousResearch/hermes-agent) | MIT | Routines, model-free jobs, continuity |
| G09 | [Priler/jarvis](https://github.com/Priler/jarvis) | README: CC BY-NC-SA 4.0; API `NOASSERTION` | Rust offline pipeline |
| G10 | [Open.Jarvis](https://github.com/dmrr35/Open.Jarvis) | MIT | Degraded mode, configuration, privacy |
| G11 | [Thejas775/Open-Jarvis](https://github.com/Thejas775/Open-Jarvis) | API license field unidentified | Accessibility, desktop context |
| G12 | [AndrewDongminYoo/jarvis-assistant](https://github.com/AndrewDongminYoo/jarvis-assistant) | API license field unidentified | Browser voice, macOS commands |
| G13 | [OpenVoiceOS](https://github.com/OpenVoiceOS/ovos-core) | Apache-2.0 | Voice plugin architecture |
| G14 | [Home Assistant](https://github.com/home-assistant/core) | Apache-2.0 | Local pipelines, possible future home automation |

Repository licenses do not automatically cover models, voices, assets, or dependent services. An unidentified license proves neither absence nor permission; verify specifically before copying code.

## 3. Inspected branch revisions

These revisions identify the research snapshot, not a recommendation to run production from `main`. A recent push may concern a different branch.

| Repository | Branch | Observed commit | Commit date UTC |
| --- | --- | --- | --- |
| OpenJarvis | main | [`0ec344454de3`](https://github.com/open-jarvis/OpenJarvis/commit/0ec344454de38525f3cfc52a8e06012e18871a7b) | 2026-10-24 06:15:36 |
| Dodaios | main | [`c2aeac0c6420`](https://github.com/Dodaios/Dodaios/commit/c2aeac0c642024b9207cf340cde19cd4b288d6c2) | 2026-10-20 19:11:00 |
| Omnigentx Jarvis | main | [`bba84b28c460`](https://github.com/omnigentx/jarvis/commit/bba84b28c460a82ea16419d64de448db9e0d32bd) | 2026-10-17 02:13:29 |
| ndunl075/Jarvis | main | [`e21ce95f40d8`](https://github.com/ndunl075/Jarvis/commit/e21ce95f40d8f653eed80cfa4d515c89f795edfb) | 2026-09-09 17:53:49 |
| justsubway/Jarvis | main | [`bcab0883b527`](https://github.com/justsubway/Jarvis/commit/bcab0883b5272c6ec8eb31e8a266997b16afefcb) | 2026-05-21 16:14:39 |
| Leon | develop | [`3955b5ce52ce`](https://github.com/leon-ai/leon/commit/3955b5ce52ce3b34175d6662a43a9943d588aa76) | 2026-10-24 02:37:00 |
| OpenClaw | main | [`7bd68959a21b`](https://github.com/openclaw/openclaw/commit/7bd68959a21b2dfb75dcad78d9d584f304107b0b) | 2026-10-24 13:55:00 |
| Hermes | main | [`adec2817ec09`](https://github.com/NousResearch/hermes-agent/commit/adec2817ec09abdd843a48d31f2fbbb6980296b1) | 2026-10-24 13:44:44 |
| Deep Agents | main | [`56b5db25ccb7`](https://github.com/langchain-ai/deepagents/commit/56b5db25ccb7be6c217ddd5575895af5c608b404) | 2026-10-24 08:33:52 |
| Pipecat | main | [`82c4fdb484db`](https://github.com/pipecat-ai/pipecat/commit/82c4fdb484db32e3ef933d03c59a395dd7f9a53b) | 2026-10-24 01:22:42 |
| LiveKit Agents | main | [`d4de5784e699`](https://github.com/livekit/agents/commit/d4de5784e699f54f3217bd56c6407ccd04894d61) | 2026-10-24 02:31:25 |


### More deeply inspected documentation and source samples

- [Dodaios telephony](https://github.com/Dodaios/Dodaios/blob/c2aeac0c642024b9207cf340cde19cd4b288d6c2/docs/telephony.md) and [bridge security](https://github.com/Dodaios/Dodaios/blob/c2aeac0c642024b9207cf340cde19cd4b288d6c2/dodaios/telephony/security.py).
- [Omnigentx self-hosting](https://github.com/omnigentx/jarvis/blob/bba84b28c460a82ea16419d64de448db9e0d32bd/docs/SELF_HOSTING.md) and [cron tool](https://github.com/omnigentx/jarvis/blob/bba84b28c460a82ea16419d64de448db9e0d32bd/backend/tools/cron_server.py).
- [OpenClaw voice wake macOS](https://github.com/openclaw/openclaw/blob/7bd68959a21b2dfb75dcad78d9d584f304107b0b/docs/platforms/mac/voicewake.md) and [phone plugin](https://github.com/openclaw/openclaw/blob/7bd68959a21b2dfb75dcad78d9d584f304107b0b/docs/plugins/voice-call.md).
- [Hermes cron](https://github.com/NousResearch/hermes-agent/blob/adec2817ec09abdd843a48d31f2fbbb6980296b1/website/docs/user-guide/features/cron.md).
- [Leon architecture](https://github.com/leon-ai/leon/blob/3955b5ce52ce3b34175d6662a43a9943d588aa76/core/context/ARCHITECTURE.md).
- [Manifest Deep Agents](https://github.com/langchain-ai/deepagents/blob/56b5db25ccb7be6c217ddd5575895af5c608b404/libs/deepagents/pyproject.toml).


## 4. Frameworks and tools

| ID | Primary sources | Supported fact or choice |
| --- | --- | --- |
| T01 | [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview), [repository](https://github.com/langchain-ai/deepagents) | LangGraph harness, tools/context; planning opt-in in the documented version |
| T02 | [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [repository](https://github.com/langchain-ai/langgraph) | Separate checkpoints/stores; in-memory saver is not durable |
| T03 | [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends), [human in the loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop) | Replaceable backends and interrupts; isolation needs qualification |
| T04 | [LangChain MCP](https://docs.langchain.com/oss/python/langchain/mcp) | New beta `MCPAdapter`; migration from previous adapters |
| T05 | [Pydantic AI](https://github.com/pydantic/pydantic-ai) | Typed alternative, MIT |
| T06 | [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | Python/.NET alternative, MIT |
| T07 | [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python) | Potential coding worker, MIT SDK with separate service terms |
| T08 | [OpenAI Agents](https://developers.openai.com/api/docs/guides/agents), [Fast-agent](https://github.com/evalstate/fast-agent) | Orchestration alternatives, less deeply assessed than the main candidate |
| T09 | [Pipecat](https://github.com/pipecat-ai/pipecat), [telephony](https://docs.pipecat.ai/pipecat/telephony/overview), [Twilio](https://docs.pipecat.ai/pipecat/telephony/twilio-websockets) | Composable pipeline/transports; BSD-2-Clause repository |
| T10 | [LiveKit Agents](https://github.com/livekit/agents), [outbound SIP](https://docs.livekit.io/telephony/making-calls/) | Voice and telephony; Apache-2.0 |
| T11 | [openWakeWord](https://github.com/dscripka/openWakeWord) | Apache-2.0 code, CC BY-NC-SA 4.0 models, “hey jarvis” keyword |
| T12 | [Porcupine docs](https://picovoice.ai/docs/porcupine/), [repository](https://github.com/Picovoice/porcupine) | On-device and AccessKey; qualify runtime/model terms |
| T13 | [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Local STT candidates, both MIT, different hardware support |
| T14 | [Current Piper](https://github.com/OHF-Voice/piper1-gpl) | Local GPL-3.0 engine; inspect voices separately |
| T15 | [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling) | Runtime tool support; measure each model’s quality |
| T16 | [LM Studio compatibility](https://lmstudio.ai/docs/developer/openai-compat), [tools](https://lmstudio.ai/docs/developer/openai-compat/tools), [server](https://lmstudio.ai/docs/developer/core/server) | Local tool endpoints; not universal model equivalence |
| T17 | [LM Studio authentication](https://lmstudio.ai/docs/python/getting-started/authentication) | Authentication tokens in documented versions |
| T18 | [OpenHands](https://github.com/OpenHands/OpenHands), [Open Interpreter](https://github.com/openinterpreter/openinterpreter) | Coding/execution references; observed MIT/Apache-2.0 licenses |
| T19 | [APScheduler](https://apscheduler.readthedocs.io/en/stable/userguide.html) | Triggers, persistence, misfires, scheduler ownership |
| T20 | [Tauri autostart](https://v2.tauri.app/plugin/autostart/), [Apple SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice), [EventKit](https://developer.apple.com/documentation/eventkit) | Startup/helpers and potential native calendar integration; test the bundle |

## 5. Services, protocols, and external data

| ID | Primary source | Use |
| --- | --- | --- |
| S01 | [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams) | Bidirectional audio, WSS endpoint, signatures |
| S02 | [Twilio Call resource](https://www.twilio.com/docs/voice/api/call-resource) | Call creation/state |
| S03 | [Twilio WebSocket messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages) | Media, mark, clear, audio format |
| S04 | [Twilio Italy pricing](https://www.twilio.com/en-us/voice/pricing/it) | October 24, 2026 cost examples; recheck before purchase |
| S05 | [OpenAI Telephony and SIP](https://developers.openai.com/api/docs/guides/voice-sip) | Realtime/Live distinction and outbound access |
| S06 | [OpenAI Create Live session](https://developers.openai.com/api/reference/resources/live/methods/create) | SIP creation requirements and duplicate-call retry risk |
| S07 | [OpenAI server-side controls](https://developers.openai.com/api/docs/guides/voice-server-controls) | Backend tools/control and one effect owner |
| S08 | [MCP Authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization) | Transport/version-dependent authorization |
| S09 | [MCP Security Best Practices](https://modelcontextprotocol.io/specification/latest/basic/security_best_practices) | Tokens, proxies, SSRF, local boundaries |
| S10 | [Google Calendar push](https://developers.google.com/workspace/calendar/api/guides/push) | HTTPS receivers and notification channels |
| S11 | [Microsoft Graph event](https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0) | Events, notifications, delta |
| S12 | [Open-Meteo terms](https://open-meteo.com/en/terms) | Noncommercial free API and attribution |
| S13 | [Home Assistant local voice](https://www.home-assistant.io/voice_control/voice_remote_local_assistant/) | Local pipelines, closed commands versus open transcription |
| S14 | [AI Act, consolidated text](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02024R1689-20260727) | Personal/professional contexts and transparency; qualify specific applicability |

For JavaScript-dependent Apple pages, official Markdown versions of `SMAppService`/`EventKit` were also retrieved. API details were not inferred from empty pages.

## 6. Local and MCP evidence

| Evidence | Limitation |
| --- | --- |
| Jarvis folder initially empty | No previous code to migrate |
| `memory_status` returned available dependencies/live worker | Point-in-time snapshot, not continuous availability or latency evidence |
| `recall` returned sourced/revisioned memories | Semantic results can be related context without establishing a Jarvis decision |
| Local Second Brain `server.py`/`engine.py` | Uncommitted working tree; remote server may run another revision |
| Local README/OAuth documentation | Reconfirm integration contract during dedicated connection |

No private credential files were read or reported during initial research. The dossier excludes personal URLs, tokens, vault IDs, and unnecessary biographical content.

## 7. User-confirmed decisions

| ID | Decision | Conversation evidence, translated |
| --- | --- | --- |
| D01 | Initial Mac-only installation | “Mac only initially” |
| D02 | Configure both cloud and local models | “I would like to enter a cloud model but also a local model” |
| D03 | Voice presence, tasks, tools, programming | Initial Jarvis request |
| D04 | Real-time phone dialogue | Initial request to call and answer by phone |
| D05 | Memory in the existing Second Brain | Initial request and available connector |
| D06 | Analysis before implementation, notes in docs | Initial request for in-depth analysis in this chat |

## 8. Proposed technical decisions

| ID | Proposal | Rationale | What could change it |
| --- | --- | --- | --- |
| A01 | LangGraph + Deep Agents | Expressed preference, orchestration/tool separation | F0 model, persistence, complexity experiments |
| A02 | Voice outside long-running work loop | Responsiveness/barge-in while work continues | Preserve the boundary even if libraries change |
| A03 | Pipecat as first voice candidate | Python, replaceable providers | Better quality/operations with LiveKit |
| A04 | Tauri + React with audio helper | Original interface, service boundary | Electron-favoring packaging/audio experiment |
| A05 | Initial SQLite/single scheduler | Personal Mac-only constraint, fewer dependencies | Concurrency, reliability, server migration |
| A06 | Second Brain as biographical authority | Existing evidence/revision engine | Only an explicit migration decision |
| A07 | Carrier bridge on Mac | Initial deployment and interchangeable models | Later always-on server decision |
| A08 | Strict local beyond local LLM alone | Understandable end-to-end privacy | Remains a proposed design capability |

## 9. Open questions by dependency

| ID | Information | Needed before | Provisional default |
| --- | --- | --- | --- |
| Q01 | Mac model, RAM, macOS | F0 audio/models/packaging | No definitive hardware minimum |
| Q02 | Initial cloud model/local runtime | F0 tool calling | Ollama/LM Studio candidates, no imposed model ID |
| Q03 | Canonical Second Brain installation | F1 connection | Dedicated endpoint, no automatic credential copying |
| Q04 | Memory policy/retention | F1 real writes | Configurable relevant explicit facts; exclude proposals |
| Q05 | Italian voice/fully offline need | F2 | Basic local TTS versus optional cloud comparison |
| Q06 | Calendar provider/account | F3 | Disabled until chosen |
| Q07 | Weather city/briefing time | F3 | Manual city, no private-data inference |
| Q08 | Initial enabled folders/actions | F3 coding | Explicit workspaces, least privilege |
| Q09 | Monthly budget/expected load | Before paid routines | Example limits are illustrative only |
| Q10 | Carrier, number, destination | F4 | Twilio test candidate, no purchase |
| Q11 | Events warranting a call | F4 phone autonomy | No proactive call without authorized rule |
| Q12 | Acceptance of Mac sleep/unavailability | Before everyday use | Explicit first-installation limitation |

These do not prevent completing the dossier. They become required inputs at the dependent experiment/integration, with later implementation updates recorded in chapters 10–13.

## 10. Research limits and dossier maintenance

Research is broad, not exhaustive of GitHub. No table establishes absolute absence of a competitor feature; capabilities not found/tested are labeled unverified.

The initial research did not demonstrate total cost, latency, keyword support, or number availability on the owner's Mac/account. Update proposals with F0 outcomes, pinned versions, and measurements.

Scope changes require corresponding requirement, architecture, and acceptance updates. Keep dated sources/superseded proposals identifiable instead of silently treating an early recommendation as a decision.

## 11. Checks on the produced material

The initial ten Markdown files, local links, and code fences were checked. The catalog contains 132 unique IDs: 96 P0, 34 P1, two P2. All 21 pinned GitHub commit/file links passed HTTP checks.

The conversation's interactive concept was browser-checked: two layouts, local/cloud/hybrid selection, listening/response/mute states, memory detail, light/dark themes, desktop/narrow widths, reduced motion. It contains demo data and makes no AI/calendar/weather/phone calls.

Those initial checks validate documentation/concept, not the then-unimplemented application. Actual implementation verification follows in chapter 11.
