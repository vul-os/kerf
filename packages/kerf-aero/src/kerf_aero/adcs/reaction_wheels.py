"""Reaction wheel cluster model for spacecraft attitude control.

A reaction wheel stores angular momentum by spinning a flywheel.
The reaction torque on the spacecraft body is equal and opposite to the
torque applied to the wheel.

Supported cluster configurations:
- 3-wheel orthogonal (axes aligned with body x, y, z)
- 4-wheel tetrahedral (pyramidal, over-actuated)

Convention:
    Wheel spin-up (increasing Ω) produces a reaction torque on the
    spacecraft body in the direction *opposite* to the wheel axis.
    T_body = -A @ T_wheel_cmd
where A is the (3 × N_wheels) axis matrix whose columns are the unit
spin-axis vectors.
"""

import numpy as np
from numpy.typing import ArrayLike


# ---------------------------------------------------------------------------
# Single wheel
# ---------------------------------------------------------------------------

class ReactionWheel:
    """Single reaction wheel.

    Parameters
    ----------
    axis : (3,) unit spin axis in body frame
    J : wheel moment of inertia about spin axis [kg·m²]
    max_torque : maximum torque magnitude [N·m]
    max_momentum : maximum angular momentum magnitude [N·m·s]
    omega0 : initial spin rate [rad/s]
    """

    def __init__(
        self,
        axis: ArrayLike,
        J: float,
        max_torque: float = 0.1,
        max_momentum: float = 30.0,
        omega0: float = 0.0,
    ):
        axis = np.asarray(axis, dtype=float)
        n = np.linalg.norm(axis)
        if n < 1e-15:
            raise ValueError("Spin axis must be non-zero")
        self.axis = axis / n
        self.J = float(J)
        self.max_torque = float(max_torque)
        self.max_momentum = float(max_momentum)
        self.omega = float(omega0)  # wheel spin rate [rad/s]

    @property
    def momentum(self) -> float:
        """Scalar angular momentum stored in wheel [N·m·s]."""
        return self.J * self.omega

    def apply_torque(self, torque_cmd: float, dt: float) -> float:
        """Apply a commanded wheel torque for a time step dt.

        Clamps to max_torque and momentum limits.

        Parameters
        ----------
        torque_cmd : commanded torque on the wheel [N·m]
                     Positive = spin-up in the +axis direction.
        dt : time step [s]

        Returns
        -------
        actual_torque : the torque actually applied [N·m]
        """
        # Clamp to torque saturation
        torque = float(np.clip(torque_cmd, -self.max_torque, self.max_torque))
        # Predict new momentum
        new_omega = self.omega + (torque / self.J) * dt
        max_omega = self.max_momentum / self.J
        if abs(new_omega) > max_omega:
            new_omega = float(np.clip(new_omega, -max_omega, max_omega))
            # Recompute actual torque consistent with new omega
            torque = (new_omega - self.omega) * self.J / dt
        self.omega = new_omega
        return torque


# ---------------------------------------------------------------------------
# Reaction wheel cluster
# ---------------------------------------------------------------------------

def _orthogonal_3wheel_axes() -> np.ndarray:
    """Return the 3×3 axis matrix for a standard orthogonal cluster."""
    return np.eye(3)


def _tetrahedral_4wheel_axes() -> np.ndarray:
    """Return the 3×4 axis matrix for a pyramidal tetrahedral cluster.

    Cone half-angle = arctan(1/sqrt(2)) ≈ 35.26°.
    """
    c = 1.0 / np.sqrt(3.0)
    s = np.sqrt(2.0 / 3.0)
    # Four axes symmetric about z, offset by 90° in azimuth
    axes = np.array([
        [ s,  0, c],
        [ 0,  s, c],
        [-s,  0, c],
        [ 0, -s, c],
    ]).T  # shape (3, 4)
    # Normalise each column
    axes = axes / np.linalg.norm(axes, axis=0)
    return axes


class ReactionWheelCluster:
    """Cluster of reaction wheels.

    Parameters
    ----------
    wheels : list of ReactionWheel
    axes : (3, N) matrix whose *columns* are the unit spin-axis vectors
           in body frame.  Derived from the wheel objects if not given.
    """

    def __init__(self, wheels: list[ReactionWheel]):
        self.wheels = list(wheels)
        n = len(wheels)
        axes = np.zeros((3, n))
        for i, w in enumerate(wheels):
            axes[:, i] = w.axis
        self.axes = axes  # (3, N)
        # Pre-compute pseudo-inverse for control allocation
        self._Apinv = np.linalg.pinv(axes)  # (N, 3)

    @classmethod
    def orthogonal_3(
        cls,
        J: float = 0.01,
        max_torque: float = 0.1,
        max_momentum: float = 30.0,
    ) -> "ReactionWheelCluster":
        """Construct a standard 3-wheel orthogonal cluster."""
        axes = _orthogonal_3wheel_axes()
        wheels = [
            ReactionWheel(axes[:, i], J, max_torque, max_momentum)
            for i in range(3)
        ]
        return cls(wheels)

    @classmethod
    def tetrahedral_4(
        cls,
        J: float = 0.01,
        max_torque: float = 0.1,
        max_momentum: float = 30.0,
    ) -> "ReactionWheelCluster":
        """Construct a 4-wheel tetrahedral cluster."""
        axes = _tetrahedral_4wheel_axes()
        wheels = [
            ReactionWheel(axes[:, i], J, max_torque, max_momentum)
            for i in range(4)
        ]
        return cls(wheels)

    @property
    def wheel_momenta(self) -> np.ndarray:
        """Return array of scalar wheel momenta [N·m·s] (N,)."""
        return np.array([w.momentum for w in self.wheels])

    @property
    def total_momentum(self) -> np.ndarray:
        """Total angular momentum vector in body frame [N·m·s] (3,)."""
        return self.axes @ self.wheel_momenta

    def command_body_torque(self, T_body: ArrayLike, dt: float) -> np.ndarray:
        """Distribute a desired body-frame torque to the wheel cluster.

        Uses Moore-Penrose pseudo-inverse to find the minimum-norm wheel
        torque vector that produces the requested body torque.

        The *reaction* on the spacecraft body is:
            T_body_actual = -A @ T_wheel
        so the wheel torque commands are:
            T_wheel_cmd = -A⁺ @ T_body

        Parameters
        ----------
        T_body : (3,) desired body-frame torque [N·m]
        dt : time step [s]

        Returns
        -------
        T_wheel_actual : (N,) actual torques applied to each wheel [N·m]
        """
        T_body = np.asarray(T_body, dtype=float)
        # Wheel torque commands (negate because reaction)
        T_wheel_cmd = -self._Apinv @ T_body
        T_wheel_actual = np.zeros(len(self.wheels))
        for i, (wheel, cmd) in enumerate(zip(self.wheels, T_wheel_cmd)):
            T_wheel_actual[i] = wheel.apply_torque(cmd, dt)
        return T_wheel_actual

    def body_torque_from_wheel_torques(self, T_wheel: ArrayLike) -> np.ndarray:
        """Compute body torque given wheel torques (reaction: negate).

        T_body = -A @ T_wheel
        """
        return -self.axes @ np.asarray(T_wheel, dtype=float)
