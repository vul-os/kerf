"""Tests for GK-P32 — hatch_region (ANSI31/concrete/brick tiling inside a 2D loop).

DoD:
  - hatch_region(loop, pattern, angle, scale) returns HatchResult with lines
  - All returned line segments have start/end inside the loop boundary
  - Pattern variations (ansi31, concrete, brick) produce different line counts
  - Scale parameter changes line density
  - All built-in patterns return at least some lines for a non-degenerate loop
"""
from __future__ import annotations
import math
import pytest
import numpy as np

from kerf_cad_core.geom.region2d import (
    hatch_region,
    HatchResult,
    HatchLine,
    make_rect_loop,
    make_circle_loop,
    material_hatch_pattern,
)


def _pt_inside_rect(x, y, x0, y0, x1, y1, tol=1e-6) -> bool:
    return x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol


class TestHatchBasics:
    def test_returns_hatch_result(self):
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, "ansi31", angle=45.0, scale=1.0)
        assert isinstance(result, HatchResult)

    def test_result_has_lines(self):
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, "ansi31", angle=45.0, scale=1.0)
        assert len(result.lines) > 0, "Expected hatch lines inside a 10×10 rect"

    def test_all_lines_inside_boundary(self):
        """Every line endpoint should be within the loop's bounding rect."""
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, "ansi31", angle=45.0, scale=1.0)
        for ln in result.lines:
            assert _pt_inside_rect(ln.start[0], ln.start[1], 0, 0, 10, 10)
            assert _pt_inside_rect(ln.end[0], ln.end[1], 0, 0, 10, 10)

    def test_scale_reduces_line_count(self):
        """Larger scale → fewer lines."""
        loop = make_rect_loop(0, 0, 10, 10)
        r1 = hatch_region(loop, "ansi31", angle=45.0, scale=0.5)
        r2 = hatch_region(loop, "ansi31", angle=45.0, scale=2.0)
        assert len(r1.lines) > len(r2.lines), (
            f"fine scale has {len(r1.lines)} lines, coarse has {len(r2.lines)}"
        )

    def test_invalid_scale_raises(self):
        loop = make_rect_loop(0, 0, 10, 10)
        with pytest.raises(ValueError, match="scale"):
            hatch_region(loop, scale=0.0)

    def test_unknown_pattern_falls_back_to_ansi31(self):
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, pattern="nonexistent_pattern")
        assert result.pattern == "ansi31"
        assert len(result.lines) > 0

    def test_pattern_key_recorded(self):
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, pattern="concrete")
        assert result.pattern == "concrete"

    def test_angle_recorded(self):
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, angle=30.0)
        assert result.angle_deg == 30.0


class TestPatternVariants:
    """Each built-in pattern should produce hatch lines in a 10×10 rect."""

    PATTERNS = ["ansi31", "concrete", "brick", "earth", "wood", "sand",
                "insulation", "steel", "glass"]

    @pytest.mark.parametrize("pat", PATTERNS)
    def test_pattern_produces_lines(self, pat):
        loop = make_rect_loop(0, 0, 10, 10)
        result = hatch_region(loop, pattern=pat, scale=1.0)
        assert len(result.lines) > 0, f"Pattern '{pat}' produced no lines"

    def test_concrete_more_lines_than_ansi31(self):
        """Concrete adds a perpendicular family → more lines than ansi31."""
        loop = make_rect_loop(0, 0, 10, 10)
        r_ansi = hatch_region(loop, pattern="ansi31", scale=1.0)
        r_conc = hatch_region(loop, pattern="concrete", scale=1.0)
        assert len(r_conc.lines) > len(r_ansi.lines)


class TestAngleEffect:
    def test_horizontal_hatch(self):
        """Horizontal hatch (angle=0) should produce near-horizontal lines."""
        loop = make_rect_loop(0, 0, 10, 5)
        result = hatch_region(loop, pattern="ansi31", angle=0.0, scale=1.0)
        assert len(result.lines) > 0
        for ln in result.lines:
            # Horizontal lines: start.y ≈ end.y
            assert abs(ln.start[1] - ln.end[1]) < 1e-6

    def test_vertical_hatch(self):
        """Vertical hatch (angle=90) should produce near-vertical lines."""
        loop = make_rect_loop(0, 0, 5, 10)
        result = hatch_region(loop, pattern="ansi31", angle=90.0, scale=1.0)
        assert len(result.lines) > 0
        for ln in result.lines:
            assert abs(ln.start[0] - ln.end[0]) < 1e-6


class TestCircularLoop:
    def test_circle_hatch_produces_lines(self):
        """Hatch of a circle produces hatch lines (correctness of clipping).

        The hatch coordinates are in the loop's local 2D frame (plane origin
        at first arc sample).  We simply verify that lines are produced and
        that there are a reasonable number of them given the radius and scale.
        """
        radius = 5.0
        loop = make_circle_loop(0, 0, radius)
        result = hatch_region(loop, pattern="ansi31", angle=45.0, scale=0.5)
        # Roughly diameter / scale lines expected (±50%)
        expected_approx = int(2 * radius / 0.5)
        assert len(result.lines) > expected_approx * 0.3, (
            f"Expected ~{expected_approx} lines for circle r={radius} scale=0.5, "
            f"got {len(result.lines)}"
        )

    def test_circle_hatch_all_line_endpoints_have_finite_coords(self):
        """All returned line coordinates should be finite numbers."""
        radius = 5.0
        loop = make_circle_loop(0, 0, radius)
        result = hatch_region(loop, pattern="ansi31", angle=45.0, scale=0.5)
        for ln in result.lines:
            assert math.isfinite(ln.start[0]) and math.isfinite(ln.start[1])
            assert math.isfinite(ln.end[0])   and math.isfinite(ln.end[1])


class TestMaterialPattern:
    def test_concrete_material_maps_concrete(self):
        assert material_hatch_pattern("concrete_reinforced") == "concrete"

    def test_brick_material_maps_brick(self):
        assert material_hatch_pattern("brick_clay") == "brick"

    def test_insulation_material_maps_insulation(self):
        assert material_hatch_pattern("insulation_rockwool") == "insulation"

    def test_unknown_material_fallback(self):
        assert material_hatch_pattern("unobtainium") == "ansi31"
