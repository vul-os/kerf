"""Tests for recovery.py — parachute and streamer descent simulation."""

from __future__ import annotations

import math
import pytest

from kerf_aero.recovery import (
    terminal_descent_speed,
    simulate_descent,
    simulate_dual_deploy,
    streamer_cd_area,
    DescentResult,
    DualDeployResult,
)


class TestTerminalDescentSpeed:
    """Validate terminal descent speed formula."""

    def test_typical_1kg_1m_chute(self):
        """1 kg on a 1 m round chute (Cd≈0.8, A≈0.785 m²) → ~5 m/s."""
        # Cd*A ≈ 0.8 * pi*(0.5)^2 ≈ 0.628 m²; typical landing speed 3-7 m/s
        v = terminal_descent_speed(mass_kg=1.0, cd_area_m2=0.628)
        assert 3.0 < v < 10.0, f"Expected 3-10 m/s; got {v:.2f} m/s"

    def test_higher_altitude_higher_terminal_speed(self):
        """Lower air density at altitude → higher terminal speed."""
        v_sl = terminal_descent_speed(1.0, 0.7, altitude_m=0)
        v_hi = terminal_descent_speed(1.0, 0.7, altitude_m=5000)
        assert v_hi > v_sl

    def test_heavier_mass_higher_speed(self):
        """Heavier mass descends faster (same chute)."""
        v_light = terminal_descent_speed(1.0, 0.7)
        v_heavy = terminal_descent_speed(5.0, 0.7)
        assert v_heavy > v_light

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            terminal_descent_speed(-1.0, 0.7)
        with pytest.raises(ValueError):
            terminal_descent_speed(1.0, 0.0)


class TestSimulateDescent:
    """Validate descent simulation from deployment altitude to ground."""

    def test_300m_deployment(self):
        """1 kg on 0.7 m² Cd·A from 300 m should land in < 120 s."""
        res = simulate_descent(300.0, mass_kg=1.0, cd_area_m2=0.7)
        assert res.descent_time_s > 0
        assert res.descent_time_s < 120.0, (
            f"Expected < 120 s descent; got {res.descent_time_s:.1f} s"
        )

    def test_touchdown_speed_reasonable(self):
        """Touchdown speed should be near terminal speed."""
        res = simulate_descent(500.0, mass_kg=1.5, cd_area_m2=0.9)
        v_term = terminal_descent_speed(1.5, 0.9, altitude_m=0.0)
        # Touchdown speed should be within 30% of terminal
        rel_err = abs(res.touchdown_speed_ms - v_term) / v_term
        assert rel_err < 0.30, (
            f"Touchdown speed {res.touchdown_speed_ms:.2f} m/s; "
            f"terminal {v_term:.2f} m/s; rel err {rel_err:.2%}"
        )

    def test_wind_drift(self):
        """Wind drift should be proportional to wind speed."""
        res_no_wind = simulate_descent(300.0, 1.0, 0.7, wind_speed_mps=0.0)
        res_wind = simulate_descent(300.0, 1.0, 0.7, wind_speed_mps=5.0)
        assert res_wind.horizontal_drift_m > res_no_wind.horizontal_drift_m

    def test_invalid_altitude(self):
        with pytest.raises(ValueError):
            simulate_descent(-10.0, 1.0, 0.7)


class TestDualDeploy:
    """Validate dual-deploy recovery sequence."""

    def test_basic_dual_deploy(self):
        """Standard dual-deploy: drogue from apogee, main at 150m."""
        r = simulate_dual_deploy(
            apogee_m=300.0,
            mass_kg=1.0,
            drogue_cd_area_m2=0.06,
            main_cd_area_m2=0.70,
            main_deploy_altitude_m=150.0,
        )
        assert isinstance(r, DualDeployResult)
        assert r.drogue_deployed_at_m == 300.0
        assert r.main_deployed_at_m == 150.0
        assert r.total_descent_time_s > 0
        assert r.touchdown_speed_ms < 15.0, (
            f"Touchdown speed too high: {r.touchdown_speed_ms:.2f} m/s"
        )

    def test_total_time_is_sum(self):
        """Total descent time = drogue phase + main phase."""
        r = simulate_dual_deploy(400.0, 1.5, 0.06, 0.9, main_deploy_altitude_m=150.0)
        total = r.drogue_descent.descent_time_s + r.main_descent.descent_time_s
        assert abs(r.total_descent_time_s - total) < 1e-6

    def test_invalid_apogee_below_main_deploy(self):
        """Apogee below main deploy altitude should raise ValueError."""
        with pytest.raises(ValueError):
            simulate_dual_deploy(100.0, 1.0, 0.06, 0.7, main_deploy_altitude_m=200.0)


class TestStreamerCdArea:
    """Validate streamer drag area calculation."""

    def test_typical_streamer(self):
        """1 m × 0.05 m streamer at Cd=0.75: expected Cd*A = 0.0375 m²."""
        cd_a = streamer_cd_area(width_m=0.05, length_m=1.0, cd_streamer=0.75)
        assert abs(cd_a - 0.0375) < 1e-9

    def test_custom_cd(self):
        """Custom Cd scales result correctly."""
        cd_a1 = streamer_cd_area(0.05, 1.0, cd_streamer=0.75)
        cd_a2 = streamer_cd_area(0.05, 1.0, cd_streamer=0.50)
        assert cd_a2 < cd_a1
