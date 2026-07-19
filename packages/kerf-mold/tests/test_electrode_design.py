"""
Tests for kerf_mold.electrode_design
======================================
Covers EDM electrode geometry offset, burning time estimation, process parameter
recommendations, input validation, and LLM tool dispatch.

References:
  Hassan, A., Boothroyd, G. (1989). *Fundamentals of Machining and Machine Tools*,
    2nd ed., §14 Table 14.3–14.4.
  Kalpakjian, S., Schmid, S. (2014). §27.
  VDI 3402 (1976).
"""
import asyncio
import json
import math

import pytest

from kerf_mold.electrode_design import (
    EdmElectrodeSpec,
    EdmElectrodeReport,
    design_edm_electrode,
    FINISH_CLASS_MRR_MM3_PER_MIN,
    FINISH_CLASS_CURRENT_A,
    FINISH_CLASS_VOLTAGE_V,
    ELECTRODE_WEAR_RATIO,
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
# 1. Spark gap offset of exactly 0.05 mm for F2
# ---------------------------------------------------------------------------

def test_electrode_offset_f2_gap_0p05():
    """F2 finish, spark_gap=0.05 mm: offset geometry should record gap = 0.05 mm exactly."""
    spec = EdmElectrodeSpec(
        target_face_geometry=None,
        spark_gap_mm=0.05,
        finish_class="F2",
        cross_section_area_mm2_hint=100.0,
    )
    report = design_edm_electrode(spec)
    assert report.spark_gap_mm == pytest.approx(0.05)
    assert report.electrode_geometry["offset_mm"] == pytest.approx(0.05)


def test_electrode_geometry_offset_reduces_area():
    """Offset area must be less than original area for any gap > 0."""
    spec = EdmElectrodeSpec(
        spark_gap_mm=0.10,
        finish_class="F1",
        cross_section_area_mm2_hint=400.0,
    )
    report = design_edm_electrode(spec)
    assert report.electrode_geometry["offset_area_mm2"] < report.electrode_geometry["original_area_mm2"]


def test_electrode_area_matches_hint():
    """cross_section_area_mm2 in report should match the hint."""
    spec = EdmElectrodeSpec(cross_section_area_mm2_hint=625.0)
    report = design_edm_electrode(spec)
    assert report.cross_section_area_mm2 == pytest.approx(625.0)


# ---------------------------------------------------------------------------
# 2. Estimated burning time scales with cross-section area
# ---------------------------------------------------------------------------

def test_burning_time_scales_with_area():
    """Doubling the cross-section area should double the burning time."""
    spec1 = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=100.0)
    spec2 = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=200.0)
    r1 = design_edm_electrode(spec1)
    r2 = design_edm_electrode(spec2)
    assert r2.estimated_burning_time_min == pytest.approx(2.0 * r1.estimated_burning_time_min, rel=1e-6)


def test_burning_time_F0_less_than_F3():
    """F0 (high MRR) should have much less burning time than F3 (low MRR)."""
    area = 500.0
    spec_f0 = EdmElectrodeSpec(finish_class="F0", cross_section_area_mm2_hint=area)
    spec_f3 = EdmElectrodeSpec(finish_class="F3", cross_section_area_mm2_hint=area)
    r0 = design_edm_electrode(spec_f0)
    r3 = design_edm_electrode(spec_f3)
    assert r0.estimated_burning_time_min < r3.estimated_burning_time_min, (
        f"F0 time {r0.estimated_burning_time_min:.2f} should be < F3 {r3.estimated_burning_time_min:.2f}"
    )


def test_burning_time_consistent_with_mrr():
    """Burning time = volume / MRR; volume = area × 10 mm assumed depth."""
    area = 300.0
    finish_class = "F2"
    spec = EdmElectrodeSpec(finish_class=finish_class, cross_section_area_mm2_hint=area)
    report = design_edm_electrode(spec)
    mrr = FINISH_CLASS_MRR_MM3_PER_MIN[finish_class]
    expected_vol = area * 10.0  # assumed depth 10 mm
    expected_time = expected_vol / mrr
    assert report.estimated_burning_time_min == pytest.approx(expected_time, rel=1e-5)


