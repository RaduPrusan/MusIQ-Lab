# Beats, downbeats, tempo

> ⚠️ **Status (2026-04-29):** This page was rewritten after `allin1` was dropped from the stack (see [`../../history.md`](../../history.md) Phase D). The current canonical setup is **`madmom` for downbeats + tempo, `beat-this` for beats**. The historical `allin1` content is preserved at the bottom of this page for the *why*, not as install instructions. Source of truth for the executable runbook is [`../../../prompts/test-stack-torch27.md`](../../../prompts/test-stack-torch27.md).

This stage produces the time grid the rest of the pipeline aligns to:
- Beats (every musical beat)
- Downbeats (the first beat of each bar)
- Tempo (BPM)

Section detection is **deferred** — see [`07-section-analysis.md`](07-section-analysis.md). It used to be bundled into `allin1`; with allin1 gone there is currently no segmenter installed.

## ✅ Recommended primary (downbeats + tempo): `madmom` (git main)

`madmom` is installed from git main (not from PyPI — the PyPI release is several years old and lacks numpy 2.x compatibility fixes). Used here for downbeats and tempo via the standard RNN + DBN pipeline.

### Install

Already part of `requirements.lock`:

```bash
pip install "git+https://github.com/CPJKU/madmom.git@main"
```

You also need `setuptools<81` in the venv because `madmom`, `basic_pitch.inference`, and `resampy<0.4.3` all still import the removed `pkg_resources` module. The runbook pins this.

### Usage — Python

```python
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor
import numpy as np

rnn = RNNDownBeatProcessor()
dbn = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)

beats = dbn(rnn("song.mp3"))
# beats is an (N, 2) array: column 0 = time in seconds, column 1 = beat-position-in-bar (1 = downbeat)

beat_times     = beats[:, 0]
downbeat_times = beats[beats[:, 1] == 1, 0]
tempo_bpm      = 60.0 / np.median(np.diff(beat_times))
```

### Why `madmom` for this role

- **Robust on most material.** The RNN+DBN combo is older but still competitive for downbeat detection specifically (where beat-this is more focused on the unsegmented beat track).
- **Already a transitive of `beat-this`**, so installing it for direct use adds no new wheels.
- **Tempo is derived analytically** from the median inter-beat interval rather than predicted as a separate output — simpler, no additional model.

### Caveats

- Older RNN architecture (pre-transformer); doesn't benefit from demixed input.
- **Tempo doubling on jazz / swing material.** Observed during batch validation: Chet Baker's *Autumn Leaves* came back as 187.5 BPM (real ≈93). Both `madmom` and `beat-this` lock onto the 8th-note swing pulse on this material — a classic MIR failure mode shared across beat trackers, not a `madmom` bug. See [`../../../install-logs/batch-test-results.md`](../../../install-logs/batch-test-results.md).
- Slow CPU-only inference (no GPU path). On a modern CPU still tractable for offline analysis.

## ✅ Recommended primary (beats): `beat-this` (final0)

ISMIR 2024 pure-neural beat tracker. In the original design this was a cross-check; after the allin1 drop it became the **canonical beat track**. Madmom's beats are kept as a second voice in the JAMS but the canonical beats reported in `summary.json` come from `beat-this`.

### Install

```bash
pip install beat-this
```

### Usage — Python

```python
from beat_this.inference import File2Beats

f2b = File2Beats(checkpoint_path="final0", device="cuda")
beats, downbeats = f2b("song.mp3")
# Both are 1-D numpy arrays of seconds
```

(The runbook uses the `File2Beats` class, not `load_model` — the former is the documented public API as of the current `beat-this` release.)

### Why `beat-this` for this role

- **Pure-neural — no DBN postprocessing.** Different inductive biases than madmom's RNN+DBN, so disagreement between the two correlates with metrical ambiguity (syncopation, hemiola, swing feel) — pedagogically useful.
- **GPU-accelerated**, so it's the fast path for beats specifically.
- **Designed to obsolete madmom's DBN approach** (per the ISMIR 2024 paper), so it's the more modern pick where the two compete (i.e. for the beat track itself).

