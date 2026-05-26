# Identify Overhaul — Test Corpus (frozen 2026-05-12)

Snapshot of the 30 cached tracks where `identify.json.identified == false`
at the moment the overhaul plan was written. Each round's agents probe
this list and report per-slug deltas. Generated from a live cache walk —
to regenerate, see "Refresh" at the bottom.

The bucket column reflects the **on-disk reason at snapshot time**, not the
post-investigation classification:

- `mb_503` — AcoustID found a fingerprint and returned a recording MBID,
  but the follow-up MusicBrainz GET failed with HTTP 503. These should
  retry cleanly via `scripts/identify-retry.*`; the corpus includes them
  so Round 1 can verify that the retry path still works after any client
  changes.
- `no_match` — AcoustID's response did not produce a usable result. Round
  1's Subagent A2 probe further classifies each into Buckets A / B / C / D
  / E / F / Z per the spec's §1 framework.

## Corpus

| Bucket | Slug | Duration | Reason (truncated) |
|--------|------|----------|---------------------|
| `mb_503` | `awolnation-run_official_audio-mw2kkyju9gy` | 242s | MusicBrainz error: HTTP 503 |
| `mb_503` | `baleen_unmedicated` | 194s | MusicBrainz error: HTTP 503 |
| `mb_503` | `baxter_dury-prince_of_tears-zppakk4xk74` | 189s | MusicBrainz error: HTTP 503 |
| `mb_503` | `buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w` | 227s | MusicBrainz error: HTTP 503 |
| `mb_503` | `crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c` | 188s | MusicBrainz error: HTTP 503 |
| `mb_503` | `editors_life_is_a_fear` | 264s | MusicBrainz error: HTTP 503 |
| `mb_503` | `editors_life_is_a_fear_alternative` | 303s | MusicBrainz error: HTTP 503 |
| `mb_503` | `emika-sing_to_me-k9sdbzm8pgk` | 253s | MusicBrainz error: HTTP 503 |
| `mb_503` | `fanfare_ciocarlia_asfalt_tango` | 373s | MusicBrainz error: HTTP 503 |
| `mb_503` | `flunk_on_my_balcony` | 180s | MusicBrainz error: HTTP 503 |
| `mb_503` | `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` | 215s | MusicBrainz error: HTTP 503 |
| `mb_503` | `hurt-ty-bldf8bsw` | 374s | MusicBrainz error: HTTP 503 |
| `mb_503` | `notre-dame_est-3frubz9yhim` | 147s | MusicBrainz error: HTTP 503 |
| `no_match` | `angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk` | 260s | no AcoustID match above threshold |
| `no_match` | `balthazar-changes_official_video-p3jb998acqo` | 200s | no AcoustID match above threshold |
| `no_match` | `charlie_puth_attention` | 302s | no AcoustID match above threshold |
| `no_match` | `cvt_380_m` | 7s | no AcoustID match above threshold |
| `no_match` | `it_could_happen_to_you_2_render` | 139s | no AcoustID match above threshold |
| `no_match` | `jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0` | 208s | no AcoustID match above threshold |
| `no_match` | `joesef_comedown_official_video_zaprrzdhyiw` | 272s | no AcoustID match above threshold |
| `no_match` | `moderat-reminder_official_video-cjwsnuoazug` | 206s | no AcoustID match above threshold |
| `no_match` | `nightbus-angles_mortz_official_video-igxitfxkd1i` | 269s | no AcoustID match above threshold |
| `no_match` | `olivia_dean_dive_acoustic_yylsa4m2zzm` | 199s | no AcoustID match above threshold |
| `no_match` | `orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a` | 327s | no AcoustID match above threshold |
| `no_match` | `ren_x_chinchilla_chalk_outlines` | 345s | no AcoustID match above threshold |
| `no_match` | `she_s_hot_tea-p_3xutn8res` | 360s | no AcoustID match above threshold |
| `no_match` | `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw` | 283s | no AcoustID match above threshold |
| `no_match` | `submotion_orchestra-finest_hour_album_version-qplldpndsx8` | 255s | no AcoustID match above threshold |
| `no_match` | `the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe` | 592s | no AcoustID match above threshold |
| `no_match` | `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` | 210s | no AcoustID match above threshold |

## A note on `cvt_380_m`

7 seconds, no slug context. Almost certainly a partial / corrupt MP3 that
fpcalc can fingerprint but AcoustID will never match — possibly a render
artifact. Round 1's A2 should flag tracks under 30 s for separate
handling: Chromaprint needs ≥ 6 s of audio for a meaningful fingerprint
but the score quality degrades sharply below ~20 s and AcoustID's own
matching backs off below 30 s.

## A note on `it_could_happen_to_you_2_render` and `she_s_hot_tea-p_3xutn8res`

The "_render" / "p_3xutn8res" suffixes suggest these are user-rendered
mixes or DAW exports, not commercial releases. Likely permanent Bucket-A
(no fingerprint exists). The MB text-search fallback in Round 4 should
still try; if it fails, that's the correct outcome.

## Tracks that should "easily" identify

These are well-known commercial releases. If any of these remain
unidentified after all four rounds, something is wrong:

- `charlie_puth_attention` — Atlantic Records, massive 2017 hit
- `balthazar-changes_official_video-p3jb998acqo` — Play It Again Sam, 2018
- `moderat-reminder_official_video-cjwsnuoazug` — Monkeytown, 2016
- `warhaus_love_s_a_stranger_official_video_gsjdhd0stag` — Play It Again Sam, 2019
- `awolnation-run_official_audio-mw2kkyju9gy` — Red Bull Records, 2015
- `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` — Parlophone, 2023
- `editors_life_is_a_fear` — PIAS, 2015
- `flunk_on_my_balcony` — Beatservice, 2002

## Tracks that "should fail gracefully"

These are live, one-off, or non-commercial. They should fall through to
the MB text-search fallback (Round 4) and either find a close match or
report `identified: false` with `reason: "fallback search returned no
duration match"` — NOT `"no AcoustID match"`:

- `sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw`
- `angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-...`
- `the_byrds-eight_miles_high_live_at_fillmore_east_1970-...`
- `olivia_dean_dive_acoustic_yylsa4m2zzm`

## Refresh

To regenerate this table from the live cache (after the overhaul lands,
or before adding new corpus members):

```bash
cd '<PROJECT_PATH>' && python -X utf8 <<'PY'
import json, pathlib
rows = []
for d in sorted(pathlib.Path("cache").iterdir()):
    if not d.is_dir(): continue
    p = d / "identify.json"
    if not p.is_file(): continue
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("identified"): continue
    reason = (data.get("reason", "") or "")[:60]
    sj = d / f"{d.name}.summary.json"
    duration = ""
    if sj.is_file():
        s = json.loads(sj.read_text(encoding="utf-8"))
        duration = f"{s.get('track', {}).get('duration_sec', 0):.0f}s"
    bucket = "mb_503" if "HTTP 503" in reason else ("no_match" if "no AcoustID" in reason else "other")
    rows.append((bucket, d.name, duration, reason))
rows.sort()
for r in rows:
    print(f"| `{r[0]}` | `{r[1]}` | {r[2]} | {r[3]} |")
PY
```
