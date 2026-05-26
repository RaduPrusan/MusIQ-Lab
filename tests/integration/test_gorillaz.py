"""End-to-end integration test against the validated Gorillaz cache.

Reuses cache/gorillaz_silent_running/ (must be populated from a prior run, or
will skip). No GPU required — every stage is cache-loaded.

Override the source MP3 path with $MUSIQ_GORILLAZ_MP3; defaults to
$MUSIQ_YT_OUT_DIR/Gorillaz...mp3, which itself defaults to ~/Videos/musiq-lab/.
The test skips cleanly when the file or cache aren't present.
"""
import json
import os
from pathlib import Path

import jams
import pytest

from analyze.cache import PROJECT_ROOT
from analyze.pipeline import analyze


def _default_gorillaz_mp3() -> Path:
    yt_dir = Path(os.environ.get("MUSIQ_YT_OUT_DIR") or (Path.home() / "Videos" / "musiq-lab"))
    return yt_dir / (
        "Gorillaz - Silent Running ft. Adeleye Omotayo "
        "(Official Video)-_0Pf48RqSsg.mp3"
    )


GORILLAZ_MP3 = Path(os.environ.get("MUSIQ_GORILLAZ_MP3") or _default_gorillaz_mp3())
GORILLAZ_CACHE = PROJECT_ROOT / "cache" / "gorillaz_silent_running"


@pytest.fixture(scope="module")
def gorillaz_result():
    if not GORILLAZ_MP3.exists():
        pytest.skip(f"reference MP3 not present: {GORILLAZ_MP3}")
    if not GORILLAZ_CACHE.exists():
        pytest.skip(f"reference cache not present: {GORILLAZ_CACHE}")
    return analyze(GORILLAZ_MP3, slug="gorillaz_silent_running", quiet=True)


@pytest.fixture(scope="module")
def gorillaz_summary(gorillaz_result):
    return json.loads(gorillaz_result.summary_path.read_text())


def test_track_metadata(gorillaz_summary):
    t = gorillaz_summary["track"]
    assert t["key"] == "F minor"
    assert 105 < t["tempo_bpm"] < 110
    assert t["time_signature"] == "4/4"
    assert t["file"].endswith(".mp3")


def test_sections_empty_with_warning(gorillaz_summary):
    assert gorillaz_summary["sections"] == []
    assert any("sections deferred" in w for w in gorillaz_summary["provenance"]["warnings"])


def test_chord_count_and_first_chord(gorillaz_summary):
    chords = gorillaz_summary["chords"]
    assert len(chords) == 94
    # first non-N chord should be F:min (per validated cache)
    non_n = [c for c in chords if c["label"] != "N"]
    assert non_n[0]["label"] == "F:min"
    assert non_n[0]["roman"] == "i"
    assert non_n[0]["function"] == "tonic"


def test_analysis_block(gorillaz_summary):
    a = gorillaz_summary["analysis"]
    assert a["scale"] == "F natural minor"
    assert a["predominant_chord_loop"] is not None
    assert "F:min" in a["predominant_chord_loop"]
    assert "C:min" in a["predominant_chord_loop"]
    assert a["loop_roman"] is not None
    assert a["vocal_range"] is not None
    assert isinstance(a["vocal_range"]["low"], str)
    assert isinstance(a["vocal_range"]["high"], str)


def test_stems_have_enriched_notes(gorillaz_summary):
    stems = gorillaz_summary["stems"]
    assert "vocals" in stems
    assert "bass" in stems
    assert "drums" in stems
    # drums shape depends on whether LarsNet was installed when the cache was
    # generated. Both shapes are valid pipeline outputs.
    drums = stems["drums"]
    if drums["transcribed"]:
        for substem in ["kick", "snare", "toms", "hihat", "cymbals"]:
            assert substem in drums, f"missing drum substem: {substem}"
            assert isinstance(drums[substem], list), f"drums.{substem} not a list"
    else:
        assert drums["transcribed"] is False
        assert "reason" in drums
    # vocals stem note count: ~1098 ± a few. Loose because of basic-pitch's
    # CUDA-reduction-order non-determinism + the per-note phantom filter.
    assert 1080 <= len(stems["vocals"]["notes"]) <= 1120
    # sample note has enrichment fields
    sample = stems["vocals"]["notes"][0]
    for fld in ["t", "dur", "midi", "name", "vel", "in_chord", "role", "scale_deg"]:
        assert fld in sample, f"missing field: {fld}"


def test_stem_presence_gate_wired_for_melodic_stems(gorillaz_summary):
    """Regression guard: every melodic stem must carry a `presence` block from
    the new stem-presence gate (analyze/derived/stem_presence.py). Catches any
    future wire-up regression in pipeline._enrich_stems()."""
    stems = gorillaz_summary["stems"]
    for melodic in ["vocals", "bass", "guitar", "piano", "other"]:
        entry = stems[melodic]
        assert "presence" in entry, f"missing presence block for {melodic}"
        p = entry["presence"]
        # Required fields the webui tooltip consumes.
        for fld in ["stem_rms_db", "active_frame_ratio", "thresholds",
                    "gates_tripped", "transcribed"]:
            assert fld in p, f"presence.{fld} missing for {melodic}"
        # Gorillaz is a vocal-led pop track — vocals should pass the gate.
        if melodic == "vocals":
            assert p["transcribed"] is True
            assert p["gates_tripped"] == []


def test_provenance(gorillaz_summary):
    p = gorillaz_summary["provenance"]
    assert p["pipeline_version"] == "0.1.0"
    assert "madmom" in p["models"]
    assert "skey" in p["models"]
    # Reconciliation block was added 2026-05-09. Older caches predate the
    # field — guard the assertion so it's exercised post-rebuild without
    # breaking the test against historical caches that still ship without it.
    if "reconciliation" in p:
        recon = p["reconciliation"]
        assert any(k.startswith("chord_downbeat_") for k in recon), (
            f"reconciliation present but missing chord_downbeat_* keys: {recon}"
        )


def test_jams_validates(gorillaz_result):
    j = jams.load(str(gorillaz_result.jams_path))
    # If JAMS strict-validation fails, write_jams logs a warning but does not crash.
    # Here we want to confirm that the file is at least loadable.
    assert j.file_metadata.duration > 0
    assert len(j.search(namespace="beat")) >= 1
    assert len(j.search(namespace="chord")) >= 1
    assert len(j.search(namespace="key_mode")) >= 1


def test_no_required_stage_failures(gorillaz_summary):
    warnings = gorillaz_summary["provenance"]["warnings"]
    for w in warnings:
        assert "stems failed" not in w
        assert "beats failed" not in w
        assert "key failed" not in w
        assert "chords failed" not in w
        assert "transcription failed" not in w


def test_jams_has_full_validated_stack_annotations(gorillaz_result):
    j = jams.load(str(gorillaz_result.jams_path))
    # tempo
    assert len(j.search(namespace="tempo")) >= 1
    # snapped chord track
    chord_annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="chord")]
    assert "lv_chordia" in chord_annotators
    assert "lv_chordia_snapped" in chord_annotators
    # note_midi per harmonic stem
    note_annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="note_midi")]
    for stem in ["vocals", "bass", "guitar", "piano", "other"]:
        assert any(stem in a for a in note_annotators), f"missing note_midi for {stem}"
    # pitch_contour (FCPE + PESTO; soft-fail-safe — only if vocal_f0 stage ran)
    pc_annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="pitch_contour")]
    if pc_annotators:  # vocal_f0 is optional
        assert "torchfcpe" in pc_annotators
        assert "pesto" in pc_annotators
