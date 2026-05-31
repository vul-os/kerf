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

Honest caveats
--------------
- 2.5D only — single flat depth, no helical entry, no ramping.
- No cutter compensation (G41/G42) — path offsets are computed in software.
- Time estimate: constant feed rate, no acceleration ramps (add 5–15 % for
  real machine dynamics per MH 31e §1109).
- High-feed (HFC) insert strategies, wiper-edge edge passes, and trochoid
  face-roughing are not implemented.
- Tool nose radius compensation not applied.
- No corner arcs — the zig-zag reversal is a feed-rate point reversal, which
  may cause a momentary dwell; use G00 + G01 repositioning if the controller
  does not support direction reversal within G01.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

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


def _compute_passes(spec: FaceMillSpec) -> list[float]:
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


# ---------------------------------------------------------------------------
# Main generator
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
    lines: list[str] = []
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
