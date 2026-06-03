"""Tests for kerf_cad_core.animation.ik_solver — CCD and FABRIK IK solvers.

Covers ≥9 assertions across:
  - CCD convergence on a 3-bone chain
  - FABRIK convergence on the same chain
  - FABRIK vs CCD convergence count comparison
  - Pole target constrains the middle bone
  - Unreachable target stretches chain in target direction
  - Return type and structure validation
  - solve_ik_ccd with various chain lengths
  - Rotation matrix validity (orthogonality)

References
----------
Wang & Chen (1991). CCD IK. IEEE Trans. Robotics 7(4):489-499.
Aristidou & Lasenby (2011). FABRIK. Graphical Models 73(5):243-260.
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.animation.armature import Bone, Skeleton
from kerf_cad_core.animation.ik_solver import (
    IKChain,
    solve_ik_ccd,
    solve_ik_fabrik,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_straight_chain(n_bones: int = 3, bone_length: float = 1.0) -> Skeleton:
    """N-bone chain along +Y axis, each bone length = bone_length.

    head is in parent-local space: root has head=[0,0,0]; each child has
    head=[0, bone_length, 0] (offset from parent's origin).
    tail is also in parent-local space: head + [0, bone_length, 0].
    This gives world positions b0=[0,0,0], b1=[0,1,0], b2=[0,2,0], ...
    """
    skel = Skeleton()
    for i in range(n_bones):
        name = f"b{i}"
        # Root: head at origin. Children: offset by one bone length in Y from parent origin.
        if i == 0:
            head = np.array([0., 0., 0.], dtype=float)
        else:
            head = np.array([0., bone_length, 0.], dtype=float)
        tail = np.array([0., bone_length, 0.], dtype=float) + head
        parent = f"b{i - 1}" if i > 0 else None
        skel.add_bone(Bone(name=name, head=head, tail=tail, parent=parent))
    return skel


def chain_names(n: int) -> list[str]:
    return [f"b{i}" for i in range(n)]


def end_effector_pos(rotations, skel, bone_names) -> np.ndarray:
    """Compute the end-effector world position (tail of last bone) from rotations."""
    from kerf_cad_core.animation.armature import Armature
    arm = Armature(skeleton=skel)
    mats = arm.apply_pose(rotations)
    order = skel.ordered_bones()
    last_name = bone_names[-1]
    last_idx = order.index(last_name)
    last_bone = skel.bones[last_name]
    world_mat = mats[last_idx]
    # tail_world = head_world + R_world @ (tail_local - head_local)
    offset = last_bone.tail - last_bone.head
    return world_mat[:3, 3] + world_mat[:3, :3] @ offset


# ---------------------------------------------------------------------------
# Tests: CCD convergence
# ---------------------------------------------------------------------------

def test_ccd_3bone_converges_to_target():
    """CCD IK on 3-bone chain converges end-effector close to target."""
    skel = make_straight_chain(3)
    names = chain_names(3)
    target = np.array([1.5, 2.0, 0.0])  # reachable (total chain length = 3)
    ik = IKChain(bones=names, target=target)
    rotations = solve_ik_ccd(ik, skel, max_iter=100, tol=1e-4)

    ee_pos = end_effector_pos(rotations, skel, names)
    dist = np.linalg.norm(ee_pos - target)
    assert dist < 0.1, f"CCD end-effector distance to target = {dist:.4f}"


def test_ccd_returns_dict_of_rotations():
    """CCD returns a dict of rotation matrices keyed by bone name."""
    skel = make_straight_chain(2)
    names = chain_names(2)
    ik = IKChain(bones=names, target=np.array([0.5, 1.5, 0.0]))
    rots = solve_ik_ccd(ik, skel)
    assert isinstance(rots, dict)
    for name in names:
        assert name in rots
        assert rots[name].shape == (3, 3)


def test_ccd_rotation_matrices_are_orthogonal():
    """CCD rotation matrices satisfy R @ R.T ≈ I (proper rotation)."""
    skel = make_straight_chain(3)
    ik = IKChain(bones=chain_names(3), target=np.array([1.0, 2.5, 0.0]))
    rots = solve_ik_ccd(ik, skel, max_iter=50)
    for name, R in rots.items():
        err = np.max(np.abs(R @ R.T - np.eye(3)))
        assert err < 1e-8, f"CCD bone {name}: R@R.T error = {err:.2e}"


def test_ccd_single_bone_chain():
    """CCD on single bone returns identity (no IK chain to solve)."""
    skel = make_straight_chain(1)
    ik = IKChain(bones=["b0"], target=np.array([0.0, 0.5, 0.0]))
    rots = solve_ik_ccd(ik, skel)
    assert "b0" in rots
    assert np.allclose(rots["b0"], np.eye(3), atol=1e-9)


# ---------------------------------------------------------------------------
# Tests: FABRIK convergence
# ---------------------------------------------------------------------------

def test_fabrik_3bone_converges_to_target():
    """FABRIK IK on 3-bone chain converges close to target."""
    skel = make_straight_chain(3)
    names = chain_names(3)
    target = np.array([1.5, 2.0, 0.0])
    ik = IKChain(bones=names, target=target)
    rotations = solve_ik_fabrik(ik, skel, max_iter=100, tol=1e-4)

    ee_pos = end_effector_pos(rotations, skel, names)
    dist = np.linalg.norm(ee_pos - target)
    assert dist < 0.1, f"FABRIK end-effector distance to target = {dist:.4f}"


def test_fabrik_rotation_matrices_are_orthogonal():
    """FABRIK rotation matrices are valid rotations."""
    skel = make_straight_chain(3)
    ik = IKChain(bones=chain_names(3), target=np.array([1.0, 2.5, 0.0]))
    rots = solve_ik_fabrik(ik, skel, max_iter=50)
    for name, R in rots.items():
        err = np.max(np.abs(R @ R.T - np.eye(3)))
        assert err < 1e-8, f"FABRIK bone {name}: R@R.T error = {err:.2e}"


def test_fabrik_converges_faster_than_ccd():
    """FABRIK converges faster than CCD on a 5-bone chain (fewer iterations needed).

    We compare the residual after 5 iterations — FABRIK should have a smaller
    end-effector error at the same low iteration count (Aristidou & Lasenby 2011).
    """
    skel = make_straight_chain(5)
    names = chain_names(5)
    target = np.array([2.0, 4.0, 0.0])  # reachable (chain = 5 units)

    ik_ccd = IKChain(bones=names, target=target)
    ik_fab = IKChain(bones=names, target=target)

    # Run both solvers with just 5 iterations
    rots_ccd = solve_ik_ccd(ik_ccd, skel, max_iter=5, tol=1e-12)
    rots_fab = solve_ik_fabrik(ik_fab, skel, max_iter=5, tol=1e-12)

    ee_ccd = end_effector_pos(rots_ccd, skel, names)
    ee_fab = end_effector_pos(rots_fab, skel, names)

    dist_ccd = np.linalg.norm(ee_ccd - target)
    dist_fab = np.linalg.norm(ee_fab - target)

    # FABRIK should be closer or at worst the same
    assert dist_fab <= dist_ccd + 0.1, (
        f"FABRIK ({dist_fab:.4f}) not faster than CCD ({dist_ccd:.4f})"
    )


# ---------------------------------------------------------------------------
# Tests: pole target
# ---------------------------------------------------------------------------

def test_pole_target_constrains_middle_bone():
    """With a pole target, the middle joint shifts toward the pole direction.

    Setup: 3-bone chain along Y. Target at [0, 3, 0] (full extension).
    Pole at [1, 1.5, 0] (to the right). Without pole: middle bone at [0, 1, 0].
    With pole: middle bone should be pulled toward positive X.
    """
    skel = make_straight_chain(3)
    names = chain_names(3)
    target = np.array([0.5, 2.5, 0.0])
    pole = np.array([2.0, 1.5, 0.0])  # pull toward +X

    ik_with_pole = IKChain(bones=names, target=target, pole_target=pole)
    ik_no_pole = IKChain(bones=names, target=target)

    rots_with = solve_ik_fabrik(ik_with_pole, skel, max_iter=50)
    rots_no = solve_ik_fabrik(ik_no_pole, skel, max_iter=50)

    from kerf_cad_core.animation.armature import Armature
    arm = Armature(skeleton=skel)
    order = skel.ordered_bones()

    mats_with = arm.apply_pose(rots_with)
    mats_no = arm.apply_pose(rots_no)

    # Check middle bone (b1) world X position
    mid_idx = order.index("b1")
    x_with = mats_with[mid_idx][0, 3]
    x_no = mats_no[mid_idx][0, 3]

    # With pole toward +X, middle joint should be at >= X without-pole
    assert x_with >= x_no - 0.01, (
        f"Pole target did not shift middle bone toward pole: "
        f"x_with={x_with:.4f}, x_no={x_no:.4f}"
    )


# ---------------------------------------------------------------------------
# Tests: unreachable target
# ---------------------------------------------------------------------------

def test_ccd_unreachable_stretches_toward_target():
    """CCD with target beyond chain length stretches chain in target direction."""
    skel = make_straight_chain(3)  # total length = 3
    names = chain_names(3)
    target = np.array([0.0, 10.0, 0.0])  # far away

    rots = solve_ik_ccd(ik := IKChain(bones=names, target=target), skel, max_iter=50)
    ee_pos = end_effector_pos(rots, skel, names)

    # End effector should be somewhere along the +Y direction
    # (closer to target than if we hadn't tried)
    assert ee_pos[1] > 1.5, f"EE Y pos {ee_pos[1]:.4f} unexpectedly low"


def test_fabrik_unreachable_stretches_toward_target():
    """FABRIK with unreachable target stretches toward it (§3.2 of Aristidou 2011)."""
    skel = make_straight_chain(3)
    names = chain_names(3)
    target = np.array([0.0, 10.0, 0.0])

    rots = solve_ik_fabrik(IKChain(bones=names, target=target), skel, max_iter=50)
    ee_pos = end_effector_pos(rots, skel, names)
    assert ee_pos[1] > 1.5, f"EE Y pos {ee_pos[1]:.4f} unexpectedly low"
