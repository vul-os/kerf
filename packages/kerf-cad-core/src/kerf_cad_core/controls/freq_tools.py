"""
kerf_cad_core.controls.freq_tools — LLM tool wrappers for frequency-domain and
time-domain analysis of transfer functions.

Registers tools with the Kerf tool registry:

  controls_bode_sweep      — Bode plot data (magnitude + phase arrays) over a
                              log-spaced frequency range (Ogata §8)
  controls_nyquist_sweep   — Nyquist diagram data Re(G(jω)), Im(G(jω)) for
                              stability analysis (Nyquist 1932)
  controls_tf_step_response — Step/impulse response array from a TF (any order)
                              via zero-order-hold simulation

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
Nyquist, H. (1932). "Regeneration Theory." Bell System Tech. J. 11, 126–147.
Franklin, G.F., Powell, J.D., Emami-Naeini, A. "Feedback Control of Dynamic
    Systems", 8th ed. (Prentice Hall).

Author: imranparuk
"""
from __future__ import annotations

import cmath
import json
import math

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401


# ---------------------------------------------------------------------------
# Internal helpers (duplicated locally so this module is self-contained)
# ---------------------------------------------------------------------------

def _poly_eval_c(coeffs: list[float], s: complex) -> complex:
    """Horner evaluation — highest power first."""
    result = complex(0.0)
    for c in coeffs:
        result = result * s + c
    return result


