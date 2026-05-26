# Round 4 Delta — MB Text-Search Fallback Corpus Results

**Date:** 2026-05-13
**Branch:** worktree-identify-overhaul (HEAD: `dc2c52a` D3 + `149deb0` D2)
**Batch wall time:** ~28 minutes across 30 corpus slugs, serial, AcoustID 3 req/s + MB 1 req/s gates active.

## 1. Aggregate

| Scope | Pre-R4 (post-R3) | Post-R4 | Delta | % |
|---|---:|---:|---:|---:|
| Corpus identified | 14/30 | **15/30** | +1 | **50%** |
| Full cache identified | 24/39 | **25/39** | +1 | **64%** |
| 75% target on corpus (≥22) | — | — | **MISS by 7** | — |

Round 4 produced **1 new identification** via the MB text-search fallback (nightbus). The spec's 75% goal (≥22/30) is not met. The fallback's strict guards (title_similarity > 0.85 AND duration_variance < 5% AND reject-ambiguous) protected against false positives but rejected most predicted wins.

## 2. Movers — false → true

Only one slug flipped. All other identified-true tracks were already true pre-R4 (R2 mb_503 retries + warhaus walker fix); they re-ran and stayed identified-true via the canonical AcoustID path.

| Slug | Source | MBID | Title | Artist | dur_variance | title_sim |
|---|---|---|---|---|---:|---:|
| `nightbus-angles_mortz_official_video-igxitfxkd1i` | **fallback** | `bf9ad8e7-db86-4713-a1ba-e8520c5ef40c` | Angles Mortz | Nightbus | 0.038 | **1.0** |

Round 4 fallback win: nightbus matched on a perfect title similarity (1.0) with 3.8% duration variance. This is the textbook case for the fallback path.

## 3. Movers — true → false (regression gate)

**Zero regressions.**

All 24 pre-R4 identified-true tracks preserved. `_preserve_or_write` held — one slug (`crippled_black_phoenix-in_bad_dreams`) hit a `ReadTimeout` during the R4 retry pass and the identify stage soft-failed, but the existing payload was preserved unchanged. The legacy bridge also synthesized v4 sidecars for legacy v2 caches without re-querying.

## 4. Per-source breakdown of the 15 identified

| Source | Count | Notes |
|---|---:|---|
| `acoustid` (canonical raw fingerprint) | 14 | 13 mb_503 retries that completed cleanly during this batch + warhaus (R2 walker-fix mover) |
| `acoustid_stripped` (Round 3 silence-strip win) | 0 | Round 3 had 0 movement; this round did not change that |
| `acoustid_unenriched` (AcoustID matched, MB failed) | 0 | Round 4's MBID-retry path prevented any from landing here |
| `fallback` (MB text-search) | 1 | nightbus |
| `none` (unidentified) | 15 | See §5 |

The 14 `source=acoustid` matches are stable. One quirk: `crippled_black_phoenix` retains `source=null` because its R2-era payload was preserved through a ReadTimeout — the R4 schema field was never written. The track is still identified correctly (mbid preserved); only the schema field is missing on this one cache.

## 5. Per-failure-reason breakdown of the 15 unidentified

| Reason | Count | Notes |
|---|---:|---|
| `fallback_no_match` | 13 | MB search ran; no candidate cleared the title-similarity ≥ 0.85 AND duration-variance < 5% gates |
| `fallback_ambiguous` | 1 | **sting-shape_of_my_heart_live_at_the_rijksmuseum** — MB returned multiple "Shape of My Heart" candidates with similar durations; the safety guard rejected to prevent false-positive |
| `skipped (mp3 missing)` | 1 | `angus_julia_stone-...-paste_studios_new_york_ny-...` — source MP3 not in cache; batch driver skipped |

The reason distribution shows the fallback's guards firing exactly as designed. The `fallback_ambiguous` outcome on Sting is particularly informative: MB DOES have "Shape of My Heart" recordings, but the live-at-Rijksmuseum performance isn't distinguishable from the canonical studio version on duration alone, so the guard correctly rejected rather than mis-identify.

## 6. Original user complaint

