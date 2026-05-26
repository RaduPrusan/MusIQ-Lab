# Phase D — Confidence signals + cross-validation

**Date:** 2026-05-03
**Effort:** ≈1 week
**Depends on:** [Phase A+B](phase-a-specialist-models.md). Independent of [Phase C](phase-c-structural-layer.md) — can run in parallel.
**Status:** Sketch — full spec to be written when Phase A+B ships.

## Goal

Make the app trustworthy. Every detection should ship with a confidence number, and the UI should be able to flag "trust this" vs "double-check this" at a glance. Today only `key` exposes a confidence value, and it's ~always 1.0 from skey.

This is what turns the app from "looks plausible" to "tool a working musician relies on."

## Scope

**In:**

- **Per-chord confidence** from lv-chordia. The model exposes posteriors internally; the wrapper currently discards them. Surface `{"start", "end", "label", "confidence"}` on each chord event.
- **Per-note confidence** from basic-pitch (already in note events) and from ByteDance HR-Piano (Phase A). Persist into the per-stem MIDI as note velocity-or-meta and into a JSON sidecar.
- **Per-beat agreement** — already computed implicitly by `beats_xcheck`. Surface as a per-beat agreement score (madmom-vs-beat-this delta in milliseconds, plus a binary "high-agreement" flag).
- **Per-section confidence** — boundary salience from the segmenter (Phase C output).
- **Cross-validation passes** where a second model exists:
  - Beats: madmom + beat-this (already done; just surface).
  - Key: skey + librosa-KS-fallback agreement.
  - Vocal F0: FCPE + PESTO agreement (already computed; not yet routed to confidence).
- **Confidence rollup** in `summary.json` — a `quality` block per stage with min / median / pct-low-confidence.

**Out:**

- UI affordances for confidence (color shading on the piano-roll, badges on chord labels) — that's surface-level, belongs in Phase E.
- New models for the sake of cross-validation. We use what's already running.

## Deliverables

1. **`analyze/stages/chords.py`** — extract posteriors from lv-chordia, write to `chords.json`.
2. **`analyze/stages/transcription.py`** + new transcribers — preserve per-note confidence into MIDI metadata and JSON sidecar.
3. **`analyze/stages/beats_xcheck.py`** — per-beat agreement output.
4. **`analyze/derivation.py`** — confidence rollup.
5. **`analyze/jams_writer.py` / `summary_writer.py`** — extended schema with confidence fields. Schema version bumped.
6. **Tests** verifying confidence values are present, plausible, and stable across runs on the corpus.

## Validation criteria

- Every chord, note, beat, and section in `summary.json` has a `confidence` field in `[0.0, 1.0]`.
- Histogram of confidences across the corpus shows reasonable spread — if everything is 1.0 or 0.0, the signal is broken.
- A manually-mis-labeled test (e.g. forced-wrong key) produces visibly lower per-section key confidence at the wrong section.

## Risks

- **lv-chordia internal API**: the wrapper at `chords.py:23` is opaque; extracting posteriors may require a fork or monkey-patch. Validate feasibility in Phase 0 of this phase.
- **Schema bump**: existing `summary.json` files in cache become stale when the schema version goes up. Provide a migration helper or accept a one-time reanalyze across the library.
