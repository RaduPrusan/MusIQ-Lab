"""Phase 4 — open_with_fallback chain tests.

Mocks ``find_device_by_identity`` to return fixed indices and patches
``AudioSession.open`` to selectively raise ``sd.PortAudioError`` with the
specific PortAudio codes the orchestrator distinguishes.

We never open a real PortAudio stream in CI. The PortAudioError shape
matters: ``args == (message, code, [host_error])``. The code is
``args[1]``, NOT ``args[0]``.
"""
from __future__ import annotations

import queue
from typing import Optional

import pytest
import sounddevice as sd

from webui.audio_backend import open_chain
from webui.audio_backend.open_chain import (
    EngineUnavailable,
    OpenResult,
    open_with_fallback,
)
from webui.audio_backend.stream import AudioSession


# PortAudio codes the orchestrator distinguishes for fallback messaging.
_PA_DEVICE_UNAVAILABLE = -9985
_PA_INVALID_SAMPLE_RATE = -9997


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_devices(monkeypatch):
    """Map (hostapi, name) → fixed device index so find_device_by_identity
    is deterministic and never touches PortAudio."""
    table = {
        ("wasapi", "Speakers"): 1,
        ("mme",    "Speakers"): 0,
    }

    def fake_find(hostapi: str, name: str) -> Optional[int]:
        return table.get((hostapi, name))

    monkeypatch.setattr(
        open_chain._devices, "find_device_by_identity", fake_find
    )
    return table


def _new_session() -> AudioSession:
    """Bare AudioSession that never opens a real PortAudio stream — the
    tests patch ``open`` on the instance directly so we don't need a
    spy stream."""
    return AudioSession(event_queue=queue.SimpleQueue())


class _OpenSpy:
    """Stand-in for AudioSession.open that records (kwargs) and raises
    according to a per-call program.

    `program` is a list of ``None`` (success) or exception instances to
    raise on each call, in order. After the program is exhausted, all
    subsequent calls succeed.
    """

    def __init__(self, program):
        self.program = list(program)
        self.calls = []  # list of dict(device_index, samplerate, exclusive)

    def __call__(self, *, device_index, samplerate, exclusive=False, blocksize=0):
        self.calls.append({
            "device_index": device_index,
            "samplerate": samplerate,
            "exclusive": bool(exclusive),
            "blocksize": blocksize,
        })
        if not self.program:
            return None
        action = self.program.pop(0)
        if action is None:
            return None
        raise action


def _install_open_spy(audio: AudioSession, spy: _OpenSpy) -> None:
    """Replace audio.open with the spy. Bound-method semantics aren't needed
    — open_chain calls audio.open(...) by attribute lookup."""
    audio.open = spy  # type: ignore[assignment]


def _pa_err(code: int, msg: str = "test") -> sd.PortAudioError:
    """Construct a PortAudioError whose `.args[1]` is the integer code,
    matching the real sounddevice shape (msg, code, [host_error_tuple])."""
    return sd.PortAudioError(msg, code)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_first_attempt_succeeds_no_fallback(fake_devices):
    audio = _new_session()
    spy = _OpenSpy([None])  # success on first try
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=True,
        samplerate=48000,
    )

    assert isinstance(result, OpenResult)
    assert result.chosen_hostapi == "wasapi"
    assert result.chosen_exclusive is True
    assert result.chosen_device_index == 1
    assert result.chosen_samplerate == 48000
    assert result.fallback_reason is None
    # Only the first attempt was made.
    assert len(spy.calls) == 1
    assert spy.calls[0]["exclusive"] is True


def test_shared_request_skips_intermediate_step(fake_devices):
    """When the user picked Shared, the chain is just (Shared, MME).
    Exclusive isn't in the chain — there's nothing to "fall back from".
    """
    audio = _new_session()
    spy = _OpenSpy([None])
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=False,
        samplerate=48000,
    )
    assert result.chosen_exclusive is False
    assert result.fallback_reason is None
    assert len(spy.calls) == 1


# ---------------------------------------------------------------------------
# Exclusive → Shared fallback
# ---------------------------------------------------------------------------


def test_exclusive_falls_back_to_shared_on_device_in_use(fake_devices):
    """Step 1 raises -9985 (device in use). Step 2 (Shared) succeeds.
    Reason must be ``exclusive_failed:device_in_use``."""
    audio = _new_session()
    spy = _OpenSpy([_pa_err(_PA_DEVICE_UNAVAILABLE), None])
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=True,
        samplerate=48000,
    )
    assert result.chosen_hostapi == "wasapi"
    assert result.chosen_exclusive is False
    assert result.fallback_reason == "exclusive_failed:device_in_use"
    # Two attempts: Exclusive (fail), Shared (success).
    assert len(spy.calls) == 2
    assert spy.calls[0]["exclusive"] is True
    assert spy.calls[1]["exclusive"] is False


def test_exclusive_falls_back_to_shared_on_invalid_sample_rate(fake_devices):
    """Step 1 raises -9997 (off-rate Exclusive). Step 2 succeeds.
    Reason must be ``exclusive_failed:invalid_sample_rate``."""
    audio = _new_session()
    spy = _OpenSpy([_pa_err(_PA_INVALID_SAMPLE_RATE), None])
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=True,
        samplerate=44100,
    )
    assert result.chosen_exclusive is False
    assert result.fallback_reason == "exclusive_failed:invalid_sample_rate"


