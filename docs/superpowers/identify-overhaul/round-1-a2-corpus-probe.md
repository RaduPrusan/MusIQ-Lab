# Round 1 — Subagent A2 — Empirical Corpus Probe

Generated: 2026-05-12T17:06:52.034485+00:00

Probed 30 unidentified slugs from the corpus with fpcalc + AcoustID + ffmpeg silencedetect. Read-only; live cache untouched.

## Bucket framework

- **A**: AcoustID returns `results: []` — fingerprint not in DB, or windows misaligned by leading silence.
- **B**: top result is high-score (≥0.85) and unlinked (`recordings: []`), no linked result below it. Fingerprint claimed by an AcoustID ID that was never linked to a MusicBrainz recording.
- **C**: top score is below 0.85 but at least one linked result is above 0.5. Threshold issue.
- **D**: results exist with linked recordings *below* a higher-score unlinked result — the current `max-by-score-then-bail-if-no-recordings` logic in `acoustid_client.lookup` throws away the correct row.
- **E**: fingerprint computed but AcoustID HTTP/key/status error.
- **F**: fpcalc failed (codec, duration <30s, missing file).
- **R**: AcoustID returns a high-score linked top result — current production `acoustid_client.lookup` WOULD identify this. In the `mb_503` corpus this is the expected state (only MB step failed historically); they should clear via `scripts/identify-retry.*`. In the `no_match` corpus it indicates the original analyze run hit a transient AcoustID issue that has since resolved.
- **Z**: novel / hybrid pattern — see notes per slug.

## Aggregate

| Bucket | Count | Slugs |
|--------|-------|-------|
| **A** | 11 | `balthazar-changes_official_video-p3jb998acqo`, `charlie_puth_attention`, `it_could_happen_to_you_2_render`, ... (+8) |
| **B** | 4 | `angus_julia_stone-harvest_moon-11_17_2017-paste_st`, `moderat-reminder_official_video-cjwsnuoazug`, `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_str`, ... (+1) |
| **D** | 1 | `warhaus_love_s_a_stranger_official_video_gsjdhd0st` |
| **F** | 1 | `cvt_380_m` |
| **R** | 13 | `awolnation-run_official_audio-mw2kkyju9gy`, `baleen_unmedicated`, `baxter_dury-prince_of_tears-zppakk4xk74`, ... (+10) |

## Leading-silence stats per bucket

| Bucket | n | mean leading (s) | p90 leading (s) | max leading (s) | mean trailing (s) | max trailing (s) |
|--------|---|------------------|-----------------|-----------------|-------------------|------------------|
| **A** | 11 | 1.09 | 1.94 | 6.47 | 0.17 | 0.81 |
| **B** | 4 | 0.00 | 0.00 | 0.00 | 0.17 | 0.70 |
| **D** | 1 | 0.00 | 0.00 | 0.00 | 0.66 | 0.66 |
| **R** | 13 | 0.40 | 1.05 | 3.21 | 0.20 | 0.90 |

### Bucket A (11 slugs)

**Fix path:** Round 3 (silence-strip preprocessing) — should unlock commercial cuts; Round 4 (MB text-search fallback) for niche / live / non-commercial / DAW renders.

| Slug | snap | dur (s) | lead silence | top score | top linked | top mbid (if any) | top recording |
|------|------|---------|--------------|-----------|------------|-------------------|----------------|
| `balthazar-changes_official_video-p3jb998acqo` | no_match | 200.1 | 0.00 |  |  | `` |  |
| `charlie_puth_attention` | no_match | 301.7 | 0.45 |  |  | `` |  |
| `it_could_happen_to_you_2_render` | no_match | 139.2 | 0.82 |  |  | `` |  |
| `jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_j` | no_match | 207.6 | 1.94 |  |  | `` |  |
| `joesef_comedown_official_video_zaprrzdhyiw` | no_match | 272.0 | 0.00 |  |  | `` |  |
| `nightbus-angles_mortz_official_video-igxitfxkd1i` | no_match | 268.9 | 0.00 |  |  | `` |  |
| `olivia_dean_dive_acoustic_yylsa4m2zzm` | no_match | 199.4 | 0.00 |  |  | `` |  |
| `ren_x_chinchilla_chalk_outlines` | no_match | 344.7 | 6.47 |  |  | `` |  |
| `she_s_hot_tea-p_3xutn8res` | no_match | 359.7 | 0.00 |  |  | `` |  |
| `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7` | no_match | 282.8 | 1.49 |  |  | `` |  |
| `submotion_orchestra-finest_hour_album_version-qplldpnds` | no_match | 255.1 | 0.78 |  |  | `` |  |

