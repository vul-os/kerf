# Moved to packages/kerf-api/src/kerf_api/tools/material.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.material import *  # noqa: F401, F403
from kerf_api.tools.material import (  # noqa: F401
    resolve_path, path_from_file_id, record_revision_for_file,
    parse_material_content, score_material,
    read_material_spec, run_read_material,
    find_material_by_name_spec, run_find_material_by_name,
    set_part_material_spec, run_set_part_material,
)
