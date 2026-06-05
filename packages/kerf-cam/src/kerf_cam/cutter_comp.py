"""
kerf_cam.cutter_comp — G41/G42 cutter-radius compensation wrapper.

Provides a pure-Python function and LLM tool that takes a 2-D toolpath
(list of (x, y) tuples) and wraps it with the correct G41/G42 cutter-
compensation preamble and G40 cancel, producing G-code that the controller's
TRC (tool-radius compensation) module can interpret.

Coordinate convention
---------------------
All coordinates are in mm (G21 metric mode).  The tool travels in the XY
plane (G17).  Z moves (plunge/retract) are passed through unchanged.

G41 / G42 semantics (Fanuc Operator Manual + NIST RS-274/NGC §3.7)
------------------------------------------------------------------
  G41  — cutter compensation LEFT of programmed path.
         Equivalent to climb milling on an outside profile when the tool
         travels CCW around the part.
  G42  — cutter compensation RIGHT of programmed path.
         Equivalent to conventional milling on an outside profile when
         the tool travels CW around the part.
  G40  — cancel cutter compensation (must be on a linear G0/G1 move).

The activation (G41/G42) must be on the FIRST linear move after the
tool touches the Z clearance height; the first move must be non-zero
length (the controller needs a direction vector to resolve the offset).

Wiring note
-----------
This module provides a software-side offset path (for preview and verification)
as well as the raw G-code wrapper.  For machines that implement TRC in
hardware the software offset is informational only — the controller applies
the offset using the actual tool-radius register (D word).

References
----------
* NIST RS-274/NGC §3.7 — Cutter compensation (G40/G41/G42)
* Fanuc Series 0i-MC Operator's Manual §12.1 — Tool-radius compensation
* MH 31e §1130 — Cutter compensation rationale and entry strategy
"""

from __future__ import annotations

import json
import math
from typing import Optional

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Pure-Python cutter-comp offset geometry
# ---------------------------------------------------------------------------

def _offset_path_2d(
    path_xy: list[tuple[float, float]],
    offset_mm: float,
    side: str,  # "left" | "right"
) -> list[tuple[float, float]]:
    """Return a software-offset copy of *path_xy* by *offset_mm*.

    Uses a simple per-segment normal offset:
      * For each segment compute the unit normal.
      * Offset each endpoint by offset_mm in the normal direction.
      * At joins, average consecutive normals (miter join, capped at 4×).

    This is a straight-line approximation — it does not handle arc segments
    or tightly concave corners.  For convex polygons the result is exact.

    side : "left" → offset to the left of the travel direction (G41).
           "right" → offset to the right (G42).
    """
    if len(path_xy) < 2:
        return list(path_xy)

    sign = +1.0 if side == "left" else -1.0

    def _seg_normal(p0, p1):
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-12:
            return (0.0, 0.0)
        # Left normal = rotate +90°: (−dy, dx) / length
        return (-dy / length * sign, dx / length * sign)

    normals = [_seg_normal(path_xy[i], path_xy[i + 1]) for i in range(len(path_xy) - 1)]

    offsets: list[tuple[float, float]] = []
    for i, pt in enumerate(path_xy):
        if i == 0:
            nx, ny = normals[0]
        elif i == len(path_xy) - 1:
            nx, ny = normals[-1]
        else:
            n0 = normals[i - 1]
            n1 = normals[i]
            nx = (n0[0] + n1[0]) / 2.0
            ny = (n0[1] + n1[1]) / 2.0
            # Cap miter factor at 4×
            mag = math.sqrt(nx * nx + ny * ny)
            if mag > 1e-12:
                # miter factor = 1/cos(half-angle) ≈ 1/mag when n0, n1 unit
                miter = 1.0 / mag
                if miter > 4.0:
                    miter = 4.0
                nx = nx / mag * miter
                ny = ny / mag * miter

        offsets.append((pt[0] + nx * offset_mm, pt[1] + ny * offset_mm))

    return offsets


