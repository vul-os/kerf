"""
LLM tool wrapper for incremental crack-propagation simulation.

Registers:
  fem_crack_growth_simulate — mesh + crack + load/cycles →
    crack path, K_I/K_II history, fatigue life N, stable/unstable flag.

References
----------
  Anderson, T. L. (2005). Fracture Mechanics, 3rd ed., CRC Press. Ch. 10.
  Erdogan, F. & Sih, G. C. (1963). J. Basic Eng. 85, 519–527.
  Paris, P. & Erdogan, F. (1963). J. Basic Eng. 85, 528–534.
  Tada, H., Paris, P. C., & Irwin, G. R. (2000). The Stress Analysis of
      Cracks Handbook, 3rd ed., ASME Press.
"""

from __future__ import annotations

import json
import math

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


_fem_crack_growth_simulate_spec = ToolSpec(
    name="fem_crack_growth_simulate",
    description=(
        "Incremental crack-propagation simulation on a 2-D cracked body (FEM). "
        "Given a cracked rectangular plate (edge crack or user-specified crack), "
        "Paris-law fatigue constants, and loading, this tool:\n"
        "  1. Solves a linear-elastic FEM for the cracked mesh at each increment.\n"
        "  2. Extracts K_I, K_II at the crack tip (displacement-correlation DCT "
        "     + handbook fallback).\n"
        "  3. Computes the mixed-mode growth direction θ_c (Erdogan-Sih 1963 "
        "     max hoop-stress criterion).\n"
        "  4. Advances the crack tip by Δa and updates the geometry.\n"
        "  5. Flags unstable fracture when K_max ≥ K_Ic.\n"
        "  6. Integrates Paris law (da/dN = C·ΔK^m) over the K history to "
        "     predict total fatigue life N.\n\n"
        "Outputs: crack path [[x,y],...], K_I/K_II vs crack-length arrays, "
        "fatigue life N [cycles], stable/unstable flag.\n\n"
        "Geometry: rectangular plate W×H, edge crack of initial length a_0 "
        "at mid-height, left edge. Mesh resolution nx×ny CST triangles.\n\n"
        "Caveats (honest):\n"
        "  • 2-D only (plane stress/strain). No 3-D crack front.\n"
        "  • CST elements + DCT extraction: K error ~5–15 % vs. quarter-point.\n"
        "  • No XFEM enrichment (Moës 1999) — mesh-tracked crack, not X-FEM.\n"
        "  • No cohesive-zone elements (see fem_cohesive_zone).\n"
        "  • K_Ic assumed constant (no R-curve / T-stress / constraint).\n\n"
        "References: Anderson (2005) Ch. 10; Erdogan & Sih (1963) J. Basic Eng. 85:519; "
        "Paris & Erdogan (1963) J. Basic Eng. 85:528; Tada et al. (2000)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            # Geometry
            "plate_width_m": {
                "type": "number",
                "description": "Plate width W [m].",
            },
            "plate_height_m": {
                "type": "number",
                "description": "Plate height H [m].",
            },
            "a_0_m": {
                "type": "number",
                "description": "Initial edge crack length a_0 [m] (from left edge, at mid-height).",
            },
            "mesh_nx": {
                "type": "integer",
                "description": "Mesh columns (default 12). More columns → better K accuracy.",
            },
            "mesh_ny": {
                "type": "integer",
                "description": "Mesh rows (default 10).",
            },
            # Material
            "youngs_modulus_pa": {
                "type": "number",
                "description": "Young's modulus E [Pa]. Default 200e9 (steel).",
            },
            "poisson": {
                "type": "number",
                "description": "Poisson's ratio ν. Default 0.3.",
            },
            "condition": {
                "type": "string",
                "enum": ["plane_stress", "plane_strain"],
                "description": "Stress state. Default 'plane_stress'.",
            },
            "thickness_m": {
                "type": "number",
                "description": "Plate thickness t [m] (plane stress). Default 0.01 m.",
            },
            # Loading
            "applied_stress_pa": {
                "type": "number",
                "description": (
                    "Remote tensile stress σ [Pa] applied to the top edge (y = H). "
                    "Creates Mode-I dominated loading."
                ),
            },
            "shear_stress_pa": {
                "type": "number",
                "description": (
                    "Remote shear stress τ [Pa] applied to the right edge. "
                    "Creates Mode-II contribution for mixed-mode growth."
                ),
            },
            # Paris law
            "C": {
                "type": "number",
                "description": "Paris coefficient C [m/cycle/(Pa√m)^m]. Steel ~3e-12.",
            },
            "m": {
                "type": "number",
                "description": "Paris exponent m. Metals: 2–4.",
            },
            "K_Ic_pa_sqrt_m": {
                "type": "number",
                "description": "Fracture toughness K_Ic [Pa√m]. Steel ~50 MPa√m.",
            },
            "K_th_pa_sqrt_m": {
                "type": "number",
                "description": "Threshold SIF range ΔK_th [Pa√m]. Default 0.",
            },
            "R_ratio": {
                "type": "number",
                "description": "Stress ratio R = K_min/K_max. Default 0.",
            },
            "delta_sigma_pa": {
                "type": "number",
                "description": "Cyclic stress range Δσ [Pa] for Paris law fatigue integration.",
            },
            # Simulation control
            "da_m": {
                "type": "number",
                "description": (
                    "Crack increment per step Δa [m]. "
                    "Typically 0.5–2 % of plate width for adequate accuracy."
                ),
            },
            "max_steps": {
                "type": "integer",
                "description": "Maximum propagation steps (default 30).",
            },
        },
        "required": [
            "plate_width_m", "plate_height_m", "a_0_m",
            "applied_stress_pa", "C", "m", "K_Ic_pa_sqrt_m",
            "delta_sigma_pa", "da_m",
        ],
    },
)


