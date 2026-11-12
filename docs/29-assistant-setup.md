# Assistant features: setup and acceptance

Updated November 3, 2026. Choose the authority before configuring accounts:

- **Local Mac:** rebuild with `./scripts/build-macos.sh`, then quit and reopen
  the source-linked `dist/Jarvis.app` through Launch Services.
- **Local Windows/Linux:** rebuild the portable service/dashboard from current
  source; the October downloadable preview predates these feature additions.
- **Remote:** follow [server deployment](../deploy/README.md), pair an
  administrator browser/companion and configure the server there. Build/install
  companions using [their guide](../companions/README.md); pair a separate desktop
  executor for granted local files, commands, Apple Calendar or a chosen window.

Installation does not connect accounts or grant device access. Pages follow the
current Personal/Work scope; private sessions allow reads and temporary sources
but block persistent feature edits. Remote scope/privacy belongs to each client
session. Local standalone and remote mode have separate data and schedulers.

The feature-by-feature requirements, security analysis and development gates are
in [chapter 27](27-assistant-expansion.md). Remote behavior and current acceptance
are in [chapters 32](32-remote-implementation.md) and
[33](33-current-state-and-verification.md).

## Today and activities

- **Today:** save up to three priorities. Calendar and weather use the existing
  Productivity settings. Choose an explicit morning/evening time and delivery
  method to enable a briefing. The owning core must be running; local mode needs
  an awake computer, remote mode needs the server. Expired briefings are skipped.
  An available remote core does not make a Mac-only calendar or speaker available;
  use reachable cloud sources and verify the intended notification channel.
- **Activities:** create projects and activities, optionally with parents, due
  times and estimates. These are the owner's commitments, separate from agent
  execution jobs. Select activities and a time window to propose work blocks.
  A proposal does not create a calendar event; the calendar is checked again
  before the normal event authorization flow.
- **Meeting preparation:** opens a request based on the agenda and authorized
  memory reads. Missing/partial calendar coverage remains visible.

Example: “Prepara il briefing della giornata e aiutami a preparare la prossima
riunione, senza modificare il calendario.”

## Mail

1. Open **Mail → Add email account** in the intended scope.
2. Enable Gmail API in a dedicated Google project, or register a Microsoft app
   with delegated `User.Read`, `Mail.Read`, `offline_access` permissions. In local
   mode, use the provider's installed/desktop flow and exact loopback callback
   shown by Jarvis. In remote mode, register an application that accepts the exact
   HTTPS callback `https://<core-domain>/oauth/mail/callback`; a Desktop client
   restricted to loopback is not the remote configuration. Enter the matching
   client ID/secret and permitted consent users on the owning core.
3. Sending is optional. Enable it explicitly and reconnect to consent to
   `gmail.send` or `Mail.Send`. Existing consent without that permission cannot
   send. Keep provider application/organization restrictions in force.
4. Save, select **Connect**, open the provider consent link, then refresh the
   connection. Callback state is one-use and expires; begin again if it expires.
5. Read/search the mailbox, open a message, or create a local draft. Review the
   sender, all recipients including Cc/Bcc, subject and body before sending the
   exact version. Provider acceptance does not establish delivery.

The Gmail/Graph adapters read at most ten messages per page. Mail HTML is rendered
as text, remote images are not fetched, and attachments are listed but not opened.
Messages are not automatically stored in Second Brain. A failed/unknown send must
be checked at the provider and explicitly reconciled before retrying. Disconnect
removes local credentials; revoke provider consent separately when needed.

