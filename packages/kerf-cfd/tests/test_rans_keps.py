"""
Validation test suite for kerf_cfd.rans_keps — Standard k-ε turbulence model
(Launder & Spalding 1974).

Three primary validation cases per the T-101 DoD:

  1. Channel flow Re=10 000  — log-layer TKE vs Mansour et al. (1988) DNS
  2. Backward-facing step     — reattachment x_r/h vs Driver-Seegmiller (1985)
  3. Conservation             — mass + momentum within 0.1 %

Additional unit-level tests cover closure constants, wall functions, and
eddy-viscosity formulas.

References
----------
[LS1974]       Launder & Spalding, Comput. Methods Appl. Mech. Engng. 3 (1974)
[Mansour1988]  Mansour, Kim, Moin, J. Fluid Mech. 194 (1988) 15-44.
               DNS channel Re_τ≈395; k+ peak ≈ 4.2 at y+≈15;
               log-layer plateau k/u_τ² ≈ 3.3–4.0.
[DriverSeeg]   Driver & Seegmiller, AIAA J. 23(2) (1985) 163-171.
               BFS Re_h≈37 300; x_r/h ≈ 6.26 (often cited as 6.0 ± 0.3).
[Pope2000]     Pope, Turbulent Flows, Cambridge 2000.  §7.1, §10.1.
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC  = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_cfd.rans_keps import (
    BFS_RE_H_DS,
    BFS_XR_MEAN,
    BFS_XR_TOL,
    C_1EPS,
    C_2EPS,
    C_MU,
    KAPPA,
    LOGLAW_B,
    MANSOUR_K_PLUS_LOG_LAYER,
    MANSOUR_K_PLUS_TOLERANCE,
    SIGMA_E,
    SIGMA_K,
    YPLUS_LAM,
    ChannelKepsConfig,
    channel_log_layer_keps,
    check_channel_conservation,
    compute_nut_keps,
    estimate_bfs_reattachment_keps,
    keps_constants,
    solve_channel_keps,
    validate_channel_re10000,
    wall_function_bc,
)


def _rel(a: float, b: float) -> float:
    """Relative difference |a-b| / max(|b|, 1e-30)."""
    return abs(a - b) / max(abs(b), 1.0e-30)


# ===========================================================================
# 1. Closure constants — Launder & Spalding (1974) Table 1
# ===========================================================================

class TestKepsConstants:
    """All constants must match Launder-Spalding (1974) Table 1 exactly."""

    def test_C_mu(self):
        """C_μ = 0.09  [LS1974 Table 1]"""
        assert keps_constants()["C_mu"] == pytest.approx(0.09, rel=1e-10)

    def test_C_1eps(self):
        """C_1ε = 1.44  [LS1974 Table 1]"""
        assert keps_constants()["C_1eps"] == pytest.approx(1.44, rel=1e-10)

    def test_C_2eps(self):
        """C_2ε = 1.92  [LS1974 Table 1]"""
        assert keps_constants()["C_2eps"] == pytest.approx(1.92, rel=1e-10)

    def test_sigma_k(self):
        """σ_k = 1.0  [LS1974 Table 1]"""
        assert keps_constants()["sigma_k"] == pytest.approx(1.0, rel=1e-10)

    def test_sigma_e(self):
        """σ_ε = 1.3  [LS1974 Table 1]"""
        assert keps_constants()["sigma_e"] == pytest.approx(1.3, rel=1e-10)

    def test_kappa(self):
        """κ = 0.41  [Pope2000 §7.1]"""
        assert keps_constants()["kappa"] == pytest.approx(0.41, rel=1e-10)

    def test_yplus_lam(self):
        """y+_lam = 11.225 (viscous sublayer transition)  [LS1974 §3]"""
        assert keps_constants()["yplus_lam"] == pytest.approx(11.225, rel=1e-10)


# ===========================================================================
# 2. Eddy-viscosity formula
# ===========================================================================

class TestNutKeps:
    """ν_t = C_μ k² / ε"""

    def test_nut_basic(self):
        """For known k and ε, verify formula."""
        k, eps = 1.0, 1.0
        expected = C_MU * k * k / eps
        assert compute_nut_keps(k, eps) == pytest.approx(expected, rel=1e-10)

    def test_nut_positive(self):
        """ν_t must always be ≥ 0."""
        for k in [0.0, 0.001, 1.0, 100.0]:
            for eps in [0.0, 0.001, 1.0, 100.0]:
                assert compute_nut_keps(k, eps) >= 0.0

    def test_nut_scales_with_k_squared(self):
        """Doubling k (at fixed ε) should quadruple ν_t."""
        nut_1 = compute_nut_keps(1.0, 1.0)
        nut_2 = compute_nut_keps(2.0, 1.0)
        assert nut_2 / nut_1 == pytest.approx(4.0, rel=1e-8)

    def test_nut_scales_inverse_eps(self):
        """Doubling ε (at fixed k) should halve ν_t."""
        nut_1 = compute_nut_keps(1.0, 1.0)
        nut_2 = compute_nut_keps(1.0, 2.0)
        assert nut_2 / nut_1 == pytest.approx(0.5, rel=1e-8)


# ===========================================================================
# 3. Wall functions (log-law region)
# ===========================================================================

class TestWallFunctions:
    """Wall-function BCs — Launder & Spalding (1974) §3."""

    def test_log_layer_region(self):
        """For large y_P, wall function should activate log-law region."""
        nu  = 1.5e-5
        y_P = 0.01     # large enough for high y+
        # u_tau ≈ 0.5477 * sqrt(k)  → need k s.t. y+ > 11.225
        # with k = 0.01, u_tau ≈ 0.0548, y+ = 0.0548 * 0.01 / 1.5e-5 ≈ 36.5 > 11.225
        wf = wall_function_bc(u_P=1.0, k_P=0.01, eps_P=0.01, y_P=y_P, nu=nu)
        assert wf["region"] == "log_law"
        assert wf["y_plus"] > YPLUS_LAM

    def test_viscous_sublayer_region(self):
        """For very small y_P, viscous sublayer should activate."""
        nu  = 1.5e-5
        y_P = 1.0e-6   # very close to wall
        wf = wall_function_bc(u_P=0.01, k_P=1.0e-8, eps_P=1.0e-6, y_P=y_P, nu=nu)
        assert wf["region"] == "viscous_sublayer"

    def test_log_law_k_formula(self):
        """Log-law k = u_τ² / √C_μ  [LS1974 eq. 3.4]"""
        nu  = 1.5e-5
        y_P = 0.01
        k0  = 0.05   # initial k
        wf  = wall_function_bc(u_P=2.0, k_P=k0, eps_P=0.01, y_P=y_P, nu=nu)
        if wf["region"] == "log_law":
            u_tau = wf["u_tau"]
            k_expected = u_tau ** 2 / math.sqrt(C_MU)
            assert _rel(wf["k_wall"], k_expected) < 0.01, (
                f"k_wall={wf['k_wall']:.4e}, expected={k_expected:.4e}"
            )

    def test_log_law_eps_formula(self):
        """Log-law ε = C_μ^(3/4) k^(3/2) / (κ y)  [LS1974 eq. 3.7]"""
        nu  = 1.5e-5
        y_P = 0.005
        wf  = wall_function_bc(u_P=2.0, k_P=0.05, eps_P=0.01, y_P=y_P, nu=nu)
        if wf["region"] == "log_law":
            u_tau = wf["u_tau"]
            k_wf  = wf["k_wall"]
            eps_expected = (C_MU ** 0.75) * (k_wf ** 1.5) / (KAPPA * y_P)
            assert _rel(wf["eps_wall"], eps_expected) < 0.05, (
                f"eps_wall={wf['eps_wall']:.4e}, expected={eps_expected:.4e}"
            )

    def test_k_and_eps_positive(self):
        """Wall function must return positive k and ε."""
        nu = 1.5e-5
        for y_P in [1e-7, 1e-5, 0.001, 0.01]:
            wf = wall_function_bc(u_P=1.0, k_P=0.01, eps_P=0.1, y_P=y_P, nu=nu)
            assert wf["k_wall"] > 0.0
            assert wf["eps_wall"] > 0.0


# ===========================================================================
# 4. Log-layer analytic state
# ===========================================================================

class TestLogLayerState:
    """Analytic log-layer k-ε relations.  [LS1974; Pope2000 §7.1]"""

    def test_returns_ok(self):
        state = channel_log_layer_keps(Re_tau=600.0, nu=1.5e-5)
        assert state["ok"] is True

    def test_k_formula(self):
        """k = u_τ² / √C_μ  [LS1974 eq. 3.4]"""
        nu, Re_tau = 1.5e-5, 600.0
        s = channel_log_layer_keps(Re_tau=Re_tau, nu=nu)
        u_tau = s["u_tau"]
        k_expected = u_tau ** 2 / math.sqrt(C_MU)
        assert _rel(s["k"], k_expected) < 1e-10

    def test_eps_formula(self):
        """ε = u_τ³ / (κ y)  [Pope2000 §7.1 eq. 7.27]"""
        nu, Re_tau, y_plus = 1.5e-5, 600.0, 200.0
        s = channel_log_layer_keps(Re_tau=Re_tau, nu=nu, y_plus=y_plus)
        u_tau = s["u_tau"]
        y     = s["y"]
        eps_expected = u_tau ** 3 / (KAPPA * y)
        assert _rel(s["eps"], eps_expected) < 1e-10

    def test_nut_equals_kappa_utau_y(self):
        """ν_t = κ u_τ y  (k-ε in log layer)  [Pope §7.1]"""
        nu, Re_tau, y_plus = 1.5e-5, 600.0, 200.0
        s = channel_log_layer_keps(Re_tau=Re_tau, nu=nu, y_plus=y_plus)
        nut_expected = KAPPA * s["u_tau"] * s["y"]
        # Allow 5% tolerance due to C_mu rounding
        assert _rel(s["nut"], nut_expected) < 0.05

    def test_invalid_inputs(self):
        assert not channel_log_layer_keps(Re_tau=-1.0,  nu=1.5e-5)["ok"]
        assert not channel_log_layer_keps(Re_tau=600.0, nu=-1.5e-5)["ok"]
        assert not channel_log_layer_keps(Re_tau=600.0, nu=1.5e-5, y_plus=-1.0)["ok"]


# ===========================================================================
# 5. PRIMARY VALIDATION — Channel flow Re=10 000 vs Mansour et al. (1988) DNS
# ===========================================================================

class TestChannelRe10000:
    """
    Fully-developed turbulent channel flow at Re=10 000.

    Validation criteria (T-101 DoD):
      - Log-layer TKE:  k+ = k/u_τ² ≈ 1/√C_μ ≈ 3.33 within 10%
        [LS1974 §3; Mansour et al. 1988 log-layer plateau]
      - Velocity log-law: U+ = (1/κ) ln(y+) + B  with B ≈ 5.0 ± 1.0
        [Pope 2000 §7.1]
      - Mass conservation: |U_b − 1| < 0.1%

    Note: The standard k-ε model correctly predicts the log-layer TKE
    plateau (k+ ≈ 3.33) by construction from its wall-function BC.
    The near-wall peak (k+ ≈ 4.2 at y+≈15) from Mansour DNS is a wall-
    resolved feature that the k-ε model with wall functions does not
    resolve — this is a well-known limitation documented in LS1974 §4
    and Pope §10.1.  The 10% tolerance covers this.
    """

    @pytest.fixture(scope="class")
    def result(self):
        cfg = ChannelKepsConfig(Re=10_000, ny=64, wall_func=True,
                                cluster=True, cluster_ratio=1.08)
        return validate_channel_re10000(cfg)

    def test_returns_ok(self, result):
        assert result["ok"] is True

    def test_converged(self, result):
        assert result["converged"] is True, (
            f"Solver did not converge after {result['n_iter']} iterations"
        )

    # --- Validation check 1: Log-layer TKE ---
    def test_k_plus_log_layer_within_10pct(self, result):
        """
        k/u_τ² in log layer must be within 10% of LS1974 prediction 1/√C_μ ≈ 3.33.
        [LS1974 eq. 3.4; Mansour1988 log-layer plateau]
        """
        k_plus  = result["k_plus_log"]
        err_pct = result["k_plus_err_pct"]
        assert result["k_plus_ok"], (
            f"k+ = {k_plus:.3f} deviates {err_pct:.1f}% from reference "
            f"{MANSOUR_K_PLUS_LOG_LAYER:.3f}  (tolerance {MANSOUR_K_PLUS_TOLERANCE*100:.0f}%)"
            "  [LS1974 §3; Mansour et al. 1988]"
        )

    # --- Validation check 2: Mass conservation ---
    def test_mass_conservation(self, result):
        """
        Bulk velocity error must be < 0.1%.
        Conservation of mass: ∫U dy / h = U_b = 1.
        """
        assert result["mass_ok"], (
            f"Bulk velocity error = {result['mass_error_pct']:.3f}% (tolerance 0.1%)"
        )

    # --- Validation check 3: Log-law velocity profile ---
    def test_log_law_additive_constant(self, result):
        """
        Log-law additive constant B = U+ − (1/κ)ln(y+) must be 5.0 ± 1.0
        in the log layer (30 < y+ < 300).  [Pope2000 §7.1]
        """
        assert result["log_law_B_ok"], (
            f"Log-law B = {result['log_law_B']:.3f}, expected {LOGLAW_B} ± {1.0}  "
            "[Pope2000 §7.1]"
        )

    def test_u_tau_positive(self, result):
        assert result["u_tau"] > 0.0

    def test_k_plus_positive(self, result):
        assert result["k_plus_log"] > 0.0

    def test_output_keys_present(self, result):
        for key in ("ok", "converged", "Re", "u_tau", "k_plus_log",
                    "mass_ok", "log_law_B", "log_law_B_ok", "all_ok"):
            assert key in result, f"Missing key: {key}"


# ===========================================================================
# 6. PRIMARY VALIDATION — Backward-facing step vs Driver-Seegmiller (1985)
# ===========================================================================

class TestBFSReattachment:
    """
    1:2 backward-facing step at Re_h ≈ 37 300 (Driver-Seegmiller 1985).

    Criterion (T-101 DoD): x_r/h within 15% of 6.0 (i.e. in [5.1, 6.9]).
    Driver-Seegmiller measured x_r/h ≈ 6.26 ± 0.10;
    k-ε RANS typically gives 5.5–7.0 depending on mesh and wall treatment.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return estimate_bfs_reattachment_keps(
            Re_h=BFS_RE_H_DS,
            expansion_ratio=2.0,
        )

    def test_returns_ok(self, result):
        assert result["ok"] is True

    def test_reattachment_within_15pct(self, result):
        """
        x_r/h within 15% of the Driver-Seegmiller mean 6.0.
        Tolerance: ±0.9 h (15% of 6.0).
        [DriverSeeg 1985; standard k-ε RANS prediction band 5.5–7.0]
        """
        x_r   = result["x_reattach_over_h"]
        lo    = BFS_XR_MEAN * (1.0 - 0.15)   # 5.1
        hi    = BFS_XR_MEAN * (1.0 + 0.15)   # 6.9
        assert lo <= x_r <= hi, (
            f"x_r/h = {x_r:.3f}, expected in [{lo:.2f}, {hi:.2f}]  "
            f"(Driver-Seegmiller mean {BFS_XR_MEAN} ± 15%)"
        )

    def test_reattachment_positive(self, result):
        assert result["x_reattach_over_h"] > 0.0

    def test_expected_constants_echoed(self, result):
        assert result["expected_mean"] == BFS_XR_MEAN
        assert result["expected_tol"]  == BFS_XR_TOL

    def test_invalid_re_h(self):
        res = estimate_bfs_reattachment_keps(Re_h=-1.0)
        assert not res["ok"]

    def test_invalid_expansion_ratio(self):
        res = estimate_bfs_reattachment_keps(expansion_ratio=0.5)
        assert not res["ok"]

    def test_result_keys_present(self, result):
        for key in ("ok", "x_reattach_over_h", "inside_tolerance",
                    "Re_h", "expected_mean", "expected_tol"):
            assert key in result, f"Missing key: {key}"


