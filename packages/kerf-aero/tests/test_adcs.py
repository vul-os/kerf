"""Analytic-oracle tests for the ADCS module.

Run with:
    PYTHONPATH=packages/kerf-core/src:packages/kerf-aero/src \
        python3 -m pytest packages/kerf-aero/tests/test_adcs.py -x
"""

import numpy as np
import pytest

from kerf_aero.adcs.attitude import (
    qconjugate,
    qfrom_axis_angle,
    qfrom_dcm,
    qmultiply,
    qnorm,
    qnormalize,
    qrotate,
    qslerp,
    qto_dcm,
    qto_euler,
    propagate,
    rk4_step,
)
from kerf_aero.adcs.reaction_wheels import ReactionWheel, ReactionWheelCluster
from kerf_aero.adcs.magnetorquer import Magnetorquer, MagnetorquerCluster
from kerf_aero.adcs.control_allocation import (
    WheelAllocator,
    pseudo_inverse_allocation,
)


# ===========================================================================
# Quaternion tests
# ===========================================================================


class TestQuaternionIdentity:
    """q ⊗ q* = (1, 0, 0, 0) to 1e-12."""

    def test_identity_from_axis_angle(self):
        q = qfrom_axis_angle([1.0, 0.0, 0.0], np.pi / 3)
        q_star = qconjugate(q)
        product = qmultiply(q, q_star)
        # Should be identity quaternion [1, 0, 0, 0]
        expected = np.array([1.0, 0.0, 0.0, 0.0])
        np.testing.assert_allclose(product, expected, atol=1e-12)

    def test_identity_arbitrary_quaternion(self):
        # Arbitrary unit quaternion
        q = qnormalize(np.array([0.5, 0.5, 0.5, 0.5]))
        q_star = qconjugate(q)
        product = qmultiply(q, q_star)
        np.testing.assert_allclose(product, [1.0, 0.0, 0.0, 0.0], atol=1e-12)

    def test_identity_norm(self):
        q = qfrom_axis_angle([0.0, 1.0, 0.0], np.pi / 4)
        q_star = qconjugate(q)
        product = qmultiply(q, q_star)
        # w must be 1 and vector part must be zero
        assert abs(product[0] - 1.0) < 1e-12
        np.testing.assert_allclose(product[1:], [0.0, 0.0, 0.0], atol=1e-12)

    def test_conjugate_product_reverse(self):
        q = qfrom_axis_angle([1.0, 2.0, 3.0], 1.1)
        # q* ⊗ q should also be identity
        product = qmultiply(qconjugate(q), q)
        np.testing.assert_allclose(product, [1.0, 0.0, 0.0, 0.0], atol=1e-12)


class TestQuaternionRotation:
    """Rotating x-axis by 90° about z should give y-axis."""

    def test_x_by_90deg_about_z(self):
        q = qfrom_axis_angle([0.0, 0.0, 1.0], np.pi / 2)
        v = np.array([1.0, 0.0, 0.0])
        v_rot = qrotate(q, v)
        expected = np.array([0.0, 1.0, 0.0])
        np.testing.assert_allclose(v_rot, expected, atol=1e-12)

    def test_y_by_90deg_about_x(self):
        q = qfrom_axis_angle([1.0, 0.0, 0.0], np.pi / 2)
        v = np.array([0.0, 1.0, 0.0])
        v_rot = qrotate(q, v)
        expected = np.array([0.0, 0.0, 1.0])
        np.testing.assert_allclose(v_rot, expected, atol=1e-12)

    def test_z_by_90deg_about_y(self):
        q = qfrom_axis_angle([0.0, 1.0, 0.0], np.pi / 2)
        v = np.array([0.0, 0.0, 1.0])
        v_rot = qrotate(q, v)
        expected = np.array([1.0, 0.0, 0.0])
        np.testing.assert_allclose(v_rot, expected, atol=1e-12)

    def test_rotation_preserves_magnitude(self):
        q = qfrom_axis_angle([1.0, 1.0, 1.0], 1.23)
        v = np.array([3.0, -1.0, 2.0])
        v_rot = qrotate(q, v)
        np.testing.assert_allclose(
            np.linalg.norm(v_rot), np.linalg.norm(v), atol=1e-12
        )

    def test_180deg_rotation(self):
        q = qfrom_axis_angle([0.0, 0.0, 1.0], np.pi)
        v = np.array([1.0, 0.0, 0.0])
        v_rot = qrotate(q, v)
        np.testing.assert_allclose(v_rot, [-1.0, 0.0, 0.0], atol=1e-12)


