"""
test_curve_split.py
===================
Analytic-oracle tests for curve_split.py (Piegl–Tiller §5.3 knot-insertion split).

Test matrix
-----------
T1  Line split round-trip
    A NURBS line from (0,0,0) to (1,0,0) split at t=0.5.
    - left end = (0,0,0), right end = (1,0,0)
    - joint point = (0.5,0,0) within 1e-12
    - left.evaluate(0) = (0,0,0), right.evaluate(1) = (1,0,0) within 1e-12
    - left.evaluate(1) = right.evaluate(0) = (0.5,0,0) within 1e-12

T2  Circle quarter split (rational NURBS)
    Unit circle split at t=0.25 → left covers first quadrant.
    - left.evaluate(1) = right.evaluate(0) ≈ (0, 1, 0) within 1e-9
    - All evaluated points on left curve lie on unit circle within 1e-9
    - All evaluated points on right curve lie on unit circle within 1e-9

T3  Multiple splits of a degree-3 curve
    Degree-3 B-spline split at 3 values → 4 sub-curves.
    - len(segments) == 4
    - Each segment has domain [0,1] (knots[0]==0, knots[-1]==1)
    - Segments are C0-continuous at join points within 1e-12

T4  Surface split (bilinear NURBS plane at u=0.5)
    A 1×1 unit bilinear patch split at u=0.5.
    - left control points span x ∈ [0, 0.5]; right span x ∈ [0.5, 1]
    - Evaluation at split line: left.evaluate(1,v) == right.evaluate(0,v) within 1e-12
    - Both sub-surfaces have knots_u domain [0,1]
"""

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    make_line_nurbs,
    make_circle_nurbs,
)
from kerf_cad_core.geom.curve_split import (
    split_curve_at,
    split_curve_at_multiple,
    split_surface_at_u,
    split_surface_at_v,
)


# ---------------------------------------------------------------------------
# T1: Line split round-trip
# ---------------------------------------------------------------------------

class TestLineSplit:
    """Analytic oracle: NURBS line from origin to (1,0,0)."""

    def setup_method(self):
        self.line = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        self.left, self.right = split_curve_at(self.line, 0.5)

    def test_left_start_is_origin(self):
        pt = self.left.evaluate(0.0)
        assert np.allclose(pt, [0.0, 0.0, 0.0], atol=1e-12), (
            f"left.evaluate(0) = {pt}, expected origin"
        )

    def test_left_end_is_midpoint(self):
        pt = self.left.evaluate(1.0)
        assert np.allclose(pt, [0.5, 0.0, 0.0], atol=1e-12), (
            f"left.evaluate(1) = {pt}, expected (0.5, 0, 0)"
        )

    def test_right_start_is_midpoint(self):
        pt = self.right.evaluate(0.0)
        assert np.allclose(pt, [0.5, 0.0, 0.0], atol=1e-12), (
            f"right.evaluate(0) = {pt}, expected (0.5, 0, 0)"
        )

    def test_right_end_is_unit(self):
        pt = self.right.evaluate(1.0)
        assert np.allclose(pt, [1.0, 0.0, 0.0], atol=1e-12), (
            f"right.evaluate(1) = {pt}, expected (1, 0, 0)"
        )

    def test_junction_continuity(self):
        """C0: left end == right start."""
        pt_l = self.left.evaluate(1.0)
        pt_r = self.right.evaluate(0.0)
        assert np.allclose(pt_l, pt_r, atol=1e-12), (
            f"Junction mismatch: left.evaluate(1)={pt_l}, right.evaluate(0)={pt_r}"
        )

    def test_left_domain_is_unit(self):
        assert abs(self.left.knots[0]) < 1e-14 and abs(self.left.knots[-1] - 1.0) < 1e-14, (
            f"left.knots domain not [0,1]: {self.left.knots}"
        )

    def test_right_domain_is_unit(self):
        assert abs(self.right.knots[0]) < 1e-14 and abs(self.right.knots[-1] - 1.0) < 1e-14, (
            f"right.knots domain not [0,1]: {self.right.knots}"
        )

    def test_midpoint_values(self):
        """Interior: left(0.5) ≈ (0.25,0,0), right(0.5) ≈ (0.75,0,0)."""
        pt_l = self.left.evaluate(0.5)
        pt_r = self.right.evaluate(0.5)
        assert np.allclose(pt_l, [0.25, 0.0, 0.0], atol=1e-12)
        assert np.allclose(pt_r, [0.75, 0.0, 0.0], atol=1e-12)


# ---------------------------------------------------------------------------
# T2: Circle split (rational NURBS)
# ---------------------------------------------------------------------------

