"""
Tests for kerf_mold.vent_depth_check
=====================================
Covers vent depth classification, polymer database values, edge cases,
unknown polymer fallback, LLM tool dispatch, plugin registration, and
__init__ re-exports.

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007,
    §8.3 + Table 8.2.
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §6.4 + Table 6.7.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_mold.vent_depth_check import (
    VENT_DEPTH_DB,
    VentDepthReport,
    VentSpec,
    check_vent_depth,
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
# 1. ABS, 0.030 mm → correct (within 0.025–0.038)
# ---------------------------------------------------------------------------

def test_abs_030_correct():
    """ABS at 0.030 mm is within [0.025, 0.038] → correct, compliant."""
    spec = VentSpec(polymer_grade="ABS", proposed_depth_mm=0.030)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True
    assert report.recommended_depth_min_mm == pytest.approx(0.025)
    assert report.recommended_depth_max_mm == pytest.approx(0.038)


# ---------------------------------------------------------------------------
# 2. ABS lower boundary — exactly at min → correct
# ---------------------------------------------------------------------------

def test_abs_at_min_boundary_correct():
    """ABS at exactly 0.025 mm is the lower boundary → correct."""
    spec = VentSpec(polymer_grade="ABS", proposed_depth_mm=0.025)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 3. ABS upper boundary — exactly at max → correct
# ---------------------------------------------------------------------------

def test_abs_at_max_boundary_correct():
    """ABS at exactly 0.038 mm is the upper boundary → correct."""
    spec = VentSpec(polymer_grade="ABS", proposed_depth_mm=0.038)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 4. PC, 0.010 mm → too_shallow (< 0.013)
# ---------------------------------------------------------------------------

def test_pc_010_too_shallow():
    """PC at 0.010 mm is below the minimum 0.013 mm → too_shallow."""
    spec = VentSpec(polymer_grade="PC", proposed_depth_mm=0.010)
    report = check_vent_depth(spec)
    assert report.depth_class == "too_shallow"
    assert report.compliant is False
    assert report.recommended_depth_min_mm == pytest.approx(0.013)
    assert report.recommended_depth_max_mm == pytest.approx(0.025)


# ---------------------------------------------------------------------------
# 5. PE, 0.100 mm → flash_risk (> 0.075 × 1.25 = 0.094)
# ---------------------------------------------------------------------------

def test_pe_100_flash_risk():
    """PE at 0.100 mm is > 0.075 × 1.25 = 0.09375 → flash_risk."""
    spec = VentSpec(polymer_grade="PE", proposed_depth_mm=0.100)
    report = check_vent_depth(spec)
    assert report.depth_class == "flash_risk"
    assert report.compliant is False
    assert report.recommended_depth_min_mm == pytest.approx(0.038)
    assert report.recommended_depth_max_mm == pytest.approx(0.075)


# ---------------------------------------------------------------------------
# 6. PE, 0.085 mm → too_deep (> 0.075 but ≤ 0.075×1.25)
# ---------------------------------------------------------------------------

def test_pe_085_too_deep():
    """PE at 0.085 mm is > 0.075 but ≤ 0.094 → too_deep."""
    spec = VentSpec(polymer_grade="PE", proposed_depth_mm=0.085)
    report = check_vent_depth(spec)
    assert report.depth_class == "too_deep"
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 7. PP, 0.025 mm → correct (lower boundary)
# ---------------------------------------------------------------------------

def test_pp_025_correct():
    """PP at 0.025 mm (lower boundary) → correct."""
    spec = VentSpec(polymer_grade="PP", proposed_depth_mm=0.025)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 8. PP, 0.015 mm → too_shallow (< 0.025)
# ---------------------------------------------------------------------------

def test_pp_015_too_shallow():
    """PP at 0.015 mm is below the minimum 0.025 mm → too_shallow."""
    spec = VentSpec(polymer_grade="PP", proposed_depth_mm=0.015)
    report = check_vent_depth(spec)
    assert report.depth_class == "too_shallow"
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 9. PA66 in correct range
# ---------------------------------------------------------------------------

def test_pa66_020_correct():
    """PA66 at 0.020 mm is within [0.013, 0.025] → correct."""
    spec = VentSpec(polymer_grade="PA66", proposed_depth_mm=0.020)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 10. POM, 0.013 mm → correct (lower boundary)
# ---------------------------------------------------------------------------

def test_pom_013_correct():
    """POM at 0.013 mm (lower boundary) → correct."""
    spec = VentSpec(polymer_grade="POM", proposed_depth_mm=0.013)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 11. PMMA at middle of range → correct
# ---------------------------------------------------------------------------

def test_pmma_030_correct():
    """PMMA at 0.030 mm is within [0.025, 0.038] → correct."""
    spec = VentSpec(polymer_grade="PMMA", proposed_depth_mm=0.030)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 12. Unknown polymer → graceful fallback with notes, no exception
# ---------------------------------------------------------------------------

def test_unknown_polymer_fallback():
    """Unknown polymer (TPU) gets fallback range [0.013, 0.038] with caveat."""
    spec = VentSpec(polymer_grade="TPU", proposed_depth_mm=0.025)
    report = check_vent_depth(spec)
    # Should not raise; falls back gracefully
    assert report.recommended_depth_min_mm == pytest.approx(0.013)
    assert report.recommended_depth_max_mm == pytest.approx(0.038)
    # Notes should mention "not found" or "fallback"
    assert "not found" in report.polymer_notes.lower() or "fallback" in report.polymer_notes.lower()
    assert report.honest_caveat != ""


# ---------------------------------------------------------------------------
# 13. Unknown polymer too_shallow
# ---------------------------------------------------------------------------

def test_unknown_polymer_too_shallow():
    """Unknown polymer at 0.005 mm → too_shallow against fallback range."""
    spec = VentSpec(polymer_grade="PEEK", proposed_depth_mm=0.005)
    report = check_vent_depth(spec)
    assert report.depth_class == "too_shallow"
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 14. Case-insensitive polymer grade
# ---------------------------------------------------------------------------

def test_polymer_grade_case_insensitive():
    """Polymer grade is case-insensitive ('abs' → 'ABS')."""
    spec = VentSpec(polymer_grade="abs", proposed_depth_mm=0.030)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 15. VentSpec rejects non-positive proposed_depth_mm
# ---------------------------------------------------------------------------

def test_zero_depth_raises():
    with pytest.raises(ValueError, match="proposed_depth_mm must be > 0"):
        VentSpec(polymer_grade="ABS", proposed_depth_mm=0.0)


def test_negative_depth_raises():
    with pytest.raises(ValueError, match="proposed_depth_mm must be > 0"):
        VentSpec(polymer_grade="ABS", proposed_depth_mm=-0.010)


# ---------------------------------------------------------------------------
# 16. VentSpec rejects negative land_length_mm
# ---------------------------------------------------------------------------

def test_negative_land_length_raises():
    with pytest.raises(ValueError, match="land_length_mm must be >= 0"):
        VentSpec(polymer_grade="ABS", proposed_depth_mm=0.030, land_length_mm=-1.0)


# ---------------------------------------------------------------------------
# 17. VentSpec rejects non-positive vent_width_mm
# ---------------------------------------------------------------------------

def test_zero_vent_width_raises():
    with pytest.raises(ValueError, match="vent_width_mm must be > 0"):
        VentSpec(polymer_grade="ABS", proposed_depth_mm=0.030, vent_width_mm=0.0)


# ---------------------------------------------------------------------------
# 18. Honest caveat mentions key references
# ---------------------------------------------------------------------------

def test_honest_caveat_references():
    """Honest caveat must cite Beaumont and Menges."""
    spec = VentSpec(polymer_grade="ABS", proposed_depth_mm=0.030)
    report = check_vent_depth(spec)
    assert "Beaumont" in report.honest_caveat
    assert "Menges" in report.honest_caveat
    assert "mold trial" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 19. VENT_DEPTH_DB values match Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7
# ---------------------------------------------------------------------------

def test_vent_depth_db_values():
    """Database values match the handbook tables exactly."""
    assert VENT_DEPTH_DB["ABS"]  == pytest.approx((0.025, 0.038))
    assert VENT_DEPTH_DB["PC"]   == pytest.approx((0.013, 0.025))
    assert VENT_DEPTH_DB["PP"]   == pytest.approx((0.025, 0.050))
    assert VENT_DEPTH_DB["PA66"] == pytest.approx((0.013, 0.025))
    assert VENT_DEPTH_DB["POM"]  == pytest.approx((0.013, 0.025))
    assert VENT_DEPTH_DB["PMMA"] == pytest.approx((0.025, 0.038))
    assert VENT_DEPTH_DB["PE"]   == pytest.approx((0.038, 0.075))


# ---------------------------------------------------------------------------
# 20. LLM tool dispatch — basic correct case
# ---------------------------------------------------------------------------

def test_tool_dispatch_abs_correct():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "polymer_grade": "ABS",
        "proposed_depth_mm": 0.030,
    }, CTX)))
    assert result.get("ok") is True
    assert result["depth_class"] == "correct"
    assert result["compliant"] is True
    assert result["recommended_depth_min_mm"] == pytest.approx(0.025)
    assert result["recommended_depth_max_mm"] == pytest.approx(0.038)


# ---------------------------------------------------------------------------
# 21. LLM tool dispatch — PC too_shallow
# ---------------------------------------------------------------------------

def test_tool_dispatch_pc_too_shallow():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "polymer_grade": "PC",
        "proposed_depth_mm": 0.010,
    }, CTX)))
    assert result.get("ok") is True
    assert result["depth_class"] == "too_shallow"
    assert result["compliant"] is False


# ---------------------------------------------------------------------------
# 22. LLM tool dispatch — PE flash_risk
# ---------------------------------------------------------------------------

def test_tool_dispatch_pe_flash_risk():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "polymer_grade": "PE",
        "proposed_depth_mm": 0.100,
    }, CTX)))
    assert result.get("ok") is True
    assert result["depth_class"] == "flash_risk"
    assert result["compliant"] is False


# ---------------------------------------------------------------------------
# 23. LLM tool dispatch — missing polymer_grade
# ---------------------------------------------------------------------------

def test_tool_dispatch_missing_polymer_grade():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "proposed_depth_mm": 0.030,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 24. LLM tool dispatch — missing proposed_depth_mm
# ---------------------------------------------------------------------------

def test_tool_dispatch_missing_depth():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "polymer_grade": "ABS",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 25. LLM tool dispatch — non-numeric depth
# ---------------------------------------------------------------------------

def test_tool_dispatch_non_numeric_depth():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "polymer_grade": "ABS",
        "proposed_depth_mm": "deep",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 26. Tool spec name and required fields
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.vent_depth_check_tool import mold_check_vent_depth_spec
    assert mold_check_vent_depth_spec.name == "mold_check_vent_depth"


def test_tool_spec_required_fields():
    from kerf_mold.vent_depth_check_tool import mold_check_vent_depth_spec
    required = mold_check_vent_depth_spec.input_schema.get("required", [])
    assert "polymer_grade" in required
    assert "proposed_depth_mm" in required


# ---------------------------------------------------------------------------
# 27. Plugin registers mold_check_vent_depth
# ---------------------------------------------------------------------------

def test_plugin_registers_vent_depth_tool():
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
    assert "mold_check_vent_depth" in ctx.tools.registered, (
        "mold_check_vent_depth should be registered in the plugin"
    )


# ---------------------------------------------------------------------------
# 28. Re-export from kerf_mold.__init__
# ---------------------------------------------------------------------------

def test_init_exports():
    from kerf_mold import (
        VentSpec,
        VentDepthReport,
        VENT_DEPTH_DB,
        check_vent_depth,
    )
    assert VentSpec is not None
    assert VentDepthReport is not None
    assert "ABS" in VENT_DEPTH_DB
    assert callable(check_vent_depth)


# ---------------------------------------------------------------------------
# 29. PC correct range midpoint
# ---------------------------------------------------------------------------

def test_pc_018_correct():
    """PC at 0.018 mm is within [0.013, 0.025] → correct."""
    spec = VentSpec(polymer_grade="PC", proposed_depth_mm=0.018)
    report = check_vent_depth(spec)
    assert report.depth_class == "correct"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 30. POM too_deep (just over max, within 25%)
# ---------------------------------------------------------------------------

def test_pom_028_too_deep():
    """POM at 0.028 mm is > 0.025 but ≤ 0.025×1.25=0.03125 → too_deep."""
    spec = VentSpec(polymer_grade="POM", proposed_depth_mm=0.028)
    report = check_vent_depth(spec)
    assert report.depth_class == "too_deep"
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 31. PA66 flash_risk (very deep)
# ---------------------------------------------------------------------------

def test_pa66_050_flash_risk():
    """PA66 at 0.050 mm is > 0.025×1.25=0.03125 → flash_risk."""
    spec = VentSpec(polymer_grade="PA66", proposed_depth_mm=0.050)
    report = check_vent_depth(spec)
    assert report.depth_class == "flash_risk"
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 32. Default land and width values on VentSpec
# ---------------------------------------------------------------------------

def test_ventspec_defaults():
    """VentSpec default land_length_mm=1.5, vent_width_mm=6.0."""
    spec = VentSpec(polymer_grade="ABS", proposed_depth_mm=0.030)
    assert spec.land_length_mm == pytest.approx(1.5)
    assert spec.vent_width_mm == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 33. Tool dispatch — unknown polymer returns ok with flash_risk notes
# ---------------------------------------------------------------------------

def test_tool_dispatch_unknown_polymer():
    from kerf_mold.vent_depth_check_tool import run_mold_check_vent_depth
    result = json.loads(_run(run_mold_check_vent_depth({
        "polymer_grade": "TPE",
        "proposed_depth_mm": 0.025,
    }, CTX)))
    assert result.get("ok") is True
    # Should not be an error — graceful fallback
    assert "depth_class" in result
    assert "polymer_notes" in result
    assert result["polymer_notes"] != ""
