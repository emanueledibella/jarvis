# Assistant expansion: requirements, implementation and verification

This record documents the October 30 expansion of the local assistant, preserving
the calendar/voice/telephony work present at that stage. Its initial baseline was
468 passing Python tests and two platform/optional-tool skips. The November 3
commit `6ff2d65` also delivers the remote core and companions. Current status and
rerun totals are in [chapter 33](33-current-state-and-verification.md); the
feature-specific gate counts below remain historical evidence.

## Delivery order

Each item has a requirements/security analysis before implementation and a
verification gate before the next item. Account-specific verification is recorded
separately from fixture-based tests; no account is connected or external message
sent merely to test the implementation.

1. Today, daily briefings and meeting preparation.
2. Personal activities and projects, with calendar-aware planning.
3. Email accounts, triage, drafts and explicitly authorized delivery.
4. Event-driven automation for calendars, files and connected services.
5. Document/image attachments, cited reading, comparison and extraction.
6. On-demand screen context and contextual assistance.
7. Jira and GitHub work assistance and configuration.
8. Home Assistant MCP connection, tool permissions and device workflows.
9. Companion architecture analysis, subsequently implemented as remote core,
   Electron desktop and Capacitor iOS/Android; see chapters 28 and 32.
   Real hosting, signing and account/device rollout remain separate setup work.

The ordering preserves the requested feature-by-feature workflow; dependencies
added later enrich earlier views without replacing existing behavior.

## Shared security requirements

- The authenticated loopback API and existing Host/Origin checks remain in force.
  The telephony tunnel never becomes a general remote API.
- User-owned configuration, allowed accounts/repositories/entities and explicit
  approvals define authority. Text from documents, calendars, mail, web, MCP and
  previous model output cannot grant permissions.
- Personal/work scope is an exact boundary for newly stored records. Private
  conversations cannot silently create persistent activities, documents or rules.
- Mutations use the existing argument-bound gateway/effect ledger; uncertain
  external results are reconciled instead of blindly repeated.
- Secrets stay in private local configuration, are omitted from listings and
  errors, and are not passed to unrelated tools or children.
- Bounded inputs, timeouts, concurrency, result sizes, retention/deletion and
  disabled/offline states are part of each feature's acceptance criteria.

## 1. Today and briefings — analysis

### Functional requirements

Provide a scoped Today page and agent tool with the local date/time zone, up to
three owner-selected priorities, reminders, active/recent agent work and verified
calendar analysis. Weather and calendar reads can fail independently and must
retain coverage/freshness warnings. A disabled source is distinct from an empty
source. Never infer free time from an incomplete agenda.

Provide opt-in morning/evening briefings, selectable local times and desktop or
voice delivery. Reuse persistent scheduling, date/DST handling and missed-run
rules. Saving settings twice must not create duplicate routines. Reading Today
must never create a task, schedule, speech playback or memory write.

Provide meeting preparation as an explicit user task using the verified event,
owner request and separately authorized memory reads. Calendar descriptions are
untrusted context. Briefings summarize sources and suggest next actions; they
cannot move events or send invitations without the existing authorization path.

### Security and development needs

Store preferences by scope with optimistic revision checks. Persistent changes
are unavailable in a private session or during emergency stop. Managed briefing
schedules are updated atomically with preferences. Background delivery is opt-in,
uses conservative missed-run handling and respects the configured profile. Strict
local mode does not make remote calendar/weather calls. Remote errors reveal only
sanitized categories. The UI cancels stale scope requests and has loading/error,
keyboard, narrow-screen and Italian/English states.

### Verification gate

Test scope separation, empty/partial/error sources, strict-local no-egress, private
and emergency write rejection, stale revision rejection, schedule deduplication,
atomic settings, and a gateway-backed Today tool. Check TypeScript and the frontend
regressions before proceeding. Real voice delivery and personal calendar access
remain separate account/device checks.

### Implementation and gate result

