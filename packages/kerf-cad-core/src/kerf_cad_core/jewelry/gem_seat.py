"""
Automated gem-seat boolean.

Algorithm
---------
A gem seat (setting/bearing) is the void cut into a host solid (ring shank,
bezel) so the gemstone can be set.  The cutter geometry is:

  1. Bearing cone  — a truncated cone whose upper radius = (girdle_mm/2 +
     girdle_clearance) and whose half-angle = pavilion_angle_deg.  Depth =
     pavilion_depth_mm + culet_clearance.
  2. Girdle ledge  — a thin cylinder of height = girdle_mm + seat_allowance
     at radius = girdle_mm/2 + girdle_clearance, forming the bearing ledge
     the girdle rests on.
  3. Culet hole    — optional through-hole (radius = culet_radius) for light
     ingress and setting tool access (through-set or bead-set).  For flush /
     gypsy settings, omit.
  4. Crown relief  — a slight countersink taper at the top of the seat to
     allow the girdle to seat flush; half-angle = crown_angle_deg / 2.

The resulting cutter solid is emitted as a `gem_seat` feature node.  The
caller is expected to follow with a `feature_boolean` cut (A=host, B=seat_id,
kind="cut") to subtract the seat from the host.  The tool optionally emits
both the seat node AND the boolean cut node in one call when
`auto_cut_host_id` is provided.

Coordinate system
-----------------
The seat is generated centred at `position` (default [0,0,0]) with the table
(top) of the gemstone facing +Z.  Rotate via `orientation_deg` if the stone
is tipped (e.g. a tilted princess in a bypass ring).

Geometry dimensions (pure Python, no OCC required)
---------------------------------------------------
seat_geometry() returns a dict that can be used by the OCCT worker's
opGemSeat to build the actual TopoDS_Shape, OR used directly by tests to
validate clearance math without OCC.

Advanced seat types
-------------------
channel_seat_geometry()   — continuous bearing groove for a row of N stones
bezel_seat_geometry()     — inner bearing ledge for a bezel/collet setting
fishtail_seat_geometry()  — accent seat with bright-cut facet geometry hint
multi_stone_seat_geometry() — shared base seat for graduated stone arrangement
fancy_cut_girdle_profile()  — compute the outline parameters for a non-round
                              girdle shape (oval/marquise/pear/emerald/cushion)

LLM-facing tools
----------------
  jewelry_cut_gem_seat              — single seat (+ optional boolean cut)
  jewelry_cut_channel_seat          — channel setting groove for N stones
  jewelry_cut_bezel_seat            — bezel / collet seat
  jewelry_cut_fishtail_seat         — bright-cut accent seat
  jewelry_cut_multi_stone_seat      — graduated multi-stone shared seat
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import (
    read_feature_content,
    append_feature_node,
    next_node_id,
)
from kerf_cad_core.jewelry.gemstones import (
    GEMSTONE_CUTS,
    gemstone_proportions,
    carat_from_mm,
    mm_from_carat,
)


# ---------------------------------------------------------------------------
# Girdle profile helper for fancy cuts
# ---------------------------------------------------------------------------

def fancy_cut_girdle_profile(
    cut: str,
    diameter_mm: float,
    *,
    aspect_ratio: Optional[float] = None,
    corner_radius_pct: Optional[float] = None,
    girdle_clearance_mm: float = 0.05,
) -> dict:
    """Return a girdle outline specification for a gemstone cut.

    For round_brilliant and princess the profile is circular / square.
    For oval, marquise, pear, emerald, cushion the profile is an analytical
    curve (ellipse, stadium, etc.) described by its bounding box + corner
    parameters.  The OCCT worker uses these fields to extrude a per-profile
    bearing ledge instead of the default circular one.

    Parameters
    ----------
    cut               : gemstone cut name
    diameter_mm       : long-axis dimension (mm)
    aspect_ratio      : width/length override; None = use cut default
    corner_radius_pct : corner-radius override (% of short axis); None = default
    girdle_clearance_mm : radial/outward clearance added to all dimensions

    Returns
    -------
    dict with keys:
        profile_shape   — "circle" | "square" | "ellipse" | "stadium" |
                          "pear" | "rect_chamfer"
        long_axis_mm    — outer long-axis dimension (with clearance)
        short_axis_mm   — outer short-axis dimension (with clearance)
        corner_radius_mm— corner blend radius (0 for circle/ellipse)
        aspect_ratio    — width / length
        cut             — passed-through
    """
    from kerf_cad_core.jewelry.gemstones import _CUT_DEFAULTS  # internal detail

    defaults = _CUT_DEFAULTS.get(cut, {})
    ar = aspect_ratio if aspect_ratio is not None else defaults.get("aspect_ratio", 1.0)

    long_axis = diameter_mm + 2 * girdle_clearance_mm
    short_axis = diameter_mm * ar + 2 * girdle_clearance_mm

    # Profile shape heuristics
    if cut == "round_brilliant":
        shape = "circle"
        cr_mm = 0.0
    elif cut == "princess":
        shape = "square"
        cr_pct = corner_radius_pct if corner_radius_pct is not None else defaults.get("extras", {}).get("corner_radius_pct", 0)
        cr_mm = short_axis * cr_pct / 100.0
    elif cut in ("oval",):
        shape = "ellipse"
        cr_mm = 0.0
    elif cut == "marquise":
        shape = "stadium"   # two semicircles joined by tangent lines
        cr_mm = 0.0
    elif cut == "pear":
        shape = "pear"
        cr_mm = 0.0
    elif cut in ("emerald",):
        shape = "rect_chamfer"
        cr_pct = corner_radius_pct if corner_radius_pct is not None else (
            defaults.get("extras", {}).get("corner_cut_ratio", 0.15) * 100
        )
        cr_mm = short_axis * cr_pct / 100.0
    elif cut == "cushion":
        shape = "rect_chamfer"
        cr_pct = corner_radius_pct if corner_radius_pct is not None else (
            defaults.get("extras", {}).get("corner_radius_pct", 15)
        )
        cr_mm = short_axis * cr_pct / 100.0
    else:
        shape = "ellipse"
        cr_mm = 0.0

    return {
        "profile_shape":    shape,
        "long_axis_mm":     round(long_axis, 4),
        "short_axis_mm":    round(short_axis, 4),
        "corner_radius_mm": round(cr_mm, 4),
        "aspect_ratio":     round(ar, 4),
        "cut":              cut,
    }


# ---------------------------------------------------------------------------
# Seat geometry calculator (pure Python — no OCC dependency)
# ---------------------------------------------------------------------------

def seat_geometry(
    cut: str,
    diameter_mm: float,
    *,
    pavilion_angle_deg: float,
    pavilion_depth_pct: float,
    girdle_pct: float,
    crown_angle_deg: float,
    # Clearances (mm)
    girdle_clearance_mm: float = 0.05,
    culet_clearance_mm: float  = 0.1,
    seat_allowance_mm: float   = 0.02,
    crown_relief_mm: float     = 0.3,
    # Optional through-hole
    through_hole: bool = False,
    through_hole_radius_mm: Optional[float] = None,
    # Optional fancy-cut girdle profile
    girdle_profile: Optional[dict] = None,
) -> dict:
    """Return a pure-Python dict describing the gem-seat cutter geometry.

    Parameters
    ----------
    cut                : gemstone cut name (for aspect-ratio awareness)
    diameter_mm        : girdle diameter (or long axis for non-round)
    pavilion_angle_deg : pavilion half-angle (degrees from vertical)
    pavilion_depth_pct : pavilion depth as % of diameter_mm
    girdle_pct         : girdle thickness as % of diameter_mm
    crown_angle_deg    : crown angle (used for relief taper)
    girdle_clearance_mm: radial clearance around girdle for setting movement
    culet_clearance_mm : extra depth below pavilion tip for culet/tool room
    seat_allowance_mm  : axial allowance on girdle ledge height
    crown_relief_mm    : depth of crown-relief countersink above girdle
    through_hole       : if True, add a cylindrical through-hole
    through_hole_radius_mm: radius of through-hole (default = culet estimate)
    girdle_profile     : optional dict from fancy_cut_girdle_profile(); if None
                         a circular profile is assumed (back-compat)

    Returns
    -------
    dict with keys:
        girdle_radius_mm          — outer radius of girdle ledge (diameter/2 + clearance)
        pavilion_depth_mm         — pavilion depth absolute
        pavilion_angle_deg        — passed-through
        girdle_height_mm          — axial height of the girdle ledge
        bearing_cone_half_angle   — half-angle of bearing cone (= pavilion_angle_deg)
        bearing_cone_top_radius   — top radius of bearing cone
        bearing_cone_bottom_radius— bottom (culet) radius of bearing cone
        culet_depth_mm            — extra depth below pavilion tip
        crown_relief_depth_mm     — depth of crown countersink
        crown_relief_half_angle   — half-angle of crown countersink taper
        through_hole              — bool
        through_hole_radius_mm    — radius of through-hole (0 if not enabled)
        total_cutter_depth_mm     — total axial depth of cutter solid
        girdle_profile            — profile dict (fancy-cut outline) or None
    """
    r_girdle = diameter_mm / 2.0 + girdle_clearance_mm
    pav_depth = diameter_mm * pavilion_depth_pct / 100.0
    gird_height = diameter_mm * girdle_pct / 100.0 + seat_allowance_mm

    # Bearing cone
    # The cone apex is at the culet; half-angle = pavilion_angle_deg from vertical.
    # top_radius at the girdle plane:
    bearing_top_r = r_girdle
    # bottom (culet) radius; for brilliant cuts culet is a point or tiny flat
    culet_r = diameter_mm * 0.005   # ~0.5% = tiny flat

    crown_relief_half_angle = crown_angle_deg / 2.0

    if through_hole:
        thr = through_hole_radius_mm if through_hole_radius_mm else max(0.3, culet_r)
    else:
        thr = 0.0

    total_depth = pav_depth + culet_clearance_mm + gird_height + crown_relief_mm

    result = {
        "girdle_radius_mm":           round(r_girdle, 4),
        "pavilion_depth_mm":          round(pav_depth, 4),
        "pavilion_angle_deg":         round(pavilion_angle_deg, 3),
        "girdle_height_mm":           round(gird_height, 4),
        "bearing_cone_half_angle":    round(pavilion_angle_deg, 3),
        "bearing_cone_top_radius":    round(bearing_top_r, 4),
        "bearing_cone_bottom_radius": round(culet_r, 4),
        "culet_depth_mm":             round(culet_clearance_mm, 4),
        "crown_relief_depth_mm":      round(crown_relief_mm, 4),
        "crown_relief_half_angle":    round(crown_relief_half_angle, 3),
        "through_hole":               through_hole,
        "through_hole_radius_mm":     round(thr, 4),
        "total_cutter_depth_mm":      round(total_depth, 4),
    }
    if girdle_profile is not None:
        result["girdle_profile"] = girdle_profile

    return result


# ---------------------------------------------------------------------------
# Channel seat geometry
# ---------------------------------------------------------------------------

def channel_seat_geometry(
    cut: str,
    diameter_mm: float,
    *,
    n_stones: int,
    pitch_mm: float,
    pavilion_angle_deg: float,
    pavilion_depth_pct: float,
    girdle_pct: float,
    crown_angle_deg: float,
    girdle_clearance_mm: float = 0.05,
    culet_clearance_mm: float = 0.10,
    seat_allowance_mm: float = 0.02,
    crown_relief_mm: float = 0.30,
    groove_wall_thickness_mm: float = 0.20,
    start_position: Optional[list] = None,
    axis_direction: Optional[list] = None,
) -> dict:
    """Compute geometry for a continuous channel-setting bearing groove.

    The channel groove is a single extruded/swept rectangular slot whose
    cross-section forms a bearing ledge for all N stones.  Each stone sits in
    its own bearing pocket within the groove; the groove cutter is the union
    of all pockets plus a connecting slot.

    Parameters
    ----------
    cut, diameter_mm         : per-stone cut and primary dimension
    n_stones                 : number of stones in the row (>= 1)
    pitch_mm                 : centre-to-centre spacing (must exceed diameter_mm)
    pavilion_angle_deg etc.  : per-stone proportions (same as seat_geometry)
    groove_wall_thickness_mm : minimum metal wall between groove edge and the
                               channel wall face (informational/hint for OCC worker)
    start_position           : [x,y,z] of the first stone centre (default [0,0,0])
    axis_direction           : [dx,dy,dz] unit vector along the row
                               (default [1,0,0] = along X)

    Returns
    -------
    dict with keys:
        n_stones                 — count
        pitch_mm                 — as provided
        stone_diameter_mm        — per-stone girdle diameter
        stone_positions          — list of N [x,y,z] dicts (relative to start)
        per_stone_geom           — single seat_geometry result (same for all stones)
        groove_width_mm          — bearing groove width (= 2*girdle_radius + clearance)
        groove_depth_mm          — total cutter depth (= per_stone total_cutter_depth)
        groove_length_mm         — full cutter sweep length
        groove_wall_thickness_mm — wall hint
        total_cutter_depth_mm    — alias of groove_depth_mm
    """
    if n_stones < 1:
        raise ValueError("n_stones must be >= 1")
    if pitch_mm <= diameter_mm:
        raise ValueError(
            f"pitch_mm ({pitch_mm}) must exceed stone diameter_mm ({diameter_mm})"
        )

    sp = seat_geometry(
        cut=cut,
        diameter_mm=diameter_mm,
        pavilion_angle_deg=pavilion_angle_deg,
        pavilion_depth_pct=pavilion_depth_pct,
        girdle_pct=girdle_pct,
        crown_angle_deg=crown_angle_deg,
        girdle_clearance_mm=girdle_clearance_mm,
        culet_clearance_mm=culet_clearance_mm,
        seat_allowance_mm=seat_allowance_mm,
        crown_relief_mm=crown_relief_mm,
    )

    # Stone positions along axis_direction
    start = list(start_position) if start_position else [0.0, 0.0, 0.0]
    axis = list(axis_direction) if axis_direction else [1.0, 0.0, 0.0]
    # Normalise axis
    mag = math.sqrt(sum(v * v for v in axis))
    if mag < 1e-9:
        raise ValueError("axis_direction must be a non-zero vector")
    axis = [v / mag for v in axis]

    positions = []
    for i in range(n_stones):
        offset = i * pitch_mm
        pos = [round(start[j] + axis[j] * offset, 6) for j in range(3)]
        positions.append(pos)

    groove_width = 2.0 * sp["girdle_radius_mm"]
    groove_depth = sp["total_cutter_depth_mm"]
    # Groove length covers from first stone edge to last stone edge + clearance
    groove_length = (n_stones - 1) * pitch_mm + 2 * sp["girdle_radius_mm"]

    return {
        "n_stones":                  n_stones,
        "pitch_mm":                  round(pitch_mm, 4),
        "stone_diameter_mm":         round(diameter_mm, 4),
        "stone_positions":           positions,
        "per_stone_geom":            sp,
        "groove_width_mm":           round(groove_width, 4),
        "groove_depth_mm":           round(groove_depth, 4),
        "groove_length_mm":          round(groove_length, 4),
        "groove_wall_thickness_mm":  round(groove_wall_thickness_mm, 4),
        "total_cutter_depth_mm":     round(groove_depth, 4),
    }


# ---------------------------------------------------------------------------
# Bezel seat geometry
# ---------------------------------------------------------------------------

def bezel_seat_geometry(
    cut: str,
    diameter_mm: float,
    *,
    pavilion_angle_deg: float,
    pavilion_depth_pct: float,
    girdle_pct: float,
    crown_angle_deg: float,
    girdle_clearance_mm: float = 0.08,
    culet_clearance_mm: float = 0.10,
    seat_allowance_mm: float = 0.02,
    crown_relief_mm: float = 0.20,
    bezel_wall_height_mm: float = 1.0,
    tapered: bool = False,
    taper_angle_deg: float = 5.0,
    through_hole: bool = False,
    through_hole_radius_mm: Optional[float] = None,
    girdle_profile: Optional[dict] = None,
) -> dict:
    """Compute geometry for a bezel (collet) setting seat.

    A bezel seat has a wider inner ledge than a prong seat; the collet wall
    is pushed over the stone after setting.  The inner bore is sized to the
    girdle + clearance; a tapered (collet) option angles the bore inward.

    Parameters
    ----------
    bezel_wall_height_mm : height of the bezel collet wall above the girdle
                           ledge (informational; controls OCC extrusion height)
    tapered              : if True the bore is a cone (collet style); if False
                           it is a cylinder
    taper_angle_deg      : half-angle of tapered bore (only used if tapered=True)

    Returns
    -------
    seat_geometry() dict plus:
        bezel_wall_height_mm  — collet wall height
        tapered               — bool
        taper_angle_deg       — tapered bore half-angle (0 if not tapered)
        inner_bore_top_radius — bore radius at table plane (= girdle_radius_mm)
        inner_bore_bottom_radius — bore radius at girdle-ledge (tapered only)
        seat_type             — "bezel"
    """
    sp = seat_geometry(
        cut=cut,
        diameter_mm=diameter_mm,
        pavilion_angle_deg=pavilion_angle_deg,
        pavilion_depth_pct=pavilion_depth_pct,
        girdle_pct=girdle_pct,
        crown_angle_deg=crown_angle_deg,
        girdle_clearance_mm=girdle_clearance_mm,
        culet_clearance_mm=culet_clearance_mm,
        seat_allowance_mm=seat_allowance_mm,
        crown_relief_mm=crown_relief_mm,
        through_hole=through_hole,
        through_hole_radius_mm=through_hole_radius_mm,
        girdle_profile=girdle_profile,
    )

    inner_bore_top = sp["girdle_radius_mm"]
    if tapered:
        # Taper reduces the bore radius at the ledge compared to the top
        inner_bore_bottom = max(
            0.0,
            inner_bore_top - bezel_wall_height_mm * math.tan(math.radians(taper_angle_deg))
        )
        ta_deg = taper_angle_deg
    else:
        inner_bore_bottom = inner_bore_top
        ta_deg = 0.0

    sp.update({
        "bezel_wall_height_mm":    round(bezel_wall_height_mm, 4),
        "tapered":                 tapered,
        "taper_angle_deg":         round(ta_deg, 3),
        "inner_bore_top_radius":   round(inner_bore_top, 4),
        "inner_bore_bottom_radius": round(inner_bore_bottom, 4),
        "seat_type":               "bezel",
    })
    return sp


# ---------------------------------------------------------------------------
# Fishtail / bright-cut accent seat geometry
# ---------------------------------------------------------------------------

def fishtail_seat_geometry(
    cut: str,
    diameter_mm: float,
    *,
    pavilion_angle_deg: float,
    pavilion_depth_pct: float,
    girdle_pct: float,
    crown_angle_deg: float,
    girdle_clearance_mm: float = 0.04,
    culet_clearance_mm: float = 0.08,
    seat_allowance_mm: float = 0.02,
    crown_relief_mm: float = 0.25,
    bright_cut_angle_deg: float = 45.0,
    bright_cut_depth_mm: float = 0.15,
    n_bright_facets: int = 4,
    through_hole: bool = False,
    through_hole_radius_mm: Optional[float] = None,
) -> dict:
    """Compute geometry for a fishtail / bright-cut accent stone seat.

    The seat is a small round seat with additional bright-cut facet grooves
    radiating outward from the girdle ledge.  The facets create the bright
    reflective cuts seen in pavé and pavé-channel work.

    Parameters
    ----------
    bright_cut_angle_deg : half-angle of each bright-cut groove (from vertical)
    bright_cut_depth_mm  : axial depth of each bright-cut groove
    n_bright_facets      : number of radial bright-cut grooves (typically 4 or 6)

    Returns
    -------
    seat_geometry() dict plus:
        bright_cut_angle_deg  — facet groove half-angle
        bright_cut_depth_mm   — facet groove depth
        n_bright_facets       — count of radial facet grooves
        bright_cut_radius_mm  — outer radius of bright-cut pattern
        seat_type             — "fishtail"
    """
    if n_bright_facets < 1:
        raise ValueError("n_bright_facets must be >= 1")

    sp = seat_geometry(
        cut=cut,
        diameter_mm=diameter_mm,
        pavilion_angle_deg=pavilion_angle_deg,
        pavilion_depth_pct=pavilion_depth_pct,
        girdle_pct=girdle_pct,
        crown_angle_deg=crown_angle_deg,
        girdle_clearance_mm=girdle_clearance_mm,
        culet_clearance_mm=culet_clearance_mm,
        seat_allowance_mm=seat_allowance_mm,
        crown_relief_mm=crown_relief_mm,
        through_hole=through_hole,
        through_hole_radius_mm=through_hole_radius_mm,
    )

    # Bright-cut radius: extends beyond the girdle by the horizontal reach
    # of the facet groove at its specified angle and depth
    bc_reach = bright_cut_depth_mm * math.tan(math.radians(bright_cut_angle_deg))
    bc_radius = sp["girdle_radius_mm"] + bc_reach

    sp.update({
        "bright_cut_angle_deg": round(bright_cut_angle_deg, 3),
        "bright_cut_depth_mm":  round(bright_cut_depth_mm, 4),
        "n_bright_facets":      n_bright_facets,
        "bright_cut_radius_mm": round(bc_radius, 4),
        "seat_type":            "fishtail",
    })
    return sp


# ---------------------------------------------------------------------------
# Multi-stone shared seat geometry
# ---------------------------------------------------------------------------

def multi_stone_seat_geometry(
    cut: str,
    center_diameter_mm: float,
    side_diameter_mm: float,
    *,
    n_side_stones: int,
    side_pitch_mm: float,
    center_pavilion_angle_deg: float,
    center_pavilion_depth_pct: float,
    center_girdle_pct: float,
    center_crown_angle_deg: float,
    side_pavilion_angle_deg: float,
    side_pavilion_depth_pct: float,
    side_girdle_pct: float,
    side_crown_angle_deg: float,
    girdle_clearance_mm: float = 0.05,
    culet_clearance_mm: float = 0.10,
    seat_allowance_mm: float = 0.02,
    crown_relief_mm: float = 0.30,
    through_hole_center: bool = False,
    through_hole_radius_mm: Optional[float] = None,
) -> dict:
    """Compute a shared base seat for a graduated multi-stone arrangement.

    The arrangement consists of a single center stone flanked by side stones
    (e.g. a three-stone or five-stone setting).  The function returns:
      - geometry for the center seat
      - geometry for each side seat (assumed identical)
      - side stone positions (symmetric around center, along ±X)

    Parameters
    ----------
    cut                  : cut for ALL stones (center and sides)
    center_diameter_mm   : girdle diameter of the center stone
    side_diameter_mm     : girdle diameter of each side stone
    n_side_stones        : total number of side stones (must be even, ≥2)
    side_pitch_mm        : centre-to-centre distance between adjacent stones
                           (must exceed max(center_diameter_mm, side_diameter_mm))
    through_hole_center  : add through-hole to center seat only

    Returns
    -------
    dict with keys:
        center_seat_geom     — seat_geometry dict for center stone
        side_seat_geom       — seat_geometry dict for each side stone
        center_position      — [0,0,0] always
        side_positions       — list of [x,y,z] for each side stone
        n_side_stones        — as provided
        side_pitch_mm        — as provided
        seat_type            — "multi_stone"
        total_cutter_depth_mm— max of center and side seat depths
    """
    if n_side_stones < 2:
        raise ValueError("n_side_stones must be >= 2")
    if n_side_stones % 2 != 0:
        raise ValueError("n_side_stones must be even (symmetric arrangement)")
    min_pitch = max(center_diameter_mm, side_diameter_mm)
    if side_pitch_mm <= min_pitch:
        raise ValueError(
            f"side_pitch_mm ({side_pitch_mm}) must exceed the larger stone "
            f"diameter ({min_pitch})"
        )

    center_geom = seat_geometry(
        cut=cut,
        diameter_mm=center_diameter_mm,
        pavilion_angle_deg=center_pavilion_angle_deg,
        pavilion_depth_pct=center_pavilion_depth_pct,
        girdle_pct=center_girdle_pct,
        crown_angle_deg=center_crown_angle_deg,
        girdle_clearance_mm=girdle_clearance_mm,
        culet_clearance_mm=culet_clearance_mm,
        seat_allowance_mm=seat_allowance_mm,
        crown_relief_mm=crown_relief_mm,
        through_hole=through_hole_center,
        through_hole_radius_mm=through_hole_radius_mm,
    )

    side_geom = seat_geometry(
        cut=cut,
        diameter_mm=side_diameter_mm,
        pavilion_angle_deg=side_pavilion_angle_deg,
        pavilion_depth_pct=side_pavilion_depth_pct,
        girdle_pct=side_girdle_pct,
        crown_angle_deg=side_crown_angle_deg,
        girdle_clearance_mm=girdle_clearance_mm,
        culet_clearance_mm=culet_clearance_mm,
        seat_allowance_mm=seat_allowance_mm,
        crown_relief_mm=crown_relief_mm,
    )

    # Side positions: symmetric pairs at ±pitch, ±2*pitch, etc.
    half = n_side_stones // 2
    side_positions = []
    for i in range(1, half + 1):
        x = round(i * side_pitch_mm, 6)
        side_positions.append([x, 0.0, 0.0])
        side_positions.append([-x, 0.0, 0.0])
    # Sort for determinism: most-negative first
    side_positions.sort(key=lambda p: p[0])

    total_depth = max(
        center_geom["total_cutter_depth_mm"],
        side_geom["total_cutter_depth_mm"],
    )

    return {
        "center_seat_geom":      center_geom,
        "side_seat_geom":        side_geom,
        "center_position":       [0.0, 0.0, 0.0],
        "side_positions":        side_positions,
        "n_side_stones":         n_side_stones,
        "side_pitch_mm":         round(side_pitch_mm, 4),
        "seat_type":             "multi_stone",
        "total_cutter_depth_mm": round(total_depth, 4),
    }


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------

def _validate_base_args(a: dict):
    """Validate file_id, cut, carat/diameter_mm. Return (fid, cut, diam, err)."""
    file_id_str = a.get("file_id", "").strip()
    cut         = a.get("cut", "").strip()
    carat       = a.get("carat", None)
    diameter_mm = a.get("diameter_mm", None)

    if not file_id_str:
        return None, None, None, err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return None, None, None, err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return None, None, None, err_payload(
            f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS"
        )
    if carat is not None and diameter_mm is not None:
        return None, None, None, err_payload("Provide carat OR diameter_mm, not both", "BAD_ARGS")
    if carat is None and diameter_mm is None:
        return None, None, None, err_payload("One of carat or diameter_mm is required", "BAD_ARGS")

    if carat is not None:
        try:
            carat = float(carat)
        except Exception:
            return None, None, None, err_payload("carat must be a number", "BAD_ARGS")
        if carat <= 0:
            return None, None, None, err_payload("carat must be positive", "BAD_ARGS")

    if diameter_mm is not None:
        try:
            diameter_mm = float(diameter_mm)
        except Exception:
            return None, None, None, err_payload("diameter_mm must be a number", "BAD_ARGS")
        if diameter_mm <= 0:
            return None, None, None, err_payload("diameter_mm must be positive", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return None, None, None, err_payload("file_id must be a uuid", "BAD_ARGS")

    return fid, cut, (carat, diameter_mm), None


def _validate_clearances(a: dict) -> Optional[str]:
    """Return an error payload string if any clearance param is negative."""
    for name in ("girdle_clearance_mm", "culet_clearance_mm",
                 "seat_allowance_mm", "crown_relief_mm"):
        val = a.get(name)
        if val is None:
            continue
        try:
            val = float(val)
        except Exception:
            return err_payload(f"{name} must be a number", "BAD_ARGS")
        if val < 0:
            return err_payload(f"{name} must be >= 0", "BAD_ARGS")
    return None


def _resolve_props(cut, carat, diameter_mm):
    """Call gemstone_proportions and return (props, err_payload_or_None)."""
    try:
        return gemstone_proportions(cut, diameter_mm=diameter_mm, carat=carat), None
    except ValueError as e:
        return None, err_payload(str(e), "BAD_ARGS")


def _append_and_auto_cut(ctx, fid, seat_node, auto_cut_host_id, result):
    """Append seat_node; optionally append a boolean cut. Mutates result."""
    _name, seat_nid, err2 = append_feature_node(ctx, fid, seat_node)
    if err2:
        return err_payload(err2, "ERROR")
    result["seat_id"] = seat_nid

    if auto_cut_host_id:
        content2, err3 = read_feature_content(ctx, fid)
        if err3:
            result["warning"] = f"seat written but auto_cut failed: {err3}"
            return ok_payload(result)
        bool_node_id = next_node_id(content2, "boolean")
        bool_node = {
            "id": bool_node_id,
            "op": "boolean",
            "target_a_id": auto_cut_host_id,
            "target_b_id": seat_nid,
            "kind": "cut",
        }
        _bname, bool_nid, err4 = append_feature_node(ctx, fid, bool_node)
        if err4:
            result["warning"] = f"seat written but auto_cut boolean failed: {err4}"
        else:
            result["boolean_id"] = bool_nid

    return ok_payload(result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_cut_gem_seat  (original single-seat tool — back-compat)
# ---------------------------------------------------------------------------

jewelry_cut_gem_seat_spec = ToolSpec(
    name="jewelry_cut_gem_seat",
    description=(
        "Append a `gem_seat` node to a `.feature` file. "
        "Generates a gem-seat cutter solid (bearing cone + girdle ledge + optional "
        "through-hole for light) parameterised from the gemstone's cut and size. "
        "The seat cutter is positioned at `position` with `orientation_deg` rotation. "
        "If `auto_cut_host_id` is provided, a `boolean` cut node is also appended "
        "so the seat is immediately subtracted from the host solid — this is the "
        "most common single-step workflow. "
        "Without auto_cut_host_id, call feature_boolean manually: "
        "  feature_boolean(file_id, target_a_id=<host>, target_b_id=<seat_id>, kind='cut'). "
        "Seat geometry algorithm: "
        "  1. Bearing cone  — truncated cone, half-angle = pavilion_angle, "
        "     top_radius = girdle_radius + girdle_clearance, depth = pavilion_depth + culet_clearance. "
        "  2. Girdle ledge  — thin cylinder of height = girdle_mm + seat_allowance. "
        "  3. Crown relief  — countersink taper (crown_angle/2) of depth crown_relief_mm. "
        "  4. Optional through-hole for light ingress (through_hole=true). "
        "For non-round cuts pass girdle_shape to match the stone outline exactly. "
        "The OCCT worker's opGemSeat assembles these primitives into a single closed "
        "TopoDS_Solid cutter."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "cut": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": "Gemstone cut to match. Used for default proportions.",
            },
            "carat": {
                "type": "number",
                "description": "Stone weight in carats (converted to mm). Provide carat OR diameter_mm.",
            },
            "diameter_mm": {
                "type": "number",
                "description": "Primary dimension in mm. Provide diameter_mm OR carat.",
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x, y, z] seat centre in model space (mm). Default [0,0,0].",
            },
            "orientation_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[rx, ry, rz] Euler angles (degrees). Default [0,0,0].",
            },
            "girdle_clearance_mm": {
                "type": "number",
                "description": "Radial clearance around girdle (mm). Default 0.05.",
            },
            "culet_clearance_mm": {
                "type": "number",
                "description": "Extra depth below pavilion tip (mm). Default 0.10.",
            },
            "seat_allowance_mm": {
                "type": "number",
                "description": "Axial allowance on girdle ledge height (mm). Default 0.02.",
            },
            "crown_relief_mm": {
                "type": "number",
                "description": "Depth of crown-relief countersink above girdle (mm). Default 0.30.",
            },
            "through_hole": {
                "type": "boolean",
                "description": "Add a cylindrical through-hole for light ingress. Default false.",
            },
            "through_hole_radius_mm": {
                "type": "number",
                "description": "Through-hole radius (mm). Default: culet estimate. Requires through_hole=true.",
            },
            "girdle_shape": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": (
                    "Optional: use the girdle outline profile matching this cut. "
                    "Useful when the seat cut name differs from the stone's visual shape, "
                    "or to explicitly request a non-round bearing ledge for fancy cuts "
                    "(oval, marquise, pear, emerald, cushion). Defaults to `cut` value."
                ),
            },
            "aspect_ratio": {
                "type": "number",
                "description": "Width/length ratio override for fancy-cut girdle profile. Optional.",
            },
            "auto_cut_host_id": {
                "type": "string",
                "description": (
                    "If set, append a boolean cut node subtracting the seat from this "
                    "host feature node id immediately after the seat node. "
                    "Equivalent to running feature_boolean(kind='cut', "
                    "target_a_id=auto_cut_host_id, target_b_id=<new_seat_id>)."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id for the gem_seat node.",
            },
        },
        "required": ["file_id", "cut"],
    },
)


@register(jewelry_cut_gem_seat_spec, write=True)
async def run_jewelry_cut_gem_seat(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str          = a.get("file_id", "").strip()
    cut                  = a.get("cut", "").strip()
    carat                = a.get("carat", None)
    diameter_mm          = a.get("diameter_mm", None)
    position             = a.get("position", None)
    orientation_deg      = a.get("orientation_deg", None)
    girdle_clearance_mm  = a.get("girdle_clearance_mm", 0.05)
    culet_clearance_mm   = a.get("culet_clearance_mm", 0.10)
    seat_allowance_mm    = a.get("seat_allowance_mm", 0.02)
    crown_relief_mm      = a.get("crown_relief_mm", 0.30)
    through_hole         = a.get("through_hole", False)
    through_hole_radius  = a.get("through_hole_radius_mm", None)
    girdle_shape         = a.get("girdle_shape", None)
    aspect_ratio_override= a.get("aspect_ratio", None)
    auto_cut_host_id     = a.get("auto_cut_host_id", "").strip()
    node_id              = a.get("id", "").strip()

    # --- Validation ---
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return err_payload(
            f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS"
        )

    if carat is not None and diameter_mm is not None:
        return err_payload("Provide carat OR diameter_mm, not both", "BAD_ARGS")
    if carat is None and diameter_mm is None:
        return err_payload("One of carat or diameter_mm is required", "BAD_ARGS")

    if carat is not None:
        try:
            carat = float(carat)
        except Exception:
            return err_payload("carat must be a number", "BAD_ARGS")
        if carat <= 0:
            return err_payload("carat must be positive", "BAD_ARGS")

    if diameter_mm is not None:
        try:
            diameter_mm = float(diameter_mm)
        except Exception:
            return err_payload("diameter_mm must be a number", "BAD_ARGS")
        if diameter_mm <= 0:
            return err_payload("diameter_mm must be positive", "BAD_ARGS")

    for name, val in [
        ("girdle_clearance_mm", girdle_clearance_mm),
        ("culet_clearance_mm",  culet_clearance_mm),
        ("seat_allowance_mm",   seat_allowance_mm),
        ("crown_relief_mm",     crown_relief_mm),
    ]:
        try:
            val = float(val)
        except Exception:
            return err_payload(f"{name} must be a number", "BAD_ARGS")
        if val < 0:
            return err_payload(f"{name} must be >= 0", "BAD_ARGS")

    if through_hole_radius is not None:
        try:
            through_hole_radius = float(through_hole_radius)
        except Exception:
            return err_payload("through_hole_radius_mm must be a number", "BAD_ARGS")
        if through_hole_radius <= 0:
            return err_payload("through_hole_radius_mm must be positive", "BAD_ARGS")

    if girdle_shape is not None and girdle_shape not in GEMSTONE_CUTS:
        return err_payload(
            f"Unknown girdle_shape {girdle_shape!r}. Valid: {sorted(GEMSTONE_CUTS)}",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    # Resolve proportions
    try:
        props = gemstone_proportions(cut, diameter_mm=diameter_mm, carat=carat)
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    # Build fancy-cut girdle profile if requested
    profile_cut = girdle_shape if girdle_shape else cut
    gp = None
    if profile_cut != "round_brilliant":
        gp = fancy_cut_girdle_profile(
            profile_cut,
            props.diameter_mm,
            girdle_clearance_mm=float(girdle_clearance_mm),
            **({"aspect_ratio": float(aspect_ratio_override)} if aspect_ratio_override is not None else {}),
        )

    # Compute seat geometry
    geom = seat_geometry(
        cut=cut,
        diameter_mm=props.diameter_mm,
        pavilion_angle_deg=props.pavilion_angle_deg,
        pavilion_depth_pct=props.pavilion_depth_pct,
        girdle_pct=props.girdle_pct,
        crown_angle_deg=props.crown_angle_deg,
        girdle_clearance_mm=float(girdle_clearance_mm),
        culet_clearance_mm=float(culet_clearance_mm),
        seat_allowance_mm=float(seat_allowance_mm),
        crown_relief_mm=float(crown_relief_mm),
        through_hole=bool(through_hole),
        through_hole_radius_mm=through_hole_radius,
        girdle_profile=gp,
    )

    if not node_id:
        node_id = next_node_id(content, "gem_seat")

    seat_node: dict = {
        "id": node_id,
        "op": "gem_seat",
        "cut": cut,
        "diameter_mm": props.diameter_mm,
        **geom,
    }
    if position is not None:
        seat_node["position"] = position
    if orientation_deg is not None:
        seat_node["orientation_deg"] = orientation_deg

    # Re-read latest content before first append (content may have changed
    # if caller already added nodes this request; use the fetched copy).
    _name, seat_nid, err2 = append_feature_node(ctx, fid, seat_node)
    if err2:
        return err_payload(err2, "ERROR")

    result: dict = {
        "file_id": file_id_str,
        "seat_id": seat_nid,
        "op": "gem_seat",
        "cut": cut,
        "diameter_mm": props.diameter_mm,
        "total_cutter_depth_mm": geom["total_cutter_depth_mm"],
    }

    # Auto-cut boolean
    if auto_cut_host_id:
        # Re-read after seat node was written
        content2, err3 = read_feature_content(ctx, fid)
        if err3:
            # Seat was written but boolean can't be chained; surface warning
            result["warning"] = f"seat written but auto_cut failed: {err3}"
            return ok_payload(result)

        bool_node_id = next_node_id(content2, "boolean")
        bool_node = {
            "id": bool_node_id,
            "op": "boolean",
            "target_a_id": auto_cut_host_id,
            "target_b_id": seat_nid,
            "kind": "cut",
        }
        _bname, bool_nid, err4 = append_feature_node(ctx, fid, bool_node)
        if err4:
            result["warning"] = f"seat written but auto_cut boolean failed: {err4}"
        else:
            result["boolean_id"] = bool_nid

    return ok_payload(result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_cut_channel_seat
# ---------------------------------------------------------------------------

jewelry_cut_channel_seat_spec = ToolSpec(
    name="jewelry_cut_channel_seat",
    description=(
        "Append a `channel_seat` node to a `.feature` file. "
        "Generates a continuous bearing groove for a row of N stones at a given pitch. "
        "The groove cutter is a swept slot sized to the stone's girdle + clearance, "
        "with per-stone bearing pockets. Emits positions for all N stones. "
        "Use auto_cut_host_id to immediately subtract the groove from the host solid. "
        "Validation: pitch_mm must exceed stone diameter_mm (spacing must exceed stone size)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "cut": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": "Gemstone cut for all stones in the row.",
            },
            "carat": {"type": "number", "description": "Stone weight (carats). Provide carat OR diameter_mm."},
            "diameter_mm": {"type": "number", "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."},
            "n_stones": {"type": "integer", "minimum": 1, "description": "Number of stones in the row."},
            "pitch_mm": {
                "type": "number",
                "description": "Centre-to-centre stone spacing (mm). Must exceed diameter_mm.",
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x,y,z] centre of the first stone. Default [0,0,0].",
            },
            "axis_direction": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[dx,dy,dz] row direction unit vector. Default [1,0,0].",
            },
            "orientation_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[rx,ry,rz] groove cutter orientation. Default [0,0,0].",
            },
            "girdle_clearance_mm": {"type": "number", "description": "Radial clearance (mm). Default 0.05."},
            "culet_clearance_mm":  {"type": "number", "description": "Depth below pavilion tip (mm). Default 0.10."},
            "seat_allowance_mm":   {"type": "number", "description": "Axial ledge allowance (mm). Default 0.02."},
            "crown_relief_mm":     {"type": "number", "description": "Crown countersink depth (mm). Default 0.30."},
            "groove_wall_thickness_mm": {
                "type": "number",
                "description": "Minimum metal wall between groove and channel face (mm). Default 0.20.",
            },
            "auto_cut_host_id": {"type": "string", "description": "Host node id to subtract the groove from."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "cut", "n_stones", "pitch_mm"],
    },
)


@register(jewelry_cut_channel_seat_spec, write=True)
async def run_jewelry_cut_channel_seat(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    cut         = a.get("cut", "").strip()
    carat       = a.get("carat", None)
    diam_mm     = a.get("diameter_mm", None)

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return err_payload(f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS")
    if carat is not None and diam_mm is not None:
        return err_payload("Provide carat OR diameter_mm, not both", "BAD_ARGS")
    if carat is None and diam_mm is None:
        return err_payload("One of carat or diameter_mm is required", "BAD_ARGS")

    try:
        n_stones = int(a.get("n_stones", 0))
    except Exception:
        return err_payload("n_stones must be an integer", "BAD_ARGS")
    if n_stones < 1:
        return err_payload("n_stones must be >= 1", "BAD_ARGS")

    try:
        pitch_mm = float(a.get("pitch_mm", 0))
    except Exception:
        return err_payload("pitch_mm must be a number", "BAD_ARGS")
    if pitch_mm <= 0:
        return err_payload("pitch_mm must be positive", "BAD_ARGS")

    if carat is not None:
        try:
            carat = float(carat)
        except Exception:
            return err_payload("carat must be a number", "BAD_ARGS")
        if carat <= 0:
            return err_payload("carat must be positive", "BAD_ARGS")
    if diam_mm is not None:
        try:
            diam_mm = float(diam_mm)
        except Exception:
            return err_payload("diameter_mm must be a number", "BAD_ARGS")
        if diam_mm <= 0:
            return err_payload("diameter_mm must be positive", "BAD_ARGS")

    clearance_err = _validate_clearances(a)
    if clearance_err:
        return clearance_err

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    props, perr = _resolve_props(cut, carat, diam_mm)
    if perr:
        return perr

    # Channel-specific: spacing must exceed stone size
    if pitch_mm <= props.diameter_mm:
        return err_payload(
            f"pitch_mm ({pitch_mm}) must exceed stone diameter_mm ({props.diameter_mm:.4f})",
            "BAD_ARGS",
        )

    try:
        geom = channel_seat_geometry(
            cut=cut,
            diameter_mm=props.diameter_mm,
            n_stones=n_stones,
            pitch_mm=pitch_mm,
            pavilion_angle_deg=props.pavilion_angle_deg,
            pavilion_depth_pct=props.pavilion_depth_pct,
            girdle_pct=props.girdle_pct,
            crown_angle_deg=props.crown_angle_deg,
            girdle_clearance_mm=float(a.get("girdle_clearance_mm", 0.05)),
            culet_clearance_mm=float(a.get("culet_clearance_mm", 0.10)),
            seat_allowance_mm=float(a.get("seat_allowance_mm", 0.02)),
            crown_relief_mm=float(a.get("crown_relief_mm", 0.30)),
            groove_wall_thickness_mm=float(a.get("groove_wall_thickness_mm", 0.20)),
            start_position=a.get("position", None),
            axis_direction=a.get("axis_direction", None),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    node_id = a.get("id", "").strip() or next_node_id(content, "channel_seat")

    seat_node: dict = {
        "id":   node_id,
        "op":   "channel_seat",
        "cut":  cut,
        **geom,
    }
    if a.get("orientation_deg") is not None:
        seat_node["orientation_deg"] = a["orientation_deg"]

    result: dict = {
        "file_id":              file_id_str,
        "op":                   "channel_seat",
        "cut":                  cut,
        "n_stones":             n_stones,
        "groove_length_mm":     geom["groove_length_mm"],
        "total_cutter_depth_mm": geom["total_cutter_depth_mm"],
    }

    return _append_and_auto_cut(ctx, fid, seat_node, a.get("auto_cut_host_id", "").strip(), result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_cut_bezel_seat
# ---------------------------------------------------------------------------

jewelry_cut_bezel_seat_spec = ToolSpec(
    name="jewelry_cut_bezel_seat",
    description=(
        "Append a `bezel_seat` node to a `.feature` file. "
        "Generates an inner bearing ledge sized for a bezel or collet setting. "
        "The inner bore is cylindrical by default; set tapered=true for a collet "
        "(tapered bore) that grips the stone. Supports all cuts including fancy shapes "
        "(oval/marquise/pear/emerald/cushion) via automatic girdle profile computation. "
        "Use auto_cut_host_id to immediately subtract the seat from the host solid."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "cut": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": "Gemstone cut.",
            },
            "carat": {"type": "number", "description": "Stone weight (carats). Provide carat OR diameter_mm."},
            "diameter_mm": {"type": "number", "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."},
            "bezel_wall_height_mm": {
                "type": "number",
                "description": "Height of the bezel collet wall above the girdle ledge (mm). Default 1.0.",
            },
            "tapered": {
                "type": "boolean",
                "description": "If true, use a tapered bore (collet style). Default false.",
            },
            "taper_angle_deg": {
                "type": "number",
                "description": "Half-angle of tapered bore (degrees). Only used if tapered=true. Default 5.0.",
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x,y,z] seat centre. Default [0,0,0].",
            },
            "orientation_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[rx,ry,rz] Euler angles. Default [0,0,0].",
            },
            "girdle_clearance_mm": {"type": "number", "description": "Radial clearance (mm). Default 0.08."},
            "culet_clearance_mm":  {"type": "number", "description": "Depth below pavilion tip (mm). Default 0.10."},
            "seat_allowance_mm":   {"type": "number", "description": "Axial ledge allowance (mm). Default 0.02."},
            "crown_relief_mm":     {"type": "number", "description": "Crown countersink depth (mm). Default 0.20."},
            "through_hole": {"type": "boolean", "description": "Add through-hole. Default false."},
            "through_hole_radius_mm": {"type": "number", "description": "Through-hole radius (mm)."},
            "auto_cut_host_id": {"type": "string", "description": "Host node id to subtract the seat from."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "cut"],
    },
)


@register(jewelry_cut_bezel_seat_spec, write=True)
async def run_jewelry_cut_bezel_seat(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    cut         = a.get("cut", "").strip()
    carat       = a.get("carat", None)
    diam_mm     = a.get("diameter_mm", None)

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return err_payload(f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS")
    if carat is not None and diam_mm is not None:
        return err_payload("Provide carat OR diameter_mm, not both", "BAD_ARGS")
    if carat is None and diam_mm is None:
        return err_payload("One of carat or diameter_mm is required", "BAD_ARGS")

    if carat is not None:
        try:
            carat = float(carat)
        except Exception:
            return err_payload("carat must be a number", "BAD_ARGS")
        if carat <= 0:
            return err_payload("carat must be positive", "BAD_ARGS")
    if diam_mm is not None:
        try:
            diam_mm = float(diam_mm)
        except Exception:
            return err_payload("diameter_mm must be a number", "BAD_ARGS")
        if diam_mm <= 0:
            return err_payload("diameter_mm must be positive", "BAD_ARGS")

    clearance_err = _validate_clearances(a)
    if clearance_err:
        return clearance_err

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    props, perr = _resolve_props(cut, carat, diam_mm)
    if perr:
        return perr

    bezel_wall_height = float(a.get("bezel_wall_height_mm", 1.0))
    if bezel_wall_height <= 0:
        return err_payload("bezel_wall_height_mm must be positive", "BAD_ARGS")

    tapered = bool(a.get("tapered", False))
    taper_angle = float(a.get("taper_angle_deg", 5.0))
    if taper_angle < 0:
        return err_payload("taper_angle_deg must be >= 0", "BAD_ARGS")

    through_hole = bool(a.get("through_hole", False))
    thr = a.get("through_hole_radius_mm", None)
    if thr is not None:
        try:
            thr = float(thr)
        except Exception:
            return err_payload("through_hole_radius_mm must be a number", "BAD_ARGS")
        if thr <= 0:
            return err_payload("through_hole_radius_mm must be positive", "BAD_ARGS")

    # Fancy-cut girdle profile for non-round cuts
    gp = None
    if cut != "round_brilliant":
        gp = fancy_cut_girdle_profile(
            cut,
            props.diameter_mm,
            girdle_clearance_mm=float(a.get("girdle_clearance_mm", 0.08)),
        )

    geom = bezel_seat_geometry(
        cut=cut,
        diameter_mm=props.diameter_mm,
        pavilion_angle_deg=props.pavilion_angle_deg,
        pavilion_depth_pct=props.pavilion_depth_pct,
        girdle_pct=props.girdle_pct,
        crown_angle_deg=props.crown_angle_deg,
        girdle_clearance_mm=float(a.get("girdle_clearance_mm", 0.08)),
        culet_clearance_mm=float(a.get("culet_clearance_mm", 0.10)),
        seat_allowance_mm=float(a.get("seat_allowance_mm", 0.02)),
        crown_relief_mm=float(a.get("crown_relief_mm", 0.20)),
        bezel_wall_height_mm=bezel_wall_height,
        tapered=tapered,
        taper_angle_deg=taper_angle,
        through_hole=through_hole,
        through_hole_radius_mm=thr,
        girdle_profile=gp,
    )

    node_id = a.get("id", "").strip() or next_node_id(content, "bezel_seat")

    seat_node: dict = {
        "id":  node_id,
        "op":  "bezel_seat",
        "cut": cut,
        **geom,
    }
    if a.get("position") is not None:
        seat_node["position"] = a["position"]
    if a.get("orientation_deg") is not None:
        seat_node["orientation_deg"] = a["orientation_deg"]

    result: dict = {
        "file_id":               file_id_str,
        "op":                    "bezel_seat",
        "cut":                   cut,
        "diameter_mm":           props.diameter_mm,
        "total_cutter_depth_mm": geom["total_cutter_depth_mm"],
        "bezel_wall_height_mm":  geom["bezel_wall_height_mm"],
        "tapered":               geom["tapered"],
    }

    return _append_and_auto_cut(ctx, fid, seat_node, a.get("auto_cut_host_id", "").strip(), result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_cut_fishtail_seat
# ---------------------------------------------------------------------------

jewelry_cut_fishtail_seat_spec = ToolSpec(
    name="jewelry_cut_fishtail_seat",
    description=(
        "Append a `fishtail_seat` node to a `.feature` file. "
        "Generates a small accent-stone seat with bright-cut facet grooves "
        "radiating outward from the girdle ledge. The bright-cut geometry hint "
        "is stored in the node for the OCCT worker to mill radial facet cuts. "
        "Typically used for pavé and channel-pavé accent stones."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "cut": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": "Gemstone cut (usually round_brilliant for accent stones).",
            },
            "carat": {"type": "number", "description": "Stone weight (carats). Provide carat OR diameter_mm."},
            "diameter_mm": {"type": "number", "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."},
            "bright_cut_angle_deg": {
                "type": "number",
                "description": "Half-angle of each bright-cut groove from vertical (degrees). Default 45.",
            },
            "bright_cut_depth_mm": {
                "type": "number",
                "description": "Axial depth of each bright-cut groove (mm). Default 0.15.",
            },
            "n_bright_facets": {
                "type": "integer",
                "minimum": 1,
                "description": "Number of radial bright-cut grooves. Default 4.",
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x,y,z] seat centre. Default [0,0,0].",
            },
            "orientation_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[rx,ry,rz] Euler angles. Default [0,0,0].",
            },
            "girdle_clearance_mm": {"type": "number", "description": "Radial clearance (mm). Default 0.04."},
            "culet_clearance_mm":  {"type": "number", "description": "Depth below pavilion tip (mm). Default 0.08."},
            "seat_allowance_mm":   {"type": "number", "description": "Axial ledge allowance (mm). Default 0.02."},
            "crown_relief_mm":     {"type": "number", "description": "Crown countersink depth (mm). Default 0.25."},
            "through_hole": {"type": "boolean", "description": "Add through-hole. Default false."},
            "through_hole_radius_mm": {"type": "number", "description": "Through-hole radius (mm)."},
            "auto_cut_host_id": {"type": "string", "description": "Host node id to subtract the seat from."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "cut"],
    },
)


@register(jewelry_cut_fishtail_seat_spec, write=True)
async def run_jewelry_cut_fishtail_seat(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    cut         = a.get("cut", "").strip()
    carat       = a.get("carat", None)
    diam_mm     = a.get("diameter_mm", None)

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return err_payload(f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS")
    if carat is not None and diam_mm is not None:
        return err_payload("Provide carat OR diameter_mm, not both", "BAD_ARGS")
    if carat is None and diam_mm is None:
        return err_payload("One of carat or diameter_mm is required", "BAD_ARGS")

    if carat is not None:
        try:
            carat = float(carat)
        except Exception:
            return err_payload("carat must be a number", "BAD_ARGS")
        if carat <= 0:
            return err_payload("carat must be positive", "BAD_ARGS")
    if diam_mm is not None:
        try:
            diam_mm = float(diam_mm)
        except Exception:
            return err_payload("diameter_mm must be a number", "BAD_ARGS")
        if diam_mm <= 0:
            return err_payload("diameter_mm must be positive", "BAD_ARGS")

    clearance_err = _validate_clearances(a)
    if clearance_err:
        return clearance_err

    n_bright_facets = int(a.get("n_bright_facets", 4))
    if n_bright_facets < 1:
        return err_payload("n_bright_facets must be >= 1", "BAD_ARGS")

    bright_cut_angle = float(a.get("bright_cut_angle_deg", 45.0))
    if bright_cut_angle <= 0:
        return err_payload("bright_cut_angle_deg must be positive", "BAD_ARGS")

    bright_cut_depth = float(a.get("bright_cut_depth_mm", 0.15))
    if bright_cut_depth <= 0:
        return err_payload("bright_cut_depth_mm must be positive", "BAD_ARGS")

    through_hole = bool(a.get("through_hole", False))
    thr = a.get("through_hole_radius_mm", None)
    if thr is not None:
        try:
            thr = float(thr)
        except Exception:
            return err_payload("through_hole_radius_mm must be a number", "BAD_ARGS")
        if thr <= 0:
            return err_payload("through_hole_radius_mm must be positive", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    props, perr = _resolve_props(cut, carat, diam_mm)
    if perr:
        return perr

    geom = fishtail_seat_geometry(
        cut=cut,
        diameter_mm=props.diameter_mm,
        pavilion_angle_deg=props.pavilion_angle_deg,
        pavilion_depth_pct=props.pavilion_depth_pct,
        girdle_pct=props.girdle_pct,
        crown_angle_deg=props.crown_angle_deg,
        girdle_clearance_mm=float(a.get("girdle_clearance_mm", 0.04)),
        culet_clearance_mm=float(a.get("culet_clearance_mm", 0.08)),
        seat_allowance_mm=float(a.get("seat_allowance_mm", 0.02)),
        crown_relief_mm=float(a.get("crown_relief_mm", 0.25)),
        bright_cut_angle_deg=bright_cut_angle,
        bright_cut_depth_mm=bright_cut_depth,
        n_bright_facets=n_bright_facets,
        through_hole=through_hole,
        through_hole_radius_mm=thr,
    )

    node_id = a.get("id", "").strip() or next_node_id(content, "fishtail_seat")

    seat_node: dict = {
        "id":  node_id,
        "op":  "fishtail_seat",
        "cut": cut,
        **geom,
    }
    if a.get("position") is not None:
        seat_node["position"] = a["position"]
    if a.get("orientation_deg") is not None:
        seat_node["orientation_deg"] = a["orientation_deg"]

    result: dict = {
        "file_id":               file_id_str,
        "op":                    "fishtail_seat",
        "cut":                   cut,
        "diameter_mm":           props.diameter_mm,
        "total_cutter_depth_mm": geom["total_cutter_depth_mm"],
        "n_bright_facets":       geom["n_bright_facets"],
        "bright_cut_radius_mm":  geom["bright_cut_radius_mm"],
    }

    return _append_and_auto_cut(ctx, fid, seat_node, a.get("auto_cut_host_id", "").strip(), result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_cut_multi_stone_seat
# ---------------------------------------------------------------------------

jewelry_cut_multi_stone_seat_spec = ToolSpec(
    name="jewelry_cut_multi_stone_seat",
    description=(
        "Append a `multi_stone_seat` node to a `.feature` file. "
        "Generates a shared base seat for a graduated multi-stone arrangement: "
        "a center stone flanked by smaller side stones (e.g. 3-stone or 5-stone). "
        "Returns the center seat geometry, per-side-stone geometry, and all stone "
        "positions. n_side_stones must be even (symmetric) and >= 2. "
        "side_pitch_mm must exceed the larger of center_diameter_mm / side_diameter_mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "cut": {
                "type": "string",
                "enum": sorted(GEMSTONE_CUTS),
                "description": "Gemstone cut for all stones (center + sides).",
            },
            "center_carat": {"type": "number", "description": "Center stone weight (carats)."},
            "center_diameter_mm": {"type": "number", "description": "Center stone primary dimension (mm)."},
            "side_carat": {"type": "number", "description": "Side stone weight (carats, each)."},
            "side_diameter_mm": {"type": "number", "description": "Side stone primary dimension (mm, each)."},
            "n_side_stones": {
                "type": "integer",
                "minimum": 2,
                "description": "Total number of side stones. Must be even (symmetric). Default 2.",
            },
            "side_pitch_mm": {
                "type": "number",
                "description": "Centre-to-centre spacing between adjacent stones (mm). Must exceed stone diameter.",
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x,y,z] centre stone position. Default [0,0,0].",
            },
            "orientation_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[rx,ry,rz] Euler angles. Default [0,0,0].",
            },
            "girdle_clearance_mm": {"type": "number", "description": "Radial clearance (mm). Default 0.05."},
            "culet_clearance_mm":  {"type": "number", "description": "Depth below pavilion tip (mm). Default 0.10."},
            "seat_allowance_mm":   {"type": "number", "description": "Axial ledge allowance (mm). Default 0.02."},
            "crown_relief_mm":     {"type": "number", "description": "Crown countersink depth (mm). Default 0.30."},
            "through_hole_center": {
                "type": "boolean",
                "description": "Add through-hole to center seat only. Default false.",
            },
            "through_hole_radius_mm": {"type": "number", "description": "Center through-hole radius (mm)."},
            "auto_cut_host_id": {"type": "string", "description": "Host node id to subtract the seat group from."},
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "cut", "side_pitch_mm"],
    },
)


@register(jewelry_cut_multi_stone_seat_spec, write=True)
async def run_jewelry_cut_multi_stone_seat(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    cut         = a.get("cut", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not cut:
        return err_payload("cut is required", "BAD_ARGS")
    if cut not in GEMSTONE_CUTS:
        return err_payload(f"Unknown cut {cut!r}. Valid cuts: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS")

    # Center stone sizing
    center_carat = a.get("center_carat", None)
    center_diam  = a.get("center_diameter_mm", None)
    if center_carat is not None and center_diam is not None:
        return err_payload("Provide center_carat OR center_diameter_mm, not both", "BAD_ARGS")
    if center_carat is None and center_diam is None:
        return err_payload("One of center_carat or center_diameter_mm is required", "BAD_ARGS")
    if center_carat is not None:
        try:
            center_carat = float(center_carat)
        except Exception:
            return err_payload("center_carat must be a number", "BAD_ARGS")
        if center_carat <= 0:
            return err_payload("center_carat must be positive", "BAD_ARGS")
    if center_diam is not None:
        try:
            center_diam = float(center_diam)
        except Exception:
            return err_payload("center_diameter_mm must be a number", "BAD_ARGS")
        if center_diam <= 0:
            return err_payload("center_diameter_mm must be positive", "BAD_ARGS")

    # Side stone sizing
    side_carat = a.get("side_carat", None)
    side_diam  = a.get("side_diameter_mm", None)
    if side_carat is not None and side_diam is not None:
        return err_payload("Provide side_carat OR side_diameter_mm, not both", "BAD_ARGS")
    if side_carat is None and side_diam is None:
        return err_payload("One of side_carat or side_diameter_mm is required", "BAD_ARGS")
    if side_carat is not None:
        try:
            side_carat = float(side_carat)
        except Exception:
            return err_payload("side_carat must be a number", "BAD_ARGS")
        if side_carat <= 0:
            return err_payload("side_carat must be positive", "BAD_ARGS")
    if side_diam is not None:
        try:
            side_diam = float(side_diam)
        except Exception:
            return err_payload("side_diameter_mm must be a number", "BAD_ARGS")
        if side_diam <= 0:
            return err_payload("side_diameter_mm must be positive", "BAD_ARGS")

    try:
        n_side = int(a.get("n_side_stones", 2))
    except Exception:
        return err_payload("n_side_stones must be an integer", "BAD_ARGS")
    if n_side < 2:
        return err_payload("n_side_stones must be >= 2", "BAD_ARGS")
    if n_side % 2 != 0:
        return err_payload("n_side_stones must be even (symmetric arrangement)", "BAD_ARGS")

    try:
        side_pitch = float(a.get("side_pitch_mm", 0))
    except Exception:
        return err_payload("side_pitch_mm must be a number", "BAD_ARGS")
    if side_pitch <= 0:
        return err_payload("side_pitch_mm must be positive", "BAD_ARGS")

    clearance_err = _validate_clearances(a)
    if clearance_err:
        return clearance_err

    through_hole_center = bool(a.get("through_hole_center", False))
    thr = a.get("through_hole_radius_mm", None)
    if thr is not None:
        try:
            thr = float(thr)
        except Exception:
            return err_payload("through_hole_radius_mm must be a number", "BAD_ARGS")
        if thr <= 0:
            return err_payload("through_hole_radius_mm must be positive", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    center_props, perr = _resolve_props(cut, center_carat, center_diam)
    if perr:
        return perr

    side_props, perr2 = _resolve_props(cut, side_carat, side_diam)
    if perr2:
        return perr2

    # Spacing validation
    min_pitch = max(center_props.diameter_mm, side_props.diameter_mm)
    if side_pitch <= min_pitch:
        return err_payload(
            f"side_pitch_mm ({side_pitch}) must exceed the larger stone diameter "
            f"({min_pitch:.4f})",
            "BAD_ARGS",
        )

    try:
        geom = multi_stone_seat_geometry(
            cut=cut,
            center_diameter_mm=center_props.diameter_mm,
            side_diameter_mm=side_props.diameter_mm,
            n_side_stones=n_side,
            side_pitch_mm=side_pitch,
            center_pavilion_angle_deg=center_props.pavilion_angle_deg,
            center_pavilion_depth_pct=center_props.pavilion_depth_pct,
            center_girdle_pct=center_props.girdle_pct,
            center_crown_angle_deg=center_props.crown_angle_deg,
            side_pavilion_angle_deg=side_props.pavilion_angle_deg,
            side_pavilion_depth_pct=side_props.pavilion_depth_pct,
            side_girdle_pct=side_props.girdle_pct,
            side_crown_angle_deg=side_props.crown_angle_deg,
            girdle_clearance_mm=float(a.get("girdle_clearance_mm", 0.05)),
            culet_clearance_mm=float(a.get("culet_clearance_mm", 0.10)),
            seat_allowance_mm=float(a.get("seat_allowance_mm", 0.02)),
            crown_relief_mm=float(a.get("crown_relief_mm", 0.30)),
            through_hole_center=through_hole_center,
            through_hole_radius_mm=thr,
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    node_id = a.get("id", "").strip() or next_node_id(content, "multi_stone_seat")

    seat_node: dict = {
        "id":  node_id,
        "op":  "multi_stone_seat",
        "cut": cut,
        **geom,
    }
    if a.get("position") is not None:
        seat_node["position"] = a["position"]
    if a.get("orientation_deg") is not None:
        seat_node["orientation_deg"] = a["orientation_deg"]

    result: dict = {
        "file_id":               file_id_str,
        "op":                    "multi_stone_seat",
        "cut":                   cut,
        "center_diameter_mm":    center_props.diameter_mm,
        "side_diameter_mm":      side_props.diameter_mm,
        "n_side_stones":         n_side,
        "total_cutter_depth_mm": geom["total_cutter_depth_mm"],
        "side_positions":        geom["side_positions"],
    }

    return _append_and_auto_cut(ctx, fid, seat_node, a.get("auto_cut_host_id", "").strip(), result)
