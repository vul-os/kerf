"""
6-DOF rigid-body equations of motion with quaternion attitude.

State vector (13 elements):
    [0]  x   — Earth-frame position, North (m)
    [1]  y   — Earth-frame position, East (m)
    [2]  z   — Earth-frame position, Down (m)  (positive down, NED convention)
    [3]  u   — body-frame velocity, forward (m/s)
    [4]  v   — body-frame velocity, right (m/s)
    [5]  w   — body-frame velocity, down (m/s)
    [6]  q0  — quaternion scalar part
    [7]  q1  — quaternion vector part x
    [8]  q2  — quaternion vector part y
    [9]  q3  — quaternion vector part z
    [10] p   — body roll rate (rad/s)
    [11] q   — body pitch rate (rad/s)
    [12] r   — body yaw rate (rad/s)

The quaternion q = (q0, q1, q2, q3) represents the rotation from body to Earth
(NED inertial) frame: v_Earth = q ⊗ v_body ⊗ q*.

Altitude above sea level (geometric, positive up) is recovered as:
    h = -z   (z is Down)

References:
    Stevens & Lewis, "Aircraft Simulation and Systems", 3rd ed.
    Zipfel, "Modeling and Simulation of Aerospace Vehicle Dynamics", 3rd ed.
"""

from __future__ import annotations

import math
from typing import Callable, NamedTuple, Sequence

# Standard gravity m/s²
_G0: float = 9.80665

# Number of state variables
STATE_DIM: int = 13


class SixDOFState(NamedTuple):
    """Named accessor for the 6-DOF state vector."""
    x: float    # North (m)
    y: float    # East (m)
    z: float    # Down (m)
    u: float    # body forward velocity (m/s)
    v: float    # body lateral velocity (m/s)
    w: float    # body vertical velocity (m/s)
    q0: float   # quaternion scalar
    q1: float   # quaternion i
    q2: float   # quaternion j
    q3: float   # quaternion k
    p: float    # roll rate (rad/s)
    q_ang: float  # pitch rate (rad/s)
    r: float    # yaw rate (rad/s)

    @property
    def altitude_m(self) -> float:
        """Geometric altitude above sea level (m, positive up)."""
        return -self.z

    @property
    def airspeed_m_s(self) -> float:
        """Body-frame total airspeed magnitude (m/s)."""
        return math.sqrt(self.u**2 + self.v**2 + self.w**2)

    @property
    def alpha_rad(self) -> float:
        """Angle of attack (rad).  Defined only when u > 0."""
        return math.atan2(self.w, self.u)

    @property
    def beta_rad(self) -> float:
        """Sideslip angle (rad)."""
        V = self.airspeed_m_s
        if V < 1e-12:
            return 0.0
        return math.asin(max(-1.0, min(1.0, self.v / V)))


class Forces(NamedTuple):
    """External forces (N) and moments (N·m) in the body frame."""
    Fx: float   # body X (forward)
    Fy: float   # body Y (right)
    Fz: float   # body Z (down)
    Mx: float   # roll moment (positive right-wing-down)
    My: float   # pitch moment (positive nose-up)
    Mz: float   # yaw moment (positive nose-right)


class RigidBody(NamedTuple):
    """Mass and inertia properties of the aircraft."""
    mass_kg: float
    Ixx: float   # kg·m²
    Iyy: float   # kg·m²
    Izz: float   # kg·m²
    Ixz: float   # kg·m²  (cross product of inertia; Ixy=Iyz=0 for symmetric)


def state_from_array(arr: Sequence[float]) -> SixDOFState:
    """Convert a plain 13-element sequence to a :class:`SixDOFState`."""
    return SixDOFState(*arr[:13])  # type: ignore[arg-type]


def state_to_array(s: SixDOFState) -> list[float]:
    """Convert a :class:`SixDOFState` to a plain list."""
    return [s.x, s.y, s.z, s.u, s.v, s.w, s.q0, s.q1, s.q2, s.q3, s.p, s.q_ang, s.r]


# ---------------------------------------------------------------------------
# Quaternion helpers
# ---------------------------------------------------------------------------

def _quat_norm(q0: float, q1: float, q2: float, q3: float) -> float:
    return math.sqrt(q0**2 + q1**2 + q2**2 + q3**2)


def _quat_normalise(q: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in q))
    if n < 1e-15:
        return [1.0, 0.0, 0.0, 0.0]
    return [x / n for x in q]


