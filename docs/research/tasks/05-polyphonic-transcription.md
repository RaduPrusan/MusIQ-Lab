# Polyphonic note transcription (per stem)

For each harmonic stem (vocals, bass, guitar, piano, other), produce a list of MIDI note events: `(start, end, pitch, velocity, pitch_bend)`. Drums are handled separately (onset detection, no pitch).

The transcription happens **per isolated stem** rather than on the full mix — running Basic Pitch on a clean bass stem produces dramatically better results than on the original mix.

## ✅ Recommended: `basic-pitch` (Spotify), per stem

Mature, packaged, instrument-agnostic neural transcriber from Spotify. Includes pitch-bend detection per note (the closest open-source equivalent to Melodyne's pitch curves).

### Install

```bash
pip install basic-pitch[tf]
# [tf] explicitly installs the TensorFlow backend on Linux (default would be tflite)
```

The `[tf]` extra is recommended on Linux for reproducibility — the TensorFlow Lite backend (default) sometimes produces marginally different results than full TensorFlow.

### Usage — CLI

```bash
basic-pitch ./output/ song_vocals.wav song_bass.wav song_guitar.wav
```

Generates one MIDI file per input audio file, e.g. `song_vocals_basic_pitch.mid`.

### Usage — Python (recommended for the pipeline)

```python
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

model_output, midi_data, note_events = predict(
    "song_vocals.wav",
    model_or_model_path=ICASSP_2022_MODEL_PATH,
    onset_threshold=0.5,
    frame_threshold=0.3,
    minimum_note_length=58,        # ms; tune per stem (longer for bass, shorter for melody)
    minimum_frequency=27.5,        # A0
    maximum_frequency=4186.0,      # C8
    multiple_pitch_bends=True,     # capture per-note pitch bends
    melodia_trick=True,
)
# note_events: list of (start_s, end_s, midi_pitch_int, velocity, pitch_bend_curve)
# midi_data:   pretty_midi.PrettyMIDI object — write with .write("song.mid")
```

### Per-stem parameter tuning

Different stems benefit from different thresholds. Recommended defaults:

| Stem | `onset_threshold` | `minimum_note_length` (ms) | `minimum_frequency` | Notes |
|---|---|---|---|---|
| `vocals.wav` | 0.5 | 58 | 80 (E2) | Default settings work well |
| `bass.wav` | 0.4 | 100 | 27.5 (A0) | Lower onset threshold; longer min length (bass notes are sustained) |
| `guitar.wav` | 0.5 | 58 | 80 (E2) | Default; tune per song style |
| `piano.wav` | 0.5 | 58 | 27.5 (A0) | Default; piano can play very low |
| `other.wav` | 0.6 | 100 | 80 | Higher threshold to suppress percussive bleed |

For drums, skip Basic Pitch entirely — use librosa onset detection instead:

```python
import librosa
y, sr = librosa.load("drums.wav")
onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time")
```

### Output format

`note_events` is a list of tuples `(start, end, pitch_midi, velocity, pitch_bend)` where:
- `start`, `end`: seconds
- `pitch_midi`: int 0..127, MIDI pitch number
- `velocity`: float 0..1
- `pitch_bend`: list of (time_offset, semitones) pairs — captures vibrato, slides, bends

In our `summary.json`, this becomes:

```json
{"t": 8.21, "dur": 0.43, "midi": 67, "name": "G4", "vel": 0.72,
 "in_chord": "Gm", "role": "chord_tone", "scale_deg": 1}
```

(The `in_chord`, `role`, `scale_deg` fields come from Stage 8 cross-validation.)

### Why basic-pitch wins as primary

- **Mature, packaged, fast** — pip install works, runs in seconds per stem on GPU
- **Pitch-bend detection per note** — the unique pedagogical signal (vibrato, bends, slides)
- **Instrument-agnostic** — same model works on vocals, bass, guitar, piano
- **The per-stem strategy** captures most of what multi-instrument models like YourMT3+ promise without the install pain. Basic Pitch on isolated bass stem ≈ YourMT3+ on full mix for bass, with much less setup

### Caveats

- **Drums are weak** — Basic Pitch attempts to assign pitches to drums, producing nonsense. Always skip drums and use onset detection instead
- **Polyphony density limit** — very dense polyphonic textures (orchestral, complex jazz piano) lose individual notes. Usually fine for popular music
- **No instrument labels** — Basic Pitch transcribes notes but doesn't say "this is a bass note" or "this is a piano note". We get instrument labels for free by transcribing per stem
- TensorFlow has a model load cost (~3 seconds first time) — pipeline keeps the model in memory across stems

## 🧪 Experimental: `MR-MT3` (Memory Retaining MT3)

ICASSP 2024 — addresses the "instrument leakage" problem where MT3 assigns notes to the wrong instrument track. Uses memory-retention attention across long contexts. Higher-quality multi-instrument transcription than Basic Pitch.

### Install

```bash
git clone https://github.com/gudgud96/MR-MT3.git
cd MR-MT3
# Recipe expects conda env Python 3.10
conda create -n mrmt3 python=3.10
conda activate mrmt3
pip install -r requirements.txt
```

Heavy dependencies (transformers, PyTorch Lightning, TensorFlow, librosa). Doesn't share venv cleanly with the main pipeline.

### When to use

- You're doing serious multi-instrument transcription work (MIDI for arrangement, not just analysis)
- You don't mind a separate conda env for this stage
- You have time budget for ~10× longer per-song inference

### Caveats

- Research code; expect breakage on dep updates
- No clean Python API; designed to be invoked as a script with the repo's recipe
- Conda env Python 3.10 conflicts with our project's Python 3.11 venv

## 🧪 Experimental: `YourMT3+` (mimbres)

MLSP 2024 — Mixture of Experts multi-instrument transcription. Higher SOTA than MR-MT3 on most benchmarks but even more research-flavoured.

### Install

```bash
git clone https://github.com/mimbres/YourMT3.git
cd YourMT3
# Original codebase uses JAX/T5X — significant compile pain
# Some PyTorch ports exist (rlax59us/MT3-pytorch, kunato/mt3-pytorch)
```

### When to use

- You want absolute SOTA multi-instrument transcription and don't mind days of setup
- The PyTorch ports become more polished (currently they're not)

### Caveats

- JAX/T5X ecosystem on WSL2 is rough
- Code is research-quality; expect to read papers to use it
- Vocal transcription quality strong but you'll need post-processing for cleaning up

## 🧪 Experimental: `SOME` (Singing-to-MIDI)

Specifically targets vocal-to-MIDI conversion. From the OpenVPI project (RVC adjacent).

```bash
pip install git+https://github.com/openvpi/SOME.git
```

### When to use

- The vocals stem from Stage 1 is clean
- You want vocal MIDI specifically (not just notes from Basic Pitch)
- You can tolerate beta-quality output

### Caveats

- Beta software; package authors warn the pretrained model is language-biased (trained primarily on Mandarin pop)
- Requires isolated vocal stem (run after Stage 1)
- Less reliable than Basic Pitch for English vocals

## ↳ Alternative: `crepe` for vocal melody only

If you only want a vocal melody track and don't need polyphony, run CREPE on the vocals stem.

```bash
pip install crepe
crepe vocals.wav --output-csv
```

Produces a single-pitch-per-frame CSV. Convert to MIDI by quantising. Use only if Basic Pitch's vocals output is too noisy. Generally PESTO/FCPE (Stage 7) is better for vocal f0; we don't recommend CREPE for this pipeline.

## Cross-validation hooks

Polyphonic transcription feeds:

- **Stage 8 → bass-stem chord cross-check**: the lowest note(s) of the bass stem at each chord boundary should match the chord's `bass` (or `root` if no slash). Disagreement → flag in chord's `agreement` field
- **Stage 8 → chord-tone tagging**: every transcribed note gets a `role` tag (chord_tone / passing_tone / neighbor_tone / non_chord_tone) computed against the active chord
- **Stage 8 → scale-degree tagging**: every transcribed note gets a `scale_deg` field relative to the detected key
- **Stage 8 → vocal melody → vocals_f0 cross-check**: the vocal MIDI track should align with the f0 contour from Stage 7. Large deviation flags a transcription error or expressive ornament

## Sources

- Basic Pitch repo: <https://github.com/spotify/basic-pitch>
- Basic Pitch paper: Bittner et al., ICASSP 2022
- MR-MT3 repo: <https://github.com/gudgud96/MR-MT3>
- MR-MT3 paper: arXiv:2403.10024
- YourMT3+ repo: <https://github.com/mimbres/YourMT3>
- YourMT3+ paper: arXiv:2407.04822
- SOME repo: <https://github.com/openvpi/SOME>
