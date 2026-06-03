"""
Tests for kerf_cfd.wind_engineering — building wind loads and bluff-body aerodynamics.

Covers:
  - WindProfile velocity profile (ASCE 7-22 Table 26.10-1)
  - compute_wind_load_aerodynamic pressures and forces
  - vortex_shedding_frequency (Bearman 1984)
  - galloping_critical_velocity (Den Hartog)
  - Input validation edge cases

References
----------
ASCE 7-22 Chapters 26–31 (Wind Loads).
Bearman, P.W. (1984). Ann. Rev. Fluid Mech. 16, 195–222.
Holmes, J.D. (2018). "Wind Loading of Structures," 3rd ed. CRC Press.
"""

from __future__ import annotations

import math

import pytest

from kerf_cfd.wind_engineering.wind_tunnel import (
    BuildingGeometry,
    WindProfile,
    WindPressureReport,
    compute_wind_load_aerodynamic,
    galloping_critical_velocity,
    vortex_shedding_frequency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _square_building(side_m: float = 30.0, height_m: float = 30.0) -> BuildingGeometry:
    """30×30×30 m building (default)."""
    h = side_m / 2.0
    return BuildingGeometry(
        name="test_building",
        footprint_polygon=[(-h, -h), (h, -h), (h, h), (-h, h)],
        height_m=height_m,
        roof_type="flat",
    )


def _exposure_c_20ms() -> WindProfile:
    return WindProfile(exposure="C", reference_velocity_m_s=20.0)


# ---------------------------------------------------------------------------
# WindProfile
# ---------------------------------------------------------------------------

def test_wind_profile_at_reference_height():
    """velocity_at(10m) should return approximately reference_velocity."""
    wp = WindProfile(exposure="C", reference_velocity_m_s=20.0)
    v = wp.velocity_at(10.0)
    assert abs(v - 20.0) < 0.5, f"Expected ~20 m/s at 10m, got {v}"


def test_wind_profile_increases_with_height():
    """For Exposure C, velocity at 100 m > velocity at 10 m."""
    wp = _exposure_c_20ms()
    assert wp.velocity_at(100.0) > wp.velocity_at(10.0)


def test_wind_profile_exposure_b_steeper_gradient():
    """
    Exposure B (α=0.25) has a steeper power-law gradient than C (α=0.143).
    The ratio v(100m)/v(10m) is higher for B than C because the larger
    exponent magnifies height variation.

    Note: ASCE 7-22 basic wind speeds are defined at Exposure C; when the same
    reference speed is applied to B, the profile rises faster with height.
    """
    wp_b = WindProfile(exposure="B", reference_velocity_m_s=20.0)
    wp_c = WindProfile(exposure="C", reference_velocity_m_s=20.0)
    ratio_b = wp_b.velocity_at(100.0) / wp_b.velocity_at(10.0)
    ratio_c = wp_c.velocity_at(100.0) / wp_c.velocity_at(10.0)
    assert ratio_b > ratio_c, (
        f"Exposure B (α=0.25) should have steeper gradient than C (α=0.143): "
        f"ratio_B={ratio_b:.3f}, ratio_C={ratio_c:.3f}"
    )


def test_wind_profile_exposure_d_flatter_gradient():
    """
    Exposure D (α=0.111) has a flatter power-law gradient than C (α=0.143)
    because open-water terrain is smoother — the velocity profile is more
    uniform with height.  The ratio v(100m)/v(10m) is lower for D than C.
    """
    wp_d = WindProfile(exposure="D", reference_velocity_m_s=20.0)
    wp_c = WindProfile(exposure="C", reference_velocity_m_s=20.0)
    ratio_d = wp_d.velocity_at(100.0) / wp_d.velocity_at(10.0)
    ratio_c = wp_c.velocity_at(100.0) / wp_c.velocity_at(10.0)
    assert ratio_d < ratio_c, (
        f"Exposure D (α=0.111) should have flatter gradient than C (α=0.143): "
        f"ratio_D={ratio_d:.3f}, ratio_C={ratio_c:.3f}"
    )


def test_wind_profile_invalid_exposure():
    """Unknown exposure category must raise ValueError."""
    wp = WindProfile(exposure="Z", reference_velocity_m_s=20.0)
    with pytest.raises(ValueError, match="exposure"):
        wp.velocity_at(10.0)


def test_wind_profile_zero_height_clipped():
    """velocity_at(0) should not crash — height clipped to 0.5 m."""
    wp = _exposure_c_20ms()
    v = wp.velocity_at(0.0)
    assert v > 0.0


# ---------------------------------------------------------------------------
# compute_wind_load_aerodynamic
# ---------------------------------------------------------------------------

def test_wind_load_30m_building_returns_report():
    """30m square building with 20 m/s wind should return a WindPressureReport."""
    building = _square_building(30.0, 30.0)
    wind = _exposure_c_20ms()
    report = compute_wind_load_aerodynamic(building, wind)
    assert isinstance(report, WindPressureReport)


def test_wind_load_windward_positive():
    """Windward face pressure must be positive (pushing in)."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.mean_pressure_pa["windward"] > 0.0


def test_wind_load_leeward_negative():
    """Leeward face pressure must be negative (suction)."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.mean_pressure_pa["leeward"] < 0.0


def test_wind_load_side_negative():
    """Side face pressures must be negative (suction)."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.mean_pressure_pa["side_left"] < 0.0


def test_wind_load_roof_negative():
    """Flat roof pressure must be negative (uplift suction)."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.mean_pressure_pa["roof"] < 0.0


def test_wind_load_drag_coefficient_positive():
    """Drag coefficient must be positive."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.drag_coefficient > 0.0


def test_wind_load_cd_asce_order_of_magnitude():
    """For a rectangular building, Cd should be in range [0.5, 2.5] per ASCE 7-22."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert 0.5 <= report.drag_coefficient <= 2.5, (
        f"Cd = {report.drag_coefficient:.3f} outside expected range [0.5, 2.5]"
    )


