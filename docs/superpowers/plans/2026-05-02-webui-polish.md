# webui Polish Session Implementation Plan

> **Status: SHIPPED 2026-05-02** — Phase 0 (CSS token foundation) landed via `c510847 refactor(webui): typography + spacing token layer`; Phase 1 (audit sweep) landed via `f201ff3 docs(webui): polish audit findings` plus the audit doc at `docs/superpowers/notes/2026-05-02-webui-audit.md`. Phase 2 (the actual fixes that the audit triaged) is a separate plan: `2026-05-02-webui-polish-fixes.md`. **Plan body retained as historical narrative.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Phase 0 (token foundation) and Phase 1 (audit sweep + triage) of the webui polish session. Phase 2 (fix passes) is planned in a follow-up plan written after the triage gate, since fix tasks depend on what the audit finds.

**Architecture:** Three sequential phases. Phase 0 introduces a CSS token layer (`webui/static/css/tokens.css`, 16 named vars) and refactors existing literals to reference it — no visible change. Phase 1 drives Playwright via the MCP browser tools through 10 flows + a narrow-viewport pass, capturing screenshots into `tests/screenshots/polish-audit/` and findings into `docs/superpowers/notes/2026-05-02-webui-audit.md`. Phase 1 ends at a triage gate where the user marks which findings make the Phase 2 cut.

**Tech Stack:** Vanilla JS modules + hand-authored CSS (no framework). Server: FastAPI on `127.0.0.1:8765` (already running, managed by `webui/webui.ps1`). Browser automation: Playwright MCP tools (`browser_navigate`, `browser_take_screenshot`, `browser_click`, `browser_evaluate`, `browser_resize`, `browser_press_key`). Tests: pytest (backend), node:test (frontend), Playwright e2e (`webui/tests-e2e/`).

**Spec:** `docs/superpowers/specs/2026-05-02-webui-polish-design.md`

---

## File map

**Create:**
- `webui/static/css/tokens.css`
- `tests/screenshots/polish-audit/` (directory) and PNGs within
- `docs/superpowers/notes/2026-05-02-webui-audit.md`

**Modify:**
- `webui/static/index.html` — link `tokens.css` before `theme.css`
- `webui/static/css/track.css` — replace literals with token references

**Out of scope (Phase 2, planned later):**
- `tests/screenshots/polish-after/`
- Any actual fix commits

---

# Phase 0 — Foundation token layer

Outcome: one commit (`refactor(webui): typography + spacing token layer`) that introduces `tokens.css` and refactors `track.css` to reference it, with no visible change verified via screenshot diff.

## Task 1: Verify webui server is up

**Files:** none (status check)

- [ ] **Step 1: Check server status**

```powershell
cd "<PROJECT_PATH>/webui"
.\webui.ps1 status
```

Expected: `port 8765   LISTENING` and `api OK (http://127.0.0.1:8765/api/tracks)`. If not listening, run `.\webui.ps1 start` and re-check.

## Task 2: Capture baseline screenshot

**Files:**
- Create: `tests/screenshots/polish-audit/00-baseline-pre-tokens.png`

- [ ] **Step 1: Create the screenshot directory**

```powershell
New-Item -ItemType Directory -Force -Path "<PROJECT_PATH>/tests/screenshots/polish-audit" | Out-Null
```

- [ ] **Step 2: Open the webui in Playwright at standard audit viewport**

Call `mcp__plugin_playwright_playwright__browser_resize` with `{width: 1600, height: 1000}`, then `mcp__plugin_playwright_playwright__browser_navigate` with `{url: "http://127.0.0.1:8765"}`. Wait for the Gorillaz fixture to render (the topbar should show `Gorillaz - Silent Running ft. Adeleye Omotayo` with `F minor`, `107.1 BPM`, `F natural minor · 4/4` badges).

- [ ] **Step 3: Take baseline screenshot**

Call `mcp__plugin_playwright_playwright__browser_take_screenshot` with `{filename: "<PROJECT_PATH>/tests/screenshots/polish-audit/00-baseline-pre-tokens.png", fullPage: false, type: "png"}`. Confirm the file exists.

## Task 3: Create tokens.css

**Files:**
- Create: `webui/static/css/tokens.css`

- [ ] **Step 1: Write the file**

