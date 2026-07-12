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
    try:
        if start_s == "":
            # suffix range: bytes=-N
            suffix = int(end_s)
            if suffix == 0 or total_size == 0:
                # zero-length suffix, or nothing to serve — malformed range.
                return None
            start = max(0, total_size - suffix)
            return (start, total_size - 1)
        start = int(start_s)
        end = total_size - 1 if end_s == "" else int(end_s)
    except ValueError:
        # Oversized numeric Range: CPython caps int(str) at 4300 digits and
        # raises ValueError. Treat as invalid; the caller maps None -> 416.
        return None
    if start > end:
        return None
    if start < 0 or end >= total_size:
        return None
    return (start, end)
