"""
Augmented Lagrangian contact formulation with friction.

The augmented Lagrangian (AL) method combines the accuracy of Lagrange
multipliers with the iterative efficiency of the penalty method. It avoids
the ill-conditioning that arises from very large penalty parameters while
still enforcing the contact constraint to any desired tolerance.

Theory — Normal contact Uzawa update (Wriggers 2006, §5.3)
------------------------------------------------------------
The contact constraint is: g(u) ≥ 0 (no penetration).

The AL functional adds a term:
    Π_AL = Π(u) - λ·g(u) + (k/2)·⟨g(u)⟩₋²

where ⟨·⟩₋ = min(·, 0) is the Macaulay bracket for negative values.

At each outer (Uzawa) iteration, the normal Lagrange multiplier is updated:
    λ_{n+1} = max(0,  λ_n - k_n · g_n)

Theory — Frictional contact (Alart-Curnier formulation, Wriggers 2006 §5.4)
----------------------------------------------------------------------------
For Coulomb friction, an additional tangential Lagrange multiplier λ_t is
maintained. The augmented tangential traction is:

    λ_t_trial_{n+1} = λ_t_n + k_t · Δu_t

Coulomb return-mapping (radial return):
    if |λ_t_trial| ≤ μ · λ_n:
        STICK  →  λ_t_{n+1} = λ_t_trial   (no slip)
    else:
        SLIP   →  λ_t_{n+1} = μ · λ_n · sign(λ_t_trial)

This ensures the constraint |λ_t| ≤ μ · λ_n is satisfied at every Uzawa
iteration, consistent with the Alart-Curnier complementarity function
(Alart & Curnier 1991, eq. 4.6).

Penetration comparison: Augmented-Lagrange vs Penalty
-------------------------------------------------------
For the same penalty factor k, the augmented-Lagrange method achieves
lower penetration because the Lagrange multiplier accumulates over Uzawa
iterations. At convergence:

    penetration_auglag ≈ penetration_penalty / (1 + λ_converged / (k · g_0))

In practice, augmented-Lagrange can achieve near-exact enforcement with
k = O(E/h), whereas pure penalty requires k ≫ E/h for the same accuracy.

References
----------
  Wriggers, P. (2006). "Computational Contact Mechanics." 2nd ed., Springer.
      §5.2–5.4 (Augmented Lagrangian, Uzawa algorithm, friction).
  Alart, P. & Curnier, A. (1991). "A mixed formulation for frictional
      contact problems." Comput. Methods Appl. Mech. Eng. 92, 353–375.
  Simo, J. C. & Laursen, T. A. (1992). "An augmented Lagrangian treatment
      of contact problems." Comput. Struct. 42(1), 97–116.
"""

from __future__ import annotations

import numpy as np


def augmented_lagrangian_step(
    current_lambda: np.ndarray,
    current_gap: np.ndarray,
    penalty_factor: float,
    tol: float = 1e-6,
) -> np.ndarray:
    """Perform one Uzawa (outer) iteration update of the normal Lagrange multipliers.

    The update rule for normal contact (Wriggers 2006, eq. 5.28):

        λ_{n+1} = max(0, λ_n - k·g_n)

    For an open gap (g_n > 0): the contact is inactive, λ → 0.
    For a closed/penetrating gap (g_n ≤ 0): λ increases.

    The update ensures λ ≥ 0 (compressive contact forces only).

    Parameters
    ----------
    current_lambda : np.ndarray, shape (n_nodes,)
        Current Lagrange multiplier estimates (contact pressures) [Pa or N/m²].
    current_gap : np.ndarray, shape (n_nodes,)
        Current gap function values per node [m]. Positive = open gap,
        negative = penetration.
    penalty_factor : float
        Penalty (augmentation) parameter k [N/m³]. Should be O(E/h) where
        h is the characteristic mesh size.
    tol : float, optional
        Convergence tolerance. Not used in the update step itself but
        available for calling code to check |λ_{n+1} - λ_n| < tol.

    Returns
    -------
    lambda_new : np.ndarray, shape (n_nodes,)
        Updated Lagrange multipliers. Non-negative (compressive contact only).

    Notes
    -----
    Multiple Uzawa iterations are performed until the contact constraint is
    satisfied to the desired tolerance:

        |g_active| < tol  (penetration is within tolerance)

    The outer loop (not implemented here) is:
        1. Solve the global FEM system with current λ.
        2. Compute the new gap g(u).
        3. Update λ via this function.
        4. Repeat until |g| < tol for all active contact nodes.

    Reference: Wriggers (2006) §5.3, Algorithm 5.1.
    """
    current_lambda = np.asarray(current_lambda, dtype=float)
    current_gap = np.asarray(current_gap, dtype=float)
    k = float(penalty_factor)

    # Uzawa update: λ_{n+1} = max(0, λ_n - k·g_n)
    # For contact: g < 0 means penetration → −k·g > 0, so λ increases.
    lambda_new = np.maximum(0.0, current_lambda - k * current_gap)
    return lambda_new


