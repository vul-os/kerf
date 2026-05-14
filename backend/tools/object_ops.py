# Moved to packages/kerf-api/src/kerf_api/tools/object_ops.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.object_ops import *  # noqa: F401, F403
from kerf_api.tools.object_ops import (  # noqa: F401
    resolve_path, record_revision_for_file,
    duplicate_object_spec, run_duplicate_object,
    delete_object_spec, run_delete_object,
)
