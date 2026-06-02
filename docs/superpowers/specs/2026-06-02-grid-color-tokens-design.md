# Configurable, distinct piano-roll grid color + transparency

**Date:** 2026-06-02
**Status:** Design approved, pending spec review
**Area:** webui — piano-roll canvas theming

## Problem

The piano-roll canvas grid (bar lines, beat lines, octave/diatonic row lines) is
not independently configurable:

- **Color** is derived from `--text-primary` via `hexToRgba()` in
  `webui/static/js/render/pianoroll.js` (`_readThemeCache`). There is no way to
  tint the grid distinctly from body text.
- **Opacity** is **hardcoded** in the renderer:
  - `t.barLine = hexToRgba(textPrimary, 0.13)` (line ~173)
  - `t.beatLine = hexToRgba(textPrimary, 0.06)` (line ~174)
  - `t.diatonicLine = hexToRgba(textPrimary, 0.10)` (line ~175)
- A `--alpha-grid-line` token exists (`tokens.css`, all 5 presets, surfaced in
  **Settings → Appearance → Transparencies**) but is **never read by any
  renderer** — it is a dead control. Dragging that slider currently changes
  nothing.

Goal: make the grid's color and transparency clearly configurable and distinct
from `--text-primary`, with **zero visual change on upgrade** (defaults reproduce
today's exact appearance).

## Scope

In scope (these follow the new grid color):

- Bar (downbeat) vertical lines — `t.barLine`
- Beat (sub-beat) vertical lines — `t.beatLine`
- Diatonic / octave horizontal row lines — `t.diatonicLine`

Out of scope (deliberately stay on `--text-primary`):

- Bar-number numerals (`t.beatNumberFg`) — these are *text*, not grid; they keep
  their existing `--alpha-bar-number` token.
- Chord-cell separators and chord-strip divider (`t.chordSep`,
  `t.chordStripDivider`) — part of the chord strip, not the grid.

Granularity (per user decision): **one color + two primary alphas** (bar, beat).
The diatonic line shares the grid color and reuses the existing (revived)
`--alpha-grid-line` token for its opacity.

## Token model

| Token | Kind | Default | Drives |
|---|---|---|---|
| `--grid-line` | color | per-preset = that preset's `--text-primary` | bar + beat + diatonic line color |
| `--alpha-grid-bar` | alpha | `0.13` | bar (downbeat) line opacity |
| `--alpha-grid-beat` | alpha | `0.06` | beat (sub-beat) line opacity |
| `--alpha-grid-line` | alpha | `0.10` (existing token, now consumed) | diatonic / octave line opacity |

### Design rationale

- **Decouple-without-flag-day.** `--grid-line` defaults to each preset's current
  `--text-primary` value, so the composited stroke colors are byte-identical to
  today until the user changes the token. The color is read once and composed
  with each alpha via the existing `hexToRgba()` helper, keeping hue and opacity
  orthogonal.
- **Revive, don't rename.** The dead `--alpha-grid-line` (default `0.10`) maps
  exactly to the diatonic line's current hardcoded `0.10`, so it becomes the
  diatonic-line opacity with no rename churn and no visual change.

## Per-preset defaults

`--grid-line` per preset = that preset's `--text-primary`:

| Preset | `--grid-line` default |
|---|---|
| classic-dark | `#e7e7ea` |
| midnight | `#e7e7ea` |
| studio-light | `#15151a` |
| high-contrast | `#ffffff` |
| jinn (DEFAULT) | `#ffffff` |

Alpha defaults are **uniform across all five presets**, matching today's
hardcoded literals:

- `--alpha-grid-bar` = `0.13`
- `--alpha-grid-beat` = `0.06`
- `--alpha-grid-line` = `0.10` — **normalized** in every preset.

### Normalization note (intentional behavior preservation)

`--alpha-grid-line` currently carries latent per-preset values that were never
rendered: **High Contrast `0.30`** and **Studio Light `0.08`**. Because the
renderer hardcoded `0.10` for the diatonic line regardless, those values never
affected pixels. Per the user's decision, all presets are **normalized to
`0.10`** so the diatonic line renders exactly as it does today in every theme.
(The latent HC/SL values are discarded — this is the explicit choice to keep the
upgrade visually inert, not an oversight.)

`tokens.css` `:root` base value for `--grid-line` mirrors the base
`--text-primary` (`#e7e7ea`).

## Implementation

### 1. `webui/static/css/tokens.css`

- Add a `--grid-line` color token (base `#e7e7ea`) in the piano-roll / canvas
  color region.
- Add `--alpha-grid-bar: 0.13;` and `--alpha-grid-beat: 0.06;` in the alpha-token
  block, next to the existing `--alpha-grid-line: 0.10;`.
- Update the `--alpha-grid-line` comment: it now drives the diatonic/octave line
  (no longer "generic / unused").

### 2. `webui/static/js/theme/presets.js`

For each of the 5 preset objects (`CLASSIC_DARK`, `MIDNIGHT`, `STUDIO_LIGHT`,
`HIGH_CONTRAST`, `JINN`):

- Add `"grid-line": <that preset's text-primary hex>` (table above).
- Add `"alpha-grid-bar": "0.13"`, `"alpha-grid-beat": "0.06"`.
- Set `"alpha-grid-line": "0.10"` (overwrites HC `0.30` and SL `0.08`).

### 3. `webui/static/js/render/pianoroll.js` — `_readThemeCache()`

```js
const gridLine = readToken("grid-line");
t.barLine      = hexToRgba(gridLine, readAlpha("alpha-grid-bar",  0.13));
t.beatLine     = hexToRgba(gridLine, readAlpha("alpha-grid-beat", 0.06));
t.diatonicLine = hexToRgba(gridLine, readAlpha("alpha-grid-line", 0.10));
```

`t.beatNumberFg` is unchanged (stays on `textPrimary` + `alpha-bar-number`). The
draw sites (`_drawGrid`, the diatonic-line stroke at ~line 464) already read
`this._theme.barLine / beatLine / diatonicLine`, so no draw-code change is
needed. The existing `musiq:theme-changed` listener re-runs `_readThemeCache()`,
so picker edits repaint live.

### 4. `webui/static/js/ui/menus.js` — Settings customizer groups

- **"Piano roll"** color group (`tokens: ["chord-default-bg","chord-no-bg","drum-lane-bg"]`):
  append `"grid-line"`. Update `help` to mention the grid-line color.
- **"Transparencies"** alpha group: add `"alpha-grid-bar"` and `"alpha-grid-beat"`
  alongside the existing `"alpha-grid-line"`. Reword `help` so the three grid
  alphas are individually labeled (bar / beat / octave-line).

### 5. `webui/tests-js/theme-presets.test.js`

Add to `REQUIRED_TOKENS`: `"grid-line"`, `"alpha-grid-bar"`, `"alpha-grid-beat"`
(`"alpha-grid-line"` is already present). This enforces that every preset defines
all four grid tokens, so the picker can never read `undefined`.

## Testing / verification

- **Unit:** `node --test` on `tests-js/` — token-parity test passes with the
  three new required tokens.
- **Manual (zero-change check):** restart webui, open a track. With default
  tokens, bar/beat/octave lines must look identical to pre-change in every preset
  (especially High Contrast and Studio Light, where the latent `alpha-grid-line`
  values were normalized).
- **Manual (configurability check):** Settings → Appearance → set `--grid-line`
  to a distinct hue (e.g. accent blue) and drag `alpha-grid-bar` /
  `alpha-grid-beat` / `alpha-grid-line` — the bar, beat, and octave lines must
  recolor / change opacity live and independently, while bar numbers and chord
  separators stay on text-primary.

## Out of scope / future

- Per-preset *tuning* of the new grid color (e.g. a deliberately tinted grid in a
  theme) — possible later by editing the preset hex; not part of this change.
- Separate color for bar vs beat lines (the rejected "fully separate" option).
