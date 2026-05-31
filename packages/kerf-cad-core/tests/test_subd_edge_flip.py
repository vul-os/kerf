"""test_subd_edge_flip.py
=======================
Tests for subd/edge_flip.py — SUBD-CAGE-EDGE-FLIP.

Coverage (12 tests across 7 classes):

  TestBasicFlipABCD (3 tests):
    1.  Two adjacent triangles ABC + BCD (share edge BC): flip produces ABD + ACD
        (the new shared edge is AD).
    2.  Face count unchanged after flip (2 in → 2 out).
    3.  All four vertices A, B, C, D appear in the result faces (no vertex lost).

  TestFacesSetEquality (1 test):
    4.  Canonical vertex sets of result faces equal {A,C,D} and {B,C,D} ... no,
        equal {A,B,D} and {A,C,D} per the flip definition verified explicitly.

  TestLargerMesh (2 tests):
    5.  Flip one interior edge of a 4-triangle fan; only the 2 incident faces
        change; the other 2 faces are unchanged.
    6.  After flip, result face list length equals input face list length.

  TestErrorCases (4 tests):
    7.  Edge not found (out-of-range edge_idx) → ValueError.
    8.  Boundary edge (only 1 incident face) → ValueError mentioning 'boundary'.
    9.  Quad face incident to the shared edge → ValueError mentioning 'triangle'.
    10. Non-manifold edge (> 2 incident faces) → ValueError mentioning 'non-manifold'.

  TestResultDataclass (1 test):
    11. flip_edge returns EdgeFlipResult with all required fields.

  TestFlipIdempotent (1 test):
    12. Flipping the same edge twice (by looking up the new edge index) restores
        the original connectivity (flip is its own inverse).

  TestHonestCaveat (1 test - bonus, total 13):
    13. honest_caveat is a non-empty string mentioning 'Delaunay' or 'topological'.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.edge_flip import (
    EdgeFlipResult,
    flip_edge,
    _build_ordered_edges,
    _faces_sharing_edge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mesh_from_tris(
    verts: List[List[float]],
    faces: List[List[int]],
) -> SubDMesh:
    return SubDMesh(vertices=verts, faces=faces)


def _edge_idx(cage: SubDMesh, va: int, vb: int) -> int:
    """Return the edge index for (va, vb) in the ordered edge list."""
    all_edges, _ = _build_ordered_edges(cage.faces)
    key = (min(va, vb), max(va, vb))
    for i, e in enumerate(all_edges):
        if e == key:
            return i
    raise ValueError(f"Edge ({va}, {vb}) not found in cage")


def _two_adjacent_tris() -> Tuple[SubDMesh, int, int, int, int]:
    """Two adjacent triangles ABC and BCD sharing edge BC.

    Vertices:
      A=0  [0, 1, 0]
      B=1  [0, 0, 0]
      C=2  [1, 0, 0]
      D=3  [1, 1, 0]

    Faces:
      T1 = [0, 1, 2]  → ABC
      T2 = [1, 2, 3]  → BCD  (shares edge BC = (1,2))

    After flip (BC → AD):
      T1' contains A, B, D  → [0, 1, 3] or some winding of it
      T2' contains A, C, D  → [0, 2, 3] or some winding of it
    """
    verts = [
        [0.0, 1.0, 0.0],  # 0 = A
        [0.0, 0.0, 0.0],  # 1 = B
        [1.0, 0.0, 0.0],  # 2 = C
        [1.0, 1.0, 0.0],  # 3 = D
    ]
    faces = [
        [0, 1, 2],  # T1 = A, B, C
        [1, 2, 3],  # T2 = B, C, D
    ]
    mesh = _mesh_from_tris(verts, faces)
    return mesh, 0, 1, 2, 3  # mesh, A, B, C, D


# ---------------------------------------------------------------------------
# TestBasicFlipABCD
# ---------------------------------------------------------------------------

class TestBasicFlipABCD:
    """Canonical two-triangle ABC+BCD flip test."""

    def test_flip_produces_two_new_faces_abd_and_acd(self):
        """After flipping BC, the new faces should be {A,B,D} and {A,C,D}."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)

        # Get the vertex-sets of the two result faces.
        result_sets = [frozenset(f) for f in res.new_cage_faces]
        expected_1 = frozenset([A, B, D])
        expected_2 = frozenset([A, C, D])
        assert expected_1 in result_sets, (
            f"Expected face {{A,B,D}} = {{{A},{B},{D}}} not in result {result_sets}"
        )
        assert expected_2 in result_sets, (
            f"Expected face {{A,C,D}} = {{{A},{C},{D}}} not in result {result_sets}"
        )

    def test_face_count_unchanged(self):
        """Face count stays at 2 after the flip (2 in → 2 out)."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)
        assert len(res.new_cage_faces) == 2

    def test_all_four_vertices_present(self):
        """All four vertices A, B, C, D must appear in the result faces."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)
        all_verts = set()
        for face in res.new_cage_faces:
            all_verts.update(face)
        for v in [A, B, C, D]:
            assert v in all_verts, f"Vertex {v} missing from result faces"


