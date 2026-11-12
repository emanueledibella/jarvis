# Changelog

This log describes repository development, not published production releases.
The current capability/build matrix is in [Current state and verification](docs/33-current-state-and-verification.md).
Version remains `0.1.0` in the application manifests.

## November 10, 2026 — assistant harness

- Start ordinary turns with a small tool set, and load capabilities and
  instructions when needed. Keep original evidence available when the model's
  context is shortened.
- Reuse successful public reads inside a task, stop loops with unchanged
  results, and track provider cache tokens when available. Deep public research
  can use a bounded specialist with read-only tools.
- Activate the coding workflow only for explicit code requests. Add ranged
  workspace reads and revision-checked exact edits. See the
  [upstream review and measurements](docs/38-harness-review.md).

## November 10, 2026 — spoken lookup updates

- Start public web research without a confirmation prompt, including in an
  ongoing conversation when the search uses words from the current request.
- Give one short spoken update during weather, web and calendar lookups or
  slower requests, then report the result. Keep fast replies direct and use
  the configured voice for both phrases.

## November 10, 2026 — companion wake listening

- Keep listening while the user continues speaking, even if the on-device
  recognizer pauses or renews its transcript. Submit the whole request once.
- Keep the same microphone open after waking on iPhone and Mac. Live uses the
  retained audio after the wake name when available; otherwise the complete
  local transcript is used, as on Android hands-free.
- Read the completed reply with the configured OpenAI Live voice even when the
  request was submitted as text. The readback does not reopen the microphone
  or submit the command again.
- Wait for iPhone unlock before accessing the saved connection. A temporary
  connection error offers a retry without asking for a new pairing code.

## November 4, 2026 — companion OAuth consent visibility

- Show pending OAuth consent in a global companion dialog with an explicit link
  to the system browser, including when connecting Second Brain from Memory settings.
  Previously the link existed only in the separate Connection tab.
- Track discovery until it succeeds or fails; starting a background connection
  no longer displays a success notification before authorization completes.
- Verify HTTPS/expiry/credential checks, the owner-device callback boundary and
  a synthetic UI flow from connection through callback to verified status.

## November 4, 2026 — managed telephony on the remote core

- Use the remote core's stable public HTTPS ingress for managed Twilio calls,
  without starting local Caddy/cloudflared processes. Companion shutdown does
  not stop telephony; enabled remote ingress survives a core restart.
- Show readable missing configuration requirements and explain core ownership
  in shared Mac/mobile settings. Refresh the settings revision after activation
  and deactivation, and keep incoming PIN validation independent of outbound PIN.
- Verify 75 focused Python regressions, 26 web tests, and isolated Linux image
  preflight without contacting a real carrier. See the managed telephony guide.

## November 4, 2026 — browser, Python sandbox and Apple Health

- Add interactive Chromium through disposable network-disabled workers, controlled
  public HTTP fetching, page revisions, DOM checks, screenshots and downloads.
- Add isolated Python with NumPy/pandas/matplotlib, selected inputs, temporary
  output artifacts, resource/time limits and cancellation of real containers.
- Add Apple Health XML/ZIP imports, source-separated daily activity/sleep summaries,
  provenance, deletion and cloud-model access disabled until explicitly enabled.
- Add read-only HealthKit access in the iOS companion, selected categories, local
  preview and explicit sharing of aggregates. Install development build 5 on the
  paired iPhone, update the signed Mac companion and deploy the verified core
  with one resource-limited sandbox at a time on the existing small server.
- Add shared English/Italian dashboard pages, gateway tools and a dedicated remote
  Docker broker. See [setup and verification](docs/37-browser-python-apple-health.md).

## November 4, 2026 — companion settings and voice parity

- Reuse the native settings UI on Mac and mobile companions, including complete
  Twilio configuration, phone PIN/limits and test calls; retain revision checks,
  administrator grants and encrypted server-side secrets.
- Add local wake recognition, automatic spoken requests/responses and follow-up,
  Mac menu/shortcut/background listening, and foreground iOS/Android listening.
  OpenAI Live reuses the native voice protocol through an authenticated,
  client-bound WSS transport with echo-protected interruption and RAM handoff.
- Keep microphone selection/consent local; stop capture on mute, logout, privacy
  changes, background/lock and emergency. Remove server/container settings that
  permanently disabled companion voice. Fix mobile navigation and settings layout.
- Verify 646 Python tests, 25 web tests, desktop bridge and native regressions,
  iOS simulator/Android builds and desktop/mobile UI with synthetic Twilio data.
  See [the parity record](docs/35-companion-native-parity.md) for device limits.

## November 4, 2026 — iOS companion pairing recovery

- Generate session and request UUIDs with cryptographically secure random bytes
  available in native WebViews, including custom-scheme contexts without
  `crypto.randomUUID`. Prepare the session before consuming a pairing code.
