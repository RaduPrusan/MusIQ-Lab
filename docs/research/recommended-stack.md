# Recommended Stack

The final recommendation after independent research from three sources (Claude, OpenAI Codex with web search, Google Gemini with grounded search). All three were given the same neutral prompt without bias toward specific tools. Where they converged independently, I treat that as high-confidence signal.

## At a glance

| Stage | Package | Underlying model | Year | Source |
|---|---|---|---|---|
| **1** Stems | ✅ `audio-separator[gpu]` | BS-RoFormer / MelBand-RoFormer / Demucs htdemucs_6s | 2023–2024 | UVR ecosystem |
| **2** Joint metrical + structural | ✅ `allin1` | All-In-One transformer w/ neighborhood attention | WASPAA 2023 | mir-aidj/all-in-one |
| **3** Beat cross-check | ✅ `beat-this` | Beat This! transformer (no DBN) | ISMIR 2024 | CPJKU/beat_this |
| **4** Key | ✅ `skey` (`git+`) | S-KEY ChromaNet, self-supervised | ICASSP 2024 | deezer/skey |
| **5** Chords | ✅ `lv-chordia` | Large-Vocab Chord Decomposition (CNN + HMM) | ISMIR 2019 | music-x-lab |
| **6** Polyphonic transcription | ✅ `basic-pitch` (per stem) | Spotify Basic Pitch | 2022 | spotify/basic-pitch |
| **7** Vocal f0 | ✅ `torchfcpe` | FCPE Lynx-Net | 2024 | CNChTu/FCPE |
| **7b** Vocal f0 cross-check | ✅ `pesto-pitch` | PESTO self-supervised, transposition-equivariant | ISMIR 2023 | SonyCSLParis/pesto |
| **8** Output | ✅ `jams` | JSON Annotated Music Specification | ISMIR 2014, current | marl/jams |
| **9** Orchestration | ✅ Claude (this CLI) | LLM cross-validator | n/a | — |

## Rationale per choice

### Stems — `audio-separator`

**Why it wins**: actively maintained CLI/Python wrapper around the entire UVR (Ultimate Vocal Remover) model zoo. Lets us use BS-RoFormer (~12.9 dB vocal SDR), MelBand-RoFormer, and the Demucs `htdemucs_6s` 6-stem model from one tool. All three independent researchers (Claude / Codex / Gemini) converged on this package.

