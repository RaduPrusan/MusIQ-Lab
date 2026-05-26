# Live Mic-Pitch Layer — Ship Report (2026-05-22 → 2026-05-23)

> Spec: [`docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md`](../docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md)
>
> Plan: [`docs/superpowers/plans/2026-05-22-live-mic-pitch-layer.md`](../docs/superpowers/plans/2026-05-22-live-mic-pitch-layer.md)

## Summary

Browser-only "Live Input" pseudo-stem sitting above the six regular stem rows in the webui piano-roll sidebar. Captures from the user's microphone via Web Audio's `AudioWorkletNode`, runs a hand-rolled YIN estimator on 2048-sample blocks (~43 ms cadence at 48 kHz), feeds the result through a main-thread coordinator (`MicPitch`) that does time-alignment math against the WASAPI engine's `currentTime`, and renders the contour as a canvas overlay above `F0Overlay` on the piano-roll. Cents-off colouring vs a user-selectable reference stem; default `vocals`.

- **Plan tasks:** 24, fully executed via subagent-driven-development.
- **Total commits:** 29 between `3d8258c` (plan landed) and `041674c` (final visual polish).
- **Files added:** 4 production JS (mic-yin-processor, mic-pitch, mic-overlay, mic-row) + 1 CSS block + 5 test files + 1 e2e + 1 WAV fixture. ~830 LOC production, ~870 LOC tests.
- **Files modified (surgical):** `main.js` +29 lines, `sidebar.js` +17 lines, `CLAUDE.md` +1 paragraph.
- **Python changes:** zero. The feature is entirely browser-side.
- **Tests at end of ship:** 29 mic-related tests + 1 Playwright e2e — all pass.
- **Pre-existing baseline failure** in `tests-js/menus.test.js` (`Analyze-stale entry uses neutral color`) untouched; tracked separately.

## Bugs found-and-fixed during ship

Eight bugs total — six caught by the two-stage per-task code review (spec-compliance + quality), two caught by user manual smoke after the e2e was green.

