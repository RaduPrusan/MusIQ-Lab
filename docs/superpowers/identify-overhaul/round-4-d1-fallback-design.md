# Round 4 D1 — MusicBrainz Text-Search Fallback Design

**Author:** Orchestrator (synthesized after the feature-dev:code-architect agent returned without disk write; D1 design content carries the audit role)
**Date:** 2026-05-12
**Status:** Design only — no source changes
**Refs:** spec §D1 (line 506-561), Blocker B (`round-4-prereq-blocker-b.md`), R3 Pass 2 inherited debt

## Executive summary

Add a MusicBrainz text-search fallback to `analyze/stages/identify.py` that fires when AcoustID returns no extractable MBID (empty results OR all above-threshold results unlinked). Seed the search from the YouTube slug via a shared parser refactored from `webui/webui/lyrics.py`'s existing `_strip_yt_id_tail` + `_parse_filename`. Accept a MB candidate only when title-similarity > 0.85 AND duration variance < 5%. Surface `source="fallback"` with `match_method`, `duration_variance_pct`, `title_similarity` so the UI can render a clear trust signal.

---

## 1. Trigger conditions

Per Blocker B's empirical bucket distribution (5/6 hard zero, 0/6 below-threshold, 1/6 unlinked-high-score), the **disjunctive** trigger:

| Condition (after silence-strip + raw lookup) | Round 4 action | Source field |
|---|---|---|
| AcoustID returns `results: []` (hard zero) | MB text-search | `fallback` if match; `none` if not |
| AcoustID returns only unlinked results (all `recordings == []`) | MB text-search | `fallback` if match; `none` if not |
| AcoustID returned a linked match but MB recording-lookup failed (current `source="acoustid_unenriched"` path) | Skip text-search — use the AcoustID-returned MBID directly via a fresh MB lookup; if that fails too, persist as `source="acoustid_unenriched"` (existing R3 behavior) | `acoustid` (canonical, if MBID resolves) or `acoustid_unenriched` (fallthrough) |
| AcoustID returned linked match above threshold | NO fallback — already canonical | `acoustid` or `acoustid_stripped` |
| AcoustID returned below-threshold results | NO fallback (per Blocker B: empirically empty on this corpus; defer to a future round if a real case surfaces) | `none` |

The "below threshold" trigger from the original spec §D1 #3 is **dropped** because Blocker B confirmed zero corpus instances. Adds complexity for no benefit.

## 2. Slug → artist/title parser

**Location:** new module `analyze/text/slug_parser.py`. `webui/webui/lyrics.py` already has `_strip_yt_id_tail`, `_slug_to_display`, `_parse_filename`, and `identify_track` (with mutagen ID3 fallback) at lines 91-154 — move the pure-string functions into the shared module and re-export from lyrics.py to preserve the existing webui API.

**Why analyze/text/ instead of webui/:** the identify stage runs inside WSL via `python -m analyze`; the parser must be importable from the analyze package without a webui dependency. webui imports analyze elsewhere (analyze_runner), so the reverse import direction (analyze → analyze.text → webui imports analyze.text) is clean.

