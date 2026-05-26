# Fix enharmonic coherence between `track.key` and `analysis.scale`

You are a backend engineer working on the `analyze/` pipeline of MusIQ-Lab. Your single job is to make the analyzer emit one consistent enharmonic spelling for a track's key across every place it appears in `summary.json`. The webui's notation layer already faithfully prettifies whatever it receives; the bug is upstream.

## The bug, by example

Run the pipeline on a track in D♯/E♭ minor and look at `summary.json`:

| Field | Current value | Spelled as |
|---|---|---|
| `track.key` | `"D# minor"` | sharp |
| `analysis.scale` | `"E♭ natural minor"` | flat |
| `essentia_agreement.key.analyze` | `"D# minor"` | sharp (echoes `track.key`) |
| `essentia_agreement.key.essentia_consensus` | `"F#:major"` | sharp (mir_eval colon form) |
| `chords_alt_key.scale` (when present) | depends on Essentia side | mixed |

The two fields name the same key with two different enharmonic letters. In the webui this shows up as e.g. "Re♯ minor" in the top-bar pill and "Mi♭ natural minor" in the scale badge — visible on every track whose key tonic falls in {C♯/D♭, D♯/E♭, F♯/G♭, G♯/A♭, A♯/B♭}.

Verified live on `cache/charlie_puth-attention_official_video-nfs8nyg7yqm/summary.json`.

## Root cause

`summary["track"]["key"]` (`analyze/writers/summary_writer.py:134`) is the **raw string** from `results["key"]["key"]`, which `analyze/stages/key.py:61` got verbatim from `skey.detect_key(...)`. The `skey` library emits sharps (`"D# minor"`).

`summary["analysis"]["scale"]` (`analyze/pipeline.py:632`) is `scale_name(parse_key(raw))`. The function in `analyze/derived/theory.py:416-430` re-spells the tonic for minor keys whose pitch class is in `_PREFER_FLAT_PCS = {1, 3, 6, 8, 10}` (`theory.py:402`) so that the conventional flat name wins: PC 3 in minor → `"E♭"`.

Two different formatters, two different opinions. The first wins for `track.key`; the second wins for `analysis.scale`; the gap is the bug.

The cross-check block adds a third spelling style — mir_eval colon form (`"F#:major"`) — but that is exempt: it is Essentia's own output and the webui's `humanizeKeyString` already collapses the colon into a space at render time. You don't need to touch the colon form.

## Goal

After your fix, for every track whose pipeline run completes successfully:

1. `summary["track"]["key"]` and `summary["analysis"]["scale"]` parse via `analyze.derived.theory.parse_key` to the **same `Key`** (same `tonic_pc`, same `mode`) **AND** have the **same enharmonic spelling of the tonic letter** (both flat or both sharp).
2. `summary["essentia_agreement"]["key"]["analyze"]` matches `track.key` byte-for-byte (it already echoes that field; keep it that way).
3. `summary["chords_alt_key"]["key"]` and `summary["chords_alt_key"]["scale"]` (when present) follow the same rule, using Essentia's consensus tonic as the input. The Essentia consensus colon form (`"F#:major"`) is allowed to remain as-is in the agreement block — only the rendered/canonicalized `chords_alt_key` fields need to be consistent with each other.
4. `skey.json` may keep its raw string (it is the model's verbatim output and useful for debugging). Canonicalization can happen at the writer boundary.
5. A round-trip is stable: feeding a canonicalized key string back through `parse_key` → canonicalize again returns the same string.

You do **not** need to change the chord labels in `summary["chords"]` (`"D#:min7"`, `"Eb:min7"` etc. are mir_eval shorthand that downstream code already handles). You also do **not** need to change MIDI files, JAMS exports, or the `chords_enriched`/`stems_enriched` blocks beyond their key/scale strings.

## Pick the canonicalization rule

Read `analyze/derived/theory.py:395-430` first. The existing `scale_name()` already encodes a sensible rule: major → sharp; minor → flat for the five flat-preferred pitch classes. Make that the canonical rule for the **whole** key/scale pipeline, not just the scale string.

Concretely, add a function alongside `scale_name`:

```python
def canonical_key_name(key: Key) -> str:
    """Return the canonical 'Tonic mode' string for `key`, matching the
    spelling convention `scale_name` uses (major → sharp; minor → flat for
    {C♯/D♭, D♯/E♭, F♯/G♭, G♯/A♭, A♯/B♭}).

    Round-trips with `parse_key`: parse_key(canonical_key_name(k)) == k.

    Used at every writer boundary that emits a human-readable key string,
    so `track.key` and `analysis.scale` always agree on enharmonic spelling.
    """
    ...
```

The body is one line of reuse over the existing tables and `_PREFER_FLAT_PCS`. Keep it next to `scale_name` so the rule lives in one place. Add a parallel helper if you find a clean way to deduplicate against `scale_name` — don't force it.

## Where to apply the canonicalizer

Treat **the writer boundary** as the canonicalization point. Don't mutate `results["key"]["key"]` in place (that's the raw skey output and other stages may want it for traceability). Instead, when building `summary`:

