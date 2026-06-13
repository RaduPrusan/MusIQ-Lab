# Deferrals & Placeholders — Remediation Roadmap

> **For agentic workers:** This is a **triage roadmap**, not a single executable plan. Tier 0 and Tier 1 are fully executable here (checkbox steps with exact edits). Tier 2 items are independent subsystems that each get their own `superpowers:brainstorming` → spec (most already exist) → `superpowers:writing-plans` → execute cycle — do **not** inline-implement them from this file. Tier 3 items are decisions, not code.

**Goal:** Sequence remediation of every deferral/placeholder found in the 2026-06-13 audit, from trivial comment-rot to multi-week features.

**Architecture:** Items are triaged by effort × risk × dependency. Cheap/concrete work (stale comments) is done immediately and surgically; large work is routed to its existing spec; externally-blocked or architecturally-hard work is surfaced for an explicit keep/defer/close decision rather than pretend-planned.

**Tech Stack:** webui (vanilla JS ES modules, FastAPI), analyze (Python 3.11, Torch 2.7, librosa/madmom/Essentia), WSL2.

---

## Source audit

Findings from the 2026-06-13 assessment. (No separate companion audit file was persisted; the findings live inline in this roadmap.)

- Python source is clean of `TODO`/`FIXME`/`NotImplementedError`.
- Genuine deferrals live in `provenance.warnings`, design specs, and `prompts/next/`.
- One class of **misleading** placeholder exists: WASAPI frontend comments describing a Phase-1/2 stub state the code has outgrown.

---

## Tier 0 — ✅ DONE: stale WASAPI comment-rot (landed in commit `34e64d9`)

**✅ Status (2026-06-13): applied.** The three WASAPI frontend files no longer contain any `Phase 1`/`stub` comment-rot (verified by grep); the prescribed edits below are complete. Kept for the record.

**Why first:** Pure comment edits, zero runtime change, highest misleading-per-byte. The WASAPI engine shipped through Phase 5 (verified: `wasapi-engine.js` load/play/seek/stems/loops/fallback all implemented; `menus.js:116/126` calls the live rebuild; `device-picker.js` is wired) but three files still claim it's a stub. Per the repo's `feedback_surgical_changes_no_tests` convention, **no test pass required** — restart webui and eyeball Settings → Audio engine.

### Task 0.1: Fix `engine-factory.js` "Phase 1 stub" comment

**Files:**
- Modify: `webui/static/js/audio/engine-factory.js:5` and `:34-43`

- [ ] **Step 1:** Replace the file-header phase label. Change line 5:

```
 * Phase 2 contract: WebAudio is the default; WASAPI is selected via the
```
to:
```
 * Engine-swap contract: WebAudio is the default; WASAPI is selected via the
```

- [ ] **Step 2:** Replace the false body comment inside `createAudioEngine()` (lines 35-39):

```js
  // Default: WebAudio. If the user has explicitly flipped the radio to
  // WASAPI, return WasapiEngine — but note that in Phase 1 every playback
  // method on WasapiEngine throws, so callers that try to load() / play()
  // will surface the "Phase 1 stub" error. The Settings UI is responsible
  // for warning the user when they make this selection.
```
with:
```js
  // Default: WebAudio. If the user has flipped the Settings radio to WASAPI,
  // return a fully-functional WasapiEngine (source + stems playback, loops,
  // and the MME / Shared / Exclusive device fallback chain). If no device has
  // been chosen yet, WasapiEngine.load() emits "sourceFailed" instead of
  // throwing, so the page mounts cleanly and the Settings device-picker can
  // drive a rebuild once a device is selected.
```

### Task 0.2: Fix `menus.js` "Phase 1 device-picker stub" docstring

**Files:**
- Modify: `webui/static/js/ui/menus.js:61-68`

- [ ] **Step 1:** Replace the `buildEngineRadioGroup` docstring:

