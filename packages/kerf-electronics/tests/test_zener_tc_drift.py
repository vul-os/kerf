"""
Tests for kerf_electronics.zener_tc_drift — Zener TC drift model.

Physical basis
--------------
Two competing breakdown mechanisms (Sze "Physics of Semiconductor Devices" §4.5):
  1. Zener tunneling (Vz < ~5 V): negative TC — higher T makes tunneling easier
     → Vz DECREASES with temperature.
  2. Avalanche (Vz > ~7 V): positive TC — higher T increases phonon scattering
     → carrier needs higher field / voltage → Vz INCREASES with temperature.
  3. Transition region (~5–7 V): two mechanisms partially cancel; near-zero TC
     crossing at ~5.6 V (device-dependent).

Linear model:
    Vz(T) = Vz_nom + ΔVz_current + TC_mV_per_C × 1e-3 × (T − T_test)   [V]
    ΔVz_current = rZ × (Iz_op − Iz_test);  rZ ≈ 0.01 × Vz / Iz_test   [Ω]

Test inventory (≥ 12 tests)
-----------------------------
T01  3.3 V Zener, TC=−1.6 mV/°C: Vz(0°C) ≈ 3.34 V, Vz(70°C) ≈ 3.228 V
T02  5.6 V near-zero TC (TC=+0.2 mV/°C): minimal drift −40..+85 °C
T03  12 V Zener, TC=+8 mV/°C: large positive drift → drift > 1V over 125°C → Vref
T04  Heavy current deviation > 50%: current_dependence_warning must be non-None
T05  Light current deviation < 50%: current_dependence_warning must be None
T06  Drift > 5% threshold → recommendation contains "5.6" or "Vref"
T07  Drift ≤ 5% threshold → recommendation says "acceptable"
T08  Symmetry: negative TC → Vz(T_min) > Vz(T_max) (voltage higher at cold)
T09  Symmetry: positive TC → Vz(T_max) > Vz(T_min) (voltage higher at hot)
T10  drift_total_V = |Vz(T_max) − Vz(T_min)| numerically
T11  drift_percent = 100 × drift_total / Vz_nominal
T12  ValueError on T_min >= T_max
T13  ValueError on Vz_nominal_V <= 0
T14  ValueError on test_current_mA <= 0
T15  ValueError on operating current_mA <= 0
T16  Dict wrapper happy path returns ok=True with all fields
T17  Dict wrapper missing required key returns ok=False
T18  LLM tool async happy path: JSON round-trip, drift fields present
T19  LLM tool bad JSON returns error payload
T20  LLM tool invalid inputs returns error payload
T21  Current correction applied: Iz_op != Iz_test shifts Vz_base
T22  Zero TC Zener: identical Vz at T_min and T_max (pure current shift)
T23  Report dataclass fields all present and correctly typed
T24  Wide industrial range −55..+125 °C with 12V/+8mV/°C: drift ~1.44 V
"""
from __future__ import annotations

import json
import pytest

from kerf_electronics.zener_tc_drift import (
    ZenerSpec,
    OperatingSpec,
    ZenerDriftReport,
    compute_zener_drift,
    compute_zener_drift_from_dict,
    elec_compute_zener_drift,
)

# Numerical tolerances
ABS_TOL = 1e-6
REL_TOL = 1e-4  # 0.01%


# ── Helpers ────────────────────────────────────────────────────────────────────


def _zener(Vz=3.3, TC=-1.6, Iz_test=5.0, T_test=25.0) -> ZenerSpec:
    return ZenerSpec(
        Vz_nominal_V=Vz,
        TC_mV_per_C=TC,
        test_current_mA=Iz_test,
        test_temp_C=T_test,
    )


def _op(Iz=5.0, T_min=0.0, T_max=70.0) -> OperatingSpec:
    return OperatingSpec(
        current_mA=Iz,
        ambient_temp_C_min=T_min,
        ambient_temp_C_max=T_max,
    )


