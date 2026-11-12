import asyncio
import base64
import json
import struct
from types import SimpleNamespace

import pytest
from test_agent_policy import model_factory

from jarvis.live_voice import LiveStart, join_prefix
from jarvis.runtime import Runtime


def configure(runtime, **changes):
    runtime.config.update(
        {
            "profile": "cloud",
            "desktop_voice_provider": "openai_live",
            "desktop_voice_api_key": "contract-test-key",
            "desktop_voice_max_session_seconds": 15,
            "desktop_voice_idle_seconds": 5,
            **changes,
        }
    )


def start(runtime, **changes):
    return LiveStart(profile="cloud", privacy_revision=runtime.voice_session["revision"], **changes)


class Peer:
    def __init__(self, runtime=None, *, on_ready=None):
        self.events = []
        self.received_events = asyncio.Queue()
        self.incoming = asyncio.Queue()
        self.on_ready = on_ready
        self.headers = {}
        self.closed_code = None
        self.accepted = False

    async def receive_json(self):
        return await self.incoming.get()

    async def send_json(self, event):
        self.events.append(event)
        await self.received_events.put(event)
        if event["type"] == "ready" and self.on_ready:
            await self.on_ready(self)
        if event["type"] == "task" and event["state"] in {"succeeded", "waiting_user"}:
            await self.incoming.put({"type": "close"})

    async def next_event(self, kind):
        async with asyncio.timeout(2):
            while True:
                event = await self.received_events.get()
                if event["type"] == kind:
                    return event

    async def close(self, code=None):
        self.closed_code = code

    async def accept(self):
        self.accepted = True


class Connection:
    def __init__(self, *, delegate=True):
        self.events = asyncio.Queue()
        self.commentary = []
        self.thinking = []
        self.audio = []
        self.received_audio = asyncio.Queue()
        self.configuration = None
        self.delegated = delegate
        self.session = SimpleNamespace(
            start=self.start,
            close=self.close,
            input_audio=SimpleNamespace(append=self.append_audio),
            commentary=SimpleNamespace(append=self.append_commentary),
            thinking=SimpleNamespace(append=self.append_thinking),
        )

    async def start(self, *, session):
        self.configuration = session
        await self.events.put({"type": "session.started"})
        if self.delegated:
            await self.events.put(
                {
                    "type": "session.input_transcript.delta",
                    "delta": "Che ore sono?",
                    "start_ms": 0,
                    "end_ms": 1000,
                }
            )
            event = {
                "type": "session.delegation.created",
                "offset_ms": 1100,
                "delegation": {"id": "same-delegation", "target": "client"},
            }
            await self.events.put(event)
            await self.events.put(event)

    async def close(self):
        await self.events.put({"type": "session.closed", "usage": {"seconds": 2.0}})

    async def append_audio(self, *, audio):
        self.audio.append(audio)
        await self.received_audio.put(audio)

    async def append_commentary(self, **update):
        self.commentary.append(update)

    async def append_thinking(self, **update):
        self.thinking.append(update)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.events.get()


class Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        pass


def factory(connection):
    def construct(**kwargs):
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        return Context(
            SimpleNamespace(live=SimpleNamespace(connect=lambda **kwargs: Context(connection)))
        )

    return construct


async def test_live_reads_a_completed_answer_with_the_saved_voice_and_no_new_task(runtime):
    configure(runtime, desktop_voice_name="voice_contract_test")
    pcm = base64.b64encode(struct.pack("<h", 1800) * 2400).decode()

    class ReadbackConnection(Connection):
        def __init__(self):
            super().__init__(delegate=False)
            self.readback = []
            self.session.thinking = SimpleNamespace(append=self.append_thinking)
            self.session.instructions = SimpleNamespace(append=self.append_instructions)

        async def append_thinking(self, **update):
            self.readback.append(("thinking", update))

        async def append_instructions(self, **update):
            self.readback.append(("instructions", update))
            await self.events.put({"type": "session.output_audio.delta", "delta": pcm})

    connection, peer = ReadbackConnection(), Peer()
    job = asyncio.create_task(
        runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection))
    )
    try:
        await peer.next_event("ready")
        silence = base64.b64encode(bytes(4800)).decode()
        await peer.incoming.put({"type": "audio", "audio": silence})
        answer = "Sì, domani mattina puoi andare a correre. Non è prevista pioggia."
        await peer.incoming.put({"type": "say", "text": "**" + answer + "**"})
        assert (await peer.next_event("audio"))["audio"] == pcm
        assert connection.configuration["audio"]["output"]["voice"] == {"id": "voice_contract_test"}
        (data_kind, data), (directive_kind, directive) = connection.readback
        assert (data_kind, directive_kind) == ("thinking", "instructions")
        assert json.loads(data["content"]) == {"jarvis_final_answer": answer}
        assert "word for word" in directive["content"]
        assert "Do not turn a statement into a question" in directive["content"]
        assert answer not in directive["content"]
        assert not connection.commentary
        assert connection.audio == [silence]
        assert not any(event["type"] == "task" for event in peer.events)
    finally:
        await peer.incoming.put({"type": "close"})
        await asyncio.wait_for(job, 2)


