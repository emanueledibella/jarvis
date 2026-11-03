import json
import sys
from pathlib import Path

from fastmcp import Client

from jarvis.development import DevelopmentConnection
from jarvis.home_assistant import HomeCall, HomeConnection, HomeExecute
from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from assistant_mcp import create_server


async def test_home_assistant_real_mcp_schema_discovery_action_and_state_readback(runtime, monkeypatch):
    server = create_server()
    monkeypatch.setattr(runtime.mcp, "client", lambda *a, **k: Client(server))
    await runtime.home_assistant.save(HomeConnection(privacy_revision=0, url="http://127.0.0.1:8790/mcp", token="synthetic-token",
        read_tools=["GetLiveContext", "HassGetState"], write_tools=["HassTurnOn"]))
    tools = await runtime.home_assistant.tools("personal", "local_connected")
    assert next(item for item in tools if item["name"] == "HassTurnOn")["schema"]["required"] == ["name"]
    proposal = await runtime.home_assistant.propose(HomeCall(privacy_revision=0, tool="HassTurnOn", arguments={"name": "Fixture desk"}))
    result = await runtime.home_assistant.execute(proposal["id"], HomeExecute(privacy_revision=0, sha256=proposal["sha256"]))
    assert result["state"] == "accepted"
    assert result["verification"]["data"]["data"]["entities"][0]["state"] == "on"


async def test_jira_real_mcp_structured_response_and_fixed_cloudid(runtime, monkeypatch):
    server = create_server()
    monkeypatch.setattr(runtime.mcp, "client", lambda *a, **k: Client(server))
    await runtime.set_voice_session(False, "work")
    await runtime.development.save(DevelopmentConnection(scope="work", privacy_revision=1, provider="jira", allowed=["BVTL"]))
    result = await runtime.development.jira_search("work", "BVTL", "local_connected")
    assert result["issues"][0]["key"] == "BVTL-1" and result["limit"] == 10


async def test_readonly_event_analysis_can_read_confined_document_without_importing(runtime, tmp_path):
    folder = tmp_path / "watched"
    folder.mkdir()
    (folder / "new.txt").write_text("Read-only document evidence")
    (folder / ".env").write_text("never read")
    runtime.config.update({"workspace_roots": [str(folder)]})
    ctx = TaskContext("source-event", "Analyze arrived document", "local_connected", "work", automation_run_id="fixture")
    marker = active_task.set(ctx)
    try:
        tool = next(item for item in build_tools(runtime) if item.name == "document_read_workspace")
        result = json.loads(await tool.ainvoke({"path": "new.txt"}))
        assert result["parts"][0]["text"] == "Read-only document evidence"
        assert not await runtime.db.fetchall("SELECT * FROM documents")
        assert "Restricted" in await tool.ainvoke({"path": ".env"})
    finally:
        active_task.reset(marker)
