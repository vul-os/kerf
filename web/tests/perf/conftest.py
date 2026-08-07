"""Pytest config for tests/perf: inject kerf packages onto sys.path."""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS_ROOT = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_TESTS_ROOT)
_PACKAGES_ROOT = os.path.join(_REPO_ROOT, "packages")

if os.path.isdir(_PACKAGES_ROOT):
    for entry in os.listdir(_PACKAGES_ROOT):
        if not entry.startswith("kerf-"):
            continue
        src = os.path.join(_PACKAGES_ROOT, entry, "src")
        if os.path.isdir(src) and src not in sys.path:
            sys.path.insert(0, src)

# Also add scripts/ so tests can import scripts/perf_assembly.py.
_SCRIPTS_ROOT = os.path.join(_REPO_ROOT, "scripts")
if os.path.isdir(_SCRIPTS_ROOT) and _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)