Added the Today page, scoped/versioned preferences, the gateway-backed
today_overview tool and opt-in morning/evening schedules. Preferences and managed
schedule changes commit atomically. Tomorrow's events are excluded from the day
view; uncertain entries remain visible with their source warnings. Meeting
preparation starts an explicit agent request and can use scoped Second Brain
reads. Weather/calendar errors do not fabricate an empty or fully available day.

Gate: 35 focused Python cases passed (Today, calendar and scheduling), Python
lint passed, TypeScript passed and all 10 frontend regressions passed. Italian
copy was checked by the catalog test. Device/account delivery is not claimed
verified by these synthetic tests.

## 2. Personal activities and projects — analysis

### Functional requirements

Maintain owner activities separately from agent execution tasks. Support named
projects, nested activities, open/in-progress/completed states, priority, estimated
minutes, optional aware due times, notes and source links. Provide create, edit,
complete/reopen, filtering and deletion through the dashboard and typed agent
tools. Project/subtask relationships cannot cross scopes or create cycles.

The Today view includes outstanding activities and overdue flags. Planning uses a
fresh verified agenda and proposes contiguous work blocks within an explicit
aware time window. Estimates are owner-provided, never invented; incomplete or
unverified calendar coverage cannot produce confirmed free slots. Creating a
calendar block remains an explicit calendar effect through the existing gateway.

### Security and development needs

Every read/write resolves the record in the current exact scope. Edits/deletes
require the expected revision to prevent lost updates. Validate parent/project
ownership, time-zone awareness, bounded content and safe source-link schemes.
Block persistent changes from private contexts and after emergency stop. The
model tools use the existing approvals and effect ledger, including deletion.
Direct UI actions carry the current privacy revision.

Deleting an activity removes its child activities only after an explicit cascade
choice; deleting a project unassigns activities without deleting their work.
Persistent records are intentional owner data and support explicit deletion;
ordinary dialogue retention must not silently erase the owner's task list.

### Verification gate

Exercise cross-scope IDs/parents, revision races, cycles, invalid dates/links,
private/emergency rejection, cascading choices, Today enrichment and planning
around real overlap/DST/free-busy fixtures. Verify typed gateway access, UI
creation/completion/editing, localization and TypeScript.

### Implementation and gate result

Added scoped projects and nested activities with due dates, estimates, priority,
source links and optimistic revisions; CRUD is available in the dashboard and
gateway-backed tools. Today includes outstanding activities. The planner checks
fresh calendar coverage, busy intervals and estimates and returns proposals only;
all-day commitments require review. Project deletion keeps activities, and
subtask deletion requires an explicit cascade choice.

Gate: 29 focused Python cases passed (organizer, Today, agent policy), Python lint,
TypeScript and all 10 frontend regressions passed.

## 3. Email — analysis

### Functional requirements and provider dependencies

Connect Gmail or Microsoft mailboxes with dedicated OAuth application credentials,
PKCE, browser consent and a loopback callback. Support multiple named accounts
assigned to exact personal/work scopes, disconnect, read/search/pagination,
message details and plain-text body extraction. Fetch no remote images and run no
mail HTML or attachments. The account connection is separate from calendar OAuth.

Drafts are reviewable local records with explicit To/Cc/Bcc, subject, body and
optional reply identity. Support creating, editing, deleting and sending the exact
reviewed revision. Agent triage and suggested replies use source message IDs;
extracting an activity remains a separately authorized organizer mutation.

Gmail needs an enabled Gmail API, a Desktop OAuth client and an authorized test
user/verified consent setup as appropriate. Microsoft needs an app registration
with a loopback redirect and delegated mail permissions. Initially request read
access; sending is an explicit connection option requiring its own OAuth scopes.
No account credentials or application registration are fabricated.

### Security and development needs

OAuth uses random one-use state, S256 PKCE, a short expiry, fixed provider
endpoints, an exact loopback redirect and account/configuration/session binding.
Never accept provider callback text as an instruction or redirect target. Callback
codes/tokens are not logged; normal service access logging is already disabled.
Token rotations are saved privately and listings redact secrets.