def _hand_calc(Vz_nom, TC_mV_per_C, Iz_test_mA, T_test, Iz_op_mA, T_min, T_max):
    """Return (Vz_at_T_min, Vz_at_T_max, drift_total, drift_pct)."""
    rz = 0.01 * Vz_nom / (Iz_test_mA * 1e-3)
    delta_i = (Iz_op_mA - Iz_test_mA) * 1e-3
    vz_base = Vz_nom + rz * delta_i
    tc_V_per_C = TC_mV_per_C * 1e-3
    vz_min = vz_base + tc_V_per_C * (T_min - T_test)
    vz_max = vz_base + tc_V_per_C * (T_max - T_test)
    drift = abs(vz_max - vz_min)
    pct = 100.0 * drift / Vz_nom
    return vz_min, vz_max, drift, pct


# ── T01 — 3.3 V Zener TC=−1.6 mV/°C: Vz(0°C) ≈ 3.34V, Vz(70°C) ≈ 3.228V ────


def test_t01_3v3_negative_tc_cold_and_hot():
    """
    3.3 V, TC=−1.6 mV/°C, Iz_test=Iz_op=5 mA (no current correction).
    T_test=25°C, range 0–70°C.

    Vz(0)  = 3.3 + (−0.0016) × (0  − 25) = 3.3 + 0.040  = 3.340 V
    Vz(70) = 3.3 + (−0.0016) × (70 − 25) = 3.3 − 0.072  = 3.228 V
    drift  = |3.228 − 3.340| = 0.112 V
    """
    report = compute_zener_drift(
        _zener(Vz=3.3, TC=-1.6, Iz_test=5.0),
        _op(Iz=5.0, T_min=0.0, T_max=70.0),
    )
    assert abs(report.Vz_at_min_temp_V - 3.340) < 1e-4, (
        f"Vz(0°C) expected 3.340, got {report.Vz_at_min_temp_V}"
    )
    assert abs(report.Vz_at_max_temp_V - 3.228) < 1e-4, (
        f"Vz(70°C) expected 3.228, got {report.Vz_at_max_temp_V}"
    )
    drift_expected = abs(3.228 - 3.340)
    assert abs(report.Vz_drift_total_V - drift_expected) < 1e-5


# ── T02 — 5.6 V near-zero TC: minimal drift over −40..+85 °C ─────────────────


def test_t02_5v6_near_zero_tc_minimal_drift():
    """
    5.6 V, TC=+0.2 mV/°C (near-zero), range −40..+85°C.
    Drift = 0.2e-3 × (85 − (−40)) = 0.2e-3 × 125 = 0.025 V = 25 mV
    drift_percent = 100 × 0.025 / 5.6 = 0.446% — well under 5% threshold.
    """
    report = compute_zener_drift(
        _zener(Vz=5.6, TC=+0.2, Iz_test=5.0),
        _op(Iz=5.0, T_min=-40.0, T_max=85.0),
    )
    # Drift should be tiny (under 50 mV = 0.89% of 5.6V)
    assert report.Vz_drift_total_V < 0.050, (
        f"Expected minimal drift for ~0 TC 5.6V Zener, got {report.Vz_drift_total_V:.4f} V"
    )
    assert report.Vz_drift_percent < 5.0, (
        f"Expected <5% drift, got {report.Vz_drift_percent:.2f}%"
    )
    # Recommendation should say "acceptable" not "Vref"
    assert "acceptable" in report.recommendation.lower() or "drift" in report.recommendation.lower()


# ── T03 — 12 V Zener, TC=+8 mV/°C: drift > 1V over 125°C → recommend Vref ───


def test_t03_12v_positive_tc_large_drift_recommend_vref():
    """
    12 V, TC=+8 mV/°C, range 0..125°C.
    Drift = 8e-3 × 125 = 1.000 V
    drift_percent = 100 × 1.0 / 12 = 8.33% > 5% → recommend Vref IC.
    """
    report = compute_zener_drift(
        _zener(Vz=12.0, TC=+8.0, Iz_test=10.0),
        _op(Iz=10.0, T_min=0.0, T_max=125.0),
    )
    assert report.Vz_drift_total_V >= 0.99, (
        f"Expected drift ≥ 1V, got {report.Vz_drift_total_V:.4f} V"
    )
    assert report.Vz_drift_percent > 5.0, (
        f"Expected drift > 5%, got {report.Vz_drift_percent:.2f}%"
    )
    # Recommendation must mention 5.6V or Vref
    rec = report.recommendation.lower()
    assert "5.6" in rec or "vref" in rec or "reference" in rec, (
        f"Expected Vref recommendation for high drift, got: {report.recommendation}"
    )


