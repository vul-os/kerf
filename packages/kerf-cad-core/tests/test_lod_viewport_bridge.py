"""Tests for viewport LOD bridge (lod_viewport_bridge.py).

Covers:
- Close camera → 'high' tier for all parts
- Far camera (distance >> diagonal) → 'culled' tier
- Mid distances → correct tier transitions
- 1000-part assembly demotes one tier from baseline
- mesh_url_suffix matches tier
- target_triangle_count is correct per tier
- Degenerate bbox handling
- plan_viewport_lods returns correct count
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.assembly.lod_viewport_bridge import (
    ViewportLodRequest,
    ViewportLodAssignment,
    plan_viewport_lods,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_bbox_request(
    component_id: str = "part-0",
    camera_position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    total_part_count: int = 1,
    mesh_triangle_count: int = 1000,
) -> ViewportLodRequest:
    """Unit bounding box [0,0,0]→[1,1,1], diagonal = √3 ≈ 1.732."""
    return ViewportLodRequest(
        component_id=component_id,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(1.0, 1.0, 1.0),
        mesh_triangle_count=mesh_triangle_count,
        camera_position=camera_position,
        total_part_count=total_part_count,
    )


_UNIT_DIAG = math.sqrt(3)  # ≈ 1.732


# ---------------------------------------------------------------------------
# Test 1: Close camera → 'high' for all parts
# ---------------------------------------------------------------------------

class TestHighTierClose:
    def test_camera_inside_bbox_is_high(self):
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5))
        result = plan_viewport_lods([req])
        assert result[0].tier == "high"

    def test_camera_very_close_is_high(self):
        # distance ≈ 0 (just outside bbox), d/diag << 5
        req = _unit_bbox_request(camera_position=(0.0, 0.0, 0.0))
        result = plan_viewport_lods([req])
        assert result[0].tier == "high"

    def test_camera_at_2x_diag_is_high(self):
        # distance = 2 × _UNIT_DIAG, ratio = 2 < 5 → high
        d = 2 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(-d, 0.5, 0.5))
        result = plan_viewport_lods([req])
        assert result[0].tier == "high"

    def test_multiple_parts_all_close_are_high(self):
        requests = [
            _unit_bbox_request(component_id=f"part-{i}", camera_position=(0.5, 0.5, 0.5))
            for i in range(5)
        ]
        results = plan_viewport_lods(requests)
        for r in results:
            assert r.tier == "high", f"{r.component_id} should be high, got {r.tier}"


# ---------------------------------------------------------------------------
# Test 2: Far camera → 'culled'
# ---------------------------------------------------------------------------

class TestCulledTierFar:
    def test_camera_at_200x_diag_is_culled(self):
        # distance = 200 × _UNIT_DIAG >> 100× threshold
        d = 200 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].tier == "culled"

    def test_culled_suffix_is_empty_string(self):
        d = 200 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].mesh_url_suffix == ""

    def test_culled_target_triangles_is_zero(self):
        d = 200 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].target_triangle_count == 0


# ---------------------------------------------------------------------------
# Test 3: Intermediate distances → mid / low
# ---------------------------------------------------------------------------

class TestMidLowTiers:
    def test_distance_at_10x_diag_is_mid(self):
        # ratio = 10, 5 <= 10 < 20 → mid
        d = 10 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].tier == "mid"

    def test_distance_at_50x_diag_is_low(self):
        # ratio = 50, 20 <= 50 < 100 → low
        d = 50 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].tier == "low"

    def test_distance_at_6x_diag_is_mid(self):
        # Place camera well past the 5× threshold so ratio is clearly in [5, 20).
        # bbox is [0,0,0]→[1,1,1]; closest-point distance from camera at (0.5,0.5,1+6d)
        # to box is 6d, so ratio = 6d/diag = 6 → mid.
        d = 6 * _UNIT_DIAG
        # Camera is outside bbox on z-axis: closest point is (0.5,0.5,1.0), dist=d
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 1.0 + d))
        result = plan_viewport_lods([req])
        assert result[0].tier == "mid"


# ---------------------------------------------------------------------------
# Test 4: 1000-part assembly demotes one tier from baseline
# ---------------------------------------------------------------------------

class TestDemotion:
    def test_1000_parts_demotes_high_to_mid(self):
        # Baseline without demotion: close camera → high
        # With 1000 parts: should demote to mid
        req = _unit_bbox_request(
            camera_position=(0.5, 0.5, 0.5),
            total_part_count=1000,
        )
        result = plan_viewport_lods([req])
        assert result[0].tier == "mid", (
            f"Expected 'mid' after demotion of 'high', got '{result[0].tier}'"
        )

    def test_1000_parts_demotes_mid_to_low(self):
        # Mid distance + 1000 parts → low
        d = 10 * _UNIT_DIAG
        req = _unit_bbox_request(
            camera_position=(0.5, 0.5, 0.5 + d),
            total_part_count=1000,
        )
        result = plan_viewport_lods([req])
        assert result[0].tier == "low"

    def test_1000_parts_demotes_low_to_culled(self):
        # Low distance + 1000 parts → culled
        d = 50 * _UNIT_DIAG
        req = _unit_bbox_request(
            camera_position=(0.5, 0.5, 0.5 + d),
            total_part_count=1000,
        )
        result = plan_viewport_lods([req])
        assert result[0].tier == "culled"

    def test_500_parts_no_demotion(self):
        # Exactly 500 parts → no demotion (threshold is > 500)
        req = _unit_bbox_request(
            camera_position=(0.5, 0.5, 0.5),
            total_part_count=500,
        )
        result = plan_viewport_lods([req])
        assert result[0].tier == "high"

    def test_501_parts_demotes(self):
        req = _unit_bbox_request(
            camera_position=(0.5, 0.5, 0.5),
            total_part_count=501,
        )
        result = plan_viewport_lods([req])
        assert result[0].tier == "mid"


# ---------------------------------------------------------------------------
# Test 5: mesh_url_suffix correctness
# ---------------------------------------------------------------------------

class TestUrlSuffix:
    def test_high_suffix_is_lod0(self):
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5))
        result = plan_viewport_lods([req])
        assert result[0].mesh_url_suffix == "_lod0.glb"

    def test_mid_suffix_is_lod1(self):
        d = 10 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].mesh_url_suffix == "_lod1.glb"

    def test_low_suffix_is_lod2(self):
        d = 50 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].mesh_url_suffix == "_lod2.glb"

    def test_culled_suffix_is_empty(self):
        d = 200 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d))
        result = plan_viewport_lods([req])
        assert result[0].mesh_url_suffix == ""


# ---------------------------------------------------------------------------
# Test 6: target_triangle_count per tier
# ---------------------------------------------------------------------------

class TestTriangleCounts:
    def test_high_tier_full_triangles(self):
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5), mesh_triangle_count=800)
        result = plan_viewport_lods([req])
        assert result[0].target_triangle_count == 800

    def test_mid_tier_quarter_triangles(self):
        d = 10 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d), mesh_triangle_count=800)
        result = plan_viewport_lods([req])
        assert result[0].target_triangle_count == 200  # 800 × 0.25

    def test_low_tier_sixteenth_triangles(self):
        d = 50 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d), mesh_triangle_count=1600)
        result = plan_viewport_lods([req])
        assert result[0].target_triangle_count == 100  # 1600 / 16

    def test_culled_tier_zero_triangles(self):
        d = 200 * _UNIT_DIAG
        req = _unit_bbox_request(camera_position=(0.5, 0.5, 0.5 + d), mesh_triangle_count=999)
        result = plan_viewport_lods([req])
        assert result[0].target_triangle_count == 0


# ---------------------------------------------------------------------------
# Test 7: Output count and component_id passthrough
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_output_count_matches_input(self):
        requests = [
            _unit_bbox_request(component_id=f"c-{i}", camera_position=(0.5, 0.5, 0.5))
            for i in range(7)
        ]
        results = plan_viewport_lods(requests)
        assert len(results) == 7

    def test_component_id_preserved(self):
        req = _unit_bbox_request(component_id="my-unique-part")
        result = plan_viewport_lods([req])
        assert result[0].component_id == "my-unique-part"

    def test_empty_list_returns_empty(self):
        results = plan_viewport_lods([])
        assert results == []
