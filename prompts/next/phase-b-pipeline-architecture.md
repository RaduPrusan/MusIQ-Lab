# Phase B — Pipeline architecture: per-stage params + selective re-run

**Date:** 2026-05-03
**Effort:** ≈1 week
**Depends on:** nothing (pure infrastructure)
**Bundled with:** [Phase A](phase-a-specialist-models.md) — same spec, same PR series
**Spec:** [`docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](../../docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md)

## Goal

Make the analyze pipeline **selectively re-runnable** at stage granularity, with per-stage parameter sidecars that automatically invalidate the right caches when params change. Without this, Phase E (advanced settings modal) is unusable — every transcription tweak would rewind ~5 minutes of stems work.

## Scope

**In:**

- **Generalize the `stems/.params.json` sidecar pattern** to every stage that takes parameters. The pattern already exists in `analyze/stages/stems.py:104-110` and is the template.
- **Per-stage `cached()`** signature gains `**params` and compares against the sidecar.
- **Pipeline driver** gets a "stages to run / stages to skip" set:
  - `--stages-only stem,trans` — run only those stages, leave others alone.
  - `--from-stage trans` — re-run from this stage onwards (downstream invalidation).
  - Default: current behavior (all-or-nothing based on cache hits).
- **`_clear_cache_dir`** in `webui/webui/analyze_runner.py` becomes selective. It deletes only the artifacts of stages being re-run, not the full cache tree.
- **Stage dependency graph** — explicit, declared in `analyze/pipeline.py`. Used to compute downstream invalidation when a stage's params change.
- **Webui reanalyze + analyze flows** accept an optional `stages` payload that maps to `--stages-only`. Backward-compatible: omitting it preserves current behavior.

**Out:**

- The actual modal UI for picking stages / params (Phase E).
- Surfacing per-stage params in `summary.json` provenance beyond the existing `stems_quality` field — Phase E will extend this.

## Deliverables

1. **`analyze/cache.py`** — new `params_sidecar(cache_dir, stage)` and `write_params(cache_dir, stage, params)` helpers shared across all stages.
2. **All eight `analyze/stages/*.py`** — `cached()` signatures normalized to `(cache_dir, **params)`. Stages without tunable params use empty `{}` (no-op).
3. **`analyze/pipeline.py`** — explicit `STAGE_DEPS: dict[str, set[str]]` graph; `analyze()` gains `stages_only`, `from_stage` kwargs.
4. **`analyze/__main__.py`** — argparse exposes `--stages-only`, `--from-stage`.
5. **`webui/webui/analyze_runner.py`** — `_clear_cache_dir(cache, *, only_stages=None)` is selective.
6. **`webui/webui/server.py`** — analyze + reanalyze endpoints accept optional `stages` payload.
7. **Tests** — selective re-run round-trips: write a cache, change one stage's params, run with `--stages-only`, verify only that stage's artifacts changed and downstream artifacts were cleared.
8. **`docs/history.md`** — chronicle entry.

## Validation criteria

- Existing reanalyze flow (no `stages` payload) behaves exactly as before — full cache wipe + full re-run.
- Setting `--stages-only=transcription` after a baseline run regenerates only `midi/`, `transcription_summary.json`, and the derived `summary.json` derivation block; everything else stays untouched and `cached()` returns true for upstream stages.
- Changing `transcription` params and running `--stages-only=transcription` correctly invalidates the cache (sidecar mismatch) and re-runs.
- Changing `stems` params and running without `--stages-only` correctly cascades: stems re-runs, then everything downstream of stems re-runs (because stems artifacts changed).

## Risks

- **Stage dependency graph** must be conservative. If we declare `transcription` doesn't depend on `key`, but it actually reads from key in some future code path, we'd serve stale data. The graph lives in code, gets enforced via tests that introspect actual reads.
- **Sidecar drift** — if a stage's param defaults change in code without a version bump, existing caches would silently look valid. Solve by adding a `schema_version` field in every sidecar, similar to `drums_summary.json:33`'s existing pattern.
- **Webui cache clear semantics** — the current `PRESERVE` set in `analyze_runner.py:69` is global. With selective re-run, we need per-stage artifact lists. Get this right or risk wiping `chat.json` or the source MP3.
