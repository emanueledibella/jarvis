# Assistant features: setup and acceptance

Rebuild the native Mac bundle with `./scripts/build-macos.sh`, then quit and reopen
Jarvis to load the new service/native capabilities. The source-linked bundle is
`dist/Jarvis.app`. Installing these changes does not connect personal accounts or
grant access to devices. New pages follow the current Personal/Work scope; private
sessions allow reading and temporary sources but block persistent feature edits.

The feature-by-feature requirements, security analysis and development gates are
in [chapter 27](27-assistant-expansion.md). Mobile deployment is a separate
[companion proposal](28-companion-architecture.md).

## Today and activities

- **Today:** save up to three priorities. Calendar and weather use the existing
  Productivity settings. Choose an explicit morning/evening time and delivery
  method to enable a briefing. Jarvis must be awake; expired briefings are skipped.
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
2. For Gmail, enable Gmail API in a dedicated Google project and create a Desktop
   OAuth client. Configure its client ID/secret and permitted consent users. For
   Microsoft, register an application with the exact loopback callback shown in
   the page and delegated `User.Read`, `Mail.Read`, `offline_access` permissions.
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

## Documents and screen context

Choose/drop PDF, DOCX, UTF-8 text/Markdown/CSV, PNG or JPEG in **Documents**. Limits
are 3 MB per file, 30 PDF pages and bounded extracted text. Select sources before
discussing/comparing them. Extraction happens locally in a separate process;
scanned pages use installed Tesseract or Apple Vision when the native app is
connected. Unsupported/encrypted/active documents fail explicitly. A missing OCR
engine produces an incomplete result rather than invented text.

On macOS the parser also runs with OS-enforced read/write boundaries and no
network access, in an empty temporary working directory. Windows/Linux currently
use a minimal-environment bounded worker rather than an equivalent OS sandbox;
resource-limit support varies by platform. These limits are not a guarantee
against a vulnerability in a native parsing library.

Text and part references are retained; raw original uploads are not stored.
Persistent extractions have a configurable 1–365 day lifetime and explicit delete.
Private uploads expire from RAM after one hour/restart. Deleting a source does not
retroactively erase ordinary chat results, which follow history retention. Text
comparison does not verify visual layout or image semantics.

**Screen context** requires the native Mac app. Choose a single window through
the macOS system picker; cancellation captures nothing. The image/text remains
in RAM for ten minutes and is cleared on privacy-context changes. Analysis sends
extracted text to the selected model, including a cloud provider when configured.
This is on-demand reading, without background screen monitoring or app control.
The real system picker/permission experience needs an owner device check.

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
3. Use a dedicated long-lived token, or choose browser OAuth. Default OAuth uses
   the loopback client ID and callback at `127.0.0.1:8766`; change the callback port
   if occupied. A server requiring public client metadata needs an owner-hosted
   HTTPS metadata document declaring the exact callback. No client secret is
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

## Local acceptance before enabling real actions

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

No such account/device checks were silently performed during development. The
mobile gateway and companion app remain a design proposal, not an enabled remote
surface.
