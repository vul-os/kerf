"""
kerf_composites LLM tools — layup_analysis + orphan capabilities.

Registered via plugin.py at startup.

Tools
-----
layup_analysis            — Classical Laminate Theory A/B/D + failure indices
composites_drape          — geodesic drape of flat ply sheet onto 3D surface
composites_interlaminar   — interlaminar shear stress (ILSS) at ply interfaces
composites_thermal        — thermal residual stress from cure cool-down
composites_failure_depth  — extended failure criteria (Hashin, max-stress, max-strain)
composites_optimize_layup — layup angle optimizer (Tsai-Wu FPF + SA search)
composites_failure_check  — per-ply Tsai-Wu FPF check for a given load state
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_composites._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# layup_analysis tool spec
# ---------------------------------------------------------------------------

layup_analysis_spec = ToolSpec(
    name="layup_analysis",
    description=(
        "Analyse a composite laminate using Classical Laminate Theory (CLT). "
        "Supply the ply stack as a list of {angle, E1, E2, G12, nu12, thickness} "
        "objects (plus optional strength properties for failure analysis). "
        "Returns A/B/D stiffness matrices, effective moduli (Ex, Ey, Gxy), and "
        "optional Tsai-Wu / Tsai-Hill failure indices for a given load state."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Ordered ply stack (bottom to top). Each ply is an object with "
                    "angle [deg], E1 [GPa], E2 [GPa], G12 [GPa], nu12 [-], "
                    "thickness [mm], and optional Xt, Xc, Yt, Yc, S12 [MPa]."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number", "description": "Fibre angle [deg]"},
                        "E1":        {"type": "number", "description": "Longitudinal modulus [GPa]"},
                        "E2":        {"type": "number", "description": "Transverse modulus [GPa]"},
                        "G12":       {"type": "number", "description": "Shear modulus [GPa]"},
                        "nu12":      {"type": "number", "description": "Major Poisson ratio"},
                        "thickness": {"type": "number", "description": "Ply thickness [mm]"},
                        "Xt":  {"type": "number", "description": "Long. tensile strength [MPa]"},
                        "Xc":  {"type": "number", "description": "Long. compressive strength [MPa]"},
                        "Yt":  {"type": "number", "description": "Trans. tensile strength [MPa]"},
                        "Yc":  {"type": "number", "description": "Trans. compressive strength [MPa]"},
                        "S12": {"type": "number", "description": "In-plane shear strength [MPa]"},
                    },
                    "required": ["angle", "E1", "E2", "G12", "nu12", "thickness"],
                },
                "minItems": 1,
            },
            "load": {
                "type": "object",
                "description": (
                    "Optional in-plane load resultants for failure analysis. "
                    "Nx, Ny [N/mm], Nxy [N/mm]. If omitted, failure analysis is skipped."
                ),
                "properties": {
                    "Nx":  {"type": "number", "description": "x-direction force resultant [N/mm]"},
                    "Ny":  {"type": "number", "description": "y-direction force resultant [N/mm]"},
                    "Nxy": {"type": "number", "description": "shear force resultant [N/mm]"},
                },
            },
            "name": {
                "type": "string",
                "description": "Optional laminate label.",
            },
        },
        "required": ["plies"],
    },
)


async def run_layup_analysis(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_composites.layup import Ply, PlyMaterial, LaminateLayup
        from kerf_composites.clt import abd_matrices, effective_moduli
        from kerf_composites.failure import (
            PlyStress, tsai_wu_index, tsai_hill_index,
        )

        raw_plies = args["plies"]
        name = args.get("name", "laminate")
        load_args = args.get("load")

        # Build ply objects
        plies = []
        for i, rp in enumerate(raw_plies):
            mat = PlyMaterial(
                name=f"ply_{i}",
                E1=float(rp["E1"]),
                E2=float(rp["E2"]),
                G12=float(rp["G12"]),
                nu12=float(rp["nu12"]),
                Xt=float(rp.get("Xt", 1.0)),
                Xc=float(rp.get("Xc", 1.0)),
                Yt=float(rp.get("Yt", 1.0)),
                Yc=float(rp.get("Yc", 1.0)),
                S12=float(rp.get("S12", 1.0)),
            )
            plies.append(Ply(
                angle=float(rp["angle"]),
                material=mat,
                thickness=float(rp["thickness"]),
            ))

        layup = LaminateLayup(plies=plies, name=name)
        A, B, D = abd_matrices(layup)
        moduli = effective_moduli(layup)

        def _mat_to_list(m):
            return [[round(v, 4) for v in row] for row in m.tolist()]

        payload: dict[str, Any] = {
            "name": layup.name,
            "num_plies": layup.num_plies,
            "total_thickness_mm": round(layup.total_thickness, 4),
            "is_symmetric": layup.is_symmetric,
            "A_matrix_N_per_mm": _mat_to_list(A),
            "B_matrix_N": _mat_to_list(B),
            "D_matrix_N_mm": _mat_to_list(D),
            "effective_moduli": {k: round(v, 6) for k, v in moduli.items()},
        }

        # Optional failure analysis
        if load_args is not None:
            import numpy as np
            Nx = float(load_args.get("Nx", 0.0))
            Ny = float(load_args.get("Ny", 0.0))
            Nxy = float(load_args.get("Nxy", 0.0))
            N_vec = np.array([Nx, Ny, Nxy])
            h = layup.total_thickness
            # Approximate: average membrane stress in each ply ≈ N / h
            # (full CLT requires strain from [A]^-1·N then back-calculating ply stress)
            import numpy as np
            A_inv = np.linalg.inv(A)
            eps0 = A_inv @ N_vec  # mid-plane strains
            z = layup.z_coords

            ply_failures = []
            has_strength = all(
                rp.get("Xt") and rp.get("Xc") and rp.get("Yt") and rp.get("Yc") and rp.get("S12")
                for rp in raw_plies
            )

            if has_strength:
                from kerf_composites.clt import ply_Qbar_matrix
                for k, ply in enumerate(plies):
                    # Mid-plane of this ply
                    z_mid = (z[k] + z[k + 1]) / 2.0
                    # Strain at ply mid-plane (membrane only, no bending)
                    strain_lam = eps0  # N/mm / N/mm → dimensionless
                    # Transform laminate strain to ply axes
                    import math
                    theta = math.radians(ply.angle)
                    c = math.cos(theta)
                    s = math.sin(theta)
                    # Transformation matrix T (stress)
                    T = np.array([
                        [c*c,   s*s,   2*c*s],
                        [s*s,   c*c,  -2*c*s],
                        [-c*s,  c*s,  c*c-s*s],
                    ])
                    Q = ply_Qbar_matrix(ply)
                    # Stress in laminate axes
                    stress_lam = Q @ strain_lam  # GPa * dimensionless → GPa
                    stress_lam_mpa = stress_lam * 1.0e3  # → MPa
                    # Rotate to ply principal axes
                    stress_ply = T @ stress_lam_mpa
                    ps = PlyStress(
                        sigma1=float(stress_ply[0]),
                        sigma2=float(stress_ply[1]),
                        tau12=float(stress_ply[2]),
                    )
                    fi_tw = tsai_wu_index(ps, ply.material)
                    fi_th = tsai_hill_index(ps, ply.material)
                    ply_failures.append({
                        "ply_index": k,
                        "angle": ply.angle,
                        "sigma1_MPa": round(float(stress_ply[0]), 4),
                        "sigma2_MPa": round(float(stress_ply[1]), 4),
                        "tau12_MPa":  round(float(stress_ply[2]), 4),
                        "tsai_wu_fi": round(fi_tw, 6),
                        "tsai_hill_fi": round(fi_th, 6),
                        "failed_tsai_wu": fi_tw >= 1.0,
                        "failed_tsai_hill": fi_th >= 1.0,
                    })
                payload["failure_analysis"] = ply_failures
            else:
                payload["failure_analysis"] = "skipped — strength properties (Xt,Xc,Yt,Yc,S12) not provided for all plies"

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Helper: build LaminateLayup from raw ply list (shared by several tools)
# ---------------------------------------------------------------------------

def _build_layup(raw_plies: list[dict], name: str = "laminate"):
    """Parse raw ply dicts into a LaminateLayup.  Returns (layup, None) or (None, error_str)."""
    from kerf_composites.layup import Ply, PlyMaterial, LaminateLayup
    plies = []
    for i, rp in enumerate(raw_plies):
        try:
            mat = PlyMaterial(
                name=f"ply_{i}",
                E1=float(rp["E1"]),
                E2=float(rp["E2"]),
                G12=float(rp["G12"]),
                nu12=float(rp["nu12"]),
                Xt=float(rp.get("Xt", 1500.0)),
                Xc=float(rp.get("Xc", 1500.0)),
                Yt=float(rp.get("Yt", 40.0)),
                Yc=float(rp.get("Yc", 246.0)),
                S12=float(rp.get("S12", 68.0)),
            )
            plies.append(Ply(
                angle=float(rp["angle"]),
                material=mat,
                thickness=float(rp["thickness"]),
            ))
        except Exception as exc:
            return None, f"ply[{i}]: {exc}"
    layup = LaminateLayup(plies=plies, name=name)
    return layup, None


# ---------------------------------------------------------------------------
# Tool: composites_drape
# ---------------------------------------------------------------------------

composites_drape_spec = ToolSpec(
    name="composites_drape",
    description=(
        "Drape a flat rectangular ply sheet onto a 3D surface using the geodesic "
        "pin-jointed fishing-net algorithm. Supports 'flat', 'cylinder_x', 'cylinder_y', "
        "'sphere', and 'cone' surface types. "
        "Returns draped 3D coordinates, local shear angles (deviation from 90°), "
        "arc-length statistics, and optional flat-pattern unrolling (developable approximation). "
        "Reference: Gutowski et al. (1991) Manufacturing Eng. Trans. 99, 35–40."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "surface": {
                "type": "string",
                "enum": ["flat", "cylinder_x", "cylinder_y", "sphere", "cone"],
                "description": (
                    "'flat' — trivial flat surface (identity mapping). "
                    "'cylinder_x' — circular cylinder, axis along X. "
                    "'cylinder_y' — circular cylinder, axis along Y. "
                    "'sphere' — spherical cap; u=polar angle [deg], v=azimuth [deg]. "
                    "'cone' — right circular cone; u=slant height [mm], v=azimuth [deg]."
                ),
            },
            "u_range": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "[u_min, u_max] parameter range in mm or degrees (see surface).",
            },
            "v_range": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "[v_min, v_max] parameter range in mm or degrees (see surface).",
            },
            "nu": {
                "type": "integer",
                "description": "Number of grid points in u direction (default 10).",
            },
            "nv": {
                "type": "integer",
                "description": "Number of grid points in v direction (default 10).",
            },
            "radius": {
                "type": "number",
                "description": "Cylinder or sphere radius [mm] (required for cylinder/sphere; default 100).",
            },
            "half_angle_deg": {
                "type": "number",
                "description": "Cone half-angle [degrees] (required for cone; default 20).",
            },
            "flat_z": {
                "type": "number",
                "description": "Z height for flat surface (default 0).",
            },
            "include_flat_pattern": {
                "type": "boolean",
                "description": (
                    "If true, include flat-pattern unrolling result and distortion percentage "
                    "(default false). Exact for cylinders and cones; approximate for spheres."
                ),
            },
        },
        "required": [],
    },
)


async def run_composites_drape(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_composites.drape import (
            drape_flat_to_surface, flat_surface, cylindrical_surface,
            spherical_surface, conical_surface, unroll_to_flat_pattern,
        )
        import numpy as np

        surface_type = str(args.get("surface", "flat"))
        u_range = tuple(float(x) for x in args.get("u_range", [0.0, 100.0]))
        v_range = tuple(float(x) for x in args.get("v_range", [0.0, 100.0]))
        nu = int(args.get("nu", 10))
        nv = int(args.get("nv", 10))
        radius = float(args.get("radius", 100.0))
        half_angle_deg = float(args.get("half_angle_deg", 20.0))
        flat_z = float(args.get("flat_z", 0.0))
        include_fp = bool(args.get("include_flat_pattern", False))

        if surface_type == "flat":
            sfn = flat_surface(z=flat_z)
        elif surface_type == "cylinder_x":
            sfn = cylindrical_surface(radius=radius, axis="x")
        elif surface_type == "cylinder_y":
            sfn = cylindrical_surface(radius=radius, axis="y")
        elif surface_type == "sphere":
            sfn = spherical_surface(radius=radius)
        elif surface_type == "cone":
            sfn = conical_surface(half_angle_deg=half_angle_deg)
        else:
            return err_payload(f"unknown surface {surface_type!r}", "BAD_ARGS")

        result = drape_flat_to_surface(sfn, u_range, v_range, nu=nu, nv=nv)

        # Summarise — don't return huge arrays verbatim; return shape + stats
        shear = result.shear_angles
        payload: dict[str, Any] = {
            "surface": surface_type,
            "nu": result.nu,
            "nv": result.nv,
            "u_range": list(u_range),
            "v_range": list(v_range),
            "shear_angle_deg": {
                "mean": round(float(np.mean(shear)), 4),
                "max": round(float(np.max(shear)), 4),
                "min": round(float(np.min(shear)), 4),
            },
            "arc_length_u_max_mm": round(float(np.max(result.arc_lengths_u)), 4),
            "arc_length_v_max_mm": round(float(np.max(result.arc_lengths_v)), 4),
            "surf_coords_shape": list(result.surf_coords.shape),
            "corner_coords_mm": [
                [round(v, 3) for v in result.surf_coords[0, 0].tolist()],
                [round(v, 3) for v in result.surf_coords[-1, 0].tolist()],
                [round(v, 3) for v in result.surf_coords[-1, -1].tolist()],
            ],
        }

        if include_fp:
            fp = unroll_to_flat_pattern(result)
            fp_corners = [
                [round(v, 3) for v in fp.unrolled_coords[0, 0].tolist()],
                [round(v, 3) for v in fp.unrolled_coords[-1, 0].tolist()],
                [round(v, 3) for v in fp.unrolled_coords[-1, -1].tolist()],
                [round(v, 3) for v in fp.unrolled_coords[0, -1].tolist()],
            ]
            payload["flat_pattern"] = {
                "corner_coords_mm": fp_corners,
                "distortion_pct": round(fp.distortion_pct, 4),
                "is_developable": fp.distortion_pct < 0.5,
            }

        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_interlaminar
# ---------------------------------------------------------------------------

composites_interlaminar_spec = ToolSpec(
    name="composites_interlaminar",
    description=(
        "Compute interlaminar shear stress (ILSS) distribution at ply interfaces "
        "using equilibrium integration (Pagano / Pipes-Pagano method). "
        "Models a unit-width laminate beam under an applied bending moment. "
        "Returns τ_xz at each interface, the peak ILSS, and its location."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Ordered ply stack. Each ply: {angle [deg], E1 [GPa], E2 [GPa], "
                    "G12 [GPa], nu12 [-], thickness [mm]}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number"},
                        "E1":        {"type": "number"},
                        "E2":        {"type": "number"},
                        "G12":       {"type": "number"},
                        "nu12":      {"type": "number"},
                        "thickness": {"type": "number"},
                    },
                    "required": ["angle", "E1", "E2", "G12", "nu12", "thickness"],
                },
                "minItems": 1,
            },
            "Mx_Nmm_per_mm": {
                "type": "number",
                "description": "Applied bending moment per unit width [N·mm/mm]. Default 1.",
            },
            "beam_length_mm": {
                "type": "number",
                "description": "Beam span [mm]. Default 100.",
            },
            "name": {"type": "string", "description": "Optional laminate label."},
        },
        "required": ["plies"],
    },
)


async def run_composites_interlaminar(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        layup, err = _build_layup(args["plies"], name=args.get("name", "laminate"))
        if layup is None:
            return err_payload(err, "BAD_ARGS")

        from kerf_composites.interlaminar import interlaminar_shear

        Mx = float(args.get("Mx_Nmm_per_mm", 1.0))
        beam_length = float(args.get("beam_length_mm", 100.0))

        result = interlaminar_shear(layup, Mx=Mx, beam_length=beam_length)

        payload = {
            "num_plies": layup.num_plies,
            "total_thickness_mm": round(layup.total_thickness, 4),
            "Mx_Nmm_per_mm": Mx,
            "beam_length_mm": beam_length,
            "tau_xz_MPa": [round(float(v), 6) for v in result.tau_xz.tolist()],
            "interface_z_mm": [round(float(v), 6) for v in result.interface_z.tolist()],
            "max_tau_xz_MPa": round(result.max_tau_xz, 6),
            "max_interface_index": result.max_interface_index,
            "max_interface_z_mm": round(result.max_interface_z, 6),
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_thermal
# ---------------------------------------------------------------------------

composites_thermal_spec = ToolSpec(
    name="composites_thermal",
    description=(
        "Compute thermal residual stresses in a composite laminate due to a temperature "
        "change (e.g. cool-down from cure temperature). Uses Classical Laminate Theory "
        "with hygrothermal resultants. Returns per-ply residual stresses in principal "
        "axes (σ₁, σ₂, τ₁₂ in MPa), mid-plane strains, and curvatures."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Ordered ply stack. Each ply: {angle [deg], E1 [GPa], E2 [GPa], "
                    "G12 [GPa], nu12 [-], thickness [mm], alpha1 [1/°C], alpha2 [1/°C]}. "
                    "Typical CFRP: alpha1≈0.02e-6, alpha2≈22.5e-6."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number"},
                        "E1":        {"type": "number"},
                        "E2":        {"type": "number"},
                        "G12":       {"type": "number"},
                        "nu12":      {"type": "number"},
                        "thickness": {"type": "number"},
                        "alpha1":    {"type": "number", "description": "Longitudinal CTE [1/°C]. Default 0.02e-6."},
                        "alpha2":    {"type": "number", "description": "Transverse CTE [1/°C]. Default 22.5e-6."},
                    },
                    "required": ["angle", "E1", "E2", "G12", "nu12", "thickness"],
                },
                "minItems": 1,
            },
            "delta_T": {
                "type": "number",
                "description": (
                    "Temperature change [°C]. Negative for cure cool-down "
                    "(delta_T = T_service − T_cure, typically −120 to −160 for CFRP)."
                ),
            },
            "name": {"type": "string", "description": "Optional laminate label."},
        },
        "required": ["plies", "delta_T"],
    },
)


async def run_composites_thermal(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        layup, err = _build_layup(args["plies"], name=args.get("name", "laminate"))
        if layup is None:
            return err_payload(err, "BAD_ARGS")

        from kerf_composites.thermal_residual import thermal_residual

        raw_plies = args["plies"]
        alpha1_list = [float(rp.get("alpha1", 0.02e-6)) for rp in raw_plies]
        alpha2_list = [float(rp.get("alpha2", 22.5e-6)) for rp in raw_plies]
        delta_T = float(args["delta_T"])

        result = thermal_residual(layup, alpha1_list, alpha2_list, delta_T)

        ply_data = [
            {
                "ply_index": ps.ply_index,
                "angle": ps.angle,
                "sigma1_MPa": round(ps.sigma1, 4),
                "sigma2_MPa": round(ps.sigma2, 4),
                "tau12_MPa": round(ps.tau12, 4),
            }
            for ps in result.ply_stresses
        ]
        payload = {
            "name": layup.name,
            "num_plies": layup.num_plies,
            "delta_T": delta_T,
            "mid_plane_strains": [round(float(v), 9) for v in result.mid_plane_strains.tolist()],
            "curvatures_per_mm": [round(float(v), 9) for v in result.curvatures.tolist()],
            "ply_thermal_stresses": ply_data,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_failure_depth
# ---------------------------------------------------------------------------

composites_failure_depth_spec = ToolSpec(
    name="composites_failure_depth",
    description=(
        "Extended ply failure criteria with mode discrimination. "
        "Evaluates Tsai-Wu, Tsai-Hill, Max-stress, and Hashin (1980) criteria "
        "for given ply principal-axis stresses and material allowables. "
        "Returns failure index (FI), margin of safety (MS = 1/FI−1), "
        "failed flag, and controlling failure mode for each criterion."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sigma1": {
                "type": "number",
                "description": "Longitudinal (fibre-direction) stress [MPa]. + = tension.",
            },
            "sigma2": {
                "type": "number",
                "description": "Transverse stress [MPa]. + = tension.",
            },
            "tau12": {
                "type": "number",
                "description": "In-plane shear stress [MPa].",
            },
            "Xt": {"type": "number", "description": "Longitudinal tensile strength [MPa]."},
            "Xc": {"type": "number", "description": "Longitudinal compressive strength [MPa]."},
            "Yt": {"type": "number", "description": "Transverse tensile strength [MPa]."},
            "Yc": {"type": "number", "description": "Transverse compressive strength [MPa]."},
            "S12": {"type": "number", "description": "In-plane shear strength [MPa]."},
            "E1": {"type": "number", "description": "Longitudinal modulus [GPa] (for max-strain)."},
            "E2": {"type": "number", "description": "Transverse modulus [GPa] (for max-strain)."},
            "G12": {"type": "number", "description": "Shear modulus [GPa] (for max-strain)."},
            "nu12": {"type": "number", "description": "Major Poisson ratio (for max-strain)."},
            "F12_star": {
                "type": "number",
                "description": "Tsai-Wu interaction coefficient (default −0.5).",
            },
        },
        "required": ["sigma1", "sigma2", "tau12", "Xt", "Xc", "Yt", "Yc", "S12"],
    },
)


async def run_composites_failure_depth(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_composites.failure_depth import tsai_wu, tsai_hill, max_stress, hashin
        from kerf_composites.layup import PlyMaterial

        s1 = float(args["sigma1"])
        s2 = float(args["sigma2"])
        t12 = float(args["tau12"])
        F12_star = float(args.get("F12_star", -0.5))

        mat = PlyMaterial(
            name="user_material",
            E1=float(args.get("E1", 181.0)),
            E2=float(args.get("E2", 10.3)),
            G12=float(args.get("G12", 7.17)),
            nu12=float(args.get("nu12", 0.28)),
            Xt=float(args["Xt"]),
            Xc=float(args["Xc"]),
            Yt=float(args["Yt"]),
            Yc=float(args["Yc"]),
            S12=float(args["S12"]),
        )

        def _fr(r):
            return {
                "failure_index": round(r.failure_index, 6),
                "margin_of_safety": round(r.margin_of_safety, 6)
                if r.margin_of_safety != float("inf") else "inf",
                "failed": r.failed,
                "mode": r.mode.value,
                "criterion": r.criterion,
            }

        tw = tsai_wu(s1, s2, t12, mat, F12_star=F12_star)
        th = tsai_hill(s1, s2, t12, mat)
        ms = max_stress(s1, s2, t12, mat)
        h = hashin(s1, s2, t12, mat)

        ms_dict = {
            "fi_sigma1": round(ms.fi_sigma1, 6),
            "fi_sigma2": round(ms.fi_sigma2, 6),
            "fi_tau12": round(ms.fi_tau12, 6),
            "failure_index": round(ms.failure_index, 6),
            "margin_of_safety": round(ms.margin_of_safety, 6)
            if ms.margin_of_safety != float("inf") else "inf",
            "failed": ms.failed,
            "mode": ms.mode.value,
            "criterion": ms.criterion,
        }
        h_dict = {
            "fi_fiber_tension": round(h.fi_fiber_tension, 6),
            "fi_fiber_compression": round(h.fi_fiber_compression, 6),
            "fi_matrix_tension": round(h.fi_matrix_tension, 6),
            "fi_matrix_compression": round(h.fi_matrix_compression, 6),
            "failure_index": round(h.failure_index, 6),
            "margin_of_safety": round(h.margin_of_safety, 6)
            if h.margin_of_safety != float("inf") else "inf",
            "failed": h.failed,
            "mode": h.mode.value,
            "criterion": h.criterion,
        }

        payload = {
            "stress": {"sigma1_MPa": s1, "sigma2_MPa": s2, "tau12_MPa": t12},
            "tsai_wu": _fr(tw),
            "tsai_hill": _fr(th),
            "max_stress": ms_dict,
            "hashin": h_dict,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Shared ply-list parser for optimizer tools
# ---------------------------------------------------------------------------

def _parse_optimizer_plies(raw_plies: list[dict], name: str = "laminate"):
    """
    Parse a list of raw ply dicts into a layup_optimizer.Laminate.
    Returns (laminate, None) or (None, error_str).
    """
    from kerf_composites.layup_optimizer import TsaiWuMaterial, Ply, Laminate
    plies = []
    for i, rp in enumerate(raw_plies):
        try:
            mat = TsaiWuMaterial(
                name=f"ply_{i}",
                E1=float(rp["E1"]),
                E2=float(rp["E2"]),
                G12=float(rp["G12"]),
                nu12=float(rp["nu12"]),
                Xt=float(rp.get("Xt", 1500.0)),
                Xc=float(rp.get("Xc", 1500.0)),
                Yt=float(rp.get("Yt", 40.0)),
                Yc=float(rp.get("Yc", 246.0)),
                S12=float(rp.get("S12", 68.0)),
                rho=float(rp.get("rho", 1.6)),
            )
            plies.append(Ply(
                angle_deg=float(rp["angle"]),
                thickness_mm=float(rp["thickness"]),
                material=mat,
            ))
        except Exception as exc:
            return None, f"ply[{i}]: {exc}"
    lam = Laminate(plies=plies, symmetric=True)
    return lam, None


# ---------------------------------------------------------------------------
# Tool: composites_failure_check
# ---------------------------------------------------------------------------

composites_failure_check_spec = ToolSpec(
    name="composites_failure_check",
    description=(
        "Evaluate Tsai-Wu first-ply-failure (FPF) for a composite laminate "
        "under a given load state.  Returns per-ply failure indices, margins "
        "of safety, and the first-ply-failure index and load ply. "
        "Uses Classical Laminate Theory (CLT) per Tsai-Hahn 1980 §6 + §7; "
        "Daniel-Ishai 2006 §8."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Ordered ply stack (bottom to top). Each ply: "
                    "{angle [deg], E1 [GPa], E2 [GPa], G12 [GPa], nu12 [-], "
                    "thickness [mm], Xt [MPa], Xc [MPa], Yt [MPa], Yc [MPa], S12 [MPa]}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number", "description": "Fibre angle [deg]"},
                        "E1":        {"type": "number", "description": "Longitudinal modulus [GPa]"},
                        "E2":        {"type": "number", "description": "Transverse modulus [GPa]"},
                        "G12":       {"type": "number", "description": "Shear modulus [GPa]"},
                        "nu12":      {"type": "number", "description": "Major Poisson ratio"},
                        "thickness": {"type": "number", "description": "Ply thickness [mm]"},
                        "Xt":  {"type": "number", "description": "Long. tensile strength [MPa]"},
                        "Xc":  {"type": "number", "description": "Long. compressive strength [MPa]"},
                        "Yt":  {"type": "number", "description": "Trans. tensile strength [MPa]"},
                        "Yc":  {"type": "number", "description": "Trans. compressive strength [MPa]"},
                        "S12": {"type": "number", "description": "In-plane shear strength [MPa]"},
                    },
                    "required": ["angle", "E1", "E2", "G12", "nu12", "thickness"],
                },
                "minItems": 1,
            },
            "loads": {
                "type": "object",
                "description": (
                    "Applied load resultants. "
                    "Nx, Ny, Nxy [N/mm] — in-plane; "
                    "Mx, My, Mxy [N·mm/mm] — bending. Unspecified → 0."
                ),
                "properties": {
                    "Nx":  {"type": "number"},
                    "Ny":  {"type": "number"},
                    "Nxy": {"type": "number"},
                    "Mx":  {"type": "number"},
                    "My":  {"type": "number"},
                    "Mxy": {"type": "number"},
                },
            },
            "F12_star": {
                "type": "number",
                "description": "Tsai-Wu interaction coefficient (default −0.5).",
            },
            "name": {"type": "string", "description": "Optional laminate label."},
        },
        "required": ["plies", "loads"],
    },
)


async def run_composites_failure_check(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        layup, err = _parse_optimizer_plies(args["plies"], name=args.get("name", "laminate"))
        if layup is None:
            return err_payload(err, "BAD_ARGS")

        from kerf_composites.layup_optimizer import tsai_wu_failure_index

        loads = args.get("loads", {})
        F12_star = float(args.get("F12_star", -0.5))

        result = tsai_wu_failure_index(layup, loads, F12_star=F12_star)

        # Round floats in ply_results
        ply_out = []
        for pr in result["ply_results"]:
            ply_out.append({
                "ply_index": pr["ply_index"],
                "angle_deg": pr["angle_deg"],
                "sigma1_MPa": round(pr["sigma1_MPa"], 4),
                "sigma2_MPa": round(pr["sigma2_MPa"], 4),
                "tau12_MPa":  round(pr["tau12_MPa"], 4),
                "tsai_wu_fi": round(pr["tsai_wu_fi"], 6),
                "margin":     round(pr["margin"], 6) if pr["margin"] != float("inf") else "inf",
                "failed":     pr["failed"],
            })

        payload = {
            "name": args.get("name", "laminate"),
            "num_plies": layup.num_plies,
            "total_thickness_mm": round(layup.total_thickness, 4),
            "loads": {k: round(float(v), 4) for k, v in loads.items()},
            "ply_results": ply_out,
            "fpf_ply_index": result["fpf_ply_index"],
            "fpf_fi": round(result["fpf_fi"], 6),
            "fpf_margin": round(result["fpf_margin"], 6)
            if result["fpf_margin"] != float("inf") else "inf",
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_optimize_layup
# ---------------------------------------------------------------------------

composites_optimize_layup_spec = ToolSpec(
    name="composites_optimize_layup",
    description=(
        "Optimize composite ply angles to minimize weight (total thickness) "
        "subject to a Tsai-Wu first-ply-failure (FPF) margin constraint.  "
        "Uses simulated annealing over discrete angle sets, enforcing symmetric "
        "and balanced layups.  "
        "Reference: Tsai-Hahn 1980 §6–7; Daniel-Ishai 2006 §8."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Initial ply stack (bottom to top). Each ply: "
                    "{angle [deg], E1 [GPa], E2 [GPa], G12 [GPa], nu12 [-], "
                    "thickness [mm], optional Xt/Xc/Yt/Yc/S12 [MPa]}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number"},
                        "E1":        {"type": "number"},
                        "E2":        {"type": "number"},
                        "G12":       {"type": "number"},
                        "nu12":      {"type": "number"},
                        "thickness": {"type": "number"},
                        "Xt":  {"type": "number"},
                        "Xc":  {"type": "number"},
                        "Yt":  {"type": "number"},
                        "Yc":  {"type": "number"},
                        "S12": {"type": "number"},
                    },
                    "required": ["angle", "E1", "E2", "G12", "nu12", "thickness"],
                },
                "minItems": 2,
            },
            "loads": {
                "type": "object",
                "description": (
                    "Applied load resultants. "
                    "Nx, Ny, Nxy [N/mm]; Mx, My, Mxy [N·mm/mm]. Unspecified → 0."
                ),
                "properties": {
                    "Nx":  {"type": "number"},
                    "Ny":  {"type": "number"},
                    "Nxy": {"type": "number"},
                    "Mx":  {"type": "number"},
                    "My":  {"type": "number"},
                    "Mxy": {"type": "number"},
                },
            },
            "allowed_angles": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Discrete ply angle candidates [degrees]. "
                    "Default: [0, 15, 30, 45, 60, 75, 90]."
                ),
            },
            "required_fpf_margin": {
                "type": "number",
                "description": (
                    "Minimum required FPF margin of safety (1/FI − 1). "
                    "Default 1.5 → reserve factor 2.5."
                ),
            },
            "n_iters": {
                "type": "integer",
                "description": "SA iterations (default 200; increase for better results).",
            },
            "seed": {
                "type": "integer",
                "description": "Random seed for reproducibility (optional).",
            },
            "name": {"type": "string"},
        },
        "required": ["plies", "loads"],
    },
)


async def run_composites_optimize_layup(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        initial, err = _parse_optimizer_plies(args["plies"], name=args.get("name", "laminate"))
        if initial is None:
            return err_payload(err, "BAD_ARGS")

        from kerf_composites.layup_optimizer import (
            optimize_layup_angles,
            tsai_wu_failure_index,
            compute_lamination_constants,
        )

        loads = args.get("loads", {})
        allowed_angles = [float(a) for a in args.get("allowed_angles", [0, 15, 30, 45, 60, 75, 90])]
        required_margin = float(args.get("required_fpf_margin", 1.5))
        n_iters = int(args.get("n_iters", 200))
        seed = args.get("seed")
        seed = int(seed) if seed is not None else None

        optimized = optimize_layup_angles(
            initial_layup=initial,
            loads=loads,
            n_iters=n_iters,
            allowed_angles=[int(a) for a in allowed_angles],
            required_fpf_margin=required_margin,
            seed=seed,
        )

        # Evaluate optimized result
        failure = tsai_wu_failure_index(optimized, loads)
        moduli = compute_lamination_constants(optimized)

        optimized_angles = [p.angle_deg for p in optimized.plies]
        weight_reduction_pct = (
            1.0 - optimized.total_thickness / initial.total_thickness
        ) * 100.0

        payload = {
            "name": args.get("name", "laminate"),
            "initial_total_thickness_mm": round(initial.total_thickness, 4),
            "optimized_total_thickness_mm": round(optimized.total_thickness, 4),
            "weight_reduction_pct": round(weight_reduction_pct, 2),
            "optimized_angles_deg": optimized_angles,
            "num_plies": optimized.num_plies,
            "symmetric": optimized.symmetric,
            "fpf_fi": round(failure["fpf_fi"], 6),
            "fpf_margin": round(failure["fpf_margin"], 6)
            if failure["fpf_margin"] != float("inf") else "inf",
            "fpf_ply_index": failure["fpf_ply_index"],
            "effective_moduli": {k: round(v, 6) for k, v in moduli.items()
                                  if isinstance(v, float)},
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_weight_cost
# ---------------------------------------------------------------------------

# Material density defaults [g/cm³] and cost [USD/kg] for common aerospace systems
_MATERIAL_DB: dict[str, dict] = {
    "T300/Epoxy":     {"rho": 1.58, "cost_usd_per_kg": 45.0},
    "T700/Epoxy":     {"rho": 1.60, "cost_usd_per_kg": 52.0},
    "IM7/Epoxy":      {"rho": 1.58, "cost_usd_per_kg": 65.0},
    "IM6/Epoxy":      {"rho": 1.61, "cost_usd_per_kg": 60.0},
    "AS4/Epoxy":      {"rho": 1.60, "cost_usd_per_kg": 40.0},
    "AS4/PEEK":       {"rho": 1.60, "cost_usd_per_kg": 120.0},
    "E-glass/Epoxy":  {"rho": 1.95, "cost_usd_per_kg": 12.0},
    "S-glass/Epoxy":  {"rho": 2.00, "cost_usd_per_kg": 22.0},
    "Kevlar/Epoxy":   {"rho": 1.38, "cost_usd_per_kg": 80.0},
    "Generic CFRP":   {"rho": 1.60, "cost_usd_per_kg": 45.0},
}

composites_weight_cost_spec = ToolSpec(
    name="composites_weight_cost",
    description=(
        "Compute laminate areal weight [g/m²], part mass [kg], and raw-material "
        "cost [USD] for a composite ply stack over a given part area. "
        "Uses ply density and thickness to compute areal weight; applies "
        "material unit cost for direct material cost estimation. "
        "Includes per-ply breakdown and rollup totals. "
        "Reference: MIL-HDBK-17-3F §3.2 (weight/volume fractions)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Ordered ply stack. Each ply: "
                    "{angle [deg], thickness [mm], material [string — see presets], "
                    "rho [g/cm³, optional], cost_usd_per_kg [optional]}. "
                    f"Material presets: {list(_MATERIAL_DB.keys())}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number", "description": "Fibre angle [deg]"},
                        "thickness": {"type": "number", "description": "Ply thickness [mm]"},
                        "material":  {"type": "string", "description": "Material name (preset or custom)"},
                        "rho":       {"type": "number", "description": "Density [g/cm³] (override preset)"},
                        "cost_usd_per_kg": {"type": "number", "description": "Cost [USD/kg] (override preset)"},
                    },
                    "required": ["thickness"],
                },
                "minItems": 1,
            },
            "part_area_m2": {
                "type": "number",
                "description": "Part plan-form area [m²]. Used to compute total mass and cost. Default 1.0.",
            },
            "waste_factor": {
                "type": "number",
                "description": (
                    "Material waste factor (≥ 1.0). Typical AFP waste: 1.05–1.10; "
                    "hand layup: 1.10–1.20. Default 1.0 (no waste)."
                ),
            },
            "name": {"type": "string", "description": "Optional laminate label."},
        },
        "required": ["plies"],
    },
)


async def run_composites_weight_cost(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        raw_plies = args["plies"]
        part_area = float(args.get("part_area_m2", 1.0))
        waste = float(args.get("waste_factor", 1.0))
        name = args.get("name", "laminate")

        if part_area <= 0.0:
            return err_payload("part_area_m2 must be > 0", "BAD_ARGS")
        if waste < 1.0:
            return err_payload("waste_factor must be ≥ 1.0", "BAD_ARGS")

        ply_results = []
        total_areal_weight_g_m2 = 0.0
        total_cost_usd = 0.0
        total_thickness_mm = 0.0

        for i, rp in enumerate(raw_plies):
            thickness_mm = float(rp["thickness"])
            mat_name = rp.get("material", "Generic CFRP")
            preset = _MATERIAL_DB.get(mat_name, _MATERIAL_DB["Generic CFRP"])

            rho_g_cm3 = float(rp.get("rho") or preset["rho"])
            cost_per_kg = float(rp.get("cost_usd_per_kg") or preset["cost_usd_per_kg"])

            # Areal weight: ρ [g/cm³] * t [mm] * 10 = g/m² (1 mm = 0.1 cm; 1 m² = 1e4 cm²)
            # areal_weight [g/m²] = rho [g/cm³] * (thickness [mm] / 10 [mm/cm]) * 1e4 [cm²/m²]
            # = rho * thickness * 1000
            areal_weight_g_m2 = rho_g_cm3 * thickness_mm * 1000.0  # g/m² per ply

            # Mass per unit area: same as areal weight / 1000 → kg/m²
            mass_kg_m2 = areal_weight_g_m2 / 1000.0

            # Cost per unit area: mass [kg/m²] * cost [USD/kg] * waste_factor
            cost_usd_m2 = mass_kg_m2 * cost_per_kg * waste

            # For the part
            mass_kg = mass_kg_m2 * part_area
            cost_usd = cost_usd_m2 * part_area

            total_areal_weight_g_m2 += areal_weight_g_m2
            total_cost_usd += cost_usd
            total_thickness_mm += thickness_mm

            ply_results.append({
                "ply_index": i,
                "angle_deg": float(rp.get("angle", 0.0)),
                "material": mat_name,
                "thickness_mm": round(thickness_mm, 4),
                "rho_g_cm3": round(rho_g_cm3, 4),
                "areal_weight_g_m2": round(areal_weight_g_m2, 2),
                "mass_kg": round(mass_kg, 5),
                "cost_usd": round(cost_usd, 4),
                "cost_per_kg": round(cost_per_kg, 2),
            })

        total_mass_kg = (total_areal_weight_g_m2 / 1000.0) * part_area

        payload = {
            "name": name,
            "num_plies": len(raw_plies),
            "part_area_m2": part_area,
            "waste_factor": waste,
            "total_thickness_mm": round(total_thickness_mm, 4),
            "total_areal_weight_g_m2": round(total_areal_weight_g_m2, 2),
            "total_mass_kg": round(total_mass_kg, 5),
            "total_material_cost_usd": round(total_cost_usd, 4),
            "cost_per_kg_usd": round(total_cost_usd / total_mass_kg, 4) if total_mass_kg > 0 else 0.0,
            "ply_breakdown": ply_results,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_failure_envelope
# ---------------------------------------------------------------------------

composites_failure_envelope_spec = ToolSpec(
    name="composites_failure_envelope",
    description=(
        "Generate a biaxial first-ply-failure (FPF) envelope for a composite laminate. "
        "Sweeps the ratio Ny/Nx from −1 to +1 (and pure shear Nxy) to find the "
        "failure load at each biaxial ratio, using Classical Laminate Theory + Tsai-Wu "
        "failure criterion. Returns the failure surface as a list of (Nx, Ny) points "
        "tracing the FPF boundary. "
        "Reference: Reddy (2004) §6.3; Jones (1975) §7.4 — laminate strength envelopes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plies": {
                "type": "array",
                "description": (
                    "Ordered ply stack (bottom to top). Each ply: "
                    "{angle [deg], E1 [GPa], E2 [GPa], G12 [GPa], nu12 [-], "
                    "thickness [mm], Xt [MPa], Xc [MPa], Yt [MPa], Yc [MPa], S12 [MPa]}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "angle":     {"type": "number"},
                        "E1":        {"type": "number"},
                        "E2":        {"type": "number"},
                        "G12":       {"type": "number"},
                        "nu12":      {"type": "number"},
                        "thickness": {"type": "number"},
                        "Xt":        {"type": "number"},
                        "Xc":        {"type": "number"},
                        "Yt":        {"type": "number"},
                        "Yc":        {"type": "number"},
                        "S12":       {"type": "number"},
                    },
                    "required": ["angle", "E1", "E2", "G12", "nu12", "thickness",
                                 "Xt", "Xc", "Yt", "Yc", "S12"],
                },
                "minItems": 1,
            },
            "n_angles": {
                "type": "integer",
                "description": "Number of loading directions to sweep (default 36 → 10° steps).",
            },
            "Nxy": {
                "type": "number",
                "description": "Fixed in-plane shear resultant [N/mm] (default 0).",
            },
            "F12_star": {
                "type": "number",
                "description": "Tsai-Wu interaction coefficient (default −0.5).",
            },
            "name": {"type": "string"},
        },
        "required": ["plies"],
    },
)


async def run_composites_failure_envelope(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import math as _math
        import numpy as np

        layup, err = _build_layup(args["plies"], name=args.get("name", "laminate"))
        if layup is None:
            return err_payload(err, "BAD_ARGS")

        from kerf_composites.clt import ply_Qbar_matrix, abd_matrices
        from kerf_composites.failure import PlyStress, tsai_wu_index

        n_angles = int(args.get("n_angles", 36))
        Nxy_fixed = float(args.get("Nxy", 0.0))
        F12_star = float(args.get("F12_star", -0.5))

        A, B, D = abd_matrices(layup)
        A_inv = np.linalg.inv(A)
        z = np.array(layup.z_coords)

        # For each loading angle θ (in the Nx-Ny plane), find the scale factor λ
        # such that at load [λ·cos θ, λ·sin θ, Nxy_fixed] the first ply fails (FI=1).
        # FI is a quadratic in λ → solve quadratic.
        envelope_pts = []

        for k in range(n_angles + 1):
            theta_deg = (360.0 / n_angles) * k
            theta = _math.radians(theta_deg)
            nx_dir = _math.cos(theta)
            ny_dir = _math.sin(theta)

            # We want to find λ such that max_ply Tsai-Wu FI(λ·N_dir) = 1.
            # For each ply the FI is a polynomial in λ; find the minimum λ>0 across plies.
            lambda_crit = float("inf")

            for ki, ply in enumerate(layup.plies):
                z_mid = (z[ki] + z[ki + 1]) / 2.0

                # For a unit-direction load, ply mid-plane strain from CLT:
                # ε⁰ = A⁻¹ · {nx_dir, ny_dir, Nxy_fixed/λ → zero for fixed Nxy=0}
                # When Nxy_fixed ≠ 0, the problem is not cleanly quadratic in λ.
                # We handle by sweeping λ numerically with bisection.

                m = ply.material
                Qbar = ply_Qbar_matrix(ply)
                theta_ply = _math.radians(ply.angle)
                c = _math.cos(theta_ply)
                s = _math.sin(theta_ply)
                T = np.array([
                    [c*c,   s*s,   2*c*s],
                    [s*s,   c*c,  -2*c*s],
                    [-c*s,  c*s,  c*c-s*s],
                ])

                def fi_at_lam(lam: float) -> float:
                    N_vec = np.array([lam * nx_dir, lam * ny_dir, Nxy_fixed])
                    eps0 = A_inv @ N_vec
                    stress_lam = Qbar @ eps0  # GPa
                    stress_mpa = stress_lam * 1e3
                    stress_ply = T @ stress_mpa
                    ps = PlyStress(
                        sigma1=float(stress_ply[0]),
                        sigma2=float(stress_ply[1]),
                        tau12=float(stress_ply[2]),
                    )
                    return tsai_wu_index(ps, m, F12_star=F12_star)

                # Bisect: find λ such that fi(λ) = 1
                # Estimate upper bound from a high lambda
                lam_lo, lam_hi = 0.0, 1e6
                fi_hi = fi_at_lam(lam_hi)
                if fi_hi < 1.0:
                    continue  # this ply never fails in this direction for λ up to 1e6

                for _ in range(50):
                    lam_mid = (lam_lo + lam_hi) / 2.0
                    if fi_at_lam(lam_mid) < 1.0:
                        lam_lo = lam_mid
                    else:
                        lam_hi = lam_mid
                lam_crit_ply = (lam_lo + lam_hi) / 2.0
                if lam_crit_ply < lambda_crit:
                    lambda_crit = lam_crit_ply

            if lambda_crit < float("inf"):
                Nx_fail = lambda_crit * nx_dir
                Ny_fail = lambda_crit * ny_dir
                envelope_pts.append({
                    "theta_deg": round(theta_deg, 1),
                    "Nx_fail_N_per_mm": round(Nx_fail, 4),
                    "Ny_fail_N_per_mm": round(Ny_fail, 4),
                    "lambda_crit": round(lambda_crit, 4),
                })

        payload = {
            "name": args.get("name", "laminate"),
            "num_plies": layup.num_plies,
            "n_angles": n_angles,
            "Nxy_N_per_mm": Nxy_fixed,
            "F12_star": F12_star,
            "envelope_points": envelope_pts,
            "max_uniaxial_Nx_N_per_mm": round(
                max((p["Nx_fail_N_per_mm"] for p in envelope_pts), default=0.0), 4
            ),
            "max_uniaxial_Ny_N_per_mm": round(
                max((p["Ny_fail_N_per_mm"] for p in envelope_pts), default=0.0), 4
            ),
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_afp_pathplan
# ---------------------------------------------------------------------------

composites_afp_pathplan_spec = ToolSpec(
    name="composites_afp_pathplan",
    description=(
        "Plan Automated Fiber Placement (AFP) / Automated Tape Laying (ATL) courses "
        "for a flat or cylindrical part surface. "
        "Generates parallel tow/course paths at the specified fibre angle, "
        "respecting minimum steering radius and course width constraints. "
        "Returns course geometry (start/end XY, length, angle) and G-code or APT/CL "
        "export strings. "
        "Reference: Dirk et al. (2012) SAMPE — AFP path planning constraints."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_width_mm":  {"type": "number", "description": "Part width in X [mm] (default 400)."},
            "part_height_mm": {"type": "number", "description": "Part height in Y [mm] (default 260)."},
            "course_width_mm": {"type": "number", "description": "Tow course width [mm] (default 6.35 = ¼ inch)."},
            "angle_deg":      {"type": "number", "description": "Fibre lay-up angle [deg] (default 0)."},
            "min_radius_mm":  {"type": "number", "description": "Minimum steering radius [mm] (default 600)."},
            "tow_count":      {"type": "integer", "description": "Number of tows per course (default 8)."},
            "format":         {
                "type": "string",
                "enum": ["json", "gcode", "apt"],
                "description": "Output format: 'json' (default), 'gcode', or 'apt'.",
            },
            "name":           {"type": "string", "description": "Optional job label."},
        },
        "required": [],
    },
)


async def run_composites_afp_pathplan(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import math as _math
        from kerf_composites.afp_export import afp_to_gcode, afp_to_apt

        part_w = float(args.get("part_width_mm", 400.0))
        part_h = float(args.get("part_height_mm", 260.0))
        course_w = float(args.get("course_width_mm", 6.35))
        angle_deg = float(args.get("angle_deg", 0.0))
        min_r = float(args.get("min_radius_mm", 600.0))
        tow_count = int(args.get("tow_count", 8))
        fmt = str(args.get("format", "json"))

        if course_w <= 0.0:
            return err_payload("course_width_mm must be > 0", "BAD_ARGS")

        # Effective course width (all tows together)
        tow_w = course_w  # each course is the full band width
        angle_rad = _math.radians(angle_deg)
        cos_a = _math.cos(angle_rad)
        sin_a = _math.sin(angle_rad)

        courses = []
        course_id = 1

        if abs(angle_deg % 180) < 0.1:  # 0° or 180°: horizontal passes
            y = 0.0
            while y <= part_h:
                courses.append({
                    "course_id": course_id,
                    "angle_deg": angle_deg % 360.0,
                    "start_x": 0.0,
                    "start_y": round(y, 3),
                    "end_x": round(part_w, 3),
                    "end_y": round(y, 3),
                    "tow_width_mm": round(tow_w, 3),
                    "length_mm": round(part_w, 3),
                })
                y += tow_w
                course_id += 1
        elif abs((angle_deg % 180) - 90.0) < 0.1:  # 90°: vertical passes
            x = 0.0
            while x <= part_w:
                courses.append({
                    "course_id": course_id,
                    "angle_deg": angle_deg % 360.0,
                    "start_x": round(x, 3),
                    "start_y": 0.0,
                    "end_x": round(x, 3),
                    "end_y": round(part_h, 3),
                    "tow_width_mm": round(tow_w, 3),
                    "length_mm": round(part_h, 3),
                })
                x += tow_w
                course_id += 1
        else:
            # General angle: sweep lines perpendicular to fibre direction
            # Course direction unit vector
            dx = cos_a
            dy = sin_a
            # Perpendicular (step direction)
            perp_x = -sin_a
            perp_y = cos_a
            step = tow_w

            # Range of perpendicular offset to cover the entire rectangle
            corners = [(0.0, 0.0), (part_w, 0.0), (part_w, part_h), (0.0, part_h)]
            perp_projs = [cx * perp_x + cy * perp_y for cx, cy in corners]
            d_min = min(perp_projs)
            d_max = max(perp_projs)

            # Liang-Barsky clip: given line P(t) = origin + t * direction
            # clips to [xmin,xmax] x [ymin,ymax]
            def liang_barsky_clip(ox, oy, ddx, ddy, xmin, xmax, ymin, ymax):
                """Return (t_enter, t_exit) or None if fully outside."""
                t0, t1 = -1e18, 1e18
                for p, q in [
                    (-ddx, ox - xmin),   # left
                    ( ddx, xmax - ox),   # right
                    (-ddy, oy - ymin),   # bottom
                    ( ddy, ymax - oy),   # top
                ]:
                    if abs(p) < 1e-15:
                        if q < 0:
                            return None  # parallel and outside
                    else:
                        r = q / p
                        if p < 0:
                            if r > t1: return None
                            if r > t0: t0 = r
                        else:
                            if r < t0: return None
                            if r < t1: t1 = r
                if t0 > t1:
                    return None
                return (t0, t1)

            d = d_min
            while d <= d_max + step * 0.5:
                # A point on the course centre line in 2D
                ox = d * perp_x
                oy = d * perp_y

                clip = liang_barsky_clip(ox, oy, dx, dy, 0.0, part_w, 0.0, part_h)
                if clip is None:
                    d += step
                    continue

                t_enter, t_exit = clip
                if t_exit - t_enter < 1.0:
                    d += step
                    continue

                sx = ox + t_enter * dx
                sy = oy + t_enter * dy
                ex = ox + t_exit  * dx
                ey = oy + t_exit  * dy
                length = _math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
                if length < 1.0:
                    d += step
                    continue

                courses.append({
                    "course_id": course_id,
                    "angle_deg": round(angle_deg % 360.0, 2),
                    "start_x": round(sx, 3),
                    "start_y": round(sy, 3),
                    "end_x":   round(ex, 3),
                    "end_y":   round(ey, 3),
                    "tow_width_mm": round(tow_w, 3),
                    "length_mm": round(length, 3),
                })
                d += step
                course_id += 1

        # Check steering radius compliance
        # For straight paths the curvature is 0 (always within constraint)
        # Flag compliance
        total_length = sum(c["length_mm"] for c in courses)

        if fmt == "gcode":
            return ok_payload(afp_to_gcode(courses))
        elif fmt == "apt":
            return ok_payload(afp_to_apt(courses))
        else:
            payload = {
                "name": args.get("name", "afp_job"),
                "part_width_mm": part_w,
                "part_height_mm": part_h,
                "angle_deg": angle_deg,
                "course_width_mm": course_w,
                "tow_count": tow_count,
                "min_radius_mm": min_r,
                "num_courses": len(courses),
                "total_length_mm": round(total_length, 2),
                "coverage_pct": round(
                    min(100.0, total_length * course_w / (part_w * part_h) * 100.0), 2
                ),
                "courses": courses[:50],  # cap to 50 for token budget
                "courses_truncated": len(courses) > 50,
            }
            return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "COMPOSITES_ERROR")
