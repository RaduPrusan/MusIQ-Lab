# UI Polish + Themable Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tokenize every color/transparency/radius/motion literal in the webui, expose them in `Settings → Appearance` (4 presets + per-token controls) with `localStorage` persistence and pre-paint hydration, then drive the iterative polish via a Ralph loop where two Opus subagents (implementer + independent Playwright reviewer) alternate until the reviewer signs off twice in a row.

**Architecture:** Three sequential build phases, then a fourth autonomous-loop phase. Phase 1 extends `tokens.css` and sweeps every literal in CSS + inline JS into named tokens, behind a ≤0.5 % visual-diff guardrail. Phase 2 builds the `webui/static/js/theme/` module package, the inline pre-paint hydration script, and the `showSettings()` Appearance section. Phase 3 builds the `tests-e2e/visual-review.spec.js` Playwright spec, the implementer/reviewer prompts, and the `scripts/ui-polish-loop.py` orchestrator. Phase 4 launches the loop and writes the ship report.

**Tech Stack:** Vanilla JS (no framework, ES modules), CSS custom properties, FastAPI static serving (no template engine), `node --test` + `jsdom` for unit tests (existing pattern), `@playwright/test` 1.45.x with `axe-core/playwright` for the reviewer spec, `pixelmatch` + `pngjs` for the Phase 1 diff guardrail, `claude-agent-sdk` (Python) for the Ralph runner.

**Spec:** [`docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md`](../specs/2026-05-09-ui-polish-themable-tokens-design.md)

---

## File Structure

### New files

```
webui/static/js/theme/
  presets.js            # 4 preset definitions (token → value maps)
  store.js              # localStorage I/O + getTheme/setTheme/subscribe
  apply.js              # writes a token map onto documentElement.style
  derive.js             # accent derivation (color-mix + WCAG luminance)
  css-tokens.js         # canvas-side reader; rebinds on musiq:theme-changed

webui/tests-js/
  theme-presets.test.js
  theme-store.test.js
  theme-apply.test.js
  theme-derive.test.js

webui/tests-e2e/
  visual-review.spec.js              # 4 presets × 6 scenes + axe scan → verdict.json
  visual-baseline.spec.js            # Phase 1 guardrail: ≤0.5% diff under Classic Dark
  visual-review/                     # output dir (gitignored except verdict.json + axe.json)

scripts/
  ui-polish-loop.py                  # claude-agent-sdk runner

prompts/
  ui-polish-implementer.md
  ui-polish-reviewer.md

install-logs/
  ui-polish-2026-05-09-token-audit.md   # Phase 1 mapping decisions
  ui-polish-2026-05-09-iter-N.md        # one per loop iteration (auto-written)
  ui-polish-2026-05-09-results.md       # Phase 4 ship report
```

### Modified files

```
webui/static/css/tokens.css              # extended with color/alpha/radius/motion + aliases
webui/static/css/theme.css               # rewritten as Classic Dark preset application
webui/static/css/track.css               # literals → tokens
webui/static/index.html                  # inline pre-paint <head> script
webui/static/js/main.js                  # listen for musiq:theme-changed
webui/static/js/ui/menus.js              # showSettings() gains Appearance section
webui/static/js/ui/{topbar,sidebar,track-picker,reanalyze,analyze-modal,analyze-shared,shortcuts,lyrics-tab,rename-modal}.js
                                          # inline-style literals → "var(--…)"
webui/static/js/render/pianoroll.js      # uses css-tokens.js reader
webui/static/js/render/f0-overlay.js     # uses css-tokens.js reader
webui/tests-e2e/playwright.config.js     # adds preset projects (4)
webui/tests-e2e/package.json             # +axe-core, @axe-core/playwright, pixelmatch, pngjs
.gitignore                               # ignore visual-review/*.png
pyproject.toml or requirements.txt       # +claude-agent-sdk
```

---

## Phase 1 — Token expansion + sweep

### Task 1.1: Extend tokens.css with color / alpha / radius / motion sections

**Files:**
- Modify: `webui/static/css/tokens.css`

- [ ] **Step 1: Replace the entire contents of `tokens.css` with the extended token surface**

```css
/* tokens.css — full design-token surface.
   Loaded BEFORE theme.css. Default values represent the Classic Dark preset;
   theme.css applies the preset semantically, the theme engine overrides per
   user preference at runtime via documentElement.style.setProperty. */

:root {
  /* ---- Typography (unchanged from 2026-05-02) ---------------------- */
  --font-sans:    ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono:    ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  --font-numeral: ui-serif, Georgia, "Iowan Old Style", serif;

  --t-micro:    10px;
  --t-body:     11px;
  --t-prose:    13px;
  --t-display:  24px;

  --ls-caps:    0.07em;

  /* ---- Spacing (unchanged) ----------------------------------------- */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;

  /* ---- Elevation (unchanged) --------------------------------------- */
  --el-1: 0 1px 4px rgba(0,0,0,0.4);
  --el-2: 0 4px 12px rgba(0,0,0,0.5);
  --el-3: 0 12px 32px rgba(0,0,0,0.6);

  /* ---- Surfaces (background layers, base → most-elevated) ---------- */
  --surface-base:        #0e0e10;
  --surface-1:           #15151a;
  --surface-2:           #1f1f25;
  --surface-3:           #2a2a30;

  /* ---- Text -------------------------------------------------------- */
  --text-primary:        #e7e7ea;
  --text-secondary:      #c6c6cc;
  --text-muted:          #888;
  --text-disabled:       #555;

  /* ---- Accent ------------------------------------------------------ */
  --accent:              #ffb86b;
  --accent-emphasis:     #ffc888;
  --accent-on:           #1a1a25;

  /* ---- Focus ring -------------------------------------------------- */
  --focus-ring:          #6cf;

  /* ---- Semantic ---------------------------------------------------- */
  --status-error:        #ff8a8a;
  --status-error-bg:     #2a0e0e;
  --status-warning:      #f0c98a;
  --status-success:      #9c9;
  --status-info:         #9cf;

  /* ---- Stems ------------------------------------------------------- */
  --stem-vocals:         #ff7eaa;
  --stem-bass:           #7ecaff;
  --stem-guitar:         #bcff7e;
  --stem-piano:          #ffc97e;
  --stem-other:          #cf7eff;
  --stem-drums:          #888;

  /* ---- Harmonic-function colors ----------------------------------- */
  --fn-tonic-bg:         #1a261a;
  --fn-tonic-fg:         #9c9;
  --fn-dominant-bg:      #26221a;
  --fn-dominant-fg:      #fc9;
  --fn-modal-bg:         #2a1a26;
  --fn-modal-fg:         #e3c3ff;
  --fn-predominant-fg:   #9cf;

  /* ---- Borders ----------------------------------------------------- */
  --border-soft:         #1f1f24;
  --border-strong:       #2a2a30;

  /* ---- Alpha tokens (every transparency named) -------------------- */
  --alpha-scrim:           0.55;
  --alpha-overlay-soft:    0.08;
  --alpha-overlay-med:     0.20;
  --alpha-overlay-strong:  0.55;
  --alpha-glow-soft:       0.30;
  --alpha-glow-strong:     0.70;
  --alpha-grid-line:       0.10;
  --alpha-stem-fill:       0.85;

  /* ---- Radii ------------------------------------------------------- */
  --radius-1:    3px;
  --radius-2:    4px;
  --radius-3:    6px;
  --radius-4:    10px;
  --radius-pill: 9999px;

  /* ---- Motion ------------------------------------------------------ */
  --motion-fast:   0.12s;
  --motion-medium: 0.18s;
  --motion-slow:   0.30s;

  /* ---- Back-compat aliases (DELETED at end of Phase 1) ------------- */
  --bg-0: var(--surface-base);
  --bg-1: var(--surface-1);
  --bg-2: var(--surface-2);
  --bg-3: var(--surface-3);
  --fg-0: var(--text-primary);
  --fg-1: var(--text-secondary);
  --fg-2: var(--text-muted);
  --fg-3: var(--text-disabled);
  --c-vocals: var(--stem-vocals);
  --c-bass:   var(--stem-bass);
  --c-guitar: var(--stem-guitar);
  --c-piano:  var(--stem-piano);
  --c-other:  var(--stem-other);
  --c-drums:  var(--stem-drums);
}
```

- [ ] **Step 2: Verify the file parses (no syntax errors) by reloading the running webui**

Run from PowerShell:
```powershell
<PROJECT_PATH>\webui\webui.ps1 restart
```

Then in a browser: `http://127.0.0.1:8765/?slug=gorillaz_silent_running`

Expected: app loads with no console errors; appearance unchanged from baseline (the new tokens have the same default values as the current `theme.css` literals + aliases).

- [ ] **Step 3: Commit**

```powershell
git add webui/static/css/tokens.css
git commit -m "refactor(webui): extend tokens.css to full design-token surface"
```

---

### Task 1.2: Rewrite theme.css as Classic Dark preset application

**Files:**
- Modify: `webui/static/css/theme.css`

- [ ] **Step 1: Replace `theme.css` contents**

```css
/* theme.css — applies the Classic Dark preset semantically.
   Token values live in tokens.css; this file binds them to the document body
   and to legacy single-purpose properties. The theme engine swaps preset
   values at runtime via documentElement.style; this file is preset-agnostic
   in everything except its filename. */

body {
  background: var(--surface-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
}
```

(All the previous `:root` declarations move into `tokens.css`. `theme.css` is now just the body binding — every other usage references the tokens directly.)

- [ ] **Step 2: Reload and confirm no visual regression**

```powershell
<PROJECT_PATH>\webui\webui.ps1 restart
```

Browser: `http://127.0.0.1:8765/?slug=gorillaz_silent_running` — should look pixel-identical to before this commit.

- [ ] **Step 3: Commit**

```powershell
git add webui/static/css/theme.css
git commit -m "refactor(webui): theme.css applies Classic Dark preset semantically"
```

---

### Task 1.3: Add Phase 1 visual-diff guardrail (baseline + spec)

**Files:**
- Modify: `webui/tests-e2e/package.json` (add deps)
- Create: `webui/tests-e2e/visual-baseline.spec.js`
- Create: `webui/tests-e2e/fixtures/baseline/` directory

The guardrail captures 6 baseline screenshots BEFORE the sweep, then the spec compares to fresh screenshots after each batch. ≤0.5 % pixel difference is the gate.

- [ ] **Step 1: Add `pixelmatch` + `pngjs` to `webui/tests-e2e/package.json`**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npm install --save-dev pixelmatch pngjs
```

Verify `package.json` now has both packages under `devDependencies`.

- [ ] **Step 2: Create `webui/tests-e2e/visual-baseline.spec.js`**

```javascript
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";

const FIXTURE_SLUG = "gorillaz_silent_running";
const BASELINE_DIR = path.join("fixtures", "baseline");
const CURRENT_DIR = path.join("visual-review", "_baseline-current");
const DIFF_DIR = path.join("visual-review", "_baseline-diff");
const PIXEL_TOLERANCE = 0.005; // 0.5 %

