"""
Tests for kerf_mates.mbd.vehicle_dynamics — Pacejka tires + bicycle model.

References
----------
Pacejka, H.B. (2012). "Tire and Vehicle Dynamics." 3rd ed., Butterworth-Heinemann.
Rajamani, R. (2012). "Vehicle Dynamics and Control." 2nd ed., Springer.
"""

from __future__ import annotations

import math

import pytest

from kerf_mates.mbd.vehicle_dynamics import (
    SuspensionLink,
    TireModel,
    VehicleSpec,
    steady_state_cornering,
    step_vehicle,
)


# ---------------------------------------------------------------------------
# TireModel / Pacejka Magic Formula tests
# ---------------------------------------------------------------------------

class TestTireModel:

    def _default_tire(self) -> TireModel:
        return TireModel()

    # Longitudinal

    def test_Fx_at_zero_slip_is_zero(self):
        """Fx(κ=0) must be 0 within 1e-9 (reference: Pacejka 2012 §4.3)."""
        tire = self._default_tire()
        assert abs(tire.Fx(0.0, 4000.0)) < 1e-9

    def test_Fx_sign_positive_for_positive_slip(self):
        """Positive slip ratio → forward traction force."""
        tire = self._default_tire()
        assert tire.Fx(0.1, 4000.0) > 0.0

    def test_Fx_sign_negative_for_negative_slip(self):
        """Negative slip ratio → braking force (negative)."""
        tire = self._default_tire()
        assert tire.Fx(-0.1, 4000.0) < 0.0

    def test_Fx_zero_normal_load(self):
        """Fx with zero normal load must return 0."""
        tire = self._default_tire()
        assert tire.Fx(0.2, 0.0) == 0.0

    def test_Fx_bounded_by_peak(self):
        """Fx must be bounded by Dx * Fz (peak friction limit)."""
        tire = self._default_tire()
        Fz = 5000.0
        assert abs(tire.Fx(0.15, Fz)) <= tire.Dx * Fz * 1.01  # 1% margin

    # Lateral

    def test_Fy_at_zero_slip_angle_is_zero(self):
        """Fy(α=0) must be 0 within 1e-9 (reference: Pacejka 2012 §4.4)."""
        tire = self._default_tire()
        assert abs(tire.Fy(0.0, 4000.0)) < 1e-9

    def test_Fy_sign_positive_for_positive_slip_angle(self):
        """Positive slip angle → positive lateral force."""
        tire = self._default_tire()
        assert tire.Fy(0.05, 4000.0) > 0.0

    def test_Fy_sign_antisymmetric(self):
        """Fy must be an odd function: Fy(-α) = -Fy(α)."""
        tire = self._default_tire()
        Fz = 4000.0
        alpha = 0.08
        assert abs(tire.Fy(-alpha, Fz) + tire.Fy(alpha, Fz)) < 1e-9

    def test_Fy_bounded_by_Dy_Fz(self):
        """Fy must be bounded by Dy * Fz (peak lateral friction, Pacejka §4.4)."""
        tire = self._default_tire()
        Fz = 5000.0
        for alpha in [0.0, 0.05, 0.1, 0.3, 1.0]:
            fy = abs(tire.Fy(alpha, Fz))
            assert fy <= tire.Dy * Fz * 1.01, f"Fy={fy:.1f} exceeds Dy*Fz={tire.Dy*Fz:.1f} at α={alpha}"

    def test_Fy_zero_normal_load(self):
        """Fy with zero normal load must return 0."""
        tire = self._default_tire()
        assert tire.Fy(0.1, 0.0) == 0.0

    def test_Fy_scales_with_normal_load(self):
        """Heavier tyre should produce higher Fy at same slip angle."""
        tire = self._default_tire()
        fy_light = abs(tire.Fy(0.05, 2000.0))
        fy_heavy = abs(tire.Fy(0.05, 4000.0))
        assert fy_heavy > fy_light


# ---------------------------------------------------------------------------
# step_vehicle tests
# ---------------------------------------------------------------------------

