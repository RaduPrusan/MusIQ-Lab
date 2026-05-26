"""Inspect the Cohen canary frame and surrounding window in detail.

Step 4 Viterbi landed at 440 Hz around t=107.7s — way off the 87 Hz
target. This script dumps everything Viterbi sees at that frame to
diagnose whether the bug is in (a) anchor presence (basic-pitch
hallucinating a high note), (b) Step 3 validation letting it through,
or (c) Viterbi's anchor-prox bonus over-trusting the anchor.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pretty_midi

PROJECT = Path(__file__).resolve().parent.parent
COHEN = PROJECT / "cache" / "leonard_cohen_in_my_secret_life"
FPS = 100.0
T_S = 107.7
WIN = 30  # frames each side


def main() -> None:
    vc = np.load(COHEN / "vocal_consensus.npz")
    fcpe_c = vc["fcpe_corrected"]
    pesto_c = vc["pesto_corrected"]
    consensus_f0 = vc["consensus_f0"]
    agreement_strength = vc["agreement_strength"]

    vf0 = np.load(COHEN / "vocal_f0.npz")
    fcpe_raw = vf0["fcpe"]
    pesto_raw = vf0["pesto"]
    fcpe_conf = vf0["fcpe_conf"] if "fcpe_conf" in vf0.files else (fcpe_raw > 0).astype(np.float32)
    pesto_conf = vf0["pesto_conf"] if "pesto_conf" in vf0.files else (pesto_raw > 0).astype(np.float32)

    midi_path = COHEN / "midi" / "vocals.mid"
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    raw_notes = sorted(
        (n for inst in pm.instruments for n in inst.notes if 36 <= n.pitch <= 95),
        key=lambda n: n.start,
    )

    i = int(round(T_S * FPS))
    print(f"Canary frame index: {i}  (t = {T_S}s)")
    print(f"Total frames: {len(consensus_f0)}\n")

    # Notes overlapping the canary window
    win_start_s = (i - WIN) / FPS
    win_end_s = (i + WIN + 1) / FPS
    print(f"Notes overlapping [{win_start_s:.2f}s, {win_end_s:.2f}s]:")
    for n in raw_notes:
        if n.end < win_start_s or n.start > win_end_s:
            continue
        bp_hz = 440.0 * (2.0 ** ((n.pitch - 69) / 12.0))
        print(
            f"  start={n.start:.3f}s  end={n.end:.3f}s  "
            f"midi={n.pitch}  hz={bp_hz:.1f}  vel={n.velocity}"
        )

    # Per-frame dump
    print(f"\nPer-frame ({WIN} each side; canary is i={i}):")
    print(f"{'idx':>5}  {'fcpe_raw':>8}  {'fc_conf':>7}  {'pesto_raw':>9}  "
          f"{'pe_conf':>7}  {'consensus':>9}  {'strength':>8}")
    for j in range(max(0, i - WIN), min(len(consensus_f0), i + WIN + 1)):
        marker = "  <-- canary" if j == i else ""
        print(
            f"{j:>5}  {fcpe_raw[j]:>8.1f}  {fcpe_conf[j]:>7.3f}  "
            f"{pesto_raw[j]:>9.1f}  {pesto_conf[j]:>7.3f}  "
            f"{consensus_f0[j]:>9.1f}  {agreement_strength[j]:>8.3f}{marker}"
        )

    # Summary view of consensus drift in window
    win = consensus_f0[max(0, i - WIN):min(len(consensus_f0), i + WIN + 1)]
    finite = win[np.isfinite(win)]
    if finite.size:
        print(f"\nWindow consensus_f0 (finite only):  median={float(np.median(finite)):.1f}Hz  "
              f"min={float(finite.min()):.1f}Hz  max={float(finite.max()):.1f}Hz")


if __name__ == "__main__":
    main()
