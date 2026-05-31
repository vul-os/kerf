"""
Hermetic tests for kerf_electronics.fet_soa_check.

MOSFET Safe Operating Area (SOA) checker.

Reference device (IRFZ44N-like spec for hand-calc):
  V_DSS_max_V       = 55 V
  I_D_continuous_A  = 49 A
  I_D_pulsed_A      = 160 A
  R_DS_on_mOhm      = 17.5  (typical)
  T_J_max_C         = 150
  R_theta_JA_K_per_W= 62.5  (worst-case, TO-220, free air)
  P_D_max_W         = 94 W

Hand-calc examples:
  T01: DC, V_DS=10V, I_D=5A, duty=1.0, T_amb=25°C
       P_diss = 10×5×1.0 = 50 W < 94 W   → OK
       T_J = 25 + 50×62.5 = 3150°C        → T_J_exceeded (very high Rth demo)
       Use a lower R_theta for within_soa=True test

  Use R_theta_JA = 1.0 K/W (heatsink) for within-SOA tests.

Covers 12+ tests:
  T01  DC in SOA (low Rth, modest operating point) → within_soa=True
  T02  V_DS exceeds V_DSS → V_DSS_exceeded
  T03  I_D exceeds continuous limit at duty=1.0 → I_D_continuous_exceeded
  T04  High P_diss → T_J > T_J_max → T_J_exceeded
  T05  P_diss exceeds P_D_max → P_D_exceeded
  T06  Pulsed in SOA (duty=0.1) → within_soa=True
  T07  I_D exceeds pulsed limit (duty<1.0) → I_D_pulsed_exceeded
  T08  Multiple simultaneous violations (V_DS + I_D)
  T09  Borderline: V_DS == V_DSS_max → NOT exceeded (strict <)
  T10  Borderline: I_D == I_D_continuous at duty=1.0 → NOT exceeded (strict <=)
  T11  headroom_pct is positive when within SOA, negative when exceeded
  T12  Report fields all present and typed correctly
  T13  LLM tool handler happy path (async)
  T14  LLM tool handler bad args (missing required field)
  T15  LLM tool handler malformed JSON
  T16  Negative V_DS raises ValueError
  T17  Invalid duty_cycle raises ValueError
  T18  I_D_pulsed_A < I_D_continuous_A raises ValueError
  T19  P_diss = V_DS × I_D × duty (parametric duty sweep)
  T20  T_J formula: T_J = T_amb + P_diss × R_theta
  T21  Zero I_D (device off) → within_soa=True, P_diss=0
  T22  High ambient temperature pushes T_J over limit
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_electronics.fet_soa_check import (
    FETSpec,
    FETOperatingPoint,
    FETSOAReport,
    check_fet_soa,
)


# ---------------------------------------------------------------------------
# Reference specs
# ---------------------------------------------------------------------------

def _irfz44n_like(R_theta_JA: float = 1.0) -> FETSpec:
    """IRFZ44N-like spec.  R_theta_JA defaults to 1.0 K/W (heatsink) for tests."""
    return FETSpec(
        part_number="IRFZ44N",
        V_DSS_max_V=55.0,
        I_D_continuous_A=49.0,
        I_D_pulsed_A=160.0,
        R_DS_on_mOhm=17.5,
        T_J_max_C=150.0,
        R_theta_JA_K_per_W=R_theta_JA,
        P_D_max_W=94.0,
    )


def _op(V_DS: float, I_D: float, duty: float = 1.0, T_amb: float = 25.0,
        pulse_ms: float = 1e6) -> FETOperatingPoint:
    return FETOperatingPoint(
        V_DS_V=V_DS,
        I_D_A=I_D,
        pulse_duration_ms=pulse_ms,
        duty_cycle=duty,
        T_ambient_C=T_amb,
    )


# ---------------------------------------------------------------------------
# T01 — DC in SOA → within_soa=True
# ---------------------------------------------------------------------------

def test_t01_dc_within_soa():
    """DC operation (duty=1.0) with low Rth: V_DS=10V, I_D=5A, T_amb=25°C.
    P_diss=50 W < 94 W; T_J = 25 + 50×1.0 = 75°C < 150°C; within_soa=True.
    """
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(10.0, 5.0, duty=1.0, T_amb=25.0)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is True
    assert rpt.soa_violation_modes == []
    assert abs(rpt.P_diss_W - 50.0) < 1e-9
    assert abs(rpt.T_junction_estimate_C - 75.0) < 1e-9
    assert rpt.headroom_pct > 0


# ---------------------------------------------------------------------------
# T02 — V_DS exceeds V_DSS → V_DSS_exceeded
# ---------------------------------------------------------------------------

def test_t02_vds_exceeds_vdss():
    """V_DS=60 V > V_DSS_max=55 V → V_DSS_exceeded violation."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(60.0, 5.0, duty=1.0)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "V_DSS_exceeded" in rpt.soa_violation_modes


