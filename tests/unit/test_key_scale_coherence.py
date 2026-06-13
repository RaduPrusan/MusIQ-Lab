import json
from pathlib import Path

from analyze.derived.theory import Key, parse_key


class TestParseKeyHardening:
    def test_parses_unicode_sharp(self):
        assert parse_key("F♯ major") == Key(tonic_pc=6, mode="major")

    def test_parses_unicode_flat_with_natural_word(self):
        # scale_name emits this exact form; parse_key must round-trip it.
        assert parse_key("E♭ natural minor") == Key(tonic_pc=3, mode="minor")

    def test_parses_harmonic_and_melodic_qualifiers(self):
        assert parse_key("A harmonic minor") == Key(tonic_pc=9, mode="minor")
        assert parse_key("A melodic minor") == Key(tonic_pc=9, mode="minor")

    def test_still_parses_legacy_forms(self):
        assert parse_key("D# minor") == Key(tonic_pc=3, mode="minor")
        assert parse_key("F#:major") == Key(tonic_pc=6, mode="major")
        assert parse_key("F minor") == Key(tonic_pc=5, mode="minor")
        assert parse_key("C major") == Key(tonic_pc=0, mode="major")
