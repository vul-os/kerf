"""
J2 (von Mises) plasticity with combined isotropic + kinematic hardening.

Theory
------
The J2 flow theory assumes that yielding initiates when the von Mises
equivalent stress σ_eq = √(3/2 s:s) reaches the current flow stress.
With combined hardening:

  f(σ, X, ε_p_eq) = σ_eq(s - X) - σ_y(ε_p_eq)

where
  s      = dev(σ)             stress deviator
  X      = back-stress tensor (kinematic hardening — Prager rule)
  σ_y    = σ_y0 + H_iso·ε_p_eq   (linear isotropic hardening)
  H_iso  = isotropic hardening modulus
  H_kin  = kinematic hardening modulus (Prager)

Return mapping — radial return (Simo & Hughes 1998, §3.3)
---------------------------------------------------------
1. Compute elastic trial stress:  σ_tr = σ_n + C·Δε
2. Compute trial deviator relative to back-stress:  η_tr = dev(σ_tr) - X_n
3. Evaluate yield function at trial state
4. If f_tr ≤ 0 → elastic step, return σ_tr
5. Otherwise → Newton iteration on consistency Δγ:
      Δγ = ||η_tr|| / √(2/3) - σ_y0 - H_iso·(ε_p_eq_n + √(2/3)·Δγ)
               ─────────────────────────────────────────────────────
                   2μ(1 + (H_iso + H_kin) / (3μ))

   For linear hardening this has a closed-form solution.

HONEST FLAG: Simplified implementation — no sub-stepping, no line-search,
no exact consistent algorithmic tangent.  For full quadratic convergence
of global Newton see Simo & Hughes (1998) §§3.3-3.6.

References
----------
Simo, J.C., Hughes, T.J.R. (1998). "Computational Inelasticity." Springer.
  §3.3 (radial return), §3.4 (consistent tangent).
Simo, J.C., Taylor, R.L. (1985). "Consistent tangent operators for rate-
  independent elastoplasticity." CMAME 48:101-118.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .return_mapping import (
    deviator,
    dev_norm,
    elastic_stiffness_6x6,
    second_invariant_deviator,
    voigt_inner,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class J2PlasticityMaterial:
    """
    J2 (von Mises) plasticity with combined linear isotropic + kinematic
    hardening.

    Parameters
    ----------
    youngs_modulus_pa : float
        Young's modulus E [Pa].
    poisson : float
        Poisson ratio ν.
    yield_stress_pa : float
        Initial uniaxial yield stress σ_y0 [Pa].
    isotropic_hardening_modulus_pa : float
        Linear isotropic hardening modulus H_iso [Pa].
        σ_y(ε_p_eq) = σ_y0 + H_iso · ε_p_eq.
        Set to 0.0 for perfect plasticity.
    kinematic_hardening_modulus_pa : float
        Prager kinematic hardening modulus H_kin [Pa].
        Back-stress rate:  Ẋ = (2/3) H_kin · ε̇_p.
        Set to 0.0 for pure isotropic hardening.
    """
    youngs_modulus_pa: float
    poisson: float
    yield_stress_pa: float
    isotropic_hardening_modulus_pa: float = 0.0
    kinematic_hardening_modulus_pa: float = 0.0


@dataclass
class J2State:
    """
    Per-Gauss-point internal state for J2 plasticity.

    Parameters
    ----------
    plastic_strain : np.ndarray, shape (6,)
        Plastic strain tensor in Voigt form [ε_xx, ε_yy, ε_zz, ε_xy, ε_yz, ε_xz].
    equivalent_plastic_strain : float
        Accumulated equivalent plastic strain ε_p_eq ≥ 0.
    back_stress : np.ndarray, shape (6,)
        Back-stress (kinematic hardening) tensor in Voigt form.
    """
    plastic_strain: np.ndarray = field(
        default_factory=lambda: np.zeros(6)
    )
    equivalent_plastic_strain: float = 0.0
    back_stress: np.ndarray = field(
        default_factory=lambda: np.zeros(6)
    )

    def copy(self) -> "J2State":
        return J2State(
            plastic_strain=self.plastic_strain.copy(),
            equivalent_plastic_strain=self.equivalent_plastic_strain,
            back_stress=self.back_stress.copy(),
        )


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def von_mises_equivalent(stress: np.ndarray) -> float:
    """
    Von Mises equivalent stress.

        σ_eq = √(3/2 · s:s)  =  √(3 J₂)

    where s = dev(σ) and J₂ = (1/2) s:s.

    For uniaxial stress σ_x:  σ_eq = σ_x.
    """
    return math.sqrt(3.0 * second_invariant_deviator(stress))


def yield_function_j2(
    stress: np.ndarray,
    state: J2State,
    mat: J2PlasticityMaterial,
) -> float:
    """
    J2 yield function (with kinematic hardening).

        f = √(3/2 · (s-X):(s-X)) - σ_y(ε_p_eq)

    where σ_y(ε_p_eq) = σ_y0 + H_iso · ε_p_eq.

    Returns
    -------
    float
        f < 0 → elastic state
        f = 0 → on yield surface
        f > 0 → infeasible (trial state before return mapping)
    """
    stress = np.asarray(stress, dtype=float)
    s = deviator(stress)
    eta = s - state.back_stress  # shifted deviator
    # √(3/2 · η:η) = √(3/2) · ||η||  (full contraction)
    # η:η = η_xx²+η_yy²+η_zz² + 2(η_xy²+η_yz²+η_xz²)
    eta_inner = voigt_inner(eta, eta)
    eq = math.sqrt(1.5 * eta_inner)
    sigma_y = mat.yield_stress_pa + mat.isotropic_hardening_modulus_pa * state.equivalent_plastic_strain
    return eq - sigma_y


# ---------------------------------------------------------------------------
# Return-mapping algorithm
# ---------------------------------------------------------------------------

def return_map_j2(
    stress_trial: np.ndarray,
    state_n: J2State,
    mat: J2PlasticityMaterial,
    strain_increment: np.ndarray,
) -> tuple[np.ndarray, J2State, np.ndarray]:
    """
    Radial return-mapping for J2 plasticity with combined hardening.

    Algorithm (Simo & Hughes 1998, §3.3)
    -------------------------------------
    1. Elastic predictor already in stress_trial (= σ_n + C·Δε).
    2. Compute shifted deviator:  η_tr = dev(σ_tr) - X_n
    3. Compute trial yield function f_tr.
    4. If f_tr ≤ 0 (tol): elastic step — return trial stress, unchanged state.
    5. Plastic corrector (radial return):
       a. ||η_tr|| is the driving norm.
       b. Closed-form plastic multiplier (linear hardening):
            Δγ = f_tr / (2μ·(1 + (H_iso + H_kin) / (3μ)))
          where for the combined-hardening case the effective denominator
          comes from differentiating the yield function along the return
          direction.
       c. Update:
            n̂ = η_tr / ||η_tr||           (unit normal, Voigt)
            σ_dev_new = dev(σ_tr) - 2μ Δγ · √(2/3) · n̂
            X_new = X_n + (2/3) H_kin Δγ · √(6) · n̂  [Prager]
            ε_p_new = ε_p_n + Δγ · √(2/3) · n̂
            ε_p_eq_new = ε_p_eq_n + Δγ · √(2/3)

    Parameters
    ----------
    stress_trial : np.ndarray, shape (6,)
        Elastic predictor stress.
    state_n : J2State
        Internal state at the start of the increment.
    mat : J2PlasticityMaterial
        Material parameters.
    strain_increment : np.ndarray, shape (6,)
        Total strain increment Δε (used only to build stress_trial externally;
        retained here for interface consistency).

    Returns
    -------
    (stress_n1, state_n1, consistent_tangent_6x6)
        stress_n1 : updated stress
        state_n1  : updated internal state
        consistent_tangent_6x6 : 6×6 algorithmic tangent (elastic when no
            yielding; approximate continuum tangent when plastic)

    HONEST FLAG: The returned tangent is the continuum elasto-plastic tangent,
    not the exact consistent (algorithmic) tangent.  Using the exact consistent
    tangent (Simo & Taylor 1985) is necessary for quadratic convergence of the
    global Newton-Raphson iteration.
    """
    stress_trial = np.asarray(stress_trial, dtype=float)
    strain_increment = np.asarray(strain_increment, dtype=float)

    E = mat.youngs_modulus_pa
    nu = mat.poisson
    H_iso = mat.isotropic_hardening_modulus_pa
    H_kin = mat.kinematic_hardening_modulus_pa

    mu = E / (2.0 * (1.0 + nu))          # shear modulus
    kappa = E / (3.0 * (1.0 - 2.0 * nu)) # bulk modulus

    C = elastic_stiffness_6x6(E, nu)

    # Shifted deviator at trial state
    s_tr = deviator(stress_trial)
    eta_tr = s_tr - state_n.back_stress

    # ||η_tr|| using full tensor contraction (factor-of-2 on shear)
    eta_norm = math.sqrt(voigt_inner(eta_tr, eta_tr))

    # Trial equivalent stress (von Mises with back-stress shift)
    sigma_eq_tr = math.sqrt(1.5) * eta_norm

    # Current flow stress
    sigma_y_n = (
        mat.yield_stress_pa
        + H_iso * state_n.equivalent_plastic_strain
    )

    # Trial yield function
    f_tr = sigma_eq_tr - sigma_y_n

    YIELD_TOL = 1e-10 * mat.yield_stress_pa

    if f_tr <= YIELD_TOL:
        # ── Elastic step ─────────────────────────────────────────────────────
        return stress_trial.copy(), state_n.copy(), C

    # ── Plastic corrector ────────────────────────────────────────────────────
    # Unit normal (flow direction) in the shifted-deviator space.
    # n_hat is the unit tensor normal: voigt_inner(n_hat, n_hat) = 1.
    if eta_norm < 1e-30:
        n_hat = np.zeros(6)
    else:
        n_hat = eta_tr / eta_norm  # Voigt; normalised in tensor-inner-product sense

    # --- Simo-Hughes §3.3 (p.124) return-mapping ---
    #
    # Conventions used here:
    #   sigma_eq   = sqrt(3/2) * ||eta||_F  =  sqrt(1.5) * eta_norm
    #   yield fn   = f = sigma_eq(eta_tr) - [sigma_y0 + H_iso * eps_p_eq_n]
    #
    # Radial return: eta_{n+1} = eta_tr - 2G * Δγ * n_hat
    #   → ||eta_{n+1}|| = eta_norm - 2G * Δγ
    #   → sigma_eq_{n+1} = sqrt(1.5) * (eta_norm - 2G * Δγ)
    #
    # Equivalent plastic strain increment (Simo-Hughes eq. 3.32):
    #   d_eps_p_eq = sqrt(2/3) * Δγ
    #
    # Back-stress update (Prager, kinematic, §3.5 eq. 3.44):
    #   ΔX = (2/3) * H_kin * Δε_p  = (2/3) * H_kin * Δγ * n_hat
    #   Note: the kinematic term adds (2/3)*H_kin * sqrt(2/3)*Δγ to sigma_y_eff;
    #   but in the shifted-deviator it changes the return direction and reduces
    #   f_tr after the update.
    #
    # Consistency condition (linear hardening, perfect return direction):
    #   sigma_eq_tr - sqrt(1.5) * 2G * Δγ - H_kin_eff * sqrt(2/3) * Δγ = sigma_y_n
    #   where sigma_y_n = sigma_y0 + H_iso * eps_p_eq_n  (already computed above)
    #   and H_kin_eff = (2/3) * H_kin  (from back-stress in the radial direction)
    #
    # Actually for combined isotropic+kinematic in the consistent formulation:
    #   sigma_eq_tr - [2G * sqrt(1.5) + H_iso * sqrt(2/3) + (2/3) * H_kin * sqrt(1.5)] * Δγ = sigma_y_n
    #
    # Simplified to match standard textbook result (Simo & Hughes §3.5):
    #   denom = 2G * sqrt(1.5) + H_iso * sqrt(2/3) + (2/3) * H_kin * sqrt(1.5)
    #         = sqrt(1.5) * (2G + (2/3)*H_kin) + sqrt(2/3) * H_iso
    #
    # Note: in practice the back-stress enters the trial norm, not the denominator,
    # for large increments.  Here we use the closed-form (exact for linear hardening).
    sqrt15 = math.sqrt(1.5)
    sqrt23 = math.sqrt(2.0 / 3.0)

    denom = sqrt15 * 2.0 * mu + sqrt23 * H_iso + sqrt15 * (2.0 / 3.0) * H_kin
    if denom < 1e-30:
        delta_gamma = 0.0
    else:
        delta_gamma = f_tr / denom

    # Equivalent plastic strain increment
    d_eps_p_eq = sqrt23 * delta_gamma   # Simo-Hughes eq. (3.32)

    # Plastic strain increment in Voigt (flow direction scaled by Δγ)
    # Δεᵖ = Δγ · n_hat  (where n_hat is the unit tensor normal in Voigt)
    d_eps_p_voigt = delta_gamma * n_hat  # shape (6,)

    # Updated state
    state_n1 = J2State(
        plastic_strain=(
            state_n.plastic_strain + d_eps_p_voigt
        ),
        equivalent_plastic_strain=(
            state_n.equivalent_plastic_strain + d_eps_p_eq
        ),
        back_stress=(
            state_n.back_stress
            + (2.0 / 3.0) * H_kin * d_eps_p_voigt
        ),
    )

    # Updated stress: subtract plastic correction from trial deviator.
    # σ_{n+1} = σ_tr - 2G · Δγ · n_hat  (Simo-Hughes §3.3 eq. 3.31)
    stress_n1 = stress_trial - 2.0 * mu * d_eps_p_voigt

    # --- Approximate continuum elasto-plastic tangent (not exact consistent) ---
    # Cep = C - (2G * sqrt(1.5))^2 / denom · (n⊗n)
    # where n⊗n is the outer product of the flow direction in Voigt.
    n_outer = np.outer(n_hat, n_hat)
    C_ep = C - ((2.0 * mu * sqrt15) ** 2 / denom) * n_outer

    return stress_n1, state_n1, C_ep
