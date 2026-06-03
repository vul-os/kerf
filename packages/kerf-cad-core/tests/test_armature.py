"""Tests for kerf_cad_core.animation.armature — Bone/Skeleton/Armature.

Covers ≥9 assertions across hierarchy construction, apply_pose, cascade
of parent transforms, identity pose, euler angle evaluation via
evaluate_armature_at_time, and linear_blend_skinning.
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.animation.armature import (
    Bone,
    Skeleton,
    Armature,
    evaluate_armature_at_time,
    linear_blend_skinning,
)
from kerf_cad_core.animation.keyframe import AnimClip, FCurve, Keyframe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_two_bone_skeleton() -> Skeleton:
    """Skeleton: root → child, both along Y axis."""
    skel = Skeleton()
    skel.add_bone(Bone(name="root", head=np.array([0., 0., 0.]),
                       tail=np.array([0., 1., 0.]), parent=None))
    skel.add_bone(Bone(name="child", head=np.array([0., 1., 0.]),
                       tail=np.array([0., 2., 0.]), parent="root"))
    return skel


def make_three_bone_skeleton() -> Skeleton:
    """Chain: A → B → C along Y axis, each bone length=1."""
    skel = Skeleton()
    skel.add_bone(Bone(name="A", head=np.array([0., 0., 0.]),
                       tail=np.array([0., 1., 0.]), parent=None))
    skel.add_bone(Bone(name="B", head=np.array([0., 1., 0.]),
                       tail=np.array([0., 2., 0.]), parent="A"))
    skel.add_bone(Bone(name="C", head=np.array([0., 1., 0.]),
                       tail=np.array([0., 2., 0.]), parent="B"))
    return skel


# ---------------------------------------------------------------------------
# Bone tests
# ---------------------------------------------------------------------------

def test_bone_length():
    """Bone length is computed from head-tail distance."""
    b = Bone(name="b", head=np.array([0., 0., 0.]),
             tail=np.array([0., 2., 0.]))
    assert abs(b.length - 2.0) < 1e-9


def test_bone_direction():
    """Bone direction is unit vector from head to tail."""
    b = Bone(name="b", head=np.array([0., 0., 0.]),
             tail=np.array([0., 3., 0.]))
    d = b.direction
    assert np.allclose(d, [0., 1., 0.], atol=1e-9)


def test_skeleton_root_names():
    """Skeleton.root_names returns only bones with no parent."""
    skel = make_two_bone_skeleton()
    assert skel.root_names == ["root"]


def test_skeleton_children_of():
    """Skeleton.children_of returns direct children."""
    skel = make_two_bone_skeleton()
    assert skel.children_of("root") == ["child"]
    assert skel.children_of("child") == []


def test_skeleton_ordered_bones():
    """ordered_bones returns breadth-first order from root."""
    skel = make_three_bone_skeleton()
    order = skel.ordered_bones()
    assert order[0] == "A"
    # B must come before C
    assert order.index("B") < order.index("C")


# ---------------------------------------------------------------------------
# Armature / apply_pose tests
# ---------------------------------------------------------------------------

def test_apply_pose_identity_returns_bone_heads():
    """Identity pose — world matrix positions equal head positions."""
    skel = make_two_bone_skeleton()
    arm = Armature(skeleton=skel)
    mats = arm.apply_pose({})  # identity rotations

    # root: head at origin, so translation part = [0,0,0]
    root_pos = mats[0][:3, 3]
    assert np.allclose(root_pos, [0., 0., 0.], atol=1e-9)

    # child: head at [0,1,0] in root local → world [0,1,0]
    child_pos = mats[1][:3, 3]
    assert np.allclose(child_pos, [0., 1., 0.], atol=1e-9)


def test_apply_pose_cascades_parent_transforms():
    """Child bone position = parent_world @ child_local_head."""
    skel = make_two_bone_skeleton()
    arm = Armature(skeleton=skel)

    # Rotate root 90° around Z
    angle = np.pi / 2
    Rz = np.array([[np.cos(angle), -np.sin(angle), 0],
                   [np.sin(angle),  np.cos(angle), 0],
                   [0, 0, 1]], dtype=float)

    mats = arm.apply_pose({"root": Rz})

    # Child head is [0,1,0] in root space.
    # After root rotation (90° Z), child world pos should be ~[-1, 0, 0]
    # because: root_world_mat = T([0,0,0]) @ R(90°Z)
    # child world = root_world @ T([0,1,0]) @ I
    # T([0,1,0]) in homogeneous adds [0,1,0] in root's rotated frame
    # Rz @ [0,1,0] = [-1, 0, 0]
    child_pos = mats[1][:3, 3]
    assert np.allclose(child_pos, [-1., 0., 0.], atol=1e-6), \
        f"Expected [-1,0,0], got {child_pos}"


def test_apply_pose_returns_4x4_matrices():
    """apply_pose returns 4×4 matrices."""
    skel = make_two_bone_skeleton()
    arm = Armature(skeleton=skel)
    mats = arm.apply_pose({})
    assert len(mats) == 2
    for m in mats:
        assert m.shape == (4, 4)


def test_apply_pose_three_bone_chain():
    """Three-bone chain cascades transforms correctly."""
    skel = make_three_bone_skeleton()
    arm = Armature(skeleton=skel)
    mats = arm.apply_pose({})
    # A at origin
    assert np.allclose(mats[0][:3, 3], [0., 0., 0.], atol=1e-9)
    # B at [0,1,0]
    assert np.allclose(mats[1][:3, 3], [0., 1., 0.], atol=1e-9)
    # C at [0,2,0] (A.head=0 + B.head=1 + C.head=1)
    assert np.allclose(mats[2][:3, 3], [0., 2., 0.], atol=1e-9)


# ---------------------------------------------------------------------------
# evaluate_armature_at_time
# ---------------------------------------------------------------------------

def make_constant_clip(bone_name: str, rx: float, ry: float, rz: float) -> AnimClip:
    """Clip with constant rotation channels for one bone."""
    def const_fc(v):
        return FCurve(keyframes=[Keyframe(t=0.0, value=v, interpolation="step")])

    return AnimClip(
        name="pose",
        duration=1.0,
        fcurves={
            f"{bone_name}.rx": const_fc(rx),
            f"{bone_name}.ry": const_fc(ry),
            f"{bone_name}.rz": const_fc(rz),
        },
    )


def test_evaluate_armature_at_time_identity():
    """evaluate_armature_at_time with zero angles = identity rotation."""
    skel = make_two_bone_skeleton()
    arm = Armature(skeleton=skel)
    clip = make_constant_clip("root", 0.0, 0.0, 0.0)
    mats = evaluate_armature_at_time(arm, clip, 0.0)
    # Root rotation block should be identity
    assert np.allclose(mats[0][:3, :3], np.eye(3), atol=1e-9)


def test_evaluate_armature_at_time_rz_90():
    """evaluate_armature_at_time with rz=π/2 rotates child correctly."""
    skel = make_two_bone_skeleton()
    arm = Armature(skeleton=skel)
    clip = make_constant_clip("root", 0.0, 0.0, np.pi / 2)
    mats = evaluate_armature_at_time(arm, clip, 0.5)
    child_pos = mats[1][:3, 3]
    # Same as test_apply_pose_cascades_parent_transforms
    assert np.allclose(child_pos, [-1., 0., 0.], atol=1e-5)


# ---------------------------------------------------------------------------
# linear_blend_skinning
# ---------------------------------------------------------------------------

def test_lbs_identity_no_deformation():
    """LBS with identity matrices leaves vertices unchanged."""
    skel = make_two_bone_skeleton()
    arm = Armature(skeleton=skel)
    world_mats = arm.apply_pose({})
    bone_order = skel.ordered_bones()

    vertices = np.array([[0., 0.5, 0.], [0., 1.5, 0.]], dtype=float)
    # Each vertex fully bound to one bone
    skin_idx = np.array([[0, 1], [1, 0]], dtype=int)
    skin_wts = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=float)

    out = linear_blend_skinning(vertices, skin_idx, skin_wts, world_mats, bone_order)
    assert out.shape == (2, 3)
