import json
from pathlib import Path

import jams
import pytest

from analyze.writers.jams_writer import write_jams
from analyze.writers.summary_writer import write_summary


@pytest.fixture
def fake_results():
    return {
        "stems": {"stems_6s": "stems_6s/", "stems_bsroformer": "stems_bsroformer/"},
        "beats": {
            "bpm": 107.14,
            "beats": [0.5, 1.0, 1.5, 2.0],
            "downbeats": [0.5, 2.5],
            "n_beats": 4,
            "n_downbeats": 2,
        },
        "beats_xcheck": {
            "beats": [0.51, 1.01, 1.51, 2.01],
            "downbeats": [0.51, 2.51],
            "n_beats": 4,
            "n_downbeats": 2,
        },
        "key": {"key": "F minor", "confidence": 1.0, "source": "skey.detect_key", "errors": []},
        "chords": [
            {"start": 0.0, "end": 1.0, "label": "F:min"},
            {"start": 1.0, "end": 2.0, "label": "C:min"},
            {"start": 2.0, "end": 3.0, "label": "F:min"},
        ],
        "transcription": {
            "vocals": {"notes": 100, "midi": "midi/vocals.mid"},
            "bass": {"notes": 50, "midi": "midi/bass.mid"},
        },
        "vocal_f0": {
            "fcpe_frames": 1000,
            "pesto_frames": 1000,
            "agreement_50c": 0.80,
        },
    }


@pytest.fixture
def fake_derived():
    return {
        "scale": "F natural minor",
        "predominant_chord_loop": ["F:min", "C:min"],
        "loop_roman": ["i", "v"],
        "loop_appearances": [{"start": 0.0, "end": 2.0}],
        "modal_interchange_count": 0,
        "vocal_range": {"low": "G3", "high": "D5"},
        "chords_enriched": [
            {"start": 0.0, "end": 1.0, "label": "F:min", "root": "F", "bass": "F",
             "type": "min", "roman": "i", "function": "tonic", "confidence": 1.0,
             "agreement": "single_source"},
            {"start": 1.0, "end": 2.0, "label": "C:min", "root": "C", "bass": "C",
             "type": "min", "roman": "v", "function": "dominant", "confidence": 1.0,
             "agreement": "single_source"},
            {"start": 2.0, "end": 3.0, "label": "F:min", "root": "F", "bass": "F",
             "type": "min", "roman": "i", "function": "tonic", "confidence": 1.0,
             "agreement": "single_source"},
        ],
        "stems_enriched": {
            "vocals": {"notes": []},  # no per-note enrichment in this synthetic test
            "bass": {"notes": []},
        },
    }


