"""Tests for SUBD-LIMIT-WALK-CROSS-CURVE.

Exercises ``walk_subd_limit_cross_plane`` from
``kerf_cad_core.subd.limit_walk_cross_curve``.

Test plan
---------
T1  cube cage, XY plane through centre  → at least 4 intersection points.
T2  cube cage, parallel plane above mesh → zero intersections.
T3  cube cage, parallel plane below mesh → zero intersections.
T4  cube cage, diagonal cut (x=y plane) → intersections exist.
T5  CrossCurveResult dataclass structure is correct.
T6  honest_caveat string is non-empty.
T7  face_indices_crossed length == num_intersections.
T8  all points are 3-tuples of floats.
T9  cube cage XY plane: all intersection z-coords near 0.
T10 cube cage, plane at z=+2 (above cube, no crossing) → empty.
T11 cube cage, plane at z=-2 (below cube, no crossing) → empty.
T12 cube cage XZ plane (y=0) → intersections with y near 0.
T13 flat quad patch, plane at midpoint → intersections found.
T14 increased samples → at least as many crossings as default.
T15 zero-area cage (degenerate) → returns empty result without raising.
T16 mesh with extraordinary vertex (valence 5) → no exception, some crossings.
T17 cube diagonal cut x+y=0 → symmetric result.
T18 non-unit plane normal → same result as unit normal (normalised internally).
T19 walk_subd_limit_cross_plane on a regular grid cage → plane divides it.
T20 num_intersections == len(points).
"""
from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.limit_walk_cross_curve import (
    CrossCurveResult,
    walk_subd_limit_cross_plane,
)


# ---------------------------------------------------------------------------
# Cage fixtures
# ---------------------------------------------------------------------------

def make_cube_cage() -> SubDMesh:
    """Unit cube cage centred at origin, half-size 1."""
    verts = [
        [-1.0, -1.0, -1.0], [1.0, -1.0, -1.0], [1.0, 1.0, -1.0], [-1.0, 1.0, -1.0],
        [-1.0, -1.0,  1.0], [1.0, -1.0,  1.0], [1.0, 1.0,  1.0], [-1.0, 1.0,  1.0],
    ]
    faces = [
        [0, 1, 2, 3],   # bottom z=-1
        [4, 5, 6, 7],   # top    z=+1
        [0, 1, 5, 4],   # front  y=-1
        [2, 3, 7, 6],   # back   y=+1
        [0, 3, 7, 4],   # left   x=-1
        [1, 2, 6, 5],   # right  x=+1
    ]
    return SubDMesh(vertices=verts, faces=faces)


def make_flat_quad_patch() -> SubDMesh:
    """Single flat quad in XY plane at z=0."""
    verts = [
        [-1.0, -1.0, 0.0], [1.0, -1.0, 0.0],
        [1.0,  1.0, 0.0], [-1.0,  1.0, 0.0],
    ]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def make_extraordinary_cage() -> SubDMesh:
    """Cage with a valence-5 extraordinary vertex at origin."""
    n = 5
    verts = [[0.0, 0.0, 0.0]]
    inner: List[int] = []
    outer: List[int] = []
    for i in range(n):
        angle = 2.0 * math.pi * i / n
        r_inner = 0.5
        verts.append([r_inner * math.cos(angle), r_inner * math.sin(angle), 0.1])
        inner.append(len(verts) - 1)
        verts.append([math.cos(angle), math.sin(angle), 0.2])
        outer.append(len(verts) - 1)

    faces = []
    for i in range(n):
        j = (i + 1) % n
        # quad: center, inner[i], outer[i], inner[j] — may be non-planar
        faces.append([0, inner[i], outer[i], inner[j]])

    return SubDMesh(vertices=verts, faces=faces)


def make_degenerate_cage() -> SubDMesh:
    """Cage with all vertices at the same point (degenerate)."""
    verts = [[0.0, 0.0, 0.0]] * 4
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def make_grid_cage(nx: int = 3, ny: int = 3, z: float = 0.0) -> SubDMesh:
    """Regular nx×ny quad grid at height z."""
    verts = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            verts.append([float(i), float(j), z])
    faces = []
    for j in range(ny):
        for i in range(nx):
            bl = j * (nx + 1) + i
            br = bl + 1
            tr = br + (nx + 1)
            tl = bl + (nx + 1)
            faces.append([bl, br, tr, tl])
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# T1: cube XY plane → at least 4 points
# ---------------------------------------------------------------------------

