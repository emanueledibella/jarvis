import json
import os

import httpx
import pytest
from pydantic import ValidationError

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.mcp_config import Server
from jarvis.network import local_endpoint, secure_endpoint
from jarvis.policy import TaskContext, active_task
from jarvis.scheduler import ScheduleInput
from jarvis.tools import build_tools
from jarvis.workspace import Workspace


def test_provider_credentials_are_bound_to_their_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-provider-fixture")
    assert Settings(_env_file=None).secret("cloud_api_key") == "ambient-provider-fixture"
    for provider in ("openai", "openai_compatible"):
        settings = Settings(
            _env_file=None, cloud_provider=provider, cloud_base_url="https://gateway.example.com/v1"
        )
        assert settings.secret("cloud_api_key") == ""
    assert (
        Settings(_env_file=None, cloud_provider="openai_compatible").secret("cloud_api_key") == ""
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://gateway.example.com/v1",
        "https://user:password@example.com/v1",
        "ftp://example.com/data",
    ],
)
def test_remote_transports_require_tls_and_separate_credentials(url):
    with pytest.raises(ValueError):
        secure_endpoint(url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, second_brain_url=url)
    with pytest.raises(ValidationError):
        Server(url=url, auth="bearer", token="fixture")


def test_localhost_models_never_depend_on_dns():
    assert local_endpoint("http://localhost:11434/v1") == "http://127.0.0.1:11434/v1"
    assert (
        Settings(_env_file=None, local_base_url="http://localhost:11434").local_base_url
        == "http://127.0.0.1:11434"
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::",
    ],
)
def test_web_fetch_cannot_use_transition_addresses_to_reach_private_hosts(address):
    from jarvis.network import public_address

    assert not public_address(address)


async def test_resumed_tasks_never_rebind_current_credentials_to_an_old_gateway(runtime):
    runtime.config.update(
        {
            "cloud_provider": "openai_compatible",
            "cloud_base_url": "https://new.example.com/v1",
            "cloud_model": "fixture",
            "cloud_api_key": "provider-fixture",
        }
    )
    with pytest.raises(PermissionError, match="endpoint changed"):
        runtime.tasks.model(
            "cloud",
            {
                "kind": "cloud",
                "provider": "openai_compatible",
                "model": "fixture",
                "base_url": "https://old.example.com/v1",
            },
        )


def test_workspace_rejects_private_data_and_credential_stores(tmp_path):
    private = tmp_path / "private-runtime"
    private.mkdir()
    (private / "arbitrary.txt").write_text("private-fixture")
    workspace = Workspace([str(tmp_path)], protected=[private])
    with pytest.raises(PermissionError):
        workspace.read("private-runtime/arbitrary.txt")
    for name in [".npmrc", ".netrc", "mcp-servers.json", "auth.json", "credentials.json"]:
        (tmp_path / name).write_text("credential-fixture")
        with pytest.raises(PermissionError):
            workspace.read(name)
        with pytest.raises(PermissionError):
            workspace.write(name, "replacement")


def test_hard_links_cannot_smuggle_secrets_under_a_public_filename(tmp_path):
    private = tmp_path / "private"
    workspace = tmp_path / "workspace"
    private.mkdir()
    workspace.mkdir()
    (private / "secret.txt").write_text("secret-fixture")
    os.link(private / "secret.txt", workspace / "notes.txt")
    with pytest.raises(ValueError):
        Workspace([str(workspace)]).read("notes.txt")


def test_workspace_slots_do_not_require_a_private_absolute_path_in_the_model_prompt(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "notes.txt").write_text("workspace fixture")
    workspace = Workspace([str(first), str(second)])
    assert workspace.read("workspace://2/notes.txt") == "workspace fixture"
    with pytest.raises(PermissionError):
        workspace.read("workspace://2/../../outside.txt")


@pytest.mark.parametrize("preauthorized", [False, True])
async def test_untrusted_research_cannot_silently_write_code_or_create_routines(
    runtime, monkeypatch, preauthorized
):
    proposals, writes = [], []

    async def reject(ctx, name, arguments):
        proposals.append(name)
        return False

    async def fetch():
        return {"text": "untrusted page fixture"}

    async def mutate():
        writes.append("must not run")

    monkeypatch.setattr(runtime.gateway, "approval", reject)
    token = active_task.set(
        TaskContext(
            "injection-test", "Research a topic", "local_connected", "personal",
            external_authorized=preauthorized,
        )
    )
    try:
        await runtime.gateway.invoke(
            "read_web_page", {"url": "https://example.com/"}, "network_read", fetch
        )
        for name, risk in [
            ("workspace_write", "workspace"),
            ("schedule_create", "schedule"),
            ("task_cancel", "task"),
        ]:
            assert (await runtime.gateway.invoke(name, {}, risk, mutate))["state"] == "rejected"
        assert not writes and proposals == ["workspace_write", "schedule_create", "task_cancel"]
    finally:
        active_task.reset(token)


