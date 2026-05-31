"""Hermetic tests for kerf_cad_core.geom.edge_chamfer_variable.

BREP-EDGE-CHAMFER-VARIABLE: variable-width chamfer strip along a 2D edge curve.
Reference: Piegl & Tiller §10.5 (Variable offsets); Mortenson §9.3 (Edge blends).

All tests are self-contained — no network, no OCCT, no external fixtures.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.edge_chamfer_variable import (
    ChamferVariableResult,
    ChamferVariableSpec,
    generate_variable_chamfer,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _straight_edge(length_mm: float = 100.0, num_pts: int = 2) -> list:
    """Return a straight horizontal edge from (0,0) to (length_mm, 0)."""
    xs = np.linspace(0.0, length_mm, num_pts)
    return [(float(x), 0.0) for x in xs]


def _diagonal_edge(length_mm: float = 100.0) -> list:
    """Return a 45-degree edge from (0,0) to (L/sqrt2, L/sqrt2)."""
    c = length_mm / math.sqrt(2.0)
    return [(0.0, 0.0), (c, c)]


def _l_shaped_edge() -> list:
    """Return an L-shaped edge: (0,0) → (50,0) → (50,50)."""
    return [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)]


# ---------------------------------------------------------------------------
# 1. Spec validation
# ---------------------------------------------------------------------------


class TestChamferVariableSpecValidation:
    def test_too_few_points(self):
        with pytest.raises(ValueError, match="at least 2 points"):
            ChamferVariableSpec(
                edge_curve_2d=[(0.0, 0.0)],
                width_start_mm=1.0,
                width_end_mm=2.0,
            )

    def test_negative_width_start(self):
        with pytest.raises(ValueError, match="width_start_mm must be non-negative"):
            ChamferVariableSpec(
                edge_curve_2d=_straight_edge(),
                width_start_mm=-1.0,
                width_end_mm=2.0,
            )

    def test_negative_width_end(self):
        with pytest.raises(ValueError, match="width_end_mm must be non-negative"):
            ChamferVariableSpec(
                edge_curve_2d=_straight_edge(),
                width_start_mm=2.0,
                width_end_mm=-0.5,
            )

    def test_both_widths_zero(self):
        with pytest.raises(ValueError, match="at least one.*strictly positive"):
            ChamferVariableSpec(
                edge_curve_2d=_straight_edge(),
                width_start_mm=0.0,
                width_end_mm=0.0,
            )

    def test_num_samples_too_small(self):
        with pytest.raises(ValueError, match="num_samples must be in"):
            ChamferVariableSpec(
                edge_curve_2d=_straight_edge(),
                width_start_mm=1.0,
                width_end_mm=1.0,
                num_samples=1,
            )

    def test_num_samples_too_large(self):
        with pytest.raises(ValueError, match="num_samples must be in"):
            ChamferVariableSpec(
                edge_curve_2d=_straight_edge(),
                width_start_mm=1.0,
                width_end_mm=1.0,
                num_samples=100001,
            )

    def test_valid_spec_zero_width_start(self):
        """width_start=0 is allowed as long as width_end > 0."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(),
            width_start_mm=0.0,
            width_end_mm=3.0,
        )
        assert spec.width_start_mm == 0.0
        assert spec.width_end_mm == 3.0


# ---------------------------------------------------------------------------
# 2. Constant chamfer (w_start == w_end)
# ---------------------------------------------------------------------------


class TestConstantChamfer:
    def test_constant_offset_magnitude(self):
        """Constant 2 mm chamfer on a 100 mm straight horizontal edge.

        Each inner / outer point must be exactly 1 mm (= w/2) away from
        the centreline (y=0) in the ±y direction.
        """
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=2.0,
            width_end_mm=2.0,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        n = spec.num_samples
        inner = result.chamfer_strip_points[:n]
        outer = result.chamfer_strip_points[n:]

        for p in inner:
            # inner offset along CCW normal = +y for horizontal edge
            assert abs(abs(p[1]) - 1.0) < 1e-9, f"inner y={p[1]} not ±1.0"

        for p in outer:
            assert abs(abs(p[1]) - 1.0) < 1e-9, f"outer y={p[1]} not ±1.0"

    def test_inner_outer_opposite_sides(self):
        """For a horizontal edge the inner and outer offsets are on opposite y-sides."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=4.0,
            width_end_mm=4.0,
            num_samples=20,
        )
        result = generate_variable_chamfer(spec)
        n = spec.num_samples
        inner = result.chamfer_strip_points[:n]
        outer = result.chamfer_strip_points[n:]

        for p_i, p_o in zip(inner, outer):
            # They should be on opposite y-sides
            assert p_i[1] * p_o[1] < 0.0 or (abs(p_i[1]) < 1e-9 and abs(p_o[1]) < 1e-9), (
                f"inner y={p_i[1]} and outer y={p_o[1]} not on opposite sides"
            )

    def test_constant_stats(self):
        """min, max, average all equal width for a constant chamfer."""
        w = 3.0
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(50.0),
            width_start_mm=w,
            width_end_mm=w,
            num_samples=30,
        )
        result = generate_variable_chamfer(spec)
        assert abs(result.min_chamfer_width_mm - w) < 1e-9
        assert abs(result.max_chamfer_width_mm - w) < 1e-9
        assert abs(result.average_width_mm - w) < 1e-9

    def test_z_is_zero_for_2d_input(self):
        """All strip points must have z=0.0 for 2D input."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=2.0,
            width_end_mm=2.0,
            num_samples=10,
        )
        result = generate_variable_chamfer(spec)
        for pt in result.chamfer_strip_points:
            assert pt[2] == 0.0, f"z != 0 for point {pt}"


