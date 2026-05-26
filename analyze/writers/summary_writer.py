"""summary.json writer.

Assembles the compact educational digest from stage outputs + derivation.
Schema mirrors docs/superpowers/specs/2026-04-29-analyze-py-design.md
(summary.json section), with v1 deltas (sections=[], single_source agreement).

stems[] entry shapes
--------------------
Each melodic stem (vocals/bass/guitar/piano/other) takes one of two shapes:

  Transcribed (stem present):
    {
      "transcribed": true,      # explicit; absent only when the gate did not
                                # run (no stem WAV — see warnings)
      "notes": [...],           # per-note enrichment output
      "presence": {             # NEW: 3-signal measurement block
        "stem_rms_db": float,
        "max_other_rms_db": float | null,
        "masking_ratio_db": float | null,
        "active_frame_ratio": float,
        "in_band_fraction": float | null,
        "band_hz": [int, int] | null,
        "thresholds": {"masking_db": -26.0, "active_ratio": 0.05, "in_band_fraction": 0.5},
        "gates_tripped": [],
        "transcribed": true,
        "reason": null
      }
    }

  Gated (stem absent / phantom):
    {
      "transcribed": false,
      "reason": "masked by guitar at -31.4 dB",   # human-readable gate reason
      "presence": { ... }                           # same block; gates_tripped non-empty
    }

The drums entry takes one of two shapes depending on whether the drums stage
ran (see analyze/pipeline.py:_enrich_stems): either
  {transcribed: true, kick: [...], snare: [...], ...}  when LarsNet ran, or
  {transcribed: false, reason: ..., ratio_db: ...}     when the stage was skipped."""
from __future__ import annotations

import json
from importlib import metadata as importlib_metadata
from pathlib import Path

import analyze

# Stage names that have sidecars after WI-1/WI-6/WI-7/WI-8/WI-9 land.
_STAGES_WITH_SIDECARS = (
    "stems", "beats", "key", "chords", "vocal_f0", "beats_xcheck",
    "transcription", "transcription_piano",
    "stems_dynamics", "vocal_consensus_contour",
    # drums has its own schema-versioned summary, not the WI-1 sidecar; skip.
    # transcription_vocals removed 2026-05-04 with the homegrown F0→notes revert.
)


def _read_per_stage_params(cache_dir: Path) -> dict[str, dict]:
    """Read each stage's sidecar from disk and aggregate into a single dict.

    Stages without sidecars (or with corrupt ones) are silently omitted —
    we don't want sidecar reads to fail the summary write.
    """
    out: dict[str, dict] = {}
    for stage in _STAGES_WITH_SIDECARS:
        # Mirror the path resolution logic from analyze.sidecar:
        #   stems → stems_6s/.params.json; others → .params_<stage>.json
        if stage == "stems":
            sidecar_path = cache_dir / "stems_6s" / ".params.json"
        else:
            sidecar_path = cache_dir / f".params_{stage}.json"
        if not sidecar_path.exists():
            continue
        try:
            data = json.loads(sidecar_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out[stage] = {
            "schema_version": data.get("schema_version"),
            "params": data.get("params", {}),
        }
    return out


def _model_versions() -> dict[str, str]:
    versions = {}
    for tool in [
        "audio-separator", "madmom", "beat-this", "skey", "lv-chordia",
        "basic-pitch", "torchfcpe", "pesto", "jams", "pretty_midi", "librosa",
    ]:
        try:
            versions[tool] = importlib_metadata.version(tool)
        except Exception:
            versions[tool] = "unknown"
    return versions


def write_summary(
    summary_path: Path,
    mp3_path: Path,
    results: dict,
    derived: dict,
    warnings: list[str],
    duration_sec: float,
    stems_quality: str | None = None,
    cache_dir: Path | None = None,
    reconciliation: dict | None = None,
) -> None:
    chords_enriched = derived.get("chords_enriched", [])
    stems_enriched = derived.get("stems_enriched", {})

    # Convert MP3 path to both Windows and WSL views.
    abs_path = mp3_path.resolve()
    wsl_path = str(abs_path)
    if wsl_path.startswith("/mnt/"):
        # /mnt/c/... → C:/...
        parts = wsl_path.split("/", 3)
        if len(parts) >= 4:
            drive = parts[2].upper()
            windows_path = f"{drive}:\\" + parts[3].replace("/", "\\")
        else:
            windows_path = wsl_path
    else:
        windows_path = wsl_path

    summary = {
        "track": {
            "file": mp3_path.name,
            "windows_path": windows_path,
            "wsl_path": wsl_path,
            "duration_sec": float(duration_sec),
            "tempo_bpm": float(results["beats"]["bpm"]),
            "key": results["key"]["key"],
            "key_confidence": float(results["key"]["confidence"]),
            "time_signature": results["beats"].get("time_signature", "4/4"),
        },
        "sections": [],
        "downbeats": [round(float(t), 3) for t in results["beats"]["downbeats"]],
        "chords": chords_enriched,
        "stems": stems_enriched,
        "analysis": {
            "scale": derived.get("scale"),
            "modal_interchange_count": derived.get("modal_interchange_count", 0),
            "predominant_chord_loop": derived.get("predominant_chord_loop"),
            "loop_roman": derived.get("loop_roman"),
            "loop_appearances": derived.get("loop_appearances", []),
            "vocal_range": derived.get("vocal_range"),
        },
        "provenance": {
            "pipeline_version": analyze.__version__,
            "models": _model_versions(),
            "stems_quality": stems_quality,
            "warnings": list(warnings),
            "per_stage_params": _read_per_stage_params(cache_dir) if cache_dir else {},
            "reconciliation": reconciliation or {},
        },
    }
    if "identify" in results:
        summary["identify"] = results["identify"]

    if "essentia_extract" in results:
        from analyze.stages.essentia_extract import compute_agreement
        essentia_data = results["essentia_extract"]
        summary["essentia"] = essentia_data
        # compute_agreement reads .get("tempo_bpm") / .get("key") at top level;
        # in our summary those fields live under "track", so pass that sub-dict.
        agreement = compute_agreement(summary["track"], essentia_data)
        if agreement:
            summary["essentia_agreement"] = agreement
            # When the key cross-check disagrees, emit a parallel
            # `chords_alt_key` block so the webui's top-bar Key toggle can
            # swap the displayed roman numerals + functions + scale name to
            # Essentia's consensus key without a re-run. Only the
            # key-dependent fields are duplicated; the chord labels and
            # timestamps stay in summary.chords (key-independent).
            key_xc = agreement.get("key")
            if key_xc and key_xc.get("ok") is False and key_xc.get("essentia_consensus"):
                from analyze.derived.alt_key import derive_alt_key_block
                try:
                    summary["chords_alt_key"] = derive_alt_key_block(
                        chords_enriched,
                        derived.get("predominant_chord_loop"),
                        key_xc["essentia_consensus"],
                    )
                except ValueError as exc:
                    # Unparseable consensus key — surface as a warning rather
                    # than fail the summary write. The toggle just won't appear
                    # for this track on the client side.
                    summary["provenance"]["warnings"].append(
                        f"chords_alt_key skipped: {exc}"
                    )

    summary_path.write_text(json.dumps(summary, indent=2))
