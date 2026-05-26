# Test Plan: validate the music-analysis stack end-to-end on Torch 2.7

**Decision**: upgrade the whole stack to PyTorch 2.7 on CUDA 12.6.

**Reason**: `deezer/skey` dictates the Torch lane. Its `pyproject.toml` pins `torch = "~2.7.0"` (i.e. `>=2.7.0,<2.8.0`), and Torchaudio is pulled in from the same series. Keeping the older Torch 2.5/cu121 pin makes the resolver fight the key-detection dependency. This runbook chooses the 2.7 lane explicitly and adjusts Basic Pitch and verification commands around that decision.

**Test track**: `Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3` (about 7.5 MB)

**Test file paths** — set these for your machine (any directory you keep the
test MP3 in; the runbook treats both as opaque). Examples on a Windows host
with the file under `~/Videos/musiq-lab`:
- Windows: `%USERPROFILE%\Videos\musiq-lab\Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3`
- WSL:     `$HOME/.../Videos/musiq-lab/Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3`

**Project** — wherever you cloned the repo; the runbook treats this as opaque.
On the maintainer's machine these are e.g. `<PROJECT_PATH>`
and `<PROJECT_WSL_PATH>`.

Run commands from Windows PowerShell unless you are already inside the target WSL distribution. Execute phases in order. If a phase fails, stop and diagnose; do not skip ahead.

---

## Current state to verify

Expected already done:

- Phase 0: WSL Ubuntu 24.04.4, RTX 3090 visible to WSL, test MP3 readable.
- Phase 1: apt dependencies installed except `sonic-annotator`, which is not in Ubuntu 24.04 main repositories.
- Phase 2: `uv 0.11.8` installed at `~/.local/bin/uv`; Python 3.11.15 installed by uv.
- Phase 3 onward: redo from scratch. No `.venv`, no `requirements-linux-cu126.txt`, no `requirements.lock` should be present unless you intentionally created them in this run.

Verify:

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
echo "==== OS ===="
lsb_release -ds

echo "==== GPU ===="
nvidia-smi --query-gpu=name,memory.free --format=csv,noheader

echo "==== uv ===="
~/.local/bin/uv --version

echo "==== Python 3.11 ===="
~/.local/bin/uv python list --only-installed 3.11 | head -5
python3.11 --version

echo "==== apt packages ===="
dpkg -s build-essential cmake pkg-config libsndfile1-dev libsamplerate0-dev libfftw3-dev sox vamp-plugin-sdk vamp-examples ffmpeg >/dev/null
echo "apt deps OK"

echo "==== project ===="
cd "<PROJECT_WSL_PATH>"
find . -maxdepth 1 -mindepth 1 -printf "%f\n" | sort
'
```

Success:
- `uv 0.11.8`
- `cpython-3.11.15-linux-x86_64-gnu` listed by uv
- `Python 3.11.15`
- apt check prints `apt deps OK`
- project root shows the expected source folders and no stale `.venv`, `requirements-linux-cu126.txt`, or `requirements.lock`

---

## Compatibility decisions

These are intentional. Do not undo them during install retries.

1. **Torch lane is 2.7/cu126**: install `torch==2.7.1`, `torchvision==0.22.1`, and `torchaudio==2.7.1` from `https://download.pytorch.org/whl/cu126`.
2. **`setuptools<81` and `madmom` from git are mandatory**: setuptools 81+ removed `pkg_resources`, which `basic_pitch.inference` and `resampy<0.4.3` still import; pin `setuptools<81` in the constraints file. `madmom` must come from git (`git+https://github.com/CPJKU/madmom.git`) — PyPI's 0.16.1 is from 2018 and won't build against numpy 2.x. The git head builds as `madmom 0.17.dev0` and is required for downbeat detection.
3. **No `numpy<2` reflex**: the stack is intentionally numpy 2.x. Keep `numpy>=2.2,<2.3` unless a specific package proves otherwise.
4. **Basic Pitch on Python 3.11 is special**: `basic-pitch[onnx]` exists, but Basic Pitch's base Linux/Python-3.11 metadata also pulls TensorFlow `<2.15.1`, which is incompatible with this numpy 2.x stack. Install Basic Pitch with `--no-deps` and install its needed ONNX/runtime dependencies explicitly.
5. **No hidden pipe failures**: use `set -euo pipefail` before `pip ... | tee ...`; otherwise `$?` can report `tee`/`tail` success instead of `pip` failure.
6. **Clean venv retries only**: if Phase 3 fails partway, remove `.venv`, `requirements*.txt`, and `install-logs/`, then restart Phase 3.

