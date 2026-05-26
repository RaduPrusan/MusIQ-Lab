# Piano-roll tooltip refinement — 2026-05-10

## Goal

Make the canvas hover tooltip informative "at a glance" — multiline, with frequency, and visually distinct between three contexts: empty grid, detected pitch (note), and detected drum hit. Add reciprocal feedback: the hovered detected event itself enlarges to 120% scale at full opacity. Surface tooltip prefs (show-delay, hover-effects toggle) plus the existing Customize tokens panel in Settings.

## Background

`webui/static/js/ui/inspector.js` currently builds a single-line tooltip via `textContent` plus a `pitch-label` DOM child for the pitch head/octave. There are three regions:

- chord strip — no tooltip
- piano roll — pitch + stem + t + scale degree + role
- drum lane — drum name + t + vel

Visual state today is just two modifier classes (`on-note`, `on-drum`) that swap the border color. There is no signal for "over a note vs. over the grid", and no frequency. Detected events render at fixed alpha — they don't react to the cursor.

## Tooltip content (multiline)

Each region produces a multi-row DOM (no `\n` + `pre-line` — DOM rows preserve the `<sub>` octave glyph wired through `pitch-label.js`).

### On a melodic note

```
F#4                       ← .tip-head  (large, accent-color)
369.99 Hz · MIDI 66       ← .tip-physics (mono, muted)
vocals · v=0.82           ← .tip-event
1.20s + 0.34s             ← .tip-timing  (start + duration)
5̂ · chord-tone            ← .tip-analysis  (scale_deg + role; only when present)
```

### On a drum hit

```
Snare                     ← .tip-head (error-color)
12.34s · v=0.78           ← .tip-timing
```

### Over the grid (no event)

```
G4                        ← .tip-head (text-secondary, signals "no event")
392.00 Hz · MIDI 67       ← .tip-physics
at 12.34s                 ← .tip-timing
```

### Over the drum lane (empty)

```
Snare lane                ← .tip-head (text-secondary)
12.34s                    ← .tip-timing
```

## Frequency

`midiToHz(midi) = 440 * 2 ** ((midi - 69) / 12)`. Display with 2 decimal places when < 1000 Hz, 1 decimal otherwise. Lives in `webui/static/js/music/notation.js` (alongside `splitPitchOctave`).

## Visual context distinction

CSS modifier classes on `.hover-tip`:

| State    | Class      | Border               | Header color      |
|----------|------------|----------------------|-------------------|
| grid     | `on-grid`  | `border-soft`        | `text-secondary`  |
| note     | `on-note`  | `accent`             | `accent`          |
| drum hit | `on-drum`  | `status-error`       | `status-error`    |

The tooltip already lives in `track.css:152-155`. Extend the rules; keep the existing `.show` opacity transition.

## Hover-enlarge effect

When the cursor sits on a detected note or drum hit, that event renders at 120% (around its center) with `globalAlpha = 1.0`. Mechanism:

1. `viewState` gains a `hoveredEvent` field: `null | {kind:"note"|"drum", stem, idx}`.
2. `Inspector._onMove` calls `viewState.update({hoveredEvent: ...})` after picking — null when no event matched.
3. `PianoRoll._drawNotes` checks `vs.hoveredEvent`; if it matches a note's stem+idx, draws it scaled around the note's vertical center with `globalAlpha = 1` instead of the dim/dyn product.
4. `PianoRoll._drawDrumLane` does the analogous check for `kind:"drum"`.

Because viewState's Proxy emits `change` on any assignment, the existing `dirty=true` repaint path picks up hover changes for free.

## Tooltip prefs (new module)

`webui/static/js/ui/tooltip-prefs.js` — mirror of `notation-prefs.js`.

- `getShowDelayMs()` → number, default `80`, clamped 0..500
- `setShowDelayMs(v)` → persists, updates CSS var `--tooltip-show-delay`, emits `musiq:tooltip-prefs-changed`
- `getEffectsEnabled()` → boolean, default `true`
- `setEffectsEnabled(v)` → persists, emits

Storage key: `musiq.tooltip` (single JSON blob).

Show-delay applies via CSS:

```css
#roll-frame .hover-tip { transition: opacity .08s var(--tooltip-show-delay, 0ms); }
```

When `effectsEnabled` is false, `Inspector` writes `hoveredEvent: null` even when on a note (so PianoRoll skips the 120% scale), and the tooltip skips its subtle `.show` scale-up.

## Settings panel additions

In `webui/static/js/ui/menus.js → buildAppearanceSection`:

1. **Tooltip subsection** — inserted between the preset cards row and the Customize button:
   - "Show delay" slider (0..500ms, step 10)
   - "Hover effects" checkbox (enlarge note to 120%, fade-in pop)
   - Section help text (matches the rest of the Customize style).
2. **Customize default-open** — flip `isOpen = true` and toggle initial label/visibility accordingly. The Customize panel was the second-most-used section on the spec sheet but hidden behind a click; default-open surfaces it as the user requested.

## Files touched

| File | Change |
|------|--------|
| `webui/static/js/music/notation.js` | + `midiToHz`, `formatHz` |
| `webui/static/js/ui/tooltip-prefs.js` | NEW: prefs module |
| `webui/static/js/ui/inspector.js` | Multiline DOM, frequency line, on-grid class, hovered-event signaling, prefs respect |
| `webui/static/js/render/pianoroll.js` | 120% scale + opacity 1.0 for hovered note + drum hit |
| `webui/static/js/view/view-state.js` | + `hoveredEvent: null` default |
| `webui/static/js/ui/menus.js` | Tooltip subsection in Appearance, Customize default-open |
| `webui/static/js/main.js` | Wire tooltip-prefs CSS var on init |
| `webui/static/css/track.css` | Multiline tooltip layout, on-grid modifier, transition-delay var |

## Validation

Independent agent dispatch (Playwright) covers:

1. Open the webui at `http://127.0.0.1:8765`, pick any analyzed track.
2. Hover the canvas over an empty grid cell → tooltip is multiline, has freq, has the `on-grid` class.
3. Hover over a vocals note → tooltip has `on-note` class, frequency present, the underlying note rectangle visibly expands.
4. Hover over the drum lane on a hit → tooltip has `on-drum` class, drum tick expands.
5. Open Settings → Appearance → Tooltip subsection visible with two controls; Customize panel open by default.
6. Bump show-delay to 300ms → re-hover → tooltip waits visibly before fading in.
7. Disable hover effects → re-hover note → no 120% expansion.