class TestCircleSplit:
    """Analytic oracle: unit circle split at t=0.25 (end of first quadrant)."""

    def setup_method(self):
        self.circle = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
        )
        self.left, self.right = split_curve_at(self.circle, 0.25)

    def test_junction_is_top_of_first_quadrant(self):
        """At t=0.25 the circle is at (0, 1, 0) (top of first quadrant)."""
        # The circle parametrisation maps t=0.25 to 90° (π/2).
        pt_l = self.left.evaluate(1.0)
        pt_r = self.right.evaluate(0.0)
        expected = np.array([0.0, 1.0, 0.0])
        assert np.allclose(pt_l, expected, atol=1e-9), (
            f"left.evaluate(1) = {pt_l}, expected {expected}"
        )
        assert np.allclose(pt_r, expected, atol=1e-9), (
            f"right.evaluate(0) = {pt_r}, expected {expected}"
        )

    def test_left_start_is_rightmost_point(self):
        """Circle starts at (1,0,0) = t=0."""
        pt = self.left.evaluate(0.0)
        assert np.allclose(pt, [1.0, 0.0, 0.0], atol=1e-9)

    def test_left_curve_on_unit_circle(self):
        """All points on the left sub-curve lie on the unit circle (r=1)."""
        for u in np.linspace(0.0, 1.0, 20):
            pt = self.left.evaluate(u)
            r = np.linalg.norm(pt[:2])  # 2D radius
            assert abs(r - 1.0) < 1e-9, f"left({u}) radius={r:.6f} != 1.0"

    def test_right_curve_on_unit_circle(self):
        """All points on the right sub-curve lie on the unit circle."""
        for u in np.linspace(0.0, 1.0, 20):
            pt = self.right.evaluate(u)
            r = np.linalg.norm(pt[:2])
            assert abs(r - 1.0) < 1e-9, f"right({u}) radius={r:.6f} != 1.0"


# ---------------------------------------------------------------------------
# T3: Multiple splits
# ---------------------------------------------------------------------------

class TestMultipleSplits:
    """A degree-3 uniform B-spline split at 3 parameter values → 4 sub-curves."""

    def _make_degree3_curve(self):
        """Degree-3 clamped uniform curve through 7 control points."""
        cps = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 2.0, 0.0],
            [2.0, -1.0, 0.0],
            [3.0, 1.5, 0.0],
            [4.0, -0.5, 0.0],
            [5.0, 0.5, 0.0],
            [6.0, 0.0, 0.0],
        ])
        # Clamped uniform knot vector for degree 3, 7 CPs: 7+3+1=11 knots
        knots = np.array([0.0, 0.0, 0.0, 0.0,
                          0.25, 0.5, 0.75,
                          1.0, 1.0, 1.0, 1.0])
        return NurbsCurve(degree=3, control_points=cps, knots=knots)

    def setup_method(self):
        self.curve = self._make_degree3_curve()
        self.t_values = [0.25, 0.5, 0.75]
        self.segments = split_curve_at_multiple(self.curve, self.t_values)

    def test_returns_four_segments(self):
        assert len(self.segments) == 4, (
            f"Expected 4 segments, got {len(self.segments)}"
        )

    def test_each_segment_has_unit_domain(self):
        for i, seg in enumerate(self.segments):
            assert abs(seg.knots[0]) < 1e-14, f"seg[{i}] knots[0]={seg.knots[0]}"
            assert abs(seg.knots[-1] - 1.0) < 1e-14, f"seg[{i}] knots[-1]={seg.knots[-1]}"

    def test_junction_c0_continuity(self):
        """Adjacent segments share the same endpoint within 1e-12."""
        for i in range(len(self.segments) - 1):
            pt_end = self.segments[i].evaluate(1.0)
            pt_start = self.segments[i + 1].evaluate(0.0)
            assert np.allclose(pt_end, pt_start, atol=1e-12), (
                f"Junction {i}/{i+1}: end={pt_end}, start={pt_start}, "
                f"diff={np.linalg.norm(pt_end - pt_start):.2e}"
            )

    def test_first_segment_start_matches_original(self):
        original_start = self.curve.evaluate(0.0)
        seg_start = self.segments[0].evaluate(0.0)
        assert np.allclose(original_start, seg_start, atol=1e-12)

    def test_last_segment_end_matches_original(self):
        original_end = self.curve.evaluate(1.0)
        seg_end = self.segments[-1].evaluate(1.0)
        assert np.allclose(original_end, seg_end, atol=1e-12)


# ---------------------------------------------------------------------------
# T4: Surface split
# ---------------------------------------------------------------------------

