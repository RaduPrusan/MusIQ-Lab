# Phase 1 Token Audit (2026-05-09)

## Decisions where literal → token mapping was ambiguous or skipped

| File | Literal | Action | Rationale |
|---|---|---|---|
| track.css | `#3a2a4a` | kept literal | topbar `.badge.k` bg + `.tp-controls .pill.active` bg; per table: KEEP — no reuse elsewhere |
| track.css | `#2a3a3a` | kept literal | topbar `.badge.t` bg; per table: KEEP |
| track.css | `#2a3a2a` | kept literal | topbar `.badge.s` bg; per table: KEEP |
| track.css | `#3a2f1f` | kept literal | topbar `.badge.q` bg; per table: KEEP |
| track.css | `#f0c98a` | kept literal | topbar `.badge.q` text color; not in mapping table; warm-amber, no semantic token match; log for future `--status-queue-fg` or similar |
| track.css | `#9cf` (badge.t) | → `var(--status-info)` | `.badge.t` tempo badge text; `#9cf` in badge/text context maps to status-info per table guidance |
| track.css | `#9c9` (badge.s) | → `var(--status-success)` | `.badge.s` (scale) badge text; `.badge.s` background is clearly status-success context |
| track.css | `#23232a` | kept literal | `.track-picker:hover` + `.track-picker.open` bg; per table: hover-row accent background — KEEP |
| track.css | `rgba(102, 204, 255, 0.35)` | kept literal | `.tp-search input:focus` outline glow; focus-ring alpha variant, no token bucket for focus-ring alpha; log for possible `--alpha-focus-ring` token in 2.x |
| track.css | `#26262e` | kept literal | `.tp-controls .pill:hover` bg; per table: hover-row accent background — KEEP |
| track.css | `#16161a` | kept literal | `.tp-row` border-bottom; per table: hover-row accent background — KEEP |
| track.css | `#1c1c22` | kept literal | `.tp-row:hover` bg + `.track-row .vol` bg; per table: hover-row accent background — KEEP |
| track.css | `#1f1f28` | kept literal | `.tp-row.current` bg + `.track-row.highlighted` bg; per table: KEEP (candidate `--row-current-bg`) |
| track.css | `rgba(0,0,0,.4)` | kept literal | `#minimap .viewport` box-shadow; minimap-specific decorative shadow, not a modal scrim; table scrim rule applies to modal overlays only |
| track.css | `#101014` | kept literal | `#roll-frame .gutter` bg; per table: KEEP |
| track.css | `#3a3a42` | kept literal | `.gutter-row` white-key bg; not in mapping table; gutter-specific value, no semantic token match |
| track.css | `#000000` | kept literal | `.gutter-row` inset shadow bottom-border; pure black used as structural separator in canvas gutter; intentional pure-black |
| track.css | `#08080b` | kept literal | `.gutter-row.black` bg; per table: KEEP |
| track.css | `#f0f0f4` | kept literal | `.gutter-row.octave` text; near-white bright octave label; not in table; log for possible `--text-emphasis` |
| track.css | `rgba(15,15,20,.94)` | kept literal | `.hover-tip` bg; very dark near-opaque tooltip bg; not in table; unique value with no semantic equivalent |
| track.css | `#4a4a55` | kept literal | `.track-row .vol-fill` (unfilled track); per table: KEEP — unique to mixer vol unfilled-track |
| track.css | `#6c6` | kept literal | `.stem-loaded` status-dot; shorthand green; not exactly `--status-success` (#9c9) — different shade used for the dot specifically; log for unification |
| track.css | `#c44` | kept literal | `.stem-missing` status-dot + count color; shorthand error-red; not exactly `--status-error` — different shade for the dot/count; log for unification |
| track.css | `#9a9aa3` | → `var(--text-muted)` | `.gutter-row` text; per table: close enough to `#888`/`#888888`, map to `--text-muted` and log |
| track.css | `#3d3d44` | → `var(--text-disabled)` | `.gutter-row.black` text; per table: close enough to `#555`, map to `--text-disabled` and log |
| track.css | `#7eddff` | kept literal | `.f0-swatch-pesto` bg; PESTO f0 swatch color; not in mapping table; different from `--stem-bass` (`#7ecaff`) — intentionally distinct contour color |
| track.css | `#f0f0f0` | kept literal | `.f0-swatch-consensus` bg; consensus f0 swatch; near-white, distinct from `--text-primary`; intentional visual identity |
| track.css | `#0a0a0a` | kept literal | `.fn-bar-wide .fn-seg` text; per table: KEEP |
| track.css | `#3a2a1a` | kept literal | `.tag.rn` bg; per table: KEEP (candidate `--tag-roman-bg`) |
| track.css | `#2a3a4a` | kept literal | `.reanalyze-quality-btn.active` bg; per table: log and reanalyze — blue-tinted surface for active quality selection, no exact token; candidate `--surface-active-info` |
| track.css | `#4a1a1a` | kept literal | `.btn-confirm` bg; per table: KEEP — destructive-action warm-red set |
| track.css | `#5a2a2a` | kept literal | `.btn-confirm:hover` bg + `.toast-error` border; per table: KEEP — destructive-action warm-red set |
| track.css | `#2a0e0e` | kept literal | `.toast-error` bg; per table: KEEP — destructive-action warm-red set |
| track.css | `rgba(0, 0, 0, 0.4)` (lyrics menu) | kept literal | `.lyrics-refresh-menu` box-shadow; decorative shadow, not modal scrim; same reasoning as minimap viewport shadow above |
| track.css | `rgba(255,184,107,.06)` | kept literal | `.msg-assistant` bg; alpha .06 is below the `--alpha-overlay-soft` (~.05-.10) bucket but conceptually different — an intentionally subtle tint; log for possible dedicated token |
| track.css | `rgba(255,136,102,.10)` | kept literal | `.msg-error` bg; error-color alpha tint bg; no status-error alpha bucket token yet; log for `--status-error-bg` |
| track.css | `rgba(255,136,102,.08)` | kept literal | `.auth-card` bg; auth-error alpha tint; same as above |
| track.css | `rgba(255,136,102,.4)` | kept literal | `.auth-card` border; error-color alpha border; no token bucket yet |
| track.css | `rgba(255, 107, 107, 0.08)` | kept literal | `.rename-modal-error` bg; error alpha tint; same reasoning as msg-error bg |
| track.css | `#ddd` | → `var(--text-primary)` | `.track-row .name` text; per table: close enough, logged |
| track.css | `#ffaa99` | → `var(--status-error)` | `.auth-title`, `.auth-card .btn`; per table: `#ff8080`/`#ff8a8a`/`#ffaa99` family → `--status-error` |
| track.css | `#1a1a25` | → `var(--accent-on)` | `.claude-composer .btn` fg text on vocals-colored bg; per table `#1a1a25` → `var(--accent-on)` |
| track.css | `#9cf` (fn-predominant) | → `var(--fn-predominant-fg)` | `.tag.fn-predominant` color; function tag context clearly maps to `--fn-predominant-fg` |
| track.css | `#9cf` (reanalyze active) | → `var(--status-info)` | `.reanalyze-quality-btn.active` color; active quality button uses info-color accent, not a function-category context |
| track.css | `#6cf` (reanalyze active inset) | → `var(--focus-ring)` | `.reanalyze-quality-btn.active` box-shadow; bottom accent line on active quality btn; focus-ring color appropriate |

## Literals kept in CSS var() fallback positions (not swept)

| File | Location | Fallback literal | Reason |
|---|---|---|---|
| track.css | `var(--bg-1, #1a1a1a)` | `#1a1a1a` | CSS var fallback; token resolves correctly in all supported browsers; fallback is insurance only |
| track.css | `var(--bg-0, #0d0d0d)` | `#0d0d0d` | Same |
| track.css | `var(--c-vocals, #4a90e2)` | `#4a90e2` | Same |

## New tokens added beyond spec taxonomy

_(None — no new tokens were added in this sweep; all replacements used existing tokens from `tokens.css`.)_

## Task 1.5 — JS inline-style sweep (2026-05-09)

| File | Literal | Action | Rationale |
|---|---|---|---|
| main.js | `#ff8866` ×2 | → `var(--status-error)` | 404-unknown-track error message + showFatal(); error-red family → status-error |
| analyze-modal.js | `rgba(0,0,0,.75)` | → `rgb(0 0 0 / var(--alpha-scrim))` | modal overlay scrim; .75 rounds to scrim bucket (.55) — close enough for a blocking overlay |
| analyze-modal.js | `#ff6b6b` ×4 | → `var(--status-error)` | file-input error, yt-dlp stale message, `_renderError` heading + body |
| analyze-modal.js | `rgba(255,107,107,.12)` | → `rgb(255 107 107 / var(--alpha-overlay-soft))` | error banner bg tint; .12 alpha → soft bucket (.08), delta +0.04 within tolerance |
| analyze-shared.js | `#7eddff` (STATUS_COLOR.running) | → `var(--status-info)` | running-state chip color; `--status-info` = `#9cf` (close; `#7eddff` is slightly lighter but semantically info-blue) |
| analyze-shared.js | `#888` (STATUS_COLOR.cached) | → `var(--text-muted)` | cached-state chip color; `--text-muted` = `#888` exact match |
| analyze-shared.js | `#7ed881` (STATUS_COLOR.done) | → `var(--status-success)` | done-state chip color; `--status-success` = `#9c9` (slightly different green but same semantic) |
| analyze-shared.js | `#ff6b6b` (STATUS_COLOR.error) | → `var(--status-error)` | error-state chip color; error-red family |
| analyze-shared.js | `rgba(126,221,255,.12)` | → `rgb(126 221 255 / var(--alpha-overlay-soft))` | running-stage chip background tint; .12 → soft bucket (.08), delta +0.04 within tolerance |
| analyze-shared.js | `#ffd93d` | → `var(--status-warning)` | Warnings section heading; `--status-warning` = `#f0c98a` (warm amber; slightly different hue but same semantic intent) |
| menus.js | `rgba(0,0,0,.6)` | → `rgb(0 0 0 / var(--alpha-scrim))` | modalOverlay() scrim; .60 → scrim bucket (.55), delta +0.05 within tolerance |
| menus.js | `#ff8080` | → `var(--status-error)` | "Reanalyze (clear cache)" destructive action entry color; error-red family |
| reanalyze.js | `rgba(0,0,0,.75)` | → `rgb(0 0 0 / var(--alpha-scrim))` | modal overlay scrim; same as analyze-modal.js |
| reanalyze.js | `rgba(255,107,107,.12)` | → `rgb(255 107 107 / var(--alpha-overlay-soft))` | error banner bg; same as analyze-modal.js |
| reanalyze.js | `#ff6b6b` | → `var(--status-error)` | error banner border + text |
| shortcuts.js | `rgba(0,0,0,.6)` | → `rgb(0 0 0 / var(--alpha-scrim))` | shortcuts modal overlay scrim |
| sidebar.js | `#9cf` (predominant fnColors) | → `var(--fn-predominant-fg)` | function-bar predominant segment color; exact semantic match |
| sidebar.js | `#9c9` (scale text) | → `var(--status-success)` | SCALE label value text; `--status-success` = `#9c9` exact match |
| sidebar.js | `#e3c3ff` (mod-int text) | → `var(--fn-modal-fg)` | MOD-INT chord count text; `--fn-modal-fg` = `#e3c3ff` exact match |
| transport.js | `#9cf` (zoom slider fill) | → `var(--focus-ring)` | zoom-slider fill bar is a UI control indicator, not status text; `--focus-ring` = `#6cf` (close; same cyan family — control-indicator semantics fit better than `--status-info`) |

### Kept literals (ambiguous or intentional)

| File | Literal | Reason |
|---|---|---|
| analyze-modal.js | `white` (heading color, ×3 instances) | Explicit anchor-white for heading contrast on dark panels; same pattern as menus.js / reanalyze.js / shortcuts.js headings — keep `white` as intentional design anchor |
| reanalyze.js | `white` (heading color) | Same as above |
| shortcuts.js | `white` (heading color) | Same as above |
| menus.js | `white` (panel h2) | Same as above |

## Alpha bucket mapping decisions

| Original alpha | Bucket used | Token | Delta | Note |
|---|---|---|---|---|
| `.30` (minimap seg bg) | med | `--alpha-overlay-med` | 0 | exact match |
| `.55` (minimap seg border) | strong | `--alpha-overlay-strong` | 0 | exact match |
| `.60` (loop-band border) | strong | `--alpha-overlay-strong` | +0.05 | within 10% tolerance |
| `.18` (loop-band bg) | soft | `--alpha-overlay-soft` | varies | soft bucket covers low-alpha fills |
| `.10` (viewport bg) | soft | `--alpha-overlay-soft` | 0 | exact match |
| `.70` (play glow) | glow-strong | `--alpha-glow-strong` | 0 | exact match |
| `.70` (playhead glow) | glow-strong | `--alpha-glow-strong` | 0 | exact match |
| `.05` (hover-row bg) | soft | `--alpha-overlay-soft` | 0 | exact match |
| `.07` (gutter hovered bg) | soft | `--alpha-overlay-soft` | +0.02 | within tolerance |
| `.10` (hover-row borders) | soft | `--alpha-overlay-soft` | 0 | exact match |
| `.12` (loop-chip bg) | soft | `--alpha-overlay-soft` | +0.02 | within tolerance |
| `.22` (loop-chip hover) | med | `--alpha-overlay-med` | −0.08 | within 10% tolerance |
| `.35` (loop-chip border) | med | `--alpha-overlay-med` | +0.05 | within tolerance |
| `.55` (paste-overlay, rename-modal scrims) | scrim | `--alpha-scrim` | 0 | exact match |
| `.60` (rename-modal box-shadow) | scrim | `--alpha-scrim` | +0.05 | within tolerance; shadow context |
