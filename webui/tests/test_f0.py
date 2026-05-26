import numpy as np
import pytest

from webui import f0


def test_decode_f0_roundtrip(tmp_path):
    npz_path = tmp_path / "vocal_f0.npz"
    fcpe = np.array([0.0, 220.0, 0.0, 440.5], dtype=np.float32)
    pesto = np.array([110.1, 220.1, 330.1, 440.1], dtype=np.float32)
    np.savez(npz_path, fcpe=fcpe, pesto=pesto)

    decoded = f0.decode_f0(npz_path)
    assert decoded["n_frames"] == 4
    assert decoded["hop_sec"] == 0.01
    assert decoded["fcpe"] == [0.0, 220.0, 0.0, 440.5]
    assert decoded["pesto"] == pytest.approx([110.1, 220.1, 330.1, 440.1], rel=1e-5)


def test_decode_f0_missing_keys_raises(tmp_path):
    npz_path = tmp_path / "vocal_f0.npz"
    np.savez(npz_path, only=np.array([1.0]))
    with pytest.raises(KeyError):
        f0.decode_f0(npz_path)


def test_decode_f0_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        f0.decode_f0(tmp_path / "absent.npz")


# ---------- Consensus extension ----------------------------------------

def _write_vocal_f0(path, fcpe, pesto):
    np.savez(path, fcpe=fcpe.astype(np.float32), pesto=pesto.astype(np.float32))


def _write_consensus_npz(path, *, n: int, with_strength: bool = True):
    """Write a small synthetic consensus arrays bundle.

    `with_strength=False` simulates a pre-Phase-0c-Step-2 cache (npz lacks
    the agreement_strength key); decode_f0 must synthesize from vote_count.
    """
    consensus_f0 = np.array(
        [np.nan, 220.0, np.nan, 440.0, 440.0],
        dtype=np.float32,
    )[:n]
    vote_count = np.array([0, 2, 0, 3, 3], dtype=np.int8)[:n]
    octave_corrections = np.zeros((n, 2), dtype=np.int8)
    octave_corrections[3, 0] = -1   # FCPE folded down at frame 3
    arrays = dict(
        consensus_f0=consensus_f0,
        vote_count=vote_count,
        octave_corrections=octave_corrections,
        # Stage actually writes more arrays but only these are consumed here
        fcpe_corrected=np.zeros(n, dtype=np.float32),
        pesto_corrected=np.zeros(n, dtype=np.float32),
    )
    if with_strength:
        # Vary by frame so tests can distinguish loaded vs synthesized.
        ag = np.array([0.0, 0.42, 0.0, 1.0, 0.85], dtype=np.float32)[:n]
        arrays["agreement_strength"] = ag
    np.savez(path, **arrays)


def test_decode_f0_with_consensus_includes_consensus_block(tmp_path):
    n = 5
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.linspace(0, 500, n, dtype=np.float32),
        np.linspace(0, 500, n, dtype=np.float32),
    )
    _write_consensus_npz(tmp_path / "vocal_consensus.npz", n=n)

    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        tmp_path / "vocal_consensus.npz",
    )
    assert decoded["consensus"] is not None
    c = decoded["consensus"]
    assert c["n_frames"] == n
    assert len(c["consensus_f0"]) == n
    assert len(c["agreement_strength"]) == n
    assert len(c["vote_count"]) == n
    assert len(c["octave_corrections_fcpe"]) == n
    assert len(c["octave_corrections_pesto"]) == n


def test_decode_f0_without_consensus_path_returns_null_consensus(tmp_path):
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.array([220.0, 440.0], dtype=np.float32),
        np.array([220.0, 440.0], dtype=np.float32),
    )
    decoded = f0.decode_f0(tmp_path / "vocal_f0.npz")
    assert decoded["consensus"] is None


def test_decode_f0_with_missing_consensus_file_returns_null(tmp_path):
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.array([220.0, 440.0], dtype=np.float32),
        np.array([220.0, 440.0], dtype=np.float32),
    )
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        tmp_path / "vocal_consensus.npz",  # path given but file missing
    )
    assert decoded["consensus"] is None


def test_decode_f0_serializes_nan_as_none(tmp_path):
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.array([0.0, 220.0, 0.0, 440.0, 440.0], dtype=np.float32),
        np.array([0.0, 220.0, 0.0, 440.0, 440.0], dtype=np.float32),
    )
    _write_consensus_npz(tmp_path / "vocal_consensus.npz", n=5)
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        tmp_path / "vocal_consensus.npz",
    )
    cf0 = decoded["consensus"]["consensus_f0"]
    # First and third frames are NaN per _write_consensus_npz
    assert cf0[0] is None
    assert cf0[2] is None
    assert cf0[1] == pytest.approx(220.0)
    assert cf0[3] == pytest.approx(440.0)


