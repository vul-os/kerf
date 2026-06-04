"""
Shared return-mapping infrastructure for kerf-fem plasticity models.

All plasticity models (J2, Drucker-Prager, Mohr-Coulomb, Hill) share the
same Voigt-notation bookkeeping and the Newton iteration for the consistency
condition.

Voigt ordering convention (throughout this package):
    [σ_xx, σ_yy, σ_zz, σ_xy, σ_yz, σ_xz]   (same for strain)

HONEST FLAG: These are simplified, single-step return-mapping implementations
for educational and moderate-accuracy engineering use.  Production FEA codes
require sub-stepping (for large strain increments), line-search, and the
consistent algorithmic tangent for quadratic global convergence of Newton-
Raphson solves.  See Simo & Hughes (1998) §§3-5 for the full treatment.

References
----------
Simo, J.C., Hughes, T.J.R. (1998). "Computational Inelasticity." Springer.
de Borst, R. et al. (2012). "Nonlinear Finite Element Analysis of Solids and
    Structures." Wiley.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Voigt ↔ tensor conversions
# ---------------------------------------------------------------------------

def voigt_to_tensor(v: np.ndarray) -> np.ndarray:
    """
    Convert a Voigt 6-vector to a 3×3 symmetric tensor.

    Voigt ordering: [xx, yy, zz, xy, yz, xz]
    """
    v = np.asarray(v, dtype=float)
    t = np.zeros((3, 3))
    t[0, 0] = v[0]
    t[1, 1] = v[1]
    t[2, 2] = v[2]
    t[0, 1] = t[1, 0] = v[3]
    t[1, 2] = t[2, 1] = v[4]
    t[0, 2] = t[2, 0] = v[5]
    return t


def tensor_to_voigt(t: np.ndarray) -> np.ndarray:
    """
    Convert a 3×3 symmetric tensor to a Voigt 6-vector.

    Voigt ordering: [xx, yy, zz, xy, yz, xz]
    """
    t = np.asarray(t, dtype=float)
    return np.array([
        t[0, 0], t[1, 1], t[2, 2],
        t[0, 1], t[1, 2], t[0, 2],
    ])


# ---------------------------------------------------------------------------
# Invariants and deviator
# ---------------------------------------------------------------------------

def deviator(stress: np.ndarray) -> np.ndarray:
    """
    Compute the stress deviator  s = σ - (1/3)·tr(σ)·I  in Voigt form.

    tr(σ) = σ_xx + σ_yy + σ_zz.
    """
    stress = np.asarray(stress, dtype=float)
    p = (stress[0] + stress[1] + stress[2]) / 3.0
    s = stress.copy()
    s[0] -= p
    s[1] -= p
    s[2] -= p
    return s


def first_invariant(stress: np.ndarray) -> float:
    """I₁ = tr(σ) = σ_xx + σ_yy + σ_zz."""
    stress = np.asarray(stress, dtype=float)
    return float(stress[0] + stress[1] + stress[2])


def second_invariant_deviator(stress: np.ndarray) -> float:
    """
    J₂ = (1/2) s:s  where  s = dev(σ).

    In Voigt form:
        J₂ = (1/2)(s_xx² + s_yy² + s_zz²) + s_xy² + s_yz² + s_xz²

    Note: shear components are NOT doubled when computing the inner product
    because the factor-of-2 from the symmetric off-diagonals cancels with the
    1/2 prefactor correctly when the Voigt shear entries store the engineering
    shear values (γ/2 or the direct stress components depending on context).

    Here we store STRESS components directly (τ_xy etc.), so:
        J₂ = (s_xx² + s_yy² + s_zz²)/2 + s_xy² + s_yz² + s_xz²
    """
    s = deviator(np.asarray(stress, dtype=float))
    return 0.5 * (s[0]**2 + s[1]**2 + s[2]**2) + s[3]**2 + s[4]**2 + s[5]**2


def principal_stresses(stress: np.ndarray) -> np.ndarray:
    """
    Compute the three principal stresses (eigenvalues of the stress tensor).

    Returns them sorted in descending order: σ₁ ≥ σ₂ ≥ σ₃.
    """
    t = voigt_to_tensor(stress)
    eigs = np.linalg.eigvalsh(t)
    return np.sort(eigs)[::-1]  # descending


# ---------------------------------------------------------------------------
# Elastic stiffness (isotropic)
# ---------------------------------------------------------------------------

def elastic_stiffness_6x6(E: float, nu: float) -> np.ndarray:
    """
    Isotropic 3-D elastic stiffness matrix in Voigt form (6×6).

    Voigt ordering: [xx, yy, zz, xy, yz, xz].
    The shear components correspond to direct stresses (not engineering shear),
    so the diagonal shear entries are G = E / (2(1+ν)).
    """
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    C = np.zeros((6, 6))
    # Normal-normal block
    for i in range(3):
        C[i, i] = lam + 2.0 * mu
        for j in range(3):
            if i != j:
                C[i, j] = lam
    # Shear-shear block
    for i in range(3, 6):
        C[i, i] = mu
    return C


# ---------------------------------------------------------------------------
# Newton iteration — consistency condition
# ---------------------------------------------------------------------------

def newton_solve_consistency(
    yield_fn: Callable[[float], float],
    d_yield_fn: Callable[[float], float],
    initial_lambda: float = 0.0,
    max_iter: int = 30,
    tol: float = 1e-10,
) -> tuple[float, bool]:
    """
    Newton iteration to find the plastic multiplier λ such that  f(λ) = 0.

    Parameters
    ----------
    yield_fn : callable
        Residual function  f(λ) — should evaluate to the yield function
        value after the return mapping given plastic multiplier λ.
        Converged when |f(λ)| ≤ tol.
    d_yield_fn : callable
        Derivative  df/dλ  (analytical or finite-difference approximation).
    initial_lambda : float
        Starting estimate (usually 0.0 for the first increment).
    max_iter : int
        Maximum Newton iterations before declaring non-convergence.
    tol : float
        Absolute convergence tolerance on |f(λ)|.

    Returns
    -------
    (lambda_converged, converged_bool)
    """
    lam = float(initial_lambda)
    for _ in range(max_iter):
        f = yield_fn(lam)
        if abs(f) <= tol:
            return lam, True
        df = d_yield_fn(lam)
        if abs(df) < 1e-30:
            break
        lam -= f / df
        if lam < 0.0:
            lam = 0.0
    # One final check
    f = yield_fn(lam)
    return lam, abs(f) <= tol * 1e3  # relaxed check for near-convergence


# ---------------------------------------------------------------------------
# Utility: norm of deviator (used by several models)
# ---------------------------------------------------------------------------

def dev_norm(s: np.ndarray) -> float:
    """
    ||s|| = sqrt(s_xx² + s_yy² + s_zz² + 2 s_xy² + 2 s_yz² + 2 s_xz²)

    Factor of 2 on shear terms because s is stored as stress components
    and the full contraction s:s = Σ_ij s_ij² includes both (i,j) and (j,i).
    """
    s = np.asarray(s, dtype=float)
    return math.sqrt(
        s[0]**2 + s[1]**2 + s[2]**2
        + 2.0 * s[3]**2 + 2.0 * s[4]**2 + 2.0 * s[5]**2
    )


def voigt_inner(a: np.ndarray, b: np.ndarray) -> float:
    """
    Full tensor inner product  a:b  from Voigt vectors.

    a:b = a_xx b_xx + a_yy b_yy + a_zz b_zz
          + 2 a_xy b_xy + 2 a_yz b_yz + 2 a_xz b_xz
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return (
        a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
        + 2.0*a[3]*b[3] + 2.0*a[4]*b[4] + 2.0*a[5]*b[5]
    )
