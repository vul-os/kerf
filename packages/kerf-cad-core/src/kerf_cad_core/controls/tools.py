"""
kerf_cad_core.controls.tools — LLM tool wrappers for classical control-systems analysis.

Registers tools with the Kerf tool registry:

  controls_second_order_spec      — ωn, ζ → overshoot, settling, rise, peak time
  controls_second_order_inverse   — performance spec → ωn and ζ
  controls_first_order_response   — first-order step & impulse response samples
  controls_second_order_response  — second-order step & impulse response samples
  controls_routh_hurwitz          — Routh array + RHP pole count
  controls_bode_point             — Bode magnitude/phase at ω
  controls_gain_phase_margins     — gain & phase margins by frequency sweep
  controls_steady_state_errors    — Kp/Kv/Ka and steady-state errors
  controls_pid_tuning             — PID tuning (Z-N open, Z-N closed, Cohen-Coon, IMC)
  controls_root_locus_breakaway   — root-locus breakaway/break-in points

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
Nise, N.S. "Control Systems Engineering", 7th ed. (Wiley)

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.controls.system import (
    second_order_spec,
    second_order_inverse,
    first_order_step,
    first_order_impulse,
    second_order_step,
    second_order_impulse,
    routh_hurwitz,
    bode_point,
    gain_phase_margins,
    steady_state_errors,
    pid_zn_open,
    pid_zn_closed,
    pid_cohen_coon,
    pid_imc,
    root_locus_breakaway,
)


# ---------------------------------------------------------------------------
# Tool: controls_second_order_spec
# ---------------------------------------------------------------------------

_second_order_spec_spec = ToolSpec(
    name="controls_second_order_spec",
    description=(
        "Compute second-order closed-loop performance specs from ωn and ζ.\n"
        "\n"
        "Returns peak overshoot %, time to first peak, 10%→90% rise time, "
        "2% and 5% settling times, and damped natural frequency.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wn": {
                "type": "number",
                "description": "Undamped natural frequency ωn (rad/s). Must be > 0.",
            },
            "zeta": {
                "type": "number",
                "description": "Damping ratio ζ. Must be >= 0.",
            },
        },
        "required": ["wn", "zeta"],
    },
)


@register(_second_order_spec_spec, write=False)
async def run_second_order_spec(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("wn") is None:
        return json.dumps({"ok": False, "reason": "wn is required"})
    if a.get("zeta") is None:
        return json.dumps({"ok": False, "reason": "zeta is required"})
    result = second_order_spec(a["wn"], a["zeta"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_second_order_inverse
# ---------------------------------------------------------------------------

_second_order_inverse_spec = ToolSpec(
    name="controls_second_order_inverse",
    description=(
        "Inverse second-order spec: given one performance metric, compute ωn and ζ.\n"
        "\n"
        "Provide exactly one of: overshoot (%), settling_time (s), rise_time (s), "
        "peak_time (s).\n"
        "\n"
        "Note: a single metric does not uniquely determine both ωn and ζ; "
        "the tool assumes a typical ζ for the missing degree of freedom and "
        "flags this in warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "overshoot": {
                "type": "number",
                "description": "Peak overshoot (%). Must be in (0, 100).",
            },
            "settling_time": {
                "type": "number",
                "description": "2% settling time (s). Must be > 0.",
            },
            "rise_time": {
                "type": "number",
                "description": "10%→90% rise time (s). Must be > 0.",
            },
            "peak_time": {
                "type": "number",
                "description": "Time to first peak (s). Must be > 0.",
            },
        },
        "required": [],
    },
)


@register(_second_order_inverse_spec, write=False)
async def run_second_order_inverse(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    kwargs = {}
    for k in ("overshoot", "settling_time", "rise_time", "peak_time"):
        if k in a:
            kwargs[k] = a[k]
    result = second_order_inverse(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_first_order_response
# ---------------------------------------------------------------------------

_first_order_response_spec = ToolSpec(
    name="controls_first_order_response",
    description=(
        "Compute first-order step and impulse response samples.\n"
        "\n"
        "Transfer function: G(s) = K / (τs + 1)\n"
        "\n"
        "Step response:   y(t) = K(1 - e^(-t/τ))\n"
        "Impulse response: y(t) = (K/τ) e^(-t/τ)\n"
        "\n"
        "Returns time and y arrays for the requested response type.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "K": {
                "type": "number",
                "description": "DC gain. Must be finite.",
            },
            "tau": {
                "type": "number",
                "description": "Time constant (s). Must be > 0.",
            },
            "t_samples": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Time sample points (s). All must be >= 0.",
            },
            "response_type": {
                "type": "string",
                "enum": ["step", "impulse"],
                "description": "Response type: 'step' (default) or 'impulse'.",
            },
        },
        "required": ["K", "tau", "t_samples"],
    },
)


@register(_first_order_response_spec, write=False)
async def run_first_order_response(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("K", "tau", "t_samples"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    rtype = a.get("response_type", "step")
    if rtype == "impulse":
        result = first_order_impulse(a["K"], a["tau"], a["t_samples"])
    else:
        result = first_order_step(a["K"], a["tau"], a["t_samples"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_second_order_response
# ---------------------------------------------------------------------------

_second_order_response_spec = ToolSpec(
    name="controls_second_order_response",
    description=(
        "Compute second-order step and impulse response samples.\n"
        "\n"
        "Transfer function: G(s) = K·ωn² / (s² + 2ζωn·s + ωn²)\n"
        "\n"
        "Returns time and y arrays for all damping regimes "
        "(underdamped, critically damped, overdamped).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wn": {
                "type": "number",
                "description": "Undamped natural frequency ωn (rad/s). Must be > 0.",
            },
            "zeta": {
                "type": "number",
                "description": "Damping ratio ζ. Must be >= 0.",
            },
            "t_samples": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Time sample points (s). All must be >= 0.",
            },
            "K": {
                "type": "number",
                "description": "DC gain (default 1.0).",
            },
            "response_type": {
                "type": "string",
                "enum": ["step", "impulse"],
                "description": "Response type: 'step' (default) or 'impulse'.",
            },
        },
        "required": ["wn", "zeta", "t_samples"],
    },
)


@register(_second_order_response_spec, write=False)
async def run_second_order_response(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("wn", "zeta", "t_samples"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs = {}
    if "K" in a:
        kwargs["K"] = a["K"]
    rtype = a.get("response_type", "step")
    if rtype == "impulse":
        result = second_order_impulse(a["wn"], a["zeta"], a["t_samples"], **kwargs)
    else:
        result = second_order_step(a["wn"], a["zeta"], a["t_samples"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_routh_hurwitz
# ---------------------------------------------------------------------------

_routh_hurwitz_spec = ToolSpec(
    name="controls_routh_hurwitz",
    description=(
        "Compute Routh-Hurwitz stability array and RHP pole count.\n"
        "\n"
        "Given characteristic polynomial coefficients [a0, a1, ..., an] "
        "(highest power first) for a_0 s^n + a_1 s^(n-1) + ... + a_n = 0,\n"
        "returns the full Routh array, number of sign changes in the first "
        "column (= number of RHP poles), and a stability flag.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "coeffs": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Characteristic polynomial coefficients [a0, a1, ..., an], "
                    "highest-degree first. Must have >= 2 entries; a0 != 0."
                ),
            },
        },
        "required": ["coeffs"],
    },
)


@register(_routh_hurwitz_spec, write=False)
async def run_routh_hurwitz(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    if a.get("coeffs") is None:
        return json.dumps({"ok": False, "reason": "coeffs is required"})
    result = routh_hurwitz(a["coeffs"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_bode_point
# ---------------------------------------------------------------------------

_bode_point_spec = ToolSpec(
    name="controls_bode_point",
    description=(
        "Compute Bode magnitude (dB) and phase (deg) of a transfer function "
        "at a single frequency ω.\n"
        "\n"
        "Transfer function G(s) = num(s)/den(s) is evaluated at s = jω "
        "using exact complex arithmetic.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Numerator polynomial [b0, b1, ..., bm], highest power first.",
            },
            "den": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Denominator polynomial [a0, a1, ..., an], highest power first.",
            },
            "omega": {
                "type": "number",
                "description": "Frequency (rad/s). Must be > 0.",
            },
        },
        "required": ["num", "den", "omega"],
    },
)


@register(_bode_point_spec, write=False)
async def run_bode_point(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("num", "den", "omega"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = bode_point(a["num"], a["den"], a["omega"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_gain_phase_margins
# ---------------------------------------------------------------------------

_gain_phase_margins_spec = ToolSpec(
    name="controls_gain_phase_margins",
    description=(
        "Compute gain margin, phase margin, and crossover frequencies for "
        "an open-loop transfer function by numeric frequency sweep.\n"
        "\n"
        "Flags poor margins (GM < 6 dB, PM < 30 deg) and instability "
        "in the warnings list.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Open-loop TF numerator polynomial (highest power first).",
            },
            "den": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Open-loop TF denominator polynomial.",
            },
            "omega_range": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "[omega_min, omega_max] or [omega_min, omega_max, n_points]. "
                    "Default: [0.001, 10000, 2000]."
                ),
            },
        },
        "required": ["num", "den"],
    },
)


@register(_gain_phase_margins_spec, write=False)
async def run_gain_phase_margins(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("num", "den"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    kwargs = {}
    if "omega_range" in a:
        kwargs["omega_range"] = a["omega_range"]
    result = gain_phase_margins(a["num"], a["den"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_steady_state_errors
# ---------------------------------------------------------------------------

_steady_state_errors_spec = ToolSpec(
    name="controls_steady_state_errors",
    description=(
        "Compute steady-state errors and error constants for a unity-feedback "
        "closed-loop system from the open-loop transfer function G(s).\n"
        "\n"
        "Returns system type (number of free integrators), Kp, Kv, Ka, "
        "and ess for step, ramp, and parabolic inputs.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num_ol": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Open-loop TF numerator polynomial (highest power first).",
            },
            "den_ol": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Open-loop TF denominator polynomial.",
            },
        },
        "required": ["num_ol", "den_ol"],
    },
)


@register(_steady_state_errors_spec, write=False)
async def run_steady_state_errors(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("num_ol", "den_ol"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = steady_state_errors(a["num_ol"], a["den_ol"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_pid_tuning
# ---------------------------------------------------------------------------

_pid_tuning_spec = ToolSpec(
    name="controls_pid_tuning",
    description=(
        "PID controller tuning by four classical methods.\n"
        "\n"
        "Methods:\n"
        "  'zn_open'    — Ziegler-Nichols open-loop (process reaction curve) "
        "from FOPDT (K, tau, theta).\n"
        "  'zn_closed'  — Ziegler-Nichols closed-loop (ultimate gain/period) "
        "from Ku and Tu.\n"
        "  'cohen_coon' — Cohen-Coon from FOPDT (K, tau, theta).\n"
        "  'imc'        — Lambda/IMC from FOPDT (K, tau, theta, lambda_c).\n"
        "\n"
        "Returns P, PI, PD (where applicable), and PID gains (Kp, Ti, Td, Ki, Kd).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["zn_open", "zn_closed", "cohen_coon", "imc"],
                "description": "Tuning method.",
            },
            "K": {
                "type": "number",
                "description": "FOPDT process gain (required for zn_open, cohen_coon, imc).",
            },
            "tau": {
                "type": "number",
                "description": "FOPDT time constant (s) (required for zn_open, cohen_coon, imc).",
            },
            "theta": {
                "type": "number",
                "description": "FOPDT dead time (s) (required for zn_open, cohen_coon, imc).",
            },
            "Ku": {
                "type": "number",
                "description": "Ultimate gain (required for zn_closed).",
            },
            "Tu": {
                "type": "number",
                "description": "Ultimate period (s) (required for zn_closed).",
            },
            "lambda_c": {
                "type": "number",
                "description": "Closed-loop time constant (s) (required for imc).",
            },
        },
        "required": ["method"],
    },
)


@register(_pid_tuning_spec, write=False)
async def run_pid_tuning(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    method = a.get("method")
    if not method:
        return json.dumps({"ok": False, "reason": "method is required"})

    if method == "zn_open":
        for field in ("K", "tau", "theta"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required for zn_open"})
        result = pid_zn_open(a["K"], a["tau"], a["theta"])

    elif method == "zn_closed":
        for field in ("Ku", "Tu"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required for zn_closed"})
        result = pid_zn_closed(a["Ku"], a["Tu"])

    elif method == "cohen_coon":
        for field in ("K", "tau", "theta"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required for cohen_coon"})
        result = pid_cohen_coon(a["K"], a["tau"], a["theta"])

    elif method == "imc":
        for field in ("K", "tau", "theta", "lambda_c"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required for imc"})
        result = pid_imc(a["K"], a["tau"], a["theta"], a["lambda_c"])

    else:
        return json.dumps({"ok": False, "reason": f"Unknown method {method!r}. Use: zn_open, zn_closed, cohen_coon, imc."})

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: controls_root_locus_breakaway
# ---------------------------------------------------------------------------

_root_locus_breakaway_spec = ToolSpec(
    name="controls_root_locus_breakaway",
    description=(
        "Find real-axis breakaway and break-in points of the root locus.\n"
        "\n"
        "For G(s)H(s) = K·num(s)/den(s), the breakaway points satisfy "
        "d/ds[den(s)/num(s)] = 0, i.e., den'·num - den·num' = 0.\n"
        "\n"
        "Returns real roots of this characteristic equation (candidate points; "
        "verify which lie on real-axis root locus segments).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Open-loop TF numerator polynomial (highest power first).",
            },
            "den": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Open-loop TF denominator polynomial.",
            },
        },
        "required": ["num", "den"],
    },
)


@register(_root_locus_breakaway_spec, write=False)
async def run_root_locus_breakaway(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    for field in ("num", "den"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})
    result = root_locus_breakaway(a["num"], a["den"])
    return ok_payload(result)
