"""
Tests for kerf_mates.mbd.machinery — gear mesh + belt/chain drives.

References
----------
Litvin, F.L. (2004). "Gear Geometry and Applied Theory." 2nd ed., Cambridge.
ISO 6336-1:2019. Gear load capacity calculation.
Shigley's Mechanical Engineering Design, §17.2 (belts).
"""

from __future__ import annotations

import math

import pytest

from kerf_mates.mbd.machinery import (
    BeltDrive,
    ChainDrive,
    GearMeshDynamics,
    belt_drive_force,
    chain_drive_tension,
    gear_mesh_force,
    iso6336_tangential_force,
)


# ---------------------------------------------------------------------------
# GearMeshDynamics tests
# ---------------------------------------------------------------------------

class TestGearMeshDynamics:

    def _default_mesh(self) -> GearMeshDynamics:
        return GearMeshDynamics(
            pinion_teeth=20,
            gear_teeth=40,
            module_mm=2.0,
            mesh_stiffness_n_per_m=2e8,
            backlash_mm=0.05,
        )

    def test_gear_ratio(self):
        """Gear ratio must equal z_g / z_p."""
        mesh = self._default_mesh()
        assert abs(mesh.gear_ratio - 2.0) < 1e-9

    def test_pitch_radius_pinion(self):
        """Pinion pitch radius = m * z_p / 2 [m]."""
        mesh = self._default_mesh()
        expected = 0.5 * 2e-3 * 20
        assert abs(mesh.pitch_radius_pinion_m - expected) < 1e-9

    def test_pitch_radius_gear(self):
        """Gear pitch radius = m * z_g / 2 [m]."""
        mesh = self._default_mesh()
        expected = 0.5 * 2e-3 * 40
        assert abs(mesh.pitch_radius_gear_m - expected) < 1e-9

    def test_contact_ratio_above_unity(self):
        """Contact ratio must be >= 1 for a valid gear pair."""
        mesh = self._default_mesh()
        assert mesh.contact_ratio >= 1.0

    def test_contact_ratio_standard_spur_range(self):
        """Typical spur-gear contact ratio is 1.1–2.0."""
        mesh = self._default_mesh()
        assert 1.0 <= mesh.contact_ratio <= 2.5

    def test_gear_mesh_force_nonzero_with_mismatch(self):
        """Mismatched ωp/ωg should produce non-zero mesh force (Litvin §8)."""
        mesh = self._default_mesh()
        # Correct ratio is 2:1, apply 1.8:1 → KTE ≠ 0
        omega_p = 100.0   # rad/s
        omega_g = 40.0    # rad/s — wrong (should be 50)
        F_t, F_n = gear_mesh_force(omega_p, omega_g, mesh, dt=1e-4)
        assert F_t > 0.0 or F_n > 0.0, "Mismatched speeds must produce mesh force"

    def test_gear_mesh_force_in_backlash_is_zero(self):
        """Conjugate ratio (perfect 2:1) within backlash band → zero force."""
        mesh = self._default_mesh()
        omega_p = 100.0
        omega_g = 50.0    # exact ratio
        # With exact ratio KTE = 0 → inside backlash dead-band
        F_t, F_n = gear_mesh_force(omega_p, omega_g, mesh, dt=1e-4)
        assert F_t == 0.0
        assert F_n == 0.0

    def test_gear_mesh_force_positive(self):
        """Tangential and normal forces must be non-negative."""
        mesh = self._default_mesh()
        F_t, F_n = gear_mesh_force(200.0, 80.0, mesh, dt=1e-3)
        assert F_t >= 0.0
        assert F_n >= 0.0

    def test_F_normal_greater_than_tangential(self):
        """Normal force (along line of action) > tangential force (α > 0)."""
        mesh = self._default_mesh()
        F_t, F_n = gear_mesh_force(200.0, 80.0, mesh, dt=1e-3)
        if F_t > 0.0:
            alpha_rad = math.radians(mesh.pressure_angle_deg)
            assert F_n > F_t - 1e-6, "F_normal must be >= F_tangential"

    def test_iso6336_tangential_force(self):
        """ISO 6336 tangential force = P / (ω · r)."""
        mesh = self._default_mesh()
        P = 5000.0         # W
        omega_p = 100.0    # rad/s
        F_t = iso6336_tangential_force(P, omega_p, mesh)
        expected = P / (omega_p * mesh.pitch_radius_pinion_m)
        assert abs(F_t - expected) < 1e-6

    def test_iso6336_zero_speed(self):
        """Zero speed → zero tangential force (avoid division by zero)."""
        mesh = self._default_mesh()
        assert iso6336_tangential_force(1000.0, 0.0, mesh) == 0.0


# ---------------------------------------------------------------------------
# BeltDrive tests
# ---------------------------------------------------------------------------

