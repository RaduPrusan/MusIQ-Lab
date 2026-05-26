"""One-shot diagnostic for the Charlie Puth - Attention truncation."""
import os, subprocess, soundfile as sf
from pathlib import Path

mp3 = str(Path(__file__).resolve().parents[1] / "cache" / "charlie_puth_attention" / "charlie_puth_attention.mp3")
clean = "/tmp/charlie_test.wav"
subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
     "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", clean],
    check=True,
)
info = sf.info(clean)
size = os.path.getsize(clean)
print(f"current ffmpeg clean.wav duration = {info.duration:.2f}s ({info.frames} frames @ {info.samplerate}Hz)")
print(f"current ffmpeg clean.wav file size = {size} bytes")
# Cross-check by running mp3info via ffmpeg with stream-level detail.
result = subprocess.run(
    ["ffprobe", "-v", "error", "-show_streams", mp3],
    capture_output=True, text=True, check=True,
)
print("--- ffprobe stream info ---")
for line in result.stdout.splitlines():
    if any(k in line for k in ("duration", "nb_frames", "codec_name", "bit_rate", "start_time")):
        print(f"  {line}")
os.unlink(clean)
