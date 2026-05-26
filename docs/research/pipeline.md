# Pipeline Architecture

## Goal

Take an MP3 and emit two artefacts:

1. **A JAMS file** (`<song>.jams`) — full multi-track annotation, schema-validated, archival format used in MIR research.
2. **A summary.json** (`<song>.summary.json`) — compact, opinionated digest optimised for Claude-CLI reading and educational use.

Both files live next to the MP3 so the data, audio, and analysis are colocated.

## Why two output files?

| File | Purpose | Used by |
|---|---|---|
| `<song>.jams` | Archival, reproducible, multi-tool annotation track storage. Supports conflicting annotations from different tools (e.g. raw model output vs LLM-corrected). Schema-validated. ~50–200 KB/song. | The pipeline itself; tools that consume MIR research data; future audits |
| `<song>.summary.json` | Compact educational digest. Roman numerals, chord-tone tags, scale-degree annotations, only-the-essentials. Designed to fit ~30 songs in one Claude conversation. ~10–30 KB/song. | You + Claude when discussing the song |

The `summary.json` is **derived from** the JAMS file by the cross-validation stage. The JAMS file is the source of truth.

## Pipeline stages

```
MP3
 │
 ├─ Stage 1: Stem separation                     (audio-separator)
 │   └─ vocals, drums, bass, [guitar, piano,] other        → cache/<song>/stems/*.wav
 │
 ├─ Stage 2: Joint metrical + structural analysis  (allin1)
 │   ├─ beats[]            (time, beat-position-in-bar)
 │   ├─ downbeats[]        (time)
 │   ├─ tempo (BPM)
 │   └─ sections[]         (start, end, label ∈ {intro, verse, chorus, bridge, outro, …})
 │
 ├─ Stage 3: Beat cross-verification              (beat_this)
 │   └─ beats_alt[] / downbeats_alt[]                       → JAMS records both, marks disagreements
 │
 ├─ Stage 4: Key detection                        (skey)
 │   └─ key (e.g. "G:minor"), confidence
 │
 ├─ Stage 5: Chord recognition                    (lv-chordia)
 │   └─ chords[]    (start, end, label, root, bass, type, confidence)
 │       boundaries are then snapped to Stage-2 downbeats
 │
 ├─ Stage 6: Per-stem note transcription          (basic-pitch on each stem)
 │   └─ MIDI events per stem (start, end, pitch_midi, velocity, pitch_bend)
 │
 ├─ Stage 7: Vocal melody f0                      (torchfcpe + pesto cross-check)
 │   └─ vocals_f0[]   (time, hz, voiced_prob)
 │
 └─ Stage 8: Cross-validation + summarisation     (Python + Claude)
     ├─ Snap chord boundaries to nearest downbeat (Stage 2)
     ├─ Validate chord roots against bass-stem MIDI (Stage 6)
     ├─ Compute Roman numeral analysis for each chord (Stage 4 + 5)
     ├─ Tag melody notes as chord-tone / passing-tone / non-chord-tone (Stage 5 + 6)
     ├─ Compute scale-degree for each melody note (Stage 4 + 6/7)
     └─ Emit summary.json
```

Each stage's output is recorded into the JAMS file as an annotation track with its source-tool tag. The `summary.json` is only built at Stage 8 by reading from JAMS.

## Design principles

### 1. Run independent models, cross-validate later

We never let one tool's mistake propagate silently. Where two tools could compute the same field (e.g. beats from `allin1` AND `beat_this`), we run both and reconcile in Stage 8. Disagreements are surfaced explicitly — they are often **musically interesting** moments (modal interchange, sus chords, ambiguous downbeat placement).

### 2. Modern over classic

Favoured 2024-2026 SOTA over 2018-era classics. Specifically rejected as primary: madmom DBN/DeepChroma (replaced by `beat-this` and `lv-chordia`), librosa K-S key detection (replaced by `skey`), MSAF sections (replaced by `allin1`). See [`recommended-stack.md`](recommended-stack.md) for rejection rationale.

### 3. JAMS for archival, summary.json for reading

Separation of concerns. JAMS is verbose, schema-strict, multi-track — perfect for "future me wants to recompute X with a new tool". `summary.json` is opinionated, compact, includes derived analysis (Roman numerals etc.) — perfect for "Claude, what does this song teach about modal interchange?"

### 4. LLM as orchestrator, not transcriber

Claude reasons over outputs from MIR tools, computes Roman numerals, tags non-chord-tones, surfaces disagreements. Claude does **not** invent missing notes or hallucinate chords. The MIR tools produce raw observations; the LLM produces **interpretation**.

### 5. Quality > speed

We're willing to wait several minutes per song. The RTX 3090 budget allows running multiple models per task and ensembling. There is no real-time constraint.

## Data flow / on-disk layout

