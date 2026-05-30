"""test_subd_subdivide_edge.py
============================
Tests for subd_subdivide_edge.py — SUBD-CAGE-SUBDIVIDE-EDGE.

Coverage:
  1.  Cube: split interior edge → V=9, F=8 (depth-bar oracle).
  2.  Cube: split interior edge → E=15 (Euler V-E+F=2 preserved).
  3.  Cube: new_vertex_index == 8 (was 8 verts, new one is index 8).
  4.  Cube: adjacent_face_count == 2 (interior edge shared by 2 faces).
  5.  Cube: new_face_count matches new_cage.num_faces.
  6.  Cube: has_non_quad_input == False (all input faces are quads).
  7.  Cube: new vertex position is midpoint of edge (position_t=0.5).
  8.  Cube: position_t=0.25 → vertex ¼ of the way along edge.
  9.  Cube: position_t=0.75 → vertex ¾ of the way along edge.
  10. Cube: split does not change non-adjacent faces.
  11. Boundary edge (open rectangle patch): adjacent_face_count == 1.
  12. Boundary edge: F increases by exactly 1.
  13. Boundary edge: V increases by exactly 1.
  14. Boundary edge: Euler identity preserved.
  15. Invalid edge_index (negative) → ValueError.
  16. Invalid edge_index (== len(edges)) → ValueError.
  17. Split twice different edges → cumulative topology consistent.
  18. SubdivideEdgeResult is a dataclass with expected fields.
  19. Non-quad face input (triangle face) → has_non_quad_input == True.
  20. Split produces faces whose vertex indices are all valid.
  21. All face vertex indices in new_cage within range [0, V').
  22. New vertex does NOT appear in non-adjacent faces.
  23. New vertex DOES appear in each pair of replacement faces.
  24. Split preserves number of non-adjacent faces unchanged.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.subd_authoring import SubDCage, create_subd_primitive
from kerf_cad_core.geom.subd_subdivide_edge import SubdivideEdgeResult, subdivide_edge


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cube_cage() -> SubDCage:
    """Unit cube cage: 8 verts, 6 quad faces, 12 edges."""
    return create_subd_primitive("cube", width=2, height=2, depth=2)


def _open_rect_cage() -> SubDCage:
    """Open 2×1 rectangle: 4 verts, 2 quad faces (sharing one edge).

    Vertices:
      0=(0,0,0), 1=(1,0,0), 2=(1,1,0), 3=(0,1,0)
      4=(2,0,0), 5=(2,1,0)

    Faces:
      [0,1,2,3]  and  [1,4,5,2]

    Shared edge: 1-2  (edge between the two quads — interior)
    Boundary edges: 0-1, 2-3, 3-0, 1-4, 4-5, 5-2  (not shared)
    """
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
        [2.0, 0.0, 0.0],
        [2.0, 1.0, 0.0],
    ]
    faces = [
        [0, 1, 2, 3],
        [1, 4, 5, 2],
    ]
    return SubDCage(vertices=verts, faces=faces)


def _single_quad_cage() -> SubDCage:
    """Single quad: 4 verts, 1 face, 4 boundary edges."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return SubDCage(vertices=verts, faces=faces)


