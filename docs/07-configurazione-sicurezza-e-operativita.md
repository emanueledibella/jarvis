# Configuration, authorization, and operations

## 1. Configuration as a product contract

The following variables are a **proposed schema**, not already-implemented parameters or a ready-to-run configuration. Choose and verify model IDs, paths, and credentials during initial experiments. The actual implemented schema is in [chapter 12](12-configurazione-env.md).

Validate types, ranges, dependencies, and capabilities. Each value has provenance/version. Telephony-option errors disable that capability; errors compromising authentication/policy prevent the affected component from starting.

### Proposed precedence

1. Package defaults.
2. Nonsecret installation profile.
3. Explicit installation `.env`, parsed without executing shell code.
4. Process environment.
5. Task overrides only for policy-permitted fields.

The GUI edits the profile and identifies env-imposed values. It cannot change the environment of an already-running process. Task overrides cannot expand privileges, disable audit, or permit forbidden egress.

Do not implicitly inherit `.env` from the project the agent is editing: that file belongs to the project and may contain unrelated secrets/settings.

## 2. Example env contract

Empty values require setup. `JARVIS_WAKE_MODEL_PATH` must identify a model actually trained for the selected keyword; the text `Jarvis` cannot change acoustic behavior.

```dotenv
# Installation and availability
JARVIS_ENV=personal
JARVIS_TIMEZONE=Europe/Rome
JARVIS_LANGUAGE=it-IT
JARVIS_AUTOSTART=true
JARVIS_KEEP_AWAKE=false
JARVIS_API_HOST=127.0.0.1
JARVIS_API_PORT=8765
JARVIS_DATA_DIR=/absolute/private/path/jarvis

# Simultaneously registered models
JARVIS_PROFILE=hybrid
JARVIS_CLOUD_PROVIDER=openai
JARVIS_CLOUD_MODEL=
JARVIS_CLOUD_BASE_URL=
JARVIS_CLOUD_SECRET_REF=keychain:jarvis/cloud
JARVIS_LOCAL_PROVIDER=ollama
JARVIS_LOCAL_BASE_URL=http://127.0.0.1:11434
JARVIS_LOCAL_MODEL=
JARVIS_FAST_MODEL=local/default
JARVIS_REASONING_MODEL=cloud/default
JARVIS_CODING_MODEL=cloud/default
JARVIS_ALLOW_CLOUD_FALLBACK=false
JARVIS_MODEL_REQUEST_TIMEOUT_SECONDS=90
JARVIS_MAX_CONTEXT_TOKENS=16000
JARVIS_MAX_OUTPUT_TOKENS=4000

# Desktop voice
JARVIS_VOICE_ENABLED=true
JARVIS_WAKE_ENABLED=true
JARVIS_WAKE_PROVIDER=openwakeword
JARVIS_WAKE_PHRASE=Jarvis
JARVIS_WAKE_MODEL_PATH=/absolute/path/to/jarvis-keyword.onnx
JARVIS_WAKE_THRESHOLD=0.5
JARVIS_WAKE_COOLDOWN_SECONDS=2
JARVIS_FOLLOWUP_SECONDS=8
JARVIS_LISTEN_TIMEOUT_SECONDS=10
JARVIS_END_OF_TURN_MS=650
JARVIS_STT_PROVIDER=whisper_cpp
JARVIS_STT_MODEL_PATH=/absolute/path/to/stt-model
JARVIS_TTS_PROVIDER=system_macos
JARVIS_TTS_VOICE=
JARVIS_AUDIO_INPUT_DEVICE=system_default
JARVIS_AUDIO_OUTPUT_DEVICE=system_default

# Second Brain: choose an endpoint; loopback is only an example
JARVIS_SECOND_BRAIN_URL=http://127.0.0.1:8000/mcp
JARVIS_SECOND_BRAIN_AUTH=oauth
JARVIS_SECOND_BRAIN_SECRET_REF=keychain:jarvis/second-brain
JARVIS_MEMORY_CAPTURE=explicit_facts
JARVIS_MEMORY_BACKGROUND=true
JARVIS_MEMORY_RECALL_TOKEN_BUDGET=2000

# Tools and work
JARVIS_MCP_CONFIG_PATH=/absolute/private/path/mcp-servers.json
JARVIS_WORKSPACE_ROOTS=/absolute/path/project-one,/absolute/path/project-two
JARVIS_TOOL_TIMEOUT_SECONDS=30
JARVIS_TASK_TIMEOUT_SECONDS=1800
JARVIS_MAX_AGENT_STEPS=40
JARVIS_MAX_PARALLEL_TASKS=2
JARVIS_MAX_CODING_WORKERS=1

# Integrations and notifications
JARVIS_CALENDAR_PROVIDER=disabled
JARVIS_WEATHER_PROVIDER=open_meteo
JARVIS_WEATHER_LOCATION=
JARVIS_WEATHER_REFRESH_MINUTES=20
JARVIS_QUIET_HOURS=22:00-08:00
JARVIS_DEFAULT_MISFIRE_POLICY=skip

# Telephony: enable only after dedicated setup
JARVIS_TELEPHONY_ENABLED=false
JARVIS_TELEPHONY_PROVIDER=twilio
JARVIS_TELEPHONY_PUBLIC_BASE_URL=
JARVIS_TELEPHONY_SECRET_REF=keychain:jarvis/twilio
JARVIS_TELEPHONY_ACCOUNT_ID=
JARVIS_TELEPHONY_FROM_NUMBER=
JARVIS_OWNER_PHONE_NUMBER=
JARVIS_PHONE_MAX_CALL_SECONDS=600
JARVIS_PHONE_MAX_ATTEMPTS=1
JARVIS_PHONE_MAX_CONCURRENT_CALLS=1
JARVIS_PHONE_DAILY_BUDGET_USD=2

# Example thresholds, not a cost estimate or an approved budget
JARVIS_MONTHLY_BUDGET_USD=50
JARVIS_LOG_LEVEL=INFO
JARVIS_RECORD_AUDIO=false
JARVIS_TRANSCRIPT_RETENTION_DAYS=30
JARVIS_OPERATION_LOG_RETENTION_DAYS=30
JARVIS_REDUCED_MOTION=system
```

