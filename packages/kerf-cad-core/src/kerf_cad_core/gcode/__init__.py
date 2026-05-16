"""
kerf_cad_core.gcode — generic G-code post-processing & toolpath utilities.

Public API (re-exported for convenience):

    from kerf_cad_core.gcode import parse_gcode, toolpath_stats, cycle_time

Distinct from:
  cncfeeds/  — cutting parameter selection (feeds & speeds)
  turning/   — lathe canned-cycle wrappers
  fiveaxis/  — 5-axis indexing utilities
  cam_layered.py — 2.5-D layer-slicing CAM

Author: imranparuk
"""

from kerf_cad_core.gcode.post import (
    parse_gcode,
    arc_to_polyline,
    toolpath_stats,
    cycle_time,
    bounding_box,
    clamp_feedrate,
    override_feedrate,
    reduce_arcs_to_lines,
    fit_lines_to_arcs,
    expand_drill_cycles,
    transform_program,
    renumber_lines,
    apply_header_footer,
    backplot_points,
)

__all__ = [
    "parse_gcode",
    "arc_to_polyline",
    "toolpath_stats",
    "cycle_time",
    "bounding_box",
    "clamp_feedrate",
    "override_feedrate",
    "reduce_arcs_to_lines",
    "fit_lines_to_arcs",
    "expand_drill_cycles",
    "transform_program",
    "renumber_lines",
    "apply_header_footer",
    "backplot_points",
]
