"""
tests/test_auto_routing_3d.py — unit tests for 3D harness auto-routing with
collision avoidance.

DoD:
  1. No-obstacle straight route — length ≈ 10 + small voxel overhead.
  2. Box obstacle in path — route detours; collision_clearance_min > cable_radius.
  3. Collision detection — a route through an obstacle raises ≥ 1 Collision.
  4. Clearance histogram — percentile_50 < percentile_95 in a tight space.

All tests are hermetic (no DB, no network).
"""
from __future__ import annotations

import json
import math

import pytest

from kerf_wiring.auto_routing_3d import (
    Body,
    Collision,
    Route,
    auto_route_harness,
    compute_routing_clearance,
    detect_route_collisions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _arc_length(polyline) -> float:
    total = 0.0
    for i in range(len(polyline) - 1):
        a, b = polyline[i], polyline[i + 1]
        total += math.sqrt(sum((b[k] - a[k]) ** 2 for k in range(3)))
    return total


# ---------------------------------------------------------------------------
# Test 1 — No-obstacle straight route
# ---------------------------------------------------------------------------

class TestNoObstacleStraightRoute:
    """
    Oracle: straight-line distance from (0,0,0) to (10,0,0) = 10 mm.
    With voxel_size=1.0 and a fine grid the smoothed route should be very close
    to 10 mm.  We allow up to 25 % overhead for the voxel grid quantisation and
    Catmull-Rom overshoot on a short path.
    """
    START = (0.0, 0.0, 0.0)
    END = (10.0, 0.0, 0.0)

    def test_returns_route(self):
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        assert isinstance(route, Route)

    def test_polyline_starts_and_ends_at_endpoints(self):
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        assert route.polyline[0] == pytest.approx(list(self.START), abs=1e-6)
        assert route.polyline[-1] == pytest.approx(list(self.END), abs=1e-6)

    def test_route_length_close_to_straight(self):
        """Routed length should be within 25 % of straight-line distance."""
        straight = 10.0
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        assert route.total_length == pytest.approx(straight, rel=0.25)

    def test_route_length_not_less_than_straight(self):
        """No path can be shorter than the straight-line distance."""
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        assert route.total_length >= 9.5  # slight tolerance for smoothing rounding

    def test_no_obstacle_clearance_is_inf(self):
        """With no obstacles, clearance should be infinite."""
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        assert route.collision_clearance_min == float("inf")

    def test_polyline_has_multiple_points(self):
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        assert len(route.polyline) >= 2

    def test_no_collisions(self):
        route = auto_route_harness(self.START, self.END, obstacles=[], voxel_size=1.0)
        collisions = detect_route_collisions(route, obstacles=[], cable_radius=2.0)
        assert collisions == []


# ---------------------------------------------------------------------------
# Test 2 — Box obstacle in path: detour around it
# ---------------------------------------------------------------------------

class TestBoxObstacleDetour:
    """
    Oracle:
    * Start=(0,0,0), End=(30,0,0), cable_radius=2.0, voxel_size=2.0.
    * A 4×4×4 box centred at (15,0,0), i.e. min=(13,-2,-2), max=(17,2,2).
    * Without collision avoidance a straight path would pass through the box.
    * With avoidance the route must detour; clearance_min should be ≥ cable_radius.
    * Route total_length > straight-line distance of 30 mm.
    """
    START = (0.0, 0.0, 0.0)
    END = (30.0, 0.0, 0.0)
    CABLE_R = 2.0
    VOXEL = 2.0
    BOX = Body(min_pt=(13.0, -2.0, -2.0), max_pt=(17.0, 2.0, 2.0), name="center_box")

    def _route(self) -> Route:
        return auto_route_harness(
            self.START, self.END,
            obstacles=[self.BOX],
            cable_radius=self.CABLE_R,
            voxel_size=self.VOXEL,
        )

    def test_route_found(self):
        route = self._route()
        assert isinstance(route, Route)
        assert len(route.polyline) >= 2

    def test_route_longer_than_straight(self):
        """Detour must be longer than straight 30 mm."""
        route = self._route()
        assert route.total_length > 30.0

    def test_collision_clearance_exceeds_cable_radius(self):
        """Min clearance from the smoothed path to the box must be >= cable_radius."""
        route = self._route()
        assert route.collision_clearance_min >= self.CABLE_R

    def test_endpoints_preserved(self):
        route = self._route()
        assert route.polyline[0] == pytest.approx(list(self.START), abs=1e-6)
        assert route.polyline[-1] == pytest.approx(list(self.END), abs=1e-6)

    def test_no_collisions_detected(self):
        """detect_route_collisions must find zero collisions on a valid routed path."""
        route = self._route()
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        assert len(collisions) == 0


# ---------------------------------------------------------------------------
# Test 3 — Collision detection on a route that passes through an obstacle
# ---------------------------------------------------------------------------

class TestCollisionDetection:
    """
    Oracle:
    * A straight polyline from (0,0,0) to (20,0,0).
    * A box obstacle centred at (10,0,0): min=(8,-1,-1) max=(12,1,1).
    * The midpoints of segments that cross the box must be reported as collisions.
    """
    BOX = Body(min_pt=(8.0, -1.0, -1.0), max_pt=(12.0, 1.0, 1.0), name="blocker")
    CABLE_R = 2.0

    def _make_route(self) -> Route:
        """Manually build a straight route that passes through the obstacle."""
        pts = [(float(x), 0.0, 0.0) for x in range(0, 21, 1)]
        total_len = 20.0
        return Route(
            polyline=pts,
            total_length=total_len,
            bend_count=0,
            collision_clearance_min=0.0,
        )

    def test_detects_at_least_one_collision(self):
        route = self._make_route()
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        assert len(collisions) >= 1

    def test_collision_obstacle_name(self):
        route = self._make_route()
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        names = {c.obstacle_name for c in collisions}
        assert "blocker" in names

    def test_collision_penetration_positive(self):
        """All reported collisions must have positive penetration depth."""
        route = self._make_route()
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        for c in collisions:
            assert c.penetration_depth > 0.0

    def test_collision_point_near_obstacle(self):
        """Each collision point should be within 2*cable_radius of the obstacle."""
        route = self._make_route()
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        for c in collisions:
            d = self.BOX.distance_to_point(c.point)
            assert d < self.CABLE_R + 1e-9

    def test_no_collision_on_clear_route(self):
        """A route well clear of the obstacle must return no collisions."""
        pts = [(float(x), 10.0, 0.0) for x in range(0, 21)]
        route = Route(polyline=pts, total_length=20.0, bend_count=0,
                      collision_clearance_min=9.0)
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        assert len(collisions) == 0

    def test_returns_collision_objects(self):
        route = self._make_route()
        collisions = detect_route_collisions(route, [self.BOX], cable_radius=self.CABLE_R)
        for c in collisions:
            assert isinstance(c, Collision)
            assert isinstance(c.segment_index, int)
            assert isinstance(c.penetration_depth, float)


# ---------------------------------------------------------------------------
# Test 4 — Clearance histogram: percentile_50 < percentile_95 in a tight space
# ---------------------------------------------------------------------------

class TestClearanceHistogram:
    """
    Oracle:
    * Route a harness between two obstacles placed along Y.  The route snakes
      between them so clearance varies: points near each obstacle get low
      clearance, and points in the gap get higher clearance.
    * We construct a polyline that varies in distance to the obstacle — some
      points close, some far — so the distribution is non-trivial and
      percentile_50 < percentile_95.
    """

    def _make_varying_route_and_obstacle(self):
        """
        Route: a zigzag in XY that alternately approaches and retreats from a wall
        at y=5. Points at even indices are at y=1 (close), odd indices at y=9 (far).
        Obstacle: a flat slab min=(0,4,0) max=(100,5,1).
        """
        obstacle = Body(min_pt=(0.0, 4.0, -1.0), max_pt=(100.0, 5.0, 1.0), name="wall")
        pts = []
        for i in range(20):
            x = float(i * 5)
            y = 1.0 if i % 2 == 0 else 9.0  # alternates close/far
            pts.append((x, y, 0.0))
        total_len = sum(
            math.sqrt(sum((pts[i+1][k] - pts[i][k])**2 for k in range(3)))
            for i in range(len(pts)-1)
        )
        route = Route(polyline=pts, total_length=total_len, bend_count=0,
                      collision_clearance_min=0.0)
        return route, obstacle

    def test_percentile_50_less_than_percentile_95(self):
        """
        With varying clearance along the route, the 50th percentile must be
        strictly less than the 95th percentile.
        """
        route, obstacle = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, [obstacle], n_samples=100)
        assert stats["percentile_50"] < stats["percentile_95"]

    def test_min_less_than_mean(self):
        route, obstacle = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, [obstacle], n_samples=100)
        assert stats["min"] <= stats["mean"]

    def test_mean_less_than_max(self):
        route, obstacle = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, [obstacle], n_samples=100)
        assert stats["mean"] <= stats["max"]

    def test_percentile_ordering(self):
        """Percentiles must be monotonically non-decreasing."""
        route, obstacle = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, [obstacle], n_samples=100)
        keys = ["min", "percentile_10", "percentile_25", "percentile_50",
                "percentile_75", "percentile_90", "percentile_95", "max"]
        vals = [stats[k] for k in keys]
        for a, b in zip(vals, vals[1:]):
            assert a <= b + 1e-9, f"Percentile order violated: {a} > {b}"

    def test_no_obstacles_returns_inf(self):
        route, _ = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, obstacles=[], n_samples=50)
        assert stats["min"] == float("inf")

    def test_n_samples_respected(self):
        route, obstacle = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, [obstacle], n_samples=20)
        assert stats["n_samples"] <= 20

    def test_all_keys_present(self):
        route, obstacle = self._make_varying_route_and_obstacle()
        stats = compute_routing_clearance(route, [obstacle], n_samples=50)
        expected = {"min", "mean", "percentile_10", "percentile_25", "percentile_50",
                    "percentile_75", "percentile_90", "percentile_95", "max", "n_samples"}
        assert set(stats.keys()) == expected