# ---------------------------------------------------------------------------
# 3. Recommended current and voltage for each finish class
# ---------------------------------------------------------------------------

def test_recommended_current_f2():
    spec = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=100.0)
    report = design_edm_electrode(spec)
    assert report.recommended_current_a == pytest.approx(FINISH_CLASS_CURRENT_A["F2"])


def test_recommended_voltage_f2():
    spec = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=100.0)
    report = design_edm_electrode(spec)
    assert report.recommended_voltage_v == pytest.approx(FINISH_CLASS_VOLTAGE_V["F2"])


def test_current_decreases_from_f0_to_f3():
    """Current should decrease from rough (F0) to fine (F3)."""
    classes = ["F0", "F1", "F2", "F3"]
    currents = [FINISH_CLASS_CURRENT_A[c] for c in classes]
    for i in range(len(currents) - 1):
        assert currents[i] > currents[i + 1], (
            f"Current for {classes[i]} ({currents[i]} A) should exceed {classes[i+1]} ({currents[i+1]} A)"
        )


# ---------------------------------------------------------------------------
# 4. Electrode material wear ratio
# ---------------------------------------------------------------------------

def test_electrode_wear_ratio_poco_edm3():
    spec = EdmElectrodeSpec(
        material="graphite_POCO_EDM-3",
        cross_section_area_mm2_hint=100.0,
    )
    report = design_edm_electrode(spec)
    assert report.electrode_wear_ratio == pytest.approx(ELECTRODE_WEAR_RATIO["graphite_POCO_EDM-3"])


def test_graphite_lower_wear_than_copper():
    """POCO EDM-3 graphite should have lower wear ratio than copper."""
    assert ELECTRODE_WEAR_RATIO["graphite_POCO_EDM-3"] < ELECTRODE_WEAR_RATIO["copper"]


# ---------------------------------------------------------------------------
# 5. Finish class and gap in geometry dict
# ---------------------------------------------------------------------------

def test_electrode_geometry_dict_fields():
    spec = EdmElectrodeSpec(finish_class="F1", spark_gap_mm=0.10, cross_section_area_mm2_hint=200.0)
    report = design_edm_electrode(spec)
    geom = report.electrode_geometry
    assert geom["type"] == "offset_face"
    assert "original_area_mm2" in geom
    assert "offset_area_mm2" in geom
    assert "offset_mm" in geom
    assert geom["electrode_material"] == "graphite_POCO_EDM-3"
    assert geom["polarity"] == "positive"


# ---------------------------------------------------------------------------
# 6. Input validation
# ---------------------------------------------------------------------------

def test_invalid_finish_class_raises():
    with pytest.raises(ValueError, match="finish_class must be one of"):
        EdmElectrodeSpec(finish_class="F9", cross_section_area_mm2_hint=100.0)


def test_invalid_material_raises():
    with pytest.raises(ValueError, match="material must be one of"):
        EdmElectrodeSpec(material="titanium", cross_section_area_mm2_hint=100.0)


def test_negative_spark_gap_raises():
    with pytest.raises(ValueError, match="spark_gap_mm must be >= 0"):
        EdmElectrodeSpec(spark_gap_mm=-0.01, cross_section_area_mm2_hint=100.0)


def test_invalid_polarity_raises():
    with pytest.raises(ValueError, match="polarity must be"):
        EdmElectrodeSpec(polarity="neutral", cross_section_area_mm2_hint=100.0)


# ---------------------------------------------------------------------------
# 7. Honest caveat references Hassan-Boothroyd
# ---------------------------------------------------------------------------

def test_honest_caveat_references():
    spec = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=100.0)
    report = design_edm_electrode(spec)
    assert "HONEST" in report.honest_caveat
    assert "Hassan" in report.honest_caveat or "MRR" in report.honest_caveat


