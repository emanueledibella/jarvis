import asyncio
import json

import pytest
from test_agent_policy import model_factory

from jarvis.policy import TaskContext, active_task
from jarvis.productivity import duckduckgo_results
from jarvis.tools import build_tools


@pytest.fixture
def public_sources(runtime, monkeypatch):
    searches, pages = [], []

    async def search(query, profile, limit):
        searches.append((query, profile, limit))
        return {"results": [
            {"title": "Forecast source", "url": "https://example.com/forecast#today", "snippet": "Read the dated forecast."},
            {"title": "Second source", "url": "https://example.org/weather", "snippet": "Forecast details."},
            {"title": "Unsafe source", "url": "http://127.0.0.1/private", "snippet": "Must never be fetched."},
        ]}

    async def fetch(url, profile):
        pages.append(url)
        return {"url": url, "title": "Synthetic public forecast", "text": "Synthetic forecast evidence: rain probability is 40 percent."}

    monkeypatch.setattr(runtime.productivity, "search", search)
    monkeypatch.setattr(runtime.productivity, "fetch", fetch)
    return searches, pages


@pytest.mark.parametrize("problem", ["network", "partial", "stale", "empty_values", "out_of_range"])
async def test_missing_public_weather_automatically_searches_and_reads_without_approval(runtime, monkeypatch, public_sources, problem):
    async def weather(*args, **kwargs):
        if problem == "network":
            raise ConnectionError("private provider diagnostics must not escape")
        value = {"state": "ready", "forecast": {"complete": problem != "partial"}, "stale": problem == "stale"}
        if problem == "empty_values":
            value["daily"] = {"weather_code": [None], "temperature_2m_min": [None], "temperature_2m_max": [None]}
        return value

    monkeypatch.setattr(runtime.productivity, "weather", weather)
    ctx = TaskContext("weather-recovery", "Check the forecast in Fixture City", "cloud", "personal", sensitive_context=True)
    ctx.mark_untrusted(routine=True)
    marker = active_task.set(ctx)
    try:
        arguments = {"location": "Fixture City"}
        if problem == "out_of_range":
            arguments.update(start_date="2099-01-01", days=1)
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke(arguments))
        recovery = result["web_recovery"]
        assert recovery["attempted"] and recovery["state"] == "ready"
        assert len(recovery["pages"]) == 2 and "Synthetic forecast evidence" in recovery["pages"][0]["text"]
        assert len(public_sources[0]) == 1 and len(public_sources[1]) == 2
        assert "127.0.0.1" not in " ".join(public_sources[1])
        assert "private provider diagnostics" not in json.dumps(result)
        assert ctx.untrusted_context and not ctx.routine_context_only
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
    finally:
        active_task.reset(marker)


async def test_recovery_stays_within_tool_timeout_and_cancels_the_slow_read(runtime, monkeypatch, public_sources):
    runtime.config.update({"tool_timeout_seconds": 3})
    cancelled = asyncio.Event()

    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    monkeypatch.setattr(runtime.productivity, "weather", slow)
    marker = active_task.set(TaskContext("slow-weather", "Check Fixture City weather", "cloud", "personal"))
    try:
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke({"location": "Fixture City"}))
        assert cancelled.is_set() and result["web_recovery"]["state"] == "ready"
    finally:
        active_task.reset(marker)


async def test_repeated_recovery_reuses_search_and_page_evidence(runtime, monkeypatch, public_sources):
    async def unavailable(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(runtime.productivity, "weather", unavailable)
    marker = active_task.set(TaskContext("recovery-once", "Check Fixture City weather", "cloud", "personal"))
    try:
        tools = {t.name: t for t in build_tools(runtime)}
        first = json.loads(await tools["weather"].ainvoke({"location": "Fixture City"}))
        second = json.loads(await tools["weather"].ainvoke({"location": "Fixture City"}))
        cached = json.loads(await tools["web_search"].ainvoke({"query": first["public_web_query"], "limit": 3}))
        assert first["web_recovery"] == second["web_recovery"] and cached["cached"]
        assert len(public_sources[0]) == 1 and len(public_sources[1]) == 2
    finally:
        active_task.reset(marker)


async def test_successful_weather_does_not_make_unnecessary_web_calls(runtime, monkeypatch, public_sources):
    async def healthy(*args, **kwargs):
        return {"state": "ready", "forecast": {"complete": True}}

    monkeypatch.setattr(runtime.productivity, "weather", healthy)
    marker = active_task.set(TaskContext("healthy-weather", "Check Fixture City weather", "cloud", "personal"))
    try:
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke({"location": "Fixture City"}))
        assert "web_recovery" not in result and public_sources == ([], [])
    finally:
        active_task.reset(marker)