```js
/**
 * Settings → Audio engine radio group + Phase 1 device-picker stub.
 *
 * Returns an array of DOM nodes appended below the "Audio engine" heading.
 * Switching to WASAPI inserts the device picker; switching back to WebAudio
 * removes it. **Phase 1 does NOT swap the currently-running engine
 * instance** — that's Phase 2's job; the radio just persists the choice for
 * the next page load and surfaces a "pending implementation" hint.
 */
```
with:
```js
/**
 * Settings → Audio engine radio group + WASAPI device picker.
 *
 * Returns an array of DOM nodes appended below the "Audio engine" heading.
 * Switching to WASAPI inserts the device picker; switching back to WebAudio
 * removes it. Either radio change persists the choice to
 * localStorage["musiq.audio"] and calls window.__musiqEngineRebuild() (see
 * main.js) to swap the live engine mid-session — no page reload required.
 */
```

### Task 0.3: Fix `wasapi-engine.js` stub claims in class JSDoc + loop comment

**Files:**
- Modify: `webui/static/js/audio/wasapi-engine.js:12-14` and `:72`

- [ ] **Step 1:** Replace the class-JSDoc "source mode only / methods throw" paragraph (lines 12-14):

```js
 * Phase 2 is **source mode only**. Stem mute/solo/volume methods throw a
 * NOT_YET error; Phase 3 wires them through. setLoop()/clearLoop() are
 * recorded locally but are no-ops server-side in Phase 2 (Phase 5).
```
with:
```js
 * Full playback surface: source mode, stems mix (per-stem mute/solo/volume
 * shipped as fire-and-forget WS ops), and server-side loop wrap. Local state
 * mirrors keep optimistic UI reads in lockstep with the authoritative server
 * mix.
```

- [ ] **Step 2:** Replace the loop-region mirror comment (line 72):

```js
    // Loop region — Phase 5 ships server-side wrap; Phase 2 just records.
```
with:
```js
    // Loop region — setLoop()/clearLoop() send the wrap server-side; these
    // local mirrors keep transport.js loop-band rendering in sync.
```

- [ ] **Step 3 (optional polish):** The `// Phase 3:` prefixes at `wasapi-engine.js:397` and `:451` describe shipped behavior accurately; drop the `Phase 3:` label if you want consistency, but this is cosmetic.

### Task 0.4: Verify + commit

- [ ] **Step 1:** Restart webui — `webui/webui.ps1 restart`
- [ ] **Step 2:** Open `http://127.0.0.1:8765`, go to Settings → Audio engine, flip to WASAPI, confirm the device picker appears and playback works (this is what the old comments said was impossible).
- [ ] **Step 3:** Commit:

```bash
git add webui/static/js/audio/engine-factory.js webui/static/js/ui/menus.js webui/static/js/audio/wasapi-engine.js
git commit -m "docs(webui): drop stale Phase-1 stub comments from shipped WASAPI engine"
```

---

## Tier 1 — Small, concrete, single-owner fixes

### Task 1.1: Key/scale enharmonic coherence (`D#:major` vs `Eb:major`)

**Status:** Prompt already filed at `prompts/fix-key-scale-enharmonic-coherence.md` (commit `fb39a1f`); "queued, not yet executed."

**Problem:** librosa K-S fallback emits sharp spellings (`D#:major`) while the chord stage emits flats (`Eb:major`); webui notation switch can't fully reconcile because the backend disagreement is upstream.

