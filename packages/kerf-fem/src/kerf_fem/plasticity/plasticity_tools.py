"""
LLM tool specifications and runners for kerf-fem plasticity models.

Wave 12E: material plasticity (J2 / Drucker-Prager / Mohr-Coulomb / Hill)

Exposes four tools:
  - fem_plasticity_j2        : J2 (von Mises) return mapping
  - fem_plasticity_dp        : Drucker-Prager cone plasticity
  - fem_plasticity_mc        : Mohr-Coulomb multi-surface plasticity
  - fem_plasticity_hill      : Hill 1948 anisotropic plasticity

All tools operate on a single Gauss-point stress state and return the
updated stress, plastic strain increment, and mode flag.  They are
intentionally stateless (the caller manages internal-state arrays).
"""

from __future__ import annotations

import traceback

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload


# ---------------------------------------------------------------------------
# J2 (von Mises) tool
# ---------------------------------------------------------------------------

fem_plasticity_j2_spec = ToolSpec(
    name="fem_plasticity_j2",
    description=(
        "Single-Gauss-point J2 (von Mises) plasticity return mapping with "
        "combined isotropic and kinematic hardening (Simo-Hughes 1998 §3.3). "
        "Returns updated stress, internal state, and yield mode."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_trial": {
                "type": "array", "items": {"type": "number"},
                "description": (
                    "Elastic predictor stress in Voigt form "
                    "[σ_xx, σ_yy, σ_zz, σ_xy, σ_yz, σ_xz] [Pa]. Length 6."
                ),
            },
            "plastic_strain": {
                "type": "array", "items": {"type": "number"},
                "description": "Current plastic strain Voigt vector (6,). Defaults to zeros.",
            },
            "equivalent_plastic_strain": {
                "type": "number",
                "description": "Current accumulated equivalent plastic strain. Default 0.",
                "default": 0.0,
            },
            "back_stress": {
                "type": "array", "items": {"type": "number"},
                "description": "Current back-stress Voigt vector (6,). Defaults to zeros.",
            },
            "youngs_modulus_pa": {"type": "number", "description": "Young's modulus [Pa]."},
            "poisson": {"type": "number", "description": "Poisson ratio."},
            "yield_stress_pa": {"type": "number", "description": "Initial yield stress σ_y0 [Pa]."},
            "isotropic_hardening_pa": {
                "type": "number", "default": 0.0,
                "description": "Isotropic hardening modulus H_iso [Pa].",
            },
            "kinematic_hardening_pa": {
                "type": "number", "default": 0.0,
                "description": "Kinematic hardening modulus H_kin [Pa].",
            },
            "strain_increment": {
                "type": "array", "items": {"type": "number"},
                "description": "Total strain increment Δε Voigt (6,). Can be zeros.",
            },
        },
        "required": [
            "stress_trial", "youngs_modulus_pa", "poisson", "yield_stress_pa",
        ],
    },
)


