"""
Hermetic tests for kerf_electronics.inductor_core_saturation.

Inductor core saturation check — Erickson "Power Electronics" §15 +
McLyman "Transformer and Inductor Design Handbook" §10.

Design equations:
  I_pk  = I_dc + I_ripple_pp / 2
  B_pk  = μ₀ · μ_r · N · I_pk / l_e   [SI units; l_e in metres]
  margin = (B_sat − B_pk) / B_sat × 100  [%]
  saturated = B_pk >= B_sat

Reference hand-calc for T01 (ferrite 3C95, 25°C):
  core: B_sat=500 mT, mu_r=2000, l_e=50 mm=0.050 m
  current: N=50, I_dc=3.0 A, I_ripple_pp=0 A → I_pk=3.0 A
  B_pk = 4π×10⁻⁷ × 2000 × 50 × 3.0 / 0.050
       = 1.2566370614…×10⁻⁶ × 2000 × 150 / 0.050
       = 1.2566370614e-6 × 300000 / 0.050
       = 0.37699… / 0.050
       = 7.53982… T  ← NO — let me redo this

  μ₀ = 4π×10⁻⁷ = 1.25664×10⁻⁶ H/m
  B_pk = 1.25664e-6 × 2000 × 50 × 3.0 / 0.050
       = 1.25664e-6 × 300000 / 0.050
  Numerator = 1.25664e-6 × 300000 = 0.376991
  B_pk = 0.376991 / 0.050 = 7.53982 T
  B_pk_mT = 7539.82 mT >> B_sat=500 mT → SATURATED

  (This is physically correct — 2000 turns·amperes on a 50 mm path with μ_r=2000
   gives enormous B; a realistic winding has far fewer AT or a different mu_r.)

Reference hand-calc for T02 (low-mu powdered iron, N=10, I_dc=3A, l_e=50mm):
  mu_r=75, N=10, I_pk=3.0 A, l_e=0.050 m, B_sat=1400 mT
  B_pk = 1.25664e-6 × 75 × 10 × 3.0 / 0.050
       = 1.25664e-6 × 2250 / 0.050
       = 0.0028274892 / 0.050
       = 0.056549784 T = 56.549784 mT << 1400 mT → NOT saturated

Test inventory (≥ 12 tests):
  T01  3C95, N=50, I_dc=3A, l_e=50mm, mu_r=2000 → saturated (B_pk >> B_sat=500mT)
  T02  Powdered iron -26, N=10, I_dc=3A → large margin (mu_r=75 << ferrite)
  T03  B_pk formula: exact float match against hand-calc
  T04  High I_dc → saturates; low I_dc → margin
  T05  saturation_margin = (B_sat - B_pk) / B_sat * 100  formula check
  T06  Temperature derating: ferrite B_sat drops at 100°C
  T07  Temperature derating: ferrite B_sat drops at 125°C (−25%)
  T08  Temperature derating: no derating for powdered_iron_-26
  T09  Temperature derating: borderline case just passes at 25°C, fails at 100°C
  T10  recommended_max_I_dc: formula check (0.99 × B_sat × l_e / (μ₀ × μ_r × N) − I_ripple/2)
  T11  I_ripple shifts I_pk: higher ripple reduces margin
  T12  N doubles → B_pk doubles → margin shrinks
  T13  ValueError on l_e_mm <= 0
  T14  ValueError on turns_N < 1
  T15  ValueError on I_dc_A < 0
  T16  ValueError on B_sat_mT <= 0
  T17  ValueError on mu_r <= 0
  T18  LLM tool happy path (JSON round-trip, not saturated)
  T19  LLM tool bad JSON
  T20  LLM tool missing required key
  T21  LLM tool saturated case returns saturated=True
  T22  Report fields all present and correctly typed
  T23  sendust core (mu_r=125, B_sat=1000 mT) — not saturated at moderate I_dc
  T24  dict-in/dict-out wrapper happy path
  T25  dict-in/dict-out wrapper bad inputs
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_electronics.inductor_core_saturation import (
    InductorCoreSpec,
    InductorCurrentSpec,
    CoreSaturationReport,
    check_inductor_saturation,
    check_inductor_saturation_from_dict,
    electronics_check_inductor_saturation,
    _MU0,
    _ferrite_bsat_factor,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

REL_TOL = 1e-4  # 0.01% tolerance for numerical comparisons


def _hand_B_pk_mT(mu_r: float, N: int, I_pk: float, l_e_mm: float) -> float:
    """Hand-calculate B_pk in mT."""
    l_e_m = l_e_mm * 1e-3
    return _MU0 * mu_r * N * I_pk / l_e_m * 1e3


def _3c95_core(
    A_e=100.0, l_e=50.0, B_sat=500.0, mu_r=2000.0
) -> InductorCoreSpec:
    return InductorCoreSpec(
        material="ferrite_3C95",
        A_e_mm2=A_e,
        l_e_mm=l_e,
        B_sat_mT=B_sat,
        mu_r=mu_r,
    )


def _pi26_core(
    A_e=100.0, l_e=50.0, B_sat=1400.0, mu_r=75.0
) -> InductorCoreSpec:
    return InductorCoreSpec(
        material="powdered_iron_-26",
        A_e_mm2=A_e,
        l_e_mm=l_e,
        B_sat_mT=B_sat,
        mu_r=mu_r,
    )


def _current(N=50, I_dc=3.0, I_rip=0.0, T=25.0) -> InductorCurrentSpec:
    return InductorCurrentSpec(
        turns_N=N,
        I_dc_A=I_dc,
        I_ripple_peak_to_peak_A=I_rip,
        temperature_C=T,
    )


# ── T01 — ferrite 3C95, N=50, I_dc=3A → saturated ────────────────────────────

def test_t01_3c95_saturated():
    """3C95 with N=50, I_pk=3A, l_e=50mm, mu_r=2000 must be saturated."""
    core = _3c95_core()
    cur = _current(N=50, I_dc=3.0, I_rip=0.0)
    report = check_inductor_saturation(core, cur)

    # Hand-calc: B_pk = μ₀ × 2000 × 50 × 3.0 / 0.050
    B_exp = _hand_B_pk_mT(2000, 50, 3.0, 50.0)
    assert abs(report.B_peak_mT - B_exp) / B_exp < REL_TOL
    assert report.saturated is True
    assert report.saturation_margin_pct < 0.0  # negative → over-saturated


# ── T02 — powdered iron -26, N=10, I_dc=3A → large margin ────────────────────

def test_t02_powdered_iron_low_mu_large_margin():
    """Powdered iron -26 (mu_r=75) at N=10, I_pk=3A should NOT be saturated."""
    core = _pi26_core()
    cur = _current(N=10, I_dc=3.0, I_rip=0.0)
    report = check_inductor_saturation(core, cur)

    B_exp = _hand_B_pk_mT(75.0, 10, 3.0, 50.0)
    assert abs(report.B_peak_mT - B_exp) / B_exp < REL_TOL
    assert report.saturated is False
    assert report.saturation_margin_pct > 90.0  # massive margin


# ── T03 — exact B_pk formula match ────────────────────────────────────────────

def test_t03_bpk_formula_exact():
    """B_pk = μ₀·μ_r·N·I_pk/l_e must match to < 0.01% for multiple cases."""
    cases = [
        # (mu_r, N, I_pk, l_e_mm, B_sat_mT)
        (2000, 20, 1.0, 80.0, 500.0),
        (1500, 30, 0.5, 60.0, 380.0),
        (75, 15, 5.0, 40.0, 1400.0),
        (125, 25, 2.0, 100.0, 1000.0),
    ]
    for mu_r, N, I_pk, l_e_mm, B_sat in cases:
        core = InductorCoreSpec(
            material="ferrite_3C95" if mu_r >= 500 else "powdered_iron_-26",
            A_e_mm2=100.0,
            l_e_mm=l_e_mm,
            B_sat_mT=B_sat,
            mu_r=mu_r,
        )
        cur = InductorCurrentSpec(
            turns_N=N,
            I_dc_A=I_pk,
            I_ripple_peak_to_peak_A=0.0,
        )
        report = check_inductor_saturation(core, cur)
        B_exp = _hand_B_pk_mT(mu_r, N, I_pk, l_e_mm)
        assert abs(report.B_peak_mT - B_exp) / max(B_exp, 1e-6) < REL_TOL, (
            f"mu_r={mu_r}, N={N}: got {report.B_peak_mT:.4f}, expected {B_exp:.4f}"
        )


# ── T04 — high I_dc saturates; low I_dc gives margin ─────────────────────────

def test_t04_high_idc_saturates_low_idc_margin():
    """For a fixed N and core, increasing I_dc eventually causes saturation."""
    # mu_r=200, N=50, l_e=50mm, B_sat=500mT
    # B_pk = μ₀ × 200 × 50 × I / 0.050 = μ₀ × 200000 × I
    # Saturation at I_pk = B_sat_T × l_e / (μ₀ × μ_r × N)
    #   = 0.5 × 0.050 / (μ₀ × 200 × 50)
    core = InductorCoreSpec(
        material="ferrite_3C95",
        A_e_mm2=100.0,
        l_e_mm=50.0,
        B_sat_mT=500.0,
        mu_r=200.0,
    )
    # Low current → not saturated
    low_cur = InductorCurrentSpec(turns_N=50, I_dc_A=0.1, I_ripple_peak_to_peak_A=0.0)
    low_rep = check_inductor_saturation(core, low_cur)
    assert low_rep.saturated is False
    assert low_rep.saturation_margin_pct > 0

    # Compute exact saturation current
    # B_sat = 500 mT = 0.500 T; solve B_sat_T × l_e / (μ₀ × μ_r × N)
    I_sat = 0.500 * 0.050 / (_MU0 * 200 * 50)  # B_sat_T × l_e / (μ₀ × μ_r × N)
    # High current → saturated (use 2× saturation current)
    high_cur = InductorCurrentSpec(turns_N=50, I_dc_A=2.0 * I_sat, I_ripple_peak_to_peak_A=0.0)
    high_rep = check_inductor_saturation(core, high_cur)
    assert high_rep.saturated is True
    assert high_rep.saturation_margin_pct < 0


# ── T05 — saturation_margin formula check ────────────────────────────────────

def test_t05_saturation_margin_formula():
    """saturation_margin = (B_sat - B_pk) / B_sat × 100 exactly."""
    core = _3c95_core(l_e=50.0, mu_r=200.0, B_sat=500.0)
    cur = _current(N=10, I_dc=1.0, I_rip=0.0)
    report = check_inductor_saturation(core, cur)

    expected_margin = (report.B_sat_mT - report.B_peak_mT) / report.B_sat_mT * 100.0
    assert abs(report.saturation_margin_pct - expected_margin) < 1e-4


# ── T06 — temperature derating: 100°C → B_sat drops 15% ─────────────────────

def test_t06_temperature_derating_100c():
    """Ferrite 3C95 B_sat must be 85% of reference at 100°C."""
    core = _3c95_core(B_sat=500.0)
    cur_25 = _current(N=10, I_dc=0.1, I_rip=0.0, T=25.0)
    cur_100 = _current(N=10, I_dc=0.1, I_rip=0.0, T=100.0)

    rep_25 = check_inductor_saturation(core, cur_25)
    rep_100 = check_inductor_saturation(core, cur_100)

    # B_sat_eff at 100°C = 500 × 0.85 = 425 mT
    assert abs(rep_100.B_sat_mT - 500.0 * 0.85) < 0.5
    # B_pk unchanged (same current), but B_sat drops → margin shrinks
    assert rep_100.saturation_margin_pct < rep_25.saturation_margin_pct
    # B_peak should be identical (same current and core path)
    assert abs(rep_25.B_peak_mT - rep_100.B_peak_mT) < 1e-4


# ── T07 — temperature derating: 125°C → B_sat drops 25% ─────────────────────

def test_t07_temperature_derating_125c():
    """Ferrite B_sat must be 75% of reference at 125°C."""
    core = _3c95_core(B_sat=500.0)
    cur = _current(N=10, I_dc=0.1, I_rip=0.0, T=125.0)
    report = check_inductor_saturation(core, cur)

    expected_bsat = 500.0 * 0.75
    assert abs(report.B_sat_mT - expected_bsat) < 0.5


# ── T08 — no derating for powdered iron ──────────────────────────────────────

def test_t08_no_derating_powdered_iron():
    """Powdered iron -26 B_sat must NOT be derated even at 100°C."""
    core = _pi26_core(B_sat=1400.0)
    cur_25 = _current(N=5, I_dc=1.0, I_rip=0.0, T=25.0)
    cur_100 = _current(N=5, I_dc=1.0, I_rip=0.0, T=100.0)

    rep_25 = check_inductor_saturation(core, cur_25)
    rep_100 = check_inductor_saturation(core, cur_100)

    # B_sat_mT must be equal (no derating)
    assert abs(rep_25.B_sat_mT - rep_100.B_sat_mT) < 1e-6
    assert rep_25.B_sat_mT == pytest.approx(1400.0, abs=1e-3)


# ── T09 — borderline: just passes at 25°C, fails at 100°C ────────────────────

def test_t09_borderline_passes_25c_fails_100c():
    """Design that passes at 25°C (B_pk < B_sat) but saturates at 100°C after derating."""
    # B_sat=500 mT @ 25°C → 425 mT @ 100°C
    # Set I_dc such that B_pk is between 425 mT and 500 mT
    # mu_r=200, N=50, l_e=50mm:
    #   I for B_pk=450mT: I = B×l_e / (μ₀ × μ_r × N)
    #                        = 0.450 × 0.050 / (μ₀ × 200 × 50)
    core = InductorCoreSpec(
        material="ferrite_3C95",
        A_e_mm2=100.0,
        l_e_mm=50.0,
        B_sat_mT=500.0,
        mu_r=200.0,
    )
    # Compute I_dc for B_pk = 460 mT (between 425 and 500)
    B_target_T = 0.460
    I_target = B_target_T * 0.050 / (_MU0 * 200 * 50)

    cur_25 = InductorCurrentSpec(turns_N=50, I_dc_A=I_target, I_ripple_peak_to_peak_A=0.0, temperature_C=25.0)
    cur_100 = InductorCurrentSpec(turns_N=50, I_dc_A=I_target, I_ripple_peak_to_peak_A=0.0, temperature_C=100.0)

    rep_25 = check_inductor_saturation(core, cur_25)
    rep_100 = check_inductor_saturation(core, cur_100)

    # At 25°C: B_pk ≈ 460 mT < B_sat=500 mT → not saturated
    assert rep_25.saturated is False, f"Expected not saturated at 25°C, got B_pk={rep_25.B_peak_mT:.1f} mT"
    # At 100°C: B_sat_eff = 425 mT < B_pk ≈ 460 mT → saturated
    assert rep_100.saturated is True, f"Expected saturated at 100°C, got B_pk={rep_100.B_peak_mT:.1f} mT, B_sat={rep_100.B_sat_mT:.1f} mT"


# ── T10 — recommended_max_I_dc formula ───────────────────────────────────────

def test_t10_recommended_max_idc_formula():
    """recommended_max_I_dc_A = 0.99×B_sat×l_e/(μ₀·μ_r·N) - I_ripple/2."""
    B_sat_mT = 500.0
    mu_r = 200.0
    N = 50
    l_e_mm = 50.0
    I_rip = 0.4

    core = InductorCoreSpec(
        material="ferrite_3C95",
        A_e_mm2=100.0,
        l_e_mm=l_e_mm,
        B_sat_mT=B_sat_mT,
        mu_r=mu_r,
    )
    cur = InductorCurrentSpec(turns_N=N, I_dc_A=0.1, I_ripple_peak_to_peak_A=I_rip)
    report = check_inductor_saturation(core, cur)

    # Hand-calc (at 25°C, no derating)
    l_e_m = l_e_mm * 1e-3
    B_sat_T = B_sat_mT * 1e-3
    I_pk_max = 0.99 * B_sat_T * l_e_m / (_MU0 * mu_r * N)
    I_dc_max_exp = max(0.0, I_pk_max - I_rip / 2.0)

    assert abs(report.recommended_max_I_dc_A - I_dc_max_exp) / max(I_dc_max_exp, 1e-9) < REL_TOL


# ── T11 — ripple increases I_pk and reduces margin ────────────────────────────

def test_t11_ripple_reduces_margin():
    """Higher I_ripple_pp increases I_pk and thus B_pk, reducing margin."""
    core = _3c95_core(l_e=50.0, mu_r=200.0, B_sat=500.0)

    cur_no_rip = InductorCurrentSpec(turns_N=50, I_dc_A=0.1, I_ripple_peak_to_peak_A=0.0)
    cur_with_rip = InductorCurrentSpec(turns_N=50, I_dc_A=0.1, I_ripple_peak_to_peak_A=0.5)

    rep_no = check_inductor_saturation(core, cur_no_rip)
    rep_rip = check_inductor_saturation(core, cur_with_rip)

    # I_pk with ripple = 0.1 + 0.25 = 0.35 A > 0.1 A without
    assert rep_rip.B_peak_mT > rep_no.B_peak_mT
    assert rep_rip.saturation_margin_pct < rep_no.saturation_margin_pct


# ── T12 — doubling N doubles B_pk ─────────────────────────────────────────────

def test_t12_double_N_doubles_Bpk():
    """Doubling the turn count doubles B_pk (all else equal)."""
    core = _pi26_core(l_e=50.0, mu_r=75.0, B_sat=1400.0)
    cur_10 = InductorCurrentSpec(turns_N=10, I_dc_A=1.0, I_ripple_peak_to_peak_A=0.0)
    cur_20 = InductorCurrentSpec(turns_N=20, I_dc_A=1.0, I_ripple_peak_to_peak_A=0.0)

    rep_10 = check_inductor_saturation(core, cur_10)
    rep_20 = check_inductor_saturation(core, cur_20)

    ratio = rep_20.B_peak_mT / rep_10.B_peak_mT
    assert abs(ratio - 2.0) / 2.0 < 1e-4, f"Expected 2×, got {ratio:.6f}"


# ── T13 — ValueError on l_e_mm <= 0 ──────────────────────────────────────────

def test_t13_invalid_le_raises():
    """l_e_mm <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="l_e_mm"):
        check_inductor_saturation(
            InductorCoreSpec("ferrite_3C95", 100.0, 0.0, 500.0, 2000.0),
            _current(),
        )
    with pytest.raises(ValueError, match="l_e_mm"):
        check_inductor_saturation(
            InductorCoreSpec("ferrite_3C95", 100.0, -5.0, 500.0, 2000.0),
            _current(),
        )