def _bode_arrays(
    num: list[float],
    den: list[float],
    omega: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Bode magnitude (dB) and unwrapped phase (deg) arrays.

    Phase is unwrapped via numpy.unwrap for correct -180° crossing detection
    (essential for phase-margin computation).

    References: Ogata §8-2; Franklin §6.1.
    """
    mag_db = np.zeros(len(omega))
    phase_rad = np.zeros(len(omega))
    for k, w in enumerate(omega):
        s = complex(0.0, w)
        G = _poly_eval_c(num, s)
        D = _poly_eval_c(den, s)
        if abs(D) < 1e-300:
            mag_db[k] = math.inf
            phase_rad[k] = 0.0
        else:
            H = G / D
            m = abs(H)
            mag_db[k] = 20.0 * math.log10(m) if m > 0 else -math.inf
            phase_rad[k] = cmath.phase(H)
    # Unwrap phase so -180° crossings are monotone
    phase_unwrapped = np.unwrap(phase_rad)
    return mag_db, np.degrees(phase_unwrapped)


def _find_margins(
    omega: np.ndarray,
    mag_db: np.ndarray,
    phase_deg: np.ndarray,
) -> dict:
    """
    Locate gain-crossover (|G|=0 dB) and phase-crossover (∠G=-180°) frequencies.

    Returns gain_margin_db, phase_margin_deg, omega_gc, omega_pc.
    Values are None when the crossover is not found in the sweep range.

    References: Ogata §9-3; Franklin §6.3.
    """
    gm_db = None
    pm_deg = None
    omega_gc = None
    omega_pc = None

    # Gain crossover: mag_db crosses 0 (from above)
    for i in range(len(omega) - 1):
        m0, m1 = mag_db[i], mag_db[i + 1]
        if math.isnan(m0) or math.isnan(m1):
            continue
        if m0 * m1 <= 0:
            frac = abs(m0) / (abs(m0) + abs(m1))
            omega_gc = float(omega[i] + frac * (omega[i + 1] - omega[i]))
            ph_gc = phase_deg[i] + frac * (phase_deg[i + 1] - phase_deg[i])
            pm_deg = 180.0 + ph_gc
            break

    # Phase crossover: phase crosses -180° (unwrapped)
    for i in range(len(omega) - 1):
        p0, p1 = phase_deg[i], phase_deg[i + 1]
        if math.isnan(p0) or math.isnan(p1):
            continue
        if (p0 + 180.0) * (p1 + 180.0) <= 0:
            frac = abs(p0 + 180.0) / (abs(p0 + 180.0) + abs(p1 + 180.0))
            omega_pc = float(omega[i] + frac * (omega[i + 1] - omega[i]))
            mag_pc = mag_db[i] + frac * (mag_db[i + 1] - mag_db[i])
            gm_db = float(-mag_pc)
            break

    warnings: list[str] = []
    if gm_db is not None and gm_db < 6.0:
        warnings.append(f"POOR_GM: gain margin {gm_db:.1f} dB < 6 dB")
    if pm_deg is not None and pm_deg < 30.0:
        warnings.append(f"POOR_PM: phase margin {pm_deg:.1f} deg < 30 deg")
    if omega_gc is None:
        warnings.append("NO_GAIN_CROSSOVER: |G(jω)| never crosses 0 dB in sweep range")
    if omega_pc is None:
        warnings.append("NO_PHASE_CROSSOVER: ∠G(jω) never crosses -180° in sweep range")

    return dict(
        gain_margin_db=gm_db,
        phase_margin_deg=pm_deg,
        omega_gc=omega_gc,
        omega_pc=omega_pc,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Tool: controls_bode_sweep
# ---------------------------------------------------------------------------

_bode_sweep_spec = ToolSpec(
    name="controls_bode_sweep",
    description=(
        "Compute a full Bode diagram — magnitude (dB) and phase (deg) arrays — "
        "for a transfer function G(s) = num(s)/den(s) over a log-spaced frequency "
        "range.\n"
        "\n"
        "Phase is unwrapped so -180° crossings are monotone (correct margin "
        "detection for higher-order TFs).\n"
        "\n"
        "Also returns gain margin, phase margin, and crossover frequencies.\n"
        "\n"
        "Use the returned omega, mag_db, phase_deg arrays directly for plotting.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises.\n"
        "\n"
        "References: Ogata §8–9; Franklin §6.1–6.3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "TF numerator polynomial [b0, b1, ..., bm], highest power first."
                ),
            },
            "den": {
                "type": "array",
                "items": {"type": "number"},
                "description": "TF denominator polynomial [a0, a1, ..., an], highest power first.",
            },
            "omega_min": {
                "type": "number",
                "description": "Minimum frequency (rad/s). Must be > 0. Default 0.01.",
            },
            "omega_max": {
                "type": "number",
                "description": "Maximum frequency (rad/s). Must be > omega_min. Default 1000.",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of log-spaced frequency points. Default 500; max 2000.",
            },
        },
        "required": ["num", "den"],
    },
)


@register(_bode_sweep_spec, write=False)
async def run_controls_bode_sweep(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("num", "den"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    try:
        num = [float(x) for x in a["num"]]
        den = [float(x) for x in a["den"]]
    except (TypeError, ValueError) as exc:
        return err_payload(f"num/den must contain numbers: {exc}", "BAD_ARGS")

    if not num or not den:
        return json.dumps({"ok": False, "reason": "num and den must be non-empty"})
    if abs(den[0]) < 1e-15:
        return json.dumps({"ok": False, "reason": "Leading denominator coefficient must be non-zero"})

    omega_min = float(a.get("omega_min", 0.01))
    omega_max = float(a.get("omega_max", 1000.0))
    n_points = int(a.get("n_points", 500))
    n_points = max(20, min(n_points, 2000))

    if omega_min <= 0:
        return json.dumps({"ok": False, "reason": "omega_min must be > 0"})
    if omega_max <= omega_min:
        return json.dumps({"ok": False, "reason": "omega_max must be > omega_min"})

    try:
        omega = np.logspace(math.log10(omega_min), math.log10(omega_max), n_points)
        mag_db, phase_deg = _bode_arrays(num, den, omega)
        margins = _find_margins(omega, mag_db, phase_deg)
    except Exception as exc:
        return err_payload(f"computation error: {exc}", "COMPUTE_ERR")

    return ok_payload({
        "omega": omega.tolist(),
        "mag_db": [round(v, 4) for v in mag_db.tolist()],
        "phase_deg": [round(v, 4) for v in phase_deg.tolist()],
        "n_points": n_points,
        "omega_min": omega_min,
        "omega_max": omega_max,
        "gain_margin_db": margins["gain_margin_db"],
        "phase_margin_deg": margins["phase_margin_deg"],
        "omega_gc": margins["omega_gc"],
        "omega_pc": margins["omega_pc"],
        "warnings": margins["warnings"],
    })


# ---------------------------------------------------------------------------
# Tool: controls_nyquist_sweep
# ---------------------------------------------------------------------------

_nyquist_sweep_spec = ToolSpec(
    name="controls_nyquist_sweep",
    description=(
        "Compute Nyquist diagram data — Re(G(jω)) and Im(G(jω)) — for a "
        "transfer function over a log-spaced frequency sweep.\n"
        "\n"
        "The Nyquist stability criterion: a stable open-loop TF G(s) gives a "
        "stable closed-loop if the Nyquist plot does not encircle the −1+j0 point "
        "(for unity negative feedback).\n"
        "\n"
        "Returns parallel arrays real_g, imag_g, mag, phase_deg and the "
        "encirclement count (approximate, positive = CCW).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises.\n"
        "\n"
        "References: Nyquist (1932); Ogata §9-2; Franklin §6.4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num": {
                "type": "array",
                "items": {"type": "number"},
                "description": "TF numerator polynomial (highest power first).",
            },
            "den": {
                "type": "array",
                "items": {"type": "number"},
                "description": "TF denominator polynomial (highest power first).",
            },
            "omega_min": {
                "type": "number",
                "description": "Minimum frequency (rad/s). Default 0.001.",
            },
            "omega_max": {
                "type": "number",
                "description": "Maximum frequency (rad/s). Default 10000.",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of frequency points (default 1000; max 4000).",
            },
        },
        "required": ["num", "den"],
    },
)


@register(_nyquist_sweep_spec, write=False)
async def run_controls_nyquist_sweep(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("num", "den"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    try:
        num = [float(x) for x in a["num"]]
        den = [float(x) for x in a["den"]]
    except (TypeError, ValueError) as exc:
        return err_payload(f"num/den must contain numbers: {exc}", "BAD_ARGS")

    if not num or not den:
        return json.dumps({"ok": False, "reason": "num and den must be non-empty"})
    if abs(den[0]) < 1e-15:
        return json.dumps({"ok": False, "reason": "Leading denominator coefficient must be non-zero"})

    omega_min = float(a.get("omega_min", 0.001))
    omega_max = float(a.get("omega_max", 10000.0))
    n_points = int(a.get("n_points", 1000))
    n_points = max(20, min(n_points, 4000))

    if omega_min <= 0:
        return json.dumps({"ok": False, "reason": "omega_min must be > 0"})
    if omega_max <= omega_min:
        return json.dumps({"ok": False, "reason": "omega_max must be > omega_min"})

    try:
        omega = np.logspace(math.log10(omega_min), math.log10(omega_max), n_points)
        real_g = []
        imag_g = []
        mag_arr = []
        phase_arr = []
        for w in omega:
            s = complex(0.0, w)
            N = _poly_eval_c(num, s)
            D = _poly_eval_c(den, s)
            if abs(D) < 1e-300:
                G = complex(math.inf, 0.0)
            else:
                G = N / D
            real_g.append(round(G.real, 8))
            imag_g.append(round(G.imag, 8))
            mag_arr.append(round(abs(G), 8))
            phase_arr.append(round(math.degrees(cmath.phase(G)), 4))

        # Approximate winding number around -1+0j using winding angle sum
        # (counts how many times the curve encircles -1+0j)
        winding = 0.0
        for i in range(len(real_g) - 1):
            x0, y0 = real_g[i] + 1, imag_g[i]     # shift to origin at -1+0j
            x1, y1 = real_g[i + 1] + 1, imag_g[i + 1]
            cross = x0 * y1 - x1 * y0
            dot = x0 * x1 + y0 * y1
            dtheta = math.atan2(cross, dot)
            winding += dtheta
        encirclements = round(winding / (2 * math.pi))

    except Exception as exc:
        return err_payload(f"computation error: {exc}", "COMPUTE_ERR")

    warnings: list[str] = []
    if abs(encirclements) > 0:
        warnings.append(
            f"ENCIRCLES_MINUS1: Nyquist curve encircles -1+0j approximately "
            f"{int(encirclements)} time(s) — closed-loop may be unstable."
        )

    return ok_payload({
        "omega": omega.tolist(),
        "real_g": real_g,
        "imag_g": imag_g,
        "mag": mag_arr,
        "phase_deg": phase_arr,
        "n_points": n_points,
        "encirclements_approx": int(encirclements),
        "warnings": warnings,
    })


# ---------------------------------------------------------------------------
# Tool: controls_tf_step_response
# ---------------------------------------------------------------------------

_tf_step_response_spec = ToolSpec(
    name="controls_tf_step_response",
    description=(
        "Compute the step or impulse response of an arbitrary-order transfer "
        "function G(s) = num(s)/den(s) over a user-defined time array.\n"
        "\n"
        "Simulation uses direct-form II difference equations with zero-order-hold "
        "discretisation (Euler) — works for any order TF.\n"
        "\n"
        "Returns parallel time (t) and output (y) arrays suitable for plotting.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises.\n"
        "\n"
        "References: Ogata §5; Franklin §3.3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "num": {
                "type": "array",
                "items": {"type": "number"},
                "description": "TF numerator polynomial [b0, ..., bm], highest power first.",
            },
            "den": {
                "type": "array",
                "items": {"type": "number"},
                "description": "TF denominator polynomial [a0, ..., an], highest power first.",
            },
            "t_end": {
                "type": "number",
                "description": "End time (s). Must be > 0. Default: auto-estimated from poles.",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of time points. Default 500; max 5000.",
            },
            "response_type": {
                "type": "string",
                "enum": ["step", "impulse"],
                "description": "Response type: 'step' (default) or 'impulse'.",
            },
        },
        "required": ["num", "den"],
    },
)


@register(_tf_step_response_spec, write=False)
async def run_controls_tf_step_response(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("num", "den"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    try:
        num = [float(x) for x in a["num"]]
        den = [float(x) for x in a["den"]]
    except (TypeError, ValueError) as exc:
        return err_payload(f"num/den must contain numbers: {exc}", "BAD_ARGS")

    if not num or not den:
        return json.dumps({"ok": False, "reason": "num and den must be non-empty"})
    if abs(den[0]) < 1e-15:
        return json.dumps({"ok": False, "reason": "Leading denominator coefficient must be non-zero"})

    response_type = a.get("response_type", "step")
    n_points = int(a.get("n_points", 500))
    n_points = max(20, min(n_points, 5000))

    # Estimate t_end from dominant pole if not supplied
    t_end = a.get("t_end")
    if t_end is None:
        # Estimate from poles: t_end ≈ 10 / min(|Re(pole)|) for LHP poles
        try:
            poles = np.roots(den)
            lhp_reals = [abs(p.real) for p in poles if p.real < 0]
            if lhp_reals:
                sigma_min = min(lhp_reals)
                t_end = max(10.0 / sigma_min, 1.0)
            else:
                t_end = 20.0
        except Exception:
            t_end = 20.0
    else:
        t_end = float(t_end)
        if t_end <= 0:
            return json.dumps({"ok": False, "reason": "t_end must be > 0"})

    t_end = min(t_end, 1e6)  # cap to avoid memory issues

    try:
        t = np.linspace(0.0, t_end, n_points)
        dt = float(t[1] - t[0]) if n_points > 1 else 1e-3

        # Normalise coefficients
        a0 = den[0]
        num_n = [c / a0 for c in num]
        den_n = [c / a0 for c in den]
        n = len(den_n) - 1  # system order
        m = len(num_n) - 1
        if m < n:
            num_n = [0.0] * (n - m) + num_n

        # Direct-form II simulation
        y = np.zeros(n_points)
        x = np.zeros(n)  # delay register
        for k in range(n_points):
            u = 1.0 if response_type == "step" else (1.0 / dt if k == 0 else 0.0)
            w = u
            for i in range(n):
                w -= den_n[i + 1] * x[i]
            out = num_n[0] * w
            for i in range(n):
                out += num_n[i + 1] * x[i]
            y[k] = out
            x = np.roll(x, 1)
            x[0] = w

        steady_state = float(y[-1]) if len(y) > 0 else None
        warnings: list[str] = []
        if not math.isfinite(steady_state):
            warnings.append("UNSTABLE: response is diverging (infinite or NaN final value)")

    except Exception as exc:
        return err_payload(f"computation error: {exc}", "COMPUTE_ERR")

    return ok_payload({
        "t": [round(v, 6) for v in t.tolist()],
        "y": [round(v, 8) for v in y.tolist()],
        "n_points": n_points,
        "t_end": t_end,
        "response_type": response_type,
        "steady_state": round(steady_state, 8) if steady_state is not None else None,
        "warnings": warnings,
    })
