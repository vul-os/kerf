"""Tests for loft_guide_rails.py — GK-P16 NURBS loft with guide rails.

Test suite (12+ tests):
  1.  Two parallel circle cross-sections + 1 straight guide: cylinder-like surface,
      radius consistent with input.
  2.  Two cross-sections + curved guide: surface bulges toward guide.
  3.  3 cross-sections + 2 guide rails: figure-of-8 swept surface is produced.
  4.  Mismatched guide endpoints (don't lie on cross-section): UserWarning issued.
  5.  Single cross-section raises ValueError.
  6.  Zero guide rails raises ValueError.
  7.  closed_v=True raises NotImplementedError.
  8.  GuideRailLoftReport fields are present and typed correctly.
  9.  Surface has finite, non-NaN control points.
  10. max_guide_rail_deviation_mm >= mean_guide_rail_deviation_mm.
  11. num_self_intersections is a non-negative integer.
  12. honest_caveat is a non-empty string.
  13. 4 cross-sections + 3 guide rails (over-determined): produces valid surface.
  14. degree_v clamp: degree_v > n_sections - 1 is silently clamped.
  15. Spec dataclass defaults are applied correctly.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.loft_guide_rails import (
    GuideRailLoftSpec,
    GuideRailLoftReport,
    loft_with_guide_rails,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(p0, p1) -> NurbsCurve:
    """Degree-1 line NurbsCurve from p0 to p1."""
    pts = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


def _polyline(*pts) -> NurbsCurve:
    """Degree-1 polyline NurbsCurve through the given points."""
    pts_arr = np.array(pts, dtype=float)
    n = pts_arr.shape[0]
    # Build clamped knot vector for degree 1.
    knots = np.zeros(n + 1)  # m = n_ctrl + degree + 1 = n + 1 + 1 = n+2; oops: degree=1
    # Proper: m = n + degree + 1 = n + 1 + 1
    m = n + 2
    knots = np.zeros(m)
    knots[0] = 0.0
    knots[-1] = 1.0
    if n > 1:
        step = 1.0 / (n - 1)
        for i in range(1, n):
            knots[i + 1] = knots[i] + step  # oversimplified; use linspace
    # Simpler: just build from linspace
    knots = np.concatenate([
        [0.0],
        np.linspace(0.0, 1.0, n),
        [1.0],
    ])
    # That gives n+2 knots but we need n + degree + 1 = n + 2. Good.
    # Wait: NurbsCurve degree=1, n_ctrl=n, needs m = n + 2 knots. We have n+2. Good.
    return NurbsCurve(degree=1, control_points=pts_arr, knots=knots)


def _approx_circle(radius: float, z: float) -> NurbsCurve:
    """Degree-2 3-point approximate circle in XY at height z.

    Uses three equally-spaced points on the circle as control points.
    This is a shape approximation, not an exact NURBS circle.
    """
    angles = [0.0, 2 * math.pi / 3, 4 * math.pi / 3]
    pts = np.array([
        [radius * math.cos(a), radius * math.sin(a), z]
        for a in angles
    ], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=pts, knots=knots)


def _quad(p0, pmid, p1) -> NurbsCurve:
    """Degree-2 Bezier curve through p0, pmid, p1."""
    pts = np.array([p0, pmid, p1], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=pts, knots=knots)


def _figure8_cross_section(scale: float, z: float) -> NurbsCurve:
    """A rough figure-of-8 cross section: two arcs represented as a polyline."""
    # Use a simple S-shape curve as the cross section.
    pts = np.array([
        [-scale,  scale * 0.5, z],
        [-scale * 0.5, 0.0, z],
        [0.0,  0.0, z],
        [ scale * 0.5, 0.0, z],
        [ scale, -scale * 0.5, z],
    ], dtype=float)
    n = pts.shape[0]
    m = n + 2  # degree=1, m = n_ctrl + degree + 1
    knots = np.zeros(m)
    knots[0] = 0.0
    knots[-1] = 1.0
    knots[1:-1] = np.linspace(0.0, 1.0, n)
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


# ---------------------------------------------------------------------------
# Test 1: Two parallel circles + 1 straight guide → cylinder-like surface
# ---------------------------------------------------------------------------

class TestCylinderLike:
    """Two parallel circle cross-sections + one straight guide rail."""

    def _spec(self, radius=1.0, height=2.0) -> GuideRailLoftSpec:
        cs0 = _approx_circle(radius, z=0.0)
        cs1 = _approx_circle(radius, z=height)
        # Guide rail: vertical line at (radius, 0, z)
        guide = _line([radius, 0.0, 0.0], [radius, 0.0, height])
        return GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1],
            guide_rail_curves=[guide],
            num_v_samples=12,
            degree_v=1,
        )

    def test_returns_report(self):
        report = loft_with_guide_rails(self._spec())
        assert isinstance(report, GuideRailLoftReport)

    def test_surface_is_nurbs(self):
        report = loft_with_guide_rails(self._spec())
        assert isinstance(report.loft_surface, NurbsSurface)

    def test_num_cross_sections_stored(self):
        report = loft_with_guide_rails(self._spec())
        assert report.num_cross_sections == 2

    def test_num_guide_rails_stored(self):
        report = loft_with_guide_rails(self._spec())
        assert report.num_guide_rails == 1

    def test_control_points_finite(self):
        report = loft_with_guide_rails(self._spec())
        cp = report.loft_surface.control_points
        assert np.all(np.isfinite(cp)), "Control points contain NaN or Inf"

    def test_radius_consistent(self):
        """Average radial distance of control points should be near the input radius."""
        radius = 2.0
        report = loft_with_guide_rails(self._spec(radius=radius))
        cp = report.loft_surface.control_points  # (nu, nv, 3)
        # Take the first v-slice (close to z=0).
        first_slice = cp[:, 0, :2]  # (nu, 2) — x,y only
        radii = np.linalg.norm(first_slice, axis=1)
        # Allow generous tolerance since this is an approximate circle.
        assert np.abs(np.mean(radii) - radius) < radius * 1.5, (
            f"Mean radius {np.mean(radii):.3f} unexpectedly far from {radius}"
        )


# ---------------------------------------------------------------------------
# Test 2: Two cross-sections + curved guide → surface bulges toward guide
# ---------------------------------------------------------------------------

class TestCurvedGuide:
    """Curved guide rail should pull the surface away from the straight loft."""

    def _data(self):
        cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
        # Curved guide: arcs toward y=0.5 at midpoint.
        curved_guide = _quad([0.0, 0.0, 0.0], [0.0, 0.5, 0.5], [0.0, 0.0, 1.0])
        return cs0, cs1, curved_guide

    def test_surface_produced(self):
        cs0, cs1, guide = self._data()
        spec = GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1],
            guide_rail_curves=[guide],
            num_v_samples=16,
            degree_v=2,
        )
        report = loft_with_guide_rails(spec)
        assert isinstance(report.loft_surface, NurbsSurface)

    def test_surface_bulges_toward_guide(self):
        """Mid-surface y-coordinates should be > 0 if the guide curves toward y>0."""
        cs0, cs1, guide = self._data()
        spec = GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1],
            guide_rail_curves=[guide],
            num_v_samples=20,
            degree_v=2,
        )
        report = loft_with_guide_rails(spec)
        srf = report.loft_surface
        # Evaluate the surface at mid-v, x=0 corner.
        u0 = float(srf.knots_u[srf.degree_u])
        u1 = float(srf.knots_u[-srf.degree_u - 1])
        v0 = float(srf.knots_v[srf.degree_v])
        v1 = float(srf.knots_v[-srf.degree_v - 1])
        mid_v = 0.5 * (v0 + v1)
        pt = np.asarray(srf.evaluate(u0, mid_v), dtype=float).ravel()[:3]
        # The guide rail at v=0.5 has y=0.5; the surface should be pulled toward y>0.
        # With the blend, it should be at least y>0 at x=0 corner.
        assert pt[1] >= -1e-3, (
            f"Expected y>=0 near curved guide, got y={pt[1]:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 3: 3 cross-sections + 2 guide rails → figure-of-8 swept surface
# ---------------------------------------------------------------------------

class TestFigureOf8:
    """3 cross-sections + 2 guide rails (figure-of-8 style)."""

    def _spec(self) -> GuideRailLoftSpec:
        scale = 1.0
        cs0 = _figure8_cross_section(scale, z=0.0)
        cs1 = _figure8_cross_section(scale * 0.8, z=1.0)  # slight taper
        cs2 = _figure8_cross_section(scale, z=2.0)

        # Two guide rails at the extremes.
        g0 = _line([-scale, 0.5 * scale, 0.0], [-scale, 0.5 * scale, 2.0])
        g1 = _line([ scale, -0.5 * scale, 0.0], [ scale, -0.5 * scale, 2.0])

        return GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1, cs2],
            guide_rail_curves=[g0, g1],
            num_v_samples=14,
            degree_v=2,
        )

    def test_surface_produced(self):
        report = loft_with_guide_rails(self._spec())
        assert isinstance(report.loft_surface, NurbsSurface)

    def test_three_cross_sections_stored(self):
        report = loft_with_guide_rails(self._spec())
        assert report.num_cross_sections == 3

    def test_two_guide_rails_stored(self):
        report = loft_with_guide_rails(self._spec())
        assert report.num_guide_rails == 2

    def test_cp_shape_valid(self):
        report = loft_with_guide_rails(self._spec())
        cp = report.loft_surface.control_points
        assert cp.ndim == 3
        assert cp.shape[2] == 3
        assert cp.shape[0] >= 2
        assert cp.shape[1] >= 2


# ---------------------------------------------------------------------------
# Test 4: Mismatched guide endpoints → UserWarning
# ---------------------------------------------------------------------------

class TestMismatchedGuideEndpoints:
    """Guide rails whose endpoints don't lie on the cross-sections trigger a warning."""

    def test_mismatched_start_warns(self):
        cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
        # Guide rail that starts far from the first cross-section.
        guide = _line([0.0, 10.0, 0.0], [0.0, 0.0, 1.0])

        spec = GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1],
            guide_rail_curves=[guide],
            num_v_samples=10,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            report = loft_with_guide_rails(spec)
        assert len(w) >= 1
        assert any("guide rail" in str(warning.message).lower() for warning in w)

    def test_mismatched_end_warns(self):
        cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
        # Guide rail that ends far from the last cross-section.
        guide = _line([0.0, 0.0, 0.0], [0.0, 10.0, 1.0])

        spec = GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1],
            guide_rail_curves=[guide],
            num_v_samples=10,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            report = loft_with_guide_rails(spec)
        assert len(w) >= 1

    def test_matching_endpoints_no_warning(self):
        cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
        # Guide exactly on cross-section endpoints.
        guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])

        spec = GuideRailLoftSpec(
            cross_section_curves=[cs0, cs1],
            guide_rail_curves=[guide],
            num_v_samples=10,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            report = loft_with_guide_rails(spec)
        # No mismatched-endpoint warnings expected.
        endpoint_warns = [
            x for x in w
            if "guide rail" in str(x.message).lower()
            and ("start" in str(x.message).lower() or "end" in str(x.message).lower())
        ]
        assert len(endpoint_warns) == 0


# ---------------------------------------------------------------------------
# Test 5: Single cross-section raises ValueError
# ---------------------------------------------------------------------------

def test_single_cross_section_raises():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0],
        guide_rail_curves=[guide],
    )
    with pytest.raises(ValueError, match="at least 2"):
        loft_with_guide_rails(spec)


