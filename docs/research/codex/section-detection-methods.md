# Section Detection Research

Date: 2026-04-30

## Local Project State

MusIQ-Lab currently has no active section-detection stage:

- `analyze/pipeline.py` initializes warnings with `"sections deferred - no segmenter installed"`.
- `analyze/writers/summary_writer.py` hardcodes `"sections": []`.
- `docs/research/tasks/07-section-analysis.md` documents that section detection was deferred after `allin1` was dropped.

The important product requirement is functional song-section labels, not only boundary detection. The target output shape is:

```json
"sections": [
  {"start": 0.0, "end": 15.5, "label": "intro"},
  {"start": 15.5, "end": 47.1, "label": "verse"},
  {"start": 47.1, "end": 78.7, "label": "chorus"}
]
```

## Recommendation

### 1. SongFormer Sidecar Stage

Use SongFormer as a separate section-analysis sidecar.

This is the best fit for the project because it targets semantic music structure analysis: boundaries plus functional labels such as verse, chorus, bridge, intro, and outro. That directly matches the reserved `summary.json["sections"]` schema, unlike older structure tools that mostly emit repeated-cluster labels such as `A`, `B`, and `C`.

Recommended integration:

1. Keep the current MusIQ-Lab environment unchanged.
2. Create a separate `songformer` conda environment so its Torch/dependency stack cannot destabilize the existing Torch 2.7 MIR pipeline.
3. Add `analyze/stages/sections.py` as an optional stage.
4. Have that stage call the SongFormer sidecar and write `cache/<slug>/sections.json`.
5. Snap predicted boundaries to the nearest known downbeat when the prediction is close enough.
6. Write sections into both `summary.json` and JAMS `segment_open` annotations.

Expected output quality:

- Best route to functional labels.
- Modern model family, no dependency on the broken `allin1`/NATTEN path.
- Strongest long-term choice if the project wants educational comments like "this is the chorus progression" or "the bridge pivots harmonically here."

Risks:

- Not packaged as a simple PyPI dependency.
- Should be isolated from the main environment.
- Needs an adapter script and a small validation set before being trusted in batch mode.

Sources:

- SongFormer paper: https://arxiv.org/abs/2510.02797
- SongFormer model card: https://huggingface.co/ASLP-lab/SongFormer
- SongFormer GitHub: https://github.com/ASLP-lab/SongFormer

### 2. librosa/MSAF Boundaries + MusIQ-Lab Heuristics

Use traditional structural segmentation for boundaries and repeated-section clusters, then infer functional labels from MusIQ-Lab's existing derived signals.

This is the safest low-risk implementation path because `librosa` is already part of the stack, and MSAF is a mature music-structure framework. The drawback is that these methods generally produce structural clusters rather than semantic labels.

Recommended integration:

1. Extract chroma and timbral features.
2. Use recurrence/novelty segmentation to estimate boundaries.
3. Cluster similar segments as `A`, `B`, `C`, etc.
4. Use existing `loop_detect.py`, chord progressions, downbeats, duration, and repetition counts to infer likely labels:
   - repeated high-energy cluster with predominant chord loop: likely `chorus`
   - long recurring non-chorus cluster: likely `verse`
   - first short segment: likely `intro`
   - final segment: likely `outro`
5. Mark these labels as inferred or low-confidence.

Expected output quality:

- Good enough for a first implementation of boundaries and repeated-section grouping.
- Useful fallback when SongFormer is unavailable.
- No large model integration required if using the pure-librosa path.

Risks:

- Functional labels are heuristic and can be wrong.
- `k`/section-count selection is non-trivial.
- Jazz, through-composed, classical, and non-pop forms will be weaker.

Sources:

- librosa recurrence matrix: https://librosa.org/doc/latest/generated/librosa.segment.recurrence_matrix.html
- librosa agglomerative segmentation: https://librosa.org/doc/latest/generated/librosa.segment.agglomerative.html
- MSAF GitHub: https://github.com/urinieto/msaf
- MSAF docs: https://msaf.readthedocs.io/en/latest/algorithms.html

### 3. allin1 Legacy Sidecar / Container

Use `allin1` only as an isolated legacy component, not inside the main MusIQ-Lab environment.

`allin1` remains conceptually attractive because it was designed for joint metrical and functional structure analysis. It predicts tempo, beats, downbeats, segment boundaries, and section labels. It was also the original planned source for sections in this project.

However, it is a poor fit for the current environment:

- It depends on NATTEN.
- The project already documented Torch/NATTEN/API incompatibilities.
- The main stack has intentionally moved to Torch 2.7 and newer MIR packages.
- Repairing `allin1` inside the current environment would reopen the same dependency failure mode that caused sections to be deferred.

Recommended use:

- Only consider this as a pinned, isolated container or conda env.
- Treat it as an external binary that writes `sections.json`.
- Do not mix it into the main Python environment.

Expected output quality:

- Potentially good functional labels if the legacy stack can run.
- Less attractive than SongFormer because the dependency path is stale and fragile.

Sources:

- allin1 PyPI: https://pypi.org/project/allin1/
- allin1 paper: https://arxiv.org/abs/2307.16425
- allin1 GitHub: https://github.com/mir-aidj/all-in-one

## Final Ranking

1. **SongFormer sidecar** - best route to true functional section labels.
2. **librosa/MSAF + heuristics** - fastest safe fallback, useful for boundaries/clusters but weaker labels.
3. **allin1 sidecar/container** - possible legacy route, but not recommended for reintegration.

## Implementation Sketch

Add an optional stage:

```text
analyze/stages/sections.py
```

Stage contract:

```python
def cached(cache_dir: Path) -> bool:
    return (cache_dir / "sections.json").exists()

def load(cache_dir: Path) -> list[dict]:
    ...

def run(mp3_path: Path, cache_dir: Path) -> list[dict]:
    ...
```

Pipeline placement:

```python
OPTIONAL_STAGES = [
    ("sections", sections),
    ("beats_xcheck", beats_xcheck),
    ("vocal_f0", vocal_f0),
]
```

Summary writer:

```python
"sections": results.get("sections", [])
```

JAMS writer:

- Add a `segment_open` annotation.
- Use section labels as annotation values.
- Preserve model/source metadata in annotation metadata.

Recommended first implementation sequence:

1. Implement the `sections.py` stage contract with a pure-librosa fallback.
2. Wire summary/JAMS output and tests.
3. Add SongFormer sidecar integration behind an explicit config/env variable.
4. Validate on the existing cached tracks:
   - Gorillaz - Silent Running
   - Charlie Puth - Attention
   - Lou Reed - Perfect Day
   - Autumn Leaves backing track
   - Chet Baker / Paul Desmond Autumn Leaves
   - Bach Air on G String arrangement

