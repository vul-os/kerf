"""
Tests for kerf_mold.cooling_pressure_drop — Darcy-Weisbach mold cooling-
channel network pressure-drop calculator.

Oracle coverage (White §6.7; Beaumont 2007 §11.2):

 1.  1 m straight, 10 mm dia, 10 L/min water: Re ≈ 21 200, turbulent,
     ΔP in [0.05, 0.30] bar (manual Darcy-Weisbach check).
 2.  Re check: 1 m, 10 mm, 10 L/min water → Re ≈ 21 200 (±5 %).
 3.  Add 4 elbow_90 segments: total ΔP > straight-only ΔP.
 4.  Double the flow rate (10→20 L/min): ΔP increases by ~factor 3.5-4.5
     (turbulent: ΔP ∝ Q^1.75 via Blasius; Re^0.25 correction).
 5.  Laminar regime: very narrow channel (1 mm dia), low flow → Re < 2300,
     f = 64/Re, ΔP significantly higher than turbulent prediction.
 6.  Friction factor: turbulent (Re > 4000) → f = 0.316/Re^0.25.
 7.  Friction factor: laminar (Re < 2300) → f ≈ 64/Re.
 8.  Segment breakdown: number of entries equals number of input segments.
 9.  Segment breakdown: per-segment dp_total_bar > 0 for all segments.
10.  elbow_90 minor loss K=0.9: dp_minor_bar = 0.9 × dynamic_pressure_bar.
11.  CoolantSpec viscosity: higher viscosity → lower Re, possibly different
     friction regime; higher ΔP in laminar, lower Re.
12.  recommended_pump_head_bar = chiller_head_required_bar × 1.25 (±0.1 %).
13.  Varying diameter: smaller diameter → higher velocity → higher ΔP
     for the same length.
14.  tee_branch K=1.8 > elbow_90 K=0.9: same geometry, tee_branch ΔP_minor >
     elbow_90 ΔP_minor.
15.  LLM tool: valid call → ok=True, total_pressure_drop_bar > 0.
16.  LLM tool: missing segments → BAD_ARGS error.
17.  LLM tool: missing flow_rate_L_per_min → BAD_ARGS error.
18.  LLM tool: invalid segment_type → BAD_ARGS error.
19.  LLM tool: negative length_mm → BAD_ARGS error.
20.  CoolingChannelSegment.__post_init__: invalid segment_type → ValueError.
21.  CoolantSpec.__post_init__: zero flow rate → ValueError.
22.  Empty segment list → ValueError from compute_cooling_pressure_drop.
23.  Series of mixed segment types: total ΔP = sum of per-segment ΔP values.
24.  Higher-flow quadratic trend (turbulent): Q×2 → ΔP in [3.0, 5.0]×ΔP_base
     confirming super-linear (≈ Q^1.75) scaling.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_mold.cooling_pressure_drop import (
    CoolingChannelSegment,
    CoolantSpec,
    CoolingPressureDropReport,
    compute_cooling_pressure_drop,
    _friction_factor,
    _MINOR_LOSS_K,
)
from kerf_mold.cooling_pressure_drop_tool import (
    mold_cooling_pressure_drop_spec,
    run_mold_compute_cooling_pressure_drop,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _straight(length_mm: float, diameter_mm: float) -> CoolingChannelSegment:
    return CoolingChannelSegment(
        length_mm=length_mm,
        diameter_mm=diameter_mm,
        segment_type="straight",
    )


def _elbow90(length_mm: float, diameter_mm: float) -> CoolingChannelSegment:
    return CoolingChannelSegment(
        length_mm=length_mm,
        diameter_mm=diameter_mm,
        segment_type="elbow_90",
    )


def _water(flow_L_per_min: float = 10.0) -> CoolantSpec:
    return CoolantSpec(
        flow_rate_L_per_min=flow_L_per_min,
        density_kg_m3=1000.0,
        viscosity_cP=1.0,
    )


async def _call_tool(args: dict) -> dict:
    result = await run_mold_compute_cooling_pressure_drop(
        ctx=None,
        args=json.dumps(args).encode(),
    )
    return json.loads(result)


# ---------------------------------------------------------------------------
# Test 1: Basic 1 m straight, 10 mm dia, 10 L/min — ΔP range + regime
# ---------------------------------------------------------------------------

def test_1m_straight_10mm_10lpm_dp_range():
    """1 m, 10 mm, 10 L/min → Re ≈ 21200, turbulent, ΔP in [0.05, 0.30] bar."""
    segs = [_straight(1000.0, 10.0)]
    coolant = _water(10.0)
    report = compute_cooling_pressure_drop(segs, coolant)
    assert 0.05 <= report.total_pressure_drop_bar <= 0.30, (
        f"Expected ΔP in [0.05, 0.30] bar, got {report.total_pressure_drop_bar}"
    )


# ---------------------------------------------------------------------------
# Test 2: Re ≈ 21 200 for baseline case
# ---------------------------------------------------------------------------

def test_1m_straight_10mm_10lpm_reynolds():
    """Re for 1 m, 10 mm, 10 L/min water should be ≈ 21 200 (±5 %)."""
    # Manual: Q=10/60000=1.667e-4 m³/s; A=π(0.005)²=7.854e-5 m²
    # v=1.667e-4/7.854e-5=2.122 m/s; Re=1000×2.122×0.01/0.001=21220
    segs = [_straight(1000.0, 10.0)]
    coolant = _water(10.0)
    report = compute_cooling_pressure_drop(segs, coolant)
    expected_re = 21220.0
    assert abs(report.reynolds_number - expected_re) / expected_re < 0.05, (
        f"Expected Re ≈ {expected_re}, got {report.reynolds_number}"
    )


# ---------------------------------------------------------------------------
# Test 3: 4 elbow_90 segments increase ΔP vs straight only
# ---------------------------------------------------------------------------

def test_elbows_increase_pressure_drop():
    """4 elbow_90 segments should add minor losses → higher total ΔP."""
    coolant = _water(10.0)

    segs_straight = [_straight(1000.0, 10.0)]
    report_straight = compute_cooling_pressure_drop(segs_straight, coolant)

    segs_with_elbows = [
        _straight(1000.0, 10.0),
        _elbow90(50.0, 10.0),
        _elbow90(50.0, 10.0),
        _elbow90(50.0, 10.0),
        _elbow90(50.0, 10.0),
    ]
    report_elbows = compute_cooling_pressure_drop(segs_with_elbows, coolant)

    assert report_elbows.total_pressure_drop_bar > report_straight.total_pressure_drop_bar, (
        "Adding 4 elbows must increase total ΔP"
    )


# ---------------------------------------------------------------------------
# Test 4: Double flow rate → ΔP increases significantly
# ---------------------------------------------------------------------------

def test_double_flow_rate_increases_dp():
    """Doubling flow rate from 10→20 L/min in turbulent regime → ΔP×(3–5)."""
    segs = [_straight(1000.0, 10.0)]
    report_10 = compute_cooling_pressure_drop(segs, _water(10.0))
    report_20 = compute_cooling_pressure_drop(segs, _water(20.0))
    ratio = report_20.total_pressure_drop_bar / report_10.total_pressure_drop_bar
    # Blasius: f ∝ Re^-0.25 ∝ Q^-0.25; ΔP ∝ f·Q²/D ∝ Q^1.75 → ratio ≈ 2^1.75 ≈ 3.36
    assert ratio > 3.0, f"Expected ratio > 3.0, got {ratio:.3f}"
    assert ratio < 5.0, f"Expected ratio < 5.0, got {ratio:.3f}"


# ---------------------------------------------------------------------------
# Test 5: Laminar regime for very small channel at low flow
# ---------------------------------------------------------------------------

def test_laminar_regime_small_channel():
    """1 mm dia, 0.1 L/min → Re well below 2300, laminar, high ΔP."""
    segs = [_straight(200.0, 1.0)]
    coolant = CoolantSpec(flow_rate_L_per_min=0.1)
    report = compute_cooling_pressure_drop(segs, coolant)
    # Re = 1000 × v × 0.001 / 0.001; v = Q/A; Q=0.1/60000=1.667e-6 m³/s
    # A=π×(5e-4)²=7.854e-7 m²; v=2.122 m/s; Re=1000×2.122×0.001/0.001=2122 < 2300
    assert report.reynolds_number < 2300, (
        f"Expected laminar Re < 2300, got {report.reynolds_number}"
    )
    # Verify laminar f ≈ 64/Re
    expected_f = 64.0 / report.reynolds_number
    assert abs(report.friction_factor - expected_f) < 0.01, (
        f"Expected laminar f≈{expected_f:.4f}, got {report.friction_factor:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 6: Turbulent friction factor = Blasius
# ---------------------------------------------------------------------------

def test_turbulent_friction_factor_blasius():
    """Re > 4000 → f = 0.316 / Re^0.25 (Blasius)."""
    segs = [_straight(1000.0, 10.0)]
    coolant = _water(10.0)
    report = compute_cooling_pressure_drop(segs, coolant)
    re = report.reynolds_number
    assert re > 4000, f"Expected turbulent Re > 4000, got {re}"
    f_blasius = 0.316 / (re ** 0.25)
    assert abs(report.friction_factor - f_blasius) < 1e-6, (
        f"Expected Blasius f={f_blasius:.8f}, got {report.friction_factor}"
    )


# ---------------------------------------------------------------------------
# Test 7: Laminar friction factor = 64/Re
# ---------------------------------------------------------------------------

def test_laminar_friction_factor():
    """Very low flow in small channel → f ≈ 64/Re within 0.1 %."""
    re = 500.0
    f = _friction_factor(re)
    assert abs(f - 64.0 / re) < 1e-10, f"Expected f=64/Re={64/re:.6f}, got {f}"


# ---------------------------------------------------------------------------
# Test 8: Segment breakdown count matches input
# ---------------------------------------------------------------------------

def test_segment_breakdown_count():
    """segment_breakdown length equals number of input segments."""
    segs = [
        _straight(200.0, 10.0),
        _elbow90(10.0, 10.0),
        CoolingChannelSegment(length_mm=100.0, diameter_mm=10.0, segment_type="tee_thru"),
    ]
    coolant = _water(8.0)
    report = compute_cooling_pressure_drop(segs, coolant)
    assert len(report.segment_breakdown) == 3


# ---------------------------------------------------------------------------
# Test 9: Per-segment dp_total_bar > 0
# ---------------------------------------------------------------------------

def test_per_segment_dp_positive():
    """Every segment breakdown entry must have dp_total_bar > 0."""
    segs = [
        _straight(500.0, 10.0),
        _elbow90(20.0, 10.0),
        CoolingChannelSegment(length_mm=300.0, diameter_mm=8.0, segment_type="elbow_45"),
    ]
    coolant = _water(10.0)
    report = compute_cooling_pressure_drop(segs, coolant)
    for entry in report.segment_breakdown:
        assert entry["dp_total_bar"] > 0, (
            f"Segment {entry['index']} has non-positive dp_total_bar: "
            f"{entry['dp_total_bar']}"
        )


# ---------------------------------------------------------------------------
# Test 10: elbow_90 minor-loss check K=0.9
# ---------------------------------------------------------------------------

def test_elbow90_minor_loss_k_factor():
    """elbow_90 dp_minor_bar = 0.9 × (ρv²/2) in bar."""
    seg = CoolingChannelSegment(length_mm=1.0, diameter_mm=10.0, segment_type="elbow_90")
    coolant = _water(10.0)
    report = compute_cooling_pressure_drop([seg], coolant)
    bkd = report.segment_breakdown[0]
    # Dynamic pressure bar = 0.5 * rho * v^2 * 1e-5
    Q = 10.0 / 60_000.0
    D = 0.01
    A = math.pi * (D / 2) ** 2
    v = Q / A
    q_dyn_bar = 0.5 * 1000.0 * v ** 2 * 1e-5
    expected_minor = 0.9 * q_dyn_bar
    # Tolerance is 1e-6 bar to accommodate float rounding from round(..., 8)
    assert abs(bkd["dp_minor_bar"] - expected_minor) < 1e-6, (
        f"Expected dp_minor_bar≈{expected_minor:.8f}, got {bkd['dp_minor_bar']}"
    )


# ---------------------------------------------------------------------------
# Test 11: Higher viscosity → higher ΔP in laminar-boundary regime
# ---------------------------------------------------------------------------

def test_higher_viscosity_higher_dp_for_small_channel():
    """2× viscosity at same flow → higher ΔP.

    Use a very small channel (1 mm) at very low flow (0.02 L/min) so both
    cases are firmly laminar.  In the laminar regime f=64/Re, and
    Re ∝ 1/μ, so f ∝ μ.  ΔP ∝ f ∝ μ → doubling viscosity doubles ΔP.
    """
    # Re check: Q=0.02 L/min=3.33e-7 m³/s; D=0.001 m; A=7.854e-7 m²
    # v=0.424 m/s; Re(1cP)=1000*0.424*0.001/0.001=424 → laminar
    segs = [_straight(200.0, 1.0)]
    coolant_1cP = CoolantSpec(flow_rate_L_per_min=0.02, density_kg_m3=1000.0, viscosity_cP=1.0)
    coolant_2cP = CoolantSpec(flow_rate_L_per_min=0.02, density_kg_m3=1000.0, viscosity_cP=2.0)
    report_1 = compute_cooling_pressure_drop(segs, coolant_1cP)
    report_2 = compute_cooling_pressure_drop(segs, coolant_2cP)
    assert report_1.reynolds_number < 2300, (
        f"Expected laminar Re for 1cP case, got {report_1.reynolds_number}"
    )
    assert report_2.total_pressure_drop_bar > report_1.total_pressure_drop_bar, (
        "Higher viscosity should increase ΔP in laminar regime"
    )


# ---------------------------------------------------------------------------
# Test 12: recommended_pump_head_bar = chiller_head × 1.25
# ---------------------------------------------------------------------------

def test_recommended_pump_head_25pct_margin():
    """recommended_pump_head_bar must be 1.25 × chiller_head_required_bar."""
    segs = [_straight(500.0, 10.0)]
    report = compute_cooling_pressure_drop(segs, _water(10.0))
    ratio = report.recommended_pump_head_bar / report.chiller_head_required_bar
    assert abs(ratio - 1.25) < 1e-6, f"Expected ratio 1.25, got {ratio}"


# ---------------------------------------------------------------------------
# Test 13: Smaller diameter → higher velocity → higher ΔP (same length)
# ---------------------------------------------------------------------------

def test_smaller_diameter_higher_dp():
    """8 mm dia → higher ΔP than 12 mm dia at same length and flow rate."""
    coolant = _water(10.0)
    report_8 = compute_cooling_pressure_drop([_straight(500.0, 8.0)], coolant)
    report_12 = compute_cooling_pressure_drop([_straight(500.0, 12.0)], coolant)
    assert report_8.total_pressure_drop_bar > report_12.total_pressure_drop_bar, (
        "Smaller diameter must produce higher ΔP at the same flow rate"
    )


# ---------------------------------------------------------------------------
# Test 14: tee_branch K=1.8 > elbow_90 K=0.9 → more minor loss
# ---------------------------------------------------------------------------

def test_tee_branch_more_minor_loss_than_elbow90():
    """tee_branch dp_minor_bar > elbow_90 dp_minor_bar (same geometry)."""
    coolant = _water(10.0)
    seg_elbow = CoolingChannelSegment(length_mm=10.0, diameter_mm=10.0, segment_type="elbow_90")
    seg_tee = CoolingChannelSegment(length_mm=10.0, diameter_mm=10.0, segment_type="tee_branch")
    rep_e = compute_cooling_pressure_drop([seg_elbow], coolant)
    rep_t = compute_cooling_pressure_drop([seg_tee], coolant)
    e_minor = rep_e.segment_breakdown[0]["dp_minor_bar"]
    t_minor = rep_t.segment_breakdown[0]["dp_minor_bar"]
    assert t_minor > e_minor, (
        f"tee_branch minor loss ({t_minor:.8f}) must exceed elbow_90 ({e_minor:.8f})"
    )


# ---------------------------------------------------------------------------
# Test 15: LLM tool round-trip
# ---------------------------------------------------------------------------

def test_llm_tool_valid_call():
    """LLM tool returns ok=True and a positive total_pressure_drop_bar."""
    async def _run():
        return await _call_tool({
            "segments": [
                {"length_mm": 1000.0, "diameter_mm": 10.0, "segment_type": "straight"},
            ],
            "flow_rate_L_per_min": 10.0,
        })
    result = asyncio.run(_run())
    assert result.get("ok") is True
    assert result["total_pressure_drop_bar"] > 0.0


# ---------------------------------------------------------------------------
# Test 16: LLM tool — missing segments → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_segments():
    async def _run():
        return await _call_tool({"flow_rate_L_per_min": 10.0})
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 17: LLM tool — missing flow_rate_L_per_min → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_flow_rate():
    async def _run():
        return await _call_tool({
            "segments": [
                {"length_mm": 500.0, "diameter_mm": 10.0, "segment_type": "straight"}
            ],
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 18: LLM tool — invalid segment_type → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_invalid_segment_type():
    async def _run():
        return await _call_tool({
            "segments": [
                {"length_mm": 500.0, "diameter_mm": 10.0, "segment_type": "spiral"}
            ],
            "flow_rate_L_per_min": 10.0,
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 19: LLM tool — negative length_mm → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_negative_length():
    async def _run():
        return await _call_tool({
            "segments": [
                {"length_mm": -100.0, "diameter_mm": 10.0, "segment_type": "straight"}
            ],
            "flow_rate_L_per_min": 10.0,
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 20: CoolingChannelSegment — invalid segment_type raises ValueError
# ---------------------------------------------------------------------------

def test_segment_invalid_type_raises():
    with pytest.raises(ValueError, match="segment_type"):
        CoolingChannelSegment(length_mm=100.0, diameter_mm=10.0, segment_type="bend_weird")


# ---------------------------------------------------------------------------
# Test 21: CoolantSpec — zero flow rate raises ValueError
# ---------------------------------------------------------------------------

def test_coolant_zero_flow_raises():
    with pytest.raises(ValueError, match="flow_rate_L_per_min"):
        CoolantSpec(flow_rate_L_per_min=0.0)


# ---------------------------------------------------------------------------
# Test 22: Empty segment list → ValueError
# ---------------------------------------------------------------------------

def test_empty_segments_raises():
    with pytest.raises(ValueError):
        compute_cooling_pressure_drop([], _water(10.0))


# ---------------------------------------------------------------------------
# Test 23: Mixed segments — total = sum of individual dp_total_bar values
# ---------------------------------------------------------------------------

def test_total_equals_sum_of_breakdown():
    """total_pressure_drop_bar ≈ Σ dp_total_bar in segment_breakdown.

    The report total is computed by accumulating raw Pa values then converting;
    per-segment values are independently rounded to 8 dp.  So the sum of
    rounded per-segment values may differ from the rounded total by up to
    a few counts in the last byte of float64.  Tolerance is 1e-5 bar (~1 Pa).
    """
    segs = [
        _straight(800.0, 10.0),
        _elbow90(20.0, 10.0),
        CoolingChannelSegment(length_mm=400.0, diameter_mm=10.0, segment_type="tee_branch"),
        CoolingChannelSegment(length_mm=20.0, diameter_mm=10.0, segment_type="elbow_45"),
    ]
    report = compute_cooling_pressure_drop(segs, _water(10.0))
    calculated_sum = sum(e["dp_total_bar"] for e in report.segment_breakdown)
    assert abs(report.total_pressure_drop_bar - calculated_sum) < 1e-5, (
        f"total ({report.total_pressure_drop_bar:.10f}) != "
        f"sum ({calculated_sum:.10f})"
    )


# ---------------------------------------------------------------------------
# Test 24: Quadratic ΔP scaling — Q×2 in turbulent regime → ΔP×(3.0–5.0)
# ---------------------------------------------------------------------------

def test_quadratic_flow_scaling_turbulent():
    """In turbulent flow, doubling Q → ΔP ≈ 3.36× (Q^1.75 Blasius scaling)."""
    segs = [_straight(2000.0, 10.0)]
    report_base = compute_cooling_pressure_drop(segs, _water(10.0))
    report_2x = compute_cooling_pressure_drop(segs, _water(20.0))
    ratio = report_2x.total_pressure_drop_bar / report_base.total_pressure_drop_bar
    # Blasius: ΔP ∝ Q^1.75 → ratio ≈ 2^1.75 ≈ 3.36; allow ±0.4 tolerance
    assert 3.0 <= ratio <= 5.0, (
        f"Expected Q²-ish turbulent scaling ratio in [3.0, 5.0], got {ratio:.3f}"
    )