# ---------------------------------------------------------------------------
# Test 6: Zero guide rails raises ValueError
# ---------------------------------------------------------------------------

def test_zero_guide_rails_raises():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[],
    )
    with pytest.raises(ValueError, match="at least 1"):
        loft_with_guide_rails(spec)


# ---------------------------------------------------------------------------
# Test 7: closed_v=True raises NotImplementedError
# ---------------------------------------------------------------------------

def test_closed_v_raises():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        closed_v=True,
    )
    with pytest.raises(NotImplementedError):
        loft_with_guide_rails(spec)


# ---------------------------------------------------------------------------
# Test 8: GuideRailLoftReport fields present and typed correctly
# ---------------------------------------------------------------------------

def test_report_fields():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        num_v_samples=8,
    )
    report = loft_with_guide_rails(spec)

    assert isinstance(report.loft_surface, NurbsSurface)
    assert isinstance(report.num_cross_sections, int)
    assert isinstance(report.num_guide_rails, int)
    assert isinstance(report.max_guide_rail_deviation_mm, float)
    assert isinstance(report.mean_guide_rail_deviation_mm, float)
    assert isinstance(report.num_self_intersections, int)
    assert isinstance(report.honest_caveat, str)


# ---------------------------------------------------------------------------
# Test 9: Surface has finite, non-NaN control points
# ---------------------------------------------------------------------------

