import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import ToolException

from jarvis.policy import TaskContext, active_task
from jarvis.tools import build_tools


async def fake_invoke(name, args, risk, execute):
    return await execute()


class DummyRuntime:
    def __init__(self, remote=None):
        self.config = MagicMock()
        self.config.settings.workspace_roots = ["/tmp"]
        self.config.settings.tool_timeout_seconds = 10
        self.config.settings.command_timeout_seconds = 15
        self.config.data_dir = "/tmp/data"
        self.config.env_file = "/tmp/env"
        self.config.settings.mcp_config_path = "/tmp/mcp"
        self.gateway = MagicMock()
        self.gateway.blocked = False
        self.gateway.invoke = AsyncMock(side_effect=fake_invoke)
        self.remote = remote
        self.voice_session = {"scope": "personal", "private": False, "revision": 1}
        self.lighting = MagicMock()
        self.lighting.tool_risk = MagicMock(return_value="read")
        self.lighting.revision = 1


def find_tool(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(f"Tool {name} not found")


async def test_whatsapp_tool_generates_links_and_validates_inputs():
    runtime = DummyRuntime()
    tools = build_tools(runtime)
    whatsapp_tool = find_tool(tools, "whatsapp_send_message")

    ctx = TaskContext("task-wa", "Manda messaggio a Mario", "cloud", "personal")
    token = active_task.set(ctx)

    try:
        # Empty message raises error
        with pytest.raises(ToolException):
            await whatsapp_tool.coroutine(recipient="Mario", message="")

        # Missing recipient and phone raises error
        with pytest.raises(ToolException):
            await whatsapp_tool.coroutine(recipient="", message="Ciao", phone="")

        # Valid Italian number with formatting
        res = await whatsapp_tool.coroutine(
            recipient="Mario Rossi",
            message="Sto arrivando tra 10 minuti",
            phone="+39 333 1234567",
        )
        if isinstance(res, str):
            res = json.loads(res)
        assert res["status"] == "ready"
        assert res["recipient"] == "Mario Rossi"
        assert res["phone"] == "+393331234567"
        assert res["message"] == "Sto arrivando tra 10 minuti"
        assert "whatsapp://send?phone=393331234567&text=Sto%20arrivando%20tra%2010%20minuti" in res["deep_link"]
        assert "https://wa.me/393331234567?text=Sto%20arrivando%20tra%2010%20minuti" in res["web_link"]
        assert "shortcuts://run-shortcut?name=JarvisWhatsApp&input=text&text=" in res["shortcut_link"]
        assert not res["desktop_dispatched"]
    finally:
        active_task.reset(token)


async def test_whatsapp_tool_desktop_dispatch():
    remote = MagicMock()
    remote_jobs = MagicMock()
    remote_jobs.submit = AsyncMock(return_value={"action": "open_url", "success": True})
    remote.jobs = remote_jobs

    runtime = DummyRuntime(remote=remote)
    tools = build_tools(runtime)
    whatsapp_tool = find_tool(tools, "whatsapp_send_message")

    ctx = TaskContext("task-wa-desktop", "Manda whatsapp dal mac", "cloud", "personal")
    token = active_task.set(ctx)

    try:
        res = await whatsapp_tool.coroutine(
            recipient="Elena",
            message="Ci vediamo alle 8",
            phone="3401234567",
            device_id="mac-executor-1",
        )
        if isinstance(res, str):
            res = json.loads(res)
        assert res["status"] == "opened_on_desktop"
        assert res["desktop_dispatched"] is True
        remote_jobs.submit.assert_called_once()
        call_args = remote_jobs.submit.call_args[0]
        assert call_args[0] == "mac-executor-1"
        assert call_args[1] == "window.action"
        assert call_args[2]["action"] == "open_url"
        assert "whatsapp://send?phone=3401234567" in call_args[2]["url"]
    finally:
        active_task.reset(token)


async def test_window_tools_dispatch():
    remote = MagicMock()
    remote_jobs = MagicMock()
    remote_jobs.submit = AsyncMock(return_value={"apps": [{"name": "Finder"}], "windows": []})
    remote.jobs = remote_jobs

    runtime = DummyRuntime(remote=remote)
    tools = build_tools(runtime)

    list_tool = find_tool(tools, "device_windows_list")
    focus_tool = find_tool(tools, "device_window_focus")
    action_tool = find_tool(tools, "device_window_action")

    ctx = TaskContext("task-win", "Controlla finestre", "cloud", "personal")
    token = active_task.set(ctx)

    try:
        # 1. list
        await list_tool.coroutine(device_id="mac-1")
        assert remote_jobs.submit.call_args[0][1] == "window.list"

        # 2. focus
        remote_jobs.submit.reset_mock()
        await focus_tool.coroutine(device_id="mac-1", app_name="Finder", window_id=12)
        assert remote_jobs.submit.call_args[0][1] == "window.action"
        assert remote_jobs.submit.call_args[0][2] == {"action": "focus", "app": "Finder", "window_id": 12}

        # 3. action - invalid action raises ToolException
        with pytest.raises(ToolException):
            await action_tool.coroutine(device_id="mac-1", action="invalid_action")

        # 4. action - valid action
        remote_jobs.submit.reset_mock()
        await action_tool.coroutine(device_id="mac-1", action="hide", app_name="Finder")
        assert remote_jobs.submit.call_args[0][1] == "window.action"
        assert remote_jobs.submit.call_args[0][2] == {"action": "hide", "app": "Finder"}
    finally:
        active_task.reset(token)
