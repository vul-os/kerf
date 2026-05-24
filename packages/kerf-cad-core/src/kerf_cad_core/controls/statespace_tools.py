"""
kerf_cad_core.controls.statespace_tools — LLM tool wrappers for modern state-space control.

Registers tools with the Kerf tool registry:

  controls_ss_model              — validate A,B,C,D; return dims + eigenvalues
  controls_controllability       — controllability matrix + rank test
  controls_observability         — observability matrix + rank test
  controls_pole_placement        — Ackermann SISO pole placement → gain K
  controls_lqr                   — continuous-time LQR (CARE) → P, K
  controls_luenberger             — Luenberger observer gains L
  controls_c2d                   — ZOH discretisation → Ad, Bd
  controls_discrete_stability    — |eigenvalues| < 1 check for discrete system
  controls_digital_pid_step      — digital PID velocity-form step update

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
Franklin, G., Powell, J.D., Emami-Naeini, A. "Feedback Control of Dynamic Systems", 8th ed.
Åström, K.J. & Wittenmark, B. "Computer-Controlled Systems", 3rd ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.controls.statespace import (
    ss_model,
    controllability_matrix,
    observability_matrix,
    pole_placement_ackermann,
    lqr,
    luenberger_gains,
    c2d,
    discrete_stability,
    digital_pid_step,
)


# ---------------------------------------------------------------------------
# Tool: controls_ss_model
# ---------------------------------------------------------------------------

_ss_model_spec = ToolSpec(
    name="controls_ss_model",
    description=(
        "Validate and describe a continuous-time state-space model (A, B, C, D).\n"
        "\n"
        "State equation:  dx/dt = A x + B u\n"
        "Output equation: y = C x + D u\n"
        "\n"
        "Returns dimension info, eigenvalues of A, and continuous-time stability.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state (system) matrix."},
            "B": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×p input matrix."},
            "C": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "q×n output matrix."},
            "D": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "q×p feedthrough matrix."},
        },
        "required": ["A", "B", "C", "D"],
    },
)


@register(_ss_model_spec, write=False)
async def run_ss_model(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "B", "C", "D"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = ss_model(a["A"], a["B"], a["C"], a["D"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_controllability
# ---------------------------------------------------------------------------

_controllability_spec = ToolSpec(
    name="controls_controllability",
    description=(
        "Compute the controllability matrix [B, AB, A²B, ..., A^(n-1)B] and rank.\n"
        "\n"
        "Returns the full controllability matrix, its rank, and whether the system "
        "is fully controllable (rank == n_states).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state matrix."},
            "B": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×p input matrix."},
        },
        "required": ["A", "B"],
    },
)


@register(_controllability_spec, write=False)
async def run_controllability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "B"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = controllability_matrix(a["A"], a["B"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_observability
# ---------------------------------------------------------------------------

_observability_spec = ToolSpec(
    name="controls_observability",
    description=(
        "Compute the observability matrix [C; CA; CA²; ...; CA^(n-1)] and rank.\n"
        "\n"
        "Returns the full observability matrix, its rank, and whether the system "
        "is fully observable (rank == n_states).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state matrix."},
            "C": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "q×n output matrix."},
        },
        "required": ["A", "C"],
    },
)


@register(_observability_spec, write=False)
async def run_observability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = observability_matrix(a["A"], a["C"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_pole_placement
# ---------------------------------------------------------------------------

_pole_placement_spec = ToolSpec(
    name="controls_pole_placement",
    description=(
        "SISO pole placement via Ackermann's formula.\n"
        "\n"
        "Finds state-feedback gain K (1×n) such that the closed-loop eigenvalues "
        "of (A - B·K) equal the desired poles.\n"
        "\n"
        "desired_poles: list of n real floats (for real poles) or "
        "[[re, im], [re, -im], ...] pairs for complex conjugate pairs.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state matrix."},
            "B": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×1 input matrix (single column)."},
            "desired_poles": {
                "type": "array",
                "items": {},
                "description": (
                    "n desired closed-loop poles. Each entry is a real number or "
                    "a [re, im] pair for complex poles."
                ),
            },
        },
        "required": ["A", "B", "desired_poles"],
    },
)


@register(_pole_placement_spec, write=False)
async def run_pole_placement(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "B", "desired_poles"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = pole_placement_ackermann(a["A"], a["B"], a["desired_poles"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_lqr
# ---------------------------------------------------------------------------

_lqr_spec = ToolSpec(
    name="controls_lqr",
    description=(
        "Continuous-time Linear Quadratic Regulator (LQR).\n"
        "\n"
        "Minimises J = ∫₀^∞ (xᵀQx + uᵀRu) dt by solving the continuous "
        "algebraic Riccati equation (CARE): Aᵀ P + P A - P B R⁻¹ Bᵀ P + Q = 0.\n"
        "\n"
        "Returns the Riccati matrix P and optimal state-feedback gain K = R⁻¹ Bᵀ P.\n"
        "\n"
        "Q must be positive semi-definite; R must be positive definite.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state matrix."},
            "B": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×p input matrix."},
            "Q": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state weighting matrix (positive semi-definite)."},
            "R": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "p×p input weighting matrix (positive definite)."},
        },
        "required": ["A", "B", "Q", "R"],
    },
)


@register(_lqr_spec, write=False)
async def run_lqr(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "B", "Q", "R"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = lqr(a["A"], a["B"], a["Q"], a["R"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_luenberger
# ---------------------------------------------------------------------------

_luenberger_spec = ToolSpec(
    name="controls_luenberger",
    description=(
        "Luenberger observer gain matrix L for SISO systems.\n"
        "\n"
        "Uses duality: applies Ackermann's formula to (Aᵀ, Cᵀ) to find L such "
        "that eigenvalues of (A - L·C) equal the desired observer poles.\n"
        "\n"
        "Observer poles are typically 3–5× faster than controller poles (more "
        "negative real part) for good state estimation.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n state matrix."},
            "C": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "1×n output matrix (single-output system)."},
            "desired_observer_poles": {
                "type": "array",
                "items": {},
                "description": "n desired observer pole locations (real or [re, im] pairs).",
            },
        },
        "required": ["A", "C", "desired_observer_poles"],
    },
)


@register(_luenberger_spec, write=False)
async def run_luenberger(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "C", "desired_observer_poles"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = luenberger_gains(a["A"], a["C"], a["desired_observer_poles"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_c2d
# ---------------------------------------------------------------------------

_c2d_spec = ToolSpec(
    name="controls_c2d",
    description=(
        "Zero-order-hold (ZOH) discretisation of a continuous-time state-space model.\n"
        "\n"
        "Converts (A, B) → (Ad, Bd) using the exact ZOH formula:\n"
        "  Ad = exp(A·dt)\n"
        "  Bd = (∫₀^dt exp(A·s) ds) B\n"
        "\n"
        "Computed via matrix exponential of the augmented system (exact for any A).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "A": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×n continuous-time state matrix."},
            "B": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                  "description": "n×p continuous-time input matrix."},
            "dt": {"type": "number", "description": "Sampling interval (s). Must be > 0."},
        },
        "required": ["A", "B", "dt"],
    },
)


@register(_c2d_spec, write=False)
async def run_c2d(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("A", "B", "dt"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = c2d(a["A"], a["B"], a["dt"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_discrete_stability
# ---------------------------------------------------------------------------

_discrete_stability_spec = ToolSpec(
    name="controls_discrete_stability",
    description=(
        "Check discrete-time stability of a state matrix.\n"
        "\n"
        "A discrete-time system x[k+1] = Ad x[k] is stable iff all eigenvalues "
        "of Ad lie strictly inside the unit circle (|λ| < 1).\n"
        "\n"
        "Returns eigenvalues with magnitudes, max magnitude, and stability flag.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Ad": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                   "description": "n×n discrete-time state matrix."},
        },
        "required": ["Ad"],
    },
)


@register(_discrete_stability_spec, write=False)
async def run_discrete_stability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("Ad") is None:
        return json.dumps({"ok": False, "reason": "Ad is required"})
    result = discrete_stability(a["Ad"])
    return ok_payload(result) if result["ok"] else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: controls_digital_pid_step
# ---------------------------------------------------------------------------

_digital_pid_step_spec = ToolSpec(
    name="controls_digital_pid_step",
    description=(
        "Compute one step of a digital PID controller (velocity/incremental form).\n"
        "\n"
        "Δu[k] = Kp(e[k]-e[k-1]) + Ki·dt·e[k] + Kd/dt·(e[k]-2e[k-1]+e[k-2])\n"
        "u[k]  = u[k-1] + Δu[k]\n"
        "\n"
        "The velocity form naturally avoids integrator windup.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Kp":    {"type": "number", "description": "Proportional gain."},
            "Ki":    {"type": "number", "description": "Integral gain."},
            "Kd":    {"type": "number", "description": "Derivative gain."},
            "dt":    {"type": "number", "description": "Sampling interval (s). Must be > 0."},
            "e_k":   {"type": "number", "description": "Current error e[k]."},
            "e_km1": {"type": "number", "description": "Previous error e[k-1]."},
            "e_km2": {"type": "number", "description": "Two-steps-ago error e[k-2]."},
            "u_km1": {"type": "number", "description": "Previous control output u[k-1]."},
        },
        "required": ["Kp", "Ki", "Kd", "dt", "e_k", "e_km1", "e_km2", "u_km1"],
    },
)


@register(_digital_pid_step_spec, write=False)
async def run_digital_pid_step(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("Kp", "Ki", "Kd", "dt", "e_k", "e_km1", "e_km2", "u_km1"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = digital_pid_step(
        a["Kp"], a["Ki"], a["Kd"], a["dt"],
        a["e_k"], a["e_km1"], a["e_km2"], a["u_km1"],
    )
    return ok_payload(result) if result["ok"] else json.dumps(result)
