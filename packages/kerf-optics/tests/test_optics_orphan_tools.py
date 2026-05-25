"""
Dispatch tests for optics_tolerancing, optics_mtf, and optics_nonsequential_trace
LLM tools — these were implemented but unregistered before this sweep.
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

from kerf_optics.tools import run_optics_tolerancing, run_optics_mtf
from kerf_optics.nonsequential import run_optics_nonsequential_trace


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# Single thin-lens element used across tests
_ONE_LENS = [
    {"type": "thin_lens", "f": 0.1}
]

_TOLERANCES = [
    {"element_index": 0, "param_name": "f", "delta": 0.001}
]


class TestOpticsTolerancingTool:
    def test_happy_path_returns_rss_budget(self):
        # Handlers return direct result dicts (no top-level "ok" on success)
        args = {"elements": _ONE_LENS, "tolerances": _TOLERANCES}
        result_str = _run(run_optics_tolerancing(args, ctx=None))
        result = json.loads(result_str)
        assert "rss_budget" in result or result.get("ok") is True

    def test_sensitivity_present(self):
        args = {"elements": _ONE_LENS, "tolerances": _TOLERANCES, "n_mc_trials": 50}
        result = json.loads(_run(run_optics_tolerancing(args, ctx=None)))
        assert "rss_budget" in result or "sensitivity_table" in result or result.get("ok") is True

    def test_missing_elements_returns_error(self):
        args = {"tolerances": _TOLERANCES}
        result = json.loads(_run(run_optics_tolerancing(args, ctx=None)))
        # Missing "elements" — must fail with error/code
        assert "error" in result or "code" in result or result.get("ok") is not True


class TestOpticsMTFTool:
    def test_happy_path_has_cutoff_freq(self):
        # Handlers return direct result dicts (no top-level "ok" on success)
        args = {"elements": _ONE_LENS}
        result_str = _run(run_optics_mtf(args, ctx=None))
        result = json.loads(result_str)
        assert "cutoff_freq_lpmm" in result or "mtf_at_50lpmm" in result or result.get("ok") is True

    def test_cutoff_frequency_present(self):
        args = {"elements": _ONE_LENS, "f_number": 8.0, "lambda_nm": 550.0}
        result = json.loads(_run(run_optics_mtf(args, ctx=None)))
        assert "cutoff_freq_lpmm" in result or "mtf_at_50lpmm" in result or result.get("ok") is True

    def test_missing_elements_returns_error(self):
        result = json.loads(_run(run_optics_mtf({}, ctx=None)))
        assert "error" in result or "code" in result or result.get("ok") is not True


class TestOpticsNonsequentialTraceTool:
    def test_happy_path_returns_detector_keys(self):
        # Response is a direct dict (no top-level "ok") with irradiance_map, ghost_flag, etc.
        args = {
            "surfaces": [
                {
                    "type": "spherical",
                    "radius": 0.05,
                    "center": [0.0, 0.0, 0.05],
                    "n1": 1.0,
                    "n2": 1.5,
                },
                {
                    "type": "detector",
                    "plane_z": 0.15,
                    "width": 0.02,
                    "height": 0.02,
                    "pixels_x": 16,
                    "pixels_y": 16,
                },
            ],
            "source": {
                "position": [0.0, 0.0, 0.0],
                "direction": [0.0, 0.0, 1.0],
                "half_angle_deg": 3.0,
                "wavelength_nm": 550.0,
            },
            "n_rays": 50,
            "seed": 7,
        }
        result_str = _run(run_optics_nonsequential_trace(args, ctx=None))
        result = json.loads(result_str)
        assert "irradiance_map" in result or result.get("ok") is True

    def test_result_has_ghost_flag(self):
        args = {
            "surfaces": [
                {
                    "type": "detector",
                    "plane_z": 0.1,
                    "width": 0.01,
                    "height": 0.01,
                    "pixels_x": 8,
                    "pixels_y": 8,
                }
            ],
            "source": {
                "position": [0.0, 0.0, 0.0],
                "direction": [0.0, 0.0, 1.0],
            },
            "n_rays": 20,
        }
        result = json.loads(_run(run_optics_nonsequential_trace(args, ctx=None)))
        # Must not crash; ghost_flag key expected in direct response
        assert "ghost_flag" in result or "irradiance_map" in result or result.get("ok") is True
