"""
Tests for kerf_systems DAE/ODE solver.

Oracle 1: RC circuit step response — Vout(t) = Vin*(1 - e^(-t/tau)) within 1%
Oracle 2: Mass-spring-damper free response — e^(-zeta*wn*t)*cos(wd*t) within 2% over 5s
"""

from __future__ import annotations

import math
import pytest


def _rel_err(actual: float, expected: float) -> float:
    if abs(expected) < 1e-12:
        return abs(actual - expected)
    return abs(actual - expected) / abs(expected)


# ---------------------------------------------------------------------------
# Basic solver unit tests
# ---------------------------------------------------------------------------

class TestSolverBasic:
    def test_exponential_decay_explicit(self):
        """dx/dt = -x → x(t) = exp(-t); check at t=1 to 1% tolerance."""
        from kerf_systems.solver.dae import solve_system

        def F(t, x, dx):
            return [dx[0] + x[0]]  # dx[0] - (-x[0]) = 0 → explicit ODE path

        result = solve_system(F, (0.0, 2.0), [1.0])
        assert result.converged
        x_final = result.x[-1][0]
        x_analytic = math.exp(-2.0)
        assert _rel_err(x_final, x_analytic) < 0.01

    def test_constant_source(self):
        """dx/dt = 1 → x(t) = t; check at t=5."""
        from kerf_systems.solver.dae import solve_system

        def F(t, x, dx):
            return [dx[0] - 1.0]

        result = solve_system(F, (0.0, 5.0), [0.0])
        assert result.converged
        x_final = result.x[-1][0]
        assert _rel_err(x_final, 5.0) < 0.01

    def test_simresult_structure(self):
        from kerf_systems.solver.dae import solve_system, SimResult

        def F(t, x, dx):
            return [dx[0] + x[0]]

        result = solve_system(F, (0.0, 1.0), [1.0])
        assert isinstance(result, SimResult)
        assert len(result.t) == len(result.x)
        assert len(result.t) > 1
        assert all(len(row) == 1 for row in result.x)


# ---------------------------------------------------------------------------
# Oracle 1: RC circuit step response
# ---------------------------------------------------------------------------

class TestRCStepResponse:
    """
    Series RC circuit: C*dv/dt = i, v + R*i = V0
    Analytic: v_C(t) = V0 * (1 - exp(-t/(R*C)))
    Tolerance: 1% relative error at t = tau, 2*tau, 3*tau.
    """

    @pytest.mark.parametrize("R, C, V0", [
        (1e3, 1e-6, 1.0),    # tau = 1 ms
        (10e3, 100e-9, 5.0), # tau = 1 ms, higher voltage
        (1e6, 1e-9, 12.0),   # tau = 1 ms, high R
    ])
    def test_rc_step(self, R, C, V0):
        from kerf_systems.solver.dae import solve_system

        tau = R * C

        def F_rc(t, x, dx):
            v_C, i = x[0], x[1]
            dv_C = dx[0]
            return [C * dv_C - i, v_C + R * i - V0]

        t_end = 5 * tau
        h = tau / 500
        result = solve_system(F_rc, (0.0, t_end), [0.0, V0 / R],
                               dx0=[V0 / (R * C), 0.0], h=h)
        assert result.converged, f"RC solver not converged: {result.warnings}"

        for n_tau in [1, 2, 3]:
            t_check = n_tau * tau
            idx = min(range(len(result.t)), key=lambda i: abs(result.t[i] - t_check))
            t_act = result.t[idx]
            v_sim = result.x[idx][0]
            v_ana = V0 * (1.0 - math.exp(-t_act / tau))
            err = _rel_err(v_sim, v_ana)
            assert err < 0.01, (
                f"RC(R={R},C={C},V0={V0}) at {n_tau}*tau: "
                f"sim={v_sim:.6f}, analytic={v_ana:.6f}, err={err*100:.3f}%"
            )

    def test_rc_final_voltage(self):
        """At t >> tau, v_C → V0."""
        from kerf_systems.solver.dae import solve_system

        R, C, V0 = 1e3, 1e-6, 5.0
        tau = R * C

        def F_rc(t, x, dx):
            return [C * dx[0] - x[1], x[0] + R * x[1] - V0]

        result = solve_system(F_rc, (0.0, 10 * tau), [0.0, V0 / R],
                               dx0=[V0 / (R * C), 0.0], h=tau / 200)
        v_final = result.x[-1][0]
        assert _rel_err(v_final, V0) < 0.01, f"Final v_C={v_final:.4f}, V0={V0}"


