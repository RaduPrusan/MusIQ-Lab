"""Pipeline orchestrator: runs stages 1-8 + derivation, writes JAMS + summary.json.

Required stages (hard-fail): stems, beats, key, chords, transcription.
Optional stages (soft-fail): beats_xcheck, vocal_f0.

Always-on derivations: theory (Roman numerals + function), loop_detect, vocal_range.
Per-note enrichment runs over all transcribed stems.
"""
from __future__ import annotations

import bisect
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from analyze import cache as cache_mod
from analyze.derived.loop_detect import predominant_chord_loop
from analyze.derived.note_enrichment import enrich_note
from analyze.derived.stem_presence import (
    compute_stems_rms_db,
    filter_phantom_notes,
    measure_stem_presence,
)
from analyze.derived.theory import (
    Chord,
    function_for,
    parse_chord,
    parse_key,
    pc_to_note_name,
    roman_for,
    scale_name,
)
from analyze.derived.vocal_range import is_instrumental, vocal_range_from_midi
from analyze.stages import (
    beats,
    beats_xcheck,
    chords as chords_stage,
    drums as drums_stage,
    essentia_extract,
    identify as identify_stage,
    key as key_stage,
    stems,
    stems_dynamics,
    transcription,
    vocal_consensus_contour,
    vocal_f0,
)
from analyze.writers.jams_writer import write_jams
from analyze.writers.summary_writer import write_summary


REQUIRED_STAGES = [
    ("stems", stems),
    ("beats", beats),
    ("key", key_stage),
    ("chords", chords_stage),
    ("transcription", transcription),
]
OPTIONAL_STAGES = [
    ("vocal_f0", vocal_f0),
    ("beats_xcheck", beats_xcheck),
    # Drums is optional because LarsNet ships separately (CC BY-NC 4.0 weights);
    # see scripts/install-larsnet.sh. If the vendor dir is empty the stage raises
    # and the pipeline soft-fails it without affecting the rest of the analysis.
    ("drums", drums_stage),
    # stems_dynamics produces per-stem RMS envelopes for the consensus
    # voicing floor gate and future dynamics-aware metadata. Optional so
    # an old cache without dynamics/ on disk doesn't fail; downstream
    # consumers no-op gracefully when dynamics is missing.
    ("stems_dynamics", stems_dynamics),
    # vocal_consensus_contour fuses FCPE/PESTO/basic-pitch (+ optional
    # RMS) into a cleaned consensus F0 line and per-note intonation.
    # Optional because it depends on vocal_f0 + transcription succeeding;
    # if vocals.mid is empty (instrumental track) the stage produces a
    # stub summary and the rest of the pipeline is unaffected.
    ("vocal_consensus_contour", vocal_consensus_contour),
    # AcoustID + MusicBrainz canonical identity. Optional because it
    # requires both a network connection and a valid ACOUSTID_API_KEY;
    # cleanly soft-fails to {identified: false, reason} otherwise.
    ("identify", identify_stage),
    # Essentia second-opinion: tempo / key / loudness / mood. Heavy native
    # C++ install (~200MB + ~30MB SVM models in analyze/vendor/essentia-models/).
    # Optional — soft-fails to {extracted: false, reason} when essentia is
    # not installed. Runs LAST so the cross-check can read beats + key.
    ("essentia_extract", essentia_extract),
]

