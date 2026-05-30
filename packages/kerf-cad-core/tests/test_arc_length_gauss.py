"""
Tests for arc_length_gauss.py — Gauss-Legendre adaptive arc-length computation.

Analytical oracles
------------------
1. Straight line NURBS (0,0,0)→(1,0,0)          → length = 1.0 within 1e-12
2. Full unit-circle NURBS                         → length = 2π within 1e-9
3. Bounded error: cubic spline rel_tol=1e-6 agrees with rel_tol=1e-12 within 1e-6
4. Round-trip arc_length_parametrize: at s = L/4 on circle, t ≈ 0.25 ± 1e-6
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    make_circle_nurbs,
    make_line_nurbs,
)
from kerf_cad_core.geom.arc_length_gauss import (
    arc_length_precise,
    arc_length_parametrize,
    reparametrize_arclength,
)
from kerf_cad_core.geom.curve_toolkit import interp_curve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_line_3d(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS from p0 to p1."""
    ctrl = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=ctrl, knots=knots)


def _make_cubic_spline() -> NurbsCurve:
    """Non-trivial degree-3 spline through a sine-wave point cloud."""
    xs = np.linspace(0.0, 2.0 * math.pi, 30)
    pts = np.column_stack([xs, np.sin(xs), np.zeros_like(xs)])
    return interp_curve(pts, degree=3)


# ---------------------------------------------------------------------------
# Test 1: Straight line length = 1.0 within 1e-12
# ---------------------------------------------------------------------------

class TestStraightLine:
    def test_unit_line_length(self):
        """NURBS line (0,0,0)→(1,0,0): arc_length_precise == 1.0 within 1e-12."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        length = arc_length_precise(curve, rel_tol=1e-9, abs_tol=1e-12)
        assert abs(length - 1.0) < 1e-12, (
            f"Expected 1.0, got {length:.15e}  (err={abs(length - 1.0):.2e})"
        )

    def test_diagonal_line_3d(self):
        """Line (0,0,0)→(3,4,0): expected length 5.0 within 1e-12."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([3.0, 4.0, 0.0]),
        )
        length = arc_length_precise(curve, rel_tol=1e-9, abs_tol=1e-12)
        assert abs(length - 5.0) < 1e-12, (
            f"Expected 5.0, got {length:.15e}  (err={abs(length - 5.0):.2e})"
        )

    def test_partial_line_interval(self):
        """Half of unit line: length = 0.5."""
        curve = _make_line_3d([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        mid = 0.5 * (u0 + u1)
        length = arc_length_precise(curve, t_start=u0, t_end=mid)
        assert abs(length - 0.5) < 1e-12, f"Expected 0.5, got {length}"


# ---------------------------------------------------------------------------
# Test 2: Full unit circle = 2π within 1e-9
# ---------------------------------------------------------------------------

class TestUnitCircle:
    def test_full_circle_length(self):
        """Full unit-circle NURBS: arc_length_precise == 2π within 1e-9."""
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
        )
        length = arc_length_precise(curve, rel_tol=1e-9, abs_tol=1e-12)
        expected = 2.0 * math.pi
        assert abs(length - expected) < 1e-9, (
            f"Expected 2π={expected:.12f}, got {length:.12f}  "
            f"(err={abs(length - expected):.2e})"
        )

    def test_radius_2_circle_length(self):
        """Circle with radius 2: length == 4π within 1e-9."""
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=2.0,
        )
        length = arc_length_precise(curve, rel_tol=1e-9, abs_tol=1e-12)
        expected = 4.0 * math.pi
        assert abs(length - expected) < 1e-9, (
            f"Expected 4π={expected:.12f}, got {length:.12f}"
        )


# ---------------------------------------------------------------------------
# Test 3: Bounded error — rel_tol=1e-6 agrees with rel_tol=1e-12 within 1e-6
# ---------------------------------------------------------------------------

class TestBoundedError:
    def test_cubic_spline_tolerance_contract(self):
        """
        For a cubic spline, arc_length_precise(rel_tol=1e-6) and
        arc_length_precise(rel_tol=1e-12) should agree within 1e-6
        (i.e. the tighter computation serves as a reference, and the looser
        one stays within its declared tolerance).
        """
        curve = _make_cubic_spline()
        L_tight = arc_length_precise(curve, rel_tol=1e-12, abs_tol=1e-15, max_depth=25)
        L_loose = arc_length_precise(curve, rel_tol=1e-6,  abs_tol=1e-9,  max_depth=25)
        rel_err = abs(L_tight - L_loose) / max(L_tight, 1e-300)
        assert rel_err < 1e-6, (
            f"Bounded-error contract violated: "
            f"tight={L_tight:.10f}, loose={L_loose:.10f}, rel_err={rel_err:.2e}"
        )

    def test_max_depth_guard(self):
        """max_depth=0 still returns a finite non-negative value (no crash)."""
        curve = _make_cubic_spline()
        length = arc_length_precise(curve, rel_tol=1e-9, abs_tol=1e-12, max_depth=0)
        assert math.isfinite(length)
        assert length >= 0.0


