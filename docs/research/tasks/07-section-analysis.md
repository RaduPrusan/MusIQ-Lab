# Section / structural analysis

> ⚠️ **Status (2026-04-29):** **Section detection is currently deferred.** It used to be bundled into `allin1`; with `allin1` dropped (see [`../../history.md`](../../history.md) Phase D), no segmenter is currently installed. The pipeline emits `"sections": []` plus a `"sections deferred — no segmenter installed"` warning in every `summary.json`. This page describes the candidate replacements ranked by how much rework they'd take.

Section analysis identifies the song's functional sections (intro, verse, chorus, bridge, outro, etc.) with timestamps. Used pedagogically to discuss song structure, identify repeated sections, and locate harmonic patterns within their structural context. The fix is non-trivial because we want **functional labels**, not just boundaries.

## Current state in `analyze/`

`analyze/pipeline.py` has no sections stage. `summary.json["sections"]` is hardcoded to `[]` and `provenance.warnings` always includes `"sections deferred — no segmenter installed"`. The JAMS file contains no segment annotation. The Roman-numeral analysis in `analyze/derived/theory.py` runs without section context — it works fine for chord-by-chord harmony but cannot say "this is the chorus's i-iv-V" vs "this is the bridge's modal pivot."

A partial replacement signal already exists: **`analyze/derived/loop_detect.py`** finds the predominant chord loop (typically the chorus's progression) and reports where it appears. That's structurally adjacent — it tells you "this 4-bar pattern repeats X times" without claiming what *kind* of section each instance is.

## Option 1 (cheapest, no new wheels): librosa recurrence + agglomerative clustering

`librosa` is already a transitive dep of half the stack. It ships boundary-detection primitives:

```python
import librosa

y, sr = librosa.load("song.mp3", sr=22050)
chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
mfcc   = librosa.feature.mfcc(y=y, sr=sr)
recurrence = librosa.segment.recurrence_matrix(chroma, mode="affinity", sym=True)
boundaries = librosa.segment.agglomerative(recurrence, k=8)  # k = target section count
boundary_times = librosa.frames_to_time(boundaries, sr=sr)
```

**What this gets you:** boundaries (where sections change), and clustered IDs (`section A`, `section B`) — *not* functional labels.

**Effort:** ~half a day to implement as a new optional stage (`analyze/stages/sections.py`), wire into the pipeline, write the JAMS `segment_open` annotation, and write tests against the gorillaz reference.

**Tradeoffs:** zero new dependencies; clustered output is enough for "find the most repeated section" but isn't `chorus / verse / bridge`. Pairs naturally with `loop_detect.py` — the cluster that contains the predominant chord loop is probably the chorus.

## Option 2 (mid effort): MSAF (Music Structure Analysis Framework)

```bash
pip install msaf
```

```python
import msaf
boundaries, labels = msaf.process("song.mp3", boundaries_id="sf", labels_id="fmc2d")
```

**What this gets you:** boundaries + cluster labels (still not functional names). Includes 4 internal algorithms (`foote`, `sf`, `scluster`, `olda`) — itself an ensemble.

**Tradeoffs:** more accurate boundaries than the librosa recipe; same "no functional labels" limitation; adds a new dependency (check Torch / numpy compat against `requirements.lock` first).

## Option 3 (high effort): retrofit `allin1`

If `allin1` ever becomes installable on Torch 2.7 — either via a NATTEN wheel with the right CXX11 ABI shipping with RPB support restored, or a community fork that rewrites `dinat.py` to use modern `na2d` *and* reproduces RPB semantics on top of fused attention — it would still be the best answer because:
- Functional labels (`verse / chorus / bridge / ...`), not just boundaries.
- Joint training with beats + downbeats means section boundaries fall on downbeats by construction.
- WASPAA 2023 SOTA on Harmonix Set across all four jointly-predicted tasks.

The blocker is structural, not just packaging — see [`../../history.md`](../../history.md) Phase D for why "rewrite `dinat.py` + reproduce RPB on Flex Attention" is research-grade work, not an afternoon.

## Option 4 (research-quality): SongFormer / structure-aware transformers

ASLP-lab/SongFormer and similar 2024-2025 papers use joint chord+structure prediction with modern attention stacks (no NATTEN dependency). Not yet packaged on PyPI. **Revisit when one matures into a `pip install` story.**

## Option 5 (free, partial signal already in pipeline): lean harder on `loop_detect.py`

`analyze/derived/loop_detect.py` already finds the predominant chord loop and reports its appearances. That can be presented as "structural snapshot" output even without true section detection:

```json
"loop_appearances": [
  {"start": 47.1,  "end": 78.7,  "loop_index": 0},
  {"start": 110.3, "end": 141.9, "loop_index": 0},
  {"start": 157.7, "end": 189.3, "loop_index": 0}
]
```

That's enough to tell a student "the same chord progression appears at these three points — that's typically your chorus." No labels, but the pedagogical value is preserved.

## Section labels (target schema, when section detection is reinstated)

The summary.json schema reserves the `sections` field with this shape:

```json
"sections": [
  {"start": 0.0,    "end": 15.5,  "label": "intro"},
  {"start": 15.5,   "end": 47.1,  "label": "verse"},
  {"start": 47.1,   "end": 78.7,  "label": "chorus"}
]
```

Target label set (matches the original `allin1` vocabulary):

| Label | Meaning |
|---|---|
| `start` | Audio leadin / pre-intro silence |
| `end`   | Audio fade-out / post-outro silence |
| `intro` | Song intro |
| `verse` | Verse section |
| `chorus`| Chorus / hook |
| `bridge`| Bridge / middle 8 |
| `outro` | Outro / coda |
| `break` | Breakdown / drop-out section |
| `inst`  | Instrumental section |
| `solo`  | Featured solo |

Options 1 and 2 will only produce cluster IDs (e.g. `A`, `B`, `C`). Mapping cluster → functional label is a separate problem; one heuristic is "the cluster with the most repetitions and the predominant chord loop is the chorus; the longest non-chorus cluster is the verse." That heuristic is fragile but viable as a stopgap until Option 3 or 4 becomes available.

## Sources

- librosa structural segmentation: <https://librosa.org/doc/main/generated/librosa.segment.recurrence_matrix.html>
- MSAF: <https://github.com/urinieto/msaf>
- All-In-One paper (WASPAA 2023, historical context): <https://arxiv.org/abs/2307.16425>
- All-In-One repo (historical context): <https://github.com/mir-aidj/all-in-one>
- Harmonix Set (training data for the original `allin1` section labels): <https://github.com/urinieto/harmonixset>