# ---------------------------------------------------------------------------
# Oracle 2: Mass-spring-damper free response
# ---------------------------------------------------------------------------

class TestMassSpringDamperOracle:
    """
    Damped 2nd-order: m*q'' + b*q' + k*q = 0
    Analytic (underdamped): q(t) = q0 * e^(-zeta*wn*t) * cos(wd*t)
    where zeta = b/(2*sqrt(m*k)), wn = sqrt(k/m), wd = wn*sqrt(1-zeta^2)

    Tolerance: 2% relative error at multiple sample points over 5 s.
    """

    @pytest.mark.parametrize("m, k, b, q0", [
        (1.0, 4.0, 0.5, 1.0),    # zeta ≈ 0.125 (lightly damped)
        (2.0, 8.0, 1.0, 0.5),    # same zeta, scaled
        (1.0, 9.0, 0.6, 2.0),    # zeta = 0.1
    ])
    def test_damped_response(self, m, k, b, q0):
        from kerf_systems.solver.dae import solve_system

        wn = math.sqrt(k / m)
        zeta = b / (2.0 * math.sqrt(m * k))
        assert zeta < 1.0, "Test requires underdamped system"
        wd = wn * math.sqrt(1.0 - zeta ** 2)

        def F_msd(t, x, dx):
            q, v = x[0], x[1]
            dq, dv = dx[0], dx[1]
            return [dq - v, m * dv + b * v + k * q]

        t_end = 5.0
        h = (2 * math.pi / wn) / 500

        result = solve_system(
            F_msd, (0.0, t_end),
            [q0, 0.0],
            dx0=[0.0, -(b * 0.0 + k * q0) / m],
            h=h,
        )
        assert result.converged, f"MSD solver not converged: {result.warnings}"

        # Correct analytic solution for v0=0:
        # q(t) = q0 * exp(-zeta*wn*t) * [cos(wd*t) + (zeta*wn/wd)*sin(wd*t)]
        # The task description e^(-zeta*wn*t)*cos(wd*t) is the envelope shape, but
        # the full solution with v0=0 also has a sin term. Use the exact formula.
        def q_analytic(t_s: float) -> float:
            return q0 * math.exp(-zeta * wn * t_s) * (
                math.cos(wd * t_s) + (zeta * wn / wd) * math.sin(wd * t_s)
            )

        # Sample at t = 0.5, 1.0, 2.0, 3.0, 5.0 s (within t_end)
        sample_times = [t for t in [0.5, 1.0, 2.0, 3.0, 5.0] if t <= t_end]
        for t_s in sample_times:
            idx = min(range(len(result.t)), key=lambda i: abs(result.t[i] - t_s))
            t_act = result.t[idx]
            q_sim = result.x[idx][0]
            q_ana = q_analytic(t_act)
            err = _rel_err(q_sim, q_ana)
            # Allow 2% relative error; for very small values use absolute
            if abs(q_ana) > 0.01 * q0:
                assert err < 0.02, (
                    f"MSD(m={m},k={k},b={b},q0={q0}) at t={t_act:.2f}: "
                    f"sim={q_sim:.6f}, analytic={q_ana:.6f}, err={err*100:.3f}%"
                )

    def test_undamped_period(self):
        """Undamped mass-spring period T = 2*pi*sqrt(m/k) to 1%."""
        from kerf_systems.solver.dae import solve_system

        m, k = 1.0, 4.0
        T_analytic = 2 * math.pi * math.sqrt(m / k)

        def F_ms(t, x, dx):
            q, v = x[0], x[1]
            return [dx[0] - v, m * dx[1] + k * q]

        t_end = 2 * T_analytic
        h = T_analytic / 1000

        result = solve_system(F_ms, (0.0, t_end), [1.0, 0.0],
                               dx0=[0.0, -k * 1.0 / m], h=h)
        assert result.converged

        q_arr = [row[0] for row in result.x]
        t_arr = result.t

        # Find two consecutive positive-going zero crossings
        zero_xings = []
        for i in range(1, len(t_arr)):
            if q_arr[i - 1] < 0 and q_arr[i] >= 0:
                t0_, t1_ = t_arr[i - 1], t_arr[i]
                q0_, q1_ = q_arr[i - 1], q_arr[i]
                t_x = t0_ - q0_ * (t1_ - t0_) / (q1_ - q0_)
                zero_xings.append(t_x)
            if len(zero_xings) == 2:
                break

        if len(zero_xings) < 2:
            pytest.skip("Could not find two zero crossings — increase t_end")

        T_sim = zero_xings[1] - zero_xings[0]
        err = _rel_err(T_sim, T_analytic)
        assert err < 0.01, (
            f"Undamped period: sim={T_sim:.4f}, analytic={T_analytic:.4f}, err={err*100:.2f}%"
        )


