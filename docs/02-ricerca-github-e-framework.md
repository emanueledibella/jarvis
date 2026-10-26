# GitHub research and framework comparison

Research conducted on **October 24, 2026**. Primary sources included repositories, READMEs, GitHub metadata, selected source files, and official documentation. Competitors were not run. “Claimed” means a capability described by the project; code and tests alone do not establish reliability on our Mac.

## 1. Method and criteria

Searches combined Jarvis, personal assistant, wake word, MCP, memory, voice, and telephony. Adjacent frameworks and products helped identify what a simple voice assistant does not cover.

Selection favors requirements fit, service/GUI separation, interchangeable models, real tools, memory, persistent work, two-way voice, documentation, and licensing. Stars and push frequency provide context, not correctness guarantees.

`pushed_at` may refer to a branch other than the default. Revisions of the inspected branches appear in the [source register](09-fonti-e-decisioni.md), without calling them the “latest release”.

## 2. Most relevant assistants

| Project and primary source | Useful claimed capabilities | Ideas to adopt | Limits against our goal |
| --- | --- | --- | --- |
| [OpenJarvis — Stanford](https://github.com/open-jarvis/OpenJarvis) | Local execution, interchangeable engines, MCP, memory, search, coding, scheduled briefings/monitors | Separate model/engine/agent; measure quality, latency, energy, and cost | Broad platform; no complete Italian wake phrase and personal telephony solution verified |
| [Dodaios, formerly Personal Jarvis](https://github.com/Dodaios/Dodaios) | Desktop, wake phrase, agents, routines, MCP, coding, calls, local wiki | Continuous service, reviewable tools, and task continuity | Large functional surface and its own memory to replace/adapt to Second Brain |
| [Omnigentx Jarvis](https://github.com/omnigentx/jarvis) | Fast-agent, MCP tools, interruptible STT/TTS, Vue dashboard, calendar/Gmail, memory, agent teams | Consistent MCP tools, timeline, provider configuration | Different from LangGraph/Deep Agents; telephony was not demonstrated in this analysis |
| [ndunl075/Jarvis](https://github.com/ndunl075/Jarvis) | Windows, Ollama, faster-whisper, Piper, wake phrase, barge-in, tray, orb/HUD | Audio onboarding, mute/sleep, wake→STT→LLM→TTS correlation | Requires macOS porting and Second Brain integration |
| [justsubway/Jarvis](https://github.com/justsubway/Jarvis) | Electron, Iron Man HUD, compact card, offline wake detection, tools, local memory | Visual organization close to the requested idea | GitHub API identified no license; public visibility does not authorize code reuse. No durable-task/telephony evidence |
| [Leon](https://github.com/leon-ai/leon) | Controlled/agentic modes, skills, layered memory, tools, computer use, Satellite | Progressive capability loading; separate deterministic flows from planning | `develop` is the 2.0 Developer Preview; older docs may describe legacy architecture |
| [OpenClaw](https://github.com/openclaw/openclaw) | Personal gateway, desktop client, voice wake, routines, channels, phone plugins | Persistent gateway, presence, channel routing | A full fork would import many conventions and maintenance surfaces |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | Personal agent, tools, memory, skills, gateway, recurring jobs | Self-contained tasks, monitor continuity, deterministic jobs without LLMs | Verify what memory jobs can actually access; interactive history may not be available in scheduled tasks |

### Secondary candidates

| Project | Value and limitation |
| --- | --- |
| [Priler/jarvis](https://github.com/Priler/jarvis) | Rust offline pipeline/voice commands. README uses CC BY-NC-SA 4.0; does not provide the requested agent/MCP foundation |
| [Open.Jarvis](https://github.com/dmrr35/Open.Jarvis) | Windows, degraded operation without keys, configuration/memory controls. Useful onboarding and per-capability degradation |
| [Thejas775/Open-Jarvis](https://github.com/Thejas775/Open-Jarvis) | Windows assistant emphasizing accessibility, focus, and UI trees. No API-identified license; documentation reference only |
| [AndrewDongminYoo/jarvis-assistant](https://github.com/AndrewDongminYoo/jarvis-assistant) | Chrome voice and FastAPI backend; useful wake+command flow. An active Chrome page alone does not satisfy independent startup |
| [OpenVoiceOS](https://github.com/OpenVoiceOS/ovos-core) | Voice/skill ecosystem for plugins and dedicated devices; not the first candidate for general coding work |
| [Home Assistant](https://github.com/home-assistant/core) | Local pipelines and voice devices for future home integration; core remains home-specific |

## 3. Targeted findings that affect decisions

### Personal Jarvis became Dodaios

`PersonalJarvis/PersonalJarvis` resolves to **Dodaios/Dodaios**. Its README records the previous name. We inspected `docs/telephony.md` and a phone-security module, providing concrete material beyond the overview. This is not evidence of a call to our number. Source: [repository and telephony documentation](https://github.com/Dodaios/Dodaios/blob/main/docs/telephony.md).

### Voice listening has several meanings

A project may call text matching after continuous transcription a “wake word”. Jarvis must distinguish local acoustic detection, trigger-activated STT, listening costs, and transmitted data. openWakeWord's pretrained model is **“hey jarvis”**; this does not prove detection of **“Jarvis”** alone. Source: [openWakeWord](https://github.com/dscripka/openWakeWord).

### Models and code have separate licenses

openWakeWord publishes Apache-2.0 code and CC BY-NC-SA 4.0 pretrained models. Current Piper is `OHF-Voice/piper1-gpl`, with a GPL-3.0 engine; individual voices require separate checks. “Open source” alone does not settle redistribution/commercial use. Sources: [openWakeWord](https://github.com/dscripka/openWakeWord#license), [Piper](https://github.com/OHF-Voice/piper1-gpl).

### READMEs and branches are not stable specifications

Leon explicitly describes its transition to Developer Preview 2.0. Widely shared LangChain examples using `langchain-mcp-adapters` and always-enabled planning may not match current APIs. Pin versions and retain adapter tests. Sources: [Leon](https://github.com/leon-ai/leon), [LangChain MCP](https://docs.langchain.com/oss/python/langchain/mcp), [Deep Agents planning](https://docs.langchain.com/oss/python/deepagents/overview#task-planning).

## 4. Reasoning and tool frameworks

| Option | Useful features | Consequence for Jarvis | Assessment |
| --- | --- | --- | --- |
| [LangGraph + Deep Agents](https://github.com/langchain-ai/deepagents) | Persistent state, streaming, interrupts, filesystem, context, specialists | Fits the expressed preference and explicit reasoning/tool/job boundaries | **First choice to validate** |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | Typing, multiple models, tools, execution/voice ecosystem | Credible alternative if typed contracts are simpler than the required graph | Second core candidate, not another mandatory dependency |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | Python/.NET, agent/workflow orchestration | Particularly relevant with predominantly Microsoft infrastructure | Reconsider only if context changes |
| [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) | Coding harness and MCP tools | Useful dedicated coding worker; less suitable as the sole abstraction across heterogeneous local/cloud models | Optional adapter |
| [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents-sdk) | Agents, tools, OpenAI voice integrations | Useful dedicated OpenAI path; verify actual portability to other providers | Optional, without binding the core |
| [Fast-agent](https://github.com/evalstate/fast-agent) | MCP-centered approach used by Omnigentx | Alternative if MCP servers become the organizing principle before durable workflows | Documentary evidence; deeper assessment deferred |

**Proposal:** start with a small controlled graph and add Deep Agents for work requiring decomposition and operational capabilities. Specialists are not an objective themselves; weather/reminders can use deterministic functions.

### Deep Agents clarifications

Current documentation describes planning as opt-in since v0.7 through `TodoListMiddleware`. The manifest fetched at the pinned commit specifies `deepagents 0.7.32`, Python `>=3.11`, and `langchain>=1.4.7`. An indexed result still showed `0.7.28`, so verify pins against actual content. This observes that manifest, not a promise that its version is the best one to freeze. Sources: [overview](https://docs.langchain.com/oss/python/deepagents/overview), [manifest](https://github.com/langchain-ai/deepagents/blob/56b5db25ccb7be6c217ddd5575895af5c608b404/libs/deepagents/pyproject.toml).

Virtual filesystems and local backends are not automatically OS sandboxes. The model can do what tools allow; enforce boundaries in the gateway and execution environment. Source: [backends](https://docs.langchain.com/oss/python/deepagents/backends).

## 5. Voice and telephony

| Option | What it provides | Proposed use |
| --- | --- | --- |
| [Pipecat](https://github.com/pipecat-ai/pipecat) | Audio pipelines, STT/LLM/TTS providers, speech-to-speech, transports, phone integrations | First Python candidate for model/transport independence |
| [LiveKit Agents](https://github.com/livekit/agents) | Audio sessions, WebRTC, SIP stack, model integrations | Strong alternative when telephony, reconnection, and multiple clients dominate |
| [OpenAI voice, Realtime, GPT-Live](https://developers.openai.com/api/docs/guides/voice-sip) | Audio conversation, SIP/WebRTC, separate application control | Optional cloud path after checking actual APIs/access |
| [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams) | Bidirectional call/application audio over WebSocket | First phone-test candidate with a replaceable pipeline |
| [Porcupine](https://picovoice.ai/docs/porcupine/) | On-device wake detection, custom keywords, macOS | Compare with openWakeWord for the isolated word and Italian accent |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Local STT with explicit Apple Silicon/Metal support | Initial Mac transcription candidate |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | STT through CTranslate2 | CPU/CUDA alternative; do not assume whisper.cpp-equivalent Metal acceleration |
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | Local TTS | Subject to Italian quality, licensing, and packaging |

STT→LLM→TTS permits changing the reasoning model; native speech-to-speech may improve dialogue but uses a specific model/protocol. Not every provider/model pair supports both paths.

## 6. Programming and computer control

[OpenHands](https://github.com/OpenHands/OpenHands) is useful for separating agent environment, sandbox, and automation. [Open Interpreter](https://github.com/openinterpreter/openinterpreter) is another reference for local execution, permissions, and coding protocols. The initial product does not need both.

Jarvis can initially use a Deep Agents coding worker with scoped filesystem access, Git tools, and verification commands. GUI and phone must share task identity and the same change proposal rather than introducing another agent with unrestricted Mac access.

## 7. Features selected from research

| Feature | Reference | Product decision |
| --- | --- | --- |
| Orb and compact overlay | justsubway, ndunl075 | Adopt the concept with original assets/components |
| Menu bar and audio onboarding | ndunl075, Dodaios | Include in the first voice experience |
| Replaceable models/tools | OpenJarvis, Deep Agents | Include from the start |
| Progressive tool loading | Leon | Reduce errors, cost, and unnecessary context |
| Routines/monitors with continuity | OpenJarvis, Hermes, OpenClaw | Persistent state and deterministic deduplication |
| Degraded mode by capability | Open.Jarvis | Keep the core usable without phone/calendar |
| Assistant-generated tools | Omnigentx | Reviewable skill/adapter proposals; no privileged core auto-installation |
| Independent wiki memory | Dodaios, Hermes | Do not create a second biographical truth; Second Brain already exists |
| Permanent many-role teams | Omnigentx | Defer; add specialists only for measured benchmark improvements |
| Energy/latency measurement | OpenJarvis | Include in actual-Mac local/cloud comparisons |

## 8. Fork or new composition

| Strategy | Advantage | Main cost |
| --- | --- | --- |
| Fork an existing Jarvis | Faster demo if the complete flow matches | Porting, foreign memory, framework assumptions, upstream maintenance |
| Extend OpenJarvis | Many inference/research primitives already exist | Adapt UX, presence, telephony, and our memory contract |
| New product on mature libraries | Control behavior, Second Brain integration, and local/cloud profiles | More initial integration work |

**Inferred recommendation:** compose a new LangGraph/Deep Agents core with dedicated libraries, taking requirements and patterns from competitors. Before freezing this choice, F0 experiments should establish its advantage over extending OpenJarvis or Dodaios. Research did not establish that one repository already satisfies the complete requested scope.
