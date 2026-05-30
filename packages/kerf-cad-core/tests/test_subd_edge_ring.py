"""test_subd_edge_ring.py
=======================
Tests for subd_edge_ring.py — SUBD-CAGE-RING-FROM-EDGE.

Coverage:
  1.  Cube: start edge → ring of exactly 4 edges, closed.
  2.  Cube: ring uses vertex-pair form for start_edge.
  3.  Cube: ring uses integer index form for start_edge.
  4.  Cube: all 12 edges → ring length 4 (each ring is length-4 closed).
  5.  Torus (4×4 quad grid): U-ring has length 4, closed.
  6.  Torus (4×4 quad grid): V-ring has length 4, closed.
  7.  Open rectangle cage: start on top edge → open ring (boundary hit).
  8.  Degenerate at triangular face: is_degenerate=True, ring truncated.
  9.  Start edge out of range (integer index) raises ValueError.
  10. Start edge vertex out of range raises ValueError.
  11. Single-quad cage: ring is open (boundary on both sides).
  12. transition_face_indices length equals ring edges - 1 for open rings.
  13. transition_face_indices length equals ring edges for closed rings.
  14. Closed-ring result: no duplicate edges.
  15. Result is EdgeRingResult dataclass with expected fields.
  16. 6×8 torus: different ring lengths in U vs V.
  17. Both-vertices-out-of-range raises ValueError.
  18. Negative integer index raises ValueError.
  19. Face indices all valid.
  20. Start edge always appears in ring.
  21. Edge indices are canonical (min, max) tuples.
  22. Single-quad ring length 2 (start + opposite within same face).
  23. Open rect interior edge ring.
  24. Degenerate ring is not closed.
  25. Mixed tri/quad: is_degenerate + not is_closed.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_edge_ring import EdgeRingResult, compute_edge_ring


# ---------------------------------------------------------------------------
# Cage fixtures
# ---------------------------------------------------------------------------

def _cube_cage() -> SubDMesh:
    """Unit cube cage: 8 vertices, 6 quad faces, 12 edges.

    Vertex indices:
      Bottom face: 0=(0,0,0) 1=(1,0,0) 2=(1,1,0) 3=(0,1,0)
      Top face:    4=(0,0,1) 5=(1,0,1) 6=(1,1,1) 7=(0,1,1)
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [0.0, 0.0, 1.0],  # 4
        [1.0, 0.0, 1.0],  # 5
        [1.0, 1.0, 1.0],  # 6
        [0.0, 1.0, 1.0],  # 7
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


def _torus_cage(nu: int = 4, nv: int = 4) -> SubDMesh:
    """nu × nv quad grid wrapped toroidally (periodic in both U and V).

    Vertex (i, j) has index i*nv + j.
    Face (i, j): [i*nv+j, i*nv+(j+1)%nv, ((i+1)%nu)*nv+(j+1)%nv, ((i+1)%nu)*nv+j]
    """
    import math
    R, r = 2.0, 0.5
    verts = []
    for i in range(nu):
        phi = 2 * math.pi * i / nu
        for j in range(nv):
            theta = 2 * math.pi * j / nv
            x = (R + r * math.cos(theta)) * math.cos(phi)
            y = (R + r * math.cos(theta)) * math.sin(phi)
            z = r * math.sin(theta)
            verts.append([x, y, z])
    faces = []
    for i in range(nu):
        for j in range(nv):
            v0 = i * nv + j
            v1 = i * nv + (j + 1) % nv
            v2 = ((i + 1) % nu) * nv + (j + 1) % nv
            v3 = ((i + 1) % nu) * nv + j
            faces.append([v0, v1, v2, v3])
    return SubDMesh(vertices=verts, faces=faces)


