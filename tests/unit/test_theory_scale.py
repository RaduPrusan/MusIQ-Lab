import pytest

from analyze.derived.theory import (
    parse_key,
    pc_to_note_name,
    scale_degree_for,
    scale_name,
)


def test_scale_name_major():
    assert scale_name(parse_key("C major")) == "C major"
    assert scale_name(parse_key("F# major")) == "F♯ major"


def test_scale_name_minor():
    assert scale_name(parse_key("F minor")) == "F natural minor"
    assert scale_name(parse_key("Bb minor")) == "B♭ natural minor"


def test_pc_to_note_name_naturals():
    assert pc_to_note_name(0) == "C"
    assert pc_to_note_name(5) == "F"
    assert pc_to_note_name(11) == "B"


def test_pc_to_note_name_sharps_or_flats():
    # We use sharps as canonical for unicode clarity.
    assert pc_to_note_name(1) == "C♯"
    assert pc_to_note_name(6) == "F♯"
    assert pc_to_note_name(8) == "G♯"


def test_scale_degree_for_in_C_major():
    # Note pc 0 (C) in C major = "1"; pc 7 (G) = "5"
    key = parse_key("C major")
    assert scale_degree_for(0, key) == "1"
    assert scale_degree_for(7, key) == "5"
    assert scale_degree_for(11, key) == "7"


def test_scale_degree_for_chromatic_in_C_major():
    key = parse_key("C major")
    assert scale_degree_for(1, key) == "♭2"
    assert scale_degree_for(3, key) == "♭3"
    assert scale_degree_for(6, key) == "♯4"
    assert scale_degree_for(8, key) == "♭6"
    assert scale_degree_for(10, key) == "♭7"


def test_scale_degree_uses_major_scale_relative_regardless_of_mode():
    # spec says: "Always relative to the major scale of the tonic, regardless of mode"
    minor_key = parse_key("F minor")  # tonic_pc=5
    # The note Ab (pc=8) is the "♭3" relative to F major (a minor third up)
    assert scale_degree_for(8, minor_key) == "♭3"
