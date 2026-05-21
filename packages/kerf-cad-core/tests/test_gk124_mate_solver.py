"""GK-124: Hermetic, analytic-oracle tests for the mate constraint solver.

All tests are pure-Python (no OCCT, no network, no DB).

Analytic oracles
----------------
* **concentric** — two cylinders mated concentrically: after applying the
  returned transform, the distance from the moved cylinder's axis to the
  fixed cylinder's axis is 0 (±tol).  Oracle is exact for infinite-precision
  rotation+translation.
* **distance** — two planar faces mated with a target separation D: the
  signed distance from the moved centroid to the fixed plane == D (±1e-9).
* **coincident** — face B ends up flush with face A: the projection of the
  moved centroid onto the plane normal equals the fixed face origin (separation
  == 0, ±1e-9).
* **angle** — the dihedral angle between the two normals after mating equals
  the requested target angle (±1e-9 rad).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    CylinderSurface,
    Plane,
    Face,
    Loop,
    Coedge,
    Edge,
    Vertex,
    Shell,
    Solid,
)
from kerf_cad_core.geom.brep_build import cylinder_to_body, box_to_body
from kerf_cad_core.geom.assembly import solve_mate
# Also verify the public façade export.
from kerf_cad_core.geom import solve_mate as solve_mate_public

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOL_EXACT = 1e-9   # used for translation-only results
TOL_ROT   = 1e-9   # used for rotation-derived results


def _apply_transform(T: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply a 4×4 homogeneous transform to an (N, 3) array of points."""
    ones = np.ones((points.shape[0], 1), dtype=float)
    ph = np.hstack([points, ones])          # (N, 4)
    ph_new = (T @ ph.T).T                   # (N, 4)
    return ph_new[:, :3]


def _point_to_line_dist(point: np.ndarray, line_pt: np.ndarray, line_dir: np.ndarray) -> float:
    """Perpendicular distance from *point* to the infinite line (line_pt, line_dir)."""
    d = point - line_pt
    proj = np.dot(d, line_dir) * line_dir
    perp = d - proj
    return float(np.linalg.norm(perp))


def _make_plane_face(origin, normal, size: float = 1.0):
    """Create a minimal planar Face for testing.

    The face has a square loop in the plane so vertices are available for
    centroid estimation.
    """
    origin = np.asarray(origin, dtype=float)
    normal = np.asarray(normal, dtype=float)
    normal = normal / np.linalg.norm(normal)

    # Pick two axes in the plane.
    if abs(float(normal[0])) < 0.9:
        x_ax = np.array([1.0, 0.0, 0.0]) - float(normal[0]) * normal
    else:
        x_ax = np.array([0.0, 1.0, 0.0]) - float(normal[1]) * normal
    x_ax = x_ax / np.linalg.norm(x_ax)
    y_ax = np.cross(normal, x_ax)
    y_ax = y_ax / np.linalg.norm(y_ax)

    surf = Plane(origin=origin, x_axis=x_ax, y_axis=y_ax)

    # Four corner vertices forming a square of side *size*.
    h = size * 0.5
    corners = [
        Vertex(origin + h * x_ax + h * y_ax),
        Vertex(origin - h * x_ax + h * y_ax),
        Vertex(origin - h * x_ax - h * y_ax),
        Vertex(origin + h * x_ax - h * y_ax),
    ]

    from kerf_cad_core.geom.brep import Line3
    edges = []
    n = len(corners)
    for i in range(n):
        v0 = corners[i]
        v1 = corners[(i + 1) % n]
        line = Line3(v0.point, v1.point)
        edges.append(Edge(line, 0.0, 1.0, v0, v1))

    coedges = [Coedge(e, True) for e in edges]
    loop = Loop(coedges, is_outer=True)
    face = Face(surf, [loop], orientation=True)
    return face


def _make_cylinder_face(center, axis, radius: float, height: float = 2.0):
    """Return the lateral CylinderSurface Face of a cylinder.

    Uses the full ``cylinder_to_body`` builder and extracts the lateral face
    (index 0 by convention from ``brep_build.cylinder_to_body``).
    """
    body = cylinder_to_body(center, axis, radius, height)
    # The lateral face (CylinderSurface) is always at index 0.
    for face in body.all_faces():
        if isinstance(face.surface, CylinderSurface):
            return face
    raise RuntimeError("No cylindrical face found in cylinder_to_body output")  # pragma: no cover


# ---------------------------------------------------------------------------
# Tests — concentric mate
# ---------------------------------------------------------------------------


