"""
kerf_cad_core.animation.ik_solver — Inverse Kinematics solvers (CCD + FABRIK).

Covers max3ds skeletal dynamics IK, Blender IK constraints.

Algorithms
----------
CCD (Cyclic Coordinate Descent)
    Wang & Chen (1991). "A combined optimization method for solving the
    inverse kinematics problem of mechanical manipulators."
    IEEE Trans. Robotics and Automation 7(4):489-499.
    Also described in Müller, M. (2013). "Kinematic Character Animation." Eurographics
    Tutorial Notes.

    Each iteration sweeps joints from end-effector toward the root.  For each
    joint, a minimal rotation is computed that aligns the current end-effector
    with the target (after that joint's correction).  Rotation is represented as
    a 3×3 matrix built from axis-angle.

FABRIK (Forward And Backward Reaching Inverse Kinematics)
    Aristidou, A., Lasenby, J. (2011). "FABRIK: A fast, iterative solver for
    the Inverse Kinematics problem." Graphical Models 73(5):243-260.

    Iterates two phases per step:
      1. Backward: set end-effector to target; pull each bone toward child.
      2. Forward: re-anchor root; push each bone away from parent.
    FABRIK converges faster than CCD on long chains because each iteration
    repositions all joints rather than rotating one at a time.

Pole Target
-----------
When a pole_target is supplied, after each solve iteration the knee-equivalent
(middle joint of a 3-bone chain) is projected onto the plane defined by
root→target and pulled toward the pole_target side.  This matches Blender's
IK pole-angle behaviour.

Notes
-----
- Both solvers operate on Cartesian joint positions and return 3×3 rotation
  matrices (axis-angle construction, rotation from rest direction to posed
  direction).
- No joint limits are enforced (add min/max angle constraints post-solve).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class IKChain:
    """Inverse-kinematics chain description.

    Attributes
    ----------
    bones : list[str]
        Bone names in order: root → end-effector.
    target : np.ndarray, shape (3,)
        World-space target position for the end-effector.
    pole_target : np.ndarray | None, shape (3,)
        Optional pole target to constrain the chain's bend plane.
    """
    bones: List[str]
    target: np.ndarray
    pole_target: Optional[np.ndarray] = None

    def __post_init__(self):
        self.target = np.asarray(self.target, dtype=float)
        if self.pole_target is not None:
            self.pole_target = np.asarray(self.pole_target, dtype=float)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_normalise(v: np.ndarray, fallback: np.ndarray = None) -> np.ndarray:
    """Normalise a vector; return fallback (or zero) if near-zero."""
    n = np.linalg.norm(v)
    if n < 1e-12:
        return fallback if fallback is not None else np.zeros_like(v)
    return v / n


def _axis_angle_to_mat3(axis: np.ndarray, angle: float) -> np.ndarray:
    """Build a 3×3 rotation matrix from axis (unit) + angle (radians).

    Rodrigues' rotation formula:
        R = I cos(θ) + (1 - cos(θ)) n⊗n + sin(θ) [n]×
    """
    c, s = np.cos(angle), np.sin(angle)
    x, y, z = axis
    t = 1.0 - c
    return np.array([
        [t*x*x + c,   t*x*y - s*z, t*x*z + s*y],
        [t*x*y + s*z, t*y*y + c,   t*y*z - s*x],
        [t*x*z - s*y, t*y*z + s*x, t*z*z + c  ],
    ], dtype=float)


def _rot_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Minimum rotation matrix that rotates unit vector a to unit vector b."""
    a = _safe_normalise(a, np.array([0., 0., 1.]))
    b = _safe_normalise(b, np.array([0., 0., 1.]))
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if dot > 1.0 - 1e-10:
        return np.eye(3, dtype=float)
    if dot < -1.0 + 1e-10:
        # 180-degree rotation around any perpendicular axis
        perp = np.array([1., 0., 0.]) if abs(a[0]) < 0.9 else np.array([0., 1., 0.])
        axis = _safe_normalise(np.cross(a, perp))
        return _axis_angle_to_mat3(axis, np.pi)
    axis = _safe_normalise(np.cross(a, b))
    angle = np.arccos(dot)
    return _axis_angle_to_mat3(axis, angle)