# ---------------------------------------------------------------------------
# 3. Linear ramp (w_start != w_end)
# ---------------------------------------------------------------------------


class TestLinearRamp:
    def test_midpoint_width_is_mean(self):
        """At t=0.5, w(t) = (w_start + w_end) / 2 — verified within sample spacing.

        With num_samples=1001 (odd), index 500 maps exactly to t=500/1000=0.5
        since t_i = i / (n-1).  So w(t=0.5) = (1+5)/2 = 3; half-width = 1.5.
        """
        w_start = 1.0
        w_end = 5.0
        n = 1001  # odd → index 500 → t = 500/1000 = 0.5 exactly
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=w_start,
            width_end_mm=w_end,
            num_samples=n,
        )
        result = generate_variable_chamfer(spec)
        inner = result.chamfer_strip_points[:n]

        # t[500] = 500 / (1001-1) = 500/1000 = 0.5 exactly
        mid_idx = 500
        expected_half_w = (w_start + w_end) / 2.0 / 2.0  # = 1.5
        actual_half_w = abs(inner[mid_idx][1])
        assert abs(actual_half_w - expected_half_w) < 1e-9, (
            f"midpoint half-width {actual_half_w} != expected {expected_half_w}"
        )

    def test_width_at_zero(self):
        """At t=0 (first sample), the inner offset should be w_start/2."""
        w_start = 2.0
        w_end = 6.0
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=w_start,
            width_end_mm=w_end,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        inner = result.chamfer_strip_points[:spec.num_samples]
        first_y = abs(inner[0][1])
        assert abs(first_y - w_start / 2.0) < 1e-9, (
            f"first inner y={first_y} expected {w_start/2.0}"
        )

    def test_width_at_one(self):
        """At t=1 (last sample), the inner offset should be w_end/2."""
        w_start = 2.0
        w_end = 6.0
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=w_start,
            width_end_mm=w_end,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        inner = result.chamfer_strip_points[:spec.num_samples]
        last_y = abs(inner[-1][1])
        assert abs(last_y - w_end / 2.0) < 1e-9, (
            f"last inner y={last_y} expected {w_end/2.0}"
        )

    def test_average_equals_arithmetic_mean(self):
        """average_width_mm == (w_start + w_end) / 2 for a linear ramp."""
        w_start = 1.0
        w_end = 5.0
        expected_avg = (w_start + w_end) / 2.0
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=w_start,
            width_end_mm=w_end,
            num_samples=1000,  # large sample → average converges
        )
        result = generate_variable_chamfer(spec)
        # For a uniform arc-length param the average of w(t_i) converges to
        # (w_start + w_end)/2 as num_samples → ∞.  With 1000 samples, the
        # error should be < 0.01 mm.
        assert abs(result.average_width_mm - expected_avg) < 0.01, (
            f"average_width {result.average_width_mm} != expected {expected_avg}"
        )

    def test_min_max_stats_ramp_up(self):
        """For a ramp-up chamfer (w_start < w_end): min=w_start, max=w_end."""
        w_start, w_end = 1.0, 5.0
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=w_start,
            width_end_mm=w_end,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        assert abs(result.min_chamfer_width_mm - w_start) < 1e-9
        assert abs(result.max_chamfer_width_mm - w_end) < 1e-9

    def test_min_max_stats_ramp_down(self):
        """For a ramp-down chamfer (w_start > w_end): min=w_end, max=w_start."""
        w_start, w_end = 5.0, 1.0
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=w_start,
            width_end_mm=w_end,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        assert abs(result.min_chamfer_width_mm - w_end) < 1e-9
        assert abs(result.max_chamfer_width_mm - w_start) < 1e-9

    def test_result_has_correct_number_of_points(self):
        """chamfer_strip_points has exactly 2*num_samples entries."""
        n = 37
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=1.0,
            width_end_mm=3.0,
            num_samples=n,
        )
        result = generate_variable_chamfer(spec)
        assert len(result.chamfer_strip_points) == 2 * n


