# Roadmap, validation, and costs

## 1. Delivery path

The first demo and complete product are different milestones. Telephony, memory, local/cloud models, and voice presence remain in scope even when delivered in later phases.

| Phase | Concrete result | Dependencies | Exit criterion |
| --- | --- | --- | --- |
| F0 — Risk experiments | Exact wake phrase, macOS audio, local/cloud tool calling, async Second Brain, packaging | Hardware, macOS, test models | Recorded results and a documented choice for every principal risk |
| F1 — Text core | Local service, configuration, gateway, chat, search, memory, persistent state | F0 models/MCP | Complete and recover a real task after restart using both AI profiles |
| F2 — Presence/interface | Login startup, menu bar, wake phrase, dialogue, orb, minimal dashboard | F1 and audio/packaging experiments | Works without opening the window; reliable interruption/mute |
| F3 — Everyday work | Agenda, weather, tasks, routines, notifications, scoped coding | Calendar provider, enabled folders, policy | Daily scenarios with sleep recovery and reviewable outcomes |
| F4 — Telephony | Carrier, bridge, identity, owner calling, dialogue with tools | Number, credit, tunnel, escalation policy | Successful real call and failure tests without duplicate ringing |
| F5 — Consolidation | Performance, restore, updates, accessibility, regression matrix | Previous paths | Verify every final-scope P0; disclose remaining limits |

F2 and parts of F3 can overlap. F4 can start as an isolated experiment. A useful installable baseline requires F1, F2, and a declared F3 subset. Do not call it “complete Jarvis” while telephony/other requested P0s are missing.

## 2. F0 experiments

| Experiment | Question | Output |
| --- | --- | --- |
| Wake phrase | Does isolated “Jarvis” work with actual accents/devices? | Consented personal dataset, false triggers, misses, detector choice |
| Audio/permissions | Does the bundle capture with window closed and after login/wake? | OS/state/device matrix; helper/supervisor approach |
| Italian/interruption | Are STT/TTS and barge-in usable without headphones? | Test phrases, perceived quality, timing, declared limits |
| Cloud/local tools | Do both models handle schemas, errors, multi-step work? | Per-model capability register and comparable benchmark |
| Deep Agents | Are opt-in planning, checkpoints, and permissions sufficient? | Resumed long task, gateway-enforced block, measured usage |
| Second Brain | Does async adoption preserve source/idempotency/state? | Dedicated test-vault checks without contaminating real memories |
| GUI | Does Tauri simplify menu bar, helper, streams, distribution? | Package comparable with Electron alternative |
| Telephony | Can carrier/tunnel reach the Mac for two-way Italian? | Authorized owner call with observed cost, not webhook-only testing |

Use synthetic data and `test-mcp` scope for ingestion experiments. Do not benchmark memory by writing invented facts to the personal profile.

## 3. Performance targets to validate

These are **design targets**, not measured results or promises for every Mac/model. Record hardware, power, network, version, warm/cold state, and sample count.

| Metric | Initial target | Test method |
| --- | --- | --- |
| Activation signal | p95 within 300 ms of keyword end | At least 100 measured activations |
| Quiet-room wake detection | At least 95% | Exact phrase, multiple distances, main device |
| Realistic-noise wake detection | At least 85% before final tuning | Separate documented noise/volume series |
| False triggers | At most one per eight hours | At least 24 controlled hours without unnecessary ambient recording |
| First short spoken reply | Warm-stack p95 within 2.5 s of command end | 50 turns/profile, separate remote-tool cases |
| Playback stop | p95 within 250 ms of recognized interruption | Separate local/phone queue tests |
| Command entity understanding | At least 95% for names/dates/targets in quiet suite | 100 Italian phrases including English technical words |
| Scheduled notification | Awake-Mac p95 within five seconds | 100 deadlines without network dependence |
| Service recovery | Within ten seconds of process crash | Restart during reads, writes, uncertain effects |
| Listener idle | Under 5% of one core; no LLM inference | Separate CPU/GPU, UI, and model runtime |
| Listener/base-service RAM | Preliminary 500 MB excluding models | Actual per-process RSS; revise after prototype |

Long tasks need prompt acknowledgment and accurate status, not a final answer within 2.5 seconds. Measure first audio separately from first useful result.

## 4. Functional acceptance matrix

| Suite | Minimum coverage | Evidence |
| --- | --- | --- |
| macOS presence | Login, hidden window, lock, wake, microphone disconnect | Redacted logs and manual device checks |
| Conversation | Wake+question, pauses, follow-up, stop, task cancellation, mute | Transcript/final state without duplicated actions |
| Models | One local/cloud, timeout, invalid schema, context limit | Actual tool execution, actual profile/model |
| Research | Cited comparison, unavailable page, conflicting documents | Bibliography and fact/inference distinction |
| Memory | Source, recall, identity, conflict, correct/revise, queue/retry | Test-vault `source_id`, revision, claims, observed states |
| Tasks | One-off, recurrence, sleep, delay, daylight saving | Expected triggers without indiscriminate replay |
| Coding | User changes, bug, failed checks, excluded workspace | Diff/results and no out-of-scope access |
| Calendar | Recurrence, all-day, time zone, expired token, empty agenda | Provider comparison |
| Telephony | Connection, auth, no-answer, voicemail, network loss, duplicate callbacks | Provider ID/state and one call intent/event |
| Privacy | Strict local, private sessions, secret redaction | Egress, checkpoint/outbox, log inspection |
| GUI | Long content, error, stale data, keyboard, VoiceOver, reduced motion | Visual checks and microphone-free flow |
| Operations | Restore, migration, package update | Consistent tasks/memory references after restore |