async def test_failure_of_both_sources_is_explicit_and_does_not_leak_provider_errors(runtime, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise TimeoutError("private-error-fixture")

    monkeypatch.setattr(runtime.productivity, "weather", unavailable)
    monkeypatch.setattr(runtime.productivity, "search", unavailable)
    marker = active_task.set(TaskContext("both-unavailable", "Check Fixture City weather", "cloud", "personal"))
    try:
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke({"location": "Fixture City"}))
        assert result["web_recovery"]["attempted"] and result["web_recovery"]["state"] == "unavailable"
        assert not result["web_recovery"]["pages"] and "private-error-fixture" not in json.dumps(result)
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("restriction", ["offline", "stop", "denied", "invalid_place"])
async def test_recovery_cannot_override_access_controls_or_invalid_arguments(runtime, monkeypatch, public_sources, restriction):
    ctx = TaskContext("restricted-recovery", "Read a document", "local_strict" if restriction == "offline" else "cloud", "personal")
    if restriction == "stop":
        runtime.gateway.blocked = True
    if restriction == "denied":
        ctx.sensitive_context = True
        ctx.mark_untrusted()

        async def reject(*args):
            return False

        monkeypatch.setattr(runtime.gateway, "approval", reject)
    marker = active_task.set(ctx)
    try:
        result = await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke({
            "location": "https://example.invalid/?private=fixture" if restriction == "invalid_place" else "Fixture City",
        })
        assert "ready" not in result and not ctx.public_queries and public_sources == ([], [])
    finally:
        active_task.reset(marker)


async def test_public_grants_cannot_export_private_data_or_approve_other_effects(runtime, monkeypatch, public_sources):
    async def unavailable(*args, **kwargs):
        raise TimeoutError

    async def reject(*args):
        return False

    async def forbidden():
        raise AssertionError("A public lookup cannot authorize a different query or action")

    monkeypatch.setattr(runtime.productivity, "weather", unavailable)
    monkeypatch.setattr(runtime.gateway, "approval", reject)
    ctx = TaskContext("bounded-recovery", "Check Fixture City weather", "cloud", "personal", external_authorized=True)
    marker = active_task.set(ctx)
    try:
        await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke({"location": "Fixture City"})
        for name, arguments, risk in [
            ("web_search", {"query": "private document contents", "limit": 3}, "network_read"),
            ("read_web_page", {"url": "https://example.com/forecast?private=fixture"}, "network_read"),
            ("send_message", {}, "external"),
            ("web_search", {"query": next(iter(ctx.public_queries)), "limit": 3}, "external"),
        ]:
            assert (await runtime.gateway.invoke(name, arguments, risk, forbidden))["state"] == "rejected"
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("name", ["memory_recall", "calendar_events", "read_web_page"])
async def test_read_network_errors_leave_agent_running_without_searching_private_facts(runtime, monkeypatch, name):
    async def unavailable(*args, **kwargs):
        raise TimeoutError("private-error-fixture")

    if name == "memory_recall":
        monkeypatch.setattr(runtime.memory, "recall", unavailable)
        arguments = {"query": "Personal fixture preference"}
    else:
        monkeypatch.setattr(runtime.productivity, "calendar" if name == "calendar_events" else "fetch", unavailable)
        arguments = {} if name == "calendar_events" else {"url": "https://example.com"}
    marker = active_task.set(TaskContext("recoverable-read", "Read the fixture", "cloud", "personal"))
    try:
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == name).ainvoke(arguments))
        assert result["state"] == "unavailable" and result["error"] == "TimeoutError"
        assert "private-error-fixture" not in json.dumps(result)
        assert not await runtime.db.fetchall("SELECT * FROM events WHERE type='tool.started' AND data LIKE '%web_search%'")
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("channel", ["text", "live"])
async def test_agent_recovers_weather_before_final_answer_in_ongoing_conversation(runtime, monkeypatch, public_sources, channel):
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    prior = await runtime.tasks.create("Tell me the time", channel=channel)
    await runtime.tasks.running[prior["id"]]

    async def unavailable(*args, **kwargs):
        raise ConnectionError

    monkeypatch.setattr(runtime.productivity, "weather", unavailable)
    monkeypatch.setattr(runtime.tasks, "model", model_factory("weather", {"location": "Fixture City"}))
    task = await runtime.tasks.create("Check the Fixture City forecast", conversation_id=prior["conversation_id"], channel=channel)
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert "Synthetic forecast evidence" in row["result"] and len(public_sources[0]) == 1
    assert not await runtime.db.fetchall("SELECT * FROM approvals")


