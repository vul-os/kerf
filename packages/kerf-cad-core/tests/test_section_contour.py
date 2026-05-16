"""
tests/test_section_contour.py
==============================
Hermetic tests for kerf_cad_core.geom.section_contour.

Tests cover:
  - section_by_plane on triangle meshes (cube, sphere)
  - contour on cylinder meshes
  - silhouette on sphere mesh
  - isoline on NURBS surfaces
  - edge / error cases (bad inputs never raise)
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.section_contour import (
    contour,
    isoline,
    polyline_length,
    section_by_plane,
    silhouette,
)
from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Mesh factories
# ---------------------------------------------------------------------------

def make_cube_mesh(side: float = 2.0) -> Tuple[List, List]:
    """Return a closed, triangulated unit cube mesh centred at origin."""
    h = side / 2.0
    verts = [
        [-h, -h, -h],  # 0
        [+h, -h, -h],  # 1
        [+h, +h, -h],  # 2
        [-h, +h, -h],  # 3
        [-h, -h, +h],  # 4
        [+h, -h, +h],  # 5
        [+h, +h, +h],  # 6
        [-h, +h, +h],  # 7
    ]
    faces = [
        # bottom z = -h
        [0, 2, 1], [0, 3, 2],
        # top z = +h
        [4, 5, 6], [4, 6, 7],
        # front y = -h
        [0, 1, 5], [0, 5, 4],
        # back y = +h
        [2, 3, 7], [2, 7, 6],
        # left x = -h
        [0, 4, 7], [0, 7, 3],
        # right x = +h
        [1, 2, 6], [1, 6, 5],
    ]
    return verts, faces


def make_sphere_mesh(radius: float = 1.0, nlat: int = 30, nlon: int = 60) -> Tuple[List, List]:
    """Return a triangulated UV-sphere mesh."""
    verts = []
    faces = []

    for i in range(nlat + 1):
        lat = math.pi * (i / nlat - 0.5)
        for j in range(nlon):
            lon = 2.0 * math.pi * j / nlon
            x = radius * math.cos(lat) * math.cos(lon)
            y = radius * math.cos(lat) * math.sin(lon)
            z = radius * math.sin(lat)
            verts.append([x, y, z])

    for i in range(nlat):
        for j in range(nlon):
            a = i * nlon + j
            b = i * nlon + (j + 1) % nlon
            c = (i + 1) * nlon + (j + 1) % nlon
            d = (i + 1) * nlon + j
            faces.append([a, b, c])
            faces.append([a, c, d])

    return verts, faces


def make_cylinder_mesh(
    radius: float = 1.0, height: float = 4.0, ncirc: int = 40, nz: int = 20
) -> Tuple[List, List]:
    """Return a triangulated open-ended cylinder mesh."""
    verts = []
    faces = []

    for iz in range(nz + 1):
        z = height * (iz / nz)
        for ic in range(ncirc):
            angle = 2.0 * math.pi * ic / ncirc
            verts.append([radius * math.cos(angle), radius * math.sin(angle), z])

    for iz in range(nz):
        for ic in range(ncirc):
            a = iz * ncirc + ic
            b = iz * ncirc + (ic + 1) % ncirc
            c = (iz + 1) * ncirc + (ic + 1) % ncirc
            d = (iz + 1) * ncirc + ic
            faces.append([a, b, c])
            faces.append([a, c, d])

    return verts, faces


# ---------------------------------------------------------------------------
# NURBS surface factory (bilinear quad)
# ---------------------------------------------------------------------------

def make_flat_nurbs(size: float = 2.0) -> NurbsSurface:
    """Flat z=0 bilinear NURBS patch in [-size/2, +size/2]^2."""
    h = size / 2.0
    cp = np.array([
        [[-h, -h, 0.0], [+h, -h, 0.0]],
        [[-h, +h, 0.0], [+h, +h, 0.0]],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
    )


def make_sphere_nurbs(radius: float = 1.0, nu: int = 10, nv: int = 10) -> NurbsSurface:
    """Approximate sphere as a degree-1 NURBS via UV sampling — good enough for tests."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        lat = math.pi * (i / (nu - 1) - 0.5)
        for j in range(nv):
            lon = 2.0 * math.pi * j / (nv - 1)
            cp[i, j] = [
                radius * math.cos(lat) * math.cos(lon),
                radius * math.cos(lat) * math.sin(lon),
                radius * math.sin(lat),
            ]

    def clamped_knots(n: int, degree: int) -> np.ndarray:
        inner = max(0, n - degree - 1)
        return np.concatenate([
            np.zeros(degree + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else [],
            np.ones(degree + 1),
        ])

    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=clamped_knots(nu, 1),
        knots_v=clamped_knots(nv, 1),
    )


