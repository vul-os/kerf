"""
Analytic oracle tests for kerf_motion.inverse_dynamics.

Coordinate conventions used in these tests
-------------------------------------------
- Joint axis: Z (0,0,1) — rotation in the XY plane.
- Link reference direction: +X at q=0.
- Gravity: (0, −g, 0) — standard "down" is −Y.

At angle q (measured CCW from +X about +Z), the CoM of a link whose
un-rotated tip points along +X sits at:
    r_com_world = (r·cos q,  r·sin q,  0)

The gravitational torque about the joint origin (Z component):
    τ_gravity = r_com × F_gravity  |_z
              = (r·cos q, r·sin q, 0) × (0, −mg, 0)  |_z
              = −mg·r·cos q    [gravity EXERTS this on the arm]

The torque REQUIRED to HOLD the arm (counteract gravity):
    τ_hold = +m·g·r_com·cos q

So the oracle formula is  τ = m·g·r_com·cos(q)  (with gravity=(0,−g,0)).

The classical  τ = m·g·r_com·sin(q)  formula (seen in many textbooks) uses
a different q convention: there q=0 means the arm hangs *down* (−Y), i.e.
q is measured from the downward vertical.  Those two conventions give
cos(q_from_horiz) = sin(q_from_vert); both are physically correct — just
different angle references.  We test the horizontal-reference convention
because it maps directly to RevoluteJoint(angle=q).

Tests
-----
1. Single-link gravity compensation: τ = m·g·(L/2)·cos(q)
2. Static at upright (q=π/2, arm pointing +Y): τ_gravity = 0
3. Free fall (zero gravity + zero acceleration): all torques = 0
4. Trajectory round-trip: sinusoidal trajectory through inverse dynamics
   matches expected torques from the equation of motion.

References
----------
Featherstone, R. (2008). Rigid Body Dynamics Algorithms. §5.3
Craig, J.J. (2005). Introduction to Robotics. §6.4 (eq. 6.45)
Meriam & Kraige, Engineering Mechanics: Dynamics, 8th ed. §6/7
"""

from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# Helper — build single-link robot
# ---------------------------------------------------------------------------

def _make_single_link_robot(mass: float, length: float):
    """
    Single revolute joint, rotation about Z, link along +X at q=0.
    Uniform rod: I_zz = m·L²/12 about CoM; CoM at (L/2, 0, 0) in link frame.
    """
    from kerf_motion.joints import RevoluteJoint
    from kerf_motion.inverse_dynamics import Robot

    joint = RevoluteJoint(
        parent_idx=0,
        child_idx=1,
        axis=(0.0, 0.0, 1.0),
        parent_offset=(0.0, 0.0, 0.0),
        name="j0",
    )
    I_zz = mass * length ** 2 / 12.0
    inertia = ((I_zz, 0.0, 0.0), (0.0, I_zz, 0.0), (0.0, 0.0, I_zz))
    return Robot(
        joints=[joint],
        link_masses=[mass],
        link_inertias=[inertia],
        com_offsets=[(length / 2.0, 0.0, 0.0)],
    )


# ===========================================================================
# Test 1 — Single-link gravity compensation
# ===========================================================================

def test_single_link_gravity_compensation():
    """
    Gravity compensation for a single revolute link:
        τ = m·g·(L/2)·cos(q)

    With gravity = (0,−g,0) and the arm at angle q from +X (q=0 = horizontal),
    the torque required to hold the arm against gravity is m·g·r_com·cos(q).

    Oracle: closed-form cross-product derivation (see module docstring).
    Tolerance: 1e-6 absolute.

    Reference: Craig §6.4; Featherstone §5.3.
    """
    from kerf_motion.inverse_dynamics import gravity_compensation

    m = 2.0    # kg
    L = 1.0    # m
    g = 9.81   # m/s²
    gravity = (0.0, -g, 0.0)

    robot = _make_single_link_robot(m, L)

    for q_val in [0.1, 0.3, 0.5, 0.785, 1.0, 1.5]:
        tau = gravity_compensation(robot, [q_val], gravity=gravity)
        # Analytic: τ = m·g·(L/2)·cos(q)
        tau_analytic = m * g * (L / 2.0) * math.cos(q_val)
        err = abs(tau[0] - tau_analytic)
        assert err < 1e-6, (
            f"q={q_val:.3f}: τ_RNE={tau[0]:.10f}, τ_analytic={tau_analytic:.10f}, "
            f"err={err:.3e}"
        )


# ===========================================================================
# Test 2 — Static at upright (q=π/2): τ_gravity = 0
# ===========================================================================