# ---------------------------------------------------------------------------
# Body / AABB helpers
# ---------------------------------------------------------------------------

class TestBody:
    def test_distance_outside(self):
        b = Body((0, 0, 0), (4, 4, 4))
        d = b.distance_to_point((6, 2, 2))
        assert pytest.approx(d) == 2.0

    def test_distance_inside_is_zero(self):
        b = Body((0, 0, 0), (4, 4, 4))
        d = b.distance_to_point((2, 2, 2))
        assert d == pytest.approx(0.0)

    def test_inflated_expands_all_sides(self):
        b = Body((0, 0, 0), (4, 4, 4))
        ib = b.inflated(2.0)
        assert ib.min_pt == pytest.approx((-2.0, -2.0, -2.0))
        assert ib.max_pt == pytest.approx((6.0, 6.0, 6.0))

    def test_inverted_box_raises(self):
        with pytest.raises(ValueError, match="min_pt"):
            Body((5, 0, 0), (2, 4, 4))

    def test_contains_point(self):
        b = Body((0, 0, 0), (4, 4, 4))
        assert b.contains_point((2, 2, 2))
        assert not b.contains_point((5, 2, 2))


# ---------------------------------------------------------------------------
# LLM tool smoke tests
# ---------------------------------------------------------------------------

class TestWiringAutoRouteTool:
    def _call(self, args: dict) -> dict:
        import asyncio
        from kerf_wiring.tools.auto_route import wiring_auto_route
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        raw = asyncio.get_event_loop().run_until_complete(
            wiring_auto_route(ctx, json.dumps(args).encode())
        )
        return json.loads(raw)

    def test_basic_call_returns_polyline(self):
        result = self._call({
            "start_point": [0, 0, 0],
            "end_point": [10, 0, 0],
            "obstacles": [],
            "voxel_size": 1.0,
        })
        assert "polyline" in result
        assert "total_length" in result
        assert result["total_length"] > 0

    def test_missing_start_returns_error(self):
        result = self._call({"end_point": [10, 0, 0]})
        assert result.get("code") == "BAD_ARGS"

    def test_missing_end_returns_error(self):
        result = self._call({"start_point": [0, 0, 0]})
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_json_returns_error(self):
        import asyncio
        from kerf_wiring.tools.auto_route import wiring_auto_route
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        raw = asyncio.get_event_loop().run_until_complete(
            wiring_auto_route(ctx, b"not json")
        )
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"