# ---------------------------------------------------------------------------
# T03 — I_D exceeds continuous limit at duty=1.0 → I_D_continuous_exceeded
# ---------------------------------------------------------------------------

def test_t03_id_exceeds_continuous():
    """DC: I_D=50 A > I_D_continuous=49 A → I_D_continuous_exceeded."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(5.0, 50.0, duty=1.0)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "I_D_continuous_exceeded" in rpt.soa_violation_modes


# ---------------------------------------------------------------------------
# T04 — High P_diss causes T_J > T_J_max → T_J_exceeded
# ---------------------------------------------------------------------------

def test_t04_high_dissipation_tj_exceeded():
    """V_DS=20V, I_D=10A, duty=1.0, R_theta=2 K/W.
    P_diss=200 W > 94 W → P_D_exceeded;
    T_J = 25 + 200×2 = 425°C > 150°C → T_J_exceeded.
    """
    spec = _irfz44n_like(R_theta_JA=2.0)
    op = _op(20.0, 10.0, duty=1.0)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "T_J_exceeded" in rpt.soa_violation_modes
    assert rpt.T_junction_estimate_C > spec.T_J_max_C


# ---------------------------------------------------------------------------
# T05 — P_diss exceeds P_D_max → P_D_exceeded
# ---------------------------------------------------------------------------

def test_t05_pd_exceeded():
    """V_DS=30V, I_D=10A, duty=0.5, R_theta_JA=0.5 K/W.
    P_diss=30×10×0.5=150 W > 94 W → P_D_exceeded.
    T_J = 25 + 150×0.5 = 100°C < 150°C → no T_J violation.
    """
    spec = _irfz44n_like(R_theta_JA=0.5)
    op = _op(30.0, 10.0, duty=0.5)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "P_D_exceeded" in rpt.soa_violation_modes


# ---------------------------------------------------------------------------
# T06 — Pulsed within SOA (duty=0.1, low V_DS, moderate I_D)
# ---------------------------------------------------------------------------

def test_t06_pulsed_within_soa():
    """Pulsed: V_DS=10V, I_D=50A, duty=0.1.  I_D=50 < I_D_pulsed=160.
    P_diss=10×50×0.1=50 W < 94 W.  T_J=25+50×1=75°C < 150°C → within_soa=True.
    """
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(10.0, 50.0, duty=0.1, pulse_ms=0.1)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is True
    assert rpt.soa_violation_modes == []
    assert abs(rpt.P_diss_W - 50.0) < 1e-9


# ---------------------------------------------------------------------------
# T07 — I_D exceeds pulsed limit (duty < 1.0) → I_D_pulsed_exceeded
# ---------------------------------------------------------------------------

def test_t07_id_exceeds_pulsed():
    """Pulsed: I_D=170 A > I_D_pulsed=160 A → I_D_pulsed_exceeded."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(5.0, 170.0, duty=0.05, pulse_ms=0.01)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "I_D_pulsed_exceeded" in rpt.soa_violation_modes
    # Should NOT flag I_D_continuous_exceeded for pulsed operation
    assert "I_D_continuous_exceeded" not in rpt.soa_violation_modes


# ---------------------------------------------------------------------------
# T08 — Multiple simultaneous violations (V_DS + I_D continuous)
# ---------------------------------------------------------------------------

