"""Tests for geom/face_centroid.py — BREP-FACE-AREA-WEIGHTED-CENTROID.

Oracles
-------
1.  Unit cube (6 planar faces): total_area=6.0, centroid=(0.5,0.5,0.5)
2.  Unit sphere: total_area=4pi~12.566, centroid=(0,0,0) within 1e-5
3.  L-shape (two unit squares meeting at an edge): centroid off-centre by known amount
4.  Precision oracle: single planar face, Gauss-Legendre vs analytic < 1e-6
5.  Single square face area = 1.0, centroid = (0.5, 0.5, 0)
6.  surface_centroid returns correct structure (ok, total_area, per_face, caveats)
7.  Cylinder lateral face: area = 2*pi*r*h, centroid at mid-height
8.  Torus full surface: area = 4*pi^2*R*r, centroid = (0,0,0)
9.  face_area() and face_centroid() convenience functions
10. Body.all_faces() integration with surface_centroid
11. Re-export from geom.__init__ (face_area, face_centroid, surface_centroid)
12. Zero-area degenerate face: no crash, area~0
13. Single face (sphere): per_face list has one entry
14. Asymmetric box: total area and centroid match analytic values
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Face,
    Plane,
    CylinderSurface,
    SphereSurface,
    TorusSurface,
    Loop,
    Coedge,
    Edge,
    Vertex,
    Line3,
    make_box,
)
from kerf_cad_core.geom.face_centroid import face_area, face_centroid, surface_centroid


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _square_face(
    origin=(0.0, 0.0, 0.0),
    x_axis=(1.0, 0.0, 0.0),
    y_axis=(0.0, 1.0, 0.0),
    width: float = 1.0,
    height: float = 1.0,
) -> Face:
    """Build a planar square/rectangle face with 4 boundary coedges."""
    ox, oy, oz = origin
    xx, xy, xz = x_axis
    yx, yy, yz = y_axis
    x_vec = np.array([xx, xy, xz], dtype=float) * width
    y_vec = np.array([yx, yy, yz], dtype=float) * height
    O = np.array([ox, oy, oz], dtype=float)
    P = [O, O + x_vec, O + x_vec + y_vec, O + y_vec]
    V = [Vertex(p) for p in P]
    E = [Edge(Line3(P[i], P[(i + 1) % 4]), 0.0, 1.0, V[i], V[(i + 1) % 4]) for i in range(4)]
    coedges = [Coedge(e, True) for e in E]
    loop = Loop(coedges, is_outer=True)
    srf = Plane(origin=P[0], x_axis=P[1] - P[0], y_axis=P[3] - P[0])
    return Face(srf, [loop])


def _sphere_face(center=(0.0, 0.0, 0.0), radius: float = 1.0) -> Face:
    """Single closed sphere face (no bounding loop; full UV domain)."""
    srf = SphereSurface(center=np.array(center, dtype=float), radius=radius)
    return Face(srf, [])


def _cylinder_face(
    center=(0.0, 0.0, 0.0),
    axis=(0.0, 0.0, 1.0),
    radius: float = 1.0,
    height: float = 1.0,
) -> Face:
    """Full lateral cylinder face [0, 2pi] x [0, h]."""
    srf = CylinderSurface(
        center=np.array(center, dtype=float),
        axis=np.array(axis, dtype=float),
        radius=radius,
    )
    ax = np.array(axis, dtype=float)
    ax = ax / np.linalg.norm(ax)
    c = np.array(center, dtype=float)
    p0, p1 = c + ax * 0.0, c + ax * height
    v0, v1 = Vertex(p0), Vertex(p1)
    e0 = Edge(Line3(p0, p1), 0.0, 1.0, v0, v1)
    e1 = Edge(Line3(p1, p0), 0.0, 1.0, v1, v0)
    loop = Loop([Coedge(e0, True), Coedge(e1, True)], is_outer=True)
    return Face(srf, [loop])


def _torus_face(
    center=(0.0, 0.0, 0.0),
    axis=(0.0, 0.0, 1.0),
    major_radius: float = 2.0,
    minor_radius: float = 0.5,
) -> Face:
    """Full torus face (no bounding loop; full UV domain)."""
    srf = TorusSurface(
        center=np.array(center, dtype=float),
        axis=np.array(axis, dtype=float),
        major_radius=major_radius,
        minor_radius=minor_radius,
    )
    return Face(srf, [])


# ---------------------------------------------------------------------------
# 1. Unit cube — area=6, centroid=(0.5, 0.5, 0.5)
# ---------------------------------------------------------------------------

def test_unit_cube_area_and_centroid():
    """Unit cube 6 planar faces: total area=6, centroid=(0.5,0.5,0.5) by symmetry."""
    body = make_box(origin=(0, 0, 0), size=(1, 1, 1))
    faces = body.all_faces()
    assert len(faces) == 6
    result = surface_centroid(faces, n=8)

    assert abs(result["total_area"] - 6.0) < 1e-6, (
        f"Expected total_area=6.0, got {result['total_area']}"
    )
    cx, cy, cz = result["centroid"]
    assert abs(cx - 0.5) < 1e-6, f"cx={cx}"
    assert abs(cy - 0.5) < 1e-6, f"cy={cy}"
    assert abs(cz - 0.5) < 1e-6, f"cz={cz}"


# ---------------------------------------------------------------------------
# 2. Unit sphere — area=4pi, centroid=(0,0,0)
# ---------------------------------------------------------------------------

def test_unit_sphere_area_and_centroid():
    """Unit sphere: area=4pi~12.566, centroid at origin within 1e-4."""
    sf = _sphere_face(center=(0, 0, 0), radius=1.0)
    result = surface_centroid([sf], n=32)

    expected_area = 4 * math.pi
    assert abs(result["total_area"] - expected_area) < 1e-3, (
        f"Sphere area: expected {expected_area:.6f}, got {result['total_area']:.6f}"
    )
    cx, cy, cz = result["centroid"]
    assert abs(cx) < 1e-5, f"Sphere cx={cx}"
    assert abs(cy) < 1e-5, f"Sphere cy={cy}"
    assert abs(cz) < 1e-5, f"Sphere cz={cz}"


# ---------------------------------------------------------------------------
# 3. L-shape (two unit squares meeting at an edge) — centroid off-centre
# ---------------------------------------------------------------------------

def test_l_shape_centroid():
    """Two unit squares: face A at x in [0,1], face B at x in [1,2].

    Combined centroid_x = (0.5*1 + 1.5*1) / 2 = 1.0.
    Combined centroid_y = (0.5*1 + 0.5*1) / 2 = 0.5.
    Each face area = 1.0, total = 2.0.
    """
    fa = _square_face(origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0), width=1.0, height=1.0)
    fb = _square_face(origin=(1, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0), width=1.0, height=1.0)
    result = surface_centroid([fa, fb], n=8)

    assert abs(result["total_area"] - 2.0) < 1e-5
    cx, cy, cz = result["centroid"]
    assert abs(cx - 1.0) < 1e-5, f"L-shape cx={cx}"
    assert abs(cy - 0.5) < 1e-5, f"L-shape cy={cy}"
    assert abs(cz - 0.0) < 1e-5, f"L-shape cz={cz}"


# ---------------------------------------------------------------------------
# 4. Precision oracle: 2x3 rectangle analytic vs Gauss-Legendre
# ---------------------------------------------------------------------------

def test_precision_oracle_planar():
    """2x3 rectangle: area=6, centroid=(1,1.5,0). GL vs analytic < 1e-6."""
    f = _square_face(origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0), width=2.0, height=3.0)
    result = surface_centroid([f], n=16)

    assert abs(result["total_area"] - 6.0) < 1e-6, f"Area: {result['total_area']}"
    cx, cy, cz = result["centroid"]
    assert abs(cx - 1.0) < 1e-6, f"cx={cx}"
    assert abs(cy - 1.5) < 1e-6, f"cy={cy}"
    assert abs(cz - 0.0) < 1e-6, f"cz={cz}"


# ---------------------------------------------------------------------------
# 5. Single unit square face
# ---------------------------------------------------------------------------

def test_single_unit_square():
    f = _square_face()
    result = surface_centroid([f], n=8)
    assert abs(result["total_area"] - 1.0) < 1e-5
    cx, cy, cz = result["centroid"]
    assert abs(cx - 0.5) < 1e-5
    assert abs(cy - 0.5) < 1e-5
    assert abs(cz - 0.0) < 1e-5


# ---------------------------------------------------------------------------
# 6. Return structure validation
# ---------------------------------------------------------------------------

def test_result_structure():
    f = _square_face()
    result = surface_centroid([f])
    assert "centroid" in result
    assert "total_area" in result
    assert "per_face" in result
    assert "caveats" in result
    assert len(result["per_face"]) == 1
    pf = result["per_face"][0]
    assert "face_index" in pf
    assert "area" in pf
    assert "centroid" in pf
    assert "trimmed_approx" in pf
    assert pf["face_index"] == 0
    assert isinstance(pf["trimmed_approx"], bool)


# ---------------------------------------------------------------------------
# 7. Cylinder lateral face
# ---------------------------------------------------------------------------

def test_cylinder_face_area():
    """Cylinder r=1, h=2: lateral area = 2*pi*r*h = 4*pi, centroid at mid-height z=1."""
    r, h = 1.0, 2.0
    cf = _cylinder_face(center=(0, 0, 0), axis=(0, 0, 1), radius=r, height=h)
    result = surface_centroid([cf], n=32)
    expected_area = 2 * math.pi * r * h
    assert abs(result["total_area"] - expected_area) < 0.01, (
        f"Cylinder area: expected {expected_area:.4f}, got {result['total_area']:.4f}"
    )
    cz = result["centroid"][2]
    assert abs(cz - h / 2) < 0.05, f"Cylinder centroid z={cz}, expected {h/2}"


# ---------------------------------------------------------------------------
# 8. Torus full surface
# ---------------------------------------------------------------------------

def test_torus_face_area_and_centroid():
    """Full torus R=2, r=0.5: area=4*pi^2*R*r, centroid=(0,0,0)."""
    R, r = 2.0, 0.5
    tf = _torus_face(center=(0, 0, 0), axis=(0, 0, 1), major_radius=R, minor_radius=r)
    result = surface_centroid([tf], n=32)
    expected_area = 4 * math.pi**2 * R * r
    assert abs(result["total_area"] - expected_area) < 0.1, (
        f"Torus area: expected {expected_area:.4f}, got {result['total_area']:.4f}"
    )
    cx, cy, cz = result["centroid"]
    assert abs(cx) < 0.01, f"Torus cx={cx}"
    assert abs(cy) < 0.01, f"Torus cy={cy}"
    assert abs(cz) < 0.01, f"Torus cz={cz}"


# ---------------------------------------------------------------------------
# 9. face_area() and face_centroid() convenience functions
# ---------------------------------------------------------------------------

def test_face_area_convenience():
    f = _square_face(width=3.0, height=4.0)
    a = face_area(f, n=16)
    assert abs(a - 12.0) < 1e-5


def test_face_centroid_convenience():
    f = _square_face(origin=(2, 3, 0), width=2.0, height=2.0)
    c = face_centroid(f, n=16)
    assert abs(c[0] - 3.0) < 1e-5  # origin.x + width/2
    assert abs(c[1] - 4.0) < 1e-5  # origin.y + height/2
    assert abs(c[2] - 0.0) < 1e-5


# ---------------------------------------------------------------------------
# 10. Body.all_faces() integration
# ---------------------------------------------------------------------------

def test_body_all_faces_integration():
    """Make a 2x2x2 box; total surface area = 6*4=24, centroid=(1,1,1)."""
    body = make_box(origin=(0, 0, 0), size=(2, 2, 2))
    faces = body.all_faces()
    result = surface_centroid(faces, n=8)
    assert abs(result["total_area"] - 24.0) < 1e-4
    cx, cy, cz = result["centroid"]
    assert abs(cx - 1.0) < 1e-5
    assert abs(cy - 1.0) < 1e-5
    assert abs(cz - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# 11. Re-export from geom.__init__
# ---------------------------------------------------------------------------

def test_reexport_from_geom_init():
    from kerf_cad_core.geom import face_area, face_centroid, surface_centroid  # noqa: F401
    assert callable(face_area)
    assert callable(face_centroid)
    assert callable(surface_centroid)


# ---------------------------------------------------------------------------
# 12. Zero-area degenerate face — no crash
# ---------------------------------------------------------------------------

def test_degenerate_zero_area_face():
    """A face with zero-extent UV domain should not crash and return area~0."""
    srf = Plane(origin=np.zeros(3), x_axis=np.array([0.0, 0.0, 0.0]), y_axis=np.array([0.0, 1.0, 0.0]))
    f = Face(srf, [])
    a = face_area(f, n=4)
    assert a >= 0.0


# ---------------------------------------------------------------------------
# 13. Single face (sphere): per_face list has one entry
# ---------------------------------------------------------------------------

def test_single_face_per_face_list():
    sf = _sphere_face()
    result = surface_centroid([sf], n=16)
    assert len(result["per_face"]) == 1
    assert result["per_face"][0]["face_index"] == 0


# ---------------------------------------------------------------------------
# 14. Asymmetric box: analytic area + centroid
# ---------------------------------------------------------------------------

def test_asymmetric_box_centroid():
    """Box 4x2x1 at origin: centroid=(2,1,0.5) by symmetry; total area=28."""
    body = make_box(origin=(0, 0, 0), size=(4, 2, 1))
    faces = body.all_faces()
    result = surface_centroid(faces, n=8)
    cx, cy, cz = result["centroid"]
    assert abs(cx - 2.0) < 1e-4, f"cx={cx}"
    assert abs(cy - 1.0) < 1e-4, f"cy={cy}"
    assert abs(cz - 0.5) < 1e-4, f"cz={cz}"
    # Total area: 2*(4*2 + 4*1 + 2*1) = 2*(8+4+2) = 28
    assert abs(result["total_area"] - 28.0) < 1e-4, f"area={result['total_area']}"
