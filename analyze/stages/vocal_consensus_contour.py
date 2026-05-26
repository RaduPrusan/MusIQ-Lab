"""Stage: vocal consensus contour + per-note intonation.

Runs the vocal_consensus pipeline (octave correction, voicing consensus,
consensus F0 line, per-note intonation) on the cached vocal_f0 + basic-
pitch MIDI + (optional) dynamics inputs. Writes:

    cache_dir/vocal_consensus.npz   — frame-rate arrays:
        fcpe_corrected, pesto_corrected, consensus_f0, vote_count,
        octave_corrections (n_frames × 2)

    cache_dir/vocal_consensus.json  — per-note intonation + summary stats

    cache_dir/.params_vocal_consensus_contour.json   — sidecar

The stage is OPTIONAL: it requires `transcription` (basic-pitch MIDI for
vocals) and `vocal_f0` (FCPE/PESTO arrays); these are the hard deps.
`stems_dynamics` is a soft dep — when present, RMS feeds the voicing
floor gate; when absent, the gate no-ops.

If basic-pitch produced no vocals.mid (e.g. instrumental track), the
stage soft-fails: writes a stub summary and returns gracefully.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from analyze import sidecar
from analyze.derived.vocal_consensus.contour import process_contour
from analyze.derived.vocal_consensus.primitives import hz_to_midi, midi_to_hz
from analyze.stages import stems_dynamics, vocal_f0


CANONICAL_NPZ = "vocal_consensus.npz"
CANONICAL_JSON = "vocal_consensus.json"
SCHEMA_VERSION = 3  # Phase 0c Step 2: agreement_strength array. Step 3 added
                    # in-memory anchor pre-validation but kept npz shape identical,
                    # so no further bump (per Step 3 rollback: "No schema change").
FPS = 100.0  # FCPE/PESTO/dynamics all align to this grid

# Plausible human-voice MIDI range. Generous bounds cover everything from
# Tom Waits-low (E2/MIDI 40) to whistle-register sopranos (MIDI 90+). The
# upper cap of 95 (B6 ≈ 1976 Hz) excludes the implausible "vocal" notes
# basic-pitch hallucinates from sibilants, breath, and instrumental bleed
# during non-vocal passages. C7+ "vocals" don't exist in real recordings;
# they're CNN false positives that, if used as an octave-correction
# anchor, would fold FCPE/PESTO up by several octaves and produce
# multi-octave spikes in the consensus contour.
VOCAL_MIDI_MIN = 36   # C2 ≈ 65 Hz
VOCAL_MIDI_MAX = 95   # B6 ≈ 1976 Hz

DEFAULT_PARAMS: dict = {
    "rms_floor_db": -45.0,
    "cents_agreement_threshold": 50.0,
    "vocal_midi_min": VOCAL_MIDI_MIN,
    "vocal_midi_max": VOCAL_MIDI_MAX,
    # Phase 0c Step 3 — anchor pre-validation against F0 medians.
    # Adding these to the param dict shifts the sidecar fingerprint, which
    # forces existing v3 caches (computed without validation) to re-run on
    # next analyze invocation. Cleaner than a schema bump because the npz
    # shape itself is unchanged.
    "anchor_validation_enabled": True,
    "anchor_validation_min_frames": 5,
    "anchor_validation_conf_threshold": 0.4,
    # Phase 0c Step 4 — Viterbi smoothing. Same trick as Step 3: adding
    # these here shifts the sidecar fingerprint and forces re-run for any
    # v3 caches that pre-date the flag. The npz shape is still the same
    # (Viterbi reuses agreement_strength as path_confidence per spec §5);
    # SCHEMA_VERSION stays at 3.
    "viterbi_enabled": True,
    "viterbi_lambda_freq": 1.0,
    "viterbi_cents_normalizer": 300.0,
    "viterbi_lambda_octave": 5.0,
    "viterbi_octave_sigma": 150.0,
    "viterbi_lambda_voicing_on": 3.0,
    "viterbi_lambda_voicing_off": 3.0,
    "viterbi_anchor_prox_bonus": 1.0,
    "viterbi_anchor_prox_sigma": 100.0,
}


def cached(cache_dir: Path, **params) -> bool:
    p = {**DEFAULT_PARAMS, **params}
    if not (cache_dir / CANONICAL_NPZ).exists():
        return False
    if not (cache_dir / CANONICAL_JSON).exists():
        return False
    return sidecar.matches(
        cache_dir, "vocal_consensus_contour", p,
        expected_schema_version=SCHEMA_VERSION,
    )


def load(cache_dir: Path) -> dict:
    """Load consensus arrays + per-note intonation summary.

    Backward-compat: pre-v3 caches lacked `agreement_strength`. We
    synthesize it from `vote_count` (3 → 1.0, 2 → 0.5, else 0.0) so
    consumers see a consistent shape until the next pipeline run
    re-caches with real strength values. The schema bump triggers that
    re-run automatically via the sidecar.
    """
    with np.load(cache_dir / CANONICAL_NPZ) as z:
        arrays = {
            "fcpe_corrected": z["fcpe_corrected"],
            "pesto_corrected": z["pesto_corrected"],
            "consensus_f0": z["consensus_f0"],
            "vote_count": z["vote_count"],
            "octave_corrections": z["octave_corrections"],
        }
        if "agreement_strength" in z.files:
            arrays["agreement_strength"] = z["agreement_strength"]
        else:
            vc = arrays["vote_count"]
            synth = np.where(vc == 3, 1.0, np.where(vc == 2, 0.5, 0.0))
            arrays["agreement_strength"] = synth.astype(np.float32)
    summary = json.loads((cache_dir / CANONICAL_JSON).read_text())
    return {**arrays, "summary": summary}


def _load_basic_pitch_vocals(
    cache_dir: Path,
    *,
    pitch_min: int = VOCAL_MIDI_MIN,
    pitch_max: int = VOCAL_MIDI_MAX,
) -> list:
    """Load basic-pitch's vocal notes from cache_dir/midi/vocals.mid.

    Returns a list of pretty_midi.Note objects, each with .start, .end,
    .pitch, .velocity. Empty list if the file exists but has no notes;
    raises FileNotFoundError if the file is missing.

    Notes outside the plausible vocal MIDI range [pitch_min, pitch_max]
    are filtered out. basic-pitch's CNN regularly hallucinates "notes" at
    very high pitches (MIDI 90+) on sibilants, breath sounds, or
    instrumental bleed in the vocals stem. Letting those through poisons
    the octave-correction anchor, which then folds FCPE/PESTO up by
    multiple octaves and produces tall vertical spikes in the consensus
    contour — the bug the user observes as "3-octave jumps."
    """
    midi_path = cache_dir / "midi" / "vocals.mid"
    if not midi_path.exists():
        raise FileNotFoundError(f"midi/vocals.mid not found at {midi_path}")
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes: list = []
    for inst in pm.instruments:
        for n in inst.notes:
            if pitch_min <= n.pitch <= pitch_max:
                notes.append(n)
    # basic-pitch can emit notes in arbitrary instrument order; sort by
    # start time so per-note intonation aligns with timing-based consumers.
    notes.sort(key=lambda n: n.start)
    return notes


def _safe_json_float(x: float) -> float | None:
    """Convert NaN to None for JSON serialization (json.dumps allows NaN
    but it produces invalid JSON that some downstream parsers reject)."""
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return float(x)


def _validate_anchor_notes(
    bp_notes,
    fcpe: np.ndarray,
    pesto: np.ndarray,
    fcpe_conf: np.ndarray,
    pesto_conf: np.ndarray,
    fps: float,
    *,
    min_validation_frames: int = 5,
    confidence_threshold: float = 0.4,
) -> tuple[list, dict]:
    """Validate basic-pitch's anchor notes against F0 medians.

    Phase 0c Step 3: stops basic-pitch's wrong-octave or hallucinated-pitch
    notes from poisoning octave correction (and, downstream, Step 4
    Viterbi's anchor candidate). Each note is checked against the median
    FCPE and PESTO Hz over its middle 60% (skipping attack/release
    transients), restricted to confident frames.

    Decision per note:
      1. Fewer than `min_validation_frames` confident frames: keep as-is
         (insufficient evidence to validate against; conservative bias
         toward trusting basic-pitch).
      2. Both medians present:
           a. Both within ±50¢ of MIDI: keep unchanged.
           b. Both medians agree with each other within ±50¢ on the SAME
              pitch class as the original (octave error): correct the
              note's pitch by the octave delta.
           c. Any other inconsistency: drop from the anchor list.
      3. Single median present (other estimator unconfident):
           ±50¢ of MIDI → keep, else drop.

    The on-disk midi/vocals.mid is NOT modified — basic-pitch's raw output
    is preserved for posterity. Only the in-memory list passed to
    process_contour is filtered/corrected. Per-note intonation downstream
    sees the validated list, so a dropped note doesn't appear in the
    intonation report (which is the right call: a hallucinated note
    isn't a meaningful intonation reference).

    Returns
    -------
    (validated_notes, info)
        validated_notes : list of pretty_midi.Note (corrected pitches where
            applicable; dropped notes absent)
        info : dict with `kept`, `corrected`, `dropped` integer counts
    """
    import pretty_midi  # local import to keep stage-import cost low

    if not bp_notes:
        return [], {"kept": 0, "corrected": 0, "dropped": 0}

    import statistics  # local import; only used inside this function

    n_frames = len(fcpe)
    kept: list = []
    info = {"kept": 0, "corrected": 0, "dropped": 0}

    # Pre-pass — compute per-note frame ranges and bulk medians.
    #
    # The original implementation called `np.median` twice per note inside a
    # tight Python loop (2 * N calls). Profiling on the Gorillaz cache (1229
    # anchor notes, 2374 median-eligible slices, avg slice len ~11 frames)
    # shows numpy's per-call dispatch overhead is the bottleneck — bare
    # np.median on 2374 tiny arrays takes ~34 ms while statistics.median on
    # the same data as Python lists takes ~0.9 ms (~38×). For arrays this
    # small the C dispatch cost dwarfs the actual work. We pre-pass to
    # collect per-note slice + mask, convert the masked frames to a Python
    # list once, and use statistics.median for the constant-bound work.
    # Equality contract: statistics.median uses the standard "average of two
    # middles for even n" definition — identical to np.median for finite
    # float input. The Gorillaz regression test (rtol=1e-4 on consensus_f0
    # AND exact kept/corrected/dropped counts) is the safety net here.
    #
    # Decision logic below is unchanged — only the median plumbing moves.
    n_notes = len(bp_notes)
    fcpe_med_arr: list[float | None] = [None] * n_notes
    pesto_med_arr: list[float | None] = [None] * n_notes
    short_note: list[bool] = [False] * n_notes

    for idx, note in enumerate(bp_notes):
        i0 = max(0, int(round(note.start * fps)))
        i1 = min(n_frames, int(round(note.end * fps)))
        if i1 - i0 < 1:
            short_note[idx] = True
            continue
        # Middle 60% — skip attack/release transients.
        span = i1 - i0
        margin = int(span * 0.2)
        m0 = i0 + margin
        m1 = i1 - margin
        if m1 - m0 < min_validation_frames:
            short_note[idx] = True
            continue
        # Hoist slice extraction so mask AND median reuse the same view.
        fcpe_slice = fcpe[m0:m1]
        pesto_slice = pesto[m0:m1]
        fcpe_v = (fcpe_slice > 0) & (fcpe_conf[m0:m1] >= confidence_threshold)
        pesto_v = (pesto_slice > 0) & (pesto_conf[m0:m1] >= confidence_threshold)
        # statistics.median over a Python list is ~38× faster than
        # np.median for these tiny (avg ~11-frame) arrays.
        if int(fcpe_v.sum()) >= min_validation_frames:
            fcpe_med_arr[idx] = float(
                statistics.median(fcpe_slice[fcpe_v].tolist())
            )
        if int(pesto_v.sum()) >= min_validation_frames:
            pesto_med_arr[idx] = float(
                statistics.median(pesto_slice[pesto_v].tolist())
            )

    for idx, note in enumerate(bp_notes):
        if short_note[idx]:
            kept.append(note)
            info["kept"] += 1
            continue

        fcpe_med = fcpe_med_arr[idx]
        pesto_med = pesto_med_arr[idx]

        if fcpe_med is None and pesto_med is None:
            kept.append(note)
            info["kept"] += 1
            continue

        target_hz = midi_to_hz(int(note.pitch))

        # Single-witness path (one estimator unconfident).
        if fcpe_med is None or pesto_med is None:
            single = fcpe_med if fcpe_med is not None else pesto_med
            cents_to_midi = abs(1200.0 * math.log2(single / target_hz))
            if cents_to_midi < 50.0:
                kept.append(note)
                info["kept"] += 1
            else:
                info["dropped"] += 1
            continue

        # Both medians present.
        f_cents = abs(1200.0 * math.log2(fcpe_med / target_hz))
        p_cents = abs(1200.0 * math.log2(pesto_med / target_hz))
        if f_cents < 50.0 and p_cents < 50.0:
            kept.append(note)
            info["kept"] += 1
            continue

        # If at least one estimator confirms MIDI, keep the anchor as-is.
        # The other estimator likely has its own glitch (octave-up doubling
        # or similar) which `correct_octaves` will fold back using this
        # anchor downstream. Dropping in this case would prevent the
        # downstream correction from seeing the anchor, defeating it.
        if f_cents < 50.0 or p_cents < 50.0:
            kept.append(note)
            info["kept"] += 1
            continue

        # Neither estimator agrees with MIDI. Three sub-cases distinguish
        # "positive evidence the note is wrong" from various estimator-
        # error patterns — only the first warrants dropping.
        inter_cents = abs(1200.0 * math.log2(fcpe_med / pesto_med))
        if inter_cents < 50.0:
            # Estimators agree with each other on a different note than MIDI.
            avg_hz = (fcpe_med + pesto_med) / 2.0
            avg_midi_int = int(round(hz_to_midi(avg_hz)))
            if (avg_midi_int % 12) == (int(note.pitch) % 12):
                # Same pitch class as the original — octave relationship.
                # Correct ONLY downward: F0 estimators rarely sub-harmonic-lock,
                # so an avg_midi BELOW basic-pitch's pitch is a real over-octave
                # error in basic-pitch (correct it). An avg_midi ABOVE
                # basic-pitch's pitch is almost certainly harmonic-lock on the
                # 2nd/4th harmonic (common on low voices) — keep the anchor at
                # basic-pitch's labelling. This asymmetry costs ~no false
                # negatives in real data because basic-pitch under-octave errors
                # ("singer is at A4, basic-pitch said A3") are vanishingly rare,
                # while harmonic-lock upward is the dominant Cohen failure mode.
                if avg_midi_int < int(note.pitch):
                    corrected = pretty_midi.Note(
                        velocity=note.velocity,
                        pitch=avg_midi_int,
                        start=note.start,
                        end=note.end,
                    )
                    kept.append(corrected)
                    info["corrected"] += 1
                else:
                    kept.append(note)
                    info["kept"] += 1
                continue

            # Different pitch class. Two more guards before dropping.
            #
            # Guard 1 (harmonic-lock): if the disagreement is at an integer
            # ratio of basic-pitch's pitch (3rd ≈ +fifth, 5th ≈ +major3rd,
            # etc.), F0 estimators are likely locked on a higher partial
            # rather than the fundamental. Keep basic-pitch's labelling.
            ratio = avg_hz / target_hz
            if (
                1.5 < ratio < 8.5
                and abs(ratio - round(ratio)) < 0.05
            ):
                kept.append(note)
                info["kept"] += 1
                continue

            # Guard 2 (small disagreement): if avg_midi is within a
            # tritone of basic-pitch's pitch, the disagreement is too
            # small to be catastrophic — it may reflect note-boundary
            # timing artifacts (basic-pitch's span overlapping a glide
            # or pitch transition) rather than a hallucinated anchor.
            # `correct_octaves` only fires on octave-multiple matches, so
            # small disagreements don't poison anything downstream. Keep.
            delta_semi = abs(avg_midi_int - int(note.pitch))
            if delta_semi < 7:
                kept.append(note)
                info["kept"] += 1
                continue

            # Large disagreement (≥7 semitones), not at a harmonic ratio,
            # different pitch class — strongly suggests basic-pitch
            # hallucinated. Drop.
            info["dropped"] += 1
            continue

        # Estimators disagree with each other AND with MIDI. Common on
        # bass-baritone material where one estimator harmonic-locks while
        # the other tracks the fundamental. Neither interpretation is more
        # credible than basic-pitch's label, so keep the anchor unmodified
        # and defer to Step 4 Viterbi (which uses temporal continuity to
        # resolve splits). Dropping here would remove information without
        # adding any.
        kept.append(note)
        info["kept"] += 1

    return kept, info


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    """Compute and persist vocal consensus contour + per-note intonation.

    `mp3` is unused — all inputs come from the cache. Argument retained
    for stage-protocol compatibility.
    """
    p = {**DEFAULT_PARAMS, **params}

    # ---- Load required inputs ----
    vf0 = vocal_f0.load(cache_dir)
    fcpe = np.asarray(vf0["fcpe_array"], dtype=np.float32)
    pesto = np.asarray(vf0["pesto_array"], dtype=np.float32)
    fcpe_conf = np.asarray(vf0["fcpe_conf_array"], dtype=np.float32)
    pesto_conf = np.asarray(vf0["pesto_conf_array"], dtype=np.float32)

    try:
        bp_notes = _load_basic_pitch_vocals(
            cache_dir,
            pitch_min=p["vocal_midi_min"],
            pitch_max=p["vocal_midi_max"],
        )
    except FileNotFoundError:
        bp_notes = []

    # ---- Anchor pre-validation (Phase 0c Step 3) ----
    if p["anchor_validation_enabled"] and bp_notes:
        bp_notes, anchor_validation_info = _validate_anchor_notes(
            bp_notes, fcpe, pesto, fcpe_conf, pesto_conf, FPS,
            min_validation_frames=int(p["anchor_validation_min_frames"]),
            confidence_threshold=float(p["anchor_validation_conf_threshold"]),
        )
    else:
        anchor_validation_info = {"kept": len(bp_notes), "corrected": 0, "dropped": 0}

    # ---- Optional dynamics input ----
    # stems_dynamics is a soft dep; a missing file means the floor gate
    # no-ops, which is correct (no veto signal available).
    dyn = stems_dynamics.load(cache_dir)
    rms = dyn.get("vocals")
    if rms is not None:
        rms = np.asarray(rms, dtype=np.float32)
        # Length-align to F0 arrays. RMS is computed on the stem WAV which
        # may have slightly different length than the FCPE/PESTO output
        # (different framers, edge effects). Truncate to the shorter.
        n = min(len(fcpe), len(pesto), len(rms))
        fcpe = fcpe[:n]
        pesto = pesto[:n]
        rms = rms[:n]
    else:
        n = min(len(fcpe), len(pesto))
        fcpe = fcpe[:n]
        pesto = pesto[:n]

    # ---- Run consensus ----
    # Length-align conf arrays to the (possibly RMS-truncated) fcpe/pesto.
    fcpe_conf = fcpe_conf[: len(fcpe)]
    pesto_conf = pesto_conf[: len(pesto)]

    viterbi_params = {
        "lambda_freq": float(p["viterbi_lambda_freq"]),
        "cents_normalizer": float(p["viterbi_cents_normalizer"]),
        "lambda_octave": float(p["viterbi_lambda_octave"]),
        "octave_sigma": float(p["viterbi_octave_sigma"]),
        "lambda_voicing_on": float(p["viterbi_lambda_voicing_on"]),
        "lambda_voicing_off": float(p["viterbi_lambda_voicing_off"]),
        "anchor_prox_bonus": float(p["viterbi_anchor_prox_bonus"]),
        "anchor_prox_sigma": float(p["viterbi_anchor_prox_sigma"]),
    }
    result = process_contour(
        fcpe, pesto, bp_notes, FPS,
        rms=rms,
        rms_floor_db=p["rms_floor_db"],
        cents_agreement_threshold=p["cents_agreement_threshold"],
        fcpe_conf=fcpe_conf,
        pesto_conf=pesto_conf,
        viterbi_enabled=bool(p["viterbi_enabled"]),
        viterbi_params=viterbi_params,
    )

    # ---- Persist arrays ----
    np.savez_compressed(
        cache_dir / CANONICAL_NPZ,
        fcpe_corrected=result.fcpe_corrected,
        pesto_corrected=result.pesto_corrected,
        consensus_f0=result.consensus_f0,
        agreement_strength=result.agreement_strength,
        vote_count=result.vote_count,
        octave_corrections=result.octave_corrections,
    )

    # ---- Build per-note + summary JSON ----
    notes_out = []
    for note, intonation in zip(bp_notes, result.note_intonation):
        notes_out.append({
            "t_start": float(note.start),
            "t_end": float(note.end),
            "midi": int(note.pitch),
            "intonation_cents": _safe_json_float(intonation.intonation_cents),
            "stability_cents": _safe_json_float(intonation.stability_cents),
            "confidence": float(intonation.confidence),
            "n_frames_used": int(intonation.n_frames_used),
        })

    votes = result.vote_count
    strength = result.agreement_strength
    summary = {
        "schema_version": SCHEMA_VERSION,
        "fps": FPS,
        "n_frames": int(len(votes)),
        "consensus_summary": {
            "frames_vote_3": int((votes == 3).sum()),
            "frames_vote_2": int((votes == 2).sum()),
            "frames_vote_1": int((votes == 1).sum()),
            "frames_vote_0": int((votes == 0).sum()),
            "frames_with_consensus_f0": int(np.isfinite(result.consensus_f0).sum()),
            "frames_strength_strong": int((strength >= 0.7).sum()),
            "frames_strength_medium": int(((strength >= 0.4) & (strength < 0.7)).sum()),
            "frames_strength_weak": int(((strength >= 0.1) & (strength < 0.4)).sum()),
            "octave_corrections_fcpe": int((result.octave_corrections[:, 0] != 0).sum()),
            "octave_corrections_pesto": int((result.octave_corrections[:, 1] != 0).sum()),
        },
        # Phase 0c Step 3 — transparency on which basic-pitch notes the
        # validator kept / corrected / dropped before they became anchors.
        "anchor_validation": {
            "kept": int(anchor_validation_info["kept"]),
            "corrected": int(anchor_validation_info["corrected"]),
            "dropped": int(anchor_validation_info["dropped"]),
        },
        "n_notes": len(notes_out),
        "notes": notes_out,
    }
    (cache_dir / CANONICAL_JSON).write_text(json.dumps(summary, indent=2))

    sidecar.write(
        cache_dir, "vocal_consensus_contour", p,
        schema_version=SCHEMA_VERSION,
    )

    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    s = r["consensus_summary"]
    print(
        f"frames: {r['n_frames']}, "
        f"vote_3: {s['frames_vote_3']}, "
        f"with_consensus: {s['frames_with_consensus_f0']}, "
        f"oct_corr_fcpe: {s['octave_corrections_fcpe']}, "
        f"notes: {r['n_notes']}"
    )
