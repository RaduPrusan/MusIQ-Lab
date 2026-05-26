"""Phase 1 — WebSocket protocol tests for /api/audio/control.

The router under test is a thin op-dispatcher that hands off to
webui.audio_backend.devices for the device enumeration ops; it never opens a
PortAudio stream in Phase 1. Tests mock sounddevice so they don't depend on
the host's audio hardware.
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient


def _client():
    from webui.server import app
    return TestClient(app)


@pytest.fixture
def fake_devices(monkeypatch):
    import sounddevice as sd
    hostapis = [
        {"name": "MME"},
        {"name": "Windows DirectSound"},
        {"name": "Windows WASAPI"},
        {"name": "Windows WDM-KS"},
    ]
    devices = [
        {"name": "Speakers (Realtek)", "hostapi": 0,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        {"name": "Speakers (Realtek)", "hostapi": 2,
         "max_output_channels": 2, "default_samplerate": 48000.0},
    ]
    monkeypatch.setattr(sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sd, "query_hostapis", lambda: hostapis)


def test_ws_ping_echoes_req_and_perf_t_client():
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "ping", "req": 7, "perf_t_client": 1.5})
        msg = ws.receive_json()
    assert msg["type"] == "pong"
    assert msg["req"] == 7
    assert msg["perf_t_client"] == 1.5
    assert isinstance(msg["perf_t_server"], float)


def test_ws_list_devices_returns_filtered_entries(fake_devices):
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "list_devices", "req": 1})
        msg = ws.receive_json()
    assert msg["type"] == "devices"
    assert msg["req"] == 1
    # 1 MME row + 2 WASAPI rows.
    assert len(msg["list"]) == 3
    hostapis = {e["hostapi"] for e in msg["list"]}
    assert hostapis == {"mme", "wasapi"}
    # Each entry carries the keys the JS picker expects.
    sample = msg["list"][0]
    for key in ("id", "label", "hostapi", "device_name",
                "device_index", "exclusive", "default_samplerate"):
        assert key in sample, f"missing {key}"


def test_ws_refresh_devices_reenumerates(monkeypatch):
    """refresh_devices must re-enumerate. We assert the resulting list shape
    rather than poking PortAudio internals — the implementation calls
    sd._terminate(); sd._initialize() to flush PortAudio's cached device list
    and then runs the same list_output_devices() pass.
    """
    import sounddevice as sd
    hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
    devices = [
        {"name": "Speakers", "hostapi": 0,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        {"name": "Speakers", "hostapi": 1,
         "max_output_channels": 2, "default_samplerate": 48000.0},
    ]
    monkeypatch.setattr(sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sd, "query_hostapis", lambda: hostapis)
    # Stub PortAudio re-init so the test doesn't poke the real audio subsystem.
    monkeypatch.setattr(sd, "_terminate", lambda: None, raising=False)
    monkeypatch.setattr(sd, "_initialize", lambda: None, raising=False)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "refresh_devices", "req": 9})
        msg = ws.receive_json()
    assert msg["type"] == "devices"
    assert msg["req"] == 9
    assert len(msg["list"]) == 3  # 1 MME + 2 WASAPI rows


def test_ws_refresh_devices_closes_active_stream_with_notification(
    fake_devices, monkeypatch
):
    """If a stream is open, refresh_devices must close it BEFORE calling
    sd._terminate(); sd._initialize() — otherwise PortAudio gets torn down
    under an active callback. The handler emits ErrorMsg(code=
    `refresh_closed_stream`) before the DevicesMsg so the client can
    surface a toast and prompt the user to re-pick a device.
    """
    import sounddevice as sd

    # Spy on the active stream so we can assert it gets closed.
    streams: list = []

    class _SpyStream:
        def __init__(self, *a, **kw):
            self.time = 0.0
            self.started = False
            self.closed = False
            streams.append(self)
        def start(self): self.started = True
        def stop(self): self.started = False
        def close(self): self.closed = True

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)
    # Stub PortAudio re-init so the test doesn't poke the real audio subsystem.
    monkeypatch.setattr(sd, "_terminate", lambda: None, raising=False)
    monkeypatch.setattr(sd, "_initialize", lambda: None, raising=False)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        # 1. set_device → opens a stream.
        ws.send_json({
            "op": "set_device", "req": 1,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        # set_device also emits a follow-up StreamInfoMsg.
        info = ws.receive_json()
        assert info["type"] == "stream_info"
        # Sanity: a stream is now open.
        assert len(streams) == 1
        assert not streams[0].closed

        # 2. refresh_devices while the stream is open.
        ws.send_json({"op": "refresh_devices", "req": 2})
        # First message: refresh_closed_stream notice.
        first = ws.receive_json()
        assert first["type"] == "error"
        assert first["code"] == "refresh_closed_stream"
        assert first["req"] == 2
        # Second message: the device list.
        second = ws.receive_json()
        assert second["type"] == "devices"
        assert second["req"] == 2

    # The pre-refresh stream must have been closed before the
    # terminate/initialize pair fired.
    assert streams[0].closed, (
        "refresh_devices must close the active stream before re-enumerating"
    )


def test_ws_refresh_devices_no_active_stream_just_lists(fake_devices, monkeypatch):
    """When no session is open, refresh_devices is a plain re-enumerate (no
    refresh_closed_stream notice). Regression for the close-first path."""
    import sounddevice as sd
    monkeypatch.setattr(sd, "_terminate", lambda: None, raising=False)
    monkeypatch.setattr(sd, "_initialize", lambda: None, raising=False)
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "refresh_devices", "req": 7})
        msg = ws.receive_json()
    assert msg["type"] == "devices"
    assert msg["req"] == 7


def test_ws_set_device_opens_stream_in_phase2(fake_devices, monkeypatch):
    """Phase 2 contract: set_device resolves (hostapi, name) -> device_index,
    constructs an AudioSession, and opens a PortAudio stream. We assert by
    spying on sd.OutputStream and checking it was constructed exactly once
    with the resolved device_index.
    """
    import sounddevice as sd

    calls = []

    class _SpyStream:
        def __init__(self, *a, **kw):
            calls.append({"args": a, "kw": kw})
            self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 4,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        msg = ws.receive_json()
    assert msg["type"] == "ack"
    assert msg["req"] == 4
    assert len(calls) == 1, "set_device must construct exactly one OutputStream"
    # The WASAPI Speakers entry sits at device-index 1 in fake_devices.
    assert calls[0]["kw"].get("device") == 1
    assert calls[0]["kw"].get("samplerate") == 48000
    assert calls[0]["kw"].get("channels") == 2
    # Phase 2: Shared only — extra_settings must be None.
    assert calls[0]["kw"].get("extra_settings") is None


def test_ws_set_device_missing_returns_error(fake_devices):
    """set_device with a (hostapi, name) tuple that no current device
    matches under any host API → ErrorMsg(code='engine_unavailable').

    Phase 4 change: the fallback chain (Exclusive → Shared → MME) means
    "device not found" only collapses to an error when *every* entry
    fails to resolve. fake_devices declares Speakers (Realtek) on both
    WASAPI and MME, so the moment the user types a name that exists
    nowhere ("Nope"), every find_device_by_identity returns None and the
    orchestrator raises EngineUnavailable. The client treats this as
    "swap to WebAudio" (vs. Phase 2's no-op `device_not_found`).
    """
    import sounddevice as sd

    def _explode(*a, **kw):
        raise AssertionError("device-not-found path must NOT open a stream")

    orig = sd.OutputStream
    sd.OutputStream = _explode  # type: ignore[assignment]
    try:
        c = _client()
        with c.websocket_connect("/api/audio/control") as ws:
            ws.send_json({
                "op": "set_device", "req": 5,
                "hostapi": "wasapi", "device_name": "Nope (No Such Card)",
                "exclusive": False, "samplerate": 48000,
            })
            msg = ws.receive_json()
    finally:
        sd.OutputStream = orig  # type: ignore[assignment]
    assert msg["type"] == "error"
    assert msg["code"] == "engine_unavailable"
    assert msg["req"] == 5


def test_ws_load_without_set_device_returns_no_device():
    """Phase 2 contract: a `load` op before any `set_device` returns
    ErrorMsg(code='no_device'). Slug resolution is not even attempted.
    """
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "load", "req": 11, "slug": "doesnt_matter"})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "no_device"
    assert msg["req"] == 11


def test_ws_play_without_load_returns_no_track(fake_devices, monkeypatch):
    """play before load must return ErrorMsg(code='no_track')."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 1,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        ws.receive_json()  # ack
        ws.receive_json()  # Phase 5: stream_info follow-up
        ws.send_json({"op": "play", "req": 2})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "no_track"
    assert msg["req"] == 2


def test_ws_pause_without_track_acks_with_state(fake_devices, monkeypatch):
    """pause should be tolerant: if a session is open but nothing's loaded
    /playing, it still emits a StateMsg(playing=False) rather than crashing.
    This mirrors the WebAudioEngine.pause() contract (no-op when idle).
    """
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 1,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        ws.receive_json()  # ack
        ws.receive_json()  # Phase 5: stream_info follow-up
        ws.send_json({"op": "pause", "req": 2})
        state_msg = ws.receive_json()
        clock_msg = ws.receive_json()
    assert state_msg["type"] == "state"
    assert state_msg["playing"] is False
    assert clock_msg["type"] == "clock"
    assert clock_msg["playing"] is False


def test_ws_shutdown_closes_all_sessions(fake_devices, monkeypatch):
    """The FastAPI shutdown handler `_close_audio_sessions` must close every
    live AudioSession. Construct a session, then invoke the handler
    directly and assert .close() was called.
    """
    import asyncio

    import sounddevice as sd

    close_calls = []

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): close_calls.append(True)

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    from webui.audio_backend import ws as audio_ws

    c = _client()
    with c.websocket_connect("/api/audio/control") as wsock:
        wsock.send_json({
            "op": "set_device", "req": 1,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        wsock.receive_json()  # ack
        wsock.receive_json()  # Phase 5: stream_info follow-up
        # While the WS is still open, the session is alive in the registry.
        assert len(audio_ws._active_sessions) == 1
        # Simulate FastAPI's shutdown handler — directly invoke
        # `shutdown_all_sessions()` while the WS is still connected.
        # asyncio.new_event_loop() so we don't depend on whichever loop
        # the TestClient WS is parked on.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(audio_ws.shutdown_all_sessions())
        finally:
            loop.close()
    # After WS disconnect + shutdown_all_sessions, the registry must be empty.
    assert len(audio_ws._active_sessions) == 0
    assert len(close_calls) >= 1


def test_ws_unknown_op_returns_error():
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "definitely_not_a_real_op", "req": 2})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "unknown_op"
    assert msg["req"] == 2


