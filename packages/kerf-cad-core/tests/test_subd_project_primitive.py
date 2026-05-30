"""
Tests for kerf_cad_core.geom.subd_project_primitive
====================================================

Coverage:
  1.  cube→sphere: all 8 corners at exactly radius=1 from origin
  2.  cube→sphere: ProjectionReport max_projection_distance > 0
  3.  cube→sphere: identity — vertices already on sphere → zero displacement
  4.  cube→cylinder (Z-axis, r=1): all vertices at radius 1 from Z-axis
  5.  cylinder: Z-coordinates are preserved after radial projection
  6.  cylinder: identity — vertices already on cylinder → zero displacement
  7.  cage→plane (XY): all vertices at z=0
  8.  plane: signed distance of all vertices to plane == 0 (both sides)
  9.  plane: identity — vertices already on plane → zero displacement
  10. ProjectionReport fields populated correctly (num_vertices, mean, max)
  11. Re-export from geom/__init__.py
  12. Never-raise: empty cage
  13. Never-raise: degenerate zero-radius sphere (clamped to 1e-9)
  14. Topology preserved: faces unchanged after projection
  15. Cage independence: projecting doesn't mutate original cage
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd_authoring import SubDCage
from kerf_cad_core.geom.subd_project_primitive import (
    ProjectionReport,
    project_cage_to_cylinder,
    project_cage_to_plane,
    project_cage_to_sphere,
)


# ---------------------------------------------------------------------------
# Helper: unit cube cage (8 vertices, 6 quad faces)
# ---------------------------------------------------------------------------

def _unit_cube_cage(half: float = 1.0) -> SubDCage:
    h = half
    verts = [
        [-h, -h, -h],  # 0
        [ h, -h, -h],  # 1
        [ h,  h, -h],  # 2
        [-h,  h, -h],  # 3
        [-h, -h,  h],  # 4
        [ h, -h,  h],  # 5
        [ h,  h,  h],  # 6
        [-h,  h,  h],  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom -z
        [4, 7, 6, 5],  # top +z
        [0, 4, 5, 1],  # front -y
        [3, 2, 6, 7],  # back +y
        [0, 3, 7, 4],  # left -x
        [1, 5, 6, 2],  # right +x
    ]
    return SubDCage(vertices=verts, faces=faces)


def _dist(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


# ---------------------------------------------------------------------------
# 1. cube→sphere: all 8 corners at distance == radius
# ---------------------------------------------------------------------------

def test_sphere_all_vertices_on_surface():
    cage = _unit_cube_cage()
    projected, report = project_cage_to_sphere(cage, center=[0.0, 0.0, 0.0], radius=1.0)
    for v in projected.vertices:
        d = _dist(v, [0.0, 0.0, 0.0])
        assert abs(d - 1.0) < 1e-10, f"vertex {v} not on unit sphere: d={d}"


# ---------------------------------------------------------------------------
# 2. cube→sphere: max_projection_distance > 0
# ---------------------------------------------------------------------------

def test_sphere_report_nonzero_distance():
    cage = _unit_cube_cage()
    _, report = project_cage_to_sphere(cage, center=[0.0, 0.0, 0.0], radius=1.0)
    # unit cube corners are at sqrt(3) ≈ 1.732; projected to 1.0; displacement ≈ 0.732
    assert report.max_projection_distance > 0.5
    assert report.num_vertices == 8


# ---------------------------------------------------------------------------
# 3. sphere identity: vertices already on sphere → zero displacement
# ---------------------------------------------------------------------------

def test_sphere_identity():
    # Build cage already on unit sphere (normalize each vertex)
    verts = []
    h = 1.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                raw = [sx * h, sy * h, sz * h]
                mag = math.sqrt(sum(x ** 2 for x in raw))
                verts.append([x / mag for x in raw])
    faces = [
        [0, 1, 2, 3],
        [4, 7, 6, 5],
        [0, 4, 5, 1],
        [3, 2, 6, 7],
        [0, 3, 7, 4],
        [1, 5, 6, 2],
    ]
    cage = SubDCage(vertices=verts, faces=faces)
    projected, report = project_cage_to_sphere(cage, center=[0.0, 0.0, 0.0], radius=1.0)
    assert report.max_projection_distance < 1e-12


# ---------------------------------------------------------------------------
# 4. cube→cylinder (Z-axis, r=1): radial distance == radius
# ---------------------------------------------------------------------------

def test_cylinder_all_vertices_on_surface():
    cage = _unit_cube_cage()
    projected, report = project_cage_to_cylinder(
        cage,
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
        radius=1.0,
    )
    for v in projected.vertices:
        # radial distance = sqrt(x^2 + y^2)
        r = math.sqrt(v[0] ** 2 + v[1] ** 2)
        assert abs(r - 1.0) < 1e-10, f"vertex {v} not on unit cylinder: r={r}"


# ---------------------------------------------------------------------------
# 5. cylinder: Z-coordinates preserved
# ---------------------------------------------------------------------------

def test_cylinder_z_preserved():
    cage = _unit_cube_cage()
    projected, _ = project_cage_to_cylinder(
        cage,
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
        radius=1.0,
    )
    original_zs = sorted(set(v[2] for v in cage.vertices))
    projected_zs = sorted(set(round(v[2], 10) for v in projected.vertices))
    assert original_zs == pytest.approx(projected_zs, abs=1e-10)


# ---------------------------------------------------------------------------
# 6. cylinder identity: vertices already on cylinder → zero displacement
# ---------------------------------------------------------------------------

def test_cylinder_identity():
    # 8-vertex prism with all vertices at r=2 from Z-axis
    r = 2.0
    verts = []
    for angle in [0, math.pi / 2, math.pi, 3 * math.pi / 2]:
        verts.append([r * math.cos(angle), r * math.sin(angle), -1.0])
        verts.append([r * math.cos(angle), r * math.sin(angle), 1.0])
    faces = [[0, 2, 4, 6], [1, 7, 5, 3], [0, 1, 3, 2], [2, 3, 5, 4], [4, 5, 7, 6], [6, 7, 1, 0]]
    cage = SubDCage(vertices=verts, faces=faces)
    projected, report = project_cage_to_cylinder(
        cage,
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
        radius=r,
    )
    assert report.max_projection_distance < 1e-10


# ---------------------------------------------------------------------------
# 7. cage→plane (XY plane): all vertices at z == 0
# ---------------------------------------------------------------------------

def test_plane_all_vertices_on_plane():
    cage = _unit_cube_cage()
    projected, report = project_cage_to_plane(
        cage,
        origin=[0.0, 0.0, 0.0],
        normal=[0.0, 0.0, 1.0],
    )
    for v in projected.vertices:
        assert abs(v[2]) < 1e-12, f"vertex {v} not on XY plane"


# ---------------------------------------------------------------------------
# 8. plane: signed distance == 0 (both sides of plane)
# ---------------------------------------------------------------------------

def test_plane_both_sides():
    # cage with vertices above AND below z=0.5 plane
    verts = [
        [0.0, 0.0, 2.0],
        [1.0, 0.0, -1.0],
        [0.0, 1.0, 3.0],
    ]
    faces = [[0, 1, 2]]
    cage = SubDCage(vertices=verts, faces=faces)
    projected, _ = project_cage_to_plane(
        cage,
        origin=[0.0, 0.0, 0.5],
        normal=[0.0, 0.0, 1.0],
    )
    for v in projected.vertices:
        assert abs(v[2] - 0.5) < 1e-10


# ---------------------------------------------------------------------------
# 9. plane identity: vertices already on plane → zero displacement
# ---------------------------------------------------------------------------

def test_plane_identity():
    verts = [[0.0, 0.0, 0.5], [1.0, 0.0, 0.5], [0.0, 1.0, 0.5], [1.0, 1.0, 0.5]]
    faces = [[0, 1, 3, 2]]
    cage = SubDCage(vertices=verts, faces=faces)
    projected, report = project_cage_to_plane(
        cage,
        origin=[0.0, 0.0, 0.5],
        normal=[0.0, 0.0, 1.0],
    )
    assert report.max_projection_distance < 1e-12


# ---------------------------------------------------------------------------
# 10. ProjectionReport fields populated correctly
# ---------------------------------------------------------------------------

def test_report_fields():
    cage = _unit_cube_cage()
    _, report = project_cage_to_sphere(cage, center=[0.0, 0.0, 0.0], radius=1.0)
    assert isinstance(report, ProjectionReport)
    assert report.num_vertices == 8
    assert report.max_projection_distance >= report.mean_projection_distance > 0
    assert report.honest_flag is True
    assert len(report.honest_note) > 10


# ---------------------------------------------------------------------------
# 11. Re-export from geom/__init__.py
# ---------------------------------------------------------------------------

def test_geom_init_reexport():
    from kerf_cad_core.geom import (
        ProjectionReport,
        project_cage_to_cylinder,
        project_cage_to_plane,
        project_cage_to_sphere,
    )
    assert callable(project_cage_to_sphere)
    assert callable(project_cage_to_cylinder)
    assert callable(project_cage_to_plane)


# ---------------------------------------------------------------------------
# 12. Never-raise: empty cage
# ---------------------------------------------------------------------------

def test_empty_cage_no_raise():
    cage = SubDCage(vertices=[], faces=[])
    projected, report = project_cage_to_sphere(cage, [0, 0, 0], 1.0)
    assert projected.num_vertices == 0
    assert report.num_vertices == 0

    projected2, report2 = project_cage_to_cylinder(cage, [0, 0, 0], [0, 0, 1], 1.0)
    assert projected2.num_vertices == 0

    projected3, report3 = project_cage_to_plane(cage, [0, 0, 0], [0, 0, 1])
    assert projected3.num_vertices == 0


# ---------------------------------------------------------------------------
# 13. Degenerate zero-radius sphere clamped to 1e-9
# ---------------------------------------------------------------------------

def test_sphere_zero_radius_clamped():
    cage = _unit_cube_cage()
    # radius=0 should not crash; vertices should end up at distance 1e-9 from center
    projected, report = project_cage_to_sphere(cage, center=[0, 0, 0], radius=0.0)
    for v in projected.vertices:
        d = _dist(v, [0.0, 0.0, 0.0])
        assert abs(d - 1e-9) < 1e-15


# ---------------------------------------------------------------------------
# 14. Topology preserved: faces unchanged after projection
# ---------------------------------------------------------------------------

def test_faces_unchanged_after_projection():
    cage = _unit_cube_cage()
    projected, _ = project_cage_to_sphere(cage, [0, 0, 0], 2.0)
    assert projected.faces == cage.faces
    projected2, _ = project_cage_to_cylinder(cage, [0, 0, 0], [0, 0, 1], 2.0)
    assert projected2.faces == cage.faces
    projected3, _ = project_cage_to_plane(cage, [0, 0, 0], [0, 1, 0])
    assert projected3.faces == cage.faces


# ---------------------------------------------------------------------------
# 15. Cage independence: projecting doesn't mutate original cage
# ---------------------------------------------------------------------------

def test_original_cage_not_mutated():
    cage = _unit_cube_cage()
    orig_verts = [list(v) for v in cage.vertices]
    project_cage_to_sphere(cage, [0, 0, 0], 1.0)
    assert cage.vertices == orig_verts

    project_cage_to_cylinder(cage, [0, 0, 0], [0, 0, 1], 1.0)
    assert cage.vertices == orig_verts

    project_cage_to_plane(cage, [0, 0, 0], [0, 0, 1])
    assert cage.vertices == orig_verts