- [ ] **Step 1:** Read `prompts/fix-key-scale-enharmonic-coherence.md` end-to-end.
- [ ] **Step 2:** Invoke `superpowers:brainstorming` to confirm the desired resolution (does the chord stage's flat/sharp choice become authoritative for the key spelling, or vice versa?).
- [ ] **Step 3:** Invoke `superpowers:writing-plans` → produce `docs/superpowers/plans/2026-06-13-key-scale-enharmonic-coherence.md` with TDD steps. Likely touch points: `analyze/stages/` key stage + `analyze/derived/theory.py`.
- [ ] **Step 4:** Execute; re-run analyze on a known offender; confirm `summary.json` key spelling matches chord spelling.

**Effort:** ~half a day. Self-contained backend fix.

### Task 1.2: Per-preset drum/typography token tuning (optional)

**Status:** All 5 theme presets ship identical drum-substem + typography token defaults; `webui/CHANGELOG.md:91,125` note per-preset tuning was "deferred until requested."

- [ ] **Step 1:** Confirm with the user this is actually wanted — it's a "future polish pass," not a defect. If not requested, **close as YAGNI** and remove from backlog.
- [ ] **Step 2 (if wanted):** Treat as a `feedback_surgical_changes_no_tests` token-tuning pass — adjust the 5 `drum-*` + 4 typography tokens per preset in `theme/store.js` preset maps, verify against `theme_audit_2026_05_24` contrast rules in the live customizer. No unit tests.

**Effort:** ~2 hours if pursued.

---

## Tier 2 — Specced features (each is its own brainstorm → plan → execute cycle)

These are **not** to be inline-implemented from this roadmap. Each already has a design spec and/or `prompts/next/` prompt. The "step" for each is the full superpowers cycle. Listed in recommended dependency order.

### 2.1 Phase C — Structural layer (sections) ★ largest open gap

- **Deferral:** `analyze/pipeline.py:539` + `analyze/writers/summary_writer.py:139` hardcode `sections: []` and emit `"sections deferred — no segmenter installed"` in every `summary.json`. allin1 dropped (NATTEN ABI).
- **Inputs:** spec/prompt `prompts/next/phase-c-structural-layer.md`; candidate ranking `docs/research/tasks/07-section-analysis.md` (librosa recurrence → MSAF → revived allin1 → SongFormer); research `docs/research/codex/section-detection-methods.md`.
- **First decision (brainstorm):** pick the segmenter. `07-section-analysis.md` says SongFormer-class models aren't yet pip-installable; the pragmatic v1 is likely librosa recurrence/MSAF. Do **not** try to revive allin1 (reopens the dependency rabbit hole — see `docs/history.md`).
- **Unblocks:** Roman-numeral analysis gains section context (`analyze/derived/theory.py`); Phase D confidence; the webui "sections" warning disappears.
- **Effort:** ~2 weeks (per `prompts/next/README.md`).

### 2.2 Phase A/B — Specialist F0→notes vocal transcriber

- **Deferral:** vocals routed through basic-pitch; a proper F0→notes specialist (crepe-notes / pyin note transcription) is a "Phase A+B follow-up." Router architecture (`TRANSCRIBERS["vocals"] = "basic"`) makes the swap ~50 lines.
- **Inputs:** `prompts/next/phase-a-specialist-models.md`, `prompts/next/phase-b-pipeline-architecture.md`, `docs/pipeline-changes-phase-ab.md`.
- **Note:** Phase A/B pipeline-architecture upgrade already largely landed; confirm what remains before planning. This task is specifically the vocal transcriber swap.
- **Effort:** ~2-3 days (model integration + validation on the vocal corpus).

### 2.3 Phase D — Confidence signals

- **Deferral:** FCPE+PESTO agreement is *computed* but "not yet routed to confidence" (`prompts/next/phase-d-confidence-signals.md`).
- **Depends on:** cleanest after Phase C (section-level confidence) but can start independently for the per-frame/per-stage signals.
- **Effort:** ~1 week.

### 2.4 Phase G — Web-research metadata agreement

- **Deferral:** design spec `docs/superpowers/specs/2026-05-09-phase-g-web-research-agreement.md`; "item #7 of the eight-item post-Phase-M plan," not implemented. Six open questions in §13 need user resolution before G.1.
- **Note:** the identify pipeline (AcoustID/MB) already shipped (SCHEMA=5); confirm overlap before planning so G doesn't duplicate identify.
- **Effort:** spec estimates phased G.1–G.5.

### 2.5 Phase F — Exports

- **Deferral:** `prompts/next/phase-f-exports.md`. Stem re-mastering/normalization explicitly out of scope.
- **Effort:** scoped in prompt.

**Recommended sequence:** C → (A/B vocal specialist, parallel-ok) → D → G → F.

---

## Tier 3 — Blocked or decision-required (surface, don't pretend-plan)

For each, the action is a **decision** (keep / formally-defer / close-as-wontfix), not implementation.

**Decisions recorded 2026-06-13** (user-confirmed; ✅ = resolved):

| Item | Where | Blocker | Decision (2026-06-13) |
|------|-------|---------|------------------------|
| **Essentia high-level** (danceability/mood/voice_instrumental → `{available:false}`) | `essentia_gaia2_gotcha` memory | PyPI Essentia built without `gaia2`; needs Qt5+swig C++ rebuild `--with-gaia`. C++/runtime, not Python. | ✅ **Deferred — documented as a known environment limitation.** Low-level path (tempo/key/loudness) works; removed from active backlog. Revisit only if a gaia-enabled wheel appears. |
| **Rec 4 — HNR voicing** (Cohen t=107.7s canary: 349 Hz vs true 87 Hz) | `docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md` §7 | Architecturally unfixable in Viterbi alone — every estimator locks above the fundamental. | ✅ **Deferred — re-evaluation gated on Task 2.2** (Phase A/B vocal F0→notes specialist). A better transcriber may moot the canary; decide then with better inputs. |
| **JAMS `beat_position`** (position-in-bar 1/2/3/4) | `docs/superpowers/plans/2026-04-29-analyze-py.md:3849` | madmom downbeat-position plumbing; downbeat list already carries adjacent info. | ✅ **Deferred to v1.x** (default). Schema-extension recorded; promote only if a JAMS consumer needs it. |
| **`claude_orchestrator`** LLM-corrected chord track | `docs/superpowers/specs/2026-04-29-analyze-py-design.md` | Deferred to v2 at design time. | ✅ **Kept as planned v2** — stays a tracked future deferral (not promoted to Tier 2 yet). Gets its own spec when scheduled. |
| **ASIO audio backend** | `docs/superpowers/specs/2026-04-30-webui-design.md` | Seam preserved; WASAPI shipped instead and covers the need. | ✅ **Closed.** WASAPI Exclusive covers the low-latency motivation. The `AudioEngine` seam is retained (free), but ASIO is removed from the deferred backlog. |
| **Identify manual-override tier** (user types artist/title) | `docs/superpowers/identify-overhaul/round-5-delta.md` | Round 6+ scope; needs UI + write path + `source:"manual"`. | ✅ **Deferred (Round 6+)** (default). Small but independent; promote to Tier 2 on request. |

---

## Execution order summary

1. ✅ **Tier 0** (comment-rot) — done (commit `34e64d9`).
2. **Tier 1.1** (enharmonic) — its own short plan; **1.2** only if user confirms.
3. ✅ **Tier 3 decisions — done 2026-06-13.** ASIO closed; Essentia documented as a limitation; Rec 4 re-eval gated on Task 2.2; `claude_orchestrator` kept as a tracked v2; `beat_position` → v1.x; identify-override → Round 6+. See the Tier 3 table.
4. **Tier 2** — sequence C → A/B → D → G → F, each as a full superpowers cycle.

---

## Self-review

- **Coverage:** every audit finding maps to a tier (Tier 0: 3 comment files; Tier 1: enharmonic, token-tuning; Tier 2: sections/Phase C, F0-specialist/A-B, confidence/D, web-research/G, exports/F; Tier 3: Essentia, Rec 4, beat_position, claude_orchestrator, ASIO, identify-override). ✅
- **Placeholders:** Tier 0/1 steps carry exact before/after text and paths. Tier 2/3 deliberately route to existing specs rather than fabricate micro-steps for un-designed multi-week work — this is the skill's Scope-Check guidance, not a placeholder. ✅
- **Path consistency:** all referenced files verified to exist (`prompts/next/phase-{a,b,c,d,e,f}.md`, `prompts/fix-key-scale-enharmonic-coherence.md`, the three WASAPI JS files, `analyze/pipeline.py:539`, `analyze/writers/summary_writer.py:139`). ✅
