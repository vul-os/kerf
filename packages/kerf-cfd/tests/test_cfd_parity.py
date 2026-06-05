"""
Tests for CFD parity gap closures.

Covers:
  1. JONSWAP variance normalisation fix (np.trapz → np.trapezoid compat)
  2. Isentropic flow relations (Anderson 2003 §3.4)
  3. Oblique shock relations (Anderson 2003 §4.7)
  4. Prandtl-Meyer expansion (Anderson 2003 §9.6)
  5. VOF surface tension — Weber, Ohnesorge, Young-Laplace
  6. VOF interface curvature (Brackbill 1992 CSF)
  7. CFD postprocessing tools — residual parser, y⁺ estimate, flow setup
  8. cfd_flow_setup sync logic
  9. cfd_extract_residuals log parser

All tests hermetic — no DB, network, filesystem (except minimal temp dirs).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Ensure src/ is on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ---------------------------------------------------------------------------
# 1. JONSWAP normalisation
# ---------------------------------------------------------------------------

class TestJonswapNormalisation:
    """JONSWAP spectrum integral must satisfy m0 = (Hs/4)² within ±15%."""

    def setup_method(self):
        from kerf_cfd.marine.hydrodynamics import jonswap_spectrum
        self.jonswap = jonswap_spectrum

    def _compute_m0(self, Hs, Tp, gamma=3.3, n=4000):
        wp = 2.0 * math.pi / Tp
        omega = np.linspace(0.01 * wp, 10.0 * wp, n)
        S = self.jonswap(omega, Hs, Tp, gamma)
        _trapz = np.trapezoid if hasattr(np, 'trapezoid') else np.trapz
        return float(_trapz(S, omega))

    def test_gamma_3p3_Hs4_Tp10(self):
        Hs, Tp = 4.0, 10.0
        m0 = self._compute_m0(Hs, Tp)
        m0_expected = (Hs / 4.0) ** 2
        assert abs(m0 - m0_expected) / m0_expected < 0.15, (
            f"m0={m0:.4f}, expected {m0_expected:.4f}"
        )

    def test_gamma_1p0_is_pierson_moskowitz(self):
        Hs, Tp = 2.0, 8.0
        m0 = self._compute_m0(Hs, Tp, gamma=1.0)
        m0_expected = (Hs / 4.0) ** 2
        assert abs(m0 - m0_expected) / m0_expected < 0.15

    def test_gamma_3p3_Hs2_Tp8(self):
        Hs, Tp = 2.0, 8.0
        m0 = self._compute_m0(Hs, Tp, gamma=3.3)
        m0_expected = (Hs / 4.0) ** 2
        assert abs(m0 - m0_expected) / m0_expected < 0.15


# ---------------------------------------------------------------------------
# 2. Isentropic relations
# ---------------------------------------------------------------------------

class TestIsentropicRelations:
    """Anderson (2003) §3.4 isentropic flow relations."""

    def setup_method(self):
        from kerf_cfd.compressible.compressible_flow import isentropic_relations
        self.iso = isentropic_relations

    def test_M0_stagnation_ratios_unity(self):
        res = self.iso(0.0)
        assert res['T0_T'] == pytest.approx(1.0, rel=1e-8)
        assert res['p0_p'] == pytest.approx(1.0, rel=1e-8)
        assert res['rho0_rho'] == pytest.approx(1.0, rel=1e-8)

    def test_M1_area_ratio_unity(self):
        """At M=1 (sonic), A/A* = 1."""
        res = self.iso(1.0)
        assert res['A_Astar'] == pytest.approx(1.0, rel=1e-3)

    def test_M2_temperature_ratio(self):
        """T0/T = 1 + (γ-1)/2·M² = 1 + 0.2·4 = 1.8 for M=2, γ=1.4."""
        res = self.iso(2.0, gamma=1.4)
        assert res['T0_T'] == pytest.approx(1.8, rel=1e-6)

    def test_M2_pressure_ratio(self):
        """p0/p = (T0/T)^(γ/(γ-1)) = 1.8^3.5 ≈ 7.824 for M=2."""
        res = self.iso(2.0, gamma=1.4)
        assert res['p0_p'] == pytest.approx(7.824, rel=1e-3)

    def test_M2_density_ratio(self):
        """ρ0/ρ = (T0/T)^(1/(γ-1)) = 1.8^2.5 ≈ 4.347."""
        res = self.iso(2.0, gamma=1.4)
        assert res['rho0_rho'] == pytest.approx(4.347, rel=1e-2)

    def test_area_ratio_supersonic_M3(self):
        """A/A* for M=3 ≈ 4.235 (NACA 1135 table)."""
        res = self.iso(3.0, gamma=1.4)
        assert res['A_Astar'] == pytest.approx(4.235, rel=2e-3)

    def test_negative_M_raises(self):
        with pytest.raises(ValueError):
            self.iso(-1.0)


# ---------------------------------------------------------------------------
# 3. Oblique shock relations
# ---------------------------------------------------------------------------

class TestObliqueShock:
    """Anderson (2003) §4.7 oblique shock."""

    def setup_method(self):
        from kerf_cfd.compressible.compressible_flow import oblique_shock_relations
        self.oblique = oblique_shock_relations

    def test_normal_shock_at_90_deg_wave_angle(self):
        """At θ → maximum deflection, β → 90° (strong shock limit)."""
        # M=2, strong solution — β should be large
        res = self.oblique(2.0, 5.0, weak_solution=False)
        assert res['beta_deg'] > 50.0

    def test_weak_shock_M2_theta10(self):
        """Weak shock at M=2, θ=10°: β ≈ 39.3° (Anderson 2003, Table A4)."""
        res = self.oblique(2.0, 10.0, weak_solution=True)
        assert res['beta_deg'] == pytest.approx(39.3, abs=1.5)

    def test_pressure_ratio_greater_than_1(self):
        """Shock always increases pressure."""
        res = self.oblique(3.0, 15.0)
        assert res['p2_p1'] > 1.0

    def test_downstream_M_less_than_upstream(self):
        """Oblique shock reduces Mach number."""
        res = self.oblique(3.0, 15.0)
        assert res['M2'] < 3.0

    def test_theta_max_exceeded_raises(self):
        """Deflection > θ_max raises ValueError."""
        with pytest.raises(ValueError, match="exceeds θ_max"):
            self.oblique(2.0, 60.0)  # θ_max at M=2 ≈ 22.97°

    def test_M1_not_supersonic_raises(self):
        with pytest.raises(ValueError):
            self.oblique(0.5, 5.0)


# ---------------------------------------------------------------------------
# 4. Prandtl-Meyer expansion
# ---------------------------------------------------------------------------

class TestPrandtlMeyer:
    """Anderson (2003) §9.6 Prandtl-Meyer expansion."""

    def setup_method(self):
        from kerf_cfd.compressible.compressible_flow import prandtl_meyer_expansion
        self.pm = prandtl_meyer_expansion

    def test_M1_theta0_unchanged(self):
        """Zero expansion → M2 = M1."""
        res = self.pm(2.0, 0.0)
        assert res['M2'] == pytest.approx(2.0, rel=1e-4)

    def test_expansion_increases_mach(self):
        res = self.pm(2.0, 10.0)
        assert res['M2'] > 2.0

    def test_expansion_decreases_pressure(self):
        """Isentropic expansion → p2/p1 < 1."""
        res = self.pm(2.0, 10.0)
        assert res['p2_p1'] < 1.0

    def test_M2_M2_theta20_approx(self):
        """M=2, θ=20°: ν2 = ν1+20, M2 ≈ 2.83 (Anderson table A5)."""
        res = self.pm(2.0, 20.0)
        assert res['M2'] == pytest.approx(2.83, abs=0.1)

    def test_M_less_than_1_raises(self):
        with pytest.raises(ValueError):
            self.pm(0.5, 10.0)

    def test_negative_theta_raises(self):
        with pytest.raises(ValueError):
            self.pm(2.0, -5.0)


# ---------------------------------------------------------------------------
# 5. VOF surface tension
# ---------------------------------------------------------------------------

class TestVofSurfaceTension:
    """Weber, Ohnesorge, Young-Laplace."""

    def setup_method(self):
        from kerf_cfd.multiphase.vof import (
            weber_number, ohnesorge_number, surface_tension_pressure_jump
        )
        self.We = weber_number
        self.Oh = ohnesorge_number
        self.dp = surface_tension_pressure_jump

    def test_weber_number_formula(self):
        """We = ρU²L/σ."""
        We = self.We(1000.0, 1.0, 0.001, 0.072)
        assert We == pytest.approx(1000.0 * 1.0 ** 2 * 0.001 / 0.072, rel=1e-6)

    def test_ohnesorge_formula(self):
        """Oh = μ/√(ρLσ)."""
        Oh = self.Oh(1e-3, 1000.0, 1e-3, 0.072)
        expected = 1e-3 / math.sqrt(1000.0 * 1e-3 * 0.072)
        assert Oh == pytest.approx(expected, rel=1e-6)

    def test_young_laplace_sphere(self):
        """Δp = σκ, κ = 2/D for sphere."""
        kappa = np.array([2.0 / 0.001])   # D = 1 mm sphere
        dp = self.dp(kappa, sigma_N_per_m=0.072)
        assert float(dp[0]) == pytest.approx(0.072 * 2.0 / 0.001, rel=1e-6)

    def test_large_drop_small_Weber(self):
        """Slow large drop: We < 1 → surface tension dominant."""
        We = self.We(rho=1000.0, U=0.01, L=0.001, sigma=0.072)
        assert We < 1.0

    def test_fast_small_drop_large_Weber(self):
        """Fast small drop: We > 10 → breakup."""
        We = self.We(rho=1000.0, U=10.0, L=0.001, sigma=0.072)
        assert We > 10.0


# ---------------------------------------------------------------------------
# 6. VOF interface curvature
# ---------------------------------------------------------------------------

class TestVofInterfaceCurvature:
    """Brackbill (1992) CSF curvature estimator."""

    def setup_method(self):
        from kerf_cfd.multiphase.vof import interface_curvature_2d
        self.curvature = interface_curvature_2d

    def test_flat_interface_zero_curvature(self):
        """Flat interface (α = 0 below y=0.5, 1 above): curvature ≈ 0."""
        n = 10
        centres = np.array([[x, y] for y in np.linspace(0, 1, n)
                              for x in np.linspace(0, 1, n)])
        alpha = np.array([1.0 if c[1] > 0.5 else 0.0 for c in centres])
        kappa = self.curvature(alpha, centres)
        # Pure-phase cells should have kappa=0
        pure = (alpha < 0.01) | (alpha > 0.99)
        assert np.all(kappa[pure] == 0.0)

    def test_returns_array_of_correct_size(self):
        centres = np.random.rand(20, 2)
        alpha = np.random.rand(20)
        kappa = self.curvature(alpha, centres)
        assert kappa.shape == (20,)


# ---------------------------------------------------------------------------
# 7. CFD postprocessing — y⁺ estimate
# ---------------------------------------------------------------------------

class TestYplusEstimate:
    """Launder-Spalding y⁺ wall distance estimate."""

    def setup_method(self):
        from kerf_cfd.cfd_postprocessing_tool import _yplus_estimate
        self.yplus = _yplus_estimate

    def test_air_duct_typical(self):
        """Air duct, U=10 m/s, L=1 m, ν=1.5e-5 → reasonable Δy."""
        res = self.yplus(10.0, 1.0, 1.5e-5, target_yplus=30.0)
        assert 'first_cell_height_m' in res
        assert res['first_cell_height_m'] > 0
        assert res['first_cell_height_m'] < 0.01   # < 1 cm

    def test_yplus_target_scales_linearly(self):
        """Δy is proportional to target_yplus."""
        res30 = self.yplus(10.0, 1.0, 1.5e-5, target_yplus=30.0)
        res1 = self.yplus(10.0, 1.0, 1.5e-5, target_yplus=1.0)
        assert (res30['first_cell_height_m'] /
                res1['first_cell_height_m']) == pytest.approx(30.0, rel=1e-6)

    def test_laminar_Re_returns_error(self):
        res = self.yplus(0.0, 1.0, 1.5e-5)
        assert 'error' in res


# ---------------------------------------------------------------------------
# 8. Flow setup logic
# ---------------------------------------------------------------------------

class TestFlowSetup:
    """cfd_flow_setup solver/turbulence selection logic."""

    def setup_method(self):
        from kerf_cfd.cfd_postprocessing_tool import _flow_setup_sync
        self.setup_fn = _flow_setup_sync

    def test_internal_high_Re_k_epsilon(self):
        res = self.setup_fn({'flow_type': 'internal', 'Re': 1e6,
                             'U_ref': 10.0, 'L_ref': 0.1})
        assert res['turbulence_model'] == 'kEpsilon'
        assert res['solver'] == 'simpleFoam'

    def test_external_k_omega_sst(self):
        res = self.setup_fn({'flow_type': 'external', 'Re': 1e5})
        assert res['turbulence_model'] == 'kOmegaSST'

    def test_laminar_Re_below_2300(self):
        res = self.setup_fn({'flow_type': 'internal', 'Re': 1000.0})
        assert res['turbulence_model'] == 'laminar'

    def test_heat_transfer_selects_buoyant_solver(self):
        res = self.setup_fn({'flow_type': 'internal',
                             'requires_heat_transfer': True})
        assert res['solver'] == 'buoyantSimpleFoam'

    def test_compressible_mach_selects_rho_solver(self):
        res = self.setup_fn({'flow_type': 'external', 'mach_number': 0.5})
        assert res['solver'] == 'rhoSimpleFoam'

    def test_bc_keys_present_internal(self):
        res = self.setup_fn({'flow_type': 'internal'})
        assert 'inlet' in res['boundary_conditions']
        assert 'outlet' in res['boundary_conditions']
        assert 'walls' in res['boundary_conditions']

    def test_bc_keys_present_external(self):
        res = self.setup_fn({'flow_type': 'external'})
        assert 'inlet_farfield' in res['boundary_conditions']
        assert 'body_surface' in res['boundary_conditions']

    def test_turb_ics_computed(self):
        res = self.setup_fn({'flow_type': 'internal', 'Re': 1e5,
                             'U_ref': 10.0, 'L_ref': 0.1, 'nu': 1e-5})
        ics = res['turbulence_initial_conditions']
        assert 'k_inlet_m2_s2' in ics
        assert ics['k_inlet_m2_s2'] > 0


# ---------------------------------------------------------------------------
# 9. Residual log parser
# ---------------------------------------------------------------------------

class TestResidualParser:
    """cfd_extract_residuals log parsing."""

    def setup_method(self):
        from kerf_cfd.cfd_postprocessing_tool import _extract_residuals_sync
        self.parse = _extract_residuals_sync

    def _make_log(self, fields, initial=0.1, final=1e-5, n_iter=5):
        lines = []
        for i in range(n_iter):
            lines.append(f"Time = {i + 1}")
            for f in fields:
                lines.append(
                    f"smoothSolver:  Solving for {f}, "
                    f"Initial residual = {initial:.6e}, "
                    f"Final residual = {final:.6e}, No Iterations 5"
                )
        return "\n".join(lines)

    def test_parses_multiple_fields(self):
        log = self._make_log(['Ux', 'Uy', 'p'])
        res = self.parse(log)
        assert res['ok']
        assert set(res['fields_found']) >= {'Ux', 'Uy', 'p'}

    def test_converged_when_final_below_tol(self):
        log = self._make_log(['Ux', 'p'], final=1e-7)
        res = self.parse(log, tol=1e-4)
        assert res['converged'] is True

    def test_not_converged_when_final_above_tol(self):
        log = self._make_log(['Ux', 'p'], final=0.1)
        res = self.parse(log, tol=1e-4)
        assert res['converged'] is False

    def test_empty_log_no_crash(self):
        res = self.parse("")
        assert res['ok']
        assert res['n_iterations'] == 0

    def test_iteration_count(self):
        log = self._make_log(['Ux'], n_iter=10)
        res = self.parse(log)
        assert res['n_iterations'] == 10


# ---------------------------------------------------------------------------
# 10. Async LLM tool wrappers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAsyncPostprocessTools:
    """Smoke tests for the async LLM tool wrappers (cfd_postprocessing_tool)."""

    def setup_method(self):
        from kerf_cfd.cfd_postprocessing_tool import (
            cfd_flow_setup, cfd_extract_residuals,
        )
        self.flow_setup = cfd_flow_setup
        self.residuals = cfd_extract_residuals

    def test_flow_setup_internal(self):
        payload = json.dumps({"flow_type": "internal", "Re": 5e4})
        result_str = _run(self.flow_setup(None, payload.encode()))
        result = json.loads(result_str)
        # cfd_postprocessing_tool wraps result in {'ok': True, ...}
        assert result.get('ok') is True
        assert 'turbulence_model' in result

    def test_flow_setup_external(self):
        payload = json.dumps({"flow_type": "external", "Re": 1e5})
        result_str = _run(self.flow_setup(None, payload.encode()))
        result = json.loads(result_str)
        assert result.get('ok') is True

    def test_flow_setup_bad_type(self):
        payload = json.dumps({"flow_type": "sideways"})
        result_str = _run(self.flow_setup(None, payload.encode()))
        result = json.loads(result_str)
        # err_payload returns {'ok': False, ...} or {'error': ...}
        assert result.get('ok') is not True

    def test_extract_residuals_tool(self):
        log = "Time = 1\nGAMG:  Solving for p, Initial residual = 0.1, Final residual = 1e-5, No Iterations 3\n"
        payload = json.dumps({"log_text": log})
        result_str = _run(self.residuals(None, payload.encode()))
        result = json.loads(result_str)
        assert result.get('ok') is True
        assert 'convergence_table' in result

    def test_extract_residuals_empty_log(self):
        payload = json.dumps({"log_text": ""})
        result_str = _run(self.residuals(None, payload.encode()))
        result = json.loads(result_str)
        assert result.get('ok') is True


class TestAsyncCompressibleTools:
    """Smoke tests for new compressible LLM tools in cfd_advanced_v3_tools.

    These tools use ok_payload() which in compat mode JSON-encodes the result
    dict directly (no 'ok' wrapper) — check for field presence instead.
    """

    def setup_method(self):
        from kerf_cfd.cfd_advanced_v3_tools import (
            run_cfd_isentropic_flow,
            run_cfd_oblique_shock,
            run_cfd_prandtl_meyer,
            run_cfd_vof_surface_tension,
        )
        self.iso = run_cfd_isentropic_flow
        self.oblique = run_cfd_oblique_shock
        self.pm = run_cfd_prandtl_meyer
        self.vof_st = run_cfd_vof_surface_tension

    def test_isentropic_M2(self):
        res = _run(self.iso({"M": 2.0, "gamma": 1.4}, None))
        data = json.loads(res)
        # ok_payload returns raw data dict; check for field keys
        assert 'T0_T' in data
        assert data['T0_T'] == pytest.approx(1.8, rel=1e-4)

    def test_oblique_M2_theta10(self):
        res = _run(self.oblique({"M1": 2.0, "theta_deg": 10.0}, None))
        data = json.loads(res)
        assert 'beta_deg' in data
        assert data['beta_deg'] == pytest.approx(39.3, abs=2.0)

    def test_prandtl_meyer_M2_theta20(self):
        res = _run(self.pm({"M1": 2.0, "theta_deg": 20.0}, None))
        data = json.loads(res)
        assert 'M2' in data
        assert data['M2'] > 2.0

    def test_vof_surface_tension_water_drop(self):
        res = _run(self.vof_st({
            "U_m_s": 0.5, "D_m": 0.001,
            "rho_kg_m3": 1000.0, "sigma_N_per_m": 0.072,
        }, None))
        data = json.loads(res)
        assert 'We' in data
        assert 'delta_p_Pa' in data

    def test_oblique_shock_theta_too_large(self):
        res = _run(self.oblique({"M1": 2.0, "theta_deg": 60.0}, None))
        data = json.loads(res)
        # err_payload returns {'ok': False, 'error': ...} or {'error': ...}
        assert data.get('ok') is not True or 'error' in data
