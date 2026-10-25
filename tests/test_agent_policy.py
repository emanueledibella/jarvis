import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from jarvis.policy import TaskContext, active_task


class ScriptedToolModel(BaseChatModel):
    operation: str = "current_time"
    arguments: dict = {}

    @property
    def _llm_type(self):
        return "contract-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, ToolMessage) and m.name == self.operation for m in messages):
            last = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            message = AIMessage(
                content="Verified outcome: " + str(last.content),
                usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            )
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {"id": "test-tool-call", "name": self.operation, "args": self.arguments}
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


def model_factory(operation="current_time", arguments=None):
    return lambda *args, **kwargs: (
        ScriptedToolModel(operation=operation, arguments=arguments or {}),
        {"kind": "local", "provider": "test", "model": "contract", "base_url": "http://127.0.0.1"},
    )


async def test_responses_stream_accepts_content_blocks_without_streaming_reasoning_or_tool_args(
    runtime,
):
    from jarvis.agent import TokenEvents, visible_text

    handler = TokenEvents(runtime.db, TaskContext("stream-test", "Saluta", "cloud", "personal"))
    await handler.on_llm_new_token(
        [
            {"type": "reasoning", "text": "private-reasoning-must-not-be-shown"},
            {"type": "text", "text": "Ciao"},
            {"type": "tool_call_chunk", "args": "private-tool-argument"},
        ]
    )
    await handler.on_llm_new_token("!")
    await handler.flush()
    event = await runtime.db.fetchone("SELECT data FROM events WHERE type='assistant.delta'")
    assert json.loads(event["data"]) == {"text": "Ciao!"}
    assert (
        visible_text([{"type": "refusal", "refusal": "Richiesta rifiutata."}])
        == "Richiesta rifiutata."
    )
    assert (
        visible_text([{"type": "output_text", "text": "Risultato pubblico."}])
        == "Risultato pubblico."
    )


async def test_actual_deep_agent_executes_a_tool(runtime, monkeypatch):
    from jarvis import agent
    from jarvis.language import language_instructions
    from jarvis.voice_style import SOURCE_POLICY

    captured = []
    create_agent = agent.create_deep_agent

    def capture_agent(**kwargs):
        captured.append(kwargs["system_prompt"])
        return create_agent(**kwargs)

    monkeypatch.setattr(agent, "create_deep_agent", capture_agent)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    task = await runtime.tasks.create("Che ore sono?")
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert "timezone" in row["result"]
    assert language_instructions("auto", "it-IT") in captured[0]
    assert SOURCE_POLICY in captured[0]
    assert await runtime.db.fetchone("SELECT * FROM events WHERE type='tool.completed'")


async def test_approval_interrupt_resume_and_no_duplicate_command(runtime, tmp_path, monkeypatch):
    runtime.config.update({"workspace_roots": [str(tmp_path)]})
    monkeypatch.setattr(
        runtime.tasks,
        "model",
        model_factory("workspace_command", {"command": "printf approved", "cwd": "."}),
    )
    task = await runtime.tasks.create("Esegui il comando")
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "waiting_user", row["error"]
    assert not await runtime.db.fetchall("SELECT * FROM effects")
    approval = await runtime.db.fetchone("SELECT * FROM approvals")
    await runtime.gateway.decide(approval["id"], True)
    await runtime.tasks.resume(task["id"])
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert "approved" in row["result"]
    assert len(await runtime.db.fetchall("SELECT * FROM effects WHERE state='succeeded'")) == 1
    with pytest.raises(ValueError):
        await runtime.gateway.decide(approval["id"], True)


async def test_private_task_leaves_no_content_on_disk(runtime, monkeypatch):
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    secret = "Testo privato unico 789012"
    task = await runtime.tasks.create(secret, private=True)
    await runtime.tasks.running[task["id"]]
    assert not await runtime.db.fetchall("SELECT * FROM messages")
    row = await runtime.db.fetchone("SELECT * FROM tasks")
    assert row["prompt"] == row["result"] == ""
    assert secret not in json.dumps(await runtime.db.fetchall("SELECT * FROM events"))
    assert not await runtime.tasks.checkpointer.aget_tuple(
        {"configurable": {"thread_id": task["id"]}}
    )


async def test_unknown_effect_blocks_retry_until_reconciled(runtime):
    marker = active_task.set(
        TaskContext("test", "request", "local_connected", "personal", external_authorized=True)
    )
    count = 0

    async def network_timeout():
        nonlocal count
        count += 1
        raise TimeoutError()

    try:
        with pytest.raises(TimeoutError):
            await runtime.gateway.invoke("send", {"text": "test"}, "external", network_timeout)
        with pytest.raises(ValueError, match="uncertain"):
            await runtime.gateway.invoke("send", {"text": "test"}, "external", network_timeout)
        assert count == 1
        effect = await runtime.db.fetchone("SELECT * FROM effects")
        await runtime.gateway.reconcile(
            effect["operation_key"], "succeeded", {"provider_id": "verified"}
        )
        result = await runtime.gateway.invoke("send", {"text": "test"}, "external", network_timeout)
        assert result["provider_id"] == "verified" and count == 1
    finally:
        active_task.reset(marker)


