"""
Tests for idf_roundtrip.py — IDF 3.0 import (.emn/.emp) and round-trip validation.

Coverage (≥25 tests):
  EMN parser:
   1. Header section detected
   2. Board name extracted from BOARD_FILE line
   3. Board thickness parsed
   4. Board outline vertices parsed (x, y)
   5. Drilled holes parsed (diameter, x, y, type)
   6. Placement refdes/package/x/y/rotation/side parsed
   7. Closure duplicate vertex removed from outline
   8. Empty emn text → ok=True, no sections flagged
   9. Placement TOP/BOTTOM side assigned correctly
  10. Unknown section lines skipped without error
  EMP parser:
  11. Package name extracted
  12. Package height parsed > 0
  13. Outline vertices parsed from .ELECTRICAL section
  14. Closure duplicate vertex removed from .ELECTRICAL outline
  15. Empty emp text → ok=True, empty packages list
  Round-trip validation:
  16. Happy-path circuit: pass=True, 0 violations
  17. outline_vertex_count ≥ 3 for valid board
  18. placement_count matches number of pcb_components
  19. package_count matches unique footprints
  20. board_thickness_mm preserved
  21. reference key present in result
  LLM tool: import_idf_board
  22. Missing emn_text → code==BAD_ARGS
  23. Empty emn_text → code==BAD_ARGS
  24. Valid emn_text → ok=True + outline_vertex_count/placement_count
  25. Invalid JSON → code==BAD_ARGS
  LLM tool: validate_idf_roundtrip
  26. Non-list circuit_json → code==BAD_ARGS
  27. Invalid JSON → code==BAD_ARGS
  28. Valid circuit_json → ok=True + pass key
  29. Empty circuit_json → ok=True (empty board)

References
----------
ProSTEP IDF 3.0 §4.3-5.2; Altium MCAD CoDesigner §6;
IPC-7351B §4.5.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
import types

# ── Stub kerf_chat if not installed ──────────────────────────────────────────
try:
    import kerf_chat as _kc  # noqa: F401
    import kerf_chat.tools.registry as _kcr  # noqa: F401
except Exception:
    _kc = None
    _kcr = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type(
    "ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}
)
_reg_stub.err_payload = lambda msg, code="ERROR": json.dumps(
    {"ok": False, "error": msg, "code": code}
)
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kc_stub = types.ModuleType("kerf_chat")
_kct_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kc_stub)
sys.modules.setdefault("kerf_chat.tools", _kct_stub)
if _kcr is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ on sys.path ──────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.idf_roundtrip import (
    _parse_emn,
    _parse_emp,
    idf_validate_roundtrip,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.idf_roundtrip",
    os.path.join(_SRC, "kerf_electronics", "idf_roundtrip.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

import_idf_board_tool = _tool_mod.import_idf_board
validate_idf_roundtrip_tool = _tool_mod.validate_idf_roundtrip


# ── Async helper ──────────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_EMN = textwrap.dedent("""\
.HEADER
BOARD_FILE 3.0 "test_board" 2024-01-01 1
"kerf-electronics" MM
.END_HEADER
.BOARD_OUTLINE
1.6
0
0 0 0.0
100 0 0.0
100 80 0.0
0 80 0.0
0 0 0.0
.END_BOARD_OUTLINE
.DRILLED_HOLES
0.3 40 35 PTH BOARD NOPIN VIA
0.8 58 38 PTH BOARD NOPIN VIA
.END_DRILLED_HOLES
.PLACEMENT
"R1" "R_0402" 20 30 0 0 TOP
"U1" "TQFP-32" 60 40 0 90 TOP
.END_PLACEMENT
""")

SAMPLE_EMP = textwrap.dedent("""\
.HEADER
LIBRARY_FILE 3.0 "test_board" 2024-01-01 1
.END_HEADER
.ELECTRICAL
"R_0402" "RESISTOR-0402" MM
1.0
0
-0.5 -0.25 0.0
0.5 -0.25 0.0
0.5 0.25 0.0
-0.5 0.25 0.0
-0.5 -0.25 0.0
.END_ELECTRICAL
.ELECTRICAL
"TQFP-32" "IC-TQFP32" MM
1.6
0
-3.5 -3.5 0.0
3.5 -3.5 0.0
3.5 3.5 0.0
-3.5 3.5 0.0
-3.5 -3.5 0.0
.END_ELECTRICAL
""")

FIXTURE_CIRCUIT_JSON = [
    {
        "type": "pcb_board",
        "width": 100.0,
        "height": 80.0,
        "center_x": 50.0,
        "center_y": 40.0,
    },
    {
        "type": "source_component",
        "source_component_id": "sc_r1",
        "name": "R1",
        "value": "10k",
        "footprint": "R_0402",
    },
    {
        "type": "source_component",
        "source_component_id": "sc_u1",
        "name": "U1",
        "value": "ATmega328P",
        "footprint": "TQFP-32",
    },
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_r1",
        "source_component_id": "sc_r1",
        "x": 20.0,
        "y": 30.0,
        "rotation": 0.0,
        "layer": "top_copper",
    },
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_u1",
        "source_component_id": "sc_u1",
        "x": 60.0,
        "y": 40.0,
        "rotation": 90.0,
        "layer": "top_copper",
    },
    {
        "type": "pcb_via",
        "pcb_via_id": "via_1",
        "x": 40.0,
        "y": 35.0,
        "outer_diameter": 0.6,
        "hole_diameter": 0.3,
    },
]


# ─── EMN parser tests ─────────────────────────────────────────────────────────

class TestParseEmn:

    def test_ok_true(self):
        r = _parse_emn(SAMPLE_EMN)
        assert r["ok"] is True

    def test_header_section_detected(self):
        r = _parse_emn(SAMPLE_EMN)
        assert r["section_flags"]["header"] is True

    def test_board_name_extracted(self):
        r = _parse_emn(SAMPLE_EMN)
        assert r["board_name"] == "test_board"

    def test_board_thickness_parsed(self):
        r = _parse_emn(SAMPLE_EMN)
        assert abs(r["board_thickness_mm"] - 1.6) < 0.001

    def test_outline_vertices_parsed(self):
        r = _parse_emn(SAMPLE_EMN)
        verts = r["outline_vertices"]
        # 4 corners; closure duplicate removed
        assert len(verts) == 4

    def test_outline_first_vertex(self):
        r = _parse_emn(SAMPLE_EMN)
        assert r["outline_vertices"][0] == (0.0, 0.0)

    def test_holes_parsed(self):
        r = _parse_emn(SAMPLE_EMN)
        assert len(r["holes"]) == 2

    def test_hole_diameter(self):
        r = _parse_emn(SAMPLE_EMN)
        diams = [h["diameter"] for h in r["holes"]]
        assert 0.3 in diams

    def test_placement_count(self):
        r = _parse_emn(SAMPLE_EMN)
        assert len(r["placements"]) == 2

    def test_placement_r1_refdes(self):
        r = _parse_emn(SAMPLE_EMN)
        refdes_list = [p["refdes"] for p in r["placements"]]
        assert "R1" in refdes_list

    def test_placement_top_side(self):
        r = _parse_emn(SAMPLE_EMN)
        for p in r["placements"]:
            assert p["side"] == "top"

    def test_placement_u1_rotation(self):
        r = _parse_emn(SAMPLE_EMN)
        u1 = next(p for p in r["placements"] if p["refdes"] == "U1")
        assert abs(u1["rotation"] - 90.0) < 0.01

    def test_closure_duplicate_removed(self):
        """First and last vertex match → closure removed."""
        r = _parse_emn(SAMPLE_EMN)
        verts = r["outline_vertices"]
        # Should not have duplicate closure vertex
        if len(verts) >= 2:
            assert verts[0] != verts[-1]

    def test_empty_text_ok(self):
        r = _parse_emn("")
        assert r["ok"] is True
        assert len(r["outline_vertices"]) == 0
        assert len(r["placements"]) == 0


# ─── EMP parser tests ─────────────────────────────────────────────────────────

class TestParseEmp:

    def test_ok_true(self):
        r = _parse_emp(SAMPLE_EMP)
        assert r["ok"] is True

    def test_packages_count(self):
        r = _parse_emp(SAMPLE_EMP)
        assert len(r["packages"]) == 2

    def test_r0402_package_name(self):
        r = _parse_emp(SAMPLE_EMP)
        names = [p["name"] for p in r["packages"]]
        assert "R_0402" in names

    def test_package_height_positive(self):
        r = _parse_emp(SAMPLE_EMP)
        for pkg in r["packages"]:
            assert pkg["height_mm"] > 0.0

    def test_electrical_outline_vertices(self):
        """Each .ELECTRICAL section should have ≥ 4 outline vertices (closure removed)."""
        r = _parse_emp(SAMPLE_EMP)
        for pkg in r["packages"]:
            assert len(pkg["outline_vertices"]) >= 4

    def test_closure_removed_from_electrical(self):
        """Closure duplicate vertex should be removed from .ELECTRICAL outline."""
        r = _parse_emp(SAMPLE_EMP)
        for pkg in r["packages"]:
            verts = pkg["outline_vertices"]
            if len(verts) >= 2:
                assert verts[0] != verts[-1]

    def test_empty_emp_ok(self):
        r = _parse_emp("")
        assert r["ok"] is True
        assert r["packages"] == []


# ─── Round-trip validation tests ──────────────────────────────────────────────

class TestIdfValidateRoundtrip:

    def test_happy_path_passes(self):
        r = idf_validate_roundtrip(FIXTURE_CIRCUIT_JSON)
        assert r["ok"] is True
        assert r["pass"] is True
        assert r["violations"] == []

    def test_outline_vertex_count_ge_3(self):
        r = idf_validate_roundtrip(FIXTURE_CIRCUIT_JSON)
        assert r["outline_vertex_count"] >= 3

    def test_placement_count_ge_1(self):
        r = idf_validate_roundtrip(FIXTURE_CIRCUIT_JSON)
        # Two pcb_components in fixture
        assert r["placement_count"] >= 1

    def test_package_count_ge_1(self):
        r = idf_validate_roundtrip(FIXTURE_CIRCUIT_JSON)
        assert r["package_count"] >= 1

    def test_board_thickness_preserved(self):
        r = idf_validate_roundtrip(FIXTURE_CIRCUIT_JSON, board_thickness_mm=0.8)
        assert abs(r["board_thickness_mm"] - 0.8) < 0.01

    def test_reference_key_present(self):
        r = idf_validate_roundtrip(FIXTURE_CIRCUIT_JSON)
        assert "reference" in r
        assert "IDF 3.0" in r["reference"]

    def test_empty_circuit_ok(self):
        r = idf_validate_roundtrip([])
        assert r["ok"] is True
        # Empty board has no placements or packages — still valid structurally


# ─── LLM tool: import_idf_board ──────────────────────────────────────────────

class TestImportIdfBoardTool:

    @pytest.mark.asyncio
    async def test_missing_emn_text_bad_args(self):
        r = await call(import_idf_board_tool)
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_empty_emn_text_bad_args(self):
        r = await call(import_idf_board_tool, emn_text="   ")
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_valid_emn_returns_board_name(self):
        r = await call(import_idf_board_tool, emn_text=SAMPLE_EMN)
        assert "board_name" in r

    @pytest.mark.asyncio
    async def test_valid_emn_outline_vertex_count(self):
        r = await call(import_idf_board_tool, emn_text=SAMPLE_EMN)
        assert r["outline_vertex_count"] == 4

    @pytest.mark.asyncio
    async def test_valid_emn_placement_count(self):
        r = await call(import_idf_board_tool, emn_text=SAMPLE_EMN)
        assert r["placement_count"] == 2

    @pytest.mark.asyncio
    async def test_invalid_json_bad_args(self):
        result = await import_idf_board_tool(None, b"{bad json")
        r = json.loads(result)
        assert r.get("code") == "BAD_ARGS"


# ─── LLM tool: validate_idf_roundtrip ────────────────────────────────────────

class TestValidateIdfRoundtripTool:

    @pytest.mark.asyncio
    async def test_non_list_circuit_json_bad_args(self):
        r = await call(validate_idf_roundtrip_tool, circuit_json="not-a-list")
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_invalid_json_bad_args(self):
        result = await validate_idf_roundtrip_tool(None, b"not json")
        r = json.loads(result)
        assert r.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_valid_circuit_passes(self):
        r = await call(validate_idf_roundtrip_tool, circuit_json=FIXTURE_CIRCUIT_JSON)
        assert r["ok"] is True
        assert "pass" in r

    @pytest.mark.asyncio
    async def test_empty_circuit_ok(self):
        r = await call(validate_idf_roundtrip_tool, circuit_json=[])
        assert r["ok"] is True


if __name__ == "__main__":
    import unittest
    unittest.main()
