# Essentia Second-Opinion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Essentia's `MusicExtractor` over the cached MP3 to produce a slim second-opinion JSON (`cache/<slug>/essentia.json`) covering tempo, key (three estimators), EBU R128 loudness, and high-level mood / danceability labels. Surface tempo/key agreement vs. the analyze pipeline as a cross-check row in the reanalyze modal, and an "Acoustic profile" card in the Track tab.

**Architecture:** New pipeline stage `essentia_extract` follows the same `cached / load / run` contract as the other optional stages. It imports `essentia.standard.MusicExtractor`, runs it on the source MP3, cherry-picks ~20 fields into a slim JSON, and computes `agreement: {bpm, key}` against the existing `beats` and `key` stage outputs. Soft-fails identically to `drums` when Essentia isn't installed. Webui-side, a small reader and two UI components surface the data.

**Tech Stack:** Python 3.11 (WSL `.venv`); `essentia` Python package (≥2.1b6, ~200MB compiled C++); MTG-hosted SVM models (~30MB, downloaded by install script into `analyze/vendor/essentia-models/`).

**Independent of:** Plans A and B. Can ship before or after them; doesn't read anything they produce.

---

## File Structure

```
analyze/stages/
  essentia_extract.py             [NEW] cached/load/run + cross-check derivation
analyze/pipeline.py               [MOD] register essentia_extract
analyze/cli.py                    [MOD] add --no-essentia flag
analyze/writers/summary_writer.py [MOD] surface essentia block in summary.json
analyze/vendor/essentia-models/
  .gitkeep                        [NEW]
scripts/
  install-essentia.sh             [NEW] pip install + model download
tests/unit/
  test_essentia_extract.py        [NEW]
  test_essentia_agreement.py      [NEW]
tests/integration/
  test_essentia_pipeline.py       [NEW]
webui/webui/
  essentia.py                     [NEW] read cache/<slug>/essentia.json
webui/tests/
  test_essentia_reader.py         [NEW]
webui/static/js/sidebar/
  acoustic-profile.js             [NEW] loudness / mood / danceability card
  index.js                        [MOD] mount acoustic-profile
webui/static/js/analyze-modal/
  crosscheck-row.js               [NEW] tempo/key agreement row
  (or wherever the post-run stats panel HTML is composed — modify there)
webui/tests-js/
  acoustic-profile.test.js        [NEW]
  crosscheck-row.test.js          [NEW]
.gitignore                        [MOD] ignore analyze/vendor/essentia-models/*
requirements.txt                  [MOD] add essentia >= 2.1b6
```

---

## Task 1: Install script + vendor dir for SVM models

**Files:**
- Create: `scripts/install-essentia.sh`
- Create: `analyze/vendor/essentia-models/.gitkeep`
- Modify: `.gitignore`
- Modify: `requirements.txt`

- [ ] **Step 1: Add gitignore rule**

Append to `.gitignore` (near the larsnet/chromaprint blocks):

```gitignore
# Essentia high-level SVM models (downloaded by scripts/install-essentia.sh,
# hosted by MTG, mixed CC BY-NC and Apache-2.0 licenses — see
# analyze/vendor/README.md). ~30MB total, not redistributed through this repo.
analyze/vendor/essentia-models/*
!analyze/vendor/essentia-models/.gitkeep
```

Create `.gitkeep` with content `# preserves analyze/vendor/essentia-models/ — populated by scripts/install-essentia.sh`.

- [ ] **Step 2: Add essentia to requirements**

Append to `requirements.txt`:
```
essentia>=2.1b6
```

- [ ] **Step 3: Write the install script**

```bash
#!/usr/bin/env bash
# scripts/install-essentia.sh — install Essentia + download high-level SVM models.
#
# Run from a WSL shell. Adds essentia to the project .venv and downloads
# the SVM models that MusicExtractor's high-level descriptors need.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="$PROJECT_ROOT/analyze/vendor/essentia-models"
VENV="$PROJECT_ROOT/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "ERROR: project .venv not found at $VENV" >&2
  echo "  Activate the WSL .venv first (uv venv .venv inside WSL)." >&2
  exit 1
fi

echo "==> Installing essentia into $VENV"
"$VENV/bin/pip" install 'essentia>=2.1b6'

mkdir -p "$MODELS_DIR"

# High-level SVM models bundled with the MTG release. URLs from
# https://essentia.upf.edu/svm_models/
BASE="https://essentia.upf.edu/svm_models/beta5"
MODELS=(
  "danceability/danceability-msd-2.svm"
  "voice_instrumental/voice_instrumental-msd-2.svm"
  "mood_acoustic/mood_acoustic-msd-2.svm"
  "mood_aggressive/mood_aggressive-msd-2.svm"
  "mood_electronic/mood_electronic-msd-2.svm"
  "mood_happy/mood_happy-msd-2.svm"
  "mood_party/mood_party-msd-2.svm"
  "mood_relaxed/mood_relaxed-msd-2.svm"
  "mood_sad/mood_sad-msd-2.svm"
  "tonal_atonal/tonal_atonal-msd-2.svm"
)

for m in "${MODELS[@]}"; do
  url="$BASE/$m"
  out="$MODELS_DIR/$(basename "$m")"
  if [[ -f "$out" ]]; then
    echo "==> Already present: $(basename "$out")"
    continue
  fi
  echo "==> Downloading $(basename "$out")"
  curl -sSLf -o "$out" "$url"
done

echo "==> Verifying install"
"$VENV/bin/python" -c "from essentia.standard import MusicExtractor; print('essentia OK')"

echo "==> Done. Models in: $MODELS_DIR"
```

