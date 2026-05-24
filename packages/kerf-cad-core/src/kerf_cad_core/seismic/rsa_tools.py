"""
kerf_cad_core.seismic.rsa_tools — LLM tool wrappers for RSA & time-history.

Registers five tools with the Kerf tool registry:

  seismic_build_asce7_spectrum     — ASCE 7-22 design response spectrum (T, Sa)
  seismic_rsa_sdof                 — SDOF peak response from spectrum
  seismic_rsa_mdof                 — Multi-mode RSA via SRSS or CQC
  seismic_newmark_sdof             — Newmark-β SDOF time-history integration
  seismic_newmark_mdof             — Newmark-β MDOF modal superposition

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ASCE/SEI 7-22 §12.9; Chopra (2012) Dynamics of Structures.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.seismic.rsa import (
    build_asce7_spectrum,
    rsa_sdof,
    rsa_mdof,
    newmark_sdof,
    newmark_mdof,
)


# ---------------------------------------------------------------------------
# Tool: seismic_build_asce7_spectrum
# ---------------------------------------------------------------------------

_build_spectrum_spec = ToolSpec(
    name="seismic_build_asce7_spectrum",
    description=(
        "Build an ASCE 7-22 §11.4.5 design response spectrum as a list of "
        "(T, Sa_g) pairs.\n"
        "\n"
        "Four regions:\n"
        "  rising (T < T0):              Sa = SDS·(0.4 + 0.6·T/T0)\n"
        "  constant acceleration (T0–Ts): Sa = SDS\n"
        "  constant velocity (Ts–TL):    Sa = SD1/T\n"
        "  long period (T > TL):         Sa = SD1·TL/T²\n"
        "\n"
        "Pass SDS/SD1 from seismic_site_coefficients output.\n"
        "\n"
        "Returns spectrum (list of [T, Sa_g]), T0, Ts, TL, SDS, SD1, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "SDS": {
                "type": "number",
                "description": "Design spectral acceleration, short period (g). > 0.",
            },
            "SD1": {
                "type": "number",
                "description": "Design spectral acceleration, 1-second period (g). > 0.",
            },
            "TL": {
                "type": "number",
                "description": "Long-period transition period (s). Default 6.0.",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of period points for the spectrum. Default 200.",
            },
        },
        "required": ["SDS", "SD1"],
    },
)


@register(_build_spectrum_spec, write=False)
async def run_build_asce7_spectrum(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("SDS", "SD1"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("TL", "n_points"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = build_asce7_spectrum(a["SDS"], a["SD1"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_rsa_sdof
# ---------------------------------------------------------------------------

_rsa_sdof_spec = ToolSpec(
    name="seismic_rsa_sdof",
    description=(
        "Compute peak SDOF response from a design response spectrum.\n"
        "\n"
        "Given natural frequency ω_n and a spectrum:\n"
        "  Sa_g = spectrum(T_n)  where T_n = 2π/ω_n\n"
        "  Sd   = Sa_g·g / ω_n²   (spectral displacement)\n"
        "  peak_force = m · Sa_g · g\n"
        "\n"
        "Returns T_n, omega_n, Sa_g, Sa_ms2, Sd_m, peak_disp_m, "
        "peak_force_N, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "omega_n": {
                "type": "number",
                "description": "Natural circular frequency (rad/s). > 0.",
            },
            "zeta": {
                "type": "number",
                "description": "Damping ratio (dimensionless, e.g. 0.05 for 5%). In [0, 1).",
            },
            "spectrum_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2},
                "description": (
                    "Design spectrum as list of [T, Sa_g] pairs (T in s, Sa in g). "
                    "Must be sorted by T ascending. "
                    "Use seismic_build_asce7_spectrum to generate."
                ),
            },
            "m": {
                "type": "number",
                "description": "Mass (kg). Default 1.0.",
            },
        },
        "required": ["omega_n", "zeta", "spectrum_pts"],
    },
)


@register(_rsa_sdof_spec, write=False)
async def run_rsa_sdof(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("omega_n", "zeta", "spectrum_pts"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    spectrum_pts = [tuple(p) for p in a["spectrum_pts"]]
    kwargs: dict = {}
    if "m" in a:
        kwargs["m"] = a["m"]

    result = rsa_sdof(a["omega_n"], a["zeta"], spectrum_pts, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_rsa_mdof
# ---------------------------------------------------------------------------

_rsa_mdof_spec = ToolSpec(
    name="seismic_rsa_mdof",
    description=(
        "Multi-mode Response-Spectrum Analysis (RSA) per ASCE 7-22 §12.9.\n"
        "\n"
        "Combines per-mode peak responses via SRSS or CQC:\n"
        "  SRSS: r = √(Σ r_n²)\n"
        "  CQC:  r = √(Σ_i Σ_j ρ_ij · r_i · r_j)\n"
        "  ρ_ij = 8ζ²(1+r)r^1.5 / [(1-r²)² + 4ζ²r(1+r)²], r=ω_j/ω_i\n"
        "\n"
        "Returns per-mode Sa_g, Sd_m, displacements, shear, moment; "
        "combined_disp_m, base_shear_N, base_moment_Nm, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "omega_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Natural circular frequencies, one per mode (rad/s). All > 0.",
            },
            "phi_list": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": (
                    "Mode shapes: phi_list[mode][dof]. "
                    "n_modes × n_dofs array of floats."
                ),
            },
            "gamma_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Modal participation factors, one per mode.",
            },
            "zeta_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Modal damping ratios, one per mode (e.g. 0.05 for 5%).",
            },
            "m_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Lumped masses at each DOF (kg). Length = n_dofs.",
            },
            "spectrum_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2},
                "description": "Design spectrum as list of [T, Sa_g] pairs.",
            },
            "method": {
                "type": "string",
                "enum": ["SRSS", "CQC"],
                "description": "Modal combination method. Default 'CQC'.",
            },
            "h_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Heights of DOFs above base (m) for overturning moment. Optional.",
            },
        },
        "required": ["omega_list", "phi_list", "gamma_list", "zeta_list", "m_list", "spectrum_pts"],
    },
)


@register(_rsa_mdof_spec, write=False)
async def run_rsa_mdof(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("omega_list", "phi_list", "gamma_list", "zeta_list", "m_list", "spectrum_pts"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    spectrum_pts = [tuple(p) for p in a["spectrum_pts"]]
    kwargs: dict = {}
    if "method" in a:
        kwargs["method"] = a["method"]
    if "h_list" in a:
        kwargs["h_list"] = a["h_list"]

    result = rsa_mdof(
        a["omega_list"], a["phi_list"], a["gamma_list"],
        a["zeta_list"], a["m_list"], spectrum_pts,
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_newmark_sdof
# ---------------------------------------------------------------------------

_newmark_sdof_spec = ToolSpec(
    name="seismic_newmark_sdof",
    description=(
        "Newmark constant-average-acceleration (γ=½, β=¼) SDOF time-history.\n"
        "\n"
        "Solves:  m·ü + c·u̇ + k·u = -m·a_g(t)\n"
        "\n"
        "Unconditionally stable for γ=0.5, β=0.25.  Returns full time "
        "histories of displacement u, velocity v, total acceleration a, "
        "and peak values.\n"
        "\n"
        "Returns t, u, v, a_total, a_relative, peak_u_m, peak_v_ms, "
        "peak_a_ms2, omega_n, T_n, zeta, warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m": {
                "type": "number",
                "description": "Mass (kg). Must be > 0.",
            },
            "k": {
                "type": "number",
                "description": "Lateral stiffness (N/m). Must be > 0.",
            },
            "zeta": {
                "type": "number",
                "description": "Damping ratio (dimensionless, e.g. 0.05). In [0, 1).",
            },
            "ag_time": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Ground acceleration time series (m/s²). At least 2 points.",
            },
            "dt": {
                "type": "number",
                "description": "Time step (s). Must be > 0.",
            },
            "gamma": {
                "type": "number",
                "description": "Newmark gamma parameter. Default 0.5.",
            },
            "beta": {
                "type": "number",
                "description": "Newmark beta parameter. Default 0.25.",
            },
        },
        "required": ["m", "k", "zeta", "ag_time", "dt"],
    },
)


@register(_newmark_sdof_spec, write=False)
async def run_newmark_sdof(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m", "k", "zeta", "ag_time", "dt"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("gamma", "beta"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = newmark_sdof(a["m"], a["k"], a["zeta"], a["ag_time"], a["dt"], **kwargs)
    # Truncate long time histories to peak summary only for LLM tool output
    if result.get("ok"):
        n = len(result["t"])
        if n > 1000:
            result["note"] = (
                f"Time histories truncated from {n} to 1000 points for display. "
                "Use peak_u_m, peak_v_ms, peak_a_ms2 for design values."
            )
            result["t"] = result["t"][:1000]
            result["u"] = result["u"][:1000]
            result["v"] = result["v"][:1000]
            result["a_total"] = result["a_total"][:1000]
            result["a_relative"] = result["a_relative"][:1000]
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: seismic_newmark_mdof
# ---------------------------------------------------------------------------

_newmark_mdof_spec = ToolSpec(
    name="seismic_newmark_mdof",
    description=(
        "Newmark-β MDOF time-history via modal superposition.\n"
        "\n"
        "Solves:  M·ü + C·u̇ + K·u = -M·{1}·a_g(t)\n"
        "\n"
        "Extracts eigenvalues/mode shapes, computes modal participation "
        "factors, integrates each mode as SDOF with Newmark constant-average-"
        "acceleration (γ=½, β=¼), then superimposes physical displacements.\n"
        "\n"
        "Best for small systems (≤ 10 DOFs).  All DOFs assumed equally "
        "excited by ground motion (influence vector = {1}).\n"
        "\n"
        "Returns omega_n_list, T_n_list, gamma_list, phi_list, "
        "peak_u_phys (per-dof), peak_u_total (SRSS), warnings.\n"
        "Errors: {ok:false, reason} — never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "M_diag": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Diagonal mass matrix entries (kg). Length = n_dofs.",
            },
            "K": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "Full stiffness matrix (N/m), n_dofs × n_dofs (list of rows).",
            },
            "zeta_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Modal damping ratios per mode (e.g. [0.05]). Padded to n_dofs.",
            },
            "ag_time": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Ground acceleration time series (m/s²). At least 2 points.",
            },
            "dt": {
                "type": "number",
                "description": "Time step (s). Must be > 0.",
            },
        },
        "required": ["M_diag", "K", "zeta_list", "ag_time", "dt"],
    },
)


@register(_newmark_mdof_spec, write=False)
async def run_newmark_mdof(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("M_diag", "K", "zeta_list", "ag_time", "dt"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = newmark_mdof(
        a["M_diag"], a["K"], a["zeta_list"], a["ag_time"], a["dt"]
    )
    # Strip long time histories for LLM output
    if result.get("ok"):
        n_steps = len(a["ag_time"])
        if n_steps > 200:
            result["note"] = (
                f"Time histories omitted ({n_steps} steps). "
                "Use peak_u_phys and peak_u_total for design values."
            )
            result.pop("u_modal", None)
            result.pop("u_phys", None)
    return ok_payload(result)
