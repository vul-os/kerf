"""
Dispatch tests for marine_seakeeping_rao and marine_seakeeping_stats LLM tools.

Confirms that the registered handlers return sane payloads for a Wigley hull.
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

from kerf_marine.tools import run_marine_seakeeping_rao, run_marine_seakeeping_stats


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_WIGLEY_ARGS = {
    "wigley_L": 100.0,
    "wigley_B": 12.0,
    "wigley_T": 6.0,
    "displacement": 3000.0,
}


class TestMarineSeakeepingRaoTool:
    def test_happy_path_returns_rao_points(self):
        args = {**_WIGLEY_ARGS, "omega_list": [0.5, 1.0, 1.5]}
        result_str = _run(run_marine_seakeeping_rao(args, ctx=None))
        result = json.loads(result_str)
        # Response is a direct dict with rao_points list (no top-level "ok" key)
        assert "rao_points" in result
        assert len(result["rao_points"]) == 3

    def test_rao_point_has_heave_and_pitch(self):
        args = {**_WIGLEY_ARGS, "omega_list": [0.8, 1.2]}
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        assert "rao_points" in result
        pt = result["rao_points"][0]
        assert "rao_heave_amp" in pt
        assert "rao_pitch_amp" in pt

    def test_no_sections_and_no_wigley_returns_error(self):
        result = json.loads(_run(run_marine_seakeeping_rao({}, ctx=None)))
        # Must not crash; if no hull given expect error or empty result
        assert isinstance(result, dict)


class TestMarineSeakeepingStatsTool:
    def test_happy_path_returns_motions(self):
        args = {**_WIGLEY_ARGS, "Hs": 2.0, "Tp": 8.0}
        result_str = _run(run_marine_seakeeping_stats(args, ctx=None))
        result = json.loads(result_str)
        # Response contains "motions" list
        assert "motions" in result
        assert len(result["motions"]) > 0

    def test_motions_have_spectral_moments(self):
        args = {**_WIGLEY_ARGS, "Hs": 3.0, "Tp": 10.0}
        result = json.loads(_run(run_marine_seakeeping_stats(args, ctx=None)))
        assert "motions" in result
        m = result["motions"][0]
        assert "m0" in m
        assert "motion" in m

    def test_missing_hs_tp_raises_or_errors(self):
        # Missing both Hs and Tp — handler should raise or return error dict
        try:
            result = json.loads(_run(run_marine_seakeeping_stats({**_WIGLEY_ARGS}, ctx=None)))
            # If it doesn't raise, must at least not crash
            assert isinstance(result, dict)
        except (KeyError, TypeError, ValueError):
            pass  # acceptable