# ---------------------------------------------------------------------------
# section_by_plane — mesh tests
# ---------------------------------------------------------------------------

class TestSectionByPlaneMesh:

    def test_cube_horizontal_cut_returns_ok(self):
        verts, faces = make_cube_mesh(side=2.0)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 0.0})
        assert result["ok"] is True

    def test_cube_horizontal_cut_produces_one_loop(self):
        verts, faces = make_cube_mesh(side=2.0)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 0.0})
        assert result["loop_count"] >= 1

    def test_cube_horizontal_cut_loop_has_four_vertices(self):
        side = 2.0
        verts, faces = make_cube_mesh(side=side)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 0.0})
        # The square at z=0 should have 4 corner points (or 5 if the loop is closed)
        loop = result["loops"][0]
        assert len(loop) >= 4

    def test_cube_horizontal_cut_perimeter(self):
        side = 2.0
        verts, faces = make_cube_mesh(side=side)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 0.0})
        loop = result["loops"][0]
        L = polyline_length(loop)
        # perimeter = 4 * side = 8.0; allow 5% tolerance
        assert abs(L - 4.0 * side) < 0.05 * 4.0 * side, f"perimeter {L} far from expected {4*side}"

    def test_cube_off_centre_cut(self):
        side = 4.0
        verts, faces = make_cube_mesh(side=side)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 1.0})
        assert result["ok"] is True
        assert result["loop_count"] >= 1

    def test_cube_diagonal_cut_ok(self):
        verts, faces = make_cube_mesh(side=2.0)
        n = [1.0, 1.0, 0.0]
        result = section_by_plane((verts, faces), {"normal": n, "d": 0.0})
        assert result["ok"] is True

    def test_cube_cut_above_returns_no_loops(self):
        verts, faces = make_cube_mesh(side=2.0)
        # plane above the cube
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 5.0})
        assert result["ok"] is True
        assert result["loop_count"] == 0

    def test_sphere_equatorial_cut_ok(self):
        verts, faces = make_sphere_mesh(radius=1.0)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 0.0})
        assert result["ok"] is True
        assert result["loop_count"] >= 1

    def test_sphere_equatorial_cut_radius(self):
        """Equatorial section of a unit sphere should be a circle of radius ~1."""
        r = 1.0
        verts, faces = make_sphere_mesh(radius=r, nlat=40, nlon=80)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": 0.0})
        assert result["ok"]
        loop = result["loops"][0]
        # The loop should approximate a circle with circumference ~2πr
        L = polyline_length(loop)
        expected_circ = 2.0 * math.pi * r
        # tessellation tolerance ~ edge length ~ 2*pi*r / nlon ≈ 0.08
        assert abs(L - expected_circ) < 0.15 * expected_circ, (
            f"circumference {L:.4f} far from expected {expected_circ:.4f}"
        )

    def test_sphere_off_equator_cut_smaller_circle(self):
        r = 1.0
        z_cut = 0.5
        verts, faces = make_sphere_mesh(radius=r, nlat=40, nlon=80)
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "d": z_cut})
        assert result["ok"]
        assert result["loop_count"] >= 1
        loop = result["loops"][0]
        L = polyline_length(loop)
        expected_r = math.sqrt(r * r - z_cut * z_cut)
        expected_circ = 2.0 * math.pi * expected_r
        assert abs(L - expected_circ) < 0.2 * expected_circ

    def test_plane_normal_is_unit_in_result(self):
        verts, faces = make_cube_mesh()
        result = section_by_plane((verts, faces), {"normal": [0, 0, 3], "d": 0.0})
        n = result["plane_normal"]
        assert abs(math.sqrt(n[0]**2 + n[1]**2 + n[2]**2) - 1.0) < 1e-9

    def test_dict_mesh_input(self):
        verts, faces = make_cube_mesh()
        result = section_by_plane({"verts": verts, "faces": faces}, {"normal": [0, 0, 1], "d": 0.0})
        assert result["ok"] is True

    def test_plane_as_tuple(self):
        verts, faces = make_cube_mesh()
        result = section_by_plane((verts, faces), ([0, 0, 1], 0.0))
        assert result["ok"] is True

    def test_plane_with_point(self):
        verts, faces = make_cube_mesh()
        result = section_by_plane((verts, faces), {"normal": [0, 0, 1], "point": [0, 0, 0]})
        assert result["ok"] is True
        assert result["loop_count"] >= 1

    def test_bad_plane_zero_normal(self):
        verts, faces = make_cube_mesh()
        result = section_by_plane((verts, faces), {"normal": [0, 0, 0], "d": 0.0})
        assert result["ok"] is False
        assert "reason" in result

    def test_empty_mesh(self):
        result = section_by_plane(([], []), {"normal": [0, 0, 1], "d": 0.0})
        assert result["ok"] is True
        assert result["loop_count"] == 0


