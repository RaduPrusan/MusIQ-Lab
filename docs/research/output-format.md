# Output format

Each analysis run emits **two** files next to the source MP3:

- `<song>.jams` — full multi-track annotation, JAMS-spec-compliant, archival format
- `<song>.summary.json` — compact educational digest, Claude-readable, derived from JAMS

## Why two files

| | JAMS | summary.json |
|---|---|---|
| **Purpose** | Archive every tool's raw output, schema-validated | Compact opinionated digest for educational reading |
| **Audience** | Future automated tools, audits, research reproducibility | You + Claude in conversation |
| **Size** | 50–200 KB/song | 10–30 KB/song |
| **Includes** | Multiple annotations per task (raw + corrected, multiple models) | One canonical answer per question, plus derived analysis |
| **Verbose** | Yes | No |
| **Schema-validated** | Yes (jams library) | No (informal contract documented here) |

## JAMS file structure

[JAMS](https://github.com/marl/jams) is the JSON Annotated Music Specification — the de-facto standard MIR annotation format. We use the standard namespaces wherever possible.

A JAMS file we produce contains the following annotation tracks:

| Namespace | Source tool | What it stores |
|---|---|---|
| `beat` | `allin1` | Primary beat times |
| `beat` | `beat_this` | Cross-check beat times (separate annotation, same namespace) |
| `beat_position` | `allin1` | Beat position within bar (1, 2, 3, 4...) |
| `segment_open` | `allin1` | Section labels (intro/verse/chorus/...) |
| `chord` | `lv_chordia` | Raw chord recognizer output (Harte grammar) |
| `chord` | `claude_orchestrator` | LLM-corrected chord track (snapped to downbeats, with Roman numerals in the value field) |
| `key_mode` | `skey` | Key estimate (e.g. "G:minor") |
| `pitch_contour` | `torchfcpe` | Vocal f0 contour |
| `pitch_contour` | `pesto` | Cross-check f0 contour |
| `note_midi` | `basic_pitch` (per stem) | Polyphonic note events; one annotation per stem |
| `tempo` | `allin1` | Single tempo value |

Each annotation includes JAMS' standard `annotation_metadata`:
```json
{
  "annotator": {"name": "claude_orchestrator", "version": "0.1.0"},
  "annotation_tools": "[script: lib/reconcile.py]",
  "data_source": "machine",
  "validation": "...",
  "corpus": "user_library"
}
```

This makes it possible to filter/query annotations by source tool later (e.g. `jams.search(namespace="chord", annotator="lv_chordia")`).

## summary.json schema

The compact digest. **Designed to be read by Claude.** Keys are short, structure is flat, derived analysis is precomputed.

```json
{
  "track": {
    "file": "Stromae - Alors On Danse.mp3",
    "windows_path": "C:\\Users\\<you>\\Videos\\Any Video Converter Ultimate\\Youtube\\Stromae - Alors On Danse.mp3",
    "wsl_path": "/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/Stromae - Alors On Danse.mp3",
    "duration_sec": 213.4,
    "tempo_bpm": 124.0,
    "key": "G:minor",
    "key_confidence": 0.87,
    "time_signature": "4/4"
  },

  "sections": [
    {"start": 0.0,    "end": 15.5,  "label": "intro"},
    {"start": 15.5,   "end": 47.1,  "label": "verse"},
    {"start": 47.1,   "end": 78.7,  "label": "chorus"},
    {"start": 78.7,   "end": 110.3, "label": "verse"},
    {"start": 110.3,  "end": 173.5, "label": "chorus"},
    {"start": 173.5,  "end": 213.4, "label": "outro"}
  ],

  "downbeats": [0.48, 2.42, 4.36, 6.30, 8.24, 10.18, ...],

  "chords": [
    {
      "start": 0.00, "end": 1.93,
      "label": "Gm",
      "root": "G", "bass": "G", "type": "min",
      "roman": "i", "function": "tonic",
      "confidence": 0.94,
      "agreement": "consensus"
    },
    {
      "start": 1.93, "end": 3.87,
      "label": "Eb",
      "root": "Eb", "bass": "Eb", "type": "maj",
      "roman": "♭VI", "function": "modal_interchange",
      "confidence": 0.71,
      "agreement": "split",
      "notes": "Lv-chordia preferred Eb; bass-stem MIDI agrees."
    }
  ],

  "stems": {
    "vocals": {
      "notes": [
        {"t": 8.21, "dur": 0.43, "midi": 67, "name": "G4", "vel": 0.72,
         "in_chord": "Gm", "role": "chord_tone", "scale_deg": 1},
        {"t": 8.64, "dur": 0.18, "midi": 65, "name": "F4", "vel": 0.61,
         "in_chord": "Gm", "role": "passing_tone", "scale_deg": "♭7"}
      ],
      "f0": [
        {"t": 0.00, "hz": null, "voiced": false},
        {"t": 8.21, "hz": 392.0, "voiced": true},
        {"t": 8.30, "hz": 393.5, "voiced": true}
      ]
    },
    "bass":   {"notes": [...]},
    "drums":  {"onsets": [...]},
    "other":  {"notes": [...]}
  },

  "analysis": {
    "scale": "G natural minor",
    "modal_interchange_count": 3,
    "predominant_chord_loop": ["Gm", "Eb", "Bb", "F"],
    "loop_roman": ["i", "♭VI", "♭III", "♭VII"],
    "loop_appearances": [{"start": 47.1, "end": 78.7}, {"start": 110.3, "end": 173.5}],
    "vocal_range": {"low": "G3", "high": "D5"}
  },

  "provenance": {
    "pipeline_version": "0.1.0",
    "models": {
      "stems": "audio_separator[bs_roformer_ep_317]",
      "beats_sections": "allin1@v1.x",
      "beats_xcheck": "beat_this[final0]",
      "key": "skey[skey.pt]",
      "chords": "lv_chordia[submission]",
      "transcription": "basic_pitch[ICASSP_2022_MODEL]",
      "vocal_f0": "torchfcpe[bundled]",
      "vocal_f0_xcheck": "pesto[bundled]"
    },
    "warnings": []
  }
}
```

### Field semantics

#### `track`

Self-describing. `windows_path` and `wsl_path` both included so you can reference the song from either OS view in conversation. `time_signature` is `4/4` unless `allin1` says otherwise (in practice, always `4/4` for popular music).

#### `sections`

From `allin1`. Labels are functional (intro/verse/chorus/bridge/outro/break/inst/solo). Probabilistic — treat as best-guess, not ground truth.

#### `downbeats`

From `allin1` (cross-checked against `beat_this`). Beats themselves aren't included in summary.json (too verbose); use the JAMS file if you want them. Downbeats are usually enough to discuss song structure.

#### `chords`

The single canonical chord track after Stage 8 reconciliation. Each chord has:

- `start`, `end` — seconds (snapped to nearest downbeat from `allin1`)
- `label` — human-readable (e.g. `Cmaj7`, `F#m7b5/A`)
- `root`, `bass`, `type` — decomposition (Harte-grammar-compatible)
- `roman` — Roman numeral relative to the detected key (e.g. `vi`, `♭VII`, `V/V`)
- `function` — diatonic function (`tonic`, `predominant`, `dominant`, `modal_interchange`, `secondary`)
- `confidence` — 0..1
- `agreement` — `consensus` (lv-chordia + bass-stem agree) or `split` (disagreement; see `notes`)
- `notes` — optional human-readable explanation when `agreement = "split"`

#### `stems`

One block per stem. `notes` is an array of MIDI events. For drums, `onsets` is used instead (no pitch).

For each note in a harmonic stem:

- `t`, `dur` — start time and duration (seconds)
- `midi`, `name` — MIDI number and pitch name (e.g. `67`, `G4`)
- `vel` — velocity 0..1
- `in_chord` — the chord active at `t` (from `chords`)
- `role` — `chord_tone` / `passing_tone` / `neighbor_tone` / `non_chord_tone` (computed by Stage 8 against `in_chord`)
- `scale_deg` — scale degree relative to the detected key (e.g. `1`, `♭3`, `5`, `♯4`)

The vocals stem also has an `f0` array of (t, hz, voiced) tuples — the merged FCPE+PESTO contour. Sampled at 100 Hz typically.

#### `analysis`

Derived analysis Claude can use to teach. Includes:

- `scale` — detected scale name (mode-aware: not just "major" but "G natural minor", "D mixolydian" etc.)
- `modal_interchange_count` — how many chords had `function = "modal_interchange"`
- `predominant_chord_loop` — the most-repeated chord progression in the song (with `loop_appearances` listing where it occurs)
- `vocal_range` — extremes of the vocal melody

This section is **the most pedagogically valuable** part of the summary — it's the precomputed teaching points.

#### `provenance`

Tools and model versions used. `warnings` lists any stage-degradation warnings (e.g. `"Stage 4 fell back from skey to librosa K-S"`).

## How Claude uses summary.json

When you mention a song in conversation, Claude can read its `summary.json` directly to answer questions like:

- "What scale does the chorus use?"
- "Are there any borrowed chords?"
- "Show me the chord-tones vs passing-tones in the verse melody"
- "What's the vocal range?"
- "Compare this song's structure with [another song]"

The `summary.json` schema is designed for this. Keys are short to keep token cost low; derived analysis is precomputed so Claude doesn't have to re-derive Roman numerals from scratch each time.

## Reading the JAMS file (Python)

```python
import jams
j = jams.load("Song.jams")

# All chord annotations
chord_anns = j.search(namespace="chord")
for ann in chord_anns:
    print(ann.annotation_metadata.annotator)  # "lv_chordia" or "claude_orchestrator"
    for obs in ann.data:
        print(f"{obs.time:.2f}-{obs.time+obs.duration:.2f}: {obs.value}")

# Beats from allin1 specifically
beats = j.search(namespace="beat", annotator="allin1")[0]
beat_times = [obs.time for obs in beats.data]
```

## Reading summary.json (any tool)

It's plain JSON. Load and use.

```python
import json
with open("Song.summary.json") as f:
    s = json.load(f)

print(f"{s['track']['file']} — {s['track']['key']}, {s['track']['tempo_bpm']} BPM")
for chord in s['chords'][:8]:
    print(f"  {chord['start']:6.2f}s  {chord['label']:8s} ({chord['roman']})")
```
