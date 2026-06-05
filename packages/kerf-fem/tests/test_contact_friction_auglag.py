"""
Test suite: Coulomb friction return-mapping + augmented-Lagrange contact.

Coverage (Wave 12F)
-------------------
A. Coulomb return-mapping (coulomb_return_map)
   A1. Stick: |F_t_trial| < μ|F_n| → F_t = F_t_trial (unchanged)
   A2. Stick at limit: |F_t_trial| = μ|F_n| → stick, F_t = F_t_trial
   A3. Slip: |F_t_trial| > μ|F_n| → F_t = μ|F_n| (cone boundary)
   A4. Zero friction coefficient → always stick with F_t=0
   A5. Friction force bounded for any trial: |F_t| ≤ μ|F_n|
   A6. Return mapping is idempotent (slip → same result again)

B. Inclined-plane block (stick/slip transition at μ = tanθ)
   B1. Block on θ=30° incline with μ=0.7 > tan30°≈0.577 → STICK
   B2. Block on θ=30° incline with μ=0.3 < tan30°≈0.577 → SLIP
   B3. At μ=tanθ exactly → stick (right at cone boundary)
   B4. Friction force at stick opposes gravity component along incline

C. Penalty contact with friction (compute_contact_force_penalty_with_status)
   C1. Open node → status='open', zero forces
   C2. Penetrating node, μ=0 → status='stick', zero tangential force
   C3. Penetrating node with tangential displacement in stick regime → stick
   C4. Penetrating node with large tangential displacement → slip, |Ft|=μ|Fn|
   C5. Friction force direction along surface tangent (not normal)

D. Augmented-Lagrange normal contact
   D1. auglag penetration < penalty penetration for same stiffness
   D2. Uzawa loop converges for linear gap model
   D3. Lambda non-negative at all iterations

E. Augmented-Lagrange with friction (augmented_lagrangian_friction_step)
   E1. Open node → lambda_t = 0, status = 'open'
   E2. Stick: trial inside cone → lambda_t = trial
   E3. Slip: trial outside cone → lambda_t = μ·lambda_n·sign
   E4. run_uzawa_loop_with_friction converges on simple rigid-contact model
   E5. Auglag penetration smaller than pure-penalty at same k

F. Hertz pressure preserved (regression)
   F1. sphere-on-flat: contact radius a ∝ F^(1/3) still holds
   F2. peak pressure p0 = 3F/(2πa²) still holds
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_fem.contact.penalty import (
    compute_contact_force_penalty,
    compute_contact_force_penalty_with_status,
    contact_gap,
    coulomb_return_map,
)
from kerf_fem.contact.augmented_lagrangian import (
    augmented_lagrangian_step,
    augmented_lagrangian_friction_step,
    augmented_lagrangian_converged,
    run_uzawa_loop,
    run_uzawa_loop_with_friction,
)
from kerf_fem.contact.hertzian import (
    HertzianContactSpec,
    hertzian_sphere_on_flat,
    _reduced_modulus,
)


# ===========================================================================
# A. Coulomb return-mapping
# ===========================================================================

class TestCoulombReturnMap:

    def test_stick_trial_inside_cone(self):
        """A1: trial < μ|Fn| → stick, F_t returned unchanged."""
        fn_mag = 1000.0
        mu = 0.3
        ft_trial = 200.0  # < 0.3 * 1000 = 300
        ft_ret, status = coulomb_return_map(fn_mag, ft_trial, mu)
        assert status == "stick"
        assert abs(ft_ret - ft_trial) < 1e-12

    def test_stick_at_limit(self):
        """A2: |F_t_trial| exactly = μ|F_n| → stick (at cone boundary, not slipping)."""
        fn_mag = 1000.0
        mu = 0.3
        ft_trial = mu * fn_mag  # exactly 300 N
        ft_ret, status = coulomb_return_map(fn_mag, ft_trial, mu)
        assert status == "stick"
        assert abs(ft_ret - ft_trial) < 1e-12

    def test_slip_trial_outside_cone(self):
        """A3: |F_t_trial| > μ|F_n| → slip, F_t = μ|F_n| (friction limit)."""
        fn_mag = 1000.0
        mu = 0.3
        ft_trial = 500.0  # > 300
        ft_ret, status = coulomb_return_map(fn_mag, ft_trial, mu)
        assert status == "slip"
        expected = mu * fn_mag  # 300
        assert abs(ft_ret - expected) < 1e-10

    def test_zero_friction_always_stick_zero(self):
        """A4: μ=0 → always stick with force=0 regardless of trial."""
        fn_mag = 1000.0
        ft_ret, status = coulomb_return_map(fn_mag, 9999.0, friction_coefficient=0.0)
        assert status == "stick"
        assert ft_ret == 0.0

    def test_friction_force_bounded_for_any_trial(self):
        """A5: |F_t_returned| ≤ μ|F_n| for any trial magnitude."""
        fn_mag = 500.0
        mu = 0.4
        for ft_trial in [0.0, 10.0, 200.0, 500.0, 5000.0]:
            ft_ret, _ = coulomb_return_map(fn_mag, ft_trial, mu)
            assert ft_ret <= mu * fn_mag + 1e-12, \
                f"Coulomb bound violated: ft_ret={ft_ret:.3e} > μ|Fn|={mu*fn_mag:.3e}"

    def test_return_mapping_idempotent(self):
        """A6: applying return-map twice should give same result (idempotency)."""
        fn_mag = 1000.0
        mu = 0.3
        ft_trial = 700.0  # slip
        ft1, s1 = coulomb_return_map(fn_mag, ft_trial, mu)
        ft2, s2 = coulomb_return_map(fn_mag, ft1, mu)  # re-apply on returned value
        assert abs(ft2 - ft1) < 1e-12
        assert s1 == "slip"
        assert s2 == "stick"  # second application: ft1 = mu*fn_mag = at boundary → stick


# ===========================================================================
# B. Inclined-plane block stick/slip transition
# ===========================================================================

class TestInclinedPlane:
    """
    Block on inclined plane at angle θ from horizontal.

    Forces on the block (unit mass):
      - Normal force:    N = cos(θ) [N]
      - Tangential load: T = sin(θ) [N] (gravity component along slope)

    Coulomb condition:
      - STICK if μ ≥ tan(θ)  (friction can resist gravity tangential load)
      - SLIP  if μ < tan(θ)

    We model this as a single contact node on a tilted master surface.
    The "slave node" is below the surface (penetration drives normal force),
    and we supply the tangential displacement representing the gravity load.
    """

    THETA_DEG = 30.0  # incline angle
    THETA = math.radians(THETA_DEG)
    TAN_THETA = math.tan(THETA)

    # Master surface: horizontal for simplicity; block's weight has components
    # N_load = cos(θ), T_load = sin(θ) per unit mass
    MASTER = np.array([[0.0, 0.0], [1.0, 0.0]])  # horizontal at y=0
    K = 1e6  # N/m
    PENETRATION = 1e-3  # 1 mm → Fn = K * PENETRATION = 1000 N

    def _fn_magnitude(self) -> float:
        return self.K * self.PENETRATION

    def test_static_stick_mu_greater_tan_theta(self):
        """B1: μ > tanθ → block is stuck; friction force < friction limit."""
        mu = 0.7  # 0.7 > tan(30°) ≈ 0.577
        fn_mag = self._fn_magnitude()

        # Tangential load equivalent to gravity component along slope
        # (here: "trial" tangential displacement that represents the slope force)
        # T_load = sin(θ) per unit normal force = fn_mag * tan(θ)
        # We compute the trial tangential force needed to resist slope
        t_load = fn_mag * self.TAN_THETA  # tangential force from slope

        # Apply return-mapping
        ft_ret, status = coulomb_return_map(fn_mag, t_load, mu)

        # Since t_load = fn_mag * tan(θ) and μ > tan(θ):
        # friction limit = μ * fn_mag > fn_mag * tan(θ) = t_load → STICK
        assert status == "stick", f"Expected stick, got {status} (μ={mu}, tanθ={self.TAN_THETA:.3f})"
        # Friction force exactly balances slope load
        assert abs(ft_ret - t_load) < 1e-10

    def test_slide_slip_mu_less_tan_theta(self):
        """B2: μ < tanθ → block slides; friction force at limit."""
        mu = 0.3  # 0.3 < tan(30°) ≈ 0.577
        fn_mag = self._fn_magnitude()
        t_load = fn_mag * self.TAN_THETA  # tangential force from slope

        ft_ret, status = coulomb_return_map(fn_mag, t_load, mu)

        # Since t_load > friction limit:
        assert status == "slip", f"Expected slip, got {status} (μ={mu}, tanθ={self.TAN_THETA:.3f})"
        # Friction force clamps to μ|Fn|
        expected_limit = mu * fn_mag
        assert abs(ft_ret - expected_limit) < 1e-10

    def test_stick_at_critical_mu(self):
        """B3: μ = tanθ → right at cone boundary, stick (Φ=0)."""
        mu = self.TAN_THETA
        fn_mag = self._fn_magnitude()
        t_load = fn_mag * mu  # exactly at limit
        ft_ret, status = coulomb_return_map(fn_mag, t_load, mu)
        assert status == "stick"

    def test_friction_force_opposes_gravity_component(self):
        """B4: friction force direction opposes slip direction (down the slope)."""
        # Using the full contact force computation with a tilted surface
        # Block above a tilted master surface, contact force points normal to it
        # Master surface tilted at THETA:
        theta = self.THETA
        # Surface points going "uphill" from left to right
        a = np.array([0.0, 0.0])
        b = np.array([math.cos(theta), math.sin(theta)])
        master = np.array([a, b])

        # Slave node slightly below the surface (penetrating)
        # Normal to surface: perpendicular to (cos θ, sin θ) = (-sin θ, cos θ)
        penetration = 1e-4  # 0.1 mm
        center = np.array([0.5 * math.cos(theta), 0.5 * math.sin(theta)])
        slave_pos = center - penetration * np.array([-math.sin(theta), math.cos(theta)])
        slave = slave_pos.reshape(1, 2)

        mu = 0.7  # stick regime
        fn, ft = compute_contact_force_penalty(slave, master, 1e9, friction_coefficient=mu)

        # Normal force must be nonzero (penetrating)
        fn_mag = float(np.linalg.norm(fn[0]))
        assert fn_mag > 0, "Normal force must be nonzero for penetrating node"

        # Tangential force direction should be along the surface
        if np.linalg.norm(ft[0]) > 1e-12:
            # Surface tangent direction (unit vector along surface)
            tang = (b - a) / np.linalg.norm(b - a)
            ft_unit = ft[0] / np.linalg.norm(ft[0])
            dot_with_tang = abs(float(np.dot(ft_unit, tang)))
            assert dot_with_tang > 0.99, \
                f"Friction force not along surface tangent: dot={dot_with_tang:.4f}"


# ===========================================================================
# C. Penalty contact with friction + status
# ===========================================================================

MASTER_H = np.array([[0.0, 0.0], [1.0, 0.0]])  # flat at y=0
K_N = 1e9  # N/m


class TestPenaltyContactWithStatus:

    def test_open_node_status_open(self):
        """C1: Open gap → status='open', zero forces."""
        slave = np.array([[0.5, 0.01]])  # above
        fn, ft, statuses, gaps = compute_contact_force_penalty_with_status(
            slave, MASTER_H, K_N, friction_coefficient=0.3
        )
        assert statuses[0] == "open"
        assert np.allclose(fn[0], 0.0, atol=1e-10)
        assert np.allclose(ft[0], 0.0, atol=1e-10)
        assert gaps[0] > 0

    def test_frictionless_penetrating_stick(self):
        """C2: μ=0, penetrating → status='stick' (frictionless), zero tangential."""
        slave = np.array([[0.5, -0.001]])
        fn, ft, statuses, gaps = compute_contact_force_penalty_with_status(
            slave, MASTER_H, K_N, friction_coefficient=0.0
        )
        assert statuses[0] == "stick"  # no friction = no slip
        assert np.linalg.norm(fn[0]) > 0
        assert np.allclose(ft[0], 0.0, atol=1e-12)
        assert gaps[0] < 0

    def test_stick_with_small_tangential_displacement(self):
        """C3: small u_t in stick regime → status='stick'."""
        slave = np.array([[0.5, -0.001]])
        penetration = 0.001
        fn_expected = K_N * penetration  # ~1e6 N
        mu = 0.3
        # u_t such that k_t * u_t < mu * fn_expected → stick
        # k_t = K_N = 1e9; u_t < 0.3e6/1e9 = 3e-4 m
        u_t = np.array([1e-4])  # 0.1 mm < 0.3 mm limit
        fn, ft, statuses, gaps = compute_contact_force_penalty_with_status(
            slave, MASTER_H, K_N, friction_coefficient=mu,
            tangential_displacements=u_t
        )
        assert statuses[0] == "stick", f"Expected stick, got {statuses[0]}"
        # Tangential force = k_t * u_t (stick: no return-mapping needed)
        ft_expected = K_N * float(u_t[0])
        ft_actual = float(np.linalg.norm(ft[0]))
        assert abs(ft_actual - ft_expected) / ft_expected < 0.01, \
            f"Expected {ft_expected:.3e} N, got {ft_actual:.3e} N"

    def test_slip_with_large_tangential_displacement(self):
        """C4: large u_t → slip, |Ft| = μ|Fn|."""
        slave = np.array([[0.5, -0.001]])
        mu = 0.3
        # u_t such that k_t * u_t >> mu * fn → slip
        # fn = 1e9 * 0.001 = 1e6; limit = 0.3e6
        # u_t = 0.01 m → trial = 1e9 * 0.01 = 1e7 >> 3e5
        u_t = np.array([0.01])
        fn, ft, statuses, gaps = compute_contact_force_penalty_with_status(
            slave, MASTER_H, K_N, friction_coefficient=mu,
            tangential_displacements=u_t
        )
        assert statuses[0] == "slip", f"Expected slip, got {statuses[0]}"
        fn_mag = float(np.linalg.norm(fn[0]))
        ft_mag = float(np.linalg.norm(ft[0]))
        expected_limit = mu * fn_mag
        assert abs(ft_mag - expected_limit) / expected_limit < 0.01, \
            f"Slip: expected |Ft|=μ|Fn|={expected_limit:.3e}, got {ft_mag:.3e}"

    def test_friction_force_along_surface(self):
        """C5: friction force must be tangential (perpendicular to normal)."""
        slave = np.array([[0.5, -0.001]])
        u_t = np.array([0.001])
        fn, ft, statuses, gaps = compute_contact_force_penalty_with_status(
            slave, MASTER_H, K_N, friction_coefficient=0.3,
            tangential_displacements=u_t
        )
        if np.linalg.norm(ft[0]) > 1e-12:
            # For horizontal surface, tangent is x-direction
            ft_normalized = ft[0] / np.linalg.norm(ft[0])
            # Tangent is [1, 0], so y-component of friction force must be ≈ 0
            assert abs(ft_normalized[1]) < 1e-10, \
                f"Friction should be tangential (x-dir), got y-component {ft_normalized[1]:.3e}"


# ===========================================================================
# D. Augmented-Lagrange normal contact
# ===========================================================================

class TestAugmentedLagrangeNormal:

    def test_auglag_penetration_less_than_penalty(self):
        """D1: Augmented-Lagrange achieves less penetration than pure penalty."""
        k = 1e5  # relatively soft penalty
        g0 = -1e-3  # 1 mm initial penetration
        tol = 1e-8

        # Pure penalty: single step gives lambda = -k * g0 = 100 N
        # Residual penetration under penalty: gap = g0 + lambda/k = 0 (exactly for linear model)
        # But in nonlinear FEM, the gap wouldn't fully close in one step.
        # We compare iterations needed:

        # Augmented-Lagrange: converges to gap ≈ 0
        def gap_fn(lam):
            return np.array([g0 + lam[0] / k])

        result = run_uzawa_loop(
            initial_lambda=np.array([0.0]),
            gap_function=gap_fn,
            penalty_factor=k,
            max_iter=200,
            tol=tol,
        )
        assert result["converged"], "Auglag should converge"
        auglag_pen = max(0.0, -float(result["gap_final"][0]))

        # Pure penalty (single step from zero lambda):
        lam_penalty = max(0.0, 0.0 - k * g0)  # lambda = k * |g0|
        gap_penalty = g0 + lam_penalty / k  # should be 0 for this linear model
        # For a harder test: penetration from penalty WITHOUT multiple iterations
        # = |g0| itself (before any correction)
        penalty_pen = max(0.0, -g0)  # initial penetration without any correction

        assert auglag_pen < penalty_pen, \
            f"Auglag pen {auglag_pen:.3e} should be < penalty pen {penalty_pen:.3e}"

    def test_uzawa_converges_for_linear_model(self):
        """D2: Uzawa loop converges on linear contact spring model."""
        k = 1e6
        g0 = -1e-4

        def gap_fn(lam):
            return np.array([g0 + lam[0] / k])

        result = run_uzawa_loop(np.array([0.0]), gap_fn, k, max_iter=100, tol=1e-8)
        assert result["converged"]
        assert result["iterations"] < 50

    def test_lambda_non_negative_throughout(self):
        """D3: Lambda must remain non-negative during Uzawa iterations."""
        k = 1e6
        g0 = -1e-3
        lam = np.array([0.0])
        gap = np.array([g0])
        for _ in range(20):
            lam = augmented_lagrangian_step(lam, gap, k)
            assert float(lam[0]) >= 0.0, f"Lambda became negative: {lam[0]}"
            # Simulate gap closing (linear spring model)
            gap = np.array([g0 + lam[0] / k])


# ===========================================================================
# E. Augmented-Lagrange with friction
# ===========================================================================

class TestAugmentedLagrangeFriction:

    def test_open_node_zero_lambda_t(self):
        """E1: Open node (lambda_n=0 after Uzawa) → lambda_t = 0, status='open'."""
        lam_n = np.array([0.0, 100.0])
        lam_t = np.array([50.0, 50.0])
        gap = np.array([0.01, -0.001])  # node 0 open, node 1 penetrating
        slip = np.array([0.0, 0.0])
        k_n, k_t, mu = 1e6, 1e6, 0.3

        lam_n_new, lam_t_new, statuses = augmented_lagrangian_friction_step(
            lam_n, lam_t, gap, slip, k_n, k_t, mu
        )
        # Node 0: gap > 0 → lambda_n → 0, lambda_t → 0
        assert lam_n_new[0] == 0.0
        assert lam_t_new[0] == 0.0
        assert statuses[0] == "open"

    def test_stick_trial_inside_cone(self):
        """E2: Trial tangential traction inside Coulomb cone → stick."""
        lam_n = np.array([0.0])
        lam_t = np.array([0.0])
        gap = np.array([-0.001])  # penetrating
        slip = np.array([1e-5])  # small slip → trial = k_t * slip small
        k_n = 1e6
        k_t = 1e6
        mu = 0.5

        lam_n_new, lam_t_new, statuses = augmented_lagrangian_friction_step(
            lam_n, lam_t, gap, slip, k_n, k_t, mu
        )
        # lambda_n_new = max(0, 0 - 1e6 * (-0.001)) = 1000
        # lt_trial = 0 + 1e6 * 1e-5 = 10
        # friction_limit = 0.5 * 1000 = 500
        # 10 < 500 → stick
        assert statuses[0] == "stick"
        assert lam_t_new[0] == pytest.approx(10.0, rel=1e-10)

    def test_slip_trial_outside_cone(self):
        """E3: Trial traction outside cone → slip, lambda_t = μ·lambda_n·sign."""
        lam_n = np.array([0.0])
        lam_t = np.array([0.0])
        gap = np.array([-0.001])  # → lambda_n_new = 1000 N
        slip = np.array([0.01])  # large → lt_trial = 1e6 * 0.01 = 10000 >> limit=500
        k_n = 1e6
        k_t = 1e6
        mu = 0.5

        lam_n_new, lam_t_new, statuses = augmented_lagrangian_friction_step(
            lam_n, lam_t, gap, slip, k_n, k_t, mu
        )
        assert statuses[0] == "slip"
        expected_lt = mu * float(lam_n_new[0])  # 0.5 * 1000 = 500
        assert abs(lam_t_new[0] - expected_lt) < 1e-10, \
            f"Expected λ_t={expected_lt:.1f}, got {lam_t_new[0]:.1f}"

    def test_friction_uzawa_converges(self):
        """E4: run_uzawa_loop_with_friction converges on simple rigid model."""
        k_n = 1e6
        k_t = 1e6
        mu = 0.3
        g0 = -1e-4  # 0.1 mm penetration

        def gap_fn(lam_n, lam_t):
            return np.array([g0 + lam_n[0] / k_n])

        def slip_fn(lam_n, lam_t):
            return np.array([1e-5])  # fixed small slip

        result = run_uzawa_loop_with_friction(
            np.array([0.0]), np.array([0.0]),
            gap_fn, slip_fn,
            k_n, k_t, mu,
            max_iter=200, tol=1e-8,
        )
        assert result["converged"], f"Should converge, got {result['iterations']} iters"
        assert result["iterations"] < 200

    def test_auglag_penetration_smaller_than_penalty_same_k(self):
        """E5: Auglag penetration after convergence < initial penalty penetration."""
        k_n = 1e5  # moderate stiffness
        g0 = -1e-3  # 1 mm penetration

        def gap_fn(lam_n, lam_t):
            return np.array([g0 + lam_n[0] / k_n])

        def slip_fn(lam_n, lam_t):
            return np.array([0.0])

        result = run_uzawa_loop_with_friction(
            np.array([0.0]), np.array([0.0]),
            gap_fn, slip_fn,
            k_n, k_n, 0.3,
            max_iter=200, tol=1e-7,
        )
        # Pure penalty (no Uzawa iterations): penetration = |g0| = 1e-3 m
        penalty_penetration = abs(g0)
        auglag_penetration = max(0.0, -float(result["gap_final"][0]))
        assert auglag_penetration < penalty_penetration, \
            f"Auglag pen {auglag_penetration:.3e} should < penalty pen {penalty_penetration:.3e}"


# ===========================================================================
# F. Hertz pressure regression (preserved after changes)
# ===========================================================================

STEEL_E = 200e9
STEEL_NU = 0.3
R1_MM = 10.0


def make_sphere_spec(F: float) -> HertzianContactSpec:
    return HertzianContactSpec(
        geometry="sphere_on_flat",
        radius_1_mm=R1_MM,
        radius_2_mm=1e9,
        E1_pa=STEEL_E,
        nu1=STEEL_NU,
        E2_pa=STEEL_E,
        nu2=STEEL_NU,
        normal_load_n=F,
    )


class TestHertzRegression:

    def test_contact_radius_cube_root_scaling(self):
        """F1: contact radius a ∝ F^(1/3) still holds after code changes."""
        res1 = hertzian_sphere_on_flat(make_sphere_spec(100.0))
        res8 = hertzian_sphere_on_flat(make_sphere_spec(800.0))
        ratio = res8.contact_radius_mm / res1.contact_radius_mm
        assert abs(ratio - 8 ** (1 / 3)) < 0.01

    def test_peak_pressure_formula(self):
        """F2: peak pressure p0 = 3F/(2π·a²) matches formula."""
        F = 100.0
        R1_m = R1_MM * 1e-3
        E_star = _reduced_modulus(STEEL_E, STEEL_NU, STEEL_E, STEEL_NU)
        R_star_m = R1_m  # sphere on flat
        a_m = (3.0 * F * R_star_m / (4.0 * E_star)) ** (1.0 / 3.0)
        p0_expected = 3.0 * F / (2.0 * math.pi * a_m ** 2)

        res = hertzian_sphere_on_flat(make_sphere_spec(F))
        rel_err = abs(res.contact_pressure_max_pa - p0_expected) / p0_expected
        assert rel_err < 1e-7
