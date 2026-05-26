import re

_RANGE_RE = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$")


def parse_range(header: str | None, total_size: int) -> tuple[int, int] | None:
    """Parse a Range header. Return (start, end) inclusive, or None if invalid/absent.

    Refuses multi-range requests (returns None) — we only serve single-range.
    """
    if not header:
        return None
    if "," in header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    start_s, end_s = m.group("start"), m.group("end")
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        # suffix range: bytes=-N
        suffix = int(end_s)
        if suffix == 0:
            return None
        start = max(0, total_size - suffix)
        return (start, total_size - 1)
    start = int(start_s)
    if end_s == "":
        end = total_size - 1
    else:
        end = int(end_s)
    if start > end:
        return None
    if start < 0 or end >= total_size:
        return None
    return (start, end)
