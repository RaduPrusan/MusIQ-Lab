# Round 4 Final Review -- Independent Second Opinion (R4 / Gemini)

**Reviewer:** R4 (Gemini CLI, gemini-2.5-pro -- different LLM, fresh context)
**Date:** 2026-05-13
**Branch:** worktree-identify-overhaul (HEAD: dc2c52a)
**Audit trail read:** spec sections 1-3 and R4, corpus doc, rounds 1-4 reviews + delta.md + delta.json, identify.py, acoustid.py, musicbrainz.py, slug_parser.py, stage_manifest.py, metadata-card.js, track.css, 30-corpus identify.json files via direct read

---

## 1. Original User Complaint -- Sting Shape of My Heart: Satisfied?

**Verdict: Unsatisfied on the spec own terms. Acceptable as an engineering outcome.**

The spec section 2 success criteria table is unambiguous:

> Sting Shape of My Heart Live at Rijksmuseum must be identified via MB text-search fallback.

The post-R4 identify.json shows: identified=false, source=none, match_method=null, reason=fallback_ambiguous.

The track is still unidentified. The spec explicit per-track requirement is not met.

That said, the engineering outcome (fallback_ambiguous) is the **right outcome** for a one-off live performance:

1. AcoustID has no fingerprint for this specific Rijksmuseum recording.
2. MusicBrainz has multiple Shape of My Heart recordings (studio, live, various years), and on title + duration alone the pipeline cannot distinguish them. The ambiguity guard fired correctly to avoid returning the studio album metadata for a live performance.
3. Returning false metadata (wrong release, wrong year, wrong ISRC) would have been silently wrong and harmful downstream. Refusing to guess is the right call.

Post-R4, a reviewer opening identify.json sees reason: fallback_ambiguous -- informative and actionable. Pre-overhaul, the reason was an opaque no AcoustID match above threshold.

**My position:** The fail-gracefully criterion for Sting is met. The spec literal identification requirement is not met, and that requirement should be re-evaluated in a Round 5 spec update. The live Rijksmuseum recording is genuinely out of reach for automated identification without a fingerprint submission or manual override.

---

## 2. Corpus Identification Rate vs Spec Target

### Numbers

| Scope | Pre-R4 | Post-R4 | Spec Target |
|---|---|---|---|
| Corpus (30 unidentified tracks) | 14/30 (47%) | **15/30 (50%)** | n/a |
| Full cache (all ~39 tracks) | 24/39 (62%) | **25/39 (64%)** | >= 30/40 (75%) |
| Miss vs spec target | -- | -- | **5 tracks short** |

Note: the round-4-delta report states MISS by 7 against the 30-corpus slice; both framings are correct for their reference frames. The spec section 2 table uses the full 40-track cache as the reference, so I use 25/39 vs 30/40.

### Was the 75% target realistic?

No. The framing error happened at Round 1, not Round 4.

The spec assumed three levers would carry the load:
1. Bucket C bug fix (AcoustID walker) -- delivered 1 track (Warhaus), not a multi-track fix
2. Silence-strip preprocessing -- delivered 0 tracks; hypothesis was empirically wrong for this corpus
3. MB text-search fallback -- delivered 1 track (nightbus)

Total new identifications across all four rounds: +15 (mostly R2 MB-503-retry completions plus the R2 walker fix). The corpus was dominated by tracks that are either not in AcoustID at all (live recordings, niche YouTube-only content, academic test renders) or are in AcoustID with no MB link and no viable text-search recovery.

Round 3 empirically proved silence-strip moved zero. By the time Round 4 shipped, the realistic ceiling for automated identification was 17-18/30, not 22+. Even the D1 design ceiling estimate (6-9 fallback wins) was too optimistic: the slug parser no-dash blindspot and the 0.85 threshold blocked every predicted win except nightbus.

The failure was in the Round 1 framing: the 75% target should have been revised downward after the Round 3 zero result, not maintained as-is through Round 4.

### The one should-have-been-easy per-track miss