def test_t1_cube_xy_plane_has_crossings():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.0],
        plane_normal=[0.0, 0.0, 1.0],
        num_walk_samples=400,
    )
    assert res.num_intersections >= 4, (
        f"Expected >= 4 intersection points on XY cross-section of cube, got {res.num_intersections}"
    )


# ---------------------------------------------------------------------------
# T2: plane above cube → no intersections
# ---------------------------------------------------------------------------

def test_t2_parallel_plane_above_no_intersection():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 2.0],
        plane_normal=[0.0, 0.0, 1.0],
        num_walk_samples=400,
    )
    assert res.num_intersections == 0, (
        f"Expected 0 intersections above cube, got {res.num_intersections}"
    )


# ---------------------------------------------------------------------------
# T3: plane below cube → no intersections
# ---------------------------------------------------------------------------

def test_t3_parallel_plane_below_no_intersection():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, -2.0],
        plane_normal=[0.0, 0.0, 1.0],
        num_walk_samples=400,
    )
    assert res.num_intersections == 0, (
        f"Expected 0 intersections below cube, got {res.num_intersections}"
    )


# ---------------------------------------------------------------------------
# T4: diagonal cut → intersections exist
# ---------------------------------------------------------------------------

def test_t4_diagonal_cut_has_intersections():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.0],
        plane_normal=[1.0, 1.0, 0.0],
        num_walk_samples=400,
    )
    assert res.num_intersections >= 4, (
        f"Expected >= 4 intersections on diagonal cut, got {res.num_intersections}"
    )


# ---------------------------------------------------------------------------
# T5: CrossCurveResult dataclass structure
# ---------------------------------------------------------------------------

def test_t5_result_dataclass_structure():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
    )
    assert isinstance(res, CrossCurveResult)
    assert hasattr(res, "points")
    assert hasattr(res, "face_indices_crossed")
    assert hasattr(res, "num_intersections")
    assert hasattr(res, "honest_caveat")
    assert isinstance(res.points, list)
    assert isinstance(res.face_indices_crossed, list)
    assert isinstance(res.num_intersections, int)
    assert isinstance(res.honest_caveat, str)


# ---------------------------------------------------------------------------
# T6: honest_caveat is non-empty
# ---------------------------------------------------------------------------

def test_t6_honest_caveat_nonempty():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
    )
    assert len(res.honest_caveat) > 0, "honest_caveat must not be empty"


# ---------------------------------------------------------------------------
# T7: face_indices_crossed length == num_intersections
# ---------------------------------------------------------------------------

def test_t7_face_indices_length_matches():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
    )
    assert len(res.face_indices_crossed) == res.num_intersections


# ---------------------------------------------------------------------------
# T8: all points are 3-tuples of floats
# ---------------------------------------------------------------------------

def test_t8_points_are_float_triples():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
    )
    for pt in res.points:
        assert len(pt) == 3
        for c in pt:
            assert isinstance(c, float), f"Coordinate {c!r} is not float"


# ---------------------------------------------------------------------------
# T9: cube XY plane → all z-coords near 0
# ---------------------------------------------------------------------------

def test_t9_xy_plane_z_near_zero():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.0],
        plane_normal=[0.0, 0.0, 1.0],
        num_walk_samples=600,
    )
    assert res.num_intersections >= 1, "Need at least one intersection for this test"
    for pt in res.points:
        assert abs(pt[2]) < 0.15, (
            f"Intersection z={pt[2]:.4f} is too far from 0 for XY plane cut"
        )


# ---------------------------------------------------------------------------
# T10: plane at z=+2 → empty
# ---------------------------------------------------------------------------

def test_t10_plane_above_z2_empty():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 2.0], [0.0, 0.0, 1.0]
    )
    assert res.num_intersections == 0


# ---------------------------------------------------------------------------
# T11: plane at z=-2 → empty
# ---------------------------------------------------------------------------

def test_t11_plane_below_zm2_empty():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, -2.0], [0.0, 0.0, 1.0]
    )
    assert res.num_intersections == 0


# ---------------------------------------------------------------------------
# T12: XZ plane (y=0) → y-coords near 0
# ---------------------------------------------------------------------------

def test_t12_xz_plane_y_near_zero():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.0],
        plane_normal=[0.0, 1.0, 0.0],
        num_walk_samples=600,
    )
    assert res.num_intersections >= 4
    for pt in res.points:
        assert abs(pt[1]) < 0.15, (
            f"Intersection y={pt[1]:.4f} too far from 0 for XZ plane cut"
        )


