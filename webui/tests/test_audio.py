import pytest

from webui import audio


@pytest.mark.parametrize(
    "header,size,expected",
    [
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=100-", 1000, (100, 999)),     # open-ended
        ("bytes=-100", 1000, (900, 999)),     # suffix
        ("bytes=0-9999", 100, None),          # out of bounds
        ("bytes=500-499", 1000, None),        # inverted
        ("bytes=0-0,200-300", 1000, None),    # multi-range — refuse
        ("invalid", 1000, None),
        (None, 1000, None),                   # no header → no range
        ("bytes=-100", 0, None),              # suffix on empty file → no range
        ("bytes=0-", 0, None),                # open-ended on empty file → no range
        ("bytes=" + "9" * 5000 + "-", 1000, None),  # oversized start (>4300 digits) → no crash
        ("bytes=-" + "9" * 5000, 1000, None),       # oversized suffix → no crash
    ],
)
def test_parse_range(header, size, expected):
    assert audio.parse_range(header, size) == expected