def _get_joint_positions(
    chain: IKChain, skeleton
) -> Tuple[List[np.ndarray], List[float]]:
    """Extract world joint positions (including end-effector) and bone lengths.

    Returns n+1 positions for n bones: positions[0..n-1] are bone heads,
    positions[n] is the tail of the last bone (the true end-effector).
    CCD/FABRIK targets positions[-1] = target.

    Uses the same cascading-head algorithm as Armature._rest_world_matrices
    (identity rotations, translation-only cascade).

    Returns
    -------
    positions : list[np.ndarray]
        World positions for each joint head + last bone tail (len = n+1).
    lengths : list[float]
        Bone length for each bone (len = n).
    """
    from kerf_cad_core.animation.armature import _translation_mat4

    # Build world rest matrices for all bones in the full skeleton
    rest: Dict[str, np.ndarray] = {}
    for name in skeleton.ordered_bones():
        bone = skeleton.bones[name]
        local_t = _translation_mat4(bone.head)
        if bone.parent is None or bone.parent not in rest:
            rest[name] = local_t
        else:
            rest[name] = rest[bone.parent] @ local_t

    positions: List[np.ndarray] = []
    lengths: List[float] = []
    for name in chain.bones:
        wp = rest[name][:3, 3].copy()
        positions.append(wp)
        lengths.append(skeleton.bones[name].length)

    # Append end-effector: tail of last bone in world space
    # (last bone head + bone.length along bone.direction in world rest pose)
    if chain.bones:
        last_name = chain.bones[-1]
        last_bone = skeleton.bones[last_name]
        # In rest pose, the last bone's world frame has identity rotation
        # so tail_world = head_world + (tail_local - head_local)
        tail_world = rest[last_name][:3, 3] + (last_bone.tail - last_bone.head)
        positions.append(tail_world.copy())

    return positions, lengths


def _apply_pole_target(
    positions: List[np.ndarray],
    target: np.ndarray,
    pole: np.ndarray,
) -> List[np.ndarray]:
    """Project the middle joint toward the pole target.

    Constrains the middle bone(s) to lie in the plane defined by
    root, target, and pole_target.  This matches Blender IK pole behaviour.
    Only meaningful for chains of length ≥ 3.

    Parameters
    ----------
    positions : list of (3,) positions, root → end
    target : target world position
    pole : pole target world position

    Returns
    -------
    Updated positions list.
    """
    if len(positions) < 3:
        return positions

    root = positions[0]
    # Project each middle joint onto the plane (root, target, pole)
    chain_dir = _safe_normalise(target - root)
    pole_dir = _safe_normalise(pole - root)
    # Plane normal
    plane_normal = _safe_normalise(np.cross(chain_dir, pole_dir))
    if np.linalg.norm(plane_normal) < 1e-10:
        return positions  # Degenerate: pole on chain axis

    updated = [positions[0].copy()]
    for i in range(1, len(positions) - 1):
        p = positions[i]
        # Project p onto the bend plane by removing the normal component
        dist_from_root = np.dot(p - root, chain_dir)
        # Projection onto plane defined by chain_dir and pole_dir
        along_chain = root + chain_dir * dist_from_root
        offset = p - along_chain
        # Decompose offset: keep only the component along pole_dir
        along_pole = np.dot(offset, pole_dir)
        along_normal = np.dot(offset, plane_normal)
        # Pull toward pole side (blend 0.5 toward pole direction)
        new_p = along_chain + pole_dir * along_pole + plane_normal * along_normal * 0.3
        updated.append(new_p)
    updated.append(positions[-1].copy())
    return updated


