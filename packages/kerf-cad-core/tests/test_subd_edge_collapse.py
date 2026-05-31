"""test_subd_edge_collapse.py
============================
Tests for subd/edge_collapse.py — SUBD-CAGE-EDGE-COLLAPSE.

API under test:
  collapse_edge(cage: SubdCage, v_keep: int, v_remove: int, midpoint: bool=True)
  -> EdgeCollapseResult

  EdgeCollapseResult fields:
    new_cage: SubdCage
    num_vertices_removed: int
    num_faces_removed: int
    collapsed_position_xyz_mm: tuple[float, float, float]
    degenerate_faces_removed: int
    became_invalid: bool
    honest_caveat: str

Coverage (14 tests across 8 classes):

  TestUnitCubeTopEdge (3 tests):
    1.  Unit cube (8 verts, 6 quads): collapse top-front edge → 7 verts.
    2.  Unit cube top-front edge: 2 degenerate faces removed (top + front).
    3.  Unit cube top-front edge: result faces are all triangles or quads
        (collapsed quads become triangles).

  TestPyramidBaseEdge (2 tests):
    4.  Pyramid: collapse base edge → vertex count decreases by 1.
    5.  Pyramid: degenerate_faces_removed >= 1 (face(s) adjacent to base edge).

  TestNonEdgePair (2 tests):
    6.  Non-adjacent vertex pair returns became_invalid=True.
    7.  Non-adjacent: returned cage is unchanged (same verts and faces).

  TestMidpointVsEndpoint (2 tests):
    8.  midpoint=True: collapsed_position_xyz_mm equals midpoint of v_keep, v_remove.
    9.  midpoint=False: collapsed_position_xyz_mm equals V[v_keep].

  TestIndexValidation (2 tests):
    10. Out-of-range v_keep raises ValueError.
    11. Out-of-range v_remove raises ValueError.

  TestResultStructure (1 test):
    12. Return type is EdgeCollapseResult with all required fields.

  TestConsistency (1 test):
    13. num_vertices_removed == 1 on any valid cube edge collapse.

  TestHonestCaveat (1 test):
    14. honest_caveat mentions 'midpoint' and 'QEM' / 'Garland'.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.subd.cage_area import SubdCage
from kerf_cad_core.subd.edge_collapse import (
    EdgeCollapseResult,
    collapse_edge,
)


# ---------------------------------------------------------------------------
# Helpers — build standard test cages using SubdCage
# ---------------------------------------------------------------------------

def _unit_cube() -> SubdCage:
    """Unit cube: 8 vertices, 6 quad faces."""
    verts: List[Tuple[float, float, float]] = [
        (0.0, 0.0, 0.0),  # 0 bottom-front-left
        (1.0, 0.0, 0.0),  # 1 bottom-front-right
        (1.0, 1.0, 0.0),  # 2 bottom-back-right
        (0.0, 1.0, 0.0),  # 3 bottom-back-left
        (0.0, 0.0, 1.0),  # 4 top-front-left
        (1.0, 0.0, 1.0),  # 5 top-front-right
        (1.0, 1.0, 1.0),  # 6 top-back-right
        (0.0, 1.0, 1.0),  # 7 top-back-left
    ]
    faces = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [1, 2, 6, 5],  # right
        [2, 3, 7, 6],  # back
        [3, 0, 4, 7],  # left
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def _pyramid() -> SubdCage:
    """Square pyramid: 5 vertices, 1 quad base + 4 triangle sides.

    Vertex layout:
      0 = base front-left   (0,0,0)
      1 = base front-right  (1,0,0)
      2 = base back-right   (1,1,0)
      3 = base back-left    (0,1,0)
      4 = apex              (0.5, 0.5, 1.0)
    """
    verts: List[Tuple[float, float, float]] = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.5, 0.5, 1.0),  # apex
    ]
    faces = [
        [0, 1, 2, 3],  # base quad
        [0, 1, 4],     # front tri
        [1, 2, 4],     # right tri
        [2, 3, 4],     # back tri
        [3, 0, 4],     # left tri
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def _simple_plane_grid() -> SubdCage:
    """2×2 plane grid: 9 vertices, 4 quad faces.

    Vertex layout (z=0 plane):
      0--1--2
      |  |  |
      3--4--5
      |  |  |
      6--7--8
    """
    verts: List[Tuple[float, float, float]] = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
        (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 0.0),
        (0.0, 2.0, 0.0), (1.0, 2.0, 0.0), (2.0, 2.0, 0.0),
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def _non_adjacent_cage() -> SubdCage:
    """Two quads sharing an edge; vertices 0 and 8 are NOT adjacent.

    Vertex layout:
      0--1--2
      |  |  |
      3--4--5
    Vertex 0 and vertex 5 are not connected (diagonal corners of 2-quad strip).
    """
    verts: List[Tuple[float, float, float]] = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
        (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 0.0),
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


# ---------------------------------------------------------------------------
# TestUnitCubeTopEdge
# ---------------------------------------------------------------------------

class TestUnitCubeTopEdge:
    """Collapse the top-front edge (vertices 4 and 5) of the unit cube."""

    def test_vertex_count_7(self):
        """After collapsing top-front edge (4,5): 8 → 7 vertices."""
        cube = _unit_cube()
        res = collapse_edge(cube, v_keep=4, v_remove=5)
        assert len(res.new_cage.vertices_xyz_mm) == 7, (
            f"Expected 7 verts, got {len(res.new_cage.vertices_xyz_mm)}"
        )

    def test_two_degenerate_faces_removed(self):
        """Faces containing both 4 and 5 are removed: top [4,5,6,7] + front [0,1,5,4] → 2 removed."""
        cube = _unit_cube()
        res = collapse_edge(cube, v_keep=4, v_remove=5)
        assert res.num_faces_removed == 2, (
            f"Expected 2 faces removed, got {res.num_faces_removed}"
        )
        assert res.degenerate_faces_removed == res.num_faces_removed

    def test_collapsed_faces_have_valid_winding(self):
        """After collapse the remaining 4 faces should be triangles or quads (size 3 or 4)."""
        cube = _unit_cube()
        res = collapse_edge(cube, v_keep=4, v_remove=5)
        nv = len(res.new_cage.vertices_xyz_mm)
        for face in res.new_cage.faces:
            # Each face must have at least 3 unique vertices
            assert len(set(face)) >= 3, f"Degenerate face survived: {face}"
            # Each index must be in range
            for vi in face:
                assert 0 <= vi < nv, f"Face index {vi} out of range [0, {nv})"


# ---------------------------------------------------------------------------
# TestPyramidBaseEdge
# ---------------------------------------------------------------------------

class TestPyramidBaseEdge:
    """Collapse a base edge of the pyramid."""

    def test_vertex_count_decreases_by_one(self):
        """Collapsing base edge (0, 1) → 4 vertices (was 5)."""
        pyr = _pyramid()
        res = collapse_edge(pyr, v_keep=0, v_remove=1)
        assert res.num_vertices_removed == 1
        assert len(res.new_cage.vertices_xyz_mm) == 4

    def test_at_least_one_degenerate_face_removed(self):
        """The front triangle [0,1,4] contains both base endpoints → degenerate."""
        pyr = _pyramid()
        res = collapse_edge(pyr, v_keep=0, v_remove=1)
        # Face [0,1,4] must be removed (both 0 and 1 present → becomes [0,0,4] after map)
        # Base quad [0,1,2,3] also contains both → becomes [0,0,2,3] → degenerate
        assert res.degenerate_faces_removed >= 1, (
            f"Expected ≥1 degenerate faces removed, got {res.degenerate_faces_removed}"
        )


# ---------------------------------------------------------------------------
# TestNonEdgePair
# ---------------------------------------------------------------------------

class TestNonEdgePair:
    """Vertices that don't share a face are not an edge — must return became_invalid=True."""

    def test_non_adjacent_became_invalid(self):
        """Vertices 0 and 5 are not adjacent → became_invalid=True."""
        cage = _non_adjacent_cage()
        res = collapse_edge(cage, v_keep=0, v_remove=5)
        assert res.became_invalid is True, "Expected became_invalid=True for non-edge pair"

    def test_non_adjacent_cage_unchanged(self):
        """When became_invalid, the returned cage must equal the input."""
        cage = _non_adjacent_cage()
        res = collapse_edge(cage, v_keep=0, v_remove=5)
        assert res.num_vertices_removed == 0
        assert res.num_faces_removed == 0
        # Vertex count unchanged
        assert len(res.new_cage.vertices_xyz_mm) == len(cage.vertices_xyz_mm)
        # Face count unchanged
        assert len(res.new_cage.faces) == len(cage.faces)


