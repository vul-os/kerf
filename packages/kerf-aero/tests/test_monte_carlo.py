"""Tests for monte_carlo.py — Monte Carlo trajectory dispersion analysis."""

from __future__ import annotations

import math
import pytest

from kerf_aero.monte_carlo import (
    NominalInputs,
    DispersionInputs,
    monte_carlo_dispersion,
    MonteCarloResult,
)


class TestMonteCarlo:
    """Validate Monte Carlo dispersion analysis statistics."""

    def test_basic_run_returns_result(self):
        """Basic MC run returns a MonteCarloResult with correct sample count."""
        nom = NominalInputs(
            total_impulse_ns=640.0,
            burn_time_s=1.7,
            initial_mass_kg=0.7,
            propellant_mass_kg=0.12,
            body_diameter_m=0.054,
            drag_coefficient=0.45,
            launch_elevation_deg=87.0,
        )
        result = monte_carlo_dispersion(nom, n_samples=30, seed=42)

        assert isinstance(result, MonteCarloResult)
        assert result.n_samples == 30
        assert len(result.samples) == 30

    def test_apogee_positive(self):
        """All trajectories should reach positive apogee altitude."""
        nom = NominalInputs(
            total_impulse_ns=1200.0,
            burn_time_s=2.0,
            initial_mass_kg=1.0,
            propellant_mass_kg=0.2,
        )
        result = monte_carlo_dispersion(nom, n_samples=20, seed=0)
        assert result.apogee_mean_m > 0
        for s in result.samples:
            assert s["apogee_m"] > 0

    def test_dispersion_spread(self):
        """With wind, landing scatter should have non-zero spread."""
        nom = NominalInputs(
            total_impulse_ns=640, burn_time_s=1.7,
            initial_mass_kg=0.7, propellant_mass_kg=0.12,
        )
        disp = DispersionInputs(wind_speed_mps=10.0)
        result = monte_carlo_dispersion(nom, disp, n_samples=50, seed=1)
        # With 10 m/s wind uncertainty, landing radius std should be > 0
        assert result.landing_radius_std_m > 0.0

    def test_zero_wind_tight_scatter(self):
        """With all uncertainties to zero, scatter should be very tight."""
        nom = NominalInputs(
            total_impulse_ns=640, burn_time_s=1.7,
            initial_mass_kg=0.7, propellant_mass_kg=0.12,
            launch_elevation_deg=90.0,  # straight up → zero horizontal drift
        )
        disp = DispersionInputs(
            wind_speed_mps=0.0,
            wind_direction_deg=0.0,
            drag_coefficient_frac=0.0,
            isp_frac=0.0,
            launch_angle_deg=0.0,
            ignition_delay_s=0.0,
        )
        result = monte_carlo_dispersion(nom, disp, n_samples=10, seed=99)
        # Very little scatter when all uncertainties are zero
        assert result.apogee_std_m < result.apogee_mean_m * 0.05

    def test_reproducibility_with_seed(self):
        """Same seed produces identical results."""
        nom = NominalInputs()
        r1 = monte_carlo_dispersion(nom, n_samples=20, seed=7)
        r2 = monte_carlo_dispersion(nom, n_samples=20, seed=7)
        assert r1.apogee_mean_m == r2.apogee_mean_m
        assert r1.landing_radius_p95_m == r2.landing_radius_p95_m

    def test_p95_greater_than_mean(self):
        """95th percentile landing radius should be >= mean."""
        nom = NominalInputs(total_impulse_ns=1000)
        result = monte_carlo_dispersion(nom, n_samples=50, seed=5)
        assert result.landing_radius_p95_m >= result.landing_radius_mean_m

    def test_apogee_percentiles_ordered(self):
        """5th percentile apogee < mean < 95th percentile."""
        nom = NominalInputs(total_impulse_ns=640, burn_time_s=1.7,
                            initial_mass_kg=0.7, propellant_mass_kg=0.12)
        result = monte_carlo_dispersion(nom, n_samples=50, seed=10)
        assert result.apogee_p05_m <= result.apogee_mean_m
        assert result.apogee_mean_m <= result.apogee_p95_m
