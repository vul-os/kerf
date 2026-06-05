"""
Tests for the LLM tool runners in kerf_cad_core.jewelry.cam_wax.

Coverage:
  run_jewelry_wax_plan_routing   — success, missing fields, bad JSON, ok=False path
  run_jewelry_wax_list_tools     — success, empty library, unknown tool type
  run_jewelry_wax_estimate_cycle_time — success, missing plan, bad plan

All tests are pure-Python and hermetic: no OCC, no DB, no network.
"""
from __future__ import annotations

import asyncio
import json
import pytest

from kerf_cad_core.jewelry.cam_wax import (
    run_jewelry_wax_plan_routing,
    run_jewelry_wax_list_tools,
    run_jewelry_wax_estimate_cycle_time,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro) -> dict:
    loop = asyncio.new_event_loop()
    try:
        return json.loads(loop.run_until_complete(coro))
    finally:
        loop.close()


# Minimal valid inputs
RING_PIECE = {
    "type": "ring",
    "inner_diameter_mm": 17.5,
    "height_mm": 8.0,
    "width_mm": 20.0,
    "depth_mm": 20.0,
}

MACHINE_4AXIS = {
    "type": "4axis_indexed",
    "pivot_mm": 50.0,
}

MACHINE_5AXIS = {
    "type": "5axis_trunnion",
    "pivot_mm": 60.0,
    "a_lo_deg": -120.0,
    "a_hi_deg": 30.0,
    "rapid_mm_min": 10000.0,
    "accel_mm_s2": 500.0,
}

TOOL_LIBRARY = [
    {
        "name": "rough_flat_3mm",
        "type": "flat_end",
        "diameter_mm": 3.0,
        "flutes": 4,
        "stickout_mm": 20.0,
        "vc_m_min": 45.0,
        "chip_load_mm": 0.020,
    },
    {
        "name": "finish_ball_1mm",
        "type": "ball_nose",
        "diameter_mm": 1.0,
        "flutes": 2,
        "stickout_mm": 15.0,
        "vc_m_min": 60.0,
        "chip_load_mm": 0.010,
    },
]

STOCK_BLOCK = {"width_mm": 22.0, "depth_mm": 22.0, "height_mm": 16.0}

CTX = None  # ProjectCtx not needed by these tools (they call plan_wax_routing directly)


def _plan_args(**overrides) -> bytes:
    base = {
        "piece": RING_PIECE,
        "machine_kinematics": MACHINE_4AXIS,
        "tool_library": TOOL_LIBRARY,
        "stock_block": STOCK_BLOCK,
    }
    base.update(overrides)
    return json.dumps(base).encode()


# ---------------------------------------------------------------------------
# run_jewelry_wax_plan_routing
# ---------------------------------------------------------------------------

