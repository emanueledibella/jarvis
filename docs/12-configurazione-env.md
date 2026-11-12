# Implemented environment configuration

Based on version 0.1.0, reviewed November 3, 2026 against `Settings` in
[`config.py`](../src/jarvis/config.py) and `ServerOptions` in
[`remote.py`](../src/jarvis/remote.py). There are **99 shared settings** and
**12 remote server options**. Feature/account registries and executor grants
are separate configuration, not additional `Settings` environment fields.

Precedence: process environment → `.env` → private GUI settings → defaults. Source checkouts default to the repository `.env`; portable executables default to `.env` inside their private application data directory. Select another file with `JARVIS_ENV_FILE` or `jarvis --env-file /path/file.env ...`. Environment-provided fields are locked in the GUI. Editing `.env` requires a service restart; closing only the window does not restart the backend.

Keys accept direct values. On macOS they also accept `keychain:account` references in the `Jarvis` Keychain service; those references fail explicitly on Windows/Linux. The GUI never returns saved secret values. Saving a blank password field retains its existing value. To remove it, explicitly edit private configuration with the service stopped. Local API tokens differ from provider credentials.

The remote core treats migrated macOS Keychain references as unavailable credentials
on other operating systems, so the administrator can enter replacement server keys
in a companion. It does not export the Mac's Keychain. The standalone mode retains
the explicit unsupported-platform error.

`api_host` stays loopback in local mode. Change `api_port`, `data_dir`, and `ui_dir` before startup through env. The remote listener uses `jarvis server --bind ... --port ...` instead; it does not relax the local validator. `record_audio` and `allow_cloud_fallback` can only be false: hybrid selects a provider at task start, without silently retrying another provider. Interrupting a task does not move its checkpoint to cloud.

`telephony_tunnel_mode` selects `external` (the compatible default) or `managed`.
Managed mode provides Activate/Deactivate controls for supervised Caddy and
Cloudflare child processes, uses the generated URL in memory, and requires an
explicit activation after restarting Jarvis. Leave the enabled/mode fields unset
in the environment to control them from Settings. See [managed telephony](26-managed-telephony.md).

Ollama uses its root endpoint, such as `http://127.0.0.1:11434`. LM Studio/compatible gateways use the full API endpoint, such as `http://127.0.0.1:1234/v1`. Not all model/template pairs support tools; run the Settings test.

`JARVIS_UI_LANGUAGE=en` or `it` selects the graphical interface and native Mac menu language; English is the default. GUI changes save immediately and do not change voice or conversation settings.

`JARVIS_LANGUAGE` selects local wake/Apple transcription, retaining `it-IT` by default. `JARVIS_RESPONSE_LANGUAGE=auto` follows the language of substantive user requests. Explicit language tags select a preferred reply language; the user can still ask to switch. OpenAI conversation audio is not restricted to the wake locale. An explicitly selected Apple TTS voice overrides automatic voice choice.

The monthly ledger covers cloud LLM requests and OpenAI Live sessions on desktop and phone. Voice reserves maximum duration plus closing margin; absent final usage retains that reservation. Phone Live uses the phone duration limit and the desktop voice rate. Rates are owner-declared and omit cache discounts. Daily phone reservations separately use rounded maximum minutes/configured conservative carrier rates, adding PIN tolerance for inbound calls. Accounting periods are UTC. Numbers, carrier charges, legacy phone STT/TTS, web services, and provider bills must still be checked in their accounts: estimates are not carrier-enforced billing limits.

When `JARVIS_DESKTOP_VOICE_PROVIDER=openai_live`, phone conversation audio reuses `JARVIS_DESKTOP_VOICE_MODEL`, `JARVIS_DESKTOP_VOICE_NAME`, `JARVIS_DESKTOP_VOICE_STYLE`, the shared response-language policy and the desktop voice key (with the same OpenAI model-key fallback). The separate phone STT/TTS settings apply only to the legacy pipeline when desktop Live is not selected. The carrier's pre-authentication PIN prompt is localized in Italian/English; PIN digits never enter the Live session.

`JARVIS_PHONE_PIN_ENABLED=true` requires a PIN when Jarvis calls the owner. The Telephony checkbox can disable this outbound verification, allowing an owner-authorized call to connect without keypad input. Incoming calls are disabled by default; enable `JARVIS_PHONE_INBOUND_ENABLED` or the separate Telephony checkbox to call Jarvis yourself. Incoming calls always require the configured 6–8 digit PIN because caller ID alone can be spoofed; without a configured PIN, incoming access is rejected. Disabling outbound verification retains any saved PIN for inbound use or later re-enabling. Rejected initial incoming calls use TwiML `Reject` before answering, rather than `Hangup`. Call authorization and tool permissions remain separate.

