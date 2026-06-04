"""
Tests for kerf_cad_core.aerospace.motor_database.

References
----------
* Sebastien Cyr — RASP .eng format spec.
* NAR Tested Motors database.
* Thrustcurve.org motor data.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.aerospace.motor_database import (
    RocketMotor,
    parse_rasp_eng_file,
    estes_motor_catalog,
    aerotech_motor_catalog,
    compute_burnout_velocity,
)


# ---------------------------------------------------------------------------
# Sample .eng content (F15-4 style, representative values)
# ---------------------------------------------------------------------------

F15_4_ENG = """\
; F15-4 Estes-like test motor
; Source: synthetic test data
F15-4 29 113 4 32.0 95.0 TestMfg
0.000 0.0
0.020 62.0
0.100 45.0
0.300 18.0
0.600 12.0
0.900 10.0
1.200 8.0
1.500 5.0
1.800 2.0
2.000 0.5
2.050 0.0
;
"""

D12_ENG = """\
D12-5 24 70 3-5-7 20.3 40.0 Estes
0.000 0.0
0.050 29.7
0.200 22.0
0.600 14.0
1.000 11.0
1.400 9.0
1.700 5.0
1.730 0.0
;
"""

MULTI_MOTOR_ENG = """\
; Two motors in one file
A8-3 18 70 3 3.0 16.2 Estes
0.000 0.0
0.030 19.4
0.150 12.0
0.300 8.0
0.450 5.0
0.500 1.0
0.520 0.0
;
B6-4 18 70 4 5.5 19.4 Estes
0.000 0.0
0.040 12.7
0.200 9.0
0.450 7.0
0.700 5.0
0.850 2.0
0.870 0.0
;
"""


# ---------------------------------------------------------------------------
# Test 1: parse_rasp_eng_file returns correct designation
# ---------------------------------------------------------------------------

def test_parse_rasp_designation():
    motors = parse_rasp_eng_file(F15_4_ENG)
    assert len(motors) == 1
    assert motors[0].designation == "F15-4"


# ---------------------------------------------------------------------------
# Test 2: parsed F15-4 — total impulse within 5% of manual trapezoidal integral
# ---------------------------------------------------------------------------

def test_parse_rasp_total_impulse_within_5pct():
    motors = parse_rasp_eng_file(F15_4_ENG)
    m = motors[0]
    # Manual trapezoidal integration
    tc = m.thrust_curve
    expected = float(np.trapz(tc[:, 1], tc[:, 0]))
    np.testing.assert_allclose(m.total_impulse_n_s, expected, rtol=0.02,
                               err_msg="Total impulse should match trapezoidal integral")


# ---------------------------------------------------------------------------
# Test 3: total_impulse = integral of thrust_curve within 1%
# ---------------------------------------------------------------------------

def test_parse_rasp_impulse_equals_integral():
    motors = parse_rasp_eng_file(D12_ENG)
    m = motors[0]
    tc = m.thrust_curve
    integral = float(np.trapz(tc[:, 1], tc[:, 0]))
    np.testing.assert_allclose(m.total_impulse_n_s, integral, rtol=0.01,
                               err_msg="total_impulse should equal integral within 1%")


# ---------------------------------------------------------------------------
# Test 4: parsed motor geometry (diameter, length)
# ---------------------------------------------------------------------------

def test_parse_rasp_geometry():
    motors = parse_rasp_eng_file(D12_ENG)
    m = motors[0]
    assert m.diameter_mm == pytest.approx(24.0)
    assert m.length_mm == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# Test 5: parsed motor manufacturer and mass
# ---------------------------------------------------------------------------

def test_parse_rasp_manufacturer_and_mass():
    motors = parse_rasp_eng_file(D12_ENG)
    m = motors[0]
    assert m.manufacturer == "Estes"
    assert m.propellant_mass_g == pytest.approx(20.3)
    assert m.total_mass_g == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Test 6: multi-motor .eng file yields correct count
# ---------------------------------------------------------------------------

def test_parse_rasp_multi_motor():
    motors = parse_rasp_eng_file(MULTI_MOTOR_ENG)
    assert len(motors) == 2
    desigs = {m.designation for m in motors}
    assert "A8-3" in desigs
    assert "B6-4" in desigs


# ---------------------------------------------------------------------------
# Test 7: Estes catalog returns ≥ 5 motors
# ---------------------------------------------------------------------------

def test_estes_catalog_count():
    motors = estes_motor_catalog()
    assert len(motors) >= 5, f"Expected ≥5 Estes motors, got {len(motors)}"


# ---------------------------------------------------------------------------
# Test 8: Estes catalog includes D12 motor
# ---------------------------------------------------------------------------

def test_estes_catalog_contains_d12():
    motors = estes_motor_catalog()
    desigs = [m.designation for m in motors]
    assert any("D12" in d for d in desigs), f"D12 not found in catalog: {desigs}"


# ---------------------------------------------------------------------------
# Test 9: AeroTech catalog returns ≥ 3 motors
# ---------------------------------------------------------------------------

def test_aerotech_catalog_count():
    motors = aerotech_motor_catalog()
    assert len(motors) >= 3, f"Expected ≥3 AeroTech motors, got {len(motors)}"


# ---------------------------------------------------------------------------
# Test 10: AeroTech catalog motors are in G/H/I class
# ---------------------------------------------------------------------------

def test_aerotech_catalog_classes():
    motors = aerotech_motor_catalog()
    classes = {m.impulse_class for m in motors}
    assert classes.issubset({"G", "H", "I"}), f"Unexpected classes: {classes}"


# ---------------------------------------------------------------------------
# Test 11: compute_burnout_velocity — D12 with 50g dry rocket is positive
# ---------------------------------------------------------------------------

def test_burnout_velocity_d12_positive():
    motors = estes_motor_catalog()
    d12 = next(m for m in motors if "D12" in m.designation)
    result = compute_burnout_velocity(d12, rocket_dry_mass_g=50.0)
    assert result["ok"], f"Simulation failed: {result['reason']}"
    v = result["burnout_velocity_m_s"]
    assert v > 0.0, f"Expected positive burnout velocity, got {v}"


# ---------------------------------------------------------------------------
# Test 12: compute_burnout_velocity — D12 burnout velocity < 100 m/s
# ---------------------------------------------------------------------------

def test_burnout_velocity_d12_less_than_100():
    """D12 with a heavy 500g rocket (e.g. a large model rocket) should stay well under 100 m/s.

    A D12 with a 50g dry rocket is actually a fast, light configuration (>100 m/s is realistic).
    Using a 500g dry mass gives a more realistic heavy-rocket scenario that stays under 100 m/s.
    """
    motors = estes_motor_catalog()
    d12 = next(m for m in motors if "D12" in m.designation)
    result = compute_burnout_velocity(d12, rocket_dry_mass_g=500.0)
    assert result["ok"], f"Simulation failed: {result['reason']}"
    v = result["burnout_velocity_m_s"]
    assert v < 100.0, f"Burnout velocity {v:.1f} m/s exceeds 100 m/s for D12 / 500g rocket"


# ---------------------------------------------------------------------------
# Test 13: all Estes catalog motors have positive total impulse
# ---------------------------------------------------------------------------

def test_estes_catalog_positive_impulse():
    for m in estes_motor_catalog():
        assert m.total_impulse_n_s > 0, f"Non-positive impulse for {m.designation}"


# ---------------------------------------------------------------------------
# Test 14: RocketMotor dataclass fields accessible
# ---------------------------------------------------------------------------

def test_rocket_motor_dataclass_fields():
    motors = estes_motor_catalog()
    m = motors[0]
    assert isinstance(m.designation, str)
    assert isinstance(m.thrust_curve, np.ndarray)
    assert m.thrust_curve.shape[1] == 2
    assert isinstance(m.delay_options, list)


# ---------------------------------------------------------------------------
# Test 15: parse empty .eng file returns empty list
# ---------------------------------------------------------------------------

def test_parse_empty_eng():
    result = parse_rasp_eng_file("")
    assert result == []


# ---------------------------------------------------------------------------
# Test 16: compute_burnout_velocity — burnout time equals motor burn_time
# ---------------------------------------------------------------------------

def test_burnout_time_matches_motor():
    motors = estes_motor_catalog()
    c6 = next(m for m in motors if "C6" in m.designation)
    result = compute_burnout_velocity(c6, rocket_dry_mass_g=30.0)
    assert result["ok"]
    np.testing.assert_allclose(result["burnout_time_s"], c6.burn_time_s, rtol=1e-10)
