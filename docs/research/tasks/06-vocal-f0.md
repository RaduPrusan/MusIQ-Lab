# Vocal melody f0 contour

Continuous monophonic pitch curve over time for the isolated vocals stem. Captures vibrato, glissandos, scoops, melismas, and the actual pitch contour between transcribed notes — the *expressive* layer of a vocal performance that quantised MIDI from Stage 6 throws away.

Run **only** on the vocals stem (from Stage 1), never on the full mix.

## ✅ Recommended primary: `torchfcpe` (FCPE)

Fast Context-based Pitch Estimation, 2024 paper. Uses a Lynx-Net backbone with depth-wise separable convolutions. ~96.79% raw pitch accuracy on benchmark vocal data, RTF ≈ 0.006 on RTX 4090 (essentially free).

### Install

```bash
pip install torchfcpe
```

### Usage — Python

```python
import librosa
import torch
from torchfcpe import spawn_bundled_infer_model

model = spawn_bundled_infer_model(device="cuda")

audio, sr = librosa.load("vocals.wav", sr=16000, mono=True)
audio_t = torch.from_numpy(audio).unsqueeze(0).to("cuda")

f0 = model.infer(
    audio_t,
    sr=16000,
    decoder_mode="local_argmax",   # recommended; alternatives: "argmax", "weighted_argmax"
    threshold=0.006,                # voicing threshold
    f0_min=80,                      # Hz, ~E2 (lowest male vocal)
    f0_max=880,                     # Hz, ~A5 (high female vocal)
    interp_uv=False,                # don't interpolate over unvoiced frames
)
# f0 shape: (1, num_frames, 1) — Hz values; 0 or NaN for unvoiced frames
```

### Output format

A 1-D NumPy array (or PyTorch tensor) of f0 values in Hz, one per frame. Frame rate is determined by the model's hop size; default is ~10 ms per frame (100 Hz frame rate). Unvoiced frames have value 0 (or NaN depending on `interp_uv`).

In `summary.json`:

```json
"f0": [
  {"t": 0.00, "hz": null, "voiced": false},
  {"t": 8.21, "hz": 392.0, "voiced": true},
  {"t": 8.30, "hz": 393.5, "voiced": true},
  ...
]
```

### Why FCPE wins as primary

- **2024 architecture** — newer than CREPE (2018) or PESTO (2023)
- **96.79% raw pitch accuracy** on benchmark singing data
- **Fast**: RTF 0.006 on a 4090 means a 4-minute song processes in ~1.5 seconds. Trivial cost
- **Lynx-Net depth-wise-separable convs** — efficient backbone with strong noise tolerance
- Recommended by Gemini's research; original 2024 paper

### Caveats

- **Monophonic** — feed only the isolated vocals stem from Stage 1, never full-mix audio
- 16 kHz sample rate expected; resample your vocals stem if it's 44.1 kHz (Stage 1's BS-RoFormer outputs 44.1 kHz; we resample at the boundary)
- f0 range bounds (`f0_min` / `f0_max`) must match the singer's range or you get edge artefacts. Defaults of 80–880 Hz cover most popular music vocals; for opera or instrumental f0, widen the range
- Frame rate is fixed by the model; for higher resolution you'd need a different model

## ✅ Recommended cross-check: `pesto-pitch`

ISMIR 2023, self-supervised, transposition-equivariant. Different inductive biases than FCPE, so it catches different failure modes. Used purely as a second voice for reconciliation in Stage 8.

### Install

```bash
pip install pesto-pitch
```

### Usage — Python

```python
import pesto
import torchaudio

audio, sr = torchaudio.load("vocals.wav")
# pesto expects 16 kHz mono
audio_16k = torchaudio.functional.resample(audio, sr, 16000).mean(0, keepdim=True)

timestamps, pitch_hz, confidence, activations = pesto.predict(
    audio_16k.squeeze(0),
    sr=16000,
    step_size=10.0,                # 10 ms hop = 100 Hz frame rate (matches FCPE)
    inference_mode="cqt",
)
# pitch_hz is per-frame Hz; confidence is per-frame in [0, 1]
```