Development may accept provider env secrets such as `OPENAI_API_KEY` or an explicitly configured private file. Personal distribution should import secrets into Keychain and pass references, keeping them inaccessible to generic tools. Examples contain no actual keys.

`local/default` and `cloud/default` are proposed Jarvis registry aliases, not valid provider model IDs.

## 3. Local and cloud profiles

| Profile | LLM | STT/TTS | Tool networking | Fallback |
| --- | --- | --- | --- | --- |
| `local_strict` | Local | Local | Egress denied except declared local dependencies | No cloud transition |
| `local_connected` | Local | Local by default | Individually enabled remote web/calendar/MCP | Local only unless authorized override |
| `cloud` | Selected cloud provider | Configurable | Permitted tools | Policy candidates only |
| `hybrid` | Selected by role/task | Configurable | Permitted tools | Cannot violate task privacy/limits |

Profiles are enforced capabilities, not UI colors. Strict local also prevents cloud STT/TTS, report uploads, remote tracing, and transfers to disallowed remote Second Brain servers.

The router can promote work to cloud only when selected by the user or already authorized by task policy. An unresponsive local model alone does not authorize private-content transmission.

## 4. Model contract

Each model has provider, actual ID, endpoint, secret reference, limits, verified capabilities, and compatible parameters. Providers differ in support for `temperature`, reasoning effort, token limits, and tool formats.

| Capability | Check before enabling |
| --- | --- |
| Tool calling | Valid arguments, multiple calls, errors, result reuse |
| Streaming | Complete events, cancellation, correct ordering |
| Italian | Personal command/conversation suite |
| Context | Actual tools/documents, not only advertised limits |
| Vision | Image format, privacy, cost; optional initially |
| Native audio | Specific API/model/transport; not inferred from text support |
| Structured output | Schema adherence or explicit refusal/error handling |

Record test results in the model registry. Reject incompatible parameters or adapt them with documented behavior; do not silently ignore them.

