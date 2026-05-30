"""test_subd_edge_walk.py
=======================
Tests for subd_edge_walk.py — SUBD-LIMIT-WALK-ALONG-EDGES.

Coverage:
  1. Flat 2x2 plane boundary walk: limit on z=0 plane (boundary = creased).
  2. Interior creased edge walk: limit near the crease line (x ~ const).
  3. Smooth interior edge walk: positive arc length, points > 2.
  4. Arc length consistency: sum of segment lengths matches arc_length field.
  5. Invalid vertex sequence (non-adjacent vertices) raises ValueError.
  6. Single edge (2 vertices) produces correct point count.
  7. Long multi-edge chain produces positive arc length with x increasing.
  8. samples_per_edge=1 returns 1 + n_edges points (endpoints only).
  9. Point count = 1 + n_edges * samples_per_edge.
 10. Closed-loop boundary walk has positive arc length near perimeter.
 11. Out-of-range vertex index raises ValueError.
 12. Sequence of length 1 raises ValueError.
 13. Boundary edge: z=0 preserved throughout walk.
 14. Smooth interior edge with no crease has positive arc length.
"""

from __future__ import annotations

import math
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_edge_walk import SubDEdgeWalk, walk_along_cage_edges


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _flat_plane_2x2() -> SubDMesh:
    """2x2 grid of quads (3x3 = 9 vertices) in the XY plane.

    Vertex layout:
      6--7--8
      |  |  |
      3--4--5
      |  |  |
      0--1--2

    Boundary edges are creased via quad_mesh_to_subd.
    """
    from kerf_cad_core.geom.subd import quad_mesh_to_subd
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 1.0, 0.0],
        [2.0, 1.0, 0.0],
        [0.0, 2.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, 2.0, 0.0],
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    return quad_mesh_to_subd(verts, faces)


def _single_quad() -> SubDMesh:
    """Single unit square quad, all boundary edges creased."""
    from kerf_cad_core.geom.subd import quad_mesh_to_subd
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return quad_mesh_to_subd(verts, faces)


# ---------------------------------------------------------------------------
# Test 1: Flat plane boundary walk — all points on z=0 (flat plane)
# ---------------------------------------------------------------------------

def test_boundary_walk_flat_plane_z_zero():
    """Bottom boundary 0->1->2 of flat plane: all limit points on z=0."""
    cage = _flat_plane_2x2()
    result = walk_along_cage_edges(cage, [0, 1, 2], samples_per_edge=4)
    assert isinstance(result, SubDEdgeWalk)
    for pt in result.points:
        assert abs(pt[2]) < 1e-9, f"z={pt[2]} expected 0 on flat plane"
    # x should increase monotonically
    xs = [pt[0] for pt in result.points]
    for i in range(len(xs) - 1):
        assert xs[i] <= xs[i + 1] + 1e-12, f"x not monotone at {i}: {xs}"


# ---------------------------------------------------------------------------
# Test 2: Creased interior edge walk — limit near the crease
# ---------------------------------------------------------------------------

def test_creased_interior_edge_walk():
    """Creased edge 1->4 at x=1: all limit points near x=1."""
    cage = _flat_plane_2x2()
    cage.set_crease(1, 4, 1.0)
    result = walk_along_cage_edges(cage, [1, 4], samples_per_edge=4)
    assert len(result.points) >= 2
    assert result.arc_length > 0.0
    for pt in result.points:
        assert abs(pt[0] - 1.0) < 0.05, f"Expected x near 1 on crease, got {pt}"


# ---------------------------------------------------------------------------
# Test 3: Smooth interior edge walk — limit differs from cage
# ---------------------------------------------------------------------------

def test_smooth_interior_edge_walk():
    """Interior edge 4->7 (smooth, no crease) produces valid walk."""
    cage = _flat_plane_2x2()
    ekey = cage.edge_key(4, 7)
    cage.creases.pop(ekey, None)
    result = walk_along_cage_edges(cage, [4, 7], samples_per_edge=8)
    assert len(result.points) > 2
    assert result.arc_length > 0.0


# ---------------------------------------------------------------------------
# Test 4: Arc length consistency
# ---------------------------------------------------------------------------

def test_arc_length_matches_segment_sum():
    """arc_length field equals sum of segment lengths."""
    cage = _flat_plane_2x2()
    result = walk_along_cage_edges(cage, [0, 1, 2], samples_per_edge=6)
    pts = result.points
    seg_sum = sum(
        math.sqrt(sum((pts[i+1][j] - pts[i][j])**2 for j in range(3)))
        for i in range(len(pts) - 1)
    )
    assert abs(result.arc_length - seg_sum) < 1e-10


# ---------------------------------------------------------------------------
# Test 5: Non-adjacent vertices raise ValueError
# ---------------------------------------------------------------------------

def test_non_adjacent_vertices_raise():
    """Vertices 0 and 8 are not adjacent in the 2x2 grid."""
    cage = _flat_plane_2x2()
    with pytest.raises(ValueError, match="do not share a cage edge"):
        walk_along_cage_edges(cage, [0, 8])


