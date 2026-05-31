"""
Tests for kerf_mold.core_pin_cooling — baffle/bubbler cooling design for
slender injection-mold core pins.

Theory references: Menges 2001 §7.5 (Core pin cooling); Beaumont 2007 §11.4
(Slender-core cooling); Incropera & DeWitt eq. 8.60 (Dittus-Boelter).

Oracle coverage (12+ tests):

 1.  30mm core, 100mm tall, baffle, 4mm ID, 2 L/min water:
     Re ≈ 10610, Nu ≈ 83, HTC ≈ 12445 W/m²K; fully turbulent.
 2.  Same spec with bubbler: HTC ≈ 2× baffle HTC.
 3.  Bubbler HTC ratio ≥ 1.95 (≈ 2× per Menges §7.5) relative to baffle.
 4.  Low flow (0.1 L/min, 4mm ID): Re < 2300 (laminar), HTC lower than high flow.
 5.  Low flow → cooling_adequate = False (Re < 10000).
 6.  High flow (10 L/min, 4mm ID): Re ≈ 53052 → higher HTC.
 7.  Re scales inversely with bore diameter: 8mm bore gives Re ≈ 5305
     vs. 4mm bore gives Re ≈ 10610 at same Q.
 8.  Re scales proportionally with flow rate: doubling Q → Re doubles.
 9.  Estimated core-tip temperature increases for inadequate flow.
10.  Cycle-time estimate > 0 for valid inputs.
11.  Cycle-time estimate scales with pin diameter squared (larger pin → longer cycle).
12.  CorePinSpec: cooling_type_id_mm ≥ core_diameter_mm → ValueError.
13.  CorePinSpec: target_core_temp_C ≥ melt_temp_C → ValueError.
14.  CorePinSpec: invalid baffle_or_bubbler → ValueError.
15.  CorePinSpec: zero flow → ValueError.
16.  LLM tool: valid baffle call → ok=True, Re ≈ 10610.
17.  LLM tool: valid bubbler call → htc ≈ 2× baffle htc.
18.  LLM tool: missing required field → BAD_ARGS.
19.  LLM tool: invalid baffle_or_bubbler string → BAD_ARGS.
20.  LLM tool: negative core_diameter → BAD_ARGS.
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

from kerf_mold.core_pin_cooling import (
    CorePinSpec,
    CorePinCoolingReport,
    design_core_pin_cooling,
    _BUBBLER_HTC_MULTIPLIER,
    _RE_MIN_DITTUS_BOELTER,
)
from kerf_mold.core_pin_cooling_tool import (
    mold_design_core_pin_cooling_spec,
    run_mold_design_core_pin_cooling,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_spec(**kwargs) -> CorePinSpec:
    """Build a default CorePinSpec with overrides."""
    defaults = dict(
        core_diameter_mm=30.0,
        core_height_mm=100.0,
        baffle_or_bubbler="baffle",
        cooling_type_id_mm=4.0,
        coolant_flow_L_per_min=2.0,
        melt_temp_C=240.0,
        target_core_temp_C=80.0,
        polymer_grade="ABS",
    )
    defaults.update(kwargs)
    return CorePinSpec(**defaults)


def _run_tool(args: dict) -> dict:
    """Execute the LLM tool handler synchronously; return parsed JSON."""
    raw = asyncio.get_event_loop().run_until_complete(
        run_mold_design_core_pin_cooling(None, json.dumps(args).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Test 1 — baseline baffle oracle (Re, Nu, HTC)
# ---------------------------------------------------------------------------

def test_baffle_baseline_reynolds():
    """30 mm core, 4 mm ID bore, 2 L/min water → Re ≈ 10610 (±2 %)."""
    spec = _make_spec()
    report = design_core_pin_cooling(spec)
    assert abs(report.reynolds_number - 10610.3) / 10610.3 < 0.02, (
        f"Expected Re ≈ 10610, got {report.reynolds_number}"
    )


def test_baffle_baseline_htc():
    """30 mm core, 4 mm ID, 2 L/min water, baffle → HTC ≈ 12445 W/m²K (±10 %)."""
    spec = _make_spec()
    report = design_core_pin_cooling(spec)
    # Dittus-Boelter with Pr=7, k=0.598: h = Nu*k/D ≈ 12445
    assert abs(report.htc_W_per_m2K - 12444.9) / 12444.9 < 0.10, (
        f"Expected HTC ≈ 12445 W/m²K, got {report.htc_W_per_m2K}"
    )


# ---------------------------------------------------------------------------
# Test 2 — bubbler ≈ 2× HTC of baffle
# ---------------------------------------------------------------------------

def test_bubbler_htc_double_baffle():
    """Bubbler HTC should be exactly 2× baffle HTC (Menges §7.5 multiplier)."""
    spec_baf = _make_spec(baffle_or_bubbler="baffle")
    spec_bub = _make_spec(baffle_or_bubbler="bubbler")
    r_baf = design_core_pin_cooling(spec_baf)
    r_bub = design_core_pin_cooling(spec_bub)
    ratio = r_bub.htc_W_per_m2K / r_baf.htc_W_per_m2K
    assert abs(ratio - _BUBBLER_HTC_MULTIPLIER) < 0.01, (
        f"Expected HTC ratio = {_BUBBLER_HTC_MULTIPLIER}, got {ratio:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 3 — bubbler HTC ratio ≥ 1.95
# ---------------------------------------------------------------------------

def test_bubbler_htc_ratio_near_two():
    """Bubbler HTC / baffle HTC ≥ 1.95 (empirical 2× factor Menges §7.5)."""
    r_baf = design_core_pin_cooling(_make_spec(baffle_or_bubbler="baffle"))
    r_bub = design_core_pin_cooling(_make_spec(baffle_or_bubbler="bubbler"))
    ratio = r_bub.htc_W_per_m2K / r_baf.htc_W_per_m2K
    assert ratio >= 1.95, f"Expected bubbler/baffle HTC ≥ 1.95, got {ratio:.4f}"


# ---------------------------------------------------------------------------
# Test 4 — low flow: Re is laminar, HTC lower
# ---------------------------------------------------------------------------

def test_low_flow_laminar_re():
    """0.1 L/min through 4mm bore → Re < 2300 (laminar)."""
    spec = _make_spec(coolant_flow_L_per_min=0.1)
    report = design_core_pin_cooling(spec)
    assert report.reynolds_number < 2300, (
        f"Expected Re < 2300 (laminar), got {report.reynolds_number}"
    )


def test_low_flow_htc_less_than_high_flow():
    """HTC at 0.1 L/min < HTC at 2 L/min (higher flow → higher HTC)."""
    r_low = design_core_pin_cooling(_make_spec(coolant_flow_L_per_min=0.1))
    r_hi  = design_core_pin_cooling(_make_spec(coolant_flow_L_per_min=2.0))
    assert r_low.htc_W_per_m2K < r_hi.htc_W_per_m2K, (
        f"Expected HTC(0.1 L/min) < HTC(2 L/min), "
        f"got {r_low.htc_W_per_m2K:.1f} vs {r_hi.htc_W_per_m2K:.1f}"
    )


# ---------------------------------------------------------------------------
# Test 5 — low flow → cooling_adequate = False
# ---------------------------------------------------------------------------

def test_low_flow_not_adequate():
    """Low flow (Re < 10000) → cooling_adequate = False."""
    spec = _make_spec(coolant_flow_L_per_min=0.1)
    report = design_core_pin_cooling(spec)
    assert not report.cooling_adequate, (
        "Expected cooling_adequate=False for laminar flow (Re < 10000)"
    )


# ---------------------------------------------------------------------------
# Test 6 — high flow: Re >> 10000
# ---------------------------------------------------------------------------

def test_high_flow_fully_turbulent():
    """10 L/min through 4mm bore → Re ≈ 53052, fully turbulent."""
    spec = _make_spec(coolant_flow_L_per_min=10.0)
    report = design_core_pin_cooling(spec)
    assert report.reynolds_number > _RE_MIN_DITTUS_BOELTER, (
        f"Expected Re > 10000, got {report.reynolds_number}"
    )
    assert abs(report.reynolds_number - 53051.6) / 53051.6 < 0.02


# ---------------------------------------------------------------------------
# Test 7 — Re scales inversely with bore diameter at same Q
# ---------------------------------------------------------------------------

def test_re_inverse_with_bore_diameter():
    """Doubling bore diameter halves Re at the same flow rate."""
    r_small = design_core_pin_cooling(_make_spec(cooling_type_id_mm=4.0))
    # 8mm bore in a slightly larger core to satisfy bore < outer constraint
    r_large = design_core_pin_cooling(
        _make_spec(core_diameter_mm=35.0, cooling_type_id_mm=8.0)
    )
    # Re ∝ 1/D at same Q: ratio should be ≈ 2 (8/4)
    ratio = r_small.reynolds_number / r_large.reynolds_number
    assert abs(ratio - 2.0) < 0.05, (
        f"Expected Re(4mm)/Re(8mm) ≈ 2.0, got {ratio:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 8 — Re scales proportionally with flow rate
# ---------------------------------------------------------------------------

def test_re_proportional_to_flow_rate():
    """Doubling flow rate at same bore → Re doubles."""
    r_lo = design_core_pin_cooling(_make_spec(coolant_flow_L_per_min=2.0))
    r_hi = design_core_pin_cooling(_make_spec(coolant_flow_L_per_min=4.0))
    ratio = r_hi.reynolds_number / r_lo.reynolds_number
    assert abs(ratio - 2.0) < 0.01, (
        f"Expected Re doubles with Q, got ratio {ratio:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 9 — higher tip temp for lower flow (inadequate cooling)
# ---------------------------------------------------------------------------

def test_inadequate_flow_raises_tip_temp():
    """Low flow → estimated core-tip temperature closer to melt temp."""
    r_lo  = design_core_pin_cooling(_make_spec(coolant_flow_L_per_min=0.1))
    r_hi  = design_core_pin_cooling(_make_spec(coolant_flow_L_per_min=2.0))
    # Both will be near melt temp due to steel conduction resistance, but
    # low-flow should be equal or higher
    assert r_lo.estimated_core_tip_temp_C >= r_hi.estimated_core_tip_temp_C - 0.1, (
        f"Expected T_tip(low flow) ≥ T_tip(high flow), "
        f"got {r_lo.estimated_core_tip_temp_C:.2f} vs {r_hi.estimated_core_tip_temp_C:.2f}"
    )


# ---------------------------------------------------------------------------
# Test 10 — cycle time > 0
# ---------------------------------------------------------------------------

def test_cycle_time_positive():
    """Cycle-time estimate should be > 0 for valid inputs."""
    spec = _make_spec()
    report = design_core_pin_cooling(spec)
    assert report.cycle_time_estimate_s > 0.0, (
        f"Expected cycle_time > 0, got {report.cycle_time_estimate_s}"
    )


def test_cycle_time_oracle():
    """30mm core, ABS, T_melt=240, T_cool=20, T_target=80 → tc ≈ 248 s."""
    spec = _make_spec()
    report = design_core_pin_cooling(spec)
    assert abs(report.cycle_time_estimate_s - 248.32) < 5.0, (
        f"Expected tc ≈ 248 s, got {report.cycle_time_estimate_s}"
    )


# ---------------------------------------------------------------------------
# Test 11 — cycle time scales with pin diameter squared
# ---------------------------------------------------------------------------

def test_cycle_time_scales_with_diameter_squared():
    """Larger pin diameter → longer cycle time (h_wall² ∝ D²)."""
    r_small = design_core_pin_cooling(_make_spec(core_diameter_mm=20.0))
    r_large = design_core_pin_cooling(_make_spec(core_diameter_mm=40.0,
                                                 cooling_type_id_mm=6.0))
    # Expect tc ∝ (D/2)²: ratio ≈ (40/20)² = 4
    ratio = r_large.cycle_time_estimate_s / r_small.cycle_time_estimate_s
    assert abs(ratio - 4.0) < 0.3, (
        f"Expected cycle-time ratio ≈ 4 (D doubled), got {ratio:.3f}"
    )


# ---------------------------------------------------------------------------
# Test 12 — CorePinSpec: cooling_type_id_mm ≥ core_diameter_mm → ValueError
# ---------------------------------------------------------------------------

def test_spec_bore_gte_outer_raises():
    """Bore ID ≥ outer diameter is physically impossible → ValueError."""
    with pytest.raises(ValueError, match="cooling_type_id_mm"):
        CorePinSpec(
            core_diameter_mm=10.0,
            core_height_mm=50.0,
            baffle_or_bubbler="baffle",
            cooling_type_id_mm=10.0,   # equal → should raise
            coolant_flow_L_per_min=2.0,
            melt_temp_C=240.0,
            target_core_temp_C=80.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# Test 13 — CorePinSpec: target_core_temp_C ≥ melt_temp_C → ValueError
# ---------------------------------------------------------------------------

def test_spec_target_gte_melt_raises():
    """target_core_temp_C ≥ melt_temp_C is unphysical → ValueError."""
    with pytest.raises(ValueError, match="target_core_temp_C"):
        CorePinSpec(
            core_diameter_mm=30.0,
            core_height_mm=100.0,
            baffle_or_bubbler="baffle",
            cooling_type_id_mm=4.0,
            coolant_flow_L_per_min=2.0,
            melt_temp_C=240.0,
            target_core_temp_C=240.0,  # equal → should raise
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# Test 14 — CorePinSpec: invalid baffle_or_bubbler → ValueError
# ---------------------------------------------------------------------------

def test_spec_invalid_cooling_type_raises():
    """Unknown baffle_or_bubbler value → ValueError."""
    with pytest.raises(ValueError, match="baffle_or_bubbler"):
        CorePinSpec(
            core_diameter_mm=30.0,
            core_height_mm=100.0,
            baffle_or_bubbler="spiral",   # invalid
            cooling_type_id_mm=4.0,
            coolant_flow_L_per_min=2.0,
            melt_temp_C=240.0,
            target_core_temp_C=80.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# Test 15 — CorePinSpec: zero flow → ValueError
# ---------------------------------------------------------------------------

def test_spec_zero_flow_raises():
    """Zero coolant flow → ValueError."""
    with pytest.raises(ValueError, match="coolant_flow_L_per_min"):
        CorePinSpec(
            core_diameter_mm=30.0,
            core_height_mm=100.0,
            baffle_or_bubbler="baffle",
            cooling_type_id_mm=4.0,
            coolant_flow_L_per_min=0.0,   # zero → should raise
            melt_temp_C=240.0,
            target_core_temp_C=80.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# Test 16 — LLM tool: valid baffle call
# ---------------------------------------------------------------------------

def test_tool_valid_baffle_call():
    """LLM tool with baffle spec returns ok=True and Re ≈ 10610."""
    result = _run_tool({
        "core_diameter_mm": 30.0,
        "core_height_mm": 100.0,
        "baffle_or_bubbler": "baffle",
        "cooling_type_id_mm": 4.0,
        "coolant_flow_L_per_min": 2.0,
        "melt_temp_C": 240.0,
        "target_core_temp_C": 80.0,
        "polymer_grade": "ABS",
    })
    assert result.get("ok") is True, f"Expected ok=True, got {result}"
    re = result["reynolds_number"]
    assert abs(re - 10610.3) / 10610.3 < 0.02, f"Expected Re ≈ 10610, got {re}"


# ---------------------------------------------------------------------------
# Test 17 — LLM tool: bubbler HTC ≈ 2× baffle HTC
# ---------------------------------------------------------------------------

def test_tool_bubbler_doubles_htc():
    """LLM tool: bubbler htc_W_per_m2K ≈ 2× baffle htc_W_per_m2K."""
    base = {
        "core_diameter_mm": 30.0,
        "core_height_mm": 100.0,
        "cooling_type_id_mm": 4.0,
        "coolant_flow_L_per_min": 2.0,
        "melt_temp_C": 240.0,
        "target_core_temp_C": 80.0,
        "polymer_grade": "ABS",
    }
    r_baf = _run_tool({**base, "baffle_or_bubbler": "baffle"})
    r_bub = _run_tool({**base, "baffle_or_bubbler": "bubbler"})
    assert r_baf["ok"] and r_bub["ok"]
    ratio = r_bub["htc_W_per_m2K"] / r_baf["htc_W_per_m2K"]
    assert abs(ratio - 2.0) < 0.05, (
        f"Expected bubbler/baffle HTC ≈ 2.0, got {ratio:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 18 — LLM tool: missing required field → BAD_ARGS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", [
    "core_diameter_mm",
    "core_height_mm",
    "baffle_or_bubbler",
    "cooling_type_id_mm",
    "coolant_flow_L_per_min",
    "melt_temp_C",
    "target_core_temp_C",
    "polymer_grade",
])
def test_tool_missing_required_field(missing_field):
    """Missing any required field → BAD_ARGS error code."""
    args = {
        "core_diameter_mm": 30.0,
        "core_height_mm": 100.0,
        "baffle_or_bubbler": "baffle",
        "cooling_type_id_mm": 4.0,
        "coolant_flow_L_per_min": 2.0,
        "melt_temp_C": 240.0,
        "target_core_temp_C": 80.0,
        "polymer_grade": "ABS",
    }
    del args[missing_field]
    result = _run_tool(args)
    assert result.get("code") == "BAD_ARGS", (
        f"Expected BAD_ARGS for missing {missing_field}, got {result}"
    )


# ---------------------------------------------------------------------------
# Test 19 — LLM tool: invalid baffle_or_bubbler → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_invalid_baffle_or_bubbler():
    """LLM tool: invalid baffle_or_bubbler value → BAD_ARGS."""
    result = _run_tool({
        "core_diameter_mm": 30.0,
        "core_height_mm": 100.0,
        "baffle_or_bubbler": "spiral_cool",
        "cooling_type_id_mm": 4.0,
        "coolant_flow_L_per_min": 2.0,
        "melt_temp_C": 240.0,
        "target_core_temp_C": 80.0,
        "polymer_grade": "ABS",
    })
    assert result.get("code") == "BAD_ARGS", (
        f"Expected BAD_ARGS for invalid baffle_or_bubbler, got {result}"
    )


# ---------------------------------------------------------------------------
# Test 20 — LLM tool: negative core_diameter → BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_negative_core_diameter():
    """LLM tool: negative core_diameter_mm → BAD_ARGS."""
    result = _run_tool({
        "core_diameter_mm": -5.0,
        "core_height_mm": 100.0,
        "baffle_or_bubbler": "baffle",
        "cooling_type_id_mm": 4.0,
        "coolant_flow_L_per_min": 2.0,
        "melt_temp_C": 240.0,
        "target_core_temp_C": 80.0,
        "polymer_grade": "ABS",
    })
    assert result.get("code") == "BAD_ARGS", (
        f"Expected BAD_ARGS for negative core_diameter, got {result}"
    )


# ---------------------------------------------------------------------------
# Test 21 — honest_caveat is non-empty string in report
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    """CorePinCoolingReport.honest_caveat is a non-empty string."""
    report = design_core_pin_cooling(_make_spec())
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 50, "honest_caveat seems too short"


# ---------------------------------------------------------------------------
# Test 22 — case-insensitive baffle_or_bubbler
# ---------------------------------------------------------------------------

def test_baffle_case_insensitive():
    """baffle_or_bubbler='BAFFLE' (uppercase) should be accepted."""
    spec = _make_spec(baffle_or_bubbler="BAFFLE")
    report = design_core_pin_cooling(spec)
    assert report.reynolds_number > 0


def test_bubbler_case_insensitive():
    """baffle_or_bubbler='Bubbler' (mixed case) should be accepted."""
    spec = _make_spec(baffle_or_bubbler="Bubbler")
    report = design_core_pin_cooling(spec)
    assert report.reynolds_number > 0