# ── T14 — ValueError on turns_N < 1 ──────────────────────────────────────────

def test_t14_invalid_turns_raises():
    """turns_N < 1 must raise ValueError."""
    with pytest.raises(ValueError, match="turns_N"):
        check_inductor_saturation(
            _3c95_core(),
            InductorCurrentSpec(turns_N=0, I_dc_A=1.0, I_ripple_peak_to_peak_A=0.0),
        )


# ── T15 — ValueError on I_dc_A < 0 ───────────────────────────────────────────

def test_t15_invalid_idc_raises():
    """I_dc_A < 0 must raise ValueError."""
    with pytest.raises(ValueError, match="I_dc_A"):
        check_inductor_saturation(
            _3c95_core(),
            InductorCurrentSpec(turns_N=10, I_dc_A=-1.0, I_ripple_peak_to_peak_A=0.0),
        )


# ── T16 — ValueError on B_sat_mT <= 0 ────────────────────────────────────────

def test_t16_invalid_bsat_raises():
    """B_sat_mT <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="B_sat_mT"):
        check_inductor_saturation(
            InductorCoreSpec("ferrite_3C95", 100.0, 50.0, 0.0, 2000.0),
            _current(),
        )
    with pytest.raises(ValueError, match="B_sat_mT"):
        check_inductor_saturation(
            InductorCoreSpec("ferrite_3C95", 100.0, 50.0, -10.0, 2000.0),
            _current(),
        )


# ── T17 — ValueError on mu_r <= 0 ────────────────────────────────────────────

def test_t17_invalid_mur_raises():
    """mu_r <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="mu_r"):
        check_inductor_saturation(
            InductorCoreSpec("ferrite_3C95", 100.0, 50.0, 500.0, 0.0),
            _current(),
        )


