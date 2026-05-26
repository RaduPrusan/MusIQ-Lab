"""Profile _validate_anchor_notes on the Gorillaz cache.

Standalone harness for measuring the cost of basic-pitch anchor
validation against FCPE/PESTO medians (vocal_consensus_contour stage 8a).

Baseline (May 2026, before vectorization): ~75 ms / call on 1229 notes.
After hoisting medians out of the decision loop and using
statistics.median on tiny slices: ~21 ms / call (~3.5×).

Usage (WSL):
    source .venv/bin/activate
    PYTHONPATH=. python scripts/profile_validate_anchor.py
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from analyze.stages.vocal_consensus_contour import (
    _load_basic_pitch_vocals,
    _validate_anchor_notes,
)
from analyze.stages.vocal_f0 import load as load_vocal_f0


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE = PROJECT_ROOT / "cache" / "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg"


def main() -> None:
    vf0 = load_vocal_f0(CACHE)
    fcpe = vf0["fcpe_array"].astype(np.float32)
    pesto = vf0["pesto_array"].astype(np.float32)
    fcpe_conf = vf0["fcpe_conf_array"].astype(np.float32)
    pesto_conf = vf0["pesto_conf_array"].astype(np.float32)
    bp_notes = _load_basic_pitch_vocals(CACHE)
    print(f"Loaded {len(bp_notes)} basic-pitch vocal notes; n_frames={len(fcpe)}")

    # Warm-up call drops one-time import / JIT overhead from the timing.
    _validate_anchor_notes(bp_notes, fcpe, pesto, fcpe_conf, pesto_conf, 100.0)

    N = 10
    t0 = time.perf_counter()
    for _ in range(N):
        kept, info = _validate_anchor_notes(
            bp_notes, fcpe, pesto, fcpe_conf, pesto_conf, 100.0
        )
    t1 = time.perf_counter()
    mean_ms = (t1 - t0) / N * 1000.0
    print(
        f"Mean: {mean_ms:.2f} ms over {N} runs, {len(bp_notes)} notes — "
        f"info={info}"
    )


if __name__ == "__main__":
    main()
