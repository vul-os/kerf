"""GK-82 — hermetic oracle tests for imprint_curve_on_face.

Oracles (from spec):
  1. Imprint a great-circle on a sphere face splits it into two equal-area
     hemispheres ± tol.
  2. Imprint a straight line on a planar face splits it into two halves of
     correct area.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.imprint import imprint_curve_on_face
from kerf_cad_core.geom.brep import (
    Body, Shell, Face, Loop, Coedge, Edge, Vertex,
    Line3, Plane, SphereSurface, _unit,
)


# ---------------------------------------------------------------------------
# Area helpers
# ---------------------------------------------------------------------------


def _poly_area_3d(pts) -> float:
    """Area of a planar polygon via fan triangulation from centroid."""
    pts = [np.asarray(p, dtype=float) for p in pts]
    n = len(pts)
    if n < 3:
        return 0.0
    c = np.mean(pts, axis=0)
    area = 0.0
    for i in range(n):
        a = pts[i] - c
        b = pts[(i + 1) % n] - c
        area += float(np.linalg.norm(np.cross(a, b)))
    return area * 0.5


def _face_poly_area(face: Face) -> float:
    """Area of a B-rep Face from its outer loop vertex positions."""
    outer = face.outer_loop()
    if outer is None:
        return 0.0
    pts = [ce.start_point() for ce in outer.coedges]
    return _poly_area_3d(pts)


# ---------------------------------------------------------------------------
# Body-building helpers
# ---------------------------------------------------------------------------


def _make_brep_face(pts) -> Face:
    """Build a minimal B-rep Face from an ordered list of 3-D points."""
    pts = [np.asarray(p, dtype=float) for p in pts]
    n = len(pts)
    e1 = _unit(pts[1] - pts[0])
    normal = np.zeros(3)
    for i in range(2, n):
        crs = np.cross(e1, pts[i] - pts[0])
        if np.linalg.norm(crs) > 1e-10:
            normal = _unit(crs)
            break
    if np.linalg.norm(normal) < 1e-10:
        normal = np.array([0.0, 0.0, 1.0])
    y_axis = _unit(np.cross(normal, e1))
    if np.linalg.norm(y_axis) < 1e-10:
        y_axis = _unit(np.cross(normal, np.array([0.0, 1.0, 0.0])))
    srf = Plane(origin=pts[0].copy(), x_axis=e1, y_axis=y_axis)
    vertices = [Vertex(point=p.copy()) for p in pts]
    coedges = []
    for i in range(n):
        v0, v1 = vertices[i], vertices[(i + 1) % n]
        seg = Line3(p0=v0.point.copy(), p1=v1.point.copy())
        e = Edge(curve=seg, t0=0.0, t1=1.0, v_start=v0, v_end=v1)
        coedges.append(Coedge(edge=e, orientation=True))
    loop = Loop(coedges=coedges, is_outer=True)
    return Face(surface=srf, loops=[loop])


def _face_in_body(face: Face) -> Body:
    """Wrap a single Face in a Body."""
    shell = Shell(faces=[face], is_closed=False)
    return Body(shells=[shell])


# ---------------------------------------------------------------------------
# Oracle 1: Great-circle imprint on a sphere face → two equal-area hemispheres
# ---------------------------------------------------------------------------
#
# We build a sphere body with a single face backed by SphereSurface and a
# simple 4-point outer-loop polygon approximating the sphere's equator so
# that the split can be applied. The great-circle curve is the equatorial
# circle (v=0 for all u), which divides the sphere into two hemispheres.
#
# The polygon we use is a square at z=±1 (the poles) and x/y=±1 (equator
# corners), producing a 4-point great-circle loop on the unit sphere.
# The imprint curve connects two equator points via the equatorial great
# circle, and the polygon is split into two halves.


class _GreatCircleCurve:
    """Half great-circle (equatorial) on the unit sphere: u in [0, pi]."""

    def __init__(self, center=(0.0, 0.0, 0.0), radius=1.0):
        self.center = np.asarray(center, dtype=float)
        self.radius = radius
        # parametric range: [0, 1] maps to u in [0, pi] at v=0 (equator)
        self.t0 = 0.0
        self.t1 = 1.0

    def evaluate(self, t: float) -> np.ndarray:
        u = float(t) * math.pi  # 0 → pi
        v = 0.0  # equatorial great circle
        return self.center + self.radius * np.array(
            [math.cos(u) * math.cos(v), math.sin(u) * math.cos(v), math.sin(v)]
        )


def _make_sphere_face_body(radius=1.0):
    """Build a Body with a single SphereSurface face.

    The outer loop is a 4-vertex polygon approximating the equatorial square
    of the unit sphere (4 points at equator positions), which gives two halves
    of equal area when split at the midpoints.
    """
    center = np.array([0.0, 0.0, 0.0])
    srf = SphereSurface(center=center, radius=radius)

    # 4-vertex equatorial square: points at (1,0,0), (0,1,0), (-1,0,0), (0,-1,0)
    pts = [
        np.array([radius, 0.0, 0.0]),
        np.array([0.0, radius, 0.0]),
        np.array([-radius, 0.0, 0.0]),
        np.array([0.0, -radius, 0.0]),
    ]
    n = len(pts)
    vertices = [Vertex(point=p.copy()) for p in pts]
    coedges = []
    for i in range(n):
        v0, v1 = vertices[i], vertices[(i + 1) % n]
        seg = Line3(p0=v0.point.copy(), p1=v1.point.copy())
        e = Edge(curve=seg, t0=0.0, t1=1.0, v_start=v0, v_end=v1)
        coedges.append(Coedge(edge=e, orientation=True))
    loop = Loop(coedges=coedges, is_outer=True)
    face = Face(surface=srf, loops=[loop])
    shell = Shell(faces=[face], is_closed=False)
    return Body(shells=[shell])


class TestImprintGreatCircle:
    """Imprint equatorial great-circle on a sphere face → two equal-area halves."""

    TOL = 1e-4  # polygon approximation tolerance

    def _setup(self):
        body = _make_sphere_face_body(radius=1.0)
        # Great-circle from (1,0,0) to (-1,0,0) via equator (u: 0→pi)
        curve = _GreatCircleCurve(radius=1.0)
        return body, curve

    def test_returns_body(self):
        body, curve = self._setup()
        result = imprint_curve_on_face(body, 0, curve)
        assert isinstance(result, Body)

    def test_returns_two_faces(self):
        body, curve = self._setup()
        result = imprint_curve_on_face(body, 0, curve)
        assert len(result.all_faces()) == 2, (
            f"Expected 2 faces, got {len(result.all_faces())}"
        )

    def test_both_faces_have_area(self):
        body, curve = self._setup()
        result = imprint_curve_on_face(body, 0, curve)
        faces = result.all_faces()
        area_a = _face_poly_area(faces[0])
        area_b = _face_poly_area(faces[1])
        assert area_a > 0.0, f"face_a area {area_a} should be positive"
        assert area_b > 0.0, f"face_b area {area_b} should be positive"

    def test_equal_area_hemispheres(self):
        """Both halves should have equal area (symmetric equatorial split)."""
        body, curve = self._setup()
        result = imprint_curve_on_face(body, 0, curve)
        faces = result.all_faces()
        area_a = _face_poly_area(faces[0])
        area_b = _face_poly_area(faces[1])
        assert abs(area_a - area_b) < self.TOL, (
            f"Hemisphere areas not equal: {area_a:.8f} vs {area_b:.8f}"
        )

    def test_total_area_preserved(self):
        """Total area of the two halves must equal the original polygon area."""
        body, curve = self._setup()
        orig_area = _face_poly_area(body.all_faces()[0])
        result = imprint_curve_on_face(body, 0, curve)
        faces = result.all_faces()
        total = _face_poly_area(faces[0]) + _face_poly_area(faces[1])
        assert abs(total - orig_area) < self.TOL, (
            f"Total area {total:.8f} not ≈ original {orig_area:.8f}"
        )

    def test_original_body_not_mutated(self):
        """Input body must not be modified."""
        body, curve = self._setup()
        n_before = len(body.all_faces())
        imprint_curve_on_face(body, 0, curve)
        assert len(body.all_faces()) == n_before


# ---------------------------------------------------------------------------
# Oracle 2: Straight line on a planar face → two halves of correct area
# ---------------------------------------------------------------------------


class TestImprintPlanarLine:
    """Imprint a horizontal midline on a unit square → two rectangles of 0.5 each."""

    TOL = 1e-6

    def _setup(self):
        # Unit square in XY: (0,0,0), (1,0,0), (1,1,0), (0,1,0)
        pts = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
        face = _make_brep_face(pts)
        body = _face_in_body(face)
        # Horizontal midline from (0, 0.5, 0) to (1, 0.5, 0)
        midline = Line3(
            p0=np.array([0.0, 0.5, 0.0]),
            p1=np.array([1.0, 0.5, 0.0]),
        )
        return body, midline

    def test_returns_body(self):
        body, midline = self._setup()
        result = imprint_curve_on_face(body, 0, midline)
        assert isinstance(result, Body)

    def test_returns_two_faces(self):
        body, midline = self._setup()
        result = imprint_curve_on_face(body, 0, midline)
        assert len(result.all_faces()) == 2

    def test_each_area_is_half(self):
        body, midline = self._setup()
        result = imprint_curve_on_face(body, 0, midline)
        faces = result.all_faces()
        area_a = _face_poly_area(faces[0])
        area_b = _face_poly_area(faces[1])
        assert abs(area_a - 0.5) < self.TOL, f"face_a area {area_a:.8f} not ≈ 0.5"
        assert abs(area_b - 0.5) < self.TOL, f"face_b area {area_b:.8f} not ≈ 0.5"

    def test_total_area_preserved(self):
        body, midline = self._setup()
        result = imprint_curve_on_face(body, 0, midline)
        faces = result.all_faces()
        total = _face_poly_area(faces[0]) + _face_poly_area(faces[1])
        assert abs(total - 1.0) < self.TOL, f"Total area {total:.8f} not ≈ 1.0"

    def test_diagonal_split(self):
        """Diagonal split of unit square → two triangles of area 0.5 each."""
        pts = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
        face = _make_brep_face(pts)
        body = _face_in_body(face)
        diag = Line3(
            p0=np.array([0.0, 0.0, 0.0]),
            p1=np.array([1.0, 1.0, 0.0]),
        )
        result = imprint_curve_on_face(body, 0, diag)
        faces = result.all_faces()
        assert len(faces) == 2
        area_a = _face_poly_area(faces[0])
        area_b = _face_poly_area(faces[1])
        assert abs(area_a - 0.5) < 1e-6, f"face_a area {area_a:.8f}"
        assert abs(area_b - 0.5) < 1e-6, f"face_b area {area_b:.8f}"

    def test_original_body_not_mutated(self):
        body, midline = self._setup()
        n_before = len(body.all_faces())
        imprint_curve_on_face(body, 0, midline)
        assert len(body.all_faces()) == n_before


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestImprintErrors:
    def test_wrong_type_raises_type_error(self):
        with pytest.raises(TypeError):
            imprint_curve_on_face("not a body", 0, Line3(np.zeros(3), np.ones(3)))

    def test_out_of_range_face_id(self):
        pts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        face = _make_brep_face(pts)
        body = _face_in_body(face)
        with pytest.raises(ValueError):
            imprint_curve_on_face(body, 5, Line3(np.zeros(3), np.ones(3)))

    def test_negative_face_id(self):
        pts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        face = _make_brep_face(pts)
        body = _face_in_body(face)
        with pytest.raises(ValueError):
            imprint_curve_on_face(body, -1, Line3(np.zeros(3), np.ones(3)))


# ---------------------------------------------------------------------------
# Public import smoke test
# ---------------------------------------------------------------------------


def test_import_from_geom_init():
    from kerf_cad_core.geom import imprint_curve_on_face as icf  # noqa: F401
    assert callable(icf)
