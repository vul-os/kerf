"""
Hermetic tests for kerf_cad_core.cam_toolpath_collision.

Tests:
  1.  clean_toolpath_no_collision        — holder well above stock → safe=True, 0 collisions
  2.  known_bad_path_holder_collision    — holder 5mm above stock top (10mm holder radius) → collision
  3.  safety_margin_zero_edge_case       — margin=0; penetrating path is still unsafe
  4.  empty_toolpath_empty_report        — no waypoints → empty report
  5.  single_waypoint_no_segments        — 1 waypoint → 0 segments checked
  6.  safe_with_large_clearance          — 20mm above stock top with 10mm holder radius → safe
  7.  mesh_stock_collision_detected      — mesh stock wall + holder close → collision
  8.  mesh_stock_safe_when_clear         — holder far from wall mesh → no mesh collision
  9.  fixture_collision_detected         — fixture mesh close to holder → collision
  10. fixture_safe_when_distant          — fixture far away → still safe
  11. position_in_collision_event        — position field is 3-tuple of floats
  12. distance_negative_on_penetration   — deep penetration gives negative distance
  13. segment_index_correct              — collision in segment 1 not 0
  14. multiple_segments_all_safe         — 5-segment ramp, holder always 30mm above stock
  15. step_mm_controls_sample_count      — step_mm=0.1 gives more samples than step_mm=10
  16. bad_step_mm_falls_back_to_default  — step_mm ≤ 0 triggers warning, report still returns
  17. collision_distance_less_than_margin — each collision distance < safety_margin
  18. penetrating_zero_margin_unsafe     — at margin=0, penetrating holder is unsafe

All tests are pure-Python and hermetic: no OCC, no DB, no network.

Author: imranparuk
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.cam_toolpath_collision import (
    CollisionReport,
    StockGeometry,
    ToolGeometry,
    verify_toolpath_collision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(flute_r=3.0, flute_l=20.0, holder_r=10.0, holder_l=40.0):
    return ToolGeometry(
        flute_radius=flute_r,
        flute_length=flute_l,
        holder_radius=holder_r,
        holder_length=holder_l,
    )


def _make_stock_aabb(zmin=0.0, zmax=50.0):
    """Stock AABB: 100×100 in XY, zmin..zmax."""
    return StockGeometry(
        aabb_min=(-50.0, -50.0, zmin),
        aabb_max=(50.0, 50.0, zmax),
    )


def _floor_triangle_mesh(z: float = 0.0, size: float = 100.0):
    """A single large triangle representing a flat floor at z."""
    return [
        [[-size, -size, z], [size, -size, z], [0.0, size, z]],
    ]


# ---------------------------------------------------------------------------
# 1. Clean toolpath — no collision
# ---------------------------------------------------------------------------

class TestCleanToolpath:
    def test_clean_toolpath_no_collision(self):
        """
        Holder with radius=10mm, length=40mm placed with tip at z=100mm:
        holder occupies z=120..160mm.  Stock top is z=50mm.
        Clearance = 120 - 50 = 70mm >> safety_margin=2mm → safe.
        """
        stock = _make_stock_aabb(zmin=0.0, zmax=50.0)
        tool = _make_tool(holder_r=10.0, holder_l=40.0)
        # Tip moves laterally at z=100mm (high above stock top=50)
        toolpath = [
            (0.0, 0.0, 100.0, 500.0),
            (50.0, 0.0, 100.0, 500.0),
        ]
        report = verify_toolpath_collision(
            toolpath, tool, stock, safety_margin=2.0
        )
        assert report.safe is True
        assert report.collisions == []

    def test_safe_with_large_clearance(self):
        """Holder tip 20mm above stock top with 10mm holder radius → 10mm clearance → safe."""
        stock = _make_stock_aabb(zmin=0.0, zmax=50.0)
        tool = _make_tool(flute_l=10.0, holder_r=10.0, holder_l=30.0)
        # tip at z=80: holder occupies z=90..120; stock top=50; clearance=40mm
        toolpath = [
            (-10.0, 0.0, 80.0, 300.0),
            (10.0, 0.0, 80.0, 300.0),
        ]
        report = verify_toolpath_collision(
            toolpath, tool, stock, safety_margin=2.0
        )
        assert report.safe is True
        assert len(report.collisions) == 0


# ---------------------------------------------------------------------------
# 2. Known-bad path — holder collision
# ---------------------------------------------------------------------------

class TestKnownBadPath:
    def test_holder_collision_detected(self):
        """
        Holder radius=10mm.  Tip at z=55mm → holder occupies z=75..115mm.
        Stock top at z=80mm → holder is 5mm above stock top (within holder),
        BUT stock spans up to 80mm and holder bottom is at z=75mm, inside the
        stock height band.  With safety_margin=2mm → collision detected.
        """
        stock = _make_stock_aabb(zmin=0.0, zmax=80.0)
        tool = _make_tool(flute_l=20.0, holder_r=10.0, holder_l=40.0)
        # Tip at z=55: flute 55..75, holder 75..115
        # Stock AABB top=80; holder bottom=75 < 80 → holder inside stock Z range
        # XY: tip at (0,0) inside stock XY (-50..50) → AABB distance < 0 → collision
        toolpath = [
            (0.0, 0.0, 55.0, 300.0),
            (5.0, 0.0, 55.0, 300.0),
        ]
        report = verify_toolpath_collision(
            toolpath, tool, stock, safety_margin=2.0
        )
        assert report.safe is False
        assert len(report.collisions) > 0
        # All reported collisions should be holder collisions
        assert all(c.body == "holder" for c in report.collisions)

    def test_collision_distance_less_than_margin(self):
        """Distance of each collision event must be < safety_margin."""
        stock = _make_stock_aabb(zmin=0.0, zmax=80.0)
        tool = _make_tool(flute_l=20.0, holder_r=10.0, holder_l=40.0)
        toolpath = [
            (0.0, 0.0, 55.0, 300.0),
            (5.0, 0.0, 55.0, 300.0),
        ]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=2.0)
        assert report.safe is False
        for evt in report.collisions:
            assert evt.distance < 2.0


# ---------------------------------------------------------------------------
# 3. Safety margin = 0 edge case
# ---------------------------------------------------------------------------

class TestSafetyMarginZero:
    def test_penetrating_is_still_unsafe_at_zero_margin(self):
        """With margin=0, a holder that physically penetrates stock is still unsafe."""
        stock = _make_stock_aabb(zmin=0.0, zmax=80.0)
        tool = _make_tool(flute_l=20.0, holder_r=10.0, holder_l=40.0)
        # Holder bottom at z=75, stock top=80 → holder inside stock (distance < 0)
        toolpath = [(0.0, 0.0, 55.0, 300.0), (5.0, 0.0, 55.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=0.0)
        assert report.safe is False

    def test_barely_clear_at_zero_margin_is_safe(self):
        """Holder clears stock by several mm → safe at margin=0."""
        stock = _make_stock_aabb(zmin=0.0, zmax=50.0)
        tool = _make_tool(flute_l=20.0, holder_r=5.0, holder_l=30.0)
        # Tip at z=50: holder bottom=70, holder top=100.
        # Stock top=50, holder bottom=70 → gap=20mm. AABB XY is -50..50.
        # Holder at (60,0) which is OUTSIDE AABB XY, so no XY overlap.
        # Min distance from holder axis to AABB: XY distance = 60-50=10, minus radius 5 = 5mm > 0 → safe.
        toolpath = [(60.0, 0.0, 50.0, 300.0), (65.0, 0.0, 50.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=0.0)
        assert report.safe is True


# ---------------------------------------------------------------------------
# 4. Empty toolpath → empty report
# ---------------------------------------------------------------------------

class TestEmptyToolpath:
    def test_empty_toolpath_returns_empty_report(self):
        stock = _make_stock_aabb()
        tool = _make_tool()
        report = verify_toolpath_collision([], tool, stock)
        assert isinstance(report, CollisionReport)
        assert report.safe is True
        assert report.collisions == []
        assert report.segments_checked == 0
        assert report.samples_total == 0


# ---------------------------------------------------------------------------
# 5. Single waypoint → 0 segments
# ---------------------------------------------------------------------------

class TestSingleWaypoint:
    def test_single_waypoint_no_segments(self):
        stock = _make_stock_aabb()
        tool = _make_tool()
        report = verify_toolpath_collision([(0.0, 0.0, 100.0, 0.0)], tool, stock)
        assert report.segments_checked == 0
        assert report.samples_total == 0


# ---------------------------------------------------------------------------
# 6. Mesh stock collision
# ---------------------------------------------------------------------------

class TestMeshStockCollision:
    def test_mesh_stock_holder_collision_detected(self):
        """
        A vertical wall mesh at x=300 (far right).  Holder radius=10.
        Tip at x=292: closest approach to wall at x=300 is 300-292-10=-2mm (penetrating) → collision.
        """
        # Vertical wall mesh at x=300
        wall_tris = [
            [[300.0, -100.0, 0.0], [300.0, 100.0, 0.0], [300.0, 100.0, 200.0]],
            [[300.0, -100.0, 0.0], [300.0, 100.0, 200.0], [300.0, -100.0, 200.0]],
        ]
        # Use a tiny AABB that won't interfere (placed below the tool path)
        stock = StockGeometry(
            aabb_min=(0.0, 0.0, 0.0),
            aabb_max=(1.0, 1.0, 1.0),
            triangles=wall_tris,
        )
        tool = _make_tool(flute_l=10.0, holder_r=10.0, holder_l=40.0)
        # Tip at (292, 0, 50): holder (z=60..100) near wall at x=300; dist=300-292-10=-2 → collision
        toolpath = [(292.0, 0.0, 50.0, 300.0), (293.0, 0.0, 50.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=2.0)
        mesh_collisions = [c for c in report.collisions if c.geometry == "stock_mesh"]
        assert len(mesh_collisions) > 0

    def test_mesh_stock_safe_when_clear(self):
        """Holder well clear of wall mesh → no mesh collision."""
        wall_tris = [
            [[300.0, -100.0, 0.0], [300.0, 100.0, 0.0], [300.0, 100.0, 200.0]],
            [[300.0, -100.0, 0.0], [300.0, 100.0, 200.0], [300.0, -100.0, 200.0]],
        ]
        # Tiny AABB below tool path
        stock = StockGeometry(
            aabb_min=(0.0, 0.0, 0.0),
            aabb_max=(1.0, 1.0, 1.0),
            triangles=wall_tris,
        )
        tool = _make_tool(flute_l=10.0, holder_r=10.0, holder_l=40.0)
        # Tip at (200, 0, 50): holder axis at x=200, dist to wall=300-200-10=90mm >> margin=2 → safe
        toolpath = [(200.0, 0.0, 50.0, 300.0), (205.0, 0.0, 50.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=2.0)
        mesh_collisions = [c for c in report.collisions if c.geometry == "stock_mesh"]
        assert len(mesh_collisions) == 0


# ---------------------------------------------------------------------------
# 7. Fixture collision
# ---------------------------------------------------------------------------

class TestFixtureCollision:
    def _fixture_wall_at_x50(self):
        """A vertical wall fixture at x=50 (two triangles forming a square face)."""
        return [
            [[50.0, -100.0, 0.0], [50.0, 100.0, 0.0], [50.0, 100.0, 100.0]],
            [[50.0, -100.0, 0.0], [50.0, 100.0, 100.0], [50.0, -100.0, 100.0]],
        ]

    def test_fixture_collision_detected(self):
        """Holder radius=10mm moving toward fixture wall at x=50; position at x=42 → dist=50-42-10=−2 → collision."""
        stock = StockGeometry(
            aabb_min=(0.0, 0.0, 0.0),
            aabb_max=(1.0, 1.0, 1.0),
        )
        fixture = self._fixture_wall_at_x50()
        tool = _make_tool(flute_l=5.0, holder_r=10.0, holder_l=30.0)
        # Tip at (42, 0, 25): holder at x=42, radius=10 → distance to fixture at x=50 is 50-42-10=-2mm
        # That's 8mm from axis → 8-10=-2mm distance (penetrating)
        toolpath = [(42.0, 0.0, 25.0, 300.0), (43.0, 0.0, 25.0, 300.0)]
        report = verify_toolpath_collision(
            toolpath, tool, stock, fixture=fixture, safety_margin=2.0
        )
        assert report.safe is False
        fix_collisions = [c for c in report.collisions if c.geometry == "fixture"]
        assert len(fix_collisions) > 0

    def test_fixture_safe_when_distant(self):
        """Holder far from fixture wall and above stock → no fixture collision."""
        # Use a stock AABB that is entirely below the tool path Z
        stock = StockGeometry(
            aabb_min=(0.0, 0.0, 0.0),
            aabb_max=(1.0, 1.0, 1.0),
        )
        fixture = self._fixture_wall_at_x50()
        tool = _make_tool(flute_l=5.0, holder_r=10.0, holder_l=30.0)
        # Tip at (-30, 0, 25): holder axis at x=-30, radius=10
        # Fixture wall at x=50: distance from axis to wall = 50 - (-30) = 80; minus radius=10 → 70mm >> 2mm
        toolpath = [(-30.0, 0.0, 25.0, 300.0), (-25.0, 0.0, 25.0, 300.0)]
        report = verify_toolpath_collision(
            toolpath, tool, stock, fixture=fixture, safety_margin=2.0
        )
        fix_collisions = [c for c in report.collisions if c.geometry == "fixture"]
        assert len(fix_collisions) == 0


# ---------------------------------------------------------------------------
# 8. Collision event fields
# ---------------------------------------------------------------------------

class TestCollisionEventFields:
    def test_position_is_3_floats(self):
        stock = _make_stock_aabb(zmin=0.0, zmax=80.0)
        tool = _make_tool(flute_l=20.0, holder_r=10.0, holder_l=40.0)
        toolpath = [(0.0, 0.0, 55.0, 300.0), (5.0, 0.0, 55.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=2.0)
        assert not report.safe
        evt = report.collisions[0]
        assert len(evt.position) == 3
        assert all(isinstance(v, float) for v in evt.position)

    def test_distance_negative_on_deep_penetration(self):
        """Holder fully inside the stock → distance is negative."""
        stock = _make_stock_aabb(zmin=0.0, zmax=200.0)
        tool = _make_tool(flute_l=10.0, holder_r=5.0, holder_l=30.0)
        # Tip at z=50: holder at z=60..90, entirely within stock (0..200)
        # XY at (0,0), stock XY=-50..50 → holder axis inside AABB → distance = 0-radius < 0
        toolpath = [(0.0, 0.0, 50.0, 300.0), (1.0, 0.0, 50.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=0.0)
        assert not report.safe
        # At least one collision with negative distance (penetration)
        assert any(c.distance < 0.0 for c in report.collisions)

    def test_segment_index_correct(self):
        """Collision on segment 1 (not 0)."""
        stock = _make_stock_aabb(zmin=0.0, zmax=80.0)
        tool = _make_tool(flute_l=20.0, holder_r=10.0, holder_l=40.0)
        # Segment 0: safe (z=200, far above stock)
        # Segment 1: collision (z=55, holder inside stock)
        toolpath = [
            (0.0, 0.0, 200.0, 500.0),  # safe position
            (0.0, 0.0, 200.0, 500.0),  # stays safe
            (0.0, 0.0, 55.0, 300.0),   # collides
        ]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=2.0)
        assert not report.safe
        collisions_by_seg = {c.segment_index for c in report.collisions}
        # Should not include segment 0
        assert 0 not in collisions_by_seg
        # Should include segment 1 (the descent)
        assert 1 in collisions_by_seg


# ---------------------------------------------------------------------------
# 9. Multiple segments all safe
# ---------------------------------------------------------------------------

class TestMultiSegmentSafe:
    def test_5_segment_ramp_all_safe(self):
        """5-segment descending ramp; holder always 30mm above stock top → safe."""
        stock = _make_stock_aabb(zmin=0.0, zmax=50.0)
        tool = _make_tool(flute_l=10.0, holder_r=8.0, holder_l=20.0)
        # Flute top at z=90..100; holder at z=100..120; stock top=50 → clearance=50mm
        toolpath = [
            (0.0, 0.0, 80.0, 500.0),
            (10.0, 5.0, 82.0, 500.0),
            (20.0, 10.0, 84.0, 500.0),
            (30.0, 5.0, 86.0, 500.0),
            (40.0, 0.0, 88.0, 500.0),
            (50.0, 0.0, 90.0, 500.0),
        ]
        report = verify_toolpath_collision(toolpath, tool, stock, safety_margin=2.0)
        assert report.safe is True
        assert report.segments_checked == 5
        assert report.collisions == []


# ---------------------------------------------------------------------------
# 10. step_mm controls sample count
# ---------------------------------------------------------------------------

class TestStepMmControls:
    def test_finer_step_gives_more_samples(self):
        """Finer step_mm → more total samples on the same segment."""
        stock = _make_stock_aabb(zmin=0.0, zmax=10.0)
        tool = _make_tool()
        toolpath = [(0.0, 0.0, 200.0, 300.0), (100.0, 0.0, 200.0, 300.0)]

        r_coarse = verify_toolpath_collision(toolpath, tool, stock, step_mm=10.0)
        r_fine = verify_toolpath_collision(toolpath, tool, stock, step_mm=1.0)
        assert r_fine.samples_total > r_coarse.samples_total

    def test_bad_step_mm_falls_back_and_warns(self):
        """step_mm ≤ 0 should trigger a warning but return a valid report."""
        stock = _make_stock_aabb()
        tool = _make_tool()
        toolpath = [(0.0, 0.0, 200.0, 300.0), (10.0, 0.0, 200.0, 300.0)]
        report = verify_toolpath_collision(toolpath, tool, stock, step_mm=0.0)
        assert isinstance(report, CollisionReport)
        assert len(report.warnings) > 0
        # Report must still complete correctly
        assert report.segments_checked == 1