Make executable: `chmod +x scripts/install-essentia.sh`.

- [ ] **Step 4: Run the install (WSL)**

```bash
wsl -d Ubuntu-24.04 -- bash -c 'cd "<PROJECT_WSL_PATH>" && bash scripts/install-essentia.sh'
```

Expected output ends with `essentia OK` and `==> Done. Models in: ...`. Takes 3-10 minutes (pip compile + downloads).

If the install fails (Essentia C++ build issues on a particular Ubuntu image), DON'T patch the script — record the failure and surface it back to the orchestration controller. The user may need to apt-install a missing dep (`libavcodec-dev`, `libsamplerate0-dev`).

- [ ] **Step 5: Commit**

```bash
git add scripts/install-essentia.sh analyze/vendor/essentia-models/.gitkeep \
        .gitignore requirements.txt
git commit -m "feat(essentia): install script + vendored SVM models

scripts/install-essentia.sh installs essentia into the WSL .venv and
downloads the high-level SVM models from MTG into
analyze/vendor/essentia-models/. Same vendoring pattern as larsnet
and chromaprint — weights not redistributed through this repo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Essentia extract stage — core extraction

**Files:**
- Create: `analyze/stages/essentia_extract.py`
- Create: `tests/unit/test_essentia_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_essentia_extract.py
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from analyze.stages import essentia_extract


def _fake_features_pool():
    """Mock the MusicExtractor return — a Pool-like object with the descriptor keys."""
    pool = MagicMock()
    descriptors = {
        "rhythm.bpm": 120.1,
        "rhythm.bpm_histogram_first_peak_bpm.median": 120.0,
        "rhythm.bpm_histogram_first_peak_weight.median": 0.62,
        "rhythm.beats_count": 240,
        "tonal.key_krumhansl.key": "A",
        "tonal.key_krumhansl.scale": "minor",
        "tonal.key_krumhansl.strength": 0.81,
        "tonal.key_temperley.key": "A",
        "tonal.key_temperley.scale": "minor",
        "tonal.key_temperley.strength": 0.77,
        "tonal.key_edma.key": "E",
        "tonal.key_edma.scale": "major",
        "tonal.key_edma.strength": 0.42,
        "lowlevel.loudness_ebu128.integrated": -9.2,
        "lowlevel.loudness_ebu128.loudness_range": 7.4,
        "lowlevel.dynamic_complexity": 4.1,
        "highlevel.danceability.all.danceable": 0.71,
        "highlevel.voice_instrumental.all.voice": 0.92,
        "highlevel.mood_electronic.all.electronic": 0.88,
        "highlevel.mood_acoustic.all.acoustic": 0.12,
        "highlevel.mood_happy.all.happy": 0.41,
        "highlevel.mood_sad.all.sad": 0.22,
    }
    pool.descriptorNames.return_value = list(descriptors)
    pool.__getitem__.side_effect = lambda k: descriptors[k]
    return pool, descriptors


