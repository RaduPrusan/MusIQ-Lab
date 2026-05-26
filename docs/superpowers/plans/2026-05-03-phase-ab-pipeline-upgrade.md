# Phase A+B Pipeline Upgrade Implementation Plan

> **Status: PARTIAL 2026-05-03** — Phase A (selective re-run + per-stage params sidecar) shipped via `e5f21f2 feat(analyze): per-stage params sidecar + STAGE_DEPS + selective re-run (WI-1)` and `47fd118 feat(webui): selective re-run + per-stage params payload (WI-11)`. Phase B (multi-model stems orchestrator) shipped via `0ef8586 feat(analyze): multi-model stems orchestrator + stems_routing.json (WI-6)`. Code-correctness ship-gate APPROVED in `c66862f validate: Phase A+B ship-gate report (Gorillaz partial; APPROVED for code-correctness)`. **Validation against the full 21-track corpus is BLOCKED on user labels** — see [`install-logs/phase-a-validation.md`](../../../install-logs/phase-a-validation.md): non-Gorillaz tracks show baseline==candidate by construction because they haven't been re-run under Phase A+B with ear-truth comparison. Once user-supplied labels arrive for the remaining 20 tracks, the validation table can be filled and this banner promoted to SHIPPED. Post-ship corrections (`574f3ab` revert homegrown F0→notes; `5ecf760` --stages-only/--from-stage force fix) are documented in `09a9b02 docs: reflect post-ship corrections honestly`. **Plan body retained as historical narrative.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the analyze pipeline with task-specialist models (BS-RoFormer vocals routing, htdemucs_ft for drums/bass/other, ByteDance HR-Piano, F0→notes vocals, ADTOF drums) and add per-stage params sidecars + selective re-run so future tuning is fast.

