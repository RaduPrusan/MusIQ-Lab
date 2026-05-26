"""AudioSession — one PortAudio output stream + source/stems playback.

Phase 3 scope: source mode + 6-stem mixing with per-stem volume / mute /
solo and a mid-playback source↔stems mode toggle. The session owns a single
`sd.OutputStream` and drives it from pre-allocated float32 stereo buffers
(source, plus six per-stem). The PortAudio callback is allocation-free in
steady state and emits "ended" via a `queue.SimpleQueue` (drained by the
WS task on the asyncio loop).

Threading model
---------------
- The WS task (asyncio loop thread) calls `open`/`close`/`load_source`/
  `play`/`pause`/`seek`/`song_t`. These are guarded by `self._lock`.
- The PortAudio callback runs on PortAudio's high-priority thread. It
  acquires the GIL on entry and takes `self._lock` for very short reads
  (offset, anchor, source-buffer reference). It does NOT call
  `np.copyto` / soxr / soundfile / logging / asyncio inside the lock —
  copying the chunk happens after the lock is released to keep the
  critical section bounded.
- `self._event_queue.put_nowait` is the only "outbound" path from the
  callback. sounddevice docs forbid logging / print / `await` inside the
  callback; the queue + drainer task pattern is what the design spec
  pinned.

What this module deliberately does NOT do
-----------------------------------------
- Open Exclusive-mode streams (Phase 4).
- Wrap a loop in-callback (Phase 5).
"""
from __future__ import annotations

import logging
import pathlib
import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
import soxr

from .clock import Anchor, song_t_from_audio_t

log = logging.getLogger(__name__)

# Mirror of webui/static/js/audio/engine.js STEM_NAMES. Order matters only
# for deterministic iteration; the callback mix is commutative.
STEM_NAMES: tuple[str, ...] = ("vocals", "piano", "other", "guitar", "bass", "drums")
# Reverse lookup name → position. Precomputed so the per-block callback
# never has to call `.index()` on the tuple.
_STEM_INDEX: dict[str, int] = {n: i for i, n in enumerate(STEM_NAMES)}
_N_STEMS: int = len(STEM_NAMES)

# Solo-ducking value from web-audio-engine.js:3 (SOLO_DUCK = 0). When any
# stem is soloed, non-soloed stems duck to this gain.
_SOLO_DUCK: float = 0.0

# 10 ms gain-smoothing time constant — matches setTargetAtTime(_, _, 0.01)
# in web-audio-engine.js:199. Used by the per-block one-pole IIR coefficient
# `1 - exp(-frames / (sr × tau))`.
_GAIN_SMOOTH_TAU_SEC: float = 0.010


