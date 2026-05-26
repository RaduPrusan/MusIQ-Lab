from pathlib import Path

import numpy as np


def decode_f0(
    npz_path: Path,
    consensus_npz_path: Path | None = None,
    vocals_dynamics_npz_path: Path | None = None,
) -> dict:
    """Decode vocal_f0.npz (raw FCPE/PESTO) plus optional consensus arrays.

    When `consensus_npz_path` is provided and the file exists, the response
    includes a `consensus` block with the cleaned consensus_f0 line, the
    per-frame vote count, and the octave-correction flags. When absent,
    `consensus` is `null` — old caches without the consensus stage still
    work and the frontend can degrade gracefully.

    When `vocals_dynamics_npz_path` is provided and exists, the response
    includes `vocals_rms` — a per-frame linear RMS amplitude array
    aligned to the F0 frame rate. The frontend uses this to modulate
    contour opacity proportionally to vocal volume. When missing,
    `vocals_rms` is `null` and the renderer falls back to a constant
    opacity per agreement-strength bucket.

    NaN values in consensus_f0 (frames with no consensus) are serialized
    as JSON null. The frontend must use `=== null` (not falsy) checks
    since 0.0 is a valid (though impossible) consensus value.
    """
    if not npz_path.is_file():
        raise FileNotFoundError(str(npz_path))
    z = np.load(npz_path)
    if "fcpe" not in z or "pesto" not in z:
        raise KeyError(f"vocal_f0.npz missing required keys; have {list(z.keys())}")
    fcpe = z["fcpe"].astype(np.float32, copy=False)
    pesto = z["pesto"].astype(np.float32, copy=False)
    n = int(min(len(fcpe), len(pesto)))

    out: dict = {
        "n_frames": n,
        "hop_sec": 0.01,
        "fcpe": fcpe[:n].tolist(),
        "pesto": pesto[:n].tolist(),
        "consensus": None,
        "vocals_rms": None,
    }

    if consensus_npz_path is not None and consensus_npz_path.is_file():
        with np.load(consensus_npz_path) as cz:
            consensus_f0 = cz["consensus_f0"].astype(np.float32, copy=False)
            vote_count = cz["vote_count"]
            oc = cz["octave_corrections"]
            # Pre-Phase-0c-Step-2 caches lacked agreement_strength. Synthesize
            # from vote_count (3 → 1.0, 2 → 0.5, else 0.0) so the frontend
            # always sees the array shape; the schema bump triggers re-cache
            # on next analyze, replacing this with real strength values.
            if "agreement_strength" in cz.files:
                strength = cz["agreement_strength"].astype(np.float32, copy=False)
            else:
                vc = vote_count
                strength = np.where(
                    vc == 3, 1.0, np.where(vc == 2, 0.5, 0.0),
                ).astype(np.float32)
        cn = int(min(len(consensus_f0), n))
        # NaN → None for JSON. The serializer would otherwise emit NaN
        # (which is invalid JSON; some downstream parsers reject it).
        cf0_list = [
            None if not np.isfinite(x) else float(x)
            for x in consensus_f0[:cn]
        ]
        out["consensus"] = {
            "n_frames": cn,
            "consensus_f0": cf0_list,
            "agreement_strength": [float(s) for s in strength[:cn]],
            "vote_count": vote_count[:cn].astype(int).tolist(),
            "octave_corrections_fcpe": oc[:cn, 0].astype(int).tolist(),
            "octave_corrections_pesto": oc[:cn, 1].astype(int).tolist(),
        }

    if vocals_dynamics_npz_path is not None and vocals_dynamics_npz_path.is_file():
        with np.load(vocals_dynamics_npz_path) as vz:
            if "rms" in vz.files:
                rms = vz["rms"].astype(np.float32, copy=False)
                # Length-align to the F0 frame count. The dynamics stage
                # uses the same 100 fps grid but stem WAV length can
                # differ from FCPE/PESTO output by a few frames at the
                # edges (different framers, edge effects).
                rn = int(min(len(rms), n))
                out["vocals_rms"] = [float(x) for x in rms[:rn]]

    return out
