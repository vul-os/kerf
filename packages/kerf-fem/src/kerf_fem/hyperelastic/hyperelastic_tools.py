"""
LLM tool wrapper for hyperelastic material analysis.

Registers:
  fem_hyperelastic — compute stress-stretch response, strain energy, and
                     tangent modulus for Neo-Hookean, Mooney-Rivlin, Ogden N=1..3.

References
----------
  Holzapfel, G. A. (2000). "Nonlinear Solid Mechanics." Wiley. Ch. 6.
  Ogden, R. W. (1972). Proc. R. Soc. London A 326, 565-584.
  Rivlin, R. S. & Saunders, D. W. (1951). Philos. Trans. R. Soc. A 243, 251.
"""

from __future__ import annotations

import json
import math
from typing import List

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


_fem_hyperelastic_spec = ToolSpec(
    name="fem_hyperelastic",
    description=(
        "Compute stress-stretch response curves (uniaxial / biaxial / planar), "
        "strain energy density, and Lagrangian tangent modulus for hyperelastic "
        "rubber-like materials. Supports Neo-Hookean (Treloar 1943 / Rivlin 1948), "
        "Mooney-Rivlin 2-parameter (Mooney 1940), and Ogden N=1..3 (Ogden 1972). "
        "Returns true (Cauchy) stress vs stretch arrays suitable for plotting. "
        "\n\nClosed-form oracles are used for incompressible uniaxial: "
        "NH σ = μ(λ²-λ⁻¹); MR σ = 2(λ²-λ⁻¹)(C10+C01/λ); "
        "Ogden σ = Σμ_p(λ^α_p - λ^{-α_p/2}). "
        "\n\nReferences: Holzapfel 2000 Ch.6; Ogden 1972; ASTM D412."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "enum": ["neo_hookean", "mooney_rivlin", "ogden"],
                "description": (
                    "Hyperelastic model. "
                    "'neo_hookean': single-parameter NH (W = μ/2(I1-3) - μ lnJ + λ/2(lnJ)²); "
                    "'mooney_rivlin': 2-parameter MR (W = C10(Ī1-3)+C01(Ī2-3)); "
                    "'ogden': principal-stretch Ogden N=1..3."
                ),
            },
            "loading": {
                "type": "string",
                "enum": ["uniaxial", "biaxial", "planar"],
                "description": (
                    "Loading mode. "
                    "'uniaxial': F=diag(λ,1/√λ,1/√λ); "
                    "'biaxial': F=diag(λ,λ,1/λ²); "
                    "'planar': F=diag(λ,1,1/λ)."
                ),
            },
            "stretch_max": {
                "type": "number",
                "description": "Maximum stretch λ_max (default 4 for uniaxial, 3 for biaxial/planar).",
            },
            "n_points": {
                "type": "integer",
                "description": "Number of stretch values in curve (default 50).",
            },
            # Neo-Hookean
            "mu_pa": {
                "type": "number",
                "description": (
                    "Shear modulus μ [Pa] for Neo-Hookean / Ogden. "
                    "Typical vulcanised rubber: 0.1–1 MPa."
                ),
            },
            # Mooney-Rivlin
            "C10_pa": {
                "type": "number",
                "description": "Mooney-Rivlin C10 [Pa]. Typical rubber: C10 ≈ 0.1–0.4 MPa.",
            },
            "C01_pa": {
                "type": "number",
                "description": "Mooney-Rivlin C01 [Pa]. Typical rubber: C01 ≈ 0.01–0.1 MPa.",
            },
            "d_inv_pa": {
                "type": "number",
                "description": (
                    "Compressibility parameter d [Pa⁻¹]; K = 2/d. "
                    "Set 0 for incompressible assumption (default)."
                ),
            },
            # Ogden
            "ogden_mu_p_pa": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Ogden moduli [μ_1, μ_2, ...] in Pa. Length 1–3. "
                    "Treloar 1944 natural rubber: μ_p = [1.491e6, 0.003e6, -0.023e6] Pa."
                ),
            },
            "ogden_alpha_p": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Ogden exponents [α_1, α_2, ...]. Same length as ogden_mu_p_pa. "
                    "Treloar: α_p = [1.3, 5.0, -2.0] (Ogden 1972 Table 1)."
                ),
            },
            "ogden_kappa_pa": {
                "type": "number",
                "description": "Ogden volumetric bulk modulus κ [Pa] (default 1e9 Pa = 1 GPa).",
            },
            # Single-point evaluation
            "F_matrix": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": (
                    "Optional 3×3 deformation gradient F for single-point stress/strain-energy "
                    "evaluation. If provided, returns stress tensor and W in addition to curve."
                ),
            },
        },
        "required": ["model", "loading"],
    },
)