# ---------------------------------------------------------------------------
# section_by_plane — surface tests
# ---------------------------------------------------------------------------

class TestSectionByPlaneSurface:

    def test_flat_surface_horizontal_cut(self):
        surf = make_flat_nurbs(size=4.0)
        # plane z = 0 should intersect the flat z=0 surface everywhere
        result = section_by_plane(surf, {"normal": [0, 0, 1], "d": 0.0})
        assert result["ok"] is True

    def test_flat_surface_above_cut_no_loops(self):
        surf = make_flat_nurbs(size=4.0)
        result = section_by_plane(surf, {"normal": [0, 0, 1], "d": 1.0})
        assert result["ok"] is True
        # No intersection (surface lies at z=0, plane at z=1)
        assert result["loop_count"] == 0


# ---------------------------------------------------------------------------
# contour tests
# ---------------------------------------------------------------------------

class TestContour:

    def test_cylinder_contour_ok(self):
        verts, faces = make_cylinder_mesh(radius=1.0, height=4.0, ncirc=40, nz=20)
        result = contour((verts, faces), axis_dir=[0, 0, 1], spacing=1.0)
        assert result["ok"] is True

    def test_cylinder_contour_level_count(self):
        verts, faces = make_cylinder_mesh(radius=1.0, height=4.0, ncirc=40, nz=20)
        result = contour((verts, faces), axis_dir=[0, 0, 1], spacing=1.0)
        # Height=4, spacing=1 → 5 levels (0, 1, 2, 3, 4)
        assert result["level_count"] >= 4

    def test_cylinder_contour_sections_structure(self):
        verts, faces = make_cylinder_mesh(radius=1.0, height=4.0, ncirc=40, nz=20)
        result = contour((verts, faces), axis_dir=[0, 0, 1], spacing=1.0)
        for sec in result["sections"]:
            assert "level_index" in sec
            assert "value" in sec
            assert "loops" in sec

    def test_cylinder_contour_equal_loop_lengths(self):
        """All interior cross-sections of a cylinder should have the same circumference."""
        r = 1.0
        verts, faces = make_cylinder_mesh(radius=r, height=6.0, ncirc=60, nz=30)
        result = contour((verts, faces), axis_dir=[0, 0, 1], spacing=1.0)
        assert result["ok"]
        interior_lengths = []
        for sec in result["sections"]:
            if sec["loops"]:
                L = polyline_length(sec["loops"][0])
                if L > 0.1:
                    interior_lengths.append(L)
        # All loop lengths should be within 15% of each other
        if len(interior_lengths) >= 2:
            min_L = min(interior_lengths)
            max_L = max(interior_lengths)
            assert (max_L - min_L) / min_L < 0.15, (
                f"loop lengths vary too much: min={min_L:.3f}, max={max_L:.3f}"
            )

    def test_contour_with_origin(self):
        verts, faces = make_cube_mesh(side=2.0)
        result = contour((verts, faces), [0, 0, 1], 0.5, origin=[0, 0, -1.0])
        assert result["ok"] is True

    def test_contour_zero_spacing_error(self):
        verts, faces = make_cube_mesh()
        result = contour((verts, faces), [0, 0, 1], 0.0)
        assert result["ok"] is False

    def test_contour_zero_axis_error(self):
        verts, faces = make_cube_mesh()
        result = contour((verts, faces), [0, 0, 0], 1.0)
        assert result["ok"] is False

    def test_contour_diagonal_axis(self):
        verts, faces = make_cube_mesh(side=2.0)
        result = contour((verts, faces), [1, 0, 0], 0.5)
        assert result["ok"] is True
        assert result["level_count"] >= 3


# ---------------------------------------------------------------------------
# silhouette tests
# ---------------------------------------------------------------------------

