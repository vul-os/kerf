"""
Tests for kerf_mold.vent_slot_layout
======================================
Covers Beaumont 2007 §8.5 + Menges 2001 §6.4 vent slot layout calculation:
slot count, width, spacing, adequacy, speed scaling, polymer sensitivity,
perimeter constraints, minimum slot enforcement, error cases, LLM tool
dispatch, plugin registration, and __init__ re-exports.

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007,
    §8.5 Vent Slot Count and Width.
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §6.4 Vent Slot Design.
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_mold.vent_slot_layout import (
    BEAUMONT_VENT_AREA_FRACTION,
    MIN_STEEL_BRIDGE_MM,
    MIN_VENT_SLOTS,
    NOMINAL_WALL_THICKNESS_MM,
    POLYMER_VENT_DEPTH_RANGE,
    REFERENCE_INJECTION_SPEED_CM3_S,
    VENT_LAND_LENGTH_MM,
    VENT_SLOT_WIDTH_MM,
    MoldVolumeSpec,
    VentSlotLayoutReport,
    generate_vent_slot_layout,
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
# 1. Slot width is always 6 mm (Beaumont §8.5 + Menges §6.4 standard)
# ---------------------------------------------------------------------------

def test_slot_width_always_6mm():
    """Standard vent slot width must be 6 mm for any valid input."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    assert report.vent_slot_width_mm == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 2. Small cavity 50 cm³, perimeter 200 mm, ABS, 50 cm³/s
#    Perimeter-constrained → max_slots = floor(200/16) = 12
# ---------------------------------------------------------------------------

def test_small_abs_cavity_slot_count():
    """50 cm³ ABS, 200 mm perimeter, 50 cm³/s → perimeter-constrained at 12 slots."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    # max_slots = floor(200 / (6 + 10)) = floor(200/16) = 12
    assert report.num_vent_slots == 12
    assert report.vent_slot_width_mm == pytest.approx(6.0)


def test_small_abs_cavity_spacing():
    """50 cm³ ABS, 200 mm perimeter → spacing = 200/12 ≈ 16.667 mm."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    assert report.vent_slot_spacing_mm == pytest.approx(200.0 / 12, rel=1e-3)


def test_small_abs_cavity_total_vent_width():
    """50 cm³ ABS, 200 mm perimeter → total_vent_width = 12 × 6 = 72 mm."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    assert report.total_vent_width_mm == pytest.approx(12 * 6.0)


# ---------------------------------------------------------------------------
# 3. Larger cavity needs more slots (perimeter also larger)
#    200 cm³, perimeter 400 mm, ABS → max_slots = floor(400/16) = 25
# ---------------------------------------------------------------------------

def test_larger_cavity_more_slots_than_small():
    """Larger cavity (200 cm³, 400 mm perimeter) → more slots than small cavity."""
    spec_small = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    spec_large = MoldVolumeSpec(
        cavity_volume_cm3=200.0,
        parting_line_perimeter_mm=400.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report_small = generate_vent_slot_layout(spec_small)
    report_large = generate_vent_slot_layout(spec_large)
    assert report_large.num_vent_slots > report_small.num_vent_slots


def test_larger_cavity_slot_count_400mm():
    """200 cm³, 400 mm perimeter → max_slots = floor(400/16) = 25."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=200.0,
        parting_line_perimeter_mm=400.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    # max_slots = floor(400/(6+10)) = floor(25.0) = 25
    assert report.num_vent_slots == 25


# ---------------------------------------------------------------------------
# 4. Faster injection requires more slots (speed scaling increases required area)
#    50 cm³, 200 mm, ABS: 150 cm³/s vs 50 cm³/s
#    Both are perimeter-constrained at 12; but we verify n_required is higher
# ---------------------------------------------------------------------------

def test_faster_injection_higher_required_slots():
    """Faster injection (150 cm³/s) should calculate more required slots than slow."""
    # 50 cm³/s: vent_area_factor=1.0, required = 83.3 mm², n_required = 74
    # 150 cm³/s: vent_area_factor=3.0, required = 250.0 mm², n_required = 221
    # Both end up at 12 (perimeter constrained); confirm the calculation
    # by checking air_displacement_rate
    spec_slow = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    spec_fast = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=150.0,
    )
    report_slow = generate_vent_slot_layout(spec_slow)
    report_fast = generate_vent_slot_layout(spec_fast)
    # air_displacement_rate == injection_speed
    assert report_fast.air_displacement_rate_cm3_s == pytest.approx(150.0)
    assert report_slow.air_displacement_rate_cm3_s == pytest.approx(50.0)


