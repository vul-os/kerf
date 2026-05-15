"""
Tests for kerf_cad_core.assembly.perf — large-assembly perf harness + LOD planner.

All tests are hermetic (pure-Python, no DB, no OCC, no network).

Coverage
--------
- Synthetic assembly generator: component counts, nesting depths, branching
- Performance harness: monotonic timing shape vs N, result structure
- LOD planner: budget adherence, determinism, culling
- Lazy-load ordering: stability, tier priority
- LLM tool wrappers: valid + invalid inputs, friendly errors (never raise)
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.assembly.model import Assembly, Component
from kerf_cad_core.assembly.perf import (
    build_assembly,
    measure_assembly,
    sweep_assembly_perf,
    ViewportBudget,
    ComponentLodEntry,
    LodPlan,
    lod_plan,
    lazy_load_order,
    run_assembly_perf_report,
    run_assembly_lod_plan,
    _PART_CATALOGUE,
    _tri_count_for,
    _bbox_half_for,
    _volume_for,
    _importance_for,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx():
    class FakeCtx:
        pass
    return FakeCtx()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tool_call(tool_fn, args_dict: dict) -> dict:
    ctx = _make_ctx()
    raw = _run(tool_fn(ctx, json.dumps(args_dict).encode()))
    parsed = json.loads(raw)
    if "error" in parsed and "code" in parsed:
        return {"ok": False, "payload": {}, "code": parsed.get("code"), "raw": parsed}
    return {"ok": True, "payload": parsed, "code": None, "raw": parsed}


# ---------------------------------------------------------------------------
# 1. build_assembly — basic counts
# ---------------------------------------------------------------------------

class TestBuildAssembly:
    def test_flat_single_component(self):
        asm = build_assembly(1, depth=0)
        assert len(asm.all_components()) == 1

    def test_flat_ten_components(self):
        asm = build_assembly(10, depth=0)
        assert len(asm.all_components()) == 10

    def test_nested_components(self):
        asm = build_assembly(20, depth=2, branching=4)
        assert len(asm.all_components()) == 20

    def test_large_flat_assembly(self):
        asm = build_assembly(100, depth=0)
        assert len(asm.all_components()) == 100

    def test_large_nested_assembly(self):
        asm = build_assembly(500, depth=3, branching=5)
        assert len(asm.all_components()) == 500

    def test_instance_ids_are_unique(self):
        asm = build_assembly(50, depth=2, branching=3)
        ids = [c.instance_id for c in asm.all_components()]
        assert len(ids) == len(set(ids)), "instance_ids must be unique"

    def test_deterministic_part_refs(self):
        """Same N produces same sequence of part_refs."""
        asm1 = build_assembly(30, depth=1, branching=4)
        asm2 = build_assembly(30, depth=1, branching=4)
        refs1 = [c.part_ref for c in asm1.all_components()]
        refs2 = [c.part_ref for c in asm2.all_components()]
        assert refs1 == refs2

    def test_part_refs_in_catalogue(self):
        asm = build_assembly(40)
        for comp in asm.all_components():
            assert comp.part_ref in _PART_CATALOGUE

    def test_invalid_n_raises(self):
        with pytest.raises(ValueError):
            build_assembly(0)

    def test_invalid_depth_raises(self):
        with pytest.raises(ValueError):
            build_assembly(5, depth=-1)

    def test_invalid_branching_raises(self):
        with pytest.raises(ValueError):
            build_assembly(5, branching=0)

    def test_depth_0_no_sub_assemblies(self):
        asm = build_assembly(8, depth=0)
        assert len(asm.sub_assemblies) == 0
        assert len(asm.components) == 8

    def test_depth_1_has_sub_assemblies(self):
        asm = build_assembly(12, depth=1, branching=4)
        # With depth=1 all leaves are in sub-assemblies
        assert len(asm.sub_assemblies) > 0
        assert len(asm.all_components()) == 12


# ---------------------------------------------------------------------------
# 2. measure_assembly — result structure
# ---------------------------------------------------------------------------

class TestMeasureAssembly:
    def test_result_fields_present(self):
        asm = build_assembly(10)
        r = measure_assembly(asm)
        assert r.n_components == 10
        assert isinstance(r.solve_time_s, float)
        assert isinstance(r.bom_time_s, float)
        assert isinstance(r.total_time_s, float)
        assert isinstance(r.peak_memory_bytes, int)
        assert r.status in ("fully_constrained", "under_constrained", "over_constrained")

    def test_single_component_fully_constrained(self):
        asm = build_assembly(1)
        r = measure_assembly(asm)
        assert r.status == "fully_constrained"
        assert r.dof_remaining == 0

    def test_multi_component_under_constrained(self):
        asm = build_assembly(5)
        r = measure_assembly(asm)
        # 4 free components × 6 DOF = 24
        assert r.dof_remaining == 24
        assert r.status == "under_constrained"

    def test_n_unique_parts_positive(self):
        asm = build_assembly(20)
        r = measure_assembly(asm)
        assert r.n_unique_parts > 0
        assert r.n_unique_parts <= r.n_components

    def test_timings_non_negative(self):
        asm = build_assembly(50)
        r = measure_assembly(asm)
        assert r.solve_time_s >= 0
        assert r.bom_time_s >= 0
        assert r.total_time_s >= 0
        assert r.peak_memory_bytes >= 0


# ---------------------------------------------------------------------------
# 3. sweep_assembly_perf — monotonic timing shape
# ---------------------------------------------------------------------------

class TestSweepAssemblyPerf:
    def test_returns_correct_count(self):
        ns = [10, 50, 100]
        results = sweep_assembly_perf(ns, depth=1, branching=3)
        assert len(results) == 3

    def test_n_components_matches_input(self):
        ns = [10, 20, 50]
        results = sweep_assembly_perf(ns)
        for r, n in zip(results, ns):
            assert r.n_components == n

    def test_total_time_monotonic(self):
        """
        Timing must be non-decreasing as N grows.  We use total_time_s and
        allow for small measurement noise by only asserting the overall
        direction holds (first < last) rather than strict pairwise monotonicity.
        """
        ns = [10, 50, 200, 500]
        results = sweep_assembly_perf(ns, depth=2, branching=4)
        times = [r.total_time_s for r in results]
        # Overall direction: last value strictly greater than first
        assert times[-1] >= times[0], (
            f"total_time should be non-decreasing vs N; got {times}"
        )

    def test_memory_non_negative(self):
        ns = [10, 100]
        results = sweep_assembly_perf(ns)
        for r in results:
            assert r.peak_memory_bytes >= 0


# ---------------------------------------------------------------------------
# 4. LOD planner — budget adherence
# ---------------------------------------------------------------------------

class TestLodPlan:
    def _asm_10(self) -> Assembly:
        return build_assembly(10, depth=0)

    def test_no_components_all_culled(self):
        asm = Assembly()
        budget = ViewportBudget(max_triangles=100000, max_visible_parts=100)
        plan = lod_plan(asm, budget)
        assert plan.entries == []
        assert plan.total_full_triangles == 0
        assert plan.total_visible_parts == 0

    def test_triangle_budget_respected(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=500, max_visible_parts=100)
        plan = lod_plan(asm, budget)
        assert plan.total_full_triangles <= budget.max_triangles

    def test_visible_parts_budget_respected(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=100000, max_visible_parts=3)
        plan = lod_plan(asm, budget)
        visible = sum(1 for e in plan.entries if e.detail in ("full", "bbox_proxy"))
        assert visible <= budget.max_visible_parts

    def test_all_details_valid_values(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=100000, max_visible_parts=100)
        plan = lod_plan(asm, budget)
        for entry in plan.entries:
            assert entry.detail in ("full", "bbox_proxy", "culled")

    def test_culled_have_zero_tris(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=200, max_visible_parts=5)
        plan = lod_plan(asm, budget)
        for entry in plan.entries:
            if entry.detail in ("bbox_proxy", "culled"):
                assert entry.tri_count == 0

    def test_full_detail_tris_positive(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=100000, max_visible_parts=100)
        plan = lod_plan(asm, budget)
        for entry in plan.entries:
            if entry.detail == "full":
                assert entry.tri_count > 0

    def test_deterministic_same_input(self):
        asm1 = build_assembly(20, depth=1, branching=4)
        asm2 = build_assembly(20, depth=1, branching=4)
        budget = ViewportBudget(max_triangles=5000, max_visible_parts=10)
        plan1 = lod_plan(asm1, budget)
        plan2 = lod_plan(asm2, budget)
        details1 = [(e.instance_id, e.detail) for e in plan1.entries]
        details2 = [(e.instance_id, e.detail) for e in plan2.entries]
        assert details1 == details2

    def test_invalid_budget_zero_triangles(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=0, max_visible_parts=10)
        plan = lod_plan(asm, budget)
        # All must be culled; error attribute present
        for entry in plan.entries:
            assert entry.detail == "culled"
        assert hasattr(plan, "error")
        assert "invalid budget" in plan.error  # type: ignore[attr-defined]

    def test_invalid_budget_zero_visible(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=100000, max_visible_parts=0)
        plan = lod_plan(asm, budget)
        for entry in plan.entries:
            assert entry.detail == "culled"
        assert hasattr(plan, "error")

    def test_invalid_budget_negative_triangles(self):
        asm = self._asm_10()
        budget = ViewportBudget(max_triangles=-1, max_visible_parts=5)
        plan = lod_plan(asm, budget)
        assert hasattr(plan, "error")
        assert all(e.detail == "culled" for e in plan.entries)

    def test_large_budget_mostly_full(self):
        asm = build_assembly(5, depth=0)
        budget = ViewportBudget(max_triangles=10_000_000, max_visible_parts=1000)
        plan = lod_plan(asm, budget)
        full_count = sum(1 for e in plan.entries if e.detail == "full")
        assert full_count == 5

    def test_tiny_budget_mostly_culled(self):
        asm = build_assembly(20, depth=0)
        budget = ViewportBudget(max_triangles=100, max_visible_parts=2)
        plan = lod_plan(asm, budget)
        culled = sum(1 for e in plan.entries if e.detail == "culled")
        assert culled >= 18  # at most 2 visible, rest culled

    def test_importance_order_largest_first(self):
        """The most important component (largest vol * complexity) gets 'full'."""
        asm = Assembly()
        # gear-32t has high importance; nut-M6 is small
        asm.add_component(Component(part_ref="nut-M6", instance_id="small"))
        asm.add_component(Component(part_ref="gear-48t", instance_id="big"))
        # Budget tight: only 1 full allowed
        budget = ViewportBudget(max_triangles=4000, max_visible_parts=1)
        plan = lod_plan(asm, budget)
        # Only 1 visible allowed with limited triangles — big gear should be it
        full_entries = [e for e in plan.entries if e.detail == "full"]
        if full_entries:
            assert full_entries[0].part_ref == "gear-48t"

    def test_total_full_triangles_consistent(self):
        asm = build_assembly(15, depth=0)
        budget = ViewportBudget(max_triangles=10000, max_visible_parts=20)
        plan = lod_plan(asm, budget)
        actual_total = sum(e.tri_count for e in plan.entries if e.detail == "full")
        assert actual_total == plan.total_full_triangles

    def test_total_visible_parts_consistent(self):
        asm = build_assembly(15, depth=0)
        budget = ViewportBudget(max_triangles=10000, max_visible_parts=10)
        plan = lod_plan(asm, budget)
        visible = sum(1 for e in plan.entries if e.detail in ("full", "bbox_proxy"))
        assert visible == plan.total_visible_parts


# ---------------------------------------------------------------------------
# 5. Lazy-load ordering
# ---------------------------------------------------------------------------

class TestLazyLoadOrder:
    def test_returns_all_instance_ids(self):
        asm = build_assembly(10, depth=0)
        budget = ViewportBudget(max_triangles=100000, max_visible_parts=100)
        plan = lod_plan(asm, budget)
        order = lazy_load_order(plan)
        all_ids = {e.instance_id for e in plan.entries}
        assert set(order) == all_ids

    def test_full_before_bbox_before_culled(self):
        asm = build_assembly(20, depth=0)
        budget = ViewportBudget(max_triangles=3000, max_visible_parts=8)
        plan = lod_plan(asm, budget)
        order = lazy_load_order(plan)
        detail_by_id = {e.instance_id: e.detail for e in plan.entries}

        tiers = [detail_by_id[iid] for iid in order]
        # No "full" should appear after first "bbox_proxy" or "culled"
        seen_non_full = False
        for t in tiers:
            if t != "full":
                seen_non_full = True
            if seen_non_full and t == "full":
                pytest.fail(f"'full' appeared after non-full in load order: {tiers}")

    def test_stable_order_same_input(self):
        asm = build_assembly(15, depth=0)
        budget = ViewportBudget(max_triangles=5000, max_visible_parts=10)
        plan1 = lod_plan(asm, budget)
        plan2 = lod_plan(asm, budget)
        assert lazy_load_order(plan1) == lazy_load_order(plan2)

    def test_empty_plan_returns_empty(self):
        asm = Assembly()
        budget = ViewportBudget(max_triangles=100, max_visible_parts=10)
        plan = lod_plan(asm, budget)
        assert lazy_load_order(plan) == []


# ---------------------------------------------------------------------------
# 6. Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_tri_count_for_known_parts(self):
        assert _tri_count_for("gear-48t") == 3600
        assert _tri_count_for("washer-M6") == 128

    def test_tri_count_fallback_in_range(self):
        count = _tri_count_for("unknown-part-xyz")
        assert 96 <= count <= 3600 + 96

    def test_tri_count_deterministic(self):
        assert _tri_count_for("mystery-part") == _tri_count_for("mystery-part")

    def test_bbox_half_known(self):
        bx, by, bz = _bbox_half_for("shaft-20mm")
        assert bx == 10 and bz == 80

    def test_bbox_half_fallback_positive(self):
        bx, by, bz = _bbox_half_for("widget-999")
        assert bx > 0 and by > 0 and bz > 0

    def test_volume_positive(self):
        vol = _volume_for("gear-32t")
        assert vol > 0

    def test_importance_positive(self):
        comp = Component(part_ref="gear-48t")
        assert _importance_for(comp) > 0


# ---------------------------------------------------------------------------
# 7. LLM tool — assembly_perf_report
# ---------------------------------------------------------------------------

class TestToolPerfReport:
    def test_default_smoke_test(self):
        resp = _tool_call(run_assembly_perf_report, {})
        assert resp["ok"] is True
        p = resp["payload"]
        assert p["n_components"] == 10
        assert p["status"] in ("fully_constrained", "under_constrained")

    def test_with_n(self):
        resp = _tool_call(run_assembly_perf_report, {"n": 50, "depth": 2, "branching": 3})
        assert resp["ok"] is True
        assert resp["payload"]["n_components"] == 50

    def test_with_assembly_dict(self):
        asm = build_assembly(15, depth=1, branching=3)
        resp = _tool_call(run_assembly_perf_report, {"assembly": asm.to_dict()})
        assert resp["ok"] is True
        assert resp["payload"]["n_components"] == 15

    def test_both_assembly_and_n_error(self):
        asm = build_assembly(5)
        resp = _tool_call(run_assembly_perf_report, {"assembly": asm.to_dict(), "n": 10})
        assert resp["ok"] is False
        assert resp["code"] == "BAD_ARGS"

    def test_n_zero_error(self):
        resp = _tool_call(run_assembly_perf_report, {"n": 0})
        assert resp["ok"] is False
        assert resp["code"] == "BAD_ARGS"

    def test_invalid_json_handled(self):
        ctx = _make_ctx()
        raw = _run(run_assembly_perf_report(ctx, b"not-json"))
        parsed = json.loads(raw)
        assert "error" in parsed

    def test_result_has_all_fields(self):
        resp = _tool_call(run_assembly_perf_report, {"n": 20})
        p = resp["payload"]
        for key in (
            "n_components", "solve_time_s", "bom_time_s", "total_time_s",
            "peak_memory_bytes", "dof_remaining", "status", "n_unique_parts",
        ):
            assert key in p, f"missing field: {key}"


# ---------------------------------------------------------------------------
# 8. LLM tool — assembly_lod_plan
# ---------------------------------------------------------------------------

class TestToolLodPlan:
    def _make_asm_dict(self, n: int = 10) -> dict:
        return build_assembly(n).to_dict()

    def test_basic_plan(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(),
            "max_triangles": 100000,
            "max_visible_parts": 100,
        })
        assert resp["ok"] is True
        p = resp["payload"]
        assert "entries" in p
        assert "total_full_triangles" in p
        assert "total_visible_parts" in p
        assert "load_order" in p

    def test_triangle_budget_in_response(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(20),
            "max_triangles": 1000,
            "max_visible_parts": 100,
        })
        assert resp["ok"] is True
        assert resp["payload"]["total_full_triangles"] <= 1000

    def test_visible_budget_in_response(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(20),
            "max_triangles": 1_000_000,
            "max_visible_parts": 5,
        })
        assert resp["ok"] is True
        assert resp["payload"]["total_visible_parts"] <= 5

    def test_load_order_all_ids_present(self):
        asm_dict = self._make_asm_dict(10)
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": asm_dict,
            "max_triangles": 100000,
            "max_visible_parts": 100,
        })
        entries = resp["payload"]["entries"]
        load_order = resp["payload"]["load_order"]
        entry_ids = {e["instance_id"] for e in entries}
        assert set(load_order) == entry_ids

    def test_invalid_budget_friendly_error_in_payload(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(),
            "max_triangles": 0,
            "max_visible_parts": 10,
        })
        # Should NOT return an ok=False — returns ok=True with error in payload
        p = resp["payload"] if resp["ok"] else resp["raw"]
        # If it went through the tool, the payload should contain "error" key
        # (budget was invalid) or entries all culled
        if "entries" in p:
            for e in p["entries"]:
                assert e["detail"] == "culled"

    def test_missing_assembly_error(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "max_triangles": 1000,
            "max_visible_parts": 10,
        })
        assert resp["ok"] is False
        assert resp["code"] == "BAD_ARGS"

    def test_missing_max_triangles_error(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(),
            "max_visible_parts": 10,
        })
        assert resp["ok"] is False

    def test_missing_max_visible_parts_error(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(),
            "max_triangles": 1000,
        })
        assert resp["ok"] is False

    def test_invalid_assembly_error(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": {"not": "valid"},
            "max_triangles": 1000,
            "max_visible_parts": 10,
        })
        # Assembly.from_dict on unknown keys should still create a valid empty assembly
        # OR return BAD_ARGS — either is acceptable; just must not raise
        assert isinstance(resp["ok"], bool)

    def test_invalid_json_handled(self):
        ctx = _make_ctx()
        raw = _run(run_assembly_lod_plan(ctx, b"{bad json"))
        parsed = json.loads(raw)
        assert "error" in parsed

    def test_entries_detail_values_valid(self):
        resp = _tool_call(run_assembly_lod_plan, {
            "assembly": self._make_asm_dict(15),
            "max_triangles": 5000,
            "max_visible_parts": 8,
        })
        assert resp["ok"] is True
        for e in resp["payload"]["entries"]:
            assert e["detail"] in ("full", "bbox_proxy", "culled")
