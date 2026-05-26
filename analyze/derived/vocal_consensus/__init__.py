"""Vocal consensus analysis: pitch+dynamics evidence fusion for vocal stems.

This package builds the substrate for the unified vocal performance pipeline
described in docs/superpowers/specs/2026-05-05-vocal-consensus-design.md
(Phase 0a — pure-Python algorithmic library, no pipeline integration).

Three pitch evidence streams (basic-pitch MIDI, FCPE F0, PESTO F0) plus one
dynamics evidence stream (frame-rate RMS envelope) are fused into:
  - canonical vocal note list (better than basic-pitch alone)
  - per-note metadata: intonation, ornamentation, dynamics, expression

Submodules:
  primitives    — pure math (Hz↔MIDI, cents, pitch class, octave folding)
  voicing       — multi-evidence voiced/unvoiced track
  octave        — 3-way pitch-class voting + outlier folding
  segmentation  — note boundary detection from F0 + RMS + basic-pitch onsets
  pitch_feat    — per-note intonation cents, stability
  dynamics_feat — per-note RMS shape, attack, decay, peak
  ornamentation — vibrato (FFT), glide (regression), scoop (asymmetry)
  expression    — joint pitch×dynamics features
  confidence    — per-note weighted-evidence scoring

Phase 0a populates these submodules incrementally; nothing here is wired
into the analyze/ pipeline until Phase 1.
"""
from analyze.derived.vocal_consensus.primitives import (
    cents_between,
    fold_cents,
    hz_to_midi,
    midi_to_hz,
    pitch_class,
)

__all__ = [
    "cents_between",
    "fold_cents",
    "hz_to_midi",
    "midi_to_hz",
    "pitch_class",
]
