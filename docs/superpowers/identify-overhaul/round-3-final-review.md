# Round 3 Final Review

**Reviewer:** R3 Pass 2 (final, independent — feature-dev:code-reviewer)
**Date:** 2026-05-12
**Commits reviewed:** `ea7ab72` (C2 silence-strip), `e0f70f8` (delta-generator)
**Verdict:** **ADVANCE TO ROUND 4** with two prerequisites (Blocker A, Blocker B)

---

## 1. Soft-fail correctness — PASS

Every failure mode was traced to its catch site:

- **ffmpeg not found:** `_detect_leading_silence` doesn't catch; propagates to `run()`'s preprocessing `except Exception` at line 239. `strip_tmp` stays None; raw path used.
- **silencedetect nonzero:** `_detect_leading_silence:106` raises `CalledProcessError`. Same catch.
- **silenceremove nonzero:** `_strip_leading_silence` uses `check=True`. Inner except at line 155 unlinks then re-raises. Preprocessing catch sets `strip_tmp = None`.
- **Disk full on temp WAV:** `OSError` from `tempfile.mkstemp` → preprocessing catch.
- **fpcalc on stripped WAV:** stripped-fallback `except Exception` (line 332) sets `match = None`. Outer `finally` still cleans up.
- **AcoustID 429 on stripped lookup:** `AcoustIDError` → same fallback catch.

**Outer `try/finally` (line 376-381):** wraps all inner blocks including raw fpcalc, raw AcoustID, stripped fallback, MB lookup, `_preserve_or_write`. Early returns from inner except blocks still trigger the finally per Python guarantee. Unlink wrapped in its own `try/except OSError` so cleanup failures don't surface. No path can crash `run()` outright.

## 2. Performance — within budget

C2 commit reports: charlie_puth probe 0.553s, ren_x_chinchilla strip 1.048s, balthazar probe 0.301s. With `-t 30` (line 96) and `-t 150` (line 139) both present, these are credible at 15-25× realtime decode. All within the < 2s budget per spec §C1 §8.

Round 3 mean wall time 43.4s/slug vs Round 2's 27.5s/slug is **NOT** comparable — different slug sets (R3 = 15 Bucket-A/B; R2 = all 30). `the_byrds` (74.5s) and `she_s_hot_tea` (56.2s) are timing outliers from AcoustID + fpcalc variance, not silence-strip overhead. `it_could_happen_to_you` (gated) ran at 26.2s while zero-silence `joesef` and `nightbus` ran at 42-43s — pattern inconsistent with strip-overhead hypothesis. The delta's flag overstates the concern.

## 3. SCHEMA_VERSION + sidecar params — all in sync

- `analyze/stages/identify.py:32` → `SCHEMA_VERSION = 3` ✓
- `analyze/stages/identify.py:33-38` → `DEFAULT_PARAMS` with 4 silence_strip_* keys ✓
- `webui/webui/stage_manifest.py:173-184` → identify entry `schema_version: 3` with matching params dict ✓
- `test_stage_manifest_in_sync.py` AST-parse drift test catches mismatch on either; uses `int` for threshold_db (literal_eval handles -50 correctly). Test is load-bearing and effective.

## 4. Round 3 delta — 0 Bucket-A clearances, evidence-supported

### Code-path verification (substitutes for missing log evidence)

All 6 gated tracks satisfy gate (`leading_sec > 0.3s` for 0.45, 0.78, 0.82, 1.49, 1.94, 6.47s leading silence values). `strip_tmp` is non-None when raw AcoustID lookup runs. All 6 returned `match = None` on raw (round-2 reasons), so the stripped fallback at `identify.py:304` fires. All 6 still show `identified: false` with reason "no AcoustID match above threshold" — confirming the stripped fallback also returned `match = None`.

### Honest analysis

The "fingerprint-not-in-DB" conclusion is INFERRED, not directly observed. The delta lacks raw AcoustID responses for the stripped fingerprints. Two possibilities are not distinguished in identify.json:
1. AcoustID returned empty `results: []` (true DB gap)
2. AcoustID returned low-score results below the 0.65 threshold

Both produce the same `reason` string. This is the load-bearing forensic gap that **Blocker B** below addresses.

### Spec-target implications

Spec projected 3-4 additional clearances; empirical 0. The 75% target (≥22/30 identified after all rounds) is unmoved — Round 3 contributes nothing. Round 4 carries all remaining load: ~9 additional identifications needed from 16 unidentified tracks.

C1's design and C2's implementation are correct. The hypothesis was reasonable; the corpus instance falsified it.

## 5. Observability bug — logging not configured (Blocker A)

`analyze/cli.py` and `analyze/__main__.py` contain ZERO logging configuration. `grep` confirms no `logging.basicConfig()`, `addHandler`, or `StreamHandler` calls anywhere in `analyze/`. All `log.info(...)` calls in `identify.py` are silently discarded at production runtime — the §4.1 structured log line never reaches `webui.log`.

Tests in `test_identify_round3.py` use `caplog` which intercepts records before handler/propagation, so they verify record CREATION but not stdout emission. The tests pass, the production code is broken.

