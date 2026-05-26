"""Tests for chat_actor.ChatActor and ChatRegistry. The real ClaudeSDKClient
is monkeypatched out so these run without invoking the Claude CLI."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from webui import chat as chat_mod
from webui import chat_actor as actor_mod


def _mk_text_block(text):
    b = MagicMock(spec=["text"])
    b.text = text
    return b


def _mk_result_msg(session_id="sid-1"):
    m = MagicMock(spec=["session_id", "usage", "duration_ms"])
    m.session_id = session_id
    m.usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0}
    m.duration_ms = 100
    return m


def _mk_assistant_msg(blocks):
    m = MagicMock(spec=["content"])
    m.content = blocks
    return m


class FakeClient:
    """Stand-in for ClaudeSDKClient. Configurable per-turn message scripts.

    Pass a list of "scripts": each script is the list of SDK messages to
    yield from receive_response() for one turn. Successive `query` calls
    consume scripts in order.
    """

    def __init__(self, *, options: Any = None, scripts: list[list[Any]] | None = None,
                 query_raises: BaseException | None = None) -> None:
        self.options = options
        self._scripts: list[list[Any]] = list(scripts or [])
        self._query_raises = query_raises
        self.aenter_calls = 0
        self.aexit_calls = 0
        self.queries: list[str] = []

    async def __aenter__(self):
        self.aenter_calls += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.aexit_calls += 1

    async def query(self, text: str) -> None:
        self.queries.append(text)
        if self._query_raises is not None:
            raise self._query_raises

    async def receive_response(self):
        if self._scripts:
            script = self._scripts.pop(0)
        else:
            script = []
        for msg in script:
            yield msg


def _patch_client(monkeypatch, factory):
    """Replace `webui.chat_actor.ClaudeSDKClient` with a callable that
    returns whatever the factory yields. Also captures construction calls."""
    captured: list[FakeClient] = []
    def _ctor(options=None):
        c = factory(options=options)
        captured.append(c)
        return c
    monkeypatch.setattr(actor_mod, "ClaudeSDKClient", _ctor)
    return captured


@pytest.mark.asyncio
async def test_actor_submit_turn_yields_translated_events(monkeypatch):
    fake_msgs = [_mk_assistant_msg([_mk_text_block("hello "), _mk_text_block("world")]),
                 _mk_result_msg(session_id="sid-x")]
    captured = _patch_client(monkeypatch, lambda options=None: FakeClient(options=options, scripts=[fake_msgs]))
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        stream = await actor.submit_turn("hi")
        events = [e async for e in stream]
        assert [e["type"] for e in events] == ["text", "text", "done"]
        assert events[0]["delta"] == "hello "
        assert events[2]["session_id"] == "sid-x"
        assert actor.current_session_id == "sid-x"
        assert captured[0].queries == ["hi"]
    finally:
        await actor.stop()
        assert captured[0].aexit_calls == 1


@pytest.mark.asyncio
async def test_actor_serializes_two_turns(monkeypatch):
    # Two turns, each with one assistant message + result. The second turn's
    # first event must arrive only after the first turn's done.
    turn_a = [_mk_assistant_msg([_mk_text_block("A")]), _mk_result_msg(session_id="sa")]
    turn_b = [_mk_assistant_msg([_mk_text_block("B")]), _mk_result_msg(session_id="sb")]
    _patch_client(monkeypatch, lambda options=None: FakeClient(options=options, scripts=[turn_a, turn_b]))
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        s1 = await actor.submit_turn("first")
        s2 = await actor.submit_turn("second")
        # Drain in order.
        e1 = [e async for e in s1]
        e2 = [e async for e in s2]
        assert any(e.get("delta") == "A" for e in e1)
        assert any(e.get("delta") == "B" for e in e2)
        assert actor.current_session_id == "sb"
    finally:
        await actor.stop()


@pytest.mark.asyncio
async def test_actor_is_busy_reflects_processing(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowClient(FakeClient):
        async def receive_response(self):
            started.set()
            await release.wait()
            yield _mk_result_msg(session_id="sx")

    _patch_client(monkeypatch, lambda options=None: SlowClient(options=options))
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        stream = await actor.submit_turn("hi")
        await started.wait()
        assert actor.is_busy() is True
        release.set()
        # Drain to completion.
        _ = [e async for e in stream]
        # Give the worker a tick to clear _processing.
        for _ in range(20):
            if not actor.is_busy():
                break
            await asyncio.sleep(0.01)
        assert actor.is_busy() is False
    finally:
        await actor.stop()


@pytest.mark.asyncio
async def test_actor_emits_auth_required_on_cli_not_found(monkeypatch):
    from claude_agent_sdk import CLINotFoundError
    _patch_client(
        monkeypatch,
        lambda options=None: FakeClient(options=options, query_raises=CLINotFoundError("nope")),
    )
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        stream = await actor.submit_turn("hi")
        events = [e async for e in stream]
        types = [e["type"] for e in events]
        assert "auth_required" in types
        # Always closes the stream with done so the consumer's `async for` exits.
        assert "done" in types
    finally:
        await actor.stop()


@pytest.mark.asyncio
async def test_actor_emits_error_for_generic_exception(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda options=None: FakeClient(options=options, query_raises=RuntimeError("boom")),
    )
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        stream = await actor.submit_turn("hi")
        events = [e async for e in stream]
        err = [e for e in events if e["type"] == "error"]
        assert len(err) == 1
        assert err[0]["kind"] == "internal"
        assert "boom" in err[0]["message"]
    finally:
        await actor.stop()


@pytest.mark.asyncio
async def test_actor_translation_uses_chat_translate_message(monkeypatch):
    # Sanity: an immediate ui_action (seek_to) emerges via translate_message
    # when the assistant message contains a tool_use block.
    tu = MagicMock(spec=["id", "name", "input"])
    tu.id = "tu1"; tu.name = "mcp__musiq-tools__seek_to"; tu.input = {"time_sec": 5.0}
    msgs = [_mk_assistant_msg([tu]), _mk_result_msg("sid")]
    _patch_client(monkeypatch, lambda options=None: FakeClient(options=options, scripts=[msgs]))
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        events = [e async for e in await actor.submit_turn("seek")]
        assert any(e["type"] == "ui_action" and e["action"] == "seek_to" for e in events)
    finally:
        await actor.stop()


# --- Registry --------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_get_or_create_returns_same_instance_per_slug(monkeypatch):
    _patch_client(monkeypatch, lambda options=None: FakeClient(options=options))
    reg = actor_mod.ChatRegistry()
    try:
        a1 = await reg.get_or_create("demo", build_options=lambda: object())
        a2 = await reg.get_or_create("demo", build_options=lambda: object())
        assert a1 is a2
        a3 = await reg.get_or_create("other", build_options=lambda: object())
        assert a3 is not a1
    finally:
        await reg.close_all()


@pytest.mark.asyncio
async def test_registry_kill_stops_actor_and_removes(monkeypatch):
    captured = _patch_client(monkeypatch, lambda options=None: FakeClient(options=options))
    reg = actor_mod.ChatRegistry()
    try:
        await reg.get_or_create("demo", build_options=lambda: object())
        await reg.kill("demo")
        assert "demo" not in reg._actors
        assert captured[0].aexit_calls == 1
        # A subsequent get_or_create constructs a NEW client.
        await reg.get_or_create("demo", build_options=lambda: object())
        assert len(captured) == 2
    finally:
        await reg.close_all()


@pytest.mark.asyncio
async def test_registry_close_all_stops_every_actor(monkeypatch):
    captured = _patch_client(monkeypatch, lambda options=None: FakeClient(options=options))
    reg = actor_mod.ChatRegistry()
    await reg.get_or_create("a", build_options=lambda: object())
    await reg.get_or_create("b", build_options=lambda: object())
    await reg.close_all()
    assert reg._actors == {}
    assert all(c.aexit_calls == 1 for c in captured)


@pytest.mark.asyncio
async def test_actor_interrupt_calls_client_when_processing(monkeypatch):
    """ChatActor.interrupt() forwards to client.interrupt() iff a turn is
    in flight. The registry's stop endpoint relies on this."""
    class InterruptibleClient(FakeClient):
        def __init__(self, *, options=None, **kw):
            super().__init__(options=options, **kw)
            self.interrupt_calls = 0
        async def interrupt(self):
            self.interrupt_calls += 1

    captured = _patch_client(monkeypatch, lambda options=None: InterruptibleClient(options=options))
    actor = actor_mod.ChatActor("demo", build_options=lambda: object())
    await actor.start()
    try:
        # Not processing yet → no-op.
        assert await actor.interrupt() is False
        assert captured[0].interrupt_calls == 0
        # Simulate in-flight turn.
        actor._processing = True
        assert await actor.interrupt() is True
        assert captured[0].interrupt_calls == 1
    finally:
        actor._processing = False
        await actor.stop()


@pytest.mark.asyncio
async def test_registry_interrupt_returns_false_when_no_actor(monkeypatch):
    _patch_client(monkeypatch, lambda options=None: FakeClient(options=options))
    reg = actor_mod.ChatRegistry()
    try:
        # No actor created for "ghost"; interrupt is a soft no-op.
        assert await reg.interrupt("ghost") is False
    finally:
        await reg.close_all()


@pytest.mark.asyncio
async def test_registry_idle_sweeper_closes_idle_actors(monkeypatch):
    captured = _patch_client(monkeypatch, lambda options=None: FakeClient(options=options))
    reg = actor_mod.ChatRegistry(idle_timeout_sec=0.05, sweep_interval_sec=0.02)
    try:
        actor = await reg.get_or_create("demo", build_options=lambda: object())
        # Force last_active into the past.
        actor.last_active = time.monotonic() - 1.0
        reg.start_sweeper()
        # Wait up to 0.5s for the sweep to fire and close the idle actor.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if "demo" not in reg._actors:
                break
        assert "demo" not in reg._actors
        assert captured[0].aexit_calls == 1
    finally:
        await reg.close_all()