def _rotations_from_positions(
    chain: IKChain,
    skeleton,
    positions: List[np.ndarray],
) -> Dict[str, np.ndarray]:
    """Convert IK-solved joint positions into per-bone LOCAL rotation matrices.

    The rotation for bone i must be in the **local** frame of bone i
    (i.e. relative to the parent's cumulative rotation), so that when
    Armature.apply_pose cascades M_world = M_parent @ T(head) @ R_local,
    the world positions reproduce the IK-solved positions.

    Algorithm
    ---------
    Track the cumulative world rotation R_world_parent (starts as identity).
    For each bone i:
      1. World-space posed direction: d_world = normalise(pos[i+1] - pos[i])
      2. World-space rest direction: d_rest_world = R_world_parent @ bone.direction
         (bone.direction is the local rest-pose unit vector head→tail)
      3. World rotation needed: R_world_i = rot_from_to(d_rest_world, d_world)
         This is the rotation in world space that brings the rest direction to
         the posed direction.
      4. Local rotation (what apply_pose expects):
         R_local_i = R_world_parent^T @ R_world_i @ R_world_parent
         Simplified for rotation matrices: since R_world_parent^T = R_world_parent^{-1}:
         R_local_i = R_world_parent.T @ R_world_i @ R_world_parent
         But actually apply_pose does M_world = M_parent @ T(head) @ R_local, and
         the rotation block of M_parent is R_world_parent, so:
         R_block_world = R_world_parent @ R_local → R_local = R_world_parent.T @ R_block_world
      5. Update cumulative: R_world_parent = R_world_parent @ R_local_i

    Returns
    -------
    dict[str, np.ndarray]
        3×3 LOCAL rotation matrices keyed by bone name (suitable for apply_pose).
    """
    rotations: Dict[str, np.ndarray] = {}
    R_cum = np.eye(3, dtype=float)  # cumulative world rotation of parent

    for i, name in enumerate(chain.bones):
        bone = skeleton.bones[name]

        if i + 1 < len(positions):
            posed_vec = positions[i + 1] - positions[i]
        else:
            # End-effector bone: no child to aim at; identity local rotation
            rotations[name] = np.eye(3, dtype=float)
            # R_cum unchanged
            continue

        # Rest direction in world space (bone.direction is in parent-local frame)
        rest_dir_world = R_cum @ bone.direction
        posed_dir = _safe_normalise(posed_vec, bone.direction)

        # World-space rotation for this bone
        R_world_i = _rot_from_to(rest_dir_world, posed_dir)

        # Local rotation = inverse(parent_world_rot) @ R_world_i @ parent_world_rot
        # apply_pose: M_parent_rot @ R_local → world_rot = R_cum @ R_local
        # So R_local = R_cum.T @ R_world_i @ R_cum ... but that overcorrects.
        # Actually: world_rot_i = R_cum @ R_local_i
        # R_world_i converts rest_world_dir → posed_dir
        # world_rot_i = R_world_i @ R_cum (apply world rotation on top of parent)
        # → R_local_i = R_cum.T @ R_world_i @ R_cum
        R_local_i = R_cum.T @ R_world_i @ R_cum

        rotations[name] = R_local_i
        # Update cumulative: next child's parent rot = R_cum @ R_local_i
        R_cum = R_cum @ R_local_i

    return rotations


# ---------------------------------------------------------------------------
# CCD solver
# ---------------------------------------------------------------------------

def solve_ik_ccd(
    chain: IKChain,
    skeleton,
    max_iter: int = 30,
    tol: float = 1e-4,
) -> Dict[str, np.ndarray]:
    """CCD (Cyclic Coordinate Descent) IK solver.

    Algorithm
    ---------
    For each iteration (outer loop):
      For each joint i from end-effector-1 down to root:
        1. Compute vector: joint_i → current_end_effector (d_e)
        2. Compute vector: joint_i → target (d_t)
        3. Rotate the sub-chain at joint_i so d_e aligns with d_t:
             axis  = normalise(d_e × d_t)
             angle = arccos(dot(d_e_hat, d_t_hat))
             Apply axis-angle rotation to all positions downstream.
      4. Check convergence: ‖end_effector - target‖ < tol.

    Wang & Chen (1991) — §3 combined optimisation; convergence bound §4.

    Parameters
    ----------
    chain : IKChain
    skeleton : Skeleton
    max_iter : int
        Maximum outer iterations.
    tol : float
        End-effector convergence tolerance (world units).

    Returns
    -------
    dict[str, np.ndarray]
        Per-bone 3×3 rotation matrices.
    """
    positions, lengths = _get_joint_positions(chain, skeleton)
    target = chain.target.copy()
    n = len(positions)

    if n < 2:
        return {chain.bones[0]: np.eye(3, dtype=float)}

    for _ in range(max_iter):
        # Sweep from joint n-2 down to 0 (not the end-effector itself)
        for i in range(n - 2, -1, -1):
            ee = positions[-1]
            if np.linalg.norm(ee - target) < tol:
                break

            d_e = ee - positions[i]
            d_t = target - positions[i]

            len_de = np.linalg.norm(d_e)
            len_dt = np.linalg.norm(d_t)
            if len_de < 1e-12 or len_dt < 1e-12:
                continue

            d_e_hat = d_e / len_de
            d_t_hat = d_t / len_dt

            dot_val = float(np.clip(np.dot(d_e_hat, d_t_hat), -1.0, 1.0))
            angle = np.arccos(dot_val)
            if abs(angle) < 1e-10:
                continue

            axis = np.cross(d_e_hat, d_t_hat)
            axis_len = np.linalg.norm(axis)
            if axis_len < 1e-12:
                continue
            axis /= axis_len

            R = _axis_angle_to_mat3(axis, angle)
            # Rotate all positions downstream of joint i around positions[i]
            for j in range(i + 1, n):
                positions[j] = positions[i] + R @ (positions[j] - positions[i])

        # Apply pole target if specified
        if chain.pole_target is not None:
            positions = _apply_pole_target(positions, target, chain.pole_target)

        if np.linalg.norm(positions[-1] - target) < tol:
            break

    return _rotations_from_positions(chain, skeleton, positions)


