"""
LLM tool wrappers for contact mechanics.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)
Wave 12F: Coulomb friction (stick/slip return-mapping) + augmented-Lagrange

Registers:
  fem_hertzian_contact              — Hertzian contact (sphere/cylinder) closed-form
  fem_penalty_contact               — penalty contact force computation + friction
  fem_augmented_lagrangian_contact  — augmented-Lagrange contact with friction
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
# fem_hertzian_contact
# ---------------------------------------------------------------------------

_fem_hertzian_contact_spec = ToolSpec(
    name="fem_hertzian_contact",
    description=(
        "Compute Hertzian contact mechanics (closed-form) for sphere-on-flat, "
        "sphere-on-sphere, or cylinder-on-flat geometry. Returns peak contact "
        "pressure, contact radius/width, indentation depth, and subsurface "
        "von Mises stress. Pure elastic — no plasticity or adhesion. "
        "Reference: Johnson (1985) 'Contact Mechanics' Ch. 3-4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "geometry": {
                "type": "string",
                "enum": ["sphere_on_flat", "sphere_on_sphere", "cylinder_on_flat"],
                "description": "Contact geometry type.",
            },
            "radius_1_mm": {
                "type": "number",
                "description": "Radius of body 1 [mm]. For sphere: sphere radius.",
            },
            "radius_2_mm": {
                "type": "number",
                "description": (
                    "Radius of body 2 [mm]. Use 1e9 for a flat surface. "
                    "For sphere_on_sphere: second sphere radius."
                ),
            },
            "E1_pa": {"type": "number", "description": "Young's modulus of body 1 [Pa]."},
            "nu1": {"type": "number", "description": "Poisson's ratio of body 1."},
            "E2_pa": {"type": "number", "description": "Young's modulus of body 2 [Pa]."},
            "nu2": {"type": "number", "description": "Poisson's ratio of body 2."},
            "normal_load_n": {"type": "number", "description": "Applied normal load [N]."},
            "length_mm": {
                "type": "number",
                "description": (
                    "Contact length [mm]. Required for cylinder_on_flat geometry only."
                ),
            },
        },
        "required": [
            "geometry", "radius_1_mm", "radius_2_mm",
            "E1_pa", "nu1", "E2_pa", "nu2", "normal_load_n",
        ],
    },
)


@register(_fem_hertzian_contact_spec)
async def run_fem_hertzian_contact(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = ["geometry", "radius_1_mm", "radius_2_mm",
                "E1_pa", "nu1", "E2_pa", "nu2", "normal_load_n"]
    for key in required:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.contact.hertzian import (
        HertzianContactSpec, hertzian_sphere_on_flat, hertzian_cylinder_on_flat,
    )

    try:
        spec = HertzianContactSpec(
            geometry=str(a["geometry"]),
            radius_1_mm=float(a["radius_1_mm"]),
            radius_2_mm=float(a["radius_2_mm"]),
            E1_pa=float(a["E1_pa"]),
            nu1=float(a["nu1"]),
            E2_pa=float(a["E2_pa"]),
            nu2=float(a["nu2"]),
            normal_load_n=float(a["normal_load_n"]),
        )

        if spec.geometry in ("sphere_on_flat", "sphere_on_sphere"):
            result = hertzian_sphere_on_flat(spec)
        elif spec.geometry == "cylinder_on_flat":
            length_mm = a.get("length_mm")
            if length_mm is None:
                return err_payload("length_mm is required for cylinder_on_flat", "BAD_ARGS")
            result = hertzian_cylinder_on_flat(spec, float(length_mm))
        else:
            return err_payload(f"Unknown geometry: {spec.geometry}", "BAD_ARGS")

    except (ValueError, ZeroDivisionError) as e:
        return err_payload(str(e), "COMPUTE_ERROR")

    return ok_payload({
        "geometry": spec.geometry,
        "contact_pressure_max_pa": result.contact_pressure_max_pa,
        "contact_radius_mm": result.contact_radius_mm,
        "contact_depth_mm": result.contact_depth_mm,
        "von_mises_max_pa": result.von_mises_max_pa,
        "von_mises_depth_mm": result.von_mises_depth_mm,
        "notes": (
            "Hertz 1882 closed-form elastic solution. "
            "von Mises max occurs ~0.48a below surface for sphere contact. "
            "Does not account for plasticity, adhesion (JKR/DMT), or surface roughness."
        ),
    })


# ---------------------------------------------------------------------------
# fem_penalty_contact
# ---------------------------------------------------------------------------

_fem_penalty_contact_spec = ToolSpec(
    name="fem_penalty_contact",
    description=(
        "Compute penalty contact forces for slave nodes against a master surface. "
        "Returns normal and tangential (friction) forces per slave node, plus "
        "per-node contact status (open/stick/slip) and gap values. "
        "Uses node-to-segment (NTS) formulation with Coulomb stick/slip return-mapping. "
        "Reference: Wriggers (2006) 'Computational Contact Mechanics' §3.2 + §5.2."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slave_positions": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "2D positions of slave nodes [[x,y], ...] [m].",
            },
            "master_surface_points": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "2D positions of master surface points [[x,y], ...] [m].",
            },
            "contact_stiffness_n_per_m": {
                "type": "number",
                "description": "Normal penalty stiffness k_n [N/m]. Typical: E × element_size.",
            },
            "friction_coefficient": {
                "type": "number",
                "description": "Coulomb friction coefficient μ (default 0.0 = frictionless).",
            },
            "tangential_stiffness_n_per_m": {
                "type": "number",
                "description": "Tangential penalty stiffness k_t [N/m]. Defaults to k_n.",
            },
            "tangential_displacements": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Accumulated tangential displacement per slave node [m]. "
                    "Used to compute trial stick force for return-mapping. "
                    "Omit for zero tangential displacement."
                ),
            },
        },
        "required": ["slave_positions", "master_surface_points", "contact_stiffness_n_per_m"],
    },
)


@register(_fem_penalty_contact_spec)
async def run_fem_penalty_contact(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ["slave_positions", "master_surface_points", "contact_stiffness_n_per_m"]:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    import numpy as np
    from kerf_fem.contact.penalty import compute_contact_force_penalty_with_status

    try:
        slave = np.array(a["slave_positions"], dtype=float)
        master = np.array(a["master_surface_points"], dtype=float)
        k_n = float(a["contact_stiffness_n_per_m"])
        mu = float(a.get("friction_coefficient", 0.0))
        k_t = float(a["tangential_stiffness_n_per_m"]) if "tangential_stiffness_n_per_m" in a else None
        u_t_list = a.get("tangential_displacements")
        u_t = np.array(u_t_list, dtype=float) if u_t_list is not None else None

        fn, ft, statuses, gaps = compute_contact_force_penalty_with_status(
            slave, master, k_n,
            friction_coefficient=mu,
            tangential_stiffness_n_per_m=k_t,
            tangential_displacements=u_t,
        )
    except Exception as e:
        return err_payload(str(e), "COMPUTE_ERROR")

    n_active = int(np.any(fn != 0, axis=1).sum())
    n_stick = statuses.count("stick")
    n_slip = statuses.count("slip")

    return ok_payload({
        "normal_forces_n": fn.tolist(),
        "tangential_forces_n": ft.tolist(),
        "contact_status": statuses,
        "gaps_m": gaps.tolist(),
        "n_active_contacts": n_active,
        "n_stick": n_stick,
        "n_slip": n_slip,
        "notes": (
            "Penalty method with Coulomb return-mapping (Wriggers 2006 §5.2). "
            "Small penetration remains (penalty compliance). "
            "For exact enforcement use fem_augmented_lagrangian_contact."
        ),
    })


# ---------------------------------------------------------------------------
# fem_augmented_lagrangian_contact
# ---------------------------------------------------------------------------

_fem_auglag_contact_spec = ToolSpec(
    name="fem_augmented_lagrangian_contact",
    description=(
        "Augmented-Lagrange contact solver with Coulomb friction. "
        "Runs the Uzawa outer loop updating both normal (λ_n) and tangential "
        "(λ_t) Lagrange multipliers until penetration < tol. "
        "Achieves lower penetration than pure penalty at the same stiffness, "
        "without the ill-conditioning of very large penalty factors. "
        "Reports per-node status: open / stick / slip. "
        "Reference: Wriggers (2006) §5.3-5.4; Alart & Curnier (1991)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "initial_gap_m": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Initial gap per contact node [m]. Negative = initial penetration. "
                    "The augmented-Lagrange loop will drive active-node penetration → 0."
                ),
            },
            "penalty_normal": {
                "type": "number",
                "description": "Normal augmentation parameter k_n [N/m]. Typical: E/h.",
            },
            "penalty_tangential": {
                "type": "number",
                "description": "Tangential augmentation parameter k_t [N/m]. Defaults to k_n.",
            },
            "friction_coefficient": {
                "type": "number",
                "description": "Coulomb friction coefficient μ ≥ 0 (default 0.0 = frictionless).",
            },
            "tangential_slip_m": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Accumulated tangential slip increment per node [m] (default zeros). "
                    "Positive = forward slip direction."
                ),
            },
            "initial_lambda_n": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Initial normal Lagrange multipliers (default zeros).",
            },
            "initial_lambda_t": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Initial tangential Lagrange multipliers (default zeros).",
            },
            "max_iter": {
                "type": "integer",
                "description": "Maximum Uzawa iterations (default 100).",
            },
            "tol": {
                "type": "number",
                "description": "Convergence tolerance on penetration [m] (default 1e-6).",
            },
        },
        "required": ["initial_gap_m", "penalty_normal"],
    },
)


@register(_fem_auglag_contact_spec)
async def run_fem_augmented_lagrangian_contact(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ["initial_gap_m", "penalty_normal"]:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    import numpy as np
    from kerf_fem.contact.augmented_lagrangian import run_uzawa_loop_with_friction

    try:
        gap0 = np.array(a["initial_gap_m"], dtype=float)
        n = len(gap0)
        k_n = float(a["penalty_normal"])
        k_t = float(a.get("penalty_tangential", k_n))
        mu = float(a.get("friction_coefficient", 0.0))
        slip0 = np.array(a.get("tangential_slip_m", [0.0] * n), dtype=float)
        lam_n0 = np.array(a.get("initial_lambda_n", [0.0] * n), dtype=float)
        lam_t0 = np.array(a.get("initial_lambda_t", [0.0] * n), dtype=float)
        max_iter = int(a.get("max_iter", 100))
        tol = float(a.get("tol", 1e-6))

        # For this tool, gap and slip are fixed inputs (rigid contact model).
        # The Uzawa loop refines the Lagrange multipliers given the initial gap.
        # The effective gap after augmentation: g_auglag = g0 + lambda_n / k_n
        # (simulates how the global FEM system would respond to the contact forces).
        def gap_fn(lam_n, lam_t):
            return gap0 + lam_n / k_n  # rigid contact spring model

        def slip_fn(lam_n, lam_t):
            return slip0.copy()

        result = run_uzawa_loop_with_friction(
            lam_n0, lam_t0,
            gap_fn, slip_fn,
            k_n, k_t, mu,
            max_iter=max_iter,
            tol=tol,
        )

    except Exception as e:
        import traceback
        return err_payload(f"{e}\n{traceback.format_exc()}", "COMPUTE_ERROR")

    statuses = result["contact_status"]
    gap_final = result["gap_final"]

    # Penetration comparison: penalty-only gap vs augmented-Lagrange gap
    # Pure penalty would give gap_penalty = g0 + lambda_at_conv / k_n
    # which is equivalent but without the Lagrange multiplier accumulation.
    # After convergence, auglag penetration ≈ 0 whereas penalty penetration
    # = |g0| * k_n/(k_n + k_n) = |g0|/2 for a single step.
    penalty_penetration = [max(0.0, -g) for g in gap0]  # pure penalty (no lambda)
    auglag_penetration = [max(0.0, -g) for g in gap_final.tolist()]

    return ok_payload({
        "lambda_n_final": result["lambda_n_final"].tolist(),
        "lambda_t_final": result["lambda_t_final"].tolist(),
        "gap_final_m": gap_final.tolist(),
        "slip_final_m": result["slip_final"].tolist(),
        "contact_status": statuses,
        "n_open": statuses.count("open"),
        "n_stick": statuses.count("stick"),
        "n_slip": statuses.count("slip"),
        "iterations": result["iterations"],
        "converged": result["converged"],
        "penalty_penetration_m": penalty_penetration,
        "auglag_penetration_m": auglag_penetration,
        "notes": (
            "Augmented-Lagrange (Uzawa) with Coulomb friction return-mapping. "
            "Penetration converges to < tol regardless of penalty factor, "
            "avoiding ill-conditioning of large-penalty methods. "
            "Friction: stick |λ_t| < μλ_n; slip |λ_t| = μλ_n. "
            "Limitation: node-to-surface NTS; no self-contact between "
            "deformable bodies (mortar/segment-to-segment needed for that)."
        ),
    })


# ---------------------------------------------------------------------------
# TOOLS registry list (for plugin.py pattern)
# ---------------------------------------------------------------------------

TOOLS = [
    ("fem_hertzian_contact", _fem_hertzian_contact_spec, run_fem_hertzian_contact),
    ("fem_penalty_contact", _fem_penalty_contact_spec, run_fem_penalty_contact),
    ("fem_augmented_lagrangian_contact", _fem_auglag_contact_spec,
     run_fem_augmented_lagrangian_contact),
]
