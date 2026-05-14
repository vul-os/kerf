# Moved to packages/kerf-api/src/kerf_api/tools/layers.py
import sys as _sys, os as _os
_pkg_src = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "packages", "kerf-api", "src",
))
if _pkg_src not in _sys.path:
    _sys.path.insert(0, _pkg_src)

from kerf_api.tools.layers import *  # noqa: F401, F403
from kerf_api.tools.layers import (  # noqa: F401
    DEFAULT_LAYER_STACK, VALID_TYPES,
    add_pcb_layer_spec, run_add_pcb_layer,
    remove_pcb_layer_spec, run_remove_pcb_layer,
    set_layer_visibility_spec, run_set_layer_visibility,
    set_layer_color_spec, run_set_layer_color,
    reorder_layers_spec, run_reorder_layers,
    assign_to_layer_spec, run_assign_to_layer,
    set_board_layer_count_spec, run_set_board_layer_count,
)
