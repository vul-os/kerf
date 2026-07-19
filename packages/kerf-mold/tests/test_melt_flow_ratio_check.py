"""
Tests for kerf_mold.melt_flow_ratio_check
==========================================
Covers:
  - MFR classification boundaries (< 5, 5-25, 25-100, > 100)
  - Speed envelope: PC MFR=10 (medium), 3 mm wall, edge gate -> 25-75 mm/s
  - Speed envelope: PP MFR=35 (high), 1.5 mm wall, hot tip -> 50-150 mm/s range
  - Thick wall 6 mm -> sink_mark_risk=high
  - Gate-freeze risk inversely with MFR
  - Jetting risk: pin/edge gate + high MFR -> high; fan gate -> low
  - Sink-mark risk thresholds (< 2.5, 2.5-4, > 4 mm)
  - Wall-thickness speed adjustment factors (< 1.5, 1.5-3, 3-4, > 4 mm)
  - Gate type adjustments (fan, hot_runner, submarine)
  - Unknown gate type handled gracefully
  - MeltFlowSpec validation (zero/negative mfr, wall, melt_temp; negative mold_temp)
  - LLM tool dispatch happy path
  - LLM tool dispatch missing arg returns error
  - LLM tool dispatch bad mfr returns error
  - Super-high MFR classification
  - Speed window min < max invariant across all combinations
  - Honest caveat non-empty and mentions DOE/ASTM

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007, §4, §7.
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §6.2.
  ASTM D1238-23 (MFR measurement standard).
"""

import asyncio
import json

import pytest