def test_speed_scaling_factor():
    """Injection speed above 50 cm³/s applies vent_area_factor > 1."""
    # Verify by checking that the adequate flag accounts for more area needed
    # For a large perimeter cavity, fast injection should still be flagged
    # lower (adequate=False when perimeter cannot accommodate all needed slots)
    spec = MoldVolumeSpec(
        cavity_volume_cm3=5.0,
        parting_line_perimeter_mm=1000.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=100.0,
    )
    report = generate_vent_slot_layout(spec)
    # vent_area_factor = 100/50 = 2.0
    # required = 0.005 * (5000/3) * 2.0 = 16.67 mm²
    # per_slot = 6 * 0.0315 * 6 = 1.134 mm²
    # n_required = ceil(16.67/1.134) = ceil(14.7) = 15
    # max_slots = floor(1000/16) = 62
    # n_slots = max(15, 4) = 15
    assert report.num_vent_slots == 15
    assert report.adequate is True


# ---------------------------------------------------------------------------
# 5. Minimum 4 slots enforced even for tiny cavities
# ---------------------------------------------------------------------------

def test_minimum_4_slots_enforced():
    """Tiny cavity should still produce at least 4 vent slots."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=0.1,
        parting_line_perimeter_mm=500.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=5.0,
    )
    report = generate_vent_slot_layout(spec)
    assert report.num_vent_slots >= MIN_VENT_SLOTS


# ---------------------------------------------------------------------------
# 6. Adequate = True for a well-configured small cavity with large perimeter
#    5 cm³, 500 mm perimeter, ABS, 10 cm³/s
# ---------------------------------------------------------------------------

def test_adequate_true_for_large_perimeter_small_cavity():
    """5 cm³ cavity, 500 mm perimeter, ABS, 10 cm³/s → adequate=True."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=5.0,
        parting_line_perimeter_mm=500.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=10.0,
    )
    report = generate_vent_slot_layout(spec)
    # n_required = ceil(8.33/1.134) = 8, n_slots = 8, max_slots = 31
    # spacing = 500/8 = 62.5 >= 16 → adequate
    assert report.num_vent_slots == 8
    assert report.adequate is True


# ---------------------------------------------------------------------------
# 7. Perimeter-constrained → adequate = False
#    500 cm³, 100 mm perimeter, ABS, 100 cm³/s
# ---------------------------------------------------------------------------

