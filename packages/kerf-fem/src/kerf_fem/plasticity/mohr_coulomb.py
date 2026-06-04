"""
Mohr-Coulomb plasticity model (soil mechanics, rock, masonry).

Theory
------
The Mohr-Coulomb yield criterion states that failure occurs when the shear
stress on a plane satisfies:

    τ + σ_n · tan φ = c

which in principal-stress space (σ₁ ≥ σ₂ ≥ σ₃) becomes six yield surfaces:

    f_αβ = σ_α − σ_β · (1 + sin φ)/(1 − sin φ) − 2c·cos φ/(1 − sin φ) ≤ 0
        for (α,β) ∈ {(1,3), (1,2), (2,3), (3,1), (2,1), (3,2)}

Or equivalently (positive in tension convention, σ₁ ≥ σ₂ ≥ σ₃):

    f = (σ_max − σ_min)/2 + (σ_max + σ_min)/2 · sin φ − c · cos φ

Return-mapping strategy (Sloan & Booker 1986; de Souza Neto et al. 2008)
-------------------------------------------------------------------------
1. Compute principal stresses and identify active yield surface(s).
2. Return type:
   a. Single-plane return: project onto one active surface.
   b. Two-surface return (edge): Newton step to find the corner.
   c. Apex return: project onto the hydrostatic apex.
3. Rotate stress back to original frame.

Implementation notes
--------------------
This implementation works entirely in principal-stress space, which avoids
the singularity at the corners of the hexagonal pyramid.  The returned stress
is transformed back to Voigt form using the eigenvectors.

HONEST FLAG: Simplified implementation — single-step, no sub-stepping,
no consistent tangent.  Suitable for moderate accuracy; production requires
the spectral decomposition consistent tangent (Borja 1991).

References
----------
Sloan, S.W., Booker, J.R. (1986). "Removal of singularities in Tresca and
    Mohr-Coulomb yield functions." Commun Appl Numer Methods 2(2):173-179.
de Souza Neto, E.A., Perić, D., Owen, D.R.J. (2008). "Computational Methods
    for Plasticity." Wiley. §8.6.
Borja, R.I. (2013). "Plasticity: Modeling & Computation." Springer. §3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .return_mapping import elastic_stiffness_6x6, voigt_to_tensor, tensor_to_voigt


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

@dataclass
class MohrCoulombMaterial:
    """
    Mohr-Coulomb elastoplastic material (perfect plasticity).

    Parameters
    ----------
    youngs_modulus_pa : float
        Young's modulus E [Pa].
    poisson : float
        Poisson ratio ν.
    cohesion_pa : float
        Cohesion c [Pa].  Setting c = 0 gives a frictional (cohesionless)
        material (e.g. dry sand).
    friction_angle_deg : float
        Internal friction angle φ [°].
    dilation_angle_deg : float
        Dilation angle ψ [°].  Associated flow: ψ = φ.
    """
    youngs_modulus_pa: float
    poisson: float
    cohesion_pa: float
    friction_angle_deg: float
    dilation_angle_deg: float


# ---------------------------------------------------------------------------
# Yield function in principal-stress space
# ---------------------------------------------------------------------------

def _mc_params(mat: MohrCoulombMaterial) -> tuple[float, float, float, float]:
    """
    Compute Mohr-Coulomb auxiliary parameters.

    Returns (N_phi, N_psi, c_cos_phi, cohesion_term)
        N_phi = (1 + sin φ) / (1 − sin φ)
        N_psi = (1 + sin ψ) / (1 − sin ψ)  [for plastic potential]
        tan_phi = tan φ
        c_cos_phi_over_sin_phi — not used directly here
    """
    phi = math.radians(mat.friction_angle_deg)
    psi = math.radians(mat.dilation_angle_deg)
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)
    sin_psi = math.sin(psi)

    denom_phi = 1.0 - sin_phi
    N_phi = (1.0 + sin_phi) / denom_phi if abs(denom_phi) > 1e-14 else 1e10

    denom_psi = 1.0 - sin_psi
    N_psi = (1.0 + sin_psi) / denom_psi if abs(denom_psi) > 1e-14 else 1e10

    # Cohesion intersection: when σ₁ − N_φ·σ₃ = 2c·√N_φ
    two_c_sqrt_N = 2.0 * mat.cohesion_pa * math.sqrt(N_phi) if N_phi >= 0 else 0.0

    return N_phi, N_psi, two_c_sqrt_N, cos_phi, sin_phi


def yield_function_mc(
    stress: np.ndarray,
    mat: MohrCoulombMaterial,
) -> float:
    """
    Mohr-Coulomb yield function using the active principal-stress pair.

    Ordering convention: σ₁ ≥ σ₂ ≥ σ₃ (principal stresses, tension positive).

    Active yield surface (largest pair):
        f = σ₁ − N_φ · σ₃ − 2c·√N_φ

    where  N_φ = (1 + sin φ)/(1 − sin φ).

    This is the Mohr-Coulomb criterion for the maximum shear plane (σ₁, σ₃).

    Returns
    -------
    float
        f < 0 → elastic; f ≥ 0 → plastic.
    """
    stress = np.asarray(stress, dtype=float)
    N_phi, _, two_c_sqrt_N, _, _ = _mc_params(mat)
    T = voigt_to_tensor(stress)
    eigvals = np.sort(np.linalg.eigvalsh(T))[::-1]  # σ₁ ≥ σ₂ ≥ σ₃
    sigma1 = eigvals[0]
    sigma3 = eigvals[2]
    return sigma1 - N_phi * sigma3 - two_c_sqrt_N


# ---------------------------------------------------------------------------
# Return-mapping (principal-stress space)
# ---------------------------------------------------------------------------

def return_map_mc(
    stress_trial: np.ndarray,
    mat: MohrCoulombMaterial,
) -> tuple[np.ndarray, dict]:
    """
    Multi-surface return mapping for Mohr-Coulomb in principal-stress space.

    Algorithm (Sloan & Booker 1986; de Souza Neto et al. 2008 §8.6)
    -----------------------------------------------------------------
    1. Compute principal stresses of σ_tr.
    2. Identify which of the six Mohr-Coulomb surfaces is active.
    3. Perform the appropriate return:
       a. Single-surface return (smooth plane).
       b. Two-surface (edge) return.
       c. Apex return.
    4. Reconstruct the full stress tensor.

    Parameters
    ----------
    stress_trial : np.ndarray, shape (6,)
    mat : MohrCoulombMaterial

    Returns
    -------
    (stress_n1, info_dict)
        info_dict: 'mode' ('elastic'|'single'|'edge'|'apex'),
                   'yield_value_trial', principal_stresses_trial.
    """
    stress_trial = np.asarray(stress_trial, dtype=float)

    E = mat.youngs_modulus_pa
    nu = mat.poisson
    G = E / (2.0 * (1.0 + nu))
    K = E / (3.0 * (1.0 - 2.0 * nu))

    N_phi, N_psi, two_c_sqrt_N, cos_phi, sin_phi = _mc_params(mat)

    # Spectral decomposition of trial stress
    T_tr = voigt_to_tensor(stress_trial)
    eigvals, eigvecs = np.linalg.eigh(T_tr)  # ascending order
    # Rearrange to descending (σ₁ ≥ σ₂ ≥ σ₃)
    idx = np.argsort(eigvals)[::-1]
    sigma_tr = eigvals[idx]       # [σ₁, σ₂, σ₃]
    eigvecs = eigvecs[:, idx]     # columns are principal directions

    s1, s2, s3 = sigma_tr[0], sigma_tr[1], sigma_tr[2]

    # Active yield function (using pair σ₁, σ₃ — maximum shear)
    f_tr = s1 - N_phi * s3 - two_c_sqrt_N

    YIELD_TOL = 1e-10 * max(abs(two_c_sqrt_N), abs(mat.youngs_modulus_pa) * 1e-6, 1.0)

    if f_tr <= YIELD_TOL:
        return stress_trial.copy(), {
            "mode": "elastic",
            "yield_value_trial": f_tr,
            "principal_stresses_trial": sigma_tr.tolist(),
        }

    # ── Determine return mode ────────────────────────────────────────────────
    # Elastic stiffness in principal space (isotropic → same matrix):
    # A = [[K+4G/3, K-2G/3, K-2G/3],
    #       [K-2G/3, K+4G/3, K-2G/3],
    #       [K-2G/3, K-2G/3, K+4G/3]]
    a11 = K + 4.0 * G / 3.0
    a12 = K - 2.0 * G / 3.0

    # Flow direction in principal-stress space for non-associated flow:
    # ∂g/∂σ = [1, 0, -N_psi]  (for surface 1-3, i.e. σ₁ active max, σ₃ active min)
    m1 = np.array([1.0, 0.0, -N_psi])  # ∂g/∂[σ₁,σ₂,σ₃]
    # Yield gradient:  ∂f/∂σ = [1, 0, -N_phi]
    nf = np.array([1.0, 0.0, -N_phi])

    # A · m1
    A = np.array([
        [a11, a12, a12],
        [a12, a11, a12],
        [a12, a12, a11],
    ])
    Am = A @ m1          # elastic stiffness times flow direction
    h = nf @ Am          # = ∂f/∂σ : C : ∂g/∂σ  (denominator)

    if abs(h) < 1e-30:
        h = 1e-30

    delta_gamma = f_tr / h

    # Trial corrected principal stresses (smooth plane)
    sigma_corrected = sigma_tr - delta_gamma * Am

    # Check if we need a two-surface (edge) or apex return
    # Edge return condition: one of the secondary yield functions is also
    # violated after the single-surface correction.
    f12 = sigma_corrected[0] - N_phi * sigma_corrected[1] - two_c_sqrt_N
    f23 = sigma_corrected[1] - N_phi * sigma_corrected[2] - two_c_sqrt_N

    mode = "single"
    if f12 > YIELD_TOL:
        # Two-surface edge: surfaces (1,3) and (1,2) both active
        # Solve 2×2 system for (Δγ₁, Δγ₂)
        m2 = np.array([1.0, -N_psi, 0.0])   # flow direction for surface (1,2)
        nf2 = np.array([1.0, -N_phi, 0.0])  # yield gradient for surface (1,2)

        Am1 = A @ m1
        Am2 = A @ m2
        h11 = nf @ Am1
        h12 = nf @ Am2
        h21 = nf2 @ Am1
        h22 = nf2 @ Am2

        det = h11 * h22 - h12 * h21
        if abs(det) < 1e-30:
            det = 1e-30
        f1 = f_tr
        f2 = sigma_tr[0] - N_phi * sigma_tr[1] - two_c_sqrt_N

        dg1 = (f1 * h22 - f2 * h12) / det
        dg2 = (f2 * h11 - f1 * h21) / det
        sigma_corrected = sigma_tr - dg1 * Am1 - dg2 * Am2
        mode = "edge"

    elif f23 > YIELD_TOL:
        # Two-surface edge: surfaces (1,3) and (2,3) both active
        m2 = np.array([0.0, 1.0, -N_psi])   # flow for surface (2,3)
        nf2 = np.array([0.0, 1.0, -N_phi])

        Am1 = A @ m1
        Am2 = A @ m2
        h11 = nf @ Am1
        h12 = nf @ Am2
        h21 = nf2 @ Am1
        h22 = nf2 @ Am2

        det = h11 * h22 - h12 * h21
        if abs(det) < 1e-30:
            det = 1e-30
        f1 = f_tr
        f2 = sigma_tr[1] - N_phi * sigma_tr[2] - two_c_sqrt_N

        dg1 = (f1 * h22 - f2 * h12) / det
        dg2 = (f2 * h11 - f1 * h21) / det
        sigma_corrected = sigma_tr - dg1 * Am1 - dg2 * Am2
        mode = "edge"

    # Apex check: all three principal stresses converge to hydrostatic apex
    # Apex: σ₁ = σ₂ = σ₃ = p_apex where f(p,p,p) = p(1-N_phi) - two_c_sqrt_N = 0
    denom_apex = 1.0 - N_phi
    if abs(denom_apex) > 1e-14:
        p_apex = two_c_sqrt_N / denom_apex
        # If corrected σ₃ > p_apex we have a true apex return
        if sigma_corrected[2] > p_apex - YIELD_TOL:
            sigma_corrected = np.array([p_apex, p_apex, p_apex])
            mode = "apex"
    # For N_phi very large (φ→90°) the apex is at +∞; just use corrected.

    # Reconstruct full stress tensor from corrected principal stresses
    T_new = eigvecs @ np.diag(sigma_corrected) @ eigvecs.T
    stress_n1 = tensor_to_voigt(T_new)

    return stress_n1, {
        "mode": mode,
        "yield_value_trial": f_tr,
        "principal_stresses_trial": sigma_tr.tolist(),
        "principal_stresses_corrected": sigma_corrected.tolist(),
    }