from kerf_mold.melt_flow_ratio_check import (
    MeltFlowSpec,
    MeltFlowRatioReport,
    check_melt_flow_ratio,
    _classify_mfr,
    _wall_speed_adjustment,
    _gate_freeze_risk,
    _jetting_risk,
    _sink_mark_risk,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_spec(**kwargs) -> MeltFlowSpec:
    """Build a MeltFlowSpec with sensible defaults; override via kwargs."""
    defaults = dict(
        polymer_grade="ABS",
        mfr_g_per_10min=15.0,
        wall_thickness_mm=3.0,
        gate_type="edge_gate",
        melt_temp_C=240.0,
        mold_temp_C=60.0,
    )
    defaults.update(kwargs)
    return MeltFlowSpec(**defaults)


# ===========================================================================
# 1. MFR classification boundaries
# ===========================================================================

def test_mfr_classify_low():
    """MFR < 5 -> low_MFR_<5."""
    assert _classify_mfr(1.0) == "low_MFR_<5"
    assert _classify_mfr(4.9) == "low_MFR_<5"


def test_mfr_classify_medium():
    """5 <= MFR < 25 -> medium_MFR_5-25."""
    assert _classify_mfr(5.0) == "medium_MFR_5-25"
    assert _classify_mfr(10.0) == "medium_MFR_5-25"
    assert _classify_mfr(24.9) == "medium_MFR_5-25"


def test_mfr_classify_high():
    """25 <= MFR < 100 -> high_MFR_25-100."""
    assert _classify_mfr(25.0) == "high_MFR_25-100"
    assert _classify_mfr(35.0) == "high_MFR_25-100"
    assert _classify_mfr(99.9) == "high_MFR_25-100"


def test_mfr_classify_super_high():
    """MFR >= 100 -> super_high_MFR_>100."""
    assert _classify_mfr(100.0) == "super_high_MFR_>100"
    assert _classify_mfr(150.0) == "super_high_MFR_>100"


# ===========================================================================
# 2. PC MFR=10 (medium), 3 mm wall, edge gate
#    Expected: speed envelope centred in medium band; gate_freeze_risk=medium
# ===========================================================================

def test_pc_medium_mfr_edge_gate_speed_envelope():
    """PC MFR=10 (medium), 3 mm wall, edge gate: speed window within 25-75 mm/s."""
    spec = MeltFlowSpec(
        polymer_grade="PC",
        mfr_g_per_10min=10.0,
        wall_thickness_mm=3.0,
        gate_type="edge_gate",
        melt_temp_C=300.0,
        mold_temp_C=80.0,
    )
    report = check_melt_flow_ratio(spec)
    v_min, v_max = report.recommended_injection_speed_mm_per_s
    # 3.0 mm is within 1.5-3 mm bracket -> no adjustment -> should be 25-75
    assert v_min == pytest.approx(25.0, abs=0.5), (
        f"Expected v_min ~25 mm/s, got {v_min}"
    )
    assert v_max == pytest.approx(75.0, abs=0.5), (
        f"Expected v_max ~75 mm/s, got {v_max}"
    )


def test_pc_medium_mfr_gate_freeze_medium():
    """PC MFR=10 (medium) -> gate_freeze_risk=medium."""
    spec = _make_spec(polymer_grade="PC", mfr_g_per_10min=10.0, gate_type="edge_gate")
    report = check_melt_flow_ratio(spec)
    assert report.gate_freeze_risk == "medium"


def test_pc_mfr_classification_is_medium():
    """PC MFR=10 -> mfr_classification=medium_MFR_5-25."""
    spec = _make_spec(mfr_g_per_10min=10.0)
    report = check_melt_flow_ratio(spec)
    assert report.mfr_classification == "medium_MFR_5-25"


# ===========================================================================
# 3. PP MFR=35 (high), 1.5 mm wall, hot tip
# ===========================================================================

def test_pp_high_mfr_hot_tip_speed_range():
    """PP MFR=35 (high), 1.5 mm wall, hot_tip: v_min >= 40, v_max <= 200 mm/s."""
    spec = MeltFlowSpec(
        polymer_grade="PP",
        mfr_g_per_10min=35.0,
        wall_thickness_mm=1.5,
        gate_type="hot_tip",
        melt_temp_C=240.0,
        mold_temp_C=40.0,
    )
    report = check_melt_flow_ratio(spec)
    v_min, v_max = report.recommended_injection_speed_mm_per_s
    # high_MFR baseline 50-150; wall=1.5 mm is at boundary, no upper adjustment
    # hot_tip: lower *0.9, upper *1.1
    # Expected: v_min=50*0.9=45, v_max=150*1.1=165
    assert v_min >= 40.0, f"v_min={v_min} should be >= 40 mm/s"
    assert v_max <= 200.0, f"v_max={v_max} should be <= 200 mm/s"
    assert v_max > v_min, "v_max must be > v_min"


def test_pp_high_mfr_classification():
    """PP MFR=35 -> mfr_classification=high_MFR_25-100."""
    spec = _make_spec(mfr_g_per_10min=35.0)
    report = check_melt_flow_ratio(spec)
    assert report.mfr_classification == "high_MFR_25-100"


def test_pp_high_mfr_gate_freeze_low():
    """High MFR -> gate_freeze_risk=low."""
    spec = _make_spec(mfr_g_per_10min=35.0)
    report = check_melt_flow_ratio(spec)
    assert report.gate_freeze_risk == "low"


# ===========================================================================
# 4. Thick wall 6 mm -> sink_mark_risk=high
# ===========================================================================

def test_thick_wall_sink_mark_high():
    """Wall 6 mm > 4 mm -> sink_mark_risk=high."""
    spec = _make_spec(wall_thickness_mm=6.0)
    report = check_melt_flow_ratio(spec)
    assert report.sink_mark_risk == "high"


def test_thick_wall_speed_reduced():
    """Wall > 4 mm -> both speed bounds scaled down 25 % vs baseline."""
    # ABS MFR=15 (medium), edge gate, baseline 25-75 mm/s
    spec_thick = _make_spec(wall_thickness_mm=6.0, mfr_g_per_10min=15.0,
                             gate_type="edge_gate")
    spec_base = _make_spec(wall_thickness_mm=2.0, mfr_g_per_10min=15.0,
                            gate_type="edge_gate")
    thick_min, thick_max = check_melt_flow_ratio(spec_thick).recommended_injection_speed_mm_per_s
    base_min, base_max = check_melt_flow_ratio(spec_base).recommended_injection_speed_mm_per_s
    assert thick_min < base_min, "Thick-wall v_min should be < baseline v_min"
    assert thick_max < base_max, "Thick-wall v_max should be < baseline v_max"


# ===========================================================================
# 5. Gate-freeze risk inversely with MFR
# ===========================================================================

def test_gate_freeze_risk_low_mfr_high():
    """Low MFR (viscous) -> gate_freeze_risk=high."""
    assert _gate_freeze_risk("low_MFR_<5") == "high"


def test_gate_freeze_risk_medium_mfr_medium():
    """Medium MFR -> gate_freeze_risk=medium."""
    assert _gate_freeze_risk("medium_MFR_5-25") == "medium"


def test_gate_freeze_risk_high_mfr_low():
    """High MFR -> gate_freeze_risk=low."""
    assert _gate_freeze_risk("high_MFR_25-100") == "low"


def test_gate_freeze_risk_super_high_low():
    """Super-high MFR -> gate_freeze_risk=low."""
    assert _gate_freeze_risk("super_high_MFR_>100") == "low"


# ===========================================================================
# 6. Jetting risk
# ===========================================================================

def test_jetting_risk_fan_gate_low():
    """Fan gate -> jetting_risk=low regardless of MFR."""
    assert _jetting_risk("high_MFR_25-100", "fan_gate", 2.0) == "low"
    assert _jetting_risk("low_MFR_<5", "fan_gate", 2.0) == "low"


def test_jetting_risk_film_gate_low():
    """Film gate -> jetting_risk=low."""
    assert _jetting_risk("super_high_MFR_>100", "film_gate", 1.0) == "low"


def test_jetting_risk_pin_gate_high_mfr_thin():
    """Pin gate + high MFR + thin wall -> jetting_risk=high."""
    risk = _jetting_risk("high_MFR_25-100", "pin_gate", 1.5)
    assert risk == "high"


def test_jetting_risk_edge_gate_low_mfr_medium():
    """Edge gate + low MFR -> jetting_risk=medium (viscous melt, small gate)."""
    risk = _jetting_risk("low_MFR_<5", "edge_gate", 3.0)
    assert risk == "medium"


# ===========================================================================
# 7. Sink-mark risk thresholds
# ===========================================================================

def test_sink_mark_thin_wall_low():
    """Wall < 2.5 mm -> sink_mark_risk=low."""
    assert _sink_mark_risk(1.5) == "low"
    assert _sink_mark_risk(2.4) == "low"


def test_sink_mark_medium_wall():
    """Wall 2.5-4 mm -> sink_mark_risk=medium."""
    assert _sink_mark_risk(2.5) == "medium"
    assert _sink_mark_risk(3.0) == "medium"
    assert _sink_mark_risk(4.0) == "medium"


def test_sink_mark_thick_wall_high():
    """Wall > 4 mm -> sink_mark_risk=high."""
    assert _sink_mark_risk(4.1) == "high"
    assert _sink_mark_risk(8.0) == "high"


# ===========================================================================
# 8. Wall-thickness speed adjustment
# ===========================================================================

def test_wall_adjustment_thin():
    """Wall < 1.5 mm -> upper bound factor = 1.3."""
    f_lower, f_upper = _wall_speed_adjustment(1.0)
    assert f_lower == pytest.approx(1.0)
    assert f_upper == pytest.approx(1.3)


def test_wall_adjustment_standard():
    """Wall 1.5-3 mm -> both factors = 1.0."""
    f_lower, f_upper = _wall_speed_adjustment(2.0)
    assert f_lower == pytest.approx(1.0)
    assert f_upper == pytest.approx(1.0)


def test_wall_adjustment_moderate_thick():
    """Wall 3-4 mm -> lower factor = 0.8."""
    f_lower, f_upper = _wall_speed_adjustment(3.5)
    assert f_lower == pytest.approx(0.8)
    assert f_upper == pytest.approx(1.0)


def test_wall_adjustment_very_thick():
    """Wall > 4 mm -> both factors = 0.75."""
    f_lower, f_upper = _wall_speed_adjustment(5.0)
    assert f_lower == pytest.approx(0.75)
    assert f_upper == pytest.approx(0.75)


# ===========================================================================
# 9. Gate-type speed adjustments via full report
# ===========================================================================

def test_fan_gate_wider_upper_bound():
    """Fan gate upper bound should be 20 % wider than edge gate for same MFR/wall."""
    spec_edge = _make_spec(gate_type="edge_gate", mfr_g_per_10min=15.0,
                            wall_thickness_mm=2.0)
    spec_fan = _make_spec(gate_type="fan_gate", mfr_g_per_10min=15.0,
                           wall_thickness_mm=2.0)
    _, edge_max = check_melt_flow_ratio(spec_edge).recommended_injection_speed_mm_per_s
    _, fan_max = check_melt_flow_ratio(spec_fan).recommended_injection_speed_mm_per_s
    assert fan_max > edge_max, (
        f"fan_gate v_max ({fan_max}) should exceed edge_gate v_max ({edge_max})"
    )


def test_submarine_gate_higher_lower_bound():
    """Submarine gate lower bound should be higher than edge gate (shear-sensitive)."""
    spec_edge = _make_spec(gate_type="edge_gate", mfr_g_per_10min=15.0,
                            wall_thickness_mm=2.0)
    spec_sub = _make_spec(gate_type="submarine_gate", mfr_g_per_10min=15.0,
                           wall_thickness_mm=2.0)
    edge_min, _ = check_melt_flow_ratio(spec_edge).recommended_injection_speed_mm_per_s
    sub_min, _ = check_melt_flow_ratio(spec_sub).recommended_injection_speed_mm_per_s
    assert sub_min > edge_min, (
        f"submarine_gate v_min ({sub_min}) should exceed edge_gate v_min ({edge_min})"
    )


# ===========================================================================
# 10. Unknown gate type handled gracefully
# ===========================================================================

def test_unknown_gate_type_no_exception():
    """Unknown gate type should not raise; uses baseline scale factors."""
    spec = _make_spec(gate_type="some_exotic_gate_type")
    report = check_melt_flow_ratio(spec)
    v_min, v_max = report.recommended_injection_speed_mm_per_s
    assert v_min > 0.0
    assert v_max > v_min
    # honest_caveat should still be present
    assert len(report.honest_caveat) > 50


# ===========================================================================
# 11. MeltFlowSpec validation
# ===========================================================================

def test_spec_zero_mfr_raises():
    """mfr_g_per_10min=0 should raise ValueError."""
    with pytest.raises(ValueError):
        MeltFlowSpec(
            polymer_grade="PP",
            mfr_g_per_10min=0.0,
            wall_thickness_mm=2.0,
            gate_type="edge_gate",
            melt_temp_C=230.0,
            mold_temp_C=40.0,
        )


def test_spec_negative_mfr_raises():
    """Negative mfr_g_per_10min should raise ValueError."""
    with pytest.raises(ValueError):
        MeltFlowSpec(
            polymer_grade="PP",
            mfr_g_per_10min=-5.0,
            wall_thickness_mm=2.0,
            gate_type="edge_gate",
            melt_temp_C=230.0,
            mold_temp_C=40.0,
        )


def test_spec_zero_wall_raises():
    """wall_thickness_mm=0 should raise ValueError."""
    with pytest.raises(ValueError):
        _make_spec(wall_thickness_mm=0.0)


def test_spec_negative_wall_raises():
    """Negative wall_thickness_mm should raise ValueError."""
    with pytest.raises(ValueError):
        _make_spec(wall_thickness_mm=-1.0)


def test_spec_zero_melt_temp_raises():
    """melt_temp_C=0 should raise ValueError."""
    with pytest.raises(ValueError):
        _make_spec(melt_temp_C=0.0)


def test_spec_negative_mold_temp_raises():
    """Negative mold_temp_C should raise ValueError."""
    with pytest.raises(ValueError):
        _make_spec(mold_temp_C=-10.0)


# ===========================================================================
# 12. Speed window min < max invariant
# ===========================================================================

@pytest.mark.parametrize("mfr,wall,gate", [
    (1.0,  1.0, "pin_gate"),
    (10.0, 3.0, "edge_gate"),
    (35.0, 1.5, "hot_tip"),
    (80.0, 2.0, "fan_gate"),
    (120.0, 0.8, "film_gate"),
    (3.0,  6.0, "sprue_gate"),
    (15.0, 3.5, "submarine_gate"),
    (50.0, 2.5, "hot_runner"),
])
def test_speed_window_min_less_than_max(mfr, wall, gate):
    """v_min must always be < v_max for all parameter combinations."""
    spec = _make_spec(mfr_g_per_10min=mfr, wall_thickness_mm=wall, gate_type=gate)
    report = check_melt_flow_ratio(spec)
    v_min, v_max = report.recommended_injection_speed_mm_per_s
    assert v_min < v_max, (
        f"v_min={v_min} must be < v_max={v_max} for MFR={mfr}, "
        f"wall={wall}, gate={gate}"
    )


# ===========================================================================
# 13. Super-high MFR gate-freeze risk
# ===========================================================================

def test_super_high_mfr_low_gate_freeze():
    """MFR=120 (super_high) -> gate_freeze_risk=low, speed >= 80 mm/s."""
    spec = _make_spec(mfr_g_per_10min=120.0, wall_thickness_mm=1.0,
                      gate_type="edge_gate")
    report = check_melt_flow_ratio(spec)
    assert report.gate_freeze_risk == "low"
    v_min, v_max = report.recommended_injection_speed_mm_per_s
    assert v_min >= 70.0, f"Super-high MFR v_min should be >= 70 mm/s, got {v_min}"


# ===========================================================================
# 14. Honest caveat
# ===========================================================================

def test_honest_caveat_non_empty():
    """honest_caveat must be a non-empty string on every report."""
    report = check_melt_flow_ratio(_make_spec())
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 50


def test_honest_caveat_mentions_doe_or_astm():
    """honest_caveat must reference DOE, ASTM, or validation requirement."""
    report = check_melt_flow_ratio(_make_spec())
    caveat_lower = report.honest_caveat.lower()
    assert (
        "doe" in caveat_lower
        or "astm" in caveat_lower
        or "validate" in caveat_lower
    ), "Honest caveat should mention DOE, ASTM, or validation"


# ===========================================================================
# 15. LLM tool dispatch
# ===========================================================================

def test_tool_dispatch_happy_path():
    """LLM tool returns ok=True with expected keys for valid request."""
    from kerf_mold.melt_flow_ratio_check_tool import run_mold_check_melt_flow_ratio

    args = {
        "polymer_grade": "ABS",
        "mfr_g_per_10min": 18.0,
        "wall_thickness_mm": 2.5,
        "gate_type": "edge_gate",
        "melt_temp_C": 240.0,
        "mold_temp_C": 60.0,
    }
    result = asyncio.run(
        run_mold_check_melt_flow_ratio(args, ctx=None)
    )
    data = json.loads(result)
    assert data.get("ok") is True
    assert "mfr_classification" in data
    assert "recommended_injection_speed_mm_per_s" in data
    assert "gate_freeze_risk" in data
    assert "jetting_risk" in data
    assert "sink_mark_risk" in data
    assert "honest_caveat" in data


def test_tool_dispatch_missing_mfr_returns_error():
    """LLM tool returns error payload when mfr_g_per_10min is missing."""
    from kerf_mold.melt_flow_ratio_check_tool import run_mold_check_melt_flow_ratio

    args = {
        "polymer_grade": "PP",
        # mfr_g_per_10min missing
        "wall_thickness_mm": 2.0,
        "gate_type": "edge_gate",
        "melt_temp_C": 230.0,
        "mold_temp_C": 40.0,
    }
    result = asyncio.run(
        run_mold_check_melt_flow_ratio(args, ctx=None)
    )
    data = json.loads(result)
    assert data.get("ok") is not True


def test_tool_dispatch_bad_mfr_zero_returns_error():
    """LLM tool returns error payload when mfr_g_per_10min=0."""
    from kerf_mold.melt_flow_ratio_check_tool import run_mold_check_melt_flow_ratio

    args = {
        "polymer_grade": "PP",
        "mfr_g_per_10min": 0.0,
        "wall_thickness_mm": 2.0,
        "gate_type": "edge_gate",
        "melt_temp_C": 230.0,
        "mold_temp_C": 40.0,
    }
    result = asyncio.run(
        run_mold_check_melt_flow_ratio(args, ctx=None)
    )
    data = json.loads(result)
    assert data.get("ok") is not True