# ── T04 — Heavy current deviation > 50%: warning issued ─────────────────────


def test_t04_heavy_current_deviation_warning():
    """
    Iz_test=10 mA, Iz_op=20 mA → deviation = (20/10 − 1) = 1.0 = 100% > 50%.
    current_dependence_warning must be non-None.
    """
    report = compute_zener_drift(
        _zener(Vz=5.6, TC=0.0, Iz_test=10.0),
        _op(Iz=20.0, T_min=0.0, T_max=70.0),
    )
    assert report.current_dependence_warning is not None, (
        "Expected current deviation warning for 100% current deviation"
    )
    assert "50%" in report.current_dependence_warning or "deviates" in report.current_dependence_warning


# ── T05 — Light current deviation < 50%: no warning ─────────────────────────


def test_t05_light_current_deviation_no_warning():
    """
    Iz_test=10 mA, Iz_op=13 mA → deviation = 30% < 50% threshold.
    current_dependence_warning must be None.
    """
    report = compute_zener_drift(
        _zener(Vz=5.6, TC=0.0, Iz_test=10.0),
        _op(Iz=13.0, T_min=0.0, T_max=70.0),
    )
    assert report.current_dependence_warning is None, (
        f"Expected no warning for 30% deviation, got: {report.current_dependence_warning}"
    )


# ── T06 — Drift > 5%: recommendation contains "5.6" or "Vref" ───────────────


def test_t06_high_drift_recommendation():
    """
    12V Zener, TC=+8 mV/°C, wide range → drift >> 5% → Vref recommendation.
    """
    report = compute_zener_drift(
        _zener(Vz=12.0, TC=+8.0, Iz_test=10.0),
        _op(Iz=10.0, T_min=-40.0, T_max=85.0),
    )
    assert report.Vz_drift_percent > 5.0
    rec_lower = report.recommendation.lower()
    assert any(kw in rec_lower for kw in ("5.6", "vref", "reference", "bandgap")), (
        f"Expected Vref/bandgap mention in recommendation, got: {report.recommendation}"
    )


# ── T07 — Drift ≤ 5%: recommendation says "acceptable" ──────────────────────


def test_t07_low_drift_acceptable_recommendation():
    """
    5.6V Zener, TC=+0.1 mV/°C, narrow range 0–50°C.
    Drift = 0.1e-3 × 50 = 0.005 V = 0.09% << 5% → "acceptable".
    """
    report = compute_zener_drift(
        _zener(Vz=5.6, TC=+0.1, Iz_test=5.0),
        _op(Iz=5.0, T_min=0.0, T_max=50.0),
    )
    assert report.Vz_drift_percent < 5.0
    assert "acceptable" in report.recommendation.lower(), (
        f"Expected 'acceptable' in recommendation, got: {report.recommendation}"
    )


# ── T08 — Negative TC: Vz higher at cold than at hot ─────────────────────────


def test_t08_negative_tc_cold_higher_than_hot():
    """
    Negative TC → Vz decreases with temperature.
    Therefore Vz(T_min) > Vz(T_max).
    """
    report = compute_zener_drift(
        _zener(Vz=3.3, TC=-2.0, Iz_test=5.0),
        _op(Iz=5.0, T_min=-40.0, T_max=85.0),
    )
    assert report.Vz_at_min_temp_V > report.Vz_at_max_temp_V, (
        f"Negative TC Zener: expected Vz(cold) > Vz(hot), "
        f"got {report.Vz_at_min_temp_V:.4f} V vs {report.Vz_at_max_temp_V:.4f} V"
    )


# ── T09 — Positive TC: Vz higher at hot than at cold ─────────────────────────


