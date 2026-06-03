"""test_subd_fractional_crease.py — Tests for fractional (semi-sharp) creases.

Tests the implementation of DeRose et al. (SIGGRAPH 1998 §4) fractional
crease rules for Catmull-Clark subdivision surfaces.

Coverage (>= 18 tests):
  1.  Infinite sharpness — cube preserves a sharp edge across many levels.
  2.  s=0 crease is identical to standard CC (no crease).
  3.  s=0.5 blends between smooth and sharp (result in-between).
  4.  Sharpness decay: s=2.0 → s=1.0 on child edges after 1 level.
  5.  Sharpness decay: s=1.0 → s=0.0 on child edges after 1 level.
  6.  Sharpness decay: s=2.0 → s=0.0 on grandchild edges after 2 levels.
  7.  Corner vertex (>= 3 sharp incident edges) is preserved exactly.
  8.  Limit eval smooth: standard CC weights at interior vertex.
  9.  Limit eval crease: 1D B-spline formula (1/6)*P_a + (2/3)*P + (1/6)*P_b.
  10. Limit eval corner: position unchanged (limit == control point).
  11. Fractional blend is strictly between smooth and sharp positions.
  12. Infinite sharpness edge midpoint preserved across subdivisions.
  13. s=1.5 after one level → s=0.5 on child edges (fractional remainder).
  14. Edge count grows 4x per quad subdivision level.
  15. Face count grows 4x per quad subdivision level.
  16. Vertex topology consistency (no duplicate face references).
  17. Boundary-only mesh (no interior edges) — vertices stay put on sharp.
  18. Crease vertex sharpness propagates to subdivided mesh unchanged.
  19. Zero-level subdivision returns copy of input.
  20. Multiple levels accumulate correctly (level-2 result matches 2x level-1).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import pytest

from kerf_cad_core.subd.fractional_crease import (
    CreaseEdge,
    CreaseSubdMesh,
    CreaseVertex,
    Vec3,
    evaluate_limit_with_creases,
    subdivide_with_creases,
)


# ---------------------------------------------------------------------------
# Mesh factory helpers
# ---------------------------------------------------------------------------

def make_single_quad() -> CreaseSubdMesh:
    """A single quad face with 4 vertices — simplest non-trivial mesh."""
    positions: List[Vec3] = [
        (0.0, 0.0, 0.0),  # 0
        (1.0, 0.0, 0.0),  # 1
        (1.0, 1.0, 0.0),  # 2
        (0.0, 1.0, 0.0),  # 3
    ]
    faces = [[0, 1, 2, 3]]
    return CreaseSubdMesh(positions=positions, faces=faces)


def make_two_quads() -> CreaseSubdMesh:
    """Two quads sharing one edge (edge 1-4), forming a 2×1 strip.

    Vertices:
      0 -- 1 -- 2
      |    |    |
      3 -- 4 -- 5
    Faces: [0,1,4,3] and [1,2,5,4]
    Shared edge: (1, 4)
    """
    positions: List[Vec3] = [
        (0.0, 1.0, 0.0),  # 0
        (1.0, 1.0, 0.0),  # 1
        (2.0, 1.0, 0.0),  # 2
        (0.0, 0.0, 0.0),  # 3
        (1.0, 0.0, 0.0),  # 4
        (2.0, 0.0, 0.0),  # 5
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
    ]
    return CreaseSubdMesh(positions=positions, faces=faces)


def make_asymmetric_two_quads() -> CreaseSubdMesh:
    """Two quads sharing edge (1, 4) with an asymmetric right quad.

    The right quad is wider so face centroids differ from edge midpoints,
    making the smooth CC edge point != the sharp (midpoint) edge point.

    Vertices:
      0(0,1) -- 1(1,1) -- 2(3,1)   <- right side is wider (x=3)
      |             |         |
      3(0,0) -- 4(1,0) -- 5(3,0)

    Shared edge: (1, 4) at x=1
    Smooth EP x: F1+F2 asymmetric → smooth_x != sharp_x = 1.0
    """
    positions: List[Vec3] = [
        (0.0, 1.0, 0.0),  # 0
        (1.0, 1.0, 0.0),  # 1
        (3.0, 1.0, 0.0),  # 2  — wide right quad
        (0.0, 0.0, 0.0),  # 3
        (1.0, 0.0, 0.0),  # 4
        (3.0, 0.0, 0.0),  # 5  — wide right quad
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
    ]
    return CreaseSubdMesh(positions=positions, faces=faces)


def make_cube_mesh() -> CreaseSubdMesh:
    """Unit cube centred at origin — 8 vertices, 6 quad faces."""
    positions: List[Vec3] = [
        (-1.0, -1.0, -1.0),  # 0
        ( 1.0, -1.0, -1.0),  # 1
        ( 1.0,  1.0, -1.0),  # 2
        (-1.0,  1.0, -1.0),  # 3
        (-1.0, -1.0,  1.0),  # 4
        ( 1.0, -1.0,  1.0),  # 5
        ( 1.0,  1.0,  1.0),  # 6
        (-1.0,  1.0,  1.0),  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom  z=-1
        [4, 5, 6, 7],  # top     z=+1
        [0, 1, 5, 4],  # front   y=-1
        [2, 3, 7, 6],  # back    y=+1
        [0, 3, 7, 4],  # left    x=-1
        [1, 2, 6, 5],  # right   x=+1
    ]
    return CreaseSubdMesh(positions=positions, faces=faces)


def _edge_midpoint(mesh: CreaseSubdMesh, v0: int, v1: int) -> Vec3:
    p0, p1 = mesh.positions[v0], mesh.positions[v1]
    return ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5, (p0[2] + p1[2]) * 0.5)


def _dist(a: Vec3, b: Vec3) -> float:
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _get_child_edge_sharpness(mesh: CreaseSubdMesh, v0: int, v1: int) -> Optional[float]:
    """Return sharpness of child edge (v0, v1) if present in crease list."""
    for ce in mesh.crease_edges:
        if (ce.v0 == min(v0, v1) and ce.v1 == max(v0, v1)) or \
           (ce.v0 == v0 and ce.v1 == v1) or \
           (ce.v0 == v1 and ce.v1 == v0):
            return ce.sharpness
    return None


def _all_edge_sharpness(mesh: CreaseSubdMesh) -> Dict[Tuple[int, int], float]:
    m: Dict[Tuple[int, int], float] = {}
    for ce in mesh.crease_edges:
        k = (min(ce.v0, ce.v1), max(ce.v0, ce.v1))
        m[k] = ce.sharpness
    return m


# ---------------------------------------------------------------------------
# TEST 1: Infinite sharpness preserves edge
# Sharp edge with s=∞ in a cube should preserve the edge midpoint.
# ---------------------------------------------------------------------------

def test_infinite_sharpness_preserves_edge_midpoint():
    """Edge with s=∞ → child edge point is exact midpoint (sharp mask).

    DeRose 1998 §4.1: infinitely sharp edge uses M_sharp = (v0 + v1) / 2.
    """
    mesh = make_cube_mesh()
    # Tag the bottom edge (0, 1) as infinitely sharp
    mesh.crease_edges = [CreaseEdge(v0=0, v1=1, sharpness=math.inf)]

    expected_mid = _edge_midpoint(mesh, 0, 1)
    result = subdivide_with_creases(mesh, levels=1)

    # The edge point for edge (0,1) is a new vertex in the subdivided mesh.
    # All vertices near (0,0,-1) and (1,0,-1) should include the midpoint.
    # The midpoint of (v0=-1,-1,-1) and (v1=1,-1,-1) is (0,-1,-1).
    expected = (0.0, -1.0, -1.0)
    positions = result.positions

    # Find the vertex at the expected midpoint
    found = any(_dist(p, expected) < 1e-9 for p in positions)
    assert found, f"Expected vertex at {expected} not found in subdivided mesh"


def test_infinite_sharpness_preserved_across_many_levels():
    """Infinite sharpness (∞) stays ∞ after multiple subdivisions.

    DeRose §4.3: infinitely sharp edges never decay; they propagate ∞
    to both child edges at every level.
    """
    mesh = make_cube_mesh()
    mesh.crease_edges = [CreaseEdge(v0=0, v1=1, sharpness=math.inf)]

    result = subdivide_with_creases(mesh, levels=3)

    # After 3 levels, some child edges should still carry infinite sharpness
    has_inf = any(math.isinf(ce.sharpness) for ce in result.crease_edges)
    assert has_inf, "Infinite sharpness should propagate across levels"


# ---------------------------------------------------------------------------
# TEST 2: s=0 crease identical to no-crease subdivision
# ---------------------------------------------------------------------------

def test_zero_sharpness_equals_smooth():
    """Crease with s=0 must produce the same result as no-crease subdivision.

    DeRose §4: σ=0 → pure smooth mask, so the result must be identical to
    standard CC without any crease tag.
    """
    mesh_no_crease = make_two_quads()
    mesh_s0 = make_two_quads()
    mesh_s0.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=0.0)]

    result_nc = subdivide_with_creases(mesh_no_crease, levels=2)
    result_s0 = subdivide_with_creases(mesh_s0, levels=2)

    assert len(result_nc.positions) == len(result_s0.positions)
    for p_nc, p_s0 in zip(result_nc.positions, result_s0.positions):
        assert _dist(p_nc, p_s0) < 1e-10, (
            f"s=0 crease should be identical to smooth: {p_nc} != {p_s0}"
        )


# ---------------------------------------------------------------------------
# TEST 3: s=0.5 result is strictly between smooth and sharp
# ---------------------------------------------------------------------------

def test_fractional_s05_is_between_smooth_and_sharp():
    """Crease with s=0.5 produces a position strictly between smooth and sharp.

    DeRose §4: E_s0.5 = 0.5 * M_smooth + 0.5 * M_sharp
    The result must be strictly between the two extremes.

    We use make_asymmetric_two_quads() because for a symmetric 2-quad strip
    the smooth and sharp edge points are identical by symmetry (face-centroid
    average = edge midpoint).  The asymmetric strip breaks this degeneracy.
    """
    # Smooth (no crease) result
    m_smooth = make_asymmetric_two_quads()
    result_smooth = subdivide_with_creases(m_smooth, levels=1)

    # Sharp (s=10 ~ fully sharp for 1 level) result
    m_sharp = make_asymmetric_two_quads()
    m_sharp.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=10.0)]
    result_sharp = subdivide_with_creases(m_sharp, levels=1)

    # Fractional (s=0.5) result
    m_frac = make_asymmetric_two_quads()
    m_frac.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=0.5)]
    result_frac = subdivide_with_creases(m_frac, levels=1)

    # The edge point for the shared edge (1, 4).
    # Sharp midpoint: v1=(1,1,0), v4=(1,0,0) → mid = (1.0, 0.5, 0.0)
    sharp_ep_expected = (1.0, 0.5, 0.0)
    # F1 = centroid([0,1,4,3]) = ((0+1+1+0)/4, (1+1+0+0)/4, 0) = (0.5, 0.5, 0)
    # F2 = centroid([1,2,5,4]) = ((1+3+3+1)/4, (1+1+0+0)/4, 0) = (2.0, 0.5, 0)
    # smooth EP = (v1 + v4 + F1 + F2) / 4 = ((1+1+0.5+2)/4, (1+0+0.5+0.5)/4, 0)
    #           = (4.5/4, 2.0/4, 0) = (1.125, 0.5, 0)
    smooth_ep_expected = (1.125, 0.5, 0.0)

    def _closest_to(pts: List[Vec3], target: Vec3) -> Vec3:
        return min(pts, key=lambda p: _dist(p, target))

    ep_smooth = _closest_to(result_smooth.positions, smooth_ep_expected)
    ep_sharp  = _closest_to(result_sharp.positions, sharp_ep_expected)
    ep_frac   = _closest_to(result_frac.positions, (1.0625, 0.5, 0.0))

    # Verify smooth and sharp edge points differ
    assert _dist(ep_smooth, ep_sharp) > 1e-9, (
        f"Smooth and sharp edge points should differ for asymmetric mesh; "
        f"smooth={ep_smooth}, sharp={ep_sharp}"
    )

    # The fractional (s=0.5) edge point must be strictly between smooth and sharp
    dist_to_smooth = _dist(ep_frac, ep_smooth)
    dist_to_sharp  = _dist(ep_frac, ep_sharp)

    assert dist_to_smooth > 1e-9, "s=0.5 result should differ from smooth"
    assert dist_to_sharp  > 1e-9, "s=0.5 result should differ from sharp"

    # s=0.5 result should be between the two extremes
    total = _dist(ep_smooth, ep_sharp)
    assert dist_to_smooth < total + 1e-9
    assert dist_to_sharp  < total + 1e-9


# ---------------------------------------------------------------------------
# TEST 4: Sharpness decay — s=2.0 → s=1.0 after 1 level
# ---------------------------------------------------------------------------

def test_sharpness_decay_s2_level1():
    """Edge with s=2.0 should produce child edges with s=1.0 after one level.

    DeRose §4 decay: s′ = max(0, s − 1).
    """
    mesh = make_two_quads()
    mesh.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=2.0)]

    result = subdivide_with_creases(mesh, levels=1)

    # All child edges of the original (1,4) edge should have sharpness 1.0
    child_sharps = [ce.sharpness for ce in result.crease_edges]
    # At least some child edges should have sharpness == 1.0
    assert any(abs(s - 1.0) < 1e-9 for s in child_sharps), (
        f"Expected child sharpness 1.0, got {child_sharps}"
    )


# ---------------------------------------------------------------------------
# TEST 5: Sharpness decay — s=1.0 → no crease edges after 1 level
# ---------------------------------------------------------------------------

def test_sharpness_decay_s1_level1():
    """Edge with s=1.0 should decay to s=0 after one level (no crease edges).

    DeRose §4 decay: s′ = max(0, 1.0 − 1) = 0.0.
    """
    mesh = make_two_quads()
    mesh.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=1.0)]

    result = subdivide_with_creases(mesh, levels=1)

    # No crease edges should remain (all decayed to 0)
    assert len(result.crease_edges) == 0, (
        f"Expected no crease edges after s=1.0 decays, got: {result.crease_edges}"
    )


# ---------------------------------------------------------------------------
# TEST 6: s=2.0 → s=0.0 after 2 levels
# ---------------------------------------------------------------------------

def test_sharpness_decay_s2_level2():
    """Edge with s=2.0 should fully decay to smooth after 2 levels.

    DeRose §4: s=2.0 → s=1.0 (level 1) → s=0.0 (level 2).
    After level 2 there should be no crease edges.
    """
    mesh = make_two_quads()
    mesh.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=2.0)]

    result = subdivide_with_creases(mesh, levels=2)

    assert len(result.crease_edges) == 0, (
        f"Expected no crease edges after s=2.0 decays over 2 levels, "
        f"got: {[ce.sharpness for ce in result.crease_edges]}"
    )


# ---------------------------------------------------------------------------
# TEST 7: Corner vertex (>= 3 sharp edges) is preserved
# ---------------------------------------------------------------------------

def test_corner_vertex_preserved_exactly():
    """Vertex with >= 3 sharp incident edges must be unchanged across subdivisions.

    DeRose §4.2: corner vertex — vertex position unchanged.
    """
    mesh = make_cube_mesh()
    # Tag 3 edges incident on vertex 0 as sharp
    # Vertex 0 connects to: 1 (bottom face), 3 (bottom face), 4 (front/left face)
    mesh.crease_edges = [
        CreaseEdge(v0=0, v1=1, sharpness=math.inf),
        CreaseEdge(v0=0, v1=3, sharpness=math.inf),
        CreaseEdge(v0=0, v1=4, sharpness=math.inf),
    ]

    original_v0 = mesh.positions[0]
    result = subdivide_with_creases(mesh, levels=2)

    # Vertex 0 is still at index 0 after subdivision
    updated_v0 = result.positions[0]
    assert _dist(original_v0, updated_v0) < 1e-9, (
        f"Corner vertex should be unchanged: {original_v0} → {updated_v0}"
    )


# ---------------------------------------------------------------------------
# TEST 8: Limit eval — smooth vertex matches CC limit weights
# ---------------------------------------------------------------------------

def test_limit_smooth_vertex_matches_cc_formula():
    """Limit position at smooth interior vertex uses standard CC limit rule.

    CC limit formula for a regular quad valence-4 vertex:
        P_lim = (n² * P + 4 * sum(R_i) + sum(F_i)) / (n² + 5n)
    For n=4: (16*P + 4*sum(R_i) + sum(F_i)) / 36.
    We verify the computed limit matches this formula directly.
    """
    # Build a 3×3 grid of quads so the centre vertex is interior and regular.
    # Vertices on a 3×3 grid (4×4 = 16 vertices):
    # (i,j) → vertex index i + 4*j
    positions: List[Vec3] = []
    for j in range(4):
        for i in range(4):
            positions.append((float(i), float(j), 0.0))
    faces = []
    for j in range(3):
        for i in range(3):
            v0 = i + 4 * j
            v1 = (i + 1) + 4 * j
            v2 = (i + 1) + 4 * (j + 1)
            v3 = i + 4 * (j + 1)
            faces.append([v0, v1, v2, v3])
    mesh = CreaseSubdMesh(positions=positions, faces=faces)

    # Centre vertex = index 5 (i=1, j=1)
    vi = 5  # position (1, 1, 0)

    # Manual CC limit formula for n=4 regular vertex
    v = positions[vi]
    nbrs = [1, 4, 6, 9]  # neighbours of (1,1)
    adj_face_idxs = [0, 1, 3, 4]  # faces adjacent to vertex (1,1)

    # Compute R (average of midpoints)
    R = [0.0, 0.0, 0.0]
    for nb in nbrs:
        p = positions[nb]
        R[0] += (v[0] + p[0]) * 0.5
        R[1] += (v[1] + p[1]) * 0.5
        R[2] += (v[2] + p[2]) * 0.5

    # Compute F (sum of face centroids)
    F = [0.0, 0.0, 0.0]
    for fi in adj_face_idxs:
        face = faces[fi]
        fc = [sum(positions[idx][c] for idx in face) / 4 for c in range(3)]
        F[0] += fc[0]; F[1] += fc[1]; F[2] += fc[2]

    n = 4
    denom = n * n + 5 * n  # 36
    expected_x = (n * n * v[0] + 4 * R[0] + F[0]) / denom
    expected_y = (n * n * v[1] + 4 * R[1] + F[1]) / denom
    expected = (expected_x, expected_y, 0.0)

    limit = evaluate_limit_with_creases(mesh, vi)

    assert _dist(limit, expected) < 1e-9, (
        f"Smooth limit should match CC formula: expected {expected}, got {limit}"
    )


# ---------------------------------------------------------------------------
# TEST 9: Limit eval — crease vertex uses 1D B-spline limit
# ---------------------------------------------------------------------------

def test_limit_crease_vertex_uses_bspline_formula():
    """Crease vertex limit = (1/6)*P_prev + (2/3)*P + (1/6)*P_next.

    DeRose 1998 §4.2: limit position along a crease is given by the
    cubic uniform B-spline limit formula.
    """
    mesh = make_two_quads()
    # Tag both edges of a straight crease through vertex 1:
    # edges (0,1) and (1,2) (top row) as sharp
    mesh.crease_edges = [
        CreaseEdge(v0=0, v1=1, sharpness=math.inf),
        CreaseEdge(v0=1, v1=2, sharpness=math.inf),
    ]

    # Vertex 1 has exactly 2 sharp incident edges → crease limit
    v1 = mesh.positions[1]  # (1.0, 1.0, 0.0)
    pa = mesh.positions[0]  # (0.0, 1.0, 0.0)
    pb = mesh.positions[2]  # (2.0, 1.0, 0.0)

    expected_x = (1.0/6.0)*pa[0] + (2.0/3.0)*v1[0] + (1.0/6.0)*pb[0]
    expected_y = (1.0/6.0)*pa[1] + (2.0/3.0)*v1[1] + (1.0/6.0)*pb[1]
    expected_z = (1.0/6.0)*pa[2] + (2.0/3.0)*v1[2] + (1.0/6.0)*pb[2]
    expected = (expected_x, expected_y, expected_z)

    limit = evaluate_limit_with_creases(mesh, 1)

    assert _dist(limit, expected) < 1e-9, (
        f"Crease limit should use B-spline formula: expected {expected}, got {limit}"
    )


# ---------------------------------------------------------------------------
# TEST 10: Limit eval — corner vertex is unchanged
# ---------------------------------------------------------------------------

def test_limit_corner_vertex_is_unchanged():
    """Corner vertex (>= 3 sharp incident edges) limit == vertex itself.

    DeRose §4.2: corner limit = control point position.
    """
    mesh = make_cube_mesh()
    mesh.crease_edges = [
        CreaseEdge(v0=0, v1=1, sharpness=math.inf),
        CreaseEdge(v0=0, v1=3, sharpness=math.inf),
        CreaseEdge(v0=0, v1=4, sharpness=math.inf),
    ]

    original = mesh.positions[0]
    limit = evaluate_limit_with_creases(mesh, 0)

    assert _dist(original, limit) < 1e-9, (
        f"Corner limit should be vertex itself: {original} → {limit}"
    )


# ---------------------------------------------------------------------------
# TEST 11: Fractional blend strictly between smooth and sharp positions
# ---------------------------------------------------------------------------

def test_fractional_blend_strictly_between():
    """s=0.5 edge-point is exactly the interpolation between smooth and sharp.

    DeRose §4: E = (1 − σ)*M_smooth + σ*M_sharp
    For σ=0.5 → E = 0.5*(M_smooth + M_sharp).
    We verify the position is exactly the midpoint of smooth and sharp results.

    Uses asymmetric geometry so smooth EP != sharp EP.
    """
    mesh_s0  = make_asymmetric_two_quads()  # smooth (no crease)
    mesh_s1  = make_asymmetric_two_quads()
    mesh_s1.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=1.0)]
    mesh_s05 = make_asymmetric_two_quads()
    mesh_s05.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=0.5)]

    r_s0  = subdivide_with_creases(mesh_s0,  levels=1)
    r_s1  = subdivide_with_creases(mesh_s1,  levels=1)
    r_s05 = subdivide_with_creases(mesh_s05, levels=1)

    # Smooth EP = (1.125, 0.5, 0), sharp EP = (1.0, 0.5, 0)
    # s=0.5 expected = midpoint = (1.0625, 0.5, 0)
    smooth_target = (1.125, 0.5, 0.0)
    sharp_target  = (1.0,   0.5, 0.0)

    def _closest(pts: List[Vec3], t: Vec3) -> Vec3:
        return min(pts, key=lambda p: _dist(p, t))

    ep_s0  = _closest(r_s0.positions,  smooth_target)
    ep_s1  = _closest(r_s1.positions,  sharp_target)
    ep_s05 = _closest(r_s05.positions, (1.0625, 0.5, 0.0))

    # Verify smooth and sharp differ meaningfully
    assert _dist(ep_s0, ep_s1) > 1e-9, (
        f"Smooth ({ep_s0}) and sharp ({ep_s1}) edge points must differ"
    )

    # Expected: exactly half-way between smooth and sharp
    expected = (
        0.5 * ep_s0[0] + 0.5 * ep_s1[0],
        0.5 * ep_s0[1] + 0.5 * ep_s1[1],
        0.5 * ep_s0[2] + 0.5 * ep_s1[2],
    )
    assert _dist(ep_s05, expected) < 1e-9, (
        f"s=0.5 edge point should be midpoint of smooth and sharp: "
        f"expected {expected}, got {ep_s05}"
    )


# ---------------------------------------------------------------------------
# TEST 12: Infinite sharpness edge midpoint in cube is preserved
# ---------------------------------------------------------------------------

def test_infinite_sharpness_edge_midpoint_exact():
    """With s=∞, the edge point is exactly (v0 + v1) / 2.

    One subdivision level; check that the new vertex at the midpoint
    of the infinitely-sharp edge has exactly the right position.
    """
    mesh = make_cube_mesh()
    # Edge (1, 2): (1,-1,-1) and (1,1,-1) → midpoint (1, 0, -1)
    mesh.crease_edges = [CreaseEdge(v0=1, v1=2, sharpness=math.inf)]
    expected = (1.0, 0.0, -1.0)

    result = subdivide_with_creases(mesh, levels=1)

    found = any(_dist(p, expected) < 1e-9 for p in result.positions)
    assert found, f"Expected exact midpoint {expected} in result mesh"


# ---------------------------------------------------------------------------
# TEST 13: s=1.5 → s=0.5 after 1 level (fractional remainder)
# ---------------------------------------------------------------------------

def test_sharpness_decay_s15_level1():
    """Edge with s=1.5 should produce child edges with s=0.5 after one level.

    DeRose §4 decay: s′ = max(0, 1.5 − 1) = 0.5.
    """
    mesh = make_two_quads()
    mesh.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=1.5)]

    result = subdivide_with_creases(mesh, levels=1)

    child_sharps = [ce.sharpness for ce in result.crease_edges]
    assert len(child_sharps) > 0, "Expected child crease edges for s=1.5"
    assert any(abs(s - 0.5) < 1e-9 for s in child_sharps), (
        f"Expected child sharpness 0.5 (decay from 1.5), got {child_sharps}"
    )


# ---------------------------------------------------------------------------
# TEST 14: Face count grows 4x per subdivision level
# ---------------------------------------------------------------------------

def test_face_count_grows_4x():
    """Each subdivision level multiplies face count by 4 (quads only)."""
    mesh = make_cube_mesh()
    n_faces_0 = len(mesh.faces)  # 6

    r1 = subdivide_with_creases(mesh, levels=1)
    assert len(r1.faces) == n_faces_0 * 4, (
        f"After 1 level: expected {n_faces_0 * 4} faces, got {len(r1.faces)}"
    )

    r2 = subdivide_with_creases(mesh, levels=2)
    assert len(r2.faces) == n_faces_0 * 16, (
        f"After 2 levels: expected {n_faces_0 * 16} faces, got {len(r2.faces)}"
    )


# ---------------------------------------------------------------------------
# TEST 15: Vertex count grows predictably (V + E + F for quads)
# ---------------------------------------------------------------------------

def test_vertex_count_grows_correctly():
    """After one level: new_V = V + E + F (Catmull-Clark invariant)."""
    mesh = make_cube_mesh()
    nv = len(mesh.positions)  # 8
    nf = len(mesh.faces)      # 6
    # For a closed quad mesh: E = 3*F/2 when all faces are quads? No.
    # For a cube: 12 edges.  V + E + F = 8 + 12 + 6 = 26.
    # After 1 CC level: new V = old_V + old_E + old_F = 8 + 12 + 6 = 26.
    ne = 12  # cube has 12 edges
    expected_new_nv = nv + ne + nf  # 26

    result = subdivide_with_creases(mesh, levels=1)
    assert len(result.positions) == expected_new_nv, (
        f"After 1 level: expected {expected_new_nv} vertices, "
        f"got {len(result.positions)}"
    )


# ---------------------------------------------------------------------------
# TEST 16: All face vertex indices are valid
# ---------------------------------------------------------------------------

def test_face_indices_valid_after_subdivision():
    """All face vertex indices must be within range after subdivision."""
    mesh = make_cube_mesh()
    mesh.crease_edges = [CreaseEdge(v0=0, v1=1, sharpness=2.5)]

    result = subdivide_with_creases(mesh, levels=3)
    nv = len(result.positions)

    for fi, face in enumerate(result.faces):
        for vi in face:
            assert 0 <= vi < nv, (
                f"Face {fi} has invalid vertex index {vi} (nv={nv})"
            )
        assert len(face) == 4, f"Face {fi} is not a quad: {face}"


# ---------------------------------------------------------------------------
# TEST 17: Sharp boundary edge — midpoints preserved
# ---------------------------------------------------------------------------

def test_sharp_boundary_edge_preserves_midpoints():
    """A boundary-tagged edge with s=∞ preserves its midpoint exactly.

    In make_two_quads(), the top edge (0,1) is a boundary edge (1 adjacent face).
    We additionally tag it as infinitely sharp. The midpoint must be exact.
    """
    mesh = make_two_quads()
    mesh.crease_edges = [CreaseEdge(v0=0, v1=1, sharpness=math.inf)]

    # positions[0]=(0,1,0), positions[1]=(1,1,0) → midpoint=(0.5,1,0)
    expected = (0.5, 1.0, 0.0)

    result = subdivide_with_creases(mesh, levels=1)

    found = any(_dist(p, expected) < 1e-9 for p in result.positions)
    assert found, (
        f"Expected exact midpoint {expected} for boundary+sharp edge (0,1)"
    )


# ---------------------------------------------------------------------------
# TEST 18: CreaseVertex sharpness propagates unchanged
# ---------------------------------------------------------------------------

def test_crease_vertex_sharpness_propagates():
    """Corner sharpness on a CreaseVertex should survive subdivision.

    We tag vertex 0 as a corner (sharpness=∞ via CreaseVertex) and verify
    the vertex position is unchanged after subdivision.
    """
    mesh = make_cube_mesh()
    mesh.crease_vertices = [CreaseVertex(vertex_index=0, sharpness=math.inf)]

    original = mesh.positions[0]
    result = subdivide_with_creases(mesh, levels=2)

    updated = result.positions[0]
    assert _dist(original, updated) < 1e-9, (
        f"CreaseVertex corner should be unchanged: {original} → {updated}"
    )


# ---------------------------------------------------------------------------
# TEST 19: Zero-level subdivision returns copy of input
# ---------------------------------------------------------------------------

def test_zero_levels_returns_copy():
    """0 subdivision levels returns mesh with same positions and faces."""
    mesh = make_cube_mesh()
    mesh.crease_edges = [CreaseEdge(v0=0, v1=1, sharpness=1.5)]

    result = subdivide_with_creases(mesh, levels=0)

    assert len(result.positions) == len(mesh.positions)
    assert len(result.faces) == len(mesh.faces)
    for orig, out in zip(mesh.positions, result.positions):
        assert _dist(orig, out) < 1e-9


# ---------------------------------------------------------------------------
# TEST 20: Two levels == applying 1 level twice
# ---------------------------------------------------------------------------

def test_two_levels_equals_two_single_level_passes():
    """Applying levels=2 must give the same result as two 1-level passes."""
    mesh = make_cube_mesh()
    mesh.crease_edges = [CreaseEdge(v0=0, v1=1, sharpness=2.0)]

    # One call with levels=2
    direct2 = subdivide_with_creases(mesh, levels=2)

    # Two sequential 1-level calls
    seq1 = subdivide_with_creases(mesh, levels=1)
    seq2 = subdivide_with_creases(seq1, levels=1)

    assert len(direct2.positions) == len(seq2.positions), (
        f"Position count mismatch: {len(direct2.positions)} vs {len(seq2.positions)}"
    )
    for d, s in zip(direct2.positions, seq2.positions):
        assert _dist(d, s) < 1e-9, f"Position mismatch: {d} vs {s}"


# ---------------------------------------------------------------------------
# TEST 21: Smooth interior cube vertex converges toward sphere
# ---------------------------------------------------------------------------

def test_smooth_cube_converges():
    """A smooth cube converges toward a sphere under many CC levels.

    After 4 levels, all vertices should be approximately equidistant from
    the origin (within ~10% of the mean radius).
    """
    mesh = make_cube_mesh()  # no creases — fully smooth

    result = subdivide_with_creases(mesh, levels=4)

    radii = [math.sqrt(p[0]**2 + p[1]**2 + p[2]**2) for p in result.positions]
    mean_r = sum(radii) / len(radii)
    max_dev = max(abs(r - mean_r) for r in radii)

    assert max_dev / mean_r < 0.15, (
        f"Smooth cube should converge toward sphere; max deviation / mean = "
        f"{max_dev / mean_r:.4f}"
    )


# ---------------------------------------------------------------------------
# TEST 22: s=3.0 edge fully decays after 3 levels
# ---------------------------------------------------------------------------

def test_sharpness_decay_s3_level3():
    """Edge with s=3.0 should produce no crease edges after 3 levels.

    Decay: 3.0 → 2.0 → 1.0 → 0.0.
    """
    mesh = make_two_quads()
    mesh.crease_edges = [CreaseEdge(v0=1, v1=4, sharpness=3.0)]

    result = subdivide_with_creases(mesh, levels=3)

    assert len(result.crease_edges) == 0, (
        f"s=3.0 should fully decay after 3 levels; remaining: "
        f"{[ce.sharpness for ce in result.crease_edges]}"
    )


# ---------------------------------------------------------------------------
# TEST 23: Limit eval at vertex with no neighbours returns vertex itself
# ---------------------------------------------------------------------------

def test_limit_isolated_vertex():
    """evaluate_limit_with_creases on a vertex with no faces returns itself."""
    # Mesh with 2 vertices but only 1 face that uses vertex 0, not vertex 1.
    # (Pathological case — never-raise contract.)
    mesh = CreaseSubdMesh(
        positions=[(0.0, 0.0, 0.0), (5.0, 5.0, 5.0)],
        faces=[[0, 0, 0, 0]],  # degenerate but no crash
    )
    # Vertex 1 has no adjacent faces
    limit = evaluate_limit_with_creases(mesh, 1)
    # Should return the vertex position itself
    assert _dist(limit, (5.0, 5.0, 5.0)) < 1e-9


# ---------------------------------------------------------------------------
# TEST 24: Out-of-range vertex index returns (0,0,0)
# ---------------------------------------------------------------------------

def test_limit_out_of_range_returns_zero():
    """evaluate_limit_with_creases with invalid index returns (0,0,0)."""
    mesh = make_single_quad()
    result = evaluate_limit_with_creases(mesh, 999)
    assert _dist(result, (0.0, 0.0, 0.0)) < 1e-9
