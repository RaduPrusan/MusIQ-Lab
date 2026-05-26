# UI Polish + Themable Tokens — Ship Report (2026-05-09)

> Spec: [`docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md`](../docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md)
>
> Plan: [`docs/superpowers/plans/2026-05-09-ui-polish-themable-tokens.md`](../docs/superpowers/plans/2026-05-09-ui-polish-themable-tokens.md)

## Summary

- **Iterations to convergence:** 5 (cap was 8). Two consecutive `passed=true` reviewers at iter 4 + iter 5.
- **Final verdict:** `passed=true`, 0 blockers, 0 axe-mechanical findings, 3 minor qualitative notes.
- **Wall time:** ~1 h 53 min (iter 1 starting 20:38 → iter 5 finishing 22:31).
- **Loop cost:** $31.82 USD across 5 iterations × (implementer + reviewer Opus 4.7 dispatches). Well under the $80–100 worst-case estimate; the implementer cost dropped from $9.17 (iter 1) to $1.67 (iter 3) once each iteration's scope narrowed to a single blocker.
- **Tokens added beyond the original spec taxonomy:** ~10 (a `--*-soft-fg` family, `--fn-on`, `--fn-predominant-bg`, `--chord-default-bg`, `--chord-no-bg`, `--drum-lane-bg`, `--surface-selected`, `--alpha-bar-number`). All driven by reviewer findings — no speculative additions.
- **Final state:** 4 presets (Classic Dark, Midnight, Studio Light, High Contrast) all axe-AA clean across the 6 captured scenes (default-load, picker-open, settings-open, vocals-tab, claude-tab, transport-playing); reviewer's free-text confirms presets read as coherent palettes with deliberate type hierarchy.

## Phase outcome

| Phase | Output | Boundary commit |
|---|---|---|
| 1 — Token sweep | `tokens.css` extended; `theme.css` rewritten as Classic Dark application; ~168 literals across CSS + inline JS swept; canvas renderers read tokens via `theme/css-tokens.js` | `8370995` |
| 2 — Theme engine + Settings | 5-module `webui/static/js/theme/` package; localStorage persistence + pre-paint hydration; Settings → Appearance UI with 4 preset cards + customize panel + Copy theme JSON | `28aea6d` |
| 3 — Loop infrastructure | `tests-e2e/visual-review.spec.js` (4 presets × 6 scenes + axe), per-preset verdict files + merge step, two prompt files, `scripts/ui-polish-loop.py` (claude-agent-sdk async runner) | `3753d4e` |
| 4 — Autonomous polish | 5 iterations of `polish(webui): iter N — …` commits to convergence | `8befa24` |

## Loop convergence detail