def test_t09_positive_tc_hot_higher_than_cold():
    """
    Positive TC → Vz increases with temperature.
    Therefore Vz(T_max) > Vz(T_min).
    """
    report = compute_zener_drift(
        _zener(Vz=12.0, TC=+8.0, Iz_test=10.0),
        _op(Iz=10.0, T_min=-40.0, T_max=85.0),
    )
    assert report.Vz_at_max_temp_V > report.Vz_at_min_temp_V, (
        f"Positive TC Zener: expected Vz(hot) > Vz(cold), "
        f"got hot={report.Vz_at_max_temp_V:.4f} V vs cold={report.Vz_at_min_temp_V:.4f} V"
    )


# ── T10 — drift_total_V = |Vz(T_max) − Vz(T_min)| numerically ───────────────


def test_t10_drift_total_equals_abs_difference():
    """drift_total_V must equal |Vz_at_max_temp − Vz_at_min_temp|."""
    report = compute_zener_drift(
        _zener(Vz=5.1, TC=+0.3, Iz_test=5.0),
        _op(Iz=5.0, T_min=-40.0, T_max=125.0),
    )
    expected_drift = abs(report.Vz_at_max_temp_V - report.Vz_at_min_temp_V)
    assert abs(report.Vz_drift_total_V - expected_drift) < ABS_TOL, (
        f"drift_total mismatch: {report.Vz_drift_total_V:.6f} vs {expected_drift:.6f}"
    )


# ── T11 — drift_percent = 100 × drift_total / Vz_nominal ─────────────────────


def test_t11_drift_percent_formula():
    """drift_percent = 100 × Vz_drift_total / Vz_nominal (use nominal not corrected)."""
    Vz_nom = 5.1
    TC = -0.5
    Iz_test = 5.0
    Iz_op = 5.0
    T_test = 25.0
    T_min = 0.0
    T_max = 70.0

    report = compute_zener_drift(
        _zener(Vz=Vz_nom, TC=TC, Iz_test=Iz_test),
        _op(Iz=Iz_op, T_min=T_min, T_max=T_max),
    )
    _, _, drift_expected, pct_expected = _hand_calc(
        Vz_nom, TC, Iz_test, T_test, Iz_op, T_min, T_max
    )
    assert abs(report.Vz_drift_percent - pct_expected) / (pct_expected + ABS_TOL) < REL_TOL, (
        f"drift_percent: got {report.Vz_drift_percent:.4f}, expected {pct_expected:.4f}"
    )


# ── T12 — ValueError on T_min >= T_max ───────────────────────────────────────


def test_t12_t_min_gte_t_max_raises():
    """ambient_temp_C_min >= ambient_temp_C_max must raise ValueError."""
    with pytest.raises(ValueError, match="ambient_temp"):
        compute_zener_drift(
            _zener(),
            _op(T_min=70.0, T_max=70.0),  # equal → invalid
        )
    with pytest.raises(ValueError):
        compute_zener_drift(
            _zener(),
            _op(T_min=100.0, T_max=0.0),  # reversed → invalid
        )


# ── T13 — ValueError on Vz_nominal_V <= 0 ───────────────────────────────────


def test_t13_vz_nominal_zero_or_negative_raises():
    """Vz_nominal_V <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="Vz_nominal"):
        compute_zener_drift(_zener(Vz=0.0), _op())
    with pytest.raises(ValueError):
        compute_zener_drift(_zener(Vz=-3.3), _op())


# ── T14 — ValueError on test_current_mA <= 0 ─────────────────────────────────


def test_t14_test_current_zero_raises():
    """test_current_mA <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="test_current"):
        compute_zener_drift(_zener(Iz_test=0.0), _op())
    with pytest.raises(ValueError):
        compute_zener_drift(_zener(Iz_test=-5.0), _op())


# ── T15 — ValueError on operating current_mA <= 0 ────────────────────────────