def _quat_derivative(
    q0: float, q1: float, q2: float, q3: float,
    p: float, q: float, r: float,
) -> tuple[float, float, float, float]:
    """
    Quaternion kinematics:  dq/dt = 0.5 · Ω(ω) · q

    where Ω is the skew-symmetric angular velocity matrix.
    """
    dq0 = 0.5 * (-q1 * p - q2 * q - q3 * r)
    dq1 = 0.5 * ( q0 * p - q3 * q + q2 * r)
    dq2 = 0.5 * ( q3 * p + q0 * q - q1 * r)
    dq3 = 0.5 * (-q2 * p + q1 * q + q0 * r)
    return dq0, dq1, dq2, dq3


def quat_to_euler(q0: float, q1: float, q2: float, q3: float) -> tuple[float, float, float]:
    """
    Convert quaternion to Euler angles (roll φ, pitch θ, yaw ψ) in radians.

    Returns (phi, theta, psi) in radians.
    """
    phi   = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1**2 + q2**2))
    sin_t = 2.0 * (q0 * q2 - q3 * q1)
    sin_t = max(-1.0, min(1.0, sin_t))
    theta = math.asin(sin_t)
    psi   = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2**2 + q3**2))
    return phi, theta, psi


def euler_to_quat(phi: float, theta: float, psi: float) -> tuple[float, float, float, float]:
    """
    Convert Euler angles (roll, pitch, yaw) in radians to a unit quaternion.

    Returns (q0, q1, q2, q3).
    """
    c_phi_2   = math.cos(phi   / 2.0)
    s_phi_2   = math.sin(phi   / 2.0)
    c_theta_2 = math.cos(theta / 2.0)
    s_theta_2 = math.sin(theta / 2.0)
    c_psi_2   = math.cos(psi   / 2.0)
    s_psi_2   = math.sin(psi   / 2.0)

    q0 = c_phi_2 * c_theta_2 * c_psi_2 + s_phi_2 * s_theta_2 * s_psi_2
    q1 = s_phi_2 * c_theta_2 * c_psi_2 - c_phi_2 * s_theta_2 * s_psi_2
    q2 = c_phi_2 * s_theta_2 * c_psi_2 + s_phi_2 * c_theta_2 * s_psi_2
    q3 = c_phi_2 * c_theta_2 * s_psi_2 - s_phi_2 * s_theta_2 * c_psi_2
    return q0, q1, q2, q3


# ---------------------------------------------------------------------------
# Gravity in body frame
# ---------------------------------------------------------------------------

def _gravity_body(
    q0: float, q1: float, q2: float, q3: float, mass_kg: float
) -> tuple[float, float, float]:
    """
    Return gravity force components in the body frame (N).

    g_body = C_BE · [0, 0, g0]^T  where C_BE is body-from-earth DCM.
    Using quaternion: rotate the NED gravity vector into body frame.
    """
    # Earth-frame gravity vector (NED, down-positive): (0, 0, g0)
    gx_e, gy_e, gz_e = 0.0, 0.0, _G0

    # Active rotation: v_body = q* ⊗ v_earth ⊗ q
    # For a pure vector rotated by quaternion:
    # v_body_x = (1 - 2(q2²+q3²)) gx + 2(q1q2+q0q3) gy + 2(q1q3-q0q2) gz
    # v_body_y = 2(q1q2-q0q3) gx + (1-2(q1²+q3²)) gy + 2(q2q3+q0q1) gz
    # v_body_z = 2(q1q3+q0q2) gx + 2(q2q3-q0q1) gy + (1-2(q1²+q2²)) gz

    gfx = ((1.0 - 2.0*(q2**2 + q3**2)) * gx_e
           + 2.0*(q1*q2 + q0*q3) * gy_e
           + 2.0*(q1*q3 - q0*q2) * gz_e)
    gfy = (2.0*(q1*q2 - q0*q3) * gx_e
           + (1.0 - 2.0*(q1**2 + q3**2)) * gy_e
           + 2.0*(q2*q3 + q0*q1) * gz_e)
    gfz = (2.0*(q1*q3 + q0*q2) * gx_e
           + 2.0*(q2*q3 - q0*q1) * gy_e
           + (1.0 - 2.0*(q1**2 + q2**2)) * gz_e)

    return mass_kg * gfx, mass_kg * gfy, mass_kg * gfz