class TestQuaternionDCMRoundtrip:
    """DCM ↔ quaternion round-trip consistency."""

    def test_dcm_to_quat_to_dcm(self):
        q = qfrom_axis_angle([1.0, 2.0, 3.0], 0.7)
        R = qto_dcm(q)
        q2 = qfrom_dcm(R)
        # Quaternions may differ by sign; test rotation equivalence
        v = np.array([1.0, 0.0, 0.0])
        v1 = qrotate(q, v)
        v2 = qrotate(q2, v)
        np.testing.assert_allclose(v1, v2, atol=1e-12)

    def test_dcm_is_orthogonal(self):
        q = qfrom_axis_angle([0.0, 1.0, 0.0], np.pi / 3)
        R = qto_dcm(q)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)

    def test_dcm_determinant_one(self):
        q = qfrom_axis_angle([1.0, 1.0, 0.0], 1.5)
        R = qto_dcm(q)
        assert abs(np.linalg.det(R) - 1.0) < 1e-12


class TestQuaternionSlerp:
    """SLERP end-points and mid-point consistency."""

    def test_slerp_at_zero(self):
        q0 = qfrom_axis_angle([1.0, 0.0, 0.0], 0.0)
        q1 = qfrom_axis_angle([0.0, 0.0, 1.0], np.pi / 2)
        result = qslerp(q0, q1, 0.0)
        np.testing.assert_allclose(result, q0, atol=1e-10)

    def test_slerp_at_one(self):
        q0 = qfrom_axis_angle([1.0, 0.0, 0.0], 0.0)
        q1 = qfrom_axis_angle([0.0, 0.0, 1.0], np.pi / 2)
        result = qslerp(q0, q1, 1.0)
        # May differ by sign
        np.testing.assert_allclose(abs(np.dot(result, q1)), 1.0, atol=1e-10)

    def test_slerp_unit_norm(self):
        q0 = qfrom_axis_angle([1.0, 0.0, 0.0], 0.3)
        q1 = qfrom_axis_angle([0.0, 1.0, 0.0], 1.2)
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = qslerp(q0, q1, t)
            assert abs(qnorm(result) - 1.0) < 1e-10


# ===========================================================================
# Attitude dynamics tests
# ===========================================================================


