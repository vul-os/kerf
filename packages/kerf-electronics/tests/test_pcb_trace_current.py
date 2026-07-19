"""
Hermetic tests for kerf_electronics.pcb_trace_current —
IPC-2221B simplified PCB trace maximum current calculator.

IPC-2221B Eq. 6-4:
  I [A] = k · ΔT^0.44 · A^0.725
  A [mil²] = trace_width_mils × (copper_oz × 1.37)
  k_external = 0.048, k_internal = 0.024

Test roster (21 tests):
  1.  10 mil × 1 oz, 10 °C, external — oracle cross-check
  2.  50 mil × 1 oz, 10 °C, external — oracle cross-check
  3.  Internal trace has exactly half the capacity of external (same geometry)
  4.  Higher temp rise → higher max current (monotonic)
  5.  Heavier copper → higher max current (monotonic): 0.5 oz < 1 oz < 2 oz < 3 oz
  6.  Wider trace → higher max current (monotonic)
  7.  External derate_factor == 1.0, internal derate_factor == 0.5
  8.  100 mil × 2 oz, 10 °C, external — large trace cross-check
  9.  cross_section_mils2 formula: width × (oz × 1.37)
  10. report has all required fields
  11. ValueError for trace_width_mils <= 0
  12. ValueError for copper_weight_oz <= 0
  13. ValueError for temp_rise_C <= 0
  14. ValueError for invalid location
  15. 0.5 oz copper accepted and returns lower current than 1 oz
  16. 3 oz copper returns higher current than 1 oz
  17. honest_caveat mentions IPC-2221 and IPC-2152
  18. formula_used string contains key=value info
  19. LLM tool handler happy path — external trace JSON
  20. LLM tool handler happy path — internal trace JSON
  21. LLM tool handler bad args — missing trace_width_mils
  22. LLM tool handler — malformed JSON
  23. PcbTraceSpec default values: temp_rise_C=10, location='external'
  24. Re-export via __init__.py works
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_electronics.pcb_trace_current import (
    PcbTraceSpec,
    PcbTraceCurrentReport,
    compute_pcb_trace_max_current,
    _K_EXTERNAL,
    _K_INTERNAL,
    _IPC_B,
    _IPC_C,
    _OZ_TO_MILS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_current(width_mils: float, oz: float, dT: float, location: str) -> float:
    """Reference implementation of IPC-2221B Eq. 6-4."""
    A = width_mils * (oz * _OZ_TO_MILS)
    k = _K_EXTERNAL if location == "external" else _K_INTERNAL
    return k * (dT ** _IPC_B) * (A ** _IPC_C)


def _run_tool(args_dict: dict) -> dict:
    """Helper to run the LLM tool handler synchronously."""
    from kerf_electronics.tools.pcb_trace_current import electronics_compute_pcb_trace_current
    raw = asyncio.run(
        electronics_compute_pcb_trace_current(None, json.dumps(args_dict).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Test 1: 10 mil × 1 oz, 10 °C, external — oracle cross-check
# ---------------------------------------------------------------------------

def test_10mil_1oz_10c_external_oracle():
    """10 mil × 1 oz, 10 °C, external — IPC-2221B oracle check."""
    spec = PcbTraceSpec(trace_width_mils=10.0, copper_weight_oz=1.0, temp_rise_C=10.0, location="external")
    report = compute_pcb_trace_max_current(spec)

    expected = _expected_current(10.0, 1.0, 10.0, "external")
    assert abs(report.max_current_A - expected) < 1e-4, (
        f"Expected ~{expected:.4f} A, got {report.max_current_A:.4f} A"
    )
    # The IPC-2221B formula for 10 mil × 1 oz at 10 °C gives ~0.88 A.
    # This is in the 0.7–1.0 A range for a narrow signal trace.
    assert 0.7 <= report.max_current_A <= 1.1, (
        f"10 mil × 1 oz, 10 °C, external: expected 0.7–1.1 A, got {report.max_current_A:.4f} A"
    )


# ---------------------------------------------------------------------------
# Test 2: 50 mil × 1 oz, 10 °C, external — oracle cross-check
# ---------------------------------------------------------------------------

def test_50mil_1oz_10c_external_oracle():
    """50 mil × 1 oz, 10 °C, external — IPC-2221B oracle check."""
    spec = PcbTraceSpec(trace_width_mils=50.0, copper_weight_oz=1.0, temp_rise_C=10.0, location="external")
    report = compute_pcb_trace_max_current(spec)

    expected = _expected_current(50.0, 1.0, 10.0, "external")
    assert abs(report.max_current_A - expected) < 1e-4, (
        f"Expected ~{expected:.4f} A, got {report.max_current_A:.4f} A"
    )
    # 50 mil × 1 oz, 10 °C external: IPC-2221B gives ~2.8 A.
    # Wider tolerance range: 2.5–3.5 A.
    assert 2.5 <= report.max_current_A <= 3.5, (
        f"50 mil × 1 oz, 10 °C, external: expected 2.5–3.5 A, got {report.max_current_A:.4f} A"
    )


# ---------------------------------------------------------------------------
# Test 3: Internal trace has exactly half the capacity of external
# ---------------------------------------------------------------------------

def test_internal_is_half_of_external():
    """Internal traces have exactly half the max current of external traces."""
    spec_ext = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0, temp_rise_C=10.0, location="external")
    spec_int = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0, temp_rise_C=10.0, location="internal")

    report_ext = compute_pcb_trace_max_current(spec_ext)
    report_int = compute_pcb_trace_max_current(spec_int)

    ratio = report_int.max_current_A / report_ext.max_current_A
    assert abs(ratio - 0.5) < 1e-9, (
        f"Internal/external ratio expected 0.5, got {ratio:.10f}"
    )


# ---------------------------------------------------------------------------
# Test 4: Higher temp rise → higher current (monotonic)
# ---------------------------------------------------------------------------

def test_higher_temp_rise_gives_higher_current():
    """Temperature rise ↑ → max current ↑ (monotonic)."""
    width = 20.0
    oz = 1.0
    currents = [
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=width, copper_weight_oz=oz, temp_rise_C=dT, location="external")
        ).max_current_A
        for dT in [5.0, 10.0, 20.0, 30.0]
    ]
    for i in range(len(currents) - 1):
        assert currents[i] < currents[i + 1], (
            f"Current should increase with temp_rise_C; got {currents}"
        )


# ---------------------------------------------------------------------------
# Test 5: Heavier copper → higher current (monotonic)
# ---------------------------------------------------------------------------

def test_heavier_copper_gives_higher_current():
    """Copper weight ↑ → max current ↑ (monotonic: 0.5 < 1 < 2 < 3 oz)."""
    width = 20.0
    dt = 10.0
    currents = [
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=width, copper_weight_oz=oz, temp_rise_C=dt, location="external")
        ).max_current_A
        for oz in [0.5, 1.0, 2.0, 3.0]
    ]
    for i in range(len(currents) - 1):
        assert currents[i] < currents[i + 1], (
            f"Current should increase with copper_weight_oz; got {currents}"
        )


# ---------------------------------------------------------------------------
# Test 6: Wider trace → higher current (monotonic)
# ---------------------------------------------------------------------------

def test_wider_trace_gives_higher_current():
    """Trace width ↑ → max current ↑ (monotonic)."""
    oz = 1.0
    dt = 10.0
    currents = [
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=w, copper_weight_oz=oz, temp_rise_C=dt, location="external")
        ).max_current_A
        for w in [5.0, 10.0, 20.0, 50.0, 100.0]
    ]
    for i in range(len(currents) - 1):
        assert currents[i] < currents[i + 1], (
            f"Current should increase with trace_width_mils; got {currents}"
        )


# ---------------------------------------------------------------------------
# Test 7: derate_factor values
# ---------------------------------------------------------------------------

def test_derate_factor_external_is_one():
    """External traces have derate_factor == 1.0."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0, location="external")
    report = compute_pcb_trace_max_current(spec)
    assert report.derate_factor == 1.0