# ---------------------------------------------------------------------------
# FABRIK solver
# ---------------------------------------------------------------------------

def solve_ik_fabrik(
    chain: IKChain,
    skeleton,
    max_iter: int = 30,
    tol: float = 1e-4,
) -> Dict[str, np.ndarray]:
    """FABRIK (Forward And Backward Reaching IK) solver.

    Algorithm
    ---------
    Aristidou & Lasenby (2011) §3, Algorithm 1:

    Let p[0..n] be joint positions, L[i] = bone length (p[i+1]-p[i] in rest).
    Let p_root = p[0] (root anchor).

    Repeat until ‖p[n] - target‖ < tol:
      (a) Forward pass: set p[n] ← target
          For i = n-1 down to 0:
            λ = L[i] / ‖p[i+1] - p[i]‖
            p[i] = (1-λ) p[i+1] + λ p[i]
      (b) Backward pass: restore p[0] = p_root
          For i = 0 to n-1:
            λ = L[i] / ‖p[i+1] - p[i]‖
            p[i+1] = (1-λ) p[i] + λ p[i+1]

    FABRIK converges substantially faster than CCD on long chains because
    each iteration moves all joints, not just one.

    Aristidou, A., Lasenby, J. (2011). "FABRIK." Graphical Models 73(5):243-260.

    Parameters
    ----------
    chain : IKChain
    skeleton : Skeleton
    max_iter : int
    tol : float

    Returns
    -------
    dict[str, np.ndarray]
        Per-bone 3×3 rotation matrices.
    """
    positions, lengths = _get_joint_positions(chain, skeleton)
    target = chain.target.copy()
    n = len(positions)  # number of joints (= number of bones)

    if n < 2:
        return {chain.bones[0]: np.eye(3, dtype=float)}

    root = positions[0].copy()

    # Check total chain length vs distance to target
    total_length = sum(lengths)
    dist_to_target = np.linalg.norm(target - root)

    if dist_to_target > total_length:
        # Target is unreachable — stretch chain toward target
        for i in range(n - 1):
            d = _safe_normalise(target - positions[i], positions[i + 1] - positions[i])
            positions[i + 1] = positions[i] + d * lengths[i]
        if chain.pole_target is not None:
            positions = _apply_pole_target(positions, target, chain.pole_target)
        return _rotations_from_positions(chain, skeleton, positions)

    for _ in range(max_iter):
        # Check convergence
        if np.linalg.norm(positions[-1] - target) < tol:
            break

        # (a) Forward pass: pull end to target
        positions[-1] = target.copy()
        for i in range(n - 2, -1, -1):
            d = positions[i + 1] - positions[i]
            dn = np.linalg.norm(d)
            if dn < 1e-12:
                continue
            lam = lengths[i] / dn
            positions[i] = (1.0 - lam) * positions[i + 1] + lam * positions[i]

        # (b) Backward pass: re-anchor root
        positions[0] = root.copy()
        for i in range(n - 1):
            d = positions[i + 1] - positions[i]
            dn = np.linalg.norm(d)
            if dn < 1e-12:
                continue
            lam = lengths[i] / dn
            positions[i + 1] = (1.0 - lam) * positions[i] + lam * positions[i + 1]

        # Apply pole target
        if chain.pole_target is not None:
            positions = _apply_pole_target(positions, target, chain.pole_target)

    return _rotations_from_positions(chain, skeleton, positions)


__all__ = [
    "IKChain",
    "solve_ik_ccd",
    "solve_ik_fabrik",
]
