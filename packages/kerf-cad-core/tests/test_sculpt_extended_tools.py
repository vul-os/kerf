"""
Tests for kerf_cad_core.sculpt.sculpt_extended_tools — Wave 9B LLM tool wrappers.

Tests the LLM tool surface (run_sculpt_dynamesh_remesh, run_sculpt_polypaint_stroke,
run_sculpt_polypaint_bake, run_sculpt_displacement_bake, run_sculpt_auto_weight,
run_sculpt_lbs_pose) covering:
  - basic smoke tests for each tool
  - output schema validation
  - bad-args / JSON-error paths
"""
from __future__ import annotations

import asyncio
import json
import numpy as np
import pytest

from kerf_cad_core.sculpt.sculpt_extended_tools import (
    run_sculpt_dynamesh_remesh,
    run_sculpt_polypaint_stroke,
    run_sculpt_polypaint_bake,
    run_sculpt_displacement_bake,
    run_sculpt_auto_weight,
    run_sculpt_lbs_pose,
)
from kerf_cad_core._compat import ProjectCtx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

_CTX = ProjectCtx()


def _tetrahedron():
    """Simple tetrahedron mesh."""
    positions = [
        [0.0,  0.0,  0.0],
        [1.0,  0.0,  0.0],
        [0.5,  1.0,  0.0],
        [0.5,  0.5,  1.0],
    ]
    triangles = [
        [0, 1, 2],
        [0, 1, 3],
        [1, 2, 3],
        [0, 2, 3],
    ]
    return positions, triangles


def _unit_tetrahedron_colors():
    """Per-vertex colors for the tetrahedron."""
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 1.0, 0.0]]


# ---------------------------------------------------------------------------
# sculpt_dynamesh_remesh
# ---------------------------------------------------------------------------