| Variable | Type / values | Default | Constraints |
| --- | --- | --- | --- |
| `JARVIS_DATA_DIR` | string | macOS: `~/Library/Application Support/Jarvis`; Windows: `%LOCALAPPDATA%/Jarvis`; Linux: `$XDG_DATA_HOME/Jarvis` or `~/.local/share/Jarvis` | Absolute path; POSIX private permissions or Windows private DACL |
| `JARVIS_API_HOST` | string | `127.0.0.1` |  |
| `JARVIS_API_PORT` | integer | `8765` | minimum: 1024, maximum: 65535 |
| `JARVIS_TIMEZONE` | string | `Europe/Rome` |  |
| `JARVIS_LANGUAGE` | string | `it-IT` | On-device wake/Apple recognition locale |
| `JARVIS_UI_LANGUAGE` | en / it | `en` | Dashboard, interface messages and native Mac menus; independent of speech |
| `JARVIS_RESPONSE_LANGUAGE` | string | `auto` | auto or a BCP 47 language tag; independent of recognition locale |
| `JARVIS_RESPONSE_PERSONALITY` | JSON object | `{"enabled":false,"humor":20,"irony":10,"professionalism":70,"warmth":60,"conciseness":70}` | Optional shared chat and Live voice profile. Scores are integers from 0 to 100. Edit in Settings → Personality. |
| `JARVIS_PROFILE` | local_strict, local_connected, cloud, hybrid | `local_connected` |  |
| `JARVIS_CLOUD_PROVIDER` | openai, anthropic, openai_compatible | `openai` |  |
| `JARVIS_CLOUD_MODEL` | string | `` |  |
| `JARVIS_CLOUD_BASE_URL` | string | `` |  |
| `JARVIS_CLOUD_API_KEY` | string | `secret, empty` |  |
| `JARVIS_CLOUD_REASONING_EFFORT` | low, medium, high, xhigh, max | `low` |  |
| `JARVIS_LOCAL_PROVIDER` | ollama, openai_compatible | `ollama` |  |
| `JARVIS_LOCAL_BASE_URL` | string | `http://127.0.0.1:11434` |  |
| `JARVIS_LOCAL_MODEL` | string | `` |  |
| `JARVIS_LOCAL_REASONING` | boolean | `false` |  |
| `JARVIS_LOCAL_CONTEXT_TOKENS` | integer | `16384` | minimum: 4096, maximum: 131072 |
| `JARVIS_LOCAL_API_KEY` | string | `secret, empty` |  |
| `JARVIS_ALLOW_CLOUD_FALLBACK` | boolean | `false` |  |
| `JARVIS_MODEL_REQUEST_TIMEOUT_SECONDS` | integer | `90` | minimum: 5, maximum: 600 |
| `JARVIS_MAX_OUTPUT_TOKENS` | integer | `4000` | minimum: 128, maximum: 32000 |
| `JARVIS_MAX_AGENT_STEPS` | integer | `40` | minimum: 5, maximum: 200 |
| `JARVIS_MAX_PARALLEL_TASKS` | integer | `2` | minimum: 1, maximum: 8 |
| `JARVIS_TASK_TIMEOUT_SECONDS` | integer | `1800` | minimum: 30, maximum: 14400 |
| `JARVIS_TOOL_TIMEOUT_SECONDS` | integer | `30` | minimum: 1, maximum: 600 |
| `JARVIS_WORKSPACE_ROOTS` | array | Source: `["<project>"]`; portable executable: `[]` | Grant folders explicitly; env accepts a JSON array, e.g. `["C:/Projects/example"]` on Windows |
| `JARVIS_PYTHON_SANDBOX_ENABLED` | boolean | `true` | Disposable Docker Python worker; requires installed worker images/broker |
| `JARVIS_BROWSER_ENABLED` | boolean | `true` | Isolated interactive browser; requires installed worker image/broker |
| `JARVIS_COMMAND_EXECUTION` | disabled, approval, sandbox | `approval` |  |
| `JARVIS_COMMAND_TIMEOUT_SECONDS` | integer | `120` | minimum: 1, maximum: 600 |
| `JARVIS_MCP_CONFIG_PATH` | string | `` |  |
| `JARVIS_SECOND_BRAIN_URL` | string | `` |  |
| `JARVIS_SECOND_BRAIN_TOKEN` | string | `secret, empty` |  |
| `JARVIS_SECOND_BRAIN_AUTH` | bearer, oauth, none | `bearer` |  |
| `JARVIS_SECOND_BRAIN_ALLOW_CORRECTIONS` | boolean | `false` |  |
| `JARVIS_MEMORY_CAPTURE` | explicit_only, explicit_facts, off | `explicit_only` |  |
| `JARVIS_MEMORY_RECALL_TOKEN_BUDGET` | integer | `2000` | minimum: 256, maximum: 10000 |
| `JARVIS_VOICE_ENABLED` | boolean | `true` |  |
| `JARVIS_MICROPHONE_DEVICE_UID` | string | empty | maxLength: 512; no control characters; empty follows the macOS default; selected UID is private local metadata |
| `JARVIS_DESKTOP_VOICE_PROVIDER` | apple, openai_live | `apple` |  |
| `JARVIS_DESKTOP_VOICE_MODEL` | string | `gpt-live-1` |  |
| `JARVIS_DESKTOP_VOICE_NAME` | string | `cedar` | Built-in name or saved voice_… ID |
| `JARVIS_DESKTOP_VOICE_STYLE` | string | Italian companion vocal profile | maxLength: 2000; full description in chapter 14 |
| `JARVIS_DESKTOP_VOICE_DUPLEX` | echo_cancelled, gated, full | `echo_cancelled` | Local echo cancellation and spoken interruption on native Mac; protected fallback. See chapter 20. |
| `JARVIS_DESKTOP_VOICE_API_KEY` | string | `secret, empty` |  |
| `JARVIS_DESKTOP_VOICE_MAX_SESSION_SECONDS` | integer | `120` | minimum: 15, maximum: 900 |
| `JARVIS_DESKTOP_VOICE_IDLE_SECONDS` | integer | `30` | minimum: 5, maximum: 120 |
| `JARVIS_DESKTOP_VOICE_RATE_USD_PER_MINUTE` | number | `0.05` | maximum: 5, exclusiveMinimum: 0 |
| `JARVIS_WAKE_ENABLED` | boolean | `true` |  |
| `JARVIS_WAKE_PHRASE` | string | `Jarvis` | minLength: 2, maxLength: 40 |
| `JARVIS_FOLLOWUP_SECONDS` | integer | `8` | minimum: 0, maximum: 60 |
| `JARVIS_LISTEN_TIMEOUT_SECONDS` | integer | `10` | minimum: 2, maximum: 120; latest workspace: inactivity while waiting for speech, not a maximum request length; see chapter 34 |
| `JARVIS_END_OF_TURN_MS` | integer | `900` | minimum: 300, maximum: 4000; quiet period for local request completion and latest Live delegation |
| `JARVIS_TTS_VOICE` | string | `` |  |
| `JARVIS_VOICE_ON_LOCK_SCREEN` | boolean | `false` |  |
| `JARVIS_LIGHTING_ENABLED` | boolean | `true` | Enables owner-configured lighting adapters; discovery and registration remain explicit. See chapter 21. |
| `JARVIS_WEATHER_LOCATION` | string | `` |  |
| `JARVIS_WEATHER_LATITUDE` | number or null | `null` | minimum: -90, maximum: 90; set together with longitude |
| `JARVIS_WEATHER_LONGITUDE` | number or null | `null` | minimum: -180, maximum: 180; set together with latitude |
| `JARVIS_WEATHER_REFRESH_MINUTES` | integer | `20` | minimum: 5, maximum: 180 |
| `JARVIS_CALENDAR_PROVIDER` | disabled, apple, ics, google, microsoft | `disabled` |  |
| `JARVIS_CALENDAR_ICS_URL` | string | `` |  |
| `JARVIS_CALENDAR_ACCESS_TOKEN` | string | `secret, empty` |  |
| `JARVIS_CALENDAR_REFRESH_TOKEN` | string | `secret, empty` |  |
| `JARVIS_CALENDAR_CLIENT_ID` | string | `` |  |
| `JARVIS_CALENDAR_CLIENT_SECRET` | string | `secret, empty` |  |
| `JARVIS_CALENDAR_TENANT_ID` | string | `common` |  |
| `JARVIS_SEARCH_PROVIDER` | duckduckgo, brave, tavily | `duckduckgo` |  |
| `JARVIS_SEARCH_API_KEY` | string | `secret, empty` |  |
| `JARVIS_QUIET_HOURS` | string | `22:00-08:00` |  |
| `JARVIS_TRANSCRIPT_RETENTION_DAYS` | integer | `30` | minimum: 0, maximum: 365 |
| `JARVIS_OPERATION_LOG_RETENTION_DAYS` | integer | `30` | minimum: 1, maximum: 365 |
| `JARVIS_RECORD_AUDIO` | boolean | `false` |  |
| `JARVIS_MONTHLY_BUDGET_USD` | number | `50.0` | maximum: 10000, exclusiveMinimum: 0 |
| `JARVIS_MODEL_INPUT_USD_PER_MILLION` | number | `0.0` | minimum: 0 |
| `JARVIS_MODEL_OUTPUT_USD_PER_MILLION` | number | `0.0` | minimum: 0 |
| `JARVIS_TELEPHONY_ENABLED` | boolean | `false` |  |
| `JARVIS_TELEPHONY_TUNNEL_MODE` | external, managed | `external` | Managed Caddy/Cloudflare lifecycle applies to local installations; stock remote Compose uses external ingress |
| `JARVIS_TELEPHONY_PUBLIC_BASE_URL` | string | `` |  |
| `JARVIS_TELEPHONY_ACCOUNT_ID` | string | `` |  |
| `JARVIS_TELEPHONY_AUTH_TOKEN` | string | `secret, empty` |  |
| `JARVIS_TELEPHONY_FROM_NUMBER` | string | `` |  |
| `JARVIS_OWNER_PHONE_NUMBER` | string | `` |  |
| `JARVIS_PHONE_INBOUND_ENABLED` | boolean | `false` | Explicitly allow inbound calls, which always require the PIN |
| `JARVIS_PHONE_PIN_ENABLED` | boolean | `true` | Require a PIN when Jarvis calls the owner; inbound calls always require a PIN |
| `JARVIS_PHONE_PIN` | string | `secret, empty` |  |
| `JARVIS_PHONE_API_KEY` | string | `secret, empty` |  |
| `JARVIS_PHONE_MAX_CALL_SECONDS` | integer | `180` | minimum: 30, maximum: 3600 |
| `JARVIS_PHONE_MAX_ATTEMPTS` | integer | `1` |  |
| `JARVIS_PHONE_DAILY_BUDGET_USD` | number | `2.0` | maximum: 100, exclusiveMinimum: 0 |
| `JARVIS_PHONE_MINUTE_RATE_USD` | number | `0.36` | maximum: 10, exclusiveMinimum: 0 |
| `JARVIS_PHONE_STT_PROVIDER` | openai, faster_whisper | `openai` |  |
| `JARVIS_PHONE_STT_MODEL` | string | `whisper-1` |  |
| `JARVIS_PHONE_TTS_MODEL` | string | `tts-1` |  |
| `JARVIS_PHONE_TTS_VOICE` | string | `onyx` |  |
| `JARVIS_PHONE_LOCAL_TTS_VOICE` | string | `` |  |
| `JARVIS_PHONE_LOCAL_STT_MODEL` | string | `small` |  |
| `JARVIS_UI_DIR` | string | Source: `<project>/web/dist`; portable executable: bundled `web/dist` | Startup-only override; normally leave unset |

