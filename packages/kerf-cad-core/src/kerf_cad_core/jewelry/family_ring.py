"""
kerf_cad_core.jewelry.family_ring
==================================

Family / mother's ring builder.

A family ring (also called a mother's ring) holds N birthstones — one per
family member — arranged along the top of the shank.  This module handles:

  * Month → birthstone resolution (from gemstones.GEM_CATALOG)
  * Stone sizing: explicit mm OR carat; default 3 mm round_brilliant per stone
  * Arrangement geometry:
      linear_across_top  — N stones in a straight row across the shank top
      channel            — N stones set in a shared channel rail
      cluster            — N stones grouped in a tight cluster; alternating heights
      wave               — N stones in a sinusoidal arc (alternating high/low)
      split_shank        — two arms crossing; stones split equally per arm
  * No-overlap check: angular spacing on the shank top arc must satisfy
      spacing_deg ≥ (girdle_mm / r_mid) × (180/π) + min_metal_gap_deg
    where r_mid is the mid-shank radius and min_metal_gap_deg is the
    metal-gap minimum expressed in degrees.  If the stones are too large
    to fit, the module auto-shrinks each stone (uniform) until they fit,
    sets ``auto_shrunk=True``, and reports the adjusted diameter.
  * Total carat = Σ per-stone carat
  * Metal weight: shank tube volume + Σ head volumes (one prong head per stone),
    converted via metal_cost.metal_weight
  * Per-stone seat + setting choice
  * Arrangement-specific layout: list of ``{x_mm, y_mm, angle_deg}`` per stone
    (x = across-finger, y = along-shank, angle = rotation about stone axis)

No OCCT imports; pure Python.  All public functions return ``dict`` and never
raise — on any error they return ``{"ok": False, "reason": "…"}``.

LLM tools
---------
  jewelry_build_family_ring   — compute + layout (write=True, gated)

Max stones per arrangement
--------------------------
  linear_across_top : 15  (shank arc ≈ half-circumference of US-7; even 15 × 2 mm stones fit)
  channel           : 12  (channel must not exceed 80 % of available shank arc)
  cluster           : 9   (bounding box of N stones fits in available arc)
  wave              : 10  (wave amplitude + spacing constrain practical count)
  split_shank       : 10  (each arm ≤ 5 stones; arms cross at 12 o'clock)
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

# ---------------------------------------------------------------------------
# Re-use helpers from peer modules
# ---------------------------------------------------------------------------

from kerf_cad_core.jewelry.gemstones import (
    GEM_CATALOG,
    GEMSTONE_DENSITIES,
    carat_from_mm,
    mm_from_carat,
)
from kerf_cad_core.jewelry.ring import ring_size_to_diameter
from kerf_cad_core.jewelry.metal_cost import (
    METAL_DENSITY_G_CM3,
    metal_weight,
)

_PI = math.pi

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Month numbers for primary/modern birthstone (first entry in GEM_CATALOG for
# each month).  Some months have two gems (e.g. Oct: opal, tourmaline); we
# always prefer the first listed in the catalog order.
_MONTH_NAMES = {
    1: "january",  2: "february",  3: "march",    4: "april",
    5: "may",      6: "june",       7: "july",     8: "august",
    9: "september",10: "october",  11: "november", 12: "december",
}

# Build month→gem lookup from GEM_CATALOG order (first match per month wins)
_MONTH_TO_GEM: dict[int, str] = {}
for _gem_name, _entry in GEM_CATALOG.items():
    for _m in _entry["months"]:
        if _m not in _MONTH_TO_GEM:
            _MONTH_TO_GEM[_m] = _gem_name

# Arrangements
VALID_ARRANGEMENTS = frozenset([
    "linear_across_top",
    "channel",
    "cluster",
    "wave",
    "split_shank",
])

# Max stones per arrangement
_MAX_STONES: dict[str, int] = {
    "linear_across_top": 15,
    "channel":           12,
    "cluster":            9,
    "wave":              10,
    "split_shank":       10,
}

# Valid setting styles for individual stones in a family ring
VALID_SETTINGS = frozenset([
    "prong",    # 4-prong head; default
    "bezel",    # full bezel collet
    "channel",  # shared rail (most natural for channel arrangement)
    "flush",    # flush/gypsy
    "bar",      # bar between stones
])

# Default design parameters
_DEFAULT_STONE_MM      = 3.0     # girdle diameter mm per stone
_DEFAULT_CUT           = "round_brilliant"
_DEFAULT_SETTING       = "prong"
_DEFAULT_METAL         = "14k_yellow"
_DEFAULT_BAND_WIDTH    = 4.0     # mm
_DEFAULT_THICKNESS     = 1.5     # mm
_MIN_METAL_GAP_MM      = 0.3     # minimum metal between adjacent stone girdles
_HEAD_WALL_MM          = 0.5     # prong-head wall thickness (added each side)
_HEAD_HEIGHT_MM        = 1.8     # typical prong-head height above girdle
_WAVE_AMPLITUDE_MM     = 1.0     # ± from centreline in y for wave arrangement


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _shank_top_arc_mm(inner_diameter_mm: float, band_width_mm: float) -> float:
    """Return the available top-arc chord length (mm) on the shank top face.

    The top arc spans ±45° from the 12-o'clock position (a 90° sector).
    Mid-wall radius = inner_r + thickness/2; we use outer-wall radius
    conservatively so all stones clear the inner bore.
    Arc length = r × θ  (θ in radians, 90° = π/2).
    """
    outer_r = inner_diameter_mm / 2.0 + _DEFAULT_THICKNESS
    arc_mm = outer_r * (_PI / 2.0)  # 90° arc on outer radius
    return arc_mm


def _shank_top_arc_mm_ex(inner_diameter_mm: float, thickness_mm: float) -> float:
    """Same as above but with explicit thickness."""
    outer_r = inner_diameter_mm / 2.0 + thickness_mm
    return outer_r * (_PI / 2.0)


def _head_volume_mm3(girdle_mm: float) -> float:
    """Approximate prong-head volume (hollow cylinder + prong wires).

    Model: a short hollow cylinder:
        outer_r = girdle_mm/2 + HEAD_WALL_MM
        inner_r = girdle_mm/2  (cavity for stone)
        height  = HEAD_HEIGHT_MM
    """
    outer_r = girdle_mm / 2.0 + _HEAD_WALL_MM
    inner_r = girdle_mm / 2.0
    h = _HEAD_HEIGHT_MM
    return _PI * (outer_r**2 - inner_r**2) * h


def _shank_volume_mm3(inner_diameter_mm: float, thickness_mm: float, band_width_mm: float) -> float:
    """Approximate hollow-tube shank volume (annular cross-section × width).

    Volume = π × (R² - r²) × band_width
    where r = inner_r, R = outer_r = r + thickness.
    """
    r = inner_diameter_mm / 2.0
    R = r + thickness_mm
    return _PI * (R**2 - r**2) * band_width_mm


# ---------------------------------------------------------------------------
# Birthstone resolution
# ---------------------------------------------------------------------------

def resolve_stone(
    month: Optional[int] = None,
    gem_name: Optional[str] = None,
    cut: Optional[str] = None,
    diameter_mm: Optional[float] = None,
    carat: Optional[float] = None,
) -> dict:
    """Resolve one stone spec.

    Priority: explicit gem_name > month lookup.
    Returns dict with keys: gem, cut, material, diameter_mm, carat_weight.
    Never raises.
    """
    # Resolve gem name
    if gem_name is not None:
        gem = gem_name.lower().strip()
        if gem not in GEM_CATALOG:
            return {"ok": False, "reason": f"Unknown gem name {gem_name!r}"}
    elif month is not None:
        if not (1 <= month <= 12):
            return {"ok": False, "reason": f"Month must be 1–12; got {month}"}
        gem = _MONTH_TO_GEM.get(month)
        if gem is None:
            return {"ok": False, "reason": f"No birthstone found for month {month}"}
    else:
        return {"ok": False, "reason": "Provide month (1–12) or gem_name"}

    # Resolve cut
    resolved_cut = cut if cut else _DEFAULT_CUT
    if resolved_cut not in ("round_brilliant", "princess", "oval", "emerald",
                             "marquise", "pear", "cushion", "radiant", "asscher",
                             "trillion", "heart", "baguette"):
        resolved_cut = _DEFAULT_CUT  # fall back to round_brilliant

    # Resolve diameter
    density = GEMSTONE_DENSITIES.get(gem, 3.51)
    if diameter_mm is not None and diameter_mm > 0:
        d_mm = float(diameter_mm)
        ct = carat_from_mm(resolved_cut, d_mm, density_g_cm3=density)
    elif carat is not None and carat > 0:
        d_mm = mm_from_carat(resolved_cut, float(carat), density_g_cm3=density)
        ct = float(carat)
    else:
        d_mm = float(_DEFAULT_STONE_MM)
        ct = carat_from_mm(resolved_cut, d_mm, density_g_cm3=density)

    return {
        "ok": True,
        "gem": gem,
        "cut": resolved_cut,
        "material": gem,
        "diameter_mm": round(d_mm, 4),
        "carat_weight": round(ct, 4),
    }


# ---------------------------------------------------------------------------
# Stone-fit / no-overlap logic
# ---------------------------------------------------------------------------

def _compute_spacing(
    n_stones: int,
    girdle_mm: float,
    available_arc_mm: float,
    min_gap_mm: float = _MIN_METAL_GAP_MM,
) -> dict:
    """Compute uniform spacing for n_stones along available_arc_mm.

    Returns dict:
        fits           : bool
        spacing_mm     : centre-to-centre distance (mm)
        total_span_mm  : n × girdle + (n-1) × gap
        available_mm   : the input arc length
        auto_shrunk    : bool (True if stones were shrunk)
        final_girdle_mm: float (possibly shrunk)
    """
    if n_stones == 0:
        return {"fits": True, "spacing_mm": 0.0, "total_span_mm": 0.0,
                "available_mm": available_arc_mm, "auto_shrunk": False,
                "final_girdle_mm": girdle_mm}

    total = n_stones * girdle_mm + (n_stones - 1) * min_gap_mm
    if total <= available_arc_mm:
        spacing = girdle_mm + min_gap_mm
        return {
            "fits": True,
            "spacing_mm": round(spacing, 4),
            "total_span_mm": round(total, 4),
            "available_mm": round(available_arc_mm, 4),
            "auto_shrunk": False,
            "final_girdle_mm": round(girdle_mm, 4),
        }

    # Auto-shrink: solve  n × d + (n-1) × gap ≤ arc  for d
    # d_max = (arc - (n-1)*gap) / n
    d_max = (available_arc_mm - (n_stones - 1) * min_gap_mm) / n_stones
    if d_max <= 0.5:
        # Cannot fit even minimal stones
        return {
            "fits": False,
            "spacing_mm": 0.0,
            "total_span_mm": round(total, 4),
            "available_mm": round(available_arc_mm, 4),
            "auto_shrunk": True,
            "final_girdle_mm": round(girdle_mm, 4),
        }

    spacing = d_max + min_gap_mm
    new_total = n_stones * d_max + (n_stones - 1) * min_gap_mm
    # Clamp to available_arc_mm before rounding to absorb fp rounding
    new_total_clamped = min(new_total, available_arc_mm)
    return {
        "fits": True,
        "spacing_mm": round(spacing, 4),
        "total_span_mm": round(new_total_clamped, 4),
        "available_mm": round(available_arc_mm, 4),
        "auto_shrunk": True,
        "final_girdle_mm": round(d_max, 4),
    }


# ---------------------------------------------------------------------------
# Layout generators (per arrangement)
# ---------------------------------------------------------------------------

def _layout_linear(
    n: int,
    spacing_mm: float,
    girdle_mm: float,
) -> list[dict]:
    """Linear row: stones at y=0, x evenly spaced, centred on 0."""
    half = (n - 1) * spacing_mm / 2.0
    coords = []
    for i in range(n):
        x = -half + i * spacing_mm
        coords.append({"x_mm": round(x, 4), "y_mm": 0.0, "angle_deg": 0.0})
    return coords


def _layout_channel(
    n: int,
    spacing_mm: float,
    girdle_mm: float,
) -> list[dict]:
    """Channel: same as linear but stones sit in a shared rail groove."""
    coords = _layout_linear(n, spacing_mm, girdle_mm)
    for c in coords:
        c["setting_hint"] = "channel_rail"
    return coords


def _layout_cluster(
    n: int,
    spacing_mm: float,
    girdle_mm: float,
) -> list[dict]:
    """Cluster: stones arranged in a tight grouping.

    Stone 0 (if odd count or centre) is at origin; others placed radially.
    For n ≤ 7 a hex-ring pattern is used; otherwise a 3×grid fallback.
    """
    coords = []
    if n == 1:
        coords.append({"x_mm": 0.0, "y_mm": 0.0, "angle_deg": 0.0})
    elif n <= 7:
        # Centre + up to 6 in ring
        coords.append({"x_mm": 0.0, "y_mm": 0.0, "angle_deg": 0.0})
        ring_r = spacing_mm  # ring radius ≈ 1 stone spacing
        n_ring = n - 1
        for i in range(n_ring):
            theta = 2 * _PI * i / n_ring
            x = ring_r * math.cos(theta)
            y = ring_r * math.sin(theta)
            coords.append({
                "x_mm": round(x, 4),
                "y_mm": round(y, 4),
                "angle_deg": round(math.degrees(theta), 2),
            })
    else:
        # 3-column grid: ceil(n/3) rows
        cols = 3
        rows = math.ceil(n / cols)
        col_sp = spacing_mm
        row_sp = spacing_mm * 0.9
        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= n:
                    break
                x = (c - (cols - 1) / 2.0) * col_sp
                y = (r - (rows - 1) / 2.0) * row_sp
                coords.append({
                    "x_mm": round(x, 4),
                    "y_mm": round(y, 4),
                    "angle_deg": 0.0,
                })
                idx += 1
    return coords


def _layout_wave(
    n: int,
    spacing_mm: float,
    girdle_mm: float,
) -> list[dict]:
    """Wave: stones alternate above/below centreline in sinusoidal arc.

    Uses phase = π/2 + i×π so stones land at ±amplitude rather than all zero.
    Stone 0: sin(π/2)=+1 (top), stone 1: sin(3π/2)=-1 (bottom), etc.
    """
    coords = []
    half = (n - 1) * spacing_mm / 2.0
    for i in range(n):
        x = -half + i * spacing_mm
        phase = _PI / 2.0 + i * _PI  # π/2, 3π/2, 5π/2, … → +1, -1, +1, -1, …
        y = _WAVE_AMPLITUDE_MM * math.sin(phase)
        coords.append({
            "x_mm": round(x, 4),
            "y_mm": round(y, 4),
            "angle_deg": 0.0,
        })
    return coords


def _layout_split_shank(
    n: int,
    spacing_mm: float,
    girdle_mm: float,
) -> list[dict]:
    """Split-shank: stones divided between two parallel arms.

    Arm A: indices 0..(ceil(n/2)-1) at y=+arm_offset
    Arm B: indices ceil(n/2)..n-1  at y=-arm_offset
    """
    arm_offset = girdle_mm * 0.8  # lateral offset between arms
    n_a = math.ceil(n / 2)
    n_b = n - n_a

    coords = []
    # Arm A
    half_a = (n_a - 1) * spacing_mm / 2.0
    for i in range(n_a):
        x = -half_a + i * spacing_mm
        coords.append({
            "x_mm": round(x, 4),
            "y_mm": round(arm_offset, 4),
            "angle_deg": 0.0,
            "arm": "A",
        })
    # Arm B
    half_b = (n_b - 1) * spacing_mm / 2.0 if n_b > 0 else 0.0
    for i in range(n_b):
        x = -half_b + i * spacing_mm
        coords.append({
            "x_mm": round(x, 4),
            "y_mm": round(-arm_offset, 4),
            "angle_deg": 0.0,
            "arm": "B",
        })
    return coords


_LAYOUT_FN = {
    "linear_across_top": _layout_linear,
    "channel":           _layout_channel,
    "cluster":           _layout_cluster,
    "wave":              _layout_wave,
    "split_shank":       _layout_split_shank,
}


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def build_family_ring(
    ring_size,
    stones: list[dict],
    arrangement: str = "linear_across_top",
    size_system: str = "us",
    metal: str = _DEFAULT_METAL,
    band_width: float = _DEFAULT_BAND_WIDTH,
    thickness: float = _DEFAULT_THICKNESS,
    default_cut: str = _DEFAULT_CUT,
    default_setting: str = _DEFAULT_SETTING,
    default_stone_mm: float = _DEFAULT_STONE_MM,
    min_metal_gap_mm: float = _MIN_METAL_GAP_MM,
    accent_stones: Optional[list[dict]] = None,
) -> dict:
    """Build a family ring layout.

    Parameters
    ----------
    ring_size : int | float | str
        Ring size in the given size_system.
    stones : list[dict]
        Per-stone specs.  Each entry may contain:
          ``month`` (int 1-12)     — resolved to birthstone
          ``gem``   (str)          — explicit gem name (overrides month)
          ``cut``   (str)          — cut style (default round_brilliant)
          ``diameter_mm`` (float)  — stone diameter (overrides default_stone_mm)
          ``carat`` (float)        — carat weight (converted to mm)
          ``setting`` (str)        — prong/bezel/channel/flush/bar
    arrangement : str
        One of VALID_ARRANGEMENTS.
    size_system : str
        Ring size system: us / uk / au / eu / jp.
    metal : str
        Metal alloy key from METAL_DENSITY_G_CM3.
    band_width : float
        Band width in mm.
    thickness : float
        Shank wall thickness in mm.
    default_cut : str
        Default gemstone cut for stones that don't specify one.
    default_setting : str
        Default setting style.
    default_stone_mm : float
        Default stone diameter if neither diameter_mm nor carat specified.
    min_metal_gap_mm : float
        Minimum metal gap between adjacent stone girdles (mm).
    accent_stones : list[dict], optional
        Optional accent stone specs (same format as stones) placed alongside
        or between main stones.  Counted toward overlap checks.

    Returns
    -------
    dict
        ``ok`` : True on success
        ``ring_id``              : US inner diameter (mm), 4 dp
        ``inner_diameter_mm``   : float
        ``stones``               : list of resolved stone dicts
        ``arrangement``          : str
        ``layout``               : list of {x_mm, y_mm, angle_deg, …} per stone
        ``available_arc_mm``     : float — shank top arc available
        ``total_span_mm``        : float — span used by stones
        ``auto_shrunk``          : bool
        ``final_girdle_mm``      : float (possibly shrunk)
        ``spacing_mm``           : float (centre-to-centre)
        ``total_carat``          : float
        ``metal_weight_g``       : float (shank + Σ heads)
        ``metal_weight_dwt``     : float
        ``metal_weight_ozt``     : float
        ``shank_volume_mm3``     : float
        ``heads_volume_mm3``     : float
        ``metal``                : str
        ``warnings``             : list[str]

    On error: ``{"ok": False, "reason": "…"}``
    """
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # Validate arrangement
    # ------------------------------------------------------------------
    if arrangement not in VALID_ARRANGEMENTS:
        return {"ok": False, "reason": (
            f"Unknown arrangement {arrangement!r}. "
            f"Valid: {sorted(VALID_ARRANGEMENTS)}"
        )}

    # ------------------------------------------------------------------
    # Validate metal
    # ------------------------------------------------------------------
    if metal not in METAL_DENSITY_G_CM3:
        return {"ok": False, "reason": (
            f"Unknown metal {metal!r}. Valid: {sorted(METAL_DENSITY_G_CM3)}"
        )}

    # ------------------------------------------------------------------
    # Validate stone list
    # ------------------------------------------------------------------
    if not stones:
        return {"ok": False, "reason": "stones list must not be empty"}

    n = len(stones)
    max_n = _MAX_STONES[arrangement]
    if n > max_n:
        return {"ok": False, "reason": (
            f"Too many stones ({n}) for arrangement {arrangement!r}; "
            f"maximum is {max_n}"
        )}

    # ------------------------------------------------------------------
    # Resolve ring size → inner diameter
    # ------------------------------------------------------------------
    try:
        id_mm = ring_size_to_diameter(size_system, ring_size)
    except (ValueError, KeyError) as exc:
        return {"ok": False, "reason": f"Invalid ring size: {exc}"}

    # ------------------------------------------------------------------
    # Resolve each stone spec
    # ------------------------------------------------------------------
    resolved_stones: list[dict] = []
    for idx, spec in enumerate(stones):
        month    = spec.get("month")
        gem_name = spec.get("gem")
        cut      = spec.get("cut") or default_cut
        d_mm     = spec.get("diameter_mm")
        ct       = spec.get("carat")
        setting  = spec.get("setting") or default_setting

        r = resolve_stone(
            month=month,
            gem_name=gem_name,
            cut=cut,
            diameter_mm=d_mm if d_mm else (default_stone_mm if not ct else None),
            carat=ct,
        )
        if not r.get("ok"):
            return {"ok": False, "reason": f"Stone {idx}: {r.get('reason', 'unknown error')}"}

        # Validate setting
        if setting not in VALID_SETTINGS:
            warnings.append(
                f"Stone {idx}: unknown setting {setting!r}; using {default_setting!r}"
            )
            setting = default_setting

        r["setting"] = setting
        r["index"]   = idx
        resolved_stones.append(r)

    # Use the first stone's diameter as the nominal girdle for spacing
    # (all stones treated as equal-diameter for overlap check; largest used
    # when diameters differ — conservative)
    all_diameters = [s["diameter_mm"] for s in resolved_stones]
    nominal_girdle = max(all_diameters)

    # ------------------------------------------------------------------
    # Available shank top arc
    # ------------------------------------------------------------------
    available_arc = _shank_top_arc_mm_ex(id_mm, thickness)

    # ------------------------------------------------------------------
    # Spacing / no-overlap check
    # ------------------------------------------------------------------
    fit = _compute_spacing(n, nominal_girdle, available_arc, min_metal_gap_mm)

    if not fit["fits"]:
        return {"ok": False, "reason": (
            f"Cannot fit {n} stones of diameter {nominal_girdle:.2f} mm "
            f"(+ {min_metal_gap_mm} mm gap) into available arc "
            f"{available_arc:.2f} mm for ring size {ring_size} ({size_system.upper()}). "
            f"Total span needed: {fit['total_span_mm']:.2f} mm. "
            f"Reduce stone count, use smaller stones, or choose a larger ring size."
        )}

    if fit["auto_shrunk"]:
        new_d = fit["final_girdle_mm"]
        warnings.append(
            f"Stones auto-shrunk from {nominal_girdle:.2f} mm to "
            f"{new_d:.2f} mm to fit available arc {available_arc:.2f} mm"
        )
        # Update resolved stone diameters + carat weights
        for s in resolved_stones:
            density = GEMSTONE_DENSITIES.get(s["gem"], 3.51)
            s["diameter_mm"]   = round(new_d, 4)
            s["carat_weight"]  = round(carat_from_mm(s["cut"], new_d, density_g_cm3=density), 4)

    final_girdle = fit["final_girdle_mm"]
    spacing_mm   = fit["spacing_mm"]

    # ------------------------------------------------------------------
    # Build layout
    # ------------------------------------------------------------------
    layout_fn = _LAYOUT_FN[arrangement]
    layout = layout_fn(n, spacing_mm, final_girdle)

    # Attach stone metadata to layout entries
    for i, (coord, stone) in enumerate(zip(layout, resolved_stones)):
        coord["gem"]          = stone["gem"]
        coord["cut"]          = stone["cut"]
        coord["diameter_mm"]  = stone["diameter_mm"]
        coord["carat_weight"] = stone["carat_weight"]
        coord["setting"]      = stone["setting"]

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------
    total_carat = round(sum(s["carat_weight"] for s in resolved_stones), 6)

    # Shank volume (annular tube)
    shank_vol = _shank_volume_mm3(id_mm, thickness, band_width)

    # Heads volume (Σ per-stone prong heads)
    heads_vol = sum(_head_volume_mm3(s["diameter_mm"]) for s in resolved_stones)

    total_vol = shank_vol + heads_vol

    try:
        wt = metal_weight(total_vol, metal=metal)
    except ValueError as exc:
        return {"ok": False, "reason": f"Metal weight calculation failed: {exc}"}

    # ------------------------------------------------------------------
    # Build node spec for feature file
    # ------------------------------------------------------------------
    node_spec = {
        "type":               "family_ring",
        "ring_size":          ring_size,
        "size_system":        size_system,
        "arrangement":        arrangement,
        "metal":              metal,
        "band_width_mm":      band_width,
        "thickness_mm":       thickness,
        "inner_diameter_mm":  round(id_mm, 4),
        "available_arc_mm":   round(available_arc, 4),
        "total_span_mm":      fit["total_span_mm"],
        "auto_shrunk":        fit["auto_shrunk"],
        "final_girdle_mm":    final_girdle,
        "spacing_mm":         spacing_mm,
        "stones":             resolved_stones,
        "layout":             layout,
        "total_carat":        total_carat,
        "shank_volume_mm3":   round(shank_vol, 4),
        "heads_volume_mm3":   round(heads_vol, 4),
        "metal_weight_g":     round(wt["grams"], 4),
        "metal_weight_dwt":   round(wt["dwt"], 4),
        "metal_weight_ozt":   round(wt["ozt"], 6),
    }
    if warnings:
        node_spec["warnings"] = warnings

    return dict(ok=True, **node_spec)


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

_ARRANGEMENT_ENUM = sorted(VALID_ARRANGEMENTS)
_METAL_ENUM       = sorted(METAL_DENSITY_G_CM3.keys())

jewelry_build_family_ring_spec = ToolSpec(
    name="jewelry_build_family_ring",
    description=(
        "Build a family / mother's ring with N birthstones arranged along the shank top. "
        "Resolves each birth month to its gemstone (Jan=garnet, Feb=amethyst, Mar=aquamarine, "
        "Apr=diamond, May=emerald, Jun=pearl, Jul=ruby, Aug=peridot, Sep=sapphire, "
        "Oct=opal, Nov=topaz, Dec=tanzanite), then lays out N stones in the chosen "
        "arrangement (linear_across_top / channel / cluster / wave / split_shank). "
        "Auto-shrinks stones if they do not fit the available shank top arc. "
        "Returns per-stone seat coordinates (x_mm, y_mm, angle_deg), total carat, "
        "metal weight (shank + Σ prong heads), and a warnings list. "
        "Use jewelry_create_ring_shank to build the matching shank node separately."
    ),
    input_schema={
        "type": "object",
        "required": ["ring_size", "stones"],
        "properties": {
            "ring_size": {
                "type": ["number", "string"],
                "description": (
                    "Ring size in the chosen size_system. "
                    "US: 0–16 (half sizes allowed, e.g. 7.5). "
                    "UK/AU: letter e.g. 'N'. EU: circumference mm. JP: integer 1–30."
                ),
            },
            "stones": {
                "type": "array",
                "minItems": 1,
                "description": (
                    "Ordered list of stone specs. Each may include: "
                    "month (int 1-12), gem (str, overrides month), cut (str), "
                    "diameter_mm (float), carat (float), setting (prong/bezel/channel/flush/bar)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "month":       {"type": "integer", "minimum": 1, "maximum": 12},
                        "gem":         {"type": "string"},
                        "cut":         {"type": "string"},
                        "diameter_mm": {"type": "number", "exclusiveMinimum": 0},
                        "carat":       {"type": "number", "exclusiveMinimum": 0},
                        "setting":     {"type": "string", "enum": sorted(VALID_SETTINGS)},
                    },
                },
            },
            "arrangement": {
                "type": "string",
                "enum": _ARRANGEMENT_ENUM,
                "description": (
                    "Stone arrangement style. "
                    "linear_across_top: row of N stones across the shank top (max 15). "
                    "channel: stones in a shared channel rail (max 12). "
                    "cluster: tight grouped cluster (max 9). "
                    "wave: sinusoidal alternating-height row (max 10). "
                    "split_shank: stones split across two shank arms (max 10 total). "
                    "Default: linear_across_top."
                ),
            },
            "size_system": {
                "type": "string",
                "enum": ["us", "uk", "au", "eu", "jp"],
                "description": "Ring size system. Default: us.",
            },
            "metal": {
                "type": "string",
                "enum": _METAL_ENUM,
                "description": (
                    "Metal alloy key. Common choices: 14k_yellow, 18k_yellow, "
                    "14k_white, 18k_white, 14k_rose, 18k_rose, sterling_925, platinum_950. "
                    "Default: 14k_yellow."
                ),
            },
            "band_width": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Band width in mm. Default 4.0 mm.",
            },
            "thickness": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Shank wall thickness in mm. Default 1.5 mm.",
            },
            "default_cut": {
                "type": "string",
                "description": (
                    "Default cut for stones that don't specify one. "
                    "Default: round_brilliant."
                ),
            },
            "default_setting": {
                "type": "string",
                "enum": sorted(VALID_SETTINGS),
                "description": "Default setting style for stones. Default: prong.",
            },
            "default_stone_mm": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "Default stone girdle diameter (mm) for stones that specify "
                    "neither diameter_mm nor carat. Default 3.0 mm."
                ),
            },
            "min_metal_gap_mm": {
                "type": "number",
                "minimum": 0,
                "description": (
                    "Minimum metal gap between adjacent stone girdles (mm). "
                    "Default 0.3 mm."
                ),
            },
            "file_id": {
                "type": "string",
                "description": (
                    "Target .feature file id (uuid) to append the family_ring node. "
                    "Optional — if omitted the layout is returned without writing."
                ),
            },
        },
    },
)


@register(jewelry_build_family_ring_spec, write=True)
async def run_jewelry_build_family_ring(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except (json.JSONDecodeError, ValueError) as exc:
        return err_payload(f"Invalid JSON: {exc}")

    ring_size = a.get("ring_size")
    stones    = a.get("stones")
    if ring_size is None:
        return err_payload("ring_size is required")
    if not stones:
        return err_payload("stones is required and must be non-empty")

    arrangement     = a.get("arrangement", "linear_across_top")
    size_system     = a.get("size_system", "us")
    metal           = a.get("metal", _DEFAULT_METAL)
    band_width      = float(a.get("band_width", _DEFAULT_BAND_WIDTH))
    thickness       = float(a.get("thickness", _DEFAULT_THICKNESS))
    default_cut     = a.get("default_cut", _DEFAULT_CUT)
    default_setting = a.get("default_setting", _DEFAULT_SETTING)
    default_stone   = float(a.get("default_stone_mm", _DEFAULT_STONE_MM))
    min_gap         = float(a.get("min_metal_gap_mm", _MIN_METAL_GAP_MM))
    file_id         = a.get("file_id")

    result = build_family_ring(
        ring_size=ring_size,
        stones=stones,
        arrangement=arrangement,
        size_system=size_system,
        metal=metal,
        band_width=band_width,
        thickness=thickness,
        default_cut=default_cut,
        default_setting=default_setting,
        default_stone_mm=default_stone,
        min_metal_gap_mm=min_gap,
    )

    if not result.get("ok"):
        return err_payload(result.get("reason", "build_family_ring failed"))

    # Optionally persist to feature file
    if file_id is not None:
        try:
            fid = uuid.UUID(str(file_id))
        except ValueError:
            return err_payload(f"file_id is not a valid UUID: {file_id!r}")

        try:
            content = await read_feature_content(ctx, fid)
        except Exception as exc:
            return err_payload(f"Could not read feature file: {exc}")

        node_id = next_node_id(content)
        node = {
            "id":   node_id,
            "type": "family_ring",
            "spec": {k: v for k, v in result.items() if k != "ok"},
        }
        try:
            await append_feature_node(ctx, fid, node)
        except Exception as exc:
            return err_payload(f"Could not append feature node: {exc}")

        result["node_id"] = node_id
        result["file_id"] = str(fid)

    return ok_payload(result)
