"""
Hermetic tests for kerf_electronics.op_amp_offset_drift.

Op-amp input offset voltage and temperature drift calculator.

Reference calculations (TI SLOA069 §3 Eq. 3-1 + Analog Devices AN-580 §1):
  Vos(T) = Vos_typ + drift × (T − T_ref)
  Vos_max_IR = max(|Vos(T_min)|, |Vos(T_max)|)
  Vos_OR_mV  = gain × Vos_max_IR / 1000
  error_pct  = 100 × (Vos_OR_mV / 1000) / FS

Reference design (used in multiple tests):
  Vos_typ=100 µV, drift=2 µV/°C, T=[0..70]°C, Tref=25°C, gain=100, FS=5V
  Vos(T_min=0)  = 100 + 2×(0−25)  = 100 − 50  =  50 µV
  Vos(T_max=70) = 100 + 2×(70−25) = 100 + 90  = 190 µV
  worst-case input-referred = 190 µV  (T_max positive drift dominates)
  output-referred = 100 × 190 / 1000 = 19 mV
  error_pct = 100 × (19/1000) / 5    = 0.38 %

Test inventory (≥ 12 tests):
  T01  Reference design: Vos(T_min), Vos(T_max), worst-case, output-referred, error_pct
  T02  High-drift standard op-amp over 0.1% budget → recommend precision
  T03  Zero-drift op-amp (0.05 µV/°C) class confirmed as "chopper"
  T04  Precision op-amp (0.5 µV/°C) within budget → recommend "precision"
  T05  Zero Vos_typ, pure drift contribution
  T06  Negative Vos_typ + positive drift: worst-case is reinforcement
  T07  Wide industrial temperature range −40..125 °C
  T08  Gain scaling: output-referred scales linearly with gain
  T09  FS scaling: error_pct inversely proportional to FS
  T10  within_spec flag: True when error_pct < error_budget_pct
  T11  within_spec flag: False when error_pct >= error_budget_pct
  T12  ValueError on negative drift coefficient
  T13  ValueError on T_min >= T_max
  T14  ValueError on gain <= 0
  T15  ValueError on FS <= 0
  T16  LLM tool happy path: JSON round-trip
  T17  LLM tool bad JSON
  T18  LLM tool invalid args
  T19  Dict wrapper happy path
  T20  Dict wrapper missing key returns ok=False
  T21  Chopper class recommended when error >> budget (10× over)
  T22  zero-drift class (TC = 0.08 µV/°C, in budget)
  T23  Report dataclass fields all present and correctly typed
  T24  T_ref outside temperature range (one-sided drift)
"""
from __future__ import annotations

import json
import pytest

from kerf_electronics.op_amp_offset_drift import (
    OpAmpSpec,
    CircuitSpec,
    OpAmpOffsetReport,
    compute_op_amp_drift,
    compute_op_amp_drift_from_dict,
    electronics_compute_op_amp_drift,
)

REL_TOL = 1e-4   # 0.01 % relative tolerance for numerical comparisons
ABS_TOL = 1e-6   # absolute floor for comparisons near zero


# ── Helpers ────────────────────────────────────────────────────────────────────


def _op(
    Vos_typ=100.0,
    drift=2.0,
    T_min=0.0,
    T_max=70.0,
    T_ref=25.0,
) -> OpAmpSpec:
    return OpAmpSpec(
        Vos_typ_uV=Vos_typ,
        Vos_drift_uV_per_C=drift,
        T_ambient_min_C=T_min,
        T_ambient_max_C=T_max,
        T_reference_C=T_ref,
    )


def _circ(gain=100.0, fs=5.0) -> CircuitSpec:
    return CircuitSpec(gain_VV=gain, signal_full_scale_V=fs)


