"""
kerf_cad_core.jewelry.eternity_auto
====================================

Calibrated eternity-ring auto-distribution (RhinoGold / MatrixGold parity).

Given the ring size, stone cut + size, and setting style this module computes:

  1. The exact stone count that fills the requested arc (full 360°, 3/4, or
     half) using the chosen calibration mode.
  2. Per-stone angular position around the shank, seat XYZ on the inner
     profile, and the corresponding seat-cutter geometry.
  3. Per-stone prong/bead/rail retention spec.
  4. Summary statistics: metal removed, total carat, estimated metal weight.

Setting styles
--------------
prong        — 4-prong or 6-prong head per stone; prong diameter = 0.5 mm.
channel      — continuous parallel-rail groove; shared groove cutter.
shared_bead  — single raised bead at each stone boundary (pavé/grain).
u_cut        — U-shaped bright-cut seat with two prong tips at the open ends.
bezel        — individual mini-bezel collet per stone.

Calibration modes
-----------------
fixed_count       — caller specifies stone count; gap is distributed evenly.
fixed_size        — stone size is fixed; stone count = floor(arc / pitch);
                    remaining gap shared evenly (standard industry default).
graduated         — stone sizes decrease monotonically from the top stone
                    outward; a size_step_mm controls the increment; count is
                    computed to fill the arc.

Coverage fractions
------------------
full             — 360° (full eternity)
three_quarter    — 270°
half             — 180°

Coordinate system
-----------------
The shank is centred at the origin; the ring axis is +Z.  Stones sit at
radius = inner_radius_mm (bore surface) in the XY plane.  Angle 0 = 12 o'clock
(+Y direction).  Angles increase clockwise when viewed from above (consistent
with the ring module and RhinoGold conventions).

    position_angle_deg  — 0 at top (12 o'clock), clockwise
    seat_x = ring_radius * sin(angle_rad)
    seat_y = ring_radius * cos(angle_rad)
    seat_z = 0.0   (centre-plane of shank)

For a full eternity the first stone is at 0°; stones are spaced by
pitch_deg = arc_deg / n_stones.

Metal-removed estimate
----------------------
Each seat cutter is approximated as a truncated cone (pavilion zone):
    V_cone = (π/3) * h * (r1² + r1*r2 + r2²)
where r1 = girdle_radius + girdle_clearance, r2 ≈ culet_radius, h = pavilion_depth.

Minimum metal bridge validation
--------------------------------
After placement the angular bridge is checked:
    bridge_mm = (pitch_deg - stone_subtended_deg) * π/180 * ring_radius
A warning "thin_metal" is appended if bridge_mm < min_bridge_mm.

LLM-facing tools
----------------
  jewelry_eternity_auto_distribute  — primary wizard; computes + emits node
  jewelry_eternity_auto_stats       — read-only re-compute of stats from existing node
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List, Optional, Tuple

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)
from kerf_cad_core.jewelry.gemstones import (
    GEMSTONE_CUTS,
    carat_from_mm,
    gemstone_proportions,
)
from kerf_cad_core.jewelry.ring import ring_size_to_diameter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SETTING_STYLES = frozenset(["prong", "channel", "shared_bead", "u_cut", "bezel"])
_VALID_CALIBRATION_MODES = frozenset(["fixed_count", "fixed_size", "graduated"])
_VALID_COVERAGES = frozenset(["full", "three_quarter", "half"])

_COVERAGE_ARC: Dict[str, float] = {
    "full":          360.0,
    "three_quarter": 270.0,
    "half":          180.0,
}

# Minimum metal bridge between seat edges (mm) — industry rule of thumb.
_DEFAULT_MIN_BRIDGE_MM = 0.15

# Minimum gap between stone edges regardless of calibration mode (mm).
_ABS_MIN_GAP_MM = 0.10

# Default stone-to-stone gap fraction of stone diameter when unspecified.
_DEFAULT_GAP_FRACTION = 0.15

# Pavilion depth factor (depth = stone_mm * factor) for cutter volume.
_SEAT_DEPTH_FACTOR = 0.605

# Default prong diameter (mm).
_PRONG_DIAMETER_MM = 0.5

# Default bead diameter expressed as a fraction of the gap.
_BEAD_GAP_FRACTION = 0.70

# Channel rail wall thickness (mm) — informational hint.
_CHANNEL_WALL_MM = 0.25

# Metal density proxy for weight estimate (18k yellow gold g/mm³).
_DEFAULT_METAL_DENSITY_G_MM3 = 15.58 / 1000.0  # 15.58 g/cm³ → g/mm³


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _positive(name: str, value: Any) -> Optional[str]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number; got {value!r}"
    if v <= 0:
        return f"{name} must be positive; got {v}"
    return None


def _non_negative(name: str, value: Any) -> Optional[str]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number; got {value!r}"
    if v < 0:
        return f"{name} must be >= 0; got {v}"
    return None


def _positive_int(name: str, value: Any) -> Optional[str]:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return f"{name} must be an integer; got {value!r}"
    if v <= 0:
        return f"{name} must be a positive integer; got {v}"
    return None


# ---------------------------------------------------------------------------
# Inner-radius helper
# ---------------------------------------------------------------------------

def _inner_radius_mm(ring_size: Any, size_system: str = "us") -> float:
    """Return inner bore radius in mm from ring size."""
    id_mm = ring_size_to_diameter(size_system, ring_size)
    return id_mm / 2.0


# ---------------------------------------------------------------------------
# Seat cutter volume (truncated cone approximation)
# ---------------------------------------------------------------------------

def _seat_cutter_volume_mm3(
    stone_mm: float,
    pavilion_angle_deg: float,
    pavilion_depth_pct: float,
    girdle_pct: float,
    girdle_clearance_mm: float = 0.05,
) -> float:
    """Approximate seat cutter volume as a truncated cone (pavilion zone)."""
    r1 = stone_mm / 2.0 + girdle_clearance_mm   # top (girdle) radius
    pav_h = stone_mm * pavilion_depth_pct / 100.0
    # Culet radius ≈ tip of pavilion cone
    r2 = max(0.0, r1 - pav_h * math.tan(math.radians(pavilion_angle_deg)))
    gird_h = stone_mm * girdle_pct / 100.0
    total_h = pav_h + gird_h
    # Truncated cone: V = (π/3)*h*(r1²+r1*r2+r2²)
    return (math.pi / 3.0) * total_h * (r1 * r1 + r1 * r2 + r2 * r2)


# ---------------------------------------------------------------------------
# Stone position on the inner-bore profile
# ---------------------------------------------------------------------------

def _stone_position(angle_deg: float, ring_radius: float) -> Dict[str, float]:
    """Return {x, y, z} for a stone at angle_deg (0=12-o'clock, CW)."""
    rad = math.radians(angle_deg)
    return {
        "x": round(ring_radius * math.sin(rad), 6),
        "y": round(ring_radius * math.cos(rad), 6),
        "z": 0.0,
    }


# ---------------------------------------------------------------------------
# Graduated size sequence
# ---------------------------------------------------------------------------

def _graduated_sizes(
    center_mm: float,
    size_step_mm: float,
    n_total: int,
) -> List[float]:
    """
    Return a list of n_total stone sizes for a graduated eternity band.

    The center stone (index 0, position 0 = top) has size center_mm.
    Each adjacent pair shrinks by size_step_mm going outward, with a minimum
    of center_mm - size_step_mm * floor(n_total/2).  Sizes are symmetric:
    for full eternity the sequence mirrors around index 0.

    Returns sizes indexed from the top stone outward, then mirrored.

    For n_total stones in full eternity:
      index 0 → center_mm
      index 1 and (n-1) → center_mm - size_step_mm
      index 2 and (n-2) → center_mm - 2*size_step_mm
      ...
    The minimum stone size is clamped at 0.5 mm.
    """
    half = n_total // 2
    # Build the decreasing half
    half_sizes = []
    for k in range(half + 1):
        s = max(0.5, center_mm - k * size_step_mm)
        half_sizes.append(s)

    sizes: List[float] = []
    if n_total % 2 == 1:
        # Odd count: one top stone + pairs on each side
        sizes.append(half_sizes[0])
        for k in range(1, half + 1):
            sizes.append(half_sizes[k])
            sizes.append(half_sizes[k])
    else:
        # Even count: pairs only (symmetric, no single top stone)
        for k in range(half):
            sz = max(0.5, center_mm - k * size_step_mm)
            sizes.append(sz)
            sizes.append(sz)

    # Ensure list is exactly n_total (trim or pad with minimum size)
    sizes = sizes[:n_total]
    while len(sizes) < n_total:
        sizes.append(max(0.5, center_mm - half * size_step_mm))

    return sizes


# ---------------------------------------------------------------------------
# Core distribution algorithm
# ---------------------------------------------------------------------------

def eternity_auto_distribute(
    ring_size: Any,
    stone_cut: str,
    stone_mm: float,
    setting_style: str = "prong",
    calibration_mode: str = "fixed_size",
    *,
    size_system: str = "us",
    coverage: str = "full",
    fixed_count: Optional[int] = None,
    gap_mm: Optional[float] = None,
    size_step_mm: float = 0.1,
    min_bridge_mm: float = _DEFAULT_MIN_BRIDGE_MM,
    girdle_clearance_mm: float = 0.05,
) -> Dict[str, Any]:
    """
    Compute calibrated stone distribution for an eternity ring.

    Parameters
    ----------
    ring_size : int | float | str
        Ring size in the specified size_system.
    stone_cut : str
        One of GEMSTONE_CUTS.
    stone_mm : float
        Primary stone dimension in mm (girdle diameter for round; long axis
        for fancy cuts).
    setting_style : str
        One of 'prong', 'channel', 'shared_bead', 'u_cut', 'bezel'.
    calibration_mode : str
        'fixed_size'  — fill arc with maximum whole stones; evenly distribute
                        remaining gap.
        'fixed_count' — place exactly fixed_count stones; compute pitch.
        'graduated'   — graduated sizes decreasing outward; size_step_mm
                        controls decrement.
    size_system : str
        Ring-size system: 'us', 'uk', 'au', 'eu', 'jp'.
    coverage : str
        Arc to cover: 'full' (360°), 'three_quarter' (270°), 'half' (180°).
    fixed_count : int, optional
        Required when calibration_mode='fixed_count'.
    gap_mm : float, optional
        Explicit stone-to-stone gap in mm.  Overrides default gap fraction.
        Must be >= _ABS_MIN_GAP_MM.
    size_step_mm : float
        Size decrement per step outward in graduated mode (default 0.1 mm).
    min_bridge_mm : float
        Minimum metal bridge between seat edges; below this a 'thin_metal'
        flag is set on the affected stones.
    girdle_clearance_mm : float
        Radial clearance added to the stone girdle for the seat bore.

    Returns
    -------
    dict with keys:
        inner_diameter_mm       — bore ID from ring size
        inner_radius_mm         — bore radius (= ID / 2)
        inner_circumference_mm  — π × ID
        arc_deg                 — arc covered (degrees)
        stone_count             — number of placed stones
        stone_cut               — passed-through
        stone_mm                — primary dimension (uniform or center size)
        setting_style           — passed-through
        calibration_mode        — passed-through
        pitch_deg               — angular pitch between stone centres
        pitch_mm                — arc pitch (stone centre-to-centre arc length)
        gap_mm                  — metal gap between stone edges
        coverage_pct            — (stone_count × stone_mm) / arc_length × 100
        total_carat             — sum of individual carat weights
        metal_removed_mm3       — sum of seat-cutter volumes
        metal_weight_estimate_g — estimated metal ring weight (18k Au proxy)
        stones                  — list of per-stone dicts (see below)
        seat_cutters            — list of per-stone cutter node specs
        retention               — list of per-stone prong/bead/rail specs
        thin_metal_warnings     — count of thin-metal flagged stones
        warn                    — '' or 'thin_metal' (band-level flag)

    Per-stone dict keys:
        index           — integer 0 … N-1
        angle_deg       — angular position from 12 o'clock (clockwise)
        seat_x, seat_y  — position on inner bore surface (mm)
        seat_z          — axial position (0 = centre-plane)
        stone_mm        — this stone's primary dimension
        carat           — individual carat weight
    """
    # ---- validate inputs ----
    if stone_cut not in GEMSTONE_CUTS:
        raise ValueError(
            f"Unknown stone_cut {stone_cut!r}. Valid: {sorted(GEMSTONE_CUTS)}"
        )
    if stone_mm <= 0:
        raise ValueError(f"stone_mm must be positive; got {stone_mm!r}")
    if setting_style not in _VALID_SETTING_STYLES:
        raise ValueError(
            f"Unknown setting_style {setting_style!r}. "
            f"Valid: {sorted(_VALID_SETTING_STYLES)}"
        )
    if calibration_mode not in _VALID_CALIBRATION_MODES:
        raise ValueError(
            f"Unknown calibration_mode {calibration_mode!r}. "
            f"Valid: {sorted(_VALID_CALIBRATION_MODES)}"
        )
    if coverage not in _VALID_COVERAGES:
        raise ValueError(
            f"Unknown coverage {coverage!r}. Valid: {sorted(_VALID_COVERAGES)}"
        )

    # ---- ring geometry ----
    inner_r = _inner_radius_mm(ring_size, size_system)
    inner_d = inner_r * 2.0
    inner_circ = math.pi * inner_d
    arc_deg = _COVERAGE_ARC[coverage]
    arc_len = inner_circ * arc_deg / 360.0  # arc length of covered segment

    # ---- gemstone proportions (for seat cutter geometry) ----
    props = gemstone_proportions(stone_cut, stone_mm)
    pav_angle = props.pavilion_angle_deg
    pav_depth_pct = props.pavilion_depth_pct
    gird_pct = props.girdle_pct

    # ---- determine stone sizes per calibration mode ----
    if calibration_mode == "fixed_count":
        if fixed_count is None or fixed_count < 1:
            raise ValueError(
                "fixed_count must be a positive integer when "
                "calibration_mode='fixed_count'"
            )
        n = int(fixed_count)
        pitch_mm = arc_len / n
        computed_gap = pitch_mm - stone_mm
        if computed_gap < _ABS_MIN_GAP_MM:
            raise ValueError(
                f"fixed_count={n} leaves gap={computed_gap:.3f} mm "
                f"which is below the minimum {_ABS_MIN_GAP_MM} mm. "
                f"Reduce the count or use a smaller stone."
            )
        eff_gap = computed_gap
        stone_sizes = [stone_mm] * n

    elif calibration_mode == "graduated":
        eff_gap = gap_mm if gap_mm is not None else stone_mm * _DEFAULT_GAP_FRACTION
        eff_gap = max(eff_gap, _ABS_MIN_GAP_MM)
        # Compute max count based on center stone
        pitch_mm_center = stone_mm + eff_gap
        n = max(1, int(math.floor(arc_len / pitch_mm_center)))
        stone_sizes = _graduated_sizes(stone_mm, size_step_mm, n)
        # Recompute actual pitch based on total stone span
        total_stone_span = sum(stone_sizes)
        available_gap = arc_len - total_stone_span
        if available_gap < _ABS_MIN_GAP_MM * n:
            # Too tight: remove one stone
            n = max(1, n - 1)
            stone_sizes = _graduated_sizes(stone_mm, size_step_mm, n)
            total_stone_span = sum(stone_sizes)
            available_gap = arc_len - total_stone_span
        eff_gap = available_gap / max(n, 1)
        pitch_mm = arc_len / n

    else:  # fixed_size (default)
        eff_gap = gap_mm if gap_mm is not None else stone_mm * _DEFAULT_GAP_FRACTION
        eff_gap = max(eff_gap, _ABS_MIN_GAP_MM)
        pitch_mm = stone_mm + eff_gap
        n = max(1, int(math.floor(arc_len / pitch_mm)))
        # Re-distribute gap evenly (ensures pitch × n exactly fills arc)
        remaining = arc_len - n * stone_mm
        eff_gap = remaining / max(n, 1)
        pitch_mm = arc_len / n
        stone_sizes = [stone_mm] * n

    # Angular pitch
    pitch_deg = arc_deg / n if n > 0 else arc_deg

    # ---- compute per-stone positions ----
    stones: List[Dict] = []
    seat_cutters: List[Dict] = []
    retention: List[Dict] = []
    total_carat = 0.0
    total_metal_removed = 0.0
    thin_metal_count = 0

    for i in range(n):
        # Angle from top, clockwise.
        if coverage == "full":
            angle_deg = pitch_deg * i
        elif coverage == "three_quarter":
            # Centred on top; spans from -135° to +135°
            start_angle = -arc_deg / 2.0
            angle_deg = start_angle + pitch_deg * i
        else:  # half
            # Bottom half excluded; spans from -90° to +90°
            start_angle = -arc_deg / 2.0
            angle_deg = start_angle + pitch_deg * i

        s_mm = stone_sizes[i]

        pos = _stone_position(angle_deg, inner_r)

        # Carat for this stone
        try:
            ct = carat_from_mm(stone_cut, s_mm)
        except Exception:
            ct = (s_mm / 6.5) ** 3
        total_carat += ct

        # Per-stone proportions if graduated (only center stone is in props)
        if calibration_mode == "graduated" and s_mm != stone_mm:
            try:
                sp = gemstone_proportions(stone_cut, s_mm)
                p_ang = sp.pavilion_angle_deg
                p_dep = sp.pavilion_depth_pct
                g_pct = sp.girdle_pct
            except Exception:
                p_ang = pav_angle
                p_dep = pav_depth_pct
                g_pct = gird_pct
        else:
            p_ang = pav_angle
            p_dep = pav_depth_pct
            g_pct = gird_pct

        # Seat-cutter volume
        vol = _seat_cutter_volume_mm3(
            s_mm, p_ang, p_dep, g_pct, girdle_clearance_mm
        )
        total_metal_removed += vol

        # Seat cutter node spec
        cutter = {
            "op": "jewelry_eternity_seat_cutter",
            "stone_index": i,
            "stone_mm": round(s_mm, 4),
            "stone_cut": stone_cut,
            "pavilion_angle_deg": round(p_ang, 3),
            "pavilion_depth_pct": round(p_dep, 3),
            "girdle_pct": round(g_pct, 3),
            "girdle_clearance_mm": round(girdle_clearance_mm, 4),
            "position": [pos["x"], pos["y"], pos["z"]],
            "normal": [
                round(-math.sin(math.radians(angle_deg)), 6),
                round(-math.cos(math.radians(angle_deg)), 6),
                0.0,
            ],
            "cutter_volume_mm3": round(vol, 5),
        }
        seat_cutters.append(cutter)

        # Bridge check (arc gap between stone edges)
        arc_gap_mm = (pitch_deg - math.degrees(
            math.asin(min(1.0, s_mm / (2.0 * inner_r)))
        ) * 2) * math.pi / 180.0 * inner_r
        # Simpler estimate: pitch_mm - s_mm
        bridge_mm = pitch_mm - s_mm
        warn = "thin_metal" if bridge_mm < min_bridge_mm else ""
        if warn:
            thin_metal_count += 1

        # Retention spec
        ret = _build_retention(
            i, s_mm, pos, angle_deg, eff_gap, setting_style
        )
        retention.append(ret)

        stone_entry = {
            "index": i,
            "angle_deg": round(angle_deg, 4),
            "seat_x": pos["x"],
            "seat_y": pos["y"],
            "seat_z": 0.0,
            "stone_mm": round(s_mm, 4),
            "carat": round(ct, 5),
            "warn": warn,
        }
        stones.append(stone_entry)

    # ---- coverage ratio ----
    total_stone_arc = sum(
        math.degrees(math.asin(min(1.0, sz / (2.0 * inner_r)))) * 2
        for sz in stone_sizes
    )
    coverage_pct = (total_stone_arc / arc_deg * 100.0) if arc_deg > 0 else 0.0

    # ---- ring metal volume estimate (annular band) ----
    # Approximate shank as a torus; band_width ≈ stone_mm + 0.6 mm rail
    band_width = stone_mm + 0.6
    wall_thickness = stone_mm * 0.4 + 0.3  # rough estimate
    outer_r = inner_r + wall_thickness
    metal_volume_mm3 = (
        math.pi * (outer_r ** 2 - inner_r ** 2) * band_width
        - total_metal_removed
    )
    metal_volume_mm3 = max(0.0, metal_volume_mm3)
    metal_weight_g = metal_volume_mm3 * _DEFAULT_METAL_DENSITY_G_MM3

    return {
        "inner_diameter_mm": round(inner_d, 4),
        "inner_radius_mm": round(inner_r, 4),
        "inner_circumference_mm": round(inner_circ, 4),
        "arc_deg": arc_deg,
        "stone_count": n,
        "stone_cut": stone_cut,
        "stone_mm": round(stone_mm, 4),
        "setting_style": setting_style,
        "calibration_mode": calibration_mode,
        "coverage": coverage,
        "pitch_deg": round(pitch_deg, 6),
        "pitch_mm": round(pitch_mm, 4),
        "gap_mm": round(eff_gap, 4),
        "coverage_pct": round(coverage_pct, 2),
        "total_carat": round(total_carat, 4),
        "metal_removed_mm3": round(total_metal_removed, 4),
        "metal_weight_estimate_g": round(metal_weight_g, 4),
        "stones": stones,
        "seat_cutters": seat_cutters,
        "retention": retention,
        "thin_metal_warnings": thin_metal_count,
        "warn": "thin_metal" if thin_metal_count > 0 else "",
    }


# ---------------------------------------------------------------------------
# Retention spec builder
# ---------------------------------------------------------------------------

def _build_retention(
    index: int,
    stone_mm: float,
    pos: Dict[str, float],
    angle_deg: float,
    gap_mm: float,
    style: str,
) -> Dict:
    """Return the per-stone retention (prong/bead/rail) spec dict."""
    rad = math.radians(angle_deg)
    # Tangential unit vector (perpendicular to radial, in XY plane)
    # Radial direction: (sin θ, cos θ, 0); tangent: (cos θ, −sin θ, 0)
    tx = math.cos(rad)
    ty = -math.sin(rad)

    if style == "prong":
        # Two prongs flanking the stone along the band tangent direction
        half_span = stone_mm / 2.0 + gap_mm / 2.0
        prongs = []
        for sign in (-1, 1):
            px = pos["x"] + sign * half_span * tx
            py = pos["y"] + sign * half_span * ty
            prongs.append({
                "x": round(px, 4),
                "y": round(py, 4),
                "z": 0.0,
                "diameter_mm": _PRONG_DIAMETER_MM,
                "height_mm": round(stone_mm * 0.3 + 0.3, 4),
            })
        return {
            "stone_index": index,
            "style": "prong",
            "prong_count": 2,
            "prong_diameter_mm": _PRONG_DIAMETER_MM,
            "prongs": prongs,
        }

    elif style == "channel":
        # Two parallel rails running tangentially; rail specs are band-level
        # but we emit per-stone markers at the half-gap points
        return {
            "stone_index": index,
            "style": "channel",
            "rail_wall_thickness_mm": _CHANNEL_WALL_MM,
            "rail_height_mm": round(stone_mm * 0.25 + 0.2, 4),
            "gap_hint_mm": round(gap_mm, 4),
        }

    elif style == "shared_bead":
        bead_d = max(0.3, gap_mm * _BEAD_GAP_FRACTION)
        # Bead sits at the midpoint between this stone and the next (along tang)
        bx = pos["x"] + (stone_mm / 2.0 + gap_mm / 2.0) * tx
        by = pos["y"] + (stone_mm / 2.0 + gap_mm / 2.0) * ty
        return {
            "stone_index": index,
            "style": "shared_bead",
            "bead_diameter_mm": round(bead_d, 4),
            "bead_position": {
                "x": round(bx, 4),
                "y": round(by, 4),
                "z": 0.0,
            },
        }

    elif style == "u_cut":
        # U-shaped bright-cut: two small prong tips at the open ends
        half_span = stone_mm / 2.0 + gap_mm * 0.4
        tips = []
        for sign in (-1, 1):
            tx2 = pos["x"] + sign * half_span * tx
            ty2 = pos["y"] + sign * half_span * ty
            tips.append({"x": round(tx2, 4), "y": round(ty2, 4), "z": 0.0})
        return {
            "stone_index": index,
            "style": "u_cut",
            "u_width_mm": round(stone_mm + gap_mm * 0.8, 4),
            "prong_tips": tips,
        }

    else:  # bezel
        return {
            "stone_index": index,
            "style": "bezel",
            "bezel_wall_mm": round(gap_mm / 2.0, 4),
            "bezel_height_mm": round(stone_mm * 0.15 + 0.2, 4),
        }


# ---------------------------------------------------------------------------
# Node builder (for .feature file integration)
# ---------------------------------------------------------------------------

def build_eternity_node(
    node_id: str,
    ring_size: Any,
    stone_cut: str,
    stone_mm: float,
    setting_style: str = "prong",
    calibration_mode: str = "fixed_size",
    size_system: str = "us",
    coverage: str = "full",
    fixed_count: Optional[int] = None,
    gap_mm: Optional[float] = None,
    size_step_mm: float = 0.1,
    min_bridge_mm: float = _DEFAULT_MIN_BRIDGE_MM,
    girdle_clearance_mm: float = 0.05,
) -> Dict[str, Any]:
    """Compute eternity distribution and wrap in an op node dict."""
    result = eternity_auto_distribute(
        ring_size=ring_size,
        stone_cut=stone_cut,
        stone_mm=stone_mm,
        setting_style=setting_style,
        calibration_mode=calibration_mode,
        size_system=size_system,
        coverage=coverage,
        fixed_count=fixed_count,
        gap_mm=gap_mm,
        size_step_mm=size_step_mm,
        min_bridge_mm=min_bridge_mm,
        girdle_clearance_mm=girdle_clearance_mm,
    )
    return {
        "id": node_id,
        "op": "jewelry_eternity_auto",
        **result,
        "_params": {
            "ring_size": ring_size,
            "stone_cut": stone_cut,
            "stone_mm": stone_mm,
            "setting_style": setting_style,
            "calibration_mode": calibration_mode,
            "size_system": size_system,
            "coverage": coverage,
            "fixed_count": fixed_count,
            "gap_mm": gap_mm,
            "size_step_mm": size_step_mm,
            "min_bridge_mm": min_bridge_mm,
            "girdle_clearance_mm": girdle_clearance_mm,
        },
    }


# ---------------------------------------------------------------------------
# LLM Tool: jewelry_eternity_auto_distribute
# ---------------------------------------------------------------------------

_eternity_distribute_spec = ToolSpec(
    name="jewelry_eternity_auto_distribute",
    description=(
        "Calibrated eternity-ring auto-distribution wizard (RhinoGold parity). "
        "Given a ring size, stone cut + size, and setting style, computes the "
        "exact stone count + per-stone seat positions for a full, 3/4, or half "
        "eternity band. "
        "\n\n"
        "Calibration modes:\n"
        "  fixed_size   — stone size fixed; count = floor(arc / pitch); "
        "remaining gap shared evenly (default).\n"
        "  fixed_count  — caller specifies count; gap is distributed evenly.\n"
        "  graduated    — stone sizes decrease outward by size_step_mm; "
        "count computed to fill arc.\n"
        "\n"
        "Setting styles: prong, channel, shared_bead, u_cut, bezel.\n"
        "Coverage: full (360°), three_quarter (270°), half (180°).\n"
        "\n"
        "Returns stone count, pitch, gap, per-stone angle + XY positions, "
        "individual carats, seat-cutter volumes, and a retention spec per stone. "
        "Also reports total carat, metal removed (mm³), metal weight estimate (g), "
        "and thin-metal bridge warnings.\n"
        "\n"
        "Appends a 'jewelry_eternity_auto' node to the .feature file."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "ring_size": {
                "description": (
                    "Ring size in the specified size_system. "
                    "US: numeric 0–16 (e.g. 7 or 7.5). "
                    "UK/AU: letter string (e.g. 'N', 'N½'). "
                    "EU: circumference mm (41–76). JP: integer 1–30."
                ),
            },
            "stone_cut": {
                "type": "string",
                "description": (
                    "Gemstone cut name. Common eternity cuts: "
                    "round_brilliant, princess, baguette, emerald, oval."
                ),
            },
            "stone_mm": {
                "type": "number",
                "description": (
                    "Primary stone dimension in mm — girdle diameter for round_brilliant, "
                    "long-axis for fancy cuts. Typical eternity range: 1.5–4 mm."
                ),
            },
            "setting_style": {
                "type": "string",
                "enum": ["prong", "channel", "shared_bead", "u_cut", "bezel"],
                "description": (
                    "Stone retention style. "
                    "prong: two prongs flanking each stone. "
                    "channel: parallel rail groove. "
                    "shared_bead: single bead between stones. "
                    "u_cut: U-shaped bright-cut. "
                    "bezel: mini collet per stone."
                ),
            },
            "calibration_mode": {
                "type": "string",
                "enum": ["fixed_size", "fixed_count", "graduated"],
                "description": (
                    "How to resolve stone count vs gap. "
                    "fixed_size: fill arc, even gap (default). "
                    "fixed_count: exact count specified via fixed_count param. "
                    "graduated: stones decrease in size outward from top."
                ),
            },
            "size_system": {
                "type": "string",
                "enum": ["us", "uk", "au", "eu", "jp"],
                "description": "Ring-size system. Default 'us'.",
            },
            "coverage": {
                "type": "string",
                "enum": ["full", "three_quarter", "half"],
                "description": "Arc to cover: full=360°, three_quarter=270°, half=180°. Default 'full'.",
            },
            "fixed_count": {
                "type": "integer",
                "description": "Number of stones. Required when calibration_mode='fixed_count'.",
            },
            "gap_mm": {
                "type": "number",
                "description": (
                    "Desired metal gap between stone edges in mm. "
                    "Overrides the default gap fraction. "
                    "Minimum enforced at 0.1 mm."
                ),
            },
            "size_step_mm": {
                "type": "number",
                "description": (
                    "Graduated mode: size decrement per step outward from centre stone (mm). "
                    "Default 0.1 mm."
                ),
            },
            "min_bridge_mm": {
                "type": "number",
                "description": "Minimum metal bridge (mm) before a thin_metal warning is issued. Default 0.15 mm.",
            },
            "girdle_clearance_mm": {
                "type": "number",
                "description": "Radial clearance around girdle for seat bore (mm). Default 0.05 mm.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "ring_size", "stone_cut", "stone_mm"],
    },
)


@register(_eternity_distribute_spec, write=True)
async def run_eternity_auto_distribute(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    ring_size = a.get("ring_size")
    if ring_size is None:
        return err_payload("ring_size is required", "BAD_ARGS")

    stone_cut = a.get("stone_cut", "").strip()
    if not stone_cut:
        return err_payload("stone_cut is required", "BAD_ARGS")
    if stone_cut not in GEMSTONE_CUTS:
        return err_payload(
            f"Unknown stone_cut {stone_cut!r}. Valid: {sorted(GEMSTONE_CUTS)}", "BAD_ARGS"
        )

    stone_mm_raw = a.get("stone_mm")
    err = _positive("stone_mm", stone_mm_raw)
    if err:
        return err_payload(err, "BAD_ARGS")
    stone_mm = float(stone_mm_raw)

    setting_style = a.get("setting_style", "prong")
    if setting_style not in _VALID_SETTING_STYLES:
        return err_payload(
            f"Unknown setting_style {setting_style!r}. Valid: {sorted(_VALID_SETTING_STYLES)}",
            "BAD_ARGS",
        )

    calibration_mode = a.get("calibration_mode", "fixed_size")
    if calibration_mode not in _VALID_CALIBRATION_MODES:
        return err_payload(
            f"Unknown calibration_mode {calibration_mode!r}. Valid: {sorted(_VALID_CALIBRATION_MODES)}",
            "BAD_ARGS",
        )

    size_system = a.get("size_system", "us")
    coverage = a.get("coverage", "full")
    if coverage not in _VALID_COVERAGES:
        return err_payload(
            f"Unknown coverage {coverage!r}. Valid: {sorted(_VALID_COVERAGES)}",
            "BAD_ARGS",
        )

    fixed_count = a.get("fixed_count")
    if fixed_count is not None:
        err = _positive_int("fixed_count", fixed_count)
        if err:
            return err_payload(err, "BAD_ARGS")
        fixed_count = int(fixed_count)

    gap_mm_raw = a.get("gap_mm")
    gap_mm: Optional[float] = None
    if gap_mm_raw is not None:
        err = _positive("gap_mm", gap_mm_raw)
        if err:
            return err_payload(err, "BAD_ARGS")
        gap_mm = float(gap_mm_raw)

    size_step_mm = float(a.get("size_step_mm", 0.1))
    min_bridge_mm = float(a.get("min_bridge_mm", _DEFAULT_MIN_BRIDGE_MM))
    girdle_clearance_mm = float(a.get("girdle_clearance_mm", 0.05))
    node_id = a.get("id", "").strip() or next_node_id()

    try:
        node = build_eternity_node(
            node_id=node_id,
            ring_size=ring_size,
            stone_cut=stone_cut,
            stone_mm=stone_mm,
            setting_style=setting_style,
            calibration_mode=calibration_mode,
            size_system=size_system,
            coverage=coverage,
            fixed_count=fixed_count,
            gap_mm=gap_mm,
            size_step_mm=size_step_mm,
            min_bridge_mm=min_bridge_mm,
            girdle_clearance_mm=girdle_clearance_mm,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"distribution failed: {exc}", "INTERNAL_ERROR")

    try:
        file_id = uuid.UUID(file_id_str)
    except ValueError:
        return err_payload(f"file_id is not a valid UUID: {file_id_str!r}", "BAD_ARGS")

    try:
        await append_feature_node(ctx, file_id, node)
    except Exception as exc:
        return err_payload(f"could not write feature node: {exc}", "WRITE_ERROR")

    summary = {
        "node_id": node_id,
        "stone_count": node["stone_count"],
        "total_carat": node["total_carat"],
        "pitch_mm": node["pitch_mm"],
        "gap_mm": node["gap_mm"],
        "coverage_pct": node["coverage_pct"],
        "metal_removed_mm3": node["metal_removed_mm3"],
        "metal_weight_estimate_g": node["metal_weight_estimate_g"],
        "thin_metal_warnings": node["thin_metal_warnings"],
        "warn": node["warn"],
    }
    return ok_payload(summary)


# ---------------------------------------------------------------------------
# LLM Tool: jewelry_eternity_auto_stats
# ---------------------------------------------------------------------------

_eternity_stats_spec = ToolSpec(
    name="jewelry_eternity_auto_stats",
    description=(
        "Read-only: re-compute summary statistics from an existing "
        "'jewelry_eternity_auto' node in a .feature file without writing changes. "
        "Returns stone count, total carat, pitch, gap, coverage %, metal removed (mm³), "
        "and metal weight estimate."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "node_id": {
                "type": "string",
                "description": "Node id of an existing jewelry_eternity_auto node.",
            },
        },
        "required": ["file_id", "node_id"],
    },
)


@register(_eternity_stats_spec, write=False)
async def run_eternity_auto_stats(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id_str = a.get("file_id", "").strip()
    node_id_str = a.get("node_id", "").strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not node_id_str:
        return err_payload("node_id is required", "BAD_ARGS")

    try:
        file_id = uuid.UUID(file_id_str)
    except ValueError:
        return err_payload(f"file_id is not a valid UUID: {file_id_str!r}", "BAD_ARGS")

    try:
        content = await read_feature_content(ctx, file_id)
        nodes = content.get("nodes", [])
    except Exception as exc:
        return err_payload(f"could not read feature file: {exc}", "READ_ERROR")

    target = next(
        (nd for nd in nodes if nd.get("id") == node_id_str and nd.get("op") == "jewelry_eternity_auto"),
        None,
    )
    if target is None:
        return err_payload(
            f"No jewelry_eternity_auto node with id={node_id_str!r} found", "NOT_FOUND"
        )

    stats = {
        "node_id": node_id_str,
        "stone_count": target.get("stone_count"),
        "total_carat": target.get("total_carat"),
        "pitch_mm": target.get("pitch_mm"),
        "gap_mm": target.get("gap_mm"),
        "coverage_pct": target.get("coverage_pct"),
        "metal_removed_mm3": target.get("metal_removed_mm3"),
        "metal_weight_estimate_g": target.get("metal_weight_estimate_g"),
        "thin_metal_warnings": target.get("thin_metal_warnings"),
        "warn": target.get("warn", ""),
    }
    return ok_payload(stats)
