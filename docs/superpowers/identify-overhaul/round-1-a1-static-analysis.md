# Round 1 — Subagent A1: Static analysis of the identify pipeline

**Date:** 2026-05-12
**Scope:** read-only audit of
  `analyze/stages/identify.py`,
  `analyze/clients/acoustid.py`,
  `analyze/clients/musicbrainz.py`,
  `analyze/keys.py`,
  `webui/webui/identify.py`,
plus supporting context from `analyze/sidecar.py`, `webui/webui/stage_manifest.py`,
`tests/unit/test_acoustid_client.py`, `tests/unit/test_identify_stage.py`,
`scripts/probe_acoustid.py`, and `analyze/vendor/chromaprint/fpcalc`
(verified Linux ELF binary).

**Known issues — not re-reported here:**
1. `analyze/clients/acoustid.py:76-78` max-by-score bails on empty recordings (Bucket C).
2. `DEFAULT_MIN_SCORE = 0.85` (`acoustid.py:17`) too aggressive for YouTube transcodes.
3. fpcalc runs on raw MP3 with no silence pre-strip.

The 13 findings below are *additional* to those.

---

## F1 — `meta=recordings` returns only the FIRST recording per result; AcoustID frequently links several

- **Severity:** high
- **Anchor:** `analyze/clients/acoustid.py:84-88` (combined with line 47, `"meta": "recordings"`)
- **What's wrong.** After picking `best`, the client does `recordings[0]["id"]` — but the AcoustID v2 spec [`/v2/lookup`](https://acoustid.org/webservice#lookup) explicitly returns `recordings` as a **list**: a single AcoustID can be linked to multiple MB recordings (typical for "same master across releases" — single, album, deluxe, remaster). Picking index 0 is a coin flip; the order is *not* documented as score-sorted, and in observed responses it's often the oldest recording, which may have less complete metadata or even be a wrong-credits entry. This is also a silent failure: nothing in the payload tells the operator there were N other candidates we threw away.
- **Smallest fix.** Either (a) request `meta=recordings+recordingids+releasegroups` and pick the recording whose duration is closest to the fingerprinted duration (we already have `fp["duration"]`), or (b) keep `recordings[0]` but persist `len(recordings)` and the full list of MBIDs in `identify.json` as `mbid_recording_candidates` so we can re-evaluate without re-querying.
- **Test.**
  - `test_lookup_prefers_recording_with_closest_duration`: payload has `recordings=[{"id":"A","duration":177},{"id":"B","duration":240}]`, fpcalc duration=241 → return mbid B.
  - `test_lookup_records_candidate_count_for_observability`: payload has 3 recordings → returned dict includes `"recording_candidates": 3` (or a list of MBIDs).
- **Round tag.** Round 2 (low-risk, no new dependency; pairs with the Bucket-C walking fix).

---

## F2 — AcoustID error responses with HTTP 200 are detected, but the error code is discarded

- **Severity:** medium
- **Anchor:** `analyze/clients/acoustid.py:69-70`
- **What's wrong.** AcoustID returns `{"status":"error","error":{"code":<int>,"message":"..."}}` with HTTP 200 ([webservice docs §Errors](https://acoustid.org/webservice#errors)). Current code does `data.get('error')` — for the documented shape this serialises the *dict* into the exception message, but more importantly the operator never sees the numeric **code** which is the only stable signal (codes 1 — "unknown format", 2 — "missing parameter", 3 — "invalid fingerprint", 4 — "invalid APIKEY", etc.). Operators reading `webui.log` after a regression won't be able to distinguish a deployment-broken key (code 4) from a transient codec issue (code 1) without re-running by hand.
- **Smallest fix.** When `status != "ok"`, parse `error` defensively — if it's a dict, surface `error.get("code")` and `error.get("message")`; if string, pass through. Raise `AcoustIDError(f"status=error code={code} message={msg}")`.
- **Test.** `test_lookup_surfaces_acoustid_error_code`: payload `{"status":"error","error":{"code":4,"message":"invalid API key"}}` → raised `AcoustIDError` contains `"code=4"`.
- **Round tag.** Round 2.

---

## F3 — `httpx.Client` constructed inside the retry loop; no connection pooling and TLS handshake re-done up to 3×

