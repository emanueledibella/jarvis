from __future__ import annotations

import re

from .network import public_url

PUBLIC_QUERY_FOCUS = ("hourly", "humidity", "rain", "wind", "snow", "temperature")
PUBLIC_PAGE_TOOLS = frozenset({"read_web_page", "browser_open", "browser_navigate"})
PUBLIC_WEB_TOOLS = PUBLIC_PAGE_TOOLS | {"web_search"}
PUBLIC_LOOKUP_TOOLS = PUBLIC_WEB_TOOLS | {"weather"}


def query_uses_owner_terms(prompt: str, query: str) -> bool:
    """Allow search terms from this request without exporting conversation history."""
    if len(query) > 300 or not re.fullmatch(r"[\w .,'’\-]+", query):
        return False
    terms = set(re.findall(r"\w+", query.casefold()))
    return bool(terms) and terms <= set(re.findall(r"\w+", prompt.casefold()))


def authorized_public_page(prompt: str, url: str, search_pages: set[str]) -> bool:
    try:
        canonical = public_url(url)
    except ValueError:
        return False
    if canonical in search_pages:
        return True
    for literal in re.findall(r"""https?://[^\s<>"'`]+""", prompt, re.IGNORECASE):
        try:
            if public_url(literal) == canonical or public_url(literal.rstrip(".,);!?")) == canonical:
                return True
        except ValueError:
            continue
    return False


def register_public_search_pages(result, pages: set[str], limit: int):
    items = result.get("results") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return
    for item in items[:min(max(1, limit), 10)]:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and len(url) <= 2048:
            try:
                canonical = public_url(url)
            except ValueError:
                continue
            pages.add(canonical)
            item["url"] = canonical


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
saying you cannot answer. Start routine public lookups directly without asking for
permission. When the conversation has private history, form the query using only
words already in the current request; use URLs supplied by the user or returned by
search. If a query is refused for containing other terms, retry with the user's
words. Look up public information before opening private sources for a mixed request.
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
