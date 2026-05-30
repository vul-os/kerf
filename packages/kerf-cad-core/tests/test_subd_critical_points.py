"""
Tests for kerf_cad_core.geom.subd_critical_points — discrete Morse critical
points on Catmull-Clark SubD limit surfaces.

Oracle strategy (Edelsbrunner-Harer 2010 §1):

  1. Sphere (cube cage, height = z):
       f(x,y,z) = z.  Smooth sphere → exactly 1 maximum (north pole) +
       1 minimum (south pole) + 0 saddles.
       Morse-Euler: 1 − 0 + 1 = 2 = χ(sphere).

  2. Torus (toroidal cage, height = z):
       f(x,y,z) = z.  Standard Morse analysis of height on the torus:
       1 maximum + 1 minimum + 2 saddles.
       Morse-Euler: 1 − 2 + 1 = 0 = χ(torus).

  3. Flat plane (z = 0, height = z):
       f = const → degenerate Morse field; SoS still assigns extrema but
       no crash guaranteed.

  4. Tilted plane (monotone height): no interior critical points.

  5. Euler verification (sphere + torus): explicit formula check.

  6. CriticalPointsReport dataclass fields all present.

  7. Dict input accepted as cage.

  8. Custom scalar field (sphere with f=x: same topology).

  9. sample_density parameter accepted (no crash).

  10. Sphere poles are antipodal.

All tests are hermetic: no OCC, no database, no network.
"""

from __future__ import annotations

import math
from typing import List

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_critical_points import (
    CriticalPointsReport,
    find_critical_points,
)


# ---------------------------------------------------------------------------
# Cage fixtures
# ---------------------------------------------------------------------------