def _hand_calc(Vos_typ, drift, T_min, T_max, T_ref, gain, FS):
    """Return (Vos_T_min, Vos_T_max, Vos_max_IR, Vos_OR_mV, error_pct)."""
    Vos_T_min_pos = Vos_typ + drift * (T_min - T_ref)
    Vos_T_max_pos = Vos_typ + drift * (T_max - T_ref)
    Vos_T_min_neg = Vos_typ - drift * (T_min - T_ref)
    Vos_T_max_neg = Vos_typ - drift * (T_max - T_ref)
    Vos_max_IR = max(
        abs(Vos_T_min_pos), abs(Vos_T_max_pos),
        abs(Vos_T_min_neg), abs(Vos_T_max_neg),
    )
    Vos_OR_mV = gain * Vos_max_IR / 1000.0
    error_pct = 100.0 * (Vos_OR_mV / 1000.0) / FS
    return Vos_T_min_pos, Vos_T_max_pos, Vos_max_IR, Vos_OR_mV, error_pct


# ── T01 — Reference design from task spec ──────────────────────────────────────


def test_t01_reference_design():
    """
    Task-spec reference:
      Vos=100µV, drift=2µV/°C, T=[0..70]°C, Tref=25, gain=100, FS=5V
      Vos(0)  = 100 + 2*(0-25)  = 50 µV
      Vos(70) = 100 + 2*(70-25) = 190 µV
      max_IR  = 190 µV
      output  = 100 × 190 / 1000 = 19 mV
      error   = 100 × 0.019 / 5 = 0.38 %
    """
    report = compute_op_amp_drift(_op(), _circ(), error_budget_pct=0.1)

    # Vos at T_min = 0 °C
    assert abs(report.Vos_at_T_min_uV - 50.0) < ABS_TOL + REL_TOL * 50, (
        f"Vos(T_min): got {report.Vos_at_T_min_uV}, expected 50.0 µV"
    )

    # Vos at T_max = 70 °C
    assert abs(report.Vos_at_T_max_uV - 190.0) < ABS_TOL + REL_TOL * 190, (
        f"Vos(T_max): got {report.Vos_at_T_max_uV}, expected 190.0 µV"
    )

    # Worst-case input-referred = 190 µV (T_max positive drift dominates)
    assert abs(report.Vos_max_input_referred_uV - 190.0) < ABS_TOL + REL_TOL * 190, (
        f"max_IR: got {report.Vos_max_input_referred_uV}, expected 190.0 µV"
    )

    # Output-referred = 19 mV
    assert abs(report.Vos_max_output_referred_mV - 19.0) < 0.001, (
        f"output_OR: got {report.Vos_max_output_referred_mV}, expected 19.0 mV"
    )

    # Error = 0.38 %
    assert abs(report.error_pct_of_FS - 0.38) < 0.001, (
        f"error_pct: got {report.error_pct_of_FS:.5f}, expected 0.38000%"
    )

    # Over 0.1% budget → not within spec
    assert report.within_spec is False


# ── T02 — Standard op-amp (drift>1 µV/°C) over 0.1% budget → "precision" ─────


def test_t02_standard_opamp_over_budget_recommends_precision():
    """
    drift=5 µV/°C (general-purpose, e.g. LM741) → over 0.1% budget
    → recommended class must be 'precision' or better.
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=500.0, drift=5.0, T_min=0.0, T_max=70.0),
        _circ(gain=100.0, fs=5.0),
        error_budget_pct=0.1,
    )
    assert report.within_spec is False
    assert report.recommended_op_amp_class in {"precision", "zero-drift", "chopper"}, (
        f"Expected precision-or-better, got {report.recommended_op_amp_class}"
    )


# ── T03 — Chopper/auto-zero op-amp (≤0.05 µV/°C) confirmed as "chopper" ──────


def test_t03_chopper_class_confirmed():
    """
    drift=0.05 µV/°C → chopper class (e.g. AD8551, MAX420).
    With small Vos and tight drift should be within budget and class=chopper.
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=10.0, drift=0.05, T_min=0.0, T_max=70.0),
        _circ(gain=100.0, fs=5.0),
        error_budget_pct=0.1,
    )
    assert report.recommended_op_amp_class == "chopper", (
        f"Expected chopper class, got {report.recommended_op_amp_class}"
    )