**Functions to move:**
- `_strip_yt_id_tail(stem) -> str` (lyrics.py:91-110) — keep regex `r"-[A-Za-z0-9_-]{11}$"` + the "digit OR underscore OR mixed case" gate. Per R1 A2 the gate already handles `hurt-ty-bldf8bsw` correctly (the trailing chars don't satisfy the gate → not stripped).
- `_slug_to_display(stem) -> str` (lines 113-123) — title-cases `_`/`-`.
- `_parse_filename(stem) -> tuple[str, str]` (lines 126-133) — returns `(artist, title)`.

**New helper for identify.py:**

```python
# analyze/text/slug_parser.py
_NOISE_TOKEN_RE = re.compile(
    r"\b(official\s+(?:music\s+)?video|official\s+audio|lyric\s+video|lyrics|"
    r"acoustic|live\s+at\s+[^,()]+|remastered|"
    r"single\s+version|album\s+version|radio\s+edit|extended\s+(?:mix|version)|"
    r"feat\.?\s+[^,()]+|ft\.?\s+[^,()]+|\(\d{4}\)|\[\d{4}\])",
    re.IGNORECASE,
)

def clean_title(title: str) -> str:
    """Strip noise tokens for MB search seeding. Conservative — only well-known
    YouTube noise patterns. Returns title unchanged if all matches would empty it."""
    cleaned = _NOISE_TOKEN_RE.sub("", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned or title  # never return empty
```

**ID3 fallback:** when slug parse yields empty artist or title, call `mutagen.File(mp3_path, easy=True)` and read `TPE1` (artist) + `TIT2` (title). This is what `webui/webui/lyrics.py:identify_track` already does at lines 136-154. Move it to `analyze/text/slug_parser.py` and have lyrics.py import it.

**Corpus sanity check** (predictions for 5 slugs, no implementation yet):

| Slug | parse_filename | clean_title | Likely MB seed |
|---|---|---|---|
| `charlie_puth_attention` | `("", "Charlie Puth Attention")` | unchanged | artist="Charlie Puth", title="Attention" (need post-parse heuristic to split when no "-") |
| `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` | `("Warhaus", "Love S A Stranger Official Video")` | `"Love S A Stranger"` | artist=Warhaus, title=Love's a Stranger (after `'s` repair) |
| `moderat-reminder_official_video-cjwsnuoazug` | `("Moderat", "Reminder Official Video")` | `"Reminder"` | clean |
| `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw` | `("Sting", "Shape Of My Heart Live At The Rijksmuseum")` | `"Shape Of My Heart"` (after `live at X` strip) | clean |
| `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a` | `("", "Orchestral Suite No 3 In D Major Ii Air On A G String Arr For Cello Quintet")` | unchanged | search likely fails — 11+ words; flag in delta |

The `charlie_puth_attention` case requires an additional heuristic: when `_parse_filename` returns empty artist with a multi-word title, AND ID3 tags are absent, attempt to split on the first capitalized word boundary (`"Charlie Puth Attention"` → ["Charlie Puth", "Attention"]) using `difflib` to score the split. Or — simpler — pass the entire title string to MB's `recording:` query and let MB's search engine extract the artist match from the `artist-credit` field. **Recommend the simpler approach** — MB search is lenient and the duration + title-similarity gates protect against false positives.

## 3. MusicBrainz search algorithm

**Dependency:** extend the existing `analyze/clients/musicbrainz.py` (httpx-based; no new dep). Spec §D1 #3 mentioned `musicbrainzngs` but adding a sync-blocking library when we already have an httpx client is unnecessary surface.

**New function:** `musicbrainz_client.search_recording(artist: str, title: str, duration_sec: float, limit: int = 10) -> list[dict]`

Behavior:
1. Build `query` per MB Lucene syntax:
   - If artist: `artist:"<artist>" AND recording:"<title>"`
   - Else: `recording:"<title>"`
2. GET `https://musicbrainz.org/ws/2/recording/?query=<urlencoded_query>&limit=10&fmt=json`
3. Standard MB headers: `User-Agent: MusIQ-Lab/0.1 ( https://github.com/RaduPrusan/MusIQ-Lab )` (already set at `keys.py:15`)
4. Respect MB's 1 req/s rate limit — add `time.sleep(1.0)` between calls (or asyncio.sleep when called from async context — for now identify is sync, so `time.sleep` is fine)
5. Parse the `recordings` array. Each entry has `id`, `length` (ms), `score` (search score 0-100), `title`, `artist-credit[*].name`. Optionally `releases` for album metadata.

**Candidate scoring:**

```python
def _score_candidate(rec, fp_duration_sec, target_title):
    rec_dur = rec.get("length", 0) / 1000.0  # ms → sec
    if rec_dur < 1.0:
        return None  # MB has no duration on file; can't confirm
    dur_variance = abs(rec_dur - fp_duration_sec) / fp_duration_sec
    if dur_variance > 0.05:  # > 5% variance → reject
        return None
    title_sim = difflib.SequenceMatcher(None, target_title.lower(), rec["title"].lower()).ratio()
    if title_sim < 0.85:
        return None
    # Combined score: lower duration variance + higher title similarity is better.
    return (dur_variance, -title_sim)
```

Return the candidate with the lowest `(dur_variance, -title_sim)` tuple (min). If no candidate scores, return None.

**Ambiguity rejection:** if the top-2 candidates both score AND their combined scores differ by less than 0.02 (effectively tied), reject as ambiguous and persist `source="none"` with `reason="fallback_ambiguous"`. False positives are worse than non-identifications.

## 4. Schema changes to `identify.json`

| Field | Old (R3 schema=3) | New (R4 schema=4) |
|---|---|---|
| `identified` | bool | bool |
| `source` | absent | `acoustid` \| `acoustid_stripped` \| `acoustid_unenriched` \| `fallback` \| `none` |
| `match_method` | absent | `chromaprint` \| `chromaprint_stripped` \| `mb_text_search` \| `mb_direct` (used for acoustid_unenriched MBID lookup) |
| `mbid_recording` | str \| null | str \| null |
| `title` | str \| null | str \| null |
| `artist` | str \| null | str \| null |
| `album` | str \| null | str \| null |
| `year` | int \| null | int \| null |
| `duration_variance_pct` | absent | float \| null (only when `source=fallback`) |
| `title_similarity` | absent | float \| null (only when `source=fallback`) |
| `reason` | "no AcoustID match above threshold" \| etc | DISAMBIGUATED: `acoustid_no_results` \| `acoustid_below_threshold` \| `acoustid_all_unlinked` \| `acoustid_transient_error` \| `fallback_no_match` \| `fallback_ambiguous` \| `fallback_duration_mismatch` \| `fallback_title_mismatch` \| `track_too_short` \| MB-error pass-through |

**Example — successful fallback:**
```json
{
  "identified": true,
  "source": "fallback",
  "match_method": "mb_text_search",
  "mbid_recording": "8feaaf3e-8c7c-4d57-9503-298a56b1c920",
  "title": "Love's a Stranger",
  "artist": "Warhaus",
  "album": "We Fucked a Flame into Being",
  "year": 2019,
  "duration_variance_pct": 0.013,
  "title_similarity": 0.94
}
```

**Example — fallback no match:**
```json
{
  "identified": false,
  "source": "none",
  "match_method": null,
  "reason": "fallback_no_match"
}
```

## 5. UI trust signaling (D3 scope)

**File: `webui/static/js/sidebar/metadata-card.js`**

When `identify.source === "fallback"`, render under the card title (existing renderer logic):

```html
<div class="metadata-card-source-note metadata-card-source-fallback"
     title="via MusicBrainz text-match search&#10;duration variance: 1.3%&#10;title similarity: 94%">
  via text-match search
</div>
```

When `identify.source === "acoustid_unenriched"`:
```html
<div class="metadata-card-source-note metadata-card-source-unenriched"
     title="AcoustID matched but full metadata unavailable">
  metadata unenriched
</div>
```

When `source === "acoustid"` or `"acoustid_stripped"`: no note (canonical match — no signaling needed).

**File: `webui/static/css/track.css`**

```css
.metadata-card-source-note {
  font-style: italic;
  font-size: 0.85em;
  color: var(--text-muted);
  margin-top: 2px;
  cursor: help;  /* hover-tooltip indicator */
}
.metadata-card-source-fallback { /* same as parent — informational, not warn */ }
.metadata-card-source-unenriched { color: var(--text-muted); }
```

**Hover tooltip** uses native `title` attribute (no JS framework needed). The `&#10;` newlines in `title` render as multi-line tooltips on most browsers.

**Tests:** add `webui/tests-js/metadata-card.test.js` (or extend an existing one) — assert the note renders only for `fallback` and `acoustid_unenriched`; assert no note for canonical sources; assert the tooltip content matches the spec.

## 6. Round 4 SCHEMA_VERSION decision

Bump 3 → 4. Triggered by:
- New required field `source` (schema shape change)
- New optional fields `match_method`, `duration_variance_pct`, `title_similarity`
- Disambiguated `reason` enum

Update BOTH:
- `analyze/stages/identify.py:32` → `SCHEMA_VERSION = 4`
- `webui/webui/stage_manifest.py:173-184` → identify entry `schema_version: 4`

The drift test (`test_stage_manifest_in_sync`) catches mismatch.

**Sidecar params:** add `fallback_enabled: True`, `fallback_min_title_similarity: 0.85`, `fallback_max_duration_variance: 0.05` to `DEFAULT_PARAMS`. These trigger sidecar invalidation on tuning changes (per Round 2/3 pattern).

Legacy bridge in `cached()` continues to protect all `identified=true` caches across the schema bump — synthesizes a v4 sidecar without re-querying AcoustID.

## 7. R3 Pass 2 inherited debt — rolled in

| Debt item | Round 4 action |
|---|---|
| `_cache_raw_acoustid` only on non-None match | Always write `.acoustid_raw.json` (incl. empty results) for forensics. Add second file `.acoustid_stripped_raw.json` for the stripped fingerprint path. |
| `reason="no AcoustID match above threshold"` ambiguous | Disambiguate per the §4 table: `acoustid_no_results` vs `acoustid_below_threshold` vs `acoustid_all_unlinked`. Required input for the fallback trigger logic. |
| `source="acoustid_unenriched"` MBID-direct path | When AcoustID returned a recording MBID but the MB recording lookup failed (5xx, parse error, etc), retry the MB lookup ONCE more before falling back. If still fails, persist `source="acoustid_unenriched"` (no text-search — we already have a confidence-validated MBID). |

## 8. Performance budget

- MB rate limit: 1 req/s strict. For 9 candidate tracks: ~18-27s extra wall time (search + duration-fetch + release-fetch per candidate).
- Acceptable: a full-corpus reanalyze is already 5-15 min; +27s is <10% increase.
- Per-track on a non-fallback path: zero overhead (the fallback only fires when AcoustID provides nothing useful).

## 9. Risks

| Risk | Mitigation |
|---|---|
| False positive: MB returns a different song with similar title + duration | Triple guard (AcoustID empty AND title_sim > 0.85 AND dur_variance < 5%). Reject ambiguous (top-2 within 0.02). |
| Slug parser overreach strips legitimate title token | Conservative noise-token regex; falls back to raw title if cleaning would empty it; preserves "Live at Y" only when not in noise list. |
| MB API timeout / rate-limit response (429/503) | Existing retry logic in `musicbrainz.py` handles 5xx; add 429 handling with exponential backoff. Soft-fail to `source="none"` reason `fallback_mb_error`. |
| Non-ASCII slugs (Romanian, Turkish) lose info in slug parse | mutagen ID3 fallback in `analyze/text/slug_parser.py` reads original tags from MP3. |
| `source="fallback"` masks a legitimate "track simply doesn't exist in MB either" outcome | Reason field disambiguates: `fallback_no_match` vs `fallback_ambiguous` vs `fallback_duration_mismatch`. |

## 10. Test corpus predictions

After Round 4 D2 lands, expected movement on the 16 remaining unidentified slugs:

| Slug | Bucket | Pre-Round-4 reason | Expected post-Round-4 | Confidence |
|---|---|---|---|---|
| `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` | D | (already identified in R2 — skip) | already identified | n/a |
| `moderat-reminder_official_video-cjwsnuoazug` | B | acoustid_all_unlinked | **identified via fallback** | high |
| `the_byrds-eight_miles_high_live_at_fillmore_east_1970...` | B | acoustid_all_unlinked | identified via fallback (if MB has live recording) OR `fallback_no_match` | medium |
| `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr...` | B | acoustid_all_unlinked | `fallback_ambiguous` likely — 11+ word title overwhelms MB search | low |
| `charlie_puth_attention` | A | acoustid_no_results | **identified via fallback** | high |
| `balthazar-changes_official_video-p3jb998acqo` | A | acoustid_no_results | identified via fallback | medium-high |
| `joesef_comedown_official_video_zaprrzdhyiw` | A | acoustid_no_results | identified via fallback | medium |
| `nightbus-angles_mortz_official_video-igxitfxkd1i` | A | acoustid_no_results | identified via fallback | medium |
| `olivia_dean_dive_acoustic_yylsa4m2zzm` | A | acoustid_no_results | identified via fallback | medium (acoustic version) |
| `angus_julia_stone-harvest_moon-...-paste_studios-...` | A | acoustid_no_results | `fallback_no_match` (live, not in MB) | low |
| `sting-shape_of_my_heart_live_at_the_rijksmuseum-...` | A | acoustid_no_results | `fallback_no_match` (specific live, not in MB) | low |
| `ren_x_chinchilla_chalk_outlines` | A | acoustid_no_results | identified via fallback (if MB has it) | low-medium |
| `it_could_happen_to_you_2_render` | A | acoustid_no_results | `fallback_no_match` (DAW render) | very low |
| `she_s_hot_tea-p_3xutn8res` | A | acoustid_no_results | `fallback_no_match` (user-render) | very low |
| `jamel_debbouze_stromae-alors_on_danse_le_tube-...` | A | acoustid_no_results | identified via fallback (Alors On Danse is a major hit) | medium |
| `submotion_orchestra-finest_hour_album_version-...` | B | acoustid_all_unlinked | identified via fallback | medium-high |
| `cvt_380_m` | F | track_too_short | `track_too_short` (unchanged) | n/a |

**Expected total: ~6-9 additional identifications.** Combined with current 14/30 → 20-23/30 (67-77%). Meets the 75% target at the upper end; just-misses at the lower end. Honest estimate.

## 11. Round 4 commit structure

Two commits (per spec D2 → D3 sequencing):

1. **`feat(identify): MB text-search fallback + reason disambiguation (Round 4 D2)`**
   - analyze/text/slug_parser.py (new — moved + extended from lyrics.py)
   - analyze/text/__init__.py
   - analyze/clients/musicbrainz.py (add search_recording wrapper)
   - analyze/stages/identify.py (fallback trigger + reason disambiguation + SCHEMA_VERSION=4 + acoustid_unenriched MBID retry + .acoustid_raw.json always)
   - webui/webui/stage_manifest.py (schema_version=4 + new params)
   - webui/webui/lyrics.py (refactor to import from analyze.text.slug_parser)
   - webui/tests/test_identify_round4.py (new)
   - webui/tests/test_slug_parser.py (new — for the shared module)
   - webui/tests/test_lyrics.py (update for the import refactor)

2. **`feat(webui): Metadata card trust signaling for fallback/unenriched (Round 4 D3)`**
   - webui/static/js/sidebar/metadata-card.js (render the source note)
   - webui/static/css/track.css (add .metadata-card-source-note)
   - webui/tests-js/metadata-card.test.js (update)

## 12. C2-style prompts

### D2 prompt (backend implementation)

```
You are Subagent D2 for Round 4 of the MusIQ-Lab identify-pipeline overhaul.
Implement the backend changes for the MusicBrainz text-search fallback.

Working directory: <PROJECT_PATH>/.claude/worktrees/identify-overhaul
Branch: worktree-identify-overhaul (do NOT touch the main worktree)

READ FIRST:
  1. docs/superpowers/identify-overhaul/round-4-d1-fallback-design.md (your spec)
  2. docs/superpowers/identify-overhaul/round-4-prereq-blocker-b.md (trigger conditions)
  3. analyze/stages/identify.py (current SCHEMA_VERSION=3 state)
  4. analyze/clients/acoustid.py (lookup() return shape)
  5. analyze/clients/musicbrainz.py (existing httpx client; you'll extend it)
  6. webui/webui/lyrics.py (functions to refactor: _strip_yt_id_tail, _slug_to_display, _parse_filename, identify_track)
  7. analyze/sidecar.py (params-hash invalidation)
  8. webui/webui/stage_manifest.py (must bump schema_version to 4)
  9. webui/tests/test_stage_manifest_in_sync.py (drift test — must pass)

## Implementation tasks

### A. Create analyze/text/slug_parser.py (new)

Move from webui/webui/lyrics.py:
- _YT_ID_TAIL_RE pattern (line 91)
- _strip_yt_id_tail (lines 94-110)
- _slug_to_display (lines 113-123)
- _parse_filename (lines 126-133)

Add new functions:
- clean_title(title) — per D1 §2 _NOISE_TOKEN_RE
- identify_track_from_slug(mp3_path, duration_sec) — moved from lyrics.py:identify_track (lines 136-154); reads ID3 via mutagen with slug fallback

Export from analyze/text/__init__.py.

### B. webui/webui/lyrics.py refactor

- Delete the moved functions
- Import from analyze.text.slug_parser:
    from analyze.text.slug_parser import (
        _strip_yt_id_tail, _slug_to_display, _parse_filename,
        identify_track as identify_track_from_slug,
    )
- Re-export `identify_track` (so existing webui code keeps working) as a thin alias
- Update webui/tests/test_lyrics.py imports to use the new path

### C. analyze/clients/musicbrainz.py

Add a new function `search_recording(artist: str, title: str, duration_sec: float, limit: int = 10) -> list[dict]`:
- Build MB Lucene query: `artist:"<artist>" AND recording:"<title>"` (or just `recording:"<title>"` if no artist)
- GET /ws/2/recording/?query=...&limit=10&fmt=json
- Respect 1 req/s (use time.sleep(1.0) after each call; analyze is sync at this layer)
- Handle 429 (wait + retry once); 503 (retry per existing pattern); 4xx other (raise)
- Return the parsed `recordings` array
- Use the existing User-Agent constant from keys.py

Add a helper `score_candidates(candidates, fp_duration_sec, target_title)`:
- For each candidate, compute dur_variance and title_similarity per D1 §3
- Reject if dur_variance > 0.05 or title_similarity < 0.85
- Return the lowest (dur_variance, -title_similarity) tuple, or None if no candidate scores
- Reject ambiguous (top-2 within 0.02) — return None with a "fallback_ambiguous" flag accessible to the caller

Add `lookup_release_metadata(mbid)`:
- GET /ws/2/recording/{mbid}?inc=releases&fmt=json
- Return {album, year, ...} for the earliest release (use release-events to pick the earliest)
- (This addresses the F8 debt from R1 — earliest release vs releases[0])

### D. analyze/stages/identify.py

1. SCHEMA_VERSION = 4 (line 32)

2. Update DEFAULT_PARAMS (line 33-38) to include:
       "fallback_enabled": True,
       "fallback_min_title_similarity": 0.85,
       "fallback_max_duration_variance": 0.05,

3. Reason disambiguation (per D1 §4): replace the "no AcoustID match above threshold" reason with one of:
   - acoustid_no_results (results == [])
   - acoustid_below_threshold (all linked results below threshold)
   - acoustid_all_unlinked (above-threshold but no recordings)
   - acoustid_transient_error (HTTP 5xx after retries)
   The acoustid_client.lookup() should return a discriminator (e.g. an enum or a tuple) that identify.run() maps to the reason string.

4. Fallback trigger: after the silence-strip block resolves match=None with reason in {acoustid_no_results, acoustid_all_unlinked}, attempt fallback:
   - Parse slug via analyze.text.slug_parser
   - Read ID3 fallback if artist or title empty
   - clean_title() the title for MB search
   - Call musicbrainz_client.search_recording(artist, title, fp.duration)
   - Pass result through score_candidates()
   - If a candidate scores: write source="fallback", match_method="mb_text_search", mbid_recording=cand.id, title=cand.title, artist=cand.artist_credit[0].name, duration_variance_pct=score.dur_variance, title_similarity=score.title_sim. Then call lookup_release_metadata(mbid) for album/year.
   - If no candidate: write identified=False with reason="fallback_no_match" (or fallback_ambiguous/fallback_duration_mismatch/etc per the reject reason)

5. acoustid_unenriched MBID retry: when AcoustID returned a linked MBID but MB lookup failed, retry MB ONCE more (1s wait). If still fails, persist source="acoustid_unenriched" (current R3 behavior; do NOT fall through to text-search — we already have a confidence-validated MBID).

6. Always write .acoustid_raw.json (incl. on empty results) per R3 inherited debt.

### E. webui/webui/stage_manifest.py

Update identify entry: schema_version=4, params dict includes fallback_* keys.

### F. webui/tests/test_identify_round4.py (new)

Required tests:
- test_fallback_fires_on_acoustid_no_results
- test_fallback_fires_on_acoustid_all_unlinked
- test_fallback_does_not_fire_on_acoustid_below_threshold (per Blocker B)
- test_fallback_does_not_fire_when_acoustid_match_found
- test_fallback_rejects_low_title_similarity
- test_fallback_rejects_high_duration_variance
- test_fallback_rejects_ambiguous_top_2
- test_fallback_uses_id3_when_slug_unparseable
- test_acoustid_unenriched_path_retries_mb_once_then_persists
- test_reason_disambiguation_no_results
- test_reason_disambiguation_all_unlinked
- test_acoustid_raw_cache_written_on_empty_results
- test_slug_parser_handles_charlie_puth (no artist/title separator)
- test_slug_parser_handles_warhaus (real corpus)
- test_slug_parser_id3_fallback
- test_schema_version_is_4
- test_clean_title_strips_official_video
- test_clean_title_preserves_live_at_when_in_title
- test_lyrics_imports_from_slug_parser_still_work

Plus integration tests (real ffmpeg + real fpcalc + MOCKED MB):
- test_integration_charlie_puth_fallback_identifies (mock MB to return Charlie Puth Attention at duration 211s; expect identified=true, source=fallback)
- test_integration_warhaus_fallback_identifies (mock MB to return Warhaus Love's a Stranger)

### G. Verification

```bash
cd "<PROJECT_WSL_PATH>/.claude/worktrees/identify-overhaul"
source .venv/bin/activate  # fall back to main worktree .venv if absent
python -m pytest webui/tests/test_identify_round4.py webui/tests/test_identify_round3.py webui/tests/test_identify_round2.py webui/tests/test_stage_manifest_in_sync.py webui/tests/test_lyrics.py webui/tests/test_slug_parser.py -x -q
```

All Round 4 tests + Round 2/3 regression tests + manifest drift + lyrics refactor tests must pass.

### H. Commit

```
feat(identify): MB text-search fallback + reason disambiguation (Round 4 D2)

- Adds MusicBrainz text-search fallback when AcoustID returns no usable
  result. Seed: slug parser refactored from webui/webui/lyrics.py into
  shared analyze/text/slug_parser.py; ID3 fallback for non-ASCII slugs.
- Accept fallback match only when title_similarity > 0.85 AND
  duration_variance < 5%. Reject ambiguous (top-2 within 0.02).
- SCHEMA_VERSION 3 → 4 (new `source`, `match_method`,
  `duration_variance_pct`, `title_similarity` fields).
- reason disambiguation: acoustid_no_results | acoustid_below_threshold
  | acoustid_all_unlinked | fallback_no_match | fallback_ambiguous etc.
- acoustid_unenriched path: retry MB once before persisting as
  unenriched.
- .acoustid_raw.json now written on empty results too (R3 debt).
- Legacy bridge in cached() protects all 24 identified=true caches
  across the schema bump.

Refs spec §D1, round-4-d1-fallback-design.md, R3 Pass 2 inherited debt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Hard rules
- Edit ONLY listed files. Especially: do not touch _preserve_or_write, _atomic_write_text, sidecar.py, the legacy bridge, the silence-strip helpers from C2.
- DO NOT push.
- DO NOT commit if pytest fails.
```

### D3 prompt (UI implementation — runs after D2 lands)

```
You are Subagent D3 for Round 4: webui Metadata card trust signaling.

Working directory: <PROJECT_PATH>/.claude/worktrees/identify-overhaul
Branch: worktree-identify-overhaul (do NOT touch main worktree)

READ FIRST:
  docs/superpowers/identify-overhaul/round-4-d1-fallback-design.md §5
  webui/static/js/sidebar/metadata-card.js (current renderer)
  webui/static/css/track.css (track styles)
  webui/tests-js/metadata-card.test.js (existing tests)

## Tasks

### A. webui/static/js/sidebar/metadata-card.js

When the renderer detects identify.source === "fallback":
- Render a `<div class="metadata-card-source-note metadata-card-source-fallback" title="...">via text-match search</div>` directly under the card title.
- The title attribute should contain: `via MusicBrainz text-match search&#10;duration variance: <pct>%&#10;title similarity: <pct>%` where the values come from identify.duration_variance_pct and identify.title_similarity (multiply by 100, round to 1 decimal).

When identify.source === "acoustid_unenriched":
- Render `<div class="metadata-card-source-note metadata-card-source-unenriched" title="AcoustID matched but full metadata unavailable">metadata unenriched</div>`.

When identify.source in {"acoustid", "acoustid_stripped"}: no note.

When identify.source === "none" (or absent): the card already returns "" for unidentified tracks — no change.

### B. webui/static/css/track.css

Add (in the metadata-card section):

```css
.metadata-card-source-note {
  font-style: italic;
  font-size: 0.85em;
  color: var(--text-muted);
  margin-top: 2px;
  cursor: help;
}
```

### C. webui/tests-js/metadata-card.test.js

Update or extend with:
- test: source=fallback renders the italic note with tooltip
- test: source=acoustid_unenriched renders a different note
- test: source=acoustid renders no note (regression for canonical)
- test: source=acoustid_stripped renders no note
- test: missing source field renders no note (legacy compat)
- test: tooltip contains the variance + similarity values formatted as percentages

### D. Visual smoke

Start webui (or use the running instance on :8765), navigate to a fallback-identified track once D2's identify reruns the corpus. Screenshot the sidebar card. Attach the screenshot path to your final report (the screenshot itself doesn't need to be committed).