class AudioSession:
    """One open PortAudio stream + a decoded source buffer.

    Owned by exactly one WebSocket connection. The WS handler calls
    `open` on first `set_device`, `load_source` on `load`, etc. On WS
    disconnect (or app shutdown) the handler calls `close()`.
    """

    def __init__(self, *, event_queue: "queue.SimpleQueue"):
        # Stream + device state -------------------------------------------------
        self._stream: Optional[sd.OutputStream] = None
        self._device_index: Optional[int] = None
        self._samplerate: int = 0
        self._blocksize: int = 0
        # Phase 4: track which mode the current stream was opened in so the
        # idempotency check (and external callers) can inspect it. Mirrors
        # the `exclusive` arg to `open()`.
        self._exclusive: bool = False

        # Source buffer (float32 stereo at device rate). Allocated by
        # `load_source`; kept alive across play/pause cycles until either
        # `load_source` runs again or `close()` is called.
        self._source_buf: Optional[np.ndarray] = None
        self._source_n_samples: int = 0

        # Playback state -------------------------------------------------------
        self._play_offset: int = 0        # next sample to emit
        self._playing: bool = False       # True between play() and pause()/end
        self._anchor: Optional[Anchor] = None
        # When True, the very next callback that emits real samples must
        # record `time_info.outputBufferDacTime` into a fresh Anchor.
        self._anchor_pending: bool = True
        # Frozen song-time read out by `song_t` while not playing.
        self._last_song_pos: float = 0.0

        # Stem buffers — float32 stereo at device rate. None until loaded.
        # Keyed by STEM_NAMES; missing keys are allowed (Stage 9 drums often
        # soft-fail). The callback reads each ref under the lock and skips
        # any None entry from the mix accumulator.
        self._stem_buffers: dict[str, Optional[np.ndarray]] = {n: None for n in STEM_NAMES}

        # Per-stem gain state. `_target_vol` / `_muted` / `_soloed` mirror
        # web-audio-engine.js:14-30; the effective per-block target is
        # computed by `_effective_target()` (truth table at l. 197-198).
        # `_gain_array` is the smoothed value the callback ramps toward
        # the target via a one-pole IIR — start at 0 so the very first
        # callback after play() doesn't pop. Indexed by stem position in
        # STEM_NAMES so the callback can iterate without dict overhead.
        self._target_vol: dict[str, float] = {n: 1.0 for n in STEM_NAMES}
        self._muted: dict[str, bool] = {n: False for n in STEM_NAMES}
        self._soloed: dict[str, bool] = {n: False for n in STEM_NAMES}
        self._gain_array: np.ndarray = np.zeros(len(STEM_NAMES), dtype=np.float32)

        # Pre-allocated scratch for the stems-mode callback. Indexed by stem
        # position in STEM_NAMES. Avoids dict allocations per callback
        # × ~60 Hz that would otherwise produce ~13 MB of dict churn over a
        # 3-min track and risk GC-induced audio glitches.
        self._stem_targets: np.ndarray = np.zeros(len(STEM_NAMES), dtype=np.float32)
        self._stem_gain_snap: np.ndarray = np.zeros(len(STEM_NAMES), dtype=np.float32)
        self._stem_buffer_refs: list = [None] * len(STEM_NAMES)

        # Load-generation counter. Incremented by `load_source` and captured
        # by `load_stems` at the start of its (possibly long) decode loop.
        # The atomic stem swap is discarded if the counter advanced — this
        # prevents Track A's thread-pool decode from landing in a session
        # that has since been re-loaded with Track B.
        self._load_gen: int = 0

        # Active playback mode — "source" or "stems". set_mode() may force
        # this back to "source" if stems mode is requested but no stems are
        # loaded yet (mirrors WebAudioEngine._resolveStartMode).
        self._mode: str = "source"

        # Phase 5 — loop region in sample units. Both None when no loop set.
        # `_loop_start_sample` is inclusive; `_loop_end_sample` is exclusive.
        # Sample units (not seconds) so the per-block wrap test is integer
        # comparison against `offset` and there's no float-rounding ambiguity
        # at the wrap point.
        self._loop_start_sample: Optional[int] = None
        self._loop_end_sample: Optional[int] = None

        # Pre-allocated mix-bus work buffers. Sized to `_max_block` so the
        # callback never allocates. Created in `open()` once samplerate is
        # known. `_mix_buf` is the accumulator; `_tmp_buf` is per-stem
        # scratch. Both are reused every callback.
        self._mix_buf: Optional[np.ndarray] = None
        self._tmp_buf: Optional[np.ndarray] = None
        # PortAudio with blocksize=0 lets the driver pick; on modern WASAPI
        # Shared this is well below 1024. 2048 is a deliberate over-budget.
        self._max_block: int = 2048

        # Thread-safety + IPC --------------------------------------------------
        # The callback runs on PortAudio's high-priority thread; reads of
        # offset / anchor / source-buf-ref are guarded by this lock. The
        # critical section is tiny — we copy out the offset under the lock,
        # then `np.copyto` after releasing. (Releasing before the copy is
        # safe: nothing else can mutate the source buffer mid-playback;
        # `load_source` requires the caller to pause first.)
        self._lock = threading.Lock()
        self._event_queue = event_queue

    # ------------------------------------------------------------------
    # Stream open / close
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        return self._stream is not None

    def is_playing(self) -> bool:
        return self._playing

    def open(
        self,
        *,
        device_index: int,
        samplerate: int,
        blocksize: int = 0,
        exclusive: bool = False,
    ) -> None:
        """Open (or re-open) a WASAPI/MME output stream.

        Idempotent: if a stream is already open with identical params
        (device, samplerate, blocksize, exclusive), this is a no-op. If
        open with different params, the existing stream is closed first.

        `exclusive=True` passes `sd.WasapiSettings(exclusive=True)` as
        `extra_settings` so the stream is opened in WASAPI Exclusive mode.
        Note that PortAudio's MME host API has no Exclusive concept — the
        flag is meaningful only when `device_index` resolves to a WASAPI
        device. The caller (open_chain.open_with_fallback) is responsible
        for never asking MME for Exclusive.

        Raises `sd.PortAudioError` if the device cannot be opened with
        the requested parameters — typically:
          - `-9985 paDeviceUnavailable` (device held in Exclusive by
            another app, or USB Audio Class block-size mismatch)
          - `-9997 paInvalidSampleRate` (Exclusive request at a rate the
            driver won't quantise to its hardware-native format)
        The caller is responsible for the fallback chain.
        """
        if (
            self._stream is not None
            and self._device_index == device_index
            and self._samplerate == samplerate
            and self._blocksize == blocksize
            and self._exclusive == bool(exclusive)
        ):
            return
        # Reopen path. Close any current stream first.
        if self._stream is not None:
            self.close()
        extra_settings = sd.WasapiSettings(exclusive=True) if exclusive else None
        stream = sd.OutputStream(
            device=device_index,
            samplerate=samplerate,
            channels=2,
            dtype="float32",
            blocksize=blocksize,
            callback=self._callback,
            extra_settings=extra_settings,
        )
        # We DON'T call `stream.start()` here; play() does. Opening it now
        # surfaces device-busy errors early without producing silent
        # callbacks before the user has loaded a track.
        self._stream = stream
        self._device_index = device_index
        self._samplerate = samplerate
        self._blocksize = blocksize
        self._exclusive = bool(exclusive)
        # Pre-allocate the mix-bus work buffers once; the callback reuses
        # them every invocation and must never allocate. Float32 stereo
        # matches the stream's `dtype="float32"` + `channels=2`.
        self._mix_buf = np.zeros((self._max_block, 2), dtype=np.float32)
        self._tmp_buf = np.zeros((self._max_block, 2), dtype=np.float32)
        # Reset playback state — a device change implicitly invalidates the
        # decoded buffers (rate may differ); load_source + load_stems are
        # the next steps.
        with self._lock:
            self._source_buf = None
            self._source_n_samples = 0
            self._play_offset = 0
            self._playing = False
            self._anchor = None
            self._anchor_pending = True
            self._last_song_pos = 0.0
            # Drop any previously-loaded stems; their rate may not match
            # the new device. Mute/solo/volume preferences carry over so
            # the user's mix survives a device swap.
            for n in STEM_NAMES:
                self._stem_buffers[n] = None
            self._gain_array.fill(0.0)
            self._mode = "source"
            # Reopening the stream invalidates everything mid-flight — bump
            # the generation so any in-flight load_stems decode is treated
            # as superseded when it attempts its swap.
            self._load_gen += 1

    def close(self) -> None:
        """Close the stream cleanly. Safe to call multiple times."""
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:  # noqa: BLE001 — best-effort teardown
                log.debug("AudioSession.close: stream.stop() raised", exc_info=True)
            try:
                stream.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
                log.debug("AudioSession.close: stream.close() raised", exc_info=True)
        with self._lock:
            self._playing = False
            self._anchor = None
            self._anchor_pending = True

    # ------------------------------------------------------------------
    # Source loading
    # ------------------------------------------------------------------

    def load_source(self, mp3_path: pathlib.Path) -> tuple[float, int]:
        """Decode the MP3, resample to device rate, cache float32 stereo.

        Resets play-offset to 0. Must NOT be called while playing — the
        caller (WS handler) is responsible for pausing first.

        Returns (duration_seconds, source_sample_rate_before_resample).
        """
        if self._stream is None or self._samplerate <= 0:
            raise RuntimeError(
                "AudioSession.load_source: open() must be called first to "
                "establish the device sample rate"
            )
        # soundfile 0.13 reads MP3 via libsndfile MP3 support.
        data, src_sr = sf.read(str(mp3_path), dtype="float32", always_2d=True)
        # Mono → stereo by replication. sf.read returns (n, ch); always_2d
        # makes mono come back as (n, 1) which we expand to (n, 2).
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        # Resample if needed. soxr.resample is a one-shot whole-buffer
        # operation; the design spec pins quality='HQ' for stem-rate
        # conversion (~10.8 ms per 10 s of 48→44.1 kHz).
        if int(src_sr) != int(self._samplerate):
            data = soxr.resample(
                data, int(src_sr), int(self._samplerate), quality="HQ"
            )
        # soxr can return float64 for some inputs; force float32 for the
        # PortAudio stream we opened with dtype="float32".
        if data.dtype != np.float32:
            data = data.astype(np.float32, copy=False)
        # Ensure C-contiguity so the callback's slice copy hits the
        # fastpath.
        if not data.flags["C_CONTIGUOUS"]:
            data = np.ascontiguousarray(data)
        n_samples = int(data.shape[0])
        with self._lock:
            # Bump generation BEFORE installing — any in-flight load_stems
            # decode (Fix 1) sees the bump and discards its swap.
            self._load_gen += 1
            self._source_buf = data
            self._source_n_samples = n_samples
            self._play_offset = 0
            self._last_song_pos = 0.0
            self._anchor = None
            self._anchor_pending = True
        return (n_samples / float(self._samplerate), int(src_sr))

    # ------------------------------------------------------------------
    # Stem loading + mix configuration
    # ------------------------------------------------------------------

    def load_stems(self, stem_paths: dict[str, pathlib.Path]) -> dict[str, str]:
        """Decode + resample each stem WAV to device rate; atomic-swap into
        ``self._stem_buffers``.

        Pure synchronous + (relatively) expensive: the WS layer must call
        this from a thread-pool executor (it does file I/O + soxr resample
        and would otherwise block the asyncio loop). The callback continues
        running through the load — it sees the old `None`/old buffer until
        the swap completes, then picks up the new buffers on the next
        invocation.

        Sample-rate handling: each stem's rate is read via `soundfile.info()`
        per the `audio_stem_cache_format` project-memory note (`summary.json`
        does not carry the stem rate, the WAV header does). If `src_sr` !=
        `self._samplerate`, resample with `soxr.resample(quality='HQ')`.

        Returns a dict mapping stem_name → status string:
          - "loaded"             — decoded + resampled + installed in slot
          - "missing"            — `stem_paths` did not supply this name OR
                                   the path didn't exist on disk
          - "failed: <reason>"   — decode / resample raised; slot stays None

        Partial loads are normal (Stage 9 LarsNet drums often soft-fail).
        """
        if self._stream is None or self._samplerate <= 0:
            raise RuntimeError(
                "AudioSession.load_stems: open() must be called first to "
                "establish the device sample rate"
            )
        # Capture the load generation BEFORE the heavy decode loop. If
        # `load_source` (or `open`) bumps `_load_gen` while we're decoding,
        # the swap below is discarded so Track A's stems can't land in a
        # session that's been re-loaded with Track B. (Fix 1: thread-pool
        # cancellation only cancels the awaiting coroutine, not this
        # synchronous worker; an in-flight prior decode would otherwise
        # silently overwrite the new session's state.)
        with self._lock:
            gen = self._load_gen
        results: dict[str, str] = {}
        new_bufs: dict[str, Optional[np.ndarray]] = {n: None for n in STEM_NAMES}
        for name in STEM_NAMES:
            path = stem_paths.get(name)
            if path is None:
                results[name] = "missing"
                continue
            try:
                p = pathlib.Path(path)
                if not p.is_file():
                    results[name] = "missing"
                    continue
                # Read header for src_sr; avoids decoding twice if we end up
                # only needing the rate (we always decode, but the header
                # tells us whether we'll need to resample).
                info = sf.info(str(p))
                src_sr = int(info.samplerate)
                data, _ = sf.read(str(p), dtype="float32", always_2d=True)
                if data.shape[1] == 1:
                    data = np.repeat(data, 2, axis=1)
                elif data.shape[1] > 2:
                    data = data[:, :2]
                if src_sr != int(self._samplerate):
                    data = soxr.resample(
                        data, src_sr, int(self._samplerate), quality="HQ"
                    )
                if data.dtype != np.float32:
                    data = data.astype(np.float32, copy=False)
                if not data.flags["C_CONTIGUOUS"]:
                    data = np.ascontiguousarray(data)
                new_bufs[name] = data
                results[name] = "loaded"
            except Exception as exc:  # noqa: BLE001 — surface to the client
                log.exception("load_stems: %s failed (path=%s)", name, path)
                results[name] = f"failed: {exc}"
        # Atomic swap. The callback only ever reads `self._stem_buffers[name]`
        # under the lock, so installing the whole dict at once means a single
        # callback either sees the entire old set or the entire new set.
        with self._lock:
            if self._load_gen != gen:
                # A `load_source` (or `open`) happened while we were
                # decoding — discard the swap. Return "superseded" for every
                # stem so the caller (and any tests) can distinguish this
                # from a genuine load.
                return {n: "superseded" for n in STEM_NAMES}
            for n, buf in new_bufs.items():
                self._stem_buffers[n] = buf
                # Reset the smoothed gain when a stem (re)appears so the
                # first stems-mode callback ramps from 0 → target instead of
                # popping from whatever stale value sat in the gain array.
                if buf is not None:
                    self._gain_array[_STEM_INDEX[n]] = 0.0
        return results

    def _has_stems_loaded(self) -> bool:
        """True when at least one stem has decoded.

        Matches WebAudioEngine._readyToMix (web-audio-engine.js:203-205) —
        "mix whatever stems decoded"; we don't require all six.
        """
        with self._lock:
            return any(buf is not None for buf in self._stem_buffers.values())

    @property
    def _stems_n_samples(self) -> int:
        """End-of-track sample count for stems mode. Uses the longest
        loaded stem so a short stem doesn't cut the track off early."""
        return max(
            (buf.shape[0] for buf in self._stem_buffers.values() if buf is not None),
            default=0,
        )

    def set_stem_volume(self, name: str, vol01: float) -> None:
        if name not in STEM_NAMES:
            raise ValueError(f"unknown stem: {name}")
        v = max(0.0, min(1.0, float(vol01)))
        with self._lock:
            self._target_vol[name] = v

    def set_stem_muted(self, name: str, muted: bool) -> None:
        if name not in STEM_NAMES:
            raise ValueError(f"unknown stem: {name}")
        with self._lock:
            self._muted[name] = bool(muted)

    def set_stem_soloed(self, name: str, soloed: bool) -> None:
        if name not in STEM_NAMES:
            raise ValueError(f"unknown stem: {name}")
        with self._lock:
            self._soloed[name] = bool(soloed)

    def set_mode(self, mode: str) -> str:
        """Switch between source / stems mid-playback. Returns the mode
        actually set — may differ from `mode` if the requested buffers
        aren't loaded (falls back to whatever IS available).

        No anchor reset: source and stems share the same `_play_offset`
        and the same sample rate, so the mode switch is glitch-free at
        the next callback boundary modulo the 10 ms gain ramp.
        """
        if mode not in ("source", "stems"):
            raise ValueError(f"invalid mode: {mode}")
        with self._lock:
            requested = mode
            if requested == "stems" and not any(
                buf is not None for buf in self._stem_buffers.values()
            ):
                # Asked for stems but none loaded — fall back to source if
                # available, else keep whatever we had.
                if self._source_buf is not None:
                    mode = "source"
                else:
                    mode = self._mode
            elif requested == "source" and self._source_buf is None:
                # Asked for source but it's not loaded — try stems.
                if any(buf is not None for buf in self._stem_buffers.values()):
                    mode = "stems"
                else:
                    mode = self._mode
            self._mode = mode
            return mode

    def get_mode(self) -> str:
        with self._lock:
            return self._mode

    def _effective_target(self, name: str, any_soloed: bool) -> float:
        """Mirrors web-audio-engine.js:194-201 mute/solo truth table.

        `_SOLO_DUCK` is 0 (matches WebAudio). Caller has already snapped
        `any_soloed` so the per-stem decision is local and lock-free.
        Caller MUST hold `_lock` (this reads `_muted`/`_soloed`/`_target_vol`).
        """
        if self._muted[name]:
            return _SOLO_DUCK
        if any_soloed and not self._soloed[name]:
            return _SOLO_DUCK
        return self._target_vol[name]

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(self) -> None:
        """Start the stream and arm the next callback to take an anchor."""
        if self._stream is None:
            raise RuntimeError("AudioSession.play: stream not open")
        if self._source_buf is None:
            raise RuntimeError("AudioSession.play: no source loaded")
        with self._lock:
            if self._playing:
                return
            # If paused at end-of-buffer, rewind so play() acts as
            # "replay-from-start" (matches WebAudioEngine semantics).
            if self._play_offset >= self._source_n_samples:
                self._play_offset = 0
                self._last_song_pos = 0.0
            self._playing = True
            self._anchor = None
            self._anchor_pending = True
        # `stream.start()` is idempotent in sounddevice — calling on an
        # already-active stream is a no-op. We call it outside the lock
        # so we don't hold the GIL-blocking section longer than needed.
        try:
            self._stream.start()
        except sd.PortAudioError:
            # Roll back the playing flag so song_t() returns the frozen
            # position instead of trying to read stream.time on a dead
            # stream.
            with self._lock:
                self._playing = False
            raise

    def pause(self) -> None:
        """Freeze song-time at the current position and stop the stream."""
        if self._stream is None:
            return
        with self._lock:
            if not self._playing:
                return
            # Sample current song-time from the anchor before we lose the
            # stream. The callback updates `_anchor` on its first run,
            # so if no callback has fired yet (very early pause), fall
            # back to the play offset.
            if self._anchor is not None:
                try:
                    audio_t = float(self._stream.time)
                except sd.PortAudioError:
                    audio_t = self._anchor.audio_t
                self._last_song_pos = song_t_from_audio_t(self._anchor, audio_t)
            else:
                self._last_song_pos = self._play_offset / float(self._samplerate)
            # Snap the play-offset to wherever song-time froze so the next
            # play() / seek() picks up from the right sample. Clamp against
            # whichever buffer set is active so a stems-mode pause near EOF
            # doesn't reset to an out-of-range index for stems shorter than
            # the source.
            if self._mode == "stems":
                clamp_n = max(
                    (
                        b.shape[0]
                        for b in self._stem_buffers.values()
                        if b is not None
                    ),
                    default=self._source_n_samples,
                )
            else:
                clamp_n = self._source_n_samples
            self._play_offset = max(
                0,
                min(
                    clamp_n,
                    int(round(self._last_song_pos * float(self._samplerate))),
                ),
            )
            self._playing = False
            self._anchor = None
            self._anchor_pending = True
        try:
            self._stream.stop()
        except sd.PortAudioError:
            log.debug("AudioSession.pause: stream.stop() raised", exc_info=True)

    def seek(self, song_t: float) -> None:
        """Move the play-offset to `song_t` seconds; resume if was playing."""
        if self._stream is None:
            raise RuntimeError("AudioSession.seek: stream not open")
        if self._source_buf is None:
            raise RuntimeError("AudioSession.seek: no source loaded")
        was_playing = self._playing
        if was_playing:
            self.pause()
        song_t = max(0.0, float(song_t))
        offset = int(round(song_t * float(self._samplerate)))
        with self._lock:
            # Mode-aware clamp. In stems mode, end-of-track is the longest
            # loaded stem, not the source length — mirrors the clamp in
            # `pause()`. (Fix 3: previously this always clamped to
            # `_source_n_samples`, so a stems-mode seek to a position past
            # the source length but within stem range got truncated.)
            if self._mode == "stems":
                clamp_n = max(
                    (
                        b.shape[0]
                        for b in self._stem_buffers.values()
                        if b is not None
                    ),
                    default=self._source_n_samples,
                )
            else:
                clamp_n = self._source_n_samples
            self._play_offset = max(0, min(clamp_n, offset))
            self._last_song_pos = self._play_offset / float(self._samplerate)
            self._anchor = None
            self._anchor_pending = True
        if was_playing:
            self.play()

    # ------------------------------------------------------------------
    # Loop region (Phase 5)
    # ------------------------------------------------------------------

    def set_loop(self, start_song_t: float, end_song_t: float) -> None:
        """Record a sample-accurate loop region.

        `start_song_t` / `end_song_t` are seconds. We convert to sample
        units once here so the per-block callback compares integers (no
        float-rounding at the wrap point). The callback also clamps the
        end against the active buffer length on the fly, so a loop region
        that exceeds the current buffer is harmless — it just never wraps.

        Caller contract: start < end. If end <= start, we clamp end to
        start+1 so the loop is at least one sample long; that defends the
        callback against a UI race where the user dragged the end past
        the start.
        """
        if self._samplerate <= 0:
            raise RuntimeError(
                "AudioSession.set_loop: open() must be called first to "
                "establish the device sample rate"
            )
        s = max(0, int(round(float(start_song_t) * float(self._samplerate))))
        e = max(s + 1, int(round(float(end_song_t) * float(self._samplerate))))
        with self._lock:
            self._loop_start_sample = s
            self._loop_end_sample = e

    def clear_loop(self) -> None:
        with self._lock:
            self._loop_start_sample = None
            self._loop_end_sample = None

    # ------------------------------------------------------------------
    # Stream-info introspection (Phase 5: Settings UI latency display)
    # ------------------------------------------------------------------

    @property
    def output_latency(self) -> float:
        """Output latency reported by PortAudio after open. 0.0 if not open.

        sounddevice surfaces the driver-reported output latency on the
        Stream object as `.latency` (a float in seconds). On WASAPI Shared
        this is typically ~10 ms; on WASAPI Exclusive on a USB-class device
        like the BEHRINGER FLOW 8 it can drop to ~3-4 ms.
        """
        stream = self._stream
        if stream is None:
            return 0.0
        try:
            return float(getattr(stream, "latency", 0.0) or 0.0)
        except Exception:  # noqa: BLE001 — defensive read of driver-reported attr
            return 0.0

    @property
    def blocksize(self) -> int:
        """Actual block size in frames. PortAudio picks this when blocksize=0
        was passed to open()."""
        stream = self._stream
        if stream is None:
            return 0
        try:
            return int(getattr(stream, "blocksize", 0) or 0)
        except Exception:  # noqa: BLE001
            return 0

    # ------------------------------------------------------------------
    # Clock readout (from the WS task)
    # ------------------------------------------------------------------

    @property
    def song_t(self) -> float:
        """Current song-time in seconds (linear extrapolation from anchor)."""
        with self._lock:
            if not self._playing or self._anchor is None or self._stream is None:
                return self._last_song_pos
            anchor = self._anchor
        # Read stream.time outside the lock — it's safe per sounddevice
        # docs for the life of an active stream.
        try:
            audio_t = float(self._stream.time)
        except sd.PortAudioError:
            return self._last_song_pos
        return song_t_from_audio_t(anchor, audio_t)

    def stream_time(self) -> float:
        """Best-effort read of the underlying stream clock."""
        if self._stream is None:
            return 0.0
        try:
            return float(self._stream.time)
        except sd.PortAudioError:
            return 0.0

    @property
    def duration(self) -> float:
        if self._source_buf is None or self._samplerate <= 0:
            return 0.0
        return self._source_n_samples / float(self._samplerate)

    # ------------------------------------------------------------------
    # PortAudio callback (high-priority thread)
    # ------------------------------------------------------------------

    def _callback(self, outdata, frames, time_info, status):  # pragma: no cover — exercised via direct invocation
        # NO allocations. NO print/logging. The single allowed "side-effect"
        # is `event_queue.put_nowait` (SimpleQueue is documented thread-safe
        # and non-blocking).
        #
        # Phase 3: two branches — source mode copies the source buffer slice;
        # stems mode runs the gain-smoothed mix accumulator using the
        # pre-allocated `_mix_buf` / `_tmp_buf`. The lock-critical section
        # snapshots refs + offsets only; heavy ops (copyto, multiply, add)
        # happen lock-free.
        with self._lock:
            playing = self._playing
            offset = self._play_offset
            anchor_pending = self._anchor_pending
            samplerate = self._samplerate
            mode = self._mode

            if not playing:
                outdata.fill(0.0)
                return

            # Compute end-of-track based on the active mode. Source mode keeps
            # Phase 2 behaviour exactly; stems mode uses the longest loaded
            # stem (mirrors WebAudioEngine — "mix whatever stems decoded").
            if mode == "source":
                buf_ref = self._source_buf
                n_total = self._source_n_samples
                if buf_ref is None:
                    outdata.fill(0.0)
                    return
            else:
                # mode == "stems"
                buf_ref = None
                # Snapshot the per-stem state for this block into the
                # pre-allocated arrays. Mutations from the WS task between
                # blocks are picked up on the next callback — no need for
                # lock-held mixing. (Fix 2: previously this allocated four
                # Python dicts per callback × ~60 Hz ≈ 13 MB of GC churn
                # over a 3-min track.)
                any_soloed = (
                    self._soloed["vocals"]
                    or self._soloed["piano"]
                    or self._soloed["other"]
                    or self._soloed["guitar"]
                    or self._soloed["bass"]
                    or self._soloed["drums"]
                )
                n_total = 0
                for i, n_ in enumerate(STEM_NAMES):
                    buf_i = self._stem_buffers[n_]
                    self._stem_buffer_refs[i] = buf_i
                    if buf_i is not None:
                        len_i = buf_i.shape[0]
                        if len_i > n_total:
                            n_total = len_i
                    # _effective_target is inlined here to avoid the dict
                    # comprehension allocation; mirrors web-audio-engine.js
                    # mute/solo truth table.
                    if self._muted[n_]:
                        self._stem_targets[i] = _SOLO_DUCK
                    elif any_soloed and not self._soloed[n_]:
                        self._stem_targets[i] = _SOLO_DUCK
                    else:
                        self._stem_targets[i] = self._target_vol[n_]
                # Snapshot smoothed gains. `np.copyto` writes into a
                # preallocated array — no allocation.
                np.copyto(self._stem_gain_snap, self._gain_array)

            n_remaining = n_total - offset
            if n_remaining <= 0:
                # Past end-of-buffer — emit silence, flip playing off, and
                # notify the WS task. Do this inside the lock so two
                # callbacks racing across end-of-buffer can't both fire
                # "ended".
                outdata.fill(0.0)
                self._playing = False
                self._last_song_pos = n_total / float(samplerate) if samplerate > 0 else 0.0
                try:
                    self._event_queue.put_nowait(("ended", None))
                except Exception:
                    # SimpleQueue.put_nowait shouldn't fail, but if it did
                    # there's nothing useful we could do from here — the
                    # stream will fall to silence on the next callback
                    # regardless.
                    pass
                return

            n = frames if frames <= n_remaining else n_remaining

            # ------------------------------------------------------------
            # Phase 5 — loop wrap detection
            # ------------------------------------------------------------
            # Two-tier policy (documented in the design spec):
            #
            # * SOURCE mode: sample-accurate split inside this block. We
            #   write `[offset .. loop_end)` first, then re-anchor and write
            #   `[loop_start .. loop_start + remainder)` into the same
            #   outdata block. No audible click; cursor wraps exactly at
            #   loop_end.
            #
            # * STEMS mode: an acceptable Phase 5 minimum is a 1-block
            #   (~10 ms) lag at the wrap — i.e. truncate this block at
            #   loop_end (zero-padding the rest), snap `_play_offset` to
            #   loop_start, and let the NEXT callback fill from loop_start.
            #   This is what WebAudio does effectively at block boundaries
            #   and the user will not perceive ~10 ms.
            #
            # `loop_split` flags the source-mode two-segment path so the
            # lock-free section below knows to do the second copy.
            loop_split = False
            first_n = 0
            loop_start_local: Optional[int] = None
            loop_end_local: Optional[int] = None
            loop_length_local: int = 0
            ls = self._loop_start_sample
            le = self._loop_end_sample
            if (
                ls is not None
                and le is not None
                and offset < le
                and le - offset <= n
                and 0 <= ls < n_total
            ):
                # Wrap detected inside this block.
                loop_start_local = ls
                loop_end_local = le
                first_n = le - offset
                loop_length_local = le - ls
                if mode == "source":
                    loop_split = True
                    # Source-mode sample-accurate wrap: advance play_offset
                    # to land INSIDE the loop region after the wrap, and
                    # re-anchor INLINE so the JS cursor snaps cleanly to
                    # loop_start at the exact wrap instant.
                    #
                    # `_play_offset` uses modular arithmetic against the
                    # loop length so a very short loop region (shorter than
                    # one block) — which causes multiple wraps within this
                    # same callback — still lands inside [loop_start,
                    # loop_end). Without the modulo, the next callback's
                    # `offset >= loop_end` check would skip wrap detection
                    # and the loop would silently break.
                    self._play_offset = ls + ((frames - first_n) % loop_length_local)
                    dac_time = getattr(time_info, "outputBufferDacTime", 0.0)
                    self._anchor = Anchor(
                        song_t=ls / float(samplerate),
                        audio_t=(
                            float(dac_time) + (first_n / float(samplerate))
                        ),
                        playing=True,
                    )
                    self._anchor_pending = False
                    # Skip the normal anchor + play_offset update at the
                    # bottom of the block — they would clobber the wrap
                    # anchor we just set.
                else:
                    # Stems mode: truncate this block at loop_end, snap to
                    # loop_start for the NEXT callback, force a re-anchor on
                    # the NEXT block. Documented above — accepts ~10 ms lag.
                    #
                    # We DO record an anchor for *this* block if one wasn't
                    # already set (so the partial block's song-time is
                    # accurate during the truncated playback). Order matters:
                    # set the pre-wrap anchor FIRST, then flip _anchor_pending
                    # back to True so the NEXT callback at offset=ls
                    # re-anchors to the loop-start song-time.
                    #
                    # Use modular arithmetic on the would-be-second-segment
                    # length so a short loop (shorter than `frames - first_n`)
                    # still lands the next-callback offset inside the loop
                    # region rather than at loop_start exactly when the
                    # truncated remainder spans more than one loop period.
                    n = first_n
                    if anchor_pending:
                        dac_time = getattr(time_info, "outputBufferDacTime", 0.0)
                        self._anchor = Anchor(
                            song_t=offset / float(samplerate),
                            audio_t=float(dac_time),
                            playing=True,
                        )
                    self._play_offset = ls + ((frames - first_n) % loop_length_local)
                    self._anchor_pending = True
                    # `loop_split` stays False — the lock-free heavy-ops
                    # path falls into the standard stem-mix branch with
                    # `n` already truncated; its `if n < frames: outdata[n:]
                    # .fill(0.0)` zero-pads the wrap remainder.
            else:
                # No wrap this block — fall through to the standard
                # anchor + play_offset update.
                # Snapshot DAC time inside the lock so the anchor update
                # sees a consistent (offset, audio_t) pair.
                if anchor_pending:
                    dac_time = getattr(time_info, "outputBufferDacTime", 0.0)
                    self._anchor = Anchor(
                        song_t=offset / float(samplerate),
                        audio_t=float(dac_time),
                        playing=True,
                    )
                    self._anchor_pending = False

                new_offset = offset + n
                self._play_offset = new_offset

        # ----- Lock-free heavy ops below -------------------------------------
        if mode == "source":
            # Phase 2 path — copy the source buffer slice. Phase 5 may
            # split into multiple segments when a loop wrap straddles the
            # block; when the loop region is shorter than the output block
            # we wrap multiple times within this single callback.
            if loop_split:
                # Segment 1: [offset .. loop_end) — the pre-wrap tail.
                np.copyto(outdata[:first_n], buf_ref[offset:offset + first_n])
                # Subsequent segments: write up to one loop period at a time,
                # wrapping as many times as fits in the remaining block
                # budget. Handles the degenerate case where loop length is
                # shorter than the output block (e.g. a 50 ms loop with a
                # 96 ms block) — without this, the post-wrap copy would
                # read past loop_end into post-loop audio and the next
                # callback's wrap detection would silently miss.
                assert loop_start_local is not None  # narrowed above
                assert loop_length_local > 0
                written = first_n
                while written < frames:
                    chunk = frames - written
                    if chunk > loop_length_local:
                        chunk = loop_length_local
                    np.copyto(
                        outdata[written:written + chunk],
                        buf_ref[loop_start_local:loop_start_local + chunk],
                    )
                    written += chunk
                return
            np.copyto(outdata[:n], buf_ref[offset:offset + n])
            if n < frames:
                outdata[n:].fill(0.0)
            return

        # Stem mix. Pre-allocated buffers; no np.zeros calls in steady state.
        # The block-scoped IIR coefficient is the standard low-pass form;
        # for ~10 ms tau at 48 kHz × 480 frames it yields ~0.63 (one tau).
        if self._mix_buf is None or self._tmp_buf is None:
            # Defensive: open() pre-allocates these. If somehow None, fall
            # back to silence rather than crash the audio thread.
            outdata.fill(0.0)
            return
        if n > self._max_block:
            # Driver picked a blocksize larger than our pre-allocated work
            # buffer. PortAudio with `blocksize=0` on Shared WASAPI does
            # not exceed 1024 in practice; this is a guardrail only.
            outdata.fill(0.0)
            return

        self._mix_buf[:n].fill(0.0)
        sr_t_const = 1.0 - float(
            np.exp(-n / (float(samplerate) * _GAIN_SMOOTH_TAU_SEC))
        )
        # Iterate by index over the pre-allocated snapshot arrays. No dict
        # allocations. (Fix 2.)
        for i in range(_N_STEMS):
            buf = self._stem_buffer_refs[i]
            g = float(self._stem_gain_snap[i])
            tgt = float(self._stem_targets[i])
            if buf is None:
                continue
            stem_len = buf.shape[0]
            if offset >= stem_len:
                # This particular stem has ended; its block contribution is
                # zero. Keep its smoothed gain coasting toward the target so
                # a future re-load doesn't pop.
                self._gain_array[i] = g + sr_t_const * (tgt - g)
                continue
            stem_take = stem_len - offset
            stem_n = n if n <= stem_take else stem_take
            # One-pole smooth toward target. Scalar EMA over the block —
            # 10 ms tau is well below per-block accuracy for any UI gesture.
            g_new = g + sr_t_const * (tgt - g)
            # Float32 array writes are not torn on x86-64 + CPython; the WS
            # task's setters take `_lock` for their own writes and the
            # callback's gain mutations are commutative with theirs (their
            # writes target _target_vol, ours target _gain_array).
            self._gain_array[i] = g_new
            # Multiply this stem's block by the smoothed gain into _tmp_buf,
            # then accumulate into _mix_buf. In-place ops only.
            np.multiply(buf[offset:offset + stem_n], g_new, out=self._tmp_buf[:stem_n])
            np.add(
                self._mix_buf[:stem_n], self._tmp_buf[:stem_n], out=self._mix_buf[:stem_n]
            )
        np.copyto(outdata[:n], self._mix_buf[:n])
        if n < frames:
            outdata[n:].fill(0.0)
