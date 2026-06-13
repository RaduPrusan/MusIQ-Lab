---
title: Documentation & memory staleness + coherence audit
updated: 2026-06-13
status: research
description: Repo-wide audit of stale documentation, stale/duplicate memory, and cross-doc coherence, verified against current code. Six parallel verification streams (entry docs, CLAUDE.md, docs/ architecture, analyze package + runbooks, webui docs, memory bank).
---

# Documentation & memory staleness + coherence audit

**Date:** 2026-06-13 · **Method:** 6 read-only verification agents, each scoped to a non-overlapping
doc set, verifying every concrete claim against current code (Read/Grep/Glob). Highest-impact
findings re-verified by hand (see the inline ✅ marks). No files were modified during the audit.

## Executive summary

The documentation is in **good overall health** — link integrity is high, the memory index is a
perfect bijection, every memory's named code symbol still exists, and the frozen design docs are
correctly fenced behind "frozen at design time / SUPERSEDED" banners so abandoned ideas (allin1,
AsioEngine) don't read as current.

The real defects cluster into a few themes:

1. **The `cache/gorillaz_silent_running/` short-slug myth** — propagated to ≥5 docs + the test
   suite; the on-disk dir is the long slug, and the mismatch **silently skips an integration test**.
2. **Two living docs drifted ~1 month behind shipped work** — `webui/CHANGELOG.md` (stops at
   2026-05-13, missing the v1.0.0/AGPL release and the entire live-mic layer) and the webui README's
   sidebar-tab section (still says "Claude", wrong order).
3. **A stale task-prompt that would re-introduce a deliberately-reverted behavior** —
   `prompts/fix-key-scale-enharmonic-coherence.md` instructs an implementer to adopt the *old*
   enharmonic rule that was superseded in commit `d3c302a`.
4. **Counted-fact drift** — "~970 tests" (actual ~1060 Python + ~300 JS), "~131 packages"
   (actual 150), Torch "2.7.0" (actual 2.7.1).
5. **One self-contradiction in the flagship README** — four notation systems claimed on line 56,
   two everywhere else and in code.

**Severity totals (deduplicated across streams):** STALE 12 · BROKEN-LINK 4 · COHERENCE 7 ·
DUPLICATE/SUPERSEDED (memory) 2 · MINOR ~10.

---

## Part 1 — Cross-cutting issues (touch multiple files)

### X1. `cache/gorillaz_silent_running/` does not exist — BROKEN-LINK + masked test ✅ verified
The validation reference cache was renamed to the long-slug convention. On disk:
`cache/gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg/`. The short underscore
slug `gorillaz_silent_running` survives only as a hard-coded fixture alias.

Appears in: `CLAUDE.md:19`, `docs/README.md:60,64,71`, `docs/history.md` (multiple), `analyze/README.md:71`,
`prompts/test-stack-torch27.md:374`.

**Teeth:** `tests/integration/test_gorillaz.py:30,37-38` `.exists()`-guards the short path and
`pytest.skip`s when absent → the integration test reports green while not running.
`tests/integration/test_vocal_consensus_gorillaz.py:37-40` already works around this by trying both slugs.

**Fix (pick one):**
- (a) Create a junction `cache/gorillaz_silent_running` → the long-slug dir, **or**
- (b) Update the test fixture + all five docs to the long slug.
Recommend (a) — it un-skips the test and makes every doc reference resolve with one change.

### X2. `requirements.lock` package count: docs say "~131", actual **150 pins / 154 lines** ✅ verified
Appears in: `README.md:246`, `AGENTS.md:220`, `INSTALL.md:612`. Fix: change all three to "~150".

### X3. Test-count drift: docs say "~970", actual ~1060 Python + ~300 JS
`def test_` counts: `tests/` = 570, `webui/tests/` = 490 (= 1060 Python); plus ~298 JS cases in
`webui/tests-js/`. Appears in: `CLAUDE.md:22`, `AGENTS.md:131`, `analyze/README.md:68,71`.
The `~` makes it approximate by design; `analyze/README.md` even hedges with the `--collect-only`
source-of-truth command. Low urgency — bump to "~1050 Python + ~300 JS" or drop the number.

