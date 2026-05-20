"""
Tests for kerf_cloud.plm.bom150 — 150% BOM / effectivity.

All tests are hermetic (no DB, no filesystem).
"""
from __future__ import annotations

import json
import pytest

from kerf_cloud.plm.bom150 import bom_150_percent


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _part(fid, name):
    return {"id": fid, "name": name, "kind": "part", "content": "", "parent_id": None}


def _asm(fid, name, components, parent_id=None):
    content = json.dumps({"components": components})
    return {"id": fid, "name": name, "kind": "assembly", "content": content, "parent_id": parent_id}


def _comp(file_id, qty=1, effectivity=None, config_id=None):
    c = {"file_id": file_id, "quantity": qty}
    if effectivity is not None:
        c["effectivity"] = effectivity
    if config_id is not None:
        c["config_id"] = config_id
    return c


# ---------------------------------------------------------------------------
# Basic BOM tests
# ---------------------------------------------------------------------------

class TestBom150Basic:
    def test_empty_project(self):
        result = bom_150_percent([])
        assert result["effectivity_date"] is None
        assert result["parts"] == []

    def test_single_part_in_assembly(self):
        p1 = _part("p1", "Bolt M5")
        asm = _asm("a1", "Frame", [_comp("p1", qty=4)])
        result = bom_150_percent([p1, asm])
        assert result["effectivity_date"] is None
        parts = result["parts"]
        assert len(parts) == 1
        assert parts[0]["part_id"] == "p1"
        assert parts[0]["name"] == "Bolt M5"
        assert parts[0]["quantity"] == 4

    def test_multiple_parts(self):
        p1 = _part("p1", "Bolt M5")
        p2 = _part("p2", "Nut M5")
        asm = _asm("a1", "Frame", [_comp("p1", 4), _comp("p2", 4)])
        result = bom_150_percent([p1, p2, asm])
        names = {p["name"] for p in result["parts"]}
        assert names == {"Bolt M5", "Nut M5"}

    def test_nested_assemblies(self):
        p1 = _part("p1", "Shaft")
        p2 = _part("p2", "Bearing")
        sub = _asm("sub1", "Spindle", [_comp("p1", 1), _comp("p2", 2)])
        top = _asm("top1", "Machine", [_comp("sub1", 1)])
        result = bom_150_percent([p1, p2, sub, top])
        part_ids = {p["part_id"] for p in result["parts"]}
        assert "p1" in part_ids
        assert "p2" in part_ids

    def test_sorted_by_name(self):
        p1 = _part("p1", "Z-Part")
        p2 = _part("p2", "A-Part")
        asm = _asm("a1", "Asm", [_comp("p1"), _comp("p2")])
        result = bom_150_percent([p1, p2, asm])
        names = [p["name"] for p in result["parts"]]
        assert names == sorted(names)

    def test_cycle_detection(self):
        """Cyclic assembly references must not cause infinite recursion."""
        asm1 = _asm("a1", "A1", [_comp("a2")])
        asm2 = _asm("a2", "A2", [_comp("a1")])
        # Should not hang; result may be empty or partial but not error
        result = bom_150_percent([asm1, asm2])
        assert isinstance(result["parts"], list)


# ---------------------------------------------------------------------------
# Effectivity window tests
# ---------------------------------------------------------------------------

class TestBom150Effectivity:
    def _make_project(self):
        p_old = _part("p_old", "Old Widget")
        p_new = _part("p_new", "New Widget")
        asm = _asm("a1", "Product", [
            _comp("p_old", effectivity={"valid_from": None, "valid_until": "2023-12-31"}),
            _comp("p_new", effectivity={"valid_from": "2024-01-01", "valid_until": None}),
        ])
        return [p_old, p_new, asm]

    def test_no_date_returns_all_parts(self):
        files = self._make_project()
        result = bom_150_percent(files)
        assert len(result["parts"]) == 2

    def test_date_filters_effective_parts(self):
        files = self._make_project()
        result = bom_150_percent(files, effectivity_date="2023-06-01")
        by_id = {p["part_id"]: p for p in result["parts"]}
        assert by_id["p_old"]["effective"] is True
        assert by_id["p_new"]["effective"] is False

    def test_new_date_flips_effectivity(self):
        files = self._make_project()
        result = bom_150_percent(files, effectivity_date="2024-06-01")
        by_id = {p["part_id"]: p for p in result["parts"]}
        assert by_id["p_old"]["effective"] is False
        assert by_id["p_new"]["effective"] is True

    def test_effectivity_date_echoed_back(self):
        result = bom_150_percent([], effectivity_date="2024-01-01")
        assert result["effectivity_date"] == "2024-01-01"

    def test_always_effective_part(self):
        p = _part("p1", "Always")
        asm = _asm("a1", "Asm", [_comp("p1")])
        result = bom_150_percent([p, asm], effectivity_date="2020-01-01")
        assert result["parts"][0]["effective"] is True

    def test_effectivity_windows_in_result(self):
        p = _part("p1", "Widget")
        asm = _asm("a1", "Asm", [
            _comp("p1", effectivity={"valid_from": "2024-01-01", "valid_until": "2024-12-31"})
        ])
        result = bom_150_percent([p, asm])
        part = result["parts"][0]
        assert len(part["effectivity"]) >= 1
        eff = part["effectivity"][0]
        assert eff["valid_from"] == "2024-01-01"
        assert eff["valid_until"] == "2024-12-31"

    def test_multiple_windows_same_part(self):
        """Part used in two assemblies with different windows → both windows recorded."""
        p = _part("p1", "Shared Part")
        asm1 = _asm("a1", "Asm1", [
            _comp("p1", effectivity={"valid_from": None, "valid_until": "2023-12-31"})
        ])
        asm2 = _asm("a2", "Asm2", [
            _comp("p1", effectivity={"valid_from": "2024-01-01", "valid_until": None})
        ])
        result = bom_150_percent([p, asm1, asm2])
        assert len(result["parts"]) == 1
        windows = result["parts"][0]["effectivity"]
        assert len(windows) == 2


# ---------------------------------------------------------------------------
# LLM tool wrapper tests
# ---------------------------------------------------------------------------

class TestPlmBom150LlmTool:
    def test_tool_basic(self):
        from kerf_cloud.plm.llm_tools import plm_bom_150_percent
        p = _part("p1", "Part A")
        asm = _asm("a1", "Asm", [_comp("p1")])
        files_json = json.dumps([p, asm])
        result = plm_bom_150_percent(files_json)
        assert len(result["parts"]) == 1

    def test_tool_bad_json(self):
        from kerf_cloud.plm.llm_tools import plm_bom_150_percent
        result = plm_bom_150_percent("not json")
        assert result["ok"] is False
        assert result["code"] == "PARSE_ERROR"

    def test_tool_defs_include_bom(self):
        from kerf_cloud.plm.llm_tools import TOOL_DEFS
        names = {t["name"] for t in TOOL_DEFS}
        assert "plm_bom_150_percent" in names