# ---------------------------------------------------------------------------
# Test 4: arc_length_parametrize round-trip on circle
#         At s = L/4, t should be ≈ 0.25 ± 1e-6 (quarter of the full range)
# ---------------------------------------------------------------------------

class TestArcLengthParametrize:
    def test_circle_quarter_roundtrip(self):
        """
        For the full unit-circle NURBS with parameter domain [0, 1]:
        arc_length_parametrize(circle, n=100) returns t(s = L/4) ≈ 0.25 ± 1e-6.

        The circle has a uniform-speed parametrisation (make_circle_nurbs uses
        the standard 9-point rational construction whose GL quadrature converges
        uniformly), so equal arc-length ↔ equal parameter should hold.
        """
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
        )
        table = arc_length_parametrize(curve, n_samples=100, rel_tol=1e-9)
        assert table.shape == (101, 2), f"Expected shape (101, 2), got {table.shape}"

        L_total = table[-1, 0]
        s_quarter = L_total / 4.0

        # Interpolate to find t at s = L/4.
        t_quarter = float(np.interp(s_quarter, table[:, 0], table[:, 1]))

        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        t_expected = u0 + 0.25 * (u1 - u0)

        assert abs(t_quarter - t_expected) < 1e-6, (
            f"Expected t≈{t_expected:.8f} at s=L/4, got {t_quarter:.8f} "
            f"(err={abs(t_quarter - t_expected):.2e})"
        )

    def test_table_monotone_and_bounds(self):
        """Table s and t values must be monotonically non-decreasing."""
        curve = _make_cubic_spline()
        table = arc_length_parametrize(curve, n_samples=50, rel_tol=1e-9)
        s_vals = table[:, 0]
        t_vals = table[:, 1]
        assert np.all(np.diff(s_vals) >= -1e-12), "s values not monotone"
        assert np.all(np.diff(t_vals) >= -1e-12), "t values not monotone"

    def test_table_endpoints(self):
        """First row is (0, t_start) and last row is (L, t_end)."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([5.0, 0.0, 0.0]),
        )
        table = arc_length_parametrize(curve, n_samples=10, rel_tol=1e-9)
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])

        assert abs(table[0, 0]) < 1e-12, "First s should be 0"
        assert abs(table[0, 1] - u0) < 1e-12, "First t should be t_start"
        assert abs(table[-1, 1] - u1) < 1e-12, "Last t should be t_end"

    def test_line_arc_length_table_consistency(self):
        """
        For a unit line, at n_samples=10, every t value should equal s/L
        (uniform speed on a line) within 1e-10.
        """
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        table = arc_length_parametrize(curve, n_samples=10, rel_tol=1e-9)
        # For a unit line: t == s (parameter is proportional to arc length)
        for s, t in table:
            assert abs(t - s) < 1e-9, (
                f"On unit line, expected t≈s, got s={s:.8f} t={t:.8f}"
            )


# ---------------------------------------------------------------------------
# LLM tool registration smoke test (import-only, no kerf_chat in test env)
# ---------------------------------------------------------------------------

class TestModuleImports:
    def test_public_symbols_importable(self):
        """All three public functions are importable from arc_length_gauss."""
        from kerf_cad_core.geom.arc_length_gauss import (
            arc_length_precise,
            arc_length_parametrize,
            reparametrize_arclength,
        )
        assert callable(arc_length_precise)
        assert callable(arc_length_parametrize)
        assert callable(reparametrize_arclength)

    def test_geom_package_exports(self):
        """arc_length_precise and arc_length_parametrize_gauss visible in geom package."""
        import kerf_cad_core.geom as _geom
        assert hasattr(_geom, "arc_length_precise"), (
            "arc_length_precise not exported from kerf_cad_core.geom"
        )
        assert hasattr(_geom, "arc_length_parametrize_gauss"), (
            "arc_length_parametrize_gauss not exported from kerf_cad_core.geom"
        )
        assert _geom.arc_length_precise is arc_length_precise
