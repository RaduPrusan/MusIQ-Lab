"""FastAPI WebSocket endpoint at /api/audio/control.

Phase 2 dispatcher: extends Phase 1's device-enum scaffold with full source
playback (load / play / pause / seek), a 40 Hz clock-tick coroutine, and an
event drainer that forwards callback-emitted events (``ended``) to the
client. Phase 2 is **Shared mode only** — `msg.exclusive=True` is recorded
but ignored at open time; Phase 4 wires Exclusive.

Connection lifecycle
--------------------
- On `accept()`, a session dict is created with no AudioSession yet.
- First `set_device` lazily constructs the AudioSession + opens the stream.
- `load` decodes the MP3 + resamples to the device rate.
- `play` starts the stream and spawns the clock-tick coroutine; the event
  drainer task is started when the session is first created.
- On WS disconnect, the session is closed (stream stopped + closed) and
  the background tasks are cancelled.
- A module-level `_active_sessions` set is iterated by
  `shutdown_all_sessions()` (called from server.py's shutdown handler) to
  guarantee we never leave a PortAudio stream alive after FastAPI exits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import queue
import time
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import devices as _devices
from .open_chain import EngineUnavailable, open_with_fallback
from .protocol import (
    AckMsg,
    ClockMsg,
    DevicesMsg,
    EndedMsg,
    ErrorMsg,
    FallbackMsg,
    ListDevicesOp,
    LoadOp,
    LoadedMsg,
    LoopClearOp,
    LoopOp,
    PauseOp,
    PingOp,
    PlayOp,
    PongMsg,
    RefreshDevicesOp,
    SeekOp,
    SetDeviceOp,
    SetModeOp,
    StateMsg,
    StemOp,
    StemsLoadedMsg,
    StreamInfoMsg,
)
from .stream import STEM_NAMES, AudioSession

# Local mirror of webui.server._STEM_GLOBS — copied (not imported) to avoid
# a circular import (server.py imports this module via include_router).
# Keep in sync with the canonical dict in server.py:80-88; the
# `test_stem_paths_match_server_globs` test enforces parity.
_STEM_GLOBS: dict[str, list[str]] = {
    "vocals": ["stems_6s/*(Vocals)*.wav"],
    "bass":   ["stems_6s/*(Bass)*.wav"],
    "guitar": ["stems_6s/*(Guitar)*.wav"],
    "piano":  ["stems_6s/*(Piano)*.wav"],
    "other":  ["stems_6s/*(Other)*.wav"],
    "drums":  ["stems_6s/*(Drums)*.wav"],
}

log = logging.getLogger(__name__)

router = APIRouter()

# Module-level registry of live AudioSession instances. Added to on WS
# accept, removed on disconnect/cleanup, and walked by
# `shutdown_all_sessions()` to forcibly close everything on FastAPI exit.
_active_sessions: set[AudioSession] = set()


@router.websocket("/api/audio/control")
async def audio_control_ws(ws: WebSocket) -> None:
    await ws.accept()
    # Per-connection state:
    #   device:  the persisted (hostapi, device_name, exclusive, samplerate)
    #   session: the AudioSession (lazily-created on first set_device)
    #   event_queue: the SimpleQueue the callback uses to push "ended" etc.
    #   tasks:   the running clock-tick / event-drainer tasks
    session_state: dict = {
        "device": None,
        "session": None,
        "event_queue": queue.SimpleQueue(),
        "loaded": False,
        "tick_task": None,
        "drain_task": None,
        "stems_task": None,
    }
    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await _send(ws, ErrorMsg(code="bad_json", message="payload is not valid JSON"))
                continue
            if not isinstance(payload, dict):
                await _send(ws, ErrorMsg(code="bad_json", message="payload must be a JSON object"))
                continue
            op = payload.get("op")
            req = payload.get("req") if isinstance(payload.get("req"), int) else None
            try:
                await _dispatch(ws, session_state, op, payload, req)
            except Exception as exc:  # noqa: BLE001 — defensive WS dispatch
                log.exception("audio ws dispatch failure for op=%s", op)
                await _send(ws, ErrorMsg(
                    code="internal_error", message=str(exc), req=req,
                ))
    except WebSocketDisconnect:
        return
    finally:
        await _teardown(session_state)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def _dispatch(ws: WebSocket, session: dict, op: str | None,
                    payload: dict, req: int | None) -> None:
    if op == "ping":
        msg = PingOp.model_validate(payload)
        await _send(ws, PongMsg(
            req=msg.req,
            perf_t_client=msg.perf_t_client,
            perf_t_server=time.perf_counter(),
        ))
        return
    if op == "list_devices":
        msg = ListDevicesOp.model_validate(payload)
        entries = [asdict(e) for e in _devices.list_output_devices()]
        await _send(ws, DevicesMsg(req=msg.req, list=entries))
        return
    if op == "refresh_devices":
        await _handle_refresh_devices(ws, session, payload)
        return
    if op == "set_device":
        await _handle_set_device(ws, session, payload)
        return
    if op == "load":
        await _handle_load(ws, session, payload)
        return
    if op == "play":
        await _handle_play(ws, session, payload)
        return
    if op == "pause":
        await _handle_pause(ws, session, payload)
        return
    if op == "seek":
        await _handle_seek(ws, session, payload)
        return
    if op == "stem":
        await _handle_stem(ws, session, payload)
        return
    if op == "set_mode":
        await _handle_set_mode(ws, session, payload)
        return
    if op == "loop":
        await _handle_loop(ws, session, payload)
        return
    if op == "loop_clear":
        await _handle_loop_clear(ws, session, payload)
        return
    await _send(ws, ErrorMsg(
        code="unknown_op",
        message=f"unknown op: {op!r}",
        req=req,
    ))


# ---------------------------------------------------------------------------
# Op handlers
# ---------------------------------------------------------------------------


async def _handle_refresh_devices(ws: WebSocket, session: dict, payload: dict) -> None:
    """Re-enumerate output devices.

    `_devices.refresh_devices()` calls `sd._terminate(); sd._initialize()`
    to flush PortAudio's cached device list. That tears down EVERY open
    stream in the process — calling it under an active callback would
    cause a silent dropout at best and a use-after-free crash at worst.
    So we first close any session that's currently holding a stream
    open, notify the client via an `refresh_closed_stream` ErrorMsg, and
    only THEN run the re-enumerate. The client should re-issue
    `set_device` (and `load`) after the refresh completes — the user
    re-picks a device.
    """
    msg = RefreshDevicesOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is not None and audio.is_open():
        audio.close()
        session["device"] = None
        session["loaded"] = False
        # Notify the client that playback was halted by the refresh. Order
        # matters: emit the error BEFORE the DevicesMsg so a client that
        # auto-picks the first device on receipt of DevicesMsg can see the
        # state-reset notice first.
        await _send(ws, ErrorMsg(
            code="refresh_closed_stream",
            message="refreshed device list — playback stopped (re-pick a device)",
            req=msg.req,
        ))
    _devices.refresh_devices()
    entries = [asdict(e) for e in _devices.list_output_devices()]
    await _send(ws, DevicesMsg(req=msg.req, list=entries))


async def _handle_set_device(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = SetDeviceOp.model_validate(payload)

    # Lazily construct the AudioSession on first set_device. If one already
    # exists, reuse it — the open-chain orchestrator handles the "same params
    # → no-op, different params → reopen" case via AudioSession.open's
    # idempotency.
    audio = session.get("session")
    if audio is None:
        audio = AudioSession(event_queue=session["event_queue"])
        session["session"] = audio
        _active_sessions.add(audio)
        # Start the event drainer once per session.
        loop = asyncio.get_running_loop()
        session["drain_task"] = loop.create_task(
            _drain_events(ws, session["event_queue"], session)
        )

    # Phase 4: walk the (Exclusive → Shared → MME) fallback chain. The
    # orchestrator resolves (hostapi, device_name) → device_index for each
    # attempt — we don't pre-resolve here because a saved (wasapi, name)
    # may not exist (driver upgrade) while the same name still exists on
    # MME for the last-resort step.
    try:
        result = open_with_fallback(
            audio,
            hostapi=msg.hostapi,
            device_name=msg.device_name,
            exclusive=msg.exclusive,
            samplerate=msg.samplerate,
        )
    except EngineUnavailable as exc:
        # No entry in the chain opened. The client treats this as "swap to
        # WebAudio" — emitting a distinct code (vs. device_not_found from
        # the Phase 2 path) so the engine-factory listener can react.
        await _send(ws, ErrorMsg(
            code="engine_unavailable",
            message=str(exc),
            req=msg.req,
        ))
        return

    # Record what was ACTUALLY opened (which may differ from what msg
    # asked for). The persistent device choice in localStorage stays the
    # user's original request — the client only re-asserts what the
    # *server* believes about the live stream.
    session["device"] = {
        "hostapi": result.chosen_hostapi,
        "device_name": msg.device_name,
        "exclusive": result.chosen_exclusive,
        "samplerate": result.chosen_samplerate,
        "device_index": result.chosen_device_index,
    }
    # A new device invalidates any previously-loaded source (rate may
    # differ). The client must re-`load` before play.
    session["loaded"] = False
    await _send(ws, AckMsg(req=msg.req))
    if result.fallback_reason is not None:
        # AckMsg confirms the op landed; FallbackMsg communicates the
        # degraded path so the client can surface a toast. Order matters:
        # ack first, fallback notification second.
        await _send(ws, FallbackMsg(
            reason=result.fallback_reason,
            chosen_hostapi=result.chosen_hostapi,
            chosen_exclusive=result.chosen_exclusive,
            chosen_samplerate=result.chosen_samplerate,
            req=msg.req,
        ))
    # Phase 5: surface the actually-opened stream parameters. blocksize and
    # output_latency are driver-reported and only known post-open, so they
    # ride a follow-up StreamInfoMsg rather than the AckMsg. The Settings
    # UI renders this as "Output: <kHz> · <frames> frames · <ms> ms buffer".
    await _send(ws, StreamInfoMsg(
        samplerate=int(result.chosen_samplerate),
        blocksize=int(audio.blocksize),
        output_latency_sec=float(audio.output_latency),
        req=msg.req,
    ))


async def _handle_load(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = LoadOp.model_validate(payload)
    # Reject malformed slugs at the door — _resolve_source_mp3 would
    # otherwise happily join "../foo" into the cache path.
    from .._security import is_safe_slug
    if not is_safe_slug(msg.slug):
        await _send(ws, ErrorMsg(
            code="invalid_slug",
            message=f"invalid slug: {msg.slug!r}",
            req=msg.req,
        ))
        return
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="load requires a prior set_device",
            req=msg.req,
        ))
        return

    mp3_path = _resolve_source_mp3(msg.slug)
    if mp3_path is None:
        await _send(ws, ErrorMsg(
            code="source_not_found",
            message=f"no source MP3 for slug {msg.slug!r}",
            req=msg.req,
        ))
        return

    # load_source can be expensive (decode + soxr resample). Run on a
    # worker thread so we don't block the event loop or the WS read.
    #
    # Reset `loaded` BEFORE the attempt. If load_source raises (stale MP3
    # path mid-reanalyze, partial file, etc.) we must NOT retain the
    # previous track's `loaded=True` — otherwise a subsequent `play` op
    # would silently play the previously-loaded buffer.
    session["loaded"] = False
    loop = asyncio.get_running_loop()
    try:
        # If currently playing, pause first — load_source contract.
        if audio.is_playing():
            audio.pause()
        duration, src_sr = await loop.run_in_executor(
            None, audio.load_source, mp3_path
        )
    except Exception as exc:  # noqa: BLE001 — decode/resample failure
        log.exception("audio load failed for slug=%s", msg.slug)
        await _send(ws, ErrorMsg(
            code="load_failed",
            message=str(exc),
            req=msg.req,
        ))
        return

    session["loaded"] = True
    # Phase 3: surface which stems we *expect* to load (paths exist on disk).
    # The actual decode + resample happens in a background task below and
    # confirms via a StemsLoadedMsg. `stems_available` here is best-effort
    # advance signal — the client uses StemsLoadedMsg to gate mode toggle.
    stem_paths = _resolve_stem_paths(msg.slug)
    stems_advertised = sorted(
        name for name, p in stem_paths.items() if p is not None and p.is_file()
    )
    await _send(ws, LoadedMsg(
        req=msg.req,
        duration=duration,
        sample_rate=int(audio._samplerate),
        source_available=True,
        stems_available=stems_advertised,
    ))

    # Kick off the stem decode in the background. We deliberately don't
    # await it here — source playback should start immediately and stems
    # mode lights up when the StemsLoadedMsg arrives. This mirrors
    # WebAudioEngine._loadStems (web-audio-engine.js:55-80).
    if any(p is not None and p.is_file() for p in stem_paths.values()):
        loop_for_stems = asyncio.get_running_loop()
        # Cancel any prior background stem-load that might still be running
        # (e.g. user re-loaded mid-stem-decode); the new load supersedes it.
        prior = session.get("stems_task")
        if prior is not None and not prior.done():
            prior.cancel()
        session["stems_task"] = loop_for_stems.create_task(
            _load_stems_bg(ws, audio, stem_paths, msg.req)
        )


async def _handle_play(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = PlayOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="play requires a prior set_device",
            req=msg.req,
        ))
        return
    if not session.get("loaded"):
        await _send(ws, ErrorMsg(
            code="no_track",
            message="play requires a prior load",
            req=msg.req,
        ))
        return
    try:
        audio.play()
    except Exception as exc:  # noqa: BLE001
        log.exception("audio play failed")
        await _send(ws, ErrorMsg(
            code="play_failed", message=str(exc), req=msg.req,
        ))
        return
    await _send(ws, StateMsg(playing=True, mode=audio.get_mode(), req=msg.req))
    # Spin up the clock-tick loop if not already running.
    tick_task = session.get("tick_task")
    if tick_task is None or tick_task.done():
        loop = asyncio.get_running_loop()
        session["tick_task"] = loop.create_task(_clock_tick_loop(ws, audio))


async def _handle_pause(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = PauseOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="pause requires a prior set_device",
            req=msg.req,
        ))
        return
    audio.pause()
    await _send(ws, StateMsg(playing=False, mode=audio.get_mode(), req=msg.req))
    # One last clock tick so the client snaps to the exact pause position.
    await _send(ws, ClockMsg(
        song_t=audio.song_t,
        audio_t=audio.stream_time(),
        perf_t_server=time.perf_counter(),
        playing=False,
    ))


async def _handle_seek(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = SeekOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="seek requires a prior set_device",
            req=msg.req,
        ))
        return
    if not session.get("loaded"):
        await _send(ws, ErrorMsg(
            code="no_track",
            message="seek requires a prior load",
            req=msg.req,
        ))
        return
    was_playing = audio.is_playing()
    try:
        audio.seek(msg.song_t)
    except Exception as exc:  # noqa: BLE001
        await _send(ws, ErrorMsg(
            code="seek_failed", message=str(exc), req=msg.req,
        ))
        return
    await _send(ws, AckMsg(req=msg.req))
    # Hard-snap the client cursor to the new position.
    await _send(ws, ClockMsg(
        song_t=audio.song_t,
        audio_t=audio.stream_time(),
        perf_t_server=time.perf_counter(),
        playing=was_playing,
    ))
    if was_playing:
        await _send(ws, StateMsg(playing=True, mode=audio.get_mode()))
        tick_task = session.get("tick_task")
        if tick_task is None or tick_task.done():
            loop = asyncio.get_running_loop()
            session["tick_task"] = loop.create_task(_clock_tick_loop(ws, audio))


async def _handle_stem(ws: WebSocket, session: dict, payload: dict) -> None:
    """Apply per-stem mixer changes (vol/muted/soloed).

    Fire-and-ack: the smoothed gain takes effect on the next callback
    block (10 ms ramp). The ack is sent immediately so the client doesn't
    serialise on the network round-trip — actual audible change converges
    via the smoothing loop within ~10 ms regardless.
    """
    msg = StemOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="stem op requires a prior set_device",
            req=msg.req,
        ))
        return
    if msg.name not in STEM_NAMES:
        await _send(ws, ErrorMsg(
            code="unknown_stem",
            message=f"unknown stem name: {msg.name!r}",
            req=msg.req,
        ))
        return
    try:
        if msg.vol is not None:
            audio.set_stem_volume(msg.name, msg.vol)
        if msg.muted is not None:
            audio.set_stem_muted(msg.name, msg.muted)
        if msg.soloed is not None:
            audio.set_stem_soloed(msg.name, msg.soloed)
    except ValueError as exc:
        await _send(ws, ErrorMsg(code="bad_request", message=str(exc), req=msg.req))
        return
    await _send(ws, AckMsg(req=msg.req))


async def _handle_loop(ws: WebSocket, session: dict, payload: dict) -> None:
    """Set a sample-accurate loop region on the AudioSession.

    Phase 5: the wrap is sample-accurate in source mode and 1-block-lagged
    (~10 ms) in stems mode — see AudioSession._callback for the split.
    """
    msg = LoopOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="loop requires a prior set_device",
            req=msg.req,
        ))
        return
    try:
        audio.set_loop(msg.start, msg.end)
    except Exception as exc:  # noqa: BLE001
        await _send(ws, ErrorMsg(code="bad_request", message=str(exc), req=msg.req))
        return
    await _send(ws, AckMsg(req=msg.req))


async def _handle_loop_clear(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = LoopClearOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        # clear_loop is tolerant: idempotent when no device — ack so the
        # client doesn't end up in a stuck "loop still set" UI state if
        # the WS reconnects mid-loop.
        await _send(ws, AckMsg(req=msg.req))
        return
    audio.clear_loop()
    await _send(ws, AckMsg(req=msg.req))


async def _handle_set_mode(ws: WebSocket, session: dict, payload: dict) -> None:
    msg = SetModeOp.model_validate(payload)
    audio: Optional[AudioSession] = session.get("session")
    if audio is None or not audio.is_open():
        await _send(ws, ErrorMsg(
            code="no_device",
            message="set_mode requires a prior set_device",
            req=msg.req,
        ))
        return
    try:
        actual = audio.set_mode(msg.mode)
    except ValueError as exc:
        await _send(ws, ErrorMsg(code="bad_request", message=str(exc), req=msg.req))
        return
    # Echo the actual mode (may differ from requested if buffers unloaded).
    await _send(ws, StateMsg(
        playing=audio.is_playing(),
        mode=actual,
        req=msg.req,
    ))


# ---------------------------------------------------------------------------
# Background tasks: clock ticks + event drainer
# ---------------------------------------------------------------------------


async def _clock_tick_loop(ws: WebSocket, audio: AudioSession) -> None:
    """40 Hz clock-tick coroutine. Self-terminates when playback stops.

    The `playing` field is re-read after the loop gate because the callback
    can flip `audio._playing` to False between the gate check and the
    message construction (e.g. end-of-buffer). If we hard-coded
    `playing=True` here, a final stale ClockMsg could overtake the
    EndedMsg + StateMsg(playing=False) pair on the wire and re-set the
    client's `_playing` flag, causing the cursor to drift past end-of-track.
    """
    try:
        while audio.is_open() and audio.is_playing():
            playing_now = audio.is_playing()  # re-read; may have flipped since gate
            try:
                await ws.send_json(ClockMsg(
                    song_t=audio.song_t,
                    audio_t=audio.stream_time(),
                    perf_t_server=time.perf_counter(),
                    playing=playing_now,
                ).model_dump())
            except (WebSocketDisconnect, RuntimeError):
                return
            await asyncio.sleep(0.025)
    except asyncio.CancelledError:
        return


async def _load_stems_bg(
    ws: WebSocket,
    audio: AudioSession,
    stem_paths: dict[str, pathlib.Path],
    load_req: int,
) -> None:
    """Background task: decode + resample all stems, then push StemsLoadedMsg.

    `AudioSession.load_stems` is synchronous file I/O + soxr resample (~10 ms
    per 10 s of 48→44.1 kHz, so ~200-400 ms for a 5-min track at HQ quality).
    Running it on the asyncio loop thread would block clock ticks for the
    entire decode. We hand it off to the default thread-pool executor.

    `load_req` is the req number of the originating `load` op so the client
    can correlate the asynchronous completion back to the load that
    triggered it. (We use -1 for "unsolicited" if no req available.)
    """
    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(None, audio.load_stems, stem_paths)
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001 — best-effort surface failures
        log.exception("background stem-load failed")
        # All-or-nothing failure → mark every stem as failed.
        results = {n: f"failed: {exc}" for n in STEM_NAMES}
    try:
        await ws.send_json(StemsLoadedMsg(req=load_req, results=results).model_dump())
    except (WebSocketDisconnect, RuntimeError):
        return


async def _drain_events(ws: WebSocket, eq: "queue.SimpleQueue", session: dict) -> None:
    """Drain callback-emitted events (`ended`, …) and forward to the client.

    Runs as an asyncio task. The blocking eq.get() is parked on a thread-pool
    worker via run_in_executor, so asyncio.Task.cancel() injects CancelledError
    at the await boundary but cannot cancel the worker thread itself. The
    worker exits cleanly when _teardown pushes the None sentinel into the
    queue. The outer try/except handles the asyncio side of teardown;
    the sentinel handles the thread side.
    """
    loop = asyncio.get_running_loop()
    try:
        while True:
            item = await loop.run_in_executor(None, eq.get)
            if item is None:
                # Sentinel pushed by teardown.
                return
            kind, _payload = item
            if kind == "ended":
                # Stream hit end-of-buffer. The callback already flipped
                # playing=False; mirror that to the client. Echo the
                # current mode so the client doesn't snap back to "source"
                # (StateMsg's pydantic default) after a stems-mode track ends.
                audio: Optional[AudioSession] = session.get("session")
                mode = audio.get_mode() if audio is not None else "source"
                try:
                    await ws.send_json(EndedMsg().model_dump())
                    await ws.send_json(
                        StateMsg(playing=False, mode=mode).model_dump()
                    )
                except (WebSocketDisconnect, RuntimeError):
                    return
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


async def _teardown(session: dict) -> None:
    """Close the AudioSession, cancel background tasks. Idempotent."""
    audio: Optional[AudioSession] = session.get("session")
    # Cancel tasks first so they don't try to send on a half-closed WS.
    for task_key in ("tick_task", "drain_task", "stems_task"):
        task = session.get(task_key)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        session[task_key] = None
    # Push a sentinel so any drain task that snuck past the cancel exits cleanly.
    eq: Optional[queue.SimpleQueue] = session.get("event_queue")
    if eq is not None:
        try:
            eq.put_nowait(None)
        except Exception:
            pass
    if audio is not None:
        try:
            audio.close()
        finally:
            _active_sessions.discard(audio)
        session["session"] = None


async def shutdown_all_sessions() -> None:
    """Close every live AudioSession. Called from FastAPI shutdown handler.

    Iterates a snapshot of the registry so disconnect handlers can mutate
    the set concurrently without RuntimeError.
    """
    for audio in list(_active_sessions):
        try:
            audio.close()
        except Exception:  # noqa: BLE001 — best-effort teardown
            log.debug("shutdown_all_sessions: close raised", exc_info=True)
        _active_sessions.discard(audio)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_source_mp3(slug: str) -> Optional[pathlib.Path]:
    """Resolve a slug to the on-disk source MP3.

    Mirrors `/api/tracks/{slug}/audio/source` resolution: first try any
    `.mp3` in the cache dir, then fall back to `summary.json:windows_path`.
    """
    from .. import _paths, tracks

    cache = _paths.cache_dir() / slug
    if cache.is_dir():
        candidates = list(cache.glob("*.mp3"))
        if candidates:
            return candidates[0]
    # Fallback: read the summary for windows_path (original MP3 outside the cache).
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        return None
    win = (summary.get("track") or {}).get("windows_path")
    if win:
        p = pathlib.Path(win)
        if p.is_file():
            return p
    return None


def _resolve_stem_paths(slug: str) -> dict[str, pathlib.Path | None]:
    """Resolve `slug` → {stem_name: Path|None} via `_STEM_GLOBS`.

    Mirrors webui/server.py's `_STEM_GLOBS` lookup; copied (not imported) so
    this module is independent of server.py at import time. Missing or
    multi-match stems collapse to a single deterministic choice (first glob
    hit, sorted) — the audio backend tolerates None entries and skips them.
    """
    from .. import _paths

    cache = _paths.cache_dir() / slug
    out: dict[str, pathlib.Path | None] = {n: None for n in STEM_NAMES}
    if not cache.is_dir():
        return out
    for name, globs in _STEM_GLOBS.items():
        if name not in out:
            continue
        for glob in globs:
            hits = sorted(cache.glob(glob))
            if hits:
                out[name] = hits[0]
                break
    return out


async def _send(ws: WebSocket, model) -> None:
    await ws.send_json(model.model_dump())
