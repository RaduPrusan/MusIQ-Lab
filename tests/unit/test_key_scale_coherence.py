import json
from pathlib import Path

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

    def test_flat_minor_spelling_rule(self):
        # PCs 1,3,6,8,10 in minor come out flat (Db/Eb/Gb/Ab/Bb).
        assert canonical_key_name(Key(tonic_pc=3, mode="minor")) == "E♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=1, mode="minor")) == "D♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=6, mode="minor")) == "G♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=8, mode="minor")) == "A♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=10, mode="minor")) == "B♭ natural minor"

    def test_major_keys_use_sharp_letter_spelling(self):
        assert canonical_key_name(Key(tonic_pc=6, mode="major")) == "F♯ major"
        assert canonical_key_name(Key(tonic_pc=3, mode="major")) == "D♯ major"

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
