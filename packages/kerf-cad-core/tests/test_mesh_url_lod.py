"""P0-5 — triangle_count_from_mesh_url + LOD planner mesh_url wiring.

Tests
-----
1.  Empty string → default_estimate returned.
2.  None → default_estimate returned.
3.  Non-mesh URL (no .glb/.gltf) → default_estimate.
4.  foo.glb with byte_count_hint=36000 → 1000 triangles (36000 // 36).
5.  foo.gltf with byte_count_hint=720000 → 20000 triangles (720000 // 36).
6.  Zero byte_count_hint → default_estimate.
7.  Local file path: create a tmp file of known size, assert estimate.
8.  Custom default_estimate is respected when URL is empty.
9.  lod_plan with mesh_url produces different tier than synthetic estimate.
10. lod_plan without mesh_url uses synthetic estimate.
11. LLM tool run_assembly_lod_plan passes mesh_url + mesh_byte_count through.
12. byte_count_hint=1 → max(1, 1//36) = 1 triangle returned.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from kerf_cad_core.assembly.model import Assembly, Component
from kerf_cad_core.assembly.perf import (
    build_assembly,
    lod_plan,
    ViewportBudget,
    triangle_count_from_mesh_url,
    run_assembly_lod_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tool_call(tool_fn, args_dict: dict) -> dict:
    class FakeCtx:
        pass
    ctx = FakeCtx()
    raw = _run(tool_fn(ctx, json.dumps(args_dict).encode()))
    parsed = json.loads(raw)
    if "error" in parsed and "code" in parsed:
        return {"ok": False, "payload": {}, "code": parsed.get("code"), "raw": parsed}
    return {"ok": True, "payload": parsed, "code": None, "raw": parsed}


# ---------------------------------------------------------------------------
# triangle_count_from_mesh_url unit tests
# ---------------------------------------------------------------------------

def test_empty_string_returns_default():
    """Empty string → default_estimate."""
    assert triangle_count_from_mesh_url("") == 1000


def test_none_returns_default():
    """None → default_estimate."""
    assert triangle_count_from_mesh_url(None) == 1000  # type: ignore[arg-type]


def test_non_mesh_url_returns_default():
    """Non-mesh URL with unrecognised extension → default_estimate."""
    assert triangle_count_from_mesh_url("https://example.com/model.obj") == 1000


def test_glb_with_byte_hint_1000_triangles():
    """foo.glb byte_count_hint=36000 → 36000 // 36 = 1000 triangles."""
    assert triangle_count_from_mesh_url("foo.glb", byte_count_hint=36_000) == 1000


def test_gltf_with_byte_hint_20000_triangles():
    """foo.gltf byte_count_hint=720000 → 720000 // 36 = 20000 triangles."""
    assert triangle_count_from_mesh_url("foo.gltf", byte_count_hint=720_000) == 20_000


def test_zero_byte_count_returns_default():
    """byte_count_hint=0 → default_estimate (can't estimate from zero bytes)."""
    assert triangle_count_from_mesh_url("model.glb", byte_count_hint=0) == 1000


def test_local_file_path():
    """Local .glb file of known size → estimate from actual file size."""
    n_bytes = 36 * 500  # 500 triangles worth
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
        f.write(b"x" * n_bytes)
        path = f.name
    try:
        result = triangle_count_from_mesh_url(path)
        assert result == 500
    finally:
        os.unlink(path)


def test_custom_default_estimate():
    """custom default_estimate is used when mesh_url is empty."""
    assert triangle_count_from_mesh_url("", default_estimate=42) == 42


def test_minimum_one_triangle():
    """byte_count_hint=1 → max(1, 1//36) = 1 triangle (never zero)."""
    result = triangle_count_from_mesh_url("model.glb", byte_count_hint=1)
    assert result == 1


def test_case_insensitive_extension():
    """Extensions are matched case-insensitively (.GLB works)."""
    result = triangle_count_from_mesh_url("model.GLB", byte_count_hint=36_000)
    assert result == 1000


# ---------------------------------------------------------------------------
# LOD planner integration — mesh_url changes the first component's tri count
# ---------------------------------------------------------------------------

def test_lod_plan_with_mesh_url_differs_from_synthetic():
    """lod_plan with mesh_url produces a different tri total vs synthetic estimate.

    Build an assembly with one component whose synthetic tri count is small (nut-M6 = 320).
    Supply a mesh_url with byte_count_hint that implies many more triangles.
    The resulting total_full_triangles must differ.
    """
    asm = Assembly()
    asm.add_component(Component(part_ref="nut-M6", instance_id="inst-0"))

    budget = ViewportBudget(max_triangles=1_000_000, max_visible_parts=10)

    # Without mesh_url: synthetic estimate for nut-M6 is 320
    plan_synthetic = lod_plan(asm, budget)

    # With mesh_url: 36 * 5000 = 180000 bytes → 5000 triangles
    plan_mesh = lod_plan(asm, budget, mesh_url="model.glb", byte_count_hint=36 * 5000)

    assert plan_synthetic.total_full_triangles != plan_mesh.total_full_triangles
    # mesh-derived plan should have 5000 triangles
    assert plan_mesh.total_full_triangles == 5000


def test_lod_plan_without_mesh_url_uses_synthetic():
    """Without mesh_url, lod_plan falls back to synthetic _tri_count_for."""
    asm = Assembly()
    asm.add_component(Component(part_ref="nut-M6", instance_id="inst-0"))

    budget = ViewportBudget(max_triangles=1_000_000, max_visible_parts=10)
    plan = lod_plan(asm, budget)

    # nut-M6 synthetic count is 320
    assert plan.total_full_triangles == 320


def test_lod_plan_mesh_url_tight_budget_changes_tier():
    """With mesh_url providing high tri count, a tight budget culls the component."""
    asm = Assembly()
    asm.add_component(Component(part_ref="nut-M6", instance_id="inst-0"))

    # Budget allows 320 triangles (the synthetic nut-M6 count) but mesh has far more
    budget = ViewportBudget(max_triangles=320, max_visible_parts=10)

    # Without mesh_url: nut-M6 (320 tris) fits in budget → "full"
    plan_synthetic = lod_plan(asm, budget)
    assert any(e.detail == "full" for e in plan_synthetic.entries)

    # With mesh_url: 36 * 10000 = 360000 bytes → 10000 tris, exceeds 320-tri budget
    plan_mesh = lod_plan(asm, budget, mesh_url="part.glb", byte_count_hint=36 * 10_000)
    # Component cannot fit "full" — must be bbox_proxy or culled
    for e in plan_mesh.entries:
        assert e.detail in ("bbox_proxy", "culled"), (
            f"Expected bbox_proxy/culled with tight budget+mesh_url, got {e.detail}"
        )


# ---------------------------------------------------------------------------
# LLM tool integration
# ---------------------------------------------------------------------------

def test_tool_lod_plan_with_mesh_url():
    """run_assembly_lod_plan passes mesh_url + mesh_byte_count through correctly."""
    asm = build_assembly(1, depth=0)
    resp = _tool_call(run_assembly_lod_plan, {
        "assembly": asm.to_dict(),
        "max_triangles": 1_000_000,
        "max_visible_parts": 10,
        "mesh_url": "scene.glb",
        "mesh_byte_count": 36 * 5000,  # 5000 triangles
    })
    assert resp["ok"] is True
    p = resp["payload"]
    assert "entries" in p
    assert p["total_full_triangles"] == 5000
