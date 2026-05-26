"""Apply the new bass-params transcription to a single track's cache.

Usage (from WSL, project root, .venv active):
    python install-logs/_apply_bass_new.py <slug>

Re-runs basic-pitch on the bass stem with the proposed params and overwrites
cache/<slug>/midi/bass.mid in place. Does NOT modify transcription.py.
"""
import sys
import glob
from pathlib import Path

from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

NEW = dict(
    onset_threshold=0.30,
    frame_threshold=0.20,
    minimum_note_length=50,
    minimum_frequency=27.5,
    maximum_frequency=400,
)

slug = sys.argv[1]
cache = Path(f"cache/{slug}")
bass_wav = next(iter(glob.glob(str(cache / "stems_6s" / "*Bass*.wav"))), None)
assert bass_wav, f"no Bass stem under {cache}/stems_6s/"
target = cache / "midi" / "bass.mid"
print(f"stem:   {bass_wav}")
print(f"target: {target}")
print(f"params: {NEW}")

_, midi_data, note_events = predict(
    bass_wav,
    model_or_model_path=ICASSP_2022_MODEL_PATH,
    multiple_pitch_bends=True,
    melodia_trick=True,
    **NEW,
)
midi_data.write(str(target))
print(f"wrote {len(note_events)} notes -> {target}")
