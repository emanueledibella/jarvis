# Interface, orb, and dashboard

## 1. Product direction

The interface should feel like a present assistant with a recognizable visual center and readable information. Cinematic inspiration guides atmosphere/motion; assets, sounds, and components are original.

Initial proposal: deep blue background, light text, cyan accents, thin geometric rings. Amber signals attention; red is reserved for significant error/stop. Use readable content typography, with monospace limited to times/small technical details. Decoration must not compete with agenda or answers.

Avoid random-number panels and permanent animation. Every displayed item corresponds to a source, task, or useful state.

## 2. Surfaces

| Surface | Purpose | Content |
| --- | --- | --- |
| Menu bar | Presence/immediate control | Active/mute/error, dashboard, shortcut, shutdown |
| Compact overlay | Answer without interrupting work | Small orb, short transcript, state, stop |
| Dashboard | Everyday overview | Central orb, next event, weather, relevant tasks |
| Expanded conversation | Read detailed responses | Text, sources, files, history, input |
| Task detail | Understand/direct work | Objective, steps, tools, artifacts, errors, decisions |
| Settings | Connect/control the system | Models, audio, MCP, memory, calendar, phone, budget |

Closing the dashboard hides it. A separate clear menu action quits the service. Verifying microphone mute must not require a complex screen.

## 3. Dashboard layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│ JARVIS        Mac only · Local/Cloud profile        Microphone/State │
├─────────────────┬────────────────────────────┬───────────────────────┤
│ WEATHER         │                            │ NEXT EVENT            │
│ Selected city   │        CENTRAL ORB         │ Time and calendar     │
│ Source and time │        and text state      │ Time until start      │
│                 │                            │                       │
│ SHORT AGENDA    │  Latest phrase and reply   │ ACTIVE TASKS          │
│ Real events     │  “Tell me what you need”   │ State and result      │
├─────────────────┴────────────────────────────┴───────────────────────┤
│ Text input          Attachments       Private session       Stop    │
└──────────────────────────────────────────────────────────────────────┘
```

Adapt to window size: at narrow widths, orb/answer precede widgets; do not shrink calendar text into illegibility. A native mobile/phone view is not an already-decided part of the first product.

Two concept directions:

- **Focal orb:** large orb, few side details, suitable for voice/quick checks.
- **Operational:** smaller orb, visible work timeline, nearby agenda, suitable for coding/research.

They are variants of one application/state, not separate products.

## 4. Orb behavior

| Actual state | Representation | Accessible text |
| --- | --- | --- |
| Waiting for wake phrase | Quiet ring, minimal/no movement | “Ready — local wake detection” |
| Listening to command | Open ring and input level | “I am listening” |
| Processing | Slow movement independent of volume | “Checking…” and short task status |
| Speaking | Output-level pulse and small shape changes | “Speaking” plus transcript |
| Active tool | Task state beneath the orb | For example “Checking the calendar” |
| Decision needed | Amber emphasis and concrete action | “Your decision is needed” |
| Muted | Static orb and microphone-off symbol/text | “Microphone muted” |
| Error/missing capability | Distinct state, cause, recovery | “Calendar disconnected — reconnect” |
| Call | Channel/duration indicator | “On a call — identity verified/unverified” |

Final pulsing follows actual rendered audio RMS/envelope, smoothed against jitter. Algorithm details stay out of Home. Reduced motion uses a simple meter or equivalent static state.

Passive listening and active-command listening must be distinguishable. Baseline passive listening does not continuously transcribe to cloud.

## 5. Selected widgets

| Widget | Data | Proposed refresh | Actions |
| --- | --- | --- | --- |
| Weather | City, temperature, conditions, precipitation | 15–30 minutes, source/last refresh | Change city, details |
| Next event | Event, time, calendar, state | Incremental/polling and wake refresh | Open event, request briefing |
| Short agenda | Selected upcoming events | As above | Show day |
| Active tasks | A few relevant tasks/states | Event stream | Details, pause, cancel |
| Decisions | Pending proposals and expiry | Event stream | Open concrete proposal |
| Memory | Connection/pending-write state when useful | Events and lightweight checks | Inspect source/backlog |

CPU, RAM, provider latency, and token counts mainly belong in diagnostics. Show them on Home only when they help a decision, such as unloaded local model or nearly exhausted budget.

Every widget has initial, loading, available, stale, connection-required, error, and disabled states. Label concept demo data; never mix it with real product data.

## 6. Conversation

Visually distinguish partial transcription from final text. Allow terminology correction before ambiguous actions. Long responses have spoken summaries and readable details with sources/attachments.

Main actions: send, stop audio, cancel task, open result, private session. Avoid a central button for every tool.

“Use local” shows its turn/task effect and any remote-service requirement. Distinguish global profile and per-task override. A local LLM alone does not justify an “offline” label.

## 7. Task detail and decisions

Show objective, state, elapsed time, expected outcome, and artifacts. Operations get readable summaries; raw payload/log details belong in diagnostics.

Change/send proposals contain recipient, content/diff, relevant consequences, and a concrete choice. Respect existing task authorization rather than repeatedly confirming every read or authorized reversible step.

Uncertain remote effects require explicit labeling and reconciliation. A model ending generation is not enough for a green completion check.

## 8. Onboarding

1. Explain Mac operation and sleep limitations.
2. Enable/test microphone; make text available immediately.
3. Calibrate/test “Jarvis”, with push-to-talk fallback.
4. Register local/cloud models; test connection and tool calling separately.
5. Connect Second Brain and verify intended vault/scope without exposing credentials.
6. Optionally connect calendar and choose weather city.
7. Choose memory policy, retention, launch at login.
8. Set up telephony separately: carrier, number, identity, tunnel, call rules.

Mark unconfigured capabilities unavailable. Allow gradual onboarding; a phone account is unnecessary for a text question.

## 9. Accessibility and discretion

- Text state beyond color, visible focus, keyboard navigation.
- VoiceOver action labels without announcements on every orb frame/token.
- Readable contrast, text scaling, reduced motion.
- Overlay does not steal editor/browser focus and can be disabled.
- No private agenda/memory on the locked screen without the appropriate preference.
- Short optional sounds with visual alternatives; no spontaneous concept-demo playback.

## 10. Visual acceptance

Test long Italian/English content, empty calendar, disconnected provider, network error, muted voice, waiting task, active call, narrow widths, Retina, supported themes, and reduced motion.

Start with simple orb geometry and refine. Suspend rendering when hidden while voice stays independent. Perceived quality depends especially on response time, continuity, and truthful state.

## 11. Application identity (October 25 update)

The original orbital “J” mark uses the dashboard's cyan/navy palette. Its editable source is `web/src/assets/jarvis.svg`, also used in the sidebar and browser favicon. `scripts/build-icon.sh` renders a 1024-pixel PNG and all standard/Retina icon sizes into `native/Resources/Jarvis.icns`. The Mac bundle declares `CFBundleIconFile` and loads the same icon for the Dock and application switcher while its dashboard is open. Closing the window returns the app to menu-bar mode.