def test_ws_bad_json_returns_error():
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_text("not json at all {{{")
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "bad_json"
    # No req available when the payload is unparseable.
    assert msg.get("req") in (None,)


def test_clock_tick_carries_actual_playing_state_after_end():
    """Regression: end-of-buffer must not leave a stale ClockMsg(playing=True)
    in flight.

    Drives the specific iteration where `is_playing()` flips between the
    loop gate and the in-body re-read. With the pre-fix code (hard-coded
    `playing=True` in the ClockMsg body), the emitted message would
    incorrectly carry `playing=True`; the fix re-reads `is_playing()`
    after the gate so the message reflects the actual state.
    """
    import asyncio

    from webui.audio_backend import ws as audio_ws

    class _FakeAudio:
        """Returns is_playing()=True for the first two reads (gate + body),
        then False thereafter so the loop terminates after one iteration.

        Sequence:
          call 1: gate          -> True   (enter body)
          call 2: in-body  re-read -> False  (emitted ClockMsg.playing)
          call 3: next gate       -> False  (loop exits)
        """
        def __init__(self):
            # Pre-fix code only calls is_playing() once per iter (gate);
            # post-fix code calls it twice (gate + re-read). The 3rd call
            # is the gate of the next iteration. We want the FIRST iter's
            # in-body re-read to observe False.
            self._is_playing_seq = iter([True, False, False, False])
            self.song_t = 12.5

        def is_open(self):
            return True

        def is_playing(self):
            return next(self._is_playing_seq)

        def stream_time(self):
            return 12.5

    class _FakeWS:
        def __init__(self):
            self.sent = []
        async def send_json(self, payload):
            self.sent.append(payload)

    fake_ws = _FakeWS()
    fake_audio = _FakeAudio()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            audio_ws._clock_tick_loop(fake_ws, fake_audio)  # type: ignore[arg-type]
        )
    finally:
        loop.close()

    # Exactly one ClockMsg should have been emitted (one iteration before
    # the gate flipped). Its `playing` field must reflect the in-body
    # re-read (False), not the pre-fix hard-coded True.
    clock_msgs = [m for m in fake_ws.sent if m.get("type") == "clock"]
    assert len(clock_msgs) == 1, f"expected 1 clock msg, got {fake_ws.sent}"
    assert clock_msgs[0]["playing"] is False, (
        "ClockMsg must carry the actual is_playing() reading, not a "
        "hard-coded True — otherwise a stale tick can race past EndedMsg "
        "and re-set the client's _playing flag."
    )