def augmented_lagrangian_friction_step(
    current_lambda_n: np.ndarray,
    current_lambda_t: np.ndarray,
    current_gap: np.ndarray,
    tangential_slip_increment: np.ndarray,
    penalty_normal: float,
    penalty_tangential: float,
    friction_coefficient: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Uzawa step for augmented-Lagrange contact with Coulomb friction.

    Updates both the normal Lagrange multiplier (contact pressure) and
    the tangential Lagrange multiplier (friction traction) using:

        Normal:     λ_n_{n+1} = max(0, λ_n_n - k_n · g_n)
        Tangential: λ_t_trial = λ_t_n + k_t · Δu_t
                    λ_t_{n+1} = return_map(λ_t_trial, μ · λ_n_{n+1})

    where return_map projects λ_t_trial onto the Coulomb cone
    |λ_t| ≤ μ · λ_n (Alart-Curnier 1991, §2.3).

    Parameters
    ----------
    current_lambda_n : np.ndarray, shape (n_nodes,)
        Current normal Lagrange multipliers (contact pressures) [N/m].
    current_lambda_t : np.ndarray, shape (n_nodes,)
        Current tangential Lagrange multipliers (friction tractions) [N/m].
    current_gap : np.ndarray, shape (n_nodes,)
        Current normal gap per node [m]. Negative = penetration.
    tangential_slip_increment : np.ndarray, shape (n_nodes,)
        Accumulated tangential slip increment Δu_t per node [m].
    penalty_normal : float
        Normal augmentation parameter k_n [N/m²].
    penalty_tangential : float
        Tangential augmentation parameter k_t [N/m²]. Typically = k_n.
    friction_coefficient : float
        Coulomb friction coefficient μ ≥ 0.

    Returns
    -------
    lambda_n_new : np.ndarray, shape (n_nodes,)
        Updated normal Lagrange multipliers. Non-negative.
    lambda_t_new : np.ndarray, shape (n_nodes,)
        Updated tangential Lagrange multipliers. |λ_t| ≤ μ · λ_n.
    contact_status : list[str]
        Per-node status: 'open', 'stick', or 'slip'.

    Reference: Alart & Curnier (1991), Wriggers (2006) §5.4.
    """
    current_lambda_n = np.asarray(current_lambda_n, dtype=float)
    current_lambda_t = np.asarray(current_lambda_t, dtype=float)
    current_gap = np.asarray(current_gap, dtype=float)
    tangential_slip_increment = np.asarray(tangential_slip_increment, dtype=float)

    k_n = float(penalty_normal)
    k_t = float(penalty_tangential)
    mu = float(friction_coefficient)

    n = len(current_lambda_n)

    # Step 1: Update normal Lagrange multiplier (Uzawa)
    lambda_n_new = np.maximum(0.0, current_lambda_n - k_n * current_gap)

    # Step 2: Update tangential Lagrange multiplier with friction return map
    lambda_t_new = np.zeros(n)
    contact_status: list[str] = ["open"] * n

    for i in range(n):
        if lambda_n_new[i] <= 0.0:
            # Node is open (or inactive) — no friction
            lambda_t_new[i] = 0.0
            contact_status[i] = "open"
            continue

        contact_status[i] = "stick"  # default for contact

        # Trial tangential traction (predictor)
        lt_trial = current_lambda_t[i] + k_t * tangential_slip_increment[i]

        # Coulomb cone limit
        friction_limit = mu * lambda_n_new[i]

        if mu <= 0.0:
            lambda_t_new[i] = 0.0
            contact_status[i] = "stick"
        elif abs(lt_trial) <= friction_limit:
            # Stick: inside cone
            lambda_t_new[i] = lt_trial
            contact_status[i] = "stick"
        else:
            # Slip: project radially onto cone boundary
            lambda_t_new[i] = friction_limit * np.sign(lt_trial)
            contact_status[i] = "slip"

    return lambda_n_new, lambda_t_new, contact_status


def augmented_lagrangian_converged(
    current_lambda: np.ndarray,
    current_gap: np.ndarray,
    tol: float = 1e-6,
) -> bool:
    """Check convergence of the augmented Lagrangian outer loop.

    Convergence is declared when the KKT complementarity conditions hold:
      (a) Penetration ≤ tol  on all nodes: |min(g, 0)| < tol
      (b) Inactive nodes (g > tol, λ ≈ 0): λ < tol
      (c) Active nodes (g ≤ tol, λ > 0): constraint satisfied by (a)

    This formulation correctly handles the boundary case g = 0 (just
    touching): the node is considered active-at-zero, not inactive,
    so a non-zero λ is accepted.

    Parameters
    ----------
    current_lambda : np.ndarray, shape (n_nodes,)
        Current Lagrange multipliers.
    current_gap : np.ndarray, shape (n_nodes,)
        Current gap values [m]. Negative = penetration.
    tol : float
        Penetration and lambda tolerance.

    Returns
    -------
    bool
        True if the outer loop has converged.
    """
    current_gap = np.asarray(current_gap, dtype=float)
    current_lambda = np.asarray(current_lambda, dtype=float)

    # (a) Penetration must be within tolerance everywhere
    max_penetration = float(np.max(-np.minimum(current_gap, 0.0)))
    if max_penetration > tol:
        return False

    # (b) Strictly open nodes (g > tol): lambda must be zero
    open_nodes = current_gap > tol
    if np.any(open_nodes):
        if float(np.max(np.abs(current_lambda[open_nodes]))) > tol:
            return False

    return True


def run_uzawa_loop(
    initial_lambda: np.ndarray,
    gap_function,
    penalty_factor: float,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> dict:
    """Run the full Uzawa augmented Lagrangian loop (normal contact only).

    This is a stand-alone driver for problems where the gap function
    can be evaluated without a full FEM solve (e.g., rigid-body contact
    or post-processing verification).

    Parameters
    ----------
    initial_lambda : np.ndarray
        Initial Lagrange multiplier estimates.
    gap_function : callable
        A function ``g(lambda) -> np.ndarray`` that returns the current
        gap for the given Lagrange multipliers. In a full FEM context,
        this involves solving the global system.
    penalty_factor : float
        Penalty parameter k [N/m³ or consistent units].
    max_iter : int
        Maximum number of Uzawa iterations.
    tol : float
        Convergence tolerance.

    Returns
    -------
    dict with keys:
        'lambda_final'   — converged Lagrange multipliers
        'gap_final'      — final gap values
        'iterations'     — number of iterations taken
        'converged'      — bool
    """
    lam = np.asarray(initial_lambda, dtype=float).copy()

    for it in range(max_iter):
        gap = np.asarray(gap_function(lam), dtype=float)
        lam_new = augmented_lagrangian_step(lam, gap, penalty_factor, tol)

        if augmented_lagrangian_converged(lam_new, gap, tol):
            return {
                "lambda_final": lam_new,
                "gap_final": gap,
                "iterations": it + 1,
                "converged": True,
            }
        lam = lam_new

    gap = np.asarray(gap_function(lam), dtype=float)
    return {
        "lambda_final": lam,
        "gap_final": gap,
        "iterations": max_iter,
        "converged": False,
    }


def run_uzawa_loop_with_friction(
    initial_lambda_n: np.ndarray,
    initial_lambda_t: np.ndarray,
    gap_function,
    slip_function,
    penalty_normal: float,
    penalty_tangential: float,
    friction_coefficient: float,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> dict:
    """Run the full Uzawa loop for frictional augmented-Lagrange contact.

    Drives the outer Uzawa iteration for normal + frictional contact.
    At each iteration both the normal gap and the tangential slip are
    re-evaluated (via the provided callables), and the Lagrange multipliers
    for both normal and tangential tractions are updated.

    Parameters
    ----------
    initial_lambda_n : np.ndarray, shape (n_nodes,)
        Initial normal Lagrange multipliers.
    initial_lambda_t : np.ndarray, shape (n_nodes,)
        Initial tangential Lagrange multipliers.
    gap_function : callable
        ``g(lam_n, lam_t) -> np.ndarray`` — returns normal gap per node [m].
    slip_function : callable
        ``s(lam_n, lam_t) -> np.ndarray`` — returns accumulated tangential
        slip increment per node [m].
    penalty_normal : float
        Normal augmentation parameter k_n [N/m²].
    penalty_tangential : float
        Tangential augmentation parameter k_t [N/m²].
    friction_coefficient : float
        Coulomb coefficient μ ≥ 0.
    max_iter : int
        Maximum Uzawa iterations.
    tol : float
        Convergence tolerance (on penetration magnitude).

    Returns
    -------
    dict with keys:
        'lambda_n_final'    — converged normal Lagrange multipliers
        'lambda_t_final'    — converged tangential Lagrange multipliers
        'gap_final'         — final normal gap values [m]
        'slip_final'        — final tangential slip values [m]
        'contact_status'    — list of 'open'/'stick'/'slip' per node
        'iterations'        — number of iterations taken
        'converged'         — bool

    Reference: Alart & Curnier (1991); Wriggers (2006) §5.4.
    """
    lam_n = np.asarray(initial_lambda_n, dtype=float).copy()
    lam_t = np.asarray(initial_lambda_t, dtype=float).copy()

    for it in range(max_iter):
        gap = np.asarray(gap_function(lam_n, lam_t), dtype=float)
        slip = np.asarray(slip_function(lam_n, lam_t), dtype=float)

        lam_n_new, lam_t_new, statuses = augmented_lagrangian_friction_step(
            lam_n, lam_t, gap, slip,
            penalty_normal, penalty_tangential, friction_coefficient,
        )

        if augmented_lagrangian_converged(lam_n_new, gap, tol):
            return {
                "lambda_n_final": lam_n_new,
                "lambda_t_final": lam_t_new,
                "gap_final": gap,
                "slip_final": slip,
                "contact_status": statuses,
                "iterations": it + 1,
                "converged": True,
            }
        lam_n = lam_n_new
        lam_t = lam_t_new

    gap = np.asarray(gap_function(lam_n, lam_t), dtype=float)
    slip = np.asarray(slip_function(lam_n, lam_t), dtype=float)
    _, lam_t_final, statuses = augmented_lagrangian_friction_step(
        lam_n, lam_t, gap, slip,
        penalty_normal, penalty_tangential, friction_coefficient,
    )
    return {
        "lambda_n_final": lam_n,
        "lambda_t_final": lam_t_final,
        "gap_final": gap,
        "slip_final": slip,
        "contact_status": statuses,
        "iterations": max_iter,
        "converged": False,
    }
