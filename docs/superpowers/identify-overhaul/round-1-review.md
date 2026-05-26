# Round 1 Review — Identify Pipeline Overhaul

**Reviewer:** R1 (independent, subagent_type=feature-dev:code-reviewer)
**Date:** 2026-05-12
**Sources read:** spec §§1–8, corpus doc, A1 static analysis, A2 corpus probe (md + json), A3 key audit, plus direct read of `analyze/stages/identify.py`, `analyze/clients/acoustid.py`, `analyze/clients/musicbrainz.py`, `analyze/sidecar.py`, `webui/webui/identify.py`, `webui/webui/stage_manifest.py`, `webui/tests/test_stage_manifest_in_sync.py`, and `cache/jamiroquai_everyday/identify.json`.

---

## 1. Validation

### A1 Spot-checks

**F9 — `_preserve_or_write` non-atomic (confirmed, severity upheld, fix scope needs clarification)**

Confirmed real at `analyze/stages/identify.py:108`. The write is:

```python
path.write_text(json.dumps(new_payload, indent=2))
sidecar.write(cache_dir, "identify", params, schema_version=SCHEMA_VERSION)
```

`sidecar.write` at `analyze/sidecar.py:39` also does `path.write_text(...)` — non-atomic. Both files are written in sequence without any locking or temp-file dance.

