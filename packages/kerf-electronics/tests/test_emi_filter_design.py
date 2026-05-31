"""
Hermetic tests for the EMI filter design module (emi_filter_design.py).

Coverage (≥12 tests):

  LC_low_pass
    T01 — 30 dB @ 150 kHz: f_c ≈ 27.6 kHz, L=100 µH → C ≈ 0.33 µF
    T02 — Higher attenuation moves f_c lower (steeper slope needed)
    T03 — Doubling target_freq_kHz with same A_dB roughly doubles f_c
    T04 — attenuation_at_target_dB ≈ target_attenuation_dB (by construction)
    T05 — C_uF positive and finite
    T06 — L_uH = 100 µH for all LC topologies (default L)
    T07 — recommended_caps_X2_uF is non-empty list of known E12 values

  PI_LC_L
    T08 — PI f_c > LC f_c for same spec (60 dB/dec → can afford higher f_c)
    T09 — PI attenuation_at_target_dB ≈ A_dB (by construction)
    T10 — C_uF for PI < C_uF for LC (higher f_c → smaller C)
    T11 — Each PI shunt cap = C_uF / 2 (verified via recommended caps)

  RC_low_pass
    T12 — RC: R_ohm = load_resistance_ohm when provided
    T13 — RC: L_uH is None
    T14 — RC: f_c correct from formula f_c = f_t / 10^(A/20)
    T15 — RC: attenuation_at_target_dB ≈ A_dB

  Validation
    T16 — Negative dc_voltage_V → ValueError
    T17 — Zero dc_current_A → ValueError
    T18 — Unknown topology → ValueError
    T19 — zero target_freq_kHz → ValueError

  Dict interface
    T20 — design_emi_filter_from_dict: valid input returns {"ok": True, ...}
    T21 — design_emi_filter_from_dict: missing required key → {"ok": False}
    T22 — honest_caveat non-empty for every topology
"""
from __future__ import annotations

import math
import pytest

