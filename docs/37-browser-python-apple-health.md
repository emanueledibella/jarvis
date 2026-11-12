# Interactive browser, isolated Python and Apple Health

Implemented November 4, 2026. These extensions use the existing local/remote core,
device authentication, personal/work scopes, private sessions and tool gateway.
No model API key, personal health export or account is needed to run the regression tests.

## Setup

Docker must be running on the machine that executes the workers. Build the three
operator-controlled images from this checkout:

```sh
./scripts/build-lab.sh
```

The agent starts workers as part of a task. A local core starts them through
Docker and reports an error when Docker is unavailable. The two capabilities
can be disabled under **Settings → Models** or with
JARVIS_PYTHON_SANDBOX_ENABLED / JARVIS_BROWSER_ENABLED.

For a remote Linux core, build the images on that server and add the optional
Compose overlay:

```sh
docker compose -f deploy/compose.yaml -f deploy/compose.lab.yaml up -d --build
```

Only the dedicated, trusted broker receives the Docker socket. The core receives
a separate Unix socket, not Docker API access. The broker accepts fixed worker
kinds and supplies their images, resource limits and flags; model/user tool
arguments cannot select an image, mount a host folder or inject Docker options.
The broker has Docker-host authority and must remain private to the core.
It exposes no network listener. Its socket is accessible to core UID/GID 10001.
The broker itself runs as UID 10001 with all capabilities dropped. Set
JARVIS_DOCKER_GID in the Compose environment to the Docker socket's numeric group
(`stat -c %g /var/run/docker.sock` on Linux); only the broker joins that group.

For a separately managed broker, export JARVIS_SANDBOX_BROKER_SOCKET in the core
process environment. This host setting is not a dashboard preference. Optional
JARVIS_SANDBOX_PYTHON_IMAGE and JARVIS_SANDBOX_BROWSER_IMAGE are trusted operator
environment overrides on the worker-launching process, not tool parameters.

For a 1 GiB core, apply compose.small.yaml, compose.lab.yaml and then
compose.lab.small.yaml. The broker uses the trusted JARVIS_SANDBOX_PROFILE=small:
one worker at a time, 384 MB RAM without swap, 0.6 CPU and 128 MB temporary storage.
The agent closes its browser before switching to Python. Busy requests
fail immediately with an explanation. Large pages/exports may exceed this budget;
direct iOS sharing only transfers small aggregates and needs no parser worker.
The standard profile retains four broker slots and 768 MB per worker.

The images pin Python 3.12.15, Playwright 1.64.1, NumPy 2.5.4, pandas 3.1.0,
matplotlib 3.11.2 and defusedxml 0.7.1. Rebuild images after worker changes.
Images are never pulled automatically during a model request.
The native Mac app handles artifact downloads with a Save panel, restricted to
main-frame Blob downloads from the verified local dashboard origin. Rebuild it
with ./scripts/build-macos.sh when updating from an older bundle.

## Browser

The agent uses browser_open, browser_navigate, browser_snapshot,
browser_interact and browser_close. Each Chromium session runs on the core's
worker host with its own profile, cookies and page state.

Each session has its own disposable container, cookies, revision and owner
identity. It expires after ten idle minutes; the broker additionally caps the
connection lifetime at fifteen minutes. Sessions close on explicit close,
app shutdown, applicable device revocation/privacy changes or emergency stop.
Agent-created sessions close when the task terminates. Restarts discard cookies.

Chromium has Docker networking disabled. Playwright intercepts HTTP requests and
asks the core to fetch them. The core's actual connection resolver rejects
nonpublic destinations and DNS answers, including loopback, LAN and metadata
services. Redirect requests undergo the same check. Request/response sizes,
concurrency and request counts are bounded. Service workers are disabled;
WebSocket/WebRTC connections cannot bypass the disabled container network.
Nonstandard ports, credential-bearing URLs and non-HTTP navigation are rejected
at the public URL entry point.

Navigation/snapshot requests permit reads; click/fill can submit data. Agent
interactions use the existing argument-bound external-action approval and effect
ledger. They include the last page revision; a DOM fingerprint also rejects a
page changed since inspection. Uncertain actions are not automatically replayed.
Password fields are blocked in the worker.
Automatic popups are closed. There is no arbitrary JavaScript evaluation tool.
The strict-local profile disables the interactive browser.

## Python

Ask Jarvis for the analysis in chat. The agent can use python_execute with
NumPy, pandas and matplotlib. Explicitly selected temporary inputs appear as
plain files in the working directory. Open **Chat → Add attachments → Download
temporary files** to retrieve generated files.