Generating the correct tool name is insufficient: results must come from execution and mutations should be verified in the destination where possible.

## 5. Decisive failure tests

1. Kill a worker after remote creation is sent but before saving its result: never blindly repeat the effect.
2. Disconnect while Second Brain saves: reuse the same key and check the revision.
3. Restart during a call: reconcile carrier state without another automatic call.
4. Lock/disconnect the microphone during TTS: recover without echo activation.
5. Sleep through a scheduled briefing: apply tolerance on wake rather than treating stale data as current.
6. Change the default model during work: continue with its declared snapshot unless explicit supported migration occurs.
7. Have a page/tool request a secret: no tool should possess that capability.
8. Open a private session: no session text in unintended ledger, outbox, cache, or tracing.

## 6. Local model selection

Before recommending size/quantization, establish Mac model, unified RAM, free storage, and concurrent loads. Chat, STT, and Second Brain can compete for resources.

Compare Italian quality, tool reliability, realistic context, first-token latency, tokens/second, RAM, energy, cold start, and license. Test progressive loading so passive listening does not keep an unused large model resident.

Minimum hardware varies by profile: light cloud listening differs from all-local LLM+STT+TTS+Second Brain. Do not claim unmeasured capabilities as supported.

## 7. Cost inventory

| Item | Driver | Possible reduction |
| --- | --- | --- |
| Cloud LLM | Input/output tokens, cache, attempts, specialists | Targeted retrieval, summaries, task limits, local path |
| STT | Provider minutes/units | Local activation before transmission, local engine |
| TTS | Characters, tokens, generated audio | Short spoken replies, local synthesis |
| Native audio | Model-specific audio/text units | Pipeline comparison, idle-session closure |
| Search | Queries, extraction, remote browsers | Caching, useful queries, research limits |
| Telephony | Number, direction, origin/destination, minutes, media | Escalation rules, max duration, verified routing |
| Tunnel | Plan, stable domain, traffic | Match personal use/availability |
| Local | Energy, storage, hardware, maintenance | No model polling, quiet UI, proportionate models |
| Distribution | Signing/notarization, dependencies, updates | Define personal channel and actual costs when selected |

An AI-app subscription is not automatically API credit. Account/SDK/subscription integration paths require qualification under the selected service terms.

## 8. Cost model without premature provider selection

For text LLMs:

```text
C_LLM = sum_per_model(
    uncached_input_tokens / 1,000,000 × input_rate
  + cached_input_tokens / 1,000,000 × cache_rate
  + output_tokens / 1,000,000 × output_rate
)
```

Composable voice adds STT/TTS in provider units. Native voice uses actual audio pricing; do not arbitrarily convert minutes to tokens. Add search, phone number, call/media minutes, tunnel, operational services.

Proposed benchmark loads, **not estimates of the owner's habits**:

| Measurement profile | Turns/month | Research/coding | Telephony |
| --- | --- | --- | --- |
| Light | 600 | 10 long tasks | 30 minutes |
| Daily | 1,500 | 40 long tasks | 120 minutes |
| Intensive | 4,500 | 120 long tasks | 300 minutes |

Per-turn cost depends on retrieved memory, tools, and model. Trial for a week, record distributions, then project a month with a stated margin. A reliable total requires chosen models, voice, carrier, and load.

## 9. Phone example using verified rates

The Twilio Italy page inspected October 24, 2026 distinguished **Italy - Mobile - From EEA: USD 0.0445/min** from **Italy - Mobile: USD 0.3473/min**, plus **USD 0.0044/min** for Media Streams. Verify routing/account category; the lowest mobile rate is not universal. Source: [Twilio Voice Pricing Italy](https://www.twilio.com/en-us/voice/pricing/it).

Illustration for 120 minutes, assuming one leg and Media Streams billed for the same duration:

| Rate assumption | Calculation | Subtotal |
| --- | --- | --- |
| EEA mobile + media | 120 × (0.0445 + 0.0044) | USD 5.868, about USD 5.87 |
| Generic mobile + media | 120 × (0.3473 + 0.0044) | USD 42.204, about USD 42.20 |

Illustrative subtotals exclude number, AI, other services, taxes, currency conversion. The same page listed Italian toll-free numbers at USD 27/month; this does not establish an inexpensive local number for our account. Recheck before purchase.

## 10. Budget controls

Each task has token, step, time, and tool-call budgets. Reserve an estimate before paid operations and update with actual usage where available. Unknown cost remains unknown rather than zero.

Apply daily/monthly thresholds, max call duration, and concurrency limits. Billing can lag: application caps are conservative controls, not mathematical guarantees of the final provider bill. Add provider-side limits when available.

## 11. Dependencies to obtain

| Need | When |
| --- | --- |
| Hardware/macOS version | Before F0 |
| Cloud model and suitable credential | F0, authorized integration test only |
| Local runtime/model | F0 after RAM-based selection |
| Wake/STT/TTS Italian models | F0/F2 |
| Dedicated Second Brain endpoint/credential | F0/F1 without reusing chat secrets |
| Calendar provider/account | F3 |
| Weather city/briefing preferences | F3 |
| Phone account, number/caller ID, recipient, tunnel | F4 |
| Memory policy, folders, permitted actions | Before enabling relevant capabilities |
| Budget/call rules | Before autonomous paid execution |

## 12. Decision order

First hardware, presence, and models; then memory contract and a complete first task; next everyday UX/calendar; finally integrated telephony and consolidation. Estimate development dates after F0 rather than hiding audio, packaging, and local-compatibility risks behind an early rigid deadline.