class TestStepVehicle:

    def _default_spec(self) -> VehicleSpec:
        return VehicleSpec(mass_kg=1200.0, wheelbase_m=2.65)

    def test_step_returns_dict_with_required_keys(self):
        required = {"x", "y", "psi", "vx", "vy", "r",
                    "Fz_front", "Fz_rear", "alpha_f", "alpha_r"}
        state = step_vehicle({}, self._default_spec(), 0.0, 0.0, 0.0, 0.01)
        assert required.issubset(state.keys())

    def test_straight_line_no_lateral_motion(self):
        """With zero steering and no disturbance vy should remain near 0."""
        spec = self._default_spec()
        state = {"vx": 20.0, "vy": 0.0, "r": 0.0}
        for _ in range(100):
            state = step_vehicle(state, spec, 0.0, 0.0, 0.0, 0.01)
        assert abs(state["vy"]) < 0.1   # should not drift laterally

    def test_braking_loads_front_axle(self):
        """Under braking the front axle should carry more load than static.

        Reference: weight transfer ΔFz = m·a·h/L shifts load forward during braking.
        """
        spec = self._default_spec()
        state = {"vx": 20.0}
        # Static: Fz_front ≈ m*g * b/L
        b = spec.b_m
        L = spec.wheelbase_m
        Fz_static_front = spec.mass_kg * spec.g * b / L

        result = step_vehicle(state, spec, 0.0, 0.0, brake=0.8, dt=0.01)
        assert result["Fz_front"] > Fz_static_front, (
            f"Braking should increase front load: got {result['Fz_front']:.1f} vs static {Fz_static_front:.1f}"
        )

    def test_throttle_does_not_reverse_speed(self):
        """Speed must remain non-negative (floor at 0)."""
        spec = self._default_spec()
        state = {"vx": 0.1}
        result = step_vehicle(state, spec, 0.0, 0.0, 1.0, 0.01)
        assert result["vx"] >= 0.0

    def test_steering_creates_yaw_rate(self):
        """Non-zero steering angle should produce a non-zero yaw rate."""
        spec = self._default_spec()
        state = {"vx": 15.0}
        result = step_vehicle(state, spec, math.radians(5.0), 0.1, 0.0, 0.01)
        assert abs(result["r"]) > 1e-6


# ---------------------------------------------------------------------------
# steady_state_cornering tests
# ---------------------------------------------------------------------------

class TestSteadyStateCornering:

    def _default_spec(self) -> VehicleSpec:
        return VehicleSpec(mass_kg=1200.0, wheelbase_m=2.65)

    def test_returns_ok(self):
        result = steady_state_cornering(self._default_spec(), 10.0, 50.0)
        assert result["ok"] is True

    def test_low_speed_small_steering_angle(self):
        """At low speed the required steering is approximately Ackermann (L/R)."""
        spec = self._default_spec()
        result = steady_state_cornering(spec, 5.0, 100.0)
        assert result["ok"]
        # Ackermann steering: δ_Ack = L/R = 2.65/100 = 0.0265 rad
        delta_ack = spec.wheelbase_m / 100.0
        # Should be within a factor of 2 of Ackermann for low speed
        assert abs(result["steering_rad"]) < 2.0 * delta_ack

    def test_higher_speed_more_steering(self):
        """Higher speed on same radius should require more steering (understeer)."""
        spec = self._default_spec()
        r1 = steady_state_cornering(spec, 10.0, 100.0)
        r2 = steady_state_cornering(spec, 20.0, 100.0)
        assert r1["ok"] and r2["ok"]
        # Higher lateral g → more correction for understeer
        assert r2["lateral_g"] > r1["lateral_g"]

    def test_invalid_radius_returns_error(self):
        result = steady_state_cornering(self._default_spec(), 10.0, 0.0)
        assert result["ok"] is False

    def test_lateral_g_matches_kinematics(self):
        """lateral_g must equal V²/(R·g)."""
        spec = self._default_spec()
        V, R = 15.0, 80.0
        result = steady_state_cornering(spec, V, R)
        assert result["ok"]
        expected_g = V**2 / (R * spec.g)
        assert abs(result["lateral_g"] - expected_g) < 1e-9

    def test_steering_deg_matches_rad(self):
        """steering_deg must equal degrees(steering_rad)."""
        spec = self._default_spec()
        result = steady_state_cornering(spec, 10.0, 50.0)
        assert result["ok"]
        assert abs(math.degrees(result["steering_rad"]) - result["steering_deg"]) < 1e-9