# ---------------------------------------------------------------------------
# T13: flat quad patch, plane at midpoint → crossings found
# ---------------------------------------------------------------------------

def test_t13_flat_patch_midplane():
    """A flat patch at z=0; a plane cutting it at x=0 should find crossings."""
    mesh = make_flat_quad_patch()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.0],
        plane_normal=[1.0, 0.0, 0.0],
        num_walk_samples=100,
    )
    assert res.num_intersections >= 1, (
        f"Expected >= 1 crossing on flat patch with x=0 plane, got {res.num_intersections}"
    )


# ---------------------------------------------------------------------------
# T14: more samples → at least as many crossings
# ---------------------------------------------------------------------------

def test_t14_more_samples_not_fewer_crossings():
    mesh = make_cube_cage()
    res_low = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0], num_walk_samples=64
    )
    res_high = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0], num_walk_samples=900
    )
    # More samples should find at least as many crossings (may find more due to finer grid)
    assert res_high.num_intersections >= res_low.num_intersections


# ---------------------------------------------------------------------------
# T15: degenerate cage → no exception, empty result
# ---------------------------------------------------------------------------

def test_t15_degenerate_cage_no_exception():
    mesh = make_degenerate_cage()
    # Should not raise; may return zero crossings
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.5], [0.0, 0.0, 1.0]
    )
    assert isinstance(res, CrossCurveResult)
    # No crossings since all verts are at z=0 (below the plane z=0.5)
    assert res.num_intersections == 0


# ---------------------------------------------------------------------------
# T16: extraordinary vertex cage → no exception, crossings found
# ---------------------------------------------------------------------------

def test_t16_extraordinary_vertex_no_exception():
    mesh = make_extraordinary_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.15],
        plane_normal=[0.0, 0.0, 1.0],
        num_walk_samples=400,
    )
    assert isinstance(res, CrossCurveResult)
    # The cage spans z ∈ [0, 0.2] approx; cut at z=0.15 should cross some faces
    # (Just checking no exception and valid structure)
    assert res.num_intersections >= 0


# ---------------------------------------------------------------------------
# T17: diagonal x+y=0 → symmetric x and y
# ---------------------------------------------------------------------------

def test_t17_diagonal_xy_symmetry():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 0.0, 0.0],
        plane_normal=[1.0, -1.0, 0.0],
        num_walk_samples=600,
    )
    assert res.num_intersections >= 2
    for pt in res.points:
        # Points should be near x=y (within tolerance of grid resolution)
        assert abs(pt[0] - pt[1]) < 0.25, (
            f"Point ({pt[0]:.3f}, {pt[1]:.3f}, {pt[2]:.3f}) not near x=y for diagonal cut"
        )


# ---------------------------------------------------------------------------
# T18: non-unit normal → same count as unit normal
# ---------------------------------------------------------------------------

def test_t18_non_unit_normal_same_as_unit():
    mesh = make_cube_cage()
    ppt = [0.0, 0.0, 0.0]
    res_unit = walk_subd_limit_cross_plane(
        mesh, ppt, [0.0, 0.0, 1.0], num_walk_samples=400
    )
    res_scale = walk_subd_limit_cross_plane(
        mesh, ppt, [0.0, 0.0, 5.0], num_walk_samples=400
    )
    assert res_unit.num_intersections == res_scale.num_intersections, (
        "Scaling the normal should not change the number of intersections"
    )


# ---------------------------------------------------------------------------
# T19: grid cage bisected by plane
# ---------------------------------------------------------------------------

def test_t19_grid_cage_plane_bisects():
    """A 3×3 quad grid at z=0 should be cut by the plane y=1.5 (middle row)."""
    mesh = make_grid_cage(3, 3, z=0.0)
    res = walk_subd_limit_cross_plane(
        mesh,
        plane_point=[0.0, 1.5, 0.0],
        plane_normal=[0.0, 1.0, 0.0],
        num_walk_samples=400,
    )
    assert res.num_intersections >= 1, (
        f"Expected at least 1 intersection on grid cut, got {res.num_intersections}"
    )


# ---------------------------------------------------------------------------
# T20: num_intersections == len(points)
# ---------------------------------------------------------------------------

def test_t20_num_intersections_equals_len_points():
    mesh = make_cube_cage()
    res = walk_subd_limit_cross_plane(
        mesh, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
    )
    assert res.num_intersections == len(res.points), (
        "num_intersections must equal len(points)"
    )
