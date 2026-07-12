"""Per-stem presence detector for melodic htdemucs_6s stems.

Addresses the fundamental problem that htdemucs always emits all 6 stems even
on tracks that don't have those instruments — leaked content from other
instruments produces phantom MIDI events that clutter the piano-roll.

Three independent signals gate each stem. The stem is marked ``transcribed:
false`` if **any** signal trips its threshold.

Signal A — Inter-stem masking ratio
    stem_rms_db − max(rms_db of other melodic stems). If the stem is far quieter
    than the loudest other stem it's effectively inaudible / leakage-only.
    Threshold: < −40 dB (tuned empirically 2026-05-02 — see
    MASKING_THRESHOLD_DB docstring for the full rationale and corpus data).

Signal B — Active-frame ratio (noise gate)
    Fraction of 100 ms frames where per-frame RMS > −40 dBFS. If fewer than 1%
    of frames are active, the stem contains only transient bleed.
    Threshold: < 0.01 (1% of frames; tuned 2026-05-02 — see
    ACTIVE_FRAME_RATIO_THRESHOLD docstring).
    Rationale for the −40 dBFS floor itself: pro-audio noise gates default to
    −40 dBFS (SSL channel strip, ProTools). Plomp's auditory integration window
    is ~100–200 ms (justifies 100 ms frame).

Signal C — In-band energy fraction
    Bandpass the stem to its core frequency range (4th-order Butterworth,
    sosfiltfilt). If in-band RMS / total RMS < 0.5, out-of-band content
    dominates → leakage. Not applied to "other" (no defined band).
    Threshold: < 0.5 (50% in-band).
    Rationale: instrument fundamental ranges are physical properties; below 50%
    means the stem is dominated by overtones from another instrument or noise.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

# ---------------------------------------------------------------------------
# Module-level constants (public — importable directly for tests / diagnostics)
# ---------------------------------------------------------------------------

MASKING_THRESHOLD_DB: float = -40.0
"""Signal A: stem gated when (stem_rms_db − max_other_rms_db) < this value.

Tuned 2026-05-02 from −26 dB (Zwicker-Fastl simultaneous-masking) to −40 dB after
an 8-track corpus survey showed the original threshold misclassified
sparse-but-real instruments. The Zwicker-Fastl 24–30 dB figure describes two
*concurrent* tones, but `_rms_db()` averages over the whole track including
silence — a real instrument that plays 25% of the time has its track-RMS
dragged down ~6 dB before any actual masking. Empirical separation: every
genuine absence in the survey sits at ≤ −45 dB; the two false-positive
suppressions (Olivia Dean acoustic guitar, Flunk piano) sit at −27 to −28 dB.
−40 dB is the midpoint with safety margin both ways."""

ACTIVE_FRAME_THRESHOLD_DBFS: float = -40.0
"""Signal B: frames below this RMS-dBFS level are counted as 'silent'."""

ACTIVE_FRAME_DURATION_SEC: float = 0.100
"""Signal B: frame length in seconds for the per-frame noise gate."""

ACTIVE_FRAME_RATIO_THRESHOLD: float = 0.01
"""Signal B: stem gated when fraction of active frames < this value.

