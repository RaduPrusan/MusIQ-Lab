"""WASAPI audio backend — Phase 1 device-picker scaffold.

Phase 1 ships device enumeration and a WebSocket control surface that does
NOT open any PortAudio stream. Subsequent phases will add playback, stem
mixing, exclusive-mode fallback and loop-wrap support.

Public re-exports kept narrow so callers don't reach into submodules.
"""
from .devices import DeviceEntry, find_device_by_identity, list_output_devices

__all__ = ["DeviceEntry", "find_device_by_identity", "list_output_devices"]
