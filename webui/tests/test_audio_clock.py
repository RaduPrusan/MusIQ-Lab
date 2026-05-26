"""Phase 2 — pure-function tests for the audio clock extrapolator.

`song_t_from_audio_t(anchor, audio_t)` is the load-bearing linear function
that the audio backend uses to read song-time from the PortAudio
stream-clock. These tests pin the math (and document the "no-drift"
guarantee — the audio device IS the song clock between anchor updates).
"""
from __future__ import annotations

from webui.audio_backend.clock import Anchor, song_t_from_audio_t


def test_extrapolate_forward_from_anchor():
    """A 0.5 s advance in audio_t produces a 0.5 s advance in song_t."""
    anchor = Anchor(song_t=10.0, audio_t=100.0, playing=True)
    assert song_t_from_audio_t(anchor, 100.5) == 10.5


def test_extrapolate_backward_documents_no_clamp():
    """If audio_t went BACKWARD by 1 s relative to the anchor (paused-and-
    resumed without re-anchoring), the function returns song_t - 1.0.

    This is BY DESIGN: the caller (AudioSession) is responsible for
    re-anchoring on play/seek so the extrapolation never sees a
    backward-moving audio_t in practice. The function itself is a pure
    linear map and has no clamping logic.
    """
    anchor = Anchor(song_t=10.0, audio_t=100.0, playing=True)
    assert song_t_from_audio_t(anchor, 99.0) == 9.0


def test_anchor_reset_across_seek():
    """After a seek to song_t=20, a fresh anchor with audio_t=150 lets
    extrapolation continue linearly: audio_t=151 → song_t=21.
    """
    new = Anchor(song_t=20.0, audio_t=150.0, playing=True)
    assert song_t_from_audio_t(new, 151.0) == 21.0


def test_no_drift_between_consecutive_reads():
    """Two reads taken Δt apart return song_t values exactly Δt apart.

    This is the "no drift accumulates between anchor updates" guarantee
    the design spec leans on for the smooth-cursor architecture.
    """
    anchor = Anchor(song_t=5.0, audio_t=200.0, playing=True)
    a = song_t_from_audio_t(anchor, 200.025)
    b = song_t_from_audio_t(anchor, 200.050)
    assert abs((b - a) - 0.025) < 1e-9


def test_anchor_dataclass_fields():
    """Anchor is a dataclass with the three documented fields."""
    a = Anchor(song_t=1.0, audio_t=2.0, playing=False)
    assert a.song_t == 1.0
    assert a.audio_t == 2.0
    assert a.playing is False