def run_fem_plasticity_j2(params: dict, ctx=None) -> dict:
    try:
        from kerf_fem.plasticity.j2 import (
            J2PlasticityMaterial, J2State, return_map_j2, yield_function_j2,
        )

        stress_trial = np.asarray(params["stress_trial"], dtype=float)
        plastic_strain = np.asarray(
            params.get("plastic_strain", [0.0] * 6), dtype=float
        )
        eps_p_eq = float(params.get("equivalent_plastic_strain", 0.0))
        back_stress = np.asarray(
            params.get("back_stress", [0.0] * 6), dtype=float
        )
        strain_inc = np.asarray(
            params.get("strain_increment", [0.0] * 6), dtype=float
        )

        mat = J2PlasticityMaterial(
            youngs_modulus_pa=float(params["youngs_modulus_pa"]),
            poisson=float(params["poisson"]),
            yield_stress_pa=float(params["yield_stress_pa"]),
            isotropic_hardening_modulus_pa=float(params.get("isotropic_hardening_pa", 0.0)),
            kinematic_hardening_modulus_pa=float(params.get("kinematic_hardening_pa", 0.0)),
        )
        state_n = J2State(
            plastic_strain=plastic_strain,
            equivalent_plastic_strain=eps_p_eq,
            back_stress=back_stress,
        )

        stress_n1, state_n1, C_ep = return_map_j2(stress_trial, state_n, mat, strain_inc)
        f_val = yield_function_j2(stress_n1, state_n1, mat)

        return ok_payload({
            "stress_n1": stress_n1.tolist(),
            "plastic_strain_n1": state_n1.plastic_strain.tolist(),
            "equivalent_plastic_strain_n1": state_n1.equivalent_plastic_strain,
            "back_stress_n1": state_n1.back_stress.tolist(),
            "yield_value_n1": f_val,
            "yielded": bool(
                state_n1.equivalent_plastic_strain > eps_p_eq + 1e-15
            ),
        })
    except Exception as exc:
        return err_payload(f"fem_plasticity_j2 error: {exc}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Drucker-Prager tool
# ---------------------------------------------------------------------------

fem_plasticity_dp_spec = ToolSpec(
    name="fem_plasticity_dp",
    description=(
        "Single-Gauss-point Drucker-Prager return mapping (soils, concrete). "
        "Handles smooth-cone and apex returns (Borja 2013 §3.5)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_trial": {
                "type": "array", "items": {"type": "number"},
                "description": "Elastic predictor stress Voigt (6,) [Pa].",
            },
            "youngs_modulus_pa": {"type": "number"},
            "poisson": {"type": "number"},
            "cohesion_pa": {"type": "number", "description": "Cohesion c [Pa]."},
            "friction_angle_deg": {"type": "number", "description": "Friction angle φ [°]."},
            "dilation_angle_deg": {
                "type": "number", "default": 0.0,
                "description": "Dilation angle ψ [°]. 0 = non-dilatant.",
            },
        },
        "required": [
            "stress_trial", "youngs_modulus_pa", "poisson",
            "cohesion_pa", "friction_angle_deg",
        ],
    },
)


def run_fem_plasticity_dp(params: dict, ctx=None) -> dict:
    try:
        from kerf_fem.plasticity.drucker_prager import (
            DruckerPragerMaterial, return_map_dp, yield_function_dp,
        )

        stress_trial = np.asarray(params["stress_trial"], dtype=float)
        mat = DruckerPragerMaterial(
            youngs_modulus_pa=float(params["youngs_modulus_pa"]),
            poisson=float(params["poisson"]),
            cohesion_pa=float(params["cohesion_pa"]),
            friction_angle_deg=float(params["friction_angle_deg"]),
            dilation_angle_deg=float(params.get("dilation_angle_deg", 0.0)),
        )

        stress_n1, info = return_map_dp(stress_trial, mat)
        f_n1 = yield_function_dp(stress_n1, mat)

        return ok_payload({
            "stress_n1": stress_n1.tolist(),
            "yield_value_n1": f_n1,
            "mode": info["mode"],
            "delta_gamma": info["delta_gamma"],
            "yield_value_trial": info["yield_value_trial"],
        })
    except Exception as exc:
        return err_payload(f"fem_plasticity_dp error: {exc}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Mohr-Coulomb tool
# ---------------------------------------------------------------------------

fem_plasticity_mc_spec = ToolSpec(
    name="fem_plasticity_mc",
    description=(
        "Single-Gauss-point Mohr-Coulomb return mapping (soil mechanics, rock). "
        "Multi-surface return handles single-plane, edge, and apex cases "
        "(Sloan & Booker 1986)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_trial": {
                "type": "array", "items": {"type": "number"},
                "description": "Elastic predictor stress Voigt (6,) [Pa].",
            },
            "youngs_modulus_pa": {"type": "number"},
            "poisson": {"type": "number"},
            "cohesion_pa": {"type": "number", "description": "Cohesion c [Pa]."},
            "friction_angle_deg": {"type": "number", "description": "Friction angle φ [°]."},
            "dilation_angle_deg": {
                "type": "number", "default": 0.0,
                "description": "Dilation angle ψ [°].",
            },
        },
        "required": [
            "stress_trial", "youngs_modulus_pa", "poisson",
            "cohesion_pa", "friction_angle_deg",
        ],
    },
)