# ---------------------------------------------------------------------------
# Modelica end-to-end integration
# ---------------------------------------------------------------------------

class TestModelicaEndToEnd:
    def test_rc_via_parser(self):
        """Parse RC model → integrate → V_C(tau) ≈ V0*(1-1/e) within 1%."""
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        from kerf_systems.solver.dae import solve_system

        src = """
        model RCStep
          parameter Real R = 1000.0;
          parameter Real C = 0.001;
          parameter Real V0 = 5.0;
          Real v_C(start = 0.0);
          Real i(start = 0.005);
        equation
          der(v_C) = i / C;
          v_C + R * i = V0;
        end RCStep;
        """
        m = parse_model(src)
        F, x0, dx0, var_names, params = build_dae_problem(m)

        R, C, V0 = params["R"], params["C"], params["V0"]
        tau = R * C
        t_end = 3 * tau
        h = tau / 500

        result = solve_system(F, (0.0, t_end), x0, dx0, h=h)
        assert result.converged

        idx = min(range(len(result.t)), key=lambda i: abs(result.t[i] - tau))
        v_C_idx = var_names.index("v_C")
        v_sim = result.x[idx][v_C_idx]
        v_ana = V0 * (1.0 - math.exp(-1.0))
        err = _rel_err(v_sim, v_ana)
        assert err < 0.01, (
            f"Modelica RC: v_C(tau)={v_sim:.4f}, analytic={v_ana:.4f}, err={err*100:.2f}%"
        )

    def test_msd_via_parser(self):
        """Parse MSD model → integrate → envelope matches e^(-zeta*wn*t) within 2%."""
        from kerf_systems.parser.mo_parser import parse_model, build_dae_problem
        from kerf_systems.solver.dae import solve_system

        src = """
        model MSD
          parameter Real m = 1.0;
          parameter Real k = 4.0;
          parameter Real b = 0.5;
          Real q(start = 1.0);
          Real v(start = 0.0);
        equation
          der(q) = v;
          der(v) = -(b * v + k * q) / m;
        end MSD;
        """
        m = parse_model(src)
        F, x0, dx0, var_names, params = build_dae_problem(m)

        mp = params["m"]
        kp = params["k"]
        bp = params["b"]
        wn = math.sqrt(kp / mp)
        zeta = bp / (2.0 * math.sqrt(mp * kp))
        wd = wn * math.sqrt(1.0 - zeta ** 2)

        t_end = 5.0
        h = (2 * math.pi / wn) / 500
        result = solve_system(F, (0.0, t_end), x0, dx0, h=h)
        assert result.converged

        q_idx = var_names.index("q")
        # Correct analytic for q0=1, v0=0:
        # q(t) = exp(-zeta*wn*t) * [cos(wd*t) + (zeta*wn/wd)*sin(wd*t)]
        def q_analytic(t_s: float) -> float:
            return math.exp(-zeta * wn * t_s) * (
                math.cos(wd * t_s) + (zeta * wn / wd) * math.sin(wd * t_s)
            )

        # Sample at t=1, 2, 3, 4, 5
        for t_s in [1.0, 2.0, 3.0, 4.0, 5.0]:
            idx = min(range(len(result.t)), key=lambda i: abs(result.t[i] - t_s))
            t_act = result.t[idx]
            q_sim = result.x[idx][q_idx]
            q_ana = q_analytic(t_act)
            if abs(q_ana) > 0.01:
                err = _rel_err(q_sim, q_ana)
                assert err < 0.02, (
                    f"MSD at t={t_act:.1f}: sim={q_sim:.5f}, analytic={q_ana:.5f}, "
                    f"err={err*100:.2f}%"
                )
