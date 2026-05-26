"""Phase 2 — AudioSession tests with the PortAudio stream mocked out.

We never open a real `sd.OutputStream` in CI. Every test patches
`sd.OutputStream` with a spy stream whose `.start()/.stop()/.close()` are
recorded, then drives the recorded callback directly with synthetic
`time_info` to assert per-frame behaviour.
"""
from __future__ import annotations

import io
import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import numpy as np
import pytest
import sounddevice as sd
import soundfile as sf


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _SpyStream:
    """Stand-in for `sd.OutputStream` that records calls + the callback."""

    last_instance: Optional["_SpyStream"] = None

    def __init__(self, **kw):
        self.kw = kw
        self.callback = kw.get("callback")
        self.samplerate = kw.get("samplerate")
        self.device = kw.get("device")
        self.channels = kw.get("channels")
        self.blocksize = kw.get("blocksize")
        self.dtype = kw.get("dtype")
        self.extra_settings = kw.get("extra_settings")
        self.time = 0.0
        self.start_called = 0
        self.stop_called = 0
        self.close_called = 0
        _SpyStream.last_instance = self

    def start(self) -> None: self.start_called += 1
    def stop(self) -> None: self.stop_called += 1
    def close(self) -> None: self.close_called += 1


@pytest.fixture
def spy_stream(monkeypatch):
    """Patch sd.OutputStream + return the SpyStream class for inspection."""
    monkeypatch.setattr(sd, "OutputStream", _SpyStream)
    _SpyStream.last_instance = None
    return _SpyStream


@pytest.fixture
def tiny_wav(tmp_path):
    """Write a 0.1 s mono WAV at 48 kHz. Caller decides what to feed it to."""
    sr = 48000
    n = sr // 10  # 0.1 s
    # sine wave — non-zero so we can assert the buffer copy actually moved data.
    t = np.arange(n) / sr
    data = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    path = tmp_path / "tiny.wav"
    sf.write(str(path), data, sr, subtype="FLOAT")
    return path


def _new_session():
    from webui.audio_backend.stream import AudioSession
    return AudioSession(event_queue=queue.SimpleQueue()), AudioSession


# ---------------------------------------------------------------------------
# open() / close()
# ---------------------------------------------------------------------------


def test_open_constructs_output_stream_with_expected_args(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000, blocksize=0)
    inst = spy_stream.last_instance
    assert inst is not None
    assert inst.device == 3
    assert inst.samplerate == 48000
    assert inst.channels == 2
    assert inst.dtype == "float32"
    assert inst.blocksize == 0
    # Phase 2 must always be Shared mode — extra_settings must be None.
    assert inst.extra_settings is None
    # open() does NOT auto-start; play() does.
    assert inst.start_called == 0


def test_open_is_idempotent_for_identical_params(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000)
    first = spy_stream.last_instance
    sess.open(device_index=3, samplerate=48000)
    # No new stream was constructed.
    assert spy_stream.last_instance is first


def test_open_reopens_on_different_params(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000)
    first = spy_stream.last_instance
    sess.open(device_index=4, samplerate=44100)
    second = spy_stream.last_instance
    assert second is not first
    # Old stream got stopped+closed during the reopen.
    assert first.close_called == 1


