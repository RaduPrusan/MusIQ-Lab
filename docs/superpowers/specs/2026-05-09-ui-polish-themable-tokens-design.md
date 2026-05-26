# webui — UI Polish + Themable Tokens (Design)

**Date:** 2026-05-09
**Scope:** finish the tokenization started on 2026-05-02; expose every color/transparency in Settings; persist in `localStorage` (mirroring the existing `f0-prefs.js` / `notation-prefs.js` pattern); ship a Ralph-driven implement→Playwright-review loop with Opus subagents.
**Server:** `127.0.0.1:8765` (already running locally)
**Test fixture:** Gorillaz — Silent Running ft. Adeleye Omotayo (already cached, used by `tests-e2e/`)

## Goal

Three things at once:

1. **Polish.** Take every hardcoded `#hex` and `rgba(...)` literal currently sprinkled across `webui/static/css/*.css` and inline JS styles (~168 occurrences across 13 files) and route them through a complete design-token system. Tighten typography rhythm, radii, and motion as we pass through each surface. Outcome: the UI looks deliberate and consistent, not stitched-together.
2. **Themable.** Expose the token layer in `Settings → Appearance`: a small set of presets plus per-token color pickers and transparency sliders. Edits apply live, persist in `localStorage`, and survive reloads with no flash of the default theme.
3. **Autonomous QA.** Drive the implementation with a Ralph loop where two Opus subagents — an *implementer* and an *independent reviewer* — alternate. The reviewer runs Playwright over every preset and every key UI scene, runs an axe-core contrast scan, and emits a structured verdict. The loop keeps going until the reviewer signs off twice in a row.

The 2026-05-02 polish session left a partial token layer (typography + spacing + elevation only). The user request — make all colors and transparencies configurable in Settings, persistent across reloads — extends that layer into a full theming system. Persistence lives in `localStorage` (the convention already in use elsewhere in the app), not cookies. Nothing is off-limits, including the canvas renderer in `static/js/render/` for places that paint fills/glows directly on `<canvas>` (those need numerical access to current token values, not CSS).

## Architecture

Four sequential phases. Each ends at a commit boundary; iterations 1..N inside Phase 3 each get their own commit so the loop's history is auditable.

| Phase | Output | Commit boundary |
|---|---|---|
| **1. Token expansion + audit** | `tokens.css` extended with color/alpha/radius/motion sections; default-theme bundle moved into `theme.css`; sweep replaces every literal in CSS + inline-JS styles with tokens. Visual diff vs. main: ≤0.5 % pixel difference per scene under the *Classic Dark* preset. | `refactor(webui): full design-token layer` |
| **2. Theme engine + Settings** | `static/js/theme/` package (preset registry, `localStorage` I/O, hydration helper, public `getTheme/setTheme/onChange` API) + Appearance section in existing Settings modal + pre-paint inline `<head>` script. | `feat(webui): user-configurable theme persisted in localStorage` |
| **3. Polish loop (Ralph)** | `scripts/ui-polish-loop.py` (claude-agent-sdk runner) + `prompts/ui-polish-{implementer,reviewer}.md` + `tests-e2e/visual-review.spec.js`. Each loop iteration commits its own `polish(webui): iter N — <one-line summary>`. | Per-iteration commits |
| **4. Wrap** | `install-logs/ui-polish-2026-05-09-results.md` ship report (final screenshots, contrast deltas, what was changed/why); minor manual touch-ups if reviewer flagged near-misses but didn't block. | `docs(webui): ui polish ship report` |

The HARD-GATE is at the end of this spec, not between phases — once approved, the loop runs unattended through Phase 3 and only stops on convergence or the iteration cap.

## Phase 1 — Token expansion + audit

### File layout

```
webui/static/css/
  reset.css        # unchanged
  tokens.css       # EXTENDED — full token surface; theme-agnostic
  theme.css        # REWRITTEN — applies the *Classic Dark* preset to the tokens
  track.css        # SWEPT — every literal becomes a var(--…)
```

### Token taxonomy

Tokens declared on `:root` in `tokens.css` with default values. They are the "shape" of the theme; presets (Phase 2) supply concrete colors that override them.