```css
/* tokens.css — typography + spacing + elevation token layer.
   Loaded BEFORE theme.css so existing color tokens cascade unchanged. */

:root {
  --font-sans:    ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono:    ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  --font-numeral: ui-serif, Georgia, "Iowan Old Style", serif;

  --t-micro:    10px;
  --t-body:     11px;
  --t-prose:    13px;
  --t-display:  24px;

  --ls-caps:    0.07em;

  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;

  --el-1: 0 1px 0 rgba(0,0,0,0.4);
  --el-2: 0 4px 12px rgba(0,0,0,0.5);
  --el-3: 0 12px 32px rgba(0,0,0,0.6);
}
```

## Task 4: Wire tokens.css into index.html

**Files:**
- Modify: `webui/static/index.html` (lines 8-10, the CSS link block)

- [ ] **Step 1: Insert the link**

Use Edit:

old_string:
```
  <link rel="stylesheet" href="/static/css/reset.css">
  <link rel="stylesheet" href="/static/css/theme.css">
  <link rel="stylesheet" href="/static/css/track.css">
```

new_string:
```
  <link rel="stylesheet" href="/static/css/reset.css">
  <link rel="stylesheet" href="/static/css/tokens.css">
  <link rel="stylesheet" href="/static/css/theme.css">
  <link rel="stylesheet" href="/static/css/track.css">
```

- [ ] **Step 2: Reload and confirm no break**

Call `mcp__plugin_playwright_playwright__browser_evaluate` with `{function: "() => { location.reload(); }"}`. Wait 2 seconds, then call `mcp__plugin_playwright_playwright__browser_console_messages` and confirm no new errors. Take a screenshot to `tests/screenshots/polish-audit/01-after-tokens-wired.png` and confirm it looks identical to baseline (tokens are defined but nothing references them yet).

## Task 5: Refactor track.css — font families

**Files:**
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Find all font-family literals**

Use Grep with pattern `font-family|ui-monospace|ui-serif|Georgia` in `webui/static/css/track.css`, output mode `content`, show line numbers.

- [ ] **Step 2: Replace mono font stacks**

Use Edit with `replace_all: true`:

old_string: `font-family: ui-monospace, monospace`
new_string: `font-family: var(--font-mono)`

- [ ] **Step 3: Replace serif/numeral font stacks**

Use Edit with `replace_all: true`:

old_string: `font-family: ui-serif, Georgia, serif`
new_string: `font-family: var(--font-numeral)`

- [ ] **Step 4: Reload and screenshot**

`browser_evaluate` reload, take screenshot to `tests/screenshots/polish-audit/02-after-fonts.png`. Open both `00-baseline-pre-tokens.png` and `02-after-fonts.png` via Read tool — they should be near-identical (the token font stacks include the same primaries plus richer fallbacks). If a visible regression appears (e.g., a different mono weight rendering), STOP and investigate before proceeding.

## Task 6: Refactor track.css — font-size literals

**Files:**
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: List all font-size occurrences**

```
Grep pattern: font-size:\s*\d+px
File: webui/static/css/track.css
Output mode: content with line numbers
```

- [ ] **Step 2: Apply mappings line-by-line (NOT replace_all — context matters)**

For each occurrence, use Edit with the surrounding line as `old_string` to disambiguate, mapping:

| Literal | Token | Notes |
|---|---|---|
| `font-size: 9px` | keep as-is | No token covers 9px. Add to audit doc as candidate "consider micro at 10px or add --t-tiny". |
| `font-size: 10px` | `font-size: var(--t-micro)` | |
| `font-size: 11px` | `font-size: var(--t-body)` | |
| `font-size: 12px` | `font-size: var(--t-body)` | 12 maps to body (closer to 11 than 13 in current usage; if any feels too small after, log audit refinement). |
| `font-size: 13px` | `font-size: var(--t-prose)` | |
| `font-size: 14px` | keep as-is | One-off. Audit candidate. |
| `font-size: 16px` | keep as-is | One-off (`.now-card .now-time .time-num`). Audit candidate. |
| `font-size: 36px` | keep as-is | Hero numeral (`.now-card .rn`). Audit candidate "promote --t-display-lg". |

- [ ] **Step 3: Reload and screenshot**

`browser_evaluate` reload, take `tests/screenshots/polish-audit/03-after-sizes.png`. Compare to `02-after-fonts.png`. Should be pixel-identical (both literals and tokens evaluate to the same numeric values). If anything moved, the mapping was wrong — investigate.

## Task 7: Refactor track.css — box-shadow + selected spacing literals

**Files:**
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: List all box-shadow occurrences**

