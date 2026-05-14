# Moved to packages/kerf-api/src/kerf_api/tools/equations.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.equations import *  # noqa: F401, F403
from kerf_api.tools.equations import (  # noqa: F401
    find_equations_file, valid_ident, record_revision_for_file,
    read_equations_spec, run_read_equations,
    set_equation_spec, run_set_equation,
)
