"""
kerf_energy.compliance_tools — ASHRAE 90.1 Appendix G + LEED EAp2 + Title 24
compliance reporting tools.

Registered LLM tools:
  energy_ashrae901_appendixg_report  — Full Appendix G baseline-vs-proposed PCI report
  energy_leed_eap2_points            — LEED v4.1 EAp2/EAc2 points from % improvement
  energy_title24_compliance          — California Title 24 Part 6 TDV compliance check

HONEST FLAG: These are engineering-estimate tools for design exploration and
compliance screening. NOT government-certified or GBCI-registered software.
Results accuracy ±15–25% vs. full dynamic simulation. For permit-grade compliance
use CEC-approved software and a certified energy analyst/modeller.

References
----------
ASHRAE 90.1-2022 Appendix G — Performance Rating Method
USGBC LEED v4.1 BD+C Reference Guide — Energy & Atmosphere
CEC Title 24 Part 6 2022 — California Energy Code

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False
    from kerf_energy._compat import (  # type: ignore[assignment]
        ToolSpec, err_payload, ok_payload, register, ProjectCtx
    )

from kerf_energy.ashrae901_appendixg import (
    ProposedBuildingSpec,
    compute_appendixg_report,
    _leed_eac2_points,
    _check_title24,
    EndUseBreakdown,
)


# ===========================================================================
# Tool 1: energy_ashrae901_appendixg_report
# ===========================================================================

energy_ashrae901_appendixg_report_spec = ToolSpec(
    name="energy_ashrae901_appendixg_report",
    description=(
        "Generate a full ASHRAE 90.1-2022 Appendix G Performance Rating Method "
        "compliance report — baseline vs. proposed building.\n"
        "\n"
        "Algorithm:\n"
        "  1. Auto-generate ASHRAE 90.1-2022 Appendix G BASELINE building "
        "     (system type per Table G3.1.1; envelope U-values per Table 5.5).\n"
        "  2. Run BASELINE and PROPOSED through an 8760-hour heat-balance engine.\n"
        "  3. Compute Performance Cost Index (PCI) = proposed_cost / baseline_cost.\n"
        "  4. Map % improvement → LEED v4.1 EAp2 prerequisite + EAc2 points.\n"
        "  5. Optionally check California Title 24 TDV compliance.\n"
        "\n"
        "Inputs:\n"
        "  building_type            : 'office'|'residential'|'retail'|'warehouse'|'hospital'|'education'\n"
        "  floor_area_m2            : gross conditioned floor area (m²)\n"
        "  num_floors               : number of above-grade conditioned floors\n"
        "  climate_zone             : ASHRAE 169 zone number 1–8 (strip letter, e.g. '4A' → 4)\n"
        "  heating_fuel             : 'gas' (default) | 'electric'\n"
        "  window_to_wall_ratio     : proposed WWR 0–1 (baseline capped at 0.40)\n"
        "  u_wall                   : proposed wall U-value W/(m²·K)\n"
        "  u_roof                   : proposed roof U-value W/(m²·K)\n"
        "  u_window                 : proposed window U-value W/(m²·K)\n"
        "  shgc                     : proposed window SHGC 0–1\n"
        "  internal_load_w_m2       : peak internal load density W/m² (equip+lighting+people)\n"
        "  hvac_heating_cop         : proposed heating COP or AFUE (e.g. 0.95 = 95% AFUE, 3.0 = HP)\n"
        "  hvac_cooling_cop         : proposed cooling COP (e.g. 5.0 = high-efficiency chiller)\n"
        "  climate_mean_c           : mean annual outdoor temperature °C (default 13.0)\n"
        "  climate_amplitude_c      : seasonal temperature amplitude °C (default 10.0)\n"
        "  california_climate_zone  : CEC CZ 1–16 for Title 24 check (optional)\n"
        "\n"
        "Outputs: baseline_system_number, baseline_system_name, baseline_end_use,\n"
        "  proposed_end_use, performance_cost_index, pct_better_than_baseline,\n"
        "  ashrae_901_compliant, leed_eap2_prerequisite_met, leed_eac2_points,\n"
        "  title24_compliant, title24_margin_pct, baseline_annual_cost_usd,\n"
        "  proposed_annual_cost_usd, recommendations, human_readable (text report).\n"
        "\n"
        "HONEST CAVEAT: Engineering estimates — NOT certified compliance software.\n"
        "PCI < 1.0 = proposed building uses less energy cost than 90.1 baseline.\n"
        "References: ASHRAE 90.1-2022 Appendix G; LEED v4.1 BD+C EA section.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "building_type": {
                "type": "string",
                "enum": ["office", "residential", "retail", "warehouse", "hospital", "education"],
                "description": "Primary building occupancy type.",
            },
            "floor_area_m2": {
                "type": "number",
                "description": "Gross conditioned floor area (m²). Must be > 0.",
            },
            "num_floors": {
                "type": "integer",
                "description": "Number of above-grade conditioned floors (≥1).",
            },
            "climate_zone": {
                "type": "integer",
                "description": "ASHRAE 169 climate zone number 1–8. Strip moisture letter (e.g. '4A' → 4).",
            },
            "heating_fuel": {
                "type": "string",
                "enum": ["gas", "electric"],
                "description": "Primary heating fuel. Default 'gas'.",
            },
            "window_to_wall_ratio": {
                "type": "number",
                "description": "Proposed building WWR (0–1). Baseline capped at 0.40 per Appendix G G3.1.5.",
            },
            "u_wall": {
                "type": "number",
                "description": "Proposed wall U-value W/(m²·K). Baseline per 90.1 Table 5.5.",
            },
            "u_roof": {
                "type": "number",
                "description": "Proposed roof U-value W/(m²·K). Baseline per 90.1 Table 5.5.",
            },
            "u_window": {
                "type": "number",
                "description": "Proposed window U-value W/(m²·K). Baseline per 90.1 Table 5.5.",
            },
            "shgc": {
                "type": "number",
                "description": "Proposed window SHGC (0–1). Baseline per 90.1 Table 5.5.",
            },
            "internal_load_w_m2": {
                "type": "number",
                "description": "Peak internal load density W/m² (equipment + lighting + people combined).",
            },
            "hvac_heating_cop": {
                "type": "number",
                "description": (
                    "Proposed heating system COP or AFUE fraction. "
                    "0.95 = 95% AFUE condensing furnace; 3.0 = heat pump COP 3.0."
                ),
            },
            "hvac_cooling_cop": {
                "type": "number",
                "description": "Proposed cooling system COP. 3.2 = standard chiller; 5.0 = high-efficiency.",
            },
            "climate_mean_c": {
                "type": "number",
                "description": "Mean annual outdoor temperature (°C) for synthetic weather. Default 13.0.",
            },
            "climate_amplitude_c": {
                "type": "number",
                "description": "Seasonal temperature amplitude (°C). Default 10.0.",
            },
            "california_climate_zone": {
                "type": "integer",
                "description": "CEC California Climate Zone 1–16 for Title 24 TDV check. Omit to skip.",
            },
        },
        "required": [
            "building_type", "floor_area_m2", "num_floors", "climate_zone",
            "u_wall", "u_roof", "u_window", "shgc",
            "hvac_heating_cop", "hvac_cooling_cop",
        ],
    },
)


@register(energy_ashrae901_appendixg_report_spec, write=False)
async def run_energy_ashrae901_appendixg_report(ctx: ProjectCtx, args: bytes) -> str:
    """Run ASHRAE 90.1 Appendix G baseline vs proposed compliance analysis."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    required = ["building_type", "floor_area_m2", "num_floors", "climate_zone",
                "u_wall", "u_roof", "u_window", "shgc",
                "hvac_heating_cop", "hvac_cooling_cop"]
    for key in required:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    try:
        spec = ProposedBuildingSpec(
            name=str(a.get("name", "Building")),
            building_type=str(a["building_type"]),
            floor_area_m2=float(a["floor_area_m2"]),
            num_floors=int(a["num_floors"]),
            climate_zone=int(a["climate_zone"]),
            heating_fuel=str(a.get("heating_fuel", "gas")),
            window_to_wall_ratio=float(a.get("window_to_wall_ratio", 0.40)),
            u_wall=float(a["u_wall"]),
            u_roof=float(a["u_roof"]),
            u_window=float(a["u_window"]),
            shgc=float(a["shgc"]),
            internal_load_w_m2=float(a.get("internal_load_w_m2", 20.0)),
            hvac_heating_cop=float(a["hvac_heating_cop"]),
            hvac_cooling_cop=float(a["hvac_cooling_cop"]),
            climate_mean_c=float(a.get("climate_mean_c", 13.0)),
            climate_amplitude_c=float(a.get("climate_amplitude_c", 10.0)),
            california_climate_zone=int(a["california_climate_zone"])
            if a.get("california_climate_zone") is not None else None,
        )
        report = compute_appendixg_report(spec)
    except (ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload(report.to_dict())


# ===========================================================================
# Tool 2: energy_leed_eap2_points
# ===========================================================================

energy_leed_eap2_points_spec = ToolSpec(
    name="energy_leed_eap2_points",
    description=(
        "Evaluate LEED v4.1 EAp2 (Minimum Energy Performance) prerequisite "
        "and EAc2 (Optimize Energy Performance) credit points from the % improvement "
        "over the ASHRAE 90.1 Appendix G baseline.\n"
        "\n"
        "Inputs:\n"
        "  pct_better_than_baseline : % improvement over 90.1 baseline (positive = better)\n"
        "  project_type             : 'new_construction'|'major_renovation'|'core_and_shell' "
        "(default 'new_construction')\n"
        "  renewables_offset_pct    : additional % improvement from on-site renewables "
        "(default 0)\n"
        "\n"
        "Outputs:\n"
        "  prerequisite_met    : True if effective savings ≥ EAp2 minimum threshold\n"
        "  minimum_threshold_pct : EAp2 minimum (5% NC, 3% C&S)\n"
        "  eac2_points_earned  : EAc2 Optimize Energy Performance points (0–18)\n"
        "  effective_savings_pct : savings after renewable offset\n"
        "  next_threshold_pct  : % needed for next point tier\n"
        "  point_detail        : narrative explanation\n"
        "\n"
        "References: USGBC LEED v4.1 BD+C Reference Guide — EAp2 + EAc2.\n"
        "Honest flag: screening only — not GBCI-certified LEED submission."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pct_better_than_baseline": {
                "type": "number",
                "description": (
                    "Percentage improvement over ASHRAE 90.1 Appendix G baseline "
                    "(from energy_ashrae901_appendixg_report or other model). "
                    "Positive = better than baseline."
                ),
            },
            "project_type": {
                "type": "string",
                "enum": [
                    "new_construction", "major_renovation", "core_and_shell",
                    "schools", "retail", "data_centers", "hospitality", "healthcare",
                ],
                "description": "LEED project type. Default 'new_construction'.",
            },
            "renewables_offset_pct": {
                "type": "number",
                "description": (
                    "Additional % improvement attributable to on-site renewable energy "
                    "(PV, wind). Adds to pct_better_than_baseline for LEED scoring. Default 0."
                ),
            },
        },
        "required": ["pct_better_than_baseline"],
    },
)