A1's proposed fix (`os.replace` from a `.tmp`) is correct in principle. However, A1's own open question 1 raises a real constraint: the worktree is at `<PROJECT_PATH>` which is an NTFS volume. `os.replace` on NTFS is atomic for same-volume renames (documented Win32 guarantee via `MoveFileEx`), but the `.tmp` file must be created on the same volume as the destination. If anyone writes `.tmp` to a `tempfile.mkstemp()` default (which defaults to the OS temp dir, potentially `C:\Users\<you>\AppData\Local\Temp\` — a different volume from `F:\`), the rename will fail with `OSError: [WinError 17] The system cannot move the file to a different disk drive`. The fix must explicitly place the `.tmp` in the same directory as `identify.json`. The test should assert this.

One additional wrinkle A1 did not mention: `sidecar.write` also does a non-atomic write, and it is called both inside and outside `_preserve_or_write` (see `_write` at line 118). A complete fix must cover both callsites.

**F11 — SCHEMA_VERSION duplication (confirmed, refactor recommendation warranted)**

Confirmed both locations exist:

- `analyze/stages/identify.py:26` — `SCHEMA_VERSION = 1`
- `webui/webui/stage_manifest.py:174` — `"schema_version": 1` (inside the `"identify"` entry of `STAGES`)

The drift-prevention test exists at `webui/tests/test_stage_manifest_in_sync.py:102` (`test_manifest_schema_versions_match_source`). That test uses `ast.literal_eval` to parse the source file — it does NOT import the module, so it works on Windows. This is a robust guard.

However, A1's recommendation to "refactor the manifest to import SCHEMA_VERSION directly" is blocked by a documented design constraint: `webui/webui/stage_manifest.py:4-7` explicitly states that `analyze.*` refuses to import on Windows Python 3.13. The AST-parse approach is the intentional workaround. Therefore the right answer for Round 2 is NOT to eliminate the duplicate but to ensure Round 2's prompt explicitly lists both locations as a two-item checklist, and to verify the drift test runs in CI before merging. A1's "RuntimeError at startup" suggestion is also blocked because `stage_manifest.py` imports on Windows where `analyze.*` cannot be imported.

The schema version bump cadence open question (A1 OQ3) has a clear answer: bump for every behavioral change, not just schema shape changes. The sidecar.py docstring at lines 8–12 only lists three cases (param defaults, param semantics, sidecar format) and does not include "picking logic changes." This is a documentation gap that should be fixed in Round 2 alongside the version bump.

**F5 — fpcalc JSON `KeyError` bypasses soft-fail (confirmed, severity confirmed)**

Confirmed at `analyze/stages/identify.py:53-54`:

```python
data = json.loads(result.stdout)
return {"fingerprint": data["fingerprint"], "duration": float(data["duration"])}
```

The caller at line 61 catches `(FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired)`. A `KeyError` from `data["fingerprint"]` or a `json.JSONDecodeError` from truncated stdout would propagate uncaught, bypassing `_preserve_or_write`. This is a real crash path confirmed by reading the code.

**F3 — `httpx.Client` inside retry loop, transient errors bypass soft-fail (confirmed)**

Confirmed at `analyze/clients/acoustid.py:53-55`. The `httpx.Client` is constructed anew on each of the three retry iterations. More critically, `httpx.ConnectError`, `httpx.ReadError`, `httpx.TimeoutException`, and similar transport-layer errors are raised by `client.get(ENDPOINT, params=params)` but the surrounding `for` loop only catches nothing — they propagate directly to `identify.run()`, which catches only `acoustid_client.AcoustIDError`. Any such transport error will crash the identify stage, bypassing `_preserve_or_write`.

### A2 Spot-checks

**Warhaus Bucket-D classification (confirmed correct)**

From the raw JSON at lines 399–428:

- `acoustid_results[0]`: score=0.98401237, recording_count=0, recordings=[]
- `acoustid_results[1]`: score=0.95058674, recording_count=1, recordings=[{mbid: "8feaaf3e-8c7c-4d57-9503-298a56b1c920", title: "Love's a Stranger", artists: ["Warhaus"]}]

This exactly matches the spec's §1 Bucket-C description (A2 relabeled this "Bucket D" per their framework, which is equivalent). The second result at score 0.951 clears both the current 0.85 threshold AND the proposed new 0.65–0.70 threshold. Current code's `max(results, key=score)` picks result[0] (score 0.984), finds no recordings, returns None. The fix is proven to unblock this track with no threshold change required.

**Moderat Bucket-B classification (confirmed, with a nuance)**

From the raw JSON: both AcoustID results have `recordings: []` (counts 0). Score 0.938 for the top result, 0.654 for the second. Neither is linked to a MB recording. A2's Bucket-B classification ("high-score unlinked, no linked alt") is correct. This track will NOT be rescued by the Bucket-C walking fix alone; it requires Round 4 MB text-search fallback. A2's fix-path assignment is accurate.

One nuance A2 did not surface: `moderat-reminder_official_video-cjwsnuoazug` has a second AcoustID result at score 0.654 — which is above A2's recommended new threshold floor of 0.65 but also unlinked. After the threshold recalibration, this result would still return None because there are no recordings on either result. So the recalibration alone does not introduce a false-positive risk for this track (it would still correctly return None).

**Balthazar Bucket-A classification (confirmed, but leading silence is 0.00s — silence-strip won't help)**

From the raw JSON: `balthazar-changes_official_video-p3jb998acqo` has `acoustid_results: []`, `leading_silence_sec: 0.0`. The spec lists this as a "should easily identify" commercial release. With zero leading silence and zero AcoustID results, silence-strip preprocessing (Round 3) will not rescue this track. The Chromaprint fingerprint simply isn't in the AcoustID database for this YouTube upload. This track is more likely a Round 4 MB text-search candidate. A2's notes column for this slug is blank — it should have flagged the 0.00s silence + Bucket-A combination as a Round 3 non-candidate. This is a minor analysis gap (the Bucket-A description says "leading silence OR fingerprint not in DB"), but it inflates Round 3's expected impact.

The same issue applies to: `joesef_comedown_official_video_zaprrzdhyiw` (0.00s), `nightbus-angles_mortz_official_video-igxitfxkd1i` (0.00s), `olivia_dean_dive_acoustic_yylsa4m2zzm` (0.00s), `she_s_hot_tea-p_3xutn8res` (0.00s). Five of the 11 Bucket-A tracks have zero leading silence. These are not silence-strip candidates; they are fingerprint-not-in-DB tracks. Round 3 will rescue at most 6 of 11 Bucket-A tracks (those with detectable silence), and empirically the most commercially likely ones are `balthazar` (0.00s — Round 3 miss), `charlie_puth` (0.45s — marginal), `ren_x_chinchilla` (6.47s — strong candidate). The spec's §2 goal of "identify charlie_puth_attention via canonical AcoustID path after silence-strip" should be revisited against this data.

### A3 Canary Verification

A3 reports: canary MBID = `b817cffd-1d5c-4905-90a4-8f9e8367a14a`. Reading `cache/jamiroquai_everyday/identify.json` directly confirms `"mbid_recording": "b817cffd-1d5c-4905-90a4-8f9e8367a14a"`. The round-trip match is exact. A3's canary is valid.

One limitation: A3's canary tests only that a correctly-identified track still resolves. It does not test what happens when the API receives an invalid key mid-batch (e.g., if the key were to expire or be regenerated), nor does it test the HTTP-200-with-error-body path (AcoustID's documented `{"status":"error","error":{"code":4,...}}` response). The F2 finding from A1 (error codes discarded) remains unverified by A3 because A3 only tested the happy path. This is acceptable for a sanity gate; just noting A3 is not a comprehensive auth robustness test.

---

## 2. Prioritized Fix List

| Rank | Finding | File:line | Size | Risk | Round | Notes |
|------|---------|-----------|------|------|-------|-------|
| 1 | Known: Bucket-C walker bug | `acoustid.py:76-82` | S | low | 2 | Unlocks `warhaus` immediately. Must land WITH F1 (multi-recording selection) in the same commit — changing the walker without duration-preferring recordings[0] leaves a different silent failure. See note below. |
| 2 | F9: non-atomic `_preserve_or_write` | `identify.py:108-109`, `sidecar.py:39` | S | high | 2 | Catastrophic under parallel agents (per `parallel_agents.md` memory note). `.tmp` MUST be same-dir as destination (F:\ volume) or `os.replace` fails with WinError 17 on NTFS cross-volume. Fix covers both `identify.py` and `sidecar.py`. |
| 3 | F5: `_run_fpcalc` KeyError / JSONDecodeError bypass | `identify.py:53-54` | S | high | 2 | Crash path that bypasses `_preserve_or_write`. Without this fix, corrupt/short fpcalc output can wipe a previously-good `identify.json`. |
| 4 | F3: httpx transport errors bypass soft-fail | `acoustid.py:53-55` | S | med | 2 | Any DNS hiccup during a batch reidentify run will crash the stage. Move client out of loop + wrap in `except httpx.RequestError`. |
| 5 | Known: `DEFAULT_MIN_SCORE` recalibration to 0.65–0.70 | `acoustid.py:17` | S | low | 2 | Data-driven from A2. Requires regression test with the walker fix (Rank 1) — batch together. Note: no Bucket-C results are currently in range 0.65-0.85 in the probe data, so this change's primary value is future-proofing, not immediate corpus rescue. |
| 6 | F11: SCHEMA_VERSION duplication (dual-bump discipline) | `identify.py:26`, `stage_manifest.py:174` | S | med | 2 | Not a runtime bug today, but critical for §4.2 staleness chip behavior. The bump must hit both locations atomically in one commit. Add "bump both" to Round 2 prompt. Update sidecar.py docstring to include "behavior change" as a bump trigger. |
| 7 | F1: recordings[0] blind pick | `acoustid.py:84-88` | S | low | 2 | Unlocks multi-recording cases (e.g., `awolnation` has 2 recordings on its top result). Bundle with Rank 1 walker fix since both modify `acoustid.py:lookup()` return shape — doing them separately forces two SCHEMA_VERSION bumps. |
| 8 | F2: AcoustID error code discarded | `acoustid.py:69-70` | S | low | 2 | Observability fix. No corpus impact, but operators debugging a broken deployment need the error code. Cheap. |
| 9 | F4: fpcalc stderr discarded | `identify.py:61-63` | S | low | 2 | Observability fix. No corpus impact. Add `e.stderr[-200:]` to the reason string. |
| 10 | O2: AcoustID retry backoff too short | `acoustid.py:60` | S | low | 2 | 3s total recovery window is insufficient for a 40-track corpus-wide reidentify. Bump to 4 attempts with [1, 4, 9]s backoff before Round 2's probe re-run. |
| 11 | F10: legacy caches without sidecar re-query on every run | `identify.py:32-36` | S | low | 2 | Wastes AcoustID quota. The 10 pre-sidecar `identified=true` caches in the corpus would re-query on every analyze run until repaired. Migration bridge: synthesize sidecar if `identify.json` exists with `identified=true` and no sidecar. |
| 12 | F6: MB recording_lookup lacks per-call retry | `musicbrainz.py:50-53` | S | med | 4 | Spec's non-goal "Touching MB 5xx handling" refers to the operational retry script, not the per-call client retry. Bundle with Round 4 MB client work. The 13 Bucket-R `mb_503` slugs are operationally addressed by `identify-retry.*`; this is belt-and-suspenders. |
| 13 | F8: `releases[0]` — wrong "first release" for year/album | `musicbrainz.py:58-59` | S | low | 4 | Data quality. No identification impact. Unlocks correct album/year display in Metadata card. Bundle with Round 4 MB client work. |
| 14 | F12: slug-to-artist parser needs ID3 fallback for non-ASCII | `identify.py` Round 4 work | M | med | 4 | Pre-emptive design requirement for Round 4 fallback. The probe already shows `fanfare_ciocarlia` (Romanian diacritics) in corpus. Read ID3 TIT2/TPE1 first, use slug only as fallback. |
| 15 | F13: `read_identify` returns None for corrupt JSON | `webui/webui/identify.py:15-23` | S | low | 4 | Consumer side. Bundle with Round 4 trust-signaling UI work. |
| 16 | F7: MB User-Agent missing email | `keys.py:15` | S | low | 5+ | Cosmetic/policy. No current impact. Confirm user accepts email in outbound strings first. |

**Note on Rank 1 + Rank 7 dependency:** The spec's Round 2 §B1 prompt says "return first result whose score >= min_score AND has at least one recording" and separately asks for logging unlinked IDs. F1 (recordings[0] blind pick within a result) is a distinct fix: once we find a result with recordings, which recording do we use? Doing Rank 1 without Rank 7 means we fix the result-picking correctly but still use recordings[0] arbitrarily within the winning result. Since both modify `acoustid.py:lookup()`, they should land in a single commit to avoid two SCHEMA_VERSION bumps (version 2 for the walker, then version 3 for the recording selector). The Round 2 B1 prompt must be updated to include F1.

**Bucket counts addressable per round:**

- Round 2 (code fixes + mb_503 retry): 1 Bucket-D (`warhaus`) + 13 Bucket-R (mb_503 retry path) = up to 14 tracks. Confirmed 14 of 30 can identify without any preprocessing.
- Round 3 (silence-strip): at most 6 of 11 Bucket-A tracks have detectable silence (>0.3s). Best case: 5–6 additional tracks (charlie_puth 0.45s is marginal; ren_x_chinchilla 6.47s is the strongest candidate). Realistically 3–4.
- Round 4 (MB text-search fallback): the remaining Bucket-A zero-silence tracks, all 4 Bucket-B tracks, plus the "should fail gracefully" live/acoustic tracks. Potentially 8–10 additional.

The spec's ≥75% target (≥22/30 identified) requires all three fix rounds to land. Round 2 alone achieves ~47% (14/30).

---

## 3. Missing Analysis

### What Round 1 did not investigate

**A. Bucket-A zero-silence failure cause not determined.** Of the 11 Bucket-A tracks, 5 have zero leading silence and still return no AcoustID results. A1 and A2 both classified these together with silence-affected Bucket-A tracks, but the root cause is different: for zero-silence tracks, either (a) no AcoustID submitter has ever uploaded a fingerprint for this YouTube video/content, or (b) the AcoustID database has fingerprints but Chromaprint 1.5.x produces a mismatched hash against newer submissions. A1 OQ6 raises the fpcalc version concern. Nobody verified the actual fpcalc version (`fpcalc -version`). If the vendored binary is substantially older than the AcoustID submitters' Chromaprint versions, the fingerprints may not match even for well-known commercial tracks. This is a material unknown that could mean Round 3 has near-zero impact on commercial Bucket-A tracks with zero silence. This should have been checked in Round 1.

**B. `balthazar-changes_official_video` should be easy to identify yet returns zero results.** The corpus doc lists Balthazar "Changes" as a "should easily identify" commercial release. It has zero leading silence and zero AcoustID results. The probe did not attempt to verify whether the AcoustID DB has ANY fingerprint for this track via a manual Shazam/AcoustID web search. If the AcoustID DB genuinely has no entry for this video's audio content, the root cause is "no fingerprint was ever submitted," not "our code has a bug." Round 3 cannot help. This distinction matters for the spec's success criteria (§2 target: ≥30/40 = 75%). If 4–5 "should easily identify" tracks simply don't have fingerprints in the DB, the 75% target becomes unreachable from the AcoustID path alone, regardless of how well Round 2 and 3 go.

**C. The spec's "Bucket C" behavior-change logging was only mentioned, not verified.** A2's "call-outs" section notes that some Bucket-R tracks from the `no_match` snapshot now return linked results — meaning the original analyze run hit a transient gap, not a code bug. Neither A1 nor A2 investigated whether the current production code emits enough log detail to distinguish "transient gap that later resolved" from "code was wrong." The spec §4.1 structured log line is a goal, but there is no existing log at all. A1 flagged observability gaps but did not enumerate what the current log output looks like for a successful vs. failed identify run. Round 2 should add the §4.1 structured log as a first-class deliverable, not as a bonus.

**D. The `_write` bypass function.** `analyze/stages/identify.py:113-118` exposes `_write(cache_dir, payload, params)` which bypasses `_preserve_or_write` entirely. A1 did not check who calls this function, whether any test infrastructure uses it, or whether the Round 2 atomicity fix needs to cover it too. If test fixtures use `_write` to set up test caches, the tests could be operating on a different code path than production.

### A2's URL-encoding gotcha — should A1 be relaunched?

A2 flagged that `+` between keys in a query string literal equals literal `%2B` → silently drops `recordings` from the AcoustID response. Reviewing the actual production code at `acoustid.py:46`: `"meta": "recordings"` — single key, no `+`. The production code is safe. A2 correctly notes this. However, A2 raised it as "should A1 add this to static analysis" — this is not a finding worth relaunching A1. R2 should note the safe path in Round 2's code review and add a comment in `acoustid.py` near the `meta` parameter that explains why a single key is used (and what breaks if you try to add a second key with `+` concatenation). No A1 relaunch required.

### Open question O1 — staleness ⟳ button routing

A1 raises whether the webui's staleness ⟳ button routes through `python -m analyze` (WSL) or calls `analyze.stages.identify.run()` directly from Windows Python. This is load-bearing: the vendored `fpcalc` is a Linux ELF binary. If the button calls the stage directly from Windows Python 3.13, it will fail with `OSError` (not `FileNotFoundError`), bypassing the current exception handler. Neither A1, A2, nor A3 investigated this. Before Round 2 commits the walker fix and SCHEMA_VERSION bump (which will trigger staleness for all 30 corpus tracks), the routing of the ⟳ button must be confirmed. This is the highest-priority open question from A1 and it was not resolved.

---

## 4. Open Questions from Spec §7

**Q1: Cache the raw AcoustID response so future re-analyses don't re-query.**
Recommendation: address in Round 2. The corpus probe had to re-query the live AcoustID API. If the raw JSON were cached alongside `identify.json` (e.g., `.acoustid_raw.json`), Round 3's threshold recalibration and Round 4's walker improvements could be replayed against cached data without quota consumption. This also enables offline debugging. The storage cost is trivial (a few KB per track). This is a Round 2 deliverable, not a future enhancement — it directly supports Round 3 development.

**Q2: Silence-strip once-per-cache vs per-run.**
Recommendation: address in Round 3. The design choice (write `stripped.wav` once, or transcode per run) belongs in the Round 3 C1 design doc. However, the reviewer's position: write once. The stripped WAV enables reuse by any other stage that benefits from silence-removed audio. The storage cost (~10MB per track) is acceptable given the project is running on a machine with ample disk. The "per-run" approach wastes CPU on every reidentify.

**Q3: Faster expiry for fallback caches.**
Recommendation: address in Round 4. The schema for a `source: "fallback"` identify.json (Round 4's output) should include a `fallback_ttl_days` field (defaulting to e.g. 30 days). The staleness checker can compare `identified_at` + `fallback_ttl_days` against today. This is a Round 4 schema design decision and the sidecar framework already supports per-stage params, so a `fallback_ttl` param could be added without structural changes.

**Q4: Manual override tier.**
Recommendation: defer to Round 5+. This requires UI (text input in the Metadata card), a new `source: "manual"` value, and a write path from webui into `identify.json`. It is valuable but independent of the automated identification pipeline. Design it in Round 5.

---

## 5. Recommendation

**ADVANCE TO ROUND 2**

The Round 1 evidence base is sufficient to proceed. A1 found real bugs with correct file:line anchors (all spot-checked anchors verified). A2's bucket classifications are accurate for the spot-checked slugs, with the noted caveat about zero-silence Bucket-A tracks. A3's canary is valid. The overall picture is clear enough to implement Round 2.

### Round 2 deliverables (concrete scope for orchestrator)

**B1 — Code fixes in `analyze/clients/acoustid.py` and `analyze/stages/identify.py`:**

1. Walker fix (known Bucket-C bug): sort results by score descending, iterate, return first result where `score >= min_score` AND `recordings` is non-empty. Log any skipped unlinked AcoustID IDs at DEBUG level with their scores (for future fingerprint submission work — this is the logging of unlinked high-score IDs the spec §B1 mentions).

2. Within the winning result, select the recording whose `duration` is closest to `fp["duration"]` (F1 fix). If no duration data, fall back to `recordings[0]`. This must land in the same commit as the walker fix.

3. Lower `DEFAULT_MIN_SCORE` from 0.85 to 0.65.

4. Move `httpx.Client` construction outside the retry loop (F3). Wrap `client.get()` in `except httpx.RequestError` and convert to `AcoustIDError`.

5. Validate `_run_fpcalc` output: check `"fingerprint" in data` and `"duration" in data` before accessing; raise a named error on failure; catch `json.JSONDecodeError` too (F5). The catch in `run()` must cover these.

6. Include `e.stderr[-200:]` in fpcalc failure reason strings (F4).

7. Surface AcoustID error code in `AcoustIDError` message when `status != "ok"` (F2).

8. Atomic writes: write `.tmp` (same directory — critical for NTFS same-volume rename guarantee) then `os.replace(tmp, dest)` in `_preserve_or_write`. Apply the same fix to `sidecar.write`. Test must assert `.tmp` is created in the same parent directory as the target file.

9. Bump `SCHEMA_VERSION` from 1 to 2 in BOTH `analyze/stages/identify.py:26` AND `webui/webui/stage_manifest.py` (identify entry, `schema_version` key). These must be in the same commit. Update `analyze/sidecar.py` module docstring to add "client picking logic or behavior changes" as a bump trigger.

10. Add the §4.1 structured log line on every `run()` completion: `identify: slug=<slug> source=acoustid|none score=<float|—> mbid=<mbid|—> reason=<string|->`. This is a Round 2 deliverable per §4.1 ("Round 2 or 3").

11. Synthesize sidecar for legacy `identified=true` caches that lack a sidecar (F10 migration bridge).

12. Cache the raw AcoustID JSON response as `.acoustid_raw.json` in the cache dir on every successful query (§7 Q1, addressed in Round 2 as recommended above).

13. Increase `RETRY_5XX_MAX_ATTEMPTS` to 4 with backoff `[1, 4, 9]s` before the corpus-wide re-run (O2).

**B1 — Before committing: verify the staleness ⟳ button routing.** Before any code is committed, read `webui/webui/chat_actor.py` and the server routing code to confirm whether the one-click ⟳ re-identify routes through `python -m analyze` (WSL) or calls `analyze.stages.identify.run()` directly. If the latter: the fpcalc subprocess path will fail with `OSError` on Windows, not `FileNotFoundError`. This must be resolved before the SCHEMA_VERSION bump triggers staleness for all 30 corpus tracks.

**B1 — Tests:** Add the full test suite A1 specified for each finding above, plus:
- `test_preserve_or_write_tmp_is_same_dir`: assert `.tmp` parent == `identify.json` parent
- `test_walker_returns_second_result_when_first_unlinked`: payload [0.984 unlinked, 0.951 linked] → returns 0.951 result
- `test_walker_prefers_closest_duration_within_result`: result has 2 recordings [duration=177, duration=241], fp duration=240 → returns duration=241 recording
- `test_schema_version_bump_invalidates_cache`: write a v1 sidecar, call `cached()` with the new v2 constant → returns False

**B2 — Probe re-run and delta report** (after B1 commits land):
Re-run `scripts/probe_acoustid.py` against the full 30-track corpus. Re-run `python -m analyze --stages identify <slug>` for each slug. Produce `round-2-delta.md` with per-slug before/after and aggregate counts. This delta will validate that warhaus identified correctly and no regressions occurred on the 10 currently-identified tracks.

**R2 — Round 2 Reviewer** must additionally verify:
- The `.tmp` same-directory constraint is enforced in both `_preserve_or_write` and `sidecar.write`
- No `identified=true` track regressed (zero tolerance — `_preserve_or_write` must have protected them)
- Both SCHEMA_VERSION locations were bumped atomically
- The staleness ⟳ routing question (O1) was resolved before merge
- The structured `identify:` log line appears in `webui.log` after a test re-identify

---

**Files relevant to this review:**

- `<PROJECT_PATH>/analyze/stages/identify.py`
- `<PROJECT_PATH>/analyze/clients/acoustid.py`
- `<PROJECT_PATH>/analyze/clients/musicbrainz.py`
- `<PROJECT_PATH>/analyze/sidecar.py`
- `<PROJECT_PATH>/webui/webui/identify.py`
- `<PROJECT_PATH>/webui/webui/stage_manifest.py`
- `<PROJECT_PATH>/webui/tests/test_stage_manifest_in_sync.py`
- `<PROJECT_PATH>/cache/jamiroquai_everyday/identify.json`
- `<PROJECT_PATH>/.claude/worktrees/identify-overhaul/docs/superpowers/identify-overhaul/round-1-a2-corpus-probe.json`