LM Studio documents local servers/token authentication; compatible endpoints remain distinct from native APIs. Sources: [server](https://lmstudio.ai/docs/developer/core/server), [authentication](https://lmstudio.ai/docs/python/getting-started/authentication).

## 5. Action policy

Enable autonomous work within authorized scope without repetitive confirmations. Preserve user context/authority and evaluate concrete tools.

| Category | Examples | Proposed behavior |
| --- | --- | --- |
| Permitted read | Weather, connected agenda, enabled-workspace files | Execute without confirming every step |
| Authorized reversible write | Note, task, requested project patch | Proceed within the request and make results reviewable |
| External effect | Email, attendee invitation, PR, call | Explicit task authority or relevant persistent rule |
| Destructive/privileged | Bulk deletion, permission changes, production deployment | Separate verification, concrete proposal, appropriate authority |
| Forbidden capability | Secret exfiltration, excluded folders | Block in execution regardless of prompt |

Approval binds identity, tool, arguments/diff, target, duration, and task. A changed proposal cannot reuse it. Scheduled work uses persistent capabilities bounded by conditions/destinations.

## 6. Technical boundaries

- Listen on loopback/private socket with local-client authentication. Loopback does not authorize every web page.
- Allowed Origin/Host, DNS-rebinding protection, and session secrets prevent indiscriminate browser access.
- Coding tools receive a minimal environment. Main-process calendar/phone credentials are not automatically inherited.
- Restrict filesystem, network, resources, and duration. Path normalization alone is not an OS sandbox.
- Docker uses a VM on macOS and can support Linux tools, but is not a prerequisite for every command. Missing isolation never silently falls back to unrestricted host shell.
- MCP stdio launches local code: allowlist/version commands and dependencies; external documents cannot trigger automatic package installation.
- MCP HTTP uses dedicated authentication, safe refresh, and least privilege. No indiscriminate token passthrough.

These boundaries address documented MCP risks; authorization also depends on transport/negotiated protocol capabilities. Sources: [MCP Authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization), [Security Best Practices](https://modelcontextprotocol.io/specification/latest/basic/security_best_practices).

## 7. Prompt injection and trust

Email, pages, documents, MCP results, and recalled notes can contain instructions. Respect provenance; do not let them alter policy, identity, recipients, or configuration.

A defensive prompt alone is insufficient. Bounded network tools, isolation, permissions, and separated secrets limit model-error impact. A page asking to send a token must not have a tool capable of reading it.

Authorized repository instructions provide project context, but cannot override service limits or authorize third-party communications on the owner's behalf.

## 8. Privacy and retention

Proposed defaults to confirm: no persistent audio, 30-day intentional transcripts, 30-day minimized operational logs, rotation/disk limits. Adopted memories follow Second Brain lifecycle.

Private mode also covers checkpoints, outbox, temporary artifacts, and tracing. Merely hiding GUI messages is insufficient. Indispensable events may retain disclosed minimal IDs/outcomes/times without content.

FileVault and private Mac permissions are a baseline; more sensitive content/keys need appropriate cryptographic boundaries. Backups obey the same policy and require a restore test. Search exclusion does not delete backups.

Screen capture, clipboard, and application reading remain optional task-specific capabilities. Continuous desktop surveillance is not a prerequisite for voice assistance.

## 9. Startup, shutdown, updates

Startup validates configuration, opens databases, reconciles paused work, checks integrations with timeouts, publishes state, and starts authorized listeners. Local models may preload or load on demand with visible waiting state.

Shutdown blocks new tasks/calls, clears audio, closes media, records known effects, saves checkpoints, and releases devices/locks. Shutdown timeout never converts an uncertain effect to “cancelled”.

Updates require one supervisor, signed package, pinned dependencies, verified migration, and previous-state compatibility. Avoid unnecessary identity changes that invalidate audio permissions.

Tauri autostart is one option; launching a window alone does not establish task/service recovery. Source: [Tauri Autostart](https://v2.tauri.app/plugin/autostart/).

## 10. Useful observability

Correlate wake→turn→task→tool→audio; retain carrier/media IDs for calls. Measure verified success, first response, job delay, MCP failures, memory backlog, model loops, and estimated consumption.

Internal model reasoning traces are unnecessary for useful audit. Show relevant inputs, actions, results, times, sources, and errors, without promising complete explanations of LLM internal processes.

Proposed local commands, not yet implemented at this design stage: `jarvis status`, `jarvis doctor`, `jarvis mute`, `jarvis unmute`, `jarvis stop`, `jarvis tasks`, `jarvis logs --redacted`, `jarvis config validate`.

Distinguish process alive, dependency reachable, and capability working. HTTP 200 does not prove tool calling or searchable memory.
