"""Re-run vocal_consensus_contour on benchmark caches with Step 3 enabled.

Step 3 added in-memory anchor pre-validation. The stage's npz shape is
unchanged (no schema bump), but the new params in DEFAULT_PARAMS shift
the sidecar fingerprint, invalidating prior caches. We re-run on the
three benchmarks to measure: how many anchors get corrected/dropped,
and how the kill rate / unanchored octave-split count moves.

Run via WSL inside the project venv:
    wsl bash -c 'cd "<PROJECT_WSL_PATH>" && \
        source .venv/bin/activate && \
        PYTHONPATH=. python install-logs/_phase_0c_step3_rerun.py'
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pretty_midi

from analyze.stages import vocal_consensus_contour as stage

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


def _bp_active_mask(bp_notes, n_frames: int, fps: float) -> np.ndarray:
    mask = np.zeros(n_frames, dtype=bool)
    for note in bp_notes:
        i0 = max(0, int(round(note.start * fps)))
        i1 = min(n_frames, int(round(note.end * fps)))
        if i1 > i0:
            mask[i0:i1] = True
    return mask


def diagnose(slug: str, run_summary: dict) -> dict:
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
        # Count basic-pitch's raw notes (pre-validation) for context
        raw_notes = [n for inst in pm.instruments for n in inst.notes if 36 <= n.pitch <= 95]
    else:
        raw_notes = []
    bp_active = _bp_active_mask(raw_notes, n_frames, FPS)

    finite_consensus = np.isfinite(consensus_f0)
    voted_voiced = vote_count >= 2
    killed_by_line_filter = voted_voiced & ~finite_consensus

    both_f0_voiced = (fcpe_c > 0) & (pesto_c > 0)
    in_range = (
        (fcpe_c >= HZ_MIN) & (fcpe_c <= HZ_MAX)
        & (pesto_c >= HZ_MIN) & (pesto_c <= HZ_MAX)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200.0 * np.log2(
            np.where(both_f0_voiced, fcpe_c, 1.0)
            / np.where(both_f0_voiced, pesto_c, 1.0),
        )
    near_octave = (np.abs(np.abs(cents) - 1200.0) < OCTAVE_BAND_CENTS)
    octave_split_mask = both_f0_voiced & in_range & near_octave
    octave_split_no_anchor = octave_split_mask & ~bp_active

    cs = run_summary["consensus_summary"]
    av = run_summary.get("anchor_validation", {"kept": 0, "corrected": 0, "dropped": 0})
    return {
        "slug": slug,
        "phase": "0c-step3-postship",
        "vc_schema_version": stage.SCHEMA_VERSION,
        "n_frames": int(n_frames),
        "frames_finite_consensus_f0": int(finite_consensus.sum()),
        "ratio_finite_consensus_f0": float(finite_consensus.sum() / max(n_frames, 1)),
        "frames_killed_by_line_filter": int(killed_by_line_filter.sum()),
        "ratio_killed_of_voted_voiced": float(
            killed_by_line_filter.sum() / max(voted_voiced.sum(), 1)
        ),
        "frames_in_range_octave_split": int(octave_split_mask.sum()),
        "frames_in_range_octave_split_no_anchor": int(octave_split_no_anchor.sum()),
        "frames_strength_strong": int(cs["frames_strength_strong"]),
        "frames_strength_medium": int(cs["frames_strength_medium"]),
        "frames_strength_weak": int(cs["frames_strength_weak"]),
        "anchor_validation_kept": int(av["kept"]),
        "anchor_validation_corrected": int(av["corrected"]),
        "anchor_validation_dropped": int(av["dropped"]),
        "n_basic_pitch_notes_raw": len(raw_notes),
        "generated_at_iso": "2026-05-05",
    }


def main() -> int:
    out_dir = PROJECT / "install-logs"
    for label, slug in TRACKS.items():
        cache_dir = CACHE / slug
        if not cache_dir.exists():
            print(f"{label:10s}  SKIP (cache not found)")
            continue
        # Force re-run by removing the old npz
        npz = cache_dir / "vocal_consensus.npz"
        if npz.exists():
            npz.unlink()
        run_summary = stage.run(Path("/dev/null"), cache_dir)
        d = diagnose(slug, run_summary)
        out = out_dir / f"phase-0c-step3-{label}.json"
        out.write_text(json.dumps(d, indent=2))
        total_anchors = d["anchor_validation_kept"] + d["anchor_validation_corrected"] + d["anchor_validation_dropped"]
        drop_pct = (
            d["anchor_validation_dropped"] / max(total_anchors, 1) * 100.0
        )
        corr_pct = (
            d["anchor_validation_corrected"] / max(total_anchors, 1) * 100.0
        )
        print(
            f"{label:10s}  finite={d['ratio_finite_consensus_f0']*100:5.1f}%  "
            f"killed={d['ratio_killed_of_voted_voiced']*100:5.1f}%  "
            f"corrected={d['anchor_validation_corrected']:3d} ({corr_pct:4.1f}%)  "
            f"dropped={d['anchor_validation_dropped']:3d} ({drop_pct:4.1f}%)  "
            f"oct_unanch={d['frames_in_range_octave_split_no_anchor']:4d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