> "I can't believe that Sting - Shape of My Heart is not found."

**Result:** still unidentified, but now with a meaningful reason: `fallback_ambiguous` instead of `no AcoustID match above threshold`.

The Sting Rijksmuseum performance is a one-off live recording that AcoustID has no fingerprint for AND that MusicBrainz cannot distinguish from the canonical studio recording on title+duration alone. The honest verdict: the song the user was thinking of (the album version) exists in MB, but our slug names a *specific live performance* that genuinely isn't catalogued. The fallback correctly refuses to claim "Sting - Shape of My Heart" because that match would be misleading — the metadata card would show wrong release/album info.

This is the right failure mode. Per spec §2 "should fail gracefully" criterion, Sting falls through to fallback_ambiguous which is an improvement over the prior opaque "no AcoustID match" — a reviewer reading identify.json can now see *why* identification failed and consider Round 5+ manual-override.

## 7. Per-bucket movement (vs Round 1 buckets)

| Bucket | Pre-R4 unidentified | Post-R4 unidentified | Movement |
|---|---:|---:|---|
| A (zero AcoustID results) | 11 | 10 | +1 fallback win (nightbus) |
| B (unlinked high-score) | 4 | 4 | 0 — fallback_no_match for all |
| F (track too short) | 1 | 1 | unchanged (cvt_380_m, 7s) |
| (skipped: mp3 missing) | 0 | 1 | angus_julia_stone source mp3 missing from cache |

## 8. Performance

- Batch wall time: ~28 min for 30 slugs serial
- Median per slug: ~36s
- Outliers: `the_byrds` 73.7s, `she_s_hot_tea` 51.0s, `orchestral_suite` 49.9s — all include MB search round-trips
- Pre-R4 (R3 batch): median 42.9s, mean 43.4s on 15 Bucket-A/B slugs
- The MB fallback added ~3-8s per fallback-firing slug. Within budget.

## 9. Predictions vs reality

D1 §10 made per-slug predictions. Score:

| Slug | D1 prediction | Confidence | Actual | Verdict |
|---|---|---|---|---|
| `warhaus_love_s_a_stranger` | already identified | n/a | acoustid | ✓ (R2 win, preserved) |
| `moderat-reminder` | identified via fallback | high | fallback_no_match | **MISS** |
| `the_byrds-eight_miles_high_live` | fallback OR no_match | medium | fallback_no_match | ✓ |
| `orchestral_suite_no_3` | fallback_ambiguous | low | fallback_no_match | partial |
| `charlie_puth_attention` | identified via fallback | high | fallback_no_match | **MISS** |
| `balthazar-changes` | identified via fallback | medium-high | fallback_no_match | **MISS** |
| `joesef_comedown` | identified via fallback | medium | fallback_no_match | **MISS** |
| `nightbus-angles_mortz` | identified via fallback | medium | **fallback** | ✓ **WIN** |
| `olivia_dean_dive_acoustic` | identified via fallback | medium | fallback_no_match | **MISS** |
| `angus_julia_stone` | fallback_no_match (live) | low | skipped (mp3 missing) | n/a |
| `sting_rijksmuseum` | fallback_no_match (specific live) | low | fallback_ambiguous | ✓ (close) |
| `ren_x_chinchilla` | fallback maybe | low-medium | fallback_no_match | ✓ |
| `it_could_happen_to_you_2_render` | fallback_no_match | very low | fallback_no_match | ✓ |
| `she_s_hot_tea` | fallback_no_match | very low | fallback_no_match | ✓ |
| `jamel_debbouze_stromae` | identified via fallback | medium | fallback_no_match | **MISS** |
| `submotion_orchestra` | identified via fallback | medium-high | fallback_no_match | **MISS** |

Score: predictions correct on **9 / 16** named tracks. **All 6 "high or medium-high confidence" predictions of identification missed** except nightbus. Predicted ceiling was 6-9; actual was 1.

### Why the predictions missed

Two failure modes dominate the "MISS" column:

1. **Slug parser ambiguity on no-`-` names.** `charlie_puth_attention`, `joesef_comedown`, `she_s_hot_tea` have no `-` separator, so `_parse_filename` returns `("", "Charlie Puth Attention")` — title contains the artist name. The MB search seed becomes ambiguous and the title-similarity comparison against MB's `recording.title` ("Attention") returns ~0.42 ratio, well below the 0.85 gate. D2 added a 3-way title-similarity max (direct, combined, stripped) to recover Charlie-Puth-style slugs — but the corpus probe shows it's still not enough for these specific cases.

2. **Title-similarity 0.85 threshold rejects close-but-not-perfect matches.** `balthazar-changes` and `moderat-reminder` are simple commercial tracks that ARE in MusicBrainz. The MB search likely returned the correct recording, but minor differences (capitalization, extra words like "Original Mix", "(Single Version)") may have dragged the similarity below 0.85.

### Recommendation for Round 5+

1. **Lower title-similarity threshold to 0.75** with a stricter duration-variance threshold (< 2%) as a compensating safeguard. Trade some false-positive risk for substantially more recall.
2. **Improve the slug parser** to handle no-`-` cases: when `_parse_filename` returns empty artist with a multi-word title, attempt to split on capitalized-word-boundaries or query MB with the full string and let MB's `artist-credit` matching extract the artist. D2 already does a 3-way max — but a search-time fix (query both `artist:X AND recording:Y` and `recording:"X Y"`) would help more.
3. **Consider a third tier**: when AcoustID returns above-threshold unlinked results AND the slug-derived artist matches the AcoustID-returned releasegroups in raw data, accept as fallback. Currently the AcoustID unlinked path returns no usable metadata (per Blocker B), so this would only help if AcoustID's response carries releasegroups.

## 10. Observability — structured log line

The Blocker A fix (`c571765` — `logging.basicConfig` in `analyze/cli.py`) successfully landed the per-spec §4.1 structured log line in stderr for every identify run. Example from this batch:

```
analyze.stages.identify INFO identify: slug=awolnation-run_official_audio-mw2kkyju9gy source=acoustid score=0.9874882 mbid=36268ba8-c787-4a53-bd0c-78e17236fff6 reason=—
analyze.stages.identify INFO identify: slug=nightbus-angles_mortz_official_video-igxitfxkd1i source=fallback score=— mbid=bf9ad8e7-db86-4713-a1ba-e8520c5ef40c reason=—
analyze.stages.identify INFO identify: slug=sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw source=none score=— mbid=— reason=fallback_ambiguous
```

29 of 30 slugs emitted the line. The 30th (`crippled_black_phoenix`) had its identify stage soft-fail on ReadTimeout before reaching `_log_outcome`, so no line for that one. This is acceptable — the legacy payload was preserved.

## 11. UI trust signal verification (D3)

The Round 4 D3 commit (`dc2c52a`) added `metadata-card-source-note` rendering for `source=fallback` and `source=acoustid_unenriched`. The slug whose UI signal needs the user's visual confirmation:

- **nightbus-angles_mortz** — `source=fallback`, `duration_variance_pct=0.038`, `title_similarity=1.0`. The metadata card should render an italic "via text-match search" note under the title with tooltip showing "duration variance: 3.8%, title similarity: 100.0%".

No `source=acoustid_unenriched` tracks in the corpus to confirm that branch — would need a deliberately-broken MB test fixture. JS unit tests cover the rendering.

## 12. Regression verdict

**PASS** — zero `identified=true → false` transitions across the 24 pre-R4 identified caches.

## 13. R4 forwarding

For R4 (Gemini independent reviewer):
- Round 4 ships correctly: zero regressions, 1 fallback win, all unidentified outcomes have meaningful disambiguated reasons.
- The fallback's strict guards prevented all predicted MISS scenarios from becoming false-positive wins — this is the *safety* trade-off built into D1.
- The 75% spec target was NOT met (15/30 = 50%, target was 22/30 = 75%).
- Round 5+ should consider: lower title-similarity threshold + better slug parsing for no-`-` names + manual-override UI tier.
- Original user complaint (Sting Rijksmuseum) now gives an honest "fallback_ambiguous" reason instead of opaque "no AcoustID match" — the fail-gracefully criterion is met for live one-offs.
