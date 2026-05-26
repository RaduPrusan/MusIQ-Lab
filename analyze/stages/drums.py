"""Stage 9: drum source separation + ADTOF drum transcription.

Splits the htdemucs (Drums) stem into 5 sub-stems (kick, snare, toms, hi-hat,
cymbals) using LarsNet for webui playback, then runs ADTOF (Carsault et al.
2022 — a CRNN trained on multi-dataset drum data) on the **full mix** for
onset detection. ADTOF was trained on full mixes, not stems, so it receives
the original mp3 rather than the htdemucs Drums stem.

LarsNet sub-stem WAVs are still emitted for webui playback visualisation. The
bandpass applied to each substem suppresses out-of-band soft-mask bleed so the
playback audio sounds clean.

A pre-stage RMS gate skips LarsNet and ADTOF entirely on tracks where the
htdemucs Drums stem is much quieter than the loudest melodic stem — without it,
the pipeline produces thousands of phantom onsets on instrumental tracks (e.g.
Bach orchestral cello quintet: 2948 fake hits before this gate).

Outputs:
    cache_dir/stems_drums/{kick,snare,toms,hihat,cymbals}.wav   (only when ungated)
    cache_dir/drums_summary.json — per-stem events with {t, vel, conf}, or
                                    {transcribed: false, reason: ...} if gated.

ADTOF GitHub: https://github.com/MZehren/ADTOF (installed via WI-4).
LarsNet ships separately (CC BY-NC 4.0 weights, code unlicensed); install via
`bash scripts/install-larsnet.sh`. If the install isn't present, this stage
raises and the pipeline soft-fails it — other analyses still run.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from analyze import stems_routing

CANONICAL = "drums_summary.json"
SUBSTEM_DIR = "stems_drums"
SUBSTEMS = ("kick", "snare", "toms", "hihat", "cymbals")
SCHEMA_VERSION = 4

# RMS gate: skip the stage when the htdemucs Drums stem is at least this many
# dB below the loudest melodic stem (Bass/Guitar/Piano/Other/Vocals). Calibrated
# against the 25-track corpus: clear no-drums cases (Bach orchestral cello,
# CVT 380 M synth tone) sit at -64 to -67 dB; the quietest legitimate drum
# track (Olivia Dean acoustic) is at -30.8 dB. -40 dB clears legit drums by
# ≥9 dB margin and catches false positives by ≥24 dB.
GATE_THRESHOLD_DB = -40.0
GATE_OTHER_STEMS = ("bass", "guitar", "piano", "other", "vocals")

MIN_ONSETS_THRESHOLD = 10
"""Second-stage gate: skip drums when total ADTOF onsets across all 5 substems
< this value. Real drum tracks have hundreds of onsets in a 3-5 minute song;
1–9 onsets is almost always ADTOF false-positives on percussive non-drum
content (acoustic guitar attacks, vocal plosives) that snuck through the
−40 dB RMS gate. Calibrated conservatively: any legitimate drum track sits
well above this floor (Olivia Dean's quietest acoustic-pop drums in the
Phase I corpus produced ~hundreds of hits in 3 minutes), so a threshold
of 10 has zero risk of suppressing real drums.

Examples this catches:
  Sting "Shape of My Heart"  — 1 onset (acoustic guitar attack false positive)
  similar acoustic/vocal-led tracks where htdemucs leakage exceeds the
  RMS gate but ADTOF correctly recognizes there's no drum content.
