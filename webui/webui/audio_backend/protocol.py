"""Pydantic v2 models for the /api/audio/control WebSocket protocol.

Phase 1 covers only the device-picker scaffold ops:
  client → server:  list_devices, refresh_devices, set_device, ping
  server → client:  devices, ack, pong, error

Subsequent phases (load/play/pause/seek/clock-tick/loop) will add their own
models alongside these without changing the existing shapes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# --- Client → server ops ---------------------------------------------------


class ListDevicesOp(BaseModel):
    op: Literal["list_devices"]
    req: int


class RefreshDevicesOp(BaseModel):
    op: Literal["refresh_devices"]
    req: int


class SetDeviceOp(BaseModel):
    """Phase 1: server stores the choice on the WS session and acks.
    No PortAudio stream is opened. Phase 2 wires real playback.
    """

    op: Literal["set_device"]
    req: int
    hostapi: str
    device_name: str
    exclusive: bool
    samplerate: int


class PingOp(BaseModel):
    op: Literal["ping"]
    req: int
    perf_t_client: float


# --- Server → client messages ----------------------------------------------


class DeviceEntryMsg(BaseModel):
    id: str
    label: str
    hostapi: Literal["mme", "wasapi"]
    device_name: str
    device_index: int
    exclusive: bool
    default_samplerate: int


# Module-level alias so the `list:` field annotation below doesn't have to
# resolve the builtin `list` from inside the class body — under
# `from __future__ import annotations` the annotation is re-evaluated at
# model-build time with class locals visible, and the `list` field name
# would shadow the builtin (FieldInfo is not subscriptable). Aliasing
# sidesteps the lookup entirely.
_DeviceList = list[DeviceEntryMsg]


class DevicesMsg(BaseModel):
    type: Literal["devices"] = "devices"
    req: int
    list: _DeviceList = Field(default_factory=list)


class AckMsg(BaseModel):
    type: Literal["ack"] = "ack"
    req: int


class PongMsg(BaseModel):
    type: Literal["pong"] = "pong"
    req: int
    perf_t_client: float
    perf_t_server: float


class ErrorMsg(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    req: int | None = None


# --- Phase 2: load / play / pause / seek + state + clock ticks -------------


class LoadOp(BaseModel):
    op: Literal["load"]
    req: int
    slug: str  # cache slug; server resolves to MP3 path


class PlayOp(BaseModel):
    op: Literal["play"]
    req: int


class PauseOp(BaseModel):
    op: Literal["pause"]
    req: int


class SeekOp(BaseModel):
    op: Literal["seek"]
    req: int
    song_t: float


# `list` is a builtin; `_StemsList` aliases at module scope so the model body
# doesn't have to resolve it under `from __future__ import annotations`.
_StemsList = list[str]


class LoadedMsg(BaseModel):
    type: Literal["loaded"] = "loaded"
    req: int
    duration: float
    sample_rate: int  # device samplerate, post-resample
    source_available: bool
    stems_available: _StemsList = Field(default_factory=list)  # Phase 2: empty


class StateMsg(BaseModel):
    type: Literal["state"] = "state"
    playing: bool
    mode: Literal["source", "stems"] = "source"  # Phase 2: always "source"
    req: int | None = None


class ClockMsg(BaseModel):
    type: Literal["clock"] = "clock"
    song_t: float
    audio_t: float
    perf_t_server: float
    playing: bool


class EndedMsg(BaseModel):
    type: Literal["ended"] = "ended"


# --- Phase 3: stem mix (volume / mute / solo) + source↔stems mode toggle ----


class StemOp(BaseModel):
    """Per-stem mixer mutation. Any combination of vol/muted/soloed may be
    supplied; unset fields leave the existing state unchanged. This matches
    web-audio-engine.js where setStemVolume/Mute/Solo are independent setters.
    """

    op: Literal["stem"]
    req: int
    name: str
    vol: float | None = None
    muted: bool | None = None
    soloed: bool | None = None


class SetModeOp(BaseModel):
    op: Literal["set_mode"]
    req: int
    mode: Literal["source", "stems"]


# Dict result map for the stems-loaded background task. Keys: STEM_NAMES.
# Values: "loaded" | "missing" | "failed: <reason>" (free-form failure
# strings so the client can surface the real soxr/soundfile error).
_StemResultsMap = dict[str, str]


class StemsLoadedMsg(BaseModel):
    type: Literal["stems_loaded"] = "stems_loaded"
    req: int  # -1 for the background task that loads stems after `load`
    results: _StemResultsMap = Field(default_factory=dict)


# --- Phase 4: Exclusive + fallback chain ----------------------------------
#
# When `set_device` requests an Exclusive open but the device cannot be
# opened with the requested parameters, the server walks a documented
# fallback chain (Exclusive → Shared → MME). Each fallback is *still a
# success* — the AckMsg confirms the op landed — but the client gets a
# follow-up FallbackMsg telling it which row was actually opened and why
# the most-specific request didn't take. The client surfaces the reason
# as a toast.
#
# Reasons are short, machine-parseable strings of the form
#   "{stage}_failed:{err_label}"
# e.g. "exclusive_failed:device_in_use", "wasapi_failed:invalid_sample_rate".
# `humanizeFallbackReason` on the client maps these to user-facing text.
#
# When NO entry in the chain opens, the server emits ErrorMsg with
# code="engine_unavailable" instead; the client disposes the engine and
# falls back to WebAudio. This separation (FallbackMsg = partial-success,
# ErrorMsg = total-failure) avoids confusing "the device picker landed
# on a slightly-different row" with "the engine cannot run at all".


class FallbackMsg(BaseModel):
    type: Literal["fallback"] = "fallback"
    reason: str             # e.g. "exclusive_failed:device_in_use"
    chosen_hostapi: str     # "wasapi" or "mme"
    chosen_exclusive: bool
    chosen_samplerate: int
    req: int                # echoes the set_device req


# --- Phase 5: loop wrap + hotplug + latency info --------------------------
#
# `LoopOp` / `LoopClearOp` ship the user's loop region (start/end in seconds)
# to the server. The audio callback wraps inside the block when crossing
# `loop_end_sample` — see AudioSession._callback / set_loop / clear_loop.
#
# `StreamInfoMsg` carries the actually-opened PortAudio stream parameters
# (samplerate, blocksize, output_latency_sec) for the Settings UI to display
# as "Output: <kHz> · <frames> frames · <ms> ms buffer". The blocksize and
# latency are driver-reported and only known after open() succeeds, so this
# message is emitted as a follow-up to the AckMsg(set_device) — not as a
# field on it.


class LoopOp(BaseModel):
    op: Literal["loop"]
    req: int
    start: float
    end: float


class LoopClearOp(BaseModel):
    op: Literal["loop_clear"]
    req: int


class StreamInfoMsg(BaseModel):
    type: Literal["stream_info"] = "stream_info"
    samplerate: int
    blocksize: int
    output_latency_sec: float
    # Echoes set_device.req when emitted as a follow-up to a successful open.
    # None when emitted for some other reason (currently unused; reserved).
    req: int | None = None
