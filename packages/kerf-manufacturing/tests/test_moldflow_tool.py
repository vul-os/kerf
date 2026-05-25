"""
Dispatch tests for the manufacturing_moldflow LLM tool.

Uses the same disc and L-shape fixtures as test_moldflow.py.

Oracles
-------
disc fixture  — simply-connected disc fills completely (fill_fraction=1.0,
               short_shot=False) with no weld lines.
lshape fixture — L-shaped part shows at least one weld-line segment near
               the inner corner.
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest
from pathlib import Path

from kerf_manufacturing.tools import (
    manufacturing_moldflow_spec,
    run_manufacturing_moldflow,
)


_FIXTURES = Path(__file__).parent / "fixtures"


def _run(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_manufacturing._compat import ProjectCtx
    return ProjectCtx()


def _call(payload: dict) -> dict:
    raw = _run(run_manufacturing_moldflow(payload, _ctx()))
    return json.loads(raw)


def _disc_params(**overrides) -> dict:
    with open(_FIXTURES / "disc.json") as f:
        d = json.load(f)
    params = {
        "nodes": d["nodes"],
        "triangles": d["triangles"],
        "thickness": d["thickness"],
        "gate_node": d["gate_node"],
    }
    params.update(overrides)
    return params


def _lshape_params(**overrides) -> dict:
    with open(_FIXTURES / "lshape.json") as f:
        d = json.load(f)
    params = {
        "nodes": d["nodes"],
        "triangles": d["triangles"],
        "thickness": d.get("thickness", 0.002),
        "gate_node": d.get("gate_node", 0),
    }
    params.update(overrides)
    return params


# ---------------------------------------------------------------------------
# Spec smoke tests
# ---------------------------------------------------------------------------

class TestSpec:
    def test_spec_name(self):
        assert manufacturing_moldflow_spec.name == "manufacturing_moldflow"

    def test_spec_required_fields(self):
        required = manufacturing_moldflow_spec.input_schema.get("required", [])
        assert "nodes" in required
        assert "triangles" in required


# ---------------------------------------------------------------------------
# Disc fixture tests
# ---------------------------------------------------------------------------

class TestDiscFixture:
    def test_disc_fills_completely(self):
        """Simply-connected disc fills to 100 % — no short shot."""
        result = _call(_disc_params())
        assert result.get("ok") is True
        assert result["fill_fraction"] == pytest.approx(1.0, abs=0.01)
        assert result["short_shot"] is False

    def test_disc_node_and_triangle_counts(self):
        result = _call(_disc_params())
        assert result.get("ok") is True
        assert result["n_nodes"] == 129
        assert result["n_triangles"] == 240

    def test_disc_fill_time_list_length(self):
        result = _call(_disc_params())
        assert len(result["fill_time_s"]) == 129

    def test_disc_fill_time_gate_is_zero(self):
        result = _call(_disc_params())
        assert result.get("ok") is True
        # Gate node (index 0) fills first → fill time ≈ 0
        assert result["fill_time_s"][0] == pytest.approx(0.0, abs=0.1)

    def test_disc_material_abs(self):
        result = _call(_disc_params(material_name="ABS"))
        assert result.get("ok") is True
        assert result["short_shot"] is False

    def test_disc_material_pp(self):
        result = _call(_disc_params(material_name="PP"))
        assert result.get("ok") is True

    def test_disc_material_pa6(self):
        result = _call(_disc_params(material_name="PA6"))
        assert result.get("ok") is True


# ---------------------------------------------------------------------------
# L-shape fixture tests
# ---------------------------------------------------------------------------

class TestLShapeFixture:
    def test_lshape_fills_without_short_shot(self):
        result = _call(_lshape_params())
        assert result.get("ok") is True
        # L-shape should fill; weld lines may appear near the inner corner
        assert result["fill_fraction"] > 0.9

    def test_lshape_weld_lines_detected(self):
        result = _call(_lshape_params())
        assert result.get("ok") is True
        # L-shape is known to produce weld lines
        assert result["weld_line_count"] >= 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_missing_nodes(self):
        result = _call({"triangles": [[0, 1, 2]]})
        assert "error" in result

    def test_missing_triangles(self):
        result = _call({"nodes": [[0, 0], [1, 0], [0.5, 1]]})
        assert "error" in result

    def test_thickness_length_mismatch(self):
        result = _call({
            "nodes": [[0, 0], [1, 0], [0.5, 1]],
            "triangles": [[0, 1, 2]],
            "thickness": [0.002, 0.003],  # wrong length (need 1, got 2)
        })
        assert "error" in result

    def test_zero_injection_pressure(self):
        """Zero pressure → short shot (no flow)."""
        result = _call({
            **_disc_params(),
            "injection_pressure_bar": 0.0,
        })
        assert result.get("ok") is True
        assert result["short_shot"] is True
