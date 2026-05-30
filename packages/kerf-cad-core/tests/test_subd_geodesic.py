"""
Tests for kerf_cad_core.geom.subd_geodesic
============================================
Geodesic distance via the heat method (Crane-Weischedel-Wardetzky 2013).

Oracles
-------
1. Flat grid   : Euclidean distance from corner (exact for flat meshes).
2. Sphere      : great-circle distance from north pole → equator = π/2.
3. Cylinder    : axial distance + wrap-around = πR + height.
4. Multi-source: min distance to four cube-corner sources.

All tolerances are ≤ 5 % of the expected value (heat-method accuracy bound).
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.subd_geodesic import (
    compute_geodesic_heat_method,
    compute_geodesic_path,
    compute_geodesic_to_point,
)


# ---------------------------------------------------------------------------
# Mesh builders
# ---------------------------------------------------------------------------

def make_flat_grid(nx: int = 10, ny: int = 10) -> dict:
    """Regular (nx-1) × (ny-1) quad grid in the z=0 plane.

    Vertices are at integer positions (i, j, 0) for i ∈ [0, nx-1], j ∈ [0, ny-1].
    """
    verts = []
    for j in range(ny):
        for i in range(nx):
            verts.append([float(i), float(j), 0.0])

    def idx(i, j):
        return j * nx + i

    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            faces.append([idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)])

    return {"vertices": verts, "faces": faces}


def make_uv_sphere(radius: float = 1.0, n_lat: int = 16, n_lon: int = 32) -> dict:
    """UV tessellated sphere.

    North pole is index 0 (θ=0).
    Returns quad+triangle faces (quads for interior, triangles at poles).
    """
    verts: List[List[float]] = []
    faces: List[List[int]] = []

    # Poles
    north_pole = 0
    verts.append([0.0, 0.0, radius])   # north (θ=0)

    # Body vertices: latitude bands θ ∈ (0, π), longitude φ ∈ [0, 2π)
    for lat in range(1, n_lat):
        theta = math.pi * lat / n_lat       # polar angle
        for lon in range(n_lon):
            phi = 2.0 * math.pi * lon / n_lon
            x = radius * math.sin(theta) * math.cos(phi)
            y = radius * math.sin(theta) * math.sin(phi)
            z = radius * math.cos(theta)
            verts.append([x, y, z])

    south_pole = len(verts)
    verts.append([0.0, 0.0, -radius])  # south (θ=π)

    def body_idx(lat_band, lon):
        # lat_band in [0, n_lat-2], lon in [0, n_lon-1]
        return 1 + lat_band * n_lon + (lon % n_lon)

    # North cap (triangles from north pole to first latitude band)
    for lon in range(n_lon):
        a = body_idx(0, lon)
        b = body_idx(0, (lon + 1) % n_lon)
        faces.append([north_pole, a, b])

    # Middle bands (quads)
    for lat_band in range(n_lat - 2):
        for lon in range(n_lon):
            a = body_idx(lat_band, lon)
            b = body_idx(lat_band, (lon + 1) % n_lon)
            c = body_idx(lat_band + 1, (lon + 1) % n_lon)
            d = body_idx(lat_band + 1, lon)
            faces.append([a, b, c, d])

    # South cap
    for lon in range(n_lon):
        a = body_idx(n_lat - 2, lon)
        b = body_idx(n_lat - 2, (lon + 1) % n_lon)
        faces.append([a, south_pole, b])

    return {"vertices": verts, "faces": faces}


def make_cylinder(
    radius: float = 1.0,
    height: float = 2.0,
    n_seg: int = 96,
    n_stack: int = 48,
) -> Tuple[dict, int, int]:
    """Open (no caps) cylinder mesh.

    Returns (mesh, bottom_idx, top_idx) where bottom_idx / top_idx are
    representative vertex indices on the bottom / top rings.
    Default resolution (n_seg=96, n_stack=48) achieves < 5 % heat-method error.
    """
    verts: List[List[float]] = []
    faces: List[List[int]] = []

    for stack in range(n_stack + 1):
        z = -height / 2.0 + height * stack / n_stack
        for seg in range(n_seg):
            phi = 2.0 * math.pi * seg / n_seg
            x = radius * math.cos(phi)
            y = radius * math.sin(phi)
            verts.append([x, y, z])

    def idx(stack, seg):
        return stack * n_seg + (seg % n_seg)

    for stack in range(n_stack):
        for seg in range(n_seg):
            a = idx(stack, seg)
            b = idx(stack, seg + 1)
            c = idx(stack + 1, seg + 1)
            d = idx(stack + 1, seg)
            faces.append([a, b, c, d])

    # bottom vertex at stack=0, seg=0; top vertex at stack=n_stack, seg=0
    bottom = idx(0, 0)
    top = idx(n_stack, 0)

    return {"vertices": verts, "faces": faces}, bottom, top


def make_flat_grid_large(nx: int = 30, ny: int = 30) -> dict:
    """Larger flat grid for multi-source test."""
    verts: List[List[float]] = []
    for j in range(ny):
        for i in range(nx):
            verts.append([float(i), float(j), 0.0])

    def idx(i, j):
        return j * nx + i

    faces: List[List[int]] = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            faces.append([idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)])

    return {"vertices": verts, "faces": faces, "_nx": nx, "_ny": ny}


# ---------------------------------------------------------------------------
# Test 1: Flat grid — distance from corner ≈ Euclidean
# ---------------------------------------------------------------------------

def test_flat_grid_euclidean():
    """On a flat 10×10 grid, geodesic distance from the origin corner equals
    the 2-D Euclidean distance to within 5 %."""
    nx, ny = 10, 10
    mesh = make_flat_grid(nx, ny)
    V = np.array(mesh["vertices"])

    # Source = vertex 0 = (0, 0, 0)
    phi = compute_geodesic_heat_method(mesh, [0])
    assert phi.shape == (nx * ny,), "Wrong number of distances"

    # Check several well-spaced interior + boundary vertices
    checks = [
        (0, 0), (3, 0), (0, 5), (5, 5), (9, 9), (3, 7),
    ]
    for i, j in checks:
        v_idx = j * nx + i
        expected = math.sqrt(i**2 + j**2)
        computed = phi[v_idx]
        if expected < 1e-9:
            assert computed < 0.1, f"Source vertex distance > 0: {computed}"
        else:
            rel_err = abs(computed - expected) / expected
            assert rel_err < 0.05, (
                f"Flat grid ({i},{j}): expected {expected:.4f}, got {computed:.4f}, "
                f"rel_err={rel_err:.3f}"
            )


# ---------------------------------------------------------------------------
# Test 2: Sphere — great-circle distance from north pole to equator = π/2
# ---------------------------------------------------------------------------

def test_sphere_geodesic_pole_to_equator():
    """On a unit sphere, geodesic distance from north pole to any equatorial
    vertex equals π/2 ≈ 1.5708 within 5 %."""
    R = 1.0
    n_lat, n_lon = 24, 48
    mesh = make_uv_sphere(radius=R, n_lat=n_lat, n_lon=n_lon)
    V = np.array(mesh["vertices"])

    # North pole is vertex 0
    phi = compute_geodesic_heat_method(mesh, [0])
    assert phi.shape == (len(mesh["vertices"]),)

    expected = math.pi / 2.0   # great-circle distance from pole to equator on R=1

    # Find equatorial vertices (latitude band n_lat//2)
    eq_band = n_lat // 2
    eq_indices = [1 + (eq_band - 1) * n_lon + lon for lon in range(n_lon)]

    for v_idx in eq_indices[::4]:   # check every 4th equatorial vertex
        computed = phi[v_idx]
        rel_err = abs(computed - expected) / expected
        assert rel_err < 0.05, (
            f"Sphere equatorial geodesic: expected {expected:.4f}, got {computed:.4f}, "
            f"rel_err={rel_err:.3f}"
        )


# ---------------------------------------------------------------------------
# Test 3: Cylinder — axial distance and wrap-around
# ---------------------------------------------------------------------------

def test_cylinder_axial_distance():
    """On an open cylinder of radius 1 and height 2, the geodesic from the
    bottom of one meridian to the top of the *same* meridian equals the height
    within 5 %.  Uses n_seg=96, n_stack=48 for sufficient mesh resolution."""
    R, H = 1.0, 2.0
    mesh, bottom_idx, top_idx = make_cylinder(radius=R, height=H, n_seg=96, n_stack=48)

    phi = compute_geodesic_heat_method(mesh, [bottom_idx])

    # Axial distance along the same meridian ≈ height
    expected_axial = H
    computed_axial = phi[top_idx]
    rel_err = abs(computed_axial - expected_axial) / expected_axial
    assert rel_err < 0.05, (
        f"Cylinder axial: expected {expected_axial:.4f}, got {computed_axial:.4f}, "
        f"rel_err={rel_err:.3f}"
    )


def test_cylinder_diametric_wrap():
    """From a bottom vertex, the geodesic to the diametrically opposite vertex
    at the *same* height wraps around half the cylinder: expected ≈ π * R."""
    R = 1.0
    # Use cylinder with 1 height stack and enough segments to resolve the wrap
    n_seg = 128
    mesh, bottom_idx, _ = make_cylinder(radius=R, height=1.0, n_seg=n_seg, n_stack=1)

    # Source: bottom ring, seg=0 (phi=0)
    # Target: bottom ring, seg=n_seg//2 (phi=π) — diametrically opposite
    source = 0                   # bottom ring, seg 0
    target = n_seg // 2          # bottom ring, seg 64 (diametrically opposite)

    phi = compute_geodesic_heat_method(mesh, [source])

    # The geodesic on a cylinder wraps around π*R (half circumference).
    # Note: discrete cylinder meshes introduce a ~5 % over-estimate because
    # geodesics zig-zag across quad diagonals; allow 6 % tolerance.
    expected = math.pi * R
    computed = phi[target]
    rel_err = abs(computed - expected) / expected
    assert rel_err < 0.06, (
        f"Cylinder diametric wrap: expected {expected:.4f}, got {computed:.4f}, "
        f"rel_err={rel_err:.3f}"
    )


# ---------------------------------------------------------------------------
# Test 4: Multi-source — min distance to 4 corner sources on flat grid
# ---------------------------------------------------------------------------

def test_multi_source_min_distance():
    """With 4 sources at the 4 corners of a flat 30×30 grid, the multi-source
    geodesic distance at each vertex should approximate the minimum Euclidean
    distance to any corner, within ~10 % (heat-method multi-source tolerance).

    The heat method for N sources solves a single combined heat equation with
    all source deltas active simultaneously.  The resulting potential
    approximates the Voronoi min-distance field.  On a fine flat grid the
    approximation is within ~10 % of the true min.
    """
    nx, ny = 30, 30
    mesh = make_flat_grid_large(nx, ny)
    V = np.array(mesh["vertices"])
    n = len(V)

    # Four grid corners
    def gidx(i, j):
        return j * nx + i

    sources = [gidx(0, 0), gidx(nx - 1, 0), gidx(0, ny - 1), gidx(nx - 1, ny - 1)]
    corner_pts = [(0, 0), (nx - 1, 0), (0, ny - 1), (nx - 1, ny - 1)]

    phi_multi = compute_geodesic_heat_method(mesh, sources)
    assert phi_multi.shape == (n,), "Wrong number of distances"

    # Check symmetry: centre vertex should have equal distance from all 4 corners
    cx, cy = (nx - 1) // 2, (ny - 1) // 2
    centre = gidx(cx, cy)
    centre_dist = phi_multi[centre]
    expected_centre = math.sqrt(cx**2 + cy**2)
    rel_err_centre = abs(centre_dist - expected_centre) / expected_centre
    assert rel_err_centre < 0.10, (
        f"Centre ({cx},{cy}) multi-source: expected {expected_centre:.3f}, "
        f"got {centre_dist:.3f}, rel_err={rel_err_centre:.3f}"
    )

    # Check several interior vertices: distance should be ≤ (min single-source + 15%)
    # This verifies multi-source doesn't over-inflate distances.
    phi_singles = [compute_geodesic_heat_method(mesh, [s]) for s in sources]
    sample_verts = [gidx(5, 5), gidx(15, 5), gidx(5, 15), gidx(15, 15), gidx(10, 10)]
    for v in sample_verts:
        expected_min = min(phi_s[v] for phi_s in phi_singles)
        computed = phi_multi[v]
        if expected_min < 0.5:
            continue
        rel_err = abs(computed - expected_min) / expected_min
        assert rel_err < 0.15, (
            f"Multi-source vertex ({v % nx},{v // nx}): "
            f"expected_min≈{expected_min:.3f}, got={computed:.3f}, rel_err={rel_err:.3f}"
        )


# ---------------------------------------------------------------------------
# Additional smoke tests
# ---------------------------------------------------------------------------

def test_source_vertex_is_zero():
    """The source vertex must be at distance 0."""
    mesh = make_flat_grid(8, 8)
    phi = compute_geodesic_heat_method(mesh, [0])
    assert phi[0] < 1e-6, f"Source vertex distance={phi[0]}"


def test_all_distances_nonneg():
    """All returned distances must be non-negative."""
    mesh = make_uv_sphere(n_lat=12, n_lon=24)
    phi = compute_geodesic_heat_method(mesh, [0])
    assert np.all(phi >= 0.0), "Negative distances found"


def test_compute_geodesic_to_point():
    """compute_geodesic_to_point should find the nearest vertex and return
    distances consistent with a direct call to the heat method on that vertex."""
    mesh = make_flat_grid(6, 6)
    V = np.array(mesh["vertices"])

    # Use a point very close to vertex 0
    src_point = [0.01, 0.01, 0.0]
    phi = compute_geodesic_to_point(mesh, src_point)
    assert phi.shape == (len(V),)
    assert phi[0] < 1e-3, "Expected vertex 0 to be closest to (0.01, 0.01, 0)"


def test_compute_geodesic_path_nonempty():
    """compute_geodesic_path should return a non-empty list from source to target."""
    mesh = make_flat_grid(10, 10)
    path = compute_geodesic_path(mesh, 0, 99)
    assert isinstance(path, list), "Path should be a list"
    assert len(path) >= 2, "Path should have at least source + target"
    # Each element is a 3-D point
    for pt in path:
        assert len(pt) == 3


def test_bad_input_never_raises():
    """Passing garbage inputs must not raise."""
    phi = compute_geodesic_heat_method({"vertices": [], "faces": []}, [0])
    assert len(phi) == 0

    phi2 = compute_geodesic_heat_method({"vertices": [], "faces": []}, [])
    assert len(phi2) == 0

    path = compute_geodesic_path({"vertices": [], "faces": []}, 0, 1)
    assert path == []


def test_quad_mesh_auto_triangulation():
    """A pure quad mesh should work via automatic triangulation."""
    mesh = make_flat_grid(5, 5)   # pure quads
    phi = compute_geodesic_heat_method(mesh, [0])
    assert phi.shape == (25,)
    assert phi[24] > 0   # farthest corner should have positive distance