# ── T18 — LLM tool happy path ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t18_llm_tool_happy_path():
    """LLM tool should return valid JSON with ok=True for valid not-saturated inputs."""
    args = json.dumps({
        "material": "powdered_iron_-26",
        "A_e_mm2": 100.0,
        "l_e_mm": 50.0,
        "B_sat_mT": 1400.0,
        "mu_r": 75.0,
        "turns_N": 10,
        "I_dc_A": 3.0,
        "I_ripple_peak_to_peak_A": 0.0,
        "temperature_C": 25.0,
    }).encode()
    result = await electronics_check_inductor_saturation(None, args)
    data = json.loads(result)
    assert data["ok"] is True
    assert "B_peak_mT" in data
    assert "saturation_margin_pct" in data
    assert data["saturated"] is False


# ── T19 — LLM tool bad JSON ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_llm_tool_bad_json():
    """LLM tool should return error for malformed JSON."""
    result = await electronics_check_inductor_saturation(None, b"{not valid json")
    data = json.loads(result)
    assert data.get("error") or data.get("ok") is False


# ── T20 — LLM tool missing required key ──────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_llm_tool_missing_key():
    """LLM tool should return ok=False when a required key is missing."""
    args = json.dumps({
        "material": "ferrite_3C95",
        "A_e_mm2": 100.0,
        # Missing: l_e_mm, B_sat_mT, mu_r, turns_N, I_dc_A, I_ripple_peak_to_peak_A
    }).encode()
    result = await electronics_check_inductor_saturation(None, args)
    data = json.loads(result)
    assert data.get("ok") is False or "error" in data