- Share an overlapping enrollment request so a single-use code is submitted
  once; disable keyboard autocorrection for the code field.
- Add regressions for unavailable WebView APIs, overlapping submissions and
  UUID version/variant bits. All 19 web tests pass; the signed iOS device update
  is build 3. The native scene now preserves the storyboard window and registers
  the Keychain plugin in its programmatic fallback. Capacitor payload logging is
  disabled and app/extension build numbers stay aligned. Deployment evidence
  records the native vault probe and physical connection outcome.

## November 3, 2026 — workspace voice continuity changes

These changes are present after the committed baseline and documented in
[chapter 34](docs/34-voice-listening-continuity.md).

- Preserve local dictation across Apple recognition task renewals/final events and
  recoverable errors; replay audio from the renewal gap instead of losing the request.
- Treat `listen_timeout_seconds` as inactivity while waiting for speech, separately
  from the maximum OpenAI session duration. The settings label now says Wait for speech.
- Track audible Live input and queued playback independently of transcript arrival;
  quiet keepalive packets do not prolong an abandoned session.
- Wait for the configured input quiet period before backend delegation and serialize
  transcript selection, avoiding partial/duplicate requests during long explanations.
- Start a replacement Live connection directly after confirmed local interruption,
  forbid listening interjections in every mode and report session closure reasons.
- Require fresh sustained audible evidence before escalating a soft recognition
  retry into a capture restart; retain other stopped-task/capture recovery paths.

## November 3, 2026 — remote core and companions

Source commit: `6ff2d65` (`Add remote core, companion apps and expanded assistant features`).
The commit also incorporates the October 28–30 work recorded below.

- Added the always-on `jarvis server` mode, dedicated device pairing/revocation,
  short-lived access tokens, rotating refresh tokens and per-session scope/privacy.
- Added administrator model/key/budget configuration with revision-conflict checks,
  encrypted core secrets, public integration OAuth callbacks and restricted HTTP MCP.
- Added outbound WSS desktop executors with local workspace/command grants, a durable
  effect journal, bounded offline waiting, cancellation and uncertain-outcome handling.
- Added Electron macOS/Windows companions and Capacitor iOS/Android projects with
  credential vaults, explicit STT/review/TTS, generic notifications and native sharing.
- Added a macOS EventKit/chosen-window executor helper; native wake and Hue Bluetooth
  remain capabilities of the separate local AppKit app.
- Added Linux Docker/Compose/Caddy deployment, a network-disabled document parser,
  encrypted age backup/restore and the remote-companions build workflow.

Development evidence covers Linux containers, macOS ARM64 packages, Android debug
and iOS simulator. Windows companion execution, physical devices, signing,
production deployment and real provider/push validation remain release work.

## October 30, 2026 — expanded assistant

Feature gates and final integration review are recorded in
[chapter 27](docs/27-assistant-expansion.md).

- Today priorities, calendar/weather briefings and explicit meeting preparation.
- Personal projects/nested activities, due dates, estimates and proposed work blocks.
- Scoped Gmail/Microsoft mail, OAuth, local drafts, reviewed sends and reconciliation.
- Event automation with quiet baselines, cooldown, history and read-only analysis.
- Cited PDF/DOCX/text/image sources, local OCR, comparison and bounded private uploads.
- On-demand macOS window selection, local OCR/preview and ephemeral screen context.
- Jira Rovo/GitHub configuration, allowlists, issue/PR/CI evidence and optional writes.
- Home Assistant MCP discovery, revocable tool grants and exact action review/readback.

## October 28, 2026 — calendar and telephony

- Shared calendar specialist with deterministic timing, conflict, urgency and
  coverage analysis; see [chapter 25](docs/25-calendar-assistant.md).
- Managed Caddy/Cloudflare activation/deactivation, signed reachability checks,
  incoming-webhook setup and child-process cleanup; see [chapter 26](docs/26-managed-telephony.md).
- Owner reminder openings, prepared Live audio, inbound opt-in/PIN enforcement,
  playback-bound keypad approval, carrier recovery and ingress hardening.

## October 26, 2026 — voice, memory and everyday tools

- English/Italian UI, wake-only timing cues, local echo-protected spoken interruption,
  automatic wake recovery and private per-app microphone selection/reconnect.
- Configurable Hue Bluetooth/MCP lighting and revocable direct-control grants.
- Default scoped Second Brain retrieval and automatic authorized dedicated writes.
- Date-aware weather forecasts, bounded public-web recovery and shared phone voice.
- Local service identity, credential/egress/scope hardening and publication controls.

## October 24–25, 2026 — local baseline

Initial analysis, AppKit/WebKit host, React command center, FastAPI/Deep Agents core,
local/cloud profiles, scoped tools, persistence, memory, routines and telephony adapters.
Windows/Linux portable preview packaging has its own
[dated verification record](docs/16-cross-platform-builds.md).
