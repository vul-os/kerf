"""test_subd_edge_collapse.py
============================
Tests for subd/edge_collapse.py — SUBD-CAGE-EDGE-COLLAPSE.

Coverage (14 tests across 7 classes):

  TestCubeCollapse (3 tests):
    1.  Cube cage (8 verts, 6 quads), collapse top edge → 7 verts.
    2.  Cube: degenerate faces containing both endpoints removed (2 faces).
    3.  Cube: result faces all contain valid vertex indices.

  TestCylinderCollapse (2 tests):
    4.  Cylinder cage: collapse one axial edge → vertex count decreases by 1.
    5.  Cylinder: num_faces_removed equals number of faces that contained
        both endpoint vertices.

  TestPlaneCollapse (3 tests):
    6.  Mid-edge of 2×2 plane grid: both vertex count and face count shrink.
    7.  Plane: mid-edge collapse → correct midpoint vertex position.
    8.  Plane: no face index exceeds new vertex count.

  TestEdgeNotFound (2 tests):
    9.  Edge index == num_edges raises ValueError.
    10. Negative edge index raises ValueError.

  TestResultStructure (2 tests):
    11. Return type is EdgeCollapseResult.
    12. EdgeCollapseResult has all required fields.

  TestCollapseConsistency (1 test):
    13. After collapse, num_verts_removed is always 1.

  TestHonestCaveat (1 test):
    14. honest_caveat is a non-empty string mentioning 'midpoint'.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.edge_collapse import (
    EdgeCollapseResult,
    collapse_edge,
    _build_ordered_edges,
)


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
    """2×2 plane grid: 6 vertices, 4 quad faces.

    Vertex layout (z=0 plane):
      0--1--2
      |  |  |
      3--4--5
    Faces:
      [0,1,4,3], [1,2,5,4]  (top row)
      No lower row — it's a 2×1 grid in u, not 2×2.

    Actually let's make a proper 2×2 grid (2 rows, 2 cols of quads):
    Vertices: 3 × 3 = 9
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


def _cylinder_cage(nu: int = 6, layers: int = 2) -> SubDMesh:
    """Simple open cylinder cage (nu segments circumferential, `layers` stacks).

    Side quads only (no caps), nu×layers quad faces.
    Vertices: nu × (layers+1).
    """
    verts = []
    for stack in range(layers + 1):
        z = float(stack)
        for i in range(nu):
            angle = 2.0 * math.pi * i / nu
            verts.append([math.cos(angle), math.sin(angle), z])

    faces = []
    for stack in range(layers):
        for i in range(nu):
            i_next = (i + 1) % nu
            a = stack * nu + i
            b = stack * nu + i_next
            c = (stack + 1) * nu + i_next
            d = (stack + 1) * nu + i
            faces.append([a, b, c, d])

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
# TestCubeCollapse
# ---------------------------------------------------------------------------

class TestCubeCollapse:
    """Collapse a top face edge of the unit cube."""

    def test_vertex_count_decreases_by_one(self):
        """After collapsing one edge, vertex count drops from 8 to 7."""
        cube = _unit_cube()
        # Top face edge: e.g., edge between vertices 4 and 5 (top-front)
        eidx = _edge_idx_for_vertices(cube, 4, 5)
        res = collapse_edge(cube, eidx)
        assert len(res.new_cage_vertices) == 7

    def test_degenerate_faces_removed(self):
        """Faces sharing both endpoints are removed (top face and front face both contain 4 and 5)."""
        cube = _unit_cube()
        # Edge (4, 5) is shared by top face [4,5,6,7] and front face [0,1,5,4]
        eidx = _edge_idx_for_vertices(cube, 4, 5)
        res = collapse_edge(cube, eidx)
        # Both top and front faces contain vertices 4 and 5 → both become degenerate
        assert res.num_faces_removed == 2

    def test_all_face_indices_valid(self):
        """All vertex indices in result faces reference valid new vertices."""
        cube = _unit_cube()
        eidx = _edge_idx_for_vertices(cube, 4, 5)
        res = collapse_edge(cube, eidx)
        nv = len(res.new_cage_vertices)
        for face in res.new_cage_faces:
            for vi in face:
                assert 0 <= vi < nv, f"Face index {vi} out of range [0, {nv})"


# ---------------------------------------------------------------------------
# TestCylinderCollapse
# ---------------------------------------------------------------------------

class TestCylinderCollapse:
    """Collapse an axial (vertical) edge of the cylinder cage."""

    def test_vertex_count_decreases_by_one(self):
        """Collapsing any edge reduces vertex count by exactly 1."""
        cyl = _cylinder_cage(nu=6, layers=2)
        # Axial edge: vertices 0 (bottom) and 6 (one stack up, same angle)
        eidx = _edge_idx_for_vertices(cyl, 0, 6)
        res = collapse_edge(cyl, eidx)
        assert len(res.new_cage_vertices) == len(cyl.vertices) - 1

    def test_faces_containing_both_endpoints_removed(self):
        """Faces that contained both collapsed endpoints are gone."""
        cyl = _cylinder_cage(nu=6, layers=2)
        # Edge (0, 6): which faces contain BOTH 0 and 6?
        v_a, v_b = 0, 6
        degenerate_expected = 0
        for face in cyl.faces:
            if v_a in face and v_b in face:
                degenerate_expected += 1
        eidx = _edge_idx_for_vertices(cyl, v_a, v_b)
        res = collapse_edge(cyl, eidx)
        assert res.num_faces_removed == degenerate_expected


