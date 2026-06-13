"""Unit tests for identify._artist_plausibility_check (Round 5, Item 1).

This gate runs on the canonical AcoustID path: when the slug-derived
artist/title diverges from the MB-identified artist/title it demotes the
match to identified=False (reason "acoustid_artist_mismatch"). It exists to
catch AcoustID-DB mislinks (the gorillaz silent-running → "DJ Allan McLoud"
case) at the cost of some false-negatives on uninformative slugs.

These tests pin the gate's branching/threshold logic. The MB normalizer and
slug parser are stubbed to keep the gate's decisions deterministic and
independent of those components' internals.
"""
from pathlib import Path

import pytest

from analyze.stages import identify

MP3 = Path("/tmp/whatever.mp3")


@pytest.fixture
def stub_deps(monkeypatch):
    # Transparent normalizer: strip only, so difflib operates on the literal
    # strings (the gate lowercases the result itself). clean_title is identity.
    monkeypatch.setattr(
        identify.musicbrainz_client, "_normalize_for_search",
        lambda s: (s or "").strip(),
    )
    monkeypatch.setattr(identify.slug_parser, "clean_title", lambda t: t)


def _stub_slug(monkeypatch, artist, title):
    monkeypatch.setattr(
        identify.slug_parser, "identify_track_from_slug",
        lambda mp3, duration_sec=None: {"artist": artist, "title": title},
    )


def test_passes_when_no_identified_artist(stub_deps):
    # Nothing to compare against → pass (cannot judge).
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist=None, identified_title="Song",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is True


def test_artist_mode_pass_on_match(stub_deps, monkeypatch):
    _stub_slug(monkeypatch, artist="Gorillaz", title="Silent Running")
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="Gorillaz", identified_title="Silent Running",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is True
    assert diag["mode"] == "artist"


def test_artist_mode_reject_on_mismatch(stub_deps, monkeypatch):
    _stub_slug(monkeypatch, artist="Gorillaz", title="Silent Running")
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="DJ Allan McLoud", identified_title="Some Mix",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is False
    assert diag["mode"] == "artist"


def test_artist_substring_rescue(stub_deps, monkeypatch):
    # slug mis-split: artist="Buddha", but the real artist "Ali Kuru" is in
    # the title portion. Direct artist sim is low, but the identified artist
    # is a substring of the full slug stem → rescue → pass.
    _stub_slug(monkeypatch, artist="Buddha", title="Bar Ali Kuru Mix")
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="Ali Kuru", identified_title="Mix",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is True
    assert diag["mode"] == "artist_substring_rescue"


def test_title_fallback_pass(stub_deps, monkeypatch):
    # No slug artist; slug title carries artist+title that matches the MB id.
    _stub_slug(monkeypatch, artist="", title="Charlie Puth Attention")
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="Charlie Puth", identified_title="Attention",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is True
    assert diag["mode"] == "title_fallback"


def test_title_fallback_reject(stub_deps, monkeypatch):
    _stub_slug(monkeypatch, artist="", title="random video hd 12345")
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="Artist", identified_title="Track",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is False
    assert diag["mode"] == "title_fallback"


def test_passes_when_slug_has_no_title(stub_deps, monkeypatch):
    # Empty slug artist AND title → nothing to compare against → pass.
    _stub_slug(monkeypatch, artist="", title="")
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="Artist", identified_title="Track",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is True


def test_fails_open_on_exception(stub_deps, monkeypatch):
    # A slug-parse hiccup must never drop an otherwise-valid identification.
    def boom(mp3, duration_sec=None):
        raise RuntimeError("slug parser exploded")
    monkeypatch.setattr(identify.slug_parser, "identify_track_from_slug", boom)
    passed, diag = identify._artist_plausibility_check(
        MP3, 200.0, identified_artist="Artist", identified_title="Track",
        min_similarity=0.5, title_fallback_threshold=0.3,
    )
    assert passed is True