@pytest.mark.parametrize("risk", ["read", "write"])
async def test_mcp_read_failures_are_recoverable_but_uncertain_mutations_are_not_retried(runtime, monkeypatch, risk):
    calls = []

    async def discover(*args):
        return [{"name": "fixture", "enabled": True, "risk": risk, "schema": {"type": "object"}}]

    async def unavailable(*args):
        calls.append(True)
        raise TimeoutError("private-mcp-diagnostics")

    async def approve(*args):
        return True

    monkeypatch.setattr(runtime.mcp, "discover", discover)
    monkeypatch.setattr(runtime.mcp, "call", unavailable)
    monkeypatch.setattr(runtime.gateway, "approval", approve)
    marker = active_task.set(TaskContext("mcp-recovery", "Use the fixture", "cloud", "personal"))
    try:
        tool = next(t for t in build_tools(runtime) if t.name == "call_mcp_tool")
        arguments = {"server": "fixture", "tool": "fixture", "arguments": {}}
        if risk == "read":
            result = json.loads(await tool.ainvoke(arguments))
            assert result["state"] == "unavailable" and "private-mcp-diagnostics" not in json.dumps(result)
        else:
            with pytest.raises(TimeoutError):
                await tool.ainvoke(arguments)
            assert "uncertain" in await tool.ainvoke(arguments)
            assert (await runtime.db.fetchone("SELECT state FROM effects"))["state"] == "unknown"
        assert len(calls) == 1
    finally:
        active_task.reset(marker)


async def test_a_missing_weather_detail_can_use_a_focused_public_query_without_exporting_more(runtime, monkeypatch, public_sources):
    async def healthy(*args, **kwargs):
        return {"state": "ready", "forecast": {"complete": True}}

    monkeypatch.setattr(runtime.productivity, "weather", healthy)
    ctx = TaskContext("humidity-query", "What is the humidity in Fixture City?", "cloud", "personal", sensitive_context=True)
    ctx.mark_untrusted(routine=True)
    marker = active_task.set(ctx)
    try:
        tools = {t.name: t for t in build_tools(runtime)}
        primary = json.loads(await tools["weather"].ainvoke({"location": "Fixture City"}))
        query = primary["public_web_query"]
        assert "web_recovery" not in primary
        assert json.loads(await tools["web_search"].ainvoke({"query": query + " humidity"}))["results"]
        assert json.loads(await tools["web_search"].ainvoke({"query": query + " hourly"}))["results"]
        exhausted = json.loads(await tools["web_search"].ainvoke({"query": query + " rain"}))
        assert exhausted["state"] == "unavailable" and len(public_sources[0]) == 2
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
    finally:
        active_task.reset(marker)


async def test_coordinates_only_weather_does_not_export_private_coordinates_to_web_search(runtime, monkeypatch, public_sources):
    runtime.config.update({"weather_location": "", "weather_latitude": 12.3456, "weather_longitude": 34.5678})

    async def unavailable(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(runtime.productivity, "weather", unavailable)
    marker = active_task.set(TaskContext("coordinates-private", "Check the weather", "cloud", "personal"))
    try:
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == "weather").ainvoke({}))
        assert result["state"] == "unavailable" and result["public_web_query"] is None
        assert public_sources == ([], [])
    finally:
        active_task.reset(marker)


@pytest.mark.parametrize("html", [
    b'<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fforecast">Forecast</a><div class="result__snippet">Dated evidence.</div></div>',
    b'<table><tr><td><a class="result-link" href="https://example.com/forecast">Forecast</a></td></tr><tr><td class="result-snippet">Dated evidence.</td></tr></table>',
])
def test_search_parser_supports_html_and_lite_with_the_actual_target_url(html):
    assert duckduckgo_results(html, 3) == [{"title": "Forecast", "url": "https://example.com/forecast", "snippet": "Dated evidence."}]


async def test_empty_keyless_html_entry_point_uses_lite_once(runtime, monkeypatch):
    runtime.config.update({"search_provider": "duckduckgo"})
    calls = []

    async def fetch(url, **kwargs):
        calls.append(url)
        raw = b'<html>No usable search results.</html>' if len(calls) == 1 else b'<table><tr><td><a class="result-link" href="https://example.com/forecast">Forecast</a></td></tr></table>'
        return url, raw, "text/html"

    monkeypatch.setattr("jarvis.productivity.fetch_public", fetch)
    result = await runtime.productivity.search("public fixture forecast", "cloud", 3)
    assert result["results"][0]["url"] == "https://example.com/forecast"
    assert len(calls) == 2 and "lite.duckduckgo.com" in calls[1]


async def test_mcp_discovery_failure_is_reported_before_any_effect_starts(runtime, monkeypatch):
    async def unavailable(*args):
        raise TimeoutError("private connection diagnostics")

    async def forbidden(*args):
        raise AssertionError("Discovery failed; no MCP operation may have started")

    monkeypatch.setattr(runtime.mcp, "discover", unavailable)
    monkeypatch.setattr(runtime.mcp, "call", forbidden)
    marker = active_task.set(TaskContext("mcp-discovery", "Use the fixture", "cloud", "personal"))
    try:
        result = json.loads(await next(t for t in build_tools(runtime) if t.name == "call_mcp_tool").ainvoke({
            "server": "fixture", "tool": "fixture", "arguments": {},
        }))
        assert result["state"] == "unavailable" and not result["effect_executed"]
        assert "private connection diagnostics" not in json.dumps(result)
        assert not await runtime.db.fetchall("SELECT * FROM effects")
    finally:
        active_task.reset(marker)
