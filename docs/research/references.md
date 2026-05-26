# References

All papers, repositories, PyPI packages, and benchmarks referenced across the docs. Grouped by stage.

## Stems

- **audio-separator**: <https://github.com/nomadkaraoke/python-audio-separator> · PyPI: `audio-separator`
- **BS-RoFormer paper**: Li et al., "Music Source Separation with Band-Split RoPE Transformer", arXiv:2309.02612 (ISMIR/SDX 2023). <https://arxiv.org/abs/2309.02612>
- **Mel-Band RoFormer paper**: Lu et al., "Mel-Band RoFormer for Music Source Separation", arXiv:2310.01809. <https://arxiv.org/abs/2310.01809>
- **BS-RoFormer reference impl**: <https://github.com/lucidrains/BS-RoFormer>
- **HTDemucs paper**: Rouard et al., "Hybrid Transformers for Music Source Separation", ICASSP 2023. <https://arxiv.org/abs/2211.08553>
- **Demucs**: <https://github.com/facebookresearch/demucs>
- **Recommended UVR model registry**: <https://github.com/nomadkaraoke/python-audio-separator/discussions/133>
- **MVSEP algorithm comparison**: <https://mvsep.com/en/algorithms>

## Joint metrical + structural (allin1)

- **All-In-One paper**: Kim & Nam, "All-In-One Metrical and Functional Structure Analysis With Neighborhood Attentions on Demixed Audio", WASPAA 2023. arXiv:2307.16425. <https://arxiv.org/abs/2307.16425>
- **All-In-One repo**: <https://github.com/mir-aidj/all-in-one> · PyPI: `allin1`
- **NATTEN (dependency)**: <https://github.com/SHI-Labs/NATTEN> · install: <https://natten.org/install/>
- **all-in-one-fix (NATTEN-version-tolerant fork)**: PyPI: `allin1fix`

## Beat tracking

- **Beat This! paper**: Foscarin, Schlüter, Widmer, "Beat This! Accurate Beat Tracking Without DBN Postprocessing", ISMIR 2024. <https://arxiv.org/abs/2407.21658>
- **Beat This! repo**: <https://github.com/CPJKU/beat_this> · PyPI: `beat-this`
- **BEAST (online beat tracking)**: ICASSP 2024. arXiv:2312.17156. <https://arxiv.org/abs/2312.17156>
- **Beat Transformer**: Zhao et al., ISMIR 2022. arXiv:2209.07140. <https://arxiv.org/abs/2209.07140>
- **BeatNet**: Heydari et al., ISMIR 2021. <https://github.com/mjhydri/BeatNet>

## Key detection

- **S-KEY repo**: <https://github.com/deezer/skey> · install: `pip install git+https://github.com/deezer/skey.git`
- **S-KEY paper**: Kong et al., "S-KEY: Self-Supervised Learning of Major and Minor Keys from Audio", ICASSP 2024.
- **Krumhansl-Schmuckler key profiles** (the older librosa K-S algorithm): Krumhansl & Schmuckler, *Cognitive Foundations of Musical Pitch*, 1990.

## Chord recognition

- **lv-chordia (PyPI)**: <https://pypi.org/project/lv-chordia/>
- **Underlying paper**: Park et al., "Large-Vocabulary Chord Transcription via Chord Structure Decomposition", ISMIR 2019. <https://archives.ismir.net/ismir2019/paper/000078.pdf>
- **Reference implementation**: <https://github.com/music-x-lab/ISMIR2019-Large-Vocabulary-Chord-Recognition>
- **Harte chord grammar** (the syntax used in JAMS chord namespace): Harte et al., "Symbolic Representation of Musical Chords", ISMIR 2005.
- **BTC (Bi-directional Transformer for Chord Recognition)**: Park et al., ISMIR 2019. <https://github.com/jayg996/BTC-ISMIR19>
- **Harmony Transformer**: Chen & Su, ISMIR 2019. <https://archives.ismir.net/ismir2019/paper/000030.pdf>
- **ChordCoT (LLM CoT for ACR)**: arXiv:2509.18700 (Sept 2025). <https://arxiv.org/html/2509.18700v1>
- **MIREX 2025 Audio Chord Estimation results**: <https://music-ir.org/mirex/wiki/2025:Audio_Chord_Estimation_Results>
- **ISMIR 2025 ACE Conformer (consonance-based training)**: <https://ismir2025program.ismir.net/poster_268.html>
- **autochord** (alternative, smaller vocab): <https://github.com/cjbayron/autochord>
- **chord-extractor** (alternative, Chordino wrapper): <https://github.com/ohollo/chord-extractor>