class TestWiringCheckClearanceTool:
    def _call(self, args: dict) -> dict:
        import asyncio
        from kerf_wiring.tools.auto_route import wiring_check_clearance
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        raw = asyncio.get_event_loop().run_until_complete(
            wiring_check_clearance(ctx, json.dumps(args).encode())
        )
        return json.loads(raw)

    def test_basic_call_returns_clearance_and_collisions(self):
        result = self._call({
            "polyline": [[0, 0, 0], [5, 0, 0], [10, 0, 0]],
            "obstacles": [{"min_pt": [4, -1, -1], "max_pt": [6, 1, 1], "name": "mid"}],
            "cable_radius": 0.5,
        })
        assert "clearance" in result
        assert "collisions" in result
        assert "collision_count" in result

    def test_clear_route_returns_no_collisions(self):
        result = self._call({
            "polyline": [[0, 10, 0], [10, 10, 0]],
            "obstacles": [{"min_pt": [3, 0, 0], "max_pt": [7, 2, 2], "name": "low_box"}],
            "cable_radius": 1.0,
        })
        assert result["collision_count"] == 0

    def test_penetrating_route_returns_collisions(self):
        result = self._call({
            "polyline": [[0, 0, 0], [5, 0, 0], [10, 0, 0]],
            "obstacles": [{"min_pt": [3, -2, -2], "max_pt": [7, 2, 2], "name": "blocker"}],
            "cable_radius": 2.0,
        })
        assert result["collision_count"] >= 1

    def test_missing_polyline_returns_error(self):
        result = self._call({
            "obstacles": [{"min_pt": [0, 0, 0], "max_pt": [1, 1, 1]}],
        })
        assert result.get("code") == "BAD_ARGS"
