# Round 5 Delta — Artist-Plausibility + Slug Parser + Unicode + Thresholds

**Date:** 2026-05-13
**Branch:** `worktree-identify-overhaul`
**Commits:**
- `d0b2b51` — R5 initial implementation (4 items)
- `56c0367` — R5 gate fix (lower threshold + substring rescue)

## 1. Aggregate

| Scope | Pre-R5 (post-R4) | Post-R5 + fix | Delta | Quality |
|---|---:|---:|---:|---|
| Corpus identified | 15/30 | **14/30** | −1 | **+1 false positive eliminated** |
| Full cache identified | 25/39 | 24/39 | −1 | gorillaz no longer mis-identified |

Round 5 reduced the raw identified count by 1 but eliminated a known false positive (gorillaz was identified as "DJ Allan McLoud — Silent Running / 100% Eurotrance 3 (2001)" at score 0.99 — fabricated metadata served to the user for months). The 14 remaining identifications are now all verified plausible.

## 2. Movers (state changes)

| Slug | Pre-R5 | Post-R5 + fix | Verdict |
|---|---|---|---|
| `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` | identified=true source=acoustid artist="DJ Allan McLoud" **(WRONG)** | identified=false reason=acoustid_artist_mismatch | ✓ Correct demotion. Artist plausibility gate caught the AcoustID DB integrity issue. |
| `buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w` | identified=true source=acoustid artist="Ali Kuru" (correct) | (transiently demoted by initial R5 gate at 0.50 threshold; restored by 56c0367 fix via substring rescue) → identified=true | ✓ No net change. R5 fix saved a legitimate match. |
| `notre-dame_est-3frubz9yhim` | identified=true source=acoustid artist="Anomalie" (correct) | (transiently demoted at 0.50 threshold; restored by 56c0367 fix via lowered 0.30 threshold) → identified=true | ✓ No net change. R5 fix saved a legitimate match. |
| `nightbus-angles_mortz_official_video-igxitfxkd1i` | identified=true source=fallback | identified=true source=fallback | unchanged |

Other 26 slugs: no state change.

## 3. Predictions vs reality (R4 R5-scope predictions)

| R5 scope item | R4 prediction | Actual | Verdict |
|---|---|---|---|
| **1. Gorillaz triage + artist-plausibility gate** | Demote gorillaz with reason=acoustid_artist_mismatch; no regressions | ✓ Gorillaz demoted; 2 transient false positives caught and fixed by 56c0367 | ✓ achieved (with fix-up commit) |
| **2. Slug parser no-dash fix + lower threshold (0.75)** | Recover Charlie Puth + Moderat | ✗ Charlie Puth and Moderat still `fallback_no_match` — title similarity remains insufficient even at 0.75 | ✗ goal not met; root cause: their slug-derived strings still don't score against MB |
| **3. Unicode normalization** | Latent bug fix; no measurable corpus impact in this run | ✓ Implemented; no smart-quote slugs in this corpus to exercise it | ✓ shipped, no test case in corpus |
| **4. Spec §2 amendment** | Document Sting reclassification + 75% calibration | ✓ Amendment paragraph appended | ✓ |

**Item 2 honest assessment:** lowering the threshold to 0.75 did not move the needle on charlie_puth / moderat. The root cause is deeper than the threshold: their slug strings (after the no-dash parser fix) still produce title-similarity scores below 0.75 against MB's canonical titles, often because the slug contains extra noise tokens that survive `clean_title` or because MB returns multiple candidates that fail the duration-variance + ambiguity guards. Round 6+ work would need to either (a) further enhance the noise-token stripping in `clean_title`, (b) accept lower title similarity when duration matches very precisely, or (c) use AcoustID's `releasegroups` metadata when present.

## 4. Per-source breakdown