### Bucket B (4 slugs)

**Fix path:** Round 4 (MB text-search fallback). The AcoustID match exists but is unlinked, so no MBID is reachable even after the Bucket-C bug fix. Long-term: a write-side submit-back path.

| Slug | snap | dur (s) | lead silence | top score | top linked | top mbid (if any) | top recording |
|------|------|---------|--------------|-----------|------------|-------------------|----------------|
| `angus_julia_stone-harvest_moon-11_17_2017-paste_studios` | no_match | 259.6 | 0.00 | 0.943 | no | `` |  |
| `moderat-reminder_official_video-cjwsnuoazug` | no_match | 206.1 | 0.00 | 0.938 | no | `` |  |
| `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_a` | no_match | 326.5 | 0.00 | 0.986 | no | `` |  |
| `the_byrds-eight_miles_high_live_at_fillmore_east_1970_p` | no_match | 592.1 | 0.00 | 0.926 | no | `` |  |

### Bucket D (1 slugs)

**Fix path:** Round 2 (Bucket-C bug fix in `acoustid_client.lookup`) — iterate results, return first linked above threshold. Cheapest, lowest-risk fix in the entire overhaul.

| Slug | snap | dur (s) | lead silence | top score | top linked | top mbid (if any) | top recording |
|------|------|---------|--------------|-----------|------------|-------------------|----------------|
| `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` | no_match | 210.1 | 0.00 | 0.984 | no | `` |  |

### Bucket F (1 slugs)

**Fix path:** Out of scope for identification - short / corrupt / missing files. Pipeline should fail-soft, NOT silently demote previously-identified records.

| Slug | snap | dur (s) | lead silence | top score | top linked | top mbid (if any) | top recording |
|------|------|---------|--------------|-----------|------------|-------------------|----------------|
| `cvt_380_m` | no_match | 7.4 | — |  |  | `` |  |

### Bucket R (13 slugs)

**Fix path:** Re-run identify. For `mb_503` slugs this is the operational `scripts/identify-retry.*` path. After Round 2's SCHEMA_VERSION bump, the staleness chip in the sidebar will surface the re-run prompt automatically.

| Slug | snap | dur (s) | lead silence | top score | top linked | top mbid (if any) | top recording |
|------|------|---------|--------------|-----------|------------|-------------------|----------------|
| `awolnation-run_official_audio-mw2kkyju9gy` | mb_503 | 241.9 | 0.00 | 0.987 | yes | `36268ba8` | AWOLNATION — Run (Beautiful Things) |
| `baleen_unmedicated` | mb_503 | 193.8 | 0.00 | 0.982 | yes | `d8de10d1` | Baleen — Unmedicated |
| `baxter_dury-prince_of_tears-zppakk4xk74` | mb_503 | 188.8 | 3.21 | 0.958 | yes | `c1b43dcf` | Baxter Dury — Prince of Tears |
| `buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w` | mb_503 | 227.2 | 0.00 | 0.973 | yes | `d9606420` | Ali Kuru — Yuregine Deprem |
| `crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c` | mb_503 | 188.0 | 0.00 | 0.976 | yes | `2899a0fa` | Crippled Black Phoenix — In Bad Dreams |
| `editors_life_is_a_fear` | mb_503 | 264.2 | 0.00 | 0.993 | yes | `ce0d7801` | Editors — Life Is a Fear |
| `editors_life_is_a_fear_alternative` | mb_503 | 303.4 | 0.64 | 0.999 | yes | `0cd265db` | Editors — Alternative: Life Is a Fear |
| `emika-sing_to_me-k9sdbzm8pgk` | mb_503 | 253.0 | 0.32 | 0.953 | yes | `3518434b` | Emika — Sing to Me |
| `fanfare_ciocarlia_asfalt_tango` | mb_503 | 372.9 | 1.05 | 0.991 | yes | `0e1474c0` | Fanfare Ciocărlia — Asfalt Tango |
| `flunk_on_my_balcony` | mb_503 | 179.6 | 0.00 | 0.969 | yes | `0985f617` | Flunk — On My Balcony |
| `gorillaz-silent_running_ft_adeleye_omotayo_official_vid` | mb_503 | 215.1 | 0.00 | 0.990 | yes | `8d74e3f5` | Allan McLoud/Fraser — Silent Running |
| `hurt-ty-bldf8bsw` | mb_503 | 374.5 | 0.00 | 0.978 | yes | `2eb2a914` | ? — ? |
| `notre-dame_est-3frubz9yhim` | mb_503 | 147.2 | 0.00 | 0.980 | yes | `a8fb3076` | Anomalie — Notre-Dame Est |