def _open_rectangle_cage() -> SubDMesh:
    """2×1 rectangle of quads: 6 vertices, 2 faces, open boundary all around.

    Vertex layout (row-major x first):
      0--1--2
      |  |  |
      3--4--5
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [2.0, 0.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [1.0, 1.0, 0.0],  # 4
        [2.0, 1.0, 0.0],  # 5
    ]
    faces = [
        [0, 1, 4, 3],  # left quad
        [1, 2, 5, 4],  # right quad
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _mixed_tri_quad_cage() -> SubDMesh:
    """3 faces: one quad + one triangle sharing an edge + one quad.

    Faces:
      F0 (quad):  [0, 1, 2, 3]
      F1 (tri):   [1, 4, 2]        — shares edge (1,2) with F0
      F2 (quad):  [1, 5, 6, 4]     — shares edge (1,4) with F1

    Edge (0,1) is on the boundary of F0 only.
    Edge (1,2) connects a quad (F0) and a triangle (F1).
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [2.0, 0.5, 0.0],  # 4
        [2.0, 0.0, 0.0],  # 5
        [2.0, 1.0, 0.0],  # 6
    ]
    faces = [
        [0, 1, 2, 3],  # quad F0
        [1, 4, 2],     # triangle F1 — degenerate transition
        [1, 5, 6, 4],  # quad F2
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _single_quad_cage() -> SubDMesh:
    """One quad face: 4 vertices, 4 edges, no interior."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCubeRing:
    def test_cube_ring_length_4_closed(self):
        """Ring on cube edge should be 4 edges, closed."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 1))
        assert result.is_closed, "Cube ring must be closed"
        assert not result.is_degenerate, "Cube is all-quad, no degenerate"
        assert len(result.edge_indices) == 4, f"Expected 4, got {len(result.edge_indices)}"

    def test_cube_ring_vertex_pair_form(self):
        """Using vertex pair (v0, v1) as start_edge."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 4))  # left vertical edge
        assert result.is_closed
        assert len(result.edge_indices) == 4

    def test_cube_ring_integer_index_form(self):
        """Using integer index as start_edge."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, 0)
        assert result.is_closed
        assert len(result.edge_indices) == 4

    def test_cube_all_edges_ring_length_4(self):
        """Every edge on the cube belongs to a ring of exactly 4."""
        cage = _cube_cage()
        all_edges = cage._all_edge_keys()
        for idx, ek in enumerate(all_edges):
            result = compute_edge_ring(cage, idx)
            assert result.is_closed, f"Edge {ek} ring not closed"
            assert len(result.edge_indices) == 4, (
                f"Edge {ek} ring length {len(result.edge_indices)}, expected 4"
            )

    def test_cube_ring_start_edge_in_result(self):
        """The start edge must appear in the ring."""
        cage = _cube_cage()
        start = cage.edge_key(0, 1)
        result = compute_edge_ring(cage, start)
        assert start in result.edge_indices, "Start edge missing from ring"

    def test_cube_ring_no_duplicate_edges(self):
        """Edge ring should not contain duplicate edges."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 1))
        assert len(result.edge_indices) == len(set(result.edge_indices)), (
            "Duplicate edges in ring"
        )


class TestTorusRing:
    def test_torus_u_ring_length_4_closed(self):
        """U-direction ring on 4×4 torus: each ring crosses 4 faces, closed."""
        cage = _torus_cage(nu=4, nv=4)
        # Edge (0, 4): crosses from row 0 to row 1 — ring traverses nv=4 V-strips.
        result = compute_edge_ring(cage, (0, 4))
        assert result.is_closed, "Torus U-ring must be closed"
        assert len(result.edge_indices) == 4, (
            f"Torus 4x4 U-ring: expected 4, got {len(result.edge_indices)}"
        )

    def test_torus_v_ring_length_4_closed(self):
        """V-direction ring on 4×4 torus: each ring crosses 4 faces, closed."""
        cage = _torus_cage(nu=4, nv=4)
        # Edge (0, 1): within row 0 — ring traverses nu=4 rows.
        result = compute_edge_ring(cage, (0, 1))
        assert result.is_closed
        assert len(result.edge_indices) == 4

    def test_torus_larger_grid(self):
        """6×8 torus: ring lengths correspond to opposite axis count.

        Vertex (i, j) has index i*nv + j, nv=8.
        Edge (0,1) is within row i=0 (V-direction): its ring crosses all nu=6
        rows → ring length 6.
        Edge (0,8) crosses from row 0 to row 1 (U-direction): its ring runs
        around nv=8 columns → ring length 8.
        """
        cage = _torus_cage(nu=6, nv=8)
        # Edge (0,1) within row 0: ring traverses nu=6 rows.
        v_result = compute_edge_ring(cage, (0, 1))
        assert v_result.is_closed
        assert len(v_result.edge_indices) == 6

        # Edge (0,8) crossing rows: ring traverses nv=8 columns.
        u_result = compute_edge_ring(cage, (0, 8))
        assert u_result.is_closed
        assert len(u_result.edge_indices) == 8


class TestOpenBoundaryRing:
    def test_boundary_ring_open(self):
        """Open rectangle: start on top boundary edge → open ring."""
        cage = _open_rectangle_cage()
        # Edge (0, 1) — top boundary, only one adjacent face.
        result = compute_edge_ring(cage, (0, 1))
        assert not result.is_closed, "Boundary start → open ring"
        assert not result.is_degenerate

    def test_boundary_ring_interior_horizontal_edge(self):
        """Interior horizontal edge (1, 4) is shared by both faces.

        Ring should cross both quads; hits boundary on both sides.
        """
        cage = _open_rectangle_cage()
        result = compute_edge_ring(cage, (1, 4))
        assert not result.is_closed
        assert len(result.edge_indices) >= 1

    def test_open_ring_boundary_edge_is_open(self):
        """Ring from boundary edge (3, 4): adjacent to 1 face only → open."""
        cage = _open_rectangle_cage()
        result = compute_edge_ring(cage, (3, 4))
        assert not result.is_closed


class TestDegenerateTransition:
    def test_tri_face_degenerate(self):
        """Ring traversal hitting a triangle face sets is_degenerate=True."""
        cage = _mixed_tri_quad_cage()
        # Edge (1, 2) is shared between quad F0 and triangle F1.
        result = compute_edge_ring(cage, (1, 2))
        assert result.is_degenerate, "Should be degenerate at tri face"

    def test_tri_cage_ring_truncated(self):
        """Degenerate ring is not closed and shorter than a full loop."""
        cage = _mixed_tri_quad_cage()
        result = compute_edge_ring(cage, (1, 2))
        assert not result.is_closed
        assert len(result.edge_indices) >= 1


class TestInvalidInputs:
    def test_out_of_range_integer_index(self):
        """Integer start_edge out of range raises ValueError."""
        cage = _cube_cage()
        ne = len(cage._all_edge_keys())
        with pytest.raises(ValueError, match="out of range"):
            compute_edge_ring(cage, ne + 100)

    def test_negative_integer_index(self):
        """Negative integer start_edge raises ValueError."""
        cage = _cube_cage()
        with pytest.raises(ValueError, match="out of range"):
            compute_edge_ring(cage, -1)

    def test_vertex_index_out_of_range(self):
        """Vertex index out of range raises ValueError."""
        cage = _cube_cage()
        with pytest.raises(ValueError, match="out of range"):
            compute_edge_ring(cage, (0, 999))

    def test_both_vertices_out_of_range(self):
        cage = _cube_cage()
        with pytest.raises(ValueError, match="out of range"):
            compute_edge_ring(cage, (100, 200))


class TestSingleQuad:
    def test_single_quad_all_edges_open(self):
        """Single quad: every edge is a boundary edge → open ring."""
        cage = _single_quad_cage()
        all_edges = cage._all_edge_keys()
        for idx in range(len(all_edges)):
            result = compute_edge_ring(cage, idx)
            assert not result.is_closed, f"Edge {idx} should be open"

    def test_single_quad_ring_length_2(self):
        """Single quad edge ring has 2 edges: start + opposite within same face.

        The ring traverses the single face to find the opposite edge, then hits
        boundary on both sides, resulting in an open ring of length 2.
        """
        cage = _single_quad_cage()
        result = compute_edge_ring(cage, 0)
        assert len(result.edge_indices) == 2
        assert not result.is_closed


class TestTransitionFaceIndices:
    def test_closed_ring_faces_equal_edges(self):
        """Closed ring: len(transition_face_indices) == len(edge_indices)."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 1))
        assert result.is_closed
        assert len(result.transition_face_indices) == len(result.edge_indices), (
            f"Closed ring faces {len(result.transition_face_indices)} != "
            f"edges {len(result.edge_indices)}"
        )

    def test_open_ring_faces_one_less(self):
        """Open ring: len(transition_face_indices) == len(edge_indices) - 1."""
        cage = _open_rectangle_cage()
        result = compute_edge_ring(cage, (0, 1))
        assert not result.is_closed
        assert len(result.transition_face_indices) == len(result.edge_indices) - 1, (
            f"Open ring faces {len(result.transition_face_indices)} != "
            f"edges {len(result.edge_indices)} - 1"
        )

    def test_face_indices_in_range(self):
        """All transition face indices are valid cage face indices."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 1))
        nf = len(cage.faces)
        for fi in result.transition_face_indices:
            assert 0 <= fi < nf, f"Face index {fi} out of range [0, {nf})"


class TestResultStructure:
    def test_result_is_dataclass(self):
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 1))
        assert isinstance(result, EdgeRingResult)
        assert hasattr(result, "edge_indices")
        assert hasattr(result, "is_closed")
        assert hasattr(result, "is_degenerate")
        assert hasattr(result, "transition_face_indices")

    def test_edge_indices_are_canonical(self):
        """All edge indices are canonical (min, max) tuples."""
        cage = _cube_cage()
        result = compute_edge_ring(cage, (0, 1))
        for v0, v1 in result.edge_indices:
            assert v0 <= v1, f"Edge ({v0},{v1}) not canonical"