```
Grep pattern: box-shadow:
File: webui/static/css/track.css
Output mode: content with line numbers
```

- [ ] **Step 2: Apply box-shadow mappings (elevation-style only; leave decorative shadows/insets alone)**

Use Edit per line:

| Literal pattern | Replace with | Found in |
|---|---|---|
| `box-shadow: 0 12px 32px rgba(0,0,0,.6)` | `box-shadow: var(--el-3)` | `.tp-panel` |
| `box-shadow: 0 4px 12px rgba(0,0,0,.5)` | `box-shadow: var(--el-2)` | `.hover-tip` |
| `box-shadow: 0 1px 4px rgba(0,0,0,.4)` | `box-shadow: var(--el-1)` | `#roll-frame .auto-badge` |

**Leave alone (decorative/inset, not elevation):**
- `box-shadow: inset 3px 0 0 0 var(--accent)` — current-row indicator
- `box-shadow: inset 2px 0 0 0 white` — highlighted-row indicator
- `box-shadow: 0 0 4px rgba(255,184,107,.7)` — playhead glow
- `box-shadow: 0 0 8px rgba(255,255,255,.7)` — playhead glow
- `box-shadow: 0 0 0 1px rgba(0,0,0,.4)` — minimap viewport outline

- [ ] **Step 3: Reload and verify shadows**

`browser_evaluate` reload, take `tests/screenshots/polish-audit/04a-after-shadows.png`. Compare to `03-after-sizes.png`. The `--el-1` mapping is approximate (`0 1px 0` vs `0 1px 4px`), so the auto-badge may have a slightly tighter shadow. If the visual difference is too pronounced, change `--el-1` in `tokens.css` to `0 1px 4px rgba(0,0,0,0.4)` exactly (token edit is one-shot, no other consumers yet).

- [ ] **Step 4: Identify spacing literals that map exactly to tokens**

The spec says "only the obvious ones (panel padding, section gaps). Don't churn every margin." Obvious = literal value matches a token value EXACTLY (`4`/`8`/`12`/`16`/`24`px). Run:

```
Grep pattern: (padding|gap|margin):\s*(\d+)px
File: webui/static/css/track.css
Output mode: content with line numbers
```