def generate_cutter_comp_gcode(
    path_xy: list[tuple[float, float]],
    tool_radius_mm: float,
    comp_side: str,           # "G41" | "G42"
    z_cut_mm: float = 0.0,
    z_clear_mm: float = 5.0,
    feed_mm_min: float = 800.0,
    rapid_mm_min: float = 5000.0,
    spindle_rpm: Optional[int] = None,
    tool_number: int = 1,
    d_register: int = 1,
    dialect: str = "linuxcnc",  # "linuxcnc" | "fanuc"
    include_software_offset: bool = False,
) -> dict:
    """Generate 2D contour G-code with G41/G42 cutter-radius compensation.

    Parameters
    ----------
    path_xy : list of (x, y) tuples
        Programmed path (tool-centre path without compensation).  At least 2 pts.
    tool_radius_mm : float
        Cutter radius for D-register and software-offset preview.
    comp_side : str
        "G41" (left / climb) or "G42" (right / conventional).
    z_cut_mm : float
        Z depth for the cutting pass.  Default 0.0.
    z_clear_mm : float
        Z clearance height for rapids.  Default 5.0.
    feed_mm_min : float
        Linear feed rate mm/min.  Default 800.
    spindle_rpm : int | None
        S-word; if None, omitted from output.
    tool_number : int
        T-word for tool change.  Default 1.
    d_register : int
        D-word (compensation register number).  Default 1.
    dialect : str
        G-code dialect: "linuxcnc" (semicolon comments) or "fanuc" (N-numbers,
        parenthetical comments).
    include_software_offset : bool
        When True, append a ``software_offset_path`` key in the result containing
        the pre-computed offset path (for preview / verification).

    Returns
    -------
    dict
        gcode_lines : list[str]
        warnings    : list[str]
        software_offset_path : list[list[float]] (only when include_software_offset=True)
    """
    warnings: list[str] = []

    if len(path_xy) < 2:
        return {
            "gcode_lines": [],
            "warnings": ["path_xy must have at least 2 points"],
        }

    if comp_side not in ("G41", "G42"):
        warnings.append(f"Unknown comp_side {comp_side!r} — defaulting to G41")
        comp_side = "G41"

    side = "left" if comp_side == "G41" else "right"

    # Software-offset path (tool-centre path after compensation).
    soft_offset = _offset_path_2d(path_xy, tool_radius_mm, side)

    cmt_open = "(" if dialect == "fanuc" else "; "
    cmt_close = ")" if dialect == "fanuc" else ""

    def _c(text: str) -> str:
        return f"{cmt_open}{text}{cmt_close}"

    lines: list[str] = []
    n = [10]  # N-line counter (Fanuc only)

    def emit(line: str) -> None:
        if dialect == "fanuc":
            lines.append(f"N{n[0]} {line}")
            n[0] += 10
        else:
            lines.append(line)

    if dialect == "linuxcnc":
        lines.append("%")

    emit(_c(f"2D contour — {comp_side} cutter compensation (D{d_register}, R={tool_radius_mm:.3f} mm)"))
    emit(_c("NIST RS-274/NGC §3.7 — cancel comp with G40 on a non-zero-length move"))
    emit("G21 G90 G17 G94")       # metric, absolute, XY plane, mm/min feed
    emit("G54")                   # work coordinate system

    tool_call = f"M6 T{tool_number}"
    emit(tool_call)

    if spindle_rpm is not None:
        emit(f"S{int(spindle_rpm)} M3")
    else:
        emit("M3")

    # Rapid to start XY at clearance Z
    x0, y0 = path_xy[0]
    emit(f"G0 X{x0:.4f} Y{y0:.4f} Z{z_clear_mm:.4f}")

    # Plunge to cut depth
    emit(f"G1 Z{z_cut_mm:.4f} F{feed_mm_min * 0.25:.1f}")

    # Activate cutter compensation on the FIRST G1 move.
    # The D register holds the tool radius. The first move must be non-zero length.
    x1, y1 = path_xy[1]
    emit(f"{comp_side} D{d_register}")
    emit(f"G1 X{x1:.4f} Y{y1:.4f} F{feed_mm_min:.1f}")

    for pt in path_xy[2:]:
        emit(f"G1 X{pt[0]:.4f} Y{pt[1]:.4f} F{feed_mm_min:.1f}")

    # Cancel compensation on the last move (must be non-zero; retract in Z).
    emit(f"G40")
    emit(f"G1 Z{z_clear_mm:.4f} F{feed_mm_min:.1f}")
    emit("M5")
    emit("M30")

    if dialect == "linuxcnc":
        lines.append("%")

    result: dict = {
        "gcode_lines": lines,
        "warnings": warnings,
    }
    if include_software_offset:
        result["software_offset_path"] = [[p[0], p[1]] for p in soft_offset]

    return result


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_apply_cutter_comp_spec = ToolSpec(
    name="cam_apply_cutter_comp",
    description=(
        "Wrap a 2-D XY toolpath with G41/G42 cutter-radius compensation (TRC) "
        "and emit the complete contour G-code block. "
        "G41 = cutter left of path (climb milling / outside CCW profile). "
        "G42 = cutter right of path (conventional milling / outside CW profile). "
        "Also returns a software_offset_path (pre-computed offset for preview). "
        "The tool activates comp on the first G1 move (D register) and cancels "
        "with G40 on the final retract. "
        "References: NIST RS-274/NGC §3.7; Fanuc 0i-MC §12.1; MH 31e §1130. "
        "Supports linuxcnc and fanuc dialects."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path_xy": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 2,
                "description": "2-D toolpath as [[x_mm, y_mm], ...] (at least 2 points).",
            },
            "tool_radius_mm": {
                "type": "number",
                "description": "Cutter radius in mm (half tool diameter).",
            },
            "comp_side": {
                "type": "string",
                "enum": ["G41", "G42"],
                "description": (
                    "G41 = cutter LEFT of path (climb milling / outside CCW profile). "
                    "G42 = cutter RIGHT of path (conventional milling / outside CW profile)."
                ),
            },
            "z_cut_mm": {
                "type": "number",
                "description": "Z depth for the cutting pass in mm. Default 0.0.",
            },
            "z_clear_mm": {
                "type": "number",
                "description": "Z clearance height for rapids in mm. Default 5.0.",
            },
            "feed_mm_min": {
                "type": "number",
                "description": "Feed rate in mm/min. Default 800.",
            },
            "spindle_rpm": {
                "type": "integer",
                "description": "Spindle speed in RPM (optional; omits S-word if not provided).",
            },
            "tool_number": {
                "type": "integer",
                "description": "T-word for tool change. Default 1.",
            },
            "d_register": {
                "type": "integer",
                "description": "D-register number for tool-radius offset. Default 1.",
            },
            "dialect": {
                "type": "string",
                "enum": ["linuxcnc", "fanuc"],
                "description": (
                    "G-code dialect. 'linuxcnc' (default) — semicolon comments, % markers. "
                    "'fanuc' — N-line numbers, parenthetical comments."
                ),
            },
            "include_software_offset": {
                "type": "boolean",
                "description": (
                    "When true, include software_offset_path in result "
                    "(pre-computed offset path for preview / verification). Default false."
                ),
            },
        },
        "required": ["path_xy", "tool_radius_mm", "comp_side"],
    },
)