def test_decode_f0_agreement_strength_loaded_from_npz_when_present(tmp_path):
    n = 5
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.zeros(n, dtype=np.float32),
        np.zeros(n, dtype=np.float32),
    )
    _write_consensus_npz(tmp_path / "vocal_consensus.npz", n=n, with_strength=True)
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        tmp_path / "vocal_consensus.npz",
    )
    ag = decoded["consensus"]["agreement_strength"]
    # Values from _write_consensus_npz fixture's `with_strength` branch
    assert ag[0] == pytest.approx(0.0)
    assert ag[1] == pytest.approx(0.42)
    assert ag[3] == pytest.approx(1.0)
    assert ag[4] == pytest.approx(0.85)


def test_decode_f0_agreement_strength_synthesized_for_old_caches(tmp_path):
    """Pre-v3 cache (no agreement_strength key) must still load — the
    decoder synthesizes 3 → 1.0 / 2 → 0.5 / else → 0.0 from vote_count."""
    n = 5
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.zeros(n, dtype=np.float32),
        np.zeros(n, dtype=np.float32),
    )
    _write_consensus_npz(tmp_path / "vocal_consensus.npz", n=n, with_strength=False)
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        tmp_path / "vocal_consensus.npz",
    )
    ag = decoded["consensus"]["agreement_strength"]
    # vote_count fixture is [0, 2, 0, 3, 3] → strength [0, 0.5, 0, 1, 1]
    assert ag == pytest.approx([0.0, 0.5, 0.0, 1.0, 1.0])


# ---------- vocals_rms (Phase 0c Step 4 follow-up) ---------------------

def test_decode_f0_without_dynamics_path_returns_null_vocals_rms(tmp_path):
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.array([220.0, 440.0], dtype=np.float32),
        np.array([220.0, 440.0], dtype=np.float32),
    )
    decoded = f0.decode_f0(tmp_path / "vocal_f0.npz")
    assert decoded["vocals_rms"] is None


def test_decode_f0_with_missing_dynamics_file_returns_null(tmp_path):
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.array([220.0, 440.0], dtype=np.float32),
        np.array([220.0, 440.0], dtype=np.float32),
    )
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        None,
        tmp_path / "absent_vocals.npz",  # path given but file missing
    )
    assert decoded["vocals_rms"] is None


def test_decode_f0_with_dynamics_includes_vocals_rms(tmp_path):
    n = 4
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.linspace(0, 500, n, dtype=np.float32),
        np.linspace(0, 500, n, dtype=np.float32),
    )
    rms = np.array([0.0, 0.05, 0.1, 0.02], dtype=np.float32)
    np.savez(tmp_path / "vocals.npz", rms=rms)
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        None,
        tmp_path / "vocals.npz",
    )
    assert decoded["vocals_rms"] == pytest.approx([0.0, 0.05, 0.1, 0.02])


def test_decode_f0_vocals_rms_truncated_to_f0_length(tmp_path):
    """When the dynamics RMS array is longer than the F0 frame count
    (different framers / edge effects between stages), it must be
    truncated to F0 length so consumers can index by F0 frame index."""
    n_f0 = 3
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.zeros(n_f0, dtype=np.float32),
        np.zeros(n_f0, dtype=np.float32),
    )
    rms = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)  # length 5
    np.savez(tmp_path / "vocals.npz", rms=rms)
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        None,
        tmp_path / "vocals.npz",
    )
    assert len(decoded["vocals_rms"]) == n_f0
    assert decoded["vocals_rms"] == pytest.approx([0.1, 0.2, 0.3])


def test_decode_f0_correction_flags_present(tmp_path):
    _write_vocal_f0(
        tmp_path / "vocal_f0.npz",
        np.zeros(5, dtype=np.float32),
        np.zeros(5, dtype=np.float32),
    )
    _write_consensus_npz(tmp_path / "vocal_consensus.npz", n=5)
    decoded = f0.decode_f0(
        tmp_path / "vocal_f0.npz",
        tmp_path / "vocal_consensus.npz",
    )
    c = decoded["consensus"]
    # Frame 3 had FCPE folded down by one octave
    assert c["octave_corrections_fcpe"][3] == -1
    assert c["octave_corrections_pesto"][3] == 0
    # All other frames are zero
    assert c["octave_corrections_fcpe"][0] == 0
    assert c["octave_corrections_fcpe"][4] == 0
