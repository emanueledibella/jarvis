# Security and publication audit

Audit started October 25, 2026; remediation and verification continued on October
26. This public record deliberately omits original identifiers, private paths,
host inventories, credentials, account state and diagnostic payloads.

## Scope and methods

The review covers reachable Git history and metadata, tracked files and branding,
release packaging, Actions artifacts/logs, Python/JavaScript dependencies, local
HTTP/WebSocket boundaries, the native host, agents/tools, workspaces, public web
fetches, MCP/OAuth integration, schedules, memory and telephony. Tests use isolated
data and synthetic providers; no real OpenAI inference, phone call or memory
mutation is needed.

Gitleaks 8.30.1 ran with full redaction. Exact local credential/path comparisons
complemented pattern scanning. GitHub secret alerts and repository refs/releases
were inspected. pip-audit and npm audit checked dependencies; Bandit findings were
reviewed alongside the code and adversarial regression tests. A scanner result
alone is not treated as proof of the absence of all possible vulnerabilities.

## Confirmed findings and remediation

| Finding | Severity | Resolution |
| --- | --- | --- |
| Identifying author metadata and personal development-machine/account observations in public history | Medium privacy | Neutral Git identity, sanitized public documentation, removal of historical local environment/document/image snapshots, history rewrite and retirement of old release/artifact references |
| Ancillary image metadata and editable-install checkout URLs could disclose build-host details | Low privacy | Strip PNG/ICNS ancillary metadata without changing pixels; exclude `direct_url.json` from frozen packages; enforce private-file packaging checks |
| Native clients could send their token to an impostor occupying the local port | High, local | Fresh HMAC peer verification before native HTTP/WebSocket use and dashboard load; same-origin requests, no redirects; browser verification before API/SSE requests and no stored browser token |
| Cancelled or duplicated native events could still dispatch an OS action | Medium | Authoritative, one-time native operation claims; expired events filtered while preserving poll cursor progress; current session settings fetched at claim time |
| Ambient provider credentials or organization metadata could reach a custom gateway; restored tasks could use new credentials against an old endpoint | High | Credentials bound to the configured provider/endpoint; explicit SDK destinations; no ambient organization/project headers; fail closed on snapshot endpoint changes |
| Workspace grants could include app credentials, credential stores or hard-linked private files | High | Protected runtime/config paths, expanded credential exclusions, non-following I/O and hard-link rejection on both native file implementations |
| Untrusted reads could influence local mutations or carry private results into arbitrary outbound queries | High | Owner proposals for all mutations; execution-time context tracking and exact egress checks across delegated tools, conversation history and resumed tasks; safe fixed-argument weather requests retained |
| Agent task/routine tools could cross personal/work scope boundaries | Medium | Scope filtering and scope-bound updates/deletes/cancellation, including explicitly preauthorized tasks |
| MCP schema validation could read external references or execute an unbounded regex | High | In-memory reference registry, bounded schema/argument trees, deadline/regex limits and sanitized errors; regression includes a local-file reference and a hostile regex |
| Transition IPs, redirects or compressed bodies could bypass intended web-fetch protections | Medium | Address checks at URL and connection resolution, transition-address checks, cross-origin credential stripping, HTTPS downgrade rejection and bounded uncompressed text responses |
| Validation errors could reflect input secrets; slow/large malformed requests could consume resources | Medium | Value-free validation errors, body deadlines/limits, bounded HTTP/WS admission, signature format checks and generic desktop notifications |
| Vulnerable build/install tooling | High advisory, build-only reachability | Python runtime pinned to 3.12.15, Pillow updated to 13.0.0 and pip bootstrap to 26.2.2; universal lock retained; legacy local environment snapshot removed |

No genuine API key/password was found in the scanned Git contents or matching
private configuration comparisons. Personal author/system metadata was present;
it was not dismissed merely because credential scanners reported no secrets.
No actual contact or family data was identified. Fixtures use reserved example
domains and fictional phone numbers.

## Verification

The regression suite exercises impostor listeners without disclosing credentials,
scope-bound tool actions, credential rebinding rejection, protected files and hard
links, prompt-injection action/egress boundaries, emergency-stop races, schema
file references/regex budgets, private input validation and native action claims.
Native Swift tests exercise the actual client with a fake local listener. Browser
tests exercise the same authentication helper used by the product.

Full Python, Swift, browser, frontend compilation, lint and frozen-app smoke checks
must pass for publication. The dependency audit after the tool upgrades reports
no known advisories in the audited environment; npm audit reports zero findings.
Checks are time-specific and need to be rerun for later dependencies/advisories.

## Residual risks and limitations

- **Low — owner-level code authority.** Reviewed host commands and installed MCP
  programs execute as the owner. Stronger isolation would require a separate
  account/container/VM and would limit local coding, calendar and desktop access.
  Strict-local confinement remains unavailable on Windows/Linux and fails closed.
- **Low — local transport race.** Peer verification reduces local port impersonation
  but loopback HTTP is not a mutually authenticated TLS channel. A service crash
  and hostile port rebinding in the verification/request gap remains a narrow
  local race. Same-account malicious software already has access to owner files;
  deployment is intended for a trusted personal OS session.
- **Low — probabilistic model output.** A model can misunderstand facts or propose
  harmful work. It cannot turn page/model prose into an owner approval. Review
  exact proposals and trust configured peers; this is not a formal noninterference
  proof or a sandbox for arbitrary hostile software.
- **Low — platform/provenance coverage.** Portable archives are unsigned previews.
  Checksums and native CI validate the tested artifacts; they do not replace code
  signing, every desktop integration test, or future dependency review.
- **External cleanup boundary.** Rewritten refs and removed assets do not erase
  existing clones, downloads, GitHub cached commit views or hosting backups.
  Cached-object removal requires GitHub Support. Public repository ownership and
  the public GitHub account remain visible by design; this audit does not change
  the owner's account identity or unrelated repositories.

Low residuals above are deliberate technical trust boundaries, not silently
suppressed high/medium findings. Private incident evidence is kept outside the
published tree. No original private values are reproduced in this report.