@register(cam_apply_cutter_comp_spec)
async def run_cam_apply_cutter_comp(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    path_raw = a.get("path_xy")
    tool_radius = a.get("tool_radius_mm")
    comp_side = a.get("comp_side", "G41")

    if not path_raw:
        return err_payload("path_xy is required", "BAD_ARGS")
    if tool_radius is None:
        return err_payload("tool_radius_mm is required", "BAD_ARGS")
    if comp_side not in ("G41", "G42"):
        return err_payload(f"comp_side must be 'G41' or 'G42', got {comp_side!r}", "BAD_ARGS")

    try:
        path_xy = [(float(p[0]), float(p[1])) for p in path_raw]
    except (TypeError, IndexError, ValueError) as e:
        return err_payload(f"invalid path_xy format: {e}", "BAD_ARGS")

    if len(path_xy) < 2:
        return err_payload("path_xy must have at least 2 points", "BAD_ARGS")

    try:
        tool_radius = float(tool_radius)
    except (TypeError, ValueError) as e:
        return err_payload(f"invalid tool_radius_mm: {e}", "BAD_ARGS")

    if tool_radius <= 0:
        return err_payload("tool_radius_mm must be > 0", "BAD_ARGS")

    try:
        result = generate_cutter_comp_gcode(
            path_xy=path_xy,
            tool_radius_mm=tool_radius,
            comp_side=comp_side,
            z_cut_mm=float(a.get("z_cut_mm", 0.0)),
            z_clear_mm=float(a.get("z_clear_mm", 5.0)),
            feed_mm_min=float(a.get("feed_mm_min", 800.0)),
            spindle_rpm=int(a["spindle_rpm"]) if "spindle_rpm" in a else None,
            tool_number=int(a.get("tool_number", 1)),
            d_register=int(a.get("d_register", 1)),
            dialect=str(a.get("dialect", "linuxcnc")),
            include_software_offset=bool(a.get("include_software_offset", False)),
        )
    except Exception as e:
        return err_payload(str(e), "ENGINE_ERROR")

    return ok_payload(result)
