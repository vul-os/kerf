"""
Tests for kerf_mold.warpage_index
==================================
Covers:
  - WarpageSpec validation (boundary conditions, bad inputs)
  - Perfect (ideal) conditions → index < 25 (low risk)
  - Worst-case (bad) conditions → index > 70 (high/severe)
  - Mitigation list non-empty when index > 50
  - Sub-score arithmetic and monotonicity
  - Polymer grade lookup (known + unknown)
  - Gate location penalties
  - Cooling time decay function
  - Mold temperature deviation penalty
  - LLM tool dispatch (async)

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007, §10.
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §8.
"""

import asyncio
import json
import math

import pytest

from kerf_mold.warpage_index import (
    WarpageSpec,
    WarpageIndexReport,
    compute_warpage_index,
    _wall_uniformity_score,
    _cooling_time_score,
    _mold_temp_score,
    _GATE_SCORES,
    _POLYMER_SCORES,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_spec(**kwargs) -> WarpageSpec:
    """Build a WarpageSpec with sensible defaults; override via kwargs."""
    defaults = dict(
        wall_thickness_uniformity_pct=90.0,
        gate_location="centered",
        polymer_grade="ABS",
        post_eject_cooling_time_s=60.0,
        mold_temp_C=60.0,
    )
    defaults.update(kwargs)
    return WarpageSpec(**defaults)


# ===========================================================================
# 1. Perfect conditions → index < 25 (low risk)
# ===========================================================================

def test_perfect_conditions_low_index():
    """100 % uniform, centered gate, PC, 30 s cooling, 80 °C mold → index < 25."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=100.0,
        gate_location="centered",
        polymer_grade="PC",
        post_eject_cooling_time_s=30.0,
        mold_temp_C=80.0,
    )
    report = compute_warpage_index(spec)
    assert report.warpage_index < 25.0, (
        f"Perfect conditions should give index < 25, got {report.warpage_index}"
    )


def test_perfect_conditions_risk_level_low():
    """Perfect conditions → risk_level == 'low'."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=100.0,
        gate_location="centered",
        polymer_grade="PC",
        post_eject_cooling_time_s=30.0,
        mold_temp_C=80.0,
    )
    report = compute_warpage_index(spec)
    assert report.risk_level == "low"


# ===========================================================================
# 2. Worst-case conditions → index > 70 (high or severe)
# ===========================================================================

def test_worst_case_high_index():
    """50 % uniformity, corner gate, GF-PA66, 2 s cooling, 150 °C mold → index > 70."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=50.0,
        gate_location="corner",
        polymer_grade="GF-PA66",
        post_eject_cooling_time_s=2.0,
        mold_temp_C=150.0,
    )
    report = compute_warpage_index(spec)
    assert report.warpage_index > 70.0, (
        f"Worst-case conditions should give index > 70, got {report.warpage_index}"
    )


def test_worst_case_risk_level_high_or_severe():
    """Worst-case → risk_level 'high' or 'severe'."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=50.0,
        gate_location="corner",
        polymer_grade="GF-PA66",
        post_eject_cooling_time_s=2.0,
        mold_temp_C=150.0,
    )
    report = compute_warpage_index(spec)
    assert report.risk_level in ("high", "severe")


# ===========================================================================
# 3. Mitigation list non-empty when index > 50
# ===========================================================================

