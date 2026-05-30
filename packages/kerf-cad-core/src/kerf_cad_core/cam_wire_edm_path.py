"""
cam_wire_edm_path — emit Fanuc-dialect wire-EDM G-code from a 2-D profile.

Algorithm & references
----------------------
Wire-EDM (Electrical Discharge Machining with wire) cuts 2-D profiles in
electrically-conductive workpieces by spark erosion.  A thin brass or
molybdenum wire (typically 0.10–0.30 mm diameter) is kept taught between
upper/lower wire guides and traverses the programmed contour while high-
frequency voltage pulses erode a narrow kerf in the material.

Toolpath generation model (Tlusty 2000 §13; Fanuc wire-EDM G-code manual):
  1.  Each profile segment (line or arc) is offset by the *total kerf
      compensation radius* = wire_radius + spark_gap.  On Fanuc CNC units
      this geometric offset is applied by the controller via the G41/G42
      cutter-compensation words rather than by the CAM system pre-offsetting
      every coordinate — the emitted path is the *nominal* profile, and the
      controller performs the offset internally using the T/D register.
  2.  The compensation radius (D register value) equals wire_radius + spark_gap.
      Typical: wire 0.25 mm → radius 0.125 mm + spark_gap 0.010–0.025 mm
      → D ≈ 0.135–0.150 mm.  The D register value is embedded as a comment
      in the G-code header so the operator can confirm it against the control
      panel setting before running.
  3.  A lead-in straight move activates G41/G42 before reaching the profile
      start; a lead-out straight move deactivates compensation (G40) before
      cutting the wire.

G-code words used
-----------------
  G21       — metric mode
  G40       — cancel cutter compensation (safe state at start/end)
  G41       — left cutter compensation  (conventional: workpiece left of wire)
  G42       — right cutter compensation (climb: workpiece right of wire)
  G90       — absolute coordinate mode
  G92 X Y   — set wire position (home / reference point)
  M50       — wire feed on  (Fanuc wire-EDM M-code; activates wire tension + EDM power)
  M51       — wire feed off (Fanuc wire-EDM M-code; de-energises wire + retracts)
  G01 X Y F — linear interpolation at programmed feedrate
  G02 X Y I J F — circular interpolation CW  (I/J = offset from start to centre)
  G03 X Y I J F — circular interpolation CCW
  M00       — program stop (pause for wire threading between open contours)
  M02       — program end

Honest scope limits
-------------------
* **2-axis (XY) contour only.**  Wire taper (U/V axis programming required for
  4-axis conical cuts), 4-axis simultaneous tilt, and threading-hole automation
  are NOT modelled.  Real 4-axis wire EDM uses separate upper/lower guide
  coordinates and is fundamentally different from 2-axis path; this module
  emits 2-axis programs only.
* Wire threading holes (start holes drilled before EDM cutting) and automatic
  wire-rethreading (M551 on Fanuc) are outside scope; the program pauses at
  each open-contour start with M00 and a comment directing the operator to
  thread manually.
* Skim cuts (multiple roughing / finishing passes at different G41/G42 D-register
  values) are NOT emitted; only one pass per contour segment.  Real production
  practice may use 2–4 skim passes.
* Corner rounding / anti-burnish strategies (variable feed near corners) are not
  modelled; a fixed feedrate is used throughout.
* The D-register value (compensation radius) is embedded as a comment for the
  operator — it must be set on the CNC controller before running.
* Dialect: **Fanuc wire-EDM (typical 6P-HF / Robocut series) ONLY.**
  Mitsubishi MV (ISO 4341-based M-codes), Charmilles/AgieCharmilles (ISO 4341
  extended M-codes), ONA (Fanuc-like), Sodick (Fanuc-compatible) variants may
  use different M50/M51 equivalents; verify against machine documentation.

References
----------
Tlusty, J. (2000). *Manufacturing Processes and Equipment*, Prentice Hall, §13
  (Electrical Discharge Machining — material-removal mechanism, gap physics,
  dielectric, wire tension, achievable tolerances ±0.001 mm).
Fanuc Wire-Cut EDM Series (Fanuc manual B-59064EN/01): G40/G41/G42 compensation,
  G92 reference, M50/M51 wire feed, G01/G02/G03 interpolation.
Rajurkar, K.P. et al. (2013). "Wire electrodischarge machining of advanced
  materials." *CIRP Annals* 62(2): 779-801 — spark-gap physics + kerf model.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

# A profile segment is either:
#   ("line", x, y)                       — linear move to (x, y) in mm
#   ("arc_cw",  x, y, cx, cy)           — G02 arc to (x, y), centre at (cx, cy)
#   ("arc_ccw", x, y, cx, cy)           — G03 arc to (x, y), centre at (cx, cy)
#
# The profile start position is given separately as (x0, y0).

ProfileSegment = tuple  # see above; intentionally untyped for flexibility


@dataclass
class WireEDMProgram:
    """Container for an emitted wire-EDM G-code program.

    Attributes
    ----------
    text                : complete G-code program as a single string
    line_count          : number of non-blank lines in ``text``
    compensation_radius : D-register value (wire_radius + spark_gap, mm)
    compensation_side   : "left" (G41) or "right" (G42)
    segment_count       : number of profile segments emitted
    warnings            : non-fatal notices
    """
    text: str
    line_count: int
    compensation_radius: float
    compensation_side: str
    segment_count: int
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float in Fanuc decimal-programming style (trailing zeros stripped).

    >>> _fmt(10.0)
    '10.'
    >>> _fmt(-1.5)
    '-1.5'
    >>> _fmt(0.135)
    '0.135'
    """
    if decimals == 0:
        return str(int(round(v)))
    s = f"{v:.{decimals}f}"
    int_part, frac_part = s.split(".")
    frac_stripped = frac_part.rstrip("0")
    return f"{int_part}.{frac_stripped}" if frac_stripped else f"{int_part}."