```css
:root {
  /* ---- Surfaces (background layers, base → most-elevated) ---- */
  --surface-base:        #0e0e10;   /* page background */
  --surface-1:           #15151a;   /* topbar, modals, sidebar */
  --surface-2:           #1f1f25;   /* cards, inputs, mixer rows */
  --surface-3:           #2a2a30;   /* dividers, hover state on surface-2 */

  /* ---- Text ---- */
  --text-primary:        #e7e7ea;
  --text-secondary:      #c6c6cc;
  --text-muted:          #888;
  --text-disabled:       #555;

  /* ---- Accent (warm amber, the brand color) ---- */
  --accent:              #ffb86b;
  --accent-emphasis:     #ffc888;   /* hover/active */
  --accent-on:           #1a1a25;   /* text/icon color when filled with --accent */

  /* ---- Focus ring ---- */
  --focus-ring:          #6cf;

  /* ---- Semantic ---- */
  --status-error:        #ff8a8a;
  --status-error-bg:     #2a0e0e;
  --status-warning:      #f0c98a;
  --status-success:      #9c9;
  --status-info:         #9cf;

  /* ---- Stems (already named, retained as-is for compatibility) ---- */
  --stem-vocals:         #ff7eaa;
  --stem-bass:           #7ecaff;
  --stem-guitar:         #bcff7e;
  --stem-piano:          #ffc97e;
  --stem-other:          #cf7eff;
  --stem-drums:          #888;

  /* ---- Harmonic-function colors ---- */
  --fn-tonic-bg:         #1a261a;   --fn-tonic-fg:       #9c9;
  --fn-dominant-bg:      #26221a;   --fn-dominant-fg:    #fc9;
  --fn-modal-bg:         #2a1a26;   --fn-modal-fg:       #e3c3ff;
  --fn-predominant-fg:   #9cf;      /* currently inline */

  /* ---- Borders ---- */
  --border-soft:         #1f1f24;
  --border-strong:       #2a2a30;

  /* ---- Alpha tokens (the headline user request — every transparency named) ---- */
  --alpha-scrim:         0.55;     /* modal backdrop */
  --alpha-overlay-soft:  0.08;     /* hover-row, hover-tip subtle wash */
  --alpha-overlay-med:   0.20;     /* minimap segs, loop band fill */
  --alpha-overlay-strong:0.55;     /* loop-band edges, track-pick selection */
  --alpha-glow-soft:     0.30;
  --alpha-glow-strong:   0.70;     /* playhead/minimap accent glow */
  --alpha-grid-line:     0.10;
  --alpha-stem-fill:     0.85;     /* piano-roll note fill (consumed by canvas) */

  /* ---- Radii ---- */
  --radius-1:            3px;      /* track-row, vol */
  --radius-2:            4px;      /* default buttons, badges, inputs */
  --radius-3:            6px;      /* cards, modals */
  --radius-4:            10px;     /* pills */
  --radius-pill:         9999px;   /* loop-chip */

  /* ---- Motion ---- */
  --motion-fast:         0.12s;
  --motion-medium:       0.18s;
  --motion-slow:         0.30s;
}
```

The existing typography/spacing/elevation tokens stay where they are; they only need additions if the audit surfaces a real gap.

**Backwards compatibility.** Old token names (`--bg-0..3`, `--fg-0..3`, `--c-vocals` etc.) are retained as aliases in `tokens.css` for one phase so the sweep can land in pieces:

```css
:root {
  --bg-0: var(--surface-base);
  --bg-1: var(--surface-1);
  /* ... */
  --c-vocals: var(--stem-vocals);
}
```

Aliases are deleted at end of Phase 1 once the sweep is complete. No two names exist simultaneously beyond the phase boundary.

### Sweep — what to replace

Targets, in priority order:

1. **`webui/static/css/track.css`** — the heavyweight (~150 of the 168 occurrences). Every literal hex becomes a token. Inline `rgba(...)` literals where the alpha channel matters become `color-mix(in srgb, var(--token) calc(var(--alpha-token) * 100%), transparent)` OR a pre-baked compound token if the same combo appears 3+ times.
2. **`webui/static/css/theme.css`** — gets rewritten as the *Classic Dark* preset application (concrete values assigned to surface/text/accent tokens).
3. **Inline JS styles** — `webui/static/js/ui/{menus,reanalyze,topbar,sidebar,track-picker,shortcuts,lyrics-tab,rename-modal}.js`, `webui/static/js/ui/analyze-{modal,shared}.js`, `webui/static/js/main.js`. Anything writing a literal color (`style: { color: "#ff8866" }`) gets replaced with `"var(--status-error)"` etc. Inline `rgba(0,0,0,.6)` for the modal scrim becomes a `--scrim` compound or a class.
4. **Canvas renderers** — `webui/static/js/render/pianoroll.js` and `webui/static/js/render/f0-overlay.js` paint to `<canvas>`, which can't read CSS variables natively. Add a tiny `static/js/theme/css-tokens.js` helper that returns `getComputedStyle(document.documentElement).getPropertyValue('--name').trim()` for the renderer's color reads, and rebinds on `musiq:theme-changed` events. Any numeric alpha read uses `parseFloat`.

### Visual-diff guardrail for Phase 1

Before merging Phase 1, the implementer runs a single Playwright pass that captures the same 6 scenes (see Phase 3) under the *Classic Dark* preset and compares to the baseline screenshots checked in beforehand. Diff threshold: ≤0.5% pixel difference per scene. Anything beyond that is a regression in the sweep, not an acceptable polish.

The audit notes (which token replaced which literal, plus any tokens that had to be added beyond the taxonomy above) land in `install-logs/ui-polish-2026-05-09-token-audit.md`.

## Phase 2 — Theme engine + Settings UI

### Module layout

```
webui/static/js/theme/
  presets.js       # 4 preset definitions: classic-dark, midnight, studio-light, high-contrast
  store.js         # localStorage I/O + getTheme/setTheme/subscribe — the public API
  apply.js         # writes a token map onto document.documentElement.style
  css-tokens.js    # canvas-side reader + change listener
  hydrate.js       # the inline-pre-paint variant — sourced into <head>
```

### Persistence — `localStorage` format

One key, `musiq.theme`, JSON-encoded. Mirrors the existing convention in `webui/static/js/music/{f0-prefs,notation-prefs}.js`: `STORAGE_KEY` constant, `JSON.parse`/`stringify`, defensive `try/catch` around every read/write, and a `document` `CustomEvent('musiq:theme-changed', { detail: theme })` fired on every change so non-module consumers (canvas renderers loaded earlier in the boot sequence) can attach.

```json
{
  "v": 1,
  "preset": "classic-dark",
  "tokens": {
    "surface-base": "#0e0e10",
    "surface-1": "#15151a",
    "...": "every token in the taxonomy, fully resolved",
    "alpha-overlay-med": "0.20"
  },
  "locks": ["accent-on"]
}
```

Rules:

- `v` is the schema version; mismatched/missing → fall back to default preset, log once to console.
- `preset` is one of the four preset IDs OR `"custom"` (set the moment the user touches any individual token).
- `tokens` is the **full resolved** token map — every token in the taxonomy with its current value. Storing the full map (rather than a sparse delta) keeps hydration trivial: read JSON, walk the map, set every property. There is no preset-table dependency at boot. The Settings UI's "Reset to <preset>" button re-applies the current preset definition (writing fresh values into `tokens`), which is also how a user picks up an upstream preset tweak after it ships.
- `locks` is a list of token names that the user has explicitly pinned against re-derivation (e.g. `accent-on` after they overrode it manually). Empty in the typical case.
- Values are strings, validated on read (color via `CSS.supports("color", v)`, alpha via `parseFloat 0..1`, radius via `^\d+(?:\.\d+)?(?:px|rem|em)$`, motion via `^\d+(?:\.\d+)?(?:s|ms)$`). Invalid values are dropped silently; the matching preset's value applies as fallback.

`localStorage` size: roughly 3–5 KB for the full token map. Multi-MB allowance; not a concern.

### Pre-paint hydration — anti-FOUC

Top of `<head>` in `webui/static/index.html`, **before** the stylesheet links:

```html
<script>
  /* musiq theme pre-paint hydration — synchronous, ASCII-clean, no deps. */
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
    } catch (e) { /* silent — default tokens.css applies as fallback */ }
  })();
</script>
```

Because `localStorage` is synchronously readable from inline `<script>` and the stored map is already fully resolved, the hydration script is self-contained — no preset table inlined into the HTML, no template-injection step on the FastAPI side, no second blocking request. A corrupt or partial entry hits the `try/catch` and the default token values from `tokens.css` apply unchanged.