class TestConcentric:
    """Oracle: after apply, distance from moved cylinder axis to fixed axis == 0."""

    def test_axes_collinear_after_parallel_offset(self):
        """Cylinders with parallel axes offset by (3, 4, 0) → axes collinear."""
        # Fixed cylinder: axis along Z, centred at origin.
        face_a = _make_cylinder_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], radius=1.0)
        # Moving cylinder: same axis direction but shifted laterally.
        face_b = _make_cylinder_face([3.0, 4.0, 0.0], [0.0, 0.0, 1.0], radius=1.5)

        result = solve_mate(None, "concentric", face_a, face_b)
        assert result["ok"] is True

        T = result["transform"]
        assert T.shape == (4, 4)

        # Original axis point on moving cylinder
        cB_orig = np.array([3.0, 4.0, 0.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]

        axA = np.array([0.0, 0.0, 1.0])
        cA = np.array([0.0, 0.0, 0.0])
        dist = _point_to_line_dist(cB_new, cA, axA)
        assert dist < 1e-9, f"Axis-to-axis distance after concentric mate = {dist}"

    def test_axes_collinear_anti_parallel(self):
        """Axes that are anti-parallel also become collinear."""
        face_a = _make_cylinder_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], radius=1.0)
        # Anti-parallel axis, offset laterally.
        face_b = _make_cylinder_face([2.0, 0.0, 5.0], [0.0, 0.0, -1.0], radius=1.0)

        result = solve_mate(None, "concentric", face_a, face_b)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([2.0, 0.0, 5.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        axA = np.array([0.0, 0.0, 1.0])
        cA = np.array([0.0, 0.0, 0.0])
        assert _point_to_line_dist(cB_new, cA, axA) < 1e-9

    def test_axes_collinear_perpendicular_axes(self):
        """Moving cylinder axis is perpendicular to fixed axis."""
        face_a = _make_cylinder_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], radius=1.0)
        face_b = _make_cylinder_face([5.0, 0.0, 0.0], [1.0, 0.0, 0.0], radius=2.0)

        result = solve_mate(None, "concentric", face_a, face_b)
        assert result["ok"] is True
        T = result["transform"]

        # After transform the axis direction of B must point along Z.
        # Check the rotated axis direction (rotate the axB vector by R).
        R = T[:3, :3]
        axB_orig = np.array([1.0, 0.0, 0.0])
        axB_new = R @ axB_orig
        axA = np.array([0.0, 0.0, 1.0])
        cross = np.cross(axB_new, axA)
        assert np.linalg.norm(cross) < 1e-9, "Axes not parallel after concentric mate"

        # Axis line passes through origin.
        cB_orig = np.array([5.0, 0.0, 0.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        assert _point_to_line_dist(cB_new, np.zeros(3), axA) < 1e-9

    def test_public_facade_export(self):
        """solve_mate is accessible from the public geom package."""
        face_a = _make_cylinder_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], radius=1.0)
        face_b = _make_cylinder_face([1.0, 0.0, 0.0], [0.0, 0.0, 1.0], radius=1.0)
        result = solve_mate_public(None, "concentric", face_a, face_b)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Tests — distance mate
# ---------------------------------------------------------------------------