```
<PROJECT_PATH>\
├── analyze.py                 # main entrypoint (CLI: analyze.py <mp3>)
├── lib/
│   ├── stems.py               # Stage 1
│   ├── allin1_stage.py        # Stage 2
│   ├── beats.py               # Stage 3
│   ├── key.py                 # Stage 4
│   ├── chords.py              # Stage 5
│   ├── transcription.py       # Stage 6
│   ├── vocal_f0.py            # Stage 7
│   ├── reconcile.py           # Stage 8
│   └── jams_io.py             # JAMS read/write helpers
├── cache/                     # ephemeral; can be deleted any time
│   └── <song-id>/
│       ├── stems/
│       │   ├── vocals.wav
│       │   ├── drums.wav
│       │   ├── bass.wav
│       │   └── other.wav
│       └── intermediate/
│           ├── allin1.json
│           ├── beat_this.txt
│           └── ...
└── docs/
    └── ...

C:\Users\<you>\Videos\Any Video Converter Ultimate\Youtube\
├── <song>.mp3              # input audio
├── <song>.jams             # output: full annotation
└── <song>.summary.json     # output: Claude-readable digest
```

The `cache/` directory holds intermediate stems and per-tool raw outputs. Deletable at any time; pipeline re-creates on next run. Lives on the WSL native filesystem (or `/mnt/f/`) for speed; the only files that **must** end up next to the MP3 are the two output artefacts.

## Hardware envelope

| Resource | Used | Notes |
|---|---|---|
| GPU VRAM | ~6–10 GB peak | Ensemble inference fits comfortably in 24 GB |
| Disk | ~50–80 MB per song (cache) + ~30 KB output | Cache cleared after pipeline if `--clean` flag given |
| Wall time | ~3–5 min per 4-min song | Most time in stem sep + chord rec + transcription |
| Network | One-time model downloads (~5 GB total) | Cached after first run |

### WSL2 + NVIDIA "Sysmem Fallback" caveat (operational addendum, May 2026)

The wall-time figure above assumes everything fits in physical VRAM. On the JINN setup
(Windows 11 host + WSL2 Ubuntu + RTX 3090) the failure mode below ~6 GB free VRAM
is **not** a CUDA OOM — it's a silent slowdown:

- NVIDIA driver 536.40+ (July 2023) added the "CUDA Sysmem Fallback Policy", which
  spills GPU allocations into Windows shared GPU memory (system RAM via WDDM) when
  VRAM is exhausted, instead of throwing `CUDA_ERROR_OUT_OF_MEMORY`.
- On native Linux this feature does **not** exist — `cudaMalloc` hard-OOMs (per
  NVIDIA: "not supported by the nvidia linux driver").
- On Windows you can disable it via NVCP → 3D Settings → "CUDA - Sysmem Fallback
  Policy" → Prefer No Sysmem Fallback.
- **Inside WSL2 the fallback is always on and the NVCP setting does not propagate**
  (`microsoft/WSL` issue #11050, still open as of May 2026). There is no in-WSL
  toggle.

Practical consequence for the analyze stack: a stage that should take 100 s on a
free GPU can take many minutes when forced into shared memory. GPU utilization will
pin at 100% and PCIe bus traffic will spike, but `nvidia-smi` will *not* show VRAM
exhaustion (it only reports physical VRAM). The Windows-side "Shared GPU memory"
counter (Task Manager → Performance → GPU) is the canonical observability surface;
inside WSL2 the only signal is wall-time inflation.

Mitigations:

- Close other GPU consumers (browser hardware accel, ComfyUI with a model loaded,
  the webui if it loads a model in-process) before invoking `python -m analyze`.
- `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` reduces the chance the
  PyTorch allocator's own fragmentation triggers spillover before physical VRAM is
  actually full.
- For empirical detection during a run, sample VRAM with
  `install-logs/_vram_watch.sh` *and* watch Windows Task Manager's "Shared GPU
  memory" — if the latter climbs above zero during a stage, you're paying the
  spillover tax.

## Failure modes & graceful degradation

| Stage failure | Effect | Pipeline behaviour |
|---|---|---|
| Stage 1 (stems) | catastrophic | abort with clear error |
| Stage 2 (allin1) | no beats/sections | emit warning, fall back to `beat-this` only, no sections |
| Stage 3 (beat-this) | no cross-check | continue, mark beats as unverified in JAMS |
| Stage 4 (key) | no key | continue, fall back to librosa K-S, mark `key.source = "fallback"` |
| Stage 5 (chords) | no chords | continue, summary.json says `chords: null` |
| Stage 6 (notes) | no notes for a stem | continue, that stem gets `notes: []` in summary |
| Stage 7 (f0) | no f0 | continue without melody contour |
| Stage 8 (recon.) | no derived analysis | emit summary with raw fields only, no Roman numerals |

The pipeline is best-effort. Catastrophic Stage 1 failure aborts; everything else degrades gracefully.
