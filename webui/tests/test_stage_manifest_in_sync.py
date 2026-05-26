"""Drift gate: webui/stage_manifest.py must agree with analyze/stages/*.py.

Parses each analyze stage as Python source (via `ast.literal_eval`) rather
than importing the module, so the test runs on Windows + py3.13 + no GPU
stack installed. We only check literal top-level constants (SCHEMA_VERSION,
DEFAULT_PARAMS, CANONICAL); anything that would require a real import is
out of scope here.

When this test fails, you either:
    1) bumped SCHEMA_VERSION / changed DEFAULT_PARAMS in analyze/stages/foo.py
       → update the matching entry in webui/webui/stage_manifest.py to match
    2) added a new stage to analyze
       → add a corresponding STAGES entry in the manifest
    3) the manifest legitimately diverges (e.g. stems quality-dependent
       params we intentionally elide) → add the stage name to _OMIT_PARAMS
"""
from __future__ import annotations

import ast
from ast import literal_eval as _parse_literal  # aliased — safe literal parser
from pathlib import Path

import pytest

from webui import stage_manifest


_OMIT_PARAMS = {
    "stems",   # params include the quality-preset model list
    "drums",   # no external params (version embedded in canonical JSON)
}


def _read_literal_constants(path: Path) -> dict:
    """Return {name: literal_value} for each top-level Assign in `path`
    whose RHS is a Python literal — with a single-pass forward substitution
    for module-level Name references that were already parsed earlier in
    the file. That handles patterns like

        VOCAL_MIDI_MIN = 36
        DEFAULT_PARAMS = {"vocal_midi_min": VOCAL_MIDI_MIN, ...}

    where the dict's RHS isn't a strict literal but every Name in it
    resolves to one we already saw."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target_name = node.target.id
            value_node = node.value
        else:
            continue
        # Substitute any Name(...) nodes inside value_node that refer to
        # constants we already parsed. Walk a fresh deep copy so unrelated
        # AST nodes elsewhere don't get mutated by the rewriter.
        substituted = _substitute_names(value_node, out)
        try:
            out[target_name] = _parse_literal(substituted)
        except (ValueError, SyntaxError):
            pass
    return out


class _NameRewriter(ast.NodeTransformer):
    """Replace Name(id=k) with Constant(value=table[k]) when k ∈ table."""
    def __init__(self, table: dict) -> None:
        self.table = table

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        if node.id in self.table:
            return ast.copy_location(ast.Constant(value=self.table[node.id]), node)
        return node


def _substitute_names(node: ast.AST, table: dict) -> ast.AST:
    # ast.NodeTransformer mutates in place; copy first so we don't disturb
    # the original tree (used by other inspections in this file).
    import copy
    cloned = copy.deepcopy(node)
    return _NameRewriter(table).visit(cloned)


@pytest.fixture(scope="module")
def stages_dir() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent.parent / "analyze" / "stages"


def test_every_manifest_stage_exists_in_analyze(stages_dir):
    for entry in stage_manifest.STAGES:
        path = stages_dir / f"{entry['name']}.py"
        assert path.is_file(), (
            f"stage_manifest references {entry['name']!r} but "
            f"{path} does not exist. Was the stage renamed or removed?"
        )


def test_manifest_schema_versions_match_source(stages_dir):
    mismatches = []
    for entry in stage_manifest.STAGES:
        consts = _read_literal_constants(stages_dir / f"{entry['name']}.py")
        sv = consts.get("SCHEMA_VERSION")
        if sv is None:
            mismatches.append(f"{entry['name']}: no SCHEMA_VERSION found in source")
            continue
        if sv != entry["schema_version"]:
            mismatches.append(
                f"{entry['name']}: manifest={entry['schema_version']} "
                f"source={sv}"
            )
    assert not mismatches, (
        "stage_manifest.py is out of sync with analyze/stages/. Update entries:\n  "
        + "\n  ".join(mismatches)
    )


def test_manifest_default_params_match_source(stages_dir):
    mismatches = []
    for entry in stage_manifest.STAGES:
        if entry["name"] in _OMIT_PARAMS:
            continue
        expected = entry.get("params")
        if expected is None:
            continue
        consts = _read_literal_constants(stages_dir / f"{entry['name']}.py")
        actual = consts.get("DEFAULT_PARAMS", {})
        if actual != expected:
            added = set(actual) - set(expected)
            removed = set(expected) - set(actual)
            changed = {k: (expected[k], actual[k]) for k in set(expected) & set(actual) if expected[k] != actual[k]}
            mismatches.append(
                f"{entry['name']}: params drifted "
                f"added={sorted(added)} removed={sorted(removed)} changed={changed}"
            )
    assert not mismatches, (
        "DEFAULT_PARAMS in analyze/stages/ no longer matches stage_manifest.py:\n  "
        + "\n  ".join(mismatches)
    )


def test_manifest_canonical_files_match_source(stages_dir):
    """The CANONICAL / CANONICAL_JSON / CANONICAL_NPZ constants in source
    should appear in the manifest's canonical list. Catches a rename like
    CANONICAL = 'beat_this.json' → 'beats_v2.json' before users hit a
    phantom 'stale' state on every cache."""
    mismatches = []
    for entry in stage_manifest.STAGES:
        consts = _read_literal_constants(stages_dir / f"{entry['name']}.py")
        sources = []
        for k in ("CANONICAL", "CANONICAL_JSON", "CANONICAL_NPZ", "CANONICAL_SUMMARY"):
            if k in consts and isinstance(consts[k], str):
                sources.append(consts[k])
        for k in ("CANONICAL_DIR", "CANONICAL_SUBDIR"):
            if k in consts and isinstance(consts[k], str):
                sources.append(consts[k])
        if not sources:
            continue
        manifest_files = entry["canonical"]
        missing = [s for s in sources if s not in manifest_files]
        if missing:
            mismatches.append(
                f"{entry['name']}: source declares {sources}, "
                f"manifest canonical={manifest_files}, missing={missing}"
            )
    assert not mismatches, "manifest canonical files drifted:\n  " + "\n  ".join(mismatches)