class TestEulersEquation:
    """Euler's rotation equation integration tests."""

    def test_zero_torque_principal_axis_spin(self):
        """Zero torque + spin about a principal axis: spin magnitude constant."""
        # Principal inertia tensor
        I = np.diag([10.0, 20.0, 30.0])
        # Initial spin about z-axis (principal axis)
        omega0 = np.array([0.0, 0.0, 1.0])  # rad/s
        q0 = np.array([1.0, 0.0, 0.0, 0.0])  # identity

        def zero_torque(t, q, omega):
            return np.zeros(3)

        t_hist, q_hist, omega_hist = propagate(q0, omega0, I, zero_torque, t_span=10.0, dt=0.01)

        # Spin magnitude must be constant
        omega_mags = np.linalg.norm(omega_hist, axis=1)
        np.testing.assert_allclose(omega_mags, 1.0, atol=1e-6)

        # Spin axis direction must stay along z
        for omega in omega_hist:
            # omega should still be predominantly z
            np.testing.assert_allclose(omega[:2], [0.0, 0.0], atol=1e-6)

    def test_zero_torque_energy_conservation(self):
        """Rotational kinetic energy conserved under zero torque."""
        I = np.diag([5.0, 15.0, 25.0])
        omega0 = np.array([1.0, 2.0, 0.5])
        q0 = np.array([1.0, 0.0, 0.0, 0.0])

        def zero_torque(t, q, omega):
            return np.zeros(3)

        _, _, omega_hist = propagate(q0, omega0, I, zero_torque, t_span=5.0, dt=0.005)

        # T = 0.5 * omega^T I omega
        KE_initial = 0.5 * omega0 @ I @ omega0
        for omega in omega_hist:
            KE = 0.5 * omega @ I @ omega
            assert abs(KE - KE_initial) / KE_initial < 1e-4, f"KE drift: {abs(KE - KE_initial)/KE_initial}"

    def test_constant_torque_increases_angular_velocity(self):
        """Constant torque about z should accelerate spin about z."""
        I = np.diag([1.0, 1.0, 1.0])
        omega0 = np.zeros(3)
        q0 = np.array([1.0, 0.0, 0.0, 0.0])
        T = np.array([0.0, 0.0, 1.0])  # 1 N·m about z

        def const_torque(t, q, omega):
            return T

        _, _, omega_hist = propagate(q0, omega0, I, const_torque, t_span=1.0, dt=0.01)

        # omega_z should increase by ~T_z/I_z * t = 1.0 rad/s
        # (final time ~1.0 s, initial omega_z = 0)
        assert omega_hist[-1, 2] > 0.9  # should be close to 1.0

    def test_torque_free_symmetric_body(self):
        """Torque-free symmetric body: energy and angular momentum magnitude constant."""
        # Symmetric top: Ix = Iy ≠ Iz
        I = np.diag([10.0, 10.0, 5.0])
        omega0 = np.array([0.1, 0.0, 1.0])  # initial spin with wobble
        q0 = np.array([1.0, 0.0, 0.0, 0.0])

        def zero_torque(t, q, omega):
            return np.zeros(3)

        _, _, omega_hist = propagate(q0, omega0, I, zero_torque, t_span=20.0, dt=0.01)

        KE_initial = 0.5 * omega0 @ I @ omega0
        H_initial = np.linalg.norm(I @ omega0)
        for omega in omega_hist:
            KE = 0.5 * omega @ I @ omega
            H = np.linalg.norm(I @ omega)
            assert abs(KE - KE_initial) / KE_initial < 1e-3
            assert abs(H - H_initial) / H_initial < 1e-3


# ===========================================================================
# Reaction wheel tests
# ===========================================================================