def test_ws_failed_load_clears_loaded_state(fake_devices, monkeypatch):
    """Regression: if load_source raises, session['loaded'] must be reset to
    False so a subsequent play op is rejected with code='no_track'.

    Without the fix, a successful prior load would leave loaded=True, and
    the next play would silently play the previous track's buffer.
    """
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    # Make _resolve_source_mp3 return a fake path so we get past the
    # source_not_found gate and hit load_source.
    import pathlib

    from webui.audio_backend import ws as audio_ws

    monkeypatch.setattr(
        audio_ws,
        "_resolve_source_mp3",
        lambda slug: pathlib.Path(f"/fake/{slug}.mp3"),
    )

    # First load_source call succeeds (track A); second raises (track B).
    from webui.audio_backend.stream import AudioSession

    call_count = {"n": 0}

    def fake_load_source(self, mp3_path):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # track A: pretend a successful decode at 48 kHz, 10 s long.
            self._samplerate = 48000
            return (10.0, 48000)
        # track B: simulate stale-MP3 decode failure.
        raise RuntimeError("simulated decode failure (stale MP3)")

    monkeypatch.setattr(AudioSession, "load_source", fake_load_source)
    # Bypass the play() preconditions that would fail with no real buffer.
    monkeypatch.setattr(AudioSession, "play", lambda self: None)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 1,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        assert ws.receive_json()["type"] == "ack"
        ws.receive_json()  # Phase 5: stream_info follow-up

        # 1) Successful load — sets loaded=True.
        ws.send_json({"op": "load", "req": 2, "slug": "track_a"})
        loaded_a = ws.receive_json()
        assert loaded_a["type"] == "loaded", loaded_a

        # 2) Failed load — must reset loaded to False.
        ws.send_json({"op": "load", "req": 3, "slug": "track_b"})
        err_b = ws.receive_json()
        assert err_b["type"] == "error"
        assert err_b["code"] == "load_failed"
        assert err_b["req"] == 3

        # 3) Play op must now be rejected with no_track — proving the
        #    failed load cleared the previous track's loaded=True flag.
        ws.send_json({"op": "play", "req": 4})
        play_resp = ws.receive_json()

    assert play_resp["type"] == "error", play_resp
    assert play_resp["code"] == "no_track", (
        "play after a failed load must return no_track; got "
        f"{play_resp!r}. This means session['loaded'] was not reset and "
        "the previous track's buffer would have played silently."
    )
    assert play_resp["req"] == 4