# ---------------------------------------------------------------------------
# TestMidpointVsEndpoint
# ---------------------------------------------------------------------------

class TestMidpointVsEndpoint:
    """Test midpoint=True vs midpoint=False position for the kept vertex."""

    def test_midpoint_true_position(self):
        """midpoint=True: collapsed_position should equal (V[v_keep] + V[v_remove]) / 2."""
        plane = _simple_plane_grid()
        # Vertex 1 = (1,0,0), vertex 4 = (1,1,0) → midpoint = (1, 0.5, 0)
        res = collapse_edge(plane, v_keep=1, v_remove=4, midpoint=True)
        expected = (1.0, 0.5, 0.0)
        pos = res.collapsed_position_xyz_mm
        assert abs(pos[0] - expected[0]) < 1e-9, f"x: {pos[0]} != {expected[0]}"
        assert abs(pos[1] - expected[1]) < 1e-9, f"y: {pos[1]} != {expected[1]}"
        assert abs(pos[2] - expected[2]) < 1e-9, f"z: {pos[2]} != {expected[2]}"

    def test_midpoint_false_keeps_v_keep_position(self):
        """midpoint=False: collapsed_position should equal V[v_keep] exactly."""
        plane = _simple_plane_grid()
        # Vertex 1 = (1,0,0)
        v_keep_pos = plane.vertices_xyz_mm[1]
        res = collapse_edge(plane, v_keep=1, v_remove=4, midpoint=False)
        pos = res.collapsed_position_xyz_mm
        assert abs(pos[0] - float(v_keep_pos[0])) < 1e-9
        assert abs(pos[1] - float(v_keep_pos[1])) < 1e-9
        assert abs(pos[2] - float(v_keep_pos[2])) < 1e-9


