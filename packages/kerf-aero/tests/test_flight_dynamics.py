"""
Tests for kerf_aero.flight_dynamics — atmosphere, 6-DOF EOM, and coefficients.
"""

from __future__ import annotations

import math
import pytest

from kerf_aero.flight_dynamics.atmosphere import atmosphere, geometric_to_geopotential
from kerf_aero.flight_dynamics.sixdof import (
    Forces,
    RigidBody,
    eom,
    euler_to_quat,
    integrate,
    level_flight_state,
    quat_to_euler,
    rk4_step,
    state_to_array,
    state_from_array,
    _quat_norm,
)
from kerf_aero.flight_dynamics.coefficients import (
    CESSNA172,
    get_coefficients,
    _bilinear_interp,
)


# ===========================================================================
# U.S. Standard Atmosphere 1976
# ===========================================================================

class TestAtmosphereSeaLevel:
    """Oracle: T=288.15 K, p=101325 Pa, ρ=1.225 kg/m³ at z=0."""

    def test_temperature(self):
        state = atmosphere(0.0)
        assert abs(state.temperature_K - 288.15) < 1e-6

    def test_pressure(self):
        state = atmosphere(0.0)
        assert abs(state.pressure_Pa - 101325.0) < 1e-6

    def test_density(self):
        state = atmosphere(0.0)
        # ρ = P/(R·T) = 101325 / (287.05287 * 288.15) ≈ 1.2250 kg/m³
        assert abs(state.density_kg_m3 - 1.225) < 1e-3

    def test_speed_of_sound(self):
        # a = sqrt(1.4 * 287.05287 * 288.15) ≈ 340.29 m/s
        state = atmosphere(0.0)
        assert abs(state.speed_of_sound_m_s - 340.294) < 0.01

    def test_viscosity(self):
        # μ(288.15) = 1.458e-6 * 288.15^1.5 / (288.15 + 110.4) ≈ 1.789e-5 Pa·s
        state = atmosphere(0.0)
        assert 1.7e-5 < state.viscosity_Pa_s < 1.85e-5


class TestAtmosphereTropopause:
    """Oracle: T=216.65 K at 11 000 m (top of troposphere)."""

    def test_temperature_exact(self):
        # At exactly 11 000 m geometric, geopotential is slightly less.
        # The layer definition uses geopotential altitude.
        # At h_geop = 11 000 m (passing geometric=False), T must be exactly 216.65 K.
        state = atmosphere(11_000.0, geometric=False)
        assert abs(state.temperature_K - 216.65) < 1e-9

    def test_temperature_geometric_approx(self):
        # At geometric 11 000 m, temperature should be very close (within ±0.5 K).
        state = atmosphere(11_000.0, geometric=True)
        assert abs(state.temperature_K - 216.65) < 0.5

    def test_pressure_tropopause(self):
        # Published USSA76 value: P ≈ 22632.1 Pa at 11 km geopotential
        state = atmosphere(11_000.0, geometric=False)
        assert abs(state.pressure_Pa - 22632.1) < 1.0

    def test_isothermal_above_11km(self):
        # Temperature must stay constant 216.65 K between 11–20 km (isothermal layer)
        for alt in [12_000.0, 15_000.0, 18_000.0, 20_000.0]:
            state = atmosphere(alt, geometric=False)
            assert abs(state.temperature_K - 216.65) < 1e-9, f"T mismatch at {alt} m"


class TestAtmospherePhysics:
    """Basic physics consistency checks."""

    def test_temperature_decreases_in_troposphere(self):
        T0 = atmosphere(0.0).temperature_K
        T5 = atmosphere(5_000.0).temperature_K
        assert T5 < T0

    def test_pressure_decreases_with_altitude(self):
        for h0, h1 in [(0, 5000), (5000, 11000), (20000, 30000), (50000, 70000)]:
            assert atmosphere(h1).pressure_Pa < atmosphere(h0).pressure_Pa, \
                f"Pressure should decrease from {h0} to {h1} m"

    def test_density_positive_everywhere(self):
        for h in [0, 1000, 11000, 25000, 50000, 80000]:
            assert atmosphere(h).density_kg_m3 > 0.0

    def test_upper_stratosphere(self):
        # At 25 km geopotential: T should be > 216.65 K (warming layer)
        state = atmosphere(25_000.0, geometric=False)
        assert state.temperature_K > 216.65

    def test_invalid_altitude_negative(self):
        with pytest.raises(ValueError):
            atmosphere(-1.0)

    def test_invalid_altitude_too_high(self):
        with pytest.raises(ValueError):
            atmosphere(90_000.0)

    def test_geopotential_conversion(self):
        h_geom = 10_000.0
        h_geop = geometric_to_geopotential(h_geom)
        # Geopotential should be slightly less than geometric
        assert h_geop < h_geom
        assert abs(h_geop - h_geom) < 20.0  # small correction at 10 km