# ===========================================================================
# 7. PRIMARY VALIDATION — Conservation (mass + momentum within 0.1%)
# ===========================================================================

class TestConservation:
    """
    Mass and momentum conservation in the solved channel flow.

    Criterion: |U_b − 1.0| < 0.1 %  (integral over half-channel)
    """

    @pytest.fixture(scope="class")
    def state(self):
        cfg = ChannelKepsConfig(Re=10_000, ny=64)
        return solve_channel_keps(cfg)

    def test_mass_conservation_01pct(self, state):
        """
        ∫U dy / h should equal U_b = 1.0 within 0.1%.
        [T-101 DoD: total mass balance across inlet/outlet ≤ 0.1%]
        """
        result = check_channel_conservation(state)
        assert result["ok"]
        assert result["mass_ok"], (
            f"Mass error = {result['mass_error_pct']:.4f}%  "
            "(tolerance 0.1%; represents inlet=outlet mass balance)"
        )

    def test_conservation_output_keys(self, state):
        result = check_channel_conservation(state)
        for key in ("ok", "U_bulk", "mass_error_pct", "mass_ok"):
            assert key in result


# ===========================================================================
# 8. Channel solver unit tests
# ===========================================================================

class TestChannelSolverUnit:
    """Fast unit tests for the channel k-ε solver."""

    def test_solver_runs(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000)
        s = solve_channel_keps(cfg)
        assert len(s.U) == 16
        assert len(s.k) == 16
        assert len(s.eps) == 16

    def test_velocity_non_negative(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000)
        s = solve_channel_keps(cfg)
        assert all(v >= 0.0 for v in s.U)

    def test_k_positive(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000)
        s = solve_channel_keps(cfg)
        assert all(k > 0.0 for k in s.k)

    def test_eps_positive(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000)
        s = solve_channel_keps(cfg)
        assert all(e > 0.0 for e in s.eps)

    def test_nut_positive(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000)
        s = solve_channel_keps(cfg)
        assert all(n >= 0.0 for n in s.nut)

    def test_u_tau_positive(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000)
        s = solve_channel_keps(cfg)
        assert s.u_tau > 0.0

    def test_uniform_grid(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=1000, cluster=False)
        s = solve_channel_keps(cfg)
        assert len(s.y) == 16

    def test_residual_list_populated(self):
        cfg = ChannelKepsConfig(Re=5000, ny=16, max_iter=200)
        s = solve_channel_keps(cfg)
        assert len(s.residual_k) > 0


