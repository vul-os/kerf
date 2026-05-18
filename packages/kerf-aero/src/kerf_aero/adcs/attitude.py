"""Quaternion attitude representation and rigid-body attitude dynamics.

Quaternion convention: q = (w, x, y, z) where w is the scalar part.
All quaternions are stored as numpy arrays of shape (4,): [w, x, y, z].

Euler's rotation equation (body frame):
    I * omega_dot + omega x (I * omega) = T
where I is the inertia tensor, omega is body angular velocity, T is torque.

Quaternion kinematics:
    q_dot = 0.5 * q ⊗ [0, omega_x, omega_y, omega_z]
"""

import numpy as np
from numpy.typing import ArrayLike


# ---------------------------------------------------------------------------
# Quaternion primitives
# ---------------------------------------------------------------------------

def qnorm(q: np.ndarray) -> float:
    """Return the Euclidean norm of a quaternion."""
    return float(np.sqrt(np.dot(q, q)))


def qnormalize(q: np.ndarray) -> np.ndarray:
    """Return the unit quaternion."""
    n = qnorm(q)
    if n < 1e-15:
        raise ValueError("Cannot normalise a zero quaternion")
    return q / n


def qconjugate(q: np.ndarray) -> np.ndarray:
    """Return q* = (w, -x, -y, -z)."""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def qmultiply(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Hamilton product p ⊗ q.

    Both inputs are [w, x, y, z].
    """
    pw, px, py, pz = p
    qw, qx, qy, qz = q
    return np.array([
        pw * qw - px * qx - py * qy - pz * qz,
        pw * qx + px * qw + py * qz - pz * qy,
        pw * qy - px * qz + py * qw + pz * qx,
        pw * qz + px * qy - py * qx + pz * qw,
    ])


def qrotate(q: np.ndarray, v: ArrayLike) -> np.ndarray:
    """Rotate a 3-vector v by unit quaternion q.

    Uses the sandwich product: v' = q ⊗ [0, v] ⊗ q*
    Returns a 3-vector.
    """
    v = np.asarray(v, dtype=float)
    qv = np.array([0.0, v[0], v[1], v[2]])
    qv_rot = qmultiply(qmultiply(q, qv), qconjugate(q))
    return qv_rot[1:]


def qslerp(q0: np.ndarray, q1: np.ndarray, t: float) -> np.ndarray:
    """Spherical linear interpolation between q0 and q1.

    t=0 → q0, t=1 → q1.
    """
    q0 = qnormalize(q0)
    q1 = qnormalize(q1)
    dot = float(np.dot(q0, q1))
    # Ensure shortest path
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    # Clamp
    dot = min(1.0, dot)
    if dot > 0.9995:
        # Linear interpolation for nearly identical quaternions
        result = q0 + t * (q1 - q0)
        return qnormalize(result)
    theta_0 = np.arccos(dot)
    theta = theta_0 * t
    sin_theta = np.sin(theta)
    sin_theta_0 = np.sin(theta_0)
    s0 = np.cos(theta) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0
    return qnormalize(s0 * q0 + s1 * q1)


def qfrom_axis_angle(axis: ArrayLike, angle: float) -> np.ndarray:
    """Construct a unit quaternion from a rotation axis and angle (radians).

    axis need not be a unit vector — it is normalised internally.
    """
    axis = np.asarray(axis, dtype=float)
    n = np.linalg.norm(axis)
    if n < 1e-15:
        raise ValueError("Axis vector must be non-zero")
    axis = axis / n
    half = angle / 2.0
    return np.array([np.cos(half), *(np.sin(half) * axis)])


def qto_euler(q: np.ndarray) -> np.ndarray:
    """Convert unit quaternion to ZYX Euler angles (roll, pitch, yaw) in radians.

    Returns [roll, pitch, yaw].
    """
    w, x, y, z = q
    # Roll (x-axis rotation)
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = np.arctan2(sinr_cosp, cosr_cosp)
    # Pitch (y-axis rotation)
    sinp = 2.0 * (w * y - z * x)
    sinp = np.clip(sinp, -1.0, 1.0)
    pitch = np.arcsin(sinp)
    # Yaw (z-axis rotation)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = np.arctan2(siny_cosp, cosy_cosp)
    return np.array([roll, pitch, yaw])


def qfrom_dcm(R: ArrayLike) -> np.ndarray:
    """Convert a 3×3 Direction Cosine Matrix (rotation matrix) to a unit quaternion.

    Uses Shepperd's method for numerical stability.
    """
    R = np.asarray(R, dtype=float)
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0.0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return qnormalize(np.array([w, x, y, z]))


def qto_dcm(q: np.ndarray) -> np.ndarray:
    """Convert a unit quaternion to a 3×3 Direction Cosine Matrix."""
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z),   2*(x*y - w*z),     2*(x*z + w*y)],
        [2*(x*y + w*z),       1 - 2*(x*x + z*z),  2*(y*z - w*x)],
        [2*(x*z - w*y),       2*(y*z + w*x),     1 - 2*(x*x + y*y)],
    ])


# ---------------------------------------------------------------------------
# Attitude dynamics
# ---------------------------------------------------------------------------

def _qdot(q: np.ndarray, omega: np.ndarray) -> np.ndarray:
    """Quaternion kinematic equation: q_dot = 0.5 * q ⊗ [0, omega]."""
    omega_quat = np.array([0.0, omega[0], omega[1], omega[2]])
    return 0.5 * qmultiply(q, omega_quat)


def _omega_dot(
    I: np.ndarray,
    omega: np.ndarray,
    torque: np.ndarray,
) -> np.ndarray:
    """Euler's rotation equation: I·ω̇ = T − ω × (I·ω).

    Parameters
    ----------
    I : (3, 3) inertia tensor in body frame [kg·m²]
    omega : (3,) body angular velocity [rad/s]
    torque : (3,) total body-frame torque [N·m]
    """
    I_omega = I @ omega
    return np.linalg.solve(I, torque - np.cross(omega, I_omega))


def _state_derivative(
    state: np.ndarray,
    I: np.ndarray,
    torque: np.ndarray,
) -> np.ndarray:
    """Compute the time derivative of the attitude state vector.

    state = [q_w, q_x, q_y, q_z, omega_x, omega_y, omega_z]  (7,)
    """
    q = state[:4]
    omega = state[4:]
    dq = _qdot(q, omega)
    domega = _omega_dot(I, omega, torque)
    return np.concatenate([dq, domega])


def rk4_step(
    state: np.ndarray,
    I: np.ndarray,
    torque: np.ndarray,
    dt: float,
) -> np.ndarray:
    """Single RK4 integration step for attitude dynamics.

    Parameters
    ----------
    state : (7,) [q_w, q_x, q_y, q_z, omega_x, omega_y, omega_z]
    I : (3, 3) principal inertia tensor [kg·m²]
    torque : (3,) body-frame torque [N·m]
    dt : time step [s]

    Returns
    -------
    new_state : (7,) updated state with re-normalised quaternion
    """
    k1 = _state_derivative(state, I, torque)
    k2 = _state_derivative(state + 0.5 * dt * k1, I, torque)
    k3 = _state_derivative(state + 0.5 * dt * k2, I, torque)
    k4 = _state_derivative(state + dt * k3, I, torque)
    new_state = state + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
    # Re-normalise quaternion part
    new_state[:4] = qnormalize(new_state[:4])
    return new_state


def propagate(
    q0: np.ndarray,
    omega0: np.ndarray,
    I: np.ndarray,
    torque_fn,
    t_span: float,
    dt: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Propagate attitude dynamics forward in time.

    Parameters
    ----------
    q0 : (4,) initial unit quaternion [w, x, y, z]
    omega0 : (3,) initial body angular velocity [rad/s]
    I : (3, 3) inertia tensor [kg·m²]
    torque_fn : callable(t, q, omega) → (3,) body torque [N·m]
    t_span : total simulation time [s]
    dt : integration step [s]

    Returns
    -------
    t_hist : (N,) time history
    q_hist : (N, 4) quaternion history
    omega_hist : (N, 3) angular velocity history
    """
    n_steps = int(np.ceil(t_span / dt))
    t_hist = np.zeros(n_steps + 1)
    q_hist = np.zeros((n_steps + 1, 4))
    omega_hist = np.zeros((n_steps + 1, 3))

    state = np.concatenate([qnormalize(q0), omega0])
    t_hist[0] = 0.0
    q_hist[0] = state[:4]
    omega_hist[0] = state[4:]

    for i in range(n_steps):
        t = t_hist[i]
        torque = torque_fn(t, state[:4], state[4:])
        state = rk4_step(state, I, torque, dt)
        t_hist[i + 1] = t + dt
        q_hist[i + 1] = state[:4]
        omega_hist[i + 1] = state[4:]

    return t_hist, q_hist, omega_hist
