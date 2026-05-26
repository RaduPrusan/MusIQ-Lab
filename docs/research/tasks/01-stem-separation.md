# Stem separation

Splits the input MP3 into per-instrument WAV files (vocals, drums, bass, other — optionally guitar/piano too). Almost every downstream task benefits from clean stems: chord recognition runs better on the harmonic mix, vocal f0 is dramatically more accurate on isolated vocals, polyphonic transcription works far better per-stem than on the full mix.

## ✅ Recommended: `audio-separator[gpu]`

Wraps the entire UVR (Ultimate Vocal Remover) model zoo plus Demucs in a single CLI / Python API.

### Install

```bash
pip install "audio-separator[gpu]"
# ffmpeg already installed system-wide on this machine
```

### Usage — CLI

```bash
# 4-stem split with the recommended BS-RoFormer model
audio-separator song.mp3 \
    --model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt \
    --output_dir cache/<song-id>/stems/

# 6-stem split (vocals/drums/bass/guitar/piano/other) using Demucs
audio-separator song.mp3 \
    --model_filename htdemucs_6s.yaml \
    --output_dir cache/<song-id>/stems/

# List available models
audio-separator --list_models
```

### Usage — Python

```python
from audio_separator.separator import Separator

s = Separator(output_dir="cache/<song-id>/stems/")
s.load_model("model_bs_roformer_ep_317_sdr_12.9755.ckpt")
output_files = s.separate("song.mp3")
# output_files is a list of paths to the produced WAVs
```

### Recommended models for this pipeline

| Model | Use | SDR (vocals) |
|---|---|---|
| `model_bs_roformer_ep_317_sdr_12.9755.ckpt` | Vocals + instrumental (highest single-pair quality) | 12.98 dB |
| `htdemucs_6s.yaml` | 6-stem split: vocals / drums / bass / guitar / piano / other | ~9 dB |
| `Mel-Roformer-Vocal-Becruily.ckpt` | Vocals isolation (excellent on synthetic / autotuned vocals) | ~12 dB |

For the default pipeline we use `htdemucs_6s.yaml` because the 6-stem split gives Stage 6 (per-stem transcription) more material to work with. The BS-RoFormer model is run additionally for the vocals stem because it's noticeably cleaner there — `audio-separator` handles ensembling implicitly when you call `separate()` with multiple loaded models.

### Output format

WAV files (44.1 kHz, stereo, 16-bit PCM by default). Filenames follow the model's stem schema:

```
song (Vocals) [model_bs_roformer_ep_317_sdr_12.9755].wav
song (Drums) [htdemucs_6s].wav
song (Bass) [htdemucs_6s].wav
song (Guitar) [htdemucs_6s].wav
song (Piano) [htdemucs_6s].wav
song (Other) [htdemucs_6s].wav
```

The pipeline renames these to canonical names (`vocals.wav`, `drums.wav`, etc.) before passing to downstream stages.

### Accuracy

- BS-RoFormer family is current SOTA on the SDX23 (Sound Demixing Challenge) leaderboard; ~3 dB SDR ahead of HTDemucs on vocals
- HTDemucs 6-stem still leads on multi-stem splits (guitar / piano)
- Either is significantly ahead of Spleeter (2019, ~5 dB SDR) — Spleeter is now obsolete for quality work

### Caveats

- Models are downloaded on first use to `~/.cache/audio-separator/`. ~5 GB across all UVR models; you only need a handful
- UVR community models have varying licences — check before redistributing produced stems commercially. Demucs is BSD-licensed and safer for redistributable use. For personal educational use neither is an issue
- 6-stem Demucs is significantly slower than 4-stem; budget ~60 s on RTX 3090 for a 4-min track

## ↳ Alternative: `demucs` directly

If you want to use only Demucs (no UVR ecosystem), `demucs` is its own well-packaged CLI.

```bash
pip install demucs
demucs --two-stems=vocals song.mp3            # 2-stem
demucs -n htdemucs_ft song.mp3                 # 4-stem fine-tuned
demucs -n htdemucs_6s song.mp3                 # 6-stem
```

Use this if `audio-separator` install fails for some reason or if you're avoiding UVR-licensed checkpoints.

## ↳ Alternative: `bs-roformer-infer` (raw)

Standalone PyPI wrapper for BS-RoFormer with no UVR baggage:

```bash
pip install bs-roformer-infer
```

Smaller dependency footprint than `audio-separator`. Only does BS-RoFormer (no Demucs, no MDX). Use if you want minimum surface area.

## 🧪 Experimental: train your own with `Music-Source-Separation-Training`

For the curious: <https://github.com/ZFTurbo/Music-Source-Separation-Training> hosts training recipes for community-trained UVR/RoFormer variants. Out of scope for the analysis pipeline.

## Cross-validation hooks

Stem separation feeds:

- **Stage 5 (chords)**: chord recognizer runs on the original mix (chord recognition is best on the full harmonic context). Stems are *not* fed to chord recognition.
- **Stage 6 (transcription)**: `basic-pitch` runs on each harmonic stem separately. This is critical — running Basic Pitch on the full mix is far less accurate than per-stem.
- **Stage 7 (vocal f0)**: FCPE / PESTO require clean monophonic vocal — they fail on full-mix audio. Always feed the isolated vocals stem.
- **Stage 2 (allin1)**: `allin1` does its own internal stem separation; we don't pass our stems to it. (Possible future optimisation: pre-feed our higher-quality stems to allin1 if its API supports it.)

## Sources

- audio-separator repo and discussion #133 (model recommendations): <https://github.com/nomadkaraoke/python-audio-separator>
- BS-RoFormer paper: <https://arxiv.org/abs/2309.02612>
- HTDemucs paper: <https://arxiv.org/abs/2211.08553>
- MVSEP algorithm leaderboard: <https://mvsep.com/en/algorithms>