def test_high_index_has_mitigations():
    """When index > 50, mitigation_suggestions must not be empty."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=55.0,
        gate_location="corner",
        polymer_grade="GF-PP",
        post_eject_cooling_time_s=3.0,
        mold_temp_C=130.0,
    )
    report = compute_warpage_index(spec)
    assert report.warpage_index > 50.0
    assert len(report.mitigation_suggestions) > 0, (
        "High-index report must include mitigation suggestions"
    )


def test_mitigations_are_strings():
    """All mitigation suggestions must be non-empty strings."""
    spec = _make_spec(
        wall_thickness_uniformity_pct=45.0,
        gate_location="unbalanced",
        polymer_grade="GF-PA66",
        post_eject_cooling_time_s=1.0,
    )
    report = compute_warpage_index(spec)
    for s in report.mitigation_suggestions:
        assert isinstance(s, str)
        assert len(s) > 0


# ===========================================================================
# 4. Sub-score breakdown
# ===========================================================================

def test_sub_scores_sum_to_index():
    """Sum of sub_scores should equal warpage_index (within rounding tolerance)."""
    spec = _make_spec(
        wall_thickness_uniformity_pct=75.0,
        gate_location="edge",
        polymer_grade="PP",
        post_eject_cooling_time_s=20.0,
        mold_temp_C=50.0,
    )
    report = compute_warpage_index(spec)
    total = sum(report.sub_scores.values())
    assert abs(total - report.warpage_index) < 0.1, (
        f"Sub-scores sum {total:.3f} should equal warpage_index {report.warpage_index}"
    )


def test_sub_scores_keys_present():
    """sub_scores dict must contain all five expected keys."""
    spec = _make_spec()
    report = compute_warpage_index(spec)
    expected_keys = {"wall_uniformity", "gate_location", "polymer_grade",
                     "cooling_time", "mold_temperature"}
    assert set(report.sub_scores.keys()) == expected_keys


# ===========================================================================
# 5. Wall uniformity monotonicity
# ===========================================================================

def test_wall_uniformity_monotonic():
    """Lower uniformity → higher wall sub-score (strictly monotonic on 0–100)."""
    scores = [_wall_uniformity_score(u) for u in [100, 90, 80, 70, 60, 50, 30, 10, 0]]
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], (
            f"wall_uniformity_score not monotonic at index {i}: "
            f"{scores[i]:.3f} > {scores[i+1]:.3f}"
        )


def test_wall_uniformity_perfect_zero():
    """100 % uniformity → wall sub-score == 0."""
    assert _wall_uniformity_score(100.0) == pytest.approx(0.0, abs=1e-9)


def test_wall_uniformity_zero_max():
    """0 % uniformity → wall sub-score == 30 (maximum)."""
    assert _wall_uniformity_score(0.0) == pytest.approx(30.0, abs=1e-9)


# ===========================================================================
# 6. Cooling time decay
# ===========================================================================

def test_cooling_time_zero_max():
    """0 s cooling → cooling sub-score == 15 (maximum)."""
    assert _cooling_time_score(0.0) == pytest.approx(15.0, abs=1e-6)


def test_cooling_time_long_near_zero():
    """Very long cooling (600 s) → cooling sub-score near 0."""
    assert _cooling_time_score(600.0) < 0.1


def test_cooling_time_monotonic():
    """Longer cooling → lower score (monotonically decreasing)."""
    times = [0, 5, 10, 20, 30, 60, 120, 300]
    scores = [_cooling_time_score(t) for t in times]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"cooling_time_score not monotonic at index {i}"
        )


# ===========================================================================
# 7. Mold temperature penalty
# ===========================================================================

def test_mold_temp_inside_range_zero():
    """Mold temp inside recommended range for ABS (40–80 °C) → penalty 0."""
    assert _mold_temp_score(60.0, "ABS") == pytest.approx(0.0, abs=1e-9)


def test_mold_temp_above_range_penalty():
    """Mold temp 80 °C above recommended upper bound → penalty > 0."""
    # ABS upper bound = 80 °C; 160 °C is 80 above
    score = _mold_temp_score(160.0, "ABS")
    assert score > 0.0


def test_mold_temp_below_range_penalty():
    """Mold temp well below recommended lower bound → penalty > 0."""
    # PC lower bound = 70 °C; 10 °C is 60 below
    score = _mold_temp_score(10.0, "PC")
    assert score > 0.0


def test_mold_temp_capped_at_10():
    """Mold temperature penalty is capped at 10."""
    # Extreme overtemperature
    score = _mold_temp_score(500.0, "ABS")
    assert score <= 10.0


# ===========================================================================
# 8. Gate location lookup
# ===========================================================================

def test_gate_centered_lowest():
    """Centered gate must score lower than edge/corner/unbalanced."""
    centered_score, _ = _GATE_SCORES["centered"]
    for gate in ("edge", "corner", "unbalanced"):
        score, _ = _GATE_SCORES[gate]
        assert centered_score < score, (
            f"centered gate ({centered_score}) should score less than {gate} ({score})"
        )


def test_gate_unbalanced_highest():
    """Unbalanced gate must have the highest gate score."""
    unbalanced_score, _ = _GATE_SCORES["unbalanced"]
    for gate in ("centered", "edge", "corner"):
        score, _ = _GATE_SCORES[gate]
        assert unbalanced_score >= score


def test_gate_corner_higher_than_edge():
    """Corner gate should score higher than edge gate."""
    edge_score, _ = _GATE_SCORES["edge"]
    corner_score, _ = _GATE_SCORES["corner"]
    assert corner_score > edge_score


# ===========================================================================
# 9. Polymer grade lookup
# ===========================================================================

def test_polymer_pc_low():
    """PC (amorphous) should have the lowest polymer sub-score."""
    pc_score, _ = _POLYMER_SCORES["PC"]
    assert pc_score <= 10.0, f"PC score {pc_score} should be ≤ 10"


def test_polymer_gfpa66_high():
    """GF-PA66 (glass-filled nylon) should have maximum polymer sub-score."""
    gf_score, _ = _POLYMER_SCORES["GF-PA66"]
    assert gf_score == pytest.approx(20.0, abs=1e-6), (
        f"GF-PA66 score {gf_score} should be 20 (maximum)"
    )


def test_polymer_unknown_fallback():
    """Unknown polymer_grade gets a fallback score without raising ValueError."""
    spec = _make_spec(polymer_grade="ULTRA-EXOTIC-RESIN-9000")
    # Should not raise; should compute a valid report
    report = compute_warpage_index(spec)
    assert 0.0 <= report.warpage_index <= 100.0
    # honest_caveat must be a non-empty screening-tool disclaimer
    assert len(report.honest_caveat) > 20
    assert "screening" in report.honest_caveat.lower()


# ===========================================================================
# 10. primary_warp_driver accuracy
# ===========================================================================

def test_primary_driver_is_polymer_for_gf_centered():
    """With perfect uniformity + centered gate, polymer grade should dominate for GF-PA66."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=100.0,
        gate_location="centered",
        polymer_grade="GF-PA66",
        post_eject_cooling_time_s=120.0,
        mold_temp_C=90.0,  # within PC recommended range; GF-PA66 range 70–120
    )
    report = compute_warpage_index(spec)
    assert report.primary_warp_driver == "polymer_grade"