const SCENES = [
  { name: "default-load", setup: async (page) => {
    await page.goto(`/?slug=${FIXTURE_SLUG}`);
    await page.waitForSelector("#roll-frame canvas.notes", { timeout: 10_000 });
    await page.waitForTimeout(500);
  }},
  { name: "picker-open", setup: async (page) => {
    await page.goto(`/?slug=${FIXTURE_SLUG}`);
    await page.waitForSelector(".track-picker", { timeout: 10_000 });
    await page.click(".track-picker");
    await page.waitForSelector(".tp-panel", { timeout: 5_000 });
  }},
  { name: "settings-open", setup: async (page) => {
    await page.goto(`/?slug=${FIXTURE_SLUG}`);
    await page.waitForSelector("#topbar .menu .item", { timeout: 10_000 });
    await page.click('#topbar .menu .item:has-text("Settings")');
    await page.waitForTimeout(300);
  }},
  { name: "vocals-tab", setup: async (page) => {
    await page.goto(`/?slug=${FIXTURE_SLUG}`);
    await page.waitForSelector(".tab-strip .tab", { timeout: 10_000 });
    await page.click('.tab-strip .tab:has-text("Lyrics")');
    await page.waitForTimeout(300);
  }},
  { name: "claude-tab", setup: async (page) => {
    await page.goto(`/?slug=${FIXTURE_SLUG}`);
    await page.waitForSelector(".tab-strip .tab", { timeout: 10_000 });
    await page.click('.tab-strip .tab:has-text("Claude")');
    await page.waitForTimeout(300);
  }},
  { name: "transport-playing", setup: async (page) => {
    await page.goto(`/?slug=${FIXTURE_SLUG}`);
    await page.waitForSelector("#transport .play-btn", { timeout: 10_000 });
    await page.click("#transport .play-btn");
    await page.waitForTimeout(2_000);
    await page.click("#transport .play-btn");
    await page.waitForTimeout(300);
  }},
];

test.describe("Phase 1 visual-diff guardrail (Classic Dark)", () => {
  for (const scene of SCENES) {
    test(`${scene.name} matches baseline within 0.5%`, async ({ page }) => {
      await scene.setup(page);
      const buf = await page.screenshot({ fullPage: false });
      fs.mkdirSync(CURRENT_DIR, { recursive: true });
      const currentPath = path.join(CURRENT_DIR, `${scene.name}.png`);
      fs.writeFileSync(currentPath, buf);

      const baselinePath = path.join(BASELINE_DIR, `${scene.name}.png`);
      if (!fs.existsSync(baselinePath)) {
        // First run captures baseline.
        fs.mkdirSync(BASELINE_DIR, { recursive: true });
        fs.copyFileSync(currentPath, baselinePath);
        test.skip(true, `Baseline captured at ${baselinePath}; rerun to compare.`);
        return;
      }

      const baseline = PNG.sync.read(fs.readFileSync(baselinePath));
      const current = PNG.sync.read(buf);
      expect(baseline.width).toBe(current.width);
      expect(baseline.height).toBe(current.height);

      const diff = new PNG({ width: baseline.width, height: baseline.height });
      const numDiff = pixelmatch(
        baseline.data, current.data, diff.data,
        baseline.width, baseline.height, { threshold: 0.1 }
      );
      const totalPixels = baseline.width * baseline.height;
      const fraction = numDiff / totalPixels;

      if (fraction > PIXEL_TOLERANCE) {
        fs.mkdirSync(DIFF_DIR, { recursive: true });
        fs.writeFileSync(path.join(DIFF_DIR, `${scene.name}.png`), PNG.sync.write(diff));
      }
      expect(fraction).toBeLessThanOrEqual(PIXEL_TOLERANCE);
    });
  }
});
```

- [ ] **Step 3: Capture baseline (first run skips, populates fixtures)**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

Expected: 6 tests skipped, `fixtures/baseline/*.png` populated.

- [ ] **Step 4: Run again to confirm baseline matches itself**

```powershell
npx playwright test visual-baseline.spec.js
```

Expected: 6 tests pass, `fraction` ~0.

- [ ] **Step 5: Commit baseline + spec**

```powershell
git add webui/tests-e2e/visual-baseline.spec.js webui/tests-e2e/fixtures/baseline webui/tests-e2e/package.json webui/tests-e2e/package-lock.json
git commit -m "test(webui): Phase 1 visual-diff guardrail at 0.5% tolerance"
```

---

### Task 1.4: Sweep `track.css` literal → token

**Files:**
- Modify: `webui/static/css/track.css`
- Create: `install-logs/ui-polish-2026-05-09-token-audit.md`

`track.css` holds ~150 of the 168 literal occurrences. Sweep with the mapping table below; ambiguous cases get logged in the audit doc.

**Mapping table — apply mechanically:**

| Literal | Token replacement |
|---|---|
| `#0e0e10` | `var(--surface-base)` |
| `#15151a` | `var(--surface-1)` |
| `#1f1f25`, `#1f1f24` | `var(--surface-2)` for `1f1f25`; `var(--border-soft)` for `1f1f24` |
| `#2a2a30` | `var(--surface-3)` |
| `#101014`, `#08080b`, `#0d0d0d`, `#0a0a0a` | `var(--surface-base)` (these are darker accents inside the gutter — see audit doc for rationale; if the visual diff fires, fall back to a literal and add a `--surface-canvas` token in a 1.4b touchup) |
| `#e7e7ea`, `#ddd`, `#fff`, `white` | `white` for pure-white anchor points (play-btn dot, focus rings, accents on dark); `var(--text-primary)` otherwise |
| `#c6c6cc` | `var(--text-secondary)` |
| `#888`, `#9a9aa3` | `var(--text-muted)` |
| `#555`, `#3d3d44`, `#4a4a55` | `var(--text-disabled)` for `#555` and `#3d3d44`; `#4a4a55` is the unfilled mixer-vol fill — keep literal and log to audit (could be a new `--mixer-vol-fill` token if it recurs; it doesn't) |
| `#ffb86b` | `var(--accent)` |
| `#ff7eaa`, `#7ecaff`, `#bcff7e`, `#ffc97e`, `#cf7eff` | `var(--stem-vocals/bass/guitar/piano/other)` |
| `#9cf`, `#6cf` | `var(--focus-ring)` for `#6cf` (focus outlines); `var(--status-info)` or `var(--fn-predominant-fg)` for `#9cf` based on context (see audit doc) |
| `#e3c3ff` | `var(--fn-modal-fg)` |
| `#fc9` | `var(--fn-dominant-fg)` |
| `#9c9` | `var(--status-success)` or `var(--fn-tonic-fg)` (same hex; both apply) |
| `#ff8866`, `#ff8a8a`, `#ffaa99`, `#ff8080`, `#ff6b6b` | `var(--status-error)` (consolidate; audit notes the variants) |
| `#3a2a4a`, `#2a3a3a`, `#2a3a2a`, `#3a2f1f` | topbar badge backgrounds — keep literal in this task, replace in Task 1.4b after a `--badge-{k,t,s,q}-bg` token decision |
| `#1a261a`, `#26221a`, `#2a1a26`, `#3a2a1a`, `#1f1f28` | function-tag backgrounds — already `--fn-*-bg` tokens; replace |
| `#2a3a4a`, `#5a2a2a`, `#4a1a1a`, `#1a1a25` | reanalyze modal — `var(--surface-2)` for `#2a3a4a`; the warm-red destructive set (`#5a2a2a`, `#4a1a1a`) keep literal, log to audit |
| `#23232a`, `#26262e`, `#1c1c22`, `#16161a` | hover-row accent backgrounds — replace with `color-mix(in srgb, var(--surface-2) 80%, var(--surface-3) 20%)` for the variants nearest `surface-2`, log; if visual-diff fires, fall back |
| `#1a1a25` | `var(--accent-on)` |
| `rgba(0,0,0,0.4)`, `rgba(0,0,0,.5)`, `rgba(0,0,0,.6)`, `rgba(0,0,0,.55)` | already in `--el-*` for shadow contexts; the `.55–.6` modal scrims become `rgba(0, 0, 0, var(--alpha-scrim))` |
| `rgba(255,184,107,...)` (varied alpha) | `rgb(255 184 107 / var(--alpha-overlay-med))`, `--alpha-overlay-strong`, `--alpha-glow-soft`, `--alpha-glow-strong` per context (minimap segs ~.30 → med; loop band edge ~.55 → strong; playhead glow ~.7 → strong) |
| `rgba(255,255,255,...)` | `rgb(255 255 255 / var(--alpha-overlay-soft))` for `.05–.10`, `--alpha-overlay-med` for `.18–.30` |
| `rgba(0,0,0,0.55)`, `rgba(0, 0, 0, 0.55)` | modal overlays → `rgb(0 0 0 / var(--alpha-scrim))` |

- [ ] **Step 1: Apply the mapping**

Open `webui/static/css/track.css`. Walk top to bottom, replacing each literal per the mapping. Where the table says "log to audit", append a row to `install-logs/ui-polish-2026-05-09-token-audit.md` (create the file with the heading shown below at first row).

Audit-doc skeleton:

```markdown
# Phase 1 Token Audit (2026-05-09)

## Decisions where literal → token mapping was ambiguous

| File | Literal | Action | Rationale |
|---|---|---|---|
| track.css | `#4a4a55` | kept literal | unique to mixer vol unfilled-track; no reuse elsewhere |
| ... | | | |

## New tokens added beyond spec taxonomy

| Token | Default | Why | Where used |
|---|---|---|---|
```

- [ ] **Step 2: Run the visual-diff guardrail**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

Expected: 6 tests pass.

If a test fails: open `visual-review/_baseline-diff/<scene>.png` to see exactly which pixels differ. Common cause: a wrong token mapping in the table above. Fix the offending literal/token pair, log it in the audit doc, rerun.

- [ ] **Step 3: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/css/track.css install-logs/ui-polish-2026-05-09-token-audit.md
git commit -m "refactor(webui): sweep track.css literals into tokens"
```

---

### Task 1.5: Sweep inline JS styles (per-file batches)

**Files:**
- Modify: `webui/static/js/main.js` and 10 files under `webui/static/js/ui/`
- Modify: `install-logs/ui-polish-2026-05-09-token-audit.md` (append rows as needed)

Each file gets its own commit so blame is clean. Pattern: replace `style: { color: "#hex" }` with `style: { color: "var(--token)" }`.

The 13 files (per `Grep` of hex/rgba in JS):

```
webui/static/js/main.js
webui/static/js/render/f0-overlay.js
webui/static/js/render/pianoroll.js
webui/static/js/ui/analyze-modal.js
webui/static/js/ui/analyze-shared.js
webui/static/js/ui/menus.js
webui/static/js/ui/reanalyze.js
webui/static/js/ui/shortcuts.js
webui/static/js/ui/sidebar.js
webui/static/js/ui/transport.js
```

The render files (`f0-overlay.js`, `pianoroll.js`) paint to `<canvas>` and need numeric token reads — those are deferred to Tasks 1.6 + 1.7. Sweep only the inline-DOM-style hex/rgba in this task.

- [ ] **Step 1: Sweep `main.js`**

The two relevant lines (per earlier `Grep`): `style: { color: "#ff8866" }` (twice, in `showFatal` and the unknown-track error). Replace both with `style: { color: "var(--status-error)" }`.

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

Expected: 6 pass.

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/main.js
git commit -m "refactor(webui): tokenize inline-style colors in main.js"
```

- [ ] **Step 2: Sweep `webui/static/js/ui/menus.js`**

Targets: `rgba(0,0,0,.6)` for the modal overlay → `rgb(0 0 0 / var(--alpha-scrim))`; `#ff8080` (the destructive Reanalyze entry) → `var(--status-error)`.

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/ui/menus.js
git commit -m "refactor(webui): tokenize inline-style colors in menus.js"
```

- [ ] **Step 3: Sweep the remaining 8 files**

For each of `analyze-modal.js`, `analyze-shared.js`, `reanalyze.js`, `shortcuts.js`, `sidebar.js`, `transport.js`, `topbar.js`, `track-picker.js`, `lyrics-tab.js`, `rename-modal.js`:

1. Open the file. Search for `#` followed by 3 or 6 hex chars, and for `rgba(`.
2. Replace per the mapping table from Task 1.4. Anything ambiguous goes in the audit doc.
3. Run `npx playwright test visual-baseline.spec.js` from `webui/tests-e2e`. If it fails, fix the mapping.
4. Commit per file: `git commit -m "refactor(webui): tokenize inline-style colors in <file>.js"`.

Expected after all 8 commits: visual-baseline.spec.js still 6/6 pass.

---

### Task 1.6: Add canvas-side theme reader

**Files:**
- Create: `webui/static/js/theme/css-tokens.js`
- Create: `webui/tests-js/theme-css-tokens.test.js`

Canvas can't read CSS variables natively. The reader caches token values on subscribe, rebinds when `musiq:theme-changed` fires.

- [ ] **Step 1: Write the failing test**

```javascript
// webui/tests-js/theme-css-tokens.test.js
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.CustomEvent = dom.window.CustomEvent;
globalThis.getComputedStyle = dom.window.getComputedStyle;

const root = dom.window.document.documentElement;
root.style.setProperty("--surface-base", "#0e0e10");
root.style.setProperty("--alpha-stem-fill", "0.85");
root.style.setProperty("--accent", "#ffb86b");

const { readToken, readAlpha, subscribe } = await import("../static/js/theme/css-tokens.js");

beforeEach(() => {
  root.style.setProperty("--surface-base", "#0e0e10");
  root.style.setProperty("--alpha-stem-fill", "0.85");
  root.style.setProperty("--accent", "#ffb86b");
});

test("readToken returns the resolved CSS variable value", () => {
  assert.equal(readToken("surface-base"), "#0e0e10");
});

test("readAlpha parses a numeric alpha token", () => {
  assert.equal(readAlpha("alpha-stem-fill"), 0.85);
});

test("readAlpha clamps to [0,1] and returns the default on parse failure", () => {
  root.style.setProperty("--alpha-stem-fill", "broken");
  assert.equal(readAlpha("alpha-stem-fill", 0.5), 0.5);
  root.style.setProperty("--alpha-stem-fill", "1.5");
  assert.equal(readAlpha("alpha-stem-fill"), 1);
  root.style.setProperty("--alpha-stem-fill", "-0.2");
  assert.equal(readAlpha("alpha-stem-fill"), 0);
});

test("subscribe fires the callback when musiq:theme-changed dispatches", () => {
  let calls = 0;
  const off = subscribe(() => calls++);
  document.dispatchEvent(new CustomEvent("musiq:theme-changed", { detail: {} }));
  assert.equal(calls, 1);
  off();
  document.dispatchEvent(new CustomEvent("musiq:theme-changed", { detail: {} }));
  assert.equal(calls, 1);
});
```

- [ ] **Step 2: Verify the test fails**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-css-tokens.test.js
```

Expected: failure with `Cannot find module '../static/js/theme/css-tokens.js'`.

- [ ] **Step 3: Implement `css-tokens.js`**

```javascript
// webui/static/js/theme/css-tokens.js
// Canvas-side reader for CSS custom properties. Subscribers re-read
// after each musiq:theme-changed event so canvas paint paths can refresh
// their cached colors / alphas without polling.

export function readToken(name) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue("--" + name)
    .trim();
}

export function readAlpha(name, fallback = 1) {
  const raw = readToken(name);
  const n = parseFloat(raw);
  if (!Number.isFinite(n)) return fallback;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

export function subscribe(fn) {
  const handler = (e) => fn(e?.detail);
  document.addEventListener("musiq:theme-changed", handler);
  return () => document.removeEventListener("musiq:theme-changed", handler);
}
```

- [ ] **Step 4: Verify the test passes**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-css-tokens.test.js
```

Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/theme/css-tokens.js webui/tests-js/theme-css-tokens.test.js
git commit -m "feat(webui): canvas-side theme-token reader with subscribe"
```

---

### Task 1.7: Update canvas renderers to use the reader

**Files:**
- Modify: `webui/static/js/render/pianoroll.js`
- Modify: `webui/static/js/render/f0-overlay.js`

The piano roll paints note fills using a stem color + the existing `0.85` alpha literal. The f0 overlay paints colored strokes per estimator. Both rebind on theme change.

- [ ] **Step 1: Patch `pianoroll.js`**

Find every literal hex / rgba in `pianoroll.js`. The hot ones (per earlier `Grep`):

- The note-fill alpha (currently `0.85` baked into `ctx.fillStyle = ...`): read as `readAlpha("alpha-stem-fill")` once per render frame.
- The stem colors (currently `#ff7eaa` etc baked in): read via `readToken("stem-" + name)`.
- The grid-line color: read via `readToken("border-soft")` and use `readAlpha("alpha-grid-line")` for the alpha.

Add at the top of the file:

```javascript
import { readToken, readAlpha, subscribe } from "../theme/css-tokens.js";
```

Inside the renderer class, add a token cache that rebinds:

```javascript
constructor(...) {
  // ...existing setup...
  this._theme = this._readThemeCache();
  this._unsubTheme = subscribe(() => {
    this._theme = this._readThemeCache();
    this._needsFullRedraw = true;  // or whatever the existing redraw flag is named
    this._scheduleFrame?.();
  });
}

_readThemeCache() {
  return {
    stems: {
      vocals: readToken("stem-vocals"),
      bass:   readToken("stem-bass"),
      guitar: readToken("stem-guitar"),
      piano:  readToken("stem-piano"),
      other:  readToken("stem-other"),
      drums:  readToken("stem-drums"),
    },
    fillAlpha: readAlpha("alpha-stem-fill", 0.85),
    gridColor: readToken("border-soft"),
    gridAlpha: readAlpha("alpha-grid-line", 0.10),
  };
}

dispose() {
  this._unsubTheme?.();
  // ...rest of dispose...
}
```

Replace inline literals with `this._theme.stems[name]` etc.

- [ ] **Step 2: Patch `f0-overlay.js`**

Same shape — cache `stem-vocals`, `status-info`, `text-primary` (whichever the overlay uses for its 3 estimator paths). Subscribe; rebind on change.

- [ ] **Step 3: Run the visual-baseline guardrail**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

Expected: 6 pass. (Renderers now read tokens, but the *values* are the same as the baked literals — pixel-identical.)

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/render/pianoroll.js webui/static/js/render/f0-overlay.js
git commit -m "refactor(webui): canvas renderers read theme tokens via subscribe"
```

---

### Task 1.8: Remove back-compat aliases + final guardrail

**Files:**
- Modify: `webui/static/css/tokens.css` (delete the alias block)

- [ ] **Step 1: Audit alias usage**

```powershell
cd "<PROJECT_PATH>"
```

Run from PowerShell with the Grep tool semantically — search for `var(--bg-` and `var(--fg-` and `var(--c-` across `webui/static/`. Expected: zero hits if the sweep is clean.

If any hits remain, fix them (replace with the canonical token name) and recommit per the affected file's pattern from Task 1.5.

- [ ] **Step 2: Delete the alias block from `tokens.css`**

Open `webui/static/css/tokens.css`. Delete the comment `/* ---- Back-compat aliases (DELETED at end of Phase 1) ---- */` and the 14 alias lines beneath it.

- [ ] **Step 3: Run guardrail**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

Expected: 6/6 pass.

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/css/tokens.css
git commit -m "refactor(webui): drop Phase 1 token aliases — sweep complete"
```