# ---------------------------------------------------------------------------
# Phase 3 — stem ops + set_mode + stems_loaded
# ---------------------------------------------------------------------------


def _set_device(ws):
    """Boilerplate: send set_device + read its ack so subsequent ops can
    assume a session is set up.

    Phase 5: every successful set_device is followed by a StreamInfoMsg with
    the driver-reported samplerate/blocksize/latency. We drain it here so
    callers don't have to know about the second message. Error paths do
    NOT emit a StreamInfoMsg — we only drain when the first response was
    an ack.
    """
    ws.send_json({
        "op": "set_device", "req": 1,
        "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
        "exclusive": False, "samplerate": 48000,
    })
    ack = ws.receive_json()
    if ack.get("type") == "ack":
        info = ws.receive_json()
        assert info.get("type") == "stream_info", (
            f"expected stream_info after ack, got {info!r}"
        )
    return ack


def test_ws_stem_op_routes_through_audio_session(fake_devices, monkeypatch):
    """{op:'stem',name:'vocals',vol:0.5} → ack + set_stem_volume called."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    from webui.audio_backend.stream import AudioSession

    calls = []
    orig_vol = AudioSession.set_stem_volume
    orig_mute = AudioSession.set_stem_muted
    orig_solo = AudioSession.set_stem_soloed

    def spy_vol(self, name, v):
        calls.append(("vol", name, v))
        return orig_vol(self, name, v)

    def spy_mute(self, name, b):
        calls.append(("muted", name, b))
        return orig_mute(self, name, b)

    def spy_solo(self, name, b):
        calls.append(("soloed", name, b))
        return orig_solo(self, name, b)

    monkeypatch.setattr(AudioSession, "set_stem_volume", spy_vol)
    monkeypatch.setattr(AudioSession, "set_stem_muted", spy_mute)
    monkeypatch.setattr(AudioSession, "set_stem_soloed", spy_solo)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ack0 = _set_device(ws)
        assert ack0["type"] == "ack"

        ws.send_json({"op": "stem", "req": 10, "name": "vocals", "vol": 0.5})
        ack = ws.receive_json()
    assert ack["type"] == "ack"
    assert ack["req"] == 10
    assert ("vol", "vocals", 0.5) in calls


def test_ws_stem_op_unknown_name_returns_error(fake_devices, monkeypatch):
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        _set_device(ws)
        ws.send_json({"op": "stem", "req": 11, "name": "kazoo", "vol": 0.5})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "unknown_stem"
    assert msg["req"] == 11


def test_ws_set_mode_acks_with_state(fake_devices, monkeypatch):
    """{op:'set_mode',mode:'source'} → StateMsg with mode field."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        _set_device(ws)
        ws.send_json({"op": "set_mode", "req": 12, "mode": "source"})
        msg = ws.receive_json()
    assert msg["type"] == "state"
    assert msg["mode"] == "source"
    assert msg["req"] == 12


