"""
kerf_cam.lead_in_out — G-code lead-in / lead-out arc and line segments for
2D contour milling, avoiding witness marks at the cutter entry/exit points.
Also provides 3D entry types: helical-ramp (spiral descent), ramp-on (linear
angled descent), and arc-tangent (arc tangent to both surface and first cut
direction).

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

* Machinery's Handbook 31e §1109 — Helical interpolation entry (helical ramp):
  - Helical lead-in: the cutter spirals down at a constant pitch angle (typically
    2–5° for aluminium, 1–3° for steel; must not exceed chip-load or side-load
    limits). The helix axis is centred on a clearance circle of radius
    lead_radius_mm; one or more full revolutions bring the cutter to depth.
  - Ramp-on entry: linear Z-descent across the XY lead-in segment at a fixed
    plunge angle (ramp_angle_deg, typically 3–7°, max 15° for hard materials).
    The ramp length is lead_radius_mm / tan(ramp_angle_deg).

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

Helical-ramp lead-in (lead_type="helical-ramp")
------------------------------------------------
The cutter spirals downward at a constant pitch angle onto the XY plane of the
contour.  Parameters: lead_radius_mm = helix radius; ramp_angle_deg = pitch
angle in degrees (default 3°); num_helix_turns = number of full revolutions
(default 1).  The helix centre is offset from P_c perpendicular to the tangent
(same side as cutter compensation).  Each revolution is sampled into
helix_points (default 36) linear G01 segments approximating the helix.
Z descends from (target_z_mm + pitch_per_turn) to target_z_mm over one
revolution.  Returns a list of (x, y, z) toolpath points.  The lead-out is a
simple retract back up the helix axis (reversed).

MH 31e §1109: pitch angle 2–5° aluminium, 1–3° steel; max 15° hard materials.
Pitch per turn = 2π × R × tan(ramp_angle_deg).

Ramp-on lead-in (lead_type="ramp-on")
--------------------------------------
Linear Z-descent across a straight XY lead-in segment at a fixed plunge angle
(ramp_angle_deg, default 5°).  Ramp length in XY =
target_depth_mm / tan(ramp_angle_deg).  The ramp starts at clearance height
(target_z_mm + target_depth_mm) and descends to target_z_mm.  The XY segment
starts behind P_c along the negative tangent direction by the ramp length.
Returns a list of (x, y, z) toolpath points.  Lead-out is the mirror: ramp up
along the positive tangent direction.

Arc-tangent lead-in (lead_type="arc-tangent")
---------------------------------------------
Arc tangent to both the surface (the tool approaches perpendicular to the XY
plane, so the arc must be tangent at 90° to the plunge axis) and to the first
cut direction (the arc exits tangent to the contour tangent).  This is the
classic MH 31e §1131 "tangent arc entry" in 2D with explicit geometry points
returned as a list of (x, y) arc samples plus the arc centre and radius.
Equivalent to lead_type="arc" at lead_angle_deg=90° but exposes the arc
geometry (centre, radius, start, end) as structured output rather than G-code
strings.  The returned toolpath points trace the arc from the start point to
the contour start.  Lead-out is the reverse arc.

Honest caveats
--------------
- Lead-in geometry is computed in the XY plane; the caller is responsible for
  setting the correct Z depth before the 2D lead-in begins.
- For "helical-ramp" and "ramp-on": 3D toolpath points are returned; Z values
  assume a flat XY contour at target_z_mm (specified in the spec).
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

_VALID_LEAD_TYPES = frozenset({"arc", "line", "perpendicular", "helical-ramp", "ramp-on", "arc-tangent"})
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
                         For "helical-ramp": helix radius.
    lead_angle_deg     : Angle of the lead-in arc (degrees, 0 < angle ≤ 90).
                         90° = classic perpendicular tangent arc entry
                         (most common; recommended by MH 31e §1131).
                         Smaller values produce a shallower arc entry.
                         Ignored for "line" and "perpendicular" types.
                         For "helical-ramp" and "ramp-on": the pitch/plunge
                         angle in degrees (typically 3–7°; default 3.0°).
    feed_mm_per_min    : Feed rate for the lead-in/lead-out moves (mm/min).
    lead_type          : "arc" | "line" | "perpendicular" |
                         "helical-ramp" | "ramp-on" | "arc-tangent".
                         arc          — tangent arc entry/exit (MH 31e §1131).
                         line         — straight entry along contour tangent.
                         perpendicular — straight entry from the side
                                        (perpendicular to tangent).
                         helical-ramp  — spiral descent at constant pitch angle
                                        to target Z (MH 31e §1109).
                         ramp-on       — linear Z descent at fixed plunge angle
                                        toward first cut point.
                         arc-tangent   — arc tangent to both surface (90°) and
                                        first cut direction; returns structured
                                        arc geometry as toolpath points.
    target_z_mm        : Z depth of the contour plane (mm).  Required for
                         "helical-ramp" and "ramp-on" types (ignored otherwise;
                         default 0.0).
    ramp_angle_deg     : Pitch/plunge angle for "helical-ramp" and "ramp-on"
                         (degrees, 0 < angle ≤ 45; default 3.0°).
                         Overrides lead_angle_deg for those types when provided.
                         For "helical-ramp": helix pitch angle (MH 31e §1109
                         recommends 2–5° Al, 1–3° steel).
                         For "ramp-on": linear plunge angle (typically 5°).
    num_helix_turns    : Number of full helix revolutions for "helical-ramp"
                         (default 1; must be ≥ 1).
    helix_points_per_turn : Number of linear G01 segments per helix revolution
                         (default 36; must be ≥ 4).
    arc_points         : Number of sample points along the arc for "arc-tangent"
                         toolpath output (default 32; must be ≥ 4).
    """
    contour_start_xy: tuple
    contour_tangent_xy: tuple
    cutter_diameter_mm: float
    lead_radius_mm: float
    lead_angle_deg: float
    feed_mm_per_min: float
    lead_type: str
    target_z_mm: float = 0.0
    ramp_angle_deg: float = 3.0
    num_helix_turns: int = 1
    helix_points_per_turn: int = 36
    arc_points: int = 32

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
        if self.lead_type in ("helical-ramp", "ramp-on"):
            if not (0 < self.ramp_angle_deg <= 45.0):
                raise ValueError(
                    f"ramp_angle_deg must be in (0, 45] for {self.lead_type!r}, "
                    f"got {self.ramp_angle_deg!r}"
                )
        if self.lead_type == "helical-ramp":
            if self.num_helix_turns < 1:
                raise ValueError(
                    f"num_helix_turns must be >= 1, got {self.num_helix_turns!r}"
                )
            if self.helix_points_per_turn < 4:
                raise ValueError(
                    f"helix_points_per_turn must be >= 4, got {self.helix_points_per_turn!r}"
                )
        if self.lead_type == "arc-tangent":
            if self.arc_points < 4:
                raise ValueError(
                    f"arc_points must be >= 4, got {self.arc_points!r}"
                )


