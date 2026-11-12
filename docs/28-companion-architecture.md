# Jarvis companions: product and security architecture

Updated November 3, 2026. The delivered architecture is **one remote core,
desktop/mobile companions and a separate desktop executor**. The original
Mac-first and React Native proposal is superseded. See
[implementation/security evidence](32-remote-implementation.md),
[current coverage](33-current-state-and-verification.md) and
[build/pairing instructions](../companions/README.md).

## Roles and platforms

| Role | Delivered implementation | Owns |
| --- | --- | --- |
| Core | Python/FastAPI/LangGraph/Deep Agents on the server | Conversations, tasks, policy, effects, schedules, budgets, connections and model keys |
| Desktop companion | Electron on macOS/Windows, shared React UI | Interface, OS-vault device credential, explicit recording, tray/notices and executor lifecycle |
| Mobile companion | Capacitor on iOS/Android, shared responsive React UI | Explicit recording/playback, device credential, push registration and native source sharing |
| Desktop executor | Separate paired Python process with outbound WSS | Local workspace/native grants, execution and effect journal |
| Model | Configured external provider API | Inference on the permitted context supplied by the core |

The phone talks to the server, not directly to the Mac. It does not need model
weights or a second harness/scheduler. The local AppKit application is still
available as a separate standalone mode; it is not the Electron companion or an
automatic offline replica. Linux has a portable local service/dashboard, not a
packaged Electron companion.

## Everyday interaction

Pair an administrator app/browser using the one-use code issued by the server
CLI. Additional device codes are issued from the paired administrator.
Ordinary conversations can continue across devices in the same scope.
Each client session has its own Personal/Work context, privacy revision and
executor choice; private sources/tasks require their originating session.

The shared assistant exposes chat, Today/briefings, activities/projects, mail,
automations, documents, memory, Jira/GitHub, Home Assistant, routines and pending
decisions. Availability follows the core's configured providers and grants.
Administrator settings update the server's model, key, declared rates and budget,
using optimistic revisions; a stale save requires reload. The key is not read
back into the app.

Voice is explicit record → server STT → transcript review/edit → send text, with
optional server TTS. It records at most 60 seconds and does not provide ambient
wake or continuous native Live conversation. STT/TTS uses the core's
`phone_stt_model`, `phone_tts_model` and `phone_tts_voice`.
Local Mac Live/custom voice IDs and Twilio calls are different audio contracts.

Sharing a selected document, image, URL or text stages it in the app's private
inbox for up to fifteen minutes, at most five items of 3 MB each. The owner
reviews and explicitly imports/attaches it. Source text is evidence, not action
authority. Persistent server extraction and private temporary uploads retain
their own separate retention rules.

## Identity, storage and approvals

Implemented device authentication uses ten-minute one-use pairing codes,
five-minute access tokens and thirty-day rotating refresh tokens. Refresh reuse
invalidates the family. Companion, administrator and executor grants are distinct.
This is the personal-device protocol; the earlier proposed OIDC login was not
implemented. Integration OAuth remains a separate supported PKCE/consent flow.

Refresh credentials use iOS Keychain, Android Keystore-backed AES-GCM or desktop
safeStorage; access tokens stay in RAM. Same-origin browsers use an HttpOnly
refresh cookie and coordinate rotation across tabs with Web Locks.
Each device can be revoked; losing a phone does not require shipping a new
provider key in every application.

Review fetches the authoritative current proposal, arguments/hash, task and expiry.
A push, deep link or model confirmation cannot approve it. Server scope/session
checks remain authoritative. Local biometrics are not implemented as a mandatory
Jarvis approval step. Remote private content remains in bounded core RAM, with
minimal metadata retained for deduplication; provider processing terms still apply.

## Working on a computer

Pair an executor with its own code and explicitly select a local folder/scope.
Read, write and command grants are distinct. Commands require permitted prefixes
and local acknowledgment that project code runs with OS-user permissions.
Core approval cannot expand the local grant. Existing-file writes compare a
previously read SHA-256.

The executor opens WSS to the core and publishes capability/workspace IDs without
absolute paths. Jobs bind exact operation/hash, task/session, destination and
deadline. Duplicate delivery cannot run the same journaled ID twice. A lost result
can retransmit its receipt; an uncertain effect is not automatically retried.
Offline waiting is explicit and expires within ten minutes; private work requires
an online executor.

macOS adds separately granted EventKit and chosen-window operations through the
native helper. Each window capture still needs local system-picker selection.
Hue Bluetooth, native wake/echo processing and general mouse/keyboard automation
are not executor operations. Windows supplies workspace/commands; cloud calendar
and home capabilities run through the core.

## Availability and notifications

| Condition | Behavior |
| --- | --- |
| Desktop asleep/offline | Core jobs and reachable integrations continue; that desktop's capabilities are unavailable |
| Mobile app closes after acceptance | Server task continues; result can be inspected later |
| Core unreachable | Connection/retry state; no second local core, silent offline approval or delayed mutation replay |
| Scope/privacy changes | Affected session context/sources are separated; another device's microphone is not toggled |
| Device revoked | Future credentials/push and associated pending work are invalidated/interrupted |
| Unknown local effect | Inspect/reconcile the original outcome before starting replacement work |

APNs/FCM outbox payloads contain generic updates, with detail fetched after
authentication. Signing, push project credentials and OS notification permission
are setup requirements. Delivery/visibility is not guaranteed by a provider's
acceptance. Desktop generic notices need a running companion and permitted OS
notifications; closing its window keeps the tray, quitting does not.

Second Brain must be hosted/reachable independently of the Mac for memory while
it is off. Home Assistant needs a route available from the server. The telephony
proxy is a separate carrier ingress, not a way to publish the local bearer API.

## Verification and original alternatives

Code and development build evidence cover macOS ARM64, Android debug and iOS
simulator, with server/container and protocol/browser checks. Windows companion
CI is configured, but an executed Windows companion build is not established by
the local macOS evidence. Physical audio, share sheet, Keychain/TCC, push,
distribution signing and production hosting remain acceptance work.

The original proposal compared an awake Mac authority with an always-on server,
React Native/SwiftUI client options and OIDC-style login. Subsequent delivery
selected the server first, Capacitor mobile, Electron desktop and personal-device
pairing. A single SQLite/scheduler authority was retained. These decisions explain
the evolution; the earlier candidate stack is not an additional supported mode.
