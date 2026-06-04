"""
Tests for kerf_cad_core.controls.state_space

Coverage:
  StateSpace construction and validation
  is_controllable / is_observable
  to_transfer_function (SISO round-trip)
  place_poles (Ackermann)
  lqr (continuous ARE)

References: Kailath (1980); Ackermann (1972); Anderson & Moore (2007); Ogata (2010).
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.controls.state_space import (
    StateSpace,
    is_controllable,
    is_observable,
    controllability_matrix,
    place_poles,
    lqr,
)
from kerf_cad_core.controls.transfer_function import TransferFunction


# ---------------------------------------------------------------------------
# 1. StateSpace construction
# ---------------------------------------------------------------------------

class TestStateSpaceConstruction:
    def test_basic_2x2(self):
        A = np.array([[0.0, 1.0], [0.0, 0.0]])
        B = np.array([[0.0], [1.0]])
        C = np.array([[1.0, 0.0]])
        D = np.array([[0.0]])
        ss = StateSpace(A, B, C, D)
        assert ss.A.shape == (2, 2)
        assert ss.B.shape == (2, 1)

    def test_list_input_converted(self):
        ss = StateSpace(
            A=[[0, 1], [0, 0]],
            B=[[0], [1]],
            C=[[1, 0]],
            D=[[0]],
        )
        assert isinstance(ss.A, np.ndarray)

    def test_non_square_A_raises(self):
        with pytest.raises(ValueError):
            StateSpace(
                A=[[1, 0, 0], [0, 1, 0]],  # 2×3 — not square
                B=[[1], [1]],
                C=[[1, 1]],
                D=[[0]],
            )

    def test_wrong_B_rows_raises(self):
        with pytest.raises(ValueError):
            StateSpace(
                A=[[0, 1], [0, 0]],
                B=[[1]],          # should have 2 rows
                C=[[1, 0]],
                D=[[0]],
            )


# ---------------------------------------------------------------------------
# 2. is_controllable
# ---------------------------------------------------------------------------

class TestControllability:
    def test_controllable_canonical(self):
        """A=[[0,1],[0,0]], B=[[0],[1]] → fully controllable (double integrator)."""
        ss = StateSpace(
            A=[[0.0, 1.0], [0.0, 0.0]],
            B=[[0.0], [1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        assert is_controllable(ss) is True

    def test_not_controllable(self):
        """If B=0 system is uncontrollable."""
        ss = StateSpace(
            A=[[1.0, 0.0], [0.0, 2.0]],
            B=[[0.0], [0.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        assert is_controllable(ss) is False

    def test_controllability_matrix_shape(self):
        """Controllability matrix for n=2, p=1 should be 2×2."""
        ss = StateSpace(
            A=[[0.0, 1.0], [-2.0, -3.0]],
            B=[[0.0], [1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        C_mat = controllability_matrix(ss)
        assert C_mat.shape == (2, 2)


# ---------------------------------------------------------------------------
# 3. is_observable
# ---------------------------------------------------------------------------

class TestObservability:
    def test_observable_canonical(self):
        """Observable canonical form."""
        ss = StateSpace(
            A=[[0.0, 1.0], [-2.0, -3.0]],
            B=[[0.0], [1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        assert is_observable(ss) is True

    def test_not_observable(self):
        """C=0 → not observable."""
        ss = StateSpace(
            A=[[0.0, 1.0], [-1.0, -2.0]],
            B=[[0.0], [1.0]],
            C=[[0.0, 0.0]],
            D=[[0.0]],
        )
        assert is_observable(ss) is False


# ---------------------------------------------------------------------------
# 4. to_transfer_function
# ---------------------------------------------------------------------------

class TestToTransferFunction:
    def test_integrator(self):
        """G(s) = 1/s: A=0, B=1, C=1, D=0."""
        ss = StateSpace(
            A=[[0.0]],
            B=[[1.0]],
            C=[[1.0]],
            D=[[0.0]],
        )
        tf = ss.to_transfer_function()
        # G(j2) = 1/(j2) = -0.5j
        expected = 1.0 / complex(0, 2.0)
        actual = tf.evaluate_at(complex(0, 2.0))
        assert abs(actual - expected) < 0.05  # numerical precision

    def test_second_order(self):
        """G(s)=1/(s²+3s+2) from controllable canonical form."""
        # Standard 2nd order: A=[[-3,-2],[1,0]], B=[[1],[0]], C=[[0,1]], D=[[0]]
        ss = StateSpace(
            A=[[-3.0, -2.0], [1.0, 0.0]],
            B=[[1.0], [0.0]],
            C=[[0.0, 1.0]],
            D=[[0.0]],
        )
        tf = ss.to_transfer_function()
        # G(0) = 1/(0+0+2) = 0.5
        val = tf.evaluate_at(complex(0.0)).real
        assert abs(val - 0.5) < 0.02

    def test_mimo_raises(self):
        """to_transfer_function raises for MIMO systems."""
        ss = StateSpace(
            A=[[0.0, 0.0], [0.0, 0.0]],
            B=[[1.0, 0.0], [0.0, 1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0, 0.0]],
        )
        with pytest.raises(NotImplementedError):
            ss.to_transfer_function()


# ---------------------------------------------------------------------------
# 5. place_poles
# ---------------------------------------------------------------------------

class TestPlacePoles:
    def test_double_integrator_place_poles(self):
        """Double integrator: place poles at -1, -2."""
        A = np.array([[0.0, 1.0], [0.0, 0.0]])
        B = np.array([[0.0], [1.0]])
        desired = [-1.0, -2.0]
        K = place_poles(A, B, desired)
        # Verify closed-loop eigenvalues
        A_cl = A - B @ K.reshape(1, -1)
        cl_eigs = np.sort(np.linalg.eigvals(A_cl).real)
        assert abs(cl_eigs[0] - (-2.0)) < 0.1
        assert abs(cl_eigs[1] - (-1.0)) < 0.1

    def test_place_poles_not_controllable_raises(self):
        """Uncontrollable system raises ValueError."""
        A = np.array([[1.0, 0.0], [0.0, 2.0]])
        B = np.array([[0.0], [0.0]])
        with pytest.raises((ValueError, np.linalg.LinAlgError)):
            place_poles(A, B, [-1.0, -2.0])

    def test_place_poles_mimo_raises(self):
        """MIMO B raises ValueError."""
        A = np.array([[0.0, 1.0], [0.0, 0.0]])
        B = np.array([[1.0, 0.0], [0.0, 1.0]])
        with pytest.raises(ValueError):
            place_poles(A, B, [-1.0, -2.0])


# ---------------------------------------------------------------------------
# 6. LQR
# ---------------------------------------------------------------------------

class TestLqr:
    def test_lqr_returns_gain_and_riccati(self):
        """LQR returns (K, P) with correct shapes."""
        ss = StateSpace(
            A=[[0.0, 1.0], [-1.0, 0.0]],
            B=[[0.0], [1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        Q = np.eye(2)
        R = np.array([[1.0]])
        K, P = lqr(ss, Q, R)
        assert K.shape[1] == 2
        assert P.shape == (2, 2)

    def test_lqr_closed_loop_stable(self):
        """LQR closed-loop A-BK should be stable."""
        ss = StateSpace(
            A=[[0.0, 1.0], [-1.0, 0.0]],
            B=[[0.0], [1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        Q = np.diag([10.0, 1.0])
        R = np.array([[1.0]])
        K, P = lqr(ss, Q, R)
        A_cl = ss.A - ss.B @ K
        eigs = np.linalg.eigvals(A_cl)
        assert np.all(np.real(eigs) < 0), f"Closed-loop eigenvalues: {eigs}"

    def test_lqr_riccati_symmetric(self):
        """P solution should be symmetric."""
        ss = StateSpace(
            A=[[0.0, 1.0], [-2.0, -3.0]],
            B=[[0.0], [1.0]],
            C=[[1.0, 0.0]],
            D=[[0.0]],
        )
        Q = np.eye(2)
        R = np.array([[1.0]])
        K, P = lqr(ss, Q, R)
        assert np.allclose(P, P.T, atol=1e-6), "P is not symmetric"
