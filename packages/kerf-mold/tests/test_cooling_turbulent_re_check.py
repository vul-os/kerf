"""
Tests for kerf_mold.cooling_turbulent_re_check — cooling-channel Reynolds-
number turbulence checker.

Oracle coverage (White §8.1; Beaumont 2007 §11; Incropera eq. 8.60):

 1.  10mm channel, 10 L/min water: v≈2.122 m/s, Re≈21220, fully_turbulent,
     dittus_boelter_applicable=True.
 2.  10mm channel, 10 L/min water: Re within ±1 % of 21220.
 3.  10mm channel, 2 L/min water: Re≈4243, "turbulent" (not fully_turbulent),
     dittus_boelter_applicable=False.
 4.  10mm channel, 1 L/min water: Re≈2121, "laminar",
     dittus_boelter_applicable=False.
 5.  Recommended min flow rate for 10mm channel gives Re ≥ 10000.
 6.  Recommended min flow rate monotonicity: larger diameter → higher Q_min.
 7.  Transitional zone: Re between 2300 and 4000 → regime="transitional".
 8.  8mm channel, 5 L/min water: Re≈10610, fully_turbulent.
 9.  Higher viscosity (2 cP) → lower Re for same Q.
10.  Higher density with same Q → higher Re.
11.  Very low flow (0.1 L/min), 10mm: Re<2300, laminar.
12.  Velocity calculation: v = Q/A check for known geometry.
13.  LLM tool: valid call → ok=True, fully_turbulent, Re>10000.
14.  LLM tool: missing channel_diameter_mm → BAD_ARGS.
15.  LLM tool: missing flow_rate_L_per_min → BAD_ARGS.
16.  LLM tool: negative diameter → BAD_ARGS.
17.  LLM tool: zero flow rate → BAD_ARGS.
18.  CoolingFlowSpec: zero diameter → ValueError.
19.  CoolingFlowSpec: zero flow rate → ValueError.
20.  CoolingFlowSpec: negative viscosity → ValueError.
21.  Re exactly at 10000 boundary → fully_turbulent.
22.  Re exactly at 4000 boundary → turbulent (not transitional).
23.  Re exactly at 2300 boundary → transitional (not laminar).
24.  Regime strings are one of the four valid values for a sweep of flow rates.
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

from kerf_mold.cooling_turbulent_re_check import (
    CoolingFlowSpec,
    TurbulentReCheckReport,
    check_turbulent_re,
    _RE_LAMINAR_MAX,
    _RE_TURBULENT_MIN,
    _RE_FULLY_TURBULENT,
)
from kerf_mold.cooling_turbulent_re_check_tool import (
    mold_check_turbulent_re_spec,
    run_mold_check_turbulent_re,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _water_spec(diameter_mm: float, flow_L_per_min: float) -> CoolingFlowSpec:
    """Create a water CoolingFlowSpec with default density/viscosity."""
    return CoolingFlowSpec(
        channel_diameter_mm=diameter_mm,
        flow_rate_L_per_min=flow_L_per_min,
        coolant_density_kg_m3=1000.0,
        coolant_viscosity_cP=1.0,
    )


def _expected_re(diameter_mm: float, flow_L_per_min: float,
                 density: float = 1000.0, viscosity_cP: float = 1.0) -> float:
    """Manual Re calculation for cross-validation."""
    D = diameter_mm * 1e-3
    Q = flow_L_per_min / 60_000.0
    mu = viscosity_cP * 1e-3
    A = math.pi * (D / 2.0) ** 2
    v = Q / A
    return density * v * D / mu


async def _call_tool(args: dict) -> dict:
    result = await run_mold_check_turbulent_re(
        ctx=None,
        args=json.dumps(args).encode(),
    )
    return json.loads(result)


# ---------------------------------------------------------------------------
# Test 1: 10mm, 10 L/min → v≈2.122 m/s, Re≈21220, fully_turbulent
# ---------------------------------------------------------------------------

def test_10mm_10lpm_fully_turbulent():
    """10 mm channel, 10 L/min water → Re≈21220, fully_turbulent, DB applicable."""
    spec = _water_spec(10.0, 10.0)
    report = check_turbulent_re(spec)
    assert report.flow_regime == "fully_turbulent", (
        f"Expected fully_turbulent, got {report.flow_regime}"
    )
    assert report.dittus_boelter_applicable is True
    # velocity check: Q=10/60000=1.667e-4 m³/s; A=π×0.005²=7.854e-5 m²; v=2.122 m/s
    assert abs(report.velocity_m_per_s - 2.122) < 0.01, (
        f"Expected v≈2.122 m/s, got {report.velocity_m_per_s}"
    )


# ---------------------------------------------------------------------------
# Test 2: Re accuracy within ±1 % of 21220
# ---------------------------------------------------------------------------

def test_10mm_10lpm_re_accuracy():
    """Re for 10mm / 10 L/min water should be ≈21220 (±1 %)."""
    spec = _water_spec(10.0, 10.0)
    report = check_turbulent_re(spec)
    expected = _expected_re(10.0, 10.0)
    assert abs(report.reynolds_number - expected) / expected < 0.01, (
        f"Expected Re≈{expected:.1f}, got {report.reynolds_number}"
    )


# ---------------------------------------------------------------------------
# Test 3: 10mm, 2 L/min → Re≈4243, turbulent (not fully_turbulent)
# ---------------------------------------------------------------------------

def test_10mm_2lpm_turbulent_not_fully():
    """10mm channel, 2 L/min water → Re≈4243, regime=turbulent, DB=False."""
    spec = _water_spec(10.0, 2.0)
    report = check_turbulent_re(spec)
    expected_re = _expected_re(10.0, 2.0)
    assert abs(report.reynolds_number - expected_re) / expected_re < 0.01
    assert report.flow_regime == "turbulent", (
        f"Expected turbulent, got {report.flow_regime}"
    )
    assert report.dittus_boelter_applicable is False


# ---------------------------------------------------------------------------
# Test 4: 10mm, 1 L/min → Re≈2121, laminar
# ---------------------------------------------------------------------------

def test_10mm_1lpm_laminar():
    """10mm channel, 1 L/min water → Re≈2121, regime=laminar, DB=False."""
    spec = _water_spec(10.0, 1.0)
    report = check_turbulent_re(spec)
    assert report.reynolds_number < _RE_LAMINAR_MAX, (
        f"Expected Re < {_RE_LAMINAR_MAX}, got {report.reynolds_number}"
    )
    assert report.flow_regime == "laminar", (
        f"Expected laminar, got {report.flow_regime}"
    )
    assert report.dittus_boelter_applicable is False


# ---------------------------------------------------------------------------
# Test 5: Recommended min flow rate achieves Re ≥ 10000
# ---------------------------------------------------------------------------

def test_recommended_min_flow_achieves_fully_turbulent():
    """recommended_min_flow_rate should result in Re ≥ 10000 when used."""
    for diameter_mm in [6.0, 10.0, 12.0, 16.0]:
        spec = _water_spec(diameter_mm, 1.0)          # start at low flow
        report = check_turbulent_re(spec)
        q_min = report.recommended_min_flow_rate_L_per_min

        # Verify by running check_turbulent_re at the recommended flow
        spec_min = _water_spec(diameter_mm, q_min)
        report_min = check_turbulent_re(spec_min)
        assert report_min.reynolds_number >= _RE_FULLY_TURBULENT - 1.0, (
            f"D={diameter_mm}mm: recommended Q_min={q_min:.4f} L/min gave "
            f"Re={report_min.reynolds_number:.1f}, expected ≥{_RE_FULLY_TURBULENT}"
        )


# ---------------------------------------------------------------------------
# Test 6: Q_min monotonicity — larger diameter → higher Q_min
# ---------------------------------------------------------------------------

def test_larger_diameter_higher_qmin():
    """Larger channel diameter requires higher flow rate to stay fully turbulent."""
    # For same fluid: Q_min = Re_target * mu * A / (rho * D) = Re*mu*π*D/4 ∝ D
    report_8 = check_turbulent_re(_water_spec(8.0, 5.0))
    report_12 = check_turbulent_re(_water_spec(12.0, 5.0))
    assert (report_12.recommended_min_flow_rate_L_per_min >
            report_8.recommended_min_flow_rate_L_per_min), (
        "12mm channel should need higher Q_min than 8mm channel"
    )


# ---------------------------------------------------------------------------
# Test 7: Transitional zone (2300 ≤ Re < 4000)
# ---------------------------------------------------------------------------

def test_transitional_zone():
    """Flow with Re between 2300 and 4000 → regime=transitional."""
    # Need Re ≈ 3000 in a 10mm channel:
    # Re = ρ*v*D/μ; v = Re*μ/(ρ*D) = 3000*0.001/(1000*0.01) = 0.3 m/s
    # Q = v*A = 0.3 * π*(0.005)² = 0.3 * 7.854e-5 = 2.356e-5 m³/s = 1.414 L/min
    spec = _water_spec(10.0, 1.414)
    report = check_turbulent_re(spec)
    assert _RE_LAMINAR_MAX <= report.reynolds_number < _RE_TURBULENT_MIN, (
        f"Expected transitional Re in [{_RE_LAMINAR_MAX}, {_RE_TURBULENT_MIN}), "
        f"got {report.reynolds_number}"
    )
    assert report.flow_regime == "transitional", (
        f"Expected transitional, got {report.flow_regime}"
    )
    assert report.dittus_boelter_applicable is False


# ---------------------------------------------------------------------------
# Test 8: 8mm channel, 5 L/min → Re≈10610, fully_turbulent
# ---------------------------------------------------------------------------

def test_8mm_5lpm_fully_turbulent():
    """8mm channel, 5 L/min water → Re≈10610, fully_turbulent."""
    spec = _water_spec(8.0, 5.0)
    report = check_turbulent_re(spec)
    expected = _expected_re(8.0, 5.0)
    assert abs(report.reynolds_number - expected) / expected < 0.01
    assert report.flow_regime == "fully_turbulent", (
        f"Expected fully_turbulent, got {report.flow_regime} (Re={report.reynolds_number:.1f})"
    )
    assert report.dittus_boelter_applicable is True


# ---------------------------------------------------------------------------
# Test 9: Higher viscosity → lower Re
# ---------------------------------------------------------------------------

def test_higher_viscosity_lower_re():
    """2 cP viscosity gives lower Re than 1 cP at the same flow rate."""
    spec_1cP = CoolingFlowSpec(
        channel_diameter_mm=10.0,
        flow_rate_L_per_min=10.0,
        coolant_density_kg_m3=1000.0,
        coolant_viscosity_cP=1.0,
    )
    spec_2cP = CoolingFlowSpec(
        channel_diameter_mm=10.0,
        flow_rate_L_per_min=10.0,
        coolant_density_kg_m3=1000.0,
        coolant_viscosity_cP=2.0,
    )
    report_1 = check_turbulent_re(spec_1cP)
    report_2 = check_turbulent_re(spec_2cP)
    # Re ∝ 1/μ → doubling viscosity halves Re
    assert report_2.reynolds_number < report_1.reynolds_number
    ratio = report_1.reynolds_number / report_2.reynolds_number
    assert abs(ratio - 2.0) < 0.01, f"Expected ratio≈2.0, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# Test 10: Higher density → higher Re
# ---------------------------------------------------------------------------

def test_higher_density_higher_re():
    """Higher coolant density (e.g. EG/water 1040 kg/m³) → higher Re."""
    spec_water = CoolingFlowSpec(
        channel_diameter_mm=10.0, flow_rate_L_per_min=10.0,
        coolant_density_kg_m3=1000.0, coolant_viscosity_cP=1.0,
    )
    spec_eg = CoolingFlowSpec(
        channel_diameter_mm=10.0, flow_rate_L_per_min=10.0,
        coolant_density_kg_m3=1040.0, coolant_viscosity_cP=1.0,
    )
    report_water = check_turbulent_re(spec_water)
    report_eg = check_turbulent_re(spec_eg)
    assert report_eg.reynolds_number > report_water.reynolds_number, (
        "Higher density should produce higher Re (Re ∝ ρ)"
    )


# ---------------------------------------------------------------------------
# Test 11: Very low flow → laminar
# ---------------------------------------------------------------------------

def test_very_low_flow_laminar():
    """0.1 L/min in a 10mm channel → Re < 2300, laminar."""
    spec = _water_spec(10.0, 0.1)
    report = check_turbulent_re(spec)
    assert report.reynolds_number < _RE_LAMINAR_MAX, (
        f"Expected laminar Re, got {report.reynolds_number:.1f}"
    )
    assert report.flow_regime == "laminar"


# ---------------------------------------------------------------------------
# Test 12: Velocity calculation cross-check
# ---------------------------------------------------------------------------

def test_velocity_calculation():
    """v = Q/A cross-check for 10mm / 10 L/min."""
    spec = _water_spec(10.0, 10.0)
    report = check_turbulent_re(spec)
    D = 0.01
    Q = 10.0 / 60_000.0
    A = math.pi * (D / 2.0) ** 2
    expected_v = Q / A
    assert abs(report.velocity_m_per_s - expected_v) < 1e-6, (
        f"Expected v={expected_v:.6f}, got {report.velocity_m_per_s}"
    )


# ---------------------------------------------------------------------------
# Test 13: LLM tool valid call
# ---------------------------------------------------------------------------

def test_llm_tool_valid_fully_turbulent():
    """LLM tool for 10mm / 10 L/min → ok=True, fully_turbulent, Re>10000."""
    async def _run():
        return await _call_tool({
            "channel_diameter_mm": 10.0,
            "flow_rate_L_per_min": 10.0,
        })
    result = asyncio.run(_run())
    assert result.get("ok") is True
    assert result["flow_regime"] == "fully_turbulent"
    assert result["reynolds_number"] > _RE_FULLY_TURBULENT
    assert result["dittus_boelter_applicable"] is True


# ---------------------------------------------------------------------------
# Test 14: LLM tool — missing channel_diameter_mm → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_diameter():
    async def _run():
        return await _call_tool({"flow_rate_L_per_min": 10.0})
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 15: LLM tool — missing flow_rate_L_per_min → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_missing_flow_rate():
    async def _run():
        return await _call_tool({"channel_diameter_mm": 10.0})
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 16: LLM tool — negative diameter → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_negative_diameter():
    async def _run():
        return await _call_tool({
            "channel_diameter_mm": -5.0,
            "flow_rate_L_per_min": 10.0,
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 17: LLM tool — zero flow rate → BAD_ARGS
# ---------------------------------------------------------------------------

def test_llm_tool_zero_flow_rate():
    async def _run():
        return await _call_tool({
            "channel_diameter_mm": 10.0,
            "flow_rate_L_per_min": 0.0,
        })
    result = asyncio.run(_run())
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 18: CoolingFlowSpec — zero diameter → ValueError
# ---------------------------------------------------------------------------

def test_spec_zero_diameter_raises():
    with pytest.raises(ValueError, match="channel_diameter_mm"):
        CoolingFlowSpec(channel_diameter_mm=0.0, flow_rate_L_per_min=10.0)


# ---------------------------------------------------------------------------
# Test 19: CoolingFlowSpec — zero flow rate → ValueError
# ---------------------------------------------------------------------------

def test_spec_zero_flow_raises():
    with pytest.raises(ValueError, match="flow_rate_L_per_min"):
        CoolingFlowSpec(channel_diameter_mm=10.0, flow_rate_L_per_min=0.0)


# ---------------------------------------------------------------------------
# Test 20: CoolingFlowSpec — negative viscosity → ValueError
# ---------------------------------------------------------------------------

def test_spec_negative_viscosity_raises():
    with pytest.raises(ValueError, match="coolant_viscosity_cP"):
        CoolingFlowSpec(
            channel_diameter_mm=10.0,
            flow_rate_L_per_min=5.0,
            coolant_viscosity_cP=-1.0,
        )


# ---------------------------------------------------------------------------
# Test 21: Re exactly at 10000 boundary → fully_turbulent
# ---------------------------------------------------------------------------

def test_re_at_exactly_10000_is_fully_turbulent():
    """Re == 10000 (edge case) should be classified as fully_turbulent."""
    # Construct a spec where Re = 10000 exactly:
    # Re = ρ*v*D/μ; v = Re*μ/(ρ*D); Q = v*A = Re*μ*π*D/4 / ρ (m³/s)
    rho, mu_Pa_s = 1000.0, 1e-3
    D_mm = 10.0
    D_m = D_mm * 1e-3
    Q_m3_s = _RE_FULLY_TURBULENT * mu_Pa_s * math.pi * D_m / (4.0 * rho)
    Q_L_per_min = Q_m3_s * 60_000.0
    spec = _water_spec(D_mm, Q_L_per_min)
    report = check_turbulent_re(spec)
    # Re should be ≈ 10000 (floating-point)
    assert abs(report.reynolds_number - _RE_FULLY_TURBULENT) < 1.0, (
        f"Expected Re≈10000, got {report.reynolds_number}"
    )
    assert report.flow_regime == "fully_turbulent", (
        f"Expected fully_turbulent at Re=10000, got {report.flow_regime}"
    )
    assert report.dittus_boelter_applicable is True


# ---------------------------------------------------------------------------
# Test 22: Re exactly at 4000 boundary → turbulent (not transitional)
# ---------------------------------------------------------------------------

def test_re_at_4000_is_turbulent():
    """Re == 4000 (lower turbulent boundary) → regime=turbulent."""
    rho, mu_Pa_s = 1000.0, 1e-3
    D_mm = 10.0
    D_m = D_mm * 1e-3
    Q_m3_s = _RE_TURBULENT_MIN * mu_Pa_s * math.pi * D_m / (4.0 * rho)
    Q_L_per_min = Q_m3_s * 60_000.0
    spec = _water_spec(D_mm, Q_L_per_min)
    report = check_turbulent_re(spec)
    assert abs(report.reynolds_number - _RE_TURBULENT_MIN) < 1.0
    assert report.flow_regime == "turbulent", (
        f"Expected turbulent at Re=4000, got {report.flow_regime}"
    )


# ---------------------------------------------------------------------------
# Test 23: Re at 2300 boundary → transitional (not laminar)
# ---------------------------------------------------------------------------

def test_re_at_2300_is_transitional():
    """Re == 2300 (upper laminar boundary) → regime=transitional."""
    rho, mu_Pa_s = 1000.0, 1e-3
    D_mm = 10.0
    D_m = D_mm * 1e-3
    Q_m3_s = _RE_LAMINAR_MAX * mu_Pa_s * math.pi * D_m / (4.0 * rho)
    Q_L_per_min = Q_m3_s * 60_000.0
    spec = _water_spec(D_mm, Q_L_per_min)
    report = check_turbulent_re(spec)
    assert abs(report.reynolds_number - _RE_LAMINAR_MAX) < 1.0
    assert report.flow_regime == "transitional", (
        f"Expected transitional at Re=2300, got {report.flow_regime}"
    )


# ---------------------------------------------------------------------------
# Test 24: All regime strings are valid for a flow-rate sweep
# ---------------------------------------------------------------------------

def test_regime_strings_are_valid_for_sweep():
    """A sweep from 0.5–15 L/min produces only valid regime string values."""
    valid_regimes = {"laminar", "transitional", "turbulent", "fully_turbulent"}
    for q in [0.5, 1.0, 1.414, 2.0, 5.0, 10.0, 15.0]:
        spec = _water_spec(10.0, q)
        report = check_turbulent_re(spec)
        assert report.flow_regime in valid_regimes, (
            f"flow_rate={q} L/min → invalid regime string '{report.flow_regime}'"
        )