def test_t08_multiple_violations():
    """V_DS=60V (>55V) AND I_D=55A (>49A DC) → both violations reported."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(60.0, 55.0, duty=1.0)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "V_DSS_exceeded" in rpt.soa_violation_modes
    assert "I_D_continuous_exceeded" in rpt.soa_violation_modes
    assert len(rpt.soa_violation_modes) >= 2


# ---------------------------------------------------------------------------
# T09 — Borderline: V_DS == V_DSS_max → NOT exceeded (strict <=)
# ---------------------------------------------------------------------------

def test_t09_vds_exactly_at_vdss_not_exceeded():
    """V_DS == V_DSS_max=55 V is NOT flagged (strict >)."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(55.0, 1.0, duty=1.0)
    rpt = check_fet_soa(spec, op)
    # V_DS == V_DSS exactly: should NOT flag V_DSS_exceeded
    assert "V_DSS_exceeded" not in rpt.soa_violation_modes


# ---------------------------------------------------------------------------
# T10 — Borderline: I_D == I_D_continuous at duty=1.0 → NOT exceeded
# ---------------------------------------------------------------------------

def test_t10_id_exactly_at_continuous_limit_not_exceeded():
    """I_D = I_D_continuous = 49 A exactly (duty=1.0) → NOT flagged."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    op = _op(5.0, 49.0, duty=1.0)
    rpt = check_fet_soa(spec, op)
    assert "I_D_continuous_exceeded" not in rpt.soa_violation_modes


# ---------------------------------------------------------------------------
# T11 — headroom_pct > 0 within SOA, < 0 when limit exceeded
# ---------------------------------------------------------------------------

def test_t11_headroom_sign():
    """headroom_pct positive within SOA; negative when limit exceeded."""
    spec = _irfz44n_like(R_theta_JA=1.0)

    # Within SOA
    rpt_ok = check_fet_soa(spec, _op(10.0, 5.0))
    assert rpt_ok.headroom_pct > 0

    # V_DS exceeds V_DSS
    rpt_fail = check_fet_soa(spec, _op(60.0, 1.0))
    assert rpt_fail.headroom_pct < 0


# ---------------------------------------------------------------------------
# T12 — Report fields all present and typed correctly
# ---------------------------------------------------------------------------

def test_t12_report_fields_typed():
    """FETSOAReport must expose all documented fields with correct types."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    rpt = check_fet_soa(spec, _op(10.0, 5.0))
    assert isinstance(rpt.within_soa, bool)
    assert isinstance(rpt.P_diss_W, float)
    assert isinstance(rpt.T_junction_estimate_C, float)
    assert isinstance(rpt.soa_violation_modes, list)
    assert isinstance(rpt.headroom_pct, float)
    assert isinstance(rpt.honest_caveat, str)
    assert len(rpt.honest_caveat) > 0


# ---------------------------------------------------------------------------
# T13 — LLM tool handler happy path (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t13_llm_tool_happy_path():
    """electronics_check_fet_soa LLM tool returns ok=True for valid input."""
    from kerf_electronics.fet_soa_check import electronics_check_fet_soa

    args = json.dumps({
        "part_number": "IRFZ44N",
        "V_DSS_max_V": 55.0,
        "I_D_continuous_A": 49.0,
        "I_D_pulsed_A": 160.0,
        "R_DS_on_mOhm": 17.5,
        "T_J_max_C": 150.0,
        "R_theta_JA_K_per_W": 1.0,
        "P_D_max_W": 94.0,
        "V_DS_V": 10.0,
        "I_D_A": 5.0,
        "duty_cycle": 1.0,
        "T_ambient_C": 25.0,
    }).encode()

    result = await electronics_check_fet_soa(None, args)
    payload = json.loads(result)
    assert payload.get("ok") is True
    assert "within_soa" in payload
    assert "P_diss_W" in payload
    assert "T_junction_estimate_C" in payload
    assert "soa_violation_modes" in payload
    assert "headroom_pct" in payload
    assert "honest_caveat" in payload
    assert payload["within_soa"] is True


# ---------------------------------------------------------------------------
# T14 — LLM tool handler bad args (missing required field V_DS_V)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t14_llm_tool_missing_required_field():
    """electronics_check_fet_soa returns error payload when V_DS_V is missing."""
    from kerf_electronics.fet_soa_check import electronics_check_fet_soa

    args = json.dumps({
        "V_DSS_max_V": 55.0,
        "I_D_continuous_A": 49.0,
        "I_D_pulsed_A": 160.0,
        "R_DS_on_mOhm": 17.5,
        "R_theta_JA_K_per_W": 1.0,
        "P_D_max_W": 94.0,
        # missing V_DS_V and I_D_A
    }).encode()

    result = await electronics_check_fet_soa(None, args)
    payload = json.loads(result)
    assert "error" in payload or payload.get("ok") is False or "code" in payload