## Remote server options

`ServerOptions` reads these values from the **process environment**. It does not
automatically parse the main `.env` selected by `--env-file` / `JARVIS_ENV_FILE`.
`deploy/.env` instead supplies Compose substitutions; `compose.yaml` translates
them to the container environment. See [deployment](../deploy/README.md).

| Variable | Type / values | Default | Constraints / purpose |
| --- | --- | --- | --- |
| `JARVIS_REMOTE_PUBLIC_URL` | string | required | Single HTTPS origin, no path, user info, query or fragment; binds Host checks and public callbacks |
| `JARVIS_REMOTE_ALLOWED_ORIGINS` | JSON string array | `["capacitor://localhost","https://localhost","jarvis://app"]` | Exact companion origins; the configured public origin is also accepted |
| `JARVIS_REMOTE_DEVELOPMENT_HTTP` | boolean | `false` | Explicit loopback-only HTTP development; client must also be a development build |
| `JARVIS_REMOTE_TRANSCRIPTION_USD_PER_MINUTE` | number | `0.006` | Greater than 0, at most 10; owner-declared STT budget rate |
| `JARVIS_REMOTE_TTS_USD_PER_MILLION_CHARACTERS` | number | `15` | Greater than 0, at most 1000; owner-declared TTS budget rate |
| `JARVIS_REMOTE_APNS_TEAM_ID` | string | empty | Apple team identifier, server-side push configuration |
| `JARVIS_REMOTE_APNS_KEY_ID` | string | empty | APNs key identifier |
| `JARVIS_REMOTE_APNS_PRIVATE_KEY` | string | empty | Path to the server-readable `.p8` file, not inline key contents |
| `JARVIS_REMOTE_APNS_TOPIC` | string | `it.jarvis.companion` | Match the installed iOS bundle ID |
| `JARVIS_REMOTE_APNS_SANDBOX` | boolean | `false` | Match the development/production push entitlement |
| `JARVIS_REMOTE_FCM_SERVICE_ACCOUNT` | string | empty | Path to the server-readable Firebase service-account JSON |
| `JARVIS_REMOTE_DOCUMENT_WORKER_SOCKET` | string | empty | Unix parser-broker socket; required for remote document extraction; Compose sets `/run/jarvis-worker/parser.sock` |

