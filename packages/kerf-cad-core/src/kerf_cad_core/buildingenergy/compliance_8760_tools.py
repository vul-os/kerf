"""
kerf_cad_core.buildingenergy.compliance_8760_tools — LLM tool wrappers for
8760-hour ASHRAE 90.1 / Title 24 / LEED v4 EAp2 + HVAC plant compliance simulation.

Wave 9D: 8760-hr ASHRAE compliance + Title 24 + LEED v4 EAp2 + HVAC plant

Registered tools
----------------
be_simulate_8760
    Run an 8760-hour single-zone heat-balance energy simulation from a building
    description (geometry, envelope U-values, occupancy, HVAC setpoints).
    Uses hourly synthetic weather or passed WeatherHour list.
    Returns AnnualResult summary: annual kWh by end-use + EUI.

be_check_title24
    Check California Title 24 Part 6 (2022) compliance for a building in a
    given CEC climate zone (1–16). Computes TDV energy vs. reference baseline.
    Returns Title24Report: compliant flag, margin %, failures.

be_evaluate_leed_eap2
    Evaluate LEED v4.1 EAp2 (Minimum Energy Performance prerequisite) and
    EAc1 (Optimize Energy Performance optional credit, 1–18 points).
    Returns LeedEAp2Report: prerequisite_met, optional_eac1_points, savings %.

be_simulate_hvac_plant
    Apply HVAC plant efficiency curves (chiller COP + boiler efficiency) to
    hourly loads from be_simulate_8760. Returns annual electricity and gas use.

All tools are pure Python + numpy.  No OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ASHRAE 90.1-2022 + Appendix G — Performance Rating Method
CA Title 24 Part 6 2022 Edition — California Energy Code
USGBC LEED v4.1 BD+C Reference Guide — EA Prerequisites and Credits
AHRI Standard 550/590-2023 — Chiller rating conditions
NREL TMY3 User's Manual (2008) — Typical Meteorological Year 3

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any, Dict

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False
    ToolSpec = None  # type: ignore[assignment,misc]
    err_payload = None  # type: ignore[assignment]
    ok_payload = None  # type: ignore[assignment]
    register = None  # type: ignore[assignment]
    ProjectCtx = None  # type: ignore[assignment,misc]

from kerf_cad_core.buildingenergy.hourly_8760 import (
    BuildingModel,
    WeatherHour,
    simulate_8760,
    load_tmy3_weather,
    _default_office_schedule,
)
from kerf_cad_core.buildingenergy.title24_compliance import (
    Title24Spec,
    check_title24_compliance,
)
from kerf_cad_core.buildingenergy.leed_v4_eap2 import (
    LeedEAp2Spec,
    evaluate_leed_v4_eap2,
)
from kerf_cad_core.buildingenergy.hvac_plant import (
    ChillerSpec,
    BoilerSpec,
    AirSideSystem,
    simulate_hvac_plant,
)


# ---------------------------------------------------------------------------
# Helper: synthesise mild-weather 8760 list for testing / demo
# ---------------------------------------------------------------------------

def _synthesise_weather_8760(climate_mean_c: float = 13.0, amplitude_c: float = 10.0) -> list:
    """Synthesise a simple sinusoidal 8760-hour weather list (no file required).

    Used when no TMY3 file is available. Produces physically plausible values
    for screening calculations.
    """
    import math
    hours = []
    for h in range(8760):
        t = (
            climate_mean_c
            + amplitude_c * math.cos(2 * math.pi * h / 8760 + math.pi)
            + 3.0 * math.cos(2 * math.pi * (h % 24) / 24 + math.pi)
        )
        rh = 50.0 + 20.0 * math.sin(2 * math.pi * h / 8760)
        hour_of_day = h % 24
        is_day = 7 <= hour_of_day <= 19
        dni = max(0.0, 600.0 * math.sin(math.pi * (hour_of_day - 7) / 12)) if is_day else 0.0
        dhi = max(0.0, 100.0 * math.sin(math.pi * (hour_of_day - 7) / 12)) if is_day else 0.0
        hours.append(WeatherHour(
            iso_datetime=f"2026-01-01T{(h % 24):02d}:00",
            dry_bulb_c=round(t, 1),
            wet_bulb_c=round(t - 3.0, 1),
            relative_humidity_pct=round(rh, 1),
            direct_normal_irradiance_w_m2=round(dni, 1),
            diffuse_horizontal_irradiance_w_m2=round(dhi, 1),
            wind_speed_m_s=3.0,
            wind_direction_deg=180.0,
        ))
    return hours


# ---------------------------------------------------------------------------
# Tool 1: be_simulate_8760
# ---------------------------------------------------------------------------

_SPEC_8760 = {
    "name": "be_simulate_8760",
    "description": (
        "Run an 8760-hour single-zone heat-balance energy simulation.\n"
        "\n"
        "Inputs:\n"
        "  name                  : building name (string)\n"
        "  floor_area_m2         : gross floor area (m²)\n"
        "  window_to_wall_ratio  : WWR 0–1 (e.g. 0.40 = 40%)\n"
        "  u_wall                : wall U-value W/(m²·K)\n"
        "  u_roof                : roof U-value W/(m²·K)\n"
        "  u_window              : window U-value W/(m²·K)\n"
        "  shgc                  : window SHGC 0–1 (default 0.40)\n"
        "  internal_load_w_m2    : peak internal load W/m² (equip+lighting+people)\n"
        "  setpoint_heating_c    : heating setpoint °C (default 20)\n"
        "  setpoint_cooling_c    : cooling setpoint °C (default 24)\n"
        "  ceiling_height_m      : ceiling height m (default 3.0)\n"
        "  climate_mean_c        : mean annual outdoor temp for synthetic weather\n"
        "  climate_amplitude_c   : seasonal amplitude °C (default 10)\n"
        "  tmy3_csv              : optional TMY3 CSV file content (overrides synthetic)\n"
        "\n"
        "Outputs: annual_heating_kwh, annual_cooling_kwh, annual_fan_kwh, "
        "annual_lighting_kwh, eui_kwh_m2_yr, peak_heating_kw, peak_cooling_kw.\n"
        "\n"
        "References: ASHRAE 90.1-2022 Appendix G; NREL TMY3 Manual.\n"
        "Honest flag: simplified single-zone model; not EnergyPlus replacement."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "floor_area_m2": {"type": "number"},
            "window_to_wall_ratio": {"type": "number"},
            "u_wall": {"type": "number"},
            "u_roof": {"type": "number"},
            "u_window": {"type": "number"},
            "shgc": {"type": "number"},
            "internal_load_w_m2": {"type": "number"},
            "setpoint_heating_c": {"type": "number"},
            "setpoint_cooling_c": {"type": "number"},
            "ceiling_height_m": {"type": "number"},
            "climate_mean_c": {"type": "number"},
            "climate_amplitude_c": {"type": "number"},
            "tmy3_csv": {"type": "string"},
        },
        "required": ["floor_area_m2", "u_wall", "u_roof", "u_window"],
    },
}


async def _run_simulate_8760(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    try:
        construction = {
            "wall": float(a.get("u_wall", 0.35)),
            "roof": float(a.get("u_roof", 0.20)),
            "window": float(a.get("u_window", 2.0)),
            "shgc": float(a.get("shgc", 0.40)),
        }
        model = BuildingModel(
            name=str(a.get("name", "Building")),
            floor_area_m2=float(a["floor_area_m2"]),
            window_to_wall_ratio=float(a.get("window_to_wall_ratio", 0.40)),
            construction_uw_m2k=construction,
            internal_load_w_m2=float(a.get("internal_load_w_m2", 20.0)),
            occupancy_schedule_8760=[],
            setpoint_heating_c=float(a.get("setpoint_heating_c", 20.0)),
            setpoint_cooling_c=float(a.get("setpoint_cooling_c", 24.0)),
            ceiling_height_m=float(a.get("ceiling_height_m", 3.0)),
        )

        tmy3_csv = a.get("tmy3_csv")
        if tmy3_csv:
            weather = load_tmy3_weather(str(tmy3_csv))
        else:
            climate_mean = float(a.get("climate_mean_c", 13.0))
            climate_amp = float(a.get("climate_amplitude_c", 10.0))
            weather = _synthesise_weather_8760(climate_mean, climate_amp)

        result = simulate_8760(model, weather)

    except (ValueError, TypeError, KeyError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    payload = {
        "ok": True,
        "annual_heating_kwh": result.annual_heating_kwh,
        "annual_cooling_kwh": result.annual_cooling_kwh,
        "annual_fan_kwh": result.annual_fan_kwh,
        "annual_lighting_kwh": result.annual_lighting_kwh,
        "eui_kwh_m2_yr": result.eui_kwh_m2_yr,
        "peak_heating_kw": result.peak_heating_kw,
        "peak_cooling_kw": result.peak_cooling_kw,
        "honest_flag": (
            "Simplified single-zone model — not EnergyPlus. "
            "Use for early-stage compliance screening only."
        ),
    }
    if _REGISTRY_AVAILABLE and ok_payload:
        return ok_payload(payload)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tool 2: be_check_title24
# ---------------------------------------------------------------------------

_SPEC_TITLE24 = {
    "name": "be_check_title24",
    "description": (
        "Check California Title 24 Part 6 (2022) compliance.\n"
        "\n"
        "Inputs (from be_simulate_8760 result):\n"
        "  climate_zone        : CEC climate zone 1–16\n"
        "  building_type       : 'office'|'retail'|'school'|'hospital'|'residential'\n"
        "  floor_area_m2       : gross floor area (m²)\n"
        "  annual_heating_kwh  : from be_simulate_8760\n"
        "  annual_cooling_kwh  : from be_simulate_8760\n"
        "  annual_lighting_kwh : from be_simulate_8760\n"
        "  annual_fan_kwh      : from be_simulate_8760\n"
        "  heating_fuel        : 'gas' (default) | 'electric'\n"
        "  peak_cooling_kw     : from be_simulate_8760 (for mandatory checks)\n"
        "\n"
        "Outputs: compliant, proposed_tdv, baseline_tdv, margin_pct, failures.\n"
        "\n"
        "References: CEC Title 24 Part 6 2022; CEC ACM Reference Manual.\n"
        "Honest flag: simplified TDV screening — not CEC-approved software."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "climate_zone": {"type": "integer"},
            "building_type": {"type": "string"},
            "floor_area_m2": {"type": "number"},
            "annual_heating_kwh": {"type": "number"},
            "annual_cooling_kwh": {"type": "number"},
            "annual_lighting_kwh": {"type": "number"},
            "annual_fan_kwh": {"type": "number"},
            "heating_fuel": {"type": "string"},
            "peak_cooling_kw": {"type": "number"},
            "peak_heating_kw": {"type": "number"},
        },
        "required": [
            "climate_zone", "building_type", "floor_area_m2",
            "annual_heating_kwh", "annual_cooling_kwh",
        ],
    },
}


async def _run_check_title24(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    try:
        # Reconstruct a minimal AnnualResult from the summary values
        from kerf_cad_core.buildingenergy.hourly_8760 import AnnualResult
        annual = AnnualResult(
            hourly=[],
            annual_heating_kwh=float(a["annual_heating_kwh"]),
            annual_cooling_kwh=float(a["annual_cooling_kwh"]),
            annual_fan_kwh=float(a.get("annual_fan_kwh", 0.0)),
            annual_lighting_kwh=float(a.get("annual_lighting_kwh", 0.0)),
            eui_kwh_m2_yr=0.0,
            peak_cooling_kw=float(a.get("peak_cooling_kw", 0.0)),
            peak_heating_kw=float(a.get("peak_heating_kw", 0.0)),
        )
        spec = Title24Spec(
            climate_zone=int(a["climate_zone"]),
            building_type=str(a["building_type"]),
            floor_area_m2=float(a["floor_area_m2"]),
            occupancy_type=str(a.get("building_type", "commercial")),
            heating_fuel=str(a.get("heating_fuel", "gas")),
        )
        report = check_title24_compliance(spec, annual)
    except (ValueError, TypeError, KeyError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    payload = {
        "ok": True,
        "compliant": report.compliant,
        "proposed_tdv_kbtu_m2_yr": report.proposed_tdv,
        "baseline_tdv_kbtu_m2_yr": report.baseline_tdv,
        "margin_pct": report.margin_pct,
        "failures": report.failures,
        "tdv_breakdown": report.tdv_breakdown,
        "honest_caveat": report.honest_caveat,
    }
    if _REGISTRY_AVAILABLE and ok_payload:
        return ok_payload(payload)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tool 3: be_evaluate_leed_eap2
# ---------------------------------------------------------------------------

_SPEC_LEED = {
    "name": "be_evaluate_leed_eap2",
    "description": (
        "Evaluate LEED v4.1 EAp2 (Minimum Energy Performance prerequisite) "
        "and EAc1 (Optimize Energy Performance, 1–18 points).\n"
        "\n"
        "Inputs:\n"
        "  project_type        : 'new_construction'|'major_renovation'|'core_and_shell'|'schools'\n"
        "  proposed_annual_eui : proposed site EUI kWh/(m²·yr) — from be_simulate_8760\n"
        "  baseline_annual_eui : ASHRAE 90.1-2016 Appendix G baseline EUI kWh/(m²·yr)\n"
        "  rating_system       : 'BD+C v4.1' (default) | 'BD+C v4.0'\n"
        "  renewables_offset   : on-site PV generation kWh/(m²·yr) (default 0)\n"
        "\n"
        "Outputs: prerequisite_met, energy_savings_pct, optional_eac1_points, "
        "net_proposed_eui, point_detail.\n"
        "\n"
        "References: USGBC LEED v4.1 BD+C Reference Guide — EA section.\n"
        "Honest flag: screening only — not GBCI-certified submission."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "project_type": {"type": "string"},
            "proposed_annual_eui": {"type": "number"},
            "baseline_annual_eui": {"type": "number"},
            "rating_system": {"type": "string"},
            "renewables_offset": {"type": "number"},
        },
        "required": ["project_type", "proposed_annual_eui", "baseline_annual_eui"],
    },
}


async def _run_evaluate_leed_eap2(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    try:
        spec = LeedEAp2Spec(
            project_type=str(a["project_type"]),
            proposed_annual_eui=float(a["proposed_annual_eui"]),
            baseline_annual_eui=float(a["baseline_annual_eui"]),
            rating_system=str(a.get("rating_system", "BD+C v4.1")),
            renewables_offset_kwh_m2=float(a.get("renewables_offset", 0.0)),
        )
        report = evaluate_leed_v4_eap2(spec)
    except (ValueError, TypeError, KeyError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    payload = {
        "ok": True,
        "prerequisite_met": report.prerequisite_met,
        "energy_savings_pct": report.energy_savings_pct,
        "minimum_threshold_pct": report.minimum_threshold_pct,
        "optional_eac1_points": report.optional_eac1_points,
        "net_proposed_eui": report.net_proposed_eui,
        "point_detail": report.point_detail,
        "honest_caveat": report.honest_caveat,
    }
    if _REGISTRY_AVAILABLE and ok_payload:
        return ok_payload(payload)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tool 4: be_simulate_hvac_plant
# ---------------------------------------------------------------------------

_SPEC_HVAC_PLANT = {
    "name": "be_simulate_hvac_plant",
    "description": (
        "Apply HVAC plant efficiency curves (chiller + boiler) to hourly loads "
        "from be_simulate_8760. Returns annual electricity and gas energy.\n"
        "\n"
        "Inputs:\n"
        "  annual_heating_kwh  : from be_simulate_8760\n"
        "  annual_cooling_kwh  : from be_simulate_8760\n"
        "  annual_fan_kwh      : from be_simulate_8760\n"
        "  floor_area_m2       : for fan sizing (m²)\n"
        "  chiller_capacity_kw : chiller rated capacity (kW)\n"
        "  chiller_cop         : chiller COP at AHRI 550/590 conditions\n"
        "  boiler_capacity_kw  : boiler rated capacity (kW)\n"
        "  boiler_efficiency_pct : boiler thermal efficiency % (e.g. 85)\n"
        "  fan_cfm             : AHU design airflow (CFM, default based on area)\n"
        "  fan_w_per_cfm       : fan power density W/CFM (default 1.25)\n"
        "  has_return_fan      : boolean (default false)\n"
        "  economizer          : 'none'|'integrated'|'differential_drybulb'\n"
        "  climate_mean_c      : mean annual outdoor temp for simulated weather\n"
        "\n"
        "Outputs: annual_electricity_kwh, annual_gas_kwh, annual_gas_therms, "
        "chiller_cop_average, boiler_efficiency_average.\n"
        "\n"
        "References: AHRI 550/590-2023; ASHRAE 90.1-2022 §6.5.3 + §6.8.1.\n"
        "Honest flag: simplified — not full dynamic HVAC simulation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "annual_heating_kwh": {"type": "number"},
            "annual_cooling_kwh": {"type": "number"},
            "annual_fan_kwh": {"type": "number"},
            "floor_area_m2": {"type": "number"},
            "chiller_capacity_kw": {"type": "number"},
            "chiller_cop": {"type": "number"},
            "boiler_capacity_kw": {"type": "number"},
            "boiler_efficiency_pct": {"type": "number"},
            "fan_cfm": {"type": "number"},
            "fan_w_per_cfm": {"type": "number"},
            "has_return_fan": {"type": "boolean"},
            "economizer": {"type": "string"},
            "climate_mean_c": {"type": "number"},
        },
        "required": [
            "annual_heating_kwh", "annual_cooling_kwh",
            "chiller_capacity_kw", "chiller_cop",
            "boiler_capacity_kw", "boiler_efficiency_pct",
        ],
    },
}


async def _run_simulate_hvac_plant(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    try:
        # Reconstruct a minimal AnnualResult to drive the plant model
        from kerf_cad_core.buildingenergy.hourly_8760 import AnnualResult, HourlyResult

        heat_kwh = float(a["annual_heating_kwh"])
        cool_kwh = float(a["annual_cooling_kwh"])
        fan_kwh = float(a.get("annual_fan_kwh", 0.0))
        climate_mean = float(a.get("climate_mean_c", 13.0))

        # Build representative hourly loads (distribute uniformly with seasonal weight)
        import math
        hourly: list = []
        total_h = 0.0
        total_c = 0.0
        total_f = 0.0

        for h in range(8760):
            t_out = (
                climate_mean
                + 10.0 * math.cos(2 * math.pi * h / 8760 + math.pi)
                + 3.0 * math.cos(2 * math.pi * (h % 24) / 24 + math.pi)
            )
            # Fraction for heating / cooling: temperature-based weight
            h_frac = max(0.0, 20.0 - t_out) / (8760 * 5.0)
            c_frac = max(0.0, t_out - 24.0) / (8760 * 3.0)
            f_frac = 1.0 / 8760.0

            h_kw = heat_kwh * h_frac * 8760
            c_kw = cool_kwh * c_frac * 8760
            f_kw = fan_kwh * f_frac

            total_h += h_kw / 8760
            total_c += c_kw / 8760
            total_f += f_kw

            hourly.append(HourlyResult(
                hour=h,
                heating_load_kw=h_kw / 8760,
                cooling_load_kw=c_kw / 8760,
                fan_kw=f_kw,
                indoor_temp_c=22.0,
                indoor_rh_pct=50.0,
                outdoor_temp_c=t_out,
            ))

        annual = AnnualResult(
            hourly=hourly,
            annual_heating_kwh=heat_kwh,
            annual_cooling_kwh=cool_kwh,
            annual_fan_kwh=fan_kwh,
            annual_lighting_kwh=0.0,
            eui_kwh_m2_yr=0.0,
        )

        # Fan sizing: default ~4 CFM/m² if not supplied
        floor_area_m2 = float(a.get("floor_area_m2", 500.0))
        fan_cfm = float(a.get("fan_cfm", floor_area_m2 * 4.0 * 10.7639))  # 4 CFM/ft²

        chiller = ChillerSpec(
            name="Chiller-1",
            rated_capacity_kw=float(a["chiller_capacity_kw"]),
            cop_rated=float(a["chiller_cop"]),
        )
        boiler = BoilerSpec(
            rated_capacity_kw=float(a["boiler_capacity_kw"]),
            efficiency_rated_pct=float(a["boiler_efficiency_pct"]),
        )
        air_side = AirSideSystem(
            cfm_design=fan_cfm,
            fan_power_w_per_cfm=float(a.get("fan_w_per_cfm", 1.25)),
            return_fan_present=bool(a.get("has_return_fan", False)),
            economizer_type=str(a.get("economizer", "none")),
        )

        result = simulate_hvac_plant(annual, chiller, boiler, air_side)

    except (ValueError, TypeError, KeyError) as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    payload = {
        "ok": True,
        "annual_electricity_kwh": result.annual_electricity_kwh,
        "annual_gas_kwh": result.annual_gas_kwh,
        "annual_gas_therms": result.annual_gas_therms,
        "chiller_cop_average": result.chiller_cop_average,
        "boiler_efficiency_average_pct": result.boiler_efficiency_average,
        "honest_caveat": result.honest_caveat,
    }
    if _REGISTRY_AVAILABLE and ok_payload:
        return ok_payload(payload)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Conditional registration
# ---------------------------------------------------------------------------

def _register_all() -> None:
    if not (_REGISTRY_AVAILABLE and ToolSpec and register):
        return

    _tools = [
        (_SPEC_8760, _run_simulate_8760),
        (_SPEC_TITLE24, _run_check_title24),
        (_SPEC_LEED, _run_evaluate_leed_eap2),
        (_SPEC_HVAC_PLANT, _run_simulate_hvac_plant),
    ]
    for spec_def, handler in _tools:
        ts = ToolSpec(
            name=spec_def["name"],
            description=spec_def["description"],
            input_schema=spec_def["input_schema"],
        )

        @register(ts, write=False)
        async def _wrapped(ctx, args: bytes, _h=handler) -> str:  # type: ignore[misc]
            return await _h(ctx, args)


_register_all()


# ---------------------------------------------------------------------------
# Stand-alone (no registry) public aliases for tests
# ---------------------------------------------------------------------------

async def run_be_simulate_8760(ctx: Any, args: bytes) -> str:
    return await _run_simulate_8760(ctx, args)


async def run_be_check_title24(ctx: Any, args: bytes) -> str:
    return await _run_check_title24(ctx, args)


async def run_be_evaluate_leed_eap2(ctx: Any, args: bytes) -> str:
    return await _run_evaluate_leed_eap2(ctx, args)


async def run_be_simulate_hvac_plant(ctx: Any, args: bytes) -> str:
    return await _run_simulate_hvac_plant(ctx, args)
