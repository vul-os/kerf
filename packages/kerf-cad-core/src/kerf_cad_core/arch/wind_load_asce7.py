"""
kerf_cad_core.arch.wind_load_asce7 — Design wind pressure per ASCE 7-22 Directional Procedure.

Implements ASCE 7-22 Chapter 26–27 Directional Procedure for Main Wind Force-Resisting
Systems (MWFRS) of enclosed/partially-enclosed buildings, §27.5 Directional Procedure for
Open Buildings (monoslope/troughed/pitched free roofs), and §28 Envelope Procedure for
low-rise buildings (h ≤ 60 ft, h/L ≤ 1.0).

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

Method (§27.5 — Open Buildings, monoslope/troughed/pitched free roofs):
  Net roof pressure p_net = qh · GCp_net  (no internal pressure term — open building).
  GCp_net from ASCE 7-22 Fig 27.5-1 (monoslope, troughed) / Fig 27.5-2 (pitched),
  tabulated as a function of roof pitch θ.  Positive = downward; negative = uplift.
  This module returns the controlling (envelope) positive and negative GCp_net bounds.

Method (§28 — Envelope Procedure, low-rise buildings):
  Applicability: h ≤ 60 ft AND h/L ≤ 1.0 (§28.3.1).
  Design pressure p = qh · (GCpf) − qi · (GCpi)  where qi = qh (§28.4.1).
  GCpf from ASCE 7-22 Fig 28.4-1 (combined wall + roof MWFRS); interior and end zones
  (A–H for Case A; E–J for end-zone) returned as zone-by-zone pressure dict.

Scope and honest caveats:
  • §27.5 Open Building: GCp_net tabulated per Fig 27.5-1/2 as a function of θ;
    column-by-column zone splitting (near/far half) is NOT modelled — single controlling
    (envelope) GCp_net pair returned per roof type.
  • §28 Envelope Procedure: GCpf values from Fig 28.4-1 fixed-table implementation;
    roof-pitch adjustments from Fig 28.4-1 supplementary data not applied beyond the
    base tabulation — conservative flat/low-slope values used for pitched roofs.
  • Directional Procedure (§26–27) — Envelope Procedure (§28) previously not implemented;
    now added via compute_low_rise_envelope_pressure().
  • Tornado loads (§32): implemented via compute_tornado_load() for Risk Category III/IV
    buildings in the tornado-prone region. See TornadoLoadSpec / TornadoLoadReport below.
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
    §26.13  (internal pressure coefficient GCpi — NOT included in §27 calc)
    §27.3   (Directional Procedure applicability)
    §27.4   (design wind pressure, Eq 27.4-1)
    Fig 27.4-1 (external pressure coefficients Cp for MWFRS)
    §27.5   (Directional Procedure for Open Buildings with free roofs)
    Fig 27.5-1 (GCp,net for monoslope and troughed open free roofs)
    Fig 27.5-2 (GCp,net for pitched open free roofs)
    §28.3.1 (Envelope Procedure applicability: h ≤ 60 ft, h/L ≤ 1.0)
    §28.4   (Envelope Procedure design pressure, Eq 28.4-1)
    Fig 28.4-1 (GCpf combined wall+roof pressure zones for low-rise MWFRS)
    §32     (Tornado Loads — new Chapter added in ASCE 7-22)
    §32.5   (tornado wind speed V_T maps, Risk Category III and IV)
    §32.6.2 (tornado wind directionality factor K_d_T = 0.55)
    §32.6.4 (tornado topographic factor K_zt = 1.0)
    §32.10.2 (tornado internal pressure coefficient GCpi = ±0.55 enclosed)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "WindSiteSpec",
    "BuildingSpec",
    "WindPressureReport",
    "compute_wind_load",
    # ASCE 7-22 §27.5 open building free-roof pressures
    "OpenBuildingSpec",
    "OpenBuildingPressureReport",
    "compute_open_building_pressure",
    # ASCE 7-22 §28 Envelope Procedure (low-rise buildings)
    "LowRiseEnvelopeSpec",
    "LowRiseEnvelopePressureReport",
    "compute_low_rise_envelope_pressure",
    # ASCE 7-22 §32 tornado loads
    "TornadoLoadSpec",
    "TornadoLoadReport",
    "compute_tornado_load",
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
# ASCE 7-22 §32 Tornado Load constants
# ---------------------------------------------------------------------------

# Tornado wind directionality factor — ASCE 7-22 §32.6.2 (NOT the same as wind Kd=0.85)
_KD_TORNADO = 0.55

# Tornado topographic factor — ASCE 7-22 §32.6.4 (flat terrain assumption)
_KZT_TORNADO = 1.0

# Tornado gust factor — ASCE 7-22 §32.9.1 (same rigid-structure value as §26.11)
_G_TORNADO = 0.85

# Tornado external Cp values for MWFRS walls — ASCE 7-22 §32.9.2 (same Fig 27.4-1 values)
_CP_WINDWARD_TORNADO = 0.8
# Leeward Cp uses the same _leeward_cp() interpolation per §32.9.2

# Tornado internal pressure coefficient (GCpi) — ASCE 7-22 §32.10.2
# Enclosed:          GCpi = ±0.55  (much higher than standard ±0.18)
# Partially enclosed: GCpi = ±0.55  (same; dominant opening scenario included in tornado)
_GCPI_TORNADO_ENCLOSED = 0.55
_GCPI_TORNADO_PARTIAL = 0.55

# Tornado importance (loss) factor I_T — ASCE 7-22 §32.5 / Table 32.5-1
# RC III → 1.0, RC IV → 1.2 (essential facilities carry higher tornado demand)
_IT_BY_RC: dict[str, float] = {"III": 1.0, "IV": 1.2}

# Tornado-prone region applies to Risk Category III and IV only (§32.1.1)
_VALID_TORNADO_RC = frozenset({"III", "IV"})

# Exposure C constants used for all tornado velocity pressure calculations (§32.6.3)
_TORNADO_EXPOSURE_ALPHA, _TORNADO_EXPOSURE_ZG = _EXPOSURE_PARAMS["C"]  # 9.5, 900.0


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
# ASCE 7-22 §27.5 Open Building dataclasses
# ---------------------------------------------------------------------------

_VALID_OPEN_ROOF_TYPES = frozenset({"monoslope", "troughed", "pitched"})


@dataclass
class OpenBuildingSpec:
    """
    Input specification for ASCE 7-22 §27.5 Directional Procedure — Open Buildings.

    Open buildings have each wall ≥ 80% open.  Wind acts directly on the free roof
    (monoslope, troughed, or pitched) with no internal pressure component.

    Parameters
    ----------
    roof_type : str
        Roof geometry: ``"monoslope"``, ``"troughed"``, or ``"pitched"``.
        Monoslope — single plane sloped in one direction.
        Troughed  — V-shape (lower at centre, rises to both eaves).
        Pitched   — inverted-V (higher at ridge, slopes to both eaves).
    pitch_deg : float
        Roof pitch angle θ in degrees from horizontal.  Must be in [0, 45].
    building_height_ft : float
        Mean roof height h (ft) above grade.  Must be > 0.
    """
    roof_type: str
    pitch_deg: float
    building_height_ft: float


@dataclass
class OpenBuildingPressureReport:
    """
    Output of ASCE 7-22 §27.5 open-building free-roof pressure calculation.

    Returns the controlling (envelope) GCp_net bounds and the resulting
    positive (downward) and negative (uplift) net pressures.

    Parameters
    ----------
    qh_psf : float
        Velocity pressure at mean roof height h (psf).
    Kz : float
        Velocity pressure exposure coefficient at h.
    GCp_net_pos : float
        Maximum positive (downward) net pressure coefficient per Fig 27.5-1/2.
    GCp_net_neg : float
        Maximum negative (uplift) net pressure coefficient per Fig 27.5-1/2
        (negative value).
    p_net_pos_psf : float
        Maximum downward net pressure: qh · GCp_net_pos (psf).
    p_net_neg_psf : float
        Maximum uplift net pressure: qh · GCp_net_neg (psf, negative = uplift).
    roof_type : str
        Roof geometry used.
    pitch_deg : float
        Roof pitch angle θ (degrees).
    code_section : list[str]
        ASCE 7-22 sections referenced.
    honest_caveat : str
        Plain-language scope statement.
    """
    qh_psf: float
    Kz: float
    GCp_net_pos: float
    GCp_net_neg: float
    p_net_pos_psf: float
    p_net_neg_psf: float
    roof_type: str
    pitch_deg: float
    code_section: list[str] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# ASCE 7-22 §28 Low-Rise Envelope Procedure dataclasses
# ---------------------------------------------------------------------------

_VALID_LOW_RISE_ROOF_TYPES = frozenset({"flat", "monoslope", "gable", "hip"})


@dataclass
class LowRiseEnvelopeSpec:
    """
    Input specification for ASCE 7-22 §28 Envelope Procedure (low-rise buildings).

    Applicability (§28.3.1):
      • Mean roof height h ≤ 60 ft
      • h / L ≤ 1.0  (L = building length in wind direction)

    Parameters
    ----------
    building_length_ft : float
        Building dimension L (ft) parallel to the wind direction.  Must be > 0.
    width_ft : float
        Building dimension B (ft) perpendicular to the wind direction.  Must be > 0.
    height_ft : float
        Mean roof height h (ft).  Must satisfy h ≤ 60 ft and h/L ≤ 1.0.
    roof_type : str
        Roof geometry: ``"flat"``, ``"monoslope"``, ``"gable"``, or ``"hip"``.
    roof_pitch_deg : float
        Roof pitch angle (degrees from horizontal).  Use 0.0 for flat roofs.
    exposure : str
        Exposure category: ``"B"``, ``"C"``, or ``"D"`` per §26.7.
    """
    building_length_ft: float
    width_ft: float
    height_ft: float
    roof_type: str = "flat"
    roof_pitch_deg: float = 0.0
    exposure: str = "C"


@dataclass
class LowRiseEnvelopePressureReport:
    """
    Output of ASCE 7-22 §28 Envelope Procedure (low-rise buildings).

    GCpf values from ASCE 7-22 Fig 28.4-1 (combined wall + roof MWFRS pressures).
    Pressures are computed for interior zones (1–6) and end zones (1E–6E).

    Zone definitions (§28.4 / Fig 28.4-1):
      Load Case A (wind parallel to ridge / gable-end wind):
        Zone 1  — windward wall (interior)
        Zone 2  — leeward wall (interior)
        Zone 3  — side wall (interior)
        Zone 4  — windward roof (interior)
        Zone 1E — windward wall (end zone, within distance a of corner)
        Zone 2E — leeward wall (end zone)
        Zone 3E — side wall (end zone)
        Zone 4E — windward roof (end zone)
      Load Case B (wind perpendicular to ridge):
        Zone 5  — windward wall (interior)
        Zone 6  — leeward wall (interior)
        Zone 5E — windward wall (end zone)
        Zone 6E — leeward wall (end zone)

    Parameters
    ----------
    qh_psf : float
        Velocity pressure at mean roof height h (psf).
    Kz : float
        Velocity pressure exposure coefficient at h.
    end_zone_a_ft : float
        End-zone width a (ft) = min(0.1·B, 0.4·h), but ≥ max(0.04·B, 3 ft).
    zone_pressures_psf : dict[str, float]
        Computed net pressures (psf) keyed by zone label.  Positive = toward
        surface (inward for walls, downward for roofs); negative = suction/uplift.
        Includes GCpi = ±0.18 (enclosed) for the governing (worst-case) combination.
    code_section : list[str]
        ASCE 7-22 sections referenced.
    honest_caveat : str
        Plain-language scope statement.
    """
    qh_psf: float
    Kz: float
    end_zone_a_ft: float
    zone_pressures_psf: dict[str, float] = field(default_factory=dict)
    code_section: list[str] = field(default_factory=list)
    honest_caveat: str = ""


@dataclass
class TornadoLoadSpec:
    """
    Input specification for ASCE 7-22 §32 tornado load calculation.

    ASCE 7-22 Chapter 32 introduced explicit tornado design provisions for
    Risk Category III and IV buildings located in the tornado-prone region
    (continental United States east of 105° W longitude + portions of the
    Gulf Coast, per §32.1.1 and Fig 32.1-1).

    Parameters
    ----------
    tornado_speed_V_T_mph : float
        Tornado wind speed V_T (mph) from the §32.5 maps (Fig 32.5-1A for
        RC III, Fig 32.5-1B for RC IV).  Typical values range from about
        60 mph (low-hazard fringe) to 250 mph (Oklahoma/Kansas core).
        Must be > 0.
    risk_category : str
        Risk Category per §1.5 — must be "III" or "IV".  Tornado Chapter 32
        applies only to these risk categories. RC I/II buildings are NOT
        required to be designed for tornado loads by ASCE 7-22.
    enclosure : str
        Building enclosure classification:
          "enclosed"  — standard occupied building (GCpi = ±0.55 per §32.10.2)
          "partial"   — partially-enclosed per §26.12.2 (GCpi = ±0.55 per §32.10.2;
                        same value as enclosed in the tornado chapter)
    building_height_ft : float
        Mean roof height h (ft) used for Kz calculation. Must be > 0.
    length_ft : float
        Building dimension parallel to the tornado track L (ft). Used for
        leeward Cp interpolation. Must be > 0.
    width_ft : float
        Building dimension perpendicular to the tornado track B (ft). Must be > 0.
    """
    tornado_speed_V_T_mph: float
    risk_category: str  # "III" or "IV"
    enclosure: str      # "enclosed" or "partial"
    building_height_ft: float
    length_ft: float = 60.0
    width_ft: float = 60.0


@dataclass
class TornadoLoadReport:
    """
    Output of ASCE 7-22 §32 tornado load calculation.

    Parameters
    ----------
    velocity_pressure_q_psf : float
        Tornado velocity pressure q_z (psf) at mean roof height:
        q_z = 0.00256 · K_z · K_zt_T · K_d_T · V_T²
        where K_d_T = 0.55 (§32.6.2), K_zt_T = 1.0 (§32.6.4),
        and K_z uses Exposure C constants (§32.6.3).
    Kz : float
        Velocity pressure exposure coefficient at h using Exposure C constants.
    K_d_T : float
        Tornado wind directionality factor = 0.55 (§32.6.2).
    I_T : float
        Tornado importance (loss) factor: 1.0 for RC III, 1.2 for RC IV (§32.5).
    gcpi_internal : float
        Magnitude of the internal pressure coefficient GCpi = 0.55 (§32.10.2).
        Design net pressure uses +(0.55) and −(0.55) combinations.
    mwfrs_walls_psf : dict[str, float]
        MWFRS wall design pressures (psf) keyed by:
          "windward_net_max"   — max net windward: q·G·Cp_w + q·GCpi (suction interior)
          "windward_net_min"   — min net windward: q·G·Cp_w − q·GCpi (pressure interior)
          "leeward_net_max"    — max net leeward (suction + suction interior)
          "leeward_net_min"    — min net leeward (suction + pressure interior)
          "total_drag"         — net lateral drag = q·G·(Cp_w − Cp_l) (no GCpi)
        Positive values act toward the surface (pressure); negative = suction.
    Cp_windward : float
        External Cp for windward wall = +0.8 (§32.9.2 / Fig 27.4-1).
    Cp_leeward : float
        External Cp for leeward wall (negative; interpolated from L/B per Fig 27.4-1).
    L_over_B : float
        Length-to-width ratio used for leeward Cp.
    code_section : list[str]
        ASCE 7-22 sections referenced in this calculation.
    honest_caveat : str
        Scope statement: what is included and what is NOT in this tornado calculation.
    """
    velocity_pressure_q_psf: float
    Kz: float
    K_d_T: float
    I_T: float
    gcpi_internal: float
    mwfrs_walls_psf: dict[str, float]
    Cp_windward: float
    Cp_leeward: float
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


def compute_tornado_load(tornado_spec: TornadoLoadSpec) -> TornadoLoadReport:
    """
    Compute MWFRS wall design pressures under tornado loading per ASCE 7-22 §32.

    ASCE 7-22 Chapter 32 introduced mandatory tornado design for Risk Category III
    and IV buildings in the tornado-prone region.  Key differences from standard
    Directional Procedure (§26–27):

      • K_d_T = 0.55 (§32.6.2)  — lower than building wind K_d = 0.85
      • K_zt   = 1.0 (§32.6.4)  — flat-terrain assumption always used
      • Exposure C constants always used for K_z (§32.6.3), regardless of
        the site exposure category for ordinary wind
      • GCpi   = ±0.55 (§32.10.2) — enclosed buildings; much higher than
        the standard ±0.18 (Table 26.13-1) because a tornado can depressurise
        the interior through failed openings and cladding
      • External Cp and G use the same Fig 27.4-1 values and G=0.85 (§32.9.2)
      • I_T (importance/loss factor): 1.0 for RC III, 1.2 for RC IV (§32.5)
        — multiplied into the mwfrs_walls_psf values

    Parameters
    ----------
    tornado_spec : TornadoLoadSpec
        Tornado wind speed, Risk Category, enclosure, and building geometry.

    Returns
    -------
    TornadoLoadReport
        Tornado velocity pressure q_z, exposure K_z, K_d_T, I_T, GCpi,
        MWFRS wall net pressures, Cp values, and caveat text.

    Raises
    ------
    ValueError
        If any input parameter is out of range.

    Notes
    -----
    Net wall pressures follow §32.9 Eq 32.9-1:
        p = q_z · G · Cp ± q_z · GCpi   (internal ± adds to/subtracts from external)
    Positive = pressure toward surface; negative = suction away from surface.
    Both the "max" (worst-case suction interior) and "min" (pressure interior)
    combinations are reported for each wall face.
    """
    # ------------------------------------------------------------------ validation
    V_T = tornado_spec.tornado_speed_V_T_mph
    if V_T <= 0.0:
        raise ValueError(f"tornado_speed_V_T_mph must be > 0, got {V_T}")
    if tornado_spec.risk_category not in _VALID_TORNADO_RC:
        raise ValueError(
            f"Tornado loads (§32) apply only to RC III or RC IV; "
            f"got risk_category={tornado_spec.risk_category!r}. "
            f"RC I and RC II buildings are not required to be designed for tornado "
            f"loads per ASCE 7-22 §32.1.1."
        )
    if tornado_spec.enclosure not in {"enclosed", "partial"}:
        raise ValueError(
            f"enclosure must be 'enclosed' or 'partial', "
            f"got {tornado_spec.enclosure!r}"
        )
    h = tornado_spec.building_height_ft
    if h <= 0.0:
        raise ValueError(f"building_height_ft must be > 0, got {h}")
    L = tornado_spec.length_ft
    W = tornado_spec.width_ft
    if L <= 0.0:
        raise ValueError(f"length_ft must be > 0, got {L}")
    if W <= 0.0:
        raise ValueError(f"width_ft must be > 0, got {W}")

    # ------------------------------------------------------------------ Kz (Exposure C, §32.6.3)
    alpha_c = _TORNADO_EXPOSURE_ALPHA  # 9.5
    zg_c    = _TORNADO_EXPOSURE_ZG     # 900.0 ft
    Kz = _compute_kz(h, alpha_c, zg_c)

    # ------------------------------------------------------------------ q_z (tornado)
    # ASCE 7-22 §32.6: q_z = 0.00256 · K_z · K_zt_T · K_d_T · V_T²  (psf)
    # K_zt_T = 1.0 (§32.6.4), K_d_T = 0.55 (§32.6.2)
    q_z = 0.00256 * Kz * _KZT_TORNADO * _KD_TORNADO * V_T * V_T

    # ------------------------------------------------------------------ Importance factor
    I_T = _IT_BY_RC[tornado_spec.risk_category]

    # ------------------------------------------------------------------ Cp
    L_over_B = L / W
    Cp_w = _CP_WINDWARD_TORNADO     # +0.8
    Cp_l = _leeward_cp(L_over_B)   # negative

    # ------------------------------------------------------------------ GCpi
    GCpi = _GCPI_TORNADO_ENCLOSED   # 0.55 for both enclosed and partial (§32.10.2)

    # ------------------------------------------------------------------ MWFRS net pressures
    # §32.9 Eq 32.9-1: p = q_z · G · Cp ± q_z · GCpi
    # The ± GCpi term is added or subtracted to find governing (worst) design case.
    # Positive pressure = toward surface; negative = away (suction).
    G = _G_TORNADO

    # Windward wall:
    #   External: q_z · G · Cp_w   (positive, toward surface)
    #   Internal: ±q_z · GCpi
    #   Max (interior suction, both external + internal act inward):
    #     p_w_max = q_z·G·Cp_w + q_z·GCpi
    #   Min (interior pressure reduces net):
    #     p_w_min = q_z·G·Cp_w - q_z·GCpi
    p_w_max = I_T * (q_z * G * Cp_w + q_z * GCpi)
    p_w_min = I_T * (q_z * G * Cp_w - q_z * GCpi)

    # Leeward wall:
    #   External: q_z · G · Cp_l   (negative, suction away from surface)
    #   Internal: ±q_z · GCpi
    #   Max suction (interior suction + exterior suction, same direction outward):
    #     p_l_max_suction = q_z·G·Cp_l - q_z·GCpi  (both negative → most negative)
    #   Min suction (interior pressure opposes exterior suction):
    #     p_l_min_suction = q_z·G·Cp_l + q_z·GCpi
    p_l_max_suction = I_T * (q_z * G * Cp_l - q_z * GCpi)  # most negative
    p_l_min_suction = I_T * (q_z * G * Cp_l + q_z * GCpi)

    # Net lateral drag (no GCpi — cancels on opposing walls for MWFRS lateral force)
    total_drag = I_T * q_z * G * (Cp_w - Cp_l)  # = q_z·G·(Cp_w + |Cp_l|)

    mwfrs = {
        "windward_net_max": round(p_w_max, 4),          # max inward pressure
        "windward_net_min": round(p_w_min, 4),          # min inward pressure (or suction if neg)
        "leeward_net_max_suction": round(p_l_max_suction, 4),   # worst suction (most negative)
        "leeward_net_min_suction": round(p_l_min_suction, 4),   # least suction
        "total_drag": round(total_drag, 4),              # net lateral, no GCpi
    }

    # ------------------------------------------------------------------ code sections
    code_sections = [
        "ASCE 7-22 §32.1.1 (tornado-prone region applicability)",
        "ASCE 7-22 §32.5 / Fig 32.5-1A/B (tornado wind speed maps, RC III / RC IV)",
        "ASCE 7-22 §32.6.2 (K_d_T = 0.55)",
        "ASCE 7-22 §32.6.3 (Exposure C constants for K_z)",
        "ASCE 7-22 §32.6.4 (K_zt = 1.0)",
        "ASCE 7-22 §32.6 (q_z = 0.00256·K_z·K_zt·K_d_T·V_T²)",
        "ASCE 7-22 §32.9.2 / Fig 27.4-1 (external Cp, G = 0.85)",
        "ASCE 7-22 §32.10.2 (GCpi = ±0.55 for enclosed/partially-enclosed)",
        "ASCE 7-22 §32.5 / Table 32.5-1 (I_T importance factor)",
    ]

    # ------------------------------------------------------------------ caveat
    caveat = (
        f"ARCH-TORNADO-LOAD-ASCE7: ASCE 7-22 §32 Tornado MWFRS wall pressures. "
        f"Inputs: V_T={V_T} mph, RC={tornado_spec.risk_category}, "
        f"enclosure={tornado_spec.enclosure!r}, h={h} ft, L/B={L_over_B:.3f}. "
        f"Tornado factors: K_d_T={_KD_TORNADO} (§32.6.2, cf. K_d=0.85 for wind), "
        f"K_zt=1.0 (§32.6.4), Exposure C K_z={Kz:.4f} (§32.6.3), "
        f"G={G} (§32.9.2), GCpi=±{GCpi} (§32.10.2), I_T={I_T} (§32.5). "
        f"Results: q_z={q_z:.2f} psf, "
        f"windward_net_max={p_w_max:.2f} psf, windward_net_min={p_w_min:.2f} psf, "
        f"leeward_net_max_suction={p_l_max_suction:.2f} psf, "
        f"leeward_net_min_suction={p_l_min_suction:.2f} psf, "
        f"total_drag={total_drag:.2f} psf. "
        f"Cp_windward=+0.8, Cp_leeward={Cp_l:.2f} (L/B={L_over_B:.3f}). "
        f"SCOPE LIMITATIONS: (1) Tornado-prone region boundaries (§32.1.1 Fig 32.1-1) "
        f"are NOT checked — user must confirm the site is in the tornado-prone region "
        f"(generally east of 105°W longitude); "
        f"(2) §32.5 wind-speed maps are tabular/geographic — V_T_mph must be read from "
        f"Fig 32.5-1A (RC III) or Fig 32.5-1B (RC IV) by the engineer for the actual site; "
        f"(3) Roof pressures, parapets, and C&C tornado pressures (§32.9.3) not included; "
        f"(4) Tornado shelters (§32.3) and refuge rooms have additional requirements; "
        f"(5) Only enclosed / partially-enclosed buildings — open buildings not in §32 scope; "
        f"(6) RC I and RC II are exempt from tornado design per §32.1.1; "
        f"(7) compare against standard §26–27 wind pressures — governing case controls."
    )

    return TornadoLoadReport(
        velocity_pressure_q_psf=round(q_z, 4),
        Kz=round(Kz, 6),
        K_d_T=_KD_TORNADO,
        I_T=I_T,
        gcpi_internal=GCpi,
        mwfrs_walls_psf=mwfrs,
        Cp_windward=Cp_w,
        Cp_leeward=round(Cp_l, 4),
        L_over_B=round(L_over_B, 4),
        code_section=code_sections,
        honest_caveat=caveat,
    )
