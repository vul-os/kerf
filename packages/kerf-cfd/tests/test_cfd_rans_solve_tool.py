"""
Dispatch tests for the cfd_rans_solve LLM tool.

Calls the tool and asserts a sane JSON-serialisable payload.
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

from kerf_cfd.rans_tool import run_cfd_rans_solve_sync, run_cfd_rans_solve


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCfdRansSolveSync:
    def test_lid_cavity_defaults(self):
        result = run_cfd_rans_solve_sync()
        assert result["ok"] is True
        assert result["case"] == "lid_driven_cavity"
        assert result["Re"] == 100.0
        assert isinstance(result["converged"], bool)
        assert result["n_iter"] > 0
        assert result["max_continuity_residual"] >= 0.0
        assert len(result["centreline_u_sample"]) > 0

    def test_lid_cavity_ghia_validation(self):
        result = run_cfd_rans_solve_sync(case="lid_driven_cavity", Re=100.0, nx=32, ny=32)
        assert result["ok"] is True
        ghia = result.get("ghia_validation")
        assert ghia is not None
        assert "within_tolerance" in ghia
        assert ghia["within_tolerance"] is True

    def test_channel_case(self):
        result = run_cfd_rans_solve_sync(case="channel", Re=50.0, nx=16, ny=16)
        assert result["ok"] is True
        assert result["case"] == "channel"
        assert result["n_iter"] > 0

    def test_custom_grid(self):
        result = run_cfd_rans_solve_sync(nx=16, ny=16, Re=50.0, max_outer=500)
        assert result["ok"] is True
        assert result["nx"] == 16 and result["ny"] == 16

    def test_bad_case_returns_error(self):
        result = run_cfd_rans_solve_sync(case="navier_stokes_3d")
        assert result["ok"] is False
        assert result.get("code") == "BAD_ARGS"

    def test_bad_re_returns_error(self):
        result = run_cfd_rans_solve_sync(Re=-10.0)
        assert result["ok"] is False
        assert result.get("code") == "BAD_ARGS"

    def test_bad_nx_too_large(self):
        result = run_cfd_rans_solve_sync(nx=512)
        assert result["ok"] is False
        assert result.get("code") == "BAD_ARGS"


class TestCfdRansSolveAsync:
    def test_async_happy_path(self):
        result_str = _run(run_cfd_rans_solve({"nx": 16, "ny": 16, "Re": 100.0, "max_outer": 500}, ctx=None))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert result["case"] == "lid_driven_cavity"

    def test_async_bad_case(self):
        result_str = _run(run_cfd_rans_solve({"case": "bad_case"}, ctx=None))
        result = json.loads(result_str)
        assert result.get("error") is not None
