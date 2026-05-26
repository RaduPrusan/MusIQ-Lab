#!/usr/bin/env bash
# Re-run Phase 6 of prompts/test-stack-torch27.md against the test MP3.
# Transcribes each stage's bash body verbatim from the runbook; saves outputs
# to $TEST_DIR (= cache/gorillaz_silent_running/), overwriting prior artifacts.
#
# Invoked as:  wsl -- bash /mnt/f/- Projects\ -/ClaudeCode/MusIQ-Lab/install-logs/rerun-mp3.sh
#
# Use `set -e` so the first stage failure halts the run; phase markers are
# `==>` lines that the Monitor filter watches for.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
# shellcheck disable=SC1091
source cache/gorillaz_silent_running/env.sh

echo "==> Phase 6 rerun starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "    TEST_MP3: $TEST_MP3"
echo "    TEST_DIR: $TEST_DIR"
test -r "$TEST_MP3"
python --version
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# ---------------------------------------------------------------------------
echo "==> Stage 1: stem separation (htdemucs_6s + BS-RoFormer)"
# ---------------------------------------------------------------------------
audio-separator "$TEST_MP3" \
  --model_filename htdemucs_6s.yaml \
  --output_dir "$TEST_DIR/stems_6s/" \
  --output_format WAV
audio-separator "$TEST_MP3" \
  --model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt \
  --output_dir "$TEST_DIR/stems_bsroformer/" \
  --output_format WAV
echo "    stems written:"
find "$TEST_DIR" -maxdepth 2 -type f -name "*.wav" -printf "    %p\n" | sort

# ---------------------------------------------------------------------------
echo "==> Stage 2a: madmom downbeats and tempo"
# ---------------------------------------------------------------------------
python - <<'PY'
import json, os
import numpy as np
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

mp3 = os.environ["TEST_MP3"]
activations = RNNDownBeatProcessor()(mp3)
tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
beats_with_pos = tracker(activations)

beats = [float(t) for t, _ in beats_with_pos]
downbeats = [float(t) for t, pos in beats_with_pos if int(pos) == 1]

if len(beats) >= 2:
    diffs = np.diff(beats)
    median_ibi = float(np.median(diffs))
    bpm = 60.0 / median_ibi if median_ibi > 0 else 0.0
else:
    bpm = 0.0

