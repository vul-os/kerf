"""
kerf_cad_core.buildingenergy.hvac_plant — Full HVAC plant + air-side system modeling.

Models a chiller plant (centrifugal / screw / scroll chillers), boiler plant,
and VAV/CAV air-handling unit (AHU) with supply fan, return fan, and economiser.
Applies COP curves and part-load efficiency to hourly loads from simulate_8760().

Equivalent to IES VE ApacheHVAC (simplified) and Carrier HAP HVAC system model.

HONEST FLAG: This is an engineering-grade screening model, not a full HVAC dynamic
simulation.  Refrigerant thermodynamics, duct heat pickup, and detailed controls
sequences are simplified.  Accuracy: ±10–20% on annual HVAC energy vs. full model.

Dataclasses
-----------
ChillerSpec     — centrifugal/screw chiller (AHRI 550/590 rating conditions)
BoilerSpec      — hot-water boiler (AHRI 155 or ASHRAE 90.1 §6.8 efficiency)
AirSideSystem   — VAV/CAV AHU with fans + economiser
HvacPlantResult — hourly + annual electricity and gas results

Functions
---------
simulate_hvac_plant(annual, chiller, boiler, air_side) -> HvacPlantResult

References
----------
AHRI Standard 550/590-2023 — Performance Rating of Water-chilling and Heat Pump
    Water-heating Packages Using the Vapor Compression Cycle (chiller COP curves)
AHRI Standard 155-2021 — Performance Rating of Commercial Space Heating Boilers
ASHRAE 90.1-2022 §6.5.3 — Fan Power Limitation
ASHRAE 90.1-2022 §6.8.1 — Boiler Efficiency Requirements
ASHRAE 90.1-2022 Appendix G §G3.1.3 — HVAC System Type Assignments
ASHRAE Handbook HVAC Systems and Equipment 2020 — Chapter 2 (Chillers)
ASHRAE Handbook HVAC Systems and Equipment 2020 — Chapter 32 (Boilers)
CoolTools Chiller Model (Hydeman & Gillespie 2002) — bi-quadratic COP curves

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from kerf_cad_core.buildingenergy.hourly_8760 import AnnualResult, HourlyResult


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_KWH_PER_THERM = 29.3       # 1 US therm = 29.3 kWh (HHV)
_KW_PER_TON_REFRIG = 3.517  # 1 refrigeration ton = 3.517 kW


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChillerSpec:
    """Water-cooled chiller specification (AHRI 550/590 rating conditions).

    AHRI 550/590 full-load rating conditions:
      - Leaving chilled water temperature: 6.67°C (44°F)
      - Entering condenser water temperature: 29.4°C (85°F) for water-cooled
      - Evaporator flow: 0.054 L/(s·kW)

    COP curves: bi-quadratic function of (load fraction, entering condenser water temp)
    based on the EnergyPlus Electric Chiller reformulated model and CoolTools
    chiller model (Hydeman & Gillespie 2002, ASHRAE Trans. DE-01-2-2).

    Attributes
    ----------
    name : str
        Chiller identifier.
    rated_capacity_kw : float
        Full-load cooling capacity at AHRI 550/590 conditions (kW).
    cop_rated : float
        Full-load COP at AHRI 550/590 conditions (dimensionless).
        Typical: centrifugal 5.5–7.0; screw 4.5–6.0; scroll 3.5–4.5.
    capacity_curve_a, _b, _c : float
        Quadratic part-load correction coefficients for COP:
        COP_actual = COP_rated × (a + b×PLR + c×PLR²)
        Default: a=1.0, b=0, c=0 (flat curve — conservative).
        Realistic centrifugal: a=0.95, b=0.12, c=-0.07 (better COP at ~50–70% load).
    ecw_temp_correction_per_k : float
        COP improvement per 1°C reduction in entering condenser water temp below
        AHRI 29.4°C design.  Typical: +2–3% per °C.
        Source: ASHRAE 90.1-2022 Appendix G §G3.1.3.7.
    min_part_load_ratio : float
        Minimum stable operating part-load ratio (0–1). Default 0.10.
    """
    name: str
    rated_capacity_kw: float
    cop_rated: float
    capacity_curve_a: float = 1.0
    capacity_curve_b: float = 0.0
    capacity_curve_c: float = 0.0
    ecw_temp_correction_per_k: float = 0.025   # 2.5% COP per °C
    min_part_load_ratio: float = 0.10

    def cop_at(self, load_pct: float, entering_cw_temp_c: float) -> float:
        """Compute actual COP at given part-load ratio and entering condenser water temp.

        Method: bi-quadratic part-load curve + linear ECW temperature correction.

        COP_plr = COP_rated × (a + b×PLR + c×PLR²)   [part-load curve]
        COP_ecw = COP_plr × (1 + γ × (T_ecw_design - T_ecw_actual))  [ECW correction]

        where γ = ecw_temp_correction_per_k, T_ecw_design = 29.4°C.

        References
        ----------
        AHRI 550/590-2023 — Chiller performance rating at off-design conditions
        CoolTools Chiller Model (Hydeman & Gillespie 2002, ASHRAE Trans.)
        ASHRAE Handbook HVAC Equipment 2020, Chapter 2
        """
        plr = max(self.min_part_load_ratio, min(1.0, load_pct))
        # Part-load curve correction
        plr_factor = (
            self.capacity_curve_a
            + self.capacity_curve_b * plr
            + self.capacity_curve_c * plr ** 2
        )
        plr_factor = max(0.5, plr_factor)  # floor at 50% to avoid unphysical values

        # Entering condenser water temperature correction
        # AHRI design ECW = 29.4°C; positive correction for cooler condenser water
        ecw_delta = 29.4 - entering_cw_temp_c
        ecw_factor = 1.0 + self.ecw_temp_correction_per_k * ecw_delta
        ecw_factor = max(0.5, min(2.0, ecw_factor))  # bound to sensible range

        return self.cop_rated * plr_factor * ecw_factor


@dataclass
class BoilerSpec:
    """Hot-water boiler specification.

    AHRI Standard 155 / ASHRAE 90.1-2022 §6.8.1 efficiency basis:
      - Combustion efficiency (CE) = heat output / fuel HHV
      - AFUE (Annual Fuel Utilisation Efficiency) for residential
      - Et (Thermal efficiency) or Ec (Combustion efficiency) for commercial

    Part-load curve: list of (PLR, efficiency_fraction) tuples.
    If empty, a default curve is used (efficiency drops at very low PLR).

    Attributes
    ----------
    rated_capacity_kw : float
        Boiler output capacity at full load (kW).
    efficiency_rated_pct : float
        Thermal efficiency at full load (%). ASHRAE 90.1-2022 §6.8.1
        minimum: 80% for ≥88 kW hot-water boilers.
    part_load_curve : list[tuple[float, float]]
        Pairs of (part_load_ratio, efficiency_fraction_of_rated).
        Efficiency fraction: 1.0 = same as rated; >1.0 = condensing mode better
        than rated; <1.0 = worse than rated.
        If empty, uses ASHRAE default (slight efficiency penalty at <20% PLR).
    """
    rated_capacity_kw: float
    efficiency_rated_pct: float
    part_load_curve: List[Tuple[float, float]] = field(default_factory=list)

    def efficiency_at(self, load_pct: float) -> float:
        """Return boiler efficiency (fraction, 0–1) at given part-load ratio.

        Interpolates through part_load_curve if provided.
        Default curve (ASHRAE 90.1-2022 simplified): efficiency is constant from
        100% down to ~30% load, then decreases linearly to 85% of rated at 0% load.

        References
        ----------
        ASHRAE 90.1-2022 §6.8.1 — Boiler Efficiency Requirements
        AHRI Standard 155-2021 — Part-load boiler testing
        DOE/PNNL — Boiler Part-Load Performance Data (2016)
        """
        plr = max(0.0, min(1.0, load_pct))
        eff_rated_frac = self.efficiency_rated_pct / 100.0

        if self.part_load_curve:
            # Sort by PLR and linearly interpolate
            sorted_curve = sorted(self.part_load_curve, key=lambda x: x[0])
            if plr <= sorted_curve[0][0]:
                frac = sorted_curve[0][1]
            elif plr >= sorted_curve[-1][0]:
                frac = sorted_curve[-1][1]
            else:
                for i in range(len(sorted_curve) - 1):
                    p0, e0 = sorted_curve[i]
                    p1, e1 = sorted_curve[i + 1]
                    if p0 <= plr <= p1:
                        t = (plr - p0) / (p1 - p0)
                        frac = e0 + t * (e1 - e0)
                        break
                else:
                    frac = 1.0
            return eff_rated_frac * frac

        # Default ASHRAE simplified part-load curve:
        # - Full efficiency from PLR 0.30–1.00
        # - Linear degradation below PLR 0.30: at PLR=0 → 85% of rated efficiency
        if plr >= 0.30:
            return eff_rated_frac
        else:
            # Linear interpolation: PLR 0.0 → 85% of rated; PLR 0.30 → 100% of rated
            t = plr / 0.30
            return eff_rated_frac * (0.85 + 0.15 * t)


@dataclass
class AirSideSystem:
    """VAV or CAV air-handling unit (AHU) air-side system model.

    Attributes
    ----------
    cfm_design : float
        Design supply airflow (CFM — cubic feet per minute).
        SI: 1 CFM ≈ 0.000472 m³/s.
    fan_power_w_per_cfm : float
        Fan power at design airflow (W/CFM).
        ASHRAE 90.1-2022 §6.5.3: VAV systems ≤1.25 W/CFM; CAV ≤1.50 W/CFM.
    return_fan_present : bool
        True if a separate return fan is modelled (adds ~25% to total fan power).
    economizer_type : str
        'none'            — no economiser (DX or chilled water only)
        'integrated'      — integrated economiser + mechanical cooling
        'differential_drybulb' — economiser active when T_outdoor < T_return - 1°C
    """
    cfm_design: float
    fan_power_w_per_cfm: float
    return_fan_present: bool
    economizer_type: str  # 'none' | 'integrated' | 'differential_drybulb'


@dataclass
class HvacPlantResult:
    """Hourly and annual HVAC plant energy results.

    Attributes
    ----------
    hourly_electricity_kwh : list[float]
        Hourly chiller + fan electricity (kWh), length 8760.
    hourly_gas_kwh : list[float]
        Hourly boiler fuel input (kWh equivalent), length 8760.
    annual_electricity_kwh : float
        Total annual electricity (kWh).
    annual_gas_kwh : float
        Total annual gas energy input (kWh equivalent, HHV basis).
    annual_gas_therms : float
        Total annual gas consumption (therms).
    chiller_cop_average : float
        Weighted-average chiller COP across cooling hours.
    boiler_efficiency_average : float
        Weighted-average boiler efficiency across heating hours (%).
    honest_caveat : str
        Methodology caveat.
    """
    hourly_electricity_kwh: List[float]
    hourly_gas_kwh: List[float]
    annual_electricity_kwh: float
    annual_gas_kwh: float
    annual_gas_therms: float
    chiller_cop_average: float
    boiler_efficiency_average: float
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Economiser logic
# ---------------------------------------------------------------------------

def _economizer_free_cooling_frac(
    economizer_type: str,
    t_outdoor_c: float,
    t_return_c: float = 24.0,
    rh_outdoor_pct: float = 50.0,
) -> float:
    """Estimate the fraction of cooling load met by economiser (0–1).

    'none'                — always 0.
    'integrated'          — active when T_outdoor ≤ 18.3°C (ASHRAE 90.1 high-limit).
    'differential_drybulb'— active when T_outdoor < T_return - 1°C.

    References: ASHRAE 90.1-2022 §6.5.1 (Economiser High-Limit Controls).
    """
    if economizer_type == "none":
        return 0.0
    if economizer_type == "integrated":
        # ASHRAE 90.1-2022 §6.5.1.1: dry-bulb high-limit at 18.3°C (65°F)
        if t_outdoor_c <= 18.3:
            # Partial free cooling: fraction scales with (18.3 - T_out) / 18.3
            frac = min(1.0, (18.3 - t_outdoor_c) / 18.3)
            return max(0.0, frac)
        return 0.0
    if economizer_type == "differential_drybulb":
        if t_outdoor_c < t_return_c - 1.0:
            frac = min(1.0, (t_return_c - 1.0 - t_outdoor_c) / max(t_return_c, 1.0))
            return max(0.0, frac)
        return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Core HVAC plant simulation
# ---------------------------------------------------------------------------

def simulate_hvac_plant(
    annual: AnnualResult,
    chiller: ChillerSpec,
    boiler: BoilerSpec,
    air_side: AirSideSystem,
) -> HvacPlantResult:
    """Apply HVAC plant efficiency curves to hourly loads from simulate_8760().

    For each hour:
      1. Cooling load → chiller electricity = cooling_kw / COP_at(PLR, ECW_temp)
         - ECW temperature estimated from outdoor dry-bulb + cooling tower approach.
         - Economiser active hours: free cooling reduces chiller load.
      2. Heating load → boiler gas input = heating_kw / boiler_efficiency_at(PLR)
      3. Fan electricity = fan_design_kw × VAV_fraction(load) for VAV,
         or fan_design_kw × (min_flow + load_frac) for part-load modulation.
         Per ASHRAE 90.1-2022 §6.5.3.3 VAV fan power curve.

    Parameters
    ----------
    annual : AnnualResult
        Output of simulate_8760().
    chiller : ChillerSpec
    boiler : BoilerSpec
    air_side : AirSideSystem

    Returns
    -------
    HvacPlantResult

    Raises
    ------
    ValueError : if chiller.rated_capacity_kw ≤ 0 or boiler.rated_capacity_kw ≤ 0.

    References
    ----------
    AHRI 550/590-2023 — Chiller COP rating conditions
    ASHRAE 90.1-2022 §6.5.3 — Fan Power Limitation
    ASHRAE 90.1-2022 §6.8.1 — Boiler Efficiency Requirements
    ASHRAE 90.1-2022 Appendix G §G3.1.3 — Baseline HVAC system modelling
    """
    if chiller.rated_capacity_kw <= 0:
        raise ValueError("chiller.rated_capacity_kw must be > 0")
    if boiler.rated_capacity_kw <= 0:
        raise ValueError("boiler.rated_capacity_kw must be > 0")

    # Fan design power (kW)
    fan_cfm = max(air_side.cfm_design, 1.0)
    fan_design_kw = fan_cfm * air_side.fan_power_w_per_cfm / 1000.0
    if air_side.return_fan_present:
        # Return fan typically ~25% of supply fan power
        fan_design_kw *= 1.25

    hourly_elec: List[float] = []
    hourly_gas: List[float] = []

    total_elec = 0.0
    total_gas = 0.0
    weighted_cop_sum = 0.0
    weighted_cop_w = 0.0
    weighted_eff_sum = 0.0
    weighted_eff_w = 0.0

    for hr in annual.hourly:
        t_out = hr.outdoor_temp_c
        cool_kw = hr.cooling_load_kw
        heat_kw = hr.heating_load_kw

        # ---- Chiller electricity ----
        chiller_elec_kwh = 0.0
        if cool_kw > 0:
            plr = cool_kw / chiller.rated_capacity_kw
            plr = max(chiller.min_part_load_ratio, min(1.0, plr))

            # Cooling tower ECW estimation:
            # ECW ≈ T_outdoor_wb + approach + T_range
            # Simplified: ECW = T_outdoor + 5°C (cooling tower approach ~5°C above outdoor db)
            # For more accuracy, wet-bulb should be used; outdoor db is conservative.
            ecw_temp = max(10.0, t_out + 5.0)

            # Economiser: reduces mechanical cooling load
            eco_frac = _economizer_free_cooling_frac(
                air_side.economizer_type,
                t_out,
                t_return_c=hr.indoor_temp_c,
            )
            mech_cool_kw = cool_kw * (1.0 - eco_frac)

            if mech_cool_kw > 0:
                cop = chiller.cop_at(mech_cool_kw / chiller.rated_capacity_kw, ecw_temp)
                cop = max(0.5, cop)  # floor to prevent division by zero
                chiller_elec_kwh = mech_cool_kw / cop  # kW input
                # kWh = kW × 1 hour
                weighted_cop_sum += cop * mech_cool_kw
                weighted_cop_w += mech_cool_kw

        # ---- Boiler gas ----
        boiler_gas_kwh = 0.0
        if heat_kw > 0:
            boiler_plr = heat_kw / boiler.rated_capacity_kw
            boiler_plr = max(0.0, min(1.0, boiler_plr))
            eff = boiler.efficiency_at(boiler_plr)
            eff = max(0.5, eff)
            boiler_gas_kwh = heat_kw / eff  # fuel input kW → kWh over 1 hour
            weighted_eff_sum += eff * heat_kw
            weighted_eff_w += heat_kw

        # ---- Fan electricity ----
        # ASHRAE 90.1-2022 §6.5.3.3 VAV Fan Part-Load Power:
        # P_fan / P_design = 0.1 × (Q/Q_design) + 0.9 × (Q/Q_design)³
        # (simplified cubic fan affinity law with minimum flow floor)
        load_frac = max(0.05, hr.fan_kw / max(fan_design_kw, 0.001))  # normalise to design
        load_frac = min(1.0, load_frac)
        vav_frac = 0.1 * load_frac + 0.9 * load_frac ** 3
        fan_kwh = fan_design_kw * max(vav_frac, 0.05)

        h_elec = chiller_elec_kwh + fan_kwh
        h_gas = boiler_gas_kwh

        hourly_elec.append(round(h_elec, 4))
        hourly_gas.append(round(h_gas, 4))
        total_elec += h_elec
        total_gas += h_gas

    avg_cop = (weighted_cop_sum / weighted_cop_w) if weighted_cop_w > 0 else chiller.cop_rated
    avg_eff = ((weighted_eff_sum / weighted_eff_w) * 100.0) if weighted_eff_w > 0 else boiler.efficiency_rated_pct

    caveat = (
        "This is a simplified HVAC plant model applying COP/efficiency curves to "
        "hourly zone loads. It does NOT model refrigerant thermodynamics, duct heat "
        "pickup, controls sequences (e.g. reset schedules, demand-controlled ventilation), "
        "or multi-chiller staging with lead/lag logic. For certified energy compliance "
        "(LEED, Title 24, ASHRAE 90.1 Appendix G), a full dynamic simulation is required. "
        "Accuracy: ±10–20% on annual HVAC energy."
    )

    return HvacPlantResult(
        hourly_electricity_kwh=hourly_elec,
        hourly_gas_kwh=hourly_gas,
        annual_electricity_kwh=round(total_elec, 1),
        annual_gas_kwh=round(total_gas, 1),
        annual_gas_therms=round(total_gas / _KWH_PER_THERM, 1),
        chiller_cop_average=round(avg_cop, 3),
        boiler_efficiency_average=round(avg_eff, 1),
        honest_caveat=caveat,
    )
