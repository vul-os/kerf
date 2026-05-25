"""
Dispatch tests for the mold_cooling_analysis LLM tool.

Calls the handler and asserts sane physics payload.
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

from kerf_mold.cooling_tool import run_mold_cooling_analysis


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_SINGLE_CHANNEL = [{"diameter_mm": 10.0, "length_mm": 200.0}]
_TWO_CHANNELS = [
    {"diameter_mm": 8.0, "length_mm": 150.0, "label": "C1"},
    {"diameter_mm": 8.0, "length_mm": 150.0, "label": "C2"},
]


class TestMoldCoolingAnalysisTool:
    def test_single_channel_defaults(self):
        result_str = _run(run_mold_cooling_analysis(
            {"channels": _SINGLE_CHANNEL},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert result["n_channels"] == 1
        assert result["effective_htc_W_m2K"] > 0.0
        assert len(result["channel_results"]) == 1
        ch = result["channel_results"][0]
        assert ch["reynolds"] > 0.0
        assert ch["flow_regime"] in ("laminar", "transitional", "turbulent")

    def test_series_two_channels(self):
        result_str = _run(run_mold_cooling_analysis(
            {"channels": _TWO_CHANNELS, "layout": "series", "flow_rate_lpm": 8.0},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert result["n_channels"] == 2
        assert result["layout"] == "series"

    def test_parallel_layout(self):
        result_str = _run(run_mold_cooling_analysis(
            {"channels": _TWO_CHANNELS, "layout": "parallel"},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert result["layout"] == "parallel"

    def test_cooling_time_present(self):
        result_str = _run(run_mold_cooling_analysis(
            {"channels": _SINGLE_CHANNEL, "polymer": "ABS", "part_thickness_mm": 3.0},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        t_cool = result.get("cooling_time_s")
        assert t_cool is not None
        assert t_cool > 0.0

    def test_turbulent_flow_high_rate(self):
        result_str = _run(run_mold_cooling_analysis(
            {"channels": [{"diameter_mm": 8.0, "length_mm": 300.0}], "flow_rate_lpm": 20.0},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        ch = result["channel_results"][0]
        assert ch["reynolds"] > 2300.0
        assert ch["flow_regime"] in ("transitional", "turbulent")

    def test_empty_channels_returns_error(self):
        result_str = _run(run_mold_cooling_analysis({"channels": []}, ctx=None))
        result = json.loads(result_str)
        assert "error" in result

    def test_pressure_drop_positive(self):
        result_str = _run(run_mold_cooling_analysis(
            {"channels": _SINGLE_CHANNEL, "flow_rate_lpm": 5.0},
            ctx=None,
        ))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert result["total_pressure_drop_kPa"] >= 0.0