def test_derate_factor_internal_is_half():
    """Internal traces have derate_factor == 0.5."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0, location="internal")
    report = compute_pcb_trace_max_current(spec)
    assert report.derate_factor == 0.5


# ---------------------------------------------------------------------------
# Test 8: 100 mil × 2 oz, 10 °C, external — large trace
# ---------------------------------------------------------------------------

def test_100mil_2oz_10c_external():
    """100 mil × 2 oz, 10 °C, external — large power-trace oracle."""
    spec = PcbTraceSpec(trace_width_mils=100.0, copper_weight_oz=2.0, temp_rise_C=10.0, location="external")
    report = compute_pcb_trace_max_current(spec)

    expected = _expected_current(100.0, 2.0, 10.0, "external")
    assert abs(report.max_current_A - expected) < 1e-4
    # A 100 mil × 2 oz trace should carry ≥ 5 A comfortably
    assert report.max_current_A >= 5.0, (
        f"100 mil × 2 oz, 10 °C: expected ≥ 5 A, got {report.max_current_A:.4f} A"
    )


# ---------------------------------------------------------------------------
# Test 9: cross_section_mils2 formula
# ---------------------------------------------------------------------------

def test_cross_section_formula():
    """cross_section_mils2 == trace_width_mils × (copper_oz × 1.37)."""
    w = 25.0
    oz = 2.0
    spec = PcbTraceSpec(trace_width_mils=w, copper_weight_oz=oz)
    report = compute_pcb_trace_max_current(spec)

    expected_area = w * (oz * _OZ_TO_MILS)
    assert abs(report.cross_section_mils2 - expected_area) < 1e-3, (
        f"Expected area {expected_area:.4f} mil², got {report.cross_section_mils2:.4f} mil²"
    )


# ---------------------------------------------------------------------------
# Test 10: report has all required fields
# ---------------------------------------------------------------------------

def test_report_fields_present():
    """PcbTraceCurrentReport has all documented fields with correct types."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0)
    report = compute_pcb_trace_max_current(spec)

    assert isinstance(report, PcbTraceCurrentReport)
    assert isinstance(report.max_current_A, float)
    assert isinstance(report.cross_section_mils2, float)
    assert isinstance(report.formula_used, str)
    assert isinstance(report.derate_factor, float)
    assert isinstance(report.honest_caveat, str)

    assert report.max_current_A > 0
    assert report.cross_section_mils2 > 0
    assert len(report.formula_used) > 0
    assert len(report.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 11–14: ValueError for invalid inputs
# ---------------------------------------------------------------------------

def test_error_zero_trace_width():
    """ValueError raised for trace_width_mils <= 0."""
    with pytest.raises(ValueError, match="trace_width_mils"):
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=0.0, copper_weight_oz=1.0)
        )


