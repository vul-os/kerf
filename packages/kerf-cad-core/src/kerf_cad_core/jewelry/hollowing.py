"""
kerf_cad_core.jewelry.hollowing
================================

Metal cleanup / hollowing for casting weight reduction.

Implements MatrixGold's "Clean Metal" / hollow-out wizard functionality:
determine how much of a solid jewelry piece can be hollowed to reach a
target casting weight while maintaining structural integrity.

## Scope

  hollow_for_weight(solid_volume_mm3, target_weight_g, alloy, min_wall_mm)
      Compute required cavity volume, maximum feasible cavity constrained by
      a minimum-wall thickness, and recommended cavity shape (centroid-inset
      prism, ellipsoid, or lattice-infill).

  lattice_infill(volume_mm3, relative_density, cell, min_strut_diameter_mm)
      Gibson-Ashby density-map for gyroid / cubic / octet-truss topologies:
      effective modulus (E_eff = C1 * rho_rel^n * E_solid) and mass.

  boolean_cleanup_holes(cavity_volume_mm3, piece_volume_mm3)
      Auto-place drainage / casting holes on hidden faces: count and diameter
      derived from a drain-rate rule.

  weight_reduction_report(solid_volume_mm3, cavity_volume_mm3, alloy,
                          bbox_volume_mm3)
      Per-stage percentage weight saved, time-to-cast change estimate, and
      structural-integrity flag when cavity exceeds 60% of bbox volume.

## Alloy density source

  Densities are resolved from the sibling metal_cost module's
  METAL_DENSITY_G_CM3 table (same keys).  An explicit density_g_cm3 override
  is accepted wherever an alloy key is expected (mirrors metal_cost API).

## Gibson-Ashby parameters

  Topology    C1      n     character
  gyroid      0.30    2.0   bending-dominated (TPMS surface lattice)
  cubic       1.00    1.0   stretch-dominated (open-cell)
  octet-truss 0.30    1.5   mixed-mode (face-centred cubic truss)

  Reference: Gibson, L.J. & Ashby, M.F. "Cellular Solids: Structure and
  Properties", Cambridge University Press, 2nd ed., 1997, Chapter 5.

## Drainage-hole rule

  Minimum one hole per 5000 mm3 of cavity volume.
  Hole diameter: d = clamp(0.8, 3.0, 0.5 * V_cavity^(1/3) / 5) mm.

## Pure Python; never raises.

All public functions return plain dicts and never raise exceptions.
Bad inputs return {"ok": False, "reason": "<human-readable>"}.
Warnings are accumulated in the "warnings" list when ok is True.

## LLM tools registered

  jewelry_hollow_for_weight
  jewelry_lattice_infill
  jewelry_boolean_cleanup_holes
  jewelry_weight_reduction_report
"""

from __future__ import annotations