async def test_live_audio_activity_survives_transcript_gaps_but_silence_times_out(runtime, monkeypatch):
    configure(runtime)
    clock = [0.0]
    monkeypatch.setattr("jarvis.live_voice.time", SimpleNamespace(monotonic=lambda: clock[0]))
    connection, peer = Connection(delegate=False), Peer()
    speech = base64.b64encode(struct.pack("<h", 2000) * 2400).decode()
    job = asyncio.create_task(runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection)))
    try:
        await peer.next_event("ready")
        for second in [0, 4, 8]:
            clock[0] = second
            await peer.incoming.put({"type": "audio", "audio": speech})
            await asyncio.wait_for(connection.received_audio.get(), 2)
        await asyncio.sleep(0.3)
        assert not job.done(), "Ongoing microphone audio must survive an idle-length gap in transcripts"
        clock[0] = 14
        await peer.incoming.put({"type": "audio", "audio": base64.b64encode(bytes(4800)).decode()})
        await asyncio.wait_for(job, 2)
        assert peer.events[-1] == {"type": "closed", "reason": "idle_timeout"}
    finally:
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


async def test_live_idle_waits_for_audio_playback_without_output_transcripts(runtime, monkeypatch):
    configure(runtime)
    clock = [0.0]
    monkeypatch.setattr("jarvis.live_voice.time", SimpleNamespace(monotonic=lambda: clock[0]))
    connection, peer = Connection(delegate=False), Peer()
    job = asyncio.create_task(runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection)))
    try:
        await peer.next_event("ready")
        await connection.events.put({"type": "session.output_audio.delta", "delta": base64.b64encode(struct.pack("<h", 2000) * 24000 * 4).decode()})
        await peer.next_event("audio")
        clock[0] = 8
        await asyncio.sleep(0.3)
        assert not job.done(), "Four seconds of queued playback postpone the five-second idle window"
        clock[0] = 10
        await asyncio.wait_for(job, 2)
        assert peer.events[-1]["reason"] == "idle_timeout"
    finally:
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


async def test_early_delegations_wait_for_the_complete_spoken_request(runtime, monkeypatch):
    configure(runtime)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    clock = [0.0]
    monkeypatch.setattr("jarvis.live_voice.time", SimpleNamespace(monotonic=lambda: clock[0]))
    connection, peer = Connection(delegate=False), Peer()
    job = asyncio.create_task(runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection)))
    try:
        await peer.next_event("ready")
        await connection.events.put({"type": "session.input_transcript.delta", "delta": "Che ore", "start_ms": 0, "end_ms": 500})
        await connection.events.put({"type": "session.delegation.created", "offset_ms": 500, "delegation": {"id": "early", "target": "client"}})
        await peer.next_event("input_text")
        await asyncio.sleep(0.1)
        assert not await runtime.db.fetchall("SELECT * FROM tasks")
        clock[0] = 0.5
        await peer.incoming.put({"type": "audio", "audio": base64.b64encode(struct.pack("<h", 2000) * 2400).decode()})
        await asyncio.wait_for(connection.received_audio.get(), 2)
        await connection.events.put({"type": "session.input_transcript.delta", "delta": " sono a Roma?", "start_ms": 500, "end_ms": 2000})
        await connection.events.put({"type": "session.delegation.created", "offset_ms": 2000, "delegation": {"id": "continuation", "target": "client"}})
        await peer.next_event("input_text")
        await asyncio.sleep(0.1)
        assert not await runtime.db.fetchall("SELECT * FROM tasks")
        clock[0] = 2
        await asyncio.wait_for(job, 3)
        rows = await runtime.db.fetchall("SELECT * FROM tasks")
        assert len(rows) == 1
        assert rows[0]["prompt"] == "Che ore sono a Roma?"
        assert {c["delegation_id"] for c in connection.commentary} == {"early", "continuation"}
    finally:
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


