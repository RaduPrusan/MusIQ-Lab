import json
from pathlib import Path

from analyze.derived.alt_key import derive_alt_key_block
from analyze.derived.theory import Key, canonical_key_name, parse_key, scale_name
from analyze.writers.summary_writer import write_summary


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



class TestCanonicalKeyName:
    def test_roundtrips_all_pcs_and_modes(self):
        for pc in range(12):
            for mode in ("major", "minor"):
                k = Key(tonic_pc=pc, mode=mode)
                assert parse_key(canonical_key_name(k)) == k

    def test_idempotent(self):
        for pc in range(12):
            for mode in ("major", "minor"):
                k = Key(tonic_pc=pc, mode=mode)
                once = canonical_key_name(k)
                assert canonical_key_name(parse_key(once)) == once

    def test_minor_spelling_convention(self):
        # Conventional minor spelling by circle-of-fifths (fewer accidentals;
        # the lone pc3 tie resolves to flat). Sharp: C#(1), F#(6), G#(8);
        # flat: Eb(3, tie), Bb(10).
        assert canonical_key_name(Key(tonic_pc=1, mode="minor")) == "C♯ natural minor"
        assert canonical_key_name(Key(tonic_pc=3, mode="minor")) == "E♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=6, mode="minor")) == "F♯ natural minor"
        assert canonical_key_name(Key(tonic_pc=8, mode="minor")) == "G♯ natural minor"
        assert canonical_key_name(Key(tonic_pc=10, mode="minor")) == "B♭ natural minor"

    def test_major_spelling_convention(self):
        # Conventional major spelling by circle-of-fifths (fewer accidentals;
        # the lone pc6 tie resolves to sharp). Flat: Db(1), Eb(3), Ab(8),
        # Bb(10); sharp: F#(6, tie).
        assert canonical_key_name(Key(tonic_pc=1, mode="major")) == "D♭ major"
        assert canonical_key_name(Key(tonic_pc=3, mode="major")) == "E♭ major"
        assert canonical_key_name(Key(tonic_pc=6, mode="major")) == "F♯ major"
        assert canonical_key_name(Key(tonic_pc=8, mode="major")) == "A♭ major"
        assert canonical_key_name(Key(tonic_pc=10, mode="major")) == "B♭ major"

    def test_natural_tonics_carry_no_accidental(self):
        for pc, name in [(0, "C"), (2, "D"), (4, "E"), (5, "F"), (7, "G"), (9, "A"), (11, "B")]:
            assert canonical_key_name(Key(tonic_pc=pc, mode="major")) == f"{name} major"
            assert canonical_key_name(Key(tonic_pc=pc, mode="minor")) == f"{name} natural minor"

    def test_byte_identical_to_scale_name(self):
        # track.key must equal analysis.scale, so the two functions agree.
        for pc in range(12):
            for mode in ("major", "minor"):
                k = Key(tonic_pc=pc, mode=mode)
                assert canonical_key_name(k) == scale_name(k)


class TestWriterBoundaryCoherence:
    def _minimal_results(self, raw_key: str) -> dict:
        return {
            "beats": {"bpm": 120.0, "downbeats": [0.5, 2.5], "time_signature": "4/4"},
            "key": {"key": raw_key, "confidence": 1.0},
            "chords": [],
        }

    def test_track_key_matches_analysis_scale(self, tmp_path):
        # Raw skey output is sharp ("D# minor"); analysis.scale is flat.
        out = tmp_path / "song.summary.json"
        mp3 = tmp_path / "song.mp3"
        mp3.write_bytes(b"")
        results = self._minimal_results("D# minor")
        derived = {"scale": scale_name(parse_key("D# minor"))}
        write_summary(out, mp3, results, derived, warnings=[], duration_sec=200.0)

        data = json.loads(out.read_text())
        track_key = data["track"]["key"]
        scale = data["analysis"]["scale"]
        # Same Key object…
        assert parse_key(track_key) == parse_key(scale)
        # …and same tonic letter spelling (the actual bug).
        assert track_key.split()[0] == scale.split()[0] == "E♭"


class TestAltKeyCoherence:
    def test_alt_block_key_matches_scale(self):
        # Essentia consensus arrives in colon form ("F#:major").
        block = derive_alt_key_block(
            chords_enriched=[{"label": "F#:maj"}],
            predominant_loop=None,
            alt_key_str="F#:major",
        )
        assert parse_key(block["key"]) == parse_key(block["scale"])
        assert block["key"].split()[0] == block["scale"].split()[0] == "F♯"

    def test_alt_block_flat_minor_consensus(self):
        block = derive_alt_key_block(
            chords_enriched=[],
            predominant_loop=None,
            alt_key_str="Eb:minor",
        )
        assert block["key"] == block["scale"] == "E♭ natural minor"