Charlie Puth Attention is a mainstream commercial release that the spec (section 2) explicitly promises will be identified via canonical AcoustID path after silence-strip. It is still fallback_no_match. The slug charlie_puth_attention has no - separator, so the slug parser returns empty artist and the MB search seed is semantically broken. This is a direct implementation miss for a track that IS in the AcoustID database.

---

## 3. Missed Failure Modes

Three failure modes beyond the two documented in round-4-delta.md (slug parser no-dash blindspot and 0.85 threshold):

### 3a. Unicode / Apostrophe Normalization Missing (HIGH SEVERITY, Latent)

musicbrainz.py search_recording() applies only _escape_lucene() before building the Lucene query. There is no Unicode normalization.

Slug parser or ID3 tags may produce titles with curly apostrophes (right-single-quote U+2019). MusicBrainz Lucene index may store a straight-apostrophe canonical form. difflib.SequenceMatcher similarity runs on .lower() strings with no normalization -- a curly vs straight apostrophe actively degrades similarity for short titles.

The warhaus track was correctly identified via the AcoustID chromaprint path (score 0.95), so this never surfaced on the test corpus. But the MB text-search path is where it matters, and the corpus happens not to test it. The bug is latent.

Fix: Fold curly apostrophes to straight and apply NFKD normalization before both the Lucene query construction and the similarity comparison. One-liner fix.

### 3b. AcoustID Walker Takes First Linked, Not Best Linked (LOW SEVERITY)

The walker returns the highest-scored entry with non-empty recordings. If two AcoustID result entries are close in score and one links to an inferior MB recording while a slightly-lower-scored entry links to the canonical release, the pipeline will silently take the inferior match. Near the 0.65 threshold, score spreads widen and this becomes more likely. No known case in current corpus.

### 3c. MB Lucene Query Does Not Handle Featured-Artist Credits (MEDIUM SEVERITY)

The query artist:Submotion-Orchestra AND recording:Finest-Hour may miss if MB indexes the track as artist_credit with a featured-artist suffix. The submotion_orchestra-finest_hour_album_version track is in fallback_no_match and was a medium-high-confidence D1 prediction. This pattern generalizes to any featured-artist track.

Fix: When the initial artist+recording query returns zero results, retry with recording:title alone and filter candidates by artist similarity on the returned results rather than at query time.

---

## 4. Regression Check -- Independent Spot-Check

### Zero true->false transitions: CONFIRMED

delta.json movers_true_to_false is empty. _preserve_or_write() held. ReadTimeout on crippled_black_phoenix preserved the existing payload.

### Three cache files directly read

**jamiroquai_everyday/identify.json:**
- identified: true, title: Everyday, artist: Jamiroquai, acoustid_score: 0.9583663
- Missing source and match_method fields -- legacy pre-overhaul format; legacy bridge synthesized v4 sidecar correctly
- No regression

**awolnation-run_official_audio-mw2kkyju9gy/identify.json:**
- identified: true, source: acoustid, match_method: chromaprint, title: Run (Beautiful Things), artist: AWOLNATION, acoustid_score: 0.9874882
- (Beautiful Things) subtitle is the MB canonical title for this single release. Correct.
- No regression

**warhaus_love_s_a_stranger_official_video_gsjdhd0stag/identify.json:**
- identified: true, source: acoustid, match_method: chromaprint, title: Love-s a Stranger (curly apostrophe, MB canonical), artist: Warhaus, acoustid_score: 0.95058674
- No regression

### Pre-Existing False Positive Not Caught by Any Round

Reading delta.json unchanged_identified:

**gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg** is identified as:
- title: Silent Running, artist: DJ Allan McLoud, release: 100% Eurotrance 3, year: 2001, acoustid_score: 0.9900119

The slug names Gorillaz ft. Adeleye Omotayo. This is a **pre-existing false positive** -- delta.json confirms it was identified: true with the same MBID before Round 1. The AcoustID database has this Gorillaz track fingerprint linked to the wrong MB recording.

