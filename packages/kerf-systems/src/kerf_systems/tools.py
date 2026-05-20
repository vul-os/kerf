"""
kerf_systems.tools
==================

LLM tool surface for the kerf-systems plugin.

Tools
-----
  systems_run     — run a .system simulation from inline equations or a
                    Modelica snippet, or from a pre-built component type
  systems_parse   — parse a .system model and return its structural description
"""

from __future__ import annotations

import json
import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_systems._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# systems_run tool spec
# ---------------------------------------------------------------------------

systems_run_spec = ToolSpec(
    name="systems_run",
    description=(
        "Run a 1D lumped-parameter system simulation (Modelica-class DAE solver). "
        "Supports thermal networks, hydraulic circuits, electrical RLC circuits, "
        "and control systems (P/PI/PID). "
        "Provide either a Modelica-flavoured .system model source string or a "
        "pre-built component shortcut."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "model_source": {
                "type": "string",
                "description": (
                    "Modelica-flavoured .system model source text. "
                    "Mutually exclusive with 'component_type'."
                ),
            },
            "component_type": {
                "type": "string",
                "enum": ["RC", "RLC", "mass_spring_damper", "thermal_RC", "PI_control"],
                "description": (
                    "Pre-built component shortcut. "
                    "RC: {R, C, V0}. "
                    "RLC: {R, L, C, V0}. "
                    "mass_spring_damper: {m, k, b, x0, v0}. "
                    "thermal_RC: {R_th, C_th, T_hot, T_cold0}. "
                    "PI_control: {Kp, Ki, setpoint, plant_tau}."
                ),
            },
            "params": {
                "type": "object",
                "description": "Component parameters (see component_type description).",
            },
            "t_end": {
                "type": "number",
                "description": "Simulation end time [s].  Default: 1.0.",
            },
            "h": {
                "type": "number",
                "description": "Time step hint [s] for implicit solver.  Default: auto.",
            },
            "output_vars": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Variable names to include in result.  Default: all.",
            },
        },
    },
)


