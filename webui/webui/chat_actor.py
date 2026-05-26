"""Per-slug Claude chat actor + registry.

A ChatActor wraps a long-lived ClaudeSDKClient bound to one chat slug. The
client is opened once and reused across turns, so multi-turn context is
maintained in-process (no per-turn subprocess restart, no `resume`
round-trip after the first turn). The registry creates actors lazily on
first POST per slug, sweeps idle ones, and closes everything on shutdown.

To survive process restarts and idle closes, build_options is supplied by
the caller and may bake in a `resume_session_id` read from chat.json. The
CLI replays prior context from its own session log on the actor's first
turn after (re-)opening; subsequent turns within the same client lifetime
use in-memory state.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from claude_agent_sdk import ClaudeSDKClient

from . import chat as _chat


log = logging.getLogger(__name__)


# Sentinel pushed onto an out_queue when the actor finishes a turn (success,
# error, or actor stop). `None` is unambiguous because real events are dicts.
_STREAM_END = None


class ChatActor:
    """One persistent ClaudeSDKClient per slug, fed by a serialized inbound queue."""

    def __init__(
        self,
        slug: str,
        build_options: Callable[[], Any],
    ) -> None:
        self.slug = slug
        self._build_options = build_options
        self._client: ClaudeSDKClient | None = None
        self._inbound: asyncio.Queue[tuple[str, asyncio.Queue[dict | None]] | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._processing = False
        self._tool_calls: dict[str, tuple[str, dict]] = {}
        self.last_active: float = time.monotonic()
        self.current_session_id: str | None = None

    async def start(self) -> None:
        if self._client is not None:
            log.debug("chat actor %s: already started", self.slug)
            return
        options = self._build_options()
        resume = getattr(options, "resume", None)
        log.info("chat actor %s: starting (resume=%s)", self.slug, resume or "<fresh>")
        client = ClaudeSDKClient(options=options)
        # Enter the async context manager manually so we own the lifetime.
        await client.__aenter__()
        self._client = client
        self._worker_task = asyncio.create_task(self._worker(), name=f"chat-actor-{self.slug}")
        log.info("chat actor %s: started; worker task=%s", self.slug, self._worker_task.get_name())

    async def stop(self) -> None:
        log.info("chat actor %s: stopping", self.slug)
        # Stop accepting new turns; signal worker to exit.
        await self._inbound.put(None)
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("chat actor %s: worker did not exit within 5s; cancelling", self.slug)
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self._worker_task = None
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                log.warning("chat actor %s: client close raised: %r", self.slug, e)
            self._client = None
        log.info("chat actor %s: stopped", self.slug)

    def is_busy(self) -> bool:
        """True iff a turn is being processed or waiting in the inbound queue."""
        return self._processing or self._inbound.qsize() > 0

    async def interrupt(self) -> bool:
        """Signal the underlying CLI to stop the in-flight turn.

        Returns True if an interrupt was sent, False if there was nothing to
        interrupt or the client wasn't connected. The CLI will emit a final
        ResultMessage shortly after (typically subtype="error_during_execution"
        or similar); the worker's `async for` exits normally and the turn's
        out_q closes via the existing fallback-done path.
        """
        if self._client is None or not self._processing:
            return False
        log.info("chat actor %s: interrupting in-flight turn", self.slug)
        try:
            await self._client.interrupt()
            return True
        except Exception as e:  # noqa: BLE001
            # If the SDK considers the client unhealthy, surface that to logs
            # but don't crash the actor — caller can fall back to kill().
            log.warning("chat actor %s: interrupt raised: %r", self.slug, e)
            return False

    async def submit_turn(self, user_message: str) -> AsyncIterator[dict]:
        """Enqueue one user turn; return an async iterator that yields the
        translated NDJSON events for that turn until the stream-end sentinel."""
        if self._client is None:
            raise RuntimeError("ChatActor not started")
        out_q: asyncio.Queue[dict | None] = asyncio.Queue()
        self.last_active = time.monotonic()
        await self._inbound.put((user_message, out_q))

        async def _drain() -> AsyncIterator[dict]:
            while True:
                ev = await out_q.get()
                if ev is _STREAM_END:
                    return
                yield ev

        return _drain()

    async def _worker(self) -> None:
        """Drain inbound forever; for each turn drive the SDK client and fan
        translated events into the per-turn out_queue. One turn at a time."""
        assert self._client is not None
        while True:
            item = await self._inbound.get()
            if item is None:
                # Stop sentinel from .stop()
                return
            user_message, out_q = item
            self._processing = True
            try:
                await self._run_one_turn(user_message, out_q)
            finally:
                self._processing = False
                self.last_active = time.monotonic()

    async def _run_one_turn(self, user_message: str, out_q: asyncio.Queue[dict | None]) -> None:
        assert self._client is not None
        # Reset per-turn correlation map. tool_use_ids are unique per turn,
        # so we don't need cross-turn state — and clearing avoids leaking
        # references to prior turns' inputs.
        self._tool_calls = {}
        emitted_done = False
        msg_count = 0
        ev_count = 0
        preview = user_message[:80].replace("\n", " ")
        log.info("chat actor %s: turn START prompt=%r", self.slug, preview)
        try:
            await self._client.query(user_message)
            log.info("chat actor %s: query() returned; awaiting receive_response", self.slug)
            async for msg in self._client.receive_response():
                msg_count += 1
                msg_kind = type(msg).__name__
                # Compact field summary for diagnostics — content type, tokens, etc.
                summary_bits = []
                if hasattr(msg, "content"):
                    c = msg.content
                    if isinstance(c, list):
                        summary_bits.append(f"content[{len(c)}]={[type(b).__name__ for b in c]}")
                if hasattr(msg, "subtype"):
                    summary_bits.append(f"subtype={msg.subtype!r}")
                if hasattr(msg, "is_error"):
                    summary_bits.append(f"is_error={msg.is_error}")
                if hasattr(msg, "session_id"):
                    summary_bits.append(f"session_id={msg.session_id}")
                if hasattr(msg, "usage") and msg.usage:
                    summary_bits.append(f"usage={msg.usage}")
                log.info("chat actor %s: SDK msg #%d %s %s", self.slug, msg_count, msg_kind, " ".join(summary_bits))
                for ev in _chat.translate_message(msg, self._tool_calls):
                    ev_count += 1
                    et = ev.get("type")
                    if et == "done":
                        emitted_done = True
                        sid = ev.get("session_id")
                        if isinstance(sid, str) and sid:
                            self.current_session_id = sid
                        log.info(
                            "chat actor %s: turn DONE msgs=%d events=%d session_id=%s tokens=%s",
                            self.slug, msg_count, ev_count, self.current_session_id, ev.get("tokens"),
                        )
                    elif et == "tool_use":
                        log.info("chat actor %s: tool_use name=%s id=%s", self.slug, ev.get("name"), ev.get("id"))
                    elif et == "tool_result":
                        log.info("chat actor %s: tool_result id=%s ok=%s", self.slug, ev.get("id"), ev.get("ok"))
                    await out_q.put(ev)
        except BaseException as e:  # noqa: BLE001 — translate every error
            kind, message = _chat.classify_exception(e) if isinstance(e, Exception) else ("internal", repr(e))
            log.exception("chat actor %s: turn FAILED kind=%s msgs=%d", self.slug, kind, msg_count)
            if kind == "auth":
                await out_q.put({"type": "auth_required"})
            else:
                await out_q.put({"type": "error", "kind": kind, "message": message})
            # Actor remains alive: the next turn will reuse the same client
            # if the SDK considers it still healthy. If it doesn't, the next
            # turn's exception will kill the actor via the registry's
            # error-recovery path (currently: caller must call kill()).
        finally:
            if not emitted_done:
                log.warning(
                    "chat actor %s: turn ENDED without ResultMessage (msgs=%d events=%d) — emitting fallback done",
                    self.slug, msg_count, ev_count,
                )
                # Always close the stream so the consumer's `async for` exits.
                # (No usage info available for error paths — that's expected.)
                await out_q.put({"type": "done", "session_id": self.current_session_id, "tokens": {"input": 0, "output": 0, "cache_read": 0}})
            await out_q.put(_STREAM_END)


class ChatRegistry:
    """Process-wide registry of slug → ChatActor with idle sweeper."""

    def __init__(self, *, idle_timeout_sec: float = 600.0, sweep_interval_sec: float = 60.0) -> None:
        self._actors: dict[str, ChatActor] = {}
        self._lock = asyncio.Lock()
        self._idle_timeout_sec = idle_timeout_sec
        self._sweep_interval_sec = sweep_interval_sec
        self._sweeper_task: asyncio.Task[None] | None = None
        self._stopped = False

    async def get_or_create(self, slug: str, *, build_options: Callable[[], Any]) -> ChatActor:
        async with self._lock:
            actor = self._actors.get(slug)
            if actor is None:
                log.info("chat registry: creating actor for slug=%s", slug)
                actor = ChatActor(slug, build_options)
                await actor.start()
                self._actors[slug] = actor
            else:
                actor.last_active = time.monotonic()
                log.debug("chat registry: reusing actor for slug=%s busy=%s", slug, actor.is_busy())
            return actor

    async def kill(self, slug: str) -> None:
        async with self._lock:
            actor = self._actors.pop(slug, None)
        if actor is not None:
            await actor.stop()

    async def interrupt(self, slug: str) -> bool:
        """Best-effort interrupt for an active turn on `slug`. Returns False
        when no actor exists or it isn't currently processing."""
        async with self._lock:
            actor = self._actors.get(slug)
        if actor is None:
            return False
        return await actor.interrupt()

    async def close_all(self) -> None:
        self._stopped = True
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._sweeper_task = None
        async with self._lock:
            actors = list(self._actors.values())
            self._actors.clear()
        await asyncio.gather(*(a.stop() for a in actors), return_exceptions=True)

    def start_sweeper(self) -> None:
        if self._sweeper_task is None and not self._stopped:
            self._sweeper_task = asyncio.create_task(self._sweep_loop(), name="chat-registry-sweeper")

    async def _sweep_loop(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(self._sweep_interval_sec)
                await self._sweep_once()
        except asyncio.CancelledError:
            return

    async def _sweep_once(self) -> None:
        now = time.monotonic()
        cutoff = now - self._idle_timeout_sec
        to_close: list[ChatActor] = []
        async with self._lock:
            for slug, actor in list(self._actors.items()):
                if not actor.is_busy() and actor.last_active < cutoff:
                    to_close.append(actor)
                    del self._actors[slug]
        for actor in to_close:
            log.info("chat actor %s: idle-closing (last_active=%.1fs ago)", actor.slug, now - actor.last_active)
            try:
                await actor.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("chat actor %s: idle close raised: %r", actor.slug, e)