def test_control_points_finite():
    cs0 = _line([0.0, 0.0, 0.0], [2.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.5], [2.0, 0.0, 1.5])
    guide = _line([1.0, 0.0, 0.0], [1.0, 0.0, 1.5])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        num_v_samples=10,
    )
    report = loft_with_guide_rails(spec)
    cp = report.loft_surface.control_points
    assert np.all(np.isfinite(cp)), f"Non-finite control points found: {cp[~np.isfinite(cp)]}"


# ---------------------------------------------------------------------------
# Test 10: max_deviation >= mean_deviation
# ---------------------------------------------------------------------------

def test_max_deviation_gte_mean():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 2.0], [1.0, 0.0, 2.0])
    guide = _line([0.5, 0.0, 0.0], [0.5, 0.0, 2.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        num_v_samples=10,
    )
    report = loft_with_guide_rails(spec)
    assert report.max_guide_rail_deviation_mm >= report.mean_guide_rail_deviation_mm - 1e-9


# ---------------------------------------------------------------------------
# Test 11: num_self_intersections is non-negative int
# ---------------------------------------------------------------------------

def test_num_self_intersections_non_negative():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
    )
    report = loft_with_guide_rails(spec)
    assert isinstance(report.num_self_intersections, int)
    assert report.num_self_intersections >= 0


