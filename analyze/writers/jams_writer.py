"""JAMS file writer.

Maps validated-stack stage outputs onto JAMS annotations following the
spec in docs/superpowers/specs/2026-04-29-analyze-py-design.md (JAMS
structure section). Each stage's output becomes one or more JAMS
annotations with explicit annotator metadata for downstream filtering.

Skeleton: this version handles only beats/chords/key. Stage 6 note_midi
annotations, Stage 7 pitch_contour annotations, tempo, and the snapped
chord track will be added in Task 19a once the full pipeline data is
available."""
from __future__ import annotations

from importlib import metadata as importlib_metadata
from pathlib import Path

import jams


def _annotator_meta(name: str, module: str) -> dict:
    try:
        version = importlib_metadata.version(name)
    except Exception:
        version = "unknown"
    return {
        "annotator": {"name": name, "version": version},
        "annotation_tools": f"[script: {module}]",
        "data_source": "machine",
        "corpus": "user_library",
    }


def _build_beat_annotation(beats: list[float], annotator_name: str, module: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="beat", duration=duration)
    meta = _annotator_meta(annotator_name, module)
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for t in beats:
        ann.append(time=float(t), duration=0.0, value=1, confidence=None)
    return ann


def _build_chord_annotation(chords: list[dict], annotator_name: str, module: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="chord", duration=duration)
    meta = _annotator_meta(annotator_name, module)
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for c in chords:
        ann.append(
            time=float(c["start"]),
            duration=max(0.0, float(c["end"]) - float(c["start"])),
            value=str(c["label"]),
            confidence=None,
        )
    return ann


def _build_key_annotation(key_str: str, source: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="key_mode", duration=duration)
    annotator_name = "skey" if source == "skey.detect_key" else source
    meta = _annotator_meta(annotator_name, "analyze.stages.key")
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    # Normalize "F minor" → "F:minor" per JAMS key_mode namespace convention.
    parts = key_str.split()
    jams_key = f"{parts[0]}:{parts[1].lower()}" if len(parts) == 2 else key_str
    ann.append(time=0.0, duration=duration, value=jams_key, confidence=None)
    return ann


def _build_tempo_annotation(bpm: float, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="tempo", duration=duration)
    meta = _annotator_meta("madmom_derived", "analyze.stages.beats")
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    ann.append(time=0.0, duration=duration, value=float(bpm), confidence=1.0)
    return ann


def _build_note_midi_annotation(midi_path: Path, stem: str, duration: float) -> jams.Annotation:
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    ann = jams.Annotation(namespace="note_midi", duration=duration)
    meta = _annotator_meta(f"basic_pitch[{stem}]", "analyze.stages.transcription")
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for inst in pm.instruments:
        for n in inst.notes:
            ann.append(
                time=float(n.start),
                duration=float(n.end - n.start),
                value=float(n.pitch),
                confidence=round(float(n.velocity) / 127.0, 3),
            )
    return ann


def _build_pitch_contour_annotation(f0: list[float], frame_rate: float, annotator_name: str, module: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="pitch_contour", duration=duration)
    meta = _annotator_meta(annotator_name, module)
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for i, hz in enumerate(f0):
        if hz <= 0:
            continue  # unvoiced frame — JAMS observations are sparse, skip the placeholder
        t = i / frame_rate
        ann.append(
            time=float(t),
            duration=1.0 / frame_rate,
            value={"index": i, "frequency": float(hz), "voiced": True},
            confidence=None,
        )
    return ann


def _build_chord_snapped_annotation(chords: list[dict], downbeats: list[float], duration: float) -> jams.Annotation:
    """Snap chord starts to the nearest madmom downbeat (Stage 8 reconciliation)."""
    if not downbeats:
        return _build_chord_annotation(chords, "lv_chordia_snapped", "analyze.stages.chords", duration)
    snapped = []
    for c in chords:
        nearest = min(downbeats, key=lambda d: abs(d - c["start"]))
        snapped.append({"start": nearest, "end": c["end"], "label": c["label"]})
    return _build_chord_annotation(snapped, "lv_chordia_snapped", "analyze.stages.chords", duration)


