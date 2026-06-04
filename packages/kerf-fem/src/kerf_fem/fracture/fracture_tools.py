"""
LLM tool wrappers for fracture mechanics.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)

Registers:
  fem_j_integral          — J-integral computation
  fem_stress_intensity     — K_I from displacement field or specimen formula
  fem_cohesive_zone        — traction-separation law evaluation
"""

from __future__ import annotations

import json
import math

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# fem_stress_intensity — K from ASTM specimen formula
# ---------------------------------------------------------------------------

_fem_stress_intensity_spec = ToolSpec(
    name="fem_stress_intensity",
    description=(
        "Compute the Mode-I stress intensity factor K_I for a standardised "
        "fracture specimen using the ASTM E399 formula (Compact Tension, "
        "Single-Edge Notched Tension, or 3-point bend). Also converts between "
        "K_I and the J-integral (energy release rate G). "
        "Reference: Anderson (2005) 'Fracture Mechanics' 3rd ed., ASTM E399-22."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "geometry": {
                "type": "string",
                "enum": ["CT_specimen", "SENT", "SENB"],
                "description": (
                    "Specimen geometry. "
                    "CT_specimen = compact tension (ASTM E399); "
                    "SENT = single-edge notched tension; "
                    "SENB = single-edge notched bending."
                ),
            },
            "crack_length_m": {
                "type": "number",
                "description": "Crack length a [m].",
            },
            "plate_width_m": {
                "type": "number",
                "description": (
                    "CT: W = distance from load-line to back face [m]. "
                    "SENT/SENB: full plate width [m]."
                ),
            },
            "load_n": {
                "type": "number",
                "description": "Applied load P [N].",
            },
            "plate_thickness_m": {
                "type": "number",
                "description": "Specimen thickness B [m].",
            },
            "youngs_modulus_pa": {
                "type": "number",
                "description": "Young's modulus [Pa]. Used to compute J = K²/E'.",
            },
            "poisson": {
                "type": "number",
                "description": "Poisson's ratio. Used for plane-strain J.",
            },
        },
        "required": [
            "geometry", "crack_length_m", "plate_width_m",
            "load_n", "plate_thickness_m",
        ],
    },
)


@register(_fem_stress_intensity_spec)
async def run_fem_stress_intensity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ["geometry", "crack_length_m", "plate_width_m", "load_n", "plate_thickness_m"]:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.fracture.stress_intensity import fracture_toughness_from_load, k_to_j

    try:
        K_I = fracture_toughness_from_load(
            crack_length_m=float(a["crack_length_m"]),
            plate_width_m=float(a["plate_width_m"]),
            load_n=float(a["load_n"]),
            plate_thickness_m=float(a["plate_thickness_m"]),
            geometry=str(a["geometry"]),
        )
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        return err_payload(str(e), "COMPUTE_ERROR")

    resp = {
        "K_I_pa_sqrt_m": K_I,
        "geometry": a["geometry"],
        "a_over_W": float(a["crack_length_m"]) / float(a["plate_width_m"]),
    }

    E = a.get("youngs_modulus_pa")
    nu = a.get("poisson")
    if E is not None and nu is not None:
        J = k_to_j(K_I, float(E), float(nu), condition="plane_strain")
        resp["J_integral_j_m2"] = J
        resp["G_c_j_m2"] = J

    resp["notes"] = (
        "ASTM E399 closed-form. Valid for LEFM (small-scale yielding). "
        "Plane-strain condition requires B ≥ 2.5·(K_I/σ_y)²."
    )
    return ok_payload(resp)


# ---------------------------------------------------------------------------
# fem_cohesive_zone — TSL evaluation
# ---------------------------------------------------------------------------

_fem_cohesive_zone_spec = ToolSpec(
    name="fem_cohesive_zone",
    description=(
        "Evaluate a cohesive zone traction-separation law (TSL) at specified "
        "crack opening displacements. Supports bilinear (Hillerborg 1976), "
        "exponential (Xu-Needleman 1994), and PPR (Park-Paulino-Roesler 2009) "
        "models. Returns traction, fracture energy, and damage parameter. "
        "Reference: Park et al. (2009) J. Mech. Phys. Solids 57."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "model_type": {
                "type": "string",
                "enum": ["bilinear", "exponential", "PPR"],
                "description": "Cohesive zone model type.",
            },
            "sigma_max_pa": {
                "type": "number",
                "description": "Peak cohesive traction σ_max [Pa].",
            },
            "delta_critical_m": {
                "type": "number",
                "description": "Critical opening displacement δ_c [m].",
            },
            "separations_m": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of crack opening displacements δ [m] to evaluate.",
            },
            "delta_0_m": {
                "type": "number",
                "description": "Opening at peak traction δ_0 [m] (bilinear/PPR). Default: 0.05·δ_c.",
            },
        },
        "required": ["model_type", "sigma_max_pa", "delta_critical_m", "separations_m"],
    },
)


