"""Unit tests for analyze.derived.alt_key.derive_alt_key_block."""
from __future__ import annotations

import pytest

from analyze.derived.alt_key import derive_alt_key_block


# Minimal chord shape — derive_alt_key_block only reads `label`.
def _chord(label: str) -> dict:
    return {"label": label, "start": 0.0, "end": 1.0}


def test_basic_re_derivation_under_relative_key():
    """An F:maj chord is I under F Major but V under B♭ Major.

    Both `key` and `scale` now route through canonical_key_name so they
    use the same spelling (major keys use sharps, so B♭ → "A♯ major").
    """
    chords = [_chord("F:maj")]
    block = derive_alt_key_block(chords, predominant_loop=None, alt_key_str="Bb:major")
    assert block["key"] == "A♯ major"
    assert block["scale"] == "A♯ major"
    assert block["annotations"] == [{"roman": "V", "function": "dominant"}]
    assert block["loop_roman"] is None
    assert block["modal_interchange_count"] == 0


def test_loop_roman_recomputed():
    """The predominant loop's roman numerals also re-derive under the alt key."""
    chords = [_chord("F:maj"), _chord("Bb:maj")]
    block = derive_alt_key_block(
        chords,
        predominant_loop=["F:maj", "Bb:maj", "F:maj"],
        alt_key_str="Bb:major",
    )
    assert block["loop_roman"] == ["V", "I", "V"]


def test_modal_interchange_count_recomputed():
    """Counting modal_interchange under the alt key produces a different number
    than under the canonical key.

    E♭ is ♭VII in F Major (interval 10, off-diatonic in major → modal_interchange),
    but is IV in B♭ Major (interval 5, diatonic predominant). So the same chord
    list re-counts differently under each key — exactly what the toggle needs
    to demonstrate.
    """
    chords = [_chord("Eb:maj"), _chord("F:maj")]
    block_f  = derive_alt_key_block(chords, None, "F:major")
    block_bb = derive_alt_key_block(chords, None, "Bb:major")
    assert block_f["modal_interchange_count"] == 1     # E♭ is ♭VII in F major
    assert block_bb["modal_interchange_count"] == 0   # E♭ is IV in B♭ major


def test_handles_no_chord_labels():
    """The 'N' (no-chord) sentinel parses but produces None roman/function —
    must not crash the loop or count toward modal_interchange."""
    block = derive_alt_key_block([_chord("N"), _chord("F:maj")], None, "Bb:major")
    assert block["annotations"][0] == {"roman": None, "function": None}
    assert block["annotations"][1] == {"roman": "V", "function": "dominant"}
    assert block["modal_interchange_count"] == 0


def test_accepts_pipeline_key_string_form():
    """parse_key accepts 'F Major' (pipeline form) as well as 'F:major'
    (Essentia consensus form). The pipeline emits the former, the cross-check
    consumes the latter — alt_key_block must accept either."""
    chords = [_chord("F:maj")]
    a = derive_alt_key_block(chords, None, "F Major")
    b = derive_alt_key_block(chords, None, "F:major")
    assert a["annotations"] == b["annotations"]


def test_minor_key_alt():
    """Re-deriving under a minor alt key uses the minor function map."""
    chords = [_chord("A:min"), _chord("E:maj")]
    block = derive_alt_key_block(chords, None, "A:minor")
    # A:min is i (tonic) in A minor; E:maj is V (raised-leading-tone dominant
    # via theory.roman_for harmonic-minor rule) — both diatonic functions.
    assert block["annotations"][0]["function"] == "tonic"
    assert block["annotations"][1]["function"] == "dominant"


def test_unparseable_alt_key_raises():
    with pytest.raises(ValueError):
        derive_alt_key_block([_chord("F:maj")], None, "not a key")


def test_loop_roman_handles_no_chord_in_loop():
    """A predominant loop containing 'N' should not crash; roman is None for
    that slot."""
    block = derive_alt_key_block(
        [_chord("F:maj")],
        predominant_loop=["F:maj", "N"],
        alt_key_str="Bb:major",
    )
    assert block["loop_roman"] == ["V", None]
