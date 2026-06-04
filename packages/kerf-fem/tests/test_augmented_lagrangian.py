"""
Test suite for kerf_fem.contact.augmented_lagrangian.

Coverage
--------
1.  Lambda increases when gap < 0 (penetration)
2.  Lambda stays zero when gap > 0 (no contact)
3.  Lambda is non-negative (compressive only)
4.  Uzawa: lambda increases monotonically over iterations for fixed gap
5.  Convergence check: converged when gap ≈ 0 and lambda ≥ 0
6.  Not converged when large penetration remains
7.  run_uzawa_loop converges for a trivially feasible problem
8.  Penalty factor scaling: larger k → larger lambda update
9.  Mixed active/inactive nodes: only active nodes get lambda updates
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_fem.contact.augmented_lagrangian import (
    augmented_lagrangian_step,
    augmented_lagrangian_converged,
    run_uzawa_loop,
)


def test_lambda_increases_with_penetration():
    """If gap < 0 (penetration), lambda should increase after Uzawa step."""
    lam = np.array([0.0])
    gap = np.array([-0.001])   # 1 mm penetration
    k = 1e9
    lam_new = augmented_lagrangian_step(lam, gap, k)
    assert lam_new[0] > lam[0], f"Lambda should increase; got {lam_new[0]:.4e}"


def test_lambda_stays_zero_for_open_gap():
    """If gap > 0 (open), lambda should stay 0."""
    lam = np.array([0.0])
    gap = np.array([0.005])   # open gap
    k = 1e9
    lam_new = augmented_lagrangian_step(lam, gap, k)
    assert lam_new[0] == 0.0, f"Lambda should be 0 for open gap; got {lam_new[0]:.4e}"


def test_lambda_non_negative():
    """Lambda must always be non-negative (compressive contact)."""
    lam = np.array([100.0, 0.0, -5.0])  # includes a negative (invalid)
    gap = np.array([-0.001, 0.01, -0.001])
    k = 1e6
    lam_new = augmented_lagrangian_step(lam, gap, k)
    assert np.all(lam_new >= 0.0), f"Lambda must be non-negative; got {lam_new}"


def test_lambda_increases_monotonically_over_iterations():
    """For a fixed penetrating gap, lambda should grow with each iteration."""
    k = 1e8
    gap_fixed = np.array([-0.001])  # constant gap (no FEM solve)
    lam = np.array([0.0])

    lambdas = [float(lam[0])]
    for _ in range(10):
        lam = augmented_lagrangian_step(lam, gap_fixed, k)
        lambdas.append(float(lam[0]))

    for i in range(len(lambdas) - 1):
        assert lambdas[i + 1] > lambdas[i], \
            f"Lambda not monotonically increasing at step {i}: {lambdas}"


def test_converged_when_gap_near_zero():
    """Should be converged when gap ≈ 0 and lambda ≥ 0."""
    lam = np.array([1e5])
    gap = np.array([-1e-9])   # essentially zero penetration
    assert augmented_lagrangian_converged(lam, gap, tol=1e-6)


def test_not_converged_large_penetration():
    """Should not be converged when there is significant penetration."""
    lam = np.array([0.0])
    gap = np.array([-0.01])   # 10 mm penetration
    assert not augmented_lagrangian_converged(lam, gap, tol=1e-6)


def test_uzawa_loop_converges_trivial():
    """Uzawa loop on a problem where the gap becomes zero as lambda grows."""
    # Simulated contact: gap = g0 + lambda/k (penalty spring model)
    # At convergence: lambda = -k * g0, gap = 0
    k = 1e6
    g0 = -1e-4  # initial penetration

    def gap_fn(lam):
        # Simulated contact response: gap closes as lambda increases
        return np.array([g0 + lam[0] / k])

    result = run_uzawa_loop(
        initial_lambda=np.array([0.0]),
        gap_function=gap_fn,
        penalty_factor=k,
        max_iter=100,
        tol=1e-8,
    )
    assert result["converged"], "Uzawa loop should converge for linear gap model"
    assert result["iterations"] < 100


def test_larger_penalty_factor_larger_update():
    """Larger penalty k → larger lambda update per step."""
    lam = np.array([0.0])
    gap = np.array([-0.001])
    lam_small_k = augmented_lagrangian_step(lam, gap, penalty_factor=1e6)
    lam_large_k = augmented_lagrangian_step(lam, gap, penalty_factor=1e9)
    assert lam_large_k[0] > lam_small_k[0]


def test_mixed_active_inactive_nodes():
    """Only active (gap < 0) nodes should get lambda updates."""
    lam = np.array([0.0, 0.0, 0.0])
    gap = np.array([-0.001, 0.005, -0.002])   # nodes 0, 2 active; node 1 open
    k = 1e8
    lam_new = augmented_lagrangian_step(lam, gap, k)
    # Active nodes get positive lambda
    assert lam_new[0] > 0, "Active node 0 should get positive lambda"
    assert lam_new[2] > 0, "Active node 2 should get positive lambda"
    # Inactive node stays at 0
    assert lam_new[1] == 0.0, "Open node should have zero lambda"
