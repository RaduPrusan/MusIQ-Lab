"""Output-device enumeration via sounddevice / PortAudio.

Filter rules (locked by the v1 design):
  - Skip devices with max_output_channels < 1.
  - Skip Windows DirectSound and Windows WDM-KS host APIs (out of scope).
  - For each MME output device emit one row (Shared semantics).
  - For each WASAPI output device emit TWO rows: Shared + Exclusive.

PortAudio integer device indices are SESSION-SCOPED — they can renumber on
every Pa_Initialize. Persist `(hostapi_name, device_name)` to localStorage
and re-resolve via find_device_by_identity() on each session. See memory
note `windows_audio_device_identity`.
"""
from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd


# Host-API name → short tag we expose to the UI / wire protocol. Only the
# two we surface in v1 appear here; anything else is filtered out.
_HOSTAPI_TAG = {
    "MME": "mme",
    "Windows WASAPI": "wasapi",
}


@dataclass
class DeviceEntry:
    """One row in the Settings → Audio device picker.

    `id` is session-scoped: it encodes the integer device index so the JS
    side can correlate within a single page session. After a reload the
    integer is re-resolved against (hostapi, device_name) via
    find_device_by_identity().
    """

    id: str
    label: str
    hostapi: str          # "mme" | "wasapi"
    device_name: str
    device_index: int
    exclusive: bool
    default_samplerate: int


def list_output_devices() -> list[DeviceEntry]:
    """Enumerate playable output rows for the device picker."""
    hostapis = sd.query_hostapis()
    rows: list[DeviceEntry] = []
    for idx, dev in enumerate(sd.query_devices()):
        if int(dev.get("max_output_channels", 0)) < 1:
            continue
        host_idx = int(dev.get("hostapi", -1))
        if host_idx < 0 or host_idx >= len(hostapis):
            continue
        host_name = hostapis[host_idx].get("name", "")
        tag = _HOSTAPI_TAG.get(host_name)
        if tag is None:
            # DirectSound / WDM-KS / anything else — out of scope for v1.
            continue
        name = dev.get("name", "") or f"device {idx}"
        sr = int(round(float(dev.get("default_samplerate", 0.0))))
        if tag == "wasapi":
            rows.append(_make_entry(
                kind="wasapi", name=name, idx=idx, exclusive=False,
                samplerate=sr, host_label="WASAPI Shared",
            ))
            rows.append(_make_entry(
                kind="wasapi-ex", name=name, idx=idx, exclusive=True,
                samplerate=sr, host_label="WASAPI Exclusive",
            ))
        else:  # mme
            rows.append(_make_entry(
                kind="mme", name=name, idx=idx, exclusive=False,
                samplerate=sr, host_label="MME",
            ))
    return rows


def _make_entry(*, kind: str, name: str, idx: int, exclusive: bool,
                samplerate: int, host_label: str) -> DeviceEntry:
    return DeviceEntry(
        id=f"{kind}:{name}:{idx}",
        label=f"{name} — {host_label}",
        hostapi=("wasapi" if kind in ("wasapi", "wasapi-ex") else "mme"),
        device_name=name,
        device_index=idx,
        exclusive=exclusive,
        default_samplerate=samplerate,
    )


def find_device_by_identity(hostapi: str, device_name: str) -> int | None:
    """Resolve a saved (hostapi, device_name) to a current device index.

    Returns the FIRST matching integer index, or None if no device matches.
    Duplicate names (e.g. two USB headsets with identical labels) resolve to
    the lowest-index match — by design; PortAudio offers no other
    discriminator without raw MMDevice access.
    """
    hostapis = sd.query_hostapis()
    want_tag = hostapi.lower()
    for idx, dev in enumerate(sd.query_devices()):
        host_idx = int(dev.get("hostapi", -1))
        if host_idx < 0 or host_idx >= len(hostapis):
            continue
        tag = _HOSTAPI_TAG.get(hostapis[host_idx].get("name", ""))
        if tag != want_tag:
            continue
        if (dev.get("name") or "") != device_name:
            continue
        return idx
    return None


def refresh_devices() -> None:
    """Force PortAudio to re-scan host hardware.

    PortAudio caches the device list at Pa_Initialize; newly-plugged-in USB
    devices won't appear via sd.query_devices() until the library is
    re-initialized. The Refresh-devices button calls this before re-enumerating.
    """
    # sounddevice exposes the private re-init helpers as the documented way
    # to bounce PortAudio — see the sounddevice changelog and the
    # spencerkclark/sounddevice cookbook entries.
    sd._terminate()
    sd._initialize()
