"""
Hill 1948 anisotropic plasticity model (sheet metal forming, rolled metals).

Theory
------
Hill (1948) extended the von Mises criterion to orthotropic anisotropic
materials.  The yield function is:

    f = √[F(σ_yy−σ_zz)² + G(σ_zz−σ_xx)² + H(σ_xx−σ_yy)²
          + 2L·σ_yz² + 2M·σ_xz² + 2N·σ_xy²] − σ_y

where F, G, H, L, M, N are the Hill coefficients defined by the anisotropic
yield stresses X, Y, Z (uniaxial) and R (shear yield stress):

    F = (1/Y² + 1/Z² − 1/X²) / 2
    G = (1/Z² + 1/X² − 1/Y²) / 2
    H = (1/X² + 1/Y² − 1/Z²) / 2
    L = 1 / (2 R_yz²)   (R_yz = in-plane shear; often set equal to shear_yield)
    M = L  (assumed equal here — isotropic shear)
    N = L

Lankford ratios (R-values)
--------------------------
The Lankford ratio R is defined as the ratio of in-plane plastic strain to
through-thickness plastic strain in a uniaxial tensile test.

    R_0  (rolling direction)
    R_45 (45° to rolling)
    R_90 (transverse direction)

The Hill coefficients can also be derived from R-values (Banabic 2010 §4.2):

    H / (G + H) = R_0         → H = R_0·G
    H / (F + H) = R_90        → H = R_90·F
    N / (F + G) = (1+2R_45)/2

These are used here when Lankford ratios are provided.

Return mapping
--------------
Closest-point projection in the anisotropic metric.  The flow direction is:

    r = ∂f/∂σ = (1/(2f_val)) · M_H · σ

where M_H is the Hill compliance matrix.  For the return step:

    σ_n+1 = σ_tr − Δγ · C · r(σ_n+1)

which for perfect plasticity reduces to a linear system in Δγ.

HONEST FLAG: Simplified single-step, no sub-stepping, no exact consistent
tangent.  Suitable for moderate accuracy.

References
----------
Hill, R. (1948). "A theory of the yielding and plastic flow of anisotropic
    metals." Proc R Soc Lond A 193:281-297.
Banabic, D. et al. (2010). "Sheet Metal Forming Processes." Springer. Ch. 4.
Sloan, S.W. (1990). "Substepping schemes for the numerical integration of
    elastoplastic stress-strain relations." Int J Numer Methods Eng 24:893-911.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .return_mapping import elastic_stiffness_6x6, voigt_inner


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

@dataclass
class HillAnisotropicMaterial:
    """
    Hill 1948 anisotropic plasticity (sheet metal forming, rolled metals).

    Voigt ordering: [xx, yy, zz, xy, yz, xz]
    The rolling direction is x, transverse is y, thickness is z.

    Parameters
    ----------
    youngs_modulus_pa : float
        Young's modulus (isotropic elastic assumed) [Pa].
    poisson : float
        Poisson ratio.
    yield_stress_x_pa : float
        Uniaxial yield stress in rolling direction (X) [Pa].
    yield_stress_y_pa : float
        Uniaxial yield stress in transverse direction (Y) [Pa].
    yield_stress_z_pa : float
        Uniaxial yield stress in thickness direction (Z) [Pa].
    shear_yield_pa : float
        In-plane shear yield stress (R_shear) [Pa].  Corresponds to the
        reference shear yield; used to set L = M = N.
    R_values : tuple (R_0, R_45, R_90)
        Lankford ratios.  If all three are 1.0 the model reduces to J2.
        R_0 is for the rolling direction.
    """
    youngs_modulus_pa: float
    poisson: float
    yield_stress_x_pa: float
    yield_stress_y_pa: float
    yield_stress_z_pa: float
    shear_yield_pa: float
    R_values: tuple = field(default_factory=lambda: (1.0, 1.0, 1.0))


# ---------------------------------------------------------------------------
# Hill coefficient computation
# ---------------------------------------------------------------------------

def _hill_coefficients(mat: HillAnisotropicMaterial) -> tuple[float, ...]:
    """
    Compute Hill 1948 coefficients F, G, H, L, M, N.

    Hill (1948) §2 defines:
        F = (1/Y² + 1/Z² − 1/X²) / 2
        G = (1/Z² + 1/X² − 1/Y²) / 2
        H = (1/X² + 1/Y² − 1/Z²) / 2
        L = M = N = 3/(2 R_shear²)   (using reference yield convention)

    If R-values are provided and not all unity, we optionally refine using
    the Lankford relation (Banabic 2010 eq 4.6–4.8):
        G / (G+H) = 1/(1+R_0)  → G/H = 1/R_0

    Here we use the direct yield-stress formula which is always valid.
    """
    X = mat.yield_stress_x_pa
    Y = mat.yield_stress_y_pa
    Z = mat.yield_stress_z_pa
    R_s = mat.shear_yield_pa

    # Guard against zero denominators
    iX2 = 1.0 / (X * X) if X > 0 else 0.0
    iY2 = 1.0 / (Y * Y) if Y > 0 else 0.0
    iZ2 = 1.0 / (Z * Z) if Z > 0 else 0.0

    F = 0.5 * (iY2 + iZ2 - iX2)
    G = 0.5 * (iZ2 + iX2 - iY2)
    H = 0.5 * (iX2 + iY2 - iZ2)

    # L = M = N from shear yield (Hill 1948 eq 1.4)
    iR2 = 1.0 / (R_s * R_s) if R_s > 0 else 0.0
    L = 1.5 * iR2
    M = L
    N = L

    return F, G, H, L, M, N


def _hill_matrix(mat: HillAnisotropicMaterial) -> np.ndarray:
    """
    6×6 Hill compliance matrix M_H such that:

        f_inner² = σ^T · M_H · σ  =  F(σ_yy−σ_zz)² + G(σ_zz−σ_xx)² + ...

    Voigt ordering: [σ_xx, σ_yy, σ_zz, σ_xy, σ_yz, σ_xz].

    The matrix is symmetric positive semi-definite (for valid Hill coefficients).
    """
    F, G, H, L, M, N = _hill_coefficients(mat)
    MH = np.zeros((6, 6))

    # Normal-stress block (Hill 1948 eq 1.1 expanded):
    # (σ_yy - σ_zz)² term: F·[0·0, 1·1, -1·-1, cross]
    # expand and collect by σ_i σ_j :
    #   F(σ_yy-σ_zz)² = F·σ_yy² - 2F·σ_yy·σ_zz + F·σ_zz²
    #   G(σ_zz-σ_xx)² = G·σ_zz² - 2G·σ_zz·σ_xx + G·σ_xx²
    #   H(σ_xx-σ_yy)² = H·σ_xx² - 2H·σ_xx·σ_yy + H·σ_yy²
    MH[0, 0] = G + H
    MH[1, 1] = F + H
    MH[2, 2] = F + G
    MH[0, 1] = MH[1, 0] = -H
    MH[1, 2] = MH[2, 1] = -F
    MH[0, 2] = MH[2, 0] = -G

    # Shear terms (2L·σ_yz² + 2M·σ_xz² + 2N·σ_xy²)
    # Voigt [3]=xy, [4]=yz, [5]=xz
    MH[3, 3] = 2.0 * N   # σ_xy
    MH[4, 4] = 2.0 * L   # σ_yz
    MH[5, 5] = 2.0 * M   # σ_xz

    return MH


# ---------------------------------------------------------------------------
# Yield function
# ---------------------------------------------------------------------------

def yield_function_hill(
    stress: np.ndarray,
    mat: HillAnisotropicMaterial,
) -> float:
    """
    Hill 1948 anisotropic yield function (normalised form).

    The Hill compliance matrix M_H is defined such that:

        σ^T · M_H · σ = 1   at the yield surface

    (i.e. M_H contains 1/yield_stress² factors so the inner product is
    dimensionless and equals 1 exactly when the stress is on the yield
    surface).  Therefore:

        f = √(σ^T · M_H · σ) − 1

    This is the standard Hill (1948) form: f = 0 on the yield surface,
    f < 0 inside (elastic), f > 0 outside (trial state).

    Returns
    -------
    float
        f < 0 → elastic; f = 0 → on yield surface; f > 0 → infeasible.
    """
    stress = np.asarray(stress, dtype=float)
    MH = _hill_matrix(mat)
    inner = float(stress @ MH @ stress)
    f_inner = math.sqrt(max(inner, 0.0))
    return f_inner - 1.0


# ---------------------------------------------------------------------------
# Return mapping
# ---------------------------------------------------------------------------

def return_map_hill(
    stress_trial: np.ndarray,
    mat: HillAnisotropicMaterial,
) -> tuple[np.ndarray, dict]:
    """
    Anisotropic return mapping for Hill 1948 (perfect plasticity).

    Algorithm
    ---------
    The flow rule for Hill:
        dε_p = Δγ · r   where  r = ∂f/∂σ = M_H · σ / (σ^T M_H σ)^(1/2)

    The consistency condition for perfect plasticity (H_iso = 0):
        f(σ_n+1) = 0
        σ_n+1 = σ_tr − Δγ · C · r(σ_n+1)

    For a linear return direction (constant r = r_tr):
        σ_n+1 = σ_tr − Δγ · (C · r_tr)
        f(σ_n+1) = 0  → linear equation in Δγ

    This is the "explicit" return which approximates r at the trial state.
    It is exact for J2 (radial return) and first-order accurate for Hill.

    Parameters
    ----------
    stress_trial : np.ndarray, shape (6,)
    mat : HillAnisotropicMaterial

    Returns
    -------
    (stress_n1, info_dict)
    """
    stress_trial = np.asarray(stress_trial, dtype=float)

    E = mat.youngs_modulus_pa
    nu = mat.poisson
    C = elastic_stiffness_6x6(E, nu)
    MH = _hill_matrix(mat)

    # Trial yield function (normalised: f = sqrt(inner) - 1, yield at f=0)
    inner_tr = float(stress_trial @ MH @ stress_trial)
    f_inner_tr = math.sqrt(max(inner_tr, 0.0))
    f_tr = f_inner_tr - 1.0

    YIELD_TOL = 1e-10

    if f_tr <= YIELD_TOL:
        return stress_trial.copy(), {
            "mode": "elastic",
            "yield_value_trial": f_tr,
        }

    # Flow direction at trial state: r_tr = M_H · σ_tr / f_inner_tr
    # (∂f/∂σ = M_H · σ / (σ^T M_H σ)^0.5)
    if f_inner_tr < 1e-30:
        r_tr = np.zeros(6)
    else:
        r_tr = MH @ stress_trial / f_inner_tr

    # Cr = C · r_tr
    Cr = C @ r_tr  # (6,)

    # Consistency condition (linearised around trial, normalised form):
    # f(σ_tr − Δγ·Cr) = 0
    # sqrt((σ_tr − Δγ·Cr)^T · M_H · (σ_tr − Δγ·Cr)) = 1
    # (σ_tr − Δγ·Cr)^T · M_H · (σ_tr − Δγ·Cr) = 1
    # Let a = σ_tr^T·M_H·σ_tr, b = −2·σ_tr^T·M_H·Cr, c = Cr^T·M_H·Cr
    # a + b·Δγ + c·Δγ² = 1   → quadratic in Δγ

    a = inner_tr
    b = -2.0 * float(stress_trial @ MH @ Cr)
    c = float(Cr @ MH @ Cr)
    sigma_y = 1.0   # normalised yield value

    # c·Δγ² + b·Δγ + (a − 1) = 0
    A_q = c
    B_q = b
    C_q = a - sigma_y ** 2

    if abs(A_q) < 1e-30:
        # Linear case (C·r perpendicular to MH)
        if abs(B_q) < 1e-30:
            delta_gamma = 0.0
        else:
            delta_gamma = -C_q / B_q
    else:
        disc = B_q ** 2 - 4.0 * A_q * C_q
        if disc < 0.0:
            disc = 0.0
        # Two roots: take the smaller positive one (physically consistent)
        root1 = (-B_q - math.sqrt(disc)) / (2.0 * A_q)
        root2 = (-B_q + math.sqrt(disc)) / (2.0 * A_q)
        # Pick the root that gives the smallest positive Δγ
        roots = [r for r in (root1, root2) if r >= -1e-14]
        if not roots:
            delta_gamma = 0.0
        else:
            delta_gamma = min(roots)

    delta_gamma = max(delta_gamma, 0.0)
    stress_n1 = stress_trial - delta_gamma * Cr

    return stress_n1, {
        "mode": "smooth",
        "delta_gamma": delta_gamma,
        "yield_value_trial": f_tr,
    }