- `analyze/writers/summary_writer.py:134` — wrap `results["key"]["key"]` with `canonical_key_name(parse_key(results["key"]["key"]))`. (Same `Key` object the pipeline already built at `pipeline.py:595` — pass it through `derived` instead of re-parsing if that's cleaner.)
- `analyze/derived/alt_key.py:85` — the `key` field there is currently a `humanize`-like form ("Bb:major" → "Bb major"). Switch to the canonicalizer so the alt block matches the spelling rule. Note: alt_key.py is fed `essentia_consensus` like `"F#:major"`; you'll need to parse it first. Reuse `parse_key` after a one-line colon-to-space normalization (the same shape as `humanizeKeyString` in `webui/static/js/music/notation.js`).
- `analyze/derived/alt_key.py:86` — already calls `scale_name(alt_key)`; this keeps working unchanged once the alt_key Key object is built canonically.
- `analyze/stages/essentia_extract.py` `compute_agreement` — the `analyze` side of the agreement block should mirror `track.key`. Currently the function reads `pipeline_summary.get("key")` — make sure it sees the canonicalized form, not the raw skey form. Easiest: canonicalize once in summary_writer.py *before* `compute_agreement` is called, then pass the updated track dict through (it's `summary["track"]` at the call site).

The cross-check `essentia_consensus` value should keep its colon form (the webui's renderer already handles it). Don't touch Essentia's output.

## What to test

Add `analyze/tests/test_key_scale_coherence.py` (or extend the existing theory tests — look for the closest neighbour). Cover:

1. **Round-trip** — for every pitch class 0..11 and both modes, `parse_key(canonical_key_name(Key(pc, mode))) == Key(pc, mode)`.
2. **Stability** — `canonical_key_name(canonical_key_name(k))` is idempotent.
3. **Spelling rule** — explicitly assert the five enharmonic minors come out flat: `canonical_key_name(Key(pc=3, mode="minor")) == "E♭ natural minor"` (and matching cases for PCs 1, 6, 8, 10). Assert all major keys come out with the sharp/natural-letter spelling.
4. **Coherence at the writer boundary** — synthesize a minimal results dict with `key="D# minor"`, call `summary_writer.write(...)`, load the resulting JSON, and assert `parse_key(track.key)` and `parse_key(analysis.scale)` yield identical `Key` objects AND that the tonic letter substring matches between the two strings (e.g. both start with "E♭"). This is the regression guard for the actual bug.
5. **Alt-key coherence** — if the run has an `essentia_agreement.key.ok == False`, the resulting `chords_alt_key.key` and `chords_alt_key.scale` parse to the same `Key`. Use `analyze/derived/alt_key.py`'s existing tests as a template.
6. **Existing tests stay green** — `analyze/tests/test_theory.py` (or wherever `scale_name` is currently tested) must not need any value-flip; you are not changing `scale_name`'s output, only making `track.key` follow the same convention.

The webui's JS tests (`webui/tests-js/notation.test.js`) should pass unchanged — the notation module operates on whatever spelling the backend hands it. If any JS test asserts a specific spelling that drifts, the test was reading the wrong layer; fix the test, not the canonicalizer.

## Cache migration

`summary.json` files in `cache/<slug>/` produced before the fix will have the old, inconsistent spellings. Two options:

- **Preferred — bump the summary schema and let staleness re-derive.** Find the summary's `SCHEMA_VERSION` constant (search for `SCHEMA_VERSION` near the summary writer or stage manifest) and bump it. The pipeline's staleness checker will mark old summaries as stale and the next analyze run rebuilds them. This is the same pattern Round 5 of the identify overhaul used — see `git log --oneline analyze/stages/identify.py` for the shape.
- **Acceptable fallback** — write a one-shot script in `scripts/` that walks `cache/*/summary.json`, re-canonicalizes `track.key` (and `analysis.scale`, and any alt-key block) in place, and exits. Document it in the script's docstring; do not run it for the user — they'll invoke it.

Either way, do **not** silently leave old caches inconsistent. Surface what you chose in the commit message.

## Boundaries

- **Don't** rewrite `scale_name`'s output, only its reach. The flat-for-minor convention is correct and already tested elsewhere; you are propagating it, not replacing it.
- **Don't** touch chord labels in `summary["chords"]`. They use mir_eval colon shorthand (`"D#:min7"`) and the webui's `formatChordShorthand` collapses that into display form. The chord *root* spelling there is a separate decision driven by lv-chordia's vocabulary; conflating the two is scope creep.
- **Don't** modify `skey.json` content. It is the model's verbatim output and useful for debugging discrepancies — canonicalize at the summary-writer boundary instead.
- **Don't** change the JS notation layer in `webui/static/js/music/notation.js` or anything that depends on it. The webui-side fix (this branch) is already complete; this prompt is exclusively backend.
- **Don't** introduce a `pyproject.toml` / `requirements.lock` / Torch pin change. This is a pure-Python logic fix.

## Deliverable

One commit on a fresh branch named `fix/key-scale-coherence`:

- `analyze/derived/theory.py` — `canonical_key_name` added (or equivalent shape).
- `analyze/writers/summary_writer.py` — `track.key` routed through the canonicalizer; `compute_agreement` sees the canonicalized form.
- `analyze/derived/alt_key.py` — alt-key block built canonically.
- `analyze/tests/<file>.py` — coherence tests (see "What to test" above).
- Cache migration: either schema bump (preferred, edit one constant) or a `scripts/migrate-key-spelling.py` one-shot.
- Commit message format: `fix(analyze): canonicalize key/scale enharmonic spelling (track.key matches analysis.scale)` — body summarises the rule and lists the schema bump or migration path.

Use `pytest analyze/tests/ -k "key or scale or theory" -x` to validate before committing. Run the pipeline once on a track that exercises sharp-vs-flat key ambiguity (e.g. Charlie Puth — Attention, in B major / Cb major depending on spelling) via `python -m analyze "$YOUR_TEST_MP3"` and confirm the new `summary.json` shows matching spellings for `track.key` and `analysis.scale`. The webui will pick up the new values on next page reload — no JS or static-asset changes required.
