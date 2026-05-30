"""
kerf_motion.inverse_dynamics
=============================
Inverse dynamics for serial kinematic chains: given a trajectory
θ(t), θ̇(t), θ̈(t) → joint torques τ(t).

Algorithm
---------
Recursive Newton-Euler (RNE) — Featherstone 2008 "Rigid Body Dynamics
Algorithms" §5.3.  The two-pass structure is:

  Forward pass (base → tip)
    Propagate joint positions, velocities, and accelerations from the base
    outward using the joint kinematics.  Each link i receives:
      ω_i   — angular velocity in link frame
      ω̇_i  — angular acceleration in link frame
      a_i   — linear acceleration of the link origin in link frame
                (includes gravity if base-link has an upward acceleration
                 equal to −g, i.e. we treat gravity as an inertial force)

  Backward pass (tip → base)
    Accumulate forces and moments from the tip inward.  At each link i:
      F_i  — net force on link i (Newton: F = m·a_c)
      N_i  — net moment about link CoM (Euler: N = I·ω̇ − ω×(I·ω))
    Then solve for the reaction forces from the parent joint and extract
    the scalar joint torque (projection onto the joint axis).

Sign convention / coordinate frames
-------------------------------------
- Each revolute joint i has a unit axis ẑ_i expressed in *its own link frame*.
- The "link frame" origin is placed at the joint i itself (Denavit-Hartenberg
  convention is NOT used; instead each joint carries an explicit ``parent_offset``
  that is the vector from the parent link origin to joint i in the parent frame).
- CoM of link i is at ``com_offset`` from the joint origin, expressed in the
  link frame.  Defaults to (0, 0, 0) when not provided (joint at CoM).

Robot descriptor
----------------
The solver accepts a ``Robot`` dataclass (defined below) that wraps the
joints/bodies already in kerf_motion.  For a serial chain of n revolute
joints you construct::

    robot = Robot(
        joints=[j0, j1, ...],          # RevoluteJoint objects, root→tip
        link_masses=[m0, m1, ...],     # kg per link
        link_inertias=[I0, I1, ...],   # 3×3 body-frame inertia tensors
        com_offsets=[(cx0,cy0,cz0), ...],  # CoM in link frame; default (0,0,0)
    )

All pure Python (no numpy) — consistent with the rest of kerf_motion.

References
----------
Featherstone, R. (2008). Rigid Body Dynamics Algorithms. Springer.  §5.3
Murray, R.M., Li, Z., Sastry, S.S. (1994). A Mathematical Introduction
  to Robotic Manipulation. CRC Press.  §4.2
Craig, J.J. (2005). Introduction to Robotics. Pearson.  §6.4
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from kerf_motion.body import (
    Vec3, Mat3,
    vec3_add, vec3_sub, vec3_scale, vec3_cross, vec3_dot, vec3_norm,
    mat3_vec, mat3_T, mat3_mul,
    quat_to_rotmat, quat_from_axis_angle,
)
from kerf_motion.joints import Joint, RevoluteJoint, PrismaticJoint


# ---------------------------------------------------------------------------
# Robot descriptor
# ---------------------------------------------------------------------------

@dataclass
class Robot:
    """
    Minimal descriptor for a serial-chain robot used by the RNE solver.

    Parameters
    ----------
    joints        : list of Joint objects (RevoluteJoint or PrismaticJoint),
                    ordered from base to tip.
    link_masses   : mass (kg) of each link (same length as joints).
    link_inertias : 3×3 inertia tensor (body frame) for each link.
    com_offsets   : CoM position in the link frame, measured from the joint
                    origin.  Defaults to zero vector for each link.
    """
    joints: List[Joint]
    link_masses: List[float]
    link_inertias: List[Mat3]
    com_offsets: Optional[List[Vec3]] = None

    def __post_init__(self):
        n = len(self.joints)
        if len(self.link_masses) != n:
            raise ValueError(
                f"Robot: {len(self.link_masses)} masses vs {n} joints"
            )
        if len(self.link_inertias) != n:
            raise ValueError(
                f"Robot: {len(self.link_inertias)} inertias vs {n} joints"
            )
        if self.com_offsets is None:
            self.com_offsets = [(0.0, 0.0, 0.0)] * n
        elif len(self.com_offsets) != n:
            raise ValueError(
                f"Robot: {len(self.com_offsets)} com_offsets vs {n} joints"
            )

    @property
    def n_dof(self) -> int:
        return sum(j.n_dof for j in self.joints)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _zeros3() -> Vec3:
    return (0.0, 0.0, 0.0)


def _mat3_identity() -> Mat3:
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _rotation_from_joint(joint: Joint, q_i: float) -> Mat3:
    """
    Return the rotation matrix R_{i,i-1} that maps vectors in the parent
    frame into the child (link i) frame.

    For a RevoluteJoint rotating about axis ẑ by angle q_i, the child frame
    is the parent frame *after* rotating by q_i.  Hence R = Rot(axis, q_i)ᵀ
    (the inverse / transpose, because we want parent→child).
    """
    if isinstance(joint, RevoluteJoint):
        # Quaternion for rotation q_i about joint axis (in parent frame)
        q = quat_from_axis_angle(joint.axis, q_i)
        R_child_to_parent = quat_to_rotmat(q)   # child→world when parent is world
        # parent→child = R^T
        return mat3_T(R_child_to_parent)
    elif isinstance(joint, PrismaticJoint):
        # Prismatic joint — no rotation component
        return _mat3_identity()
    else:
        # Fixed joint or unknown — identity
        return _mat3_identity()


def _link_offset_in_parent(joint: Joint) -> Vec3:
    """
    Position of the joint origin in the parent link frame.
    This is ``parent_offset`` from the Joint base class.
    """
    return joint.parent_offset  # type: ignore[return-value]


def _joint_axis_in_child(joint: Joint) -> Vec3:
    """
    Unit axis of motion expressed in the joint's own (child) link frame.
    For a RevoluteJoint the axis is given in the parent frame; after
    applying the rotation R (parent→child), the axis in the child frame is
    R · axis_parent.  However, since the axis is the rotation axis *itself*,
    it is invariant under that rotation — i.e. R · axis_parent == axis_parent
    (eigenvector of a rotation about that axis).  We return it as-is.
    """
    if isinstance(joint, (RevoluteJoint, PrismaticJoint)):
        return joint.axis
    return (0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Core solver: recursive_newton_euler
# ---------------------------------------------------------------------------

def recursive_newton_euler(
    robot: Robot,
    q: Sequence[float],
    q_dot: Sequence[float],
    q_ddot: Sequence[float],
    gravity: Vec3 = (0.0, 0.0, -9.81),
) -> List[float]:
    """
    Recursive Newton-Euler inverse dynamics.

    Given joint positions, velocities, and accelerations, compute the
    joint torques (forces for prismatic joints) required to produce the
    specified motion.

    Parameters
    ----------
    robot  : Robot descriptor (joints, masses, inertias, CoM offsets).
    q      : Joint positions, length = n_dof.
    q_dot  : Joint velocities, length = n_dof.
    q_ddot : Joint accelerations, length = n_dof.
    gravity: Gravitational acceleration vector in the world/base frame.
             Default (0,0,−9.81) m/s².  Pass (0,0,0) to disable gravity.

    Returns
    -------
    tau : list of floats, length = n_dof.
          Joint torques (N·m for revolute; N for prismatic).

    Algorithm (Featherstone 2008 §5.3)
    ------------------------------------
    We process single-DOF joints only (RevoluteJoint, PrismaticJoint).
    Multi-DOF joints (SphericalJoint etc.) are not currently supported and
    will raise ValueError.

    The gravity trick: we initialise the base-link linear acceleration as
    a_0 = −g (pointing opposite to gravity).  This propagates the
    gravitational force through the backward pass automatically, giving the
    correct generalised forces without explicit gravity terms.

    Forward pass variables per link i (in link-i frame):
        omega[i]   : angular velocity  ω_i
        alpha[i]   : angular acceleration  ω̇_i
        a_lin[i]   : linear acceleration of link origin  ä_i

    Backward pass forces per link i:
        f[i]  : reaction force  from link i on its parent joint (link frame i)
        n[i]  : reaction moment from link i on its parent joint (link frame i)
    """
    joints = robot.joints
    n = len(joints)

    # Validate all joints are 1-DOF
    for i, j in enumerate(joints):
        if not isinstance(j, (RevoluteJoint, PrismaticJoint)):
            raise ValueError(
                f"recursive_newton_euler: joint {i} ({j.name!r}) is not a "
                "RevoluteJoint or PrismaticJoint.  Multi-DOF joints are not "
                "supported by the scalar RNE algorithm."
            )

    masses = robot.link_masses
    inertias = robot.link_inertias
    com_offsets = robot.com_offsets  # type: ignore[assignment]

    # -----------------------------------------------------------------------
    # Forward pass: base → tip
    # -----------------------------------------------------------------------
    # Arrays indexed 0..n-1 (link 0 is the first link after the base).
    # Link frame: origin at joint i, z-axis = joint axis (for revolute).

    # Rotation matrices: R[i] maps parent-frame vectors into link-i frame.
    R: List[Mat3] = []
    # Joint offset p[i]: position of joint i origin in parent (i-1) frame.
    p: List[Vec3] = []
    # Angular velocity of each link in its own frame
    omega: List[Vec3] = [_zeros3()] * n
    # Angular acceleration of each link in its own frame
    alpha: List[Vec3] = [_zeros3()] * n
    # Linear acceleration of joint-i origin in link-i frame
    a_lin: List[Vec3] = [_zeros3()] * n

    # Base: treat the world frame as the "−1" link.
    # The gravity trick initialises the base linear acceleration:
    #   a_base = −g  (in world frame = link-0 "parent" frame at the base)
    # This will be propagated and appear as −m_i g when we compute inertial forces.
    omega_prev: Vec3 = _zeros3()
    alpha_prev: Vec3 = _zeros3()
    # Base acceleration (in world frame) = −gravity vector
    a_prev: Vec3 = (-gravity[0], -gravity[1], -gravity[2])

    for i in range(n):
        joint = joints[i]
        qi = float(q[i])
        qd_i = float(q_dot[i])
        qdd_i = float(q_ddot[i])

        # Rotation: R_i maps parent→child (link i)
        Ri = _rotation_from_joint(joint, qi)
        R.append(Ri)

        # Joint origin in parent frame
        pi = _link_offset_in_parent(joint)  # parent frame
        p.append(pi)

        # Joint axis in child frame
        z_i = _joint_axis_in_child(joint)

        if isinstance(joint, RevoluteJoint):
            # ω_i = R_i * ω_{i-1} + q̇_i * ẑ_i
            omega_i: Vec3 = vec3_add(
                mat3_vec(Ri, omega_prev),
                vec3_scale(z_i, qd_i),
            )

            # ω̇_i = R_i * ω̇_{i-1} + q̈_i * ẑ_i + ω_i × (q̇_i * ẑ_i)
            #      = R_i * α_{i-1} + q̈_i * ẑ_i + ω_i × (q̇_i * ẑ_i)
            cross_term = vec3_cross(omega_i, vec3_scale(z_i, qd_i))
            alpha_i: Vec3 = vec3_add(
                vec3_add(mat3_vec(Ri, alpha_prev), vec3_scale(z_i, qdd_i)),
                cross_term,
            )

            # Linear acceleration of joint i origin (in link i frame):
            # a_i = R_i * (a_{i-1} + α_{i-1} × p_i + ω_{i-1} × (ω_{i-1} × p_i))
            # p_i is in parent frame; transform everything to child frame.
            # Use: a_i = R_i*(a_{i-1}) + R_i*(α_{i-1} × p_i) + R_i*(ω_{i-1} × (ω_{i-1} × p_i))
            # All cross products done in parent frame first, then rotate.
            cross1 = vec3_cross(alpha_prev, pi)          # α_{i-1} × p_i  (parent frame)
            cross2_inner = vec3_cross(omega_prev, pi)    # ω × p (parent frame)
            cross2 = vec3_cross(omega_prev, cross2_inner)  # ω × (ω × p)
            a_sum = vec3_add(vec3_add(a_prev, cross1), cross2)
            a_i: Vec3 = mat3_vec(Ri, a_sum)

        else:  # PrismaticJoint
            # ω_i = R_i * ω_{i-1}  (no angular velocity contribution)
            omega_i = mat3_vec(Ri, omega_prev)

            # ω̇_i = R_i * ω̇_{i-1}
            alpha_i = mat3_vec(Ri, alpha_prev)

            # For prismatic joint, the joint translation is along z_i.
            # a_i = R_i*(a_{i-1} + α_{i-1}×p_i + ω_{i-1}×(ω_{i-1}×p_i))
            #       + q̈_i * ẑ_i + 2 * ω_i × (q̇_i * ẑ_i)
            cross1 = vec3_cross(alpha_prev, pi)
            cross2_inner = vec3_cross(omega_prev, pi)
            cross2 = vec3_cross(omega_prev, cross2_inner)
            a_sum = vec3_add(vec3_add(a_prev, cross1), cross2)
            a_rot = mat3_vec(Ri, a_sum)
            # Coriolis + direct acceleration
            coriolis = vec3_scale(vec3_cross(omega_i, z_i), 2.0 * qd_i)
            a_i = vec3_add(
                vec3_add(a_rot, coriolis),
                vec3_scale(z_i, qdd_i),
            )

        omega[i] = omega_i
        alpha[i] = alpha_i
        a_lin[i] = a_i

        # Update "previous" for next iteration
        omega_prev = omega_i
        alpha_prev = alpha_i
        a_prev = a_i

    # -----------------------------------------------------------------------
    # Backward pass: tip → base
    # -----------------------------------------------------------------------
    # f[i] = force exerted by link i on joint i (in link-i frame)
    # n[i] = moment exerted by link i on joint i about joint-i origin (in link-i frame)

    f: List[Vec3] = [_zeros3()] * n
    n_moment: List[Vec3] = [_zeros3()] * n

    # Tip: no outward force/moment on the last link (no end-effector wrench)
    f_next: Vec3 = _zeros3()
    n_next: Vec3 = _zeros3()
    R_next: Optional[Mat3] = None   # R_{i+1}: link-(i+1) → link-i rotation

    for i in range(n - 1, -1, -1):
        mi = masses[i]
        Ii = inertias[i]
        ci = com_offsets[i]   # CoM in link-i frame
        omega_i = omega[i]
        alpha_i = alpha[i]
        a_link_i = a_lin[i]   # acceleration of joint-i origin in link-i frame

        # Acceleration of CoM:
        # a_c = a_{link_i} + α_i × c_i + ω_i × (ω_i × c_i)
        cross_alpha_c = vec3_cross(alpha_i, ci)
        cross_omega_c_inner = vec3_cross(omega_i, ci)
        cross_omega_c = vec3_cross(omega_i, cross_omega_c_inner)
        a_com: Vec3 = vec3_add(vec3_add(a_link_i, cross_alpha_c), cross_omega_c)

        # Newton: F_i = m_i * a_com
        F_i: Vec3 = vec3_scale(a_com, mi)

        # Euler: N_i = I_i * α_i + ω_i × (I_i * ω_i)
        Iw: Vec3 = mat3_vec(Ii, omega_i)
        gyro: Vec3 = vec3_cross(omega_i, Iw)
        Ialpha: Vec3 = mat3_vec(Ii, alpha_i)
        N_i: Vec3 = vec3_add(Ialpha, gyro)

        # Outward force from child link i+1 (rotated into frame i)
        if R_next is None:
            # Last link: no child
            f_out: Vec3 = _zeros3()
            n_out: Vec3 = _zeros3()
        else:
            # R_next maps link-(i+1) frame into link-i frame (= transpose of R[i+1])
            f_out = mat3_vec(R_next, f_next)
            n_out = mat3_vec(R_next, n_next)

        # Inward force: f_i = F_i + f_out
        # (joint reaction force balances inertial + child outward force)
        f_i: Vec3 = vec3_add(F_i, f_out)

        # p_{i+1} in current link-i frame: offset from joint-i to joint-(i+1)
        # This is the parent_offset of joint (i+1) expressed in link-i frame.
        if i < n - 1:
            # parent_offset of joint i+1 is in link-i frame
            p_next = joints[i + 1].parent_offset
        else:
            p_next = _zeros3()

        # Moment about joint-i origin:
        # n_i = N_i + n_out + (c_i × F_i) + (p_{i+1} × f_out) + (c_i × f_out) — wait,
        # correct formula per Craig/Featherstone:
        # n_i = N_i                        (Euler moment about CoM)
        #       + c_i × f_i               (lever from joint origin to CoM, times joint reaction)
        #       - c_i × F_i               (cancel the CoM contribution; net = c_i × (f_i - F_i))
        #       + p_{i+1} × f_out          (lever from joint origin to child joint, times child force)
        #       + n_out                    (child moment)
        #
        # Craig eq. (6.45): n_i = N_i + n_{i+1} + (-p_c) × (−F_i) + p_{i+1} × (−f_{i+1})
        # rewritten in consistent sign convention (all in frame i, inward forces positive):
        #
        # n_i = N_i + n_out + c_i × F_i + p_{i+1} × f_out

        ci_x_Fi = vec3_cross(ci, F_i)
        p_next_x_fout = vec3_cross(p_next, f_out)
        n_i: Vec3 = vec3_add(
            vec3_add(N_i, n_out),
            vec3_add(ci_x_Fi, p_next_x_fout),
        )

        f[i] = f_i
        n_moment[i] = n_i

        # Prepare for next (lower) iteration
        f_next = f_i
        n_next = n_i
        R_next = mat3_T(R[i])   # R[i] was parent→child, so transpose is child→parent

    # -----------------------------------------------------------------------
    # Extract joint torques / forces
    # -----------------------------------------------------------------------
    tau: List[float] = []
    for i, joint in enumerate(joints):
        z_i = _joint_axis_in_child(joint)
        if isinstance(joint, RevoluteJoint):
            # τ_i = n_i · ẑ_i
            tau_i = vec3_dot(n_moment[i], z_i)
        else:  # PrismaticJoint
            # f_i = f_i · ẑ_i
            tau_i = vec3_dot(f[i], z_i)
        tau.append(tau_i)

    return tau


# ---------------------------------------------------------------------------
# gravity_compensation
# ---------------------------------------------------------------------------

def gravity_compensation(
    robot: Robot,
    q: Sequence[float],
    gravity: Vec3 = (0.0, 0.0, -9.81),
) -> List[float]:
    """
    Compute joint torques that hold the robot stationary at configuration q
    against gravity (no motion).

    τ_grav = recursive_newton_euler(robot, q, 0, 0, gravity)

    Parameters
    ----------
    robot   : Robot descriptor.
    q       : Joint positions, length = n_dof.
    gravity : Gravitational acceleration vector (world frame).

    Returns
    -------
    tau : list of floats — joint torques required for static equilibrium.
    """
    zeros = [0.0] * len(q)
    return recursive_newton_euler(robot, q, zeros, zeros, gravity)


# ---------------------------------------------------------------------------
# compute_joint_torques_from_trajectory
# ---------------------------------------------------------------------------

def compute_joint_torques_from_trajectory(
    robot: Robot,
    trajectory: List[Tuple[float, Sequence[float], Sequence[float], Sequence[float]]],
    gravity: Vec3 = (0.0, 0.0, -9.81),
) -> List[List[float]]:
    """
    Vectorised inverse dynamics over a complete trajectory.

    Parameters
    ----------
    robot      : Robot descriptor.
    trajectory : list of (t, q, q_dot, q_ddot) tuples, one per time step.
                 t       — time (float, not used in RNE but kept for completeness)
                 q       — joint positions  (length n_dof)
                 q_dot   — joint velocities (length n_dof)
                 q_ddot  — joint accelerations (length n_dof)
    gravity    : Gravitational acceleration vector (world frame).

    Returns
    -------
    torques : list of length len(trajectory), each element is a list of
              n_dof floats — the joint torques at that time step.

    Example
    -------
    >>> import math
    >>> traj = [(i*0.01, [math.sin(i*0.01)], [math.cos(i*0.01)], [-math.sin(i*0.01)])
    ...         for i in range(100)]
    >>> torques = compute_joint_torques_from_trajectory(robot, traj)
    """
    result: List[List[float]] = []
    for step in trajectory:
        _t, q_s, qd_s, qdd_s = step
        tau = recursive_newton_euler(robot, q_s, qd_s, qdd_s, gravity)
        result.append(tau)
    return result