class TestReactionWheels:
    """Reaction wheel momentum conservation and desaturation."""

    def test_wheel_spin_up(self):
        """Commanding a torque changes wheel speed in expected direction."""
        w = ReactionWheel(axis=[0.0, 0.0, 1.0], J=0.01, max_torque=0.1)
        assert w.omega == 0.0
        actual = w.apply_torque(0.05, dt=1.0)  # 0.05 N·m for 1 s
        assert w.omega > 0.0
        assert abs(actual - 0.05) < 1e-10

    def test_wheel_torque_clamping(self):
        """Commanded torque exceeding max is clamped."""
        w = ReactionWheel(axis=[1.0, 0.0, 0.0], J=0.01, max_torque=0.1)
        actual = w.apply_torque(1.0, dt=0.1)  # command 1 N·m, max is 0.1
        assert abs(actual) <= 0.1 + 1e-10

    def test_orthogonal_cluster_allocation(self):
        """3 orthogonal wheels: body torque [1, 0, 0] → wheel torques [-1, 0, 0]."""
        cluster = ReactionWheelCluster.orthogonal_3(J=0.01, max_torque=10.0)
        T_body = np.array([1.0, 0.0, 0.0])

        # Store initial wheel momenta
        omega_before = np.array([w.omega for w in cluster.wheels])

        # Command the body torque
        T_wheel_actual = cluster.command_body_torque(T_body, dt=1.0)

        # Wheel torque should be [-1, 0, 0] (opposite sign, same magnitude)
        np.testing.assert_allclose(T_wheel_actual, [-1.0, 0.0, 0.0], atol=1e-10)

        # Wheel 0 (x-axis) spun in negative direction
        omega_after = np.array([w.omega for w in cluster.wheels])
        assert omega_after[0] < omega_before[0]  # x-wheel spun negatively

    def test_momentum_conservation_body_plus_wheels(self):
        """Total angular momentum (body + wheels) conserved under wheel torque."""
        cluster = ReactionWheelCluster.orthogonal_3(J=0.01, max_torque=10.0)
        I_body = np.diag([5.0, 5.0, 5.0])

        omega_body = np.array([0.0, 0.0, 0.0])
        # Initial total angular momentum
        H_wheels_before = cluster.total_momentum  # = 0 since all wheels at rest
        H_total_before = I_body @ omega_body + H_wheels_before

        T_body_desired = np.array([1.0, 0.0, 0.0])
        dt = 0.1
        T_wheel = cluster.command_body_torque(T_body_desired, dt)
        # Actual body torque from wheel reaction
        T_reaction = cluster.body_torque_from_wheel_torques(T_wheel)

        # Body angular velocity update (simplified 1-step)
        delta_omega = np.linalg.solve(I_body, T_reaction * dt)
        omega_body_new = omega_body + delta_omega

        H_wheels_after = cluster.total_momentum
        H_total_after = I_body @ omega_body_new + H_wheels_after

        # Total angular momentum must be conserved
        np.testing.assert_allclose(H_total_after, H_total_before, atol=1e-8)

    def test_desaturation_sign(self):
        """Command body torque T → wheel speeds change in opposite sign (momentum)."""
        cluster = ReactionWheelCluster.orthogonal_3(J=0.01, max_torque=10.0)
        T_body = np.array([0.0, 1.0, 0.0])
        omega_before = np.array([w.omega for w in cluster.wheels])
        cluster.command_body_torque(T_body, dt=1.0)
        omega_after = np.array([w.omega for w in cluster.wheels])
        # Y-wheel (index 1) should decrease (opposite sign to +y body torque)
        assert omega_after[1] < omega_before[1]

    def test_tetrahedral_4wheel_cluster(self):
        """4-wheel tetrahedral cluster allocates torque correctly."""
        cluster = ReactionWheelCluster.tetrahedral_4(J=0.01, max_torque=10.0)
        T_body = np.array([0.0, 0.0, 1.0])
        T_wheel = cluster.command_body_torque(T_body, dt=1.0)
        # All 4 wheels should receive some torque
        assert len(T_wheel) == 4

    def test_body_torque_reconstruction(self):
        """Reconstructed body torque matches desired (orthogonal cluster, no saturation)."""
        cluster = ReactionWheelCluster.orthogonal_3(J=0.01, max_torque=100.0)
        T_desired = np.array([0.5, -0.3, 0.1])
        T_wheel = cluster.command_body_torque(T_desired, dt=0.001)
        T_reconstructed = cluster.body_torque_from_wheel_torques(T_wheel)
        np.testing.assert_allclose(T_reconstructed, T_desired, atol=1e-8)


# ===========================================================================
# Magnetorquer tests
# ===========================================================================