This was not introduced by the overhaul. But it was not caught by any of the four rounds, not by any of the 108 new tests, and not by any reviewer. The application is actively showing fabricated metadata for a named Gorillaz track. Wrong metadata is strictly worse than identified: false -- users act on artist/album information.

The threshold lowering from 0.85 to 0.65 did not cause this (score is 0.99). It is an AcoustID database integrity issue that needs manual triage.

### Threshold Lowering to 0.65: False Positives Introduced?

No new false positives attributable to R2 threshold change were found in the 14 acoustid-identified tracks. The gorillaz false positive pre-dates the overhaul at score 0.99, independent of any threshold setting.

---

## 5. UI Trust Signaling Clarity

**Verdict: Passes for power users. Not pre-attentive enough for casual users.**

Reading webui/static/js/sidebar/metadata-card.js and webui/static/css/track.css:

The source=fallback case renders an always-visible div (classes: metadata-card-source-note metadata-card-source-fallback) containing italic text via text-match search immediately under the Metadata card h3 heading. Hovering reveals duration variance % and title similarity score in a native tooltip.

**What works:**
- Always visible -- no hover required to know a fallback was used
- Hover tooltip provides actionable precision data for power users
- The three states (canonical / fallback / unenriched) have distinct text labels readable without hovering

**What is weak:**
- The label uses color: var(--text-muted) with font-style: italic -- muted and unsized. No amber/yellow warning coloring, no badge, no icon.
- .metadata-card-source-fallback has no distinct CSS rules beyond what .metadata-card-source-note provides. The D3 commit added the class hook but did not differentiate it visually.
- fallback_ambiguous and fallback_no_match (unidentified tracks) render nothing in the Metadata card. A user looking at a card with no source note cannot tell whether the track is canonically identified, fallback-identified, or unidentified without reading the title/artist fields themselves.

**Assessment:** The distinction is readable but requires active reading, not pre-attentive visual scanning. For the current corpus (1 fallback track) this is acceptable. As the fallback corpus grows, a color-coded badge (amber for fallback, gray for unidentified) becomes load-bearing. Currently: an informational footnote, not a pre-attentive trust signal.

---

## 6. Maintenance Burden + Observability Assessment

### MusicBrainz API

Rate limiting correctly enforced via _gate() with MIN_INTERVAL_SEC = 1.0 and a threading lock. HTTP 429 and 503 are retried once with sleep. The /ws/2/recording/ endpoint has been stable since ~2013.

**One fragility:** _escape_lucene() only escapes backslash and double-quote. Special Lucene characters in artist or title strings (colon, parentheses, plus, minus, tilde, asterisk, question-mark) will silently corrupt the Lucene query. No current corpus track triggers this, but band names like !!! would.

### AcoustID

No proactive rate gate; relies on single-track sequential use. The 4-attempt exponential backoff (1s, 4s, 9s) for 5xx handles transient outages. The reason discriminator (acoustid_no_results, acoustid_all_unlinked, acoustid_below_threshold) is clean and enables differentiated fallback logic.

### Chromaprint / fpcalc

No version check on fpcalc binary. If fpcalc fingerprint format changes between versions (it has changed once in history), all caches become invalid silently. Adding fpcalc version to the stage parameters sidecar would detect this. Low priority for now.

If a future fpcalc adds native silence removal, pre-stripping via ffmpeg is harmless -- no double-processing damage.

### Legacy Bridge

The bridge in cached() that synthesizes v4 sidecars from old identified:true caches is effectively permanent. Safe to remove only after every user has re-run identify on every cached track. Runtime cost when sidecars are current: zero. Keep it.

One cosmetic issue: the jamiroquai_everyday cache will retain missing source and match_method fields indefinitely because the v4 sidecar was synthesized from the old payload and the pipeline will not re-query AcoustID. Not operationally harmful.

### Slug Parser

_NOISE_TOKEN_RE requires manual maintenance as YouTube naming conventions evolve. The confirmed over-strip risk (titles containing legitimate words matching noise tokens, e.g., a song titled Acoustic) is mitigated by the return cleaned or title fallback for total erasure but not for partial stripping.

