"""
Tests for kerf_packaging pre-press and material yield LLM tools.

Covers:
  Pre-press tools (packaging_prepress_check, packaging_prepress_gen_marks,
                   packaging_prepress_export_pdf_x1a):
    1.  Spec names and required fields
    2.  Plugin registration — all 8 tools in ctx.tools
    3.  prepress_check — valid job returns ok:True
    4.  prepress_check — bleed < 3 mm is flagged
    5.  prepress_check — safety zone breach is flagged
    6.  prepress_check — missing trim_box returns error
    7.  prepress_gen_marks — returns 4 marks
    8.  prepress_gen_marks — marks outside trim box
    9.  prepress_export_pdf_x1a — returns ok:True + pdf_size_bytes > 0
    10. prepress_export_pdf_x1a — bad trim_box returns error

  Material yield tool (packaging_material_yield):
    11. Spec name + required fields
    12. A4 sheet, 100×100 outline → parts_per_sheet == 4
    13. Cost scales linearly with quantity
    14. waste_pct == 100 - efficiency
    15. material_cost_per_part > 0
    16. job_quantity = 0 → BAD_ARGS
    17. honest_caveat present in result

All tests hermetic (no DB / filesystem / network).
"""

from __future__ import annotations

import asyncio
import json
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_packaging.tools import (
    packaging_prepress_check_spec,
    run_packaging_prepress_check,
    packaging_prepress_gen_marks_spec,
    run_packaging_prepress_gen_marks,
    packaging_prepress_export_pdf_x1a_spec,
    run_packaging_prepress_export_pdf_x1a,
    packaging_material_yield_spec,
    run_packaging_material_yield,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


def _call_check(**kwargs):
    return json.loads(_run(run_packaging_prepress_check(kwargs, CTX)))

def _call_marks(**kwargs):
    return json.loads(_run(run_packaging_prepress_gen_marks(kwargs, CTX)))

def _call_export(**kwargs):
    return json.loads(_run(run_packaging_prepress_export_pdf_x1a(kwargs, CTX)))

def _call_yield(**kwargs):
    return json.loads(_run(run_packaging_material_yield(kwargs, CTX)))


# A4 trim box placed at offset (10,10) in mm
TRIM_A4 = [10.0, 10.0, 220.0, 307.0]
ARTWORK_SAFE    = [20.0, 20.0, 210.0, 297.0]
ARTWORK_BREACH  = [12.0, 12.0, 218.0, 305.0]

# A4 sheet material spec for yield tests
A4_YIELD_ARGS = dict(
    box_outline=[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
    material_name="sbs_320gsm",
    cost_per_kg=1.60,
    sheet_width_mm=210.0,
    sheet_height_mm=297.0,
    sheet_weight_gsm=320.0,
    job_quantity=100,
    nesting_efficiency_pct=75.0,
)


# ===========================================================================
# 1. Spec names and required fields
# ===========================================================================

class TestSpecs:
    def test_prepress_check_spec_name(self):
        assert packaging_prepress_check_spec.name == "packaging_prepress_check"

    def test_prepress_check_required_trim_box(self):
        assert "trim_box" in packaging_prepress_check_spec.input_schema["required"]

    def test_prepress_gen_marks_spec_name(self):
        assert packaging_prepress_gen_marks_spec.name == "packaging_prepress_gen_marks"

    def test_prepress_gen_marks_required_trim_box(self):
        assert "trim_box" in packaging_prepress_gen_marks_spec.input_schema["required"]

    def test_prepress_export_pdf_x1a_spec_name(self):
        assert packaging_prepress_export_pdf_x1a_spec.name == "packaging_prepress_export_pdf_x1a"

    def test_prepress_export_required_trim_box(self):
        assert "trim_box" in packaging_prepress_export_pdf_x1a_spec.input_schema["required"]

    def test_material_yield_spec_name(self):
        assert packaging_material_yield_spec.name == "packaging_material_yield"

    def test_material_yield_required_fields(self):
        req = packaging_material_yield_spec.input_schema["required"]
        for field in ["box_outline", "cost_per_kg", "sheet_width_mm", "sheet_height_mm",
                      "sheet_weight_gsm", "job_quantity"]:
            assert field in req, f"Missing required field: {field}"

    def test_spec_description_mentions_iso(self):
        assert "ISO" in packaging_prepress_check_spec.description


# ===========================================================================
# 2. Plugin registration — all 8 tools in ctx.tools
# ===========================================================================

class TestPluginRegistration:
    def test_all_tools_registered(self):
        from kerf_packaging.plugin import _register_tools

        class _MockReg:
            def __init__(self):
                self.registered = {}
            def register(self, name, spec, handler):
                self.registered[name] = (spec, handler)

        class _MockCtx:
            def __init__(self):
                self.tools = _MockReg()

        ctx = _MockCtx()
        provides = []
        _register_tools(ctx, provides)

        expected_tools = [
            "packaging_dieline_generate",
            "packaging_dieline_to_dxf",
            "packaging_fold_preview",
            "packaging_bct_estimate",
            "packaging_prepress_check",
            "packaging_prepress_gen_marks",
            "packaging_prepress_export_pdf_x1a",
            "packaging_material_yield",
        ]
        for t in expected_tools:
            assert t in ctx.tools.registered, f"Tool not registered: {t}"

    def test_provides_includes_prepress_check(self):
        from kerf_packaging.plugin import _register_tools

        class _MockReg:
            def register(self, *a): pass

        class _MockCtx:
            tools = _MockReg()

        provides = []
        _register_tools(_MockCtx(), provides)
        assert "packaging.prepress-check" in provides

    def test_provides_includes_material_yield(self):
        from kerf_packaging.plugin import _register_tools

        class _MockReg:
            def register(self, *a): pass

        class _MockCtx:
            tools = _MockReg()

        provides = []
        _register_tools(_MockCtx(), provides)
        assert "packaging.material-yield" in provides


# ===========================================================================
# 3. prepress_check — valid job returns ok:True
# ===========================================================================

class TestPrePressCheck:
    def test_valid_job_ok(self):
        marks = [
            {"position": [2.0,  2.0],  "kind": "corner_bracket", "color_layers": ["cyan","black"]},
            {"position": [228.0, 2.0],  "kind": "corner_bracket", "color_layers": ["cyan","black"]},
            {"position": [228.0, 314.0],"kind": "corner_bracket", "color_layers": ["cyan","black"]},
            {"position": [2.0,  314.0], "kind": "corner_bracket", "color_layers": ["cyan","black"]},
        ]
        result = _call_check(
            trim_box=TRIM_A4,
            bleed_mm=3.0,
            safety_zone_mm=4.0,
            registration_marks=marks,
            artwork_bbox=ARTWORK_SAFE,
        )
        assert result.get("ok") is True
        assert result["bleed_mm_correct"] is True
        assert result["safety_zone_clear"] is True
        assert result["registration_mark_count"] == 4

    # 4. bleed < 3 mm is flagged
    def test_bleed_too_small_flagged(self):
        result = _call_check(trim_box=TRIM_A4, bleed_mm=2.0)
        assert result.get("ok") is True
        assert result["bleed_mm_correct"] is False
        assert any("BLEED" in w for w in result.get("warnings", []))

    # 5. safety zone breach is flagged
    def test_safety_zone_breach_flagged(self):
        result = _call_check(
            trim_box=TRIM_A4,
            bleed_mm=3.0,
            artwork_bbox=ARTWORK_BREACH,
        )
        assert result.get("ok") is True
        assert result["safety_zone_clear"] is False
        assert any("SAFETY" in w for w in result.get("warnings", []))

    # 6. missing trim_box returns error
    def test_missing_trim_box_returns_error(self):
        result = _call_check(trim_box=[10.0, 10.0])  # only 2 elements
        assert result.get("ok") is False
        assert "trim_box" in result.get("reason", "").lower()

    def test_plate_count_4_without_spots(self):
        result = _call_check(trim_box=TRIM_A4)
        assert result.get("estimated_plate_count") == 4

    def test_honest_caveat_always_present(self):
        result = _call_check(trim_box=TRIM_A4)
        assert any("HONEST" in w for w in result.get("warnings", []))


# ===========================================================================
# 7–8. prepress_gen_marks
# ===========================================================================

class TestPrePressGenMarks:
    def test_returns_4_marks(self):
        result = _call_marks(trim_box=TRIM_A4)
        assert result.get("ok") is True
        assert len(result["marks"]) == 4

    def test_all_corner_bracket(self):
        result = _call_marks(trim_box=TRIM_A4)
        assert all(m["kind"] == "corner_bracket" for m in result["marks"])

    def test_marks_outside_trim_box(self):
        result = _call_marks(trim_box=TRIM_A4)
        x0, y0, x1, y1 = TRIM_A4
        for m in result["marks"]:
            px, py = m["position"]
            # At least one coordinate must be outside the trim box
            outside = px < x0 or px > x1 or py < y0 or py > y1
            assert outside, f"Mark at {m['position']} is inside trim box"

    def test_cmyk_layers(self):
        result = _call_marks(trim_box=TRIM_A4)
        for m in result["marks"]:
            assert set(m["color_layers"]) == {"cyan", "magenta", "yellow", "black"}

    def test_bad_trim_box(self):
        result = _call_marks(trim_box=[1.0])  # too short
        assert result.get("ok") is False


# ===========================================================================
# 9–10. prepress_export_pdf_x1a
# ===========================================================================

class TestPrePressExport:
    def test_returns_ok(self):
        result = _call_export(trim_box=TRIM_A4, bleed_mm=3.0)
        assert result.get("ok") is True

    def test_pdf_size_positive(self):
        result = _call_export(trim_box=TRIM_A4)
        assert result.get("pdf_size_bytes", 0) > 100

    def test_honest_caveat_present(self):
        result = _call_export(trim_box=TRIM_A4)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 10

    def test_with_spot_colors(self):
        result = _call_export(
            trim_box=TRIM_A4,
            spot_colors=[
                {"layer_id": "p485", "color_name": "PANTONE 485 C", "coverage_pct": 40.0}
            ],
        )
        assert result.get("ok") is True
        assert "PANTONE 485 C" in result.get("spot_colors", [])

    def test_bad_trim_box(self):
        result = _call_export(trim_box="not_a_list")
        assert result.get("ok") is False


# ===========================================================================
# 11. packaging_material_yield — spec
# ===========================================================================

class TestMaterialYieldSpec:
    def test_spec_name(self):
        assert packaging_material_yield_spec.name == "packaging_material_yield"

    def test_description_mentions_pmmi(self):
        assert "PMMI" in packaging_material_yield_spec.description


# ===========================================================================
# 12. A4 sheet, 100×100 outline → parts_per_sheet == 4
# ===========================================================================

def test_a4_100mm_square_parts_per_sheet():
    """A4: 210×297 = 62370 mm²; bbox = 10000 mm²; 75% eff → floor(4.677) = 4."""
    result = _call_yield(**A4_YIELD_ARGS)
    assert "parts_per_sheet" in result
    assert result["parts_per_sheet"] == 4, f"expected 4, got {result['parts_per_sheet']}"


# ===========================================================================
# 13. Cost scales linearly with quantity
# ===========================================================================

def test_cost_scales_linearly():
    r100 = _call_yield(**A4_YIELD_ARGS)
    r200 = _call_yield(**{**A4_YIELD_ARGS, "job_quantity": 200})
    ratio = r200["total_material_cost"] / r100["total_material_cost"]
    assert abs(ratio - 2.0) < 0.1, f"cost ratio {ratio:.3f} expected ~2.0"


# ===========================================================================
# 14. waste_pct == 100 - efficiency
# ===========================================================================

def test_waste_pct_complement():
    result = _call_yield(**A4_YIELD_ARGS)
    assert abs(result["waste_pct"] - 25.0) < 1e-6


# ===========================================================================
# 15. material_cost_per_part > 0
# ===========================================================================

def test_cost_per_part_positive():
    result = _call_yield(**A4_YIELD_ARGS)
    assert result["material_cost_per_part"] > 0


# ===========================================================================
# 16. job_quantity = 0 → BAD_ARGS
# ===========================================================================

def test_zero_job_quantity_error():
    args = {**A4_YIELD_ARGS, "job_quantity": 0}
    result = _call_yield(**args)
    assert result.get("code") == "BAD_ARGS"


# ===========================================================================
# 17. honest_caveat present
# ===========================================================================

def test_honest_caveat_in_result():
    result = _call_yield(**A4_YIELD_ARGS)
    assert "honest_caveat" in result
    assert len(result["honest_caveat"]) > 10


# ===========================================================================
# Bonus: sheets_per_job is ceiling(qty / parts_per_sheet)
# ===========================================================================

def test_sheets_per_job_ceiling():
    import math
    result = _call_yield(**{**A4_YIELD_ARGS, "job_quantity": 7})
    expected = math.ceil(7 / result["parts_per_sheet"])
    assert result["sheets_per_job"] == expected