"""

# Per-stem bandpass (Hz). Snare/hihat overlap in 4-8 kHz is genuine and
# survives the filter. The bandpass is applied to the LarsNet substem WAVs
# for webui playback quality — it does not affect ADTOF onset detection,
# which runs on the full mix.
BANDS = {
    "kick":    (30,    300),
    "snare":   (150,  5000),
    "toms":    (60,    600),
    "hihat":   (3000, 16000),
    "cymbals": (2000, 16000),
}

# ADTOF MIDI-class → our piece mapping (per spec §3).
#
# IMPORTANT: the installed ADTOF model (Frame_RNN_adtofAll_0) was trained
# with a 5-class output — LABELS_5 = [35, 38, 47, 42, 49]. The extra aliases
# here (36, 40, 41, 43, 44, 45, 46, 48, 50, 51–59) are included per spec for
# forward-compatibility with a potential future model that uses expanded MIDI
# output. In practice only the 5 canonical classes will appear in ADTOF output.
ADTOF_CLASS_MAP: dict[int, str] = {
    35: "kick",   36: "kick",
    38: "snare",  40: "snare",
    41: "toms",   43: "toms", 45: "toms", 47: "toms", 48: "toms", 50: "toms",
    42: "hihat",  44: "hihat", 46: "hihat",
    49: "cymbals", 51: "cymbals", 52: "cymbals", 53: "cymbals",
    55: "cymbals", 57: "cymbals", 59: "cymbals",
}

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "larsnet"

# ADTOF model name: the pretrained checkpoint that ships with the package.
_ADTOF_MODEL_NAME = "Frame_RNN"
_ADTOF_SCENARIO = "adtofAll"
_ADTOF_FOLD = 0


def cached(cache_dir: Path) -> bool:
    summary_path = cache_dir / CANONICAL
    if not summary_path.exists():
        return False
    try:
        summary = json.loads(summary_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    # Older schema versions need to be re-run: v1/v2 used librosa onset
    # detection on substems; v3 uses ADTOF on the full mix. cached()
    # returning False makes the pipeline transparently re-run on next call.
    if summary.get("version", 0) < SCHEMA_VERSION:
        return False
    if summary.get("transcribed") is False:
        # Gated tracks legitimately have no substem WAVs — the stage skipped
        # LarsNet entirely. The summary itself is the cache.
        return True
    return all((cache_dir / SUBSTEM_DIR / f"{s}.wav").exists() for s in SUBSTEMS)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def _import_larsnet():
    """Import the vendored LarsNet model. Raises with an actionable hint if
    the vendor dir is empty (i.e. install-larsnet.sh hasn't been run)."""
    if not (VENDOR / "config.yaml").exists():
        raise RuntimeError(
            f"LarsNet not installed at {VENDOR}. "
            "Run `bash scripts/install-larsnet.sh` to fetch the model."
        )
    sys.path.insert(0, str(VENDOR))
    try:
        from larsnet import LarsNet  # noqa: WPS433
    finally:
        sys.path.pop(0)
    return LarsNet


class _chdir:
    """Temporarily change cwd. LarsNet's config.yaml uses relative paths to
    the checkpoints (e.g. `pretrained_larsnet_models/kick/...`), so the model
    must be instantiated with cwd = vendor dir. Restore on exit even if the
    instantiation raises."""

    def __init__(self, target: Path):
        self.target = target

    def __enter__(self):
        import os
        self._prev = os.getcwd()
        os.chdir(self.target)

    def __exit__(self, *exc):
        import os
        os.chdir(self._prev)


def _stem_rms_db(wav_path: Path) -> float:
    import numpy as np
    import soundfile as sf
    y, _ = sf.read(str(wav_path), dtype="float32")
    if y.ndim == 2:
        y = y.mean(axis=1)
    rms = float(np.sqrt(np.mean(y ** 2)))
    return 20 * float(np.log10(rms + 1e-12))


def _check_gate(cache_dir: Path, drums_path: Path) -> tuple[float, float, float]:
    """Compute the gate metrics (drums_db, max_other_db, ratio_db) for the
    track. Returns the ratio in dB; caller decides whether to gate."""
    drums_db = _stem_rms_db(drums_path)
    other_dbs: list[float] = []
    for stem in GATE_OTHER_STEMS:
        try:
            path = stems_routing.path_for(cache_dir, stem)
        except stems_routing.RoutingError:
            # stem absent from routing (or routing.json missing entirely);
            # skip it — denominator is the max over the stems we did find.
            continue
        other_dbs.append(_stem_rms_db(path))
    if not other_dbs:
        # transition path: legacy caches without stems_routing.json — fall
        # back to the original glob-over-stems_6s behaviour so old caches
        # still gate correctly.
        for path in (cache_dir / "stems_6s").glob("*.wav"):
            name = path.name.lower()
            if "drum" in name:
                continue
            if any(stem in name for stem in GATE_OTHER_STEMS):
                other_dbs.append(_stem_rms_db(path))
    max_other_db = max(other_dbs) if other_dbs else drums_db
    return drums_db, max_other_db, drums_db - max_other_db


def _emit_larsnet_substems(cache_dir: Path, drums_path: Path) -> None:
    """Run LarsNet on the drums stem and write the bandpassed substem WAVs.

    The substem WAVs are kept for webui playback only — onset detection now
    happens via ADTOF on the full mix. We still bandpass each substem so the
    webui playback sounds clean (no out-of-band soft-mask bleed)."""
    import numpy as np
    import scipy.signal as sps
    import soundfile as sf
    import torch

    LarsNet = _import_larsnet()

    out_dir = cache_dir / SUBSTEM_DIR
    out_dir.mkdir(exist_ok=True)

    audio, sr = sf.read(str(drums_path), dtype="float32")
    # LarsNet wants stereo as (channels, time).
    if audio.ndim == 1:
        audio_t = torch.from_numpy(np.stack([audio, audio]))
    else:
        audio_t = torch.from_numpy(audio.T)

    with _chdir(VENDOR):
        model = LarsNet(config="config.yaml", device="cuda")
    if model.sr != sr:
        # htdemucs writes 44.1k natively; this is a safety net only.
        import librosa
        resampled = librosa.resample(audio_t.numpy(), orig_sr=sr, target_sr=model.sr, axis=-1)
        audio_t = torch.from_numpy(resampled)
        sr = model.sr

    substems = model.separate(audio_t)
    # Move every substem off CUDA before dropping the model reference.
    substems = {name: t.cpu() for name, t in substems.items()}
    del model
    import gc
    gc.collect()
    gc.collect()
    torch.cuda.empty_cache()

    for stem_name in SUBSTEMS:
        y = substems[stem_name].cpu().numpy()  # (2, T) stereo
        y_mono = y.mean(axis=0) if y.ndim == 2 else y

        lo, hi = BANDS[stem_name]
        sos = sps.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
        y_filtered = sps.sosfiltfilt(sos, y_mono).astype(np.float32)

        # Mono is intentional — we only need the WAV for webui playback;
        # drum substems don't carry meaningful stereo information after this
        # much processing, and mono halves the disk cost.
        sf.write(str(out_dir / f"{stem_name}.wav"), y_filtered, sr)


def _run_adtof(mp3: Path) -> list[dict]:
    """Run ADTOF on the full mix; return a list of {time, midi_class, velocity, conf}.

    API discovery (verified against the installed package at b3968fb):
    - Model: adtof.model.model.Model — TF/Keras CRNN (trained on full mixes).
    - Requires TF_USE_LEGACY_KERAS=1 because the checkpoint uses Adam from
      tf.keras.optimizers.legacy; with Keras 3 / TF 2.21 this needs tf_keras.
    - Model.modelFactory(modelName, scenario, fold) → (model_obj, hparams).
      The pre-shipped checkpoint is "Frame_RNN_adtofAll_0".
    - Track(audioPath, sampleRate, **hparams) preprocesses the audio via
      madmom (log-filtered spectrogram at 100 fps). Does NOT require annotation.
    - Model.predict(track, **hparams) → np.ndarray shape (T, 5), float32 in [0,1].
      T = duration_seconds * sampleRate (100 fps). 5 columns = LABELS_5.
    - PeakPicking.predict([Y], ...) → list[dict[int, list[float]]] where
      keys are MIDI pitch ints from LABELS_5 = [35, 38, 47, 42, 49] and
      values are lists of onset times in seconds. No velocity/confidence.
    - ADTOF's 5 output classes: 35=BD, 38=SD, 47=TT, 42=HH, 49=CY+RD.
      Extra aliases in ADTOF_CLASS_MAP (36, 40, 41, …) are spec-required for
      forward-compat but will never appear in current model output.
    """
    import os
    # tf.keras.optimizers.legacy is not available in Keras 3 (TF ≥ 2.16).
    # Setting TF_USE_LEGACY_KERAS=1 redirects tf.keras to tf_keras (Keras 2).
    # Must be set before any tensorflow/adtof import.
    os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

    from adtof.model.model import Model
    from adtof.model.peakPicking import PeakPicking
    from adtof.model.track import Track

    # Build model — loads pretrained Frame_RNN_adtofAll_0 checkpoint.
    model_obj, hparams = Model.modelFactory(
        modelName=_ADTOF_MODEL_NAME,
        scenario=_ADTOF_SCENARIO,
        fold=_ADTOF_FOLD,
    )

    # Build Track (inference mode: no annotationPath, no beatPath).
    # Pass only the subset of hparams that Track.__init__ consumes via **kwargs
    # (sampleRate is a named param; labels/sampleWeight/emptyWeight are not
    # consumed by Track and would be silently ignored, but skip them anyway
    # to keep the call clean).
    _track_skip = {"sampleRate", "labels", "sampleWeight", "emptyWeight",
                   "peakThreshold", "multiplePPThreshold", "validation_epoch",
                   "training_epoch", "reduce_patience", "stopping_patience",
                   "batchSize", "samplePerTrack", "regulateSamplingProbability"}
    track_kwargs = {k: v for k, v in hparams.items() if k not in _track_skip}
    track = Track(
        audioPath=str(mp3),
        sampleRate=hparams["sampleRate"],
        **track_kwargs,
    )

    # Raw frame-level predictions → shape (T, 5), values in [0, 1].
    Y = model_obj.predict(track, **hparams)

    # Peak picking: converts frame activations to sparse onset times.
    pp = PeakPicking()
    pp.setParameters(hparams["peakThreshold"], sampleRate=hparams["sampleRate"])
    results_list = pp.predict(
        [Y],
        labelOffset=hparams["labelOffset"],
        sampleRate=hparams["sampleRate"],
    )
    # results_list[0] is dict[int, list[float]] — MIDI class → onset times.
    results: dict[int, list[float]] = results_list[0]

    # Normalise to the common event format. ADTOF does not expose per-onset
    # velocity or confidence scores — we emit 0.0 as sentinels so consumers
    # can detect "not provided" rather than misinterpret a missing key.
    events: list[dict] = []
    for midi_class, times in results.items():
        for t in times:
            events.append({
                "time": float(t),
                "midi_class": int(midi_class),
                "velocity": 0.0,   # ADTOF does not provide velocity
                "confidence": 0.0,  # ADTOF does not provide confidence
            })
    events.sort(key=lambda e: e["time"])
    return events


def run(mp3: Path, cache_dir: Path) -> dict:
    try:
        drums_path = stems_routing.path_for(cache_dir, "drums")
    except stems_routing.RoutingError:
        # transition path: legacy caches or fast preset without routing.json
        drums_path = next(
            Path(p) for p in glob.glob(str(cache_dir / "stems_6s" / "*.wav"))
            if "drum" in Path(p).name.lower()
        )

    drums_db, max_other_db, ratio_db = _check_gate(cache_dir, drums_path)
    if ratio_db < GATE_THRESHOLD_DB:
        # Track has no meaningful drum content — skip LarsNet and ADTOF.
        # The summary captures the gate measurement for provenance.
        summary = {
            "version": SCHEMA_VERSION,
            "model": "adtof+larsnet",
            "transcribed": False,
            "reason": (
                f"drum content below gate ({ratio_db:.1f} dB below loudest "
                f"melodic stem; threshold {GATE_THRESHOLD_DB:.0f} dB)"
            ),
            "drums_stem_db": round(drums_db, 1),
            "max_other_stem_db": round(max_other_db, 1),
            "ratio_db": round(ratio_db, 1),
            "threshold_db": GATE_THRESHOLD_DB,
        }
        (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
        return summary

    # 3. Run LarsNet on the drums stem (preserved for webui playback).
    _emit_larsnet_substems(cache_dir, drums_path)

    # 4. Run ADTOF on the FULL MIX. ADTOF was trained on full mixes; using
    #    the original mp3 outperforms running it on the htdemucs drums stem.
    adtof_events = _run_adtof(mp3)

    # 5. Bucket ADTOF events into our 5 substems via ADTOF_CLASS_MAP.
    summary_stems: dict[str, dict] = {
        s: {"events": [], "wav": f"{SUBSTEM_DIR}/{s}.wav", "n_onsets": 0}
        for s in SUBSTEMS
    }
    unmapped = 0
    for e in adtof_events:
        piece = ADTOF_CLASS_MAP.get(e["midi_class"])
        if piece is None:
            unmapped += 1
            continue
        summary_stems[piece]["events"].append({
            "t": round(float(e["time"]), 3),
            "vel": round(float(e["velocity"]), 3),
            "conf": round(float(e["confidence"]), 3),
        })
    for s in SUBSTEMS:
        summary_stems[s]["n_onsets"] = len(summary_stems[s]["events"])

    # Second-stage gate: catch ADTOF false positives that slipped past the
    # first-stage RMS gate (e.g. acoustic-guitar attacks where htdemucs Drums
    # stem leakage keeps ratio_db above -40, but ADTOF correctly emits only a
    # handful of onsets). Note: LarsNet substem WAVs were already written to
    # disk above; we leave them in place — they're small, harmless when
    # transcribed=False, and removing them mid-run complicates the error path.
    total_onsets = sum(info["n_onsets"] for info in summary_stems.values())

    if total_onsets < MIN_ONSETS_THRESHOLD:
        summary = {
            "version": SCHEMA_VERSION,
            "model": "adtof+larsnet",
            "transcribed": False,
            "reason": (
                f"only {total_onsets} ADTOF onset(s) detected "
                f"(threshold {MIN_ONSETS_THRESHOLD}); likely false positives on "
                f"percussive non-drum content"
            ),
            # Preserve diagnostic fields from the first-stage gate so a downstream
            # consumer can see the full chain: RMS gate said "OK" (didn't fire),
            # but ADTOF said "very few hits" so the second gate fired.
            "drums_stem_db": round(drums_db, 1),
            "max_other_stem_db": round(max_other_db, 1),
            "ratio_db": round(ratio_db, 1),
            "threshold_db": GATE_THRESHOLD_DB,
            # New diagnostic — tells the consumer "ADTOF actually ran, it just
            # found very little". Distinct from first-stage gate where ADTOF
            # never ran at all.
            "adtof_total_onsets": total_onsets,
            "min_onsets_threshold": MIN_ONSETS_THRESHOLD,
        }
        (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
        return summary

    summary = {
        "version": SCHEMA_VERSION,
        "model": "adtof+larsnet",
        "transcribed": True,
        "drums_stem_db": round(drums_db, 1),
        "max_other_stem_db": round(max_other_db, 1),
        "ratio_db": round(ratio_db, 1),
        "stems": summary_stems,
        "adtof_unmapped_classes": unmapped,
    }
    (cache_dir / CANONICAL).write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    if r.get("transcribed") is False:
        print(f"GATED: {r['reason']}")
    else:
        for stem, info in r["stems"].items():
            print(f"{stem:<8} {info['n_onsets']:>5} hits")