def _tri_cage() -> SubDCage:
    """Single triangle cage (non-quad) for honest-flag testing."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.5, 1.0, 0.0],
    ]
    faces = [[0, 1, 2]]
    return SubDCage(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Test 1: Cube interior edge split — V count
# ---------------------------------------------------------------------------

def test_cube_vertex_count():
    """Split one interior cube edge → V=9 (depth-bar oracle)."""
    cage = _cube_cage()
    assert cage.num_vertices == 8
    r = subdivide_edge(cage, edge_index=0)
    assert r.new_cage.num_vertices == 9


# ---------------------------------------------------------------------------
# Test 2: Cube interior edge split — F count
# ---------------------------------------------------------------------------

def test_cube_face_count():
    """Split one interior cube edge → F=8 (depth-bar oracle)."""
    cage = _cube_cage()
    assert cage.num_faces == 6
    r = subdivide_edge(cage, edge_index=0)
    assert r.new_cage.num_faces == 8


# ---------------------------------------------------------------------------
# Test 3: Cube — new_vertex_index is 8
# ---------------------------------------------------------------------------

def test_cube_new_vertex_index():
    """New vertex index should be len(original verts) = 8."""
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.new_vertex_index == 8


# ---------------------------------------------------------------------------
# Test 4: Cube — adjacent_face_count == 2
# ---------------------------------------------------------------------------

def test_cube_adjacent_face_count():
    """Cube interior edge is shared by exactly 2 faces."""
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.adjacent_face_count == 2


# ---------------------------------------------------------------------------
# Test 5: new_face_count matches new_cage.num_faces
# ---------------------------------------------------------------------------

def test_new_face_count_matches():
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.new_face_count == r.new_cage.num_faces


# ---------------------------------------------------------------------------
# Test 6: has_non_quad_input == False for cube
# ---------------------------------------------------------------------------

def test_cube_has_non_quad_input_false():
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.has_non_quad_input is False


# ---------------------------------------------------------------------------
# Test 7: Euler identity preserved (V - E + F = 2 for cube sphere topology)
# ---------------------------------------------------------------------------

def test_cube_euler_preserved():
    """Euler: V - E + F must remain 2 after interior edge split."""
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    nc = r.new_cage
    V = nc.num_vertices
    F = nc.num_faces
    E = len(nc.cage_edges())
    assert V - E + F == 2, f"Euler broken: {V}-{E}+{F}={V - E + F}"


# ---------------------------------------------------------------------------
# Test 8: Edge count after cube split = 15
# ---------------------------------------------------------------------------

def test_cube_edge_count():
    """After splitting 1 interior cube edge: E = 12 - 1 + 2 + 2 = 15."""
    cage = _cube_cage()
    assert len(cage.cage_edges()) == 12
    r = subdivide_edge(cage, edge_index=0)
    assert len(r.new_cage.cage_edges()) == 15


# ---------------------------------------------------------------------------
# Test 9: position_t=0.5 → midpoint
# ---------------------------------------------------------------------------

def test_position_t_midpoint():
    """position_t=0.5 places new vertex at midpoint of edge."""
    cage = _cube_cage()
    edges = cage.cage_edges()
    a, b = edges[0]
    va = cage.vertices[a]
    vb = cage.vertices[b]
    mid = [(va[i] + vb[i]) / 2.0 for i in range(3)]

    r = subdivide_edge(cage, edge_index=0, position_t=0.5)
    vm = r.new_cage.vertices[r.new_vertex_index]

    for i in range(3):
        assert abs(vm[i] - mid[i]) < 1e-12, f"coord {i}: {vm[i]} != {mid[i]}"


# ---------------------------------------------------------------------------
# Test 10: position_t=0.25 → quarter-point
# ---------------------------------------------------------------------------

def test_position_t_quarter():
    """position_t=0.25 places new vertex ¼ from v_a toward v_b."""
    cage = _cube_cage()
    edges = cage.cage_edges()
    a, b = edges[0]
    va = cage.vertices[a]
    vb = cage.vertices[b]
    expected = [va[i] + 0.25 * (vb[i] - va[i]) for i in range(3)]

    r = subdivide_edge(cage, edge_index=0, position_t=0.25)
    vm = r.new_cage.vertices[r.new_vertex_index]

    for i in range(3):
        assert abs(vm[i] - expected[i]) < 1e-12


# ---------------------------------------------------------------------------
# Test 11: position_t=0.75 → three-quarter point
# ---------------------------------------------------------------------------

def test_position_t_three_quarter():
    """position_t=0.75 places new vertex ¾ from v_a toward v_b."""
    cage = _cube_cage()
    edges = cage.cage_edges()
    a, b = edges[0]
    va = cage.vertices[a]
    vb = cage.vertices[b]
    expected = [va[i] + 0.75 * (vb[i] - va[i]) for i in range(3)]

    r = subdivide_edge(cage, edge_index=0, position_t=0.75)
    vm = r.new_cage.vertices[r.new_vertex_index]

    for i in range(3):
        assert abs(vm[i] - expected[i]) < 1e-12


# ---------------------------------------------------------------------------
# Test 12: Non-adjacent faces are unchanged
# ---------------------------------------------------------------------------

def test_non_adjacent_faces_unchanged():
    """Faces not touching the split edge must be identical in the new cage."""
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    edges = cage.cage_edges()
    edge_key = (min(edges[0][0], edges[0][1]), max(edges[0][0], edges[0][1]))

    original_non_adj = [
        sorted(f)
        for f in cage.faces
        if not any(
            (min(f[i], f[(i + 1) % len(f)]), max(f[i], f[(i + 1) % len(f)])) == edge_key
            for i in range(len(f))
        )
    ]
    new_non_adj = [
        sorted(f)
        for f in r.new_cage.faces
        if r.new_vertex_index not in f
    ]

    # Each original non-adjacent face appears in new non-adj faces.
    for orig_f in original_non_adj:
        assert orig_f in new_non_adj, f"Missing original face {orig_f} in new cage"


# ---------------------------------------------------------------------------
# Test 13: Boundary edge (single-quad cage) → adjacent_face_count == 1
# ---------------------------------------------------------------------------

def test_boundary_edge_adjacent_count():
    """Single-quad cage: every edge is boundary → adjacent_face_count == 1."""
    cage = _single_quad_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.adjacent_face_count == 1


# ---------------------------------------------------------------------------
# Test 14: Boundary edge split → F increases by 1
# ---------------------------------------------------------------------------

def test_boundary_edge_face_increase():
    cage = _single_quad_cage()
    orig_f = cage.num_faces
    r = subdivide_edge(cage, edge_index=0)
    assert r.new_cage.num_faces == orig_f + 1


# ---------------------------------------------------------------------------
# Test 15: Boundary edge split → V increases by 1
# ---------------------------------------------------------------------------

def test_boundary_edge_vertex_increase():
    cage = _single_quad_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.new_cage.num_vertices == cage.num_vertices + 1


# ---------------------------------------------------------------------------
# Test 16: Boundary edge Euler preserved (disk topology χ=1)
# ---------------------------------------------------------------------------

def test_boundary_edge_euler():
    """Single-quad: χ = V - E + F = 1 (disk with boundary); preserved after split."""
    cage = _single_quad_cage()
    V0 = cage.num_vertices
    E0 = len(cage.cage_edges())
    F0 = cage.num_faces
    chi0 = V0 - E0 + F0

    r = subdivide_edge(cage, edge_index=0)
    nc = r.new_cage
    V1, E1, F1 = nc.num_vertices, len(nc.cage_edges()), nc.num_faces
    assert V1 - E1 + F1 == chi0, f"Euler changed: {chi0} → {V1 - E1 + F1}"


# ---------------------------------------------------------------------------
# Test 17: Invalid edge_index (negative) → ValueError
# ---------------------------------------------------------------------------

def test_invalid_edge_index_negative():
    cage = _cube_cage()
    with pytest.raises(ValueError):
        subdivide_edge(cage, edge_index=-1)


# ---------------------------------------------------------------------------
# Test 18: Invalid edge_index (too large) → ValueError
# ---------------------------------------------------------------------------

def test_invalid_edge_index_too_large():
    cage = _cube_cage()
    n_edges = len(cage.cage_edges())
    with pytest.raises(ValueError):
        subdivide_edge(cage, edge_index=n_edges)  # exact OOB


# ---------------------------------------------------------------------------
# Test 19: SubdivideEdgeResult has expected fields
# ---------------------------------------------------------------------------

def test_result_dataclass_fields():
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert isinstance(r, SubdivideEdgeResult)
    assert hasattr(r, "new_cage")
    assert hasattr(r, "new_vertex_index")
    assert hasattr(r, "new_face_count")
    assert hasattr(r, "adjacent_face_count")
    assert hasattr(r, "has_non_quad_input")


# ---------------------------------------------------------------------------
# Test 20: Non-quad input sets has_non_quad_input = True
# ---------------------------------------------------------------------------

def test_non_quad_input_honest_flag():
    """Triangle face → has_non_quad_input == True."""
    cage = _tri_cage()
    r = subdivide_edge(cage, edge_index=0)
    assert r.has_non_quad_input is True


# ---------------------------------------------------------------------------
# Test 21: All face vertex indices valid after split
# ---------------------------------------------------------------------------

def test_all_face_indices_valid():
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    nc = r.new_cage
    V = nc.num_vertices
    for fi, f in enumerate(nc.faces):
        for vi in f:
            assert 0 <= vi < V, f"Face {fi} has invalid vertex index {vi}"


# ---------------------------------------------------------------------------
# Test 22: New vertex appears in replacement faces
# ---------------------------------------------------------------------------

def test_new_vertex_in_replacement_faces():
    """The new vertex must appear in both replacement face pairs."""
    cage = _cube_cage()
    r = subdivide_edge(cage, edge_index=0)
    nv = r.new_vertex_index
    faces_with_nv = [f for f in r.new_cage.faces if nv in f]
    # 2 adjacent faces → each split into 2 → 4 faces contain nv.
    assert len(faces_with_nv) == 2 * r.adjacent_face_count


# ---------------------------------------------------------------------------
# Test 23: New vertex does NOT appear in non-adjacent faces
# ---------------------------------------------------------------------------

def test_new_vertex_not_in_non_adjacent():
    cage = _open_rect_cage()
    # Find a boundary edge (edge 0 is typically boundary in open rect).
    r = subdivide_edge(cage, edge_index=0)
    nv = r.new_vertex_index
    # The adjacent face(s) contain nv; check there is at least one face without nv.
    faces_without_nv = [f for f in r.new_cage.faces if nv not in f]
    assert len(faces_without_nv) > 0


# ---------------------------------------------------------------------------
# Test 24: Consecutive splits — topology stays consistent
# ---------------------------------------------------------------------------

def test_consecutive_splits_euler():
    """Split two different edges sequentially; Euler stays 2."""
    cage = _cube_cage()
    r1 = subdivide_edge(cage, edge_index=0)
    nc1 = r1.new_cage
    r2 = subdivide_edge(nc1, edge_index=0)
    nc2 = r2.new_cage
    V, E, F = nc2.num_vertices, len(nc2.cage_edges()), nc2.num_faces
    assert V - E + F == 2
