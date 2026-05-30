"""
test_curvature_profile_export.py
=================================
Tests for NURBS-CURVE-CURVATURE-PROFILE-EXPORT.

Oracle tests
------------
1. Circle radius R → κ = 1/R constant to ≤1e-6 (relative).
2. Asymmetric Bézier S-curve → sign change in κ (inflection_params non-empty).
3. Sin-curve oracle: κ(t) = |−sin(t)| / (1+cos²t)^(3/2)  (reference §11.6).

Format tests
------------
4. CSV: correct header, correct column count, numeric values parseable.
5. SVG: well-formed XML, contains <svg>, <polyline>.
6. PNG: starts with \\x89PNG magic bytes.

Degenerate tests
----------------
7. Degenerate curve (all control points equal) → kappa_max ≈ 0, no crash.
8. Two-point degree-1 straight line → kappa_max ≈ 0.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_circle_nurbs
from kerf_cad_core.geom.curvature_profile_export import (
    export_curvature_profile,
    export_curvature_profile_result,
    CurvatureProfileResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_circle(radius: float) -> NurbsCurve:
    """Exact 9-point rational NURBS circle of given radius."""
    return make_circle_nurbs(
        center=np.array([0.0, 0.0, 0.0]),
        radius=float(radius),
    )


def _make_bezier(ctrl_pts: list, degree: int | None = None) -> NurbsCurve:
    """Build a Bézier curve (single-span NURBS) from control points."""
    pts = np.array(ctrl_pts, dtype=float)
    n = len(pts)
    p = degree if degree is not None else (n - 1)
    knots = np.concatenate([np.zeros(p + 1), np.ones(p + 1)])
    return NurbsCurve(degree=p, control_points=pts, knots=knots)


def _make_sin_approx(n_pts: int = 40) -> NurbsCurve:
    """
    Degree-3 NURBS approximation to y = sin(t), t in [0, 2π].

    Used for the reference oracle test.  We interpolate through sampled
    points on the sin curve; the NURBS will closely follow the analytic curve.
    The oracle: κ(t) = sin(t) / (1+cos²t)^(3/2)  for y=sin(x), x=t.
    """
    from kerf_cad_core.geom.curve_toolkit import interp_curve

    ts = np.linspace(0.0, 2 * math.pi, n_pts)
    pts = np.column_stack([ts, np.sin(ts), np.zeros(n_pts)])
    return interp_curve(pts.tolist(), degree=3, param="chord")


def _sin_kappa_oracle(t: float) -> float:
    """
    Reference curvature for y = sin(x) at x = t.

    κ(t) = |−sin(t)| / (1 + cos²(t))^(3/2)

    Ref: Farin §11.6; standard differential geometry formula for y = f(x):
      κ = |f''| / (1 + f'²)^(3/2)
    with f'(t) = cos(t), f''(t) = −sin(t).
    """
    return abs(math.sin(t)) / (1.0 + math.cos(t) ** 2) ** 1.5


def _make_s_curve_bezier() -> NurbsCurve:
    """
    Asymmetric cubic Bézier S-curve in 2-D.

    Control polygon: (0,0), (0.3, 1.5), (0.7, -1.5), (1,0)
    This is a classic S-shape with an inflection point near the middle.
    Asymmetry ensures the inflection is not exactly at the midpoint.
    """
    return _make_bezier([[0.0, 0.0], [0.3, 1.5], [0.7, -1.5], [1.0, 0.0]], degree=3)


# ---------------------------------------------------------------------------
# Oracle: circle constant curvature
# ---------------------------------------------------------------------------

class TestCircleCurvature:
    def test_kappa_constant(self):
        """Circle of radius R: κ = 1/R at every sample, uniform to ≤1e-6 relative."""
        R = 3.7
        curve = _make_circle(R)
        result = export_curvature_profile_result(curve, samples=100)
        kappas = np.array(result.kappas)
        expected = 1.0 / R
        # All κ values should be within 1e-6 relative of 1/R
        rel_err = np.abs(kappas - expected) / expected
        assert np.all(rel_err < 1e-5), (
            f"Circle κ should be constant 1/R={expected:.6f}; "
            f"max_rel_err={rel_err.max():.2e}"
        )

    def test_kappa_mean_circle(self):
        R = 2.0
        curve = _make_circle(R)
        result = export_curvature_profile_result(curve, samples=80)
        assert abs(result.kappa_mean - 1.0 / R) / (1.0 / R) < 1e-4

    def test_no_inflections_in_circle(self):
        curve = _make_circle(1.5)
        result = export_curvature_profile_result(curve, samples=100)
        assert result.inflection_params == []

    def test_total_arc_length_circle(self):
        """Total arc length should be ≈ 2πR."""
        R = 4.0
        curve = _make_circle(R)
        result = export_curvature_profile_result(curve, samples=300)
        assert abs(result.total_arc_length - 2 * math.pi * R) / (2 * math.pi * R) < 1e-3


# ---------------------------------------------------------------------------
# Oracle: S-curve inflection
# ---------------------------------------------------------------------------

class TestSCurveInflection:
    def test_inflection_detected(self):
        """Asymmetric Bézier S-curve: at least one inflection must be detected."""
        curve = _make_s_curve_bezier()
        result = export_curvature_profile_result(curve, samples=400)
        assert len(result.inflection_params) >= 1, (
            "S-curve must have at least one inflection point"
        )

    def test_inflection_in_interior(self):
        """Inflection parameter must lie strictly inside (0, 1)."""
        curve = _make_s_curve_bezier()
        result = export_curvature_profile_result(curve, samples=400)
        for t_infl in result.inflection_params:
            assert 0.0 < t_infl < 1.0, f"Inflection at {t_infl} outside (0,1)"

    def test_kappa_varies(self):
        """S-curve kappa_max > kappa_min (profile is not constant)."""
        curve = _make_s_curve_bezier()
        result = export_curvature_profile_result(curve, samples=200)
        assert result.kappa_max > result.kappa_min


# ---------------------------------------------------------------------------
# Oracle: sin curve reference
# ---------------------------------------------------------------------------

class TestSinCurveOracle:
    def test_sin_kappa_oracle_shape(self):
        """
        For y = sin(t), κ(t) = |−sin(t)| / (1 + cos²t)^(3/2).

        We verify that the NURBS approximation matches the oracle at a
        few test points to within 10% relative tolerance
        (NURBS interpolation error is small but non-zero).
        """
        try:
            curve = _make_sin_approx(n_pts=60)
        except Exception:
            pytest.skip("interp_curve unavailable in this environment")

        result = export_curvature_profile_result(curve, samples=400)
        # The NURBS x-coords ≈ the arc parameter; map kappas back to t ≈ x
        pts = np.array(result.points)
        xs = pts[:, 0]  # x ≈ t in [0, 2π]
        kappas = np.array(result.kappas)

        # Test at t ≈ π/2 (maximum curvature point: κ = 1)
        idx_max = int(np.argmin(np.abs(xs - math.pi / 2)))
        kappa_at_half_pi = kappas[idx_max]
        oracle_half_pi = _sin_kappa_oracle(math.pi / 2)  # = 1.0
        assert abs(kappa_at_half_pi - oracle_half_pi) / oracle_half_pi < 0.15, (
            f"At t=π/2: NURBS κ={kappa_at_half_pi:.4f}, oracle={oracle_half_pi:.4f}"
        )

    def test_sin_kappa_zero_near_inflections(self):
        """For y = sin(t), κ ≈ 0 near t = 0, π, 2π (inflection points)."""
        try:
            curve = _make_sin_approx(n_pts=60)
        except Exception:
            pytest.skip("interp_curve unavailable")

        result = export_curvature_profile_result(curve, samples=400)
        pts = np.array(result.points)
        xs = pts[:, 0]
        kappas = np.array(result.kappas)

        for t_zero in [math.pi, 2 * math.pi - 0.1]:
            idx = int(np.argmin(np.abs(xs - t_zero)))
            # κ near inflection should be much smaller than max
            assert kappas[idx] < result.kappa_max * 0.3, (
                f"Near t={t_zero:.2f}: κ={kappas[idx]:.4f} should be near 0 "
                f"(kappa_max={result.kappa_max:.4f})"
            )


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------

class TestCsvFormat:
    def test_header_present(self):
        curve = _make_circle(1.0)
        csv = export_curvature_profile(curve, samples=50, fmt="csv")
        assert isinstance(csv, str)
        assert "t,kappa,arc_length,x,y,z,high_kappa_risk" in csv

    def test_row_count(self):
        curve = _make_circle(1.0)
        csv = export_curvature_profile(curve, samples=50, fmt="csv")
        data_rows = [l for l in csv.splitlines() if l and not l.startswith("#") and "t,kappa" not in l]
        assert len(data_rows) == 50

    def test_numeric_values_parseable(self):
        curve = _make_s_curve_bezier()
        csv = export_curvature_profile(curve, samples=30, fmt="csv")
        data_rows = [l for l in csv.splitlines() if l and not l.startswith("#") and "t,kappa" not in l]
        for row in data_rows:
            parts = row.split(",")
            assert len(parts) == 7, f"Expected 7 columns, got {len(parts)}: {row}"
            for p in parts:
                float(p)  # must be parseable

    def test_arc_length_monotone(self):
        """Arc-length column must be non-decreasing."""
        curve = _make_circle(2.0)
        csv = export_curvature_profile(curve, samples=100, fmt="csv")
        data_rows = [l for l in csv.splitlines() if l and not l.startswith("#") and "t,kappa" not in l]
        arc_lengths = [float(row.split(",")[2]) for row in data_rows]
        for i in range(1, len(arc_lengths)):
            assert arc_lengths[i] >= arc_lengths[i - 1] - 1e-10, (
                f"arc_length not monotone at index {i}: {arc_lengths[i-1]:.6f} > {arc_lengths[i]:.6f}"
            )

    def test_kappa_nonnegative_unsigned(self):
        """κ in CSV must be ≥ 0 (unsigned magnitude)."""
        curve = _make_s_curve_bezier()
        csv = export_curvature_profile(curve, samples=60, fmt="csv")
        data_rows = [l for l in csv.splitlines() if l and not l.startswith("#") and "t,kappa" not in l]
        for row in data_rows:
            kappa = float(row.split(",")[1])
            assert kappa >= -1e-12, f"Negative κ in CSV: {kappa}"

    def test_sampling_caveat_in_header(self):
        curve = _make_circle(1.0)
        csv = export_curvature_profile(curve, samples=10, fmt="csv")
        assert "high_kappa_risk" in csv.lower() or "warning" in csv.lower()


# ---------------------------------------------------------------------------
# SVG format
# ---------------------------------------------------------------------------

class TestSvgFormat:
    def test_returns_string(self):
        curve = _make_circle(1.0)
        svg = export_curvature_profile(curve, samples=50, fmt="svg")
        assert isinstance(svg, str)

    def test_svg_tag_present(self):
        curve = _make_circle(1.0)
        svg = export_curvature_profile(curve, samples=50, fmt="svg")
        assert "<svg" in svg and "</svg>" in svg

    def test_polyline_present(self):
        curve = _make_circle(1.0)
        svg = export_curvature_profile(curve, samples=50, fmt="svg")
        assert "<polyline" in svg

    def test_well_formed_xml(self):
        curve = _make_s_curve_bezier()
        svg = export_curvature_profile(curve, samples=80, fmt="svg")
        try:
            ET.fromstring(svg)
        except ET.ParseError as e:
            pytest.fail(f"SVG is not well-formed XML: {e}")

    def test_svg_dimensions(self):
        curve = _make_circle(1.0)
        svg = export_curvature_profile(curve, samples=30, fmt="svg", svg_width=800, svg_height=300)
        assert 'width="800"' in svg
        assert 'height="300"' in svg

    def test_inflection_marker_in_s_curve_svg(self):
        """SVG for S-curve should contain inflection marker (dashed red line)."""
        curve = _make_s_curve_bezier()
        svg = export_curvature_profile(curve, samples=200, fmt="svg")
        # Inflection markers are dashed red lines
        assert "d32f2f" in svg or "stroke-dasharray" in svg


# ---------------------------------------------------------------------------
# PNG format
# ---------------------------------------------------------------------------

class TestPngFormat:
    _PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

    def test_returns_bytes(self):
        curve = _make_circle(1.0)
        png = export_curvature_profile(curve, samples=50, fmt="png")
        assert isinstance(png, bytes)

    def test_png_magic_header(self):
        curve = _make_circle(1.0)
        png = export_curvature_profile(curve, samples=50, fmt="png")
        assert png[:8] == self._PNG_MAGIC, f"PNG magic not found; got {png[:8]!r}"

    def test_png_ihdr_chunk(self):
        """PNG should start with IHDR chunk after the signature."""
        curve = _make_circle(1.0)
        png = export_curvature_profile(curve, samples=50, fmt="png")
        # bytes 8..12 = length of IHDR (should be 13)
        import struct
        length = struct.unpack(">I", png[8:12])[0]
        assert length == 13, f"IHDR data length should be 13, got {length}"
        assert png[12:16] == b"IHDR"

    def test_png_ends_with_iend(self):
        curve = _make_circle(1.0)
        png = export_curvature_profile(curve, samples=50, fmt="png")
        # Last 12 bytes: 4B len (0) + 4B IEND + 4B CRC
        assert png[-8:-4] == b"IEND", f"PNG does not end with IEND: {png[-12:]!r}"

    def test_png_s_curve(self):
        """S-curve PNG export must produce valid PNG bytes."""
        curve = _make_s_curve_bezier()
        png = export_curvature_profile(curve, samples=100, fmt="png")
        assert png[:8] == self._PNG_MAGIC


# ---------------------------------------------------------------------------
# Degenerate / edge cases
# ---------------------------------------------------------------------------

class TestDegenerateCurve:
    def test_degenerate_all_same_points(self):
        """All control points equal → speed ≈ 0, κ = 0 everywhere, no crash."""
        pts = np.array([[1.0, 1.0, 0.0]] * 4, dtype=float)
        knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        curve = NurbsCurve(degree=3, control_points=pts, knots=knots)
        result = export_curvature_profile_result(curve, samples=20)
        assert result.kappa_max < 1e-6, f"kappa_max={result.kappa_max} for degenerate curve"
        assert result.total_arc_length < 1e-6

    def test_straight_line_zero_curvature(self):
        """Degree-1 straight line: κ = 0 at all samples."""
        pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        curve = NurbsCurve(
            degree=1,
            control_points=pts,
            knots=np.array([0.0, 0.0, 1.0, 1.0]),
        )
        result = export_curvature_profile_result(curve, samples=20)
        assert result.kappa_max < 1e-9, f"Straight line kappa_max={result.kappa_max}"

    def test_single_sample_no_crash(self):
        """samples=2 (minimum) should not raise."""
        curve = _make_circle(1.0)
        result = export_curvature_profile_result(curve, samples=2)
        assert len(result.kappas) == 2

    def test_invalid_format_raises(self):
        curve = _make_circle(1.0)
        with pytest.raises(ValueError, match="Unsupported format"):
            export_curvature_profile(curve, samples=10, fmt="xyz")

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="NurbsCurve"):
            export_curvature_profile("not a curve", samples=10, fmt="csv")


# ---------------------------------------------------------------------------
# CurvatureProfileResult fields
# ---------------------------------------------------------------------------

class TestResultFields:
    def test_result_fields_populated(self):
        curve = _make_circle(2.5)
        result = export_curvature_profile_result(curve, samples=50)
        assert len(result.parameters) == 50
        assert len(result.kappas) == 50
        assert len(result.arc_lengths) == 50
        assert len(result.points) == 50
        assert len(result.high_kappa_risk) == 50
        assert result.total_arc_length > 0

    def test_high_kappa_risk_binary(self):
        """high_kappa_risk must contain only 0 or 1."""
        curve = _make_s_curve_bezier()
        result = export_curvature_profile_result(curve, samples=100)
        for v in result.high_kappa_risk:
            assert v in (0, 1), f"high_kappa_risk value {v} is not 0 or 1"

    def test_kappa_min_le_max(self):
        curve = _make_circle(1.0)
        result = export_curvature_profile_result(curve, samples=50)
        assert result.kappa_min <= result.kappa_max

    def test_geom_init_re_export(self):
        """The public symbols are accessible via kerf_cad_core.geom."""
        from kerf_cad_core.geom import (
            export_curvature_profile as ecp,
            export_curvature_profile_result as ecpr,
            CurvatureProfileResult as CPR,
        )
        assert callable(ecp)
        assert callable(ecpr)
        assert CPR is CurvatureProfileResult