**allin1 is excluded.** allin1 1.1.0 (last release 2023-10, last commit 2024-05-09) was built against NATTEN ≤0.16's split QK/AV API and RPB. NATTEN ≥0.17 removed RPB, NATTEN ≥0.20 removed the split functional API, and NATTEN's prebuilt `+torch270cu126` wheels have a pre-CXX11 vs CXX11 libtorch ABI mismatch with our installed Torch 2.7. The pretrained checkpoint is welded to legacy NATTEN behavior, so any forward-port is a numerical-correctness gamble. We replace allin1's responsibilities with components already in the stack: `beat-this` becomes the canonical beat tracker, `madmom` (from git) provides downbeats and tempo, and section detection is deferred (see Phase 6 Stage 2b).

---

## Phase 3 - clean venv and installs

Goal: create a clean project venv with Torch 2.7/cu126 and the MIR stack.

Expected time: 15-30 minutes.

Expected disk: about 8-10 GB in `.venv/` plus model caches under `~/.cache/`.

### 3.1 Create the venv

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
source "$HOME/.local/bin/env"
cd "<PROJECT_WSL_PATH>"

uv venv --python 3.11 --seed --clear .venv

source .venv/bin/activate
python --version
python -m pip --version
'
```

Success:
- Python is 3.11.x.
- pip, setuptools, and wheel are present inside `.venv`.

### 3.2 Write constraints and requirements

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"

cat > constraints-torch27-cu126.txt <<CONSTRAINTS
torch==2.7.1
torchvision==0.22.1
torchaudio==2.7.1
numpy>=2.2,<2.3
setuptools<81
CONSTRAINTS

cat > requirements-linux-cu126.txt <<REQS
# Core
numpy>=2.2,<2.3
soundfile
librosa
mir_eval
pretty_midi
scipy
scikit-learn
resampy<0.4.3
typing-extensions
tqdm
rich

# Stems
demucs
audio-separator[gpu]

# Beat tracking (canonical)
beat-this

# Downbeats / tempo (replaces allin1)
git+https://github.com/CPJKU/madmom.git

# Key. Current upstream expects Torch/Torchaudio 2.7-series.
git+https://github.com/deezer/skey.git

# Chords
lv-chordia

# Basic Pitch ONNX runtime deps. Install the basic-pitch package itself with --no-deps in 3.4.
onnxruntime-gpu

# Vocal f0
torchfcpe
pesto-pitch

# Output / interchange
jams
REQS

wc -l constraints-torch27-cu126.txt requirements-linux-cu126.txt
'
```

### 3.3 Install Torch 2.7/cu126

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
source "$HOME/.local/bin/env"
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
mkdir -p install-logs

python -m pip install --upgrade pip "setuptools<81" wheel cython 2>&1 | tee install-logs/00-bootstrap.log

python -m pip install \
  torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
  --index-url https://download.pytorch.org/whl/cu126 \
  2>&1 | tee install-logs/01-torch-cu126.log

python - <<PY
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda)
assert torch.__version__.startswith("2.7.1"), torch.__version__
assert torch.cuda.is_available(), "CUDA not available"
print(torch.cuda.get_device_name(0))
PY
'
```

Success:
- Torch prints `2.7.1+cu126` or equivalent 2.7.1 CUDA 12.6 build.
- CUDA is available.

Failure pivots:

| Symptom | Diagnosis | Fix |
|---|---|---|
| `No matching distribution` for Torch 2.7 | cu126 index not used or platform mismatch | Re-run exactly with `--index-url https://download.pytorch.org/whl/cu126` |
| Torch installs but CUDA not available | CPU-only wheel pulled because index URL was missing or overridden by another constraint | Wipe `.venv` and re-run Phase 3 ensuring the cu126 index URL is the only Torch source |