def test_single_link_upright_zero_torque():
    """
    At q=π/2 the link points along +Y (straight up, anti-gravity direction).
    With gravity in −Y, the CoM is directly above the joint — moment arm is
    zero — so τ = 0.

    τ = m·g·(L/2)·cos(π/2) = 0

    This is the 'balanced at vertical' special case; even a tiny numerical
    error here would indicate a forward-pass or moment-propagation bug.
    """
    from kerf_motion.inverse_dynamics import gravity_compensation

    m = 5.0
    L = 0.8
    g = 9.80665
    gravity = (0.0, -g, 0.0)

    robot = _make_single_link_robot(m, L)
    tau = gravity_compensation(robot, [math.pi / 2.0], gravity=gravity)

    assert abs(tau[0]) < 1e-12, (
        f"Expected τ=0 at q=π/2 (arm vertical), got τ={tau[0]:.3e}"
    )


# ===========================================================================
# Test 3 — Free fall: zero gravity + zero acceleration → all torques = 0
# ===========================================================================

def test_free_fall_zero_torques():
    """
    With gravity=(0,0,0) and all velocities/accelerations=0, the system
    is in a state of zero dynamics.  All joint torques must be exactly 0.

    This tests the degenerate case and verifies that no spurious forces
    are generated from the implementation.

    Reference: Featherstone §5.3 — when a_0 = 0 and q̇ = q̈ = 0, all
    link forces reduce to zero.
    """
    from kerf_motion.inverse_dynamics import recursive_newton_euler

    m = 3.0
    L = 1.2
    robot = _make_single_link_robot(m, L)

    for q_val in [0.0, 0.5, 1.0, -0.7, math.pi / 4]:
        tau = recursive_newton_euler(
            robot,
            q=[q_val],
            q_dot=[0.0],
            q_ddot=[0.0],
            gravity=(0.0, 0.0, 0.0),
        )
        assert abs(tau[0]) < 1e-12, (
            f"q={q_val:.3f}: expected τ=0 with zero gravity/motion, got {tau[0]:.3e}"
        )


# ===========================================================================
# Test 4 — Trajectory round-trip (sinusoidal)
# ===========================================================================

def test_trajectory_round_trip_sinusoidal():
    """
    Sinusoidal trajectory for a single-link pendulum:
        q(t)   = A·sin(ω·t)
        q̇(t)  = A·ω·cos(ω·t)
        q̈(t) = −A·ω²·sin(ω·t)

    Equation of motion for a uniform rod link (joint as pivot):
        τ(t) = I_pivot·q̈ + m·g·r_com·cos(q)
    where I_pivot = m·L²/3 (parallel-axis from CoM).

    With gravity = (0,−g,0) and the arm starting horizontal (q=0):
    - Inertial contribution: I_pivot · q̈
    - Gravity contribution: m·g·r_com·cos(q)

    Both the RNE result and the analytic formula are computed and compared.
    The test also exercises ``compute_joint_torques_from_trajectory``.

    Tolerance: 1% relative error (sinusoidal excitation, moderate amplitude).

    Reference: Featherstone §5.3; Craig §6.4 eq (6.45).
    """
    from kerf_motion.inverse_dynamics import (
        recursive_newton_euler,
        compute_joint_torques_from_trajectory,
    )

    m = 2.0
    L = 1.0
    g = 9.81
    gravity = (0.0, -g, 0.0)

    robot = _make_single_link_robot(m, L)

    # Inertia about the joint (parallel-axis theorem):
    r_com = L / 2.0
    I_com_zz = m * L ** 2 / 12.0
    I_pivot = I_com_zz + m * r_com ** 2   # = m·L²/3

    A = 0.5          # amplitude (rad)
    omega_traj = 2.0 # rad/s
    dt = 0.01
    t_vals = [i * dt for i in range(200)]

    trajectory = []
    for t in t_vals:
        q_t = A * math.sin(omega_traj * t)
        qd_t = A * omega_traj * math.cos(omega_traj * t)
        qdd_t = -A * omega_traj ** 2 * math.sin(omega_traj * t)
        trajectory.append((t, [q_t], [qd_t], [qdd_t]))

    # Compute via vectorised function
    torques = compute_joint_torques_from_trajectory(robot, trajectory, gravity=gravity)

    for idx, (t, q_t_tup, qd_t_tup, qdd_t_tup) in enumerate(trajectory):
        q_t = q_t_tup[0]
        qdd_t = qdd_t_tup[0]

        tau_rne = torques[idx][0]

        # Analytic: τ = I_pivot·q̈ + m·g·r_com·cos(q)
        tau_analytic = I_pivot * qdd_t + m * g * r_com * math.cos(q_t)

        # Use absolute tolerance near zero, relative elsewhere
        denom = max(abs(tau_analytic), 0.1)
        rel_err = abs(tau_rne - tau_analytic) / denom
        assert rel_err < 0.01, (
            f"t={t:.3f}: τ_RNE={tau_rne:.8f}, τ_analytic={tau_analytic:.8f}, "
            f"rel_err={rel_err:.3e}"
        )

    # Spot-check: direct call must match vectorised call
    step = trajectory[50]
    tau_direct = recursive_newton_euler(robot, step[1], step[2], step[3], gravity)
    assert abs(tau_direct[0] - torques[50][0]) < 1e-15, "Direct vs vectorised mismatch"