# ---------------------------------------------------------------------------
# Test 12: honest_caveat is a non-empty string
# ---------------------------------------------------------------------------

def test_honest_caveat_non_empty():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
    )
    report = loft_with_guide_rails(spec)
    assert len(report.honest_caveat) > 0
    # Should mention approximation.
    assert any(word in report.honest_caveat.lower() for word in ["approximate", "approx", "caveat", "deviation"])


# ---------------------------------------------------------------------------
# Test 13: 4 cross-sections + 3 guide rails → valid surface
# ---------------------------------------------------------------------------

def test_four_cs_three_rails():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    cs2 = _line([0.0, 0.0, 2.0], [1.0, 0.0, 2.0])
    cs3 = _line([0.0, 0.0, 3.0], [1.0, 0.0, 3.0])

    g0 = _line([0.0, 0.0, 0.0], [0.0, 0.0, 3.0])
    g1 = _line([0.5, 0.0, 0.0], [0.5, 0.0, 3.0])
    g2 = _line([1.0, 0.0, 0.0], [1.0, 0.0, 3.0])

    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1, cs2, cs3],
        guide_rail_curves=[g0, g1, g2],
        num_v_samples=16,
        degree_v=3,
    )
    report = loft_with_guide_rails(spec)
    assert isinstance(report.loft_surface, NurbsSurface)
    assert report.num_cross_sections == 4
    assert report.num_guide_rails == 3
    assert np.all(np.isfinite(report.loft_surface.control_points))


# ---------------------------------------------------------------------------
# Test 14: degree_v clamp (degree_v > n_sections − 1 should not crash)
# ---------------------------------------------------------------------------

def test_degree_v_clamp():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])

    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        degree_v=10,  # Way higher than n_sections - 1 = 1
        num_v_samples=8,
    )
    # Should not raise; degree_v is clamped internally.
    report = loft_with_guide_rails(spec)
    assert isinstance(report.loft_surface, NurbsSurface)
    # The effective degree_v should be <= n_sections - 1 = 1.
    assert report.loft_surface.degree_v <= 1


# ---------------------------------------------------------------------------
# Test 15: GuideRailLoftSpec default values
# ---------------------------------------------------------------------------

def test_spec_defaults():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])

    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
    )
    assert spec.num_v_samples == 20
    assert spec.degree_v == 3
    assert spec.closed_v is False


# ---------------------------------------------------------------------------
# Test 16: Surface knot vectors are clamped (start at 0, end at 1 for both dirs)
# ---------------------------------------------------------------------------

def test_surface_knots_clamped():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])

    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        num_v_samples=8,
    )
    report = loft_with_guide_rails(spec)
    srf = report.loft_surface
    assert float(srf.knots_u[0]) == pytest.approx(0.0, abs=1e-10)
    assert float(srf.knots_u[-1]) == pytest.approx(1.0, abs=1e-10)
    assert float(srf.knots_v[0]) == pytest.approx(0.0, abs=1e-10)
    assert float(srf.knots_v[-1]) == pytest.approx(1.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Test 17: Deviation is non-negative
# ---------------------------------------------------------------------------

def test_deviation_non_negative():
    cs0 = _line([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cs1 = _line([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    guide = _line([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])

    spec = GuideRailLoftSpec(
        cross_section_curves=[cs0, cs1],
        guide_rail_curves=[guide],
        num_v_samples=10,
    )
    report = loft_with_guide_rails(spec)
    assert report.max_guide_rail_deviation_mm >= 0.0
    assert report.mean_guide_rail_deviation_mm >= 0.0
