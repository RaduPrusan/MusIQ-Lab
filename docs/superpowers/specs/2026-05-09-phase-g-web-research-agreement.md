# Phase G — Web research + post-analysis agreement check

**Date:** 2026-05-09
**Status:** Design spec — not yet implemented. Item #7 of the eight-item post-Phase-M improvement plan.
**Roadmap:** [`docs/pipeline-changes-phase-ab.md`](../../pipeline-changes-phase-ab.md) §"Phase G — proposed" (this spec is the long-form expansion of that sketch).
**Related:** [`docs/history.md`](../../history.md) Phase M (the lesson that motivates this), [`install-logs/phase-a-validation.md`](../../../install-logs/phase-a-validation.md) (the corpus-validation TODO that is currently blocked).

---

## 1. Context & motivation

Phase L shipped 13 work items behind a "code-correctness APPROVED" verdict that turned out to be overconfident. Phase M's post-ship corrections found four structurally different bugs whose unifying signature was: **tests passed, the pipeline did not crash, and the output was wrong anyway**. The most expensive of the four (the WI-7 vocals specialist) was caught only when the user opened the piano roll in the webui and saw nonsense. Phase M's lesson, recorded verbatim in `history.md`:

> Tests passing + no crash ≠ correct output for any stage that produces audio/MIDI. The validation surface needs a cross-reference against something: ground-truth labels (manual), web-sourced metadata (Spotify/songbpm/etc. for popular tracks), or another independent algorithm.

The corpus-and-labels TODO from `install-logs/phase-a-validation.md` is the manual path. It is currently blocked: this is a learning project, the user is not a music-theory expert, and hand-labelling 30+ tracks for `key` / `tempo` / `time_signature` / chord progressions requires expertise the user is explicitly building rather than already has. The work is real, but it is on the user's critical path; the project cannot wait on it.

The web-sourced metadata path is the autonomous alternative. Popular tracks have abundant external metadata — tempo aggregator sites, third-party APIs that resurrected what Spotify killed, manually-curated databases — that can serve as zero-labelling-cost ground truth for the three fields the pipeline emits with high confidence: `track.key`, `track.tempo_bpm`, `track.time_signature`. Phase G builds the loop that fetches this metadata for any analyzed track and writes a per-source agreement record into `summary.provenance.external_check`. The pipeline output becomes self-validating against external authority, every run, with no per-track human cost.

Out of scope for this phase: chord progressions (too noisy/proprietary), per-note transcription (no external source has this), section labels, vocal range. Those remain on the manual-corpus track.

---

## 2. Goals & non-goals

### Goals

1. **Cross-check three fields per track against 2–3 external sources.** Fields: `track.key`, `track.tempo_bpm`, `track.time_signature`. Optional fourth: `analysis.scale` (where the source reports it).
2. **Write a structured agreement record into `summary.provenance.external_check`.** Per-source, per-field, with explicit "agrees" booleans and quantitative distances (BPM delta, octave/half-tempo flags, key-relative-major flag).
3. **Soft-fail on any source error.** Network down, rate-limit, track-not-found, ambiguous artist/title — none of these may break the analyze pipeline. Each failure mode produces a structured record explaining what went wrong.
4. **Cache external responses for 30 days** under `cache/<slug>/external_check.json`, keyed on (source, artist, title), so re-running `python -m analyze` on a previously-analyzed track does not burn rate-limit budget.
5. **Be opt-in via CLI flag** (`--external-check`) and via a per-stage opt-out for users who don't want the network call. Default: enabled when the relevant secrets are present, silently skipped when they're not.
6. **No conditional pipeline outputs.** External check is observational. The pipeline does not change `track.key` because Spotify-replacement disagrees; it records the disagreement and lets the user / chat actor / future evaluator decide what to do.

### Non-goals

1. **Chord-progression cross-check.** External sources for full chord progressions (Hooktheory, Chordify) are paywalled, partial, or scrape-hostile. Defer.
2. **Section / structure cross-check.** No good external source. Defer (waits on Phase C anyway).
3. **Lyrics-based section labels** (Genius). Useful but a different problem; defer.
4. **Auto-correction of pipeline output.** The temptation will be: "if Spotify-replacement says 100 BPM and we computed 200 BPM, halve it." This is exactly the kind of over-fit the Phase M vocals fix-then-revert taught us to avoid. Phase G observes; it does not correct.
5. **Replacement of the manual corpus.** The hand-labelled corpus catches things web sources can't (non-popular tracks, transcription accuracy, vocal-range correctness). Phase G is *additive* validation, not a substitute.
6. **HNR voicing for the Cohen 107.7s canary** (Rec 4 from Phase 0c). Separate work item.

### Success criteria

After Phase G ships:

- For every track in `cache/` that has a recognizable "Artist - Title" filename pattern, `summary.provenance.external_check` is populated with at least one source's response (or a structured "all sources failed" record).
- On the validation track `gorillaz-silent_running` (where the pipeline emits `key="F minor"`, `tempo_bpm=107.14`, `time_signature="4/4"`), at least one source agrees on all three fields after tolerance bands. (If they don't, the spec hasn't shipped — either the lookup is broken or our pipeline has a bug Phase G just surfaced. Both outcomes are wins.)
- A regression in any future `key` / `tempo` / `time_signature` change — for any track in `cache/` with external metadata — surfaces as a flipped `agrees_*` boolean. The benchmark dashboard (Section 11) reads `external_check` blocks across `cache/*/` and reports aggregate agreement, so a future change that drops aggregate from "27/30 tracks agree on key" to "12/30 tracks agree on key" is loud.
- Total external-API budget per analyze run is bounded: at most 3 HTTP calls per source per track on a cache miss, 0 calls on a cache hit within 30 days.

