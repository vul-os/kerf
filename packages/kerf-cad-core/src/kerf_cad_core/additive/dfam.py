"""
kerf_cad_core.additive.dfam — pure-Python additive-manufacturing / DFAM
process-planning calculations.

Implements eleven public functions:

  process_params(process)
      Built-in process parameter record for FDM/SLA/SLS/MJF/DMLS.

  build_time_estimate(process, bounding_box_m, layer_thickness_m,
                      fill_fraction, travel_speed_ms, deposit_speed_ms)
      Build-time estimate: layer_count × layer_time + travel overhead.

  support_volume(part_volume_m3, projected_area_m2, overhang_fraction,
                 support_density)
      Estimated support-structure volume from overhang projection.

  overhang_removability(process, overhang_angle_deg)
      Assess whether overhangs at the given angle need support and how
      removable that support is.

  orientation_cost(part_bbox_m, surface_area_m2, overhang_area_m2,
                   process)
      Scalar cost for a given build orientation
      (support + build height + surface quality tradeoff).

  best_orientation(part_bbox_m_list, surface_area_m2, overhang_areas_m2,
                   process)
      Pick the lowest-cost orientation from N candidate bounding-boxes.

  shrinkage_compensation(nominal_dim_m, process, material)
      Scaled model dimension needed to achieve the nominal size after
      process-specific shrinkage.

  lattice_infill(process, infill_type, relative_density,
                 solid_modulus_Pa, solid_density_kg_m3,
                 volume_m3)
      Gibson-Ashby lattice: effective modulus, mass, and relative density
      validation for gyroid or cubic topology.

  feature_checks(process, wall_thickness_m, hole_diameter_m,
                 bridge_span_m)
      Minimum feature / wall / hole / bridging-span checks per process.

  cost_rollup(process, material, build_time_s, support_volume_m3,
              part_volume_m3, machine_rate_per_h, material_cost_per_kg,
              post_cost)
      Total part cost: machine-hour + material + post-processing.

  nesting_packing(build_volume_m3, part_volume_m3, n_parts,
                  packing_factor)
      Powder-bed nesting: effective packing factor and batch throughput.

All functions return plain dicts:
    success → {"ok": True, ...fields..., "warnings": [...]}
    failure → {"ok": False, "reason": "<human-readable>"}

Functions NEVER raise; invalid inputs return {"ok": False, ...}.
Warnings are collected in the "warnings" list; never raised as exceptions.

References
----------
Gibson, I., Rosen, D. & Stucker, B. "Additive Manufacturing Technologies",
    Springer, 2nd ed., 2015.
Gibson, L.J. & Ashby, M.F. "Cellular Solids: Structure and Properties",
    Cambridge, 2nd ed., 1997.
EOS GmbH — "EOS P 396 Material Data Sheet" (SLS).
Thomas, D. "The Development of Design Rules for Selective Laser Melting",
    PhD thesis, University of Wales, 2009.
Materialise "Design Guidelines for SLS/MJF" (2022).
Formlabs "Engineering Design Guide" (2023).

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Built-in process parameter table
# ---------------------------------------------------------------------------

#: Default critical overhang angle below which support is required (degrees
#: from vertical, i.e. from build direction).  Convention: 0° = vertical wall
#: (no support needed); 90° = horizontal ceiling (always needs support).
#: Values represent the threshold at which self-support typically fails.
_OVERHANG_THRESHOLD_DEG: dict[str, float] = {
    "FDM": 45.0,
    "SLA": 30.0,   # resin drag force is lower; can print shallower without support
    "SLS": 90.0,   # powder bed is self-supporting — no support structures needed
    "MJF": 90.0,   # powder-bed; no support needed
    "DMLS": 45.0,
}

#: Minimum wall thickness by process (metres).
_MIN_WALL_M: dict[str, float] = {
    "FDM": 0.0008,   # ~0.8 mm (two-bead wall at 0.4 mm nozzle)
    "SLA": 0.0006,   # ~0.6 mm
    "SLS": 0.0007,   # ~0.7 mm
    "MJF": 0.0006,   # ~0.6 mm
    "DMLS": 0.0004,  # ~0.4 mm
}

#: Minimum hole diameter by process (metres).
_MIN_HOLE_M: dict[str, float] = {
    "FDM": 0.0015,
    "SLA": 0.0005,
    "SLS": 0.0015,
    "MJF": 0.0015,
    "DMLS": 0.0008,
}

#: Maximum self-supporting bridge span by process (metres).
_MAX_BRIDGE_M: dict[str, float] = {
    "FDM": 0.020,   # ~20 mm unsupported bridge
    "SLA": 0.012,
    "SLS": 0.060,   # powder supports
    "MJF": 0.060,
    "DMLS": 0.010,
}

#: Typical layer thickness range used for build-time calculations (metres).
_DEFAULT_LAYER_M: dict[str, float] = {
    "FDM": 0.0002,
    "SLA": 0.0001,
    "SLS": 0.0001,
    "MJF": 0.0001,
    "DMLS": 0.00006,
}

#: Typical build-platform speeds (seconds per layer × cm² of projected area).
#: Used as fallback when caller does not supply deposit/travel speeds.
#: Units: s / (layer × m²) — time to deposit one layer of 1 m² cross-section.
_LAYER_TIME_PER_M2: dict[str, float] = {
    "FDM": 60.0,    # ~1 min / layer-cm² at 0.4 mm nozzle, 60 mm/s
    "SLA": 30.0,
    "SLS": 40.0,
    "MJF": 35.0,
    "DMLS": 120.0,  # slower scan speed, fine detail
}

#: Typical shrinkage fractions (linear, not volumetric) per process+material.
#: Format: {process: {material: fraction}}.  Values from published data.
_SHRINKAGE: dict[str, dict[str, float]] = {
    "FDM": {
        "PLA": 0.003,
        "ABS": 0.008,
        "PETG": 0.004,
        "Nylon": 0.012,
        "default": 0.005,
    },
    "SLA": {
        "standard_resin": 0.002,
        "engineering_resin": 0.003,
        "default": 0.002,
    },
    "SLS": {
        "PA12": 0.030,
        "PA11": 0.028,
        "TPU": 0.015,
        "default": 0.030,
    },
    "MJF": {
        "PA12": 0.028,
        "PA11": 0.026,
        "default": 0.027,
    },
    "DMLS": {
        "316L": 0.001,
        "AlSi10Mg": 0.003,
        "Ti6Al4V": 0.001,
        "Inconel625": 0.001,
        "default": 0.002,
    },
}

#: Material densities (kg/m³).
_MATERIAL_DENSITY: dict[str, float] = {
    # FDM filaments
    "PLA": 1240.0,
    "ABS": 1050.0,
    "PETG": 1270.0,
    "Nylon": 1100.0,
    # SLA resins (approximate)
    "standard_resin": 1100.0,
    "engineering_resin": 1150.0,
    # SLS/MJF powders
    "PA12": 1010.0,
    "PA11": 1030.0,
    "TPU": 1210.0,
    # DMLS metals
    "316L": 7980.0,
    "AlSi10Mg": 2670.0,
    "Ti6Al4V": 4430.0,
    "Inconel625": 8440.0,
    # generic fallback
    "default": 1200.0,
}

#: Typical machine hourly rates (USD/h).  Conservative mid-market estimates.
_DEFAULT_MACHINE_RATE: dict[str, float] = {
    "FDM": 3.0,
    "SLA": 8.0,
    "SLS": 25.0,
    "MJF": 20.0,
    "DMLS": 80.0,
}

_VALID_PROCESSES = ("FDM", "SLA", "SLS", "MJF", "DMLS")
_VALID_INFILL = ("gyroid", "cubic")


def _w(warnings: list[str], msg: str) -> None:
    """Append a warning string (never raises)."""
    warnings.append(msg)


def _bad(reason: str) -> dict[str, Any]:
    return {"ok": False, "reason": reason}


# ---------------------------------------------------------------------------
# 1. process_params
# ---------------------------------------------------------------------------

def process_params(process: str) -> dict[str, Any]:
    """Return the built-in parameter record for the named AM process.

    Parameters
    ----------
    process:
        One of "FDM", "SLA", "SLS", "MJF", "DMLS".

    Returns
    -------
    dict with ok=True and process parameters, or ok=False with reason.
    """
    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(
            f"unknown process '{process}'; valid: {list(_VALID_PROCESSES)}"
        )
    return {
        "ok": True,
        "process": p,
        "overhang_threshold_deg": _OVERHANG_THRESHOLD_DEG[p],
        "min_wall_m": _MIN_WALL_M[p],
        "min_hole_m": _MIN_HOLE_M[p],
        "max_bridge_m": _MAX_BRIDGE_M[p],
        "default_layer_m": _DEFAULT_LAYER_M[p],
        "layer_time_per_m2": _LAYER_TIME_PER_M2[p],
        "default_machine_rate_usd_h": _DEFAULT_MACHINE_RATE[p],
        "needs_support": p in ("FDM", "SLA", "DMLS"),
        "powder_bed": p in ("SLS", "MJF"),
        "shrinkage_materials": list(_SHRINKAGE[p].keys()),
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# 2. build_time_estimate
# ---------------------------------------------------------------------------

def build_time_estimate(
    process: str,
    bounding_box_m: tuple[float, float, float],
    *,
    layer_thickness_m: float | None = None,
    fill_fraction: float = 0.20,
    travel_overhead_frac: float = 0.15,
    cross_section_m2: float | None = None,
) -> dict[str, Any]:
    """Estimate build time for an AM part.

    Model:
        layer_count = build_height / layer_thickness
        layer_time  = cross_section_m2 * layer_time_per_m2 * fill_fraction
        travel_time = layer_count * layer_time * travel_overhead_frac
        total       = layer_count * layer_time + travel_time

    Parameters
    ----------
    process:
        AM process name.
    bounding_box_m:
        (x, y, z) bounding box dimensions in metres.  z is the build height.
    layer_thickness_m:
        Layer thickness (m).  Defaults to process default.
    fill_fraction:
        Fraction of the bounding-box cross-section that is solid material.
        Represents average fill density + shell (default 0.20 = 20%).
    travel_overhead_frac:
        Fractional travel/recoating overhead added to deposit time
        (default 0.15 = 15%).
    cross_section_m2:
        Override average cross-section area (m²).  Defaults to x*y.

    Returns
    -------
    dict with ok=True and build_time_s, layer_count, etc.
    """
    warnings: list[str] = []

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    if not (isinstance(bounding_box_m, (list, tuple)) and len(bounding_box_m) == 3):
        return _bad("bounding_box_m must be a 3-element sequence (x, y, z)")
    x_m, y_m, z_m = (float(v) for v in bounding_box_m)
    if x_m <= 0 or y_m <= 0 or z_m <= 0:
        return _bad("all bounding_box_m dimensions must be > 0")

    lt = float(layer_thickness_m) if layer_thickness_m is not None else _DEFAULT_LAYER_M[p]
    if lt <= 0:
        return _bad("layer_thickness_m must be > 0")

    ff = float(fill_fraction)
    if not (0.0 < ff <= 1.0):
        return _bad("fill_fraction must be in (0, 1]")

    tof = float(travel_overhead_frac)
    if tof < 0:
        return _bad("travel_overhead_frac must be >= 0")

    cs = float(cross_section_m2) if cross_section_m2 is not None else x_m * y_m
    if cs <= 0:
        return _bad("cross_section_m2 must be > 0")

    layer_count = math.ceil(z_m / lt)
    # time to deposit one layer = cross-section × fill fraction × rate
    time_per_layer_s = cs * ff * _LAYER_TIME_PER_M2[p]
    deposit_time_s = layer_count * time_per_layer_s
    travel_time_s = deposit_time_s * tof
    total_s = deposit_time_s + travel_time_s

    # Sanity warning for very short build times
    if total_s < 60:
        _w(warnings, "estimated build time < 1 min; check inputs")
    if layer_count > 50_000:
        _w(warnings, f"high layer count ({layer_count}); verify layer_thickness_m")

    return {
        "ok": True,
        "process": p,
        "layer_count": layer_count,
        "layer_thickness_m": lt,
        "time_per_layer_s": round(time_per_layer_s, 4),
        "deposit_time_s": round(deposit_time_s, 2),
        "travel_time_s": round(travel_time_s, 2),
        "build_time_s": round(total_s, 2),
        "build_time_h": round(total_s / 3600.0, 4),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3. support_volume
# ---------------------------------------------------------------------------

def support_volume(
    part_volume_m3: float,
    projected_area_m2: float,
    overhang_fraction: float = 0.20,
    support_density: float = 0.15,
    support_height_m: float | None = None,
    bounding_z_m: float | None = None,
) -> dict[str, Any]:
    """Estimate support-structure volume from overhang projection.

    Model:
        support_footprint = projected_area * overhang_fraction
        support_volume    = support_footprint * support_height * support_density

    If support_height_m is not supplied, bounding_z_m / 2 is used as a
    conservative mid-part estimate.

    Parameters
    ----------
    part_volume_m3:
        Solid part volume (m³). Must be > 0.
    projected_area_m2:
        Top-down projected area of the part (m²). Must be > 0.
    overhang_fraction:
        Fraction of projected area that forms unsupported overhangs (0–1).
    support_density:
        Volumetric fill density of the support structure (0–1, default 0.15).
    support_height_m:
        Average height over which supports span (m).
    bounding_z_m:
        Bounding box height used if support_height_m is not provided.

    Returns
    -------
    dict with support_volume_m3 and support_to_part_ratio.
    """
    warnings: list[str] = []

    pv = float(part_volume_m3)
    pa = float(projected_area_m2)
    if pv <= 0:
        return _bad("part_volume_m3 must be > 0")
    if pa <= 0:
        return _bad("projected_area_m2 must be > 0")
    of = float(overhang_fraction)
    if not (0.0 <= of <= 1.0):
        return _bad("overhang_fraction must be in [0, 1]")
    sd = float(support_density)
    if not (0.0 < sd <= 1.0):
        return _bad("support_density must be in (0, 1]")

    if support_height_m is not None:
        sh = float(support_height_m)
        if sh <= 0:
            return _bad("support_height_m must be > 0")
    elif bounding_z_m is not None:
        sh = float(bounding_z_m) / 2.0
    else:
        # crude fallback: assume supports span ~20% of part height guessed from V/A
        sh = pv / pa * 0.2

    sv = pa * of * sh * sd
    ratio = sv / pv if pv > 0 else 0.0

    if ratio > 0.5:
        _w(warnings, f"support volume {ratio:.0%} of part volume — consider reorienting")
    if of >= 0.5:
        _w(warnings, "overhang_fraction >= 50%; high support volume expected")

    return {
        "ok": True,
        "support_volume_m3": round(sv, 12),
        "support_height_m": round(sh, 6),
        "support_to_part_ratio": round(ratio, 4),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 4. overhang_removability
# ---------------------------------------------------------------------------

def overhang_removability(
    process: str,
    overhang_angle_deg: float,
) -> dict[str, Any]:
    """Assess overhang printability and support-removal difficulty.

    Convention: overhang_angle_deg is measured from the vertical (build
    direction).  0° = perfectly vertical wall (no support needed).
    90° = horizontal ceiling (always needs support for FDM/SLA/DMLS).

    Parameters
    ----------
    process:
        AM process name.
    overhang_angle_deg:
        Overhang angle from vertical (degrees, 0–90).

    Returns
    -------
    dict with needs_support, removability ("easy"/"moderate"/"difficult"/"N/A"),
    and a risk description.
    """
    warnings: list[str] = []

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    angle = float(overhang_angle_deg)
    if not (0.0 <= angle <= 90.0):
        return _bad("overhang_angle_deg must be in [0, 90]")

    threshold = _OVERHANG_THRESHOLD_DEG[p]
    needs_support = angle > threshold

    if p in ("SLS", "MJF"):
        # Powder-bed processes are always self-supporting; no discrete support structures
        needs_support = False
        removability = "easy"
        risk = "unfused powder; removed during de-powdering"
    elif not needs_support:
        removability = "N/A"
        risk = "self-supporting at this angle"
    elif p == "FDM":
        if angle <= 60:
            removability = "easy"
            risk = "low-density breakaway support; accessible geometry"
        elif angle <= 75:
            removability = "moderate"
            risk = "moderate support density; possible surface scarring on removal"
        else:
            removability = "difficult"
            risk = "dense support required; significant surface scarring likely"
            _w(warnings, f"overhang {angle}° is steep for FDM; consider redesign")
    elif p == "SLA":
        if angle <= 50:
            removability = "easy"
            risk = "light support; clean break with needle-nose pliers"
        elif angle <= 70:
            removability = "moderate"
            risk = "medium support; potential witness marks"
        else:
            removability = "difficult"
            risk = "heavy support; post-process sanding recommended"
            _w(warnings, f"overhang {angle}° requires heavy SLA support")
    else:  # DMLS
        if angle <= 55:
            removability = "easy"
            risk = "thin support; removed by wire EDM or hand tools"
        elif angle <= 70:
            removability = "moderate"
            risk = "medium support block; machining may be needed"
        else:
            removability = "difficult"
            risk = "heavy support; risk of distortion on removal"
            _w(warnings, f"overhang {angle}° is problematic for DMLS; redesign recommended")

    return {
        "ok": True,
        "process": p,
        "overhang_angle_deg": angle,
        "overhang_threshold_deg": threshold,
        "needs_support": needs_support,
        "removability": removability,
        "risk": risk,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 5. orientation_cost
# ---------------------------------------------------------------------------

def orientation_cost(
    part_bbox_m: tuple[float, float, float],
    surface_area_m2: float,
    overhang_area_m2: float,
    process: str,
    *,
    w_support: float = 1.0,
    w_height: float = 0.5,
    w_surface: float = 0.3,
) -> dict[str, Any]:
    """Compute a scalar cost for one candidate build orientation.

    Cost model (dimensionless, lower is better):
        C = w_support * (overhang_area / surface_area)
          + w_height  * (build_height / max_dim)
          + w_surface * (surface_area / surface_area_sphere_equiv)

    The surface-area term penalises orientations that expose more area to
    staircase stepping (down-facing skin quality).

    Parameters
    ----------
    part_bbox_m:
        Bounding box (x, y, z) for this orientation.  z is build height.
    surface_area_m2:
        Total part surface area (invariant across orientations) in m².
    overhang_area_m2:
        Area of faces requiring support in this orientation (m²).
    process:
        AM process.
    w_support, w_height, w_surface:
        Weighting factors for each cost term.

    Returns
    -------
    dict with cost (float) and each cost term.
    """
    warnings: list[str] = []

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    if not (isinstance(part_bbox_m, (list, tuple)) and len(part_bbox_m) == 3):
        return _bad("part_bbox_m must be a 3-element sequence")
    x_m, y_m, z_m = (float(v) for v in part_bbox_m)
    if x_m <= 0 or y_m <= 0 or z_m <= 0:
        return _bad("all part_bbox_m dimensions must be > 0")

    sa = float(surface_area_m2)
    if sa <= 0:
        return _bad("surface_area_m2 must be > 0")
    oa = float(overhang_area_m2)
    if oa < 0:
        return _bad("overhang_area_m2 must be >= 0")
    if oa > sa:
        return _bad("overhang_area_m2 cannot exceed surface_area_m2")

    # For powder-bed processes (SLS/MJF) support is not needed → zero support cost
    if p in ("SLS", "MJF"):
        support_term = 0.0
    else:
        support_term = oa / sa

    max_dim = max(x_m, y_m, z_m)
    height_term = z_m / max_dim

    # Equivalent-sphere surface area: S_sphere = (4π)^(1/3) × (3V)^(2/3)
    # Use bounding-box volume as a proxy for part volume
    vol_proxy = x_m * y_m * z_m
    sa_sphere = (4 * math.pi) ** (1 / 3) * (3 * vol_proxy) ** (2 / 3)
    surface_term = sa / sa_sphere if sa_sphere > 0 else 1.0

    cost = (
        float(w_support) * support_term
        + float(w_height) * height_term
        + float(w_surface) * surface_term
    )

    if support_term > 0.4:
        _w(warnings, f"high support fraction {support_term:.0%}; costly removal")
    if height_term > 0.9:
        _w(warnings, "build height is near the maximum bounding dimension; slow build")

    return {
        "ok": True,
        "process": p,
        "cost": round(cost, 6),
        "support_term": round(support_term, 6),
        "height_term": round(height_term, 6),
        "surface_term": round(surface_term, 6),
        "build_height_m": z_m,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 6. best_orientation
# ---------------------------------------------------------------------------

def best_orientation(
    part_bbox_m_list: list[tuple[float, float, float]],
    surface_area_m2: float,
    overhang_areas_m2: list[float],
    process: str,
    *,
    w_support: float = 1.0,
    w_height: float = 0.5,
    w_surface: float = 0.3,
) -> dict[str, Any]:
    """Select the best build orientation from N candidate bounding boxes.

    Parameters
    ----------
    part_bbox_m_list:
        List of (x, y, z) bounding boxes, one per candidate orientation.
        z is the build direction.
    surface_area_m2:
        Total surface area (invariant).
    overhang_areas_m2:
        List of overhang areas (m²), one per candidate.  Must have same
        length as part_bbox_m_list.
    process:
        AM process.
    w_support, w_height, w_surface:
        Cost-function weights.

    Returns
    -------
    dict with best_index (0-based), best_cost, and all costs.
    """
    warnings: list[str] = []

    if not part_bbox_m_list:
        return _bad("part_bbox_m_list must not be empty")
    if len(part_bbox_m_list) != len(overhang_areas_m2):
        return _bad(
            "part_bbox_m_list and overhang_areas_m2 must have the same length"
        )

    costs: list[float] = []
    for i, (bbox, oa) in enumerate(zip(part_bbox_m_list, overhang_areas_m2)):
        res = orientation_cost(
            bbox, surface_area_m2, oa, process,
            w_support=w_support, w_height=w_height, w_surface=w_surface,
        )
        if not res.get("ok"):
            return _bad(f"orientation {i}: {res.get('reason', 'error')}")
        costs.append(res["cost"])
        warnings.extend(res.get("warnings", []))

    best_idx = int(min(range(len(costs)), key=lambda i: costs[i]))

    return {
        "ok": True,
        "process": process.upper().strip(),
        "n_candidates": len(costs),
        "best_index": best_idx,
        "best_cost": round(costs[best_idx], 6),
        "all_costs": [round(c, 6) for c in costs],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 7. shrinkage_compensation
# ---------------------------------------------------------------------------

def shrinkage_compensation(
    nominal_dim_m: float,
    process: str,
    material: str = "default",
) -> dict[str, Any]:
    """Compute scale-up factor and compensated model dimension.

    Compensated_dim = nominal_dim / (1 - shrinkage_fraction)

    Parameters
    ----------
    nominal_dim_m:
        Desired finished-part dimension (m). Must be > 0.
    process:
        AM process.
    material:
        Material name (process-specific).  Defaults to 'default'.

    Returns
    -------
    dict with shrinkage_fraction, compensated_dim_m, and scale_factor.
    """
    warnings: list[str] = []

    nd = float(nominal_dim_m)
    if nd <= 0:
        return _bad("nominal_dim_m must be > 0")

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    mat_table = _SHRINKAGE[p]
    mat_key = material if material in mat_table else "default"
    if material not in mat_table and material != "default":
        _w(warnings, f"material '{material}' not in table for {p}; using default")
    sf = mat_table[mat_key]

    compensated = nd / (1.0 - sf)
    scale_factor = 1.0 / (1.0 - sf)

    if sf > 0.02:
        _w(warnings, f"high shrinkage fraction {sf:.1%} for {p}/{mat_key}; verify calibration")

    return {
        "ok": True,
        "process": p,
        "material": mat_key,
        "shrinkage_fraction": sf,
        "nominal_dim_m": round(nd, 9),
        "compensated_dim_m": round(compensated, 9),
        "scale_factor": round(scale_factor, 6),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 8. lattice_infill (Gibson-Ashby)
# ---------------------------------------------------------------------------

# Gibson-Ashby exponents for relative density → relative stiffness:
#   E_eff / E_solid = C1 × (ρ_rel)^n
# Gyroid: bending-dominated → n ≈ 2.0, C1 ≈ 0.3
# Cubic: stretch-dominated → n ≈ 1.0, C1 ≈ 1.0
_GA_PARAMS: dict[str, tuple[float, float]] = {
    "gyroid": (0.3, 2.0),
    "cubic": (1.0, 1.0),
}


def lattice_infill(
    process: str,
    infill_type: str,
    relative_density: float,
    solid_modulus_Pa: float,
    solid_density_kg_m3: float,
    volume_m3: float,
) -> dict[str, Any]:
    """Compute Gibson-Ashby lattice effective properties.

    Effective modulus:  E_eff = C1 × (ρ_rel)^n × E_solid
    Effective density:  ρ_eff = ρ_rel × ρ_solid
    Lattice mass:       m     = ρ_eff × volume

    Parameters
    ----------
    process:
        AM process (used only for printability warning).
    infill_type:
        "gyroid" or "cubic".
    relative_density:
        Infill volume fraction (0–1, exclusive).  Typical: 0.10–0.50.
    solid_modulus_Pa:
        Young's modulus of the fully dense solid (Pa).
    solid_density_kg_m3:
        Density of the fully dense solid (kg/m³).
    volume_m3:
        Bounding volume of the latticed region (m³).

    Returns
    -------
    dict with effective_modulus_Pa, effective_density_kg_m3, mass_kg,
    and relative_stiffness.
    """
    warnings: list[str] = []

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    it = infill_type.lower().strip() if isinstance(infill_type, str) else ""
    if it not in _GA_PARAMS:
        return _bad(f"infill_type must be one of {list(_GA_PARAMS.keys())}")

    rho_rel = float(relative_density)
    if not (0.0 < rho_rel < 1.0):
        return _bad("relative_density must be in (0, 1) exclusive")

    E_s = float(solid_modulus_Pa)
    if E_s <= 0:
        return _bad("solid_modulus_Pa must be > 0")
    rho_s = float(solid_density_kg_m3)
    if rho_s <= 0:
        return _bad("solid_density_kg_m3 must be > 0")
    vol = float(volume_m3)
    if vol <= 0:
        return _bad("volume_m3 must be > 0")

    C1, n = _GA_PARAMS[it]
    E_eff = C1 * (rho_rel ** n) * E_s
    rho_eff = rho_rel * rho_s
    mass_kg = rho_eff * vol
    rel_stiffness = E_eff / E_s

    # FDM gyroid printability: minimum wall at infill crossings
    if p == "FDM" and rho_rel < 0.15:
        _w(warnings, "FDM relative density < 15%; strut width may fall below nozzle diameter")
    if p == "DMLS" and rho_rel < 0.10:
        _w(warnings, "DMLS relative density < 10%; strut width may be below minimum feature size")
    if rel_stiffness < 0.05:
        _w(warnings, "effective modulus < 5% of solid; verify structural adequacy")

    return {
        "ok": True,
        "process": p,
        "infill_type": it,
        "relative_density": rho_rel,
        "C1": C1,
        "n_exponent": n,
        "effective_modulus_Pa": round(E_eff, 2),
        "effective_density_kg_m3": round(rho_eff, 4),
        "mass_kg": round(mass_kg, 6),
        "relative_stiffness": round(rel_stiffness, 6),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 9. feature_checks
# ---------------------------------------------------------------------------

def feature_checks(
    process: str,
    wall_thickness_m: float | None = None,
    hole_diameter_m: float | None = None,
    bridge_span_m: float | None = None,
) -> dict[str, Any]:
    """Check minimum feature sizes and bridging span for the given process.

    At least one of wall_thickness_m, hole_diameter_m, or bridge_span_m
    must be provided.  Each check that fails is added to warnings (not an
    error); the function still returns ok=True so callers can inspect all
    issues at once.

    Parameters
    ----------
    process:
        AM process.
    wall_thickness_m:
        Wall thickness to check (m).
    hole_diameter_m:
        Hole diameter to check (m).
    bridge_span_m:
        Unsupported bridging span to check (m).

    Returns
    -------
    dict with ok=True, per-feature pass/fail flags, and warnings list.
    """
    warnings: list[str] = []

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    if wall_thickness_m is None and hole_diameter_m is None and bridge_span_m is None:
        return _bad("at least one of wall_thickness_m, hole_diameter_m, bridge_span_m must be supplied")

    results: dict[str, Any] = {
        "ok": True,
        "process": p,
        "warnings": warnings,
    }

    if wall_thickness_m is not None:
        wt = float(wall_thickness_m)
        min_w = _MIN_WALL_M[p]
        wall_ok = wt >= min_w
        results["wall_thickness_m"] = wt
        results["min_wall_m"] = min_w
        results["wall_pass"] = wall_ok
        if not wall_ok:
            _w(warnings, (
                f"wall_thickness {wt*1000:.2f} mm is below minimum "
                f"{min_w*1000:.2f} mm for {p} — UNPRINTABLE"
            ))

    if hole_diameter_m is not None:
        hd = float(hole_diameter_m)
        min_h = _MIN_HOLE_M[p]
        hole_ok = hd >= min_h
        results["hole_diameter_m"] = hd
        results["min_hole_m"] = min_h
        results["hole_pass"] = hole_ok
        if not hole_ok:
            _w(warnings, (
                f"hole_diameter {hd*1000:.2f} mm is below minimum "
                f"{min_h*1000:.2f} mm for {p} — risk of closure"
            ))

    if bridge_span_m is not None:
        bs = float(bridge_span_m)
        max_b = _MAX_BRIDGE_M[p]
        bridge_ok = bs <= max_b
        results["bridge_span_m"] = bs
        results["max_bridge_m"] = max_b
        results["bridge_pass"] = bridge_ok
        if not bridge_ok:
            _w(warnings, (
                f"bridge_span {bs*1000:.1f} mm exceeds maximum "
                f"{max_b*1000:.1f} mm for {p} — POOR QUALITY / requires support"
            ))

    return results


# ---------------------------------------------------------------------------
# 10. cost_rollup
# ---------------------------------------------------------------------------

def cost_rollup(
    process: str,
    material: str,
    build_time_s: float,
    support_volume_m3: float,
    part_volume_m3: float,
    *,
    machine_rate_per_h: float | None = None,
    material_cost_per_kg: float | None = None,
    post_cost: float = 0.0,
    fill_fraction: float = 1.0,
) -> dict[str, Any]:
    """Compute total part cost from machine-hour, material, and post-processing.

    Cost components:
        machine_cost = build_time_h × machine_rate
        material_mass = (part_volume × fill_fraction + support_volume) × density
        material_cost = material_mass × material_cost_per_kg
        total_cost    = machine_cost + material_cost + post_cost

    Parameters
    ----------
    process:
        AM process.
    material:
        Material name (for density and default cost lookup).
    build_time_s:
        Total build time (s). Must be > 0.
    support_volume_m3:
        Support structure volume (m³). Must be >= 0.
    part_volume_m3:
        Solid part volume (m³). Must be > 0.
    machine_rate_per_h:
        Machine operating cost (USD/h). Defaults to process default.
    material_cost_per_kg:
        Material feedstock cost (USD/kg).  Rough defaults if not supplied:
        FDM PLA ≈ $20/kg, SLS PA12 ≈ $80/kg, DMLS 316L ≈ $400/kg.
    post_cost:
        Fixed post-processing cost (USD, default 0).
    fill_fraction:
        Infill fraction for material consumption (default 1.0 = solid).

    Returns
    -------
    dict with machine_cost_usd, material_cost_usd, total_cost_usd.
    """
    warnings: list[str] = []

    if not isinstance(process, str):
        return _bad("process must be a string")
    p = process.upper().strip()
    if p not in _VALID_PROCESSES:
        return _bad(f"unknown process '{process}'")

    bt = float(build_time_s)
    if bt <= 0:
        return _bad("build_time_s must be > 0")
    sv = float(support_volume_m3)
    if sv < 0:
        return _bad("support_volume_m3 must be >= 0")
    pv = float(part_volume_m3)
    if pv <= 0:
        return _bad("part_volume_m3 must be > 0")
    ff = float(fill_fraction)
    if not (0.0 < ff <= 1.0):
        return _bad("fill_fraction must be in (0, 1]")

    mr = float(machine_rate_per_h) if machine_rate_per_h is not None else _DEFAULT_MACHINE_RATE[p]
    if mr < 0:
        return _bad("machine_rate_per_h must be >= 0")

    # Material density
    density = _MATERIAL_DENSITY.get(material, _MATERIAL_DENSITY["default"])
    # Material cost defaults (USD/kg) if not supplied
    _DEFAULT_MAT_COST: dict[str, float] = {
        "PLA": 20.0, "ABS": 22.0, "PETG": 25.0, "Nylon": 45.0,
        "standard_resin": 60.0, "engineering_resin": 120.0,
        "PA12": 80.0, "PA11": 85.0, "TPU": 70.0,
        "316L": 400.0, "AlSi10Mg": 300.0, "Ti6Al4V": 600.0, "Inconel625": 800.0,
        "default": 50.0,
    }
    mat_key = material if material in _DEFAULT_MAT_COST else "default"
    mc_per_kg = float(material_cost_per_kg) if material_cost_per_kg is not None else _DEFAULT_MAT_COST[mat_key]
    if mc_per_kg < 0:
        return _bad("material_cost_per_kg must be >= 0")

    build_time_h = bt / 3600.0
    machine_cost = build_time_h * mr

    material_mass_kg = (pv * ff + sv) * density
    material_cost = material_mass_kg * mc_per_kg

    post = float(post_cost)
    total = machine_cost + material_cost + post

    if material_cost > machine_cost * 5:
        _w(warnings, "material cost dominates (>5× machine cost); consider hollowing or infill")
    if machine_cost > material_cost * 10:
        _w(warnings, "machine time dominates (>10× material cost); check build efficiency")

    return {
        "ok": True,
        "process": p,
        "material": material,
        "build_time_h": round(build_time_h, 4),
        "machine_rate_per_h": round(mr, 2),
        "machine_cost_usd": round(machine_cost, 4),
        "material_mass_kg": round(material_mass_kg, 6),
        "material_cost_per_kg": round(mc_per_kg, 2),
        "material_cost_usd": round(material_cost, 4),
        "post_cost_usd": round(post, 2),
        "total_cost_usd": round(total, 4),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 11. nesting_packing
# ---------------------------------------------------------------------------

def nesting_packing(
    build_volume_m3: float,
    part_volume_m3: float,
    n_parts: int,
    packing_factor: float = 0.60,
) -> dict[str, Any]:
    """Estimate powder-bed nesting efficiency and batch throughput.

    Packing factor (φ) represents the fraction of the build volume that
    parts actually occupy (accounting for gaps, de-powdering access, and
    support-free spacing).  Typical values: SLS/MJF ≈ 0.55–0.70.

    Effective build volume available for parts: V_eff = V_build × φ
    Maximum parts per build:  n_max = floor(V_eff / V_part)
    Batch utilisation:        U = (n_parts × V_part) / (V_build × φ)

    Parameters
    ----------
    build_volume_m3:
        Total build chamber volume (m³). Must be > 0.
    part_volume_m3:
        Volume of one part (m³). Must be > 0.
    n_parts:
        Number of parts to nest. Must be >= 1.
    packing_factor:
        Fraction of build volume usable for parts (default 0.60).

    Returns
    -------
    dict with n_max_per_build, batches_needed, utilisation, and warnings.
    """
    warnings: list[str] = []

    bv = float(build_volume_m3)
    pv = float(part_volume_m3)
    if bv <= 0:
        return _bad("build_volume_m3 must be > 0")
    if pv <= 0:
        return _bad("part_volume_m3 must be > 0")
    np_ = int(n_parts)
    if np_ < 1:
        return _bad("n_parts must be >= 1")
    phi = float(packing_factor)
    if not (0.0 < phi <= 1.0):
        return _bad("packing_factor must be in (0, 1]")

    v_eff = bv * phi
    n_max = max(1, int(v_eff / pv))
    batches = math.ceil(np_ / n_max)
    utilisation = (np_ * pv) / (bv * phi) if (bv * phi) > 0 else 0.0

    if utilisation > 1.0:
        _w(warnings, f"parts exceed effective build volume by {(utilisation - 1)*100:.0f}%; split into more batches")
    if utilisation < 0.5:
        _w(warnings, f"low utilisation ({utilisation:.0%}); consider adding more parts per batch")
    if pv > bv:
        _w(warnings, "single part volume exceeds build chamber volume — part too large to print")

    return {
        "ok": True,
        "build_volume_m3": round(bv, 9),
        "part_volume_m3": round(pv, 12),
        "packing_factor": round(phi, 4),
        "effective_volume_m3": round(v_eff, 9),
        "n_max_per_build": n_max,
        "n_parts": np_,
        "batches_needed": batches,
        "utilisation": round(min(utilisation, 9.9999), 4),
        "warnings": warnings,
    }