async def test_duration_cap_cancels_an_incomplete_delegation_and_reports_its_reason(runtime, monkeypatch):
    configure(runtime)
    clock = [0.0]
    monkeypatch.setattr("jarvis.live_voice.time", SimpleNamespace(monotonic=lambda: clock[0]))
    connection, peer = Connection(), Peer()
    job = asyncio.create_task(runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection)))
    try:
        await peer.next_event("input_text")
        for half_second in range(1, 30):
            clock[0] = half_second / 2
            await peer.incoming.put({"type": "audio", "audio": base64.b64encode(struct.pack("<h", 2000) * 2400).decode()})
            await asyncio.wait_for(connection.received_audio.get(), 2)
        clock[0] = 15
        await asyncio.wait_for(job, 2)
        assert not await runtime.db.fetchall("SELECT * FROM tasks")
        assert peer.events[-1] == {"type": "closed", "reason": "duration_limit"}
    finally:
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


@pytest.mark.parametrize("voice", ["cedar", "voice_contract_test"])
async def test_live_delegation_uses_deep_agent_once_and_accounts_audio(runtime, monkeypatch, voice):
    configure(
        runtime, desktop_voice_name=voice,
        response_personality={"enabled": True, "irony": 65},
    )
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    connection, peer = Connection(), Peer()
    await asyncio.wait_for(
        runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection)), 5
    )
    tasks = await runtime.db.fetchall("SELECT * FROM tasks")
    assert len(tasks) == 1 and tasks[0]["state"] == "succeeded"
    assert tasks[0]["channel"] == "live"
    assert len(connection.commentary) == 1 and "timezone" in connection.commentary[0]["content"]
    assert connection.configuration["store"] is False
    assert connection.configuration["delegation"] == {"type": "client"}
    from jarvis.language import language_instructions
    from jarvis.retrieval import WEB_FALLBACK_POLICY
    from jarvis.voice_style import SOURCE_POLICY

    assert language_instructions("auto", "it-IT") in connection.configuration["instructions"]
    assert SOURCE_POLICY in connection.configuration["instructions"]
    assert WEB_FALLBACK_POLICY in connection.configuration["instructions"]
    assert "Do not produce any backchannel interjections" in connection.configuration["instructions"]
    assert "Do not answer or delegate a partial request" in connection.configuration["instructions"]
    assert runtime.config.settings.desktop_voice_style in connection.configuration["instructions"]
    assert "Irony 65/100" in connection.configuration["instructions"]
    assert "pacing and emphasis" in connection.configuration["instructions"]
    assert connection.configuration["audio"]["output"]["voice"] == (
        {"id": voice} if voice.startswith("voice_") else voice
    )
    assert not await runtime.db.fetchone("SELECT * FROM events WHERE type='speech.requested'")
    usage = await runtime.db.fetchone("SELECT * FROM model_usage")
    assert usage["state"] == "complete" and usage["actual_usd"] == pytest.approx(2 * 0.05 / 60)
    assert not runtime.live_voice.sessions