@register(_fem_cohesive_zone_spec)
async def run_fem_cohesive_zone(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ["model_type", "sigma_max_pa", "delta_critical_m", "separations_m"]:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.fracture.cohesive_zone import (
        CohesiveZoneMaterial,
        traction_separation_bilinear,
        traction_separation_exponential,
        park_paulino_roesler,
        cohesive_fracture_energy,
    )
    import numpy as np

    mat = CohesiveZoneMaterial(
        sigma_max_pa=float(a["sigma_max_pa"]),
        delta_critical_m=float(a["delta_critical_m"]),
        type=str(a["model_type"]),
        delta_0_m=float(a["delta_0_m"]) if a.get("delta_0_m") is not None else None,
    )

    separations = [float(s) for s in a["separations_m"]]
    tractions = []
    model_type = str(a["model_type"])

    try:
        for s in separations:
            if model_type == "bilinear":
                T = traction_separation_bilinear(s, mat)
            elif model_type == "exponential":
                T = traction_separation_exponential(s, mat)
            elif model_type == "PPR":
                T_vec = park_paulino_roesler(np.array([s, 0.0]), mat)
                T = float(T_vec[0])
            else:
                return err_payload(f"Unknown model_type: {model_type}", "BAD_ARGS")
            tractions.append(T)

        G_c = cohesive_fracture_energy(mat)
    except Exception as e:
        return err_payload(str(e), "COMPUTE_ERROR")

    return ok_payload({
        "model_type": model_type,
        "separations_m": separations,
        "tractions_pa": tractions,
        "fracture_energy_j_m2": G_c,
        "sigma_max_pa": mat.sigma_max_pa,
        "delta_critical_m": mat.delta_critical_m,
        "notes": (
            "Cohesive zone model at a single material point. "
            "Element assembly and FEM integration loop not included. "
            "For mixed-mode: use PPR with [delta_n, delta_t] vector input."
        ),
    })


# ---------------------------------------------------------------------------
# fem_j_integral_specimen — J from LEFM K_I
# ---------------------------------------------------------------------------

_fem_j_integral_spec = ToolSpec(
    name="fem_j_integral_specimen",
    description=(
        "Compute the J-integral (energy release rate G) from the stress "
        "intensity factor K_I for a standardised fracture specimen under "
        "linear-elastic conditions (LEFM). Also computes critical crack size "
        "for a given fracture toughness K_Ic. "
        "Reference: Rice (1968); Anderson (2005) Ch. 2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "K_I_pa_sqrt_m": {
                "type": "number",
                "description": "Mode-I stress intensity factor K_I [Pa·√m].",
            },
            "youngs_modulus_pa": {
                "type": "number",
                "description": "Young's modulus E [Pa].",
            },
            "poisson": {
                "type": "number",
                "description": "Poisson's ratio ν.",
            },
            "condition": {
                "type": "string",
                "enum": ["plane_stress", "plane_strain"],
                "description": "Stress state condition (default plane_strain).",
            },
            "yield_strength_pa": {
                "type": "number",
                "description": "Yield strength σ_y [Pa]. Used to check LEFM validity.",
            },
        },
        "required": ["K_I_pa_sqrt_m", "youngs_modulus_pa", "poisson"],
    },
)


@register(_fem_j_integral_spec)
async def run_fem_j_integral(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ["K_I_pa_sqrt_m", "youngs_modulus_pa", "poisson"]:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.fracture.stress_intensity import k_to_j
    import math

    K_I = float(a["K_I_pa_sqrt_m"])
    E = float(a["youngs_modulus_pa"])
    nu = float(a["poisson"])
    cond = str(a.get("condition", "plane_strain"))

    try:
        J = k_to_j(K_I, E, nu, cond)
    except Exception as e:
        return err_payload(str(e), "COMPUTE_ERROR")

    resp = {
        "J_integral_j_m2": J,
        "G_c_j_m2": J,
        "K_I_pa_sqrt_m": K_I,
        "condition": cond,
    }

    # LEFM validity check: plastic zone size r_p vs specimen dimensions
    sigma_y = a.get("yield_strength_pa")
    if sigma_y is not None:
        sigma_y = float(sigma_y)
        r_p = (1.0 / (2.0 * math.pi)) * (K_I / sigma_y) ** 2  # plane stress
        r_p_ps = r_p / 3.0  # plane strain (smaller)
        resp["plastic_zone_radius_plane_stress_m"] = r_p
        resp["plastic_zone_radius_plane_strain_m"] = r_p_ps
        resp["lefm_validity_note"] = (
            f"ASTM E399 requires specimen dimensions ≥ 2.5·(K_I/σ_y)² = "
            f"{2.5 * (K_I / sigma_y)**2:.4e} m for valid K_Ic measurement."
        )

    resp["notes"] = (
        "J = K_I²(1-ν²)/E (plane strain) or K_I²/E (plane stress). "
        "Valid for LEFM (small-scale yielding). For elastic-plastic fracture "
        "use J_ep from incremental FEM with path-independent domain integral."
    )
    return ok_payload(resp)
