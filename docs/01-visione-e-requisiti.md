# Vision, scenarios, and functional requirements

Date: October 24, 2026. All behaviors are **requirements for the product to be built**, except evidence explicitly marked as already observed. The October 25 language update preserves Italian support and adds automatic response-language adaptation.

## 1. Objective and boundaries

Jarvis is a personal assistant that accepts goals in the user's language, uses suitable sources and tools, completes authorized work, makes its results verifiable, and maintains continuity through Second Brain.

The initial environment is **one Mac and one owner**, with one or more cloud and local models. Availability depends on the Mac and its user session. The window is an interaction surface; the service must operate independently of its visibility.

“Answering a specific question” means choosing relevant tools and sources, requesting genuinely missing context, and explaining the answer's limits. It does not promise universal knowledge or successful execution in every external service.

### Priority and origin

- **P0:** required for the first complete version of the described product. Delivery can be staged; telephony remains P0 even if it follows the first demo.
- **P1:** useful for reliable everyday use.
- **P2:** a later expansion.
- **U:** explicit user request; **D:** necessary consequence of a request; **N:** additional proposal from the analysis.

Table criteria are functional checks. Performance thresholds and test samples are in the [validation plan](08-roadmap-validazione-e-costi.md).

## 2. Main scenarios

| Scenario | Expected behavior | Verifiable outcome |
| --- | --- | --- |
| “Jarvis, what does my day look like?” | Activate voice, read calendar and tasks, retrieve weather for the configured location, and give a short briefing | Sources, times, and last update available in the GUI |
| “Remind me in twenty minutes to…” | Interpret the deadline, save the reminder, and confirm date/time | The reminder survives a process restart |
| “Check every morning whether…” | Create a monitor with frequency, condition, expiry, and notification rule | Stay quiet when nothing changes; record an event when it does |
| “Compare these three frameworks” | Search primary sources, examine differences, and return a cited comparison | A report with links and research limitations |
| “Fix this bug in the project…” | Identify the authorized repository, read applicable instructions, and propose/apply changes in the intended workspace | A diff and relevant verification, including any failures |
| “What did we decide about…?” | Query Second Brain in the correct context | An answer with source and revision, preserving conflicts |
| “From today, I prefer…” | Capture a new preference with its effective date | Source saved; adoption checked separately |
| An authorized task is blocked and needs an urgent choice | Evaluate an escalation rule, call the owner, and explain why | Two-way conversation and a decision linked to the task |
| “Use the local model for this request” | Apply the local profile throughout the intended path | No hidden cloud fallback; disclose required remote services |
| The Mac wakes after an hour | Reconcile missed jobs and external results | No burst of expired reminders or overdue calls |

## 3. Presence and lifecycle

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| PR-01 | P0 U | Activation by saying “Jarvis” | The word alone opens a listening window; “Jarvis, …” retains the following command |
| PR-02 | P0 D | Configurable launch at login | After login and completed onboarding, the service starts without opening a chat |
| PR-03 | P0 U | Operation with the window closed | Wake detection, scheduler, and tasks continue after the window closes |
| PR-04 | P0 D | Active, muted, and stopped states | Menu bar and GUI show the same state; mute releases the microphone |
| PR-05 | P0 D | Crash recovery | The supervisor restarts the service and reconciles tasks without repeating known effects |
| PR-06 | P0 D | Recovery after sleep and network changes | Resume audio and connections; apply each job's recovery policy |
| PR-07 | P0 D | Denied-permission handling | Denying microphone access leaves text available and explains how to restore voice |
| PR-08 | P1 N | Alternative activation | A global shortcut and push-to-talk work without the wake phrase |
| PR-09 | P1 N | Idle resource limit | No LLM loop without requests; a lightweight listener and idle UI |

## 4. Conversation and voice

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| CV-01 | P0 U | Natural Italian | Understand and pronounce the Italian command suite and configured names correctly; retain Italian when the user speaks it |
| CV-02 | P0 D | End-of-turn detection | Do not cut off a short pause or listen indefinitely |
| CV-03 | P0 D | Interrupt spoken responses | “Stop” interrupts playback and discards queued audio |
| CV-04 | P0 D | Continue the dialogue | Follow-up questions in the active window retain context without repeating “Jarvis” |
| CV-05 | P0 D | Distinguish muting from cancellation | Stopping speech does not automatically cancel background work |
| CV-06 | P0 D | Correct rendering of numbers and code | Offer text for long commands/details; do not read entire code blocks by default |
| CV-07 | P0 D | Ambiguity handling | Ask one relevant clarification for ambiguous recipients, dates, or repositories |
| CV-08 | P0 D | Clear progress while working | Show listening, processing, active tools, and completion using actual events |
| CV-09 | P1 N | Replaceable audio devices | Switching headphones/microphones does not require restarting the whole app |
| CV-10 | P1 N | Pronunciation and terminology registry | A configurable, correctable vocabulary for names, acronyms, and projects |

