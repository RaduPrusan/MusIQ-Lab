"""Octave correction via 3-way pitch-class consensus.

Algorithm
---------
For each frame i, gather pitch-class evidence from up to three sources:
    FCPE         — pc(fcpe[i])  if voiced
    PESTO        — pc(pesto[i]) if voiced
    basic-pitch  — pc of the active note at time t_i, if any

When basic-pitch provides an active note, its pitch class + octave is the
**anchor**. basic-pitch sees the spectrum (not just the dominant fundamental),
which makes it robust to the octave glitches that the F0 estimators
produce on breathy / whispered / percussive passages. FCPE/PESTO frames
whose pitch class matches the anchor but whose octave differs by ±N are
folded toward the anchor's octave.

When basic-pitch is silent (between notes), no correction is applied —
there's no spectral anchor to vote against, and folding F0 toward a
guessed octave would risk introducing errors instead of removing them.
The unfolded glitch shows up as a low-confidence frame downstream and
gets penalized at the inter-estimator-agreement layer.

This is conservative by design: false corrections (turning correct F0
into wrong F0) are much worse than missed corrections (leaving a glitch
in for downstream to flag), so the algorithm only fires when basic-pitch
provides spectral evidence to vote against.
"""
from __future__ import annotations

import math

import numpy as np

from analyze.derived.vocal_consensus.primitives import hz_to_midi


def _build_basic_pitch_frame_lookup(
    bp_notes,
    n_frames: int,
    fps: float,
) -> np.ndarray:
    """Per-frame active basic-pitch MIDI integer, or -1 when no note is active.

    Overlap policy: when two notes overlap (rare on vocals but possible
    on harmonized vocals or backing-vocal bleed), the later-onset note
    wins. The "most recently attacked note" is what the singer is
    currently on; the earlier note is presumed releasing.
    """
    active = np.full(n_frames, -1, dtype=np.int16)
    for note in bp_notes:
        i0 = max(0, int(round(note.start * fps)))
        i1 = min(n_frames, int(round(note.end * fps)))
        if i1 > i0:
            active[i0:i1] = note.pitch
    return active


def _midi_octave(midi_continuous: float) -> int:
    """Octave bucket = floor(MIDI / 12). Used for octave-difference math."""
    return int(math.floor(midi_continuous / 12.0))


def correct_octaves(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    basic_pitch_notes,
    fps: float,
    *,
    max_abs_octave_shift: int = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply 3-way octave-consensus correction to FCPE and PESTO arrays.

    Parameters
    ----------
    fcpe, pesto : np.ndarray
        1-D float arrays of equal length, frequency in Hz, 0 = unvoiced.
    basic_pitch_notes : list
        Iterable of objects with `start` (sec), `end` (sec), `pitch` (MIDI int).
    fps : float
        Frame rate of the F0 arrays (typically 100.0).
    max_abs_octave_shift : int, keyword-only, default 1
        Maximum |signed octave shift| this function will apply per frame.
        F0 estimators glitch by ±1 octave in real-world failures; folds of
        ±2 or more would imply the anchor itself is wrong (e.g. basic-pitch
        hallucinated a high "vocal" note from sibilants while FCPE/PESTO
        were on the actual lower pitch with matching pitch class). Capping
        at ±1 prevents the cascade where a poisoned anchor pulls F0
        estimates several octaves up.
        Tests that exercise multi-octave correction can pass a higher
        value; production callers should leave it at 1.

    Returns
    -------
    fcpe_corrected, pesto_corrected : np.ndarray
        Same shape and dtype as inputs. Frames where basic-pitch's PC
        anchor matched but the F0 octave differed by ≤ max_abs_octave_shift
        are scaled by 2**diff toward the anchor's octave. Other frames
        are unchanged.
    corrections : np.ndarray, shape (n_frames, 2), dtype int8
        Per-frame correction signal. Column 0 is FCPE, column 1 is PESTO.
        Value is the signed octave shift applied; 0 = no change.
    """
    if fcpe.shape != pesto.shape:
        raise ValueError(f"fcpe/pesto shape mismatch: {fcpe.shape} vs {pesto.shape}")
    if fcpe.ndim != 1:
        raise ValueError(f"fcpe must be 1-D, got shape {fcpe.shape}")
    if max_abs_octave_shift < 1:
        raise ValueError(f"max_abs_octave_shift must be >= 1, got {max_abs_octave_shift}")

    n_frames = len(fcpe)
    fcpe_out = fcpe.copy()
    pesto_out = pesto.copy()
    corrections = np.zeros((n_frames, 2), dtype=np.int8)

    bp_active = _build_basic_pitch_frame_lookup(basic_pitch_notes, n_frames, fps)

    for i in range(n_frames):
        bp_midi = int(bp_active[i])
        if bp_midi < 0:
            continue  # no anchor; skip

        anchor_pc = bp_midi % 12
        anchor_oct = bp_midi // 12

        # FCPE
        if fcpe[i] > 0:
            f_midi = hz_to_midi(float(fcpe[i]))
            if round(f_midi) % 12 == anchor_pc:
                f_oct = _midi_octave(f_midi)
                if f_oct != anchor_oct:
                    diff = anchor_oct - f_oct
                    if abs(diff) <= max_abs_octave_shift:
                        fcpe_out[i] = float(fcpe[i]) * (2.0 ** diff)
                        corrections[i, 0] = diff
                    # else: anchor likely poisoned; leave FCPE alone

        # PESTO (same logic)
        if pesto[i] > 0:
            p_midi = hz_to_midi(float(pesto[i]))
            if round(p_midi) % 12 == anchor_pc:
                p_oct = _midi_octave(p_midi)
                if p_oct != anchor_oct:
                    diff = anchor_oct - p_oct
                    if abs(diff) <= max_abs_octave_shift:
                        pesto_out[i] = float(pesto[i]) * (2.0 ** diff)
                        corrections[i, 1] = diff

    return fcpe_out, pesto_out, corrections
