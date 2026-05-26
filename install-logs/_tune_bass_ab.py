"""A/B test bass transcription params on a single stem.

Usage (from WSL, project root, .venv active):
    python install-logs/_tune_bass_ab.py <slug>

Runs basic-pitch twice on cache/<slug>/stems_6s/*Bass*.wav with old and
proposed params. Writes both MIDI files to /tmp and reports comparative
stats. Does NOT touch cache/<slug>/midi/bass.mid.
"""
import sys
from pathlib import Path
import glob
import statistics

from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

OLD = dict(onset_threshold=0.4, minimum_note_length=100, minimum_frequency=27.5)
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
print(f"bass stem: {bass_wav}\n")


def midi_hz(midi):
    return 440.0 * (2 ** ((midi - 69) / 12.0))


def analyze(label, params, out_path):
    print(f"=== {label} ===  params={params}")
    _, midi_data, note_events = predict(
        bass_wav,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        multiple_pitch_bends=True,
        melodia_trick=True,
        **params,
    )
    midi_data.write(str(out_path))
    # note_events: list of (start, end, pitch, amplitude, pitch_bends)
    durs = [(e[1] - e[0]) for e in note_events]
    pitches = [e[2] for e in note_events]
    short_pct = 100.0 * sum(1 for d in durs if d < 0.10) / max(1, len(durs))
    above_g4 = sum(1 for p in pitches if midi_hz(p) > 400.0)
    print(f"  notes: {len(note_events)}")
    if durs:
        print(f"  duration ms: median={statistics.median(durs)*1000:.0f} "
              f"mean={statistics.mean(durs)*1000:.0f} "
              f"min={min(durs)*1000:.0f} max={max(durs)*1000:.0f}")
        print(f"  short (<100ms): {short_pct:.1f}%")
    if pitches:
        print(f"  pitch MIDI: min={min(pitches)} max={max(pitches)}  "
              f"({midi_hz(min(pitches)):.1f}-{midi_hz(max(pitches)):.1f} Hz)")
        print(f"  notes >400Hz (octave-error candidates): {above_g4} "
              f"({100.0*above_g4/len(pitches):.1f}%)")
    print(f"  midi: {out_path}\n")
    return note_events


old_events = analyze("OLD (current)", OLD, Path("/tmp/bass_old.mid"))
new_events = analyze("NEW (proposed)", NEW, Path("/tmp/bass_new.mid"))

print("=== DIFF ===")
print(f"  notes:   {len(old_events)} -> {len(new_events)} "
      f"(+{len(new_events) - len(old_events):+d}, "
      f"{100.0*(len(new_events)-len(old_events))/max(1,len(old_events)):+.1f}%)")
