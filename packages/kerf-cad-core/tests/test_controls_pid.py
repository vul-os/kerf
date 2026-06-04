"""
Tests for kerf_cad_core.controls.pid_tuning

Coverage:
  PidParams construction + defaults
  step_pid — basic step, anti-windup
  ziegler_nichols_open_loop — positive Kp, Ki, Kd
  ziegler_nichols_closed_loop — positive gains
  imc_tuning — IMC formula verification
  lambda_tuning — alias equivalence

References: Ziegler & Nichols (1942); Skogestad (2003); Åström & Hägglund (2006).
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.controls.pid_tuning import (
    PidParams,
    step_pid,
    ziegler_nichols_open_loop,
    ziegler_nichols_closed_loop,
    imc_tuning,
    lambda_tuning,
)


# ---------------------------------------------------------------------------
# 1. PidParams
# ---------------------------------------------------------------------------

class TestPidParams:
    def test_construction_basic(self):
        p = PidParams(Kp=1.0, Ki=0.1, Kd=0.01)
        assert p.Kp == 1.0
        assert p.Ki == 0.1
        assert p.Kd == 0.01

    def test_default_setpoint(self):
        p = PidParams(Kp=1.0, Ki=0.0, Kd=0.0)
        assert p.setpoint == 0.0

    def test_output_limits_default(self):
        p = PidParams(Kp=1.0, Ki=0.0, Kd=0.0)
        lo, hi = p.output_limits
        assert lo < 0 and hi > 0

    def test_invalid_limits_raises(self):
        with pytest.raises(ValueError):
            PidParams(Kp=1.0, Ki=0.0, Kd=0.0, output_limits=(10.0, 5.0))


# ---------------------------------------------------------------------------
# 2. step_pid
# ---------------------------------------------------------------------------

class TestStepPid:
    def test_proportional_output_equals_error(self):
        """Kp=1, Ki=0, Kd=0, setpoint=1, measurement=0 → output ≈ 1."""
        params = PidParams(Kp=1.0, Ki=0.0, Kd=0.0, setpoint=1.0)
        output, _ = step_pid({}, params, measurement=0.0, dt=0.1)
        assert abs(output - 1.0) < 1e-10

    def test_zero_error(self):
        """setpoint == measurement → output == 0 for P-only."""
        params = PidParams(Kp=5.0, Ki=0.0, Kd=0.0, setpoint=0.5)
        output, _ = step_pid({}, params, measurement=0.5, dt=0.1)
        assert abs(output) < 1e-10

    def test_integral_accumulates(self):
        """With Ki>0, integral term grows across multiple steps."""
        params = PidParams(Kp=0.0, Ki=1.0, Kd=0.0, setpoint=1.0)
        state = {}
        total_out = 0.0
        for _ in range(5):
            out, state = step_pid(state, params, measurement=0.0, dt=0.1)
            total_out = out
        # After 5 steps: integral ≈ 5 * 0.1 * 1 = 0.5
        assert total_out > 0.0

    def test_output_clamping(self):
        """Output is clamped to output_limits."""
        params = PidParams(
            Kp=1000.0, Ki=0.0, Kd=0.0, setpoint=1.0,
            output_limits=(-1.0, 1.0)
        )
        output, _ = step_pid({}, params, measurement=0.0, dt=0.1)
        assert output <= 1.0

    def test_state_carries_prev_error(self):
        """new_state contains prev_error equal to current error."""
        params = PidParams(Kp=1.0, Ki=0.0, Kd=0.0, setpoint=2.0)
        _, new_state = step_pid({}, params, measurement=0.5, dt=0.1)
        assert abs(new_state["prev_error"] - 1.5) < 1e-10

    def test_initial_empty_state(self):
        """Empty state dict is valid (initial call)."""
        params = PidParams(Kp=1.0, Ki=0.0, Kd=0.0)
        output, state = step_pid({}, params, measurement=0.0, dt=0.01)
        assert "integral" in state
        assert "prev_error" in state


# ---------------------------------------------------------------------------
# 3. Ziegler-Nichols open-loop
# ---------------------------------------------------------------------------

class TestZNOpenLoop:
    def test_returns_pid_params(self):
        result = ziegler_nichols_open_loop(K_process=1.0, tau=10.0, theta=1.0)
        assert isinstance(result, PidParams)

    def test_positive_gains(self):
        """All gains must be positive for positive-gain process."""
        result = ziegler_nichols_open_loop(K_process=2.0, tau=5.0, theta=0.5)
        assert result.Kp > 0
        assert result.Ki > 0
        assert result.Kd > 0

    def test_formula_kp(self):
        """Kp = 1.2 * tau / (K * theta)."""
        K, tau, theta = 1.0, 10.0, 2.0
        result = ziegler_nichols_open_loop(K, tau, theta)
        expected_Kp = 1.2 * tau / (K * theta)
        assert abs(result.Kp - expected_Kp) < 1e-10

    def test_invalid_zero_K_raises(self):
        with pytest.raises(ValueError):
            ziegler_nichols_open_loop(K_process=0.0, tau=5.0, theta=1.0)

    def test_invalid_zero_tau_raises(self):
        with pytest.raises(ValueError):
            ziegler_nichols_open_loop(K_process=1.0, tau=0.0, theta=1.0)


# ---------------------------------------------------------------------------
# 4. Ziegler-Nichols closed-loop
# ---------------------------------------------------------------------------

class TestZNClosedLoop:
    def test_returns_pid_params(self):
        result = ziegler_nichols_closed_loop(K_u=2.0, T_u=10.0)
        assert isinstance(result, PidParams)

    def test_positive_gains(self):
        result = ziegler_nichols_closed_loop(K_u=3.0, T_u=5.0)
        assert result.Kp > 0
        assert result.Ki > 0
        assert result.Kd > 0

    def test_formula_kp(self):
        """Kp = 0.6 * Ku."""
        Ku, Tu = 4.0, 8.0
        result = ziegler_nichols_closed_loop(Ku, Tu)
        assert abs(result.Kp - 0.6 * Ku) < 1e-10


# ---------------------------------------------------------------------------
# 5. IMC tuning
# ---------------------------------------------------------------------------

class TestImcTuning:
    def test_returns_pid_params(self):
        result = imc_tuning(K_process=1.0, tau=10.0, theta=1.0, lambda_c=2.0)
        assert isinstance(result, PidParams)

    def test_formula_kp(self):
        """Kp = tau / (K * (lambda_c + theta))."""
        K, tau, theta, lam = 2.0, 5.0, 1.0, 3.0
        result = imc_tuning(K, tau, theta, lam)
        expected = tau / (K * (lam + theta))
        assert abs(result.Kp - expected) < 1e-10

    def test_positive_gains(self):
        result = imc_tuning(K_process=1.0, tau=8.0, theta=0.5, lambda_c=1.0)
        assert result.Kp > 0
        assert result.Ki > 0
        assert result.Kd > 0


# ---------------------------------------------------------------------------
# 6. Lambda tuning
# ---------------------------------------------------------------------------

class TestLambdaTuning:
    def test_alias_matches_imc(self):
        """lambda_tuning is an alias for imc_tuning."""
        K, tau, theta, tau_c = 1.5, 6.0, 0.8, 2.0
        r1 = imc_tuning(K, tau, theta, tau_c)
        r2 = lambda_tuning(K, tau, theta, tau_c)
        assert abs(r1.Kp - r2.Kp) < 1e-12
        assert abs(r1.Ki - r2.Ki) < 1e-12
        assert abs(r1.Kd - r2.Kd) < 1e-12
