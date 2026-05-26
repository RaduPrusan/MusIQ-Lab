import pytest

from analyze.derived.theory import Key, parse_chord, roman_for


# Helper
def r(chord_label: str, key_str: str) -> str | None:
    from analyze.derived.theory import parse_key
    return roman_for(parse_chord(chord_label), parse_key(key_str))


# === Major key diatonic ===
def test_major_diatonic():
    assert r("C:maj", "C major") == "I"
    assert r("D:min", "C major") == "ii"
    assert r("E:min", "C major") == "iii"
    assert r("F:maj", "C major") == "IV"
    assert r("G:maj", "C major") == "V"
    assert r("A:min", "C major") == "vi"
    assert r("B:dim", "C major") == "vii°"


def test_major_dominant_seventh():
    assert r("G:7", "C major") == "V7"


# === Minor key diatonic (natural minor) ===
def test_minor_diatonic_natural():
    assert r("F:min", "F minor") == "i"
    assert r("G:dim", "F minor") == "ii°"
    assert r("Ab:maj", "F minor") == "♭III"
    assert r("Bb:min", "F minor") == "iv"
    assert r("C:min", "F minor") == "v"
    assert r("Db:maj", "F minor") == "♭VI"
    assert r("Eb:maj", "F minor") == "♭VII"


def test_minor_raised_leading_tone_dominant():
    # In F minor, E:7 is the harmonic-minor V (raised leading tone).
    # Interval E - F = 11 (or -1 mod 12). We mark this as V (uppercase, dominant).
    assert r("E:7", "F minor") == "V7"


# === Modal interchange in major ===
def test_modal_interchange_in_major():
    # In C major: bIII, bVI, bVII (borrowed from parallel minor)
    assert r("Eb:maj", "C major") == "♭III"
    assert r("Ab:maj", "C major") == "♭VI"
    assert r("Bb:maj", "C major") == "♭VII"


# === Modal interchange in minor (Neapolitan, etc.) ===
def test_neapolitan_in_minor():
    # In F minor, the bII is Gb (root pc 6, F=5, interval 1) — major chord.
    assert r("Gb:maj", "F minor") == "♭II"


# === Inversions ===
def test_inversion_first_inversion_third_in_bass():
    assert r("C:maj/3", "C major") == "I/3"


def test_inversion_second_inversion_fifth_in_bass():
    assert r("C:maj/5", "C major") == "I/5"


def test_inversion_minor_chord_first_inversion():
    # F:min/3 — bass is Ab (minor third)
    assert r("F:min/3", "F minor") == "i/♭3"


# === Unparseable / no-chord ===
def test_no_chord_returns_none():
    assert r("N", "C major") is None


def test_unknown_chord_returns_none():
    assert r("???", "C major") is None
