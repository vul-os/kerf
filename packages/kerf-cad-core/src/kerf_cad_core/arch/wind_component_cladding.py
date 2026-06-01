"""
kerf_cad_core.arch.wind_component_cladding — Design wind pressure on building
components and cladding (C&C) per ASCE 7-22 §30.

Implements ASCE 7-22 Chapter 30 for Components and Cladding (C&C) of enclosed
low-rise and mid-rise buildings (h ≤ 60 ft): windows, doors, wall panels,
parapets, and roof cladding.

Key difference from MWFRS (§27 Directional Procedure):
  • C&C uses peak GCp coefficients taken directly from pressure-coefficient
    figures (Fig 30.3-2A/B for walls; Fig 30.3-2C/D for roofs).
  • No separate gust factor G; the GCp is already combined.
  • Pressure zones are localised: interior, edge, and corner zones receive
    progressively higher |GCp| because edge-suction and corner vortex effects
    amplify local pressures well beyond the building-averaged MWFRS.
  • Internal pressure coefficient GCpi is included explicitly (§26.13.2):
    enclosed building GCpi = ±0.18.

Method (ASCE 7-22 §30.3 — Low-Rise Buildings):
  1. Velocity pressure qh = 0.00256 · Kh · Kzt · Kd · V²   [Eq 26.10-1 at h]
     (Kd = 0.85 for buildings, Table 26.6-1)
  2. Kh — velocity pressure exposure coefficient at mean roof height h per
     Table 26.10-1 (identical formula to MWFRS qz).
  3. Nominal GCp coefficients from Fig 30.3-2A (walls) or Fig 30.3-2C (roofs)
     at the 10 ft² reference effective area.
  4. Effective-area reduction (Eq 30.3-2 / commentary Fig C30.3-2):
     For walls: GCp varies linearly (log-area) between the 10 ft² and 500 ft²
     anchor points given in Fig 30.3-2A.
     For roofs: GCp varies between 10 ft² and 100 ft² anchors (Fig 30.3-2C/D).
  5. Design pressure (§30.3.2, Eq 30.3-1):
       p = qh · (GCp − GCpi)  [positive pressure toward surface]
       positive case: p_pos = qh · (GCp_positive − GCpi_neg)   [GCpi_neg = −0.18]
       negative case: p_neg = qh · (GCp_negative − GCpi_pos)   [GCpi_pos = +0.18]
     Positive p = net inward (pressure); negative p = net outward (suction).

Zone naming follows ASCE 7-22 §30.3 / Fig 30.3-2:
  Walls:
    Zone_1_interior_wall — field of wall away from edges
    Zone_4_wall_edge     — strip within 10% of smallest building dimension
    Zone_5_corner_wall   — corner of building, Zone 4 × Zone 4 intersection
  Roofs (low-slope or flat; Fig 30.3-2C):
    Zone_1_roof_interior — field of roof away from edges
    Zone_2_roof_edge     — strip within 10% of smallest building dimension
    Zone_3_roof_corner   — roof corner region

Steep-roof GCp (ASCE 7-22 Fig 30.3-2D — gable/hip roofs 7° < θ ≤ 45°):
  The compute_wind_cc_pressure() function routes roof components through the
  steep-roof table when roof_slope_deg >= 7 is passed via ComponentSpec.
  Zone anchors per Fig 30.3-2D (log-linear on [10, 100] ft²):
    Zone_1_roof_interior:  GCp_neg_10=−1.0,  GCp_neg_100=−0.9  (suction field)
    Zone_2_roof_edge:      GCp_neg varies from −1.2 (θ=45°) to −2.3 (θ=7°)
    Zone_3_roof_corner:    GCp_neg varies from −2.0 (θ=45°) to −3.0 (θ=7°)
  Positive GCp (upward slope surfaces, θ≥7°):
    Zone_1 +0.5/+0.4; Zone_2/3 +0.5/+0.4 per Fig 30.3-2D note 3.

Parapet C&C pressures (ASCE 7-22 §30.9):
  Parapets use area-independent GCp,parap (no log-area reduction):
    Windward parapet: GCp,parap = +1.5 (net pressure toward windward face)
    Leeward parapet: GCp,parap = −1.0 (net pressure away from leeward face)
  Design pressure: p_parap = qh · GCp,parap  [GCpi NOT added for parapets per §30.9]
  Use compute_parapet_pressure() for parapet elements.

Scope and honest caveats:
  • Low-rise buildings (h ≤ 60 ft) only — §30.3 does NOT cover high-rise.
  • Enclosed buildings only — GCpi = ±0.18 (§26.13.2 Table 26.13-1).
    Partially-enclosed buildings (GCpi = ±0.55) are NOT modelled.
    Open buildings (GCpi = 0.00) are NOT modelled.
  • Simplified (§30.3) envelope approach — Directional Procedure §30.4 and
    the Alternative All-Heights Method §30.5 are out of scope.
  • Roof slopes ≤ 7° use Fig 30.3-2C anchors; slopes > 7° up to 45° use
    Fig 30.3-2D anchors via the steep-roof interpolation table.
  • Parapets (§30.9) are now implemented via compute_parapet_pressure().
  • Minimum pressure per §30.2.2: +/- 16 psf not enforced automatically;
    engineer must check.
  • Kzt default = 1.0 (flat terrain); set for hills per §26.8.
  • Ground elevation factor Ke = 1.0 (sea level).

References:
  ASCE/SEI 7-22, Minimum Design Loads and Associated Criteria for Buildings
    and Other Structures. American Society of Civil Engineers, 2022.
    §26.10  — velocity pressure exposure coefficient Kz (Table 26.10-1)
    §26.13.2 — internal pressure coefficient GCpi (Table 26.13-1)
    §30.1   — Components and Cladding scope
    §30.3   — Low-Rise Buildings (h ≤ 60 ft) — Eq 30.3-1
    §30.9   — Parapets C&C
    Fig 30.3-2A — GCp for wall C&C (positive and negative, vs effective area)
    Fig 30.3-2C — GCp for roof C&C (positive and negative, vs effective area)
    Fig 30.3-2D — GCp for roof C&C (gable/hip, 7° < θ ≤ 45°)
    Eq 30.3-2  — effective-area interpolation
    Mehta R.D. & Perry D.C. (2001) — pressure-zone commentary
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "ComponentSpec",
    "WindCCPressureReport",
    "ParapetPressureReport",
    "compute_wind_cc_pressure",
    "compute_parapet_pressure",
]

# ---------------------------------------------------------------------------
# Re-use site/building specs from the MWFRS module to avoid duplication
# ---------------------------------------------------------------------------
from kerf_cad_core.arch.wind_load_asce7 import (
    WindSiteSpec,
    BuildingSpec,
    _EXPOSURE_PARAMS,
    _KD_BUILDING,
    _Z_MIN_FT,
    _VALID_EXPOSURE,
    _VALID_RISK_CAT,
    _VALID_ENCLOSURE,
    _compute_kz,
)

# ---------------------------------------------------------------------------
# C&C zone constants
# ---------------------------------------------------------------------------

_VALID_CC_ZONES = frozenset({
    "Zone_1_interior_wall",
    "Zone_4_wall_edge",
    "Zone_5_corner_wall",
    "Zone_1_roof_interior",
    "Zone_2_roof_edge",
    "Zone_3_roof_corner",
})

_VALID_COMPONENT_TYPES = frozenset({"wall", "roof"})

# Internal pressure coefficient for enclosed buildings — ASCE 7-22 Table 26.13-1
# GCpi positive (worst for negative external GCp case)
# GCpi negative (worst for positive external GCp case)
_GCPI_ENCLOSED_POS = 0.18
_GCPI_ENCLOSED_NEG = -0.18

# ---------------------------------------------------------------------------
# GCp anchor table: (GCp_positive_10, GCp_positive_500or100,
#                    GCp_negative_10, GCp_negative_500or100, area_max_ft2)
#
# Wall anchors (Fig 30.3-2A): interpolate log-linearly on [10, 500] ft²
# Roof anchors (Fig 30.3-2C): interpolate log-linearly on [10, 100] ft²
#
# Values from ASCE 7-22 Fig 30.3-2A (walls) and Fig 30.3-2C (roof, ≤7° slope):
#
#  Wall Zone 1 (interior): +0.9 / +0.8 (10→500 ft²), -1.1 / -0.8 (10→500 ft²)
#  Wall Zone 4 (edge):     +1.0 / +0.8 (10→500 ft²), -1.1 / -0.8 (10→500 ft²)
#    [Zone 4 positive same as interior; negative same as Zone 1 per Fig 30.3-2A
#     note — this is slightly simplified: Fig 30.3-2A actual anchors are
#     edge zone = same negative curve but higher positive; use +1.0/+0.8]
#  Wall Zone 5 (corner):   +1.0 / +0.8 (10→500 ft²), -1.4 / -0.8 (10→500 ft²)
#    [Corner sees highest suction; Fig 30.3-2A Zone 5 = separate curve]
#
#  Roof Zone 1 (interior): +0.3 / +0.2 (10→100 ft²), -1.0 / -0.9 (10→100 ft²)
#  Roof Zone 2 (edge):     +0.3 / +0.2 (10→100 ft²), -1.8 / -1.1 (10→100 ft²)
#  Roof Zone 3 (corner):   +0.3 / +0.2 (10→100 ft²), -2.8 / -1.1 (10→100 ft²)
#
# Notes:
#  • All anchor values are at standard (unmodified) 10 ft² effective area from
#    Fig 30.3-2A/C ASCE 7-22.
#  • Log-linear interpolation: GCp(A) = GCp_10 + (GCp_max − GCp_10) ×
#    [log10(A/10) / log10(A_max/10)]  clamped to [GCp_10, GCp_max].
# ---------------------------------------------------------------------------

# Tuple layout: (GCp_pos_at_10, GCp_pos_at_Amax, GCp_neg_at_10, GCp_neg_at_Amax, A_max_ft2)
_GCP_ANCHORS: dict[str, tuple[float, float, float, float, float]] = {
    #                           GCp+@10  GCp+@Amax  GCp-@10  GCp-@Amax  Amax
    "Zone_1_interior_wall":  (  0.9,     0.8,        -1.1,    -0.8,      500.0),
    "Zone_4_wall_edge":      (  1.0,     0.8,        -1.1,    -0.8,      500.0),
    "Zone_5_corner_wall":    (  1.0,     0.8,        -1.4,    -0.8,      500.0),
    "Zone_1_roof_interior":  (  0.3,     0.2,        -1.0,    -0.9,      100.0),
    "Zone_2_roof_edge":      (  0.3,     0.2,        -1.8,    -1.1,      100.0),
    "Zone_3_roof_corner":    (  0.3,     0.2,        -2.8,    -1.1,      100.0),
}

# ---------------------------------------------------------------------------
# Steep-roof GCp table — ASCE 7-22 Fig 30.3-2D
# Gable/hip roofs: 7° < θ ≤ 45°.  Effective area range: [10, 100] ft².
#
# Negative GCp anchors per Fig 30.3-2D vary with slope θ:
#   Zone 1 (interior field): small slope dependence; −1.0@10 / −0.9@100 across range
#   Zone 2 (eave/edge strip): linear interpolation from −2.3 @ θ=7° to −1.2 @ θ=45°
#   Zone 3 (corner):          linear interpolation from −3.0 @ θ=7° to −2.0 @ θ=45°
#
# Positive GCp (surfaces facing into wind at higher slopes per Fig 30.3-2D note 3):
#   Zone 1/2/3: +0.5@10ft² / +0.4@100ft²
#
# θ is clamped to [7, 45] degrees before interpolation.
# ---------------------------------------------------------------------------

_STEEP_ROOF_SLOPE_LO = 7.0    # degrees — lower bound (flat-roof boundary)
_STEEP_ROOF_SLOPE_HI = 45.0   # degrees — upper bound of Fig 30.3-2D

# Zone 2 negative anchor at [θ_lo, θ_hi]: linear interpolation
_STEEP_ZONE2_NEG_10_AT_7DEG   = -2.3
_STEEP_ZONE2_NEG_10_AT_45DEG  = -1.2
# (the @100ft² anchor for zone 2 is less steep: −1.1 at θ=7° → −0.9 at θ=45°)
_STEEP_ZONE2_NEG_100_AT_7DEG  = -1.1
_STEEP_ZONE2_NEG_100_AT_45DEG = -0.9

# Zone 3 negative anchor at [θ_lo, θ_hi]
_STEEP_ZONE3_NEG_10_AT_7DEG   = -3.0
_STEEP_ZONE3_NEG_10_AT_45DEG  = -2.0
_STEEP_ZONE3_NEG_100_AT_7DEG  = -1.2
_STEEP_ZONE3_NEG_100_AT_45DEG = -0.8

# Positive GCp (same for all steep-roof zones per Fig 30.3-2D note 3)
_STEEP_POS_GCP_AT_10  =  0.5
_STEEP_POS_GCP_AT_100 =  0.4

# ---------------------------------------------------------------------------
# Parapet GCp constants — ASCE 7-22 §30.9
#
# GCp,parap is area-independent (single value, not a log-area curve).
# Design pressure: p_parap = qh · GCp,parap  (no GCpi addition per §30.9).
# ---------------------------------------------------------------------------

_GCPPARAP_WINDWARD = +1.5   # positive = net pressure toward windward parapet face
_GCPPARAP_LEEWARD  = -1.0   # negative = net suction away from leeward parapet face

_VALID_PARAPET_POSITIONS = frozenset({"windward", "leeward"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ComponentSpec:
    """
    Specification for a building component or cladding element.

    Parameters
    ----------
    area_ft2 : float
        Effective wind area of the component (ft²). Used for GCp reduction
        per ASCE 7-22 Fig 30.3-2A/C effective-area interpolation.
        Must be > 0.
        Effective area is typically the tributary area of the component,
        but for members spanning in one direction (e.g. purlins, girts), it
        is the span length × 1/3 of the span, per §26.2 definitions.
    zone : str
        Pressure zone per ASCE 7-22 §30.3 / Fig 30.3-2:
          "Zone_1_interior_wall" — field of wall, away from edges
          "Zone_4_wall_edge"     — edge strip of wall (within 10% of smallest bldg dim)
          "Zone_5_corner_wall"   — corner zone of wall
          "Zone_1_roof_interior" — field of roof (flat ≤7° or steep via Fig 30.3-2D)
          "Zone_2_roof_edge"     — roof edge strip
          "Zone_3_roof_corner"   — roof corner (highest negative pressure)
    component_type : str
        "wall" or "roof" — determines which GCp figure is used and which
        effective-area interpolation range applies.
    roof_slope_deg : float
        Roof slope in degrees (default 0.0 → flat/low-slope ≤7° per Fig 30.3-2C).
        When roof_slope_deg >= 7.0 and component_type == "roof", the steep-roof
        GCp table (Fig 30.3-2D) is used instead.  Clamped at 45°.
        Ignored for wall components.
    """
    area_ft2: float
    zone: str
    component_type: str = "wall"
    roof_slope_deg: float = 0.0


@dataclass
class ParapetPressureReport:
    """
    Output of ASCE 7-22 §30.9 C&C parapet pressure calculation.

    Parameters
    ----------
    qh_psf : float
        Velocity pressure at mean roof height (psf).
    GCp_parap : float
        Parapet pressure coefficient per §30.9:
          +1.5 for windward parapet; −1.0 for leeward parapet.
    p_design_psf : float
        Design pressure: p = qh · GCp,parap  (psf).
        Positive = toward windward face; negative = away from leeward face.
    parapet_position : str
        "windward" or "leeward".
    ASD_or_LRFD : str
        Strength level ("LRFD").
    code_section : list[str]
        ASCE 7-22 sections referenced.
    honest_caveat : str
        Plain-language scope statement.
    """
    qh_psf: float
    GCp_parap: float
    p_design_psf: float
    parapet_position: str
    ASD_or_LRFD: str
    code_section: list[str] = field(default_factory=list)
    honest_caveat: str = ""


@dataclass
class WindCCPressureReport:
    """
    Output of ASCE 7-22 §30.3 C&C design pressure calculation.

    Parameters
    ----------
    qz_psf : float
        Velocity pressure qh at mean roof height (psf).
    GCp_positive : float
        Combined external pressure coefficient for the net-positive (inward)
        case, after effective-area reduction.  GCp > 0.
    GCp_negative : float
        Combined external pressure coefficient for the net-negative (outward)
        case.  GCp < 0.
    p_design_positive_psf : float
        Net design pressure (positive = toward surface / inward):
        p = qh · (GCp_positive − GCpi_negative)
          = qh · (GCp_positive + 0.18)   [enclosed building]
    p_design_negative_psf : float
        Net design pressure (negative = away from surface / outward / suction):
        p = qh · (GCp_negative − GCpi_positive)
          = qh · (GCp_negative − 0.18)   [enclosed building]
        Reported as a negative value (suction convention).
    ASD_or_LRFD : str
        Strength level ("LRFD" for ASCE 7-22 strength-design pressures).
    code_section : list[str]
        ASCE 7-22 sections referenced.
    honest_caveat : str
        Plain-language scope statement.
    """
    qz_psf: float
    GCp_positive: float
    GCp_negative: float
    p_design_positive_psf: float
    p_design_negative_psf: float
    ASD_or_LRFD: str
    code_section: list[str] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# GCp effective-area interpolation
# ---------------------------------------------------------------------------

def _interpolate_gcp(gcp_at_10: float, gcp_at_amax: float,
                     area_ft2: float, a_max_ft2: float) -> float:
    """
    Log-linear interpolation of GCp between the 10 ft² and A_max anchors.

    ASCE 7-22 Fig 30.3-2A/C plots GCp on a log10(area) axis.  Values are
    anchored at 10 ft² and at A_max (500 ft² for walls; 100 ft² for roofs).
    Outside the range: clamp to the respective anchor.

    The interpolation follows the direction of the axis: for negative GCp
    (suction), |GCp| decreases as area increases (larger area = lower peak),
    so gcp_at_10 has higher magnitude than gcp_at_amax.

    Formula:
        t = log10(min(A, A_max) / 10) / log10(A_max / 10)
        GCp(A) = gcp_at_10 + (gcp_at_amax − gcp_at_10) * t
    clamped so the reduction never reverses sign or overshoots.
    """
    if area_ft2 <= 10.0:
        return gcp_at_10
    if area_ft2 >= a_max_ft2:
        return gcp_at_amax
    t = math.log10(area_ft2 / 10.0) / math.log10(a_max_ft2 / 10.0)
    return gcp_at_10 + (gcp_at_amax - gcp_at_10) * t


# ---------------------------------------------------------------------------
# Steep-roof GCp helper — ASCE 7-22 Fig 30.3-2D
# ---------------------------------------------------------------------------

def _steep_roof_gcp_anchors(
    zone: str, slope_deg: float
) -> tuple[float, float, float, float, float]:
    """
    Return (GCp_pos_10, GCp_pos_100, GCp_neg_10, GCp_neg_100, A_max=100) for a
    steep-roof zone at the given slope angle per Fig 30.3-2D.

    slope_deg is clamped to [7, 45] before interpolation.
    Zone must be one of Zone_1_roof_interior / Zone_2_roof_edge / Zone_3_roof_corner.
    """
    theta = max(_STEEP_ROOF_SLOPE_LO, min(_STEEP_ROOF_SLOPE_HI, slope_deg))
    # Linear interpolation parameter 0=7° .. 1=45°
    t = (theta - _STEEP_ROOF_SLOPE_LO) / (_STEEP_ROOF_SLOPE_HI - _STEEP_ROOF_SLOPE_LO)

    pos_10  = _STEEP_POS_GCP_AT_10
    pos_100 = _STEEP_POS_GCP_AT_100

    if zone == "Zone_1_roof_interior":
        neg_10  = -1.0
        neg_100 = -0.9
    elif zone == "Zone_2_roof_edge":
        neg_10  = _STEEP_ZONE2_NEG_10_AT_7DEG  + t * (_STEEP_ZONE2_NEG_10_AT_45DEG  - _STEEP_ZONE2_NEG_10_AT_7DEG)
        neg_100 = _STEEP_ZONE2_NEG_100_AT_7DEG + t * (_STEEP_ZONE2_NEG_100_AT_45DEG - _STEEP_ZONE2_NEG_100_AT_7DEG)
    else:  # Zone_3_roof_corner
        neg_10  = _STEEP_ZONE3_NEG_10_AT_7DEG  + t * (_STEEP_ZONE3_NEG_10_AT_45DEG  - _STEEP_ZONE3_NEG_10_AT_7DEG)
        neg_100 = _STEEP_ZONE3_NEG_100_AT_7DEG + t * (_STEEP_ZONE3_NEG_100_AT_45DEG - _STEEP_ZONE3_NEG_100_AT_7DEG)

    return pos_10, pos_100, neg_10, neg_100, 100.0


# ---------------------------------------------------------------------------
# Parapet C&C pressure — ASCE 7-22 §30.9
# ---------------------------------------------------------------------------

def compute_parapet_pressure(
    site: WindSiteSpec,
    building: BuildingSpec,
    parapet_position: str,
) -> "ParapetPressureReport":
    """
    Compute design wind pressure on a parapet per ASCE 7-22 §30.9.

    Parapets are treated as a special case: a single area-independent
    GCp,parap replaces the log-area curve used for other C&C elements.
    No GCpi is added (§30.9 gives a net combined coefficient).

    Parameters
    ----------
    site : WindSiteSpec
        Site wind speed, exposure, topographic factor, risk category.
    building : BuildingSpec
        Building geometry — mean_height_h_ft used for qh.
    parapet_position : str
        "windward" → GCp,parap = +1.5 (inward pressure on windward face)
        "leeward"  → GCp,parap = −1.0 (suction on leeward face)

    Returns
    -------
    ParapetPressureReport

    Raises
    ------
    ValueError
        If inputs are invalid or parapet_position is not "windward"/"leeward".

    Notes
    -----
    • §30.9 specifies GCp,parap as a combined net coefficient that already
      incorporates the internal/external pressure difference across the thin
      parapet wall.  GCpi is therefore NOT added separately.
    • The velocity pressure qh is evaluated at mean roof height h (not at
      the top of the parapet) as a conservative simplification consistent
      with §30.9 commentary.
    """
    # -- validate site
    if site.V_basic_mph <= 0.0:
        raise ValueError(f"V_basic_mph must be > 0, got {site.V_basic_mph}")
    if site.exposure_category not in _VALID_EXPOSURE:
        raise ValueError(
            f"exposure_category must be one of {sorted(_VALID_EXPOSURE)}, "
            f"got {site.exposure_category!r}"
        )
    if site.K_zt < 1.0:
        raise ValueError(f"K_zt must be ≥ 1.0, got {site.K_zt}")
    if site.risk_category not in _VALID_RISK_CAT:
        raise ValueError(
            f"risk_category must be one of {sorted(_VALID_RISK_CAT)}, "
            f"got {site.risk_category!r}"
        )

    # -- validate building
    if building.mean_height_h_ft <= 0.0:
        raise ValueError(f"mean_height_h_ft must be > 0, got {building.mean_height_h_ft}")

    # -- validate parapet position
    pos_lower = parapet_position.lower()
    if pos_lower not in _VALID_PARAPET_POSITIONS:
        raise ValueError(
            f"parapet_position must be 'windward' or 'leeward', "
            f"got {parapet_position!r}"
        )

    # -- qh at mean roof height
    alpha, zg_ft = _EXPOSURE_PARAMS[site.exposure_category]
    z_ft = building.mean_height_h_ft
    Kh = _compute_kz(z_ft, alpha, zg_ft)
    V = site.V_basic_mph
    qh = 0.00256 * Kh * site.K_zt * _KD_BUILDING * V * V

    # -- GCp,parap per §30.9
    GCp_parap = _GCPPARAP_WINDWARD if pos_lower == "windward" else _GCPPARAP_LEEWARD

    # -- design pressure: p = qh · GCp,parap  (no GCpi per §30.9)
    p_design = qh * GCp_parap

    code_sections = [
        "ASCE 7-22 §26.6 (Kd = 0.85 buildings)",
        "ASCE 7-22 §26.10 / Table 26.10-1 (Kh velocity pressure exposure coeff)",
        "ASCE 7-22 Eq 26.10-1 (qh = 0.00256·Kh·Kzt·Kd·V²)",
        "ASCE 7-22 §30.9 (C&C parapet pressures)",
    ]

    caveat = (
        f"ARCH-WIND-CC-PARAPET: ASCE 7-22 §30.9 parapet C&C. "
        f"Inputs: V={V} mph, Exposure {site.exposure_category}, "
        f"h={z_ft} ft, Kzt={site.K_zt}, position={pos_lower}. "
        f"Kh={Kh:.4f}, qh={qh:.2f} psf. "
        f"GCp,parap={GCp_parap} ({'windward +1.5' if pos_lower == 'windward' else 'leeward -1.0'}). "
        f"p_design = qh · GCp,parap = {p_design:.2f} psf "
        f"({'inward pressure on windward face' if pos_lower == 'windward' else 'suction on leeward face'}). "
        f"NOTE: §30.9 GCp,parap is area-independent and net combined; GCpi NOT added separately. "
        f"Parapet height above roofline NOT separately accounted; conservative qh at h used. "
        f"Minimum pressure ±16 psf (§30.2.2) must be verified manually."
    )

    return ParapetPressureReport(
        qh_psf=round(qh, 4),
        GCp_parap=GCp_parap,
        p_design_psf=round(p_design, 4),
        parapet_position=pos_lower,
        ASD_or_LRFD="LRFD",
        code_section=code_sections,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_wind_cc_pressure(
    site: WindSiteSpec,
    building: BuildingSpec,
    component: ComponentSpec,
) -> WindCCPressureReport:
    """
    Compute design wind pressure on a building component or cladding element
    per ASCE 7-22 §30.3 (Low-Rise Buildings, h ≤ 60 ft).

    Parameters
    ----------
    site : WindSiteSpec
        Site wind speed, exposure, topographic, and risk category data.
    building : BuildingSpec
        Building geometry.  mean_height_h_ft must be ≤ 60 ft for §30.3
        applicability (a warning is embedded in the caveat; the math still
        executes so users of h up to 60 ft can call directly).
    component : ComponentSpec
        Component pressure zone and effective area.

    Returns
    -------
    WindCCPressureReport
        Velocity pressure qh, interpolated GCp (positive and negative),
        net design pressures, and scope caveats.

    Raises
    ------
    ValueError
        If any input parameter is out of range or invalid.

    Notes
    -----
    • p_design_positive = qh · (GCp_pos − GCpi_neg) = qh · (GCp_pos + 0.18)
    • p_design_negative = qh · (GCp_neg − GCpi_pos) = qh · (GCp_neg − 0.18)
    • GCpi = ±0.18 for enclosed buildings (Table 26.13-1).
    • Partially-enclosed (GCpi = ±0.55) NOT implemented.
    """
    # ------------------------------------------------------------------ validate site
    if site.V_basic_mph <= 0.0:
        raise ValueError(f"V_basic_mph must be > 0, got {site.V_basic_mph}")
    if site.exposure_category not in _VALID_EXPOSURE:
        raise ValueError(
            f"exposure_category must be one of {sorted(_VALID_EXPOSURE)}, "
            f"got {site.exposure_category!r}"
        )
    if site.K_zt < 1.0:
        raise ValueError(
            f"K_zt must be ≥ 1.0, got {site.K_zt}"
        )
    if site.risk_category not in _VALID_RISK_CAT:
        raise ValueError(
            f"risk_category must be one of {sorted(_VALID_RISK_CAT)}, "
            f"got {site.risk_category!r}"
        )

    # ------------------------------------------------------------------ validate building
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

    # ------------------------------------------------------------------ validate component
    if component.area_ft2 <= 0.0:
        raise ValueError(f"area_ft2 must be > 0, got {component.area_ft2}")
    if component.zone not in _VALID_CC_ZONES:
        raise ValueError(
            f"zone must be one of {sorted(_VALID_CC_ZONES)}, "
            f"got {component.zone!r}"
        )
    if component.component_type not in _VALID_COMPONENT_TYPES:
        raise ValueError(
            f"component_type must be 'wall' or 'roof', "
            f"got {component.component_type!r}"
        )

    # Cross-check zone vs component_type
    is_roof_zone = component.zone.startswith("Zone_") and "roof" in component.zone
    is_wall_zone = not is_roof_zone
    if component.component_type == "roof" and is_wall_zone:
        raise ValueError(
            f"component_type='roof' but zone={component.zone!r} is a wall zone. "
            f"Roof zones: Zone_1_roof_interior, Zone_2_roof_edge, Zone_3_roof_corner."
        )
    if component.component_type == "wall" and is_roof_zone:
        raise ValueError(
            f"component_type='wall' but zone={component.zone!r} is a roof zone. "
            f"Wall zones: Zone_1_interior_wall, Zone_4_wall_edge, Zone_5_corner_wall."
        )

    # ------------------------------------------------------------------ qh
    alpha, zg_ft = _EXPOSURE_PARAMS[site.exposure_category]
    z_ft = building.mean_height_h_ft
    Kh = _compute_kz(z_ft, alpha, zg_ft)
    V = site.V_basic_mph
    qh = 0.00256 * Kh * site.K_zt * _KD_BUILDING * V * V

    # ------------------------------------------------------------------ GCp interpolation
    # Route steep-roof zones (slope >= 7°) through Fig 30.3-2D table;
    # flat/low-slope roofs and walls use the standard Fig 30.3-2A/C anchors.
    use_steep_roof = (
        component.component_type == "roof"
        and component.roof_slope_deg >= _STEEP_ROOF_SLOPE_LO
    )

    if use_steep_roof:
        gcp_pos_10, gcp_pos_amax, gcp_neg_10, gcp_neg_amax, a_max = (
            _steep_roof_gcp_anchors(component.zone, component.roof_slope_deg)
        )
        gcp_figure = f"Fig 30.3-2D (steep roof, θ={component.roof_slope_deg}°)"
    else:
        anchors = _GCP_ANCHORS[component.zone]
        gcp_pos_10, gcp_pos_amax, gcp_neg_10, gcp_neg_amax, a_max = anchors
        gcp_figure = "Fig 30.3-2A/C (wall/low-slope roof)"

    GCp_pos = _interpolate_gcp(gcp_pos_10, gcp_pos_amax, component.area_ft2, a_max)
    GCp_neg = _interpolate_gcp(gcp_neg_10, gcp_neg_amax, component.area_ft2, a_max)

    # ------------------------------------------------------------------ design pressures
    # Enclosed building: GCpi = ±0.18 (ASCE 7-22 Table 26.13-1)
    # p_net = qh · (GCp_external − GCpi)
    # Positive (worst inward): GCp_ext = +ve, GCpi = −0.18
    # Negative (worst outward): GCp_ext = −ve, GCpi = +0.18
    GCpi_neg = _GCPI_ENCLOSED_NEG  # = -0.18
    GCpi_pos = _GCPI_ENCLOSED_POS  # = +0.18

    p_positive = qh * (GCp_pos - GCpi_neg)   # = qh * (GCp_pos + 0.18)
    p_negative = qh * (GCp_neg - GCpi_pos)   # = qh * (GCp_neg - 0.18)

    # ------------------------------------------------------------------ caveats
    high_rise_warn = (
        " WARNING: mean_height_h_ft > 60 ft — §30.3 applies only to h ≤ 60 ft;"
        " use §30.4 (All-Heights Directional Procedure) for taller buildings."
    ) if z_ft > 60.0 else ""

    roof_fig_ref = (
        "ASCE 7-22 Fig 30.3-2D (GCp vs effective area — steep roofs 7°–45°)"
        if use_steep_roof
        else "ASCE 7-22 Fig 30.3-2C (GCp vs effective area — roofs ≤7° slope)"
    )

    code_sections = [
        "ASCE 7-22 §26.6 (Kd = 0.85 buildings)",
        "ASCE 7-22 §26.10 / Table 26.10-1 (Kh velocity pressure exposure coeff)",
        "ASCE 7-22 Eq 26.10-1 (qh = 0.00256·Kh·Kzt·Kd·V²)",
        "ASCE 7-22 §26.13.2 / Table 26.13-1 (GCpi = ±0.18 enclosed buildings)",
        "ASCE 7-22 §30.1 (C&C applicability)",
        "ASCE 7-22 §30.3 / Eq 30.3-1 (Low-Rise C&C net design pressure)",
        "ASCE 7-22 Fig 30.3-2A (GCp vs effective area — walls)",
        roof_fig_ref,
    ]

    caveat = (
        f"ARCH-WIND-CC-PRESSURE: ASCE 7-22 §30.3 C&C. "
        f"Inputs: V={V} mph, Exposure {site.exposure_category}, "
        f"h={z_ft} ft, Kzt={site.K_zt}, zone={component.zone}, "
        f"A={component.area_ft2} ft², type={component.component_type}, "
        f"slope={component.roof_slope_deg}°, enclosure={building.enclosure}. "
        f"GCp source: {gcp_figure}. "
        f"Kh={Kh:.4f}, qh={qh:.2f} psf. "
        f"GCp_pos={GCp_pos:.3f} (at A={component.area_ft2} ft²; anchors +{gcp_pos_10}/{gcp_pos_amax}), "
        f"GCp_neg={GCp_neg:.3f} (anchors {gcp_neg_10}/{gcp_neg_amax}, A_max={a_max} ft²). "
        f"GCpi = ±0.18 (enclosed, Table 26.13-1). "
        f"p_design_positive = qh·(GCp_pos+0.18) = {p_positive:.2f} psf (inward). "
        f"p_design_negative = qh·(GCp_neg−0.18) = {p_negative:.2f} psf (outward/suction). "
        f"NOT INCLUDED: partially-enclosed GCpi=±0.55 (§26.13.2) — enclosed only; "
        f"open buildings (GCpi=0); Envelope Procedure (§30.4) for h>60 ft; "
        f"parapets (§30.9) — use compute_parapet_pressure(); "
        f"roof slopes >45° not supported; "
        f"tornado loads (§32); Ke ground-elevation factor (§26.9); "
        f"minimum pressure check of ±16 psf (§30.2.2) must be verified manually."
        f"{high_rise_warn}"
    )

    return WindCCPressureReport(
        qz_psf=round(qh, 4),
        GCp_positive=round(GCp_pos, 4),
        GCp_negative=round(GCp_neg, 4),
        p_design_positive_psf=round(p_positive, 4),
        p_design_negative_psf=round(p_negative, 4),
        ASD_or_LRFD="LRFD",
        code_section=code_sections,
        honest_caveat=caveat,
    )
