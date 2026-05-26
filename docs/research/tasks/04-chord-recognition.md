# Chord recognition

Detects the chord progression with timestamps. The output drives Roman numeral analysis, function tagging, and chord-tone classification of the melody — the core of the educational analysis.

## ✅ Recommended: `lv-chordia`

Pip-installable rich-vocabulary chord recogniser. Supports 170 chord classes by default and up to 600+ in extended vocabulary mode — including 7ths, sus2/sus4, dim, aug, slash chords, and bass inversions. This is the **vocabulary breadth** required for educational use; smaller-vocab tools like autochord (25 classes) collapse `Cmaj7` and `C` to the same label.

### Install

```bash
pip install lv-chordia
```

### Usage — CLI

```bash
python -m lv_chordia song.mp3 song.chords --chord_dict submission
```

`--chord_dict` accepts:
- `submission` (default, recommended) — 170-class vocabulary used in the ISMIR 2019 submission. Strongest pretrained model, balanced accuracy/breadth.
- `large` — 600+ class extended vocabulary. More detail, slightly lower per-class accuracy.

### Usage — Python

```python
from lv_chordia import predict

chords = predict("song.mp3", chord_dict="submission")
# chords is a list of (start_seconds, end_seconds, chord_label) tuples
for start, end, label in chords[:10]:
    print(f"{start:6.2f}s - {end:6.2f}s : {label}")
```

(Exact API may vary; check the package README for the latest entry-point shape.)

### Output format

A list of chord events as `(start_s, end_s, label)`. Labels follow the **Harte chord grammar** (the JAMS chord namespace standard):

```
G:min          # G minor triad
G:min7         # G minor 7th
G:min7/Bb      # G minor 7th, Bb in bass (slash chord)
N              # No chord (silence, drum-only, etc.)
X              # Unknown / unclassifiable
G:sus4         # G suspended 4th
G:dim          # G diminished
G:aug          # G augmented
G:maj/3        # G major, third in bass = G/B
```

Decompose a label like `G:min7/Bb` with:
```python
import re
m = re.match(r"^([A-G][#b]?)(?::(\w+))?(?:/([A-G][#b]?\d?))?$", label)
root, type_, bass = m.groups()
```

`pip install jams` includes a tested parser at `jams.namespaces.chord_harte`.

### Why lv-chordia wins

- **Rich vocabulary**: 170+ chord classes including 7ths and slash chords. autochord has 25; chord-extractor (Chordino) has ~50 with no slash chords. lv-chordia is the only well-packaged Python tool with the vocabulary needed for music-theory-grade analysis.
- **MIREX 2025 results show the underlying ISMIR 2019 architecture is still competitive** — newer transformer entries from 2024-2025 haven't published packaged code yet
- **CNN ensemble + HMM smoothing**: 5 CNN models with diverse training, chord-structure decomposition (root/bass/type independently predicted then combined), HMM smooths the temporal sequence

### Caveats

- The underlying paper is ISMIR 2019 — no transformer architecture. Newer 2024-2025 ACE work (ChordFormer, ACE Conformer with consonance training) outperforms it on benchmarks but isn't packaged. Revisit in 12 months
- **Bass inversion accuracy is the weak spot** — slash chord predictions (`G/B`, `C/E`) are less accurate than root-position predictions. Stage 8 cross-checks chord roots against the bass-stem MIDI to correct this when possible
- Older deps (mir-eval, pumpp) — install with `--upgrade` if you hit version conflicts

## ↳ Alternative: `chord-extractor` (Chordino wrapper)

Wraps the venerable Chordino Vamp plugin (the academic reference implementation of automatic chord estimation).

### Install

```bash
pip install chord-extractor
sudo apt install vamp-plugin-sdk vamp-examples sonic-annotator
# Plus the NNLS-Chroma .so plugin in ~/vamp/  (chord-extractor handles this in modern versions)
```

### Usage

```python
from chord_extractor.extractors import Chordino
chordino = Chordino()
chords = chordino.extract("song.mp3")
# chords is a list of ChordChange(timestamp, chord) objects
```

### When to prefer over lv-chordia

- You want academic-baseline reproducibility
- You need only major/minor + a few sevenths (smaller vocabulary acceptable)
- lv-chordia install fails for some reason

### Caveats

- ~25-50 chord classes only — no slash chords, limited 7ths
- Chordino is 2009-vintage. Strong baseline but not modern SOTA

## ↳ Alternative: `autochord`

Small, pip-only, 25-class chord recogniser using Bi-LSTM-CRF.

```bash
pip install autochord
```

Use only if both lv-chordia and chord-extractor fail. Vocabulary is too sparse for educational use (collapses all 7ths and slash chords to triads).

## 🧪 Experimental: BTC (Bi-directional Transformer for Chord Recognition)

ISMIR 2019 transformer-based chord recogniser. Higher-quality predictions than lv-chordia on small-vocabulary tasks but not pip-packaged.

```bash
git clone https://github.com/jayg996/BTC-ISMIR19.git
cd BTC-ISMIR19
pip install -r requirements.txt
python test.py  # see repo for inference script
```

Use as a third voice in the chord ensemble if you want maximum accuracy and don't mind the manual setup. Pipeline doesn't include it by default.

## 🧪 Experimental: ChordCoT (LLM Chain-of-Thought for ACR)

Sept 2025 paper proposing using an LLM to refine chord recognizer outputs by reasoning over harmonic context. Exactly what our Stage 8 does — see [`cross-validation.md`](../cross-validation.md) for our implementation. The paper itself doesn't ship code; we implement the pattern using Claude.

Reference: arXiv:2509.18700 — <https://arxiv.org/html/2509.18700v1>

## Cross-validation hooks

Chord recognition feeds:

- **Stage 8 → Stage 8**: chord boundaries are snapped to nearest downbeat (from `allin1`)
- **Stage 8 cross-check vs bass-stem MIDI**: the chord's `bass` (or `root` if no slash) should match the bass note at that time. Disagreement → flag as `agreement: split` in summary.json
- **Stage 8 → Roman numerals**: each chord gets `roman` and `function` annotations relative to the detected key
- **Stage 8 → modal interchange detection**: chords whose Roman numeral isn't diatonic to the key are tagged `function: "modal_interchange"`
- **Stage 6 (notes) cross-check**: each transcribed note gets tagged as `chord_tone` / `passing_tone` / `non_chord_tone` relative to the active chord at its onset

## Output snippet (per chord, in summary.json)

```json
{
  "start": 1.93, "end": 3.87,
  "label": "Eb",
  "root": "Eb", "bass": "Eb", "type": "maj",
  "roman": "♭VI",
  "function": "modal_interchange",
  "confidence": 0.71,
  "agreement": "consensus",
  "notes": "Bass-stem MIDI confirms Eb root."
}
```

## Sources

- lv-chordia PyPI: <https://pypi.org/project/lv-chordia/>
- Underlying paper: Park et al., ISMIR 2019 — <https://archives.ismir.net/ismir2019/paper/000078.pdf>
- Reference implementation: <https://github.com/music-x-lab/ISMIR2019-Large-Vocabulary-Chord-Recognition>
- Harte chord grammar: ISMIR 2005 — <https://www.semanticscholar.org/paper/Symbolic-Representation-of-Musical-Chords-Harte-Sandler/>
- MIREX 2025 ACE results: <https://music-ir.org/mirex/wiki/2025:Audio_Chord_Estimation_Results>
- ChordCoT (LLM CoT for ACR): <https://arxiv.org/html/2509.18700v1>
- BTC repo: <https://github.com/jayg996/BTC-ISMIR19>
