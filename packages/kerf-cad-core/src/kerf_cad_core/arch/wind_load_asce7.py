"""
kerf_cad_core.arch.wind_load_asce7 — Design wind pressure per ASCE 7-22 Directional Procedure.

Implements ASCE 7-22 Chapter 26–27 Directional Procedure for Main Wind Force-Resisting
Systems (MWFRS) of enclosed/partially-enclosed buildings.

Method:
  1. Velocity pressure qz = 0.00256 · Kz · Kzt · Kd · V²   [ASCE 7-22 §26.10-1]
     (Kd = 0.85 for buildings, per Table 26.6-1)
  2. Kz — velocity pressure exposure coefficient per Table 26.10-1:
       Kz = 2.01 · (z/zg)^(2/α)           for z ≥ 15 ft
       Kz = 2.01 · (15/zg)^(2/α)          for z < 15 ft  (floor at 15 ft)
     Exposure category constants (Table 26.10-1 footnote / commentary):
       B: α=7.0,  zg=1200 ft
       C: α=9.5,  zg=900 ft
       D: α=11.5, zg=700 ft
  3. External pressure coefficients Cp per Fig 27.4-1 (MWFRS walls):
       Windward wall: Cp = +0.8  (all cases, all L/B)
       Leeward wall:  Cp = −0.5  (L/B = 0–1); −0.3 (L/B = 4+); interpolated between
  4. Design wall pressures (§27.4.1):
       p = qz · G · Cp   where G = 0.85 (rigid structure, §26.11.1)
     Windward: p_w = qz · G · Cp_windward
     Leeward:  p_l = qz · G · Cp_leeward   (qh used for leeward, same qz at h)
  5. Total drag (net lateral): p_drag = qz · G · (Cp_windward − Cp_leeward)
     = qz · G · (0.8 + |Cp_leeward|)

Scope and honest caveats:
  • Directional Procedure (§26–27) only — Envelope Procedure (§28) and simplified method
    (§27.5) are not implemented.
  • Tornado loads (§32) not implemented.
  • Internal pressure coefficient (GCpi, §26.13) not included; add separately for
    component design.
  • Parapets (§27.7), rooftop structures (§27.8), and roof pressures not computed.
  • Risk Category IV velocity multiplier not applied here — user supplies V_basic_mph
    directly from ASCE 7-22 Fig 26.5-1 / Fig 26.5-2 for the appropriate risk category.
  • Topographic factor Kzt default = 1.0 (flat/gentle terrain); user must set for hills/
    ridges/escarpments per §26.8 and Fig 26.8-1.
  • Ground elevation factor Ke = 1.0 (sea level); §26.9 adjustment not included.
  • Only rigid buildings (G = 0.85); flexible buildings (§26.11.2) require dynamic
    analysis and are out of scope.

References:
  ASCE/SEI 7-22, Minimum Design Loads and Associated Criteria for Buildings and Other
    Structures. American Society of Civil Engineers, 2022.
    §26.5   (basic wind speed maps, Fig 26.5-1 / 26.5-2)
    §26.6   (wind directionality factor Kd, Table 26.6-1)
    §26.8   (topographic factor Kzt)
    §26.10  (velocity pressure exposure coefficients Kz, Table 26.10-1)
    §26.10-1 (velocity pressure equation qz = 0.00256·Kz·Kzt·Kd·V²)
    §26.11  (gust factor G = 0.85 for rigid structures)
    §26.13  (internal pressure coefficient GCpi — NOT included here)
    §27.3   (Directional Procedure applicability)
    §27.4   (design wind pressure, Eq 27.4-1)
    Fig 27.4-1 (external pressure coefficients Cp for MWFRS)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "WindSiteSpec",
    "BuildingSpec",
    "WindPressureReport",
    "compute_wind_load",
]

# ---------------------------------------------------------------------------
# Exposure category constants — ASCE 7-22 Table 26.10-1 / Commentary
# ---------------------------------------------------------------------------

_EXPOSURE_PARAMS: dict[str, tuple[float, float]] = {
    #        α      zg (ft)
    "B": (7.0,  1200.0),
    "C": (9.5,   900.0),
    "D": (11.5,  700.0),
}

# Wind directionality factor for buildings — ASCE 7-22 Table 26.6-1
_KD_BUILDING = 0.85

# Gust factor for rigid structures — ASCE 7-22 §26.11.1
_G_RIGID = 0.85

# Minimum height for Kz evaluation (ft) — ASCE 7-22 §26.10
_Z_MIN_FT = 15.0

# Valid exposure categories and risk categories
_VALID_EXPOSURE = frozenset({"B", "C", "D"})
_VALID_RISK_CAT = frozenset({"I", "II", "III", "IV"})
_VALID_ENCLOSURE = frozenset({"enclosed", "partially_enclosed", "open"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WindSiteSpec:
    """
    Site parameters for ASCE 7-22 wind load calculation.

    Parameters
    ----------
    V_basic_mph : float
        Basic wind speed V (mph) from ASCE 7-22 Fig 26.5-1 (Risk Category II),
        Fig 26.5-2A/B/C for other risk categories, or by site-specific study.
        Must be > 0. Typical US values: 85–200 mph depending on region.
        User is responsible for selecting the correct map / risk category
        combination — this module does not apply velocity multipliers.
    exposure_category : str
        Surface roughness / exposure category per §26.7:
          "B" — urban, suburban, wooded (z0 ≈ 1 ft / 0.3 m)
          "C" — open terrain, scattered obstructions < 30 ft (z0 ≈ 0.07 ft / 0.02 m)
          "D" — flat, unobstructed areas and water surfaces (z0 ≈ 0.016 ft / 0.005 m)
    K_zt : float
        Topographic factor per §26.8 and Fig 26.8-1. Default = 1.0 (flat terrain).
        Set > 1 for hills, ridges, or escarpments.
    risk_category : str
        Risk Category per §1.5 and Table 1.5-1:
          "I"   — low hazard (agricultural, minor storage)
          "II"  — standard (typical residential, commercial)
          "III" — substantial hazard (schools, hospitals < 250 occ)
          "IV"  — essential facilities (hospitals, fire stations, shelters)
        Used for documentation; V_basic_mph must already reflect the correct RC map.
    """
    V_basic_mph: float
    exposure_category: str
    K_zt: float = 1.0
    risk_category: str = "II"


@dataclass
class BuildingSpec:
    """
    Building geometry for ASCE 7-22 MWFRS wall pressure calculation.

    Parameters
    ----------
    mean_height_h_ft : float
        Mean roof height h in feet. Must be > 0.
        For flat roofs: h = eave height.
        For gable/hip roofs: h = midpoint of the roof slope.
    length_ft : float
        Horizontal building dimension parallel to the wind direction L (ft).
        Used to compute the L/B ratio for leeward Cp. Must be > 0.
    width_ft : float
        Horizontal building dimension perpendicular to the wind direction B (ft).
        Must be > 0.
    enclosure : str
        Building enclosure classification per §26.12:
          "enclosed"           — no dominant openings (most buildings)
          "partially_enclosed" — dominant opening on one face
          "open"               — each wall ≥ 80% open
        Used for documentation; internal pressure (GCpi) is NOT computed here.
    """
    mean_height_h_ft: float
    length_ft: float
    width_ft: float
    enclosure: str = "enclosed"


@dataclass
class WindPressureReport:
    """
    Output of ASCE 7-22 §26–27 Directional Procedure wall pressure calculation.

    Parameters
    ----------
    qz_psf : float
        Velocity pressure at height z = h (psf).  qz = 0.00256·Kz·Kzt·Kd·V².
    Kz : float
        Velocity pressure exposure coefficient at z = h.
    Cp_windward : float
        External pressure coefficient for windward wall (+0.8, ASCE 7-22 Fig 27.4-1).
    Cp_leeward : float
        External pressure coefficient for leeward wall (negative, Fig 27.4-1,
        depends on L/B ratio).
    p_windward_psf : float
        Design pressure on windward wall (psf): qz · G · Cp_windward.
        Positive = pressure toward surface (inward).
    p_leeward_psf : float
        Design pressure on leeward wall (psf): qz · G · |Cp_leeward|.
        Reported as a positive magnitude; direction is away from surface (suction).
    total_drag_psf : float
        Net lateral drag pressure: qz · G · (Cp_windward − Cp_leeward)
        = qz · G · (|Cp_windward| + |Cp_leeward|).
        This is the combined windward + leeward effect for lateral force calc.
    L_over_B : float
        Building length-to-width ratio used for leeward Cp selection.
    code_section : list[str]
        ASCE 7-22 sections referenced in this calculation.
    honest_caveat : str
        Plain-language scope statement: what is computed, what is NOT.
    """
    qz_psf: float
    Kz: float
    Cp_windward: float
    Cp_leeward: float
    p_windward_psf: float
    p_leeward_psf: float
    total_drag_psf: float
    L_over_B: float
    code_section: list[str] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_kz(z_ft: float, alpha: float, zg_ft: float) -> float:
    """
    Velocity pressure exposure coefficient Kz per ASCE 7-22 Table 26.10-1.

    Kz = 2.01 · (z / zg)^(2/α)    for z ≥ 15 ft
    Kz = 2.01 · (15 / zg)^(2/α)   for z < 15 ft  (floor at 15 ft per footnote)
    """
    z_eff = max(z_ft, _Z_MIN_FT)
    return 2.01 * (z_eff / zg_ft) ** (2.0 / alpha)


def _leeward_cp(L_over_B: float) -> float:
    """
    Leeward wall Cp per ASCE 7-22 Fig 27.4-1.

    L/B = 0–1  → Cp = −0.5
    L/B = 2    → Cp = −0.3 (interpolated from table; Fig 27.4-1 gives −0.3 at L/B≥2)
    L/B ≥ 4    → Cp = −0.2

    ASCE 7-22 Fig 27.4-1 tabulates:
      L/B ≤ 1  → −0.5
      L/B = 2  → −0.3
      L/B ≥ 4  → −0.2
    Linear interpolation between breakpoints.
    """
    if L_over_B <= 1.0:
        return -0.5
    elif L_over_B <= 2.0:
        # interpolate between −0.5 (at L/B=1) and −0.3 (at L/B=2)
        t = (L_over_B - 1.0) / (2.0 - 1.0)
        return -0.5 + t * (-0.3 - (-0.5))
    elif L_over_B <= 4.0:
        # interpolate between −0.3 (at L/B=2) and −0.2 (at L/B=4)
        t = (L_over_B - 2.0) / (4.0 - 2.0)
        return -0.3 + t * (-0.2 - (-0.3))
    else:
        return -0.2


def compute_wind_load(site: WindSiteSpec, building: BuildingSpec) -> WindPressureReport:
    """
    Compute MWFRS wall design wind pressures per ASCE 7-22 §26–27 Directional Procedure.

    Parameters
    ----------
    site : WindSiteSpec
        Site wind speed, exposure, topographic, and risk category data.
    building : BuildingSpec
        Building geometry (height, length, width, enclosure class).

    Returns
    -------
    WindPressureReport
        Velocity pressure qz, exposure coefficient Kz, external pressure
        coefficients Cp (windward and leeward), design wall pressures, and
        total lateral drag pressure.

    Raises
    ------
    ValueError
        If any input parameter is invalid.

    Notes
    -----
    • Velocity pressure: qz = 0.00256 · Kz · Kzt · Kd · V²  (psf, mph)
    • Windward Cp = +0.8 (all cases, Fig 27.4-1)
    • Leeward Cp: −0.5 (L/B ≤ 1), −0.3 (L/B = 2), −0.2 (L/B ≥ 4), interpolated
    • Gust factor G = 0.85 (rigid structures, §26.11.1)
    • Kd = 0.85 (buildings, Table 26.6-1)
    • Internal pressure (GCpi) not included — add per §26.13 for component design.
    """
    # ------------------------------------------------------------------ validation
    if site.V_basic_mph <= 0.0:
        raise ValueError(f"V_basic_mph must be > 0, got {site.V_basic_mph}")
    if site.exposure_category not in _VALID_EXPOSURE:
        raise ValueError(
            f"exposure_category must be one of {sorted(_VALID_EXPOSURE)}, "
            f"got {site.exposure_category!r}"
        )
    if site.K_zt < 1.0:
        raise ValueError(f"K_zt must be ≥ 1.0 (topographic effect is neutral or amplifying), "
                         f"got {site.K_zt}")
    if site.risk_category not in _VALID_RISK_CAT:
        raise ValueError(
            f"risk_category must be one of {sorted(_VALID_RISK_CAT)}, "
            f"got {site.risk_category!r}"
        )
    if building.mean_height_h_ft <= 0.0:
        raise ValueError(f"mean_height_h_ft must be > 0, got {building.mean_height_h_ft}")
    if building.length_ft <= 0.0:
        raise ValueError(f"length_ft must be > 0, got {building.length_ft}")
    if building.width_ft <= 0.0:
        raise ValueError(f"width_ft must be > 0, got {building.width_ft}")
    if building.enclosure not in _VALID_ENCLOSURE:
        raise ValueError(
            f"enclosure must be one of {sorted(_VALID_ENCLOSURE)}, "
            f"got {building.enclosure!r}"
        )

    # ------------------------------------------------------------------ Kz
    alpha, zg_ft = _EXPOSURE_PARAMS[site.exposure_category]
    z_ft = building.mean_height_h_ft
    Kz = _compute_kz(z_ft, alpha, zg_ft)

    # ------------------------------------------------------------------ qz
    # ASCE 7-22 Eq 26.10-1: qz = 0.00256 · Kz · Kzt · Kd · V²  (psf)
    V = site.V_basic_mph
    qz = 0.00256 * Kz * site.K_zt * _KD_BUILDING * V * V

    # ------------------------------------------------------------------ Cp
    L_over_B = building.length_ft / building.width_ft
    Cp_windward = 0.8   # ASCE 7-22 Fig 27.4-1, all L/B
    Cp_leeward  = _leeward_cp(L_over_B)

    # ------------------------------------------------------------------ design pressures
    G = _G_RIGID
    p_windward = qz * G * Cp_windward          # positive = toward surface
    p_leeward  = qz * G * abs(Cp_leeward)     # magnitude of suction, positive
    total_drag = qz * G * (Cp_windward - Cp_leeward)  # = qz·G·(Cp_w + |Cp_l|)

    # ------------------------------------------------------------------ caveat
    code_sections = [
        "ASCE 7-22 §26.6 (Kd)",
        "ASCE 7-22 §26.10 / Table 26.10-1 (Kz)",
        "ASCE 7-22 Eq 26.10-1 (qz)",
        "ASCE 7-22 §26.11.1 (G = 0.85 rigid)",
        "ASCE 7-22 §27.3 (Directional Procedure applicability)",
        "ASCE 7-22 Eq 27.4-1 (p = q·G·Cp)",
        "ASCE 7-22 Fig 27.4-1 (external Cp, MWFRS walls)",
    ]

    caveat = (
        f"ARCH-WIND-LOAD-ASCE7: Directional Procedure (§26–27) for MWFRS wall pressures. "
        f"Inputs: V={V} mph, Exposure {site.exposure_category}, "
        f"h={z_ft} ft, L/B={L_over_B:.3f}, RC={site.risk_category}, "
        f"K_zt={site.K_zt}, Kd={_KD_BUILDING}, G={G}. "
        f"Results: Kz={Kz:.4f}, qz={qz:.2f} psf, "
        f"p_windward={p_windward:.2f} psf, p_leeward={p_leeward:.2f} psf (suction), "
        f"total_drag={total_drag:.2f} psf. "
        f"NOT INCLUDED: Envelope Procedure (§28); tornado loads (§32); "
        f"internal pressure coefficient GCpi (§26.13) — add separately for component design; "
        f"parapet loads (§27.7); roof pressures; flexible-building dynamic G (§26.11.2); "
        f"ground elevation factor Ke (§26.9). "
        f"V_basic_mph must match the correct ASCE 7-22 risk-category map "
        f"(Fig 26.5-1 for RC II; Fig 26.5-2A/B/C for RC I/III/IV). "
        f"Leeward Cp = {Cp_leeward:.2f} for L/B = {L_over_B:.3f} "
        f"(Fig 27.4-1: −0.5 at L/B≤1, −0.3 at L/B=2, −0.2 at L/B≥4, interpolated)."
    )

    return WindPressureReport(
        qz_psf=round(qz, 4),
        Kz=round(Kz, 6),
        Cp_windward=Cp_windward,
        Cp_leeward=round(Cp_leeward, 4),
        p_windward_psf=round(p_windward, 4),
        p_leeward_psf=round(p_leeward, 4),
        total_drag_psf=round(total_drag, 4),
        L_over_B=round(L_over_B, 4),
        code_section=code_sections,
        honest_caveat=caveat,
    )