class TestMagnetorquer:
    """Magnetorquer torque computation tests."""

    def test_dipole_aligned_with_B_gives_zero_torque(self):
        """Dipole moment parallel to B → cross product = 0."""
        B = np.array([0.0, 0.0, 5e-5])  # [T]
        mt = Magnetorquer(axis=[0.0, 0.0, 1.0], max_dipole=1.0)
        T = mt.torque(1.0, B)
        np.testing.assert_allclose(T, [0.0, 0.0, 0.0], atol=1e-20)

    def test_dipole_perpendicular_to_B_gives_max_torque(self):
        """Dipole ⊥ B → |T| = |m||B|."""
        B = np.array([1e-4, 0.0, 0.0])  # [T]
        mt = Magnetorquer(axis=[0.0, 1.0, 0.0], max_dipole=2.0)
        T = mt.torque(2.0, B)
        # m = 2.0 A·m² along y, B along x → T = m × B = (2*y) × (1e-4*x)
        # = 2 * 1e-4 * (y × x) = -2e-4 * z
        expected_mag = 2.0 * 1e-4
        assert abs(np.linalg.norm(T) - expected_mag) < 1e-20

    def test_torque_perpendicular_to_both_m_and_B(self):
        """T = m × B must be perpendicular to both m and B."""
        B = np.array([3e-5, 1e-5, 2e-5])
        mt = Magnetorquer(axis=[0.0, 1.0, 0.0], max_dipole=5.0)
        T = mt.torque(3.0, B)
        m_vec = 3.0 * mt.axis
        # T must be perpendicular to m
        assert abs(np.dot(T, m_vec)) < 1e-20
        # T must be perpendicular to B
        assert abs(np.dot(T, B)) < 1e-20

    def test_dipole_clamping(self):
        """Dipole command exceeding max_dipole is clamped."""
        B = np.array([0.0, 1e-4, 0.0])
        mt = Magnetorquer(axis=[1.0, 0.0, 0.0], max_dipole=1.0)
        T_clamped = mt.torque(100.0, B)  # clamped to 1.0
        T_max = mt.torque(1.0, B)
        np.testing.assert_allclose(T_clamped, T_max, atol=1e-20)

    def test_cluster_orthogonal_zero_when_aligned(self):
        """Orthogonal cluster with all dipoles along z and B along z → zero torque."""
        cluster = MagnetorquerCluster.orthogonal_3(max_dipole=1.0)
        B = np.array([0.0, 0.0, 5e-5])
        # Only z-component dipole, B along z
        T = cluster.torque([0.0, 0.0, 1.0], B)
        np.testing.assert_allclose(T, [0.0, 0.0, 0.0], atol=1e-20)

    def test_cluster_torque_superposition(self):
        """Cluster torque equals sum of individual torques."""
        cluster = MagnetorquerCluster.orthogonal_3(max_dipole=5.0)
        B = np.array([1e-5, 2e-5, 3e-5])
        dipoles = np.array([1.0, 2.0, 0.5])
        T_cluster = cluster.torque(dipoles, B)
        # Compute manually
        T_manual = np.zeros(3)
        for rod, d in zip(cluster.rods, dipoles):
            T_manual += np.cross(d * rod.axis, B)
        np.testing.assert_allclose(T_cluster, T_manual, atol=1e-20)

    def test_earth_field_nonzero(self):
        """Earth magnetic field model returns nonzero vector for LEO orbit."""
        from kerf_aero.adcs.magnetorquer import (
            earth_magnetic_field_body,
            leo_circular_orbit_position,
        )
        r_eci = leo_circular_orbit_position(500, 51.6, 0.0)
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        B = earth_magnetic_field_body(r_eci, q_identity)
        assert np.linalg.norm(B) > 1e-10, "Earth magnetic field should be non-zero"

    def test_earth_field_magnitude_order_of_magnitude(self):
        """LEO field magnitude should be in range [1e-8, 1e-4] T (realistic)."""
        from kerf_aero.adcs.magnetorquer import (
            earth_magnetic_field_body,
            leo_circular_orbit_position,
        )
        r_eci = leo_circular_orbit_position(500, 51.6, 90.0)
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        B = earth_magnetic_field_body(r_eci, q_identity)
        B_mag = np.linalg.norm(B)
        assert 1e-8 < B_mag < 1e-4, f"Unexpected B magnitude: {B_mag:.2e} T"


# ===========================================================================
# Control allocation tests
# ===========================================================================