# ── T04 — Precision op-amp (0.5 µV/°C) within tight budget → "precision" ─────


def test_t04_precision_class_in_budget():
    """
    drift=0.5 µV/°C (e.g. OPA227, LT1012) should be classified 'precision'.
    At gain=10, FS=5V the error should be small enough to be in a 1% budget.
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=25.0, drift=0.5, T_min=0.0, T_max=70.0),
        _circ(gain=10.0, fs=5.0),
        error_budget_pct=1.0,
    )
    assert report.recommended_op_amp_class == "precision", (
        f"Expected 'precision', got {report.recommended_op_amp_class}"
    )


# ── T05 — Zero Vos_typ: pure drift contribution ──────────────────────────────


def test_t05_zero_vos_typ_pure_drift():
    """
    Vos_typ=0 µV: offset at T_ref=0; output error is drift-only over the range.
    Vos(0°C) = 0 + 2*(0-25) = -50 µV  (negative drift down)
    Vos(70°C) = 0 + 2*(70-25) = 90 µV (positive drift up)
    worst-case = max(|-50|, |90|, |+50|, |-90|) = 90 µV
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=0.0, drift=2.0, T_min=0.0, T_max=70.0),
        _circ(gain=100.0, fs=5.0),
        error_budget_pct=0.1,
    )
    # Vos at Tref=25 is zero; drift pushes to ±90 µV at T_max=70
    assert abs(report.Vos_max_input_referred_uV - 90.0) < 0.01, (
        f"max_IR: got {report.Vos_max_input_referred_uV}, expected 90.0 µV"
    )
    expected_OR = 100.0 * 90.0 / 1000.0  # 9.0 mV
    assert abs(report.Vos_max_output_referred_mV - expected_OR) < 0.001


# ── T06 — Negative Vos_typ reinforced by drift ───────────────────────────────


def test_t06_negative_vos_typ_reinforced_by_drift():
    """
    Vos_typ=−150 µV, drift=3 µV/°C, T=[0..85], Tref=25.
    Positive-drift direction:
      Vos(0)  = -150 + 3*(0-25)  = -150 - 75 = -225 µV   (large negative)
      Vos(85) = -150 + 3*(85-25) = -150 + 180 =   30 µV
    Negative-drift direction (drift flipped):
      Vos(0)  = -150 - 3*(0-25)  = -150 + 75  = -75 µV
      Vos(85) = -150 - 3*(85-25) = -150 - 180 = -330 µV  (even larger neg)

    worst-case = max(225, 30, 75, 330) = 330 µV
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=-150.0, drift=3.0, T_min=0.0, T_max=85.0, T_ref=25.0),
        _circ(gain=50.0, fs=5.0),
        error_budget_pct=0.1,
    )
    expected_max_IR = 330.0  # µV
    assert abs(report.Vos_max_input_referred_uV - expected_max_IR) < 0.01, (
        f"max_IR: got {report.Vos_max_input_referred_uV}, expected 330.0 µV"
    )
    expected_OR = 50.0 * 330.0 / 1000.0  # 16.5 mV
    assert abs(report.Vos_max_output_referred_mV - expected_OR) < 0.001


# ── T07 — Wide industrial range −40..125 °C ──────────────────────────────────


def test_t07_industrial_temperature_range():
    """
    Industrial −40..125 °C range with typical precision op-amp.
    Vos=50 µV, drift=0.5 µV/°C, T=[-40..125], Tref=25, gain=50, FS=3.3V.
    Positive drift:
      Vos(-40) = 50 + 0.5*(-40-25) = 50 - 32.5 = 17.5 µV
      Vos(125) = 50 + 0.5*(125-25) = 50 + 50   = 100.0 µV
    Negative drift:
      Vos(-40) = 50 - 0.5*(-40-25) = 50 + 32.5 = 82.5 µV
      Vos(125) = 50 - 0.5*(125-25) = 50 - 50   = 0.0 µV
    worst-case = max(17.5, 100.0, 82.5, 0.0) = 100.0 µV
    output_OR = 50 * 100.0 / 1000 = 5.0 mV
    error = 100 * 0.005 / 3.3 = 0.1515 %
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=50.0, drift=0.5, T_min=-40.0, T_max=125.0, T_ref=25.0),
        _circ(gain=50.0, fs=3.3),
        error_budget_pct=0.1,
    )
    _, _, Vos_max_IR_exp, Vos_OR_exp, err_exp = _hand_calc(
        50.0, 0.5, -40.0, 125.0, 25.0, 50.0, 3.3
    )
    assert abs(report.Vos_max_input_referred_uV - Vos_max_IR_exp) < 0.01
    assert abs(report.Vos_max_output_referred_mV - Vos_OR_exp) < 0.001
    assert abs(report.error_pct_of_FS - err_exp) / (err_exp + ABS_TOL) < REL_TOL


