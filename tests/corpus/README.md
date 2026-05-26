# Corpus

10 tracks for Phase A validation, per [`docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](../../docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md) §5.

## Setup

1. Fill in `sources.txt` with one YouTube URL per slot (see comments inside).
2. Hand-label each track: copy `labels/_template.json` to `labels/<slug>.json` and fill in.
3. Run `bash scripts/fetch-test-fixtures.sh` (downloads mp3s to `tests/mp3/`).
4. Run `bash scripts/benchmark-pipeline.sh baseline` to snapshot baseline.
5. After Phase A changes, run `bash scripts/benchmark-pipeline.sh phaseA`.
6. Read `install-logs/phase-a-validation.md` for the delta.

## Note on slugs

Track slugs in `labels/<slug>.json` should match the `<slug>` used in `cache/<slug>/<slug>.summary.json`. The pipeline derives slugs from the source mp3 filename — see `analyze/cache.py` for the exact derivation. After fetching a track, run `python -m analyze tests/mp3/<file>.mp3` once to materialize the cache directory and observe the slug it generates.

## Snapshots

`snapshots/baseline/` — reference snapshot taken before Phase A changes.
`snapshots/<label>/` — candidate snapshot taken after a pipeline run.

Both directories are gitignored (binary-like large JSON blobs). Regenerate by running the benchmark script.
