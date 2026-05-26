import json
from pathlib import Path
import pytest
from webui import user_meta


def test_read_returns_empty_when_file_missing(tmp_path):
    assert user_meta.read(tmp_path) == {}


def test_read_returns_parsed_when_present(tmp_path):
    (tmp_path / "user_meta.json").write_text('{"display_name": "X"}', encoding="utf-8")
    assert user_meta.read(tmp_path) == {"display_name": "X"}


def test_read_returns_empty_when_corrupt(tmp_path):
    (tmp_path / "user_meta.json").write_text("not json", encoding="utf-8")
    assert user_meta.read(tmp_path) == {}


def test_write_creates_file_with_indent(tmp_path):
    user_meta.write(tmp_path, {"display_name": "Charlie Puth - Attention"})
    raw = (tmp_path / "user_meta.json").read_text(encoding="utf-8")
    assert json.loads(raw) == {"display_name": "Charlie Puth - Attention"}
    assert "\n" in raw  # pretty-printed


def test_validate_display_name_strips_and_accepts():
    assert user_meta.validate_display_name("  Charlie Puth - Attention  ") == "Charlie Puth - Attention"


def test_validate_display_name_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        user_meta.validate_display_name("   ")


def test_validate_display_name_rejects_too_long():
    with pytest.raises(ValueError, match="too long"):
        user_meta.validate_display_name("x" * 201)


@pytest.mark.parametrize("ch", ["\\", "/", "\n", "\r", "\x00"])
def test_validate_display_name_rejects_path_chars(ch):
    with pytest.raises(ValueError, match="invalid character"):
        user_meta.validate_display_name(f"foo{ch}bar")


def test_validate_display_name_rejects_non_string():
    with pytest.raises(ValueError, match="must be a string"):
        user_meta.validate_display_name(42)


def test_split_artist_title_with_dash():
    assert user_meta.split_artist_title("Charlie Puth - Attention") == ("Charlie Puth", "Attention")


def test_split_artist_title_without_dash():
    assert user_meta.split_artist_title("Track 03 fragment") == ("", "Track 03 fragment")


def test_split_artist_title_partition_first_only():
    # Only the FIRST " - " is the boundary; the rest stays in the title.
    assert user_meta.split_artist_title("A - B - C") == ("A", "B - C")


def test_split_artist_title_strips_each_side():
    assert user_meta.split_artist_title("  Foo   -   Bar  ") == ("Foo", "Bar")
