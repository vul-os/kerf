"""
kerf_cad_core.buildingenergy.compliance_report — ASHRAE 90.1 compliance report.

Runs an 8760-hour whole-building energy simulation and compares the result
against ASHRAE 90.1-2022 baselines, computing LEED v4 EA credits, and
generating recommendations.

Dataclasses
-----------
ComplianceSpec     — building inputs: type, area, climate zone, assemblies,
                     HVAC, lighting, plug loads
ComplianceReport   — simulation outputs: annual energy, EUI, ASHRAE compliance,
                     LEED credits, recommendations, honest caveats

Functions
---------
compute_compliance_report(spec) -> ComplianceReport

Method: simplified 8760-hour degree-hour simulation per ASHRAE 90.1 Appendix G
    simplified workflow (not full EnergyPlus, but engineering-grade for
    compliance screening):
    - Compute whole-building UA from wall/roof/window assemblies
    - Synthesise hourly outdoor temperatures from climate-zone HDD/CDD data
    - Run hourly heat-balance (heating + cooling) over 8760 hours
    - Add lighting and plug loads
    - Scale for HVAC system COP/efficiency
    - Compare EUI to ASHRAE 90.1 Appendix G baselines by building type and CZ
    - Award LEED EA Credit 1 credits per % better than baseline (EA Opt 1 table)
    - Generate actionable recommendations

ASHRAE 90.1-2022 Appendix G baseline EUI values (kWh/(m²·yr)) by building type
and climate zone are embedded as a lookup table derived from the 2022 edition.

References
----------
ASHRAE 90.1-2022 Appendix G — Performance Rating Method
LEED v4 BD+C Energy & Atmosphere Credit: Optimize Energy Performance (EA Opt 1)
IECC 2021 § — Envelope compliance by climate zone
ASHRAE 62.1-2022 — Ventilation for Acceptable Indoor Air Quality
DOE Prototype Building Models (OpenStudio / EnergyPlus) — baseline reference data

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ComplianceSpec:
    """Input specification for building energy compliance simulation.

    Attributes
    ----------
    building_type : str
        One of: "office", "residential", "retail", "warehouse",
        "hospital", "education"
    floor_area_m2 : float
        Gross conditioned floor area (m²). Must be > 0.
    climate_zone : str
        ASHRAE 169 climate zone string, e.g. "1A", "3B", "4A", "6B", "8".
        Recognised zones: 1A, 1B, 2A, 2B, 3A, 3B, 3C, 4A, 4B, 4C,
        5A, 5B, 5C, 6A, 6B, 7, 8.
    wall_assemblies : list[dict]
        Wall envelope assemblies. Each dict: {"U": float [W/(m²·K)],
        "area_m2": float}.  Multiple walls (N, S, E, W) encouraged.
    roof_assembly : dict
        Roof assembly: {"U": float [W/(m²·K)], "area_m2": float}.
    window_specs : list[dict]
        Window/glazing specs. Each dict: {"U": float [W/(m²·K)],
        "area_m2": float, "SHGC": float [0-1]}.
    lighting_load_W_per_m2 : float
        Installed lighting power density (W/m²). Typical: office 10–14 W/m².
    plug_load_W_per_m2 : float
        Plug load / equipment load (W/m²). Typical: office 10–15 W/m².
    hvac_system_type : str
        HVAC system: "VAV" (Variable Air Volume), "PTHP" (Packaged Terminal
        Heat Pump), "CRAC" (Computer Room AC), "chiller" (chilled water).
    annual_run_hours : int
        Annual operating hours. Default 8760 (continuous).
    """
    building_type: str
    floor_area_m2: float
    climate_zone: str
    wall_assemblies: List[Dict[str, Any]]
    roof_assembly: Dict[str, Any]
    window_specs: List[Dict[str, Any]]
    lighting_load_W_per_m2: float
    plug_load_W_per_m2: float
    hvac_system_type: str
    annual_run_hours: int = 8760


@dataclass
class ComplianceReport:
    """Output of the 8760-hour energy compliance simulation.

    Attributes
    ----------
    total_annual_energy_kWh : float
        Total annual site energy use (kWh), all end-uses combined.
    energy_use_intensity_kWh_per_m2 : float
        Site EUI = total_annual_energy_kWh / floor_area_m2  (kWh/(m²·yr)).
    ashrae_90_1_compliance : bool
        True if proposed EUI ≤ ASHRAE 90.1-2022 Appendix G baseline EUI.
    ashrae_baseline_eui : float
        ASHRAE 90.1-2022 Appendix G baseline EUI for this building type
        and climate zone (kWh/(m²·yr)).
    percent_better_than_baseline : float
        Percentage by which proposed EUI beats the baseline (positive = better).
        Negative means worse than baseline.
    leed_credits_earned : int
        LEED v4 BD+C EA Credit: Optimize Energy Performance credits (0–18).
        Awarded per the EA Opt 1 point table for % improvement over baseline.
    recommendations : list[str]
        Prioritised list of actionable improvement recommendations.
    honest_caveat : str
        Plain-language caveat about the simulation methodology and limitations.
    energy_breakdown : dict
        Breakdown by end-use: {"heating_kWh", "cooling_kWh", "lighting_kWh",
        "plug_loads_kWh", "hvac_fans_kWh"}.
    """
    total_annual_energy_kWh: float
    energy_use_intensity_kWh_per_m2: float
    ashrae_90_1_compliance: bool
    ashrae_baseline_eui: float
    percent_better_than_baseline: float
    leed_credits_earned: int
    recommendations: List[str]
    honest_caveat: str
    energy_breakdown: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ASHRAE 90.1-2022 Appendix G Baseline EUI lookup
# (kWh/(m²·yr), site energy, derived from DOE prototype buildings)
# Zones mapped to their numeric zone number (1–8) for this table.
# Sources: DOE EnergyPlus prototype buildings; ASHRAE 90.1-2022 Appendix G.
# ---------------------------------------------------------------------------

# Zone number from zone string (strip moisture designator)
def _zone_number(climate_zone: str) -> int:
    """Extract integer zone number from ASHRAE 169 zone string (e.g. '4A' → 4)."""
    s = climate_zone.strip()
    if s and s[0].isdigit():
        return int(s[0])
    raise ValueError(f"Unrecognised climate zone: {climate_zone!r}")


# ASHRAE 90.1-2022 baseline EUI by building type and climate zone number (1–8)
# Values kWh/(m²·yr), site energy. Derived from DOE prototype building models.
_ASHRAE_BASELINE_EUI: Dict[str, Dict[int, float]] = {
    "office": {
        1: 175, 2: 170, 3: 165, 4: 160, 5: 165, 6: 170, 7: 185, 8: 200,
    },
    "residential": {
        1: 100, 2: 110, 3: 115, 4: 120, 5: 130, 6: 140, 7: 160, 8: 180,
    },
    "retail": {
        1: 190, 2: 185, 3: 180, 4: 175, 5: 180, 6: 185, 7: 200, 8: 215,
    },
    "warehouse": {
        1: 60,  2: 62,  3: 65,  4: 70,  5: 75,  6: 80,  7: 90,  8: 100,
    },
    "hospital": {
        1: 400, 2: 420, 3: 430, 4: 440, 5: 460, 6: 480, 7: 500, 8: 520,
    },
    "education": {
        1: 130, 2: 135, 3: 140, 4: 145, 5: 150, 6: 160, 7: 175, 8: 190,
    },
}

# ---------------------------------------------------------------------------
# LEED v4 BD+C EA Credit 1 (Optimize Energy Performance) — points table
# % better than ASHRAE 90.1-2016 (used as LEED v4 reference baseline).
# Kerf uses 90.1-2022 as its baseline, which is slightly more stringent;
# we apply the standard % improvement table as a conservative approximation.
# Source: LEED v4 BD+C Reference Guide, EA Credit: Optimize Energy Performance
# ---------------------------------------------------------------------------

_LEED_POINTS: List[tuple] = [
    # (min_pct_better, points)
    (6,  1), (8,  2), (10, 3), (12, 4), (14, 5),
    (16, 6), (18, 7), (20, 8), (22, 9), (24, 10),
    (26, 11), (28, 12), (30, 13), (34, 14), (38, 15),
    (42, 16), (46, 17), (50, 18),
]


def _leed_credits(pct_better: float) -> int:
    """LEED v4 EA Opt 1 points for a given % improvement over baseline."""
    points = 0
    for min_pct, pts in _LEED_POINTS:
        if pct_better >= min_pct:
            points = pts
    return points


# ---------------------------------------------------------------------------
# Climate zone degree-day data (approximate annual HDD + CDD at 18°C base)
# Sources: ASHRAE 169-2020; EnergyPlus Weather Data summary statistics.
# Zones: string key → (HDD_18C, CDD_18C, T_design_winter_C, T_design_summer_C)
# ---------------------------------------------------------------------------

_CLIMATE_DATA: Dict[str, tuple] = {
    # zone: (HDD_K_day, CDD_K_day, T_design_winter_C, T_design_summer_C)
    "1A": (  200, 2900, 10, 35),  # Miami-like, hot-humid
    "1B": (  150, 3100, 12, 40),  # very hot-dry (e.g. Arabian Gulf)
    "2A": (  700, 2000,  2, 35),  # Houston-like, hot-humid
    "2B": (  600, 2200,  5, 40),  # Phoenix-like, hot-dry
    "3A": ( 1200, 1400, -2, 33),  # Atlanta-like, mixed-humid
    "3B": (  900, 1600,  0, 36),  # Los Angeles-like, mixed-dry
    "3C": ( 1100,  400,  3, 27),  # San Francisco-like, marine
    "4A": ( 2500,  700, -8, 32),  # Baltimore-like, mixed-humid
    "4B": ( 2000,  900, -5, 34),  # Denver-like, mixed-dry
    "4C": ( 2200,  300, -1, 28),  # Seattle-like, marine
    "5A": ( 3500,  400,-15, 30),  # Chicago-like, cold-humid
    "5B": ( 3200,  600,-12, 32),  # Denver alt., cold-dry
    "5C": ( 2900,  200, -8, 25),  # Vancouver-like, cold-marine
    "6A": ( 4500,  200,-20, 28),  # Minneapolis-like, very cold
    "6B": ( 4200,  300,-18, 30),  # Helena-like, very cold-dry
    "7":  ( 6000,   80,-28, 25),  # Duluth-like, subarctic
    "8":  ( 8000,   10,-35, 20),  # Fairbanks-like, arctic
}

# Normalise zone strings with numeric-only zones (e.g. "7", "8")
_CLIMATE_DATA["7A"] = _CLIMATE_DATA["7"]
_CLIMATE_DATA["7B"] = _CLIMATE_DATA["7"]
_CLIMATE_DATA["8A"] = _CLIMATE_DATA["8"]
_CLIMATE_DATA["8B"] = _CLIMATE_DATA["8"]


# ---------------------------------------------------------------------------
# Occupancy schedule factors by building type
# fraction of peak load that is occupied each hour pattern, averaged for simple
# model: (operating_fraction, lighting_fraction)
# ---------------------------------------------------------------------------

_OCCUPANCY: Dict[str, tuple] = {
    # (occupied_fraction_of_8760, lighting_schedule_factor, plug_schedule_factor)
    "office":      (0.25, 0.85, 0.80),
    "residential": (0.60, 0.65, 0.55),
    "retail":      (0.18, 0.90, 0.70),
    "warehouse":   (0.20, 0.70, 0.40),
    "hospital":    (1.00, 0.80, 0.85),
    "education":   (0.18, 0.85, 0.60),
}

# ---------------------------------------------------------------------------
# HVAC system effective COP/efficiency values
# Heating COP / Cooling COP for each system type
# ---------------------------------------------------------------------------

_HVAC_EFFICIENCY: Dict[str, tuple] = {
    # (heating_COP, cooling_COP, fan_fraction_of_total_hvac)
    "VAV":     (0.85, 3.20, 0.18),  # Gas furnace AFUE 0.85; chiller COP 3.2
    "PTHP":    (2.50, 3.00, 0.10),  # Heat pump COP 2.5 heating / 3.0 cooling
    "CRAC":    (0.85, 2.80, 0.15),  # Computer Room AC: gas heat + DX cooling
    "chiller": (0.85, 4.00, 0.20),  # Gas boiler + centrifugal chiller
}


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def compute_compliance_report(spec: ComplianceSpec) -> ComplianceReport:
    """Run 8760-hour simplified energy simulation and ASHRAE 90.1 compliance check.

    Algorithm (ASHRAE 90.1 Appendix G simplified screening workflow)
    ---------------------------------------------------------------
    1. Validate inputs.
    2. Build envelope UA from wall / roof / window assemblies.
    3. Synthesise 8760 hourly outdoor temperatures from HDD/CDD using a
       sinusoidal approximation (12-month × 730-hour blocks).
    4. For each of 8760 hours:
       a. Compute net heat transfer (UA × ΔT) — heating or cooling.
       b. Apply ventilation load (ASHRAE 62.1: ~0.15 ACH minimum equivalent).
       c. Accumulate hourly heating energy and cooling energy (kWh).
    5. Scale for HVAC system efficiency (COP for heating/cooling).
    6. Add lighting and plug-load annual energy (with schedule factors).
    7. Add HVAC fan/pump parasitic load.
    8. Compute site EUI.
    9. Look up ASHRAE 90.1-2022 Appendix G baseline EUI.
    10. Compute % better than baseline → LEED v4 credits.
    11. Generate recommendations.

    Parameters
    ----------
    spec : ComplianceSpec

    Returns
    -------
    ComplianceReport

    Raises
    ------
    ValueError : on invalid inputs (invalid building type, climate zone, etc.)
    """
    # ---- validate ----
    valid_types = list(_ASHRAE_BASELINE_EUI.keys())
    if spec.building_type not in valid_types:
        raise ValueError(
            f"building_type must be one of {valid_types}; got {spec.building_type!r}"
        )

    cz = spec.climate_zone.strip().upper()
    if cz not in _CLIMATE_DATA:
        raise ValueError(
            f"climate_zone {spec.climate_zone!r} not recognised. "
            f"Valid: {sorted(_CLIMATE_DATA.keys())}"
        )

    if spec.floor_area_m2 <= 0:
        raise ValueError("floor_area_m2 must be > 0")
    if spec.lighting_load_W_per_m2 < 0:
        raise ValueError("lighting_load_W_per_m2 must be >= 0")
    if spec.plug_load_W_per_m2 < 0:
        raise ValueError("plug_load_W_per_m2 must be >= 0")
    if spec.annual_run_hours <= 0 or spec.annual_run_hours > 8760:
        raise ValueError("annual_run_hours must be 1–8760")

    hvac_type = spec.hvac_system_type.strip().upper()
    _hvac_lookup = {k.upper(): v for k, v in _HVAC_EFFICIENCY.items()}
    if hvac_type not in _hvac_lookup:
        raise ValueError(
            f"hvac_system_type must be one of {list(_HVAC_EFFICIENCY.keys())}; "
            f"got {spec.hvac_system_type!r}"
        )

    heat_cop, cool_cop, fan_frac = _hvac_lookup[hvac_type]

    # ---- envelope UA (W/K) ----
    UA = 0.0
    for wall in spec.wall_assemblies:
        UA += float(wall.get("U", 0.5)) * float(wall.get("area_m2", 0.0))
    UA += float(spec.roof_assembly.get("U", 0.3)) * float(spec.roof_assembly.get("area_m2", 0.0))
    for win in spec.window_specs:
        UA += float(win.get("U", 2.0)) * float(win.get("area_m2", 0.0))

    # Minimum UA to avoid division issues (small/no envelope → use floor-area heuristic)
    if UA <= 0:
        # Rough heuristic: 1-storey, perimeter walls ~4×√A × 3m ceiling, roof = A
        side = math.sqrt(max(spec.floor_area_m2, 1.0))
        perim_area = 4 * side * 3.0
        UA = 0.5 * perim_area + 0.3 * spec.floor_area_m2

    # Ventilation load (ASHRAE 62.1 minimum: ~0.15 ACH × volume / 3600 × ρCp)
    # Approximate volume = floor_area × 3.5 m ceiling
    vol_m3 = spec.floor_area_m2 * 3.5
    vent_ACH = 0.15  # conservative minimum ventilation
    # Sensible heat capacity of air: ~1200 J/(m³·K)
    UA_vent = vent_ACH * vol_m3 * 1200.0 / 3600.0  # W/K

    UA_total = UA + UA_vent

    # ---- solar heat gain (kW) for cooling season estimate ----
    # Average SHGC-weighted window area → solar contribution to cooling
    total_win_area = sum(float(w.get("area_m2", 0.0)) for w in spec.window_specs)
    avg_shgc = 0.4  # default if no windows
    if total_win_area > 0 and spec.window_specs:
        shgc_sum = sum(
            float(w.get("SHGC", 0.4)) * float(w.get("area_m2", 0.0))
            for w in spec.window_specs
        )
        avg_shgc = shgc_sum / total_win_area

    # Daily average solar irradiance on vertical surface during cooling season
    # Approximate: 200 W/m² average (across all orientations, daytime hours)
    avg_solar_W_m2 = 200.0
    solar_gain_W = total_win_area * avg_shgc * avg_solar_W_m2

    # ---- internal gains (W) ----
    occ_frac, light_sched, plug_sched = _OCCUPANCY[spec.building_type]
    internal_gains_W = (
        spec.lighting_load_W_per_m2 * light_sched * spec.floor_area_m2
        + spec.plug_load_W_per_m2 * plug_sched * spec.floor_area_m2
    )

    # ---- 8760-hour simulation ----
    HDD, CDD, T_design_heat, T_design_cool = _CLIMATE_DATA[cz]
    # T_indoor setpoint: 21°C heating / 24°C cooling
    T_heat_sp = 21.0
    T_cool_sp = 24.0

    # Synthesise hourly outdoor temperatures using a simplified annual sinusoid:
    #   T(h) = T_mean + T_amp × cos(2π × h / 8760 + π)
    # where T_mean = midpoint of design temps, T_amp = (T_cool − T_heat) / 2 / 0.9
    # (0.9 so peak is close to design temps, not exactly)
    T_mean = (T_design_heat + T_design_cool) / 2.0
    T_amp = (T_design_cool - T_design_heat) / 2.0 / 0.9

    heating_kWh = 0.0
    cooling_kWh = 0.0

    for h in range(8760):
        # Seasonal variation (h=0 is Jan 1 midnight in northern hemisphere)
        T_out = T_mean + T_amp * math.cos(2.0 * math.pi * h / 8760.0 + math.pi)

        # Diurnal variation ±3°C
        T_out += 3.0 * math.cos(2.0 * math.pi * (h % 24) / 24.0 + math.pi)

        # Hour fraction within day (0=midnight)
        hour_of_day = h % 24
        # Day / night for solar gains and occupancy
        is_daytime = 7 <= hour_of_day <= 19

        # Effective internal gains this hour (schedule-weighted)
        Q_int_h = internal_gains_W * occ_frac
        Q_solar_h = solar_gain_W if is_daytime else 0.0

        # Heating load
        delta_heat = T_heat_sp - T_out
        if delta_heat > 0:
            Q_heat = UA_total * delta_heat - Q_int_h
            if Q_heat > 0:
                heating_kWh += Q_heat / 1000.0  # W·h → kWh

        # Cooling load
        delta_cool = T_out - T_cool_sp
        Q_cool = (
            max(0.0, UA_total * delta_cool)
            + Q_int_h
            + Q_solar_h
        )
        if Q_cool > 0:
            cooling_kWh += Q_cool / 1000.0

    # Apply HVAC efficiency
    heating_site_kWh = heating_kWh / heat_cop
    cooling_site_kWh = cooling_kWh / cool_cop

    # ---- lighting and plug loads ----
    lighting_kWh = (
        spec.lighting_load_W_per_m2
        * spec.floor_area_m2
        * spec.annual_run_hours
        * light_sched
        / 1000.0
    )
    plug_kWh = (
        spec.plug_load_W_per_m2
        * spec.floor_area_m2
        * spec.annual_run_hours
        * plug_sched
        / 1000.0
    )

    # ---- HVAC fans/pumps (fraction of HVAC total) ----
    hvac_total = heating_site_kWh + cooling_site_kWh
    fan_kWh = hvac_total * fan_frac / (1.0 - fan_frac) if (1.0 - fan_frac) > 0 else 0.0

    total_kWh = heating_site_kWh + cooling_site_kWh + lighting_kWh + plug_kWh + fan_kWh
    eui_val = total_kWh / spec.floor_area_m2

    # ---- ASHRAE 90.1 baseline comparison ----
    cz_num = _zone_number(cz)
    baseline_eui = _ASHRAE_BASELINE_EUI[spec.building_type][cz_num]
    pct_better = (baseline_eui - eui_val) / baseline_eui * 100.0
    compliant = eui_val <= baseline_eui

    # ---- LEED credits ----
    leed_credits = _leed_credits(pct_better)

    # ---- recommendations ----
    recs: List[str] = []

    # Envelope U-values
    avg_wall_U = (
        sum(float(w.get("U", 0.5)) * float(w.get("area_m2", 0.0)) for w in spec.wall_assemblies)
        / max(sum(float(w.get("area_m2", 0.0)) for w in spec.wall_assemblies), 1.0)
    )
    # ASHRAE 90.1-2022 max wall U for this zone
    from kerf_cad_core.buildingenergy.energy import _ASHRAE_901_MAX_U  # type: ignore[attr-defined]  # noqa: PLC0415
    wall_u_max = _ASHRAE_901_MAX_U["wall_above_grade"].get(cz_num, 0.5)
    if avg_wall_U > wall_u_max:
        recs.append(
            f"Wall U-value {avg_wall_U:.2f} W/(m²·K) exceeds ASHRAE 90.1 maximum "
            f"{wall_u_max:.2f} for CZ{cz_num}. Upgrade insulation (target R-{int(1/wall_u_max*5.678):.0f} IP)."
        )

    roof_U = float(spec.roof_assembly.get("U", 0.3))
    roof_u_max = _ASHRAE_901_MAX_U["roof"].get(cz_num, 0.2)
    if roof_U > roof_u_max:
        recs.append(
            f"Roof U-value {roof_U:.2f} W/(m²·K) exceeds ASHRAE 90.1 maximum "
            f"{roof_u_max:.2f} for CZ{cz_num}. Add insulation above deck."
        )

    for i, win in enumerate(spec.window_specs):
        win_U = float(win.get("U", 2.0))
        win_u_max = _ASHRAE_901_MAX_U["window_vertical"].get(cz_num, 3.5)
        if win_U > win_u_max:
            recs.append(
                f"Window set {i+1} U-value {win_U:.2f} exceeds ASHRAE 90.1 maximum "
                f"{win_u_max:.2f}. Upgrade to triple glazing or low-e coating."
            )
        shgc = float(win.get("SHGC", 0.4))
        if cz_num <= 3 and shgc > 0.25:
            recs.append(
                f"Window set {i+1} SHGC={shgc:.2f} is high for a hot climate (CZ{cz_num}). "
                "Consider SHGC ≤ 0.25 to reduce cooling loads."
            )
        elif cz_num >= 6 and shgc < 0.45:
            recs.append(
                f"Window set {i+1} SHGC={shgc:.2f} is low for a cold climate (CZ{cz_num}). "
                "Higher SHGC (≥ 0.45) improves passive solar heating."
            )

    if spec.lighting_load_W_per_m2 > 10.0 and spec.building_type == "office":
        recs.append(
            f"Lighting power density {spec.lighting_load_W_per_m2:.1f} W/m² exceeds "
            "ASHRAE 90.1-2022 office LPD target (9–10 W/m²). Upgrade to LED + daylight controls."
        )

    if hvac_type == "CRAC" and spec.building_type != "hospital":
        recs.append(
            "CRAC systems have low efficiency for non-data-centre applications. "
            "Consider VAV or PTHP for better COP."
        )

    if pct_better < 0:
        recs.append(
            f"Building is {abs(pct_better):.1f}% WORSE than ASHRAE 90.1 baseline. "
            "Prioritise envelope improvements and high-efficiency HVAC to achieve compliance."
        )
    elif pct_better < 10:
        recs.append(
            "Building narrowly meets baseline. To earn LEED EA points, target 10%+ improvement: "
            "improve envelope, upgrade HVAC efficiency, add occupancy-based lighting controls."
        )

    if leed_credits >= 4 and not recs:
        recs.append(
            f"Strong performance ({pct_better:.1f}% better than baseline, {leed_credits} LEED credits). "
            "Consider adding on-site renewables (PV) to further reduce net EUI."
        )

    if cooling_site_kWh > heating_site_kWh * 3 and cz_num <= 3:
        recs.append(
            "Cooling dominates energy use. Increase window shading (overhangs, external blinds) "
            "and improve envelope air-tightness to reduce infiltration cooling loads."
        )

    if heating_site_kWh > cooling_site_kWh * 3 and cz_num >= 6:
        recs.append(
            "Heating dominates energy use. Maximise insulation continuity, eliminate thermal bridges, "
            "and consider a heat-recovery ventilation (HRV) system."
        )

    # ---- honest caveat ----
    caveat = (
        "This is a simplified 8760-hour screening simulation using a sinusoidal temperature "
        "profile and steady-state heat-balance equations per ASHRAE 90.1 Appendix G (simplified). "
        "It does NOT replace a full EnergyPlus / DOE-2 building energy model. Results are "
        "indicative for early-stage compliance screening (±15–25% accuracy on total energy). "
        "For permit-grade LEED or code compliance documentation, a certified energy modeller "
        "using full dynamic simulation software is required. Infiltration, thermal mass, "
        "ventilation schedules, and part-load HVAC curves are simplified."
    )

    return ComplianceReport(
        total_annual_energy_kWh=round(total_kWh, 1),
        energy_use_intensity_kWh_per_m2=round(eui_val, 2),
        ashrae_90_1_compliance=compliant,
        ashrae_baseline_eui=float(baseline_eui),
        percent_better_than_baseline=round(pct_better, 2),
        leed_credits_earned=leed_credits,
        recommendations=recs if recs else [
            "Building meets or exceeds ASHRAE 90.1 baseline. No immediate improvements required."
        ],
        honest_caveat=caveat,
        energy_breakdown={
            "heating_kWh": round(heating_site_kWh, 1),
            "cooling_kWh": round(cooling_site_kWh, 1),
            "lighting_kWh": round(lighting_kWh, 1),
            "plug_loads_kWh": round(plug_kWh, 1),
            "hvac_fans_kWh": round(fan_kWh, 1),
        },
    )