@pytest.mark.parametrize(("tool", "request_text", "arguments", "spoken"), [
    ("weather", "Che tempo fa a Torino?", {"location": "Torino"}, "check the weather"),
    ("web_search", "Cerca online gli orari del museo di Torino", {"query": "orari museo Torino"}, "look that up online"),
])
async def test_live_announces_a_lookup_before_its_result_in_an_existing_conversation(
    runtime, monkeypatch, tool, request_text, arguments, spoken,
):
    configure(runtime, end_of_turn_ms=300)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    prior = await runtime.tasks.create("Private conversation history fixture.")
    await runtime.tasks.running[prior["id"]]

    release = asyncio.Event()

    async def lookup(*args, **kwargs):
        await release.wait()
        return {"state": "ready", "evidence": "Lookup completed"}

    monkeypatch.setattr(runtime.productivity, "search" if tool == "web_search" else tool, lookup)
    monkeypatch.setattr(runtime.tasks, "model", model_factory(tool, arguments))

    class LookupConnection(Connection):
        async def append_commentary(self, **update):
            await super().append_commentary(**update)
            if update["content"].startswith("Progress:"):
                await self.events.put({
                    "type": "session.output_audio.delta",
                    "delta": base64.b64encode(struct.pack("<h", 1800) * 480).decode(),
                })

    connection, peer = LookupConnection(delegate=False), Peer()
    job = asyncio.create_task(runtime.live_voice.serve(
        peer, start(runtime, conversation_id=prior["conversation_id"]),
        client_factory=factory(connection),
    ))
    try:
        await peer.next_event("ready")
        await connection.events.put({
            "type": "session.input_transcript.delta", "delta": request_text,
            "start_ms": 0, "end_ms": 1000,
        })
        await connection.events.put({
            "type": "session.delegation.created", "offset_ms": 1000,
            "delegation": {"id": "public-lookup", "target": "client"},
        })
        accepted = await peer.next_event("task")
        await peer.next_event("audio")
        assert await runtime.db.fetchone(
            "SELECT state,result FROM tasks WHERE id=?", (accepted["id"],),
        ) == {"state": "running", "result": ""}
        assert len(connection.commentary) == 1 and spoken in connection.commentary[0]["content"]
        assert not await runtime.db.fetchall("SELECT * FROM approvals")
        release.set()
        await asyncio.wait_for(job, 3)
        assert [item["delegation_id"] for item in connection.commentary] == ["public-lookup"] * 2
        assert "Lookup completed" in connection.commentary[-1]["content"]
    finally:
        release.set()
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)


async def test_live_private_conversation_does_not_persist_transcripts(runtime, monkeypatch):
    configure(runtime)
    await runtime.set_voice_session(True, "personal")
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    await asyncio.wait_for(
        runtime.live_voice.serve(
            Peer(), start(runtime, private=True), client_factory=factory(Connection())
        ),
        5,
    )
    assert not await runtime.db.fetchall("SELECT * FROM messages")
    row = await runtime.db.fetchone("SELECT * FROM tasks")
    assert row["prompt"] == row["result"] == ""


async def test_live_voice_budget_is_reserved_before_provider_connection(runtime):
    configure(runtime, monthly_budget_usd=0.001)

    def forbidden(**kwargs):
        raise AssertionError("No provider request may happen after budget exhaustion")

    with pytest.raises(ValueError, match="budget"):
        await runtime.live_voice.serve(Peer(), start(runtime), client_factory=forbidden)
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_live_rejects_malformed_pcm_without_forwarding_it(runtime):
    configure(runtime)

    async def ready(peer):
        await peer.incoming.put({"type": "audio", "audio": base64.b64encode(b"x").decode()})

    connection = Connection(delegate=False)
    peer = Peer(on_ready=ready)
    with pytest.raises(ValueError, match="complete 16-bit samples"):
        await asyncio.wait_for(
            runtime.live_voice.serve(peer, start(runtime), client_factory=factory(connection)),
            3,
        )
    assert connection.audio == []
    assert not any(event["type"] == "closed" for event in peer.events), (
        "A terminal event must not hide the error that the endpoint still needs to report"
    )
    assert (await runtime.db.fetchone("SELECT state FROM model_usage"))["state"] == "unknown"


async def test_privacy_change_stops_audio_before_the_next_provider_append(runtime):
    configure(runtime)

    async def ready(peer):
        await runtime.set_voice_session(True, "personal")
        await peer.incoming.put({"type": "audio", "audio": base64.b64encode(b"\x00\x00").decode()})

    connection = Connection(delegate=False)
    with pytest.raises(PermissionError):
        await asyncio.wait_for(
            runtime.live_voice.serve(
                Peer(on_ready=ready), start(runtime), client_factory=factory(connection)
            ),
            3,
        )
    assert connection.audio == []