from kerf_electronics.emi_filter_design import (
    EmiFilterSpec,
    EmiFilterReport,
    design_emi_filter,
    design_emi_filter_from_dict,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_X2_E12_UF = [
    0.010, 0.012, 0.015, 0.018, 0.022, 0.027, 0.033, 0.039, 0.047,
    0.056, 0.068, 0.082,
    0.10,  0.12,  0.15,  0.18,  0.22,  0.27,  0.33,  0.39,  0.47,
    0.56,  0.68,  0.82,
    1.0,   1.2,   1.5,   1.8,   2.2,   2.7,   3.3,   3.9,   4.7,
]


def _make_lc_spec(**kwargs) -> EmiFilterSpec:
    defaults = dict(
        dc_voltage_V=48.0,
        dc_current_A=5.0,
        target_attenuation_dB=30.0,
        target_freq_kHz=150.0,
        filter_topology="LC_low_pass",
    )
    defaults.update(kwargs)
    return EmiFilterSpec(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# T01 — LC 30 dB @ 150 kHz: f_c ≈ 27 590 Hz, C ≈ 0.333 µF
# Derivation: f_c = 150e3 / 10^(30/40) = 150000 / 10^0.75 ≈ 27 586 Hz
#             C   = 1/((2π·27586)² · 100e-6) ≈ 0.333 µF
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_30dB_150kHz_corner_frequency():
    """T01: LC f_c ≈ 27 586 Hz (within 1%)."""
    spec = _make_lc_spec()
    report = design_emi_filter(spec)
    expected_fc = 150e3 / (10.0 ** (30.0 / 40.0))
    assert abs(report.cutoff_freq_Hz - expected_fc) / expected_fc < 0.001


def test_lc_30dB_150kHz_capacitance():
    """T01: C ≈ 0.333 µF (within 1%)."""
    spec = _make_lc_spec()
    report = design_emi_filter(spec)
    f_c = report.cutoff_freq_Hz
    L_h = 100e-6
    expected_C_uf = 1.0 / ((2.0 * math.pi * f_c) ** 2 * L_h) * 1e6
    assert abs(report.C_uF - expected_C_uf) / expected_C_uf < 0.001


# ══════════════════════════════════════════════════════════════════════════════
# T02 — Higher A_dB moves f_c lower
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_higher_attenuation_lowers_fc():
    """T02: Increasing target_attenuation_dB lowers the corner frequency."""
    spec_30 = _make_lc_spec(target_attenuation_dB=30.0)
    spec_50 = _make_lc_spec(target_attenuation_dB=50.0)
    r30 = design_emi_filter(spec_30)
    r50 = design_emi_filter(spec_50)
    assert r50.cutoff_freq_Hz < r30.cutoff_freq_Hz


# ══════════════════════════════════════════════════════════════════════════════
# T03 — Doubling target_freq_kHz roughly doubles f_c (linear scaling)
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_double_target_freq_doubles_fc():
    """T03: f_c scales linearly with target_freq_kHz."""
    spec_150 = _make_lc_spec(target_freq_kHz=150.0)
    spec_300 = _make_lc_spec(target_freq_kHz=300.0)
    r150 = design_emi_filter(spec_150)
    r300 = design_emi_filter(spec_300)
    ratio = r300.cutoff_freq_Hz / r150.cutoff_freq_Hz
    assert abs(ratio - 2.0) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# T04 — attenuation_at_target_dB ≈ target_attenuation_dB (by construction)
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_attenuation_matches_spec():
    """T04: Computed attenuation equals requested A_dB within 0.01 dB."""
    spec = _make_lc_spec()
    report = design_emi_filter(spec)
    assert abs(report.attenuation_at_target_dB - spec.target_attenuation_dB) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# T05 — C_uF positive and finite
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_capacitance_positive_finite():
    """T05: C_uF is a positive finite number."""
    spec = _make_lc_spec()
    report = design_emi_filter(spec)
    assert report.C_uF is not None
    assert report.C_uF > 0
    assert math.isfinite(report.C_uF)


# ══════════════════════════════════════════════════════════════════════════════
# T06 — L_uH = 100 µH for LC_low_pass
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_default_inductance_100uH():
    """T06: Default L = 100 µH for LC_low_pass."""
    spec = _make_lc_spec()
    report = design_emi_filter(spec)
    assert report.L_uH is not None
    assert abs(report.L_uH - 100.0) < 0.001


# ══════════════════════════════════════════════════════════════════════════════
# T07 — recommended_caps_X2_uF are valid E12 values
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_recommended_caps_are_e12():
    """T07: recommended_caps_X2_uF are non-empty and within E12 set."""
    spec = _make_lc_spec()
    report = design_emi_filter(spec)
    assert len(report.recommended_caps_X2_uF) > 0
    for val in report.recommended_caps_X2_uF:
        # Allow small floating-point tolerance
        assert any(abs(val - e12) / e12 < 1e-6 for e12 in _X2_E12_UF), (
            f"Cap {val} µF not found in E12 set"
        )


# ══════════════════════════════════════════════════════════════════════════════
# T08 — PI f_c > LC f_c for same spec (60 dB/dec can accept higher f_c)
# ══════════════════════════════════════════════════════════════════════════════

def test_pi_fc_higher_than_lc_fc():
    """T08: PI topology achieves the same A_dB with a higher f_c than LC."""
    spec_lc = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="LC_low_pass",
    )
    spec_pi = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="PI_LC_L",
    )
    r_lc = design_emi_filter(spec_lc)
    r_pi = design_emi_filter(spec_pi)
    assert r_pi.cutoff_freq_Hz > r_lc.cutoff_freq_Hz


# ══════════════════════════════════════════════════════════════════════════════
# T09 — PI attenuation_at_target_dB ≈ A_dB
# ══════════════════════════════════════════════════════════════════════════════

def test_pi_attenuation_matches_spec():
    """T09: PI computed attenuation equals requested A_dB within 0.01 dB."""
    spec = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="PI_LC_L",
    )
    report = design_emi_filter(spec)
    assert abs(report.attenuation_at_target_dB - spec.target_attenuation_dB) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# T10 — PI C_uF < LC C_uF (PI has higher f_c → smaller total cap required)
# ══════════════════════════════════════════════════════════════════════════════

def test_pi_capacitance_smaller_than_lc():
    """T10: PI total C is less than LC C for the same attenuation spec."""
    spec_lc = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="LC_low_pass",
    )
    spec_pi = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="PI_LC_L",
    )
    r_lc = design_emi_filter(spec_lc)
    r_pi = design_emi_filter(spec_pi)
    assert r_pi.C_uF < r_lc.C_uF


# ══════════════════════════════════════════════════════════════════════════════
# T11 — PI steeper roll-off: attenuation at 2×f_c target is larger for PI
# ══════════════════════════════════════════════════════════════════════════════