@register(energy_leed_eap2_points_spec, write=False)
async def run_energy_leed_eap2_points(ctx: ProjectCtx, args: bytes) -> str:
    """Evaluate LEED v4.1 EAp2 + EAc2 from % improvement over 90.1 baseline."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("pct_better_than_baseline") is None:
        return err_payload("pct_better_than_baseline is required", "BAD_ARGS")

    try:
        pct_raw = float(a["pct_better_than_baseline"])
        renewables_offset = float(a.get("renewables_offset_pct", 0.0))
        effective_pct = pct_raw + max(0.0, renewables_offset)
        project_type = str(a.get("project_type", "new_construction")).lower().replace("-", "_")
    except (ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    # Minimum threshold by project type
    _EAP2_MIN: dict = {
        "new_construction": 5.0,
        "major_renovation": 5.0,
        "core_and_shell": 3.0,
        "schools": 5.0,
        "retail": 5.0,
        "data_centers": 5.0,
        "hospitality": 5.0,
        "healthcare": 5.0,
    }
    # Core & Shell gets 2% bonus on EAc2 point thresholds
    core_shell_bonus = 2.0 if project_type == "core_and_shell" else 0.0
    min_threshold = _EAP2_MIN.get(project_type, 5.0)
    prereq_met = effective_pct >= min_threshold

    # EAc2 scoring with Core & Shell bonus
    eac2_pct = effective_pct + core_shell_bonus
    pts = _leed_eac2_points(eac2_pct) if prereq_met else 0

    # Find next threshold
    from kerf_energy.ashrae901_appendixg import _LEED_EAC2_TABLE
    next_threshold = None
    for min_p, p in _LEED_EAC2_TABLE:
        if (eac2_pct - core_shell_bonus) < min_p:
            next_threshold = float(min_p) - core_shell_bonus
            break

    # Point detail narrative
    detail: list = []
    if prereq_met:
        detail.append(
            f"EAp2 Prerequisite MET: {effective_pct:.1f}% energy savings "
            f"≥ {min_threshold:.1f}% minimum for {project_type}."
        )
        if pts > 0:
            detail.append(
                f"EAc2 Optimize Energy Performance: {pts} point(s) earned "
                f"at {effective_pct:.1f}% savings tier."
            )
            if next_threshold is not None:
                gap = next_threshold - effective_pct
                detail.append(
                    f"To earn {pts + 1} EAc2 points: improve by {gap:.1f}% more "
                    f"(target ≥{next_threshold:.0f}%)."
                )
            else:
                detail.append("Maximum EAc2 points (18) achieved at ≥50% savings tier.")
        else:
            detail.append(
                f"EAc2 requires ≥6% savings for 1 point (≥8% for 2 points). "
                f"Current: {effective_pct:.1f}%. EAp2 prerequisite satisfied."
            )
    else:
        detail.append(
            f"EAp2 Prerequisite NOT MET: {effective_pct:.1f}% savings < "
            f"{min_threshold:.1f}% minimum for {project_type}. "
            "Building cannot pursue LEED certification until this is satisfied."
        )

    if renewables_offset > 0:
        detail.append(
            f"On-site renewable offset: +{renewables_offset:.1f}% applied "
            f"(raw savings {pct_raw:.1f}% → effective {effective_pct:.1f}%)."
        )

    return ok_payload({
        "prerequisite_met": prereq_met,
        "minimum_threshold_pct": min_threshold,
        "eac2_points_earned": pts,
        "effective_savings_pct": round(effective_pct, 2),
        "raw_savings_pct": round(pct_raw, 2),
        "renewables_offset_pct": round(renewables_offset, 2),
        "next_threshold_pct": next_threshold,
        "point_detail": detail,
        "honest_caveat": (
            "LEED v4.1 EAp2/EAc2 screening only. NOT a GBCI-certified submission. "
            "Full LEED certification requires a LEED-AP qualified professional and "
            "GBCI project review. EUI-based savings may differ from energy-cost savings "
            "used in formal submissions by ±5–15% depending on fuel mix."
        ),
    })


# ===========================================================================
# Tool 3: energy_title24_compliance
# ===========================================================================

energy_title24_compliance_spec = ToolSpec(
    name="energy_title24_compliance",
    description=(
        "Check California Title 24 Part 6 (2022) energy compliance using the "
        "Time-Dependent Valuation (TDV) method.\n"
        "\n"
        "Compares the proposed building's annual TDV energy against the Title 24 "
        "2022 Reference Building TDV baseline for the applicable California Climate "
        "Zone (1–16) and building type.\n"
        "\n"
        "Inputs:\n"
        "  california_climate_zone : CEC CZ 1–16\n"
        "  building_type           : 'office'|'retail'|'school'|'hospital'|'residential'\n"
        "  floor_area_m2           : gross conditioned floor area (m²)\n"
        "  annual_heating_kwh      : proposed annual heating energy (kWh)\n"
        "  annual_cooling_kwh      : proposed annual cooling energy (kWh)\n"
        "  annual_fan_kwh          : proposed annual fan energy (kWh)\n"
        "  annual_lighting_kwh     : proposed annual lighting energy (kWh)\n"
        "  heating_fuel            : 'gas' (default) | 'electric'\n"
        "\n"
        "Outputs:\n"
        "  compliant           : True if proposed TDV ≤ Title 24 reference baseline\n"
        "  proposed_tdv        : proposed TDV kBtu/(m²·yr)\n"
        "  baseline_tdv        : T24 reference TDV kBtu/(m²·yr)\n"
        "  margin_pct          : (baseline - proposed) / baseline × 100 (positive = better)\n"
        "  tdv_breakdown       : TDV by end-use\n"
        "  pass_fail_badge     : 'PASS' | 'FAIL'\n"
        "\n"
        "TDV method: site energy × CEC 2022 hourly TDV multipliers (annual average). "
        "References: CEC Title 24 Part 6 2022; CEC ACM Reference Manual.\n"
        "Honest flag: simplified TDV screening — not CEC-approved compliance software."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "california_climate_zone": {
                "type": "integer",
                "description": "CEC California Climate Zone (1–16).",
            },
            "building_type": {
                "type": "string",
                "enum": ["office", "retail", "school", "hospital", "residential"],
                "description": "Building occupancy type.",
            },
            "floor_area_m2": {
                "type": "number",
                "description": "Gross conditioned floor area (m²).",
            },
            "annual_heating_kwh": {
                "type": "number",
                "description": "Proposed annual heating site energy (kWh).",
            },
            "annual_cooling_kwh": {
                "type": "number",
                "description": "Proposed annual cooling site energy (kWh).",
            },
            "annual_fan_kwh": {
                "type": "number",
                "description": "Proposed annual HVAC fan energy (kWh). Default 0.",
            },
            "annual_lighting_kwh": {
                "type": "number",
                "description": "Proposed annual lighting energy (kWh). Default 0.",
            },
            "heating_fuel": {
                "type": "string",
                "enum": ["gas", "electric"],
                "description": "Primary heating fuel. Default 'gas'.",
            },
        },
        "required": [
            "california_climate_zone", "building_type", "floor_area_m2",
            "annual_heating_kwh", "annual_cooling_kwh",
        ],
    },
)


# T24 reference TDV baselines (kBtu/(m²·yr)) by building type and CEC CZ
# Source: CEC 2022 ACM Reference Manual, derived from DOE prototype buildings
_T24_BASELINE: dict = {
    "office": {
        1: 968.75, 2: 914.93, 3: 882.64, 4: 903.76, 5: 839.58,
        6: 925.68, 7: 861.11, 8: 1022.57, 9: 1076.39, 10: 947.22,
        11: 1130.21, 12: 1054.86, 13: 1237.85, 14: 1291.67, 15: 1453.13, 16: 947.22,
    },
    "retail": {
        1: 1183.92, 2: 1129.71, 3: 1076.39, 4: 1108.68, 5: 1044.62,
        6: 1140.28, 7: 1055.21, 8: 1237.85, 9: 1291.67, 10: 1151.74,
        11: 1345.49, 12: 1270.14, 13: 1453.13, 14: 1506.94, 15: 1668.40, 16: 1140.28,
    },
    "school": {
        1: 753.47, 2: 710.07, 3: 667.36, 4: 699.65, 5: 645.83,
        6: 720.83, 7: 656.60, 8: 807.29, 9: 839.58, 10: 731.94,
        11: 882.64, 12: 818.06, 13: 947.22, 14: 990.28, 15: 1076.39, 16: 753.47,
    },
    "hospital": {
        1: 3013.89, 2: 2906.25, 3: 2852.43, 4: 2884.72, 5: 2798.61,
        6: 2928.47, 7: 2831.60, 8: 3068.40, 9: 3122.22, 10: 2960.76,
        11: 3175.35, 12: 3101.39, 13: 3282.99, 14: 3336.81, 15: 3552.08, 16: 2992.36,
    },
    "residential": {
        1: 430.56, 2: 409.03, 3: 387.50, 4: 398.26, 5: 376.74,
        6: 409.03, 7: 376.74, 8: 462.85, 9: 484.72, 10: 419.79,
        11: 516.67, 12: 473.61, 13: 559.72, 14: 592.01, 15: 667.36, 16: 451.74,
    },
}
_BTYPE_ALIAS: dict = {
    "office": "office", "retail": "retail", "school": "school",
    "education": "school", "hospital": "hospital",
    "residential": "residential", "multifamily": "residential",
}
_TDV_ELECT: dict = {
    1: 3.50, 2: 3.55, 3: 3.58, 4: 3.62, 5: 3.45, 6: 3.70, 7: 3.65, 8: 3.85,
    9: 3.90, 10: 3.68, 11: 4.05, 12: 3.80, 13: 4.10, 14: 4.30, 15: 4.50, 16: 3.40,
}
_KWH_TO_KBTU = 3.412141


@register(energy_title24_compliance_spec, write=False)
async def run_energy_title24_compliance(ctx: ProjectCtx, args: bytes) -> str:
    """Check California Title 24 Part 6 (2022) TDV compliance."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    required_fields = [
        "california_climate_zone", "building_type", "floor_area_m2",
        "annual_heating_kwh", "annual_cooling_kwh",
    ]
    for key in required_fields:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    try:
        ca_cz = int(a["california_climate_zone"])
        building_type = str(a["building_type"]).lower()
        floor_area_m2 = float(a["floor_area_m2"])
        heat_kwh = float(a["annual_heating_kwh"])
        cool_kwh = float(a["annual_cooling_kwh"])
        fan_kwh = float(a.get("annual_fan_kwh", 0.0))
        light_kwh = float(a.get("annual_lighting_kwh", 0.0))
        heating_fuel = str(a.get("heating_fuel", "gas")).lower()
    except (ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    if not 1 <= ca_cz <= 16:
        return err_payload(f"california_climate_zone must be 1–16; got {ca_cz}", "BAD_ARGS")
    if floor_area_m2 <= 0:
        return err_payload("floor_area_m2 must be > 0", "BAD_ARGS")

    btype_key = _BTYPE_ALIAS.get(building_type)
    if btype_key is None:
        return err_payload(
            f"building_type must be one of {sorted(set(_BTYPE_ALIAS.keys()))}; "
            f"got {building_type!r}",
            "BAD_ARGS",
        )

    tdv_e = _TDV_ELECT.get(ca_cz, 3.80)
    kbtu_per_therm = 100.0
    kwh_per_therm = 29.3

    if heating_fuel.startswith("electric"):
        tdv_heat = heat_kwh * tdv_e * _KWH_TO_KBTU
    else:
        heat_therms = heat_kwh / kwh_per_therm
        tdv_heat = heat_therms * 1.07 * kbtu_per_therm

    tdv_cool = cool_kwh * tdv_e * _KWH_TO_KBTU
    tdv_fan = fan_kwh * tdv_e * _KWH_TO_KBTU
    tdv_light = light_kwh * tdv_e * _KWH_TO_KBTU
    total_tdv_kbtu = tdv_heat + tdv_cool + tdv_fan + tdv_light

    proposed_tdv_per_m2 = total_tdv_kbtu / floor_area_m2
    baseline_tdv_per_m2 = _T24_BASELINE[btype_key][ca_cz]

    margin_pct = (baseline_tdv_per_m2 - proposed_tdv_per_m2) / baseline_tdv_per_m2 * 100.0
    compliant = proposed_tdv_per_m2 <= baseline_tdv_per_m2

    tdv_breakdown = {
        "heating_kbtu_m2_yr": round(tdv_heat / floor_area_m2, 2),
        "cooling_kbtu_m2_yr": round(tdv_cool / floor_area_m2, 2),
        "fans_kbtu_m2_yr": round(tdv_fan / floor_area_m2, 2),
        "lighting_kbtu_m2_yr": round(tdv_light / floor_area_m2, 2),
        "total_kbtu_m2_yr": round(proposed_tdv_per_m2, 2),
    }

    failures: list = []
    if not compliant:
        failures.append(
            f"Proposed TDV {proposed_tdv_per_m2:.1f} kBtu/(m²·yr) exceeds Title 24 "
            f"baseline {baseline_tdv_per_m2:.1f} kBtu/(m²·yr) for CZ{ca_cz} "
            f"{building_type} by {abs(margin_pct):.1f}%."
        )

    return ok_payload({
        "compliant": compliant,
        "pass_fail_badge": "PASS" if compliant else "FAIL",
        "proposed_tdv_kbtu_m2_yr": round(proposed_tdv_per_m2, 2),
        "baseline_tdv_kbtu_m2_yr": round(baseline_tdv_per_m2, 2),
        "margin_pct": round(margin_pct, 2),
        "tdv_breakdown": tdv_breakdown,
        "failures": failures,
        "california_climate_zone": ca_cz,
        "building_type": building_type,
        "honest_caveat": (
            "Simplified Title 24 Part 6 (2022) TDV compliance screening. "
            "TDV multipliers are CEC 2022 annual averages (the full hourly weighting "
            "with summer-afternoon peaks is approximated). "
            "NOT CEC-approved compliance software. For permit-grade compliance, "
            "use EnergyPro or OpenStudio with Title 24 measures and a certified "
            "energy analyst."
        ),
    })