# ---------------------------------------------------------------------------
# Equations of motion
# ---------------------------------------------------------------------------

def eom(
    state: list[float],
    forces: Forces,
    body: RigidBody,
) -> list[float]:
    """
    Compute the state derivative d(state)/dt.

    Parameters
    ----------
    state:
        13-element list [x, y, z, u, v, w, q0, q1, q2, q3, p, q_ang, r].
    forces:
        External (aerodynamic + thrust) forces and moments in the body frame.
        Gravity is added internally from the quaternion attitude.
    body:
        Rigid-body mass and inertia properties.

    Returns
    -------
    list[float]
        13-element derivative vector.
    """
    x, y, z, u, v, w, q0, q1, q2, q3, p, q_ang, r = state

    m   = body.mass_kg
    Ixx = body.Ixx
    Iyy = body.Iyy
    Izz = body.Izz
    Ixz = body.Ixz

    # ---- Gravity in body frame ----------------------------------------
    Fgx, Fgy, Fgz = _gravity_body(q0, q1, q2, q3, m)

    # ---- Total body-frame forces ---------------------------------------
    Fx_tot = forces.Fx + Fgx
    Fy_tot = forces.Fy + Fgy
    Fz_tot = forces.Fz + Fgz

    # ---- Translational EOM (body frame) --------------------------------
    # Newton: m * (dV/dt + ω × V) = F_total
    du = Fx_tot / m + r * v - q_ang * w
    dv = Fy_tot / m - r * u + p * w
    dw = Fz_tot / m + q_ang * u - p * v

    # ---- Rotational EOM (Euler's equations with Ixz cross term) -------
    # I·dω/dt + ω × (I·ω) = M
    # For symmetric aircraft (Ixy = Iyz = 0, Ixz ≠ 0):
    Gamma = Ixx * Izz - Ixz**2
    dp = (Izz * forces.Mx + Ixz * forces.Mz
          - (Izz * (Izz - Iyy) - Ixz**2) * q_ang * r
          + Ixz * (Ixx - Iyy + Izz) * p * q_ang) / Gamma
    dq = (forces.My
          - (Ixx - Izz) * p * r
          + Ixz * (p**2 - r**2)) / Iyy
    dr = (Ixx * forces.Mz + Ixz * forces.Mx
          - (Ixx * (Ixx - Iyy) + Ixz**2) * p * q_ang
          + (Izz * (Izz - Iyy) - Ixz**2) * q_ang * r) / Gamma

    # ---- Quaternion kinematics ----------------------------------------
    dq0, dq1, dq2, dq3 = _quat_derivative(q0, q1, q2, q3, p, q_ang, r)

    # ---- Position kinematics (body → Earth/NED) -----------------------
    # v_earth = C_EB · v_body  (rotation by quaternion: body-to-earth)
    # x_dot = (1-2(q2²+q3²))u + 2(q1q2-q0q3)v + 2(q1q3+q0q2)w
    # y_dot = 2(q1q2+q0q3)u + (1-2(q1²+q3²))v + 2(q2q3-q0q1)w
    # z_dot = 2(q1q3-q0q2)u + 2(q2q3+q0q1)v + (1-2(q1²+q2²))w

    dx = ((1.0 - 2.0*(q2**2 + q3**2)) * u
          + 2.0*(q1*q2 - q0*q3) * v
          + 2.0*(q1*q3 + q0*q2) * w)
    dy = (2.0*(q1*q2 + q0*q3) * u
          + (1.0 - 2.0*(q1**2 + q3**2)) * v
          + 2.0*(q2*q3 - q0*q1) * w)
    dz = (2.0*(q1*q3 - q0*q2) * u
          + 2.0*(q2*q3 + q0*q1) * v
          + (1.0 - 2.0*(q1**2 + q2**2)) * w)

    return [dx, dy, dz, du, dv, dw, dq0, dq1, dq2, dq3, dp, dq, dr]


# ---------------------------------------------------------------------------
# RK4 integrator
# ---------------------------------------------------------------------------

ForceModel = Callable[[float, list[float]], Forces]
"""
Signature for a force model callback::

    forces = force_model(t, state) -> Forces

*t* is the current simulation time (s), *state* is the 13-element list.
"""