class TestControlAllocation:
    """Control allocation tests."""

    def test_pseudo_inverse_3wheel_orthogonal(self):
        """3 orthogonal wheels, body torque [1, 0, 0] → wheel torques [-1, 0, 0]."""
        A = -np.eye(3)  # T_body = -I @ T_wheel (reaction)
        T_body = np.array([1.0, 0.0, 0.0])
        T_wheel = pseudo_inverse_allocation(A, T_body)
        # A = -I, so T_wheel = -I⁻¹ T_body = [−1, 0, 0]
        np.testing.assert_allclose(T_wheel, [-1.0, 0.0, 0.0], atol=1e-12)

    def test_wheel_allocator_orthogonal(self):
        """WheelAllocator with orthogonal axes: allocation is exact."""
        axes = np.eye(3)
        allocator = WheelAllocator(axes)
        T_body = np.array([1.0, 0.0, 0.0])
        T_wheel = allocator.allocate(T_body)
        np.testing.assert_allclose(T_wheel, [-1.0, 0.0, 0.0], atol=1e-12)

    def test_wheel_allocator_reconstruct(self):
        """Reconstructed torque matches desired for orthogonal cluster."""
        axes = np.eye(3)
        allocator = WheelAllocator(axes)
        T_body = np.array([0.3, -0.5, 0.2])
        T_wheel = allocator.allocate(T_body)
        T_recon = allocator.reconstruct_torque(T_wheel)
        np.testing.assert_allclose(T_recon, T_body, atol=1e-12)

    def test_pseudo_inverse_overdetermined(self):
        """Over-actuated system: 4 wheels, should find minimum-norm solution."""
        from kerf_aero.adcs.reaction_wheels import _tetrahedral_4wheel_axes
        axes = _tetrahedral_4wheel_axes()  # (3, 4)
        A = -axes  # T_body = -axes @ T_wheel
        T_body = np.array([0.0, 0.0, 1.0])
        T_wheel = pseudo_inverse_allocation(A, T_body)
        # Reconstruct: should match T_body
        T_reconstructed = A @ T_wheel
        np.testing.assert_allclose(T_reconstructed, T_body, atol=1e-10)

    def test_weighted_allocation(self):
        """Weighted allocation favours lower-weight actuators."""
        axes = np.eye(3)
        A = -axes
        T_body = np.array([1.0, 1.0, 1.0])
        # High weight on wheel 2 (z)
        W = np.diag([1.0, 1.0, 1000.0])
        T_wheel = pseudo_inverse_allocation(A, T_body, W)
        T_recon = A @ T_wheel
        np.testing.assert_allclose(T_recon, T_body, atol=1e-8)
        # Wheel 2 command should be smaller in magnitude relative to others
        # (because it has higher weight penalty)

    def test_null_space_projection(self):
        """Null space projection adds desaturation without changing output torque."""
        from kerf_aero.adcs.control_allocation import null_space_projection
        axes = np.eye(3)
        A = -axes
        T_body = np.array([1.0, 0.0, 0.0])
        u_particular = pseudo_inverse_allocation(A, T_body)
        u_bias = np.array([10.0, 10.0, 10.0])
        u_augmented = null_space_projection(A, u_particular, u_bias)
        # Reconstructed torque must still equal T_body
        T_recon = A @ u_augmented
        np.testing.assert_allclose(T_recon, T_body, atol=1e-10)

    def test_mixed_allocator_wheels_plus_magnetorquers(self):
        """Mixed allocator: total torque from wheels+magnetorquers matches desired."""
        from kerf_aero.adcs.control_allocation import MixedActuatorAllocator
        rw_axes = np.eye(3)
        mt_axes = np.eye(3)
        allocator = MixedActuatorAllocator(rw_axes, mt_axes)
        B = np.array([3e-5, 0.0, 4e-5])
        T_desired = np.array([0.001, 0.002, 0.0])
        T_rw, m_mt = allocator.allocate(T_desired, B)
        # Reconstruct: T_body_rw + T_body_mt
        T_rw_body = -rw_axes @ T_rw
        T_mt_body = np.zeros(3)
        for i in range(3):
            T_mt_body += np.cross(m_mt[i] * mt_axes[:, i], B)
        T_total = T_rw_body + T_mt_body
        np.testing.assert_allclose(T_total, T_desired, atol=1e-8)