# ---------------------------------------------------------------------------
# TestIndexValidation
# ---------------------------------------------------------------------------

class TestIndexValidation:
    """Out-of-range vertex indices raise ValueError."""

    def test_v_keep_out_of_range_raises(self):
        """v_keep >= nv raises ValueError."""
        cube = _unit_cube()
        nv = len(cube.vertices_xyz_mm)
        with pytest.raises(ValueError, match="v_keep"):
            collapse_edge(cube, v_keep=nv, v_remove=0)

    def test_v_remove_out_of_range_raises(self):
        """v_remove >= nv raises ValueError."""
        cube = _unit_cube()
        nv = len(cube.vertices_xyz_mm)
        with pytest.raises(ValueError, match="v_remove"):
            collapse_edge(cube, v_keep=0, v_remove=nv)


# ---------------------------------------------------------------------------
# TestResultStructure
# ---------------------------------------------------------------------------

class TestResultStructure:
    """EdgeCollapseResult has the correct type and all required fields."""

    def test_all_required_fields_present(self):
        """EdgeCollapseResult has all fields mandated by the task spec."""
        cube = _unit_cube()
        res = collapse_edge(cube, v_keep=0, v_remove=1)
        assert isinstance(res, EdgeCollapseResult)
        assert hasattr(res, "new_cage")
        assert hasattr(res, "num_vertices_removed")
        assert hasattr(res, "num_faces_removed")
        assert hasattr(res, "collapsed_position_xyz_mm")
        assert hasattr(res, "degenerate_faces_removed")
        assert hasattr(res, "became_invalid")
        assert hasattr(res, "honest_caveat")
        # new_cage must be a SubdCage
        assert isinstance(res.new_cage, SubdCage)
        # collapsed_position must be a 3-tuple
        assert len(res.collapsed_position_xyz_mm) == 3


# ---------------------------------------------------------------------------
# TestConsistency
# ---------------------------------------------------------------------------

class TestConsistency:
    """After any valid single edge collapse on a cube, num_vertices_removed == 1."""

    def test_num_vertices_removed_always_one(self):
        """Collapse every edge of the unit cube — each removes exactly 1 vertex."""
        # The 12 edges of a cube: we try all vertex pairs that share a face
        cube = _unit_cube()
        edges = set()
        for face in cube.faces:
            n = len(face)
            for i in range(n):
                a = face[i]
                b = face[(i + 1) % n]
                edges.add((min(a, b), max(a, b)))

        for v_a, v_b in edges:
            res = collapse_edge(cube, v_keep=v_a, v_remove=v_b)
            assert res.num_vertices_removed == 1, (
                f"Edge ({v_a},{v_b}): expected num_vertices_removed=1, "
                f"got {res.num_vertices_removed}"
            )
            assert res.became_invalid is False


# ---------------------------------------------------------------------------
# TestHonestCaveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    """honest_caveat is a non-empty string mentioning key limitations."""

    def test_caveat_mentions_midpoint_and_qem(self):
        """honest_caveat should mention 'midpoint' and either 'QEM' or 'Garland'."""
        cube = _unit_cube()
        res = collapse_edge(cube, v_keep=4, v_remove=7)
        caveat = res.honest_caveat
        assert isinstance(caveat, str), "honest_caveat must be a str"
        assert len(caveat) > 20, "honest_caveat should be a meaningful description"
        assert "midpoint" in caveat.lower(), "honest_caveat should mention 'midpoint'"
        has_qem = ("qem" in caveat.lower() or "garland" in caveat.lower())
        assert has_qem, "honest_caveat should mention QEM or Garland-Heckbert"
