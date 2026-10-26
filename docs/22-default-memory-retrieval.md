# Default Second Brain retrieval

Second Brain is Jarvis's default persistent source for personal and work context. Recent
conversation remains available, and explicit statements or corrections from the current
user take precedence over older stored evidence. No personal memory corpus is included in
the repository or distribution.

## Retrieval behavior

For personal facts missing from the current conversation, Jarvis consults `memory_recall`
before saying it does not know. This includes pet and family names, preferences, identity,
work, history, plans, and decisions. Users can ask an ordinary question without naming
Second Brain. The policy also applies to uncertain personal/project context.

The backend detects common Italian and English personal questions, such as “Come si chiama
il mio cane?” or “Where do I live?”, and performs a lookup before the first model answer.
This early path uses no separate model classifier. Other contextual questions use the same
retrieval policy through the agent's memory tools; the early detector is not a complete
semantic classifier. Routine light commands, time/weather requests, and personal statements
do not trigger that prefetch.

The lookup uses the current conversation scope, at most five results, and the configured
`JARVIS_MEMORY_RECALL_TOKEN_BUDGET` (default 2,000). Its actual tool result is passed as
evidence with a matching tool-call message. It is not promoted into system instructions.
Identical `memory_recall` queries reuse a cache limited to the current task in RAM; a new
task fetches fresh evidence. Successful memory corrections invalidate that cache.

Retrieved source IDs, revisions, quotations, uncertainty, and conflicts stay available to
the agent. Similarity alone does not establish identity. Insufficient evidence can lead to
a more targeted query or a source/entity lookup. Empty, failed, and conflicting retrievals
must be distinguished, and no missing personal fact should be guessed.

## Approvals and boundaries

Authorized reads on the configured `second_brain` MCP service are automatic, including
after prior conversation, workspace reads, or other external content:

`recall`, `find_entities`, `read_source`, `explain`, `memory_status`, `source_status`,
`recovery_jobs`, `history`, `knowledge_schema`, and `reason_memory`.

Saves through `memory_remember` and changes through `memory_change` also run without a
dashboard or spoken confirmation. Corrections, revisions, and retractions require the
configured correction option and the connection's `memory:write` privilege. Saving still
requires source text from the owner's request and the configured capture policy. Private
sessions, explicit opt-out, capture disabled, and strict offline mode block memory writes.

The gateway exception uses the fixed read allowlist and the dedicated write tool/risk
pairs. It does not apply to arbitrary MCP servers/tools. Generic MCP calls still require enabled
tools, valid schemas, the conversation scope where the tool accepts it, the configured
connection, and its OAuth/token privileges. Generic memory writes remain prohibited;
the agent uses the dedicated memory tools automatically to retain source and correction
controls. Writes retain their effect ledger and request IDs: an uncertain outcome must be
reconciled rather than blindly repeated, and a queued source is not yet adopted memory.

Memory evidence marks the task as containing sensitive, untrusted data. It cannot authorize
messages, commands, uploads, or private-data exports through another network service, or
supply invented facts to the save tool. The automatic memory grant does not extend to
other services. Emergency stop and strict offline mode remain authoritative. No new credentials
or relaxed OAuth privileges are needed for this behavior.

`JARVIS_MEMORY_CAPTURE` controls writing, independently of reading. Private sessions and
“do not remember” prevent new memory writes; private retrieval evidence remains in RAM
instead of persistent checkpoints/history. `local_strict` disables remote memory, and an
unconfigured/unavailable service is reported accurately.

## Voice and verification

OpenAI Live receives the same memory policy and delegates personal questions to the backend
before claiming a fact is unknown. The backend performs the same prefetch for delegated
voice requests. Saves and changes are also delegated without asking for confirmation. The
voice session reports the verified result, distinguishes queued sources from adopted
memory, and never invents a dashboard approval requirement for Second Brain.

`tests/test_memory_retrieval.py` uses synthetic data to exercise retrieval before the first
model answer, ongoing text/live conversations, delegated voice, scoped generic MCP reads,
task-local deduplication, unavailable memory, private sessions, and offline behavior.
`tests/test_memory_permissions.py` verifies automatic saves and enabled corrections,
delivery acknowledgement, effect deduplication, uncertain outcomes, and source/privacy/
connection checks. Regression checks also retain private-data export boundaries.
These mocked voice tests verify delegation and evidence flow; they do not replace a spoken
test on the owner's device. Account-specific checks and results belong in ignored local
diagnostics, never in public fixtures or documentation.