# ── T08 — Gain scaling: output-referred scales linearly with gain ─────────────


def test_t08_gain_scaling():
    """Doubling gain should double the output-referred offset and error_pct."""
    r1 = compute_op_amp_drift(_op(), _circ(gain=100.0), error_budget_pct=0.1)
    r2 = compute_op_amp_drift(_op(), _circ(gain=200.0), error_budget_pct=0.1)

    assert abs(r2.Vos_max_output_referred_mV - 2.0 * r1.Vos_max_output_referred_mV) < 0.001
    assert abs(r2.error_pct_of_FS - 2.0 * r1.error_pct_of_FS) / r2.error_pct_of_FS < REL_TOL


# ── T09 — FS scaling: error_pct inversely proportional to FS ─────────────────


def test_t09_fs_scaling():
    """Doubling FS should halve error_pct (input-referred offset unchanged)."""
    r1 = compute_op_amp_drift(_op(), _circ(fs=5.0), error_budget_pct=0.1)
    r2 = compute_op_amp_drift(_op(), _circ(fs=10.0), error_budget_pct=0.1)

    assert abs(r2.Vos_max_input_referred_uV - r1.Vos_max_input_referred_uV) < ABS_TOL
    assert abs(r2.error_pct_of_FS * 2.0 - r1.error_pct_of_FS) / r1.error_pct_of_FS < REL_TOL


# ── T10 — within_spec = True when error_pct < budget ─────────────────────────


def test_t10_within_spec_true():
    """Very tight drift + low gain should be within a 1% budget."""
    report = compute_op_amp_drift(
        _op(Vos_typ=10.0, drift=0.05, T_min=0.0, T_max=70.0),
        _circ(gain=10.0, fs=5.0),
        error_budget_pct=1.0,
    )
    assert report.within_spec is True


# ── T11 — within_spec = False when error_pct >= budget ───────────────────────


def test_t11_within_spec_false():
    """Reference design (0.38% error) exceeds 0.1% budget → within_spec=False."""
    report = compute_op_amp_drift(_op(), _circ(), error_budget_pct=0.1)
    assert report.within_spec is False
    assert report.error_pct_of_FS > 0.1


# ── T12 — ValueError on negative drift coefficient ───────────────────────────


def test_t12_negative_drift_raises():
    """Negative Vos_drift_uV_per_C must raise ValueError."""
    with pytest.raises(ValueError, match="Vos_drift"):
        compute_op_amp_drift(
            _op(drift=-1.0),
            _circ(),
        )


# ── T13 — ValueError on T_min >= T_max ───────────────────────────────────────


def test_t13_t_min_gte_t_max_raises():
    """T_ambient_min_C >= T_ambient_max_C must raise ValueError."""
    with pytest.raises(ValueError, match="T_ambient"):
        compute_op_amp_drift(
            _op(T_min=70.0, T_max=70.0),
            _circ(),
        )

    with pytest.raises(ValueError):
        compute_op_amp_drift(
            _op(T_min=100.0, T_max=70.0),
            _circ(),
        )