# Stage execution order respecting STAGE_DEPS. The downstream consumer
# of vocal_f0.npz is vocal_consensus_contour (the orchestrator that fuses
# FCPE / PESTO / basic-pitch into a per-frame consensus_f0 contour). It
# is OPTIONAL and runs last, so its inputs (vocal_f0 + transcription)
# must already be cached by the time it executes.
#
# (Historical: the WI-7 transcription_vocals specialist also read this
# file and was the original reason for the explicit vocal_f0 → transcription
# ordering. That module was reverted in commit 574f3ab — vocals now route
# through basic-pitch like the other non-piano stems — so the ordering is
# kept solely to satisfy vocal_consensus_contour's deps via the explicit
# graph in STAGE_DEPS below.)
_STAGE_EXECUTION_ORDER = [
    ("stems", stems),
    ("stems_dynamics", stems_dynamics),  # cheap; runs right after stems
    ("identify", identify_stage),  # NEW — runs early, network-bound
    ("beats", beats),
    ("key", key_stage),
    ("chords", chords_stage),
    ("vocal_f0", vocal_f0),       # MUST run before transcription
    ("transcription", transcription),
    ("beats_xcheck", beats_xcheck),
    ("drums", drums_stage),
    # Consumes vocal_f0 + transcription (+ optional stems_dynamics);
    # placed last so all its inputs have settled.
    ("vocal_consensus_contour", vocal_consensus_contour),
    ("essentia_extract", essentia_extract),  # NEW — runs last; reads beats + key for cross-check
]

# Directed acyclic dependency graph: stage → set of stages that must have run
# (and whose outputs must be cached) before this stage can run.
STAGE_DEPS: dict[str, frozenset[str]] = {
    "stems":                     frozenset(),
    "stems_dynamics":            frozenset({"stems"}),
    "identify":                  frozenset(),  # NEW — reads source MP3 directly
    "beats":                     frozenset(),
    "key":                       frozenset(),
    "chords":                    frozenset(),
    "transcription":             frozenset({"stems"}),
    "beats_xcheck":              frozenset(),
    "vocal_f0":                  frozenset({"stems"}),
    "drums":                     frozenset({"stems"}),
    # stems_dynamics is a SOFT dep — when absent the floor gate no-ops —
    # so it's not in the hard-dep set even though the stage uses it.
    "vocal_consensus_contour":   frozenset({"vocal_f0", "transcription"}),
    "essentia_extract":          frozenset({"beats", "key"}),
}


def downstream_of(stage: str) -> set[str]:
    """Return the transitive closure of stages that depend on `stage`."""
    out: set[str] = set()
    frontier = [stage]
    while frontier:
        s = frontier.pop()
        for candidate, deps in STAGE_DEPS.items():
            if s in deps and candidate not in out:
                out.add(candidate)
                frontier.append(candidate)
    return out


class PipelineError(RuntimeError):
    pass


@dataclass
class AnalyzeResult:
    jams_path: Path
    summary_path: Path
    warnings: list[str]


def _log(msg: str, *, quiet: bool) -> None:
    if not quiet:
        print(msg, file=sys.stderr, flush=True)