def test_error_negative_trace_width():
    """ValueError raised for negative trace_width_mils."""
    with pytest.raises(ValueError, match="trace_width_mils"):
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=-5.0, copper_weight_oz=1.0)
        )


def test_error_zero_copper_weight():
    """ValueError raised for copper_weight_oz <= 0."""
    with pytest.raises(ValueError, match="copper_weight_oz"):
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=10.0, copper_weight_oz=0.0)
        )


def test_error_zero_temp_rise():
    """ValueError raised for temp_rise_C <= 0."""
    with pytest.raises(ValueError, match="temp_rise_C"):
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=10.0, copper_weight_oz=1.0, temp_rise_C=0.0)
        )


def test_error_invalid_location():
    """ValueError raised for unrecognised location string."""
    with pytest.raises(ValueError, match="location"):
        compute_pcb_trace_max_current(
            PcbTraceSpec(trace_width_mils=10.0, copper_weight_oz=1.0, location="buried")
        )


# ---------------------------------------------------------------------------
# Test 15–16: Copper weight range acceptance
# ---------------------------------------------------------------------------

def test_half_oz_lower_than_1oz():
    """0.5 oz copper gives lower current than 1.0 oz (same geometry)."""
    r_half = compute_pcb_trace_max_current(
        PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=0.5)
    )
    r_one = compute_pcb_trace_max_current(
        PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0)
    )
    assert r_half.max_current_A < r_one.max_current_A


def test_3oz_higher_than_1oz():
    """3.0 oz copper gives higher current than 1.0 oz (same geometry)."""
    r_three = compute_pcb_trace_max_current(
        PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=3.0)
    )
    r_one = compute_pcb_trace_max_current(
        PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0)
    )
    assert r_three.max_current_A > r_one.max_current_A


# ---------------------------------------------------------------------------
# Test 17: honest_caveat content
# ---------------------------------------------------------------------------

