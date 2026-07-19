"""test_subd_vertex_merge.py
===========================
Tests for subd/vertex_merge.py — SUBD-CAGE-VERTEX-MERGE.

Coverage (16 tests across 8 classes):

  TestEdgeEquivalence (3 tests):
    1.  Merge 2 adjacent vertices in plane cage → vertex count same as
        edge-collapse result.
    2.  Merge 2 adjacent vertices → degenerate face count same as
        edge-collapse result.
    3.  Merge 2 adjacent vertices → centroid at midpoint (as expected).

  TestQuadCornerCollapse (3 tests):
    4.  Merge all 4 corners of a single isolated quad → entire quad
        collapsed (1 face removed, 3 verts removed).
    5.  Merge 4 corners → 0 surviving faces.
    6.  Merge 4 corners → new vertex list has exactly 1 extra vertex (the
        centroid) compared to 4 removed, plus original non-merged.

  TestNonAdjacentMerge (3 tests):
    7.  Merge non-adjacent vertices (no shared edge) → no faces removed.
    8.  Merge non-adjacent vertices → vertex count drops by |S|-1.
    9.  Merge non-adjacent vertices → all face indices remain valid.

  TestNoOp (2 tests):
    10. Empty vertex list → no-op (vertex/face count unchanged).
    11. Single-vertex list → no-op (vertex/face count unchanged).

  TestDuplicates (2 tests):
    12. Duplicate indices in list → treated as deduplicated merge; same
        result as passing unique indices only.
    13. Duplicates do not produce extra vertex removals.

  TestCentroidPosition (1 test):
    14. Merge 3 vertices of a triangle face → centroid equals arithmetic
        mean of the 3 positions.

  TestErrorHandling (1 test):
    15. Out-of-range index in vertex_indices → ValueError.

  TestResultStructure (1 test):
    16. Return type is VertexMergeResult with all required fields and
        honest_caveat mentioning 'centroid'.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.vertex_merge import (
    VertexMergeResult,
    merge_vertices,
)
from kerf_cad_core.subd.edge_collapse import collapse_edge
from kerf_cad_core.subd.edge_flip import _build_ordered_edges


# ---------------------------------------------------------------------------
# Helpers to build test cages
# ---------------------------------------------------------------------------

def _unit_cube() -> SubDMesh:
    """Unit cube: 8 vertices, 6 quad faces."""
    verts = [
        [0.0, 0.0, 0.0],  # 0 bottom-front-left
        [1.0, 0.0, 0.0],  # 1 bottom-front-right
        [1.0, 1.0, 0.0],  # 2 bottom-back-right
        [0.0, 1.0, 0.0],  # 3 bottom-back-left
        [0.0, 0.0, 1.0],  # 4 top-front-left
        [1.0, 0.0, 1.0],  # 5 top-front-right
        [1.0, 1.0, 1.0],  # 6 top-back-right
        [0.0, 1.0, 1.0],  # 7 top-back-left
    ]
    faces = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [1, 2, 6, 5],  # right
        [2, 3, 7, 6],  # back
        [3, 0, 4, 7],  # left
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _simple_plane_grid() -> SubDMesh:
    """2×2 plane grid: 9 vertices, 4 quad faces.

    Vertex layout (z=0 plane):
      0--1--2
      |  |  |
      3--4--5
      |  |  |
      6--7--8
    Faces (4 quads):
      [0,1,4,3], [1,2,5,4], [3,4,7,6], [4,5,8,7]
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [2.0, 0.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [1.0, 1.0, 0.0],  # 4 centre
        [2.0, 1.0, 0.0],  # 5
        [0.0, 2.0, 0.0],  # 6
        [1.0, 2.0, 0.0],  # 7
        [2.0, 2.0, 0.0],  # 8
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _single_quad() -> SubDMesh:
    """Isolated quad face: 4 vertices, 1 face."""
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
    ]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def _two_non_adjacent_quads() -> SubDMesh:
    """Two disconnected quads (vertices 0-3 and 4-7), no shared edge.

      Quad A: [0,1,2,3]
      Quad B: [4,5,6,7]
    """
    verts = [
        [0.0, 0.0, 0.0],   # 0
        [1.0, 0.0, 0.0],   # 1
        [1.0, 1.0, 0.0],   # 2
        [0.0, 1.0, 0.0],   # 3
        [5.0, 0.0, 0.0],   # 4 (far away — no shared edge)
        [6.0, 0.0, 0.0],   # 5
        [6.0, 1.0, 0.0],   # 6
        [5.0, 1.0, 0.0],   # 7
    ]
    faces = [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _edge_idx_for_vertices(cage: SubDMesh, va: int, vb: int) -> int:
    """Return the edge index for the edge between va and vb."""
    all_edges, _ = _build_ordered_edges(cage.faces)
    key = (min(va, vb), max(va, vb))
    for i, e in enumerate(all_edges):
        if e == key:
            return i
    raise ValueError(f"Edge ({va}, {vb}) not found in cage")


# ---------------------------------------------------------------------------
# TestEdgeEquivalence
# ---------------------------------------------------------------------------

class TestEdgeEquivalence:
    """Merge 2 adjacent vertices should behave equivalently to edge collapse."""

    def test_vertex_count_same_as_edge_collapse(self):
        """merge_vertices([v_a, v_b]) → same vertex count as collapse_edge."""
        plane = _simple_plane_grid()
        # Edge (1, 4): adjacent pair sharing a face edge.
        v_a, v_b = 1, 4
        eidx = _edge_idx_for_vertices(plane, v_a, v_b)

        res_collapse = collapse_edge(plane, eidx)
        res_merge = merge_vertices(plane, [v_a, v_b])

        assert len(res_merge.new_cage_vertices) == len(res_collapse.new_cage_vertices)

    def test_faces_removed_same_as_edge_collapse(self):
        """merge_vertices([v_a, v_b]) removes the same number of faces as edge collapse."""
        plane = _simple_plane_grid()
        v_a, v_b = 1, 4
        eidx = _edge_idx_for_vertices(plane, v_a, v_b)

        res_collapse = collapse_edge(plane, eidx)
        res_merge = merge_vertices(plane, [v_a, v_b])

        assert res_merge.num_faces_removed == res_collapse.num_faces_removed

    def test_centroid_equals_midpoint_for_two_vertices(self):
        """For exactly 2 vertices, centroid = midpoint = (v_a + v_b) / 2."""
        plane = _simple_plane_grid()
        # v_1 = [1,0,0], v_4 = [1,1,0]; midpoint = [1, 0.5, 0]
        v_a, v_b = 1, 4
        expected = (1.0, 0.5, 0.0)

        res = merge_vertices(plane, [v_a, v_b])

        found = any(
            abs(v[0] - expected[0]) < 1e-9
            and abs(v[1] - expected[1]) < 1e-9
            and abs(v[2] - expected[2]) < 1e-9
            for v in res.new_cage_vertices
        )
        assert found, (
            f"Centroid {expected} not found in {res.new_cage_vertices}"
        )


# ---------------------------------------------------------------------------
# TestQuadCornerCollapse
# ---------------------------------------------------------------------------

class TestQuadCornerCollapse:
    """Merging all 4 corners of a single quad collapses the face entirely."""

    def test_single_quad_all_corners_removes_quad(self):
        """Merging all 4 vertices of a single quad → 1 face removed."""
        quad = _single_quad()
        res = merge_vertices(quad, [0, 1, 2, 3])
        assert res.num_faces_removed == 1

    def test_single_quad_all_corners_zero_faces_remain(self):
        """After merging all 4 quad corners, no faces survive."""
        quad = _single_quad()
        res = merge_vertices(quad, [0, 1, 2, 3])
        assert len(res.new_cage_faces) == 0

    def test_single_quad_all_corners_verts_removed_count(self):
        """Merging all 4 corners: 3 vertices removed (4 fused to 1 centroid)."""
        quad = _single_quad()
        res = merge_vertices(quad, [0, 1, 2, 3])
        assert res.num_verts_removed == 3
        # 4 original → 4 - 3 = 1 vertex remains (the centroid).
        assert len(res.new_cage_vertices) == 1


# ---------------------------------------------------------------------------
# TestNonAdjacentMerge
# ---------------------------------------------------------------------------

class TestNonAdjacentMerge:
    """Merging vertices that share no edge: faces are preserved, vertex count drops."""

    def test_non_adjacent_no_faces_removed(self):
        """Merging corner vertices from two separate quads removes no faces."""
        mesh = _two_non_adjacent_quads()
        # Vertex 0 is in quad A, vertex 4 is in quad B — no shared edge.
        res = merge_vertices(mesh, [0, 4])
        assert res.num_faces_removed == 0

    def test_non_adjacent_vertex_count_drops_by_n_minus_1(self):
        """Merging k non-adjacent vertices reduces vertex count by k-1."""
        mesh = _two_non_adjacent_quads()
        # Merge corner 0 (quad A) with corner 4 (quad B): k=2, drop by 1.
        res = merge_vertices(mesh, [0, 4])
        assert len(res.new_cage_vertices) == len(mesh.vertices) - 1

    def test_non_adjacent_all_face_indices_valid(self):
        """All result face indices reference valid new vertices."""
        mesh = _two_non_adjacent_quads()
        res = merge_vertices(mesh, [0, 4])
        nv = len(res.new_cage_vertices)
        for face in res.new_cage_faces:
            for vi in face:
                assert 0 <= vi < nv, (
                    f"Face index {vi} out of range [0, {nv}) in face {face}"
                )


# ---------------------------------------------------------------------------
# TestNoOp
# ---------------------------------------------------------------------------

class TestNoOp:
    """Empty or single-element vertex list is a no-op."""

    def test_empty_list_is_noop(self):
        """Empty vertex_indices → mesh returned unchanged (same V and F counts)."""
        cube = _unit_cube()
        res = merge_vertices(cube, [])
        assert len(res.new_cage_vertices) == len(cube.vertices)
        assert len(res.new_cage_faces) == len(cube.faces)
        assert res.num_verts_removed == 0
        assert res.num_faces_removed == 0

    def test_single_index_is_noop(self):
        """Single vertex_index → no-op (nothing to merge)."""
        cube = _unit_cube()
        res = merge_vertices(cube, [3])
        assert len(res.new_cage_vertices) == len(cube.vertices)
        assert len(res.new_cage_faces) == len(cube.faces)
        assert res.num_verts_removed == 0
        assert res.num_faces_removed == 0


# ---------------------------------------------------------------------------
# TestDuplicates
# ---------------------------------------------------------------------------

class TestDuplicates:
    """Duplicate indices in the input list are deduplicated gracefully."""

    def test_duplicates_same_result_as_unique(self):
        """[v_a, v_b, v_a] should produce the same result as [v_a, v_b]."""
        plane = _simple_plane_grid()
        res_unique = merge_vertices(plane, [1, 4])
        res_dupes = merge_vertices(plane, [1, 4, 1, 4, 4])

        assert len(res_dupes.new_cage_vertices) == len(res_unique.new_cage_vertices)
        assert len(res_dupes.new_cage_faces) == len(res_unique.new_cage_faces)
        assert res_dupes.num_faces_removed == res_unique.num_faces_removed
        assert res_dupes.num_verts_removed == res_unique.num_verts_removed

    def test_duplicates_do_not_over_remove_vertices(self):
        """Passing an index multiple times still counts as 1 unique vertex."""
        cube = _unit_cube()
        # Merging [0, 1, 0, 0, 1] → unique {0, 1}: 2 unique → removes 1 vertex.
        res = merge_vertices(cube, [0, 1, 0, 0, 1])
        assert res.num_verts_removed == 1
        assert len(res.new_cage_vertices) == len(cube.vertices) - 1


# ---------------------------------------------------------------------------
# TestCentroidPosition
# ---------------------------------------------------------------------------

class TestCentroidPosition:
    """Centroid is the arithmetic mean of the merged vertex positions."""

    def test_three_vertex_centroid(self):
        """Merge v_0, v_1, v_4 from plane grid → centroid = mean([0,0,0],[1,0,0],[1,1,0])."""
        plane = _simple_plane_grid()
        # v_0 = [0,0,0], v_1 = [1,0,0], v_4 = [1,1,0]
        # centroid = [(0+1+1)/3, (0+0+1)/3, 0] = [2/3, 1/3, 0]
        expected = (2.0 / 3.0, 1.0 / 3.0, 0.0)

        res = merge_vertices(plane, [0, 1, 4])

        found = any(
            abs(v[0] - expected[0]) < 1e-9
            and abs(v[1] - expected[1]) < 1e-9
            and abs(v[2] - expected[2]) < 1e-9
            for v in res.new_cage_vertices
        )
        assert found, (
            f"Expected centroid {expected} not found in {res.new_cage_vertices}"
        )


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Out-of-range vertex indices raise ValueError."""

    def test_out_of_range_index_raises_value_error(self):
        """Passing an index >= len(vertices) raises ValueError."""
        cube = _unit_cube()
        with pytest.raises(ValueError, match="out of range"):
            merge_vertices(cube, [0, 8])  # cube has 8 verts (indices 0–7)

    def test_negative_index_raises_value_error(self):
        """Negative vertex index raises ValueError."""
        cube = _unit_cube()
        with pytest.raises(ValueError, match="out of range"):
            merge_vertices(cube, [0, -1])


# ---------------------------------------------------------------------------
# TestResultStructure
# ---------------------------------------------------------------------------

class TestResultStructure:
    """VertexMergeResult has the correct type and fields."""

    def test_return_type_is_vertex_merge_result(self):
        """merge_vertices returns a VertexMergeResult instance."""
        cube = _unit_cube()
        res = merge_vertices(cube, [0, 1])
        assert isinstance(res, VertexMergeResult)

    def test_all_required_fields_present(self):
        """VertexMergeResult has all required fields."""
        cube = _unit_cube()
        res = merge_vertices(cube, [0, 1])
        assert hasattr(res, "new_cage_vertices")
        assert hasattr(res, "new_cage_faces")
        assert hasattr(res, "num_faces_removed")
        assert hasattr(res, "num_verts_removed")
        assert hasattr(res, "merged_index")
        assert hasattr(res, "honest_caveat")

    def test_honest_caveat_mentions_centroid(self):
        """honest_caveat must mention 'centroid' (not QEM-optimal)."""
        cube = _unit_cube()
        res = merge_vertices(cube, [4, 5])
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 0
        assert "centroid" in res.honest_caveat.lower()

    def test_merged_index_within_new_vertex_list(self):
        """merged_index must be a valid index into new_cage_vertices."""
        cube = _unit_cube()
        res = merge_vertices(cube, [4, 5, 6])
        nv = len(res.new_cage_vertices)
        assert 0 <= res.merged_index < nv