# ── T14 — ValueError on gain <= 0 ────────────────────────────────────────────


def test_t14_invalid_gain_raises():
    """gain_VV <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="gain_VV"):
        compute_op_amp_drift(_op(), _circ(gain=0.0))

    with pytest.raises(ValueError):
        compute_op_amp_drift(_op(), _circ(gain=-10.0))


# ── T15 — ValueError on FS <= 0 ──────────────────────────────────────────────


def test_t15_invalid_fs_raises():
    """signal_full_scale_V <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="signal_full_scale_V"):
        compute_op_amp_drift(_op(), _circ(fs=0.0))

    with pytest.raises(ValueError):
        compute_op_amp_drift(_op(), _circ(fs=-3.3))


# ── T16 — LLM tool happy path ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t16_llm_tool_happy_path():
    """LLM tool should return valid JSON with ok=True for valid inputs."""
    args = json.dumps({
        "Vos_typ_uV": 100.0,
        "Vos_drift_uV_per_C": 2.0,
        "T_ambient_min_C": 0.0,
        "T_ambient_max_C": 70.0,
        "gain_VV": 100.0,
        "signal_full_scale_V": 5.0,
        "error_budget_pct": 0.1,
    }).encode()
    result = await electronics_compute_op_amp_drift(None, args)
    data = json.loads(result)
    assert data["ok"] is True
    assert "Vos_max_output_referred_mV" in data
    assert abs(data["Vos_max_output_referred_mV"] - 19.0) < 0.001
    assert data["within_spec"] is False
    assert "recommended_op_amp_class" in data
    assert "honest_caveat" in data


# ── T17 — LLM tool bad JSON ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t17_llm_tool_bad_json():
    """LLM tool should return an error dict for malformed JSON."""
    result = await electronics_compute_op_amp_drift(None, b"{bad json here")
    data = json.loads(result)
    assert data.get("error") or data.get("ok") is False


# ── T18 — LLM tool invalid args ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t18_llm_tool_invalid_args():
    """LLM tool should return error when T_min >= T_max."""
    args = json.dumps({
        "Vos_typ_uV": 100.0,
        "Vos_drift_uV_per_C": 2.0,
        "T_ambient_min_C": 70.0,
        "T_ambient_max_C": 0.0,   # T_min > T_max → invalid
        "gain_VV": 100.0,
        "signal_full_scale_V": 5.0,
    }).encode()
    result = await electronics_compute_op_amp_drift(None, args)
    data = json.loads(result)
    assert data.get("ok") is False or "error" in data


# ── T19 — Dict wrapper happy path ─────────────────────────────────────────────


def test_t19_dict_wrapper_happy_path():
    """compute_op_amp_drift_from_dict should return ok=True for valid inputs."""
    result = compute_op_amp_drift_from_dict({
        "Vos_typ_uV": 100.0,
        "Vos_drift_uV_per_C": 2.0,
        "T_ambient_min_C": 0.0,
        "T_ambient_max_C": 70.0,
        "gain_VV": 100.0,
        "signal_full_scale_V": 5.0,
    })
    assert result["ok"] is True
    assert abs(result["Vos_max_output_referred_mV"] - 19.0) < 0.001
    assert result["within_spec"] is False
    assert isinstance(result["honest_caveat"], str)
    assert len(result["honest_caveat"]) > 50


# ── T20 — Dict wrapper missing key ───────────────────────────────────────────


def test_t20_dict_wrapper_missing_key():
    """Dict wrapper should return ok=False when a required key is absent."""
    result = compute_op_amp_drift_from_dict({
        "Vos_typ_uV": 100.0,
        # Vos_drift_uV_per_C missing
        "T_ambient_min_C": 0.0,
        "T_ambient_max_C": 70.0,
        "gain_VV": 100.0,
        "signal_full_scale_V": 5.0,
    })
    assert result["ok"] is False
    assert "reason" in result


# ── T21 — Chopper recommended when error >> budget (≥ 10× over) ──────────────


