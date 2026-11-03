# Jarvis companion: product and security architecture

Historical proposal: the later discussion chose the remote core first, with both
iOS and Android. See [the implemented architecture and verification](32-remote-implementation.md)
and the [companion build guide](../companions/README.md) for the current state.

## What smartphone access means

A companion app is a second user interface to the same Jarvis authority: chat,
push-to-talk, Today, activities, job progress, source sharing and action approvals.
The phone records an explicit voice request or shares a chosen document; the
configured Jarvis service runs tools and returns results. The phone does not need
to run the main language model. Its app remains useful outside the home network
when a secure network path and an awake authority are available.

This is separate from Twilio phone calls. The existing carrier feature can reach
the owner at a phone number; a companion offers a rich interface and authenticated
device identity, without placing a carrier call for each interaction.

## Recommended first delivery

Use the current Mac as the authority and build a companion with:

1. Device pairing and revocation.
2. Text chat, explicit voice capture and spoken replies.
3. Today, activities/projects and job status.
4. Generic push notifications with authenticated detail retrieval.
5. Review of exact pending actions, with fresh arguments and expiry.
6. A share extension/share target for an explicitly chosen page, image or document.
7. Visible online/offline state and source freshness.

For iPhone and Android, React Native is a natural candidate because the dashboard
and API work already use React/TypeScript. API models, validation expectations and
domain logic can be shared; most desktop DOM/CSS views cannot simply be copied
into native mobile screens. For an iPhone-only product, SwiftUI is an alternative
worth choosing deliberately. Signing, Apple/Google developer accounts, release
distribution and push credentials depend on that platform decision.

The first version should use explicit voice capture, with platform shortcuts as
an optional entry point. Continuous background microphone behavior requires
separate platform, permission, battery and store-policy validation.

## Connectivity and availability

### Option A: companion connected to an awake Mac

The smallest first delivery keeps the existing service and local files on the
Mac. A private VPN can provide network reachability to a dedicated companion
gateway. The gateway exposes only mobile-facing operations and calls the local
Jarvis API internally. The current local bearer token never goes to the phone.

The Mac must remain awake, logged in and connected. A sleeping/offline Mac cannot
run AI jobs, receive new requests or send fresh push notifications. The app shows
that state honestly. Previously downloaded data can be shown as stale cached
data; an offline phone must not silently approve an expired action.

### Option B: companion connected to an always-on authority

An always-on mini PC, suitable NAS/container host or server owns scheduling,
canonical state, mailbox/project connections and the mobile gateway. The Mac
becomes an optional paired satellite for its microphone, chosen windows,
Bluetooth devices and authorized local workspaces.

This provides availability while the laptop is off. Mac-only actions remain
unavailable until that Mac reconnects. Home Assistant operations can remain
available if the server can reach the owner's Home Assistant instance.

There must be one canonical scheduler and database authority. Running independent
Mac/server copies of the same routines risks duplicate effects. Do not share a
live SQLite WAL database over a network filesystem. Move the authority through a
verified migration/backup procedure and give satellites separate authenticated
capabilities. The existing loopback-only native bridge cannot be exposed directly.

## Gateway and device security

The current API intentionally binds to loopback and trusts a local owner token.
Mobile support needs a separate surface, not a setting that publishes the entire
dashboard, shell tools, native endpoints or telephony proxy.

Use a supported OAuth/OIDC authorization flow with PKCE for a public native
client, short-lived access tokens and rotating refresh tokens. Pairing should
have an explicit owner ceremony, a short-lived one-use code/QR, device identity,
proof of possession where supported, and a revocable device record. Secrets live
in iOS Keychain/Android Keystore-backed storage. A VPN improves reachability and
exposure, but does not replace app authentication.

Device grants distinguish chat/read access, source uploads, approvals and any
workspace capability. Each operation names its exact scope and conversation
privacy version. Mobile conversation privacy is per session/device; it must not
silently toggle a different user's or the Mac microphone's current context.

Approvals fetch authoritative current arguments, target, hash, expiry and task
identity. A notification, deep link or a model's text is never itself approval.
Local biometric confirmation can protect the review UI, but the server still
validates token/device authority, freshness and the exact proposal. Revocation
invalidates future access and queued decisions.

## Notifications and offline behavior

Use APNs for iOS and FCM for Android, either directly or through an explicitly
chosen delivery service. Push credentials and developer accounts are setup
dependencies. Push payloads carry a generic event identity, not private message
bodies, email recipients, source text or secrets. Details are fetched after
authentication; privacy/lock-screen preferences control what appears.

Cached data should be bounded and protected by the device. Queued new requests
have stable request IDs, scope, expiry and clear state. Mutations and approvals
need current server validation; they are not blindly replayed after hours offline.
The existing effect ledger remains the authority for duplicate/unknown outcomes.

## Required acceptance checks before release

- Pair, revoke, lose and replace a phone; reject stolen/replayed/expired codes.
- Refresh rotation, concurrent requests, clock skew and authorization expiry.
- Scope/private separation across Mac and multiple phones.
- Mac sleep/network loss/server recovery without duplicate work.
- Push redaction, denied permission, device changes and stale deep links.
- Exact approvals after proposal edits/expiry and uncertain remote effects.
- Shared file size/type boundaries, local cache deletion and account sign-out.
- Real iOS/Android audio, background and notification behavior on signed builds.
- Gateway TLS, rate limits, request/result bounds, audit and backup restoration.

## Suggested sequence

First build the paired companion against an awake Mac, after choosing iPhone-only
or iPhone/Android and the private-connectivity approach. Keep availability limits
visible. Then move the canonical service to an always-on host if independent
availability is needed. This keeps the first mobile delivery bounded while
preserving a coherent path to a continuously available personal assistant.

## Primary implementation references

- [React Native platform-specific and shared code](https://reactnative.dev/docs/platform-specific-code).
- [OAuth for native apps, browser authorization and PKCE](https://www.rfc-editor.org/info/rfc8252/).
- [Apple remote notifications](https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns).
- [Firebase Cloud Messaging](https://firebase.google.com/docs/cloud-messaging).
