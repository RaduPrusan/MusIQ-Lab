# webui — Beautify & Polish Session (Design)

**Date:** 2026-05-02
**Scope:** half-day session, ~10-15 items fixed, editorial / data-rich aesthetic direction
**Method:** Playwright-driven audit + token-foundation refactor + fix passes
**Server:** `127.0.0.1:8765` (already running locally)
**Test fixture:** Gorillaz - Silent Running ft. Adeleye Omotayo (already cached, used by `tests-e2e/`)

## Goal

Take the webui from "functional and tasteful" to "deliberate and refined." The session covers three concerns at once: visual bug-hunt (alignment, contrast, overflow), small information-architecture tweaks (regrouping/reordering sidebar sections, condensing where overweight), and aesthetic refinement (typography hierarchy, spacing rhythm, hover/idle/empty states, motion).

The aesthetic target is **editorial / data-rich**: lean into the music-IQ angle by treating the sidebar like a magazine sidebar of facts. Real heading hierarchy, three deliberate type families (sans for prose, mono for data, serif for Roman numerals + display), tight rhythm. Less generic-DAW, more "dense informational interface that respects the reader."

Nothing is off-limits — including the canvas renderer in `static/js/render/` if a glitch lives there. In practice we expect 80%+ of changes to land in CSS.

## Architecture

Three sequential phases, each with a clear handoff and commit boundary:

| Phase | Output | Commit boundary |
|---|---|---|
| **0. Foundation** | New `webui/static/css/tokens.css` + refactor of existing CSS to reference tokens. No visible redesign — before/after screenshots near pixel-identical. | `refactor(webui): typography + spacing token layer` |
| **1. Audit** | `tests/screenshots/polish-audit/` directory + `docs/superpowers/notes/2026-05-02-webui-audit.md` listing each finding with screenshot ref + severity + category. Triaged with user before fixes start. | `docs(webui): polish audit findings` |
| **2. Fix passes** | 3-5 cohesive area-scoped commits, each with before/after screenshots in `tests/screenshots/polish-after/`. | Per-batch commits |

The Playwright loop runs in phase 1 (audit) and after every fix batch in phase 2 (verification). Phase 1 ends at a triage gate — implementation pauses for the user to mark which audit items make the cut.

## Phase 0 — Foundation token layer

**File:** `webui/static/css/tokens.css` (new), loaded *before* `theme.css` in `index.html`.

**Token set — capped at 16 variables** (3 fonts + 4 sizes + 1 letter-spacing + 5 spacings + 3 elevations). Anything beyond this is over-engineering for a 220-line CSS codebase.

```css
:root {
  /* Type families — editorial means distinct roles, not one sans for everything */
  --font-sans:    ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono:    ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  --font-numeral: ui-serif, Georgia, "Iowan Old Style", serif;

  /* Type scale — 4 sizes is the floor for hierarchy */
  --t-micro:    10px;
  --t-body:     11px;
  --t-prose:    13px;
  --t-display:  24px;

  /* Caps treatment */
  --ls-caps:    0.07em;

  /* Spacing — base 4 */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;

  /* Elevation */
  --el-1: 0 1px 0 rgba(0,0,0,0.4);
  --el-2: 0 4px 12px rgba(0,0,0,0.5);
  --el-3: 0 12px 32px rgba(0,0,0,0.6);
}
```

**Refactor pass in same commit:**

- Sweep `webui/static/css/track.css` and any inline styles in `webui/static/js/`, replace literal values with token references.
- Replace 3 ad-hoc font-stacks with `var(--font-*)` (mono → `--font-mono`, Georgia → `--font-numeral`, default sans → `--font-sans`).
- Replace inline `9px..14px` font-sizes with the closest token (most map cleanly; near-misses get logged in the audit, not papered over).
- Replace inline `box-shadow` literals with `var(--el-*)`.
- Spacing replacements: only the obvious ones (panel padding, section gaps). Don't churn every margin.

**What we explicitly do NOT do here:**

- Don't change visible appearance — a screenshot diff before/after this commit should be near pixel-identical.
- Don't add new colors. Existing palette in `theme.css` stays.
- Don't touch canvas-side rendering values.

If after the audit we discover we need a 5th size, a 6th spacing stop, or new elevation — we add it then, surgically. Tokens grow in response to demand, not speculation.

## Phase 1 — Audit sweep

