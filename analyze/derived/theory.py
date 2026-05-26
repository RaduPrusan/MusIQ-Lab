"""Music-theory primitives: key parsing, chord parsing, Roman numerals,
diatonic function, scale name. All pure functions; no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Pitch class indices: C=0, C#/Db=1, D=2, D#/Eb=3, E=4, F=5,
# F#/Gb=6, G=7, G#/Ab=8, A=9, A#/Bb=10, B=11.
_NOTE_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

Mode = Literal["major", "minor"]


@dataclass(frozen=True)
class Key:
    tonic_pc: int  # 0..11
    mode: Mode


_KEY_RE = re.compile(
    r"^\s*([A-G][#b]?)\s*[:\s]?\s*(major|maj|minor|min)\s*$",
    re.IGNORECASE,
)


def parse_key(s: str) -> Key:
    m = _KEY_RE.match(s)
    if not m:
        raise ValueError(f"unparseable key: {s!r}")
    note = m.group(1).capitalize()
    # canonicalize: 'C#' stays 'C#', 'cb' → 'Cb' but only valid letters reach here
    note = note[0].upper() + note[1:].lower() if len(note) > 1 else note
    if note not in _NOTE_TO_PC:
        raise ValueError(f"unknown note letter: {note!r}")
    mode_raw = m.group(2).lower()
    mode: Mode = "major" if mode_raw.startswith("maj") else "minor"
    return Key(tonic_pc=_NOTE_TO_PC[note], mode=mode)


from typing import Optional

# Inversion bass intervals from chord root, in semitones.
# "/3" means a major third above root; "/b3" means minor third; etc.
_INVERSION_INTERVALS = {
    "1": 0,
    "b2": 1, "2": 2,
    "b3": 3, "3": 4,
    "4": 5,
    "b5": 6, "5": 7, "#5": 8,
    "b6": 8, "6": 9,
    "b7": 10, "7": 11,
}

# For minor/dim chords, the "3" (third) is a minor third (3 semitones), not major (4).
_INVERSION_INTERVALS_MINOR = {
    **_INVERSION_INTERVALS,
    "3": 3,   # minor third
    "6": 8,   # minor sixth
}

# Harte-style quality tokens we recognize.
_QUALITY_TOKENS = {
    "maj", "min", "dim", "aug", "sus2", "sus4", "maj7", "min7", "7", "dim7", "hdim7", "minmaj7",
}


@dataclass(frozen=True)
class Chord:
    root_pc: Optional[int]    # 0..11, or None for N/unknown
    bass_pc: Optional[int]    # 0..11, or None for N/unknown
    quality: str              # "maj"/"min"/"dim"/"aug"/"sus2"/"sus4"/"N"/"unknown"
    extensions: list[str]     # e.g. ["7"], ["b9", "#11"]
    raw_label: str
    is_no_chord: bool = False


# Harte-style: ROOT[:QUALITY[(EXTENSIONS)]][/BASS]
_HARTE_RE = re.compile(
    r"^\s*([A-G][#b]?)"
    r"(?::([a-zA-Z0-9]+)"
    r"(?:\(([^)]*)\))?)?"
    r"(?:/([#b]?\d+))?\s*$"
)
# Letter-form: ROOT[QUALITY_LETTER][EXTENSIONS][/BASS]
_LETTER_RE = re.compile(
    r"^\s*([A-G][#b]?)"
    r"(maj|min|m|M|dim|aug|sus[24]?)?"
    r"(\d+)?"
    r"([#b]\d+)?"
    r"(?:/([A-G][#b]?))?\s*$"
)


def _normalize_note(s: str) -> str:
    return s[0].upper() + (s[1:].lower() if len(s) > 1 else "")


def _quality_to_extensions(qtoken: str) -> tuple[str, list[str]]:
    """Split a quality+extension token like 'maj7' or 'min7' into (quality, [extensions])."""
    qtoken = qtoken.lower()
    if qtoken in {"maj", "min", "dim", "aug", "sus2", "sus4"}:
        return qtoken, []
    if qtoken == "7":
        # bare "7" = dominant 7 = major triad + b7
        return "maj", ["7"]
    if qtoken == "maj7":
        return "maj", ["maj7"]
    if qtoken in {"min7", "m7"}:
        return "min", ["7"]
    if qtoken == "dim7":
        return "dim", ["7"]
    if qtoken == "hdim7":  # half-diminished
        return "dim", ["7"]
    if qtoken == "minmaj7":
        return "min", ["maj7"]
    return qtoken, []


def parse_chord(label: str) -> Chord:
    label = label.strip()
    if label in {"N", "n"}:
        return Chord(root_pc=None, bass_pc=None, quality="N", extensions=[], raw_label=label, is_no_chord=True)
    if label in {"X", "x"}:
        return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)

    m = _HARTE_RE.match(label)
    if m:
        root = _normalize_note(m.group(1))
        if root not in _NOTE_TO_PC:
            return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)
        root_pc = _NOTE_TO_PC[root]
        qtoken = (m.group(2) or "maj").lower()
        ext_inside = m.group(3) or ""
        bass_token = m.group(4)
        quality, exts = _quality_to_extensions(qtoken)
        if ext_inside:
            exts = exts + [e.strip() for e in ext_inside.split(",") if e.strip()]
        bass_pc = root_pc
        if bass_token:
            inv_table = _INVERSION_INTERVALS_MINOR if quality in {"min", "dim"} else _INVERSION_INTERVALS
            interval = inv_table.get(bass_token)
            if interval is not None:
                bass_pc = (root_pc + interval) % 12
        return Chord(root_pc=root_pc, bass_pc=bass_pc, quality=quality, extensions=exts, raw_label=label)

    # Try letter-form (Cmaj7, Fm, F#m7b5/A)
    m = _LETTER_RE.match(label)
    if m:
        root = _normalize_note(m.group(1))
        if root not in _NOTE_TO_PC:
            return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)
        root_pc = _NOTE_TO_PC[root]
        qletter = m.group(2)
        digit = m.group(3)
        accidental = m.group(4)
        bass_letter = m.group(5)

        if qletter in {"m", "min"}:
            quality = "min"
        elif qletter in {"M", "maj"}:
            quality = "maj"
        elif qletter == "dim":
            quality = "dim"
        elif qletter == "aug":
            quality = "aug"
        elif qletter and qletter.startswith("sus"):
            quality = qletter
        else:
            quality = "maj"

        exts: list[str] = []
        if digit:
            if digit == "7" and quality == "maj":
                exts.append("7")
            elif digit == "7" and quality == "min":
                exts.append("7")
            elif digit == "7":
                exts.append("7")
            else:
                exts.append(digit)
        if accidental:
            exts.append(accidental)

        bass_pc = root_pc
        if bass_letter:
            bass_norm = _normalize_note(bass_letter)
            if bass_norm in _NOTE_TO_PC:
                bass_pc = _NOTE_TO_PC[bass_norm]

        return Chord(root_pc=root_pc, bass_pc=bass_pc, quality=quality, extensions=exts, raw_label=label)

    return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)


# Diatonic interval → Roman numeral mapping.
# Major: I ii iii IV V vi vii°  (intervals 0 2 4 5 7 9 11)
# Minor: i ii° ♭III iv v ♭VI ♭VII  (intervals 0 2 3 5 7 8 10)
# Off-diatonic intervals get ♭/♯ prefix and case from chord quality.

_MAJOR_DIATONIC = {
    0: ("I", True),   # uppercase = major-typed degree
    2: ("II", False), # lowercase if chord is minor; "ii"
    4: ("III", False),
    5: ("IV", True),
    7: ("V", True),
    9: ("VI", False),
    11: ("VII", False),
}

_MINOR_DIATONIC = {
    0: ("I", False),    # i
    2: ("II", False),   # ii°
    3: ("III", True),   # ♭III but uppercase prefix
    5: ("IV", False),   # iv
    7: ("V", False),    # v (or V if dominant — natural vs harmonic minor)
    8: ("VI", True),    # ♭VI
    10: ("VII", True),  # ♭VII
}

# In minor, off-diatonic intervals
_MINOR_OFF_DIATONIC = {
    1: "♭II",
    4: "♯III",
    6: "♯IV",
    9: "♯VI",
    11: "VII",  # raised leading tone (treated as dominant when chord is major/dom7)
}

# In major, off-diatonic intervals (borrowed from parallel minor + chromatic)
_MAJOR_OFF_DIATONIC = {
    1: "♭II",
    3: "♭III",
    6: "♯IV",
    8: "♭VI",
    10: "♭VII",
}

# Bass-interval → suffix for inversion notation.
_INVERSION_SUFFIX = {
    0: "",     # root position
    1: "/♭2",
    2: "/2",
    3: "/♭3",
    4: "/3",
    5: "/4",
    6: "/♭5",
    7: "/5",
    8: "/♯5",
    9: "/6",
    10: "/♭7",
    11: "/7",
}


def _case_for_quality(numeral_upper: str, quality: str) -> str:
    if quality == "min":
        return numeral_upper.lower()
    if quality == "dim":
        return numeral_upper.lower() + "°"
    if quality == "aug":
        return numeral_upper + "+"
    if quality in {"sus2", "sus4"}:
        return numeral_upper + quality
    # maj or unknown-but-major-ish: uppercase
    return numeral_upper


def _add_extensions(roman_str: str, extensions: list[str]) -> str:
    if not extensions:
        return roman_str
    # Single-purpose: append "7" / "maj7" / extensions verbatim
    return roman_str + "".join(extensions)


def roman_for(chord: "Chord", key: "Key") -> Optional[str]:
    if chord.is_no_chord or chord.root_pc is None or chord.quality == "unknown":
        return None

    interval = (chord.root_pc - key.tonic_pc) % 12

    # Step 1: scale-degree numeral + accidental
    if key.mode == "major":
        if interval in _MAJOR_DIATONIC:
            numeral_upper, _ = _MAJOR_DIATONIC[interval]
            base = _case_for_quality(numeral_upper, chord.quality)
        else:
            off = _MAJOR_OFF_DIATONIC[interval]
            # off has accidental prefix like "♭III"; case stays as-is for major chord, lowercase for min
            if chord.quality == "min":
                base = off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()
            elif chord.quality == "dim":
                base = (off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()) + "°"
            elif chord.quality == "aug":
                base = off + "+"
            else:
                base = off
    else:  # minor
        # Harmonic minor: raised leading tone (interval 11) with a major/dominant chord = V.
        if interval == 11 and chord.quality == "maj":
            base = "V"
        elif interval in _MINOR_DIATONIC:
            numeral_upper, has_flat_prefix = _MINOR_DIATONIC[interval]
            base = _case_for_quality(numeral_upper, chord.quality)
            if has_flat_prefix:
                base = "♭" + base
        else:
            off = _MINOR_OFF_DIATONIC[interval]
            if chord.quality == "min":
                base = off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()
            elif chord.quality == "dim":
                base = (off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()) + "°"
            elif chord.quality == "aug":
                base = off + "+"
            else:
                base = off

    # Step 2: extensions
    base = _add_extensions(base, chord.extensions)

    # Step 3: inversion suffix
    if chord.bass_pc is not None and chord.bass_pc != chord.root_pc:
        bass_interval = (chord.bass_pc - chord.root_pc) % 12
        base = base + _INVERSION_SUFFIX[bass_interval]

    return base


Function = Literal["tonic", "predominant", "dominant", "modal_interchange", "secondary"]

# Map base Roman numeral (no accidental, no extension, no inversion) → function.
# Mode-aware: i in minor is tonic, I in major is tonic; both use the same lookup.
_FUNCTION_MAP_MAJOR = {
    "I": "tonic", "i": "tonic",
    "ii": "predominant", "ii°": "predominant",
    "iii": "tonic",  # mediant — weak tonic
    "IV": "predominant", "iv": "predominant",
    "V": "dominant", "v": "dominant",
    "vi": "tonic",  # submediant — substitute tonic
    "vii°": "dominant",
}

_FUNCTION_MAP_MINOR = {
    "i": "tonic", "I": "tonic",
    "ii°": "predominant", "ii": "predominant",
    "♭III": "tonic",  # relative major in minor key — tonic-functional
    "iv": "predominant", "IV": "predominant",
    "v": "dominant", "V": "dominant",
    "♭VI": "modal_interchange",  # actually diatonic in minor; v1 calls it tonic-substitute
    "♭VII": "modal_interchange",
    "vii°": "dominant",
}


def _strip_extensions_inversion(roman: str) -> str:
    """Strip extensions and inversion to get bare numeral for function lookup."""
    # Remove inversion (everything from "/" on)
    if "/" in roman:
        roman = roman.split("/")[0]
    # Remove trailing digits + accidentals (extensions like "7", "b9")
    # but keep "°" and "+" which are part of the numeral itself
    # AND keep leading "♭"/"♯" accidental prefix
    base = re.match(r"^([♭♯]?[IiVv]+[°+]?)", roman)
    return base.group(1) if base else roman


def function_for(roman_str: str, mode: Mode) -> Optional[Function]:
    if not roman_str:
        return None
    bare = _strip_extensions_inversion(roman_str)

    # Off-diatonic accidentals → modal_interchange
    if bare.startswith("♭") or bare.startswith("♯"):
        # In minor, ♭III ♭VI ♭VII are diatonic — handle via mode map below first
        table = _FUNCTION_MAP_MINOR if mode == "minor" else _FUNCTION_MAP_MAJOR
        if bare in table:
            return table[bare]  # type: ignore[return-value]
        return "modal_interchange"

    table = _FUNCTION_MAP_MINOR if mode == "minor" else _FUNCTION_MAP_MAJOR
    if bare in table:
        return table[bare]  # type: ignore[return-value]
    return None


# ---------------------------------------------------------------------------
# Scale name + pitch-class helpers
# ---------------------------------------------------------------------------

# Canonical sharp-spelled note names per pitch class (unicode ♯ for clarity).
_PC_TO_NOTE = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]

# For scale-name display: prefer flat spelling for keys traditionally notated with flats.
_PC_TO_FLAT_NAME = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"]

# Pitch classes where flat spelling is conventional in scale names (minor keys).
_PREFER_FLAT_PCS = {1, 3, 6, 8, 10}  # Db, Eb, Gb, Ab, Bb

# Scale-degree label per chromatic interval from tonic, relative to MAJOR scale.
_INTERVAL_TO_DEGREE = {
    0: "1", 1: "♭2", 2: "2", 3: "♭3", 4: "3", 5: "4",
    6: "♯4", 7: "5", 8: "♭6", 9: "6", 10: "♭7", 11: "7",
}


def pc_to_note_name(pc: int) -> str:
    """Return the canonical sharp-spelled note name for pitch class 0..11."""
    return _PC_TO_NOTE[pc % 12]


def scale_name(key: Key) -> str:
    """Return a human-readable scale name, e.g. 'C major' or 'F natural minor'.

    For major keys, always use sharp spellings (F♯ major, not G♭ major).
    For minor keys, prefer flat spellings for conventionally flat-notated tonics
    (Bb, Eb, Ab, Db, Gb minor → B♭, E♭, A♭, D♭, G♭ natural minor).
    """
    pc = key.tonic_pc
    if key.mode == "minor" and pc in _PREFER_FLAT_PCS:
        tonic = _PC_TO_FLAT_NAME[pc]
    else:
        tonic = _PC_TO_NOTE[pc]
    if key.mode == "major":
        return f"{tonic} major"
    return f"{tonic} natural minor"


def scale_degree_for(note_pc: int, key: Key) -> str:
    """Return the scale-degree label for note_pc relative to key's tonic.

    Always relative to the major scale of the tonic, regardless of mode.
    E.g. pc=1 in any key with tonic C → '♭2'.
    """
    interval = (note_pc - key.tonic_pc) % 12
    return _INTERVAL_TO_DEGREE[interval]