@register(_fem_crack_growth_simulate_spec)
async def run_fem_crack_growth_simulate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = [
        "plate_width_m", "plate_height_m", "a_0_m",
        "applied_stress_pa", "C", "m", "K_Ic_pa_sqrt_m",
        "delta_sigma_pa", "da_m",
    ]
    for key in required:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.fracture.crack_growth_sim import (
        build_edge_crack_mesh,
        Mesh2D,
        Material2D,
        BoundaryConditions,
        ParisLawParams as _Params,  # re-use from crack_growth
        simulate_crack_growth,
        handbook_sif_edge_crack,
        fatigue_life_from_K_history,
    )
    # ParisLawParams is actually from crack_growth, import directly
    from kerf_fem.fracture.crack_growth import ParisLawParams

    try:
        W = float(a["plate_width_m"])
        H = float(a["plate_height_m"])
        a0 = float(a["a_0_m"])
        sigma = float(a["applied_stress_pa"])
        shear = float(a.get("shear_stress_pa", 0.0))
        C = float(a["C"])
        m_exp = float(a["m"])
        K_Ic = float(a["K_Ic_pa_sqrt_m"])
        K_th = float(a.get("K_th_pa_sqrt_m", 0.0))
        R = float(a.get("R_ratio", 0.0))
        delta_sigma = float(a["delta_sigma_pa"])
        da = float(a["da_m"])
        max_steps = int(a.get("max_steps", 30))
        nx = int(a.get("mesh_nx", 12))
        ny = int(a.get("mesh_ny", 10))
        E = float(a.get("youngs_modulus_pa", 200e9))
        nu = float(a.get("poisson", 0.3))
        cond = str(a.get("condition", "plane_stress"))
        t = float(a.get("thickness_m", 0.01))
    except Exception as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    # Validate
    if W <= 0 or H <= 0:
        return err_payload("plate dimensions must be positive", "BAD_ARGS")
    if a0 <= 0 or a0 >= W:
        return err_payload("a_0_m must be 0 < a_0 < plate_width_m", "BAD_ARGS")
    if da <= 0:
        return err_payload("da_m must be positive", "BAD_ARGS")
    if C <= 0:
        return err_payload("C must be positive", "BAD_ARGS")
    if m_exp <= 0:
        return err_payload("m must be positive", "BAD_ARGS")
    if K_Ic <= 0:
        return err_payload("K_Ic_pa_sqrt_m must be positive", "BAD_ARGS")

    try:
        # Build mesh
        mesh, crack_tip_node = build_edge_crack_mesh(W, H, a0, nx=nx, ny=ny)
    except Exception as e:
        return err_payload(f"mesh build failed: {e}", "COMPUTE_ERROR")

    # Boundary conditions:
    #   - Bottom edge (y=0): fixed in y.
    #   - Left bottom corner: fixed in x (prevent rigid body rotation).
    #   - Top edge (y=H): distributed tensile load in y.
    #   - Right edge: shear load in y (for mixed-mode, optional).
    nodes = mesh.nodes
    n_nodes = len(nodes)
    tol = H / ny * 0.5

    fixed_dofs = []
    for i, (x, y) in enumerate(nodes):
        if y < tol:
            fixed_dofs.append(2 * i + 1)  # fix y at bottom
        if y < tol and x < W / nx:
            fixed_dofs.append(2 * i)      # fix x at one bottom-left node

    # Applied forces: distribute on top edge
    top_nodes = [i for i, (x, y) in enumerate(nodes) if y > H - tol]
    forces = {}
    if len(top_nodes) > 0:
        F_total_top = sigma * W * t
        f_per_node_y = F_total_top / len(top_nodes)
        for i in top_nodes:
            forces[2 * i + 1] = f_per_node_y

    # Optional shear on right edge
    if abs(shear) > 0:
        right_nodes = [i for i, (x, y) in enumerate(nodes) if x > W - W / nx * 0.5]
        if right_nodes:
            F_shear = shear * H * t
            f_shear_per = F_shear / len(right_nodes)
            for i in right_nodes:
                forces[2 * i + 1] = forces.get(2 * i + 1, 0.0) + f_shear_per

    bc = BoundaryConditions(fixed_dofs=list(set(fixed_dofs)), forces=forces)
    mat = Material2D(E=E, nu=nu, condition=cond, thickness=t)
    paris = ParisLawParams(C=C, m=m_exp, K_Ic=K_Ic, K_th=K_th, R_ratio=R)

    # Initial crack direction: +x (rightward)
    crack_dir = np.array([1.0, 0.0])

    try:
        result = simulate_crack_growth(
            mesh=mesh,
            mat=mat,
            bc=bc,
            crack_tip_node=crack_tip_node,
            crack_dir_initial=crack_dir,
            a_initial=a0,
            paris_params=paris,
            da=da,
            delta_sigma=delta_sigma,
            max_steps=max_steps,
            plate_width=W,
        )
    except Exception as e:
        return err_payload(f"simulation failed: {e}", "COMPUTE_ERROR")

    # Also compute handbook K_I at initial crack for reference
    K_handbook = handbook_sif_edge_crack(sigma, a0, W)

    # Fatigue life summary
    N_fatigue = result.N_fatigue

    # Re-integrate from K history for verification
    N_recalc = fatigue_life_from_K_history(
        result.K_eff_history, da, paris, delta_sigma
    )

    # Serialize crack path
    crack_path_list = [[float(p[0]), float(p[1])] for p in result.crack_path]

    resp = {
        "crack_path_m": crack_path_list,
        "crack_length_m": [float(v) for v in result.crack_length_m],
        "K_I_pa_sqrt_m": result.K_I_history,
        "K_II_pa_sqrt_m": result.K_II_history,
        "K_eff_pa_sqrt_m": result.K_eff_history,
        "kink_angle_deg": [math.degrees(th) for th in result.kink_angle_history],
        "N_fatigue_cycles": float(N_fatigue),
        "stable": result.stable,
        "stop_reason": result.stop_reason,
        "n_increments": result.n_increments,
        "K_handbook_initial_pa_sqrt_m": float(K_handbook),
        "plate_geometry": {
            "W_m": W, "H_m": H, "a0_m": a0, "condition": cond,
        },
        "paris_params": {
            "C": C, "m": m_exp, "K_Ic_pa_sqrt_m": K_Ic,
            "K_th_pa_sqrt_m": K_th, "R_ratio": R,
        },
    }

    if result.warnings:
        resp["warnings"] = result.warnings

    resp["notes"] = (
        "Incremental FEM crack-propagation: CST elements, DCT SIF extraction, "
        "Erdogan-Sih mixed-mode kink angle, Paris law fatigue life. "
        "2-D plane-stress/strain only. No XFEM enrichment (deferred T-100-C). "
        "K error vs. quarter-point elements: ~5–15 %. "
        "References: Anderson (2005) Ch. 10; Erdogan & Sih (1963); "
        "Paris & Erdogan (1963); Tada et al. (2000)."
    )

    return ok_payload(resp)


# TOOLS list for plugin.py
TOOLS = [
    ("fem_crack_growth_simulate", _fem_crack_growth_simulate_spec, run_fem_crack_growth_simulate),
]