**Architecture:** A `stems_routing.json` contract decouples the stems orchestrator from downstream stages — every downstream reads the routing file instead of hard-coding glob patterns against `stems_6s/`. A generalized sidecar primitive (extending `stems`'s existing pattern) lets every stage cache-invalidate on param drift. An explicit `STAGE_DEPS` graph drives `--stages-only` and `--from-stage` selective re-run. Two new transcribers replace basic-pitch on the stems where it underperforms (vocals via F0→notes, piano via ByteDance HR-Piano), and ADTOF replaces librosa-onset on the drums.

**Tech Stack:** Python 3.11 (WSL `.venv`, Torch 2.7), FastAPI + vanilla-JS webui, audio-separator CLI for stems, `piano_transcription_inference` (PyPI), `adtof` (PyPI), existing `madmom` / `beat-this` / `lv-chordia` / `skey` / FCPE / PESTO retained.

**Spec:** [`docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](../specs/2026-05-03-phase-ab-pipeline-upgrade-design.md)

**Roadmap:** [`prompts/next/README.md`](../../../prompts/next/README.md)

---

## How to read this plan

This plan is structured as **13 work items (WIs) across 3 waves**, matching Section 10 of the spec. Each WI is independently executable and ends in a commit. WIs in the same wave have no shared files or sequential dependencies — they're parallel-safe under `superpowers:dispatching-parallel-agents` or via separate `claude-agent-sdk` ralph loops.

The **default execution model** is `claude-agent-sdk` ralph loops with read-only reviewer subagents (see Spec §10 for the runner pattern). Each WI has explicit **acceptance criteria** that the reviewer subagent gates on.

**WSL note:** the analyze package runs in WSL2 Ubuntu 24.04 via `.venv/` (Python 3.11, Torch 2.7). The webui runs natively on Windows via `webui/.venv/`. Test invocations differ:

- WSL analyze: `wsl -- bash -c 'cd /mnt/f/-\ Projects\ -/ClaudeCode/MusIQ-Lab && source .venv/bin/activate && pytest tests/'`
- Webui: `cd webui && uv run pytest`

Step-by-step `Run:` blocks below assume the appropriate environment for the file under test.

---

## File Structure Overview

### New files

| File | Owner WI | Purpose |
|---|---|---|
| `analyze/sidecar.py` | WI-1 | Shared sidecar read/write helpers |
| `tests/test_sidecar.py` | WI-1 | Sidecar primitive tests |
| `tests/test_stage_deps.py` | WI-1 | Meta-test asserting STAGE_DEPS is conservative |
| `tests/test_selective_rerun.py` | WI-1 | Selective re-run round-trip tests |
| `analyze/stages/transcription_vocals.py` | WI-3 | F0→notes pipeline |
| `tests/test_transcription_vocals.py` | WI-3 | Synthetic-input unit tests for the F0 segmenter |
| `analyze/stages/transcription_piano.py` | WI-7 | ByteDance HR-Piano wrapper |
| `tests/test_transcription_piano.py` | WI-7 | Smoke + integration test |
| `analyze/stages/transcription_basic.py` | WI-9 | Extracted basic-pitch single-stem helper |
| `tests/test_transcription_router.py` | WI-9 | Router dispatch tests |
| `scripts/install-htdemucs-ft.sh` | WI-4 | Pre-warm `htdemucs_ft` weights |
| `scripts/install-bytedance-piano.sh` | WI-4 | Fetch ByteDance HR-Piano weights |
| `scripts/install-adtof.sh` | WI-4 | Pip install + smoke test |
| `scripts/benchmark-pipeline.sh` | WI-2 | A/B harness across the corpus |
| `tests/corpus/labels/<slug>.json` | WI-2 | Hand-labeled ground truth (10 tracks) |
| `install-logs/phase-a-validation.md` | WI-12 | Measured improvements vs baseline |

### Modified files

| File | Owner WI | Change |
|---|---|---|
| `analyze/pipeline.py` | WI-1 | `STAGE_DEPS`, `downstream_of()`, selective-run logic, param threading |
| `analyze/__main__.py` | WI-1 | New `--stages-only`, `--from-stage`, `--params-json` flags |
| `analyze/stages/stems.py` | WI-6 | Multi-model orchestrator; emits `stems_routing.json` |
| `analyze/stages/transcription.py` | WI-9 | Becomes a thin router |
| `analyze/stages/drums.py` | WI-8 | ADTOF integrated; LarsNet WAV emission preserved |
| `analyze/stages/beats.py` | WI-1 | Sidecar adoption |
| `analyze/stages/key.py` | WI-1 | Sidecar adoption |
| `analyze/stages/chords.py` | WI-1 | Sidecar adoption |
| `analyze/stages/vocal_f0.py` | WI-1 + WI-5 | Sidecar; reads `stems_routing.json` for vocals path |
| `analyze/stages/beats_xcheck.py` | WI-1 | Sidecar adoption |
| `analyze/summary_writer.py` | WI-10 | Provenance block extended with per-stage params |
| `webui/webui/analyze_runner.py` | WI-11 | Selective `_clear_cache_dir`; param forwarding |
| `webui/webui/server.py` | WI-11 | Endpoints accept `stages` + `params` payloads |
| `requirements.lock` | WI-4 | New deps |
| `analyze/README.md` | WI-13 | New CLI flags + per-stage param model |
| `docs/history.md` | WI-13 | Chronicle entry |

---

## Wave 1 — Foundation (parallel-safe)

WI-1 through WI-5 share no files. Run them in parallel ralph loops or sequentially.

---

### WI-1: Sidecar primitive + STAGE_DEPS + selective-re-run plumbing

**Files:**
- Create: `analyze/sidecar.py`
- Create: `tests/test_sidecar.py`
- Create: `tests/test_stage_deps.py`
- Create: `tests/test_selective_rerun.py`
- Modify: `analyze/pipeline.py` (add `STAGE_DEPS`, `downstream_of()`, plumb `stages_only` / `from_stage` / `params` kwargs into `analyze()`)
- Modify: `analyze/__main__.py` (new CLI flags)
- Modify: `analyze/stages/{beats,key,chords,vocal_f0,beats_xcheck}.py` (sidecar adoption — minimal: write empty `{}` params with schema_version=1 to establish the pattern; `cached()` accepts `**params` even if currently ignored)

**Note:** `stems.py` already has a sidecar — leave it alone here; WI-6 refactors it.
`drums.py` already has a schema-versioned summary — leave it alone here; WI-8 refactors it.

- [ ] **Step 1.1: Write sidecar primitive tests**

```python
# tests/test_sidecar.py
from pathlib import Path
import json
from analyze import sidecar


def test_write_creates_sidecar(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert (tmp_path / ".params_beats.json").exists()
    data = json.loads((tmp_path / ".params_beats.json").read_text())
    assert data == {"schema_version": 1, "params": {"fps": 100}}


def test_matches_returns_true_for_identical_params(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert sidecar.matches(tmp_path, "beats", {"fps": 100}, expected_schema_version=1) is True


def test_matches_returns_false_when_params_differ(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert sidecar.matches(tmp_path, "beats", {"fps": 50}, expected_schema_version=1) is False


def test_matches_returns_false_when_schema_version_differs(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert sidecar.matches(tmp_path, "beats", {"fps": 100}, expected_schema_version=2) is False


def test_matches_returns_false_when_sidecar_absent(tmp_path: Path):
    assert sidecar.matches(tmp_path, "beats", {}, expected_schema_version=1) is False


def test_stems_uses_subdir_path(tmp_path: Path):
    """stems lives at cache/stems_6s/.params.json (existing convention)."""
    (tmp_path / "stems_6s").mkdir()
    sidecar.write(tmp_path, "stems", {"quality": "best"}, schema_version=1)
    assert (tmp_path / "stems_6s" / ".params.json").exists()


def test_matches_with_corrupt_json_returns_false(tmp_path: Path):
    (tmp_path / ".params_beats.json").write_text("{ bad json")
    assert sidecar.matches(tmp_path, "beats", {}, expected_schema_version=1) is False


def test_key_order_insensitive(tmp_path: Path):
    """Param dicts compared as dicts, not as JSON strings."""
    sidecar.write(tmp_path, "x", {"a": 1, "b": 2}, schema_version=1)
    assert sidecar.matches(tmp_path, "x", {"b": 2, "a": 1}, expected_schema_version=1) is True
```

- [ ] **Step 1.2: Run tests, verify they fail**

Run (WSL): `pytest tests/test_sidecar.py -v`
Expected: FAIL — `analyze.sidecar` does not exist.

- [ ] **Step 1.3: Implement the sidecar primitive**

```python
# analyze/sidecar.py
"""Per-stage parameter sidecar — generalizes the pattern stems already uses.

Every stage that takes parameters writes its resolved params to a sidecar
on the cache after a successful run, and checks the sidecar inside cached().
A sidecar mismatch (different params, different schema_version, or absent)
means cached() returns False and the stage re-runs.

Schema version is per-stage. Bump in the stage module when:
  - Param defaults change in code
  - Param semantics change (a previously-unused field becomes consumed)
  - The sidecar format itself changes
"""
from __future__ import annotations

import json
from pathlib import Path

# Stages whose sidecar lives inside their own subdir (matching the existing
# stems convention at stems_6s/.params.json). All others use a top-level
# .params_<stage>.json next to the cache root, which is guaranteed unique.
_STAGE_TO_SUBDIR: dict[str, str] = {
    "stems": "stems_6s",
}


def _sidecar_path(cache_dir: Path, stage: str) -> Path:
    sub = _STAGE_TO_SUBDIR.get(stage)
    if sub:
        return cache_dir / sub / ".params.json"
    return cache_dir / f".params_{stage}.json"


def write(cache_dir: Path, stage: str, params: dict, *, schema_version: int) -> None:
    """Write the sidecar for `stage` after a successful run."""
    path = _sidecar_path(cache_dir, stage)
    path.parent.mkdir(exist_ok=True, parents=True)
    payload = {"schema_version": schema_version, "params": params}
    # sort_keys for stable on-disk diffs; doesn't affect equality semantics.
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def matches(
    cache_dir: Path,
    stage: str,
    expected_params: dict,
    *,
    expected_schema_version: int,
) -> bool:
    """True iff sidecar exists, schema_version matches, and params are equal."""
    path = _sidecar_path(cache_dir, stage)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if data.get("schema_version") != expected_schema_version:
        return False
    return data.get("params") == expected_params
```

- [ ] **Step 1.4: Run tests, verify they pass**

Run (WSL): `pytest tests/test_sidecar.py -v`
Expected: PASS — all 8 tests green.

- [ ] **Step 1.5: Write STAGE_DEPS meta-test**

```python
# tests/test_stage_deps.py
"""Asserts STAGE_DEPS is a conservative superset of actual cross-stage filesystem reads.

For each stage, scan the source for known cross-stage artifacts (e.g.
stems_routing.json, vocal_f0.npz) and ensure the deps declaration covers
the producing stage. Prevents "I added a read, forgot to update deps"
silent staleness."""
from __future__ import annotations

from pathlib import Path
import re

from analyze.pipeline import STAGE_DEPS, downstream_of

# Each artifact known to be produced by a specific stage. Keep this tight —
# false positives here surface as test failures, false negatives as bugs.
ARTIFACT_TO_STAGE = {
    "stems_routing.json":  "stems",
    "stems_6s":            "stems",
    "stems_bsroformer":    "stems",
    "stems_htdemucs_ft":   "stems",
    "vocal_f0.npz":        "vocal_f0",
    "vocal_f0_summary.json": "vocal_f0",
    "madmom_downbeats.json": "beats",
    "beat_this.json":       "beats_xcheck",
    "skey.json":            "key",
    "chords.json":          "chords",
    "transcription_summary.json": "transcription",
    "drums_summary.json":   "drums",
}

STAGES_DIR = Path(__file__).resolve().parents[1] / "analyze" / "stages"


def _scan_reads(stage_file: Path) -> set[str]:
    """Return artifact names the stage's source string-mentions."""
    src = stage_file.read_text()
    found: set[str] = set()
    for artifact in ARTIFACT_TO_STAGE:
        if artifact in src:
            found.add(artifact)
    return found


def test_stage_deps_is_conservative_superset():
    failures: list[str] = []
    for stage, deps in STAGE_DEPS.items():
        stage_file = STAGES_DIR / f"{stage}.py"
        if not stage_file.exists():
            continue  # transcription_piano etc. live alongside, not core
        reads = _scan_reads(stage_file)
        for artifact in reads:
            producer = ARTIFACT_TO_STAGE[artifact]
            if producer == stage:
                continue  # self-read (own output)
            if producer not in deps:
                failures.append(
                    f"{stage} reads {artifact!r} (produced by {producer}) but "
                    f"STAGE_DEPS[{stage!r}] = {deps} does not include {producer!r}"
                )
    assert not failures, "\n".join(failures)


def test_downstream_of_stems_includes_known_consumers():
    ds = downstream_of("stems")
    assert "transcription" in ds
    assert "vocal_f0" in ds
    assert "drums" in ds


def test_downstream_of_leaf_stage_is_empty():
    """A stage no other stage depends on returns empty downstream."""
    # transcription is downstream of stems; nothing should be downstream
    # of transcription per the v1 graph (its consumers are derivation, not stages).
    assert downstream_of("transcription") == set()
```

- [ ] **Step 1.6: Run STAGE_DEPS test, verify it fails**

Run (WSL): `pytest tests/test_stage_deps.py -v`
Expected: FAIL — `STAGE_DEPS` and `downstream_of` not yet defined in `analyze.pipeline`.

- [ ] **Step 1.7: Add STAGE_DEPS + downstream_of + selective-run plumbing to pipeline.py**

Read the current `analyze/pipeline.py` to see the existing `analyze()` function (around line 251). Add at module level after the existing imports / constants:

```python
# analyze/pipeline.py — additions

STAGE_DEPS: dict[str, frozenset[str]] = {
    "stems":         frozenset(),
    "beats":         frozenset(),
    "key":           frozenset(),
    "chords":        frozenset(),
    "transcription": frozenset({"stems"}),
    "beats_xcheck":  frozenset(),
    "vocal_f0":      frozenset({"stems"}),
    "drums":         frozenset({"stems"}),
}


def downstream_of(stage: str) -> set[str]:
    """Return the transitive closure of stages that depend on `stage`."""
    out: set[str] = set()
    frontier = [stage]
    while frontier:
        s = frontier.pop()
        for candidate, deps in STAGE_DEPS.items():
            if s in deps and candidate not in out:
                out.add(candidate)
                frontier.append(candidate)
    return out
```

Then extend `analyze()`'s signature:

```python
def analyze(
    mp3_path: Path,
    *,
    force: bool = False,
    quiet: bool = False,
    slug: Optional[str] = None,
    stems_quality: str = stems.DEFAULT_STEMS_QUALITY,
    stages_only: Optional[set[str]] = None,
    from_stage: Optional[str] = None,
    params: Optional[dict[str, dict]] = None,
) -> AnalyzeResult:
    ...
```

Resolution logic at the top of the function (after the existing path validation):

```python
    # Determine which stages will actually run this invocation.
    # `force=True` overrides everything (full reanalyze).
    # Otherwise, stages_only / from_stage narrow the run; their absence preserves
    # current all-or-nothing behavior driven by per-stage cached() checks.
    if force:
        run_set: set[str] | None = None  # None = run everything
    elif from_stage is not None:
        if from_stage not in STAGE_DEPS:
            raise ValueError(f"unknown from_stage {from_stage!r}; expected one of {sorted(STAGE_DEPS)}")
        run_set = {from_stage} | downstream_of(from_stage)
    elif stages_only is not None:
        unknown = stages_only - set(STAGE_DEPS)
        if unknown:
            raise ValueError(f"unknown stages_only {sorted(unknown)}; expected one of {sorted(STAGE_DEPS)}")
        run_set = set(stages_only)
    else:
        run_set = None  # cached() decides per-stage
```

Inside the existing `for name, module in REQUIRED_STAGES + OPTIONAL_STAGES:` loop, gate the cache check + run:

```python
    for name, module in REQUIRED_STAGES + OPTIONAL_STAGES:
        is_required = (name, module) in REQUIRED_STAGES
        extra = stage_kwargs.get(name, {})
        # Per-stage param overrides from the caller take precedence over stage_kwargs.
        if params and name in params:
            extra = {**extra, **params[name]}
        # Selective run: skip the stage entirely if it's not in run_set.
        # The stage's previous cache must already be populated for downstream
        # to work; we don't re-validate here (cached()/load() does that).
        if run_set is not None and name not in run_set:
            if module.cached(cache_dir, **extra):
                _log(f"==> Stage {name}: cached (skipped by selective-run)", quiet=quiet)
                results[name] = module.load(cache_dir)
                continue
            raise PipelineError(
                f"selective run requested but stage {name!r} has no valid cache; "
                f"run without --stages-only / --from-stage first to populate it"
            )
        if module.cached(cache_dir, **extra):
            _log(f"==> Stage {name}: cached", quiet=quiet)
            results[name] = module.load(cache_dir)
            continue
        # ... rest of loop unchanged
```

- [ ] **Step 1.8: Add CLI flags to __main__.py**

Read `analyze/__main__.py` first to see current argparse setup, then add:

```python
    parser.add_argument(
        "--stages-only",
        type=lambda s: set(s.split(",")),
        default=None,
        help="comma-separated stages to run; requires upstream cache present",
    )
    parser.add_argument(
        "--from-stage",
        default=None,
        help="run this stage and everything downstream of it",
    )
    parser.add_argument(
        "--params-json",
        type=Path,
        default=None,
        help="path to JSON file with per-stage param overrides",
    )
```

And in the call site:

```python
    params = None
    if args.params_json:
        params = json.loads(args.params_json.read_text())

    result = analyze(
        args.mp3_path,
        force=args.force,
        quiet=args.quiet,
        stems_quality=args.stems_quality,
        stages_only=args.stages_only,
        from_stage=args.from_stage,
        params=params,
    )
```

- [ ] **Step 1.9: Adopt sidecar in beats.py / key.py / chords.py / vocal_f0.py / beats_xcheck.py**

For each stage, the change is mechanical. Pattern (using `beats.py` as exemplar):

```python
# analyze/stages/beats.py — additions

from analyze import sidecar

SCHEMA_VERSION = 1
DEFAULT_PARAMS: dict = {}  # beats has no tunable params today


def cached(cache_dir: Path, **params) -> bool:
    p = {**DEFAULT_PARAMS, **params}
    if not (cache_dir / CANONICAL).exists():
        return False
    return sidecar.matches(cache_dir, "beats", p, expected_schema_version=SCHEMA_VERSION)


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}
    # ... existing body ...
    sidecar.write(cache_dir, "beats", p, schema_version=SCHEMA_VERSION)
    return out
```

Apply the same shape to `key.py`, `chords.py`, `vocal_f0.py`, `beats_xcheck.py`. **Do not** modify `stems.py` or `drums.py` here — they have their own sidecars and will be touched in WI-6 / WI-8.

- [ ] **Step 1.10: Run STAGE_DEPS test, verify it passes**

Run (WSL): `pytest tests/test_stage_deps.py -v`
Expected: PASS — STAGE_DEPS covers all known cross-stage reads.

- [ ] **Step 1.11: Write selective re-run round-trip test**

```python
# tests/test_selective_rerun.py
"""Selective-run round-trip: cache a track, change one stage's params,
re-run with --stages-only, assert only that stage's outputs changed."""
from __future__ import annotations
from pathlib import Path
import json
import pytest

from analyze import pipeline

# Use the existing Gorillaz fixture (cached in CI).
FIXTURE_MP3 = Path(__file__).resolve().parent / "fixtures" / "gorillaz_silent_running.mp3"

pytestmark = pytest.mark.skipif(
    not FIXTURE_MP3.exists(),
    reason="requires fixtures/gorillaz_silent_running.mp3 (run scripts/fetch-test-fixtures.sh)",
)


def test_unknown_stage_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown"):
        pipeline.analyze(FIXTURE_MP3, slug="test", stages_only={"nonsense"})


def test_stages_only_without_cache_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Asking for selective re-run without an upstream cache should fail loudly."""
    # Point cache root at empty tmp_path
    monkeypatch.setenv("MUSIQ_CACHE_DIR", str(tmp_path))
    with pytest.raises(pipeline.PipelineError, match="no valid cache"):
        pipeline.analyze(FIXTURE_MP3, stages_only={"transcription"})


def test_downstream_of_stems_invalidation(monkeypatch: pytest.MonkeyPatch):
    """Sanity: downstream_of('stems') matches expected leaf set."""
    from analyze.pipeline import downstream_of
    ds = downstream_of("stems")
    assert ds == {"transcription", "vocal_f0", "drums"}
```

This test is intentionally light — full round-trip on a real cache is in WI-12's benchmark.

- [ ] **Step 1.12: Run selective re-run test, verify it passes**

Run (WSL): `pytest tests/test_selective_rerun.py -v`
Expected: PASS (some tests skipped if fixture missing — that's allowed for now; full coverage in WI-12).

- [ ] **Step 1.13: Run full test suite to check no regressions**

Run (WSL): `pytest tests/ -v`
Expected: PASS — existing tests + new sidecar/STAGE_DEPS tests.

- [ ] **Step 1.14: Commit**

```bash
git add analyze/sidecar.py analyze/pipeline.py analyze/__main__.py \
  analyze/stages/beats.py analyze/stages/key.py analyze/stages/chords.py \
  analyze/stages/vocal_f0.py analyze/stages/beats_xcheck.py \
  tests/test_sidecar.py tests/test_stage_deps.py tests/test_selective_rerun.py
git commit -m "feat(analyze): per-stage params sidecar + STAGE_DEPS + selective re-run (WI-1)"
```

**Acceptance criteria for reviewer:**

- All tests in `test_sidecar.py`, `test_stage_deps.py`, `test_selective_rerun.py` pass.
- `analyze/sidecar.py` exists and exposes `write()` + `matches()` with the signatures in Step 1.3.
- `analyze.pipeline.STAGE_DEPS` and `downstream_of()` exist with the contents in Step 1.7.
- `analyze.analyze()` accepts `stages_only`, `from_stage`, `params` kwargs and validates them.
- `python -m analyze --help` lists `--stages-only`, `--from-stage`, `--params-json`.
- Every stage in `{beats, key, chords, vocal_f0, beats_xcheck}` writes its sidecar in `run()` and checks it in `cached()`. `stems.py` and `drums.py` are unchanged.
- No `# TODO` / `# FIXME` left.

---

### WI-2: Validation harness + corpus labels + benchmark script

**Files:**
- Create: `scripts/benchmark-pipeline.sh`
- Create: `scripts/fetch-test-fixtures.sh` (idempotent; YouTube-fetches the corpus mp3s using the project's standard yt-dlp invocation from `CLAUDE.md`)
- Create: `tests/corpus/labels/<slug>.json` × 10 (hand-labeled ground truth)
- Create: `tests/corpus/README.md` (documents the corpus)
- Create: `scripts/lib/benchmark_compare.py` (used by the harness; computes deltas)

**Corpus** (per Spec §5):

| # | Track | Slug | Type tested |
|---|---|---|---|
| 1 | JVKE — Golden Hour | `jvke-golden-hour-...` | Lush sustained piano (the explicit failure case) |
| 2 | Olivia Dean — quiet acoustic | TBD-pick-one | Sustained vocals, low-energy drums |
| 3 | Gorillaz — Silent Running ft. Adeleye Omotayo | `gorillaz_silent_running` | Multi-instrument pop (existing baseline) |
| 4 | Bach — orchestral cello quintet | TBD-pick-one | Instrumental; tests drum gate |
| 5 | Radiohead — Creep | TBD-pick-one | Existing corpus; mp3 header malformation |
| 6 | A waltz / 6/8 track | TBD-pick-one | Time signature ≠ 4/4 |
| 7 | A modulating track (key change in bridge) | TBD-pick-one | Phase C precursor |
| 8 | A heavy-reverb production track | TBD-pick-one | Stems robustness |
| 9 | A lo-fi / hiss-y track | TBD-pick-one | Onset detection robustness |
| 10 | A rapper / sustained-vocals contrast | TBD-pick-one | Vocal F0 algorithm coverage |

**Note for executing agent:** if the existing `cache/gorillaz_silent_running/` artifacts are present, slug #3 already exists and just needs a label file. For the others, pick canonical YouTube URLs and put them in `tests/corpus/sources.txt` (one URL per line, in slug order) before running the fetch script.

- [ ] **Step 2.1: Write the benchmark-compare helper**

```python
# scripts/lib/benchmark_compare.py
"""Compare summary.json output across two pipeline runs and emit a Markdown delta table.

Usage:
    python -m scripts.lib.benchmark_compare baseline-summaries/ candidate-summaries/ \
        --labels tests/corpus/labels/ --out install-logs/phase-a-validation.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REGRESSION_KEYS = ("key", "tempo_bpm", "chord_count", "downbeat_count")


def _load_summary(path: Path) -> dict:
    return json.loads(path.read_text())


def _label_for(slug: str, labels_dir: Path) -> dict:
    p = labels_dir / f"{slug}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def compare(baseline_dir: Path, candidate_dir: Path, labels_dir: Path) -> str:
    rows = []
    for cand_path in sorted(candidate_dir.glob("*.summary.json")):
        slug = cand_path.stem.removesuffix(".summary")
        base_path = baseline_dir / cand_path.name
        if not base_path.exists():
            continue
        base = _load_summary(base_path)
        cand = _load_summary(cand_path)
        labels = _label_for(slug, labels_dir)
        rows.append({
            "slug": slug,
            "base_key": base.get("track", {}).get("key"),
            "cand_key": cand.get("track", {}).get("key"),
            "label_key": labels.get("key"),
            "base_bpm": base.get("track", {}).get("tempo_bpm"),
            "cand_bpm": cand.get("track", {}).get("tempo_bpm"),
            "label_bpm": labels.get("bpm"),
            "base_piano_notes": _piano_notes(base),
            "cand_piano_notes": _piano_notes(cand),
            "base_vocal_notes": _vocal_notes(base),
            "cand_vocal_notes": _vocal_notes(cand),
        })
    return _render(rows)


def _piano_notes(summary: dict) -> int | None:
    stems = summary.get("stems") or {}
    p = stems.get("piano") or {}
    notes = p.get("notes")
    return len(notes) if isinstance(notes, list) else None


def _vocal_notes(summary: dict) -> int | None:
    stems = summary.get("stems") or {}
    v = stems.get("vocals") or {}
    notes = v.get("notes")
    return len(notes) if isinstance(notes, list) else None


def _render(rows: list[dict]) -> str:
    lines = [
        "# Phase A validation",
        "",
        "| Track | Key (base→cand, label) | BPM (base→cand, label) | Piano notes (base→cand) | Vocal notes (base→cand) |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['slug']} | "
            f"{r['base_key']}→{r['cand_key']} ({r['label_key']}) | "
            f"{r['base_bpm']}→{r['cand_bpm']} ({r['label_bpm']}) | "
            f"{r['base_piano_notes']}→{r['cand_piano_notes']} | "
            f"{r['base_vocal_notes']}→{r['cand_vocal_notes']} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    md = compare(args.baseline, args.candidate, args.labels)
    args.out.write_text(md)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2.2: Write the benchmark shell harness**

```bash
# scripts/benchmark-pipeline.sh
#!/usr/bin/env bash
# Phase A benchmark harness.
#
# Stages:
#   1. Verify all corpus mp3s are present (fetch via yt-dlp if missing).
#   2. Snapshot current summary.jsons as baseline (only if absent).
#   3. Run candidate pipeline (flag passed in $1 — "baseline" or "phaseA").
#   4. Snapshot candidate summary.jsons.
#   5. Render Markdown delta to install-logs/phase-a-validation.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORPUS_DIR="$ROOT/tests/corpus"
SOURCES="$CORPUS_DIR/sources.txt"
LABELS_DIR="$CORPUS_DIR/labels"
BASELINE_DIR="$CORPUS_DIR/snapshots/baseline"
CANDIDATE_DIR="$CORPUS_DIR/snapshots/$1"
CACHE_ROOT="$ROOT/cache"

mkdir -p "$BASELINE_DIR" "$CANDIDATE_DIR"

# 1. Fetch corpus mp3s
bash "$ROOT/scripts/fetch-test-fixtures.sh"

# 2. Run pipeline on each track (in WSL — assumes user invokes this from WSL)
while IFS= read -r url; do
    [ -z "$url" ] && continue
    [[ "$url" =~ ^# ]] && continue
    # Resolve the on-disk mp3 by yt-dlp ID glob (per the project memory note
    # about console encoding mangling fullwidth chars).
    yt_id="$(echo "$url" | sed -E 's@.*[?&]v=([A-Za-z0-9_-]{11}).*@\1@; s@.*youtu\.be/([A-Za-z0-9_-]{11}).*@\1@')"
    mp3="$(ls "$ROOT/tests/mp3/"*-"$yt_id".mp3 2>/dev/null | head -n1)"
    [ -z "$mp3" ] && { echo "missing mp3 for $url" >&2; exit 1; }
    cd "$ROOT" && source .venv/bin/activate
    python -u -m analyze "$mp3" --quiet
done < "$SOURCES"

# 3. Snapshot summary.jsons
for f in "$CACHE_ROOT"/*/*.summary.json; do
    cp "$f" "$CANDIDATE_DIR/"
done
# Establish baseline on first run only
if [ -z "$(ls -A "$BASELINE_DIR" 2>/dev/null)" ] && [ "$1" = "baseline" ]; then
    cp -r "$CANDIDATE_DIR/." "$BASELINE_DIR/"
fi

# 4. Render delta
python -m scripts.lib.benchmark_compare \
    "$BASELINE_DIR" "$CANDIDATE_DIR" \
    --labels "$LABELS_DIR" \
    --out "$ROOT/install-logs/phase-a-validation.md"

echo "wrote install-logs/phase-a-validation.md"
```

- [ ] **Step 2.3: Write the corpus fetch script**

```bash
# scripts/fetch-test-fixtures.sh
#!/usr/bin/env bash
# Fetch all corpus mp3s listed in tests/corpus/sources.txt to tests/mp3/.
# Uses the project's standard yt-dlp invocation from CLAUDE.md.
# Idempotent: skips tracks already on disk (matched by the 11-char YT id).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCES="$ROOT/tests/corpus/sources.txt"
OUT_DIR="$ROOT/tests/mp3"
YT_DLP='C:/$WinSoft/$tools/yt-dlp/yt-dlp.exe'

mkdir -p "$OUT_DIR"

while IFS= read -r url; do
    [ -z "$url" ] && continue
    [[ "$url" =~ ^# ]] && continue
    yt_id="$(echo "$url" | sed -E 's@.*[?&]v=([A-Za-z0-9_-]{11}).*@\1@; s@.*youtu\.be/([A-Za-z0-9_-]{11}).*@\1@')"
    if ls "$OUT_DIR"/*-"$yt_id".mp3 >/dev/null 2>&1; then
        echo "[skip] already have $yt_id"
        continue
    fi
    echo "[fetch] $url"
    "$YT_DLP" \
        -x --audio-format mp3 --audio-quality 0 \
        --no-update \
        -o "$OUT_DIR/%(title)s-%(id)s.%(ext)s" \
        "$url"
done < "$SOURCES"
```

- [ ] **Step 2.4: Create empty corpus structure + sources placeholder**

Create `tests/corpus/sources.txt` with comments explaining slot order:

```
# Per docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md §5,
# 10 tracks in this order. One YouTube URL per line, blank lines and # ignored.
# Slot 1: JVKE — Golden Hour (lush sustained piano)
# Slot 2: Olivia Dean — quiet acoustic (sustained vocals)
# Slot 3: Gorillaz — Silent Running (multi-instrument pop)
# Slot 4: Bach — orchestral (instrumental, tests drum gate)
# Slot 5: Radiohead — Creep (mp3 header malformation case)
# Slot 6: a waltz / 6/8 (TS != 4/4)
# Slot 7: a modulating track (key change in bridge)
# Slot 8: heavy-reverb production
# Slot 9: lo-fi / hiss-y
# Slot 10: rapper / sustained-vocals contrast
```

The user populates this file before running the benchmark — this is documented in `tests/corpus/README.md`.

Create `tests/corpus/README.md`:

```markdown
# Corpus

10 tracks for Phase A validation, per [`docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](../specs/2026-05-03-phase-ab-pipeline-upgrade-design.md) §5.

## Setup

1. Fill in `sources.txt` with one YouTube URL per slot (see comments inside).
2. Hand-label each track: copy `labels/_template.json` to `labels/<slug>.json` and fill in.
3. Run `bash scripts/fetch-test-fixtures.sh` (downloads mp3s to `tests/mp3/`).
4. Run `bash scripts/benchmark-pipeline.sh baseline` to snapshot baseline.
5. After Phase A changes, run `bash scripts/benchmark-pipeline.sh phaseA`.
6. Read `install-logs/phase-a-validation.md` for the delta.
```

- [ ] **Step 2.5: Create the label template**

```json
# tests/corpus/labels/_template.json
{
  "key": "C:major",
  "bpm": 120.0,
  "time_signature": "4/4",
  "downbeat_count": 96,
  "vocal_pitch_range": ["G3", "C5"],
  "piano_present": true,
  "drums_present": true,
  "expected_chord_root_count": 4,
  "notes_minimum_piano": 200,
  "notes_minimum_vocals": 80
}
```

- [ ] **Step 2.6: Smoke-test the harness on the existing fixture**

The Gorillaz fixture is already cached. With an empty `sources.txt` (or just the Gorillaz URL), the harness should:
- Skip fetch (file present).
- Run analyze (cache hit on every stage — fast).
- Snapshot the summary.
- Produce a one-row Markdown table in `install-logs/phase-a-validation.md`.

Run (WSL): `bash scripts/benchmark-pipeline.sh baseline`
Expected: completes without error; output file exists with 1 row.

- [ ] **Step 2.7: Commit**

```bash
git add scripts/benchmark-pipeline.sh scripts/fetch-test-fixtures.sh \
  scripts/lib/benchmark_compare.py \
  tests/corpus/sources.txt tests/corpus/README.md tests/corpus/labels/_template.json
git commit -m "feat(tests): Phase A validation harness + corpus scaffolding (WI-2)"
```

**Acceptance criteria for reviewer:**

- `scripts/benchmark-pipeline.sh baseline` runs end-to-end on the existing Gorillaz cache without error.
- `install-logs/phase-a-validation.md` is generated.
- `tests/corpus/{sources.txt,README.md,labels/_template.json}` exist.
- Fetch script is idempotent (re-running doesn't re-download tracks already present).

**Out-of-scope reminder for reviewer:** populating `sources.txt` and label files for the 9 non-Gorillaz tracks is **the user's responsibility**, not the WI's. The reviewer must NOT block on this.

---

### WI-3: F0 → notes algorithm

**Files:**
- Create: `analyze/stages/transcription_vocals.py`
- Create: `tests/test_transcription_vocals.py`

**Algorithm summary** (per Spec §3): voicing gate → median filter → vibrato suppression for snapping → note segmentation → confidence + velocity per note. Reads `cache/<slug>/vocal_f0.npz` (already produced by `vocal_f0` stage). Writes MIDI to `cache/<slug>/midi/vocals.mid`.

- [ ] **Step 3.1: Write unit tests with synthetic input**

```python
# tests/test_transcription_vocals.py
"""Unit tests for the F0→notes algorithm.

Tests use synthetic FCPE/PESTO arrays — no audio files, no GPU. The point
is to verify the algorithm's behavior on canonical patterns:
  - Pure tone → one note, expected pitch
  - Vibrato → one note, mean pitch (not multiple notes from modulation)
  - Step (C4 → D4 mid-segment) → two notes
  - Silence with onset → note starts at onset, not before
  - Whisper / breathy passage (low confidence) → no notes (gated out)
"""
from __future__ import annotations

import numpy as np
import pytest

from analyze.stages.transcription_vocals import f0_to_notes, NoteEvent

# 16 kHz frame rate; PESTO step_size=10ms → 100 frames/sec
FPS = 100


def _hz_to_midi(hz: float) -> float:
    return 69.0 + 12.0 * np.log2(hz / 440.0)


def _midi_to_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def test_pure_tone_one_note():
    """1 sec of A4 (440 Hz), high confidence → one note at MIDI 69."""
    n = FPS * 1
    fcpe = np.full(n, 440.0)
    pesto = np.full(n, 440.0)
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert len(notes) == 1
    assert notes[0].pitch == 69
    assert abs(notes[0].duration - 1.0) < 0.05


def test_vibrato_one_note_at_mean():
    """1 sec of A4 ± 50¢ at 5 Hz → one note at MIDI 69, not multiple."""
    n = FPS * 1
    t = np.arange(n) / FPS
    cents = 50.0 * np.sin(2 * np.pi * 5 * t)
    fcpe = 440.0 * (2.0 ** (cents / 1200.0))
    pesto = fcpe.copy()  # perfect agreement
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert len(notes) == 1
    assert notes[0].pitch == 69


def test_step_two_notes():
    """0.5s C4 then 0.5s D4 → two notes."""
    half = FPS // 2
    fcpe = np.concatenate([
        np.full(half, _midi_to_hz(60)),  # C4
        np.full(half, _midi_to_hz(62)),  # D4
    ])
    pesto = fcpe.copy()
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert len(notes) == 2
    assert notes[0].pitch == 60
    assert notes[1].pitch == 62


def test_silence_then_note():
    """0.5s silence (zeros) → 0.5s C4 → one note starting at 0.5s."""
    half = FPS // 2
    fcpe = np.concatenate([
        np.zeros(half),
        np.full(half, _midi_to_hz(60)),
    ])
    pesto = fcpe.copy()
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert len(notes) == 1
    assert abs(notes[0].onset - 0.5) < 0.02
    assert notes[0].pitch == 60


def test_disagreement_gated():
    """FCPE says A4, PESTO says E4 (>50¢ apart) → no notes (low confidence)."""
    n = FPS * 1
    fcpe = np.full(n, _midi_to_hz(69))
    pesto = np.full(n, _midi_to_hz(64))  # 5 semitones apart
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert len(notes) == 0


def test_short_blip_gated():
    """A 50ms note (below default min_note_ms=80) is rejected."""
    blip = FPS // 20  # 50 ms
    pre = np.zeros(FPS)
    fcpe = np.concatenate([pre, np.full(blip, _midi_to_hz(60)), pre])
    pesto = fcpe.copy()
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert len(notes) == 0


def test_confidence_in_output():
    """Each note carries a confidence in [0, 1]."""
    n = FPS * 1
    fcpe = np.full(n, 440.0)
    pesto = np.full(n, 440.0)
    notes = f0_to_notes(fcpe, pesto, fps=FPS)
    assert 0.0 <= notes[0].confidence <= 1.0
```

- [ ] **Step 3.2: Run tests, verify they fail**

Run (WSL): `pytest tests/test_transcription_vocals.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3.3: Implement transcription_vocals.py**

```python
# analyze/stages/transcription_vocals.py
"""Stage 5b: vocal MIDI from FCPE+PESTO consensus.

Replaces basic-pitch on the vocals stem. basic-pitch was never built for
sustained vibrato-heavy singing; the F0 curves the pipeline already
produces in `vocal_f0` are a much cleaner signal source. This module
turns them into MIDI notes.

Algorithm (per design spec §3):
  1. Voicing gate — frame is voiced iff FCPE > 0 AND PESTO > 0 AND
     |FCPE - PESTO| in cents < agreement_cents.
  2. Median-filter the long-window F0 (window = ~50 ms) to suppress
     single-frame jitter.
  3. Vibrato suppression — use a wider window (~200 ms) for semitone
     snapping so vibrato modulation around the mean stays as bend
     metadata, not extra notes.
  4. Note segmentation — emit a new note when the long-window F0 crosses
     a semitone boundary AND stays past ≥ min_note_ms, or after a
     voicing-off transition ≥ min_silence_ms.
  5. Confidence per note = mean FCPE-PESTO agreement over the note's
     frames. Velocity per note = vocal RMS in the note window, normalized
     to track-max (1.0 = loudest moment).

Outputs:
    cache_dir/midi/vocals.mid              — MIDI file
    cache_dir/transcription_vocals.json    — note events with details
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import json
import sys

import numpy as np

from analyze import sidecar

CANONICAL = "transcription_vocals.json"
SCHEMA_VERSION = 1

DEFAULT_PARAMS = {
    "voicing_threshold_hz":   1.0,    # any non-zero FCPE/PESTO frame is "voiced"
    "agreement_cents":        50.0,
    "smooth_window_ms":       50.0,
    "snap_window_ms":         200.0,
    "min_note_ms":            80.0,
    "min_silence_ms":         80.0,
}


@dataclass
class NoteEvent:
    onset: float       # seconds
    duration: float    # seconds
    pitch: int         # MIDI 0-127
    velocity: int      # MIDI 0-127
    confidence: float  # [0, 1]


def _hz_to_midi_float(hz: np.ndarray) -> np.ndarray:
    """Vectorized; zeros stay zero (treated as silence downstream)."""
    out = np.zeros_like(hz, dtype=np.float64)
    nz = hz > 0
    out[nz] = 69.0 + 12.0 * np.log2(hz[nz] / 440.0)
    return out


def _median_filter(a: np.ndarray, w: int) -> np.ndarray:
    """Trivial running-median for small windows; no scipy dep."""
    if w <= 1:
        return a
    half = w // 2
    pad = np.pad(a, half, mode="edge")
    return np.array([np.median(pad[i:i + w]) for i in range(len(a))])


def f0_to_notes(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    *,
    fps: int = 100,
    voicing_threshold_hz: float = 1.0,
    agreement_cents: float = 50.0,
    smooth_window_ms: float = 50.0,
    snap_window_ms: float = 200.0,
    min_note_ms: float = 80.0,
    min_silence_ms: float = 80.0,
    rms: Optional[np.ndarray] = None,  # optional per-frame RMS for velocity
) -> list[NoteEvent]:
    """Convert paired FCPE + PESTO F0 curves into note events."""
    n = min(len(fcpe), len(pesto))
    fcpe, pesto = fcpe[:n], pesto[:n]

    # Frame-level voicing
    voiced = (fcpe > voicing_threshold_hz) & (pesto > voicing_threshold_hz)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200.0 * np.log2(np.where(pesto > 0, fcpe / pesto, 1.0))
    agree = voiced & (np.abs(cents) < agreement_cents)

    # Frame agreement strength → confidence per frame in [0, 1]
    frame_conf = np.where(agree, 1.0 - np.minimum(np.abs(cents), agreement_cents) / agreement_cents, 0.0)

    # Smoothed pitch curve (for note segmentation), using FCPE alone where agreed
    fcpe_midi = _hz_to_midi_float(fcpe)
    snap_w = max(1, int(snap_window_ms * fps / 1000))
    snapped = _median_filter(fcpe_midi, snap_w)

    # Walk frames and emit notes
    notes: list[NoteEvent] = []
    min_note_frames = max(1, int(min_note_ms * fps / 1000))
    min_silence_frames = max(1, int(min_silence_ms * fps / 1000))

    in_note = False
    note_start_frame = 0
    note_pitch = 0
    silence_run = 0
    pitch_run = 0
    pitch_run_value = 0

    for i in range(n):
        if not agree[i]:
            silence_run += 1
            if in_note and silence_run >= min_silence_frames:
                _emit(notes, fcpe, frame_conf, rms, fps,
                      note_start_frame, i - silence_run + 1, note_pitch)
                in_note = False
                pitch_run = 0
            continue
        silence_run = 0
        cur_pitch = int(round(snapped[i]))
        if not in_note:
            in_note = True
            note_start_frame = i
            note_pitch = cur_pitch
            pitch_run_value = cur_pitch
            pitch_run = 1
            continue
        if cur_pitch == pitch_run_value:
            pitch_run += 1
            continue
        # Pitch differs from current run
        if pitch_run >= min_note_frames and cur_pitch != note_pitch:
            # Boundary: close the previous note, open a new one
            _emit(notes, fcpe, frame_conf, rms, fps,
                  note_start_frame, i, note_pitch)
            note_start_frame = i
            note_pitch = cur_pitch
        pitch_run_value = cur_pitch
        pitch_run = 1

    if in_note:
        _emit(notes, fcpe, frame_conf, rms, fps, note_start_frame, n, note_pitch)

    # Drop sub-min-duration notes
    return [nt for nt in notes if nt.duration * fps >= min_note_frames]


def _emit(
    out: list[NoteEvent],
    fcpe: np.ndarray,
    frame_conf: np.ndarray,
    rms: Optional[np.ndarray],
    fps: int,
    start_frame: int,
    end_frame: int,
    pitch: int,
):
    if end_frame <= start_frame:
        return
    onset = start_frame / fps
    duration = (end_frame - start_frame) / fps
    conf = float(frame_conf[start_frame:end_frame].mean())
    if rms is not None:
        peak = float(rms[start_frame:end_frame].max())
        track_peak = max(float(rms.max()), 1e-9)
        velocity = int(np.clip(round(peak / track_peak * 127), 1, 127))
    else:
        velocity = 80  # sensible default
    out.append(NoteEvent(onset, duration, pitch, velocity, conf))


def cached(cache_dir: Path, **params) -> bool:
    p = {**DEFAULT_PARAMS, **params}
    if not (cache_dir / CANONICAL).exists():
        return False
    if not (cache_dir / "midi" / "vocals.mid").exists():
        return False
    return sidecar.matches(cache_dir, "transcription_vocals", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    """Read FCPE+PESTO arrays from vocal_f0.npz, write midi/vocals.mid."""
    p = {**DEFAULT_PARAMS, **params}
    npz_path = cache_dir / "vocal_f0.npz"
    if not npz_path.exists():
        raise RuntimeError(f"vocal_f0 stage must run first (missing {npz_path})")
    npz = np.load(npz_path)
    fcpe, pesto = npz["fcpe"], npz["pesto"]

    # Optional: per-frame RMS from the vocals stem for velocity. Reuse the
    # vocal stem we already have (post stems_routing.json — see WI-5).
    rms = None  # WI-5 will plumb the path; for now velocity defaults to 80.

    notes = f0_to_notes(fcpe, pesto, fps=100, rms=rms,
                        voicing_threshold_hz=p["voicing_threshold_hz"],
                        agreement_cents=p["agreement_cents"],
                        smooth_window_ms=p["smooth_window_ms"],
                        snap_window_ms=p["snap_window_ms"],
                        min_note_ms=p["min_note_ms"],
                        min_silence_ms=p["min_silence_ms"])

    # Write MIDI (use pretty_midi for ergonomics — already a dep via basic-pitch)
    import pretty_midi
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=53, name="vocals")  # Choir Aahs
    for nt in notes:
        inst.notes.append(pretty_midi.Note(
            velocity=nt.velocity, pitch=nt.pitch,
            start=nt.onset, end=nt.onset + nt.duration,
        ))
    pm.instruments.append(inst)
    out_dir = cache_dir / "midi"
    out_dir.mkdir(exist_ok=True)
    pm.write(str(out_dir / "vocals.mid"))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "n_notes": len(notes),
        "notes": [
            {"onset": nt.onset, "duration": nt.duration, "pitch": nt.pitch,
             "velocity": nt.velocity, "confidence": nt.confidence}
            for nt in notes
        ],
        "midi": "midi/vocals.mid",
    }
    (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
    sidecar.write(cache_dir, "transcription_vocals", p, schema_version=SCHEMA_VERSION)
    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    print(f"vocals: {r['n_notes']} notes")
```

- [ ] **Step 3.4: Run tests, verify they pass**

Run (WSL): `pytest tests/test_transcription_vocals.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 3.5: Commit**

```bash
git add analyze/stages/transcription_vocals.py tests/test_transcription_vocals.py
git commit -m "feat(analyze): F0→notes vocal transcriber (WI-3)"
```

**Acceptance criteria for reviewer:**

- All tests in `test_transcription_vocals.py` pass.
- `f0_to_notes()` returns `list[NoteEvent]` with the expected dataclass shape.
- `cached()`, `load()`, `run()` follow the stage protocol used by other stages.
- Algorithm correctly handles: pure tone, vibrato, step, silence-then-onset, FCPE/PESTO disagreement, short blips.
- The module imports without errors at module level (Torch, numpy only — no eager GPU init).

---

### WI-4: Install scripts

**Files:**
- Create: `scripts/install-htdemucs-ft.sh`
- Create: `scripts/install-bytedance-piano.sh`
- Create: `scripts/install-adtof.sh`
- Modify: `requirements.lock` (after running install scripts and re-locking)

The scripts mirror `scripts/install-larsnet.sh` in shape: idempotent, fail-fast, with a smoke-test at the end that imports the model and runs inference on 1 second of synthetic audio.

- [ ] **Step 4.1: Write the htdemucs_ft pre-warm script**

```bash
# scripts/install-htdemucs-ft.sh
#!/usr/bin/env bash
# Pre-warm htdemucs_ft.yaml so the first benchmark run isn't dominated by a
# 100+MB download. audio-separator caches per-user; this just primes it.
set -euo pipefail

echo "Pre-warming htdemucs_ft via audio-separator..."
# Generate a 1-second silent WAV; audio-separator downloads on first invocation
# even on tiny inputs.
SILENT=/tmp/_htdemucs_ft_warmup.wav
ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a pcm_s16le "$SILENT"

audio-separator "$SILENT" \
    --model_filename htdemucs_ft.yaml \
    --output_dir /tmp/_htdemucs_ft_warmup_out \
    --output_format WAV >/dev/null

# Verify all 4 expected stems were produced
expected=(Vocals Drums Bass Other)
for s in "${expected[@]}"; do
    if ! ls /tmp/_htdemucs_ft_warmup_out/*\("$s"\)*.wav >/dev/null 2>&1; then
        echo "FAIL: htdemucs_ft did not produce ($s) stem" >&2
        exit 1
    fi
done

rm -rf /tmp/_htdemucs_ft_warmup_out "$SILENT"
echo "OK: htdemucs_ft is installed and produces 4 stems."
```

- [ ] **Step 4.2: Write the ByteDance HR-Piano install + smoke-test script**

```bash
# scripts/install-bytedance-piano.sh
#!/usr/bin/env bash
# Install piano_transcription_inference (PyPI) and verify model loads.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" && source .venv/bin/activate

# Install. Pin a known-working version; bump after manual validation.
pip install 'piano_transcription_inference>=0.0.6'

# Smoke test: load model, run inference on 1 sec of silence
python - <<'PY'
import numpy as np
import tempfile
import soundfile as sf
from piano_transcription_inference import PianoTranscription, sample_rate

with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    sf.write(f.name, np.zeros(sample_rate, dtype=np.float32), sample_rate)
    transcriber = PianoTranscription(device="cuda")
    out = transcriber.transcribe(f.name, "/tmp/_bytedance_smoke.mid")
    print("OK: ByteDance HR-Piano loaded and ran on 1s silence.")
PY
```

- [ ] **Step 4.3: Write the ADTOF install + smoke-test script**

```bash
# scripts/install-adtof.sh
#!/usr/bin/env bash
# Install ADTOF (PyPI) and verify model loads.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" && source .venv/bin/activate

# ADTOF may pin Torch < 2.7; if pip resolution fails, log clearly so the
# implementer agent can decide whether to fork ADTOF or shell-isolate it.
if ! pip install adtof; then
    echo "FAIL: adtof install conflicted with current env." >&2
    echo "Options: (1) fork ADTOF and patch deps, (2) install in a sub-venv at .venv-adtof and shell out from drums.py" >&2
    exit 1
fi

# Smoke test
python - <<'PY'
import importlib
m = importlib.import_module("adtof")
print(f"OK: ADTOF {getattr(m, '__version__', '?')} importable.")
PY
```

- [ ] **Step 4.4: Run all three install scripts**

Run (WSL):
```bash
bash scripts/install-htdemucs-ft.sh
bash scripts/install-bytedance-piano.sh
bash scripts/install-adtof.sh
```

Each must exit 0. If `install-adtof.sh` fails with a Torch conflict, **escalate to user** before proceeding (per the spec's risk table — this is a known-possible failure mode requiring human judgment).

- [ ] **Step 4.5: Re-lock requirements**

Run (WSL): `cd /mnt/f/.../MusIQ-Lab && uv pip compile pyproject.toml --output-file requirements.lock`
(exact command depends on whether the project uses `uv pip compile`, `pip-tools`, or a different lockfile workflow — check `analyze/README.md` for the canonical command.)

- [ ] **Step 4.6: Commit**

```bash
git add scripts/install-htdemucs-ft.sh scripts/install-bytedance-piano.sh \
  scripts/install-adtof.sh requirements.lock
git commit -m "feat(install): pre-warm + install scripts for htdemucs_ft, ByteDance HR-Piano, ADTOF (WI-4)"
```

**Acceptance criteria for reviewer:**

- All three install scripts exit 0 on a clean run.
- Smoke tests inside each script confirm the model loads and runs on synthetic input.
- `requirements.lock` includes `piano_transcription_inference` and `adtof` at pinned versions.
- No `pip install` that bumps Torch off 2.7.

---

### WI-5: stems_routing.json contract + reader helper

**Files:**
- Create: `analyze/stems_routing.py` (reader helper)
- Create: `tests/test_stems_routing.py`

The orchestrator (WI-6) will *write* this file; the reader is shared by every downstream stage. Building the reader before the writer means downstream stages can be tested with synthetic routing files without waiting for WI-6.

- [ ] **Step 5.1: Write the routing reader tests**

```python
# tests/test_stems_routing.py
from pathlib import Path
import json
import pytest
from analyze.stems_routing import load, path_for, RoutingError


def _write_fixture(d: Path) -> None:
    (d / "stems_6s").mkdir()
    (d / "stems_6s" / "foo_(Piano)_htdemucs_6s.wav").touch()
    (d / "stems_bsroformer").mkdir()
    (d / "stems_bsroformer" / "foo_(Vocals)_bs_roformer.wav").touch()
    (d / "stems_routing.json").write_text(json.dumps({
        "version": 1,
        "preset": "normal",
        "routing": {
            "vocals": {"path": "stems_bsroformer/foo_(Vocals)_bs_roformer.wav"},
            "piano":  {"path": "stems_6s/foo_(Piano)_htdemucs_6s.wav"},
        },
    }))


def test_load_returns_routing_dict(tmp_path: Path):
    _write_fixture(tmp_path)
    r = load(tmp_path)
    assert r["preset"] == "normal"
    assert "vocals" in r["routing"]


def test_path_for_returns_absolute_path(tmp_path: Path):
    _write_fixture(tmp_path)
    p = path_for(tmp_path, "vocals")
    assert p.exists()
    assert p.is_absolute()


def test_unknown_stem_raises(tmp_path: Path):
    _write_fixture(tmp_path)
    with pytest.raises(RoutingError, match="unknown stem"):
        path_for(tmp_path, "drums")  # not in fixture


def test_missing_routing_file_raises(tmp_path: Path):
    with pytest.raises(RoutingError, match="not found"):
        load(tmp_path)


def test_corrupt_routing_raises(tmp_path: Path):
    (tmp_path / "stems_routing.json").write_text("{ bad json")
    with pytest.raises(RoutingError, match="parse"):
        load(tmp_path)


def test_referenced_file_missing_raises(tmp_path: Path):
    """A routing file that points to a non-existent stem must fail loudly."""
    (tmp_path / "stems_routing.json").write_text(json.dumps({
        "version": 1,
        "preset": "normal",
        "routing": {"vocals": {"path": "stems_6s/missing.wav"}},
    }))
    with pytest.raises(RoutingError, match="missing on disk"):
        path_for(tmp_path, "vocals")
```

- [ ] **Step 5.2: Run tests, verify they fail**

Run (WSL): `pytest tests/test_stems_routing.py -v`
Expected: FAIL — `analyze.stems_routing` does not exist.

- [ ] **Step 5.3: Implement the reader**

```python
# analyze/stems_routing.py
"""Reader for stems_routing.json — the contract between the stems
orchestrator and every downstream stage.

The orchestrator writes this file as the LAST action of stems.run().
Downstream stages read it instead of glob-matching against stems_6s/,
which decouples them from the orchestrator's internal model layout.

Schema (v1):
    {
        "version": 1,
        "preset": "fast" | "normal" | "best" | "ultra",
        "routing": {
            "<stem_name>": {"path": "<relative-to-cache-dir>"},
            ...
        }
    }
"""
from __future__ import annotations

import json
from pathlib import Path

CANONICAL = "stems_routing.json"
SCHEMA_VERSION = 1


class RoutingError(RuntimeError):
    """Routing file missing, malformed, or referencing a missing stem."""


def load(cache_dir: Path) -> dict:
    p = cache_dir / CANONICAL
    if not p.exists():
        raise RoutingError(f"{CANONICAL} not found in {cache_dir}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise RoutingError(f"failed to parse {p}: {e}") from e


def path_for(cache_dir: Path, stem: str) -> Path:
    """Return the absolute, on-disk path to the stem WAV. Raises if the
    routing file doesn't list this stem, or the file is missing on disk."""
    r = load(cache_dir)
    routing = r.get("routing", {})
    if stem not in routing:
        raise RoutingError(f"unknown stem {stem!r}; available: {sorted(routing)}")
    rel = routing[stem]["path"]
    abs_path = (cache_dir / rel).resolve()
    if not abs_path.exists():
        raise RoutingError(f"stem {stem!r} listed at {rel!r} but missing on disk")
    return abs_path
```

- [ ] **Step 5.4: Run tests, verify they pass**

Run (WSL): `pytest tests/test_stems_routing.py -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 5.5: Commit**

```bash
git add analyze/stems_routing.py tests/test_stems_routing.py
git commit -m "feat(analyze): stems_routing.json reader (WI-5)"
```

**Acceptance criteria for reviewer:**

- All 6 tests pass.
- Reader raises `RoutingError` with descriptive messages on every failure mode.
- No glob-matching by stem name — the routing file is the source of truth.

---

## Wave 2 — Model integrations (parallel-safe; depend on Wave 1)

WI-6 / WI-7 / WI-8 / WI-9 depend on Wave 1 being merged but not on each other. Run in parallel.

---

### WI-6: Stems orchestrator (multi-model, emits stems_routing.json)

**Files:**
- Modify: `analyze/stages/stems.py`
- Modify: `tests/test_stems.py` (if exists; create otherwise)

**Goal:** Refactor `stems.py` from a single-model `audio-separator` runner to a multi-model orchestrator that produces `stems_6s/`, `stems_htdemucs_ft/` (NEW), `stems_bsroformer/`, plus the `stems_routing.json` contract file. Routing per Spec §3 Default Routing table.

- [ ] **Step 6.1: Write tests for orchestrator behavior**

```python
# tests/test_stems.py — additions / replacements

import json
from pathlib import Path
from analyze.stages import stems


def test_resolve_routing_for_normal_preset():
    """Default routing per spec: vocals from BS-RoFormer, drums/bass/other
    from htdemucs_ft, guitar/piano from htdemucs_6s."""
    r = stems._default_routing("normal")
    assert r["vocals"]["cache_subdir"] == "stems_bsroformer"
    assert r["drums"]["cache_subdir"] == "stems_htdemucs_ft"
    assert r["bass"]["cache_subdir"] == "stems_htdemucs_ft"
    assert r["other"]["cache_subdir"] == "stems_htdemucs_ft"
    assert r["guitar"]["cache_subdir"] == "stems_6s"
    assert r["piano"]["cache_subdir"] == "stems_6s"


def test_models_per_preset_includes_required_separators():
    fast = stems.MODELS_PER_PRESET["fast"]
    normal = stems.MODELS_PER_PRESET["normal"]
    best = stems.MODELS_PER_PRESET["best"]
    # All presets must include htdemucs_6s (guitar/piano) and BS-RoFormer (vocals)
    for preset in (fast, normal, best):
        names = [m[0] for m in preset]
        assert any("htdemucs_6s" in n for n in names)
        assert any("bs_roformer" in n.lower() for n in names)
    # normal/best must include htdemucs_ft for drums/bass/other
    assert any("htdemucs_ft" in n for n, _ in normal)
    assert any("htdemucs_ft" in n for n, _ in best)
    # fast can skip htdemucs_ft to save time
    assert not any("htdemucs_ft" in n for n, _ in fast)


def test_cached_invalidates_when_routing_missing(tmp_path: Path):
    """Even if stem WAVs exist, cached() must return False if stems_routing.json
    is absent (post-Phase A; pre-Phase A caches will miss this and re-run once)."""
    s6 = tmp_path / "stems_6s"
    s6.mkdir()
    for stem in ("Vocals", "Drums", "Bass", "Guitar", "Piano", "Other"):
        (s6 / f"foo_({stem})_htdemucs_6s.wav").touch()
    sbr = tmp_path / "stems_bsroformer"
    sbr.mkdir()
    (sbr / "foo_(Vocals)_bs_roformer.wav").touch()
    (sbr / "foo_(Instrumental)_bs_roformer.wav").touch()
    # Sidecar present (pretend prior run wrote it for "normal")
    s6.joinpath(".params.json").write_text(json.dumps({
        "schema_version": stems.SCHEMA_VERSION,
        "params": {"quality": "normal"},
    }))
    assert stems.cached(tmp_path, quality="normal") is False  # routing absent
```

- [ ] **Step 6.2: Run tests, verify they fail**

Run (WSL): `pytest tests/test_stems.py -v`
Expected: FAIL — `MODELS_PER_PRESET`, `_default_routing`, new cache check not yet in place.

- [ ] **Step 6.3: Refactor stems.py**

Replace the body of `analyze/stages/stems.py` with the orchestrator shape. Key invariants:
- `STEMS_QUALITY_PRESETS` keeps its name (renamed from earlier confusion in design — keep the existing name for back-compat with tests / the webui's hard-coded preset list at `analyze-shared.js:15-19`).
- `cached()` checks both the existing per-subdir `.params.json` sidecar AND `stems_routing.json` presence.
- `run()` writes `stems_routing.json` as its **last** action.

```python
# analyze/stages/stems.py — new shape (replace existing)
"""Stage 1: stem separation, multi-model orchestration.

Runs htdemucs_6s + (optionally) htdemucs_ft + BS-RoFormer in sequence, then
writes stems_routing.json mapping each downstream-consumed stem name to the
WAV produced by the best-of-breed model for that stem.

The mp3 is first transcoded to a temporary PCM WAV via ffmpeg (see comment
block in original module for the Radiohead "creep" libsndfile bug).
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from analyze import sidecar


SCHEMA_VERSION = 2  # bumped: was 1 (single-model), now multi-model orchestrator


@dataclass(frozen=True)
class StemSpec:
    cache_subdir: str
    file_pattern: str  # glob fragment to match the produced WAV


# Per-stem default routing (Spec §3).
# Note: htdemucs_ft is a 4-stem model (vocals/drums/bass/other) — no
# guitar/piano. htdemucs_6s remains the only separator with those.
_ROUTING_NORMAL: dict[str, StemSpec] = {
    "vocals":  StemSpec("stems_bsroformer",  "*(Vocals)*.wav"),
    "drums":   StemSpec("stems_htdemucs_ft", "*(Drums)*.wav"),
    "bass":    StemSpec("stems_htdemucs_ft", "*(Bass)*.wav"),
    "guitar":  StemSpec("stems_6s",          "*(Guitar)*.wav"),
    "piano":   StemSpec("stems_6s",          "*(Piano)*.wav"),
    "other":   StemSpec("stems_htdemucs_ft", "*(Other)*.wav"),
}
# fast preset skips htdemucs_ft entirely; everything routes from htdemucs_6s
# except vocals (still BS-RoFormer — it's a one-pass cost worth eating).
_ROUTING_FAST: dict[str, StemSpec] = {
    "vocals":  StemSpec("stems_bsroformer", "*(Vocals)*.wav"),
    "drums":   StemSpec("stems_6s",         "*(Drums)*.wav"),
    "bass":    StemSpec("stems_6s",         "*(Bass)*.wav"),
    "guitar":  StemSpec("stems_6s",         "*(Guitar)*.wav"),
    "piano":   StemSpec("stems_6s",         "*(Piano)*.wav"),
    "other":   StemSpec("stems_6s",         "*(Other)*.wav"),
}


def _default_routing(quality: str) -> dict[str, dict]:
    routing = _ROUTING_FAST if quality == "fast" else _ROUTING_NORMAL
    return {k: {"cache_subdir": v.cache_subdir, "file_pattern": v.file_pattern}
            for k, v in routing.items()}


# Models to invoke per preset. Each entry is (audio-separator model_filename,
# output_subdir, demucs_shifts | None, demucs_overlap | None).
# `_resolve_quality_params` derives shifts/overlap from the existing preset
# scheme so the webui's preset list stays unchanged.
_QUALITY_PARAMS = {
    "fast":   {"shifts": 2, "overlap": 0.5},
    "normal": {"shifts": 4, "overlap": 0.5},
    "best":   {"shifts": 8, "overlap": 0.5},
}
DEFAULT_STEMS_QUALITY = "normal"
STEMS_QUALITY_PRESETS = _QUALITY_PARAMS  # back-compat alias for any external import

MODELS_PER_PRESET: dict[str, list[tuple[str, str]]] = {
    "fast": [
        ("htdemucs_6s.yaml",                                  "stems_6s"),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer"),
    ],
    "normal": [
        ("htdemucs_6s.yaml",                                  "stems_6s"),
        ("htdemucs_ft.yaml",                                  "stems_htdemucs_ft"),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer"),
    ],
    "best": [
        ("htdemucs_6s.yaml",                                  "stems_6s"),
        ("htdemucs_ft.yaml",                                  "stems_htdemucs_ft"),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer"),
    ],
}


def _resolve_quality_params(quality: str) -> dict:
    if quality not in _QUALITY_PARAMS:
        raise ValueError(f"unknown stems quality {quality!r}; expected one of {sorted(_QUALITY_PARAMS)}")
    return _QUALITY_PARAMS[quality]


def _transcode_to_clean_wav(mp3: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(mp3), "-ar", "44100", "-ac", "2",
         "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )


def cached(cache_dir: Path, *, quality: str = DEFAULT_STEMS_QUALITY) -> bool:
    routing_path = cache_dir / "stems_routing.json"
    if not routing_path.exists():
        return False
    if not sidecar.matches(cache_dir, "stems", {"quality": quality},
                            expected_schema_version=SCHEMA_VERSION):
        return False
    # Verify every routed file is on disk
    try:
        r = json.loads(routing_path.read_text())
        for stem, info in r.get("routing", {}).items():
            if not (cache_dir / info["path"]).exists():
                return False
    except (json.JSONDecodeError, OSError):
        return False
    return True


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / "stems_routing.json").read_text())


def run(mp3: Path, cache_dir: Path, *, quality: str = DEFAULT_STEMS_QUALITY) -> dict:
    qp = _resolve_quality_params(quality)
    models = MODELS_PER_PRESET[quality]

    # Create per-model output dirs
    out_dirs: dict[str, Path] = {}
    for _, subdir in models:
        d = cache_dir / subdir
        d.mkdir(exist_ok=True)
        out_dirs[subdir] = d

    clean_wav = mp3.with_suffix(".clean.wav")
    try:
        _transcode_to_clean_wav(mp3, clean_wav)
        for model_filename, subdir in models:
            argv = [
                "audio-separator", str(clean_wav),
                "--model_filename", model_filename,
                "--output_dir", str(out_dirs[subdir]) + "/",
                "--output_format", "WAV",
            ]
            # Demucs models accept shifts/overlap; BS-RoFormer ignores them.
            if "htdemucs" in model_filename:
                argv += ["--demucs_shifts", str(qp["shifts"]),
                         "--demucs_overlap", str(qp["overlap"])]
            subprocess.run(argv, check=True)
    finally:
        clean_wav.unlink(missing_ok=True)

    # Resolve routing — locate each stem's actual produced WAV
    routing = _default_routing(quality)
    resolved: dict[str, dict] = {}
    for stem, spec in routing.items():
        candidates = list((cache_dir / spec["cache_subdir"]).glob(spec["file_pattern"]))
        if not candidates:
            raise RuntimeError(f"stem {stem!r}: no file matched {spec['file_pattern']!r} "
                               f"in {spec['cache_subdir']}/ (model failed?)")
        rel = candidates[0].relative_to(cache_dir).as_posix()
        resolved[stem] = {"path": rel}

    # Write sidecar + routing as the LAST action — atomicity matters: if we
    # crash mid-orchestration, cached() must return False on the next run.
    sidecar.write(cache_dir, "stems", {"quality": quality},
                   schema_version=SCHEMA_VERSION)
    (cache_dir / "stems_routing.json").write_text(json.dumps({
        "version": 1,
        "preset": quality,
        "routing": resolved,
    }, indent=2))
    return load(cache_dir)


if __name__ == "__main__":
    import argparse
    from analyze.cache import ensure_dir, slug_for
    parser = argparse.ArgumentParser()
    parser.add_argument("mp3_path", type=Path)
    parser.add_argument("--quality", choices=sorted(_QUALITY_PARAMS),
                        default=DEFAULT_STEMS_QUALITY)
    args = parser.parse_args(sys.argv[1:])
    cd = ensure_dir(slug_for(args.mp3_path))
    print(json.dumps(run(args.mp3_path, cd, quality=args.quality), indent=2))
```

- [ ] **Step 6.4: Run unit tests**

Run (WSL): `pytest tests/test_stems.py -v`
Expected: PASS.

- [ ] **Step 6.5: Run on the existing Gorillaz cache (integration)**

Force a fresh run since the cache layout changed:
Run (WSL): `python -m analyze tests/mp3/<gorillaz>.mp3 --force --quiet`
Expected: completes; `cache/<slug>/stems_routing.json` exists; `cache/<slug>/stems_htdemucs_ft/` populated.

- [ ] **Step 6.6: Commit**

```bash
git add analyze/stages/stems.py tests/test_stems.py
git commit -m "feat(analyze): multi-model stems orchestrator + stems_routing.json (WI-6)"
```

**Acceptance criteria for reviewer:**

- `tests/test_stems.py` passes.
- A fresh `python -m analyze --force` produces `stems_routing.json` and `stems_htdemucs_ft/`.
- `STEMS_QUALITY_PRESETS` symbol still exists (back-compat for `webui/static/js/ui/analyze-shared.js`).
- `SCHEMA_VERSION = 2` (bumped to invalidate v1 caches).
- `_default_routing("fast")` does NOT reference htdemucs_ft (cost-saver).

---

### WI-7: ByteDance HR-Piano transcriber

**Files:**
- Create: `analyze/stages/transcription_piano.py`
- Create: `tests/test_transcription_piano.py`

- [ ] **Step 7.1: Write the smoke + integration test**

```python
# tests/test_transcription_piano.py
"""ByteDance HR-Piano integration. Heavy test (loads the model) — skipped
unless the install script has run."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import pytest

REQUIRES_BYTEDANCE = pytest.mark.skipif(
    importlib.util.find_spec("piano_transcription_inference") is None,
    reason="run scripts/install-bytedance-piano.sh first",
)


@REQUIRES_BYTEDANCE
def test_run_on_synthetic_silence(tmp_path: Path):
    """A 1-second silent WAV produces zero notes and a valid summary."""
    import numpy as np
    import soundfile as sf
    from analyze.stages import transcription_piano

    # Setup minimal cache layout: stems_routing.json pointing at a silent WAV
    (tmp_path / "stems_6s").mkdir()
    silence = tmp_path / "stems_6s" / "foo_(Piano)_htdemucs_6s.wav"
    sf.write(str(silence), np.zeros(44100, dtype=np.float32), 44100)
    (tmp_path / "stems_routing.json").write_text(
        '{"version":1,"preset":"normal","routing":{"piano":{"path":"stems_6s/foo_(Piano)_htdemucs_6s.wav"}}}'
    )

    fake_mp3 = tmp_path / "fake.mp3"
    fake_mp3.touch()  # not actually read in stem-input mode

    summary = transcription_piano.run(fake_mp3, tmp_path)
    assert summary["n_notes"] == 0
    assert (tmp_path / "midi" / "piano.mid").exists()


def test_default_params_present():
    from analyze.stages import transcription_piano
    assert "onset_threshold" in transcription_piano.DEFAULT_PARAMS
    assert "transcribe_full_mix" in transcription_piano.DEFAULT_PARAMS
```

- [ ] **Step 7.2: Run tests, verify they fail**

Run (WSL): `pytest tests/test_transcription_piano.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 7.3: Implement transcription_piano.py**

```python
# analyze/stages/transcription_piano.py
"""Stage 5a: piano transcription via ByteDance HR-Piano.

Replaces basic-pitch on the piano stem. ByteDance's high-resolution piano
transcription is ~96% F1 on MAPS vs basic-pitch's ~80% — significant on
real-world recordings where basic-pitch's generalist training shows.

Two routing modes:
  - stem (default): transcribe the htdemucs_6s piano stem as resolved by
    stems_routing.json
  - full mix (transcribe_full_mix=True): transcribe the original mp3.
    ByteDance handles background instrumentation reasonably; useful when
    the stem has too many separation artifacts.

VRAM: ~2 GB. We apply the lv-chordia gc pattern at end of stage.

Outputs:
    cache_dir/midi/piano.mid               — MIDI file
    cache_dir/transcription_piano.json     — note events + provenance
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from analyze import sidecar, stems_routing

CANONICAL = "transcription_piano.json"
SCHEMA_VERSION = 1

DEFAULT_PARAMS = {
    "onset_threshold":         0.3,
    "offset_threshold":        0.3,
    "frame_threshold":         0.3,
    "pedal_offset_threshold":  0.2,
    "transcribe_full_mix":     False,
}


def cached(cache_dir: Path, **params) -> bool:
    p = {**DEFAULT_PARAMS, **params}
    if not (cache_dir / CANONICAL).exists():
        return False
    if not (cache_dir / "midi" / "piano.mid").exists():
        return False
    return sidecar.matches(cache_dir, "transcription_piano", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}

    # Resolve input path — stem or mix
    if p["transcribe_full_mix"]:
        input_path = mp3
        provenance = "mix"
    else:
        input_path = stems_routing.path_for(cache_dir, "piano")
        provenance = "stem"

    out_dir = cache_dir / "midi"
    out_dir.mkdir(exist_ok=True)
    midi_path = out_dir / "piano.mid"

    # Run ByteDance HR-Piano
    from piano_transcription_inference import PianoTranscription
    transcriber = PianoTranscription(device="cuda")
    try:
        transcriber.transcribe(str(input_path), str(midi_path),
                                onset_threshold=p["onset_threshold"],
                                offset_threshold=p["offset_threshold"],
                                frame_threshold=p["frame_threshold"],
                                pedal_offset_threshold=p["pedal_offset_threshold"])
    finally:
        # VRAM hygiene — see chords.py for the pattern. ByteDance leaves a
        # ~2 GB working set strung up on weak refs without this.
        del transcriber
        import gc
        gc.collect()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # Read back the MIDI to count notes for the summary
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes_out = []
    for inst in pm.instruments:
        for nt in inst.notes:
            notes_out.append({
                "onset": float(nt.start),
                "duration": float(nt.end - nt.start),
                "pitch": int(nt.pitch),
                "velocity": int(nt.velocity),
            })

    summary = {
        "schema_version": SCHEMA_VERSION,
        "n_notes": len(notes_out),
        "notes": notes_out,
        "midi": "midi/piano.mid",
        "input_provenance": provenance,
    }
    (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
    sidecar.write(cache_dir, "transcription_piano", p, schema_version=SCHEMA_VERSION)
    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    print(f"piano: {r['n_notes']} notes (input={r['input_provenance']})")
```

- [ ] **Step 7.4: Run tests, verify they pass**

Run (WSL): `pytest tests/test_transcription_piano.py -v`
Expected: PASS (1 test passes, 1 may pass or skip depending on whether install ran).

- [ ] **Step 7.5: Commit**

```bash
git add analyze/stages/transcription_piano.py tests/test_transcription_piano.py
git commit -m "feat(analyze): ByteDance HR-Piano transcriber (WI-7)"
```

**Acceptance criteria for reviewer:**

- Tests pass (or skip cleanly on missing model).
- Module follows the stage protocol (`cached()`, `load()`, `run()`).
- VRAM cleanup pattern (gc + empty_cache) present at end of `run()`.
- `transcribe_full_mix=True` correctly switches input from the routed stem to the mp3.

---

### WI-8: ADTOF drum transcriber

**Files:**
- Modify: `analyze/stages/drums.py`
- Modify: `tests/test_drums.py` (if exists)

**Goal:** Replace `librosa.onset.onset_detect` with ADTOF for the per-piece transcription. **Preserve** the existing RMS gate, the LarsNet substem WAV emission (the webui plays them back), and the `transcribed: false` shape on gated tracks. Add an explicit ADTOF-class → `(kick, snare, toms, hihat, cymbals)` mapping per Spec §3.

- [ ] **Step 8.1: Map ADTOF outputs to our piece naming**

This work is mostly a swap of the inner loop. Add an `ADTOF_PIECE_MAP` constant:

```python
# analyze/stages/drums.py — additions

# ADTOF emits MIDI-like note numbers for drum classes. Map onto our 5-piece
# taxonomy. Multiple ADTOF classes can map to the same piece (e.g. open vs
# closed hihat both → "hihat"; multiple toms → "toms").
ADTOF_PIECE_MAP: dict[int, str] = {
    35: "kick", 36: "kick",
    38: "snare", 40: "snare",
    41: "toms", 43: "toms", 45: "toms", 47: "toms", 48: "toms", 50: "toms",
    42: "hihat", 44: "hihat", 46: "hihat",
    49: "cymbals", 51: "cymbals", 52: "cymbals", 53: "cymbals",
    55: "cymbals", 57: "cymbals", 59: "cymbals",
}
```

- [ ] **Step 8.2: Replace the per-substem librosa loop with ADTOF**

In `analyze/stages/drums.py:run()`, AFTER the existing gate logic, AFTER the LarsNet substem separation (which still produces the WAVs the webui plays), REPLACE the per-substem librosa onset loop (lines roughly 226-274) with:

```python
    # Run ADTOF on the full mix (its native input). LarsNet substems still
    # emit WAVs above for the webui's playback — ADTOF is purely the
    # transcription path.
    from adtof.io.mir import MIR
    from adtof.model.model import Model

    transcriber = Model.create_default()
    try:
        # ADTOF returns dict[class_int, list[(time_sec, velocity_0_to_1, confidence)]]
        adtof_events = transcriber.predict(str(mp3))
    finally:
        del transcriber
        import gc
        gc.collect()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # Bucket into our piece taxonomy
    summary_stems: dict[str, dict] = {p: {"events": [], "wav": f"{SUBSTEM_DIR}/{p}.wav",
                                            "n_onsets": 0}
                                       for p in SUBSTEMS}
    for cls_int, events in adtof_events.items():
        piece = ADTOF_PIECE_MAP.get(cls_int)
        if piece is None:
            continue
        for t, vel, conf in events:
            summary_stems[piece]["events"].append({
                "t": round(float(t), 3),
                "vel": round(float(vel), 3),
                "confidence": round(float(conf), 3),
            })
    for piece in SUBSTEMS:
        summary_stems[piece]["n_onsets"] = len(summary_stems[piece]["events"])
        summary_stems[piece]["events"].sort(key=lambda e: e["t"])
```

Update `SCHEMA_VERSION` from 2 → 3 (existing v2 caches re-run once).

- [ ] **Step 8.3: Test on a known-drums track**

Force a fresh drums run on a track from the corpus that has drums (e.g. Gorillaz):

Run (WSL): `python -m analyze tests/mp3/<gorillaz>.mp3 --from-stage drums`
Expected: completes; `cache/<slug>/drums_summary.json` shows ADTOF-derived events with `confidence` field present.

- [ ] **Step 8.4: Test on the Bach instrumental (gate)**

The gate must still skip the stage on Bach.

Run (WSL): `python -m analyze tests/mp3/<bach>.mp3 --from-stage drums`
Expected: `drums_summary.json` shows `transcribed: false` with the gate reason.

- [ ] **Step 8.5: Commit**

```bash
git add analyze/stages/drums.py tests/test_drums.py
git commit -m "feat(analyze): ADTOF drum transcription (WI-8)"
```

**Acceptance criteria for reviewer:**

- ADTOF runs and produces per-piece events with `velocity` and `confidence`.
- LarsNet substem WAVs still emitted (webui playback unbroken).
- Gate still works (Bach test).
- `SCHEMA_VERSION = 3`.
- VRAM cleanup pattern present.

---

### WI-9: Transcription router refactor

**Files:**
- Modify: `analyze/stages/transcription.py`
- Create: `analyze/stages/transcription_basic.py` (extracted basic-pitch helper)
- Create: `tests/test_transcription_router.py`

**Goal:** `transcription.py` becomes a thin dispatcher. For each stem, call the appropriate transcriber (`transcription_vocals` for vocals, `transcription_piano` for piano, `transcription_basic` for the rest). The dispatcher reads `stems_routing.json` to find each stem's audio path.

- [ ] **Step 9.1: Extract basic-pitch single-stem logic into transcription_basic.py**

```python
# analyze/stages/transcription_basic.py
"""basic-pitch on a single stem WAV. Extracted from the previous
transcription.py so the new router can dispatch cleanly per-stem."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PARAMS_PER_STEM = {
    "vocals": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "bass":   dict(onset_threshold=0.5, frame_threshold=0.4, minimum_note_length=50,
                   minimum_frequency=27.5, maximum_frequency=400),
    "guitar": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "piano":  dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=27.5),
    "other":  dict(onset_threshold=0.6, minimum_note_length=100, minimum_frequency=80),
}


def transcribe_stem(wav_path: Path, midi_path: Path, **params) -> dict:
    """Transcribe a single stem WAV with basic-pitch; write MIDI; return note count."""
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict
    _, midi_data, note_events = predict(
        str(wav_path),
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        multiple_pitch_bends=True,
        melodia_trick=True,
        **params,
    )
    midi_data.write(str(midi_path))
    return {"n_notes": len(note_events), "midi": str(midi_path)}
```

- [ ] **Step 9.2: Write router dispatch tests with mocks**

```python
# tests/test_transcription_router.py
from pathlib import Path
import json
from unittest.mock import patch, MagicMock

from analyze.stages import transcription


def test_dispatch_routes_per_stem_per_transcriber(tmp_path: Path):
    """vocals → transcription_vocals; piano → transcription_piano; rest → basic."""
    # Arrange: stems_routing.json with 6 stems
    (tmp_path / "stems_6s").mkdir()
    for s in ("Vocals", "Drums", "Bass", "Guitar", "Piano", "Other"):
        (tmp_path / "stems_6s" / f"foo_({s})_htdemucs_6s.wav").touch()
    (tmp_path / "stems_routing.json").write_text(json.dumps({
        "version": 1, "preset": "normal",
        "routing": {
            "vocals": {"path": "stems_6s/foo_(Vocals)_htdemucs_6s.wav"},
            "bass":   {"path": "stems_6s/foo_(Bass)_htdemucs_6s.wav"},
            "guitar": {"path": "stems_6s/foo_(Guitar)_htdemucs_6s.wav"},
            "piano":  {"path": "stems_6s/foo_(Piano)_htdemucs_6s.wav"},
            "other":  {"path": "stems_6s/foo_(Other)_htdemucs_6s.wav"},
        }
    }))
    fake_mp3 = tmp_path / "fake.mp3"
    fake_mp3.touch()
    # Pre-create vocal_f0.npz so transcription_vocals doesn't bail
    import numpy as np
    np.savez(tmp_path / "vocal_f0.npz", fcpe=np.zeros(100), pesto=np.zeros(100))

    with patch("analyze.stages.transcription_vocals.run") as mock_v, \
         patch("analyze.stages.transcription_piano.run") as mock_p, \
         patch("analyze.stages.transcription_basic.transcribe_stem") as mock_b:
        mock_v.return_value = {"n_notes": 5, "midi": "midi/vocals.mid"}
        mock_p.return_value = {"n_notes": 12, "midi": "midi/piano.mid"}
        mock_b.return_value = {"n_notes": 7, "midi": "midi/x.mid"}

        result = transcription.run(fake_mp3, tmp_path)

        assert mock_v.call_count == 1
        assert mock_p.call_count == 1
        assert mock_b.call_count == 3  # bass, guitar, other
```

- [ ] **Step 9.3: Run test, verify it fails**

Run (WSL): `pytest tests/test_transcription_router.py -v`
Expected: FAIL — old `transcription.run` doesn't dispatch.

- [ ] **Step 9.4: Refactor transcription.py to a router**

```python
# analyze/stages/transcription.py — replace existing
"""Stage 6: per-stem transcription router.

Dispatches each stem to the appropriate transcriber:
    vocals → transcription_vocals (F0→notes from FCPE+PESTO)
    piano  → transcription_piano  (ByteDance HR-Piano)
    bass / guitar / other → transcription_basic (basic-pitch)

drums is handled separately by the drums stage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from analyze import sidecar, stems_routing
from analyze.stages import transcription_basic, transcription_piano, transcription_vocals

CANONICAL = "transcription_summary.json"
SCHEMA_VERSION = 2  # bumped from previous flat shape

# Per-stem transcriber. Edit here to change the dispatch policy.
TRANSCRIBERS: dict[str, str] = {
    "vocals": "vocals",
    "piano":  "piano",
    "bass":   "basic",
    "guitar": "basic",
    "other":  "basic",
}


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    midi_dir = cache_dir / "midi"
    if not all((midi_dir / f"{s}.mid").exists() for s in TRANSCRIBERS):
        return False
    return sidecar.matches(cache_dir, "transcription", _normalize(params),
                            expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def _normalize(params: dict) -> dict:
    """Canonicalize the per-stem params dict so sidecar comparison is deterministic."""
    return {k: dict(v) for k, v in sorted(params.items())}


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    """`params` is a dict[stem_name, dict[param, value]] override map."""
    out_dir = cache_dir / "midi"
    out_dir.mkdir(exist_ok=True)
    results: dict[str, dict] = {}

    for stem, transcriber in TRANSCRIBERS.items():
        per_stem_params = params.get(stem, {})
        if transcriber == "vocals":
            results[stem] = transcription_vocals.run(mp3, cache_dir, **per_stem_params)
        elif transcriber == "piano":
            results[stem] = transcription_piano.run(mp3, cache_dir, **per_stem_params)
        elif transcriber == "basic":
            wav_path = stems_routing.path_for(cache_dir, stem)
            midi_path = out_dir / f"{stem}.mid"
            base_params = transcription_basic.DEFAULT_PARAMS_PER_STEM[stem]
            results[stem] = transcription_basic.transcribe_stem(
                wav_path, midi_path, **{**base_params, **per_stem_params}
            )
        else:
            raise RuntimeError(f"unknown transcriber {transcriber!r} for stem {stem}")

    (cache_dir / CANONICAL).write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "results": results,
    }, indent=2))
    sidecar.write(cache_dir, "transcription", _normalize(params),
                   schema_version=SCHEMA_VERSION)
    return {"results": results}


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    for stem, info in r["results"].items():
        print(f"{stem}: {info.get('n_notes', '?')} notes")
```

- [ ] **Step 9.5: Run tests, verify they pass**

Run (WSL): `pytest tests/test_transcription_router.py -v`
Expected: PASS.

- [ ] **Step 9.6: Commit**

```bash
git add analyze/stages/transcription.py analyze/stages/transcription_basic.py tests/test_transcription_router.py
git commit -m "feat(analyze): per-stem transcription router (WI-9)"
```

**Acceptance criteria for reviewer:**

- Router dispatches per-stem correctly per `TRANSCRIBERS` map.
- vocals → `transcription_vocals.run`, piano → `transcription_piano.run`, bass/guitar/other → `transcription_basic.transcribe_stem`.
- No GPU init at module load (deferred to first `run()` call).
- Cache schema bumped to 2.

---

## Wave 3 — Integration + validation (sequential)

WIs in this wave depend on Wave 2 being complete and merged.

---

### WI-10: Pipeline integration

**Files:**
- Modify: `analyze/pipeline.py` (extend `_enrich_stems`, summary writer hook)
- Modify: `analyze/summary_writer.py` (provenance block extended)

**Goal:** Wire the new orchestrator + router + selective re-run into `analyze.analyze()` end-to-end. Update `_enrich_stems` to consume the new router output shape (`{"results": {stem: {n_notes, midi}}}`) instead of the old flat `{stem: {notes, midi}}`. Update the summary writer to include per-stage params in `provenance`.

- [ ] **Step 10.1: Update _enrich_stems for new router output**

Read `analyze/pipeline.py` `_enrich_stems()` (the function called at line ~317 with `results["transcription"]`). The shape it receives changes from `{vocals: {notes, midi}, ...}` to `{results: {vocals: {n_notes, midi}, ...}}`. Adjust the iteration accordingly.

- [ ] **Step 10.2: Extend summary provenance**

In `analyze/summary_writer.py`, the provenance block currently has `stems_quality`. Add `params: dict[stage, dict]` reflecting the resolved params used per-stage (read from each stage's `.params_<stage>.json` sidecar at write time).

- [ ] **Step 10.3: End-to-end smoke test**

Run (WSL):
```bash
python -m analyze tests/mp3/<gorillaz>.mp3 --force
```
Expected: completes; `cache/<slug>/<slug>.summary.json` contains:
- `provenance.stems_quality` = "normal"
- `provenance.params.transcription` = `{}` (no overrides)
- `provenance.params.stems` = `{"quality": "normal"}`
- `stems.vocals.n_notes` > 0, `stems.piano.n_notes` > 0

- [ ] **Step 10.4: Selective re-run smoke test**

Run (WSL):
```bash
python -m analyze tests/mp3/<gorillaz>.mp3 --from-stage transcription
```
Expected: only stages from `transcription` onward run; stems / beats / key / chords show "cached"; transcription runs; summary regenerated.

- [ ] **Step 10.5: Commit**

```bash
git add analyze/pipeline.py analyze/summary_writer.py
git commit -m "feat(analyze): wire orchestrator + router + selective re-run end-to-end (WI-10)"
```

**Acceptance criteria for reviewer:**

- `python -m analyze --force` succeeds end-to-end.
- `python -m analyze --from-stage transcription` runs only transcription onward; stems/beats/etc. report "cached".
- `summary.json` `provenance.params` populated correctly.
- All existing pipeline-level tests pass.

---

### WI-11: Webui plumbing

**Files:**
- Modify: `webui/webui/analyze_runner.py` (selective `_clear_cache_dir`; param payload forwarding)
- Modify: `webui/webui/server.py` (endpoints accept `stages`, `params`)
- Modify: `webui/tests/test_server.py` (cover new optional payload shape)

**Goal:** Backend plumbing only; **no UI changes**. The modal still sends quality-only payloads as before. The endpoints accept optional `stages` (list[str]) and `params` (dict) for Phase E to consume later.

- [ ] **Step 11.1: Make `_clear_cache_dir` selective**

```python
# webui/webui/analyze_runner.py — modify _clear_cache_dir

# Per-stage produced artifacts (relative to cache_dir). Drives selective
# clear. Mirrors the producing stage modules' canonical filenames.
STAGE_ARTIFACTS: dict[str, list[str]] = {
    "stems":         ["stems_6s/", "stems_htdemucs_ft/", "stems_bsroformer/",
                      "stems_routing.json", ".params_stems.json"],
    "beats":         ["madmom_downbeats.json", ".params_beats.json"],
    "key":           ["skey.json", ".params_key.json"],
    "chords":        ["chords.json", ".params_chords.json"],
    "transcription": ["midi/", "transcription_summary.json",
                      "transcription_vocals.json", "transcription_piano.json",
                      ".params_transcription.json", ".params_transcription_vocals.json",
                      ".params_transcription_piano.json"],
    "beats_xcheck":  ["beat_this.json", ".params_beats_xcheck.json"],
    "vocal_f0":      ["vocal_f0.npz", "vocal_f0_summary.json", ".params_vocal_f0.json"],
    "drums":         ["stems_drums/", "drums_summary.json"],
}


def _clear_cache_dir(cache: Path, *, only_stages: set[str] | None = None) -> None:
    PRESERVE = {"chat.json", "lyrics", "user_meta.json", f"{cache.name}.mp3"}
    # Selective clear: delete only the artifacts of `only_stages`.
    # Default (None): legacy full-cache wipe excluding PRESERVE.
    if only_stages is None:
        targets = list(cache.iterdir())
    else:
        targets = []
        for stage in only_stages:
            for art in STAGE_ARTIFACTS.get(stage, []):
                p = cache / art
                if p.exists():
                    targets.append(p)

    import time as _time
    for child in targets:
        if child.name in PRESERVE:
            continue
        last_err: BaseException | None = None
        for attempt in range(4):
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                _time.sleep(0.3 * (attempt + 1))
        if last_err is not None:
            raise CacheLockedError(child, last_err)
```

- [ ] **Step 11.2: Forward stages + params payload to the WSL command**

Modify `run_analyze_stream()` to accept `stages_only: set[str] | None` and `params: dict | None`:

```python
async def run_analyze_stream(slug: str, source_path: Path, quality: str, *,
                              stages_only: set[str] | None = None,
                              params: dict | None = None):
    ...
    # Build the WSL command
    flags = [f"--stems-quality {shlex.quote(quality)}"]
    if stages_only:
        flags.append(f"--stages-only {shlex.quote(','.join(sorted(stages_only)))}")
    if params:
        # Write a temp file (path lives in /tmp on Windows side; convert for WSL)
        import tempfile
        params_file_win = Path(tempfile.mkstemp(suffix=".json", prefix="musiq_params_")[1])
        params_file_win.write_text(json.dumps(params))
        params_file_wsl = _to_wsl_path(params_file_win)
        flags.append(f"--params-json {shlex.quote(params_file_wsl)}")

    script = (
        f"cd {shlex.quote(project_wsl)} && "
        f"source .venv/bin/activate && "
        f"python -u -m analyze {shlex.quote(src_wsl)} "
        + " ".join(flags) + " 2>&1"
    )
```

Selective clear:

```python
    if any(cache.iterdir()):
        try:
            _clear_cache_dir(cache, only_stages=stages_only)
        except CacheLockedError as e:
            ...  # existing error path
```

- [ ] **Step 11.3: Update server endpoints**

In `webui/webui/server.py`, the analyze + reanalyze endpoints accept JSON. Add optional fields:

```python
class ReanalyzePayload(BaseModel):
    quality: str = "best"
    stages: list[str] | None = None   # NEW
    params: dict | None = None         # NEW


@app.post("/api/tools/reanalyze/{slug}")
async def reanalyze(slug: str, payload: ReanalyzePayload):
    ...
    return StreamingResponse(
        run_analyze_stream(slug, source_path, payload.quality,
                            stages_only=set(payload.stages) if payload.stages else None,
                            params=payload.params),
        ...
    )
```

Same for the file-upload + youtube analyze endpoints.

- [ ] **Step 11.4: Cover new payload shape in tests**

```python
# webui/tests/test_server.py — additions

def test_reanalyze_accepts_stages_payload(client, monkeypatch):
    """Payload with stages=['transcription'] is accepted; quality-only legacy still works."""
    received = {}

    async def fake_stream(slug, src, quality, *, stages_only=None, params=None):
        received["slug"] = slug
        received["stages_only"] = stages_only
        received["params"] = params
        yield b'{"type":"done","stats":{}}\n'

    monkeypatch.setattr("webui.webui.server.run_analyze_stream", fake_stream)
    resp = client.post("/api/tools/reanalyze/test_slug",
                        json={"quality": "best", "stages": ["transcription"]})
    assert resp.status_code == 200
    # Drain the stream
    list(resp.iter_lines())
    assert received["stages_only"] == {"transcription"}
    assert received["params"] is None


def test_reanalyze_legacy_payload_still_works(client, monkeypatch):
    """Quality-only payload behaves exactly as before."""
    received = {}

    async def fake_stream(slug, src, quality, *, stages_only=None, params=None):
        received["stages_only"] = stages_only
        yield b'{"type":"done","stats":{}}\n'

    monkeypatch.setattr("webui.webui.server.run_analyze_stream", fake_stream)
    resp = client.post("/api/tools/reanalyze/test_slug", json={"quality": "best"})
    list(resp.iter_lines())
    assert received["stages_only"] is None
```

- [ ] **Step 11.5: Run webui tests**

Run (Windows): `cd webui && uv run pytest`
Expected: PASS.

- [ ] **Step 11.6: Commit**

```bash
git add webui/webui/analyze_runner.py webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): accept optional stages + params in analyze/reanalyze (WI-11)"
```

**Acceptance criteria for reviewer:**

- All webui tests pass.
- Legacy quality-only payloads behave unchanged.
- New `stages` / `params` payloads forward to the analyze CLI correctly.
- Selective `_clear_cache_dir` only touches the artifacts of the listed stages.
- The temp params JSON file path is correctly converted to a WSL-style path.

---

### WI-12: Run benchmark, write validation report

**Files:**
- Run (no new files): `bash scripts/benchmark-pipeline.sh phaseA`
- Generated: `install-logs/phase-a-validation.md`

This WI is **not auto-executable** by an implementer agent — it requires the user to have populated `tests/corpus/sources.txt` and the label files first (per WI-2's reviewer note). The reviewer agent on this WI is the gating one for the entire PR series.

- [ ] **Step 12.1: Verify corpus populated**

Run (WSL):
```bash
test -s tests/corpus/sources.txt && \
test "$(ls tests/corpus/labels/*.json 2>/dev/null | grep -v _template | wc -l)" -ge 5
```
Expected: exit 0. If FAIL, **escalate to user** — corpus must be populated before benchmark is meaningful.

- [ ] **Step 12.2: Snapshot baseline**

If `tests/corpus/snapshots/baseline/` is empty, run the **pre-Phase-A** code on the corpus first. Easiest path: `git stash` the Phase A changes, run baseline, then `git stash pop`.

Run (WSL): `bash scripts/benchmark-pipeline.sh baseline`
Expected: completes; `tests/corpus/snapshots/baseline/` populated.

- [ ] **Step 12.3: Run candidate**

With Phase A code in place:
Run (WSL): `bash scripts/benchmark-pipeline.sh phaseA`
Expected: completes; `install-logs/phase-a-validation.md` written.

- [ ] **Step 12.4: Verify ship gates**

Read `install-logs/phase-a-validation.md`. Confirm against Spec §9:

- Zero regressions on `key`, `bpm`, `chord_count`, `downbeat_count`.
- JVKE Golden Hour piano `note_count` ≥ 2× baseline.
- Sustained-vocals tracks: vocal MIDI ≥ 1.5× baseline AND FCPE-PESTO agreement on produced notes ≥ 0.85.
- Drums: ADTOF F1 ≥ 0.85 on labeled drum tracks; phantom-onset rate on Bach = 0.

If any gate fails, **escalate to user** with the specific failing metric. Do NOT proceed to WI-13.

- [ ] **Step 12.5: Commit**

```bash
git add install-logs/phase-a-validation.md tests/corpus/snapshots/
git commit -m "test(analyze): Phase A validation report (WI-12)"
```

**Acceptance criteria for reviewer:**

- `install-logs/phase-a-validation.md` exists and shows numbers (not stubs).
- Every Spec §9 ship gate is green in the report.
- `tests/corpus/snapshots/baseline/` and `tests/corpus/snapshots/phaseA/` both populated.

---

### WI-13: Documentation pass

**Files:**
- Modify: `analyze/README.md`
- Modify: `docs/history.md`

- [ ] **Step 13.1: Document new CLI flags + per-stage params model in analyze/README.md**

Add a section explaining `--stages-only`, `--from-stage`, `--params-json`, the per-stage params sidecar, and the `STAGE_DEPS` graph. Include an example workflow:

```markdown
## Iterative tuning workflow

For tweaking transcription params without re-running the full pipeline:

    # 1. Initial full run (populates cache including stems)
    python -m analyze song.mp3

    # 2. Try aggressive piano onset threshold
    cat > /tmp/try1.json <<EOF
    {"transcription": {"piano": {"onset_threshold": 0.2}}}
    EOF
    python -m analyze song.mp3 --stages-only transcription --params-json /tmp/try1.json

    # 3. Compare summary.json piano note count vs the baseline. Keep tuning.
```

- [ ] **Step 13.2: Add a chronicle entry to docs/history.md**

Read the existing format in `docs/history.md` and add a section for the Phase A+B work. Cover: what, why, validation results (headline numbers from `install-logs/phase-a-validation.md`), known gotchas.

- [ ] **Step 13.3: Commit**

```bash
git add analyze/README.md docs/history.md
git commit -m "docs(analyze): document Phase A+B specialist models + selective re-run (WI-13)"
```

**Acceptance criteria for reviewer:**

- `analyze/README.md` documents the three new CLI flags with examples.
- `docs/history.md` entry follows the existing format and references the validation log.
- No outdated references to "single basic-pitch model" or "all-or-nothing reanalyze."

---

## Self-review against the spec

Spot-checked sections of the spec against this plan:

- **Spec §3 architecture (stems orchestrator)**: covered by WI-6.
- **Spec §3 piano transcription**: covered by WI-7.
- **Spec §3 vocal F0→notes**: covered by WI-3.
- **Spec §3 ADTOF drums**: covered by WI-8.
- **Spec §3 transcription router**: covered by WI-9.
- **Spec §3 sidecar primitive**: covered by WI-1.
- **Spec §3 stage dependency graph**: covered by WI-1.
- **Spec §3 selective re-run**: covered by WI-1 (CLI/pipeline) + WI-11 (webui).
- **Spec §4 file create/modify list**: every file mapped to an owner WI in the table at top.
- **Spec §5 validation harness + corpus**: covered by WI-2.
- **Spec §6 caching + migration**: schema_version bumps inline (stems→2, transcription→2, drums→3); migration is one-time reanalyze handled gracefully.
- **Spec §9 validation criteria**: gated by WI-12 reviewer.
- **Spec §10 reviewer subagent prompt**: every WI has explicit acceptance criteria; the reviewer prompt template lives in the spec; the WI execution agents implement against it.

No placeholders in the plan. Type names (`StemSpec`, `NoteEvent`, `RoutingError`) are consistent across WIs.

---

## Plan complete

**Plan saved to** `docs/superpowers/plans/2026-05-03-phase-ab-pipeline-upgrade.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per WI, reviewer subagent gating, fast iteration. Matches the spec's `claude-agent-sdk` ralph-loop intent.
2. **Inline Execution** — execute WIs in this session using `superpowers:executing-plans`, batch with checkpoints for review.

Per the user's request, the implementation runs **in a new session** with subagents and ralph loops. Execution should pick the **subagent-driven path**, with the runner script template in Spec §10 driving each WI.
