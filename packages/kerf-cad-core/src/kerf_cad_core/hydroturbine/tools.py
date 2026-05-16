"""
kerf_cad_core.hydroturbine.tools — LLM tool wrappers for hydropower plant engineering.

Registers tools with the Kerf tool registry:

  hydro_plant_power           — P = ρ·g·Q·H·η
  hydro_turbine_type          — select turbine type from head/flow/speed
  hydro_runner_speed          — estimate runner speed from head
  hydro_sync_speed_poles      — synchronous generator speed & pole count
  hydro_penstock_diameter     — economic penstock diameter
  hydro_penstock_friction     — Darcy-Weisbach friction head loss
  hydro_penstock_wall         — penstock wall thickness (Barlow)
  hydro_water_hammer_joukowsky — Joukowsky (rapid closure) pressure rise
  hydro_water_hammer_allievi  — Allievi finite-closure water hammer
  hydro_surge_tank            — simple surge-tank sizing
  hydro_thoma_cavitation      — Thoma sigma cavitation check
  hydro_runaway_speed         — turbine runaway speed estimate
  hydro_flow_duration_energy  — annual energy from flow-duration curve
  hydro_pelton_jet            — Pelton jet and bucket sizing
  hydro_micro_quick           — micro-hydro quick sizing

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Warnick, C.C., "Hydropower Engineering", Prentice-Hall (1984)
IEC 60193:1999 — Hydraulic turbines, storage pumps and pump-turbines
Gordon, J.L. (1999), Can. J. Civ. Eng. 26

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.hydroturbine.plant import (
    plant_power,
    turbine_type_selection,
    runner_speed,
    synchronous_speed_poles,
    penstock_diameter,
    penstock_friction_loss,
    penstock_wall_thickness,
    water_hammer_joukowsky,
    water_hammer_allievi,
    surge_tank_area,
    thoma_cavitation,
    runaway_speed,
    flow_duration_energy,
    pelton_jet_sizing,
    micro_hydro_quick,
)


# ---------------------------------------------------------------------------
# Tool: hydro_plant_power
# ---------------------------------------------------------------------------

_plant_power_spec = ToolSpec(
    name="hydro_plant_power",
    description=(
        "Compute hydropower turbine shaft power and hydraulic power.\n"
        "\n"
        "P_hydraulic = ρ·g·Q·H_net       (W)\n"
        "P_shaft     = ρ·g·Q·H_net·η     (W)\n"
        "\n"
        "Returns P_hydraulic_W, P_shaft_W, P_shaft_kW, P_shaft_MW.\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q": {
                "type": "number",
                "description": "Design flow rate (m³/s). Must be > 0.",
            },
            "H_net": {
                "type": "number",
                "description": "Net head at turbine (m). Must be > 0.",
            },
            "eta": {
                "type": "number",
                "description": (
                    "Overall plant efficiency (turbine × generator), "
                    "0 < η ≤ 1. Default 0.88."
                ),
            },
            "rho": {
                "type": "number",
                "description": "Water density (kg/m³). Default 1000 (fresh water).",
            },
        },
        "required": ["Q", "H_net"],
    },
)


@register(_plant_power_spec, write=False)
async def run_plant_power(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("Q") is None:
        return json.dumps({"ok": False, "reason": "Q is required"})
    if a.get("H_net") is None:
        return json.dumps({"ok": False, "reason": "H_net is required"})
    kwargs: dict = {}
    if "eta" in a:
        kwargs["eta"] = a["eta"]
    if "rho" in a:
        kwargs["rho"] = a["rho"]
    result = plant_power(a["Q"], a["H_net"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_turbine_type
# ---------------------------------------------------------------------------

_turbine_type_spec = ToolSpec(
    name="hydro_turbine_type",
    description=(
        "Select the appropriate turbine type from net head, flow, and "
        "optionally runner speed.\n"
        "\n"
        "Uses the true IEC dimensionless specific speed "
        "Ns = ω·√Q / (g·H)^(3/4) when n_rpm is given; otherwise uses "
        "head-range heuristics.\n"
        "\n"
        "Turbine types: Pelton (high head), Turgo (medium-high), "
        "Crossflow (micro-hydro), Francis (medium), Kaplan (low head, "
        "variable flow), Bulb (tidal/run-of-river).\n"
        "\n"
        "Returns turbine_type, Ns, alternatives, head_range_ok, warnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_net": {
                "type": "number",
                "description": "Net head (m). Must be > 0.",
            },
            "Q": {
                "type": "number",
                "description": "Design flow (m³/s). Must be > 0.",
            },
            "n_rpm": {
                "type": "number",
                "description": "Runner speed (rpm). Optional; enables Ns-based classification.",
            },
            "P_kW": {
                "type": "number",
                "description": "Plant power (kW). Optional, informational only.",
            },
        },
        "required": ["H_net", "Q"],
    },
)


@register(_turbine_type_spec, write=False)
async def run_turbine_type(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("H_net") is None:
        return json.dumps({"ok": False, "reason": "H_net is required"})
    if a.get("Q") is None:
        return json.dumps({"ok": False, "reason": "Q is required"})
    kwargs: dict = {}
    if "n_rpm" in a:
        kwargs["n_rpm"] = a["n_rpm"]
    if "P_kW" in a:
        kwargs["P_kW"] = a["P_kW"]
    result = turbine_type_selection(a["H_net"], a["Q"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_runner_speed
# ---------------------------------------------------------------------------

_runner_speed_spec = ToolSpec(
    name="hydro_runner_speed",
    description=(
        "Estimate turbine runner design speed using the empirical relation "
        "n ≈ K·√H (rpm).\n"
        "\n"
        "K factors (approximate):\n"
        "  Pelton: 30, Turgo: 60, Crossflow: 25, Francis: 50, "
        "Kaplan: 150, Bulb: 200\n"
        "\n"
        "Returns n_rpm_approx and K_used. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_net": {
                "type": "number",
                "description": "Net head (m). Must be > 0.",
            },
            "turbine_type": {
                "type": "string",
                "enum": ["Pelton", "Turgo", "Crossflow", "Francis", "Kaplan", "Bulb"],
                "description": "Turbine type. Default 'Francis'.",
            },
        },
        "required": ["H_net"],
    },
)


@register(_runner_speed_spec, write=False)
async def run_runner_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("H_net") is None:
        return json.dumps({"ok": False, "reason": "H_net is required"})
    kwargs: dict = {}
    if "turbine_type" in a:
        kwargs["turbine_type"] = a["turbine_type"]
    result = runner_speed(a["H_net"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_sync_speed_poles
# ---------------------------------------------------------------------------

_sync_speed_spec = ToolSpec(
    name="hydro_sync_speed_poles",
    description=(
        "Find the nearest synchronous generator speeds and pole counts "
        "for direct-drive or geared coupling.\n"
        "\n"
        "n_sync = 120·f / p  (rpm)  where p is the pole count (even integer ≥ 2).\n"
        "\n"
        "Returns poles_lower, n_sync_lower_rpm (≤ n_runner), "
        "poles_higher, n_sync_higher_rpm (> n_runner). Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_runner_rpm": {
                "type": "number",
                "description": "Runner/turbine speed (rpm). Must be > 0.",
            },
            "f_hz": {
                "type": "number",
                "description": "Grid frequency (Hz). 50 or 60. Default 50.",
            },
        },
        "required": ["n_runner_rpm"],
    },
)


@register(_sync_speed_spec, write=False)
async def run_sync_speed_poles(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("n_runner_rpm") is None:
        return json.dumps({"ok": False, "reason": "n_runner_rpm is required"})
    kwargs: dict = {}
    if "f_hz" in a:
        kwargs["f_hz"] = a["f_hz"]
    result = synchronous_speed_poles(a["n_runner_rpm"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_penstock_diameter
# ---------------------------------------------------------------------------

_penstock_diameter_spec = ToolSpec(
    name="hydro_penstock_diameter",
    description=(
        "Compute the economic penstock diameter from design flow and "
        "target flow velocity.\n"
        "\n"
        "D = √(4·Q / (π·V_economic))\n"
        "\n"
        "Typical economic velocity: 3–5 m/s (steel penstock). "
        "Returns D_m and A_m2. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q": {
                "type": "number",
                "description": "Design flow (m³/s). Must be > 0.",
            },
            "V_economic": {
                "type": "number",
                "description": (
                    "Target flow velocity (m/s). Default 3.0. "
                    "Typical range 2.5–5.0 m/s."
                ),
            },
        },
        "required": ["Q"],
    },
)


@register(_penstock_diameter_spec, write=False)
async def run_penstock_diameter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("Q") is None:
        return json.dumps({"ok": False, "reason": "Q is required"})
    kwargs: dict = {}
    if "V_economic" in a:
        kwargs["V_economic"] = a["V_economic"]
    result = penstock_diameter(a["Q"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_penstock_friction
# ---------------------------------------------------------------------------

_penstock_friction_spec = ToolSpec(
    name="hydro_penstock_friction",
    description=(
        "Compute Darcy-Weisbach friction head loss in the penstock.\n"
        "\n"
        "h_f = f·(L/D)·(V²/2g)   where V = Q/A\n"
        "\n"
        "Returns h_f_m, V_m_s, Re_approx. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q": {"type": "number", "description": "Flow rate (m³/s). Must be > 0."},
            "D": {"type": "number", "description": "Internal pipe diameter (m). Must be > 0."},
            "L": {"type": "number", "description": "Penstock length (m). Must be > 0."},
            "f": {
                "type": "number",
                "description": (
                    "Darcy friction factor (dimensionless). "
                    "Default 0.015 (smooth steel). Must be > 0."
                ),
            },
        },
        "required": ["Q", "D", "L"],
    },
)


@register(_penstock_friction_spec, write=False)
async def run_penstock_friction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("Q", "D", "L"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    if "f" in a:
        kwargs["f"] = a["f"]
    result = penstock_friction_loss(a["Q"], a["D"], a["L"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_penstock_wall
# ---------------------------------------------------------------------------

_penstock_wall_spec = ToolSpec(
    name="hydro_penstock_wall",
    description=(
        "Compute minimum penstock wall thickness using the thin-wall "
        "(Barlow) pressure formula.\n"
        "\n"
        "t = P·D / (2·σ_allow·e) + corrosion_allowance\n"
        "\n"
        "Use the maximum internal pressure = P_static + water-hammer ΔP. "
        "Returns t_calc_mm and t_total_mm. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "D": {"type": "number", "description": "Internal pipe diameter (m). Must be > 0."},
            "P_internal_Pa": {
                "type": "number",
                "description": (
                    "Design internal pressure (Pa). Must be > 0. "
                    "Include water-hammer allowance: P = ρ·g·(H_static + ΔH_wh)."
                ),
            },
            "sigma_allow_Pa": {
                "type": "number",
                "description": (
                    "Allowable hoop stress (Pa). Default 120 MPa (mild steel A36). "
                    "Increase for higher-grade steel."
                ),
            },
            "weld_efficiency": {
                "type": "number",
                "description": "Longitudinal weld joint efficiency. Default 0.85.",
            },
            "corrosion_mm": {
                "type": "number",
                "description": "Corrosion allowance (mm). Default 2.0 mm.",
            },
        },
        "required": ["D", "P_internal_Pa"],
    },
)


@register(_penstock_wall_spec, write=False)
async def run_penstock_wall(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("D", "P_internal_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    if "sigma_allow_Pa" in a:
        kwargs["sigma_allow_Pa"] = a["sigma_allow_Pa"]
    if "weld_efficiency" in a:
        kwargs["weld_efficiency"] = a["weld_efficiency"]
    if "corrosion_mm" in a:
        kwargs["corrosion_mm"] = a["corrosion_mm"]
    result = penstock_wall_thickness(a["D"], a["P_internal_Pa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_water_hammer_joukowsky
# ---------------------------------------------------------------------------

_joukowsky_spec = ToolSpec(
    name="hydro_water_hammer_joukowsky",
    description=(
        "Compute Joukowsky water-hammer pressure rise for rapid (instantaneous) "
        "valve closure.\n"
        "\n"
        "ΔP = ρ·a·ΔV   (full velocity change ΔV = V for complete closure)\n"
        "\n"
        "Wave speed a ≈ 1200 m/s (steel penstock), ≈ 300 m/s (HDPE). "
        "Returns dP_Pa, dP_bar, dH_m. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V": {"type": "number", "description": "Initial flow velocity (m/s). Must be > 0."},
            "a_wave": {
                "type": "number",
                "description": (
                    "Acoustic wave speed (m/s). Must be > 0. "
                    "Steel penstock ≈ 1200 m/s; HDPE ≈ 300 m/s."
                ),
            },
            "rho": {
                "type": "number",
                "description": "Water density (kg/m³). Default 1000.",
            },
        },
        "required": ["V", "a_wave"],
    },
)


@register(_joukowsky_spec, write=False)
async def run_water_hammer_joukowsky(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("V", "a_wave"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    if "rho" in a:
        kwargs["rho"] = a["rho"]
    result = water_hammer_joukowsky(a["V"], a["a_wave"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_water_hammer_allievi
# ---------------------------------------------------------------------------

_allievi_spec = ToolSpec(
    name="hydro_water_hammer_allievi",
    description=(
        "Allievi water-hammer analysis for finite valve closure time.\n"
        "\n"
        "Slow closure (T_close > 2L/a): ΔH = 2·L·V / (g·T_close)  [Michaud]\n"
        "Rapid closure (T_close ≤ 2L/a): ΔH = a·V / g              [Joukowsky]\n"
        "\n"
        "Returns T_critical_s, regime ('slow' or 'rapid'), dH_max_m, "
        "H_total_max_m, overpressure_ratio. Flags overpressure > 50% in warnings. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_static": {"type": "number", "description": "Static head (m). Must be > 0."},
            "V": {"type": "number", "description": "Initial flow velocity (m/s). Must be > 0."},
            "a_wave": {"type": "number", "description": "Wave speed (m/s). Must be > 0."},
            "L": {"type": "number", "description": "Penstock length (m). Must be > 0."},
            "T_close": {"type": "number", "description": "Valve closure time (s). Must be > 0."},
            "rho": {"type": "number", "description": "Water density (kg/m³). Default 1000."},
        },
        "required": ["H_static", "V", "a_wave", "L", "T_close"],
    },
)


@register(_allievi_spec, write=False)
async def run_water_hammer_allievi(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("H_static", "V", "a_wave", "L", "T_close"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    if "rho" in a:
        kwargs["rho"] = a["rho"]
    result = water_hammer_allievi(
        a["H_static"], a["V"], a["a_wave"], a["L"], a["T_close"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_surge_tank
# ---------------------------------------------------------------------------

_surge_tank_spec = ToolSpec(
    name="hydro_surge_tank",
    description=(
        "Size a simple cylindrical surge tank using the Thoma stability "
        "criterion.\n"
        "\n"
        "A_Thoma = A_pipe·L / (2·H_friction_effective)\n"
        "\n"
        "Also computes the natural oscillation period. "
        "If max_upsurge_m is given, an energy-balance area is also returned. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q": {"type": "number", "description": "Design flow (m³/s). Must be > 0."},
            "a_wave": {"type": "number", "description": "Wave speed (m/s). Must be > 0."},
            "L": {"type": "number", "description": "Penstock/tunnel length (m). Must be > 0."},
            "H_net": {"type": "number", "description": "Net head (m). Must be > 0."},
            "D_penstock": {
                "type": "number",
                "description": "Penstock internal diameter (m). Must be > 0.",
            },
            "max_upsurge_m": {
                "type": "number",
                "description": (
                    "Allowable upsurge above reservoir level (m). Optional. "
                    "Enables energy-balance area calculation."
                ),
            },
        },
        "required": ["Q", "a_wave", "L", "H_net", "D_penstock"],
    },
)


@register(_surge_tank_spec, write=False)
async def run_surge_tank(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("Q", "a_wave", "L", "H_net", "D_penstock"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    if "max_upsurge_m" in a:
        kwargs["max_upsurge_m"] = a["max_upsurge_m"]
    result = surge_tank_area(
        a["Q"], a["a_wave"], a["L"], a["H_net"], a["D_penstock"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_thoma_cavitation
# ---------------------------------------------------------------------------

_thoma_cavitation_spec = ToolSpec(
    name="hydro_thoma_cavitation",
    description=(
        "Thoma cavitation analysis for hydropower turbines.\n"
        "\n"
        "σ_plant = (H_atm − H_vapor − H_s) / H_net\n"
        "\n"
        "Compares σ_plant to σ_crit (empirical, Gordon 1999).\n"
        "Flags cavitation risk if σ_plant < σ_crit.\n"
        "\n"
        "H_s is the draft head: positive = runner above tailwater (suction lift). "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_net": {"type": "number", "description": "Net head (m). Must be > 0."},
            "H_s": {
                "type": "number",
                "description": (
                    "Draft head / setting height (m). "
                    "Positive = runner above tailwater; negative = submerged."
                ),
            },
            "turbine_type": {
                "type": "string",
                "enum": ["Pelton", "Turgo", "Crossflow", "Francis", "Kaplan", "Bulb"],
                "description": "Turbine type. Default 'Francis'.",
            },
            "n_rpm": {
                "type": "number",
                "description": (
                    "Runner speed (rpm). Optional; used with Q for Ns-based σ_crit."
                ),
            },
            "Q": {
                "type": "number",
                "description": "Design flow (m³/s). Optional; used with n_rpm.",
            },
            "P_vapor_Pa": {
                "type": "number",
                "description": "Vapour pressure (Pa). Default 2338 (water 20°C).",
            },
            "P_atm_Pa": {
                "type": "number",
                "description": "Atmospheric pressure at site (Pa). Default 101325.",
            },
            "rho": {
                "type": "number",
                "description": "Water density (kg/m³). Default 1000.",
            },
            "elevation_m": {
                "type": "number",
                "description": "Site elevation above sea level (m). Adjusts P_atm. Default 0.",
            },
        },
        "required": ["H_net", "H_s"],
    },
)


@register(_thoma_cavitation_spec, write=False)
async def run_thoma_cavitation(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("H_net", "H_s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("turbine_type", "n_rpm", "Q", "P_vapor_Pa", "P_atm_Pa", "rho", "elevation_m"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = thoma_cavitation(a["H_net"], a["H_s"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_runaway_speed
# ---------------------------------------------------------------------------

_runaway_speed_spec = ToolSpec(
    name="hydro_runaway_speed",
    description=(
        "Estimate turbine runaway (load-rejection, no-load) speed.\n"
        "\n"
        "Empirical multipliers (Warnick 1984):\n"
        "  Pelton: 1.8×, Turgo: 1.8×, Crossflow: 1.9×,\n"
        "  Francis: 1.8×, Kaplan: 2.3×, Bulb: 2.2×\n"
        "\n"
        "All rotating components must be rated for this speed. "
        "Returns n_runaway_rpm and runaway_factor. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_rpm": {
                "type": "number",
                "description": "Rated runner speed (rpm). Must be > 0.",
            },
            "turbine_type": {
                "type": "string",
                "enum": ["Pelton", "Turgo", "Crossflow", "Francis", "Kaplan", "Bulb"],
                "description": "Turbine type. Default 'Francis'.",
            },
        },
        "required": ["n_rpm"],
    },
)


@register(_runaway_speed_spec, write=False)
async def run_runaway_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("n_rpm") is None:
        return json.dumps({"ok": False, "reason": "n_rpm is required"})
    kwargs: dict = {}
    if "turbine_type" in a:
        kwargs["turbine_type"] = a["turbine_type"]
    result = runaway_speed(a["n_rpm"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_flow_duration_energy
# ---------------------------------------------------------------------------

_flow_duration_spec = ToolSpec(
    name="hydro_flow_duration_energy",
    description=(
        "Compute annual energy from a discretised flow-duration curve (FDC).\n"
        "\n"
        "Supply a list of flow fractions (Q_i / Q_design) for equal time "
        "intervals covering one year. Flows above design are capped (spill); "
        "flows ≤ 0 produce no power.\n"
        "\n"
        "Returns E_annual_MWh, capacity_factor, plant_factor, hours_generating, "
        "spill_fraction. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "flow_fractions": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "List of Q_i/Q_design values for equal time steps. "
                    "At least 2 values. Values > 1.0 are capped (excess spill)."
                ),
                "minItems": 2,
            },
            "Q_design": {
                "type": "number",
                "description": "Design (installed) flow (m³/s). Must be > 0.",
            },
            "H_net": {
                "type": "number",
                "description": "Net head (m), assumed constant. Must be > 0.",
            },
            "eta": {
                "type": "number",
                "description": "Overall efficiency. Default 0.88.",
            },
            "rho": {
                "type": "number",
                "description": "Water density (kg/m³). Default 1000.",
            },
            "hours_per_year": {
                "type": "number",
                "description": "Hours per year. Default 8760.",
            },
        },
        "required": ["flow_fractions", "Q_design", "H_net"],
    },
)


@register(_flow_duration_spec, write=False)
async def run_flow_duration_energy(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("flow_fractions", "Q_design", "H_net"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("eta", "rho", "hours_per_year"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = flow_duration_energy(a["flow_fractions"], a["Q_design"], a["H_net"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_pelton_jet
# ---------------------------------------------------------------------------

_pelton_jet_spec = ToolSpec(
    name="hydro_pelton_jet",
    description=(
        "Size Pelton turbine jets and buckets.\n"
        "\n"
        "V_jet = Cv·√(2·g·H_net)    d_jet = √(4·Q / (n_jets·π·V_jet))\n"
        "B_bucket ≈ 3.2·d_jet       u_opt = 0.46·V_jet\n"
        "\n"
        "Optimal runner tangential speed u_opt ≈ 0.46·V_jet. "
        "If D_runner_m is given, the optimal n_rpm is also returned. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_net": {"type": "number", "description": "Net head (m). Must be > 0."},
            "Q": {"type": "number", "description": "Total flow (m³/s). Must be > 0."},
            "n_jets": {
                "type": "integer",
                "description": "Number of jets. Default 1. Range 1–6.",
            },
            "Cv": {
                "type": "number",
                "description": "Jet velocity coefficient. Default 0.97.",
            },
            "D_runner_m": {
                "type": "number",
                "description": "Runner pitch diameter (m). Optional; enables n_opt_rpm.",
            },
            "rho": {
                "type": "number",
                "description": "Water density (kg/m³). Default 1000.",
            },
        },
        "required": ["H_net", "Q"],
    },
)


@register(_pelton_jet_spec, write=False)
async def run_pelton_jet(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("H_net", "Q"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("n_jets", "Cv", "D_runner_m", "rho"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = pelton_jet_sizing(a["H_net"], a["Q"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: hydro_micro_quick
# ---------------------------------------------------------------------------

_micro_quick_spec = ToolSpec(
    name="hydro_micro_quick",
    description=(
        "Quick-sizing utility for micro-hydro plants (target < 100 kW).\n"
        "\n"
        "Given gross head and design flow, automatically sizes the penstock "
        "(economic velocity 2.5 m/s), estimates friction loss, computes net "
        "head and shaft power, and recommends a turbine type.\n"
        "\n"
        "Returns H_net_m, P_shaft_kW, turbine_type, D_penstock_m. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_gross": {
                "type": "number",
                "description": "Gross (total available) head (m). Must be > 0.",
            },
            "Q": {
                "type": "number",
                "description": "Design flow (m³/s). Must be > 0.",
            },
            "penstock_length": {
                "type": "number",
                "description": "Penstock length (m). Default 0 (neglects friction).",
            },
            "eta_overall": {
                "type": "number",
                "description": (
                    "Overall efficiency (turbine + generator + transmission). "
                    "Default 0.70 for micro-hydro."
                ),
            },
            "penstock_D": {
                "type": "number",
                "description": "Penstock internal diameter (m). Optional; auto-sized if omitted.",
            },
            "rho": {
                "type": "number",
                "description": "Water density (kg/m³). Default 1000.",
            },
        },
        "required": ["H_gross", "Q"],
    },
)


@register(_micro_quick_spec, write=False)
async def run_micro_quick(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("H_gross", "Q"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("penstock_length", "eta_overall", "penstock_D", "rho"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = micro_hydro_quick(a["H_gross"], a["Q"], **kwargs)
    return ok_payload(result)
