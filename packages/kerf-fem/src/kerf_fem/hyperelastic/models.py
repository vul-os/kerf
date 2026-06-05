"""
Hyperelastic constitutive models — strain-energy density functions and
their first / second derivatives for finite-deformation solid mechanics.

Models implemented
------------------
1.  **Neo-Hookean** (Treloar 1943 / Rivlin 1948)
        W = (mu/2)(I1 - 3) - mu*ln(J) + (lam/2)(ln J)²
    Single material parameter: shear modulus μ and bulk modulus K.
    Simplest model; accurate for ≲ 100 % strain.

2.  **Mooney-Rivlin** (Mooney 1940 / Rivlin 1948)
        W = C10 (I1-3) + C01 (I2-3) + (1/d)(J-1)²
    Two deviatoric parameters C10, C01 plus bulk penalty 1/d.
    Standard for vulcanised rubbers; valid to ≲ 300 % engineering strain.

3.  **Ogden** (Ogden 1972, N = 1..3)
        W = Σ_p (μ_p/α_p)(λ1^α_p + λ2^α_p + λ3^α_p - 3) + κ(J-1-ln J)
    where λ_i are principal stretches.
    N=1: neo-Hookean at α=2; N=2 or N=3: excellent rubber accuracy to 700 %.

Kinematic framework (Holzapfel 2000 §6.2)
-----------------------------------------
  F = deformation gradient (3×3)
  J = det(F)             volume ratio
  C = Fᵀ F              right Cauchy-Green tensor
  B = F Fᵀ              left Cauchy-Green tensor
  I1 = tr(C)            first invariant
  I2 = (1/2)(I1² - tr(C²))  second invariant

Stress output
-------------
All stress functions return the Cauchy stress σ (true stress, 3×3 symmetric).
The 2nd Piola-Kirchhoff stress S is related by S = J F⁻¹ σ F⁻ᵀ.
For the uniaxial / biaxial / planar helpers we use the incompressibility
assumption J = 1 (rubber) and return engineering nominal stress P = σ / λ.

Tangent modulus
---------------
The Lagrangian (material) tangent C_mat = 2 ∂S/∂C is returned as a (6,6)
Voigt matrix for use in FEM element stiffness assembly.  The push-forward
(spatial) tangent c_spat is obtained externally via c_spat_ijkl = F_iI F_jJ c_mat_IJKL F_kK F_lL / J.

References
----------
  Holzapfel (2000) "Nonlinear Solid Mechanics" Wiley — Ch. 6 (hyperelasticity).
  Ogden (1972) Proc. R. Soc. London A 326, 565-584 — principal-stretch model.
  Mooney (1940) J. Appl. Phys. 11, 582-592.
  Rivlin (1948) Philos. Trans. R. Soc. A 241, 379-397.
  Treloar (1943) Trans. Faraday Soc. 39, 241-246.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Model descriptor
# ---------------------------------------------------------------------------

@dataclass
class HyperelasticModel:
    """Descriptor for a hyperelastic material.

    Parameters
    ----------
    model : str
        One of 'neo_hookean', 'mooney_rivlin', 'ogden'.
    C10, C01 : float
        Mooney-Rivlin deviatoric constants [Pa].
        For neo-Hookean: C10 = μ/2, C01 = 0.
    d : float
        Mooney-Rivlin incompressibility parameter [Pa⁻¹].
        Penalty: W_vol = (J-1)²/d.  d → 0 means fully incompressible.
        Relation to bulk modulus K: K = 2/d.
    mu_p, alpha_p : list of float
        Ogden moduli [Pa] and exponents (dimensionless).  Length 1..3.
    kappa : float
        Ogden bulk modulus [Pa] (volumetric penalty κ(J-1-ln J)).
    mu : float
        Neo-Hookean shear modulus [Pa].  Derived from C10 = μ/2 if not set.
    lam : float
        Neo-Hookean first Lamé parameter [Pa].
    """
    model: str = "mooney_rivlin"
    # Mooney-Rivlin
    C10: float = 0.1e6     # Pa (typical rubber ≈ 0.1–1 MPa)
    C01: float = 0.02e6    # Pa
    d: float = 0.0         # Pa⁻¹ (0 = incompressible penalty disabled)
    # Ogden
    mu_p: List[float] = field(default_factory=lambda: [1.0e6])
    alpha_p: List[float] = field(default_factory=lambda: [2.0])
    kappa: float = 1e9     # Pa
    # Neo-Hookean
    mu: float = 0.0        # Pa — if > 0, overrides C10
    lam: float = 0.0       # Pa

    def __post_init__(self):
        if self.model == "neo_hookean":
            if self.mu <= 0 and self.C10 > 0:
                self.mu = 2.0 * self.C10
            if self.lam <= 0:
                # default: nearly-incompressible, K ≈ 1000 μ
                self.lam = 1000.0 * self.mu * (1.0 / 3.0)
        if self.model == "ogden":
            assert len(self.mu_p) == len(self.alpha_p), (
                "mu_p and alpha_p must have the same length (1–3)"
            )
            assert 1 <= len(self.mu_p) <= 3, "Ogden: N must be 1, 2, or 3"


# ---------------------------------------------------------------------------
# Invariant helpers
# ---------------------------------------------------------------------------

def _invariants(C: np.ndarray) -> Tuple[float, float, float]:
    """Compute I1, I2, I3 = J² from right Cauchy-Green tensor C (3×3)."""
    I1 = float(np.trace(C))
    I2 = 0.5 * (I1**2 - float(np.trace(C @ C)))
    I3 = float(np.linalg.det(C))
    return I1, I2, I3


def _principal_stretches(F: np.ndarray) -> np.ndarray:
    """Return principal stretches λ1 ≥ λ2 ≥ λ3 from deformation gradient F."""
    C = F.T @ F
    eigvals = np.linalg.eigvalsh(C)  # sorted ascending
    # Stretches: λ_i = sqrt(eigenvalue of C)
    lams = np.sqrt(np.maximum(eigvals, 0.0))
    return lams[::-1]  # descending: λ1 ≥ λ2 ≥ λ3


# ---------------------------------------------------------------------------
# Neo-Hookean
# ---------------------------------------------------------------------------

def neo_hookean_strain_energy(F: np.ndarray, mu: float, lam: float) -> float:
    """Neo-Hookean strain energy density W [J/m³].

    W = (μ/2)(I1 - 3) - μ ln(J) + (λ/2)(ln J)²

    Valid for large-strain nearly-incompressible elasticity.
    As μ → μ, λ → ∞  this approaches the incompressible limit.

    Reference: Holzapfel (2000) eq. 6.134.

    Parameters
    ----------
    F : np.ndarray (3, 3)
        Deformation gradient.
    mu : float
        Shear modulus μ [Pa].
    lam : float
        First Lamé parameter λ [Pa].
    """
    C = F.T @ F
    I1 = float(np.trace(C))
    J = float(np.linalg.det(F))
    if J <= 0:
        raise ValueError(f"det(F) = {J:.4g} ≤ 0; deformation is not physical")
    lnJ = math.log(J)
    W = (mu / 2.0) * (I1 - 3.0) - mu * lnJ + (lam / 2.0) * lnJ**2
    return W


def neo_hookean_stress(F: np.ndarray, mu: float, lam: float) -> np.ndarray:
    """Neo-Hookean Cauchy stress σ (3×3) [Pa].

    σ = (1/J) [μ (B - I) + λ ln(J) I]

    where B = F Fᵀ (left Cauchy-Green tensor).

    Reference: Holzapfel (2000) eq. 6.162.
    """
    J = float(np.linalg.det(F))
    if J <= 0:
        raise ValueError(f"det(F) = {J:.4g} ≤ 0")
    B = F @ F.T
    I = np.eye(3)
    lnJ = math.log(J)
    sigma = (1.0 / J) * (mu * (B - I) + lam * lnJ * I)
    return sigma


def neo_hookean_tangent(F: np.ndarray, mu: float, lam: float) -> np.ndarray:
    """Neo-Hookean Lagrangian (material) tangent modulus C_mat (6×6) Voigt.

    C_mat_ABCD = 2 ∂S_AB / ∂C_CD

    For neo-Hookean (Holzapfel 2000 §6.6.2):
        C_mat = λ C⁻¹ ⊗ C⁻¹ - 2(μ - λ ln J) I₄_sym(C⁻¹)

    where I₄_sym(C⁻¹)_ABCD = (C⁻¹_AC C⁻¹_BD + C⁻¹_AD C⁻¹_BC)/2.

    This is computed via central-difference on S w.r.t. C for robustness.
    The FD approach guarantees consistency with the stress formula.

    Voigt order: [11, 22, 33, 12, 23, 13] (engineering shear convention).

    Returns
    -------
    C_mat : np.ndarray (6, 6)
    """
    return _fd_tangent(F, lambda F_: neo_hookean_stress(F_, mu, lam))


# ---------------------------------------------------------------------------
# Mooney-Rivlin
# ---------------------------------------------------------------------------

def mooney_rivlin_strain_energy(
    F: np.ndarray, C10: float, C01: float, d: float = 0.0
) -> float:
    """Mooney-Rivlin strain energy density W [J/m³].

    W = C10 (Ī1 - 3) + C01 (Ī2 - 3) + (1/d)(J-1)²

    where Ī1 = J^{-2/3} I1 and Ī2 = J^{-4/3} I2 are deviatoric invariants,
    and the volumetric term (1/d)(J-1)² penalises compressibility.
    For d = 0 the volumetric term is omitted (fully-incompressible assumed).

    Reference: Holzapfel (2000) §6.4; Rivlin & Saunders (1951).

    Parameters
    ----------
    F : np.ndarray (3, 3)
    C10, C01 : float
        Deviatoric material constants [Pa].
    d : float
        Incompressibility parameter [Pa⁻¹]. Bulk modulus K = 2/d.
    """
    C = F.T @ F
    I1, I2, I3 = _invariants(C)
    J = math.sqrt(max(I3, 0.0))
    if J <= 0:
        raise ValueError(f"J = {J:.4g} ≤ 0")
    # Deviatoric invariants (Holzapfel 2000 §6.4.1)
    I1_bar = J**(-2.0 / 3.0) * I1
    I2_bar = J**(-4.0 / 3.0) * I2
    W = C10 * (I1_bar - 3.0) + C01 * (I2_bar - 3.0)
    if d != 0.0:
        W += (1.0 / d) * (J - 1.0)**2
    return W


def mooney_rivlin_stress(
    F: np.ndarray, C10: float, C01: float, d: float = 0.0
) -> np.ndarray:
    """Mooney-Rivlin Cauchy stress σ (3×3) [Pa].

    Derived analytically from ∂W/∂F (Holzapfel 2000 §6.4.2):

        σ = (2/J)[C10 J^{-2/3} dev(B) + C01 J^{-4/3} dev(I1 B - B²)]
            + (2/d)(J-1) I

    where dev(X) = X - (1/3)tr(X) I (deviatoric part).

    Parameters
    ----------
    F : np.ndarray (3, 3)
    C10, C01 : float
    d : float
    """
    J = float(np.linalg.det(F))
    if J <= 0:
        raise ValueError(f"det(F) = {J:.4g} ≤ 0")
    B = F @ F.T
    I = np.eye(3)
    trB = float(np.trace(B))

    # Deviatoric parts
    def dev(X):
        return X - (np.trace(X) / 3.0) * I

    # σ_dev contribution from C10
    B_bar = J**(-2.0 / 3.0) * B
    s1 = (2.0 / J) * C10 * dev(B_bar)

    # σ_dev contribution from C01: W_I2 = C01, ∂I2/∂B = I1 I - B
    # (Holzapfel eq. 6.188)
    BB = B @ B
    B2_bar = J**(-4.0 / 3.0) * BB
    I1_bar = J**(-2.0 / 3.0) * trB
    s2 = (2.0 / J) * C01 * dev(I1_bar * B_bar - B2_bar)

    # Volumetric
    s_vol = (2.0 / d * (J - 1.0)) * I if d != 0.0 else np.zeros((3, 3))

    return s1 + s2 + s_vol


def mooney_rivlin_tangent(
    F: np.ndarray, C10: float, C01: float, d: float = 0.0
) -> np.ndarray:
    """Mooney-Rivlin Lagrangian tangent modulus C_mat (6×6) Voigt [Pa].

    Computed by finite differencing the 2nd PK stress S w.r.t. C.
    This is exact up to FD truncation error and avoids the lengthy
    closed-form expression.

    Reference: Holzapfel (2000) §6.6.
    """
    return _fd_tangent(F, lambda F_: mooney_rivlin_stress(F_, C10, C01, d))


# ---------------------------------------------------------------------------
# Ogden
# ---------------------------------------------------------------------------

def ogden_strain_energy(
    F: np.ndarray,
    mu_p: List[float],
    alpha_p: List[float],
    kappa: float = 1e9,
) -> float:
    """Ogden (1972) strain energy density W [J/m³].

    W = Σ_{p=1}^N (μ_p/α_p)(λ1^{α_p} + λ2^{α_p} + λ3^{α_p} - 3)
        + κ (J - 1 - ln J)

    where λ_i are the principal stretches (eigenvalues of sqrt(C)).
    The volumetric term κ(J - 1 - ln J) ensures W = 0 at J = 1 and
    penalises volume changes.

    Initial shear modulus: μ = (1/2) Σ_p μ_p α_p

    Reference: Ogden (1972) Proc. R. Soc. London A 326, 565-584.
               Holzapfel (2000) §6.5.

    Parameters
    ----------
    F : np.ndarray (3, 3)
    mu_p, alpha_p : list of float  (same length, N=1..3)
    kappa : float
        Volumetric bulk modulus [Pa].
    """
    N = len(mu_p)
    assert len(alpha_p) == N, "mu_p and alpha_p must have same length"
    lams = _principal_stretches(F)
    J = float(np.linalg.det(F))
    if J <= 0:
        raise ValueError(f"J = {J:.4g} ≤ 0")
    W_dev = 0.0
    for mup, ap in zip(mu_p, alpha_p):
        W_dev += (mup / ap) * (
            lams[0]**ap + lams[1]**ap + lams[2]**ap - 3.0
        )
    W_vol = kappa * (J - 1.0 - math.log(J))
    return W_dev + W_vol


def ogden_stress(
    F: np.ndarray,
    mu_p: List[float],
    alpha_p: List[float],
    kappa: float = 1e9,
) -> np.ndarray:
    """Ogden Cauchy stress σ (3×3) [Pa].

    σ = (1/J) Σ_p μ_p (λ_a^{α_p} - λ_b^{α_p}) / (λ_a² - λ_b²) ...
        expressed via spectral decomposition of B.

    Implementation: spectral decomposition of B = F Fᵀ, then:
        σ = (1/J) Σ_a β_a n_a ⊗ n_a

    where β_a = Σ_p μ_p λ_a^{α_p - 2} (deviatoric part, incompressible)
    plus volumetric term.

    Reference: Holzapfel (2000) §6.5.2, eq. 6.195-6.197.
               Ogden (1972) eq. 5.3.
    """
    J = float(np.linalg.det(F))
    if J <= 0:
        raise ValueError(f"det(F) = {J:.4g} ≤ 0")
    B = F @ F.T
    eigvals, eigvecs = np.linalg.eigh(B)
    # λ_a² = eigenvalues of B
    lam_sq = np.maximum(eigvals, 1e-30)
    lam = np.sqrt(lam_sq)

    # Cauchy stress principal components (Holzapfel 6.197)
    beta = np.zeros(3)
    for mup, ap in zip(mu_p, alpha_p):
        # Deviatoric contribution: (1/J) μ_p λ_a^{α_p}
        beta += mup * lam**ap

    # Volumetric: p_vol = κ (1 - 1/J) — Cauchy pressure from κ(J-1-lnJ)
    p_vol = kappa * (1.0 - 1.0 / J)

    # Principal Cauchy stresses: τ_a / J = β_a/J  + p_vol
    tau = beta / J + p_vol

    # Build Cauchy stress from spectral decomposition
    sigma = np.zeros((3, 3))
    for a in range(3):
        n = eigvecs[:, a]
        sigma += tau[a] * np.outer(n, n)
    return sigma


def ogden_tangent(
    F: np.ndarray,
    mu_p: List[float],
    alpha_p: List[float],
    kappa: float = 1e9,
) -> np.ndarray:
    """Ogden Lagrangian tangent modulus C_mat (6×6) Voigt [Pa].

    Computed by finite-differencing the PK2 stress; accurate and avoids
    the cumbersome closed-form Ogden tangent.
    """
    return _fd_tangent(F, lambda F_: ogden_stress(F_, mu_p, alpha_p, kappa))


# ---------------------------------------------------------------------------
# Finite-difference tangent helper
# ---------------------------------------------------------------------------

def _fd_tangent(F: np.ndarray, stress_fn) -> np.ndarray:
    """Compute the Lagrangian tangent C_mat (6×6) by central-difference.

    C_mat_AB = 2 ∂S_A / ∂C_B  (Voigt, A,B ∈ 0..5)

    Strategy:
    1. Convert Cauchy σ → PK2 S = J F⁻¹ σ F⁻ᵀ.
    2. Perturb C in each Voigt direction, convert to F via Cholesky.
    3. Finite-difference S w.r.t. C.

    This is numerically stable for non-singular deformations.
    """
    C0 = F.T @ F
    J0 = float(np.linalg.det(F))
    Finv = np.linalg.inv(F)

    def sigma_to_S(sigma, Fmat):
        J = float(np.linalg.det(Fmat))
        Finvmat = np.linalg.inv(Fmat)
        return J * Finvmat @ sigma @ Finvmat.T

    def S_from_C(C_):
        # Reconstruct F from C via Cholesky: C = Fᵀ F → F = chol(C)ᵀ
        try:
            L = np.linalg.cholesky(C_)
            F_ = L.T
        except np.linalg.LinAlgError:
            F_ = F  # fallback
        sigma_ = stress_fn(F_)
        return sigma_to_S(sigma_, F_)

    # Voigt pairs: (0,0),(1,1),(2,2),(0,1),(1,2),(0,2)
    idx = [(0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (0, 2)]
    # engineering shear factor: off-diagonal entries in C are halved when stored
    shear_factor = [1.0, 1.0, 1.0, 2.0, 2.0, 2.0]

    S0_full = S_from_C(C0)
    S0 = _full_to_voigt(S0_full)

    h = 1e-7  # perturbation step in C

    C_mat = np.zeros((6, 6))
    for j, (I, J_) in enumerate(idx):
        dC = np.zeros((3, 3))
        dC[I, J_] = h
        dC[J_, I] = h  # symmetrise
        Cp = C0 + dC
        Cm = C0 - dC

        try:
            Sp = _full_to_voigt(S_from_C(Cp))
            Sm = _full_to_voigt(S_from_C(Cm))
            dS_dC_j = (Sp - Sm) / (2.0 * h)
        except Exception:
            dS_dC_j = np.zeros(6)

        C_mat[:, j] = 2.0 * dS_dC_j / shear_factor[j]

    return C_mat


def _full_to_voigt(S: np.ndarray) -> np.ndarray:
    """Convert 3×3 symmetric tensor to 6-component Voigt vector."""
    return np.array([S[0, 0], S[1, 1], S[2, 2], S[0, 1], S[1, 2], S[0, 2]])


# ---------------------------------------------------------------------------
# Stress-stretch response curves (for visualisation / LLM tool)
# ---------------------------------------------------------------------------

def uniaxial_response(
    mat: HyperelasticModel,
    stretch_max: float = 4.0,
    n_points: int = 100,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute true (Cauchy) stress vs stretch for uniaxial tension.

    For an incompressible material under uniaxial stretch λ:
        F = diag(λ, 1/√λ, 1/√λ),   J = 1

    The true Cauchy stress in the loading direction is obtained as:
        σ_uniaxial = σ_11 - σ_22

    This difference is invariant to the indeterminate hydrostatic pressure
    that arises in incompressible (d=0) or nearly-incompressible materials,
    and is exactly the free-surface uniaxial Cauchy stress:
        σ_uniaxial = μ(λ² - 1/λ)  [Neo-Hookean]
        σ_uniaxial = 2(λ²-1/λ)(C10 + C01/λ)  [Mooney-Rivlin]
        σ_uniaxial = Σ μ_p(λ^α_p - λ^{-α_p/2})  [Ogden]

    Reference: Holzapfel (2000) §6.4.2; Ogden (1972).

    Returns
    -------
    lambdas : np.ndarray (n_points,)
        Stretch values λ ∈ [1, stretch_max].
    sigma_uniaxial : np.ndarray (n_points,)
        True (Cauchy) uniaxial stress [Pa].
    """
    lambdas = np.linspace(1.0, stretch_max, n_points)
    P = np.zeros(n_points)
    for i, lam in enumerate(lambdas):
        F = np.diag([lam, 1.0 / math.sqrt(lam), 1.0 / math.sqrt(lam)])
        sigma = _stress_from_model(mat, F)
        # σ_11 - σ_22 eliminates the indeterminate pressure for incompressible limit
        P[i] = sigma[0, 0] - sigma[1, 1]
    return lambdas, P


