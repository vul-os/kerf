"""Control allocation for spacecraft ADCS actuators.

Given a desired body-frame torque vector, distribute it to the available
actuators using weighted least-squares / Moore-Penrose pseudo-inverse methods.

Actuator types handled:
- Reaction wheel clusters (via their axis matrix)
- Magnetorquer clusters (field-dependent effectiveness matrix)
- Mixed reaction wheel + magnetorquer allocation

The effectiveness matrix A maps actuator commands u to body torque T:
    T = A @ u
For over-actuated systems (more actuators than DOF), the minimum-norm
solution is:
    u* = A⁺ @ T = Aᵀ (A Aᵀ)⁻¹ T   (right pseudo-inverse)
For weighted least-squares with weight matrix W:
    u* = W A (A W Aᵀ)⁻¹ T
"""

import numpy as np
from numpy.typing import ArrayLike


# ---------------------------------------------------------------------------
# Generic control allocation
# ---------------------------------------------------------------------------

def pseudo_inverse_allocation(
    A: np.ndarray,
    T_desired: ArrayLike,
    W: np.ndarray | None = None,
) -> np.ndarray:
    """Moore-Penrose pseudo-inverse control allocation.

    Solves the minimum-norm least-squares problem:
        min_u  ||W^(1/2) u||²   subject to   A @ u ≈ T_desired

    Parameters
    ----------
    A : (3, N) effectiveness matrix mapping N actuator commands to 3 torques
    T_desired : (3,) desired body-frame torque [N·m]
    W : (N, N) positive-definite weight matrix.  If None, identity is used.

    Returns
    -------
    u : (N,) actuator commands (e.g., wheel torques [N·m] or dipoles [A·m²])
    """
    T_desired = np.asarray(T_desired, dtype=float)
    if W is None:
        u = np.linalg.pinv(A) @ T_desired
    else:
        # Weighted pseudo-inverse: u* = W A^T (A W A^T)^{-1} T
        AW = A @ W
        AWAt = AW @ A.T
        try:
            AWAt_inv = np.linalg.inv(AWAt)
        except np.linalg.LinAlgError:
            AWAt_inv = np.linalg.pinv(AWAt)
        u = W @ A.T @ AWAt_inv @ T_desired
    return u


def null_space_projection(
    A: np.ndarray,
    u_particular: np.ndarray,
    u_bias: ArrayLike,
) -> np.ndarray:
    """Project a bias vector onto the null space of A and add to u_particular.

    Useful for momentum management: add a desaturation component without
    affecting the output torque.

    Parameters
    ----------
    A : (3, N) effectiveness matrix
    u_particular : (N,) particular solution from control allocation
    u_bias : (N,) desired bias in actuator command space (e.g., desaturation)

    Returns
    -------
    u : (N,) augmented command
    """
    u_bias = np.asarray(u_bias, dtype=float)
    # Null-space projector: N = I - A⁺ A
    Apinv = np.linalg.pinv(A)
    N = np.eye(A.shape[1]) - Apinv @ A
    return u_particular + N @ u_bias


# ---------------------------------------------------------------------------
# Mixed actuator allocation
# ---------------------------------------------------------------------------

class MixedActuatorAllocator:
    """Allocate body torque across reaction wheels and magnetorquers.

    Since magnetorquer effectiveness depends on the local B field, the
    allocation must be recomputed at each time step.

    Parameters
    ----------
    rw_axes : (3, Nrw) reaction wheel spin axes in body frame
    mt_axes : (3, Nmt) magnetorquer dipole axes in body frame
    rw_weights : (Nrw,) actuator weight for each reaction wheel
    mt_weights : (Nmt,) actuator weight for each magnetorquer
    """

    def __init__(
        self,
        rw_axes: np.ndarray,
        mt_axes: np.ndarray,
        rw_weights: np.ndarray | None = None,
        mt_weights: np.ndarray | None = None,
    ):
        self.rw_axes = np.asarray(rw_axes, dtype=float)
        self.mt_axes = np.asarray(mt_axes, dtype=float)
        n_rw = self.rw_axes.shape[1]
        n_mt = self.mt_axes.shape[1]
        self.rw_weights = rw_weights if rw_weights is not None else np.ones(n_rw)
        self.mt_weights = mt_weights if mt_weights is not None else np.ones(n_mt) * 10.0

    def allocate(
        self,
        T_desired: ArrayLike,
        B_body: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Allocate desired body torque.

        Parameters
        ----------
        T_desired : (3,) desired body torque [N·m]
        B_body : (3,) local magnetic field in body frame [T]

        Returns
        -------
        T_rw_cmd : (Nrw,) reaction wheel torque commands [N·m]
                   (convention: reaction on body, so wheel speeds change
                    in the opposite sign)
        m_mt_cmd : (Nmt,) magnetorquer dipole commands [A·m²]
        """
        T_desired = np.asarray(T_desired, dtype=float)
        n_rw = self.rw_axes.shape[1]
        n_mt = self.mt_axes.shape[1]

        # Magnetorquer effectiveness: A_mt[:,i] = axis_i × B
        A_mt = np.zeros((3, n_mt))
        for i in range(n_mt):
            A_mt[:, i] = np.cross(self.mt_axes[:, i], B_body)

        # Reaction wheel: T_body = -A_rw @ T_wheel (reaction), so
        # effectiveness matrix for wheel torques on body: A_rw = -rw_axes
        A_rw = -self.rw_axes  # (3, Nrw)

        # Combined effectiveness matrix
        A = np.hstack([A_rw, A_mt])  # (3, Nrw + Nmt)
        W = np.diag(np.concatenate([self.rw_weights, self.mt_weights]))

        u = pseudo_inverse_allocation(A, T_desired, W)
        T_rw_cmd = u[:n_rw]
        m_mt_cmd = u[n_rw:]
        return T_rw_cmd, m_mt_cmd


# ---------------------------------------------------------------------------
# Reaction-wheel-only allocator (convenience wrapper)
# ---------------------------------------------------------------------------

class WheelAllocator:
    """Minimum-norm torque allocation for a reaction wheel cluster.

    Body torque = -A_rw @ T_wheel, so:
        T_wheel = -A_rw⁺ @ T_body
    """

    def __init__(self, axes: np.ndarray, weights: np.ndarray | None = None):
        """
        Parameters
        ----------
        axes : (3, N) spin axes in body frame
        weights : (N,) non-negative weights (lower = preferred)
        """
        self.axes = np.asarray(axes, dtype=float)
        n = self.axes.shape[1]
        self.W = np.diag(weights) if weights is not None else np.eye(n)
        self._Apinv = np.linalg.pinv(self.axes)

    def allocate(self, T_body: ArrayLike) -> np.ndarray:
        """Return wheel torque commands for desired body torque.

        T_wheel_cmd = -axes⁺ @ T_body
        """
        return -self._Apinv @ np.asarray(T_body, dtype=float)

    def reconstruct_torque(self, T_wheel: ArrayLike) -> np.ndarray:
        """Reconstruct body torque from wheel torques.

        T_body = -axes @ T_wheel
        """
        return -self.axes @ np.asarray(T_wheel, dtype=float)
