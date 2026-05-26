# Round 2 — Delta Report

**Generated:** 2026-05-12T18:24:34.735459+00:00

Re-ran `analyze --stages-only identify` against the 30-track corpus after B1's commits (SHA `baa991b`). See [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md) §B2.

## Aggregate

| Scope | Before | After | Delta |
|---|---|---|---|
| 30-track corpus identified | 0 / 30 (0.0%) | 14 / 30 (46.7%) | +14 |
| Full cache identified | 10 / 40 (25.0%) | 24 / 40 (60.0%) | +14 |

Batch wall time: 826.87s

## Regression gate verdict

**PASS** — zero `identified=true → false` transitions on the 30-track corpus. `_preserve_or_write` guard held.

## Movers

### `identified: false → true` (14)

| Slug | R1 bucket | Score | MBID | Title — Artist |
|---|---|---|---|---|
| `awolnation-run_official_audio-mw2kkyju9gy` | R | 0.987 | `36268ba8-c787-4a53-bd0c-78e17236fff6` | Run (Beautiful Things) — AWOLNATION |
| `baleen_unmedicated` | R | 0.982 | `d8de10d1-d9dc-47db-bf95-92b09a47adf3` | Unmedicated — Baleen |
| `baxter_dury-prince_of_tears-zppakk4xk74` | R | 0.958 | `c45ee266-4d59-4de2-b0a4-3d3247b11c1a` | Prince of Tears — Baxter Dury |
| `buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w` | R | 0.973 | `d9606420-d8f5-449b-af9e-4497e582e38d` | Yuregine Deprem — Ali Kuru |
| `crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c` | R | 0.976 | `2899a0fa-8907-41d8-9f7d-e1a209d219cc` | In Bad Dreams — Crippled Black Phoenix |
| `editors_life_is_a_fear` | R | 0.993 | `ce0d7801-7c20-4baf-9511-961910d6c45e` | Life Is a Fear — Editors |
| `editors_life_is_a_fear_alternative` | R | 0.999 | `0cd265db-6b19-402b-b7da-a8bde6268d00` | Alternative: Life Is a Fear — Editors |
| `emika-sing_to_me-k9sdbzm8pgk` | R | 0.953 | `3518434b-406a-4581-93ec-ebfcbb577717` | Sing to Me — Emika |
| `fanfare_ciocarlia_asfalt_tango` | R | 0.991 | `3f992092-6aee-4382-bd7e-76c6db242580` | Asfalt tango — Fanfare Ciocărlia |
| `flunk_on_my_balcony` | R | 0.969 | `423eeb11-a7d6-4276-8c02-3759fde57484` | On My Balcony (radio edit) — Flunk |
| `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` | R | 0.990 | `8d74e3f5-3e94-4d6f-bff2-66883f906999` | Silent Running — DJ Allan McLoud |
| `hurt-ty-bldf8bsw` | R | 0.978 | `ab7805a8-c161-403d-92bf-a92c8b8e17dc` | Hurt — Nine Inch Nails |
| `notre-dame_est-3frubz9yhim` | R | 0.980 | `a8fb3076-98ba-42c3-9f0b-979ea81bc37a` | Notre-Dame Est — Anomalie |
| `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` | D | 0.951 | `8feaaf3e-8c7c-4d57-9503-298a56b1c920` | Love’s a Stranger — Warhaus |

### `identified: true → false` (0)

(none — regression gate held)

### Reason changed but still `identified: false` (0)

(none)

## Per-bucket movement (R1 framework)

| Bucket | Total | Cleared (now identified) | Remaining (still false) |
|---|---|---|---|
| **A** | 11 | 0 | 11 |
| **B** | 4 | 0 | 4 |
| **D** | 1 | 1 | 0 |
| **F** | 1 | 0 | 1 |
| **R** | 13 | 13 | 0 |

- **Bucket D cleared:** `warhaus_love_s_a_stranger_official_video_gsjdhd0stag`
- **Bucket R cleared:** `awolnation-run_official_audio-mw2kkyju9gy`, `baleen_unmedicated`, `baxter_dury-prince_of_tears-zppakk4xk74`, `buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w`, `crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c`, `editors_life_is_a_fear`, `editors_life_is_a_fear_alternative`, `emika-sing_to_me-k9sdbzm8pgk`, `fanfare_ciocarlia_asfalt_tango`, `flunk_on_my_balcony`, `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg`, `hurt-ty-bldf8bsw`, `notre-dame_est-3frubz9yhim`

## Observability — structured `identify:` log lines