The parser service reads `JARVIS_DOCUMENT_WORKER_SOCKET` (without `REMOTE_`),
defaulting to `/run/jarvis-worker/parser.sock`. Core and worker must share that
socket directory; only the core mounts its private data and push secrets.

### Compose names and forced remote settings

`deploy/.env.example` uses `JARVIS_PUBLIC_HOST` plus `JARVIS_APNS_TEAM_ID`,
`JARVIS_APNS_KEY_ID`, `JARVIS_APNS_PRIVATE_KEY`, `JARVIS_APNS_TOPIC`,
`JARVIS_APNS_SANDBOX` and `JARVIS_FCM_SERVICE_ACCOUNT`. These are Compose inputs,
not aliases accepted directly by `ServerOptions`. Their credential paths refer
to files inside the container, normally `/run/secrets/...`. Extra remote options
need explicit Compose environment entries; merely adding an unused variable to
`deploy/.env` does not inject it into the container.

The remote runtime forces `profile=cloud`, `workspace_roots=[]`,
`command_execution=disabled`. Voice/wake preferences now configure companion
devices; the core never captures microphone audio. They are no longer forced
off by the runtime or the container image. Explicit environment values still
lock the corresponding controls.
Compose additionally fixes `max_parallel_tasks=1`. Local desktop operations go
through a paired executor; HTTP MCP is supported and server-side stdio is denied.
The companion cannot turn the remote core into an unrestricted host shell or
select a desktop local model as an inference backend.

