# analyze/vendor/

Third-party MIR models that we don't redistribute through this repo. Each
sub-directory is populated by an install script under `scripts/` — the
contents themselves are gitignored.

## larsnet/

Drum source separation U-Nets from [polimi-ispl/larsnet][1]. Used by
`analyze/stages/drums.py` to split the htdemucs `(Drums)` stem into 5
sub-stems (kick, snare, toms, hi-hat, cymbals) before per-stem onset
detection.

**Install:**

```bash
bash scripts/install-larsnet.sh
```

This clones the upstream repo and downloads the pretrained weights
(~562 MB) from the authors' Google Drive. Idempotent.

**License:**

- Code: no formal license declared upstream. Treat as "all rights reserved";
  personal / research use only.
- Weights: **CC BY-NC 4.0** (non-commercial). See upstream README for the
  full grant.

If the drums stage needs to skip (e.g. checkpoints not installed on a fresh
clone), the pipeline soft-fails the stage and continues — the other
analyses still run.

[1]: https://github.com/polimi-ispl/larsnet

## chromaprint/

The `fpcalc` audio-fingerprint CLI from [acoustid/chromaprint][2]. Used by
`analyze/stages/identify.py` to fingerprint the source MP3 before posting
to the AcoustID lookup endpoint, which returns a MusicBrainz recording
ID we then enrich into title / artist / release / year / ISRC.

**Install:**

```bash
bash scripts/install-chromaprint.sh
```

Downloads the v1.5.1 Linux x86_64 release binary (~5 MB, single static
executable). Idempotent. The vendor dir contains only this binary plus
a `.gitkeep`.

**License:** LGPL 2.1 (Chromaprint itself). The `fpcalc` binary is
distributed under the same terms; we ship a copy via the install script
rather than redistributing through this repo.

[2]: https://github.com/acoustid/chromaprint

## essentia-models/

High-level SVM classifier models trained on the Million Song Dataset by
the MTG ([upstream models][3]). Intended to back Essentia's
`MusicExtractorSVM` for danceability / mood / voice-instrumental
classification, called from `analyze/stages/essentia_extract.py`.

**Install:**

```bash
bash scripts/install-essentia.sh
```

Installs Essentia into the project `.venv` (PyPI wheel, no C++ compile
on manylinux Python 3.11) and downloads the 10 model `.history` files
(~14 MB total) from the MTG model archive.

**License:** **CC BY-NC-SA 4.0** (uniformly across all 10 models).
Non-commercial use only.

**⚠ Known limitation (2026-05-11):** Pure-PyPI Essentia does NOT include
`gaia2` at runtime, so the SVM classifiers can't be loaded — they need
`MusicExtractorSVM` + `GaiaTransform`, both of which import gaia. The
low-level path (tempo, three key estimators, EBU R128 loudness,
dynamic complexity) works fine — that's the genuinely useful
cross-check vs the analyze pipeline. The high-level classifications
degrade to `{available: false, reason: "...gaia2..."}` and the webui
Acoustic Profile card hides the danceability bar + mood pills.

To unlock the SVMs you'd need to build [`gaia2`][4] from source
(requires Qt5 + swig + a C++ toolchain), then rebuild Essentia with
`--with-gaia`. Out of scope for the local install; deferred.

[3]: https://essentia.upf.edu/models.html
[4]: https://github.com/MTG/gaia