## 5. Intelligence and models

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| IN-01 | P0 U | Configure a cloud and a local model | Both can be registered in the same installation profile |
| IN-02 | P0 U | Selection through env | Change provider, model ID, endpoint, and supported parameters without editing code |
| IN-03 | P0 D | Execution profiles | At least local, cloud, and hybrid profiles with explicit rules |
| IN-04 | P0 D | Capability validation | A model without tool calling is not presented as a complete operational agent |
| IN-05 | P0 D | Unavailable-provider behavior | Report the error or use only fallbacks compatible with the profile and privacy |
| IN-06 | P0 D | Model tied to each run | Timeline and audit show the actual provider/model even after changing defaults |
| IN-07 | P0 D | Persistent complex work | The plan has steps and state; closing the GUI does not lose the result |
| IN-08 | P1 N | Different models by role | Voice, reasoning, coding, and summarization can use different configurations |
| IN-09 | P1 N | Specialists with bounded context | Delegation respects the parent task's permissions, budget, and cancellation |

## 6. Local and MCP tools

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| TL-01 | P0 U | Local and MCP tool registry | Discover tools with name, schema, provenance, and connection state |
| TL-02 | P0 D | Local and remote MCP | An authorized stdio server and authenticated Streamable HTTP server both work |
| TL-03 | P0 D | Permissions before execution | The gateway blocks requests outside policy even if the model insists |
| TL-04 | P0 D | Verified results | “Done” requires a consistent tool result; timeout remains an error or uncertain outcome |
| TL-05 | P0 D | Timeouts and error isolation | An unreachable MCP server does not block independent tools or the GUI |
| TL-06 | P0 D | Filesystem scope | Restrict access to authorized folders, including symlink and path checks |
| TL-07 | P0 D | Controlled command execution | Task-defined directory, timeout, resources, and network; no indiscriminate credential inheritance |
| TL-08 | P0 D | Operation deduplication | Reconnection does not automatically repeat sends, creations, or calls |
| TL-09 | P0 D | Authentication and reconnection | Expired tokens request reconnection without exposing secrets |
| TL-10 | P1 N | Targeted capability loading | Each agent receives only the tools relevant to its task |
| TL-11 | P1 N | Enable integrations through UI | Show capabilities, scope, and shared data before enabling |

## 7. Specialist answers and web research

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| RS-01 | P0 U | Web search | Questions about current information use an up-to-date source |
| RS-02 | P0 D | Answers with accessible sources | Each central report claim links to its supporting page |
| RS-03 | P0 D | Appropriate source selection | Calendar from the calendar, memories from Second Brain, technical documentation from primary sources |
| RS-04 | P0 D | Facts versus inference | Distinguish evidence, assumptions, and recommendations, with dates when relevant |
| RS-05 | P0 D | Knowledge limitations | Explain missing evidence and propose a concrete verification |
| RS-06 | P0 D | External documents as data | Retrieved web text cannot change policy, permissions, or recipients |
| RS-07 | P1 N | Long research in the background | Save reports and bibliography; expose progress during execution |
| RS-08 | P1 N | Browser as an additional tool | Isolated navigation when APIs/fetch are insufficient, with controlled sessions/downloads |
| RS-09 | P1 N | Project document knowledge | Search authorized files with path and revision references |

## 8. Programming

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| CD-01 | P0 U | Understand the repository | Identify structure and applicable instructions before changing files |
| CD-02 | P0 U | Edit code | Produce concrete patches for implementation or bug-fix requests |
| CD-03 | P0 D | Preserve existing changes | Do not overwrite or clean a working tree containing user changes |
| CD-04 | P0 D | Relevant verification | Run required build/lint/tests and report which passed or failed |
| CD-05 | P0 D | Reviewable result | Show diff, changed files, expected behavior, and verification limits |
| CD-06 | P0 D | Bounded execution environment | Project code does not automatically receive calendar or telephony credentials |
| CD-07 | P1 N | Dedicated worktree | Isolate a task without mixing it with other work |
| CD-08 | P1 N | GitHub/Jira connection | Read issues and CI; prepare PRs/updates within task authorization |
| CD-09 | P1 N | Voice-controlled long sessions | “How far along are you?” returns status; “cancel the task…” stops future steps |
| CD-10 | P2 N | External coding agents | SDK/CLI adapters with structured contracts and equivalent permissions |