# ===========================================================================
# 6-DOF EOM and RK4 integration
# ===========================================================================

# Cessna 172 inertia properties (approximate)
_C172_BODY = RigidBody(
    mass_kg=1111.0,
    Ixx=1285.3,
    Iyy=1824.9,
    Izz=2666.9,
    Ixz=0.0,
)

_ZERO_FORCES = Forces(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _zero_force_model(t, state):
    """No aerodynamic forces — only gravity acts (via EOM internally)."""
    return _ZERO_FORCES


class TestFreeFall:
    """
    Oracle: free fall from rest at z = −10000 m (NED: z = +10000 m Down)
    for 10 s with no aerodynamic forces.

    z_final = z_initial + ½·g0·t²  (NED, down-positive)
    z_0 = 10000 m  →  z_10 = 10000 + ½·9.80665·100 = 10490.3325 m

    altitude (positive up) = −z:
    alt_0 = 10000 m  →  alt_10 = −10490.3325 = 9509.6675 m

    Wait — the task oracle says z ≈ 9510.5 m using g = 9.81.
    We use g0 = 9.80665 consistently, so alt_10 = 10000 - ½·9.80665·100
    = 10000 - 490.3325 = 9509.6675 m.

    We'll validate within 1 m (timestep error), and also check the precise
    value against our own g0.
    """

    def _initial_state(self):
        # At rest, level (no attitude), at altitude 10000 m.
        # NED: z_down = 10000, quaternion = identity (wings level, nose North).
        return [0.0, 0.0, -10000.0,  # x, y, z(Down)
                0.0, 0.0, 0.0,       # u, v, w
                1.0, 0.0, 0.0, 0.0,  # q0, q1, q2, q3 (identity)
                0.0, 0.0, 0.0]       # p, q, r

    def test_freefall_z_position(self):
        """Altitude after 10 s free fall from rest at 10000 m."""
        dt = 0.001  # 1 ms step for high accuracy
        n_steps = 10_000  # 10 s
        s0 = self._initial_state()
        _, states = integrate(0.0, s0, dt, n_steps, _zero_force_model, _C172_BODY)
        s_final = states[-1]

        # z (NED Down) increases during fall
        z_final = s_final[2]
        alt_final = -z_final  # positive-up altitude

        # Expected: 10000 - 0.5 * 9.80665 * 100 = 9509.6675 m
        expected_alt = 10000.0 - 0.5 * 9.80665 * 100.0
        assert abs(alt_final - expected_alt) < 1.0, \
            f"Expected alt ≈ {expected_alt:.4f} m, got {alt_final:.4f} m"

    def test_freefall_approx_9510(self):
        """Altitude after free fall consistent with oracle ≈ 9510 m."""
        dt = 0.01
        n_steps = 1000
        s0 = self._initial_state()
        _, states = integrate(0.0, s0, dt, n_steps, _zero_force_model, _C172_BODY)
        alt_final = -states[-1][2]
        # Oracle says ≈ 9510.5 m (g=9.81); we use g0=9.80665 → 9509.6675 m
        # Accept within 2 m of 9510 m
        assert abs(alt_final - 9510.0) < 2.0, f"alt_final={alt_final:.4f}"

    def test_freefall_downward_velocity(self):
        """Downward velocity after 10 s should be g0*t = 98.0665 m/s."""
        dt = 0.001
        n_steps = 10_000
        s0 = self._initial_state()
        _, states = integrate(0.0, s0, dt, n_steps, _zero_force_model, _C172_BODY)
        s_final = states[-1]
        # In NED body frame with identity quaternion and no rotation,
        # w (body-down velocity) ≈ g0 * t
        w_final = s_final[5]
        expected_w = 9.80665 * 10.0
        assert abs(w_final - expected_w) < 0.01, \
            f"Expected w ≈ {expected_w:.4f} m/s, got {w_final:.4f} m/s"

    def test_freefall_no_lateral_motion(self):
        """No lateral motion during free fall with identity quaternion."""
        dt = 0.01
        n_steps = 1000
        s0 = self._initial_state()
        _, states = integrate(0.0, s0, dt, n_steps, _zero_force_model, _C172_BODY)
        s_final = states[-1]
        assert abs(s_final[3]) < 1e-10, "u should remain zero"  # forward
        assert abs(s_final[4]) < 1e-10, "v should remain zero"  # lateral


class TestSteadyLevelFlight:
    """
    Steady level flight: apply forces that exactly balance gravity and drag,
    and verify that velocity remains constant.
    """

    def _make_force_model(self, body: RigidBody, alpha_rad: float):
        """
        Return a force model that balances gravity at the given pitch angle.

        For a level-flight trim at pitch θ = alpha (no flight-path angle):
            Lift = W * cos(θ)     (body Z axis)
            Drag = W * sin(θ)  but we zero it — just balance gravity exactly.

        Simplification: we supply constant forces that exactly cancel gravity
        in the body frame for the given attitude, and zero moments.
        The aircraft will maintain constant velocity.
        """
        mass = body.mass_kg
        g0 = 9.80665
        W = mass * g0

        # With identity quaternion (wings level, zero pitch) and zero alpha,
        # gravity in body frame is: Fx=0, Fy=0, Fz=+W (down in body = down in earth).
        # We apply Fz = -W to cancel gravity exactly.
        # With zero alpha and zero pitch, the gravity body components are simply (0,0,W).
        def model(t, state):
            return Forces(
                Fx=0.0,
                Fy=0.0,
                Fz=-W,    # cancel gravity
                Mx=0.0,
                My=0.0,
                Mz=0.0,
            )
        return model

    def test_velocity_constant(self):
        """With balanced forces, forward velocity must remain constant."""
        body = _C172_BODY
        airspeed = 55.0  # m/s cruise
        alpha = 0.0      # level trim with no pitch

        s0 = level_flight_state(airspeed, 1000.0, alpha_rad=alpha)
        force_model = self._make_force_model(body, alpha)

        dt = 0.1
        n_steps = 100
        _, states = integrate(0.0, s0, dt, n_steps, force_model, body)

        s_final = states[-1]
        u_final = s_final[3]
        v_final = s_final[4]
        w_final = s_final[5]

        # All body velocities should remain as initialised
        s0_arr = s0
        assert abs(u_final - s0_arr[3]) < 1e-6, \
            f"u changed: {s0_arr[3]:.6f} → {u_final:.6f}"
        assert abs(v_final - s0_arr[4]) < 1e-6
        assert abs(w_final - s0_arr[5]) < 1e-6

    def test_altitude_constant(self):
        """With balanced forces and no flight-path angle, altitude should not change."""
        body = _C172_BODY
        s0 = level_flight_state(55.0, 1000.0)
        mass = body.mass_kg
        g0 = 9.80665
        W = mass * g0

        def model(t, state):
            return Forces(0.0, 0.0, -W, 0.0, 0.0, 0.0)

        dt = 0.1
        n_steps = 100
        _, states = integrate(0.0, s0, dt, n_steps, model, body)

        alt_0 = -s0[2]
        alt_f = -states[-1][2]
        assert abs(alt_f - alt_0) < 1e-6, f"Altitude changed: {alt_0:.4f} → {alt_f:.4f}"


class TestQuaternionNorm:
    """Oracle: quaternion remains unit-norm to 1e-9 over 100-step integration."""

    def test_unit_norm_pure_rotation(self):
        """Spinning manoeuvre: quaternion stays unit during 100 steps."""
        body = _C172_BODY
        # Start from level flight and apply a pure roll moment
        s0 = level_flight_state(55.0, 1000.0)

        def spinning_model(t, state):
            # Constant roll moment only
            return Forces(0.0, 0.0, 0.0, 500.0, 0.0, 0.0)

        dt = 0.05
        n_steps = 100
        _, states = integrate(0.0, s0, dt, n_steps, spinning_model, body)

        for i, s in enumerate(states):
            norm = _quat_norm(s[6], s[7], s[8], s[9])
            assert abs(norm - 1.0) < 1e-9, \
                f"Quaternion norm deviation at step {i}: |q|={norm:.15f}"

    def test_unit_norm_zero_forces(self):
        """Free fall: quaternion stays unit over 100 steps."""
        s0 = level_flight_state(0.0, 5000.0)

        dt = 0.1
        n_steps = 100
        _, states = integrate(0.0, s0, dt, n_steps, _zero_force_model, _C172_BODY)

        for i, s in enumerate(states):
            norm = _quat_norm(s[6], s[7], s[8], s[9])
            assert abs(norm - 1.0) < 1e-9, \
                f"Quaternion norm deviation at step {i}: |q|={norm:.15f}"

    def test_unit_norm_combined_manoeuvre(self):
        """Combined pitching and yawing manoeuvre over 100 steps."""
        body = _C172_BODY
        s0 = level_flight_state(60.0, 2000.0)

        def combined_model(t, state):
            return Forces(0.0, 0.0, 0.0, 200.0, 300.0, 100.0)

        dt = 0.02
        n_steps = 100
        _, states = integrate(0.0, s0, dt, n_steps, combined_model, body)

        for i, s in enumerate(states):
            norm = _quat_norm(s[6], s[7], s[8], s[9])
            assert abs(norm - 1.0) < 1e-9, \
                f"Quaternion norm at step {i}: {norm:.15f}"


# ===========================================================================
# Quaternion / Euler conversion round-trips
# ===========================================================================

class TestQuaternionConversions:

    def test_identity_quaternion(self):
        q0, q1, q2, q3 = euler_to_quat(0.0, 0.0, 0.0)
        assert abs(q0 - 1.0) < 1e-14
        assert abs(q1) < 1e-14
        assert abs(q2) < 1e-14
        assert abs(q3) < 1e-14

    @pytest.mark.parametrize("phi,theta,psi", [
        (0.0, 0.0, 0.0),
        (0.1, 0.0, 0.0),
        (0.0, 0.2, 0.0),
        (0.0, 0.0, 0.5),
        (0.3, -0.1, 1.0),
        (math.radians(45), math.radians(15), math.radians(90)),
    ])
    def test_round_trip(self, phi, theta, psi):
        q0, q1, q2, q3 = euler_to_quat(phi, theta, psi)
        phi2, theta2, psi2 = quat_to_euler(q0, q1, q2, q3)
        assert abs(phi2 - phi) < 1e-12
        assert abs(theta2 - theta) < 1e-12
        # Yaw angle may wrap; use sin/cos comparison
        assert abs(math.sin(psi2) - math.sin(psi)) < 1e-12
        assert abs(math.cos(psi2) - math.cos(psi)) < 1e-12

    def test_quaternion_unit_norm(self):
        for phi, theta, psi in [(0.1, 0.2, 0.3), (1.0, -0.5, 2.0)]:
            q = euler_to_quat(phi, theta, psi)
            norm = math.sqrt(sum(x**2 for x in q))
            assert abs(norm - 1.0) < 1e-14


# ===========================================================================
# Aerodynamic coefficient tables
# ===========================================================================

class TestBilinearInterp:
    """Unit tests for the bilinear interpolation helper."""

    def test_exact_grid_point(self):
        xs = [0.0, 1.0]
        ys = [0.0, 1.0]
        table = [[1.0, 2.0], [3.0, 4.0]]
        assert _bilinear_interp(0.0, 0.0, xs, ys, table) == 1.0
        assert _bilinear_interp(0.0, 1.0, xs, ys, table) == 2.0
        assert _bilinear_interp(1.0, 0.0, xs, ys, table) == 3.0
        assert _bilinear_interp(1.0, 1.0, xs, ys, table) == 4.0

    def test_midpoint(self):
        xs = [0.0, 1.0]
        ys = [0.0, 1.0]
        table = [[0.0, 0.0], [0.0, 4.0]]
        val = _bilinear_interp(0.5, 0.5, xs, ys, table)
        assert abs(val - 1.0) < 1e-12

    def test_clamp_below(self):
        xs = [0.0, 1.0]
        ys = [0.0, 1.0]
        table = [[1.0, 2.0], [3.0, 4.0]]
        assert _bilinear_interp(-5.0, -5.0, xs, ys, table) == 1.0

    def test_clamp_above(self):
        xs = [0.0, 1.0]
        ys = [0.0, 1.0]
        table = [[1.0, 2.0], [3.0, 4.0]]
        assert _bilinear_interp(5.0, 5.0, xs, ys, table) == 4.0


class TestCessna172Coefficients:
    """Smoke tests for Cessna 172-class aerodynamic tables."""

    def test_CL_zero_alpha(self):
        # At α=0°, CL should be positive (cambered wing ≈ 0.30)
        cl = CESSNA172.CL(0.0, 0.1)
        assert 0.2 < cl < 0.5

    def test_CL_increases_with_alpha(self):
        mach = 0.15
        cl_low  = CESSNA172.CL(math.radians(2.0), mach)
        cl_high = CESSNA172.CL(math.radians(10.0), mach)
        assert cl_high > cl_low

    def test_CD_minimum_near_zero_alpha(self):
        cd_0  = CESSNA172.CD(0.0, 0.1)
        cd_10 = CESSNA172.CD(math.radians(10.0), 0.1)
        # Drag at 10° alpha should be higher than at 0°
        assert cd_10 > cd_0

    def test_Cm_nose_down_at_positive_alpha(self):
        # Pitching moment should be negative (nose-down) at positive AoA
        cm = CESSNA172.Cm(math.radians(8.0), 0.1)
        assert cm < 0.0

    def test_CL_stall(self):
        # CL at 18° should be less than at 14° (post-stall drop)
        cl_14 = CESSNA172.CL(math.radians(14.0), 0.1)
        cl_18 = CESSNA172.CL(math.radians(18.0), 0.1)
        assert cl_18 < cl_14

    def test_get_coefficients_lookup(self):
        c1 = get_coefficients("cessna172")
        c2 = get_coefficients("c172")
        assert c1.name == c2.name == CESSNA172.name

    def test_get_coefficients_unknown(self):
        with pytest.raises(KeyError):
            get_coefficients("unknown_aircraft_xyz")

    def test_CD_positive_everywhere(self):
        for alpha_deg in range(-5, 21, 2):
            cd = CESSNA172.CD(math.radians(float(alpha_deg)), 0.15)
            assert cd > 0.0, f"CD should be positive at alpha={alpha_deg}°"


# ===========================================================================
# EOM derivative sanity checks
# ===========================================================================

class TestEOMDerivatives:

    def test_eom_returns_13_elements(self):
        s = level_flight_state(50.0, 1000.0)
        deriv = eom(s, _ZERO_FORCES, _C172_BODY)
        assert len(deriv) == 13

    def test_eom_freefall_acceleration(self):
        """With zero forces, du/dt = 0, dw/dt = g0 (level, identity quaternion)."""
        s = [0.0, 0.0, -10000.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        deriv = eom(s, _ZERO_FORCES, _C172_BODY)
        # With identity quaternion (level), gravity is pure down in body → dw = +g0
        assert abs(deriv[3]) < 1e-12, f"du/dt should be 0, got {deriv[3]}"
        assert abs(deriv[4]) < 1e-12, f"dv/dt should be 0, got {deriv[4]}"
        assert abs(deriv[5] - 9.80665) < 1e-6, f"dw/dt should be g0={9.80665}, got {deriv[5]}"

    def test_eom_no_forces_no_angular_accel(self):
        """With zero moments, angular rates should not change if ω=0."""
        s = level_flight_state(0.0, 0.0)
        deriv = eom(s, _ZERO_FORCES, _C172_BODY)
        # dp/dt, dq/dt, dr/dt should all be zero when M=0 and ω=0
        assert abs(deriv[10]) < 1e-12
        assert abs(deriv[11]) < 1e-12
        assert abs(deriv[12]) < 1e-12


# ===========================================================================
# State vector utilities
# ===========================================================================

class TestStateUtils:

    def test_round_trip(self):
        s = level_flight_state(50.0, 1000.0)
        named = state_from_array(s)
        back  = state_to_array(named)
        for a, b in zip(s, back):
            assert abs(a - b) < 1e-15

    def test_altitude_property(self):
        s = level_flight_state(50.0, 2500.0)
        named = state_from_array(s)
        assert abs(named.altitude_m - 2500.0) < 1e-6

    def test_airspeed_property(self):
        s = level_flight_state(60.0, 1000.0, alpha_rad=0.0)
        named = state_from_array(s)
        assert abs(named.airspeed_m_s - 60.0) < 1e-6