**What it replaces**: Spleeter (2019, ~5 dB SDR — significantly behind), running raw HTDemucs alone (loses BS-RoFormer's ~3 dB advantage on vocals).

### Beats / downbeats / tempo / sections — `allin1`

**Why it wins**: a single transformer that **jointly** predicts beats, downbeats, tempo, and section labels (intro/verse/chorus/bridge/outro). Joint prediction is higher-quality than running independent models because the tasks share latent structure (downbeats correlate with section boundaries, etc.). Internally separates the audio with Demucs first, so it's fed clean stems.

**What it replaces**: madmom's DBN-based beat tracker (2014 architecture), MSAF (boundary detection only, no functional labels), running 3 separate tools that don't share information.

### Beat cross-check — `beat-this`

**Why it's a useful second voice**: ISMIR 2024 paper titled literally "Beat Tracking Without DBN Postprocessing" — explicitly designed to obsolete madmom's DBN approach. Pure-neural beat/downbeat. Cross-checks `allin1`'s beats and surfaces disagreements (which often correspond to ambiguous metrical phenomena like syncopation or hemiola).

**Why not primary**: `allin1` does beats, downbeats, AND sections in one pass. Making `beat-this` primary would mean running it AND `allin1` for sections anyway. So `allin1` primary, `beat-this` as cross-validator.

### Key — `skey` (Deezer)

**Why it wins**: self-supervised ChromaNet from Deezer Research, ICASSP 2024. Matches SOTA supervised models without needing labelled data. Codex and Gemini independently converged on this; my original plan (librosa K-S) is a 1990 algorithm that's been outclassed by modern models.

**Caveat**: not yet on PyPI; install via `git+https://github.com/deezer/skey.git`. The repo says PyPI packaging is planned.

**Fallback**: librosa K-S correlation for if skey installation fails.

### Chords — `lv-chordia`

**Why it wins**: pip-installable, supports 170–600 chord classes including 7ths/sus/slash/bass — the rich vocabulary needed for **educational** use where harmonic detail matters. The underlying ISMIR 2019 paper (Large-Vocabulary Chord Transcription via Chord Structure Decomposition) remains competitive in the 2025 MIREX results despite predating transformers.

**What it replaces**: `autochord` (25 classes — far too sparse for educational analysis), `chord-extractor` wrapping Chordino (no slash chords), madmom DeepChroma (24 classes only).

**Augmentation**: Claude post-processes chord predictions in Stage 8, snapping boundaries to downbeats and computing Roman numerals using detected key. This is the "LLM-as-orchestrator" pattern — described in detail in [`cross-validation.md`](cross-validation.md).

### Polyphonic note transcription — `basic-pitch` (per stem)

**Why it wins**: mature, packaged, runs in seconds per stem on GPU, outputs MIDI with per-note pitch bends. Critically, by running it on **isolated stems** (from Stage 1) rather than the full mix, we get most of the multi-instrument benefit of YourMT3+ without the install pain. Spotify ships it as a polished Python package.

**What we considered**: YourMT3+ (2024 MoE multi-instrument model) and MR-MT3 (2024 ICASSP, instrument-leakage mitigation) are academically more advanced but their packaging is research-grade — JAX/T5X dependencies, no clean PyPI release, install pain on WSL2. Documented as 🧪 advanced options in [`tasks/05-polyphonic-transcription.md`](tasks/05-polyphonic-transcription.md).

### Vocal f0 — `torchfcpe` primary, `pesto-pitch` cross-check

**Why FCPE wins primary**: FCPE (Fast Context-based Pitch Estimation, 2024) uses a Lynx-Net depth-wise-separable conv backbone. Achieves ~96.79 % raw pitch accuracy with RTF 0.0062 on RTX 4090 (essentially free). Newer than CREPE (2018) and PESTO (2023). `torchfcpe` is on PyPI as a clean PyTorch wrapper.

**Why PESTO as cross-check**: ISMIR 2023 self-supervised, transposition-equivariant — different inductive biases than FCPE, so it catches different failure modes. Two voices reconciled gives higher confidence than either alone.

**What we rejected**: RMVPE (Codex's pick) — it's strong for voice-conversion (RVC) ecosystems but ties us to that pipeline's conventions; PESTO is academically cleaner. CREPE — superseded by both PESTO and FCPE; ~12 minutes of compute for what PESTO does in 13 seconds.

### Output — JAMS + summary.json

**Why JAMS wins**: standard MIR research format since 2014, JSON-native, schema-validated, supports multi-track annotations with per-track tool provenance. Both Codex and Gemini independently said "do not invent a custom JSON schema; use JAMS". My initial plan (custom JSON only) would have been worse.

**Why also summary.json**: JAMS is verbose. For Claude-CLI reading, we want a compact opinionated digest with derived analysis (Roman numerals, chord-tone tags, scale degrees). The summary.json is what we feed into conversation context; the JAMS is the archival source of truth.

See [`output-format.md`](output-format.md) for the schemas of both.

## What I considered but rejected

| Rejected | Why | Replacement |
|---|---|---|
| madmom DeepChroma chord | 2017 architecture; 24 chord classes; superseded | `lv-chordia` (170–600 classes) |
| madmom DBN beat tracker | 2014 architecture; explicitly replaced by Beat This! | `allin1` + `beat-this` |
| librosa K-S key | 1990 algorithm; outclassed by self-supervised models | `skey` (skey as fallback) |
| MSAF | Boundary detection only, no functional labels | `allin1` |
| `autochord` | 25 chord classes; too sparse for educational use | `lv-chordia` |
| `chord-extractor` (Chordino) | No slash chords; 2010-era | `lv-chordia` |
| `essentia` | No reliable Py3.11/3.12 wheels; AGPL; we don't need it | librosa + dedicated tools |
| YourMT3+ as primary | Packaging immature; JAX/T5X compile pain | `basic-pitch` per stem (with YourMT3+/MR-MT3 documented as 🧪 advanced) |
| Custom JSON only output | Reinvents the wheel | JAMS + summary.json |

## Optional / advanced add-ons

These are documented but **not** in the default pipeline. Add when you have a specific need.

| Tool | Use case | Notes |
|---|---|---|
| 🧪 `MR-MT3` (gudgud96) | Multi-instrument transcription with leakage mitigation | Research code; conda env Python 3.10; heavy deps |
| 🧪 `YourMT3+` (mimbres) | Multi-instrument MoE transcription | Research code; JAX/T5X; expect install friction |
| 🧪 `SOME` (openvpi) | Singing-voice-to-MIDI specifically | Beta, language-biased, needs isolated vocal stem |
| `MERT` (HuggingFace) | Self-supervised music representation embeddings | For future similarity search across your library |
| `mir_eval` | Evaluating analysis quality vs ground truth | Useful if you start labelling songs by hand |
| `pretty_midi` | Reading/writing MIDI cleanly | Used internally by `basic-pitch` |

## Cross-research convergence

Where all three independent researchers (Claude, Codex, Gemini) agreed, treated as **highest-confidence**:

- ✅ `audio-separator` for stems
- ✅ `allin1` for joint metrical+structural analysis
- ✅ `beat-this` for beat cross-check
- ✅ JAMS as output format
- ✅ LLM-as-orchestrator pattern

Where Codex + Gemini agreed but I had missed:

- ⚠️ `skey` for key detection (I had librosa K-S — wrong)
- ⚠️ `lv-chordia` (Codex's pick) and YourMT3+ (Gemini's pick) — converged on "use modern transformers / large-vocab models"

Where the three diverged on f0 (PESTO / RMVPE / FCPE):

- 🔀 picked **FCPE primary + PESTO cross-check** as the "two-voice reconciliation" approach. RMVPE remains documented as an option for voice-conversion-pipeline users.
