// webui/static/js/theme/presets.js
// Five presets (Classic Dark / Midnight / Studio Light / High Contrast / Jinn).
// Every preset enumerates every token in the taxonomy explicitly — no spread
// from another preset. This was enforced for JINN first (commit 499b20d) and
// extended to MIDNIGHT / STUDIO_LIGHT / HIGH_CONTRAST on 2026-05-10 so future
// edits to CLASSIC_DARK don't silently leak into the other presets.

const CLASSIC_DARK = {
  "surface-base": "#0e0e10",
  "surface-1": "#15151a",
  "surface-2": "#1f1f25",
  "surface-3": "#2a2a30",
  "text-primary": "#e7e7ea",
  "grid-line": "#e7e7ea",
  "text-secondary": "#c6c6cc",
  // text-muted/disabled bumped from #888/#555 so axe AA passes on every dark
  // surface. text-disabled bumped again 2026-05-09-iter-2 from #828288 → #92929a
  // because picker-rows render disabled text on --surface-selected (#1f1f28),
  // which gave 4.27:1 at the old value.
  "text-muted": "#a8a8b0",
  "text-disabled": "#92929a",
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
  // Shifted from #ffc97e (warm peach) → true orange. The old value was only
  // 2° hue + 4% lightness from --accent #ffb86b (warm amber), so piano stem
  // swatches/sliders/MIDI segments visually blurred into accent UI elements
  // (TRACK underline, accent-filled chips). The new value preserves piano's
  // "warm content" semantic while opening a clear hue gap (now ~16° from
  // accent). 2026-05-24.
  "stem-piano": "#ff9966",
  "stem-other": "#cf7eff",
  "stem-drums": "#888888",
  "drum-kick":    "#ff6b6b",
  "drum-snare":   "#ffd93d",
  "drum-toms":    "#cf7eff",
  "drum-hihat":   "#7eddff",
  "drum-cymbals": "#cccccc",
  "fn-tonic-bg": "#1a261a",
  "fn-tonic-fg": "#99cc99",
  "fn-dominant-bg": "#26221a",
  "fn-dominant-fg": "#ffcc99",
  "fn-modal-bg": "#2a1a26",
  "fn-modal-fg": "#e3c3ff",
  "fn-predominant-bg": "#1f262e",
  "fn-predominant-fg": "#99ccff",
  // Canvas chord-strip + drum-lane surfaces — these were hardcoded in
  // pianoroll.js until 2026-05-09-iter-2. Tokenizing them lets light /
  // midnight / HC presets repaint the strips without canvas refactors.
  "chord-default-bg": "#1a1a20",
  "chord-no-bg":      "#101014",
  "drum-lane-bg":     "#0e0e12",
  "border-soft": "#1f1f24",
  "border-strong": "#2a2a30",
  // Surface accents + chrome (newly tokenized 2026-05-09).
  "surface-selected": "#1f1f28",
  "surface-hover": "#1c1c22",
  "surface-hover-2": "#23232a",
  "surface-pill-hover": "#26262e",
  "picker-divider": "#16161a",
  "gutter-bg": "#101014",
  "gutter-row-bg": "#3a3a42",
  "gutter-row-black-bg": "#08080b",
  // Label colors for the regular (white-key) and black-key gutter rows.
  // Forked from --text-muted / --text-disabled in 2026-05-13 so the user
  // can tone the keyboard sidebar independently of body text.
  "gutter-row-fg":        "#a8a8b0",
  "gutter-row-black-fg":  "#92929a",
  // Label colors for the C row ("Do" absolute) and the song's detected
  // tonic. Vivid neon-green / hot-pink defaults make both anchors easy to
  // pick out at a glance against the muted default gutter labels. When the
  // C row and the tonic coincide (key of C), the tonic rule wins by CSS
  // order — song-specific signal beats universal anchor.
  "gutter-row-octave-fg": "#39ff14",
  "gutter-row-tonic-fg":  "#ff4ec1",
  // Soft semantic badge backgrounds.
  "accent-soft-bg": "#3a2a1a",
  "success-soft-bg": "#2a3a2a",
  "info-soft-bg": "#2a3a3a",
  "warn-soft-bg": "#3a2f1f",
  "modal-soft-bg": "#3a2a4a",
  "error-emphasis-bg": "#4a1a1a",
  "error-emphasis-bd": "#5a2a2a",
  "status-dot-loaded": "#66cc66",
  "status-dot-missing": "#cc4444",
  // Soft semantic foreground partners — in dark themes these mirror the
  // saturated headline colors since the soft-bg tile is dark enough to
  // support a saturated foreground. Studio Light overrides these.
  "accent-soft-fg": "#ffb86b",
  "success-soft-fg": "#99cc99",
  "info-soft-fg": "#99ccff",
  "warn-soft-fg": "#f0c98a",
  "modal-soft-fg": "#e3c3ff",
  // fn-bar overlay text (matches the saturated fn-color fills).
  "fn-on": "#0a0a0a",
  "alpha-scrim": "0.55",
  "alpha-overlay-soft": "0.08",
  "alpha-overlay-med": "0.20",
  "alpha-overlay-strong": "0.55",
  "alpha-glow-soft": "0.30",
  "alpha-glow-strong": "0.70",
  "alpha-grid-line": "0.10",
  "alpha-grid-bar": "0.13",
  "alpha-grid-beat": "0.06",
  "alpha-stem-fill": "0.85",
  // Loop-band overlays — drives both the canvas analyzed-loop bands
  // (pianoroll.js _drawLoopBands) and the minimap playback loop band
  // (track.css #minimap .loop-band). One pair tunes both.
  "alpha-loop-band-fill":   "0.05",
  "alpha-loop-band-stroke": "0.225",
  // User's playback-loop band on the canvas. By design brighter than the
  // analyzed bands above (pianoroll.js:369 design comment) so the user's
  // active selection reads as a deliberate marker, not background.
  "alpha-play-band-fill":   "0.10",
  "alpha-play-band-stroke": "0.55",
  // Multiplier on --text-primary for the canvas-painted bar-number labels
  // above each downbeat. Per-theme override exists for studio-light to
  // address the iter-4 minor: dark text @ 0.60 on cream perceptually
  // lighter than light text @ 0.60 on near-black. Studio Light bumps this
  // to 0.78 — still well within "secondary text" weight, but enough that
  // bar numerals stop reading as recessed.
  "alpha-bar-number": "0.60",
  // Canvas-painted F0 overlay strokes. Off-white consensus + teal PESTO
  // + neon-magenta FCPE are tuned for dark backgrounds; studio-light
  // overrides to dark inks.
  "f0-consensus-stroke": "#f0f0f0",
  "f0-fcpe-stroke":      "#ff00ff",
  "f0-pesto-stroke":     "#7eddff",
  // Mic overlay stroke colours + sidebar swatch. Four semantics:
  // in=matched, off=unmatched, neutral=matched-to-stem-but-silent,
  // no-match=match dropdown set to none. See mic-overlay.js.
  "mic-in":       "#7fdc20",
  "mic-off":      "#e7574a",
  "mic-neutral":  "#5ab4ff",
  "mic-no-match": "#a48cff",
  "radius-1": "3px",
  "radius-2": "4px",
  "radius-3": "6px",
  "radius-4": "10px",
  "radius-pill": "9999px",
  "motion-fast": "0.12s",
  "motion-medium": "0.18s",
  "motion-slow": "0.30s",
  // Type-size tokens (10/11/13/24 px tier system).
  "t-micro":   "10px",
  "t-body":    "11px",
  "t-prose":   "13px",
  "t-display": "24px",
};