import json
import math
from typing import Any, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.jewelry.metal_cost import (
    METAL_DENSITY_G_CM3,
    METAL_LABELS,
    MM3_PER_CM3,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bad(reason: str) -> dict[str, Any]:
    return {"ok": False, "reason": reason}


def _w(warnings: list, msg: str) -> None:
    warnings.append(msg)


# ---------------------------------------------------------------------------
# Gibson-Ashby lattice topology parameters
#
#   E_eff = C1 * rho_rel^n * E_solid
#   n and C1 from Gibson & Ashby (1997), Table 5.1 and section 5.4.
#
# octet-truss (FCC truss) treated as mixed-mode; exponent from
# Deshpande et al. (2001) "Effective properties of the octet-truss lattice
# material", J. Mech. Phys. Solids 49(8):1747-1769.
# ---------------------------------------------------------------------------

_GA_PARAMS: dict[str, tuple[float, float]] = {
    "gyroid":      (0.30, 2.0),   # TPMS bending-dominated
    "cubic":       (1.00, 1.0),   # stretch-dominated open-cell
    "octet_truss": (0.30, 1.5),   # mixed-mode FCC truss
}

# Typical Young's modulus (GPa) for common jewelry alloys.
# Sources: ASM Metals Handbook Vol.2 (2000); Platinum Guild International
# technical notes; Legor Group alloy data sheets (2023).
_ALLOY_MODULUS_GPA: dict[str, float] = {
    "10k_yellow": 95.0,
    "14k_yellow": 85.0,
    "18k_yellow": 80.0,
    "22k_yellow": 78.0,
    "24k_yellow": 77.0,
    "10k_white":  115.0,
    "14k_white":  110.0,
    "18k_white":  100.0,
    "22k_white":  90.0,
    "10k_rose":   95.0,
    "14k_rose":   90.0,
    "18k_rose":   85.0,
    "22k_rose":   82.0,
    "platinum_950":  147.0,
    "platinum_900":  145.0,
    "palladium_950": 121.0,
    "palladium_500": 100.0,
    "sterling_925":  82.7,
    "fine_silver":   83.0,
    "argentium_935": 83.0,
    "titanium":      105.0,
    "brass":         97.0,
    "bronze":        110.0,
}

# Drainage hole diameter clamp limits (mm)
_HOLE_DIA_MIN_MM: float = 0.8
_HOLE_DIA_MAX_MM: float = 3.0

# Cavity-to-bbox volume ratio above which structural integrity warning fires
_STRUCTURAL_WARN_RATIO: float = 0.60

# Maximum fraction of solid volume that can be removed
_MAX_HOLLOW_FRACTION: float = 0.99


# ---------------------------------------------------------------------------
# 1. hollow_for_weight
# ---------------------------------------------------------------------------

def hollow_for_weight(
    solid_volume_mm3: float,
    target_weight_g: float,
    alloy: str,
    min_wall_mm: float = 0.8,
    density_g_cm3: Optional[float] = None,
) -> dict[str, Any]:
    """
    Compute the cavity volume needed to reduce a solid piece to a target weight.

    Parameters
    ----------
    solid_volume_mm3 : float
        Volume of the solid (un-hollowed) piece in mm3.
    target_weight_g : float
        Desired final weight in grams.
    alloy : str
        Alloy key from METAL_DENSITY_G_CM3 (e.g. "18k_yellow").
        Ignored when density_g_cm3 is supplied.
    min_wall_mm : float
        Minimum shell-wall thickness in mm (default 0.8 mm).
    density_g_cm3 : float, optional
        Explicit density override (g/cm3).

    Returns
    -------
    dict with keys:
        ok, alloy, density_g_cm3, solid_volume_mm3, solid_weight_g,
        target_weight_g, required_cavity_mm3, max_cavity_mm3, cavity_shape,
        hollow_fraction, feasible, weight_saved_g, weight_saved_pct, warnings.
    """
    warnings: list = []

    if density_g_cm3 is not None:
        try:
            rho = float(density_g_cm3)
        except (TypeError, ValueError):
            return _bad("density_g_cm3 must be a number")
        if rho <= 0:
            return _bad(f"density_g_cm3 must be positive, got {density_g_cm3}")
        alloy_key = "custom"
    else:
        key = str(alloy).strip().lower() if alloy else ""
        if key not in METAL_DENSITY_G_CM3:
            valid = sorted(METAL_DENSITY_G_CM3)
            return _bad(f"Unknown alloy '{alloy}'. Valid: {valid}")
        rho = METAL_DENSITY_G_CM3[key]
        alloy_key = key

    try:
        vol_solid = float(solid_volume_mm3)
    except (TypeError, ValueError):
        return _bad("solid_volume_mm3 must be a number")
    if vol_solid <= 0:
        return _bad(f"solid_volume_mm3 must be positive, got {solid_volume_mm3}")

    try:
        tgt_g = float(target_weight_g)
    except (TypeError, ValueError):
        return _bad("target_weight_g must be a number")
    if tgt_g <= 0:
        return _bad(f"target_weight_g must be positive, got {target_weight_g}")

    try:
        min_w = float(min_wall_mm)
    except (TypeError, ValueError):
        return _bad("min_wall_mm must be a number")
    if min_w <= 0:
        return _bad(f"min_wall_mm must be positive, got {min_wall_mm}")

    solid_weight_g = rho * (vol_solid / MM3_PER_CM3)

    if tgt_g >= solid_weight_g:
        return _bad(
            f"target_weight_g ({tgt_g:.4f} g) must be less than solid_weight_g "
            f"({solid_weight_g:.4f} g) -- nothing to hollow"
        )

    # V_cavity = V_solid - target_g / rho  (in cm3, then converted)
    v_required_cm3 = (solid_weight_g - tgt_g) / rho
    v_required_mm3 = v_required_cm3 * MM3_PER_CM3

    # Max feasible cavity via spherical-shell approximation
    r_outer = (3.0 * vol_solid / (4.0 * math.pi)) ** (1.0 / 3.0)
    r_inner = max(0.0, r_outer - min_w)
    v_max_cavity_mm3 = (4.0 / 3.0) * math.pi * (r_inner ** 3)
    v_max_cavity_mm3 = min(v_max_cavity_mm3, vol_solid * _MAX_HOLLOW_FRACTION)

    if min_w < 0.5:
        _w(warnings, f"min_wall_mm ({min_w:.2f}) is below recommended 0.5 mm for lost-wax casting")

    feasible = v_required_mm3 <= v_max_cavity_mm3

    if not feasible:
        _w(
            warnings,
            f"required cavity ({v_required_mm3:.2f} mm3) exceeds max feasible "
            f"({v_max_cavity_mm3:.2f} mm3) for min_wall={min_w:.2f} mm -- "
            "consider reducing target_weight_g or increasing min_wall_mm"
        )

    hollow_frac = v_required_mm3 / vol_solid
    if hollow_frac < 0.30:
        cavity_shape = "ellipsoid"
    elif hollow_frac <= 0.60:
        cavity_shape = "prism"
    else:
        cavity_shape = "lattice_infill"

    weight_saved_g = solid_weight_g - tgt_g
    weight_saved_pct = (weight_saved_g / solid_weight_g) * 100.0

    return {
        "ok": True,
        "alloy": alloy_key,
        "alloy_label": METAL_LABELS.get(alloy_key, alloy_key),
        "density_g_cm3": rho,
        "solid_volume_mm3": vol_solid,
        "solid_weight_g": round(solid_weight_g, 4),
        "target_weight_g": tgt_g,
        "required_cavity_mm3": round(v_required_mm3, 4),
        "max_cavity_mm3": round(v_max_cavity_mm3, 4),
        "cavity_shape": cavity_shape,
        "hollow_fraction": round(hollow_frac, 6),
        "feasible": feasible,
        "weight_saved_g": round(weight_saved_g, 4),
        "weight_saved_pct": round(weight_saved_pct, 4),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 2. lattice_infill
# ---------------------------------------------------------------------------

def lattice_infill(
    volume_mm3: float,
    relative_density: float,
    cell: str = "gyroid",
    min_strut_diameter_mm: float = 0.3,
    alloy: Optional[str] = None,
    solid_modulus_gpa: Optional[float] = None,
    density_g_cm3: Optional[float] = None,
) -> dict[str, Any]:
    """
    Gibson-Ashby lattice density-map for gyroid / cubic / octet-truss.

    E_eff = C1 * rho_rel^n * E_solid
    rho_eff = rho_rel * rho_solid
    mass    = rho_eff * V (mm3 -> g)

    Parameters
    ----------
    volume_mm3 : float
        Volume of the region to be latticed (mm3).
    relative_density : float
        Infill volume fraction in (0, 1) exclusive.
    cell : str
        Topology: "gyroid", "cubic", or "octet_truss". Default "gyroid".
    min_strut_diameter_mm : float
        Minimum strut / wall thickness in mm (default 0.3 mm).
    alloy : str, optional
        Alloy key for automatic density + modulus lookup.
    solid_modulus_gpa : float, optional
        Young's modulus of the fully dense solid in GPa (overrides alloy table).
    density_g_cm3 : float, optional
        Density of the fully dense solid in g/cm3 (overrides alloy table).

    Returns
    -------
    dict with: ok, cell, relative_density, C1, n_exponent,
               solid_modulus_gpa, effective_modulus_gpa, relative_stiffness,
               solid_density_g_cm3, effective_density_g_cm3, volume_mm3,
               mass_g, warnings.
    """
    warnings: list = []

    cell_key = str(cell).strip().lower() if cell else ""
    if cell_key not in _GA_PARAMS:
        return _bad(f"cell must be one of {sorted(_GA_PARAMS)}; got '{cell}'")
    C1, n = _GA_PARAMS[cell_key]

    try:
        rho_rel = float(relative_density)
    except (TypeError, ValueError):
        return _bad("relative_density must be a number")
    if not (0.0 < rho_rel < 1.0):
        return _bad("relative_density must be in (0, 1) exclusive")

    try:
        vol = float(volume_mm3)
    except (TypeError, ValueError):
        return _bad("volume_mm3 must be a number")
    if vol <= 0:
        return _bad(f"volume_mm3 must be positive, got {volume_mm3}")

    try:
        min_strut = float(min_strut_diameter_mm)
    except (TypeError, ValueError):
        return _bad("min_strut_diameter_mm must be a number")
    if min_strut <= 0:
        return _bad(f"min_strut_diameter_mm must be positive, got {min_strut_diameter_mm}")

    if density_g_cm3 is not None:
        try:
            rho_solid = float(density_g_cm3)
        except (TypeError, ValueError):
            return _bad("density_g_cm3 must be a number")
        if rho_solid <= 0:
            return _bad(f"density_g_cm3 must be positive, got {density_g_cm3}")
        alloy_key = "custom"
    elif alloy is not None:
        key = str(alloy).strip().lower()
        if key not in METAL_DENSITY_G_CM3:
            return _bad(f"Unknown alloy '{alloy}'. Valid: {sorted(METAL_DENSITY_G_CM3)}")
        rho_solid = METAL_DENSITY_G_CM3[key]
        alloy_key = key
    else:
        return _bad("Provide alloy key or explicit density_g_cm3")

    if solid_modulus_gpa is not None:
        try:
            E_solid_gpa = float(solid_modulus_gpa)
        except (TypeError, ValueError):
            return _bad("solid_modulus_gpa must be a number")
        if E_solid_gpa <= 0:
            return _bad(f"solid_modulus_gpa must be positive, got {solid_modulus_gpa}")
    elif alloy_key != "custom":
        E_solid_gpa = _ALLOY_MODULUS_GPA.get(alloy_key, 80.0)
    else:
        return _bad("Provide solid_modulus_gpa when using explicit density_g_cm3")

    E_eff_gpa = C1 * (rho_rel ** n) * E_solid_gpa
    rho_eff = rho_rel * rho_solid
    mass_g = rho_eff * (vol / MM3_PER_CM3)
    rel_stiffness = E_eff_gpa / E_solid_gpa

    cell_size_est = (vol / 100.0) ** (1.0 / 3.0) if vol >= 1.0 else 1.0
    strut_est = 2.0 * rho_rel * cell_size_est
    if strut_est < min_strut:
        _w(
            warnings,
            f"estimated strut diameter ({strut_est:.2f} mm) may be below "
            f"min_strut_diameter_mm ({min_strut:.2f} mm); increase relative_density "
            "or reduce cell count"
        )

    if rel_stiffness < 0.05:
        _w(warnings, "effective modulus < 5% of solid; verify structural adequacy")

    if rho_rel < 0.15:
        _w(warnings, "relative_density < 0.15; check castability of thin struts in lost-wax process")

    return {
        "ok": True,
        "alloy": alloy_key,
        "alloy_label": METAL_LABELS.get(alloy_key, alloy_key),
        "cell": cell_key,
        "relative_density": rho_rel,
        "C1": C1,
        "n_exponent": n,
        "solid_modulus_gpa": round(E_solid_gpa, 4),
        "effective_modulus_gpa": round(E_eff_gpa, 6),
        "relative_stiffness": round(rel_stiffness, 6),
        "solid_density_g_cm3": rho_solid,
        "effective_density_g_cm3": round(rho_eff, 6),
        "volume_mm3": vol,
        "mass_g": round(mass_g, 6),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3. boolean_cleanup_holes
# ---------------------------------------------------------------------------

def boolean_cleanup_holes(
    cavity_volume_mm3: float,
    piece_volume_mm3: float,
) -> dict[str, Any]:
    """
    Auto-place drainage and casting-investment holes on hidden faces.

    Rule: at least one hole per 5000 mm3 of cavity volume, minimum 2 holes
    (one inlet, one outlet for investment flow). Hole diameter scales with
    cavity size: d = clamp(0.8, 3.0, 0.5 * V_cavity^(1/3) / 5) mm.

    Parameters
    ----------
    cavity_volume_mm3 : float
        Volume of the hollow cavity (mm3).
    piece_volume_mm3 : float
        Volume of the outer solid piece (mm3).

    Returns
    -------
    dict with: ok, cavity_volume_mm3, piece_volume_mm3, cavity_fraction,
               hole_count, hole_diameter_mm, hole_area_mm2,
               total_drain_area_mm2, placement, warnings.
    """
    warnings: list = []

    try:
        v_cav = float(cavity_volume_mm3)
    except (TypeError, ValueError):
        return _bad("cavity_volume_mm3 must be a number")
    if v_cav <= 0:
        return _bad(f"cavity_volume_mm3 must be positive, got {cavity_volume_mm3}")

    try:
        v_piece = float(piece_volume_mm3)
    except (TypeError, ValueError):
        return _bad("piece_volume_mm3 must be a number")
    if v_piece <= 0:
        return _bad(f"piece_volume_mm3 must be positive, got {piece_volume_mm3}")

    if v_cav >= v_piece:
        return _bad(
            f"cavity_volume_mm3 ({v_cav:.2f}) must be less than "
            f"piece_volume_mm3 ({v_piece:.2f})"
        )

    hole_count = max(2, math.ceil(v_cav / 5000.0))

    raw_dia = 0.5 * (v_cav ** (1.0 / 3.0)) / 5.0
    hole_dia = max(_HOLE_DIA_MIN_MM, min(_HOLE_DIA_MAX_MM, raw_dia))

    hole_area = math.pi * (hole_dia / 2.0) ** 2
    total_area = hole_count * hole_area
    cavity_fraction = v_cav / v_piece

    if hole_dia <= _HOLE_DIA_MIN_MM + 0.05:
        _w(warnings, f"hole diameter clamped to minimum {_HOLE_DIA_MIN_MM} mm; "
           "verify investment flow through small cavity")

    if hole_count > 6:
        _w(warnings, f"{hole_count} holes recommended for large cavity; "
           "consider enlarging hole diameter to reduce count")

    return {
        "ok": True,
        "cavity_volume_mm3": v_cav,
        "piece_volume_mm3": v_piece,
        "cavity_fraction": round(cavity_fraction, 6),
        "hole_count": hole_count,
        "hole_diameter_mm": round(hole_dia, 4),
        "hole_area_mm2": round(hole_area, 4),
        "total_drain_area_mm2": round(total_area, 4),
        "placement": "hidden_face_auto",
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 4. weight_reduction_report
# ---------------------------------------------------------------------------

def weight_reduction_report(
    solid_volume_mm3: float,
    cavity_volume_mm3: float,
    alloy: str,
    bbox_volume_mm3: Optional[float] = None,
    density_g_cm3: Optional[float] = None,
) -> dict[str, Any]:
    """
    Per-stage weight saving, time-to-cast change, and structural-integrity flag.

    Parameters
    ----------
    solid_volume_mm3 : float
        Volume of the un-hollowed solid piece (mm3).
    cavity_volume_mm3 : float
        Volume of the proposed cavity (mm3).
    alloy : str
        Alloy key from METAL_DENSITY_G_CM3.
    bbox_volume_mm3 : float, optional
        Bounding-box volume of the piece (mm3). When supplied, the
        cavity / bbox ratio is evaluated against the 60% threshold.
    density_g_cm3 : float, optional
        Explicit density override (g/cm3).

    Returns
    -------
    dict with: ok, alloy, density_g_cm3, solid_volume_mm3, hollow_volume_mm3,
               cavity_volume_mm3, solid_weight_g, hollow_weight_g,
               weight_saved_g, weight_saved_pct, metal_volume_pct,
               cavity_bbox_ratio, structural_integrity_ok,
               cast_time_change_pct, warnings.
    """
    warnings: list = []

    if density_g_cm3 is not None:
        try:
            rho = float(density_g_cm3)
        except (TypeError, ValueError):
            return _bad("density_g_cm3 must be a number")
        if rho <= 0:
            return _bad(f"density_g_cm3 must be positive, got {density_g_cm3}")
        alloy_key = "custom"
    else:
        key = str(alloy).strip().lower() if alloy else ""
        if key not in METAL_DENSITY_G_CM3:
            return _bad(f"Unknown alloy '{alloy}'. Valid: {sorted(METAL_DENSITY_G_CM3)}")
        rho = METAL_DENSITY_G_CM3[key]
        alloy_key = key

    try:
        vol_solid = float(solid_volume_mm3)
    except (TypeError, ValueError):
        return _bad("solid_volume_mm3 must be a number")
    if vol_solid <= 0:
        return _bad(f"solid_volume_mm3 must be positive, got {solid_volume_mm3}")

    try:
        vol_cav = float(cavity_volume_mm3)
    except (TypeError, ValueError):
        return _bad("cavity_volume_mm3 must be a number")
    if vol_cav <= 0:
        return _bad(f"cavity_volume_mm3 must be positive, got {cavity_volume_mm3}")
    if vol_cav >= vol_solid:
        return _bad(
            f"cavity_volume_mm3 ({vol_cav:.2f}) must be less than "
            f"solid_volume_mm3 ({vol_solid:.2f})"
        )

    solid_weight_g = rho * (vol_solid / MM3_PER_CM3)
    hollow_vol = vol_solid - vol_cav
    hollow_weight_g = rho * (hollow_vol / MM3_PER_CM3)
    weight_saved_g = solid_weight_g - hollow_weight_g
    weight_saved_pct = (weight_saved_g / solid_weight_g) * 100.0
    metal_vol_pct = (hollow_vol / vol_solid) * 100.0

    if bbox_volume_mm3 is not None:
        try:
            v_bbox = float(bbox_volume_mm3)
        except (TypeError, ValueError):
            return _bad("bbox_volume_mm3 must be a number")
        if v_bbox <= 0:
            return _bad(f"bbox_volume_mm3 must be positive, got {bbox_volume_mm3}")
        cavity_bbox_ratio = vol_cav / v_bbox
        structural_ok = cavity_bbox_ratio <= _STRUCTURAL_WARN_RATIO
        if not structural_ok:
            _w(
                warnings,
                f"cavity / bbox volume ratio ({cavity_bbox_ratio:.2%}) exceeds "
                f"{_STRUCTURAL_WARN_RATIO:.0%}; structural integrity may be compromised -- "
                "consider lattice infill or thicker walls"
            )
    else:
        cavity_bbox_ratio = None
        structural_ok = True

    cast_time_change_pct = -weight_saved_pct

    return {
        "ok": True,
        "alloy": alloy_key,
        "alloy_label": METAL_LABELS.get(alloy_key, alloy_key),
        "density_g_cm3": rho,
        "solid_volume_mm3": vol_solid,
        "hollow_volume_mm3": round(hollow_vol, 4),
        "cavity_volume_mm3": vol_cav,
        "solid_weight_g": round(solid_weight_g, 4),
        "hollow_weight_g": round(hollow_weight_g, 4),
        "weight_saved_g": round(weight_saved_g, 4),
        "weight_saved_pct": round(weight_saved_pct, 4),
        "metal_volume_pct": round(metal_vol_pct, 4),
        "cavity_bbox_ratio": round(cavity_bbox_ratio, 6) if cavity_bbox_ratio is not None else None,
        "structural_integrity_ok": structural_ok,
        "cast_time_change_pct": round(cast_time_change_pct, 4),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# LLM tool specs and runners
# ---------------------------------------------------------------------------

# --- 1. jewelry_hollow_for_weight -------------------------------------------

_hollow_for_weight_spec = ToolSpec(
    name="jewelry_hollow_for_weight",
    description=(
        "Compute the cavity volume needed to hollow a solid jewelry piece to a "
        "target casting weight (MatrixGold 'Clean Metal' parity).\n\n"
        "Formula: V_cavity = V_solid - target_g / rho\n\n"
        "Also computes the maximum feasible cavity (constrained by min_wall_mm) "
        "and recommends a cavity shape: ellipsoid (< 30% removal), prism "
        "(30-60%), or lattice_infill (> 60%).\n\n"
        "Returns: required_cavity_mm3, max_cavity_mm3, cavity_shape, feasible, "
        "weight_saved_g, weight_saved_pct."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "solid_volume_mm3": {
                "type": "number",
                "description": "Volume of the solid (un-hollowed) piece in mm3.",
            },
            "target_weight_g": {
                "type": "number",
                "description": "Desired final weight in grams.",
            },
            "alloy": {
                "type": "string",
                "description": "Alloy key e.g. '18k_yellow', 'platinum_950', 'sterling_925'.",
            },
            "min_wall_mm": {
                "type": "number",
                "description": "Minimum shell-wall thickness in mm (default 0.8).",
            },
            "density_g_cm3": {
                "type": "number",
                "description": "Optional explicit density override (g/cm3).",
            },
        },
        "required": ["solid_volume_mm3", "target_weight_g", "alloy"],
    },
)


@register(_hollow_for_weight_spec, write=False)
async def run_jewelry_hollow_for_weight(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool: jewelry_hollow_for_weight."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    vol = a.get("solid_volume_mm3")
    if vol is None:
        return err_payload("solid_volume_mm3 is required", "BAD_ARGS")
    tgt = a.get("target_weight_g")
    if tgt is None:
        return err_payload("target_weight_g is required", "BAD_ARGS")
    alloy = a.get("alloy")
    if not alloy:
        return err_payload("alloy is required", "BAD_ARGS")

    kwargs: dict[str, Any] = {}
    if "min_wall_mm" in a:
        try:
            kwargs["min_wall_mm"] = float(a["min_wall_mm"])
        except (TypeError, ValueError):
            return err_payload("min_wall_mm must be a number", "BAD_ARGS")
    if "density_g_cm3" in a:
        try:
            kwargs["density_g_cm3"] = float(a["density_g_cm3"])
        except (TypeError, ValueError):
            return err_payload("density_g_cm3 must be a number", "BAD_ARGS")

    try:
        vol_f = float(vol)
        tgt_f = float(tgt)
    except (TypeError, ValueError):
        return err_payload("solid_volume_mm3 and target_weight_g must be numbers", "BAD_ARGS")

    result = hollow_for_weight(vol_f, tgt_f, str(alloy), **kwargs)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# --- 2. jewelry_lattice_infill -----------------------------------------------

_lattice_infill_spec = ToolSpec(
    name="jewelry_lattice_infill",
    description=(
        "Gibson-Ashby lattice infill for jewelry hollowing: effective modulus, "
        "mass, and relative density for gyroid / cubic / octet-truss topologies.\n\n"
        "E_eff = C1 * rho_rel^n * E_solid\n"
        "rho_eff = rho_rel * rho_solid\n"
        "mass = rho_eff * volume\n\n"
        "Topology    C1    n\n"
        "gyroid      0.30  2.0   bending-dominated (TPMS)\n"
        "cubic       1.00  1.0   stretch-dominated\n"
        "octet_truss 0.30  1.5   mixed-mode\n\n"
        "Returns: effective_modulus_gpa, relative_stiffness, "
        "effective_density_g_cm3, mass_g, warnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "volume_mm3": {
                "type": "number",
                "description": "Volume of the latticed region (mm3).",
            },
            "relative_density": {
                "type": "number",
                "description": "Infill volume fraction in (0, 1). Typical: 0.15-0.50.",
            },
            "cell": {
                "type": "string",
                "description": "'gyroid', 'cubic', or 'octet_truss' (default 'gyroid').",
            },
            "min_strut_diameter_mm": {
                "type": "number",
                "description": "Minimum strut diameter in mm (default 0.3).",
            },
            "alloy": {
                "type": "string",
                "description": "Alloy key for automatic density + modulus lookup.",
            },
            "solid_modulus_gpa": {
                "type": "number",
                "description": "Young's modulus of fully dense solid (GPa).",
            },
            "density_g_cm3": {
                "type": "number",
                "description": "Density of fully dense solid (g/cm3).",
            },
        },
        "required": ["volume_mm3", "relative_density"],
    },
)


@register(_lattice_infill_spec, write=False)
async def run_jewelry_lattice_infill(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool: jewelry_lattice_infill."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    vol = a.get("volume_mm3")
    rho = a.get("relative_density")
    if vol is None:
        return err_payload("volume_mm3 is required", "BAD_ARGS")
    if rho is None:
        return err_payload("relative_density is required", "BAD_ARGS")

    try:
        vol_f = float(vol)
        rho_f = float(rho)
    except (TypeError, ValueError):
        return err_payload("volume_mm3 and relative_density must be numbers", "BAD_ARGS")

    kwargs: dict[str, Any] = {}
    if "cell" in a:
        kwargs["cell"] = str(a["cell"])
    if "min_strut_diameter_mm" in a:
        try:
            kwargs["min_strut_diameter_mm"] = float(a["min_strut_diameter_mm"])
        except (TypeError, ValueError):
            return err_payload("min_strut_diameter_mm must be a number", "BAD_ARGS")
    if "alloy" in a:
        kwargs["alloy"] = str(a["alloy"])
    if "solid_modulus_gpa" in a:
        try:
            kwargs["solid_modulus_gpa"] = float(a["solid_modulus_gpa"])
        except (TypeError, ValueError):
            return err_payload("solid_modulus_gpa must be a number", "BAD_ARGS")
    if "density_g_cm3" in a:
        try:
            kwargs["density_g_cm3"] = float(a["density_g_cm3"])
        except (TypeError, ValueError):
            return err_payload("density_g_cm3 must be a number", "BAD_ARGS")

    result = lattice_infill(vol_f, rho_f, **kwargs)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# --- 3. jewelry_boolean_cleanup_holes ----------------------------------------

_cleanup_holes_spec = ToolSpec(
    name="jewelry_boolean_cleanup_holes",
    description=(
        "Auto-place drainage and casting-investment holes on the hidden faces "
        "of a hollowed jewelry piece.\n\n"
        "Count: max(2, ceil(cavity_volume_mm3 / 5000))\n"
        "Diameter: clamp(0.8, 3.0, 0.5 * V_cav^(1/3) / 5) mm\n\n"
        "Returns: hole_count, hole_diameter_mm, total_drain_area_mm2, placement."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cavity_volume_mm3": {
                "type": "number",
                "description": "Volume of the hollow cavity (mm3).",
            },
            "piece_volume_mm3": {
                "type": "number",
                "description": "Volume of the outer solid piece (mm3).",
            },
        },
        "required": ["cavity_volume_mm3", "piece_volume_mm3"],
    },
)


@register(_cleanup_holes_spec, write=False)
async def run_jewelry_boolean_cleanup_holes(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool: jewelry_boolean_cleanup_holes."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    cav = a.get("cavity_volume_mm3")
    piece = a.get("piece_volume_mm3")
    if cav is None:
        return err_payload("cavity_volume_mm3 is required", "BAD_ARGS")
    if piece is None:
        return err_payload("piece_volume_mm3 is required", "BAD_ARGS")

    try:
        cav_f = float(cav)
        piece_f = float(piece)
    except (TypeError, ValueError):
        return err_payload("cavity_volume_mm3 and piece_volume_mm3 must be numbers", "BAD_ARGS")

    result = boolean_cleanup_holes(cav_f, piece_f)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# --- 4. jewelry_weight_reduction_report -------------------------------------

_wr_report_spec = ToolSpec(
    name="jewelry_weight_reduction_report",
    description=(
        "Per-stage weight-saving report for a hollowed jewelry piece.\n\n"
        "Reports: hollow_weight_g, weight_saved_g, weight_saved_pct, "
        "structural_integrity_ok (flags when cavity > 60% of bounding-box "
        "volume), cast_time_change_pct (Chvorinov-rule estimate).\n\n"
        "Returns: all weight fields, cavity_bbox_ratio, structural_integrity_ok."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "solid_volume_mm3": {
                "type": "number",
                "description": "Volume of the un-hollowed solid piece (mm3).",
            },
            "cavity_volume_mm3": {
                "type": "number",
                "description": "Volume of the proposed cavity (mm3).",
            },
            "alloy": {
                "type": "string",
                "description": "Alloy key e.g. '18k_yellow', 'sterling_925'.",
            },
            "bbox_volume_mm3": {
                "type": "number",
                "description": "Bounding-box volume (mm3) -- enables structural-integrity check.",
            },
            "density_g_cm3": {
                "type": "number",
                "description": "Optional explicit density override (g/cm3).",
            },
        },
        "required": ["solid_volume_mm3", "cavity_volume_mm3", "alloy"],
    },
)


@register(_wr_report_spec, write=False)
async def run_jewelry_weight_reduction_report(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool: jewelry_weight_reduction_report."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    sol_vol = a.get("solid_volume_mm3")
    cav_vol = a.get("cavity_volume_mm3")
    alloy = a.get("alloy")
    if sol_vol is None:
        return err_payload("solid_volume_mm3 is required", "BAD_ARGS")
    if cav_vol is None:
        return err_payload("cavity_volume_mm3 is required", "BAD_ARGS")
    if not alloy:
        return err_payload("alloy is required", "BAD_ARGS")

    try:
        sol_f = float(sol_vol)
        cav_f = float(cav_vol)
    except (TypeError, ValueError):
        return err_payload("solid_volume_mm3 and cavity_volume_mm3 must be numbers", "BAD_ARGS")

    kwargs: dict[str, Any] = {}
    if "bbox_volume_mm3" in a:
        try:
            kwargs["bbox_volume_mm3"] = float(a["bbox_volume_mm3"])
        except (TypeError, ValueError):
            return err_payload("bbox_volume_mm3 must be a number", "BAD_ARGS")
    if "density_g_cm3" in a:
        try:
            kwargs["density_g_cm3"] = float(a["density_g_cm3"])
        except (TypeError, ValueError):
            return err_payload("density_g_cm3 must be a number", "BAD_ARGS")

    result = weight_reduction_report(sol_f, cav_f, str(alloy), **kwargs)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)
