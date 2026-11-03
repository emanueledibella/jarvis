import json
import time

import httpx2
import pytest
from pydantic import ValidationError

from jarvis.home_assistant import HomeCall, HomeConnection, HomeExecute
from jarvis.network import home_assistant_endpoint
from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools


async def configure(runtime, *, reads=None, writes=None, **kwargs):
    data = HomeConnection(url="https://home.example.test/api/mcp", token="private-home-token", privacy_revision=0,
                          read_tools=reads or [], write_tools=writes or [], **kwargs)
    await runtime.home_assistant.save(data)
    return data


def fake_server(monkeypatch, runtime):
    calls = []
    async def discover(*args, **kwargs):
        policy = runtime.mcp.specs()["jarvis_home_personal"]
        return [{"name": name, "enabled": name in policy["read_tools"] + policy["write_tools"],
                 "risk": "write" if name in policy["write_tools"] else "read",
                 "schema": {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}}
                for name in ["GetLiveContext", "HassGetState", "HassTurnOn", "UnexpectedTool"]]
    async def call(server, tool, arguments, profile, **kwargs):
        calls.append((tool, arguments))
        return {"state": "on", "name": arguments.get("name")}
    monkeypatch.setattr(runtime.mcp, "discover", discover)
    monkeypatch.setattr(runtime.mcp, "call", call)
    return calls


@pytest.mark.parametrize("url", [
    "http://evil.test/api/mcp", "http://homeassistant.local:8123/api/mcp",
    "http://169.254.169.254/api/mcp", "http://8.8.8.8/api/mcp",
    "http://user:password@192.168.1.2:8123/api/mcp",
])
def test_home_lan_exception_never_allows_arbitrary_or_metadata_destinations(url):
    with pytest.raises(ValueError):
        home_assistant_endpoint(url, True)


def test_home_lan_is_explicit_and_only_literal_rfc1918():
    with pytest.raises(ValueError):
        home_assistant_endpoint("http://192.168.1.2:8123/api/mcp")
    assert home_assistant_endpoint("http://192.168.1.2:8123/api/mcp", True).startswith("http://192.")
    assert home_assistant_endpoint("http://127.0.0.1:8123/api/mcp")
    with pytest.raises(ValidationError):
        HomeConnection(privacy_revision=0, url="https://example.test/api/mcp", read_tools=["HassTurnOn"])


async def test_home_tools_default_denied_scoped_redacted_and_generic_bypass_blocked(runtime, monkeypatch):
    await configure(runtime)
    fake_server(monkeypatch, runtime)
    tools = await runtime.home_assistant.tools("personal", "local_connected")
    assert not any(t["enabled"] for t in tools)
    assert next(t for t in tools if t["name"] == "UnexpectedTool")["risk"] == "write"
    assert "private-home-token" not in json.dumps(runtime.home_assistant.configuration("personal"))
    with pytest.raises(PermissionError, match="grant"):
        await runtime.home_assistant.call("personal", "HassTurnOn", {}, "local_connected", write=True)
    with pytest.raises(ValueError, match="scope"):
        runtime.home_assistant.authorize("work", "local_connected")
    ctx = TaskContext("home-bypass", "Read state", "local_connected", "personal")
    marker = active_task.set(ctx)
    try:
        tool = next(t for t in build_tools(runtime) if t.name == "call_mcp_tool")
        assert "dedicated integration" in await tool.ainvoke({"server": "jarvis_home_personal", "tool": "HassTurnOn", "arguments": {}})
    finally:
        active_task.reset(marker)


