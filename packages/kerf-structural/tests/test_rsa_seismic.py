"""
Tests for ASCE 7-22 Response-Spectrum Analysis (RSA) and Newmark-β integration.

Sources
-------
kerf_cad_core.seismic.rsa — pure-Python RSA engine.

Oracle values
-------------
build_asce7_spectrum:
  SDS=1.0g, SD1=0.6g → T0=0.12s, Ts=0.60s (ASCE 7-22 §11.4.5).
  Sa at T=0 → 0.4×SDS = 0.4g.  Sa at T=Ts → SDS = 1.0g.  Sa at T=1.2s → SD1/T = 0.5g.

rsa_sdof:
  ωn=2π rad/s (Tn=1.0s), SDS=1.0g, SD1=0.6g.
  T=1.0s is in the constant-velocity region (Ts<T<TL):
  Sa = SD1/T = 0.6/1.0 = 0.6g = 0.6×9.80665 = 5.884 m/s².
  Sd = Sa/ωn² = 5.884/(4π²) ≈ 0.1491 m.

rsa_mdof:
  2-DOF system, 2 modes, SRSS.
  Mode 1: ωn=6.28 rad/s (T=1.0s), Mode 2: ωn=18.85 rad/s (T=0.333s).
  Masses m=[50000, 50000] kg.  Both modes compact (phi=[1,1] normalized).
  Sa_1 = SD1/T_1 = 0.6/1.0 = 0.6g; Sa_2 = SDS = 1.0g (T_2 < Ts for default SDS/SD1).
  Combined base shear ≈ SRSS of per-mode shears.

newmark_sdof:
  Undamped SDOF under sinusoidal forcing at resonance: u_peak ≈ A·t/(2·ωn) grows
  linearly — can verify peak > A/ωn² (quasi-static).

All quantities in SI (m, kg, N, rad/s, s).
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.seismic.rsa import (
    build_asce7_spectrum,
    rsa_sdof,
    rsa_mdof,
    newmark_sdof,
    newmark_mdof,
)

_g = 9.80665  # m/s²

# ===========================================================================
# Helpers
# ===========================================================================

def _quick_spectrum(SDS: float = 1.0, SD1: float = 0.6, TL: float = 6.0):
    """Build a default ASCE 7-22 spectrum — used by many tests."""
    res = build_asce7_spectrum(SDS, SD1, TL=TL, n_points=200)
    assert res["ok"], f"build_asce7_spectrum failed: {res}"
    return [(pt[0], pt[1]) for pt in res["spectrum"]]


# ===========================================================================
# build_asce7_spectrum
# ===========================================================================

class TestBuildAsce7Spectrum:
    def test_returns_ok(self):
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6)
        assert r["ok"]

    def test_T0_and_Ts_formula(self):
        """T0 = 0.2·SD1/SDS; Ts = SD1/SDS (ASCE 7-22 §11.4.5)."""
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6)
        assert r["ok"]
        assert r["T0"] == pytest.approx(0.2 * 0.6 / 1.0, rel=1e-6)  # 0.12s
        assert r["Ts"] == pytest.approx(0.6 / 1.0, rel=1e-6)           # 0.60s

    def test_plateau_value_equals_SDS(self):
        """In plateau region (T0 ≤ T ≤ Ts), Sa = SDS = 1.0g."""
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6, n_points=200)
        assert r["ok"]
        # Find point nearest T=0.4s (between T0=0.12 and Ts=0.60)
        spec = r["spectrum"]
        matches = [sa for T, sa in spec if abs(T - 0.4) < 0.05]
        assert matches, "No point near T=0.4s in spectrum"
        assert matches[0] == pytest.approx(1.0, rel=0.005)

    def test_Sa_at_T0_equals_SDS(self):
        """At exactly Ts the plateau Sa = SDS."""
        r = build_asce7_spectrum(SDS=0.8, SD1=0.4)
        Ts = r["Ts"]
        spec = r["spectrum"]
        matches = [sa for T, sa in spec if abs(T - Ts) < 0.01]
        assert matches, f"No point near Ts={Ts}"
        assert matches[0] == pytest.approx(0.8, rel=0.01)

    def test_constant_velocity_region(self):
        """At T≈1.2s (> Ts=0.6s, < TL=6s): Sa = SD1/T = 0.6/1.2 = 0.5g.
        Allow 5% tolerance because nearest grid point may be T=1.17 or T=1.23."""
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6, TL=6.0, n_points=400)
        spec = r["spectrum"]
        matches = [(T, sa) for T, sa in spec if 1.1 < T < 1.3]
        assert matches, "No spectrum point in 1.1–1.3s range"
        T_found, sa = matches[0]
        # In constant-velocity region: Sa = SD1/T
        expected = 0.6 / T_found
        assert sa == pytest.approx(expected, rel=0.01)

    def test_long_period_region(self):
        """At T=8s (> TL=6s): Sa = SD1·TL/T² = 0.6×6/64 = 0.05625g."""
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6, TL=6.0, n_points=400)
        spec = r["spectrum"]
        sa = next((sa for T, sa in spec if abs(T - 8.0) < 0.1), None)
        if sa is not None:
            expected = 0.6 * 6.0 / 8.0 ** 2
            assert sa == pytest.approx(expected, rel=0.05)

    def test_spectrum_sorted_ascending(self):
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6)
        spec = r["spectrum"]
        Ts = [pt[0] for pt in spec]
        assert all(Ts[i] <= Ts[i + 1] for i in range(len(Ts) - 1))

    def test_Sa_at_T0_positive(self):
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6)
        assert all(sa > 0 for T, sa in r["spectrum"] if T > 0)

    def test_returns_n_points_approx(self):
        r = build_asce7_spectrum(SDS=1.0, SD1=0.6, n_points=100)
        # spectrum may have extra key points injected
        assert len(r["spectrum"]) >= 100

    def test_invalid_SDS_zero(self):
        r = build_asce7_spectrum(SDS=0, SD1=0.6)
        assert not r["ok"]

    def test_invalid_SD1_zero(self):
        r = build_asce7_spectrum(SDS=1.0, SD1=0)
        assert not r["ok"]

    def test_SD1_gt_SDS_warning(self):
        """SD1 > SDS: unusual but not invalid — should produce a warning."""
        r = build_asce7_spectrum(SDS=0.3, SD1=0.6)
        assert r["ok"]
        assert len(r["warnings"]) > 0


# ===========================================================================
# rsa_sdof
# ===========================================================================

class TestRsaSdof:
    def _spec(self):
        return _quick_spectrum(SDS=1.0, SD1=0.6)

    def test_returns_ok(self):
        r = rsa_sdof(omega_n=2 * math.pi, zeta=0.05, spectrum_pts=self._spec())
        assert r["ok"]

    def test_Tn_from_omega(self):
        """Tn = 2π/ωn = 1.0s for ωn = 2π."""
        r = rsa_sdof(omega_n=2 * math.pi, zeta=0.05, spectrum_pts=self._spec())
        assert r["T_n"] == pytest.approx(1.0, rel=1e-5)

    def test_Sa_in_velocity_region(self):
        """Tn=1.0s in constant-velocity region: Sa = SD1/T = 0.6g."""
        r = rsa_sdof(omega_n=2 * math.pi, zeta=0.05, spectrum_pts=self._spec())
        assert r["ok"]
        assert r["Sa_g"] == pytest.approx(0.6, rel=0.01)

    def test_Sa_ms2_conversion(self):
        """Sa_ms2 = Sa_g × g."""
        r = rsa_sdof(omega_n=2 * math.pi, zeta=0.05, spectrum_pts=self._spec())
        assert r["Sa_ms2"] == pytest.approx(r["Sa_g"] * _g, rel=1e-6)

    def test_Sd_from_Sa_omega(self):
        """Sd = Sa_ms2 / ωn²."""
        omega = 2 * math.pi
        r = rsa_sdof(omega_n=omega, zeta=0.05, spectrum_pts=self._spec())
        Sa_ms2 = r["Sa_ms2"]
        expected_Sd = Sa_ms2 / (omega ** 2)
        assert r["Sd_m"] == pytest.approx(expected_Sd, rel=1e-6)

    def test_Sd_oracle_value(self):
        """
        Tn=1.0s, SDS=1.0g, SD1=0.6g:
        Sa = 0.6g = 0.6×9.80665 = 5.8840 m/s².
        ωn = 2π → Sd = 5.8840/(4π²) ≈ 0.1491 m.
        """
        r = rsa_sdof(omega_n=2 * math.pi, zeta=0.05, spectrum_pts=self._spec())
        expected_Sd = 0.6 * _g / (2 * math.pi) ** 2
        assert r["Sd_m"] == pytest.approx(expected_Sd, rel=0.01)

    def test_peak_force_m_times_Sa(self):
        """peak_force_N = m × Sa_ms2."""
        m = 50_000  # kg
        r = rsa_sdof(omega_n=2 * math.pi, zeta=0.05, spectrum_pts=self._spec(), m=m)
        expected = m * r["Sa_ms2"]
        assert r["peak_force_N"] == pytest.approx(expected, rel=1e-5)

    def test_high_freq_near_plateau(self):
        """ωn=50 rad/s → Tn≈0.126s (near T0=0.12s): Sa close to SDS=1.0g."""
        r = rsa_sdof(omega_n=50.0, zeta=0.05, spectrum_pts=self._spec())
        assert r["ok"]
        # T=0.126 ≈ T0=0.12s → just entering plateau or at plateau end
        # Sa should be ≥ 0.90 × SDS (1.0 g)
        assert r["Sa_g"] >= 0.90

    def test_invalid_omega_zero(self):
        r = rsa_sdof(omega_n=0, zeta=0.05, spectrum_pts=self._spec())
        assert not r["ok"]

    def test_invalid_zeta_ge1(self):
        r = rsa_sdof(omega_n=6.28, zeta=1.0, spectrum_pts=self._spec())
        assert not r["ok"]

    def test_empty_spectrum_fails(self):
        r = rsa_sdof(omega_n=6.28, zeta=0.05, spectrum_pts=[])
        assert not r["ok"]


# ===========================================================================
# rsa_mdof
# ===========================================================================

class TestRsaMdof:
    def _spec(self):
        return _quick_spectrum(SDS=1.0, SD1=0.6)

    def test_returns_ok_2dof(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[0.707, 1.0], [-1.0, 0.707]],
            gamma_list=[1.2, 0.3],
            zeta_list=[0.05, 0.05],
            m_list=[50000, 50000],
            spectrum_pts=spec,
            method="CQC",
        )
        assert r["ok"], r

    def test_n_modes_n_dofs(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[1.0, 0.0], [0.0, 1.0]],
            gamma_list=[1.0, 1.0],
            zeta_list=[0.05, 0.05],
            m_list=[1000, 1000],
            spectrum_pts=spec,
        )
        assert r["ok"]
        assert r["n_modes"] == 2
        assert r["n_dofs"] == 2

    def test_srss_vs_cqc_close_frequencies(self):
        """SRSS and CQC should give similar results when modes are well-separated."""
        spec = self._spec()
        kw = dict(
            omega_list=[6.28, 62.8],  # far-apart modes
            phi_list=[[1.0, 0.0], [0.0, 1.0]],
            gamma_list=[1.0, 1.0],
            zeta_list=[0.05, 0.05],
            m_list=[1000, 1000],
            spectrum_pts=spec,
        )
        r_srss = rsa_mdof(**kw, method="SRSS")
        r_cqc  = rsa_mdof(**kw, method="CQC")
        assert r_srss["ok"] and r_cqc["ok"]
        # For well-separated modes CQC ≈ SRSS (correlation → 0)
        assert r_srss["base_shear_N"] == pytest.approx(r_cqc["base_shear_N"], rel=0.05)

    def test_base_shear_positive(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[1.0, 0.0], [0.0, 1.0]],
            gamma_list=[1.0, 0.5],
            zeta_list=[0.05, 0.05],
            m_list=[10000, 10000],
            spectrum_pts=spec,
        )
        assert r["ok"]
        assert r["base_shear_N"] > 0

    def test_combined_disp_has_n_dofs_entries(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[1.0, 0.5], [0.3, 1.0]],
            gamma_list=[1.0, 0.4],
            zeta_list=[0.05, 0.05],
            m_list=[5000, 5000],
            spectrum_pts=spec,
        )
        assert r["ok"]
        assert len(r["combined_disp_m"]) == 2

    def test_overturning_moment_with_h_list(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[1.0, 0.0], [0.0, 1.0]],
            gamma_list=[1.0, 0.5],
            zeta_list=[0.05, 0.05],
            m_list=[10000, 10000],
            spectrum_pts=spec,
            h_list=[3.0, 6.0],
        )
        assert r["ok"]
        assert r["base_moment_Nm"] is not None
        assert r["base_moment_Nm"] > 0

    def test_overturning_moment_without_h_list(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28],
            phi_list=[[1.0]],
            gamma_list=[1.0],
            zeta_list=[0.05],
            m_list=[10000],
            spectrum_pts=spec,
        )
        assert r["ok"]
        assert r["base_moment_Nm"] is None

    def test_invalid_empty_omega(self):
        r = rsa_mdof([], [], [], [], [], spectrum_pts=self._spec())
        assert not r["ok"]

    def test_invalid_phi_length_mismatch(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[1.0], [0.0, 1.0]],  # inconsistent n_dofs
            gamma_list=[1.0, 1.0],
            zeta_list=[0.05, 0.05],
            m_list=[1000, 1000],
            spectrum_pts=spec,
        )
        assert not r["ok"]

    def test_per_mode_Sa_g_list_length(self):
        spec = self._spec()
        r = rsa_mdof(
            omega_list=[6.28, 18.85],
            phi_list=[[1.0, 0.0], [0.0, 1.0]],
            gamma_list=[1.0, 0.5],
            zeta_list=[0.05, 0.05],
            m_list=[1000, 1000],
            spectrum_pts=spec,
        )
        assert r["ok"]
        assert len(r["mode_Sa_g"]) == 2

    def test_sdof_mode_shear_vs_single_mode(self):
        """1-DOF, 1-mode RSA: mode_shear = m × Gamma × Sa × phi."""
        spec = self._spec()
        m = 10_000
        gamma = 1.0
        phi = [1.0]
        omega = 2 * math.pi  # Tn=1s → Sa=0.6g in velocity region

        r = rsa_mdof(
            omega_list=[omega],
            phi_list=[phi],
            gamma_list=[gamma],
            zeta_list=[0.05],
            m_list=[m],
            spectrum_pts=spec,
        )
        assert r["ok"]
        expected_Sa_ms2 = 0.6 * _g   # Sa=0.6g for Tn=1s
        expected_shear = m * phi[0] * gamma * expected_Sa_ms2
        assert r["mode_shear_N"][0] == pytest.approx(expected_shear, rel=0.01)


# ===========================================================================
# newmark_sdof
# ===========================================================================

class TestNewmarkSdof:
    def _harmonic_ag(self, omega_force: float = 2 * math.pi,
                     A: float = 0.3 * _g, N: int = 500, dt: float = 0.01):
        """Harmonic ground acceleration at frequency omega_force."""
        return [A * math.sin(omega_force * i * dt) for i in range(N)]

    def test_returns_ok(self):
        ag = self._harmonic_ag()
        r = newmark_sdof(m=10000, k=10000 * (2 * math.pi) ** 2, zeta=0.05,
                         ag_time=ag, dt=0.01)
        assert r["ok"]

    def test_undamped_resonance_grows(self):
        """
        Undamped SDOF at resonance: |u_peak| should exceed quasi-static response
        A/ωn² = 0.3g / ωn² (grows approximately linearly for first few cycles).
        """
        omega_n = 4.0  # rad/s
        A = 0.3 * _g
        dt = 0.005
        N = int(20 * 2 * math.pi / omega_n / dt)  # 20 cycles
        ag = [A * math.sin(omega_n * i * dt) for i in range(N)]
        r = newmark_sdof(m=1.0, k=omega_n ** 2, zeta=0.0, ag_time=ag, dt=dt)
        assert r["ok"]
        quasi_static = A / omega_n ** 2
        # After 20 cycles resonant peak >> quasi-static
        assert r["peak_u_m"] > 2 * quasi_static

    def test_peak_u_positive(self):
        ag = self._harmonic_ag()
        r = newmark_sdof(m=10000, k=100000, zeta=0.05, ag_time=ag, dt=0.01)
        assert r["ok"]
        assert r["peak_u_m"] >= 0

    def test_Tn_formula(self):
        """Tn = 2π√(m/k)."""
        m, k = 1000.0, 40000.0
        r = newmark_sdof(m=m, k=k, zeta=0.05, ag_time=[0.0, 0.0], dt=0.01)
        assert r["ok"]
        expected_Tn = 2 * math.pi * math.sqrt(m / k)
        assert r["T_n"] == pytest.approx(expected_Tn, rel=1e-6)

    def test_zero_excitation_zero_response(self):
        """Zero ground acceleration → zero displacement."""
        ag = [0.0] * 200
        r = newmark_sdof(m=5000, k=500000, zeta=0.05, ag_time=ag, dt=0.01)
        assert r["ok"]
        assert r["peak_u_m"] == pytest.approx(0.0, abs=1e-12)

    def test_higher_damping_lower_peak(self):
        """Higher ζ → smaller peak displacement at resonance."""
        omega_n = 4.0
        A = 0.2 * _g
        dt = 0.005
        N = int(15 * 2 * math.pi / omega_n / dt)
        ag = [A * math.sin(omega_n * i * dt) for i in range(N)]
        r_lo = newmark_sdof(m=1.0, k=omega_n ** 2, zeta=0.02, ag_time=ag, dt=dt)
        r_hi = newmark_sdof(m=1.0, k=omega_n ** 2, zeta=0.20, ag_time=ag, dt=dt)
        assert r_lo["ok"] and r_hi["ok"]
        assert r_hi["peak_u_m"] < r_lo["peak_u_m"]

    def test_invalid_m_zero(self):
        r = newmark_sdof(m=0, k=1000, zeta=0.05, ag_time=[0, 0], dt=0.01)
        assert not r["ok"]

    def test_invalid_k_negative(self):
        r = newmark_sdof(m=1000, k=-100, zeta=0.05, ag_time=[0, 0], dt=0.01)
        assert not r["ok"]

    def test_invalid_dt_zero(self):
        r = newmark_sdof(m=1000, k=1000, zeta=0.05, ag_time=[0, 0], dt=0)
        assert not r["ok"]

    def test_ag_single_point_fails(self):
        r = newmark_sdof(m=1000, k=1000, zeta=0.05, ag_time=[1.0], dt=0.01)
        assert not r["ok"]

    def test_coarse_dt_warning(self):
        """dt > Tn/10 should produce a warning."""
        omega_n = 10.0  # Tn ≈ 0.63s; dt = 0.1 > Tn/10 = 0.063
        ag = [0.1 * _g] * 100
        r = newmark_sdof(m=1.0, k=omega_n ** 2, zeta=0.05, ag_time=ag, dt=0.1)
        assert r["ok"]
        assert any("coarse" in w.lower() or "dt" in w.lower() for w in r["warnings"])

    def test_output_arrays_correct_length(self):
        ag = [0.01 * _g * math.sin(i * 0.1) for i in range(300)]
        r = newmark_sdof(m=5000, k=50000, zeta=0.05, ag_time=ag, dt=0.01)
        assert r["ok"]
        assert len(r["u"]) == 300
        assert len(r["v"]) == 300
        assert len(r["t"]) == 300


# ===========================================================================
# newmark_mdof
# ===========================================================================

class TestNewmarkMdof:
    def test_returns_ok_2dof(self):
        M_diag = [1000.0, 1000.0]
        K = [[2000.0, -1000.0], [-1000.0, 1000.0]]
        ag = [0.1 * _g * math.sin(0.5 * i * 0.02) for i in range(200)]
        r = newmark_mdof(M_diag=M_diag, K=K, zeta_list=[0.05, 0.05], ag_time=ag, dt=0.02)
        assert r["ok"], r

    def test_peak_u_phys_length(self):
        M_diag = [500.0, 500.0]
        K = [[1000.0, -500.0], [-500.0, 500.0]]
        ag = [0.0] * 100
        r = newmark_mdof(M_diag=M_diag, K=K, zeta_list=[0.05], ag_time=ag, dt=0.02)
        assert r["ok"]
        assert len(r["peak_u_phys"]) == 2

    def test_zero_excitation_zero_response(self):
        M_diag = [1000.0, 1000.0]
        K = [[2000.0, -1000.0], [-1000.0, 1000.0]]
        ag = [0.0] * 100
        r = newmark_mdof(M_diag=M_diag, K=K, zeta_list=[0.05], ag_time=ag, dt=0.01)
        assert r["ok"]
        assert all(abs(p) < 1e-10 for p in r["peak_u_phys"])

    def test_n_modes_used_equals_n_dofs(self):
        M_diag = [1000.0, 1000.0]
        K = [[2000.0, -1000.0], [-1000.0, 1000.0]]
        ag = [0.0, 0.0]
        r = newmark_mdof(M_diag=M_diag, K=K, zeta_list=[0.05], ag_time=ag, dt=0.01)
        assert r["ok"]
        assert r["n_modes_used"] == 2

    def test_invalid_empty_M(self):
        r = newmark_mdof(M_diag=[], K=[], zeta_list=[0.05], ag_time=[0, 0], dt=0.01)
        assert not r["ok"]

    def test_invalid_K_wrong_shape(self):
        r = newmark_mdof(
            M_diag=[1000.0, 1000.0],
            K=[[2000.0]],  # wrong shape
            zeta_list=[0.05],
            ag_time=[0, 0],
            dt=0.01,
        )
        assert not r["ok"]