## Call-outs

### Surprising AcoustID responses

Slugs where the AcoustID payload contains evidence the current code can't reach today, or where today's AcoustID response disagrees with the cached identify.json reason string:
- **Bucket D**: correct linked match present below a higher-score unlinked top result. Round 2 bug fix unlocks.
- **Bucket C**: top score below 0.85 but a linked recording exists. Round 2 threshold recalibration unlocks.
- **Bucket R + `no_match` snapshot**: cached `identify.json` says "no AcoustID match above threshold" but the live API now returns a usable linked recording. Either the AcoustID DB was updated since the original analyze, or the original run hit a transient gap.

- `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` — bucket D, top score 0.984
    - Best linked candidate: score=0.951, `8feaaf3e-8c7c-4d57-9503-298a56b1c920` — Warhaus — Love’s a Stranger

### Mangled slug guesses (Round 4 fallback risk)

Slugs whose derived artist/title is so noisy that a MusicBrainz text-search fallback may struggle. Round 4 design should pay attention to these.

- `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a` → artist=`Orchestral Suite` title=`No 3 In D Major Ii Air On A G String` (title has 11 words)
- `hurt-ty-bldf8bsw` → artist=`Hurt` title=`` (empty artist or title after cleaning)

### Easy wins (Round 2 alone, plus mb_503 retry path)

Slugs that bucket as **D** (max-by-score bug) or **C** (threshold), plus bucket **R** entries from the `no_match` corpus (current code already identifies them - the only reason they're in this corpus is that the original analyze run hit a transient AcoustID issue that has since resolved). The `mb_503` entries also fall in bucket R and are addressable via `scripts/identify-retry.*` rather than a code fix.

- `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` - bucket D, expect MBID `8feaaf3e-8c7c-4d57-9503-298a56b1c920` at score 0.951

### Hard cases (need Rounds 3 + 4 combined)

Slugs that bucket as **A** (zero AcoustID results) — Round 3 silence-strip may rescue commercial cuts; everything else falls through to Round 4 MB text-search fallback. The live/acoustic/niche cuts will almost certainly need Round 4.

- `balthazar-changes_official_video-p3jb998acqo` — leading silence 0.00s (likely commercial — silence-strip should help)
- `charlie_puth_attention` — leading silence 0.45s
- `it_could_happen_to_you_2_render` — leading silence 0.82s
- `jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0` — leading silence 1.94s
- `joesef_comedown_official_video_zaprrzdhyiw` — leading silence 0.00s (likely commercial — silence-strip should help)
- `nightbus-angles_mortz_official_video-igxitfxkd1i` — leading silence 0.00s (likely commercial — silence-strip should help)
- `olivia_dean_dive_acoustic_yylsa4m2zzm` — leading silence 0.00s
- `ren_x_chinchilla_chalk_outlines` — leading silence 6.47s
- `she_s_hot_tea-p_3xutn8res` — leading silence 0.00s
- `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw` — leading silence 1.49s
- `submotion_orchestra-finest_hour_album_version-qplldpndsx8` — leading silence 0.78s

### mb_503 corpus members — AcoustID-side verification

These slugs already had AcoustID matches at original analyze time but failed on MusicBrainz HTTP 503. We re-probe AcoustID only — the operational `identify-retry` script handles the MB retry.

- `awolnation-run_official_audio-mw2kkyju9gy` — top score 0.987, linked=True → OK (still resolvable)
- `baleen_unmedicated` — top score 0.982, linked=True → OK (still resolvable)
- `baxter_dury-prince_of_tears-zppakk4xk74` — top score 0.958, linked=True → OK (still resolvable)
- `buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w` — top score 0.973, linked=True → OK (still resolvable)
- `crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c` — top score 0.976, linked=True → OK (still resolvable)
- `editors_life_is_a_fear` — top score 0.993, linked=True → OK (still resolvable)
- `editors_life_is_a_fear_alternative` — top score 0.999, linked=True → OK (still resolvable)
- `emika-sing_to_me-k9sdbzm8pgk` — top score 0.953, linked=True → OK (still resolvable)
- `fanfare_ciocarlia_asfalt_tango` — top score 0.991, linked=True → OK (still resolvable)
- `flunk_on_my_balcony` — top score 0.969, linked=True → OK (still resolvable)
- `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` — top score 0.990, linked=True → OK (still resolvable)
- `hurt-ty-bldf8bsw` — top score 0.978, linked=True → OK (still resolvable)
- `notre-dame_est-3frubz9yhim` — top score 0.980, linked=True → OK (still resolvable)

