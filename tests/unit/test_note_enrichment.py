import pytest

from analyze.derived.note_enrichment import (
    chord_intervals,
    enrich_note,
    find_chord_at,
)
from analyze.derived.theory import parse_chord, parse_key


def test_chord_intervals_major_triad():
    assert chord_intervals(parse_chord("C:maj")) == {0, 4, 7}


def test_chord_intervals_minor_triad():
    assert chord_intervals(parse_chord("F:min")) == {0, 3, 7}


def test_chord_intervals_dominant_seventh():
    assert chord_intervals(parse_chord("G:7")) == {0, 4, 7, 10}


def test_chord_intervals_no_chord_returns_empty():
    assert chord_intervals(parse_chord("N")) == set()


def test_chord_intervals_half_diminished():
    # Harte hdim7 form: A root, expect {0, 3, 6, 10}
    assert chord_intervals(parse_chord("A:hdim7")) == {0, 3, 6, 10}
    # Letter form Am7b5: same intervals — b5 must replace the perfect 5
    assert chord_intervals(parse_chord("Am7b5")) == {0, 3, 6, 10}


def test_chord_intervals_augmented_seventh():
    # quality=aug already provides 8; adding "7" extension gives b7
    assert chord_intervals(parse_chord("C:aug(7)")) == {0, 4, 8, 10}


def test_chord_intervals_maj7_sharp_5():
    # Harte form preserves maj7 vs dominant-7 distinction; #5 must replace
    # the perfect 5 → {0, 4, 8, 11} (root, M3, #5, maj7).
    # NOTE: The letter-form parser (Cmaj7#5) folds digit=7 into a plain "7"
    # ext regardless of qletter=maj, so it actually yields {0, 4, 8, 10}
    # (an augmented dominant 7th). That's a parse_chord limitation outside
    # this fix's scope; Harte form is the canonical input for this case.
    assert chord_intervals(parse_chord("C:maj7(#5)")) == {0, 4, 8, 11}


def test_chord_intervals_aug7_sharp_5_redundant():
    # quality=aug already gives 8; #5 ext is redundant but must not introduce duplicates
    # or extra intervals (set semantics handle dedup; the assertion enforces the shape)
    assert chord_intervals(parse_chord("C:aug(7,#5)")) == {0, 4, 8, 10}


def test_chord_intervals_maj_b5_replaces_fifth():
    # C:maj(b5) — b5 must replace the perfect 5, not add to it
    assert chord_intervals(parse_chord("C:maj(b5)")) == {0, 4, 6}


def test_find_chord_at_returns_active_chord():
    chords = [
        {"start": 0.0, "end": 2.0, "label": "F:min"},
        {"start": 2.0, "end": 4.0, "label": "C:min"},
        {"start": 4.0, "end": 6.0, "label": "Ab:maj"},
    ]
    assert find_chord_at(0.5, chords)["label"] == "F:min"
    assert find_chord_at(2.5, chords)["label"] == "C:min"
    assert find_chord_at(5.9, chords)["label"] == "Ab:maj"


def test_find_chord_at_returns_none_outside_range():
    chords = [{"start": 0.0, "end": 2.0, "label": "F:min"}]
    assert find_chord_at(-1.0, chords) is None
    assert find_chord_at(5.0, chords) is None


def test_enrich_note_chord_tone():
    chords = [{"start": 0.0, "end": 2.0, "label": "F:min"}]
    key = parse_key("F minor")
    # MIDI 53 = F3 (root of F:min) — chord tone
    enriched = enrich_note({"t": 0.5, "midi": 53}, prev=None, next_=None, chords=chords, key=key)
    assert enriched["in_chord"] == "F:min"
    assert enriched["role"] == "chord_tone"
    assert enriched["scale_deg"] == "1"


def test_enrich_note_passing_tone():
    chords = [{"start": 0.0, "end": 2.0, "label": "C:maj"}]
    key = parse_key("C major")
    # C maj chord tones are C, E, G (pc 0, 4, 7)
    # MIDI 60 (C4) → 62 (D4) → 64 (E4): D is passing tone between C and E
    prev = {"t": 0.1, "midi": 60}
    cur = {"t": 0.2, "midi": 62}
    next_ = {"t": 0.3, "midi": 64}
    enriched = enrich_note(cur, prev=prev, next_=next_, chords=chords, key=key)
    assert enriched["in_chord"] == "C:maj"
    assert enriched["role"] == "passing_tone"
    assert enriched["scale_deg"] == "2"


def test_enrich_note_neighbor_tone():
    chords = [{"start": 0.0, "end": 2.0, "label": "C:maj"}]
    key = parse_key("C major")
    # C → D → C: D is neighbor tone above C
    prev = {"t": 0.1, "midi": 60}
    cur = {"t": 0.2, "midi": 62}
    next_ = {"t": 0.3, "midi": 60}
    enriched = enrich_note(cur, prev=prev, next_=next_, chords=chords, key=key)
    assert enriched["role"] == "neighbor_tone"


def test_enrich_note_non_chord_tone_when_isolated():
    chords = [{"start": 0.0, "end": 2.0, "label": "C:maj"}]
    key = parse_key("C major")
    # F (pc 5) jumping in/out, not stepwise
    prev = {"t": 0.1, "midi": 60}  # C
    cur = {"t": 0.2, "midi": 65}  # F (not chord tone, not stepwise from C)
    next_ = {"t": 0.3, "midi": 60}  # back to C
    enriched = enrich_note(cur, prev=prev, next_=next_, chords=chords, key=key)
    assert enriched["role"] == "non_chord_tone"


def test_enrich_note_outside_any_chord():
    chords = [{"start": 1.0, "end": 2.0, "label": "F:min"}]
    key = parse_key("F minor")
    enriched = enrich_note({"t": 0.5, "midi": 53}, prev=None, next_=None, chords=chords, key=key)
    assert enriched["in_chord"] is None
    assert enriched["role"] is None


def test_enrich_note_in_no_chord_span():
    chords = [{"start": 0.0, "end": 2.0, "label": "N"}]
    key = parse_key("C major")
    enriched = enrich_note({"t": 1.0, "midi": 60}, prev=None, next_=None, chords=chords, key=key)
    assert enriched["in_chord"] is None
    assert enriched["role"] is None