def biaxial_response(
    mat: HyperelasticModel,
    stretch_max: float = 3.0,
    n_points: int = 100,
) -> Tuple[np.ndarray, np.ndarray]:
    """True Cauchy stress vs stretch for equi-biaxial tension.

    F = diag(λ, λ, 1/λ²),  J = 1 (incompressible).

    Returns σ_biaxial = σ_11 - σ_33 (in-plane minus out-of-plane) vs λ.
    This is the free-surface equi-biaxial Cauchy stress.
    """
    lambdas = np.linspace(1.0, stretch_max, n_points)
    P = np.zeros(n_points)
    for i, lam in enumerate(lambdas):
        F = np.diag([lam, lam, 1.0 / lam**2])
        sigma = _stress_from_model(mat, F)
        P[i] = sigma[0, 0] - sigma[2, 2]
    return lambdas, P


def planar_response(
    mat: HyperelasticModel,
    stretch_max: float = 4.0,
    n_points: int = 100,
) -> Tuple[np.ndarray, np.ndarray]:
    """True Cauchy stress vs stretch for planar (pure shear) extension.

    F = diag(λ, 1, 1/λ),  J = 1.
    Returns σ_planar = σ_11 - σ_33 vs λ.
    """
    lambdas = np.linspace(1.0, stretch_max, n_points)
    P = np.zeros(n_points)
    for i, lam in enumerate(lambdas):
        F = np.diag([lam, 1.0, 1.0 / lam])
        sigma = _stress_from_model(mat, F)
        P[i] = sigma[0, 0] - sigma[2, 2]
    return lambdas, P


