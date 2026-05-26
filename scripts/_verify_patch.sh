#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
echo "=== AST parse ==="
.venv/bin/python -c 'import ast; ast.parse(open("analyze/pipeline.py").read()); print("OK")'
echo "=== py_compile ==="
.venv/bin/python -m py_compile analyze/pipeline.py
echo "COMPILED"
echo "=== fast unit tests (no integration) ==="
.venv/bin/python -m pytest tests/ -x -q --ignore=tests/integration 2>&1 | tail -20
