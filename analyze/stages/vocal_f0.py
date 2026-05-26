"""Stage 7: vocal F0 via FCPE primary + PESTO cross-check.

Outputs:
    cache_dir/vocal_f0.npz   — four arrays at the FCPE/PESTO 100 fps grid:
        fcpe         (n,) float32 Hz, 0 = unvoiced
        pesto        (n,) float32 Hz, 0 = unvoiced
        fcpe_conf    (n,) float32 in [0, 1]
        pesto_conf   (n,) float32 in [0, 1]
    cache_dir/vocal_f0_summary.json — frame counts + agreement_50c

Confidence semantics
--------------------
- `pesto_conf` is PESTO's per-frame confidence (position 3 of pesto.predict's
  return tuple). Continuous in [0, 1].
- `fcpe_conf` is a binary voiced/unvoiced mask synthesized from `fcpe > 0`.
  torchfcpe's public infer() applies its threshold internally and does not
  expose the underlying activation, so smooth FCPE confidence would require
  a vendor-source patch we deliberately avoid.
  Downstream code (vocal_consensus contour, Viterbi smoothing in Phase 0c)
  treats both arrays uniformly as `[0, 1]` weights; the asymmetry is
  acceptable because the Viterbi cost `−log(max(conf, ε))` collapses to
  zero for any conf=1 frame, so the binary mask only matters at ties.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np

from analyze import sidecar, stems_routing

CANONICAL_NPZ = "vocal_f0.npz"
CANONICAL_SUMMARY = "vocal_f0_summary.json"
SCHEMA_VERSION = 2  # bumped: npz now carries fcpe_conf + pesto_conf
DEFAULT_PARAMS: dict = {}


def cached(cache_dir: Path, **params) -> bool:
    if not ((cache_dir / CANONICAL_NPZ).exists() and (cache_dir / CANONICAL_SUMMARY).exists()):
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "vocal_f0", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    """Load vocal F0 arrays + summary.

    Backward-compat: a v1 npz (no `fcpe_conf` / `pesto_conf` keys) still loads
    cleanly. Confidence arrays are synthesized from the voiced mask in that
    case, matching the v2 fcpe_conf semantics. The sidecar version mismatch
    will trigger a re-run on the next analyze invocation, but until then
    consumers see a consistent interface.
    """
    summary = json.loads((cache_dir / CANONICAL_SUMMARY).read_text())
    npz = np.load(cache_dir / CANONICAL_NPZ)
    fcpe = npz["fcpe"]
    pesto = npz["pesto"]
    fcpe_conf = (
        npz["fcpe_conf"] if "fcpe_conf" in npz.files
        else (fcpe > 0).astype(np.float32)
    )
    pesto_conf = (
        npz["pesto_conf"] if "pesto_conf" in npz.files
        else (pesto > 0).astype(np.float32)
    )
    return {
        **summary,
        "fcpe_array": fcpe,
        "pesto_array": pesto,
        "fcpe_conf_array": fcpe_conf,
        "pesto_conf_array": pesto_conf,
    }


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    import librosa
    import torch
    from torchfcpe import spawn_bundled_infer_model
    import pesto

    p = {**DEFAULT_PARAMS, **params}

    try:
        vocals_path = str(stems_routing.path_for(cache_dir, "vocals"))
    except stems_routing.RoutingError:
        # transition path: legacy caches or fast preset without routing.json
        vocals_path = next(
            path for path in glob.glob(str(cache_dir / "stems_6s" / "*.wav"))
            if "vocal" in Path(path).name.lower()
        )
    audio, sr = librosa.load(vocals_path, sr=16000, mono=True)

    audio_cuda = torch.from_numpy(audio).unsqueeze(0).to("cuda")
    fcpe = spawn_bundled_infer_model(device="cuda")
    f0_fcpe = fcpe.infer(
        audio_cuda, sr=16000, decoder_mode="local_argmax",
        threshold=0.006, f0_min=80, f0_max=880, interp_uv=False,
    ).squeeze().detach().cpu().numpy()

    audio_cpu = torch.from_numpy(audio)
    _, f0_pesto, conf_pesto, _ = pesto.predict(
        audio_cpu, sr=16000, step_size=10.0, inference_mode="cqt",
    )
    if hasattr(f0_pesto, "detach"):
        f0_pesto = f0_pesto.detach().cpu().numpy()
    else:
        f0_pesto = np.asarray(f0_pesto)
    if hasattr(conf_pesto, "detach"):
        conf_pesto = conf_pesto.detach().cpu().numpy()
    else:
        conf_pesto = np.asarray(conf_pesto)

    f0_fcpe = f0_fcpe.astype(np.float32, copy=False)
    f0_pesto = f0_pesto.astype(np.float32, copy=False)
    fcpe_conf = (f0_fcpe > 0).astype(np.float32)
    pesto_conf = np.clip(conf_pesto.astype(np.float32, copy=False), 0.0, 1.0)

    n = min(len(f0_fcpe), len(f0_pesto))
    fcpe_n, pesto_n = f0_fcpe[:n], f0_pesto[:n]
    both_voiced = (fcpe_n > 0) & (pesto_n > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200 * np.log2(fcpe_n / np.maximum(pesto_n, 1e-6))
    agree_50c = both_voiced & (np.abs(cents) < 50)
    agreement = float(agree_50c.sum() / max(both_voiced.sum(), 1))

    np.savez_compressed(
        cache_dir / CANONICAL_NPZ,
        fcpe=f0_fcpe,
        pesto=f0_pesto,
        fcpe_conf=fcpe_conf,
        pesto_conf=pesto_conf,
    )
    summary = {
        "fcpe_frames": int(len(f0_fcpe)),
        "pesto_frames": int(len(f0_pesto)),
        "agreement_50c": agreement,
    }
    (cache_dir / CANONICAL_SUMMARY).write_text(json.dumps(summary, indent=2))
    sidecar.write(cache_dir, "vocal_f0", p, schema_version=SCHEMA_VERSION)
    return {
        **summary,
        "fcpe_array": f0_fcpe,
        "pesto_array": f0_pesto,
        "fcpe_conf_array": fcpe_conf,
        "pesto_conf_array": pesto_conf,
    }


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    print(f"FCPE frames: {r['fcpe_frames']}, PESTO frames: {r['pesto_frames']}, agree50c: {r['agreement_50c']:.3f}")