### E. Commit

```
feat(webui): Metadata card trust signaling for fallback/unenriched (Round 4 D3)

When the identify stage returns source="fallback" or
source="acoustid_unenriched", render an italic info note under the
Metadata card title with tooltip showing match details.

- source=fallback: "via text-match search" with tooltip showing
  duration variance + title similarity
- source=acoustid_unenriched: "metadata unenriched" with tooltip
  explaining the partial match
- source=acoustid / acoustid_stripped: no note (canonical match)

CSS: --text-muted color (informational, NOT --status-warn) per spec §2.5.

Refs spec §D3, round-4-d1-fallback-design.md §5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Hard rules
- ONLY metadata-card.js, track.css, metadata-card.test.js.
- DO NOT change the renderer's behavior for identified=false tracks (they should still return "").
- DO NOT push.
```

---

## Sources

- `webui/webui/lyrics.py` (existing slug parser at lines 91-154)
- Blocker B report (`docs/superpowers/identify-overhaul/round-4-prereq-blocker-b.md`)
- spec §D1 (`docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md` lines 506-561)
- R3 Pass 2 inherited debt (`docs/superpowers/identify-overhaul/round-3-final-review.md` §9)
- MusicBrainz Recording Search docs (https://musicbrainz.org/doc/MusicBrainz_API/Search)
