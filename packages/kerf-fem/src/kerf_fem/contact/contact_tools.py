"""
LLM tool wrappers for contact mechanics.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)

Registers:
  fem_hertzian_contact   — Hertzian contact (sphere/cylinder) closed-form
  fem_penalty_contact    — penalty contact force computation
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
        "Returns normal and tangential (friction) forces per slave node. "
        "Uses node-to-segment (NTS) formulation with Coulomb friction. "
        "Reference: Wriggers (2006) 'Computational Contact Mechanics' §3.2."
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
                "description": "Penalty stiffness [N/m]. Typical: E × element_size.",
            },
            "friction_coefficient": {
                "type": "number",
                "description": "Coulomb friction coefficient μ (default 0.0 = frictionless).",
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
    from kerf_fem.contact.penalty import compute_contact_force_penalty

    try:
        slave = np.array(a["slave_positions"], dtype=float)
        master = np.array(a["master_surface_points"], dtype=float)
        k = float(a["contact_stiffness_n_per_m"])
        mu = float(a.get("friction_coefficient", 0.0))

        fn, ft = compute_contact_force_penalty(slave, master, k, mu)
    except Exception as e:
        return err_payload(str(e), "COMPUTE_ERROR")

    return ok_payload({
        "normal_forces_n": fn.tolist(),
        "tangential_forces_n": ft.tolist(),
        "n_active_contacts": int(np.any(fn != 0, axis=1).sum()),
        "notes": (
            "Penalty method: small penetration remains. "
            "For exact enforcement use fem_augmented_lagrangian_contact."
        ),
    })
