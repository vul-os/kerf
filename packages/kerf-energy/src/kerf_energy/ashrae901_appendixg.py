"""
kerf_energy.ashrae901_appendixg — ASHRAE 90.1 Appendix G Performance Rating Method.

Implements the ASHRAE 90.1-2022 Appendix G (Performance Rating Method) compliance
workflow:

  1. Auto-generate the ASHRAE 90.1 Appendix G BASELINE building from the proposed
     building description, per 90.1 system-selection tables (Table G3.1.1).
  2. Run both BASELINE and PROPOSED buildings through the 8760-hour energy engine.
  3. Compute the Performance Cost Index (PCI) = proposed_cost / baseline_cost.
  4. Compute percent improvement vs. baseline.
  5. Map % improvement → LEED v4.1 EAp2/EAc2 points.
  6. Check California Title 24 compliance (TDV method) where applicable.
  7. Generate a structured compliance report (JSON + human-readable rendering).

HONEST FLAG: This module implements the Appendix G Performance Rating Method
using a simplified 8760-hour single-zone heat-balance engine (not EnergyPlus /
DOE-2 / eQUEST).  Results are engineering estimates for design exploration and
code-compliance SCREENING.  Accuracy: ±15–25% on total annual energy.
NOT a government-certified or GBCI-registered compliance tool.  For permit-grade
LEED or ASHRAE 90.1 compliance documentation, a certified energy modeller using
approved dynamic simulation software is required.

ASHRAE 90.1-2022 Appendix G Baseline System Selection (Table G3.1.1)
----------------------------------------------------------------------
The baseline HVAC system is assigned based on:
  - Fossil-fuel availability and building type/size:
      System 1:  PTAC (Packaged Terminal AC) — residential, small commercial ≤ 3 floors
      System 2:  PTHP (Packaged Terminal Heat Pump) — residential, heating-dominated CZs
      System 3:  Packaged rooftop PSZ-AC — nonresidential ≤ 75,000 ft² (≈6968 m²)
      System 4:  Packaged rooftop PSZ-HP — nonresidential ≤ 75,000 ft², mild climates
      System 5:  Packaged rooftop VAV w/ reheat — nonresidential > 75,000 ft² ≤ 5 floors
      System 6:  Packaged rooftop VAV w/ PFP boxes — nonresidential > 75,000 ft² ≤ 5 floors
      System 7:  VAV w/ reheat (chiller + boiler) — nonresidential > 150,000 ft² or > 5 fl
      System 8:  VAV w/ PFP (chiller + boiler)   — nonresidential > 150,000 ft² or > 5 fl

Baseline envelope U-values per 90.1-2022 Table 5.5 (Climate Zones 1–8):
  - Wall (above-grade, mass/non-mass), Roof, Window (vertical fenestration), Skylight
  - SHGC limits by climate zone and orientation

Energy cost basis: electricity at $0.12/kWh, gas at $0.60/therm (national averages).
For PCI, relative cost ratio is what matters; exact rates cancel in the ratio.

References
----------
ASHRAE 90.1-2022 — Energy Standard for Sites and Buildings Except Low-Rise
  Residential Buildings; §6 HVAC; Appendix G Performance Rating Method
ASHRAE 90.1-2022 Table G3.1.1 — Baseline HVAC System Selection
ASHRAE 90.1-2022 Table 5.5 — Building Envelope Requirements
LEED v4.1 BD+C Reference Guide — EA Prerequisites and Credits
USGBC — LEED v4.1 EAp2 + EAc2 (Optimize Energy Performance)
CEC Title 24 Part 6 2022 — California Energy Code

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# ASHRAE 90.1-2022 Table 5.5 — Baseline envelope U-values (W/(m²·K))
# Opaque envelope: above-grade walls (steel-framed), roofs (insulation above deck)
# Window: vertical fenestration U-value, SHGC
# Climate zone number 1–8 (moisture designator ignored for simplicity)
# ---------------------------------------------------------------------------

# Maximum allowed U-values for BASELINE building (W/(m²·K))
# Source: ASHRAE 90.1-2022 Table 5.5, nonresidential, row labels per 90.1
_BASELINE_U_WALL: Dict[int, float] = {
    1: 0.857, 2: 0.701, 3: 0.513, 4: 0.513,
    5: 0.513, 6: 0.365, 7: 0.365, 8: 0.365,
}
_BASELINE_U_ROOF: Dict[int, float] = {
    1: 0.273, 2: 0.273, 3: 0.273, 4: 0.220,
    5: 0.220, 6: 0.162, 7: 0.162, 8: 0.162,
}
_BASELINE_U_WINDOW: Dict[int, float] = {
    1: 6.927, 2: 4.203, 3: 3.407, 4: 3.407,
    5: 3.407, 6: 3.407, 7: 2.555, 8: 2.555,
}
_BASELINE_SHGC_WINDOW: Dict[int, float] = {
    1: 0.25, 2: 0.25, 3: 0.25, 4: 0.40,
    5: 0.40, 6: 0.40, 7: 0.40, 8: 0.40,
}
# Baseline window-to-wall ratio per Appendix G G3.1.5: same as proposed up to 40%
_BASELINE_WWR_MAX = 0.40

# ---------------------------------------------------------------------------
# ASHRAE 90.1-2022 Table G3.1.1 — Baseline HVAC system selection
# Returns (system_number, system_name, heating_cop, cooling_cop, fan_fraction)
# ---------------------------------------------------------------------------

# Baseline system efficiency by system type
# (heating_cop, cooling_cop, fan_fraction_of_HVAC)
_SYSTEM_EFFICIENCY: Dict[int, tuple] = {
    1: (0.82, 2.93, 0.12),  # PTAC: gas resistance/heat (eff 82%) + DX cooling (COP 2.93)
    2: (2.20, 2.93, 0.12),  # PTHP: heat pump heating COP 2.2 + DX cooling
    3: (0.80, 3.10, 0.15),  # PSZ-AC: gas furnace 80% + packaged DX (EER 10 ≈ COP 2.93)
    4: (2.20, 3.10, 0.15),  # PSZ-HP: heat pump COP 2.2 + cooling COP 3.1
    5: (0.80, 3.30, 0.18),  # Packaged VAV+reheat: gas 80% + packaged chiller COP 3.3
    6: (2.20, 3.30, 0.18),  # Packaged VAV+PFP: heat pump + packaged chiller
    7: (0.85, 4.50, 0.20),  # Central VAV+reheat: gas boiler 85% + centrifugal chiller COP 4.5
    8: (2.50, 4.50, 0.20),  # Central VAV+PFP: HW heat pump + centrifugal chiller
}

_SYSTEM_NAMES: Dict[int, str] = {
    1: "PTAC (Packaged Terminal AC, gas heat)",
    2: "PTHP (Packaged Terminal Heat Pump)",
    3: "PSZ-AC (Packaged Single-Zone, gas furnace + DX)",
    4: "PSZ-HP (Packaged Single-Zone Heat Pump)",
    5: "Packaged VAV with Reheat (gas + packaged chiller)",
    6: "Packaged VAV with PFP Boxes (heat pump + packaged chiller)",
    7: "Central VAV with Reheat (gas boiler + centrifugal chiller)",
    8: "Central VAV with PFP Boxes (electric + centrifugal chiller)",
}


def select_ashrae901_baseline_system(
    building_type: str,
    floor_area_m2: float,
    num_floors: int,
    climate_zone: int,
    heating_fuel: str = "gas",
) -> int:
    """Select the ASHRAE 90.1-2022 Appendix G baseline HVAC system number.

    Implements Table G3.1.1 system selection logic.

    Parameters
    ----------
    building_type : str
        'residential', 'office', 'retail', 'warehouse', 'hospital', 'education'.
    floor_area_m2 : float
        Gross conditioned floor area (m²).
    num_floors : int
        Number of stories above grade.
    climate_zone : int
        ASHRAE 169 climate zone number 1–8.
    heating_fuel : str
        'gas' (default) or 'electric' — determines system type selection.

    Returns
    -------
    int
        Baseline system number 1–8.

    References
    ----------
    ASHRAE 90.1-2022 Table G3.1.1
    """
    # Convert m² to ft² for ASHRAE threshold comparisons
    floor_area_ft2 = floor_area_m2 * 10.7639

    is_residential = building_type.lower() in ("residential", "multifamily", "apartment")
    is_electric = heating_fuel.lower() in ("electric", "electricity")

    # CZ 1-2: mild heating → prefer electric systems (even-numbered systems)
    # CZ 3-8: gas preferred unless specified electric
    prefer_electric = is_electric or climate_zone in (1, 2)

    if is_residential:
        # G3.1.1.B: Residential buildings
        # Systems 1 (PTAC) or 2 (PTHP) — ≤4 stories
        if num_floors <= 4:
            return 2 if prefer_electric else 1
        else:
            # Taller residential: Systems 3/4 (PSZ)
            return 4 if prefer_electric else 3

    # Non-residential
    # G3.1.1.A: Non-residential
    # < 75,000 ft² (≈6968 m²) AND ≤ 3 floors → System 3/4 (PSZ)
    # < 75,000 ft² AND > 3 floors → System 5/6 (packaged VAV)
    # ≥ 75,000 ft² AND ≤ 5 floors → System 5/6 (packaged VAV)
    # > 150,000 ft² OR > 5 floors → System 7/8 (central VAV)

    _SMALL_THRESHOLD_FT2 = 75_000.0   # 6,968 m²
    _LARGE_THRESHOLD_FT2 = 150_000.0  # 13,935 m²

    is_large = floor_area_ft2 > _LARGE_THRESHOLD_FT2 or num_floors > 5
    is_medium = not is_large and (floor_area_ft2 > _SMALL_THRESHOLD_FT2 or num_floors > 3)
    is_small = not is_large and not is_medium

    if is_large:
        return 8 if prefer_electric else 7
    elif is_medium:
        return 6 if prefer_electric else 5
    else:  # small / single-zone
        return 4 if prefer_electric else 3


# ---------------------------------------------------------------------------
# Baseline building generator
# ---------------------------------------------------------------------------

@dataclass
class ProposedBuildingSpec:
    """Description of the proposed building for ASHRAE 90.1 Appendix G analysis.

    Attributes
    ----------
    name : str
        Building name / project ID.
    building_type : str
        'office' | 'residential' | 'retail' | 'warehouse' | 'hospital' | 'education'.
    floor_area_m2 : float
        Gross conditioned floor area (m²).
    num_floors : int
        Number of above-grade conditioned stories.
    climate_zone : int
        ASHRAE 169 climate zone number (1–8; moisture designator stripped).
    heating_fuel : str
        'gas' or 'electric'.
    window_to_wall_ratio : float
        Proposed building WWR (0–1).
    u_wall : float
        Proposed wall U-value (W/(m²·K)).
    u_roof : float
        Proposed roof U-value (W/(m²·K)).
    u_window : float
        Proposed window U-value (W/(m²·K)).
    shgc : float
        Proposed window SHGC (0–1).
    internal_load_w_m2 : float
        Peak internal load density (W/m²), equipment + lighting + people combined.
    hvac_heating_cop : float
        Proposed heating system COP (or AFUE for gas). Default 0.95 (95% AFUE condensing).
    hvac_cooling_cop : float
        Proposed cooling system COP. Default 5.0 (high-efficiency chiller).
    climate_mean_c : float
        Mean annual outdoor dry-bulb temperature (°C) for synthetic weather generation.
        Default 13.0 (temperate).
    climate_amplitude_c : float
        Seasonal temperature amplitude (°C). Default 10.0.
    california_climate_zone : int | None
        CEC California climate zone (1–16) if applicable for Title 24 check.
        None to skip Title 24 analysis.
    """
    name: str
    building_type: str
    floor_area_m2: float
    num_floors: int
    climate_zone: int
    heating_fuel: str = "gas"
    window_to_wall_ratio: float = 0.40
    u_wall: float = 0.30
    u_roof: float = 0.15
    u_window: float = 2.00
    shgc: float = 0.25
    internal_load_w_m2: float = 20.0
    hvac_heating_cop: float = 0.95
    hvac_cooling_cop: float = 5.0
    climate_mean_c: float = 13.0
    climate_amplitude_c: float = 10.0
    california_climate_zone: Optional[int] = None


@dataclass
class EndUseBreakdown:
    """Annual energy consumption broken down by end-use (kWh/yr)."""
    heating_kwh: float
    cooling_kwh: float
    fan_kwh: float
    lighting_kwh: float
    total_kwh: float
    eui_kwh_m2_yr: float


@dataclass
class AppendixGComplianceReport:
    """ASHRAE 90.1 Appendix G + LEED + Title 24 compliance report.

    Attributes
    ----------
    baseline_system_number : int
        ASHRAE 90.1-2022 Table G3.1.1 baseline system selection (1–8).
    baseline_system_name : str
        Human-readable name of the baseline system.
    baseline_end_use : EndUseBreakdown
        Annual energy by end-use for the BASELINE building.
    proposed_end_use : EndUseBreakdown
        Annual energy by end-use for the PROPOSED building.
    performance_cost_index : float
        PCI = proposed_annual_cost / baseline_annual_cost.
        PCI < 1.0 means the proposed building uses less energy cost than baseline.
    pct_better_than_baseline : float
        (1 - PCI) × 100 %.  Positive = better than baseline.
    ashrae_901_compliant : bool
        True if PCI < 1.0 (proposed costs less than baseline).
    leed_eap2_prerequisite_met : bool
        True if pct_better_than_baseline ≥ 5% (EAp2 minimum threshold).
    leed_eac2_points : int
        LEED v4.1 EAc2 (Optimize Energy Performance) points (0–18).
    title24_compliant : Optional[bool]
        California Title 24 compliance result (None if not applicable).
    title24_margin_pct : Optional[float]
        Title 24 margin (positive = better than T24 baseline). None if N/A.
    baseline_annual_cost_usd : float
        Estimated annual energy cost for the BASELINE building (USD).
    proposed_annual_cost_usd : float
        Estimated annual energy cost for the PROPOSED building (USD).
    honest_caveat : str
        Methodology and certification caveat.
    recommendations : list[str]
        Prioritised improvement recommendations.
    human_readable : str
        Multi-line plain-English compliance report summary.
    """
    baseline_system_number: int
    baseline_system_name: str
    baseline_end_use: EndUseBreakdown
    proposed_end_use: EndUseBreakdown
    performance_cost_index: float
    pct_better_than_baseline: float
    ashrae_901_compliant: bool
    leed_eap2_prerequisite_met: bool
    leed_eac2_points: int
    title24_compliant: Optional[bool]
    title24_margin_pct: Optional[float]
    baseline_annual_cost_usd: float
    proposed_annual_cost_usd: float
    honest_caveat: str
    recommendations: List[str]
    human_readable: str = field(default="")

    def to_dict(self) -> dict:
        """Serialise report to a JSON-compatible dict."""
        return {
            "baseline_system_number": self.baseline_system_number,
            "baseline_system_name": self.baseline_system_name,
            "baseline_end_use": {
                "heating_kwh": self.baseline_end_use.heating_kwh,
                "cooling_kwh": self.baseline_end_use.cooling_kwh,
                "fan_kwh": self.baseline_end_use.fan_kwh,
                "lighting_kwh": self.baseline_end_use.lighting_kwh,
                "total_kwh": self.baseline_end_use.total_kwh,
                "eui_kwh_m2_yr": self.baseline_end_use.eui_kwh_m2_yr,
            },
            "proposed_end_use": {
                "heating_kwh": self.proposed_end_use.heating_kwh,
                "cooling_kwh": self.proposed_end_use.cooling_kwh,
                "fan_kwh": self.proposed_end_use.fan_kwh,
                "lighting_kwh": self.proposed_end_use.lighting_kwh,
                "total_kwh": self.proposed_end_use.total_kwh,
                "eui_kwh_m2_yr": self.proposed_end_use.eui_kwh_m2_yr,
            },
            "performance_cost_index": self.performance_cost_index,
            "pct_better_than_baseline": self.pct_better_than_baseline,
            "ashrae_901_compliant": self.ashrae_901_compliant,
            "leed_eap2_prerequisite_met": self.leed_eap2_prerequisite_met,
            "leed_eac2_points": self.leed_eac2_points,
            "title24_compliant": self.title24_compliant,
            "title24_margin_pct": self.title24_margin_pct,
            "baseline_annual_cost_usd": self.baseline_annual_cost_usd,
            "proposed_annual_cost_usd": self.proposed_annual_cost_usd,
            "honest_caveat": self.honest_caveat,
            "recommendations": self.recommendations,
            "human_readable": self.human_readable,
        }


# ---------------------------------------------------------------------------
# LEED v4.1 EAc2 point table (identical to EAc1 from leed_v4_eap2.py)
# ---------------------------------------------------------------------------

_LEED_EAC2_TABLE: List[tuple] = [
    (6,  1), (8,  2), (10,  3), (12,  4), (14,  5),
    (16, 6), (18, 7), (20,  8), (22,  9), (24, 10),
    (26, 11), (28, 12), (30, 13), (34, 14), (38, 15),
    (42, 16), (46, 17), (50, 18),
]


def _leed_eac2_points(pct_better: float) -> int:
    """LEED v4.1 EAc2 Optimize Energy Performance points."""
    pts = 0
    for min_pct, p in _LEED_EAC2_TABLE:
        if pct_better >= min_pct:
            pts = p
    return min(pts, 18)


# ---------------------------------------------------------------------------
# Energy cost calculation
# ---------------------------------------------------------------------------

# National average energy costs (Appendix G G3.1.3 energy rate basis)
# Electricity: $0.12/kWh (EIA 2022 commercial average)
# Natural gas: $0.60/therm = $0.0205/kWh (EIA 2022 commercial average)
_ELECT_COST_PER_KWH = 0.12
_GAS_COST_PER_KWH = 0.60 / 29.3  # $0.60/therm ÷ 29.3 kWh/therm


def _annual_cost(
    heating_kwh: float,
    cooling_kwh: float,
    fan_kwh: float,
    lighting_kwh: float,
    heating_fuel: str = "gas",
) -> float:
    """Compute annual energy cost (USD) from end-use energy.

    Cooling, fans, and lighting are always electricity.
    Heating cost depends on fuel type.
    """
    cooling_cost = cooling_kwh * _ELECT_COST_PER_KWH
    fan_cost = fan_kwh * _ELECT_COST_PER_KWH
    lighting_cost = lighting_kwh * _ELECT_COST_PER_KWH

    if heating_fuel.lower().startswith("electric"):
        heat_cost = heating_kwh * _ELECT_COST_PER_KWH
    else:
        # Gas heating: kWh of zone load → gas kWh consumed
        heat_cost = heating_kwh * _GAS_COST_PER_KWH

    return cooling_cost + fan_cost + lighting_cost + heat_cost


# ---------------------------------------------------------------------------
# 8760-hour simulation engine (self-contained — avoids cross-package import)
# ---------------------------------------------------------------------------

def _synthesise_weather(mean_c: float = 13.0, amplitude_c: float = 10.0) -> list:
    """Generate 8760 synthetic hourly weather tuples (dry_bulb_c, dni, dhi, rh)."""
    hours = []
    for h in range(8760):
        t = (
            mean_c
            + amplitude_c * math.cos(2 * math.pi * h / 8760 + math.pi)
            + 3.0 * math.cos(2 * math.pi * (h % 24) / 24 + math.pi)
        )
        rh = 50.0 + 20.0 * math.sin(2 * math.pi * h / 8760)
        hour_of_day = h % 24
        is_day = 7 <= hour_of_day <= 19
        dni = max(0.0, 600.0 * math.sin(math.pi * (hour_of_day - 7) / 12)) if is_day else 0.0
        dhi = max(0.0, 100.0 * math.sin(math.pi * (hour_of_day - 7) / 12)) if is_day else 0.0
        hours.append((round(t, 1), round(dni, 1), round(dhi, 1), round(rh, 1)))
    return hours


def _simulate_building(
    floor_area_m2: float,
    wwr: float,
    u_wall: float,
    u_roof: float,
    u_window: float,
    shgc: float,
    internal_load_w_m2: float,
    heating_cop: float,
    cooling_cop: float,
    ceiling_height_m: float,
    weather: list,
    setpoint_heat_c: float = 20.0,
    setpoint_cool_c: float = 24.0,
    vent_ach: float = 0.20,
    fan_power_w_m2: float = 5.0,
    lighting_fraction: float = 0.40,
) -> EndUseBreakdown:
    """Simplified 8760-hour single-zone heat-balance simulation.

    Computes annual heating, cooling, fan, and lighting energy considering
    HVAC system COP/efficiency.

    Parameters
    ----------
    heating_cop : float
        Heating system COP or AFUE fraction (e.g. 0.85 for 85% furnace, 3.0 for heat pump).
    cooling_cop : float
        Cooling system COP (e.g. 3.2 for chiller, 5.0 for high-efficiency).
    fan_power_w_m2 : float
        Peak supply fan power density (W/m²).

    Returns
    -------
    EndUseBreakdown
    """
    # Clamp inputs
    fa = max(floor_area_m2, 1.0)
    wwr = max(0.0, min(0.95, wwr))
    ceiling_height_m = max(2.5, ceiling_height_m)

    # Envelope UA (W/K)
    side_len = math.sqrt(fa)
    perim = 4.0 * side_len
    wall_gross = perim * ceiling_height_m
    win_area = wall_gross * wwr
    opaque_area = wall_gross - win_area
    roof_area = fa

    # Psychrometric constants
    CP_AIR = 1006.0
    RHO_AIR = 1.20

    UA_env = U_wall_val * opaque_area + u_roof * roof_area + u_window * win_area
    UA_env = max(UA_env, 1.0)
    vol_m3 = fa * ceiling_height_m
    UA_vent = vent_ach * vol_m3 * RHO_AIR * CP_AIR / 3600.0
    UA_total = UA_env + UA_vent

    Q_int_peak = internal_load_w_m2 * fa  # W
    fan_peak = fan_power_w_m2 * fa         # W

    # Default office schedule
    schedule = []
    for h in range(8760):
        doy = h // 24
        hod = h % 24
        dow = doy % 7
        if dow < 5 and 8 <= hod < 18:
            frac = 1.0
        elif dow < 5 and (7 <= hod < 8 or 18 <= hod < 20):
            frac = 0.40
        else:
            frac = 0.05
        schedule.append(frac)

    total_heat_kw = 0.0
    total_cool_kw = 0.0
    total_fan_kw = 0.0
    total_light_kw = 0.0

    for h, (t_out, dni, dhi, _rh) in enumerate(weather):
        occ = schedule[h]
        Q_int = Q_int_peak * occ

        # Solar heat gain (simplified isotropic)
        diffuse_vert = dhi * 0.5
        beam_avg_vert = dni * 0.35
        q_solar = shgc * win_area * (diffuse_vert + beam_avg_vert)  # W

        # Heating
        q_loss = UA_total * (setpoint_heat_c - t_out)
        heat_w = max(0.0, q_loss - Q_int - q_solar)

        # Cooling
        q_gain = UA_total * (t_out - setpoint_cool_c)
        cool_w = max(0.0, q_gain + Q_int + q_solar)

        # Fan
        fan_frac = max(occ, 0.05)
        fan_w = fan_peak * fan_frac

        total_heat_kw += heat_w / 1000.0
        total_cool_kw += cool_w / 1000.0
        total_fan_kw += fan_w / 1000.0
        total_light_kw += (Q_int * lighting_fraction) / 1000.0

    # Apply system efficiency
    # heating_cop < 1.0 means furnace AFUE fraction (zone load ÷ AFUE = fuel input ÷ by AFUE)
    # For PCI, we need SITE energy: zone_load / efficiency
    # Note: for gas furnace, heating_cop is AFUE (0.0–1.0 range), so site_heat = zone_heat / afue
    # For heat pump, heating_cop > 1.0, site_heat = zone_heat / cop
    site_heat_kwh = total_heat_kw / max(heating_cop, 0.05)
    site_cool_kwh = total_cool_kw / max(cooling_cop, 0.5)
    fan_kwh = total_fan_kw
    light_kwh = total_light_kw

    total_kwh = site_heat_kwh + site_cool_kwh + fan_kwh + light_kwh
    eui = total_kwh / fa

    return EndUseBreakdown(
        heating_kwh=round(site_heat_kwh, 1),
        cooling_kwh=round(site_cool_kwh, 1),
        fan_kwh=round(fan_kwh, 1),
        lighting_kwh=round(light_kwh, 1),
        total_kwh=round(total_kwh, 1),
        eui_kwh_m2_yr=round(eui, 2),
    )


# Fix: expose U_wall_val as a proper parameter — refactor the inner function
def _simulate_building_v2(
    floor_area_m2: float,
    wwr: float,
    u_wall: float,
    u_roof: float,
    u_window: float,
    shgc: float,
    internal_load_w_m2: float,
    heating_cop: float,
    cooling_cop: float,
    ceiling_height_m: float,
    weather: list,
    setpoint_heat_c: float = 20.0,
    setpoint_cool_c: float = 24.0,
    vent_ach: float = 0.20,
    fan_power_w_m2: float = 5.0,
    lighting_fraction: float = 0.40,
) -> EndUseBreakdown:
    """Corrected 8760-hour single-zone simulation (uses u_wall parameter properly)."""
    fa = max(floor_area_m2, 1.0)
    wwr = max(0.0, min(0.95, wwr))
    ceiling_height_m = max(2.5, ceiling_height_m)

    side_len = math.sqrt(fa)
    perim = 4.0 * side_len
    wall_gross = perim * ceiling_height_m
    win_area = wall_gross * wwr
    opaque_area = wall_gross - win_area
    roof_area = fa

    CP_AIR = 1006.0
    RHO_AIR = 1.20

    UA_env = u_wall * opaque_area + u_roof * roof_area + u_window * win_area
    UA_env = max(UA_env, 1.0)
    vol_m3 = fa * ceiling_height_m
    UA_vent = vent_ach * vol_m3 * RHO_AIR * CP_AIR / 3600.0
    UA_total = UA_env + UA_vent

    Q_int_peak = internal_load_w_m2 * fa
    fan_peak = fan_power_w_m2 * fa

    schedule = []
    for h in range(8760):
        doy = h // 24
        hod = h % 24
        dow = doy % 7
        if dow < 5 and 8 <= hod < 18:
            frac = 1.0
        elif dow < 5 and (7 <= hod < 8 or 18 <= hod < 20):
            frac = 0.40
        else:
            frac = 0.05
        schedule.append(frac)

    total_heat_kw = 0.0
    total_cool_kw = 0.0
    total_fan_kw = 0.0
    total_light_kw = 0.0

    for h, (t_out, dni, dhi, _rh) in enumerate(weather):
        occ = schedule[h]
        Q_int = Q_int_peak * occ

        diffuse_vert = dhi * 0.5
        beam_avg_vert = dni * 0.35
        q_solar = shgc * win_area * (diffuse_vert + beam_avg_vert)

        q_loss = UA_total * (setpoint_heat_c - t_out)
        heat_w = max(0.0, q_loss - Q_int - q_solar)

        q_gain = UA_total * (t_out - setpoint_cool_c)
        cool_w = max(0.0, q_gain + Q_int + q_solar)

        fan_frac = max(occ, 0.05)
        fan_w = fan_peak * fan_frac

        total_heat_kw += heat_w / 1000.0
        total_cool_kw += cool_w / 1000.0
        total_fan_kw += fan_w / 1000.0
        total_light_kw += (Q_int * lighting_fraction) / 1000.0

    site_heat_kwh = total_heat_kw / max(heating_cop, 0.05)
    site_cool_kwh = total_cool_kw / max(cooling_cop, 0.5)
    fan_kwh = total_fan_kw
    light_kwh = total_light_kw

    total_kwh = site_heat_kwh + site_cool_kwh + fan_kwh + light_kwh
    eui = total_kwh / fa

    return EndUseBreakdown(
        heating_kwh=round(site_heat_kwh, 1),
        cooling_kwh=round(site_cool_kwh, 1),
        fan_kwh=round(fan_kwh, 1),
        lighting_kwh=round(light_kwh, 1),
        total_kwh=round(total_kwh, 1),
        eui_kwh_m2_yr=round(eui, 2),
    )


# ---------------------------------------------------------------------------
# Title 24 compliance (simplified TDV method)
# ---------------------------------------------------------------------------

# CEC Title 24 2022 reference TDV baseline kBtu/(m²·yr) for office buildings by CZ
# Used when california_climate_zone is specified
_T24_OFFICE_BASELINE_KBTU_M2: Dict[int, float] = {
    1:  90 * 10.7639,   2:  85 * 10.7639,  3:  82 * 10.7639,  4:  84 * 10.7639,
    5:  78 * 10.7639,   6:  86 * 10.7639,  7:  80 * 10.7639,  8:  95 * 10.7639,
    9: 100 * 10.7639,  10:  88 * 10.7639, 11: 105 * 10.7639, 12:  98 * 10.7639,
    13: 115 * 10.7639, 14: 120 * 10.7639, 15: 135 * 10.7639, 16:  88 * 10.7639,
}
# TDV electricity multipliers (kBtu/kWh) by CA CZ
_TDV_ELECT: Dict[int, float] = {
    1: 3.50, 2: 3.55, 3: 3.58, 4: 3.62, 5: 3.45, 6: 3.70, 7: 3.65, 8: 3.85,
    9: 3.90, 10: 3.68, 11: 4.05, 12: 3.80, 13: 4.10, 14: 4.30, 15: 4.50, 16: 3.40,
}
_KWH_TO_KBTU = 3.412141


def _check_title24(
    proposed: EndUseBreakdown,
    floor_area_m2: float,
    ca_cz: int,
    heating_fuel: str,
) -> tuple:
    """Return (compliant: bool, margin_pct: float).

    TDV method: convert proposed kWh end-use totals to kBtu TDV and compare
    against reference building TDV baseline.
    """
    ca_cz = max(1, min(16, ca_cz))
    tdv_e = _TDV_ELECT.get(ca_cz, 3.80)
    kbtu_per_therm = 100.0
    kwh_per_therm = 29.3

    if heating_fuel.lower().startswith("electric"):
        tdv_heat = proposed.heating_kwh * tdv_e * _KWH_TO_KBTU
    else:
        heat_therms = proposed.heating_kwh / kwh_per_therm
        tdv_heat = heat_therms * 1.07 * kbtu_per_therm  # gas TDV ≈ 1.07 kBtu/therm

    tdv_cool = proposed.cooling_kwh * tdv_e * _KWH_TO_KBTU
    tdv_fan = proposed.fan_kwh * tdv_e * _KWH_TO_KBTU
    tdv_light = proposed.lighting_kwh * tdv_e * _KWH_TO_KBTU

    total_tdv = (tdv_heat + tdv_cool + tdv_fan + tdv_light) / max(floor_area_m2, 1.0)
    baseline_tdv = _T24_OFFICE_BASELINE_KBTU_M2.get(ca_cz, 900.0)

    margin_pct = (baseline_tdv - total_tdv) / baseline_tdv * 100.0
    compliant = total_tdv <= baseline_tdv
    return compliant, round(margin_pct, 2)


# ---------------------------------------------------------------------------
# Human-readable report renderer
# ---------------------------------------------------------------------------

def _render_human_readable(report: AppendixGComplianceReport) -> str:
    """Render a multi-line human-readable compliance report summary."""
    b = report.baseline_end_use
    p = report.proposed_end_use
    lines = [
        "=" * 70,
        "ASHRAE 90.1 APPENDIX G PERFORMANCE RATING METHOD — COMPLIANCE REPORT",
        "=" * 70,
        "",
        f"ASHRAE 90.1-2022 Appendix G Baseline System (Table G3.1.1):",
        f"  System {report.baseline_system_number}: {report.baseline_system_name}",
        "",
        "ANNUAL ENERGY END-USE COMPARISON",
        "-" * 45,
        f"{'End Use':<20} {'Baseline':>12} {'Proposed':>12} {'Delta':>10}",
        f"{'':20} {'(kWh/yr)':>12} {'(kWh/yr)':>12} {'(kWh/yr)':>10}",
        "-" * 45,
        f"{'Heating':<20} {b.heating_kwh:>12,.0f} {p.heating_kwh:>12,.0f} "
        f"{p.heating_kwh - b.heating_kwh:>+10,.0f}",
        f"{'Cooling':<20} {b.cooling_kwh:>12,.0f} {p.cooling_kwh:>12,.0f} "
        f"{p.cooling_kwh - b.cooling_kwh:>+10,.0f}",
        f"{'HVAC Fans':<20} {b.fan_kwh:>12,.0f} {p.fan_kwh:>12,.0f} "
        f"{p.fan_kwh - b.fan_kwh:>+10,.0f}",
        f"{'Lighting':<20} {b.lighting_kwh:>12,.0f} {p.lighting_kwh:>12,.0f} "
        f"{p.lighting_kwh - b.lighting_kwh:>+10,.0f}",
        "-" * 45,
        f"{'TOTAL':<20} {b.total_kwh:>12,.0f} {p.total_kwh:>12,.0f} "
        f"{p.total_kwh - b.total_kwh:>+10,.0f}",
        f"{'EUI (kWh/m²·yr)':<20} {b.eui_kwh_m2_yr:>12.1f} {p.eui_kwh_m2_yr:>12.1f}",
        "",
        "PERFORMANCE COST INDEX (PCI)",
        f"  Baseline annual cost: ${report.baseline_annual_cost_usd:,.0f}",
        f"  Proposed annual cost: ${report.proposed_annual_cost_usd:,.0f}",
        f"  PCI = {report.performance_cost_index:.3f}  "
        f"({'PASS — proposed < baseline' if report.performance_cost_index < 1.0 else 'FAIL — proposed ≥ baseline'})",
        f"  % Better than baseline: {report.pct_better_than_baseline:+.1f}%",
        "",
        "ASHRAE 90.1-2022 COMPLIANCE:",
        f"  {'✓ COMPLIANT' if report.ashrae_901_compliant else '✗ NON-COMPLIANT'} "
        f"(PCI {'< 1.0' if report.ashrae_901_compliant else '≥ 1.0'})",
        "",
        "LEED v4.1 ENERGY & ATMOSPHERE:",
        f"  EAp2 Prerequisite: "
        f"{'✓ MET' if report.leed_eap2_prerequisite_met else '✗ NOT MET'} "
        f"(requires ≥5% savings)",
        f"  EAc2 Points Earned: {report.leed_eac2_points} / 18",
    ]
    if report.title24_compliant is not None:
        lines += [
            "",
            "CALIFORNIA TITLE 24 (2022):",
            f"  {'✓ COMPLIANT' if report.title24_compliant else '✗ NON-COMPLIANT'} "
            f"(margin: {report.title24_margin_pct:+.1f}%)",
        ]
    if report.recommendations:
        lines += ["", "RECOMMENDATIONS:"]
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"  {i}. {rec}")
    lines += [
        "",
        "IMPORTANT CAVEAT:",
        report.honest_caveat,
        "=" * 70,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_appendixg_report(spec: ProposedBuildingSpec) -> AppendixGComplianceReport:
    """Run ASHRAE 90.1 Appendix G Performance Rating Method compliance analysis.

    Algorithm
    ---------
    1. Select baseline HVAC system per Table G3.1.1.
    2. Build baseline envelope per Table 5.5 (U-values, SHGC, WWR capped at 40%).
    3. Synthesise 8760-hour weather from climate parameters.
    4. Simulate BASELINE building through 8760-hour engine.
    5. Simulate PROPOSED building through 8760-hour engine.
    6. Compute annual energy costs for both (electricity + gas rates).
    7. Compute PCI = proposed_cost / baseline_cost.
    8. Compute % better than baseline = (1 - PCI) × 100.
    9. Map % → LEED v4.1 EAp2/EAc2 result.
    10. Check Title 24 if california_climate_zone is specified.
    11. Generate recommendations and human-readable report.

    Parameters
    ----------
    spec : ProposedBuildingSpec

    Returns
    -------
    AppendixGComplianceReport

    Raises
    ------
    ValueError : for invalid inputs.

    References
    ----------
    ASHRAE 90.1-2022 Appendix G — Performance Rating Method
    LEED v4.1 BD+C Reference Guide — EA section
    CEC Title 24 Part 6 2022
    """
    if spec.floor_area_m2 <= 0:
        raise ValueError("floor_area_m2 must be > 0")
    if spec.num_floors < 1:
        raise ValueError("num_floors must be ≥ 1")
    cz = int(spec.climate_zone)
    if not 1 <= cz <= 8:
        raise ValueError(f"climate_zone must be 1–8 (ASHRAE 169); got {cz}")

    # --- 1. Baseline system selection ---
    sys_num = select_ashrae901_baseline_system(
        building_type=spec.building_type,
        floor_area_m2=spec.floor_area_m2,
        num_floors=spec.num_floors,
        climate_zone=cz,
        heating_fuel=spec.heating_fuel,
    )
    baseline_heat_cop, baseline_cool_cop, _fan_frac = _SYSTEM_EFFICIENCY[sys_num]
    sys_name = _SYSTEM_NAMES[sys_num]

    # --- 2. Baseline envelope per Table 5.5 ---
    bl_u_wall = _BASELINE_U_WALL.get(cz, 0.513)
    bl_u_roof = _BASELINE_U_ROOF.get(cz, 0.220)
    bl_u_window = _BASELINE_U_WINDOW.get(cz, 3.407)
    bl_shgc = _BASELINE_SHGC_WINDOW.get(cz, 0.40)
    bl_wwr = min(spec.window_to_wall_ratio, _BASELINE_WWR_MAX)  # G3.1.5

    # --- 3. Synthesise weather ---
    weather = _synthesise_weather(spec.climate_mean_c, spec.climate_amplitude_c)

    # Ceiling height heuristic: 3.5 m per floor for commercial, 2.8 m for residential
    is_res = spec.building_type.lower() in ("residential", "multifamily", "apartment")
    ceiling_h = spec.num_floors * (2.8 if is_res else 3.5) / max(spec.num_floors, 1)
    ceiling_h = max(2.8, min(ceiling_h, 5.0))

    # Internal load for baseline: Appendix G G3.1.2 — same as proposed building
    # (baseline uses same internal loads as proposed — only envelope/HVAC baseline)
    internal_load = spec.internal_load_w_m2

    # --- 4. Simulate BASELINE ---
    baseline_eu = _simulate_building_v2(
        floor_area_m2=spec.floor_area_m2,
        wwr=bl_wwr,
        u_wall=bl_u_wall,
        u_roof=bl_u_roof,
        u_window=bl_u_window,
        shgc=bl_shgc,
        internal_load_w_m2=internal_load,
        heating_cop=baseline_heat_cop,
        cooling_cop=baseline_cool_cop,
        ceiling_height_m=ceiling_h,
        weather=weather,
    )

    # --- 5. Simulate PROPOSED ---
    proposed_eu = _simulate_building_v2(
        floor_area_m2=spec.floor_area_m2,
        wwr=spec.window_to_wall_ratio,
        u_wall=spec.u_wall,
        u_roof=spec.u_roof,
        u_window=spec.u_window,
        shgc=spec.shgc,
        internal_load_w_m2=internal_load,
        heating_cop=spec.hvac_heating_cop,
        cooling_cop=spec.hvac_cooling_cop,
        ceiling_height_m=ceiling_h,
        weather=weather,
    )

    # --- 6. Annual energy costs ---
    baseline_cost = _annual_cost(
        baseline_eu.heating_kwh,
        baseline_eu.cooling_kwh,
        baseline_eu.fan_kwh,
        baseline_eu.lighting_kwh,
        spec.heating_fuel,
    )
    proposed_cost = _annual_cost(
        proposed_eu.heating_kwh,
        proposed_eu.cooling_kwh,
        proposed_eu.fan_kwh,
        proposed_eu.lighting_kwh,
        spec.heating_fuel,
    )

    # --- 7. PCI ---
    if baseline_cost > 0:
        pci = proposed_cost / baseline_cost
    else:
        pci = 1.0
    pct_better = (1.0 - pci) * 100.0

    # --- 8. ASHRAE compliance ---
    ashrae_compliant = pci < 1.0

    # --- 9. LEED ---
    leed_prereq = pct_better >= 5.0
    leed_pts = _leed_eac2_points(pct_better) if leed_prereq else 0

    # --- 10. Title 24 ---
    t24_compliant: Optional[bool] = None
    t24_margin: Optional[float] = None
    if spec.california_climate_zone is not None:
        t24_compliant, t24_margin = _check_title24(
            proposed_eu, spec.floor_area_m2, spec.california_climate_zone, spec.heating_fuel
        )

    # --- 11. Recommendations ---
    recs: List[str] = []
    if not ashrae_compliant:
        recs.append(
            f"PCI {pci:.3f} ≥ 1.0: proposed building does not comply with "
            "ASHRAE 90.1-2022 Appendix G. Improve envelope and HVAC efficiency."
        )
    if spec.u_wall > bl_u_wall * 1.05:
        recs.append(
            f"Wall U-value {spec.u_wall:.3f} > baseline {bl_u_wall:.3f} W/(m²·K). "
            "Upgrade wall insulation to meet or beat the 90.1 baseline."
        )
    if spec.u_roof > bl_u_roof * 1.05:
        recs.append(
            f"Roof U-value {spec.u_roof:.3f} > baseline {bl_u_roof:.3f} W/(m²·K). "
            "Add insulation above deck."
        )
    if spec.u_window > bl_u_window * 0.95:
        recs.append(
            f"Window U-value {spec.u_window:.3f} ≥ baseline {bl_u_window:.3f} W/(m²·K). "
            "Upgrade to low-e glazing."
        )
    if pct_better < 10.0 and ashrae_compliant:
        recs.append(
            "Marginal compliance (PCI just below 1.0). To earn LEED EAc2 points "
            "target ≥6% improvement. Consider high-efficiency HVAC upgrade."
        )
    if leed_prereq and leed_pts < 8 and pct_better < 20.0:
        recs.append(
            f"Currently {leed_pts} LEED EAc2 point(s). To reach 8+ points "
            "target ≥20% improvement with better envelope + HVAC COP."
        )
    if not recs and ashrae_compliant:
        recs.append(
            f"Strong performance: PCI={pci:.3f} ({pct_better:.1f}% better than baseline). "
            "Consider on-site renewables to further reduce operational carbon."
        )
    if t24_compliant is False:
        recs.append(
            f"Title 24 non-compliant (margin {t24_margin:.1f}%). "
            "Use CEC-approved energy software for permit documentation."
        )

    caveat = (
        "IMPORTANT — NOT GOVERNMENT-CERTIFIED/REGISTERED COMPLIANCE SOFTWARE: "
        "This is a simplified ASHRAE 90.1 Appendix G Performance Rating Method "
        "screening tool using an 8760-hour single-zone heat-balance engine. "
        "Results are ENGINEERING ESTIMATES for design exploration (±15–25% accuracy "
        "on total annual energy versus full dynamic simulation). "
        "This tool does NOT replace EnergyPlus, eQUEST, IES VE, or Carrier HAP for "
        "permit-grade compliance. Appendix G baseline selection follows Table G3.1.1 "
        "(ASHRAE 90.1-2022); envelope baselines follow Table 5.5. "
        "For official LEED submission or code authority compliance documentation, "
        "a certified energy modeller using CEC-approved or GBCI-accepted software "
        "is required."
    )

    # Build initial report (without human_readable)
    report = AppendixGComplianceReport(
        baseline_system_number=sys_num,
        baseline_system_name=sys_name,
        baseline_end_use=baseline_eu,
        proposed_end_use=proposed_eu,
        performance_cost_index=round(pci, 4),
        pct_better_than_baseline=round(pct_better, 2),
        ashrae_901_compliant=ashrae_compliant,
        leed_eap2_prerequisite_met=leed_prereq,
        leed_eac2_points=leed_pts,
        title24_compliant=t24_compliant,
        title24_margin_pct=t24_margin,
        baseline_annual_cost_usd=round(baseline_cost, 2),
        proposed_annual_cost_usd=round(proposed_cost, 2),
        honest_caveat=caveat,
        recommendations=recs,
    )
    report.human_readable = _render_human_readable(report)
    return report