### 3.4 Install the remaining stack

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
source "$HOME/.local/bin/env"
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
mkdir -p install-logs

python -m pip install -c constraints-torch27-cu126.txt -r requirements-linux-cu126.txt \
  2>&1 | tee install-logs/03-requirements.log

# Avoid Basic Pitch pulling TensorFlow on Linux/Python 3.11.
python -m pip install --no-deps "basic-pitch[onnx]" \
  2>&1 | tee install-logs/04-basic-pitch-nodeps.log

set +e
python -m pip check 2>&1 | tee install-logs/05-pip-check.log
pip_check_status=${PIPESTATUS[0]}
set -e
if [ "$pip_check_status" -ne 0 ]; then
  non_basic_pitch_lines=$(grep -v -E "^basic-pitch .* requires tensorflow" install-logs/05-pip-check.log || true)
  if [ -n "$non_basic_pitch_lines" ]; then
    echo "$non_basic_pitch_lines"
    exit "$pip_check_status"
  fi
  echo "Ignoring Basic Pitch TensorFlow metadata requirement; ONNX path is installed intentionally without TensorFlow."
fi
'
```

Success:
- No `ResolutionImpossible`.
- No attempted downgrade to numpy 1.x.
- No attempted Torch upgrade outside 2.7.x.
- `pip check` has no broken requirements except the intentional Basic Pitch TensorFlow metadata warning. Do not install TensorFlow; verify Basic Pitch ONNX import and prediction in Phase 3.5/6 instead.

### 3.5 Verify imports, CUDA, and snapshot

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
source "$HOME/.local/bin/env"
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate

python - <<PY
import importlib
import torch

print("torch:", torch.__version__, "| CUDA build:", torch.version.cuda)
assert torch.__version__.startswith("2.7.1"), torch.__version__
assert torch.cuda.is_available(), "CUDA not available"
print("GPU:", torch.cuda.get_device_name(0))
print("VRAM free GB:", round(torch.cuda.mem_get_info()[0] / 1e9, 1))

modules = [
    ("numpy", "__version__"),
    ("torch", "__version__"),
    ("torchaudio", "__version__"),
    ("librosa", "__version__"),
    ("soundfile", None),
    ("jams", "__version__"),
    ("madmom", None),
    ("lv_chordia", None),
    ("torchfcpe", None),
    ("pesto", None),
    ("audio_separator", None),
    ("demucs", None),
    ("beat_this", None),
    ("skey", None),
    ("basic_pitch", None),
    ("basic_pitch.inference", None),
    ("onnxruntime", "__version__"),
]

failed = []
for name, attr in modules:
    try:
        module = importlib.import_module(name)
        value = getattr(module, attr, "OK") if attr else "OK"
        print(f"OK {name}: {value}")
    except Exception as exc:
        failed.append((name, type(exc).__name__, str(exc)[:200]))

if failed:
    print("FAILED IMPORTS:")
    for row in failed:
        print(row)
    raise SystemExit(1)
PY

python -m pip freeze > requirements.lock
wc -l requirements.lock
'
```

Success:
- Torch is 2.7.1 and CUDA is available.
- All listed imports succeed.
- `requirements.lock` is written.

---

## Phase 4 - pre-warm model downloads

Goal: download model checkpoints once so first real inference does not hide install problems.

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
source "$HOME/.local/bin/env"
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate

echo "==== audio-separator models ===="
audio-separator --download_model_only --model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt
audio-separator --download_model_only --model_filename htdemucs_6s.yaml

echo "==== beat-this final0 ===="
python - <<PY
try:
    from beat_this.inference import File2Beats
    model = File2Beats(checkpoint_path="final0", device="cuda")
    print("OK File2Beats")
except Exception as exc:
    raise SystemExit(f"beat-this model load failed: {exc}") from exc
PY