async def test_home_proposal_is_exact_schema_bound_and_executes_once_with_readback(runtime, monkeypatch):
    await configure(runtime, reads=["GetLiveContext"], writes=["HassTurnOn"])
    calls = fake_server(monkeypatch, runtime)
    proposal = await runtime.home_assistant.propose(HomeCall(privacy_revision=0, tool="HassTurnOn", arguments={"name": "Desk"}))
    execute = HomeExecute(privacy_revision=0, sha256=proposal["sha256"])
    first = await runtime.home_assistant.execute(proposal["id"], execute)
    second = await runtime.home_assistant.execute(proposal["id"], execute)
    assert first["state"] == second["state"] == "accepted"
    assert first["verification"]["state"] == "readback"
    assert [x[0] for x in calls].count("HassTurnOn") == 1
    with pytest.raises(ValueError, match="validation"):
        await runtime.home_assistant.prepare("personal", "HassTurnOn", {"raw_command": "unsafe"}, "local_connected", write=True)
    runtime.home_assistant.proposals[proposal["id"]]["expires"] = time.monotonic() - 1
    with pytest.raises(PermissionError, match="expired"):
        await runtime.home_assistant.execute(proposal["id"], execute)


async def test_home_revoked_permissions_private_and_offline_block_actions(runtime, monkeypatch):
    data = await configure(runtime, writes=["HassTurnOn"])
    calls = fake_server(monkeypatch, runtime)
    proposal = await runtime.home_assistant.propose(HomeCall(privacy_revision=0, tool="HassTurnOn", arguments={}))
    await runtime.home_assistant.save(data.model_copy(update={"write_tools": []}))
    with pytest.raises(PermissionError):
        await runtime.home_assistant.execute(proposal["id"], HomeExecute(privacy_revision=0, sha256=proposal["sha256"]))
    assert not calls
    await runtime.set_voice_session(True, "personal")
    with pytest.raises(PermissionError, match="private"):
        await runtime.home_assistant.propose(HomeCall(privacy_revision=1, tool="HassTurnOn", arguments={}))
    with pytest.raises(PermissionError, match="strict"):
        runtime.home_assistant.authorize("personal", "local_strict")


async def test_uncertain_home_actions_block_new_proposals_until_evidence_reconciliation(runtime, monkeypatch):
    await configure(runtime, writes=["HassTurnOn"])
    fake_server(monkeypatch, runtime)
    count = 0
    async def lost(*args, **kwargs):
        nonlocal count
        count += 1
        raise TimeoutError("Lost after effect")
    monkeypatch.setattr(runtime.mcp, "call", lost)
    request = HomeCall(privacy_revision=0, tool="HassTurnOn", arguments={"name": "Desk"})
    proposal = await runtime.home_assistant.propose(request)
    with pytest.raises(TimeoutError):
        await runtime.home_assistant.execute(proposal["id"], HomeExecute(privacy_revision=0, sha256=proposal["sha256"]))
    second = await runtime.home_assistant.propose(request)
    with pytest.raises(ValueError, match="Reconcile"):
        await runtime.home_assistant.execute(second["id"], HomeExecute(privacy_revision=0, sha256=second["sha256"]))
    assert count == 1
    receipt = (await runtime.home_assistant.history("personal"))[0]
    assert receipt["state"] == "unknown"
    await runtime.home_assistant.reconcile("personal", receipt["id"], "not_executed", "Verified device and logs; effect did not execute")
    assert (await runtime.home_assistant.history("personal"))[0]["state"] == "not_executed"


async def test_home_oauth_uses_explicit_loopback_client_and_transport_pins_origin(runtime):
    await configure(runtime, auth="oauth")
    client = runtime.mcp.client("jarvis_home_personal", "local_connected", interactive=True)
    transport = client.transport
    assert transport.url == "https://home.example.test/api/mcp"
    factory = transport.httpx_client_factory
    async with factory() as http:
        request = httpx2.Request("GET", "https://evil.test/auth/token")
        with pytest.raises(PermissionError, match="origin"):
            await http.event_hooks["request"][-1](request)
        await http.event_hooks["request"][-1](httpx2.Request("GET", "https://home.example.test/api/mcp"))
    policy = runtime.mcp.specs()["jarvis_home_personal"]
    assert policy["oauth_client_id"] == "http://127.0.0.1:8766/"
    assert policy["oauth_callback_port"] == 8766