This is a **Round 2 deferred bug** that surfaced in Round 3. It's a Round 4 prerequisite — the Round 4 delta generator faces the same gap unless fixed.

**Minimal fix (one-line):** add to `analyze/cli.py:main()` before invoking the pipeline:
```python
import logging as _logging
if not _logging.root.handlers:
    _logging.basicConfig(level=_logging.INFO, stream=sys.stderr,
                         format="%(name)s %(levelname)s %(message)s")
```
The `if not handlers` guard prevents double-configuration.

## 6. R2 fold-ins applied correctly

- `source="acoustid_unenriched"` at `identify.py:360` ✓; `_log_outcome` docstring lines 192-210 lists all four sources.
- Recording tie-break at `acoustid.py:165-168`: `lambda rd: (rd[1], rd[0].get("id", ""))` ✓; primary duration delta, secondary recording.id lexicographic.

## 7. Test quality

- `test_temp_wav_cleaned_up_after_acoustid_error` (#7): correctly tracks `created_temps` and asserts `not t.exists()` after AcoustIDError. Strong test.
- `test_log_emits_acoustid_stripped_when_stripped_match_wins` (#15): asserts both log message content AND `_fingerprint_source` not in payload. Verifies internal flag cleanup. Strong.
- `test_post_strip_duration_below_30_skips_stripped_lookup` (#14): asserts `lookups == ["RAW"]`. Correct verification of the duration guard.

One weakness: cleanup tests pass even if `unlink()` were silently swallowing OSError, because in practice `missing_ok=True` doesn't raise on extant files. Adequate for production confidence.

Integration tests gated by `@pytest.mark.skipif` on corpus MP3 presence. Duration assertions use realistic bounds accounting for `-t 150` cap.

## 8. Regression spot-checks — PASS

- `jamiroquai_everyday` (pre-existing): identify.json `identified=true`, mbid unchanged from R2 baseline. Protected by legacy bridge.
- `lou_reed_perfect_day_official_audio_9wxi4kk9zyo` (pre-existing): same.
- `the_national-graceless-jpz_guyimhw` (R2 mover): same.

All 24 pre-R3 identified caches stayed identified. Round 3 batch excluded them, so verification is code-path-based: legacy bridge synthesizes v3 sidecar without re-querying AcoustID. Bridge logic unchanged from R2.

## 9. Round 4 readiness

### Blocker A (prerequisite before D1): Logging config

One-line fix to `analyze/cli.py` per §5. Without it, the Round 4 delta generator cannot distinguish `source="fallback"` from `source="none"` in batch output. Must land before any Round 4 delta is generated.

### Blocker B (prerequisite before D1): Stripped-fingerprint AcoustID raw responses

The Round 3 delta does not contain raw AcoustID API responses for the stripped fingerprints of the 6 gated tracks. Before D1 designs the MB text-search trigger conditions, explicitly probe AcoustID with the stripped WAVs and capture the raw JSON. This decides:
- If empty `results: []` for all 6 → MB text-search must trigger on "raw AND stripped both returned nothing"
- If low-score linked results exist → MB text-search can use the AcoustID MBID as a confirmation signal (cross-check artist/title match between slug-derived guess and the AcoustID-returned recording)

### Debt R4 inherits

- `_cache_raw_acoustid` only writes on non-None match (`identify.py:296-298, 311-319`). When AcoustID returns empty on the stripped fingerprint, no cache artifact is written. R4 should write `.acoustid_stripped_raw.json` even on empty results for forensic completeness.
- `reason="no AcoustID match above threshold"` is ambiguous (empty results vs below-threshold results). R4 should split into `reason="acoustid_no_results"` vs `reason="acoustid_below_threshold"` to give MB text-search the correct trigger condition.
- The `source="acoustid_unenriched"` path (AcoustID matched, MB failed) leaves `identified=false`. R4's MB text-search should use the AcoustID MBID directly here, bypassing text-search.

## 10. Recommendation: ADVANCE TO ROUND 4

C2's Round 3 implementation is correct. All error paths soft-fail. Outer `try/finally` correctly placed. SCHEMA_VERSION=3 in sync. R2 fold-ins applied. 22 tests with adequate-to-strong coverage. Zero regressions.

The 0 Bucket-A clearances are not a code defect — silence-strip executed; AcoustID simply doesn't have these tracks. C1's honest ceiling estimate (3-4 IF in DB) held: the tracks aren't in the DB.

Round 4 scope (in priority order):
1. **Fix Blocker A** (logging.basicConfig in analyze/cli.py) — 1-line fix, prerequisite
2. **Address Blocker B** (capture stripped-fingerprint raw responses) — feeds D1 design
3. **D1 design**: MusicBrainz text-search fallback (slug → artist/title → MB search → duration confirmation → `source="fallback"`)
4. **D2 implementation**: backend changes (identify.py fallback path, new musicbrainz.py search_recordings wrapper)
5. **D3 UI changes**: Metadata card trust signaling (italic "via text-match search" note)
6. **R4 final review**: gemini-cli:gemini second opinion per spec §R4

75% target (23/30) needs ~9 additional identifications from 16 remaining unidentified tracks. The `_fragments-round2` data shows most have parseable artist/title in slug names. MB text-search is the correct mechanism and the load is achievable.