def _cube_cage() -> SubDMesh:
    """Unit cube control mesh centred at origin (sphere approximation)."""
    verts = [
        [-1.0, -1.0, -1.0],  # 0
        [ 1.0, -1.0, -1.0],  # 1
        [ 1.0,  1.0, -1.0],  # 2
        [-1.0,  1.0, -1.0],  # 3
        [-1.0, -1.0,  1.0],  # 4
        [ 1.0, -1.0,  1.0],  # 5
        [ 1.0,  1.0,  1.0],  # 6
        [-1.0,  1.0,  1.0],  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [2, 3, 7, 6],  # back
        [0, 3, 7, 4],  # left
        [1, 2, 6, 5],  # right
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _torus_cage(nu: int = 8, nv: int = 8) -> SubDMesh:
    """nu × nv quad grid wrapped toroidally — axis along Y (upright donut on its side).

    The torus is rotated 90° around the X-axis so that its axis is along Y and
    the height function z achieves its global maximum and minimum at single
    isolated points (generic / Morse function).

    R = 2.0 (major), r = 0.5 (minor).
    Max z ≈ R + r = 2.5  (outermost top).
    Min z ≈ -(R + r) = -2.5  (outermost bottom).
    Two saddle points at z ≈ ±(R - r) = ±1.5.
    """
    R, r = 2.0, 0.5

    def _rot_x_90(v: List[float]) -> List[float]:
        """Rotate 90° around X-axis: (x, y, z) → (x, -z, y)."""
        return [v[0], -v[2], v[1]]

    verts: List[List[float]] = []
    for i in range(nu):
        phi = 2 * math.pi * i / nu
        for j in range(nv):
            theta = 2 * math.pi * j / nv
            x = (R + r * math.cos(theta)) * math.cos(phi)
            y = (R + r * math.cos(theta)) * math.sin(phi)
            z = r * math.sin(theta)
            verts.append(_rot_x_90([x, y, z]))
    faces: List[List[int]] = []
    for i in range(nu):
        for j in range(nv):
            v0 = i * nv + j
            v1 = i * nv + (j + 1) % nv
            v2 = ((i + 1) % nu) * nv + (j + 1) % nv
            v3 = ((i + 1) % nu) * nv + j
            faces.append([v0, v1, v2, v3])
    return SubDMesh(vertices=verts, faces=faces)


def _flat_plane_cage(nx: int = 4, ny: int = 4) -> SubDMesh:
    """Flat plane at z=0 (all vertices share same height → degenerate Morse)."""
    verts: List[List[float]] = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            verts.append([float(i), float(j), 0.0])
    faces: List[List[int]] = []
    for j in range(ny):
        for i in range(nx):
            v00 = j * (nx + 1) + i
            v10 = v00 + 1
            v01 = v00 + (nx + 1)
            v11 = v01 + 1
            faces.append([v00, v10, v11, v01])
    mesh = SubDMesh(vertices=verts, faces=faces)
    # crease all boundary edges so shape stays flat
    nxv = nx + 1
    for i in range(nx):
        mesh.set_crease(i, i + 1, 1.0)
        mesh.set_crease(ny * nxv + i, ny * nxv + i + 1, 1.0)
    for j in range(ny):
        mesh.set_crease(j * nxv, (j + 1) * nxv, 1.0)
        mesh.set_crease(j * nxv + nx, (j + 1) * nxv + nx, 1.0)
    return mesh


def _tilted_plane_cage() -> SubDMesh:
    """2×2 quad plane tilted so z = x (skewed height function)."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 1.0],
        [2.0, 0.0, 2.0],
        [0.0, 1.0, 0.0],
        [1.0, 1.0, 1.0],
        [2.0, 1.0, 2.0],
        [0.0, 2.0, 0.0],
        [1.0, 2.0, 1.0],
        [2.0, 2.0, 2.0],
    ]
    faces = [
        [0, 1, 4, 3],
        [1, 2, 5, 4],
        [3, 4, 7, 6],
        [4, 5, 8, 7],
    ]
    mesh = SubDMesh(vertices=verts, faces=faces)
    # crease all boundary edges
    boundary_edges = [
        (0, 1), (1, 2),
        (6, 7), (7, 8),
        (0, 3), (3, 6),
        (2, 5), (5, 8),
    ]
    for (a, b) in boundary_edges:
        mesh.set_crease(a, b, 1.0)
    return mesh


# ---------------------------------------------------------------------------
# Test 1: Sphere height field — 1 max, 1 min, 0 saddles
# ---------------------------------------------------------------------------

def test_sphere_height_max_min_saddle_counts():
    """Sphere height: exactly 1 max (north pole) + 1 min (south pole) + 0 saddles.

    Edelsbrunner-Harer 2010 §1: height on S² has χ = 2 = #max − #sad + #min.
    """
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=4)
    assert rpt.n_maxima == 1, f"sphere height: expected 1 maximum, got {rpt.n_maxima}"
    assert rpt.n_minima == 1, f"sphere height: expected 1 minimum, got {rpt.n_minima}"
    assert rpt.n_saddles == 0, f"sphere height: expected 0 saddles, got {rpt.n_saddles}"


def test_sphere_euler_check():
    """Sphere: Morse-Euler #max − #sad + #min == χ == 2."""
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=4)
    assert rpt.euler_characteristic == 2, (
        f"sphere Euler characteristic should be 2, got {rpt.euler_characteristic}"
    )
    assert rpt.euler_check, (
        f"Morse-Euler check failed: {rpt.n_maxima} − {rpt.n_saddles} + {rpt.n_minima} "
        f"= {rpt.n_maxima - rpt.n_saddles + rpt.n_minima} ≠ {rpt.euler_characteristic}"
    )


def test_sphere_max_at_north_pole():
    """The single maximum should be near the top of the sphere (z > 0)."""
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=4)
    assert rpt.maxima, "no maxima found"
    z_max = rpt.maxima[0][2]
    assert z_max > 0.5, f"maximum z = {z_max:.3f}; expected > 0.5 (north-ish pole)"


def test_sphere_min_at_south_pole():
    """The single minimum should be near the bottom of the sphere (z < 0)."""
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=4)
    assert rpt.minima, "no minima found"
    z_min = rpt.minima[0][2]
    assert z_min < -0.5, f"minimum z = {z_min:.3f}; expected < −0.5 (south-ish pole)"


