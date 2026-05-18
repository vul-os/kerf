"""test_mask.py — pytest suite for kerf_silicon.mask (fracturing + OPC stub).

Run with:
    PYTHONPATH=packages/kerf-core/src:packages/kerf-silicon/src \
        python3 -m pytest packages/kerf-silicon/tests/test_mask.py -x
"""

from __future__ import annotations

import math
import pytest

from kerf_silicon.mask import fracture_polygon, Trapezoid, apply_opc, Shape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rect_polygon(x: float, y: float, w: float, h: float):
    """Return the four vertices of a rectangle as (x,y) tuples (CCW)."""
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _total_area(traps: list[Trapezoid]) -> float:
    return sum(t.area for t in traps)


def _poly_area_shoelace(poly) -> float:
    n = len(poly)
    s = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(0.5 * s)


# ---------------------------------------------------------------------------
# Fracture tests
# ---------------------------------------------------------------------------

class TestFractureRectangle:
    """A simple rectangle should fracture to exactly one trapezoid."""

    def test_single_trapezoid(self):
        poly = _rect_polygon(0, 0, 500, 300)
        traps = fracture_polygon(poly)
        assert len(traps) == 1, (
            f"Rectangle should produce 1 trapezoid, got {len(traps)}"
        )

    def test_is_rectangle(self):
        """The trapezoid's top and bottom edges should have identical x-bounds."""
        poly = _rect_polygon(0, 0, 500, 300)
        traps = fracture_polygon(poly)
        t = traps[0]
        assert abs(t.x_lo_bot - t.x_lo_top) < 1e-9
        assert abs(t.x_hi_bot - t.x_hi_top) < 1e-9

    def test_correct_bounds(self):
        poly = _rect_polygon(100, 200, 500, 300)
        traps = fracture_polygon(poly)
        t = traps[0]
        assert abs(t.x_lo_bot - 100) < 1e-9
        assert abs(t.x_hi_bot - 600) < 1e-9
        assert abs(t.y_bot - 200) < 1e-9
        assert abs(t.y_top - 500) < 1e-9

    def test_area_preserved(self):
        poly = _rect_polygon(0, 0, 500, 300)
        traps = fracture_polygon(poly)
        expected = _poly_area_shoelace(poly)
        assert abs(_total_area(traps) - expected) < 1e-9


class TestFractureLShape:
    """An L-shaped polygon must fracture into >= 2 trapezoids."""

    def _l_shape(self):
        """
        L-shape (all units in nm):

            (0,1000)---------(500,1000)
                |                |
                |                |
            (0,500)---(500,500)  |
                        |        |
                        |        |
                    (500,0)---(1000,0)
                         NOT QUITE — easier variant:

        Vertices (CCW):
            (0,0), (500,0), (500,500), (1000,500), (1000,1000), (0,1000)
        """
        return [
            (0, 0),
            (500, 0),
            (500, 500),
            (1000, 500),
            (1000, 1000),
            (0, 1000),
        ]

    def test_minimum_two_trapezoids(self):
        traps = fracture_polygon(self._l_shape())
        assert len(traps) >= 2, (
            f"L-shape should fracture to >= 2 trapezoids, got {len(traps)}"
        )

    def test_area_preserved(self):
        poly = self._l_shape()
        expected = _poly_area_shoelace(poly)
        traps = fracture_polygon(poly)
        got = _total_area(traps)
        assert abs(got - expected) < 1e-9, (
            f"Area mismatch: expected {expected}, got {got}"
        )


class TestFractureAreaPreservation:
    """Area of all trapezoids must match the original polygon within 1e-9."""

    def _triangle(self):
        return [(0, 0), (1000, 0), (500, 800)]

    def _hexagon(self):
        """Regular hexagon approximated as 6-gon, in nm."""
        r = 500.0
        return [
            (r * math.cos(math.radians(60 * k)),
             r * math.sin(math.radians(60 * k)))
            for k in range(6)
        ]

    def test_triangle_area(self):
        poly = self._triangle()
        expected = _poly_area_shoelace(poly)
        got = _total_area(fracture_polygon(poly))
        assert abs(got - expected) < 1e-9

    def test_hexagon_area(self):
        poly = self._hexagon()
        expected = _poly_area_shoelace(poly)
        got = _total_area(fracture_polygon(poly))
        assert abs(got - expected) < 1e-9

    def test_large_rectangle_area(self):
        """100 µm × 200 µm rectangle, units in nm."""
        poly = _rect_polygon(0, 0, 100_000, 200_000)
        expected = _poly_area_shoelace(poly)
        got = _total_area(fracture_polygon(poly))
        assert abs(got - expected) < 1e-9