@dataclass
class LeadResult:
    """Result from ``generate_lead_in_out``.

    Attributes
    ----------
    gcode_lead_in    : G-code block for the lead-in move (activates cutter
                       compensation, then arcs/lines to the contour start).
                       For "helical-ramp", "ramp-on", and "arc-tangent" types
                       this is a descriptive comment block; use
                       lead_in_toolpath_points for the actual geometry.
    gcode_lead_out   : G-code block for the lead-out move (arcs/lines away
                       from the contour end, then cancels cutter compensation).
    lead_in_length_mm  : Path length of the lead-in move in mm.
                         For arc: R × angle_rad.  For line: lead_radius_mm.
                         For helical-ramp: helix arc length (2π × R × turns /
                         cos(pitch_angle)).  For ramp-on: ramp XY distance /
                         cos(angle).  For arc-tangent: R × pi/2.
    lead_out_length_mm : Path length of the lead-out move in mm (same formula,
                         mirrored).
    honest_caveat    : Plain-English note on assumptions and limitations.
    lead_in_toolpath_points  : List of (x, y) or (x, y, z) tuples tracing the
                               lead-in path (populated for all types; 2-tuples
                               for 2D types, 3-tuples for 3D types).
    lead_out_toolpath_points : List of (x, y) or (x, y, z) tuples tracing the
                               lead-out path.
    arc_centre_xy    : (cx, cy) arc centre for "arc" and "arc-tangent" types;
                       None for other types.
    arc_radius_mm    : Arc radius for "arc" and "arc-tangent" types; None
                       otherwise.
    """
    gcode_lead_in: str
    gcode_lead_out: str
    lead_in_length_mm: float
    lead_out_length_mm: float
    honest_caveat: str
    lead_in_toolpath_points: list = None
    lead_out_toolpath_points: list = None
    arc_centre_xy: tuple = None
    arc_radius_mm: float = None

    def __post_init__(self):
        if self.lead_in_toolpath_points is None:
            self.lead_in_toolpath_points = []
        if self.lead_out_toolpath_points is None:
            self.lead_out_toolpath_points = []


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