## 9. Tasks, reminders, and routines

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| TK-01 | P0 U | One-off and daily tasks | Create, list, update, complete, and cancel tasks with description and state |
| TK-02 | P0 D | Relative and absolute reminders | “In 20 minutes” and “tomorrow at 9” produce explicit deadlines in Europe/Rome |
| TK-03 | P0 D | Recurrence | Weekdays and recurring frequencies have a readable summary |
| TK-04 | P0 D | Persistence | Service/Mac restarts retain jobs, next trigger, and results |
| TK-05 | P0 D | Sleep and delay handling | Each job defines tolerance, recovery, or skip without indiscriminate catch-up |
| TK-06 | P0 D | Explicit states and resumption | Distinguish queued, running, paused, waiting for user, success, failure, cancellation, and uncertainty |
| TK-07 | P0 D | Execution control | Pause/cancel stop future steps; completed effects remain visible |
| TK-08 | P0 D | Result and completion criterion | Finish when the requested outcome is verified or explain the limit reached |
| TK-09 | P1 N | Condition monitors | Persist frequency, condition, last value, expiry, and change criterion |
| TK-10 | P1 N | Model-free triggers | Deterministic checks do not call an LLM on every tick |
| TK-11 | P1 N | Concurrency and priority | Heavy work does not saturate voice; serialize tasks on the same repository when needed |
| TK-12 | P1 N | Daylight saving and travel | Recurrences follow their specified zone; nonexistent/duplicate times have a policy |

## 10. Proactivity and notifications

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| NT-01 | P0 D | Event-linked notifications | Each notification identifies its generating task or condition |
| NT-02 | P0 D | Escalation rules | Calls occur only for authorized events and recipients |
| NT-03 | P0 D | Deduplication and rate limits | One incident does not create concurrent calls or a notification on every check |
| NT-04 | P0 D | Quiet hours | Exceptions are configured; a model-generated “urgent” label cannot override them |
| NT-05 | P0 D | Delivery outcomes | Separate sent, delivered where observable, read/acknowledged, and failed |
| NT-06 | P1 N | Channel preference | Desktop, voice, or phone according to presence, priority, and rules |
| NT-07 | P1 N | Daily briefing | Configurable agenda, weather, and task briefing with explicit missing data |
| NT-08 | P1 N | Contextual reminders | Suggest departure/preparation only with location, travel time, and available sources |

## 11. Personal memory

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| ME-01 | P0 U | Second Brain as memory authority | Answers about personal history query the existing MCP server |
| ME-02 | P0 D | Cross-conversation continuity | An adopted fact can be recalled in a new session |
| ME-03 | P0 D | Verifiable provenance | Answer and panel show `source_id`, revision, and a relevant quotation |
| ME-04 | P0 D | Separate scopes | Do not combine `personal` and `work` without an explicit task reason |
| ME-05 | P0 D | Asynchronous adoption | Saved source and searchable memory are distinct states shown correctly |
| ME-06 | P0 D | Correction versus change | Use `correct` for errors and `revise` for actual changes, with a date |
| ME-07 | P0 D | Uncertainty and conflicts | Do not invent a definitive preference to resolve conflicting evidence |
| ME-08 | P0 D | Exclude memory | “Do not remember this” and private sessions prevent new writes of that content |
| ME-09 | P0 D | Reliable writes | Retry with the same `request_id` and check the already-saved source |
| ME-10 | P0 D | No agent-invented facts | Assumptions, examples, and proposals do not become the user's biographical data |
| ME-11 | P1 N | Deliberate deletion handling | Distinguish retraction, removal from search, and deletion of original data |
| ME-12 | P1 N | Inspection and maintenance | Show service state, pending extraction, and review requests in the GUI |

## 12. Telephony

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| PH-01 | P0 U | Outbound call to the owner | An authorized event can ring the configured verified number |
| PH-02 | P0 U | Real-time two-way dialogue | Jarvis listens, answers, and uses tools during a call without recorded-message turns |
| PH-03 | P0 D | Context for the call | Opening identifies Jarvis, reason, and task; dialogue resumes the correct context |
| PH-04 | P0 D | Identity before sensitive data | Caller ID and voice alone are insufficient authentication |
| PH-05 | P0 D | Phone interruption | Speaking interrupts output and corrects the provider playback queue |
| PH-06 | P0 D | Separate call outcomes | Handle busy, declined, unanswered, voicemail, connected, and failed |
| PH-07 | P0 D | Duration, attempt, and spending limits | Respect configured limits and never redial indefinitely |
| PH-08 | P0 D | No duplicate ringing after ambiguous retries | A creation timeout requires reconciliation before another attempt |
| PH-09 | P0 D | Phone decision linked to the action | Approval applies to one specific, valid, unchanged proposal |
| PH-10 | P0 D | Actual Mac availability | GUI explains telephony's awake-Mac, network, and tunnel requirements |
| PH-11 | P1 N | Inbound calls | The owner can call Jarvis with the same authentication and scope as outbound |
| PH-12 | P1 N | Desktop/phone handoff | Resume a task while preserving identity, state, and turn ownership |