## Polyphonic note transcription

- **Basic Pitch (Spotify)**: <https://github.com/spotify/basic-pitch> · PyPI: `basic-pitch`
- **Basic Pitch paper**: Bittner et al., "A Lightweight Instrument-Agnostic Model for Polyphonic Note Transcription and Multipitch Estimation", ICASSP 2022.
- **MR-MT3** (advanced/research): Tan et al., "MR-MT3: Memory Retaining Multi-Track Music Transcription to Mitigate Instrument Leakage", ICASSP 2024. arXiv:2403.10024. Repo: <https://github.com/gudgud96/MR-MT3>
- **YourMT3+** (advanced/research): mimbres et al., MLSP 2024. arXiv:2407.04822. Repo: <https://github.com/mimbres/YourMT3>
- **MT3 (original)**: Gardner et al., "MT3: Multi-Task Multitrack Music Transcription", ICLR 2022.
- **SOME (singing-to-MIDI)**: <https://github.com/openvpi/SOME>
- **Magenta**: <https://github.com/magenta/magenta>

## Pitch (monophonic) / vocal f0

- **FCPE paper**: Liu et al., "FCPE: A Fast Context-based Pitch Estimation Model", arXiv:2509.15140. <https://arxiv.org/abs/2509.15140>
- **FCPE repo**: <https://github.com/CNChTu/FCPE> · PyPI: `torchfcpe`
- **PESTO paper**: Riou et al., "PESTO: Pitch Estimation with Self-Supervised Transposition-Equivariant Objective", ISMIR 2023. <https://hal.science/hal-04260042v1/document>
- **PESTO repo**: <https://github.com/SonyCSLParis/pesto> · PyPI: `pesto-pitch`
- **CREPE (older, baseline)**: Kim et al., ICASSP 2018. <https://github.com/marl/crepe>
- **RMVPE**: Robust Vocal Pitch Estimation. PyPI: `rmvpe-onnx`. (Recommended by Codex; we use PESTO instead.)

## Output / interchange

- **JAMS spec paper**: Humphrey et al., "JAMS: A JSON Annotated Music Specification for Reproducible MIR Research", ISMIR 2014. <https://archives.ismir.net/ismir2014/paper/000355.pdf>
- **JAMS repo**: <https://github.com/marl/jams> · PyPI: `jams`
- **JAMS docs (namespaces)**: <https://jams.readthedocs.io/en/stable/namespace.html>
- **JAMS examples**: <https://jams.readthedocs.io/en/stable/examples.html>
- **mir_eval (evaluation library)**: <https://github.com/craffel/mir_eval>

## Self-supervised music representation (optional add-on)

- **MERT paper**: Li et al., "MERT: Acoustic Music Understanding Model with Large-Scale Self-supervised Training", ICLR 2024. arXiv:2306.00107. <https://arxiv.org/abs/2306.00107>
- **MERT repo**: <https://github.com/yizhilll/MERT>
- **MERT v1 330M (HuggingFace)**: <https://huggingface.co/m-a-p/MERT-v1-330M>
- **MARBLE benchmark**: <https://github.com/m-mir/marble>

## LLM orchestrator pattern

- **ChordCoT-style enhancement of ACR**: arXiv:2509.18700 (Sept 2025). <https://arxiv.org/html/2509.18700v1>

## Misc

- **librosa**: <https://librosa.org/>
- **mido (MIDI I/O)**: <https://github.com/mido/mido>
- **pretty_midi (MIDI utilities)**: <https://github.com/craffel/pretty-midi>
- **soundfile (audio I/O)**: <https://github.com/bastibe/python-soundfile>

## Independent research sources

- Codex CLI (gpt-5.5 high) research output: `.research/codex_response.txt`
- Gemini CLI (gemini-3.1-pro-preview, with grounded Google Search) research summary: see Stage-7 result in conversation log
- Original Claude research: this set of docs