def test_close_idempotent(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.close()
    sess.close()  # second close should be a no-op, not raise


# ---------------------------------------------------------------------------
# load_source() — decode + resample
# ---------------------------------------------------------------------------


def test_load_source_decodes_wav_and_reports_duration(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    duration, src_sr = sess.load_source(tiny_wav)
    assert src_sr == 48000
    # 0.1 s of audio at 48 kHz, but allow a tiny rounding slop in case
    # libsndfile rounds frame counts.
    assert abs(duration - 0.1) < 1e-3
    assert sess._source_buf is not None
    assert sess._source_buf.shape[1] == 2  # mono replicated to stereo
    assert sess._source_buf.dtype == np.float32


def test_load_source_resamples_when_rates_differ(spy_stream, tmp_path):
    """If device rate ≠ source rate, soxr.resample is invoked transparently."""
    sr_in = 44100
    n = sr_in // 10
    data = (np.random.default_rng(0).standard_normal(n) * 0.3).astype(np.float32)
    path = tmp_path / "44k.wav"
    sf.write(str(path), data, sr_in, subtype="FLOAT")

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    duration, src_sr = sess.load_source(path)
    assert src_sr == 44100
    # After resampling 0.1 s 44.1k → 48k we should have ~4800 samples.
    assert sess._source_buf is not None
    assert abs(sess._source_buf.shape[0] - 4800) < 10
    # Duration is computed off the resampled buffer at the device rate.
    assert abs(duration - 0.1) < 5e-3


def test_load_source_requires_open(spy_stream, tiny_wav):
    sess, _ = _new_session()
    with pytest.raises(RuntimeError):
        sess.load_source(tiny_wav)


# ---------------------------------------------------------------------------
# Callback — the heart of Phase 2
# ---------------------------------------------------------------------------


def _drive_callback(stream, frames=480, dac_time=1.0):
    """Invoke the captured callback with synthetic `time_info` + outdata."""
    outdata = np.zeros((frames, 2), dtype=np.float32)
    time_info = SimpleNamespace(
        inputBufferAdcTime=0.0,
        currentTime=dac_time - 0.005,
        outputBufferDacTime=dac_time,
    )
    stream.callback(outdata, frames, time_info, 0)
    return outdata


def test_callback_emits_silence_when_not_playing(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    inst = spy_stream.last_instance
    # Pre-fill outdata with garbage to confirm the callback overwrites with zeros.
    outdata = np.full((480, 2), 0.7, dtype=np.float32)
    time_info = SimpleNamespace(outputBufferDacTime=1.0, currentTime=0.995, inputBufferAdcTime=0.0)
    inst.callback(outdata, 480, time_info, 0)
    assert np.all(outdata == 0.0)


def test_callback_copies_source_buffer_when_playing(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    inst = spy_stream.last_instance
    out = _drive_callback(inst, frames=480, dac_time=1.0)
    # First 480 samples of source must be in outdata.
    assert np.allclose(out[:480], sess._source_buf[:480])
    # play_offset advanced by 480.
    assert sess._play_offset == 480


def test_callback_updates_anchor_on_first_call(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    inst = spy_stream.last_instance
    _drive_callback(inst, frames=480, dac_time=2.5)
    assert sess._anchor is not None
    # song_t at offset=0 with sr=48000 → 0.0; audio_t recorded as the DAC time.
    assert sess._anchor.song_t == 0.0
    assert sess._anchor.audio_t == 2.5
    # Subsequent callbacks must NOT clobber the anchor.
    _drive_callback(inst, frames=480, dac_time=3.5)
    assert sess._anchor.audio_t == 2.5


def test_callback_emits_ended_at_end_of_buffer(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    # Manually advance the play offset to one frame before EOF, then drive
    # a callback that crosses the boundary. The first callback will fill
    # the remainder; the next one will see n_remaining == 0 and emit "ended".
    n = sess._source_n_samples
    inst = spy_stream.last_instance
    # First callback consumes everything left.
    sess._play_offset = n - 100
    _drive_callback(inst, frames=480, dac_time=1.0)
    assert sess._play_offset == n
    # Second callback hits the end-of-buffer branch.
    _drive_callback(inst, frames=480, dac_time=2.0)
    # The session must have emitted ("ended", None) into its event queue
    # and flipped _playing to False.
    assert sess._playing is False
    item = sess._event_queue.get_nowait()
    assert item == ("ended", None)


# ---------------------------------------------------------------------------
# play / pause / seek
# ---------------------------------------------------------------------------


def test_play_starts_stream(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    assert spy_stream.last_instance.start_called == 1
    assert sess._playing is True


def test_pause_stops_stream_and_freezes_song_t(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    inst = spy_stream.last_instance
    # Advance the play offset by driving a few callbacks.
    _drive_callback(inst, frames=2400, dac_time=1.0)
    # Spoof stream.time so song_t() / pause() get a real-looking value.
    inst.time = 1.05  # 50 ms past the anchor's audio_t=1.0
    sess.pause()
    assert sess._playing is False
    assert inst.stop_called == 1
    # song_t() should now return the frozen position (anchor.song_t + 0.05).
    assert abs(sess.song_t - 0.05) < 1e-6


def test_seek_repositions_play_offset(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    # Seek before play — must just move offset.
    sess.seek(0.05)  # 50 ms in
    assert sess._play_offset == int(round(0.05 * 48000))
    assert sess._playing is False


def test_seek_during_play_resumes_play(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    inst = spy_stream.last_instance
    initial_starts = inst.start_called
    sess.seek(0.05)
    assert sess._playing is True
    assert inst.start_called == initial_starts + 1  # was paused + replayed
    assert sess._play_offset == int(round(0.05 * 48000))


def test_replay_from_end_rewinds(spy_stream, tiny_wav):
    """If paused at end-of-buffer, play() rewinds and starts from 0 — same
    behaviour as WebAudioEngine.play() with _pausedAt >= duration."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess._play_offset = sess._source_n_samples  # simulate paused at end
    sess.play()
    assert sess._play_offset == 0
    assert sess._playing is True


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_duration_property(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    assert abs(sess.duration - 0.1) < 1e-3


def test_song_t_when_not_playing_returns_frozen_position(spy_stream, tiny_wav):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    # No playback yet — song_t reads _last_song_pos (= 0.0).
    assert sess.song_t == 0.0
    sess.seek(0.03)
    assert abs(sess.song_t - 0.03) < 1e-6


# ---------------------------------------------------------------------------
# Phase 3 — stem mixing
# ---------------------------------------------------------------------------


def _write_stem_wav(path, *, sr=48000, n=None, amplitude=0.5, channels=2):
    """Write a tiny stereo wav with a constant DC offset so we can assert
    which stem contributed to the mix without arithmetic precision worries.
    `amplitude` is the per-sample value; channels duplicates it.
    """
    if n is None:
        n = sr // 10  # 0.1 s
    if channels == 1:
        data = np.full((n,), amplitude, dtype=np.float32)
    else:
        data = np.full((n, channels), amplitude, dtype=np.float32)
    sf.write(str(path), data, sr, subtype="FLOAT")
    return path


def _make_stem_paths(tmp_path, *, sr=48000, amplitudes=None, missing=()):
    """Build a {stem_name: Path|None} dict per STEM_NAMES order.

    `amplitudes` maps stem_name → per-sample amplitude. Missing names
    default to 0.0 (still emitted to disk as silence so they aren't
    confused with "missing").  `missing` is a set of names to leave OUT
    of the dict entirely — testing the missing-path branch.
    """
    from webui.audio_backend.stream import STEM_NAMES
    amplitudes = amplitudes or {}
    paths: dict = {}
    for name in STEM_NAMES:
        if name in missing:
            continue
        amp = amplitudes.get(name, 0.0)
        p = tmp_path / f"{name}.wav"
        _write_stem_wav(p, sr=sr, amplitude=amp)
        paths[name] = p
    return paths


def test_load_stems_decodes_all_six(spy_stream, tmp_path):
    """All six stems decoded → every slot populated, all results == 'loaded'."""
    from webui.audio_backend.stream import STEM_NAMES
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    paths = _make_stem_paths(tmp_path, amplitudes={n: 0.1 for n in STEM_NAMES})
    results = sess.load_stems(paths)
    assert set(results) == set(STEM_NAMES)
    assert all(v == "loaded" for v in results.values()), results
    for n in STEM_NAMES:
        assert sess._stem_buffers[n] is not None
        assert sess._stem_buffers[n].shape[1] == 2
    assert sess._has_stems_loaded() is True


def test_load_stems_missing_path_reports_missing(spy_stream, tmp_path):
    """A stem absent from the input dict reports 'missing'; its slot stays None."""
    from webui.audio_backend.stream import STEM_NAMES
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    # Drop "drums" entirely (mirrors Stage 9 LarsNet soft-fail).
    paths = _make_stem_paths(
        tmp_path, amplitudes={n: 0.1 for n in STEM_NAMES}, missing={"drums"}
    )
    results = sess.load_stems(paths)
    assert results["drums"] == "missing"
    assert sess._stem_buffers["drums"] is None
    # The other five are still loaded.
    assert results["vocals"] == "loaded"
    assert sess._has_stems_loaded() is True


def test_load_stems_resamples_to_device_rate(spy_stream, tmp_path):
    """Source rate ≠ device rate triggers soxr resample; buffer length scales."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    # 44.1 kHz stem; 0.1 s → 4410 samples in, ~4800 out at 48 kHz.
    p = tmp_path / "vocals.wav"
    _write_stem_wav(p, sr=44100, n=4410, amplitude=0.2)
    results = sess.load_stems({"vocals": p})
    assert results["vocals"] == "loaded"
    buf = sess._stem_buffers["vocals"]
    assert buf is not None
    assert abs(buf.shape[0] - 4800) < 10


def test_stem_mix_zeros_when_no_stems_loaded(spy_stream, tiny_wav):
    """Stems mode + no stems loaded → callback emits silence, no crash."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    # Force stems mode without loading any stems.
    with sess._lock:
        sess._mode = "stems"
    inst = spy_stream.last_instance
    out = _drive_callback(inst, frames=480, dac_time=1.0)
    # No stems → mix accumulator stays zero → outdata is zero.
    assert np.all(out == 0.0)


def test_stem_mix_truth_table_mute(spy_stream, tmp_path, tiny_wav):
    """vocals + bass loaded, vocals muted → output equals bass alone (after
    the gain ramp has converged)."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    # Source required by play(); doesn't affect stems mix.
    sess.load_source(tiny_wav)
    paths = _make_stem_paths(
        tmp_path, amplitudes={"vocals": 0.3, "bass": 0.2}
    )
    sess.load_stems(paths)
    sess.set_mode("stems")
    sess.set_stem_muted("vocals", True)
    sess.play()
    inst = spy_stream.last_instance
    # Drive enough callbacks for the 10 ms IIR to converge (one 480-frame
    # block @ 48 kHz = 10 ms = one tau ≈ 0.63 convergence; six blocks gets
    # us within float-noise of the target).
    out = None
    for _ in range(8):
        out = _drive_callback(inst, frames=480, dac_time=1.0)
    # Expected output: 0 (vocals muted) + 0.2 (bass) ≈ 0.2
    # The vocals stem also has zeros for the other 4 stems (their files
    # are silence by default).
    assert np.allclose(out, 0.2, atol=1e-3), out[0]


def test_stem_mix_truth_table_solo(spy_stream, tmp_path, tiny_wav):
    """vocals + bass loaded, bass soloed → vocals ducks to 0, bass passes."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    paths = _make_stem_paths(
        tmp_path, amplitudes={"vocals": 0.3, "bass": 0.2}
    )
    sess.load_stems(paths)
    sess.set_mode("stems")
    sess.set_stem_soloed("bass", True)
    sess.play()
    inst = spy_stream.last_instance
    out = None
    for _ in range(8):
        out = _drive_callback(inst, frames=480, dac_time=1.0)
    # Only bass at 0.2 passes; vocals duck to 0.
    assert np.allclose(out, 0.2, atol=1e-3), out[0]


def test_stem_gain_smoothing_converges_toward_target(spy_stream, tmp_path, tiny_wav):
    """One-pole IIR with tau=10 ms must produce ~0.63 after one tau (480
    frames @ 48 kHz)."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    paths = _make_stem_paths(tmp_path, amplitudes={"vocals": 1.0})
    sess.load_stems(paths)
    sess.set_mode("stems")
    sess.set_stem_volume("vocals", 1.0)
    sess.play()
    inst = spy_stream.last_instance
    # First 480-frame block: gain ramps from 0 toward 1.0; coefficient
    # `1 - exp(-1)` ≈ 0.632.
    out = _drive_callback(inst, frames=480, dac_time=1.0)
    # Output equals the smoothed gain (since vocals amplitude is 1.0).
    # Allow a small float-noise margin.
    g = float(out[0, 0])
    assert 0.55 < g < 0.70, f"expected ~0.63 after one tau, got {g}"


def test_stem_set_mode_falls_back_when_stems_missing(spy_stream, tiny_wav):
    """set_mode('stems') with no stems loaded falls back to source mode."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    actual = sess.set_mode("stems")
    assert actual == "source"


def test_stem_setters_validate_name(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    with pytest.raises(ValueError):
        sess.set_stem_volume("not_a_stem", 0.5)
    with pytest.raises(ValueError):
        sess.set_stem_muted("not_a_stem", True)
    with pytest.raises(ValueError):
        sess.set_stem_soloed("not_a_stem", True)


def test_stem_callback_no_allocations_steady_state(spy_stream, tmp_path, tiny_wav):
    """Drive the stems-mix callback many times and assert no significant
    heap growth — pre-allocated buffers are reused.

    Tracemalloc captures Python-level allocations; numpy scratch via
    `out=` arg should not allocate new arrays. A small (< 64 KB) delta
    is allowed for occasional small-object overhead (frame info dicts,
    log handlers, etc.).
    """
    import tracemalloc

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    paths = _make_stem_paths(
        tmp_path,
        amplitudes={"vocals": 0.1, "bass": 0.1, "drums": 0.1,
                    "piano": 0.1, "guitar": 0.1, "other": 0.1},
    )
    sess.load_stems(paths)
    sess.set_mode("stems")
    sess.play()
    inst = spy_stream.last_instance
    # Warm-up: let the gain ramp settle so any first-block overhead doesn't
    # land in the measurement window.
    pre_outdata = np.zeros((480, 2), dtype=np.float32)
    time_info = SimpleNamespace(
        inputBufferAdcTime=0.0, currentTime=0.995, outputBufferDacTime=1.0
    )
    for _ in range(10):
        inst.callback(pre_outdata, 480, time_info, 0)
    # Measure 200 steady-state callbacks.
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()
    for _ in range(200):
        inst.callback(pre_outdata, 480, time_info, 0)
    snap_after = tracemalloc.take_snapshot()
    diff = snap_after.compare_to(snap_before, "lineno")
    total_bytes = sum(stat.size_diff for stat in diff if stat.size_diff > 0)
    tracemalloc.stop()
    # 100 KB ceiling — captures real leaks but tolerates pytest's own
    # bookkeeping and dict-snapshot overhead in the per-callback path.
    assert total_bytes < 100_000, (
        f"steady-state stems callback allocated {total_bytes} bytes over 200 calls"
    )


# ---------------------------------------------------------------------------
# Phase 3 — three-bug-fix regressions
# ---------------------------------------------------------------------------


def test_load_stems_discards_superseded_load(spy_stream, tmp_path, monkeypatch):
    """If load_source runs while load_stems is mid-decode, the stem swap
    must be discarded — Track A's stems must NOT land in Track B's session.

    We block `soundfile.read` inside the decode worker via a threading.Event,
    let `load_source` run on the main thread (which bumps `_load_gen`), then
    release the worker and assert it returned "superseded" without mutating
    `_stem_buffers`.
    """
    import threading
    from webui.audio_backend import stream as stream_mod
    from webui.audio_backend.stream import STEM_NAMES

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)

    # Write a tiny WAV that load_source can decode without blocking.
    src_wav = tmp_path / "track_b.wav"
    sr = 48000
    n_src = sr // 10
    t = np.arange(n_src) / sr
    sf.write(str(src_wav), (np.sin(2 * np.pi * 880 * t) * 0.3).astype(np.float32), sr, subtype="FLOAT")

    # Write a Track A stem WAV that the worker thread will try to decode.
    track_a_stems_dir = tmp_path / "a"
    track_a_stems_dir.mkdir()
    track_a_vocals = track_a_stems_dir / "vocals.wav"
    _write_stem_wav(track_a_vocals, sr=48000, amplitude=0.9)

    # Patch sf.read inside the stream module so it blocks until released.
    decode_release = threading.Event()
    decode_entered = threading.Event()
    real_sf_read = stream_mod.sf.read

    def blocking_sf_read(*args, **kwargs):
        # First call from load_stems → block; later calls (load_source) pass.
        if "vocals.wav" in str(args[0]) and not decode_release.is_set():
            decode_entered.set()
            decode_release.wait(timeout=5.0)
        return real_sf_read(*args, **kwargs)

    monkeypatch.setattr(stream_mod.sf, "read", blocking_sf_read)

    # Kick off load_stems on a worker thread (this is what
    # loop.run_in_executor would do in production).
    results_box: dict = {}

    def _worker():
        results_box["r"] = sess.load_stems({"vocals": track_a_vocals})

    worker = threading.Thread(target=_worker)
    worker.start()

    # Wait until the worker is actually inside the blocking decode.
    assert decode_entered.wait(timeout=5.0), "decode never entered"

    # Now simulate "user loaded Track B" on the main thread. This must
    # bump `_load_gen` while the worker is still suspended.
    pre_gen = sess._load_gen
    sess.load_source(src_wav)
    assert sess._load_gen > pre_gen

    # Release the worker. Its swap must observe the gen bump and be discarded.
    decode_release.set()
    worker.join(timeout=5.0)
    assert not worker.is_alive(), "worker did not finish"

    results = results_box["r"]
    # Every stem in the discarded result reports "superseded".
    assert set(results) == set(STEM_NAMES)
    assert all(v == "superseded" for v in results.values()), results
    # `_stem_buffers` was NOT mutated — every slot remains None.
    for name in STEM_NAMES:
        assert sess._stem_buffers[name] is None, (
            f"stale Track A stem leaked into Track B for {name!r}"
        )


def test_seek_stems_mode_clamps_to_longest_stem(spy_stream, tmp_path, tiny_wav):
    """In stems mode, seek must clamp to the longest loaded stem's length,
    not the source length."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    # tiny_wav is ~0.1s. Build a stem ~0.2s long (twice as long) so the
    # clamp difference is observable.
    sess.load_source(tiny_wav)
    sr = 48000
    long_vocals = tmp_path / "long_vocals.wav"
    _write_stem_wav(long_vocals, sr=sr, n=sr * 2 // 10, amplitude=0.1)  # ~0.2s
    sess.load_stems({"vocals": long_vocals})
    actual_mode = sess.set_mode("stems")
    assert actual_mode == "stems"

    # Seek to 0.18s — past source end (0.1s) but within the long stem.
    sess.seek(0.18)
    # Without the fix, this would clamp to _source_n_samples (~4800).
    # With the fix, it clamps to the longest stem (~9600), so we land at
    # the requested sample.
    expected = int(round(0.18 * 48000))
    assert sess._play_offset == expected, (
        f"expected play_offset={expected} (0.18s), got {sess._play_offset}"
    )


# ---------------------------------------------------------------------------
# Phase 4 — Exclusive open passes WasapiSettings(exclusive=True)
# ---------------------------------------------------------------------------


def test_open_with_exclusive_passes_wasapi_settings(spy_stream):
    """`exclusive=True` must construct OutputStream with
    `extra_settings=sd.WasapiSettings(exclusive=True)`. We assert the
    settings object's type rather than identity — WasapiSettings doesn't
    define __eq__, and constructing it twice yields distinct instances."""
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000, exclusive=True)
    inst = spy_stream.last_instance
    assert inst is not None
    assert inst.extra_settings is not None
    assert isinstance(inst.extra_settings, sd.WasapiSettings)


def test_open_with_exclusive_false_passes_none_extra_settings(spy_stream):
    """Default (Shared) open must keep extra_settings=None — Phase 2
    contract preserved."""
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000, exclusive=False)
    inst = spy_stream.last_instance
    assert inst.extra_settings is None


def test_open_reopens_when_exclusive_flag_changes(spy_stream):
    """Idempotency must consider the `exclusive` flag — opening Shared
    then Exclusive on the same device+rate must close-and-reopen."""
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000, exclusive=False)
    first = spy_stream.last_instance
    sess.open(device_index=3, samplerate=48000, exclusive=True)
    second = spy_stream.last_instance
    assert second is not first
    assert first.close_called == 1
    assert second.extra_settings is not None
    assert isinstance(second.extra_settings, sd.WasapiSettings)


def test_open_with_identical_exclusive_params_is_idempotent(spy_stream):
    """Same device, rate, exclusive → no reopen."""
    sess, _ = _new_session()
    sess.open(device_index=3, samplerate=48000, exclusive=True)
    first = spy_stream.last_instance
    sess.open(device_index=3, samplerate=48000, exclusive=True)
    assert spy_stream.last_instance is first


def test_no_allocations_in_stem_callback_at_scale(spy_stream, tmp_path, tiny_wav):
    """Extrapolated allocation budget: 1000 callbacks @ 480 frames must stay
    well under the per-call dict-allocation budget that the old four-dict
    callback would burn. Validates Fix 2 — pre-allocated numpy arrays."""
    import tracemalloc

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    from webui.audio_backend.stream import STEM_NAMES
    paths = _make_stem_paths(
        tmp_path, amplitudes={n: 0.1 for n in STEM_NAMES}
    )
    sess.load_stems(paths)
    sess.set_mode("stems")
    sess.play()
    inst = spy_stream.last_instance
    pre_outdata = np.zeros((480, 2), dtype=np.float32)
    time_info = SimpleNamespace(
        inputBufferAdcTime=0.0, currentTime=0.995, outputBufferDacTime=1.0
    )
    # Warm-up.
    for _ in range(10):
        inst.callback(pre_outdata, 480, time_info, 0)
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()
    # 1000 callbacks ≈ 16.6 s of audio at 60 Hz block rate. The old code
    # path would allocate ~4 dicts × 1000 = 4000 dicts → tens of MB. The
    # new path allocates nothing measurable.
    for _ in range(1000):
        inst.callback(pre_outdata, 480, time_info, 0)
    snap_after = tracemalloc.take_snapshot()
    diff = snap_after.compare_to(snap_before, "lineno")
    total_bytes = sum(stat.size_diff for stat in diff if stat.size_diff > 0)
    tracemalloc.stop()
    # 200 KB ceiling for 1000 callbacks — well below the old per-callback
    # dict allocation budget (~4 dicts × ~280 bytes × 1000 ≈ 1.1 MB).
    assert total_bytes < 200_000, (
        f"stems callback allocated {total_bytes} bytes over 1000 calls"
    )


# ---------------------------------------------------------------------------
# Phase 5 — loop wrap + clear
# ---------------------------------------------------------------------------


def test_set_loop_clamps_and_stores(spy_stream):
    """set_loop(2.0, 5.0) @ 48 kHz → loop_start_sample=96000, loop_end_sample=240000."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.set_loop(2.0, 5.0)
    assert sess._loop_start_sample == 96000
    assert sess._loop_end_sample == 240000


def test_set_loop_enforces_min_one_sample(spy_stream):
    """If end <= start, callback contract requires end > start; we clamp to
    start+1 so the wrap detection still has a well-formed region."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.set_loop(2.0, 2.0)
    assert sess._loop_start_sample == 96000
    assert sess._loop_end_sample == 96001


def test_set_loop_negative_start_clamped_to_zero(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.set_loop(-0.5, 1.0)
    assert sess._loop_start_sample == 0
    assert sess._loop_end_sample == 48000


def test_set_loop_requires_open(spy_stream):
    sess, _ = _new_session()
    with pytest.raises(RuntimeError):
        sess.set_loop(0.0, 1.0)


def test_clear_loop_resets_both_to_none(spy_stream):
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.set_loop(0.5, 1.5)
    sess.clear_loop()
    assert sess._loop_start_sample is None
    assert sess._loop_end_sample is None


def test_callback_wraps_at_loop_end_sample_accurate(spy_stream, tmp_path):
    """Source mode: tiny loop region; drive callbacks crossing the wrap and
    assert play_offset lands inside the loop region post-wrap.

    Build a longer source (0.5 s @ 48 kHz = 24000 samples) so the loop
    region has room to be both pre-wrap and post-wrap.
    """
    sr = 48000
    n = sr // 2  # 0.5 s
    t = np.arange(n) / sr
    data = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    p = tmp_path / "long.wav"
    sf.write(str(p), data, sr, subtype="FLOAT")

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=sr)
    sess.load_source(p)
    sess.play()

    # Loop region: [10 ms, 20 ms) = samples [480, 960).
    sess.set_loop(0.010, 0.020)
    # Position play just before loop_end so the next callback crosses.
    # We want offset=460, frames=480, loop_end=960 → no wrap yet.
    # Then offset=940, frames=480, loop_end=960 → wrap after 20 frames.
    sess._play_offset = 940

    inst = spy_stream.last_instance
    outdata = np.zeros((480, 2), dtype=np.float32)
    time_info = SimpleNamespace(
        inputBufferAdcTime=0.0, currentTime=0.995, outputBufferDacTime=1.0,
    )
    inst.callback(outdata, 480, time_info, 0)
    # first_n = loop_end - offset = 960 - 940 = 20
    # second_n = 480 - 20 = 460
    # play_offset post-wrap = loop_start + second_n = 480 + 460 = 940
    assert sess._play_offset == 940, (
        f"expected play_offset to land at loop_start+second_n=940, got "
        f"{sess._play_offset}"
    )
    # Sanity: first 20 frames came from pre-wrap region (offset 940..959);
    # next 460 from loop_start..loop_start+460.
    assert np.allclose(outdata[:20], sess._source_buf[940:960])
    assert np.allclose(outdata[20:], sess._source_buf[480:940])


def test_callback_no_wrap_when_loop_inactive(spy_stream, tiny_wav):
    """clear_loop, drive callback at end-of-buffer → no wrap, ended event fires."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    sess.play()
    sess.set_loop(0.01, 0.02)
    sess.clear_loop()  # back to no loop
    inst = spy_stream.last_instance
    # Advance play_offset to one frame before EOF.
    n_total = sess._source_n_samples
    sess._play_offset = n_total - 100
    _drive_callback(inst, frames=480, dac_time=1.0)
    # First callback drains the rest of the buffer (no wrap, no loop).
    assert sess._play_offset == n_total
    # Second callback hits the end-of-buffer branch.
    _drive_callback(inst, frames=480, dac_time=2.0)
    assert sess._playing is False
    item = sess._event_queue.get_nowait()
    assert item == ("ended", None)


def test_callback_anchor_resets_on_loop_wrap(spy_stream, tmp_path):
    """After a source-mode wrap, the anchor must be reset to (loop_start_t,
    dac_time + first_n/sr) so the client's clock-tick snaps to loop_start."""
    sr = 48000
    n = sr // 2
    t = np.arange(n) / sr
    data = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    p = tmp_path / "long.wav"
    sf.write(str(p), data, sr, subtype="FLOAT")

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=sr)
    sess.load_source(p)
    sess.play()
    sess.set_loop(0.010, 0.020)  # samples [480, 960)
    sess._play_offset = 940
    # First, drive a callback with a known DAC time so we can predict the
    # post-wrap anchor.
    inst = spy_stream.last_instance
    outdata = np.zeros((480, 2), dtype=np.float32)
    time_info = SimpleNamespace(
        inputBufferAdcTime=0.0, currentTime=0.995, outputBufferDacTime=1.0,
    )
    inst.callback(outdata, 480, time_info, 0)
    # Expected anchor: song_t = loop_start / sr = 480/48000 = 0.01;
    # audio_t = dac_time + first_n/sr = 1.0 + 20/48000 ≈ 1.0004166.
    assert sess._anchor is not None
    assert abs(sess._anchor.song_t - 0.01) < 1e-9
    assert abs(sess._anchor.audio_t - (1.0 + 20.0 / sr)) < 1e-9


def test_callback_loop_wrap_stems_mode_one_block_lag(spy_stream, tmp_path, tiny_wav):
    """Stems mode: at the wrap, the block truncates at loop_end (zero-padded)
    and the NEXT callback resumes from loop_start. The 1-block (~10 ms) lag
    is the documented stems-mode minimum (see _callback comment)."""
    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=48000)
    sess.load_source(tiny_wav)
    # Make a 0.5 s stem so the loop region has room.
    sr = 48000
    p = tmp_path / "long_vocals.wav"
    _write_stem_wav(p, sr=sr, n=sr // 2, amplitude=0.3)
    sess.load_stems({"vocals": p})
    sess.set_mode("stems")
    sess.play()
    sess.set_loop(0.010, 0.020)  # samples [480, 960), loop_length=480
    sess._play_offset = 940
    inst = spy_stream.last_instance
    out = _drive_callback(inst, frames=480, dac_time=1.0)
    # play_offset uses modular arithmetic against loop_length so a short
    # loop region still lands inside [loop_start, loop_end): for offset=940,
    # frames=480, ls=480, le=960, first_n=20, loop_length=480:
    #   _play_offset = ls + ((frames - first_n) % loop_length)
    #                = 480 + (460 % 480) = 480 + 460 = 940
    # The next callback's wrap detection (offset < loop_end) then trips
    # again on this offset.
    assert sess._play_offset == 940, (
        f"stems-mode wrap should land inside loop region (modular arithmetic), got "
        f"{sess._play_offset}"
    )
    # _anchor_pending must be True so the next callback re-anchors at the
    # loop-start position.
    assert sess._anchor_pending is True
    # First 20 frames carry stem audio; rest is zero-padded.
    # Stem amplitude is 0.3, gain ramps from 0 → 1 with tau=10 ms; for a
    # 20-frame slice the gain is tiny. Just assert the trailing zeros.
    assert np.all(out[20:] == 0.0), "tail of wrap-block must be zero-padded"


def test_loop_wrap_with_short_loop_region_smaller_than_block(spy_stream, tmp_path):
    """Loop length shorter than the audio block must wrap correctly within
    one callback invocation; play_offset must land inside the loop region.

    Regression for the Phase 5 polish fix: previously `second_n` was clamped
    against `frames - first_n` and EOF only — NOT against `loop_end -
    loop_start`. So a loop region of, say, 100 samples with a 480-frame
    callback read past loop_end into post-loop audio, and `_play_offset`
    landed at or past loop_end. The next callback's wrap detection
    (`offset < loop_end`) then silently skipped and the loop broke.

    Build a 2000-sample source, set a 100-sample loop region (samples
    [100, 200), loop_length=100), position play just before the wrap, and
    drive one 480-frame callback. After the callback:
      * `_play_offset` must be in [100, 200).
      * `outdata` must contain audio everywhere (no garbage past loop_end
        read from post-loop region).
    """
    sr = 48000
    n = 2000
    # Distinct values per sample so we can spot reads from post-loop audio:
    # samples 200..1999 are 1.0; samples [100, 200) (the loop region) are
    # 0.5; samples [0, 100) are 0.25. If the wrap reads past loop_end, we'll
    # see 1.0 in outdata where we expect 0.5.
    data = np.full(n, 1.0, dtype=np.float32)
    data[100:200] = 0.5
    data[:100] = 0.25
    p = tmp_path / "short_loop_src.wav"
    sf.write(str(p), data, sr, subtype="FLOAT")

    sess, _ = _new_session()
    sess.open(device_index=0, samplerate=sr)
    sess.load_source(p)
    sess.play()

    # Loop region: samples [100, 200) — loop_length=100, much shorter than
    # a 480-frame callback block.
    sess.set_loop(100.0 / sr, 200.0 / sr)
    # Position play just before loop_end so the next callback crosses.
    # offset=150, frames=480, le=200 → first_n=50; then we need to wrap
    # (480 - 50) = 430 samples within a 100-sample loop = 4 full periods +
    # 30 samples of partial. New _play_offset = 100 + (430 % 100) = 130.
    sess._play_offset = 150

    inst = spy_stream.last_instance
    outdata = np.zeros((480, 2), dtype=np.float32)
    time_info = SimpleNamespace(
        inputBufferAdcTime=0.0, currentTime=0.995, outputBufferDacTime=1.0,
    )
    inst.callback(outdata, 480, time_info, 0)

    # Sanity: play_offset must land inside the loop region.
    assert 100 <= sess._play_offset < 200, (
        f"play_offset {sess._play_offset} must be inside loop [100, 200) "
        f"after a short-loop wrap; otherwise the next callback skips wrap "
        f"detection and the loop silently breaks"
    )
    # Specifically: 100 + (430 % 100) = 130.
    assert sess._play_offset == 130

    # No garbage past loop_end: outdata must not contain 1.0 anywhere
    # (only 0.25 and 0.5 are in [0, 200), which is the only legal read
    # range; the value 1.0 would mean we read post-loop audio).
    # outdata is stereo (replicated mono) — channel 0 is sufficient.
    assert not np.any(outdata[:, 0] >= 0.99), (
        "outdata contains values from post-loop audio — wrap was not "
        "clamped against loop_length"
    )
    # First 50 frames came from [150, 200) which is the loop tail (0.5).
    assert np.all(outdata[:50, 0] == 0.5)
    # The remaining 430 frames must contain only loop-region values (0.5).
    assert np.all(outdata[50:, 0] == 0.5), (
        "post-wrap segments must only read from the loop region"
    )