Tuned 2026-05-02 from 0.05 to 0.01 after the same corpus survey: sparse-but-real
comping/pad instruments (Olivia Dean acoustic guitar at 2.4%, Flunk piano at
2.2%) sit between 1% and 5%; truly absent stems reproducibly sit at 0.0–0.2%.
The original 5% justification (\"any real instrument plays 30–40% of a song\")
holds for vocals/bass/drums but not for instruments that only enter in the
bridge or play percussive stabs at sub-bar density."""

IN_BAND_FRACTION_THRESHOLD: float = 0.5
"""Signal C: stem gated when in_band_rms / total_rms < this value."""

PHANTOM_NOTE_MAX_DUR_SEC: float = 0.060
"""Per-note cull 3: notes shorter than this AND quieter than
PHANTOM_NOTE_MAX_VEL are perceptually clicks (below the ~50 ms onset-fusion
window of Bregman's auditory scene analysis), not musical events."""

PHANTOM_NOTE_MAX_VEL: float = 0.2
"""Per-note cull 3: velocity (0..1) ceiling for clicks. 0.2 ≈ −14 dB below the
loudest note of the stem; co-occurring with sub-60 ms duration this is the
characteristic signature of basic-pitch transient false positives."""

LOG_EPS: float = 1e-12
"""Added inside log10() to safely handle silent input (matches the precedent in
analyze/stages/drums.py and analyze/derived/vocal_range.py)."""

SILENT_DBFS_FLOOR: float = -120.0
"""Returned by _rms_db() when the audio file is empty — well below any
real-world stem energy and below ACTIVE_FRAME_THRESHOLD_DBFS so all gates
trip naturally."""

CORE_BANDS_HZ: dict[str, Optional[tuple[int, int]]] = {
    "vocals": (80, 1100),
    "bass":   (30, 330),
    "guitar": (80, 1320),
    "piano":  (27, 4200),
    "other":  None,   # no defined fundamental band — Signal C skipped
}

# Per-instrument MIDI pitch ranges used by the per-note phantom filter.
NOTE_MIDI_RANGES: dict[str, tuple[int, int]] = {
    "vocals": (36, 96),    # C2 – C7
    "bass":   (24, 67),    # C1 – G4
    "guitar": (40, 100),   # E2 – E7
    "piano":  (21, 108),   # A0 – C8 (full keyboard)
    "other":  (21, 108),   # full keyboard
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rms_db(wav_path: Path) -> float:
    """Streaming RMS of a WAV file → dBFS.

    Mirrors ``_wav_rms()`` in vocal_range.py (blocksize=65536, float32) but
    returns dBFS directly and uses numpy vectorisation for the sum-of-squares.
    """
    sum_sq = 0.0
    n_samples = 0
    with sf.SoundFile(str(wav_path)) as f:
        for block in f.blocks(blocksize=65536, dtype="float32"):
            arr = np.asarray(block, dtype=np.float64)
            sum_sq += float(np.sum(arr ** 2))
            n_samples += arr.size
    if n_samples == 0:
        return SILENT_DBFS_FLOOR
    rms = math.sqrt(sum_sq / n_samples)
    return 20.0 * math.log10(rms + LOG_EPS)


def _active_frame_ratio(y_mono: np.ndarray, sr: int) -> float:
    """Fraction of 100 ms frames with per-frame RMS > ACTIVE_FRAME_THRESHOLD_DBFS.

    Reads the full mono signal at once (these stems are ~50 MB, fits easily in
    RAM). Frames that don't fill a complete window are dropped.
    """
    frame_len = int(ACTIVE_FRAME_DURATION_SEC * sr)
    if frame_len == 0 or len(y_mono) == 0:
        return 0.0
    n_frames = len(y_mono) // frame_len
    if n_frames == 0:
        return 0.0
    frames = y_mono[: n_frames * frame_len].reshape(n_frames, frame_len)
    # Per-frame RMS (broadcast over samples dimension)
    frame_rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    frame_db = 20.0 * np.log10(frame_rms + LOG_EPS)
    active = float(np.sum(frame_db > ACTIVE_FRAME_THRESHOLD_DBFS))
    return active / n_frames


def _in_band_fraction(y_mono: np.ndarray, sr: int, band_hz: tuple[int, int]) -> float:
    """Ratio of in-band RMS to total RMS after a 4th-order Butterworth bandpass.

    Same SOS + sosfiltfilt pattern as analyze/stages/drums.py:222-223.
    """
    import scipy.signal as sps

    lo, hi = band_hz
    # Clamp to Nyquist; scipy will raise if either edge ≥ Nyquist.
    nyq = sr / 2.0
    lo_clamped = max(lo, 1)
    hi_clamped = min(hi, nyq - 1)
    if lo_clamped >= hi_clamped:
        return 1.0  # degenerate band — can't gate on bad numerics

    sos = sps.butter(4, [lo_clamped, hi_clamped], btype="bandpass", fs=sr, output="sos")
    y64 = y_mono.astype(np.float64)
    y_bp = sps.sosfiltfilt(sos, y64)

    total_rms = float(np.sqrt(np.mean(y64 ** 2)))
    if total_rms < LOG_EPS:
        # Silent stem — no meaningful ratio, don't gate on this signal.
        # Signal B (active_frame_ratio) is the safety net that catches silence.
        return 1.0
    in_band_rms = float(np.sqrt(np.mean(y_bp ** 2)))
    return in_band_rms / total_rms


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_stems_rms_db(stem_wavs: dict[str, Path]) -> dict[str, float]:
    """Compute RMS-dBFS for each stem WAV, streaming. Returns name → dBFS map.

    Skips entries whose path doesn't exist. Used by ``pipeline._enrich_stems``
    to amortize RMS streaming across the per-stem presence-gate calls (each
    melodic stem appears once as the test stem and N−1 times as an "other"
    stem; without caching, each WAV is RMS-scanned N times).
    """
    out: dict[str, float] = {}
    for name, path in stem_wavs.items():
        if path is None or not path.exists():
            continue
        out[name] = _rms_db(path)
    return out


def measure_stem_presence(
    stem_wav: Path,
    other_stem_wavs: dict[str, Path],
    stem_name: str,
    *,
    precomputed_rms_db: dict[str, float] | None = None,
) -> dict:
    """Compute 3-signal presence metrics for a single melodic stem.

    Parameters
    ----------
    stem_wav:
        Path to the stem WAV under test.
    other_stem_wavs:
        Mapping ``{stem_name: path}`` for ALL other melodic stems (i.e. the
        four stems that are NOT the one under test). Drums should be excluded.
    stem_name:
        One of ``"vocals" | "bass" | "guitar" | "piano" | "other"``.

    Returns
    -------
    dict with the following keys:

    ``stem_rms_db``
        RMS level of the test stem in dBFS.
    ``max_other_rms_db``
        Highest RMS level (dBFS) among the other melodic stems, or ``None`` if
        no other stems were supplied.
    ``masking_ratio_db``
        ``stem_rms_db − max_other_rms_db``.  ``None`` when ``max_other_rms_db``
        is ``None``.
    ``active_frame_ratio``
        Fraction of 100 ms frames where per-frame RMS > −40 dBFS (Signal B).
    ``in_band_fraction``
        ``in_band_rms / total_rms`` after bandpass to the instrument's core
        frequency range.  ``None`` for *other* (no defined band).
    ``band_hz``
        The ``[lo, hi]`` band used for Signal C, or ``None``.
    ``thresholds``
        Dict of the three threshold values for reference.
    ``gates_tripped``
        Subset of ``["masking", "active", "in_band"]`` listing which signals
        fired.
    ``transcribed``
        ``False`` iff any gate was tripped.
    ``reason``
        Human-readable explanation string if ``transcribed`` is ``False``,
        otherwise ``None``.
    """
    # ---- Signal A: inter-stem masking ratio (streaming) --------------------
    # Use the precomputed RMS map when present to amortize streaming across the
    # per-stem loop in pipeline._enrich_stems. Fall back to a fresh _rms_db()
    # call when an entry is missing — a partial map shouldn't crash the gate.
    if precomputed_rms_db is not None and stem_name in precomputed_rms_db:
        stem_rms_db: float = precomputed_rms_db[stem_name]
    else:
        stem_rms_db = _rms_db(stem_wav)

    max_other_rms_db: Optional[float] = None
    max_other_name: Optional[str] = None
    for other_name, other_path in other_stem_wavs.items():
        if other_path is None or not other_path.exists():
            continue
        if precomputed_rms_db is not None and other_name in precomputed_rms_db:
            db = precomputed_rms_db[other_name]
        else:
            db = _rms_db(other_path)
        if max_other_rms_db is None or db > max_other_rms_db:
            max_other_rms_db = db
            max_other_name = other_name

    masking_ratio_db: Optional[float] = None
    if max_other_rms_db is not None:
        masking_ratio_db = stem_rms_db - max_other_rms_db

    # ---- Signals B + C: load full mono signal once -------------------------
    audio, sr = sf.read(str(stem_wav), dtype="float32")
    if audio.ndim == 2:
        y_mono = audio.mean(axis=1)
    else:
        y_mono = audio

    # Signal B
    active_frame_ratio: float = _active_frame_ratio(y_mono, sr)

    # Signal C
    band_hz = CORE_BANDS_HZ.get(stem_name)
    in_band_fraction: Optional[float] = None
    if band_hz is not None:
        in_band_fraction = _in_band_fraction(y_mono, sr, band_hz)

    # ---- Gate evaluation ---------------------------------------------------
    gates_tripped: list[str] = []
    reason_parts: list[str] = []

    if masking_ratio_db is not None and masking_ratio_db < MASKING_THRESHOLD_DB:
        gates_tripped.append("masking")
        reason_parts.append(
            f"masked by {max_other_name} at {masking_ratio_db:.1f} dB"
        )

    if active_frame_ratio < ACTIVE_FRAME_RATIO_THRESHOLD:
        gates_tripped.append("active")
        reason_parts.append(
            f"active in only {active_frame_ratio * 100:.1f}% of frames"
            f" (gate {ACTIVE_FRAME_THRESHOLD_DBFS:.0f} dBFS)"
        )

    if in_band_fraction is not None and in_band_fraction < IN_BAND_FRACTION_THRESHOLD:
        gates_tripped.append("in_band")
        lo, hi = band_hz  # type: ignore[misc]
        reason_parts.append(
            f"only {in_band_fraction * 100:.0f}% of energy in"
            f" {stem_name} band {lo}-{hi} Hz"
        )

    transcribed: bool = len(gates_tripped) == 0
    reason: Optional[str] = "; ".join(reason_parts) if reason_parts else None

    return {
        "stem_rms_db": round(stem_rms_db, 1),
        "max_other_rms_db": round(max_other_rms_db, 1) if max_other_rms_db is not None else None,
        "masking_ratio_db": round(masking_ratio_db, 1) if masking_ratio_db is not None else None,
        "active_frame_ratio": round(active_frame_ratio, 4),
        "in_band_fraction": round(in_band_fraction, 4) if in_band_fraction is not None else None,
        "band_hz": list(band_hz) if band_hz is not None else None,
        "thresholds": {
            "masking_db": MASKING_THRESHOLD_DB,
            "active_ratio": ACTIVE_FRAME_RATIO_THRESHOLD,
            "in_band_fraction": IN_BAND_FRACTION_THRESHOLD,
        },
        "gates_tripped": gates_tripped,
        "transcribed": transcribed,
        "reason": reason,
    }


def filter_phantom_notes(
    notes_raw: list[dict],
    stem_wav: Path,
    stem_name: str,
) -> list[dict]:
    """Remove phantom MIDI notes from a stem's raw transcription.

    Three culls are applied in order:

    1. **MIDI range cull** — drop notes outside the physical range for this
       instrument (``NOTE_MIDI_RANGES[stem_name]``).
    2. **Per-note noise gate** — for each surviving note, compute the RMS-dBFS
       of ``stem_wav`` audio in ``[t, t + min(dur, 0.1)]``.  Drop if below
       ``ACTIVE_FRAME_THRESHOLD_DBFS``.  Audio is loaded once and sliced by
       sample index.
    3. **Perceptual-insignificance cull** — drop notes where
       ``dur < 0.060 AND vel < 0.2``.

    Parameters
    ----------
    notes_raw:
        List of ``{"t": float, "dur": float, "midi": int, "name": str,
        "vel": float}`` dicts as produced by ``_enrich_stems`` before
        enrichment.
    stem_wav:
        Path to the stem WAV (used for per-note RMS gating).
    stem_name:
        One of ``"vocals" | "bass" | "guitar" | "piano" | "other"``.

    Returns
    -------
    Surviving notes in the same dict shape.
    """
    if not notes_raw:
        return []

    lo_midi, hi_midi = NOTE_MIDI_RANGES.get(stem_name, (21, 108))

    # Cull 1: MIDI range
    notes_range = [n for n in notes_raw if lo_midi <= n["midi"] <= hi_midi]
    if not notes_range:
        return []

    # Load audio once for per-note gating (Cull 2).
    audio, sr = sf.read(str(stem_wav), dtype="float32")
    if audio.ndim == 2:
        y_mono = audio.mean(axis=1).astype(np.float64)
    else:
        y_mono = audio.astype(np.float64)
    total_samples = len(y_mono)

    surviving: list[dict] = []
    for note in notes_range:
        t = float(note["t"])
        dur = float(note["dur"])
        vel = float(note["vel"])

        # Cull 2: per-note noise gate
        window_sec = min(dur, ACTIVE_FRAME_DURATION_SEC)
        start_idx = int(t * sr)
        end_idx = int((t + window_sec) * sr)
        start_idx = max(0, min(start_idx, total_samples))
        end_idx = max(start_idx, min(end_idx, total_samples))
        window = y_mono[start_idx:end_idx]
        if window.size > 0:
            note_rms = float(math.sqrt(float(np.mean(window ** 2))))
            note_db = 20.0 * math.log10(note_rms + LOG_EPS)
            if note_db < ACTIVE_FRAME_THRESHOLD_DBFS:
                continue  # gate fired — silent window
        # If window is empty (note at end of file) we keep the note rather
        # than silently dropping it — audio truncation shouldn't penalise notes.

        # Cull 3: perceptual insignificance
        if dur < PHANTOM_NOTE_MAX_DUR_SEC and vel < PHANTOM_NOTE_MAX_VEL:
            continue

        surviving.append(note)

    return surviving