The script intentionally reads `localStorage` *before* any stylesheet link is parsed. CSS custom properties are live: even though `tokens.css` declares the same properties slightly later in the parse stream, our inline `setProperty` calls on `documentElement.style` win (inline style beats stylesheet declarations), and the values were already on the element by the time the first pixel is painted.

### Settings UI — Appearance section

Added to existing `showSettings()` modal in `webui/static/js/ui/menus.js`. Three top-level controls plus a customize disclosure.

**Top of the section:**

```
APPEARANCE
[ Classic Dark ] [ Midnight ] [ Studio Light ] [ High Contrast ]
   ●               ○             ○                 ○
   sample-swatch   sample-swatch sample-swatch     sample-swatch

▸ Customize
```

Preset cards are radio-style; clicking one sets `preset`, clears `tokens` overrides, persists, dispatches `musiq:theme-changed`.

**The Customize disclosure** opens a scrollable panel with grouped controls:

| Group | Controls |
|---|---|
| Surfaces | 4 color pickers (`--surface-base/1/2/3`) |
| Text | 4 color pickers (`--text-primary/secondary/muted/disabled`) |
| Accent | 1 color picker (`--accent`); `--accent-emphasis` and `--accent-on` auto-derived (see "Accent derivation" below). User can override either via "advanced" sub-disclosure, which then locks that specific token against re-derivation on the next `--accent` change. |
| Semantic | 4 color pickers (`--status-error/warning/success/info`) |
| Stems | 6 swatches with click-to-edit color picker |
| Function colors | 3 fg/bg pairs |
| Borders | 2 color pickers |
| Transparencies | 8 sliders (0..1, two-decimal step) — each with a live numeric label and a tiny preview tile |
| Radii | 4 sliders (0..16 px) + pill (locked) |
| Motion | 3 sliders (0..0.6 s) |

Footer of the panel:

- `[ Reset to <preset name> ]` — clears `tokens` overrides
- `[ Copy theme JSON ]` — `navigator.clipboard.writeText(JSON.stringify(currentTheme, null, 2))`

All edits are debounced (100 ms idle) before the `localStorage` write + the `musiq:theme-changed` dispatch. Live preview is immediate (the `applyTheme` call runs on every input event, mutating `documentElement.style`); only the persistence and the broadcast are debounced.

### Accent derivation

When the user changes `--accent` and has not manually pinned the related tokens, the theme engine computes:

- `--accent-emphasis` = `color-mix(in srgb, var(--accent) 92%, white 8%)` (8 % lighter; clamps perceived hover-brightness regardless of accent hue).
- `--accent-on` = pick between `#1a1a25` (dark) and `#ffffff` (light) by computing the WCAG relative luminance of `--accent` and choosing whichever yields the higher contrast ratio against it. Implementation: standard `relativeLuminance(rgb)` from WCAG 2.2 Section 1.4.3; tie-break to `#1a1a25` since it matches the established Classic Dark visual.

If the user edits either token directly via the advanced sub-disclosure, the theme engine adds the token's name to the `locks` array in the stored payload (`locks: ["accent-on"]`) and stops re-deriving that token until the user clicks "Reset derived" in the same sub-disclosure, which removes the entry from `locks` and re-runs the derivation against the current `--accent`.

### Public API

```js
// webui/static/js/theme/store.js
import { PRESETS } from "./presets.js";
import { applyTheme } from "./apply.js";

export function getTheme();              // → { preset, tokens (sparse overrides), resolved (full map) }
export function setPreset(id);           // switches preset, clears overrides
export function setToken(name, value);   // edits one token; flips preset → "custom" if it wasn't already
export function resetTokens();           // clears overrides, keeps preset
export function subscribe(fn);           // returns unsubscribe; fired on every change
```

`subscribe` is also wired to fire a `document` `CustomEvent('musiq:theme-changed', { detail: theme })` so non-module consumers (canvas renderers loaded earlier in the boot sequence) can attach without importing the module.

### Preset definitions

Sketches (full hex maps live in `presets.js`):