@register(systems_run_spec)
async def run_systems_run(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    t_end = float(a.get("t_end", 1.0))
    params = a.get("params") or {}

    if "model_source" in a:
        return _run_from_source(a["model_source"], t_end, a.get("h"), a.get("output_vars"))

    comp = a.get("component_type")
    if comp == "RC":
        return _run_rc(params, t_end, a.get("h"), a.get("output_vars"))
    elif comp == "RLC":
        return _run_rlc(params, t_end, a.get("h"), a.get("output_vars"))
    elif comp == "mass_spring_damper":
        return _run_msd(params, t_end, a.get("h"), a.get("output_vars"))
    elif comp == "thermal_RC":
        return _run_thermal_rc(params, t_end, a.get("h"), a.get("output_vars"))
    elif comp == "PI_control":
        return _run_pi_control(params, t_end, a.get("h"), a.get("output_vars"))
    else:
        return err_payload(
            "Provide 'model_source' or one of: RC, RLC, mass_spring_damper, "
            "thermal_RC, PI_control",
            "BAD_ARGS",
        )


def _format_result(result, var_names: list[str], output_vars=None) -> str:
    t_arr = result.t
    x_arr = result.x
    n_steps = len(t_arr)
    stride = max(1, n_steps // 500)
    t_out = t_arr[::stride]
    x_out = x_arr[::stride]

    if output_vars:
        indices = [i for i, v in enumerate(var_names) if v in output_vars]
        names_out = [var_names[i] for i in indices]
    else:
        indices = list(range(len(var_names)))
        names_out = list(var_names)

    traces = {}
    for idx, name in zip(indices, names_out):
        traces[name] = [row[idx] for row in x_out]

    return ok_payload({
        "t": t_out,
        "traces": traces,
        "converged": result.converged,
        "warnings": result.warnings,
        "n_steps": n_steps,
        "method": getattr(result, "method", "BDF"),
    })


def _run_from_source(source: str, t_end: float, h_hint, output_vars) -> str:
    from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
    from kerf_systems.solver.dae import solve_system

    try:
        model = parse_model(source)
        F, x0, dx0, var_names, _ = build_dae_problem(model)
    except Exception as e:
        return err_payload(f"parse error: {e}", "PARSE_ERROR")

    h = float(h_hint) if h_hint else t_end / 2000
    try:
        result = solve_system(F, (0.0, t_end), x0, dx0, h=h)
    except Exception as e:
        return err_payload(f"solver error: {e}", "SOLVER_ERROR")

    return _format_result(result, var_names, output_vars)


def _run_rc(params: dict, t_end: float, h_hint, output_vars) -> str:
    R = float(params.get("R", 1e3))
    C = float(params.get("C", 1e-6))
    V0 = float(params.get("V0", 1.0))
    from kerf_systems.solver.dae import solve_system

    def F_rc(t, x, dx):
        v_C, i = x[0], x[1]
        dv_C = dx[0]
        return [C * dv_C - i, v_C + R * i - V0]

    tau = R * C
    h = float(h_hint) if h_hint else tau / 500
    result = solve_system(F_rc, (0.0, t_end), [0.0, V0 / R], [V0 / (R * C), 0.0], h=h)
    return _format_result(result, ["v_C", "i"], output_vars)


def _run_rlc(params: dict, t_end: float, h_hint, output_vars) -> str:
    R = float(params.get("R", 10.0))
    L = float(params.get("L", 1e-3))
    C = float(params.get("C", 1e-6))
    V0 = float(params.get("V0", 1.0))
    from kerf_systems.solver.dae import solve_system

    def F_rlc(t, x, dx):
        v_C, i_L = x[0], x[1]
        dv_C, di_L = dx[0], dx[1]
        return [
            C * dv_C - i_L,
            L * di_L + R * i_L + v_C - V0,
        ]

    T0 = 2 * math.pi * math.sqrt(L * C)
    h = float(h_hint) if h_hint else T0 / 500
    result = solve_system(F_rlc, (0.0, t_end), [0.0, 0.0], [0.0, V0 / L], h=h)
    return _format_result(result, ["v_C", "i_L"], output_vars)


def _run_msd(params: dict, t_end: float, h_hint, output_vars) -> str:
    """Mass-spring-damper: m*x'' + b*x' + k*x = 0"""
    m = float(params.get("m", 1.0))
    k = float(params.get("k", 4.0))
    b = float(params.get("b", 0.5))
    x0 = float(params.get("x0", 1.0))
    v0 = float(params.get("v0", 0.0))
    from kerf_systems.solver.dae import solve_system

    def F_msd(t, x, dx):
        q, v = x[0], x[1]
        dq, dv = dx[0], dx[1]
        return [
            dq - v,
            m * dv + b * v + k * q,
        ]

    wn = math.sqrt(k / m)
    h = float(h_hint) if h_hint else (2 * math.pi / wn) / 500
    result = solve_system(F_msd, (0.0, t_end), [x0, v0], [v0, -(b * v0 + k * x0) / m], h=h)
    return _format_result(result, ["q", "v"], output_vars)


def _run_thermal_rc(params: dict, t_end: float, h_hint, output_vars) -> str:
    """Thermal RC: C_th * dT/dt = (T_hot - T) / R_th"""
    R_th = float(params.get("R_th", 1.0))
    C_th = float(params.get("C_th", 1000.0))
    T_hot = float(params.get("T_hot", 100.0))
    T_cold0 = float(params.get("T_cold0", 20.0))
    from kerf_systems.solver.dae import solve_system

    def F_trc(t, x, dx):
        T, Q = x[0], x[1]
        dT = dx[0]
        return [
            C_th * dT - Q,
            Q - (T_hot - T) / R_th,
        ]

    tau = R_th * C_th
    h = float(h_hint) if h_hint else tau / 500
    Q0 = (T_hot - T_cold0) / R_th
    result = solve_system(F_trc, (0.0, t_end), [T_cold0, Q0], [Q0 / C_th, 0.0], h=h)
    return _format_result(result, ["T_cold", "Q"], output_vars)


def _run_pi_control(params: dict, t_end: float, h_hint, output_vars) -> str:
    """PI-controlled first-order plant: tau_p * dy/dt + y = Kp*e + Ki*xi"""
    Kp = float(params.get("Kp", 2.0))
    Ki = float(params.get("Ki", 1.0))
    setpoint = float(params.get("setpoint", 1.0))
    plant_tau = float(params.get("plant_tau", 1.0))
    from kerf_systems.solver.dae import solve_system

    # States: [y (plant output), xi (integral of error), e (error)]
    def F_pi(t, x, dx):
        y, xi, e = x[0], x[1], x[2]
        dy, dxi, _ = dx[0], dx[1], dx[2]
        u = Kp * e + Ki * xi       # PI control law
        return [
            plant_tau * dy + y - u,  # plant: tau*dy/dt + y = u
            dxi - e,                 # integrator: dxi/dt = e
            e - (setpoint - y),      # error definition
        ]

    h = float(h_hint) if h_hint else t_end / 2000
    result = solve_system(F_pi, (0.0, t_end), [0.0, 0.0, setpoint], [0.0, setpoint, 0.0], h=h)
    return _format_result(result, ["y", "xi", "e"], output_vars)


# ---------------------------------------------------------------------------
# systems_parse tool spec
# ---------------------------------------------------------------------------

systems_parse_spec = ToolSpec(
    name="systems_parse",
    description=(
        "Parse a Modelica-flavoured .system model string and return its "
        "structural description: variables, parameters, and equations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "model_source": {
                "type": "string",
                "description": "Modelica .system model source text.",
            },
        },
        "required": ["model_source"],
    },
)


@register(systems_parse_spec)
async def run_systems_parse(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    source = a.get("model_source", "")
    if not source:
        return err_payload("model_source is required", "BAD_ARGS")

    from kerf_systems.parser.mo_parser import parse_model

    try:
        model = parse_model(source)
    except Exception as e:
        return err_payload(f"parse error: {e}", "PARSE_ERROR")

    vars_out = [
        {
            "name": v.name,
            "is_parameter": v.is_parameter,
            "start": v.start,
            **({"value": v.value} if v.is_parameter else {}),
        }
        for v in model.vars
    ]
    eqs_out = [
        {
            "lhs": eq.lhs,
            "rhs": eq.rhs,
            "is_der": eq.is_der,
            **({"der_var": eq.der_var} if eq.is_der else {}),
        }
        for eq in model.equations
    ]

    return ok_payload({
        "model_name": model.name,
        "vars": vars_out,
        "equations": eqs_out,
        "n_state_vars": sum(1 for v in model.vars if not v.is_parameter),
        "n_params": sum(1 for v in model.vars if v.is_parameter),
        "n_equations": len(model.equations),
    })