### Observability

Strong. The structured log line:

    identify: slug=... source=acoustid|fallback|none score=... mbid=... reason=...

is emitted for 29/30 corpus slugs (the 1 miss was a ReadTimeout before the log call -- acceptable). Greppable reason codes, em-dash for absent fields. A future operator can detect regressions via:
- grep source=none webui.log -- all unidentified tracks
- grep reason=fallback_ambiguous webui.log -- ambiguous cases needing manual review
- grep source=fallback webui.log -- text-search identifications for confidence review

The observability requirement from spec section 2 is met. This is a genuine operational improvement.

---

## 7. Overall Verdict: RECOMMEND ROUND 5

The overhaul delivered real improvements: the AcoustID walker bug fix, atomic writes, silence-strip infrastructure, MB text-search fallback, structured observability, and 108 new identify-pipeline tests. Zero regressions across 24 pre-existing caches. The infrastructure is sound and worth keeping.

I cannot issue ACCEPT for three reasons:

**Reason A -- Three Spec Section 2 Per-Track Mandates Unmet**

| Spec promise | Actual outcome |
|---|---|
| Sting: identified via MB text-search fallback | fallback_ambiguous -- not identified |
| Charlie Puth Attention: identified via canonical AcoustID after silence-strip | fallback_no_match |
| Moderat Reminder: identified via MB text-search fallback | fallback_no_match |

The Sting outcome is defensible -- the spec requirement was wrong (the live recording is genuinely unidentifiable automatically), and the engineering outcome is correct. The Charlie Puth and Moderat misses are implementation gaps.

**Reason B -- Pre-Existing False Positive in the Corpus, Undetected Across Four Rounds**

The gorillaz track has been identified as DJ Allan McLoud -- Silent Running (Eurotrance 3) since before Round 1. Four rounds, 108 new tests, and four reviewer passes all missed it. The application is actively showing fabricated metadata for a named Gorillaz track. Wrong metadata is worse than identified: false.

**Reason C -- Unicode Normalization Gap in the New Code**

The MB text-search fallback has no apostrophe or Unicode normalization. The fix is a one-liner and should land before the fallback path is considered production-quality. Currently latent; will break the first real-world track with smart quotes in its slug or ID3 tags.

### Recommended Round 5 Scope (Narrow -- 3 code changes + 1 spec amendment)

1. **Slug parser + threshold for no-dash slugs:** When slug parser returns empty artist with a multi-word title (e.g., charlie_puth_attention), query MB as recording:full-title and filter candidates by artist similarity on returned results. Lower min_title_similarity to 0.75 AND tighten max_duration_variance to 0.03 as a compensating guard. This should recover Charlie Puth Attention and Moderat Reminder.

2. **Unicode normalization:** Add curly-apostrophe folding and NFKD normalization in both search_recording() (before Lucene query construction) and in the similarity comparison. One-liner in each location.

3. **Gorillaz false positive triage:** Verify MBID 8d74e3f5-3e94-4d6f-bff2-66883f906999 against MusicBrainz. Add a post-identification artist-plausibility sanity check: warn (but do not block) when slug-derived artist and identified artist have edit-distance > 0.5 after normalization. The gorillaz/DJ-Allan-McLoud case would catch this and any future AcoustID database errors.

4. **Spec amendment:** Update section 2 per-track table -- Sting requirement should read: fails gracefully as fallback_ambiguous; manual-override UI is the Round 5+ unlock -- rather than: identified via MB text-search fallback. The current outcome is correct engineering; the spec requirement was incorrect at design time.

Round 5 is scoped to 3 code changes and a spec amendment. It does not require re-running the full four-round architecture. The Round 1-4 infrastructure is worth shipping after these gap closures.

---

*Reviewed by R4 (Gemini CLI, gemini-2.5-pro) -- independent second-opinion gate per spec section R4. Read-only review; only this file was written.*

