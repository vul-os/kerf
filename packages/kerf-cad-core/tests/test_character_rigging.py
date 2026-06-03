"""Tests for kerf_cad_core.sculpt.character_rigging — bone hierarchy, weight painting, LBS.

Coverage:
- Skeleton.by_name: found / KeyError
- Skeleton.topological_order: parents before children, root first
- Skeleton.topological_order: multi-level hierarchy
- WeightMap dataclass fields
- linear_blend_skinning: rest pose → identity (positions unchanged within 1e-9)
- linear_blend_skinning: pure translation bone moves vertices correctly
- auto_weight_from_proximity: nearest bone gets highest weight
- auto_weight_from_proximity: weights sum to 1 per vertex
- auto_weight_from_proximity: with triangles enables Laplacian smoothing
- auto_weight_from_proximity: bone_indices shape (V, 4), bone_weights shape (V, 4)
- make_bone: creates valid rest_matrix (4×4, rightmost column = head)
- Bone dataclass fields
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.sculpt.character_rigging import (
    Bone,
    Skeleton,
    WeightMap,
    auto_weight_from_proximity,
    linear_blend_skinning,
    make_bone,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _two_bone_skeleton():
    """Simple 2-bone skeleton: root at origin→(0,1,0) + child at (0,1,0)→(0,2,0)."""
    b_root  = make_bone("root",  head=[0, 0, 0], tail=[0, 1, 0], parent=None)
    b_child = make_bone("child", head=[0, 1, 0], tail=[0, 2, 0], parent="root")
    return Skeleton(bones=[b_root, b_child])


def _three_level_skeleton():
    """A → B → C chain."""
    ba = make_bone("A", head=[0, 0, 0], tail=[0, 1, 0], parent=None)
    bb = make_bone("B", head=[0, 1, 0], tail=[0, 2, 0], parent="A")
    bc = make_bone("C", head=[0, 2, 0], tail=[0, 3, 0], parent="B")
    return Skeleton(bones=[ba, bb, bc])


def _line_mesh(n: int = 10):
    """n vertices along the Y axis, 0..n-1 at y=0..n-1.

    Returns positions (n, 3) and triangles as a simple strip (n-2 tris).
    """
    positions = np.zeros((n, 3), dtype=np.float64)
    positions[:, 1] = np.arange(n, dtype=np.float64)

    # Degenerate strip (just for Laplacian connectivity)
    tris = [[i, i+1, i] for i in range(n-1)]  # degenerate, but OK for connectivity
    return positions, np.array(tris, dtype=np.int32)


# ---------------------------------------------------------------------------
# Tests: Bone + make_bone
# ---------------------------------------------------------------------------

class TestBone:
    def test_make_bone_fields(self):
        bone = make_bone("spine", head=[0, 0, 0], tail=[0, 1, 0])
        assert bone.name == "spine"
        assert bone.parent is None
        np.testing.assert_array_almost_equal(bone.head, [0, 0, 0])
        np.testing.assert_array_almost_equal(bone.tail, [0, 1, 0])

    def test_make_bone_rest_matrix_4x4(self):
        bone = make_bone("spine", head=[1, 2, 3], tail=[1, 3, 3])
        assert bone.rest_matrix.shape == (4, 4)

    def test_make_bone_rest_matrix_translation_column(self):
        """Last column of rest_matrix should encode the head position."""
        bone = make_bone("test", head=[1.0, 2.0, 3.0], tail=[1.0, 3.0, 3.0])
        np.testing.assert_array_almost_equal(bone.rest_matrix[:3, 3], [1.0, 2.0, 3.0])

    def test_make_bone_with_parent(self):
        bone = make_bone("child", head=[0, 1, 0], tail=[0, 2, 0], parent="root")
        assert bone.parent == "root"


# ---------------------------------------------------------------------------
# Tests: Skeleton
# ---------------------------------------------------------------------------

class TestSkeleton:
    def test_by_name_found(self):
        skel = _two_bone_skeleton()
        bone = skel.by_name("root")
        assert bone.name == "root"

    def test_by_name_not_found(self):
        skel = _two_bone_skeleton()
        with pytest.raises(KeyError):
            skel.by_name("nonexistent")

    def test_topological_order_root_first(self):
        skel = _two_bone_skeleton()
        order = skel.topological_order()
        assert order[0] == "root", f"Expected root first, got {order}"

    def test_topological_order_parent_before_child(self):
        skel = _two_bone_skeleton()
        order = skel.topological_order()
        assert order.index("root") < order.index("child"), (
            f"Expected root before child in {order}"
        )

    def test_topological_order_three_levels(self):
        skel = _three_level_skeleton()
        order = skel.topological_order()
        assert order.index("A") < order.index("B"), "A must precede B"
        assert order.index("B") < order.index("C"), "B must precede C"

    def test_topological_order_all_bones_present(self):
        skel = _three_level_skeleton()
        order = skel.topological_order()
        assert set(order) == {"A", "B", "C"}

    def test_topological_order_single_bone(self):
        skel = Skeleton(bones=[make_bone("solo", [0, 0, 0], [0, 1, 0])])
        assert skel.topological_order() == ["solo"]


# ---------------------------------------------------------------------------
# Tests: linear_blend_skinning
# ---------------------------------------------------------------------------

class TestLinearBlendSkinning:
    def test_rest_pose_returns_original_positions(self):
        """LBS with pose = rest matrices should return the original positions within 1e-9."""
        positions = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.5, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 1.5, 0.0],
            [0.0, 2.0, 0.0],
        ], dtype=np.float64)

        skel = _two_bone_skeleton()

        # Build simple weight map: lower verts to root, upper to child
        V = len(positions)
        bone_indices = np.array([
            [0, 1, -1, -1],  # y=0.0: root-only
            [0, 1, -1, -1],  # y=0.5
            [0, 1, -1, -1],  # y=1.0: split
            [1, 0, -1, -1],  # y=1.5
            [1, 0, -1, -1],  # y=2.0: child-only
        ], dtype=np.int32)
        bone_weights = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.7, 0.3, 0.0, 0.0],
            [0.5, 0.5, 0.0, 0.0],
            [0.3, 0.7, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ], dtype=np.float32)

        wm = WeightMap(vertex_count=V, bone_indices=bone_indices, bone_weights=bone_weights)

        # Pose matrices = rest matrices (identity transform)
        pose_matrices = [b.rest_matrix.copy() for b in skel.bones]

        deformed = linear_blend_skinning(positions, wm, skel, pose_matrices)

        np.testing.assert_allclose(deformed, positions, atol=1e-9,
                                   err_msg="Rest-pose LBS should return original positions")

    def test_translation_bone_moves_vertices(self):
        """A bone translated by +1 in Z should move fully-weighted vertices by +1 in Z."""
        positions = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        bone = make_bone("arm", head=[0, 0, 0], tail=[0, 1, 0])
        skel = Skeleton(bones=[bone])

        wm = WeightMap(
            vertex_count=1,
            bone_indices=np.array([[0, -1, -1, -1]], dtype=np.int32),
            bone_weights=np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        )

        # Pose matrix = rest matrix + translate Z by 1.0
        pose_mat = bone.rest_matrix.copy()
        pose_mat[2, 3] += 1.0   # translate Z

        deformed = linear_blend_skinning(positions, wm, skel, [pose_mat])
        assert abs(deformed[0, 2] - 1.0) < 1e-9, (
            f"Expected Z=1.0 after translation, got {deformed[0, 2]}"
        )


# ---------------------------------------------------------------------------
# Tests: auto_weight_from_proximity
# ---------------------------------------------------------------------------

class TestAutoWeightFromProximity:
    def test_weights_sum_to_one(self):
        positions, _ = _line_mesh(n=10)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel, max_bones_per_vert=2)
        row_sums = wm.bone_weights[wm.bone_indices[:, 0] >= 0].sum(axis=1)
        # Check all vertices have weights summing to ~1.0
        for v_idx in range(len(positions)):
            active = wm.bone_indices[v_idx, :] >= 0
            total  = float(wm.bone_weights[v_idx, active].sum())
            assert abs(total - 1.0) < 1e-5, (
                f"Vertex {v_idx} weights sum to {total:.6f}, expected 1.0"
            )

    def test_nearest_bone_gets_highest_weight(self):
        """Vertex at y=0 should have root as its highest-weight bone (closest)."""
        positions = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel, max_bones_per_vert=2)
        # Slot 0 should be the bone with the highest weight
        top_bone = int(wm.bone_indices[0, 0])
        top_w    = float(wm.bone_weights[0, 0])
        assert top_w >= 0.5, (
            f"Top bone weight {top_w:.4f} is not the highest for vertex near root"
        )
        # Root bone is index 0, child is index 1
        assert top_bone == 0, (
            f"Expected root (idx=0) as top bone for vertex at origin, got {top_bone}"
        )

    def test_bone_indices_shape(self):
        positions, _ = _line_mesh(n=6)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel)
        assert wm.bone_indices.shape == (6, 4)

    def test_bone_weights_shape(self):
        positions, _ = _line_mesh(n=6)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel)
        assert wm.bone_weights.shape == (6, 4)

    def test_unused_slots_are_minus_one(self):
        """With only 2 bones and max_bones=4, slots 2 and 3 should be -1."""
        positions, _ = _line_mesh(n=4)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel, max_bones_per_vert=4)
        assert np.all(wm.bone_indices[:, 2:] == -1), (
            "Slots 2-3 should be -1 with only 2 bones"
        )

    def test_weights_non_negative(self):
        positions, _ = _line_mesh(n=8)
        skel = _three_level_skeleton()
        wm = auto_weight_from_proximity(positions, skel)
        assert np.all(wm.bone_weights >= 0.0)

    def test_with_triangles_runs_smoothing(self):
        """Providing triangles enables Laplacian smoothing — should not error."""
        positions, triangles = _line_mesh(n=8)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel, triangles=triangles, smooth_iters=2)
        # Should still sum to 1
        for v_idx in range(len(positions)):
            active = wm.bone_indices[v_idx, :] >= 0
            total  = float(wm.bone_weights[v_idx, active].sum())
            assert abs(total - 1.0) < 1e-4, f"Vertex {v_idx} sum={total:.6f}"

    def test_vertex_count_stored(self):
        positions, _ = _line_mesh(n=5)
        skel = _two_bone_skeleton()
        wm = auto_weight_from_proximity(positions, skel)
        assert wm.vertex_count == 5
