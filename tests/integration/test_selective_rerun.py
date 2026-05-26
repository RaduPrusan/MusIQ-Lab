"""
Selective-rerun round-trip integration tests.

The pure validation / graph tests that were here have been moved to
tests/unit/test_stage_deps.py (they don't require a fixture mp3).

Real end-to-end round-trip tests (run → invalidate → selective-rerun → verify
artifacts on disk) will land here as part of WI-12.
"""
