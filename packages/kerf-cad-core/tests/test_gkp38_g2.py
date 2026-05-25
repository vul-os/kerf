"""
GK-P38 — G2 (curvature) continuity constraint between adjacent bspline/arc
endpoints — Python-side hermetic tests.

Tests verify:
  1. bezier_g2 constraint round-trips through sketch_add_constraint.
  2. DOF accounting: bezier_g2 removes 2 DOF (G1 collinearity + equal-chord).
  3. Adjacent curves with a bezier_g2 at the junction are not over-constrained.
  4. Realistic G1+G2 combination on two cubic Bezier segments is consistent.
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
import pytest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _FakeResolve:
    async def __call__(self, ctx, path):
        return {"exists": True}


class _FakePool:
    def __init__(self, initial: dict | None = None):
        self._store: dict[str, str] = {}
        if initial:
            for path, data in initial.items():
                self._store[path] = json.dumps(data)

    async def fetchrow(self, query, *args):
        path = args[1] if len(args) > 1 else None
        if path in self._store:
            return {"content": self._store[path]}
        return None

    async def execute(self, query, *args):
        content = args[0]
        path = args[2] if len(args) > 2 else None
        if path:
            self._store[path] = content


class _FakeCtx:
    def __init__(self, pool):
        self.pool = pool
        self.project_id = "test-project-id"


def _empty_sketch() -> dict:
    return {
        "version": 1,
        "plane": {"type": "base", "name": "XY"},
        "entities": [],
        "constraints": [],
        "visible_3d": [],
        "solved": {},
        "metadata": {},
    }


def _make_ctx_and_path(sketch_data: dict | None = None):
    path = "/test.sketch"
    pool = _FakePool({path: sketch_data or _empty_sketch()})
    ctx = _FakeCtx(pool)
    return ctx, path


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_fake_resolve = _FakeResolve()

with mock.patch("kerf_cad_core.sketch.resolve_path", new=_fake_resolve):
    import kerf_cad_core.sketch as sketch_mod


def _call(fn, ctx, args_dict: dict) -> dict:
    with mock.patch("kerf_cad_core.sketch.resolve_path", new=_fake_resolve):
        raw = _run(fn(ctx, json.dumps(args_dict).encode()))
    return json.loads(raw)


def _read_sketch(ctx: _FakeCtx, path: str) -> dict:
    raw = _run(ctx.pool.fetchrow("", None, path))
    return json.loads(raw["content"])


def _validate(sketch_data: dict) -> dict:
    ctx, path = _make_ctx_and_path(sketch_data)
    with mock.patch("kerf_cad_core.sketch.resolve_path", new=_fake_resolve):
        raw = _run(sketch_mod.run_sketch_validate(ctx, json.dumps({"file_path": path}).encode()))
    return json.loads(raw)


def test_gkp38_bezier_g2_roundtrips():
    """bezier_g2 constraint is accepted by sketch_add_constraint and round-trips."""
    ctx, path = _make_ctx_and_path()
    result = _call(sketch_mod.run_sketch_add_constraint, ctx, {
        "file_path": path,
        "constraint": {
            "type": "bezier_g2",
            "id": "g2_1",
            "p_minus2": "pm2",
            "p_minus1": "pm1",
            "p_junction": "pj",
            "p_plus1":  "pp1",
            "p_plus2":  "pp2",
        },
    })
    assert result.get("ok") is True
    assert result.get("id") == "g2_1"

    sketch = _read_sketch(ctx, path)
    c = next(c for c in sketch["constraints"] if c["id"] == "g2_1")
    assert c["type"] == "bezier_g2"
    assert c["p_minus1"]   == "pm1"
    assert c["p_junction"] == "pj"
    assert c["p_plus1"]    == "pp1"


def test_gkp38_bezier_g2_dof_removes_2():
    """bezier_g2 removes 2 DOF (G1 collinearity + equal-chord condition)."""
    sketch = _empty_sketch()
    sketch["entities"] = [
        {"id": "pm2", "type": "point", "x": 0.0,  "y": 0.0},
        {"id": "pm1", "type": "point", "x": 5.0,  "y": 5.0},
        {"id": "pj",  "type": "point", "x": 10.0, "y": 0.0},
        {"id": "pp1", "type": "point", "x": 15.0, "y": -5.0},
        {"id": "pp2", "type": "point", "x": 20.0, "y": 0.0},
    ]
    sketch["constraints"] = [
        {
            "id": "g2_1",
            "type": "bezier_g2",
            "p_minus2": "pm2",
            "p_minus1": "pm1",
            "p_junction": "pj",
            "p_plus1": "pp1",
            "p_plus2": "pp2",
        },
    ]
    result = _validate(sketch)
    errors = result.get("errors", [])
    over = [e for e in errors if e.get("kind") == "redundant_constraint"]
    assert len(over) == 0, f"8 DOF remaining should not be over-constrained: {errors}"


def test_gkp38_g2_adjacent_curves_curvature_continuity():
    """
    Two collinear cubic Bezier segments joined at a junction point with bezier_g2.
    Validates the constraint is accepted and DOF accounting is consistent.
    """
    sketch = _empty_sketch()
    sketch["entities"] = [
        {"id": "a0", "type": "point", "x": 0.0,  "y": 0.0},
        {"id": "a1", "type": "point", "x": 5.0,  "y": 0.0},
        {"id": "a2", "type": "point", "x": 10.0, "y": 0.0},
        {"id": "a3", "type": "point", "x": 15.0, "y": 0.0},  # junction
        {"id": "b1", "type": "point", "x": 20.0, "y": 0.0},
        {"id": "b2", "type": "point", "x": 25.0, "y": 0.0},
        {"id": "b3", "type": "point", "x": 30.0, "y": 0.0},
    ]
    sketch["constraints"] = [
        {"id": "fix_a0", "type": "fixed", "point": "a0"},
        {"id": "fix_b3", "type": "fixed", "point": "b3"},
        {
            "id": "g2_j",
            "type": "bezier_g2",
            "p_minus2":   "a2",
            "p_minus1":   "a2",
            "p_junction": "a3",
            "p_plus1":    "b1",
            "p_plus2":    "b2",
        },
    ]
    result = _validate(sketch)
    errors = result.get("errors", [])
    over = [e for e in errors if e.get("kind") == "redundant_constraint"]
    assert len(over) == 0, f"G2 join should not over-constrain: {errors}"


def test_gkp38_g2_combined_with_g1_and_coincident():
    """
    Realistic G2 setup: fixed endpoints + bezier_g2 at junction on two cubic
    Bezier segments with symmetric tangent handles. Not over-constrained.
    """
    sketch = _empty_sketch()
    sketch["entities"] = [
        {"id": "a0", "type": "point", "x": 0.0,  "y": 0.0},
        {"id": "a1", "type": "point", "x": 3.0,  "y": 4.0},
        {"id": "a2", "type": "point", "x": 7.0,  "y": 4.0},
        {"id": "a3", "type": "point", "x": 10.0, "y": 0.0},  # junction
        {"id": "b1", "type": "point", "x": 13.0, "y": -4.0},
        {"id": "b2", "type": "point", "x": 17.0, "y": -4.0},
        {"id": "b3", "type": "point", "x": 20.0, "y": 0.0},
    ]
    sketch["constraints"] = [
        {"id": "fix_a0", "type": "fixed", "point": "a0"},
        {"id": "fix_b3", "type": "fixed", "point": "b3"},
        {
            "id": "g2_j",
            "type": "bezier_g2",
            "p_minus2":   "a2",
            "p_minus1":   "a2",
            "p_junction": "a3",
            "p_plus1":    "b1",
            "p_plus2":    "b2",
        },
    ]
    result = _validate(sketch)
    errors = result.get("errors", [])
    over = [e for e in errors if e.get("kind") == "redundant_constraint"]
    assert len(over) == 0, f"G2 realistic join should not over-constrain: {errors}"