---

## 3. Scope of cross-check

The pipeline emits these fields in `summary["track"]` (see `analyze/writers/summary_writer.py:126-156`):

| Field | Type | Source stage | Cross-check feasibility |
|---|---|---|---|
| `track.tempo_bpm` | float | `beats` (madmom DBN) | **High** — many sources report this |
| `track.key` | string e.g. `"F minor"` | `key` (skey) | **High** — Spotify-replacement, songkey, Tunebat, etc. |
| `track.time_signature` | string e.g. `"4/4"` | hardcoded `"4/4"` (!) | **Medium** — Spotify-replacement reports it; few others do |
| `analysis.scale` | string e.g. `"Aeolian"` | derived from `key` | **Low** — sources report key/mode, not scale-mode separation |

**Note on `time_signature`.** The current implementation hardcodes `"4/4"`. This is a known bug being addressed in Phase C; until then, an `external_check.sources.*.time_signature` value of `3/4` against our `4/4` is a *true positive* finding — a track in 3/4 the pipeline is mis-reporting. Phase G will surface these even before Phase C lands.

**Out of scope:**

- `chords[]` — external chord databases are partial and unreliable.
- `stems[*].notes` — no external source.
- `analysis.vocal_range` — too instrument-dependent and rarely reported externally.
- `downbeats[]` / `sections[]` — no external source.

---

## 4. External data sources

### 4.1 What changed in late 2024

The original Phase G sketch in `docs/pipeline-changes-phase-ab.md` named "Spotify Web API (`/v1/audio-features`)" as the primary source. **This endpoint was deprecated by Spotify on 2024-11-27.** New apps cannot access it; only apps with a pending quota-extension at deprecation time still work. There is no migration path and no first-party replacement. (Sources: Spotify for Developers blog, 2024-11-27 announcement; multiple developer communities documented the breakage Q4 2024 / Q1 2025.)

This invalidates the Phase G sketch's primary recommendation. The replacement landscape that emerged in 2024–2026:

- **Third-party APIs that re-derived audio features** (Musicae, FreqBlog Music, MeloData) — feature parity with the dead Spotify endpoint at varying free-tier ceilings.
- **Tempo / key aggregator sites** that pre-date Spotify's API (GetSongBPM, GetSongKey, Tunebat) — still functional, mostly free, but each covers fewer fields than Spotify did.
- **MusicBrainz / AcousticBrainz** — AcousticBrainz was shut down by MetaBrainz in 2022; MusicBrainz still operates but its tempo/key data is sparse (community-contributed, not algorithmic).

The Phase G recommendation is therefore to **use 2–3 narrow sources rather than one wide one**, accepting that no single replacement matches Spotify's old combined signal.

### 4.2 Recommended sources

#### Primary: GetSongBPM (`getsongbpm.com`)

- **Provides:** tempo (BPM), time signature (sometimes), key (sometimes). Tempo is the headline; the other two are best-effort.
- **Free tier:** Free with API key, **requires a backlink to getsongbpm.com from your site/app store listing** (account suspended without notice if missing). For a non-public local pipeline this requirement is awkward — either the project README acknowledges the source, or this source is opt-in and disabled by default.
- **Rate limit:** documented as light — adequate for analyze-pipeline cadence (1 track every few minutes during interactive use; bulk re-analyze is rare).
- **Identifier:** track name + artist as URL-encoded query params.
- **Reliability:** strong on popular tracks; partial coverage on indie / international / instrumental tracks. Pre-dates Spotify's deprecation, has been the canonical free BPM source for ~10 years.

#### Primary: GetSongKey (`getsongkey.com`)

- **Provides:** key (tonic + mode). No tempo.
- **Free tier:** same shape as GetSongBPM (same operator), same backlink requirement.
- **Rate limit:** same.
- **Identifier:** same.
- **Reliability:** strong on popular tracks; key data is harder to crowd-source than tempo, so coverage gaps are more common. When it does report, the data tends to be hand-curated and reliable.

These two are run by the same operator. Treat them as one logical source pair: enable both or neither, share the API key.

#### Secondary: Musicae (`musicae.io`) or equivalent Spotify-replacement

- **Provides:** tempo, key, energy, loudness, time signature, mode — explicitly positioned as the "audio_features replacement".
- **Free tier:** API-key based, exact ceiling varies by provider; expect "free for low volume, pay above a threshold". Verify current terms at implementation time — these third-party shims are 2025-emergent and pricing is volatile.
- **Rate limit:** moderate; documented per-provider.
- **Identifier:** artist + title, or Spotify track URI (which the user does not have without a separate Spotify lookup).
- **Reliability:** unknown long-term — these services are 1–2 years old and operator durability is unproven. Useful as a third opinion; not load-bearing.

This is recommended as a **third source** to cross-validate against (GetSongBPM, GetSongKey). If two of the three agree on a field, that's a strong signal; if all three disagree with the pipeline, the pipeline is suspect.

#### Tertiary / fallback: web search + LLM extraction

For tracks that none of the above have, the pipeline can fall back to a Google / DuckDuckGo search for "<artist> <title> tempo bpm key" and an LLM extraction pass. Practical example: many indie songs have a Wikipedia infobox or a Tunebat listing that surfaces in the first search result.

This fallback is recommended as a **final, opt-in tier** (`--external-check-llm-fallback`). It is more expensive (LLM API call), less reliable (LLM extraction can hallucinate), and only worthwhile when none of the structured sources have the track. **Do not enable by default.**

### 4.3 Sources considered and rejected