class TestWaxPlanRoutingTool:
    def test_success_4axis_ring(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        assert r.get("ok") is True, r
        assert "roughing_strategy" in r
        assert "finishing_strategy" in r
        assert "gcode_stubs" in r
        assert isinstance(r["gcode_stubs"], list)
        assert len(r["gcode_stubs"]) > 0
        assert "cycle_time_s" in r
        assert r["cycle_time_s"] >= 0.0

    def test_success_5axis_ring(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(machine_kinematics=MACHINE_5AXIS)))
        assert r.get("ok") is True, r
        assert r["machine_type"] == "5axis_trunnion"

    def test_success_pendant(self):
        piece = {"type": "pendant", "height_mm": 12.0, "width_mm": 25.0, "depth_mm": 15.0}
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(piece=piece)))
        assert r.get("ok") is True, r

    def test_missing_piece_returns_ok_false(self):
        args = json.dumps({
            "machine_kinematics": MACHINE_4AXIS,
            "tool_library": TOOL_LIBRARY,
            "stock_block": STOCK_BLOCK,
        }).encode()
        r = _run(run_jewelry_wax_plan_routing(CTX, args))
        assert r.get("ok") is False or "reason" in r

    def test_missing_machine_returns_ok_false(self):
        args = json.dumps({
            "piece": RING_PIECE,
            "tool_library": TOOL_LIBRARY,
            "stock_block": STOCK_BLOCK,
        }).encode()
        r = _run(run_jewelry_wax_plan_routing(CTX, args))
        assert r.get("ok") is False or "reason" in r

    def test_missing_tool_library_returns_ok_false(self):
        args = json.dumps({
            "piece": RING_PIECE,
            "machine_kinematics": MACHINE_4AXIS,
            "stock_block": STOCK_BLOCK,
        }).encode()
        r = _run(run_jewelry_wax_plan_routing(CTX, args))
        assert r.get("ok") is False or "reason" in r

    def test_missing_stock_block_returns_ok_false(self):
        args = json.dumps({
            "piece": RING_PIECE,
            "machine_kinematics": MACHINE_4AXIS,
            "tool_library": TOOL_LIBRARY,
        }).encode()
        r = _run(run_jewelry_wax_plan_routing(CTX, args))
        assert r.get("ok") is False or "reason" in r

    def test_invalid_json_returns_error(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, b"not json!!"))
        # cam_wax uses its own err_payload stub → {"ok": False, "reason": ...}
        # or kerf_chat's err_payload → {"error": ..., "code": ...}
        assert r.get("ok") is False or "error" in r

    def test_tool_list_present_in_result(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        assert "tool_list" in r
        assert isinstance(r["tool_list"], list)
        assert len(r["tool_list"]) >= 1

    def test_collision_warnings_key_present(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        assert "collision_warnings" in r
        assert isinstance(r["collision_warnings"], list)

    def test_roughing_has_pass_count(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        rough = r["roughing_strategy"]
        assert rough["pass_count"] >= 1

    def test_custom_step_down(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(step_down_mm=2.0)))
        assert r.get("ok") is True
        # Larger step-down → fewer passes
        r_fine = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(step_down_mm=0.5)))
        assert r_fine.get("ok") is True
        assert r_fine["roughing_strategy"]["pass_count"] >= r["roughing_strategy"]["pass_count"]

    def test_custom_prong_tilt(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(prong_tilt_deg=15.0)))
        assert r.get("ok") is True
        fin = r["finishing_strategy"]
        assert fin["prong_tilt_deg"] == 15.0

    def test_zero_step_down_returns_ok_false(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(step_down_mm=0.0)))
        assert r.get("ok") is False

    def test_gcode_stubs_contain_metric_declaration(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        gcode = "\n".join(r["gcode_stubs"])
        assert "G21" in gcode

    def test_gcode_stubs_contain_m30_end(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        gcode = "\n".join(r["gcode_stubs"])
        assert "M30" in gcode

    def test_fishtail_tool_in_list_if_provided(self):
        tools_with_fishtail = TOOL_LIBRARY + [{
            "name": "fishtail_1mm",
            "type": "fishtail",
            "diameter_mm": 1.0,
            "flutes": 2,
            "stickout_mm": 12.0,
        }]
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(tool_library=tools_with_fishtail)))
        assert r.get("ok") is True
        tool_types = [t["type"] for t in r["tool_list"]]
        assert "fishtail" in tool_types

    def test_cycle_time_positive_for_ring(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        assert r["cycle_time_s"] > 0.0

    def test_bore_passes_present_for_ring_with_5axis(self):
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(machine_kinematics=MACHINE_5AXIS)))
        assert r.get("ok") is True
        fin = r["finishing_strategy"]
        assert fin["has_bore_finishing"] is True
        assert len(fin["bore_passes"]) > 0

    def test_bore_passes_absent_for_pendant(self):
        piece = {"type": "pendant", "height_mm": 12.0, "width_mm": 25.0, "depth_mm": 15.0}
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args(
            piece=piece,
            machine_kinematics=MACHINE_5AXIS,
        )))
        assert r.get("ok") is True
        assert r["finishing_strategy"]["has_bore_finishing"] is False


# ---------------------------------------------------------------------------
# run_jewelry_wax_list_tools
# ---------------------------------------------------------------------------

def _list_tools_ok(r: dict) -> bool:
    """list_tools uses ok_payload which returns flat dict — check absence of 'error'."""
    return "error" not in r and "tools" in r


