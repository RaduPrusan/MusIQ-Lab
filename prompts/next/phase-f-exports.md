# Phase F — Exports musicians actually use

**Date:** 2026-05-03
**Effort:** ≈1 week
**Depends on:** [Phase A+B](phase-a-specialist-models.md) (specialist models so the MIDI is actually accurate) and [Phase C](phase-c-structural-layer.md) (sections, for sectional MIDI bundles).
**Status:** Sketch — full spec to be written when its turn comes.

## Goal

Make the analyzed output usable in real production. Today's MIDI files have constant velocity, generic instrument channels, and aren't tempo-locked. A musician can't drop them into a DAW and have anything musical happen.

## Scope

**In:**

- **Per-instrument MIDI** with proper General MIDI patches per stem (vocals → 53 Choir Aahs, piano → 1 Acoustic Grand, bass → 33 Acoustic Bass, etc.) and per-stem MIDI channels. Configurable.
- **Tempo-locked MIDI** — embed the per-bar tempo curve from Phase C as MIDI tempo events. DAW import lines up to the audio.
- **Real velocity curves** on instrument MIDI — per-note velocity from the transcribers' confidence/loudness output (Phase D).
- **Sectional MIDI bundle** — each section becomes a clip / bar-aligned region. Useful for arrangers.
- **MusicXML lead sheet** — chord symbols + melody (vocal F0→notes) + sections, in a format that opens in MuseScore / Sibelius / Finale.
- **DAW-importable bundle** — zip containing the multi-track MIDI, the audio stems, and a Reaper / Ableton-friendly project file (or just a manifest the DAW can ingest).

**Out:**

- Stem audio re-mastering or normalization. Out of scope.
- Audio rendering of the MIDI back to WAV. Side project, not core.
- Sheet music typesetting beyond what MusicXML naturally provides.

## Deliverables

1. **`analyze/exporters/midi.py`** — per-instrument MIDI writer. Replaces the bare `midi_data.write` calls in transcription stages.
2. **`analyze/exporters/musicxml.py`** — lead sheet writer.
3. **`analyze/exporters/bundle.py`** — DAW bundle packager.
4. **Webui** — download buttons in the track view for each export format.
5. **`tests/test_exports.py`** — golden output tests on the corpus.

## Validation criteria

- MIDI imports into Reaper, Ableton, and Logic with audio-aligned timing on a tempo-stable track.
- Tempo-curve track imports correctly on a track with measurable tempo drift.
- MusicXML lead sheet opens in MuseScore and shows chord symbols, melody, and section markers.
- Round-trip: export MIDI, re-import, render to audio with stock instruments, and the result is recognizably the original song.

## Risks

- **GM patch mapping** — choosing GM patches per stem is taste-dependent. Provide sensible defaults plus a per-export override.
- **DAW project format compatibility** — Reaper and Ableton have very different project formats. Start with one (probably Reaper, since it's text-based) and add Ableton as a stretch goal.
