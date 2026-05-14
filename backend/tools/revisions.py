# Moved to packages/kerf-api/src/kerf_api/tools/revisions.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.revisions import *  # noqa: F401, F403
from kerf_api.tools.revisions import (  # noqa: F401
    resolve_path, reconstruct_revision, write_revision,
    list_revisions_spec, run_list_revisions,
    restore_revision_spec, run_restore_revision,
)