@register(_fem_hyperelastic_spec)
async def run_fem_hyperelastic(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    model_name = str(a.get("model", "mooney_rivlin"))
    loading = str(a.get("loading", "uniaxial"))
    n_points = int(a.get("n_points", 50))

    # Default stretch_max depends on loading mode
    default_stretch = 4.0 if loading == "uniaxial" else 3.0
    stretch_max = float(a.get("stretch_max", default_stretch))
    if stretch_max <= 1.0:
        return err_payload("stretch_max must be > 1.0", "BAD_ARGS")

    # Build HyperelasticModel
    from kerf_fem.hyperelastic.models import (
        HyperelasticModel,
        uniaxial_response, biaxial_response, planar_response,
        uniaxial_cauchy_stress,
        neo_hookean_uniaxial_cauchy,
        mooney_rivlin_uniaxial_cauchy,
        ogden_uniaxial_cauchy,
        neo_hookean_tangent, mooney_rivlin_tangent, ogden_tangent,
        neo_hookean_strain_energy, mooney_rivlin_strain_energy, ogden_strain_energy,
        neo_hookean_stress, mooney_rivlin_stress, ogden_stress,
    )

    try:
        if model_name == "neo_hookean":
            mu = float(a.get("mu_pa", 0.4e6))
            if mu <= 0:
                return err_payload("mu_pa must be positive", "BAD_ARGS")
            mat = HyperelasticModel(
                model="neo_hookean",
                mu=mu,
                lam=1000.0 * mu / 3.0,
                C10=mu / 2.0,
            )
            model_params = {"mu_pa": mu, "initial_shear_modulus_pa": mu}

        elif model_name == "mooney_rivlin":
            C10 = float(a.get("C10_pa", 0.15e6))
            C01 = float(a.get("C01_pa", 0.015e6))
            d = float(a.get("d_inv_pa", 0.0))
            if C10 <= 0:
                return err_payload("C10_pa must be positive", "BAD_ARGS")
            mat = HyperelasticModel(model="mooney_rivlin", C10=C10, C01=C01, d=d)
            mu_init = 2.0 * (C10 + C01)
            model_params = {"C10_pa": C10, "C01_pa": C01, "d_inv_pa": d,
                            "initial_shear_modulus_pa": mu_init}

        elif model_name == "ogden":
            mu_p = [float(v) for v in a.get("ogden_mu_p_pa", [0.63e6])]
            alpha_p = [float(v) for v in a.get("ogden_alpha_p", [1.3])]
            kappa = float(a.get("ogden_kappa_pa", 1e9))
            if len(mu_p) != len(alpha_p):
                return err_payload("ogden_mu_p_pa and ogden_alpha_p must have same length", "BAD_ARGS")
            if not (1 <= len(mu_p) <= 3):
                return err_payload("Ogden N must be 1, 2, or 3", "BAD_ARGS")
            mat = HyperelasticModel(model="ogden", mu_p=mu_p, alpha_p=alpha_p, kappa=kappa)
            # Initial shear modulus: μ = (1/2) Σ μ_p α_p
            mu_init = 0.5 * sum(m * a_ for m, a_ in zip(mu_p, alpha_p))
            model_params = {
                "ogden_mu_p_pa": mu_p, "ogden_alpha_p": alpha_p,
                "ogden_kappa_pa": kappa,
                "initial_shear_modulus_pa": mu_init,
                "N_terms": len(mu_p),
            }
        else:
            return err_payload(f"Unknown model: {model_name!r}", "BAD_ARGS")

    except Exception as e:
        return err_payload(f"model parameter error: {e}", "BAD_ARGS")

    # Compute stress-stretch curve
    try:
        if loading == "uniaxial":
            lambdas, sigma = uniaxial_response(mat, stretch_max=stretch_max, n_points=n_points)
        elif loading == "biaxial":
            lambdas, sigma = biaxial_response(mat, stretch_max=stretch_max, n_points=n_points)
        elif loading == "planar":
            lambdas, sigma = planar_response(mat, stretch_max=stretch_max, n_points=n_points)
        else:
            return err_payload(f"Unknown loading: {loading!r}", "BAD_ARGS")
    except Exception as e:
        return err_payload(f"stress-stretch computation failed: {e}", "COMPUTE_ERROR")

    resp = {
        "model": model_name,
        "loading": loading,
        "stretch_lambda": lambdas.tolist(),
        "cauchy_stress_pa": sigma.tolist(),
        "sigma_at_stretch_max_pa": float(sigma[-1]),
        "model_params": model_params,
    }

    # Closed-form oracle for uniaxial (validation)
    # oracle returns incompressible closed-form = sigma_11 - sigma_22 (free-surface Cauchy)
    if loading == "uniaxial":
        try:
            oracle = [uniaxial_cauchy_stress(mat, lam) for lam in lambdas]
            resp["cauchy_stress_analytical_pa"] = oracle
            max_err = max(abs(s - o) / max(abs(o), 1.0)
                          for s, o in zip(sigma.tolist(), oracle))
            resp["max_relative_error_vs_analytical"] = max_err
        except Exception:
            pass

    # Single-point F evaluation
    F_raw = a.get("F_matrix")
    if F_raw is not None:
        try:
            F = np.array(F_raw, dtype=float)
            if F.shape != (3, 3):
                return err_payload("F_matrix must be 3×3", "BAD_ARGS")
            if model_name == "neo_hookean":
                W = neo_hookean_strain_energy(F, mat.mu, mat.lam)
                sigma_pt = neo_hookean_stress(F, mat.mu, mat.lam)
                C_mat = neo_hookean_tangent(F, mat.mu, mat.lam)
            elif model_name == "mooney_rivlin":
                W = mooney_rivlin_strain_energy(F, mat.C10, mat.C01, mat.d)
                sigma_pt = mooney_rivlin_stress(F, mat.C10, mat.C01, mat.d)
                C_mat = mooney_rivlin_tangent(F, mat.C10, mat.C01, mat.d)
            else:  # ogden
                W = ogden_strain_energy(F, mat.mu_p, mat.alpha_p, mat.kappa)
                sigma_pt = ogden_stress(F, mat.mu_p, mat.alpha_p, mat.kappa)
                C_mat = ogden_tangent(F, mat.mu_p, mat.alpha_p, mat.kappa)

            resp["single_point"] = {
                "F_matrix": F.tolist(),
                "J_det_F": float(np.linalg.det(F)),
                "strain_energy_density_j_m3": float(W),
                "cauchy_stress_pa": sigma_pt.tolist(),
                "lagrangian_tangent_voigt_pa": C_mat.tolist(),
            }
        except Exception as e:
            resp["single_point_error"] = str(e)

    resp["notes"] = (
        f"Hyperelastic {model_name} ({loading} loading). "
        "Cauchy (true) stress vs stretch λ. "
        "For uniaxial, analytical oracle is the exact incompressible closed form: "
        "NH: σ=μ(λ²-1/λ); MR: σ=2(λ²-1/λ)(C10+C01/λ); "
        "Ogden: σ=Σμ_p(λ^α_p - λ^{-α_p/2}). "
        "References: Holzapfel (2000) Ch.6; Ogden (1972) Proc. R. Soc. A 326."
    )
    return ok_payload(resp)


# TOOLS list for plugin.py registration
TOOLS = [
    ("fem_hyperelastic", _fem_hyperelastic_spec, run_fem_hyperelastic),
]