# ---------------------------------------------------------------------------
# WASAPI → MME fallback
# ---------------------------------------------------------------------------


def test_wasapi_falls_back_to_mme_when_shared_also_fails(fake_devices):
    """All three attempts: Exclusive fails, Shared fails, MME succeeds.
    Final reason describes the WASAPI → MME jump (not the original
    Exclusive failure)."""
    audio = _new_session()
    spy = _OpenSpy([
        _pa_err(_PA_DEVICE_UNAVAILABLE),   # Exclusive: device in use
        _pa_err(_PA_DEVICE_UNAVAILABLE),   # Shared: also in use
        None,                              # MME: success
    ])
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=True,
        samplerate=48000,
    )
    assert result.chosen_hostapi == "mme"
    assert result.chosen_exclusive is False
    assert result.chosen_device_index == 0  # MME index in fake_devices
    assert result.fallback_reason == "wasapi_failed:device_in_use"
    assert len(spy.calls) == 3


def test_fallback_reason_reflects_root_failure_not_proximate(fake_devices):
    """3-step chain: Exclusive fails -9985 (device in use), Shared then
    fails -9997 (invalid sample rate), MME succeeds. The toast reason
    must surface the ROOT blocker (-9985 = device_in_use), not the
    proximate one (-9997 = invalid_sample_rate).

    The host-API jump (wasapi → mme) is still the user-visible *kind* of
    fallback, so the stage stays ``wasapi_failed``. The err_label, though,
    comes from attempts[0]'s exception — not last_err."""
    audio = _new_session()
    spy = _OpenSpy([
        _pa_err(_PA_DEVICE_UNAVAILABLE),    # Exclusive (root): device in use
        _pa_err(_PA_INVALID_SAMPLE_RATE),   # Shared (proximate): off-rate
        None,                               # MME: success
    ])
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=True,
        samplerate=48000,
    )
    assert result.chosen_hostapi == "mme"
    # ROOT cause wins. If the function used last_err this would be
    # "wasapi_failed:invalid_sample_rate" — misleading toast.
    assert result.fallback_reason == "wasapi_failed:device_in_use"
    assert len(spy.calls) == 3


def test_wasapi_shared_request_falls_back_to_mme(fake_devices):
    """User picked Shared (not Exclusive). Shared fails; MME takes over.
    Only two attempts in the chain (no intermediate Shared step)."""
    audio = _new_session()
    spy = _OpenSpy([_pa_err(_PA_DEVICE_UNAVAILABLE), None])
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=False,
        samplerate=48000,
    )
    assert result.chosen_hostapi == "mme"
    assert result.fallback_reason == "wasapi_failed:device_in_use"
    assert len(spy.calls) == 2


# ---------------------------------------------------------------------------
# Total failure
# ---------------------------------------------------------------------------


def test_engine_unavailable_when_all_attempts_fail(fake_devices):
    """Every attempt raises → EngineUnavailable. The last error is in the
    message so the caller (and the user-facing toast) can debug."""
    audio = _new_session()
    spy = _OpenSpy([
        _pa_err(_PA_DEVICE_UNAVAILABLE),
        _pa_err(_PA_DEVICE_UNAVAILABLE),
        _pa_err(_PA_DEVICE_UNAVAILABLE),
    ])
    _install_open_spy(audio, spy)

    with pytest.raises(EngineUnavailable) as excinfo:
        open_with_fallback(
            audio,
            hostapi="wasapi",
            device_name="Speakers",
            exclusive=True,
            samplerate=48000,
        )
    # Three attempts were made before giving up.
    assert len(spy.calls) == 3
    # The last underlying error is referenced in the message for debugging.
    assert "PaErrorCode" in str(excinfo.value) or "-9985" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Device not found
# ---------------------------------------------------------------------------


def test_device_not_found_at_first_attempt_skips_to_next(monkeypatch):
    """If find_device_by_identity returns None for (wasapi, name) but
    succeeds for (mme, name), the chain skips the missing entry and lands
    on MME. The Shared step is also skipped (find returns None for the same
    name on wasapi). Reason is ``wasapi_failed:device_not_found``."""
    table = {
        # No wasapi entry — only MME.
        ("mme", "Speakers"): 0,
    }
    monkeypatch.setattr(
        open_chain._devices,
        "find_device_by_identity",
        lambda api, name: table.get((api, name)),
    )

    audio = _new_session()
    spy = _OpenSpy([None])  # the only attempt that actually runs
    _install_open_spy(audio, spy)

    result = open_with_fallback(
        audio,
        hostapi="wasapi",
        device_name="Speakers",
        exclusive=True,
        samplerate=48000,
    )
    assert result.chosen_hostapi == "mme"
    assert result.chosen_device_index == 0
    # Both wasapi attempts skipped at the find step; only MME ran.
    assert len(spy.calls) == 1
    assert result.fallback_reason == "wasapi_failed:device_not_found"


def test_device_not_found_anywhere_raises_engine_unavailable(monkeypatch):
    """No device under any host API → EngineUnavailable."""
    monkeypatch.setattr(
        open_chain._devices,
        "find_device_by_identity",
        lambda api, name: None,
    )
    audio = _new_session()
    spy = _OpenSpy([])  # should never be called
    _install_open_spy(audio, spy)

    with pytest.raises(EngineUnavailable):
        open_with_fallback(
            audio,
            hostapi="wasapi",
            device_name="Nonexistent",
            exclusive=True,
            samplerate=48000,
        )
    assert len(spy.calls) == 0