Every invocation starts a fresh unprivileged container, with no host mounts or
network, read-only root, dropped capabilities, no-new-privileges, one CPU,
768 MB memory/swap ceiling, 96 PIDs and bounded temporary storage. The default
code timeout is twenty seconds, configurable per invocation from one to sixty.
Cancellation/timeout removes the actual container, not just its Docker client.
The sandbox never receives core credentials or the Docker socket.

Input/output files are at most 3 MB each, with ten input and ten output files.
Output collection is capped at 8 MB; logs at 16 KB. Temporary artifacts have
opaque IDs, hashes, scope and one-hour expiration. Private files stay in RAM and
require the originating device/session; ordinary files persist in the core
database until expiration/deletion. Files and tool output remain untrusted data.
This capability does not modify the owner’s original workspace files.

## Apple Health

### Direct sharing from the iOS companion

Open **Apple Health** in the iPhone companion, choose categories and 1–90 days,
then select **Read and preview on iPhone**. HealthKit presents Apple's read-only
authorization request for those categories. Jarvis never requests write access.
Daily aggregation happens on the phone; the preview remains in RAM. Only
**Share with Jarvis** sends the displayed daily groups to the authenticated core.
There is no automatic/background upload. Read again to include new records.

The native bridge has no network client and receives no core/model credentials.
It hashes source/device descriptors into source IDs, discards raw samples after
aggregation, unions asleep intervals and preserves heart-rate sample counts and
min/max. Daily periods use the iPhone timezone, including midnight and DST.
Workouts use recorded active duration assigned to their starting day. Phone and
watch/app sources remain separate even if their visible names match.

The preview is discarded on backgrounding, leaving the page, changing session,
scope/privacy, or after fifteen minutes. Backgrounding cancels pending queries.
Limits are 100,000 samples per category, 1,500 daily groups and a 450 KB bridge
payload. An empty read cannot replace existing server summaries. iOS conceals
read-denial status; empty categories indicate unavailable data or limited access,
not confirmed permission denial. Review permissions in Health's app settings.

