"""Webui-side mirror of analyze.stages.* SCHEMA_VERSION + DEFAULT_PARAMS.

This module exists because the `analyze` package only imports on WSL Python
3.11 (refuse-to-import guard in `analyze/__init__.py`), so the Windows-side
webui can't introspect SCHEMA_VERSION directly. The manifest below mirrors
the stage constants so we can probe staleness on disk without invoking the
pipeline.

**Drift prevention:** `tests/test_stage_manifest_in_sync.py` imports each
analyze stage and asserts the manifest matches. The test skips on non-WSL
runners (where analyze.* can't import), so CI on Linux/WSL is the gate.

Schema entries:
    name         — stage identifier (matches analyze.stages.<name>)
    schema_version — current SCHEMA_VERSION constant in that stage
    canonical    — list of relative paths inside cache/<slug>/ that must
                   ALL exist for the stage to be considered "ran". When
                   absent and no sidecar is present, the stage is "skipped"
                   not "stale".
    sidecar      — relative path to the per-stage sidecar (or None for
                   stages with embedded version, like drums)
    params       — expected DEFAULT_PARAMS dict, or None to skip the params
                   check (stages where DEFAULT_PARAMS depends on a runtime
                   choice like stems quality)
    optional     — whether to surface as "skipped" instead of "stale" when
                   no output and no sidecar exist. Required stages (stems,
                   beats, key, chords, transcription) are not optional.
    version_kind — "sidecar" (default — schema_version lives in the
                   sidecar) or "embedded_json" (version lives inside the
                   canonical JSON, under the key in `version_key`)
    version_key  — JSON key for "embedded_json" stages (default "version")
"""
from __future__ import annotations

from typing import Any


# Mirror of analyze.stages.vocal_consensus_contour.DEFAULT_PARAMS at SCHEMA_VERSION=3.
_VOCAL_CONSENSUS_PARAMS: dict[str, Any] = {
    "rms_floor_db": -45.0,
    "cents_agreement_threshold": 50.0,
    "vocal_midi_min": 36,   # VOCAL_MIDI_MIN — C2 ≈ 65 Hz
    "vocal_midi_max": 95,   # VOCAL_MIDI_MAX — B6 ≈ 1976 Hz
    "anchor_validation_enabled": True,
    "anchor_validation_min_frames": 5,
    "anchor_validation_conf_threshold": 0.4,
    "viterbi_enabled": True,
    "viterbi_lambda_freq": 1.0,
    "viterbi_cents_normalizer": 300.0,
    "viterbi_lambda_octave": 5.0,
    "viterbi_octave_sigma": 150.0,
    "viterbi_lambda_voicing_on": 3.0,
    "viterbi_lambda_voicing_off": 3.0,
    "viterbi_anchor_prox_bonus": 1.0,
    "viterbi_anchor_prox_sigma": 100.0,
}

# Mirror of analyze.stages.stems_dynamics.DEFAULT_PARAMS at SCHEMA_VERSION=1.
_STEMS_DYNAMICS_PARAMS: dict[str, Any] = {
    "fps": 100,
    "frame_length": 2048,
    "target_sr": 44100,
}

# Mirror of analyze.stages.transcription_piano.DEFAULT_PARAMS at SCHEMA_VERSION=1.
_TRANSCRIPTION_PIANO_PARAMS: dict[str, Any] = {
    "onset_threshold": 0.3,
    "offset_threshold": 0.3,
    "frame_threshold": 0.3,
    "pedal_offset_threshold": 0.2,
    "transcribe_full_mix": False,
}