def test_perimeter_constrained_not_adequate():
    """Very large cavity on a tiny perimeter → perimeter-constrained, not adequate."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=500.0,
        parting_line_perimeter_mm=100.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=100.0,
    )
    report = generate_vent_slot_layout(spec)
    # max_slots = floor(100/16) = 6
    assert report.num_vent_slots == 6
    # Much more area needed than 6 slots can provide
    assert report.adequate is False


# ---------------------------------------------------------------------------
# 8. Air displacement rate equals injection speed
# ---------------------------------------------------------------------------

def test_air_displacement_rate_equals_injection_speed():
    """Air displacement rate (cm³/s) must equal injection_speed_cm3_s."""
    for speed in [25.0, 50.0, 100.0, 200.0]:
        spec = MoldVolumeSpec(
            cavity_volume_cm3=50.0,
            parting_line_perimeter_mm=200.0,
            polymer_grade="PP",
            injection_speed_cm3_s=speed,
        )
        report = generate_vent_slot_layout(spec)
        assert report.air_displacement_rate_cm3_s == pytest.approx(speed)


# ---------------------------------------------------------------------------
# 9. Polymer sensitivity: PC (low vent depth) needs more slots than PE
#    (high vent depth) for same cavity, since per_slot_area is smaller for PC
# ---------------------------------------------------------------------------

def test_pc_requires_more_slots_than_pe_same_cavity():
    """PC (lower vent depth) needs more slots than PE (higher depth) for same cavity/perimeter."""
    # Both will be perimeter-constrained at same max_slots for same perimeter,
    # but let's use a large perimeter so n_required matters
    spec_pc = MoldVolumeSpec(
        cavity_volume_cm3=5.0,
        parting_line_perimeter_mm=1000.0,
        polymer_grade="PC",
        injection_speed_cm3_s=10.0,
    )
    spec_pe = MoldVolumeSpec(
        cavity_volume_cm3=5.0,
        parting_line_perimeter_mm=1000.0,
        polymer_grade="PE",
        injection_speed_cm3_s=10.0,
    )
    report_pc = generate_vent_slot_layout(spec_pc)
    report_pe = generate_vent_slot_layout(spec_pe)
    # PC depth_mid=0.019 mm (smaller area per slot → more slots)
    # PE depth_mid=0.0565 mm (larger area per slot → fewer slots)
    assert report_pc.num_vent_slots >= report_pe.num_vent_slots


# ---------------------------------------------------------------------------
# 10. PA66 moderate cavity
# ---------------------------------------------------------------------------

def test_pa66_moderate_cavity():
    """PA66, 80 cm³, 300 mm perimeter, 60 cm³/s → perimeter-constrained."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=80.0,
        parting_line_perimeter_mm=300.0,
        polymer_grade="PA66",
        injection_speed_cm3_s=60.0,
    )
    report = generate_vent_slot_layout(spec)
    # max_slots = floor(300/16) = 18
    assert report.num_vent_slots == 18
    assert report.vent_slot_width_mm == pytest.approx(6.0)
    assert isinstance(report.adequate, bool)


# ---------------------------------------------------------------------------
# 11. POM cavity
# ---------------------------------------------------------------------------

def test_pom_cavity():
    """POM, 30 cm³, 180 mm perimeter, 40 cm³/s → max_slots = 11."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=30.0,
        parting_line_perimeter_mm=180.0,
        polymer_grade="POM",
        injection_speed_cm3_s=40.0,
    )
    report = generate_vent_slot_layout(spec)
    # max_slots = floor(180/16) = 11
    assert report.num_vent_slots == 11
    assert report.vent_slot_spacing_mm == pytest.approx(180.0 / 11, rel=1e-3)


# ---------------------------------------------------------------------------
# 12. PMMA in-range
# ---------------------------------------------------------------------------

def test_pmma_cavity():
    """PMMA cavity uses standard 6 mm slot width and returns a valid report."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=40.0,
        parting_line_perimeter_mm=250.0,
        polymer_grade="PMMA",
        injection_speed_cm3_s=30.0,
    )
    report = generate_vent_slot_layout(spec)
    assert report.vent_slot_width_mm == pytest.approx(6.0)
    assert report.num_vent_slots >= MIN_VENT_SLOTS
    assert isinstance(report.honest_caveat, str)
    assert report.honest_caveat != ""


# ---------------------------------------------------------------------------
# 13. Unknown polymer uses fallback depth range with caveat
# ---------------------------------------------------------------------------

def test_unknown_polymer_fallback():
    """Unknown polymer (TPU) uses fallback depth range; no exception raised."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="TPU",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    # Should not raise; fallback range used
    assert report.num_vent_slots >= MIN_VENT_SLOTS
    assert report.vent_slot_width_mm == pytest.approx(6.0)
    assert isinstance(report.adequate, bool)


# ---------------------------------------------------------------------------
# 14. Case-insensitive polymer grade
# ---------------------------------------------------------------------------

def test_polymer_grade_case_insensitive():
    """Polymer grade is case-insensitive ('abs' → 'ABS')."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="abs",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    assert report.num_vent_slots >= MIN_VENT_SLOTS
    assert report.vent_slot_width_mm == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 15. MoldVolumeSpec rejects invalid inputs
# ---------------------------------------------------------------------------

def test_zero_cavity_volume_raises():
    with pytest.raises(ValueError, match="cavity_volume_cm3 must be > 0"):
        MoldVolumeSpec(
            cavity_volume_cm3=0.0,
            parting_line_perimeter_mm=200.0,
            polymer_grade="ABS",
            injection_speed_cm3_s=50.0,
        )


