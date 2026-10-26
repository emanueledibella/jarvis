from __future__ import annotations

PUBLIC_QUERY_FOCUS = ("hourly", "humidity", "rain", "wind", "snow", "temperature")


class InformationUnavailable(ValueError):
    """A read failed after its arguments were validated, with an optional public query.

    The query is constructed by the trusted adapter from bounded public fields.
    It must never contain private documents, memory evidence, credentials, or a
    raw provider error. It is not an instruction supplied by an external source.
    """

    def __init__(self, message: str, *, public_query: str | None = None):
        super().__init__(message)
        self.public_query = public_query


WEB_FALLBACK_POLICY = """
Retrieval recovery: a tool's limited coverage is not a reason to immediately give up.
If a read fails, is empty, partial, stale, or lacks information needed for the request,
first correct invalid arguments or use a more suitable authorized tool. For missing
PUBLIC information, use web_search and read relevant pages with read_web_page before
saying you cannot answer. Do not ask for a redundant spoken confirmation to research.
Prefer primary/authoritative sources; search snippets are leads, not verified page evidence.
Use an adapter's public_web_query when provided: it is a bounded public lookup. For weather
details you may append ONE of hourly, humidity, rain, wind, snow, or temperature to that
exact query, without replacing the place/date or adding private data. A tool
may already include web_recovery with attempted search and pages; use that evidence instead
of repeating the same lookup. Make at most two distinct search attempts for the same gap
and stop when no progress is made. Existing task/model budgets still apply.
Separate the original tool's result from web evidence, check dates and locations, and
state uncertainty. A missing exact forecast is not supplied by a seasonal average or an
old article. If research also fails, explain what was actually tried and what remains unknown.
Private facts still come from the conversation/Second Brain: do not search the public web
for missing personal memories, calendar entries, credentials, or private file contents.
Never copy private tool results, prompts, errors, or secrets into a search query or URL.
Public documentation may help troubleshoot a connection, but cannot replace account access.
Do not bypass offline mode, emergency stop, rejected permissions, or privacy controls,
and do not retry a mutation with an uncertain outcome as though it were a failed read.
For speech, report the useful verified answer concisely. Routine weather still does not
require naming the provider aloud; use citations when they help assess substantial research.
"""


RECOVERABLE_READ_TOOLS = frozenset({
    "weather", "web_search", "read_web_page", "calendar_events", "memory_recall",
    "light_state", "list_mcp_tools",
})