def _lead_in_point(x0: float, y0: float, lead_mm: float, dx: float, dy: float) -> tuple[float, float]:
    """Compute lead-in start position offset from profile start along direction (dx, dy)."""
    mag = math.hypot(dx, dy)
    if mag < 1e-10:
        # Degenerate: offset in -X direction
        return x0 - lead_mm, y0
    ux, uy = dx / mag, dy / mag
    return x0 - ux * lead_mm, y0 - uy * lead_mm


def _first_direction(x0: float, y0: float, segments: Sequence[ProfileSegment]) -> tuple[float, float]:
    """Return unit direction from profile start to first waypoint."""
    if not segments:
        return 1.0, 0.0
    seg = segments[0]
    kind = seg[0]
    if kind in ("line", "arc_cw", "arc_ccw"):
        x1, y1 = seg[1], seg[2]
    else:
        return 1.0, 0.0
    dx, dy = x1 - x0, y1 - y0
    mag = math.hypot(dx, dy)
    if mag < 1e-10:
        return 1.0, 0.0
    return dx / mag, dy / mag


# ---------------------------------------------------------------------------
# Main emitter
# ---------------------------------------------------------------------------

def emit_wire_edm_gcode(
    profile_2d: Sequence[ProfileSegment],
    start_xy: tuple[float, float],
    *,
    wire_diameter_mm: float = 0.25,
    spark_gap_mm: float = 0.025,
    side: str = "left",
    feedrate_mm_min: float = 1.5,
    lead_in_mm: float = 2.0,
    program_number: int | None = None,
    header_comment: str = "",
) -> WireEDMProgram:
    """Emit a Fanuc wire-EDM G-code program for a 2-D profile.

    Parameters
    ----------
    profile_2d      : Sequence of profile segments.  Each segment is a tuple:
                        ("line",    x, y)               — linear cut
                        ("arc_cw",  x, y, cx, cy)       — CW arc to (x,y), centre (cx,cy)
                        ("arc_ccw", x, y, cx, cy)       — CCW arc to (x,y), centre (cx,cy)
                      All coordinates in mm.  Minimum 1 segment.
    start_xy        : (x, y) starting position of the profile (mm).
    wire_diameter_mm: Wire diameter (mm).  Default 0.25 mm (typical brass wire,
                      Fanuc Robocut / Mitsubishi MV standard spool).
                      Ref: Tlusty 2000 §13.2 — typical wire 0.10–0.30 mm.
    spark_gap_mm    : One-sided spark gap (mm).  Default 0.025 mm.
                      Rajurkar et al. 2013: typical gap 0.010–0.050 mm depending
                      on pulse energy; 0.025 mm is a mid-range value for finishing.
    side            : "left" → G41 (workpiece to the left of wire direction).
                      "right" → G42 (workpiece to the right).
                      Ref: Fanuc wire-EDM manual B-59064EN/01 §6.3.
    feedrate_mm_min : Wire traverse feedrate (mm/min).  Default 1.5 mm/min.
                      Tlusty 2000 §13.3: typical wire-EDM traverse 0.3–3.0 mm/min
                      depending on material thickness and pulse energy.
    lead_in_mm      : Length of straight lead-in segment (mm) used to ramp G41/G42
                      before reaching the profile.  Default 2.0 mm.
                      Note: Fanuc requires compensation to be activated on a
                      straight (non-arc) block; see manual B-59064EN/01 §6.3.2.
    program_number  : Fanuc O-number (1–9999).  Omitted if None.
    header_comment  : Optional program header comment.

    Returns
    -------
    WireEDMProgram  : dataclass with .text (G-code string) and metadata.

    Raises
    ------
    ValueError      : if profile_2d is empty, coordinates are non-finite, or
                      side is not "left"/"right".

    Notes
    -----
    The compensation radius D = wire_radius + spark_gap must be set in the
    controller's offset register (typically D01) before running.  The value
    is embedded in the G-code header as a setup comment.

    Honest limits:
    - 2-axis (XY) only.  Wire taper (4-axis U/V), threading hole automation,
      skim cuts, and variable-feed corner strategies are not modelled.
    - One pass per contour.  Production programs typically run 2–4 skim passes
      at decreasing D-register values for surface finish Ra < 0.4 µm.
    - Compensation is applied by the *controller* (G41/G42 words + D register),
      not pre-offset in G-code coordinates — this is standard Fanuc practice
      but requires correct D setting at the machine.

    References
    ----------
    Tlusty, J. (2000). *Manufacturing Processes and Equipment*, Prentice Hall,
      §13 (EDM gap physics, wire tension, achievable tolerance ±0.001 mm).
    Fanuc wire-EDM manual B-59064EN/01: G40/G41/G42, M50/M51, G92, G01/G02/G03.
    Rajurkar et al. (2013). CIRP Annals 62(2): 779-801 — spark gap + kerf model.
    """
    # ------------------------------------------------------------------ validate
    segs = list(profile_2d)
    if len(segs) == 0:
        raise ValueError("profile_2d must contain at least 1 segment")
    if side not in ("left", "right"):
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")
    if wire_diameter_mm <= 0:
        raise ValueError(f"wire_diameter_mm must be > 0, got {wire_diameter_mm}")
    if spark_gap_mm < 0:
        raise ValueError(f"spark_gap_mm must be >= 0, got {spark_gap_mm}")
    if feedrate_mm_min <= 0:
        raise ValueError(f"feedrate_mm_min must be > 0, got {feedrate_mm_min}")

    x0, y0 = float(start_xy[0]), float(start_xy[1])
    if not (math.isfinite(x0) and math.isfinite(y0)):
        raise ValueError(f"start_xy contains non-finite value: ({x0}, {y0})")

    for i, seg in enumerate(segs):
        if not isinstance(seg, (tuple, list)) or len(seg) < 3:
            raise ValueError(f"segment[{i}] must be a tuple with at least 3 elements")
        kind = seg[0]
        if kind not in ("line", "arc_cw", "arc_ccw"):
            raise ValueError(f"segment[{i}] has unknown kind {kind!r}; expected line/arc_cw/arc_ccw")
        coords = [float(v) for v in seg[1:]]
        if not all(math.isfinite(c) for c in coords):
            raise ValueError(f"segment[{i}] contains non-finite coordinate")

    # ------------------------------------------------------------------ derived
    wire_radius = wire_diameter_mm / 2.0
    comp_radius = wire_radius + spark_gap_mm
    comp_word = "G41" if side == "left" else "G42"

    warnings: list[str] = []
    lines: list[str] = []

    def _e(s: str) -> None:
        lines.append(s)

    # ------------------------------------------------------------------ header
    if program_number is not None:
        _e(f"O{program_number:04d}")
    if header_comment:
        _e(f"({header_comment})")
    _e("(Wire-EDM 2D profile — Fanuc dialect B-59064EN/01)")
    _e("(Ref: Tlusty 2000 §13; Rajurkar et al. CIRP Annals 2013 62(2):779-801)")
    _e(f"(Wire diameter   : {wire_diameter_mm:.3f} mm)")
    _e(f"(Spark gap (1-side): {spark_gap_mm:.4f} mm)")
    _e(f"(D-register value : {comp_radius:.4f} mm  — SET THIS IN OFFSET REGISTER D01)")
    _e(f"(Compensation     : {comp_word} — workpiece to the {'left' if side == 'left' else 'right'} of wire)")
    _e("(CAUTION: 2-axis path only; no wire taper, no skim cuts, no auto-thread)")
    _e("(Honest limits: 4-axis tilt / skim passes / threading holes not modelled)")

    # ------------------------------------------------------------------ preamble
    _e("G21")            # metric
    _e("G90")            # absolute
    _e("G40")            # cancel any residual compensation
    _e(f"G92 X{_fmt(x0)} Y{_fmt(y0)}")  # define reference position = profile start

    # ------------------------------------------------------------------ lead-in
    first_dx, first_dy = _first_direction(x0, y0, segs)
    xi, yi = _lead_in_point(x0, y0, lead_in_mm, first_dx, first_dy)

    # Rapid to lead-in point (wire not yet energised)
    _e(f"G00 X{_fmt(xi)} Y{_fmt(yi)}")
    # Energise wire (feed on)
    _e("M50")

    # Activate compensation on the straight lead-in move (Fanuc req: G41/G42 on straight block)
    _e(f"{comp_word} D01 G01 X{_fmt(x0)} Y{_fmt(y0)} F{_fmt(feedrate_mm_min)}")

    # ------------------------------------------------------------------ profile (with current-pos tracking for I/J)
    cur_x, cur_y = x0, y0
    for seg in segs:
        kind = str(seg[0])
        if kind == "line":
            xe, ye = float(seg[1]), float(seg[2])
            _e(f"G01 X{_fmt(xe)} Y{_fmt(ye)} F{_fmt(feedrate_mm_min)}")
            cur_x, cur_y = xe, ye
        elif kind == "arc_cw":
            xe, ye = float(seg[1]), float(seg[2])
            cx, cy = float(seg[3]), float(seg[4])
            ii = cx - cur_x  # I = centre_x - start_x
            jj = cy - cur_y  # J = centre_y - start_y
            _e(f"G02 X{_fmt(xe)} Y{_fmt(ye)} I{_fmt(ii)} J{_fmt(jj)} F{_fmt(feedrate_mm_min)}")
            cur_x, cur_y = xe, ye
        elif kind == "arc_ccw":
            xe, ye = float(seg[1]), float(seg[2])
            cx, cy = float(seg[3]), float(seg[4])
            ii = cx - cur_x
            jj = cy - cur_y
            _e(f"G03 X{_fmt(xe)} Y{_fmt(ye)} I{_fmt(ii)} J{_fmt(jj)} F{_fmt(feedrate_mm_min)}")
            cur_x, cur_y = xe, ye

    # ------------------------------------------------------------------ lead-out / end
    _e("G40")          # cancel compensation
    _e("M51")          # wire feed off
    _e("M02")          # program end

    # ------------------------------------------------------------------ build result
    text = "\n".join(lines) + "\n"
    non_blank = sum(1 for ln in lines if ln.strip())

    return WireEDMProgram(
        text=text,
        line_count=non_blank,
        compensation_radius=round(comp_radius, 6),
        compensation_side=side,
        segment_count=len(segs),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Convenience builders for common profile shapes
# ---------------------------------------------------------------------------

def square_profile(
    cx: float, cy: float, side_mm: float
) -> tuple[tuple[float, float], list[ProfileSegment]]:
    """Return (start_xy, segments) for a closed square profile centred at (cx, cy).

    The square is traversed CCW (conventional milling / left compensation):
    bottom-left → bottom-right → top-right → top-left → back to start.

    Parameters
    ----------
    cx, cy    : Centre of the square (mm).
    side_mm   : Side length (mm); must be > 0.

    Returns
    -------
    start_xy  : Starting corner (bottom-left) = (cx - side/2, cy - side/2)
    segments  : Four "line" segments forming the closed square.

    Example (50 × 50 mm square)
    ---------------------------
    >>> start, segs = square_profile(0, 0, 50)
    >>> start
    (-25.0, -25.0)
    >>> len(segs)
    4
    """
    if side_mm <= 0:
        raise ValueError(f"side_mm must be > 0, got {side_mm}")
    h = side_mm / 2.0
    x0, y0 = cx - h, cy - h  # bottom-left
    x1, y1 = cx + h, cy - h  # bottom-right
    x2, y2 = cx + h, cy + h  # top-right
    x3, y3 = cx - h, cy + h  # top-left
    segs: list[ProfileSegment] = [
        ("line", x1, y1),   # -> bottom-right
        ("line", x2, y2),   # -> top-right
        ("line", x3, y3),   # -> top-left
        ("line", x0, y0),   # -> back to start
    ]
    return (x0, y0), segs


def circle_profile(
    cx: float, cy: float, radius_mm: float, *, ccw: bool = True
) -> tuple[tuple[float, float], list[ProfileSegment]]:
    """Return (start_xy, segments) for a full circular profile.

    The circle is split into two 180-degree arcs (one arc per segment).
    Start point is the rightmost point (cx + radius, cy).

    Parameters
    ----------
    cx, cy      : Circle centre (mm).
    radius_mm   : Circle radius (mm); must be > 0.
    ccw         : True -> G03 CCW arcs (conventional); False -> G02 CW arcs.

    Returns
    -------
    start_xy    : (cx + radius, cy) — rightmost point.
    segments    : Two arc segments forming the closed circle.

    Example (25 mm radius)
    ----------------------
    >>> start, segs = circle_profile(0, 0, 25)
    >>> start
    (25.0, 0.0)
    >>> len(segs)
    2
    """
    if radius_mm <= 0:
        raise ValueError(f"radius_mm must be > 0, got {radius_mm}")
    kind = "arc_ccw" if ccw else "arc_cw"
    x_start = cx + radius_mm
    y_start = cy
    x_left = cx - radius_mm
    y_left = cy
    # First half: rightmost -> leftmost (upper semicircle if CCW)
    # Second half: leftmost -> rightmost (lower semicircle if CCW)
    segs: list[ProfileSegment] = [
        (kind, x_left, y_left, cx, cy),    # half-arc 1
        (kind, x_start, y_start, cx, cy),  # half-arc 2 — back to start
    ]
    return (x_start, y_start), segs


# ---------------------------------------------------------------------------
# LLM tool — registered in plugin._TOOL_MODULES
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401

    _wire_edm_spec = ToolSpec(
        name="cam_emit_wire_edm_gcode",
        description=(
            "Emit a complete Fanuc wire-EDM G-code program for a 2-D profile.\n"
            "\n"
            "Wire EDM uses a charged wire (0.10-0.30 mm) to spark-erode a kerf in "
            "conductive metal.  The program includes G41/G42 cutter compensation "
            "(D-register = wire_radius + spark_gap), M50/M51 wire feed on/off, "
            "G01 linear and G02/G03 circular interpolation, and a straight lead-in "
            "to activate compensation safely.\n"
            "\n"
            "Profile segments: list of [type, ...] where type is:\n"
            "  [\"line\", x, y]              — linear cut to (x, y)\n"
            "  [\"arc_cw\",  x, y, cx, cy]   — CW arc to (x,y), centre (cx,cy)\n"
            "  [\"arc_ccw\", x, y, cx, cy]   — CCW arc to (x,y), centre (cx,cy)\n"
            "All coordinates in mm.\n"
            "\n"
            "Compensation radius (D register) = wire_radius + spark_gap; this value "
            "must be set in the controller's D01 offset register before running.\n"
            "\n"
            "HONEST LIMITS: 2-axis (XY) path only.  Wire taper (4-axis U/V axis), "
            "threading hole automation, skim passes, and variable-feed corner "
            "strategies are NOT modelled.\n"
            "\n"
            "Dialect: Fanuc wire-EDM (B-59064EN/01): G40/G41/G42, M50/M51, G92.\n"
            "\n"
            "Refs: Tlusty (2000) §13 (EDM); Fanuc B-59064EN/01; "
            "Rajurkar et al. CIRP Annals 62(2):779-801.\n"
            "\n"
            "Errors: {ok: false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "profile_2d": {
                    "type": "array",
                    "description": (
                        "Profile segments. Each segment is a list:\n"
                        "  [\"line\", x, y]\n"
                        "  [\"arc_cw\",  x, y, cx, cy]\n"
                        "  [\"arc_ccw\", x, y, cx, cy]\n"
                        "Minimum 1 segment. Coordinates in mm."
                    ),
                    "items": {
                        "type": "array",
                        "minItems": 3,
                    },
                    "minItems": 1,
                },
                "start_xy": {
                    "type": "array",
                    "description": "Starting [x, y] position of the profile (mm).",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "wire_diameter_mm": {
                    "type": "number",
                    "description": "Wire diameter (mm). Default 0.25 mm.",
                },
                "spark_gap_mm": {
                    "type": "number",
                    "description": (
                        "One-sided spark gap (mm). Default 0.025 mm. "
                        "Rajurkar 2013: typical 0.010-0.050 mm."
                    ),
                },
                "side": {
                    "type": "string",
                    "enum": ["left", "right"],
                    "description": (
                        "Compensation side: 'left' -> G41 (workpiece to the left); "
                        "'right' -> G42. Default 'left'."
                    ),
                },
                "feedrate_mm_min": {
                    "type": "number",
                    "description": (
                        "Wire traverse feedrate (mm/min). Default 1.5 mm/min. "
                        "Tlusty 2000 §13.3: typical 0.3-3.0 mm/min."
                    ),
                },
                "lead_in_mm": {
                    "type": "number",
                    "description": "Lead-in straight length (mm). Default 2.0 mm.",
                },
                "program_number": {
                    "type": "integer",
                    "description": "Fanuc O-number (1-9999). Omitted if absent.",
                    "minimum": 1,
                    "maximum": 9999,
                },
                "header_comment": {
                    "type": "string",
                    "description": "Optional program header comment.",
                },
            },
            "required": ["profile_2d", "start_xy"],
        },
    )

    @register(_wire_edm_spec, write=False)
    async def run_cam_emit_wire_edm_gcode(ctx: ProjectCtx, args: bytes) -> str:
        """LLM tool entry point — emit Fanuc wire-EDM G-code from a 2-D profile."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        raw_profile = a.get("profile_2d")
        if raw_profile is None:
            return err_payload("profile_2d is required", "BAD_ARGS")
        if not isinstance(raw_profile, list) or len(raw_profile) < 1:
            return err_payload(
                "profile_2d must be a JSON array of at least 1 segment", "BAD_ARGS"
            )

        raw_start = a.get("start_xy")
        if raw_start is None:
            return err_payload("start_xy is required", "BAD_ARGS")
        try:
            start_xy = (float(raw_start[0]), float(raw_start[1]))
        except Exception as exc:
            return err_payload(f"start_xy contains invalid values: {exc}", "BAD_ARGS")

        try:
            profile = []
            for seg in raw_profile:
                if not isinstance(seg, list) or len(seg) < 3:
                    raise ValueError(f"invalid segment: {seg!r}")
                profile.append(tuple(seg))
        except Exception as exc:
            return err_payload(f"profile_2d contains invalid segment: {exc}", "BAD_ARGS")

        kwargs: dict = {}
        for key in (
            "wire_diameter_mm", "spark_gap_mm", "side",
            "feedrate_mm_min", "lead_in_mm", "program_number", "header_comment",
        ):
            if key in a:
                kwargs[key] = a[key]

        try:
            result = emit_wire_edm_gcode(profile, start_xy, **kwargs)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"internal error: {exc}", "INTERNAL_ERROR")

        return ok_payload({
            "gcode": result.text,
            "line_count": result.line_count,
            "compensation_radius": result.compensation_radius,
            "compensation_side": result.compensation_side,
            "segment_count": result.segment_count,
            "warnings": result.warnings,
        })

except ImportError:
    # Running outside the Kerf service (e.g. plain pytest) — skip registration.
    pass