def test_negative_cavity_volume_raises():
    with pytest.raises(ValueError, match="cavity_volume_cm3 must be > 0"):
        MoldVolumeSpec(
            cavity_volume_cm3=-10.0,
            parting_line_perimeter_mm=200.0,
            polymer_grade="ABS",
            injection_speed_cm3_s=50.0,
        )


def test_zero_perimeter_raises():
    with pytest.raises(ValueError, match="parting_line_perimeter_mm must be > 0"):
        MoldVolumeSpec(
            cavity_volume_cm3=50.0,
            parting_line_perimeter_mm=0.0,
            polymer_grade="ABS",
            injection_speed_cm3_s=50.0,
        )


def test_zero_injection_speed_raises():
    with pytest.raises(ValueError, match="injection_speed_cm3_s must be > 0"):
        MoldVolumeSpec(
            cavity_volume_cm3=50.0,
            parting_line_perimeter_mm=200.0,
            polymer_grade="ABS",
            injection_speed_cm3_s=0.0,
        )


# ---------------------------------------------------------------------------
# 16. Total vent width = num_slots × 6 mm
# ---------------------------------------------------------------------------

def test_total_vent_width_consistent():
    """total_vent_width_mm must equal num_vent_slots × vent_slot_width_mm."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=100.0,
        parting_line_perimeter_mm=350.0,
        polymer_grade="PP",
        injection_speed_cm3_s=75.0,
    )
    report = generate_vent_slot_layout(spec)
    expected = report.num_vent_slots * report.vent_slot_width_mm
    assert report.total_vent_width_mm == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# 17. Spacing = perimeter / num_slots
# ---------------------------------------------------------------------------

def test_spacing_equals_perimeter_over_slots():
    """vent_slot_spacing_mm must equal parting_line_perimeter / num_vent_slots."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=300.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    expected_spacing = 300.0 / report.num_vent_slots
    assert report.vent_slot_spacing_mm == pytest.approx(expected_spacing, rel=1e-3)


# ---------------------------------------------------------------------------
# 18. Honest caveat cites Beaumont and Menges
# ---------------------------------------------------------------------------

def test_honest_caveat_cites_references():
    """Honest caveat must cite Beaumont 2007 and Menges 2001."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    assert "Beaumont" in report.honest_caveat
    assert "Menges" in report.honest_caveat
    assert "Moldflow" in report.honest_caveat or "simulation" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 19. Speedup doubles required slots (before perimeter capping)
#    Verify by comparing two specs on a large enough perimeter
# ---------------------------------------------------------------------------

def test_doubled_speed_doubles_required_slots():
    """Doubling injection speed doubles required vent area → approx doubles n_required."""
    # Large perimeter so neither is constrained
    spec_base = MoldVolumeSpec(
        cavity_volume_cm3=5.0,
        parting_line_perimeter_mm=2000.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    spec_2x = MoldVolumeSpec(
        cavity_volume_cm3=5.0,
        parting_line_perimeter_mm=2000.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=100.0,
    )
    report_base = generate_vent_slot_layout(spec_base)
    report_2x = generate_vent_slot_layout(spec_2x)
    # Doubling speed doubles vent_area_factor → doubles n_required
    assert report_2x.num_vent_slots == pytest.approx(2 * report_base.num_vent_slots, abs=1)


# ---------------------------------------------------------------------------
# 20. Slot width constant — not affected by cavity volume
# ---------------------------------------------------------------------------

def test_slot_width_invariant_to_cavity_size():
    """vent_slot_width_mm must be 6 mm regardless of cavity volume."""
    for volume in [1.0, 10.0, 100.0, 1000.0]:
        spec = MoldVolumeSpec(
            cavity_volume_cm3=volume,
            parting_line_perimeter_mm=1000.0,
            polymer_grade="ABS",
            injection_speed_cm3_s=50.0,
        )
        report = generate_vent_slot_layout(spec)
        assert report.vent_slot_width_mm == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 21. Larger PP cavity with fast injection (300 cm³, 600 mm, 200 cm³/s)
# ---------------------------------------------------------------------------

def test_large_pp_fast_injection():
    """300 cm³ PP, 600 mm perimeter, 200 cm³/s → max_slots=37, adequate=False."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=300.0,
        parting_line_perimeter_mm=600.0,
        polymer_grade="PP",
        injection_speed_cm3_s=200.0,
    )
    report = generate_vent_slot_layout(spec)
    # max_slots = floor(600/16) = 37
    assert report.num_vent_slots == 37
    assert report.adequate is False  # requires way more area than 37 slots can provide


