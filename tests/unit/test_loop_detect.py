import pytest

from analyze.derived.loop_detect import predominant_chord_loop


def make_chords(labels_with_times: list[tuple[float, float, str]]) -> list[dict]:
    """Helper to build chord dicts."""
    return [{"start": s, "end": e, "label": l} for (s, e, l) in labels_with_times]


def test_simple_two_chord_loop():
    chords = make_chords([
        (0.0, 1.0, "F:min"),
        (1.0, 2.0, "C:min"),
        (2.0, 3.0, "F:min"),
        (3.0, 4.0, "C:min"),
        (4.0, 5.0, "F:min"),
        (5.0, 6.0, "C:min"),
    ])
    loop, appearances = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min"]
    assert len(appearances) == 3  # three full passes
    assert appearances[0] == {"start": 0.0, "end": 2.0}
    assert appearances[1] == {"start": 2.0, "end": 4.0}
    assert appearances[2] == {"start": 4.0, "end": 6.0}


def test_collapses_consecutive_duplicates():
    chords = make_chords([
        (0.0, 1.0, "F:min"),
        (1.0, 2.0, "F:min"),
        (2.0, 3.0, "C:min"),
        (3.0, 4.0, "F:min"),
        (4.0, 5.0, "C:min"),
    ])
    loop, appearances = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min"]
    assert len(appearances) == 2  # [F:min, C:min] appears twice (with the run of F:min collapsed)


def test_longer_loop_wins_when_score_higher():
    # 4-chord loop appearing 3 times = score 12
    # 2-chord loop appearing 6 times = score 12 (tie — longer loop wins by tie-breaker)
    chords = make_chords([
        (i * 1.0, (i + 1) * 1.0, label)
        for i, label in enumerate(["F:min", "C:min", "Ab:maj", "Eb:maj"] * 3)
    ])
    loop, _ = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min", "Ab:maj", "Eb:maj"]


def test_no_repeating_loop_returns_none():
    chords = make_chords([
        (0.0, 1.0, "C:maj"),
        (1.0, 2.0, "G:maj"),
        (2.0, 3.0, "F:maj"),
        (3.0, 4.0, "Am:min"),
    ])
    loop, appearances = predominant_chord_loop(chords)
    assert loop is None
    assert appearances == []


def test_handles_single_chord():
    chords = make_chords([(0.0, 1.0, "C:maj")])
    loop, appearances = predominant_chord_loop(chords)
    assert loop is None
    assert appearances == []


def test_skips_no_chord_spans():
    # "N" entries collapse into the sequence; the loop algorithm operates on labels.
    # Per spec, we leave N in place — loop just won't include them as part of any meaningful pattern.
    chords = make_chords([
        (0.0, 1.0, "N"),
        (1.0, 2.0, "F:min"),
        (2.0, 3.0, "C:min"),
        (3.0, 4.0, "F:min"),
        (4.0, 5.0, "C:min"),
    ])
    loop, _ = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min"]
