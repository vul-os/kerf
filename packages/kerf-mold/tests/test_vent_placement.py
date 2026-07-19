"""
Tests for kerf_mold.vent_placement -- MOLD-VENT-PLACEMENT-OPTIMIZE

Oracle refs: Beaumont 2007 §8.4 + Table 8.4.

Covers:
  - 100x50x20 box gated top-center -> bottom corners are last-fill candidates
  - Thin elongated 200x20x5 gated at one end -> far-end vents highest priority
  - ABS depth range: 0.025-0.040 mm
  - PP depth range: 0.020-0.030 mm (polyolefin class)
  - POM depth range: 0.013-0.020 mm (crystalline)
  - PA66 depth range: 0.013-0.020 mm (crystalline)
  - is_crystalline flag for POM/PA66; False for ABS/PP
  - Recommended depth is midpoint of range
  - Parting-line rib candidates included by default
  - Sharp-corner candidates included by default
  - Avoid-zone excludes vent candidates
  - max_vents cap respected
  - Honest-flag in warnings
  - LLM tool round-trip (mold_optimize_vent_placement)
  - Plugin registration
  - Input validation errors
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_mold.vent_placement import (
    CavityBbox,
    VentLocation,
    VentPlacementResult,
    optimize_vent_placement,
    _vent_depth_for_material,
    _CRYSTALLINE_MATERIALS,
)


def _run(coro):
    return asyncio.run(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# CavityBbox
# ---------------------------------------------------------------------------

class TestCavityBboxVent:
    def test_center(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        assert bbox.center == pytest.approx((50.0, 25.0, 10.0))

    def test_parting_line_corners_count(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        corners = bbox.parting_line_corners()
        assert len(corners) == 4

    def test_parting_line_z_at_origin(self):
        bbox = CavityBbox(100.0, 50.0, 20.0, origin=(0.0, 0.0, 0.0))
        corners = bbox.parting_line_corners()
        for _, _, z in corners:
            assert z == pytest.approx(0.0)

    def test_zero_width_raises(self):
        with pytest.raises(ValueError):
            CavityBbox(0.0, 50.0, 20.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError):
            CavityBbox(100.0, -1.0, 20.0)


# ---------------------------------------------------------------------------
# Material depth table -- Beaumont Table 8.4 oracle
# ---------------------------------------------------------------------------

class TestVentDepthTable:
    def test_abs_range(self):
        lo, hi = _vent_depth_for_material("ABS")
        assert lo == pytest.approx(0.025)
        assert hi == pytest.approx(0.040)

    def test_abs_lowercase_normalized(self):
        lo, hi = _vent_depth_for_material("abs")
        assert lo == pytest.approx(0.025)
        assert hi == pytest.approx(0.040)

    def test_pp_range(self):
        lo, hi = _vent_depth_for_material("PP")
        assert lo == pytest.approx(0.020)
        assert hi == pytest.approx(0.030)

    def test_pe_range(self):
        lo, hi = _vent_depth_for_material("PE")
        assert lo == pytest.approx(0.020)
        assert hi == pytest.approx(0.030)

    def test_pc_range(self):
        lo, hi = _vent_depth_for_material("PC")
        assert lo == pytest.approx(0.025)
        assert hi == pytest.approx(0.035)

    def test_pom_crystalline_range(self):
        lo, hi = _vent_depth_for_material("POM")
        assert lo == pytest.approx(0.013)
        assert hi == pytest.approx(0.020)

    def test_pa66_crystalline_range(self):
        lo, hi = _vent_depth_for_material("PA66")
        assert lo == pytest.approx(0.013)
        assert hi == pytest.approx(0.020)

    def test_pa_range(self):
        lo, hi = _vent_depth_for_material("PA")
        assert lo == pytest.approx(0.013)
        assert hi == pytest.approx(0.020)

    def test_pbt_range(self):
        lo, hi = _vent_depth_for_material("PBT")
        assert lo == pytest.approx(0.013)
        assert hi == pytest.approx(0.020)

    def test_pet_range(self):
        lo, hi = _vent_depth_for_material("PET")
        assert lo == pytest.approx(0.013)
        assert hi == pytest.approx(0.020)

    def test_lcp_range(self):
        lo, hi = _vent_depth_for_material("LCP")
        assert lo == pytest.approx(0.010)
        assert hi == pytest.approx(0.015)

    def test_pps_range(self):
        lo, hi = _vent_depth_for_material("PPS")
        assert lo == pytest.approx(0.010)
        assert hi == pytest.approx(0.015)

    def test_tpe_range(self):
        lo, hi = _vent_depth_for_material("TPE")
        assert lo == pytest.approx(0.020)
        assert hi == pytest.approx(0.030)

    def test_unknown_material_falls_back_to_abs_class(self):
        lo, hi = _vent_depth_for_material("UNKNOWN_RESIN")
        assert lo == pytest.approx(0.025)
        assert hi == pytest.approx(0.040)

    def test_crystalline_flag_pom(self):
        assert "POM" in _CRYSTALLINE_MATERIALS

    def test_crystalline_flag_pa66(self):
        assert "PA66" in _CRYSTALLINE_MATERIALS

    def test_crystalline_flag_abs_false(self):
        assert "ABS" not in _CRYSTALLINE_MATERIALS

    def test_crystalline_flag_pp_false(self):
        assert "PP" not in _CRYSTALLINE_MATERIALS


# ---------------------------------------------------------------------------
# 100x50x20 box gated top-center
# ---------------------------------------------------------------------------

class TestBox100x50x20TopGate:
    """
    Depth bar (Beaumont §8.4.1):
    Gate at top-center (50, 25, 20).
    Last-fill = bottom corners at (0,0,0), (100,0,0), (0,50,0), (100,50,0).
    These are farthest from the gate -> highest priority vents.
    """

    GATE = (50.0, 25.0, 20.0)
    BBOX = CavityBbox(100.0, 50.0, 20.0)

    def _result(self, **kw) -> VentPlacementResult:
        return optimize_vent_placement(self.BBOX, self.GATE, **kw)

    def test_returns_result(self):
        r = self._result()
        assert isinstance(r, VentPlacementResult)

    def test_count_positive(self):
        r = self._result()
        assert r.count > 0

    def test_vent_positions_match_count(self):
        r = self._result()
        assert len(r.vent_positions) == r.count
        assert len(r.vent_locations) == r.count

    def test_last_fill_vents_present(self):
        r = self._result()
        reasons = [v.reason for v in r.vent_locations]
        assert "last_fill" in reasons

    def test_bottom_corners_in_last_fill(self):
        """For top-gate, the bottom corners should be last-fill candidates."""
        r = self._result()
        last_fill_vents = [v for v in r.vent_locations if v.reason == "last_fill"]
        assert len(last_fill_vents) >= 2
        for v in last_fill_vents:
            assert v.position[2] == pytest.approx(0.0, abs=0.01), \
                f"Expected last-fill at z=0 (bottom), got z={v.position[2]}"

    def test_primary_vent_farthest_from_gate(self):
        r = self._result()
        p1_vents = [v for v in r.vent_locations if v.priority == 1]
        assert p1_vents, "No priority-1 (last_fill) vents found"
        max_dist = max(v.distance_from_gate_mm for v in p1_vents)
        # Farthest corner from (50,25,20) to (0,0,0) approx sqrt(50^2+25^2+20^2) approx 59.2 mm
        assert max_dist == pytest.approx(59.16, abs=1.5)

    def test_abs_depth_range_default(self):
        r = self._result(material="ABS")
        dm = r.depth_per_material
        assert dm["depth_min_mm"] == pytest.approx(0.025)
        assert dm["depth_max_mm"] == pytest.approx(0.040)

    def test_abs_not_crystalline(self):
        r = self._result(material="ABS")
        assert r.depth_per_material["is_crystalline"] is False

    def test_recommended_depth_is_midpoint(self):
        r = self._result(material="ABS")
        dm = r.depth_per_material
        expected_mid = (dm["depth_min_mm"] + dm["depth_max_mm"]) / 2.0
        assert dm["recommended_depth_mm"] == pytest.approx(expected_mid, abs=0.001)

    def test_beaumont_reference_in_depth_info(self):
        r = self._result()
        assert "Beaumont" in r.depth_per_material["reference"]

    def test_honest_flag_in_warnings(self):
        r = self._result()
        combined = " ".join(r.warnings).lower()
        assert "heuristic" in combined or "honest" in combined

    def test_recommendations_not_empty(self):
        r = self._result()
        assert len(r.recommendations) >= 1

    def test_parting_rib_vents_present(self):
        r = self._result(include_parting_ribs=True)
        reasons = [v.reason for v in r.vent_locations]
        assert "parting_rib" in reasons

    def test_corner_vents_present(self):
        # Use max_vents=12 to ensure sharp_corner (priority-3) candidates appear
        # beyond the default cap of 8 (4 last_fill + 4 parting_rib exhausts it).
        r = self._result(include_corner_vents=True, max_vents=12)
        reasons = [v.reason for v in r.vent_locations]
        assert "sharp_corner" in reasons

    def test_disable_parting_ribs(self):
        r = self._result(include_parting_ribs=False)
        reasons = [v.reason for v in r.vent_locations]
        assert "parting_rib" not in reasons

    def test_disable_corner_vents(self):
        r = self._result(include_corner_vents=False)
        reasons = [v.reason for v in r.vent_locations]
        assert "sharp_corner" not in reasons

    def test_max_vents_cap(self):
        r = self._result(max_vents=3)
        assert r.count <= 3
        assert len(r.vent_positions) <= 3


# ---------------------------------------------------------------------------
# Thin elongated part: 200x20x5 gated at one end (Beaumont §8.4.1)
# ---------------------------------------------------------------------------

class TestElongatedPartSingleGate:
    """
    Depth bar: 200x20x5 mm part, gate at (0, 10, 5) -- left end center top.
    Last-fill zone = right end corners (x=200).
    Highest-priority vents must be at the far end (x approx 200).
    """

    GATE = (0.0, 10.0, 5.0)
    BBOX = CavityBbox(200.0, 20.0, 5.0)

    def _result(self, **kw) -> VentPlacementResult:
        return optimize_vent_placement(self.BBOX, self.GATE, **kw)

    def test_far_end_vents_are_last_fill(self):
        r = self._result()
        last_fill = [v for v in r.vent_locations if v.reason == "last_fill"]
        assert last_fill, "No last-fill vents found"
        for v in last_fill:
            assert v.position[0] == pytest.approx(200.0, abs=0.01), \
                f"Expected last-fill at x=200 (far end), got x={v.position[0]}"

    def test_primary_vent_at_far_end(self):
        r = self._result()
        primary = r.vent_locations[0]
        assert primary.position[0] == pytest.approx(200.0, abs=0.01)

    def test_distance_from_gate_large(self):
        r = self._result()
        last_fill = [v for v in r.vent_locations if v.reason == "last_fill"]
        max_dist = max(v.distance_from_gate_mm for v in last_fill)
        assert max_dist >= 195.0, \
            f"Expected >=195 mm distance for elongated part, got {max_dist:.1f} mm"

    def test_count_positive(self):
        r = self._result()
        assert r.count > 0


# ---------------------------------------------------------------------------
# Material-specific depth tests (oracle: Beaumont Table 8.4)
# ---------------------------------------------------------------------------

class TestMaterialDepths:
    def _depth_info(self, material: str) -> dict:
        bbox = CavityBbox(100.0, 50.0, 20.0)
        gate = (50.0, 25.0, 20.0)
        r = optimize_vent_placement(bbox, gate, material=material)
        return r.depth_per_material

    def test_abs_depth_025_040(self):
        dm = self._depth_info("ABS")
        assert dm["depth_min_mm"] == pytest.approx(0.025)
        assert dm["depth_max_mm"] == pytest.approx(0.040)
        assert dm["is_crystalline"] is False

    def test_pp_depth_020_030(self):
        dm = self._depth_info("PP")
        assert dm["depth_min_mm"] == pytest.approx(0.020)
        assert dm["depth_max_mm"] == pytest.approx(0.030)
        assert dm["is_crystalline"] is False

    def test_pom_depth_013_020_crystalline(self):
        dm = self._depth_info("POM")
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["depth_max_mm"] == pytest.approx(0.020)
        assert dm["is_crystalline"] is True

    def test_pa66_depth_013_020_crystalline(self):
        dm = self._depth_info("PA66")
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["depth_max_mm"] == pytest.approx(0.020)
        assert dm["is_crystalline"] is True

    def test_pa6_depth_013_020_crystalline(self):
        dm = self._depth_info("PA6")
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["depth_max_mm"] == pytest.approx(0.020)
        assert dm["is_crystalline"] is True

    def test_pbt_depth_013_020_crystalline(self):
        dm = self._depth_info("PBT")
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["depth_max_mm"] == pytest.approx(0.020)
        assert dm["is_crystalline"] is True

    def test_pet_depth_013_020_crystalline(self):
        dm = self._depth_info("PET")
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["depth_max_mm"] == pytest.approx(0.020)
        assert dm["is_crystalline"] is True

    def test_pc_depth_025_035(self):
        dm = self._depth_info("PC")
        assert dm["depth_min_mm"] == pytest.approx(0.025)
        assert dm["depth_max_mm"] == pytest.approx(0.035)
        assert dm["is_crystalline"] is False

    def test_lcp_depth_010_015_crystalline(self):
        dm = self._depth_info("LCP")
        assert dm["depth_min_mm"] == pytest.approx(0.010)
        assert dm["depth_max_mm"] == pytest.approx(0.015)
        assert dm["is_crystalline"] is True

    def test_tpe_depth_020_030(self):
        dm = self._depth_info("TPE")
        assert dm["depth_min_mm"] == pytest.approx(0.020)
        assert dm["depth_max_mm"] == pytest.approx(0.030)
        assert dm["is_crystalline"] is False

    def test_all_vents_have_correct_depth_min(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        gate = (50.0, 25.0, 20.0)
        r = optimize_vent_placement(bbox, gate, material="POM")
        for v in r.vent_locations:
            assert v.depth_min_mm == pytest.approx(0.013)
            assert v.depth_max_mm == pytest.approx(0.020)


# ---------------------------------------------------------------------------
# Avoid-zone constraint
# ---------------------------------------------------------------------------

class TestAvoidZone:
    def _bbox(self) -> CavityBbox:
        return CavityBbox(100.0, 50.0, 20.0)

    def test_avoid_zone_removes_candidates(self):
        bbox = self._bbox()
        gate = (50.0, 25.0, 20.0)
        r = optimize_vent_placement(
            bbox, gate, avoid_functional_zones=[(0.0, 0.0, 0.0, 3.0)]
        )
        for v in r.vent_locations:
            dist = math.sqrt(v.position[0] ** 2 + v.position[1] ** 2 + v.position[2] ** 2)
            assert dist > 3.0, \
                f"Vent at {v.position} is inside the avoid zone (radius 3 mm)"

    def test_all_candidates_in_avoid_zone_produces_empty_or_others(self):
        bbox = self._bbox()
        gate = (50.0, 25.0, 20.0)
        r = optimize_vent_placement(
            bbox, gate, avoid_functional_zones=[(50.0, 25.0, 10.0, 200.0)]
        )
        assert isinstance(r, VentPlacementResult)
        assert "no vent" in " ".join(r.warnings).lower() or r.count == 0


# ---------------------------------------------------------------------------
# max_vents cap
# ---------------------------------------------------------------------------

class TestMaxVents:
    def test_max_vents_1(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        r = optimize_vent_placement(bbox, (50.0, 25.0, 20.0), max_vents=1)
        assert r.count == 1
        assert len(r.vent_positions) == 1

    def test_max_vents_3(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        r = optimize_vent_placement(bbox, (50.0, 25.0, 20.0), max_vents=3)
        assert r.count <= 3

    def test_max_vents_zero_raises(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        with pytest.raises(ValueError):
            optimize_vent_placement(bbox, (50.0, 25.0, 20.0), max_vents=0)


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def test_last_fill_before_parting_rib(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        gate = (50.0, 25.0, 20.0)
        r = optimize_vent_placement(bbox, gate)
        priorities = [v.priority for v in r.vent_locations]
        assert priorities[0] == 1, "First vent should be priority 1 (last_fill)"

    def test_parting_rib_before_sharp_corner(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        gate = (50.0, 25.0, 20.0)
        r = optimize_vent_placement(bbox, gate)
        priorities = [v.priority for v in r.vent_locations]
        if 2 in priorities and 3 in priorities:
            first_2 = priorities.index(2)
            first_3 = priorities.index(3)
            assert first_2 < first_3, "parting_rib (p2) should come before sharp_corner (p3)"


# ---------------------------------------------------------------------------
# LLM tool round-trip
# ---------------------------------------------------------------------------

class TestVentPlacementTool:
    def test_basic_100x50x20_abs(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0, "gate_z": 20.0,
            "material": "ABS",
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is True
        assert result["count"] >= 1
        assert len(result["vent_positions"]) == result["count"]

    def test_pom_crystalline_depth(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0, "gate_z": 20.0,
            "material": "POM",
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is True
        dm = result["depth_per_material"]
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["depth_max_mm"] == pytest.approx(0.020)
        assert dm["is_crystalline"] is True

    def test_pa66_crystalline_depth(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 80.0, "depth_mm": 40.0, "height_mm": 15.0,
            "gate_x": 40.0, "gate_y": 20.0, "gate_z": 15.0,
            "material": "PA66",
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is True
        dm = result["depth_per_material"]
        assert dm["depth_min_mm"] == pytest.approx(0.013)
        assert dm["is_crystalline"] is True

    def test_max_vents_param(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0, "gate_z": 20.0,
            "max_vents": 2,
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is True
        assert result["count"] <= 2

    def test_honest_flag_in_warnings(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0, "gate_z": 20.0,
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        combined = " ".join(result.get("warnings", [])).lower()
        assert "heuristic" in combined or "honest" in combined

    def test_reference_field_contains_beaumont(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0, "gate_z": 20.0,
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert "Beaumont" in result.get("reference", "")

    def test_missing_gate_z_returns_error(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0,
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is not True
        assert "error" in result

    def test_zero_width_returns_error(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 0.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 0.0, "gate_y": 25.0, "gate_z": 20.0,
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is not True

    def test_avoid_zone_serialized(self):
        from kerf_mold.vent_placement_tool import run_mold_optimize_vent_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "gate_x": 50.0, "gate_y": 25.0, "gate_z": 20.0,
            "avoid_zones": [[0.0, 0.0, 0.0, 2.0]],
        }
        result = json.loads(_run(run_mold_optimize_vent_placement(args, CTX)))
        assert result.get("ok") is True


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    def test_vent_tool_registered(self):
        from kerf_mold.plugin import register
        from fastapi import FastAPI

        class _MockReg:
            def __init__(self):
                self.registered = {}

            def register(self, name, spec, handler):
                self.registered[name] = (spec, handler)

        class _MockCtx:
            def __init__(self):
                self.tools = _MockReg()

        app = FastAPI()
        ctx = _MockCtx()
        _run(register(app, ctx))
        assert "mold_optimize_vent_placement" in ctx.tools.registered, \
            "mold_optimize_vent_placement not found in registered tools"
