# Moved to packages/kerf-api/src/kerf_api/tools/configurations.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.configurations import *  # noqa: F401, F403
from kerf_api.tools.configurations import (  # noqa: F401
    as_string, record_revision_for_file,
    add_configuration_spec, run_add_configuration,
    set_active_config_spec, run_set_active_config,
)