echo "==== torchfcpe bundled model ===="
python - <<PY
from torchfcpe import spawn_bundled_infer_model
spawn_bundled_infer_model(device="cuda")
print("OK")
PY

echo "==== basic-pitch import ===="
python - <<PY
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH
print("OK", ICASSP_2022_MODEL_PATH)
PY

echo "==== cache footprint ===="
du -sh ~/.cache/audio-separator/ ~/.cache/torch/ ~/.cache/huggingface/ 2>/dev/null || true
'
```

Success:
- Every section prints `OK`.
- Cache footprint is understood and under available disk limits.

---

## Phase 5 - set up test working directory

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
source "$HOME/.local/bin/env"
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate

mkdir -p cache/gorillaz_silent_running
cat > cache/gorillaz_silent_running/env.sh <<ENV
export TEST_MP3="${MUSIQ_YT_OUT_DIR:-$HOME/Videos/musiq-lab}/Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3"
export TEST_DIR="$(pwd)/cache/gorillaz_silent_running"
ENV

source cache/gorillaz_silent_running/env.sh
test -r "$TEST_MP3"
ffprobe -v error -show_entries format=format_name,duration,bit_rate -of default=nw=1 "$TEST_MP3"
'
```

Success:
- MP3 is readable.
- Duration ≈ 215 s for the test MP3 (3:35). For other tracks, just confirm a non-zero duration is reported.
- Bitrate is plausible for the downloaded MP3.

For every Phase 6 command, source `cache/gorillaz_silent_running/env.sh` first.

---

## Phase 6 - per-stage validation on the Gorillaz track

### Stage 1 - stem separation

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

audio-separator "$TEST_MP3" \
  --model_filename htdemucs_6s.yaml \
  --output_dir "$TEST_DIR/stems_6s/" \
  --output_format WAV

audio-separator "$TEST_MP3" \
  --model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt \
  --output_dir "$TEST_DIR/stems_bsroformer/" \
  --output_format WAV

find "$TEST_DIR" -maxdepth 2 -type f -name "*.wav" -printf "%p\n" | sort
'
```

Success:
- `stems_6s/` has roughly six WAV files.
- `stems_bsroformer/` has vocal/instrumental-style outputs.

### Stage 2a - madmom downbeats and tempo

madmom's RNN downbeat model runs on CPU (it's a custom inference path, not a torch model). That is expected and fine — it's still fast enough for offline analysis.

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
import json, os
import numpy as np
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

mp3 = os.environ["TEST_MP3"]

activations = RNNDownBeatProcessor()(mp3)
tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
beats_with_pos = tracker(activations)  # array of [time, beat_position_in_bar]

beats = [float(t) for t, _ in beats_with_pos]
downbeats = [float(t) for t, pos in beats_with_pos if int(pos) == 1]

if len(beats) >= 2:
    diffs = np.diff(beats)
    median_ibi = float(np.median(diffs))
    bpm = 60.0 / median_ibi if median_ibi > 0 else 0.0
else:
    bpm = 0.0

out = {
    "bpm": float(bpm),
    "beats": beats,
    "downbeats": downbeats,
    "n_beats": len(beats),
    "n_downbeats": len(downbeats),
    "first_8_downbeats": [round(t, 3) for t in downbeats[:8]],
}
with open(os.path.join(os.environ["TEST_DIR"], "madmom_downbeats.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ["bpm", "n_beats", "n_downbeats", "first_8_downbeats"]}, indent=2))
PY
'
```

Success:
- Tempo is in a plausible 70-180 BPM range.
- Downbeats are roughly evenly spaced (consistent with `beats_per_bar` of 3 or 4).
- `madmom_downbeats.json` is written.

### Stage 2b - sections (DEFERRED)

Section detection is not currently provided in this stack. allin1 supplied joint sections; without it, we have no installed segmenter. Possible future paths:

- `msaf` (likely numpy 1.x bound — would need a separate venv).
- librosa-based recurrence-matrix segmentation (boundaries only, no labels).
- A small custom model trained on SALAMI or similar.

**For this validation, sections are skipped.** Optionally write a placeholder so downstream code can detect the gap:

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source cache/gorillaz_silent_running/env.sh