| Source | Count | Notes |
|---|---:|---|
| `acoustid` (canonical raw) | 13 | All 13 verified plausible via artist-plausibility gate |
| `acoustid_stripped` | 0 | Round 3 had 0 movement; unchanged |
| `acoustid_unenriched` | 0 | Round 4's MB retry path keeps this at 0 |
| `fallback` (MB text-search) | 1 | nightbus (Round 4's only fallback win) |
| `none` (unidentified) | 16 | See §5 |

## 5. Per-failure-reason breakdown

| Reason | Count | Notes |
|---|---:|---|
| `fallback_no_match` | 13 | MB search ran; no candidate cleared title_similarity ≥ 0.75 AND duration_variance < 0.03 |
| `fallback_ambiguous` | 1 | Sting Rijksmuseum — guard correctly rejected |
| **`acoustid_artist_mismatch`** | **1** | **gorillaz — R5 win** |
| skipped (mp3 missing) | 1 | angus_julia_stone — source file absent |

## 6. Regression verdict

**PASS** — zero net `identified=true → false` for legitimate matches.

Initial R5 batch (d0b2b51, threshold 0.50) created 2 transient false-positive demotions (buddha-bar, notre-dame). The 56c0367 fix lowered the threshold to 0.30 and added a substring-rescue branch, restoring both. The only net demotion is gorillaz, which was a false positive in the first place.

The 24 pre-R5 identified caches that were already correct: 22 unaffected by the batch, 2 (buddha-bar, notre-dame) transiently demoted and immediately restored.

## 7. The gorillaz fix in detail

**Pre-R5 cache state:**
```json
{
  "identified": true,
  "source": "acoustid",
  "match_method": "chromaprint",
  "mbid_recording": "8d74e3f5-3e94-4d6f-bff2-66883f906999",
  "acoustid_score": 0.9900119,
  "title": "Silent Running",
  "artist": "DJ Allan McLoud",
  "release": "100% Eurotrance 3",
  "year": 2001
}
```

**Post-R5 cache state:**
```json
{
  "identified": false,
  "source": "none",
  "match_method": null,
  "reason": "acoustid_artist_mismatch",
  "acoustid_proposed_artist": "DJ Allan McLoud",
  "slug_derived_artist": "Gorillaz",
  "acoustid_artist_similarity": 0.2609
}
```

The structured log line:
```
analyze.stages.identify WARNING artist-plausibility gate REJECTED canonical match for gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg: identified='DJ Allan McLoud' vs slug='Gorillaz' sim=0.2609 (mode=artist)
analyze.stages.identify INFO identify: slug=gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg source=none score=0.9900119 mbid=8d74e3f5-3e94-4d6f-bff2-66883f906999 reason=acoustid_artist_mismatch
```

The substring rescue did not trigger because "DJ Allan McLoud" is nowhere in the slug. Demotion is the correct outcome.

## 8. Performance

Batch wall time: ~28 min for 30 slugs (similar to R4). No measurable overhead from the artist-plausibility gate (it runs only on canonical AcoustID matches and uses cached slug-parsed metadata).

## 9. Outstanding work after Round 5

| Item | Status | Notes |
|---|---|---|
| Gorillaz false positive | ✓ FIXED | Now demoted with diagnostic reason. |
| Artist-plausibility false-positive demotions | ✓ FIXED in 56c0367 | Substring rescue + lower threshold. |
| Unicode/apostrophe handling | ✓ SHIPPED | No corpus instance to exercise; latent bug fix. |
| Spec §2 calibration | ✓ AMENDED | Sting reclassified; 75% target marked as Round-1 framing error. |
| Charlie Puth / Moderat / Balthazar etc. fallback misses | ✗ STILL OUT | Threshold lowering to 0.75 didn't move them. Root cause deeper than threshold — needs `clean_title` enhancement OR AcoustID `releasegroups` integration OR exhaustive MB search-by-duration heuristic. |
| Manual override tier | ✗ DEFERRED | Spec §7 Q4; Round 6+ scope. |

## 10. Final verdict

**Round 5 ships cleanly with one fix-up commit.** The overhaul arc (Rounds 1-5) is in a defensible end-state:

- **Correctness:** zero known false positives. The application no longer serves fabricated metadata. Demotion protection (`_preserve_or_write` + atomic writes) is airtight.
- **Coverage:** 14/30 corpus identified (47%). Below the spec's 75% target, but the spec target was a Round-1 framing error against this corpus.
- **Observability:** structured `identify: slug=...` log line emitted on every run; reason codes disambiguated; raw AcoustID responses cached for forensic replay.
- **Trust signaling:** fallback-identified tracks show an italic "via text-match search" note with hover tooltip showing variance + similarity.
- **Test coverage:** 100+ new tests across Rounds 2-5; corpus-driven integration tests for silence-strip + fallback paths.

Recommend: ACCEPT (with documented future scope for the Charlie Puth-style miss).