class TestMaxDimSubdivision:
    """Shapes wider than max_dim_nm should be subdivided."""

    def test_wide_rect_subdivided(self):
        poly = _rect_polygon(0, 0, 300_000, 50_000)
        traps = fracture_polygon(poly, max_dim_nm=100_000)
        assert len(traps) >= 3

    def test_area_preserved_after_subdivision(self):
        poly = _rect_polygon(0, 0, 300_000, 50_000)
        expected = _poly_area_shoelace(poly)
        got = _total_area(fracture_polygon(poly, max_dim_nm=100_000))
        assert abs(got - expected) < 1e-9


# ---------------------------------------------------------------------------
# OPC tests
# ---------------------------------------------------------------------------

class TestOpcHammerheads:
    """OPC on a 100 nm × 1 µm wire must add exactly 2 hammerheads."""

    def _wire_shape(self) -> Shape:
        # 100 nm wide, 1000 nm long, horizontal
        return Shape(x=0, y=0, width=1000, height=100, tag="original")

    def test_two_hammerheads_added(self):
        wire = self._wire_shape()
        dr = {
            "min_width_nm": 150,         # wire (100 nm) is narrower → qualifies
            "hammerhead_extension_nm": 25,
            "hammerhead_width_nm": 160,
        }
        result = apply_opc([wire], dr)
        hammerheads = [s for s in result if s.tag == "hammerhead"]
        assert len(hammerheads) == 2, (
            f"Expected 2 hammerheads for 100nm×1µm wire, got {len(hammerheads)}"
        )

    def test_hammerheads_are_at_wire_ends(self):
        wire = self._wire_shape()
        dr = {
            "min_width_nm": 150,
            "hammerhead_extension_nm": 25,
            "hammerhead_width_nm": 160,
        }
        result = apply_opc([wire], dr)
        hh = [s for s in result if s.tag == "hammerhead"]
        # Left hammerhead should be to the left of x=0
        left_hh = [s for s in hh if s.x < 0]
        right_hh = [s for s in hh if s.x >= wire.x2]
        assert len(left_hh) == 1
        assert len(right_hh) == 1

    def test_vertical_wire_two_hammerheads(self):
        # 100 nm wide, 1000 nm tall, vertical
        wire = Shape(x=0, y=0, width=100, height=1000, tag="original")
        dr = {
            "min_width_nm": 150,
            "hammerhead_extension_nm": 25,
            "hammerhead_width_nm": 160,
        }
        result = apply_opc([wire], dr)
        hh = [s for s in result if s.tag == "hammerhead"]
        assert len(hh) == 2

    def test_wide_shape_no_hammerheads(self):
        """A square (aspect ratio 1:1) should not get hammerheads."""
        square = Shape(x=0, y=0, width=1000, height=1000, tag="original")
        dr = {"min_width_nm": 1500}
        result = apply_opc([square], dr)
        hh = [s for s in result if s.tag == "hammerhead"]
        assert len(hh) == 0


class TestOpcSerifs:
    """OPC on an L-shaped compound produces serifs at inside corners."""

    def _l_shape_as_rects(self) -> list[Shape]:
        """L-shape decomposed into two rectangles (all dimensions in nm):
            Bottom rect: x=0..1000, y=0..500 (1µm × 500nm)
            Left rect:   x=0..500,  y=500..1000 (500nm × 500nm)
        """
        return [
            Shape(x=0, y=0, width=1000, height=500, tag="original"),
            Shape(x=0, y=500, width=500, height=500, tag="original"),
        ]

    def test_inside_corner_gets_serif(self):
        shapes = self._l_shape_as_rects()
        dr = {"serif_size_nm": 30}
        result = apply_opc(shapes, dr)
        serifs = [s for s in result if s.tag == "serif"]
        assert len(serifs) >= 1, (
            "L-shape should have at least 1 serif at the inside corner"
        )

    def test_serif_size_matches_design_rule(self):
        shapes = self._l_shape_as_rects()
        serif_size = 40.0
        dr = {"serif_size_nm": serif_size}
        result = apply_opc(shapes, dr)
        serifs = [s for s in result if s.tag == "serif"]
        for s in serifs:
            assert abs(s.width - serif_size) < 1e-9
            assert abs(s.height - serif_size) < 1e-9

    def test_unit_square_no_inside_corners(self):
        """A simple rectangle has no inside corners, so no serifs."""
        rect = Shape(x=0, y=0, width=1000, height=1000, tag="original")
        # Use large min_width_nm so no hammerheads either
        dr = {"min_width_nm": 2000, "serif_size_nm": 30}
        result = apply_opc([rect], dr)
        serifs = [s for s in result if s.tag == "serif"]
        assert len(serifs) == 0


class TestOpcRetainsOriginals:
    """apply_opc must return the original shapes as the first elements."""

    def test_originals_first(self):
        shapes = [
            Shape(x=0, y=0, width=1000, height=1000, tag="original"),
            Shape(x=2000, y=0, width=1000, height=1000, tag="original"),
        ]
        result = apply_opc(shapes, {"min_width_nm": 2000})
        for i, s in enumerate(shapes):
            assert result[i] is s

    def test_empty_input(self):
        result = apply_opc([])
        assert result == []