### X4. Torch version string: "2.7.0" vs lock's `torch==2.7.1+cu126`
`CLAUDE.md:22` says "Torch 2.7.0+cu126". `requirements.lock:143` pins `2.7.1+cu126` (the
2026-05-26 security audit raised the lane 2.7.0→2.7.1). The `~2.7.0` pin from `deezer/skey` still
holds, so the "don't bump off 2.7" rule is intact. `INSTALL.md:251` and `prompts/test-stack-torch27.md`
already say 2.7.1 correctly. Fix: `CLAUDE.md:22` → "2.7.1+cu126" (or "~2.7.x").

---

## Part 2 — Entry docs (README, AGENTS, INSTALL, SECURITY, security-audit)

- **[STALE] `README.md:56`** ✅ — "Multiple notation systems — Scientific, Solfège, **Flat-only,
  Sharp-only**". Only two exist (`webui/static/js/music/notation-prefs.js:6`
  `VALID = {"scientific","solfege"}`); README's own line 31 says "(Scientific or Solfège-Romance)".
  Fix: "switch globally between Scientific (C♯4) and Solfège (Do♯4)".
- **[STALE] `AGENTS.md:56`** — AcoustID key location wrong. The key is read from env
  `ACOUSTID_API_KEY` via `analyze/keys.py:28-30` (`.env` at project root), **not** a slot in
  `identify.py` (whose docstring says nothing about it). Fix: "set `ACOUSTID_API_KEY` in the
  project-root `.env` (read by `analyze/keys.py`)". (This also matches SECURITY.md's guidance.)
- **[STALE] `SECURITY.md:17`** — "Before the project is public, report issues privately…". Repo went
  public 2026-05-26 (AGPL-3.0). Fix: drop the pre-publication conditional; state GitHub private
  vulnerability reporting directly.
- **[COHERENCE] `INSTALL.md:23` vs `:207`** — self-contradicting model-download size ("~5 GB" on
  line 23 vs "~8 GB" on 207 and in README/AGENTS). ~8 GB is *downloaded*; ~5 GB is the resident
  *cache* after install. Fix: line 23 → "~8 GB".
- **[COHERENCE] `AGENTS.md:198`** ✅ — repo-layout diagram lists `webui/webui/main.py` as "uvicorn
  entry". No such file; the entry is `webui/webui/__main__.py` (→ `webui.server:app`); the FastAPI app
  is `webui/webui/server.py`. Fix the diagram lines.
- **[MINOR] `INSTALL.md`** — described as "10 phases" but headers run Phase 0–10 (11 sections).
  Defensible (Phase 0 = prereqs); optionally say "phases 0–10".
- **Clean:** `docs/security-audit-2026-05-26.md` (all dependency claims verify against the lock
  files); all entry-doc cross-links resolve; all INSTALL scripts exist; port/Python versions/lifecycle
  verbs all correct.

---

## Part 3 — Project `CLAUDE.md`

- All 8 `[[memory]]` links resolve; 24 of 25 named paths exist (the 25th = X1 gorillaz cache).
- Every dense feature paragraph verified symbol-for-symbol against code: WASAPI engine, live mic +
  2026-05-23 iteration, sidebar/theme 2026-05-24 (`DEFAULT_PRESET_ID="jinn"`), pitch-notation (two
  systems), enharmonic spelling (`_MAJOR_FLAT_PCS`/`_MINOR_FLAT_PCS`/`_canonical_tonic`), identify
  (SCHEMA=5, `_preserve_or_write`, `--no-identify`), drums/LarsNet soft-fail, vocal consensus
  Phase 0c (`viterbi_enabled`). All ✅ pass.
