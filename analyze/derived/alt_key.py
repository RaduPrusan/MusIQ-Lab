"""Alternative-key chord annotations for the Essentia cross-check toggle.

When Essentia's `compute_agreement` reports `key.ok == False`, the user-facing
toggle in the webui top-bar lets the user view the track *as if* the pipeline
had picked Essentia's consensus key instead. The roman numerals, chord
functions, scale name, predominant-loop roman, and modal-interchange count
all key off the tonic+mode, so re-deriving them under the alternative key is
the only way to keep the labels coherent.

This module is pure / side-effect-free — it consumes the already-enriched
chords list, the predominant loop, and the consensus key string, and returns
a self-contained "alt_key block" the summary writer can drop into
summary.chords_alt_key verbatim. The result mirrors the analyze-side fields
that depend on key (scale name, loop roman, modal-interchange count, plus a
per-chord {roman, function} array parallel to summary.chords).

Why a parallel array instead of a full chord re-emit: the chord labels,
timestamps, root/bass pitch classes, and quality are all key-independent.
Only roman + function vary. The thin annotations array keeps summary.json
small and makes the toggle on the client a pure index-map swap.
"""
from __future__ import annotations

from typing import Optional

from analyze.derived.theory import (
    canonical_key_name,
    function_for,
    parse_chord,
    parse_key,
    roman_for,
    scale_name,
)


def derive_alt_key_block(
    chords_enriched: list[dict],
    predominant_loop: Optional[list[str]],
    alt_key_str: str,
) -> dict:
    """Re-derive key-dependent annotations under an alternative key.

    Parameters
    ----------
    chords_enriched
        The canonical summary.chords array (per `_enrich_chords` in pipeline.py).
        Only the `label` field is consulted; other fields are key-independent.
    predominant_loop
        summary.analysis.predominant_chord_loop — the chord-label loop the
        chord stage identified as repeating. Can be None when no loop dominates.
    alt_key_str
        Alternative key string in any form accepted by `parse_key`, e.g.
        "Bb:major" (Essentia's consensus form) or "F Major" (pipeline form).

    Returns
    -------
    A dict shaped::

        {
            "key": "A♯ major",                   # canonical form via canonical_key_name
            "scale": "A♯ major",                  # identical spelling (canonical_key_name == scale_name)
            "annotations": [{roman, function}, ...],  # parallel to chords[]
            "loop_roman": ["V", "I", ...] or None,    # parallel to predominant_loop
            "modal_interchange_count": 12,    # recount under alt key
        }

    Raises ValueError if alt_key_str doesn't parse.
    """
    alt_key = parse_key(alt_key_str)

    annotations: list[dict] = []
    modal_count = 0
    for c in chords_enriched:
        chord = parse_chord(c["label"])
        roman = roman_for(chord, alt_key)
        function = function_for(roman, alt_key.mode) if roman else None
        annotations.append({"roman": roman, "function": function})
        if function == "modal_interchange":
            modal_count += 1

    loop_roman: Optional[list[Optional[str]]] = None
    if predominant_loop:
        loop_roman = [roman_for(parse_chord(lbl), alt_key) for lbl in predominant_loop]

    return {
        "key": canonical_key_name(alt_key),
        "scale": scale_name(alt_key),
        "annotations": annotations,
        "loop_roman": loop_roman,
        "modal_interchange_count": modal_count,
    }