def test_ws_set_mode_stems_falls_back_without_buffers(fake_devices, monkeypatch):
    """set_mode('stems') with nothing loaded returns whatever IS available."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        _set_device(ws)
        ws.send_json({"op": "set_mode", "req": 13, "mode": "stems"})
        msg = ws.receive_json()
    # No source loaded, no stems loaded → falls back to the initial mode
    # ("source" — set by open()).
    assert msg["type"] == "state"
    assert msg["mode"] == "source"


def test_ws_load_triggers_background_stems_loaded(fake_devices, monkeypatch, tmp_path):
    """After a successful `load`, the server kicks off a background stem
    decode and pushes StemsLoadedMsg when it finishes.
    """
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    # Build a fake cache dir with all 6 stems present.
    from webui.audio_backend import ws as audio_ws
    slug = "fake_track"
    cache_root = tmp_path / "cache"
    track_dir = cache_root / slug / "stems_6s"
    track_dir.mkdir(parents=True)
    sr = 48000
    n = sr // 20  # 50 ms of silence each
    for tok in ("Vocals", "Bass", "Guitar", "Piano", "Other", "Drums"):
        p = track_dir / f"{slug}_({tok})_htdemucs_6s.wav"
        data = np.zeros((n, 2), dtype=np.float32)
        sf.write(str(p), data, sr, subtype="FLOAT")

    # Redirect _paths.cache_dir() and _resolve_source_mp3 so load can succeed.
    from webui import _paths
    monkeypatch.setattr(_paths, "cache_dir", lambda: cache_root)

    # Source MP3 — make a tiny WAV that load_source can decode.
    src_path = tmp_path / "source.mp3"
    data = np.zeros((sr // 10, 2), dtype=np.float32)
    sf.write(str(src_path), data, sr, subtype="FLOAT", format="WAV")

    monkeypatch.setattr(audio_ws, "_resolve_source_mp3", lambda s: src_path)

    # Patch AudioSession.load_source so we don't depend on libsndfile MP3 read.
    from webui.audio_backend.stream import AudioSession

    def fake_load_source(self, mp3_path):
        self._source_buf = np.zeros((sr, 2), dtype=np.float32)
        self._source_n_samples = sr
        return (1.0, sr)

    monkeypatch.setattr(AudioSession, "load_source", fake_load_source)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        _set_device(ws)
        ws.send_json({"op": "load", "req": 20, "slug": slug})
        # 1st message: LoadedMsg
        loaded = ws.receive_json()
        assert loaded["type"] == "loaded", loaded
        assert "stems_available" in loaded
        # Eventually the StemsLoadedMsg arrives. Reading repeatedly until we
        # see it; bail out after a few messages so a regression doesn't hang
        # the test forever.
        stems_loaded = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "stems_loaded":
                stems_loaded = msg
                break
    assert stems_loaded is not None, "expected a stems_loaded message after load"
    # All six stems decoded successfully.
    assert set(stems_loaded["results"]) == {
        "vocals", "bass", "guitar", "piano", "other", "drums"
    }
    assert all(v == "loaded" for v in stems_loaded["results"].values()), (
        stems_loaded["results"]
    )


def test_stem_paths_match_server_globs():
    """Parity test: webui.audio_backend.ws._STEM_GLOBS must mirror the
    canonical mapping in webui.server._STEM_GLOBS for the six htdemucs
    stems. Any drift would mean the audio backend looks at the wrong
    paths.
    """
    from webui.audio_backend.ws import _STEM_GLOBS as WS_GLOBS
    from webui.server import _STEM_GLOBS as SERVER_GLOBS
    for name in ("vocals", "bass", "guitar", "piano", "other", "drums"):
        assert SERVER_GLOBS.get(name) == WS_GLOBS.get(name), (
            f"glob drift for {name}: ws={WS_GLOBS.get(name)} vs "
            f"server={SERVER_GLOBS.get(name)}"
        )


# ---------------------------------------------------------------------------
# Phase 4 — Exclusive fallback chain over the WS
# ---------------------------------------------------------------------------


def test_set_device_emits_fallback_msg_on_exclusive_failure(fake_devices, monkeypatch):
    """set_device(exclusive=True) where Exclusive open fails but Shared
    succeeds → AckMsg + FallbackMsg pair. The FallbackMsg carries the
    reason and the actual chosen row."""
    from webui.audio_backend import open_chain
    from webui.audio_backend import ws as audio_ws
    from webui.audio_backend.open_chain import OpenResult

    # Stub the orchestrator so the test doesn't have to drive PortAudio
    # internals — we cover the orchestrator end-to-end in
    # test_audio_open_chain.py. Here we only care about the WS-level
    # protocol shape.
    def fake_open_with_fallback(audio, *, hostapi, device_name, exclusive, samplerate):
        return OpenResult(
            chosen_hostapi="wasapi",
            chosen_exclusive=False,
            chosen_device_index=1,
            chosen_samplerate=samplerate,
            fallback_reason="exclusive_failed:device_in_use",
        )

    monkeypatch.setattr(audio_ws, "open_with_fallback", fake_open_with_fallback)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 30,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": True, "samplerate": 48000,
        })
        ack = ws.receive_json()
        fb = ws.receive_json()
        # Phase 5 always emits StreamInfoMsg after the ack/fb pair.
        info = ws.receive_json()
        assert info["type"] == "stream_info"

    assert ack["type"] == "ack"
    assert ack["req"] == 30
    assert fb["type"] == "fallback"
    assert fb["req"] == 30
    assert fb["reason"] == "exclusive_failed:device_in_use"
    assert fb["chosen_hostapi"] == "wasapi"
    assert fb["chosen_exclusive"] is False
    assert fb["chosen_samplerate"] == 48000


def test_set_device_no_fallback_emits_only_ack(fake_devices, monkeypatch):
    """When the first attempt succeeds (no fallback), set_device emits a
    single AckMsg — no FallbackMsg follow-up. Regression-guard against
    accidentally emitting an empty/false-positive fallback."""
    from webui.audio_backend import ws as audio_ws
    from webui.audio_backend.open_chain import OpenResult

    def fake_open_with_fallback(audio, *, hostapi, device_name, exclusive, samplerate):
        return OpenResult(
            chosen_hostapi=hostapi,
            chosen_exclusive=exclusive,
            chosen_device_index=1,
            chosen_samplerate=samplerate,
            fallback_reason=None,
        )

    monkeypatch.setattr(audio_ws, "open_with_fallback", fake_open_with_fallback)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 31,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        ack = ws.receive_json()
        # Phase 5: StreamInfoMsg always follows AckMsg(set_device).
        info = ws.receive_json()
        # Send a ping to flush — if there was a stray FallbackMsg in the
        # queue we'd see it before the pong.
        ws.send_json({"op": "ping", "req": 32, "perf_t_client": 1.0})
        next_msg = ws.receive_json()

    assert ack["type"] == "ack"
    assert ack["req"] == 31
    assert info["type"] == "stream_info"
    # Pong arrived next — no fallback msg was in between.
    assert next_msg["type"] == "pong"
    assert next_msg["req"] == 32


def test_set_device_emits_engine_unavailable_on_total_failure(fake_devices, monkeypatch):
    """When every entry in the fallback chain raises, the WS emits a single
    ErrorMsg with code='engine_unavailable'. The client's wasapi-engine.js
    treats this as terminal and the engine-factory listener swaps to
    WebAudio."""
    from webui.audio_backend import ws as audio_ws
    from webui.audio_backend.open_chain import EngineUnavailable

    def fake_open_with_fallback(audio, *, hostapi, device_name, exclusive, samplerate):
        raise EngineUnavailable("all attempts failed: simulated total outage")

    monkeypatch.setattr(audio_ws, "open_with_fallback", fake_open_with_fallback)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 33,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": True, "samplerate": 48000,
        })
        err = ws.receive_json()

    assert err["type"] == "error"
    assert err["code"] == "engine_unavailable"
    assert err["req"] == 33
    assert "all attempts failed" in err["message"]


def test_play_pause_seek_preserve_current_mode_in_state_msg(
    fake_devices, monkeypatch, tmp_path,
):
    """Regression: every StateMsg emitted by play/pause/seek must echo the
    AudioSession's current mode, not the pydantic default ("source").

    Before the fix, _handle_play / _handle_pause / _handle_seek built
    StateMsg(playing=..., req=...) without mode=, so a session in "stems"
    mode would emit StateMsg(mode="source") after every play/pause click,
    flipping the client's UI back to SRC even though stems kept mixing.
    """
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    # Build a fake cache dir with all 6 stems present so set_mode('stems')
    # has buffers to switch to.
    from webui.audio_backend import ws as audio_ws
    slug = "fake_track_mode"
    cache_root = tmp_path / "cache"
    track_dir = cache_root / slug / "stems_6s"
    track_dir.mkdir(parents=True)
    sr = 48000
    n = sr // 20  # 50 ms of silence each
    for tok in ("Vocals", "Bass", "Guitar", "Piano", "Other", "Drums"):
        p = track_dir / f"{slug}_({tok})_htdemucs_6s.wav"
        data = np.zeros((n, 2), dtype=np.float32)
        sf.write(str(p), data, sr, subtype="FLOAT")

    from webui import _paths
    monkeypatch.setattr(_paths, "cache_dir", lambda: cache_root)

    src_path = tmp_path / "source.mp3"
    data = np.zeros((sr // 10, 2), dtype=np.float32)
    sf.write(str(src_path), data, sr, subtype="FLOAT", format="WAV")
    monkeypatch.setattr(audio_ws, "_resolve_source_mp3", lambda s: src_path)

    # Patch AudioSession.load_source so we don't depend on libsndfile MP3 read.
    from webui.audio_backend.stream import AudioSession

    def fake_load_source(self, mp3_path):
        self._source_buf = np.zeros((sr, 2), dtype=np.float32)
        self._source_n_samples = sr
        return (1.0, sr)

    monkeypatch.setattr(AudioSession, "load_source", fake_load_source)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        _set_device(ws)
        # Load (kicks off background stem decode).
        ws.send_json({"op": "load", "req": 20, "slug": slug})
        loaded = ws.receive_json()
        assert loaded["type"] == "loaded"
        # Wait for stems_loaded so set_mode('stems') has buffers.
        stems_loaded = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "stems_loaded":
                stems_loaded = msg
                break
        assert stems_loaded is not None

        # Switch to stems mode.
        ws.send_json({"op": "set_mode", "req": 21, "mode": "stems"})
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["mode"] == "stems", state

        def _next_state(ws, *, expect_req=None, drain_limit=20):
            """Drain ClockMsg / EndedMsg noise until we see a StateMsg.

            The 40 Hz clock-tick + event-drainer coroutines can interleave
            messages on the wire, so we can't assume the next receive is
            the StateMsg the op handler just emitted.
            """
            for _ in range(drain_limit):
                msg = ws.receive_json()
                if msg.get("type") == "state":
                    if expect_req is None or msg.get("req") == expect_req:
                        return msg
            raise AssertionError(
                f"did not see a StateMsg (req={expect_req}) within "
                f"{drain_limit} messages"
            )

        # play — StateMsg MUST report mode="stems", not the default "source".
        ws.send_json({"op": "play", "req": 22})
        play_state = _next_state(ws, expect_req=22)
        assert play_state["playing"] is True
        assert play_state["mode"] == "stems", (
            "play in stems mode emitted StateMsg(mode='source'); the client "
            f"would flip back to SRC. got: {play_state!r}"
        )

        # pause — same contract.
        ws.send_json({"op": "pause", "req": 23})
        pause_state = _next_state(ws, expect_req=23)
        assert pause_state["playing"] is False
        assert pause_state["mode"] == "stems", (
            f"pause in stems mode emitted wrong mode: {pause_state!r}"
        )

        # Resume play, then seek (exercises was_playing=True branch of
        # _handle_seek which emits a StateMsg).
        ws.send_json({"op": "play", "req": 24})
        resume_state = _next_state(ws, expect_req=24)
        assert resume_state["mode"] == "stems"

        ws.send_json({"op": "seek", "req": 25, "song_t": 0.2})
        # _handle_seek emits AckMsg(req=25), ClockMsg, then StateMsg
        # (req=None because the StateMsg from seek doesn't carry req).
        seek_state = _next_state(ws)
        assert seek_state["playing"] is True
        assert seek_state["mode"] == "stems", (
            f"seek in stems mode emitted wrong mode: {seek_state!r}"
        )


# ---------------------------------------------------------------------------
# Phase 5 — loop wrap, stream_info, refresh terminate/initialize
# ---------------------------------------------------------------------------


def test_ws_loop_op_sets_loop(fake_devices, monkeypatch):
    """{op:'loop',start,end} → ack + set_loop called with the right args."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    from webui.audio_backend.stream import AudioSession

    calls = []
    orig = AudioSession.set_loop

    def spy_set_loop(self, s, e):
        calls.append((s, e))
        return orig(self, s, e)

    monkeypatch.setattr(AudioSession, "set_loop", spy_set_loop)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ack0 = _set_device(ws)
        assert ack0["type"] == "ack"

        ws.send_json({"op": "loop", "req": 50, "start": 1.0, "end": 3.0})
        ack = ws.receive_json()
    assert ack["type"] == "ack"
    assert ack["req"] == 50
    assert (1.0, 3.0) in calls