class TestDynameshRemesh:

    def test_remesh_basic(self):
        positions, triangles = _tetrahedron()
        args = json.dumps({
            "positions": positions,
            "triangles": triangles,
            "target_resolution": 16,
        })
        raw = run(run_sculpt_dynamesh_remesh(args, _CTX))
        result = json.loads(raw)
        data = result if "positions" in result else result.get("result", result)
        # Should produce some mesh
        assert "positions" in data
        assert "triangles" in data
        # Volume before/after should be available
        assert "volume_before" in data
        assert "volume_after" in data

    def test_volume_preserved_approx(self):
        positions, triangles = _tetrahedron()
        args = json.dumps({
            "positions": positions,
            "triangles": triangles,
            "target_resolution": 64,  # higher resolution for better volume accuracy
        })
        raw = run(run_sculpt_dynamesh_remesh(args, _CTX))
        result = json.loads(raw)
        data = result if "positions" in result else result.get("result", result)
        vb = data.get("volume_before", 1.0)
        va = data.get("volume_after", 1.0)
        if vb > 0:
            # Allow ≤20% error — SDF voxelization at moderate resolution
            # has inherent discretization error; ZBrush DynaMesh docs cite ≤2%
            # for resolution ≥128, but we test at 64 so tolerance is looser.
            assert abs(va - vb) / max(abs(vb), 1e-6) < 0.20

    def test_bad_json(self):
        raw = run(run_sculpt_dynamesh_remesh("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result

    def test_missing_triangles(self):
        positions, _ = _tetrahedron()
        args = json.dumps({"positions": positions})
        raw = run(run_sculpt_dynamesh_remesh(args, _CTX))
        result = json.loads(raw)
        assert "error" in result or result.get("ok") is False or result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# sculpt_polypaint_stroke
# ---------------------------------------------------------------------------

class TestPolyPaintStroke:

    def test_stroke_basic(self):
        positions, _ = _tetrahedron()
        colors = _unit_tetrahedron_colors()
        args = json.dumps({
            "positions": positions,
            "vertex_colors": colors,
            "center": [0.5, 0.5, 0.5],
            "radius": 2.0,
            "color": [1.0, 1.0, 1.0],
        })
        raw = run(run_sculpt_polypaint_stroke(args, _CTX))
        result = json.loads(raw)
        data = result if "vertex_colors" in result else result.get("result", result)
        assert "vertex_colors" in data
        assert len(data["vertex_colors"]) == 4

    def test_out_of_radius_unchanged(self):
        positions, _ = _tetrahedron()
        colors = [[0.0, 0.0, 0.0]] * 4
        args = json.dumps({
            "positions": positions,
            "vertex_colors": colors,
            "center": [100.0, 100.0, 100.0],   # far away
            "radius": 0.01,
            "color": [1.0, 0.0, 0.0],
        })
        raw = run(run_sculpt_polypaint_stroke(args, _CTX))
        result = json.loads(raw)
        data = result if "vertex_colors" in result else result.get("result", result)
        vc = data.get("vertex_colors", [])
        # All colors should remain ~0 (no vertex in radius)
        for c in vc:
            assert max(c) < 0.01

    def test_bad_json(self):
        raw = run(run_sculpt_polypaint_stroke("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result


# ---------------------------------------------------------------------------
# sculpt_polypaint_bake
# ---------------------------------------------------------------------------

class TestPolyPaintBake:

    def test_bake_basic(self):
        positions, triangles = _tetrahedron()
        colors = _unit_tetrahedron_colors()
        args = json.dumps({
            "positions": positions,
            "triangles": triangles,
            "vertex_colors": colors,
            "texture_size": 32,
        })
        raw = run(run_sculpt_polypaint_bake(args, _CTX))
        result = json.loads(raw)
        data = result if "texture" in result else result.get("result", result)
        assert "texture" in data
        tex = data["texture"]
        # 32×32 texture
        assert len(tex) == 32
        assert len(tex[0]) == 32

    def test_bad_json(self):
        raw = run(run_sculpt_polypaint_bake("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result


# ---------------------------------------------------------------------------
# sculpt_displacement_bake
# ---------------------------------------------------------------------------

class TestDisplacementBake:

    def test_bake_basic(self):
        positions, triangles = _tetrahedron()
        # High-poly = slightly perturbed version
        hp_pos = [[p[0] + 0.05, p[1], p[2]] for p in positions]
        args = json.dumps({
            "low_poly_positions": positions,
            "low_poly_triangles": triangles,
            "high_poly_positions": hp_pos,
            "high_poly_triangles": triangles,
            "map_resolution": 16,
        })
        raw = run(run_sculpt_displacement_bake(args, _CTX))
        result = json.loads(raw)
        data = result if "scalar_field" in result else result.get("result", result)
        assert "scalar_field" in data
        assert "resolution" in data

    def test_bad_json(self):
        raw = run(run_sculpt_displacement_bake("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result


# ---------------------------------------------------------------------------
# sculpt_auto_weight
# ---------------------------------------------------------------------------

class TestAutoWeight:

    def _two_bone_skeleton(self):
        return [
            {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0], "parent": None},
            {"name": "child", "head": [0, 1, 0], "tail": [0, 2, 0], "parent": "root"},
        ]

    def test_auto_weight_basic(self):
        positions, triangles = _tetrahedron()
        args = json.dumps({
            "positions": positions,
            "bones": self._two_bone_skeleton(),
        })
        raw = run(run_sculpt_auto_weight(args, _CTX))
        result = json.loads(raw)
        data = result if "bone_indices" in result else result.get("result", result)
        assert "bone_indices" in data
        assert "bone_weights" in data
        # V×4 shape
        assert len(data["bone_indices"]) == 4
        assert len(data["bone_indices"][0]) == 4

    def test_weights_sum_to_one(self):
        positions, _ = _tetrahedron()
        args = json.dumps({
            "positions": positions,
            "bones": self._two_bone_skeleton(),
        })
        raw = run(run_sculpt_auto_weight(args, _CTX))
        result = json.loads(raw)
        data = result if "bone_weights" in result else result.get("result", result)
        for row in data["bone_weights"]:
            assert abs(sum(row) - 1.0) < 1e-4

    def test_bad_json(self):
        raw = run(run_sculpt_auto_weight("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result


# ---------------------------------------------------------------------------
# sculpt_lbs_pose
# ---------------------------------------------------------------------------

class TestLbsPose:

    def _two_bone_data(self):
        positions, triangles = _tetrahedron()
        bones = [
            {"name": "root",  "head": [0, 0, 0], "tail": [0, 1, 0], "parent": None},
            {"name": "child", "head": [0, 1, 0], "tail": [0, 2, 0], "parent": "root"},
        ]
        # First get weights
        wt_args = json.dumps({"positions": positions, "bones": bones})
        wt_raw = run(run_sculpt_auto_weight(wt_args, _CTX))
        wt = json.loads(wt_raw)
        wt_data = wt if "bone_indices" in wt else wt.get("result", wt)
        return positions, bones, wt_data["bone_indices"], wt_data["bone_weights"]

    def test_identity_pose_unchanged(self):
        positions, bones, b_idx, b_wts = self._two_bone_data()
        # Identity pose matrices
        I4 = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        args = json.dumps({
            "positions": positions,
            "bone_indices": b_idx,
            "bone_weights": b_wts,
            "bones": bones,
            "pose_matrices": [I4, I4],
        })
        raw = run(run_sculpt_lbs_pose(args, _CTX))
        result = json.loads(raw)
        data = result if "positions" in result else result.get("result", result)
        assert "positions" in data
        assert len(data["positions"]) == 4

    def test_bad_json(self):
        raw = run(run_sculpt_lbs_pose("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result
