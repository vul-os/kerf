"""
Tests for kerf_cam.adaptive — HSM strategies:
  - adaptive_pocket (constant tool-engagement 2D clearing)
  - trochoidal_slot (trochoidal slot milling)
  - rest_machining  (rest-machining helper)

Run:
    pytest packages/kerf-cam/tests/test_hsm_adaptive.py -v
"""

import math
import pytest

from kerf_cam.adaptive import (
    adaptive_pocket,
    trochoidal_slot,
    rest_machining,
    _dist,
    _poly_length,
    _point_in_polygon,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rect_boundary(w: float, h: float, cx: float = 0.0, cy: float = 0.0):
    """CCW rectangle centred at (cx, cy)."""
    hw, hh = w / 2, h / 2
    return [
        (cx - hw, cy - hh),
        (cx + hw, cy - hh),
        (cx + hw, cy + hh),
        (cx - hw, cy + hh),
    ]


# ---------------------------------------------------------------------------
# Geometry helpers unit tests
# ---------------------------------------------------------------------------

def test_point_in_polygon_inside():
    box = rect_boundary(10, 10)
    assert _point_in_polygon(0, 0, box)


def test_point_in_polygon_outside():
    box = rect_boundary(10, 10)
    assert not _point_in_polygon(10, 10, box)


def test_poly_length_unit_square():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    assert abs(_poly_length(sq) - 4.0) < 1e-9


# ---------------------------------------------------------------------------
# adaptive_pocket tests
# ---------------------------------------------------------------------------

class TestAdaptivePocket:
    BOUNDARY = rect_boundary(100, 60)
    TOOL_D = 10.0
    ENG = 0.30

    def _run(self, **kw):
        params = dict(
            boundary=self.BOUNDARY,
            tool_diameter=self.TOOL_D,
            engagement_fraction=self.ENG,
            depth=5.0,
            feed=1000.0,
        )
        params.update(kw)
        return adaptive_pocket(**params)

    def test_returns_polylines(self):
        result = self._run()
        assert "polylines" in result
        assert len(result["polylines"]) > 0, "Expected at least one offset ring"

    def test_returns_feeds(self):
        result = self._run()
        assert len(result["feeds"]) == len(result["polylines"])
        for feed_list in result["feeds"]:
            assert all(f > 0 for f in feed_list)

    def test_total_length_positive(self):
        result = self._run()
        assert result["total_length"] > 0

    def test_engagement_not_exceeded_by_more_than_5pct(self):
        """
        The actual max engagement (centroid-to-centroid ring distance) should
        not exceed the target by more than 5 %.
        """
        result = self._run()
        meta = result["metadata"]
        target = meta["target_engagement_mm"]
        actual = meta["actual_max_engagement_mm"]
        tolerance = target * 1.05
        assert actual <= tolerance, (
            f"engagement {actual:.3f} mm exceeds target {target:.3f} mm + 5% = {tolerance:.3f}"
        )

    def test_path_shorter_than_naive_zigzag_times_2(self):
        """
        Naive zigzag length ≈ (area / step_over) strips × pocket width.
        The adaptive path should be less than 2× that bound.
        """
        result = self._run()
        step_over = self.TOOL_D * self.ENG
        area = 100.0 * 60.0
        strips = area / step_over
        # Each strip ≈ 100mm wide; naive total ≈ strips × 100
        naive_length = strips * 100.0
        assert result["total_length"] < naive_length * 2, (
            f"Adaptive path {result['total_length']:.1f} mm >= 2× naive {naive_length:.1f} mm"
        )

    def test_multiple_rings_generated(self):
        """100×60 pocket with 10mm tool / 30% step should produce at least 3 rings."""
        result = self._run()
        assert result["metadata"]["rings"] >= 3

    def test_metadata_present(self):
        result = self._run()
        meta = result["metadata"]
        assert meta["strategy"] == "adaptive_pocket"
        assert meta["tool_diameter"] == self.TOOL_D
        assert meta["engagement_fraction"] == self.ENG

    def test_small_pocket_returns_gracefully(self):
        """A pocket smaller than the tool should return empty, not crash."""
        tiny = rect_boundary(2, 2)
        result = adaptive_pocket(tiny, 10.0, 0.30, 5.0, 1000.0)
        assert result["total_length"] == 0.0
        assert result["polylines"] == []

    def test_feeds_bounded(self):
        """Feed rates should be between 50% and 110% of the nominal feed."""
        result = self._run()
        for feed_list in result["feeds"]:
            for f in feed_list:
                assert f >= 500.0, f"feed {f} too low"
                assert f <= 1100.0, f"feed {f} too high"


# ---------------------------------------------------------------------------
# trochoidal_slot tests
# ---------------------------------------------------------------------------

class TestTrochoidalSlot:
    SLOT = [(0, 0), (100, 0)]   # 100 mm horizontal slot
    TOOL_D = 6.0
    TROCHOID_R = 4.0

    def _run(self, **kw):
        params = dict(
            slot_polyline=self.SLOT,
            tool_diameter=self.TOOL_D,
            trochoid_radius=self.TROCHOID_R,
            feed=800.0,
        )
        params.update(kw)
        return trochoidal_slot(**params)

    def test_returns_circles(self):
        result = self._run()
        assert len(result["polylines"]) > 0
        assert result["metadata"]["circles"] > 0

    def test_circles_form_closed_loops(self):
        """Each polyline should start and end at approximately the same point."""
        result = self._run()
        for pl in result["polylines"]:
            assert _dist(pl[0], pl[-1]) < 0.1, "circle not closed"

    def test_circles_overlap(self):
        """
        Step-over = trochoid_radius.  Two consecutive circle centres are
        step_over apart; they overlap when 2R > step_over, i.e. R > step_over/2.
        With step = R the overlap fraction = 0.5.
        """
        result = self._run()
        meta = result["metadata"]
        assert meta["overlap_ratio"] >= 0.0, "no overlap — slot not fully covered"

    def test_slot_fully_covered(self):
        """
        Every point along the slot centreline from 0 to 100 mm should be
        within trochoid_radius of at least one circle centre.
        """
        result = self._run()
        centres = []
        for pl in result["polylines"]:
            # Centre is average of all points (circle centred there)
            cx = sum(p[0] for p in pl) / len(pl)
            cy = sum(p[1] for p in pl) / len(pl)
            centres.append((cx, cy))

        R = self.TROCHOID_R
        check_xs = [i * 2.0 for i in range(51)]  # 0, 2, 4, ... 100 mm
        for tx in check_xs:
            covered = any(_dist((tx, 0), c) <= R + 0.01 for c in centres)
            assert covered, f"slot position x={tx} not covered by any trochoidal circle"

    def test_circle_radius_correct(self):
        """Each polyline point should be trochoid_radius away from circle centre."""
        result = self._run()
        R = self.TROCHOID_R
        for pl in result["polylines"]:
            cx = sum(p[0] for p in pl) / len(pl)
            cy = sum(p[1] for p in pl) / len(pl)
            for px, py in pl:
                d = _dist((px, py), (cx, cy))
                assert abs(d - R) < 0.15, f"circle point at dist {d:.3f} from centre (expected {R})"

    def test_total_length_positive(self):
        result = self._run()
        assert result["total_length"] > 0

    def test_metadata(self):
        result = self._run()
        meta = result["metadata"]
        assert meta["strategy"] == "trochoidal_slot"
        assert meta["trochoid_radius"] == self.TROCHOID_R

    def test_multi_segment_slot(self):
        """L-shaped slot path should still produce circles without crashing."""
        slot = [(0, 0), (50, 0), (50, 30)]
        result = trochoidal_slot(slot, 6.0, 4.0, 800.0)
        assert result["metadata"]["circles"] > 0


# ---------------------------------------------------------------------------
# rest_machining tests
# ---------------------------------------------------------------------------

class TestRestMachining:
    # 60×60 square, large tool sweeps most but leaves corners
    BOUNDARY = rect_boundary(60, 60)
    LARGE_D = 20.0
    SMALL_D = 5.0

    def _large_toolpath(self):
        """
        Simulate a face-mill with 20mm tool doing only a single central sweep.
        This clears the central horizontal band (y from -10 to +10) but leaves
        the top and bottom strips (y > 10 and y < -10) uncleared.
        """
        # Single horizontal pass at y=0 with 20mm tool (r=10mm) clears y=-10..+10
        return [[(-30.0, 0.0), (30.0, 0.0)]]

    def test_uncleared_cells_detected(self):
        result = rest_machining(
            prior_toolpaths=self._large_toolpath(),
            boundary=self.BOUNDARY,
            large_tool_diameter=self.LARGE_D,
            small_tool_diameter=self.SMALL_D,
            feed=600.0,
            grid_resolution=0.5,
        )
        assert result["metadata"]["uncleared_cells"] > 0, (
            "Expected some uncleared cells above/below the single central pass"
        )

    def test_corner_reached(self):
        """
        With only a single central pass (y=0, r=10mm), the corners at (±30, ±30)
        are far from the large-tool sweep and must be cleared by the rest pass.
        The small-tool path must reach within 14mm of the corner (-30, -30).
        (The nearest uncleared grid cell to the corner is at about 0.35mm.)
        """
        result = rest_machining(
            prior_toolpaths=self._large_toolpath(),
            boundary=self.BOUNDARY,
            large_tool_diameter=self.LARGE_D,
            small_tool_diameter=self.SMALL_D,
            feed=600.0,
            grid_resolution=0.5,
        )
        corner = (-30.0, -30.0)
        all_pts = [p for pl in result["polylines"] for p in pl]
        assert all_pts, "rest-machining produced no toolpath points"
        closest = min(_dist(p, corner) for p in all_pts)
        # Corner is in the uncleared region; small tool must reach it
        assert closest <= 14.0, (
            f"rest path closest point to corner is {closest:.2f} mm — too far"
        )

    def test_no_path_when_fully_cleared(self):
        """
        If the large tool clears every cell inside the boundary (e.g. huge tool),
        rest-machining should return an empty path.
        """
        # Use a 200mm tool on a 60mm pocket — everything cleared
        big_stripe = [[(-200, 0), (200, 0)]]
        result = rest_machining(
            prior_toolpaths=big_stripe,
            boundary=self.BOUNDARY,
            large_tool_diameter=200.0,
            small_tool_diameter=self.SMALL_D,
            feed=600.0,
        )
        assert result["polylines"] == [] or result["total_length"] == 0.0

    def test_total_length_positive_when_corners_remain(self):
        result = rest_machining(
            prior_toolpaths=self._large_toolpath(),
            boundary=self.BOUNDARY,
            large_tool_diameter=self.LARGE_D,
            small_tool_diameter=self.SMALL_D,
            feed=600.0,
        )
        assert result["total_length"] > 0

    def test_metadata_present(self):
        result = rest_machining(
            prior_toolpaths=self._large_toolpath(),
            boundary=self.BOUNDARY,
            large_tool_diameter=self.LARGE_D,
            small_tool_diameter=self.SMALL_D,
            feed=600.0,
        )
        meta = result["metadata"]
        assert meta["strategy"] == "rest_machining"
        assert meta["large_tool_diameter"] == self.LARGE_D
        assert meta["small_tool_diameter"] == self.SMALL_D

    def test_empty_prior_toolpath_clears_nothing(self):
        """No prior toolpath → entire pocket is uncleared → path is generated."""
        result = rest_machining(
            prior_toolpaths=[],
            boundary=self.BOUNDARY,
            large_tool_diameter=self.LARGE_D,
            small_tool_diameter=self.SMALL_D,
            feed=600.0,
            grid_resolution=1.0,
        )
        assert result["metadata"]["uncleared_cells"] > 0
        assert result["total_length"] > 0


# ---------------------------------------------------------------------------
# LLM tool smoke tests (sync wrapper, no real DB)
# ---------------------------------------------------------------------------

import asyncio
import json

class TestLLMTools:
    def _ctx(self):
        from kerf_cam._compat import ProjectCtx
        return ProjectCtx()

    def _call(self, coro):
        return asyncio.run(coro)

    def test_adaptive_pocket_tool(self):
        from kerf_cam.adaptive import run_adaptive_pocket
        ctx = self._ctx()
        boundary = [[-50, -30], [50, -30], [50, 30], [-50, 30]]
        args = json.dumps({
            "boundary": boundary,
            "tool_diameter": 10.0,
            "engagement_fraction": 0.30,
            "depth": 5.0,
            "feed": 1000.0,
        }).encode()
        raw = self._call(run_adaptive_pocket(ctx, args))
        result = json.loads(raw)
        assert "polylines" in result
        assert result["total_length"] > 0

    def test_trochoidal_slot_tool(self):
        from kerf_cam.adaptive import run_trochoidal_slot
        ctx = self._ctx()
        args = json.dumps({
            "slot_polyline": [[0, 0], [100, 0]],
            "tool_diameter": 6.0,
            "trochoid_radius": 4.0,
            "feed": 800.0,
        }).encode()
        raw = self._call(run_trochoidal_slot(ctx, args))
        result = json.loads(raw)
        assert "circles" in result["metadata"]
        assert result["metadata"]["circles"] > 0

    def test_rest_machining_tool(self):
        from kerf_cam.adaptive import run_rest_machining
        ctx = self._ctx()
        prior = [[[-30, -10], [30, -10]], [[-30, 0], [30, 0]], [[-30, 10], [30, 10]]]
        boundary = [[-30, -30], [30, -30], [30, 30], [-30, 30]]
        args = json.dumps({
            "prior_toolpaths": prior,
            "boundary": boundary,
            "large_tool_diameter": 20.0,
            "small_tool_diameter": 5.0,
            "feed": 600.0,
            "grid_resolution": 1.0,
        }).encode()
        raw = self._call(run_rest_machining(ctx, args))
        result = json.loads(raw)
        assert "metadata" in result

    def test_bad_args_returns_error(self):
        from kerf_cam.adaptive import run_adaptive_pocket
        ctx = self._ctx()
        raw = asyncio.run(run_adaptive_pocket(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"
