# Implemented environment configuration

Based on the `Settings` schema for version 0.1.0, updated October 26, 2026. All 92 settings appear below.

Precedence: process environment → `.env` → private GUI settings → defaults. Source checkouts default to the repository `.env`; portable executables default to `.env` inside their private application data directory. Select another file with `JARVIS_ENV_FILE` or `jarvis --env-file /path/file.env ...`. Environment-provided fields are locked in the GUI. Editing `.env` requires a service restart; closing only the window does not restart the backend.

Keys accept direct values. On macOS they also accept `keychain:account` references in the `Jarvis` Keychain service; those references fail explicitly on Windows/Linux. The GUI never returns saved secret values. Saving a blank password field retains its existing value. To remove it, explicitly edit private configuration with the service stopped. Local API tokens differ from provider credentials.

`api_host` stays loopback. Change `api_port`, `data_dir`, and `ui_dir` before startup through env. `record_audio` and `allow_cloud_fallback` can only be false: hybrid selects a provider at task start, without silently retrying another provider. Interrupting a task does not move its checkpoint to cloud.

Ollama uses its root endpoint, such as `http://127.0.0.1:11434`. LM Studio/compatible gateways use the full API endpoint, such as `http://127.0.0.1:1234/v1`. Not all model/template pairs support tools; run the Settings test.

`JARVIS_UI_LANGUAGE=en` or `it` selects the graphical interface and native Mac menu language; English is the default. GUI changes save immediately and do not change voice or conversation settings.

`JARVIS_LANGUAGE` selects local wake/Apple transcription, retaining `it-IT` by default. `JARVIS_RESPONSE_LANGUAGE=auto` follows the language of substantive user requests. Explicit language tags select a preferred reply language; the user can still ask to switch. OpenAI conversation audio is not restricted to the wake locale. An explicitly selected Apple TTS voice overrides automatic voice choice.

The monthly ledger covers cloud LLM requests and recorded OpenAI desktop voice sessions. Voice reserves maximum duration plus closing margin; absent final usage retains that reservation. Rates are owner-declared and omit cache discounts. Daily phone reservations use rounded maximum minutes/configured conservative rates, adding inbound PIN tolerance. Accounting periods are UTC. Numbers, carrier charges, cloud phone audio, web services, and provider bills must still be checked in their accounts: estimates are not carrier-enforced billing limits.

| Variable | Type / values | Default | Constraints |
| --- | --- | --- | --- |
| `JARVIS_DATA_DIR` | string | macOS: `~/Library/Application Support/Jarvis`; Windows: `%LOCALAPPDATA%/Jarvis`; Linux: `$XDG_DATA_HOME/Jarvis` or `~/.local/share/Jarvis` | Absolute path; POSIX private permissions or Windows private DACL |
| `JARVIS_API_HOST` | string | `127.0.0.1` |  |
| `JARVIS_API_PORT` | integer | `8765` | minimum: 1024, maximum: 65535 |
| `JARVIS_TIMEZONE` | string | `Europe/Rome` |  |
| `JARVIS_LANGUAGE` | string | `it-IT` | On-device wake/Apple recognition locale |
| `JARVIS_UI_LANGUAGE` | en / it | `en` | Dashboard, interface messages and native Mac menus; independent of speech |
| `JARVIS_RESPONSE_LANGUAGE` | string | `auto` | auto or a BCP 47 language tag; independent of recognition locale |
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
| `JARVIS_LISTEN_TIMEOUT_SECONDS` | integer | `10` | minimum: 2, maximum: 120 |
| `JARVIS_END_OF_TURN_MS` | integer | `900` | minimum: 300, maximum: 4000 |
| `JARVIS_TTS_VOICE` | string | `` |  |
| `JARVIS_VOICE_ON_LOCK_SCREEN` | boolean | `false` |  |
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
| `JARVIS_TELEPHONY_PUBLIC_BASE_URL` | string | `` |  |
| `JARVIS_TELEPHONY_ACCOUNT_ID` | string | `` |  |
| `JARVIS_TELEPHONY_AUTH_TOKEN` | string | `secret, empty` |  |
| `JARVIS_TELEPHONY_FROM_NUMBER` | string | `` |  |
| `JARVIS_OWNER_PHONE_NUMBER` | string | `` |  |
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
