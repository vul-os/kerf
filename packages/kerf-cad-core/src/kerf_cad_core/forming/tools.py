"""
kerf_cad_core.forming.tools — LLM tool wrappers for bulk metal forming.

Registers ten tools with the Kerf tool registry:

  forming_flow_stress           — Hollomon flow stress σ = K·ε^n
  forming_mean_flow_stress      — mean flow stress σ̄_f = K·ε_f^n / (n+1)
  forming_upset_forging_force   — open-die upset forging force (Siebel slab method)
  forming_closed_die_load       — closed-die forging load (projected area × Kf)
  forming_forward_extrusion     — forward extrusion pressure + force
  forming_backward_extrusion    — backward extrusion pressure + force
  forming_flat_rolling          — flat rolling: force, torque, power, neutral point
  forming_wire_drawing          — wire/bar drawing stress, force, max reduction
  forming_work                  — forming work/energy and adiabatic temperature rise
  forming_passes_required       — number of passes to achieve total reduction

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Kalpakjian, S. & Schmid, S.R. "Manufacturing Engineering & Technology", 7th ed.
Hosford, W.F. & Caddell, R.M. "Metal Forming: Mechanics and Metallurgy", 4th ed.
Groover, M.P. "Fundamentals of Modern Manufacturing", 5th ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.forming.bulk import (
    flow_stress,
    mean_flow_stress,
    upset_forging_force,
    closed_die_forging_load,
    forward_extrusion,
    backward_extrusion,
    flat_rolling,
    wire_drawing,
    forming_work,
    passes_required,
)


# ---------------------------------------------------------------------------
# Tool: forming_flow_stress
# ---------------------------------------------------------------------------

_flow_stress_spec = ToolSpec(
    name="forming_flow_stress",
    description=(
        "Compute the Hollomon power-law flow stress: σ_f = K · ε^n.\n"
        "\n"
        "The Hollomon equation is the most widely used strain-hardening model "
        "for bulk metal forming.  Returns instantaneous flow stress at a given "
        "true strain.\n"
        "\n"
        "Typical K and n values:\n"
        "  Low-carbon steel:    K ≈ 530 MPa, n ≈ 0.26\n"
        "  304 Stainless:       K ≈ 1275 MPa, n ≈ 0.45\n"
        "  Aluminium 1100-O:    K ≈ 180 MPa, n ≈ 0.20\n"
        "  Copper (annealed):   K ≈ 315 MPa, n ≈ 0.54\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "K": {
                "type": "number",
                "description": "Strength coefficient (Pa).  Must be > 0.",
            },
            "eps": {
                "type": "number",
                "description": "True (logarithmic) strain at which to evaluate flow stress.  Must be > 0.",
            },
            "n": {
                "type": "number",
                "description": "Strain-hardening exponent (dimensionless).  Typical range [0, 1].  Must be >= 0.",
            },
        },
        "required": ["K", "eps", "n"],
    },
)


@register(_flow_stress_spec, write=False)
async def run_forming_flow_stress(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("K", "eps", "n"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = flow_stress(a["K"], a["eps"], a["n"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_mean_flow_stress
# ---------------------------------------------------------------------------

_mean_flow_stress_spec = ToolSpec(
    name="forming_mean_flow_stress",
    description=(
        "Compute the mean (average) flow stress over a strain range 0 → ε_f.\n"
        "\n"
        "σ̄_f = K · ε_f^n / (n + 1)\n"
        "\n"
        "Use this for force/energy estimates where the total deformation strain "
        "is known (e.g. cold extrusion, rolling, forging).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "K": {
                "type": "number",
                "description": "Strength coefficient (Pa).  Must be > 0.",
            },
            "n": {
                "type": "number",
                "description": "Strain-hardening exponent.  Must be >= 0.",
            },
            "eps_f": {
                "type": "number",
                "description": "Final true strain (total deformation).  Must be > 0.",
            },
        },
        "required": ["K", "n", "eps_f"],
    },
)


@register(_mean_flow_stress_spec, write=False)
async def run_forming_mean_flow_stress(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("K", "n", "eps_f"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = mean_flow_stress(a["K"], a["n"], a["eps_f"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_upset_forging_force
# ---------------------------------------------------------------------------

_upset_spec = ToolSpec(
    name="forming_upset_forging_force",
    description=(
        "Compute open-die upset forging force including Coulomb friction "
        "(Siebel slab-method).\n"
        "\n"
        "Applies volume conservation to find the final workpiece geometry, "
        "then computes average forging pressure:\n"
        "  p_avg = σ_f · (1 + 2·μ·R_f / (3·h_f))\n"
        "\n"
        "Returns forging force (N and MN), average pressure, and friction factor.\n"
        "Warns if friction factor > 0.5 or reduction > 80%.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_f": {
                "type": "number",
                "description": "Flow stress at the forging strain (Pa).  Must be > 0.",
            },
            "A0": {
                "type": "number",
                "description": "Initial cross-sectional area of workpiece (m²).  Must be > 0.",
            },
            "h0": {
                "type": "number",
                "description": "Initial workpiece height (m).  Must be > 0.",
            },
            "hf": {
                "type": "number",
                "description": "Final workpiece height after forging (m).  Must be > 0 and < h0.",
            },
            "mu": {
                "type": "number",
                "description": (
                    "Coulomb friction coefficient at die–workpiece interface "
                    "(default 0.1).  Typical: 0.05 (lubricated) – 0.4 (dry)."
                ),
            },
        },
        "required": ["sigma_f", "A0", "h0", "hf"],
    },
)


@register(_upset_spec, write=False)
async def run_forming_upset_forging_force(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_f", "A0", "h0", "hf"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "mu" in a:
        kwargs["mu"] = a["mu"]

    result = upset_forging_force(a["sigma_f"], a["A0"], a["h0"], a["hf"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_closed_die_load
# ---------------------------------------------------------------------------

_closed_die_spec = ToolSpec(
    name="forming_closed_die_load",
    description=(
        "Compute closed-die (impression-die) forging load.\n"
        "\n"
        "F = Kf · σ̄_f · A_proj\n"
        "\n"
        "Kf is the die constraint / flash factor.  Typical values:\n"
        "  3 — simple shapes with generous flash\n"
        "  6 — moderate complexity (default)\n"
        "  8 — complex, thin-flash, high-precision forgings\n"
        "\n"
        "Returns forging load in N, MN, and metric tonnes-force.\n"
        "Warns if Kf > 8 or load > 100 MN (press-tonnage-exceeded).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_f": {
                "type": "number",
                "description": "Mean flow stress at forging temperature and strain (Pa).  Must be > 0.",
            },
            "A_proj": {
                "type": "number",
                "description": "Projected plan-form area of the forging including flash (m²).  Must be > 0.",
            },
            "Kf": {
                "type": "number",
                "description": "Die constraint / flash factor (default 6.0).  Typical range [3, 9].",
            },
        },
        "required": ["sigma_f", "A_proj"],
    },
)


@register(_closed_die_spec, write=False)
async def run_forming_closed_die_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_f", "A_proj"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "Kf" in a:
        kwargs["Kf"] = a["Kf"]

    result = closed_die_forging_load(a["sigma_f"], a["A_proj"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_forward_extrusion
# ---------------------------------------------------------------------------

_fwd_ext_spec = ToolSpec(
    name="forming_forward_extrusion",
    description=(
        "Compute forward (direct) extrusion pressure and force.\n"
        "\n"
        "Uses the modified Johnson/Altan upper-bound formula:\n"
        "  p_e = σ̄_f · [B · ln(R) + μ·π·D0·L/A0]\n"
        "where B = 0.8 + 1.2·tan(α) is the redundant-work factor,\n"
        "R = A0/Af is the extrusion ratio, L is billet length in container.\n"
        "\n"
        "Returns extrusion pressure, force (N and MN), extrusion ratio, and strain.\n"
        "Warns if R > 20, die angle < 5°, die angle > 60°, or force > 50 MN.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_f": {
                "type": "number",
                "description": "Mean flow stress of billet material (Pa).  Must be > 0.",
            },
            "A0": {
                "type": "number",
                "description": "Billet cross-sectional area (m²).  Must be > 0.",
            },
            "Af": {
                "type": "number",
                "description": "Extrudate cross-sectional area (m²).  Must be > 0 and < A0.",
            },
            "mu": {
                "type": "number",
                "description": "Friction coefficient at billet–container and die interfaces (default 0.05).",
            },
            "die_half_angle_deg": {
                "type": "number",
                "description": "Die half-angle α (degrees, from extrusion axis).  Default 45°.  Range (0, 90).",
            },
            "L": {
                "type": "number",
                "description": "Length of billet remaining in container (m).  Default 0.  Must be >= 0.",
            },
        },
        "required": ["sigma_f", "A0", "Af"],
    },
)


@register(_fwd_ext_spec, write=False)
async def run_forming_forward_extrusion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_f", "A0", "Af"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("mu", "die_half_angle_deg", "L"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = forward_extrusion(a["sigma_f"], a["A0"], a["Af"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_backward_extrusion
# ---------------------------------------------------------------------------

_bwd_ext_spec = ToolSpec(
    name="forming_backward_extrusion",
    description=(
        "Compute backward (indirect) extrusion pressure and force.\n"
        "\n"
        "In backward extrusion the billet does not slide against the container "
        "wall, eliminating container-wall friction.  Pressure is lower than "
        "forward extrusion at the same extrusion ratio.\n"
        "\n"
        "  p_e = σ̄_f · B · ln(R)\n"
        "where B = 0.8 + 1.2·tan(α).\n"
        "\n"
        "Returns extrusion pressure, force (N and MN), and the ratio of backward "
        "to forward pressure (at same parameters).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_f": {
                "type": "number",
                "description": "Mean flow stress of billet material (Pa).  Must be > 0.",
            },
            "A0": {
                "type": "number",
                "description": "Billet cross-sectional area (m²).  Must be > 0.",
            },
            "Af": {
                "type": "number",
                "description": "Extrudate cross-sectional area (m²).  Must be > 0 and < A0.",
            },
            "mu": {
                "type": "number",
                "description": "Friction coefficient at die–workpiece interface (default 0.05).",
            },
            "die_half_angle_deg": {
                "type": "number",
                "description": "Die half-angle α (degrees).  Default 45°.  Range (0, 90).",
            },
        },
        "required": ["sigma_f", "A0", "Af"],
    },
)


@register(_bwd_ext_spec, write=False)
async def run_forming_backward_extrusion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_f", "A0", "Af"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("mu", "die_half_angle_deg"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = backward_extrusion(a["sigma_f"], a["A0"], a["Af"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_flat_rolling
# ---------------------------------------------------------------------------

_rolling_spec = ToolSpec(
    name="forming_flat_rolling",
    description=(
        "Flat rolling analysis: contact length, roll force, torque, power, "
        "max draft, neutral point.\n"
        "\n"
        "  L_c = sqrt(R · Δh)          — contact length\n"
        "  F = σ̄_f · w · L_c · (1 + μ·L_c/(2·h_avg))  — roll force\n"
        "  T = F · L_c / 2             — torque per roll\n"
        "  P = 2·T·ω                   — total rolling power\n"
        "  Δh_max = μ²·R               — max draft (bite condition)\n"
        "\n"
        "Warns if draft exceeds bite limit, reduction > 50%, or power > 10 MW.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_f": {
                "type": "number",
                "description": "Mean flow stress of the strip (Pa).  Must be > 0.",
            },
            "mu": {
                "type": "number",
                "description": "Friction coefficient between strip and rolls.  Must be > 0.",
            },
            "R": {
                "type": "number",
                "description": "Roll radius (m).  Must be > 0.",
            },
            "h0": {
                "type": "number",
                "description": "Incoming strip thickness (m).  Must be > 0.",
            },
            "hf": {
                "type": "number",
                "description": "Outgoing strip thickness (m).  Must be > 0 and < h0.",
            },
            "w": {
                "type": "number",
                "description": "Strip width (m).  Must be > 0.",
            },
            "omega_rad_s": {
                "type": "number",
                "description": "Angular velocity of each roll (rad/s).  Default 0 (power not computed).",
            },
        },
        "required": ["sigma_f", "mu", "R", "h0", "hf", "w"],
    },
)


@register(_rolling_spec, write=False)
async def run_forming_flat_rolling(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_f", "mu", "R", "h0", "hf", "w"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "omega_rad_s" in a:
        kwargs["omega_rad_s"] = a["omega_rad_s"]

    result = flat_rolling(
        a["sigma_f"], a["mu"], a["R"], a["h0"], a["hf"], a["w"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_wire_drawing
# ---------------------------------------------------------------------------

_drawing_spec = ToolSpec(
    name="forming_wire_drawing",
    description=(
        "Wire/bar drawing: drawing stress, force, max reduction per pass, "
        "and limiting reduction.\n"
        "\n"
        "Uses the Hosford–Caddell slab-analysis formula:\n"
        "  σ_d = σ̄_f · (B/(B-1)) · [1 - (Af/A0)^((B-1)/B)]\n"
        "  B = μ · cot(α)   (friction-geometry parameter)\n"
        "\n"
        "Max reduction per pass: r_max = 1 - exp(-1/B)\n"
        "Limiting reduction (frictionless ideal): ≈ 63.2%\n"
        "\n"
        "Warns if drawing stress ≥ flow stress (EXCEEDS-LIMIT-REDUCTION), "
        "die angle < 3°, or die angle > 30°.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma_f": {
                "type": "number",
                "description": "Mean flow stress of the wire/bar material (Pa).  Must be > 0.",
            },
            "A0": {
                "type": "number",
                "description": "Initial wire/bar cross-sectional area (m²).  Must be > 0.",
            },
            "Af": {
                "type": "number",
                "description": "Final wire/bar cross-sectional area (m²).  Must be > 0 and < A0.",
            },
            "mu": {
                "type": "number",
                "description": "Friction coefficient at wire–die interface (default 0.05).",
            },
            "die_half_angle_deg": {
                "type": "number",
                "description": "Die semi-angle α (degrees, from wire axis).  Default 8°.",
            },
        },
        "required": ["sigma_f", "A0", "Af"],
    },
)


@register(_drawing_spec, write=False)
async def run_forming_wire_drawing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("sigma_f", "A0", "Af"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("mu", "die_half_angle_deg"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = wire_drawing(a["sigma_f"], a["A0"], a["Af"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_work
# ---------------------------------------------------------------------------

_work_spec = ToolSpec(
    name="forming_work",
    description=(
        "Compute forming work / energy and adiabatic temperature rise.\n"
        "\n"
        "  W = F · d / η\n"
        "  ΔT = W / (ρ · V · C_p)   (adiabatic upper bound)\n"
        "\n"
        "If volume_m3 is not provided (or 0), temperature rise is not computed.\n"
        "\n"
        "Warns if ΔT > 200°C (significant thermal softening / die wear risk).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "F_N": {
                "type": "number",
                "description": "Average forming force (N).  Must be > 0.",
            },
            "displacement_m": {
                "type": "number",
                "description": "Total press stroke / displacement (m).  Must be > 0.",
            },
            "eta": {
                "type": "number",
                "description": "Machine efficiency (default 1.0 — no losses).  Range (0, 1].",
            },
            "rho": {
                "type": "number",
                "description": "Workpiece density (kg/m³).  Default 7850 (steel).  Used if volume_m3 > 0.",
            },
            "Cp": {
                "type": "number",
                "description": "Specific heat capacity (J/kg·K).  Default 502 (steel).  Used if volume_m3 > 0.",
            },
            "volume_m3": {
                "type": "number",
                "description": "Workpiece volume (m³).  Default 0 (temperature rise not computed).",
            },
        },
        "required": ["F_N", "displacement_m"],
    },
)


@register(_work_spec, write=False)
async def run_forming_work(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("F_N", "displacement_m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("eta", "rho", "Cp", "volume_m3"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = forming_work(a["F_N"], a["displacement_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: forming_passes_required
# ---------------------------------------------------------------------------

_passes_spec = ToolSpec(
    name="forming_passes_required",
    description=(
        "Compute the minimum number of rolling / drawing passes to achieve "
        "a total area or thickness reduction.\n"
        "\n"
        "  n = ceil(ln(1 - r_total) / ln(1 - r_per_pass))\n"
        "\n"
        "Returns number of passes, true strain per pass, and total accumulated "
        "true strain.\n"
        "Warns if n_passes > 20 (consider intermediate annealing).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_total": {
                "type": "number",
                "description": "Total fractional reduction required, e.g. 0.75 for 75%.  Range (0, 1).",
            },
            "r_per_pass": {
                "type": "number",
                "description": "Fractional reduction per pass, e.g. 0.20 for 20%.  Range (0, 1).",
            },
        },
        "required": ["r_total", "r_per_pass"],
    },
)


@register(_passes_spec, write=False)
async def run_forming_passes_required(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("r_total", "r_per_pass"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = passes_required(a["r_total"], a["r_per_pass"])
    return ok_payload(result)