async def test_strict_profile_cannot_start_a_cloud_voice_session(runtime):
    configure(runtime, profile="local_strict")
    with pytest.raises(PermissionError, match="offline"):
        await runtime.live_voice.serve(Peer(), start(runtime))
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_live_websocket_requires_authentication_and_same_origin(runtime):
    for headers in [
        {"host": "127.0.0.1"},
        {
            "host": "127.0.0.1",
            "authorization": "Bearer " + runtime.config.token,
            "origin": "https://example.com",
        },
    ]:
        peer = Peer()
        peer.headers = headers
        await runtime.live_voice.endpoint(peer)
        assert peer.closed_code == 1008 and not peer.accepted


async def test_disabled_voice_cannot_open_or_charge_a_provider_session(runtime):
    configure(runtime, voice_enabled=False)
    with pytest.raises(PermissionError, match="suspended"):
        await runtime.live_voice.serve(Peer(), start(runtime))
    assert not runtime.live_voice.sessions
    assert not await runtime.db.fetchall("SELECT * FROM model_usage")


async def test_default_openai_endpoint_cannot_be_changed_by_an_unrelated_environment(
    runtime, monkeypatch
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/unexpected")
    runtime.config.update(
        {
            "cloud_provider": "openai",
            "cloud_model": "gpt-6.1-sol",
            "cloud_api_key": "contract-test-key",
            "cloud_base_url": "",
        }
    )
    model, _ = runtime.tasks.model("cloud")
    assert model.openai_api_base == "https://api.openai.com/v1"


async def test_existing_second_brain_connection_recovers_without_opening_a_browser(
    config, monkeypatch
):
    config.update({"second_brain_url": "https://example.com/mcp", "second_brain_auth": "oauth"})
    (config.data_dir / "oauth" / "second_brain").mkdir(parents=True)
    runtime = Runtime(config)
    seen = []

    async def discover(name, profile, *, interactive):
        seen.append((name, interactive))
        return []

    monkeypatch.setattr(runtime.mcp, "discover", discover)
    try:
        await runtime.start(scheduler=False, process_lock=False)
        await runtime.connect_jobs["second_brain"]
        assert seen == [("second_brain", False)]
    finally:
        await runtime.close()


async def test_concurrent_voice_sessions_claim_slots_before_waiting_on_the_budget(
    runtime, monkeypatch
):
    configure(runtime)
    release = asyncio.Event()

    async def hold_budget(*args):
        await release.wait()
        raise PermissionError("Test completed before provider connection")

    monkeypatch.setattr(runtime.budget, "reserve_voice", hold_budget)
    first = asyncio.create_task(runtime.live_voice.serve(Peer(), start(runtime)))
    second = asyncio.create_task(runtime.live_voice.serve(Peer(), start(runtime)))
    try:
        await asyncio.sleep(0)
        assert len(runtime.live_voice.sessions) == 2
        with pytest.raises(ValueError, match="already open"):
            await runtime.live_voice.serve(Peer(), start(runtime))
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
    assert not runtime.live_voice.sessions


@pytest.mark.parametrize(("prefix", "transcript", "expected"), [
    ("Che ore", " ore sono?", "Che ore sono?"),
    ("Che", "Che ore sono?", "Che ore sono?"),
    ("Dimmi che ore", "sono?", "Dimmi che ore sono?"),
    ("", "Ciao", "Ciao"),
    ("Che ore sono?", "", "Che ore sono?"),
    ("CHE ORE", "che ore sono?", "CHE ORE sono?"),
])
def test_local_cue_overlap_restores_user_words_without_repeating_them(prefix, transcript, expected):
    assert join_prefix(prefix, transcript) == expected


async def test_live_partial_prefix_is_user_context_and_used_once_for_delegation(runtime, monkeypatch):
    configure(runtime)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    connection = Connection()
    await asyncio.wait_for(runtime.live_voice.serve(
        Peer(), start(runtime, initial_text="Che"), client_factory=factory(connection)
    ), 5)
    history = connection.configuration["input"]
    assert history == [{"role": "user", "status": "incomplete", "content": [{"type": "input_text", "text": "Che"}]}]
    rows = await runtime.db.fetchall("SELECT * FROM tasks")
    assert len(rows) == 1 and rows[0]["prompt"] == "Che ore sono?"
    instructions = connection.configuration["instructions"]
    assert "Do not greet or acknowledge activation" in instructions
    assert "wait silently for a substantive request" in instructions
    assert "briefly invite the user" not in instructions


async def test_private_prefix_is_not_persisted(runtime, monkeypatch):
    configure(runtime)
    await runtime.set_voice_session(True, "personal")
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    await asyncio.wait_for(runtime.live_voice.serve(
        Peer(), start(runtime, private=True, initial_text="Che"), client_factory=factory(Connection())
    ), 5)
    assert not await runtime.db.fetchall("SELECT * FROM messages")
    row = await runtime.db.fetchone("SELECT * FROM tasks")
    assert row["prompt"] == row["result"] == ""


@pytest.mark.parametrize("private", [False, True])
async def test_interrupted_voice_resumes_with_bounded_ram_history_and_no_action_replay(runtime, private):
    configure(runtime)
    if private:
        await runtime.set_voice_session(True, "personal")

    class Speaking(Connection):
        async def start(self, *, session):
            await super().start(session=session)
            await self.events.put({
                "type": "session.input_transcript.delta", "delta": "Tell me a story",
                "start_ms": 0, "end_ms": 1000,
            })
            await self.events.put({"type": "session.output_transcript.delta", "delta": "Once upon a time"})

    class InterruptedPeer(Peer):
        async def send_json(self, event):
            await super().send_json(event)
            if event["type"] == "output_text":
                await self.incoming.put({"type": "close", "handoff": True})

    first = InterruptedPeer()
    await asyncio.wait_for(runtime.live_voice.serve(
        first, start(runtime, private=private), client_factory=factory(Speaking(delegate=False))
    ), 5)
    resume_id = next(event["resume_id"] for event in first.events if event["type"] == "ready")
    assert resume_id in runtime.live_voice.contexts.entries

    async def done(peer):
        await peer.incoming.put({"type": "close"})

    second = Connection(delegate=False)
    await asyncio.wait_for(runtime.live_voice.serve(
        Peer(on_ready=done), start(runtime, private=private, resume_id=resume_id),
        client_factory=factory(second),
    ), 5)
    assert [item["role"] for item in second.configuration["input"]] == ["user", "assistant"]
    assert second.configuration["input"][-1] == {
        "role": "assistant", "status": "incomplete",
        "content": [{"type": "output_text", "text": "Once upon a time"}],
    }
    assert "not proof it was heard" in second.configuration["instructions"]
    assert not await runtime.db.fetchall("SELECT * FROM tasks")
    assert not await runtime.db.fetchall("SELECT * FROM messages")
    assert not runtime.live_voice.contexts.entries
    assert not runtime.live_voice.sessions
    assert len(await runtime.db.fetchall("SELECT * FROM model_usage")) == 2


async def test_normal_voice_close_leaves_no_resumable_history(runtime):
    configure(runtime)

    async def done(peer):
        await peer.incoming.put({"type": "close"})

    await asyncio.wait_for(runtime.live_voice.serve(
        Peer(on_ready=done), start(runtime), client_factory=factory(Connection(delegate=False))
    ), 5)
    assert not runtime.live_voice.contexts.entries


async def test_interruption_preserves_accepted_task_identity_without_resubmitting(runtime, monkeypatch):
    configure(runtime)
    monkeypatch.setattr(runtime.tasks, "model", model_factory())

    class InterruptedTaskPeer(Peer):
        async def send_json(self, event):
            self.events.append(event)
            if event["type"] == "task" and event["state"] == "succeeded":
                await self.incoming.put({"type": "close", "handoff": True})

    first = InterruptedTaskPeer()
    await asyncio.wait_for(runtime.live_voice.serve(
        first, start(runtime), client_factory=factory(Connection())
    ), 5)
    resume_id = next(event["resume_id"] for event in first.events if event["type"] == "ready")
    accepted = await runtime.db.fetchone("SELECT * FROM tasks")
    assert runtime.live_voice.contexts.entries[resume_id].conversation_id == accepted["conversation_id"]

    async def forbidden(*args, **kwargs):
        raise AssertionError("Restoring voice context must not resubmit an accepted action")

    monkeypatch.setattr(runtime.tasks, "create", forbidden)

    async def done(peer):
        await peer.incoming.put({"type": "close"})

    await asyncio.wait_for(runtime.live_voice.serve(
        Peer(on_ready=done), start(runtime, resume_id=resume_id),
        client_factory=factory(Connection(delegate=False)),
    ), 5)
    assert len(await runtime.db.fetchall("SELECT * FROM tasks")) == 1
    assert not runtime.live_voice.contexts.entries
