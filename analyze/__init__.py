"""MusIQ-Lab music analysis pipeline driver."""
import os as _os
import sys as _sys

# ADTOF (drums) needs `tf.keras.optimizers.legacy` which Keras 3 (TF ≥ 2.16)
# removed. The shim is the `tf_keras` package + this env var. Must be set
# BEFORE any tensorflow import — basic-pitch imports TF transitively, so
# setting it inside analyze.stages.drums.run() is too late. Setting it here
# (analyze package init) ensures it's the first thing that happens when
# `python -m analyze` runs.
_os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

# Refuse to import on the wrong interpreter. The stack is built and locked
# against Linux/WSL2 + Python 3.11 + Torch 2.7/cu126; importing under the host
# Windows py3.13 conda env has previously triggered a bare `pip install` that
# downgraded torch 2.9 → 2.7+cpu across an unrelated env. Opt out only for
# read-only tooling (e.g. webui inspecting cached summaries) that does NOT
# pip-install anything.
if not _os.environ.get("MUSIQ_LAB_ALLOW_HOST_PYTHON"):
    if _sys.platform == "win32" or _sys.version_info[:2] != (3, 11):
        raise RuntimeError(
            f"analyze/ must run under WSL2 Python 3.11 (.venv/), got "
            f"{_sys.platform} py{_sys.version_info.major}.{_sys.version_info.minor}. "
            "See INSTALL.md Phase 4. Set MUSIQ_LAB_ALLOW_HOST_PYTHON=1 to override "
            "(read-only inspection only — never run `pip install` from this env)."
        )

__version__ = "0.1.0"

from analyze.pipeline import AnalyzeResult, PipelineError, analyze

__all__ = ["AnalyzeResult", "PipelineError", "analyze", "__version__"]
