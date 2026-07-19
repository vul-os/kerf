"""
Hermetic tests for kerf_electronics.fuse_i2t_check.

Fuse I²t (melting energy) verification — IEC 60269 + Cooper Bussmann SPD §2–§4.

Hand-calc reference:
  applied_I2t = peak_current_A² × (duration_ms / 1000)   [A²·s]
  clears_safely = applied_I2t >= fuse_pre_arc_I2t
  breaking_capacity_adequate = available_SCC_kA <= fuse.breaking_capacity_kA
  ratio_pct = 100 × applied_I2t / fuse_pre_arc_I2t

Test cases:
  T01  5 A F-class fuse, I²t=10 A²·s, fault: 100 A × 1 ms
         applied = 100² × 0.001 = 10 A²·s → ratio=100%, clears=True (on threshold)
  T02  Heavy fault: 1000 A × 10 ms
         applied = 1000² × 0.010 = 10 000 A²·s >> 10 → ratio=100000%, clears=True
  T03  Low fault (nuisance no-trip): 5 A × 100 ms
         applied = 5² × 0.100 = 2.5 A²·s < 10 → clears=False
  T04  Breaking capacity exceeded → breaking_capacity_adequate=False
  T05  Breaking capacity exactly at limit → breaking_capacity_adequate=True
  T06  All fuse classes accepted (F, M, T, FF, gG, aR)
  T07  Invalid fuse_class raises ValueError
  T08  Negative peak_current raises ValueError
  T09  Zero duration_ms raises ValueError
  T10  Non-positive I_squared_t_pre_arc_A2_s raises ValueError
  T11  Non-positive breaking_capacity_kA raises ValueError
  T12  Report dataclass fields all present and correctly typed
  T13  LLM tool happy path (JSON round-trip) — clears case
  T14  LLM tool happy path (JSON round-trip) — no-clear case
  T15  LLM tool malformed JSON → error payload
  T16  LLM tool bad fuse_class → error payload
  T17  gG class, 32 A fuse, I²t=800, fault: 900 A × 1 ms = 810 → clears
  T18  aR semiconductor fuse, high fault, ratio >> 500% → recommended=aR
  T19  ratio < 50% → recommended=T (slow fuse suggestion)
  T20  ratio 50–100% → recommended=gG
  T21  ratio 100–200% → recommended=F
  T22  ratio 200–500% → recommended=FF
  T23  Zero peak current → applied_I2t=0, clears=False
  T24  honest_caveat always mentions square-wave limitation
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_electronics.fuse_i2t_check import (
    FuseSpec,
    FaultSpec,
    FuseI2tReport,
    check_fuse_i2t,
)
from kerf_electronics.tools.fuse_i2t import electronics_check_fuse_i2t


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fuse_5a_F() -> FuseSpec:
    """5 A F-class fuse, 250 V, I²t=10 A²·s, breaking 10 kA."""
    return FuseSpec(
        nominal_current_A=5.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=10.0,
        breaking_capacity_kA=10.0,
        fuse_class="F",
    )


def _fault(peak_A: float, dur_ms: float, scc_kA: float = 1.0) -> FaultSpec:
    return FaultSpec(
        peak_current_A=peak_A,
        duration_ms=dur_ms,
        available_short_circuit_current_kA=scc_kA,
    )


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# T01 — threshold case: 100 A × 1 ms = 10 A²·s → ratio=100%, clears=True
# ---------------------------------------------------------------------------

def test_T01_threshold_case():
    fuse = _fuse_5a_F()
    fault = _fault(peak_A=100.0, dur_ms=1.0, scc_kA=1.0)
    report = check_fuse_i2t(fuse, fault)
    assert math.isclose(report.applied_I2t_A2s, 10.0, rel_tol=1e-9)
    assert math.isclose(report.ratio_pct, 100.0, rel_tol=1e-9)
    assert report.clears_safely is True


# ---------------------------------------------------------------------------
# T02 — heavy fault: 1000 A × 10 ms = 10 000 A²·s
# ---------------------------------------------------------------------------

def test_T02_heavy_fault_clears():
    fuse = _fuse_5a_F()
    fault = _fault(peak_A=1000.0, dur_ms=10.0, scc_kA=1.0)
    report = check_fuse_i2t(fuse, fault)
    expected_i2t = 1000.0 ** 2 * 0.010  # 10 000
    assert math.isclose(report.applied_I2t_A2s, expected_i2t, rel_tol=1e-9)
    assert math.isclose(report.ratio_pct, 100000.0, rel_tol=1e-6)
    assert report.clears_safely is True
    assert report.breaking_capacity_adequate is True


# ---------------------------------------------------------------------------
# T03 — low fault (nuisance no-trip): 5 A × 100 ms = 2.5 A²·s < 10
# ---------------------------------------------------------------------------

def test_T03_low_fault_no_clear():
    fuse = _fuse_5a_F()
    fault = _fault(peak_A=5.0, dur_ms=100.0, scc_kA=0.1)
    report = check_fuse_i2t(fuse, fault)
    expected = 5.0 ** 2 * 0.100  # 2.5
    assert math.isclose(report.applied_I2t_A2s, expected, rel_tol=1e-9)
    assert report.clears_safely is False
    assert math.isclose(report.ratio_pct, 25.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# T04 — breaking capacity exceeded
# ---------------------------------------------------------------------------

def test_T04_breaking_capacity_exceeded():
    fuse = _fuse_5a_F()  # breaking_capacity_kA=10
    fault = _fault(peak_A=100.0, dur_ms=1.0, scc_kA=15.0)  # SCC > breaking cap
    report = check_fuse_i2t(fuse, fault)
    assert report.breaking_capacity_adequate is False
    # warnings should appear in caveat
    assert "breaking" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# T05 — breaking capacity exactly at limit → adequate
# ---------------------------------------------------------------------------

def test_T05_breaking_capacity_exactly_at_limit():
    fuse = _fuse_5a_F()  # breaking_capacity_kA=10
    fault = _fault(peak_A=100.0, dur_ms=1.0, scc_kA=10.0)
    report = check_fuse_i2t(fuse, fault)
    assert report.breaking_capacity_adequate is True


# ---------------------------------------------------------------------------
# T06 — all fuse classes accepted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fuse_class", ["F", "M", "T", "FF", "gG", "aR"])
def test_T06_all_fuse_classes_accepted(fuse_class):
    fuse = FuseSpec(
        nominal_current_A=10.0,
        voltage_rating_V=400.0,
        I_squared_t_pre_arc_A2_s=100.0,
        breaking_capacity_kA=10.0,
        fuse_class=fuse_class,
    )
    fault = _fault(peak_A=200.0, dur_ms=2.0, scc_kA=5.0)
    report = check_fuse_i2t(fuse, fault)
    assert isinstance(report, FuseI2tReport)


# ---------------------------------------------------------------------------
# T07 — invalid fuse_class raises ValueError
# ---------------------------------------------------------------------------

def test_T07_invalid_fuse_class_raises():
    fuse = FuseSpec(
        nominal_current_A=5.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=10.0,
        breaking_capacity_kA=10.0,
        fuse_class="SUPER_FAST",
    )
    with pytest.raises(ValueError, match="fuse_class"):
        check_fuse_i2t(fuse, _fault(100, 1.0))


# ---------------------------------------------------------------------------
# T08 — negative peak_current raises ValueError
# ---------------------------------------------------------------------------

def test_T08_negative_peak_current_raises():
    with pytest.raises(ValueError, match="peak_current_A"):
        check_fuse_i2t(_fuse_5a_F(), _fault(peak_A=-1.0, dur_ms=1.0))


# ---------------------------------------------------------------------------
# T09 — zero duration_ms raises ValueError
# ---------------------------------------------------------------------------

def test_T09_zero_duration_raises():
    with pytest.raises(ValueError, match="duration_ms"):
        check_fuse_i2t(_fuse_5a_F(), _fault(peak_A=100.0, dur_ms=0.0))


# ---------------------------------------------------------------------------
# T10 — non-positive I_squared_t_pre_arc raises ValueError
# ---------------------------------------------------------------------------

def test_T10_nonpositive_I2t_raises():
    fuse = FuseSpec(
        nominal_current_A=5.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=0.0,
        breaking_capacity_kA=10.0,
        fuse_class="F",
    )
    with pytest.raises(ValueError, match="I_squared_t_pre_arc_A2_s"):
        check_fuse_i2t(fuse, _fault(100, 1.0))


# ---------------------------------------------------------------------------
# T11 — non-positive breaking_capacity raises ValueError
# ---------------------------------------------------------------------------

def test_T11_nonpositive_breaking_capacity_raises():
    fuse = FuseSpec(
        nominal_current_A=5.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=10.0,
        breaking_capacity_kA=0.0,
        fuse_class="F",
    )
    with pytest.raises(ValueError, match="breaking_capacity_kA"):
        check_fuse_i2t(fuse, _fault(100, 1.0))


# ---------------------------------------------------------------------------
# T12 — report dataclass fields correctly typed
# ---------------------------------------------------------------------------

def test_T12_report_fields_types():
    report = check_fuse_i2t(_fuse_5a_F(), _fault(100, 1.0))
    assert isinstance(report.applied_I2t_A2s, float)
    assert isinstance(report.fuse_pre_arc_I2t_A2s, float)
    assert isinstance(report.ratio_pct, float)
    assert isinstance(report.clears_safely, bool)
    assert isinstance(report.breaking_capacity_adequate, bool)
    assert isinstance(report.recommended_fuse_class, str)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 20


# ---------------------------------------------------------------------------
# T13 — LLM tool happy path — clears case
# ---------------------------------------------------------------------------

def test_T13_llm_tool_clears():
    payload = json.dumps({
        "nominal_current_A": 5.0,
        "voltage_rating_V": 250.0,
        "I_squared_t_pre_arc_A2_s": 10.0,
        "breaking_capacity_kA": 10.0,
        "fuse_class": "F",
        "peak_current_A": 100.0,
        "duration_ms": 1.0,
        "available_short_circuit_current_kA": 1.0,
    }).encode()

    result = _run(electronics_check_fuse_i2t(None, payload))
    data = json.loads(result)
    assert data["ok"] is True
    assert math.isclose(data["applied_I2t_A2s"], 10.0, rel_tol=1e-9)
    assert data["clears_safely"] is True
    assert data["breaking_capacity_adequate"] is True
    assert math.isclose(data["ratio_pct"], 100.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# T14 — LLM tool happy path — no-clear case
# ---------------------------------------------------------------------------

def test_T14_llm_tool_no_clear():
    payload = json.dumps({
        "nominal_current_A": 5.0,
        "voltage_rating_V": 250.0,
        "I_squared_t_pre_arc_A2_s": 10.0,
        "breaking_capacity_kA": 10.0,
        "fuse_class": "F",
        "peak_current_A": 5.0,
        "duration_ms": 100.0,
        "available_short_circuit_current_kA": 0.1,
    }).encode()

    result = _run(electronics_check_fuse_i2t(None, payload))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["clears_safely"] is False
    assert math.isclose(data["applied_I2t_A2s"], 2.5, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# T15 — LLM tool malformed JSON → error payload
# ---------------------------------------------------------------------------

def test_T15_llm_tool_malformed_json():
    result = _run(electronics_check_fuse_i2t(None, b"not valid json {{{"))
    data = json.loads(result)
    assert "error" in data
    assert data.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T16 — LLM tool bad fuse_class → error payload
# ---------------------------------------------------------------------------

def test_T16_llm_tool_bad_fuse_class():
    payload = json.dumps({
        "nominal_current_A": 5.0,
        "voltage_rating_V": 250.0,
        "I_squared_t_pre_arc_A2_s": 10.0,
        "breaking_capacity_kA": 10.0,
        "fuse_class": "INVALID",
        "peak_current_A": 100.0,
        "duration_ms": 1.0,
        "available_short_circuit_current_kA": 1.0,
    }).encode()
    result = _run(electronics_check_fuse_i2t(None, payload))
    data = json.loads(result)
    assert "error" in data
    assert data.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T17 — gG class, 32 A fuse, I²t=800, fault: 900 A × 1 ms = 810 → clears
# ---------------------------------------------------------------------------

def test_T17_gG_32A_fuse_clears():
    fuse = FuseSpec(
        nominal_current_A=32.0,
        voltage_rating_V=400.0,
        I_squared_t_pre_arc_A2_s=800.0,
        breaking_capacity_kA=50.0,
        fuse_class="gG",
    )
    fault = FaultSpec(
        peak_current_A=900.0,
        duration_ms=1.0,
        available_short_circuit_current_kA=5.0,
    )
    report = check_fuse_i2t(fuse, fault)
    expected = 900.0 ** 2 * 0.001  # 810
    assert math.isclose(report.applied_I2t_A2s, expected, rel_tol=1e-9)
    assert report.clears_safely is True


# ---------------------------------------------------------------------------
# T18 — aR semiconductor fuse, ratio >> 500% → recommended=aR
# ---------------------------------------------------------------------------

def test_T18_aR_recommendation_for_very_high_ratio():
    fuse = FuseSpec(
        nominal_current_A=16.0,
        voltage_rating_V=690.0,
        I_squared_t_pre_arc_A2_s=50.0,
        breaking_capacity_kA=100.0,
        fuse_class="aR",
    )
    # ratio = 5000²×0.001 / 50 = 25 000 / 50 = 500 = 500%, just at threshold
    # Use more to get > 500
    fault = FaultSpec(
        peak_current_A=6000.0,
        duration_ms=1.0,
        available_short_circuit_current_kA=5.0,
    )
    report = check_fuse_i2t(fuse, fault)
    assert report.ratio_pct > 500.0
    assert report.recommended_fuse_class == "aR"


# ---------------------------------------------------------------------------
# T19 — ratio < 50% → recommended = T
# ---------------------------------------------------------------------------

def test_T19_low_ratio_recommends_T():
    fuse = FuseSpec(
        nominal_current_A=10.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=1000.0,
        breaking_capacity_kA=10.0,
        fuse_class="gG",
    )
    # applied = 10² × 0.010 = 1 A²·s; ratio = 0.1% → << 50%
    fault = _fault(peak_A=10.0, dur_ms=10.0, scc_kA=1.0)
    report = check_fuse_i2t(fuse, fault)
    assert report.ratio_pct < 50.0
    assert report.recommended_fuse_class == "T"


# ---------------------------------------------------------------------------
# T20 — ratio 50–100% → recommended = gG
# ---------------------------------------------------------------------------

def test_T20_medium_ratio_recommends_gG():
    fuse = FuseSpec(
        nominal_current_A=10.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=100.0,
        breaking_capacity_kA=10.0,
        fuse_class="F",
    )
    # ratio = 70 A²·s / 100 = 70%
    fault = _fault(peak_A=math.sqrt(70.0 / 0.001), dur_ms=1.0)  # I²t = 70
    report = check_fuse_i2t(fuse, fault)
    assert 50.0 <= report.ratio_pct < 100.0
    assert report.recommended_fuse_class == "gG"


# ---------------------------------------------------------------------------
# T21 — ratio 100–200% → recommended = F
# ---------------------------------------------------------------------------

def test_T21_ratio_100_200_recommends_F():
    fuse = FuseSpec(
        nominal_current_A=5.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=10.0,
        breaking_capacity_kA=10.0,
        fuse_class="gG",
    )
    # applied = 130 A²·s; ratio = 1300%
    # Actually let's target 150% → applied = 15
    # I_peak = sqrt(15/0.001) = sqrt(15000) ≈ 122.47 A
    i_peak = math.sqrt(15.0 / 0.001)
    fault = _fault(peak_A=i_peak, dur_ms=1.0)
    report = check_fuse_i2t(fuse, fault)
    assert 100.0 <= report.ratio_pct < 200.0
    assert report.recommended_fuse_class == "F"


# ---------------------------------------------------------------------------
# T22 — ratio 200–500% → recommended = FF
# ---------------------------------------------------------------------------

def test_T22_ratio_200_500_recommends_FF():
    fuse = FuseSpec(
        nominal_current_A=5.0,
        voltage_rating_V=250.0,
        I_squared_t_pre_arc_A2_s=10.0,
        breaking_capacity_kA=10.0,
        fuse_class="gG",
    )
    # ratio = 300% → applied = 30 A²·s
    i_peak = math.sqrt(30.0 / 0.001)
    fault = _fault(peak_A=i_peak, dur_ms=1.0)
    report = check_fuse_i2t(fuse, fault)
    assert 200.0 <= report.ratio_pct < 500.0
    assert report.recommended_fuse_class == "FF"


# ---------------------------------------------------------------------------
# T23 — zero peak current → applied_I2t=0, clears=False
# ---------------------------------------------------------------------------

def test_T23_zero_peak_current():
    fuse = _fuse_5a_F()
    fault = FaultSpec(
        peak_current_A=0.0,
        duration_ms=10.0,
        available_short_circuit_current_kA=0.0,
    )
    report = check_fuse_i2t(fuse, fault)
    assert report.applied_I2t_A2s == 0.0
    assert report.clears_safely is False
    assert report.ratio_pct == 0.0


# ---------------------------------------------------------------------------
# T24 — honest_caveat always mentions square-wave limitation
# ---------------------------------------------------------------------------

def test_T24_honest_caveat_mentions_square_wave():
    report = check_fuse_i2t(_fuse_5a_F(), _fault(100.0, 1.0))
    caveat_lower = report.honest_caveat.lower()
    assert "square" in caveat_lower or "square-wave" in caveat_lower
    assert "iec 60269" in caveat_lower or "sinusoidal" in caveat_lower or "ac" in caveat_lower
