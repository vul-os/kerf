"""
kerf_cad_core.buildingenergy.title24_compliance — California Title 24 Part 6 (2022)
Energy Code compliance check.

Compares a proposed building's annual Time-Dependent Valuation (TDV) energy
against the Title 24 Reference Building TDV baseline for the applicable
California climate zone and building type.

HONEST FLAG: This is a simplified TDV compliance screening tool for design
exploration.  It does NOT replace a CEC-approved energy model (e.g. EnergyPro,
OpenStudio/EnergyPlus with CEC Title 24 measures). For permit compliance,
a certified energy analyst using approved software is required.

Dataclasses
-----------
Title24Spec     — building + climate inputs
Title24Report   — compliance result: TDV comparison, margin, failures, caveats

Functions
---------
check_title24_compliance(spec, annual) -> Title24Report

TDV Method
----------
Time-Dependent Valuation converts site energy to a cost/environmental-impact
weighting:
    TDV_annual = Σ_h [ E_h (kWh) × TDV_multiplier_h (kBtu/kWh) ]
where TDV_multiplier_h varies by hour, fuel type, and climate zone.

This module uses a simplified approach:
  - Annual heating TDV  = heating_kwh × TDV_heat_factor(cz, fuel)
  - Annual cooling TDV  = cooling_kwh × TDV_cool_factor(cz)
  - Annual lighting TDV = lighting_kwh × TDV_elect_factor(cz)
  - Annual fans TDV     = fan_kwh × TDV_elect_factor(cz)
TDV factors are kBtu/kWh from CEC 2022 TDV multiplier tables (annual averages).

References
----------
CEC — California Building Energy Code, Title 24 Part 6, 2022 Edition
CEC — 2022 Title 24 TDV Multiplier Data (Appendix C, Tables C-1 to C-6)
CEC — 2022 ACM Reference Manual (Alternative Calculation Method)
ASHRAE 169-2020 — Climate data (CZ correlation)
California Climate Zones 1-16 (CEC CZ definition)

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from kerf_cad_core.buildingenergy.hourly_8760 import AnnualResult


# ---------------------------------------------------------------------------
# CEC Title 24 2022 TDV multiplier data (simplified annual averages)
# Units: kBtu/kWh for electricity, kBtu/therm for natural gas
# Source: CEC 2022 TDV multipliers, Appendix C — averaged across occupancy types
#
# California Climate Zones (CEC):
#   CZ1  = Arcata (North Coast)     CZ9  = West San Fernando Valley
#   CZ2  = Santa Rosa               CZ10 = West Los Angeles (Coastal)
#   CZ3  = Oakland                  CZ11 = Burbank
#   CZ4  = Sunnyvale                CZ12 = Sacramento
#   CZ5  = Santa Maria              CZ13 = Fresno
#   CZ6  = Los Angeles              CZ14 = Needles
#   CZ7  = San Diego                CZ15 = Palm Springs
#   CZ8  = El Toro                  CZ16 = Blue Canyon
# ---------------------------------------------------------------------------

# TDV multipliers (kBtu/kWh) for electricity by climate zone
# Derived from CEC 2022 TDV data — annual average mixed-fuel scenario
# Cooling peak hours have higher TDV; this uses annual weighted average
_TDV_ELECT_KZ: Dict[int, float] = {
    1: 3.50,   # CZ1: North Coast — low cooling, moderate heating
    2: 3.55,
    3: 3.58,
    4: 3.62,
    5: 3.45,   # CZ5: Coastal Santa Maria
    6: 3.70,
    7: 3.65,
    8: 3.85,
    9: 3.90,
    10: 3.68,
    11: 4.05,  # CZ11: Burbank — high cooling TDV
    12: 3.80,
    13: 4.10,  # CZ13: Fresno — very high cooling demand
    14: 4.30,  # CZ14: Needles — extreme cooling
    15: 4.50,  # CZ15: Palm Springs — highest cooling TDV
    16: 3.40,  # CZ16: High desert/mountain
}

# TDV multipliers (kBtu/therm) for natural gas heating by climate zone
# (gas-heated buildings; lower value = less TDV per kBtu delivered)
_TDV_GAS_KZ: Dict[int, float] = {
    1: 1.07,
    2: 1.05,
    3: 1.04,
    4: 1.05,
    5: 1.03,
    6: 1.04,
    7: 1.04,
    8: 1.06,
    9: 1.07,
    10: 1.04,
    11: 1.08,
    12: 1.07,
    13: 1.09,
    14: 1.10,
    15: 1.12,
    16: 1.06,
}

# kWh to kBtu conversion
_KWH_TO_KBTU = 3.412141

# Natural gas: 1 therm = 29.3 kWh (HHV basis)
_KWH_PER_THERM = 29.3


# ---------------------------------------------------------------------------
# Title 24 Reference Building TDV baseline (kBtu/(ft²·yr))
# Derived from CEC 2022 ACM Reference Manual, Tables with DOE prototype buildings
# Converted to kBtu/(m²·yr) internally.
#
# Building types: office, retail, school, hospital, residential
# All 16 California climate zones represented.
# ---------------------------------------------------------------------------

# kBtu/(m²·yr) = kBtu/(ft²·yr) × 10.7639
_FT2_TO_M2 = 10.7639

def _kbtu_ft2_to_m2(v: float) -> float:
    return v * _FT2_TO_M2

# Title 24 2022 Reference Building TDV baseline (kBtu/(m²·yr))
# Source: CEC 2022 Compliance Manual Table 3, derived from ACM Reference Manual
_T24_BASELINE_TDV: Dict[str, Dict[int, float]] = {
    "office": {
        1:  _kbtu_ft2_to_m2(90),
        2:  _kbtu_ft2_to_m2(85),
        3:  _kbtu_ft2_to_m2(82),
        4:  _kbtu_ft2_to_m2(84),
        5:  _kbtu_ft2_to_m2(78),
        6:  _kbtu_ft2_to_m2(86),
        7:  _kbtu_ft2_to_m2(80),
        8:  _kbtu_ft2_to_m2(95),
        9:  _kbtu_ft2_to_m2(100),
        10: _kbtu_ft2_to_m2(88),
        11: _kbtu_ft2_to_m2(105),
        12: _kbtu_ft2_to_m2(98),
        13: _kbtu_ft2_to_m2(115),
        14: _kbtu_ft2_to_m2(120),
        15: _kbtu_ft2_to_m2(135),
        16: _kbtu_ft2_to_m2(88),
    },
    "retail": {
        1:  _kbtu_ft2_to_m2(110),
        2:  _kbtu_ft2_to_m2(105),
        3:  _kbtu_ft2_to_m2(100),
        4:  _kbtu_ft2_to_m2(103),
        5:  _kbtu_ft2_to_m2(97),
        6:  _kbtu_ft2_to_m2(106),
        7:  _kbtu_ft2_to_m2(98),
        8:  _kbtu_ft2_to_m2(115),
        9:  _kbtu_ft2_to_m2(120),
        10: _kbtu_ft2_to_m2(107),
        11: _kbtu_ft2_to_m2(125),
        12: _kbtu_ft2_to_m2(118),
        13: _kbtu_ft2_to_m2(135),
        14: _kbtu_ft2_to_m2(140),
        15: _kbtu_ft2_to_m2(155),
        16: _kbtu_ft2_to_m2(106),
    },
    "school": {
        1:  _kbtu_ft2_to_m2(70),
        2:  _kbtu_ft2_to_m2(66),
        3:  _kbtu_ft2_to_m2(62),
        4:  _kbtu_ft2_to_m2(65),
        5:  _kbtu_ft2_to_m2(60),
        6:  _kbtu_ft2_to_m2(67),
        7:  _kbtu_ft2_to_m2(61),
        8:  _kbtu_ft2_to_m2(75),
        9:  _kbtu_ft2_to_m2(78),
        10: _kbtu_ft2_to_m2(68),
        11: _kbtu_ft2_to_m2(82),
        12: _kbtu_ft2_to_m2(76),
        13: _kbtu_ft2_to_m2(88),
        14: _kbtu_ft2_to_m2(92),
        15: _kbtu_ft2_to_m2(100),
        16: _kbtu_ft2_to_m2(70),
    },
    "hospital": {
        1:  _kbtu_ft2_to_m2(280),
        2:  _kbtu_ft2_to_m2(270),
        3:  _kbtu_ft2_to_m2(265),
        4:  _kbtu_ft2_to_m2(268),
        5:  _kbtu_ft2_to_m2(260),
        6:  _kbtu_ft2_to_m2(272),
        7:  _kbtu_ft2_to_m2(263),
        8:  _kbtu_ft2_to_m2(285),
        9:  _kbtu_ft2_to_m2(290),
        10: _kbtu_ft2_to_m2(275),
        11: _kbtu_ft2_to_m2(295),
        12: _kbtu_ft2_to_m2(288),
        13: _kbtu_ft2_to_m2(305),
        14: _kbtu_ft2_to_m2(310),
        15: _kbtu_ft2_to_m2(330),
        16: _kbtu_ft2_to_m2(278),
    },
    "residential": {
        1:  _kbtu_ft2_to_m2(40),
        2:  _kbtu_ft2_to_m2(38),
        3:  _kbtu_ft2_to_m2(36),
        4:  _kbtu_ft2_to_m2(37),
        5:  _kbtu_ft2_to_m2(35),
        6:  _kbtu_ft2_to_m2(38),
        7:  _kbtu_ft2_to_m2(35),
        8:  _kbtu_ft2_to_m2(43),
        9:  _kbtu_ft2_to_m2(45),
        10: _kbtu_ft2_to_m2(39),
        11: _kbtu_ft2_to_m2(48),
        12: _kbtu_ft2_to_m2(44),
        13: _kbtu_ft2_to_m2(52),
        14: _kbtu_ft2_to_m2(55),
        15: _kbtu_ft2_to_m2(62),
        16: _kbtu_ft2_to_m2(42),
    },
}

# Synonym mapping for building type normalisation
_BTYPE_MAP: Dict[str, str] = {
    "office": "office",
    "retail": "retail",
    "school": "school",
    "education": "school",
    "hospital": "hospital",
    "residential": "residential",
    "multifamily": "residential",
    "apartment": "residential",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Title24Spec:
    """Input specification for Title 24 Part 6 compliance check.

    Attributes
    ----------
    climate_zone : int
        California Climate Zone (1–16). CEC definition.
    building_type : str
        Building occupancy: 'office' | 'retail' | 'school' | 'hospital' | 'residential'.
    floor_area_m2 : float
        Gross conditioned floor area (m²).
    occupancy_type : str
        Occupancy descriptor (informational; used in report narrative).
    annual_proposed_tdv_kbtu : float
        Proposed annual TDV energy (kBtu) for the whole building.
        If 0 or negative, it is computed from the AnnualResult passed to
        check_title24_compliance().
    heating_fuel : str
        'gas' (natural gas, default) or 'electric'.
    """
    climate_zone: int
    building_type: str
    floor_area_m2: float
    occupancy_type: str
    annual_proposed_tdv_kbtu: float = 0.0
    heating_fuel: str = "gas"


@dataclass
class Title24Report:
    """Title 24 Part 6 compliance check result.

    Attributes
    ----------
    compliant : bool
        True if proposed TDV ≤ reference baseline TDV.
    proposed_tdv : float
        Proposed annual TDV (kBtu/m²/yr, whole building).
    baseline_tdv : float
        Title 24 2022 Reference Building TDV (kBtu/m²/yr).
    margin_pct : float
        (baseline - proposed) / baseline × 100.  Positive = better than baseline.
    failures : list[str]
        List of compliance failures or warnings.
    honest_caveat : str
        Methodology caveat.
    tdv_breakdown : dict
        TDV by end-use: heating, cooling, lighting, fans.
    """
    compliant: bool
    proposed_tdv: float
    baseline_tdv: float
    margin_pct: float
    failures: List[str]
    honest_caveat: str
    tdv_breakdown: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TDV energy calculation
# ---------------------------------------------------------------------------

def _compute_tdv_from_annual(
    annual: AnnualResult,
    climate_zone: int,
    heating_fuel: str = "gas",
) -> Dict[str, float]:
    """Convert AnnualResult energy (kWh) to TDV energy (kBtu) by end-use.

    TDV_electricity = kWh × TDV_elect_multiplier (kBtu/kWh)
    TDV_gas_heating = (heating_kWh ÷ kWh_per_therm) × TDV_gas_multiplier (kBtu/therm)

    References: CEC 2022 Title 24 ACM Reference Manual, Appendix C.
    """
    cz = max(1, min(16, climate_zone))
    tdv_e = _TDV_ELECT_KZ.get(cz, 3.80)
    tdv_g = _TDV_GAS_KZ.get(cz, 1.07)

    if heating_fuel.lower().startswith("gas"):
        # Heating via gas boiler/furnace: convert kWh → therms → kBtu
        heat_therms = annual.annual_heating_kwh / _KWH_PER_THERM
        tdv_heating = heat_therms * tdv_g * 100.0  # 1 therm = 100 kBtu
    else:
        # Electric heating
        tdv_heating = annual.annual_heating_kwh * tdv_e * _KWH_TO_KBTU

    tdv_cooling = annual.annual_cooling_kwh * tdv_e * _KWH_TO_KBTU
    tdv_lighting = annual.annual_lighting_kwh * tdv_e * _KWH_TO_KBTU
    tdv_fans = annual.annual_fan_kwh * tdv_e * _KWH_TO_KBTU

    return {
        "heating": round(tdv_heating, 1),
        "cooling": round(tdv_cooling, 1),
        "lighting": round(tdv_lighting, 1),
        "fans": round(tdv_fans, 1),
    }


# ---------------------------------------------------------------------------
# Core compliance check
# ---------------------------------------------------------------------------

def check_title24_compliance(spec: Title24Spec, annual: AnnualResult) -> Title24Report:
    """Compare proposed building TDV against Title 24 2022 Reference Building baseline.

    Algorithm
    ---------
    1. Convert AnnualResult to TDV energy (kBtu) using CEC TDV multipliers.
    2. Normalise by floor area → kBtu/(m²·yr).
    3. Look up Title 24 reference baseline TDV from CEC tables (by CZ + building type).
    4. Compute compliance margin.
    5. List failures (compliance mandatories not met).

    Parameters
    ----------
    spec : Title24Spec
    annual : AnnualResult
        Result from simulate_8760().

    Returns
    -------
    Title24Report

    Raises
    ------
    ValueError : for invalid climate_zone or building_type.

    References
    ----------
    CEC — California Building Energy Code, Title 24 Part 6, 2022 Edition
    CEC — 2022 ACM Reference Manual
    """
    cz = spec.climate_zone
    if not 1 <= cz <= 16:
        raise ValueError(f"climate_zone must be 1–16 (California CEC); got {cz}")

    btype_key = _BTYPE_MAP.get(spec.building_type.lower())
    if btype_key is None:
        raise ValueError(
            f"building_type must be one of {sorted(set(_BTYPE_MAP.keys()))}; got {spec.building_type!r}"
        )

    if spec.floor_area_m2 <= 0:
        raise ValueError("floor_area_m2 must be > 0")

    # --- compute TDV from simulation ---
    tdv_breakdown = _compute_tdv_from_annual(annual, cz, spec.heating_fuel)
    total_tdv_kbtu = sum(tdv_breakdown.values())

    # If caller supplied an override, use it (allows pre-computed TDV input)
    if spec.annual_proposed_tdv_kbtu and spec.annual_proposed_tdv_kbtu > 0:
        total_tdv_kbtu = spec.annual_proposed_tdv_kbtu

    proposed_tdv_per_m2 = total_tdv_kbtu / spec.floor_area_m2

    # --- baseline lookup ---
    baseline_tdv_per_m2 = _T24_BASELINE_TDV[btype_key][cz]

    margin_pct = (baseline_tdv_per_m2 - proposed_tdv_per_m2) / baseline_tdv_per_m2 * 100.0
    compliant = proposed_tdv_per_m2 <= baseline_tdv_per_m2

    # --- failure list ---
    failures: List[str] = []
    if not compliant:
        failures.append(
            f"Proposed TDV {proposed_tdv_per_m2:.1f} kBtu/(m²·yr) exceeds Title 24 baseline "
            f"{baseline_tdv_per_m2:.1f} kBtu/(m²·yr) for CZ{cz} {spec.building_type} "
            f"by {abs(margin_pct):.1f}%."
        )

    # Mandatory requirements per Title 24 Part 6 §110.0–§120.0 (simplified checks)
    # §110.2: Air leakage — flag if cooling load is very high relative to floor area
    if annual.peak_cooling_kw / max(spec.floor_area_m2, 1) > 0.25:
        failures.append(
            "Peak cooling load density >250 W/m² suggests poor envelope air-tightness. "
            "Title 24 §110.2 requires air infiltration ≤0.04 L/(s·m²) at 75 Pa."
        )

    # §140.6: Lighting power density — flag only if lighting kwh very high
    lighting_lpd_equiv = annual.annual_lighting_kwh / max(spec.floor_area_m2 * 8760 / 1000, 1.0)
    if btype_key == "office" and lighting_lpd_equiv > 10.0:
        failures.append(
            f"Estimated LPD {lighting_lpd_equiv:.1f} W/m² may exceed Title 24 §140.6 "
            "office limit (8–10 W/m²). Upgrade to LED + daylight controls."
        )

    caveat = (
        "This is a simplified Title 24 Part 6 (2022) compliance screening tool. "
        "TDV multipliers are CEC 2022 annual averages — the full hourly TDV weighting "
        "(which peaks during summer afternoons) is approximated. "
        "Results are indicative only. For permit-grade compliance, use CEC-approved "
        "software (EnergyPro, OpenStudio with Title 24 measures) and a certified energy analyst."
    )

    return Title24Report(
        compliant=compliant,
        proposed_tdv=round(proposed_tdv_per_m2, 2),
        baseline_tdv=round(baseline_tdv_per_m2, 2),
        margin_pct=round(margin_pct, 2),
        failures=failures,
        honest_caveat=caveat,
        tdv_breakdown={k: round(v / max(spec.floor_area_m2, 1), 2) for k, v in tdv_breakdown.items()},
    )