Remote administrator settings cover cloud provider/model/endpoint/key, declared
prices/budget, supported limits, language/time zone/weather, cloud calendars,
search, Second Brain, companion wake/Live voice and Twilio configuration (carrier
credentials, verified numbers, PIN, inbound calls and limits). Saving requires
the current `ETag` in `If-Match`; HTTP 409 requires a reload. Host paths/listener,
push credentials and non-allowlisted settings require
server administration. Environment-controlled fields remain locked.

Manual companion recording STT/TTS uses `JARVIS_PHONE_STT_MODEL`, `JARVIS_PHONE_TTS_MODEL` and
`JARVIS_PHONE_TTS_VOICE`. It uses a
dedicated `JARVIS_DESKTOP_VOICE_API_KEY` or the official OpenAI text key when
eligible. Its STT/TTS rates are the remote options above. Hands-free companion
Live instead uses `JARVIS_DESKTOP_VOICE_*`, including saved `voice_…` IDs, style,
duration, idle timeout and the existing Live budget reservation. Wake recognition
stays on each device. Microphone permission/selection and local listening opt-in
are device preferences, not server environment variables. See
[companion voice parity](35-companion-native-parity.md).

## Feature and device configuration

Today preferences, projects/activities, mail accounts/drafts, automation rules,
documents, development targets, Home Assistant grants and the light registry are
managed through their dedicated pages. Do not invent `JARVIS_MAIL_*`,
`JARVIS_GITHUB_*` or similar env settings for these registries.
Account credentials and OAuth state stay private; remote secret stores are encrypted.
Persistent feature edits are blocked in private sessions.

Desktop executors store local grants in their own `executor.json`, keep device
credentials in the OS vault and journal effects separately. CLI JSON enrollment
supports up to 32 workspaces; the companion GUI configures one. These are not core
`JARVIS_WORKSPACE_ROOTS` settings. See [companion enrollment](../companions/README.md).