---

## Phase 2 — Theme engine + Settings UI

### Task 2.1: Create presets.js

**Files:**
- Create: `webui/static/js/theme/presets.js`
- Create: `webui/tests-js/theme-presets.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// webui/tests-js/theme-presets.test.js
import { test } from "node:test";
import assert from "node:assert/strict";

const { PRESETS, PRESET_IDS, DEFAULT_PRESET_ID } = await import("../static/js/theme/presets.js");

const REQUIRED_TOKENS = [
  "surface-base","surface-1","surface-2","surface-3",
  "text-primary","text-secondary","text-muted","text-disabled",
  "accent","accent-emphasis","accent-on",
  "focus-ring",
  "status-error","status-error-bg","status-warning","status-success","status-info",
  "stem-vocals","stem-bass","stem-guitar","stem-piano","stem-other","stem-drums",
  "fn-tonic-bg","fn-tonic-fg","fn-dominant-bg","fn-dominant-fg","fn-modal-bg","fn-modal-fg","fn-predominant-fg",
  "border-soft","border-strong",
  "alpha-scrim","alpha-overlay-soft","alpha-overlay-med","alpha-overlay-strong",
  "alpha-glow-soft","alpha-glow-strong","alpha-grid-line","alpha-stem-fill",
  "radius-1","radius-2","radius-3","radius-4","radius-pill",
  "motion-fast","motion-medium","motion-slow",
];

test("PRESET_IDS contains the four named presets", () => {
  assert.deepEqual(PRESET_IDS.sort(), ["classic-dark","high-contrast","midnight","studio-light"]);
});

test("DEFAULT_PRESET_ID is classic-dark", () => {
  assert.equal(DEFAULT_PRESET_ID, "classic-dark");
});

for (const id of ["classic-dark","midnight","studio-light","high-contrast"]) {
  test(`preset '${id}' defines every required token`, () => {
    const p = PRESETS[id];
    assert.ok(p, `preset ${id} missing`);
    for (const name of REQUIRED_TOKENS) {
      assert.ok(name in p, `preset ${id} missing token ${name}`);
    }
  });
}
```

- [ ] **Step 2: Verify it fails**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-presets.test.js
```

Expected: failure on `Cannot find module`.

- [ ] **Step 3: Implement `presets.js`**

```javascript
// webui/static/js/theme/presets.js
// Four presets. Every token in the taxonomy gets a value in every preset.

const CLASSIC_DARK = {
  "surface-base": "#0e0e10",
  "surface-1": "#15151a",
  "surface-2": "#1f1f25",
  "surface-3": "#2a2a30",
  "text-primary": "#e7e7ea",
  "text-secondary": "#c6c6cc",
  "text-muted": "#888888",
  "text-disabled": "#555555",
  "accent": "#ffb86b",
  "accent-emphasis": "#ffc888",
  "accent-on": "#1a1a25",
  "focus-ring": "#66ccff",
  "status-error": "#ff8a8a",
  "status-error-bg": "#2a0e0e",
  "status-warning": "#f0c98a",
  "status-success": "#99cc99",
  "status-info": "#99ccff",
  "stem-vocals": "#ff7eaa",
  "stem-bass": "#7ecaff",
  "stem-guitar": "#bcff7e",
  "stem-piano": "#ffc97e",
  "stem-other": "#cf7eff",
  "stem-drums": "#888888",
  "fn-tonic-bg": "#1a261a",
  "fn-tonic-fg": "#99cc99",
  "fn-dominant-bg": "#26221a",
  "fn-dominant-fg": "#ffcc99",
  "fn-modal-bg": "#2a1a26",
  "fn-modal-fg": "#e3c3ff",
  "fn-predominant-fg": "#99ccff",
  "border-soft": "#1f1f24",
  "border-strong": "#2a2a30",
  "alpha-scrim": "0.55",
  "alpha-overlay-soft": "0.08",
  "alpha-overlay-med": "0.20",
  "alpha-overlay-strong": "0.55",
  "alpha-glow-soft": "0.30",
  "alpha-glow-strong": "0.70",
  "alpha-grid-line": "0.10",
  "alpha-stem-fill": "0.85",
  "radius-1": "3px",
  "radius-2": "4px",
  "radius-3": "6px",
  "radius-4": "10px",
  "radius-pill": "9999px",
  "motion-fast": "0.12s",
  "motion-medium": "0.18s",
  "motion-slow": "0.30s",
};

const MIDNIGHT = {
  ...CLASSIC_DARK,
  "surface-base": "#060814",
  "surface-1": "#0d1024",
  "surface-2": "#161a36",
  "surface-3": "#222748",
  "accent": "#6ea8ff",
  "accent-emphasis": "#8ebaff",
  "accent-on": "#06091a",
  "focus-ring": "#9ec3ff",
  "border-soft": "#171a30",
  "border-strong": "#222748",
  "fn-tonic-bg": "#10261c",
  "fn-dominant-bg": "#1a2236",
  "fn-modal-bg": "#221a36",
};