const MIDNIGHT = {
  // Inherited from CLASSIC_DARK (formerly via spread; enumerated 2026-05-10
  // per the freeze-every-preset rule from JINN's 499b20d).
  "text-primary": "#e7e7ea",
  "grid-line": "#e7e7ea",
  "text-secondary": "#c6c6cc",
  "text-muted": "#a8a8b0",
  "text-disabled": "#92929a",
  "status-error": "#ff8a8a",
  "status-error-bg": "#2a0e0e",
  "status-warning": "#f0c98a",
  "status-success": "#99cc99",
  "status-info": "#99ccff",
  "stem-vocals": "#ff7eaa",
  // Bass shifted from cyan-blue (#7ecaff) → teal in Midnight specifically.
  // The dark default put bass at only 9° hue from --accent #6ea8ff, with
  // similar lightness — bass-coloured elements blurred into the cool-blue
  // accent UI throughout the chrome. Teal is the cleanest free hue slot
  // (none of the other Midnight tokens occupy 170-180°). Note that this is
  // unconventional for a bass stem (traditionally blue), but in Midnight's
  // blue-tinted palette ANY blue collides with accent — teal preserves the
  // "cool stem" feel while restoring clear differentiation. 2026-05-24.
  "stem-bass": "#2dc7c7",
  // Stems below are intentionally warm against Midnight's cool chrome —
  // not an oversight from the 2026-05-09 iter-2 cool-cohesion pass (which
  // reworked --fn-* + soft-bg/fg only). Warm stem fills act as "content"
  // colour against the cool "frame" colour, giving the canvas its visual
  // hierarchy. Don't recool these without intent.
  "stem-guitar": "#bcff7e",
  "stem-piano": "#ffc97e",
  "stem-other": "#cf7eff",
  "stem-drums": "#888888",
  "drum-kick":    "#ff6b6b",
  "drum-snare":   "#ffd93d",
  "drum-toms":    "#cf7eff",
  "drum-hihat":   "#7eddff",
  "drum-cymbals": "#cccccc",
  "status-dot-loaded": "#66cc66",
  "status-dot-missing": "#cc4444",
  "alpha-scrim": "0.55",
  "alpha-overlay-soft": "0.08",
  "alpha-overlay-med": "0.20",
  "alpha-overlay-strong": "0.55",
  "alpha-glow-soft": "0.30",
  "alpha-glow-strong": "0.70",
  "alpha-grid-line": "0.10",
  "alpha-grid-bar": "0.13",
  "alpha-grid-beat": "0.06",
  "alpha-stem-fill": "0.85",
  "alpha-loop-band-fill":   "0.05",
  "alpha-loop-band-stroke": "0.225",
  "alpha-play-band-fill":   "0.10",
  "alpha-play-band-stroke": "0.55",
  "alpha-bar-number": "0.60",
  "f0-consensus-stroke": "#f0f0f0",
  "f0-fcpe-stroke":      "#ff00ff",
  "f0-pesto-stroke":     "#7eddff",
  "mic-in":       "#7fdc20",
  "mic-off":      "#e7574a",
  "mic-neutral":  "#5ab4ff",
  "mic-no-match": "#a48cff",
  "radius-1": "3px",
  "radius-2": "4px",
  "radius-3": "6px",
  "radius-4": "10px",
  "radius-pill": "9999px",
  "motion-fast": "0.12s",
  "motion-medium": "0.18s",
  "motion-slow": "0.30s",
  // Midnight overrides:
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
  // fn-tonic-bg cooled from the warm-leaning #10261c (green-teal) to a
  // cool desaturated teal that shares hue with --fn-dominant-bg / Midnight's
  // surface family. Keeps the green semantic via fn-tonic-fg (#9cd9bf) while
  // staying in the cool hemisphere. Cohen-style cohesion fix from the
  // 2026-05-09 iter-2 verdict (midnight default-load minor).
  "fn-tonic-bg": "#0e2630",
  "fn-dominant-bg": "#1a2236",
  "fn-modal-bg": "#221a36",
  "fn-predominant-bg": "#101c2e",
  "chord-default-bg": "#0f132a",
  "chord-no-bg":      "#070a18",
  "drum-lane-bg":     "#070a18",
  // Tuned for midnight surfaces.
  "surface-selected": "#1a1f3c",
  "surface-hover": "#11142a",
  "surface-hover-2": "#1c2040",
  "surface-pill-hover": "#222848",
  "picker-divider": "#0d1124",
  "gutter-bg": "#080a18",
  "gutter-row-bg": "#2c3052",
  "gutter-row-black-bg": "#04050d",
  "gutter-row-fg":        "#a8a8b0",
  "gutter-row-black-fg":  "#92929a",
  "gutter-row-octave-fg": "#39ff14",
  "gutter-row-tonic-fg":  "#ff4ec1",
  "fn-on": "#06091a",
  // Cool-tinted soft-bg family — midnight previously inherited the warm
  // browns from CLASSIC_DARK via spread, breaking palette cohesion (the
  // amber loop band, warm topbar pills, warm picker buttons in the
  // 2026-05-09 iter-1 verdict). These pair with the cool blue --accent
  // (#6ea8ff). 2026-05-09-iter-2.
  "accent-soft-bg":      "#1a2440",
  "success-soft-bg":     "#1a2e2a",
  "info-soft-bg":        "#1a2a3a",
  "warn-soft-bg":        "#2a2638",
  "modal-soft-bg":       "#241a36",
  "error-emphasis-bg":   "#3a1a26",
  "error-emphasis-bd":   "#4a2238",
  // Cool soft foregrounds; mirror the cool headline accent on a tinted bg.
  "accent-soft-fg":      "#9ec3ff",
  "success-soft-fg":     "#9cd9bf",
  "info-soft-fg":        "#9ec5ff",
  "warn-soft-fg":        "#d6c2f0",
  "modal-soft-fg":       "#dcc3ff",
  // fn-fg colors for the harmony-function chips: same cool family.
  "fn-tonic-fg":         "#9cd9bf",
  "fn-dominant-fg":      "#9ec3ff",
  "fn-modal-fg":         "#dcc3ff",
  "fn-predominant-fg":   "#9ec5ff",
  // Type-size tokens (10/11/13/24 px tier system).
  "t-micro":   "10px",
  "t-body":    "11px",
  "t-prose":   "13px",
  "t-display": "24px",
};

