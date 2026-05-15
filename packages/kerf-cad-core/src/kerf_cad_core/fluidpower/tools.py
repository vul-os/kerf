"""
kerf_cad_core.fluidpower.tools — LLM tool wrappers for hydraulic fluid-power
circuit sizing.

Registers nine tools with the Kerf tool registry:

  fp_cylinder           — extend/retract force & velocity; regeneration mode
  fp_pump               — pump flow, input power and torque from displacement
  fp_motor              — motor output torque and speed from displacement
  fp_accumulator        — gas pre-charge sizing (Boyle / adiabatic)
  fp_valve_cv           — valve Cv / Kv flow-coefficient sizing
  fp_line_pressure_drop — Hagen-Poiseuille (laminar) / Darcy-Weisbach (turbulent)
  fp_line_size          — recommended bore from ISO velocity limits
  fp_reservoir          — reservoir volume rule-of-thumb
  fp_thermal_balance    — steady-state heat load and heat-exchanger check

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Vickers Industrial Hydraulics Manual (4th ed.)
Parker Hannifin Hydraulic Systems Design Guide
ISO 4399 — Hydraulic fluid power; Terminology

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.fluidpower.circuit import (
    cylinder,
    pump,
    motor,
    accumulator,
    valve_cv,
    line_pressure_drop,
    line_size,
    reservoir,
    thermal_balance,
)


# ---------------------------------------------------------------------------
# Tool: fp_cylinder
# ---------------------------------------------------------------------------

_fp_cylinder_spec = ToolSpec(
    name="fp_cylinder",
    description=(
        "Compute hydraulic cylinder extend/retract force and velocity from bore "
        "diameter, rod diameter, supply pressure and flow rate. Optionally "
        "compute regenerative (regen) extend mode where bore-side return oil is "
        "routed back to the inlet, increasing extend speed at reduced force.\n"
        "\n"
        "Returns:\n"
        "  F_extend_N, F_retract_N — extend and retract forces (N)\n"
        "  v_extend_ms, v_retract_ms — velocities (m/s)\n"
        "  F_regen_N, v_regen_ms — regenerative mode force and velocity\n"
        "  A_bore_m2, A_rod_m2 — piston and annulus areas (m²)\n"
        "  warnings — list of cavitation/under-sizing flags\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bore_m": {
                "type": "number",
                "description": "Cylinder bore diameter (m). Must be > 0.",
            },
            "rod_m": {
                "type": "number",
                "description": "Piston rod diameter (m). Must be > 0 and < bore_m.",
            },
            "pressure_Pa": {
                "type": "number",
                "description": "Supply pressure (Pa). Must be > 0.",
            },
            "flow_m3s": {
                "type": "number",
                "description": "Supply flow rate (m³/s). Must be > 0.",
            },
            "regen": {
                "type": "boolean",
                "description": (
                    "True to compute regenerative extend mode "
                    "(bore-side return oil routed to inlet). Default false."
                ),
            },
        },
        "required": ["bore_m", "rod_m", "pressure_Pa", "flow_m3s"],
    },
)


@register(_fp_cylinder_spec, write=False)
async def run_fp_cylinder(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("bore_m", "rod_m", "pressure_Pa", "flow_m3s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "regen" in a:
        kwargs["regen"] = bool(a["regen"])

    result = cylinder(
        a["bore_m"], a["rod_m"], a["pressure_Pa"], a["flow_m3s"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_pump
# ---------------------------------------------------------------------------

_fp_pump_spec = ToolSpec(
    name="fp_pump",
    description=(
        "Size a hydraulic pump: compute actual flow output and required shaft "
        "input power from displacement, speed, volumetric efficiency, overall "
        "efficiency, and supply pressure.\n"
        "\n"
        "  Q_actual = displacement × (rpm/60) × vol_eff\n"
        "  P_input  = pressure × Q_actual / overall_eff\n"
        "  T_input  = displacement × pressure / (2π × mech_eff)\n"
        "\n"
        "Returns Q_theoretical_m3s, Q_actual_m3s, P_hydraulic_W, P_input_W, "
        "T_input_Nm, mech_eff, plus warnings for low-efficiency conditions.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "displacement_m3": {
                "type": "number",
                "description": "Pump displacement per revolution (m³/rev). Must be > 0.",
            },
            "rpm": {
                "type": "number",
                "description": "Shaft speed (rpm). Must be > 0.",
            },
            "vol_eff": {
                "type": "number",
                "description": (
                    "Volumetric efficiency (0, 1]. Typical 0.85–0.98. "
                    "Warning issued if < 0.80."
                ),
            },
            "overall_eff": {
                "type": "number",
                "description": (
                    "Overall pump efficiency (0, 1]. Typical 0.80–0.92. "
                    "Warning issued if < 0.75."
                ),
            },
            "pressure_Pa": {
                "type": "number",
                "description": "System supply pressure (Pa). Must be > 0.",
            },
        },
        "required": ["displacement_m3", "rpm", "vol_eff", "overall_eff", "pressure_Pa"],
    },
)


@register(_fp_pump_spec, write=False)
async def run_fp_pump(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("displacement_m3", "rpm", "vol_eff", "overall_eff", "pressure_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = pump(
        a["displacement_m3"],
        a["rpm"],
        a["vol_eff"],
        a["overall_eff"],
        a["pressure_Pa"],
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_motor
# ---------------------------------------------------------------------------

_fp_motor_spec = ToolSpec(
    name="fp_motor",
    description=(
        "Compute hydraulic motor output torque and shaft speed from displacement, "
        "differential pressure, and desired rpm, accounting for mechanical and "
        "volumetric efficiencies.\n"
        "\n"
        "  T_output = displacement × ΔP × mech_eff / (2π)\n"
        "  Q_actual = displacement × (rpm/60) / vol_eff  (flow consumed)\n"
        "\n"
        "Returns T_theoretical_Nm, T_output_Nm, Q_theoretical_m3s, Q_actual_m3s, "
        "omega_rad_s, P_output_W.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "displacement_m3": {
                "type": "number",
                "description": "Motor displacement per revolution (m³/rev). Must be > 0.",
            },
            "pressure_Pa": {
                "type": "number",
                "description": "Differential pressure across motor (Pa). Must be > 0.",
            },
            "rpm": {
                "type": "number",
                "description": "Desired output shaft speed (rpm). Must be > 0.",
            },
            "mech_eff": {
                "type": "number",
                "description": (
                    "Mechanical efficiency (0, 1]. Default 0.92. "
                    "Warning if < 0.85."
                ),
            },
            "vol_eff": {
                "type": "number",
                "description": "Volumetric efficiency (0, 1]. Default 0.95.",
            },
        },
        "required": ["displacement_m3", "pressure_Pa", "rpm"],
    },
)


@register(_fp_motor_spec, write=False)
async def run_fp_motor(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("displacement_m3", "pressure_Pa", "rpm"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "mech_eff" in a:
        kwargs["mech_eff"] = a["mech_eff"]
    if "vol_eff" in a:
        kwargs["vol_eff"] = a["vol_eff"]

    result = motor(a["displacement_m3"], a["pressure_Pa"], a["rpm"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_accumulator
# ---------------------------------------------------------------------------

_fp_accumulator_spec = ToolSpec(
    name="fp_accumulator",
    description=(
        "Size a gas-charged bladder/piston accumulator using Boyle's Law "
        "(isothermal, slow cycling) or the adiabatic polytropic law (n=1.4, "
        "fast cycling).\n"
        "\n"
        "  P1 = gas pre-charge pressure (must be <= 0.90 × P2)\n"
        "  P2 = minimum system working pressure\n"
        "  P3 = maximum system pressure\n"
        "\n"
        "Usable volume:\n"
        "  ΔV = V_total × [(P1/P2)^(1/n) − (P1/P3)^(1/n)]\n"
        "  where n=1.0 (isothermal) or n=1.4 (adiabatic)\n"
        "\n"
        "Returns delta_V_m3, delta_V_L, V_gas_at_P2_m3, V_gas_at_P3_m3, "
        "precharge_ratio, precharge_ok, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V_total_m3": {
                "type": "number",
                "description": "Total accumulator shell volume (m³). Must be > 0.",
            },
            "P1_Pa": {
                "type": "number",
                "description": (
                    "Gas pre-charge pressure (Pa). "
                    "Recommended P1 <= 0.9 × P2. Must be > 0."
                ),
            },
            "P2_Pa": {
                "type": "number",
                "description": "Minimum system working pressure (Pa). Must be > P1.",
            },
            "P3_Pa": {
                "type": "number",
                "description": "Maximum system pressure (Pa). Must be > P2.",
            },
            "process": {
                "type": "string",
                "enum": ["isothermal", "adiabatic"],
                "description": (
                    "'isothermal' (Boyle, n=1, default — slow cycling) or "
                    "'adiabatic' (isentropic, n=1.4 — fast cycling)."
                ),
            },
        },
        "required": ["V_total_m3", "P1_Pa", "P2_Pa", "P3_Pa"],
    },
)


@register(_fp_accumulator_spec, write=False)
async def run_fp_accumulator(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("V_total_m3", "P1_Pa", "P2_Pa", "P3_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "process" in a:
        kwargs["process"] = a["process"]

    result = accumulator(a["V_total_m3"], a["P1_Pa"], a["P2_Pa"], a["P3_Pa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_valve_cv
# ---------------------------------------------------------------------------

_fp_valve_cv_spec = ToolSpec(
    name="fp_valve_cv",
    description=(
        "Compute valve flow coefficient Cv (US) or Kv (metric ISO) from flow "
        "rate, pressure drop across the valve, and fluid specific gravity.\n"
        "\n"
        "  Cv [gpm/√psi] = Q_gpm / √(ΔP_psi / SG)\n"
        "  Kv [m³/h / √bar] = Q_m3h / √(ΔP_bar / SG)\n"
        "  Relation: Cv ≈ Kv × 1.156\n"
        "\n"
        "Use to select a valve from a manufacturer's Cv/Kv catalogue, or to "
        "predict the actual ΔP across an existing valve at a given flow.\n"
        "\n"
        "Returns Cv, Kv, converted flow and pressure-drop values, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_m3s": {
                "type": "number",
                "description": "Volumetric flow rate (m³/s). Must be > 0.",
            },
            "delta_P_Pa": {
                "type": "number",
                "description": "Pressure drop across fully-open valve (Pa). Must be > 0.",
            },
            "SG": {
                "type": "number",
                "description": (
                    "Specific gravity relative to water. "
                    "Typical mineral oil: 0.87. Must be > 0."
                ),
            },
            "metric": {
                "type": "boolean",
                "description": (
                    "True → report primary result as Kv (m³/h, bar); "
                    "False (default) → Cv (gpm, psi). Both are always returned."
                ),
            },
        },
        "required": ["Q_m3s", "delta_P_Pa", "SG"],
    },
)


@register(_fp_valve_cv_spec, write=False)
async def run_fp_valve_cv(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_m3s", "delta_P_Pa", "SG"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "metric" in a:
        kwargs["metric"] = bool(a["metric"])

    result = valve_cv(a["Q_m3s"], a["delta_P_Pa"], a["SG"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_line_pressure_drop
# ---------------------------------------------------------------------------

_fp_line_pressure_drop_spec = ToolSpec(
    name="fp_line_pressure_drop",
    description=(
        "Compute hydraulic line pressure drop using Hagen-Poiseuille for laminar "
        "flow (Re < 2300) or Darcy-Weisbach with Swamee-Jain friction factor for "
        "turbulent flow. Fittings can be added as equivalent length.\n"
        "\n"
        "Returns velocity_ms, Re, regime ('laminar'/'turbulent'), f_darcy, "
        "delta_P_Pa, delta_P_bar, L_total_m, plus over-velocity warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_m3s": {
                "type": "number",
                "description": "Volumetric flow rate (m³/s). Must be > 0.",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Must be > 0. Mineral oil ≈ 870.",
            },
            "mu": {
                "type": "number",
                "description": (
                    "Dynamic viscosity (Pa·s). Must be > 0. "
                    "ISO VG46 at 40°C ≈ 0.046 Pa·s."
                ),
            },
            "D_i_m": {
                "type": "number",
                "description": "Internal pipe/hose diameter (m). Must be > 0.",
            },
            "L_m": {
                "type": "number",
                "description": "Pipe length (m). Must be > 0.",
            },
            "roughness_m": {
                "type": "number",
                "description": (
                    "Absolute wall roughness (m). Default 4.6e-5 (commercial steel). "
                    "Use 0 for smooth hose/tubing."
                ),
            },
            "fittings_Le_m": {
                "type": "number",
                "description": (
                    "Total equivalent length of fittings (m). Default 0. "
                    "Added to pipe length before computing ΔP."
                ),
            },
        },
        "required": ["Q_m3s", "rho", "mu", "D_i_m", "L_m"],
    },
)


@register(_fp_line_pressure_drop_spec, write=False)
async def run_fp_line_pressure_drop(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_m3s", "rho", "mu", "D_i_m", "L_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "roughness_m" in a:
        kwargs["roughness_m"] = a["roughness_m"]
    if "fittings_Le_m" in a:
        kwargs["fittings_Le_m"] = a["fittings_Le_m"]

    result = line_pressure_drop(
        a["Q_m3s"], a["rho"], a["mu"], a["D_i_m"], a["L_m"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_line_size
# ---------------------------------------------------------------------------

_fp_line_size_spec = ToolSpec(
    name="fp_line_size",
    description=(
        "Recommend minimum hydraulic line bore diameter from ISO/Parker velocity "
        "limits for the given service type.\n"
        "\n"
        "Velocity limits:\n"
        "  suction  lines: 0.5 – 1.5 m/s  (exceeding risks pump cavitation)\n"
        "  return   lines: 2.0 – 4.0 m/s\n"
        "  pressure lines: 3.0 – 6.0 m/s\n"
        "\n"
        "Returns D_min_m, D_min_mm (for v_max), D_rec_m, D_rec_mm (at midpoint "
        "velocity), Re_at_D_rec, regime_at_D_rec, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_m3s": {
                "type": "number",
                "description": "Flow rate (m³/s). Must be > 0.",
            },
            "service": {
                "type": "string",
                "enum": ["suction", "return", "pressure"],
                "description": (
                    "Line service: 'suction', 'return', or 'pressure' (default)."
                ),
            },
            "fluid_rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Default 870.",
            },
            "fluid_mu": {
                "type": "number",
                "description": "Dynamic viscosity (Pa·s). Default 0.046 (ISO VG46 at 40°C).",
            },
        },
        "required": ["Q_m3s"],
    },
)


@register(_fp_line_size_spec, write=False)
async def run_fp_line_size(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Q_m3s") is None:
        return json.dumps({"ok": False, "reason": "Q_m3s is required"})

    kwargs: dict = {}
    if "service" in a:
        kwargs["service"] = a["service"]
    if "fluid_rho" in a:
        kwargs["fluid_rho"] = a["fluid_rho"]
    if "fluid_mu" in a:
        kwargs["fluid_mu"] = a["fluid_mu"]

    result = line_size(a["Q_m3s"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_reservoir
# ---------------------------------------------------------------------------

_fp_reservoir_spec = ToolSpec(
    name="fp_reservoir",
    description=(
        "Compute a rule-of-thumb hydraulic reservoir volume.\n"
        "\n"
        "  V_reservoir = rule_factor × Q_pump_per_minute\n"
        "\n"
        "Typical rule_factor values:\n"
        "  3  — standard industrial (default, Vickers manual)\n"
        "  5  — high-duty or contamination-sensitive\n"
        "  1  — compact mobile systems (minimum)\n"
        "\n"
        "Returns V_reservoir_m3, V_reservoir_L, pump_flow_Lmin, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pump_flow_m3s": {
                "type": "number",
                "description": "Total pump flow rate (m³/s). Must be > 0.",
            },
            "rule_factor": {
                "type": "number",
                "description": (
                    "Multiplier on flow-per-minute. Default 3.0. Must be > 0."
                ),
            },
        },
        "required": ["pump_flow_m3s"],
    },
)


@register(_fp_reservoir_spec, write=False)
async def run_fp_reservoir(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("pump_flow_m3s") is None:
        return json.dumps({"ok": False, "reason": "pump_flow_m3s is required"})

    kwargs: dict = {}
    if "rule_factor" in a:
        kwargs["rule_factor"] = a["rule_factor"]

    result = reservoir(a["pump_flow_m3s"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: fp_thermal_balance
# ---------------------------------------------------------------------------

_fp_thermal_balance_spec = ToolSpec(
    name="fp_thermal_balance",
    description=(
        "Compute hydraulic system steady-state heat load and check thermal "
        "balance against reservoir surface cooling and an optional auxiliary "
        "heat exchanger.\n"
        "\n"
        "  Q_heat   = P_input × (1 - η_overall)\n"
        "  Q_surface = U × A × ΔT\n"
        "  Q_cooler  = ρ × Q_cool × cp × ΔT\n"
        "  Balanced when Q_heat ≤ Q_surface + Q_cooler\n"
        "\n"
        "Returns Q_heat_W, Q_surface_W, Q_cooler_W, Q_total_dissipated_W, "
        "thermal_balanced, heat_surplus_W, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "input_power_W": {
                "type": "number",
                "description": "Pump shaft input power (W). Must be > 0.",
            },
            "eff_overall": {
                "type": "number",
                "description": (
                    "Overall system efficiency (0, 1]. "
                    "Losses = input_power × (1 - eff_overall). "
                    "Warning if < 0.70."
                ),
            },
            "area_m2": {
                "type": "number",
                "description": (
                    "Reservoir surface area for natural convection cooling (m²). "
                    "Omit to skip surface-cooling contribution."
                ),
            },
            "U_Wm2K": {
                "type": "number",
                "description": (
                    "Overall heat-transfer coefficient for reservoir surface "
                    "(W/(m²·K)). Default 10 W/(m²·K) (unpainted steel, still air)."
                ),
            },
            "dT_K": {
                "type": "number",
                "description": (
                    "Temperature rise above ambient (K). Default 40 K. "
                    "Warning if > 60 K."
                ),
            },
            "cooling_flow_m3s": {
                "type": "number",
                "description": (
                    "Auxiliary cooler fluid flow rate (m³/s). "
                    "Omit to skip heat-exchanger contribution."
                ),
            },
            "fluid_cp": {
                "type": "number",
                "description": (
                    "Specific heat of cooler fluid J/(kg·K). "
                    "Default 1880 (mineral oil)."
                ),
            },
            "fluid_rho": {
                "type": "number",
                "description": "Cooler fluid density (kg/m³). Default 870.",
            },
        },
        "required": ["input_power_W", "eff_overall"],
    },
)


@register(_fp_thermal_balance_spec, write=False)
async def run_fp_thermal_balance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("input_power_W", "eff_overall"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("area_m2", "U_Wm2K", "dT_K", "cooling_flow_m3s", "fluid_cp", "fluid_rho"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = thermal_balance(a["input_power_W"], a["eff_overall"], **kwargs)
    return ok_payload(result)