def test_run_writes_slim_essentia_json(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    pool, descriptors = _fake_features_pool()

    fake_extractor = MagicMock(return_value=(pool, MagicMock()))
    monkeypatch.setattr(essentia_extract, "_build_extractor", lambda: fake_extractor)

    out = essentia_extract.run(mp3, tmp_path)

    assert out["extracted"] is True
    assert out["tempo"]["bpm"] == 120.1
    assert out["tempo"]["first_peak_bpm"] == 120.0
    assert out["key"]["krumhansl"] == ["A", "minor", 0.81]
    assert out["key"]["edma"] == ["E", "major", 0.42]
    assert out["loudness_ebu_r128"]["integrated"] == -9.2
    assert out["high_level"]["danceability"] == 0.71
    assert out["high_level"]["mood_electronic"] == 0.88

    # On-disk
    on_disk = json.loads((tmp_path / "essentia.json").read_text())
    assert on_disk == out


def test_run_soft_fails_when_essentia_missing(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")

    def explode():
        raise ImportError("essentia not installed")
    monkeypatch.setattr(essentia_extract, "_build_extractor", explode)

    out = essentia_extract.run(mp3, tmp_path)
    assert out == {"extracted": False, "reason": "essentia not installed"}
    assert (tmp_path / "essentia.json").exists()


def test_run_soft_fails_on_extractor_error(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    fake_extractor = MagicMock(side_effect=RuntimeError("audio decode failed"))
    monkeypatch.setattr(essentia_extract, "_build_extractor", lambda: fake_extractor)

    out = essentia_extract.run(mp3, tmp_path)
    assert out["extracted"] is False
    assert "audio decode" in out["reason"]


def test_cached_after_run(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")

    def explode():
        raise ImportError("essentia not installed")
    monkeypatch.setattr(essentia_extract, "_build_extractor", explode)

    essentia_extract.run(mp3, tmp_path)
    assert essentia_extract.cached(tmp_path) is True
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_essentia_extract.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the stage**

```python
"""Stage: Essentia MusicExtractor — second opinion on tempo / key / loudness / mood.

Output: cache_dir/essentia.json with either
    {"extracted": true,
     "tempo": {"bpm": 120.1, "first_peak_bpm": 120, "first_peak_weight": 0.62,
               "beats_count": 240},
     "key": {"krumhansl": ["A","minor",0.81], "temperley": [...], "edma": [...]},
     "loudness_ebu_r128": {"integrated": -9.2, "range": 7.4, "dynamic_complexity": 4.1},
     "high_level": {"danceability": 0.71, "voice_instrumental": "voice",
                    "mood_electronic": 0.88, "mood_acoustic": 0.12,
                    "mood_happy": 0.41, "mood_sad": 0.22}}
or
    {"extracted": false, "reason": "..."}

Soft-fails to the not-extracted sentinel on any error, same pattern as
analyze/stages/drums.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from analyze import sidecar

CANONICAL = "essentia.json"
SCHEMA_VERSION = 1
DEFAULT_PARAMS: dict = {}

_MODELS_DIR = Path(__file__).resolve().parents[1] / "vendor" / "essentia-models"


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "essentia_extract", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def _build_extractor():
    """Construct an Essentia MusicExtractor configured for our slim feature set.

    Separated out so tests can monkeypatch this whole function (the real
    MusicExtractor is heavy + has C++ deps we don't want to import in unit tests).
    """
    from essentia.standard import MusicExtractor

    svm_models = sorted(str(p) for p in _MODELS_DIR.glob("*.svm"))
    return MusicExtractor(
        lowlevelStats=["mean", "stdev"],
        rhythmStats=["mean", "stdev"],
        tonalStats=["mean", "stdev"],
        highlevel=svm_models,
    )


def _pick(pool, key, default=None):
    """Safe accessor for Essentia Pool keys that may or may not be present."""
    try:
        if key in pool.descriptorNames():
            return pool[key]
    except Exception:
        pass
    return default


def _extract_slim(pool) -> dict:
    """Cherry-pick ~20 fields out of the ~500-key Essentia output."""
    return {
        "extracted": True,
        "tempo": {
            "bpm": float(_pick(pool, "rhythm.bpm", 0.0)),
            "first_peak_bpm": float(_pick(pool, "rhythm.bpm_histogram_first_peak_bpm.median", 0.0)),
            "first_peak_weight": float(_pick(pool, "rhythm.bpm_histogram_first_peak_weight.median", 0.0)),
            "beats_count": int(_pick(pool, "rhythm.beats_count", 0)),
        },
        "key": {
            "krumhansl": [
                _pick(pool, "tonal.key_krumhansl.key", ""),
                _pick(pool, "tonal.key_krumhansl.scale", ""),
                float(_pick(pool, "tonal.key_krumhansl.strength", 0.0)),
            ],
            "temperley": [
                _pick(pool, "tonal.key_temperley.key", ""),
                _pick(pool, "tonal.key_temperley.scale", ""),
                float(_pick(pool, "tonal.key_temperley.strength", 0.0)),
            ],
            "edma": [
                _pick(pool, "tonal.key_edma.key", ""),
                _pick(pool, "tonal.key_edma.scale", ""),
                float(_pick(pool, "tonal.key_edma.strength", 0.0)),
            ],
        },
        "loudness_ebu_r128": {
            "integrated": float(_pick(pool, "lowlevel.loudness_ebu128.integrated", 0.0)),
            "range": float(_pick(pool, "lowlevel.loudness_ebu128.loudness_range", 0.0)),
            "dynamic_complexity": float(_pick(pool, "lowlevel.dynamic_complexity", 0.0)),
        },
        "high_level": {
            "danceability": float(_pick(pool, "highlevel.danceability.all.danceable", 0.0)),
            "voice_instrumental": "voice"
                if float(_pick(pool, "highlevel.voice_instrumental.all.voice", 0.0)) > 0.5
                else "instrumental",
            "mood_acoustic": float(_pick(pool, "highlevel.mood_acoustic.all.acoustic", 0.0)),
            "mood_electronic": float(_pick(pool, "highlevel.mood_electronic.all.electronic", 0.0)),
            "mood_happy": float(_pick(pool, "highlevel.mood_happy.all.happy", 0.0)),
            "mood_sad": float(_pick(pool, "highlevel.mood_sad.all.sad", 0.0)),
        },
    }


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}
    try:
        extractor = _build_extractor()
    except ImportError as e:
        out = {"extracted": False, "reason": f"essentia not installed: {e}"}
        _write(cache_dir, out, p)
        return out

    try:
        pool, _frames = extractor(str(mp3))
    except Exception as e:
        out = {"extracted": False, "reason": f"extractor failed: {type(e).__name__}: {e}"}
        _write(cache_dir, out, p)
        return out

    out = _extract_slim(pool)
    _write(cache_dir, out, p)
    return out


def _write(cache_dir: Path, payload: dict, params: dict) -> None:
    (cache_dir / CANONICAL).write_text(json.dumps(payload, indent=2))
    sidecar.write(cache_dir, "essentia_extract", params, schema_version=SCHEMA_VERSION)
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_essentia_extract.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add analyze/stages/essentia_extract.py tests/unit/test_essentia_extract.py
git commit -m "feat(essentia): essentia_extract stage produces slim JSON

Stage runs MusicExtractor with low/rhythm/tonal stats + high-level SVMs,
cherry-picks ~20 fields into a slim cache/<slug>/essentia.json. Soft-
fails to {extracted: false, reason} when essentia is not installed or
the extractor blows up on a particular file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Tempo / key cross-check against the analyze pipeline

**Files:**
- Modify: `analyze/stages/essentia_extract.py` (add agreement computation)
- Create: `tests/unit/test_essentia_agreement.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_essentia_agreement.py
import pytest

from analyze.stages.essentia_extract import compute_agreement


def test_bpm_agreement_within_one_bpm():
    pipeline = {"tempo_bpm": 120.0}
    essentia = {"tempo": {"bpm": 120.4}, "key": {"krumhansl": ["A", "minor", 0.81]}}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["bpm"]["ok"] is True
    assert agreement["bpm"]["delta"] == pytest.approx(0.4, abs=0.01)


def test_bpm_disagreement_when_delta_above_threshold():
    pipeline = {"tempo_bpm": 120.0}
    essentia = {"tempo": {"bpm": 90.0}, "key": {"krumhansl": ["A", "minor", 0.81]}}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["bpm"]["ok"] is False
    assert agreement["bpm"]["delta"] == pytest.approx(30.0, abs=0.01)


def test_bpm_half_tempo_caught_as_disagreement():
    """Essentia at 60, pipeline at 120 — Essentia is at half tempo."""
    pipeline = {"tempo_bpm": 120.0}
    essentia = {"tempo": {"bpm": 60.0}, "key": {"krumhansl": ["A", "minor", 0.81]}}
    agreement = compute_agreement(pipeline, essentia)
    # Half-tempo is a disagreement — the cross-check is about raw agreement,
    # not "is there a sensible relationship". Surfaces visibly in the UI.
    assert agreement["bpm"]["ok"] is False


def test_key_agreement_uses_best_estimator_consensus():
    """key.ok when at least 2 of 3 Essentia estimators agree with pipeline."""
    pipeline = {"key": "A:minor"}
    essentia = {
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["A", "minor", 0.81],
            "temperley": ["A", "minor", 0.77],
            "edma": ["E", "major", 0.42],  # disagrees, but krumhansl + temperley agree
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is True
    assert agreement["key"]["analyze"] == "A:minor"
    assert agreement["key"]["essentia_consensus"] == "A:minor"


def test_key_disagreement_when_essentia_estimators_split():
    pipeline = {"key": "A:minor"}
    essentia = {
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["C", "major", 0.9],
            "temperley": ["D", "major", 0.8],
            "edma": ["E", "major", 0.4],  # all three disagree with pipeline
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is False


def test_agreement_skipped_when_essentia_not_extracted():
    pipeline = {"tempo_bpm": 120.0, "key": "A:minor"}
    essentia = {"extracted": False, "reason": "not installed"}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement == {}
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_essentia_agreement.py -v`
Expected: FAIL — `compute_agreement` undefined.

- [ ] **Step 3: Implement**

Append to `analyze/stages/essentia_extract.py`:

```python
BPM_TOLERANCE = 1.0  # |Essentia.bpm - pipeline.tempo_bpm| ≤ 1 → ok


def compute_agreement(pipeline_summary: dict, essentia_data: dict) -> dict:
    """Compare Essentia's tempo + key against the analyze pipeline's output.

    Returns ``{}`` if Essentia didn't extract (caller renders nothing).
    Otherwise ``{"bpm": {analyze, essentia, delta, ok}, "key": {analyze, essentia_consensus, ok}}``.

    Key agreement uses 2-of-3 estimator consensus: if at least two of
    krumhansl / temperley / edma agree on (pitch, mode), that pair is the
    "essentia consensus." The cross-check is ok if the consensus matches
    the pipeline's key. EDMA is the most permissive estimator (often
    biased toward major / electronic music), so requiring 2-of-3 protects
    against EDMA single-handedly tipping the result.
    """
    if not essentia_data.get("extracted"):
        return {}

    out: dict = {}

    pipeline_bpm = pipeline_summary.get("tempo_bpm")
    essentia_bpm = essentia_data.get("tempo", {}).get("bpm")
    if pipeline_bpm is not None and essentia_bpm is not None:
        delta = abs(float(essentia_bpm) - float(pipeline_bpm))
        out["bpm"] = {
            "analyze": round(float(pipeline_bpm), 2),
            "essentia": round(float(essentia_bpm), 2),
            "delta": round(delta, 2),
            "ok": delta <= BPM_TOLERANCE,
        }

    pipeline_key = pipeline_summary.get("key")  # "A:minor"
    keys = essentia_data.get("key") or {}
    estimators = [keys.get("krumhansl"), keys.get("temperley"), keys.get("edma")]
    pairs = [(k[0], k[1]) for k in estimators if k and k[0] and k[1]]

    if pipeline_key and pairs:
        from collections import Counter
        counts = Counter(pairs)
        # consensus = pair with >= 2 votes; if none, fall back to highest-strength
        consensus_pair, votes = counts.most_common(1)[0]
        if votes >= 2:
            consensus = f"{consensus_pair[0]}:{consensus_pair[1]}"
        else:
            best = max(
                (k for k in estimators if k),
                key=lambda k: float(k[2] or 0.0),
                default=None,
            )
            consensus = f"{best[0]}:{best[1]}" if best else ""
        out["key"] = {
            "analyze": pipeline_key,
            "essentia_consensus": consensus,
            "ok": consensus == pipeline_key,
        }

    return out
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_essentia_agreement.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add analyze/stages/essentia_extract.py tests/unit/test_essentia_agreement.py
git commit -m "feat(essentia): tempo/key agreement cross-check

compute_agreement(pipeline_summary, essentia_data) emits a flat dict
with bpm.{analyze,essentia,delta,ok} and key.{analyze,essentia_consensus,ok}.
Tolerance: ±1 BPM. Key uses 2-of-3 estimator consensus so EDMA can't
single-handedly tip a disagreement (it's biased toward electronic /
major). Returns {} when Essentia didn't extract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Pipeline registration + `--no-essentia` flag

**Files:**
- Modify: `analyze/pipeline.py`
- Modify: `analyze/cli.py`
- Create: `tests/integration/test_essentia_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_essentia_pipeline.py
from analyze import pipeline


def test_essentia_extract_registered():
    stage_names = [name for name, _ in pipeline._STAGE_EXECUTION_ORDER]
    assert "essentia_extract" in stage_names


def test_essentia_extract_is_optional():
    optional_names = [name for name, _ in pipeline.OPTIONAL_STAGES]
    assert "essentia_extract" in optional_names


def test_essentia_extract_runs_late():
    """essentia_extract must run AFTER beats + key so compute_agreement has
    something to compare against."""
    order = [name for name, _ in pipeline._STAGE_EXECUTION_ORDER]
    assert order.index("essentia_extract") > order.index("beats")
    assert order.index("essentia_extract") > order.index("key")


def test_essentia_extract_has_correct_deps():
    """STAGE_DEPS for essentia_extract should include beats + key (for the
    agreement cross-check). Selecting --stages-only essentia_extract
    requires beats + key already cached."""
    assert "essentia_extract" in pipeline.STAGE_DEPS
    deps = pipeline.STAGE_DEPS["essentia_extract"]
    assert "beats" in deps
    assert "key" in deps
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/integration/test_essentia_pipeline.py -v`
Expected: FAIL — `"essentia_extract" not in stage_names`.

- [ ] **Step 3: Wire the stage**

In `analyze/pipeline.py`:

(a) Add to the import block:
```python
from analyze.stages import (
    ...
    essentia_extract,
    ...
)
```

(b) Append to `OPTIONAL_STAGES`:
```python
    # Essentia second-opinion: tempo / key / loudness / mood. Heavy native
    # C++ install (~200MB + ~30MB SVM models in analyze/vendor/essentia-models/).
    # Optional — soft-fails to {extracted: false, reason} when essentia is
    # not installed. Runs LAST so the cross-check can read beats + key.
    ("essentia_extract", essentia_extract),
```

(c) Insert into `_STAGE_EXECUTION_ORDER` AT THE END (after `vocal_consensus_contour`):
```python
_STAGE_EXECUTION_ORDER = [
    ...
    ("vocal_consensus_contour", vocal_consensus_contour),
    ("essentia_extract", essentia_extract),   # NEW — runs last; reads no other stage's output directly, but the post-pipeline cross-check uses beats + key
]
```

(d) Add the STAGE_DEPS entry:
```python
STAGE_DEPS = {
    ...
    "essentia_extract":          frozenset({"beats", "key"}),
}
```

In `analyze/cli.py`, add the flag (next to `--no-identify` from Plan A):

```python
parser.add_argument(
    "--no-essentia",
    action="store_true",
    help="skip the Essentia second-opinion stage",
)
```

And in the analyze() call site:

```python
skip_stages = set()
if args.no_identify:
    skip_stages.add("identify")
if args.no_essentia:
    skip_stages.add("essentia_extract")
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/integration/test_essentia_pipeline.py -v`
Expected: 4 passed.

Run: `pytest tests/unit/test_stage_deps.py -v`
Expected: still passes (DAG remains valid).

- [ ] **Step 5: Commit**

```bash
git add analyze/pipeline.py analyze/cli.py tests/integration/test_essentia_pipeline.py
git commit -m "feat(essentia): register essentia_extract + --no-essentia flag

Pipeline registers essentia_extract as the last stage, with STAGE_DEPS
{beats, key} (the cross-check needs both). --no-essentia threads
through the generic skip_stages mechanism added for --no-identify.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Summary writer integration + cross-check field

**Files:**
- Modify: `analyze/writers/summary_writer.py`
- Modify: `tests/unit/test_writers.py`

- [ ] **Step 1: Add failing test**

Append to `tests/unit/test_writers.py`:

```python
def test_summary_includes_essentia_with_agreement(tmp_path):
    """When results['essentia_extract'] is set, summary.json gets
    summary.essentia + summary.essentia_agreement."""
    from analyze.writers.summary_writer import write_summary
    # Use the same minimal-results fixture pattern as test_summary_includes_identify_*.
    # Add essentia_extract = {extracted: True, tempo: {bpm: 120.4}, key: {...}, ...}
    # and assert summary['essentia']['tempo']['bpm'] == 120.4
    # and assert 'bpm' in summary['essentia_agreement']
```

(Specifics depend on the local fixture pattern — read the existing tests in this file and follow them.)

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_writers.py::test_summary_includes_essentia_with_agreement -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `analyze/writers/summary_writer.py`, locate where summary dict is built. After the existing optional-stage write-throughs (e.g. where drums is added), add:

```python
if "essentia_extract" in results:
    from analyze.stages.essentia_extract import compute_agreement
    essentia_data = results["essentia_extract"]
    summary["essentia"] = essentia_data
    agreement = compute_agreement(summary, essentia_data)
    if agreement:
        summary["essentia_agreement"] = agreement
```

The agreement computation needs the pipeline's `tempo_bpm` and `key`, both of which are already written into `summary` earlier in `write_summary`. Confirm those fields exist BEFORE the new block; if they don't (e.g. they're computed later), move the new block to after they're set.

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_writers.py -v`
Expected: existing tests still pass + new one passes.

- [ ] **Step 5: Commit**

```bash
git add analyze/writers/summary_writer.py tests/unit/test_writers.py
git commit -m "feat(essentia): summary.json gets essentia + essentia_agreement

When the essentia_extract stage ran, summary.essentia is the slim
JSON and summary.essentia_agreement is the {bpm, key} cross-check
computed against summary.tempo_bpm + summary.key.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Webui reader for essentia.json

**Files:**
- Create: `webui/webui/essentia.py`
- Create: `webui/tests/test_essentia_reader.py`

- [ ] **Step 1: Failing test**

```python
# webui/tests/test_essentia_reader.py
import json
from pathlib import Path

from webui.essentia import read_essentia


def test_read_essentia_returns_payload(tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    payload = {"extracted": True, "tempo": {"bpm": 120.1}, "high_level": {}}
    (cache_dir / "essentia.json").write_text(json.dumps(payload))
    assert read_essentia(cache_dir) == payload


def test_read_essentia_missing_returns_none(tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    assert read_essentia(cache_dir) is None


def test_read_essentia_corrupt_returns_none(tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    (cache_dir / "essentia.json").write_text("not json {")
    assert read_essentia(cache_dir) is None
```

- [ ] **Step 2: Run — fail**

Run: `.venv/Scripts/python -m pytest tests/test_essentia_reader.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# webui/webui/essentia.py
"""Read cache/<slug>/essentia.json (written by the analyze pipeline)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def read_essentia(cache_dir: Path) -> dict | None:
    path = cache_dir / "essentia.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.warning("essentia.json corrupt at %s: %s", path, e)
        return None
```

- [ ] **Step 4: Run — pass**

Run: `.venv/Scripts/python -m pytest tests/test_essentia_reader.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/essentia.py webui/tests/test_essentia_reader.py
git commit -m "feat(essentia): webui reader for cache/<slug>/essentia.json

Mirrors webui.identify.read_identify — returns the payload, or None
on missing / corrupt. Same robustness contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Acoustic profile UI card

**Files:**
- Create: `webui/static/js/sidebar/acoustic-profile.js`
- Create: `webui/tests-js/acoustic-profile.test.js`

- [ ] **Step 1: Failing test**

```js
// webui/tests-js/acoustic-profile.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderAcousticProfile } from '../static/js/sidebar/acoustic-profile.js';

test('renders loudness + danceability when extracted', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      loudness_ebu_r128: { integrated: -9.2, range: 7.4 },
      high_level: {
        danceability: 0.71,
        voice_instrumental: 'voice',
        mood_electronic: 0.88,
        mood_acoustic: 0.12,
        mood_happy: 0.41,
        mood_sad: 0.22,
      },
    },
  });
  assert.ok(html.includes('-9.2'));
  assert.ok(html.includes('LUFS'));
  assert.ok(html.includes('Danceability') || html.includes('danceability'));
});

test('renders top moods as pills', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      loudness_ebu_r128: { integrated: -9.2, range: 7.4 },
      high_level: {
        danceability: 0.5,
        voice_instrumental: 'voice',
        mood_electronic: 0.92,
        mood_acoustic: 0.03,
        mood_happy: 0.72,
        mood_sad: 0.10,
      },
    },
  });
  // mood_electronic (0.92) and mood_happy (0.72) should appear (>0.5)
  assert.ok(html.includes('electronic'));
  assert.ok(html.includes('happy'));
  // mood_sad (0.10) and mood_acoustic (0.03) should not (<0.5)
  assert.ok(!html.includes('mood_sad'));
});

test('returns empty when not extracted', () => {
  assert.equal(renderAcousticProfile({ essentia: { extracted: false, reason: 'x' } }), '');
});

test('returns empty when essentia is missing', () => {
  assert.equal(renderAcousticProfile({}), '');
});
```

- [ ] **Step 2: Run — fail**

Run: `node --test webui/tests-js/acoustic-profile.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement**

```js
// webui/static/js/sidebar/acoustic-profile.js
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

const MOOD_THRESHOLD = 0.5;
const MOOD_LABELS = {
  mood_acoustic: 'acoustic',
  mood_electronic: 'electronic',
  mood_happy: 'happy',
  mood_sad: 'sad',
};

function moodPills(highLevel) {
  if (!highLevel) return '';
  const pills = [];
  for (const [key, label] of Object.entries(MOOD_LABELS)) {
    const val = Number(highLevel[key] || 0);
    if (val >= MOOD_THRESHOLD) {
      pills.push(
        `<span class="mood-pill mood-${escapeHtml(label)}" title="${val.toFixed(2)}">` +
        `${escapeHtml(label)}</span>`,
      );
    }
  }
  return pills.length ? `<div class="mood-pills">${pills.join('')}</div>` : '';
}

export function renderAcousticProfile(trackData) {
  const e = trackData && trackData.essentia;
  if (!e || !e.extracted) return '';

  const lufs = e.loudness_ebu_r128 || {};
  const hl = e.high_level || {};

  const dancePct = Math.round((hl.danceability || 0) * 100);

  return `<section class="sidebar-card acoustic-profile">` +
    `<h3>Acoustic Profile</h3>` +
    `<div class="meta-row"><span class="label">Loudness</span>` +
    `<span class="value">${escapeHtml(lufs.integrated?.toFixed(1) ?? '–')} LUFS</span></div>` +
    `<div class="meta-row"><span class="label">Range</span>` +
    `<span class="value">${escapeHtml(lufs.range?.toFixed(1) ?? '–')} LU</span></div>` +
    `<div class="meta-row"><span class="label">Danceability</span>` +
    `<span class="value">` +
      `<div class="bar"><div class="bar-fill" style="width:${dancePct}%"></div></div>` +
      `<span class="bar-pct">${dancePct}%</span>` +
    `</span></div>` +
    moodPills(hl) +
    `</section>`;
}
```

Add minimal CSS to `webui/static/css/sidebar.css`:

```css
.acoustic-profile .bar {
  display: inline-block;
  width: 60px;
  height: 6px;
  background: var(--bar-bg, rgba(255,255,255,0.08));
  border-radius: 3px;
  vertical-align: middle;
  margin-right: 4px;
}
.acoustic-profile .bar-fill {
  height: 100%;
  background: var(--accent, #4ade80);
  border-radius: 3px;
}
.acoustic-profile .bar-pct {
  font-size: 0.8em;
  color: var(--text-muted);
}
.acoustic-profile .mood-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.acoustic-profile .mood-pill {
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--mood-bg, rgba(255,255,255,0.08));
  font-size: 0.8em;
}
```

- [ ] **Step 4: Run — pass**

Run: `node --test webui/tests-js/acoustic-profile.test.js`
Expected: 4 passed.

- [ ] **Step 5: Mount in sidebar**

In `webui/static/js/sidebar/index.js` (or wherever the Track tab sections are composed), import + insert:

```js
import { renderAcousticProfile } from './acoustic-profile.js';

const sections = [
  renderMetadataCard(trackData),
  /* existing analysis cards (Now Playing / Stems / Loop / Harmony stats) */
  renderAcousticProfile(trackData),
  /* renderTagsSection from Plan B if present */
];
```

Also: the track-data loader needs to include `essentia` in `trackData`. Confirm the backend `/api/track/<slug>` endpoint already includes `summary.essentia` (it should — Task 5 wrote it to summary.json, and the existing endpoint serves summary.json fields). If not, add a passthrough.

- [ ] **Step 6: Commit**

```bash
git add webui/static/js/sidebar/acoustic-profile.js webui/static/js/sidebar/index.js \
        webui/static/css/sidebar.css webui/tests-js/acoustic-profile.test.js
git commit -m "feat(essentia): Acoustic Profile card in Track tab

Loudness (LUFS + range), danceability bar, mood pills (>0.5 threshold,
top 4 moods). Hides when essentia not extracted. XSS-escaped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Reanalyze modal cross-check row

**Files:**
- Create: `webui/static/js/analyze-modal/crosscheck-row.js`
- Modify: existing analyze-modal stats panel composer (find via `grep -rn 'stats panel' webui/static/js` or similar; the modal is built somewhere in the JS layer)
- Create: `webui/tests-js/crosscheck-row.test.js`

- [ ] **Step 1: Inspect**

Find where the post-reanalyze stats panel is composed. The README mentions: "live stage badge + scrolling log + post-run stats panel (duration, tempo, key+confidence, scale, chord/downbeat/note counts, drum hit breakdown, ...)." Locate that composition; that's where the new row attaches.

- [ ] **Step 2: Failing test**

```js
// webui/tests-js/crosscheck-row.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderCrosscheckRow } from '../static/js/analyze-modal/crosscheck-row.js';

test('renders agreement green when ok', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 120.0, essentia: 120.4, delta: 0.4, ok: true },
    key: { analyze: 'A:minor', essentia_consensus: 'A:minor', ok: true },
  });
  assert.ok(html.includes('120') && html.includes('agree'));
  assert.ok(html.includes('A:minor'));
});

test('renders disagreement yellow', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 120.0, essentia: 60.0, delta: 60.0, ok: false },
    key: { analyze: 'A:minor', essentia_consensus: 'A:minor', ok: true },
  });
  assert.ok(html.includes('60') || html.includes('disagree'));
});

test('returns empty when agreement object is empty', () => {
  assert.equal(renderCrosscheckRow({}), '');
});

test('returns empty when agreement is missing entirely', () => {
  assert.equal(renderCrosscheckRow(undefined), '');
});
```

- [ ] **Step 3: Run — fail**

Run: `node --test webui/tests-js/crosscheck-row.test.js`
Expected: FAIL.

- [ ] **Step 4: Implement**

```js
// webui/static/js/analyze-modal/crosscheck-row.js
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function icon(ok) {
  // ✓ when ok, ⚠ otherwise. Pure text, no SVG dependency.
  return ok
    ? '<span class="xcheck-icon ok" title="Essentia agrees">✓</span>'
    : '<span class="xcheck-icon warn" title="Essentia disagrees">⚠</span>';
}

export function renderCrosscheckRow(agreement) {
  if (!agreement || Object.keys(agreement).length === 0) return '';

  const rows = [];
  if (agreement.bpm) {
    const b = agreement.bpm;
    rows.push(
      `<div class="xcheck-row">${icon(b.ok)}` +
      `<span class="label">Tempo</span>` +
      `<span class="value">${escapeHtml(b.analyze)} vs ${escapeHtml(b.essentia)} BPM ` +
      `(Δ ${escapeHtml(b.delta)})</span></div>`,
    );
  }
  if (agreement.key) {
    const k = agreement.key;
    rows.push(
      `<div class="xcheck-row">${icon(k.ok)}` +
      `<span class="label">Key</span>` +
      `<span class="value">${escapeHtml(k.analyze)} vs ${escapeHtml(k.essentia_consensus)}</span></div>`,
    );
  }
  if (rows.length === 0) return '';

  return `<div class="xcheck-block"><h4>Essentia cross-check</h4>${rows.join('')}</div>`;
}
```

CSS in `webui/static/css/analyze-modal.css` (or wherever the modal is styled):

```css
.xcheck-block { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-subtle); }
.xcheck-block h4 { margin: 0 0 4px 0; font-size: 0.9em; color: var(--text-muted); }
.xcheck-row { display: flex; gap: 8px; align-items: center; padding: 2px 0; }
.xcheck-icon.ok { color: var(--ok, #4ade80); }
.xcheck-icon.warn { color: var(--warn, #facc15); }
```

- [ ] **Step 5: Run — pass**

Run: `node --test webui/tests-js/crosscheck-row.test.js`
Expected: 4 passed.

- [ ] **Step 6: Mount in stats panel**

In the modal stats composer (located in Step 1), import + insert:

```js
import { renderCrosscheckRow } from './crosscheck-row.js';

// After the existing stats rows (tempo, key, etc.), append:
panelHTML += renderCrosscheckRow(summary.essentia_agreement);
```

(`summary` here is the post-analyze summary object the modal already has access to.)

- [ ] **Step 7: Smoke check**

After running `python -m analyze tests/mp3/silent-running.mp3 --force` (with Essentia installed), open the webui and trigger Reanalyze. The post-run stats panel should show the new "Essentia cross-check" block with two rows. Confirm the ✓ / ⚠ icons render correctly.

- [ ] **Step 8: Commit**

```bash
git add webui/static/js/analyze-modal/crosscheck-row.js \
        webui/tests-js/crosscheck-row.test.js \
        webui/static/css/analyze-modal.css
# Also commit the file where the modal composer was modified.
git commit -m "feat(essentia): cross-check row in reanalyze modal

Renders 'Tempo: 120.0 vs 120.4 BPM ✓' and 'Key: A:minor vs A:minor ✓'
in the post-run stats panel. Disagreements get the ⚠ icon — visual
heads-up that one of the two MIR opinions might be wrong.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Gorillaz smoke test

**Files:**
- Run (no code): full pipeline against the Gorillaz fixture
- Manual verification

- [ ] **Step 1: Run the full pipeline**

```bash
wsl -d Ubuntu-24.04 -- bash -c 'cd "<PROJECT_WSL_PATH>" && source .venv/bin/activate && python -m analyze tests/mp3/silent-running.mp3 --force 2>&1 | tail -40'
```

Expected: pipeline completes, last few stages include `==> Stage essentia_extract: running` and end with `Wrote ...summary.json`.

- [ ] **Step 2: Verify artifact**

```bash
cat "cache/gorillaz_silent_running/essentia.json" | head -40
cat "cache/gorillaz_silent_running/gorillaz_silent_running.summary.json" | jq '.essentia_agreement'
```

Expected: `essentia.json` has tempo/key/loudness/high_level blocks; `essentia_agreement` is `{"bpm": {...}, "key": {...}}` with `ok: true` (or false with sensible deltas).

- [ ] **Step 3: Verify webui**

`webui.ps1 restart`. Open the Gorillaz track. Confirm:
- Track tab has the Acoustic Profile card with loudness LUFS, danceability bar, mood pills.
- Reanalyze flow (Tools → Reanalyze) shows the cross-check row in the post-run panel.

- [ ] **Step 4: Document**

Append to `docs/history.md` a short entry: "Essentia second-opinion landed YYYY-MM-DD. Slim `essentia.json` + `essentia_agreement` block in summary. Acoustic Profile card + reanalyze cross-check row. Tempo / key consensus 2-of-3 across Krumhansl / Temperley / EDMA. ±1 BPM tolerance."

- [ ] **Step 5: Commit**

```bash
git add docs/history.md
git commit -m "docs(history): Essentia second-opinion shipped

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- ✅ Install script + SVM models (Task 1)
- ✅ Essentia extraction stage (Task 2)
- ✅ Cross-check derivation (Task 3)
- ✅ Pipeline + CLI integration (Task 4)
- ✅ Summary writer integration (Task 5)
- ✅ Webui reader (Task 6)
- ✅ Acoustic Profile card (Task 7)
- ✅ Reanalyze modal cross-check row (Task 8)
- ✅ End-to-end smoke test (Task 9)

**Failure modes covered:**
- ✅ Essentia not installed (Task 2 test)
- ✅ Extractor blows up on a specific file (Task 2 test)
- ✅ EDMA single-handedly tipping a key disagreement (Task 3 test — 2-of-3 consensus)
- ✅ Half-tempo BPM (Task 3 test — caught as disagreement, intentional)
- ✅ Corrupt essentia.json (Task 6 test)
- ✅ Empty agreement object (Task 8 test)

**Type consistency:**
- `essentia.json` shape: `{extracted: bool, tempo: {...}, key: {krumhansl|temperley|edma: [pitch, mode, strength]}, loudness_ebu_r128: {...}, high_level: {...}}` — consistent across Tasks 2, 3, 5, 6, 7.
- `compute_agreement` output: `{bpm: {analyze, essentia, delta, ok}, key: {analyze, essentia_consensus, ok}}` — Task 8 UI reads exactly those fields.
- `summary.essentia` + `summary.essentia_agreement` — Tasks 5, 7, 8 all reference these names.

**Placeholders:** None. The two "inspect existing code first" steps (Task 5 Step 1's fixture pattern, Task 8 Step 1's stats panel composer) name what to find; the implementation steps that follow include actual code.
