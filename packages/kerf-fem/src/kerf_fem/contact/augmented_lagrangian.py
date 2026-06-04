"""
Augmented Lagrangian contact formulation.

The augmented Lagrangian (AL) method combines the accuracy of Lagrange
multipliers with the iterative efficiency of the penalty method. It avoids
the ill-conditioning that arises from very large penalty parameters while
still enforcing the contact constraint to any desired tolerance.

Theory — Uzawa update (Wriggers 2006, §5.3)
--------------------------------------------
The contact constraint is: g(u) ≥ 0 (no penetration).

The AL functional adds a term:
    Π_AL = Π(u) - λ·g(u) + (k/2)·⟨g(u)⟩₋²

where ⟨·⟩₋ = min(·, 0) is the Macaulay bracket for negative values.

At each outer (Uzawa) iteration, the Lagrange multiplier is updated:
    λ_{n+1} = max(0,  λ_n - k · g_n)

For stick conditions (friction), this converges to the exact Lagrange
multiplier solution as the outer loop converges, regardless of the
penalty k. Typical values of k are O(E/h), much smaller than the
large penalty factors needed for the pure penalty method.

References
----------
  Wriggers, P. (2006). "Computational Contact Mechanics." 2nd ed., Springer.
      §5.2–5.4 (Augmented Lagrangian, Uzawa algorithm).
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
    """Perform one Uzawa (outer) iteration update of the Lagrange multipliers.

    The update rule for normal contact (Wriggers 2006, eq. 5.28):

        λ_{n+1} = max(0, λ_n - k · g_n)

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
    """Run the full Uzawa augmented Lagrangian loop.

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
