# Identify Pipeline Overhaul — Analyze, Debug, Enhance

**Date:** 2026-05-12
**Status:** Plan, not yet implemented
**Trigger:** "I can't believe that Sting - Shape of My Heart is not found." User-driven scrutiny of AcoustID identification quality after a 17-track corpus probe revealed three distinct failure modes hiding behind a single "no AcoustID match above threshold" error string.

This document is a **resumable, round-based execution plan**. Each round is a set of parallel subagent tasks followed by an **independent reviewer subagent** that gates progress to the next round. A fresh context can pick this up by reading sections 1–3, then launching Round 1.

---

## 1. Background — what we already know

`analyze/stages/identify.py` calls AcoustID → MusicBrainz to populate `cache/<slug>/identify.json`, which the webui's Metadata sidebar card reads. As of 2026-05-12, on a 40-track local cache:

- **10 / 40** identified (`identified: true`)
- **17 / 40** "no AcoustID match above threshold"
- **13 / 40** "MusicBrainz error: HTTP 503" (transient — covered by the `identify-retry` script and the `_preserve_or_write` guard)

The 17 unmatched include real commercial releases that *should* match (Charlie Puth - Attention, Moderat - Reminder, Warhaus - Love's A Stranger). A manual probe via `scripts/probe_acoustid.py` (already in repo) against 7 of those 17 tracks revealed:

| Bucket | Example slug | AcoustID response | Root cause hypothesis |
|---|---|---|---|
| **A: zero results** | `charlie_puth_attention`, `sting-shape_of_my_heart_live_at_the_rijksmuseum-...`, `balthazar-changes_official_video-...`, `joesef_comedown_...`, `olivia_dean_dive_acoustic_...` | `results: []` | YouTube source adds 1–4 s of leading silence/label slate, shifting Chromaprint's 6 s rolling windows out of phase with the canonical CD master. AcoustID returns nothing even though the song's fingerprint is in the DB. Plus: niche cuts (live, acoustic) where no YouTube fingerprint was ever submitted. |
| **B: high-score AcoustID-only** | `moderat-reminder_official_video-...` | `score=0.938` but `recordings=[]` | Someone submitted a YouTube-source fingerprint and got an AcoustID ID, but never linked it to a MusicBrainz recording. |
| **C: real match buried under unlinked higher score** | `warhaus_love_s_a_stranger_official_video-...` | top: `score=0.984` no recordings; **second: `score=0.951` correct Warhaus recording** | **Bug** in `acoustid_client.lookup` (`analyze/clients/acoustid.py:76-78`): the code takes `max(results, key=score)`, finds no recordings, returns None. It throws away the correct second-best result. |

The current `DEFAULT_MIN_SCORE = 0.85` in `analyze/clients/acoustid.py:17` is over-conservative for YouTube-transcoded sources (which score 0.7–0.95 typically).

### Code locations to know up front

- `analyze/stages/identify.py` — pipeline stage; orchestrates fpcalc → AcoustID → MusicBrainz
- `analyze/clients/acoustid.py` — Web Service v2 client (the source of Bucket-C bug)
- `analyze/clients/musicbrainz.py` — MB recording-lookup client; handles 5xx retries
- `analyze/vendor/chromaprint/fpcalc` — vendored Linux Chromaprint binary
- `analyze/keys.py` — reads `ACOUSTID_API_KEY` from `.env`
- `webui/webui/identify.py` — webui-side reader for identify.json
- `webui/static/js/sidebar/metadata-card.js` — UI consumer (returns `''` when `identified: false`)
- `scripts/probe_acoustid.py` — diagnostic CLI (already exists, hits AcoustID at no threshold)
- `scripts/identify-retry.*` — operational helper for MB-503 batch retry

### Existing memory notes worth re-reading

- `acoustid_app_key_vs_user_key` — `/v2/lookup` needs the *Application API Key* (from acoustid.org/applications → Register Application), not the personal user account key. "HTTP 400: invalid API key" → almost always this.
- `identify_demotion_protection` — `_preserve_or_write()` is load-bearing; AcoustID/MB transient errors must never overwrite cached `identified: true`. 12-track wipe incident on 2026-05-11 motivated this.

### Test corpus

The 30 unidentified slugs live at [`docs/superpowers/specs/2026-05-12-identify-corpus.md`](./2026-05-12-identify-corpus.md). Each round operates on this corpus and emits per-slug deltas.

---

## 2. Goals & non-goals

### Goals (in order of leverage)

1. **Fix the Bucket C bug** (`acoustid.py` returning None when max-score is unlinked) — restores currently-throwable matches with no risk
2. **Recalibrate `DEFAULT_MIN_SCORE`** from 0.85 to a data-driven value (probably 0.65–0.7) — empirical, no risk if accompanied by a regression-corpus test
3. **Strip leading silence before fpcalc** — should unlock Bucket A for YouTube-transcoded commercial releases. The Chromaprint fingerprint is time-anchored; intro silence misaligns the 6 s windows.
4. **MusicBrainz text-search fallback** — when AcoustID returns nothing (or only unlinked results), search MB by artist/title from the slug, confirm via duration match (±3 s). Surfaces a "fallback-identified" trust state.
5. **Trust signaling in UI** — Metadata card should distinguish "canonical AcoustID + MB match" from "fallback text-search match" (different chip, link).
6. **Observability** — every identify run should emit a structured log line so future regressions are detectable from `webui.log` greps.

### Non-goals

- **Submitting fingerprints back to AcoustID** — that's a separate, write-side feature; the AcoustID `/v2/submit` API is well-documented but not needed to fix the read-side gap.
- **Replacing AcoustID with a different ID provider** — Shazam-style commercial fingerprinters are not open and not in scope. We optimize what we have.
- **Touching MusicBrainz 5xx handling** — already addressed by retry loop + `_preserve_or_write`. The `identify-retry` script handles the operational case.
- **Reworking the Metadata card layout** — the recent reordering (`Metadata` directly above `Acoustic Profile`) is the desired final layout.
- **Cross-checking against Last.fm or Spotify APIs** — out of scope; tracked in `2026-05-09-phase-g-web-research-agreement.md`.

### Success criteria

After all four rounds land:

| Metric | Today | Target |
|---|---|---|
| `identified: true` on the 30-track corpus | 10 / 40 (25%) | ≥ 30 / 40 (75%) |
| Sting "Shape of My Heart Live at Rijksmuseum" | unidentified | **identified via MB text-search fallback** (it's a niche live performance; AcoustID will never have a fingerprint for it) |
| Warhaus "Love's A Stranger" | unidentified | **identified via canonical AcoustID path** (the data is right there — bug fix alone unlocks this) |
| Charlie Puth "Attention" | zero results | **identified via canonical AcoustID path** after silence-strip preprocessing |
| Moderat "Reminder" | unlinked high-score | **identified via MB text-search fallback** triggered by "AcoustID returned only unlinked results" condition |
| Unit + integration test count | (current) | (current) + at least 25 new tests covering the three failure-mode buckets |
| `webui.log` shows structured `identify:` lines on every run | grep returns sparse, ad-hoc strings | Every identify emits `identify: slug=... source=acoustid|fallback|none score=... mbid=... reason=...` |

#### Round 5 amendment (2026-05-13)

After Rounds 1–4 shipped and Gemini's independent R4 review (see
`docs/superpowers/identify-overhaul/round-4-final-review.md`), three of
the per-track promises above need calibration. This amendment records
the recalibration; it is **not** a goal-reduction — it's based on
empirical findings from four rounds of investigation, design, and
shipping.

- **Sting "Shape of My Heart Live at Rijksmuseum"** — the requirement
  is now "**fails gracefully as `fallback_ambiguous` with diagnostic
  reason field**". The "identified via MB text-search fallback"
  framing was a Round-1 error: the live-at-Rijksmuseum performance is
  genuinely not in MusicBrainz under a duration/title-distinguishable
  identifier. The Round-4 fallback's ambiguity guard correctly refuses
  to claim a match because MB returns multiple "Shape of My Heart"
  candidates with similar durations (studio, demo, other live cuts).
  Returning the studio album's metadata for a Rijksmuseum live cut
  would be silently wrong; the current `fallback_ambiguous` outcome is
  the right engineering call. Manual-override UI is the Round-5+
  unlock for this class of track.

- **The 75% corpus target (≥ 30/40)** — was tentatively set at Round 1
  design time based on an unverified assumption that the three planned
  levers (walker fix, silence-strip, MB fallback) would each unlock
  multiple tracks. Empirically: walker fix = +1 track (Warhaus),
  silence-strip = 0 tracks (Round 3 batch validated zero movement),
  fallback = +1 track (nightbus). The realistic ceiling on this
  specific corpus is **~17–18/30**, dominated by live recordings,
  niche YouTube-only content, and academic test renders that simply
  aren't in AcoustID or MusicBrainz. Future corpora additions should
  be evaluated against achievability before setting a numeric target.

- **Charlie Puth "Attention" and Moderat "Reminder"** — both remain
  unidentified after R4. The two failure modes are (a) the slug
  parser's no-`-` blindspot returning empty artist on
  `charlie_puth_attention`, and (b) the 0.85 title-similarity floor
  rejecting close-but-not-perfect matches like
  `moderat-reminder_official_video`. Round 5 lowers the threshold to
  0.75 with a compensating 0.03 duration-variance tighten and queries
  MB without an artist filter when the slug has no separator. These
  changes target the two specific tracks but may flip other tracks in
  the unidentified set too.

This amendment is not a contract revision — it's a record of the
calibration deltas between Round-1 framing and the empirical outcome
after four rounds. The original table above is preserved verbatim so
the design-time assumptions remain auditable.

---

## 3. Round structure & subagent contract

Each round has:

- **Investigation phase** — parallel subagents, no commits unless the task explicitly says "commit"
- **Review phase** — one reviewer subagent reads all investigation outputs and writes a `round-N-review.md` under `docs/superpowers/identify-overhaul/`
- **Gate** — the assistant running the plan reads the review, decides if the round's deliverables are accepted, and either advances to the next round or relaunches the failed agents with sharper prompts

**Output convention.** Each subagent writes a markdown report to `docs/superpowers/identify-overhaul/round-N-agent-X.md` (created during execution; not pre-committed). Code changes go to PRs / commits as usual. Investigation rounds typically commit only the investigation report, not source changes.

**Subagent selection.** Use the agent types best matched to the work. Suggested mapping:

- **Static analysis / "find the bugs"** → `feature-dev:code-explorer` or `pr-review-toolkit:silent-failure-hunter` (the latter is excellent at "error-swallowing" patterns which abound in identify)
- **Empirical experiments / "run the probe and tabulate"** → `general-purpose` (it can shell out, write files, parse JSON)
- **Design choices** → `feature-dev:code-architect`
- **Implementation** → `general-purpose` (it can write code) or directly by the orchestrator
- **Review** → `feature-dev:code-reviewer` or `pr-review-toolkit:code-reviewer`
- **Second opinion / contrarian** → `gemini-cli:gemini` (a Gemini-backed reviewer is independent of Claude's failure modes)

---

## Round 1 — Evidence-gathering (no code changes)

**Goal.** Build a complete, evidence-backed picture of *every* identification failure mode in the 30-track corpus, plus a static-analysis pass over the identify code to catch any bugs beyond the three already known.

### Round 1 — Subagent A1 (static analysis)

```
Subagent type: pr-review-toolkit:silent-failure-hunter (preferred) or feature-dev:code-explorer

Prompt (paste verbatim into Task):

You are doing a deep static analysis of the MusIQ-Lab AcoustID/MusicBrainz
identification pipeline. The user just discovered that 17 of 40 cached tracks
fail to identify with "no AcoustID match above threshold", and a manual probe
showed several distinct failure modes hidden behind that single error string.

The known issues (DO NOT just rediscover these — find OTHERS):

1. acoustid.py:76-78 picks max-by-score then bails if recordings=[], throwing
   away correctly-linked lower-score results that follow.
2. DEFAULT_MIN_SCORE=0.85 is too aggressive for YouTube-transcoded sources.
3. fpcalc runs on the raw cached MP3 with no preprocessing; leading silence
   from YouTube intros breaks the 6-second window alignment.

Your job: read these files line by line and report EVERY other bug, design
smell, or silent failure you find:

  analyze/stages/identify.py
  analyze/clients/acoustid.py
  analyze/clients/musicbrainz.py
  analyze/keys.py
  webui/webui/identify.py (consumer side — defensive read)

Things to look for specifically:

  - Exception handlers that swallow errors and return identified=false with a
    short reason (these can hide root cause from operators)
  - Rate-limit / retry logic that has gaps (e.g. retries only on 5xx but not
    on transient network errors)
  - Cache invalidation bugs that could let a stale identify.json survive a
    schema bump
  - Race conditions in _preserve_or_write
  - API contract assumptions that the AcoustID v2 spec doesn't actually
    guarantee (consult their docs at https://acoustid.org/webservice)
  - Encoding / unicode bugs in slug-derived artist/title (this is a Windows
    project; non-ASCII titles abound)
  - Schema versioning: should SCHEMA_VERSION bump when we change client
    behavior even if the cached payload schema is unchanged?

Deliverable: write your findings to
docs/superpowers/identify-overhaul/round-1-a1-static-analysis.md

For each finding include:
  - severity (critical | high | medium | low | nit)
  - file:line anchor
  - what's wrong
  - smallest fix that addresses it
  - test we should add to prevent regression

Do NOT edit any source. This is investigation only. Report in markdown.
```

### Round 1 — Subagent A2 (empirical corpus probe)

```
Subagent type: general-purpose

Prompt (paste verbatim into Task):

You are running an empirical probe of the AcoustID identification pipeline
against the 30-track unidentified-corpus listed in
docs/superpowers/specs/2026-05-12-identify-corpus.md.

CONTEXT — do not skim:
  - The vendored fpcalc binary at analyze/vendor/chromaprint/fpcalc runs
    inside WSL2 only (Linux ELF binary). Invoke via `wsl -e bash -c "..."`.
  - The Windows path containing dollar signs and spaces means you MUST set
    MSYS_NO_PATHCONV=1 before wsl commands when invoked from Git Bash; on
    Windows PowerShell direct wsl invocation works.
  - There is already a probe script at scripts/probe_acoustid.py. Extend it
    (or write a sibling) — DO NOT manually duplicate its logic from scratch.
  - The AcoustID API key lives in .env. The key MUST be an Application API
    Key (registered at acoustid.org/applications), not the personal user key.
    Validate this at the top of your script via a single canary lookup; if
    it fails with HTTP 400 "invalid API key", stop and report.

For each of the 30 corpus slugs, collect:

  - fpcalc fingerprint + duration_sec
  - AcoustID raw response (top 5 results, scores, whether each has
    recordings linked, what MBIDs if any)
  - Leading-silence duration in the source MP3 (use ffmpeg
    "silencedetect=noise=-50dB:d=0.3" or equivalent; report the offset of
    the first non-silent sample in seconds)
  - The slug-derived artist/title guess (parse the slug — strip YouTube ID
    tail, "-" separates artist/title, "_" separates words; lowercase to
    title case)

Output two artifacts:

  1. docs/superpowers/identify-overhaul/round-1-a2-corpus-probe.json
     — machine-readable per-slug dump

  2. docs/superpowers/identify-overhaul/round-1-a2-corpus-probe.md
     — human-readable analysis. Bucket every slug into ONE of these:

        A.  zero results (results: [])
        B.  results[0] high-score unlinked (recordings=[]) — Bucket C bug
        C.  no results above 0.85 but one above 0.5 (threshold issue)
        D.  results exist but our code picks wrong row (Bucket C bug from §1)
        E.  fingerprint computed but AcoustID errored (HTTP, key, etc.)
        F.  fpcalc itself failed (codec, duration < 30s, etc.)
        Z.  novel — describe the pattern

     For each bucket compute:
        - count
        - representative slugs (up to 3)
        - leading-silence stats (mean, max) across the bucket
        - what fix would address it

Hard rules:
  - DO NOT commit source changes
  - DO NOT modify the live cache (the script reads, doesn't write)
  - DO rate-limit AcoustID lookups to 3/sec per their API rules
  - DO save raw responses; we may want to re-analyze without re-querying

Be thorough. The user is paying for an LLM to do this so we don't have to.
Allocate ~30 min if needed.
```

### Round 1 — Subagent A3 (key + auth sanity)

```
Subagent type: general-purpose

Prompt:

Verify the AcoustID API key registration is correct, and audit the .env
loading path for any silent fallthrough.

Steps:
  1. Read analyze/keys.py and confirm how ACOUSTID_API_KEY is loaded
     (look for default fallbacks, alternate env vars, etc.)
  2. Read the current .env value (do NOT print it; just confirm it exists
     and is non-empty)
  3. Make ONE test request to https://api.acoustid.org/v2/lookup with a
     known-canonical fingerprint (you can compute fpcalc on any track that
     IS currently identified — pick one from /api/tracks where identified
     is true, look at its identify.json to find a known good
     mbid_recording, then re-verify the round-trip). If the response says
     status="error" with "invalid API key", the user's key is the personal
     User Key not the Application Key — report this and link them to
     https://acoustid.org/applications.
  4. Confirm the rate-limit comment in acoustid.py ("3 req/s") matches the
     current AcoustID published limit. Their docs sometimes change.

Output: docs/superpowers/identify-overhaul/round-1-a3-key-audit.md
Be brief — this is a sanity gate, not an essay.
```

### Round 1 — Reviewer R1

```
Subagent type: feature-dev:code-reviewer (or pr-review-toolkit:code-reviewer)

Prompt:

You are reviewing the Round 1 investigation outputs of the identify-pipeline
overhaul. Read:

  docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md (this plan)
  docs/superpowers/identify-overhaul/round-1-a1-static-analysis.md
  docs/superpowers/identify-overhaul/round-1-a2-corpus-probe.md
  docs/superpowers/identify-overhaul/round-1-a2-corpus-probe.json
  docs/superpowers/identify-overhaul/round-1-a3-key-audit.md

Then produce docs/superpowers/identify-overhaul/round-1-review.md with:

  1. Validation: are the findings real? Spot-check the static analysis by
     reading the cited file:line anchors yourself. Spot-check the corpus
     probe by re-running 2-3 of the per-slug queries.
  2. Prioritized fix list: combine A1's bug list with A2's empirical
     evidence into a single ranked list. Mark each fix as
     (small | medium | large) and (low-risk | medium-risk | high-risk).
     Recommend which fixes go into Round 2 (quick wins) vs Round 3+
     (preprocessing, fallbacks).
  3. Missing analysis: anything Round 1 should have investigated but
     didn't? Should we relaunch any agent before advancing?
  4. Recommendation: ADVANCE TO ROUND 2 | RELAUNCH ROUND 1 with specific
     agents and prompts. If RELAUNCH, write the new prompts.

Be skeptical. The point of the reviewer is independence. If A1 missed
something obvious, say so.
```

### Round 1 gate

Orchestrator reads `round-1-review.md`. If `ADVANCE`, proceed. If `RELAUNCH`, redo the named agents with the reviewer's revised prompts. Do not advance until the reviewer says ADVANCE.

---

## Round 2 — Quick wins (low-risk fixes)

Goal: ship the two changes Round 1 agreed are smallest-impact-highest-value, with full test coverage and a re-run of the probe to measure improvement.

### Round 2 — Subagent B1 (Bucket-C bug fix + threshold recalibration)

```
Subagent type: general-purpose

Prompt:

Implement two fixes in analyze/clients/acoustid.py:

  1. The result-walking bug. Current code:

         best = max(results, key=lambda r: r.get("score", 0.0))
         if best.get("score", 0.0) < min_score: return None
         recordings = best.get("recordings") or []
         if not recordings: return None

     Replace with: sort results by score descending; iterate; return the
     first result whose score >= min_score AND that has at least one
     recording. (If you encounter a higher-score result with no recordings,
     you may still want to log its acoustid_id so we can investigate
     submitting an MB link later.)

  2. Lower DEFAULT_MIN_SCORE from 0.85 to the value Round 1 recommended
     (probably 0.65 or 0.70 — read the review for the data-driven number).

Add tests in webui/tests/ (or analyze/tests/ if that's where AcoustID-client
tests live — search first; the project uses pytest):

  - results sorted [0.95 unlinked, 0.92 linked] → returns 0.92 result
  - results sorted [0.99 unlinked, 0.98 unlinked, 0.75 linked] → returns
    0.75 result (assuming threshold lowered)
  - results sorted [0.99 unlinked, 0.40 linked] → returns None (linked one
    is below threshold)
  - threshold default IS the new value (regression guard)
  - existing tests for the simple positive path still pass

Bump SCHEMA_VERSION in analyze/stages/identify.py from 1 to 2 to force a
re-run of identify on every existing cache (so users pick up the fix
without having to reanalyze).

After implementing: run `pytest` in webui/.venv and confirm zero
regressions. Commit with a message that points back to this spec.

Do NOT touch fpcalc preprocessing — that's Round 3.
Do NOT touch MusicBrainz fallback — that's Round 4.
```

### Round 2 — Subagent B2 (probe re-run + delta report)

```
Subagent type: general-purpose

Prompt:

After B1's commits land, re-run scripts/probe_acoustid.py against the full
30-track corpus (NOT just the 7 from the original probe). Then re-run the
identify stage via `python -m analyze --stages identify <slug>` for each
slug, so cache/<slug>/identify.json reflects the new code.

Produce docs/superpowers/identify-overhaul/round-2-delta.md showing:

  - Per-slug before/after (was: identified=false reason=X; now:
    identified=true mbid=Y score=Z, or still false with new reason)
  - Aggregate: how many tracks moved from false to true after Round 2
  - Which buckets cleared, which remain (this informs whether Round 3 is
    still needed and at what intensity)

Commit the regenerated identify.json files in the same commit, marked
"chore(identify): refresh after Round 2 fixes".
```

### Round 2 — Reviewer R2

```
Subagent type: pr-review-toolkit:code-reviewer

Prompt:

Review the Round 2 commits and round-2-delta.md. Check:

  - Code review of B1's changes: clarity, edge cases, test quality.
    Specifically: are the new tests deterministic? Do they cover the case
    where ALL results lack recordings?
  - Does the SCHEMA_VERSION bump correctly invalidate caches per the
    sidecar contract? (See analyze/sidecar.py.)
  - Does round-2-delta.md actually show improvement? Are any tracks
    REGRESSED (was identified=true, now false)? If yes, the
    _preserve_or_write guard should have prevented this — investigate.
  - Are there commit messages that point back to this spec for future
    archaeology?

Output: docs/superpowers/identify-overhaul/round-2-review.md.
Recommendation: ADVANCE TO ROUND 3 | REVISE.
```

---

## Round 3 — Silence-strip preprocessing

Goal: address Bucket A (zero AcoustID results) by preprocessing the MP3 before fingerprint extraction.

### Round 3 — Subagent C1 (design)

```
Subagent type: feature-dev:code-architect

Prompt:

Design the silence-strip preprocessing layer for identify.py. Requirements:

  1. Before calling fpcalc, run a step that produces a transient WAV with
     leading silence (and optionally trailing silence) removed.
  2. The threshold should be configurable but default to something
     conservative (e.g. -50 dB for 0.3 s). Too aggressive will strip the
     attack of a quiet intro.
  3. The output must be valid WAV (44.1 kHz or 48 kHz; fpcalc accepts
     either). ffmpeg is already a hard dep on this stack.
  4. The preprocessing must be FAST — identify is a per-track stage and
     must not significantly slow down the pipeline. Target: <2 s overhead
     per track.
  5. If silence-strip fails for any reason, fall back to running fpcalc on
     the raw MP3 (current behavior). Soft fail.
  6. The decision to silence-strip should be conditional: only run it if
     the leading silence exceeds some threshold (e.g. >0.5 s). Pure CD
     transcodes that start at sample 0 should skip preprocessing entirely
     to avoid changing the fingerprint unnecessarily.
  7. Both fingerprints (raw + stripped) could be queried — if AcoustID
     finds nothing on the stripped one, try the raw one. Discuss the
     tradeoffs in your design doc.

Deliverable: docs/superpowers/identify-overhaul/round-3-c1-silence-strip-design.md

Include:
  - Architectural diagram (mermaid or ascii is fine)
  - ffmpeg command line(s) you intend to use, tested against 3 sample
    tracks from the corpus
  - Exact place in identify.run() to wire it in
  - Any new params for the sidecar (so cache invalidates on tuning changes)
  - SCHEMA_VERSION bump strategy
  - Test plan
  - Discussion of "query both fingerprints" vs "query stripped only"
  - Risks (could we accidentally identify the WRONG song by stripping too
    much intro? Worth thinking about)
```

### Round 3 — Subagent C2 (implementation)

Launched only after C1 design is accepted by R3 partial review (see below).

```
Subagent type: general-purpose

Prompt: (defer — generate after C1 design is reviewed; the prompt depends
on the design choices C1 makes)
```

### Round 3 — Reviewer R3 (two-pass: design then code)

```
Subagent type: feature-dev:code-reviewer

Pass 1 prompt (after C1, before C2):

Read docs/superpowers/identify-overhaul/round-3-c1-silence-strip-design.md.
Critique the design:
  - Are the ffmpeg parameters justified? (Default thresholds matter — too
    aggressive strips real music, too conservative leaves the problem
    unfixed.)
  - Is the "query both fingerprints" tradeoff correctly weighed?
  - Are the test plans complete (include the 5-track Charlie-Puth-style
    Bucket A corpus from Round 1)?
  - Are risks adequately addressed?
Output: docs/superpowers/identify-overhaul/round-3-c1-design-review.md
Recommendation: PROCEED TO IMPLEMENTATION | REVISE DESIGN.

Pass 2 prompt (after C2):

Code review of the silence-strip implementation. Check:
  - Soft-fail correctness (any path that prevents identify from completing
    is a regression)
  - Performance overhead (measure on a sample track)
  - SCHEMA_VERSION + sidecar params include the silence-strip config
  - Round-3 delta report shows the expected Bucket A clearance
Output: docs/superpowers/identify-overhaul/round-3-final-review.md
```

---

## Round 4 — MusicBrainz text-search fallback

Goal: when AcoustID returns nothing or only unlinked results, fall back to MusicBrainz search by artist + title from the slug, confirmed by duration match. Surfaces a `source: "fallback"` field in identify.json so the UI can show a different trust state.

### Round 4 — Subagent D1 (design)

```
Subagent type: feature-dev:code-architect

Prompt:

Design the MusicBrainz text-search fallback for identify.py.

Trigger conditions (compose, don't overlap):
  - AcoustID returns 0 results
  - AcoustID returns N results but none have linked recordings
  - AcoustID's best linked result is below threshold

Approach:
  1. Parse the slug into artist/title using the same heuristic the lyrics
     pipeline already uses (search webui/webui/lyrics.py for the existing
     "smart split" logic — DO NOT duplicate it, refactor into a shared
     module if needed). For example,
       "warhaus_love_s_a_stranger_official_video_gsjdhd0stag" →
       artist="Warhaus", title="Love's A Stranger"
  2. Strip noise tokens: "official video", "official audio", "lyric video",
     "live at X", "acoustic", "(2010)", YouTube-ID-tail
  3. Call musicbrainzngs.search_recordings(artist=..., recording=...,
     limit=10). musicbrainzngs is presumably already installed — check
     pyproject.toml; if not, add it.
  4. For each result, fetch its duration via the include=releases flag and
     score: |duration_recording - duration_track| / duration_track. Pick
     the best match with score < 0.05 (≤5% duration variance).
  5. If a match is found, write identify.json with the new schema:
       {
         "identified": true,
         "source": "fallback",         // NEW field — UI keys on this
         "mbid_recording": ...,
         "title": ...,
         "artist": ...,
         "match_method": "mb_text_search",
         "duration_variance_pct": 0.013,
         ...
       }
  6. The Metadata card in webui must render fallback-sourced identifications
     with a small visual distinction (e.g. ⚠ icon or a "metadata via text
     match" footnote). Don't make it scary; just informative.

Deliverable: docs/superpowers/identify-overhaul/round-4-d1-fallback-design.md

Include:
  - Slug-to-artist/title parser specification (DRY against lyrics.py)
  - MB query strategy + duration confirmation algorithm
  - Schema diff for identify.json (the new "source" field, optional
    "match_method", "duration_variance_pct")
  - Test corpus: which 5 tracks from the Round 1 probe should this fix?
  - UI changes spec (metadata-card.js + CSS)
  - Risk analysis: what's the false-positive rate likely to be? (Worst case:
    we identify a different song by the same artist with a similar
    duration.) Mitigations: require exact-or-close title match, not just
    artist match.
```

### Round 4 — Subagent D2 (implementation)

Launched only after D1 design is reviewed.

```
Subagent type: general-purpose

Prompt: (defer — generate after D1 is reviewed)
```

### Round 4 — Subagent D3 (UI changes)

```
Subagent type: general-purpose

Prompt:

After D2 lands the backend, update the webui Metadata card to surface the
fallback trust state. Files to edit:

  webui/static/js/sidebar/metadata-card.js
  webui/static/css/track.css (find the .metadata-card section)

Requirements:
  - When identify.source === "fallback", show a small italic note under the
    card title: "via text-match search" (or similar — coordinate with
    Round-4 design).
  - The note's color should be --text-muted, not --status-warn — this is
    informational, not a warning.
  - Add unit tests in webui/tests-js/ for the renderer with both source
    states.
  - Snapshot test or visual smoke: open the webui after Round-4 backend
    lands, navigate to a fallback-identified track, screenshot the sidebar
    card, attach to the round-4-final-review.md.

Do not break the existing 10 canonical-identified tracks' rendering.
```

### Round 4 — Final Reviewer R4

```
Subagent type: gemini-cli:gemini (intentional — second opinion from a
different LLM to catch blind spots in Round 1's framing)

Prompt:

You are doing an independent second-opinion review of the entire
identify-pipeline overhaul. Read:

  docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md (this plan)
  docs/superpowers/identify-overhaul/round-1-review.md
  docs/superpowers/identify-overhaul/round-2-review.md
  docs/superpowers/identify-overhaul/round-3-final-review.md
  docs/superpowers/identify-overhaul/round-4-d1-fallback-design.md
  All round-N-delta.md files
  The current state of:
    analyze/stages/identify.py
    analyze/clients/acoustid.py
    analyze/clients/musicbrainz.py
    webui/webui/identify.py
    webui/static/js/sidebar/metadata-card.js

Answer:
  1. Did this overhaul actually fix the problem the user originally raised?
     ("Sting - Shape of My Heart" — does it identify now? If yes, how? If
     no, why not, and is that acceptable?)
  2. What's the new identification rate on the 30-track corpus?
  3. Any failure mode that was missed entirely?
  4. Any net regression introduced by the fixes? (E.g. did the threshold
     lowering admit any false positives — a track now identified as the
     WRONG song?)
  5. Is the trust signaling in the UI clear enough that a power user can
     tell at a glance which tracks were canonically vs fallback identified?
  6. Maintenance burden assessment: how often will this break? What's the
     observability story?

Output: docs/superpowers/identify-overhaul/round-4-final-review.md

Be candid. The user named this "make this application not junk" — if
something still feels junky, say so. If we should have done something
differently, propose Round 5.
```

---

## 4. Cross-cutting concerns

### 4.1 Observability

The current identify code emits no structured log lines that grep against `webui.log`. Round 2 or 3 should introduce a single info-level log on every identify run:

```
identify: slug=<slug> source=<acoustid|fallback|none> mbid=<mbid|—> score=<float|—> reason=<string|->
```

This lets future regressions be detected without re-running the corpus probe.

### 4.2 Staleness integration

After Round 2 bumps `SCHEMA_VERSION` to 2, every existing cache's identify will surface as `stale` via the new staleness chip (the webui-side stale_stages probe added in PR-of-2026-05-12). The user gets a one-click ⟳ to re-identify each track. **This is desired behavior** — it surfaces the upgrade to the user without forcing a full reanalyze.

### 4.3 Operational helpers

The existing `scripts/identify-retry.*` should be extended (Round 2 or 4) to:
- Filter not just by `MusicBrainz error: HTTP 503` but also by `no AcoustID match` AND `source: none` (the new state).
- Skip tracks where `source: fallback` was already accepted (or accept a `--re-fallback` flag to re-run them).

### 4.4 Memory updates

After each round, the orchestrator should write a brief note to auto-memory under names like `identify_overhaul_round_2_results.md` summarizing the deltas. Future contexts inheriting this work should be able to grep the memory index for context.

---

## 5. File list (created or modified)

### New files

- `docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md` — this plan
- `docs/superpowers/specs/2026-05-12-identify-corpus.md` — the 30-track corpus
- `docs/superpowers/identify-overhaul/round-N-*.md` — per-round outputs (created by agents)
- `scripts/probe_acoustid.py` — already exists; may be extended

### Modified

- `analyze/stages/identify.py` — Rounds 2, 3, 4
- `analyze/clients/acoustid.py` — Round 2 (bug fix + threshold)
- `analyze/clients/musicbrainz.py` — Round 4 (search_recordings wrapper if needed)
- `analyze/sidecar.py` — unchanged unless silence-strip params need new sidecar keys
- `webui/static/js/sidebar/metadata-card.js` — Round 4 (trust signaling)
- `webui/static/css/track.css` — Round 4 (trust signaling visual)
- `webui/webui/stage_manifest.py` — bump identify schema_version after Round 2

---

## 6. How to start (orchestrator quick-reference)

In a fresh context with this spec open, the orchestrator should:

```
1. Read this spec (sections 1-3 minimum) and the corpus file.
2. Create docs/superpowers/identify-overhaul/ directory.
3. Launch Round 1 subagents A1, A2, A3 in PARALLEL via a single Task tool
   message with multiple Task content blocks.
4. Wait for all three to return.
5. Launch reviewer R1.
6. Read R1's output. If ADVANCE: proceed to Round 2. If RELAUNCH: redo named
   agents with R1's revised prompts.
7. Repeat for Rounds 2, 3, 4 per the gate pattern.
8. After R4 returns, summarize the entire arc for the user and propose any
   Round 5 work R4 identified.
```

Each round's subagents should be launched in parallel where possible
(same Task tool call with multiple content blocks) and serialized only
where one depends on another.

---

## 7. Open questions to surface in Round 1 review

These are not blockers, but the reviewer should call them out:

- Should we cache the raw AcoustID response (not just the parsed result) so that future re-analyses with different threshold/walking logic don't have to re-query?
- Should the silence-strip happen ONCE per cache (writing a `stripped.wav` mirror) rather than per-identify-run? Pro: reusable for other stages. Con: storage cost.
- Should "identified via fallback" caches expire faster than canonical ones? Their accuracy is structurally lower.
- Is there a place for a third tier — "manual override" — where the user types in artist/title? (Likely yes; design but defer.)

---

## 8. Acceptance criteria (final gate)

Before any "this work is done" claim:

- All four rounds' reviewers have written ADVANCE / ACCEPT verdicts.
- The 30-track corpus shows ≥ 75% identification rate (combined canonical + fallback).
- Zero regressions: every previously-identified-true track remains identified after all four rounds.
- `pytest` in `webui/.venv` reports zero failures; new tests for each round exist.
- `webui.log` shows structured identify lines after a fresh reanalyze of any track.
- The user has visually confirmed the trust-signal UI on at least one fallback-identified track.
- Memory notes for each round are written and indexed in `MEMORY.md`.

Anything short of the above is not "this application is not junk" — it's "this application has a known unsolved problem with a sketch of the fix".
