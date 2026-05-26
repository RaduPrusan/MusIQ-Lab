"""Probe whether the Charlie Puth file actually contains audio past 220.80s."""
import os, subprocess, soundfile as sf, numpy as np
from pathlib import Path

mp3 = str(Path(__file__).resolve().parents[1] / "cache" / "charlie_puth_attention" / "charlie_puth_attention.mp3")

# 1. Try seeking past the truncation point and decoding the tail.
print("=== Try ffmpeg seek -ss 221 (one second past where decode stops) ===")
out = "/tmp/tail.wav"
if os.path.exists(out): os.unlink(out)
r = subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error",
     "-ss", "221", "-i", mp3,
     "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
     out],
    capture_output=True, text=True,
)
if os.path.exists(out):
    info = sf.info(out)
    print(f"  -> tail.wav duration: {info.duration:.2f}s "
          f"(decoder DID find audio after 221s)" if info.duration > 0.5
          else f"  -> tail.wav duration: {info.duration:.2f}s (effectively empty)")
    if info.duration > 0.1:
        data, sr = sf.read(out)
        rms = float(np.sqrt(np.mean(data ** 2)))
        peak = float(np.max(np.abs(data)))
        print(f"     RMS = {rms:.6f}  peak = {peak:.6f}")
    os.unlink(out)
else:
    print(f"  ffmpeg stderr: {r.stderr[:300]}")

# 2. Try -ss 200 to confirm seeking works before the truncation.
print("\n=== Sanity: ffmpeg seek -ss 200 (well before truncation) ===")
out = "/tmp/before.wav"
if os.path.exists(out): os.unlink(out)
r = subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error",
     "-ss", "200", "-i", mp3,
     "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
     out],
    capture_output=True, text=True,
)
if os.path.exists(out):
    info = sf.info(out)
    print(f"  -> before.wav duration: {info.duration:.2f}s (from ss=200, expected ~20s)")
    data, sr = sf.read(out)
    rms = float(np.sqrt(np.mean(data ** 2)))
    print(f"     RMS = {rms:.6f}  (non-zero = real audio)")
    os.unlink(out)

# 3. Dump last 4 KB of file to see what's at the end.
print("\n=== Last bytes of MP3 file ===")
size = os.path.getsize(mp3)
print(f"  file size: {size} bytes")
with open(mp3, "rb") as f:
    f.seek(max(0, size - 256))
    tail = f.read(256)
print(f"  last 256 bytes hex (32-byte rows):")
for i in range(0, len(tail), 32):
    row = tail[i:i+32]
    hex_s = " ".join(f"{b:02x}" for b in row)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
    print(f"    {size - len(tail) + i:08x}: {hex_s}  {asc}")

# 4. Check for ID3v2 tag at start (may contain padding that bloats reported duration).
print("\n=== First bytes of MP3 file ===")
with open(mp3, "rb") as f:
    head = f.read(64)
print(f"  first 64 bytes hex:")
for i in range(0, len(head), 32):
    row = head[i:i+32]
    hex_s = " ".join(f"{b:02x}" for b in row)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
    print(f"    {i:08x}: {hex_s}  {asc}")
if head.startswith(b"ID3"):
    # ID3v2 size is in bytes 6..10 (7-bit-encoded)
    sz = head[6:10]
    id3_size = (sz[0] << 21) | (sz[1] << 14) | (sz[2] << 7) | sz[3]
    print(f"  ID3v2 header detected; tag size = {id3_size} bytes (+10 byte header)")