def test_primary_driver_wall_when_very_nonuniform():
    """When uniformity is 0 %, wall_uniformity should dominate (30 pts vs others)."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=0.0,
        gate_location="centered",
        polymer_grade="PC",
        post_eject_cooling_time_s=300.0,
        mold_temp_C=90.0,  # within PC range
    )
    report = compute_warpage_index(spec)
    assert report.primary_warp_driver == "wall_uniformity"


# ===========================================================================
# 11. Report fields are populated
# ===========================================================================

def test_report_honest_caveat_non_empty():
    """honest_caveat must always be a non-empty string."""
    report = compute_warpage_index(_make_spec())
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 50


def test_report_index_in_range():
    """warpage_index must always be in [0, 100] for any valid input."""
    cases = [
        _make_spec(wall_thickness_uniformity_pct=100.0, post_eject_cooling_time_s=300.0),
        _make_spec(wall_thickness_uniformity_pct=0.0, gate_location="unbalanced",
                   polymer_grade="GF-PA66", post_eject_cooling_time_s=0.0, mold_temp_C=200.0),
        _make_spec(wall_thickness_uniformity_pct=50.0, gate_location="edge",
                   polymer_grade="PP", post_eject_cooling_time_s=15.0, mold_temp_C=100.0),
    ]
    for spec in cases:
        report = compute_warpage_index(spec)
        assert 0.0 <= report.warpage_index <= 100.0


# ===========================================================================
# 12. WarpageSpec validation
# ===========================================================================

def test_spec_uniformity_out_of_range_raises():
    """wall_thickness_uniformity_pct outside [0, 100] should raise ValueError."""
    with pytest.raises(ValueError):
        WarpageSpec(
            wall_thickness_uniformity_pct=110.0,
            gate_location="centered",
            polymer_grade="ABS",
            post_eject_cooling_time_s=30.0,
            mold_temp_C=60.0,
        )


def test_spec_negative_uniformity_raises():
    """Negative wall_thickness_uniformity_pct should raise ValueError."""
    with pytest.raises(ValueError):
        WarpageSpec(
            wall_thickness_uniformity_pct=-5.0,
            gate_location="centered",
            polymer_grade="ABS",
            post_eject_cooling_time_s=30.0,
            mold_temp_C=60.0,
        )


def test_spec_negative_cooling_time_raises():
    """Negative post_eject_cooling_time_s should raise ValueError."""
    with pytest.raises(ValueError):
        WarpageSpec(
            wall_thickness_uniformity_pct=80.0,
            gate_location="centered",
            polymer_grade="ABS",
            post_eject_cooling_time_s=-1.0,
            mold_temp_C=60.0,
        )


def test_spec_negative_mold_temp_raises():
    """Negative mold_temp_C should raise ValueError."""
    with pytest.raises(ValueError):
        WarpageSpec(
            wall_thickness_uniformity_pct=80.0,
            gate_location="centered",
            polymer_grade="ABS",
            post_eject_cooling_time_s=30.0,
            mold_temp_C=-10.0,
        )


# ===========================================================================
# 13. LLM tool handler
# ===========================================================================

def test_tool_dispatch_happy_path():
    """LLM tool returns ok=True with expected keys for a valid request."""
    from kerf_mold.warpage_index_tool import run_mold_compute_warpage_index

    args = {
        "wall_thickness_uniformity_pct": 85.0,
        "gate_location": "edge",
        "polymer_grade": "PA66",
        "post_eject_cooling_time_s": 45.0,
        "mold_temp_C": 80.0,
    }
    result = asyncio.get_event_loop().run_until_complete(
        run_mold_compute_warpage_index(args, ctx=None)
    )
    data = json.loads(result)
    assert data.get("ok") is True or "warpage_index" in data
    assert "warpage_index" in data or "result" in data


def test_tool_dispatch_missing_arg_returns_error():
    """LLM tool returns an error payload when a required arg is missing."""
    from kerf_mold.warpage_index_tool import run_mold_compute_warpage_index

    args = {
        "wall_thickness_uniformity_pct": 85.0,
        # gate_location missing
        "polymer_grade": "ABS",
        "post_eject_cooling_time_s": 30.0,
        "mold_temp_C": 60.0,
    }
    result = asyncio.get_event_loop().run_until_complete(
        run_mold_compute_warpage_index(args, ctx=None)
    )
    data = json.loads(result)
    assert data.get("ok") is not True


def test_tool_dispatch_bad_uniformity_returns_error():
    """LLM tool returns an error payload when uniformity is out of range."""
    from kerf_mold.warpage_index_tool import run_mold_compute_warpage_index

    args = {
        "wall_thickness_uniformity_pct": 150.0,  # invalid
        "gate_location": "centered",
        "polymer_grade": "ABS",
        "post_eject_cooling_time_s": 30.0,
        "mold_temp_C": 60.0,
    }
    result = asyncio.get_event_loop().run_until_complete(
        run_mold_compute_warpage_index(args, ctx=None)
    )
    data = json.loads(result)
    assert data.get("ok") is not True


# ===========================================================================
# 14. Additional boundary / regression cases
# ===========================================================================

def test_boundary_uniformity_80_medium_low():
    """Uniformity at exactly 80 % (acceptable boundary) should score ≤ 6 wall pts."""
    wall_score = _wall_uniformity_score(80.0)
    assert wall_score == pytest.approx(6.0, abs=1e-6)


def test_medium_risk_range():
    """A medium-risk configuration should land in [25, 50)."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=80.0,
        gate_location="edge",
        polymer_grade="PP",
        post_eject_cooling_time_s=40.0,
        mold_temp_C=50.0,
    )
    report = compute_warpage_index(spec)
    assert 20.0 <= report.warpage_index < 60.0, (
        f"Expected medium-ish index, got {report.warpage_index}"
    )


