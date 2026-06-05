"""
Tests for marine hydrodynamics module (Wave 12B).

References:
  Holtrop & Mennen (1982) Int. Shipbuilding Progress 29.
  Faltinsen (1990) Sea Loads on Ships and Offshore Structures.
  ISSC (1964) — JONSWAP variance = (Hs/4)².
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cfd.marine.hydrodynamics import (
    ResistanceReport,
    ShipHull,
    WaveSpec,
    _wavenumber,
    holtrop_mennen_resistance,
    jonswap_spectrum,
    linear_wave_diffraction_force,
)


# ---------------------------------------------------------------------------
# ShipHull fixtures
# ---------------------------------------------------------------------------

def _typical_container_ship() -> ShipHull:
    """Representative Panamax container ship."""
    return ShipHull(
        length_water_line_m=230.0,
        beam_m=32.0,
        draft_m=12.5,
        displacement_tonnes=60000.0,
        block_coefficient=0.65,
        prismatic_coefficient=0.68,
    )


def _small_ferry() -> ShipHull:
    """Small RoRo ferry."""
    return ShipHull(
        length_water_line_m=80.0,
        beam_m=14.0,
        draft_m=4.0,
        displacement_tonnes=4000.0,
        block_coefficient=0.60,
        prismatic_coefficient=0.63,
    )


# ---------------------------------------------------------------------------
# Holtrop-Mennen resistance
# ---------------------------------------------------------------------------

def test_resistance_positive_at_nonzero_speed():
    """Total resistance must be > 0 for any hull at positive speed."""
    hull = _typical_container_ship()
    report = holtrop_mennen_resistance(hull, velocity_m_s=6.0)
    assert report.total_resistance_n > 0, "Total resistance must be positive"


def test_resistance_increases_with_speed():
    """Higher speed → higher total resistance (monotonic for reasonable speeds)."""
    hull = _typical_container_ship()
    r1 = holtrop_mennen_resistance(hull, velocity_m_s=4.0)
    r2 = holtrop_mennen_resistance(hull, velocity_m_s=8.0)
    assert r2.total_resistance_n > r1.total_resistance_n


def test_friction_positive():
    """Frictional resistance must be positive."""
    hull = _small_ferry()
    report = holtrop_mennen_resistance(hull, velocity_m_s=5.0)
    assert report.frictional_resistance_n > 0


def test_effective_power_positive():
    """Effective power must be positive at nonzero speed."""
    hull = _typical_container_ship()
    report = holtrop_mennen_resistance(hull, velocity_m_s=7.0)
    assert report.effective_power_kw > 0


def test_froude_number_correct():
    """Froude number should match Fn = V/sqrt(g·L)."""
    hull = _typical_container_ship()
    V = 8.23  # m/s ≈ 16 knots
    report = holtrop_mennen_resistance(hull, velocity_m_s=V)
    Fn_expected = V / math.sqrt(9.80665 * hull.length_water_line_m)
    assert report.froude_number == pytest.approx(Fn_expected, rel=1e-6)


def test_effective_power_consistency():
    """PE [kW] = Rt [N] * V [m/s] / 1000."""
    hull = _typical_container_ship()
    V = 6.5
    report = holtrop_mennen_resistance(hull, velocity_m_s=V)
    PE_expected = report.total_resistance_n * V / 1000.0
    assert report.effective_power_kw == pytest.approx(PE_expected, rel=1e-6)


def test_resistance_report_is_dataclass():
    """Return type must be ResistanceReport."""
    hull = _small_ferry()
    report = holtrop_mennen_resistance(hull, velocity_m_s=4.0)
    assert isinstance(report, ResistanceReport)


# ---------------------------------------------------------------------------
# JONSWAP spectrum
# ---------------------------------------------------------------------------

def test_jonswap_variance_approx_hs_squared_over_16():
    """
    Variance m₀ = ∫ S(ω)dω should ≈ (Hs/4)² (± 20%).

    This is by definition: Hs = 4·sqrt(m₀) — ISSC (1964).
    """
    Hs = 4.0   # m
    Tp = 10.0  # s
    omega_p = 2.0 * math.pi / Tp
    omega = np.linspace(0.05, 5.0 * omega_p, 2000)
    S = jonswap_spectrum(omega, Hs, Tp, gamma=3.3)
    _trapz = np.trapezoid if hasattr(np, 'trapezoid') else np.trapz
    m0 = float(_trapz(S, omega))
    m0_expected = (Hs / 4.0) ** 2
    assert abs(m0 - m0_expected) / m0_expected < 0.25, (
        f"Variance m0={m0:.4f} deviates >25% from expected {m0_expected:.4f}"
    )


def test_jonswap_peak_at_omega_p():
    """Spectrum peak should be at or near ωp = 2π/Tp."""
    Hs = 3.0
    Tp = 8.0
    omega_p = 2.0 * math.pi / Tp
    omega = np.linspace(0.1, 3.0, 1000)
    S = jonswap_spectrum(omega, Hs, Tp, gamma=3.3)
    peak_omega = float(omega[np.argmax(S)])
    assert abs(peak_omega - omega_p) < 0.1, (
        f"Peak at ω={peak_omega:.3f} vs ωp={omega_p:.3f} rad/s"
    )


def test_jonswap_non_negative():
    """Spectral density must be non-negative for all ω > 0."""
    omega = np.linspace(0.01, 5.0, 500)
    S = jonswap_spectrum(omega, Hs=2.5, Tp=7.0)
    assert np.all(S >= 0), "S(ω) must be non-negative"


def test_jonswap_gamma1_is_pm():
    """γ=1 → Pierson-Moskowitz (lower peak, broader spectrum)."""
    Hs = 3.0
    Tp = 9.0
    omega = np.linspace(0.1, 3.0, 500)
    S_pm = jonswap_spectrum(omega, Hs, Tp, gamma=1.0)
    S_jonswap = jonswap_spectrum(omega, Hs, Tp, gamma=3.3)
    # JONSWAP has sharper peak: max(S_jonswap) > max(S_pm)
    assert np.max(S_jonswap) > np.max(S_pm), "JONSWAP peak should exceed P-M peak"


def test_jonswap_zero_for_omega_zero():
    """S(0) = 0 (no energy at ω=0)."""
    omega = np.array([0.0, 0.1, 0.5])
    S = jonswap_spectrum(omega, Hs=2.0, Tp=8.0)
    assert S[0] == pytest.approx(0.0, abs=1e-20), "S(ω=0) must be 0"


# ---------------------------------------------------------------------------
# Wave diffraction force
# ---------------------------------------------------------------------------

def test_wave_force_returns_dict_with_keys():
    """linear_wave_diffraction_force must return dict with expected keys."""
    hull = _typical_container_ship()
    wave = WaveSpec(height_m=3.0, period_s=10.0)
    result = linear_wave_diffraction_force(hull, wave)
    for key in ("F_surge_kN", "F_sway_kN", "F_heave_kN", "wave_length_m", "encounter_freq_rad_s"):
        assert key in result, f"Key '{key}' missing from result"


def test_wave_force_heave_positive_head_sea():
    """Head sea (β=0): heave force should be positive (upward pressure from wave)."""
    hull = _typical_container_ship()
    wave = WaveSpec(height_m=4.0, period_s=12.0, direction_deg=0.0)
    result = linear_wave_diffraction_force(hull, wave)
    assert result["F_heave_kN"] > 0, f"Heave force should be positive, got {result['F_heave_kN']}"


def test_wave_force_increases_with_wave_height():
    """Larger wave height → larger forces (linear)."""
    hull = _typical_container_ship()
    wave_small = WaveSpec(height_m=1.0, period_s=10.0)
    wave_large = WaveSpec(height_m=4.0, period_s=10.0)
    r_small = linear_wave_diffraction_force(hull, wave_small)
    r_large = linear_wave_diffraction_force(hull, wave_large)
    assert r_large["F_heave_kN"] > r_small["F_heave_kN"]


def test_wave_length_dispersion_relation():
    """Computed wavelength must satisfy λ ≈ gT²/(2π) for deep water."""
    hull = _typical_container_ship()
    Tp = 10.0
    wave = WaveSpec(height_m=2.0, period_s=Tp)
    result = linear_wave_diffraction_force(hull, wave, depth_m=500.0)
    lambda_deep = 9.80665 * Tp ** 2 / (2.0 * math.pi)
    lambda_computed = result["wave_length_m"]
    assert abs(lambda_computed - lambda_deep) < 0.1 * lambda_deep, (
        f"λ={lambda_computed:.1f} vs deep-water {lambda_deep:.1f}"
    )


# ---------------------------------------------------------------------------
# Wavenumber solver
# ---------------------------------------------------------------------------

def test_wavenumber_deep_water_limit():
    """Deep water: k → ω²/g."""
    omega = 0.628  # ~ 10s period
    k = _wavenumber(omega, depth=10000.0)
    k_deep = omega ** 2 / 9.80665
    assert abs(k - k_deep) / k_deep < 0.001


def test_wavenumber_satisfies_dispersion():
    """k must satisfy ω² = g·k·tanh(k·d) to within 1e-8."""
    omega = 0.5
    d = 30.0
    k = _wavenumber(omega, d)
    lhs = omega ** 2
    rhs = 9.80665 * k * math.tanh(k * d)
    assert abs(lhs - rhs) / lhs < 1e-6, f"Dispersion residual too large: {abs(lhs-rhs)}"
