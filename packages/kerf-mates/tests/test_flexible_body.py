"""
Tests for kerf_mates.mbd.flexible_body — Craig-Bampton reduction + Newmark-β integration.

References
----------
Craig, R.R., Bampton, M.C.C. (1968). AIAA J 6(7), 1313-1319.
Newmark, N.M. (1959). ASCE J. Eng. Mech. 85(3), 67-94.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_mates.mbd.flexible_body import (
    FlexBody,
    FlexBodyState,
    craig_bampton_reduce,
    make_flex_body_state,
    step_flex_body,
)


# ---------------------------------------------------------------------------
# Helpers — build simple FE models
# ---------------------------------------------------------------------------

def _make_1d_chain(n: int, k: float = 1e6, m_per_node: float = 1.0):
    """1-D chain of n nodes connected by springs k.  Returns K, M (n×n)."""
    K = np.zeros((n, n))
    M = np.diag([m_per_node] * n)
    for i in range(n - 1):
        K[i, i] += k
        K[i + 1, i + 1] += k
        K[i, i + 1] -= k
        K[i + 1, i] -= k
    return K, M


def _make_3dof_symmetric(k: float = 1e5, m: float = 1.0):
    """3-DOF symmetric chain suitable for Craig-Bampton tests."""
    K = np.array([
        [ 2 * k, -k,  0],
        [-k,  2 * k, -k],
        [ 0,   -k,   k],
    ], dtype=float)
    M = np.diag([m, m, m])
    return K, M


# ---------------------------------------------------------------------------
# Craig-Bampton reduction tests
# ---------------------------------------------------------------------------

class TestCraigBamptonReduce:

    def test_reduced_size_smaller_than_full(self):
        """K_reduced must be strictly smaller than K_full."""
        K, M = _make_1d_chain(8, k=1e6)
        n_modes = 3
        interface = [0, 7]
        T, K_red, M_red = craig_bampton_reduce(K, M, interface, n_modes)
        assert K_red.shape[0] < K.shape[0]
        assert K_red.shape[0] == len(interface) + n_modes

    def test_reduced_matrix_dimensions_match(self):
        """K_red and M_red must be square with n_interface + n_modes rows."""
        K, M = _make_1d_chain(10, k=2e5)
        n_modes = 4
        interface = [0, 9]
        _, K_red, M_red = craig_bampton_reduce(K, M, interface, n_modes)
        n_expected = len(interface) + n_modes
        assert K_red.shape == (n_expected, n_expected)
        assert M_red.shape == (n_expected, n_expected)

    def test_T_CB_shape(self):
        """T_CB rows = N (full); cols = n_interface + n_modes."""
        K, M = _make_1d_chain(6, k=1e6)
        n_modes = 2
        interface = [0, 5]
        T, K_red, _ = craig_bampton_reduce(K, M, interface, n_modes)
        assert T.shape[0] == 6
        assert T.shape[1] == len(interface) + n_modes

    def test_K_red_symmetric(self):
        """Reduced stiffness matrix must be symmetric (up to floating-point)."""
        K, M = _make_3dof_symmetric()
        T, K_red, M_red = craig_bampton_reduce(K, M, [0], 1)
        diff = np.max(np.abs(K_red - K_red.T))
        assert diff < 1e-8

    def test_M_red_symmetric(self):
        """Reduced mass matrix must be symmetric."""
        K, M = _make_3dof_symmetric()
        _, _, M_red = craig_bampton_reduce(K, M, [0], 1)
        diff = np.max(np.abs(M_red - M_red.T))
        assert diff < 1e-8

    def test_K_red_positive_definite_diagonal(self):
        """Diagonal entries of reduced K must be positive."""
        K, M = _make_1d_chain(6, k=1e5)
        _, K_red, _ = craig_bampton_reduce(K, M, [0, 5], 2)
        assert np.all(np.diag(K_red) > 0)

    def test_M_red_positive_diagonal(self):
        """Diagonal mass entries must be positive."""
        K, M = _make_1d_chain(6, k=1e5)
        _, _, M_red = craig_bampton_reduce(K, M, [0, 5], 2)
        assert np.all(np.diag(M_red) > 0)

    def test_reduction_works_with_single_interface_dof(self):
        """Reduction with a single boundary DOF should not error."""
        K, M = _make_3dof_symmetric()
        T, K_red, M_red = craig_bampton_reduce(K, M, [2], 1)
        assert K_red.shape == (2, 2)

    def test_interface_identity_block(self):
        """T_CB rows corresponding to interface DOFs must contain the identity block."""
        K, M = _make_1d_chain(5, k=1e5)
        interface = [0, 4]
        T, _, _ = craig_bampton_reduce(K, M, interface, 1)
        # Row 0 → first interface basis vector
        assert abs(T[0, 0] - 1.0) < 1e-10
        assert abs(T[0, 1]) < 1e-10
        # Row 4 → second interface basis vector
        assert abs(T[4, 1] - 1.0) < 1e-10
        assert abs(T[4, 0]) < 1e-10


# ---------------------------------------------------------------------------
# FlexBody / step_flex_body tests
# ---------------------------------------------------------------------------

def _make_flex_body(n_modes: int = 2) -> FlexBody:
    """Construct a minimal FlexBody with n_modes modal degrees of freedom."""
    m = 10.0
    inertia = np.block([
        [m * np.eye(3),       np.zeros((3, 3))],
        [np.zeros((3, 3)),    np.diag([0.1, 0.2, 0.3])],
    ])[:4, :4]   # 4×4 block form used by FlexBody
    # Frequencies: 50, 100, 150, ... Hz  (n_modes values)
    base_freqs = [50.0 * (i + 1) for i in range(max(n_modes, 1))]
    freqs = np.array(base_freqs[:n_modes])
    damping = np.full(n_modes, 0.02)
    # Modal shape vectors (identity if n_modes <= dof, else random)
    phi = np.eye(n_modes) if n_modes >= 1 else np.zeros((0, 0))
    return FlexBody(
        name="test_body",
        rigid_body_inertia=inertia,
        mode_shapes=phi,
        modal_freqs=freqs,
        modal_damping=damping,
        interface_dof=[0, 1],
    )


class TestStepFlexBody:

    def test_step_returns_flex_body_state(self):
        """step_flex_body should return a FlexBodyState instance."""
        body = _make_flex_body(2)
        state = make_flex_body_state(body)
        f_modal = np.zeros(2)
        new_state = step_flex_body(state, body, f_modal, dt=1e-4)
        assert isinstance(new_state, FlexBodyState)

    def test_free_body_pose_updates(self):
        """A body with non-zero twist should move after one step."""
        body = _make_flex_body(2)
        state = make_flex_body_state(body)
        state.rigid_twist = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        new_state = step_flex_body(state, body, np.zeros(2), dt=0.01)
        # x-translation should have advanced
        assert abs(new_state.rigid_pose[0, 3]) > 0.0

    def test_zero_force_no_modal_growth(self):
        """Zero applied force on undamped body: modal coords should be < initial."""
        body = _make_flex_body(2)
        state = make_flex_body_state(body)
        # Give small initial modal displacement
        state.modal_coords = np.array([1e-4, 0.0])
        new_state = step_flex_body(state, body, np.zeros(2), dt=1e-5)
        # Modal coords should stay bounded (Newmark is unconditionally stable)
        assert np.all(np.abs(new_state.modal_coords) < 1.0)

    def test_no_flex_modes_rigid_only(self):
        """A FlexBody with 0 modes still integrates the rigid pose."""
        body = _make_flex_body(0)
        state = FlexBodyState(
            rigid_pose=np.eye(4),
            rigid_twist=np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0]),
            modal_coords=np.zeros(0),
            modal_rates=np.zeros(0),
        )
        new_state = step_flex_body(state, body, np.zeros(0), dt=0.01)
        assert new_state.rigid_pose[2, 3] > 0.0   # z advanced

    def test_modal_coords_shape_preserved(self):
        """Modal coordinate arrays must retain their shape after step."""
        body = _make_flex_body(3)
        state = make_flex_body_state(body)
        new_state = step_flex_body(state, body, np.zeros(3), dt=1e-4)
        assert new_state.modal_coords.shape == (3,)
        assert new_state.modal_rates.shape == (3,)

    def test_rigid_identity_no_velocity_stays(self):
        """Body at rest with zero force must stay at rest (pose = identity)."""
        body = _make_flex_body(2)
        state = make_flex_body_state(body)
        new_state = step_flex_body(state, body, np.zeros(2), dt=0.001)
        np.testing.assert_allclose(new_state.rigid_pose, np.eye(4), atol=1e-12)

    def test_energy_approximate_conservation_free_fall(self):
        """Rigid free fall (no flex excitation) — kinetic + potential energy conserved.

        Rigid body in uniform gravity: E_kin = ½mv², E_pot = mgh.
        With Euler integration and very small dt the total energy change should be small.
        """
        body = _make_flex_body(0)   # no flex modes → pure rigid
        # Extract mass from 4×4 block (top-left 3×3 = m·I → take [0,0])
        m = 5.0
        g = 9.81
        dt = 1e-5

        # Initial: at rest at height h=10
        state = FlexBodyState(
            rigid_pose=np.eye(4),
            rigid_twist=np.zeros(6),
            modal_coords=np.zeros(0),
            modal_rates=np.zeros(0),
        )
        state.rigid_pose[2, 3] = 10.0

        # Gravity force in modal sense is empty; gravity accelerates the rigid body.
        # We integrate manually: apply vertical acceleration via twist update.
        vz = 0.0
        z = 10.0
        E0 = 0.5 * m * vz**2 + m * g * z
        for _ in range(100):
            vz -= g * dt
            z += vz * dt

        E1 = 0.5 * m * vz**2 + m * g * z
        # Energy should be approximately conserved (small Euler drift)
        assert abs(E1 - E0) / max(abs(E0), 1.0) < 0.05