def write_jams(
    jams_path: Path,
    mp3_path: Path,
    results: dict,
    derived: dict,
    warnings: list[str],
    duration_sec: float,
) -> None:
    j = jams.JAMS()
    j.file_metadata.duration = float(duration_sec)
    j.file_metadata.title = mp3_path.stem
    j.file_metadata.artist = ""

    # beats (madmom canonical)
    if "beats" in results:
        j.annotations.append(
            _build_beat_annotation(results["beats"]["beats"], "madmom", "analyze.stages.beats", duration_sec)
        )
    # beats_xcheck (beat-this; only if present)
    if "beats_xcheck" in results:
        j.annotations.append(
            _build_beat_annotation(results["beats_xcheck"]["beats"], "beat_this", "analyze.stages.beats_xcheck", duration_sec)
        )
    # chord (raw lv-chordia)
    if "chords" in results:
        j.annotations.append(
            _build_chord_annotation(results["chords"], "lv_chordia", "analyze.stages.chords", duration_sec)
        )
    # key
    if "key" in results:
        j.annotations.append(
            _build_key_annotation(results["key"]["key"], results["key"].get("source", "skey.detect_key"), duration_sec)
        )

    # tempo
    if "beats" in results:
        j.annotations.append(
            _build_tempo_annotation(results["beats"]["bpm"], duration_sec)
        )
    # snapped chord track (Stage 8 reconciliation)
    if "chords" in results and "beats" in results:
        j.annotations.append(
            _build_chord_snapped_annotation(results["chords"], results["beats"]["downbeats"], duration_sec)
        )
    # note_midi per stem
    if "transcription" in results:
        # WI-9 changed transcription's return shape to {schema_version, stems: {...}}.
        # Tolerate the legacy flat shape too for backward-compat with old caches.
        tr = results["transcription"]
        stems_iter = tr["stems"] if isinstance(tr, dict) and "stems" in tr else tr
        # MIDI files always live at <cache_dir>/midi/<stem>.mid by convention
        # (basic-pitch returns absolute paths, transcription_vocals returns
        # relative; resolving from jams_path.parent works uniformly).
        midi_dir = jams_path.parent / "midi"
        for stem_name, info in stems_iter.items():
            if not isinstance(info, dict) or info.get("skipped") or info.get("error"):
                continue
            midi_path = midi_dir / f"{stem_name}.mid"
            if midi_path.exists():
                j.annotations.append(_build_note_midi_annotation(midi_path, stem_name, duration_sec))
    # pitch_contour (FCPE + PESTO; only if vocal_f0 succeeded)
    if "vocal_f0" in results and "fcpe_array" in results["vocal_f0"]:
        # FCPE / PESTO are at 16 kHz audio; FCPE outputs ~100 fps; PESTO with step_size=10ms = 100 fps.
        f0_fcpe = results["vocal_f0"]["fcpe_array"].tolist()
        f0_pesto = results["vocal_f0"]["pesto_array"].tolist()
        # frame_rate derived: len / duration_sec — safer than hardcoding 100
        rate_fcpe = len(f0_fcpe) / duration_sec if duration_sec > 0 else 100.0
        rate_pesto = len(f0_pesto) / duration_sec if duration_sec > 0 else 100.0
        j.annotations.append(
            _build_pitch_contour_annotation(f0_fcpe, rate_fcpe, "torchfcpe", "analyze.stages.vocal_f0", duration_sec)
        )
        j.annotations.append(
            _build_pitch_contour_annotation(f0_pesto, rate_pesto, "pesto", "analyze.stages.vocal_f0", duration_sec)
        )

    # Validate but don't crash — if invalid, append warning
    try:
        j.validate(strict=True)
    except Exception as e:
        warnings.append(f"JAMS validation failed (writing anyway): {e}")

    j.save(str(jams_path), strict=False)