def _add_scaled(a: list[float], b: list[float], scale: float) -> list[float]:
    return [ai + scale * bi for ai, bi in zip(a, b)]


def rk4_step(
    t: float,
    state: list[float],
    dt: float,
    force_model: ForceModel,
    body: RigidBody,
    normalise_quat: bool = True,
) -> list[float]:
    """
    Advance the state by one RK4 step of size *dt*.

    Parameters
    ----------
    t:
        Current simulation time (s).
    state:
        13-element state vector at time *t*.
    dt:
        Time step (s).
    force_model:
        Callable ``(t, state) -> Forces`` returning applied aerodynamic +
        thrust forces/moments in the body frame (gravity excluded — added
        internally by :func:`eom`).
    body:
        Mass and inertia properties.
    normalise_quat:
        Re-normalise the quaternion after integration (recommended).

    Returns
    -------
    list[float]
        New 13-element state vector at time *t + dt*.
    """
    f1 = eom(state,
             force_model(t, state), body)

    s2 = _add_scaled(state, f1, 0.5 * dt)
    f2 = eom(s2,
             force_model(t + 0.5 * dt, s2), body)

    s3 = _add_scaled(state, f2, 0.5 * dt)
    f3 = eom(s3,
             force_model(t + 0.5 * dt, s3), body)

    s4 = _add_scaled(state, f3, dt)
    f4 = eom(s4,
             force_model(t + dt, s4), body)

    new_state = [
        si + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        for si, k1, k2, k3, k4 in zip(state, f1, f2, f3, f4)
    ]

    if normalise_quat:
        qn = _quat_normalise(new_state[6:10])
        new_state[6:10] = qn

    return new_state


def integrate(
    t0: float,
    state0: list[float],
    dt: float,
    n_steps: int,
    force_model: ForceModel,
    body: RigidBody,
    normalise_quat: bool = True,
) -> tuple[list[float], list[list[float]]]:
    """
    Integrate the 6-DOF EOM for *n_steps* steps of size *dt*.

    Parameters
    ----------
    t0:
        Initial time (s).
    state0:
        Initial 13-element state vector.
    dt:
        Time step (s).
    n_steps:
        Number of integration steps.
    force_model:
        Force model callback.
    body:
        Mass/inertia.
    normalise_quat:
        Re-normalise quaternion after each step.

    Returns
    -------
    times:
        List of *n_steps + 1* time values.
    states:
        List of *n_steps + 1* state vectors.
    """
    times: list[float] = [t0]
    states: list[list[float]] = [list(state0)]

    t = t0
    s = list(state0)
    for _ in range(n_steps):
        s = rk4_step(t, s, dt, force_model, body, normalise_quat=normalise_quat)
        t += dt
        times.append(t)
        states.append(s)

    return times, states


# ---------------------------------------------------------------------------
# Convenience: build a standard level-flight state
# ---------------------------------------------------------------------------

def level_flight_state(
    airspeed_m_s: float,
    altitude_m: float,
    heading_rad: float = 0.0,
    flight_path_angle_rad: float = 0.0,
    alpha_rad: float = 0.0,
) -> list[float]:
    """
    Return a 13-element state vector for unaccelerated level (or climbing) flight.

    The aircraft is oriented at the given angle of attack relative to the
    velocity vector; the body axes are rotated accordingly.

    Parameters
    ----------
    airspeed_m_s:
        Total airspeed (m/s).
    altitude_m:
        Geometric altitude above sea level (m).
    heading_rad:
        Heading (rad), measured from North, clockwise positive.
    flight_path_angle_rad:
        Flight path angle (rad); positive up.
    alpha_rad:
        Angle of attack (rad); pitch = gamma + alpha.

    Returns
    -------
    list[float]
        13-element state [x, y, z, u, v, w, q0, q1, q2, q3, p, q_ang, r].
    """
    pitch = flight_path_angle_rad + alpha_rad
    roll  = 0.0
    psi   = heading_rad

    q0, q1, q2, q3 = euler_to_quat(roll, pitch, psi)

    # Body velocities: forward speed u; no sideslip; w from alpha
    u = airspeed_m_s * math.cos(alpha_rad)
    v = 0.0
    w = airspeed_m_s * math.sin(alpha_rad)

    z = -altitude_m  # NED: down is positive

    return [0.0, 0.0, z, u, v, w, q0, q1, q2, q3, 0.0, 0.0, 0.0]