Official references: [Gmail native OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Graph message reads](https://learn.microsoft.com/en-us/graph/api/user-list-messages),
[Graph MIME sending](https://learn.microsoft.com/en-us/graph/api/user-sendmail).

## Automations

Create a named rule, select its source and event condition, then preview the source
before saving. Calendar rules support changes, additions, overlaps and imminent
events with a 1–120 minute lead time. The polling interval limits timing precision;
choose an interval consistent with the required warning time.

Other targets are an authorized workspace directory, a scoped mailbox account ID,
an allowed Jira project, an allowed GitHub repository, or a granted Home Assistant
read tool. Home arguments must be a JSON object matching the discovered tool.
Directory rules inspect regular-file metadata, not arbitrary file contents.

The first successful check establishes a quiet baseline. Unchanged sources do not
notify. Cooldown coalesces changes. Paused rules do not poll. Mail/Jira/GitHub checks
inspect bounded current pages, so this is not a complete provider event archive.
Preview does not enable a rule or change its baseline. Rules run while Jarvis is
awake; local mode, permissions and failed-source coverage remain authoritative.

Choose a notification or an owner-written analysis instruction. Event analysis
can read authorized sources, including documents in an allowed workspace, but the
gateway rejects mutations, messages and commands. Start a separate user request
for further action. Voice alerts observe quiet hours, mute and lock. Local event
history expires after seven days; deleting a rule removes its event copies.

For remote deployments, rules run on the server. A directory rule checks a
workspace on the **core host**, not an executor folder. Stock remote mode grants
no host workspaces, so pairing a Mac does not enable remote directory watching.
Mail/Jira/GitHub/Home Assistant rules need services reachable from the server.
Push notifications are a separate delivery mechanism, not provider event ingestion.

## Documents and screen context

Choose/drop PDF, DOCX, UTF-8 text/Markdown/CSV, PNG or JPEG in **Chat → Add attachments**. Limits
are 3 MB per file, 30 PDF pages and bounded extracted text. Select sources before
discussing/comparing them. Extraction happens on the owning core in a separate process;
scanned pages use installed Tesseract or Apple Vision when the native app is
connected. Unsupported/encrypted/active documents fail explicitly. A missing OCR
engine produces an incomplete result rather than invented text.

On macOS the parser also runs with OS-enforced read/write boundaries and no
network access, in an empty temporary working directory. Windows/Linux currently
use a minimal-environment bounded worker rather than an equivalent OS sandbox;
resource-limit support varies by platform. These limits are not a guarantee
against a vulnerability in a native parsing library.

Remote Compose instead runs the broker/parser in a separate no-network container
without the core's data volume or credentials, with Tesseract installed there.
`JARVIS_REMOTE_DOCUMENT_WORKER_SOCKET` must reach its shared Unix socket; an
unconfigured remote parser rejects uploads. Native sharing on iOS/Android stages
selected sources locally for explicit review/upload. Server extraction is not
on-device processing, and configured cloud analysis sends excerpts to the model.

Text and part references are retained; raw original uploads are not stored.
Persistent extractions have a configurable 1–365 day lifetime and explicit delete.
Private uploads expire from RAM after one hour/restart. Deleting a source does not
retroactively erase ordinary chat results, which follow history retention. Text
comparison does not verify visual layout or image semantics.

For **screen context**, open the paperclip in chat, choose a window, review the
preview, then attach it to your message. You can also ask Jarvis directly to
explain a window. The macOS system picker requires you to select one window each
time. Cancellation captures nothing.

The local Mac app provides the picker in local mode. In Companion, the selected
Mac executor must be connected and unlocked with its separate window capture
grant enabled. Choose the window on the Mac even when starting from your phone.
When a picker is unavailable, attach a screenshot from the same dialog.

The capture stays available in RAM for ten minutes in the same privacy context.
When you send the message, only extracted text is shared with the selected model,
including a cloud provider when configured. The preview image and the attached
window text are not saved in task checkpoints; answers follow chat history settings.

## Jira and GitHub

Use **Jira and GitHub** in Work scope for work accounts.

- **Jira:** defaults to `https://teamsystem.atlassian.net/` and project `BVTL`.
  Save and connect with dedicated browser OAuth. Organization administrators may
  need to allow the client/domain. Jarvis uses the official Rovo MCP flat tool
  catalog at `https://mcp.atlassian.com/v2/mcp?tools=all`. Searches use structured,
  escaped project/text criteria and ten results per page. The default stand-up
  view selects the current user's issues.
- **GitHub:** create an expiring fine-grained token for selected repositories and
  list exact `owner/repository` targets. Grant read permissions only as needed:
  metadata, issues, pull requests, contents, checks and commit statuses. Save and
  test the connection. No organization-wide token is required by the adapter.
- Writes start disabled. Enable issue/comment writes explicitly and grant only
  the provider permissions required. Agent effects still need exact approval.
- PR evidence includes a verified head revision, changes, reviews and CI evidence.
  Moving heads, absent permissions/checks and truncated pages are reported as
  stale/unknown/partial. Reading a patch never executes it or publishes a review.

“Prepara lo stand-up” gathers bounded Jira/GitHub evidence. Issue analysis and PR
review open ordinary scoped agent requests. Disconnect removes local credentials
and grants; revoke remote tokens/consent separately.

References: [Atlassian tools and flat catalog](https://developer.atlassian.com/cloud/rovo-mcp/guides/supported-tools/),
[Atlassian OAuth setup](https://developer.atlassian.com/cloud/rovo-mcp/guides/configuring-oauth-2-1/),
[GitHub fine-grained tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

## Home Assistant MCP

1. Install/configure Home Assistant separately. In its Model Context Protocol
   Server integration, disable **Expose all LLM APIs**, select the intended Assist
   API and expose only the entities Jarvis should see/control. Review **Require an
   administrator account** and use the narrowest account/exposure that works.
2. Copy the actual MCP URL from Home Assistant into Jarvis. Prefer HTTPS. A private
   CA can be configured with its certificate file. For a deliberately chosen
   private IPv4 LAN address, the explicit HTTP option permits unencrypted access;
   this is not enabled for arbitrary/public hostnames or metadata addresses.
3. Use a dedicated long-lived token, or choose browser OAuth. Local OAuth defaults
   to the loopback client ID/callback at `127.0.0.1:8766`; change the port if occupied.
   Remote OAuth uses the public core callback
   `https://<core-domain>/oauth/mcp/<configured-server-name>/callback`.
   A server requiring public client metadata needs an owner-hosted HTTPS metadata
   document declaring that exact callback; the installed Home Assistant must
   accept the configured client identity. Complete consent from the initiating
   administrator companion's **Authorizations** page. No client secret is
   embedded in a mobile app or borrowed from Codex.
4. Save, connect, then discover tools. All new tools are disabled. Grant only
   selected reads/actions and save grants. Schemas describe the actual installed
   API; supported light/scene/climate capabilities depend on that API and exposure.
5. Read state through the permitted tools or ask Jarvis about the home. For a
   change, review the exact arguments and confirm within five minutes. The service
   rechecks current schemas, connection and permissions. Provider acceptance and
   subsequent state readback are displayed separately.

An uncertain action blocks repeating the identical physical command across new
proposals. Check actual state and Home Assistant logs, then record verification
evidence before retrying. Revoking grants immediately blocks future calls. Entity
exposure in Home Assistant remains the boundary for which devices are reachable.

Reference: [official Home Assistant MCP configuration](https://www.home-assistant.io/integrations/mcp_server/).

## Remote continuity, voice and notifications

Pair each app/browser separately. An administrator can configure the core model,
dedicated API key, declared token rates and budget. Reload settings after a stale
revision conflict. Model/provider credentials remain on the server; the phone's
device credential is independently revocable.

Companion voice records at most 60 seconds, transcribes for review, then sends the
edited text explicitly. Optional TTS uses the core's `phone_tts_model` and
`phone_tts_voice`, with a dedicated OpenAI voice key or eligible official OpenAI
text key. This is separate from local Mac wake/Live and Twilio calls. STT/TTS
budget estimates use the remote rate settings. A saved Live custom voice ID is
not a companion TTS voice.

Accepted server work continues when the mobile app closes. APNs/FCM requires
server credentials and device permission; a generic push retrieves authenticated
details when opened. A notification cannot approve a pending action. Desktop
notices need the companion process running. Native voice delivery needs an
available audio host and is not automatically routed to a phone or Mac speaker.

The remote model, memory, cloud accounts and home network route must work without
the Mac for independent availability. Desktop commands/files and Apple Calendar
need that executor online; native Hue Bluetooth remains in the local AppKit mode.
Local standalone mode does not take over automatically when the server is offline.

## Account and device acceptance before enabling real actions

Synthetic protocol/browser tests do not establish personal provider consent,
organization access or physical success. After restarting the built app, verify:

- Intended Personal/Work accounts and read-only results before enabling writes.
- One authorized email draft to an owner-chosen test recipient, including its
  provider sent record; exact recipients/content must match the reviewed draft.
- Jira organization consent and project permissions; GitHub repository access,
  PR head and CI permissions.
- Home Assistant read grants first, then a harmless exposed device command with
  actual state/log verification and revoked-grant rejection.
- Native screen picker cancellation/selection/lock behavior and real OCR quality.
- Briefing/notification timing while awake and after sleep, including quiet hours.

For remote acceptance, also verify a request/result with the Mac off, a granted
desktop operation and reconnect without replay, per-session private/scope
isolation, device revocation, real push/share/audio, public OAuth consent and
encrypted restore with historical credentials revoked. These are deployment
checks; the [current verification record](33-current-state-and-verification.md)
identifies the automated and packaged evidence already available.

No such personal-account/device checks were silently performed during the
documentation review. The remote core and companion source are implemented;
public hosting, signing and real-device/provider acceptance remain separate.