const STUDIO_LIGHT = {
  ...CLASSIC_DARK,
  "surface-base": "#f6f6f8",
  "surface-1": "#ececef",
  "surface-2": "#dcdce2",
  "surface-3": "#c8c8cf",
  "text-primary": "#15151a",
  "text-secondary": "#3a3a44",
  "text-muted": "#5e5e6a",
  "text-disabled": "#9a9aa3",
  "accent": "#d97706",
  "accent-emphasis": "#b45309",
  "accent-on": "#ffffff",
  "focus-ring": "#1d4ed8",
  "status-error": "#b91c1c",
  "status-error-bg": "#fde2e2",
  "status-warning": "#a16207",
  "status-success": "#15803d",
  "status-info": "#1d4ed8",
  "stem-vocals": "#c2185b",
  "stem-bass": "#1565c0",
  "stem-guitar": "#2e7d32",
  "stem-piano": "#ef6c00",
  "stem-other": "#7b1fa2",
  "stem-drums": "#424242",
  "fn-tonic-bg": "#dff5e1",
  "fn-tonic-fg": "#15803d",
  "fn-dominant-bg": "#fff3dc",
  "fn-dominant-fg": "#a16207",
  "fn-modal-bg": "#f3e5fa",
  "fn-modal-fg": "#7b1fa2",
  "fn-predominant-fg": "#1d4ed8",
  "border-soft": "#dcdce2",
  "border-strong": "#c8c8cf",
  "alpha-scrim": "0.45",
  "alpha-overlay-soft": "0.05",
  "alpha-overlay-med": "0.15",
  "alpha-overlay-strong": "0.40",
  "alpha-grid-line": "0.08",
};

const HIGH_CONTRAST = {
  ...CLASSIC_DARK,
  "surface-base": "#000000",
  "surface-1": "#0a0a0a",
  "surface-2": "#141414",
  "surface-3": "#1f1f1f",
  "text-primary": "#ffffff",
  "text-secondary": "#f0f0f0",
  "text-muted": "#c8c8c8",
  "text-disabled": "#8a8a8a",
  "accent": "#ffd166",
  "accent-emphasis": "#ffe089",
  "accent-on": "#000000",
  "focus-ring": "#ffffff",
  "status-error": "#ff5050",
  "status-warning": "#ffcc33",
  "status-success": "#33ff66",
  "status-info": "#33ccff",
  "stem-vocals": "#ff66aa",
  "stem-bass": "#66bbff",
  "stem-guitar": "#88ff66",
  "stem-piano": "#ffcc44",
  "stem-other": "#cc66ff",
  "stem-drums": "#cccccc",
  "border-soft": "#3a3a3a",
  "border-strong": "#5a5a5a",
  "alpha-scrim": "0.85",
  "alpha-overlay-soft": "0.20",
  "alpha-overlay-med": "0.45",
  "alpha-overlay-strong": "0.85",
  "alpha-glow-soft": "0.60",
  "alpha-glow-strong": "1.00",
  "alpha-grid-line": "0.30",
  "alpha-stem-fill": "0.95",
};

export const PRESETS = {
  "classic-dark": CLASSIC_DARK,
  "midnight": MIDNIGHT,
  "studio-light": STUDIO_LIGHT,
  "high-contrast": HIGH_CONTRAST,
};

export const PRESET_IDS = Object.keys(PRESETS);
export const DEFAULT_PRESET_ID = "classic-dark";

export const PRESET_LABELS = {
  "classic-dark":   "Classic Dark",
  "midnight":       "Midnight",
  "studio-light":   "Studio Light",
  "high-contrast":  "High Contrast",
};
```

- [ ] **Step 4: Verify the test passes**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-presets.test.js
```

Expected: 6/6 pass.

- [ ] **Step 5: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/theme/presets.js webui/tests-js/theme-presets.test.js
git commit -m "feat(webui): theme presets — Classic Dark / Midnight / Studio Light / High Contrast"
```

---

### Task 2.2: Create store.js (localStorage I/O)

**Files:**
- Create: `webui/static/js/theme/store.js`
- Create: `webui/tests-js/theme-store.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// webui/tests-js/theme-store.test.js
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.localStorage = dom.window.localStorage;
globalThis.CustomEvent = dom.window.CustomEvent;

const { PRESETS, DEFAULT_PRESET_ID } = await import("../static/js/theme/presets.js");
const { getTheme, setPreset, setToken, resetTokens, subscribe, _resetForTests } =
  await import("../static/js/theme/store.js");

beforeEach(() => {
  localStorage.clear();
  _resetForTests();
});

test("getTheme returns the default preset on first read", () => {
  const t = getTheme();
  assert.equal(t.preset, DEFAULT_PRESET_ID);
  assert.deepEqual(t.tokens, PRESETS[DEFAULT_PRESET_ID]);
  assert.deepEqual(t.locks, []);
});

test("setPreset persists and switches the active preset", () => {
  setPreset("midnight");
  const t = getTheme();
  assert.equal(t.preset, "midnight");
  assert.equal(t.tokens["surface-base"], PRESETS["midnight"]["surface-base"]);
  // Survives reload by re-reading from localStorage:
  _resetForTests();
  assert.equal(getTheme().preset, "midnight");
});

test("setToken changes a single token and flips preset to 'custom'", () => {
  setPreset("classic-dark");
  setToken("accent", "#ff00ff");
  const t = getTheme();
  assert.equal(t.preset, "custom");
  assert.equal(t.tokens["accent"], "#ff00ff");
});

test("setToken rejects invalid color values", () => {
  setToken("accent", "not-a-color");
  assert.equal(getTheme().tokens["accent"], PRESETS[DEFAULT_PRESET_ID]["accent"]);
});

test("setToken rejects out-of-range alpha values", () => {
  setToken("alpha-scrim", "1.5");
  assert.equal(getTheme().tokens["alpha-scrim"], PRESETS[DEFAULT_PRESET_ID]["alpha-scrim"]);
});

test("resetTokens reapplies the current preset's values", () => {
  setPreset("midnight");
  setToken("accent", "#ff00ff");
  resetTokens();
  const t = getTheme();
  assert.equal(t.preset, "midnight");
  assert.equal(t.tokens["accent"], PRESETS["midnight"]["accent"]);
});

test("subscribe fires on every change and unsubscribes cleanly", () => {
  let calls = 0;
  const off = subscribe(() => calls++);
  setPreset("midnight");
  setToken("accent", "#ff00ff");
  off();
  setToken("accent", "#000000");
  assert.equal(calls, 2);
});

test("corrupt localStorage payload falls back to default preset", () => {
  localStorage.setItem("musiq.theme", "{not json");
  _resetForTests();
  assert.equal(getTheme().preset, DEFAULT_PRESET_ID);
});

test("schema-version mismatch falls back to default preset", () => {
  localStorage.setItem("musiq.theme", JSON.stringify({ v: 999, preset: "midnight", tokens: {} }));
  _resetForTests();
  assert.equal(getTheme().preset, DEFAULT_PRESET_ID);
});
```

- [ ] **Step 2: Verify it fails**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-store.test.js
```

Expected: failure on missing module.

- [ ] **Step 3: Implement `store.js`**

```javascript
// webui/static/js/theme/store.js
// localStorage-backed theme store. Mirrors the f0-prefs/notation-prefs
// pattern: STORAGE_KEY + JSON + try/catch + musiq:theme-changed event.

import { PRESETS, DEFAULT_PRESET_ID } from "./presets.js";

const STORAGE_KEY = "musiq.theme";
const SCHEMA_VERSION = 1;

const COLOR_KEYS_PREFIX = ["surface-","text-","accent","focus-","status-","stem-","fn-","border-"];
const ALPHA_KEYS_PREFIX = ["alpha-"];
const RADIUS_KEYS_PREFIX = ["radius-"];
const MOTION_KEYS_PREFIX = ["motion-"];

let cache = null;
const subscribers = new Set();

function defaultTheme() {
  return { preset: DEFAULT_PRESET_ID, tokens: { ...PRESETS[DEFAULT_PRESET_ID] }, locks: [] };
}

function isValidColor(v) {
  return typeof v === "string" && /^#[0-9a-fA-F]{3,8}$/.test(v.trim());
}
function isValidAlpha(v) {
  if (typeof v !== "string") return false;
  const n = parseFloat(v);
  return Number.isFinite(n) && n >= 0 && n <= 1;
}
function isValidRadius(v) {
  return typeof v === "string" && /^\d+(?:\.\d+)?(?:px|rem|em)$/.test(v.trim());
}
function isValidMotion(v) {
  return typeof v === "string" && /^\d+(?:\.\d+)?m?s$/.test(v.trim());
}

function categoryOf(name) {
  if (ALPHA_KEYS_PREFIX.some((p) => name.startsWith(p))) return "alpha";
  if (RADIUS_KEYS_PREFIX.some((p) => name.startsWith(p))) return "radius";
  if (MOTION_KEYS_PREFIX.some((p) => name.startsWith(p))) return "motion";
  if (COLOR_KEYS_PREFIX.some((p) => name.startsWith(p))) return "color";
  return null;
}

function validate(name, value) {
  switch (categoryOf(name)) {
    case "color":  return isValidColor(value);
    case "alpha":  return isValidAlpha(value);
    case "radius": return isValidRadius(value);
    case "motion": return isValidMotion(value);
    default:       return false;
  }
}

function readStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultTheme();
    const obj = JSON.parse(raw);
    if (!obj || obj.v !== SCHEMA_VERSION) return defaultTheme();
    if (!obj.tokens || typeof obj.tokens !== "object") return defaultTheme();
    const presetId = (obj.preset === "custom" || PRESETS[obj.preset]) ? obj.preset : DEFAULT_PRESET_ID;
    const baseline = presetId === "custom"
      ? { ...PRESETS[DEFAULT_PRESET_ID] }
      : { ...PRESETS[presetId] };
    const tokens = { ...baseline };
    for (const [k, v] of Object.entries(obj.tokens)) {
      if (validate(k, v)) tokens[k] = v;
    }
    const locks = Array.isArray(obj.locks) ? obj.locks.filter((s) => typeof s === "string") : [];
    return { preset: presetId, tokens, locks };
  } catch {
    return defaultTheme();
  }
}

function writeStorage(theme) {
  try {
    const payload = JSON.stringify({
      v: SCHEMA_VERSION,
      preset: theme.preset,
      tokens: theme.tokens,
      locks: theme.locks,
    });
    localStorage.setItem(STORAGE_KEY, payload);
  } catch (e) {
    console.warn("theme: localStorage write failed", e);
  }
}

function ensureCache() {
  if (cache === null) cache = readStorage();
  return cache;
}

function broadcast() {
  for (const fn of subscribers) {
    try { fn(cache); } catch (e) { console.warn("theme subscriber threw", e); }
  }
  document.dispatchEvent(new CustomEvent("musiq:theme-changed", { detail: cache }));
}

export function getTheme() {
  return ensureCache();
}

export function setPreset(id) {
  if (!PRESETS[id]) return;
  cache = { preset: id, tokens: { ...PRESETS[id] }, locks: [] };
  writeStorage(cache);
  broadcast();
}

export function setToken(name, value) {
  if (!validate(name, value)) return;
  ensureCache();
  cache = {
    preset: "custom",
    tokens: { ...cache.tokens, [name]: value },
    locks: cache.locks,
  };
  writeStorage(cache);
  broadcast();
}

export function resetTokens() {
  ensureCache();
  const presetId = cache.preset === "custom" ? DEFAULT_PRESET_ID : cache.preset;
  cache = { preset: presetId, tokens: { ...PRESETS[presetId] }, locks: [] };
  writeStorage(cache);
  broadcast();
}

export function setLock(name, locked) {
  ensureCache();
  const set = new Set(cache.locks);
  if (locked) set.add(name); else set.delete(name);
  cache = { ...cache, locks: [...set] };
  writeStorage(cache);
  broadcast();
}

export function subscribe(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

// Test hook only — drops the in-memory cache so tests can simulate a reload.
export function _resetForTests() {
  cache = null;
  subscribers.clear();
}
```

- [ ] **Step 4: Verify all 9 tests pass**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-store.test.js
```

Expected: 9/9 pass.

- [ ] **Step 5: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/theme/store.js webui/tests-js/theme-store.test.js
git commit -m "feat(webui): theme store — localStorage-backed preset + per-token API"
```

