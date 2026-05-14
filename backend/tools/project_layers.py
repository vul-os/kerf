# Moved to packages/kerf-api/src/kerf_api/tools/project_layers.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.project_layers import *  # noqa: F401, F403
from kerf_api.tools.project_layers import (  # noqa: F401
    _default_canvas, _next_layer_id, _HEX_RE, _load_canvas, _save_canvas,
    create_layer_spec, run_create_layer,
    delete_layer_spec, run_delete_layer,
    set_layer_visibility_spec, run_set_layer_visibility,
    set_layer_color_spec, run_set_layer_color,
    assign_to_layer_spec, run_assign_to_layer,
    switch_display_mode_spec, run_switch_display_mode,
)
