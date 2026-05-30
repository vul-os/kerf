"""
Tests for kerf_mold.gate_placement — MOLD-GATE-PLACEMENT-OPTIMIZE

Covers:
  - 100×50×20 box: top-center gate recommended (lowest composite score)
  - Thin elongated part: multi-gate suggested
  - Constraint at functional surface: gate moves away from forbidden face
  - Avoid-zone constraint removes candidate
  - Multi-gate request: returns N gates
  - Balance score in [0, 1]
  - Flow metrics are finite and positive
  - LLM tool round-trip (mold_optimize_gate_placement)
  - Plugin registration
  - Input validation errors
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_mold.gate_placement import (
    CavityBbox,
    GateConstraint,
    GatePlacementResult,
    optimize_gate_placement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# CavityBbox
# ---------------------------------------------------------------------------

class TestCavityBbox:
    def test_center(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        assert bbox.center == pytest.approx((50.0, 25.0, 10.0))

    def test_corners_count(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        assert len(bbox.corners()) == 8

    def test_zero_width_raises(self):
        with pytest.raises(ValueError):
            CavityBbox(0.0, 50.0, 20.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError):
            CavityBbox(100.0, -1.0, 20.0)

    def test_zero_height_raises(self):
        with pytest.raises(ValueError):
            CavityBbox(100.0, 50.0, 0.0)


# ---------------------------------------------------------------------------
# GateConstraint
# ---------------------------------------------------------------------------

class TestGateConstraint:
    def test_invalid_face_raises(self):
        with pytest.raises(ValueError, match="unrecognised"):
            GateConstraint(functional_faces=["diagonal"])

    def test_valid_faces_accepted(self):
        c = GateConstraint(functional_faces=["top", "bottom", "left"])
        assert "top" in c.functional_faces


# ---------------------------------------------------------------------------
# Core: 100×50×20 box
# ---------------------------------------------------------------------------

class TestBox100x50x20:
    """
    Depth bar: optimal gate at top-center (50, 25, 20).
    Max flow to farthest corner ≈ sqrt(50² + 25² + 20²) ≈ 59.6 mm.
    Side gate at (0, 25, 10): max flow ≈ sqrt(100² + 25² + 10²) ≈ 103.8 mm.
    Top-center must win.
    """

    def _result(self, **kw) -> GatePlacementResult:
        bbox = CavityBbox(100.0, 50.0, 20.0)
        return optimize_gate_placement(bbox, **kw)

    def test_returns_result(self):
        r = self._result()
        assert isinstance(r, GatePlacementResult)

    def test_one_gate_by_default(self):
        r = self._result()
        assert r.gate_count == 1
        assert len(r.gate_positions) == 1

    def test_top_center_is_recommended(self):
        """Top-center (50, 25, 20) should be the primary recommendation."""
        r = self._result()
        pos = r.gate_positions[0]
        # x ≈ 50 (centre of width=100), y ≈ 25 (centre of depth=50), z=20 (top)
        assert pos[0] == pytest.approx(50.0, abs=1.0)
        assert pos[1] == pytest.approx(25.0, abs=1.0)
        assert pos[2] == pytest.approx(20.0, abs=0.5)

    def test_top_center_max_flow_approx(self):
        """Max flow from top-center should be ≈ 59.6 mm (Beaumont §7 reference)."""
        r = self._result()
        max_f = r.flow_metrics[0]["max_flow_mm"]
        assert max_f == pytest.approx(59.16, abs=2.0), \
            f"Expected ≈59.6 mm, got {max_f:.2f} mm"

    def test_composite_score_low_for_top_center(self):
        """Top-center should have the lowest composite score."""
        r = self._result()
        assert r.flow_metrics[0]["composite_score"] == pytest.approx(0.0, abs=0.01)

    def test_balance_score_in_range(self):
        r = self._result()
        assert 0.0 <= r.balance_score <= 1.0

    def test_flow_metrics_finite(self):
        r = self._result()
        fm = r.flow_metrics[0]
        for key in ("max_flow_mm", "mean_flow_mm", "balance_std_mm"):
            assert math.isfinite(fm[key])
            assert fm[key] >= 0.0

    def test_recommendations_not_empty(self):
        r = self._result()
        assert len(r.recommendations) >= 1

    def test_honest_flag_in_warnings(self):
        r = self._result()
        combined = " ".join(r.warnings).lower()
        assert "heuristic" in combined or "honest" in combined or "viscosity" in combined

    def test_candidates_evaluated_positive(self):
        r = self._result()
        assert r.candidates_evaluated >= 1


# ---------------------------------------------------------------------------
# Thin elongated part: multi-gate suggested
# ---------------------------------------------------------------------------

class TestThinElongatedPart:
    """
    Part: 300×20×5 mm — very long, narrow, thin.
    Single gate → max flow / min_dim ≈ >5 → multi_gate_suggested = True.
    """

    def _bbox(self) -> CavityBbox:
        return CavityBbox(300.0, 20.0, 5.0)

    def test_multi_gate_suggested_for_elongated_part(self):
        r = optimize_gate_placement(self._bbox())
        assert r.multi_gate_suggested is True, \
            "Expected multi_gate_suggested=True for 300×20×5 part"

    def test_multi_gate_request(self):
        r = optimize_gate_placement(self._bbox(), gate_count=2)
        assert r.gate_count == 2
        assert len(r.gate_positions) == 2

    def test_two_gates_further_apart_than_min_sep(self):
        """Two gates should not be placed at identical positions."""
        r = optimize_gate_placement(self._bbox(), gate_count=2)
        p0, p1 = r.gate_positions
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(p0, p1)))
        assert dist > 0.5, f"Gates too close: {dist:.2f} mm"


# ---------------------------------------------------------------------------
# Constraint: functional surface → gate moves away
# ---------------------------------------------------------------------------

class TestFunctionalSurfaceConstraint:
    """
    Forbid 'top' face: gate must land on a side or bottom face.
    """

    def _result(self) -> GatePlacementResult:
        bbox = CavityBbox(100.0, 50.0, 20.0)
        c = GateConstraint(functional_faces=["top"])
        return optimize_gate_placement(bbox, constraints=c)

    def test_gate_not_on_top_face(self):
        r = self._result()
        fm = r.flow_metrics[0]
        assert fm["face"] != "top", \
            f"Expected gate NOT on 'top' face, got '{fm['face']}'"

    def test_recommendation_mentions_avoided_faces(self):
        r = self._result()
        combined = " ".join(r.recommendations)
        assert "top" in combined.lower() or "avoided" in combined.lower()

    def test_result_still_valid(self):
        r = self._result()
        assert isinstance(r, GatePlacementResult)
        assert r.gate_count == 1
        assert len(r.gate_positions) == 1


# ---------------------------------------------------------------------------
# Avoid-zone constraint: removes candidates in zone
# ---------------------------------------------------------------------------

class TestAvoidZoneConstraint:
    """
    Place an avoid zone at the top-center of the 100×50×20 box.
    The top-center candidate should be removed.
    """

    def _result(self) -> GatePlacementResult:
        bbox = CavityBbox(100.0, 50.0, 20.0)
        # Avoid zone centred at top-center (50, 25, 20) with radius 5 mm
        c = GateConstraint(avoid_zones=[(50.0, 25.0, 20.0, 5.0)])
        return optimize_gate_placement(bbox, constraints=c)

    def test_gate_not_at_top_center(self):
        r = self._result()
        pos = r.gate_positions[0]
        # Top-center = (50, 25, 20); gate must be elsewhere
        dist = math.sqrt((pos[0] - 50.0) ** 2 + (pos[1] - 25.0) ** 2 + (pos[2] - 20.0) ** 2)
        assert dist > 5.0, \
            f"Gate should be outside the avoid zone (radius=5), dist={dist:.2f}"

    def test_result_still_has_gate(self):
        r = self._result()
        assert r.gate_count == 1
        assert len(r.gate_positions) == 1


# ---------------------------------------------------------------------------
# Multi-gate: 3 gates
# ---------------------------------------------------------------------------

class TestThreeGates:
    def test_three_gates_returned(self):
        bbox = CavityBbox(200.0, 60.0, 15.0)
        r = optimize_gate_placement(bbox, gate_count=3)
        assert r.gate_count == 3
        assert len(r.gate_positions) == 3
        assert len(r.flow_metrics) == 3

    def test_all_positions_inside_or_on_bbox(self):
        bbox = CavityBbox(200.0, 60.0, 15.0)
        r = optimize_gate_placement(bbox, gate_count=3)
        for pos in r.gate_positions:
            assert -0.01 <= pos[0] <= 200.01
            assert -0.01 <= pos[1] <= 60.01
            assert -0.01 <= pos[2] <= 15.01


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_gate_count_zero_raises(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        with pytest.raises(ValueError):
            optimize_gate_placement(bbox, gate_count=0)

    def test_negative_gate_count_raises(self):
        bbox = CavityBbox(100.0, 50.0, 20.0)
        with pytest.raises(ValueError):
            optimize_gate_placement(bbox, gate_count=-1)

    def test_invalid_constraint_face_raises(self):
        with pytest.raises(ValueError):
            GateConstraint(functional_faces=["diagonal"])


# ---------------------------------------------------------------------------
# All faces forbidden: fallback to bbox centre
# ---------------------------------------------------------------------------

class TestAllFacesForbidden:
    def test_fallback_when_all_faces_forbidden(self):
        bbox = CavityBbox(50.0, 50.0, 50.0)
        c = GateConstraint(functional_faces=["top", "bottom", "left", "right", "front", "back"])
        r = optimize_gate_placement(bbox, constraints=c)
        # Should not raise; returns some result
        assert r.gate_count >= 1
        assert isinstance(r.gate_positions[0], tuple)


# ---------------------------------------------------------------------------
# LLM tool round-trip
# ---------------------------------------------------------------------------

class TestGatePlacementTool:
    def test_basic_100x50x20(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is True
        assert result["gate_count"] == 1
        assert len(result["gate_positions"]) == 1
        assert len(result["flow_metrics"]) == 1
        # Top-center
        pos = result["gate_positions"][0]
        assert pos[0] == pytest.approx(50.0, abs=1.0)
        assert pos[2] == pytest.approx(20.0, abs=0.5)

    def test_multi_gate_request(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"width_mm": 200.0, "depth_mm": 40.0, "height_mm": 10.0, "gate_count": 2}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is True
        assert result["gate_count"] == 2

    def test_functional_face_constraint(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "functional_faces": ["top"],
        }
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is True
        face = result["flow_metrics"][0]["face"]
        assert face != "top"

    def test_avoid_zone_removes_top_center(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {
            "width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0,
            "avoid_zones": [[50.0, 25.0, 20.0, 5.0]],
        }
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is True
        pos = result["gate_positions"][0]
        dist = math.sqrt((pos[0] - 50.0) ** 2 + (pos[1] - 25.0) ** 2 + (pos[2] - 20.0) ** 2)
        assert dist > 5.0

    def test_balance_score_in_result(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"width_mm": 80.0, "depth_mm": 80.0, "height_mm": 30.0}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is True
        assert 0.0 <= result["balance_score"] <= 1.0

    def test_reference_field_contains_beaumont(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert "Beaumont" in result.get("reference", "")

    def test_honest_flag_in_warnings(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"width_mm": 100.0, "depth_mm": 50.0, "height_mm": 20.0}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        combined = " ".join(result.get("warnings", [])).lower()
        assert "heuristic" in combined or "viscosity" in combined

    def test_missing_width_returns_error(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"depth_mm": 50.0, "height_mm": 20.0}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is not True
        assert "error" in result

    def test_zero_height_returns_error(self):
        from kerf_mold.gate_placement_tool import run_mold_optimize_gate_placement

        args = {"width_mm": 100.0, "depth_mm": 50.0, "height_mm": 0.0}
        result = json.loads(_run(run_mold_optimize_gate_placement(args, CTX)))
        assert result.get("ok") is not True

    def test_plugin_registration(self):
        """mold_optimize_gate_placement is registered by plugin.register()."""
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
        assert "mold_optimize_gate_placement" in ctx.tools.registered