# ---------------------------------------------------------------------------
# Test 2: Torus height field — 1 max, 1 min, 2 saddles
# ---------------------------------------------------------------------------

def test_torus_height_critical_counts():
    """Torus height: 1 max + 1 min + 2 saddles.

    Standard Morse analysis (Edelsbrunner-Harer 2010 §1 torus example):
    height on the torus (major axis along z=const) yields exactly 4 critical
    points: 1 global max + 1 global min + 2 saddles.
    χ(torus) = 0 = 1 − 2 + 1.
    """
    cage = _torus_cage(nu=12, nv=12)
    rpt = find_critical_points(cage, sample_density=4)
    assert rpt.n_maxima == 1, f"torus height: expected 1 maximum, got {rpt.n_maxima}"
    assert rpt.n_minima == 1, f"torus height: expected 1 minimum, got {rpt.n_minima}"
    assert rpt.n_saddles == 2, f"torus height: expected 2 saddles, got {rpt.n_saddles}"


def test_torus_euler_check():
    """Torus: Morse-Euler #max − #sad + #min == χ == 0."""
    cage = _torus_cage(nu=12, nv=12)
    rpt = find_critical_points(cage, sample_density=4)
    assert rpt.euler_characteristic == 0, (
        f"torus Euler characteristic should be 0, got {rpt.euler_characteristic}"
    )
    assert rpt.euler_check, (
        f"Torus Morse-Euler check failed: {rpt.n_maxima} − {rpt.n_saddles} + "
        f"{rpt.n_minima} = {rpt.n_maxima - rpt.n_saddles + rpt.n_minima} ≠ 0"
    )


# ---------------------------------------------------------------------------
# Test 3: Flat plane (degenerate Morse field)
# ---------------------------------------------------------------------------

def test_flat_plane_no_crash():
    """Flat plane should not raise regardless of sample_density."""
    cage = _flat_plane_cage()
    for density in [1, 2, 3]:
        rpt = find_critical_points(cage, sample_density=density)
        assert isinstance(rpt, CriticalPointsReport)


def test_flat_plane_report_is_valid():
    """Flat plane: result is a valid CriticalPointsReport (no exceptions)."""
    cage = _flat_plane_cage()
    rpt = find_critical_points(cage, sample_density=2)
    # SoS tie-breaking ensures consistent (though arbitrary) classification
    assert rpt.n_maxima >= 0
    assert rpt.n_minima >= 0
    assert rpt.n_saddles >= 0


# ---------------------------------------------------------------------------
# Test 4: Tilted plane (no interior critical points)
# ---------------------------------------------------------------------------

def test_tilted_plane_no_interior_critical_points():
    """Strictly tilted plane: monotone height → no interior critical points."""
    cage = _tilted_plane_cage()
    rpt = find_critical_points(cage, sample_density=3)
    # Interior vertices of an open patch under monotone f have no extrema
    assert rpt.n_maxima == 0, f"tilted plane: unexpected maxima {rpt.n_maxima}"
    assert rpt.n_minima == 0, f"tilted plane: unexpected minima {rpt.n_minima}"
    assert rpt.n_saddles == 0, f"tilted plane: unexpected saddles {rpt.n_saddles}"


# ---------------------------------------------------------------------------
# Test 5: Euler verification (explicit formula check)
# ---------------------------------------------------------------------------

def test_euler_formula_sphere():
    """Sphere: #max − #sad + #min must equal euler_characteristic = 2."""
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=3)
    computed = rpt.n_maxima - rpt.n_saddles + rpt.n_minima
    assert computed == rpt.euler_characteristic, (
        f"Morse-Euler violation (sphere): {rpt.n_maxima} − {rpt.n_saddles} + {rpt.n_minima} "
        f"= {computed} ≠ χ = {rpt.euler_characteristic}"
    )


