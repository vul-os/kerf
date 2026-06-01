"""
kerf_cam.face_mill_path — zig-zag face-milling toolpath for rectangular pockets.

Reference standards
-------------------
* Machinery's Handbook 31e §1136 — Face milling:
  - Recommended stepover (radial engagement): 60–80 % of cutter diameter for
    face milling; 70 % is the common balanced choice between MRR and chip load.
  - Climb milling (cutter rotation assists feed direction): superior surface
    finish and insert life vs. conventional; preferred on rigid machines.
  - Starting position: tool centre placed inside the pocket at tool_radius
    distance from the boundary to avoid air cuts at the first pass.

* NIST RS-274/NGC §3.5 — Data input format and modal state:
  G00  rapid positioning
  G01  linear feed move
  G21  metric mode (mm)
  G90  absolute distance mode
  G94  feed per minute mode
  M03  spindle on (CW)
  M05  spindle off
  M30  program end

Zig-zag strategy
----------------
The tool makes parallel passes in the X direction, stepping in Y by
(tool_diameter × stepover_pct / 100) between each pass.

  Pass 0 (leftward or rightward depending on climb setting):
      Start at (x_start, y_current), end at (x_end, y_current)
  Pass 1 (reversed):
      Start at (x_end, y_current), end at (x_start, y_current)
  …and so on.

Boundary conditions
-------------------
  x_start = xmin + tool_radius   (first fully-inside cut)
  x_end   = xmax - tool_radius   (last fully-inside cut)
  y_start = ymin + tool_radius
  y_end   = ymax - tool_radius

  Number of passes = ceil((y_end - y_start) / stepover) + 1
  (last pass MAY be a partial stepover to ensure the top boundary is covered)

Climb vs conventional
---------------------
For climb milling (climb_milling=True):
  - Even-numbered passes go in the +X direction (left → right).
  - Odd-numbered passes go in the −X direction (right → left).
  For conventional milling the directions are inverted.
  (Reference: MH 31e §1136 climb-milling definition; feed direction
   relative to rotation determines whether the chip starts thin or thick.)

Roughing + finishing strategy
------------------------------
When total_depth_mm, stepdown_mm, and stock_allowance_mm are supplied:
  - Roughing: ceil(total_depth_mm / stepdown_mm) Z layers, each at
    roughing_feedrate_mm_per_min.  The last roughing layer stops at
    Z = work_top_z_mm − (total_depth_mm − stock_allowance_mm) leaving a
    thin layer of stock on the floor.
  - Finishing: a single zig-zag pass at Z = work_top_z_mm − total_depth_mm
    (floor) at finishing_feedrate_mm_per_min with light stepover for
    surface quality.  Complies with MH 31e §1136 roughing/finishing
    sequence: rough to within 0.1–0.5 mm, then finish to final dimension.

Honest caveats
--------------
- 2.5D only — no helical entry, no ramping.
- No cutter compensation (G41/G42) — path offsets are computed in software.
- Time estimate: constant feed rate, no acceleration ramps (add 5–15 % for
  real machine dynamics per MH 31e §1109).
- Face-roughing multi-layer (Z-axis stepdown) toolpath is now implemented
  via FaceMillPathSpec.  High-feed (HFC) insert strategies, wiper-edge edge
  passes, and trochoidal face-roughing remain outside scope.
- Tool nose radius compensation not applied.
- No corner arcs — the zig-zag reversal is a feed-rate point reversal, which
  may cause a momentary dwell; use G00 + G01 repositioning if the controller
  does not support direction reversal within G01.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FaceMillSpec:
    """Specification for a zig-zag face-milling operation on a rectangular pocket.

    All distance parameters are in millimetres (assumes G21 metric mode).
    Feed is in mm/min; RPM is spindle speed; rapid is in mm/min.

    Parameters
    ----------
    xmin_mm, ymin_mm, xmax_mm, ymax_mm
        Pocket bounding box corners in the work coordinate system (WCS).
    depth_mm
        Axial depth of cut (positive value; tool moves in −Z direction).
    tool_diameter_mm
        Nominal cutter diameter in mm.  Must be > 0 and ≤ pocket width/height.
    stepover_pct
        Radial engagement as a percentage of tool diameter (default 70 %).
        MH 31e §1136: 60–80 % typical for face milling.
    feed_mm_per_min
        Feed rate during cutting passes (mm/min).
    spindle_rpm
        Spindle speed (RPM).  Used for M03 S-word and MRR commentary only.
    rapid_z_mm
        Rapid traverse rate in Z (mm/min) — used for time estimation only.
        Typical VMC: 10 000–30 000 mm/min.
    work_top_z_mm
        Absolute Z of the work surface (default 0.0).
        The cutting pass runs at Z = work_top_z_mm − depth_mm.
    """
    xmin_mm: float
    ymin_mm: float
    xmax_mm: float
    ymax_mm: float
    depth_mm: float
    tool_diameter_mm: float
    stepover_pct: float = 70.0
    feed_mm_per_min: float = 1000.0
    spindle_rpm: float = 3000.0
    rapid_z_mm: float = 10000.0
    work_top_z_mm: float = 0.0

    # rapid clearance plane above work_top_z_mm (mm above work surface for rapid moves)
    rapid_clearance_mm: float = 5.0

    def __post_init__(self):
        if self.xmax_mm <= self.xmin_mm:
            raise ValueError(
                f"xmax_mm ({self.xmax_mm}) must be > xmin_mm ({self.xmin_mm})"
            )
        if self.ymax_mm <= self.ymin_mm:
            raise ValueError(
                f"ymax_mm ({self.ymax_mm}) must be > ymin_mm ({self.ymin_mm})"
            )
        if self.depth_mm <= 0:
            raise ValueError(f"depth_mm must be > 0, got {self.depth_mm!r}")
        if self.tool_diameter_mm <= 0:
            raise ValueError(
                f"tool_diameter_mm must be > 0, got {self.tool_diameter_mm!r}"
            )
        pocket_width = self.xmax_mm - self.xmin_mm
        pocket_height = self.ymax_mm - self.ymin_mm
        if self.tool_diameter_mm > pocket_width:
            raise ValueError(
                f"tool_diameter_mm ({self.tool_diameter_mm} mm) exceeds pocket width "
                f"({pocket_width:.4f} mm) — tool cannot fit inside pocket"
            )
        if self.tool_diameter_mm > pocket_height:
            raise ValueError(
                f"tool_diameter_mm ({self.tool_diameter_mm} mm) exceeds pocket height "
                f"({pocket_height:.4f} mm) — tool cannot fit inside pocket"
            )
        if not (1.0 <= self.stepover_pct <= 100.0):
            raise ValueError(
                f"stepover_pct must be between 1 and 100, got {self.stepover_pct!r}"
            )
        if self.feed_mm_per_min <= 0:
            raise ValueError(
                f"feed_mm_per_min must be > 0, got {self.feed_mm_per_min!r}"
            )
        if self.spindle_rpm <= 0:
            raise ValueError(
                f"spindle_rpm must be > 0, got {self.spindle_rpm!r}"
            )
        if self.rapid_z_mm <= 0:
            raise ValueError(
                f"rapid_z_mm must be > 0, got {self.rapid_z_mm!r}"
            )


@dataclass
class FaceMillPathSpec:
    """Specification for a multi-layer roughing + finishing face-mill operation.

    Extends the single-depth FaceMillSpec concept with Z-axis stepdown layers
    so that a rough cut removes the bulk of material (leaving a stock allowance
    on the floor), followed by a single finishing pass to the final depth.

    References
    ----------
    * MH 31e §1136 — recommends rough to within 0.1–0.5 mm stock, then finish.
    * NIST RS-274/NGC §3.5 — G-code modal state (G21/G90/G94/M03/M05/M30).

    Parameters
    ----------
    xmin_mm, ymin_mm, xmax_mm, ymax_mm
        Pocket bounding box (WCS, mm).
    total_depth_mm
        Final floor depth below work_top_z_mm (positive, mm).
    tool_diameter_mm
        Nominal cutter diameter (mm).
    stepdown_mm
        Maximum axial depth of cut per roughing layer (mm, positive).
        MH 31e §1136: typically 0.5–3 mm for face mills depending on material.
    stock_allowance_mm
        Floor stock left after roughing, removed by the finish pass (mm).
        Typical: 0.1–0.5 mm per MH 31e §1136.  Must be < total_depth_mm.
    roughing_feedrate_mm_per_min
        Feed rate for roughing layers (mm/min).  Usually 20–40 % higher than
        finishing for higher MRR per Sandvik CoroKey §2.
    finishing_feedrate_mm_per_min
        Feed rate for finishing pass (mm/min).  Slower for surface quality.
    stepover_pct
        Radial engagement as % of tool diameter (default 70 %).
    finishing_stepover_pct
        Stepover for the finishing pass (default 50 %).  Lighter radial
        engagement improves surface finish per MH 31e §1136.
    spindle_rpm
        Spindle speed (RPM).
    rapid_z_mm
        Rapid Z traverse rate (mm/min, used for time estimation).
    work_top_z_mm
        Absolute Z of the work surface (default 0.0).
    rapid_clearance_mm
        Clearance above work_top_z_mm for rapid moves (mm, default 5.0).
    """
    xmin_mm: float
    ymin_mm: float
    xmax_mm: float
    ymax_mm: float
    total_depth_mm: float
    tool_diameter_mm: float
    stepdown_mm: float
    stock_allowance_mm: float = 0.2
    roughing_feedrate_mm_per_min: float = 1500.0
    finishing_feedrate_mm_per_min: float = 800.0
    stepover_pct: float = 70.0
    finishing_stepover_pct: float = 50.0
    spindle_rpm: float = 3000.0
    rapid_z_mm: float = 10000.0
    work_top_z_mm: float = 0.0
    rapid_clearance_mm: float = 5.0

    def __post_init__(self):
        if self.xmax_mm <= self.xmin_mm:
            raise ValueError(
                f"xmax_mm ({self.xmax_mm}) must be > xmin_mm ({self.xmin_mm})"
            )
        if self.ymax_mm <= self.ymin_mm:
            raise ValueError(
                f"ymax_mm ({self.ymax_mm}) must be > ymin_mm ({self.ymin_mm})"
            )
        if self.total_depth_mm <= 0:
            raise ValueError(f"total_depth_mm must be > 0, got {self.total_depth_mm!r}")
        if self.tool_diameter_mm <= 0:
            raise ValueError(
                f"tool_diameter_mm must be > 0, got {self.tool_diameter_mm!r}"
            )
        pocket_width = self.xmax_mm - self.xmin_mm
        pocket_height = self.ymax_mm - self.ymin_mm
        if self.tool_diameter_mm > pocket_width:
            raise ValueError(
                f"tool_diameter_mm ({self.tool_diameter_mm} mm) exceeds pocket width "
                f"({pocket_width:.4f} mm) — tool cannot fit inside pocket"
            )
        if self.tool_diameter_mm > pocket_height:
            raise ValueError(
                f"tool_diameter_mm ({self.tool_diameter_mm} mm) exceeds pocket height "
                f"({pocket_height:.4f} mm) — tool cannot fit inside pocket"
            )
        if self.stepdown_mm <= 0:
            raise ValueError(f"stepdown_mm must be > 0, got {self.stepdown_mm!r}")
        if self.stock_allowance_mm < 0:
            raise ValueError(
                f"stock_allowance_mm must be >= 0, got {self.stock_allowance_mm!r}"
            )
        if self.stock_allowance_mm >= self.total_depth_mm:
            raise ValueError(
                f"stock_allowance_mm ({self.stock_allowance_mm}) must be < "
                f"total_depth_mm ({self.total_depth_mm})"
            )
        if not (1.0 <= self.stepover_pct <= 100.0):
            raise ValueError(
                f"stepover_pct must be between 1 and 100, got {self.stepover_pct!r}"
            )
        if not (1.0 <= self.finishing_stepover_pct <= 100.0):
            raise ValueError(
                f"finishing_stepover_pct must be between 1 and 100, "
                f"got {self.finishing_stepover_pct!r}"
            )
        if self.roughing_feedrate_mm_per_min <= 0:
            raise ValueError(
                f"roughing_feedrate_mm_per_min must be > 0, "
                f"got {self.roughing_feedrate_mm_per_min!r}"
            )
        if self.finishing_feedrate_mm_per_min <= 0:
            raise ValueError(
                f"finishing_feedrate_mm_per_min must be > 0, "
                f"got {self.finishing_feedrate_mm_per_min!r}"
            )
        if self.spindle_rpm <= 0:
            raise ValueError(
                f"spindle_rpm must be > 0, got {self.spindle_rpm!r}"
            )
        if self.rapid_z_mm <= 0:
            raise ValueError(
                f"rapid_z_mm must be > 0, got {self.rapid_z_mm!r}"
            )


@dataclass
class FaceMillResult:
    """Result from ``generate_face_mill_path``.

    Attributes
    ----------
    gcode
        Complete G-code program (UTF-8 text, NIST RS-274/NGC §3.5).
    num_passes
        Number of cutting passes in the zig-zag pattern.
    total_path_length_mm
        Total cutting path length in the XY plane (mm).
    material_removal_mm3
        Volume of material removed = pocket_area × depth_mm (mm³).
        Assumes full floor coverage to the pocket boundary.
    machining_time_s
        Estimated cutting time in seconds (constant feed only — see honest_caveat).
    honest_caveat
        Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_passes: int
    total_path_length_mm: float
    material_removal_mm3: float
    machining_time_s: float
    honest_caveat: str