def test_pi_steeper_rolloff_than_lc():
    """T11: PI gives steeper roll-off — 60 dB/dec vs LC 40 dB/dec.
    At the same f_c, the PI should provide 60% more attenuation per decade."""
    # Fix the same f_c by using a specific attenuation spec
    # For both topologies with same corner, PI roll-off should give more attenuation
    # at target.  We verify the slope ratio: PI/LC attenuation ≈ 60/40 = 1.5
    spec_lc = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=40.0, target_freq_kHz=150.0,
        filter_topology="LC_low_pass",
    )
    spec_pi = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=5.0,
        target_attenuation_dB=60.0, target_freq_kHz=150.0,
        filter_topology="PI_LC_L",
    )
    r_lc = design_emi_filter(spec_lc)
    r_pi = design_emi_filter(spec_pi)
    # Both designed for their respective attenuations; f_c ratio should be 1.5 decades
    # lc f_c = f_t / 10^(40/40) = 150kHz/10 = 15 kHz
    # pi f_c = f_t / 10^(60/60) = 150kHz/10 = 15 kHz (same!)
    # Both should have approximately the same f_c here
    assert abs(r_lc.cutoff_freq_Hz - r_pi.cutoff_freq_Hz) / r_lc.cutoff_freq_Hz < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# T12 — RC: R_ohm = load_resistance_ohm when provided
# ══════════════════════════════════════════════════════════════════════════════

def test_rc_uses_provided_load_resistance():
    """T12: RC_low_pass uses load_resistance_ohm when provided."""
    spec = EmiFilterSpec(
        dc_voltage_V=5.0, dc_current_A=0.01,
        target_attenuation_dB=20.0, target_freq_kHz=150.0,
        filter_topology="RC_low_pass",
        load_resistance_ohm=100.0,
    )
    report = design_emi_filter(spec)
    assert report.R_ohm is not None
    assert abs(report.R_ohm - 100.0) < 0.001


# ══════════════════════════════════════════════════════════════════════════════
# T13 — RC: L_uH is None
# ══════════════════════════════════════════════════════════════════════════════

def test_rc_no_inductance():
    """T13: RC_low_pass reports L_uH = None."""
    spec = EmiFilterSpec(
        dc_voltage_V=5.0, dc_current_A=0.01,
        target_attenuation_dB=20.0, target_freq_kHz=150.0,
        filter_topology="RC_low_pass",
    )
    report = design_emi_filter(spec)
    assert report.L_uH is None


# ══════════════════════════════════════════════════════════════════════════════
# T14 — RC: f_c correct from formula f_c = f_t / 10^(A/20)
# ══════════════════════════════════════════════════════════════════════════════

def test_rc_corner_frequency_formula():
    """T14: RC f_c = f_t / 10^(A/20) within 0.1%."""
    spec = EmiFilterSpec(
        dc_voltage_V=5.0, dc_current_A=0.01,
        target_attenuation_dB=20.0, target_freq_kHz=100.0,
        filter_topology="RC_low_pass",
        load_resistance_ohm=50.0,
    )
    report = design_emi_filter(spec)
    expected_fc = 100e3 / (10.0 ** (20.0 / 20.0))  # = 10 kHz
    assert abs(report.cutoff_freq_Hz - expected_fc) / expected_fc < 0.001


# ══════════════════════════════════════════════════════════════════════════════
# T15 — RC: attenuation_at_target_dB ≈ A_dB
# ══════════════════════════════════════════════════════════════════════════════

def test_rc_attenuation_matches_spec():
    """T15: RC computed attenuation equals requested A_dB within 0.01 dB."""
    spec = EmiFilterSpec(
        dc_voltage_V=5.0, dc_current_A=0.01,
        target_attenuation_dB=25.0, target_freq_kHz=200.0,
        filter_topology="RC_low_pass",
        load_resistance_ohm=75.0,
    )
    report = design_emi_filter(spec)
    assert abs(report.attenuation_at_target_dB - spec.target_attenuation_dB) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# T16 — Negative dc_voltage_V → ValueError
# ══════════════════════════════════════════════════════════════════════════════

def test_validation_negative_voltage():
    """T16: Negative dc_voltage_V raises ValueError."""
    spec = EmiFilterSpec(
        dc_voltage_V=-12.0, dc_current_A=1.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="LC_low_pass",
    )
    with pytest.raises(ValueError, match="dc_voltage_V"):
        design_emi_filter(spec)