def test_euler_formula_torus():
    """Torus: #max − #sad + #min must equal euler_characteristic = 0."""
    cage = _torus_cage(nu=10, nv=10)
    rpt = find_critical_points(cage, sample_density=3)
    computed = rpt.n_maxima - rpt.n_saddles + rpt.n_minima
    assert computed == rpt.euler_characteristic, (
        f"Morse-Euler violation (torus): {rpt.n_maxima} − {rpt.n_saddles} + {rpt.n_minima} "
        f"= {computed} ≠ χ = {rpt.euler_characteristic}"
    )


# ---------------------------------------------------------------------------
# Test 6: Report dataclass has all expected fields
# ---------------------------------------------------------------------------

def test_report_fields_present():
    """CriticalPointsReport must have all documented fields."""
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=2)
    assert hasattr(rpt, "maxima")
    assert hasattr(rpt, "minima")
    assert hasattr(rpt, "saddles")
    assert hasattr(rpt, "n_maxima")
    assert hasattr(rpt, "n_minima")
    assert hasattr(rpt, "n_saddles")
    assert hasattr(rpt, "euler_characteristic")
    assert hasattr(rpt, "euler_check")
    assert hasattr(rpt, "degenerate_warning")
    assert isinstance(rpt.maxima, list)
    assert isinstance(rpt.minima, list)
    assert isinstance(rpt.saddles, list)
    assert isinstance(rpt.euler_check, bool)
    assert isinstance(rpt.degenerate_warning, str)


# ---------------------------------------------------------------------------
# Test 7: Dict input accepted
# ---------------------------------------------------------------------------

def test_dict_cage_input():
    """find_critical_points accepts a plain dict as cage."""
    cage = _cube_cage()
    cage_dict = {"vertices": cage.vertices, "faces": cage.faces}
    rpt = find_critical_points(cage_dict, sample_density=3)
    assert rpt.n_maxima == 1
    assert rpt.n_minima == 1
    assert rpt.euler_check


# ---------------------------------------------------------------------------
# Test 8: Custom scalar field
# ---------------------------------------------------------------------------

def test_custom_scalar_field_sphere_x():
    """Sphere with f = x: same topology as f = z (1 max, 1 min, 0 saddles, χ=2)."""
    cage = _cube_cage()
    rpt = find_critical_points(
        cage,
        scalar_field=lambda xyz: float(xyz[0]),
        sample_density=4,
    )
    assert rpt.n_maxima == 1
    assert rpt.n_minima == 1
    assert rpt.n_saddles == 0
    assert rpt.euler_check


# ---------------------------------------------------------------------------
# Test 9: sample_density parameter accepted (no crash at boundaries)
# ---------------------------------------------------------------------------

def test_sample_density_clamp_no_crash():
    """sample_density 1 and 6 should run without error."""
    cage = _cube_cage()
    rpt1 = find_critical_points(cage, sample_density=1)
    assert isinstance(rpt1, CriticalPointsReport)
    rpt6 = find_critical_points(cage, sample_density=6)
    assert isinstance(rpt6, CriticalPointsReport)
    assert rpt6.euler_check  # sphere should still pass at fine density


# ---------------------------------------------------------------------------
# Test 10: Sphere critical point positions are on opposing ends of z-axis
# ---------------------------------------------------------------------------

def test_sphere_poles_are_antipodal():
    """Max and min of height on the sphere should be near antipodal (z_max ≈ −z_min)."""
    cage = _cube_cage()
    rpt = find_critical_points(cage, sample_density=5)
    z_max = rpt.maxima[0][2]
    z_min = rpt.minima[0][2]
    assert z_max > 0, f"max z should be positive (north), got {z_max}"
    assert z_min < 0, f"min z should be negative (south), got {z_min}"
    # |z_max + z_min| should be small relative to |z_max|
    symmetry_err = abs(z_max + z_min) / max(abs(z_max), 0.01)
    assert symmetry_err < 0.3, f"sphere not symmetric: z_max={z_max:.3f} z_min={z_min:.3f}"
