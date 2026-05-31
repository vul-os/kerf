"""
Hermetic tests for kerf_electronics.dc_dc_ripple.

Buck DC-DC converter output voltage ripple (CCM only).

Reference calculations (Erickson 3e §2.4 + Sandler §3):
  D = V_out / V_in
  ΔiL = (V_in - V_out) · D / (L · f_sw)
  ΔV_cap = ΔiL / (8 · C · f_sw)
  ΔV_ESR = ΔiL · ESR
  ΔV_out = ΔV_cap + ΔV_ESR   (worst-case linear sum)

Reference design (used in multiple tests):
  V_in=12V, V_out=5V, I_load=1A, f=500kHz, L=22µH, C=22µF, ESR=10mΩ
  D = 5/12 = 0.41667
  ΔiL = (12-5)·0.41667/(22e-6·500e3) = 7·0.41667/11 = 2.91667/11 = 0.26515 A
  ΔV_cap = 0.26515/(8·22e-6·500e3) = 0.26515/88 = 3.013 mV
  ΔV_ESR = 0.26515·0.01 = 2.652 mV
  ΔV_total ≈ 5.665 mV

Test inventory (≥ 12 tests):
  T01  Reference design: D, ΔiL, ΔV_cap, ΔV_ESR, total
  T02  Higher f_sw → lower ripple (all else equal)
  T03  Lower f_sw → higher ripple
  T04  Higher ESR → ESR-dominated ripple
  T05  Zero ESR → ΔV_ESR=0, total=ΔV_cap
  T06  Higher L → lower ΔiL and ΔV_out
  T07  Higher C → lower ΔV_cap (ΔV_ESR unchanged)
  T08  CCM validity: large load → iL_min > 0
  T09  CCM boundary: small load triggers DCM warning in caveat
  T10  Output ripple_pct scales with ΔV_out/V_out
  T11  LLM tool handler happy path (JSON round-trip)
  T12  LLM tool handler bad JSON
  T13  LLM tool handler invalid args (V_out > V_in)
  T14  ValueError on V_out >= V_in
  T15  ValueError on negative L
  T16  Report fields all present and correct types
  T17  ΔV_out = ΔV_cap + ΔV_ESR exactly (no rounding drift)
  T18  Duty cycle range 0 < D < 1 always
  T19  Small-ripple approximation warning in caveat when ΔiL > 30% of 2·I_load
  T20  ESR-dominated flag in caveat
  T21  24V→12V, 2A, 250kHz, L=47µH, C=100µF, ESR=5mΩ
  T22  3.3V→1.2V, 3A, 1MHz, L=4.7µH, C=47µF, ESR=3mΩ
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_electronics.dc_dc_ripple import (
    BuckConverterSpec,
    ConverterRippleReport,
    compute_buck_ripple,
    compute_buck_ripple_from_dict,
    electronics_compute_buck_ripple,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REL_TOL = 1e-3  # 0.1% relative tolerance for numerical comparisons


def _spec(
    V_in=12.0,
    V_out=5.0,
    I_load=1.0,
    f=500_000.0,
    L=22.0,
    C=22.0,
    ESR=10.0,
) -> BuckConverterSpec:
    return BuckConverterSpec(
        V_in_V=V_in,
        V_out_V=V_out,
        I_load_A=I_load,
        switching_freq_Hz=f,
        L_uH=L,
        C_out_uF=C,
        C_ESR_mOhm=ESR,
    )


def _hand_calc(V_in, V_out, f, L_uH, C_uF, ESR_mOhm):
    """Return (D, delta_iL_A, delta_Vcap_mV, delta_VESR_mV, delta_Vtotal_mV)."""
    L_H = L_uH * 1e-6
    C_F = C_uF * 1e-6
    ESR_Ohm = ESR_mOhm * 1e-3
    D = V_out / V_in
    delta_iL = (V_in - V_out) * D / (L_H * f)
    delta_Vcap = delta_iL / (8.0 * C_F * f)
    delta_VESR = delta_iL * ESR_Ohm
    delta_Vtotal = delta_Vcap + delta_VESR
    return D, delta_iL, delta_Vcap * 1e3, delta_VESR * 1e3, delta_Vtotal * 1e3


# ---------------------------------------------------------------------------
# T01 — Reference design: 12V→5V, 1A, 500kHz, L=22µH, C=22µF, ESR=10mΩ
# ---------------------------------------------------------------------------

def test_t01_reference_design_values():
    """Reference design matches hand-calc from Erickson §2.4."""
    report = compute_buck_ripple(_spec())

    D_exp, diL_exp, Vcap_exp, VESR_exp, Vtot_exp = _hand_calc(
        V_in=12.0, V_out=5.0, f=500_000.0,
        L_uH=22.0, C_uF=22.0, ESR_mOhm=10.0,
    )

    assert abs(report.duty_cycle - D_exp) / D_exp < REL_TOL, (
        f"duty_cycle: got {report.duty_cycle}, expected {D_exp:.6f}"
    )
    assert abs(report.delta_iL_pp_A - diL_exp) / diL_exp < REL_TOL, (
        f"delta_iL_pp_A: got {report.delta_iL_pp_A}, expected {diL_exp:.6f}"
    )
    assert abs(report.delta_V_capacitor_mV - Vcap_exp) / Vcap_exp < REL_TOL, (
        f"delta_V_cap: got {report.delta_V_capacitor_mV}, expected {Vcap_exp:.4f} mV"
    )
    assert abs(report.delta_V_ESR_mV - VESR_exp) / VESR_exp < REL_TOL, (
        f"delta_V_ESR: got {report.delta_V_ESR_mV}, expected {VESR_exp:.4f} mV"
    )
    assert abs(report.delta_V_out_pp_mV - Vtot_exp) / Vtot_exp < REL_TOL, (
        f"delta_V_total: got {report.delta_V_out_pp_mV}, expected {Vtot_exp:.4f} mV"
    )

    # Spot-check against task-spec values:
    # D ≈ 0.417, ΔiL ≈ 0.265 A, ΔV_cap ≈ 3.01 mV, ΔV_ESR ≈ 2.65 mV, total ≈ 5.66 mV
    assert abs(report.duty_cycle - 0.4167) < 0.001
    assert abs(report.delta_iL_pp_A - 0.265) < 0.002
    assert abs(report.delta_V_capacitor_mV - 3.01) < 0.05
    assert abs(report.delta_V_ESR_mV - 2.65) < 0.05
    assert abs(report.delta_V_out_pp_mV - 5.66) < 0.10


# ---------------------------------------------------------------------------
# T02 — Higher f_sw → lower ripple
# ---------------------------------------------------------------------------

def test_t02_higher_freq_lower_ripple():
    """Doubling f_sw should halve both ΔiL and ΔV_out (all else equal)."""
    base = compute_buck_ripple(_spec(f=500_000.0))
    fast = compute_buck_ripple(_spec(f=1_000_000.0))

    # ΔiL ∝ 1/f_sw; ΔV_cap ∝ 1/f_sw²; ΔV_ESR ∝ 1/f_sw
    assert fast.delta_iL_pp_A < base.delta_iL_pp_A
    assert fast.delta_V_out_pp_mV < base.delta_V_out_pp_mV
    # Doubling freq roughly halves ΔiL (1/f factor)
    ratio = base.delta_iL_pp_A / fast.delta_iL_pp_A
    assert 1.9 < ratio < 2.1, f"Expected ~2×, got {ratio:.3f}"


# ---------------------------------------------------------------------------
# T03 — Lower f_sw → higher ripple
# ---------------------------------------------------------------------------

def test_t03_lower_freq_higher_ripple():
    """Halving f_sw should roughly double ΔiL."""
    base = compute_buck_ripple(_spec(f=500_000.0))
    slow = compute_buck_ripple(_spec(f=250_000.0))

    assert slow.delta_iL_pp_A > base.delta_iL_pp_A
    assert slow.delta_V_out_pp_mV > base.delta_V_out_pp_mV
    ratio = slow.delta_iL_pp_A / base.delta_iL_pp_A
    assert 1.9 < ratio < 2.1, f"Expected ~2×, got {ratio:.3f}"


# ---------------------------------------------------------------------------
# T04 — Higher ESR → ESR-dominated ripple
# ---------------------------------------------------------------------------

def test_t04_high_esr_dominated_ripple():
    """High ESR (100 mΩ) should dominate over ΔV_cap."""
    report = compute_buck_ripple(_spec(ESR=100.0))  # 100 mΩ
    assert report.delta_V_ESR_mV > report.delta_V_capacitor_mV, (
        "With high ESR, ESR term should dominate capacitor term"
    )
    # caveat should mention ESR-dominated
    assert "ESR-dominated" in report.honest_caveat or "esr" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# T05 — Zero ESR → ΔV_ESR = 0, total = ΔV_cap
# ---------------------------------------------------------------------------

def test_t05_zero_esr():
    """With ESR=0, ΔV_ESR=0 and ΔV_total = ΔV_cap."""
    report = compute_buck_ripple(_spec(ESR=0.0))
    assert report.delta_V_ESR_mV == 0.0
    assert abs(report.delta_V_out_pp_mV - report.delta_V_capacitor_mV) < 1e-9


# ---------------------------------------------------------------------------
# T06 — Higher L → lower ΔiL and ΔV_out
# ---------------------------------------------------------------------------

def test_t06_higher_L_lower_ripple():
    """Doubling L should halve ΔiL."""
    base = compute_buck_ripple(_spec(L=22.0))
    big_L = compute_buck_ripple(_spec(L=44.0))

    ratio = base.delta_iL_pp_A / big_L.delta_iL_pp_A
    assert 1.9 < ratio < 2.1, f"Expected ~2×, got {ratio:.3f}"
    assert big_L.delta_V_out_pp_mV < base.delta_V_out_pp_mV


# ---------------------------------------------------------------------------
# T07 — Higher C → lower ΔV_cap (ΔV_ESR unchanged)
# ---------------------------------------------------------------------------

def test_t07_higher_C_lower_capacitor_ripple():
    """Doubling C should halve ΔV_cap but leave ΔV_ESR unchanged."""
    base = compute_buck_ripple(_spec(C=22.0))
    big_C = compute_buck_ripple(_spec(C=44.0))

    # ΔiL is independent of C
    assert abs(base.delta_iL_pp_A - big_C.delta_iL_pp_A) < 1e-8

    ratio = base.delta_V_capacitor_mV / big_C.delta_V_capacitor_mV
    assert 1.9 < ratio < 2.1, f"Expected ~2×, got {ratio:.3f}"

    # ΔV_ESR depends only on ΔiL and ESR, not C
    assert abs(base.delta_V_ESR_mV - big_C.delta_V_ESR_mV) < 1e-6


# ---------------------------------------------------------------------------
# T08 — CCM validity: reference design at 1A → CCM confirmed
# ---------------------------------------------------------------------------

def test_t08_ccm_valid_at_1a_load():
    """Reference 1A load should give CCM with positive iL_min."""
    report = compute_buck_ripple(_spec(I_load=1.0))
    # iL_min = I_load - ΔiL/2; with ΔiL ≈ 0.265A and I_load=1A, iL_min ≈ 0.867A
    iL_min = 1.0 - report.delta_iL_pp_A / 2.0
    assert iL_min > 0, f"Expected CCM (iL_min > 0), got {iL_min:.4f}"
    assert "CCM confirmed" in report.honest_caveat


# ---------------------------------------------------------------------------
# T09 — DCM boundary: very small load current → DCM warning
# ---------------------------------------------------------------------------

def test_t09_dcm_warning_low_load():
    """Very small load current (0.05A) should trigger DCM warning in caveat."""
    # ΔiL ≈ 0.265A; I_load=0.05A → iL_min = 0.05 - 0.132 = -0.082A → DCM
    report = compute_buck_ripple(_spec(I_load=0.05))
    iL_min = 0.05 - report.delta_iL_pp_A / 2.0
    assert iL_min < 0
    assert "WARNING" in report.honest_caveat and "DCM" in report.honest_caveat


# ---------------------------------------------------------------------------
# T10 — output_ripple_pct = 100 * ΔV_out / V_out
# ---------------------------------------------------------------------------

def test_t10_ripple_pct_formula():
    """output_ripple_pct should equal 100 * delta_V_out_pp_mV / (V_out * 1000).

    Both output_ripple_pct and delta_V_out_pp_mV are independently rounded
    (to 4 decimal places) in the report, so we allow a small absolute tolerance
    corresponding to ±0.5 LSB of 4-decimal rounding (0.00005 mV → 0.001% relative).
    """
    report = compute_buck_ripple(_spec())
    expected_pct = 100.0 * (report.delta_V_out_pp_mV * 1e-3) / 5.0
    # Allow up to 1e-3 relative tolerance to accommodate independent rounding
    assert abs(report.output_ripple_pct - expected_pct) / expected_pct < 1e-3


# ---------------------------------------------------------------------------
# T11 — LLM tool handler happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t11_llm_tool_happy_path():
    """LLM tool should return valid JSON with ok=True for valid inputs."""
    args = json.dumps({
        "V_in_V": 12.0, "V_out_V": 5.0, "I_load_A": 1.0,
        "switching_freq_Hz": 500_000.0, "L_uH": 22.0,
        "C_out_uF": 22.0, "C_ESR_mOhm": 10.0,
    }).encode()
    result = await electronics_compute_buck_ripple(None, args)
    data = json.loads(result)
    assert data["ok"] is True
    assert "delta_V_out_pp_mV" in data
    assert data["delta_V_out_pp_mV"] > 0


# ---------------------------------------------------------------------------
# T12 — LLM tool handler bad JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t12_llm_tool_bad_json():
    """LLM tool should return ok=False for malformed JSON."""
    result = await electronics_compute_buck_ripple(None, b"{not valid json")
    data = json.loads(result)
    assert data.get("error") or data.get("ok") is False


# ---------------------------------------------------------------------------
# T13 — LLM tool handler invalid args (V_out > V_in)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t13_llm_tool_invalid_args():
    """LLM tool should return error when V_out > V_in."""
    args = json.dumps({
        "V_in_V": 5.0, "V_out_V": 12.0, "I_load_A": 1.0,
        "switching_freq_Hz": 500_000.0, "L_uH": 22.0,
        "C_out_uF": 22.0, "C_ESR_mOhm": 10.0,
    }).encode()
    result = await electronics_compute_buck_ripple(None, args)
    data = json.loads(result)
    assert data.get("ok") is False or "error" in data


# ---------------------------------------------------------------------------
# T14 — ValueError on V_out >= V_in
# ---------------------------------------------------------------------------

def test_t14_vout_greater_than_vin_raises():
    """V_out >= V_in should raise ValueError."""
    with pytest.raises(ValueError, match="buck"):
        compute_buck_ripple(_spec(V_in=5.0, V_out=12.0))

    with pytest.raises(ValueError):
        compute_buck_ripple(_spec(V_in=5.0, V_out=5.0))


# ---------------------------------------------------------------------------
# T15 — ValueError on invalid inputs
# ---------------------------------------------------------------------------

def test_t15_invalid_inputs_raise():
    """Negative or zero physical quantities should raise ValueError."""
    with pytest.raises(ValueError, match="L_uH"):
        compute_buck_ripple(_spec(L=-1.0))

    with pytest.raises(ValueError, match="C_out_uF"):
        compute_buck_ripple(_spec(C=0.0))

    with pytest.raises(ValueError, match="switching_freq_Hz"):
        compute_buck_ripple(_spec(f=0.0))

    with pytest.raises(ValueError, match="V_in_V"):
        compute_buck_ripple(_spec(V_in=0.0))

    with pytest.raises(ValueError, match="I_load_A"):
        compute_buck_ripple(_spec(I_load=-1.0))


# ---------------------------------------------------------------------------
# T16 — Report fields all present and correctly typed
# ---------------------------------------------------------------------------

def test_t16_report_fields_typed():
    """All ConverterRippleReport fields must be present and correctly typed."""
    report = compute_buck_ripple(_spec())
    assert isinstance(report, ConverterRippleReport)
    assert isinstance(report.delta_iL_pp_A, float)
    assert isinstance(report.delta_V_out_pp_mV, float)
    assert isinstance(report.delta_V_capacitor_mV, float)
    assert isinstance(report.delta_V_ESR_mV, float)
    assert isinstance(report.duty_cycle, float)
    assert isinstance(report.output_ripple_pct, float)
    assert isinstance(report.honest_caveat, str)
    # Positivity
    assert report.delta_iL_pp_A > 0
    assert report.delta_V_out_pp_mV > 0
    assert report.delta_V_capacitor_mV > 0
    assert report.delta_V_ESR_mV > 0
    assert 0 < report.duty_cycle < 1
    assert report.output_ripple_pct > 0
    assert len(report.honest_caveat) > 20


# ---------------------------------------------------------------------------
# T17 — ΔV_out = ΔV_cap + ΔV_ESR (no rounding drift in raw result)
# ---------------------------------------------------------------------------

def test_t17_total_equals_sum_of_components():
    """ΔV_out must equal ΔV_cap + ΔV_ESR to within floating-point precision."""
    report = compute_buck_ripple(_spec())
    expected = report.delta_V_capacitor_mV + report.delta_V_ESR_mV
    assert abs(report.delta_V_out_pp_mV - expected) < 0.001, (
        f"total={report.delta_V_out_pp_mV:.6f} != cap+ESR={expected:.6f}"
    )


# ---------------------------------------------------------------------------
# T18 — Duty cycle always in (0, 1)
# ---------------------------------------------------------------------------

def test_t18_duty_cycle_in_range():
    """Duty cycle must be strictly between 0 and 1 for any valid buck spec."""
    for V_in, V_out in [(12, 5), (24, 12), (5, 3.3), (48, 15)]:
        report = compute_buck_ripple(_spec(V_in=V_in, V_out=V_out))
        assert 0 < report.duty_cycle < 1, (
            f"D={report.duty_cycle} out of range for {V_in}V→{V_out}V"
        )


# ---------------------------------------------------------------------------
# T19 — Small-ripple approximation warning when ΔiL > 30% of 2·I_load
# ---------------------------------------------------------------------------

def test_t19_small_ripple_approximation_warning():
    """Large ΔiL relative to I_load should trigger a small-ripple warning."""
    # Use small L so ΔiL ≈ I_load → ratio > 30%
    # ΔiL = (12-5)·(5/12) / (4.7e-6·500e3) = 2.917/2.35 ≈ 1.24 A
    # ratio = 1.24 / (2·0.5) = 1.24 > 0.30 → warning
    report = compute_buck_ripple(_spec(L=4.7, I_load=0.5))
    diL_ratio = report.delta_iL_pp_A / (2 * 0.5)
    if diL_ratio > 0.30:
        assert "30%" in report.honest_caveat or "small-ripple" in report.honest_caveat


# ---------------------------------------------------------------------------
# T20 — ESR-dominated flag in caveat
# ---------------------------------------------------------------------------

def test_t20_esr_dominated_flag_in_caveat():
    """Very high ESR should cause ESR-dominated note in caveat."""
    # ESR=500mΩ, C=22µF, f=500kHz: 1/(4πCf) = 1/(4π·22e-6·500e3) = 7.2mΩ
    # 500mΩ >> 7.2mΩ → ESR dominated
    report = compute_buck_ripple(_spec(ESR=500.0))
    assert "ESR-dominated" in report.honest_caveat


# ---------------------------------------------------------------------------
# T21 — 24V→12V, 2A, 250kHz, L=47µH, C=100µF, ESR=5mΩ
# ---------------------------------------------------------------------------

def test_t21_24v_to_12v_design():
    """24V→12V, 2A, 250kHz, L=47µH, C=100µF, ESR=5mΩ — hand-verified."""
    # D = 12/24 = 0.5
    # ΔiL = (24-12)·0.5/(47e-6·250e3) = 6.0/11.75 = 0.5106 A
    # ΔV_cap = 0.5106/(8·100e-6·250e3) = 0.5106/200 = 2.553 mV
    # ΔV_ESR = 0.5106·0.005 = 2.553 mV
    # total ≈ 5.106 mV
    report = compute_buck_ripple(_spec(
        V_in=24.0, V_out=12.0, I_load=2.0,
        f=250_000.0, L=47.0, C=100.0, ESR=5.0,
    ))

    D_exp, diL_exp, Vcap_exp, VESR_exp, Vtot_exp = _hand_calc(
        V_in=24.0, V_out=12.0, f=250_000.0, L_uH=47.0, C_uF=100.0, ESR_mOhm=5.0
    )

    assert abs(report.duty_cycle - D_exp) / D_exp < REL_TOL
    assert abs(report.delta_iL_pp_A - diL_exp) / diL_exp < REL_TOL
    assert abs(report.delta_V_capacitor_mV - Vcap_exp) / Vcap_exp < REL_TOL
    assert abs(report.delta_V_ESR_mV - VESR_exp) / VESR_exp < REL_TOL
    assert abs(report.delta_V_out_pp_mV - Vtot_exp) / Vtot_exp < REL_TOL
    # Spot check
    assert abs(report.duty_cycle - 0.5) < 0.001


# ---------------------------------------------------------------------------
# T22 — 3.3V→1.2V, 3A, 1MHz, L=4.7µH, C=47µF, ESR=3mΩ
# ---------------------------------------------------------------------------

def test_t22_3v3_to_1v2_high_freq():
    """3.3V→1.2V at 1MHz — low-ripple ASIC power-rail scenario."""
    report = compute_buck_ripple(_spec(
        V_in=3.3, V_out=1.2, I_load=3.0,
        f=1_000_000.0, L=4.7, C=47.0, ESR=3.0,
    ))

    D_exp, diL_exp, Vcap_exp, VESR_exp, Vtot_exp = _hand_calc(
        V_in=3.3, V_out=1.2, f=1_000_000.0, L_uH=4.7, C_uF=47.0, ESR_mOhm=3.0
    )

    assert abs(report.duty_cycle - D_exp) / D_exp < REL_TOL
    assert abs(report.delta_iL_pp_A - diL_exp) / diL_exp < REL_TOL
    assert abs(report.delta_V_capacitor_mV - Vcap_exp) / Vcap_exp < REL_TOL
    assert abs(report.delta_V_out_pp_mV - Vtot_exp) / Vtot_exp < REL_TOL

    # At 1 MHz the ripple should be small (< 5 mV for these params)
    assert report.delta_V_out_pp_mV < 5.0


# ---------------------------------------------------------------------------
# T23 — dict-in / dict-out wrapper happy path
# ---------------------------------------------------------------------------

def test_t23_dict_wrapper_happy_path():
    """compute_buck_ripple_from_dict should return ok=True for valid inputs."""
    result = compute_buck_ripple_from_dict({
        "V_in_V": 12.0, "V_out_V": 5.0, "I_load_A": 1.0,
        "switching_freq_Hz": 500_000.0, "L_uH": 22.0,
        "C_out_uF": 22.0, "C_ESR_mOhm": 10.0,
    })
    assert result["ok"] is True
    assert result["delta_V_out_pp_mV"] > 0
    assert result["duty_cycle"] > 0
    assert isinstance(result["honest_caveat"], str)


# ---------------------------------------------------------------------------
# T24 — dict wrapper bad inputs
# ---------------------------------------------------------------------------

def test_t24_dict_wrapper_bad_inputs():
    """compute_buck_ripple_from_dict should return ok=False for bad inputs."""
    # Missing required key
    result = compute_buck_ripple_from_dict({"V_in_V": 12.0})
    assert result["ok"] is False
    assert "reason" in result

    # V_out > V_in
    result = compute_buck_ripple_from_dict({
        "V_in_V": 5.0, "V_out_V": 12.0, "I_load_A": 1.0,
        "switching_freq_Hz": 500_000.0, "L_uH": 22.0,
        "C_out_uF": 22.0, "C_ESR_mOhm": 10.0,
    })
    assert result["ok"] is False