def uniaxial_cauchy_stress(mat: HyperelasticModel, lam: float) -> float:
    """Dispatch uniaxial Cauchy stress to the correct closed-form oracle.

    Returns sigma_11 - sigma_22 = true free-surface uniaxial Cauchy stress.
    """
    if mat.model == "neo_hookean":
        mu = mat.mu if mat.mu > 0 else 2.0 * mat.C10
        return neo_hookean_uniaxial_cauchy(lam, mu)
    elif mat.model == "mooney_rivlin":
        return mooney_rivlin_uniaxial_cauchy(lam, mat.C10, mat.C01)
    elif mat.model == "ogden":
        return ogden_uniaxial_cauchy(lam, mat.mu_p, mat.alpha_p)
    else:
        raise ValueError(f"Unknown model: {mat.model!r}")


def _stress_from_model(mat: HyperelasticModel, F: np.ndarray) -> np.ndarray:
    """Dispatch stress computation to the correct model."""
    if mat.model == "neo_hookean":
        mu = mat.mu if mat.mu > 0 else 2.0 * mat.C10
        lam = mat.lam if mat.lam > 0 else 1000.0 * mu / 3.0
        return neo_hookean_stress(F, mu, lam)
    elif mat.model == "mooney_rivlin":
        return mooney_rivlin_stress(F, mat.C10, mat.C01, mat.d)
    elif mat.model == "ogden":
        return ogden_stress(F, mat.mu_p, mat.alpha_p, mat.kappa)
    else:
        raise ValueError(f"Unknown hyperelastic model: {mat.model!r}")


