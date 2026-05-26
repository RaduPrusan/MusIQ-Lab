#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import glob, json, os
import librosa
import numpy as np
import torch
from torchfcpe import spawn_bundled_infer_model

vocals_path = next(
    path for path in glob.glob(os.path.join(os.environ["TEST_DIR"], "stems_6s/*.wav"))
    if "vocal" in os.path.basename(path).lower()
)
print("vocals stem:", vocals_path)

audio, sr = librosa.load(vocals_path, sr=16000, mono=True)
audio_cuda = torch.from_numpy(audio).unsqueeze(0).to("cuda")

fcpe = spawn_bundled_infer_model(device="cuda")
f0_fcpe = fcpe.infer(
    audio_cuda,
    sr=16000,
    decoder_mode="local_argmax",
    threshold=0.006,
    f0_min=80,
    f0_max=880,
    interp_uv=False,
).squeeze().detach().cpu().numpy()
print("FCPE frames:", len(f0_fcpe), "voiced:", float((f0_fcpe > 0).mean()))

import pesto
audio_cpu = torch.from_numpy(audio)
ts, f0_pesto, conf_pesto, _ = pesto.predict(
    audio_cpu,
    sr=16000,
    step_size=10.0,
    inference_mode="cqt",
)
if hasattr(f0_pesto, "detach"):
    f0_pesto = f0_pesto.detach().cpu().numpy()
else:
    f0_pesto = np.asarray(f0_pesto)
print("PESTO frames:", len(f0_pesto))

n = min(len(f0_fcpe), len(f0_pesto))
fcpe_n = f0_fcpe[:n]
pesto_n = f0_pesto[:n]
both_voiced = (fcpe_n > 0) & (pesto_n > 0)
agree_50c = both_voiced & (np.abs(1200 * np.log2(fcpe_n / np.maximum(pesto_n, 1e-6))) < 50)
agreement = float(agree_50c.sum() / max(both_voiced.sum(), 1))
print("Voiced agreement within 50 cents:", agreement)

np.savez_compressed(os.path.join(os.environ["TEST_DIR"], "vocal_f0.npz"), fcpe=f0_fcpe, pesto=f0_pesto)
with open(os.path.join(os.environ["TEST_DIR"], "vocal_f0_summary.json"), "w") as f:
    json.dump({"fcpe_frames": len(f0_fcpe), "pesto_frames": len(f0_pesto), "agreement_50c": agreement}, f, indent=2)
PY
