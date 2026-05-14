# Moved to packages/kerf-api/src/kerf_api/tools/file_ops.py
# This stub re-exports everything for backward compatibility.
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.file_ops import *  # noqa: F401, F403
from kerf_api.tools.file_ops import (  # noqa: F401
    normalize_path, split_path, resolve_path, ensure_folders,
    path_from_file_id, record_revision_for_file,
    list_files_spec, run_list_files,
    read_file_spec, run_read_file,
    write_file_spec, run_write_file,
    edit_file_spec, run_edit_file,
    create_file_spec, run_create_file,
    delete_file_spec, run_delete_file,
    search_code_spec, run_search_code,
    import_step_spec, run_import_step,
    import_kicad_spec, run_import_kicad,
)