class TestSilhouette:

    def test_sphere_silhouette_from_front_ok(self):
        verts, faces = make_sphere_mesh(radius=1.0, nlat=20, nlon=40)
        result = silhouette((verts, faces), view_dir=[0, 0, 1])
        assert result["ok"] is True

    def test_sphere_silhouette_has_edges(self):
        verts, faces = make_sphere_mesh(radius=1.0, nlat=20, nlon=40)
        result = silhouette((verts, faces), view_dir=[0, 0, 1])
        assert result["edge_count"] > 0

    def test_sphere_silhouette_from_front_forms_great_circle(self):
        """Silhouette of a sphere viewed along +Z should approximate equator."""
        r = 1.0
        verts, faces = make_sphere_mesh(radius=r, nlat=30, nlon=60)
        result = silhouette((verts, faces), view_dir=[0, 0, 1])
        assert result["ok"]
        # All silhouette points should have z ≈ 0 (within mesh tessellation tolerance)
        all_pts = []
        for chain in result["chains"]:
            all_pts.extend(chain)
        if all_pts:
            zvals = [abs(p[2]) for p in all_pts]
            mean_z = sum(zvals) / len(zvals)
            # tessellation tolerance ~ r * pi / nlat ≈ 0.1 for nlat=30
            assert mean_z < 0.25 * r, f"mean |z| of silhouette = {mean_z:.4f}, expected ≈ 0"

    def test_sphere_silhouette_from_side(self):
        verts, faces = make_sphere_mesh(radius=1.0, nlat=20, nlon=40)
        result = silhouette((verts, faces), view_dir=[1, 0, 0])
        assert result["ok"] is True
        assert result["edge_count"] > 0

    def test_silhouette_zero_view_error(self):
        verts, faces = make_sphere_mesh()
        result = silhouette((verts, faces), view_dir=[0, 0, 0])
        assert result["ok"] is False

    def test_silhouette_empty_mesh(self):
        result = silhouette(([], []), [0, 0, 1])
        assert result["ok"] is True
        assert result["edge_count"] == 0

    def test_silhouette_cube_from_front(self):
        verts, faces = make_cube_mesh(side=2.0)
        result = silhouette((verts, faces), view_dir=[0, 0, 1])
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# isoline tests
# ---------------------------------------------------------------------------

class TestIsoline:

    def test_isoline_u_flat_surface(self):
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "u", 0.5)
        assert result["ok"] is True
        assert len(result["points"]) >= 2

    def test_isoline_v_flat_surface(self):
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "v", 0.5)
        assert result["ok"] is True

    def test_isoline_returns_correct_direction(self):
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "u", 0.5)
        assert result["parameter_direction"] == "u"
        assert abs(result["parameter_value"] - 0.5) < 1e-9

    def test_isoline_z_zero_on_flat_surface(self):
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "u", 0.5)
        for pt in result["points"]:
            assert abs(pt[2]) < 1e-6, f"z={pt[2]} not near 0 on flat surface"

    def test_isoline_num_samples(self):
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "v", 0.3, num_samples=20)
        assert len(result["points"]) == 20

    def test_isoline_bad_direction(self):
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "w", 0.5)
        assert result["ok"] is False

    def test_isoline_clamps_value(self):
        """Values outside [0,1] should be clamped, not error."""
        surf = make_flat_nurbs(size=4.0)
        result = isoline(surf, "u", 5.0)
        assert result["ok"] is True

    def test_isoline_not_surface_type(self):
        result = isoline("not_a_surface", "u", 0.5)  # type: ignore[arg-type]
        assert result["ok"] is False

    def test_isoline_sphere_u_constant_latitude(self):
        """On an approximate sphere NURBS, u=0.5 isoline should have constant latitude."""
        surf = make_sphere_nurbs(radius=1.0, nu=10, nv=10)
        result = isoline(surf, "u", 0.5, num_samples=30)
        assert result["ok"]
        zvals = [p[2] for p in result["points"]]
        # All z should be roughly constant along the latitude line
        z_range = max(zvals) - min(zvals)
        assert z_range < 0.4, f"z_range={z_range:.4f} too large for constant-u isoline"


# ---------------------------------------------------------------------------
# polyline_length tests
# ---------------------------------------------------------------------------

class TestPolylineLength:

    def test_straight_line(self):
        pts = [[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]]
        assert abs(polyline_length(pts) - 3.0) < 1e-9

    def test_empty(self):
        assert polyline_length([]) == 0.0

    def test_single_point(self):
        assert polyline_length([[1, 2, 3]]) == 0.0

    def test_unit_square(self):
        pts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]]
        assert abs(polyline_length(pts) - 4.0) < 1e-9