### Why PESTO as cross-check

- **Self-supervised, transposition-equivariant** — fundamentally different inductive bias than FCPE's supervised Lynx-Net
- Disagreement frames flag uncertain regions (vibrato bottom/top, octave errors, voiced/unvoiced ambiguity)
- ~12× faster than CREPE; comparable accuracy

### Caveats

- Same monophonic-input requirement as FCPE
- 16 kHz expected; resample as above
- Same f0 range considerations

## ↳ Alternative: `crepe` (older baseline)

Original convolutional pitch tracker, 2018. Still works, still cited, but ~12 minutes inference per song vs ~1 second for FCPE. Use only as a sanity check or for academic-baseline comparisons.

```bash
pip install crepe          # TensorFlow backend
# or
pip install torchcrepe     # PyTorch backend (recommended)
```

## ↳ Alternative: `rmvpe-onnx`

Robust Vocal Pitch Estimation. Strong practical results on singing voice; popular in voice-conversion (RVC) ecosystems. Recommended by Codex's research as the practical singing f0 choice.

```bash
pip install rmvpe-onnx
```

### When to prefer

- You're integrating with the RVC voice-conversion ecosystem
- FCPE results show artefacts on a specific singer

We use FCPE as primary because the bundled model + clean PyTorch API is more ergonomic, but RMVPE is a perfectly valid third voice if you want to try it.

## Cross-validation hooks

Vocal f0 feeds:

- **Stage 6 (vocal MIDI) cross-check**: the f0 contour should pass through each transcribed MIDI note's pitch. Large deviation (> ±50 cents sustained) → flag the MIDI note as having significant pitch bend / vibrato (or being a transcription error)
- **Stage 8 → educational analysis**: f0 contour resolution captures vibrato rate, depth, scoops, falls — pedagogically rich expressive content
- **Stage 8 reconciliation between FCPE and PESTO**:

```python
# Pseudocode
TOL_CENTS = 50  # ±50 cents agreement window
for f, p in zip(fcpe_f0, pesto_f0):
    if not voiced(f) and not voiced(p):
        merged.append({"hz": None, "voiced": False, "conf": 1.0})
    elif voiced(f) and voiced(p):
        cents_diff = 1200 * abs(log2(f) - log2(p))
        if cents_diff < TOL_CENTS:
            merged.append({"hz": (f + p) / 2, "voiced": True, "conf": 1.0})
        else:
            # disagreement — typically octave error or vibrato extreme
            merged.append({"hz": f, "voiced": True, "conf": 0.5,
                           "fcpe_hz": f, "pesto_hz": p})
    else:
        # one says voiced, other says unvoiced
        merged.append({"hz": f if voiced(f) else p, "voiced": True, "conf": 0.6})
```

## Output snippet

```json
"vocals": {
  "notes": [...],
  "f0": [
    {"t": 8.21, "hz": 392.0, "voiced": true},
    {"t": 8.22, "hz": 392.3, "voiced": true},
    {"t": 8.23, "hz": 393.1, "voiced": true},
    {"t": 8.24, "hz": 394.0, "voiced": true},
    ...
  ]
}
```

For storage compactness, the f0 array can be downsampled to 50 Hz (every 20 ms) without losing much pedagogical information — vibrato rates are typically 4-7 Hz, well below Nyquist for 50 Hz sampling.

## Sources

- FCPE paper: arXiv:2509.15140 — <https://arxiv.org/abs/2509.15140>
- FCPE repo: <https://github.com/CNChTu/FCPE>
- torchfcpe PyPI: <https://pypi.org/project/torchfcpe/>
- PESTO paper (ISMIR 2023): <https://hal.science/hal-04260042v1/document>
- PESTO repo: <https://github.com/SonyCSLParis/pesto>
- pesto-pitch PyPI: <https://pypi.org/project/pesto-pitch/>
- CREPE (older baseline): <https://github.com/marl/crepe>
- torchcrepe (PyTorch port): <https://github.com/maxrmorrison/torchcrepe>
- RMVPE: <https://pypi.org/project/rmvpe-onnx/>
