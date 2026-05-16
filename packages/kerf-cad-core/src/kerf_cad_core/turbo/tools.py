"""
kerf_cad_core.turbo.tools — LLM tool wrappers for turbomachinery blade/stage
design.

Registers tools with the Kerf tool registry:

  turbo_euler_work                — Euler turbomachine equation W = U·ΔCθ
  turbo_velocity_triangles_axial  — Axial stage velocity triangles
  turbo_velocity_triangles_centrifugal — Centrifugal impeller exit triangles
  turbo_dimensionless_groups      — Flow φ, work ψ, power coefficients
  turbo_specific_speed_diameter   — Dimensionless Ω_s and Δ_s
  turbo_cordier_optimum           — Cordier-line optimum specific diameter
  turbo_degree_of_reaction        — Stage degree of reaction R
  turbo_axial_stage               — Full axial stage analysis
  turbo_centrifugal_impeller      — Centrifugal impeller design point
  turbo_fan_affinity              — Fan / pump affinity laws
  turbo_stage_efficiency          — Isentropic & polytropic efficiency
  turbo_surge_choke_margin        — Surge/choke margin check

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
Dixon, S.L. & Hall, C.A. "Fluid Mechanics and Thermodynamics of
  Turbomachinery", 7th ed., Butterworth-Heinemann (2014).
Saravanamuttoo, H.I.H. et al. "Gas Turbine Theory", 7th ed.,
  Pearson (2017).

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.turbo.stage import (
    euler_work,
    velocity_triangles_axial,
    velocity_triangles_centrifugal,
    dimensionless_groups,
    specific_speed_diameter,
    cordier_optimum,
    degree_of_reaction,
    axial_stage,
    centrifugal_impeller,
    fan_affinity,
    stage_efficiency,
    surge_choke_margin,
)


# ---------------------------------------------------------------------------
# Tool: turbo_euler_work
# ---------------------------------------------------------------------------

_euler_work_spec = ToolSpec(
    name="turbo_euler_work",
    description=(
        "Compute the Euler turbomachine specific work W = U · ΔCθ.\n"
        "\n"
        "The Euler equation gives the ideal specific work transferred "
        "between fluid and rotor for any turbomachine.\n"
        "  Compressor/pump: ΔCθ > 0 (work input)\n"
        "  Turbine: ΔCθ < 0 (work extracted)\n"
        "\n"
        "Returns W_specific (J/kg). Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "U": {
                "type": "number",
                "description": "Blade (peripheral) speed (m/s). Must be > 0.",
            },
            "dCtheta": {
                "type": "number",
                "description": (
                    "Change in whirl velocity ΔCθ = Cθ2 − Cθ1 (m/s). "
                    "Positive = work input (compressor), negative = extraction (turbine)."
                ),
            },
        },
        "required": ["U", "dCtheta"],
    },
)


@register(_euler_work_spec, write=False)
async def run_turbo_euler_work(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("U") is None:
        return json.dumps({"ok": False, "reason": "U is required"})
    if a.get("dCtheta") is None:
        return json.dumps({"ok": False, "reason": "dCtheta is required"})

    result = euler_work(a["U"], a["dCtheta"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_velocity_triangles_axial
# ---------------------------------------------------------------------------

_vt_axial_spec = ToolSpec(
    name="turbo_velocity_triangles_axial",
    description=(
        "Compute velocity triangles for an axial turbomachinery stage.\n"
        "\n"
        "Assumes constant axial velocity Ca. Returns absolute angles α, "
        "relative angles β, absolute velocities C, relative velocities W, "
        "whirl (swirl) components, and Euler specific work.\n"
        "\n"
        "Convention: angles measured from the axial direction; positive "
        "in the direction of blade rotation.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "U": {
                "type": "number",
                "description": "Blade speed at mean radius (m/s). Must be > 0.",
            },
            "Ca": {
                "type": "number",
                "description": "Axial velocity component (m/s). Must be > 0.",
            },
            "alpha1_deg": {
                "type": "number",
                "description": (
                    "Absolute inlet flow angle from axial (degrees). "
                    "Range ±89°. Typically 0° for axial entry."
                ),
            },
            "alpha2_deg": {
                "type": "number",
                "description": (
                    "Absolute exit flow angle from axial (degrees). "
                    "Range ±89°."
                ),
            },
        },
        "required": ["U", "Ca", "alpha1_deg", "alpha2_deg"],
    },
)


@register(_vt_axial_spec, write=False)
async def run_turbo_velocity_triangles_axial(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("U", "Ca", "alpha1_deg", "alpha2_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = velocity_triangles_axial(
        a["U"], a["Ca"], a["alpha1_deg"], a["alpha2_deg"]
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_velocity_triangles_centrifugal
# ---------------------------------------------------------------------------

_vt_centrifugal_spec = ToolSpec(
    name="turbo_velocity_triangles_centrifugal",
    description=(
        "Compute velocity triangles at the exit of a centrifugal impeller.\n"
        "\n"
        "Slip factor σ accounts for the finite blade count reducing the "
        "ideal whirl velocity. Returns ideal and actual exit whirl velocities, "
        "absolute and relative exit velocities, and Euler specific work.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "U2": {
                "type": "number",
                "description": "Tip blade speed at impeller exit (m/s). Must be > 0.",
            },
            "Cr2": {
                "type": "number",
                "description": "Radial velocity component at exit (m/s). Must be > 0.",
            },
            "beta2_deg": {
                "type": "number",
                "description": (
                    "Blade angle from radial at exit (degrees). "
                    "Negative = backward sweep (default −30°). "
                    "Range ±89°."
                ),
            },
            "slip_factor": {
                "type": "number",
                "description": (
                    "Slip factor σ (0 < σ ≤ 1). If omitted, default 0.9 is used."
                ),
            },
        },
        "required": ["U2", "Cr2"],
    },
)


@register(_vt_centrifugal_spec, write=False)
async def run_turbo_velocity_triangles_centrifugal(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("U2") is None:
        return json.dumps({"ok": False, "reason": "U2 is required"})
    if a.get("Cr2") is None:
        return json.dumps({"ok": False, "reason": "Cr2 is required"})

    kwargs: dict = {}
    if "beta2_deg" in a:
        kwargs["beta2_deg"] = a["beta2_deg"]
    if "slip_factor" in a:
        kwargs["slip_factor"] = a["slip_factor"]

    result = velocity_triangles_centrifugal(a["U2"], a["Cr2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_dimensionless_groups
# ---------------------------------------------------------------------------

_dim_groups_spec = ToolSpec(
    name="turbo_dimensionless_groups",
    description=(
        "Compute dimensionless turbomachinery performance groups.\n"
        "\n"
        "Returns:\n"
        "  φ = Ca/U      flow coefficient\n"
        "  ψ = ΔCθ/U     work/head (loading) coefficient\n"
        "  C_P = φ·ψ     power coefficient\n"
        "  M_U = U/a     blade Mach number (if speed of sound provided)\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "U": {
                "type": "number",
                "description": "Blade (tip) speed (m/s). Must be > 0.",
            },
            "Ca": {
                "type": "number",
                "description": "Axial (meridional) velocity (m/s). Must be > 0.",
            },
            "dCtheta": {
                "type": "number",
                "description": "Change in whirl velocity ΔCθ = Cθ2 − Cθ1 (m/s).",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Default 1.225 (ISA air).",
            },
            "blade_speed_sound": {
                "type": "number",
                "description": (
                    "Speed of sound at blade tip (m/s). "
                    "If provided, blade Mach number M_U is returned."
                ),
            },
        },
        "required": ["U", "Ca", "dCtheta"],
    },
)


@register(_dim_groups_spec, write=False)
async def run_turbo_dimensionless_groups(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("U", "Ca", "dCtheta"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "rho" in a:
        kwargs["rho"] = a["rho"]
    if "blade_speed_sound" in a:
        kwargs["blade_speed_sound"] = a["blade_speed_sound"]

    result = dimensionless_groups(a["U"], a["Ca"], a["dCtheta"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_specific_speed_diameter
# ---------------------------------------------------------------------------

_spec_speed_spec = ToolSpec(
    name="turbo_specific_speed_diameter",
    description=(
        "Compute dimensionless specific speed Ω_s and specific diameter Δ_s.\n"
        "\n"
        "  Ω_s = ω·√Q / (gH)^(3/4)   — machine classification on Cordier diagram\n"
        "  Δ_s = D·(gH)^(1/4) / √Q   — size parameter (if D provided)\n"
        "\n"
        "Ω_s < 1.0 → radial; 1–3 → mixed-flow; > 3.0 → axial.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q": {
                "type": "number",
                "description": "Volume flow rate (m³/s). Must be > 0.",
            },
            "gH": {
                "type": "number",
                "description": "Specific energy g·H (J/kg). Must be > 0.",
            },
            "omega": {
                "type": "number",
                "description": "Shaft angular velocity (rad/s). Must be > 0.",
            },
            "D": {
                "type": "number",
                "description": "Impeller diameter (m). If provided, Δ_s is computed.",
            },
        },
        "required": ["Q", "gH", "omega"],
    },
)


@register(_spec_speed_spec, write=False)
async def run_turbo_specific_speed_diameter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q", "gH", "omega"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "D" in a:
        kwargs["D"] = a["D"]

    result = specific_speed_diameter(a["Q"], a["gH"], a["omega"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_cordier_optimum
# ---------------------------------------------------------------------------

_cordier_spec = ToolSpec(
    name="turbo_cordier_optimum",
    description=(
        "Return the Cordier-line optimum specific diameter Δ_s_opt for a "
        "given dimensionless specific speed Ω_s.\n"
        "\n"
        "The Cordier diagram correlates peak-efficiency machines. This tool "
        "uses a log-polynomial fit (Dixon Fig 1.5).\n"
        "\n"
        "Reliable range: Ω_s ∈ [0.2, 10.0]. Extrapolation outside this range "
        "is flagged with a warning.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Omega_s": {
                "type": "number",
                "description": "Dimensionless specific speed. Must be > 0.",
            },
        },
        "required": ["Omega_s"],
    },
)


@register(_cordier_spec, write=False)
async def run_turbo_cordier_optimum(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Omega_s") is None:
        return json.dumps({"ok": False, "reason": "Omega_s is required"})

    result = cordier_optimum(a["Omega_s"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_degree_of_reaction
# ---------------------------------------------------------------------------

_reaction_spec = ToolSpec(
    name="turbo_degree_of_reaction",
    description=(
        "Compute the stage degree of reaction R.\n"
        "\n"
        "R = 1 − (Cθ1 + Cθ2) / (2·U)\n"
        "\n"
        "R = 0.5 → 50% reaction (symmetric velocity triangles).\n"
        "R = 0   → impulse stage (all static pressure drop in the rotor).\n"
        "R < 0   → unusual; warnings are flagged.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Ctheta1": {
                "type": "number",
                "description": "Absolute whirl velocity at rotor inlet (m/s).",
            },
            "Ctheta2": {
                "type": "number",
                "description": "Absolute whirl velocity at rotor exit (m/s).",
            },
            "U": {
                "type": "number",
                "description": "Blade speed (m/s). Must be > 0.",
            },
        },
        "required": ["Ctheta1", "Ctheta2", "U"],
    },
)


@register(_reaction_spec, write=False)
async def run_turbo_degree_of_reaction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Ctheta1", "Ctheta2", "U"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = degree_of_reaction(a["Ctheta1"], a["Ctheta2"], a["U"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_axial_stage
# ---------------------------------------------------------------------------

_axial_stage_spec = ToolSpec(
    name="turbo_axial_stage",
    description=(
        "Full axial compressor or turbine stage analysis.\n"
        "\n"
        "Computes velocity triangles, stage work, degree of reaction, "
        "and blade loading diagnostics:\n"
        "  Compressor: diffusion factor DF (Lieblein) and de Haller W2/W1.\n"
        "    Warnings if DF > 0.6 or W2/W1 < 0.72 (stall risk).\n"
        "  Turbine: blade loading ΔCθ/U.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "U": {
                "type": "number",
                "description": "Blade speed at mean radius (m/s). Must be > 0.",
            },
            "Ca": {
                "type": "number",
                "description": "Axial velocity component (m/s). Must be > 0.",
            },
            "alpha1_deg": {
                "type": "number",
                "description": "Absolute inlet flow angle from axial (degrees).",
            },
            "alpha2_deg": {
                "type": "number",
                "description": "Absolute exit flow angle from axial (degrees).",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Default 1.225.",
            },
            "is_compressor": {
                "type": "boolean",
                "description": "True (default) for compressor/fan; False for turbine.",
            },
            "chord": {
                "type": "number",
                "description": "Blade chord (m). Optional; enables aspect ratio + Re.",
            },
            "span": {
                "type": "number",
                "description": "Blade span (m). Optional; used with chord.",
            },
            "nu": {
                "type": "number",
                "description": (
                    "Kinematic viscosity (m²/s). Default 1.46e-5 (air at 15°C)."
                ),
            },
        },
        "required": ["U", "Ca", "alpha1_deg", "alpha2_deg"],
    },
)


@register(_axial_stage_spec, write=False)
async def run_turbo_axial_stage(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("U", "Ca", "alpha1_deg", "alpha2_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("rho", "is_compressor", "chord", "span", "nu"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = axial_stage(a["U"], a["Ca"], a["alpha1_deg"], a["alpha2_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_centrifugal_impeller
# ---------------------------------------------------------------------------

_cent_imp_spec = ToolSpec(
    name="turbo_centrifugal_impeller",
    description=(
        "Centrifugal pump/compressor impeller design-point analysis.\n"
        "\n"
        "Computes Euler head, slip factor (Stanitz or Wiesner), exit velocity "
        "triangles, volume flow rate, and NPSH inception estimate.\n"
        "\n"
        "Inputs: shaft speed, outer diameter, exit blade width, inlet tip/hub "
        "diameters, blade exit angle, and blade count.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_rpm": {
                "type": "number",
                "description": "Rotational speed (rpm). Must be > 0.",
            },
            "D2_m": {
                "type": "number",
                "description": "Impeller exit (outer) diameter (m). Must be > 0.",
            },
            "b2_m": {
                "type": "number",
                "description": "Impeller exit blade width (m). Must be > 0.",
            },
            "D1_tip_m": {
                "type": "number",
                "description": "Inlet tip diameter (m). Must be > 0 and <= D2_m.",
            },
            "D1_hub_m": {
                "type": "number",
                "description": (
                    "Inlet hub diameter (m). Must be >= 0 and < D1_tip_m. "
                    "Use 0 for open-eye impeller."
                ),
            },
            "beta2_deg": {
                "type": "number",
                "description": (
                    "Blade angle at exit from radial (degrees). "
                    "Negative = backward sweep (default −30°)."
                ),
            },
            "Z": {
                "type": "integer",
                "description": "Number of impeller blades. Must be >= 2. Default 8.",
            },
            "rho": {
                "type": "number",
                "description": "Fluid density (kg/m³). Default 1000 (water).",
            },
            "slip_model": {
                "type": "string",
                "enum": ["stanitz", "wiesner"],
                "description": (
                    "Slip factor model: 'stanitz' (default) or 'wiesner'."
                ),
            },
        },
        "required": ["n_rpm", "D2_m", "b2_m", "D1_tip_m", "D1_hub_m"],
    },
)


@register(_cent_imp_spec, write=False)
async def run_turbo_centrifugal_impeller(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("n_rpm", "D2_m", "b2_m", "D1_tip_m", "D1_hub_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("beta2_deg", "Z", "rho", "g", "slip_model"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = centrifugal_impeller(
        a["n_rpm"], a["D2_m"], a["b2_m"],
        D1_tip_m=a["D1_tip_m"], D1_hub_m=a["D1_hub_m"],
        **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_fan_affinity
# ---------------------------------------------------------------------------

_fan_affinity_spec = ToolSpec(
    name="turbo_fan_affinity",
    description=(
        "Apply fan / pump affinity laws for speed change and/or impeller trim.\n"
        "\n"
        "Speed change (constant geometry):\n"
        "  Q2 = Q1·(n2/n1),  H2 = H1·(n2/n1)²,  P2 = P1·(n2/n1)³\n"
        "\n"
        "Impeller trim (constant speed):\n"
        "  Q2 = Q1·(D2/D1),  H2 = H1·(D2/D1)²,  P2 = P1·(D2/D1)³\n"
        "\n"
        "Combined: use both speed ratio and diameter ratio.\n"
        "Warning issued if trim ratio < 0.70 (accuracy degrades).\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q1": {
                "type": "number",
                "description": "Reference flow rate (m³/s). Must be > 0.",
            },
            "H1": {
                "type": "number",
                "description": "Reference head / pressure rise (m). Must be > 0.",
            },
            "P1": {
                "type": "number",
                "description": "Reference shaft power (W). Must be > 0.",
            },
            "n1": {
                "type": "number",
                "description": "Reference shaft speed (rpm). Must be > 0.",
            },
            "n2": {
                "type": "number",
                "description": "New shaft speed (rpm). Must be > 0.",
            },
            "D1": {
                "type": "number",
                "description": "Reference impeller diameter (m). Required if D2 provided.",
            },
            "D2": {
                "type": "number",
                "description": "New impeller diameter (m). Must be > 0 and <= D1.",
            },
        },
        "required": ["Q1", "H1", "P1", "n1", "n2"],
    },
)


@register(_fan_affinity_spec, write=False)
async def run_turbo_fan_affinity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q1", "H1", "P1", "n1", "n2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "D1" in a:
        kwargs["D1"] = a["D1"]
    if "D2" in a:
        kwargs["D2"] = a["D2"]

    result = fan_affinity(a["Q1"], a["H1"], a["P1"], a["n1"], a["n2"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_stage_efficiency
# ---------------------------------------------------------------------------

_stage_eff_spec = ToolSpec(
    name="turbo_stage_efficiency",
    description=(
        "Compute isentropic and polytropic efficiency for a turbomachinery stage.\n"
        "\n"
        "Isentropic efficiency:\n"
        "  Compressor: η_is = W_isentropic / W_actual\n"
        "  Turbine:    η_is = W_actual / W_isentropic\n"
        "\n"
        "Polytropic efficiency (from polytropic index n, requires gamma):\n"
        "  Compressor: η_p = [(γ−1)/γ] / [(n−1)/n]\n"
        "  Turbine:    η_p = [(n−1)/n] / [(γ−1)/γ]\n"
        "\n"
        "Also returns approximate small-stage preheat/reheat factor f_r.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "W_actual": {
                "type": "number",
                "description": "Actual specific work (J/kg). Must be > 0.",
            },
            "W_isentropic": {
                "type": "number",
                "description": "Isentropic specific work (J/kg). Must be > 0.",
            },
            "polytropic_n": {
                "type": "number",
                "description": (
                    "Polytropic index n. If provided, polytropic efficiency is returned. "
                    "Must not be 1.0 (isothermal)."
                ),
            },
            "gamma": {
                "type": "number",
                "description": "Ratio of specific heats cp/cv. Default 1.4 (air).",
            },
            "stage_type": {
                "type": "string",
                "enum": ["compressor", "turbine"],
                "description": "Stage type: 'compressor' (default) or 'turbine'.",
            },
        },
        "required": ["W_actual", "W_isentropic"],
    },
)


@register(_stage_eff_spec, write=False)
async def run_turbo_stage_efficiency(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("W_actual", "W_isentropic"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("polytropic_n", "gamma", "stage_type"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = stage_efficiency(a["W_actual"], a["W_isentropic"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: turbo_surge_choke_margin
# ---------------------------------------------------------------------------

_surge_choke_spec = ToolSpec(
    name="turbo_surge_choke_margin",
    description=(
        "Compute surge margin and choke margin for a compressor/fan stage.\n"
        "\n"
        "  Surge margin SM = (φ_op − φ_surge) / φ_op\n"
        "  Choke margin CM = (φ_choke − φ_op) / φ_op\n"
        "\n"
        "SM < 0 → operating in surge (critical warning).\n"
        "Defaults: min_surge_margin = 0.15 (15%), min_choke_margin = 0.10 (10%).\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "phi_op": {
                "type": "number",
                "description": "Operating flow coefficient. Must be > 0.",
            },
            "phi_surge": {
                "type": "number",
                "description": "Flow coefficient at surge line. Must be >= 0.",
            },
            "phi_choke": {
                "type": "number",
                "description": "Flow coefficient at choke. Must be > phi_op.",
            },
            "min_surge_margin": {
                "type": "number",
                "description": "Minimum acceptable surge margin. Default 0.15.",
            },
            "min_choke_margin": {
                "type": "number",
                "description": "Minimum acceptable choke margin. Default 0.10.",
            },
        },
        "required": ["phi_op", "phi_surge", "phi_choke"],
    },
)


@register(_surge_choke_spec, write=False)
async def run_turbo_surge_choke_margin(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("phi_op", "phi_surge", "phi_choke"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "min_surge_margin" in a:
        kwargs["min_surge_margin"] = a["min_surge_margin"]
    if "min_choke_margin" in a:
        kwargs["min_choke_margin"] = a["min_choke_margin"]

    result = surge_choke_margin(a["phi_op"], a["phi_surge"], a["phi_choke"], **kwargs)
    return ok_payload(result)
