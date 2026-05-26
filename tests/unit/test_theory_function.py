from analyze.derived.theory import function_for, parse_chord, parse_key, roman_for


def f(chord_label: str, key_str: str) -> str | None:
    chord = parse_chord(chord_label)
    key = parse_key(key_str)
    rom = roman_for(chord, key)
    if rom is None:
        return None
    return function_for(rom, key.mode)


def test_function_tonic_major():
    assert f("C:maj", "C major") == "tonic"
    assert f("A:min", "C major") == "tonic"  # vi is also tonic-functional
    assert f("E:min", "C major") == "tonic"  # iii sometimes tonic


def test_function_predominant_major():
    assert f("D:min", "C major") == "predominant"  # ii
    assert f("F:maj", "C major") == "predominant"  # IV


def test_function_dominant_major():
    assert f("G:maj", "C major") == "dominant"
    assert f("G:7", "C major") == "dominant"
    assert f("B:dim", "C major") == "dominant"  # vii°


def test_function_modal_interchange_major():
    assert f("Eb:maj", "C major") == "modal_interchange"  # bIII
    assert f("Ab:maj", "C major") == "modal_interchange"  # bVI
    assert f("Bb:maj", "C major") == "modal_interchange"  # bVII


def test_function_tonic_minor():
    assert f("F:min", "F minor") == "tonic"


def test_function_predominant_minor():
    assert f("Bb:min", "F minor") == "predominant"  # iv
    assert f("G:dim", "F minor") == "predominant"  # ii°


def test_function_dominant_minor_natural_v_is_minor():
    # In natural minor, "v" (lowercase) is technically not a strong dominant.
    # We classify it as dominant anyway because that's its scale-position role.
    assert f("C:min", "F minor") == "dominant"


def test_function_dominant_minor_raised_v():
    # Harmonic-minor V — the major V chord
    assert f("E:7", "F minor") == "dominant"


def test_function_modal_interchange_minor_neapolitan():
    assert f("Gb:maj", "F minor") == "modal_interchange"  # bII / Neapolitan


def test_function_none_for_no_chord():
    assert f("N", "C major") is None
