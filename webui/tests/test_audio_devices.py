"""Phase 1 — device enumeration tests for webui.audio_backend.devices."""
from __future__ import annotations

import pytest


@pytest.fixture
def fake_devices(monkeypatch):
    """Inject a deterministic 5-device, 4-hostapi snapshot.

    The shape mirrors what sounddevice returns on Windows: every output device
    appears once per host API (MME / DirectSound / WASAPI / WDM-KS). One input-
    only mic is included to verify the max_output_channels filter; one MME
    speaker plus a DirectSound copy, a WASAPI copy and a WDM-KS copy of the
    same physical "Speakers (Realtek)" endpoint exercise the host-API filter
    and the WASAPI Shared+Exclusive doubling.
    """
    hostapis = [
        {"name": "MME"},                       # 0
        {"name": "Windows DirectSound"},       # 1
        {"name": "Windows WASAPI"},            # 2
        {"name": "Windows WDM-KS"},            # 3
    ]
    devices = [
        # 0: MME input-only mic — filtered out (max_output_channels=0)
        {"name": "Microphone (Realtek)", "hostapi": 0,
         "max_output_channels": 0, "default_samplerate": 48000.0},
        # 1: MME speaker — emits one row
        {"name": "Speakers (Realtek)", "hostapi": 0,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        # 2: DirectSound copy — filtered out (out of scope for v1)
        {"name": "Primary Sound Driver", "hostapi": 1,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        # 3: WASAPI speaker — emits TWO rows (Shared + Exclusive)
        {"name": "Speakers (Realtek)", "hostapi": 2,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        # 4: WDM-KS copy — filtered out
        {"name": "Speakers (Realtek)", "hostapi": 3,
         "max_output_channels": 2, "default_samplerate": 48000.0},
    ]
    import sounddevice as sd
    monkeypatch.setattr(sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sd, "query_hostapis", lambda: hostapis)
    return devices, hostapis


def test_list_output_devices_filters_and_doubles_wasapi(fake_devices):
    from webui.audio_backend import list_output_devices

    rows = list_output_devices()
    # MME mic skipped, DirectSound skipped, WDM-KS skipped.
    # MME speaker → 1 row. WASAPI speaker → 2 rows (Shared + Exclusive).
    assert len(rows) == 3, rows

    mme_rows = [r for r in rows if r.hostapi == "mme"]
    wasapi_rows = [r for r in rows if r.hostapi == "wasapi"]
    assert len(mme_rows) == 1
    assert len(wasapi_rows) == 2

    mme = mme_rows[0]
    assert mme.device_name == "Speakers (Realtek)"
    assert mme.device_index == 1
    assert mme.exclusive is False
    assert mme.default_samplerate == 48000
    assert "MME" in mme.label

    shared = next(r for r in wasapi_rows if not r.exclusive)
    excl = next(r for r in wasapi_rows if r.exclusive)
    assert shared.device_name == "Speakers (Realtek)"
    assert shared.device_index == 3
    assert "Shared" in shared.label
    assert excl.device_index == 3
    assert "Exclusive" in excl.label
    # Session-scoped id surfaces the index so the JS side can correlate
    # before re-resolving against (hostapi, name) on a later page load.
    assert "3" in shared.id and "3" in excl.id
    assert shared.id != excl.id


def test_find_device_by_identity_returns_first_match(fake_devices):
    from webui.audio_backend import find_device_by_identity

    # MME speaker
    assert find_device_by_identity("mme", "Speakers (Realtek)") == 1
    # WASAPI speaker
    assert find_device_by_identity("wasapi", "Speakers (Realtek)") == 3


def test_find_device_by_identity_returns_none_when_absent(fake_devices):
    from webui.audio_backend import find_device_by_identity

    assert find_device_by_identity("mme", "No Such Device") is None
    assert find_device_by_identity("wasapi", "No Such Device") is None
    # Unknown hostapi names also return None (we don't currently surface
    # DirectSound or WDM-KS, so callers should never ask for them).
    assert find_device_by_identity("directsound", "Speakers (Realtek)") is None


def test_find_device_by_identity_duplicate_names_returns_first(monkeypatch):
    """Two USB headsets with the same name share a device_name. The resolver
    deterministically returns the first match (lowest index) — by design, as
    PortAudio offers no other discriminator without raw MMDevice access.
    """
    import sounddevice as sd
    hostapis = [{"name": "Windows WASAPI"}]
    devices = [
        {"name": "Headset (USB)", "hostapi": 0,
         "max_output_channels": 2, "default_samplerate": 48000.0},
        {"name": "Headset (USB)", "hostapi": 0,
         "max_output_channels": 2, "default_samplerate": 48000.0},
    ]
    monkeypatch.setattr(sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sd, "query_hostapis", lambda: hostapis)

    from webui.audio_backend import find_device_by_identity
    assert find_device_by_identity("wasapi", "Headset (USB)") == 0


# ---------------------------------------------------------------------------
# Phase 5 — hotplug refresh
# ---------------------------------------------------------------------------


def test_refresh_devices_calls_terminate_initialize(monkeypatch):
    """`refresh_devices()` must call `sd._terminate(); sd._initialize()` in
    order. PortAudio caches the device list at init; newly-plugged-in USB
    devices only appear after a re-init (memory-noted research finding).
    """
    import sounddevice as sd

    order: list[str] = []

    def fake_terminate():
        order.append("terminate")

    def fake_initialize():
        order.append("initialize")

    monkeypatch.setattr(sd, "_terminate", fake_terminate, raising=False)
    monkeypatch.setattr(sd, "_initialize", fake_initialize, raising=False)

    from webui.audio_backend.devices import refresh_devices
    refresh_devices()
    assert order == ["terminate", "initialize"], (
        f"refresh_devices must call _terminate then _initialize; got {order}"
    )
