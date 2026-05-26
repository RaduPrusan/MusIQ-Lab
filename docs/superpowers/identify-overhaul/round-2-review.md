# Round 2 Review — Identify Pipeline Overhaul

**Reviewer:** R2 (independent, code-review)
**Date:** 2026-05-12
**Scope reviewed:** B1 commit `baa991b`, B2 commit `90d60be`, the R1 prioritized fix list (`round-1-review.md`), and current state of `analyze/clients/acoustid.py`, `analyze/stages/identify.py`, `analyze/sidecar.py`, `webui/webui/stage_manifest.py`, `webui/tests/test_identify_round2.py`.

Verdict up front: **ADVANCE TO ROUND 3** with three minor follow-ups that do not block (see §7).

---

## 1. B1 deviations — verdict per (D1–D4)

### D1. Sidecar docstring expanded into module docstring (lines 1–22) instead of just lines 8–12 — **ACCEPT**

The module docstring at `analyze/sidecar.py:1-19` now lists four bump triggers (param defaults, param semantics, sidecar format, client picking logic) AND documents the atomic-write contract with the same-dir tmp + NTFS WinError 17 warning. Placing the atomic-write contract in the module docstring rather than confined to the `write()` docstring is the right call: the constraint applies equally to anyone who adds a new write site to this module in the future, not just to current callers of `write()`. The bump-trigger list is also more discoverable at module-top. The information is duplicated lightly in `write()`'s docstring (lines 42–47) which is fine — module docs explain the why, the function docs explain the how.

### D2. `raw_response` stripped from on-disk `identify.json` and only cached in `.acoustid_raw.json` — **ACCEPT**

This is the right split. Two reasons:

1. The `raw_response` payload is typically 1–4 KB of JSON per track. Keeping it inside `identify.json` would inflate the on-disk size of an otherwise ~400-byte payload by 5–10×, hurting the readability of the file that's actually surfaced to operators (it's the canonical "did we identify this" artifact).
2. The split is cleanly implemented: `acoustid_client.lookup()` returns it in the dict, `_cache_raw_acoustid()` writes the sidecar atomically, and `run()` then strips the key before calling `_preserve_or_write()` (identify.py:161-165). Round-trip is a single read of two files, both same-directory.

If a future stage needs both, it can read both. The on-disk size win matters more than the read ergonomics.

### D3. `source=none` when AcoustID succeeded but MB failed — **REVISE (minor)**

`analyze/stages/identify.py:180-183` logs `source=none score=<acoustid_score> mbid=<acoustid_mbid> reason="MusicBrainz error: ..."`. The spec §4.1 specifies `source=acoustid|fallback|none`. There is a legitimate argument either way:

- For `source=none`: the *output* (identify.json) shows `identified=false`, so from the consumer's perspective nothing was identified. The score+mbid in the log are debugging metadata for the operator.
- For `source=acoustid`: AcoustID actually returned a match. The failure mode is downstream (MB enrichment), which is operationally different from "AcoustID had nothing." Operators grepping `webui.log` for `source=none` to find "AcoustID gap" tracks will get false positives if MB-503 outages are mixed in.

Recommendation: **introduce a fourth value, `source=acoustid_unenriched`**, or keep `source=acoustid` but add a distinct `mb_error=<bool>` token to the log line. Either is better than overloading `none`. Because the spec already calls out that the existing `identify-retry.*` script filters by reason substring, the operational difference matters. A log-line-only change has no schema impact and can land in Round 3 alongside the silence-strip work.

The current behavior is internally consistent (MB-failed tracks become `identified=false` for *all* purposes), so this is REVISE-LATER, not block-Round-2.

### D4. `RETRY_BACKOFF_SEC` exposed as module-level constant — **ACCEPT**

`acoustid.py:22` exposes `RETRY_BACKOFF_SEC = [1, 4, 9]`. This is defensible: tests can monkeypatch it to `[0, 0, 0]` to avoid 14 s of dead time in CI; operators tuning a corpus-wide reanalyze can override it. The "public surface" concern is theoretical — the module is internal to `analyze.clients`, not exported from the package's top-level `__init__.py`, and the constant is documented in a comment. The alternative (hardcoding) costs more in test latency than the marginal API surface costs in maintenance.

---

## 2. Code spot-checks

### Walker fix — `analyze/clients/acoustid.py:119-145`

Exact loop:

```python
results = data.get("results") or []
if not results:
    return None

sorted_results = sorted(
    results, key=lambda r: r.get("score", 0.0), reverse=True
)
chosen = None
for r in sorted_results:
    score = r.get("score", 0.0)
    if score < min_score:
        break  # sorted descending — nothing further will pass
    recordings = r.get("recordings") or []
    if not recordings:
        log.debug(...)
        continue
    chosen = r
    break

if chosen is None:
    return None
```

- `results == []` → early return at line 121. Correct.
- Single result with `score >= threshold` AND `recordings = []`: enters the `if not recordings` branch, logs, `continue`. Loop exhausts. `chosen is None` → `return None`. Correct.
- High-score linked: chosen on first iteration. Correct.
- Bucket-C case [0.98 unlinked, 0.95 linked]: first iteration skips, second iteration picks. Correct (confirmed by `test_walker_returns_second_result_when_first_unlinked`).
- The descending-sort + threshold `break` is sound; no need to walk the tail.

One implementation nitpick (non-blocking): the inner `recordings` variable is re-computed at line 147 (`recordings = chosen.get("recordings") or []`). The walker already extracted it. Cheap and not load-bearing — leave alone.

### Recording-by-duration selector — `acoustid.py:147-165`

Tie-break determinism. `min(candidates_with_dur, key=lambda rd: rd[1])` returns the FIRST element with the minimum value when multiple are tied (Python's `min` is stable in iteration order). So for `fp["duration"] = 200.0` with recordings `[199.5, 200.5]`: deltas are `[0.5, 0.5]`. Python's `min` returns the first encountered. `recordings` is taken from `chosen["recordings"]` which is whatever AcoustID returned, in whatever order. AcoustID's API does not guarantee a stable ordering of `recordings` within a result (the spec is silent on it). So across runs, if AcoustID re-orders the recordings, the tie-break could flip.

**Severity: low.** The 1 s delta on a 200 s track is well within MusicBrainz duration drift, and the chosen recording is one of two genuine recordings of the same track (think album vs single edit at the same length). Both MBIDs map to the same canonical artist/title via MB. A truly defensive implementation would tie-break by recording `id` lexicographically as the second key; recommend adding this in Round 3:

```python
chosen_rec = min(candidates_with_dur, key=lambda rd: (rd[1], rd[0].get("id", "")))[0]
```

Non-blocking for Round 2.

### Atomic write in `_preserve_or_write` — `identify.py:198-206`, `:223-234`

The helper `_atomic_write_text(path, text)` at line 198 does:

```python
tmp = path.with_suffix(path.suffix + ".tmp")  # path/identify.json → path/identify.json.tmp
tmp.write_text(text)
os.replace(tmp, path)
```

- `tmp.parent == path.parent` — confirmed: `Path.with_suffix` only changes the suffix component, not the directory. Same NTFS volume.
- Stem: `identify.json.tmp` (suffix appended, not replaced) — a stale `.tmp` next to `identify.json` after a crash is recoverable / visually obvious.

`test_preserve_or_write_tmp_is_same_dir` (test file lines 266-284) verifies this with a real `os.replace` capture. Solid.

`test_preserve_or_write_atomic` (lines 240-263) verifies the F9 catastrophe scenario: seeds an identified=true cache, patches `os.replace` to raise mid-write, asserts the original `identify.json` is byte-identical afterward. This is exactly the test the spec demands. The assertion `(cache_dir / "identify.json").read_text() == original_text` is sound — it doesn't just check `identified=true`, it checks the entire file is unchanged.

### Atomic write in `sidecar.py` — `analyze/sidecar.py:41-54`

```python
path = _sidecar_path(cache_dir, stage)  # → cache_dir / ".params_identify.json"
path.parent.mkdir(exist_ok=True, parents=True)
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
os.replace(tmp, path)
```

For stage `identify`, `_sidecar_path` returns `cache_dir / ".params_identify.json"` (line 38). `path.with_suffix(".json.tmp")` produces `cache_dir / ".params_identify.json.tmp"`. Same directory. ✓

One subtle anchor check on `with_suffix`: the file name is `.params_identify.json`. Python's `Path.with_suffix(".tmp")` on this path → `.params_identify.tmp` (replacing `.json`). But the code is `path.with_suffix(path.suffix + ".tmp")` → `path.with_suffix(".json.tmp")` → `.params_identify.json.tmp`. Correct chained-suffix idiom.

`test_sidecar_write_atomic` (test_identify_round2.py:287-302) captures the `os.replace` call and asserts both `src.parent == dst.parent` and `dst.name == ".params_identify.json"`. The src filename isn't explicitly checked but the parent check is sufficient for the NTFS guarantee.

### SCHEMA_VERSION dual bump

- `analyze/stages/identify.py:30` → `SCHEMA_VERSION = 2` ✓
- `webui/webui/stage_manifest.py:174` → `"schema_version": 2` ✓

Drift test at `webui/tests/test_stage_manifest_in_sync.py:102-118` walks every entry in STAGES, parses the source file via `ast.literal_eval`, and compares. With both at 2, the test passes. The test is robust against import-platform mismatch (uses AST, not import).

### Legacy-cache bridge — `identify.py:42-61`

The code path: `identify.json` exists, `sidecar.matches(...)` returns False (sidecar absent OR schema_version mismatch OR params drift), `existing` is parsed JSON, `existing.get("identified") is True` → `sidecar.write(cache_dir, "identify", p, schema_version=SCHEMA_VERSION)` and return True.

- `p` is `{**DEFAULT_PARAMS, **params}` — `DEFAULT_PARAMS = {}`. Caller passes no kwargs in normal use. So `p == {}`.
- A fresh identify run also uses `p = {**DEFAULT_PARAMS, **params} == {}`.
- **Therefore params hashes match.** A re-run of `python -m analyze --stages identify` against a legacy `identified=true` cache will: cached() bridge synthesizes sidecar at v2/`{}`, returns True, run() is not invoked, no AcoustID quota burned.

I verified this against the live state. `cache/leonard_cohen_in_my_secret_life/.params_identify.json` still shows `schema_version=1` (it hasn't been touched since R1). On next analyze of that slug, the bridge will trigger: `matches()` returns False (1 ≠ 2), `existing.identified` is True → bridge synthesizes a v2 sidecar with `{}`. `identify.json` itself stays untouched.

`test_legacy_cache_synthesizes_sidecar` (test_identify_round2.py:313-330) and `test_legacy_cache_bridge_does_not_synthesize_for_identified_false` (333-341) cover both branches correctly.

**One non-blocking concern.** If a future Round 3 introduces new `DEFAULT_PARAMS` (e.g. `silence_strip_threshold_db`), the bridge will synthesize a sidecar containing those new defaults onto a cache that was originally identified under different (or no) preprocessing. This is acceptable as long as the bridge only fires when `identified=True` (the existing match is presumed canonical), but it should be documented in Round 3's bridge update. Worth a note in the Round 3 prompt.

### `_write` bypass

`identify.py:237-242` defines `_write(cache_dir, payload, params)` which calls `_atomic_write_text` and `sidecar.write` — both now atomic. R1's D4 concern is addressed: there's no remaining non-atomic write path in this module.

Grep confirms `_write` is referenced only from `tests/unit/test_identify_stage.py` (5 fixture calls). Not used by production code. The function exists as a test-friendly affordance, and tests will benefit from the same atomic guarantee.

---

## 3. Regression spot-checks

Checked 3 pre-existing identified-true caches NOT in the 30-track corpus:

| Slug | `identified` | MBID | Sidecar |
|---|---|---|---|
| `jamiroquai_everyday` | true | `b817cffd-1d5c-4905-90a4-8f9e8367a14a` | `schema_version=1` (legacy, bridge-eligible) |
| `leonard_cohen_in_my_secret_life` | true | `3b26072c-426e-41d8-8498-037a4e95bfb7` | `schema_version=1` (legacy, bridge-eligible) |
| `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` | true | `8d74e3f5-3e94-4d6f-bff2-66883f906999` | `schema_version=2` (was re-run in Round 2 — it IS in the corpus) |

Note: my original third pick (`gorillaz_silent_running`) is in the corpus, contrary to the prompt. Substitute observation: the cache was successfully bumped to v2 via the production run, NOT via the legacy bridge — exercising the "happy path" of the new code rather than the legacy path. Both jamiroquai and leonard_cohen are correctly untouched, sidecar will be upgraded by bridge on next analyze.

**Regression gate verdict: PASS.** No `identified=true → false` transitions on the 10 baseline-true caches.

**Caveat on the gorillaz cache.** The cache shows `title="Silent Running" / artist="DJ Allan McLoud" / release="100% Eurotrance 3"` at score 0.99. This is almost certainly a misidentification — the YouTube source is "Gorillaz ft. Adeleye Omotayo" per the slug. This is NOT a regression caused by Round 2; it's an AcoustID-side data quality issue (someone submitted a fingerprint of the Gorillaz track linked to the wrong MB recording, or the fingerprints collide). The walker change cannot fix this — only one result is involved and it's linked. Flagging it because the spec mentions Gorillaz in §1 examples and a future round may want to add a confirmation step (e.g. compare slug-derived artist to MB artist with a soft match). Bump to Round 4 / Round 5 as a "trust signal" enhancement, not a Round 2 blocker.

---

## 4. Test suite quality

**F9 atomicity coverage — sound.**

`test_preserve_or_write_atomic` (test_identify_round2.py:240-263) is the load-bearing test. The assertion structure:

1. Write a known-good identified=true cache via the production path.
2. Snapshot `identify.json` text.
3. Patch `os.replace` to raise `OSError("simulated rename failure")`.
4. Call `_preserve_or_write` with a different identified=true payload.
5. Expect the call to raise `OSError`.
6. Re-read `identify.json`; assert byte-identical to the snapshot.

This is the right shape. It exercises the FULL contract: the temp file may have been written, but the canonical file is not corrupted. If a future refactor moves the write into a `try/except` that swallows the rename failure, this test catches it. If a future refactor changes the write order (rename then write?), this test catches it. If someone replaces `os.replace` with a non-atomic `shutil.move`, this test would still pass — that's a small gap, but the existing `_capturing_replace` test catches accidental replacement of the atomic primitive.

One additional assertion I'd add (Round 3 polish, non-blocking): after the failure, scan the cache_dir for stray `.tmp` files and assert either zero or one. Currently a crash leaves `identify.json.tmp` orphaned. Not a correctness issue (it doesn't corrupt anything), but a janitorial nice-to-have for future tooling.

**Coverage gaps to call out:**

- No test for the `sidecar.write` atomicity under simulated `os.replace` failure (we have `test_sidecar_write_atomic` which only captures the call, not the crash recovery). The same F9-style crash test should exist for sidecar. Not blocking — the sidecar is less catastrophic to corrupt because the sidecar's contents are reconstructable.
- No test for the "all results below threshold AND linked" case. Covered implicitly by `test_walker_respects_threshold` but with an unlinked-first ordering. The pure case `[0.40 linked, 0.30 linked]` is not exercised. Not blocking — the walker logic treats them identically.
- No test for the `_log_outcome` `source=none score=... mbid=...` D3 case (AcoustID succeeded, MB failed). Bundle with the D3 revision.

Overall test quality is high. All new tests are deterministic (no real network, no real subprocess except the binary presence check, no time-dependence except a `queried_at` value that's only checked for key presence).

---

## 5. Pre-existing `test_paths.py` failure — recommendation

`webui/tests/test_paths.py:7-10` asserts `root.name == "MusIQ-Lab"`. Worktree directory name is `identify-overhaul`. The test fails in any worktree.

**Recommendation: (b) loosen the test to check git toplevel rather than directory name.**

Rationale:
- (a) "skip in worktrees" with a marker is fragile — what's a worktree to a test? Detecting via `.git` being a file vs a directory works but is obscure. Easy to break with a refactor.
- (b) The actual invariant the test is trying to enforce is "the resolved project root is the one git considers the repo root," not "the user happened to name the directory MusIQ-Lab." Comparing against `git rev-parse --show-toplevel` (or reading `.git/HEAD` upward) captures the real intent and works in both worktrees and the main checkout. It also handles the edge case where a user clones the repo into a directory named anything else.
- (c) "leave alone" creates an ongoing tax: every worktree-based contributor sees a red test and has to context-switch to understand why. The branching workflow memory note (`branching_workflow`) says the user doesn't usually use worktrees here, but the identify overhaul is explicitly running in one — this is a real workflow now.

Implementation sketch (not to be done in this round, just to make the recommendation concrete):

```python
import subprocess
toplevel = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True
).strip())
assert root.resolve() == toplevel.resolve()
```

Defer to the Round 3 housekeeping batch. Do not gate Round 2 on it — it's pre-existing.

---

## 6. R1 open questions A/B/C/D — Round 3/4 owners

### A. Bucket-A zero-silence root cause (fpcalc version vs submitter version) — **OPEN, Round 3 owner**

Not addressed in Round 2. The B2 delta correctly shows 0/11 Bucket-A tracks identified. The root cause investigation (run `fpcalc -version`, check Chromaprint vendor version vs current AcoustID submitter median, possibly bump the vendored binary) belongs in Round 3 alongside silence-strip preprocessing. Specifically: if fpcalc 1.5.x produces fingerprints that don't match the AcoustID DB's 1.5.6+ submissions, silence-strip alone will not rescue these tracks regardless of trim quality. The Round 3 C1 design doc must include a "verify fpcalc version" step before designing the silence-strip ffmpeg pipeline.

### B. Balthazar may not exist in AcoustID DB — **OPEN, Round 4 owner**

Round 2 did not check whether AcoustID has ANY fingerprint for Balthazar's "Changes" video. The B2 delta confirms it remains `no AcoustID match above threshold`. This is exactly the scenario MB text-search fallback (Round 4) is designed to address. The Round 4 D1 design should explicitly include Balthazar in the test corpus and validate that the slug-to-artist/title parser handles "balthazar-changes_official_video-p3jb998acqo" cleanly. No additional Round 3 work needed for this slug.

### C. Observability gap (transient vs code bug) — **ADDRESSED, Round 2**

The new `identify: slug=... source=... score=... mbid=... reason=...` log line at `identify.py:97-107` is emitted on every code path that returns from `run()`. Verified via `test_structured_log_emitted_on_failure` and `test_structured_log_emitted_on_success`. The B2 delta confirms it fired for 30/30 corpus slugs. This satisfies §4.1.

Minor gap (Round 3 polish): the log line currently elides retry attempts. If AcoustID 5xx'd twice before succeeding, the success line doesn't say so. For operators debugging transient-vs-persistent gaps, adding `attempts=<int>` to the log line would help. Non-blocking.

### D. `_write` bypass coverage — **ADDRESSED, Round 2**

As noted in §2, `_write` calls `_atomic_write_text` and `sidecar.write` — both atomic. The bypass function name is misleading (it bypasses *preservation*, not *atomicity*) but the safety property holds. The function is only referenced from `tests/unit/test_identify_stage.py`, so production callers cannot accidentally bypass the F9 fix.

---

## 7. Recommendation — **ADVANCE TO ROUND 3**

The Round 2 deliverables match R1's prioritized list 1-for-1. All four B1-reported deviations are minor; D1, D2, D4 are accepted as designed, D3 should be revised but is non-blocking and can fold into Round 3's logging work. Atomicity is correctly implemented and well-tested. The corpus moved 0/30 → 14/30 with zero regressions on the 10 baseline-true caches. The structured log fires on every code path.

### Round 3 scope (from R1 + this review)

Start from R1's existing Round 3 design (silence-strip preprocessing). Add:

1. **Pre-design step:** verify the vendored `fpcalc` version against current AcoustID submitter Chromaprint version (R1 OQ-A). If they're materially out of phase, bump the vendored binary FIRST and re-run the corpus probe — silence-strip may have near-zero impact on commercial Bucket-A tracks if the fingerprint algorithm itself is mismatched.
2. **D3 log refinement:** introduce `source=acoustid_unenriched` (or equivalent) for the AcoustID-succeeded-but-MB-failed case. Add a test.
3. **Tie-break determinism in recording selector** (minor, optional): add `recording.id` as the secondary sort key in `_dur_delta`'s `min()` to make the selection reproducible across AcoustID response permutations.
4. **Bridge documentation:** if Round 3 introduces new `DEFAULT_PARAMS` for silence-strip, the legacy-cache bridge in `identify.py:42-61` will synthesize a sidecar with those new defaults onto pre-Round-2 identified-true caches. Document this in the Round 3 design (decision: it's safe because the bridge only triggers when `identified=True`).
5. **test_paths.py fix:** loosen to `git rev-parse --show-toplevel` comparison so worktree development doesn't trip the test (R1 housekeeping carryover).
6. **F9 polish (optional):** stray `.tmp` file scan after crash in atomicity test; sidecar F9 crash test.

### Files relevant to this review

- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/analyze/clients/acoustid.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/analyze/stages/identify.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/analyze/sidecar.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/webui/webui/stage_manifest.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/webui/tests/test_identify_round2.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/webui/tests/test_stage_manifest_in_sync.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/webui/tests/test_paths.py`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/cache/jamiroquai_everyday/identify.json`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/cache/leonard_cohen_in_my_secret_life/identify.json`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/cache/gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg/identify.json`
