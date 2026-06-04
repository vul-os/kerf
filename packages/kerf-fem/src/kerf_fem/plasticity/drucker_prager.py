"""
Drucker-Prager plasticity model (soils, concrete, granular materials).

Theory
------
The Drucker-Prager (1952) criterion is a smooth approximation to Mohr-Coulomb
that circumscribes the hexagonal cone.  In terms of stress invariants:

    f = α·I₁ + √J₂ - k  ≤ 0

where
    I₁ = σ_xx + σ_yy + σ_zz      (first invariant, positive in tension)
    J₂ = (1/2) s:s                (second deviatoric invariant)
    α  = (2 sin φ) / (√3·(3 − sin φ))      (outer Mohr-Coulomb match)
    k  = (6 c cos φ) / (√3·(3 − sin φ))

    c   = cohesion [Pa]
    φ   = friction angle [°]

Non-associated flow uses a different dilation angle ψ in the plastic
potential:
    g = α_ψ·I₁ + √J₂  (same form but with α_ψ(ψ) instead of α(φ))

Return-mapping (Borja 2013 §3.5)
---------------------------------
Two regimes must be handled:
  A. Smooth-cone return: projection onto the smooth cone surface.
  B. Apex return: trial stress maps to the hydrostatic apex of the cone.

The dividing criterion is whether the smooth return gives a tensile
hydrostatic stress above the apex.

HONEST FLAG: Simplified single-step implementation.  Production codes
require sub-stepping and the consistent tangent for global convergence.

References
----------
Drucker, D.C., Prager, W. (1952). "Soil mechanics and plastic analysis or
    limit design." Q Appl Math 10(2):157-165.
Lubliner, J. (1990). "Plasticity Theory." MacMillan. Ch. 4.
Borja, R.I. (2013). "Plasticity: Modeling & Computation." Springer. §3.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .return_mapping import (
    deviator,
    elastic_stiffness_6x6,
    first_invariant,
    second_invariant_deviator,
    voigt_inner,
)


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

@dataclass
class DruckerPragerMaterial:
    """
    Drucker-Prager elastoplastic material.

    Parameters
    ----------
    youngs_modulus_pa : float
        Young's modulus E [Pa].
    poisson : float
        Poisson ratio ν.
    cohesion_pa : float
        Cohesion c [Pa].  For frictionless materials (pure cohesion) set
        friction_angle_deg = 0.
    friction_angle_deg : float
        Internal friction angle φ [°].  Setting φ = 0 reduces DP to J2
        (von Mises) with k = c/√3.
    dilation_angle_deg : float
        Dilation angle ψ [°].  For associated flow set ψ = φ.
        Non-associated flow (ψ < φ) is the norm for soils.
    """
    youngs_modulus_pa: float
    poisson: float
    cohesion_pa: float
    friction_angle_deg: float
    dilation_angle_deg: float


# ---------------------------------------------------------------------------
# DP coefficients
# ---------------------------------------------------------------------------

def _dp_alpha_k(mat: DruckerPragerMaterial) -> tuple[float, float]:
    """
    Compute Drucker-Prager α and k for the outer Mohr-Coulomb circumscription.

        α = (2 sin φ) / (√3·(3 − sin φ))
        k = (6 c cos φ) / (√3·(3 − sin φ))

    When φ = 0:  α = 0,  k = c·2/√3  (reduces to von Mises with k = c√3/3…
    actually for φ=0: denominator = √3·3 = 3√3, numerator of k = 6c·1 = 6c
    → k = 6c/(3√3) = 2c/√3 = c√3·(2/3)…).

    We store k such that f = α·I₁ + √J₂ − k; for φ=0 this is √J₂ − k which
    is von Mises-like with σ_eq_VM = √(3J₂) matching when k = σ_y/√3.
    """
    phi_rad = math.radians(mat.friction_angle_deg)
    sin_phi = math.sin(phi_rad)
    cos_phi = math.cos(phi_rad)
    denom = math.sqrt(3.0) * (3.0 - sin_phi)
    alpha = 2.0 * sin_phi / denom if denom > 1e-30 else 0.0
    k = 6.0 * mat.cohesion_pa * cos_phi / denom if denom > 1e-30 else mat.cohesion_pa
    return alpha, k


def _dp_alpha_psi(mat: DruckerPragerMaterial) -> float:
    """Dilation coefficient α_ψ for the plastic potential g."""
    psi_rad = math.radians(mat.dilation_angle_deg)
    sin_psi = math.sin(psi_rad)
    denom = math.sqrt(3.0) * (3.0 - sin_psi)
    return 2.0 * sin_psi / denom if denom > 1e-30 else 0.0


# ---------------------------------------------------------------------------
# Yield function
# ---------------------------------------------------------------------------

def yield_function_dp(
    stress: np.ndarray,
    mat: DruckerPragerMaterial,
) -> float:
    """
    Drucker-Prager yield function.

        f = α·I₁ + √J₂ − k

    where α, k are computed from the friction angle and cohesion via outer
    Mohr-Coulomb circumscription.

    Parameters
    ----------
    stress : array-like, shape (6,)
        Stress in Voigt form [σ_xx, σ_yy, σ_zz, σ_xy, σ_yz, σ_xz] [Pa].
    mat : DruckerPragerMaterial

    Returns
    -------
    float
        f < 0 → elastic; f = 0 → on cone; f > 0 → infeasible.
    """
    stress = np.asarray(stress, dtype=float)
    alpha, k = _dp_alpha_k(mat)
    I1 = first_invariant(stress)
    J2 = second_invariant_deviator(stress)
    sqrt_J2 = math.sqrt(max(J2, 0.0))
    return alpha * I1 + sqrt_J2 - k


# ---------------------------------------------------------------------------
# Return-mapping
# ---------------------------------------------------------------------------

def return_map_dp(
    stress_trial: np.ndarray,
    mat: DruckerPragerMaterial,
) -> tuple[np.ndarray, dict]:
    """
    Closest-point return mapping for Drucker-Prager.

    Handles two return modes:
    - Smooth-cone return (general stress states)
    - Apex return (high triaxial compression beyond the cone tip)

    Algorithm (Borja 2013 §3.5; de Souza Neto et al. 2008 §8.4)
    --------------------------------------------------------------
    Let:  σ_tr = stress_trial (already the elastic predictor)
          I1_tr = tr(σ_tr)
          s_tr  = dev(σ_tr)
          sqrt_J2_tr = ||s_tr||_dev

    Smooth-cone return:
        σ_n+1 = σ_tr − Δγ·(2G·r̂ + 9K·α_ψ·m)
        where r̂ = ∂f/∂σ_dev = s_tr / (2√J2_tr)
              m  = (1/3)·I  (volumetric direction)
        Consistency: f(σ_n+1) = 0 → closed-form Δγ

    Apex return (when smooth return gives I1 > I1_apex):
        Project onto the hydrostatic axis:
        σ_n+1 = (k / (3α)) · I / 3   (isotropic stress at apex)

    Parameters
    ----------
    stress_trial : np.ndarray, shape (6,)
    mat : DruckerPragerMaterial

    Returns
    -------
    (stress_n1, info_dict)
        info_dict keys: 'mode' ('elastic'|'smooth'|'apex'),
                        'delta_gamma', 'yield_value_trial'
    """
    stress_trial = np.asarray(stress_trial, dtype=float)
    E = mat.youngs_modulus_pa
    nu = mat.poisson
    G = E / (2.0 * (1.0 + nu))          # shear modulus
    K = E / (3.0 * (1.0 - 2.0 * nu))   # bulk modulus

    alpha, k = _dp_alpha_k(mat)
    alpha_psi = _dp_alpha_psi(mat)

    I1_tr = first_invariant(stress_trial)
    s_tr = deviator(stress_trial)
    J2_tr = second_invariant_deviator(stress_trial)
    sqrt_J2_tr = math.sqrt(max(J2_tr, 0.0))

    f_tr = alpha * I1_tr + sqrt_J2_tr - k
    YIELD_TOL = 1e-10 * max(abs(k), 1.0)

    if f_tr <= YIELD_TOL:
        return stress_trial.copy(), {
            "mode": "elastic",
            "delta_gamma": 0.0,
            "yield_value_trial": f_tr,
        }

    # ── Smooth-cone return ───────────────────────────────────────────────────
    # Consistency condition (linear in Δγ for perfect plasticity):
    #   f(Δγ) = α·(I1_tr − 9K·α_ψ·Δγ) + (sqrt_J2_tr − G·Δγ) − k = 0
    #   Δγ = (α·I1_tr + sqrt_J2_tr − k) / (9K·α·α_ψ + G)
    denom_smooth = G + 9.0 * K * alpha * alpha_psi
    if denom_smooth < 1e-30:
        denom_smooth = 1e-30

    delta_gamma_smooth = f_tr / denom_smooth

    # Updated invariants after smooth return
    I1_new_smooth = I1_tr - 9.0 * K * alpha_psi * delta_gamma_smooth
    sqrt_J2_new = max(sqrt_J2_tr - G * delta_gamma_smooth, 0.0)

    # Check if we've gone past the apex (I1 > k/α for α > 0)
    at_apex = False
    if alpha > 1e-12:
        I1_apex = k / alpha
        if I1_new_smooth > I1_apex or sqrt_J2_tr < 1e-30 * abs(k):
            at_apex = True

    if at_apex:
        # ── Apex return ──────────────────────────────────────────────────────
        # Project onto the hydrostatic apex point:  σ = p_apex · I
        # f(p·I) = α·3p − k = 0  → p_apex = k / (3α)
        p_apex = k / (3.0 * alpha)
        stress_n1 = np.zeros(6)
        stress_n1[0] = p_apex
        stress_n1[1] = p_apex
        stress_n1[2] = p_apex
        return stress_n1, {
            "mode": "apex",
            "delta_gamma": delta_gamma_smooth,
            "yield_value_trial": f_tr,
        }

    # ── Apply smooth-cone correction ─────────────────────────────────────────
    # Flow direction (normalised deviator)
    if sqrt_J2_tr > 1e-30:
        r_hat = s_tr / (2.0 * sqrt_J2_tr)  # ∂f/∂σ_dev = s/(2√J₂)
    else:
        r_hat = np.zeros(6)

    # Volumetric part correction
    p_tr = I1_tr / 3.0
    p_new = p_tr - K * 9.0 * alpha_psi / 3.0 * delta_gamma_smooth

    # Deviatoric part: s_new = s_tr · (sqrt_J2_new / sqrt_J2_tr)
    if sqrt_J2_tr > 1e-30:
        s_new = s_tr * (sqrt_J2_new / sqrt_J2_tr)
    else:
        s_new = np.zeros(6)

    stress_n1 = s_new.copy()
    stress_n1[0] += p_new
    stress_n1[1] += p_new
    stress_n1[2] += p_new

    return stress_n1, {
        "mode": "smooth",
        "delta_gamma": delta_gamma_smooth,
        "yield_value_trial": f_tr,
    }
