"""Tests for GK-87: Pattern (linear / circular / path).

Oracles
-------
1. circular_pattern of a cylinder around an axis yields 4 disjoint bodies
   at correct angles ± tol (90° increments for count=4, full circle).
2. linear_pattern preserves spacing — consecutive body centroids are
   exactly ``spacing`` apart along the direction vector.
3. path_pattern follows the curve — body centroids land on the path at
   evenly-spaced parameter values.
4. count=1 returns a single body (no error).
5. Top-level re-exports accessible from geom.__init__.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep_build import cylinder_to_body, box_to_body
from kerf_cad_core.geom.pattern import linear_pattern, circular_pattern, path_pattern

# Verify top-level re-exports
from kerf_cad_core.geom import (
    linear_pattern as _lp_geom,
    circular_pattern as _cp_geom,
    path_pattern as _pp_geom,
)

_TOL = 1e-6


def _centroid(body) -> np.ndarray:
    """Mean position of all vertices in body."""
    verts = body.all_vertices()
    assert verts, "body has no vertices"
    return np.mean([v.point for v in verts], axis=0)


def _bodies_disjoint(a, b, tol: float = 1e-4) -> bool:
    """Return True if every vertex of a is farther than tol from every vertex of b."""
    verts_a = [v.point for v in a.all_vertices()]
    verts_b = [v.point for v in b.all_vertices()]
    for pa in verts_a:
        for pb in verts_b:
            if np.linalg.norm(pa - pb) < tol:
                return False
    return True


# ---------------------------------------------------------------------------
# Circular pattern oracle
# ---------------------------------------------------------------------------

class TestCircularPattern:
    """4× circular pattern of a cylinder around Z axis."""

    @pytest.fixture
    def cylinder(self):
        # Cylinder centred at (5, 0, 0), axis Z, radius=0.5, height=1
        return cylinder_to_body(
            axis_pt=[5.0, 0.0, 0.0],
            axis_dir=[0.0, 0.0, 1.0],
            radius=0.5,
            height=1.0,
        )

    @pytest.fixture
    def pattern(self, cylinder):
        return circular_pattern(
            cylinder,
            axis_point=[0.0, 0.0, 0.0],
            axis_dir=[0.0, 0.0, 1.0],
            count=4,
            total_angle=2.0 * math.pi,
        )

    def test_count(self, pattern):
        assert len(pattern) == 4

    def test_all_bodies_are_valid(self, pattern):
        from kerf_cad_core.geom.brep import validate_body
        for body in pattern:
            res = validate_body(body)
            assert res["ok"], f"invalid body: {res['errors']}"

    def test_centroids_at_correct_angles(self, pattern):
        """Each centroid should be the body[0] centroid rotated by i*90° around Z."""
        c0 = _centroid(pattern[0])
        # Rotation by angle theta around Z: [x*cos - y*sin, x*sin + y*cos, z]
        for i, body in enumerate(pattern):
            theta = i * math.pi / 2.0
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            expected_x = c0[0] * cos_t - c0[1] * sin_t
            expected_y = c0[0] * sin_t + c0[1] * cos_t
            expected_z = c0[2]
            c = _centroid(body)
            assert abs(c[0] - expected_x) < 1e-4, (
                f"body {i}: expected cx={expected_x:.4f}, got {c[0]:.4f}"
            )
            assert abs(c[1] - expected_y) < 1e-4, (
                f"body {i}: expected cy={expected_y:.4f}, got {c[1]:.4f}"
            )
            assert abs(c[2] - expected_z) < 1e-4, (
                f"body {i}: expected cz={expected_z:.4f}, got {c[2]:.4f}"
            )

    def test_bodies_are_pairwise_disjoint(self, pattern):
        """No vertex from one copy should coincide with a vertex from another."""
        for i in range(len(pattern)):
            for j in range(i + 1, len(pattern)):
                assert _bodies_disjoint(pattern[i], pattern[j]), (
                    f"bodies {i} and {j} share vertices — not disjoint"
                )

    def test_first_body_preserves_original_position(self, pattern, cylinder):
        """The first copy should be at the same position as the source."""
        c_orig = _centroid(cylinder)
        c_copy = _centroid(pattern[0])
        assert np.linalg.norm(c_orig - c_copy) < 1e-5


# ---------------------------------------------------------------------------
# Linear pattern oracle
# ---------------------------------------------------------------------------

class TestLinearPattern:
    @pytest.fixture
    def box(self):
        return box_to_body(corner=[0.0, 0.0, 0.0], dx=1.0, dy=1.0, dz=1.0)

    def test_count(self, box):
        bodies = linear_pattern(box, direction=[1.0, 0.0, 0.0], spacing=3.0, count=5)
        assert len(bodies) == 5

    def test_spacing_along_x(self, box):
        """Centroids should be 3 units apart in X."""
        spacing = 3.0
        bodies = linear_pattern(box, direction=[1.0, 0.0, 0.0], spacing=spacing, count=4)
        centroids = [_centroid(b) for b in bodies]
        for i in range(1, len(centroids)):
            dist = np.linalg.norm(centroids[i] - centroids[i - 1])
            assert abs(dist - spacing) < 1e-5, (
                f"gap between bodies {i-1} and {i}: expected {spacing}, got {dist:.6f}"
            )

    def test_direction_normalised(self, box):
        """Pattern with non-unit direction vector should still space by ``spacing``."""
        bodies = linear_pattern(box, direction=[2.0, 0.0, 0.0], spacing=5.0, count=3)
        centroids = [_centroid(b) for b in bodies]
        for i in range(1, len(centroids)):
            dist = np.linalg.norm(centroids[i] - centroids[i - 1])
            assert abs(dist - 5.0) < 1e-5

    def test_y_direction(self, box):
        """Spacing should work along any axis."""
        bodies = linear_pattern(box, direction=[0.0, 1.0, 0.0], spacing=2.0, count=3)
        c0 = _centroid(bodies[0])
        c2 = _centroid(bodies[2])
        assert abs(c2[1] - c0[1] - 4.0) < 1e-5

    def test_single_copy(self, box):
        bodies = linear_pattern(box, direction=[1.0, 0.0, 0.0], spacing=5.0, count=1)
        assert len(bodies) == 1

    def test_first_body_at_original_position(self, box):
        bodies = linear_pattern(box, direction=[1.0, 0.0, 0.0], spacing=5.0, count=3)
        c_orig = _centroid(box)
        c_copy = _centroid(bodies[0])
        assert np.linalg.norm(c_orig - c_copy) < 1e-5

    def test_bad_count_raises(self, box):
        with pytest.raises(ValueError, match="count"):
            linear_pattern(box, direction=[1.0, 0.0, 0.0], spacing=1.0, count=0)


# ---------------------------------------------------------------------------
# Path pattern oracle
# ---------------------------------------------------------------------------

class _LineCurve:
    """Straight-line curve from ``p0`` to ``p1`` for ``t`` in [0, 1]."""

    def __init__(self, p0, p1):
        self.p0 = np.asarray(p0, dtype=float)
        self.p1 = np.asarray(p1, dtype=float)

    def evaluate(self, t: float) -> np.ndarray:
        return self.p0 + float(t) * (self.p1 - self.p0)


class _CircleCurve:
    """Unit circle in XY plane for ``t`` in [0, 1]."""

    def evaluate(self, t: float) -> np.ndarray:
        angle = 2.0 * math.pi * float(t)
        return np.array([math.cos(angle), math.sin(angle), 0.0])


class TestPathPattern:
    @pytest.fixture
    def box(self):
        return box_to_body(corner=[-0.5, -0.5, -0.5], dx=1.0, dy=1.0, dz=1.0)

    def test_count(self, box):
        curve = _LineCurve([0, 0, 0], [10, 0, 0])
        bodies = path_pattern(box, curve, count=5)
        assert len(bodies) == 5

    def test_first_copy_at_path_start(self, box):
        """First copy centroid should be at path(0)."""
        curve = _LineCurve([0, 0, 0], [10, 0, 0])
        bodies = path_pattern(box, curve, count=4)
        c = _centroid(bodies[0])
        target = curve.evaluate(0.0)
        assert np.linalg.norm(c - target) < 1e-5

    def test_last_copy_at_path_end(self, box):
        """Last copy centroid should be at path(1)."""
        curve = _LineCurve([0, 0, 0], [10, 0, 0])
        bodies = path_pattern(box, curve, count=4)
        c = _centroid(bodies[-1])
        target = curve.evaluate(1.0)
        assert np.linalg.norm(c - target) < 1e-5

    def test_intermediate_positions_on_line(self, box):
        """For a straight-line path, centroids should be uniformly spaced."""
        curve = _LineCurve([0, 0, 0], [9, 0, 0])
        bodies = path_pattern(box, curve, count=4)
        centroids = [_centroid(b) for b in bodies]
        # Expected: [0, 3, 6, 9]
        for i, c in enumerate(centroids):
            expected_x = float(i) * 3.0
            assert abs(c[0] - expected_x) < 1e-5, (
                f"copy {i}: expected x={expected_x}, got {c[0]:.6f}"
            )

    def test_path_follows_circle(self, box):
        """Centroids should land on the unit circle at evenly-spaced angles."""
        curve = _CircleCurve()
        bodies = path_pattern(box, curve, count=8)
        for i, body in enumerate(bodies):
            t = float(i) / 7.0
            expected = curve.evaluate(t)
            c = _centroid(body)
            assert np.linalg.norm(c - expected) < 1e-5, (
                f"copy {i}: expected {expected}, got {c}"
            )

    def test_single_copy(self, box):
        curve = _LineCurve([0, 0, 0], [10, 0, 0])
        bodies = path_pattern(box, curve, count=1)
        assert len(bodies) == 1

    def test_bad_count_raises(self, box):
        curve = _LineCurve([0, 0, 0], [10, 0, 0])
        with pytest.raises(ValueError, match="count"):
            path_pattern(box, curve, count=0)


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestExports:
    def test_geom_init_exports_linear(self):
        from kerf_cad_core.geom.pattern import linear_pattern as _ref
        assert _lp_geom is _ref

    def test_geom_init_exports_circular(self):
        from kerf_cad_core.geom.pattern import circular_pattern as _ref
        assert _cp_geom is _ref

    def test_geom_init_exports_path(self):
        from kerf_cad_core.geom.pattern import path_pattern as _ref
        assert _pp_geom is _ref