# ---------------------------------------------------------------------------
# 3D lead-in geometry helpers
# ---------------------------------------------------------------------------

def compute_helical_ramp_points(
    spec: LeadSpec,
    cutter_comp: str,
) -> tuple:
    """Compute toolpath points for a helical-ramp lead-in.

    The helix axis is centred offset from the contour start point, perpendicular
    to the contour tangent (same side as cutter_comp).  The cutter spirals down
    from (target_z_mm + pitch_per_turn * num_helix_turns) to target_z_mm over
    num_helix_turns full revolutions.

    Algorithm (MH 31e §1109 helical interpolation entry):
      pitch_per_turn = 2π × R × tan(ramp_angle_deg)
      For each turn t in [0, num_helix_turns]:
        For each sample s in [0, helix_points_per_turn]:
          θ = 2π × (t + s/helix_points_per_turn)
          x = cx + R × cos(θ_start + θ × direction)
          y = cy + R × sin(θ_start + θ × direction)
          z = z_start - pitch_per_turn × (t + s/helix_points_per_turn)

    Returns
    -------
    (lead_in_pts, lead_out_pts, centre_xy, helix_length_mm)

    lead_in_pts  : list of (x, y, z) tuples — helical descent
    lead_out_pts : list of (x, y, z) tuples — reversed (ascent)
    centre_xy    : (cx, cy) helix centre
    helix_length_mm : arc length of the helix (chord approximation)
    """
    px, py = spec.contour_start_xy
    tx, ty = _normalise(*spec.contour_tangent_xy)
    R = spec.lead_radius_mm
    z_target = spec.target_z_mm
    pitch_angle_rad = math.radians(spec.ramp_angle_deg)
    n_turns = spec.num_helix_turns
    n_pts = spec.helix_points_per_turn

    # Pitch per full revolution: p = 2π × R × tan(α)
    pitch_per_turn = 2.0 * math.pi * R * math.tan(pitch_angle_rad)
    z_start = z_target + pitch_per_turn * n_turns

    # Helix centre: offset from P_c perpendicular to tangent (same side as comp)
    if cutter_comp == "G41":
        nx, ny = _rotate_90_ccw(tx, ty)
    else:
        nx, ny = _rotate_90_cw(tx, ty)
    cx = px + R * nx
    cy = py + R * ny

    # θ at the contour start: angle from centre to P_c
    theta_end = math.atan2(py - cy, px - cx)

    # Helix direction: G41 → CCW (positive θ direction = +1); G42 → CW (−1)
    direction = 1 if cutter_comp == "G41" else -1

    # θ at helix start (before the descent begins)
    total_angle = 2.0 * math.pi * n_turns
    theta_start = theta_end - direction * total_angle

    total_samples = n_turns * n_pts
    pts: list = []
    for i in range(total_samples + 1):
        frac = i / total_samples
        theta = theta_start + direction * total_angle * frac
        x = cx + R * math.cos(theta)
        y = cy + R * math.sin(theta)
        z = z_start - pitch_per_turn * n_turns * frac
        pts.append((x, y, z))

    # Helix arc length: √((2πR)² + p²) per turn × num_turns
    helix_length_mm = (
        math.hypot(2.0 * math.pi * R, pitch_per_turn) * n_turns
    )

    lead_out_pts = list(reversed(pts))
    return pts, lead_out_pts, (cx, cy), helix_length_mm