- **Severity:** low (perf + reliability nit; can magnify failure under flaky DNS)
- **Anchor:** `analyze/clients/acoustid.py:53-55`
- **What's wrong.** The loop pattern is `for attempt in range(...): with httpx.Client(...) as client: resp = client.get(...)`. Each retry tears down and rebuilds the TLS session. For batch identify (the planned operational mode after staleness refresh) this is wasted; for the single-track case it's a non-issue. More importantly, this style means transient `httpx.ConnectError` / `httpx.ReadError` (DNS hiccup, ECONNRESET in mid-handshake) bubble up as **uncaught exceptions** that bypass `_preserve_or_write` — the caller in `identify.run` only catches `AcoustIDError`, so a network blip would crash the analyze stage instead of writing a soft-fail stub.
- **Smallest fix.** Move `httpx.Client(...)` out of the loop (one client, one connection pool). Wrap `client.get(...)` in `try/except (httpx.RequestError,)` to convert transient transport errors into `AcoustIDError` so they participate in the 5xx retry policy *and* the soft-fail path in `identify.run`.
- **Test.**
  - `test_lookup_retries_on_connect_error`: first 2 calls raise `httpx.ConnectError`, third returns 200 → returns parsed match. (Today this test would fail; the first ConnectError escapes.)
  - `test_lookup_exhausts_retries_then_raises_acoustid_error`: every call raises `httpx.ReadTimeout` → final exception is `AcoustIDError`, not bare httpx error.
- **Round tag.** Round 2.

---

## F4 — `identify.run` catches `subprocess.CalledProcessError` etc. but throws away stderr

- **Severity:** medium (operator-debugging penalty)
- **Anchor:** `analyze/stages/identify.py:43-54` and `:61-63`
- **What's wrong.** `_run_fpcalc` calls `subprocess.run(..., capture_output=True, check=True)`. When fpcalc exits non-zero (corrupt MP3, missing libavcodec at runtime, WSL fs/mount permission error), the raised `CalledProcessError` carries `.stderr` containing the actual cause. The catch in `run()` formats only `type(e).__name__: e` → the persisted reason is e.g. `"fpcalc failed: CalledProcessError: Command '[...]' returned non-zero exit status 1."` with **no fpcalc stderr**. The next operator hitting a 17/40 corpus has no signal whether it was codec failure, file truncation, or path issue.
- **Smallest fix.** In `_run_fpcalc`'s exception handler (or in `run()`'s catch), capture `e.stderr` (or `e.stdout` for `TimeoutExpired`) and include the last 200 chars. Also include exit code: `f"fpcalc failed (exit {e.returncode}): {e.stderr[-200:]}"`.
- **Test.** `test_run_includes_fpcalc_stderr_on_failure`: monkeypatch `_run_fpcalc` to raise `CalledProcessError(returncode=1, cmd=..., stderr="libavcodec: unsupported codec")` → assert `"unsupported codec"` is in `out["reason"]`.
- **Round tag.** Round 2.

---

## F5 — `_run_fpcalc` parses fpcalc's JSON unsafely: `data["fingerprint"]` raises `KeyError`, not `AcoustIDError`/etc.

- **Severity:** medium
- **Anchor:** `analyze/stages/identify.py:53-54`
- **What's wrong.** fpcalc with very short clips or malformed input has been observed to emit `{"error":"..."}` with exit 0 (especially on Windows-side ffmpeg muxes carried into WSL); `data["fingerprint"]` then raises `KeyError`. `run()` only catches `(FileNotFoundError, CalledProcessError, TimeoutExpired)` so `KeyError` bubbles up uncaught — the whole analyze stage crashes mid-pipeline and `_preserve_or_write` never gets a chance to protect the cache. `json.JSONDecodeError` from a truncated stdout would do the same thing.
- **Smallest fix.** In `_run_fpcalc`, validate keys explicitly: `if "fingerprint" not in data or "duration" not in data: raise FpcalcError(f"unexpected fpcalc JSON: {list(data)}")`. Add `FpcalcError(RuntimeError)` and catch it (plus `json.JSONDecodeError`) in `run()`.
- **Test.** `test_run_soft_fails_on_fpcalc_garbage_json`: `_run_fpcalc` returns `{"error":"short input"}` style payload → `run()` returns `{"identified": False, "reason": "fpcalc failed: ..."}` and does not raise.
- **Round tag.** Round 2.

---