class TestSurfaceSplit:
    """Bilinear 1×1 NURBS plane split at u=0.5."""

    def _make_unit_plane(self):
        """Degree (1,1) bilinear patch over [0,1]×[0,1]."""
        # Control points: 2×2 grid
        P00 = np.array([0.0, 0.0, 0.0])
        P10 = np.array([1.0, 0.0, 0.0])
        P01 = np.array([0.0, 1.0, 0.0])
        P11 = np.array([1.0, 1.0, 0.0])
        cps = np.array([[P00, P01], [P10, P11]])  # shape (2, 2, 3)
        ku = np.array([0.0, 0.0, 1.0, 1.0])
        kv = np.array([0.0, 0.0, 1.0, 1.0])
        return NurbsSurface(degree_u=1, degree_v=1,
                            control_points=cps, knots_u=ku, knots_v=kv)

    def setup_method(self):
        self.plane = self._make_unit_plane()
        self.left, self.right = split_surface_at_u(self.plane, 0.5)

    def test_left_right_domains_are_unit(self):
        assert abs(self.left.knots_u[0]) < 1e-14 and abs(self.left.knots_u[-1] - 1.0) < 1e-14
        assert abs(self.right.knots_u[0]) < 1e-14 and abs(self.right.knots_u[-1] - 1.0) < 1e-14

    def test_split_line_continuity(self):
        """Evaluation at split line: left.evaluate(1,v) == right.evaluate(0,v)."""
        for v in np.linspace(0.0, 1.0, 11):
            pt_l = self.left.evaluate(1.0, v)
            pt_r = self.right.evaluate(0.0, v)
            assert np.allclose(pt_l, pt_r, atol=1e-12), (
                f"Split line v={v:.2f}: left={pt_l}, right={pt_r}, "
                f"diff={np.linalg.norm(pt_l - pt_r):.2e}"
            )

    def test_left_x_range(self):
        """Left sub-surface spans x ∈ [0, 0.5]."""
        for u in np.linspace(0.0, 1.0, 11):
            for v in np.linspace(0.0, 1.0, 11):
                pt = self.left.evaluate(u, v)
                assert -1e-12 <= pt[0] <= 0.5 + 1e-12, (
                    f"left.evaluate({u:.2f},{v:.2f}).x = {pt[0]:.6f} not in [0, 0.5]"
                )

    def test_right_x_range(self):
        """Right sub-surface spans x ∈ [0.5, 1]."""
        for u in np.linspace(0.0, 1.0, 11):
            for v in np.linspace(0.0, 1.0, 11):
                pt = self.right.evaluate(u, v)
                assert 0.5 - 1e-12 <= pt[0] <= 1.0 + 1e-12, (
                    f"right.evaluate({u:.2f},{v:.2f}).x = {pt[0]:.6f} not in [0.5, 1]"
                )

    def test_left_corners(self):
        """Analytic oracle: bilinear patch corners."""
        assert np.allclose(self.left.evaluate(0.0, 0.0), [0.0, 0.0, 0.0], atol=1e-12)
        assert np.allclose(self.left.evaluate(0.0, 1.0), [0.0, 1.0, 0.0], atol=1e-12)
        assert np.allclose(self.left.evaluate(1.0, 0.0), [0.5, 0.0, 0.0], atol=1e-12)
        assert np.allclose(self.left.evaluate(1.0, 1.0), [0.5, 1.0, 0.0], atol=1e-12)

    def test_right_corners(self):
        assert np.allclose(self.right.evaluate(0.0, 0.0), [0.5, 0.0, 0.0], atol=1e-12)
        assert np.allclose(self.right.evaluate(0.0, 1.0), [0.5, 1.0, 0.0], atol=1e-12)
        assert np.allclose(self.right.evaluate(1.0, 0.0), [1.0, 0.0, 0.0], atol=1e-12)
        assert np.allclose(self.right.evaluate(1.0, 1.0), [1.0, 1.0, 0.0], atol=1e-12)


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_split_at_existing_knot():
    """Split at an existing internal knot (t=0.25 in the degree-3 curve)."""
    cps = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, -1.0, 0.0],
        [3.0, 1.5, 0.0],
        [4.0, -0.5, 0.0],
        [5.0, 0.5, 0.0],
        [6.0, 0.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 1.0, 1.0])
    curve = NurbsCurve(degree=3, control_points=cps, knots=knots)
    left, right = split_curve_at(curve, 0.25)
    pt_l = left.evaluate(1.0)
    pt_r = right.evaluate(0.0)
    pt_orig = curve.evaluate(0.25)
    assert np.allclose(pt_l, pt_orig, atol=1e-12)
    assert np.allclose(pt_r, pt_orig, atol=1e-12)


def test_surface_split_v_continuity():
    """A 1x1 bilinear plane split at v=0.5 → continuity at split row."""
    cps = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
    ])
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    surf = NurbsSurface(degree_u=1, degree_v=1, control_points=cps,
                        knots_u=ku, knots_v=kv)
    bottom, top = split_surface_at_v(surf, 0.5)
    for u in np.linspace(0.0, 1.0, 11):
        pt_b = bottom.evaluate(u, 1.0)
        pt_t = top.evaluate(u, 0.0)
        assert np.allclose(pt_b, pt_t, atol=1e-12), (
            f"v-split u={u:.2f}: bottom_end={pt_b}, top_start={pt_t}"
        )