# ── T21 — LLM tool saturated case ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t21_llm_tool_saturated_case():
    """LLM tool should correctly report saturated=True when core is over-driven."""
    args = json.dumps({
        "material": "ferrite_3C95",
        "A_e_mm2": 100.0,
        "l_e_mm": 50.0,
        "B_sat_mT": 500.0,
        "mu_r": 2000.0,
        "turns_N": 50,
        "I_dc_A": 3.0,
        "I_ripple_peak_to_peak_A": 0.0,
        "temperature_C": 25.0,
    }).encode()
    result = await electronics_check_inductor_saturation(None, args)
    data = json.loads(result)
    assert data["ok"] is True
    assert data["saturated"] is True
    assert data["saturation_margin_pct"] < 0.0


# ── T22 — Report fields all present and correct types ────────────────────────

def test_t22_report_fields_typed():
    """All CoreSaturationReport fields must be present and correctly typed."""
    core = _pi26_core()
    cur = _current(N=10, I_dc=1.0, I_rip=0.2)
    report = check_inductor_saturation(core, cur)

    assert isinstance(report, CoreSaturationReport)
    assert isinstance(report.B_peak_mT, float)
    assert isinstance(report.B_sat_mT, float)
    assert isinstance(report.saturation_margin_pct, float)
    assert isinstance(report.saturated, bool)
    assert isinstance(report.recommended_max_I_dc_A, float)
    assert isinstance(report.honest_caveat, str)

    # Sanity ranges
    assert report.B_peak_mT > 0
    assert report.B_sat_mT > 0
    assert report.recommended_max_I_dc_A >= 0
    assert len(report.honest_caveat) > 50