# ---------------------------------------------------------------------------
# Closed-form uniaxial Cauchy stress (for testing / validation)
# ---------------------------------------------------------------------------

def neo_hookean_uniaxial_cauchy(lam: float, mu: float) -> float:
    """Analytical Cauchy stress for incompressible Neo-Hookean under uniaxial stretch.

    For incompressible NH:
        σ = μ(λ² - λ⁻¹)

    This follows from σ = (1/J)[μ(B - I)] + p I  with J=1 and
    the incompressibility constraint p = -μ/λ.

    Reference: Holzapfel (2000) eq. 6.163 (plane stress incompressible).
    """
    return mu * (lam**2 - 1.0 / lam)


def mooney_rivlin_uniaxial_cauchy(lam: float, C10: float, C01: float) -> float:
    """Analytical Cauchy stress for incompressible Mooney-Rivlin under uniaxial stretch.

    For incompressible MR (J=1, λ2 = λ3 = 1/√λ):
        σ_11 = 2(λ² - λ⁻¹)(C10 + C01/λ)

    Reference: Holzapfel (2000) §6.4.2; Rivlin & Saunders (1951) eq. 7.
    """
    return 2.0 * (lam**2 - 1.0 / lam) * (C10 + C01 / lam)


def ogden_uniaxial_cauchy(lam: float, mu_p: List[float], alpha_p: List[float]) -> float:
    """Analytical Cauchy stress for incompressible Ogden under uniaxial stretch.

    For incompressible Ogden (J=1):
        σ_11 = Σ_p μ_p (λ^{α_p} - λ^{-α_p/2})

    Reference: Ogden (1972) eq. 5.1; Holzapfel (2000) eq. 6.204.
    """
    sigma = 0.0
    for mup, ap in zip(mu_p, alpha_p):
        sigma += mup * (lam**ap - lam**(-ap / 2.0))
    return sigma
