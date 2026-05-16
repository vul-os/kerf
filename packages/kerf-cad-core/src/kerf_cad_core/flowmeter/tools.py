"""
kerf_cad_core.flowmeter.tools — LLM tool wrappers for flow metering & sizing.

Registers tools with the Kerf tool registry:

  dp_meter              — ISO 5167 differential-pressure orifice/venturi/nozzle
  control_valve_liquid  — ISA/IEC Cv & Kv for liquid service
  control_valve_gas     — ISA/IEC Cv & Kv for gas service
  control_valve_steam   — ISA/IEC Cv for steam service
  prv_gas               — API 520 gas/vapour PRV orifice area
  prv_liquid            — API 520 liquid PRV orifice area
  prv_steam             — API 520 steam PRV (Napier) orifice area
  pitot_velocity        — pitot-tube velocity
  annubar_flow          — annubar multi-port averaging pitot flow
  v_notch_weir          — ISO 1438 V-notch weir open-channel flow
  rectangular_weir      — rectangular sharp-crested weir flow
  parshall_flume        — Parshall flume free-flow equation
  rotameter_scale       — rotameter density correction
  turndown_ratio        — meter turndown ratio

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ISO 5167-1/2/3:2003
ISA-75.01.01-2007 / IEC 60534-2-1:2011
API 520 Part I (9th ed. 2014); API 526 (7th ed. 2017)

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.flowmeter.measure import (
    dp_meter,
    control_valve_liquid,
    control_valve_gas,
    control_valve_steam,
    prv_gas,
    prv_liquid,
    prv_steam,
    pitot_velocity,
    annubar_flow,
    v_notch_weir,
    rectangular_weir,
    parshall_flume,
    rotameter_scale,
    turndown_ratio,
)


# ---------------------------------------------------------------------------
# Tool: dp_meter
# ---------------------------------------------------------------------------

_dp_meter_spec = ToolSpec(
    name="dp_meter",
    description=(
        "ISO 5167 differential-pressure flow meter calculation.\n"
        "\n"
        "Supports orifice plate (Reader-Harris/Gallagher iterative Cd), "
        "venturi tube, and ISA nozzle.\n"
        "Returns mass flow (kg/s), volume flow (m³/s), discharge coefficient, "
        "Reynolds number, expansibility factor, and permanent pressure loss.\n"
        "\n"
        "Warnings are issued (not errors) for: out-of-range beta, low Re_D, "
        "iteration non-convergence.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "meter_type": {
                "type": "string",
                "enum": ["orifice", "venturi", "nozzle"],
                "description": "Meter type: 'orifice' (ISO 5167-1), 'venturi' (ISO 5167-4), or 'nozzle' (ISO 5167-3).",
            },
            "pipe_d_m": {
                "type": "number",
                "description": "Pipe internal diameter [m]. Must be > 0.",
            },
            "beta": {
                "type": "number",
                "description": "Diameter ratio d/D (0.1–0.75 for orifice; 0.3–0.75 for venturi/nozzle).",
            },
            "dp_pa": {
                "type": "number",
                "description": "Differential pressure (p1 − p2) [Pa]. Must be > 0.",
            },
            "rho_kg_m3": {
                "type": "number",
                "description": "Upstream fluid density [kg/m³]. Must be > 0.",
            },
            "mu_pa_s": {
                "type": "number",
                "description": "Dynamic viscosity [Pa·s] (default 1e-3 for water).",
            },
            "p1_pa": {
                "type": "number",
                "description": "Upstream absolute pressure [Pa]. Required for gas (gas=true).",
            },
            "kappa": {
                "type": "number",
                "description": "Isentropic exponent (default 1.4 for air). Used only when gas=true.",
            },
            "gas": {
                "type": "boolean",
                "description": "True to apply ISO 5167 expansibility factor for compressible gas.",
            },
        },
        "required": ["meter_type", "pipe_d_m", "beta", "dp_pa", "rho_kg_m3"],
    },
)


@register(_dp_meter_spec, write=False)
async def run_dp_meter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("meter_type", "pipe_d_m", "beta", "dp_pa", "rho_kg_m3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("mu_pa_s", "p1_pa", "kappa", "gas"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = dp_meter(
        a["meter_type"], a["pipe_d_m"], a["beta"], a["dp_pa"], a["rho_kg_m3"],
        **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: control_valve_liquid
# ---------------------------------------------------------------------------

_cv_liquid_spec = ToolSpec(
    name="control_valve_liquid",
    description=(
        "ISA/IEC Cv & Kv sizing for liquid control valves.\n"
        "\n"
        "Applies choked-flow correction (FL factor), FF liquid critical-pressure "
        "ratio factor, and cavitation index check.\n"
        "Returns Cv (US gpm/psi^0.5), Kv (m³/h/bar^0.5), choked-ΔP, "
        "cavitation index, and flags.\n"
        "\n"
        "Warnings: choked flow, cavitating condition.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "q_m3h": {
                "type": "number",
                "description": "Required flow rate [m³/h]. Must be > 0.",
            },
            "rho_kg_m3": {
                "type": "number",
                "description": "Upstream liquid density [kg/m³]. Must be > 0.",
            },
            "dp_kpa": {
                "type": "number",
                "description": "Service pressure drop p1 − p2 [kPa]. Must be > 0.",
            },
            "p1_kpa": {
                "type": "number",
                "description": "Upstream absolute pressure [kPa]. Must be > 0.",
            },
            "pv_kpa": {
                "type": "number",
                "description": "Liquid vapour pressure at flowing temperature [kPa]. Must be >= 0.",
            },
            "pc_kpa": {
                "type": "number",
                "description": "Liquid thermodynamic critical pressure [kPa]. Must be > 0.",
            },
            "FL": {
                "type": "number",
                "description": "Pressure recovery factor (default 0.90 for single-seat globe).",
            },
        },
        "required": ["q_m3h", "rho_kg_m3", "dp_kpa", "p1_kpa", "pv_kpa", "pc_kpa"],
    },
)


@register(_cv_liquid_spec, write=False)
async def run_control_valve_liquid(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("q_m3h", "rho_kg_m3", "dp_kpa", "p1_kpa", "pv_kpa", "pc_kpa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "FL" in a:
        kwargs["FL"] = a["FL"]

    result = control_valve_liquid(
        a["q_m3h"], a["rho_kg_m3"], a["dp_kpa"], a["p1_kpa"],
        a["pv_kpa"], a["pc_kpa"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: control_valve_gas
# ---------------------------------------------------------------------------

_cv_gas_spec = ToolSpec(
    name="control_valve_gas",
    description=(
        "ISA/IEC Cv & Kv sizing for compressible gas control valves.\n"
        "\n"
        "Applies xT terminal pressure-drop ratio factor and expansion factor Y. "
        "Detects choked flow condition (x >= Fk·xT).\n"
        "Returns Cv, Kv, x, x_choked, Y, and is_choked flag.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "q_kg_s": {
                "type": "number",
                "description": "Required mass flow [kg/s]. Must be > 0.",
            },
            "p1_pa": {
                "type": "number",
                "description": "Upstream absolute pressure [Pa]. Must be > 0.",
            },
            "T1_K": {
                "type": "number",
                "description": "Upstream temperature [K]. Must be > 0.",
            },
            "MW_g_mol": {
                "type": "number",
                "description": "Gas molar mass [g/mol]. Must be > 0.",
            },
            "dp_pa": {
                "type": "number",
                "description": "Service differential pressure [Pa]. Must be > 0.",
            },
            "xT": {
                "type": "number",
                "description": "Terminal pressure-drop ratio factor (default 0.72 for single-seat globe).",
            },
            "Fp": {
                "type": "number",
                "description": "Piping geometry factor (default 1.0).",
            },
            "Z": {
                "type": "number",
                "description": "Compressibility factor (default 1.0 ideal gas).",
            },
            "kappa": {
                "type": "number",
                "description": "Isentropic exponent (default 1.4).",
            },
        },
        "required": ["q_kg_s", "p1_pa", "T1_K", "MW_g_mol", "dp_pa"],
    },
)


@register(_cv_gas_spec, write=False)
async def run_control_valve_gas(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("q_kg_s", "p1_pa", "T1_K", "MW_g_mol", "dp_pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("xT", "Fp", "Z", "kappa"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = control_valve_gas(
        a["q_kg_s"], a["p1_pa"], a["T1_K"], a["MW_g_mol"], a["dp_pa"],
        **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: control_valve_steam
# ---------------------------------------------------------------------------

_cv_steam_spec = ToolSpec(
    name="control_valve_steam",
    description=(
        "IEC 60534-2-1 Cv sizing for steam control valves.\n"
        "\n"
        "Uses N6 mass-flow form with upstream specific volume. "
        "Detects choked steam flow (x >= Fk·xT where κ=1.135 for saturated steam).\n"
        "Returns Cv, Kv, x, x_choked, Y, is_choked.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "q_kg_s": {
                "type": "number",
                "description": "Required steam mass flow [kg/s]. Must be > 0.",
            },
            "p1_pa": {
                "type": "number",
                "description": "Upstream absolute pressure [Pa]. Must be > 0.",
            },
            "dp_pa": {
                "type": "number",
                "description": "Differential pressure [Pa]. Must be > 0.",
            },
            "v1_m3_kg": {
                "type": "number",
                "description": "Upstream specific volume [m³/kg]. Must be > 0.",
            },
            "xT": {
                "type": "number",
                "description": "Terminal pressure-drop ratio factor (default 0.72).",
            },
            "Fp": {
                "type": "number",
                "description": "Piping geometry factor (default 1.0).",
            },
        },
        "required": ["q_kg_s", "p1_pa", "dp_pa", "v1_m3_kg"],
    },
)


@register(_cv_steam_spec, write=False)
async def run_control_valve_steam(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("q_kg_s", "p1_pa", "dp_pa", "v1_m3_kg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("xT", "Fp"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = control_valve_steam(a["q_kg_s"], a["p1_pa"], a["dp_pa"], a["v1_m3_kg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: prv_gas
# ---------------------------------------------------------------------------

_prv_gas_spec = ToolSpec(
    name="prv_gas",
    description=(
        "API 520 Part I gas/vapour pressure-relief-valve orifice area sizing.\n"
        "\n"
        "Supports critical (sonic) and sub-critical flow regimes. "
        "Returns required area (m² and in²), API 526 designation letter, "
        "relieving pressure P1, and back-pressure ratio Pcf.\n"
        "\n"
        "Warnings: sub-critical flow condition.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "q_kg_s": {
                "type": "number",
                "description": "Required relieving mass flow [kg/s]. Must be > 0.",
            },
            "p_set_pa": {
                "type": "number",
                "description": "Set pressure [Pa abs]. Must be > 0.",
            },
            "T_K": {
                "type": "number",
                "description": "Relieving temperature [K]. Must be > 0.",
            },
            "MW_g_mol": {
                "type": "number",
                "description": "Gas molar mass [g/mol]. Must be > 0.",
            },
            "overpressure_frac": {
                "type": "number",
                "description": "Allowable overpressure as fraction (default 0.10 = 10%).",
            },
            "backpressure_pa": {
                "type": "number",
                "description": "Back pressure [Pa abs] (default 101325 Pa).",
            },
            "Z": {
                "type": "number",
                "description": "Compressibility factor (default 1.0).",
            },
            "kd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.975).",
            },
            "kb": {
                "type": "number",
                "description": "Back-pressure correction factor (default 1.0).",
            },
            "kc": {
                "type": "number",
                "description": "Combination correction factor (default 1.0).",
            },
        },
        "required": ["q_kg_s", "p_set_pa", "T_K", "MW_g_mol"],
    },
)


@register(_prv_gas_spec, write=False)
async def run_prv_gas(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("q_kg_s", "p_set_pa", "T_K", "MW_g_mol"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("overpressure_frac", "backpressure_pa", "Z", "kd", "kb", "kc"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = prv_gas(a["q_kg_s"], a["p_set_pa"], a["T_K"], a["MW_g_mol"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: prv_liquid
# ---------------------------------------------------------------------------

_prv_liquid_spec = ToolSpec(
    name="prv_liquid",
    description=(
        "API 520 Part I liquid pressure-relief-valve orifice area sizing.\n"
        "\n"
        "Returns required area (m² and in²), API 526 designation letter.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "q_m3s": {
                "type": "number",
                "description": "Required volumetric relief flow [m³/s]. Must be > 0.",
            },
            "p_set_pa": {
                "type": "number",
                "description": "Set pressure [Pa abs]. Must be > 0.",
            },
            "rho_kg_m3": {
                "type": "number",
                "description": "Liquid density [kg/m³]. Must be > 0.",
            },
            "overpressure_frac": {
                "type": "number",
                "description": "Allowable overpressure as fraction (default 0.25 = 25%).",
            },
            "backpressure_pa": {
                "type": "number",
                "description": "Back pressure [Pa abs] (default 101325 Pa).",
            },
            "kd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.65).",
            },
            "kw": {
                "type": "number",
                "description": "Back-pressure correction factor (default 1.0).",
            },
            "kc": {
                "type": "number",
                "description": "Combination correction factor (default 1.0).",
            },
            "kv": {
                "type": "number",
                "description": "Viscosity correction factor (default 1.0).",
            },
        },
        "required": ["q_m3s", "p_set_pa", "rho_kg_m3"],
    },
)


@register(_prv_liquid_spec, write=False)
async def run_prv_liquid(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("q_m3s", "p_set_pa", "rho_kg_m3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("overpressure_frac", "backpressure_pa", "kd", "kw", "kc", "kv"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = prv_liquid(a["q_m3s"], a["p_set_pa"], a["rho_kg_m3"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: prv_steam
# ---------------------------------------------------------------------------

_prv_steam_spec = ToolSpec(
    name="prv_steam",
    description=(
        "API 520 Part I steam PRV orifice area sizing (Napier equation).\n"
        "\n"
        "Applies Napier kn correction automatically when P1 > 1500 psia. "
        "Returns required area (m² and in²), API 526 designation letter.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "q_kg_s": {
                "type": "number",
                "description": "Required steam mass flow [kg/s]. Must be > 0.",
            },
            "p_set_pa": {
                "type": "number",
                "description": "Set pressure [Pa abs]. Must be > 0.",
            },
            "overpressure_frac": {
                "type": "number",
                "description": "Allowable overpressure as fraction (default 0.10 = 10%).",
            },
            "kd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.975).",
            },
            "kb": {
                "type": "number",
                "description": "Back-pressure correction (default 1.0).",
            },
            "ksh": {
                "type": "number",
                "description": "Superheat correction factor (default 1.0 = saturated steam).",
            },
        },
        "required": ["q_kg_s", "p_set_pa"],
    },
)


@register(_prv_steam_spec, write=False)
async def run_prv_steam(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("q_kg_s", "p_set_pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("overpressure_frac", "kd", "kb", "ksh"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = prv_steam(a["q_kg_s"], a["p_set_pa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: pitot_velocity
# ---------------------------------------------------------------------------

_pitot_spec = ToolSpec(
    name="pitot_velocity",
    description=(
        "Pitot-tube point velocity from impact (stagnation − static) pressure.\n"
        "\n"
        "v = Cp × √(2 × dp / ρ)\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dp_pa": {
                "type": "number",
                "description": "Impact pressure (stagnation − static) [Pa]. Must be > 0.",
            },
            "rho_kg_m3": {
                "type": "number",
                "description": "Fluid density [kg/m³]. Must be > 0.",
            },
            "Cp": {
                "type": "number",
                "description": "Pitot-tube coefficient (default 1.0; range 0.5–1.1).",
            },
        },
        "required": ["dp_pa", "rho_kg_m3"],
    },
)


@register(_pitot_spec, write=False)
async def run_pitot_velocity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("dp_pa", "rho_kg_m3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "Cp" in a:
        kwargs["Cp"] = a["Cp"]

    result = pitot_velocity(a["dp_pa"], a["rho_kg_m3"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: annubar_flow
# ---------------------------------------------------------------------------

_annubar_spec = ToolSpec(
    name="annubar_flow",
    description=(
        "Annubar (multi-port averaging pitot) volume and mass flow.\n"
        "\n"
        "v_avg = Cp × √(2 × dp / ρ),  qv = v_avg × (π/4) × D²\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dp_pa": {
                "type": "number",
                "description": "Differential pressure [Pa]. Must be > 0.",
            },
            "rho_kg_m3": {
                "type": "number",
                "description": "Fluid density [kg/m³]. Must be > 0.",
            },
            "pipe_d_m": {
                "type": "number",
                "description": "Pipe inside diameter [m]. Must be > 0.",
            },
            "Cp": {
                "type": "number",
                "description": "Annubar flow coefficient (default 0.77; range 0.5–1.1).",
            },
        },
        "required": ["dp_pa", "rho_kg_m3", "pipe_d_m"],
    },
)


@register(_annubar_spec, write=False)
async def run_annubar_flow(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("dp_pa", "rho_kg_m3", "pipe_d_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "Cp" in a:
        kwargs["Cp"] = a["Cp"]

    result = annubar_flow(a["dp_pa"], a["rho_kg_m3"], a["pipe_d_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: v_notch_weir
# ---------------------------------------------------------------------------

_vnotch_spec = ToolSpec(
    name="v_notch_weir",
    description=(
        "ISO 1438 V-notch (triangular) weir open-channel flow.\n"
        "\n"
        "Q = (8/15) × Cd × √(2g) × tan(θ/2) × H^(5/2)\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_m": {
                "type": "number",
                "description": "Head above notch vertex [m]. Must be > 0.",
            },
            "theta_deg": {
                "type": "number",
                "description": "Notch angle [degrees] (default 90°; typical range 20–120°).",
            },
            "Cd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.611).",
            },
        },
        "required": ["H_m"],
    },
)


@register(_vnotch_spec, write=False)
async def run_v_notch_weir(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("H_m") is None:
        return json.dumps({"ok": False, "reason": "H_m is required"})

    kwargs: dict = {}
    for opt in ("theta_deg", "Cd"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = v_notch_weir(a["H_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rectangular_weir
# ---------------------------------------------------------------------------

_rect_weir_spec = ToolSpec(
    name="rectangular_weir",
    description=(
        "Rectangular sharp-crested weir flow — Francis / Rehbock formula.\n"
        "\n"
        "Q = (2/3) × Cd × √(2g) × Leff × H^(3/2)\n"
        "Leff = L − 0.1 × n_contractions × H  (end-contraction correction)\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_m": {
                "type": "number",
                "description": "Head above weir crest [m]. Must be > 0.",
            },
            "L_m": {
                "type": "number",
                "description": "Weir crest length [m]. Must be > 0.",
            },
            "Cd": {
                "type": "number",
                "description": "Discharge coefficient (default 0.611).",
            },
            "end_contractions": {
                "type": "integer",
                "enum": [0, 2],
                "description": "Number of end contractions: 0 (suppressed) or 2 (default).",
            },
        },
        "required": ["H_m", "L_m"],
    },
)


@register(_rect_weir_spec, write=False)
async def run_rectangular_weir(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("H_m", "L_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("Cd", "end_contractions"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = rectangular_weir(a["H_m"], a["L_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: parshall_flume
# ---------------------------------------------------------------------------

_parshall_spec = ToolSpec(
    name="parshall_flume",
    description=(
        "Parshall flume free-flow discharge from upstream head.\n"
        "\n"
        "Q = C × Ha^n  (USBR standard; nearest standard throat width selected)\n"
        "\n"
        "Standard throat widths: 0.025, 0.051, 0.076, 0.152, 0.229, 0.305, "
        "0.457, 0.610, 0.914, 1.219, 1.524, 1.829 m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Ha_m": {
                "type": "number",
                "description": "Upstream gauge head Ha [m]. Must be > 0.",
            },
            "throat_w_m": {
                "type": "number",
                "description": "Throat width [m]; matched to nearest standard size.",
            },
        },
        "required": ["Ha_m", "throat_w_m"],
    },
)


@register(_parshall_spec, write=False)
async def run_parshall_flume(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Ha_m", "throat_w_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = parshall_flume(a["Ha_m"], a["throat_w_m"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: rotameter_scale
# ---------------------------------------------------------------------------

_rotameter_spec = ToolSpec(
    name="rotameter_scale",
    description=(
        "Rotameter (variable-area meter) flow correction for actual fluid density.\n"
        "\n"
        "Q_actual = Q_reading × √[(ρ_float − ρ_ref) × ρ_actual / "
        "((ρ_float − ρ_actual) × ρ_ref)]\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_ref_m3s": {
                "type": "number",
                "description": "Rotameter reading calibrated for reference fluid [m³/s]. Must be > 0.",
            },
            "rho_ref_kg_m3": {
                "type": "number",
                "description": "Calibration fluid density [kg/m³]. Must be > 0.",
            },
            "rho_actual_kg_m3": {
                "type": "number",
                "description": "Actual process fluid density [kg/m³]. Must be > 0.",
            },
            "float_density_kg_m3": {
                "type": "number",
                "description": "Float (rotor) material density [kg/m³] (default 8000 for 316SS).",
            },
        },
        "required": ["Q_ref_m3s", "rho_ref_kg_m3", "rho_actual_kg_m3"],
    },
)


@register(_rotameter_spec, write=False)
async def run_rotameter_scale(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_ref_m3s", "rho_ref_kg_m3", "rho_actual_kg_m3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "float_density_kg_m3" in a:
        kwargs["float_density_kg_m3"] = a["float_density_kg_m3"]

    result = rotameter_scale(a["Q_ref_m3s"], a["rho_ref_kg_m3"], a["rho_actual_kg_m3"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turndown_ratio
# ---------------------------------------------------------------------------

_turndown_spec = ToolSpec(
    name="turndown_ratio",
    description=(
        "Compute the turndown ratio of a flow meter or control valve.\n"
        "\n"
        "turndown = Q_max / Q_min\n"
        "Warns if turndown < 3:1 (low range).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_max": {
                "type": "number",
                "description": "Maximum flow rate (any consistent unit). Must be > 0.",
            },
            "Q_min": {
                "type": "number",
                "description": "Minimum flow rate (same unit as Q_max). Must be > 0.",
            },
        },
        "required": ["Q_max", "Q_min"],
    },
)


@register(_turndown_spec, write=False)
async def run_turndown_ratio(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_max", "Q_min"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = turndown_ratio(a["Q_max"], a["Q_min"])
    return ok_payload(result)
