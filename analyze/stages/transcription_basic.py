"""basic-pitch single-stem transcriber.

Extracted from the original transcription.py monolith so the router (WI-9)
can dispatch per-stem to either basic-pitch or a specialist (vocals →
transcription_vocals, piano → transcription_piano).

basic-pitch is retained for bass / guitar / other. Vocals and piano now go
to specialists per Phase A. The hyperparameter dicts here are the original
runbook-tuned values — DO NOT change them in this refactor (any tuning is
deferred to Phase E).
"""
from __future__ import annotations

from pathlib import Path
import json

# Per-stem basic-pitch hyperparameters. Calibrated per the runbook for the
# corpus we benchmarked April 2026. Vocals/piano are kept here because the
# router falls back to basic-pitch if a specialist transcriber fails (and
# because the values are reference-correct for the existing summary diffs).
BASIC_PITCH_PARAMS: dict[str, dict] = {
    "vocals": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "bass":   dict(onset_threshold=0.5, frame_threshold=0.4, minimum_note_length=50, minimum_frequency=27.5, maximum_frequency=400),
    "guitar": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "piano":  dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=27.5),
    "other":  dict(onset_threshold=0.6, minimum_note_length=100, minimum_frequency=80),
}


def run_for_stem(stem: str, wav_path: Path, midi_out_dir: Path, *, params: dict | None = None) -> dict:
    """Run basic-pitch on one stem WAV and write its MIDI.

    Returns {"notes": <count>, "midi": <relative midi path>}.
    """
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    # Stem-specific defaults; caller can override via `params` kwarg.
    p = dict(BASIC_PITCH_PARAMS.get(stem, BASIC_PITCH_PARAMS["other"]))
    if params:
        p.update(params)

    midi_out_dir.mkdir(exist_ok=True)
    midi_path = midi_out_dir / f"{stem}.mid"

    _, midi_data, note_events = predict(
        str(wav_path),
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        multiple_pitch_bends=True,
        melodia_trick=True,
        **p,
    )
    midi_data.write(str(midi_path))
    return {"notes": len(note_events), "midi": str(midi_path)}
