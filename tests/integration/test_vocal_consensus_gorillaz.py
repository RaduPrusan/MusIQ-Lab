"""Real-audio regression tests for vocal-consensus on the Gorillaz cache.

Locks in current behavior of `_validate_anchor_notes` and
`process_contour` against the canonical Gorillaz reference cache
(215 s track) so a future vectorization (item #8a) can be verified by
drift detection rather than re-derivation from spec.

Phase M lessons (see docs/history.md): the WI-7 vocals specialist
passed all synthetic-input tests but failed on real audio. The
existing tests/unit/test_vocal_consensus_*.py suite uses synthetic
sines and doesn't catch real-world failure modes — these regression
tests fill that gap.

The cache must already exist (skipped otherwise — regenerating is a
6-10 min full pipeline run).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from analyze.cache import PROJECT_ROOT
from analyze.derived.vocal_consensus.contour import process_contour
from analyze.stages import stems_dynamics, vocal_f0
from analyze.stages.vocal_consensus_contour import (
    DEFAULT_PARAMS,
    FPS,
    _load_basic_pitch_vocals,
    _validate_anchor_notes,
)


# Cache dir uses the long slug from `slug_for(<mp3>)`. Older docs/tests
# referenced `cache/gorillaz_silent_running/` as a short alias — try both
# so the tests work in either layout.
_LONG_SLUG = "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg"
_SHORT_SLUG = "gorillaz_silent_running"


def _resolve_cache_dir() -> Path | None:
    for slug in (_LONG_SLUG, _SHORT_SLUG):
        candidate = PROJECT_ROOT / "cache" / slug
        if (candidate / "vocal_consensus.json").exists():
            return candidate
    return None


@pytest.fixture(scope="module")
def gorillaz_cache_dir() -> Path:
    cd = _resolve_cache_dir()
    if cd is None:
        pytest.skip(
            "Gorillaz cache lacks vocal_consensus artifacts; run analyze first"
        )
    # Hard deps for the regression tests.
    required = [
        "vocal_f0.npz",
        "midi/vocals.mid",
        "vocal_consensus.npz",
        "vocal_consensus.json",
    ]
    for rel in required:
        if not (cd / rel).exists():
            pytest.skip(f"Gorillaz cache missing {rel}; run analyze first")
    return cd


@pytest.fixture(scope="module")
def gorillaz_cached_summary(gorillaz_cache_dir: Path) -> dict:
    return json.loads((gorillaz_cache_dir / "vocal_consensus.json").read_text())


@pytest.fixture(scope="module")
def gorillaz_cached_npz(gorillaz_cache_dir: Path) -> dict:
    with np.load(gorillaz_cache_dir / "vocal_consensus.npz") as z:
        return {k: z[k] for k in z.files}


@pytest.fixture(scope="module")
def gorillaz_inputs(gorillaz_cache_dir: Path) -> dict:
    """Re-load the inputs that fed `vocal_consensus_contour.run` originally."""
    vf0 = vocal_f0.load(gorillaz_cache_dir)
    fcpe = np.asarray(vf0["fcpe_array"], dtype=np.float32)
    pesto = np.asarray(vf0["pesto_array"], dtype=np.float32)
    fcpe_conf = np.asarray(vf0["fcpe_conf_array"], dtype=np.float32)
    pesto_conf = np.asarray(vf0["pesto_conf_array"], dtype=np.float32)
    bp_notes = _load_basic_pitch_vocals(
        gorillaz_cache_dir,
        pitch_min=DEFAULT_PARAMS["vocal_midi_min"],
        pitch_max=DEFAULT_PARAMS["vocal_midi_max"],
    )
    dyn = stems_dynamics.load(gorillaz_cache_dir)
    rms = dyn.get("vocals")
    if rms is not None:
        rms = np.asarray(rms, dtype=np.float32)
    return {
        "fcpe": fcpe,
        "pesto": pesto,
        "fcpe_conf": fcpe_conf,
        "pesto_conf": pesto_conf,
        "bp_notes": bp_notes,
        "rms": rms,
    }


# ---------- Test A: anchor validation counts -----------------------------


def test_anchor_validation_kept_dropped_corrected_counts_match_cache(
    gorillaz_inputs: dict, gorillaz_cached_summary: dict
):
    """`_validate_anchor_notes` reproduces the cached kept/corrected/dropped."""
    cached_av = gorillaz_cached_summary["anchor_validation"]

    _validated, info = _validate_anchor_notes(
        gorillaz_inputs["bp_notes"],
        gorillaz_inputs["fcpe"],
        gorillaz_inputs["pesto"],
        gorillaz_inputs["fcpe_conf"],
        gorillaz_inputs["pesto_conf"],
        FPS,
        min_validation_frames=int(DEFAULT_PARAMS["anchor_validation_min_frames"]),
        confidence_threshold=float(DEFAULT_PARAMS["anchor_validation_conf_threshold"]),
    )

    assert info["kept"] == cached_av["kept"], (
        f"kept count drift: re-derived={info['kept']} vs cache={cached_av['kept']}"
    )
    assert info["corrected"] == cached_av["corrected"], (
        f"corrected count drift: re-derived={info['corrected']} vs cache={cached_av['corrected']}"
    )
    assert info["dropped"] == cached_av["dropped"], (
        f"dropped count drift: re-derived={info['dropped']} vs cache={cached_av['dropped']}"
    )


# ---------- Helper: re-run process_contour with the same params ----------


def _rerun_process_contour(inputs: dict):
    # Match what `vocal_consensus_contour.run` does: anchor-validate first,
    # then length-align fcpe/pesto/conf to RMS if RMS was supplied, then
    # call process_contour with the same Viterbi params.
    bp_notes, _ = _validate_anchor_notes(
        inputs["bp_notes"],
        inputs["fcpe"],
        inputs["pesto"],
        inputs["fcpe_conf"],
        inputs["pesto_conf"],
        FPS,
        min_validation_frames=int(DEFAULT_PARAMS["anchor_validation_min_frames"]),
        confidence_threshold=float(DEFAULT_PARAMS["anchor_validation_conf_threshold"]),
    )

    fcpe = inputs["fcpe"]
    pesto = inputs["pesto"]
    rms = inputs["rms"]
    if rms is not None:
        n = min(len(fcpe), len(pesto), len(rms))
        fcpe = fcpe[:n]
        pesto = pesto[:n]
        rms = rms[:n]
    else:
        n = min(len(fcpe), len(pesto))
        fcpe = fcpe[:n]
        pesto = pesto[:n]
    fcpe_conf = inputs["fcpe_conf"][: len(fcpe)]
    pesto_conf = inputs["pesto_conf"][: len(pesto)]

    viterbi_params = {
        "lambda_freq": float(DEFAULT_PARAMS["viterbi_lambda_freq"]),
        "cents_normalizer": float(DEFAULT_PARAMS["viterbi_cents_normalizer"]),
        "lambda_octave": float(DEFAULT_PARAMS["viterbi_lambda_octave"]),
        "octave_sigma": float(DEFAULT_PARAMS["viterbi_octave_sigma"]),
        "lambda_voicing_on": float(DEFAULT_PARAMS["viterbi_lambda_voicing_on"]),
        "lambda_voicing_off": float(DEFAULT_PARAMS["viterbi_lambda_voicing_off"]),
        "anchor_prox_bonus": float(DEFAULT_PARAMS["viterbi_anchor_prox_bonus"]),
        "anchor_prox_sigma": float(DEFAULT_PARAMS["viterbi_anchor_prox_sigma"]),
    }
    return process_contour(
        fcpe, pesto, bp_notes, FPS,
        rms=rms,
        rms_floor_db=DEFAULT_PARAMS["rms_floor_db"],
        cents_agreement_threshold=DEFAULT_PARAMS["cents_agreement_threshold"],
        fcpe_conf=fcpe_conf,
        pesto_conf=pesto_conf,
        viterbi_enabled=bool(DEFAULT_PARAMS["viterbi_enabled"]),
        viterbi_params=viterbi_params,
    )


@pytest.fixture(scope="module")
def gorillaz_rerun(gorillaz_inputs: dict):
    return _rerun_process_contour(gorillaz_inputs)


# ---------- Test B: consensus_summary counts -----------------------------


def test_process_contour_consensus_summary_matches_cache(
    gorillaz_rerun, gorillaz_cached_summary: dict
):
    """Re-derived per-bucket frame counts match the cached summary exactly.

    Tolerance: zero. process_contour is fully deterministic for a given
    set of inputs (no RNG; Viterbi uses argmax tie-breaking which is
    stable for float64 cost arrays). If you find non-determinism, see
    the test docstring of analyze/derived/vocal_consensus/viterbi.py
    for guidance.
    """
    result = gorillaz_rerun
    cached = gorillaz_cached_summary["consensus_summary"]

    votes = result.vote_count
    strength = result.agreement_strength

    rederived = {
        "frames_vote_3": int((votes == 3).sum()),
        "frames_vote_2": int((votes == 2).sum()),
        "frames_vote_1": int((votes == 1).sum()),
        "frames_vote_0": int((votes == 0).sum()),
        "frames_with_consensus_f0": int(np.isfinite(result.consensus_f0).sum()),
        "frames_strength_strong": int((strength >= 0.7).sum()),
        "frames_strength_medium": int(((strength >= 0.4) & (strength < 0.7)).sum()),
        "frames_strength_weak": int(((strength >= 0.1) & (strength < 0.4)).sum()),
        "octave_corrections_fcpe": int((result.octave_corrections[:, 0] != 0).sum()),
        "octave_corrections_pesto": int((result.octave_corrections[:, 1] != 0).sum()),
    }

    for key, expected in cached.items():
        actual = rederived[key]
        assert actual == expected, (
            f"consensus_summary[{key!r}] drift: re-derived={actual} vs cache={expected}"
        )


# ---------- Test C: full consensus_f0 array ------------------------------


def test_consensus_f0_array_matches_cache(
    gorillaz_rerun, gorillaz_cached_npz: dict
):
    """Per-frame `consensus_f0` matches cached array (NaN positions exact)."""
    rederived = np.asarray(gorillaz_rerun.consensus_f0)
    cached = np.asarray(gorillaz_cached_npz["consensus_f0"])

    assert rederived.shape == cached.shape, (
        f"shape drift: re-derived={rederived.shape} vs cache={cached.shape}"
    )

    # NaN positions must align exactly.
    nan_re = np.isnan(rederived)
    nan_cached = np.isnan(cached)
    n_diff = int((nan_re != nan_cached).sum())
    assert n_diff == 0, (
        f"NaN-mask drift: {n_diff} frames differ in voiced/unvoiced status"
    )

    # Finite positions must match within tight tolerance.
    finite_mask = ~nan_re
    np.testing.assert_allclose(
        rederived[finite_mask],
        cached[finite_mask],
        rtol=1e-4,
        atol=1e-3,
        err_msg="consensus_f0 finite-frame Hz drift exceeds tolerance",
    )


def test_agreement_strength_array_matches_cache(
    gorillaz_rerun, gorillaz_cached_npz: dict
):
    """Per-frame `agreement_strength` matches cached array."""
    if "agreement_strength" not in gorillaz_cached_npz:
        pytest.skip("cache predates agreement_strength array (pre-Phase 0c v3)")
    rederived = np.asarray(gorillaz_rerun.agreement_strength)
    cached = np.asarray(gorillaz_cached_npz["agreement_strength"])
    assert rederived.shape == cached.shape
    np.testing.assert_allclose(rederived, cached, rtol=1e-4, atol=1e-4)