# ---------------------------------------------------------------------------
# 4. Geometric correctness on diagonal / L-shaped edges
# ---------------------------------------------------------------------------


class TestGeometricCorrectness:
    def test_diagonal_inner_outer_separation(self):
        """Inner and outer strip points are separated by ~w(t) on a 45° edge."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_diagonal_edge(100.0),
            width_start_mm=4.0,
            width_end_mm=4.0,
            num_samples=20,
        )
        result = generate_variable_chamfer(spec)
        n = spec.num_samples
        inner = np.array(result.chamfer_strip_points[:n])
        outer = np.array(result.chamfer_strip_points[n:])

        # The distance between corresponding inner and outer points should be w
        w = 4.0
        for i in range(n):
            dist = np.linalg.norm(inner[i, :2] - outer[i, :2])
            assert abs(dist - w) < 1e-9, (
                f"sample {i}: distance {dist:.6f} != {w}"
            )

    def test_strip_points_are_floats(self):
        """All strip point coordinates are Python floats (or numpy float64)."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(10.0),
            width_start_mm=1.0,
            width_end_mm=2.0,
            num_samples=5,
        )
        result = generate_variable_chamfer(spec)
        for pt in result.chamfer_strip_points:
            assert len(pt) == 3
            for coord in pt:
                assert isinstance(coord, (float, np.floating)), (
                    f"coord {coord} is type {type(coord)}"
                )

    def test_l_shaped_edge_num_points(self):
        """L-shaped edge: strip still has 2*num_samples entries."""
        n = 25
        spec = ChamferVariableSpec(
            edge_curve_2d=_l_shaped_edge(),
            width_start_mm=2.0,
            width_end_mm=4.0,
            num_samples=n,
        )
        result = generate_variable_chamfer(spec)
        assert len(result.chamfer_strip_points) == 2 * n

    def test_honest_caveat_present(self):
        """honest_caveat must be a non-empty string."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(50.0),
            width_start_mm=1.0,
            width_end_mm=3.0,
        )
        result = generate_variable_chamfer(spec)
        assert isinstance(result.honest_caveat, str)
        assert len(result.honest_caveat) > 10

    def test_result_type(self):
        """generate_variable_chamfer returns ChamferVariableResult."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=2.0,
            width_end_mm=2.0,
        )
        result = generate_variable_chamfer(spec)
        assert isinstance(result, ChamferVariableResult)


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimum_two_samples(self):
        """num_samples=2 is the minimum allowed; produces 4 strip points."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=1.0,
            width_end_mm=5.0,
            num_samples=2,
        )
        result = generate_variable_chamfer(spec)
        assert len(result.chamfer_strip_points) == 4

    def test_many_samples(self):
        """Large num_samples works without error."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0, num_pts=10),
            width_start_mm=1.0,
            width_end_mm=1.0,
            num_samples=500,
        )
        result = generate_variable_chamfer(spec)
        assert len(result.chamfer_strip_points) == 1000

    def test_width_zero_at_start(self):
        """width_start=0 degenerates the chamfer to a wedge starting from zero width."""
        spec = ChamferVariableSpec(
            edge_curve_2d=_straight_edge(100.0),
            width_start_mm=0.0,
            width_end_mm=4.0,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        # First inner point should be on the edge itself (y=0)
        inner_first = result.chamfer_strip_points[0]
        assert abs(inner_first[1]) < 1e-9, f"inner[0].y={inner_first[1]} != 0"

    def test_polyline_with_dense_points(self):
        """Multi-point polyline resampled correctly."""
        n_pts = 100
        edge = _straight_edge(200.0, num_pts=n_pts)
        spec = ChamferVariableSpec(
            edge_curve_2d=edge,
            width_start_mm=2.0,
            width_end_mm=6.0,
            num_samples=50,
        )
        result = generate_variable_chamfer(spec)
        assert len(result.chamfer_strip_points) == 100
        # Width at midpoint should be ~4 mm (half = 2 mm in y)
        inner = result.chamfer_strip_points[:50]
        mid_y = abs(inner[25][1])
        assert abs(mid_y - 2.0) < 0.05, f"mid inner y={mid_y} expected ~2.0"
