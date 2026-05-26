"""Unit tests for the piano-transcription stage.

The actual ByteDance model is heavyweight (165MB weights, GPU inference);
we mock it here. Real-pipeline coverage lands in WI-12's benchmark."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import json

import numpy as np
import pytest

from analyze.stages import transcription_piano


def _fixture_routing(d: Path, with_piano: bool = True) -> Path:
    """Set up a cache_dir with stems_routing.json (with or without piano)."""
    (d / "stems_6s").mkdir(parents=True, exist_ok=True)
    routing: dict = {"version": 1, "preset": "normal", "routing": {}}
    if with_piano:
        piano_wav = d / "stems_6s" / "foo_(Piano)_htdemucs_6s.wav"
        piano_wav.touch()
        routing["routing"]["piano"] = {"path": "stems_6s/foo_(Piano)_htdemucs_6s.wav"}
    (d / "stems_routing.json").write_text(json.dumps(routing))
    return d


def test_resolve_audio_uses_routing_when_available(tmp_path: Path):
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()
    p = transcription_piano._resolve_audio_path(mp3, tmp_path, transcribe_full_mix=False)
    assert p.name == "foo_(Piano)_htdemucs_6s.wav"


def test_resolve_audio_falls_back_to_mix_when_routing_missing(tmp_path: Path):
    """No stems_routing.json → fall back to original mp3, don't crash."""
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()
    p = transcription_piano._resolve_audio_path(mp3, tmp_path, transcribe_full_mix=False)
    assert p == mp3


def test_resolve_audio_falls_back_when_routing_has_no_piano(tmp_path: Path):
    _fixture_routing(tmp_path, with_piano=False)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()
    p = transcription_piano._resolve_audio_path(mp3, tmp_path, transcribe_full_mix=False)
    assert p == mp3


def test_resolve_audio_uses_mix_when_full_mix_flag_set(tmp_path: Path):
    """transcribe_full_mix=True forces the original mix even if routing has piano."""
    _fixture_routing(tmp_path, with_piano=True)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()
    p = transcription_piano._resolve_audio_path(mp3, tmp_path, transcribe_full_mix=True)
    assert p == mp3


def test_default_params_match_spec():
    """ByteDance recommended thresholds — bumping these requires a SCHEMA_VERSION bump."""
    p = transcription_piano.DEFAULT_PARAMS
    assert p["onset_threshold"] == 0.3
    assert p["offset_threshold"] == 0.3
    assert p["frame_threshold"] == 0.3
    assert p["pedal_offset_threshold"] == 0.2
    assert p["transcribe_full_mix"] is False


def test_cached_returns_false_without_summary(tmp_path: Path):
    assert transcription_piano.cached(tmp_path) is False


def test_cached_returns_false_without_midi(tmp_path: Path):
    """Summary present but MIDI missing → cached should be False."""
    (tmp_path / transcription_piano.CANONICAL).write_text("{}")
    assert transcription_piano.cached(tmp_path) is False


def test_cached_requires_sidecar(tmp_path: Path):
    """Both files exist but no sidecar → cached False."""
    (tmp_path / transcription_piano.CANONICAL).write_text("{}")
    (tmp_path / "midi").mkdir()
    (tmp_path / "midi" / "piano.mid").touch()
    assert transcription_piano.cached(tmp_path) is False


def test_run_writes_summary_and_sidecar(tmp_path: Path):
    """End-to-end run with the model mocked. Verifies the side effects."""
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    fake_audio = np.zeros(16000, dtype=np.float32)
    fake_out = {
        "est_note_events": [
            {"onset_time": 0.0, "offset_time": 0.5, "midi_note": 60, "velocity": 80},
            {"onset_time": 0.5, "offset_time": 1.0, "midi_note": 64, "velocity": 90},
        ]
    }

    with patch("librosa.load", return_value=(fake_audio, 16000)), \
         patch("piano_transcription_inference.PianoTranscription") as Mock:
        instance = Mock.return_value
        instance.transcribe = MagicMock(return_value=fake_out)
        # Make the mocked transcribe also write a stub MIDI file at the second arg
        def write_midi(audio, midi_path):
            Path(midi_path).touch()
            return fake_out
        instance.transcribe.side_effect = write_midi

        result = transcription_piano.run(mp3, tmp_path)

    assert result["n_notes"] == 2
    assert result["notes"][0]["pitch"] == 60
    assert (tmp_path / "midi" / "piano.mid").exists()
    assert (tmp_path / "transcription_piano.json").exists()
    assert (tmp_path / ".params_transcription_piano.json").exists()


def test_run_handles_missing_est_note_events(tmp_path: Path):
    """If the model returns a dict without est_note_events, summary has 0 notes (not crash)."""
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    fake_audio = np.zeros(16000, dtype=np.float32)

    with patch("librosa.load", return_value=(fake_audio, 16000)), \
         patch("piano_transcription_inference.PianoTranscription") as Mock:
        instance = Mock.return_value
        def write_midi(audio, midi_path):
            Path(midi_path).touch()
            return {}  # No note events
        instance.transcribe.side_effect = write_midi

        result = transcription_piano.run(mp3, tmp_path)

    assert result["n_notes"] == 0
    assert result["notes"] == []
