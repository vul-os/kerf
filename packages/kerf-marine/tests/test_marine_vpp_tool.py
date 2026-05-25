"""
Dispatch tests for the marine_vpp LLM tool.

Calls the handler and asserts sane speed-polar payload.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_marine.tools import run_marine_vpp


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_YACHT_10M = {
    "L_wl": 9.5,
    "B_wl": 3.0,
    "T_c": 0.6,
    "T_keel": 1.8,
    "displacement_t": 5.0,
    "sail_area_m2": 60.0,
    "hull_name": "test_yacht",
}


class TestMarineVPPTool:
    def test_happy_path_returns_ok(self):
        result_str = _run(run_marine_vpp(
            {**_YACHT_10M, "tws_knots": [10.0], "twa_deg_list": [45.0, 90.0, 135.0]},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert result["hull_name"] == "test_yacht"
        assert result["n_points"] == 3

    def test_polar_points_have_speed(self):
        result_str = _run(run_marine_vpp(
            {**_YACHT_10M, "tws_knots": [8.0, 12.0], "twa_deg_list": [60.0, 90.0]},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        pts = result["polar_points"]
        assert len(pts) == 4
        for pt in pts:
            assert pt["boat_speed_kn"] >= 0.0
            assert 0.0 <= pt["heel_deg"] <= 35.0

    def test_default_twa_list(self):
        result_str = _run(run_marine_vpp(
            {**_YACHT_10M, "tws_knots": [10.0]},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        # default twa list has multiple angles
        assert result["n_points"] > 1

    def test_missing_required_returns_error(self):
        # Missing T_keel
        result_str = _run(run_marine_vpp(
            {"L_wl": 9.5, "B_wl": 3.0, "T_c": 0.6},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert "error" in result

    def test_boat_speed_positive(self):
        result_str = _run(run_marine_vpp(
            {**_YACHT_10M, "tws_knots": [15.0], "twa_deg_list": [90.0]},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        pts = result["polar_points"]
        assert all(p["boat_speed_kn"] >= 0.0 for p in pts)