Mailbox queries are bounded, pagination is opaque/validated and cannot become an
arbitrary credential-bearing URL. Responses are size/time bounded. IDs and
recipients reject path/header injection. External bodies become untrusted
context before follow-up effects. Offline mode, emergency stop, scope and private
write rules remain authoritative.

Send authority binds account, complete recipients/content and draft revision.
Double delivery executes once. An ambiguous timeout leaves an unknown outcome
that blocks retries until explicit reconciliation. Provider acceptance is
reported as accepted, not proof of delivery. Local draft deletion is explicit;
mailbox content is read on demand and not silently ingested into Second Brain.

### Verification gate

Use synthetic Gmail/Graph responses to test PKCE/state/replay/expiry, token
rotation and redaction, cross-scope account/draft IDs, MIME/HTML handling, bounded
inputs, exact reviewed sending, duplicate requests and uncertain outcomes. Check
the complete configuration/read/draft/review UI and preserve Italian/English.

References: [Google installed-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Gmail drafts](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts),
[Microsoft message reads](https://learn.microsoft.com/en-us/graph/api/user-list-messages),
[Microsoft draft sending](https://learn.microsoft.com/en-us/graph/api/message-send).

### Implementation and gate result

Added dedicated Gmail/Microsoft PKCE consent, scoped accounts, verified sender
identity, private rotating tokens, bounded reads/search/pagination and plain-text
message rendering. Local drafts have complete recipient/content review, hashes
and revisions. Both adapters send MIME, including verified reply headers; Gmail
also preserves the original thread ID. Send effects are deduplicated, uncertain
results block retries and support evidence-based owner reconciliation.

Gate: 46 focused Python cases passed (mail, security and routine permission
boundaries), Python lint, TypeScript and all 10 frontend regressions passed.
No real mailbox consent or message delivery was attempted. Personal application
registration and consent remain explicit setup steps in the Mail page.

## 4. Event-driven automation — analysis

### Functional requirements

Persist named rules for calendar changes/conflicts/imminent events, arrivals or
changes in an explicitly authorized directory, new mailbox messages, and later
Jira/GitHub changes. Support enable/pause, edit/delete, a read-only preview,
poll interval, cooldown, recent event history and desktop/voice delivery.
The first successful snapshot establishes a baseline without announcing old
items. Unchanged data stays quiet. Errors do not replace the baseline or masquerade
as deletions. Resume after sleep performs a current check without replaying an
unbounded backlog. Duplicate checks produce one event.

Actions are a deterministic notification or an explicitly configured analysis
task. An analysis task reads a separate untrusted event tool result, never treats
provider text as the owner's request, and cannot perform mutations. Further
changes are initiated by a separate user request with ordinary approvals.

### Security and development needs

Configuration is scoped and privacy-versioned. Directory polling revalidates
workspace confinement and symlink/secret exclusions each time; no arbitrary
filesystem watching or command execution. Provider polling rechecks current
account and allowlist policy. Strict-local/emergency states prevent remote work.
Rules are bounded, serialized and polled with timeouts and cooldowns; snapshots
and event payloads are bounded. Event retention and explicit deletion remove
stored copies without touching original provider data. Voice notification is
opt-in, suppressed while locked/muted and observes quiet hours.

### Verification gate

Test baseline/no-change behavior, source failures, concurrent checks, cooldown,
pause/delete, private/scope constraints, path replacement and symlink exclusion,
sleep recovery, and prompt injection via event content. Analysis tasks must keep
event data outside their original owner prompt and the gateway must reject every
mutation even if the model attempts one. Test UI configuration and localization.

### Implementation and gate result

Added scoped persistent rules, source previews, baselines, cooldowns, pause/edit/
delete controls and seven-day event history. Sources include calendar conditions,
confined directory metadata and connected mail; Jira/GitHub adapters are wired
through the development feature below. Event-triggered analysis receives source
data through a separate tool and is read-only at the gateway, including after
checkpoint reconstruction. Voice notifications respect quiet hours, mute and
lock. Directory scans pin a confined directory handle on POSIX and use the Windows
directory guard.

Gate: 23 automation/agent/scheduler cases and a further 30 automation/mail/
organizer cases passed; lint, TypeScript and 10 frontend regressions passed.
Mail polling observes the newest bounded page; high-volume mail is not claimed
to have lossless provider push delivery. Remote push delivery is now implemented through the
companion/server outbox, separately from these provider polling sources. The
existing phone tunnel is not reused as the companion API.

## 5. Documents, images and attachments — analysis

### Functional requirements

Accept explicitly selected/dropped PDF, DOCX, UTF-8 text/Markdown/CSV and PNG/JPEG
files. Extract bounded page/paragraph/line evidence with a source hash, support
scoped listing/search/read/delete, attach source IDs to a chat request, compare two
sources with cited evidence and propose extracted activities through existing
organizer tools. The conversation stores attachment identities separately from
the owner's words: document text cannot become owner testimony or memory input.

Provide local OCR for images and scanned PDF pages with clear OCR confidence and
coverage limits. Native macOS Vision can be used through the existing native
bridge; portable builds can use an explicitly installed local OCR runtime.
No cloud upload, remote image loading or automatic Second Brain ingestion occurs.
Private attachments stay in bounded RAM and expire; persistent attachments are
explicit owner records with individual deletion and retention controls.

### Security and development needs

Bound request/file/page/pixel/text/archive sizes, reject unsupported types and
misleading extensions, block encrypted PDFs, active document content, macros,
archive expansion bombs and XML entities. Run parsing in a minimal-environment
child with wall/CPU/address-space limits where available. Cancel/kill/reap workers
on timeout, keep input bytes in pipes, and do not run embedded scripts or fetch
references. OCR is local and bounded. Native permission is requested only when
needed, with no silent fallback to a cloud service.

Store normalized extracted evidence, not executable originals, under random IDs
and hashes. Every attachment lookup checks scope and private-session ownership.
Attachment IDs are server-validated before model invocation; external evidence
uses ToolMessages and is marked sensitive/untrusted before the first model turn.
Excerpts and comparisons have precise source/page identities and explicit
truncation. Unsupported visual/layout claims are not inferred from plain text.

### Verification gate

Test real synthetic PDF/DOCX/image/text extraction, hashes and citations,
malformed/encrypted/oversized files, archive/XML attacks, worker timeout/cleanup,
scope/private isolation, expiry/deletion, source IDs in conversations and prompt
injection that cannot authorize effects or save a document as an owner's fact.

Reference: [pypdf text extraction and resource limits](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

### Implementation and gate result

Added upload/drop, scoped source listing, part citations/hashes, text comparison,
explicit deletion and 1–365 day retention. Private uploads live only in a bounded
one-hour RAM store. PDF/DOCX/text/image extraction runs in a minimal-environment
child with wall-time limits and supported OS resource limits. PDF rendering uses
a separate-process PDFium instance; embedded active content is not executed.
Apple Vision performs local Italian/English OCR when the native app is connected;
portable installations may install tesseract locally. Missing OCR is an explicit
partial result. Attachments enter agent context as untrusted ToolMessages,
separately from the owner's request.

Gate: 24 document/agent/privacy Python cases passed, native OCR compiled and two
real synthetic OCR scenarios passed, Python lint, TypeScript and all 10 frontend
regressions passed. No personal documents were read. Text comparisons disclose
their bounded coverage and do not establish visual equivalence.

## 6. On-demand screen context — analysis

### Functional requirements

Provide a native macOS one-shot window picker, a local preview and extracted
visible text. The owner chooses the exact window each time; there is no ambient
screen monitoring. Support explicit text/voice requests such as explaining an
error or summarizing the chosen page. Keep captures in scoped, session-bound RAM
for ten minutes, expose source identity/time/OCR confidence and allow immediate
deletion. The dashboard can send a selected capture for analysis with the chosen
model; text remains external evidence. Portable systems can supply a screenshot
through the document upload instead.

### Security and development needs

Use ScreenCaptureKit's system picker restricted to a single window. Never
silently capture all monitors, password dialogs, hidden applications or another
window after selection changes. Selection cancellation, screen lock, privacy
revision changes, emergency stop and timeout discard the result. Raw images stay
out of the database, history and event logs. The native operation rechecks its
authority at claim and completion. Avoid private metadata in generic notices.

Direct model invocation requires an explicit screen-related owner request;
background automation cannot trigger screen capture. Capturing does not provide
mouse/keyboard control or authorize app actions. The user sees OCR limits; text
extraction alone cannot identify every visual element or prove webpage state.
Native UI and provider choices remain independent: OCR is local, subsequent
analysis may use the configured cloud model as in an ordinary conversation.

### Verification gate

Test request-intent checks, scope/private-session ownership, TTL/deletion,
lock/emergency/privacy changes before and after capture, cancellation and native
claim guards, no persisted image bytes, and gateway tainting of returned text.
Compile against the actual macOS SDK and run synthetic OCR tests. System-picker
and Screen Recording consent need a separate deliberate interactive device test.

### Implementation and gate result

Added a single-window ScreenCaptureKit picker, local OCR/preview, bounded
session-scoped capture IDs, immediate deletion and timed ten-minute RAM expiry.
Privacy changes invalidate existing captures. The agent receives bounded OCR
excerpts and can request later portions; image bytes stay outside history/events.
Explicit request-intent checks and background-analysis exclusion protect the
capture tool. Native claims and completions recheck authority.

Gate: 48 screen/document/wake regression cases passed; the actual native screen
module compiled against the installed SDK, TypeScript/lint and all 10 frontend
regressions passed. No real screen was captured during verification. The system
picker and consent remain an interactive device check.

## 7. Jira and GitHub — analysis

### Functional requirements and configuration

Provide scoped connections and explicit allowed Jira projects/GitHub repositories.
Default Jira site/cloudId is https://teamsystem.atlassian.net/ and project BVTL;
Jira searches request ten records. Jira uses the official Rovo MCP server with
dedicated browser OAuth and an explicitly restricted tool policy. Use its current
flat-catalog endpoint so schemas can be verified before every operation. Do not
reuse Codex credentials or collect an Atlassian account password.

GitHub uses a dedicated fine-grained token restricted to selected repositories,
stored privately. Read issues, pull requests, changed files, reviews and CI
evidence tied to the actual PR head revision. Provide connection checks, bounded
pagination, issue detail, stand-up preparation and links between explicit Jira
keys and PR titles/branches. A textual reference is a reference, not proof of a
validated Jira relationship or a completed implementation.

Support reviewable issue creation and comments when the owner enables writes;
all mutations use the gateway's exact arguments and uncertain-effect handling.
Provider workflows, required custom fields, denied scopes and rate limits remain
explicit errors. Stand-up/review preparation does not publish its output.

### Security and development needs

Every target is validated against the current exact scope and allowlist before
discovery/network access. Search filters are constructed from bounded structured
inputs, never interpolated arbitrary JQL that could escape the project boundary.
Verify returned Jira issue project keys. GitHub requests use fixed API origins
and locally constructed paths; returned links cannot redirect credentials.
Provider text/patches/check logs are untrusted and cannot authorize shell commands
or comments. Code review records head SHA, partial pagination and stale-head
warnings; missing checks never mean passing checks.

Managed Jira MCP tools cannot be reached through the generic model MCP escape
path. Local server classification and scope are rechecked after discovery.
Writes default off, use an explicit owner action/approval and retain their effect
ledger. Configuration/disconnect recheck privacy revisions. Strict-local and
emergency states block remote work. Development event sources reuse the same
target authorization. No repository, project or remote deployment is modified
by tests.

### Verification gate

Test scope/allowlist/path/JQL injection, secret redaction, schema/risk validation,
ten-result searches, partial/stale PR evidence, unknown CI states, default-off
writes, duplicate/uncertain effects, and the Jira/GitHub automation adapters.
Check setup, connection, read/review and proposed-action UI flows with fixtures.

References: [Rovo setup](https://developer.atlassian.com/cloud/rovo-mcp/guides/getting-started/),
[Rovo tools](https://developer.atlassian.com/cloud/rovo-mcp/guides/supported-tools/),
[GitHub pull requests](https://docs.github.com/en/rest/pulls/pulls),
[GitHub check runs](https://docs.github.com/en/rest/checks/runs).

### Implementation and gate result

Added dedicated scoped Jira Rovo OAuth configuration and GitHub fine-grained
token configuration, target allowlists, ten-item listings, detail/PR/CI evidence,
stand-up preparation, and approved issue creation/comments. Managed Jira calls
validate discovered schemas, exact scope/site and risk policy; generic MCP calls
cannot bypass those wrappers. GitHub paths use its fixed API origin and PR
evidence is pinned to head SHA with stale/partial/unknown states. Automation
sources reuse these adapters. Disconnect removes local credentials/consent state.

Gate: 37 development/agent/routine/telephony integration cases passed, Python
lint, TypeScript and all 10 frontend regressions passed. No real Jira/GitHub
account was connected, no issue/comment was published, and no PR was changed.

## 8. Home Assistant MCP — analysis

### Functional requirements and setup dependencies

Provide a dedicated connection page for the Home Assistant MCP server, endpoint
and authentication configuration, explicit Connect/discovery, per-tool grants,
schema inspection, read requests, action review/execution and disconnect. Support
state/sensor queries and the scene/light/climate tools actually exposed by the
chosen Home Assistant LLM API. Do not invent tools or assume every installation
has the same API, entities or capabilities.

Home Assistant must already be installed. Enable its Model Context Protocol Server
integration, disable broad exposure of all LLM APIs, select the intended Assist
API and expose only chosen entities. Copy the server URL from Home Assistant.
Its defaults can require an administrator; review that setting and use the
narrowest account/API suitable for the exposed devices. Jarvis does not install
Home Assistant or expose a user's home to the internet.

Use HTTPS or loopback by default. An explicit insecure-LAN option permits only a
literal RFC1918 private IPv4 address, never an arbitrary hostname or link-local/
metadata destination. Explain that such a connection is unencrypted. Support a
dedicated long-lived bearer token and the provider's supported browser OAuth
flow. Home Assistant's client metadata/IndieAuth behavior differs from generic
DCR: client identity and redirect configuration must be handled explicitly.

### Security and development needs

Newly discovered tools are disabled. Only a small known read-only tool set can
receive read grants; every other tool is treated as an action, regardless of
self-reported annotations. Exact arguments must validate against the current
discovered schema and the current connection/tool policy. Control grants are
per scope and revocable; generic MCP calls cannot bypass the adapter. In addition
to Jarvis's tool policy, Home Assistant's entity exposure is the device boundary.

Actions use reviewable argument hashes, short-lived proposals and the existing
effect ledger. Unknown effects cannot be replayed without reconciliation.
Post-action state readback is separate evidence, not automatic proof that a
physical device changed. Configuration and direct action execution recheck
privacy revisions after waits. Strict-local/emergency states, bounded arguments/
results, revoked permissions and provider failures remain authoritative.
OAuth/tokens stay private and endpoint changes invalidate old consent.

### Verification gate

Test TLS/LAN endpoint rules and credential transport, read/action classification,
default-denied tools, schema/scope checks, generic-MCP bypass rejection, changed
policy between proposal and execution, one-use/expired proposals, duplicate and
uncertain effects, private/offline/emergency rejection and sanitized readback.
Exercise the full setup/discovery/permissions/review UI with a synthetic MCP
server. Real device control requires the owner's actual Home Assistant setup.

Reference: [Home Assistant MCP server](https://www.home-assistant.io/integrations/mcp_server/).

### Implementation and gate result

Added dedicated connection/authentication, CA-certificate support, explicit
literal-IP LAN HTTP consent, known-read/action classifications, schema discovery,
revocable per-tool grants, exact five-minute action proposals, state readback and
evidence-based reconciliation. Home Assistant HTTP/OAuth requests and browser
consent are pinned to the configured origin; endpoint changes discard cached
consent. The OAuth client supports same-origin loopback identity and optional
public client metadata. Tokens are private and omitted from API listings.

Unknown/running action receipts block a second identical physical action across
new proposals. Reads and writes are scoped; generic MCP cannot bypass the adapter.
Home state can also be an explicitly configured event source. Home Assistant's
entity exposure remains the device boundary and is explained in the setup page.

Gate: 77 Home Assistant/development/lighting cases passed, followed by 25 focused
integration/automation cases; lint, TypeScript and all 10 frontend regressions
passed. Personal server consent, canonical URLs, account roles and real physical
state changes still require the owner's installed Home Assistant.

## 9. Companion app — delivered after the architecture analysis

The [companion architecture](28-companion-architecture.md) now describes the
implemented remote-first choice: one server authority, Electron macOS/Windows,
Capacitor iOS/Android and a separately paired outbound-WSS desktop executor.
Private/session scope, administrator model/key setup, explicit voice, push,
native sharing, isolated parsing and encrypted restore are implemented.
The local bearer/native endpoints remain unavailable remotely. The delivered
source does not assume real signing accounts, push credentials, a purchased VM or
published store apps. See [implementation and build evidence](32-remote-implementation.md)
and [current verification](33-current-state-and-verification.md).

## Final integration review

Added an actual FastMCP protocol fixture for Home Assistant/Jira discovery, schemas,
calls and readback, plus a confined workspace-document analysis check. Browser QA
runs the real production dashboard against a separate temporary data directory,
synthetic mail/GitHub adapters and a local MCP HTTP server. No personal service or
device is contacted. The fixture covers Today settings, projects/activities,
mail consent/read/reply/draft/exact send, automation preview/save/pause, scoped
views/private controls, document upload/citation/agent handoff, Jira/GitHub setup
and reads, Home Assistant grants/review/execute/readback, and native-unavailable
screen behavior. Native picker/device consent remains a separate real-device check.

The integration review also corrected the configurable imminent-event window up
to 120 minutes, validated provider identities before UI follow-up requests, removed
source free text from calendar-block owner prompts, localized assistant shortcut
requests and separated home acceptance/readback in the UI. New secret-file names
are rejected by the publication inventory. Desktop and 390px layouts were checked
without horizontal page overflow.

Document parsing on macOS is additionally confined with OS-enforced file/network
rules, an empty scratch directory and explicit denial of Jarvis private paths.
An actual subprocess probe verifies denied private/outside reads, outside writes
and loopback networking. Worker timeout/cancellation terminates its process group
(Windows uses a bounded process-tree termination request) and reaps the worker.
Other platforms retain the bounded-process model and do not claim equivalent OS
isolation. Parser-library compromise remains a residual risk; dependencies must
stay patched and platform confinement must be rechecked on deployment targets.

Final local gate on October 30, 2026: **550 Python tests passed, two skipped**;
**10 frontend checks passed**; TypeScript/Vite, Python lint and whitespace checks
passed; **181 native scenarios passed**, including two actual Apple Vision OCR
scenarios. The complete native Mac bundle compiled without diagnostics and was
ad-hoc signed. The source-linked bundle is `dist/Jarvis.app`; it was not launched
against the owner's accounts merely to verify these changes. Vite retains its
non-failing main-chunk size advisory (about 645 KB minified).

The public-file inventory passed and now rejects the mail, development and home
connection files. Its separate synthetic tests cover forced tracking of those
files. Full-account/model quality, Windows/Linux rebuilt executables, native
screen permissions and real provider/device effects are not claimed verified by
this local gate. See [setup and acceptance](29-assistant-setup.md).
