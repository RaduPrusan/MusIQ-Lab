"""Pure clock-extrapolation helpers for the WASAPI audio backend.

The audio device's own stream clock is the song clock — the anchor just
establishes the (song_t ↔ audio_t) offset. Between anchor updates,
song-time is a simple linear extrapolation from the anchor; no drift
accumulates because both sides of the subtraction live on the same
PortAudio stream-internal monotonic clock.

This module is intentionally side-effect-free (no I/O, no sounddevice
import). The session module imports it and feeds it `time_info.outputBufferDacTime`
values from the PortAudio callback. Tested in `test_audio_clock.py`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Anchor:
    """Pairs a song-time with the stream-clock instant it corresponds to.

    `playing` is informational only — `song_t_from_audio_t` reads `song_t`
    and `audio_t` regardless. The caller (AudioSession) is responsible for
    re-anchoring on `play()` and `seek()` so the extrapolation stays glued
    to the actually-emitted DAC samples.
    """

    song_t: float       # song-time (seconds) at the anchor instant
    audio_t: float      # PortAudio stream-clock time at the same instant
    playing: bool       # informational; song-time read regardless


def song_t_from_audio_t(anchor: Anchor, audio_t: float) -> float:
    """Linearly extrapolate song-time from an anchor.

    Pure function. No drift accumulates between anchor updates because the
    audio device's own clock IS the song clock — the anchor just
    establishes the offset.
    """
    return anchor.song_t + (audio_t - anchor.audio_t)
