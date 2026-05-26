# Installation

Setup for **WSL2 Ubuntu 24.04 on JINN** (RTX 3090, miniforge already present). Three install layers: system deps via apt, Python 3.11 via uv, project venv with pip.

## Prerequisites (already verified on this machine)

- ✅ Ubuntu 24.04 in WSL2
- ✅ NVIDIA driver 595+, CUDA passthrough working (`nvidia-smi` returns `RTX 3090, 24576 MiB`)
- ✅ pytorch already installable with CUDA support (`torch.cuda.is_available() == True` confirmed in existing `py3.13` env)
- ✅ ffmpeg already installed system-wide at `/usr/bin/ffmpeg`
- ✅ Internet to PyPI / HuggingFace / GitHub all 200 OK
- ✅ Project folder mounted at `<PROJECT_WSL_PATH>/`

If you're reading this on a fresh machine, run the WSL probe in [`pipeline.md`](pipeline.md) first to verify these.

## Layer 1 — System dependencies (apt, requires sudo)

One-time install of system libraries that aren't pip-installable.

```bash
sudo apt update
sudo apt install -y \
    build-essential cmake pkg-config \
    libsndfile1-dev libsamplerate0-dev libfftw3-dev \
    sox vamp-plugin-sdk vamp-examples sonic-annotator
```

**Why each:**
- `build-essential cmake pkg-config` — needed for any pip package that compiles native extensions (madmom is a transitive dep of `allin1`, requires Cython compile)
- `libsndfile1-dev libsamplerate0-dev libfftw3-dev` — audio I/O headers for librosa/torchaudio backends
- `sox` — utility for one-off resampling/format conversion
- `vamp-plugin-sdk vamp-examples sonic-annotator` — host for Chordino if we ever fall back from `lv-chordia` to `chord-extractor`

`ffmpeg` is already installed; if it's not on a fresh machine, add `ffmpeg` to the list.

## Layer 2 — Python 3.11 via uv (no sudo, ~5 seconds)

Ubuntu 24.04 ships Python 3.12 by default. We want **3.11** because several MIR packages (`allin1`'s madmom transitive dep, `lv-chordia`'s pinning) have smoother install on 3.11 than 3.12.

```bash
# Install uv (single binary, no global Python pollution)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # or restart shell

# Have uv download a standalone Python 3.11 (managed in uv's cache)
uv python install 3.11
```

**uv is not conda.** It's a small Rust binary that handles Python installs and venv creation. After it sets up the venv, you use plain `pip install` from inside that venv. uv only appears in the bootstrap step.

If you'd rather not use uv:

- **Alternative A**: deadsnakes PPA — `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.11 python3.11-venv`. Adds an external repo to the system.
- **Alternative B**: use the system Python 3.12 — works for most of the stack but `allin1` install can be flaky on 3.12. Acceptable risk for a quick start.

## Layer 3 — Project venv + Python deps (pip)

```bash
cd "<PROJECT_WSL_PATH>"

# Create the project-local venv with Python 3.11
uv venv --python 3.11 .venv

# Activate (from this point on, just plain pip)
source .venv/bin/activate

# Install PyTorch with CUDA first (some packages need it during their own install)
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install the rest of the stack
pip install -r requirements-linux-cu126.txt

# Pin exact versions for reproducibility
pip freeze > requirements.lock
```

Once this is done, the `.venv/` folder lives **inside the project** — true "embedded Python install" semantics. Move the project folder, the env moves with it. Recreate from `requirements.lock` (or `requirements-linux-cu126.txt`) on any machine.

## Layer 4 — Models / weights (downloaded on first use)

Most packages download model weights lazily on first inference. To pre-warm the cache (optional, but useful before going offline):

```bash
# Stems — pre-fetch the recommended BS-RoFormer model
audio-separator --download_model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt

# allin1 — pre-fetch its bundled checkpoints (does this on first run anyway)
python -c "import allin1; allin1.analyze('test.wav') if False else None"

# beat-this — model auto-loads on first call to load_model('final0')
python -c "from beat_this.inference import load_model; load_model('final0', device='cuda')"

# torchfcpe — bundled model
python -c "from torchfcpe import spawn_bundled_infer_model; spawn_bundled_infer_model(device='cuda')"

# basic-pitch — model bundled in the package, no download needed

# skey — clone repo, weights are in the repo
pip install git+https://github.com/deezer/skey.git
```

Models live in:
- `~/.cache/audio-separator/` — UVR models
- `~/.cache/torch/hub/` — beat-this, torchfcpe
- `~/.cache/allin1/` — All-In-One checkpoints
- `~/.cache/huggingface/` — anything via HF Transformers (e.g. MERT if you add it)

Total model footprint: ~5 GB. Cleanable via `rm -rf ~/.cache/audio-separator/` etc. if you ever need disk back.

## requirements-linux-cu126.txt

Recommended pin set. Paste into `<PROJECT_PATH>\requirements-linux-cu126.txt`:

```text
# Core (no numpy pin — let pip resolve; skey requires >=2.2 in practice)
soundfile
librosa
mir_eval
pretty_midi
tqdm
rich

# Stems
demucs
audio-separator[gpu]

# Joint beats / downbeats / tempo / sections
allin1

# Beat cross-check
beat-this

# Key (git, no PyPI release yet)
git+https://github.com/deezer/skey.git

# Chords
lv-chordia

# Polyphonic transcription
basic-pitch[onnx]         # ONNX backend (avoids TF 2.14 numpy 1.x ABI clash)

# Vocal f0
torchfcpe
pesto-pitch

# Output / interchange
jams

# Optional / advanced (commented; uncomment if needed)
# mr-mt3 @ git+https://github.com/gudgud96/MR-MT3.git    # 🧪 multi-instrument transcription
# transformers                                             # for MERT embeddings
```