out = {
    "bpm": float(bpm),
    "beats": beats,
    "downbeats": downbeats,
    "n_beats": len(beats),
    "n_downbeats": len(downbeats),
    "first_8_downbeats": [round(t, 3) for t in downbeats[:8]],
}
with open(os.path.join(os.environ["TEST_DIR"], "madmom_downbeats.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ["bpm", "n_beats", "n_downbeats", "first_8_downbeats"]}, indent=2))
PY

# ---------------------------------------------------------------------------
echo "==> Stage 2b: sections (deferred placeholder)"
# ---------------------------------------------------------------------------
python - <<'PY'
import json, os
out = {
    "status": "deferred",
    "reason": "No segmenter installed in this stack; allin1 dropped due to NATTEN ABI/API breakage.",
}
with open(os.path.join(os.environ["TEST_DIR"], "sections.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
PY

# ---------------------------------------------------------------------------
echo "==> Stage 3: beat-this"
# ---------------------------------------------------------------------------
python - <<'PY'
import json, os
from beat_this.inference import File2Beats

model = File2Beats(checkpoint_path="final0", device="cuda")
beats, downbeats = model(os.environ["TEST_MP3"])
out = {
    "beats": [float(t) for t in beats],
    "downbeats": [float(t) for t in downbeats],
    "n_beats": len(beats),
    "n_downbeats": len(downbeats),
    "first_8_beats": [round(float(t), 3) for t in beats[:8]],
    "first_8_downbeats": [round(float(t), 3) for t in downbeats[:8]],
}
with open(os.path.join(os.environ["TEST_DIR"], "beat_this.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ["n_beats", "n_downbeats", "first_8_beats", "first_8_downbeats"]}, indent=2))
PY

# ---------------------------------------------------------------------------
echo "==> Stage 4: skey key detection (with librosa K-S fallback)"
# ---------------------------------------------------------------------------
python - <<'PY'
import json, os

key = conf = src = None
errors = []

try:
    from skey.key_detection import detect_key
    result = detect_key(os.environ["TEST_MP3"], device="cuda", cli=False)
    if result:
        key = result[0] if isinstance(result, list) else str(result)
        conf = 1.0
        src = "skey.detect_key"
except Exception as exc:
    errors.append(f"skey.detect_key failed: {type(exc).__name__}: {exc}")

if not key or key == "error":
    import librosa, numpy as np
    src = "librosa_ks"
    KS_MAJ = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    KS_MIN = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
    y, sr = librosa.load(os.environ["TEST_MP3"], duration=120)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = max(
        [(notes[i] + ":" + mode, np.corrcoef(np.roll(chroma, -i), profile)[0, 1])
         for i in range(12) for mode, profile in [("major", KS_MAJ), ("minor", KS_MIN)]],
        key=lambda row: row[1],
    )
    key, conf = best[0], float(best[1])

out = {"key": str(key), "confidence": float(conf), "source": src, "errors": errors}
with open(os.path.join(os.environ["TEST_DIR"], "skey.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
PY

# ---------------------------------------------------------------------------
echo "==> Stage 5: lv-chordia chord recognition"
# ---------------------------------------------------------------------------
python - <<'PY'
import json, os

chords = None
errors = []

try:
    from lv_chordia.chord_recognition import chord_recognition
    raw = chord_recognition(os.environ["TEST_MP3"], chord_dict_name="submission")
    chords = [
        {
            "start": float(item.get("start_time", item.get("start", 0.0))),
            "end": float(item.get("end_time", item.get("end", 0.0))),
            "label": str(item.get("chord", item.get("label", "N"))),
        }
        for item in raw
    ]
except Exception as exc:
    errors.append(f"lv-chordia python API failed: {type(exc).__name__}: {exc}")

if chords is None:
    raise SystemExit("\n".join(errors))

with open(os.path.join(os.environ["TEST_DIR"], "chords.json"), "w") as f:
    json.dump(chords, f, indent=2)

print(f"Found {len(chords)} chord events")
for c in chords[:12]:
    print(f"{c['start']:7.2f}-{c['end']:7.2f}: {c['label']}")
if errors:
    print("Fallback notes:")
    for err in errors:
        print(err)
PY

# ---------------------------------------------------------------------------
echo "==> Stage 6: Basic Pitch per harmonic stem"
# ---------------------------------------------------------------------------
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
for wav in sorted(glob.glob(os.path.join(stems_dir, "*.wav"))):
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

# ---------------------------------------------------------------------------
echo "==> Stage 7: vocal F0 via FCPE + PESTO"
# ---------------------------------------------------------------------------
python - <<'PY'
import glob, json, os
import librosa
import numpy as np
import torch
from torchfcpe import spawn_bundled_infer_model

vocals_path = next(
    path for path in glob.glob(os.path.join(os.environ["TEST_DIR"], "stems_6s/*.wav"))
    if "vocal" in os.path.basename(path).lower()
)
print("vocals stem:", vocals_path)

audio, sr = librosa.load(vocals_path, sr=16000, mono=True)
audio_cuda = torch.from_numpy(audio).unsqueeze(0).to("cuda")

fcpe = spawn_bundled_infer_model(device="cuda")
f0_fcpe = fcpe.infer(
    audio_cuda,
    sr=16000,
    decoder_mode="local_argmax",
    threshold=0.006,
    f0_min=80,
    f0_max=880,
    interp_uv=False,
).squeeze().detach().cpu().numpy()
print("FCPE frames:", len(f0_fcpe), "voiced:", float((f0_fcpe > 0).mean()))

import pesto
audio_cpu = torch.from_numpy(audio)
ts, f0_pesto, conf_pesto, _ = pesto.predict(
    audio_cpu,
    sr=16000,
    step_size=10.0,
    inference_mode="cqt",
)
if hasattr(f0_pesto, "detach"):
    f0_pesto = f0_pesto.detach().cpu().numpy()
else:
    f0_pesto = np.asarray(f0_pesto)
print("PESTO frames:", len(f0_pesto))

n = min(len(f0_fcpe), len(f0_pesto))
fcpe_n = f0_fcpe[:n]
pesto_n = f0_pesto[:n]
both_voiced = (fcpe_n > 0) & (pesto_n > 0)
agree_50c = both_voiced & (np.abs(1200 * np.log2(fcpe_n / np.maximum(pesto_n, 1e-6))) < 50)
agreement = float(agree_50c.sum() / max(both_voiced.sum(), 1))
print("Voiced agreement within 50 cents:", agreement)

np.savez_compressed(os.path.join(os.environ["TEST_DIR"], "vocal_f0.npz"), fcpe=f0_fcpe, pesto=f0_pesto)
with open(os.path.join(os.environ["TEST_DIR"], "vocal_f0_summary.json"), "w") as f:
    json.dump({"fcpe_frames": len(f0_fcpe), "pesto_frames": len(f0_pesto), "agreement_50c": agreement}, f, indent=2)
PY

# ---------------------------------------------------------------------------
echo "==> Stage 8: reconciliation skeleton"
# ---------------------------------------------------------------------------
python - <<'PY'
import json, os

test_dir = os.environ["TEST_DIR"]
madmom_data = json.load(open(os.path.join(test_dir, "madmom_downbeats.json")))
chords = json.load(open(os.path.join(test_dir, "chords.json")))
key_data = json.load(open(os.path.join(test_dir, "skey.json")))

downbeats = madmom_data["downbeats"]
if not downbeats:
    raise SystemExit("No downbeats available for snapping")

def nearest_downbeat(t):
    return min(downbeats, key=lambda d: abs(d - t))

summary = {
    "key": key_data["key"],
    "key_source": key_data["source"],
    "tempo_bpm": madmom_data["bpm"],
    "first_12_chords_snapped": [],
}
for chord in chords[:12]:
    summary["first_12_chords_snapped"].append({
        "snap_start": round(nearest_downbeat(chord["start"]), 3),
        "original_start": round(chord["start"], 3),
        "label": chord["label"],
    })

with open(os.path.join(test_dir, "reconciliation_preview.json"), "w") as f:
    json.dump(summary, f, indent=2)
print(json.dumps(summary, indent=2))
PY

echo "==> Phase 6 rerun complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
ls -la "$TEST_DIR" | awk '{print "    "$0}'
