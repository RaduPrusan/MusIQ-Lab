"""Stage 5b: piano MIDI from ByteDance High-Resolution Piano Transcription.

Replaces basic-pitch on the piano stem. ByteDance HR-Piano (Kong et al. 2021)
hits ~96% F1 on MAPS vs basic-pitch's ~80% on the same. Trained predominantly
on solo piano; robust to background but produces extra notes when other
instruments are loud — gate with transcribe_full_mix=True only when the piano
stem RMS is too low or shows obvious bleed.

Two routing options for the piano signal (per spec §3):
  - Stem-based (default): read stems_routing.json's piano.path, transcribe that.
  - Mix-based: transcribe the original mp3 directly. Set transcribe_full_mix=True.

Outputs:
    cache_dir/midi/piano.mid                     — MIDI file
    cache_dir/transcription_piano.json           — note events with details
"""
from __future__ import annotations

from pathlib import Path
import json
import sys

from analyze import sidecar
from analyze import stems_routing

CANONICAL = "transcription_piano.json"
SCHEMA_VERSION = 1

DEFAULT_PARAMS = {
    "onset_threshold":         0.3,   # ByteDance recommended default
    "offset_threshold":        0.3,
    "frame_threshold":         0.3,
    "pedal_offset_threshold":  0.2,
    "transcribe_full_mix":     False,
}


def cached(cache_dir: Path, **params) -> bool:
    p = {**DEFAULT_PARAMS, **params}
    if not (cache_dir / CANONICAL).exists():
        return False
    if not (cache_dir / "midi" / "piano.mid").exists():
        return False
    return sidecar.matches(cache_dir, "transcription_piano", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def _resolve_audio_path(mp3: Path, cache_dir: Path, transcribe_full_mix: bool) -> Path:
    """Pick the audio source — original mix or stems_routing's piano.

    Falls back to the original mix if the routing file is missing or has no
    piano entry (e.g. the piano stem failed separation). Raises if the
    fallback mp3 itself is missing — that's a real error, not a routing
    miss."""
    if transcribe_full_mix:
        return mp3
    try:
        return stems_routing.path_for(cache_dir, "piano")
    except stems_routing.RoutingError:
        # Routing missing or no piano entry → fall back to the original mix.
        # This still lets the stage work for fast-preset runs or stems that
        # didn't produce a piano output for some reason.
        return mp3


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    """Transcribe the piano signal to MIDI via ByteDance HR-Piano."""
    p = {**DEFAULT_PARAMS, **params}
    audio_src = _resolve_audio_path(mp3, cache_dir, p["transcribe_full_mix"])

    # ByteDance HR-Piano expects 16kHz mono float32. librosa is already a dep.
    import librosa
    audio, _sr = librosa.load(str(audio_src), sr=16000, mono=True)

    # Output paths.
    midi_dir = cache_dir / "midi"
    midi_dir.mkdir(exist_ok=True)
    midi_path = midi_dir / "piano.mid"

    try:
        from piano_transcription_inference import PianoTranscription
        transcriber = PianoTranscription(
            device="cuda",
            checkpoint_path=None,  # use default; weights cached in user dir
        )
        # The .transcribe() return dict varies across versions; we capture
        # whatever's there for forward-compat. The MIDI write side-effect is
        # what we mostly care about.
        out = transcriber.transcribe(audio, str(midi_path))
    finally:
        # ByteDance HR-Piano constructs a Regress_onset_offset_frame_velocity_CRNN
        # which holds GRUs + a few CNN heads on CUDA. Same memory-leak family as
        # lv-chordia: nn.Module reference cycles + Adam optimizer state stranded
        # on the device after `transcriber` goes out of scope. Two gc passes
        # break the cycles before empty_cache returns blocks to the driver.
        # See spec §8 risks for measured background.
        import gc
        gc.collect()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # Normalize note events for the JSON summary. ByteDance returns
    # `est_note_events` as a list of dicts with onset_time, offset_time,
    # midi_note, velocity (0-127). Be defensive — if the field names differ
    # in the installed version, prefer raw dicts over crashing.
    raw_notes = out.get("est_note_events") if isinstance(out, dict) else None
    notes: list[dict] = []
    if raw_notes:
        for n in raw_notes:
            onset = float(n.get("onset_time", n.get("onset", 0.0)))
            offset = float(n.get("offset_time", n.get("offset", 0.0)))
            notes.append({
                "onset":    onset,
                "duration": offset - onset,
                "pitch":    int(n.get("midi_note", n.get("pitch", 0))),
                "velocity": int(n.get("velocity", 80)),
            })

    summary = {
        "schema_version": SCHEMA_VERSION,
        "n_notes":        len(notes),
        "notes":          notes,
        "midi":           "midi/piano.mid",
        "audio_source":   (
            str(audio_src.relative_to(cache_dir))
            if cache_dir in audio_src.parents
            else str(audio_src.name)
        ),
    }
    (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
    sidecar.write(cache_dir, "transcription_piano", p, schema_version=SCHEMA_VERSION)
    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    print(f"piano: {r['n_notes']} notes (source: {r['audio_source']})")
