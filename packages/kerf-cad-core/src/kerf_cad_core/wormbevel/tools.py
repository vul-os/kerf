"""
kerf_cad_core.wormbevel.tools — LLM tool wrappers for worm-gear & bevel-gear design.

Registers seven tools with the Kerf tool registry:

  worm_geometry          — worm/gear pitch diameters, lead, lead angle, centre distance
  worm_efficiency        — efficiency η, back-drive, self-locking criterion
  worm_forces            — tangential/axial/radial/separating force analysis
  worm_agma_rating       — AGMA rated tangential load & thermal-power limit
  bevel_geometry         — straight-bevel pitch angles, cone distance, virtual teeth
  bevel_forces           — tangential/radial/axial force at mean pitch circle
  bevel_agma_stress      — AGMA bending & contact stress with bevel geometry factors

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Shigley's Mechanical Engineering Design, 10th ed., §§ 13-7 to 13-10, 13-17
AGMA 6022-C93 — Coarse-Pitch Worm Gearing
AGMA 2003-B97 — Straight Bevel, Zerol Bevel, and Spiral Bevel Gear Teeth

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.wormbevel.design import (
    worm_geometry,
    worm_efficiency,
    worm_forces,
    worm_agma_rating,
    bevel_geometry,
    bevel_forces,
    bevel_agma_stress,
)


# ---------------------------------------------------------------------------
# Tool: worm_geometry
# ---------------------------------------------------------------------------

_worm_geometry_spec = ToolSpec(
    name="worm_geometry",
    description=(
        "Compute worm-gear pair geometry: lead, lead angle, pitch diameters, "
        "centre distance, gear ratio, and maximum recommended face width.\n"
        "\n"
        "When centre distance C is provided, the worm pitch diameter is sized "
        "via the AGMA 6022 preferred formula; otherwise a standard worm quotient "
        "q=10 is used.\n"
        "\n"
        "Returns: m_n_mm, N_w, N_g, m_G, phi_n_deg, lead_mm, lead_angle_deg, "
        "d_w_mm, d_g_mm, C_mm, face_width_max_mm, axial_pitch_mm, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "m_n": {
                "type": "number",
                "description": "Normal module (mm). Must be > 0.",
            },
            "N_w": {
                "type": "integer",
                "description": "Number of worm starts (threads). Typically 1–6. Must be >= 1.",
            },
            "N_g": {
                "type": "integer",
                "description": "Number of worm-gear teeth. Must be > N_w.",
            },
            "C": {
                "type": "number",
                "description": (
                    "Centre distance (mm). Optional. If provided, pitch diameters are "
                    "sized per AGMA 6022 preferred formula."
                ),
            },
            "phi_n_deg": {
                "type": "number",
                "description": "Normal pressure angle (°). Default 20°.",
            },
        },
        "required": ["m_n", "N_w", "N_g"],
    },
)


@register(_worm_geometry_spec, write=False)
async def run_worm_geometry(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("m_n", "N_w", "N_g"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "C" in a:
        kwargs["C"] = a["C"]
    if "phi_n_deg" in a:
        kwargs["phi_n_deg"] = a["phi_n_deg"]

    result = worm_geometry(a["m_n"], a["N_w"], a["N_g"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: worm_efficiency
# ---------------------------------------------------------------------------

_worm_efficiency_spec = ToolSpec(
    name="worm_efficiency",
    description=(
        "Compute worm-gear pair efficiency (worm driving gear) and back-drive "
        "efficiency, and check the self-locking criterion.\n"
        "\n"
        "Formula (Shigley §13-9):\n"
        "  η_forward = tan(λ) × (cos φ_n − μ tan λ) / (cos φ_n tan λ + μ)\n"
        "Self-locking when η_back ≤ 0, i.e. μ ≥ cos(φ_n) · tan(λ).\n"
        "\n"
        "Returns: eta_forward, eta_back, self_locking, warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lambda_deg": {
                "type": "number",
                "description": "Worm lead angle (°). Must be in (0, 90).",
            },
            "phi_n_deg": {
                "type": "number",
                "description": "Normal pressure angle (°). Default 20°.",
            },
            "mu": {
                "type": "number",
                "description": (
                    "Coefficient of sliding friction (dimensionless). "
                    "Typical range 0.01–0.15. Default 0.05."
                ),
            },
        },
        "required": ["lambda_deg"],
    },
)


@register(_worm_efficiency_spec, write=False)
async def run_worm_efficiency(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("lambda_deg") is None:
        return json.dumps({"ok": False, "reason": "lambda_deg is required"})

    kwargs: dict = {}
    if "phi_n_deg" in a:
        kwargs["phi_n_deg"] = a["phi_n_deg"]
    if "mu" in a:
        kwargs["mu"] = a["mu"]

    result = worm_efficiency(a["lambda_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: worm_forces
# ---------------------------------------------------------------------------

_worm_forces_spec = ToolSpec(
    name="worm_forces",
    description=(
        "Compute force analysis on a worm-gear pair (worm drives gear).\n"
        "\n"
        "Returns tangential force on worm W_t_w (= axial on gear), axial force "
        "on worm W_a_w (= tangential on gear), separating/radial force W_r, "
        "and normal force W_n at the tooth contact.\n"
        "\n"
        "Formulas (Shigley §13-10):\n"
        "  W_n = W_t_w / (cos φ_n sin λ + μ cos λ)\n"
        "  W_a_w = W_n × (cos φ_n cos λ − μ sin λ)\n"
        "  W_r   = W_n × sin φ_n\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_w": {
                "type": "number",
                "description": "Input torque on worm (N·mm). Must be > 0.",
            },
            "d_w": {
                "type": "number",
                "description": "Worm pitch diameter (mm). Must be > 0.",
            },
            "lambda_deg": {
                "type": "number",
                "description": "Worm lead angle (°). Must be in (0, 90).",
            },
            "phi_n_deg": {
                "type": "number",
                "description": "Normal pressure angle (°). Default 20°.",
            },
            "mu": {
                "type": "number",
                "description": "Coefficient of sliding friction. Default 0.05.",
            },
        },
        "required": ["T_w", "d_w", "lambda_deg"],
    },
)


@register(_worm_forces_spec, write=False)
async def run_worm_forces(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_w", "d_w", "lambda_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "phi_n_deg" in a:
        kwargs["phi_n_deg"] = a["phi_n_deg"]
    if "mu" in a:
        kwargs["mu"] = a["mu"]

    result = worm_forces(a["T_w"], a["d_w"], a["lambda_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: worm_agma_rating
# ---------------------------------------------------------------------------

_worm_agma_rating_spec = ToolSpec(
    name="worm_agma_rating",
    description=(
        "Compute the AGMA 6022 rated tangential load and approximate thermal "
        "power limit for a worm-gear set.\n"
        "\n"
        "AGMA formula: W_t_rated = C_s × d_g^0.8 × b × C_m × C_v\n"
        "Thermal rating flags over-temperature if rated power > thermal limit.\n"
        "\n"
        "material_pair options:\n"
        "  'sand_cast_bronze_cast_iron'\n"
        "  'centrifugal_cast_bronze_steel' (default)\n"
        "  'chilled_cast_bronze_steel'\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C_s": {
                "type": "number",
                "description": "AGMA 6022 materials constant. Typical range 600–1000.",
            },
            "C_m": {
                "type": "number",
                "description": "Ratio correction factor. Typical 0.7–1.0.",
            },
            "C_v": {
                "type": "number",
                "description": "Velocity factor. Typical 0.4–1.0.",
            },
            "d_g": {
                "type": "number",
                "description": "Worm-gear pitch diameter (mm). Must be > 0.",
            },
            "b": {
                "type": "number",
                "description": "Worm-gear face width (mm). Must be > 0.",
            },
            "d_w": {
                "type": "number",
                "description": "Worm pitch diameter (mm). Must be > 0.",
            },
            "n_w": {
                "type": "number",
                "description": "Worm rotational speed (rpm). Must be > 0.",
            },
            "material_pair": {
                "type": "string",
                "enum": [
                    "sand_cast_bronze_cast_iron",
                    "centrifugal_cast_bronze_steel",
                    "chilled_cast_bronze_steel",
                ],
                "description": "Material combination (default 'centrifugal_cast_bronze_steel').",
            },
        },
        "required": ["C_s", "C_m", "C_v", "d_g", "b", "d_w", "n_w"],
    },
)


@register(_worm_agma_rating_spec, write=False)
async def run_worm_agma_rating(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C_s", "C_m", "C_v", "d_g", "b", "d_w", "n_w"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "material_pair" in a:
        kwargs["material_pair"] = a["material_pair"]

    result = worm_agma_rating(
        a["C_s"], a["C_m"], a["C_v"],
        a["d_g"], a["b"], a["d_w"], a["n_w"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bevel_geometry
# ---------------------------------------------------------------------------

_bevel_geometry_spec = ToolSpec(
    name="bevel_geometry",
    description=(
        "Compute straight-bevel gear pair geometry: pitch angles, outer cone "
        "distance, mean module, face width, mean pitch diameters, and equivalent "
        "(virtual) spur-gear tooth counts.\n"
        "\n"
        "Formulas (Shigley §13-17, 90° shaft angle):\n"
        "  tan Γ_p = N_p / N_g\n"
        "  A_0 = d_p / (2 sin Γ_p)\n"
        "  b   = b_fraction × A_0  (AGMA: b_fraction ≤ 1/3)\n"
        "  N_e = N / cos(Γ)   (virtual spur-gear teeth)\n"
        "\n"
        "Returns: pitch angles, A_0_mm, b_mm, m_m_mm, d_m_p_mm, N_e_p, N_e_g.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "N_p": {
                "type": "integer",
                "description": "Number of pinion teeth. Must be >= 12.",
            },
            "N_g": {
                "type": "integer",
                "description": "Number of gear teeth. Must be > N_p.",
            },
            "m": {
                "type": "number",
                "description": "Back-cone (outer) module (mm). Must be > 0.",
            },
            "b_fraction": {
                "type": "number",
                "description": (
                    "Face width as a fraction of cone distance A_0. "
                    "AGMA limit: 0.333. Default 0.3."
                ),
            },
        },
        "required": ["N_p", "N_g", "m"],
    },
)


@register(_bevel_geometry_spec, write=False)
async def run_bevel_geometry(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("N_p", "N_g", "m"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "b_fraction" in a:
        kwargs["b_fraction"] = a["b_fraction"]

    result = bevel_geometry(a["N_p"], a["N_g"], a["m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bevel_forces
# ---------------------------------------------------------------------------

_bevel_forces_spec = ToolSpec(
    name="bevel_forces",
    description=(
        "Compute force analysis on a straight-bevel pinion at its mean pitch circle.\n"
        "\n"
        "Formulas (Shigley §13-17):\n"
        "  W_t = 2 T_p / d_m_p\n"
        "  W_r = W_t × tan(φ_n) × cos(Γ_p)   [radial on pinion = axial on gear]\n"
        "  W_a = W_t × tan(φ_n) × sin(Γ_p)   [axial on pinion  = radial on gear]\n"
        "\n"
        "Returns: W_t_N, W_r_N, W_a_N, W_total_N.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_p": {
                "type": "number",
                "description": "Pinion input torque (N·mm). Must be > 0.",
            },
            "d_m_p": {
                "type": "number",
                "description": "Pinion mean pitch diameter (mm). Must be > 0.",
            },
            "Gamma_p_deg": {
                "type": "number",
                "description": "Pinion pitch angle (°). Must be in (0, 90).",
            },
            "phi_n_deg": {
                "type": "number",
                "description": "Normal pressure angle (°). Default 20°.",
            },
        },
        "required": ["T_p", "d_m_p", "Gamma_p_deg"],
    },
)


@register(_bevel_forces_spec, write=False)
async def run_bevel_forces(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_p", "d_m_p", "Gamma_p_deg"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "phi_n_deg" in a:
        kwargs["phi_n_deg"] = a["phi_n_deg"]

    result = bevel_forces(a["T_p"], a["d_m_p"], a["Gamma_p_deg"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: bevel_agma_stress
# ---------------------------------------------------------------------------

_bevel_agma_stress_spec = ToolSpec(
    name="bevel_agma_stress",
    description=(
        "Compute AGMA bending stress (Lewis/AGMA) and contact stress for "
        "straight-bevel (or spiral-bevel) gears, using geometry factors J and I "
        "at the mean pitch circle.\n"
        "\n"
        "Bending:  σ_t = Wt · Ko · Kv · Ks · Km / (b · m_m · J)  [MPa]\n"
        "Contact:  σ_c = Cp · √(Wt · Ko · Kv · Ks · Km / (d_m_p · b · I))  [MPa]\n"
        "\n"
        "Typical geometry factors for straight bevel at 20°: J ≈ 0.23, I ≈ 0.07.\n"
        "For spiral bevel, supply spiral-bevel J_s and I_s from AGMA 2003.\n"
        "metric=True (default) → SI (MPa, N, mm). metric=False → English (psi, lbf, in).\n"
        "\n"
        "Warnings issued for overstress. Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Wt": {
                "type": "number",
                "description": "Tangential load at mean pitch circle (N for metric, lbf for English).",
            },
            "Ko": {"type": "number", "description": "Overload factor (>= 1)."},
            "Kv": {"type": "number", "description": "Dynamic factor (>= 1)."},
            "Ks": {"type": "number", "description": "Size factor (>= 1)."},
            "Km": {"type": "number", "description": "Load-distribution factor (>= 1)."},
            "b": {
                "type": "number",
                "description": "Face width (mm for metric, inches for English). Must be > 0.",
            },
            "m_m": {
                "type": "number",
                "description": (
                    "Mean module (mm, metric) or mean diametral pitch (teeth/in, English). "
                    "Must be > 0."
                ),
            },
            "J": {
                "type": "number",
                "description": "Bending geometry factor. Typical 0.20–0.35.",
            },
            "I": {
                "type": "number",
                "description": "Contact geometry factor. Typical 0.05–0.20.",
            },
            "Cp": {
                "type": "number",
                "description": (
                    "Elastic coefficient (√MPa metric, √psi English). "
                    "Steel/steel: 191 √MPa or 2300 √psi."
                ),
            },
            "d_m_p": {
                "type": "number",
                "description": "Pinion mean pitch diameter (mm or inches). Must be > 0.",
            },
            "metric": {
                "type": "boolean",
                "description": "True (default) for SI units, False for English.",
            },
        },
        "required": ["Wt", "Ko", "Kv", "Ks", "Km", "b", "m_m", "J", "I", "Cp", "d_m_p"],
    },
)


@register(_bevel_agma_stress_spec, write=False)
async def run_bevel_agma_stress(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    required = ("Wt", "Ko", "Kv", "Ks", "Km", "b", "m_m", "J", "I", "Cp", "d_m_p")
    for field in required:
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "metric" in a:
        kwargs["metric"] = a["metric"]

    result = bevel_agma_stress(
        a["Wt"], a["Ko"], a["Kv"], a["Ks"], a["Km"],
        a["b"], a["m_m"], a["J"], a["I"], a["Cp"], a["d_m_p"],
        **kwargs,
    )
    return ok_payload(result)
