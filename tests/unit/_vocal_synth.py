"""Synthetic vocal-clip generator for vocal_consensus tests.

Produces the four input streams the consensus pipeline expects, with known
ground-truth properties so individual algorithms can be tested in isolation:

  - FCPE F0 array (1D float32, Hz, frame-rate, 0 = unvoiced)
  - PESTO F0 array (same shape)
  - basic-pitch note list (list[SynthBPNote] mimicking pretty_midi.Note)
  - RMS envelope (1D float32, linear amplitude in [0, ~1], frame-rate)

This file is private to the test suite (underscore prefix). Real audio is
not synthesized — we directly produce the *post-extraction* arrays the
real pipeline writes to vocal_f0.npz / dynamics/<stem>.npz, plus the
basic-pitch note list. That's what the consensus algorithms consume.

Phase 0a.2 ships steady-note rendering only. Vibrato, glide, scoop,
dynamics shapes, and estimator glitches (octave errors, voicing dropout)
are deferred to 0a.2b — the dataclass fields exist now so the API doesn't
churn when those features land.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

DynamicsShape = Literal["flat", "crescendo", "decrescendo", "arch"]

# Frame rate aligning with FCPE / PESTO / dynamics natural grid in the real
# pipeline. Real FCPE@16kHz with default hop = 100 fps; PESTO step_size=10ms
# = 100 fps. Synthetic data uses the same convention.
DEFAULT_FPS = 100.0

# Conventional silence amplitude in the RMS envelope. Real-world stem
# silence has noise floor around -60 dB ≈ 0.001 linear; we mimic.
SILENCE_RMS = 0.001


@dataclass
class SynthNote:
    """Specification of a single synthesized vocal note.

    Only the timing/pitch fields are honored in 0a.2 (steady note). The
    ornamentation/dynamics/glitch fields are accepted but ignored until
    0a.2b — they're declared now to keep the API stable.
    """
    t_start: float
    t_end: float
    midi: int
    cents_offset: float = 0.0           # +15 = 15¢ sharp of equal-temperament

    # --- Reserved for 0a.2b (currently no-op) ---
    vibrato_rate_hz: float = 0.0        # 0 = no vibrato
    vibrato_extent_cents: float = 0.0
    glide_cents: float = 0.0            # signed cents from t_start to t_end
    scoop_cents: float = 0.0            # signed scoop into the attack
    vel_peak: float = 0.7
    dynamics: DynamicsShape = "flat"
    fcpe_octave_glitch: bool = False
    fcpe_voicing_dropout: bool = False


@dataclass
class SynthBPNote:
    """Mimics pretty_midi.Note (the per-event shape basic-pitch returns)."""
    start: float
    end: float
    pitch: int
    velocity: int = 90    # MIDI velocity 0..127


@dataclass
class SynthClip:
    """The four synthesized streams + ground-truth references."""
    fcpe: np.ndarray            # shape (n_frames,), float32, Hz
    pesto: np.ndarray           # shape (n_frames,), float32, Hz
    basic_pitch_notes: list[SynthBPNote]
    rms: np.ndarray             # shape (n_frames,), float32, linear amplitude
    fps: float                  # frame rate (frames per second)
    duration_sec: float
    notes_truth: list[SynthNote] = field(default_factory=list)  # ground truth

    @property
    def n_frames(self) -> int:
        return len(self.fcpe)


class VocalSynth:
    """Builder for a synthetic vocal clip.

    Usage:
        clip = (VocalSynth(duration=2.0)
                .add_note(t_start=0.5, t_end=0.9, midi=69, cents_offset=15)
                .add_note(t_start=1.2, t_end=1.6, midi=72)
                .render())

    Notes added are sorted by t_start at render time; overlapping notes are
    permitted (and will produce overlapping basic-pitch entries, mirroring
    real basic-pitch output in polyphonic-vocal cases).
    """

    def __init__(self, duration: float, fps: float = DEFAULT_FPS):
        if duration <= 0:
            raise ValueError(f"duration must be positive, got {duration}")
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        self.duration = float(duration)
        self.fps = float(fps)
        self._notes: list[SynthNote] = []

    def add_note(self, **kwargs) -> "VocalSynth":
        note = SynthNote(**kwargs)
        if not (0 <= note.t_start < note.t_end <= self.duration):
            raise ValueError(
                f"note span [{note.t_start}, {note.t_end}] outside clip "
                f"duration [0, {self.duration}]"
            )
        if not (0 <= note.midi <= 127):
            raise ValueError(f"midi out of range: {note.midi}")
        self._notes.append(note)
        return self

    def render(self) -> SynthClip:
        n_frames = int(round(self.duration * self.fps))
        fcpe = np.zeros(n_frames, dtype=np.float32)
        pesto = np.zeros(n_frames, dtype=np.float32)
        rms = np.full(n_frames, SILENCE_RMS, dtype=np.float32)
        bp_notes: list[SynthBPNote] = []

        sorted_notes = sorted(self._notes, key=lambda n: n.t_start)

        for note in sorted_notes:
            i0 = int(round(note.t_start * self.fps))
            i1 = int(round(note.t_end * self.fps))
            if i1 <= i0:
                continue  # zero-length after rounding; skip

            # Steady F0: midi (integer) + cents_offset, constant across span.
            # Real estimators jitter; we'll add jitter in 0a.2b. For now the
            # ground truth is exactly known so algorithms can be tested
            # against deterministic inputs.
            target_hz = 440.0 * (2.0 ** ((note.midi - 69.0) / 12.0))
            shifted_hz = target_hz * (2.0 ** (note.cents_offset / 1200.0))

            fcpe[i0:i1] = shifted_hz
            pesto[i0:i1] = shifted_hz
            rms[i0:i1] = note.vel_peak  # flat envelope until 0a.2b

            # basic-pitch reports the integer (semitone-quantized). We round
            # to nearest semitone — matches what basic-pitch would do given
            # a continuous F0 input ±50¢.
            bp_pitch = note.midi
            if abs(note.cents_offset) >= 50:
                # Beyond ±50¢, basic-pitch would land on the adjacent semitone
                bp_pitch = note.midi + (1 if note.cents_offset > 0 else -1)

            bp_notes.append(SynthBPNote(
                start=note.t_start,
                end=note.t_end,
                pitch=bp_pitch,
                velocity=int(round(note.vel_peak * 127)),
            ))

        return SynthClip(
            fcpe=fcpe,
            pesto=pesto,
            basic_pitch_notes=bp_notes,
            rms=rms,
            fps=self.fps,
            duration_sec=self.duration,
            notes_truth=list(sorted_notes),
        )


# ---------- Recipe helpers (thin wrappers for common scenarios) ----------

def synth_steady_note(
    midi: int,
    *,
    t_start: float = 0.5,
    duration: float = 0.4,
    cents: float = 0.0,
    vel_peak: float = 0.7,
    clip_duration: float = 2.0,
    fps: float = DEFAULT_FPS,
) -> SynthClip:
    """One steady note centered in a 2s clip. The most common test fixture."""
    return (
        VocalSynth(duration=clip_duration, fps=fps)
        .add_note(
            t_start=t_start,
            t_end=t_start + duration,
            midi=midi,
            cents_offset=cents,
            vel_peak=vel_peak,
        )
        .render()
    )