class TestWaxListToolsTool:
    def test_success_returns_tool_summaries(self):
        args = json.dumps({"tool_library": TOOL_LIBRARY}).encode()
        r = _run(run_jewelry_wax_list_tools(CTX, args))
        assert _list_tools_ok(r), r
        assert r["count"] == len(TOOL_LIBRARY)

    def test_tool_summary_has_required_keys(self):
        args = json.dumps({"tool_library": TOOL_LIBRARY}).encode()
        r = _run(run_jewelry_wax_list_tools(CTX, args))
        assert _list_tools_ok(r)
        for t in r["tools"]:
            for key in ("name", "type", "diameter_mm", "flutes", "stickout_mm"):
                assert key in t, f"Missing key {key!r} in tool summary"

    def test_missing_tool_library_returns_error(self):
        r = _run(run_jewelry_wax_list_tools(CTX, json.dumps({}).encode()))
        # Missing tool_library → {"ok": False, "reason": ...} from the inline stub
        assert r.get("ok") is False or "error" in r

    def test_invalid_json(self):
        r = _run(run_jewelry_wax_list_tools(CTX, b"[bad json"))
        assert "error" in r or r.get("ok") is False

    def test_unknown_tool_type_returns_error(self):
        bad_tool = {"name": "laser", "type": "laser_cutter", "diameter_mm": 2.0, "flutes": 0, "stickout_mm": 50.0}
        args = json.dumps({"tool_library": [bad_tool]}).encode()
        r = _run(run_jewelry_wax_list_tools(CTX, args))
        # Unknown type should fail validation → {"ok": False, "reason": ...}
        assert r.get("ok") is False or "error" in r

    def test_single_tool_count_is_one(self):
        args = json.dumps({"tool_library": [TOOL_LIBRARY[0]]}).encode()
        r = _run(run_jewelry_wax_list_tools(CTX, args))
        assert _list_tools_ok(r), r
        assert r["count"] == 1

    def test_computed_rpm_present_when_cncfeeds_available(self):
        """If cncfeeds is available, each tool gets computed_rpm."""
        try:
            from kerf_cad_core.cncfeeds.calc import spindle_rpm  # noqa: F401
            cncfeeds_ok = True
        except ImportError:
            cncfeeds_ok = False

        args = json.dumps({"tool_library": TOOL_LIBRARY}).encode()
        r = _run(run_jewelry_wax_list_tools(CTX, args))
        if cncfeeds_ok and _list_tools_ok(r):
            for t in r["tools"]:
                assert "computed_rpm" in t, "cncfeeds available but computed_rpm missing"


# ---------------------------------------------------------------------------
# run_jewelry_wax_estimate_cycle_time
# ---------------------------------------------------------------------------

def _ct_ok(r: dict) -> bool:
    """estimate_cycle_time uses ok_payload → flat dict without 'error'."""
    return "error" not in r and "total_s" in r


class TestWaxEstimateCycleTimeTool:
    def _get_plan(self) -> dict:
        r = _run(run_jewelry_wax_plan_routing(CTX, _plan_args()))
        assert r.get("ok") is True
        return r

    def test_success_returns_total_s(self):
        plan = self._get_plan()
        args = json.dumps({"plan": plan}).encode()
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, args))
        assert _ct_ok(r), r
        assert r["total_s"] >= 0.0

    def test_total_min_correct(self):
        plan = self._get_plan()
        args = json.dumps({"plan": plan}).encode()
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, args))
        assert _ct_ok(r)
        assert r["total_min"] == pytest.approx(r["total_s"] / 60.0, rel=1e-3)

    def test_roughing_pass_count_matches(self):
        plan = self._get_plan()
        args = json.dumps({"plan": plan}).encode()
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, args))
        assert _ct_ok(r)
        assert r["roughing_pass_count"] == plan["roughing_strategy"]["pass_count"]

    def test_missing_plan_returns_error(self):
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, json.dumps({}).encode()))
        # Missing plan → {"ok": False, "reason": ...} from inline stub
        assert r.get("ok") is False or "error" in r

    def test_bad_plan_returns_error(self):
        args = json.dumps({"plan": {"ok": False, "reason": "bad plan"}}).encode()
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, args))
        assert r.get("ok") is False or "error" in r

    def test_invalid_json_returns_error(self):
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, b"not json!"))
        assert "error" in r or r.get("ok") is False

    def test_custom_rapid_rate(self):
        plan = self._get_plan()
        args = json.dumps({"plan": plan, "rapid_mm_min": 5000.0}).encode()
        r = _run(run_jewelry_wax_estimate_cycle_time(CTX, args))
        assert _ct_ok(r), r
        assert r["total_s"] >= 0.0
        # Default rate comparison
        args_default = json.dumps({"plan": plan}).encode()
        r_default = _run(run_jewelry_wax_estimate_cycle_time(CTX, args_default))
        assert _ct_ok(r_default)
        assert r_default["total_s"] >= 0.0
