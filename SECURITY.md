# Security policy

Only the latest security preview is supported. Do not use older portable archives.
The published October portable preview predates the expanded assistant and remote
companion implementation; unsigned development packages have separate evidence in
the [current verification record](docs/33-current-state-and-verification.md).
Report vulnerabilities with GitHub's private vulnerability reporting for this
repository. Do not post credentials, personal documents, or exploit payloads in a
public issue.

## Trust boundaries

Jarvis is a single-owner application. The OS account, selected model provider,
installed MCP programs and configured MCP endpoints must be trusted. A process
running as the owner, an administrator, or compromised system software can access
the owner's files. File permissions do not sandbox that authority.

- Local HTTP binds to loopback. API requests require an owner token; host/origin checks,
  CSP, request limits and server admission limits protect the local boundary.
- Launchers and browser/native clients verify a fresh HMAC challenge before
  disclosing the API token. Browser tokens stay in page memory. Refresh by
  reopening Jarvis; they are deliberately not restored from browser storage.
- A native action must claim its still-active operation exactly once before OS
  execution. Cancellation invalidates queued operations. An already-dispatched
  external action cannot be undone by emergency stop.
- Files are restricted to explicit workspaces. App data, credential stores,
  symlinks/reparse escapes and hard-link aliases are excluded. Model prompts use
  numbered workspace slots rather than automatically including home paths.
- Untrusted documents/tool results cannot authorize mutations. File, routine and
  task-control effects use argument-bound proposals where required. Dedicated
  Second Brain reads/writes retain their automatic policy, source and
  correction-privilege checks; registered lights can have narrow direct grants.
  An owner
  can preauthorize direct actions, but that broad grant stops applying after an
  untrusted read and cannot authorize outbound queries containing private context.
- Remote credential endpoints require HTTPS. Localhost model URLs are pinned to
  a loopback IP. Provider keys are not implicitly reused for a custom gateway,
  and paused tasks cannot bind new credentials to an old endpoint.
- MCP schemas cannot retrieve files/URLs. Validation has size/depth/time limits
  and bounded regex matching. `patternProperties` and `unevaluatedProperties`
  require a simpler self-contained schema; they are intentionally unsupported.
- Strict-local mode does not silently fall back to an unconstrained host command.
  Approved host commands and installed stdio MCP programs have the owner's OS
  authority; review and trust them before execution.

## Remote core and companion boundary

Remote mode uses `jarvis server` and dedicated device authentication, not a public
local owner token. Pairing codes are one-use/ten-minute, access tokens five-minute,
and refresh tokens rotate with reuse-family revocation. Companion/admin/executor
grants are distinct. Host/Origin, request/time/admission limits and HTTPS apply;
loopback HTTP requires explicit development configuration. Local native/Live and
SSE endpoints remain unavailable through the remote boundary.

The server checks exact scope/session ownership of tasks, sources and approvals.
JSON authority checks also cover requests without a Content-Type, structured
JSON media types and mixed-case media types accepted by FastAPI; changing that
header cannot bypass scope, profile or attachment-session checks.
Private content remains in bounded RAM, with minimal IDs/hashes/outcomes retained
for deduplication. Administrator settings require a current `ETag` / `If-Match`.
New destinations require dedicated credentials; integration OAuth is bound to the
initiating administrator device and public callback. Device pairing is not OIDC.

Model keys, private integration/OAuth stores and push tokens are encrypted with
the core master key. Ordinary conversations/checkpoints remain in private databases.
This is not end-to-end encryption against the server administrator. A companion
stores its own credential in the OS vault; model keys are not bundled into apps.

Executors connect outward over WSS and independently check local workspace,
command/native grants, hashes and deadlines. Commands run with the OS user's
authority; allowed prefixes do not sandbox project code. Receipt recovery never
authorizes replay of an uncertain effect. Native Hue Bluetooth and general GUI
control are not remote executor capabilities.

Stock remote mode disables host workspaces/commands and stdio MCP. Its document
parser runs in a separate no-network container without the core's private volume
or credentials. Push carries generic updates, never action authority.
Age restore revokes old device credentials and pairing, disables routines, enables
emergency stop and marks pending dispatch uncertain before resuming operation.

Private mode controls local retention, not the selected provider's processing
terms or OS swap/backups. Cloud models receive the conversation/tool data needed
for their work. Do not supply secrets in a prompt or authorize their export.

## Publishing controls

Use a neutral Git identity or public GitHub noreply attribution, reserved example
domains for fixtures, and placeholder home paths. Never publish local configuration, environment snapshots,
OAuth caches, logs, memory databases, screenshots of personal data, or private
diagnostic reports. Install the pre-push guard with:

```sh
git config --local core.hooksPath .githooks
# Install Gitleaks 8.30.1, or configure jarvis.secretScanner to its absolute path.
```

The pre-push hook accepts audited named branches/tags and rejects internal refs,
including app-managed snapshots; do not mirror private workspace refs.

CI scans reachable history, Git identities, dependencies and medium/high static
findings. It does not print secret matches or upload secret-scan reports. Release
builders remove editable-install URLs and image ancillary metadata. Portable
previews have checksums but are not publisher-signed installers.

See the [security audit](docs/17-security-audit.md) for verification and residual
limitations. Rewriting Git refs cannot delete third-party clones or GitHub cached
objects; a hosting-provider purge is a separate operation.