# ── T23 — Sendust core at moderate I_dc ──────────────────────────────────────

def test_t23_sendust_not_saturated_moderate_current():
    """Sendust (mu_r=125, B_sat=1000 mT) at N=20, I_dc=2A, l_e=80mm."""
    core = InductorCoreSpec(
        material="sendust",
        A_e_mm2=120.0,
        l_e_mm=80.0,
        B_sat_mT=1000.0,
        mu_r=125.0,
    )
    cur = InductorCurrentSpec(turns_N=20, I_dc_A=2.0, I_ripple_peak_to_peak_A=0.5)
    report = check_inductor_saturation(core, cur)

    # B_pk = μ₀ × 125 × 20 × (2.0 + 0.25) / 0.080
    I_pk = 2.0 + 0.25
    B_exp = _hand_B_pk_mT(125.0, 20, I_pk, 80.0)
    assert abs(report.B_peak_mT - B_exp) / B_exp < REL_TOL
    # Sendust has B_sat=1000mT; with these params B_pk should be well below B_sat
    assert report.saturated is False
    assert "NOTE" in report.honest_caveat  # no-derating note for sendust


# ── T24 — dict-in/dict-out wrapper happy path ─────────────────────────────────

def test_t24_dict_wrapper_happy_path():
    """check_inductor_saturation_from_dict should return ok=True for valid inputs."""
    result = check_inductor_saturation_from_dict({
        "material": "powdered_iron_-26",
        "A_e_mm2": 100.0,
        "l_e_mm": 50.0,
        "B_sat_mT": 1400.0,
        "mu_r": 75.0,
        "turns_N": 10,
        "I_dc_A": 1.0,
        "I_ripple_peak_to_peak_A": 0.0,
    })
    assert result["ok"] is True
    assert result["B_peak_mT"] > 0
    assert result["B_sat_mT"] == pytest.approx(1400.0, abs=0.01)
    assert isinstance(result["honest_caveat"], str)


