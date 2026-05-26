"""Stage 6: per-stem polyphonic transcription router.

Dispatches each stem to its appropriate transcriber:
  - piano → transcription_piano (ByteDance HR-Piano specialist)
  - vocals, bass, guitar, other → transcription_basic (basic-pitch)

Drums are NOT transcribed here — see drums.py (Stage 9, ADTOF + LarsNet).

Reads stems_routing.json (written by stems.py / WI-6) instead of glob-
matching against stems_6s/. This decouples downstream from the orchestrator's
internal model layout: future stems-orchestrator changes (e.g. ensemble
separation) don't ripple through here.

Note on vocals (2026-05-04 revert): Phase A originally shipped a homegrown
F0→notes specialist (transcription_vocals.py) that read FCPE+PESTO output
and quantized to MIDI. The homegrown algorithm had several structural flaws
that produced silently-wrong note pitches on bimodal alternations and
F0-estimator octave-glitches. Reverted to basic-pitch on the vocals stem
(the pre-WI-3 baseline). A proper F0→notes specialist (e.g. crepe-notes,
or pyin's note-transcription mode) is deferred as a Phase A+B follow-up
and will slot back into TRANSCRIBERS["vocals"] when ready.

Outputs:
    cache_dir/midi/{vocals,bass,guitar,piano,other}.mid
    cache_dir/transcription_summary.json — per-stem dispatch result
"""
from __future__ import annotations

from pathlib import Path
import json
import sys

from analyze import sidecar, stems_routing
from analyze.stages import transcription_basic, transcription_piano

CANONICAL = "transcription_summary.json"
MIDI_SUBDIR = "midi"
SCHEMA_VERSION = 2

# Per-stem dispatch table. Adding a new specialist means: implement the
# stage module, then add its entry here. The router is otherwise generic.
TRANSCRIBERS: dict[str, str] = {
    "vocals": "basic",    # basic-pitch (revert from F0→notes specialist; see module docstring)
    "piano":  "piano",    # ByteDance HR-Piano via transcription_piano
    "bass":   "basic",    # basic-pitch
    "guitar": "basic",    # basic-pitch
    "other":  "basic",    # basic-pitch
}

DEFAULT_PARAMS: dict = {}


def cached(cache_dir: Path, **params) -> bool:
    p = {**DEFAULT_PARAMS, **params}
    if not (cache_dir / CANONICAL).exists():
        return False
    midi_dir = cache_dir / MIDI_SUBDIR
    if not all((midi_dir / f"{stem}.mid").exists() for stem in TRANSCRIBERS):
        return False
    return sidecar.matches(cache_dir, "transcription", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    """Dispatch each stem to its transcriber and write a unified summary.

    Per-stem params can be threaded via `params={'vocals': {...}, 'piano': {...}, ...}`.
    Stems not present in the routing file are skipped silently — that's how
    the router stays preset-agnostic (e.g. fast preset has no piano in some
    routings).
    """
    p = {**DEFAULT_PARAMS, **params}
    midi_out = cache_dir / MIDI_SUBDIR
    midi_out.mkdir(exist_ok=True)

    results: dict[str, dict] = {}
    for stem, transcriber_name in TRANSCRIBERS.items():
        stem_params = (p.get(stem) if isinstance(p, dict) else None) or {}
        try:
            if transcriber_name == "piano":
                # transcription_piano resolves its audio path via stems_routing
                # internally (with mp3 fallback). No path-passing needed here.
                pr = transcription_piano.run(mp3, cache_dir, **stem_params)
                results[stem] = {
                    "transcriber": "piano",
                    "notes": pr.get("n_notes", 0),
                    "midi": pr.get("midi", f"{MIDI_SUBDIR}/piano.mid"),
                }
            else:
                # basic-pitch: needs the actual stem WAV path. Read from routing.
                try:
                    wav_path = stems_routing.path_for(cache_dir, stem)
                except stems_routing.RoutingError as e:
                    # Routing missing this stem — likely fast-preset or a stem
                    # the orchestrator skipped. Don't crash the whole stage.
                    results[stem] = {"transcriber": "basic", "skipped": True, "reason": str(e)}
                    continue
                br = transcription_basic.run_for_stem(stem, wav_path, midi_out, params=stem_params or None)
                results[stem] = {**br, "transcriber": "basic"}
        except Exception as exc:
            # Per-stem failure should not kill the whole stage. The summary
            # captures the failure so downstream can decide what to do.
            results[stem] = {
                "transcriber": transcriber_name,
                "error": f"{type(exc).__name__}: {exc}",
            }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "stems": results,
    }
    (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
    sidecar.write(cache_dir, "transcription", p, schema_version=SCHEMA_VERSION)
    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    for stem, info in r["stems"].items():
        if "error" in info:
            print(f"{stem:<8} ERROR: {info['error']}")
        elif info.get("skipped"):
            print(f"{stem:<8} skipped: {info['reason']}")
        else:
            print(f"{stem:<8} {info.get('notes', '?'):>6} notes  ({info.get('transcriber')})")