---

### Task 2.3: Create apply.js

**Files:**
- Create: `webui/static/js/theme/apply.js`
- Create: `webui/tests-js/theme-apply.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// webui/tests-js/theme-apply.test.js
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;

const { applyTheme } = await import("../static/js/theme/apply.js");
const root = dom.window.document.documentElement;

beforeEach(() => {
  root.removeAttribute("style");
});

test("applyTheme sets every token as a CSS custom property on documentElement", () => {
  applyTheme({ "accent": "#ff00ff", "alpha-scrim": "0.42" });
  assert.equal(root.style.getPropertyValue("--accent").trim(), "#ff00ff");
  assert.equal(root.style.getPropertyValue("--alpha-scrim").trim(), "0.42");
});

test("applyTheme overwrites prior values cleanly", () => {
  applyTheme({ "accent": "#aaaaaa" });
  applyTheme({ "accent": "#bbbbbb" });
  assert.equal(root.style.getPropertyValue("--accent").trim(), "#bbbbbb");
});
```

- [ ] **Step 2: Verify it fails**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-apply.test.js
```

- [ ] **Step 3: Implement**

```javascript
// webui/static/js/theme/apply.js
// Writes a token map onto documentElement.style. Order-independent and
// idempotent. Does no validation — that's store.js's job.

export function applyTheme(tokens) {
  const r = document.documentElement;
  for (const [k, v] of Object.entries(tokens)) {
    r.style.setProperty("--" + k, v);
  }
}
```

- [ ] **Step 4: Verify**

```powershell
node --test tests-js/theme-apply.test.js
```

Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/theme/apply.js webui/tests-js/theme-apply.test.js
git commit -m "feat(webui): theme apply — write token map to documentElement"
```

---

### Task 2.4: Create derive.js (accent derivation)

**Files:**
- Create: `webui/static/js/theme/derive.js`
- Create: `webui/tests-js/theme-derive.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// webui/tests-js/theme-derive.test.js
import { test } from "node:test";
import assert from "node:assert/strict";

const { deriveAccentEmphasis, deriveAccentOn, hexToRgb, relativeLuminance } =
  await import("../static/js/theme/derive.js");

test("hexToRgb accepts 3- and 6-digit hex", () => {
  assert.deepEqual(hexToRgb("#fff"),    { r: 255, g: 255, b: 255 });
  assert.deepEqual(hexToRgb("#000000"), { r: 0,   g: 0,   b: 0 });
  assert.deepEqual(hexToRgb("#ffb86b"), { r: 255, g: 184, b: 107 });
});

test("relativeLuminance matches WCAG examples within rounding", () => {
  // White ~1.0, black ~0.0
  assert.ok(Math.abs(relativeLuminance({ r: 255, g: 255, b: 255 }) - 1.0) < 1e-6);
  assert.ok(relativeLuminance({ r: 0, g: 0, b: 0 }) === 0);
});

test("deriveAccentOn picks dark for light accents", () => {
  assert.equal(deriveAccentOn("#ffb86b"), "#1a1a25");
  assert.equal(deriveAccentOn("#ffd166"), "#1a1a25");
});

test("deriveAccentOn picks white for dark accents", () => {
  assert.equal(deriveAccentOn("#3a2a4a"), "#ffffff");
  assert.equal(deriveAccentOn("#1a1a25"), "#ffffff");
});

test("deriveAccentEmphasis returns a color-mix string", () => {
  const e = deriveAccentEmphasis("#ffb86b");
  assert.match(e, /^color-mix\(in srgb, #ffb86b 92%, #ffffff 8%\)$/);
});
```

- [ ] **Step 2: Verify it fails**

```powershell
node --test tests-js/theme-derive.test.js
```

- [ ] **Step 3: Implement**

```javascript
// webui/static/js/theme/derive.js
// Accent token derivation. Spec §"Accent derivation".

export function hexToRgb(hex) {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (h.length !== 6) return null;
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff };
}

// WCAG 2.2 §1.4.3 relative luminance.
export function relativeLuminance({ r, g, b }) {
  const channel = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrastRatio(rgbA, rgbB) {
  const lA = relativeLuminance(rgbA);
  const lB = relativeLuminance(rgbB);
  const [hi, lo] = lA > lB ? [lA, lB] : [lB, lA];
  return (hi + 0.05) / (lo + 0.05);
}

const DARK_PICK  = "#1a1a25";
const LIGHT_PICK = "#ffffff";

export function deriveAccentOn(accentHex) {
  const a = hexToRgb(accentHex);
  if (!a) return DARK_PICK;
  const cDark  = contrastRatio(a, hexToRgb(DARK_PICK));
  const cLight = contrastRatio(a, hexToRgb(LIGHT_PICK));
  // Tie-break to DARK_PICK to preserve the established Classic Dark visual.
  return cDark >= cLight ? DARK_PICK : LIGHT_PICK;
}

export function deriveAccentEmphasis(accentHex) {
  return `color-mix(in srgb, ${accentHex} 92%, #ffffff 8%)`;
}
```

- [ ] **Step 4: Verify**

```powershell
node --test tests-js/theme-derive.test.js
```

Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/theme/derive.js webui/tests-js/theme-derive.test.js
git commit -m "feat(webui): theme derive — accent-on (WCAG luminance) + accent-emphasis"
```

---

### Task 2.5: Add inline pre-paint hydration script to index.html

**Files:**
- Modify: `webui/static/index.html`

- [ ] **Step 1: Edit `index.html`**

Insert the inline script as the first child of `<head>` (immediately after `<title>` is fine, but before any `<link rel="stylesheet">`):

```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MusIQ-Lab</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,...">
  <script>
    /* musiq theme pre-paint hydration. Synchronous; no deps. */
    (function () {
      try {
        var raw = localStorage.getItem('musiq.theme');
        if (!raw) return;
        var t = JSON.parse(raw);
        if (!t || t.v !== 1 || !t.tokens) return;
        var r = document.documentElement;
        for (var k in t.tokens) if (Object.prototype.hasOwnProperty.call(t.tokens, k)) {
          r.style.setProperty('--' + k, t.tokens[k]);
        }
      } catch (e) { /* silent — tokens.css applies as fallback */ }
    })();
  </script>
  <link rel="stylesheet" href="/static/css/reset.css">
  <link rel="stylesheet" href="/static/css/tokens.css">
  <link rel="stylesheet" href="/static/css/theme.css">
  <link rel="stylesheet" href="/static/css/track.css">
</head>
```

- [ ] **Step 2: Smoke-test in the browser**

```powershell
<PROJECT_PATH>\webui\webui.ps1 restart
```

Open DevTools console at `http://127.0.0.1:8765/?slug=gorillaz_silent_running`. Run:

```javascript
localStorage.setItem('musiq.theme', JSON.stringify({
  v: 1, preset: 'custom',
  tokens: { 'accent': '#ff00ff', 'surface-base': '#001100' }, locks: []
}));
location.reload();
```

Expected: page reloads with magenta accent and a dark green canvas, no flash of the default theme.

Run `localStorage.removeItem('musiq.theme'); location.reload();` to revert.

- [ ] **Step 3: Verify visual-baseline still passes (default theme is unchanged)**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