def test_write_summary_produces_valid_json(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    warnings = ["sections deferred — no segmenter installed"]

    write_summary(out, mp3, fake_results, fake_derived, warnings, duration_sec=215.0)

    data = json.loads(out.read_text())
    assert data["track"]["file"] == "song.mp3"
    assert data["track"]["key"] == "F minor"
    assert data["track"]["tempo_bpm"] == 107.14
    assert data["track"]["duration_sec"] == 215.0
    assert data["sections"] == []
    assert data["downbeats"] == [0.5, 2.5]
    assert len(data["chords"]) == 3
    assert data["chords"][0]["roman"] == "i"
    assert data["chords"][1]["roman"] == "v"
    assert data["analysis"]["scale"] == "F natural minor"
    assert data["analysis"]["predominant_chord_loop"] == ["F:min", "C:min"]
    assert data["analysis"]["vocal_range"] == {"low": "G3", "high": "D5"}
    assert "sections deferred" in data["provenance"]["warnings"][0]


def test_summary_includes_identify_when_present(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    fake_results["identify"] = {
        "identified": True,
        "title": "Silent Running",
        "artist": "Gorillaz",
        "mbid_recording": "rec-mbid",
        "year": 2001,
        "isrc": "GB123",
    }
    write_summary(out, mp3, fake_results, fake_derived, warnings=[], duration_sec=215.0)
    data = json.loads(out.read_text())
    assert data["identify"]["title"] == "Silent Running"
    assert data["identify"]["mbid_recording"] == "rec-mbid"


def test_summary_omits_identify_when_absent(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    assert "identify" not in fake_results
    write_summary(out, mp3, fake_results, fake_derived, warnings=[], duration_sec=215.0)
    data = json.loads(out.read_text())
    assert "identify" not in data


def test_summary_includes_essentia_with_agreement(tmp_path, fake_results, fake_derived):
    """When results['essentia_extract'] is set, summary.json gets
    summary.essentia (the slim dict) AND summary.essentia_agreement
    (computed via compute_agreement against summary.tempo_bpm + summary.key)."""
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    # Tune the fixture so the pipeline's (bpm, key) match Essentia's, for the
    # agreement cross-check to come back ok=True.
    fake_results["beats"]["bpm"] = 120.0
    fake_results["key"]["key"] = "A:minor"
    fake_results["essentia_extract"] = {
        "extracted": True,
        "tempo": {
            "bpm": 120.4,
            "first_peak_bpm": 120.0,
            "first_peak_weight": 0.5,
            "beats_count": 240,
        },
        "key": {
            "krumhansl": ["A", "minor", 0.81],
            "temperley": ["A", "minor", 0.77],
            "edma": ["E", "major", 0.42],
        },
        "loudness_ebu_r128": {"integrated": -9.2, "range": 7.4, "dynamic_complexity": 4.1},
        "high_level": {"available": False},
    }
    write_summary(out, mp3, fake_results, fake_derived, warnings=[], duration_sec=215.0)
    data = json.loads(out.read_text())
    assert data["essentia"]["tempo"]["bpm"] == 120.4
    assert data["essentia"]["key"]["krumhansl"] == ["A", "minor", 0.81]
    assert data["essentia_agreement"]["bpm"]["ok"] is True
    assert data["essentia_agreement"]["bpm"]["delta"] == pytest.approx(0.4, abs=0.01)
    assert data["essentia_agreement"]["key"]["ok"] is True
    assert data["essentia_agreement"]["key"]["essentia_consensus"] == "A:minor"


def test_summary_omits_essentia_when_absent(tmp_path, fake_results, fake_derived):
    """When results lacks 'essentia_extract', summary lacks both
    'essentia' and 'essentia_agreement'."""
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    assert "essentia_extract" not in fake_results
    write_summary(out, mp3, fake_results, fake_derived, warnings=[], duration_sec=215.0)
    data = json.loads(out.read_text())
    assert "essentia" not in data
    assert "essentia_agreement" not in data


def test_write_jams_produces_valid_file(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"

    write_jams(out, mp3, fake_results, fake_derived, warnings=[], duration_sec=215.0)

    j = jams.load(str(out))
    # Required JAMS structure
    assert j.file_metadata.duration == 215.0
    # at least one beat, one chord, one key annotation
    assert len(j.search(namespace="beat")) >= 1
    assert len(j.search(namespace="chord")) >= 1
    assert len(j.search(namespace="key_mode")) >= 1


def test_write_jams_skips_missing_stages(tmp_path, fake_derived):
    """If beats_xcheck and vocal_f0 are absent (None), the JAMS still writes — those annotations just aren't included."""
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"
    results_minimal = {
        "stems": {"stems_6s": "stems_6s/", "stems_bsroformer": "stems_bsroformer/"},
        "beats": {"bpm": 107.0, "beats": [0.5, 1.0], "downbeats": [0.5], "n_beats": 2, "n_downbeats": 1},
        "key": {"key": "F minor", "confidence": 1.0, "source": "skey.detect_key", "errors": []},
        "chords": [{"start": 0.0, "end": 1.0, "label": "F:min"}],
        "transcription": {"vocals": {"notes": 0, "midi": "midi/vocals.mid"}},
        # beats_xcheck and vocal_f0 are missing
    }
    write_jams(out, mp3, results_minimal, fake_derived, warnings=[], duration_sec=215.0)
    j = jams.load(str(out))
    # only one beat annotation (from madmom), no beat_this
    annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="beat")]
    assert "madmom" in annotators
    assert "beat_this" not in annotators
    # no pitch_contour annotations
    assert len(j.search(namespace="pitch_contour")) == 0


def test_write_jams_includes_tempo(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"
    write_jams(out, mp3, fake_results, fake_derived, [], duration_sec=215.0)
    j = jams.load(str(out))
    tempos = j.search(namespace="tempo")
    assert len(tempos) == 1
    assert list(tempos[0].data)[0].value == fake_results["beats"]["bpm"]


def test_write_jams_includes_snapped_chord(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"
    write_jams(out, mp3, fake_results, fake_derived, [], duration_sec=215.0)
    j = jams.load(str(out))
    chord_anns = j.search(namespace="chord")
    annotators = sorted(ann.annotation_metadata.annotator["name"] for ann in chord_anns)
    assert "lv_chordia" in annotators
    assert "lv_chordia_snapped" in annotators