# ---------------------------------------------------------------------------
# T15 — LLM tool handler malformed JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t15_llm_tool_malformed_json():
    """electronics_check_fet_soa returns error for malformed JSON."""
    from kerf_electronics.fet_soa_check import electronics_check_fet_soa

    result = await electronics_check_fet_soa(None, b"{not valid json{{")
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T16 — Negative V_DS raises ValueError
# ---------------------------------------------------------------------------

def test_t16_negative_vds_raises():
    """Negative V_DS must raise ValueError."""
    spec = _irfz44n_like()
    with pytest.raises(ValueError, match="V_DS_V"):
        check_fet_soa(spec, _op(-1.0, 5.0))


# ---------------------------------------------------------------------------
# T17 — Invalid duty_cycle raises ValueError
# ---------------------------------------------------------------------------

def test_t17_invalid_duty_cycle_raises():
    """duty_cycle=0 or duty_cycle>1.0 must raise ValueError."""
    spec = _irfz44n_like()
    with pytest.raises(ValueError, match="duty_cycle"):
        check_fet_soa(spec, FETOperatingPoint(10.0, 5.0, 1.0, 0.0, 25.0))
    with pytest.raises(ValueError, match="duty_cycle"):
        check_fet_soa(spec, FETOperatingPoint(10.0, 5.0, 1.0, 1.1, 25.0))


# ---------------------------------------------------------------------------
# T18 — I_D_pulsed_A < I_D_continuous_A raises ValueError
# ---------------------------------------------------------------------------

def test_t18_pulsed_less_than_continuous_raises():
    """I_D_pulsed_A < I_D_continuous_A must raise ValueError."""
    with pytest.raises(ValueError, match="I_D_pulsed_A"):
        FETSpec(
            part_number="bad",
            V_DSS_max_V=55.0,
            I_D_continuous_A=49.0,
            I_D_pulsed_A=40.0,   # less than continuous
            R_DS_on_mOhm=17.5,
            T_J_max_C=150.0,
            R_theta_JA_K_per_W=1.0,
            P_D_max_W=94.0,
        )
        # Validation happens inside check_fet_soa, not __init__
        check_fet_soa(
            FETSpec("bad", 55.0, 49.0, 40.0, 17.5, 150.0, 1.0, 94.0),
            _op(10.0, 5.0),
        )


def test_t18b_pulsed_less_than_continuous_raises_in_check():
    """check_fet_soa raises when I_D_pulsed_A < I_D_continuous_A."""
    bad_spec = FETSpec.__new__(FETSpec)
    # Build via object.__setattr__ to bypass any init logic
    object.__setattr__(bad_spec, "part_number", "bad")
    object.__setattr__(bad_spec, "V_DSS_max_V", 55.0)
    object.__setattr__(bad_spec, "I_D_continuous_A", 49.0)
    object.__setattr__(bad_spec, "I_D_pulsed_A", 40.0)
    object.__setattr__(bad_spec, "R_DS_on_mOhm", 17.5)
    object.__setattr__(bad_spec, "T_J_max_C", 150.0)
    object.__setattr__(bad_spec, "R_theta_JA_K_per_W", 1.0)
    object.__setattr__(bad_spec, "P_D_max_W", 94.0)
    with pytest.raises(ValueError, match="I_D_pulsed_A"):
        check_fet_soa(bad_spec, _op(10.0, 5.0))


# ---------------------------------------------------------------------------
# T19 — P_diss = V_DS × I_D × duty (parametric duty sweep)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("duty", [0.1, 0.25, 0.5, 0.75, 1.0])
def test_t19_pdiss_parametric_duty(duty: float):
    """P_diss == V_DS × I_D × duty (exact floating-point check)."""
    spec = _irfz44n_like(R_theta_JA=0.1)  # very low Rth to avoid T_J violation
    V_DS, I_D = 5.0, 3.0
    rpt = check_fet_soa(spec, _op(V_DS, I_D, duty=duty))
    expected = V_DS * I_D * duty
    assert abs(rpt.P_diss_W - expected) < 1e-9