@dataclass
class FaceMillRoughFinishResult:
    """Result from ``generate_face_mill_rough_finish_path``.

    Attributes
    ----------
    gcode
        Complete G-code program including all roughing layers + finishing pass.
    num_roughing_layers
        Number of Z-axis roughing layers generated.
    num_passes_per_layer
        Number of XY zig-zag passes per roughing layer.
    num_finishing_passes
        Number of XY passes in the finishing layer.
    total_path_length_mm
        Total XY cutting path length across all layers (mm).
    material_removal_mm3
        Volume of material removed = pocket_area × total_depth_mm (mm³).
    machining_time_s
        Estimated total cutting time in seconds (constant feeds, no ramp).
    roughing_z_levels
        List of absolute Z depths cut during roughing (one per layer).
    finishing_z
        Absolute Z of the finishing pass floor.
    honest_caveat
        Plain-English note on assumptions and limitations.
    """
    gcode: str
    num_roughing_layers: int
    num_passes_per_layer: int
    num_finishing_passes: int
    total_path_length_mm: float
    material_removal_mm3: float
    machining_time_s: float
    roughing_z_levels: list
    finishing_z: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation.

    RS-274/NGC §3.5.1: numbers may be integers or reals; no trailing zeros
    required but decimal point must be present for reals.  We use 4 decimal
    places (1 μm resolution).

    >>> _fmt(10.0)
    '10.0'
    >>> _fmt(-5.5)
    '-5.5'
    >>> _fmt(0.0)
    '0.0'
    """
    formatted = f"{v:.{decimals}f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
        if '.' not in formatted:
            formatted = formatted + '.0'
    return formatted


def _compute_passes(spec: FaceMillSpec) -> list:
    """Return a list of Y centre coordinates for each cutting pass.

    Boundary logic (MH 31e §1136):
      y_start = ymin + tool_radius  (first pass, tool centre just inside south wall)
      y_end   = ymax - tool_radius  (last pass,  tool centre just inside north wall)
      stepover = tool_diameter × stepover_pct / 100

    The last pass is always positioned at y_end regardless of whether the
    stepover divides evenly — this guarantees full coverage at the north wall.

    Returns
    -------
    list[float]
        Y positions for each pass (at least 1).
    """
    tool_radius = spec.tool_diameter_mm / 2.0
    stepover = spec.tool_diameter_mm * spec.stepover_pct / 100.0

    y_start = spec.ymin_mm + tool_radius
    y_end = spec.ymax_mm - tool_radius

    if y_end <= y_start:
        # Pocket height == tool_diameter → single pass down the middle
        return [(y_start + y_end) / 2.0]

    span = y_end - y_start
    n = math.ceil(span / stepover)  # number of steps between first and last
    passes = []
    for i in range(n):
        y = y_start + i * stepover
        passes.append(y)
    # Always include final boundary pass
    if abs(passes[-1] - y_end) > 1e-9:
        passes.append(y_end)
    return passes


def _compute_passes_from_bounds(
    xmin_mm: float, ymin_mm: float, xmax_mm: float, ymax_mm: float,
    tool_diameter_mm: float, stepover_pct: float,
) -> list:
    """Return Y centre coordinates for zig-zag passes over a rectangular pocket.

    Used internally by generate_face_mill_rough_finish_path so it can compute
    passes for both roughing and finishing stepover values without constructing
    a full FaceMillSpec.

    Returns
    -------
    list[float]
        Y positions for each pass (at least 1).
    """
    tool_radius = tool_diameter_mm / 2.0
    stepover = tool_diameter_mm * stepover_pct / 100.0

    y_start = ymin_mm + tool_radius
    y_end = ymax_mm - tool_radius

    if y_end <= y_start:
        return [(y_start + y_end) / 2.0]

    span = y_end - y_start
    n = math.ceil(span / stepover)
    passes = []
    for i in range(n):
        y = y_start + i * stepover
        passes.append(y)
    if abs(passes[-1] - y_end) > 1e-9:
        passes.append(y_end)
    return passes


def _emit_layer_passes(
    lines: list,
    y_positions: list,
    x_start: float,
    x_end: float,
    z_cut: float,
    z_rapid: float,
    feedrate: float,
    climb_milling: bool,
    layer_label: str,
) -> float:
    """Append G-code lines for a single Z layer of zig-zag passes.

    Repositions between passes with G00 retract/plunge to avoid drag marks.

    Parameters
    ----------
    lines
        In-place list of G-code strings to append to.
    y_positions
        List of Y positions for each pass in this layer.
    x_start, x_end
        X extents of the tool-centre path.
    z_cut
        Absolute Z of the cutting depth for this layer.
    z_rapid
        Absolute Z of the rapid clearance plane.
    feedrate
        Feed rate for this layer (mm/min).
    climb_milling
        Direction convention (True = climb, pass 0 in +X).
    layer_label
        Comment prefix shown in the G-code (e.g. "Roughing layer 1/5").

    Returns
    -------
    float
        Total XY path length cut in this layer (mm).
    """
    num_passes = len(y_positions)
    total_length = 0.0

    # Rapid to entry point for first pass in this layer
    pass0_x_entry = x_start if climb_milling else x_end
    lines.append(f"G00 Z{_fmt(z_rapid)}  (retract — {layer_label})")
    lines.append(f"G00 X{_fmt(pass0_x_entry)} Y{_fmt(y_positions[0])}  (entry — {layer_label})")
    lines.append(f"G01 Z{_fmt(z_cut)} F{_fmt(feedrate)}  (plunge to {_fmt(z_cut)} mm)")
    lines.append("")

    for i, y in enumerate(y_positions):
        if climb_milling:
            go_positive_x = (i % 2 == 0)
        else:
            go_positive_x = (i % 2 == 1)

        if go_positive_x:
            x_from = x_start
            x_to = x_end
        else:
            x_from = x_end
            x_to = x_start

        pass_length = abs(x_to - x_from)
        total_length += pass_length

        direction_label = "+X" if go_positive_x else "-X"
        lines.append(
            f"({layer_label} — pass {i + 1}/{num_passes}: "
            f"Y={_fmt(y)}  {direction_label}  len={_fmt(pass_length)} mm)"
        )

        if i == 0:
            lines.append(f"G01 X{_fmt(x_to)} Y{_fmt(y)} F{_fmt(feedrate)}")
        else:
            lines.append(f"G00 Z{_fmt(z_rapid)}  (retract between passes)")
            lines.append(f"G00 X{_fmt(x_from)} Y{_fmt(y)}  (reposition to pass {i + 1} entry)")
            lines.append(f"G01 Z{_fmt(z_cut)} F{_fmt(feedrate)}  (plunge to cut depth)")
            lines.append(f"G01 X{_fmt(x_to)} Y{_fmt(y)} F{_fmt(feedrate)}")

        lines.append("")

    return total_length


# ---------------------------------------------------------------------------
# Main generators
# ---------------------------------------------------------------------------

def generate_face_mill_path(
    spec: FaceMillSpec,
    climb_milling: bool = True,
) -> FaceMillResult:
    """Generate a zig-zag face-milling G-code toolpath.

    The toolpath follows NIST RS-274/NGC §3.5 (G21/G90/G94 modal setup) and
    Machinery's Handbook 31e §1136 face-milling recommendations.

    Parameters
    ----------
    spec
        FaceMillSpec instance defining the pocket geometry and cutting conditions.
    climb_milling
        If True (default): pass 0 travels in the +X direction (climb milling
        per MH 31e §1136).  If False: pass 0 travels in the −X direction
        (conventional milling).

    Returns
    -------
    FaceMillResult

    Raises
    ------
    ValueError
        If spec parameters are invalid (see FaceMillSpec.__post_init__).
    """
    tool_radius = spec.tool_diameter_mm / 2.0

    # XY extents of tool centre path (inside pocket by one tool radius)
    x_start = spec.xmin_mm + tool_radius
    x_end = spec.xmax_mm - tool_radius

    # Y positions for each pass
    y_positions = _compute_passes(spec)
    num_passes = len(y_positions)

    # Absolute Z values
    z_cut = spec.work_top_z_mm - spec.depth_mm      # cutting depth
    z_rapid = spec.work_top_z_mm + spec.rapid_clearance_mm  # rapid clearance plane

    # ── Build G-code ──────────────────────────────────────────────────────────
    lines = []
    lines.append("%")
    lines.append("(Face-mill zig-zag — Kerf CAM / MH 31e §1136 + NIST RS-274/NGC §3.5)")
    lines.append("(Generated by: kerf_cam.face_mill_path.generate_face_mill_path)")
    lines.append(f"(Pocket: X{_fmt(spec.xmin_mm)}..{_fmt(spec.xmax_mm)}"
                 f"  Y{_fmt(spec.ymin_mm)}..{_fmt(spec.ymax_mm)}"
                 f"  depth={_fmt(spec.depth_mm)} mm)")
    lines.append(f"(Tool: D={_fmt(spec.tool_diameter_mm)} mm"
                 f"  stepover={_fmt(spec.stepover_pct)} %"
                 f"  passes={num_passes})")
    lines.append(f"(Milling mode: {'climb' if climb_milling else 'conventional'})")
    lines.append("(WARNING: 2.5D only — no helical entry; no cutter comp G41/G42)")
    lines.append("(WARNING: time estimate excludes acceleration ramps)")
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")

    # Spindle on
    lines.append(f"M03 S{int(spec.spindle_rpm)}  (spindle on CW)")
    lines.append("")

    # Rapid to clearance plane above first pass entry
    pass0_y = y_positions[0]
    pass0_x_entry = x_start if climb_milling else x_end
    lines.append(f"G00 Z{_fmt(z_rapid)}  (rapid to clearance plane)")
    lines.append(f"G00 X{_fmt(pass0_x_entry)} Y{_fmt(pass0_y)}  (rapid to first pass entry)")
    lines.append(f"G00 Z{_fmt(spec.work_top_z_mm)}  (rapid to work surface)")
    lines.append(f"G01 Z{_fmt(z_cut)} F{_fmt(spec.feed_mm_per_min)}  (plunge to cut depth)")
    lines.append("")

    total_path_length = 0.0

    for i, y in enumerate(y_positions):
        # Determine direction for this pass
        # climb_milling=True:  even passes +X, odd passes -X
        # climb_milling=False: even passes -X, odd passes +X
        if climb_milling:
            go_positive_x = (i % 2 == 0)
        else:
            go_positive_x = (i % 2 == 1)

        if go_positive_x:
            x_from = x_start
            x_to = x_end
        else:
            x_from = x_end
            x_to = x_start

        pass_length = abs(x_to - x_from)
        total_path_length += pass_length

        direction_label = "+X" if go_positive_x else "-X"
        lines.append(
            f"(Pass {i + 1}/{num_passes}: Y={_fmt(y)}  {direction_label}"
            f"  len={_fmt(pass_length)} mm)"
        )

        if i == 0:
            # Already positioned at (x_from, y, z_cut) from preamble
            lines.append(f"G01 X{_fmt(x_to)} Y{_fmt(y)} F{_fmt(spec.feed_mm_per_min)}")
        else:
            prev_y = y_positions[i - 1]

            # Rapid clear, reposition XY, plunge (or step over in XY at cut depth)
            # Strategy: retract to clearance, rapid to entry, plunge.
            # This avoids dragging the cutter over stock during the stepover arc.
            # (MH 31e §1136: clear-and-reposition preferred over zigzag drag on
            #  non-zero-helix face mills at full DOC.)
            lines.append(f"G00 Z{_fmt(z_rapid)}  (retract between passes)")
            lines.append(f"G00 X{_fmt(x_from)} Y{_fmt(y)}  (reposition to pass {i + 1} entry)")
            lines.append(f"G01 Z{_fmt(z_cut)} F{_fmt(spec.feed_mm_per_min)}  (plunge to cut depth)")
            lines.append(f"G01 X{_fmt(x_to)} Y{_fmt(y)} F{_fmt(spec.feed_mm_per_min)}")

        lines.append("")

    # Retract and end
    lines.append(f"G00 Z{_fmt(z_rapid)}  (retract to clearance plane)")
    lines.append("M05  (spindle off)")
    lines.append("M30  (program end)")
    lines.append("%")

    gcode = "\n".join(lines)

    # ── Metrics ───────────────────────────────────────────────────────────────
    pocket_area_mm2 = (spec.xmax_mm - spec.xmin_mm) * (spec.ymax_mm - spec.ymin_mm)
    material_removal_mm3 = pocket_area_mm2 * spec.depth_mm

    # Machining time: cutting passes only (constant feed, no accel ramps)
    cutting_time_s = (total_path_length / spec.feed_mm_per_min) * 60.0
    # Add Z plunge time per pass (feed plunge at feed rate from work_top to z_cut)
    plunge_depth = spec.depth_mm
    plunge_time_per_pass_s = (plunge_depth / spec.feed_mm_per_min) * 60.0
    # Add rapid Z times (retract + descend between passes): num_passes - 1 retract cycles
    rapid_z_distance_per_cycle = spec.rapid_clearance_mm + plunge_depth  # up + down
    rapid_time_per_cycle_s = (rapid_z_distance_per_cycle / spec.rapid_z_mm) * 60.0
    repositions = num_passes - 1
    total_time_s = (
        cutting_time_s
        + num_passes * plunge_time_per_pass_s
        + repositions * rapid_time_per_cycle_s
    )

    honest_caveat = (
        "2.5D zig-zag face mill only — features NOT implemented: "
        "(1) helical ramping entry (no gradual Z ramp; tool plunges at feed rate); "
        "(2) cutter compensation G41/G42 (path offsets are pre-computed); "
        "(3) high-feed (HFC) insert strategies; "
        "(4) wiper-edge finish pass; "
        "(5) corner arcs at pass reversal (momentary dwell possible at reversal point). "
        "Time estimate uses constant feed rate — actual cycle time will be 5–15 % longer "
        "due to acceleration ramps (Altintas 2012 §5.7; MH 31e §1109). "
        "MRR = pocket_area × depth (assumes 100 % floor coverage). "
        "Refs: MH 31e §1136 (face milling); NIST RS-274/NGC §3.5 (G-code data format)."
    )

    return FaceMillResult(
        gcode=gcode,
        num_passes=num_passes,
        total_path_length_mm=round(total_path_length, 6),
        material_removal_mm3=round(material_removal_mm3, 6),
        machining_time_s=round(total_time_s, 3),
        honest_caveat=honest_caveat,
    )


def generate_face_mill_rough_finish_path(
    spec: FaceMillPathSpec,
    climb_milling: bool = True,
) -> FaceMillRoughFinishResult:
    """Generate a multi-layer roughing + single finishing face-mill toolpath.

    Algorithm (MH 31e §1136 roughing/finishing sequence):

    1. Roughing layers:
       - roughing_depth = total_depth_mm − stock_allowance_mm
       - num_roughing_layers = ceil(roughing_depth / stepdown_mm)
       - Each layer i cuts to Z = work_top_z_mm − (i+1) × layer_doc, where
         layer_doc = roughing_depth / num_roughing_layers (equal passes).
       - Feed rate: roughing_feedrate_mm_per_min.
       - Stepover: stepover_pct (70 % default for face roughing).
       - The last roughing layer floor = work_top_z_mm − roughing_depth,
         leaving stock_allowance_mm of material on the floor.

    2. Finishing pass:
       - Single Z layer at Z = work_top_z_mm − total_depth_mm (final depth).
       - Feed rate: finishing_feedrate_mm_per_min (slower for surface quality).
       - Stepover: finishing_stepover_pct (50 % default, lighter cut).

    Parameters
    ----------
    spec
        FaceMillPathSpec instance.
    climb_milling
        True (default) = climb milling; False = conventional.

    Returns
    -------
    FaceMillRoughFinishResult

    Raises
    ------
    ValueError
        If spec parameters are invalid (see FaceMillPathSpec.__post_init__).
    """
    tool_radius = spec.tool_diameter_mm / 2.0
    x_start = spec.xmin_mm + tool_radius
    x_end = spec.xmax_mm - tool_radius
    z_rapid = spec.work_top_z_mm + spec.rapid_clearance_mm

    # ── Compute roughing layer depths ─────────────────────────────────────────
    roughing_depth = spec.total_depth_mm - spec.stock_allowance_mm
    num_roughing_layers = math.ceil(roughing_depth / spec.stepdown_mm)
    # Equal-doc split (avoids a thin final roughing sliver)
    layer_doc = roughing_depth / num_roughing_layers

    roughing_z_levels = []
    for i in range(num_roughing_layers):
        z = spec.work_top_z_mm - (i + 1) * layer_doc
        roughing_z_levels.append(round(z, 9))

    finishing_z = spec.work_top_z_mm - spec.total_depth_mm

    # ── Y positions per roughing/finishing layer ──────────────────────────────
    roughing_y_positions = _compute_passes_from_bounds(
        spec.xmin_mm, spec.ymin_mm, spec.xmax_mm, spec.ymax_mm,
        spec.tool_diameter_mm, spec.stepover_pct,
    )
    finishing_y_positions = _compute_passes_from_bounds(
        spec.xmin_mm, spec.ymin_mm, spec.xmax_mm, spec.ymax_mm,
        spec.tool_diameter_mm, spec.finishing_stepover_pct,
    )

    num_passes_per_layer = len(roughing_y_positions)
    num_finishing_passes = len(finishing_y_positions)

    # ── Build G-code ──────────────────────────────────────────────────────────
    lines = []
    lines.append("%")
    lines.append(
        "(Face-mill roughing + finishing — Kerf CAM / MH 31e §1136 + NIST RS-274/NGC §3.5)"
    )
    lines.append(
        "(Generated by: kerf_cam.face_mill_path.generate_face_mill_rough_finish_path)"
    )
    lines.append(
        f"(Pocket: X{_fmt(spec.xmin_mm)}..{_fmt(spec.xmax_mm)}"
        f"  Y{_fmt(spec.ymin_mm)}..{_fmt(spec.ymax_mm)}"
        f"  total_depth={_fmt(spec.total_depth_mm)} mm)"
    )
    lines.append(
        f"(Tool: D={_fmt(spec.tool_diameter_mm)} mm"
        f"  roughing_stepover={_fmt(spec.stepover_pct)} %"
        f"  finishing_stepover={_fmt(spec.finishing_stepover_pct)} %)"
    )
    lines.append(
        f"(Roughing: {num_roughing_layers} layers × {_fmt(layer_doc)} mm doc"
        f"  to Z={_fmt(roughing_z_levels[-1])} mm"
        f"  (stock_allowance={_fmt(spec.stock_allowance_mm)} mm))"
    )
    lines.append(
        f"(Finishing: 1 layer at Z={_fmt(finishing_z)} mm"
        f"  F={_fmt(spec.finishing_feedrate_mm_per_min)} mm/min)"
    )
    lines.append(f"(Milling mode: {'climb' if climb_milling else 'conventional'})")
    lines.append("(WARNING: 2.5D only — no helical entry; no cutter comp G41/G42)")
    lines.append("(WARNING: time estimate excludes acceleration ramps)")
    lines.append("G21  (metric mode)")
    lines.append("G90  (absolute distances)")
    lines.append("G94  (feed per minute)")
    lines.append("")

    lines.append(f"M03 S{int(spec.spindle_rpm)}  (spindle on CW)")
    lines.append("")

    total_path_length = 0.0
    total_time_s = 0.0

    # ── Roughing layers ───────────────────────────────────────────────────────
    for layer_idx, z_cut in enumerate(roughing_z_levels):
        layer_label = f"Roughing layer {layer_idx + 1}/{num_roughing_layers}"
        layer_len = _emit_layer_passes(
            lines, roughing_y_positions, x_start, x_end,
            z_cut, z_rapid, spec.roughing_feedrate_mm_per_min,
            climb_milling, layer_label,
        )
        total_path_length += layer_len

        # Time for this layer: cutting + plunges
        cutting_t = (layer_len / spec.roughing_feedrate_mm_per_min) * 60.0
        plunge_dist = abs(z_cut - spec.work_top_z_mm) if layer_idx == 0 else layer_doc
        plunge_t = (plunge_dist / spec.roughing_feedrate_mm_per_min) * 60.0 * num_passes_per_layer
        rapid_per_repos = (spec.rapid_clearance_mm + abs(layer_doc)) / spec.rapid_z_mm * 60.0
        rapid_t = rapid_per_repos * (num_passes_per_layer - 1)
        total_time_s += cutting_t + plunge_t + rapid_t

    # ── Finishing pass ────────────────────────────────────────────────────────
    finish_label = "Finishing pass"
    finish_len = _emit_layer_passes(
        lines, finishing_y_positions, x_start, x_end,
        finishing_z, z_rapid, spec.finishing_feedrate_mm_per_min,
        climb_milling, finish_label,
    )
    total_path_length += finish_len

    # Time for finishing layer
    finish_cutting_t = (finish_len / spec.finishing_feedrate_mm_per_min) * 60.0
    finish_plunge_t = (
        (spec.stock_allowance_mm / spec.finishing_feedrate_mm_per_min) * 60.0
        * num_finishing_passes
    )
    finish_rapid_t = (
        (spec.rapid_clearance_mm + spec.stock_allowance_mm) / spec.rapid_z_mm * 60.0
        * (num_finishing_passes - 1)
    )
    total_time_s += finish_cutting_t + finish_plunge_t + finish_rapid_t

    # Retract and end
    lines.append(f"G00 Z{_fmt(z_rapid)}  (retract to clearance plane)")
    lines.append("M05  (spindle off)")
    lines.append("M30  (program end)")
    lines.append("%")

    gcode = "\n".join(lines)

    # ── Metrics ───────────────────────────────────────────────────────────────
    pocket_area_mm2 = (spec.xmax_mm - spec.xmin_mm) * (spec.ymax_mm - spec.ymin_mm)
    material_removal_mm3 = pocket_area_mm2 * spec.total_depth_mm

    honest_caveat = (
        "2.5D roughing + finishing face-mill — MH 31e §1136 sequence: rough to within "
        f"{spec.stock_allowance_mm} mm, finish to final depth. "
        "Features NOT implemented: "
        "(1) helical ramping entry (tool plunges at feed rate — add ramp macro for production); "
        "(2) cutter compensation G41/G42 (path offsets pre-computed in software); "
        "(3) high-feed (HFC) insert strategies (trochoidal face-roughing not modelled); "
        "(4) wiper-edge finish pass; "
        "(5) corner arcs at pass reversal (momentary dwell possible); "
        "(6) adaptive doc (equal-layer split used — verify chip load per layer against "
        "    CoroPlus ToolGuide for production). "
        "Roughing doc per layer = roughing_depth / num_layers (equal distribution). "
        "Time estimate uses constant feed rates — add 5–15 % for acceleration ramps "
        "(Altintas 2012 §5.7; MH 31e §1109). "
        "MRR = pocket_area × total_depth (assumes 100 % floor coverage). "
        "Refs: MH 31e §1136 (face milling + roughing/finishing); "
        "NIST RS-274/NGC §3.5 (G-code); Sandvik CoroKey §2 (roughing feeds)."
    )

    return FaceMillRoughFinishResult(
        gcode=gcode,
        num_roughing_layers=num_roughing_layers,
        num_passes_per_layer=num_passes_per_layer,
        num_finishing_passes=num_finishing_passes,
        total_path_length_mm=round(total_path_length, 6),
        material_removal_mm3=round(material_removal_mm3, 6),
        machining_time_s=round(total_time_s, 3),
        roughing_z_levels=roughing_z_levels,
        finishing_z=round(finishing_z, 9),
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_face_mill_path_spec = ToolSpec(
    name="cam_generate_face_mill_path",
    description=(
        "Generate a zig-zag face-milling G-code toolpath for a rectangular pocket. "
        "Implements the face-milling strategy from Machinery's Handbook 31e §1136 "
        "(70 % stepover default; climb milling preferred) following NIST RS-274/NGC §3.5. "
        "Returns complete G-code, pass count, total path length, material removal volume, "
        "estimated machining time, and honest caveats. "
        "LIMITATION: 2.5D pocket only (single flat depth); no helical entry; no "
        "high-feed strategies; no cutter compensation G41/G42."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "xmin_mm": {
                "type": "number",
                "description": "Pocket bounding box minimum X (mm, work CS)",
            },
            "ymin_mm": {
                "type": "number",
                "description": "Pocket bounding box minimum Y (mm, work CS)",
            },
            "xmax_mm": {
                "type": "number",
                "description": "Pocket bounding box maximum X (mm, work CS)",
            },
            "ymax_mm": {
                "type": "number",
                "description": "Pocket bounding box maximum Y (mm, work CS)",
            },
            "depth_mm": {
                "type": "number",
                "description": "Axial depth of cut in mm (positive; tool moves in -Z direction)",
            },
            "tool_diameter_mm": {
                "type": "number",
                "description": "Face mill cutter diameter in mm",
            },
            "stepover_pct": {
                "type": "number",
                "description": (
                    "Radial engagement as % of tool diameter (default 70). "
                    "MH 31e §1136: 60–80 % typical for face milling."
                ),
            },
            "feed_mm_per_min": {
                "type": "number",
                "description": "Cutting feed rate in mm/min",
            },
            "spindle_rpm": {
                "type": "number",
                "description": "Spindle speed in RPM",
            },
            "rapid_z_mm": {
                "type": "number",
                "description": "Rapid Z traverse rate in mm/min (used for time estimate, default 10000)",
            },
            "work_top_z_mm": {
                "type": "number",
                "description": "Absolute Z of work surface (default 0.0)",
            },
            "rapid_clearance_mm": {
                "type": "number",
                "description": "Clearance height above work_top_z_mm for rapid moves (default 5.0 mm)",
            },
            "climb_milling": {
                "type": "boolean",
                "description": (
                    "If true (default), use climb milling (pass 0 in +X direction). "
                    "If false, use conventional milling. "
                    "Climb milling per MH 31e §1136 gives better finish and insert life."
                ),
            },
        },
        "required": [
            "xmin_mm", "ymin_mm", "xmax_mm", "ymax_mm",
            "depth_mm", "tool_diameter_mm", "feed_mm_per_min", "spindle_rpm",
        ],
    },
)


@register(cam_generate_face_mill_path_spec)
async def run_cam_generate_face_mill_path(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required_fields = [
        "xmin_mm", "ymin_mm", "xmax_mm", "ymax_mm",
        "depth_mm", "tool_diameter_mm", "feed_mm_per_min", "spindle_rpm",
    ]
    for field in required_fields:
        if field not in a:
            return err_payload(f"missing required field: {field!r}", "BAD_ARGS")

    try:
        spec = FaceMillSpec(
            xmin_mm=float(a["xmin_mm"]),
            ymin_mm=float(a["ymin_mm"]),
            xmax_mm=float(a["xmax_mm"]),
            ymax_mm=float(a["ymax_mm"]),
            depth_mm=float(a["depth_mm"]),
            tool_diameter_mm=float(a["tool_diameter_mm"]),
            stepover_pct=float(a.get("stepover_pct", 70.0)),
            feed_mm_per_min=float(a["feed_mm_per_min"]),
            spindle_rpm=float(a["spindle_rpm"]),
            rapid_z_mm=float(a.get("rapid_z_mm", 10000.0)),
            work_top_z_mm=float(a.get("work_top_z_mm", 0.0)),
            rapid_clearance_mm=float(a.get("rapid_clearance_mm", 5.0)),
        )
        climb = bool(a.get("climb_milling", True))
        result = generate_face_mill_path(spec, climb_milling=climb)
    except (KeyError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "gcode": result.gcode,
        "num_passes": result.num_passes,
        "total_path_length_mm": result.total_path_length_mm,
        "material_removal_mm3": result.material_removal_mm3,
        "machining_time_s": result.machining_time_s,
        "honest_caveat": result.honest_caveat,
    })