def test_ws_loop_clear_op_clears(fake_devices, monkeypatch):
    """{op:'loop_clear'} → ack + clear_loop called."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw): self.time = 0.0
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    from webui.audio_backend.stream import AudioSession

    cleared = {"n": 0}
    orig = AudioSession.clear_loop

    def spy_clear(self):
        cleared["n"] += 1
        return orig(self)

    monkeypatch.setattr(AudioSession, "clear_loop", spy_clear)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        _set_device(ws)
        ws.send_json({"op": "loop_clear", "req": 51})
        ack = ws.receive_json()
    assert ack["type"] == "ack"
    assert ack["req"] == 51
    assert cleared["n"] == 1


def test_ws_loop_clear_without_device_is_tolerant():
    """loop_clear without a prior set_device acks rather than erroring —
    matches the "don't strand the UI in a stuck loop-set state" contract."""
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "loop_clear", "req": 52})
        msg = ws.receive_json()
    assert msg["type"] == "ack"
    assert msg["req"] == 52


def test_ws_loop_without_device_returns_error():
    """loop op without a prior set_device → error (loop requires an open device)."""
    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({"op": "loop", "req": 53, "start": 0.0, "end": 1.0})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "no_device"
    assert msg["req"] == 53


def test_set_device_emits_stream_info_follow_up(fake_devices, monkeypatch):
    """After AckMsg(set_device), the server emits StreamInfoMsg carrying the
    driver-reported samplerate/blocksize/latency for the Settings UI."""
    import sounddevice as sd

    class _SpyStream:
        def __init__(self, *a, **kw):
            self.time = 0.0
            self.latency = 0.0042  # 4.2 ms — fake WASAPI Shared latency
            self.blocksize = 480
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "OutputStream", _SpyStream)

    c = _client()
    with c.websocket_connect("/api/audio/control") as ws:
        ws.send_json({
            "op": "set_device", "req": 60,
            "hostapi": "wasapi", "device_name": "Speakers (Realtek)",
            "exclusive": False, "samplerate": 48000,
        })
        ack = ws.receive_json()
        info = ws.receive_json()

    assert ack["type"] == "ack"
    assert info["type"] == "stream_info"
    assert info["samplerate"] == 48000
    assert info["blocksize"] == 480
    # Allow a small float jitter — the value passes through float() casts.
    assert abs(info["output_latency_sec"] - 0.0042) < 1e-6
    assert info["req"] == 60