async def test_cloud_budget_reserves_before_request_and_accounts_usage(runtime):
    from langchain_core.messages import HumanMessage

    runtime.config.update(
        {
            "monthly_budget_usd": 0.05,
            "model_input_usd_per_million": 100,
            "model_output_usd_per_million": 100,
        }
    )
    with pytest.raises(ValueError, match="budget"):
        await runtime.budget.reserve("rejected", "task", [[HumanMessage(content="hello")]], {})
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")
    runtime.config.update({"monthly_budget_usd": 50})
    rates = await runtime.budget.reserve("accepted", "task", [[HumanMessage(content="hello")]], {})
    await runtime.budget.finish("accepted", {"input_tokens": 20, "output_tokens": 10}, rates)
    assert (await runtime.budget.status())["committed_usd"] == pytest.approx(0.003)


async def test_concurrent_identical_effect_is_claimed_once(runtime):
    import asyncio

    marker = active_task.set(
        TaskContext("same-task", "request", "local_connected", "personal", external_authorized=True)
    )
    executions = 0

    async def execute():
        nonlocal executions
        executions += 1
        await asyncio.sleep(0.02)
        return {"state": "done"}

    try:
        results = await asyncio.gather(
            *(
                runtime.gateway.invoke("send", {"text": "one"}, "external", execute)
                for _ in range(10)
            ),
            return_exceptions=True,
        )
        assert executions == 1
        assert sum(isinstance(r, dict) and r.get("state") == "done" for r in results) >= 1
        cached = await runtime.gateway.invoke("send", {"text": "one"}, "external", execute)
        assert cached == {"state": "done"} and executions == 1
    finally:
        active_task.reset(marker)


async def test_checkpoint_approval_survives_service_restart(config, tmp_path, monkeypatch):
    from jarvis.runtime import Runtime

    config.update({"workspace_roots": [str(tmp_path)]})
    before = Runtime(config)
    await before.start(scheduler=False, process_lock=False)
    monkeypatch.setattr(
        before.tasks,
        "model",
        model_factory("workspace_command", {"command": "printf resumed", "cwd": "."}),
    )
    task = await before.tasks.create("Esegui printf resumed")
    await before.tasks.running[task["id"]]
    approval = await before.db.fetchone("SELECT * FROM approvals")
    assert (await before.db.fetchone("SELECT state FROM tasks"))["state"] == "waiting_user"
    await before.close()
    after = Runtime(config)
    await after.start(scheduler=False, process_lock=False)
    monkeypatch.setattr(
        after.tasks,
        "model",
        model_factory("workspace_command", {"command": "printf resumed", "cwd": "."}),
    )
    try:
        await after.gateway.decide(approval["id"], True)
        await after.tasks.resume(task["id"])
        await after.tasks.running[task["id"]]
        row = await after.db.fetchone("SELECT * FROM tasks")
        assert row["state"] == "succeeded", row["error"]
        assert "resumed" in row["result"]
        assert len(await after.db.fetchall("SELECT * FROM effects WHERE state='succeeded'")) == 1
    finally:
        await after.close()


async def test_submission_retry_reuses_task_and_executes_effect_once(
    runtime, tmp_path, monkeypatch
):
    import asyncio

    from jarvis.db import uid

    runtime.config.update({"workspace_roots": [str(tmp_path)]})
    monkeypatch.setattr(
        runtime.tasks,
        "model",
        model_factory("workspace_command", {"command": "printf once", "cwd": "."}),
    )
    key = uid()
    replies = await asyncio.gather(
        *(
            runtime.tasks.create("Esegui printf once", request_id=key, external_authorized=True)
            for _ in range(5)
        )
    )
    assert {r["id"] for r in replies} == {key}
    if key in runtime.tasks.running:
        await runtime.tasks.running[key]
    assert len(await runtime.db.fetchall("SELECT * FROM tasks")) == 1
    assert len(await runtime.db.fetchall("SELECT * FROM messages WHERE role='user'")) == 1
    assert len(await runtime.db.fetchall("SELECT * FROM effects WHERE state='succeeded'")) == 1
    retry = await runtime.tasks.create(
        "Esegui printf once", request_id=key, external_authorized=True
    )
    assert retry["state"] == "succeeded" and key not in runtime.tasks.running


async def test_submission_id_cannot_be_rebound_to_different_arguments(runtime, monkeypatch):
    from jarvis.db import uid

    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    key = uid()
    await runtime.tasks.create("Prima richiesta", request_id=key)
    with pytest.raises(ValueError, match="different request"):
        await runtime.tasks.create("Richiesta diversa", request_id=key)
    if key in runtime.tasks.running:
        await runtime.tasks.running[key]
    assert len(await runtime.db.fetchall("SELECT * FROM tasks")) == 1