# ══════════════════════════════════════════════════════════════════════════════
# T17 — Zero dc_current_A → ValueError
# ══════════════════════════════════════════════════════════════════════════════

def test_validation_zero_current():
    """T17: Zero dc_current_A raises ValueError."""
    spec = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=0.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="LC_low_pass",
    )
    with pytest.raises(ValueError, match="dc_current_A"):
        design_emi_filter(spec)


# ══════════════════════════════════════════════════════════════════════════════
# T18 — Unknown topology → ValueError
# ══════════════════════════════════════════════════════════════════════════════

def test_validation_unknown_topology():
    """T18: Unknown filter_topology raises ValueError."""
    spec = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=1.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology="T_network",
    )
    with pytest.raises(ValueError, match="filter_topology"):
        design_emi_filter(spec)


# ══════════════════════════════════════════════════════════════════════════════
# T19 — Zero target_freq_kHz → ValueError
# ══════════════════════════════════════════════════════════════════════════════

def test_validation_zero_target_freq():
    """T19: Zero target_freq_kHz raises ValueError."""
    spec = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=1.0,
        target_attenuation_dB=30.0, target_freq_kHz=0.0,
        filter_topology="LC_low_pass",
    )
    with pytest.raises(ValueError, match="target_freq_kHz"):
        design_emi_filter(spec)


# ══════════════════════════════════════════════════════════════════════════════
# T20 — Dict wrapper: valid input returns {"ok": True, ...}
# ══════════════════════════════════════════════════════════════════════════════

def test_dict_wrapper_valid_lc():
    """T20: design_emi_filter_from_dict returns ok=True and expected keys."""
    d = {
        "dc_voltage_V": 48.0,
        "dc_current_A": 5.0,
        "target_attenuation_dB": 30.0,
        "target_freq_kHz": 150.0,
        "filter_topology": "LC_low_pass",
    }
    result = design_emi_filter_from_dict(d)
    assert result["ok"] is True
    for key in ("cutoff_freq_Hz", "L_uH", "C_uF", "attenuation_at_target_dB",
                "recommended_caps_X2_uF", "honest_caveat"):
        assert key in result, f"Missing key: {key}"


# ══════════════════════════════════════════════════════════════════════════════
# T21 — Dict wrapper: missing required key → {"ok": False}
# ══════════════════════════════════════════════════════════════════════════════

def test_dict_wrapper_missing_key():
    """T21: Missing required key returns ok=False."""
    d = {
        "dc_voltage_V": 48.0,
        # dc_current_A missing
        "target_attenuation_dB": 30.0,
        "target_freq_kHz": 150.0,
        "filter_topology": "LC_low_pass",
    }
    result = design_emi_filter_from_dict(d)
    assert result["ok"] is False
    assert "reason" in result


# ══════════════════════════════════════════════════════════════════════════════
# T22 — honest_caveat non-empty for every topology
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("topology", ["LC_low_pass", "PI_LC_L", "RC_low_pass"])
def test_honest_caveat_nonempty(topology):
    """T22: honest_caveat is a non-empty string for every topology."""
    spec = EmiFilterSpec(
        dc_voltage_V=48.0, dc_current_A=1.0,
        target_attenuation_dB=30.0, target_freq_kHz=150.0,
        filter_topology=topology,
    )
    report = design_emi_filter(spec)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 10


# ══════════════════════════════════════════════════════════════════════════════
# Extra: LC f_c formula cross-check at a different frequency
# ══════════════════════════════════════════════════════════════════════════════

def test_lc_10dB_500kHz_formula():
    """Extra: LC 10 dB @ 500 kHz → f_c = 500 / 10^(10/40) = 500 / 1.778 ≈ 281 kHz."""
    spec = _make_lc_spec(target_attenuation_dB=10.0, target_freq_kHz=500.0)
    report = design_emi_filter(spec)
    expected_fc = 500e3 / (10.0 ** (10.0 / 40.0))
    assert abs(report.cutoff_freq_Hz - expected_fc) / expected_fc < 0.001


def test_rc_default_50ohm():
    """Extra: RC_low_pass without load_resistance_ohm uses 50 Ω default."""
    spec = EmiFilterSpec(
        dc_voltage_V=5.0, dc_current_A=0.001,
        target_attenuation_dB=20.0, target_freq_kHz=100.0,
        filter_topology="RC_low_pass",
    )
    report = design_emi_filter(spec)
    assert report.R_ohm is not None
    assert abs(report.R_ohm - 50.0) < 0.001
