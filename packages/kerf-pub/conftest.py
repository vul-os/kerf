"""Package-local conftest: make ``kerf_pub`` (and sibling ``kerf_core`` for the
plugin contract) importable whether the suite is run from the repo root
(``pytest packages/``) or per-package (``pytest packages/kerf-pub``).

The repo-root conftest already inserts every ``packages/kerf-*/src`` when the
full suite runs; this mirrors that for the narrower invocation the task uses.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)

for _pkg in ("kerf-pub", "kerf-core"):
    _src = os.path.join(_PKGS, _pkg, "src")
    if os.path.isdir(_src) and _src not in sys.path:
        sys.path.insert(0, _src)