# ---------------------------------------------------------------------------
# TestFacesSetEquality
# ---------------------------------------------------------------------------

class TestFacesSetEquality:
    """Verify the exact face vertex-sets produced by the flip."""

    def test_new_shared_edge_is_AD_not_BC(self):
        """After flipping BC, the new shared edge must be AD (not BC)."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)

        # The OLD shared edge (BC) should NOT appear in either new face.
        for face in res.new_cage_faces:
            face_set = set(face)
            assert not (B in face_set and C in face_set), (
                f"Old shared edge (B={B}, C={C}) still present in face {face}"
            )

        # The NEW shared edge (AD) must appear in BOTH new faces.
        faces_containing_A = [f for f in res.new_cage_faces if A in f]
        faces_containing_D = [f for f in res.new_cage_faces if D in f]
        assert len(faces_containing_A) == 2, "A should be in both new faces"
        assert len(faces_containing_D) == 2, "D should be in both new faces"


# ---------------------------------------------------------------------------
# TestLargerMesh
# ---------------------------------------------------------------------------

class TestLargerMesh:
    """Flip one interior edge of a larger triangulated mesh."""

    def _four_tri_fan(self) -> Tuple[SubDMesh, int]:
        """Four triangles sharing a central vertex (fan).

        Vertices:
          0 = centre [0,0,0]
          1 = [1,0,0]
          2 = [0,1,0]
          3 = [-1,0,0]
          4 = [0,-1,0]

        Faces (4 tris around centre):
          [0,1,2]  edge (1,2) interior → target flip
          [0,2,3]
          [0,3,4]
          [0,4,1]
        """
        verts = [
            [0.0, 0.0, 0.0],   # 0 centre
            [1.0, 0.0, 0.0],   # 1
            [0.0, 1.0, 0.0],   # 2
            [-1.0, 0.0, 0.0],  # 3
            [0.0, -1.0, 0.0],  # 4
        ]
        faces = [
            [0, 1, 2],
            [0, 2, 3],
            [0, 3, 4],
            [0, 4, 1],
        ]
        mesh = _mesh_from_tris(verts, faces)
        # Edge between tris [0,1,2] and [0,2,3] is (0,2).
        eidx = _edge_idx(mesh, 0, 2)
        return mesh, eidx

    def test_only_two_incident_faces_change(self):
        """After flipping edge (0,2), the two non-incident faces are unchanged."""
        mesh, eidx = self._four_tri_fan()
        original_faces = [list(f) for f in mesh.faces]
        res = flip_edge(mesh, eidx)

        # The incident faces are indices 0 ([0,1,2]) and 1 ([0,2,3]).
        # The non-incident faces are indices 2 and 3.
        for i in [2, 3]:
            assert list(res.new_cage_faces[i]) == original_faces[i], (
                f"Face {i} changed unexpectedly: "
                f"expected {original_faces[i]}, got {res.new_cage_faces[i]}"
            )

    def test_face_count_unchanged_larger_mesh(self):
        """Face count is the same before and after flip."""
        mesh, eidx = self._four_tri_fan()
        res = flip_edge(mesh, eidx)
        assert len(res.new_cage_faces) == len(mesh.faces)


# ---------------------------------------------------------------------------
# TestErrorCases
# ---------------------------------------------------------------------------

class TestErrorCases:
    """Error conditions raise ValueError with informative messages."""

    def test_out_of_range_edge_idx_raises(self):
        """edge_idx >= num_edges raises ValueError."""
        mesh, A, B, C, D = _two_adjacent_tris()
        all_edges, _ = _build_ordered_edges(mesh.faces)
        ne = len(all_edges)
        with pytest.raises(ValueError, match="out of range"):
            flip_edge(mesh, ne)

    def test_boundary_edge_raises(self):
        """Flipping a boundary edge (only 1 incident face) raises ValueError."""
        mesh, A, B, C, D = _two_adjacent_tris()
        # Edge (0,1) = AB is a boundary edge (only in T1 = ABC).
        eidx = _edge_idx(mesh, A, B)
        with pytest.raises(ValueError, match="boundary"):
            flip_edge(mesh, eidx)

    def test_quad_face_raises(self):
        """An edge incident to a quad face raises ValueError mentioning 'triangle'."""
        # Make one triangle and one quad sharing an edge.
        verts = [
            [0.0, 0.0, 0.0],  # 0
            [1.0, 0.0, 0.0],  # 1
            [1.0, 1.0, 0.0],  # 2
            [0.0, 1.0, 0.0],  # 3
            [2.0, 0.0, 0.0],  # 4
        ]
        # Edge (0,1) is shared by a quad [0,1,2,3] and a triangle [0,1,4].
        faces = [
            [0, 1, 2, 3],  # quad
            [0, 1, 4],     # triangle
        ]
        mesh = _mesh_from_tris(verts, faces)
        eidx = _edge_idx(mesh, 0, 1)
        with pytest.raises(ValueError, match="triangle"):
            flip_edge(mesh, eidx)

    def test_non_manifold_edge_raises(self):
        """An edge shared by 3 faces raises ValueError mentioning 'non-manifold'."""
        # Three triangles all sharing edge (0,1).
        verts = [
            [0.0, 0.0, 0.0],   # 0
            [1.0, 0.0, 0.0],   # 1
            [0.5, 1.0, 0.0],   # 2
            [0.5, -1.0, 0.0],  # 3
            [0.5, 0.0, 1.0],   # 4
        ]
        faces = [
            [0, 1, 2],
            [0, 1, 3],
            [0, 1, 4],
        ]
        mesh = _mesh_from_tris(verts, faces)
        eidx = _edge_idx(mesh, 0, 1)
        with pytest.raises(ValueError, match="non-manifold"):
            flip_edge(mesh, eidx)


# ---------------------------------------------------------------------------
# TestResultDataclass
# ---------------------------------------------------------------------------

class TestResultDataclass:
    """EdgeFlipResult has all required fields with correct types."""

    def test_result_has_all_required_fields(self):
        """flip_edge returns EdgeFlipResult with the four required fields."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)

        assert isinstance(res, EdgeFlipResult)
        assert hasattr(res, "new_cage_faces")
        assert hasattr(res, "num_edges_flipped")
        assert hasattr(res, "flipped_edge_indices")
        assert hasattr(res, "honest_caveat")

        assert res.num_edges_flipped == 1
        assert isinstance(res.flipped_edge_indices, list)
        assert len(res.flipped_edge_indices) == 1
        assert res.flipped_edge_indices[0] == eidx
        assert isinstance(res.new_cage_faces, list)
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 0