- **[STALE]** Torch "2.7.0" (X4) and "~970 tests" (X3).
- **[BROKEN-LINK]** `cache/gorillaz_silent_running/` (X1).
- **[COHERENCE, low]** Download section hardcodes `C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe` and never
  mentions `$MUSIQ_YTDLP_BIN` — the shipped canonical override (`webui/webui/analyze_runner.py:502`,
  `scripts/fetch-test-fixtures.sh:17`). Defensible (CLAUDE.md's top banner frames the download section
  as the maintainer's private runbook), but a one-line nod to the env var would reconcile it with the
  stated convention in memory `ytdlp_env_var_convention`.
- **[MINOR/info]** "walker-based result iteration" attributed to the identify stage actually lives one
  module deeper in `analyze/clients/acoustid.py:99,146` (the claim is accurate, just relocated).

---

## Part 4 — `docs/` architecture & chronology

- **[BROKEN-LINK] `docs/history.md:96,107`** ✅ — references `scripts/refresh-essentia.sh`; only
  `scripts/install-essentia.sh` exists (no `refresh-*` script at all). Fix: rename to the real script
  or describe it as a since-removed one-off.
- **[BROKEN-LINK] `docs/README.md:60,64,71`** — gorillaz cache path (X1).
- **[COHERENCE] `docs/pipeline-changes-phase-ab.md:134,263`** — documents drums "schema v3"; code is
  `drums.py:40` `SCHEMA_VERSION = 4`. Doc is a frozen Phase-A/B point-in-time reference (header:
  "Shipped through HEAD 574f3ab"), so it was correct at authorship — add "(drums schema since advanced
  to v4)" or leave per frozen-doc convention.
- **[COHERENCE] `docs/pipeline-changes-phase-ab.md:216,260,272`** — cache-layout/provenance snippets
  still list `transcription_vocals.json` (NEW) although the same doc's §2a documents the revert
  (commit 574f3ab); the module and artifact are absent. Strike the snippet lines to match the prose.
- **[MINOR] `docs/history.md:600`** — "## Phase K — Memory anchors" appears *after* Phase R, breaking
  the A→R lettering (K is skipped mid-sequence, then reappears last). Rename to an unlettered appendix.
- **[MINOR] `docs/superpowers/plans/2026-06-13-deferrals-remediation-roadmap.md` Tier 0** ✅ — presents
  three WASAPI files as still carrying "Phase 1 stub" comment-rot with unchecked "do now" steps; those
  strings are already gone from the code (the fixes landed, commit `34e64d9`). Mark Tier 0 ✅ done.
  Also two off-by-one line citations (summary_writer.py:138 → 139) and a reference to
  `docs/research/2026-06-13-deferrals-audit.md` that isn't on disk (hedged in-text as "if persisted").
- **Clean (exemplary):** `docs/README.md` (allin1 correctly fenced as frozen; section detection
  correctly "deferred"), `docs/webui/PROGRESS.md` (leads with a "SUPERSEDED — historical brainstorm"
  banner, self-corrects `:8080`→`:8765` and AsioEngine→WASAPI), the `docs/research/` tree.

---

## Part 5 — analyze package & runbooks

- **[STALE] `prompts/fix-key-scale-enharmonic-coherence.md`** — **highest-value item in this section.**
  Reads as a live task ("Your single job is to make…") but the work shipped (`canonical_key_name`
  exists at `theory.py:459`; commits `ebf53a7`+`d3c302a`). Worse, it instructs the implementer to use
  `_PREFER_FLAT_PCS = {1,3,6,8,10}` for minor — a rule **superseded** by the conventional
  circle-of-fifths rule now in code (`_MINOR_FLAT_PCS={3,10}`, `_MAJOR_FLAT_PCS={1,3,8,10}`). Anyone
  following it would revert the spelling the maintainer deliberately moved to. Fix: add a
  "SHIPPED (commits ebf53a7+d3c302a; rule later revised)" banner or archive the file.
