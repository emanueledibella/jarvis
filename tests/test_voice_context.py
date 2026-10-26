import asyncio

import pytest

from jarvis.live_voice import LiveStart
from jarvis.voice_context import VoiceContextStore


def metadata(**changes):
    return LiveStart.model_validate({"profile": "cloud", "privacy_revision": 0, **changes})


async def test_handoff_is_single_use_and_copies_incomplete_assistant_history():
    store = VoiceContextStore()
    stop = asyncio.Event()
    key, old = store.create(metadata(), stop)
    old.append("user", "Tell me a story")
    old.append("assistant", "Once upon a time")
    old.conversation_id = "fixture-conversation"
    previous = store.resume(key, metadata())
    assert stop.is_set()
    with pytest.raises(ValueError, match="expired"):
        store.resume(key, metadata())
    new_key, new = store.create(metadata(), asyncio.Event(), previous)
    assert new.history[-1]["status"] == "incomplete"
    assert old.history[-1]["status"] == "completed"
    assert new.conversation_id == "fixture-conversation"
    new.append("user", "Make it shorter")
    assert len(old.history) == 2
    assert new_key != key
    store.clear()


@pytest.mark.parametrize("changes", [
    {"private": True}, {"scope": "work"}, {"profile": "hybrid"}, {"privacy_revision": 1},
])
async def test_handoff_cannot_cross_privacy_scope_profile_or_revision(changes):
    store = VoiceContextStore()
    key, context = store.create(metadata(), asyncio.Event())
    context.append("user", "Private fixture text")
    with pytest.raises(PermissionError, match="boundary"):
        store.resume(key, metadata(**changes))
    assert not context.stop.is_set()
    store.clear()


async def test_closed_handoff_expires_and_releases_ram_without_another_request():
    store = VoiceContextStore(ttl=0.01)
    key, context = store.create(metadata(private=True), asyncio.Event())
    context.append("user", "Private fixture text")
    store.close(key, context)
    await asyncio.sleep(0.04)
    assert not store.entries and not store.deadlines


async def test_history_and_handle_counts_remain_bounded():
    store = VoiceContextStore()
    pairs = [store.create(metadata(), asyncio.Event()) for _ in range(4)]
    with pytest.raises(ValueError, match="Too many"):
        store.create(metadata(), asyncio.Event())
    context = pairs[0][1]
    for index in range(100):
        context.append("user" if index % 2 else "assistant", "x" * 5000)
    assert len(context.history) <= 12
    assert sum(len(item["content"][0]["text"]) for item in context.history) <= 6000
    store.close(*pairs[0])
    store.create(metadata(), asyncio.Event())
    assert len(store.entries) == 4 and pairs[0][0] not in store.entries
    store.clear()
    assert not store.entries