const STUDIO_LIGHT = {
  // Inherited from CLASSIC_DARK (formerly via spread; enumerated 2026-05-10).
  // Studio Light overrides almost every visual token; only sizing/motion
  // tokens and three alpha-glow / alpha-stem-fill values are inherited.
  "alpha-glow-soft": "0.30",
  "alpha-glow-strong": "0.70",
  "alpha-stem-fill": "0.85",
  "radius-1": "3px",
  "radius-2": "4px",
  "radius-3": "6px",
  "radius-4": "10px",
  "radius-pill": "9999px",
  "motion-fast": "0.12s",
  "motion-medium": "0.18s",
  "motion-slow": "0.30s",
  // Studio Light overrides:
  "surface-base": "#f6f6f8",
  "surface-1": "#ececef",
  "surface-2": "#dcdce2",
  "surface-3": "#c8c8cf",
  "text-primary": "#15151a",
  "grid-line": "#15151a",
  "text-secondary": "#3a3a44",
  "text-muted": "#525258",      // bumped from #5e5e6a — needs 4.5:1 against
                                // surface-1/2 in light theme; #525258 on
                                // #ececef → 7.0:1, on #dcdce2 → 6.0:1.
  "text-disabled": "#4d4d52",   // darkened again 2026-05-09-iter-3 from
                                // #5a5a60 → #4d4d52. --surface-selected was
                                // bumped from #dcdce2 → #c8c8cf this round
                                // (verdict said the previous selected-row
                                // delta was too subtle). Old text-disabled on
                                // the new surface-selected was 4.08:1 (FAIL);
                                // #4d4d52 on #c8c8cf → 5.07:1, on #ececef →
                                // 7.14:1, on #f6f6f8 → 8.0:1. AA holds in
                                // every picker-row context.
                                //
                                // KNOWN TRADE-OFF: text-disabled (L≈0.080) is
                                // DARKER than text-muted (#525258, L≈0.091),
                                // inverting the usual visual hierarchy. On
                                // surface-base, disabled measures 7.4:1 while
                                // muted measures 6.8:1 — disabled reads MORE
                                // prominent than muted. This is structural,
                                // not a bug: any light-theme disabled colour
                                // light enough to feel "faded" (e.g. #92929a)
                                // would fail 4.5:1 on surface-selected
                                // (#c8c8cf → 2.47:1), and a chromatic shift
                                // can't widen the luminance gap without
                                // restructuring surface-selected away from
                                // achromatic grey. The "disabled" semantic is
                                // carried by italic/strikethrough/missing-marker
                                // in the consuming components (track.css:558,
                                // .tp-row .nm .warn font-style:italic), not
                                // by colour weight alone. Reviewed 2026-05-24.
  "accent": "#d97706",
  "accent-emphasis": "#b45309",
  // accent-on derived per spec §"Accent derivation": pick the higher-contrast
  // of #1a1a25 or #ffffff against --accent. For #d97706 (rel. luminance
  // ~0.247), dark text wins (~4.71:1 vs ~3.54:1). The 2026-05-09 iter-2 axe
  // scan caught the prior #ffffff value at 3.18:1 on the transport-playing
  // chip; aligning the static preset literal with deriveAccentOn() also
  // clears latent failures wherever else --accent-on is consumed at small
  // sizes (TRACK tab underline, accent-filled chips, focus glyphs).
  "accent-on": "#1a1a25",
  "focus-ring": "#1d4ed8",
  "status-error": "#b91c1c",
  "status-error-bg": "#fde2e2",
  "status-warning": "#854d0e",  // darkened from #a16207 — needed 4.5:1 on
                                // warn-soft-bg #fef3c7. Old value tested at
                                // 4.42:1 (axe 2026-05-09).
  "status-success": "#166534",  // darkened from #15803d so 4.5:1 holds on
                                // surface-1 (#ececef → 5.4:1).
  "status-info": "#1d4ed8",
  "stem-vocals": "#c2185b",
  "stem-bass": "#1565c0",
  "stem-guitar": "#2e7d32",
  "stem-piano": "#ef6c00",
  "stem-other": "#7b1fa2",
  "stem-drums": "#424242",
  // Drums re-derived for the light theme — the dark-default palette (red/
  // yellow/violet/cyan/grey above 0.5 luminance) fails 3:1 AA-non-text on
  // drum-lane-bg #ececef. Measured contrast on #ececef:
  //   kick   #d32f2f → ~5.3 : 1  (red 700)
  //   snare  #8b6914 → ~4.4 : 1  (dark mustard — yellow family but darkened)
  //   toms   #4527a0 → ~8.3 : 1  (deep indigo, distinct from stem-other #7b1fa2)
  //   hihat  #00838f → ~3.9 : 1  (teal 800, distinct from stem-bass #1565c0)
  //   cymbal #616161 → ~5.2 : 1  (grey 700, lighter than stem-drums #424242)
  // All pass AA-non-text; kick/toms/cymbals also pass AA body text (4.5:1).
  // 2026-05-24.
  "drum-kick":    "#d32f2f",
  "drum-snare":   "#8b6914",
  "drum-toms":    "#4527a0",
  "drum-hihat":   "#00838f",
  "drum-cymbals": "#616161",
  "fn-tonic-bg": "#dff5e1",
  "fn-tonic-fg": "#166534",
  "fn-dominant-bg": "#fff3dc",
  "fn-dominant-fg": "#854d0e",  // darkened from #a16207 → 4.5:1 on
                                // surface-1.
  "fn-modal-bg": "#f3e5fa",
  "fn-modal-fg": "#6b21a8",     // darkened from #7b1fa2.
  "fn-predominant-bg": "#dbeafe",
  "fn-predominant-fg": "#1d4ed8",
  // Light-theme chord-strip + drum-lane backgrounds — pale neutrals so
  // the saturated stem fills and chord-band tints read clearly above.
  "chord-default-bg": "#ececef",
  "chord-no-bg":      "#dcdce2",
  "drum-lane-bg":     "#ececef",
  "border-soft": "#dcdce2",
  "border-strong": "#c8c8cf",
  "alpha-scrim": "0.45",
  "alpha-overlay-soft": "0.05",
  "alpha-overlay-med": "0.15",
  "alpha-overlay-strong": "0.40",
  "alpha-grid-line": "0.10",
  "alpha-grid-bar": "0.13",
  "alpha-grid-beat": "0.06",
  "alpha-loop-band-fill":   "0.10",
  "alpha-loop-band-stroke": "0.40",
  "alpha-play-band-fill":   "0.15",
  "alpha-play-band-stroke": "0.55",
  // Surface chrome — light analogues of the dark literals.
  // surface-selected darkened 2026-05-09-iter-3 from #dcdce2 (= surface-2,
  // only ~3% luminance delta over surface-base) → #c8c8cf (= surface-3,
  // ~13% delta) so the picker's selected row reads at-a-glance without
  // relying solely on the 3px accent left rule. Verdict iter-2 minor.
  "surface-selected": "#c8c8cf",
  "surface-hover": "#ececef",
  "surface-hover-2": "#dcdce2",
  "surface-pill-hover": "#c8c8cf",
  "picker-divider": "#dcdce2",
  "gutter-bg": "#ececef",
  "gutter-row-bg": "#dcdce2",
  "gutter-row-black-bg": "#c8c8cf",
  "gutter-row-fg":        "#525258",
  "gutter-row-black-fg":  "#4d4d52",
  "gutter-row-octave-fg": "#1aa30a",
  "gutter-row-tonic-fg":  "#d11473",
  // Light soft badge backgrounds — pale tints so the dark fg text passes
  // contrast (this was the largest cluster of axe failures: dark text on
  // hardcoded dark soft-bg literals).
  "accent-soft-bg": "#fed7aa",   // for .tag.rn (accent text)
  "success-soft-bg": "#dcfce7",  // for status-success badges
  "info-soft-bg": "#dbeafe",     // for status-info / reanalyze quality btn
  "warn-soft-bg": "#fef3c7",
  "modal-soft-bg": "#f3e5fa",
  "error-emphasis-bg": "#fde2e2",
  "error-emphasis-bd": "#fca5a5",
  "status-dot-loaded": "#16a34a",
  "status-dot-missing": "#dc2626",
  // Soft semantic foregrounds — *darker than the headline color* in light
  // theme so the same .tag.rn / badge.q / loop-chip / etc. components clear
  // 4.5:1 against their pale tints. The 2026-05-09 axe scan flagged eight
  // separate elements rendering at 2.35:1 because they painted --accent
  // (#d97706) text on its own --accent-soft-bg (#fed7aa) tile.
  "accent-soft-fg":      "#7c2d12",  // 7.0:1 on #fed7aa; brand-warm chestnut.
  "success-soft-fg":     "#14532d",  // 6.7:1 on #dcfce7.
  "info-soft-fg":        "#1e3a8a",  // 8.4:1 on #dbeafe.
  "warn-soft-fg":        "#713f12",  // 7.7:1 on #fef3c7.
  "modal-soft-fg":       "#581c87",  // 7.4:1 on #f3e5fa.
  // White-on-saturated fills for the function bar in light theme.
  "fn-on": "#ffffff",
  // Bar-number contrast bump for the cream canvas — see token comment in
  // tokens.css. Iter-4 verdict flagged numerals as "slightly recessed".
  "alpha-bar-number": "0.78",
  // F0 overlay strokes on a light surface — the dark-theme values washed
  // out against #f6f6f8. Consensus = text-primary ink (matches body text
  // weight as a neutral reference line). PESTO raw stays cool but darker:
  // a denser blue that's still distinct from --stem-bass (#1565c0).
  "f0-consensus-stroke": "#15151a",
  "f0-fcpe-stroke":      "#ad1457",
  "f0-pesto-stroke":     "#0d47a1",
  // Mic colours: darker variants — the dark-theme greens/reds wash out
  // against the #f6f6f8 surface. Picked from Material 800-tier palettes.
  "mic-in":       "#2e7d32",
  "mic-off":      "#c62828",
  "mic-neutral":  "#1976d2",
  "mic-no-match": "#6a1b9a",
  // Type-size tokens (10/11/13/24 px tier system).
  "t-micro":   "10px",
  "t-body":    "11px",
  "t-prose":   "13px",
  "t-display": "24px",
};