- **[STALE] `analyze/README.md:71`** + **`prompts/test-stack-torch27.md:374`** — gorillaz cache path
  (X1). The runbook hand-builds `cache/gorillaz_silent_running` because it predates the `analyze/`
  driver; worth a one-line note that `python -m analyze` derives the long slug.
- **[STALE, partial] `prompts/next/phase-c-structural-layer.md:32`** — lists "time-signature
  detection — replace hard-coded `beats_per_bar=[3,4]`" as future work; `beats.py:49-62` already emits
  a derived `time_signature`/`beats_per_bar` (SCHEMA bumped to 2 for exactly this). Per-section TS is
  still pending. Annotate the bullet "partial".
- **[COHERENCE] `analyze/README.md:3`** — "validated **8-stage** MIR pipeline"; `pipeline.py`'s
  `_STAGE_EXECUTION_ORDER` has 13 stages (the README's own bullet list enumerates all of them). "8-stage"
  is a holdover from the runbook's Phase-6 stages 1–8. Fix: "13-stage" or "multi-stage".
- **[MINOR] `analyze/README.md`** — `--no-essentia` exists in `cli.py:65` but isn't in the README CLI
  examples (which do list `--no-identify`). Doc gap, not an error.
- **Clean:** all CLI flags (`--stems-quality` not `--quality`, `--from-stage`, `--params-json`,
  `--force`, `--quiet`, `--slug`), all runbook model entry points (skey/lv-chordia/beat-this/torchfcpe,
  matching memory `mir_api_quirks`), Torch pins (runbook correctly says 2.7.1), and
  `analyze/vendor/README.md` (LarsNet CC BY-NC / fpcalc LGPL / install scripts — all consistent).

---

## Part 6 — webui docs (README + CHANGELOG)

- **[STALE] `webui/README.md:86,94,99`** ✅ — sidebar documented as "Track / Claude / Lyrics" with a
  "Claude" section header and "Claude tab"; code ships **Track / Lyrics / Assistant** (id stays
  `claude`, label is "Assistant" — `tabbed-sidebar.js:31-33`, commit `3e50218`). Fix order + rename to
  "Assistant"; note the id stays `claude` so `localStorage["musiq:activeTab"]` stays valid.
- **[STALE] `webui/CHANGELOG.md`** — newest entry is 2026-05-13; omits the entire post-release body of
  work: v1.0.0/AGPL (`fc51678`, `391ed31`), analyze-workflow polish, configurable grid/drum-lane,
  **Live Input on the Lyrics tab** (`7b5ef51`), tab-strip pinning, scrollbar contrast, WASAPI stub
  removal, Unicode key parsers. The **live-mic layer is entirely undocumented in both README and
  CHANGELOG** despite being a headline feature in root README/AGENTS. Fix: add a v1.0.0/dated entry +
  a README feature section for the mic overlay.
- **[STALE] `webui/CHANGELOG.md:40`** ✅ — documents `POST /api/track/<slug>/chat/stop`; real route is
  `POST /api/chat/{slug}/stop` (`server.py:974`; client `api.js:146`). Fix the path.
- **[MINOR] `webui/README.md:62-66`** — presents `python -m webui --reload` as the Develop workflow;
  `__main__.py:70-79` force-disables `--reload` on Windows (ProactorEventLoop requirement). Note it.
- **[MINOR] `webui/README.md:151`** — calls "Classic Dark (default)"; `DEFAULT_PRESET_ID="jinn"` now
  (commit `1e7769c`). Preset *list* is correct; just the "(default)" tag is stale.
- **[COHERENCE]** README omits the Python version (3.13) that root README + AGENTS state; test-command
  forms diverge from AGENTS (`..\webui\tests-js` vs `cd webui && node --test tests-js/`). Both work.
- **Clean:** port 8765, `python -m webui` entry (no `main.py` referenced here — the AGENTS diagram
  error does *not* recur), lifecycle verbs, venv setup, WASAPI 3-mode description + `/api/audio/control`,
  5 theme presets, notation (two systems), identify trust-signal, `stage_manifest`.

---

## Part 7 — Memory bank

**Bijection (MEMORY.md ↔ 43 files): perfect.** No orphan files, no dangling index entries, no
duplicate index lines. Counts reconcile exactly.

**Per-symbol staleness: ZERO stale.** Every concrete code symbol named across all 43 memories was
verified to still exist where claimed — including the recently-edited `theory.py` enharmonic constants,
the `grid-` token-store allow-list fix (`theme/store.js:11`), `DEFAULT_PRESET_ID="jinn"`, the four mic
colour tokens with `--mic-accent` fully retired, and all WASAPI/soxr/security/identify symbols.

**Cleanup (consolidation, not correction):**
- **[SUPERSEDED] `mic_overlay_neutral_token`** — now a strict subset of `mic_overlay_color_buckets`
  (both 2026-05-23; the buckets memory reflects the final 4-bucket scheme + full `--mic-accent`
  retirement). Recommend retiring the neutral-token memory.
- **[DUPLICATE] `feedback_surgical_changes_no_tests` + `feedback_lighter_process_simple_ui`** — same
  actionable advice (skip test ceremony for small UI edits; verify in the running app); the newer one
  is slightly broader and already links the older. Consider merging into one.
- **[MINOR] Three hyphenated `[[wiki-links]]`** — `[[ytdlp-env-var-convention]]`, `[[branching-workflow]]`,
  `[[public-release-v1]]` (in `public_release_v1.md` and `ytdlp_env_var_convention.md`) use hyphens
  while the files use underscores. They match the memories' hyphenated `name:` frontmatter, so
  resolution depends on whether the linker is name-based or filename-based. Normalize to underscores
  to be safe.
- **[INFO] `analyze_relative_path_bug`** — its suggested `cli.py` `.resolve()` cleanup was never
  implemented (`cli.py:100` still passes the path unresolved); the "always pass absolute" advice
  remains valid. Not stale.

---

## Prioritized fix list

**Tier 1 — correctness / has teeth**
1. X1 gorillaz cache path: junction `cache/gorillaz_silent_running` → long-slug dir (un-skips the
   integration test + fixes 5 doc refs at once).
2. `prompts/fix-key-scale-enharmonic-coherence.md`: SHIPPED banner / archive (prevents reverting the
   enharmonic rule).
3. `webui/CHANGELOG.md`: wrong chat-stop endpoint path (`:40`) + add v1.0.0 / post-2026-05-13 entries
   incl. live-mic layer.
4. `webui/README.md`: sidebar tabs → Track / Lyrics / Assistant; document the live-mic layer.

**Tier 2 — factual drift**
5. `README.md:56` notation Flat/Sharp → two systems.
6. `AGENTS.md:56` AcoustID key location → `ACOUSTID_API_KEY` in `.env`.
7. `AGENTS.md:198` diagram `main.py` → `__main__.py`/`server.py`.
8. `SECURITY.md:17` drop pre-publication wording.
9. `docs/history.md:96,107` `refresh-essentia.sh` → real script.
10. Package count ~131 → ~150 (README, AGENTS, INSTALL); Torch 2.7.0 → 2.7.1 (CLAUDE.md);
    test count ~970 → ~1060 (CLAUDE.md, AGENTS, analyze/README).
11. `analyze/README.md:3` "8-stage" → 13-stage.
12. `INSTALL.md:23` download size 5 GB → 8 GB.

**Tier 3 — coherence / cosmetic**
13. Deferrals roadmap Tier 0 → mark done; fix off-by-one cites.
14. `prompts/next/phase-c` time-signature bullet → "partial".
15. `pipeline-changes-phase-ab.md` drums v3→v4 note; strike reverted `transcription_vocals` snippets.
16. `docs/history.md:600` "Phase K" → unlettered appendix.
17. Memory: retire `mic_overlay_neutral_token`; merge the two feedback_* memories; normalize 3 wiki-links.
18. CLAUDE.md download section: one-line `$MUSIQ_YTDLP_BIN` note.

## Method notes / scope
- Frozen design docs (`docs/superpowers/specs|plans/`, `docs/research/`) and `install-logs/` were
  treated as point-in-time and **not** flagged for design-time content — only for broken links or
  cases where a frozen doc reads as current. They are correctly fenced.
- `<PROJECT_PATH>`/`<maintainer-email>`/etc. placeholders are intentional and were not flagged.
- SCHEMA_VERSION is per-stage (identify=5, drums=4, beats=2, others=1); "SCHEMA=5" in CLAUDE.md is
  correctly scoped to the identify stage.

---

## Remediation applied — 2026-06-13

All tiers (1–3 + memory) were applied the same day. Summary of changes:

**Tier 1**
- Created junction `cache/gorillaz_silent_running` → the long-slug dir (un-skips
  `tests/integration/test_gorillaz.py`; resolves all short-slug doc/runbook refs locally).
- `prompts/fix-key-scale-enharmonic-coherence.md`: added a "✅ SHIPPED / rule superseded" banner.
- `webui/CHANGELOG.md`: fixed the chat-stop endpoint path; added a "1.0.0 and later" roll-up entry
  (public release, live-mic layer, sidebar/theme polish, analyze-workflow polish).
- `webui/README.md`: sidebar tabs → Track / Lyrics / Assistant; added a "Live input" section.

**Tier 2**
- `README.md`: notation Flat/Sharp → two systems; package count → ~150.
- `AGENTS.md`: AcoustID key → `ACOUSTID_API_KEY` in `.env`; diagram `main.py` → `__main__.py`/`server.py`;
  test count → ~1060; package count → ~150.
- `SECURITY.md`: dropped pre-publication wording.
- `INSTALL.md`: download size 5 GB → 8 GB; package count → ~150.
- `CLAUDE.md`: Torch 2.7.0 → 2.7.1; test count → ~1060; added a `$MUSIQ_YTDLP_BIN` reconciliation note.
- `docs/history.md`: `refresh-essentia.sh` → "one-off sweep script, never checked in".
- `analyze/README.md`: "8-stage" → 13-stage; test counts; added `--no-essentia`.

**Tier 3 (coherence/cosmetic)**
- Deferrals roadmap: Tier 0 marked ✅ done; off-by-one line cites (`summary_writer.py:138`→139);
  removed the non-persisted companion-audit reference.
- `prompts/next/phase-c-structural-layer.md`: time-signature deliverable marked ✅ partially shipped.
- `docs/pipeline-changes-phase-ab.md`: drums v3→v4 note; struck reverted `transcription_vocals` lines.
- `docs/history.md`: "## Phase K — Memory anchors" → "## Appendix — Memory anchors".

**Memory**
- Retired `mic_overlay_neutral_token` (subsumed by `mic_overlay_color_buckets`); redirected its 3 inbound
  links (buckets memory, `mic_ring_gate_isplaying`, the live-mic spec).
- Merged `feedback_lighter_process_simple_ui` into `feedback_surgical_changes_no_tests` (kept the slug so
  AGENTS.md/CLAUDE.md/roadmap/spec links stay valid); redirected the roadmap reference.
- Normalized 3 hyphenated `[[wiki-links]]` to underscore form.
- Updated `MEMORY.md` index. Final state: 41 files = 41 index lines, zero dangling/hyphenated links.

**Left intentionally unchanged:** the webui README vs AGENTS test-command form divergence
(`node --test` from project-root vs `cd webui`) — the README notes its test files use project-root-relative
paths, so "run from project root" may be load-bearing; changing it risks a real breakage. Flagged, not edited.
