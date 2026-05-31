"""
kerf_cam.lead_in_out — G-code lead-in / lead-out arc and line segments for
2D contour milling, avoiding witness marks at the cutter entry/exit points.

Reference standards
-------------------
* Machinery's Handbook 31e §1131 — Cutter entry strategies:
  - Arc tangent entry: the cutter approaches along an arc that is tangent to
    the contour at the entry point; eliminates the entry mark (witness) that a
    plunge or straight entry at an angle produces.
  - Recommended lead-in radius: 50–100 % of cutter radius for most 2D profiling
    operations; the arc sweeps from a stand-off point to the contour start point
    with a tangent join.
  - Lead-out (exit): mirror image of lead-in; exit arc departs tangent to the
    contour to avoid the step that occurs when the cutter leaves suddenly.

* Fanuc Operator Manual — G41/G42 Cutter Compensation:
  - G41: cutter compensation LEFT of programmed path (climb milling, outside
    profile when tool travels CCW around part in standard XY orientation).
  - G42: cutter compensation RIGHT of programmed path.
  - The first move after G41/G42 must NOT be zero-length; a lead-in segment
    satisfies this requirement and ramps the compensation register smoothly.
  - Cancel with G40.

Lead-in geometry (arc type)
---------------------------
Given:
  contour_start_xy  — point where the contour begins, P_c
  contour_tangent_xy — unit tangent direction at the contour start (pointing
                       into the contour direction of cut), t̂_c
  lead_radius_mm    — radius R of the lead-in arc
  lead_angle_deg    — the angle (degrees) between the outbound tangent of the
                      arc at the contour start and the contour tangent.
                      90° is the classic perpendicular arc entry (tangent arc).
                      0° means the arc entry is collinear with the tangent —
                      degenerate; must be > 0°.

For a 90° (perpendicular) arc entry:
  The centre of the lead-in arc is at P_c ± R × n̂_c
  (left offset for G41, right for G42), where n̂_c is the left-hand normal
  to t̂_c (rotate t̂_c by +90° CCW → n̂_c).

  The lead-in start point Q is diametrically opposite P_c relative to the
  centre C, i.e. Q = C − R × t̂_c  (90° back along the contour tangent gives
  a 90° arc sweep from Q → P_c, tangent at P_c to the contour).

For a general lead_angle_deg α (0 < α ≤ 90):
  The arc still ends tangent to the contour at P_c; the arc sweeps an angle of
  (90° + (90° − α)) = 180° − α  when α < 90°, but for practical CAM we keep
  the definition simple:

  Algorithm (follows MH 31e §1131, Smid §4):
    1. Compute the unit normal n̂ = rotate(t̂_c, +90°) for G41 (left comp) or
       n̂ = rotate(t̂_c, −90°) for G42.
    2. Centre of arc: C = P_c + R × n̂
    3. Arc start Q: rotate (P_c − C) by −lead_angle_deg (CW) around C, then
       Q = C + that rotated vector.
       For α=90° this gives Q = P_c − R × t̂_c (classic perpendicular entry).
    4. Arc: Q → P_c, radius R, centre C.
       Direction: G41 uses G03 (CCW); G42 uses G02 (CW).
       I/J offsets = C − Q (from the arc start point).
    5. Lead-out: mirror symmetry about the contour *end* point.  We reuse the
       same geometry but start at P_c and depart from the mirrored exit arc.
       Arc direction is reversed (lead-out departs the contour tangentially).

Line lead-in (lead_type="line")
--------------------------------
Start at P_c − lead_radius_mm × t̂_c (directly behind the contour start,
along the tangent direction).  Emit G01 to P_c.  Lead-in length = lead_radius_mm.
Cutter comp is activated before this move.

Perpendicular lead-in (lead_type="perpendicular")
--------------------------------------------------
Approach P_c from a point offset perpendicular to the tangent by lead_radius_mm.
Emit G01.  Equivalent to a line entry but at 90° to the contour.

Honest caveats
--------------
- **2D contours only** (XY plane, constant Z): 3D ramp entry and helical
  entry are not implemented.
- Lead-in geometry is computed in the XY plane; the caller is responsible for
  setting the correct Z depth before the lead-in begins.
- Cutter compensation (G41/G42) is activated by the emitted block; the
  caller must ensure the D-offset register is set beforehand (typically
  D = tool_radius in the controller's offset table).
- The lead-in arc assumes the contour tangent is the direction of cut.  If
  the tangent direction is reversed or the contour is closed and the sign is
  ambiguous, verify the direction before use.
- No gouge/collision checking is performed against the part geometry.
  Verify the lead-in path visually or via cam_verify_toolpath_collision.
- I/J arc offsets are relative to the arc start point (incremental arc centre
  vector), which is the Fanuc RS-274/NGC convention.  Some controllers use
  absolute I/J; set G91.1 or check controller docs.
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
# Constants
# ---------------------------------------------------------------------------

_VALID_LEAD_TYPES = frozenset({"arc", "line", "perpendicular"})
_VALID_CUTTER_COMP = frozenset({"G41", "G42"})

# Minimum lead angle to avoid a degenerate arc (< 1° treated as line).
_MIN_LEAD_ANGLE_DEG = 1.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LeadSpec:
    """Specification for a lead-in / lead-out segment pair.

    All distance parameters are in millimetres.  Angles are in degrees.

    Parameters
    ----------
    contour_start_xy   : (x, y) tuple — the point where the cutter enters
                         the contour (first on-part contact point).
    contour_tangent_xy : (tx, ty) tuple — the direction the cutter is moving
                         when it first touches the contour (does not need to
                         be unit-length; it is normalised internally).
    cutter_diameter_mm : Cutter diameter in mm (used for honest_caveat
                         commentary only; path offsets are NOT applied here
                         — use G41/G42 cutter compensation for that).
    lead_radius_mm     : Radius of the lead-in arc, or length of the lead-in
                         line segment, in mm.  MH 31e §1131: typically
                         50–100 % of cutter radius; must be > 0.
    lead_angle_deg     : Angle of the lead-in arc (degrees, 0 < angle ≤ 90).
                         90° = classic perpendicular tangent arc entry
                         (most common; recommended by MH 31e §1131).
                         Smaller values produce a shallower arc entry.
                         Ignored for "line" and "perpendicular" types.
    feed_mm_per_min    : Feed rate for the lead-in/lead-out moves (mm/min).
    lead_type          : "arc" | "line" | "perpendicular".
                         arc          — tangent arc entry/exit (MH 31e §1131).
                         line         — straight entry along contour tangent.
                         perpendicular — straight entry from the side
                                        (perpendicular to tangent).
    """
    contour_start_xy: tuple
    contour_tangent_xy: tuple
    cutter_diameter_mm: float
    lead_radius_mm: float
    lead_angle_deg: float
    feed_mm_per_min: float
    lead_type: str

    def __post_init__(self):
        if self.cutter_diameter_mm <= 0:
            raise ValueError(
                f"cutter_diameter_mm must be > 0, got {self.cutter_diameter_mm!r}"
            )
        if self.lead_radius_mm <= 0:
            raise ValueError(
                f"lead_radius_mm must be > 0, got {self.lead_radius_mm!r}"
            )
        if self.lead_type not in _VALID_LEAD_TYPES:
            raise ValueError(
                f"lead_type must be one of {sorted(_VALID_LEAD_TYPES)}, "
                f"got {self.lead_type!r}"
            )
        if self.feed_mm_per_min <= 0:
            raise ValueError(
                f"feed_mm_per_min must be > 0, got {self.feed_mm_per_min!r}"
            )
        tx, ty = self.contour_tangent_xy
        if math.hypot(tx, ty) < 1e-12:
            raise ValueError(
                "contour_tangent_xy must be a non-zero direction vector"
            )
        if self.lead_type == "arc":
            if not (_MIN_LEAD_ANGLE_DEG <= self.lead_angle_deg <= 90.0):
                raise ValueError(
                    f"lead_angle_deg must be in [{_MIN_LEAD_ANGLE_DEG}, 90] for arc type, "
                    f"got {self.lead_angle_deg!r}"
                )


@dataclass
class LeadResult:
    """Result from ``generate_lead_in_out``.

    Attributes
    ----------
    gcode_lead_in    : G-code block for the lead-in move (activates cutter
                       compensation, then arcs/lines to the contour start).
    gcode_lead_out   : G-code block for the lead-out move (arcs/lines away
                       from the contour end, then cancels cutter compensation).
    lead_in_length_mm  : Path length of the lead-in move in mm.
                         For arc: R × angle_rad.  For line: lead_radius_mm.
    lead_out_length_mm : Path length of the lead-out move in mm (same formula,
                         mirrored).
    honest_caveat    : Plain-English note on assumptions and limitations.
    """
    gcode_lead_in: str
    gcode_lead_out: str
    lead_in_length_mm: float
    lead_out_length_mm: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 4) -> str:
    """Format a float to NIST RS-274/NGC decimal notation (≥ 1 decimal place).

    RS-274/NGC §3.5.1: numbers may be integers or reals; the decimal point
    must be present for reals.  Uses 4 decimal places for mm values then strips
    trailing zeros, keeping at least one decimal place (e.g. "2.0000" → "2.0").
    """
    formatted = f"{v:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
        if "." not in formatted:
            formatted += ".0"
    return formatted


def _normalise(tx: float, ty: float) -> tuple:
    """Return the unit vector (ux, uy) of (tx, ty)."""
    mag = math.hypot(tx, ty)
    return tx / mag, ty / mag


def _rotate_90_ccw(vx: float, vy: float) -> tuple:
    """Rotate vector (vx, vy) by +90° CCW (left-hand normal)."""
    return -vy, vx


def _rotate_90_cw(vx: float, vy: float) -> tuple:
    """Rotate vector (vx, vy) by −90° CW (right-hand normal)."""
    return vy, -vx


def _rotate_deg(vx: float, vy: float, angle_deg: float) -> tuple:
    """Rotate vector (vx, vy) by angle_deg CCW."""
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return vx * cos_a - vy * sin_a, vx * sin_a + vy * cos_a


def _arc_ij(start_x: float, start_y: float,
             centre_x: float, centre_y: float) -> tuple:
    """Return I, J = arc centre offset from arc start (Fanuc incremental convention).

    Fanuc RS-274/NGC §3.5.3 / Fanuc 0i OM §4.3:
      I = (centre_x - start_x)
      J = (centre_y - start_y)
    """
    return centre_x - start_x, centre_y - start_y


def _arc_length(radius_mm: float, angle_deg: float) -> float:
    """Return arc length = R × |θ| in mm (angle in degrees)."""
    return radius_mm * abs(math.radians(angle_deg))


def _compute_arc_lead_in(
    spec: LeadSpec,
    cutter_comp: str,
) -> tuple:
    """Compute arc lead-in geometry.

    Returns
    -------
    (start_x, start_y, centre_x, centre_y, arc_code, sweep_deg, lead_in_length)

    arc_code : "G02" or "G03" (direction of the lead-in arc)
    sweep_deg : the angular sweep of the lead-in arc (positive value, degrees)
    """
    px, py = spec.contour_start_xy
    tx, ty = _normalise(*spec.contour_tangent_xy)
    R = spec.lead_radius_mm
    alpha = spec.lead_angle_deg  # degrees, 0 < alpha <= 90

    # Normal offset direction depends on cutter compensation side:
    #   G41 (left of path) → arc centre is to the LEFT of the tangent (+90° CCW)
    #   G42 (right of path) → arc centre is to the RIGHT of the tangent (−90° CW)
    if cutter_comp == "G41":
        # Centre to the left of tangent (standard MH 31e §1131 arc entry)
        nx, ny = _rotate_90_ccw(tx, ty)
    else:
        # G42: centre to the right
        nx, ny = _rotate_90_cw(tx, ty)

    # Arc centre: C = P_c + R * n̂
    cx = px + R * nx
    cy = py + R * ny

    # Arc start Q: rotate the vector (P_c - C) by -alpha (CW) around C.
    # (P_c - C) = -R * n̂  → a unit vector pointing from C back to P_c.
    # Rotating by -alpha gives us the start point of the lead-in arc.
    # For G41 we rotate CCW by alpha (negative angle = CW), then Q = C + rotated vector.
    # For G42 we rotate CW by alpha.
    pc_minus_c_x = px - cx   # = -R * nx
    pc_minus_c_y = py - cy   # = -R * ny

    if cutter_comp == "G41":
        # Rotate PCc vector by +alpha CCW to get start point offset from C
        rot_x, rot_y = _rotate_deg(pc_minus_c_x, pc_minus_c_y, alpha)
    else:
        # G42: rotate by -alpha
        rot_x, rot_y = _rotate_deg(pc_minus_c_x, pc_minus_c_y, -alpha)

    qx = cx + rot_x
    qy = cy + rot_y

    # I/J = arc centre offset from arc start point Q
    i_val, j_val = _arc_ij(qx, qy, cx, cy)

    # Arc direction:
    #   G41: CCW arc (G03) — tool arc sweeps left around centre
    #   G42: CW arc (G02) — tool arc sweeps right
    # This keeps the arc tangent to the contour tangent at P_c.
    arc_code = "G03" if cutter_comp == "G41" else "G02"

    # Arc sweep angle = alpha degrees (the angle we rotated from P_c back to Q)
    sweep_deg = abs(alpha)
    lead_in_length = _arc_length(R, sweep_deg)

    return qx, qy, cx, cy, i_val, j_val, arc_code, sweep_deg, lead_in_length


def _compute_arc_lead_out(
    spec: LeadSpec,
    cutter_comp: str,
) -> tuple:
    """Compute arc lead-out geometry (mirror of lead-in about the contour end).

    The lead-out arc starts at the contour end point (same as contour_start_xy
    for closed contours, or use the same start for an open-contour exit estimate)
    and departs tangentially.

    Returns
    -------
    (end_x, end_y, centre_x, centre_y, i_val, j_val, arc_code, sweep_deg, lead_out_length)
    """
    px, py = spec.contour_start_xy
    tx, ty = _normalise(*spec.contour_tangent_xy)
    R = spec.lead_radius_mm
    alpha = spec.lead_angle_deg

    # For lead-out: the cutter leaves P_c tangentially.
    # Centre offset is the same side as lead-in.
    if cutter_comp == "G41":
        nx, ny = _rotate_90_ccw(tx, ty)
    else:
        nx, ny = _rotate_90_cw(tx, ty)

    cx = px + R * nx
    cy = py + R * ny

    # Lead-out end point: rotate (P_c - C) by -alpha (for G41) to get exit point.
    pc_minus_c_x = px - cx
    pc_minus_c_y = py - cy

    if cutter_comp == "G41":
        rot_x, rot_y = _rotate_deg(pc_minus_c_x, pc_minus_c_y, -alpha)
    else:
        rot_x, rot_y = _rotate_deg(pc_minus_c_x, pc_minus_c_y, alpha)

    ex = cx + rot_x
    ey = cy + rot_y

    # I/J from arc start (P_c) to centre
    i_val, j_val = _arc_ij(px, py, cx, cy)

    # Arc direction for lead-out is reversed vs lead-in
    arc_code = "G02" if cutter_comp == "G41" else "G03"

    sweep_deg = abs(alpha)
    lead_out_length = _arc_length(R, sweep_deg)

    return ex, ey, cx, cy, i_val, j_val, arc_code, sweep_deg, lead_out_length


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_lead_in_out(
    spec: LeadSpec,
    cutter_comp: str = "G41",
) -> LeadResult:
    """Generate G-code lead-in / lead-out blocks for 2D contour milling.

    The lead-in block:
      1. Activates cutter compensation (G41 or G42 with D word).
      2. Moves (arc or line) from a stand-off point to the contour start.

    The lead-out block:
      1. Moves (arc or line) away from the contour end point.
      2. Cancels cutter compensation (G40).

    Parameters
    ----------
    spec         : LeadSpec — contour entry geometry, cutter size, lead type.
    cutter_comp  : "G41" (left of motion, default) or "G42" (right of motion).
                   Per Fanuc §G41/G42: G41 is used for climb milling on an
                   outside profile; G42 for conventional or inside profiles.

    Returns
    -------
    LeadResult

    Raises
    ------
    ValueError if cutter_comp is not "G41" or "G42".
    """
    if cutter_comp not in _VALID_CUTTER_COMP:
        raise ValueError(
            f"cutter_comp must be 'G41' or 'G42', got {cutter_comp!r}"
        )

    px, py = spec.contour_start_xy
    tx, ty = _normalise(*spec.contour_tangent_xy)
    R = spec.lead_radius_mm
    F = spec.feed_mm_per_min

    if spec.lead_type == "arc":
        (qx, qy, cx, cy, i_val, j_val,
         arc_in_code, sweep_deg, lead_in_length) = _compute_arc_lead_in(spec, cutter_comp)

        (ex, ey, ocx, ocy, oi_val, oj_val,
         arc_out_code, osweep_deg, lead_out_length) = _compute_arc_lead_out(spec, cutter_comp)

        # Lead-in G-code block
        lead_in_lines = [
            f"(Lead-in arc — MH 31e §1131; R={_fmt(R)} mm; α={_fmt(spec.lead_angle_deg)}°; {cutter_comp})",
            f"G00 X{_fmt(qx)} Y{_fmt(qy)}  (rapid to lead-in start)",
            f"{cutter_comp} D  (activate cutter compensation — set D=tool_radius in offset table)",
            (
                f"{arc_in_code} X{_fmt(px)} Y{_fmt(py)}"
                f" I{_fmt(i_val)} J{_fmt(j_val)}"
                f" F{_fmt(F)}"
                f"  (lead-in arc sweep {_fmt(sweep_deg)}° → contour start)"
            ),
        ]

        # Lead-out G-code block
        lead_out_lines = [
            f"(Lead-out arc — MH 31e §1131; R={_fmt(R)} mm; α={_fmt(spec.lead_angle_deg)}°)",
            (
                f"{arc_out_code} X{_fmt(ex)} Y{_fmt(ey)}"
                f" I{_fmt(oi_val)} J{_fmt(oj_val)}"
                f" F{_fmt(F)}"
                f"  (lead-out arc sweep {_fmt(osweep_deg)}°)"
            ),
            "G40  (cancel cutter compensation)",
            f"G00 X{_fmt(ex)} Y{_fmt(ey)}  (rapid clear)",
        ]

    elif spec.lead_type == "line":
        # Straight line along the tangent direction, entering from behind
        sx = px - R * tx
        sy = py - R * ty

        lead_in_length = R
        lead_out_length = R

        # Lead-out end: continue along tangent
        lox = px + R * tx
        loy = py + R * ty

        lead_in_lines = [
            f"(Lead-in line — along contour tangent; length={_fmt(R)} mm; {cutter_comp})",
            f"G00 X{_fmt(sx)} Y{_fmt(sy)}  (rapid to lead-in start)",
            f"{cutter_comp} D  (activate cutter compensation)",
            f"G01 X{_fmt(px)} Y{_fmt(py)} F{_fmt(F)}  (lead-in line → contour start)",
        ]

        lead_out_lines = [
            f"(Lead-out line — along contour tangent; length={_fmt(R)} mm)",
            f"G01 X{_fmt(lox)} Y{_fmt(loy)} F{_fmt(F)}  (lead-out line)",
            "G40  (cancel cutter compensation)",
        ]

    else:  # "perpendicular"
        # Approach from the side: perpendicular to the tangent (from the
        # same side as cutter_comp dictates).
        if cutter_comp == "G41":
            nx, ny = _rotate_90_ccw(tx, ty)
        else:
            nx, ny = _rotate_90_cw(tx, ty)

        sx = px + R * nx
        sy = py + R * ny

        lead_in_length = R
        lead_out_length = R

        # Lead-out: depart in the opposite normal direction
        lox = px - R * nx
        loy = py - R * ny

        lead_in_lines = [
            f"(Lead-in perpendicular — 90° to contour tangent; length={_fmt(R)} mm; {cutter_comp})",
            f"G00 X{_fmt(sx)} Y{_fmt(sy)}  (rapid to lead-in start)",
            f"{cutter_comp} D  (activate cutter compensation)",
            f"G01 X{_fmt(px)} Y{_fmt(py)} F{_fmt(F)}  (perpendicular lead-in → contour start)",
        ]

        lead_out_lines = [
            f"(Lead-out perpendicular — 90° from contour tangent; length={_fmt(R)} mm)",
            f"G01 X{_fmt(lox)} Y{_fmt(loy)} F{_fmt(F)}  (perpendicular lead-out)",
            "G40  (cancel cutter compensation)",
        ]

    caveat = (
        "2D contours only (XY plane, constant Z): 3D ramp entry and helical entry "
        "are NOT implemented. "
        "Cutter compensation (G41/G42) is activated in the lead-in block; "
        "ensure the D-offset register (D = tool_radius) is set in the controller "
        "offset table before execution. "
        "I/J offsets are relative to the arc start point (Fanuc RS-274/NGC "
        "incremental arc centre convention); check controller docs if using "
        "absolute arc centre mode (G91.1). "
        "No gouge or collision checking is performed — verify path visually or "
        "via cam_verify_toolpath_collision before running on the machine. "
        f"Lead-in arc direction: {'G03 (CCW) for G41' if cutter_comp == 'G41' else 'G02 (CW) for G42'}. "
        "Refs: MH 31e §1131; Fanuc Operator Manual §G41/G42."
    )

    return LeadResult(
        gcode_lead_in="\n".join(lead_in_lines),
        gcode_lead_out="\n".join(lead_out_lines),
        lead_in_length_mm=round(lead_in_length, 6),
        lead_out_length_mm=round(lead_out_length, 6),
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_lead_in_out_spec = ToolSpec(
    name="cam_generate_lead_in_out",
    description=(
        "Generate G-code lead-in and lead-out arc or line segments for 2D contour "
        "milling, avoiding witness marks at the cutter entry/exit points. "
        "Follows MH 31e §1131 (cutter entry strategies) and Fanuc §G41/G42 cutter "
        "compensation. "
        "Supports three lead types: 'arc' (tangent-arc entry, most common), "
        "'line' (straight entry along contour tangent), and 'perpendicular' "
        "(straight entry 90° to tangent). "
        "Emits G02/G03 arc blocks with I/J offsets and G41/G42 cutter compensation. "
        "Returns lead-in and lead-out G-code blocks, path lengths, and honest "
        "caveats (2D only; no gouge check; I/J are incremental/Fanuc convention)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "contour_start_xy": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": (
                    "[x, y] — the XY point where the cutter first touches the "
                    "contour (contour entry point, mm)."
                ),
            },
            "contour_tangent_xy": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": (
                    "[tx, ty] — direction vector of the contour at the entry "
                    "point (direction of cut; normalised internally)."
                ),
            },
            "cutter_diameter_mm": {
                "type": "number",
                "description": "Cutter diameter in mm (used for commentary only; path offsets use G41/G42).",
            },
            "lead_radius_mm": {
                "type": "number",
                "description": (
                    "Radius of the lead-in arc, or length of the lead-in line, "
                    "in mm.  MH 31e §1131: typically 50–100 % of cutter radius."
                ),
            },
            "lead_angle_deg": {
                "type": "number",
                "description": (
                    "Arc sweep angle in degrees (1–90).  90° = classic perpendicular "
                    "tangent arc entry (recommended).  Ignored for 'line' and "
                    "'perpendicular' types."
                ),
            },
            "feed_mm_per_min": {
                "type": "number",
                "description": "Feed rate for lead-in and lead-out moves (mm/min).",
            },
            "lead_type": {
                "type": "string",
                "enum": ["arc", "line", "perpendicular"],
                "description": (
                    "'arc' — tangent arc entry/exit (MH 31e §1131, recommended). "
                    "'line' — straight entry along contour tangent. "
                    "'perpendicular' — straight entry 90° to tangent."
                ),
            },
            "cutter_comp": {
                "type": "string",
                "enum": ["G41", "G42"],
                "description": (
                    "G41 = cutter compensation LEFT of programmed path "
                    "(climb milling, outside profile). "
                    "G42 = RIGHT of path (conventional or inside profile). "
                    "Default: G41."
                ),
            },
        },
        "required": [
            "contour_start_xy",
            "contour_tangent_xy",
            "cutter_diameter_mm",
            "lead_radius_mm",
            "lead_angle_deg",
            "feed_mm_per_min",
            "lead_type",
        ],
    },
)


@register(cam_generate_lead_in_out_spec)
async def run_cam_generate_lead_in_out(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        cxy = a["contour_start_xy"]
        txy = a["contour_tangent_xy"]
        spec = LeadSpec(
            contour_start_xy=(float(cxy[0]), float(cxy[1])),
            contour_tangent_xy=(float(txy[0]), float(txy[1])),
            cutter_diameter_mm=float(a["cutter_diameter_mm"]),
            lead_radius_mm=float(a["lead_radius_mm"]),
            lead_angle_deg=float(a["lead_angle_deg"]),
            feed_mm_per_min=float(a["feed_mm_per_min"]),
            lead_type=str(a["lead_type"]),
        )
        cutter_comp = str(a.get("cutter_comp", "G41"))
        result = generate_lead_in_out(spec, cutter_comp=cutter_comp)
    except (KeyError, IndexError, TypeError) as e:
        return err_payload(f"missing or invalid field: {e}", "BAD_ARGS")
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "gcode_lead_in": result.gcode_lead_in,
        "gcode_lead_out": result.gcode_lead_out,
        "lead_in_length_mm": result.lead_in_length_mm,
        "lead_out_length_mm": result.lead_out_length_mm,
        "honest_caveat": result.honest_caveat,
    })