const HIGH_CONTRAST = {
  // Inherited from CLASSIC_DARK (formerly via spread; enumerated 2026-05-10).
  "status-error-bg": "#2a0e0e",
  "alpha-bar-number": "0.60",
  "radius-1": "3px",
  "radius-2": "4px",
  "radius-3": "6px",
  "radius-4": "10px",
  "radius-pill": "9999px",
  "motion-fast": "0.12s",
  "motion-medium": "0.18s",
  "motion-slow": "0.30s",
  // High Contrast overrides:
  "surface-base": "#000000",
  "surface-1": "#0a0a0a",
  "surface-2": "#141414",
  "surface-3": "#1f1f1f",
  "text-primary": "#ffffff",
  "grid-line": "#ffffff",
  "text-secondary": "#f0f0f0",
  "text-muted": "#d6d6d6",     // bumped slightly — comfortably AAA on #000.
  "text-disabled": "#bababa",  // bumped — needs to clear 4.5:1 on
                               // --surface-selected (#1f1f1f) for picker-row
                               // sub-text in HC. #bababa → 8.5:1 there.
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
  // Shifted from #88ff66 (= fn-tonic-fg) → chartreuse. Keeps the green-family
  // semantic link to the tonic function (per the cross-axis stem↔fn hue map
  // used elsewhere in the system) while breaking the exact-hex collision that
  // made guitar piano-roll segments visually indistinguishable from tonic
  // chord-strip chips on the canvas. 2026-05-24.
  "stem-guitar": "#ccff66",
  "stem-piano": "#ffcc44",
  "stem-other": "#cc66ff",
  "stem-drums": "#cccccc",
  "drum-kick":    "#ff6b6b",
  "drum-snare":   "#ffd93d",
  "drum-toms":    "#cf7eff",
  "drum-hihat":   "#7eddff",
  "drum-cymbals": "#cccccc",
  // HC fn-fg colors take saturated AAA-friendly hues (these double as the
  // fn-bar segment fill, so they need to read well with --fn-on as text).
  "fn-tonic-fg": "#88ff66",
  "fn-dominant-fg": "#ffcc44",
  "fn-modal-fg": "#cc66ff",
  "fn-predominant-fg": "#33ccff",
  // HC canvas-strip backgrounds — saturated dark tints. Highlights pop
  // against #000 with the AAA-bumped alpha tokens.
  "fn-tonic-bg":      "#0a2a0a",
  "fn-dominant-bg":   "#2a1f00",
  "fn-modal-bg":      "#2a0a2a",
  "fn-predominant-bg":"#0a1a2a",
  "chord-default-bg": "#0a0a0a",
  "chord-no-bg":      "#000000",
  "drum-lane-bg":     "#000000",
  "border-soft": "#3a3a3a",
  "border-strong": "#5a5a5a",
  "alpha-scrim": "0.85",
  "alpha-overlay-soft": "0.20",
  "alpha-overlay-med": "0.45",
  "alpha-overlay-strong": "0.85",
  "alpha-glow-soft": "0.60",
  "alpha-glow-strong": "1.00",
  "alpha-grid-line": "0.10",
  "alpha-grid-bar": "0.13",
  "alpha-grid-beat": "0.06",
  "alpha-stem-fill": "0.95",
  "alpha-loop-band-fill":   "0.15",
  "alpha-loop-band-stroke": "0.85",
  "alpha-play-band-fill":   "0.20",
  "alpha-play-band-stroke": "0.95",
  // Surface chrome.
  "surface-selected": "#1f1f1f",
  "surface-hover": "#141414",
  "surface-hover-2": "#1f1f1f",
  "surface-pill-hover": "#2a2a2a",
  "picker-divider": "#3a3a3a",
  "gutter-bg": "#0a0a0a",
  "gutter-row-bg": "#2a2a2a",
  "gutter-row-black-bg": "#000000",
  "gutter-row-fg":        "#d6d6d6",
  "gutter-row-black-fg":  "#bababa",
  "gutter-row-octave-fg": "#39ff14",
  "gutter-row-tonic-fg":  "#ff4ec1",
  // Soft semantic backgrounds keep the dark base in HC; saturated fg colors
  // pop against them with very high ratios.
  "accent-soft-bg": "#3a2a1a",
  "success-soft-bg": "#1a2a1a",
  "info-soft-bg": "#1a2a3a",
  "warn-soft-bg": "#3a2f1f",
  "modal-soft-bg": "#2a1a3a",
  "error-emphasis-bg": "#5a1a1a",
  "error-emphasis-bd": "#ff5050",
  "status-dot-loaded": "#33ff66",
  "status-dot-missing": "#ff5050",
  // HC soft-fg = saturated headline; on the dark soft-bg tiles ratios
  // exceed 9:1 in every case.
  "accent-soft-fg":      "#ffd166",
  "success-soft-fg":     "#33ff66",
  "info-soft-fg":        "#33ccff",
  "warn-soft-fg":        "#ffcc33",
  "modal-soft-fg":       "#cc66ff",
  "fn-on": "#000000",
  // HC: pure white consensus + saturated cyan PESTO for AAA legibility
  // against the #000 canvas.
  "f0-consensus-stroke": "#ffffff",
  "f0-fcpe-stroke":      "#ff00ff",
  "f0-pesto-stroke":     "#66ddff",
  // Mic colours: saturated primaries for AAA legibility on the #000 canvas.
  // mic-no-match shifted from #cc66ff (= stem-other = fn-modal-fg) → mint.
  // The old value made the no-match overlay paint identically to the
  // "other"-stem MIDI notes it's drawn on top of when "other" was the
  // reference stem; mint occupies the otherwise-unused teal-green hue slot
  // and stays distinct from every stem AND every other mic colour. 2026-05-24.
  "mic-in":       "#00ff00",
  "mic-off":      "#ff4444",
  "mic-neutral":  "#66ddff",
  "mic-no-match": "#33ffaa",
  // Type-size tokens (10/11/13/24 px tier system).
  "t-micro":   "10px",
  "t-body":    "11px",
  "t-prose":   "13px",
  "t-display": "24px",
};

