"""
Hermetic tests for kerf_electronics.voltage_drop — NEC 2023 Article 210.19(A).

Hand-calc reference (IEEE 141 §3.3):
  12 AWG copper @ 75°C → NEC Ch9 Table 8: 1.93 Ω/1000 ft
  1.93 / (1000 × 0.3048) = 1.93 / 304.8 = 0.006331... Ω/m
  Single-phase, L=30 m, I=20 A, PF=1.0, V=240 V:
    R_total = 2 × 0.006331 × 30 = 0.37989 Ω
    V_drop  = 20 × 0.37989 = 7.5978 V
    V_drop% = 7.5978/240 × 100 = 3.165...%

Covers ≥ 12 tests across:
  - Hand-calc baseline (12AWG copper, 240V single-phase, 20A, 30m)
  - Aluminum vs copper ratio (≈ 1.64×)
  - DC short run → compliant
  - Long thin run → non-compliant (>3%)
  - Three-phase voltage drop formula (√3 factor)
  - Power factor effect
  - Zero current → zero drop
  - Boundary compliance (exactly at limit)
  - max_drop_pct override
  - Invalid AWG → ValueError
  - Invalid material → ValueError
  - Negative length → ValueError
  - Invalid phase → ValueError
  - PF out of range → ValueError
  - Report has all required fields
  - LLM tool handler (happy path + bad args)
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_electronics.voltage_drop import (
    ConductorSpec,
    CircuitSpec,
    VoltageDropReport,
    check_voltage_drop,
    _TABLE_8_75C,
    _OHMS_PER_M_FACTOR,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _r_per_m(awg: str, material: str) -> float:
    """Return NEC Table 8 resistance [Ω/m] for hand-calc assertions."""
    row = _TABLE_8_75C[awg]
    r1000ft = row[0] if material == "copper" else row[1]
    return r1000ft * _OHMS_PER_M_FACTOR


# ---------------------------------------------------------------------------
# Test 1 — 12AWG copper, 240V single-phase, 20A, 30m — hand-calc baseline
# ---------------------------------------------------------------------------

def test_12awg_copper_240v_single_phase_20a_30m_hand_calc():
    """IEEE 141 hand-calc: 12 AWG Cu, 240V, 20A, PF=1.0, 30m → ~3.165%."""
    conductor = ConductorSpec(awg_size="12", material="copper", length_one_way_m=30.0)
    circuit = CircuitSpec(voltage_V=240.0, current_A=20.0, phase="single_phase")
    report = check_voltage_drop(conductor, circuit)

    r_m = _r_per_m("12", "copper")
    expected_vd = 2.0 * 20.0 * r_m * 30.0
    expected_pct = expected_vd / 240.0 * 100.0

    assert abs(report.voltage_drop_V - expected_vd) < 1e-4, (
        f"V_drop mismatch: got {report.voltage_drop_V:.5f}, expected {expected_vd:.5f}"
    )
    assert abs(report.voltage_drop_pct - expected_pct) < 1e-3, (
        f"Vd% mismatch: got {report.voltage_drop_pct:.4f}%, expected {expected_pct:.4f}%"
    )
    # 3.165% > 3.0% → non-compliant with default 3% limit
    assert report.compliant is False


# ---------------------------------------------------------------------------
# Test 2 — Aluminum vs copper: aluminum has higher drop
# ---------------------------------------------------------------------------

def test_aluminum_higher_drop_than_copper():
    """Aluminum resistance ≈ 1.64× copper → higher V_drop."""
    conductor_cu = ConductorSpec("12", "copper", 20.0)
    conductor_al = ConductorSpec("12", "aluminum", 20.0)
    circuit = CircuitSpec(voltage_V=120.0, current_A=15.0, phase="single_phase")

    r_cu = check_voltage_drop(conductor_cu, circuit)
    r_al = check_voltage_drop(conductor_al, circuit)

    assert r_al.voltage_drop_V > r_cu.voltage_drop_V, (
        "Aluminum should have higher voltage drop than copper"
    )
    ratio = r_al.voltage_drop_V / r_cu.voltage_drop_V
    # NEC Table 8 ratio for 12 AWG: 3.165/1.93 ≈ 1.64
    assert 1.55 < ratio < 1.75, f"Al/Cu ratio {ratio:.3f} out of expected band 1.55–1.75"


# ---------------------------------------------------------------------------
# Test 3 — DC short run → small drop → compliant
# ---------------------------------------------------------------------------

def test_dc_short_run_compliant():
    """DC 12V, 10AWG, 2m, 10A — short run should be well under 3%."""
    conductor = ConductorSpec("10", "copper", length_one_way_m=2.0)
    circuit = CircuitSpec(voltage_V=12.0, current_A=10.0, phase="dc")
    report = check_voltage_drop(conductor, circuit)

    assert report.voltage_drop_pct < 3.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 4 — Long thin run → Vd% > 3% → non-compliant
# ---------------------------------------------------------------------------

def test_long_thin_run_non_compliant():
    """14AWG, 100m, 120V, 15A single-phase — must exceed 3%."""
    conductor = ConductorSpec("14", "copper", length_one_way_m=100.0)
    circuit = CircuitSpec(voltage_V=120.0, current_A=15.0, phase="single_phase")
    report = check_voltage_drop(conductor, circuit)

    assert report.voltage_drop_pct > 3.0, (
        f"Expected Vd% > 3% for long 14 AWG run, got {report.voltage_drop_pct:.2f}%"
    )
    assert report.compliant is False


# ---------------------------------------------------------------------------
# Test 5 — Three-phase uses √3 factor
# ---------------------------------------------------------------------------

def test_three_phase_sqrt3_factor():
    """Three-phase V_drop = √3 × I × R × L × PF vs single-phase 2 × I × R × L × PF."""
    conductor = ConductorSpec("6", "copper", length_one_way_m=50.0)
    r_m = _r_per_m("6", "copper")
    I = 30.0
    V = 208.0
    PF = 0.9

    circuit_sp = CircuitSpec(voltage_V=V, current_A=I, phase="single_phase", power_factor=PF)
    circuit_3p = CircuitSpec(voltage_V=V, current_A=I, phase="three_phase", power_factor=PF)

    rpt_sp = check_voltage_drop(conductor, circuit_sp)
    rpt_3p = check_voltage_drop(conductor, circuit_3p)

    expected_sp = 2.0 * I * r_m * 50.0 * PF
    expected_3p = math.sqrt(3) * I * r_m * 50.0 * PF

    assert abs(rpt_sp.voltage_drop_V - expected_sp) < 1e-5
    assert abs(rpt_3p.voltage_drop_V - expected_3p) < 1e-5
    # Three-phase drop < single-phase drop (√3 < 2)
    assert rpt_3p.voltage_drop_V < rpt_sp.voltage_drop_V


# ---------------------------------------------------------------------------
# Test 6 — Power factor reduces apparent voltage drop
# ---------------------------------------------------------------------------

def test_power_factor_reduces_drop():
    """Lower PF → lower resistive voltage drop (V_drop uses resistive component only)."""
    conductor = ConductorSpec("8", "copper", length_one_way_m=40.0)
    circuit_unity = CircuitSpec(240.0, 25.0, "single_phase", power_factor=1.0)
    circuit_pf85 = CircuitSpec(240.0, 25.0, "single_phase", power_factor=0.85)

    rpt_unity = check_voltage_drop(conductor, circuit_unity)
    rpt_pf85 = check_voltage_drop(conductor, circuit_pf85)

    assert rpt_pf85.voltage_drop_V < rpt_unity.voltage_drop_V


# ---------------------------------------------------------------------------
# Test 7 — Zero current → zero voltage drop
# ---------------------------------------------------------------------------

def test_zero_current_zero_drop():
    """Zero load current must produce zero voltage drop."""
    conductor = ConductorSpec("4", "copper", length_one_way_m=20.0)
    circuit = CircuitSpec(voltage_V=120.0, current_A=0.0, phase="single_phase")
    report = check_voltage_drop(conductor, circuit)

    assert report.voltage_drop_V == 0.0
    assert report.voltage_drop_pct == 0.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 8 — Boundary: exactly at the limit → compliant=True
# ---------------------------------------------------------------------------

def test_exactly_at_limit_is_compliant():
    """If Vd% == max_drop_pct exactly, compliant should be True (≤ check)."""
    # Construct a circuit where Vd% exactly equals 3.0%
    conductor = ConductorSpec("10", "copper", length_one_way_m=20.0)
    r_m = _r_per_m("10", "copper")
    # V_drop = 2 × I × r_m × L = 3% × V_sys
    # Choose I such that V_drop / V = 0.03: I = 0.03 × V / (2 × r_m × L)
    V = 120.0
    I_exact = 0.03 * V / (2.0 * r_m * 20.0)
    circuit = CircuitSpec(voltage_V=V, current_A=I_exact, phase="single_phase")
    report = check_voltage_drop(conductor, circuit, max_drop_pct=3.0)

    assert abs(report.voltage_drop_pct - 3.0) < 0.001, (
        f"Expected Vd% ≈ 3.0%, got {report.voltage_drop_pct:.4f}%"
    )
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 9 — max_drop_pct override (2% branch circuit check)
# ---------------------------------------------------------------------------

def test_max_drop_pct_override_branch_circuit():
    """Using max_drop_pct=2.0 gives tighter compliance threshold."""
    conductor = ConductorSpec("12", "copper", length_one_way_m=15.0)
    circuit = CircuitSpec(voltage_V=120.0, current_A=20.0, phase="single_phase")

    rpt_3 = check_voltage_drop(conductor, circuit, max_drop_pct=3.0)
    rpt_2 = check_voltage_drop(conductor, circuit, max_drop_pct=2.0)

    # Same Vd but different compliance threshold
    assert rpt_3.voltage_drop_V == rpt_2.voltage_drop_V
    assert rpt_3.recommended_max_pct == 3.0
    assert rpt_2.recommended_max_pct == 2.0
    # If drop > 2% but ≤ 3%, they differ
    if 2.0 < rpt_3.voltage_drop_pct <= 3.0:
        assert rpt_3.compliant is True
        assert rpt_2.compliant is False


# ---------------------------------------------------------------------------
# Test 10 — Report has all required fields
# ---------------------------------------------------------------------------

def test_report_has_all_required_fields():
    """VoltageDropReport must expose all six documented fields."""
    conductor = ConductorSpec("6", "aluminum", 25.0)
    circuit = CircuitSpec(480.0, 40.0, "three_phase", 0.9)
    report = check_voltage_drop(conductor, circuit)

    assert hasattr(report, "voltage_drop_V")
    assert hasattr(report, "voltage_drop_pct")
    assert hasattr(report, "recommended_max_pct")
    assert hasattr(report, "compliant")
    assert hasattr(report, "resistance_ohm")
    assert hasattr(report, "honest_caveat")
    assert isinstance(report.voltage_drop_V, float)
    assert isinstance(report.voltage_drop_pct, float)
    assert isinstance(report.compliant, bool)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 11 — Invalid AWG → ValueError
# ---------------------------------------------------------------------------

def test_invalid_awg_raises():
    """Unsupported AWG size must raise ValueError."""
    conductor = ConductorSpec("3", "copper", 10.0)  # AWG 3 not in Table 8 subset
    circuit = CircuitSpec(120.0, 10.0, "single_phase")
    with pytest.raises(ValueError, match="Unsupported AWG"):
        check_voltage_drop(conductor, circuit)


# ---------------------------------------------------------------------------
# Test 12 — Invalid material → ValueError
# ---------------------------------------------------------------------------

def test_invalid_material_raises():
    """Unknown material must raise ValueError."""
    conductor = ConductorSpec("12", "silver", 10.0)
    circuit = CircuitSpec(120.0, 10.0, "single_phase")
    with pytest.raises(ValueError, match="material"):
        check_voltage_drop(conductor, circuit)


# ---------------------------------------------------------------------------
# Test 13 — Negative length → ValueError
# ---------------------------------------------------------------------------

def test_negative_length_raises():
    """Negative one-way length must raise ValueError."""
    conductor = ConductorSpec("12", "copper", -5.0)
    circuit = CircuitSpec(120.0, 10.0, "single_phase")
    with pytest.raises(ValueError, match="length_one_way_m"):
        check_voltage_drop(conductor, circuit)


# ---------------------------------------------------------------------------
# Test 14 — Invalid phase → ValueError
# ---------------------------------------------------------------------------

def test_invalid_phase_raises():
    """Invalid phase string must raise ValueError."""
    conductor = ConductorSpec("10", "copper", 10.0)
    circuit = CircuitSpec(120.0, 10.0, "quad_phase")
    with pytest.raises(ValueError, match="phase"):
        check_voltage_drop(conductor, circuit)


# ---------------------------------------------------------------------------
# Test 15 — PF out of range → ValueError
# ---------------------------------------------------------------------------

def test_pf_out_of_range_raises():
    """Power factor > 1.0 or ≤ 0 must raise ValueError."""
    conductor = ConductorSpec("10", "copper", 10.0)
    circuit_hi = CircuitSpec(120.0, 10.0, "single_phase", power_factor=1.1)
    circuit_lo = CircuitSpec(120.0, 10.0, "single_phase", power_factor=0.0)
    with pytest.raises(ValueError, match="power_factor"):
        check_voltage_drop(conductor, circuit_hi)
    with pytest.raises(ValueError, match="power_factor"):
        check_voltage_drop(conductor, circuit_lo)


# ---------------------------------------------------------------------------
# Test 16 — 250kcmil copper three-phase large run
# ---------------------------------------------------------------------------

def test_250kcmil_copper_three_phase_large_run():
    """250 kcmil copper, 200m, 480V 3-phase, 150A, PF=0.9."""
    conductor = ConductorSpec("250kcmil", "copper", 200.0)
    circuit = CircuitSpec(480.0, 150.0, "three_phase", 0.9)
    report = check_voltage_drop(conductor, circuit)

    r_m = _r_per_m("250kcmil", "copper")
    expected_vd = math.sqrt(3) * 150.0 * r_m * 200.0 * 0.9
    assert abs(report.voltage_drop_V - expected_vd) < 1e-4


# ---------------------------------------------------------------------------
# Test 17 — 4/0 aluminum feeder, long run, 240V single-phase
# ---------------------------------------------------------------------------

def test_4_0_aluminum_240v_single_phase_long():
    """4/0 aluminum, 120m, 240V single-phase, 100A — spot check compliance."""
    conductor = ConductorSpec("4/0", "aluminum", 120.0)
    circuit = CircuitSpec(240.0, 100.0, "single_phase")
    report = check_voltage_drop(conductor, circuit)

    r_m = _r_per_m("4/0", "aluminum")
    expected = 2.0 * 100.0 * r_m * 120.0
    assert abs(report.voltage_drop_V - expected) < 1e-4
    # Check caveat mentions aluminum
    assert "aluminum" in report.honest_caveat.lower() or "Aluminum" in report.honest_caveat


# ---------------------------------------------------------------------------
# Test 18 — LLM tool handler happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_handler_happy_path():
    """electronics_check_voltage_drop LLM tool returns ok=True for valid inputs."""
    from kerf_electronics.tools.voltage_drop import electronics_check_voltage_drop

    args = json.dumps({
        "awg_size": "12",
        "material": "copper",
        "length_one_way_m": 30.0,
        "voltage_V": 240.0,
        "current_A": 20.0,
        "phase": "single_phase",
        "power_factor": 1.0,
        "max_drop_pct": 3.0,
    }).encode()

    result = await electronics_check_voltage_drop(None, args)
    payload = json.loads(result)
    assert payload.get("ok") is True
    assert "voltage_drop_V" in payload
    assert "voltage_drop_pct" in payload
    assert "compliant" in payload
    assert "resistance_ohm" in payload
    assert "honest_caveat" in payload


# ---------------------------------------------------------------------------
# Test 19 — LLM tool handler bad args
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_handler_bad_args():
    """electronics_check_voltage_drop returns error payload for invalid AWG."""
    from kerf_electronics.tools.voltage_drop import electronics_check_voltage_drop

    args = json.dumps({
        "awg_size": "3",       # not supported
        "material": "copper",
        "length_one_way_m": 10.0,
        "voltage_V": 120.0,
        "current_A": 10.0,
        "phase": "single_phase",
    }).encode()

    result = await electronics_check_voltage_drop(None, args)
    payload = json.loads(result)
    assert "error" in payload or payload.get("ok") is False or "code" in payload


# ---------------------------------------------------------------------------
# Test 20 — LLM tool handler malformed JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_tool_handler_malformed_json():
    """electronics_check_voltage_drop returns error payload for malformed JSON."""
    from kerf_electronics.tools.voltage_drop import electronics_check_voltage_drop

    result = await electronics_check_voltage_drop(None, b"not valid json {{")
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 21 — DC formula uses 2× factor (not √3)
# ---------------------------------------------------------------------------

def test_dc_formula_uses_2x_factor():
    """DC V_drop = 2 × I × R/m × L (no PF term, no √3)."""
    conductor = ConductorSpec("8", "copper", 10.0)
    circuit = CircuitSpec(24.0, 20.0, "dc")
    report = check_voltage_drop(conductor, circuit)

    r_m = _r_per_m("8", "copper")
    expected = 2.0 * 20.0 * r_m * 10.0
    assert abs(report.voltage_drop_V - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 22 — resistance_ohm equals round-trip resistance
# ---------------------------------------------------------------------------

def test_resistance_ohm_is_round_trip():
    """resistance_ohm in report = 2 × r_per_m × L for single-phase."""
    conductor = ConductorSpec("10", "copper", 30.0)
    circuit = CircuitSpec(120.0, 15.0, "single_phase")
    report = check_voltage_drop(conductor, circuit)

    r_m = _r_per_m("10", "copper")
    expected_r_total = 2.0 * r_m * 30.0
    assert abs(report.resistance_ohm - expected_r_total) < 1e-7


# ---------------------------------------------------------------------------
# Test 23 — honest_caveat mentions reactance for AC
# ---------------------------------------------------------------------------

def test_honest_caveat_mentions_reactance_for_ac():
    """Caveat for AC circuits should warn about reactance."""
    conductor = ConductorSpec("1/0", "copper", 50.0)
    circuit = CircuitSpec(480.0, 100.0, "three_phase")
    report = check_voltage_drop(conductor, circuit)
    assert "reactance" in report.honest_caveat.lower() or "X_L" in report.honest_caveat


# ---------------------------------------------------------------------------
# Test 24 — DC caveat does NOT mention reactance
# ---------------------------------------------------------------------------

def test_dc_caveat_no_reactance_warning():
    """For DC circuits, the reactance caveat should not appear."""
    conductor = ConductorSpec("6", "copper", 20.0)
    circuit = CircuitSpec(48.0, 30.0, "dc")
    report = check_voltage_drop(conductor, circuit)
    # DC should not mention reactance
    assert "X_L" not in report.honest_caveat


# ---------------------------------------------------------------------------
# Test 25 — All AWG sizes in table produce positive resistance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("awg", list(_TABLE_8_75C.keys()))
def test_all_awg_copper_produce_positive_resistance(awg):
    """Every supported AWG size for copper must return positive Vd."""
    conductor = ConductorSpec(awg, "copper", 10.0)
    circuit = CircuitSpec(120.0, 10.0, "single_phase")
    report = check_voltage_drop(conductor, circuit)
    assert report.voltage_drop_V > 0.0
    assert report.resistance_ohm > 0.0