- **Classic Dark** — current palette, refined. Warm amber accent on near-black canvas.
- **Midnight** — deeper, cooler. `--surface-base #060814`, `--accent #6ea8ff`.
- **Studio Light** — neutral whites/greys. `--surface-base #f6f6f8`, `--accent #d97706`. (Real working light theme, not a haystack of grey-on-grey — designed to pass axe contrast at AA.)
- **High Contrast** — pure black canvas, near-white text, saturated stem colors, full opacity on every alpha token (every `--alpha-*` ≥ 0.85). Designed to pass axe contrast at AAA.

## Phase 3 — Ralph loop with Opus subagents

### Files

```
scripts/ui-polish-loop.py            # the orchestrator
prompts/ui-polish-implementer.md     # subagent prompt — fresh context per iteration
prompts/ui-polish-reviewer.md        # subagent prompt — fresh context per iteration
tests-e2e/visual-review.spec.js      # captures screenshots + axe scan, writes verdict
tests-e2e/visual-review/             # output dir (gitignored except verdict.json)
  classic-dark/{scene}.png
  midnight/{scene}.png
  studio-light/{scene}.png
  high-contrast/{scene}.png
  axe.json
  verdict.json
```

### `visual-review.spec.js` — what the reviewer sees

For each preset × each scene:

| Scene | Setup |
|---|---|
| `default-load` | Open `?slug=<fixture>`; wait for piano roll first paint. |
| `picker-open` | Click track-picker; wait for `.tp-panel` visible. |
| `settings-open` | Open menus → Settings → expand Appearance + Customize. |
| `vocals-tab` | Click sidebar Vocals tab. |
| `claude-tab` | Click sidebar Claude tab. |
| `transport-playing` | Play 2 s, pause, screenshot at t=2.0. |

Steps:

1. Read `process.env.MUSIQ_THEME_PRESET` (set per Playwright project).
2. `await context.addInitScript((payload) => { localStorage.setItem('musiq.theme', payload); }, JSON.stringify({ v: 1, preset, tokens: PRESETS[preset], locks: [] }));` — `addInitScript` runs before any page script, so the inline `<head>` hydration sees the seeded value.
3. For each scene: navigate, set up state, full-page screenshot.
4. `axe-core` scan with `withTags(['wcag2aa']).analyze()`; aggregate violations.
5. Write `verdict.json`:

```json
{
  "iteration": 3,
  "passed": false,
  "summary": "midnight settings-open contrast fail; minor rhythm issue in transport bar",
  "presets_tested": ["classic-dark","midnight","studio-light","high-contrast"],
  "issues": [
    {
      "severity": "blocker",
      "preset": "midnight",
      "scene": "settings-open",
      "category": "contrast",
      "details": "axe color-contrast: text-secondary on surface-1 measured 3.1:1; AA requires 4.5:1",
      "screenshot": "midnight/settings-open.png"
    }
  ],
  "screenshots": [...],
  "notes": "..."
}
```

**`summary`** is a one-line human-readable string the orchestrator uses verbatim as its commit message tail. The reviewer subagent fills it; the mechanical pass writes a placeholder (`"axe scan complete; <N> contrast violations"`) which the reviewer then replaces if it adds qualitative findings.

The reviewer subagent (separate Claude) reads `verdict.json` + the screenshots and adds qualitative findings (visual rhythm, alignment, idle/empty/error states). Two layers of review:

- **Mechanical (axe + diff)** — Playwright spec, deterministic. Verdict drives a hard fail.
- **Qualitative (Opus reviewer)** — looks at screenshots like a designer would, flags rhythm/spacing/typography problems axe can't see.

The reviewer's qualitative findings are appended to `verdict.json`'s `issues` with `category: "qualitative"`, `severity: "minor"|"major"|"blocker"`.

### Loop runner — `scripts/ui-polish-loop.py`

```python
# Pseudocode
MAX_ITER = 8
prev_pass = False
for i in range(1, MAX_ITER + 1):
    run_implementer(spec_path, verdict_path_or_None, allowed_tools=["Read","Edit","Write","Grep","Glob","Bash"])
    subprocess.run(["npx","playwright","test","tests-e2e/visual-review.spec.js"], check=True)
    run_reviewer(verdict_path, screenshots_dir, allowed_tools=["Read"], read_scope=["tests-e2e/visual-review/"])
    verdict = json.load(open(verdict_path))
    git_commit(f"polish(webui): iter {i} — {verdict['summary']}")
    if verdict["passed"]:
        if prev_pass:
            sys.exit(0)
        prev_pass = True
    else:
        prev_pass = False
sys.exit(1)
```