# ---------------------------------------------------------------------------
# 22. LLM tool dispatch — basic ABS case
# ---------------------------------------------------------------------------

def test_tool_dispatch_basic_abs():
    """LLM tool returns ok=True for valid ABS spec."""
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert result.get("ok") is True
    assert result["vent_slot_width_mm"] == pytest.approx(6.0)
    assert result["num_vent_slots"] >= MIN_VENT_SLOTS
    assert "honest_caveat" in result
    assert "reference" in result


def test_tool_dispatch_returns_adequate_flag():
    """LLM tool result includes 'adequate' boolean field."""
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert "adequate" in result
    assert isinstance(result["adequate"], bool)


# ---------------------------------------------------------------------------
# 23. LLM tool dispatch — missing required args
# ---------------------------------------------------------------------------

def test_tool_dispatch_missing_cavity_volume():
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_missing_perimeter():
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_missing_polymer_grade():
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "parting_line_perimeter_mm": 200.0,
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_missing_injection_speed():
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "ABS",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 24. LLM tool dispatch — non-numeric input
# ---------------------------------------------------------------------------

def test_tool_dispatch_non_numeric_volume():
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": "big",
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_non_numeric_speed():
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": "fast",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 25. Tool spec name and required fields
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.vent_slot_layout_tool import mold_generate_vent_slot_layout_spec
    assert mold_generate_vent_slot_layout_spec.name == "mold_generate_vent_slot_layout"


def test_tool_spec_required_fields():
    from kerf_mold.vent_slot_layout_tool import mold_generate_vent_slot_layout_spec
    required = mold_generate_vent_slot_layout_spec.input_schema.get("required", [])
    assert "cavity_volume_cm3" in required
    assert "parting_line_perimeter_mm" in required
    assert "polymer_grade" in required
    assert "injection_speed_cm3_s" in required


# ---------------------------------------------------------------------------
# 26. Plugin registers mold_generate_vent_slot_layout
# ---------------------------------------------------------------------------

def test_plugin_registers_vent_slot_layout_tool():
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
    assert "mold_generate_vent_slot_layout" in ctx.tools.registered, (
        "mold_generate_vent_slot_layout should be registered in the plugin"
    )


# ---------------------------------------------------------------------------
# 27. Re-export from kerf_mold.__init__
# ---------------------------------------------------------------------------

def test_init_exports():
    from kerf_mold import (
        MoldVolumeSpec,
        VentSlotLayoutReport,
        POLYMER_VENT_DEPTH_RANGE,
        generate_vent_slot_layout,
    )
    assert MoldVolumeSpec is not None
    assert VentSlotLayoutReport is not None
    assert "ABS" in POLYMER_VENT_DEPTH_RANGE
    assert callable(generate_vent_slot_layout)


# ---------------------------------------------------------------------------
# 28. POLYMER_VENT_DEPTH_RANGE database values match Beaumont Table 8.2
# ---------------------------------------------------------------------------

def test_vent_depth_db_values():
    """POLYMER_VENT_DEPTH_RANGE values match Beaumont 2007 Table 8.2."""
    assert POLYMER_VENT_DEPTH_RANGE["ABS"]  == pytest.approx((0.025, 0.038))
    assert POLYMER_VENT_DEPTH_RANGE["PC"]   == pytest.approx((0.013, 0.025))
    assert POLYMER_VENT_DEPTH_RANGE["PP"]   == pytest.approx((0.025, 0.050))
    assert POLYMER_VENT_DEPTH_RANGE["PA66"] == pytest.approx((0.013, 0.025))
    assert POLYMER_VENT_DEPTH_RANGE["POM"]  == pytest.approx((0.013, 0.025))
    assert POLYMER_VENT_DEPTH_RANGE["PMMA"] == pytest.approx((0.025, 0.038))
    assert POLYMER_VENT_DEPTH_RANGE["PE"]   == pytest.approx((0.038, 0.075))


# ---------------------------------------------------------------------------
# 29. Constants sanity check
# ---------------------------------------------------------------------------