The main iOS target includes the HealthKit entitlement and
NSHealthShareUsageDescription; the Share extension does not access HealthKit.
For physical builds, the App ID and regenerated provisioning profile must include
HealthKit. Permission selection and real Health data acceptance remain on-device
actions by the owner. See [Apple authorization documentation](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data)
and [HealthKit setup](https://developer.apple.com/documentation/healthkit/setting-up-healthkit).

### Export import on any client

On iPhone, open **Health → profile picture → Export All Health Data**. In
**Chat → Add attachments → Apple Health export**, import the ZIP or its
export.xml and choose the last 1–365 days.
This cross-platform path imports a manually refreshed snapshot. It does not
access an undocumented macOS database.

The raw upload is limited to 64 MB. ZIP XML expansion is limited to 256 MB and
one million records; encrypted/ambiguous archives and XML entities/external
references are rejected. The XML is streamed inside the network-disabled worker.
Raw input is discarded after processing. Only aggregates and provenance are saved.
Large full-history exports may exceed these bounds and require a smaller source.

Supported measurements are steps, heart rate, resting heart rate, active energy,
walking/running distance, asleep minutes and workout minutes. Summaries:

- Preserve source/device separation; steps from iPhone and Watch are not silently added.
- Deduplicate identical records and union overlapping asleep intervals per source.
- Convert record timestamps to the configured timezone, including midnight/DST boundaries.
- Preserve sample counts, units, aggregation methods and heart-rate min/max.
- Treat missing data as unknown and avoid diagnoses.

Import replaces the previous aggregate snapshot. Identical imports are idempotent
for the same date window. Each result has a source ID, revision, export hash and
import timestamp. Reads are limited to 31 days and 200 groups per request.

Health data is personal-scope only. Private sessions may read authorized existing
summaries but cannot import, delete or change persistent settings. Import and
settings changes recheck the current privacy revision. **Cloud model access is
off by default**; the owner must enable it separately in the Health page.
This also gates Live/phone model access. Conversations that have read Health
evidence are marked; switching that conversation to a cloud model checks consent
before any model request. Revoking consent stops active Live sessions.
The backend uses the task’s recorded
model in addition to its profile. Health readings are not automatically adopted
into Second Brain. Remote storage uses the core's encrypted private-feature store.
Disconnect/delete removes the aggregate dataset and revokes cloud consent;
existing conversations keep their normal history-retention policy.

## API and verification

The authenticated `/api/lab` routes cover status and temporary files. Python
execution and browser sessions are available through the agent tool gateway.
`/api/apple-health` covers import, summary, consent and deletion.
Remote calls use the companion's existing device/session grants; changing health
cloud consent additionally requires an administrator device. The upload path is
bounded multipart, with scope/privacy checked before parsing.
POST /api/apple-health/native accepts only typed daily aggregates, selected
categories, a bounded dated window and an expected dataset/privacy revision.
It rejects unknown fields/raw samples, non-finite values, invalid units and
duplicate daily groups. Native data is authenticated evidence, not device
attestation; it receives the same model-consent/history safeguards as XML imports.

Regression commands:

```sh
.venv/bin/pytest -q
npm --prefix web test
npm --prefix web run build
JARVIS_TEST_LAB_DOCKER=1 JARVIS_SANDBOX_PROFILE=small .venv/bin/pytest -q tests/test_lab.py tests/test_apple_health.py tests/test_health_native_remote.py
./scripts/test-native.sh
```

The opt-in suite executes real Docker Python, Chromium and Health parsing, and
checks the broker from a client running as the actual non-root core UID. Other
tests cover scope/device/session isolation, expiry, cancellation, private data,
cloud consent, stale revisions, malformed XML/ZIP, network boundaries and auth.
The disposable UI fixture is tests/fixtures/lab_dashboard.py; it uses synthetic
Health records and a synthetic website, with real workers and no model provider.
Browser UI artifacts are kept in ignored output/playwright.

Source/UI and worker checks remain distinct from physical HealthKit permission
and personal-data acceptance. Worker setup must be performed on each chosen core host.

### Recorded local results

- Dedicated feature suite with real Docker and the small worker profile: **35 passed**, including actual
  Chromium, Python/Health parsing, network-disabled execution and the non-root
  core-to-broker path.
- Native logic: **211 scenarios passed**, including ten Health summary and ten
  Blob download-origin cases. The Health summary fixture also passes validation
  through the actual Python native-upload contract.
- Shared UI: **26 passed**; desktop IPC bridge: **2 passed**; TypeScript/Vite build,
  Python lint, public-file inventory and whitespace checks passed.
- Dashboard QA: website navigation/fill/click, Python result 42, synthetic Health
  XML import and daily value 4321; 1200px desktop and 390px mobile layouts checked.
  Mobile document width remained 390px, without horizontal page overflow.
- Caddy configuration adapted successfully with separate 65 MB Health and 4.1 MB
  ordinary request limits. Health uploads have a two-minute body timeout.
- The full workspace run recorded **679 passed, 5 failed, 6 skipped** while
  separate telephony edits were appearing in the shared workspace. The five
  failures concern PIN/telephony transport tests in test_phone_pin_settings.py
  and test_telephony_security.py; a focused rerun reproduced them. They are not
  reported as a passing full-repository gate.

The earlier full run before those concurrent changes passed 661 tests. Detailed
local logs for this implementation are in /tmp/jarvis-lab-*.log and UI screenshots
in output/playwright. No personal Health export or real model/carrier was used.

### Installed companions and remote core

The existing remote core was updated to jarvis-core:lab-health-20261104 after an
encrypted backup and an idle-work check. Device records, data volumes and parser
were preserved. The broker runs without root/capabilities, with the host Docker
socket's group and the small resource profile. An initial permission failure
triggered rollback; the corrected deployment passed Python (42), real Chromium,
busy-worker admission and HTTPS/authentication probes. Public Health/Lab routes
reject unauthenticated requests. Existing telephony module hashes were unchanged.

The development-signed Mac companion was rebuilt, installed in the user's
Applications folder and reopened. iOS development build 5, with the HealthKit
entitlement in both the signed app and provisioning profile, was installed on the
already paired iPhone. Android debug assemble/lint and iOS simulator builds passed.
IPA, simulator ZIP, APK and Mac DMG/ZIP are in dist/companions. These are development
packages; no TestFlight/App Store publication or Mac notarization was performed.

Synthetic browser UI QA verified the iPhone HealthKit controls, zero uploads after
reading, one upload after explicit sharing, the core summary and a 390px layout
without horizontal page overflow. This bridge simulation does not establish real
HealthKit read consent or personal-data acceptance on the iPhone: the owner must
perform the native permission and sharing steps. Detailed manifests and deployment
evidence are in output/lab-core-update and dist/companions/lab-health-verification-20261104.json.
