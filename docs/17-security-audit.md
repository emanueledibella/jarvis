# Security and publication audit

Audit started October 25, 2026; the dated entries extend through November 3.
The current mode/verification map is in [chapter 33](33-current-state-and-verification.md). This public record deliberately omits original identifiers, private paths,
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
| Local clients could send their token to an impostor occupying the local port | High, local | Fresh HMAC peer verification before CLI/native HTTP/WebSocket use and dashboard load; same-origin requests, no redirects; browser verification before API/SSE requests and no stored browser token |
| Cancelled or duplicated native events could still dispatch an OS action | Medium | Authoritative, one-time native operation claims; expired events filtered while preserving poll cursor progress; current session settings fetched at claim time |
| Ambient provider credentials or organization metadata could reach a custom gateway; restored tasks could use new credentials against an old endpoint | High | Credentials bound to the configured provider/endpoint; explicit SDK destinations; no ambient organization/project headers; fail closed on snapshot endpoint changes |
| Workspace grants could include app credentials, credential stores or hard-linked private files | High | Protected runtime/config paths, expanded credential exclusions, non-following I/O and hard-link rejection on both native file implementations |
| Untrusted reads could influence local mutations or carry private results into arbitrary outbound queries | High | Argument-bound mutation proposals with bounded owner preauthorization; broad grants cannot survive untrusted reads or authorize private query export; execution-time context tracking and exact egress checks across delegated tools, conversation history and resumed tasks; safe fixed-argument weather requests retained |
| Agent task/routine tools could cross personal/work scope boundaries | Medium | Scope filtering and scope-bound updates/deletes/cancellation, including explicitly preauthorized tasks |
| MCP schema validation could read external references or execute an unbounded regex | High | In-memory reference registry, bounded schema/argument trees, deadline/regex limits and sanitized errors; regression includes a local-file reference and a hostile regex |
| Transition IPs, redirects or compressed bodies could bypass intended web-fetch protections | Medium | Address checks at URL and connection resolution, transition-address checks, cross-origin credential stripping, HTTPS downgrade rejection and bounded uncompressed text responses |
| Validation errors could reflect input secrets; slow/large malformed requests could consume resources | Medium | Value-free validation errors, body deadlines/limits, bounded HTTP/WS admission, signature format checks and generic desktop notifications |
| Vulnerable build/install tooling | High advisory, build-only reachability | Python runtime pinned to 3.12.15, Pillow updated to 13.0.0 and pip bootstrap to 26.2.2; universal lock retained; legacy local environment snapshot removed |

No genuine API key/password was found in the scanned Git contents or matching
private configuration comparisons. Personal author/system metadata was present;
it was not dismissed merely because credential scanners reported no secrets.
No actual contact or family data was identified. Fixtures use reserved example
domains and fictional phone numbers. Public GitHub authorship is an accepted
attribution; the owner chose to retain public repository visibility.

## Verification

The regression suite exercises impostor listeners without disclosing credentials,
scope-bound tool actions, credential rebinding rejection, protected files and hard
links, prompt-injection action/egress boundaries, emergency-stop races, schema
file references/regex budgets, private input validation and native action claims.
Native Swift tests exercise the actual client with a fake local listener. Browser
tests exercise the same authentication helper used by the product.

Local verification on the pinned Python runtime passed 110 tests with two
platform-specific skips. All 34 Swift scenarios and three browser authentication
tests passed; TypeScript/Vite, lint, full Mac bundle compilation and ad-hoc
signature verification passed. A fresh clone of the rewritten public repository
passed Gitleaks and exact saved-secret/private-path comparisons with zero matches.
The updated local service authenticated successfully, and saved configuration and
credentials remained byte-for-byte unchanged.