PyTorch is installed separately (above) because the CUDA-suffixed wheel index URL doesn't play well in `requirements-linux-cu126.txt` for a multi-platform team. Single-machine: install torch first, then this file.

## Verifying the install

```bash
source .venv/bin/activate
python -c "
import torch, librosa, jams, basic_pitch, allin1, lv_chordia, torchfcpe, pesto
import audio_separator
print('torch CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')
print('OK')
"
```

If everything imports and CUDA is True, you're good.

## Common install issues

### `allin1` fails with NATTEN error

NATTEN (Neighborhood Attention Transformer kernels) is the most fragile dep in the stack. Symptoms: `ImportError: cannot import name 'natten'`, or compile errors.

**Fix**:
```bash
pip uninstall natten
# Match the wheel to your PyTorch + CUDA version. Visit https://www.shi-labs.com/natten/wheels/
# and copy-paste the install command for torch+cu121 (or whatever you have).
# Example for torch 2.5 + cu121:
pip install natten==0.17.5 -f https://shi-labs.com/natten/wheels/cu121/torch250
```

If that still fails, try the community-maintained `all-in-one-fix` package which bundles compatible NATTEN versions:

```bash
pip install allin1fix
```

### `madmom` install fails (transitive dep of `allin1`)

madmom's PyPI release is from 2018. `allin1` requires the git master version which has Cython compile fixes. Symptom: `error: invalid command 'bdist_wheel'` or Cython errors.

**Fix**:
```bash
pip install --upgrade pip setuptools wheel cython
pip install git+https://github.com/CPJKU/madmom.git
```

Then retry `allin1`.

### `skey` import errors

The deezer/skey repo expects PyTorch and torchaudio specific versions. If imports fail:

```bash
cd /tmp
git clone https://github.com/deezer/skey.git
cd skey
pip install -e .  # editable install gives clearer error messages
```

### `lv-chordia` complains about `pumpp` or `mir-eval`

`lv-chordia` has older deps. Force-reinstall:

```bash
pip install --upgrade --no-cache-dir lv-chordia mir-eval pumpp
```

### Out of VRAM during ensemble inference

> **Note (May 2026):** the `--sequential` flag described in earlier versions of
> this doc was never implemented in `analyze/cli.py`. The shipped pipeline
> already runs stages strictly sequentially (`analyze/pipeline.py:527`), and
> each GPU stage cleans up via `gc.collect() + torch.cuda.empty_cache()` in a
> `finally` block (the "lv-chordia pattern", see `analyze/stages/chords.py`).
> Peak VRAM is therefore bounded by the single heaviest stage (~6–10 GB), not
> the sum across stages.

If you're still seeing memory pressure:

1. **Use the lighter stems preset.** `python -m analyze <mp3> --stems-quality fast`
   reduces Demucs `shifts` from 8 → 2 (see `analyze/stages/stems.py:52-57`),
   which shrinks intermediate tensor sizes during separation. Same model,
   smaller working set.
2. **Skip optional stages.** `--stages-only stems,beats,key,chords,transcription`
   confines the run to the 5 required stages and skips `vocal_f0`, `drums`,
   `beats_xcheck`, `stems_dynamics`, and `vocal_consensus_contour`.
3. **Set the PyTorch allocator fragmentation knob:**
   ```bash
   export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
   ```
   This is safe for this codebase (no multi-process DataLoader workers).
4. **Free up VRAM on the Windows side first** — anything else holding GPU
   memory (browser hardware accel, ComfyUI sitting idle with a loaded model,
   etc.) eats from the same 24 GB pool that WSL2 sees.

#### WSL2-specific: you almost never get a clean OOM

On native Linux, exhausting VRAM produces `CUDA_ERROR_OUT_OF_MEMORY` and the
stage fails fast. **On WSL2 (this project's runtime) you do not get that.**
NVIDIA's "CUDA Sysmem Fallback Policy" (driver 536.40+, July 2023) silently
spills allocations into Windows shared GPU memory (system RAM via WDDM) once
physical VRAM is exhausted. The Windows NVIDIA Control Panel toggle that would
disable this on a native Windows app **does not propagate into WSL2** — the
fallback is always on inside WSL and there is no in-WSL switch
(`microsoft/WSL` #11050, open as of May 2026).

The practical consequence for `python -m analyze`:

- It will *not* crash even if free VRAM is well under the documented 6 GB
  floor.
- Instead the stage that should take ~100 s under normal Demucs separation may
  take **many minutes** as tensors round-trip across PCIe.
- `nvidia-smi` will not flag this — it only reports physical VRAM. The
  authoritative signal is **Windows Task Manager → Performance → GPU →
  "Shared GPU memory"**; if that climbs above zero during a stage, you've hit
  spillover.
- `install-logs/_vram_watch.sh` can be run alongside the analyze invocation
  for a stage-tagged VRAM trace. If physical-VRAM usage looks fine but a stage
  takes 5–10× longer than the figures in `docs/research/pipeline.md`, suspect
  spillover before suspecting the model.

The 96 GB system RAM on JINN means the spillover ceiling is effectively
unreachable for this workload — the cost of low VRAM here is wall-time, not
crashes.

## Project-local Python is "embedded" enough

`.venv/` lives inside `<PROJECT_PATH>\.venv\`. Anyone (or any future Claude session) can:

```bash
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
python analyze.py <mp3>
```

If `.venv/` is deleted or the project is moved to another machine, recreate with:

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
pip install -r requirements.lock
```

The `requirements.lock` (committed) ensures byte-identical reproducibility.