| # | Severity | Bug | Caught by | Fix commit |
|---|---|---|---|---|
| 1 | Important | YIN CMND loop iterated `[1..tauMax]` but Step 1's difference function only filled `[tauMin..tauMax]`. Stale `d[1..tauMin-1]` from previous `process()` calls polluted the running denominator on every call after the first. Masked on first call by Float32Array zero-init. | Code review (Task 1-3) | `abbb3e9` |
| 2 | Important | `MicPitch._cents[i] = 0` collided with "perfectly in tune" for the no-reference case. Downstream `MicOverlay.centsToColourBucket(0)` would have returned `"in"` (green) instead of `"neutral"` for samples drawn without a reference. Now stores `NaN`. | Code review (Task 4-7) | `653311f` |
| 3 | Important | `MicPitch.start()` race: `_running` set only at the end of the async chain. A double-click on M acquired two concurrent `getUserMedia` streams; the second overwrote `_stream/_source/_node`, leaking the first stream + its mic indicator. Fixed with a `_starting` sentinel and `try/finally`. | Code review (Task 8) | `39fc974` |
| 4 | Important | `getUserMedia` `NotReadableError` (device hardware-busy — common with WASAPI Exclusive mode conflicts on this machine) mapped to `"unknown"`. Now maps to `"device-busy"` with user-meaningful text. | Code review (Task 8) | `39fc974` |
| 5 | Critical | `MicOverlay` `midiToY(...)` calls were missing the `+ CHORD_H` offset that `F0Overlay` applies on every call (`f0-overlay.js:183, 262`). The live ribbon would have rendered 48 px above its musically correct position, overlapping the chord strip. Spy test had silently been writing `NaN` Y values because the test viewState used the wrong field name (`scrollMidi` vs `midiCenter`) — fixed both. | Code review (Task 9-11) | `a434616` |
| 6 | Critical | `MicRow.mount()` re-subscribed `_onNotationChanged` (a fresh arrow per call) to `document` without removing the previous one. Each `setTrackData` call added one new live listener. After N track-changes, N redundant readout updates per notation-change event. | Code review (Task 12-15) | `a1602b5` |
| 7 | Critical | `MicOverlay` constructor subscribed an inline arrow to `MicPitch`'s `"sample"` event with no removal path. Every per-track `new MicOverlay(...)` instance stayed pinned by the closure on the long-lived `window.__musiqMic` singleton — same bug class as #6 in a different layer. Added `destroy()` + `micOverlay?.destroy()` in `main.js` before reassign. | Code review (Task 18) | `a8c5034` |
| 8 | Critical | Silence-gap bridging in `MicOverlay`: the renderer drew a polyline segment between every consecutive ring-buffer sample, regardless of the time gap. When the user stopped singing briefly and resumed at a different pitch, the ribbon drew a long diagonal across the silence — visually implying a slide that never happened. | User manual smoke | `dcd5c56` |
| 9 | Important | YIN hysteresis only caught DOWN-jumps below 80% of the previous freq. Single-frame octave-DOWN errors (sub-harmonic lock) escaped for one frame and made vertical spikes; octave-UP errors weren't caught at all. Made symmetric: reject any ratio outside `[0.55, 1.82]` for ≤2 frames. | User manual smoke (same screenshot as #8) | `dcd5c56` |
| 10 | Critical | `MicPitch._midi` ring buffer was `Uint8Array` with `Math.round(midiF)` at the push site — so every drawn pitch snapped to the nearest semitone, producing a visible staircase. The `"sample"` event detail was always a float (that's why the readout has always shown `"1174.7 Hz · MIDI 86"`); only the ring was wrong. Switched to `Float32Array`, removed the round. Public API contract change. | User manual smoke (Tuner.2 comparison screenshot) | `13f717d` |

Plus one visual polish pass after user feedback:

- `041674c` rebuilt `MicRow` on the existing `.track-row` 5-column grid instead of the original side-stem-row anatomy. The first version had oversized text, a standalone M button, status dot floating below, controls overflowing the panel width. Now sits as a peer of the six regular stems with a sub-meta line for Match/Offset.

## What worked

- **Subagent-driven decomposition.** Each chunk got a fresh implementer + two-stage review (spec compliance, then code quality). The reviewer caught 6 of the 8 in-loop bugs. Without the gate the feature would have shipped with all six.
- **`_attachForTest` seam in MicPitch.** Injectable engine + audioContext + workletFactory + getUserMedia let `node:test` exercise the full message path without an actual AudioWorklet. 12 unit tests cover the coordinator surface; the integration test walks a synthetic melody through the seam.
- **The two listener-leak bugs (#6, #7) were the same shape in different layers.** Catching it once in MicRow primed the reviewer to look for it in MicOverlay one chunk later — explicit pattern recognition across chunks worked.
- **Playwright e2e with `--use-file-for-fake-audio-capture`** passed on first run after the unit-level fixes — a strong "everything actually connects" signal.

## What didn't work

- **The plan's reference patterns weren't quite right twice.** I wrote `midiToY(m, vs, innerH)` instead of `midiToY(m, vs, innerH) + CHORD_H` in the MicOverlay plan, and chose `Uint8Array` for the ring's `midi` channel without thinking through that "1 byte saved per sample × 1024 samples" was nothing compared to the quantization cost. The reviewer caught #5 (CHORD_H); manual smoke caught #10 (Uint8). Plans benefit from cross-checking against the closest sibling code (F0Overlay's existing draw calls would have flagged the missing CHORD_H if I'd done a side-by-side comparison while writing the plan).
- **The initial visual style was wrong.** I designed the row anatomy (Row 1 header + Row 2 controls) without actually reading the existing `.track-row` grid definition in `track.css`. The first ship had to be redone to match the rest of the sidebar. A 10-minute look at the existing CSS before writing the spec would have avoided the rebuild.
- **`describe.skip` / silently failing tests.** The MicOverlay spy test passed despite drawing NaN Y values because the assertion only counted call sites — the strengthened version now also asserts coordinates are finite + in-bounds. The lesson: count-based assertions are weak; if you can spot-check one value cheaply, do.

## Lessons recorded to memory

- `live_mic_layer_shipped.md` — concise project memory pointer.
- `listener_leak_singleton_pattern.md` — generalized "long-lived EventTarget + transient consumer + inline-arrow handler" anti-pattern with fix template. Already cited twice (MicRow, MicOverlay).

## Manual smoke checklist outcomes

| # | Step | Result |
|---|---|---|
| 1 | Sing C4, C5 — ribbon at the right pitch | ✅ (after #10 fix; before, ribbon snapped to nearest semitone) |
| 2 | Switch reference stem — colour bands shift | ✅ |
| 3 | Slide offset — ribbon translates horizontally | ✅ |
| 4 | Switch notation system — readout updates | ✅ |
| 5 | Switch tracks — ribbon clears, mic stays on | ✅ |
| 6 | Hit M — browser mic indicator releases | ✅ |
| 7 | Deny permission once, recover via second M-click | not explicitly retested after the lifecycle fixes; the `permission` error path is unit-tested at `tests-js/mic-pitch.test.js` and the M-click retry has no code change since the e2e ran |

## v1.5 follow-ups (intentionally deferred)

- Per-device picker UI in the row. `setDeviceId()` is callable + persisted, but needs the post-permission `enumerateDevices()` refresh dance for useful labels.
- Click-track latency calibration wizard. Offset slider is the v1 answer.
- Hop-overlap (halve worklet hop to 1024 → ~47 Hz estimate rate). Currently 1 estimate per 43 ms block.
- HNR / per-frame voicing strength (currently driven only by YIN's clarity score).
- Sensitivity slider in the row (RMS gate fixed at 0.005).

## Final state

- **Branch:** `main` (project commits straight to main per `[[branching_workflow]]`).
- **Webui:** running, all four new JS modules served, e2e green against the live server.
- **Doc trail:** spec carries a "Post-ship deltas (2026-05-23)" section with all API/semantic changes; plan carries an "Executed" footer pointing here; this report is the standalone outcome record.
