"""Per-note intonation: cents deviation, stability, and confidence.

For each basic-pitch note span, measures:
  - intonation_cents : median cents deviation from the note's MIDI integer,
                      computed over voiced-agreement frames in the middle
                      portion of the note (skipping attack/release transients)
  - stability_cents  : std of the same cents distribution (low = steady,
                      high = vibrato/bend/drift)
  - confidence       : fraction of middle-portion frames that contributed
                      to the measurement
  - n_frames_used    : count of contributing frames

Why the middle portion only
---------------------------
F0 estimators are unreliable in the first 30-50ms (note onset transient,
where vocal-fold vibration is still stabilizing) and in the last ~50ms
(release decay). Measuring only the central window — by default 60% of
the note's duration — yields a much cleaner intonation reading. This
also matches the rationale that a sung note's "true" pitch is what the
singer settles on after the attack, not what the formants do during
articulation.

Why voted-AND-agreeing frames
-----------------------------
Two filters compose to define "trustworthy" frames within the note:
  1. vote_count >= 2 — at least two pitch evidence streams agree this is
     a voiced frame (catches consonants, bleed, breath gaps)
  2. |FCPE - PESTO| < cents_agreement_threshold — the two F0 estimators
     agree within 50¢ on what the actual pitch is (catches octave
     glitches and other estimator-disagreement frames)

The intersection is the set of frames where we have high confidence in
the underlying F0. The fraction of middle-window frames meeting both
criteria is reported as `confidence`.

Octave-fold safety net
----------------------
After computing per-frame cents-from-target, fold into [-600, 600] to
absorb any residual single-octave error that octave correction missed
(rare, but happens when the basic-pitch anchor was itself octave-off).
The intonation reading stays in a musically meaningful range without
being corrupted by stray ±1200¢ outliers in the median.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class NoteIntonation:
    """Pitch-accuracy metadata for a single note.

    `intonation_cents` is float NaN when measurement was impossible
    (note too short, or no voiced-agreement frames in the middle window).
    `confidence` stays in [0, 1] regardless — 0.0 means "no evidence."
    """
    intonation_cents: float
    stability_cents: float
    confidence: float
    n_frames_used: int


def per_note_intonation(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    vote_count: np.ndarray,
    basic_pitch_notes,
    fps: float,
    *,
    min_frames: int = 3,
    cents_agreement_threshold: float = 50.0,
    middle_fraction: float = 0.6,
) -> list[NoteIntonation]:
    """Compute per-note intonation/stability/confidence from cleaned F0 inputs.

    Parameters
    ----------
    fcpe, pesto : np.ndarray
        Octave-corrected F0 arrays (typically the output of
        `correct_octaves()`). 1-D, frame-rate, 0 = unvoiced.
    vote_count : np.ndarray
        Per-frame voicing-vote count from `consensus_voicing()`. int8,
        same length as fcpe/pesto, values 0..3.
    basic_pitch_notes : list
        Iterable of objects with `start` (sec), `end` (sec), `pitch`
        (MIDI int). Each note becomes one entry in the output list,
        positionally aligned with the input.
    fps : float
        Frame rate of the F0/vote_count arrays.
    min_frames : int, keyword-only, default 3
        Minimum number of voiced-agreement frames required to compute
        a measurement. Notes with fewer frames return NaN/0 results.
    cents_agreement_threshold : float, keyword-only, default 50.0
        Maximum |cents(FCPE/PESTO)| difference for a frame to count as
        agreement. 50¢ is half a semitone — looser than this admits
        frames where the two estimators are reading different notes.
    middle_fraction : float, keyword-only, default 0.6
        Fraction of each note's duration to use, centered on the note's
        midpoint. 0.6 trims ~20% off each end to avoid attack/release
        transients.

    Returns
    -------
    list[NoteIntonation]
        One entry per input note, in the same order. Notes that couldn't
        be measured return `NoteIntonation(NaN, NaN, 0.0, 0)`.
    """
    if fcpe.shape != pesto.shape:
        raise ValueError(f"fcpe/pesto shape mismatch: {fcpe.shape} vs {pesto.shape}")
    if vote_count.shape != fcpe.shape:
        raise ValueError(f"vote_count shape mismatch: {vote_count.shape} vs {fcpe.shape}")
    if fcpe.ndim != 1:
        raise ValueError(f"fcpe must be 1-D, got shape {fcpe.shape}")
    if not (0.0 < middle_fraction <= 1.0):
        raise ValueError(f"middle_fraction must be in (0, 1], got {middle_fraction}")

    n_frames = len(fcpe)
    results: list[NoteIntonation] = []
    empty = NoteIntonation(
        intonation_cents=float("nan"),
        stability_cents=float("nan"),
        confidence=0.0,
        n_frames_used=0,
    )

    for note in basic_pitch_notes:
        # Trim to middle fraction (centered on note midpoint)
        note_dur = note.end - note.start
        margin = note_dur * (1.0 - middle_fraction) / 2.0
        i0 = max(0, int(round((note.start + margin) * fps)))
        i1 = min(n_frames, int(round((note.end - margin) * fps)))

        window_size = i1 - i0
        if window_size < min_frames:
            results.append(empty)
            continue

        fcpe_n = fcpe[i0:i1]
        pesto_n = pesto[i0:i1]
        votes_n = vote_count[i0:i1]

        # Stage 1: voted-voiced AND both F0 estimators report a value
        candidate = np.flatnonzero((votes_n >= 2) & (fcpe_n > 0) & (pesto_n > 0))
        if candidate.size == 0:
            results.append(empty)
            continue

        # Stage 2: of candidates, restrict to FCPE/PESTO agreement
        # (skipping log(0) issues by working only on candidate indices)
        cents_diff = 1200.0 * np.log2(fcpe_n[candidate] / pesto_n[candidate])
        agreement = np.abs(cents_diff) < cents_agreement_threshold
        kept = candidate[agreement]

        if kept.size < min_frames:
            results.append(empty)
            continue

        # Per-frame consensus F0 (arithmetic mean is fine in the regime
        # where FCPE and PESTO are within 50¢ — geometric mean would be
        # mathematically more correct in log-frequency but the difference
        # is sub-cent here)
        consensus = (fcpe_n[kept] + pesto_n[kept]) / 2.0
        target_hz = 440.0 * (2.0 ** ((float(note.pitch) - 69.0) / 12.0))
        cents = 1200.0 * np.log2(consensus / target_hz)

        # Fold ±N-octave residuals into [-600, 600] (vectorized fold_cents)
        cents_folded = ((cents + 600.0) % 1200.0) - 600.0

        results.append(NoteIntonation(
            intonation_cents=float(np.median(cents_folded)),
            stability_cents=float(np.std(cents_folded)),
            confidence=float(kept.size / window_size),
            n_frames_used=int(kept.size),
        ))

    return results