def run_fem_plasticity_mc(params: dict, ctx=None) -> dict:
    try:
        from kerf_fem.plasticity.mohr_coulomb import (
            MohrCoulombMaterial, return_map_mc, yield_function_mc,
        )

        stress_trial = np.asarray(params["stress_trial"], dtype=float)
        mat = MohrCoulombMaterial(
            youngs_modulus_pa=float(params["youngs_modulus_pa"]),
            poisson=float(params["poisson"]),
            cohesion_pa=float(params["cohesion_pa"]),
            friction_angle_deg=float(params["friction_angle_deg"]),
            dilation_angle_deg=float(params.get("dilation_angle_deg", 0.0)),
        )

        stress_n1, info = return_map_mc(stress_trial, mat)
        f_n1 = yield_function_mc(stress_n1, mat)

        return ok_payload({
            "stress_n1": stress_n1.tolist(),
            "yield_value_n1": f_n1,
            "mode": info["mode"],
            "yield_value_trial": info["yield_value_trial"],
            "principal_stresses_trial": info.get("principal_stresses_trial"),
        })
    except Exception as exc:
        return err_payload(f"fem_plasticity_mc error: {exc}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Hill anisotropic tool
# ---------------------------------------------------------------------------

fem_plasticity_hill_spec = ToolSpec(
    name="fem_plasticity_hill",
    description=(
        "Single-Gauss-point Hill 1948 anisotropic return mapping (sheet metal "
        "forming, rolled metals). Uses the Hill compliance matrix from "
        "anisotropic yield stresses and Lankford R-values (Hill 1948)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stress_trial": {
                "type": "array", "items": {"type": "number"},
                "description": "Elastic predictor stress Voigt (6,) [Pa].",
            },
            "youngs_modulus_pa": {"type": "number"},
            "poisson": {"type": "number"},
            "yield_stress_x_pa": {
                "type": "number",
                "description": "Yield stress in rolling direction (X) [Pa].",
            },
            "yield_stress_y_pa": {
                "type": "number",
                "description": "Yield stress in transverse direction (Y) [Pa].",
            },
            "yield_stress_z_pa": {
                "type": "number",
                "description": "Yield stress in thickness direction (Z) [Pa].",
            },
            "shear_yield_pa": {
                "type": "number",
                "description": "In-plane shear yield stress [Pa].",
            },
            "R_values": {
                "type": "array", "items": {"type": "number"},
                "description": "Lankford ratios [R_0, R_45, R_90]. Default [1,1,1].",
            },
        },
        "required": [
            "stress_trial", "youngs_modulus_pa", "poisson",
            "yield_stress_x_pa", "yield_stress_y_pa", "yield_stress_z_pa",
            "shear_yield_pa",
        ],
    },
)


def run_fem_plasticity_hill(params: dict, ctx=None) -> dict:
    try:
        from kerf_fem.plasticity.hill import (
            HillAnisotropicMaterial, return_map_hill, yield_function_hill,
        )

        stress_trial = np.asarray(params["stress_trial"], dtype=float)
        R_vals = tuple(params.get("R_values", [1.0, 1.0, 1.0]))

        mat = HillAnisotropicMaterial(
            youngs_modulus_pa=float(params["youngs_modulus_pa"]),
            poisson=float(params["poisson"]),
            yield_stress_x_pa=float(params["yield_stress_x_pa"]),
            yield_stress_y_pa=float(params["yield_stress_y_pa"]),
            yield_stress_z_pa=float(params["yield_stress_z_pa"]),
            shear_yield_pa=float(params["shear_yield_pa"]),
            R_values=R_vals,
        )

        stress_n1, info = return_map_hill(stress_trial, mat)
        f_n1 = yield_function_hill(stress_n1, mat)

        return ok_payload({
            "stress_n1": stress_n1.tolist(),
            "yield_value_n1": f_n1,
            "mode": info["mode"],
            "delta_gamma": info.get("delta_gamma", 0.0),
            "yield_value_trial": info["yield_value_trial"],
        })
    except Exception as exc:
        return err_payload(f"fem_plasticity_hill error: {exc}\n{traceback.format_exc()}")
