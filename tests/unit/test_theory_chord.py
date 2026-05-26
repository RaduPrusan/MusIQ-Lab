import pytest

from analyze.derived.theory import Chord, parse_chord


def test_parse_chord_simple_minor():
    c = parse_chord("F:min")
    assert c.root_pc == 5
    assert c.bass_pc == 5  # no inversion → bass = root
    assert c.quality == "min"
    assert c.extensions == []
    assert c.is_no_chord is False


def test_parse_chord_simple_major():
    c = parse_chord("C:maj")
    assert c.root_pc == 0
    assert c.bass_pc == 0
    assert c.quality == "maj"
    assert c.extensions == []


def test_parse_chord_sharp_root():
    c = parse_chord("C#:maj")
    assert c.root_pc == 1
    assert c.quality == "maj"


def test_parse_chord_flat_root():
    c = parse_chord("Eb:maj")
    assert c.root_pc == 3
    assert c.quality == "maj"


def test_parse_chord_dominant_seventh():
    c = parse_chord("D:7")
    assert c.root_pc == 2
    # "X:7" means major triad + minor 7th (= dominant 7); we treat as quality="maj" with ext "7"
    assert c.quality == "maj"
    assert c.extensions == ["7"]


def test_parse_chord_inversion_bass_third():
    c = parse_chord("Eb:maj/3")
    assert c.root_pc == 3
    # /3 → bass is 4 semitones up from Eb (major third) = G (pc=7)
    assert c.bass_pc == 7
    assert c.quality == "maj"


def test_parse_chord_inversion_bass_fifth():
    c = parse_chord("F:min/5")
    assert c.root_pc == 5
    # /5 → bass is 7 semitones up from F = C (pc=0)
    assert c.bass_pc == 0


def test_parse_chord_no_chord():
    c = parse_chord("N")
    assert c.is_no_chord is True
    assert c.quality == "N"


def test_parse_chord_unknown_label_returns_unknown():
    c = parse_chord("X")
    assert c.quality == "unknown"
    assert c.root_pc is None


def test_parse_chord_letter_form_minor():
    # alt notation lv-chordia sometimes uses
    c = parse_chord("Fm")
    assert c.root_pc == 5
    assert c.quality == "min"


def test_parse_chord_letter_form_maj7():
    c = parse_chord("Cmaj7")
    assert c.root_pc == 0
    assert c.quality == "maj"
    assert "7" in c.extensions  # spec says: extension list — exact representation is implementation choice


def test_parse_chord_unparseable_returns_unknown_with_raw_label():
    c = parse_chord("???garbage???")
    assert c.quality == "unknown"
    assert c.raw_label == "???garbage???"


def test_parse_chord_diminished():
    c = parse_chord("B:dim")
    assert c.root_pc == 11
    assert c.quality == "dim"