python - <<PY
import json, os
out = {
    "status": "deferred",
    "reason": "No segmenter installed in this stack; allin1 dropped due to NATTEN ABI/API breakage.",
}
with open(os.path.join(os.environ["TEST_DIR"], "sections.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
PY
'
```

### Stage 3 - beat-this (canonical beat tracker)

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
import json, os
from beat_this.inference import File2Beats

model = File2Beats(checkpoint_path="final0", device="cuda")
beats, downbeats = model(os.environ["TEST_MP3"])
out = {
    "beats": [float(t) for t in beats],
    "downbeats": [float(t) for t in downbeats],
    "n_beats": len(beats),
    "n_downbeats": len(downbeats),
    "first_8_beats": [round(float(t), 3) for t in beats[:8]],
    "first_8_downbeats": [round(float(t), 3) for t in downbeats[:8]],
}
with open(os.path.join(os.environ["TEST_DIR"], "beat_this.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ["n_beats", "n_downbeats", "first_8_beats", "first_8_downbeats"]}, indent=2))
PY
'
```

Success:
- Beat count is plausible for track duration.
- Sanity check: average inter-beat interval from beat-this should be consistent with the gap between successive `madmom_downbeats.json` downbeats divided by `beats_per_bar` (3 or 4). Large divergences (>~10%) indicate a tempo-octave disagreement worth flagging for reconciliation.

### Stage 4 - key detection via skey (with librosa Krumhansl-Schmuckler safety net)

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
import json, os

key = conf = src = None
errors = []

# skey 0.1.0 entry point is `skey.key_detection.detect_key`, NOT `skey.inference.predict_key`
# (the latter does not exist in upstream).
try:
    from skey.key_detection import detect_key
    result = detect_key(os.environ["TEST_MP3"], device="cuda", cli=False)
    if result:
        key = result[0] if isinstance(result, list) else str(result)
        conf = 1.0  # detect_key returns argmax labels, not probabilities
        src = "skey.detect_key"
except Exception as exc:
    errors.append(f"skey.detect_key failed: {type(exc).__name__}: {exc}")

if not key or key == "error":
    import librosa, numpy as np
    src = "librosa_ks"
    KS_MAJ = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    KS_MIN = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
    y, sr = librosa.load(os.environ["TEST_MP3"], duration=120)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = max(
        [(notes[i] + ":" + mode, np.corrcoef(np.roll(chroma, -i), profile)[0, 1])
         for i in range(12) for mode, profile in [("major", KS_MAJ), ("minor", KS_MIN)]],
        key=lambda row: row[1],
    )
    key, conf = best[0], float(best[1])

out = {"key": str(key), "confidence": float(conf), "source": src, "errors": errors}
with open(os.path.join(os.environ["TEST_DIR"], "skey.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
PY
'
```

Success: skey returns a key string (e.g. `F minor`); a librosa Krumhansl-Schmuckler fallback fires only if skey raises.

### Stage 5 - chord recognition via lv-chordia

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
import json, os

chords = None
errors = []

try:
    from lv_chordia.chord_recognition import chord_recognition
    raw = chord_recognition(os.environ["TEST_MP3"], chord_dict_name="submission")
    chords = [
        {
            "start": float(item.get("start_time", item.get("start", 0.0))),
            "end": float(item.get("end_time", item.get("end", 0.0))),
            "label": str(item.get("chord", item.get("label", "N"))),
        }
        for item in raw
    ]
except Exception as exc:
    errors.append(f"lv-chordia python API failed: {type(exc).__name__}: {exc}")

if chords is None:
    # lv-chordia has no `__main__.py` so `python -m lv_chordia` does not work.
    # The Python API above is the only supported entry point — surface the error directly.
    raise SystemExit("\n".join(errors))

with open(os.path.join(os.environ["TEST_DIR"], "chords.json"), "w") as f:
    json.dump(chords, f, indent=2)

print(f"Found {len(chords)} chord events")
for c in chords[:12]:
    start = c["start"]
    end = c["end"]
    label = c["label"]
    print(f"{start:7.2f}-{end:7.2f}: {label}")
if errors:
    print("Fallback notes:")
    for err in errors:
        print(err)
PY
'
```

Success:
- 30-150 chord events is plausible for this track.
- Labels are Harte-like chord labels or `N`.

### Stage 6 - Basic Pitch per harmonic stem

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
import glob, json, os
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

stems_dir = os.path.join(os.environ["TEST_DIR"], "stems_6s")
out_dir = os.path.join(os.environ["TEST_DIR"], "midi")
os.makedirs(out_dir, exist_ok=True)

params = {
    "vocals": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "bass": dict(onset_threshold=0.4, minimum_note_length=100, minimum_frequency=27.5),
    "guitar": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "piano": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=27.5),
    "other": dict(onset_threshold=0.6, minimum_note_length=100, minimum_frequency=80),
}

results = {}
for wav in glob.glob(os.path.join(stems_dir, "*.wav")):
    name = os.path.basename(wav).lower()
    matched = next((key for key in params if key in name), None)
    if matched is None or "drum" in name:
        print("skip:", name)
        continue
    print("transcribing", matched)
    model_output, midi_data, note_events = predict(
        wav,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        multiple_pitch_bends=True,
        melodia_trick=True,
        **params[matched],
    )
    midi_path = os.path.join(out_dir, f"{matched}.mid")
    midi_data.write(midi_path)
    results[matched] = {"notes": len(note_events), "midi": midi_path}
    print(matched, len(note_events), "notes")

with open(os.path.join(os.environ["TEST_DIR"], "transcription_summary.json"), "w") as f:
    json.dump(results, f, indent=2)
print(json.dumps(results, indent=2))
PY
'
```

Success:
- Harmonic stems produce MIDI files.
- Note counts are nonzero and plausible.

### Stage 7 - vocal f0 via FCPE and PESTO

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
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
'
```

Success:
- FCPE and PESTO both produce frame sequences.
- Full-track isolated-vocal agreement of ~75-90% within 50 cents is normal (measured 80.0% on the validation run). Below 70% across full track suggests either a vocal stem with heavy bleed, or a real install/model issue worth investigating.

### Stage 8 - reconciliation skeleton

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<PY
import json, os

test_dir = os.environ["TEST_DIR"]
madmom_data = json.load(open(os.path.join(test_dir, "madmom_downbeats.json")))
chords = json.load(open(os.path.join(test_dir, "chords.json")))
key_data = json.load(open(os.path.join(test_dir, "skey.json")))

downbeats = madmom_data["downbeats"]
if not downbeats:
    raise SystemExit("No downbeats available for snapping")

def nearest_downbeat(t):
    return min(downbeats, key=lambda d: abs(d - t))

summary = {
    "key": key_data["key"],
    "key_source": key_data["source"],
    "tempo_bpm": madmom_data["bpm"],
    "first_12_chords_snapped": [],
}
for chord in chords[:12]:
    summary["first_12_chords_snapped"].append({
        "snap_start": round(nearest_downbeat(chord["start"]), 3),
        "original_start": round(chord["start"], 3),
        "label": chord["label"],
    })

with open(os.path.join(test_dir, "reconciliation_preview.json"), "w") as f:
    json.dump(summary, f, indent=2)
print(json.dumps(summary, indent=2))
PY
'
```

Success:
- Uses the full `downbeats` list, not just the first eight downbeats.
- Produces `reconciliation_preview.json`.

---

## Exit criteria

The stack is validated only when all are true:

- Phase 3 installs Torch 2.7.1/cu126 and does not upgrade or downgrade Torch afterward.
- `skey` installs without forcing Torch away from 2.7.
- Basic Pitch imports without TensorFlow being installed.
- `madmom` from git installs and produces downbeats on the Gorillaz track.
- `setuptools` is pinned `<81` so `pkg_resources` remains importable for `basic_pitch.inference` and `resampy`.
- Phase 4 model pre-warm succeeds or records a specific external download failure.
- Phase 6 stages 1-7 complete on the Gorillaz track (Stage 2b sections is explicitly deferred).
- Stage 8 writes a sensible `reconciliation_preview.json`.

After validation, document deviations in `CLAUDE.md` before building production `analyze.py`.

---

## Rollback

If Phase 3 goes badly:

```powershell
& "C:\Program Files\WSL\wsl.exe" --distribution-id "{1c646321-14ab-419e-81e0-9c41b56e9447}" -- bash -lc '
set -euo pipefail
cd "<PROJECT_WSL_PATH>"
rm -rf .venv requirements-linux-cu126.txt constraints-torch27-cu126.txt requirements.lock install-logs cache/gorillaz_silent_running
'
```

Do not remove apt packages, uv, or uv-managed Python unless explicitly troubleshooting those layers.

---

## Known risks

- `basic-pitch[onnx]` is valid, but installing it normally on Linux/Python 3.11 can still pull TensorFlow through base package metadata. The `--no-deps` install is intentional.
- `skey` is git-installed (`git+https://github.com/deezer/skey.git`). Verified entry point on 0.1.0: `skey.key_detection.detect_key(audio, device='cuda', cli=False)`. If upstream renames again, fall back to librosa Krumhansl-Schmuckler — do NOT rely on the skey CLI, which has no JSON-output flag and prints to stdout only.
- `lv-chordia` 1.0.0 has no `__main__.py` — `python -m lv_chordia` does not work. Only the Python API (`from lv_chordia.chord_recognition import chord_recognition; chord_recognition(audio, chord_dict_name='submission')`) is supported.
- The `beat-this` Python API should use `File2Beats`. If upstream changes again, prefer the documented package CLI or inspect the installed module inside `.venv`.
- `madmom` from git is `0.17.dev0` — uses Cython extensions that build cleanly on numpy 2.x as of writing. If the git head is broken at build time, fall back to a known-good commit (current head when this runbook was written is the master branch around 2026-04). The PyPI 0.16.1 release does NOT work on numpy 2.x; do not pin to it.
- Section detection is not implemented. The reconciliation output therefore has no section labels. Acceptable for current validation; revisit if a sections backbone is added later.

---

## Reproducibility notes

- **Windows → WSL invocation pattern.** When invoking via `wsl.exe -- bash -lc '...'` from PowerShell with multi-statement scripts that include heredocs and `source`, variable propagation across statements has been observed to be flaky in this environment. The reliable invocation pattern is: write the bash body to a `.sh` file under `/mnt/f/...` and execute as `wsl.exe -- bash /mnt/f/.../script.sh`. Both forms work when run directly from inside WSL — the issue is purely the PowerShell→wsl.exe arg-passing layer.
- **Lock file convergence.** The validated run produced `requirements.lock` (131 packages). Re-running Phase 3 should converge to the same lock file modulo dated git revisions of `madmom` and `skey`. To pin those exactly, copy the resolved versions from `requirements.lock` into the requirements file.
- **Expected artifacts.** Downstream code can rely on the following artifact names produced by Phase 6:

| Artifact | Phase | Notes |
|---|---|---|
| `cache/<track>/stems_6s/*.wav` | 6.1 | 6 WAVs, htdemucs_6s |
| `cache/<track>/stems_bsroformer/*.wav` | 6.1 | 2 WAVs (Vocals/Instrumental) |
| `cache/<track>/madmom_downbeats.json` | 6.2a | bpm, beats[], downbeats[] |
| `cache/<track>/sections.json` | 6.2b | `{"status": "deferred", ...}` |
| `cache/<track>/beat_this.json` | 6.3 | beats[], downbeats[] |
| `cache/<track>/skey.json` | 6.4 | key, confidence, source |
| `cache/<track>/chords.json` | 6.5 | normalised list of `{start, end, label}` |
| `cache/<track>/midi/*.mid` | 6.6 | one per harmonic stem |
| `cache/<track>/transcription_summary.json` | 6.6 | per-stem note counts |
| `cache/<track>/vocal_f0.npz` + `vocal_f0_summary.json` | 6.7 | FCPE+PESTO arrays + agreement summary |
| `cache/<track>/reconciliation_preview.json` | 6.8 | key, tempo, snapped chord previews |