# ---------------------------------------------------------------------------
# T20 — T_J formula: T_J = T_amb + P_diss × R_theta
# ---------------------------------------------------------------------------

def test_t20_tj_formula():
    """T_junction = T_ambient + P_diss × R_theta_JA."""
    spec = _irfz44n_like(R_theta_JA=5.0)
    V_DS, I_D, duty, T_amb = 10.0, 3.0, 0.5, 30.0
    P_expected = V_DS * I_D * duty  # = 15 W
    T_J_expected = T_amb + P_expected * 5.0  # = 30 + 75 = 105
    rpt = check_fet_soa(spec, _op(V_DS, I_D, duty=duty, T_amb=T_amb))
    assert abs(rpt.P_diss_W - P_expected) < 1e-9
    assert abs(rpt.T_junction_estimate_C - T_J_expected) < 1e-9


# ---------------------------------------------------------------------------
# T21 — Zero I_D (device off) → within_soa=True, P_diss=0
# ---------------------------------------------------------------------------

def test_t21_zero_id_device_off():
    """I_D=0 A (device off) → P_diss=0, within_soa=True (assuming V_DS <= V_DSS)."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    rpt = check_fet_soa(spec, _op(30.0, 0.0, duty=1.0))
    assert rpt.P_diss_W == 0.0
    assert rpt.within_soa is True


# ---------------------------------------------------------------------------
# T22 — High ambient temperature pushes T_J over limit
# ---------------------------------------------------------------------------

def test_t22_high_ambient_tj_exceeded():
    """High ambient (T_amb=130°C) + small P_diss → T_J exceeds 150°C limit.
    V_DS=5V, I_D=2A, duty=1.0, R_theta=10 K/W.
    P_diss=10 W; T_J=130+10×10=230°C > 150°C → T_J_exceeded.
    """
    spec = _irfz44n_like(R_theta_JA=10.0)
    op = _op(5.0, 2.0, duty=1.0, T_amb=130.0)
    rpt = check_fet_soa(spec, op)
    assert rpt.within_soa is False
    assert "T_J_exceeded" in rpt.soa_violation_modes
    assert rpt.T_junction_estimate_C > spec.T_J_max_C


# ---------------------------------------------------------------------------
# T23 — honest_caveat always mentions linearised SOA and pulse-width caveats
# ---------------------------------------------------------------------------

def test_t23_honest_caveat_content():
    """honest_caveat must mention linearised SOA and pulse-width limitation."""
    spec = _irfz44n_like(R_theta_JA=1.0)
    rpt = check_fet_soa(spec, _op(10.0, 5.0))
    caveat_lower = rpt.honest_caveat.lower()
    assert "linearised" in caveat_lower or "linearized" in caveat_lower
    assert "pulse" in caveat_lower
    assert "second" in caveat_lower  # second-breakdown caveat


# ---------------------------------------------------------------------------
# T24 — check_fet_soa_from_dict success and error paths
# ---------------------------------------------------------------------------

def test_t24_from_dict_success():
    """check_fet_soa_from_dict returns ok=True for valid dict input."""
    from kerf_electronics.fet_soa_check import check_fet_soa_from_dict

    d = {
        "part_number": "IRFZ44N",
        "V_DSS_max_V": 55.0,
        "I_D_continuous_A": 49.0,
        "I_D_pulsed_A": 160.0,
        "R_DS_on_mOhm": 17.5,
        "T_J_max_C": 150.0,
        "R_theta_JA_K_per_W": 1.0,
        "P_D_max_W": 94.0,
        "V_DS_V": 10.0,
        "I_D_A": 5.0,
    }
    result = check_fet_soa_from_dict(d)
    assert result["ok"] is True
    assert result["within_soa"] is True
    assert "soa_violation_modes" in result


def test_t24b_from_dict_error_missing_key():
    """check_fet_soa_from_dict returns ok=False when a required key is missing."""
    from kerf_electronics.fet_soa_check import check_fet_soa_from_dict

    d = {"V_DSS_max_V": 55.0}  # many required keys missing
    result = check_fet_soa_from_dict(d)
    assert result["ok"] is False
    assert "reason" in result