@pytest.mark.parametrize("preauthorized", [False, True])
async def test_web_egress_after_private_reads_needs_an_exact_proposal(
    runtime, monkeypatch, preauthorized
):
    calls, proposals = [], []

    async def read():
        return {"text": "confidential fixture"}

    async def export():
        calls.append("must not send")

    async def reject(ctx, name, arguments):
        proposals.append((name, arguments))
        return False

    monkeypatch.setattr(runtime.gateway, "approval", reject)
    ctx = TaskContext(
        "egress-test", "Read a document", "local_connected", "personal",
        external_authorized=preauthorized,
    )
    token = active_task.set(ctx)
    try:
        await runtime.gateway.invoke("workspace_read", {"path": "notes.txt"}, "read", read)
        result = await runtime.gateway.invoke(
            "read_web_page", {"url": "https://example.com/?data=fixture"}, "network_read", export
        )
        assert result["state"] == "rejected" and not calls
        assert proposals == [("read_web_page", {"url": "https://example.com/?data=fixture"})]
    finally:
        active_task.reset(token)


async def test_emergency_stop_between_approval_and_execution_is_authoritative(runtime, monkeypatch):
    calls = []

    async def approval(*args):
        runtime.gateway.blocked = True
        return True

    async def execute():
        calls.append("must not execute")

    monkeypatch.setattr(runtime.gateway, "approval", approval)
    token = active_task.set(TaskContext("stop-race", "request", "local_connected", "personal"))
    try:
        with pytest.raises(PermissionError, match="Emergency"):
            await runtime.gateway.invoke("send", {}, "external", execute)
        assert not calls and not await runtime.db.fetchall("SELECT * FROM effects")
    finally:
        active_task.reset(token)


async def test_agent_tools_cannot_discover_or_change_another_scope(runtime):
    personal = await runtime.scheduler.create(
        ScheduleInput(
            title="Personal fixture", expression="2030-01-01T12:00:00+00:00", scope="personal"
        )
    )
    work = await runtime.scheduler.create(
        ScheduleInput(title="Work fixture", expression="2030-01-01T12:00:00+00:00", scope="work")
    )
    tools = {t.name: t for t in build_tools(runtime)}
    token = active_task.set(
        TaskContext("scope-test", "request", "local_connected", "work", external_authorized=True)
    )
    try:
        rows = json.loads(await tools["schedules_list"].ainvoke({}))
        assert [r["id"] for r in rows] == [work["id"]]
        result = await tools["schedule_delete"].ainvoke({"schedule_id": personal["id"]})
        assert "not found" in result.lower()
        assert await runtime.db.fetchone("SELECT id FROM schedules WHERE id=?", (personal["id"],))
    finally:
        active_task.reset(token)


async def test_validation_errors_do_not_reflect_sensitive_values(config):
    app = create_app(config, start_scheduler=False, process_lock=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer " + config.token},
        ) as client,
    ):
        marker = "sensitive-input-fixture-never-reflect"
        response = await client.post(
            "/api/chat", json={"text": "hello", "external_authorized": marker}
        )
        assert response.status_code == 422 and marker not in response.text
        response = await client.get("/api/status", headers={b"Authorization": b"Bearer \xff"})
        assert response.status_code == 401


async def test_mcp_schema_cannot_load_a_private_file(tmp_path):
    from jarvis.schemas import validate_arguments

    source = tmp_path / "private-schema.json"
    source.write_text('{"type":"integer"}')
    # The previous default validator reads this file and accepts the integer.
    with pytest.raises(ValueError, match="External references"):
        await validate_arguments({"$ref": source.as_uri()}, 42)


async def test_mcp_patterns_have_a_real_cpu_budget():
    from jarvis.schemas import validate_arguments

    with pytest.raises(ValueError):
        await validate_arguments({"type": "string", "pattern": "^(a+)+$"}, "a" * 2000 + "!")


async def test_self_contained_mcp_schemas_still_support_local_refs():
    from jarvis.schemas import validate_arguments

    await validate_arguments({"$defs": {"value": {"type": "integer"}}, "$ref": "#/$defs/value"}, 42)


async def test_cancelled_native_actions_cannot_be_dispatched_and_live_actions_are_claimed_once(
    runtime,
):
    import asyncio
    import time

    runtime.native.last_seen = time.monotonic()
    pending = asyncio.create_task(
        runtime.native.invoke("calendar.create", {"event": {"title": "fixture"}})
    )
    await asyncio.sleep(0)
    assert runtime.native.pending
    key = next(iter(runtime.native.pending))
    assert runtime.native.claim(key)["operation"] == "calendar.create"
    with pytest.raises(PermissionError, match="already claimed"):
        runtime.native.claim(key)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    with pytest.raises(PermissionError, match="cancelled"):
        runtime.native.claim(key)
    assert not runtime.native.operations and not runtime.native.claimed