# ---------------------------------------------------------------------------
# 8. Cavity volume correct
# ---------------------------------------------------------------------------

def test_cavity_volume_correct():
    """cavity_volume_mm3 = area * 10 (assumed depth)."""
    spec = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=250.0)
    report = design_edm_electrode(spec)
    assert report.cavity_volume_mm3 == pytest.approx(250.0 * 10.0, rel=1e-5)


# ---------------------------------------------------------------------------
# 9. LLM tool dispatch
# ---------------------------------------------------------------------------

def test_tool_dispatch_basic():
    from kerf_mold.electrode_design_tool import run_mold_design_edm_electrode
    result = json.loads(_run(run_mold_design_edm_electrode({
        "cross_section_area_mm2": 200.0,
        "spark_gap_mm": 0.05,
        "finish_class": "F2",
    }, CTX)))
    assert result.get("ok") is True
    assert result["spark_gap_mm"] == pytest.approx(0.05)
    assert result["estimated_burning_time_min"] > 0
    assert "electrode_geometry" in result


def test_tool_dispatch_missing_area():
    from kerf_mold.electrode_design_tool import run_mold_design_edm_electrode
    result = json.loads(_run(run_mold_design_edm_electrode({
        "finish_class": "F2",
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_invalid_finish_class():
    from kerf_mold.electrode_design_tool import run_mold_design_edm_electrode
    result = json.loads(_run(run_mold_design_edm_electrode({
        "cross_section_area_mm2": 100.0,
        "finish_class": "F9",
    }, CTX)))
    assert "error" in result


# ---------------------------------------------------------------------------
# 10. Tool spec
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.electrode_design_tool import mold_design_edm_electrode_spec
    assert mold_design_edm_electrode_spec.name == "mold_design_edm_electrode"


def test_tool_spec_required_fields():
    from kerf_mold.electrode_design_tool import mold_design_edm_electrode_spec
    req = mold_design_edm_electrode_spec.input_schema.get("required", [])
    assert "cross_section_area_mm2" in req


# ---------------------------------------------------------------------------
# 11. Zero-area geometry falls back to zero cleanly
# ---------------------------------------------------------------------------

def test_zero_area_hint_gives_zero_burning_time():
    """Zero area → zero volume → zero burning time (no division by zero)."""
    spec = EdmElectrodeSpec(finish_class="F2", cross_section_area_mm2_hint=0.0)
    report = design_edm_electrode(spec)
    assert report.estimated_burning_time_min == pytest.approx(0.0)
    assert report.cross_section_area_mm2 == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 12. Dict geometry input (simulating B-rep face duck-type)
# ---------------------------------------------------------------------------

def test_dict_geometry_extracts_area():
    """If target_face_geometry is a dict with 'area_mm2', use that value."""
    spec = EdmElectrodeSpec(
        target_face_geometry={"area_mm2": 400.0, "type": "flat"},
        spark_gap_mm=0.05,
        finish_class="F2",
        cross_section_area_mm2_hint=0.0,  # should be overridden by dict
    )
    report = design_edm_electrode(spec)
    assert report.cross_section_area_mm2 == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# 13. F3 super-fine has smallest MRR
# ---------------------------------------------------------------------------

def test_f3_lowest_mrr():
    mrr_vals = list(FINISH_CLASS_MRR_MM3_PER_MIN.values())
    assert FINISH_CLASS_MRR_MM3_PER_MIN["F3"] == min(mrr_vals)


# ---------------------------------------------------------------------------
# 14. F0 rough has highest MRR
# ---------------------------------------------------------------------------

def test_f0_highest_mrr():
    mrr_vals = list(FINISH_CLASS_MRR_MM3_PER_MIN.values())
    assert FINISH_CLASS_MRR_MM3_PER_MIN["F0"] == max(mrr_vals)