def compute_ramp_on_points(
    spec: LeadSpec,
) -> tuple:
    """Compute toolpath points for a linear ramp-on lead-in.

    The cutter descends linearly from (P_start_xy, z_clearance) to
    (P_c, target_z_mm) along the negative contour tangent direction.

    Algorithm (MH 31e §1109 ramp entry):
      ramp_length_xy = target_depth / tan(ramp_angle_deg)
        where target_depth = z_clearance − target_z_mm
        and z_clearance = target_z_mm + target_depth
      P_start = P_c − ramp_length_xy × t̂_c
      Z descends linearly from z_clearance to target_z_mm.

    The target_depth is computed from the spec: it is lead_radius_mm
    (reused as the desired depth of cut for the ramp — the caller sets
    lead_radius_mm to the axial depth, and ramp_angle_deg to the plunge angle;
    the XY ramp length follows automatically).

    Returns
    -------
    (lead_in_pts, lead_out_pts, ramp_xy_length_mm, ramp_3d_length_mm)

    lead_in_pts  : list of (x, y, z) tuples
    lead_out_pts : list of (x, y, z) tuples (ramp up along +tangent direction)
    ramp_xy_length_mm : horizontal length of the ramp
    ramp_3d_length_mm : total 3D path length = ramp_xy / cos(angle)
    """
    px, py = spec.contour_start_xy
    tx, ty = _normalise(*spec.contour_tangent_xy)
    target_depth = spec.lead_radius_mm  # axial depth to ramp through
    z_target = spec.target_z_mm
    angle_rad = math.radians(spec.ramp_angle_deg)

    # Horizontal distance: L_xy = depth / tan(α)
    ramp_xy_length = target_depth / math.tan(angle_rad)

    # Start point: behind P_c along negative tangent
    sx = px - ramp_xy_length * tx
    sy = py - ramp_xy_length * ty
    z_start = z_target + target_depth

    lead_in_pts = [(sx, sy, z_start), (px, py, z_target)]

    # Lead-out: ramp up along +tangent from P_c
    lox = px + ramp_xy_length * tx
    loy = py + ramp_xy_length * ty
    lead_out_pts = [(px, py, z_target), (lox, loy, z_start)]

    ramp_3d_length = ramp_xy_length / math.cos(angle_rad)
    return lead_in_pts, lead_out_pts, ramp_xy_length, ramp_3d_length


