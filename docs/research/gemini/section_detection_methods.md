# Music Section Detection Research (April 2026)

This document summarizes the research into music section detection (Music Structure Analysis - MSA) methods for the MusIQ-Lab project, specifically focusing on alternatives to the original `allin1` package which was dropped due to `NATTEN` dependency issues.

## Proposed Methods

### 1. all-in-one-fix (The Modernized Successor)
A community-maintained fork of the original `allin1` project, specifically patched for 2025/2026 environments.
- **Goal:** Provide a drop-in replacement for `allin1` with updated dependencies.
- **Pros:**
  - High accuracy using transformer-based models.
  - Provides semantic labels (Intro, Verse, Chorus, etc.).
  - Already optimized for PyTorch 2.x and newer CUDA versions.
- **Cons:**
  - Still relies on `NATTEN`, which requires verification against the local environment's ABI/API.
- **Integration:** `pip install all-in-one-fix`.

### 2. MSAF (Music Structure Analysis Framework)
A comprehensive framework that wraps multiple modular algorithms for music segmentation.
- **Goal:** Provide a stable, multi-algorithm platform for MSA.
- **Pros:**
  - **No NATTEN dependency.**
  - Modular architecture allows switching between different boundary detection and labeling algorithms.
  - Highly stable for academic and research use.
- **Cons:**
  - Might require minor compatibility updates for Python 3.11+.
- **Integration:** `pip install msaf`.

### 3. Native Librosa + Laplacian Segmentation
A lightweight, signal-processing approach using existing stack components (`librosa`, `scipy`, `scikit-learn`).
- **Goal:** Detect structural repetitions using Self-Similarity Matrices (SSM) and Spectral Clustering.
- **Pros:**
  - **Zero new dependencies.**
  - Immune to CUDA/NATTEN versioning issues.
  - Extremely fast and predictable.
- **Cons:**
  - Does not provide semantic labels (e.g., "Chorus") out of the box; labels sections as "A", "B", etc.
- **Integration:** Custom implementation using `librosa.segment.recurrence_matrix`.

## Summary Comparison

| Method | Implementation Effort | Stability | Semantic Labels? | Dependency Risk |
| :--- | :--- | :--- | :--- | :--- |
| **all-in-one-fix** | Low | Medium | Yes | High (NATTEN) |
| **MSAF** | Medium | High | Yes | Low |
| **Librosa Native** | High | Highest | No | None |

## Recommendation
Attempt to validate **all-in-one-fix** first to preserve the high-quality semantic labeling. If `NATTEN` remains a blocker, pivot to **MSAF** or a custom **Librosa** implementation.