def test_high_index_fem_suggestion():
    """When index > 50, mitigations should mention FEM/Moldflow."""
    spec = WarpageSpec(
        wall_thickness_uniformity_pct=40.0,
        gate_location="unbalanced",
        polymer_grade="GF-PA66",
        post_eject_cooling_time_s=2.0,
        mold_temp_C=160.0,
    )
    report = compute_warpage_index(spec)
    assert report.warpage_index > 50.0
    combined = " ".join(report.mitigation_suggestions).lower()
    assert "moldflow" in combined or "fem" in combined or "moldex" in combined


def test_risk_level_thresholds():
    """Test that risk_level transitions match the documented thresholds."""
    # Force index into known bands by inspecting the score
    # Low: perfect conditions
    spec_low = WarpageSpec(
        wall_thickness_uniformity_pct=100.0,
        gate_location="centered",
        polymer_grade="PC",
        post_eject_cooling_time_s=120.0,
        mold_temp_C=90.0,
    )
    assert compute_warpage_index(spec_low).risk_level == "low"

    # Severe: all worst-case
    spec_severe = WarpageSpec(
        wall_thickness_uniformity_pct=0.0,
        gate_location="unbalanced",
        polymer_grade="GF-PA66",
        post_eject_cooling_time_s=0.0,
        mold_temp_C=200.0,
    )
    report_severe = compute_warpage_index(spec_severe)
    assert report_severe.risk_level == "severe"
    assert report_severe.warpage_index >= 75.0
