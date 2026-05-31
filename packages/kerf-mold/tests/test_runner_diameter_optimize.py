"""
Tests for kerf_mold.runner_diameter_optimize — Beaumont §6.5 runner-diameter
optimiser.

Oracle coverage (Beaumont 2007 §6.5 + Menges 2001 §6.5):

 1.  Beaumont base formula: W=50g, L=100mm → D_base ≈ 7.19mm (±1%)
 2.  ABS (+10%) adjustment: W=50g, L=100mm → D_rec ≈ 7.91mm (±1%)
 3.  PC (+15%) adjustment → D_rec > ABS D_rec for same inputs
 4.  PP (-5%) adjustment → D_rec < ABS D_rec for same inputs
 5.  PA66 (±0%) adjustment → D_rec ≈ D_base (no adjustment)
 6.  Unknown polymer → D_rec ≈ D_base (±0% adjustment, no crash)
 7.  D clamp lower: very tiny part (W=0.5g, L=20mm) → D ≥ 1.5mm
 8.  D clamp upper: very large part (W=1000g, L=300mm) → D ≤ 16.0mm
 9.  Cold-runner waste > 0 for all valid inputs
10.  PC waste > ABS waste for same W and L (higher density + larger D)
11.  Fill-pressure proxy > 0 for all valid inputs
12.  Longer runner → larger recommended diameter (√L dependence)
13.  Heavier part → larger recommended diameter (W^0.25 dependence)
14.  Multi-gate (gate_count=2) → smaller D than gate_count=1 for same total W
15.  Polymer-specific adjustment string is non-empty and mentions polymer
16.  Honest caveat is non-empty and mentions Beaumont
17.  LLM tool: valid ABS call → ok=True, recommended_diameter_mm > 0
18.  LLM tool: missing part_weight_g → BAD_ARGS error
19.  LLM tool: missing runner_length_mm → BAD_ARGS error
20.  LLM tool: missing polymer_grade → BAD_ARGS error
21.  LLM tool: zero part_weight_g → BAD_ARGS error
22.  LLM tool: negative runner_length_mm → BAD_ARGS error
23.  LLM tool: gate_count=0 → BAD_ARGS error
24.  LLM tool: gate_count=3 (valid multi-gate) → ok=True, smaller D
25.  RunnerOptimizeSpec.__post_init__: zero weight → ValueError
26.  RunnerOptimizeSpec.__post_init__: zero runner length → ValueError
27.  RunnerOptimizeSpec.__post_init__: gate_count=0 → ValueError
28.  Waste for ABS W=50g L=100mm: vol=π*(7.91/2)²×100mm³ × 1.05g/cm³ × 1e-3 ≈ 5.15g (±5%)
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

from kerf_mold.runner_diameter_optimize import (
    RunnerOptimizeSpec,
    RunnerOptimizeReport,
    optimize_runner_diameter,
)
from kerf_mold.runner_diameter_optimize_tool import (
    mold_optimize_runner_diameter_spec,
    run_mold_optimize_runner_diameter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(
    part_weight_g: float = 50.0,
    runner_length_mm: float = 100.0,
    polymer_grade: str = "ABS",
    gate_count: int = 1,
) -> RunnerOptimizeSpec:
    return RunnerOptimizeSpec(
        part_weight_g=part_weight_g,
        runner_length_mm=runner_length_mm,
        polymer_grade=polymer_grade,
        gate_count=gate_count,
    )


async def _call_tool(args: dict) -> dict:
    result = await run_mold_optimize_runner_diameter(
        ctx=None,
        args=json.dumps(args).encode(),
    )
    return json.loads(result)


# ---------------------------------------------------------------------------
# Test 1: Beaumont base formula
# ---------------------------------------------------------------------------

def test_beaumont_base_formula_abs_50g_100mm():
    """W=50g, L=100mm: D_base = (50^0.25 × √100) / 3.7 ≈ 7.19mm (±1%)."""
    report = optimize_runner_diameter(_spec(50.0, 100.0, "ABS"))
    expected = (50.0 ** 0.25 * math.sqrt(100.0)) / 3.7
    assert abs(report.beaumont_diameter_mm - expected) / expected < 0.01, (
        f"Expected D_base ≈ {expected:.4f} mm, got {report.beaumont_diameter_mm}"
    )


# ---------------------------------------------------------------------------
# Test 2: ABS +10% adjustment
# ---------------------------------------------------------------------------

def test_abs_10pct_adjustment():
    """W=50g, L=100mm, ABS: D_rec ≈ D_base × 1.10 ≈ 7.91mm (±1%)."""
    report = optimize_runner_diameter(_spec(50.0, 100.0, "ABS"))
    expected_adj = report.beaumont_diameter_mm * 1.10
    assert abs(report.recommended_diameter_mm - expected_adj) / expected_adj < 0.01, (
        f"ABS +10%: expected {expected_adj:.4f}, got {report.recommended_diameter_mm}"
    )


# ---------------------------------------------------------------------------
# Test 3: PC (+15%) larger than ABS
# ---------------------------------------------------------------------------

def test_pc_larger_than_abs():
    """PC (+15%) must yield larger recommended diameter than ABS (+10%)."""
    report_abs = optimize_runner_diameter(_spec(50.0, 100.0, "ABS"))
    report_pc = optimize_runner_diameter(_spec(50.0, 100.0, "PC"))
    assert report_pc.recommended_diameter_mm > report_abs.recommended_diameter_mm, (
        f"PC ({report_pc.recommended_diameter_mm:.4f}) must exceed "
        f"ABS ({report_abs.recommended_diameter_mm:.4f})"
    )


# ---------------------------------------------------------------------------
# Test 4: PP (-5%) smaller than ABS
# ---------------------------------------------------------------------------

def test_pp_smaller_than_abs():
    """PP (-5%) must yield smaller recommended diameter than ABS (+10%)."""
    report_abs = optimize_runner_diameter(_spec(50.0, 100.0, "ABS"))
    report_pp = optimize_runner_diameter(_spec(50.0, 100.0, "PP"))
    assert report_pp.recommended_diameter_mm < report_abs.recommended_diameter_mm, (
        f"PP ({report_pp.recommended_diameter_mm:.4f}) must be less than "
        f"ABS ({report_abs.recommended_diameter_mm:.4f})"
    )


# ---------------------------------------------------------------------------
# Test 5: PA66 (±0%) close to D_base
# ---------------------------------------------------------------------------

def test_pa66_zero_adjustment():
    """PA66 (±0%): recommended_diameter_mm ≈ beaumont_diameter_mm (clamped)."""
    report = optimize_runner_diameter(_spec(50.0, 100.0, "PA66"))
    assert abs(report.recommended_diameter_mm - report.beaumont_diameter_mm) < 1e-6, (
        f"PA66 no adjustment: expected D_rec == D_base, "
        f"got D_rec={report.recommended_diameter_mm}, D_base={report.beaumont_diameter_mm}"
    )


# ---------------------------------------------------------------------------
# Test 6: Unknown polymer — no crash, ±0% adjustment
# ---------------------------------------------------------------------------

def test_unknown_polymer_no_crash():
    """Unknown polymer 'PEEK' must not crash and apply ±0% adjustment."""
    report = optimize_runner_diameter(_spec(50.0, 100.0, "PEEK"))
    # Should equal D_base (no adjustment, then clamped if needed)
    assert abs(report.recommended_diameter_mm - report.beaumont_diameter_mm) < 1e-6, (
        "Unknown polymer must apply ±0% adjustment"
    )
    assert report.recommended_diameter_mm > 0.0


# ---------------------------------------------------------------------------
# Test 7: Lower clamp — tiny part
# ---------------------------------------------------------------------------

def test_lower_clamp_tiny_part():
    """Very tiny part (W=0.5g, L=20mm) → D_rec >= 1.5mm lower clamp."""
    report = optimize_runner_diameter(_spec(0.5, 20.0, "PP"))
    assert report.recommended_diameter_mm >= 1.5, (
        f"Lower clamp: expected D_rec >= 1.5mm, got {report.recommended_diameter_mm}"
    )


# ---------------------------------------------------------------------------
# Test 8: Upper clamp — very large part
# ---------------------------------------------------------------------------

def test_upper_clamp_large_part():
    """Very large part (W=1000g, L=300mm) → D_rec <= 16.0mm upper clamp."""
    report = optimize_runner_diameter(_spec(1000.0, 300.0, "PC"))
    assert report.recommended_diameter_mm <= 16.0, (
        f"Upper clamp: expected D_rec <= 16.0mm, got {report.recommended_diameter_mm}"
    )


# ---------------------------------------------------------------------------
# Test 9: Cold-runner waste positive
# ---------------------------------------------------------------------------

def test_cold_runner_waste_positive():
    """cold_runner_waste_g must be > 0 for all valid inputs."""
    for grade in ["ABS", "PC", "PP", "PA66", "PEEK"]:
        report = optimize_runner_diameter(_spec(50.0, 100.0, grade))
        assert report.cold_runner_waste_g > 0.0, (
            f"Expected waste > 0 for {grade}, got {report.cold_runner_waste_g}"
        )


# ---------------------------------------------------------------------------
# Test 10: PC waste > ABS waste (higher density + larger D)
# ---------------------------------------------------------------------------

def test_pc_more_waste_than_abs():
    """PC produces more cold-runner waste than ABS (higher density + larger D)."""
    report_abs = optimize_runner_diameter(_spec(50.0, 100.0, "ABS"))
    report_pc = optimize_runner_diameter(_spec(50.0, 100.0, "PC"))
    assert report_pc.cold_runner_waste_g > report_abs.cold_runner_waste_g, (
        f"PC waste ({report_pc.cold_runner_waste_g:.4f}g) must exceed "
        f"ABS waste ({report_abs.cold_runner_waste_g:.4f}g)"
    )


# ---------------------------------------------------------------------------
# Test 11: Fill-pressure estimate positive
# ---------------------------------------------------------------------------

def test_fill_pressure_positive():
    """fill_pressure_estimate_MPa must be > 0 for all valid inputs."""
    for grade in ["ABS", "PC", "PP", "PA66"]:
        report = optimize_runner_diameter(_spec(50.0, 100.0, grade))
        assert report.fill_pressure_estimate_MPa > 0.0, (
            f"Expected fill_pressure > 0 for {grade}, got "
            f"{report.fill_pressure_estimate_MPa}"
        )


# ---------------------------------------------------------------------------
# Test 12: Longer runner → larger diameter (√L dependence)
# ---------------------------------------------------------------------------

def test_longer_runner_larger_diameter():
    """D increases with runner length L (√L scaling in Beaumont formula)."""
    report_short = optimize_runner_diameter(_spec(50.0, 50.0, "ABS"))
    report_long = optimize_runner_diameter(_spec(50.0, 200.0, "ABS"))
    assert report_long.recommended_diameter_mm > report_short.recommended_diameter_mm, (
        f"Longer runner: D(200)={report_long.recommended_diameter_mm:.4f} must exceed "
        f"D(50)={report_short.recommended_diameter_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 13: Heavier part → larger diameter (W^0.25 dependence)
# ---------------------------------------------------------------------------

def test_heavier_part_larger_diameter():
    """D increases with part weight W (W^0.25 scaling in Beaumont formula)."""
    report_light = optimize_runner_diameter(_spec(10.0, 100.0, "ABS"))
    report_heavy = optimize_runner_diameter(_spec(200.0, 100.0, "ABS"))
    assert report_heavy.recommended_diameter_mm > report_light.recommended_diameter_mm, (
        f"Heavier part: D(200g)={report_heavy.recommended_diameter_mm:.4f} must exceed "
        f"D(10g)={report_light.recommended_diameter_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 14: Multi-gate (gate_count=2) → smaller D than single gate
# ---------------------------------------------------------------------------

def test_multi_gate_smaller_diameter():
    """gate_count=2 splits W/2 per gate → smaller runner D than single gate."""
    report_single = optimize_runner_diameter(_spec(50.0, 100.0, "ABS", gate_count=1))
    report_multi = optimize_runner_diameter(_spec(50.0, 100.0, "ABS", gate_count=2))
    assert report_multi.recommended_diameter_mm < report_single.recommended_diameter_mm, (
        f"Multi-gate D ({report_multi.recommended_diameter_mm:.4f}) must be less than "
        f"single-gate D ({report_single.recommended_diameter_mm:.4f})"
    )


# ---------------------------------------------------------------------------
# Test 15: Polymer adjustment string non-empty and mentions polymer
# ---------------------------------------------------------------------------

def test_polymer_adjustment_string_content():
    """polymer_specific_adjustment must mention the polymer grade."""
    for grade, expected_upper in [("ABS", "ABS"), ("PC", "PC"), ("PP", "PP"), ("PA66", "PA66")]:
        report = optimize_runner_diameter(_spec(50.0, 100.0, grade))
        adj = report.polymer_specific_adjustment
        assert len(adj) > 0, f"polymer_specific_adjustment must not be empty for {grade}"
        assert expected_upper in adj, (
            f"Expected '{expected_upper}' in adjustment string, got '{adj}'"
        )


# ---------------------------------------------------------------------------
# Test 16: Honest caveat mentions Beaumont and is non-empty
# ---------------------------------------------------------------------------

def test_honest_caveat_content():
    """honest_caveat must be non-empty and mention Beaumont."""
    report = optimize_runner_diameter(_spec())
    assert len(report.honest_caveat) > 0, "honest_caveat must not be empty"
    assert "Beaumont" in report.honest_caveat, (
        "honest_caveat must mention Beaumont"
    )


# ---------------------------------------------------------------------------
# Test 17: LLM tool valid ABS call
# ---------------------------------------------------------------------------

def test_llm_tool_valid_abs_call():
    """LLM tool: valid ABS call returns ok=True and positive diameter."""
    async def _run():
        return await _call_tool({
            "part_weight_g": 50.0,
            "runner_length_mm": 100.0,
            "polymer_grade": "ABS",
        })
    result = asyncio.run(_run())
    assert result.get("ok") is True, f"Expected ok=True, got: {result}"
    assert result["recommended_diameter_mm"] > 0.0, (
        f"Expected positive diameter, got {result['recommended_diameter_mm']}"
    )


# ---------------------------------------------------------------------------
# Test 18: LLM tool — missing part_weight_g → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_part_weight():
    async def _run():
        return await _call_tool({
            "runner_length_mm": 100.0,
            "polymer_grade": "ABS",
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result}"


# ---------------------------------------------------------------------------
# Test 19: LLM tool — missing runner_length_mm → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_runner_length():
    async def _run():
        return await _call_tool({
            "part_weight_g": 50.0,
            "polymer_grade": "ABS",
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result}"


# ---------------------------------------------------------------------------
# Test 20: LLM tool — missing polymer_grade → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_polymer_grade():
    async def _run():
        return await _call_tool({
            "part_weight_g": 50.0,
            "runner_length_mm": 100.0,
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result}"


# ---------------------------------------------------------------------------
# Test 21: LLM tool — zero part_weight_g → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_zero_weight():
    async def _run():
        return await _call_tool({
            "part_weight_g": 0.0,
            "runner_length_mm": 100.0,
            "polymer_grade": "ABS",
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result}"


# ---------------------------------------------------------------------------
# Test 22: LLM tool — negative runner_length_mm → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_negative_length():
    async def _run():
        return await _call_tool({
            "part_weight_g": 50.0,
            "runner_length_mm": -100.0,
            "polymer_grade": "ABS",
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result}"


# ---------------------------------------------------------------------------
# Test 23: LLM tool — gate_count=0 → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_zero_gate_count():
    async def _run():
        return await _call_tool({
            "part_weight_g": 50.0,
            "runner_length_mm": 100.0,
            "polymer_grade": "ABS",
            "gate_count": 0,
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result}"


# ---------------------------------------------------------------------------
# Test 24: LLM tool — gate_count=3, valid multi-gate
# ---------------------------------------------------------------------------

def test_llm_tool_multi_gate_valid():
    """LLM tool: gate_count=3 is valid, D smaller than single gate."""
    async def _run_single():
        return await _call_tool({
            "part_weight_g": 60.0,
            "runner_length_mm": 120.0,
            "polymer_grade": "ABS",
            "gate_count": 1,
        })

    async def _run_multi():
        return await _call_tool({
            "part_weight_g": 60.0,
            "runner_length_mm": 120.0,
            "polymer_grade": "ABS",
            "gate_count": 3,
        })

    res_single = asyncio.run(_run_single())
    res_multi = asyncio.run(_run_multi())
    assert res_multi.get("ok") is True, f"Multi-gate call failed: {res_multi}"
    assert res_multi["recommended_diameter_mm"] < res_single["recommended_diameter_mm"], (
        f"gate_count=3 D ({res_multi['recommended_diameter_mm']:.4f}) must be less "
        f"than gate_count=1 D ({res_single['recommended_diameter_mm']:.4f})"
    )


# ---------------------------------------------------------------------------
# Test 25: RunnerOptimizeSpec — zero weight → ValueError
# ---------------------------------------------------------------------------

def test_spec_zero_weight_raises():
    with pytest.raises(ValueError, match="part_weight_g"):
        RunnerOptimizeSpec(part_weight_g=0.0, runner_length_mm=100.0, polymer_grade="ABS")


# ---------------------------------------------------------------------------
# Test 26: RunnerOptimizeSpec — zero length → ValueError
# ---------------------------------------------------------------------------

def test_spec_zero_length_raises():
    with pytest.raises(ValueError, match="runner_length_mm"):
        RunnerOptimizeSpec(part_weight_g=50.0, runner_length_mm=0.0, polymer_grade="ABS")


# ---------------------------------------------------------------------------
# Test 27: RunnerOptimizeSpec — gate_count=0 → ValueError
# ---------------------------------------------------------------------------

def test_spec_zero_gate_count_raises():
    with pytest.raises(ValueError, match="gate_count"):
        RunnerOptimizeSpec(part_weight_g=50.0, runner_length_mm=100.0,
                           polymer_grade="ABS", gate_count=0)


# ---------------------------------------------------------------------------
# Test 28: Cold-runner waste oracle for ABS W=50g L=100mm
# ---------------------------------------------------------------------------

def test_abs_cold_runner_waste_oracle():
    """ABS W=50g L=100mm: waste ≈ π*(7.91/2)²×100mm³ × 1.05/1000 ≈ 5.15g (±5%)."""
    report = optimize_runner_diameter(_spec(50.0, 100.0, "ABS"))
    # D_rec ≈ 7.906mm
    D = report.recommended_diameter_mm
    L = 100.0
    rho = 1.05  # ABS g/cm³
    expected_waste = math.pi * (D / 2) ** 2 * L * 1e-3 * rho
    assert abs(report.cold_runner_waste_g - expected_waste) / expected_waste < 0.01, (
        f"Expected waste ≈ {expected_waste:.4f}g, got {report.cold_runner_waste_g:.4f}g"
    )
    # Sanity range: should be roughly 5 g for these dimensions
    assert 3.0 < report.cold_runner_waste_g < 10.0, (
        f"Expected waste in [3, 10]g, got {report.cold_runner_waste_g:.4f}g"
    )
