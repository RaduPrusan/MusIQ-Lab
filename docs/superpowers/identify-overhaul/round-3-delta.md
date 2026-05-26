# Round 3 — Delta Report

**Generated:** 2026-05-12T19:40:47+00:00

Re-ran `analyze --stages-only identify` against 15 Bucket-A/B slugs after C2's silence-strip preprocessing + `SCHEMA_VERSION=3` landed (worktree SHA `ea7ab72`). Spec: [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md) §C2.

## Aggregate

| Scope | Before (post-R2) | After (post-R3) | Delta |
|---|---|---|---|
| 30-track corpus identified | 14 / 30 (46.7%) | 14 / 30 (46.7%) | +0 |
| Full cache identified | 24 / 40 (60.0%) | 24 / 40 (60.0%) | +0 |

Batch wall time: 650.44s

## Regression gate verdict

**PASS** — zero `identified=true → false` transitions on the 24 pre-R3 identified caches. `_preserve_or_write` guard + legacy-cache bridge held.

## Movers

### `identified: false → true` (0)

(none)

### `identified: true → false` (0)

(none — regression gate held)

### Reason changed, still `identified: false` (0)

(none)

## Silence-strip behavior

Per-slug. `lead (R1)` is the leading-silence ffmpeg silencedetect measured during the Round-1 probe. `gate fired?` reports whether `silence_strip_gate_sec=0.3` should have triggered the strip. `acoustid_stripped` is whether the stripped-fingerprint AcoustID lookup produced the match (per the structured log line).

| Slug | Bucket | Lead (R1) s | Gate fired? | Stripped path used? | Identified now? | log source |
|---|---|---|---|---|---|---|
| `balthazar-changes_official_video-p3jb998acqo` | A | 0.00 | no | no | no | `None` |
| `charlie_puth_attention` | A | 0.45 | yes | no | no | `None` |
| `it_could_happen_to_you_2_render` | A | 0.82 | yes | no | no | `None` |
| `jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0` | A | 1.94 | yes | no | no | `None` |
| `joesef_comedown_official_video_zaprrzdhyiw` | A | 0.00 | no | no | no | `None` |
| `nightbus-angles_mortz_official_video-igxitfxkd1i` | A | 0.00 | no | no | no | `None` |
| `olivia_dean_dive_acoustic_yylsa4m2zzm` | A | 0.00 | no | no | no | `None` |
| `ren_x_chinchilla_chalk_outlines` | A | 6.47 | yes | no | no | `None` |
| `she_s_hot_tea-p_3xutn8res` | A | 0.00 | no | no | no | `None` |
| `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw` | A | 1.49 | yes | no | no | `None` |
| `submotion_orchestra-finest_hour_album_version-qplldpndsx8` | A | 0.78 | yes | no | no | `None` |
| `angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk` | B | 0.00 | no | no | no | `None` |
| `moderat-reminder_official_video-cjwsnuoazug` | B | 0.00 | no | no | no | `None` |
| `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a` | B | 0.00 | no | no | no | `None` |
| `the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe` | B | 0.00 | no | no | no | `None` |

## Bucket A analysis

- Gated tracks (lead silence > 0.3s): **6** (`charlie_puth_attention`, `it_could_happen_to_you_2_render`, `jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0`, `ren_x_chinchilla_chalk_outlines`, `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw`, `submotion_orchestra-finest_hour_album_version-qplldpndsx8`)
- Of those, newly identified via stripped fingerprint: **0** (—)
- Zero-silence tracks (lead silence ≤ 0.3s): **5** (`balthazar-changes_official_video-p3jb998acqo`, `joesef_comedown_official_video_zaprrzdhyiw`, `nightbus-angles_mortz_official_video-igxitfxkd1i`, `olivia_dean_dive_acoustic_yylsa4m2zzm`, `she_s_hot_tea-p_3xutn8res`)
- Of those still unidentified (expected — Round 4 work): **5** (any unexpected clearance: none)

## Bucket B analysis

- Bucket B (top score ≥0.85, unlinked): **4** slugs
- Newly identified via stripped path: **0** (none — expected, stripping does not help when raw fingerprint is already strong but unlinked)

## Performance

| Metric | Round 2 | Round 3 | Note |
|---|---|---|---|
| Mean wall time / slug | 27.5s | 43.36s | n=15 (R3 ran 15, R2 ran 30) |
| Median wall time / slug | — | 42.92s | |
| Total batch wall time | 826.87s | 650.44s | |

**Flag:** mean wall time 43.4s is >50% higher than R2's 27.5s. Investigate silence-strip overhead.

## Source references

- Spec: [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md)
- Round 1 probe: [`round-1-a2-corpus-probe.md`](./round-1-a2-corpus-probe.md)
- Round 2 delta: [`round-2-delta.md`](./round-2-delta.md)
- C2 silence-strip design: [`round-3-c1-silence-strip-design.md`](./round-3-c1-silence-strip-design.md)
- Per-slug raw fragments: [`_fragments-round3/`](./_fragments-round3/)
