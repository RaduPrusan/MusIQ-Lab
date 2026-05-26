"""Probe different decoders / flags to find one that decodes the full Charlie Puth file."""
import os, subprocess, soundfile as sf, shutil
from pathlib import Path

mp3 = str(Path(__file__).resolve().parents[1] / "cache" / "charlie_puth_attention" / "charlie_puth_attention.mp3")

def probe(label, cmd, out="/tmp/probe_test.wav"):
    if os.path.exists(out):
        os.unlink(out)
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  exit {r.returncode}\n  stderr: {r.stderr[:400]}")
        return
    if not os.path.exists(out):
        print(f"  (no output file)")
        return
    info = sf.info(out)
    print(f"  -> duration {info.duration:.2f}s  ({info.frames} frames, {os.path.getsize(out)} bytes)")
    os.unlink(out)

# A: plain ffmpeg (baseline — what stems.py currently does)
probe("A. ffmpeg baseline (current pipeline)", [
    "ffmpeg", "-y", "-loglevel", "error",
    "-i", mp3, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
    "/tmp/probe_test.wav",
])

# B: ffmpeg with corruption-tolerant flags
probe("B. ffmpeg with err_detect=ignore_err + discardcorrupt", [
    "ffmpeg", "-y", "-loglevel", "error",
    "-err_detect", "ignore_err", "-fflags", "+discardcorrupt",
    "-i", mp3, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
    "/tmp/probe_test.wav",
])

# C: ffmpeg with -bitexact to disable any AV optimizations that might skip
probe("C. ffmpeg with -analyzeduration 100M -probesize 100M", [
    "ffmpeg", "-y", "-loglevel", "error",
    "-analyzeduration", "100M", "-probesize", "100M",
    "-i", mp3, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
    "/tmp/probe_test.wav",
])

# D: ffmpeg copying the stream (no re-decode) and inspecting the raw
print("\n=== D. ffmpeg stream-copy → MP3 (no decode) — what's the byte-level extent? ===")
out_mp3 = "/tmp/probe_copy.mp3"
if os.path.exists(out_mp3):
    os.unlink(out_mp3)
r = subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-c:a", "copy", out_mp3],
    capture_output=True, text=True,
)
print(f"  stream-copy size: {os.path.getsize(out_mp3) if os.path.exists(out_mp3) else 'n/a'} bytes "
      f"(original: {os.path.getsize(mp3)})")
# Probe the duration of the stream-copied output
r2 = subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "default=noprint_wrappers=1:nokey=1", out_mp3],
    capture_output=True, text=True,
)
print(f"  stream-copy ffprobe duration: {r2.stdout.strip()}s")
# Now decode the stream-copy
probe("D-decode. Decode the stream-copied MP3", [
    "ffmpeg", "-y", "-loglevel", "error", "-i", out_mp3,
    "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
    "/tmp/probe_test.wav",
])
os.unlink(out_mp3)

# E: mpg123 if installed
print("\n=== E. mpg123 (alternate decoder) ===")
if shutil.which("mpg123"):
    r = subprocess.run(["mpg123", "-q", "-w", "/tmp/probe_test.wav", mp3],
                       capture_output=True, text=True)
    if os.path.exists("/tmp/probe_test.wav"):
        info = sf.info("/tmp/probe_test.wav")
        print(f"  -> duration {info.duration:.2f}s")
        os.unlink("/tmp/probe_test.wav")
    else:
        print(f"  (failed) {r.stderr[:200]}")
else:
    print("  mpg123 not installed; apt install mpg123 to test")
