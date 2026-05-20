"""
Tests for kerf_cloud.plm.where_used — assembly-graph inverse lookup.

All tests are hermetic (no DB, no filesystem).
"""
from __future__ import annotations

import json
import pytest

from kerf_cloud.plm.where_used import where_used


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _part(fid, name):
    return {"id": fid, "name": name, "kind": "part", "content": "", "parent_id": None}


def _asm(fid, name, components, parent_id=None):
    content = json.dumps({"components": components})
    return {"id": fid, "name": name, "kind": "assembly", "content": content, "parent_id": parent_id}


def _comp(file_id, qty=1, effectivity=None):
    c = {"file_id": file_id, "quantity": qty}
    if effectivity is not None:
        c["effectivity"] = effectivity
    return c


# ---------------------------------------------------------------------------
# Basic where-used tests
# ---------------------------------------------------------------------------

class TestWhereUsedBasic:
    def test_part_not_used_returns_empty(self):
        p1 = _part("p1", "Bolt")
        result = where_used("p1", [p1])
        assert result["part_id"] == "p1"
        assert result["usages"] == []

    def test_direct_parent(self):
        p1 = _part("p1", "Shaft")
        asm = _asm("a1", "Motor", [_comp("p1", qty=1)])
        result = where_used("p1", [p1, asm])
        assert len(result["usages"]) == 1
        assert result["usages"][0]["assembly_id"] == "a1"
        assert result["usages"][0]["assembly_name"] == "Motor"
        assert result["usages"][0]["quantity"] == 1

    def test_multiple_direct_parents(self):
        p1 = _part("p1", "Bolt M5")
        asm1 = _asm("a1", "Frame", [_comp("p1", qty=4)])
        asm2 = _asm("a2", "Door", [_comp("p1", qty=2)])
        result = where_used("p1", [p1, asm1, asm2])
        asm_ids = {u["assembly_id"] for u in result["usages"]}
        assert "a1" in asm_ids
        assert "a2" in asm_ids

    def test_indirect_parent(self):
        p1 = _part("p1", "Bearing")
        sub = _asm("sub1", "Spindle", [_comp("p1")])
        top = _asm("top1", "Machine", [_comp("sub1")])
        result = where_used("p1", [p1, sub, top])
        asm_ids = {u["assembly_id"] for u in result["usages"]}
        assert "sub1" in asm_ids
        assert "top1" in asm_ids

    def test_result_sorted_by_name(self):
        p1 = _part("p1", "Part")
        asm1 = _asm("a1", "Z-Assembly", [_comp("p1")])
        asm2 = _asm("a2", "A-Assembly", [_comp("p1")])
        result = where_used("p1", [p1, asm1, asm2])
        names = [u["assembly_name"] for u in result["usages"]]
        assert names == sorted(names)

    def test_quantity_preserved(self):
        p1 = _part("p1", "Screw")
        asm = _asm("a1", "Panel", [_comp("p1", qty=8)])
        result = where_used("p1", [p1, asm])
        assert result["usages"][0]["quantity"] == 8

    def test_unknown_part_returns_empty(self):
        p1 = _part("p1", "Known")
        result = where_used("unknown-id", [p1])
        assert result["usages"] == []


# ---------------------------------------------------------------------------
# Effectivity in where-used
# ---------------------------------------------------------------------------

class TestWhereUsedEffectivity:
    def test_effectivity_passed_through(self):
        p1 = _part("p1", "Widget")
        eff = {"valid_from": "2024-01-01", "valid_until": None}
        asm = _asm("a1", "Product", [_comp("p1", effectivity=eff)])
        result = where_used("p1", [p1, asm])
        usage = result["usages"][0]
        assert usage["effectivity"]["valid_from"] == "2024-01-01"
        assert usage["effectivity"]["valid_until"] is None

    def test_no_effectivity_defaults_to_none(self):
        p1 = _part("p1", "Part")
        asm = _asm("a1", "Asm", [_comp("p1")])
        result = where_used("p1", [p1, asm])
        eff = result["usages"][0]["effectivity"]
        assert eff["valid_from"] is None
        assert eff["valid_until"] is None


# ---------------------------------------------------------------------------
# Path breadcrumb
# ---------------------------------------------------------------------------

class TestWhereUsedPath:
    def test_direct_usage_has_path(self):
        p1 = _part("p1", "Part")
        asm = _asm("a1", "TopAsm", [_comp("p1")])
        result = where_used("p1", [p1, asm])
        assert result["usages"][0]["path"] == ["TopAsm"]

    def test_nested_path(self):
        p1 = _part("p1", "Part")
        sub = _asm("sub1", "SubAsm", [_comp("p1")])
        top = _asm("top1", "TopAsm", [_comp("sub1")])
        result = where_used("p1", [p1, sub, top])
        by_id = {u["assembly_id"]: u for u in result["usages"]}
        assert "sub1" in by_id
        # sub path includes TopAsm as ancestor
        sub_path = by_id["sub1"]["path"]
        assert "TopAsm" in sub_path or "SubAsm" in sub_path


# ---------------------------------------------------------------------------
# LLM tool wrapper
# ---------------------------------------------------------------------------

class TestPlmWhereUsedLlmTool:
    def test_basic_dispatch(self):
        from kerf_cloud.plm.llm_tools import plm_where_used
        p = _part("p1", "Gear")
        asm = _asm("a1", "Gearbox", [_comp("p1")])
        files_json = json.dumps([p, asm])
        result = plm_where_used("p1", files_json)
        assert len(result["usages"]) == 1

    def test_bad_json(self):
        from kerf_cloud.plm.llm_tools import plm_where_used
        result = plm_where_used("p1", "not json")
        assert result["ok"] is False

    def test_missing_part_id(self):
        from kerf_cloud.plm.llm_tools import plm_where_used
        result = plm_where_used("", json.dumps([]))
        assert result["ok"] is False
        assert result["code"] == "BAD_ARGS"
