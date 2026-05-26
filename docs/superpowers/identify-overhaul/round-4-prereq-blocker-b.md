# Round 4 Pre-req — Blocker B: stripped-fingerprint AcoustID probe

**Date:** 2026-05-12
**Branch:** `worktree-identify-overhaul`
**Refs:** `c571765` (R3 Pass 2 ADVANCE TO ROUND 4), R3 forensic gap on the 6 gated Bucket-A tracks.

## Goal

R3 demonstrated that 6 Bucket-A tracks fail identify even with the `silence_strip_enabled=True` preprocessing path active. R3 did not separate two distinct failure modes:

1. AcoustID's DB doesn't have these fingerprints at all (true cold-start) — Round 4's MusicBrainz text-search fallback is the **only** possible recovery.
2. AcoustID's DB has them, but
   (a) the score sits below the 0.65 in-stage threshold, or
   (b) the AcoustID match is "unlinked" (an AcoustID `id` with no MusicBrainz `recordings` array attached) — meaning the production code's MB-id walk yields nothing even though AcoustID itself is confident.

This probe runs the silence-stripped fingerprints through `/v2/lookup` with **no score gating** (raw API response) so we can see exactly which mode we're in per track.

## Method

For each slug:

1. WSL `ffmpeg -t 150 -y -i <mp3> -af "silenceremove=start_periods=1:start_threshold=-50dB:start_duration=0.3:detection=peak" -ar 44100 -ac 1 -c:a pcm_s16le /tmp/stripped_<slug>.wav` — identical params to `analyze/stages/identify.py:_strip_leading_silence`.
2. `analyze/vendor/chromaprint/fpcalc -json /tmp/stripped_<slug>.wav` — capture fingerprint + duration.
3. POST `https://api.acoustid.org/v2/lookup` form-encoded with `client`, `meta=recordings`, `duration`, `fingerprint`. **No `score`/threshold parameter — we want every hit.**
4. Persist raw response as `_fragments-round3-stripped/<slug>.json`.
5. Serialize calls, 0.4s gap between requests (≤3 req/s).

Raw fragments: `docs/superpowers/identify-overhaul/_fragments-round3-stripped/*.json` (6 files).

## Per-track results

| Slug | Leading silence | Stripped duration | AcoustID status | Top score | Recordings on top hit | Bucket |
|---|---:|---:|---|---:|---:|---|
| `ren_x_chinchilla_chalk_outlines` | 6.47 s | 143 s | `ok`, `results: []` | — | 0 | Hard zero |
| `jamel_debbouze_stromae-alors_on_danse_le_tube-...` | 1.94 s | 148 s | `ok`, `results: []` | — | 0 | Hard zero |
| `sting-shape_of_my_heart_live_at_the_rijksmuseum-...` | 1.49 s | 148 s | `ok`, `results: []` | — | 0 | Hard zero |
| `it_could_happen_to_you_2_render` | 0.82 s | 136 s | `ok`, `results: []` | — | 0 | Hard zero |
| `submotion_orchestra-finest_hour_album_version-...` | 0.78 s | 149 s | `ok`, 1 result | **0.944** | 0 | Unlinked high-score |
| `charlie_puth_attention` | 0.45 s | 149 s | `ok`, `results: []` | — | 0 | Hard zero |

All six probes returned HTTP 200 with `status: ok`. None hit the rate limiter; none returned a transient error. The pattern is real, not a probe artifact.

## Bucket distribution

- **Hard zero (no DB record at all):** 5 / 6 — `ren_x_chinchilla`, `jamel_debbouze`, `sting-shape`, `it_could_happen`, `charlie_puth`.
  AcoustID returned `results: []` even with no threshold. These are pure cold-start: only the Round 4 MB text-search fallback can recover them.
- **Below threshold (DB has it, our 0.65 rejected it):** 0 / 6.
  No track returned results in the 0–0.65 score band. The 0.65 threshold is not the cause of any of the 6 R3 failures.
- **Unlinked high-score (AcoustID match, no MB recording):** 1 / 6 — `submotion_orchestra-finest_hour`.
  AcoustID returned `id: 0168b64a-c5d9-44c2-82f7-ce5f62d7077b` at score **0.944** (well above our 0.65 threshold), but with `recordings: []` — i.e. the AcoustID id exists in their DB but has never been linked to a MusicBrainz recording. Our production code currently relies on the `recordings[*].id` walk for MBID extraction and therefore drops this match on the floor.

## Recommendation for D1 (MB text-search trigger condition)

**Trigger the MB text-search fallback when AcoustID returns _either_ no results _or_ only unlinked high-score results (`recordings: []` on every hit above threshold).** Do **not** trigger on "only below-threshold results" — the probe found zero tracks in that band, so that condition would never fire on this corpus and would add complexity for no benefit.

Concretely, the D1 spec should adopt the simpler **disjunctive** trigger:

> Fall back to MB text-search when, after silence-strip + raw lookup, the AcoustID response yields no extractable MBID — whether because `results == []` (hard zero, 5/6 of R3's residue) or because all results above the score threshold have `recordings == []` (unlinked, 1/6).

Both branches share the same downstream need: a non-fingerprint route to a MusicBrainz recording-id. The "below threshold" branch is empirically empty on R3's residue and should be left out of the v1 trigger to keep the fallback boundary auditable; if a real instance shows up later, a follow-up round can re-open it.

Note for D1 authors: the unlinked-high-score case (submotion) is **not** a usable seed source for MB text-search — the AcoustID response carries only `{id, score}` with no artist/title/releasegroups metadata, because the AcoustID id was never bound to an MB recording. The MB text-search seed will have to come from the **YouTube slug / filename** (already the working hypothesis), not from AcoustID's response.