def test_t21_chopper_recommended_far_over_budget():
    """
    When error is 10× or more over budget, recommend 'chopper'.
    Vos=1000 µV, drift=10 µV/°C, gain=1000 → massive offset → chopper needed.
    Vos(70) = 1000 + 10*45 = 1450 µV → OR = 1450 mV → error = 29% >> 0.1% budget.
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=1000.0, drift=10.0, T_min=0.0, T_max=70.0),
        _circ(gain=1000.0, fs=5.0),
        error_budget_pct=0.1,
    )
    assert report.within_spec is False
    assert report.error_pct_of_FS >= 10.0 * 0.1  # at least 10× budget
    assert report.recommended_op_amp_class == "chopper", (
        f"Expected chopper class far over budget, got {report.recommended_op_amp_class}"
    )


# ── T22 — zero-drift class (TC = 0.08 µV/°C, in budget) ─────────────────────


def test_t22_zero_drift_class_in_budget():
    """
    TC=0.08 µV/°C (≤0.1 µV/°C threshold for zero-drift) and in budget
    → class 'zero-drift'.
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=5.0, drift=0.08, T_min=0.0, T_max=70.0),
        _circ(gain=10.0, fs=5.0),
        error_budget_pct=1.0,
    )
    assert report.within_spec is True
    assert report.recommended_op_amp_class == "zero-drift", (
        f"Expected zero-drift class, got {report.recommended_op_amp_class}"
    )


# ── T23 — Report fields all present and correctly typed ──────────────────────


def test_t23_report_fields_typed():
    """All OpAmpOffsetReport fields must be present and correctly typed."""
    report = compute_op_amp_drift(_op(), _circ(), error_budget_pct=0.1)
    assert isinstance(report, OpAmpOffsetReport)
    assert isinstance(report.Vos_at_T_min_uV, float)
    assert isinstance(report.Vos_at_T_max_uV, float)
    assert isinstance(report.Vos_max_input_referred_uV, float)
    assert isinstance(report.Vos_max_output_referred_mV, float)
    assert isinstance(report.error_pct_of_FS, float)
    assert isinstance(report.within_spec, bool)
    assert isinstance(report.recommended_op_amp_class, str)
    assert isinstance(report.honest_caveat, str)

    # Positivity constraints
    assert report.Vos_max_input_referred_uV >= 0.0
    assert report.Vos_max_output_referred_mV >= 0.0
    assert report.error_pct_of_FS >= 0.0
    assert report.recommended_op_amp_class in {
        "standard", "precision", "zero-drift", "chopper"
    }
    assert len(report.honest_caveat) > 100
    assert "HONEST" in report.honest_caveat
    # Caveats must mention 1/f and PSRR (as per task spec)
    assert "1/f" in report.honest_caveat
    assert "PSRR" in report.honest_caveat


# ── T24 — T_ref outside [T_min, T_max] (one-sided drift scenario) ────────────


def test_t24_t_ref_outside_temperature_range():
    """
    T_ref=125°C with T=[0..70]°C — T_ref is above the operating range,
    so drift is always in the negative direction from T_ref down to T_max.
    Vos(0)  = 100 + 2*(0-125)  = 100 - 250 = -150 µV
    Vos(70) = 100 + 2*(70-125) = 100 - 110 =  -10 µV
    max |Vos| via all 4 candidates = max(150, 10, ...) = 250 µV
    (negative drift direction at T_min gives +250)
    """
    report = compute_op_amp_drift(
        _op(Vos_typ=100.0, drift=2.0, T_min=0.0, T_max=70.0, T_ref=125.0),
        _circ(gain=100.0, fs=5.0),
        error_budget_pct=0.1,
    )
    # All 4 candidates:
    # pos: Vos(0) = -150, Vos(70) = -10
    # neg: Vos(0) = +350, Vos(70) = +210
    # worst-case = 350 µV
    assert abs(report.Vos_max_input_referred_uV - 350.0) < 0.01, (
        f"Expected 350.0 µV, got {report.Vos_max_input_referred_uV}"
    )