Each row = one iteration: the implementer's polish commit, the reviewer's findings (committed as the orchestrator's iter-N commit), and what was specifically fixed.

| Iter | Implementer | Reviewer | Issues end-of-iter | Implementer cost | Reviewer cost |
|---|---|---|---|---|---|
| 1 | `3547a32` tokenize remaining literals + per-preset contrast fix | `393b32c` 39 blockers (studio-light canvas + modal stay dark; stem M/S + Now-Playing text invisible; midnight inherits warm `*-soft-bg`; high-contrast indistinguishable from classic-dark; claude-tab tool NDJSON overflows assistant bubble) | **47** | $9.17 | $1.50 |
| 2 | `5f401df` canvas fills + soft-fg family + studio-light contrast (added `hexToRgba` helper, `--*-soft-fg` family, midnight cool-accent overrides, status-warning + text-disabled bumps) | `93b60cc` 1 blocker (studio-light `accent-on=#fff` on `#d97706` transport chip = 3.18:1) | **1** | $10.25 | $1.45 |
| 3 | `d7ff098` studio-light `accent-on=#1a1a25` (WCAG-derived flip), bump `surface-selected`, cool midnight `fn-tonic-bg` | `70177f6` 1 blocker (studio-light claude-tab Send btn: dark text on hot-pink stem chip = 2.93:1) | **3** | $1.68 | $0.95 |
| 4 | `49576cd` Send btn → `--fn-on` (5.89:1), user-bubble lifted to `--surface-3` for visibility | `442d7e4` ✅ axe-clean across all 4 presets × 6 scenes; 2 minor qualitative (studio-light f0 contour low contrast on cream; grid-line ticks recessed) | **2** | $1.67 | $1.15 |
| 5 | `671ac73` tokenize f0 consensus + pesto strokes; per-theme `--alpha-bar-number` for cream-canvas legibility | `8befa24` ✅ all 4 presets × 6 scenes coherent; 3 minor non-blockers (deferred to future polish) | **3** | $2.24 | $1.76 |

## Token audit summary

Phase 1 sweep totals (from `install-logs/ui-polish-2026-05-09-token-audit.md`):

- **Literals replaced** (CSS + inline JS): 47 in `track.css`, 25 across 8 inline-DOM JS files, 15 in canvas renderers — **~87 token-references introduced**, plus ~30 `rgba(…)` modernizations to `rgb(… / var(--alpha-*))`.
- **Literals deliberately KEPT** (logged in audit): 20+ — gutter accent backgrounds, hover-row bgs, destructive warm-red set, badge-specific hex (`.badge.{k,t,s,q}` topbar pills until tokenized in iter 2), the deliberately-distinct `#7eddff` PESTO stroke + `#f0f0f0` consensus stroke (preserved in `f0-overlay.js` until iter 5 tokenized them).
- **Back-compat aliases**: 14 (`--bg-0..3` → `--surface-…`, `--fg-0..3` → `--text-…`, `--c-{stem}` → `--stem-{name}`) added in Task 1.1, removed at end of Phase 1 (Task 1.8).

New tokens added across the 5 loop iterations (beyond the original spec taxonomy):

| Token | Default | Why | Where |
|---|---|---|---|
| `--accent-soft-fg` | preset-specific | text on `--accent-soft-bg` tiles, fixes Studio Light contrast | iter 2 |
| `--success-soft-fg`, `--info-soft-fg`, `--warn-soft-fg`, `--modal-soft-fg` | preset-specific | sibling tokens for the `*-soft-bg` family | iter 2 |
| `--fn-predominant-bg` | new | function-tag bg parity with the other 3 functions | iter 2 |
| `--chord-default-bg`, `--chord-no-bg` | new | tokenize the chord-strip default + no-chord cells | iter 2 |
| `--drum-lane-bg` | new | tokenize drum-lane background (was `#0e0e12` hardcoded) | iter 2 |
| `--surface-selected` | new | tokenize `.tp-row.current` and `.track-row.highlighted` highlight bg | iter 3 |
| `--fn-on` | new | text color when filled with function/accent — distinct from `--accent-on` for cases where the saturated stem chip + dark text would fail (e.g. studio-light hot-pink) | iter 4 |
| `--alpha-bar-number` | preset-specific | per-theme alpha for the function-bar segment number labels — the 0.85 default was illegible on cream canvas | iter 5 |

## Contrast deltas

axe-core findings under `wcag2aa` rules, before vs after the loop:

| Preset | iter-1 axe issues | iter-5 axe issues |
|---|---|---|
| Classic Dark | 0–2 | 0 |
| Midnight | 4–6 | 0 |
| Studio Light | ~30 | 0 |
| High Contrast | 0 | 0 |
| **Total** | ~34 | **0** |

(iter-1 had 47 issues total — 34 axe-mechanical + 13 reviewer qualitative blockers like studio-light's dark canvas bands. The verdict was driven by the qualitative blockers more than axe.)

## Three remaining minor notes (not blockers)

The reviewer's iter-5 verdict has 3 minor qualitative notes that did not gate convergence. They're real polish opportunities for a future session:

1. **midnight / default-load** — Stem swatches in the right sidebar (Vocals pink, Piano warm amber, Other purple) inherit the warm Classic Dark hues via `--stem-*`. Could get a Midnight-specific cool-tinted override pass if we want stems to feel preset-aware rather than canonical.
2. **studio-light / default-load** — Piano-roll stem note fills appear muted on the cream surface; `--alpha-stem-fill` (0.85) was tuned for dark surfaces. A studio-light override (e.g. 0.55–0.65, or a darker stem-color set when surface luminance > threshold) would help.
3. **high-contrast / default-load** — Topbar minimap segments render as solid amber blocks at `--alpha-overlay-strong=0.85`. Louder than the subtler accent on other presets; a slight lightening (or a separate `--alpha-minimap-seg`) would calibrate.

## Reviewer's free-text closing summary (iter 5)

> All 4 presets render coherently across the 6 scenes — typography rhythm is consistent, modal scrim, picker selection, sidebar tabs, transport bar and lyrics list all hold together within each preset. Studio Light passes the 'real working light theme, not a dumping ground' bar. Midnight + High Contrast canvas elements (piano roll, minimap, function bar) inherit theme correctly rather than looking like Classic Dark embedded in another preset. With iter-4 already passing, this is the second consecutive pass — the loop's convergence criterion is satisfied.

## Lessons + surprises

1. **The visual-baseline guardrail (Phase 1) was load-bearing through iter 0 only.** Once Phase 4 started iterating, the `Classic Dark = pixel-baseline` invariant was deliberately broken (canvas literals tokenized, alphas re-derived from preset). The guardrail's purpose was the SWEEP gate, not a permanent test. We should retire the spec or refresh its baselines if we want it as a regression net for future visual edits.
2. **Cost dropped a 6× between iter 1 and iter 3.** Iter 1's implementer had 47 issues to chew through plus broad scope. Iters 3–5 each had a single blocker and ran in 5 minutes. *Lesson:* the loop pays for itself most efficiently when each iteration has a narrow target — front-load broad work in a manual pass before dispatching, or accept a fat first iteration and let the subsequent ones be cheap.
3. **The reviewer caught what axe-mechanical missed.** Iter 1's reviewer found canvas-side issues (drum-lane stays dark in studio-light, FN_BG warm-tinted in midnight) that no contrast scanner would flag — these were *visual* failures of the theme system, not accessibility violations. Without an LLM reviewer reading the screenshots, the loop would have terminated at axe-clean (iter 2 or 3) with broken-looking presets.
4. **Worker-isolation gotcha.** Initial visual-review.spec wrote a single `verdict.json` from a module-level mutable buffer; Playwright's parallel worker model meant only one preset's data persisted. Caught at smoke time, fixed via per-preset intermediate files + `merge-verdicts.js`. *Lesson:* any shared output file from a parallel test runner needs a per-worker write + post-merge step.
5. **A spec bug in `resetTokens` was caught by TDD.** The spec said `resetTokens` falls back to `DEFAULT_PRESET_ID` if preset is "custom"; the test (also in the spec) required restoring whichever preset was active before going custom. The implementer (Task 2.2) noticed the contradiction, added a `_basePreset` field, fixed both. *Lesson:* mature TDD catches spec bugs as well as implementation bugs; trust the test, fix the spec.
6. **Convergence-twice-in-a-row was right.** Iter 4 was the first clean pass; iter 5 confirmed. Iter 5's implementer also addressed iter-4's deferred minors (f0 strokes, alpha-bar-number) — work the loop wouldn't have done with single-pass convergence. The "two in a row" gate is cheap insurance against a single-pass fluke.
7. **The 8-iteration cap was conservative.** With 5 iterations to converge, we used ~60 % of the budget. For similar future loops, cap=6 would be sufficient with the same narrowing-scope dynamic.

## Final commit chain (this session)

42 commits from `cd1a016` (Task 1.1, tokens.css extension) through `8befa24` (iter-5 convergence). Highlights:

```
8befa24 polish(webui): iter 5 — iter-5 qualitative review clean ... convergence reached
671ac73 polish(webui): iter 5 — tokenize f0 consensus + pesto strokes; per-theme alpha-bar-number
442d7e4 polish(webui): iter 4 — iter 4 clean — axe 0 violations across 4 presets × 6 scenes
49576cd polish(webui): iter 4 — fix studio-light claude-tab blocker (composer Send: --accent-on→--fn-on)
70177f6 polish(webui): iter 3 — studio-light claude-tab: --accent-on (#1a1a25) on --stem-vocals fails
d7ff098 polish(webui): iter 3 — studio-light accent-on=#1a1a25 (WCAG-derived), cool midnight fn-tonic-bg
93b60cc polish(webui): iter 2 — studio-light accent-on=#fff fails WCAG on #d97706 (3.18:1 transport chip)
5f401df polish(webui): iter 2 — tokenize canvas fills, soft-fg family, fix studio-light contrast
393b32c polish(webui): iter 1 — studio-light: canvas bands+modal stay dark, stem M/S + Now-Playing invisible
3547a32 polish(webui): iter 1 — tokenize remaining literals + per-preset contrast fix
3753d4e fix(scripts): use claude-opus-4-7 (latest) for ralph loop subagents
5470f56 feat(scripts): ui-polish-loop runner — implementer + reviewer subagents
b6dc30d test(webui): visual-review spec — 4 presets × 6 scenes + axe-core verdict
af20da3 feat(webui): Settings → Appearance — presets + per-token customize
8370995 refactor(webui): drop Phase 1 token aliases — sweep complete
cd1a016 refactor(webui): extend tokens.css to full design-token surface
```

## Artifacts

- 24 final screenshots: `webui/tests-e2e/visual-review/<preset>/<scene>.png` (4 presets × 6 scenes; gitignored)
- Final verdict: `webui/tests-e2e/visual-review/verdict.json` (passed=true, 3 minor)
- axe findings: `webui/tests-e2e/visual-review/axe.json` (empty array — clean)
- Per-iter logs: `install-logs/ui-polish-2026-05-09-iter-{1..5}.md`
- Token audit: `install-logs/ui-polish-2026-05-09-token-audit.md`