# ---------------------------------------------------------------------------
# TestFlipIdempotent
# ---------------------------------------------------------------------------

class TestFlipIdempotent:
    """Flipping an edge twice restores the original topology."""

    def test_double_flip_restores_original(self):
        """Two consecutive flips of the same logical edge restore original faces."""
        mesh, A, B, C, D = _two_adjacent_tris()
        original_face_sets = [frozenset(f) for f in mesh.faces]

        # First flip: flip BC.
        eidx_bc = _edge_idx(mesh, B, C)
        res1 = flip_edge(mesh, eidx_bc)

        # Build a temporary mesh from the flipped faces to flip back.
        flipped_mesh = SubDMesh(vertices=mesh.vertices, faces=res1.new_cage_faces)

        # The new shared edge is AD.  Find its index in the flipped mesh.
        eidx_ad = _edge_idx(flipped_mesh, A, D)
        res2 = flip_edge(flipped_mesh, eidx_ad)

        # The result should be back to the original topology.
        restored_face_sets = [frozenset(f) for f in res2.new_cage_faces]
        for fs in original_face_sets:
            assert fs in restored_face_sets, (
                f"Original face {fs} not restored after double flip"
            )


# ---------------------------------------------------------------------------
# TestHonestCaveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    """honest_caveat mentions the topological-only nature of the flip."""

    def test_honest_caveat_mentions_delaunay_or_topological(self):
        """honest_caveat should mention 'Delaunay' or 'topological'."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)
        caveat_lower = res.honest_caveat.lower()
        assert "delaunay" in caveat_lower or "topological" in caveat_lower, (
            f"honest_caveat does not mention 'Delaunay' or 'topological': "
            f"{res.honest_caveat!r}"
        )

    def test_honest_caveat_mentions_triangles(self):
        """honest_caveat should mention triangle restriction."""
        mesh, A, B, C, D = _two_adjacent_tris()
        eidx = _edge_idx(mesh, B, C)
        res = flip_edge(mesh, eidx)
        assert "triangle" in res.honest_caveat.lower(), (
            f"honest_caveat does not mention 'triangle': {res.honest_caveat!r}"
        )
