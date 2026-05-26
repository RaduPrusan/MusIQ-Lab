"""Phase 2 WASAPI smoke-test via the /api/audio/control WS.

Connects to 127.0.0.1:8766, picks a WASAPI device, loads a slug, plays,
collects ~20 clock ticks, asserts song_t is monotonic increasing, then
pauses. Replaces the (un-runnable here) Playwright UI walk-through with
a backend-only verification that the engine end-to-end is healthy.
"""
import asyncio
import json
import sys

import websockets


SLUG = "baleen_unmedicated"
DEVICE_NAME = "USB Out 1/2 (BEHRINGER FLOW 8 (Recording))"


async def main() -> int:
    uri = "ws://127.0.0.1:8766/api/audio/control"
    print(f"connecting to {uri}", flush=True)
    async with websockets.connect(uri) as ws:
        # 1. list devices to confirm WASAPI host present and find the right entry
        await ws.send(json.dumps({"op": "list_devices", "req": 1}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        devices = msg.get("list", [])
        wasapi = [d for d in devices if d.get("hostapi") == "wasapi"]
        if not wasapi:
            print(f"no WASAPI devices in list: {msg}", file=sys.stderr)
            return 1
        match = next((d for d in wasapi if DEVICE_NAME in d.get("device_name", "")), None)
        if not match:
            # Fall back to first WASAPI device.
            match = wasapi[0]
            print(f"target device '{DEVICE_NAME}' not found; using {match['device_name']}", file=sys.stderr)
        print(f"using device: {match['device_name']} ({match['hostapi']})", flush=True)

        # 2. set_device
        await ws.send(json.dumps({
            "op": "set_device", "req": 2,
            "hostapi": match["hostapi"],
            "device_name": match["device_name"],
            "exclusive": False,
            "samplerate": int(match.get("default_samplerate", 48000)),
        }))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        print("set_device ack:", msg, flush=True)
        if msg.get("type") == "error":
            return 1

        # 3. load
        await ws.send(json.dumps({"op": "load", "req": 3, "slug": SLUG}))
        # Server may send progress messages; wait until we see "loaded".
        loaded = None
        for _ in range(20):
            msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if msg.get("type") in ("loaded", "error"):
                loaded = msg
                break
        if not loaded or loaded.get("type") == "error":
            print(f"load failed: {loaded}", file=sys.stderr)
            return 1
        print(f"loaded duration={loaded.get('duration')} source_available={loaded.get('source_available')}", flush=True)

        # 4. play + collect clock ticks
        await ws.send(json.dumps({"op": "play", "req": 4}))
        clocks = []
        for _ in range(40):
            msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if msg.get("type") == "clock":
                clocks.append((msg["song_t"], msg.get("playing")))
                if len(clocks) >= 20:
                    break
            elif msg.get("type") == "error":
                print(f"play error: {msg}", file=sys.stderr)
                return 1
        if len(clocks) < 5:
            print(f"too few clock ticks: {clocks}", file=sys.stderr)
            return 1
        print(f"collected {len(clocks)} clock ticks; first 3: {clocks[:3]}; last 3: {clocks[-3:]}", flush=True)
        # Assert monotonic non-decreasing song_t.
        regressions = [(a, b) for a, b in zip(clocks[:-1], clocks[1:]) if b[0] < a[0]]
        if regressions:
            print(f"FAIL: song_t regressed: {regressions[:3]}", file=sys.stderr)
            return 1
        # Should have advanced at least ~0.1s over 20 ticks (with default ~40Hz tick).
        delta = clocks[-1][0] - clocks[0][0]
        if delta < 0.1:
            print(f"FAIL: song_t barely advanced: {delta:.4f}s over {len(clocks)} ticks", file=sys.stderr)
            return 1
        print(f"PASS: song_t advanced {delta:.3f}s monotonically over {len(clocks)} ticks", flush=True)

        # 5. pause
        await ws.send(json.dumps({"op": "pause", "req": 5}))
        for _ in range(20):
            msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if msg.get("type") == "state" and msg.get("playing") is False:
                print("pause confirmed:", msg, flush=True)
                break
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