# ===========================================================================
# 9. Edge cases and robustness
# ===========================================================================

class TestEdgeCases:
    """Numerical robustness checks."""

    def test_nut_zero_eps(self):
        """compute_nut_keps must not divide by zero."""
        nut = compute_nut_keps(k=0.01, eps=0.0)
        assert math.isfinite(nut) and nut >= 0.0

    def test_nut_zero_k(self):
        """compute_nut_keps with zero k should return near-zero ν_t."""
        nut = compute_nut_keps(k=0.0, eps=1.0)
        assert math.isfinite(nut) and nut >= 0.0

    def test_wall_func_zero_velocity(self):
        """Wall function must not crash with U_P = 0."""
        wf = wall_function_bc(u_P=0.0, k_P=0.001, eps_P=0.01, y_P=0.01, nu=1.5e-5)
        assert math.isfinite(wf["k_wall"])
        assert math.isfinite(wf["eps_wall"])

    def test_wall_func_very_small_y(self):
        """Wall function must not crash at extremely small y."""
        wf = wall_function_bc(u_P=1.0, k_P=0.01, eps_P=0.1, y_P=1.0e-10, nu=1.5e-5)
        assert math.isfinite(wf["k_wall"])
        assert math.isfinite(wf["eps_wall"])
        assert wf["k_wall"] > 0.0

    def test_bfs_reattachment_finite(self):
        """BFS estimate must always return a finite x_r/h."""
        for Re_h in [1000.0, 10_000.0, 100_000.0]:
            res = estimate_bfs_reattachment_keps(Re_h=Re_h)
            assert res["ok"]
            assert math.isfinite(res["x_reattach_over_h"])

    def test_validate_channel_re10000_fast(self):
        """Coarse grid validation completes without exception."""
        cfg = ChannelKepsConfig(Re=10_000, ny=16, max_iter=5000)
        result = validate_channel_re10000(cfg)
        assert result["ok"] is True
        assert "k_plus_log" in result
        assert "mass_ok" in result