### Caveats

- The `beat-this` package has a `madmom` transitive (which is fine — we want it anyway).
- Less mature ecosystem than allin1; primarily a research artifact.

## ↳ Fallback: librosa

If both `madmom` and `beat-this` somehow fail (rare), librosa's classic `beat.beat_track` still works:

```python
import librosa
y, sr = librosa.load("song.mp3", sr=22050)
tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
beat_times = librosa.frames_to_time(beats, sr=sr)
```

librosa **does not** detect downbeats — beat-only. Use only as last resort. Pipeline already requires beats + downbeats as a hard-fail stage, so falling back to librosa would mean accepting a chord-snap-disabled run.

## 🧪 Historical pick (rejected): `allin1`

`allin1` was the original recommended primary in the design phase. It would have produced beats + downbeats + tempo + functional sections in a single transformer pass. We are no longer using it.

**Why it was attractive:**
- Joint prediction (tasks share latent structure — downbeats correlate with section boundaries; tempo influences beat density).
- Demixed-input (internally separates with Demucs before metrical analysis).
- Functional section labels (verse/chorus/bridge/...), not just boundaries.
- WASPAA 2023 SOTA on Harmonix Set across all four jointly-predicted tasks.

**Why we dropped it (April 2026):**
- `allin1` 1.1.0 hardcodes a NATTEN API that no longer exists (calls `natten1dav` etc. from `natten.functional`; those names were removed in NATTEN ≥0.20).
- More fundamentally, `allin1`'s pretrained checkpoint encodes **relative positional bias (RPB)** weights; RPB was deprecated in NATTEN 0.17 and is now completely absent from the source tree. Reproducing RPB on top of fused `na2d` is research-grade work.
- NATTEN's prebuilt `+torch270cu126` wheels have a CXX11 ABI mismatch against PyTorch 2.7's `libc10.so` (undefined-symbol failures at import time).
- We can't bump Torch off 2.7 (skey hard-pins `torch = "~2.7.0"`) to reach a NATTEN ≥0.21 lane where modern wheels exist.

Full diagnosis: [`../../history.md`](../../history.md) Phase D.

If `allin1` ever sheds its NATTEN dependency (or NATTEN ships a Torch 2.7 wheel with the right ABI and someone backports `allin1` to use modern `na2d`), this is the keystone pick to revisit.

## 🧪 Experimental: BEAST (online beat tracking)

ICASSP 2024 streaming beat tracker. Useful only for real-time beat tracking (live performance applications). For offline analysis the `madmom` + `beat-this` combo is what we use.

Repo: <https://github.com/WildHoneyPie/BEAST>

## Cross-validation in the current pipeline

Beats / downbeats / tempo feed:

- **Stage 5 (chords)**: chord boundaries are snapped to the nearest downbeat (from `madmom`). This is the highest-leverage cross-validation in the pipeline — fixes wobbly chord transitions without touching the chord recognizer. Implementation: `analyze/writers/jams_writer.py:_build_chord_snapped_annotation`.
- **`summary.json`**: `tempo_bpm` (from madmom) and `downbeats[]` are emitted. Full beat tracks (both madmom and beat-this) stay in the JAMS file as separate annotations so a downstream consumer can compare them.

## Sources

- madmom RNN+DBN downbeat paper: <https://archives.ismir.net/ismir2016/paper/000186.pdf>
- madmom repo: <https://github.com/CPJKU/madmom>
- Beat This! paper (ISMIR 2024): <https://arxiv.org/abs/2407.21658>
- Beat This! repo: <https://github.com/CPJKU/beat_this>
- librosa beat tracking: <https://librosa.org/doc/main/generated/librosa.beat.beat_track.html>
- All-In-One paper (WASPAA 2023, historical context): <https://arxiv.org/abs/2307.16425>
- All-In-One repo (historical context): <https://github.com/mir-aidj/all-in-one>