The [security CI](https://github.com/emanueledibella/jarvis/actions/runs/40284754112)
passed the history/inventory, credential scan, Python dependency, Bandit and npm
gates. The [native matrix](https://github.com/emanueledibella/jarvis/actions/runs/40284754035)
passed on all three operating systems: 111 Python tests on Windows with one skip,
110 on Linux/macOS with two skips each, plus browser/frontend checks and 34 Swift
scenarios on macOS. Actual frozen Windows/Linux executables completed an isolated
Deep Agents tool round-trip against a loopback model fixture. Downloaded release
archives passed SHA256, PE/ELF architecture, source/lock/runtime provenance,
private-file inventory and exact saved-secret/private-path comparisons.

The dependency audit after the tool upgrades reports no known advisories in both the audited build environment and the updated production
environment; npm audit reports zero findings. An additional advisory scan covered
all 167 package/version pairs in the universal lock, including platform-specific
and optional voice dependencies, with zero findings and no skipped packages.
The verified downloads are published as [portable preview 3](https://github.com/emanueledibella/jarvis/releases/tag/v0.1.0-portable-preview.3).
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
  GitHub Support controls cached-object removal; no support request or visibility
  change was requested for accepted author attribution. Public repository ownership
  and the public GitHub account remain visible by design; this audit does not change
  the owner's account identity or unrelated repositories.

Low residuals above are deliberate technical trust boundaries, not silently
suppressed high/medium findings. Private incident evidence is kept outside the
published tree. No original private values are reproduced in this report.

## October 27: public telephony ingress review

The review covered the running Cloudflare/Caddy route, loopback listeners,
HTTP and WebSocket authentication, inbound caller identity, media admission,
keypad approvals and installed Python/JavaScript dependencies. Adversarial tests
used isolated databases and synthetic signed carrier messages. No real phone
call, model inference, credential rotation or third-party message was required.

| Confirmed finding | Severity | Remediation |
| --- | --- | --- |
| Disabling the outbound PIN also allowed inbound callers to authenticate using spoofable caller ID alone | High | Incoming calls are now opt-in and always require a PIN. The owner's outbound hands-free preference remains available and unchanged. |
| Rejected or duplicate media starts could finalize another call before validating the one-use media token | Medium | Only the connection that successfully claims a call may release its active state or finalize it. Wrong-token, wrong-account and duplicate-session attempts cannot mutate the victim call. |
| Legacy phone approvals could accept a keypad confirmation before the readback was acknowledged as played | Medium | Bind approval to a unique playback mark. Early digits cannot approve; interrupted audio invalidates the mark. |
| Rejected inbound calls used Hangup, which could still answer and bill the call | Medium | Use Reject as the first verb for disabled, unrecognized, unconfigured, busy or over-budget initial inbound calls. |
| Slow requests and idle or malformed media could consume shared resources or raise unhandled errors | Medium | Reject malformed signature headers before body reads and perform cryptographic checks before voice setup. Limit public pending webhooks to eight, media sockets to two, media setup to five seconds and input audio frames to one second. Enforce proxy body/connection/time limits separately from the private API. |
| Duplicate webhook form/query/signature fields were parsed ambiguously | Low | Reject duplicates before dispatch and validate the carrier account when supplied, including the media start account. |

External checks verified that the dashboard, API, settings, health, documentation,
environment and Git paths are not exposed by the public proxy. Unsigned webhook
requests and unsigned audio upgrades were refused. The Caddy administrator remains
disabled, and backend/proxy listeners remain bound to loopback. The proxy only
forwards POST voice/status webhooks and GET media handshakes; upstream connections
are capped to protect local controls.

Installed Python packages were checked with pip-audit 2.10.1, with the editable
application reviewed as source. npm audit reported no known advisories, and
Bandit 1.9.4 reported no medium/high findings. Scanner tools ran from a separate
temporary environment, without changing application dependencies.

Verification passed 439 Python tests with two platform-specific skips and nine
browser/interface tests. Lint, TypeScript/Vite and Caddy configuration validation
passed. The hardened proxy configuration was applied through its reload signal,
and the supervised backend was restarted with no active calls or tasks. Repeated
live probes confirmed private/encoded routes blocked, unsigned HTTP/audio denied,
ambiguous forms rejected and oversized bodies refused. Signed instance and audio
transport probes succeeded without creating a phone call. The private settings
file was unchanged, including the owner's outbound PIN preference and secrets.

## October 30: assistant feature boundaries

The [assistant expansion record](27-assistant-expansion.md) contains a separate
requirements/security analysis and verification gate for each feature. New mail,
Jira/GitHub and Home Assistant connections use dedicated private credentials,
exact scope/target grants and bounded transport. Mail/home uncertain-effect
receipts block blind retries; review binds current content/arguments and policy.
Home state readback remains separate from command acceptance. Generic MCP cannot
bypass the managed integration adapters.

Documents, source events and chosen-window text remain untrusted evidence rather
than owner testimony. Automatic event analysis is read-only at the gateway,
including after checkpoint reconstruction. Native capture uses a one-window
system picker, guarded claims/completions and a ten-minute RAM lifetime. Private
attachments have session-bound RAM storage and actual expiry timers. Persistent
feature writes recheck privacy revisions, scope and emergency state after waits.

macOS document parsing additionally has OS-enforced file/network confinement and
an empty working directory. An actual subprocess probe verifies rejection of
private/outside reads, outside writes and loopback connections. Separate workers
have timeout, size and supported resource limits; Windows/Linux do not claim the
same OS confinement. Native parser vulnerabilities remain a residual risk.
Publication inventory also rejects all newly introduced credential filenames.

The local final gate passed 550 Python cases (two skips), ten frontend checks and
181 native scenarios, with a compiled/signed Mac bundle. Synthetic browser and
actual MCP protocol fixtures exercised configured flows; no personal mailbox,
organization account or physical device was used as a test target. Real consent,
permissions, device state and signed mobile/platform acceptance remain separate
deployment checks described in [the setup guide](29-assistant-setup.md).

References: [Twilio signatures](https://www.twilio.com/docs/usage/security),
[caller ID spoofing](https://help.twilio.com/articles/46755020494875),
[Reject before answering](https://www.twilio.com/docs/voice/twiml/reject),
[Caddy upstream connection limits](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

These results cover the inspected application and current configuration. They do
not establish the absence of every possible vulnerability or prevent a network
outage or volumetric denial of service. With outbound PIN verification disabled,
whoever answers the owner's configured number can converse with Jarvis; that is
the owner's explicitly requested hands-free policy. Phone conversations retain
the normal tool permission and approval gateway.

## November 3: publication check for the remote core and companions

The source scope now includes the device-authenticated server boundary, distinct
companion/admin/executor grants, rotating refresh/reuse rejection, private
session/object filtering, revision-bound settings and initiating-device OAuth.
The local owner token/native bridge is not published. Executor WSS uses local
grants/hashes/deadlines and receipt reconciliation; prefix checks are not a code
sandbox. Remote parsing is isolated from the core volume/credentials/network.
Encrypted age restore revokes historical device credentials/pairing, disables
routine execution and sets emergency stop. See [the security policy](../SECURITY.md#remote-core-and-companion-boundary)
and [remote implementation](32-remote-implementation.md).

The publication check covers the complete source tree, new companion assets,
deployment examples, and named branch/tag/origin history. Gitleaks 8.30.1 runs
with full redaction. Independent home-path checks and read-only exact comparisons
with sensitive local configuration values complement the scanner's default
exceptions. No credentials or private configuration values were detected in the
publishable files. Environment files, runtime databases, signing credentials,
device configuration, and build outputs remain excluded from publication.
PNG assets contain no identifying ancillary metadata; signing/project files
contain no personal development-team identifier or embedded signing passwords.

Gmail's literal `/users/me` API resource is explicitly allowed as a match,
without exempting the surrounding source file. The iOS icon has a filename that
does not resemble an email address. Independent rule checks still reject private
macOS/Linux home paths and non-example email addresses.

Verification passed 617 Python tests with two platform-specific skips, 14 web
tests, two desktop companion tests, and 181 native scenarios. Python lint and the
TypeScript/Vite production build also passed. These checks do not replace signed
device testing or establish the absence of every possible vulnerability.

The documentation review independently reran the existing Python, web, desktop
bridge and native suites; see [current results](33-current-state-and-verification.md#verification-on-november-3).
It did not repeat live dependency advisories, history rewrite or provider/account
checks. The earlier build audit recorded 16 moderate companion build-toolchain
findings, separately from its runtime dependency result; chapter 32 preserves
that limitation rather than claiming an entirely clean toolchain audit.
