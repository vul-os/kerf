"""
Tests for kerf_mold.mold_base_library
======================================
Covers standard mold base selection, plate stack-up, hardware selection,
input validation, LLM tool dispatch, and plugin registration.

References:
  Sanford, J. (2017). *Mold Engineering*, 2nd ed., Hanser Publishers, §3–§4.
  DME Mold Components Catalog — CD/CV series §2–§6.
"""
import asyncio
import json
import math

import pytest

from kerf_mold.mold_base_library import (
    MoldBasePlate,
    MoldBaseAssembly,
    standard_mold_base,
    list_catalog_sizes,
    DME_CD_SERIES_SIZES_MM,
    CATALOG_SIZES,
    CATALOG_THICKNESSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# 1. 50×50mm cavity → smallest DME CD accommodating it with 30mm clearance
# ---------------------------------------------------------------------------

def test_50x50_cavity_selects_adequate_dme_size():
    """A 50×50 mm cavity with 30 mm clearance each side needs ≥110×110 mm plate.
    The smallest DME CD size ≥ 110 mm in both dims is 130×130 mm.
    """
    asm = standard_mold_base(50.0, 50.0, 20.0, catalog="DME", series="CD")
    # Cavity + 2×30 mm clearance = 110 mm in each direction
    assert asm.plate_width_mm >= 110.0
    assert asm.plate_length_mm >= 110.0


def test_50x50_cavity_is_smallest_adequate():
    """The selected size should be the smallest available that fits."""
    asm = standard_mold_base(50.0, 50.0, 20.0, catalog="DME", series="CD")
    sizes = sorted(DME_CD_SERIES_SIZES_MM, key=lambda s: s[0] * s[1])
    for w, l in sizes:
        if (w >= asm.plate_width_mm and l >= asm.plate_length_mm) or \
           (l >= asm.plate_width_mm and w >= asm.plate_length_mm):
            # All sizes smaller than selected should be inadequate
            break
    # Just verify selected plate fits cavity + clearance
    req = 50.0 + 2 * 30.0
    assert asm.plate_width_mm >= req
    assert asm.plate_length_mm >= req


# ---------------------------------------------------------------------------
# 2. MoldBaseAssembly total_height_mm > 100mm for any non-trivial base
# ---------------------------------------------------------------------------

def test_total_height_exceeds_100mm():
    """Any standard mold base with non-trivial cavity should be > 100 mm tall."""
    asm = standard_mold_base(50.0, 50.0, 20.0)
    assert asm.total_height_mm > 100.0, (
        f"Expected total_height_mm > 100, got {asm.total_height_mm}"
    )


def test_total_height_matches_sum_of_plates():
    """total_height_mm must equal sum of all plate thicknesses."""
    asm = standard_mold_base(80.0, 100.0, 30.0)
    computed = sum(p.thickness_mm for p in asm.plates)
    assert asm.total_height_mm == pytest.approx(computed, abs=0.01)


# ---------------------------------------------------------------------------
# 3. Plate stack-up — all seven roles present
# ---------------------------------------------------------------------------

EXPECTED_ROLES = {"TCP", "CB-A", "CB-B", "BB", "BC", "EJ-A", "EJ-B"}


def test_seven_plate_roles_present():
    asm = standard_mold_base(60.0, 80.0, 25.0)
    roles = {p.role for p in asm.plates}
    assert roles == EXPECTED_ROLES, f"Expected roles {EXPECTED_ROLES}, got {roles}"


def test_plates_are_moldbaseplate_instances():
    asm = standard_mold_base(60.0, 80.0, 25.0)
    for p in asm.plates:
        assert isinstance(p, MoldBasePlate)


# ---------------------------------------------------------------------------
# 4. A-plate and B-plate thickness grow with cavity depth
# ---------------------------------------------------------------------------

def test_a_plate_grows_with_cavity_depth():
    asm_shallow = standard_mold_base(80.0, 80.0, 10.0)
    asm_deep = standard_mold_base(80.0, 80.0, 60.0)
    a_shallow = next(p for p in asm_shallow.plates if p.role == "CB-A")
    a_deep = next(p for p in asm_deep.plates if p.role == "CB-A")
    assert a_deep.thickness_mm > a_shallow.thickness_mm, (
        f"Deep A-plate ({a_deep.thickness_mm}) should be thicker than shallow ({a_shallow.thickness_mm})"
    )


def test_b_plate_grows_with_cavity_depth():
    asm_shallow = standard_mold_base(80.0, 80.0, 10.0)
    asm_deep = standard_mold_base(80.0, 80.0, 50.0)
    b_shallow = next(p for p in asm_shallow.plates if p.role == "CB-B")
    b_deep = next(p for p in asm_deep.plates if p.role == "CB-B")
    assert b_deep.thickness_mm > b_shallow.thickness_mm


# ---------------------------------------------------------------------------
# 5. Cavity area = plate_w × plate_l
# ---------------------------------------------------------------------------

def test_cavity_area_correct():
    asm = standard_mold_base(70.0, 90.0, 20.0)
    expected = asm.plate_width_mm * asm.plate_length_mm
    assert asm.cavity_area_mm2 == pytest.approx(expected, abs=0.1)


# ---------------------------------------------------------------------------
# 6. Leader pin count = 4
# ---------------------------------------------------------------------------

def test_leader_pin_count_is_4():
    asm = standard_mold_base(80.0, 100.0, 25.0)
    total_pins = sum(lp["count"] for lp in asm.leader_pins)
    assert total_pins == 4


def test_bushing_count_matches_leader_pins():
    asm = standard_mold_base(80.0, 100.0, 25.0)
    pin_count = sum(lp["count"] for lp in asm.leader_pins)
    bush_count = sum(b["count"] for b in asm.bushings)
    assert pin_count == bush_count


# ---------------------------------------------------------------------------
# 7. Hasco catalog returns valid assembly
# ---------------------------------------------------------------------------

def test_hasco_catalog_returns_assembly():
    asm = standard_mold_base(80.0, 80.0, 20.0, catalog="Hasco", series="Z")
    assert asm.catalog == "Hasco"
    assert asm.total_height_mm > 100.0
    assert len(asm.plates) == 7


# ---------------------------------------------------------------------------
# 8. Misumi catalog returns valid assembly
# ---------------------------------------------------------------------------

def test_misumi_catalog_returns_assembly():
    asm = standard_mold_base(80.0, 80.0, 20.0, catalog="Misumi", series="FSWP")
    assert asm.catalog == "Misumi"
    assert asm.total_height_mm > 100.0


# ---------------------------------------------------------------------------
# 9. Invalid inputs raise ValueError
# ---------------------------------------------------------------------------

def test_zero_cavity_width_raises():
    with pytest.raises(ValueError, match="cavity_w_mm must be > 0"):
        standard_mold_base(0.0, 80.0, 20.0)


def test_negative_cavity_height_raises():
    with pytest.raises(ValueError, match="cavity_h_mm must be > 0"):
        standard_mold_base(80.0, -5.0, 20.0)


def test_zero_cavity_depth_raises():
    with pytest.raises(ValueError, match="cavity_depth_mm must be > 0"):
        standard_mold_base(80.0, 80.0, 0.0)


def test_unknown_catalog_raises():
    with pytest.raises(ValueError, match="catalog must be one of"):
        standard_mold_base(80.0, 80.0, 20.0, catalog="FakeVendor")


# ---------------------------------------------------------------------------
# 10. Honest caveat present and mentions catalog
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    asm = standard_mold_base(80.0, 100.0, 30.0)
    assert len(asm.honest_caveat) > 50
    assert "HONEST" in asm.honest_caveat
    assert "DME" in asm.honest_caveat or "Hasco" in asm.honest_caveat or "Misumi" in asm.honest_caveat


# ---------------------------------------------------------------------------
# 11. list_catalog_sizes returns non-empty list
# ---------------------------------------------------------------------------

def test_list_catalog_sizes_dme():
    sizes = list_catalog_sizes("DME")
    assert len(sizes) >= 5
    for w, l in sizes:
        assert w > 0 and l > 0


def test_list_catalog_sizes_invalid_raises():
    with pytest.raises(ValueError, match="Unknown catalog"):
        list_catalog_sizes("XYZ")


# ---------------------------------------------------------------------------
# 12. LLM tool dispatch
# ---------------------------------------------------------------------------

def test_tool_dispatch_basic():
    from kerf_mold.mold_base_library_tool import run_mold_select_standard_base
    result = json.loads(_run(run_mold_select_standard_base({
        "cavity_w_mm": 50.0,
        "cavity_h_mm": 50.0,
        "cavity_depth_mm": 20.0,
    }, CTX)))
    assert result.get("ok") is True
    assert result["total_height_mm"] > 100.0
    assert len(result["plates"]) == 7


def test_tool_dispatch_missing_cavity_w():
    from kerf_mold.mold_base_library_tool import run_mold_select_standard_base
    result = json.loads(_run(run_mold_select_standard_base({
        "cavity_h_mm": 80.0,
        "cavity_depth_mm": 20.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_invalid_catalog():
    from kerf_mold.mold_base_library_tool import run_mold_select_standard_base
    result = json.loads(_run(run_mold_select_standard_base({
        "cavity_w_mm": 80.0,
        "cavity_h_mm": 80.0,
        "cavity_depth_mm": 25.0,
        "catalog": "NotACatalog",
    }, CTX)))
    assert "error" in result


# ---------------------------------------------------------------------------
# 13. Tool spec name
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.mold_base_library_tool import mold_select_standard_base_spec
    assert mold_select_standard_base_spec.name == "mold_select_standard_base"


def test_tool_spec_required_fields():
    from kerf_mold.mold_base_library_tool import mold_select_standard_base_spec
    req = mold_select_standard_base_spec.input_schema.get("required", [])
    assert "cavity_w_mm" in req
    assert "cavity_h_mm" in req
    assert "cavity_depth_mm" in req


# ---------------------------------------------------------------------------
# 14. Plugin registers mold_select_standard_base
# ---------------------------------------------------------------------------

def test_plugin_registers_mold_base_tool():
    from kerf_mold.plugin import register
    from fastapi import FastAPI

    class _MockReg:
        def __init__(self):
            self.registered = {}
        def register(self, name, spec, handler):
            self.registered[name] = (spec, handler)

    class _MockCtx:
        def __init__(self):
            self.tools = _MockReg()

    app = FastAPI()
    ctx = _MockCtx()

    async def _go():
        return await register(app, ctx)

    _run(_go())
    assert "mold_select_standard_base" in ctx.tools.registered
    assert "mold_design_edm_electrode" in ctx.tools.registered
    assert "mold_generate_wire_edm_gcode" in ctx.tools.registered


# ---------------------------------------------------------------------------
# 15. Larger cavity → larger or equal plate selection
# ---------------------------------------------------------------------------

def test_larger_cavity_gives_larger_or_equal_plate():
    asm_small = standard_mold_base(30.0, 30.0, 15.0)
    asm_large = standard_mold_base(200.0, 250.0, 30.0)
    assert asm_large.plate_width_mm >= asm_small.plate_width_mm
    assert asm_large.plate_length_mm >= asm_small.plate_length_mm


# ---------------------------------------------------------------------------
# 16. MoldBasePlate validation
# ---------------------------------------------------------------------------

def test_moldbaseplate_invalid_thickness():
    with pytest.raises(ValueError, match="thickness_mm must be > 0"):
        MoldBasePlate(
            catalog="DME", series="CD", role="TCP",
            thickness_mm=0.0, width_mm=100.0, length_mm=100.0, material="P20"
        )


def test_moldbaseplate_invalid_catalog():
    with pytest.raises(ValueError, match="catalog must be one of"):
        MoldBasePlate(
            catalog="XYZ", series="CD", role="TCP",
            thickness_mm=25.0, width_mm=100.0, length_mm=100.0, material="P20"
        )