- **Implementer subagent.** Opus, fresh context per iteration. Tools: `Read, Edit, Write, Grep, Glob, Bash`. Working directory: repo root. Cannot run Playwright itself (the runner does that).
- **Reviewer subagent.** Opus, fresh context per iteration. Tools: `Read` only, scoped to `tests-e2e/visual-review/`, `webui/static/css/tokens.css`, `webui/static/js/theme/presets.js`, and the spec doc. Cannot read the implementer's diffs, only the rendered output. This is the "independent" part.
- **SDK.** `claude-agent-sdk` in `claude_agent_sdk_bundled_cli.md`-mode (Windows). Streams stdout/cost to console. Iteration log written to `install-logs/ui-polish-2026-05-09-iter-N.md`.
- **Convergence rule.** Reviewer must output `passed: true` **two iterations in a row** before exit-success. Prevents single-pass fluke approvals; one extra iteration is cheap insurance.
- **Cap.** 8 iterations. Beyond that the loop exits with status 1 and a summary; user reviews and decides whether to re-launch with a tightened scope.

### Subagent prompt sketches

Both prompts live as Markdown files; the runner injects them as the `system` prompt for the SDK call.

`prompts/ui-polish-implementer.md`:

> You are an implementer subagent in a polish loop for `webui`. Read the spec at `docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md` and the most recent reviewer verdict at `tests-e2e/visual-review/verdict.json` (may not exist on iteration 1). Your job: address every `blocker` and `major` issue in the verdict; `minor` issues are best-effort. Do not refactor outside the issues' scope. Do not write or modify Playwright tests — `visual-review.spec.js` is owned by the orchestrator. Do not invoke `npx playwright test` or `webui/tests-e2e/*` yourself; the orchestrator runs them after your turn. Run `webui\webui.ps1 restart` if your changes need a server reload. End your turn after a single `git commit` whose message starts with `polish(webui): iter <N> — `.

`prompts/ui-polish-reviewer.md`:

> You are an independent reviewer subagent. You have NOT seen the implementer's code changes. Your inputs are: the spec, the screenshots in `tests-e2e/visual-review/<preset>/<scene>.png`, the axe findings in `tests-e2e/visual-review/axe.json`. Read each screenshot and the corresponding axe entries. Add qualitative findings (visual rhythm, alignment, hover/idle/empty states, type hierarchy, color harmony) to `verdict.json` under `issues[]` with `category: "qualitative"` and a severity in {`minor`, `major`, `blocker`}. Set `passed: true` only when there are zero blocker-severity issues across all presets and scenes. End by writing the updated verdict file and a one-line summary to stdout.

## Phase 4 — Ship report

`install-logs/ui-polish-2026-05-09-results.md` covers, in order:

- Final preset gallery — 4 presets × 6 scenes, embedded thumbnails.
- Token audit summary: how many literals were replaced, how many tokens added beyond the taxonomy in this spec, with rationale per addition.
- Reviewer convergence: how many iterations, what each iteration fixed, final verdict file.
- Contrast deltas: before/after axe scores per preset.
- Lessons / surprises (the half-page that turns a one-off polish into reusable knowledge for the next session).

## Out of scope (YAGNI)

Explicitly **not** in this spec, even though they're tempting:

- **Day/night auto-switching** — Studio Light exists, but auto-switching by `prefers-color-scheme` adds complexity for low return. User can flip presets manually in Settings.
- **Per-track theme overrides** — theme is global. Adding per-track adds a second persistence layer and a confusing "why doesn't my theme apply" debugging surface.
- **Server-side theme storage** — `localStorage` only, per-browser per-origin. Themes don't roam between browsers; that's fine for a local-only app.
- **Theme import via paste / file upload** — Copy export is in scope (one-line to `clipboard`); import is omitted because parsing untrusted JSON adds validation surface for a feature few would use.
- **Color blindness simulators / palette generators** — axe contrast is sufficient. If we want this later, it's a discrete future spec.

## HARD-GATE

Implementation does not start until the user approves this design doc. Once approved, the writing-plans skill is invoked next; the resulting plan drives Phases 1 and 2 (manual-ish, with check-ins) and Phase 3 (`scripts/ui-polish-loop.py`, autonomous through to convergence or the cap).