class TestDistance:
    """Oracle: after apply, signed distance from moved centroid to fixed plane == target."""

    def _signed_dist(self, point, plane_origin, plane_normal):
        return float(np.dot(point - plane_origin, plane_normal))

    def test_target_zero(self):
        """Distance-mate with target=0 → centroids coplanar."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 3.0], [0.0, 0.0, 1.0])

        result = solve_mate(None, "distance", face_a, face_b, distance=0.0)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([0.0, 0.0, 3.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        d = self._signed_dist(cB_new, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert abs(d) < TOL_EXACT, f"Expected 0, got {d}"

    def test_target_5(self):
        """Distance-mate with target=5 → separation is exactly 5."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 2.0], [0.0, 0.0, 1.0])

        result = solve_mate(None, "distance", face_a, face_b, distance=5.0)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([0.0, 0.0, 2.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        d = self._signed_dist(cB_new, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert abs(d - 5.0) < TOL_EXACT, f"Expected 5.0, got {d}"

    def test_negative_distance(self):
        """Negative distance pulls face B to the other side of face A."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 1.0], [0.0, 0.0, 1.0])

        result = solve_mate(None, "distance", face_a, face_b, distance=-3.0)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([0.0, 0.0, 1.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        d = self._signed_dist(cB_new, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert abs(d - (-3.0)) < TOL_EXACT, f"Expected -3.0, got {d}"

    def test_oblique_normal(self):
        """Distance mate along a diagonal normal."""
        n = np.array([1.0, 1.0, 0.0]) / math.sqrt(2.0)
        face_a = _make_plane_face([0.0, 0.0, 0.0], n)
        face_b = _make_plane_face([4.0, 4.0, 0.0], n)

        result = solve_mate(None, "distance", face_a, face_b, distance=2.0)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([4.0, 4.0, 0.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        d = self._signed_dist(cB_new, np.array([0.0, 0.0, 0.0]), n)
        assert abs(d - 2.0) < TOL_EXACT


# ---------------------------------------------------------------------------
# Tests — coincident mate
# ---------------------------------------------------------------------------


class TestCoincident:
    """Oracle: after apply, separation between faces is 0 (faces are flush)."""

    def _face_separation(self, cB_new, cA_origin, nA):
        return abs(float(np.dot(cB_new - cA_origin, nA)))

    def test_parallel_faces_same_normal(self):
        """Two parallel planes with same normal → coincident (separation=0)."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([1.0, 2.0, 5.0], [0.0, 0.0, 1.0])

        result = solve_mate(None, "coincident", face_a, face_b)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([1.0, 2.0, 5.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        sep = self._face_separation(cB_new, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert sep < TOL_EXACT, f"Separation after coincident mate = {sep}"

    def test_antiparallel_normals(self):
        """Faces with anti-parallel normals rotate into contact."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 3.0], [0.0, 0.0, -1.0])

        result = solve_mate(None, "coincident", face_a, face_b)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([0.0, 0.0, 3.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        sep = self._face_separation(cB_new, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert sep < TOL_EXACT

    def test_perpendicular_normals(self):
        """Face B normal perpendicular to face A normal: rotation + translation."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([3.0, 0.0, 0.0], [1.0, 0.0, 0.0])

        result = solve_mate(None, "coincident", face_a, face_b)
        assert result["ok"] is True
        T = result["transform"]

        cB_orig = np.array([3.0, 0.0, 0.0])
        cB_new = _apply_transform(T, cB_orig[np.newaxis, :])[0]
        sep = self._face_separation(cB_new, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert sep < TOL_EXACT


# ---------------------------------------------------------------------------
# Tests — angle mate
# ---------------------------------------------------------------------------


class TestAngle:
    """Oracle: after apply, the dihedral angle between normals == target."""

    def _angle_between(self, T, nB_orig, nA):
        R = T[:3, :3]
        nB_new = R @ nB_orig
        dot = float(np.dot(nA, nB_new))
        return math.acos(max(-1.0, min(1.0, dot)))

    def test_angle_ninety_degrees(self):
        """Request 90° dihedral angle between two originally-parallel faces."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 1.0], [0.0, 0.0, 1.0])

        target = math.pi / 2.0
        result = solve_mate(None, "angle", face_a, face_b, angle=target)
        assert result["ok"] is True
        T = result["transform"]

        theta = self._angle_between(T, np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]))
        assert abs(theta - target) < TOL_ROT, f"Expected {target:.6f}, got {theta:.6f}"

    def test_angle_zero_from_perpendicular(self):
        """Starting from 90° (nB perpendicular to nA), request 0° → parallel."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])

        result = solve_mate(None, "angle", face_a, face_b, angle=0.0)
        assert result["ok"] is True
        T = result["transform"]

        theta = self._angle_between(T, np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]))
        assert abs(theta - 0.0) < TOL_ROT, f"Expected 0, got {theta:.6f}"

    def test_angle_45_degrees(self):
        """Request 45° between two originally-aligned faces."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 2.0], [0.0, 0.0, 1.0])

        target = math.pi / 4.0
        result = solve_mate(None, "angle", face_a, face_b, angle=target)
        assert result["ok"] is True
        T = result["transform"]

        theta = self._angle_between(T, np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]))
        assert abs(theta - target) < TOL_ROT


# ---------------------------------------------------------------------------
# Tests — error cases
# ---------------------------------------------------------------------------


class TestErrors:
    def test_invalid_mate_type_raises(self):
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 1.0], [0.0, 0.0, 1.0])
        with pytest.raises(ValueError, match="mate_type"):
            solve_mate(None, "nonexistent", face_a, face_b)

    def test_concentric_non_cylinder_raises(self):
        """Concentric mate on a planar face raises ValueError.

        ``_face_cylinder_info`` raises ValueError for non-CylinderSurface faces.
        ValueError is not swallowed by solve_mate so it propagates to the caller,
        letting the UI report "wrong geometry type" cleanly.
        """
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([1.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        with pytest.raises(ValueError, match="[Cc]oncentric|[Cc]ylinder"):
            solve_mate(None, "concentric", face_a, face_b)

    def test_return_shape(self):
        """Transform is always a 4×4 matrix."""
        face_a = _make_plane_face([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
        face_b = _make_plane_face([0.0, 0.0, 1.0], [0.0, 0.0, 1.0])
        for mate in ("coincident", "distance", "angle"):
            result = solve_mate(None, mate, face_a, face_b)
            assert result["transform"].shape == (4, 4)
            assert result["ok"] is True
