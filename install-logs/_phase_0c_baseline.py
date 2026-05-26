"""Phase 0c diagnostic snapshot — produces install-logs/phase-0c-baseline-<track>.json.

Per spec §1, computes:
  - frames_finite_consensus_f0   (and ratio over total frames)
  - frames_vote_2_or_3           (voted-voiced gate)
  - frames_killed_by_line_filter (voted-voiced minus finite consensus)
  - frames_in_range_octave_split (FCPE/PESTO both voiced, ~1200±100c apart, both in vocal range)
  - frames_in_range_octave_split_no_anchor (subset where basic-pitch is silent)

Run via WSL inside the project venv:
    wsl bash -c 'cd "<PROJECT_WSL_PATH>" && \
        source .venv/bin/activate && python install-logs/_phase_0c_baseline.py'
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pretty_midi

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "cache"

TRACKS = {
    "sting": "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw",
    "radiohead": "radiohead_creep_heads_on_the_radio",
    "cohen": "leonard_cohen_in_my_secret_life",
}

FPS = 100.0
HZ_MIN, HZ_MAX = 65.0, 1500.0
OCTAVE_BAND_CENTS = 100.0


def basic_pitch_active_mask(bp_notes, n_frames: int, fps: float) -> np.ndarray:
    mask = np.zeros(n_frames, dtype=bool)
    for note in bp_notes:
        i0 = max(0, int(round(note.start * fps)))
        i1 = min(n_frames, int(round(note.end * fps)))
        if i1 > i0:
            mask[i0:i1] = True
    return mask


def diagnose(slug: str) -> dict:
    cache_dir = CACHE / slug
    vc = np.load(cache_dir / "vocal_consensus.npz")
    fcpe_c = vc["fcpe_corrected"]
    pesto_c = vc["pesto_corrected"]
    consensus_f0 = vc["consensus_f0"]
    vote_count = vc["vote_count"]
    n_frames = len(consensus_f0)

    midi_path = cache_dir / "midi" / "vocals.mid"
    if midi_path.exists():
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        bp_notes = [n for inst in pm.instruments for n in inst.notes if 36 <= n.pitch <= 95]
    else:
        bp_notes = []
    bp_active = basic_pitch_active_mask(bp_notes, n_frames, FPS)

    finite_consensus = np.isfinite(consensus_f0)
    voted_voiced = vote_count >= 2
    killed_by_line_filter = voted_voiced & ~finite_consensus

    both_f0_voiced = (fcpe_c > 0) & (pesto_c > 0)
    in_range = (fcpe_c >= HZ_MIN) & (fcpe_c <= HZ_MAX) & (pesto_c >= HZ_MIN) & (pesto_c <= HZ_MAX)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200.0 * np.log2(np.where(both_f0_voiced, fcpe_c, 1.0) /
                                 np.where(both_f0_voiced, pesto_c, 1.0))
    near_octave = (np.abs(np.abs(cents) - 1200.0) < OCTAVE_BAND_CENTS)
    octave_split_mask = both_f0_voiced & in_range & near_octave
    octave_split_no_anchor = octave_split_mask & ~bp_active

    return {
        "slug": slug,
        "n_frames": int(n_frames),
        "frames_finite_consensus_f0": int(finite_consensus.sum()),
        "ratio_finite_consensus_f0": float(finite_consensus.sum() / max(n_frames, 1)),
        "frames_vote_2_or_3": int(voted_voiced.sum()),
        "frames_killed_by_line_filter": int(killed_by_line_filter.sum()),
        "ratio_killed_of_voted_voiced": float(
            killed_by_line_filter.sum() / max(voted_voiced.sum(), 1)
        ),
        "frames_in_range_octave_split": int(octave_split_mask.sum()),
        "frames_in_range_octave_split_no_anchor": int(octave_split_no_anchor.sum()),
        "ratio_octave_split_unanchored": float(
            octave_split_no_anchor.sum() / max(octave_split_mask.sum(), 1)
        ),
        "n_basic_pitch_notes": len(bp_notes),
        "vc_schema_version": 2,
        "phase": "0c-baseline",
        "generated_at_iso": "2026-05-05",
    }


def main() -> int:
    out_dir = PROJECT / "install-logs"
    for label, slug in TRACKS.items():
        d = diagnose(slug)
        out = out_dir / f"phase-0c-baseline-{label}.json"
        out.write_text(json.dumps(d, indent=2))
        print(f"{label:10s}  finite={d['ratio_finite_consensus_f0']*100:5.1f}%  "
              f"killed={d['ratio_killed_of_voted_voiced']*100:5.1f}%  "
              f"octsplit={d['frames_in_range_octave_split']:5d}  "
              f"(unanch {d['ratio_octave_split_unanchored']*100:4.1f}%)  "
              f"→ {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