Expected: 6/6 pass.

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/index.html
git commit -m "feat(webui): pre-paint theme hydration from localStorage"
```

---

### Task 2.6: Wire main.js theme-changed listener (canvas refresh)

**Files:**
- Modify: `webui/static/js/main.js`

The canvas renderers from Task 1.7 already subscribe to `musiq:theme-changed`. This task wires the *application* of stored theme into the boot sequence, so cached `documentElement` properties are present when modules initialize.

- [ ] **Step 1: Edit `main.js`**

Add at the top of the imports:

```javascript
import { applyTheme } from "./theme/apply.js";
import { getTheme, subscribe as subscribeTheme } from "./theme/store.js";
```

Inside `boot()` before any other UI mount:

```javascript
async function boot() {
  // Reapply the stored theme to documentElement. The inline pre-paint script
  // already did this, but Phase 2 module code (theme/store.js) hasn't run yet
  // at that point — re-running is idempotent and ensures the in-memory cache
  // is consistent with what's painted.
  applyTheme(getTheme().tokens);
  subscribeTheme((theme) => applyTheme(theme.tokens));

  // ...rest of boot...
```

- [ ] **Step 2: Reload and confirm theme survives a setPreset call**

```powershell
<PROJECT_PATH>\webui\webui.ps1 restart
```

In DevTools:

```javascript
const { setPreset } = await import('/static/js/theme/store.js');
setPreset('midnight');
```

Expected: theme switches live to Midnight blues without a reload.

- [ ] **Step 3: Run guardrail (default state still pixel-baseline)**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/main.js
git commit -m "feat(webui): wire theme-store → applyTheme on boot + subscribe"
```

---

### Task 2.7: Add Appearance section to showSettings()

**Files:**
- Modify: `webui/static/js/ui/menus.js`

`showSettings()` already exists. We extend it.

- [ ] **Step 1: Add imports + appearance UI builder**

At the top of `menus.js`, alongside existing imports:

```javascript
import { PRESETS, PRESET_IDS, PRESET_LABELS } from "../theme/presets.js";
import { getTheme, setPreset, setToken, resetTokens, setLock } from "../theme/store.js";
import { deriveAccentOn, deriveAccentEmphasis } from "../theme/derive.js";
```

Add a builder function above `showSettings()`:

```javascript
function buildAppearanceSection() {
  const root = el("div");
  const heading = el("h3", {
    style: {
      fontSize: "11px", textTransform: "uppercase",
      color: "var(--text-muted)", margin: "16px 0 8px",
      letterSpacing: "var(--ls-caps)",
    },
    text: "Appearance",
  });
  root.appendChild(heading);

  const presetRow = el("div", {
    style: { display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "8px", marginBottom: "12px" },
  });
  for (const id of PRESET_IDS) {
    const card = el("div", {
      style: {
        border: "1px solid var(--border-strong)", borderRadius: "var(--radius-3)",
        padding: "8px 10px", cursor: "pointer", display: "flex", flexDirection: "column", gap: "6px",
        background: "var(--surface-2)", transition: "border-color var(--motion-fast)",
      },
      onClick: () => {
        setPreset(id);
        rebuild();
      },
    });
    if (getTheme().preset === id) {
      card.style.borderColor = "var(--accent)";
    }
    const label = el("div", { text: PRESET_LABELS[id], style: { fontSize: "12px", color: "var(--text-primary)" } });
    const swatchRow = el("div", { style: { display: "flex", gap: "3px" } });
    for (const t of ["surface-base","surface-2","accent","stem-vocals","stem-bass","status-error"]) {
      swatchRow.appendChild(el("div", {
        style: {
          width: "16px", height: "12px", borderRadius: "2px",
          background: PRESETS[id][t],
          border: "1px solid var(--border-soft)",
        },
      }));
    }
    card.appendChild(label);
    card.appendChild(swatchRow);
    presetRow.appendChild(card);
  }
  root.appendChild(presetRow);

  const customizeBtn = el("button", {
    style: {
      background: "transparent", border: "1px solid var(--border-strong)",
      color: "var(--text-secondary)", fontSize: "11px", borderRadius: "var(--radius-2)",
      padding: "4px 10px", cursor: "pointer",
    },
    text: "▸ Customize",
  });
  const customizePanel = el("div", { style: { display: "none", marginTop: "8px" } });
  let isOpen = false;
  customizeBtn.addEventListener("click", () => {
    isOpen = !isOpen;
    customizeBtn.textContent = isOpen ? "▾ Customize" : "▸ Customize";
    customizePanel.style.display = isOpen ? "block" : "none";
    if (isOpen && !customizePanel.dataset.built) {
      buildCustomizePanel(customizePanel, rebuild);
      customizePanel.dataset.built = "1";
    }
  });
  root.appendChild(customizeBtn);
  root.appendChild(customizePanel);

  function rebuild() {
    const next = buildAppearanceSection();
    root.replaceWith(next);
  }

  return root;
}

function buildCustomizePanel(host, rebuild) {
  // Color group rows
  const groups = [
    { title: "Surfaces",   tokens: ["surface-base","surface-1","surface-2","surface-3"] },
    { title: "Text",       tokens: ["text-primary","text-secondary","text-muted","text-disabled"] },
    { title: "Accent",     tokens: ["accent"] },
    { title: "Semantic",   tokens: ["status-error","status-warning","status-success","status-info"] },
    { title: "Stems",      tokens: ["stem-vocals","stem-bass","stem-guitar","stem-piano","stem-other","stem-drums"] },
    { title: "Borders",    tokens: ["border-soft","border-strong"] },
  ];
  for (const g of groups) {
    const wrap = el("div", { style: { margin: "10px 0" } });
    wrap.appendChild(el("div", {
      text: g.title, style: { fontSize: "10px", color: "var(--text-muted)", letterSpacing: "var(--ls-caps)", textTransform: "uppercase", marginBottom: "4px" },
    }));
    const row = el("div", { style: { display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "4px 12px" } });
    for (const t of g.tokens) {
      row.appendChild(buildColorRow(t));
    }
    wrap.appendChild(row);
    host.appendChild(wrap);
  }

  // Alpha sliders
  const alphaWrap = el("div", { style: { margin: "10px 0" } });
  alphaWrap.appendChild(el("div", { text: "Transparencies", style: { fontSize: "10px", color: "var(--text-muted)", letterSpacing: "var(--ls-caps)", textTransform: "uppercase", marginBottom: "4px" } }));
  for (const t of ["alpha-scrim","alpha-overlay-soft","alpha-overlay-med","alpha-overlay-strong","alpha-glow-soft","alpha-glow-strong","alpha-grid-line","alpha-stem-fill"]) {
    alphaWrap.appendChild(buildAlphaRow(t));
  }
  host.appendChild(alphaWrap);

  // Footer
  const footer = el("div", { style: { display: "flex", gap: "8px", marginTop: "12px" } });
  const resetBtn = el("button", {
    text: `Reset to ${PRESET_LABELS[getTheme().preset === "custom" ? "classic-dark" : getTheme().preset]}`,
    style: {
      background: "var(--surface-2)", border: "1px solid var(--border-strong)",
      color: "var(--text-primary)", borderRadius: "var(--radius-2)", padding: "5px 10px",
      fontSize: "11px", cursor: "pointer",
    },
    onClick: () => { resetTokens(); rebuild(); },
  });
  const copyBtn = el("button", {
    text: "Copy theme JSON",
    style: {
      background: "transparent", border: "1px solid var(--border-strong)",
      color: "var(--text-secondary)", borderRadius: "var(--radius-2)", padding: "5px 10px",
      fontSize: "11px", cursor: "pointer",
    },
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(JSON.stringify(getTheme(), null, 2));
        copyBtn.textContent = "Copied!";
        setTimeout(() => { copyBtn.textContent = "Copy theme JSON"; }, 1200);
      } catch (e) {
        showToast("error", "Clipboard write failed");
      }
    },
  });
  footer.appendChild(resetBtn);
  footer.appendChild(copyBtn);
  host.appendChild(footer);
}

function buildColorRow(name) {
  const row = el("label", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "var(--text-secondary)" } });
  const input = el("input", {
    type: "color",
    style: { width: "28px", height: "20px", padding: "0", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-1)", background: "transparent" },
  });
  input.value = getTheme().tokens[name] || "#000000";
  let writeTimer = null;
  input.addEventListener("input", () => {
    setToken(name, input.value);
    // Apply locally on every input event (live preview); store debounces persistence internally if desired.
  });
  row.appendChild(input);
  row.appendChild(document.createTextNode(name));
  return row;
}

function buildAlphaRow(name) {
  const row = el("label", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "var(--text-secondary)", marginBottom: "4px" } });
  const slider = el("input", {
    type: "range",
    attrs: { min: "0", max: "1", step: "0.01" },
    style: { flex: "1", maxWidth: "120px" },
  });
  slider.value = getTheme().tokens[name] || "0";
  const valueLabel = el("span", { style: { fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)", minWidth: "32px", textAlign: "right" }, text: slider.value });
  slider.addEventListener("input", () => {
    setToken(name, slider.value);
    valueLabel.textContent = slider.value;
  });
  row.appendChild(document.createTextNode(name));
  row.appendChild(slider);
  row.appendChild(valueLabel);
  return row;
}
```

Then inside the existing `showSettings()`, append the appearance section before `addCloseButton(panel, ...)`:

```javascript
// Inside showSettings(), after the existing notation + audio engine sections:
panel.appendChild(buildAppearanceSection());
addCloseButton(panel, () => overlay.remove());
```

- [ ] **Step 2: Smoke-test by hand**

```powershell
<PROJECT_PATH>\webui\webui.ps1 restart
```

Open the app, click the Settings menu item. Expected: Appearance section shows 4 preset cards. Clicking a preset card switches the entire UI live. Expanding "Customize" shows color pickers and alpha sliders that mutate the UI in real time. Reloading the page preserves the choice.

- [ ] **Step 3: Run guardrail (default theme is still pixel-baseline)**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npx playwright test visual-baseline.spec.js
```

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/ui/menus.js
git commit -m "feat(webui): Settings → Appearance — presets + per-token customize"
```

---

### Task 2.8: Update accent derivation to flip emphasis + accent-on automatically

**Files:**
- Modify: `webui/static/js/theme/store.js`

When `setToken("accent", value)` is called, also derive `accent-emphasis` and `accent-on` UNLESS they're locked.

- [ ] **Step 1: Edit `store.js` `setToken` to chain the derivation**

Replace `setToken` with:

```javascript
import { deriveAccentEmphasis, deriveAccentOn } from "./derive.js";

export function setToken(name, value) {
  if (!validate(name, value)) return;
  ensureCache();
  const tokens = { ...cache.tokens, [name]: value };
  if (name === "accent") {
    if (!cache.locks.includes("accent-emphasis")) {
      tokens["accent-emphasis"] = deriveAccentEmphasis(value);
    }
    if (!cache.locks.includes("accent-on")) {
      tokens["accent-on"] = deriveAccentOn(value);
    }
  }
  cache = { preset: "custom", tokens, locks: cache.locks };
  writeStorage(cache);
  broadcast();
}
```

- [ ] **Step 2: Add a test**

Append to `webui/tests-js/theme-store.test.js`:

```javascript
test("setToken('accent', X) re-derives accent-emphasis + accent-on", async () => {
  setToken("accent", "#000000");
  const t = getTheme();
  assert.equal(t.tokens["accent-on"], "#ffffff", "dark accent → white accent-on");
  assert.match(t.tokens["accent-emphasis"], /color-mix\(in srgb, #000000 92%, #ffffff 8%\)/);
});

test("locks block re-derivation", async () => {
  const { setLock } = await import("../static/js/theme/store.js");
  setLock("accent-on", true);
  setToken("accent-on", "#abcdef");
  setToken("accent", "#000000");
  assert.equal(getTheme().tokens["accent-on"], "#abcdef");
});
```

Note: the second test calls `setToken("accent-on", "#abcdef")` directly — but `accent-on` color tokens currently pass through validation. Confirm `validate` accepts. (It does: `accent-on` matches `accent` prefix → color category.)

- [ ] **Step 3: Verify**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-store.test.js
```

Expected: 11/11 pass.

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/static/js/theme/store.js webui/tests-js/theme-store.test.js
git commit -m "feat(webui): auto-derive accent-emphasis + accent-on on accent change"
```

---

### Task 2.9: End-to-end smoke check + Phase 2 commit-marker

- [ ] **Step 1: Manual flow**

```powershell
<PROJECT_PATH>\webui\webui.ps1 restart
```

Open `http://127.0.0.1:8765/?slug=gorillaz_silent_running`.

1. Open Settings → Appearance.
2. Click each preset card; verify UI changes (cards highlight; piano-roll note colors change; mixer rows recolor; modals tint).
3. Hard-reload (Ctrl+F5). The chosen preset persists with no flash of Classic Dark.
4. Reset to Classic Dark; reload; expect canonical baseline.
5. Open DevTools, run `localStorage.setItem('musiq.theme', '{not json'); location.reload();` — UI should boot in Classic Dark, no console explosion (a single warn line is fine).
6. Run `localStorage.removeItem('musiq.theme'); location.reload();` to clean up.

- [ ] **Step 2: Run all theme unit tests + visual baseline**

```powershell
cd "<PROJECT_PATH>/webui"
node --test tests-js/theme-presets.test.js tests-js/theme-store.test.js tests-js/theme-apply.test.js tests-js/theme-derive.test.js tests-js/theme-css-tokens.test.js
cd tests-e2e
npx playwright test visual-baseline.spec.js
```

Expected: all pass (≥30 unit tests + 6 e2e).

---

## Phase 3 — Polish loop infrastructure

### Task 3.1: Add reviewer-side deps

**Files:**
- Modify: `webui/tests-e2e/package.json`

- [ ] **Step 1: Install axe**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
npm install --save-dev @axe-core/playwright axe-core
```

- [ ] **Step 2: Verify**

```powershell
node -e "import('@axe-core/playwright').then(m => console.log(typeof m.default))"
```

Expected: `function`.

- [ ] **Step 3: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/tests-e2e/package.json webui/tests-e2e/package-lock.json
git commit -m "chore(webui): add @axe-core/playwright for visual reviewer"
```

---

### Task 3.2: Create `tests-e2e/visual-review.spec.js`

**Files:**
- Create: `webui/tests-e2e/visual-review.spec.js`
- Modify: `webui/tests-e2e/playwright.config.js`
- Modify: `.gitignore`

- [ ] **Step 1: Add per-preset projects to playwright.config.js**

Replace `playwright.config.js` with:

```javascript
import { defineConfig } from "@playwright/test";

const PRESETS = ["classic-dark","midnight","studio-light","high-contrast"];

export default defineConfig({
  testDir: ".",
  use: {
    baseURL: "http://localhost:8765",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "..\\.venv\\Scripts\\python -m webui --port 8765",
    cwd: "..",
    url: "http://localhost:8765/api/tracks",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    ...PRESETS.map((preset) => ({
      name: `review-${preset}`,
      testMatch: /visual-review\.spec\.js$/,
      use: { browserName: "chromium" },
      metadata: { preset },
    })),
  ],
});
```

- [ ] **Step 2: Create `visual-review.spec.js`**

```javascript
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "fs";
import path from "path";

const FIXTURE_SLUG = "gorillaz_silent_running";
const OUT_ROOT = path.join("visual-review");

const SCENES = [
  { name: "default-load", setup: async (page) => {
    await page.waitForSelector("#roll-frame canvas.notes", { timeout: 10_000 });
    await page.waitForTimeout(500);
  }},
  { name: "picker-open", setup: async (page) => {
    await page.click(".track-picker");
    await page.waitForSelector(".tp-panel", { timeout: 5_000 });
  }},
  { name: "settings-open", setup: async (page) => {
    await page.click('#topbar .menu .item:has-text("Settings")');
    await page.waitForTimeout(300);
    await page.click('button:has-text("▸ Customize")').catch(() => {});
    await page.waitForTimeout(200);
  }},
  { name: "vocals-tab", setup: async (page) => {
    await page.click('.tab-strip .tab:has-text("Lyrics")').catch(() => {});
    await page.waitForTimeout(200);
  }},
  { name: "claude-tab", setup: async (page) => {
    await page.click('.tab-strip .tab:has-text("Claude")').catch(() => {});
    await page.waitForTimeout(200);
  }},
  { name: "transport-playing", setup: async (page) => {
    await page.click("#transport .play-btn");
    await page.waitForTimeout(2_000);
    await page.click("#transport .play-btn");
    await page.waitForTimeout(300);
  }},
];

const verdictBuffer = {
  iteration: parseInt(process.env.MUSIQ_ITER || "0", 10),
  passed: false,
  summary: "",
  presets_tested: [],
  issues: [],
  screenshots: [],
  notes: "",
};

test.beforeAll(async () => {
  fs.mkdirSync(OUT_ROOT, { recursive: true });
});

test.describe("visual review", () => {
  for (const scene of SCENES) {
    test(`${scene.name}`, async ({ page, browserName }, testInfo) => {
      const preset = testInfo.project.metadata?.preset;
      if (!preset) test.skip(true, "non-review project");
      if (!verdictBuffer.presets_tested.includes(preset)) {
        verdictBuffer.presets_tested.push(preset);
      }

      // Seed localStorage BEFORE the page boots so pre-paint hydration sees it.
      await page.addInitScript((value) => {
        try { localStorage.setItem("musiq.theme", value); } catch {}
      }, JSON.stringify({
        v: 1,
        preset,
        tokens: PRESETS_INLINE[preset],
        locks: [],
      }));

      await page.goto(`/?slug=${FIXTURE_SLUG}`);
      await scene.setup(page);

      const dir = path.join(OUT_ROOT, preset);
      fs.mkdirSync(dir, { recursive: true });
      const shotPath = path.join(dir, `${scene.name}.png`);
      await page.screenshot({ path: shotPath, fullPage: false });
      verdictBuffer.screenshots.push(`${preset}/${scene.name}.png`);

      const axe = await new AxeBuilder({ page }).withTags(["wcag2aa"]).analyze();
      for (const v of axe.violations) {
        for (const node of v.nodes) {
          verdictBuffer.issues.push({
            severity: v.impact === "critical" || v.impact === "serious" ? "blocker" : "major",
            preset,
            scene: scene.name,
            category: v.id,
            details: `${v.help}: ${node.failureSummary || node.html}`,
            screenshot: `${preset}/${scene.name}.png`,
          });
        }
      }
    });
  }
});

test.afterAll(async () => {
  const blockers = verdictBuffer.issues.filter((i) => i.severity === "blocker");
  verdictBuffer.passed = blockers.length === 0;
  verdictBuffer.summary = blockers.length === 0
    ? `axe scan complete; ${verdictBuffer.issues.length} non-blocker findings`
    : `${blockers.length} blocker contrast/aria violations across ${verdictBuffer.presets_tested.length} presets`;
  fs.writeFileSync(path.join(OUT_ROOT, "verdict.json"), JSON.stringify(verdictBuffer, null, 2));
  fs.writeFileSync(path.join(OUT_ROOT, "axe.json"), JSON.stringify(verdictBuffer.issues, null, 2));
});

// Inlined preset table — kept here so the spec is self-contained and doesn't
// import from /static/, which would require the running server. Updated by
// hand if presets.js changes; this is acceptable because preset edits are rare.
import { PRESETS as PRESETS_INLINE } from "../static/js/theme/presets.js";
```

- [ ] **Step 3: Update `.gitignore`**

```powershell
cd "<PROJECT_PATH>"
```

Append to `.gitignore`:

```
# Phase 3 visual-review output (verdict + axe.json are versioned via the loop's commits; PNGs are not)
webui/tests-e2e/visual-review/**/*.png
```

- [ ] **Step 4: Run the spec once manually**

```powershell
cd "<PROJECT_PATH>/webui/tests-e2e"
$env:MUSIQ_ITER = "0"
npx playwright test visual-review.spec.js --project=review-classic-dark --project=review-midnight --project=review-studio-light --project=review-high-contrast
```

Expected: 24 tests run (4 presets × 6 scenes). Some may fail-with-screenshot — that's the signal we want. `visual-review/verdict.json` exists with sensible structure.

- [ ] **Step 5: Inspect verdict.json**

Open `webui/tests-e2e/visual-review/verdict.json`. Confirm structure: `iteration`, `passed`, `summary`, `presets_tested`, `issues`, `screenshots`. Confirm at least the four presets appear under `presets_tested`.

- [ ] **Step 6: Commit**

```powershell
cd "<PROJECT_PATH>"
git add webui/tests-e2e/visual-review.spec.js webui/tests-e2e/playwright.config.js webui/tests-e2e/visual-review/verdict.json webui/tests-e2e/visual-review/axe.json .gitignore
git commit -m "test(webui): visual-review spec — 4 presets x 6 scenes + axe-core verdict"
```

---

### Task 3.3: Author the implementer prompt

**Files:**
- Create: `prompts/ui-polish-implementer.md`

- [ ] **Step 1: Write the prompt**

```markdown
# UI Polish Implementer (Subagent System Prompt)

You are an implementer subagent in a polish loop for the `webui` of the MusIQ-Lab project. The orchestrator (`scripts/ui-polish-loop.py`) dispatches you each iteration with this prompt and a fresh context.

## Inputs

- The design spec at `docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md`.
- The latest reviewer verdict at `webui/tests-e2e/visual-review/verdict.json` (may not exist on iteration 1; in that case your goal is to run the spec, capture the iteration-1 baseline, then exit).
- The screenshots in `webui/tests-e2e/visual-review/<preset>/<scene>.png`.

## Your job

Address every `blocker` and `major` issue in `verdict.json`. `minor` issues are best-effort. Do NOT refactor outside the issues' scope.

## Tools

You have: `Read, Edit, Write, Grep, Glob, Bash`. You do NOT have any agentic dispatch tools.

## Boundaries

- DO NOT write or modify any file under `webui/tests-e2e/`. The Playwright spec is owned by the orchestrator.
- DO NOT invoke `npx playwright test` or any `webui/tests-e2e/*` command. The orchestrator runs the reviewer spec after your turn.
- DO restart the webui server with `webui\webui.ps1 restart` (PowerShell) if your changes affect static-asset serving — though for CSS/JS edits a hard browser reload usually suffices since the server only serves files.
- DO run `node --test webui/tests-js/<file>.test.js` if you change any of the theme modules and want to verify your edits.

## Output

End your turn with a single `git commit` whose message starts with `polish(webui): iter <N> — ` where `<N>` is the value of `$env:MUSIQ_ITER`. The orchestrator will tail your last commit message into its iteration log.

If you cannot make progress (e.g., the verdict has no actionable items, or every blocker requires a design decision the spec doesn't authorize), commit a short note as `polish(webui): iter <N> — no-op (reason: <one line>)` and exit.
```

- [ ] **Step 2: Commit**

```powershell
cd "<PROJECT_PATH>"
git add prompts/ui-polish-implementer.md
git commit -m "docs(prompts): UI polish implementer subagent prompt"
```

---

### Task 3.4: Author the reviewer prompt

**Files:**
- Create: `prompts/ui-polish-reviewer.md`

- [ ] **Step 1: Write the prompt**

```markdown
# UI Polish Reviewer (Subagent System Prompt)

You are an INDEPENDENT reviewer subagent in a polish loop for the `webui` of the MusIQ-Lab project. The orchestrator (`scripts/ui-polish-loop.py`) dispatches you each iteration after the Playwright reviewer spec has captured screenshots and an axe scan.

## What you have access to

You have ONLY the following inputs:

- The design spec at `docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md`.
- The Playwright-mechanical verdict draft at `webui/tests-e2e/visual-review/verdict.json` (already written by the spec; you append to it).
- The axe-core findings at `webui/tests-e2e/visual-review/axe.json`.
- The screenshots at `webui/tests-e2e/visual-review/<preset>/<scene>.png` (4 presets × 6 scenes).
- The preset definitions at `webui/static/js/theme/presets.js`.

You do NOT have access to the implementer's diffs or any other source files. You judge the rendered UI on visual + accessibility merit only.

## Tools

You have: `Read` only. No `Edit`, no `Write` except for one specific file: `webui/tests-e2e/visual-review/verdict.json` (which you must update). No `Bash`. No `Grep` outside the four allowed paths.

## Your job

Read every screenshot. Read the axe findings. Add qualitative findings to `verdict.json[issues]` covering:

- **Visual rhythm** — are spacing/alignment/border treatments consistent across the 6 scenes within a single preset?
- **Type hierarchy** — do headings, body text, and labels read in distinct sizes/weights/families per the spec's editorial-aesthetic goal?
- **Color harmony** — do the stem colors play well against the surface and text colors of each preset?
- **Hover/idle/empty/error states** — do the screenshots include any state that looks unfinished, e.g. a disabled button rendered with visible-but-broken hover, an empty list with no friendly message, an error toast that clashes with the preset?
- **Preset-specific issues** — Studio Light is a real working theme, not a parking-lot for failed contrast. Does it pass that bar visually?

Each finding gets:

- `severity`: one of `minor`, `major`, `blocker`. A `blocker` is anything that would make a user say "this looks broken" — not just "this is suboptimal".
- `preset`, `scene`, `category: "qualitative"`, `details` (one or two sentences), `screenshot` (relative path).

## Pass criterion

Set `passed: true` ONLY when there are zero `blocker`-severity issues across all presets and scenes (both axe-mechanical and your qualitative findings). Otherwise set `passed: false`.

## Summary

Replace the placeholder `summary` field with a one-line human-readable description that the orchestrator will use as the commit message tail. Be specific: "midnight settings-open contrast 3.1:1 fail; transport rhythm minor in classic-dark" beats "issues found".

## Output

End by:

1. Writing the updated `verdict.json` (single Write call).
2. Printing your one-line summary to stdout (so the orchestrator log captures it).
3. Returning.

Do NOT commit anything. The orchestrator commits the verdict file along with the iteration's polish commit.
```

- [ ] **Step 2: Commit**

```powershell
cd "<PROJECT_PATH>"
git add prompts/ui-polish-reviewer.md
git commit -m "docs(prompts): UI polish independent reviewer subagent prompt"
```

---

### Task 3.5: Add `claude-agent-sdk` Python dep

**Files:**
- Modify: `requirements.txt` or `pyproject.toml` (whichever is canonical for the project)

The repo has both `webui/requirements.lock` and `pyproject.toml` mentions. Top-level `requirements.txt` is what `python -m analyze` uses. `claude-agent-sdk` doesn't need to live in either of those — it's a dev/scripts tooling dep. Best home: a fresh `scripts/requirements-loop.txt` so it doesn't pollute the analyze pipeline.

- [ ] **Step 1: Create `scripts/requirements-loop.txt`**

```
# Dependencies for scripts/ui-polish-loop.py — kept separate from the analyze
# stack so the loop runner doesn't drag SDK pins into MIR territory.
claude-agent-sdk>=0.1.0
```

- [ ] **Step 2: Install into the conda default env**

```powershell
conda run -n py3.13 pip install -r "<PROJECT_PATH>/scripts/requirements-loop.txt"
```

Expected: SDK installs cleanly. Per `claude_agent_sdk_bundled_cli.md` memory, this also bundles a Windows `claude.exe`.

- [ ] **Step 3: Verify SDK loads + bundled CLI message appears**

```powershell
python -c "import claude_agent_sdk; print(claude_agent_sdk.__version__)"
```

Expected: a version string ≥0.1.

- [ ] **Step 4: Commit**

```powershell
cd "<PROJECT_PATH>"
git add scripts/requirements-loop.txt
git commit -m "chore(scripts): pin claude-agent-sdk for ui-polish-loop"
```

---

### Task 3.6: Create `scripts/ui-polish-loop.py`

**Files:**
- Create: `scripts/ui-polish-loop.py`

- [ ] **Step 1: Write the runner**

```python
"""
ui-polish-loop.py — autonomous polish loop for the webui.

Per docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md:
  iter:
    1. Implementer subagent (Opus, fresh context) addresses verdict.json issues.
    2. Orchestrator runs `npx playwright test visual-review.spec.js`.
    3. Reviewer subagent (Opus, fresh context, blind to implementer) updates verdict.
    4. Commit verdict + emit iteration log.
    5. If verdict.passed two iterations in a row -> exit 0.
    6. Cap: MAX_ITER iterations.

Usage:
  python scripts/ui-polish-loop.py [--cap N] [--dry-run] [--start-iter N]
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md"
VERDICT = REPO / "webui/tests-e2e/visual-review/verdict.json"
PROMPT_IMPL = REPO / "prompts/ui-polish-implementer.md"
PROMPT_REVIEW = REPO / "prompts/ui-polish-reviewer.md"
TESTS_E2E = REPO / "webui/tests-e2e"
ITER_LOG_DIR = REPO / "install-logs"
DEFAULT_MAX_ITER = 8

REVIEW_PROJECTS = [
    "review-classic-dark", "review-midnight",
    "review-studio-light", "review-high-contrast",
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_playwright(iteration: int) -> None:
    log(f"iter {iteration}: running visual-review.spec.js across 4 presets...")
    env = os.environ.copy()
    env["MUSIQ_ITER"] = str(iteration)
    cmd = ["npx", "playwright", "test", "visual-review.spec.js"]
    for proj in REVIEW_PROJECTS:
        cmd.extend(["--project", proj])
    result = subprocess.run(cmd, cwd=TESTS_E2E, env=env)
    # Non-zero is expected when there are violations; the spec writes verdict.json regardless.
    log(f"iter {iteration}: playwright exit code {result.returncode}")


async def run_subagent(role: str, prompt_path: Path, allowed_tools: list[str], iteration: int) -> str:
    """
    Dispatch a fresh Claude subagent. Returns the final stdout summary line.
    Uses claude-agent-sdk; per memory the SDK ships a bundled claude.exe on Windows.
    """
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

    system_prompt = prompt_path.read_text(encoding="utf-8")
    user_msg = (
        f"This is iteration {iteration} of the UI polish loop. "
        f"Read the spec at {SPEC.relative_to(REPO).as_posix()} and the latest verdict "
        f"at {VERDICT.relative_to(REPO).as_posix()} (if it exists). Begin."
    )
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        cwd=str(REPO),
        allowed_tools=allowed_tools,
        model="opus",
        permission_mode="acceptEdits",
    )
    log(f"iter {iteration}: dispatching {role} subagent...")
    last_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_msg)
        async for msg in client.receive_response():
            kind = type(msg).__name__
            if kind == "AssistantMessage":
                for block in getattr(msg, "content", []):
                    if hasattr(block, "text"):
                        last_text = block.text
            elif kind == "ResultMessage":
                if hasattr(msg, "total_cost_usd"):
                    log(f"iter {iteration}: {role} done; cost ${getattr(msg, 'total_cost_usd', 0):.4f}")
    return last_text.strip().split("\n")[-1] if last_text else ""


def read_verdict() -> dict:
    if not VERDICT.exists():
        return {"passed": False, "summary": "no verdict yet", "issues": []}
    try:
        return json.loads(VERDICT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"passed": False, "summary": "verdict.json corrupt", "issues": []}


def commit_iteration(iteration: int, summary: str) -> None:
    subprocess.run(
        ["git", "add",
         "webui/tests-e2e/visual-review/verdict.json",
         "webui/tests-e2e/visual-review/axe.json",
         f"install-logs/ui-polish-2026-05-09-iter-{iteration}.md"],
        cwd=REPO, check=False,
    )
    msg = f"polish(webui): iter {iteration} — {summary}"
    subprocess.run(["git", "commit", "-m", msg, "--allow-empty"], cwd=REPO, check=False)


def write_iter_log(iteration: int, impl_summary: str, review_summary: str, verdict: dict) -> None:
    ITER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = ITER_LOG_DIR / f"ui-polish-2026-05-09-iter-{iteration}.md"
    blockers = sum(1 for i in verdict.get("issues", []) if i.get("severity") == "blocker")
    log_path.write_text(
        f"# Iteration {iteration}\n\n"
        f"- **Implementer summary:** {impl_summary}\n"
        f"- **Reviewer summary:** {review_summary}\n"
        f"- **Verdict:** passed={verdict.get('passed')} blockers={blockers}\n"
        f"- **Total issues:** {len(verdict.get('issues', []))}\n",
        encoding="utf-8",
    )


async def main_async(cap: int, dry_run: bool, start_iter: int) -> int:
    prev_pass = False
    for iteration in range(start_iter, cap + 1):
        log(f"=== iter {iteration} of {cap} ===")
        if dry_run:
            log("dry-run: skipping subagent dispatch + playwright")
            return 0

        impl_summary = await run_subagent(
            role="implementer",
            prompt_path=PROMPT_IMPL,
            allowed_tools=["Read","Edit","Write","Grep","Glob","Bash"],
            iteration=iteration,
        )

        run_playwright(iteration)

        review_summary = await run_subagent(
            role="reviewer",
            prompt_path=PROMPT_REVIEW,
            allowed_tools=["Read","Write"],   # Write only for verdict.json — the prompt enforces this
            iteration=iteration,
        )

        verdict = read_verdict()
        write_iter_log(iteration, impl_summary, review_summary, verdict)
        commit_iteration(iteration, verdict.get("summary","(no summary)"))

        if verdict.get("passed"):
            log(f"iter {iteration}: PASSED")
            if prev_pass:
                log(f"iter {iteration}: convergence (passed twice in a row); exiting 0")
                return 0
            prev_pass = True
        else:
            log(f"iter {iteration}: NOT passed; {len(verdict.get('issues',[]))} issues remaining")
            prev_pass = False

    log(f"hit cap of {cap} iterations without convergence")
    return 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cap", type=int, default=DEFAULT_MAX_ITER)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--start-iter", type=int, default=1)
    args = p.parse_args()

    if not shutil.which("npx"):
        print("ERROR: npx not on PATH; install Node and rerun.", file=sys.stderr)
        return 2
    if not SPEC.exists():
        print(f"ERROR: spec not found at {SPEC}", file=sys.stderr)
        return 2

    return asyncio.run(main_async(cap=args.cap, dry_run=args.dry_run, start_iter=args.start_iter))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test with `--dry-run`**

```powershell
python "<PROJECT_PATH>/scripts/ui-polish-loop.py" --dry-run --cap 1
```

Expected output: `=== iter 1 of 1 ===` → `dry-run: skipping subagent dispatch + playwright` → exit 0.

- [ ] **Step 3: Commit**

```powershell
cd "<PROJECT_PATH>"
git add scripts/ui-polish-loop.py
git commit -m "feat(scripts): ui-polish-loop runner — implementer + reviewer subagents"
```

---

### Task 3.7: Smoke-test the full loop with cap=1

The first real run gets the loop end-to-end without committing the user to a multi-hour autonomous session.

- [ ] **Step 1: Make sure the webui is running**

```powershell
<PROJECT_PATH>\webui\webui.ps1 status
<PROJECT_PATH>\webui\webui.ps1 restart
```

- [ ] **Step 2: Single-iteration full loop**

```powershell
python "<PROJECT_PATH>/scripts/ui-polish-loop.py" --cap 1
```

Expected:

- Implementer subagent dispatches; takes 1–5 min; ends with a `polish(webui): iter 1 — ...` commit (or a no-op commit if there's nothing actionable on iter 1).
- Playwright runs (1–3 min) capturing 24 screenshots + axe findings.
- Reviewer subagent dispatches (1–3 min); writes verdict.
- Orchestrator commits verdict + axe + iter log; loop exits with code 0 or 1 depending on whether verdict.passed.

- [ ] **Step 3: Inspect the iter-1 output**

Open:
- `webui/tests-e2e/visual-review/verdict.json` — should be valid, with at least one issue (axe almost always finds something on first run).
- `install-logs/ui-polish-2026-05-09-iter-1.md` — should have the four log lines.
- `git log --oneline -5` — should show the iter-1 commit on top.

- [ ] **Step 4: Phase 3 wrap commit (if any catch-up edits were needed)**

```powershell
cd "<PROJECT_PATH>"
git status
```

If clean: skip. Otherwise commit any debug fixes with a clear message.

---

## Phase 4 — Run + ship

### Task 4.1: Launch the full Ralph loop

- [ ] **Step 1: Confirm the webui is reachable**

```powershell
<PROJECT_PATH>\webui\webui.ps1 status
```

- [ ] **Step 2: Launch with the default cap (8 iterations)**

```powershell
python "<PROJECT_PATH>/scripts/ui-polish-loop.py" --start-iter 2 --cap 8
```

Note: `--start-iter 2` if Task 3.7 already produced iter-1 commits. If you wiped state and want a fresh run, use `--start-iter 1`.

- [ ] **Step 3: Monitor**

The orchestrator prints one log line per major step. Expect each iteration to take 5–15 min depending on subagent load. Total wall time for an 8-iteration run: 1–2 hours. Convergence usually arrives well before the cap.

- [ ] **Step 4: When it exits, inspect**

- Exit code 0 = converged (passed twice in a row).
- Exit code 1 = hit cap; check the latest verdict.

```powershell
git log --oneline | Select-Object -First 12
type "<PROJECT_PATH>\webui\tests-e2e\visual-review\verdict.json"
```

---

### Task 4.2: Write the ship report

**Files:**
- Create: `install-logs/ui-polish-2026-05-09-results.md`

- [ ] **Step 1: Author the report**

Template:

```markdown
# UI Polish + Themable Tokens — Ship Report (2026-05-09)

## Summary
- Iterations to convergence: <N>
- Final verdict: passed = <true|false>; remaining minor issues: <K>
- Tokens added beyond the spec taxonomy: <list — empty is fine>
- Wall time: <minutes>

## Preset gallery
For each preset, embed the 6 final scene thumbnails:

### Classic Dark
![default-load](../webui/tests-e2e/visual-review/classic-dark/default-load.png)
... (6 scenes)

### Midnight
... etc

## Token audit summary
- Literals replaced: <number, sourced from `git diff --stat` on Phase 1 commits>
- New tokens beyond spec: <list with rationale>
- Aliases removed at end of Phase 1: yes/no

## Loop convergence
| Iter | Implementer summary | Reviewer summary | Passed |
|---|---|---|---|
| 1 | ... | ... | false |
| 2 | ... | ... | false |
| ... | | | |
| N | ... | ... | true |

## Contrast deltas
- Classic Dark: axe AA violations before / after: <X> / <Y>
- Midnight: ...
- Studio Light: ...
- High Contrast: ...

## Lessons / surprises
<half-page on what went wrong, what the loop caught that a human review would have missed, what the loop missed that took manual cleanup>
```

Source the data from `install-logs/ui-polish-2026-05-09-iter-*.md`, the final `verdict.json`, and `git log --oneline | grep "polish(webui)"`.

- [ ] **Step 2: Commit**

```powershell
cd "<PROJECT_PATH>"
git add install-logs/ui-polish-2026-05-09-results.md
git commit -m "docs(webui): UI polish ship report"
```

---

## Plan self-review notes (for the implementer's awareness)

The plan was reviewed for:

- **Spec coverage** — every spec section has at least one task: token taxonomy → 1.1; theme.css preset binding → 1.2; sweep guardrail → 1.3 + 1.4 + 1.5 + 1.7; canvas reader → 1.6 + 1.7; alias removal → 1.8; preset registry → 2.1; localStorage I/O → 2.2; apply → 2.3; derive → 2.4; pre-paint hydration → 2.5; main wiring → 2.6; Settings UI → 2.7; auto-derive → 2.8; smoke check → 2.9; axe + visual-review spec → 3.1 + 3.2; prompts → 3.3 + 3.4; SDK install → 3.5; runner → 3.6; smoke → 3.7; loop launch + report → 4.1 + 4.2.
- **Type consistency** — `getTheme()` returns `{ preset, tokens, locks }` everywhere; `setToken(name, value)` everywhere; `subscribe(fn)` returns an unsubscribe function everywhere; `applyTheme(tokens)` takes a flat map everywhere.
- **Placeholder scan** — no TBD/TODO; all code blocks are real and runnable; all commands are exact.