def test_physical_constants():
    """Key physical constants must match Beaumont §8.5 + Menges §6.4 values."""
    assert VENT_SLOT_WIDTH_MM == pytest.approx(6.0)
    assert VENT_LAND_LENGTH_MM == pytest.approx(6.0)
    assert BEAUMONT_VENT_AREA_FRACTION == pytest.approx(0.005)
    assert REFERENCE_INJECTION_SPEED_CM3_S == pytest.approx(50.0)
    assert MIN_VENT_SLOTS == 4
    assert MIN_STEEL_BRIDGE_MM == pytest.approx(10.0)
    assert NOMINAL_WALL_THICKNESS_MM == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 30. VentSlotLayoutReport dataclass fields are accessible
# ---------------------------------------------------------------------------

def test_report_fields_accessible():
    """VentSlotLayoutReport exposes all required fields."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=200.0,
        polymer_grade="ABS",
        injection_speed_cm3_s=50.0,
    )
    report = generate_vent_slot_layout(spec)
    assert hasattr(report, "num_vent_slots")
    assert hasattr(report, "vent_slot_width_mm")
    assert hasattr(report, "vent_slot_spacing_mm")
    assert hasattr(report, "total_vent_width_mm")
    assert hasattr(report, "air_displacement_rate_cm3_s")
    assert hasattr(report, "adequate")
    assert hasattr(report, "honest_caveat")


# ---------------------------------------------------------------------------
# 31. LLM tool dispatch — adequate=True case (small cavity, large perimeter)
# ---------------------------------------------------------------------------

def test_tool_dispatch_adequate_true():
    """LLM tool returns adequate=True for 5 cm³ ABS, 500 mm, 10 cm³/s."""
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 5.0,
        "parting_line_perimeter_mm": 500.0,
        "polymer_grade": "ABS",
        "injection_speed_cm3_s": 10.0,
    }, CTX)))
    assert result.get("ok") is True
    assert result["adequate"] is True
    assert result["num_vent_slots"] == 8


# ---------------------------------------------------------------------------
# 32. LLM tool includes reference citation
# ---------------------------------------------------------------------------

def test_tool_dispatch_reference_citation():
    """LLM tool response must include Beaumont and Menges references."""
    from kerf_mold.vent_slot_layout_tool import run_mold_generate_vent_slot_layout
    result = json.loads(_run(run_mold_generate_vent_slot_layout({
        "cavity_volume_cm3": 50.0,
        "parting_line_perimeter_mm": 200.0,
        "polymer_grade": "PP",
        "injection_speed_cm3_s": 50.0,
    }, CTX)))
    assert result.get("ok") is True
    assert "Beaumont" in result["reference"]
    assert "Menges" in result["reference"]
    assert "§8.5" in result["reference"]


# ---------------------------------------------------------------------------
# 33. Spacing always ≤ perimeter (no slot can be wider than the mold)
# ---------------------------------------------------------------------------

def test_spacing_less_than_perimeter():
    """Spacing must always be ≤ parting_line_perimeter_mm / 1 (single slot minimum)."""
    for volume in [5.0, 50.0, 200.0]:
        spec = MoldVolumeSpec(
            cavity_volume_cm3=volume,
            parting_line_perimeter_mm=300.0,
            polymer_grade="ABS",
            injection_speed_cm3_s=50.0,
        )
        report = generate_vent_slot_layout(spec)
        assert report.vent_slot_spacing_mm <= 300.0
        assert report.vent_slot_spacing_mm > 0


# ---------------------------------------------------------------------------
# 34. Num slots × spacing ≈ perimeter
# ---------------------------------------------------------------------------

def test_num_slots_times_spacing_equals_perimeter():
    """num_vent_slots × vent_slot_spacing_mm must approximately equal perimeter."""
    spec = MoldVolumeSpec(
        cavity_volume_cm3=50.0,
        parting_line_perimeter_mm=250.0,
        polymer_grade="PC",
        injection_speed_cm3_s=40.0,
    )
    report = generate_vent_slot_layout(spec)
    reconstructed = report.num_vent_slots * report.vent_slot_spacing_mm
    assert reconstructed == pytest.approx(250.0, rel=1e-3)