STAGES: list[dict[str, Any]] = [
    # --- Required stages (hard-fail in pipeline, always have outputs on a
    # successfully analyzed track) ---
    {
        "name": "stems",
        "schema_version": 1,
        # stems lives in a subdir; params depend on the quality preset
        # chosen at run time, so we don't statically pin them — only the
        # schema_version is checked.
        "canonical": ["stems_routing.json"],
        "sidecar": "stems_6s/.params.json",
        "params": None,
        "optional": False,
    },
    {
        "name": "beats",
        "schema_version": 2,
        "canonical": ["madmom_downbeats.json"],
        "sidecar": ".params_beats.json",
        "params": {},
        "optional": False,
    },
    {
        "name": "key",
        "schema_version": 1,
        "canonical": ["skey.json"],
        "sidecar": ".params_key.json",
        "params": {},
        "optional": False,
    },
    {
        "name": "chords",
        "schema_version": 1,
        "canonical": ["chords.json"],
        "sidecar": ".params_chords.json",
        "params": {},
        "optional": False,
    },
    {
        "name": "transcription",
        "schema_version": 2,
        "canonical": ["transcription_summary.json"],
        "sidecar": ".params_transcription.json",
        "params": {},
        "optional": False,
    },
    # --- Optional stages (soft-fail; absence means "skipped on this track") ---
    {
        "name": "beats_xcheck",
        "schema_version": 1,
        "canonical": ["beat_this.json"],
        "sidecar": ".params_beats_xcheck.json",
        "params": {},
        "optional": True,
    },
    {
        "name": "vocal_f0",
        "schema_version": 2,
        # Both .npz and the summary JSON are written by a successful run.
        "canonical": ["vocal_f0.npz", "vocal_f0_summary.json"],
        "sidecar": ".params_vocal_f0.json",
        "params": {},
        "optional": True,
    },
    {
        "name": "vocal_consensus_contour",
        "schema_version": 3,
        "canonical": ["vocal_consensus.npz", "vocal_consensus.json"],
        "sidecar": ".params_vocal_consensus_contour.json",
        "params": _VOCAL_CONSENSUS_PARAMS,
        "optional": True,
    },
    {
        "name": "stems_dynamics",
        "schema_version": 1,
        # stems_dynamics writes per-stem .npz into a `dynamics/` subdir;
        # we treat the dir's existence as the "ran" signal and let the
        # sidecar carry the canonical version probe.
        "canonical": ["dynamics"],
        "sidecar": ".params_stems_dynamics.json",
        "params": _STEMS_DYNAMICS_PARAMS,
        "optional": True,
    },
    {
        "name": "drums",
        "schema_version": 4,
        "canonical": ["drums_summary.json"],
        # Drums embeds its version inside the canonical JSON (key="version")
        # instead of a separate sidecar — older v1/v2 schemas used a
        # different algorithm and the upgrade path is to read the version
        # from the file itself.
        "sidecar": None,
        "params": None,
        "optional": True,
        "version_kind": "embedded_json",
        "version_key": "version",
    },
    {
        "name": "identify",
        "schema_version": 5,
        "canonical": ["identify.json"],
        "sidecar": ".params_identify.json",
        "params": {
            "silence_strip_enabled": True,
            "silence_strip_threshold_db": -50,
            "silence_strip_min_duration_sec": 0.3,
            "silence_strip_gate_sec": 0.3,
            "fallback_enabled": True,
            # Round 5: title-sim lowered to 0.75, duration-variance
            # tightened to 0.03 as a compensating guard.
            "fallback_min_title_similarity": 0.75,
            "fallback_max_duration_variance": 0.03,
            # Round 5 (Item 1) — artist-plausibility gate.
            "artist_plausibility_min_similarity": 0.30,
            "artist_plausibility_title_fallback_threshold": 0.30,
        },
        "optional": True,
    },
    {
        "name": "essentia_extract",
        "schema_version": 1,
        "canonical": ["essentia.json"],
        "sidecar": ".params_essentia_extract.json",
        "params": {},
        "optional": True,
    },
    {
        "name": "transcription_piano",
        "schema_version": 1,
        "canonical": ["transcription_piano.json"],
        "sidecar": ".params_transcription_piano.json",
        "params": _TRANSCRIPTION_PIANO_PARAMS,
        "optional": True,
    },
]


# Lookup helper kept here so callers don't reimport the list.
def by_name(name: str) -> dict[str, Any] | None:
    for s in STAGES:
        if s["name"] == name:
            return s
    return None