For each line, identify which numeric values match tokens. Examples to swap:
- `padding: 24px` → `padding: var(--sp-5)` (only if both axes are 24)
- `padding: 12px 14px` → `padding: var(--sp-3) 14px` ❌ — 14 is not a token, leaves a mixed expression that's harder to read. **Skip mixed cases.** Only swap when ALL values on the property line are token-valued.
- `gap: 8px` → `gap: var(--sp-2)` ✓
- `gap: 14px` → leave (14 isn't a token; log "consider dropping --sp-4 to 14 or adding a stop")

Restrict the sweep to property lines on `padding` / `gap` / `margin` shorthand-and-axis variants (`padding-top`, `padding-inline`, etc.). Do NOT touch positional offsets (`top`/`left`/`width`/`height`) — those aren't part of the spacing rhythm.

- [ ] **Step 5: Apply spacing edits**

Use Edit per line. Swap only the unambiguous, all-tokenable lines. Keep a running tally — if you find more than 8-10 swaps, you're churning; stop and reassess against the "panel padding, section gaps" guidance.

- [ ] **Step 6: Reload and screenshot diff**

`browser_evaluate` reload, take `tests/screenshots/polish-audit/04b-after-spacing.png`. Compare to `04a-after-shadows.png`. Should be pixel-identical — token values equal the literals they replaced. If anything moved, a swap was wrong.

## Task 8: Run regression suites

**Files:** none

- [ ] **Step 1: Backend pytest**

```powershell
cd "<PROJECT_PATH>/webui"
.\.venv\Scripts\python -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Frontend node:test**

```powershell
cd "<PROJECT_PATH>"
node --test webui/tests-js/*.test.js
```

Expected: all tests pass.

- [ ] **Step 3: Playwright e2e**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npm test
```

Expected: all tests pass.

If any suite fails: stop, investigate. Token refactor should not have functional impact — failure means a typo or unintended cascade change.

## Task 9: Foundation commit

**Files:** none (commit only)

- [ ] **Step 1: Stage code-only changes**

Screenshots stay uncommitted at this stage — they'll be bundled with the audit commit. Stage only the code:

```powershell
cd "<PROJECT_PATH>"
git add webui/static/css/tokens.css webui/static/index.html webui/static/css/track.css
git status --short
```

Expected: 3 files staged (1 new, 2 modified). No screenshots staged.

- [ ] **Step 2: Commit**

```powershell
git commit -m @'
refactor(webui): typography + spacing token layer

Introduce tokens.css with 16 named variables (3 font families, 4 type
sizes, 1 letter-spacing, 5 spacings, 3 elevations) and refactor track.css
to reference them. No visible change — foundation for the editorial
polish session described in
docs/superpowers/specs/2026-05-02-webui-polish-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

- [ ] **Step 3: Verify**

```powershell
git log --oneline -3
git status --short
```

Expected: new commit on top, working tree shows only screenshot files (untracked, kept for the next phase).

---

# Phase 1 — Audit sweep

Outcome: one commit (`docs(webui): polish audit findings`) that adds the audit doc and all audit screenshots, with the user having triaged which findings make the Phase 2 cut.

## Task 10: Initialize the audit doc

**Files:**
- Create: `docs/superpowers/notes/2026-05-02-webui-audit.md`

- [ ] **Step 1: Ensure notes directory exists**

```powershell
New-Item -ItemType Directory -Force -Path "<PROJECT_PATH>/docs/superpowers/notes" | Out-Null
```

- [ ] **Step 2: Write the skeleton**

```markdown
# webui polish audit — 2026-05-02

Findings from the Playwright-driven audit sweep. Spec at
`docs/superpowers/specs/2026-05-02-webui-polish-design.md`.

**Severity:** P1 broken / P2 refine / P3 nice-to-have
**Category:** bug / refine / ia
**Format:** `- [ ] [Pn] [cat] short title — screenshot ref` then a `notes:` line

## A. Empty state

(populated in Task 11)

## B. Track loaded, idle

(populated in Task 11)

## C. Track playing

(populated in Task 11)

## D. Hover states

(populated in Task 12)

## E. Mute / solo

(populated in Task 12)

## F. Track picker

(populated in Task 12)

## G. Modals (Settings, Tools, Shortcuts, Reanalyze)

(populated in Task 13)

## H. Toasts / errors

(populated in Task 13)

## I. Suppressed / missing stems

(populated in Task 14)

## J. Narrow viewport (1280×800)

(populated in Task 15)

## K. Token-refactor near-misses (from Phase 0)

Carry-overs flagged during the foundation pass:
- `font-size: 9px` occurrences — no token; consider `--t-tiny: 9px` or rebase to `--t-micro: 10px`.
- `font-size: 14px` one-off — log occurrence(s).
- `font-size: 16px` (`.now-card .now-time .time-num`) — promote to `--t-prose-lg` if reused.
- `font-size: 36px` (`.now-card .rn`) — promote to `--t-display-lg` if reused.
- `--el-1` token (`0 1px 0`) approximated `auto-badge`'s `0 1px 4px rgba(0,0,0,.4)` — verify visually.

## Triage

(user fills this section after audit complete; mark items as included/deferred)

## Deferred

(items not chosen for Phase 2 cut land here as future work)
```

## Task 11: Audit flows A-C — empty / idle / playing

**Files:**
- Create: screenshots in `tests/screenshots/polish-audit/`
- Modify: `docs/superpowers/notes/2026-05-02-webui-audit.md`

- [ ] **Step 1: Flow A — empty state**

The webui auto-loads the most recent track. To see the picker-only empty-ish state: open the topbar track-picker (click on the track title in the topbar), wait for the panel to render. Screenshot to `polish-audit/A1-picker-open.png`. If a true "no track selected" state isn't reachable from the live UI, document this as a finding ("no empty state — first load picks a track"). Note any layout, spacing, or focus-ring issues in the picker as findings under section A of the audit doc.

- [ ] **Step 2: Flow B — track loaded, idle (1600×1000)**

Close the picker (Escape), confirm Gorillaz fixture loaded, t=0, paused. Screenshot to `polish-audit/B1-idle-overview.png`. Then capture three close-ups via `browser_take_screenshot` with `element` references obtained from `browser_snapshot`:
- `B2-topbar.png` — `#topbar`
- `B3-sidebar.png` — `#viewer-side`
- `B4-transport.png` — `#transport`

For each, look for: typography hierarchy issues, idle/empty copy that feels limp (the `(no chord)` text under "NOW PLAYING" is a known suspect), spacing inconsistency between sections, alignment to grid, contrast on small text. Append findings to section B of the audit doc.

- [ ] **Step 3: Flow C — track playing**

Press Space (`browser_press_key` with `{key: "Space"}`). Wait 8 seconds for playback to advance and the now-playing card to populate with a real chord. Screenshot to `polish-audit/C1-playing.png`. Then close-up the now-playing card (`C2-now-card-filled.png`). Look for: playhead glow rendering, auto-scroll badge state, time display formatting, chord/Roman numeral typography. Press Space again to pause.

Append findings under section C.

## Task 12: Audit flows D-F — hover / mute-solo / picker

**Files:**
- Create: screenshots in `tests/screenshots/polish-audit/`
- Modify: `docs/superpowers/notes/2026-05-02-webui-audit.md`

- [ ] **Step 1: Flow D — hover states**

Use `browser_hover` to hover over each, screenshot each:
- Sidebar track row (e.g., the Vocals row): `D1-hover-track-row.png`
- Topbar menu item (Tools): `D2-hover-tools.png`
- Track-picker chevron in topbar: `D3-hover-picker.png`
- Transport play button: `D4-hover-play.png`
- Canvas at a reasonable position (use `browser_evaluate` to compute a center point on the canvas, then hover): `D5-hover-canvas.png` — this should reveal pitch tooltip + row-band highlight.

Findings under section D: hover-state visibility, contrast in hover bg, transition smoothness (or lack of), focus-ring presence.

- [ ] **Step 2: Flow E — mute / solo**

Use `browser_click` on the M button of the Vocals sidebar row, then S on the Bass row. Screenshot to `polish-audit/E1-mute-solo-active.png`. Find the visual indicators (red M button, orange S button per current CSS) and assess: are they obvious? Is the visual treatment matched between M and S? Restore by clicking each off again. Findings under section E.

- [ ] **Step 3: Flow F — track picker**

Click the topbar track title to open the picker. Screenshot `F1-picker-open.png`. Use `browser_type` to type a few chars into the search input (e.g., "gor"). Screenshot `F2-picker-filter.png`. Hover a filter pill (`browser_hover` on `.tp-controls .pill`) and screenshot `F3-picker-pill-hover.png`. Close picker (Escape).

Findings under F: filter pill hierarchy, search-input focus ring, row hover treatment, footer typography, panel elevation.

## Task 13: Audit flows G-H — modals / toasts

**Files:**
- Create: screenshots in `tests/screenshots/polish-audit/`
- Modify: `docs/superpowers/notes/2026-05-02-webui-audit.md`

- [ ] **Step 1: Settings modal**

Click the topbar `Settings` item. Screenshot `G1-settings-modal.png`. Note: backdrop opacity, modal elevation, padding rhythm, header/body typography hierarchy, button styles. Close (Escape or close button).

- [ ] **Step 2: Tools modal**

Click `Tools`. Screenshot `G2-tools-modal.png`. Same checklist. Close.

- [ ] **Step 3: Shortcuts modal**

Press `?`. Screenshot `G3-shortcuts-modal.png`. The shortcuts panel is also visible in the sidebar — assess whether the modal duplicates information unnecessarily. Close.

- [ ] **Step 4: Reanalyze modal (open, do not run)**

Click `Tools`, then click the `Reanalyze (clear cache + re-run pipeline)` row. Screenshot `G4-reanalyze-modal.png`. **Do NOT click confirm** — this would wipe the cache and run the WSL pipeline (~minutes). The reanalyze modal is known to have been recently enlarged (commit `6f0155b`); audit it for over-spacing, log scroll behavior at idle. Cancel/close.

- [ ] **Step 5: Flow H — error toast**

Trigger via `browser_evaluate`:
```js
() => fetch("/api/tracks/__nonexistent__").catch(() => {});
```
This may or may not produce a toast depending on the error pathway. If it doesn't, try loading a bad URL by manipulating `window.location.hash` or the picker. If no toast surfaces, document "could not trigger toast in audit; needs a separate test track or backend mocking" as a finding rather than spending more time.

If a toast appears: screenshot `H1-error-toast.png`, then findings under H (toast typography, dismiss affordance, color/elevation, position, animation).

Findings under sections G and H.

## Task 14: Audit flow I — suppressed / missing stems

**Files:**
- Create: screenshots in `tests/screenshots/polish-audit/`
- Modify: `docs/superpowers/notes/2026-05-02-webui-audit.md`

- [ ] **Step 1: Survey tracks**

Open the picker, scan for tracks with warnings or unusual states. Or fetch via API:

```js
() => fetch("/api/tracks").then(r => r.json())
```

via `browser_evaluate`, returning the result. Look for tracks where stems may be suppressed (the presence-gate may have fired) or missing.

- [ ] **Step 2: If a candidate exists**

Switch tracks to a candidate, screenshot the sidebar `I1-suppressed-stems.png` and the suppressed-footer if visible (`I2-suppressed-footer.png`). Findings under section I.

- [ ] **Step 3: If no candidate**

Document under section I: "no track in fixture set exhibits suppressed/missing stems; CSS rules `.stem-missing`, `.stem-suppressed`, `.stems-suppressed-footer` audited from source only." Inspect the CSS rules in `webui/static/css/track.css` lines 117-150 and note any obvious issues (color contrast on `--fg-3`, spacing, dotted-underline cursor target size).

- [ ] **Step 4: Restore Gorillaz fixture**

Switch back to Gorillaz before flow J.

## Task 15: Audit flow J — narrow viewport (1280×800)

**Files:**
- Create: screenshots in `tests/screenshots/polish-audit/`
- Modify: `docs/superpowers/notes/2026-05-02-webui-audit.md`

- [ ] **Step 1: Resize**

Call `browser_resize` with `{width: 1280, height: 800}`.

- [ ] **Step 2: Capture parallel set**

Screenshot:
- `J1-idle-1280.png` — full viewport at narrow width
- `J2-topbar-1280.png` — element close-up
- `J3-sidebar-1280.png` — element close-up
- `J4-transport-1280.png` — element close-up

- [ ] **Step 3: Open picker at narrow width**

Open picker, screenshot `J5-picker-1280.png`. The picker panel is `width: 480px`; verify it fits within the topbar width.

- [ ] **Step 4: Findings**

Look for: overflow into scroll regions, sidebar width crowding, transport zoom-group wrapping, topbar items wrapping or hiding, picker panel clipping. Append under section J.

- [ ] **Step 5: Restore default viewport**

Resize back to `{width: 1600, height: 1000}` for any subsequent work.

## Task 16: Commit audit + screenshots

**Files:** none (commit only)

- [ ] **Step 1: Stage**

```powershell
cd "<PROJECT_PATH>"
git add docs/superpowers/notes/2026-05-02-webui-audit.md tests/screenshots/polish-audit/
git status --short
```

Expected: audit doc (new), all screenshots in `polish-audit/` (new). No fixes yet.

- [ ] **Step 2: Commit**

```powershell
git commit -m @'
docs(webui): polish audit findings

10-flow Playwright sweep + 1280×800 narrow-viewport pass at
docs/superpowers/notes/2026-05-02-webui-audit.md, with reference
screenshots in tests/screenshots/polish-audit/. Triage section
empty pending user review — Phase 2 fixes will be planned in a
follow-up plan once items are chosen.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

## Task 17: Triage gate — present audit, await user picks

**Files:** none (hand-off)

- [ ] **Step 1: Summarize the audit to the user**

Post a message naming the count of findings per severity (P1/P2/P3) and per category (bug/refine/ia), plus the top 3-5 P1s by severity-then-impact. Link the audit doc and the screenshot directory.

- [ ] **Step 2: Ask the user to triage**

Ask the user to edit the `## Triage` section of `docs/superpowers/notes/2026-05-02-webui-audit.md` directly, marking items they want included with a `[x]` checkbox, or to reply with the numbers they want included. Default cap: 10-15 items. Anything not marked moves to `## Deferred`.

- [ ] **Step 3: Wait**

Do not proceed to Phase 2 planning until the user has responded with their triage choices. This is the only mid-implementation pause in the session.

- [ ] **Step 4: Hand-off to Phase 2 sub-plan**

Once triage is in, write a follow-up plan at `docs/superpowers/plans/2026-05-02-webui-polish-fixes.md` that decomposes the chosen items into 4-6 area-scoped fix tasks (each producing one commit), invoking the writing-plans skill again. Then resume execution against that plan.

---

# Done criteria (Phase 0 + Phase 1)

- Foundation commit lands. Before/after foundation screenshots show no visible regression.
- Audit doc committed at `docs/superpowers/notes/2026-05-02-webui-audit.md` with sections A-K populated, all P1 issues recorded, screenshots referenced and present in `tests/screenshots/polish-audit/`.
- All three regression suites green at end of Phase 0.
- Triage section filled by user; Phase 2 sub-plan written and ready to execute.
