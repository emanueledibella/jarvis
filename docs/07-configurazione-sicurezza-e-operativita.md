# Configuration, authorization, and operations

Updated November 3, 2026. This chapter describes implemented behavior. The complete
setting tables are in [chapter 12](12-configurazione-env.md); the original proposed
env names are superseded by those tables and `Settings` / `ServerOptions`.

## Configuration sources

Precedence is process environment → explicitly selected/source-default `.env` →
private GUI settings → defaults. Environment-controlled values are locked in the
UI. Restart the owning service after changing its environment; hiding a window
does not restart it. `--env-file` / `JARVIS_ENV_FILE` select the main settings file.

Local source installs default to the repository `.env`; portable builds use
their private application data directory. Jarvis does not load the `.env` of a
workspace merely because the agent edits that project.

The GUI returns secret-presence indicators, never saved key values. Blank password
fields retain existing values. Local macOS can resolve Keychain references; copying
such a reference to Linux does not export the key. Re-enter dedicated server
credentials after migrating. Remote settings are encrypted using the core master
key; database permissions and protected backups remain necessary.

## Local and remote startup

| Use | Entry point | Authority |
| --- | --- | --- |
| Native Mac | `open dist/Jarvis.app --args --show` | AppKit supervises the loopback core |
| Portable/browser local | `jarvis desktop` or `jarvis serve` then `jarvis open` | Local process and owner bearer |
| Remote | `jarvis server --bind ... --port ...`, normally Compose behind Caddy | Device-authenticated remote core |
| Executor | Desktop companion setup or `jarvis-executor` | Separate identity, local grants and journal |
| Backup | `jarvis-backup backup` / `restore` | Offline encrypted snapshot/restore |

`JARVIS_API_HOST` remains loopback-only for local mode. Remote mode uses the
separate server command, `JARVIS_REMOTE_PUBLIC_URL` and device boundary.
Do not publish the local owner bearer/native API. See the exact reproducible
commands in [deploy](../deploy/README.md) and [companions](../companions/README.md).

`ServerOptions` reads `JARVIS_REMOTE_*` from the process environment; it does
not automatically read the main `.env`. Compose translates its own `deploy/.env`
variables into the container environment. Remote listener bind/port are CLI options,
not `JARVIS_REMOTE_BIND` / `JARVIS_REMOTE_PORT` settings.

## Models and profiles

Local mode supports `local_strict`, `local_connected`, `cloud` and `hybrid`.
Hybrid selects the configured provider at task start; there is no automatic
mid-task cloud fallback. Strict local blocks remote memory, web, MCP, cloud audio
and telephony, and requires network-disabled confinement for commands. Missing
confinement fails closed on Windows/Linux.

Remote mode forces `cloud`, empty host workspaces, disabled host commands and
disabled native wake/capture. It accepts HTTP MCP, with server-side stdio disabled.
The executor is an explicit tool destination, not another core or inference fallback.

Models need actual tool-calling compatibility checks. Provider/endpoint changes
do not forward an old key to a new destination. Remote administrator saves require
the settings revision (`ETag` / `If-Match`); reload after a 409 conflict.
Task snapshots cannot silently attach replacement credentials to an old endpoint.

## Authorization

The common gateway checks policy, scope, provenance, arguments and effect state
at execution time. Owner requests and explicit grants define authority; mail,
documents, recalled evidence, tool output and model prose cannot create it.

| Capability | Implemented control |
| --- | --- |
| Reads | Enabled capability and exact scope; bounded tools and network destinations |
| Second Brain | Dedicated automatic reads/writes, source/capture checks and separate correction privileges |
| Registered lights | Revocable per-light direct grant; otherwise exact proposal |
| Persistent assistant records | Scope, privacy revision and record revision; private feature edits blocked |
| External/critical effects | Exact action/argument approval where required, expiry and durable receipt |
| Executor work | Core policy plus independently granted local workspace/command/native capabilities |
| Unknown effects | Verify at the original system and reconcile; do not blindly repeat |
| Emergency stop | Block new tasks/tools/audio and interrupt work where possible; completed effects remain |

Source evidence is not promoted into the owner's request. Event-triggered analysis
is read-only even when source text asks for a command or message.
Home Assistant entity exposure, Jira project/GitHub repository allowlists and
mail sending OAuth scopes remain additional provider boundaries.

## Device and network security

Remote pairing codes last ten minutes, access tokens five minutes and rotating
refresh tokens thirty days. The first administrator pairs with a CLI-issued owner
code. Device grants separate companion, administration and executor use.
Revocation invalidates credentials/push and interrupts associated work.
This device protocol is not OIDC; integration OAuth uses supported SDK PKCE flows.

Local HMAC service verification and remote HTTPS/device authentication are
distinct paths. Allowed Host/Origin, CSP, body/time/admission limits and per-device
quotas protect the HTTP boundary. Remote `/api/native*`, local SSE and Live
audio/control endpoints are unavailable. The executor opens WSS outward.

Coding processes do not inherit provider credentials. Workspace I/O checks paths,
symlinks/reparse points, hard links and file revisions. Executor command prefixes
and shell-chain rejection constrain allowed operations, but project code runs with
the OS user's permissions. Trust installed stdio programs in local mode.
Remote document parsing instead runs in a separate no-network container without
core credentials/data. Do not mount the Docker socket or broad host directories.

## Privacy, notifications and recovery

Content scopes are `personal` / `work`; remote privacy/context is per session,
not a global microphone switch across devices. Private messages, checkpoints,
sources and results remain in bounded RAM. Minimal IDs/hashes/outcomes can persist
for deduplication. Private mode cannot prevent an explicitly requested file/effect
from persisting or change provider retention terms.

Audio is not recorded to disk. Ordinary transcripts default to 30-day retention;
operational logs to 30 days. Persistent documents have their own 1–365 day lifetime;
private documents expire after one hour and chosen windows after ten minutes.
Intentional activities/drafts/rules have explicit deletion instead of dialogue TTL.

Push payloads and background desktop notices are generic. Push needs APNs/FCM
credentials and real-device verification; desktop notices need a running app.
Neither notification text nor opening a deep link approves an action.

One process owns each core data directory. Reconcile tasks/effects on restart.
Disconnecting an executor stops its active work; receipt recovery does not replay
uncertain commands. Explicit offline waiting expires within ten minutes.

## Operations and release evidence

Use local `jarvis status`, `doctor`, `tasks`, `mute`, `unmute`, `listen`
and `config validate|show|set` for the local service. They are not a remote login
client. Remote administration uses the paired UI and server CLI/Compose.
There is no implemented `jarvis logs --redacted` or generic `jarvis stop` command.

Stop the authority before copying data or creating an age backup. Preserve the
core master key with the encrypted snapshot, protect the age identity separately,
and back up mounted push credentials and Second Brain separately.
Restore into a new/empty destination; old devices/pairing are revoked, routines
disabled and emergency stop enabled. Review effects before resuming.

Distribution signing/notarization and a signed updater are not delivered by the
source-linked AppKit bundle or unsigned companion builds. Current verification,
dated artifacts and outstanding device/account checks are in
[chapter 33](33-current-state-and-verification.md) and the [security audit](17-security-audit.md).