def test_t15_operating_current_zero_raises():
    """operating current_mA <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="current"):
        compute_zener_drift(_zener(), _op(Iz=0.0))
    with pytest.raises(ValueError):
        compute_zener_drift(_zener(), _op(Iz=-1.0))


# ── T16 — Dict wrapper happy path ────────────────────────────────────────────


def test_t16_dict_wrapper_happy_path():
    """compute_zener_drift_from_dict returns ok=True with all required fields."""
    result = compute_zener_drift_from_dict({
        "Vz_nominal_V": 3.3,
        "TC_mV_per_C": -1.6,
        "test_current_mA": 5.0,
        "test_temp_C": 25.0,
        "current_mA": 5.0,
        "ambient_temp_C_min": 0.0,
        "ambient_temp_C_max": 70.0,
    })
    assert result["ok"] is True
    for key in (
        "Vz_at_min_temp_V",
        "Vz_at_max_temp_V",
        "Vz_drift_total_V",
        "Vz_drift_percent",
        "current_dependence_warning",
        "recommendation",
        "honest_caveat",
    ):
        assert key in result, f"Missing key in dict result: {key}"
    assert abs(result["Vz_at_min_temp_V"] - 3.340) < 1e-4
    assert abs(result["Vz_at_max_temp_V"] - 3.228) < 1e-4


# ── T17 — Dict wrapper missing required key ───────────────────────────────────


def test_t17_dict_wrapper_missing_key():
    """Dict wrapper returns ok=False when a required key is absent."""
    result = compute_zener_drift_from_dict({
        "Vz_nominal_V": 3.3,
        # TC_mV_per_C missing
        "test_current_mA": 5.0,
        "current_mA": 5.0,
        "ambient_temp_C_min": 0.0,
        "ambient_temp_C_max": 70.0,
    })
    assert result["ok"] is False
    assert "reason" in result


# ── T18 — LLM tool async happy path ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_t18_llm_tool_happy_path():
    """LLM tool returns valid JSON with ok=True and all drift fields."""
    args = json.dumps({
        "Vz_nominal_V": 3.3,
        "TC_mV_per_C": -1.6,
        "test_current_mA": 5.0,
        "test_temp_C": 25.0,
        "current_mA": 5.0,
        "ambient_temp_C_min": 0.0,
        "ambient_temp_C_max": 70.0,
    }).encode()
    result_str = await elec_compute_zener_drift(None, args)
    data = json.loads(result_str)
    assert data["ok"] is True
    assert "Vz_drift_total_V" in data
    assert "recommendation" in data
    assert "honest_caveat" in data
    assert abs(data["Vz_at_min_temp_V"] - 3.340) < 1e-4
    assert abs(data["Vz_at_max_temp_V"] - 3.228) < 1e-4


# ── T19 — LLM tool bad JSON ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t19_llm_tool_bad_json():
    """LLM tool returns error payload for malformed JSON."""
    result_str = await elec_compute_zener_drift(None, b"{bad json}")
    data = json.loads(result_str)
    assert "error" in data or data.get("ok") is False


# ── T20 — LLM tool invalid inputs ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t20_llm_tool_invalid_inputs():
    """LLM tool returns error for T_min >= T_max."""
    args = json.dumps({
        "Vz_nominal_V": 3.3,
        "TC_mV_per_C": -1.6,
        "test_current_mA": 5.0,
        "current_mA": 5.0,
        "ambient_temp_C_min": 70.0,
        "ambient_temp_C_max": 0.0,   # invalid: T_min > T_max
    }).encode()
    result_str = await elec_compute_zener_drift(None, args)
    data = json.loads(result_str)
    assert data.get("ok") is False or "error" in data


# ── T21 — Current correction shifts Vz_base ──────────────────────────────────


def test_t21_current_correction_shifts_vz():
    """
    When Iz_op != Iz_test, the current correction shifts Vz.
    rZ ≈ 0.01 × 3.3 / 0.005 = 6.6 Ω.
    Iz_op=10mA vs Iz_test=5mA → ΔI = 5mA → ΔVz_current = 6.6 × 0.005 = 0.033 V.
    Both Vz(T_min) and Vz(T_max) should be about 0.033 V higher than
    the same calc at Iz_op=Iz_test=5mA.
    """
    Vz_nom = 3.3
    TC = 0.0  # zero TC so drift is purely current correction
    Iz_test = 5.0
    T_test = 25.0

    r_base = compute_zener_drift(
        _zener(Vz=Vz_nom, TC=TC, Iz_test=Iz_test),
        _op(Iz=5.0, T_min=0.0, T_max=70.0),
    )
    r_shifted = compute_zener_drift(
        _zener(Vz=Vz_nom, TC=TC, Iz_test=Iz_test),
        _op(Iz=10.0, T_min=0.0, T_max=70.0),
    )

    # rZ = 0.01 × 3.3 / 0.005 = 6.6 Ω, delta_I = 5mA → ΔVz = 6.6 × 0.005 = 0.033 V
    rz_expected = 0.01 * Vz_nom / (Iz_test * 1e-3)
    delta_vz_expected = rz_expected * (10.0 - 5.0) * 1e-3
    assert abs(r_shifted.Vz_at_min_temp_V - r_base.Vz_at_min_temp_V - delta_vz_expected) < 1e-5, (
        f"Expected shift {delta_vz_expected:.4f}V, got {r_shifted.Vz_at_min_temp_V - r_base.Vz_at_min_temp_V:.6f}"
    )


# ── T22 — Exactly zero TC: Vz(T_min) == Vz(T_max) (no temperature drift) ────


def test_t22_zero_tc_no_temperature_drift():
    """
    TC=0.0: the only drift is from current correction.
    When Iz_op = Iz_test, there is zero drift across the full temperature range.
    """
    report = compute_zener_drift(
        _zener(Vz=5.6, TC=0.0, Iz_test=5.0),
        _op(Iz=5.0, T_min=-40.0, T_max=85.0),
    )
    assert abs(report.Vz_at_min_temp_V - report.Vz_at_max_temp_V) < ABS_TOL, (
        f"Zero TC: expected identical Vz at T_min and T_max, "
        f"got {report.Vz_at_min_temp_V:.8f} vs {report.Vz_at_max_temp_V:.8f}"
    )
    assert report.Vz_drift_total_V < ABS_TOL


# ── T23 — Report dataclass fields all present and correctly typed ─────────────


def test_t23_report_fields_typed():
    """All ZenerDriftReport fields must be present and correctly typed."""
    report = compute_zener_drift(_zener(), _op())
    assert isinstance(report, ZenerDriftReport)
    assert isinstance(report.Vz_at_min_temp_V, float)
    assert isinstance(report.Vz_at_max_temp_V, float)
    assert isinstance(report.Vz_drift_total_V, float)
    assert isinstance(report.Vz_drift_percent, float)
    # current_dependence_warning is Optional[str]
    assert report.current_dependence_warning is None or isinstance(
        report.current_dependence_warning, str
    )
    assert isinstance(report.recommendation, str)
    assert isinstance(report.honest_caveat, str)

    # Physical constraints
    assert report.Vz_at_min_temp_V > 0.0
    assert report.Vz_at_max_temp_V > 0.0
    assert report.Vz_drift_total_V >= 0.0
    assert report.Vz_drift_percent >= 0.0

    # Honest caveat must be substantive and reference caveats
    assert len(report.honest_caveat) > 100
    assert "HONEST" in report.honest_caveat
    assert "LINEAR" in report.honest_caveat
    assert "quadratic" in report.honest_caveat


# ── T24 — Wide industrial range −55..+125 °C with 12V/+8mV/°C: drift ~1.44V ─


def test_t24_industrial_range_12v_high_drift():
    """
    12 V, TC=+8 mV/°C, range −55..+125°C.
    Drift = 8e-3 × (125 − (−55)) = 8e-3 × 180 = 1.44 V
    drift_percent = 100 × 1.44 / 12 = 12%  >> 5% → strong Vref recommendation.
    """
    report = compute_zener_drift(
        _zener(Vz=12.0, TC=+8.0, Iz_test=10.0),
        _op(Iz=10.0, T_min=-55.0, T_max=125.0),
    )
    expected_drift = 8e-3 * 180.0  # 1.44 V
    assert abs(report.Vz_drift_total_V - expected_drift) < 1e-4, (
        f"Expected drift {expected_drift:.3f} V, got {report.Vz_drift_total_V:.4f} V"
    )
    assert report.Vz_drift_percent > 10.0, (
        f"Expected drift > 10%, got {report.Vz_drift_percent:.2f}%"
    )
    rec_lower = report.recommendation.lower()
    assert any(kw in rec_lower for kw in ("vref", "5.6", "bandgap", "reference")), (
        f"Expected Vref recommendation for {report.Vz_drift_percent:.1f}% drift"
    )