- **Spotify Web API audio-features** — deprecated 2024-11-27. New apps cannot use it. Removed from the original Phase G sketch.
- **AcousticBrainz** — shut down 2022. Dead.
- **MusicBrainz** — alive, but tempo/key metadata is sparse and community-contributed (not algorithmic). Useful for ISRC / recording lookup, not for our cross-check fields. Out of scope for Phase G; possibly useful for Phase C (sections / structure) later.
- **Hooktheory** — has chord-progression and key data, but the API is paywalled for any meaningful query volume and ToS forbids automated scraping. Out of scope.
- **Genius.com** — has lyrics and sometimes infobox metadata, but the structured tempo/key fields are inconsistent and unofficial. Possible Phase H target for lyrics-based section labels; not Phase G.
- **Tunebat** — has key/BPM/camelot, but no public API; UI-only with anti-scrape measures. Cannot use politely.
- **Cyanite** — mood/genre focused, expensive, B2B-only. Wrong audience for this project.

### 4.4 Recommendation summary

Default-enabled when secrets present:

1. **GetSongBPM** (tempo, sometimes time-sig)
2. **GetSongKey** (key) — same operator, same key, run as a pair

Opt-in for cross-validation:

3. **Musicae** or equivalent Spotify-replacement (tempo + key + time-sig + mode)

Opt-in fallback for unknown tracks:

4. **Web-search + LLM extraction** (last resort, costs LLM tokens)

This matches the Phase G sketch's "2–3 sources" intent while routing around Spotify's 2024 deprecation. The pair (1+2) gives strong tempo and key coverage on popular Western tracks for free; (3) provides the time-signature coverage the pair lacks; (4) extends coverage to long-tail tracks that aren't in any database.

---

## 5. Architecture

### 5.1 Two options considered

**Option A — pre-analysis web-research as a prior.** Run web-research first, use the result to inform pipeline expectations (e.g. constrain skey's output, restrict beat-this's tempo octave search to a band around the external value).

- **Pro:** could improve pipeline accuracy on hard cases by leaning on prior knowledge.
- **Con:** the existing pipeline stages are not parameterized to accept priors. Adding "tempo prior" to madmom or "key prior" to skey requires wrapper logic that fundamentally changes how those stages work. This is a multi-week project of its own and entangles the validation surface with the analysis surface — exactly what Phase M warned against.
- **Con:** if the external source is wrong, the pipeline now silently inherits its error. "Trust but verify" becomes "trust and obey", and we lose independence between the pipeline and the validator.
- **Con:** breaks reproducibility. Pipeline output becomes a function of network state at analysis time.

**Option B — post-analysis agreement check (recommended).** Web-research runs *after* `summary.json` is written, reads it, queries sources, writes `summary.provenance.external_check`. The pipeline's stage outputs are unchanged; only the provenance block grows.

- **Pro:** clean separation. The pipeline remains deterministic and offline; the agreement check is a validation surface bolted on top.
- **Pro:** opt-in/opt-out is trivial — add `--external-check` flag, skip the stage if disabled.
- **Pro:** disagreements are recorded, not acted on. When the pipeline is wrong, we see it in the data; when the source is wrong, the pipeline is unaffected.
- **Pro:** matches the existing `STAGE_DEPS` model — `external_check` depends on `summary_writer`, depends on everything upstream. No new wiring needed.
- **Con:** validation is observational, not corrective. A pipeline bug Phase G surfaces still has to be fixed in the pipeline.

**Recommendation: Option B.** The Phase M lesson is that any conditioning of pipeline output on external data is a foot-gun. The validation surface needs to be independent of the analysis surface to be trustworthy.

### 5.2 Stage placement in the pipeline

Add `external_check` as the *final* stage in `analyze/pipeline.py`'s loop, after `summary_writer` runs and writes `<slug>.summary.json`. The stage:

1. Reads `<slug>.summary.json` (re-parses, doesn't trust in-memory `results` dict — defends against summary-vs-results drift).
2. Parses `<slug>.summary.json["track"]["file"]` to derive (artist, title) — see Section 6.
3. Loads `cache/<slug>/external_check.json` if present and not stale (>30 days).
4. For each enabled source, queries it with (artist, title) — skipping sources that cached responses already cover.
5. Computes per-source, per-field agreement against the pipeline's emitted values, applying tolerance bands (Section 8).
6. Writes/updates `cache/<slug>/external_check.json` with the new responses and the computed agreement record.
7. Re-opens `<slug>.summary.json`, splices the agreement record into `provenance.external_check`, and re-writes.

Step 7 is unfortunate (we re-write the summary file after writing it), but it's the cleanest seam. The alternative — passing external_check through the summary writer's args — couples the writer to a network-dependent stage. Re-write is fine: the file is small, atomic-write semantics are easy.

Schema-version sidecar pattern (per Phase A+B) applies: `cache/<slug>/.params_external_check.json` records `{schema_version, params: {sources_enabled, ...}}`. Bumping `SCHEMA_VERSION` re-runs.

### 5.3 Module layout

```
analyze/
├── stages/
│   ├── external_check.py           # orchestrator stage: cached/run/load
├── research/                       # NEW package
│   ├── __init__.py
│   ├── identify.py                 # filename → (artist, title) parser
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py                 # Source protocol + tolerance helpers
│   │   ├── songbpm.py              # GetSongBPM client
│   │   ├── songkey.py              # GetSongKey client
│   │   ├── musicae.py              # Musicae client (or chosen replacement)
│   │   └── llm_fallback.py         # opt-in: web-search + LLM extraction
│   ├── normalize.py                # key string canonicalization (e.g. "Eb" ↔ "D#")
│   ├── tolerance.py                # agreement-band logic (Section 8)
│   └── cache.py                    # external_check.json read/write
└── writers/
    └── summary_writer.py           # gain a thin "splice external_check into provenance" helper
```

Tests:

```
tests/research/
├── test_identify.py                # parametrized filename fixtures
├── test_normalize.py               # key string equivalences
├── test_tolerance.py               # tempo bands, key relative, time-sig bands
├── test_songbpm.py                 # against recorded HTTP fixtures (vcrpy or json blobs)
├── test_songkey.py
├── test_musicae.py
└── test_external_check_stage.py    # end-to-end against a fixture summary.json
```

### 5.4 Source protocol

```python
# analyze/research/sources/base.py
from typing import Protocol

class Source(Protocol):
    name: str

    def query(self, artist: str, title: str) -> SourceResponse:
        """Hit the source. Return a structured response or a soft-fail record.

        Raises only on programming errors. Network errors, 404s, and
        rate-limits are returned as SourceResponse(status=...) variants.
        """

@dataclass
class SourceResponse:
    status: Literal["ok", "not_found", "rate_limited", "network_error", "auth_error"]
    fields: dict[str, Any]              # subset of {tempo_bpm, key, time_signature, mode, scale}
    raw: dict | None                    # the source's raw JSON for debugging
    error_message: str | None
```

Soft-fail discipline: each source's `query()` swallows exceptions and turns them into structured `status` values. The orchestrator never sees `requests.Timeout`; it sees `SourceResponse(status="network_error")`.

---

## 6. Track identification

The hardest sub-problem in Phase G. Pipeline output identifies tracks by `cache/<slug>/<slug>.summary.json` paths derived from the MP3 filename. External sources identify tracks by (artist, title) or by Spotify URI / ISRC. We have to bridge.

### 6.1 Filename conventions in this project

Per `CLAUDE.md`, yt-dlp emits `<title>-<id>.mp3` where `<id>` is an 11-char YouTube video ID. Examples in `cache/`:

| `<slug>` | Original `<title>` | Inferred artist / title |
|---|---|---|
| `gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg` | `Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)` | Gorillaz / Silent Running |
| `charlie_puth_attention` | `Charlie Puth - Attention` (manual rename, no YT id) | Charlie Puth / Attention |
| `joesef_comedown_official_video_zaprrzdhyiw` | `Joesef - Comedown (Official Video)` | Joesef / Comedown |
| `leonard_cohen_in_my_secret_life` | `Leonard Cohen - In My Secret Life` | Leonard Cohen / In My Secret Life |
| `crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c` | `Crippled Black Phoenix - In Bad Dreams` | Crippled Black Phoenix / In Bad Dreams |
| `baleen_unmedicated` | `Baleen - Unmedicated` (manual) | Baleen / Unmedicated |

Observations:

- Slugs are lowercased and `[^a-z0-9]+` is collapsed to `_`. The `<title>` was lossy-transformed; recovering the original is impossible without reading `summary.json["track"]["file"]` (which retains the original `.mp3` filename).
- Most original filenames follow `<Artist> - <Title>` with " - " (space dash space) as separator. yt-dlp users sometimes have `<Artist>: <Title>` or `<Artist>_<Title>` instead; this project's `CLAUDE.md` directs single-format YouTube downloads, so " - " dominates.
- The trailing 11-char alphanumeric YT id is detectable by regex (`[A-Za-z0-9_-]{11}` at end). When present, strip it before parsing.
- Suffix noise: `(Official Video)`, `(Official Audio)`, `[HD]`, `(Lyrics)`, `(Live at ...)`. Strip before sending to source.

### 6.2 Identification algorithm

```python
# analyze/research/identify.py — sketch
import re

YT_ID_RE = re.compile(r"-([A-Za-z0-9_-]{11})$")
SUFFIX_NOISE = [
    r"\(Official Video\)", r"\(Official Audio\)", r"\(Official Music Video\)",
    r"\(Lyrics\)", r"\(Lyric Video\)", r"\[HD\]", r"\[4K\]",
    r"\(Audio\)", r"\(Visualizer\)",
]

def identify_from_filename(mp3_filename: str) -> TrackIdentity:
    """Best-effort (artist, title) extraction from yt-dlp filename.

    Returns a TrackIdentity with confidence in [0.0, 1.0] reflecting how
    much we had to guess. Confidence drops with each unrecognized suffix
    and with non-standard separator characters.
    """
    name = Path(mp3_filename).stem  # drop .mp3

    # Strip YT id suffix if present (e.g. "...-0pf48rqssg")
    m = YT_ID_RE.search(name)
    if m:
        name = name[: m.start()]

    # Strip parenthetical/bracketed noise
    for pattern in SUFFIX_NOISE:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()

    # Try " - " split first (canonical yt-dlp format)
    if " - " in name:
        artist, title = name.split(" - ", 1)
        confidence = 0.95
    elif " — " in name:           # em-dash variant
        artist, title = name.split(" — ", 1)
        confidence = 0.90
    elif " : " in name:
        artist, title = name.split(" : ", 1)
        confidence = 0.80
    else:
        # No recognized separator — last resort, treat the whole thing
        # as title and let sources do fuzzy match.
        return TrackIdentity(artist=None, title=name.strip(), confidence=0.30)

    return TrackIdentity(
        artist=artist.strip(),
        title=title.strip(),
        confidence=confidence,
    )
```

### 6.3 Disambiguation + LLM fallback

When a structured source returns multiple matches (e.g. there are 12 tracks called "Attention" by various artists), the algorithm picks the one whose `artist` matches our parsed artist. When no source has a match, the LLM-fallback tier (Section 4.2.4, opt-in) can be invoked to disambiguate via web search.

The chat-actor in webui already has Claude available and could in principle do the disambiguation, but Phase G keeps the pipeline self-contained. The webui chat actor is a *consumer* of `external_check`, not a participant in producing it.

### 6.4 What we do not attempt

- ISRC lookup. Would need MusicBrainz round-trip, and ISRCs are not on the file. Defer.
- Acoustic fingerprinting (Chromaprint / AcoustID). Could turn any audio file into a MusicBrainz match. Heavyweight; defer; possibly Phase H if filename-based identification proves too unreliable.
- Fuzzy title matching with edit distance. Sources do this internally; we defer to them.

---

## 7. Schema for `summary.provenance.external_check`

```json
{
  "external_check": {
    "queried_at": "2026-05-09T10:32:11Z",
    "schema_version": 1,
    "track_identification": {
      "method": "filename-split",
      "raw_filename": "Charlie Puth - Attention.mp3",
      "artist": "Charlie Puth",
      "title": "Attention",
      "confidence": 0.95
    },
    "sources": {
      "songbpm": {
        "status": "ok",
        "queried_at": "2026-05-09T10:32:11Z",
        "tempo_bpm": 100,
        "time_signature": "4/4",
        "agrees_tempo_within_bpm": 0.4,
        "agrees_tempo_within_5pct": true,
        "agrees_tempo_double": false,
        "agrees_tempo_half": false,
        "agrees_time_signature": true
      },
      "songkey": {
        "status": "ok",
        "queried_at": "2026-05-09T10:32:11Z",
        "key": "D# minor",
        "agrees_key_exact": true,
        "agrees_key_relative": false,
        "agrees_key_parallel": false
      },
      "musicae": {
        "status": "rate_limited",
        "queried_at": "2026-05-09T10:32:11Z",
        "error_message": "429 Too Many Requests; retry after 60s"
      }
    },
    "summary": {
      "n_sources_enabled": 3,
      "n_sources_responded": 2,
      "n_fields_checked": 3,
      "n_fields_agreed": 3,
      "agreement_pct": 1.0,
      "any_disagreement": false
    }
  }
}
```

### 7.1 Field semantics

- **`status`** per source: `"ok" | "not_found" | "rate_limited" | "network_error" | "auth_error" | "disabled" | "cached"`. `disabled` = source secret not configured. `cached` = response served from `external_check.json`, unchanged this run.
- **`queried_at`** per source records when *that source* was last hit (may differ from the top-level `queried_at` if some sources were served from cache).
- **`agrees_tempo_within_bpm`** is the absolute BPM delta (always positive). The companion `agrees_tempo_within_5pct` is the booleanized agreement under our tolerance band (Section 8).
- **`agrees_tempo_double` / `agrees_tempo_half`** are MIR-failure-mode flags. If our pipeline says 200 and the source says 100, both agreement booleans are `false` but `agrees_tempo_half: true` flags the half-tempo MIR failure pattern. This is observational only; we do not auto-correct.
- **`agrees_key_exact`** = same tonic + same mode. **`agrees_key_relative`** = relative-major/minor flip (e.g., we said "F minor", source says "Ab major"). **`agrees_key_parallel`** = same tonic, different mode (we said "F minor", source says "F major"). All three booleans can be true simultaneously only in the trivial case `agrees_key_exact=true`; otherwise mutually exclusive.
- **`summary.n_fields_agreed`** counts each field once across all responding sources, using a "majority of responding sources agree" rule. If two sources agree and one disagrees, the field is counted as agreed. Edge case: two sources, split — counted as `disagreed` (no majority).

### 7.2 What downstream consumers do with this

- **The webui chat actor** opens a track and reads `provenance.external_check`. First message becomes data-grounded: "Songbpm.com lists this as 100 BPM in 4/4. Our pipeline computed 100.0 BPM in 4/4 — those match. Songkey.com says D# minor; our pipeline says D# minor — match. Two of three sources responded; Musicae was rate-limited."
- **The benchmark dashboard** (Section 11) walks `cache/*/` and aggregates `summary.agreement_pct` across all tracks. A regression in any future change shows up here.
- **The user, when reading `summary.json` directly,** sees disagreements as obvious flags rather than buried in numbers.

---

## 8. Tolerance bands

External sources are not byte-equal to pipeline outputs even when both are correct. Tolerances quantify "close enough":

### 8.1 Tempo

- **Direct agreement:** `|pipeline.tempo_bpm - source.tempo_bpm| ≤ max(1.0, 0.05 * pipeline.tempo_bpm)`.
  - Whichever is larger of ±1 BPM and ±5%. The 1 BPM floor handles slow tracks (e.g. 60 BPM ballad: 5% is 3 BPM, but the pipeline routinely lands within 1 BPM); the 5% ceiling handles fast tracks (180 BPM: 5% is 9 BPM, within reasonable beat-detection tolerance).
- **Half-tempo flag:** `|pipeline.tempo_bpm - 2 * source.tempo_bpm| ≤ max(1.0, 0.05 * source.tempo_bpm * 2)`. We're at double what the source says.
- **Double-tempo flag:** `|pipeline.tempo_bpm - source.tempo_bpm / 2| ≤ max(1.0, 0.05 * source.tempo_bpm / 2)`. We're at half what the source says.

The half/double flags are MIR-octave-failure signals. They are independent of the direct-agreement boolean (they may both be false, or the half-flag may be true and direct-agreement false). All three live alongside each other in the schema.

**Note on jazz / world music.** Some genres legitimately oscillate between half- and double-tempo descriptions (e.g. swing-feel tunes scored at 120 may be "felt" at 60). The pipeline is consistent (it picks one); the source may pick the other. The half/double flag captures this without judgement.

### 8.2 Key

Keys are compared as canonicalized `(tonic_pc, mode)` tuples. Canonicalization handles enharmonic equivalence:

- `D#` ↔ `Eb` (same `tonic_pc=3`)
- `F#` ↔ `Gb`
- `C#` ↔ `Db`
- `G#` ↔ `Ab`
- `A#` ↔ `Bb`

Mode normalizes to `{"major", "minor"}`. Modal sources (Dorian, Phrygian, etc.) collapse to their parent (Dorian → minor, Mixolydian → major, etc.) — coarser than `analysis.scale` but matches what most external sources actually report.

- **`agrees_key_exact`:** `(pipeline_pc, pipeline_mode) == (source_pc, source_mode)`.
- **`agrees_key_relative`:** relative-major/minor. `pipeline = ("F", "minor")`, `source = ("Ab", "major")`. Relative pair: `(minor_pc + 3) % 12 == major_pc`. Common MIR ambiguity — many tracks are tonally ambiguous between the two.
- **`agrees_key_parallel`:** same tonic, different mode. `pipeline = ("F", "minor")`, `source = ("F", "major")`. Less common; usually a real disagreement.

### 8.3 Time signature

String comparison after normalization (`"4/4"` ↔ `"4 / 4"` ↔ `"common"`). Most sources only report `3/4` vs `4/4`; the schema accepts `"unknown"` for sources that don't have it.

- **`agrees_time_signature`:** exact match after normalization.

There is no "close enough" for time signature — `4/4` and `3/4` are categorically different.

### 8.4 Scale (optional)

If `analysis.scale` is `"Aeolian"` and the source has only `"minor"`, count as agreement (Aeolian = natural minor). If `analysis.scale` is `"Dorian"` and source has `"minor"`, count as agreement-with-warning (Dorian is *a* minor mode, but distinct). Granular scale agreement is low-priority — most sources don't report scale at this resolution. Mark it optional in the schema and tolerate missing data.

---

## 9. Caching

External API calls cost rate-limit budget. Cache discipline:

- **Cache file:** `cache/<slug>/external_check.json`.
- **Cache key:** `(source_name, artist, title)`. Source upgrades (e.g. switching from songbpm v1 → v2) invalidate via the schema-version sidecar.
- **TTL:** 30 days. After 30 days, re-query (popular tracks may have updated metadata; this is rare but cheap to re-check).
- **Negative caching:** `status: "not_found"` responses are also cached, with a shorter TTL (7 days). Re-querying every run for tracks the source doesn't have wastes the rate-limit budget.
- **Rate-limit responses (`status: "rate_limited"`)** are *not* cached — the source is temporarily over budget, not permanently empty.
- **Network-error responses (`status: "network_error"`)** are not cached for the same reason.
- **`auth_error`** is not cached but is *fatal for the source this run* — once a source returns an auth error, skip it for the rest of the run. The user has a credentials problem to resolve before retry.
- **The 30-day TTL is per-source, per-track,** stored as `last_queried_at` in the cached entry. Independent of the top-level `queried_at`.

Cache layout sketch:

```json
{
  "schema_version": 1,
  "track_identification": { ... },
  "responses": {
    "songbpm": {
      "last_queried_at": "2026-05-09T10:32:11Z",
      "status": "ok",
      "fields": {"tempo_bpm": 100, "time_signature": "4/4"},
      "raw": { ... }
    },
    "songkey": {
      "last_queried_at": "2026-05-09T10:32:11Z",
      "status": "not_found",
      "fields": {},
      "raw": null
    }
  }
}
```

The orchestrator reads this at the start of each run, decides per-source whether to re-query or use cached, then writes the merged result back. The agreement record (booleans + summary) is *always* recomputed from live `summary.json` values — only the source responses are cached.

---

## 10. Authentication & secrets

GetSongBPM and GetSongKey require API keys (free, requires registration with email + intended-use disclosure). Musicae and equivalent third-party APIs are similarly key-gated.

### 10.1 Where secrets live

Per the global `CLAUDE.md`, the user's canonical .env for image-generation lives at `C:/Users/<you>/.claude/skills/cloud-image-gen/.env`. **Phase G does not reuse that file.** The MusIQ-Lab project gets a project-local `.env`:

```
<PROJECT_PATH>/.env
```

Loaded via `python-dotenv` at the top of `analyze/research/__init__.py`:

```python
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[2] / ".env", override=False)
```

`override=False` so a process-level env-var (e.g. CI) takes precedence.

### 10.2 Required vars

```
# .env at MusIQ-Lab project root
GETSONGBPM_API_KEY=...                 # free at https://getsongbpm.com/api
GETSONGKEY_API_KEY=...                 # free at https://getsongkey.com/api (often same operator → same key)
MUSICAE_API_KEY=...                    # optional; opt-in source
EXTERNAL_CHECK_LLM_FALLBACK=false      # opt-in switch for the LLM tier
ANTHROPIC_API_KEY=...                  # only required if EXTERNAL_CHECK_LLM_FALLBACK=true
```

### 10.3 .gitignore + safety

Add `/.env` to `.gitignore` if not already. Add a `.env.example` checked-in template that documents the required vars without values. The pipeline never logs secret values; on `auth_error`, the message is "songbpm: invalid API key" not "songbpm: invalid API key abc123...".

### 10.4 Behaviour without secrets

- **No secrets at all + `--external-check` not specified:** stage is silently skipped, `provenance.external_check` is absent.
- **No secrets + `--external-check` explicitly passed:** stage runs, every source returns `status: "auth_error"` (or `disabled` if no key configured at all), `summary.agreement_pct` is `null`, the warning `external_check requested but no source secrets configured` is added to `provenance.warnings`.
- **Some secrets present:** stage runs the configured sources, missing ones report `status: "disabled"`.

The default behaviour for a fresh checkout with no `.env` is "everything works as before". The check is opt-in by configuration.

---

## 11. Failure modes

Every failure mode produces a structured record, never an exception that escapes the stage:

| Failure | `status` value | Recovery |
|---|---|---|
| Track not found in any source | `not_found` per source | `summary.n_fields_agreed = 0`; chat actor says "external metadata not available for this track" |
| All sources rate-limited | `rate_limited` per source | re-query next run; cached `ok` responses still apply |
| Network down | `network_error` per source | re-query next run |
| Filename unparseable (no separator, low confidence) | `track_identification.confidence < 0.3` | skip all sources; `summary.warnings` adds "external_check skipped: could not identify track from filename" |
| Ambiguous artist/title (multiple match) | source-specific; usually picks first | recorded in `raw`, may still be the right track |
| Auth error (bad key) | `auth_error` per source | source skipped for rest of run; user-actionable warning surfaces in webui banner |
| API contract change (source returns unexpected JSON shape) | `network_error` with `error_message: "JSON shape unexpected: ..."` | non-fatal, re-query next run; if persistent, the source's adapter needs updating |
| `summary.json` missing required field | refuse to run; raise `ExternalCheckPreconditionError` | this is a programming error, not runtime — pipeline.py would not have written incomplete summary; bubbles up as a hard fail of the external_check stage with no soft-recovery |

The pipeline-level `external_check` stage is in `OPTIONAL_STAGES`, so any uncaught exception still soft-fails per the existing pipeline policy (`analyze/pipeline.py`). The intent is that no uncaught exception ever reaches that level — every failure is structured — but the soft-fail safety net catches programming errors.

---

## 12. Implementation phases

### G.1 — Track identification (~50 LOC + tests)

- `analyze/research/identify.py` with the `identify_from_filename()` function from Section 6.2.
- `analyze/research/normalize.py` with key-string canonicalization.
- `tests/research/test_identify.py` — parametrized over a fixture list of 30+ filenames covering yt-dlp `<title>-<id>` patterns, manual `Artist - Title.mp3` patterns, edge cases (em-dash, colon, no separator, multiple parentheticals, leading/trailing whitespace).
- `tests/research/test_normalize.py` — `D#` ↔ `Eb` round-trips, mode normalization (Dorian → minor, etc.).

**Acceptance:** all `cache/*/` slugs in this project parse to a `TrackIdentity` with confidence ≥ 0.8, and every parametrized test case passes.

**Effort:** half a day.

### G.2 — Source: GetSongBPM + GetSongKey (~250 LOC + tests)

- `analyze/research/sources/songbpm.py` with `Source` protocol implementation.
- `analyze/research/sources/songkey.py` likewise.
- HTTP via `httpx` (already in `webui/` deps; add to analyze venv lock).
- Recorded HTTP fixtures (json blobs in `tests/research/fixtures/`) — does not require network in tests.
- One opt-in integration test gated on env-var (`MUSIQLAB_RUN_NETWORK_TESTS=1`) that hits the live API on Gorillaz Silent Running and asserts the response shape, not values. Validates the API hasn't drifted.

**Acceptance:** unit tests with fixtures pass on every CI run; integration test passes when network is available.

**Effort:** 1 day per source — there are two sources but they share an API surface from the same operator, so closer to 1.5 days total.

### G.3 — Source: Musicae (or equivalent Spotify-replacement) (~150 LOC + tests)

- Same shape as G.2.
- The exact API to integrate is decided at implementation time, after a brief market check (these third-party shims have churn; the spec deliberately doesn't lock the choice — Section 4.2's recommendation is operating-environment-conditional).

**Acceptance:** as G.2.

**Effort:** 1 day, with the tax on it being "evaluate which Musicae-equivalent has the best free tier and reliability *at implementation time*".

### G.4 — Orchestrator + summary splice (~200 LOC + tests)

- `analyze/stages/external_check.py` with `cached() / load() / run()` matching the existing stage protocol.
- Integration with `analyze/pipeline.py`: append `external_check` to `OPTIONAL_STAGES`, ensure it runs after `summary_writer`.
- Thin `splice_external_check_into_summary()` helper in `analyze/writers/summary_writer.py` (does the post-write modify dance from Section 5.2).
- Cache file read/write (`analyze/research/cache.py`).
- `tests/research/test_external_check_stage.py` — end-to-end against a fixture summary.json + mocked Source instances.

**Acceptance:** `python -m analyze tests/fixtures/silent_running_clip.mp3 --external-check` produces a summary.json with a populated `provenance.external_check` block. Cached run within 30 days reuses the cache.

**Effort:** 2 days, the highest-risk piece because of the summary-rewrite seam.

### G.5 — Tolerance scoring + summary stats (~100 LOC + tests)

- `analyze/research/tolerance.py` with the band logic from Section 8.
- `tests/research/test_tolerance.py` — parametrized over hand-crafted (pipeline, source) value pairs covering each band and each flag.
- Aggregate `summary.n_fields_agreed` / `agreement_pct` calculation in the orchestrator.

**Acceptance:** every band-edge test case (1 BPM exactly, 5% exactly, 199 vs 100 for half-tempo, F minor vs Ab major for relative-key, etc.) classifies the way the spec says it should.

**Effort:** half a day.

### G.6 — Optional: web-search + LLM extraction fallback (~150 LOC + tests)

- `analyze/research/sources/llm_fallback.py`. Uses `claude-agent-sdk` (already a project dep via webui) or direct Anthropic SDK call. Web search via the model's tool surface or a structured search API (DuckDuckGo, etc.).
- Disabled by default; enabled only when `EXTERNAL_CHECK_LLM_FALLBACK=true` AND `ANTHROPIC_API_KEY` is set.
- Cost ceiling: max 1 LLM call per track per run, only when *all* structured sources returned `not_found`.
- Tests against mocked LLM responses (no network).

**Acceptance:** when enabled, recovers fields for at least one of (handful of indie tracks not in any structured source) without hallucinating values for tracks that genuinely don't have public metadata.

**Effort:** 2 days. Defer until G.1–G.5 ship and the gap is measured.

### G.7 — Webui chat actor integration (~50 LOC + tests, in webui not analyze)

- `webui/webui/chat_actor.py` reads `summary.provenance.external_check` and surfaces it in the opening message of any track conversation.
- Banner in the track-detail UI when `summary.any_disagreement == true`.
- Unit test on the chat actor's "first message" generator, asserting the agreement string format on a fixture summary.

**Acceptance:** opening Gorillaz Silent Running in the webui shows "songbpm.com agrees on tempo (107 BPM); songkey.com agrees on key (F minor)" or similar.

**Effort:** half a day. Could ship in a follow-up PR; not strictly part of Phase G.

### G.8 — Benchmark dashboard (~100 LOC, optional)

- A small script `scripts/external-check-aggregate.py` that walks `cache/*/`, reads each `summary.json`, and prints aggregate agreement: "27/30 tracks agree on key, 28/30 on tempo, 22/30 on time-sig". Used as a regression signal after future analyze changes.
- Could land as a Phase G follow-up or Phase H entry.

**Effort:** half a day. Optional.

### Total Phase G effort

- **Critical path (G.1 → G.5):** ≈4–5 days of focused work.
- **With LLM fallback (G.6):** add 2 days.
- **With webui surfacing (G.7):** add 0.5 days.
- **With benchmark dashboard (G.8):** add 0.5 days.

Comparable to the Phase 0c arc (~1 week). Independent of the Phase A+B specialist work — does not touch any stage's algorithm.

---

## 13. Out-of-scope / deferred

- **Chord-progression cross-check.** Hooktheory paywall + ToS. Genius / Chordify partial and unreliable. Defer until either a free chord-database emerges or the pipeline's chord output is trustworthy enough that external validation is overkill.
- **Lyrics-based section labels (Genius).** Useful but a different problem; possibly Phase H.
- **HNR voicing for the Cohen 107.7s canary** (Rec 4 from Phase 0c). Independent work item.
- **Acoustic-fingerprint identification** (Chromaprint / AcoustID → MusicBrainz). Heavyweight; pursue only if filename-based identification proves too unreliable on this corpus. Promising signal: confidence-< 0.5 rate across `cache/*/`.
- **Sections / structure.** Waits on Phase C anyway; no good external source.
- **Per-detection confidence rollup.** Phase D.
- **Auto-correction of pipeline output based on external sources.** Foot-gun (see Phase M lessons). Phase G observes; correction is a separate, later, controversial design discussion.
- **Integration with the manual-corpus workflow.** When the user labels a corpus, those labels and the external-check labels both feed into a unified `validation_report.json` per track. That unification is Phase H, not G.

---

## 14. Open questions

These need user input before G.1 starts:

1. **Which sources to enable by default?** The spec recommends GetSongBPM + GetSongKey + Musicae (or equivalent). The user may have preferences — e.g., wants to avoid the GetSongBPM backlink-required terms. **Decision needed:** confirm the default-enabled set, or specify alternatives.

2. **Should disagreement ever block the pipeline?** The spec says no — Phase G is observational. The user may want a `--strict` mode that fails the run if (n_fields_agreed / n_fields_checked) < some threshold. **Default recommendation:** never block; surface in the chat actor and the dashboard. **Decision needed:** confirm "never block".

3. **Cost ceiling for the LLM fallback (G.6).** The fallback gates on `all structured sources returned not_found`, but on a long-tail-heavy corpus this could fire on most tracks. **Decision needed:** opt-in (default-off) is the conservative choice; the alternative is opt-in-with-budget (e.g., max N LLM calls per `python -m analyze` invocation).

4. **Scope of `track_identification.method`.** The spec describes `"filename-split"`. If the user wants a future "manual override" path (e.g., a `cache/<slug>/track_identity.override.json` checked into the cache), that's a small addition but the schema needs to anticipate it. **Decision needed:** open the door to manual overrides in v1, or defer?

5. **Chat actor surfacing (G.7).** Should the chat actor proactively show external check on every track open, or only when there's a disagreement? Proactive surfacing is more visible but noisier. **Default recommendation:** proactive on the *opening message* (one line), banner only on disagreement.

6. **Should `external_check` ever invalidate `cached()` for upstream stages?** I.e., if `external_check` says "tempo disagrees by 50%", does the user want `--from-stage beats` to fire automatically next run? The spec says no (auto-correction is out of scope). The user may want a softer alternative — e.g., a warning that the *next* manual run should pass `--from-stage beats`. **Decision needed:** confirm "external_check never auto-invalidates upstream caches".

These are the six the spec needs resolved before G.1. Other questions (which Musicae-equivalent to integrate, exact LLM model for fallback, dashboard format) can be deferred to implementation time.

---

## 15. Reading order for a fresh implementer

1. `docs/history.md` Phase M — the lesson that motivates this.
2. `docs/pipeline-changes-phase-ab.md` §"Phase G — proposed" — the original sketch (now superseded by this spec).
3. This document.
4. `analyze/writers/summary_writer.py` — the file you'll be splicing into.
5. `analyze/pipeline.py` — to understand `STAGE_DEPS`, `OPTIONAL_STAGES`, and where `external_check` slots in.
6. `cache/gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg/` (or similar) — a reference end-to-end track to test against.
7. `docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md` Section "Reviewer subagent prompt template" — the convention this project uses for spec-driven implementation, if Phase G is run as a subagent loop.