## F6 — `MusicBrainz.recording_lookup` does not retry 5xx; only AcoustID does

- **Severity:** medium (asymmetric reliability — currently masked only by the operational `identify-retry` script + `_preserve_or_write`)
- **Anchor:** `analyze/clients/musicbrainz.py:50-53`
- **What's wrong.** MB serves intermittent 503/504 under load (and historically: every ~10 minutes during their reindex windows). AcoustID got the retry-with-backoff treatment; MB did not. The spec's own success-criteria table cites 13/40 tracks bucketed as `"MusicBrainz error: HTTP 503"`. The orchestrator non-goal "Touching MusicBrainz 5xx handling" is about the operational retry tool — but the **per-call** retry inside the client is still missing and is a cheaper fix than spinning up an external script.
- **Smallest fix.** Mirror the AcoustID retry pattern: `for attempt in range(3): … if resp.status_code < 500: break; time.sleep(2**attempt)`. Combined with the existing `_gate()` rate-limiter this stays inside MB's 1 req/s policy because the sleeps are >1s.
- **Test.**
  - `test_recording_lookup_retries_on_5xx_then_succeeds`: two 503s then 200 → returns parsed dict, call_count=3.
  - `test_recording_lookup_no_retry_on_4xx`: 404 → raises immediately, call_count=1.