# ---------------------------------------------------------------------------
# Test 6: Single edge (2 vertices) point count
# ---------------------------------------------------------------------------

def test_single_edge_point_count():
    """Single boundary edge 0->1: 1 + 1 * spe = spe + 1 points."""
    cage = _single_quad()
    spe = 4
    result = walk_along_cage_edges(cage, [0, 1], samples_per_edge=spe)
    assert len(result.points) == spe + 1
    assert result.arc_length > 0.0


# ---------------------------------------------------------------------------
# Test 7: Long multi-edge chain has positive arc length and x increasing
# ---------------------------------------------------------------------------

def test_long_chain_arc_length():
    """5-vertex chain along the bottom row of a wider mesh."""
    from kerf_cad_core.geom.subd import quad_mesh_to_subd
    verts = [[float(i), 0.0, 0.0] for i in range(5)] + \
            [[float(i), 1.0, 0.0] for i in range(5)]
    faces = [[i, i+1, i+6, i+5] for i in range(4)]
    cage = quad_mesh_to_subd(verts, faces)
    result = walk_along_cage_edges(cage, [0, 1, 2, 3, 4], samples_per_edge=4)
    assert result.arc_length > 0.0
    xs = [pt[0] for pt in result.points]
    assert xs[-1] > xs[0]


# ---------------------------------------------------------------------------
# Test 8: samples_per_edge=1 returns 1 + n_edges points
# ---------------------------------------------------------------------------

def test_samples_per_edge_1():
    """samples_per_edge=1 -> 1 start + 1 per edge = n_verts points."""
    cage = _flat_plane_2x2()
    result = walk_along_cage_edges(cage, [0, 1, 2], samples_per_edge=1)
    assert len(result.points) == 3  # 1 start + 2 endpoints


# ---------------------------------------------------------------------------
# Test 9: Point count formula
# ---------------------------------------------------------------------------

def test_point_count_formula():
    """Total points = 1 + n_edges * samples_per_edge."""
    cage = _flat_plane_2x2()
    spe = 4
    vseq = [0, 1, 2]
    result = walk_along_cage_edges(cage, vseq, samples_per_edge=spe)
    n_edges = len(vseq) - 1
    assert len(result.points) == 1 + n_edges * spe


# ---------------------------------------------------------------------------
# Test 10: Closed-loop boundary walk has correct arc length
# ---------------------------------------------------------------------------

def test_closed_loop_walk():
    """Closed boundary walk of the single quad: arc length near perimeter.

    The first vertex is sampled via subd_limit_position on the original cage;
    the final endpoint is sampled from the subdivided mesh.  These converge
    as levels increase but are not bit-identical at finite depth.  We check
    that the result is within a plausible range of the unit-square perimeter.
    """
    cage = _single_quad()
    result = walk_along_cage_edges(cage, [0, 1, 2, 3, 0], samples_per_edge=4)
    assert result.arc_length > 0.0
    # Unit square perimeter = 4.0; CC boundary limit stays on cage for corners.
    assert 3.0 < result.arc_length < 5.0, f"Perimeter {result.arc_length} out of range"


# ---------------------------------------------------------------------------
# Test 11: Out-of-range vertex raises ValueError
# ---------------------------------------------------------------------------

def test_out_of_range_vertex_raises():
    cage = _flat_plane_2x2()
    with pytest.raises(ValueError, match="out of range"):
        walk_along_cage_edges(cage, [0, 999])


# ---------------------------------------------------------------------------
# Test 12: Sequence length < 2 raises ValueError
# ---------------------------------------------------------------------------

def test_sequence_too_short_raises():
    cage = _flat_plane_2x2()
    with pytest.raises(ValueError, match="at least 2"):
        walk_along_cage_edges(cage, [0])


# ---------------------------------------------------------------------------
# Test 13: Boundary edge z=0 throughout walk
# ---------------------------------------------------------------------------

def test_boundary_edge_z_zero():
    """Bottom boundary edge 0->1: all limit points on z=0 (flat plane)."""
    cage = _flat_plane_2x2()
    result = walk_along_cage_edges(cage, [0, 1], samples_per_edge=8)
    for pt in result.points:
        assert abs(pt[2]) < 1e-8, f"z={pt[2]} should be 0 on flat plane"


# ---------------------------------------------------------------------------
# Test 14: Smooth interior edge has positive arc length
# ---------------------------------------------------------------------------

def test_smooth_interior_arc_length_positive():
    """Smooth interior edge 3->4 on the 2x2 plane has positive arc length."""
    cage = _flat_plane_2x2()
    ekey = cage.edge_key(3, 4)
    cage.creases.pop(ekey, None)
    result = walk_along_cage_edges(cage, [3, 4], samples_per_edge=8)
    assert result.arc_length > 0.0
    assert len(result.points) > 2
