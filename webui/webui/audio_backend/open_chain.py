"""Open a WASAPI / MME stream with a documented fallback chain.

Phase 4 orchestrator. The user picks
``(hostapi, device_name, exclusive, samplerate)`` in the Settings UI;
this module tries the most-specific request first, then degrades:

    1. (api,    device_name, exclusive, samplerate)     # requested
    2. (api,    device_name, Shared,    samplerate)     # if exclusive=True
    3. ("mme",  device_name, False,     samplerate)     # last resort

Each attempt returns an ``OpenResult`` carrying:
  - which row was actually opened, and
  - ``fallback_reason`` (None when the first attempt succeeded; otherwise
    a short string like ``"exclusive_failed:device_in_use"`` that the WS
    layer forwards to the client as a ``FallbackMsg`` for toast display).

If every entry fails, ``EngineUnavailable`` is raised. The WS layer
converts that to ``ErrorMsg(code="engine_unavailable")``; the client
disposes the WasapiEngine and the engine-factory swaps back to WebAudio.

Why a separate module:
  ``AudioSession.open(...)`` is the device-level primitive — it opens
  exactly what the caller asks for and raises on failure. The fallback
  *policy* is host-API-specific and Phase-specific; keeping it out of
  ``stream.py`` keeps the audio thread's contract simple and the policy
  easily unit-testable in isolation.

PortAudio error-code mapping
----------------------------
``sd.PortAudioError`` stringifies as ``"msg [PaErrorCode N]"`` with
``args == (msg, code, ...)``. We extract the integer code via
``exc.args[1]`` (NOT ``args[0]`` — that's the message) and map two
codes worth distinguishing for fallback messaging:

  - ``-9985`` paDeviceUnavailable — Windows ``AUDCLNT_E_DEVICE_IN_USE``
    family. Device held in Exclusive by another app, or USB Audio Class
    rejected the block size. Toast: "device in use".
  - ``-9997`` paInvalidSampleRate — driver wouldn't quantise the
    requested rate to its hardware-native format (the 2026-05-12 probe
    saw this for off-rate Exclusive on FLOW 8). Toast: "off-rate".

Anything else collapses to the exception's class name; the toast still
makes the fallback visible without surfacing PortAudio internals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import sounddevice as sd

from . import devices as _devices
from .stream import AudioSession

log = logging.getLogger(__name__)


# PortAudio error codes worth distinguishing for fallback messaging. See
# module docstring for the rationale. Source: portaudio.h PaErrorCode.
_PA_DEVICE_UNAVAILABLE = -9985   # AUDCLNT_E_DEVICE_IN_USE family
_PA_INVALID_SAMPLE_RATE = -9997  # off-rate Exclusive request


class EngineUnavailable(Exception):
    """Raised when no entry in the fallback chain succeeded.

    Carries the last underlying error in its message so the WS layer can
    surface it for debugging. The client treats this as "swap back to
    WebAudio" rather than "retry".
    """


@dataclass
class OpenResult:
    """What ``open_with_fallback`` actually opened."""

    chosen_hostapi: str         # "wasapi" or "mme"
    chosen_exclusive: bool
    chosen_device_index: int
    chosen_samplerate: int
    # None when the first attempt (most-specific request) succeeded.
    # Otherwise a short reason string of the form
    #   "{stage}_failed:{err_label}"
    # — see module docstring for the labels.
    fallback_reason: Optional[str] = None


def open_with_fallback(
    audio: AudioSession,
    *,
    hostapi: str,            # "wasapi" or "mme"
    device_name: str,
    exclusive: bool,
    samplerate: int,
) -> OpenResult:
    """Walk the documented fallback chain. Raises ``EngineUnavailable`` if
    nothing in the chain opens.

    Order (skipping the Shared step when Exclusive wasn't requested):

      1. (hostapi, device_name, exclusive, samplerate)        # requested
      2. (hostapi, device_name, False,     samplerate)        # if exclusive
      3. ("mme",   device_name, False,     samplerate)        # last resort

    ``AudioSession.open()`` is idempotent — repeated calls with the same
    params are a no-op, and a different-param call closes-and-reopens. So
    each attempt either succeeds (returning ``OpenResult``) or raises
    ``sd.PortAudioError``; on failure we move to the next entry.

    MME has no Exclusive concept (Phase 4 don't). Entry 3 always uses
    ``exclusive=False``.
    """
    # Build the attempt list. Each entry is (api, name, excl, sr).
    attempts: list[tuple[str, str, bool, int]] = []
    attempts.append((hostapi, device_name, exclusive, samplerate))
    if exclusive:
        # Same device, Shared. Only meaningful when the user asked for
        # Exclusive; for a Shared request, attempt 1 *is* this entry.
        attempts.append((hostapi, device_name, False, samplerate))
    # Last-resort: same device-name on the MME host API. MME has no
    # Exclusive concept — never pass exclusive=True here.
    if hostapi != "mme":
        attempts.append(("mme", device_name, False, samplerate))

    requested = attempts[0]
    last_err: Optional[Exception] = None
    # Error from attempts[0] specifically. We feed this (not last_err) to
    # _format_fallback_reason so the toast surfaces the ORIGINAL blocker,
    # not whatever the immediately-preceding attempt happened to fail with.
    # Example: Exclusive fails with -9985 (device in use), Shared then fails
    # with -9997 (invalid sample rate), MME succeeds. The user-meaningful
    # reason is "device in use" — the -9997 is just a side effect of
    # retrying a contended device on an off-rate.
    root_err: Optional[Exception] = None

    for i, attempt in enumerate(attempts):
        api, name, excl, sr = attempt
        device_index = _devices.find_device_by_identity(api, name)
        if device_index is None:
            # Treat "device disappeared" as a fallback-worthy error rather
            # than a hard abort — the same device name often exists on the
            # MME host API even when the WASAPI row doesn't resolve (saved
            # device gone after driver upgrade; spec risks-table row).
            stub = EngineUnavailable(
                f"{api}/{name}: device not found"
            )
            last_err = stub
            if i == 0:
                root_err = stub
            log.warning(
                "audio_backend.open_chain: attempt %d device not found "
                "(api=%s name=%s)", i, api, name,
            )
            continue
        try:
            audio.open(
                device_index=device_index,
                samplerate=sr,
                exclusive=excl,
            )
        except sd.PortAudioError as exc:
            last_err = exc
            if i == 0:
                root_err = exc
            log.warning(
                "audio_backend.open_chain: attempt %d failed "
                "(api=%s excl=%s sr=%s): %s",
                i, api, excl, sr, exc,
            )
            continue
        except Exception as exc:  # noqa: BLE001 — defensive
            last_err = exc
            if i == 0:
                root_err = exc
            log.exception(
                "audio_backend.open_chain: attempt %d unexpected error",
                i,
            )
            continue

        # Success. If this wasn't the most-specific request, format the
        # reason for the FallbackMsg. Use root_err (the error from
        # attempts[0]) so the label describes the original blocker. When
        # i > 0, attempts[0] necessarily failed, so root_err is set; the
        # `or last_err` is belt-and-braces for an unreachable path.
        reason: Optional[str] = None
        if i > 0:
            reason = _format_fallback_reason(
                requested, attempt, root_err or last_err
            )
        return OpenResult(
            chosen_hostapi=api,
            chosen_exclusive=excl,
            chosen_device_index=device_index,
            chosen_samplerate=sr,
            fallback_reason=reason,
        )

    raise EngineUnavailable(
        f"all attempts failed for hostapi={hostapi!r} name={device_name!r} "
        f"exclusive={exclusive} samplerate={samplerate}: {last_err}"
    )


def _format_fallback_reason(
    requested: tuple[str, str, bool, int],
    actual: tuple[str, str, bool, int],
    err: Optional[Exception],
) -> str:
    """Produce a short reason string describing why we fell back.

    Shape: ``"{stage}_failed:{err_label}"`` so the client can split on
    ``":"`` and look up a human message:

      - stage ``"exclusive"`` — requested Exclusive, opened Shared
      - stage ``"wasapi"``    — requested WASAPI, opened MME
      - stage ``"fallback"``  — anything else (shouldn't happen with
        the current 3-step chain, included for defensiveness)

      - err_label ``"device_in_use"``     — paDeviceUnavailable (-9985)
      - err_label ``"invalid_sample_rate"`` — paInvalidSampleRate (-9997)
      - err_label ``"device_not_found"``  — find_device_by_identity → None
      - err_label = exception class name  — anything else
    """
    err_label = _err_label(err)
    # requested = (api, name, excl, sr); actual = same shape.
    #
    # When BOTH the host API and the exclusive flag changed (e.g. asked
    # for WASAPI Exclusive, landed on MME), the host-API change is the
    # user-visible one — the Exclusive distinction is moot once we're on
    # MME. So check the host-API jump first.
    if requested[0] == "wasapi" and actual[0] == "mme":
        return f"wasapi_failed:{err_label}"
    if requested[2] and not actual[2]:
        # Asked Exclusive, got Shared on the same host API.
        return f"exclusive_failed:{err_label}"
    return f"fallback:{err_label}"


def _err_label(err: Optional[Exception]) -> str:
    """Map a PortAudioError code (or other exception) to a short label."""
    if err is None:
        return "unknown"
    if isinstance(err, EngineUnavailable):
        # Synthesised "device not found" from find_device_by_identity.
        return "device_not_found"
    if isinstance(err, sd.PortAudioError):
        # PortAudioError.args == (message, code, [host_error_tuple]). The
        # code is args[1], NOT args[0] (a common docs-vs-reality trap;
        # sounddevice's __str__ confirms via `if len(args) > 1: ... args[1]`).
        if len(err.args) >= 2:
            code = err.args[1]
            if code == _PA_DEVICE_UNAVAILABLE:
                return "device_in_use"
            if code == _PA_INVALID_SAMPLE_RATE:
                return "invalid_sample_rate"
            return f"pa_error_{code}"
        return "pa_error_unknown"
    return type(err).__name__