# ===========================================================================
# Additional robustness tests
# ===========================================================================

def test_robot_constructor_validates_lengths():
    """Robot constructor must reject mismatched array lengths."""
    from kerf_motion.joints import RevoluteJoint
    from kerf_motion.inverse_dynamics import Robot

    joint = RevoluteJoint(0, 1, axis=(0, 0, 1))
    I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError):
        Robot(joints=[joint], link_masses=[1.0, 2.0], link_inertias=[I])
    with pytest.raises(ValueError):
        Robot(joints=[joint], link_masses=[1.0], link_inertias=[I, I])


def test_rne_rejects_multi_dof_joint():
    """RNE must raise ValueError for non-1-DOF joints."""
    from kerf_motion.joints import SphericalJoint
    from kerf_motion.inverse_dynamics import Robot, recursive_newton_euler

    joint = SphericalJoint(0, 1)
    I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    robot = Robot(joints=[joint], link_masses=[1.0], link_inertias=[I])
    with pytest.raises(ValueError):
        recursive_newton_euler(robot, [0.0], [0.0], [0.0])


def test_gravity_compensation_two_link():
    """
    2-link planar arm gravity compensation at two configurations.

    Configuration A: q1=0, q2=0 (both horizontal, along +X).
      τ1 = m1·g·(L1/2) + m2·g·(L1 + L2/2)  [cosine terms at q=0 = 1]
      τ2 = m2·g·(L2/2)

    Configuration B: q1=π/2, q2=0 (link1 vertical +Y, link2 still along link-1 X).
    With both links pointing up, gravity has no moment arm → both torques = 0.

    Reference: Craig §6.4; Featherstone §5.3.
    """
    from kerf_motion.joints import RevoluteJoint
    from kerf_motion.inverse_dynamics import Robot, gravity_compensation

    L1, L2 = 1.0, 0.8
    m1, m2 = 2.0, 1.5
    g = 9.81
    grav = (0.0, -g, 0.0)

    I_zz1 = m1 * L1 ** 2 / 12.0
    I_zz2 = m2 * L2 ** 2 / 12.0
    I1 = ((I_zz1, 0, 0), (0, I_zz1, 0), (0, 0, I_zz1))
    I2 = ((I_zz2, 0, 0), (0, I_zz2, 0), (0, 0, I_zz2))

    j0 = RevoluteJoint(0, 1, axis=(0, 0, 1), parent_offset=(0, 0, 0), name="j0")
    j1 = RevoluteJoint(1, 2, axis=(0, 0, 1), parent_offset=(L1, 0, 0), name="j1")

    robot = Robot(
        joints=[j0, j1],
        link_masses=[m1, m2],
        link_inertias=[I1, I2],
        com_offsets=[(L1 / 2, 0, 0), (L2 / 2, 0, 0)],
    )

    # --- Configuration A: q1=0, q2=0 (both horizontal) ---
    # At q1=0, q2=0: all cos terms = 1.
    # Proximal joint bears weight of both links:
    #   τ1 = m1·g·(L1/2)·cos(q1) + m2·g·(L1 + L2/2·cos(q2))·cos(q1)
    #      = m1·g·(L1/2) + m2·g·(L1 + L2/2)   [at q1=q2=0, all cos=1]
    # Distal joint bears only link-2 weight:
    #   τ2 = m2·g·(L2/2)·cos(q2) = m2·g·L2/2  [at q2=0]
    tau_A = gravity_compensation(robot, [0.0, 0.0], gravity=grav)
    tau1_A_analytic = m1 * g * (L1 / 2) + m2 * g * (L1 + L2 / 2)
    tau2_A_analytic = m2 * g * (L2 / 2)

    rel1 = abs(tau_A[0] - tau1_A_analytic) / tau1_A_analytic
    rel2 = abs(tau_A[1] - tau2_A_analytic) / tau2_A_analytic
    assert rel1 < 1e-6, (
        f"Config A τ0: RNE={tau_A[0]:.8f}, analytic={tau1_A_analytic:.8f}, "
        f"rel={rel1:.3e}"
    )
    assert rel2 < 1e-6, (
        f"Config A τ1: RNE={tau_A[1]:.8f}, analytic={tau2_A_analytic:.8f}, "
        f"rel={rel2:.3e}"
    )

    # --- Configuration B: q1=π/2, q2=0 ---
    # Link1 points up (+Y), link2 also points up (in link-1 local X → world Y after 90°).
    # Both links are vertical → no horizontal moment arm → both torques = 0.
    tau_B = gravity_compensation(robot, [math.pi / 2, 0.0], gravity=grav)
    assert abs(tau_B[0]) < 1e-10, (
        f"Config B τ0 at q1=π/2,q2=0: expected 0, got {tau_B[0]:.3e}"
    )
    assert abs(tau_B[1]) < 1e-10, (
        f"Config B τ1 at q1=π/2,q2=0: expected 0, got {tau_B[1]:.3e}"
    )
