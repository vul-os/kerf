"""
kerf_cad_core.waterhammer.tools — LLM tool wrappers for hydraulic transient analysis.

Registers tools with the Kerf tool registry:

  waterhammer_wave_speed         — pressure-wave celerity from fluid + pipe properties
  waterhammer_joukowsky          — Joukowsky head rise for rapid/slow valve closure
  waterhammer_moc                — MOC single-pipe transient solver (head/velocity envelopes)
  waterhammer_safe_closure_time  — minimum valve closure time to limit surge
  waterhammer_pump_trip          — simplified pump-trip transient (rundown + check-valve)
  waterhammer_air_vessel         — air vessel minimum volume for surge protection
  waterhammer_surge_tank         — surge tank oscillation period and amplitude
  waterhammer_relief_valve       — relief valve discharge flow

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Wylie, E.B. & Streeter, V.L. (1993) Fluid Transients in Systems. Prentice Hall.
Chaudhry, M.H. (2014) Applied Hydraulic Transients, 3rd ed. Springer.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.waterhammer.transient import (
    wave_speed,
    joukowsky_head_rise,
    moc_single_pipe,
    safe_closure_time,
    pump_trip_simplified,
    air_vessel_sizing,
    surge_tank_oscillation,
    relief_valve_flow,
)


# ---------------------------------------------------------------------------
# Tool: waterhammer_wave_speed
# ---------------------------------------------------------------------------

_wave_speed_spec = ToolSpec(
    name="waterhammer_wave_speed",
    description=(
        "Compute the pressure-wave celerity (speed of sound) a (m/s) in a "
        "pressurised pipe.\n"
        "\n"
        "Accounts for:\n"
        "  - fluid bulk modulus K_fluid (compressibility)\n"
        "  - pipe wall elasticity (E_pipe, D, e)\n"
        "  - axial restraint factor c1 per Wylie & Streeter Table 2.1\n"
        "  - entrained-gas void fraction (Chaudhry §2.4)\n"
        "\n"
        "Restraint options:\n"
        "  'anchored-both'   — c1 = 1−ν² (default, ν=0.3)\n"
        "  'anchored-up'     — c1 = 1−ν/2\n"
        "  'expansion-joint' — c1 = 1.0\n"
        "\n"
        "Returns a_m_s, K_eff, c1.  Warns if a > 1600 or a < 100 m/s. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "K_fluid": {
                "type": "number",
                "description": "Bulk modulus of the liquid (Pa). Water ≈ 2.07e9 Pa. Must be > 0.",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Water ≈ 998. Must be > 0.",
            },
            "D": {
                "type": "number",
                "description": "Internal pipe diameter (m). Must be > 0.",
            },
            "e": {
                "type": "number",
                "description": "Pipe wall thickness (m). Must be > 0.",
            },
            "E_pipe": {
                "type": "number",
                "description": "Young's modulus of pipe material (Pa). Steel ≈ 200e9. Must be > 0.",
            },
            "restraint": {
                "type": "string",
                "enum": ["anchored-both", "anchored-up", "expansion-joint"],
                "description": "Axial restraint condition. Default 'anchored-both'.",
            },
            "alpha_gas": {
                "type": "number",
                "description": "Free-gas void fraction 0–1. Default 0 (no gas).",
            },
            "P_abs": {
                "type": "number",
                "description": "Absolute pressure at section (Pa), for gas correction. Default 101325.",
            },
        },
        "required": ["K_fluid", "rho", "D", "e", "E_pipe"],
    },
)


@register(_wave_speed_spec, write=False)
async def run_wave_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("K_fluid", "rho", "D", "e", "E_pipe"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("restraint", "alpha_gas", "P_abs"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = wave_speed(a["K_fluid"], a["rho"], a["D"], a["e"], a["E_pipe"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_joukowsky
# ---------------------------------------------------------------------------

_joukowsky_spec = ToolSpec(
    name="waterhammer_joukowsky",
    description=(
        "Compute Joukowsky head rise for valve closure.\n"
        "\n"
        "Pipe period T_p = 2L/a.\n"
        "Rapid closure (t_close ≤ T_p):  ΔH = a·V0/g (instantaneous Joukowsky).\n"
        "Slow closure  (t_close > T_p):  ΔH = 2·L·V0/(g·t_close) (rigid-column).\n"
        "\n"
        "Flags column separation (return wave drops below vapor pressure) and "
        "overpressure (H_max exceeds pipe_rating_m if given). Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V0": {
                "type": "number",
                "description": "Initial flow velocity (m/s). Must be >= 0.",
            },
            "a": {
                "type": "number",
                "description": "Wave celerity (m/s). Must be > 0.",
            },
            "L": {
                "type": "number",
                "description": "Pipe length (m). Must be > 0.",
            },
            "t_close": {
                "type": "number",
                "description": "Valve closure time (s). Must be > 0.",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Default 998.",
            },
            "P_vapor_Pa": {
                "type": "number",
                "description": "Vapour pressure (Pa). Default 2338 (water 20°C).",
            },
            "H0": {
                "type": "number",
                "description": "Steady-state head at valve (m). Default 0.",
            },
            "pipe_rating_m": {
                "type": "number",
                "description": "Pipe pressure rating expressed as head (m). Optional.",
            },
        },
        "required": ["V0", "a", "L", "t_close"],
    },
)


@register(_joukowsky_spec, write=False)
async def run_joukowsky(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("V0", "a", "L", "t_close"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("rho", "P_vapor_Pa", "H0", "pipe_rating_m"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = joukowsky_head_rise(a["V0"], a["a"], a["L"], a["t_close"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_moc
# ---------------------------------------------------------------------------

_moc_spec = ToolSpec(
    name="waterhammer_moc",
    description=(
        "Method-of-Characteristics (MOC) single-pipe transient solver.\n"
        "\n"
        "Solves the 1-D water-hammer equations on a uniform reach grid "
        "(Wylie & Streeter §3.2).  Returns head and velocity envelopes "
        "(max/min vs position) over the simulation period.\n"
        "\n"
        "BCs:\n"
        "  Upstream:   constant-head reservoir (H = H_res)\n"
        "  Downstream: 'valve' (closure law τ(t)) or 'dead-end' (V=0)\n"
        "\n"
        "Closure laws: 'linear' τ=1−t/t_close, 'parabolic' τ=(1−t/t_close)²\n"
        "\n"
        "Time step = dx/a (Courant=1, exact characteristics).\n"
        "Flags column separation and overpressure. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "L": {"type": "number", "description": "Pipe length (m). Must be > 0."},
            "D": {"type": "number", "description": "Internal diameter (m). Must be > 0."},
            "a": {"type": "number", "description": "Wave celerity (m/s). Must be > 0."},
            "V0": {"type": "number", "description": "Initial velocity (m/s). Must be >= 0."},
            "H_res": {"type": "number", "description": "Upstream reservoir head (m)."},
            "f": {"type": "number", "description": "Darcy-Weisbach friction factor. Must be >= 0."},
            "n_reaches": {
                "type": "integer",
                "description": "Number of uniform reaches (>= 2). More reaches = higher resolution.",
            },
            "t_total": {"type": "number", "description": "Total simulation time (s). Must be > 0."},
            "closure_law": {
                "type": "string",
                "enum": ["linear", "parabolic"],
                "description": "Valve closure profile. Default 'linear'.",
            },
            "t_close": {
                "type": "number",
                "description": "Valve closure time (s). Default = pipe period 2L/a.",
            },
            "downstream_bc": {
                "type": "string",
                "enum": ["valve", "dead-end"],
                "description": "Downstream boundary condition. Default 'valve'.",
            },
            "P_vapor_Pa": {
                "type": "number",
                "description": "Vapour pressure (Pa). Default 2338.",
            },
            "rho": {"type": "number", "description": "Fluid density (kg/m³). Default 998."},
            "pipe_rating_m": {
                "type": "number",
                "description": "Pipe pressure rating as head (m). Optional; triggers overpressure flag.",
            },
        },
        "required": ["L", "D", "a", "V0", "H_res", "f", "n_reaches", "t_total"],
    },
)


@register(_moc_spec, write=False)
async def run_moc(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("L", "D", "a", "V0", "H_res", "f", "n_reaches", "t_total"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("closure_law", "t_close", "downstream_bc", "P_vapor_Pa", "rho", "pipe_rating_m"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = moc_single_pipe(
        a["L"], a["D"], a["a"], a["V0"], a["H_res"],
        a["f"], int(a["n_reaches"]), a["t_total"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_safe_closure_time
# ---------------------------------------------------------------------------

_safe_closure_spec = ToolSpec(
    name="waterhammer_safe_closure_time",
    description=(
        "Compute minimum safe valve-closure time to limit surge head rise.\n"
        "\n"
        "Uses rigid-column formula:\n"
        "  t_close_min = 2·L·V0 / (g·dH_allowable)\n"
        "\n"
        "Also returns pipe period T_pipe = 2L/a, Joukowsky dH for rapid closure, "
        "and flags if the minimum time is still in the rapid-closure regime. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V0": {"type": "number", "description": "Initial velocity (m/s). Must be >= 0."},
            "a": {"type": "number", "description": "Wave celerity (m/s). Must be > 0."},
            "L": {"type": "number", "description": "Pipe length (m). Must be > 0."},
            "H0": {"type": "number", "description": "Steady-state head at valve (m). Must be > 0."},
            "dH_allowable": {
                "type": "number",
                "description": "Maximum allowable head rise (m). Must be > 0.",
            },
        },
        "required": ["V0", "a", "L", "H0", "dH_allowable"],
    },
)


@register(_safe_closure_spec, write=False)
async def run_safe_closure_time(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("V0", "a", "L", "H0", "dH_allowable"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = safe_closure_time(a["V0"], a["a"], a["L"], a["H0"], a["dH_allowable"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_pump_trip
# ---------------------------------------------------------------------------

_pump_trip_spec = ToolSpec(
    name="waterhammer_pump_trip",
    description=(
        "Simplified pump-trip (power failure) transient analysis.\n"
        "\n"
        "Estimates:\n"
        "  - pump rundown time from rotational inertia WR² and rated power\n"
        "  - Joukowsky head drop at pump trip\n"
        "  - check-valve slam head rise (conservative = same as drop)\n"
        "  - column separation risk at pump suction\n"
        "\n"
        "Uses rigid-column / Joukowsky approach.  For detailed transients, "
        "use waterhammer_moc. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_ss": {
                "type": "number",
                "description": "Steady-state total head at pump discharge (m). Must be > 0.",
            },
            "V0": {"type": "number", "description": "Steady-state pipe velocity (m/s). Must be > 0."},
            "a": {"type": "number", "description": "Wave celerity (m/s). Must be > 0."},
            "L": {"type": "number", "description": "Pipe length (m). Must be > 0."},
            "WR2": {
                "type": "number",
                "description": "Pump + motor rotational inertia W·R² (kg·m²). Must be > 0.",
            },
            "n_rated": {"type": "number", "description": "Rated speed (rpm). Must be > 0."},
            "P_rated_W": {"type": "number", "description": "Rated shaft power (W). Must be > 0."},
            "rho": {"type": "number", "description": "Fluid density (kg/m³). Default 998."},
            "P_vapor_Pa": {"type": "number", "description": "Vapour pressure (Pa). Default 2338."},
        },
        "required": ["H_ss", "V0", "a", "L", "WR2", "n_rated", "P_rated_W"],
    },
)


@register(_pump_trip_spec, write=False)
async def run_pump_trip(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("H_ss", "V0", "a", "L", "WR2", "n_rated", "P_rated_W"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("rho", "P_vapor_Pa"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = pump_trip_simplified(
        a["H_ss"], a["V0"], a["a"], a["L"],
        a["WR2"], a["n_rated"], a["P_rated_W"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_air_vessel
# ---------------------------------------------------------------------------

_air_vessel_spec = ToolSpec(
    name="waterhammer_air_vessel",
    description=(
        "Estimate minimum air vessel (air chamber) volume for surge protection.\n"
        "\n"
        "Uses simplified rigid-column formula (Chaudhry §13.3):\n"
        "  Vol_min = a·L·V0·A_pipe / (2·g·dH_allowable)\n"
        "\n"
        "Returns minimum volume, recommended volume (1.5× safety factor), "
        "and initial air pressure. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V0": {"type": "number", "description": "Initial velocity (m/s). Must be > 0."},
            "A_pipe": {
                "type": "number",
                "description": "Pipe cross-sectional area (m²). Must be > 0. Circular: π·D²/4.",
            },
            "a": {"type": "number", "description": "Wave celerity (m/s). Must be > 0."},
            "L": {"type": "number", "description": "Pipe length (m). Must be > 0."},
            "H_res": {"type": "number", "description": "Reservoir head (m). Must be > 0."},
            "dH_allowable": {
                "type": "number",
                "description": "Maximum allowable head change (m). Must be > 0.",
            },
            "rho": {"type": "number", "description": "Fluid density (kg/m³). Default 998."},
            "polytropic_n": {
                "type": "number",
                "description": "Polytropic index for air (default 1.2; 1.0=isothermal, 1.4=adiabatic).",
            },
        },
        "required": ["V0", "A_pipe", "a", "L", "H_res", "dH_allowable"],
    },
)


@register(_air_vessel_spec, write=False)
async def run_air_vessel(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("V0", "A_pipe", "a", "L", "H_res", "dH_allowable"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("rho", "polytropic_n"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = air_vessel_sizing(
        a["V0"], a["A_pipe"], a["a"], a["L"], a["H_res"], a["dH_allowable"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_surge_tank
# ---------------------------------------------------------------------------

_surge_tank_spec = ToolSpec(
    name="waterhammer_surge_tank",
    description=(
        "Compute simple surge tank oscillation period and amplitude.\n"
        "\n"
        "Mass-oscillation theory (Wylie & Streeter §8.1):\n"
        "  T_osc = 2π · sqrt(L·A_tank / (g·A_pipe))\n"
        "  z_max = V0 · sqrt(L·A_tank / (g·A_pipe))   [undamped, frictionless]\n"
        "\n"
        "Conservative upper bound. Warns if z_max > H0 (tank overflow/drain). "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "L": {
                "type": "number",
                "description": "Tunnel/pipe length from reservoir to surge tank (m). Must be > 0.",
            },
            "A_pipe": {"type": "number", "description": "Tunnel/pipe area (m²). Must be > 0."},
            "A_tank": {"type": "number", "description": "Surge tank cross-sectional area (m²). Must be > 0."},
            "H0": {"type": "number", "description": "Initial steady-state head in tunnel (m). Must be > 0."},
            "V0": {"type": "number", "description": "Initial flow velocity (m/s). Must be >= 0."},
            "rho": {"type": "number", "description": "Fluid density (kg/m³). Default 998."},
        },
        "required": ["L", "A_pipe", "A_tank", "H0", "V0"],
    },
)


@register(_surge_tank_spec, write=False)
async def run_surge_tank(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("L", "A_pipe", "A_tank", "H0", "V0"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    if "rho" in a:
        kwargs["rho"] = a["rho"]
    result = surge_tank_oscillation(
        a["L"], a["A_pipe"], a["A_tank"], a["H0"], a["V0"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: waterhammer_relief_valve
# ---------------------------------------------------------------------------

_relief_valve_spec = ToolSpec(
    name="waterhammer_relief_valve",
    description=(
        "Estimate relief valve discharge flow rate.\n"
        "\n"
        "Uses SI orifice head form with standard Cv coefficient (US GPM/sqrt(psi)):\n"
        "  Q = Cv · sqrt(dP_psi)  [converted to m³/s]\n"
        "\n"
        "Valve opens when H_operating > H_set.  Returns Q_m3s, dH_m, "
        "valve_open flag. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H_set": {
                "type": "number",
                "description": "Relief valve set pressure as head (m). Must be > 0.",
            },
            "H_operating": {
                "type": "number",
                "description": "Actual upstream head at valve (m). Must be > 0.",
            },
            "Cv": {
                "type": "number",
                "description": "Valve flow coefficient (US GPM/sqrt(psi)). Must be > 0.",
            },
            "rho": {"type": "number", "description": "Fluid density (kg/m³). Default 998."},
            "P_atm_Pa": {"type": "number", "description": "Atmospheric pressure (Pa). Default 101325."},
        },
        "required": ["H_set", "H_operating", "Cv"],
    },
)


@register(_relief_valve_spec, write=False)
async def run_relief_valve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("H_set", "H_operating", "Cv"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs: dict = {}
    for opt in ("rho", "P_atm_Pa"):
        if opt in a:
            kwargs[opt] = a[opt]
    result = relief_valve_flow(a["H_set"], a["H_operating"], a["Cv"], **kwargs)
    return ok_payload(result)