def test_honest_caveat_mentions_standards():
    """honest_caveat mentions IPC-2221 and IPC-2152."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0)
    report = compute_pcb_trace_max_current(spec)
    assert "IPC-2221" in report.honest_caveat, "Caveat should mention IPC-2221"
    assert "IPC-2152" in report.honest_caveat, "Caveat should mention IPC-2152"


# ---------------------------------------------------------------------------
# Test 18: formula_used string content
# ---------------------------------------------------------------------------

def test_formula_used_string():
    """formula_used contains k, ΔT, and area values."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0, temp_rise_C=10.0, location="external")
    report = compute_pcb_trace_max_current(spec)
    assert "0.048" in report.formula_used, "formula_used should contain k=0.048 for external"
    assert "10.0" in report.formula_used, "formula_used should contain ΔT=10"
    assert "external" in report.formula_used


def test_formula_used_internal():
    """formula_used contains k=0.024 for internal traces."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0, temp_rise_C=10.0, location="internal")
    report = compute_pcb_trace_max_current(spec)
    assert "0.024" in report.formula_used, "formula_used should contain k=0.024 for internal"


# ---------------------------------------------------------------------------
# Test 19–22: LLM tool handler
# ---------------------------------------------------------------------------

def test_tool_handler_external_happy_path():
    """LLM tool handler returns ok=True for valid external trace args."""
    result = _run_tool({
        "trace_width_mils": 20.0,
        "copper_weight_oz": 1.0,
        "temp_rise_C": 10.0,
        "location": "external",
    })
    assert result.get("ok") is True
    assert result["max_current_A"] > 0
    assert "cross_section_mils2" in result
    assert "honest_caveat" in result
    assert "IPC-2221" in result["honest_caveat"]


def test_tool_handler_internal_happy_path():
    """LLM tool handler returns ok=True for valid internal trace args."""
    result = _run_tool({
        "trace_width_mils": 20.0,
        "copper_weight_oz": 1.0,
        "temp_rise_C": 10.0,
        "location": "internal",
    })
    assert result.get("ok") is True
    # Internal should be half of external
    ext_result = _run_tool({
        "trace_width_mils": 20.0,
        "copper_weight_oz": 1.0,
        "temp_rise_C": 10.0,
        "location": "external",
    })
    ratio = result["max_current_A"] / ext_result["max_current_A"]
    assert abs(ratio - 0.5) < 1e-6


def test_tool_handler_missing_required_param():
    """LLM tool handler returns error for missing trace_width_mils."""
    result = _run_tool({
        "copper_weight_oz": 1.0,
        "temp_rise_C": 10.0,
    })
    # Should fail — trace_width_mils is required
    # Either ok=False or an error/code key
    is_error = (
        result.get("ok") is False
        or "error" in result
        or result.get("code") is not None
    )
    assert is_error, f"Expected error for missing trace_width_mils, got: {result}"


def test_tool_handler_malformed_json():
    """LLM tool handler returns error for malformed JSON."""
    from kerf_electronics.tools.pcb_trace_current import electronics_compute_pcb_trace_current
    raw = asyncio.run(
        electronics_compute_pcb_trace_current(None, b"not valid json{{")
    )
    result = json.loads(raw)
    assert "error" in result or result.get("ok") is False


# ---------------------------------------------------------------------------
# Test 23: PcbTraceSpec default values
# ---------------------------------------------------------------------------

def test_pcb_trace_spec_defaults():
    """PcbTraceSpec defaults: temp_rise_C=10.0, location='external'."""
    spec = PcbTraceSpec(trace_width_mils=20.0, copper_weight_oz=1.0)
    assert spec.temp_rise_C == 10.0
    assert spec.location == "external"


# ---------------------------------------------------------------------------
# Test 24: Re-export via __init__.py
# ---------------------------------------------------------------------------

def test_init_reexport():
    """PcbTraceSpec, PcbTraceCurrentReport, compute_pcb_trace_max_current accessible via package __init__."""
    from kerf_electronics import (
        PcbTraceSpec as PS,
        PcbTraceCurrentReport as PCR,
        compute_pcb_trace_max_current as compute,
    )
    spec = PS(trace_width_mils=10.0, copper_weight_oz=1.0)
    report = compute(spec)
    assert isinstance(report, PCR)
    assert report.max_current_A > 0