def test_wind_load_base_shear_positive():
    """Base shear must be positive [kN]."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.base_shear_kn > 0.0


def test_wind_load_overturning_moment_positive():
    """Overturning moment must be positive [kN·m]."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert report.overturning_moment_kn_m > 0.0


def test_wind_load_taller_building_higher_forces():
    """A taller building should produce higher base shear (more area + higher v)."""
    wind = _exposure_c_20ms()
    report_30 = compute_wind_load_aerodynamic(_square_building(30.0, 30.0), wind)
    report_60 = compute_wind_load_aerodynamic(_square_building(30.0, 60.0), wind)
    assert report_60.base_shear_kn > report_30.base_shear_kn


def test_wind_load_pressure_order():
    """Mean windward |p| should be ≥ mean leeward |p| (Cp +0.8 vs −0.5)."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    assert abs(report.mean_pressure_pa["windward"]) >= abs(report.mean_pressure_pa["leeward"])


def test_wind_load_zero_height_raises():
    """Building with height 0 should raise ValueError."""
    building = BuildingGeometry(
        name="zero", footprint_polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        height_m=0.0,
    )
    with pytest.raises(ValueError):
        compute_wind_load_aerodynamic(building, _exposure_c_20ms())


def test_wind_load_peak_greater_than_mean():
    """Peak pressures must exceed mean pressures in magnitude."""
    report = compute_wind_load_aerodynamic(_square_building(), _exposure_c_20ms())
    for face in ("windward", "leeward", "side_left", "roof"):
        mean_abs = abs(report.mean_pressure_pa[face])
        peak_abs = abs(report.peak_pressure_pa[face])
        assert peak_abs > mean_abs, (
            f"Peak pressure for '{face}' ({peak_abs:.1f} Pa) "
            f"should exceed mean ({mean_abs:.1f} Pa)"
        )


# ---------------------------------------------------------------------------
# vortex_shedding_frequency
# ---------------------------------------------------------------------------

def test_vortex_shedding_2hz():
    """f_s = St·v/D = 0.2×10/1 = 2.0 Hz (Bearman 1984)."""
    f = vortex_shedding_frequency(body_width_m=1.0, velocity_m_s=10.0, strouhal_number=0.2)
    assert abs(f - 2.0) < 1e-9, f"Expected 2.0 Hz, got {f}"


def test_vortex_shedding_scales_with_velocity():
    """Doubling velocity should double shedding frequency."""
    f1 = vortex_shedding_frequency(1.0, 10.0)
    f2 = vortex_shedding_frequency(1.0, 20.0)
    assert abs(f2 / f1 - 2.0) < 1e-9


def test_vortex_shedding_scales_inversely_with_width():
    """Doubling width should halve shedding frequency."""
    f1 = vortex_shedding_frequency(1.0, 10.0)
    f2 = vortex_shedding_frequency(2.0, 10.0)
    assert abs(f2 / f1 - 0.5) < 1e-9


def test_vortex_shedding_zero_velocity():
    """Zero velocity → zero shedding frequency."""
    f = vortex_shedding_frequency(body_width_m=1.0, velocity_m_s=0.0)
    assert f == 0.0


def test_vortex_shedding_invalid_width():
    """Non-positive width should raise ValueError."""
    with pytest.raises(ValueError):
        vortex_shedding_frequency(body_width_m=0.0, velocity_m_s=10.0)


# ---------------------------------------------------------------------------
# galloping_critical_velocity
# ---------------------------------------------------------------------------

def test_galloping_velocity_positive():
    """galloping_critical_velocity must return a positive m/s value."""
    building = _square_building(30.0, 30.0)
    v_cr = galloping_critical_velocity(building, damping_ratio=0.02)
    assert v_cr > 0.0, f"Galloping critical velocity should be positive, got {v_cr}"


def test_galloping_higher_damping_higher_critical_velocity():
    """More damping → higher galloping onset velocity."""
    building = _square_building(30.0, 30.0)
    v1 = galloping_critical_velocity(building, damping_ratio=0.01)
    v2 = galloping_critical_velocity(building, damping_ratio=0.05)
    assert v2 > v1, (
        f"Higher damping should give higher v_cr: {v1:.2f} vs {v2:.2f}"
    )


def test_galloping_taller_building_lower_natural_frequency():
    """Taller buildings have lower f_n → lower galloping critical velocity."""
    b_short = _square_building(30.0, 30.0)
    b_tall  = _square_building(30.0, 150.0)
    v_short = galloping_critical_velocity(b_short)
    v_tall  = galloping_critical_velocity(b_tall)
    # Taller → lower f_n → lower v_cr (Den Hartog proportional to ω_n)
    assert v_tall < v_short, (
        f"Taller building should have lower galloping v_cr: "
        f"short={v_short:.2f}, tall={v_tall:.2f}"
    )
