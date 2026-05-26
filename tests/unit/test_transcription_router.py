"""Unit tests for the transcription router.

Each transcriber is mocked at the module boundary; we verify the dispatch
logic, error handling, and routing-fallback behavior. Real-pipeline coverage
lands in WI-12's benchmark.

Note: the homegrown vocals F0→notes specialist (transcription_vocals.py)
was reverted 2026-05-04 — vocals now dispatch to basic-pitch like the
other non-piano stems. See analyze/stages/transcription.py docstring.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import json

import pytest

from analyze.stages import transcription


def _fixture_routing(d: Path, stems: list[str] = None) -> None:
    """Set up a cache_dir with stems_routing.json containing the listed stems."""
    stems = stems or ["vocals", "piano", "bass", "guitar", "other"]
    routing_entries = {}
    for s in stems:
        wav_name = f"foo_({s.title()})_htdemucs_6s.wav"
        sub = d / "stems_6s"
        sub.mkdir(exist_ok=True)
        (sub / wav_name).touch()
        routing_entries[s] = {"path": f"stems_6s/{wav_name}"}
    (d / "stems_routing.json").write_text(json.dumps({
        "version": 1,
        "preset": "normal",
        "routing": routing_entries,
    }))


def test_transcribers_table_covers_5_melodic_stems():
    expected = {"vocals", "piano", "bass", "guitar", "other"}
    assert set(transcription.TRANSCRIBERS) == expected


def test_drums_not_in_transcribers():
    """Drums are handled by drums.py (Stage 9), not the transcription router."""
    assert "drums" not in transcription.TRANSCRIBERS


def test_vocals_dispatched_to_basic_pitch():
    """Post-2026-05-04 revert: vocals go through basic-pitch, not a specialist."""
    assert transcription.TRANSCRIBERS["vocals"] == "basic"


def test_router_dispatches_piano_to_specialist(tmp_path: Path):
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    with patch("analyze.stages.transcription_piano.run") as p_run, \
         patch("analyze.stages.transcription_basic.run_for_stem") as b_run:
        p_run.return_value = {"n_notes": 50, "notes": [], "midi": "midi/piano.mid"}
        b_run.return_value = {"notes": 30, "midi": "midi/bass.mid"}

        result = transcription.run(mp3, tmp_path)

    assert result["stems"]["piano"]["transcriber"] == "piano"
    assert result["stems"]["piano"]["notes"] == 50
    assert p_run.call_count == 1


def test_router_dispatches_non_piano_stems_to_basic_pitch(tmp_path: Path):
    """vocals + bass + guitar + other all go through basic-pitch."""
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    with patch("analyze.stages.transcription_piano.run") as p_run, \
         patch("analyze.stages.transcription_basic.run_for_stem") as b_run:
        p_run.return_value = {"n_notes": 50, "midi": "midi/piano.mid"}
        b_run.return_value = {"notes": 30, "midi": "midi/X.mid"}

        transcription.run(mp3, tmp_path)

    # 4 basic-pitch calls: vocals, bass, guitar, other
    assert b_run.call_count == 4
    called_stems = {call.args[0] for call in b_run.call_args_list}
    assert called_stems == {"vocals", "bass", "guitar", "other"}


def test_router_skips_basic_pitch_stems_missing_from_routing(tmp_path: Path):
    """Stems that aren't in the routing file are marked skipped, not error."""
    _fixture_routing(tmp_path, stems=["vocals", "piano"])  # no bass/guitar/other
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    with patch("analyze.stages.transcription_piano.run") as p_run, \
         patch("analyze.stages.transcription_basic.run_for_stem") as b_run:
        p_run.return_value = {"n_notes": 50, "midi": "midi/piano.mid"}
        b_run.return_value = {"notes": 30, "midi": "midi/X.mid"}

        result = transcription.run(mp3, tmp_path)

    # Only vocals routes to basic-pitch (bass/guitar/other not in routing).
    assert b_run.call_count == 1
    assert b_run.call_args.args[0] == "vocals"
    for skipped_stem in ("bass", "guitar", "other"):
        assert result["stems"][skipped_stem].get("skipped") is True


def test_router_captures_per_stem_errors_without_killing_others(tmp_path: Path):
    """If a transcriber raises, the failing stem records error, others succeed."""
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    with patch("analyze.stages.transcription_piano.run") as p_run, \
         patch("analyze.stages.transcription_basic.run_for_stem") as b_run:
        p_run.side_effect = RuntimeError("piano model failed")
        b_run.return_value = {"notes": 30, "midi": "midi/X.mid"}

        result = transcription.run(mp3, tmp_path)

    assert "error" in result["stems"]["piano"]
    assert "RuntimeError" in result["stems"]["piano"]["error"]
    assert result["stems"]["vocals"]["notes"] == 30  # vocals (basic-pitch) still succeeded


def test_router_writes_summary_and_sidecar(tmp_path: Path):
    _fixture_routing(tmp_path)
    mp3 = tmp_path / "fake.mp3"
    mp3.touch()

    with patch("analyze.stages.transcription_piano.run") as p_run, \
         patch("analyze.stages.transcription_basic.run_for_stem") as b_run:
        p_run.return_value = {"n_notes": 50, "midi": "midi/piano.mid"}
        b_run.return_value = {"notes": 30, "midi": "midi/X.mid"}

        transcription.run(mp3, tmp_path)

    assert (tmp_path / transcription.CANONICAL).exists()
    assert (tmp_path / ".params_transcription.json").exists()
    summary = json.loads((tmp_path / transcription.CANONICAL).read_text())
    assert summary["schema_version"] == transcription.SCHEMA_VERSION
    assert "stems" in summary


def test_cached_returns_false_without_summary(tmp_path: Path):
    assert transcription.cached(tmp_path) is False


def test_cached_returns_false_when_midi_files_missing(tmp_path: Path):
    (tmp_path / transcription.CANONICAL).write_text("{}")
    # No midi/ dir at all
    assert transcription.cached(tmp_path) is False


def test_cached_requires_sidecar(tmp_path: Path):
    """Summary + all midi files exist but no sidecar → cached False."""
    (tmp_path / transcription.CANONICAL).write_text("{}")
    md = tmp_path / "midi"
    md.mkdir()
    for s in transcription.TRANSCRIBERS:
        (md / f"{s}.mid").touch()
    assert transcription.cached(tmp_path) is False


def test_basic_pitch_params_preserved():
    """The original per-stem hyperparams must be byte-identical (no tuning here;
    that's deferred to Phase E)."""
    from analyze.stages import transcription_basic
    p = transcription_basic.BASIC_PITCH_PARAMS
    assert p["vocals"] == dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80)
    assert p["bass"] == dict(onset_threshold=0.5, frame_threshold=0.4, minimum_note_length=50, minimum_frequency=27.5, maximum_frequency=400)
    assert p["guitar"] == dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80)
    assert p["piano"] == dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=27.5)
    assert p["other"] == dict(onset_threshold=0.6, minimum_note_length=100, minimum_frequency=80)