def compute_arc_tangent_points(
    spec: LeadSpec,
    cutter_comp: str,
) -> tuple:
    """Compute toolpath points for an arc-tangent lead-in (2D).

    This is the classic MH 31e §1131 90° tangent arc entry, exposing structured
    arc geometry: centre (cx, cy), radius R, and sampled (x, y) toolpath points
    tracing the arc from the lead-in start to the contour start.

    The arc is tangent to the contour at the contour start point (contour_start_xy)
    and the lead-in start is positioned such that the arc is a 90° sweep.

    Algorithm:
      1. Centre C = P_c + R × n̂  (perpendicular offset, same side as cutter_comp)
      2. Arc start Q = C − R × t̂_c  (90° back along tangent from P_c)
      3. Sample n_pts evenly along the arc Q → P_c.

    Returns
    -------
    (lead_in_pts, lead_out_pts, centre_xy, radius_mm, arc_length_mm)

    lead_in_pts  : list of (x, y) tuples from Q to P_c
    lead_out_pts : list of (x, y) tuples from P_c to Q (reversed)
    centre_xy    : (cx, cy) arc centre
    radius_mm    : arc radius
    arc_length_mm : R × π/2 (90° arc)
    """
    px, py = spec.contour_start_xy
    tx, ty = _normalise(*spec.contour_tangent_xy)
    R = spec.lead_radius_mm
    n_pts = spec.arc_points

    if cutter_comp == "G41":
        nx, ny = _rotate_90_ccw(tx, ty)
    else:
        nx, ny = _rotate_90_cw(tx, ty)

    # Arc centre
    cx = px + R * nx
    cy = py + R * ny

    # Arc start Q (90° back along negative tangent from C)
    qx = cx - R * tx
    qy = cy - R * ty

    # Sample the arc from Q to P_c
    theta_start = math.atan2(qy - cy, qx - cx)
    theta_end = math.atan2(py - cy, px - cx)

    # Determine sweep direction: G41 → CCW (+θ), G42 → CW (−θ)
    if cutter_comp == "G41":
        # CCW: normalise delta to (0, 2π]
        delta = theta_end - theta_start
        while delta <= 0:
            delta += 2.0 * math.pi
        while delta > 2.0 * math.pi:
            delta -= 2.0 * math.pi
    else:
        # CW: normalise delta to [-2π, 0)
        delta = theta_end - theta_start
        while delta >= 0:
            delta -= 2.0 * math.pi
        while delta < -2.0 * math.pi:
            delta += 2.0 * math.pi

    pts: list = []
    for i in range(n_pts + 1):
        frac = i / n_pts
        theta = theta_start + delta * frac
        x = cx + R * math.cos(theta)
        y = cy + R * math.sin(theta)
        pts.append((x, y))

    arc_length_mm = R * abs(delta)
    lead_out_pts = list(reversed(pts))
    return pts, lead_out_pts, (cx, cy), R, arc_length_mm


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

        lead_in_toolpath_pts = [(qx, qy), (px, py)]
        lead_out_toolpath_pts = [(px, py), (ex, ey)]
        arc_centre = (cx, cy)
        arc_radius = R

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

        lead_in_toolpath_pts = [(sx, sy), (px, py)]
        lead_out_toolpath_pts = [(px, py), (lox, loy)]
        arc_centre = None
        arc_radius = None

    elif spec.lead_type == "perpendicular":
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

        lead_in_toolpath_pts = [(sx, sy), (px, py)]
        lead_out_toolpath_pts = [(px, py), (lox, loy)]
        arc_centre = None
        arc_radius = None

    elif spec.lead_type == "helical-ramp":
        # Helical-ramp: spiral descent at constant pitch angle to target Z.
        # MH 31e §1109.
        (lead_in_toolpath_pts, lead_out_toolpath_pts,
         arc_centre, helix_length) = compute_helical_ramp_points(spec, cutter_comp)
        arc_radius = spec.lead_radius_mm
        lead_in_length = helix_length
        lead_out_length = helix_length

        pitch_per_turn = (
            2.0 * math.pi * R * math.tan(math.radians(spec.ramp_angle_deg))
        )
        z_start = spec.target_z_mm + pitch_per_turn * spec.num_helix_turns

        lead_in_lines = [
            f"(Lead-in helical-ramp — MH 31e §1109; R={_fmt(R)} mm; "
            f"pitch_angle={_fmt(spec.ramp_angle_deg)}°; "
            f"turns={spec.num_helix_turns}; "
            f"pitch_per_turn={_fmt(pitch_per_turn)} mm; "
            f"Z_start={_fmt(z_start)} → Z_target={_fmt(spec.target_z_mm)}; {cutter_comp})",
            f"(Use lead_in_toolpath_points for actual G01 segments)",
            f"{cutter_comp} D  (activate cutter compensation)",
        ]
        lead_out_lines = [
            f"(Lead-out helical-ramp — reverse helix ascent; R={_fmt(R)} mm)",
            f"(Use lead_out_toolpath_points for actual G01 segments)",
            "G40  (cancel cutter compensation)",
        ]

    elif spec.lead_type == "ramp-on":
        # Ramp-on: linear Z descent at fixed plunge angle toward first cut point.
        # MH 31e §1109.
        (lead_in_toolpath_pts, lead_out_toolpath_pts,
         ramp_xy_length, ramp_3d_length) = compute_ramp_on_points(spec)
        arc_centre = None
        arc_radius = None
        lead_in_length = ramp_3d_length
        lead_out_length = ramp_3d_length

        sx, sy, z_s = lead_in_toolpath_pts[0]
        lead_in_lines = [
            f"(Lead-in ramp-on — MH 31e §1109; depth={_fmt(R)} mm; "
            f"angle={_fmt(spec.ramp_angle_deg)}°; "
            f"XY_length={_fmt(ramp_xy_length)} mm; "
            f"Z_start={_fmt(z_s)} → Z_target={_fmt(spec.target_z_mm)}; {cutter_comp})",
            f"G00 X{_fmt(sx)} Y{_fmt(sy)}  (rapid to ramp start)",
            f"{cutter_comp} D  (activate cutter compensation)",
            f"G01 X{_fmt(px)} Y{_fmt(py)} Z{_fmt(spec.target_z_mm)} F{_fmt(F)}"
            f"  (ramp descent → contour start)",
        ]
        lox, loy, loz = lead_out_toolpath_pts[-1]
        lead_out_lines = [
            f"(Lead-out ramp-on — ramp ascent along +tangent; angle={_fmt(spec.ramp_angle_deg)}°)",
            f"G01 X{_fmt(lox)} Y{_fmt(loy)} Z{_fmt(loz)} F{_fmt(F)}  (ramp ascent)",
            "G40  (cancel cutter compensation)",
        ]

    else:  # "arc-tangent"
        # Arc-tangent: 2D arc tangent to both surface (90° to plunge axis) and
        # first cut direction. MH 31e §1131.  Returns structured geometry.
        (lead_in_toolpath_pts, lead_out_toolpath_pts,
         arc_centre, arc_radius, arc_length_mm) = compute_arc_tangent_points(
            spec, cutter_comp
        )
        lead_in_length = arc_length_mm
        lead_out_length = arc_length_mm

        cx_at, cy_at = arc_centre
        qx_at, qy_at = lead_in_toolpath_pts[0]
        lead_in_lines = [
            f"(Lead-in arc-tangent — MH 31e §1131; R={_fmt(R)} mm; "
            f"sweep=90°; centre=({_fmt(cx_at)},{_fmt(cy_at)}); {cutter_comp})",
            f"G00 X{_fmt(qx_at)} Y{_fmt(qy_at)}  (rapid to arc-tangent lead-in start)",
            f"{cutter_comp} D  (activate cutter compensation)",
            f"(Use lead_in_toolpath_points for sampled arc G01 segments)",
        ]
        lead_out_lines = [
            f"(Lead-out arc-tangent — reverse arc; R={_fmt(R)} mm)",
            f"(Use lead_out_toolpath_points for sampled arc G01 segments)",
            "G40  (cancel cutter compensation)",
        ]

    _2d_types = ("arc", "line", "perpendicular", "arc-tangent")
    caveat = (
        (
            "2D contours only (XY plane, constant Z): arc and line lead-in/out "
            "are computed in the XY plane; the caller must set the correct Z "
            "depth before the lead-in begins. "
            if spec.lead_type in _2d_types
            else ""
        )
        + "Cutter compensation (G41/G42) is activated in the lead-in block; "
        "ensure the D-offset register (D = tool_radius) is set in the controller "
        "offset table before execution. "
        "I/J offsets are relative to the arc start point (Fanuc RS-274/NGC "
        "incremental arc centre convention); check controller docs if using "
        "absolute arc centre mode (G91.1). "
        "No gouge or collision checking is performed — verify path visually or "
        "via cam_verify_toolpath_collision before running on the machine. "
        + (
            f"Lead-in arc direction: {'G03 (CCW) for G41' if cutter_comp == 'G41' else 'G02 (CW) for G42'}. "
            if spec.lead_type in ("arc", "arc-tangent")
            else ""
        )
        + (
            "For helical-ramp and ramp-on: Z values assume a flat XY contour at "
            "target_z_mm; 3D toolpath points are in lead_in_toolpath_points. "
            "Pitch angle recommendation: 2–5° Al, 1–3° steel (MH 31e §1109). "
            if spec.lead_type in ("helical-ramp", "ramp-on")
            else ""
        )
        + "Refs: MH 31e §1131, §1109; Fanuc Operator Manual §G41/G42."
    )

    return LeadResult(
        gcode_lead_in="\n".join(lead_in_lines),
        gcode_lead_out="\n".join(lead_out_lines),
        lead_in_length_mm=round(lead_in_length, 6),
        lead_out_length_mm=round(lead_out_length, 6),
        honest_caveat=caveat,
        lead_in_toolpath_points=lead_in_toolpath_pts,
        lead_out_toolpath_points=lead_out_toolpath_pts,
        arc_centre_xy=arc_centre,
        arc_radius_mm=arc_radius,
    )


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

