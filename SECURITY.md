# Security policy

Only the latest security preview is supported. Do not use older portable archives.
Report vulnerabilities with GitHub's private vulnerability reporting for this
repository. Do not post credentials, personal documents, or exploit payloads in a
public issue.

## Trust boundaries

Jarvis is a single-owner application. The OS account, selected model provider,
installed MCP programs and configured MCP endpoints must be trusted. A process
running as the owner, an administrator, or compromised system software can access
the owner's files. File permissions do not sandbox that authority.

- HTTP binds to loopback. API requests require an owner token; host/origin checks,
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
- Untrusted documents/tool results cannot authorize mutations. File, routine, task-control and memory mutations, and outbound queries following
  private reads, require an argument-bound proposal unless the owner explicitly preauthorized the task.
- Remote credential endpoints require HTTPS. Localhost model URLs are pinned to
  a loopback IP. Provider keys are not implicitly reused for a custom gateway,
  and paused tasks cannot bind new credentials to an old endpoint.
- MCP schemas cannot retrieve files/URLs. Validation has size/depth/time limits
  and bounded regex matching. `patternProperties` and `unevaluatedProperties`
  require a simpler self-contained schema; they are intentionally unsupported.
- Strict-local mode does not silently fall back to an unconstrained host command.
  Approved host commands and installed stdio MCP programs have the owner's OS
  authority; review and trust them before execution.

Private mode controls local retention, not the selected provider's processing
terms or OS swap/backups. Cloud models receive the conversation/tool data needed
for their work. Do not supply secrets in a prompt or authorize their export.

## Publishing controls

Use a neutral local Git identity, a reserved example domain for fixtures, and
placeholder home paths. Never publish local configuration, environment snapshots,
OAuth caches, logs, memory databases, screenshots of personal data, or private
diagnostic reports. Install the pre-push guard with:

```sh
git config --local core.hooksPath .githooks
# Install Gitleaks 8.30.1, or configure jarvis.secretScanner to its absolute path.
```

CI scans reachable history, Git identities, dependencies and medium/high static
findings. It does not print secret matches or upload secret-scan reports. Release
builders remove editable-install URLs and image ancillary metadata. Portable
previews have checksums but are not publisher-signed installers.

See the [security audit](docs/17-security-audit.md) for verification and residual
limitations. Rewriting Git refs cannot delete third-party clones or GitHub cached
objects; a hosting-provider purge is a separate operation.
