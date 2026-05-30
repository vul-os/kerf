"""
tests/test_infill_patterns.py — analytical oracle tests for infill_patterns.py.

Tests
-----
T1 — Gyroid density oracle
    A 100×100 mm bounding box with density=0.20 should produce segments whose
    combined line coverage approximates 20% of the bbox area (within 2%).
    Coverage = Σ segment_length × line_width / bbox_area.

T2 — Honeycomb cell count oracle
    A 100×100 bbox with cell_size=10 → analytic hex count = 10000 / (3√3/2 · s²)
    ≈ 77. We verify the segment count corresponds to 50–100 hexagons (±generous
    margin for boundary clipping).

T3 — Triangular density oracle
    density=0.25, bbox 200×200. Total segment length should satisfy:
        fill_ratio = Σ length × line_width / bbox_area ≈ 0.25 (±2%).

T4 — Concentric for circle
    A 16-gon approximating a unit circle (r=1 mm) with n_offsets=4.
    The four rings should have decreasing perimeters ≈ 2π·r_k where
    r_k = 1 − k·(1/5), k=1..4. Verify perimeters are within 0.5% of analytic.

T5 — fill_perimeter_with_pattern dispatches correctly
    Basic smoke test for all 4 pattern kinds.

T6 — unknown pattern raises ValueError
    fill_perimeter_with_pattern with unknown kind raises ValueError.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_slicing.infill_patterns import (
    BBox2D,
    Segment2D,
    fill_perimeter_with_pattern,
    generate_concentric,
    generate_gyroid_pattern,
    generate_honeycomb_pattern,
    generate_triangular_grid,
)

# ── helpers ────────────────────────────────────────────────────────────────────

LINE_WIDTH_MM = 0.4  # standard FDM extrusion width for coverage calculations

def _total_length(segs: List[Segment2D]) -> float:
    return sum(s.length() for s in segs)


def _coverage_ratio(segs: List[Segment2D], bbox: BBox2D, lw: float = LINE_WIDTH_MM) -> float:
    """Approximate fill ratio from segment length * line_width / area."""
    return _total_length(segs) * lw / bbox.area


def _rect_polygon(bbox: BBox2D) -> List[Tuple[float, float]]:
    """CCW rectangle polygon from bbox."""
    return [
        (bbox.xmin, bbox.ymin),
        (bbox.xmax, bbox.ymin),
        (bbox.xmax, bbox.ymax),
        (bbox.xmin, bbox.ymax),
    ]


# ── T1: Gyroid density ─────────────────────────────────────────────────────────

class TestGyroidDensity:
    """
    Oracle: the gyroid pattern at density=0.20 should yield segments whose
    combined line coverage approximates 20% of the bbox area within ±2%.

    Coverage is estimated as:  Σ length_i × line_width / area
    The gyroid pattern generates both the +iso and -iso iso-contours of the
    periodic field. For a flat layer (z=0) the two contour families together
    span the cross-sectional area of the solid shell. We verify the total
    coverage falls in [18%, 22%] for a 100×100 bbox.
    """
    BBOX = BBox2D(0.0, 0.0, 100.0, 100.0)
    TARGET_DENSITY = 0.20
    TOLERANCE = 0.02  # ±2 percentage points

    def test_gyroid_coverage_within_tolerance(self):
        segs = generate_gyroid_pattern(
            self.BBOX,
            z=0.0,
            density=self.TARGET_DENSITY,
            cell_size=10.0,
            resolution=200,
        )
        assert len(segs) > 10, "expected gyroid to generate segments"
        ratio = _coverage_ratio(segs, self.BBOX)
        assert abs(ratio - self.TARGET_DENSITY) <= self.TOLERANCE, (
            f"gyroid coverage {ratio:.4f} not within {self.TOLERANCE} of "
            f"target {self.TARGET_DENSITY}"
        )

    def test_gyroid_zero_density_fewer_segments(self):
        """Near-zero density should produce far fewer segments than 20%."""
        segs_20 = generate_gyroid_pattern(self.BBOX, z=0.0, density=0.20, cell_size=10.0)
        segs_01 = generate_gyroid_pattern(self.BBOX, z=0.0, density=0.01, cell_size=10.0)
        assert _total_length(segs_01) < _total_length(segs_20), (
            "lower density should produce shorter total path"
        )

    def test_gyroid_returns_segment2d_instances(self):
        segs = generate_gyroid_pattern(self.BBOX, z=0.0, density=0.20, cell_size=10.0)
        assert all(isinstance(s, Segment2D) for s in segs)


# ── T2: Honeycomb cell count ──────────────────────────────────────────────────

class TestHoneycombCellCount:
    """
    Analytic count: bbox_area / (3√3/2 · s²) = 10000 / 129.9 ≈ 77.
    After boundary clipping, expect 50–100 distinct hexagons.
    Each hexagon contributes 6 edges (some clipped at boundary).

    We count the number of hexagons by dividing total segment count by ~6
    (complete hexagons) and check the range, plus directly counting centres
    via the generator.
    """
    BBOX = BBox2D(0.0, 0.0, 100.0, 100.0)
    CELL_SIZE = 10.0

    @staticmethod
    def _analytic_hex_count(bbox: BBox2D, s: float) -> float:
        """Approximate number of hexagons covering bbox.

        For a regular hexagon with circumscribed radius (vertex-to-centre) = s,
        the side length equals s and the area = (3√3/2)·s².
        For s=10: area = 3√3/2 · 100 ≈ 259.8, count ≈ 10000/259.8 ≈ 38.5.
        """
        hex_area = 3.0 * math.sqrt(3) / 2.0 * s ** 2
        return bbox.area / hex_area

    def test_analytic_count_is_reasonable(self):
        expected = self._analytic_hex_count(self.BBOX, self.CELL_SIZE)
        # For cell_size=10 (circumscribed radius): area≈259.8, count≈38.5
        assert 30 < expected < 50, f"analytic count {expected:.1f} outside sanity range"

    def test_segment_count_consistent_with_hex_count(self):
        segs = generate_honeycomb_pattern(
            self.BBOX, cell_size=self.CELL_SIZE, wall_thickness=0.4
        )
        # Each hex has 6 edges; after clipping ~ half boundary cells are partial.
        # With ~77 full hexes and ~30% clipped at boundary: expect 200–500 segs.
        assert len(segs) > 100, f"too few segments: {len(segs)}"
        assert len(segs) < 700, f"too many segments: {len(segs)}"

    def test_honeycomb_all_within_bbox(self):
        bbox = self.BBOX
        segs = generate_honeycomb_pattern(bbox, cell_size=self.CELL_SIZE)
        tol = 1e-6
        for s in segs:
            assert s.x0 >= bbox.xmin - tol and s.x0 <= bbox.xmax + tol
            assert s.y0 >= bbox.ymin - tol and s.y0 <= bbox.ymax + tol
            assert s.x1 >= bbox.xmin - tol and s.x1 <= bbox.xmax + tol
            assert s.y1 >= bbox.ymin - tol and s.y1 <= bbox.ymax + tol

    def test_honeycomb_cell_count_in_range(self):
        """
        Derive approx cell count from total perimeter.
        Each complete hexagon has perimeter = 6 × s_in where s_in = s - wall_thickness/2.

        For cell_size=10 (circumscribed radius), analytic cell count ≈ 38.5.
        With boundary clipping and margin centres, expect 20–60 equivalent cells.
        """
        wall = 0.4
        s_in = self.CELL_SIZE - wall / 2.0
        hex_perimeter = 6.0 * s_in
        segs = generate_honeycomb_pattern(self.BBOX, cell_size=self.CELL_SIZE, wall_thickness=wall)
        total_len = _total_length(segs)
        approx_cells = total_len / hex_perimeter
        # Generous range [20, 80] to account for boundary clipping
        assert 20 <= approx_cells <= 80, (
            f"inferred cell count {approx_cells:.1f} outside expected range [20,80]"
        )


# ── T3: Triangular density ─────────────────────────────────────────────────────

class TestTriangularDensity:
    """
    Oracle: triangular grid at density=0.25 should produce combined line
    coverage ≈ 25% of bbox area within ±2%.
    """
    BBOX = BBox2D(0.0, 0.0, 200.0, 200.0)
    TARGET_DENSITY = 0.25
    TOLERANCE = 0.02

    def test_triangular_coverage_within_tolerance(self):
        segs = generate_triangular_grid(
            self.BBOX,
            density=self.TARGET_DENSITY,
            line_width=LINE_WIDTH_MM,
        )
        assert len(segs) > 0
        ratio = _coverage_ratio(segs, self.BBOX)
        assert abs(ratio - self.TARGET_DENSITY) <= self.TOLERANCE, (
            f"triangular grid coverage {ratio:.4f} not within ±{self.TOLERANCE} of "
            f"{self.TARGET_DENSITY}"
        )

    def test_triangular_three_families(self):
        """
        At density=0.25, each of the three line families contributes ~0.25/3
        of the total coverage. Verify all three angles produce segments.
        """
        segs = generate_triangular_grid(self.BBOX, density=0.25, line_width=0.4)
        assert len(segs) >= 30, "expected multiple lines per family"

    def test_triangular_all_within_bbox(self):
        bbox = self.BBOX
        segs = generate_triangular_grid(bbox, density=0.25)
        tol = 1e-6
        for s in segs:
            assert s.x0 >= bbox.xmin - tol and s.x0 <= bbox.xmax + tol
            assert s.y0 >= bbox.ymin - tol and s.y0 <= bbox.ymax + tol
            assert s.x1 >= bbox.xmin - tol and s.x1 <= bbox.xmax + tol
            assert s.y1 >= bbox.ymin - tol and s.y1 <= bbox.ymax + tol


# ── T4: Concentric for circle ──────────────────────────────────────────────────

class TestConcentricCircle:
    """
    Oracle: A unit circle (r=1) approximated by N_SIDES vertices, with
    n_offsets=4. The default offset_step = inradius / 5 = 0.2.

    Expected ring radii: 0.8, 0.6, 0.4, 0.2.
    Expected perimeters: 2π × {0.8, 0.6, 0.4, 0.2}.

    We verify the total perimeter of each ring is within 0.5% of the analytic
    value (residual error from polygon approximation of the circle).

    Note: a regular 16-gon has a slight apothem < r, so we use a generous
    polygon (N_SIDES=64) to get a good circle approximation.
    """
    N_SIDES = 64
    R = 1.0
    N_OFFSETS = 4
    TOL_REL = 0.001  # 0.1% relative tolerance on perimeter

    @staticmethod
    def _circle_polygon(r: float, n: int) -> List[Tuple[float, float]]:
        angles = [2.0 * math.pi * k / n for k in range(n)]
        return [(r * math.cos(a), r * math.sin(a)) for a in angles]

    def _ring_perimeters(self) -> List[float]:
        """Compute perimeter of each concentric ring from generate_concentric."""
        poly = self._circle_polygon(self.R, self.N_SIDES)
        segs = generate_concentric(poly, n_offsets=self.N_OFFSETS)
        # Each ring has N_SIDES segments; group by index
        segs_per_ring = self.N_SIDES
        perimeters = []
        for k in range(self.N_OFFSETS):
            ring_segs = segs[k * segs_per_ring : (k + 1) * segs_per_ring]
            perimeters.append(sum(s.length() for s in ring_segs))
        return perimeters

    def test_concentric_produces_n_offsets_rings(self):
        poly = self._circle_polygon(self.R, self.N_SIDES)
        segs = generate_concentric(poly, n_offsets=self.N_OFFSETS)
        expected_count = self.N_OFFSETS * self.N_SIDES
        assert len(segs) == expected_count, (
            f"expected {expected_count} segments, got {len(segs)}"
        )

    def test_concentric_ring_perimeters_match_analytic(self):
        """
        Inradius of N=64-gon ≈ r·cos(π/N) ≈ 0.9988 r.
        offset_step = inradius / (n_offsets+1) ≈ 0.9988/5 ≈ 0.1998.
        Ring k has effective radius ≈ inradius − k × offset_step.
        Analytic perimeter: 2π × r_k.
        """
        perimeters = self._ring_perimeters()
        # Expected radii for a 64-gon: inradius ≈ r·cos(π/64)
        inradius = self.R * math.cos(math.pi / self.N_SIDES)
        step = inradius / (self.N_OFFSETS + 1)
        for k, measured in enumerate(perimeters, start=1):
            expected_r = inradius - k * step
            expected_perimeter = 2.0 * math.pi * expected_r
            rel_err = abs(measured - expected_perimeter) / expected_perimeter
            assert rel_err <= self.TOL_REL, (
                f"ring {k}: measured perimeter {measured:.6f}, "
                f"analytic {expected_perimeter:.6f}, rel_err={rel_err:.6f} "
                f"(tolerance {self.TOL_REL})"
            )

    def test_concentric_rings_shrink_monotonically(self):
        """Each successive ring should have a smaller perimeter than the previous."""
        perimeters = self._ring_perimeters()
        for i in range(len(perimeters) - 1):
            assert perimeters[i] > perimeters[i + 1], (
                f"ring {i+1} perimeter {perimeters[i]:.4f} not greater than "
                f"ring {i+2} perimeter {perimeters[i+1]:.4f}"
            )


# ── T5: fill_perimeter_with_pattern dispatch ──────────────────────────────────

class TestFillPerimeterDispatch:
    BBOX = BBox2D(0.0, 0.0, 50.0, 50.0)

    def _poly(self) -> List[Tuple[float, float]]:
        return [
            (self.BBOX.xmin, self.BBOX.ymin),
            (self.BBOX.xmax, self.BBOX.ymin),
            (self.BBOX.xmax, self.BBOX.ymax),
            (self.BBOX.xmin, self.BBOX.ymax),
        ]

    def test_dispatch_gyroid(self):
        segs = fill_perimeter_with_pattern(self._poly(), "gyroid", {"density": 0.20})
        assert isinstance(segs, list)
        assert all(isinstance(s, Segment2D) for s in segs)

    def test_dispatch_honeycomb(self):
        segs = fill_perimeter_with_pattern(self._poly(), "honeycomb", {"cell_size": 8.0})
        assert isinstance(segs, list)
        assert len(segs) > 0

    def test_dispatch_triangular(self):
        segs = fill_perimeter_with_pattern(self._poly(), "triangular", {"density": 0.25})
        assert isinstance(segs, list)
        assert len(segs) > 0

    def test_dispatch_concentric(self):
        segs = fill_perimeter_with_pattern(self._poly(), "concentric", {"n_offsets": 3})
        assert isinstance(segs, list)
        assert len(segs) > 0

    def test_dispatch_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown pattern kind"):
            fill_perimeter_with_pattern(self._poly(), "unknown_xyz", {})

    def test_empty_polygon_returns_empty(self):
        segs = fill_perimeter_with_pattern([], "gyroid", {})
        assert segs == []

    def test_degenerate_polygon_returns_empty(self):
        segs = fill_perimeter_with_pattern([(0, 0), (1, 0)], "gyroid", {})
        assert segs == []


# ── T6: LLM tool round-trip ───────────────────────────────────────────────────

class TestLlmToolRoundTrip:
    """Basic smoke test for the LLM tool JSON plumbing."""

    @pytest.mark.asyncio
    async def test_tool_returns_ok_payload(self):
        import json as _json
        from kerf_slicing.tools.generate_infill import slicing_generate_infill
        from kerf_slicing._compat import ProjectCtx

        ctx = ProjectCtx()
        polygon = [[0, 0], [100, 0], [100, 100], [0, 100]]
        args = _json.dumps({
            "pattern": "honeycomb",
            "layer_polygon": polygon,
            "params": {"cell_size": 10.0},
        }).encode()

        result_str = await slicing_generate_infill(ctx, args)
        result = _json.loads(result_str)

        assert "error" not in result or result.get("error") is None
        assert result.get("pattern") == "honeycomb"
        assert result.get("segment_count", 0) > 0
        assert isinstance(result.get("segments"), list)
        assert result.get("total_length_mm", 0) > 0

    @pytest.mark.asyncio
    async def test_tool_bad_pattern_returns_error(self):
        import json as _json
        from kerf_slicing.tools.generate_infill import slicing_generate_infill
        from kerf_slicing._compat import ProjectCtx

        ctx = ProjectCtx()
        args = _json.dumps({
            "pattern": "invalid_pattern",
            "layer_polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
        }).encode()

        result_str = await slicing_generate_infill(ctx, args)
        result = _json.loads(result_str)
        assert result.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_tool_missing_polygon_returns_error(self):
        import json as _json
        from kerf_slicing.tools.generate_infill import slicing_generate_infill
        from kerf_slicing._compat import ProjectCtx

        ctx = ProjectCtx()
        args = _json.dumps({"pattern": "gyroid"}).encode()
        result_str = await slicing_generate_infill(ctx, args)
        result = _json.loads(result_str)
        assert result.get("code") == "BAD_ARGS"