**Tooling:** Playwright via the MCP browser tools (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`, `browser_click`, `browser_evaluate`, `browser_resize`). Drive a live session against `http://127.0.0.1:8765`. The existing `tests-e2e/` Playwright suite stays as-is and is run only as regression at session end — we don't fold the audit into it.

**Captures:** Screenshots saved into `tests/screenshots/polish-audit/NN-<slug>.png`. Numbered so audit-doc references stay stable. Captured at **two viewport sizes**: 1600×1000 (default) and 1280×800 (the lower edge — `tests/screenshots/audit-11-1280-noflow.png` exists already, indicating this resolution matters).

**Flows walked:**

| # | Flow | What we look at |
|---|---|---|
| 1 | Empty state | First load with no track selected (if reachable) — does it look intentional or limp? |
| 2 | Track loaded, idle | Gorillaz fixture loaded, t=0, no playback. Topbar, sidebar sections, transport. |
| 3 | Track playing | Press Space, playhead mid-track. Now-playing card filled, auto-scroll badge live. |
| 4 | Hover states | Hover canvas (pitch tooltip + row highlight), sidebar rows, track-picker rows, topbar menu items, transport buttons. |
| 5 | Mute / solo | Click M and S on a stem, verify visual states. |
| 6 | Track picker open | Open picker, search filter, scroll, hover rows. |
| 7 | Modals | Open Settings, Tools, Shortcuts (`?`), Reanalyze modal (start, don't actually reanalyze). |
| 8 | Toasts | Trigger an error toast (load a bad URL or similar). |
| 9 | Suppressed/missing stems | Find a track with these states; if Gorillaz has none, document. |
| 10 | Narrow viewport (1280×800) | Repeat 2-3 at narrow size, check overflow + layout breaks. |

**Finding format** (entries in `docs/superpowers/notes/2026-05-02-webui-audit.md`):

```
- [ ] [P1|P2|P3] [bug|refine|ia] short title — screenshot 04-hover-row-misalign.png
  notes: row highlight is 1px below the gutter row it should pair with
```

Severity:

- **P1** — visibly broken (alignment, contrast failure, overflow, clipping, dead state). Must fix.
- **P2** — noticeable refinement (typography rhythm off, spacing inconsistent, hover lacks feedback). Should fix.
- **P3** — nice-to-have (more deliberate motion, redundant info, cosmetic). Fix if time.

Category:

- **bug** — pre-existing visual defect.
- **refine** — polish opportunity.
- **ia** — layout/grouping change.

**Triage gate:** Before any fix lands, the audit list is posted to the user, who marks which items make the cut. Target ~10-15 items in fix passes — the rest stay as documented future work in the same audit doc. This is the only mid-session pause.

**Done criteria for the audit:** All 10 flows walked, all P1s captured, the 1280 viewport pass done, audit doc committed.

## Phase 2 — Fix passes

**Cadence per batch:** edit CSS/JS → reload at `127.0.0.1:8765` → Playwright screenshot to `tests/screenshots/polish-after/NN-<slug>.png` → compare against the corresponding audit shot → commit.

**Commit shape:** Area-scoped, audit-ID-referenced. Examples:

- `fix(webui): polish topbar density — A2, A5, A8`
- `fix(webui): editorial typography pass on sidebar — A4, A7, A11`
- `feat(webui): empty/idle states for now-playing card — A12, A13`
- `fix(webui): modal alignment and elevation rhythm — A6, A9, A14`
- `refactor(webui): condense shortcuts panel — A15` (an IA tweak)

Target: 4-6 commits across the fix phase. Each commit body lists the audit items resolved and references the before/after screenshot pair. Commits are kept small enough to be reverted independently.

## Testing & regression

Session-end gates — must pass before the final commit:

- Backend: `cd webui && .venv\Scripts\python -m pytest`
- Frontend pure-logic: `node --test webui/tests-js/*.test.js` (run from project root)
- Integration: `cd webui/tests-e2e && npm test` (Playwright e2e against Gorillaz fixture)

No new automated visual-regression tests are added in this session. The before/after screenshot pairs in `tests/screenshots/polish-{audit,after}/` are the durable visual artifact and live in the repo as documentation of the session.

## Out of scope

- Backend changes (`webui/webui/*.py`).
- New product features. Polish only.
- File restructure / renames within `webui/static/`.
- Edits to the existing design spec `docs/superpowers/specs/2026-04-30-webui-design.md`.
- Documentation rewrites beyond the audit note. (`webui/README.md` may receive a one-line pointer to the audit doc.)
- Visual-regression test scaffolding. Screenshots only.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Token refactor introduces regressions where a literal doesn't map cleanly to a token. | Capture a single full-viewport screenshot before and after the foundation commit; visually diff. Any near-miss gets logged in the audit and addressed in fix passes. |
| MCP Playwright session flakiness (lost session, missed screenshot). | Save each shot as soon as captured. Audit doc references files, not in-memory state — resumable from last saved file. |
| Scope creep — 10-15 items balloons to 30. | Triage gate after audit is the firm scope-limiter. Items beyond the cut go to the audit doc as deferred, not to fix passes. |
| Foundation pass over-engineers a 220-line CSS file. | 16-token cap is hard. If we want a 17th, we cut something or wait. |
| Audit happens against an old visual baseline because the foundation refactor changed something subtle. | Foundation commit is required to be visually neutral. If the diff is non-trivial, we treat the diff itself as audit input rather than skipping it. |

## Done criteria

- Foundation commit lands with no visible regression (verified by before/after screenshot pair).
- Audit doc committed at `docs/superpowers/notes/2026-05-02-webui-audit.md` with all P1s captured and triaged.
- At least one fix commit per area we touched. All triaged items either resolved or explicitly deferred in the audit doc.
- All three test suites pass (backend pytest, frontend node:test, e2e Playwright).
- Final summary message to user lists addressed-vs-deferred audit items.

## Decisions worth flagging

- **Aesthetic choice — editorial / data-rich** over "studio glass" or "stay the course." Implies typography hierarchy is the primary lever; chrome (gradients, glass blur) is secondary or absent.
- **Approach — foundation first, then audit, then fix.** Alternative was walk-and-fix area by area (faster to first commit, less coherent result). Foundation-first chosen because editorial aesthetic depends on typographic system, and a system without tokens is just whim.
- **Triage gate is the only mid-session pause.** User opted into autopilot for the rest. Implies the session can otherwise run end-to-end without further questions.