- **Round tag.** Round 4 (spec says we're not touching MB this round; revisit when the fallback work goes in).

---

## F7 — MB User-Agent string violates MusicBrainz published policy

- **Severity:** medium (etiquette + risk of being rate-throttled or banned in batch operation)
- **Anchor:** `analyze/keys.py:15` — `"MusIQ-Lab/0.1 ( https://github.com/RaduPrusan/MusIQ-Lab )"`
- **What's wrong.** [MB UA policy](https://musicbrainz.org/doc/MusicBrainz_API#Application_rate_limiting_and_identification) requires `ApplicationName/Version ( ContactInfoString )` where the contact must be "a URL or email address where the maintainer can be reached." This UA passes URL form but lacks the application's contact email; not strictly invalid, but if MB ops complain they'll go to the GitHub Issues which the project's user-email memory note shows is not actively monitored for that purpose. Lower risk: version stuck at `0.1` forever — no signal whether a regression came from an old or new build of the analyzer.
- **Smallest fix.** Make the version dynamic (read from `pyproject.toml` or a constants file) and add `mailto:` to the contact tuple: `"MusIQ-Lab/{ver} ( https://github.com/RaduPrusan/MusIQ-Lab; <maintainer-email> )"`. Confirm the user is okay with surfacing their address in outbound UA strings before committing.
- **Test.** `test_user_agent_includes_version_and_contact`: `keys.get_user_agent()` matches `re.compile(r"MusIQ-Lab/\d+\.\d+.* \(.+\)")`.
- **Round tag.** Round 5+ (defer; cosmetic relative to identification rate).

---

## F8 — `recording_lookup` returns `releases[0]` blindly — wrong "first release"

- **Severity:** medium (data-quality smell in the eventual UI)
- **Anchor:** `analyze/clients/musicbrainz.py:58-71`
- **What's wrong.** `releases[0]` is whatever order the MB JSON serializer chose — *not* the earliest release. For a track that appears on (single 2010, album 2010, compilation 2018, remaster 2020) we might persist the *compilation* as `release` and `release-group`, then derive `year=2018` from it. The `first-release-date` field higher up (`data.get("first-release-date")`) is the correct canonical year, and the code does prefer it for the `year` field — but the `release` *title* and `mbid_release_group` are taken from `releases[0]` regardless. This will cause the Metadata card to show a misleading album once the data lands.
- **Smallest fix.** Sort `releases` by `(release.get("date") or "9999-99-99")` ascending and pick the earliest before extracting `title` and `release-group`. Or, parallel to `year`'s logic, special-case "if `first-release-date` matches a release's date, pick that release".
- **Test.** `test_recording_lookup_picks_earliest_release`: MB payload has 3 releases dated 2020-01-01, 2010-05-15, 2015-08-20 → returned `release` corresponds to the 2010 entry.
- **Round tag.** Round 4 (touches MB client; bundle with retry fix).

---

## F9 — `_preserve_or_write` writes to the cache without atomicity; concurrent identify runs can corrupt `identify.json`

- **Severity:** high (matches the user's known parallel-agents note in MEMORY.md)
- **Anchor:** `analyze/stages/identify.py:108-109` (and `:117`)
- **What's wrong.** `path.write_text(json.dumps(...))` is a non-atomic "open, truncate, write, close". If the analyze stage is invoked twice in parallel (the user explicitly notes in `parallel_agents.md` that they sometimes run multiple agents on this repo), one writer can truncate the file while the other is mid-read inside `_preserve_or_write`'s `existing = json.loads(path.read_text())`, producing a JSONDecodeError that gets swallowed (`existing = None`) — which means the second writer *will not preserve* a previously-good payload because it didn't see one. Net effect: under concurrency, the identify-demotion-protection guard silently regresses. Same story for `webui/webui/identify.py:read_identify` — corrupt mid-write JSON is read as "missing".
- **Smallest fix.** Write to `identify.json.tmp` then `os.replace(tmp, identify.json)` (atomic on both POSIX and NTFS). Combine with `analyze.sidecar.write` doing the same. Optionally add a file lock (`portalocker` or `fcntl.flock` POSIX-only) around the read-modify-write block in `_preserve_or_write`.
- **Test.**
  - `test_preserve_or_write_uses_atomic_rename`: monkeypatch `Path.write_text` to assert it is never called for `identify.json`; assert `os.replace` is called from a `.tmp` path.
  - `test_preserve_or_write_handles_concurrent_writers`: spawn two threads, each calling `_preserve_or_write` with the same good payload; assert the file is always valid JSON after `thread.join()`. Use `concurrent.futures` and run 50 iterations.
- **Round tag.** Round 2 (cheap; the spec already lists `_preserve_or_write` correctness as load-bearing per the demotion-protection memory note).

---

## F10 — `cached()` doesn't notice `identify.json` deletion or staleness vs. params; relies entirely on the sidecar

- **Severity:** medium
- **Anchor:** `analyze/stages/identify.py:32-36`
- **What's wrong.** `cached` checks `(cache_dir/CANONICAL).exists()` and then defers to `sidecar.matches` — but the sidecar is a separate file (`.params_identify.json`). If somebody manually deletes `identify.json` to force a re-run (a documented operator move; the README's "what NOT to do" doesn't explicitly forbid it) the sidecar still says "we have valid params for v1 with these defaults" — `cached` returns False correctly because of the first check, *but* the inverse case where `identify.json` exists yet the sidecar was lost (because the user ran an old version of the code that didn't write sidecars) will report `cached=False` and re-query AcoustID/MB on every analyze run, wasting their rate-limit. This currently affects the 10 pre-sidecar `identified=true` caches in the corpus.
- **Smallest fix.** Add a bridge: if `identify.json` exists and is `identified=True` but the sidecar is missing, synthesize a default-params sidecar at the current `SCHEMA_VERSION` once, then return True. Document the migration in a comment.
- **Test.** `test_cached_synthesizes_sidecar_for_legacy_caches`: write a good `identify.json` directly (no sidecar). Call `identify.cached(...)` → True; assert sidecar now exists with `schema_version=SCHEMA_VERSION`, `params={}`.
- **Round tag.** Round 2.

---

## F11 — Schema-version is duplicated in two places; the spec's plan to bump it in Round 2 risks a silent miss

- **Severity:** medium (process risk, not a runtime bug today)
- **Anchor:** `analyze/stages/identify.py:26` AND `webui/webui/stage_manifest.py:174-175`
- **What's wrong.** The webui's staleness probe reads `stage_manifest.STAGES[..."identify"...]["schema_version"]` (currently `1`). The analyze stage exposes its own `SCHEMA_VERSION = 1`. They are kept in sync only by `webui/tests/test_stage_manifest_in_sync.py::test_manifest_schema_versions_match_source` — which is great, but it does NOT exist in the project's main CI loop description. Round 2 of this spec instructs the agent to bump `SCHEMA_VERSION` in analyze; if they forget the manifest, the analyze side will re-run identify but the webui staleness chip won't recognize anything as stale, so the user-facing one-click ⟳ documented in §4.2 will silently be a no-op until the manifest is updated separately.
- **Smallest fix.** Add an explicit checkbox to Round 2's prompt ("bump both `analyze/stages/identify.py:SCHEMA_VERSION` AND `webui/webui/stage_manifest.py` STAGES[identify]['schema_version']"). Even better: refactor the manifest to import `SCHEMA_VERSION` directly from the stage module instead of duplicating the literal — the existing manifest-drift test was added because of exactly this class of bug. If a circular-import concern blocks the import, at least raise a `RuntimeError` in `stage_manifest.py` import if the two disagree at start-up time of the webui.
- **Also relevant**: the spec asks "should SCHEMA_VERSION bump when we change CLIENT BEHAVIOR even if the cached payload schema is unchanged?" — **yes**. The Bucket-C walking fix in Round 2 changes WHICH recording we pick, which is exactly the kind of behavior change that should re-evaluate caches. The current SCHEMA_VERSION docstring (sidecar.py:8-12) is ambiguous; we should update the comment to say "bump when client picking logic changes even if the JSON shape is identical."
- **Test.** Already exists (`test_manifest_schema_versions_match_source`). Add: `test_schema_version_doc_includes_behavior_changes` — read the sidecar.py module docstring and assert the substring "client picking logic" or "behavior change" appears.
- **Round tag.** Round 2.

---

## F12 — Slug-to-artist parsing (planned in Round 4) needs to handle non-ASCII; current pipeline strips at no clear boundary

- **Severity:** low for Round 1 / high once Round 4 lands
- **Anchor:** none yet — flagged for `analyze/stages/identify.py` Round 4 work, plus existing yt-dlp template `%(title)s-%(id)s.%(ext)s` (CLAUDE.md)
- **What's wrong.** Memory note `ytdlp_print_vs_ondisk_filename` already records that yt-dlp's `--print after_move:filepath` mangles fullwidth chars on Windows. The slugs that survive contain ASCII-only fragments — but `fanfare_ciocarlia`, Turkish/Romanian titles, French accents are part of the user's library. The Round 4 fallback design will do "search MB by artist/title parsed from the slug": if the slug is already ASCII-mangled (e.g. `bjork_post` instead of `Björk_Post`), MB's text search will return no results and we'll declare the track unidentifiable when in fact the canonical metadata is right there. We should not commit to the slug-only approach without falling back to a secondary input (the source MP3's ID3 tags, which yt-dlp populates correctly because they're UTF-8 in the file, not the filesystem).
- **Smallest fix.** In Round 4: before doing slug-derived MB search, read `mutagen.File(mp3).tags` for `TIT2`/`TPE1`/`TALB` — these survive the Windows filename roundtrip intact. Slug parsing is the *fallback* of the fallback.
- **Test.** `test_fallback_prefers_id3_over_slug_for_nonascii_titles`: build an MP3 with TIT2="Hâle" and TPE1="Žarko"; slug = "h_le_zarko_official_video"; assert the MB query receives the ID3-derived strings, not the slug-derived `"H Le", "Zarko"`.
- **Round tag.** Round 4.

---

## F13 — `webui/webui/identify.py:read_identify` silently treats missing `identify.json` and corrupt `identify.json` differently (returns `None` for both) — UI sees no signal that something is wrong

- **Severity:** low (consumer side; mostly fine because the canonical contract is "None = pretend it doesn't exist")
- **Anchor:** `webui/webui/identify.py:15-23`
- **What's wrong.** When `identify.json` is corrupt, we log a warning to the Python logger but the front-end's metadata card just renders "no identification" — indistinguishable from "we never ran identify". For a defensive read this is fine; for a power-user this means a half-written JSON (e.g. from F9 concurrency) becomes invisible until someone greps `webui.log`. The spec's §4.1 observability goal already covers a structured log line per identify run; this consumer-side gap is the mirror image.
- **Smallest fix.** Add `read_identify_status(cache_dir) -> Literal["missing","ok","corrupt"]` and expose it to the metadata card so the UI can distinguish the three states. Keep `read_identify` as the payload-only convenience. Or: return a sentinel dict `{"identified": False, "reason": "identify.json corrupt"}` instead of `None` when the file exists but doesn't parse — this lets the UI render the same "unidentified" chip but with an explicit reason chip beside it, which is what an operator wants.
- **Test.** `test_read_identify_returns_corrupt_sentinel`: write `identify.json` containing `"{ not json"`; call `read_identify` → returns a dict whose `reason` mentions "corrupt", not `None`.
- **Round tag.** Round 4 (bundles with trust-signaling UI work).

---

## Cross-cutting observations

### O1 — `subprocess.run` invocation of vendored Linux fpcalc on Windows host

- **Anchor:** `analyze/stages/identify.py:49-52`, `analyze/vendor/chromaprint/fpcalc` (ELF binary).
- **Observation.** The analyze stack only runs inside WSL2 per CLAUDE.md and `requirements.lock`, so `subprocess.run([str(_FPCALC), …])` works because cwd is Linux. The webui (running on Windows-side Python per port 8765) cannot call this stage. If anyone later wires "click ⟳ to re-identify" through the webui directly (rather than via the analyze CLI through WSL), this subprocess call will silently fail with `[Errno 8] Exec format error` and the `FileNotFoundError` catch on line 61 will NOT fire — because the file does exist; it's the *exec* that fails. The exception will be `OSError` instead. The webui side of the identify retry flow needs to be aware of this. **Verify** before Round 2 closes whether the staleness ⟳ button routes through `python -m analyze` (WSL) or through `analyze.stages.identify.run` directly (Windows process).
- **Round tag.** Open question for R1.

### O2 — `acoustid.py` retry delays are tiny vs. AcoustID's typical recovery window

- **Anchor:** `analyze/clients/acoustid.py:60` — `time.sleep(2 ** attempt)` ⇒ waits 1s, then 2s, total ≤ 3s of recovery time before giving up.
- **Observation.** AcoustID's typical 5xx incident is "a minute or two while a fanout node reboots." Our `RETRY_5XX_MAX_ATTEMPTS=3` with `[1s, 2s]` backoff means we surrender after 3 seconds of being unlucky. This is fine for an interactive single-track analyze, but Round 2's plan to re-identify the entire 40-track corpus via staleness ⟳ would shoot 40 single-track requests within ~30 seconds — if AcoustID has a hiccup at second 5 we lose ~half the run. Consider `RETRY_5XX_MAX_ATTEMPTS=4` with `[1, 4, 9]s` backoff (sub-15s total) before any corpus-wide batch operation.
- **Round tag.** Round 2 (paired with corpus reanalyze).

---

## Open questions for R1

1. **Atomic writes ↔ `os.replace` on Windows-NTFS-from-WSL.** Does the `_preserve_or_write` atomic-rename fix (F9) need to use `tmp` inside the same NTFS dir to avoid cross-volume rename failures when WSL maps `/mnt/f` to the Windows F: drive? Verify with a single test on the live cache dir before committing.
2. **Bucket-C bug fix interaction with F1 (multi-recording results).** If we change the walker (Round 2 §B1) to "return the first scored result whose recordings ≠ []", do we also pre-emptively want the duration-closest-recording selection from F1? Or is that a separate Round 2 commit? They both modify `acoustid.py:lookup` return shape, so doing them together avoids a second cache-bust.
3. **Schema-version bump cadence.** If Round 2 bumps to v2 for the walker fix, Round 3 (silence-strip) for v3, and Round 4 (fallback source field) for v4, the user will see three consecutive staleness flushes within a week. Acceptable, or should we batch all four rounds behind a single v2 bump landed at the end (with the orchestrator running the full pipeline once before flipping the manifest)?
4. **AcoustID API contract for `recordings` ordering.** The webservice docs (consulted) state results have `score`, `id`, optional `recordings`. They do **not** specify ordering of `recordings` within a result. Should we file a clarification issue upstream, or just defensively sort by closest-duration as per F1?
5. **Should `webui/webui/identify.py:read_identify`'s `log.warning` upgrade to `log.error`?** Today there's no signal anywhere on disk after a corrupt JSON read — and §4.1's structured `identify:` log line is on the producer side, not the consumer side. A second log statement on read may help.
6. **fpcalc upgrade path.** The vendored binary has BuildID `459da401d41a4d8af8539d14759d8703d1804cc7` (Chromaprint 1.5.x family by signature). Newer Chromaprint (1.5.1+) has fingerprint-format extensions; if any of the unidentified corpus has been re-fingerprinted by AcoustID submitters with a newer Chromaprint, our old fpcalc may produce a fingerprint that scores lower against the same canonical recording. Confirm the version (`fpcalc -version`) and check whether a rebuild is warranted independent of the silence-strip fix.
