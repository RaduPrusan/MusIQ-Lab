import pytest

from analyze.derived.theory import Key, parse_key


def test_parse_key_space_form_major():
    assert parse_key("C major") == Key(tonic_pc=0, mode="major")
    assert parse_key("F major") == Key(tonic_pc=5, mode="major")


def test_parse_key_space_form_minor():
    assert parse_key("F minor") == Key(tonic_pc=5, mode="minor")
    assert parse_key("A minor") == Key(tonic_pc=9, mode="minor")


def test_parse_key_colon_form():
    assert parse_key("F:min") == Key(tonic_pc=5, mode="minor")
    assert parse_key("G:maj") == Key(tonic_pc=7, mode="major")


def test_parse_key_sharp_and_flat():
    assert parse_key("F# minor") == Key(tonic_pc=6, mode="minor")
    assert parse_key("Gb major") == Key(tonic_pc=6, mode="major")
    assert parse_key("Bb minor") == Key(tonic_pc=10, mode="minor")
    assert parse_key("A# major") == Key(tonic_pc=10, mode="major")


def test_parse_key_strips_whitespace():
    assert parse_key("  C major  ") == Key(tonic_pc=0, mode="major")


def test_parse_key_case_insensitive_mode():
    assert parse_key("C MAJOR") == Key(tonic_pc=0, mode="major")
    assert parse_key("F Minor") == Key(tonic_pc=5, mode="minor")


def test_parse_key_invalid_raises():
    with pytest.raises(ValueError):
        parse_key("nonsense")
    with pytest.raises(ValueError):
        parse_key("H major")  # H is not a valid note letter
    with pytest.raises(ValueError):
        parse_key("C dorian")  # only major/minor supported in v1
