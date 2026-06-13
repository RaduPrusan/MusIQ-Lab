---
title: Investigation — 5 failing identify/acoustid unit tests
updated: 2026-06-13
status: research
description: Root-cause analysis of 5 pre-existing tests/unit failures (test_acoustid_client, test_identify_stage) surfaced during the key/scale coherence work. All five are stale tests lagging the May 2026 Round-5 identify overhaul; no code bugs. Includes two design/coverage observations.
---

# Investigation: 5 failing identify/acoustid unit tests

## Context

Surfaced while running the full `tests/unit` suite to verify the key/scale enharmonic-coherence work (`2026-06-13-key-scale-enharmonic-coherence.md`). Result: **530 passed, 5 failed**. The 5 failures are causally independent of the coherence work — `identify.py`/`acoustid.py` and their tests import none of the changed modules (`theory`, `summary_writer`, `alt_key`). Verified by grep.

Investigated with `superpowers:systematic-debugging` (root cause before fixes).

**Git note:** all four files last changed in `fc51678 chore: release v1.0.0` — the public repo is a squash of the 412-commit dev history (dev tip preserved under tag `pre-public-squash-2026-05-26`). So `git log`/`bisect` can't date the breakage on the public repo; the determination rests on reading current code against current test expectations.

## Verdict

**All 5 failures are stale tests, not code bugs.** Each asserts pre-overhaul behavior; the production code reflects the intentional, documented May 2026 Round-5 identify overhaul (artist-plausibility gate, MB text-search fallback + new reason taxonomy) and a deliberate AcoustID retry-count widening. The `ffmpeg ... exit 234` warnings in the logs are a red herring — the code logs them and falls back to the raw file, then continues.

---

## Cluster A — `test_acoustid_client.py::test_retries_exhausted_raises`

**Symptom:** `AssertionError: Regex 'after 3 attempts' did not match Input 'HTTP 503 after 4 attempts: still down'`.

**Root cause:** `acoustid.py:24` sets `RETRY_5XX_MAX_ATTEMPTS = 4  # initial + 3 retries` (with backoff `[1,4,9]` = 14 s, documented as "headroom for a corpus-wide reanalyze"), and the raise (`acoustid.py:184`) interpolates that constant → "after 4 attempts". The test (`:108`) and its docstring still say "3 attempts". The sibling `test_retries_on_5xx_then_succeeds` passes because it's compatible with either count.

**Classification:** Stale test. The retry policy was deliberately widened 3→4; only this assertion + docstring weren't updated.

**Fix:** update `match="after 3 attempts"` → `"after 4 attempts"` and the docstring "All 3 attempts" → "All 4 attempts". Test-only.

---

## Cluster B1 — artist-plausibility gate rejects junk-slug fixtures

**Tests:** `test_run_writes_identify_json` (assert False is True), `test_run_overwrites_cached_identified_with_new_identified` (KeyError 'title' — returned dict is a reject payload with no title).

**Symptom (log):** `artist-plausibility gate REJECTED canonical match … identified='Artist' vs slug='' sim=0.25 (mode=title_fallback)`.

**Root cause:** Round-5 added `_artist_plausibility_check` (`identify.py:206`), wired into the canonical AcoustID path (`identify.py:665-718`). When the slug-derived artist/title diverges from the MB-identified artist/title (similarity < threshold), it **deliberately demotes** to `{identified: False, reason: "acoustid_artist_mismatch", source: "none", match_method: None}`, bypassing `_preserve_or_write` (it's an integrity decision, not a transient error). The tests use a pytest tmp dir as the cache/mp3 path, so the slug parser yields a gibberish title (`test_run_writes_identify_json` / `fake`) with no artist; title-fallback mode compares it against the mocked `"Artist" "Track"` → sim 0.25–0.27 < 0.30 → REJECT.

The gate fails *open* only on exceptions (`:310-314`) or when the slug has no title at all (`:292-293`). A *non-empty junk* title that mismatches is rejected by design.

**Classification:** Stale tests. They predate the gate and verify the *write/overwrite* behavior, not the gate. Their fixtures don't provide a slug whose derived artist/title resembles the mocked MB metadata.

**Fix:** in these two tests, `monkeypatch.setattr(identify, "_artist_plausibility_check", lambda *a, **k: (True, {}))` so they exercise the write/overwrite path they're actually about. (Naming the cache dir plausibly is brittle — test #3's MB artist is `"A"`, below the 4-char substring-rescue floor.)

---

## Cluster B2 — soft-fail reason taxonomy changed

**Tests:** `test_run_soft_fails_below_score_threshold`, `test_run_overwrites_cached_unidentified_with_new_unidentified`.

**Symptom:** expected `{"identified": False, "reason": "no AcoustID match above threshold"}`; got `{"identified": False, "reason": "fallback_no_match", "match_method": None, "source": "none"}`.

**Root cause:** Round-4/5 added the MB text-search fallback (`_attempt_mb_text_search_fallback`, `identify.py:390`). When AcoustID returns no match, `run()` now invokes the fallback; with the junk slug there's no usable title seed, so it returns `(None, "fallback_no_match")` (`:414`) — short-circuiting *before* any network call. The final outcome dict gained `match_method`/`source` fields and the reason string changed.

Why the sibling "does-not-demote-on-no-match" test (`:169`) still passes: it seeds a cached `identified=True` payload, so `_preserve_or_write` preserves it regardless of the fallback miss. B2's tests have a fresh / `identified=False` cache, so the new fallback reason surfaces.

**Classification:** Stale tests. The new reason taxonomy + fields are the intended post-overhaul shape.

**Fix:** update the expected dict/reason to `"fallback_no_match"` and include `match_method: None, source: "none"` (or assert the subset that matters).

---

## Secondary findings (not failures — flag to maintainer)

1. **Coverage gap:** `_artist_plausibility_check` — a load-bearing *integrity* feature that can flip `identified` to False — has **no dedicated unit test** in the public suite (`test_identify_stage.py` has none; only run-level tests exercise it incidentally). Recommend adding direct tests for: artist-mode pass/reject, substring rescue, title-fallback pass/reject, fail-open on no-slug-title, fail-open on exception. This also lets B1's run-level tests legitimately monkeypatch the gate.

2. **Design observation (not a bug):** the gate demotes a *high-confidence* AcoustID fingerprint match (0.94–0.99) when the slug is uninformative (e.g. a generic YouTube title or `track01.mp3`) and its title doesn't fuzzy-match the true artist/title. This is a deliberate false-negative trade-off the overhaul chose to prevent AcoustID-DB mislink false-positives (the gorillaz→"DJ Allan McLoud" case). Worth the maintainer's awareness: real tracks with non-descriptive slugs + strong fingerprints will land at `identified=False, reason=acoustid_artist_mismatch`. Tuning lever: `artist_plausibility_title_fallback_threshold` (default 0.30).

## Recommended action

Test-only changes (5 assertions across 2 files) + optionally a new `test_artist_plausibility.py`. Zero production-code change. Low risk. The behavior the tests will be updated to match is the documented, shipped Round-5 design.
