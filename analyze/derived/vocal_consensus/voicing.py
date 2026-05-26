"""Voicing consensus: per-frame voiced/unvoiced decision from three (or four) evidence streams.

Algorithm
---------
For each frame i, count how many of the three pitch-evidence estimators
say "voiced":

    fcpe_v   = fcpe[i]  > 0
    pesto_v  = pesto[i] > 0
    basic_v  = a basic-pitch note is active at time t_i

The function returns the per-frame vote count as an int8 array with values
in {0, 1, 2, 3}. The voicing *decision* is `vote_count >= 2` — at least
two of three must agree. Callers that need the boolean track derive it
trivially; callers that need confidence (downstream scoring layers, UI
overlays) read the count directly.

Why 2-of-3 majority
-------------------
basic-pitch alone is the strongest evidence (it sees spectrum, not just
dominant fundamental), but it can hallucinate notes from spectral residue
or backing-vocal bleed. Requiring at least one F0 estimator to agree
with basic-pitch suppresses those false positives. Similarly, FCPE alone
on a percussive consonant or breathy whisper can produce a spurious F0
reading; requiring corroboration from one other source removes those.

The 2-of-3 rule is the tightest filter that still tolerates one
estimator being wrong in either direction (false positive or false
negative on any single source).

Optional RMS floor: a veto, not a vote
--------------------------------------
RMS energy is asymmetric for voicing:
  - Low RMS reliably means unvoiced (no signal, regardless of what F0
    estimators may erroneously claim).
  - High RMS does NOT reliably mean voiced (sibilants, breath, and
    instrument bleed all have high energy without periodicity).

Therefore RMS enters this module as a *veto* on the vote count, not as a
fourth vote. When `rms` is supplied, frames whose energy is below
`rms_floor_db` have their vote count forced to 0 regardless of pitch
agreement. This catches F0-estimator hallucinations on silent passages
(occasional voiced readings at -50 dB that the pitch detectors are
confident about but that contradict the actual signal energy).

Adding RMS as a positive 4th vote would push the failure mode in the
wrong direction — every consonant would become voiced. The asymmetry
matters; preserve it.
"""
from __future__ import annotations

import numpy as np


def _basic_pitch_active_mask(bp_notes, n_frames: int, fps: float) -> np.ndarray:
    """Boolean mask: True for frames where any basic-pitch note is active.

    Independent of the int16-MIDI variant in octave.py — that one is
    needed for pitch-class lookups; this one is purely binary. They'll
    likely merge into a shared frame-index utility in 0a.5 when the
    segmenter needs both shapes.
    """
    mask = np.zeros(n_frames, dtype=bool)
    for note in bp_notes:
        i0 = max(0, int(round(note.start * fps)))
        i1 = min(n_frames, int(round(note.end * fps)))
        if i1 > i0:
            mask[i0:i1] = True
    return mask


def consensus_voicing(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    basic_pitch_notes,
    fps: float,
    *,
    rms: np.ndarray | None = None,
    rms_floor_db: float = -45.0,
) -> np.ndarray:
    """Return a per-frame vote-count for "voiced" across three estimators.

    Parameters
    ----------
    fcpe, pesto : np.ndarray
        1-D float arrays of equal length, frequency in Hz, 0 = unvoiced.
    basic_pitch_notes : list
        Iterable of objects with `start` (sec), `end` (sec). `pitch` is
        not consulted here — voicing is purely about presence.
    fps : float
        Frame rate of the F0 arrays (typically 100.0).
    rms : np.ndarray | None, keyword-only
        Optional per-frame RMS envelope (linear amplitude, same shape as
        fcpe/pesto). When supplied, frames whose RMS is strictly below
        `rms_floor_db` (in dBFS) have their vote count forcibly zeroed —
        catches F0 hallucinations on silent regions. See module
        docstring for why this is a veto and not a vote.
    rms_floor_db : float, keyword-only, default -45.0
        Energy floor in dBFS below which voicing is vetoed. -45 dBFS
        ≈ 0.0056 linear amplitude — conservatively above the noise floor
        of a clean BS-RoFormer vocals stem and below typical whisper
        levels (~-40 dBFS). Tracks with noisier stems may need a higher
        (less strict) floor; this is one of the parameters that will
        want corpus-level calibration in Phase 1.

    Returns
    -------
    vote_count : np.ndarray, shape (n_frames,), dtype int8
        Per-frame number of estimators voting voiced. Values are 0..3.
        Voicing decision = `vote_count >= 2`. Vote count itself doubles
        as a confidence measure for downstream consumers.
    """
    if fcpe.shape != pesto.shape:
        raise ValueError(f"fcpe/pesto shape mismatch: {fcpe.shape} vs {pesto.shape}")
    if fcpe.ndim != 1:
        raise ValueError(f"fcpe must be 1-D, got shape {fcpe.shape}")

    n_frames = len(fcpe)
    fcpe_v = (fcpe > 0).astype(np.int8)
    pesto_v = (pesto > 0).astype(np.int8)
    basic_v = _basic_pitch_active_mask(basic_pitch_notes, n_frames, fps).astype(np.int8)

    vote_count = fcpe_v + pesto_v + basic_v

    if rms is not None:
        if rms.shape != fcpe.shape:
            raise ValueError(f"rms shape mismatch: {rms.shape} vs {fcpe.shape}")
        floor_linear = 10.0 ** (rms_floor_db / 20.0)
        vote_count[rms < floor_linear] = 0

    return vote_count