`identify: slug=... source=... score=... mbid=... reason=...` log line emitted for **30 / 30** corpus slugs.

Sample lines (false → true movers):

```
analyze.stages.identify INFO identify: slug=awolnation-run_official_audio-mw2kkyju9gy source=acoustid score=0.9874882 mbid=36268ba8-c787-4a53-bd0c-78e17236fff6 reason=—
analyze.stages.identify INFO identify: slug=baleen_unmedicated source=acoustid score=0.98213345 mbid=d8de10d1-d9dc-47db-bf95-92b09a47adf3 reason=—
analyze.stages.identify INFO identify: slug=baxter_dury-prince_of_tears-zppakk4xk74 source=acoustid score=0.9575422 mbid=c45ee266-4d59-4de2-b0a4-3d3247b11c1a reason=—
analyze.stages.identify INFO identify: slug=buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w source=acoustid score=0.9729035 mbid=d9606420-d8f5-449b-af9e-4497e582e38d reason=—
analyze.stages.identify INFO identify: slug=crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c source=acoustid score=0.9756725 mbid=2899a0fa-8907-41d8-9f7d-e1a209d219cc reason=—
```

## Raw-cache verification — `.acoustid_raw.json`

Expected for each slug that got a non-error AcoustID response: **14** slugs.
Slugs missing `.acoustid_raw.json` despite having a successful AcoustID query: **0**.

## Sidecar migration — pre-existing identified=true caches (NOT re-queried)

Cache slugs that were `identified=true` at baseline and are NOT in the corpus: **10**.

These caches must NOT have been re-queried — the legacy-cache bridge in `cached()` should synthesize a sidecar and skip AcoustID. We did not invoke analyze on these slugs in Round 2, so behavior is implicitly preserved (they were not touched). Slugs:

- `jamiroquai_everyday`
- `leonard_cohen_in_my_secret_life`
- `lou_reed_perfect_day_official_audio_9wxi4kk9zyo`
- `oslo_twins-i_wake_up_slowly_official_visualizer-hyvmgaveilq`
- `radiohead_creep_heads_on_the_radio`
- `the_beatles-the_beatles-strawberry_fields_forever_official_music_video_2015_mix-htuh9z_oey8`
- `the_national-graceless-jpz_guyimhw`
- `two_fingers_deep_jinx`
- `we_re_in_this_together_the_atomica_project-9fycdye4aqc`
- `where_is_my_mind_49fb9hhoo6c`

## AcoustID database delta (Round 1 → Round 2)

No top-result MBID changes between R1 (`_fragments/`) and R2 (`_fragments-round2/`) — AcoustID DB state is stable.

## Stable rows

- Stable `identified=true` (corpus): 0
- Stable `identified=false` (corpus): 16

Slugs still false after Round 2:
- `angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk` — reason: `no AcoustID match above threshold`
- `balthazar-changes_official_video-p3jb998acqo` — reason: `no AcoustID match above threshold`
- `charlie_puth_attention` — reason: `no AcoustID match above threshold`
- `cvt_380_m` — reason: `no AcoustID match above threshold`
- `it_could_happen_to_you_2_render` — reason: `no AcoustID match above threshold`
- `jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0` — reason: `no AcoustID match above threshold`
- `joesef_comedown_official_video_zaprrzdhyiw` — reason: `no AcoustID match above threshold`
- `moderat-reminder_official_video-cjwsnuoazug` — reason: `no AcoustID match above threshold`
- `nightbus-angles_mortz_official_video-igxitfxkd1i` — reason: `no AcoustID match above threshold`
- `olivia_dean_dive_acoustic_yylsa4m2zzm` — reason: `no AcoustID match above threshold`
- `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a` — reason: `no AcoustID match above threshold`
- `ren_x_chinchilla_chalk_outlines` — reason: `no AcoustID match above threshold`
- `she_s_hot_tea-p_3xutn8res` — reason: `no AcoustID match above threshold`
- `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw` — reason: `no AcoustID match above threshold`
- `submotion_orchestra-finest_hour_album_version-qplldpndsx8` — reason: `no AcoustID match above threshold`
- `the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe` — reason: `no AcoustID match above threshold`

## Source MP3 — references

- Spec: [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md)
- Corpus: [`2026-05-12-identify-corpus.md`](../specs/2026-05-12-identify-corpus.md)
- Round 1 baseline: [`round-1-a2-corpus-probe.md`](./round-1-a2-corpus-probe.md)
- Round 1 review: [`round-1-review.md`](./round-1-review.md)