# ── T25 — dict-in/dict-out wrapper bad inputs ─────────────────────────────────

def test_t25_dict_wrapper_bad_inputs():
    """check_inductor_saturation_from_dict should return ok=False for bad inputs."""
    # Missing required key
    result = check_inductor_saturation_from_dict({
        "material": "ferrite_3C95",
        "A_e_mm2": 100.0,
    })
    assert result["ok"] is False
    assert "reason" in result

    # Invalid mu_r
    result = check_inductor_saturation_from_dict({
        "material": "ferrite_3C95",
        "A_e_mm2": 100.0,
        "l_e_mm": 50.0,
        "B_sat_mT": 500.0,
        "mu_r": -10.0,
        "turns_N": 50,
        "I_dc_A": 1.0,
        "I_ripple_peak_to_peak_A": 0.0,
    })
    assert result["ok"] is False


# ── T26 — _ferrite_bsat_factor interpolation ──────────────────────────────────

def test_t26_ferrite_derating_interpolation():
    """_ferrite_bsat_factor should interpolate and boundary correctly."""
    # At 25°C → 1.00
    assert _ferrite_bsat_factor(25.0) == pytest.approx(1.00, abs=1e-6)
    # At 100°C → 0.85
    assert _ferrite_bsat_factor(100.0) == pytest.approx(0.85, abs=1e-6)
    # At 125°C → 0.75
    assert _ferrite_bsat_factor(125.0) == pytest.approx(0.75, abs=1e-6)
    # At 150°C → 0.60
    assert _ferrite_bsat_factor(150.0) == pytest.approx(0.60, abs=1e-6)
    # At 200°C → 0.50
    assert _ferrite_bsat_factor(200.0) == pytest.approx(0.50, abs=1e-6)
    # Below 25°C → 1.00 (clamped)
    assert _ferrite_bsat_factor(0.0) == pytest.approx(1.00, abs=1e-6)
    # At 62.5°C (midpoint 25–100) → 0.925
    expected_62_5 = 1.00 + (0.85 - 1.00) * (62.5 - 25.0) / (100.0 - 25.0)
    assert _ferrite_bsat_factor(62.5) == pytest.approx(expected_62_5, abs=1e-6)
    # Monotonically decreasing over range
    prev = _ferrite_bsat_factor(25.0)
    for t in [50, 75, 100, 125, 150, 175, 200]:
        curr = _ferrite_bsat_factor(float(t))
        assert curr <= prev, f"Expected decreasing at T={t}°C"
        prev = curr
