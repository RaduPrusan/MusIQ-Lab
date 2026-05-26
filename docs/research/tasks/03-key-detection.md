# Key detection

Determines the song's tonal centre (e.g. "G:minor", "D:major"). Required for downstream Roman numeral analysis, scale-degree tagging, and modal-interchange detection in Stage 8.

## ✅ Recommended primary: `skey` (Deezer S-KEY)

Self-supervised key estimator from Deezer Research, ICASSP 2024. Matches the performance of the best supervised models without requiring a labelled training corpus.

### Install

```bash
pip install git+https://github.com/deezer/skey.git
```

Not yet on PyPI as of writing — the repo says PyPI release is planned. The `git+` install works fine.

### Usage — Python

```python
from skey.inference import predict_key

key, confidence = predict_key("song.mp3", device="cuda")
print(key, confidence)
# e.g. "G:minor", 0.87
```

(Exact API may vary slightly with future versions — check the repo README. The above is the expected shape.)

### Output format

A string in the format `<root>:<mode>` where:
- `root` ∈ `{C, C#, Db, D, D#, Eb, E, F, F#, Gb, G, G#, Ab, A, A#, Bb, B}`
- `mode` ∈ `{major, minor}`

Plus a confidence in `[0, 1]`.

### Why S-KEY wins

- **Self-supervised**: trained without labelled data, sidesteps the small-corpus problem of supervised key detection
- **ChromaNet backbone**: operates end-to-end on raw audio (not on hand-crafted chroma features like older methods)
- **ICASSP 2024**: actively published modern model
- Both Codex and Gemini independently recommended this — convergence signal

### Caveats

- Major / minor only. Doesn't detect modes (Dorian, Phrygian, Mixolydian, etc.). For modal songs the output will be the closest major/minor relative; use the chord/melody analysis to detect modal character downstream
- No local-key-modulation detection. Reports a single global key. If a song modulates (key change), only the dominant key is reported
- Not yet on PyPI — install via git+ which is one extra step
- GPU strongly recommended (CPU inference works but is slow)

## ↳ Fallback: librosa Krumhansl-Schmuckler

The classic algorithm. 1990 vintage, but still works as a fallback when `skey` install fails.

### Install

Already part of the dependency tree (librosa).

### Usage — Python

```python
import librosa
import numpy as np

# Krumhansl-Schmuckler key profiles
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def detect_key(audio_path):
    y, sr = librosa.load(audio_path)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    
    correlations = []
    for i in range(12):
        major_corr = np.corrcoef(np.roll(chroma, -i), KS_MAJOR)[0, 1]
        minor_corr = np.corrcoef(np.roll(chroma, -i), KS_MINOR)[0, 1]
        correlations.append((NOTES[i] + ":major", major_corr))
        correlations.append((NOTES[i] + ":minor", minor_corr))
    
    return max(correlations, key=lambda x: x[1])
```

### Why fallback only

- 1990-vintage profile correlation. Outclassed by modern self-supervised models on benchmark datasets
- Sensitive to the audio's tonal centre being clearly stated (struggles with songs that take a while to establish key)
- ~70-80% accuracy on benchmark sets, vs ~85-90% for skey-class models

### When to use

- `skey` install fails on your machine
- Quick sanity-check that a song's key is at all detectable
- Educational use: simple enough to read the algorithm in 20 lines and understand it

## ↳ Alternative: Essentia KeyExtractor

If you happen to have Essentia installed (we don't, by default — see [`recommended-stack.md`](../recommended-stack.md#what-i-considered-but-rejected) for why):

```python
import essentia.standard as es
loader = es.MonoLoader(filename="song.mp3")
audio = loader()
key, scale, strength = es.KeyExtractor()(audio)
```

Mature, but adds a heavy dep with AGPL licence and Linux-WSL install pain. Not in the default stack.

## 🧪 Future: ChromaNet local-key tracker

Some research lines (e.g. ChromaNet variants) detect *time-varying* local keys rather than a single global key. Useful for jazz / songs with strong modulations. None of these are well-packaged for general use as of 2026; revisit when one matures.

## Cross-validation hooks

Key detection feeds:

- **Stage 5 (chords) → Stage 8**: every detected chord gets a Roman numeral relative to the key (e.g. `Gm` in key `G:minor` is `i`; `Eb` is `♭VI`)
- **Stage 6 (notes) → Stage 8**: every transcribed note gets a scale-degree tag (e.g. `G4` in key `G:minor` is `1`; `C#4` is `♯4`)
- **Stage 8 reconciliation**: if `skey` confidence < 0.5, fall back to librosa K-S; if both disagree, log the disagreement and use the higher-confidence answer
- **Modal-interchange detection**: chords whose Roman numeral isn't diatonic to the key are flagged as `modal_interchange` (e.g. `♭VI` in major); helpful for educational tagging

## Sources

- S-KEY repo: <https://github.com/deezer/skey>
- S-KEY paper (ICASSP 2024): linked from the repo README
- Krumhansl-Schmuckler profiles: Krumhansl, *Cognitive Foundations of Musical Pitch*, 1990
- librosa: <https://librosa.org>