# ---------------------------------------------------------------------------
# TestPlaneCollapse
# ---------------------------------------------------------------------------

class TestPlaneCollapse:
    """Collapse the interior shared edge between two quads in a 2×2 plane grid."""

    def test_vertex_and_face_count_both_shrink(self):
        """After collapsing an interior edge, both vertex and face count shrink."""
        plane = _simple_plane_grid()
        # Interior edge: (1, 4) — shared by faces [0,1,4,3] and [1,2,5,4]
        eidx = _edge_idx_for_vertices(plane, 1, 4)
        res = collapse_edge(plane, eidx)
        assert len(res.new_cage_vertices) < len(plane.vertices)
        assert len(res.new_cage_faces) < len(plane.faces)

    def test_midpoint_vertex_position_correct(self):
        """The midpoint vertex v_m must equal (v_a + v_b) / 2."""
        plane = _simple_plane_grid()
        v_a, v_b = 1, 4
        eidx = _edge_idx_for_vertices(plane, v_a, v_b)
        res = collapse_edge(plane, eidx)
        # Midpoint of vertex 1 = [1,0,0] and vertex 4 = [1,1,0] is [1,0.5,0].
        expected = (1.0, 0.5, 0.0)
        # The midpoint replaces v_a (index 1) in the new vertex list.
        # After removing v_b (index 4), the vertex at position 1 is the midpoint.
        # Find which index now has coordinates closest to expected.
        found = False
        for v in res.new_cage_vertices:
            if (abs(v[0] - expected[0]) < 1e-9
                    and abs(v[1] - expected[1]) < 1e-9
                    and abs(v[2] - expected[2]) < 1e-9):
                found = True
                break
        assert found, f"Midpoint {expected} not found in {res.new_cage_vertices}"

    def test_no_face_index_out_of_range(self):
        """No face index should exceed the new vertex count."""
        plane = _simple_plane_grid()
        eidx = _edge_idx_for_vertices(plane, 1, 4)
        res = collapse_edge(plane, eidx)
        nv = len(res.new_cage_vertices)
        for face in res.new_cage_faces:
            for vi in face:
                assert 0 <= vi < nv, (
                    f"Face index {vi} out of range [0, {nv}) in face {face}"
                )


# ---------------------------------------------------------------------------
# TestEdgeNotFound
# ---------------------------------------------------------------------------

class TestEdgeNotFound:
    """Out-of-range edge indices raise ValueError."""

    def test_edge_idx_equals_num_edges_raises(self):
        """edge_idx == num_edges is out of range."""
        cube = _unit_cube()
        all_edges, _ = _build_ordered_edges(cube.faces)
        ne = len(all_edges)
        with pytest.raises(ValueError, match="out of range"):
            collapse_edge(cube, ne)

    def test_negative_edge_idx_raises(self):
        """Negative edge index raises ValueError."""
        cube = _unit_cube()
        with pytest.raises(ValueError, match="out of range"):
            collapse_edge(cube, -1)


# ---------------------------------------------------------------------------
# TestResultStructure
# ---------------------------------------------------------------------------

class TestResultStructure:
    """EdgeCollapseResult has the correct type and fields."""

    def test_return_type_is_edge_collapse_result(self):
        """collapse_edge returns an EdgeCollapseResult instance."""
        cube = _unit_cube()
        eidx = _edge_idx_for_vertices(cube, 0, 1)
        res = collapse_edge(cube, eidx)
        assert isinstance(res, EdgeCollapseResult)

    def test_all_fields_present(self):
        """EdgeCollapseResult has all required fields."""
        cube = _unit_cube()
        eidx = _edge_idx_for_vertices(cube, 0, 1)
        res = collapse_edge(cube, eidx)
        assert hasattr(res, "new_cage_vertices")
        assert hasattr(res, "new_cage_faces")
        assert hasattr(res, "num_faces_removed")
        assert hasattr(res, "num_verts_removed")
        assert hasattr(res, "honest_caveat")


# ---------------------------------------------------------------------------
# TestCollapseConsistency
# ---------------------------------------------------------------------------

class TestCollapseConsistency:
    """After any single edge collapse, num_verts_removed == 1."""

    def test_num_verts_removed_always_one(self):
        """num_verts_removed is always 1 regardless of which edge is collapsed."""
        cube = _unit_cube()
        all_edges, _ = _build_ordered_edges(cube.faces)
        for i in range(len(all_edges)):
            res = collapse_edge(cube, i)
            assert res.num_verts_removed == 1, (
                f"Edge {i}: expected num_verts_removed=1, got {res.num_verts_removed}"
            )


# ---------------------------------------------------------------------------
# TestHonestCaveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    """honest_caveat is a non-empty string mentioning midpoint."""

    def test_honest_caveat_mentions_midpoint(self):
        """honest_caveat should mention 'midpoint' (no QEM)."""
        cube = _unit_cube()
        eidx = _edge_idx_for_vertices(cube, 4, 7)
        res = collapse_edge(cube, eidx)
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 0
        assert "midpoint" in res.honest_caveat.lower()
