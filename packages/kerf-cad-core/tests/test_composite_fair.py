"""
Tests for kerf_cad_core.geom.composite_fair
============================================
NURBS-FAIR-COMPOSITE-CURVE — global curvature-variance fairing.

Coverage (10 tests across 4 groups):
  1. 3-segment kink composite → curvature variance halved (≥50% reduction).
  2. Already-faired (smooth arc) → variance does not increase.
  3. Endpoint preservation → both endpoints within 1e-6 after fairing.
  4. Single-curve composite → consistent result (no crash, endpoints pinned).
  5. CompositeFairResult dataclass fields present and typed correctly.
  6. Non-destructive: original NurbsCurve objects not mutated.
  7. Empty composite → returns empty result without crash.
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor, curve_derivative
from kerf_cad_core.geom.composite_fair import (
    CompositeFairResult,
    fair_composite,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamped_knots(n_cp: int, degree: int = 3) -> np.ndarray:
    """Clamped knot vector for n_cp control points at given degree."""
    p = degree
    n_inner = n_cp - p - 1
    if n_inner <= 0:
        inner = np.array([], dtype=float)
    else:
        inner = np.linspace(0.0, 1.0, n_inner + 2)[1:-1]
    return np.concatenate([np.zeros(p + 1), inner, np.ones(p + 1)])


def _make_segment(cps: np.ndarray, degree: int = 3) -> NurbsCurve:
    return NurbsCurve(
        degree=degree,
        control_points=cps.astype(float),
        knots=_clamped_knots(len(cps), degree),
    )


def _kink_composite() -> list:
    """3-segment composite with deliberate kinks (sharp tangent changes at seams).

    Designed so curvature variance is large and concentrated at seam regions.
    """
    # Segment 0: cubic, sharp upward bend at second-to-last CP
    cps0 = np.array([
        [0.0,  0.0, 0.0],
        [0.3,  0.0, 0.0],
        [0.7,  0.8, 0.0],   # large upward deviation creates kink at seam
        [1.0,  0.0, 0.0],
    ], dtype=float)

    # Segment 1: cubic, strong zigzag kink
    cps1 = np.array([
        [1.0,  0.0, 0.0],
        [1.2, -0.9, 0.0],   # large downward kink
        [1.8,  0.9, 0.0],   # large upward kink
        [2.0,  0.0, 0.0],
    ], dtype=float)

    # Segment 2: cubic, downward kink at start
    cps2 = np.array([
        [2.0,  0.0, 0.0],
        [2.3, -0.8, 0.0],   # sharp downward kink
        [2.7,  0.0, 0.0],
        [3.0,  0.0, 0.0],
    ], dtype=float)

    return [_make_segment(cps0), _make_segment(cps1), _make_segment(cps2)]


def _smooth_arc_composite() -> list:
    """2-segment composite approximating a quarter-circle arc (very smooth).

    Already well-faired; fairing should not degrade it.
    """
    k = 4.0 / 3.0 * (math.sqrt(2) - 1)  # standard NURBS arc factor

    cps0 = np.array([
        [1.0, 0.0, 0.0],
        [1.0,   k, 0.0],
        [k,   1.0, 0.0],
        [math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0],
    ], dtype=float)

    mid = np.array([math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0])
    cps1 = np.array([
        mid,
        mid + np.array([-math.sin(math.pi / 4), math.cos(math.pi / 4), 0.0]) * k,
        np.array([k, 1.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
    ], dtype=float)

    return [_make_segment(cps0), _make_segment(cps1)]


def _composite_variance_total(curves: list, n_samples: int = 100) -> float:
    """Sum of curvature variance over all segments."""
    total = 0.0
    for curve in curves:
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        us = np.linspace(u0, u1, n_samples)
        kappas = []
        for u in us:
            d1 = curve_derivative(curve, float(u), order=1)
            d2 = curve_derivative(curve, float(u), order=2)
            dim = len(d1)
            if dim == 2:
                cross = abs(float(d1[0]) * float(d2[1]) - float(d1[1]) * float(d2[0]))
            else:
                d1_3 = np.zeros(3); d2_3 = np.zeros(3)
                d1_3[:min(dim, 3)] = d1[:min(dim, 3)]
                d2_3[:min(dim, 3)] = d2[:min(dim, 3)]
                cross = float(np.linalg.norm(np.cross(d1_3, d2_3)))
            speed = float(np.linalg.norm(d1))
            kappas.append(0.0 if speed < 1e-14 else cross / speed ** 3)
        total += float(np.var(np.array(kappas)))
    return total


# ---------------------------------------------------------------------------
# Group 1: Depth-bar — kink composite variance halved
# ---------------------------------------------------------------------------

class TestKinkCompositeVarianceReduction:
    """3-segment kink composite → curvature variance halved (≥50% reduction)."""

    def test_variance_halved(self):
        curves = _kink_composite()
        var_before = _composite_variance_total(curves)
        result = fair_composite(curves, max_iter=100, lambda_smoothness=1.0)
        var_after = result.curvature_variance_after
        reduction = (var_before - var_after) / (var_before + 1e-300)
        assert reduction >= 0.50, (
            f"Variance reduction {reduction:.1%} < 50% "
            f"(before={var_before:.6g}, after={var_after:.6g})"
        )

    def test_result_fields(self):
        curves = _kink_composite()
        result = fair_composite(curves, max_iter=50)
        assert isinstance(result, CompositeFairResult)
        assert isinstance(result.faired_curves, list)
        assert len(result.faired_curves) == 3
        assert isinstance(result.curvature_variance_before, float)
        assert isinstance(result.curvature_variance_after, float)
        assert isinstance(result.iterations, int)
        assert isinstance(result.converged, bool)
        assert isinstance(result.endpoint_error, float)
        assert result.iterations >= 1
        assert result.curvature_variance_before >= 0.0
        assert result.curvature_variance_after >= 0.0

    def test_variance_after_matches_computed(self):
        """result.curvature_variance_after agrees with direct measurement."""
        curves = _kink_composite()
        result = fair_composite(curves, max_iter=50)
        direct = _composite_variance_total(result.faired_curves)
        # Allow small discrepancy (different internal vs external sample counts).
        assert abs(result.curvature_variance_after - direct) < max(direct * 0.3, 1e-10)


# ---------------------------------------------------------------------------
# Group 2: Already-faired (smooth arc) → no degradation
# ---------------------------------------------------------------------------

class TestAlreadyFaired:
    """A smooth arc composite must not become worse after fairing."""

    def test_variance_does_not_increase(self):
        curves = _smooth_arc_composite()
        var_before = _composite_variance_total(curves)
        result = fair_composite(curves, max_iter=50)
        assert result.curvature_variance_after <= var_before + 1e-6, (
            f"Fairing degraded smooth arc: before={var_before:.6g}, "
            f"after={result.curvature_variance_after:.6g}"
        )


# ---------------------------------------------------------------------------
# Group 3: Endpoint preservation
# ---------------------------------------------------------------------------

class TestEndpointPreservation:
    """Both global endpoints must be preserved within 1e-6."""

    def test_start_endpoint_preserved(self):
        curves = _kink_composite()
        orig_start = curves[0].control_points[0].copy()
        result = fair_composite(curves, max_iter=50)
        faired_start = result.faired_curves[0].control_points[0]
        err = float(np.linalg.norm(faired_start - orig_start))
        assert err <= 1e-6, f"Start endpoint displaced by {err:.2e} > 1e-6"

    def test_end_endpoint_preserved(self):
        curves = _kink_composite()
        orig_end = curves[-1].control_points[-1].copy()
        result = fair_composite(curves, max_iter=50)
        faired_end = result.faired_curves[-1].control_points[-1]
        err = float(np.linalg.norm(faired_end - orig_end))
        assert err <= 1e-6, f"End endpoint displaced by {err:.2e} > 1e-6"

    def test_endpoint_error_field_matches(self):
        curves = _kink_composite()
        orig_start = curves[0].control_points[0].copy()
        orig_end   = curves[-1].control_points[-1].copy()
        result = fair_composite(curves, max_iter=50)
        actual_err = max(
            float(np.linalg.norm(result.faired_curves[0].control_points[0] - orig_start)),
            float(np.linalg.norm(result.faired_curves[-1].control_points[-1] - orig_end)),
        )
        assert abs(result.endpoint_error - actual_err) < 1e-12


# ---------------------------------------------------------------------------
# Group 4: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Single-curve composite, empty input, non-destructive."""

    def test_single_curve_no_crash(self):
        cps = np.array([
            [0.0,  0.0, 0.0],
            [0.3,  0.5, 0.0],
            [0.7, -0.5, 0.0],
            [1.0,  0.0, 0.0],
        ], dtype=float)
        curve = _make_segment(cps)
        result = fair_composite([curve], max_iter=20)
        assert len(result.faired_curves) == 1
        assert result.endpoint_error <= 1e-6

    def test_empty_composite(self):
        result = fair_composite([])
        assert result.faired_curves == []
        assert result.iterations == 0
        assert result.converged is True

    def test_non_destructive(self):
        """Original NurbsCurve objects must not be mutated."""
        curves = _kink_composite()
        originals = [c.control_points.copy() for c in curves]
        _ = fair_composite(curves, max_iter=30)
        for i, curve in enumerate(curves):
            assert np.allclose(curve.control_points, originals[i]), (
                f"Segment {i} original was mutated"
            )
