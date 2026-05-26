#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import glob, json, os
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

stems_dir = os.path.join(os.environ["TEST_DIR"], "stems_6s")
out_dir = os.path.join(os.environ["TEST_DIR"], "midi")
os.makedirs(out_dir, exist_ok=True)

params = {
    "vocals": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "bass": dict(onset_threshold=0.4, minimum_note_length=100, minimum_frequency=27.5),
    "guitar": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
    "piano": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=27.5),
    "other": dict(onset_threshold=0.6, minimum_note_length=100, minimum_frequency=80),
}

results = {}
for wav in glob.glob(os.path.join(stems_dir, "*.wav")):
    name = os.path.basename(wav).lower()
    matched = next((key for key in params if key in name), None)
    if matched is None or "drum" in name:
        print("skip:", name)
        continue
    print("transcribing", matched)
    model_output, midi_data, note_events = predict(
        wav,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        multiple_pitch_bends=True,
        melodia_trick=True,
        **params[matched],
    )
    midi_path = os.path.join(out_dir, f"{matched}.mid")
    midi_data.write(midi_path)
    results[matched] = {"notes": len(note_events), "midi": midi_path}
    print(matched, len(note_events), "notes")

with open(os.path.join(os.environ["TEST_DIR"], "transcription_summary.json"), "w") as f:
    json.dump(results, f, indent=2)
print(json.dumps(results, indent=2))
PY