// User-saved theme; latest snapshot rebaked 2026-05-13 (gutter inversion:
// white-key rows on a black gutter, black-key rows on white, vivid green
// octave anchor). Frozen by design: NO spread from another preset, every
// token enumerated explicitly so future edits to Classic Dark / Midnight /
// etc. don't leak into Jinn. If you tweak Jinn live in Settings →
// Customize, then click "Copy theme JSON" again and re-bake here, do the
// same — full enumeration, no spread.
const JINN = {
  "surface-base": "#0e0e10",
  "surface-1": "#15151a",
  "surface-2": "#1f1f25",
  "surface-3": "#2a2a30",
  "text-primary": "#ffffff",
  "grid-line": "#ffffff",
  "text-secondary": "#c6c6cc",
  "text-muted": "#a8a8b0",
  "text-disabled": "#48484b",
  "accent": "#ffffff",
  "accent-emphasis": "#ffffff",   // baked from color-mix(srgb, #ffffff 92%, #ffffff 8%) so the picker validator accepts it
  "accent-on": "#1a1a25",
  "focus-ring": "#66ccff",
  "status-error": "#ff8a8a",
  "status-error-bg": "#2a0e0e",
  "status-warning": "#f0c98a",
  "status-success": "#99cc99",
  "status-info": "#99ccff",
  "stem-vocals": "#ffde66",
  "stem-bass": "#2e95f5",
  "stem-guitar": "#80ffdf",
  "stem-piano": "#ffb380",
  "stem-other": "#ff80fb",
  "stem-drums": "#ffffff",
  "drum-kick":    "#ff6b6b",
  "drum-snare":   "#ffd93d",
  "drum-toms":    "#cf7eff",
  "drum-hihat":   "#7eddff",
  "drum-cymbals": "#cccccc",
  "fn-tonic-bg": "#80a758",
  "fn-tonic-fg": "#85a65c",
  "fn-dominant-bg": "#2f7a93",
  "fn-dominant-fg": "#3f7a92",
  "fn-modal-bg": "#6e5388",
  "fn-modal-fg": "#6c5487",
  "fn-predominant-bg": "#599183",
  "fn-predominant-fg": "#629083",
  "chord-default-bg": "#1a1a20",
  "chord-no-bg": "#101014",
  "drum-lane-bg": "#0e0e12",
  "border-soft": "#1f1f24",
  "border-strong": "#2a2a30",
  "surface-selected": "#1f1f28",
  "surface-hover": "#1c1c22",
  "surface-hover-2": "#23232a",
  "surface-pill-hover": "#26262e",
  "picker-divider": "#16161a",
  "gutter-bg": "#000000",
  "gutter-row-bg": "#ffffff",
  "gutter-row-black-bg": "#000000",
  "gutter-row-fg":        "#000000",
  "gutter-row-black-fg":  "#ffffff",
  "gutter-row-octave-fg": "#199e10",
  "gutter-row-tonic-fg":  "#ff4ec1",
  "accent-soft-bg": "#3a2a1a",
  "success-soft-bg": "#2a3a2a",
  "info-soft-bg": "#2a3a3a",
  "warn-soft-bg": "#3a2f1f",
  "modal-soft-bg": "#3a2a4a",
  "error-emphasis-bg": "#4a1a1a",
  "error-emphasis-bd": "#5a2a2a",
  "status-dot-loaded": "#66cc66",
  "status-dot-missing": "#cc4444",
  "accent-soft-fg": "#ffb86b",
  "success-soft-fg": "#99cc99",
  "info-soft-fg": "#99ccff",
  "warn-soft-fg": "#f0c98a",
  "modal-soft-fg": "#e3c3ff",
  "fn-on": "#0a0a0a",
  "alpha-scrim": "0.55",
  "alpha-overlay-soft": "0.08",
  "alpha-overlay-med": "0.20",
  "alpha-overlay-strong": "0.55",
  "alpha-glow-soft": "0.30",
  "alpha-glow-strong": "0.85",
  "alpha-grid-line": "0.10",
  "alpha-grid-bar": "0.13",
  "alpha-grid-beat": "0.06",
  "alpha-stem-fill": "1",
  "alpha-loop-band-fill": "0.02",
  "alpha-loop-band-stroke": "0.08",
  "alpha-play-band-fill": "0.10",
  "alpha-play-band-stroke": "0.55",
  "alpha-bar-number": "0.60",
  "f0-consensus-stroke": "#f0f0f0",
  "f0-fcpe-stroke": "#ff00ff",
  "f0-pesto-stroke": "#7eddff",
  "mic-in":       "#7fdc20",
  "mic-off":      "#e7574a",
  "mic-neutral":  "#5ab4ff",
  "mic-no-match": "#80ff00",
  "radius-1": "3px",
  "radius-2": "4px",
  "radius-3": "6px",
  "radius-4": "10px",
  "radius-pill": "9999px",
  "motion-fast": "0.12s",
  "motion-medium": "0.18s",
  "motion-slow": "0.30s",
  // Type-size tokens (10/11/13/24 px tier system).
  "t-micro":   "10px",
  "t-body":    "11px",
  "t-prose":   "13px",
  "t-display": "24px",
};

export const PRESETS = {
  "classic-dark": CLASSIC_DARK,
  "midnight": MIDNIGHT,
  "studio-light": STUDIO_LIGHT,
  "high-contrast": HIGH_CONTRAST,
  "jinn": JINN,
};

export const PRESET_IDS = Object.keys(PRESETS);
export const DEFAULT_PRESET_ID = "jinn";

export const PRESET_LABELS = {
  "classic-dark":   "Classic Dark",
  "midnight":       "Midnight",
  "studio-light":   "Studio Light",
  "high-contrast":  "High Contrast",
  "jinn":           "Jinn",
};