class TestBeltDrive:

    def _default_belt(self) -> BeltDrive:
        return BeltDrive(
            pulley_a_radius_m=0.10,
            pulley_b_radius_m=0.05,
            belt_pitch_m=0.60,
            belt_youngs_modulus_pa=200e6,
            pretension_n=500.0,
            mu=0.35,
            groove_angle_deg=0.0,    # flat belt
        )

    def test_tension_ratio_euler_formula(self):
        """T1/T2 = e^(μ·θ) per Shigley §17.2."""
        belt = self._default_belt()
        ratio = belt.tension_ratio()
        phi = belt.wrap_angle_small()
        expected = math.exp(belt.mu * phi)
        assert abs(ratio - expected) < 1e-9

    def test_belt_drive_T1_geq_T2(self):
        """Tight-side tension must be >= slack-side tension."""
        belt = self._default_belt()
        T1, T2 = belt_drive_force(100.0, 40.0, belt)
        assert T1 >= T2

    def test_belt_drive_zero_slip_gives_equal_tensions(self):
        """At zero slip (no load) T1 ≈ T2 ≈ Ti."""
        belt = self._default_belt()
        # Ideal slip-free: omega_b = omega_a * r_a/r_b
        omega_a = 100.0
        omega_b_ideal = omega_a * belt.pulley_a_radius_m / belt.pulley_b_radius_m
        T1, T2 = belt_drive_force(omega_a, omega_b_ideal, belt)
        # At zero slip both tensions should equal pretension
        assert abs(T1 - belt.pretension_n) < 1.0
        assert abs(T2 - belt.pretension_n) < 1.0

    def test_belt_drive_T1_T2_ratio_bounded_by_euler(self):
        """Actual T1/T2 ratio under slip must be <= theoretical Euler limit."""
        belt = self._default_belt()
        T1, T2 = belt_drive_force(100.0, 20.0, belt)    # high slip
        if T2 > 0.1:
            ratio_actual = T1 / T2
            ratio_euler = belt.tension_ratio()
            # Should not exceed Euler limit by more than 1%
            assert ratio_actual <= ratio_euler * 1.01, (
                f"Actual ratio {ratio_actual:.3f} exceeds Euler limit {ratio_euler:.3f}"
            )

    def test_v_belt_higher_friction(self):
        """V-belt (groove_angle > 0) should have higher tension ratio than flat belt."""
        flat = BeltDrive(0.10, 0.05, 0.60, 200e6, 500.0, mu=0.35, groove_angle_deg=0.0)
        vbelt = BeltDrive(0.10, 0.05, 0.60, 200e6, 500.0, mu=0.35, groove_angle_deg=38.0)
        assert vbelt.tension_ratio() > flat.tension_ratio()

    def test_wrap_angle_small_pulley_lt_pi(self):
        """Wrap angle on smaller pulley must be < π for open belt."""
        belt = self._default_belt()
        phi = belt.wrap_angle_small()
        assert 0.1 <= phi < math.pi

    def test_belt_tensions_positive(self):
        """Both tensions must be non-negative."""
        belt = self._default_belt()
        T1, T2 = belt_drive_force(80.0, 30.0, belt)
        assert T1 >= 0.0
        assert T2 >= 0.0


# ---------------------------------------------------------------------------
# ChainDrive tests
# ---------------------------------------------------------------------------

class TestChainDrive:

    def _default_chain(self) -> ChainDrive:
        return ChainDrive(
            drive_sprocket_teeth=17,
            driven_sprocket_teeth=34,
            chain_pitch_m=0.0127,    # 1/2" chain pitch
            shaft_centre_m=0.40,
        )

    def test_gear_ratio(self):
        chain = self._default_chain()
        assert abs(chain.gear_ratio - 2.0) < 1e-9

    def test_chordal_speed_ratio_positive(self):
        """Chordal velocity variation must be positive (Shigley §17.4)."""
        chain = self._default_chain()
        assert chain.chordal_speed_ratio > 0.0

    def test_chordal_speed_ratio_formula(self):
        """Chordal ratio = 1 - cos(π/N)."""
        chain = self._default_chain()
        N = chain.drive_sprocket_teeth
        expected = 1.0 - math.cos(math.pi / N)
        assert abs(chain.chordal_speed_ratio - expected) < 1e-12

    def test_chain_drive_tension_nonzero(self):
        """Non-zero torque should produce non-zero tight-side tension."""
        chain = self._default_chain()
        result = chain_drive_tension(50.0, 20.0, chain)
        assert result["T_tight_n"] > 0.0

    def test_chain_drive_returns_expected_keys(self):
        chain = self._default_chain()
        result = chain_drive_tension(50.0, 20.0, chain)
        for key in ("T_tight_n", "T_slack_n", "v_chain_m_s", "delta_v_m_s"):
            assert key in result