def _probe_duration_sec(mp3_path: Path) -> float:
    # ffprobe scans the container instead of trusting MP3 Xing/VBR headers,
    # which can lie (observed: a Charlie Puth MP3 reported 1712s vs actual 301s).
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(mp3_path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _enrich_chords(chords_raw: list[dict], key) -> list[dict]:
    """Build the chords[] entries for summary.json with roman/function/decomposition."""
    enriched = []
    for c in chords_raw:
        chord = parse_chord(c["label"])
        roman = roman_for(chord, key)
        function = function_for(roman, key.mode) if roman else None
        out = {
            "start": float(c["start"]),
            "end": float(c["end"]),
            "label": c["label"],
            "root": pc_to_note_name(chord.root_pc) if chord.root_pc is not None else None,
            "bass": pc_to_note_name(chord.bass_pc) if chord.bass_pc is not None else None,
            "type": chord.quality,
            "roman": roman,
            "function": function,
            "confidence": 1.0,
            "agreement": "single_source",
        }
        enriched.append(out)
    return enriched


_STEM_LABEL_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _find_stem_wav(stems_dir: Path, stem_name: str) -> Optional[Path]:
    """Locate the htdemucs/bs_roformer WAV for a melodic stem.

    Matches the demucs-family label token ``_(<Stem>)_`` rather than a free
    substring, so titles that contain a stem keyword (e.g. "Hurt (Piano
    Tutorial)") don't shadow the actual stem label. The token always shows
    up as ``..._(Piano)_htdemucs_6s.wav`` / ``..._(Vocals)_model_bs_...``.
    """
    import re
    pat = _STEM_LABEL_RE_CACHE.get(stem_name)
    if pat is None:
        pat = re.compile(r"_\(" + re.escape(stem_name) + r"\)_", re.IGNORECASE)
        _STEM_LABEL_RE_CACHE[stem_name] = pat
    for wav in stems_dir.glob("*.wav"):
        if pat.search(wav.name):
            return wav
    return None


MELODIC_STEMS = ("vocals", "bass", "guitar", "piano", "other")


def _enrich_stems(
    transcription_result: dict,
    chords_raw: list[dict],
    key,
    cache_dir: Path,
    drums_result: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Build stems.<stem>.notes[] with per-note enrichment for each transcribed
    stem. The drums entry has a different shape (per-substem onset arrays
    instead of pitched notes); see drums_stage for details.

    For melodic stems, ``measure_stem_presence()`` is called before enrichment.
    If any of its three signals (inter-stem masking, active-frame ratio, or
    in-band energy fraction) fires, the stem is marked ``transcribed: false``
    and enrichment is skipped entirely.  When the stem passes the gate,
    ``filter_phantom_notes()`` removes obvious phantom notes before the
    per-note enrichment loop runs.  The full ``presence`` measurement dict is
    always included in the output for diagnostic transparency.

    Gate decisions are also pushed onto the optional ``warnings`` list so they
    surface in ``summary.provenance.warnings`` for log/CI inspection.

    WI-9 changed the transcription stage's return shape from a flat
    ``{stem: {notes, midi}}`` dict to the router shape
    ``{"schema_version": int, "stems": {stem: {transcriber, ...}, ...}}``.
    Both shapes are tolerated for forward/backward compatibility with old caches.
    """
    import pretty_midi

    stems_6s_dir = cache_dir / "stems_6s"

    # Tolerate both the new router shape (WI-9+) and the legacy flat shape.
    if isinstance(transcription_result, dict) and "stems" in transcription_result:
        stems_iter = transcription_result["stems"]
    else:
        stems_iter = transcription_result  # legacy flat shape

    # Precompute streaming RMS-dBFS once per melodic stem WAV. Without this,
    # each WAV is re-streamed N times (once as the test stem + N−1 times as an
    # "other" stem in the loop below) — for 5 melodic stems that's 25 reads of
    # tens-of-MB files. With the cache it collapses to 5 reads. The
    # measure_stem_presence() fallback path handles missing entries safely.
    melodic_wavs: dict[str, Path] = {}
    for _name in MELODIC_STEMS:
        _w = _find_stem_wav(stems_6s_dir, _name)
        if _w is not None and _w.exists():
            melodic_wavs[_name] = _w
    rms_db_map = compute_stems_rms_db(melodic_wavs)

    out: dict = {}
    for stem_name, info in stems_iter.items():
        # Per-stem error/skip from the router → mark transcribed: False without
        # attempting to read MIDI.
        if isinstance(info, dict) and (info.get("skipped") or info.get("error")):
            reason = info.get("reason") or info.get("error") or "transcriber failed"
            out[stem_name] = {"notes": [], "transcribed": False, "reason": reason}
            if warnings is not None:
                warnings.append(f"stem {stem_name} transcriber issue: {reason}")
            continue

        # Resolve MIDI by stable convention rather than trusting the per-stem
        # path string (which may be relative or absolute depending on transcriber).
        midi_path = cache_dir / "midi" / f"{stem_name}.mid"
        if not midi_path.exists():
            out[stem_name] = {"notes": [], "transcribed": False, "reason": "midi missing"}
            continue

        # Locate the stem WAV for presence measurement + per-note gating.
        stem_wav = _find_stem_wav(stems_6s_dir, stem_name)
        if stem_wav is None or not stem_wav.exists():
            # No WAV to measure — skip presence check and proceed with plain
            # enrichment (graceful degradation: don't break if stems_6s is
            # missing, e.g. during unit tests with only MIDI fixtures).
            presence_result = None
            if warnings is not None:
                warnings.append(
                    f"stem {stem_name} presence gate skipped: no WAV in stems_6s/"
                )
        else:
            # Build the map of other melodic stems for Signal A.
            other_stem_wavs: dict[str, Path] = {}
            for other_name in MELODIC_STEMS:
                if other_name == stem_name:
                    continue
                other_wav = _find_stem_wav(stems_6s_dir, other_name)
                if other_wav is not None and other_wav.exists():
                    other_stem_wavs[other_name] = other_wav

            presence_result = measure_stem_presence(
                stem_wav,
                other_stem_wavs,
                stem_name,
                precomputed_rms_db=rms_db_map,
            )

            if not presence_result["transcribed"]:
                out[stem_name] = {
                    "transcribed": False,
                    "reason": presence_result["reason"],
                    "presence": presence_result,
                }
                if warnings is not None:
                    warnings.append(
                        f"stem {stem_name} suppressed by presence gate: "
                        f"{presence_result['reason']}"
                    )
                continue  # skip per-note enrichment for this gated stem

        # Stem passed the presence gate (or no WAV was available).
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        notes_raw = sorted(
            (
                {"t": float(n.start), "dur": float(n.end - n.start), "midi": int(n.pitch),
                 "name": pretty_midi.note_number_to_name(n.pitch),
                 "vel": round(float(n.velocity) / 127.0, 3)}
                for inst in pm.instruments for n in inst.notes
            ),
            key=lambda x: x["t"],
        )

        # Filter phantoms BEFORE enrichment.
        if stem_wav is not None and stem_wav.exists():
            notes_raw = filter_phantom_notes(notes_raw, stem_wav, stem_name)

        enriched = []
        for i, note in enumerate(notes_raw):
            prev_n = notes_raw[i - 1] if i > 0 else None
            next_n = notes_raw[i + 1] if i + 1 < len(notes_raw) else None
            enriched.append(enrich_note(note, prev=prev_n, next_=next_n, chords=chords_raw, key=key))

        # `transcribed: True` is set explicitly so a JSON reader can tell the
        # difference between "passed the gate" and "gate did not run" (the
        # latter omits the key entirely, with a warning logged above).
        stem_out: dict = {"notes": enriched, "transcribed": True}
        if presence_result is not None:
            stem_out["presence"] = presence_result
        out[stem_name] = stem_out

    if drums_result is None:
        out["drums"] = {"transcribed": False, "reason": "drums stage not run"}
    elif drums_result.get("transcribed") is False:
        # Stage ran but the RMS gate fired (track has no significant drum
        # content). Surface the gate's reason and metrics so the UI can show
        # "no drums detected" with diagnostic detail.
        out["drums"] = {
            "transcribed": False,
            "reason": drums_result.get("reason", "no drums detected"),
            "ratio_db": drums_result.get("ratio_db"),
        }
    else:
        out["drums"] = {
            "transcribed": True,
            "model": drums_result.get("model", "larsnet"),
            **{stem: info["events"] for stem, info in drums_result["stems"].items()},
        }
    return out


def _compute_reconciliation(results: dict) -> dict:
    """Stack-consistency metrics across stages.

    All keys are optional — missing inputs cleanly omit their entries
    rather than raising. The presence of a key is itself information
    (downstream can tell which checks ran).

    Metrics
    -------
    chord_downbeat_alignment_pct
        Fraction of chord starts (excluding "N" / empty no-chord events) that
        fall within 50 ms of any madmom downbeat. Pop/rock tracks should be
        > 0.7; jazz tracks may be ~0.3.
    beat_xcheck_agreement_pct
        Fraction of madmom beats that have a beat-this beat within 20 ms
        (greedy nearest-neighbor matching). Optional — depends on
        beats_xcheck having run.
    beat_xcheck_median_diff_ms
        Median absolute timing difference between madmom and beat-this beats.
    """
    out: dict = {}

    # 1. Chord starts vs downbeats
    if "beats" in results and "chords" in results:
        downbeats = results["beats"].get("downbeats") or []
        chord_starts = [
            float(c["start"]) for c in results["chords"]
            if str(c.get("label", "")).upper() not in {"N", ""}
        ]
        if downbeats and chord_starts:
            n_aligned = sum(
                1 for cs in chord_starts
                if any(abs(cs - db) <= 0.050 for db in downbeats)
            )
            out["chord_downbeat_alignment_pct"] = round(n_aligned / len(chord_starts), 3)
            out["chord_downbeat_n_chords"] = len(chord_starts)
            out["chord_downbeat_tolerance_ms"] = 50

    # 2. + 3. Beat cross-check (optional)
    if "beats" in results and "beats_xcheck" in results:
        m = results["beats"].get("beats") or []
        b = results["beats_xcheck"].get("beats") or []
        if m and b:
            # bisect needs sorted; madmom/beat-this both emit ascending but
            # don't assume.
            b_sorted = sorted(b)
            diffs = []
            for mt in m:
                idx = bisect.bisect_left(b_sorted, mt)
                candidates = []
                if idx > 0:
                    candidates.append(b_sorted[idx - 1])
                if idx < len(b_sorted):
                    candidates.append(b_sorted[idx])
                if candidates:
                    nearest = min(candidates, key=lambda bt: abs(bt - mt))
                    diffs.append(abs(nearest - mt))
            if diffs:
                agreed = sum(1 for d in diffs if d <= 0.020)
                out["beat_xcheck_agreement_pct"] = round(agreed / len(diffs), 3)
                out["beat_xcheck_median_diff_ms"] = round(float(np.median(diffs)) * 1000, 1)
                out["beat_xcheck_tolerance_ms"] = 20
                out["beat_xcheck_n_beats_matched"] = len(diffs)

    return out


def analyze(
    mp3_path: Path,
    *,
    force: bool = False,
    quiet: bool = False,
    slug: Optional[str] = None,
    stems_quality: str = stems.DEFAULT_STEMS_QUALITY,
    stages_only: Optional[set[str]] = None,
    from_stage: Optional[str] = None,
    params: Optional[dict] = None,
    skip_stages: Optional[set[str]] = None,
) -> AnalyzeResult:
    if not mp3_path.exists():
        raise FileNotFoundError(f"MP3 not found: {mp3_path}")
    if stems_quality not in stems.STEMS_QUALITY_PARAMS:
        raise ValueError(
            f"unknown stems_quality {stems_quality!r}; expected one of "
            f"{sorted(stems.STEMS_QUALITY_PARAMS)}"
        )

    # Resolve the selective-run set.
    stale_downstream: list[str] = []
    if force:
        run_set: Optional[set[str]] = None  # None = run everything
    elif from_stage is not None:
        if from_stage not in STAGE_DEPS:
            raise ValueError(
                f"unknown from_stage {from_stage!r}; expected one of {sorted(STAGE_DEPS)}"
            )
        run_set = {from_stage} | downstream_of(from_stage)
    elif stages_only is not None:
        unknown = stages_only - set(STAGE_DEPS)
        if unknown:
            raise ValueError(
                f"unknown stages_only {sorted(unknown)}; expected one of {sorted(STAGE_DEPS)}"
            )
        # Capture downstream stages whose caches were derived from prior runs of
        # the selected stages — they'll silently keep stale outputs unless the
        # caller cascades via --from-stage. Surface as a warning rather than an
        # error: --stages-only X is a documented affordance (e.g. transcription
        # tuning) and the caller may have already hand-rebuilt downstream caches.
        stale_downstream = sorted({
            s for stage in stages_only
            for s in downstream_of(stage)
            if s not in stages_only
        })
        run_set = set(stages_only)
    else:
        run_set = None  # cached() decides per-stage

    slug_str = slug if slug else cache_mod.slug_for(mp3_path)
    cache_dir = cache_mod.ensure_dir(slug_str)
    cached_mp3 = cache_dir / f"{slug_str}.mp3"

    # If the input IS the cache mirror, --force would delete it before any
    # stage can read it. Stage out to a tempdir, let clear() proceed, then
    # the mirror-copy below restores it. The webui's reanalyze flow always
    # pre-stages via TemporaryDirectory; this defends the same property at
    # the pipeline boundary so direct CLI callers are safe too.
    staging_tmp: tempfile.TemporaryDirectory | None = None
    if force and cached_mp3.exists() and cached_mp3.resolve() == mp3_path.resolve():
        staging_tmp = tempfile.TemporaryDirectory(prefix="analyze_force_stage_")
        staged = Path(staging_tmp.name) / mp3_path.name
        shutil.copy2(mp3_path, staged)
        _log(f"==> Staged input out of cache before --force ({staged})", quiet=quiet)
        mp3_path = staged

    try:
        if force:
            cache_mod.clear(cache_dir)

        # Mirror the source MP3 into the cache so the webui (which globs
        # cache/<slug>/*.mp3) can serve it without depending on the original path.
        if cached_mp3.resolve() != mp3_path.resolve() and not cached_mp3.exists():
            shutil.copy2(mp3_path, cached_mp3)
            _log(f"==> Copied source MP3 to {cached_mp3.name}", quiet=quiet)

        warnings: list[str] = ["sections deferred — no segmenter installed"]
        if stale_downstream:
            msg = (
                f"selective re-run leaves downstream stages stale: {stale_downstream}. "
                f"Their cached outputs were derived from prior runs of {sorted(stages_only or [])}. "
                f"Use --from-stage to cascade automatically."
            )
            warnings.append(msg)
            _log(f"!!  {msg}", quiet=quiet)
        results: dict = {}

        # Per-stage extra kwargs threaded into both cached() and run(). Empty for
        # stages that don't take any; the stems entry carries the user-selected
        # quality preset so cache validity is preset-aware.
        stage_kwargs: dict[str, dict] = {"stems": {"quality": stems_quality}}

        for name, module in _STAGE_EXECUTION_ORDER:
            if skip_stages and name in skip_stages:
                _log(f"==> Stage {name}: skipped (--no-{name.replace('_', '-')})", quiet=quiet)
                continue
            is_required = (name, module) in REQUIRED_STAGES
            extra = stage_kwargs.get(name, {})
            if params and name in params:
                # Per-stage params from --params-json take precedence over per-stage
                # kwargs (e.g. --stems-quality). Last-write-wins on key collision.
                extra = {**extra, **params[name]}

            if run_set is not None and name not in run_set:
                # Stage excluded from selective run — must be cached already.
                if module.cached(cache_dir, **extra):
                    _log(f"==> Stage {name}: cached (skipped by selective-run)", quiet=quiet)
                    results[name] = module.load(cache_dir)
                    continue
                raise PipelineError(
                    f"selective run requested but stage {name!r} has no valid cache; "
                    f"run without --stages-only / --from-stage first to populate it"
                )

            # Stages explicitly in run_set (--stages-only / --from-stage) are
            # FORCED to re-run regardless of cache — that's the whole point of
            # selective re-run. The cached() check below only applies when
            # run_set is None (default all-or-nothing mode).
            if run_set is not None and name in run_set:
                _log(f"==> Stage {name}: running (forced by selective-run)", quiet=quiet)
                try:
                    results[name] = module.run(mp3_path, cache_dir, **extra)
                except Exception as e:
                    if is_required:
                        raise PipelineError(f"required stage {name} failed: {type(e).__name__}: {e}") from e
                    warnings.append(f"stage {name} failed (soft): {type(e).__name__}: {e}")
                    _log(f"!!  Stage {name} soft-failed: {e}", quiet=quiet)
                continue

            if module.cached(cache_dir, **extra):
                _log(f"==> Stage {name}: cached", quiet=quiet)
                results[name] = module.load(cache_dir)
                continue
            _log(f"==> Stage {name}: running", quiet=quiet)
            try:
                results[name] = module.run(mp3_path, cache_dir, **extra)
            except Exception as e:
                if is_required:
                    raise PipelineError(f"required stage {name} failed: {type(e).__name__}: {e}") from e
                warnings.append(f"stage {name} failed (soft): {type(e).__name__}: {e}")
                _log(f"!!  Stage {name} soft-failed: {e}", quiet=quiet)

        # Derivation
        _log("==> Derivation: theory + loop + vocal range + note enrichment", quiet=quiet)
        key_obj = parse_key(results["key"]["key"])
        chords_raw = results["chords"]
        chords_enriched = _enrich_chords(chords_raw, key_obj)
        loop, loop_appearances = predominant_chord_loop(chords_raw)
        loop_roman = None
        if loop:
            loop_roman = [roman_for(parse_chord(lbl), key_obj) for lbl in loop]
        modal_interchange_count = sum(1 for c in chords_enriched if c["function"] == "modal_interchange")
        # Stem enrichment runs FIRST so vocal_range can respect the new per-stem
        # presence gate (the htdemucs vocals stem may be suppressed even when the
        # coarser BS-RoFormer is_instrumental() check passes — different separators,
        # different signals).
        stems_enriched = _enrich_stems(
            results["transcription"], chords_raw, key_obj, cache_dir,
            drums_result=results.get("drums"),
            warnings=warnings,
        )

        # vocal_range is suppressed if EITHER gate fires:
        #   (1) BS-RoFormer is_instrumental — coarse, track-level
        #   (2) htdemucs vocals stem failed the new presence gate — per-stem
        # The two are independent because they measure different separators'
        # outputs; both are conservative ("when in doubt, don't claim a range").
        if is_instrumental(cache_dir / "stems_bsroformer"):
            vocal_range = None
            warnings.append("vocal_range suppressed (track appears instrumental — BS-RoFormer vocals stem RMS << instrumental stem)")
        elif stems_enriched.get("vocals", {}).get("transcribed") is False:
            vocal_range = None
            gate_reason = stems_enriched["vocals"].get("reason", "presence gate fired")
            warnings.append(f"vocal_range suppressed (vocals stem failed presence gate: {gate_reason})")
        else:
            vocals_midi = cache_dir / "midi" / "vocals.mid"
            vocal_range = vocal_range_from_midi(vocals_midi)
            if vocal_range is None:
                warnings.append("vocal_range not computable (no vocals MIDI or empty)")

        derived = {
            "scale": scale_name(key_obj),
            "predominant_chord_loop": loop,
            "loop_roman": loop_roman,
            "loop_appearances": loop_appearances,
            "modal_interchange_count": modal_interchange_count,
            "vocal_range": vocal_range,
            "chords_enriched": chords_enriched,
            "stems_enriched": stems_enriched,
        }

        duration_sec = _probe_duration_sec(mp3_path)

        # Stack-consistency metrics (chord/downbeat alignment, beat xcheck).
        # Returns {} gracefully if inputs are missing — never fails the run.
        reconciliation = _compute_reconciliation(results)

        jams_path = cache_dir / f"{slug_str}.jams"
        summary_path = cache_dir / f"{slug_str}.summary.json"
        write_jams(jams_path, mp3_path, results, derived, warnings, duration_sec=duration_sec)
        # Source stems_quality from the on-disk stems sidecar (via the loaded
        # result) so a selective re-run that doesn't include stems can't lie
        # about which preset is actually on disk. Fall back to the CLI flag
        # only if the sidecar predates the quality field.
        recorded_quality = results["stems"].get("quality") or stems_quality
        write_summary(
            summary_path, mp3_path, results, derived, warnings,
            duration_sec=duration_sec, stems_quality=recorded_quality,
            cache_dir=cache_dir,
            reconciliation=reconciliation,
        )
        _log(f"==> Wrote {jams_path.name} + {summary_path.name}", quiet=quiet)

        return AnalyzeResult(jams_path=jams_path, summary_path=summary_path, warnings=warnings)
    finally:
        if staging_tmp is not None:
            staging_tmp.cleanup()