## 13. Personal productivity

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| PD-01 | P0 U | Read calendar | List events, upcoming commitments, and overlaps from the chosen provider |
| PD-02 | P0 D | Correct event semantics | Correctly represent all-day, recurring, cancelled, and time-zone-aware events |
| PD-03 | P0 U | Local weather | Configured location's data, source, and update time |
| PD-04 | P0 D | Explicit missing/stale data | Do not replace unknown values with generated content |
| PD-05 | P1 N | Calendar writes | Create/update events after checking dates, calendar, and required recipients |
| PD-06 | P1 N | Email and messages | Read/draft for connected accounts; sending requires relevant authorization |
| PD-07 | P1 N | Notes, files, and local search | Create notes or find documents in enabled folders |
| PD-08 | P2 N | Home automation and devices | Optional Home Assistant/service adapters with bounded actions |

## 14. GUI and control

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| UI-01 | P0 U | Central orb | React to actual rendered audio level and distinguish states |
| UI-02 | P0 U | Compact dashboard | Weather, next event, and active tasks with source and freshness |
| UI-03 | P0 D | Always-available menu bar | Show status, mute, dashboard opening, and explicit quit |
| UI-04 | P0 D | Complete text input | All main capabilities work without a microphone |
| UI-05 | P0 D | Task timeline | Tools, results, waits, and errors visible, with details on request |
| UI-06 | P0 D | Clear confirmations | Show concrete action, recipient, and consequence before approval where required |
| UI-07 | P0 D | AI profile status | Identify the local/cloud model and relevant data transfers |
| UI-08 | P0 D | Microphone/privacy control | One gesture reaches mute and private mode; their meanings remain distinct |
| UI-09 | P0 D | Accessibility | Keyboard, VoiceOver, text states, contrast, and reduced motion |
| UI-10 | P1 N | Discreet overlay | Appear after wake detection without stealing focus from the active app |
| UI-11 | P1 N | Customization | Configurable density, widgets, voice, and overlay behavior |
| UI-12 | P1 N | Useful diagnostics | Service state and recovery actions without tokens or stack traces on the home screen |

## 15. Configuration and operations

| ID | Priority / origin | Requirement | Acceptance |
| --- | --- | --- | --- |
| CF-01 | P0 U | Documented env configuration | Models, voice, wake phrase, integrations, and limits have schema and validation |
| CF-02 | P0 D | Protected secrets | Keys are unavailable to the renderer or tools that do not need them |
| CF-03 | P0 D | Parameter provenance | UI identifies env, profile, or default values |
| CF-04 | P0 D | Missing settings handled by capability | Missing telephony does not prevent the text core from starting |
| CF-05 | P0 D | Valid configuration before use | Incompatible endpoints, paths, or capabilities produce useful errors before a task |
| CF-06 | P0 D | Minimized logs/audit | Correlate events without ambient audio or plaintext secrets |
| CF-07 | P0 D | Emergency stop | Block new tools/calls, stop audio, and retain known task outcomes |
| CF-08 | P1 N | Backup and restore | Restore nonsecret configuration, task state, and memory references with a restore test |
| CF-09 | P1 N | Migrations and updates | Explicit schema version and package rollback |
| CF-10 | P1 N | Observable budget | Estimate before expensive work, actual usage where available, and unknown-cost state |

## 16. Proposed extensions and rationale

| Proposal | Why it helps | Requirements |
| --- | --- | --- |
| Morning briefing with sources | Everyday usefulness with one command | NT-07, PD-01, PD-03 |
| Monitors quiet until something changes | Reduce noise and model consumption | TK-09, TK-10, NT-03 |
| Decision continuity across voice, text, and phone | Avoid repeating context during a task | PH-12, ME-02, TK-06 |
| Verify the resulting effect | Prevent success claims after a mere attempt | TL-04, CD-04, TK-08 |
| Verifiable private mode | Clear boundaries for sensitive requests | ME-08, UI-08, CF-06 |
| Reusable recipe after successful work | Turn a useful procedure into a reviewed skill | IN-09, TK-01; P2 proposal |
| Preventive integration diagnostics | Prevent missed notifications from expired tokens | TL-09, UI-12 |
| End-to-end strict local profile | Prevent a local LLM choice from hiding remote STT/TTS/MCP transfers | IN-03, IN-05, UI-07 |

## 17. Beyond the first installation

Multiple users, whole-home listening, native mobile apps, server high availability, core self-modification, autonomous purchases, and indiscriminate third-party calls are expansions. They are not dependencies of the first Mac installation. Carrier integration and support for one local and one cloud model remain part of the requested product.

This catalog is a baseline to refine through use: no prototype is complete while P0 requirements remain uncovered within its declared scope.