cam_generate_lead_in_out_spec = ToolSpec(
    name="cam_generate_lead_in_out",
    description=(
        "Generate G-code lead-in and lead-out segments for 2D or 3D contour milling, "
        "avoiding witness marks at the cutter entry/exit points. "
        "Follows MH 31e §1131 (cutter entry strategies), §1109 (helical/ramp entry), "
        "and Fanuc §G41/G42 cutter compensation. "
        "Supports six lead types: 'arc' (tangent-arc entry, most common), "
        "'line' (straight entry along contour tangent), 'perpendicular' "
        "(straight entry 90° to tangent), 'helical-ramp' (spiral descent at constant "
        "pitch angle to target Z), 'ramp-on' (linear descent at fixed plunge angle), "
        "and 'arc-tangent' (arc tangent to both surface and first cut direction with "
        "structured geometry output). "
        "Emits G02/G03 arc blocks with I/J offsets and G41/G42 cutter compensation. "
        "Returns lead-in and lead-out G-code blocks, path lengths, toolpath points "
        "list, arc centre/radius, and honest caveats."
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
                    "in mm.  MH 31e §1131: typically 50–100 % of cutter radius. "
                    "For 'helical-ramp': helix radius.  "
                    "For 'ramp-on': axial depth to ramp through."
                ),
            },
            "lead_angle_deg": {
                "type": "number",
                "description": (
                    "Arc sweep angle in degrees (1–90).  90° = classic perpendicular "
                    "tangent arc entry (recommended).  Ignored for 'line', "
                    "'perpendicular', 'helical-ramp', and 'ramp-on' types."
                ),
            },
            "feed_mm_per_min": {
                "type": "number",
                "description": "Feed rate for lead-in and lead-out moves (mm/min).",
            },
            "lead_type": {
                "type": "string",
                "enum": ["arc", "line", "perpendicular", "helical-ramp", "ramp-on", "arc-tangent"],
                "description": (
                    "'arc' — tangent arc entry/exit (MH 31e §1131, recommended). "
                    "'line' — straight entry along contour tangent. "
                    "'perpendicular' — straight entry 90° to tangent. "
                    "'helical-ramp' — spiral descent at constant pitch angle to target Z (MH 31e §1109). "
                    "'ramp-on' — linear descent at fixed plunge angle toward first cut point. "
                    "'arc-tangent' — arc tangent to both surface and first cut direction; "
                    "returns structured arc geometry as toolpath points."
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
            "target_z_mm": {
                "type": "number",
                "description": (
                    "Z depth of the contour plane (mm).  Required for "
                    "'helical-ramp' and 'ramp-on' types (default 0.0)."
                ),
            },
            "ramp_angle_deg": {
                "type": "number",
                "description": (
                    "Pitch/plunge angle in degrees (0 < angle ≤ 45, default 3.0°). "
                    "For 'helical-ramp': helix pitch angle "
                    "(MH 31e §1109 rec: 2–5° Al, 1–3° steel). "
                    "For 'ramp-on': linear plunge angle (typically 5°)."
                ),
            },
            "num_helix_turns": {
                "type": "integer",
                "description": "Number of full helix revolutions for 'helical-ramp' (default 1, min 1).",
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
        spec_kwargs = dict(
            contour_start_xy=(float(cxy[0]), float(cxy[1])),
            contour_tangent_xy=(float(txy[0]), float(txy[1])),
            cutter_diameter_mm=float(a["cutter_diameter_mm"]),
            lead_radius_mm=float(a["lead_radius_mm"]),
            lead_angle_deg=float(a["lead_angle_deg"]),
            feed_mm_per_min=float(a["feed_mm_per_min"]),
            lead_type=str(a["lead_type"]),
        )
        if "target_z_mm" in a:
            spec_kwargs["target_z_mm"] = float(a["target_z_mm"])
        if "ramp_angle_deg" in a:
            spec_kwargs["ramp_angle_deg"] = float(a["ramp_angle_deg"])
        if "num_helix_turns" in a:
            spec_kwargs["num_helix_turns"] = int(a["num_helix_turns"])
        spec = LeadSpec(**spec_kwargs)
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
        "lead_in_toolpath_points": result.lead_in_toolpath_points,
        "lead_out_toolpath_points": result.lead_out_toolpath_points,
        "arc_centre_xy": result.arc_centre_xy,
        "arc_radius_mm": result.arc_radius_mm,
        "honest_caveat": result.honest_caveat,
    })
