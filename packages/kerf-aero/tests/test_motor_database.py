"""Tests for the motor database (Thrustcurve / RASP .eng integration).

Numerical oracles:
  1. Built-in catalogue loads and contains expected motors.
  2. RASP .eng parser: reference .eng strings → correct performance data.
  3. Total impulse by trapezoidal integration matches analytic oracle.
  4. Isp computation oracle: Isp = total_impulse / (prop_mass × g0).
  5. Impulse class classification (NAR/TRA letter boundaries).
  6. Motor selector: list_motors filters correctly.
  7. get_motor: name lookup, case-insensitive, KeyError on unknown.
  8. thrust_at: linear interpolation between data points.
  9. Multi-motor .eng file parsing.
  10. LLM tool (aero_motor_database) round-trips.

References
----------
NAR Standards & Testing Committee impulse classification.
Thrustcurve.org RASP .eng file format.
Sutton & Biblarz "Rocket Propulsion Elements" 9th ed. §11.
"""

from __future__ import annotations

import math
import io

import pytest

from kerf_aero.propulsion.motor_database import (
    ThrustcurveMotor,
    ThrustCurvePoint,
    parse_eng,
    list_motors,
    get_motor,
    classify_impulse,
    MOTOR_CATALOGUE,
    IMPULSE_CLASS_BOUNDS,
    G0_M_S2,
)


# ---------------------------------------------------------------------------
# 1. Built-in catalogue
# ---------------------------------------------------------------------------

class TestBuiltinCatalogue:
    """The built-in catalogue loads and contains expected motors."""

    def test_catalogue_non_empty(self):
        """Built-in catalogue must have at least 10 motors."""
        assert len(MOTOR_CATALOGUE) >= 10

    def test_catalogue_contains_estes_a8(self):
        """Estes A8 must be present."""
        assert "A8" in MOTOR_CATALOGUE

    def test_catalogue_contains_aerotech_g79(self):
        """Aerotech G79 must be present."""
        assert "G79" in MOTOR_CATALOGUE

    def test_all_motors_have_thrust_curve(self):
        """Every motor must have at least 2 thrust-curve points."""
        for name, motor in MOTOR_CATALOGUE.items():
            assert len(motor.thrust_curve) >= 2, (
                f"Motor '{name}' has fewer than 2 thrust-curve points"
            )

    def test_all_motors_positive_impulse(self):
        """All motors must have positive total impulse."""
        for name, motor in MOTOR_CATALOGUE.items():
            assert motor.total_impulse_ns > 0, (
                f"Motor '{name}' has non-positive total impulse"
            )

    def test_all_motors_positive_isp(self):
        """All motors must have positive Isp."""
        for name, motor in MOTOR_CATALOGUE.items():
            assert motor.isp_s > 0, f"Motor '{name}' has non-positive Isp"

    def test_estes_a8_class(self):
        """Estes A8 must be class A (1.251–2.50 N·s)."""
        a8 = get_motor("A8")
        assert a8.impulse_class == "A"

    def test_aerotech_g79_class(self):
        """Aerotech G79 must be class G (80.001–160.00 N·s)."""
        g79 = get_motor("G79")
        assert g79.impulse_class == "G"

    def test_aerotech_h128_class(self):
        """Aerotech H128 must be class H (160.001–320.00 N·s)."""
        h128 = get_motor("H128")
        assert h128.impulse_class == "H"


# ---------------------------------------------------------------------------
# 2. RASP .eng parser — simple known-answer test
# ---------------------------------------------------------------------------

class TestEngParser:
    """RASP .eng parser produces correct performance data."""

    # Analytic oracle: a triangular thrust profile
    # Thrust: rises linearly 0→100 N from t=0 to t=0.5 s, then drops 100→0 N
    # from t=0.5 to t=1.0 s.
    # Total impulse = 0.5 * 100 * 1.0 = 50 N·s  (area of triangle)
    TRIANGLE_ENG = """\
; Analytic triangular thrust profile: 50 N·s total, 0.5-s peak
TestTriangle 24 70 5 25.0 55.0 TestMfr
0.000 0.00
0.500 100.00
1.000 0.00
"""

    def test_parse_triangle_motor(self):
        """Parse a simple triangular thrust profile."""
        motors = parse_eng(self.TRIANGLE_ENG)
        assert len(motors) == 1
        m = motors[0]
        assert m.name == "TestTriangle"
        assert m.manufacturer == "TestMfr"

    def test_triangle_total_impulse_oracle(self):
        """Triangle area: I = 0.5 × base × height = 0.5 × 1.0 × 100 = 50.0 N·s."""
        motors = parse_eng(self.TRIANGLE_ENG)
        m = motors[0]
        # Trapezoid rule: (0+100)/2 × 0.5 + (100+0)/2 × 0.5 = 25 + 25 = 50
        assert abs(m.total_impulse_ns - 50.0) < 0.01, (
            f"Triangle impulse {m.total_impulse_ns:.4f} ≠ 50.0 N·s"
        )

    def test_triangle_burn_time(self):
        """Burn time for triangle motor must be 0.5 s (last non-zero thrust)."""
        motors = parse_eng(self.TRIANGLE_ENG)
        m = motors[0]
        assert abs(m.burn_time_s - 0.5) < 1e-9, (
            f"Triangle burn time {m.burn_time_s:.4f} s ≠ 0.5 s"
        )

    def test_triangle_average_thrust(self):
        """Average thrust = 50 N·s / 0.5 s = 100 N (note: 50 N·s over burn_time)."""
        motors = parse_eng(self.TRIANGLE_ENG)
        m = motors[0]
        # avg_thrust = total_impulse / burn_time = 50 / 0.5 = 100 N
        assert abs(m.average_thrust_n - 100.0) < 0.01, (
            f"Average thrust {m.average_thrust_n:.3f} N ≠ 100.0 N"
        )

    def test_triangle_isp_oracle(self):
        """Isp = total_impulse / (prop_mass_kg × g0).

        prop_mass = 25 g = 0.025 kg; g0 = 9.80665 m/s²
        Isp = 50 / (0.025 × 9.80665) = 50 / 0.24517 ≈ 203.9 s
        """
        motors = parse_eng(self.TRIANGLE_ENG)
        m = motors[0]
        expected_isp = 50.0 / (0.025 * G0_M_S2)
        assert abs(m.isp_s - expected_isp) < 0.1, (
            f"Isp {m.isp_s:.2f} s ≠ expected {expected_isp:.2f} s"
        )

    def test_comment_parsing(self):
        """Comments in .eng file are captured."""
        motors = parse_eng(self.TRIANGLE_ENG)
        m = motors[0]
        assert any("Analytic" in c for c in m.comments)

    def test_delay_parsing(self):
        """Delays '5' are parsed to [5.0]."""
        motors = parse_eng(self.TRIANGLE_ENG)
        m = motors[0]
        assert m.delays_s == [5.0]

    def test_parse_plugged_motor(self):
        """Motor with 'P' delay has empty delays_s list."""
        eng = """\
; Plugged motor
TestPlugged 38 200 P 100.0 200.0 TestMfr
0.000 0.00
0.500 200.00
1.000 0.00
"""
        motors = parse_eng(eng)
        m = motors[0]
        assert m.delays_s == []

    def test_parse_bytes_input(self):
        """Parser accepts bytes input."""
        eng_bytes = self.TRIANGLE_ENG.encode("utf-8")
        motors = parse_eng(eng_bytes)
        assert len(motors) == 1

    def test_parse_file_like_input(self):
        """Parser accepts file-like input."""
        motors = parse_eng(io.StringIO(self.TRIANGLE_ENG))
        assert len(motors) == 1

    def test_parse_missing_header_raises(self):
        """If no header is present (only data), raise ValueError."""
        eng = """\
; No header
0.000 0.00
0.500 100.00
1.000 0.00
"""
        with pytest.raises(ValueError, match="header"):
            parse_eng(eng)

    def test_parse_incomplete_header_raises(self):
        """Header with fewer than 7 fields must raise ValueError."""
        eng = """\
ShortHeader 24 70 5 25.0
0.000 0.00
1.000 0.00
"""
        with pytest.raises(ValueError, match="7 fields"):
            parse_eng(eng)


# ---------------------------------------------------------------------------
# 3. Multi-motor .eng file
# ---------------------------------------------------------------------------

class TestMultiMotorEng:
    """A single .eng file with multiple motor records."""

    MULTI_ENG = """\
; Motor A
MotorA 18 70 3 5.0 15.0 MfrA
0.000 0.00
0.250 20.00
0.500 0.00

; Motor B
MotorB 24 95 0 10.0 30.0 MfrB
0.000 0.00
0.500 40.00
1.000 0.00
"""

    def test_multi_motor_count(self):
        """Two-motor .eng file parses to 2 motors."""
        motors = parse_eng(self.MULTI_ENG)
        assert len(motors) == 2

    def test_multi_motor_names(self):
        """Both motor names are parsed correctly."""
        motors = parse_eng(self.MULTI_ENG)
        names = {m.name for m in motors}
        assert names == {"MotorA", "MotorB"}

    def test_multi_motor_impulses(self):
        """Motor A: 2.5 N·s; Motor B: 20.0 N·s."""
        motors = parse_eng(self.MULTI_ENG)
        motor_map = {m.name: m for m in motors}
        # MotorA: (0+20)/2 * 0.25 + (20+0)/2 * 0.25 = 2.5 + 2.5 = 5.0...
        # Actually: (0+20)/2 * 0.25 = 2.5 from 0-0.25, (20+0)/2 * 0.25 = 2.5 from 0.25-0.5 → total 5.0
        # Wait, let's recalculate:
        # MotorA: (0+20)/2 × (0.25-0) + (20+0)/2 × (0.5-0.25) = 2.5 + 2.5 = 5.0 N·s
        # MotorB: (0+40)/2 × 0.5 + (40+0)/2 × 0.5 = 10 + 10 = 20 N·s
        assert abs(motor_map["MotorA"].total_impulse_ns - 5.0) < 0.01
        assert abs(motor_map["MotorB"].total_impulse_ns - 20.0) < 0.01


# ---------------------------------------------------------------------------
# 4. Impulse class classification
# ---------------------------------------------------------------------------

class TestImpulseClassification:
    """NAR/TRA impulse classification letter boundaries."""

    @pytest.mark.parametrize("impulse_ns,expected_class", [
        (0.3, "1/4A"),    # 0.3 in 0.0–0.625 → 1/4A
        (1.0, "1/2A"),    # 1.0 in 0.626–1.25 → 1/2A
        (2.0, "A"),       # 2.0 in 1.251–2.50 → A
        (4.0, "B"),       # 4.0 in 2.501–5.00 → B
        (8.0, "C"),       # 8.0 in 5.001–10.00 → C
        (15.0, "D"),      # 15.0 in 10.001–20.00 → D
        (30.0, "E"),      # 30.0 in 20.001–40.00 → E
        (60.0, "F"),      # 60.0 in 40.001–80.00 → F
        (100.0, "G"),     # 100.0 in 80.001–160.00 → G
        (200.0, "H"),     # 200.0 in 160.001–320.00 → H
        (400.0, "I"),     # 400.0 in 320.001–640.00 → I
        (1000.0, "J"),    # 1000.0 in 640.001–1280.00 → J
        (2000.0, "K"),    # 2000.0 in 1280.001–2560.00 → K
        (3000.0, "L"),    # 3000.0 in 2560.001–5120.00 → L
        (6000.0, "M"),    # 6000.0 in 5120.001–10240.00 → M
        (15000.0, "N"),   # 15000.0 in 10240.001–20480.00 → N
    ])
    def test_classification_oracle(self, impulse_ns, expected_class):
        """Classify_impulse returns correct letter."""
        cls = classify_impulse(impulse_ns)
        assert cls == expected_class, (
            f"classify_impulse({impulse_ns}) = '{cls}', expected '{expected_class}'"
        )

    def test_above_range_returns_o_plus(self):
        """Impulse > 40960 N·s returns 'O+'."""
        cls = classify_impulse(50_000.0)
        assert cls == "O+"

    def test_sub_a_returns_quarter_a(self):
        """Impulse 0.1 N·s returns '1/4A' (in 0.0–0.625 range)."""
        cls = classify_impulse(0.1)
        assert cls == "1/4A", f"Got {cls}"


# ---------------------------------------------------------------------------
# 5. Motor selector (list_motors)
# ---------------------------------------------------------------------------

class TestMotorSelector:
    """list_motors filters correctly."""

    def test_list_all(self):
        """list_motors() with no filter returns all catalogue motors."""
        all_motors = list_motors()
        assert len(all_motors) == len(MOTOR_CATALOGUE)

    def test_filter_by_class(self):
        """Filter by impulse_class='G' returns only G-class motors."""
        g_motors = list_motors(impulse_class="G")
        for m in g_motors:
            assert m.impulse_class == "G", f"Motor {m.name} class={m.impulse_class} != G"

    def test_filter_by_manufacturer(self):
        """Filter by manufacturer='Estes' returns only Estes motors."""
        estes = list_motors(manufacturer="Estes")
        assert len(estes) > 0
        for m in estes:
            assert "estes" in m.manufacturer.lower(), (
                f"Motor {m.name} manufacturer={m.manufacturer!r} not Estes"
            )

    def test_filter_by_diameter(self):
        """Filter by diameter_mm=29 (±1mm) returns correct motors."""
        motors_29 = list_motors(diameter_mm=29.0, diameter_tol_mm=0.5)
        for m in motors_29:
            assert abs(m.diameter_mm - 29.0) <= 0.5, (
                f"Motor {m.name} diameter={m.diameter_mm} outside ±0.5mm of 29mm"
            )

    def test_filter_by_class_case_insensitive(self):
        """Class filter is case-insensitive."""
        g_upper = list_motors(impulse_class="G")
        g_lower = list_motors(impulse_class="g")
        assert len(g_upper) == len(g_lower)

    def test_sorted_by_impulse(self):
        """Results are sorted by total impulse ascending."""
        all_motors = list_motors()
        impulses = [m.total_impulse_ns for m in all_motors]
        assert impulses == sorted(impulses), "Motors not sorted by total impulse"

    def test_empty_result_for_unknown_class(self):
        """Filter for a non-existent class returns empty list."""
        result = list_motors(impulse_class="Z")
        assert result == []


# ---------------------------------------------------------------------------
# 6. get_motor
# ---------------------------------------------------------------------------

class TestGetMotor:
    """get_motor: name lookup and error handling."""

    def test_get_a8(self):
        """get_motor('A8') returns the Estes A8."""
        m = get_motor("A8")
        assert m.name == "A8"
        assert m.manufacturer == "Estes"

    def test_case_insensitive_lookup(self):
        """get_motor is case-insensitive."""
        m1 = get_motor("A8")
        m2 = get_motor("a8")
        assert m1.name == m2.name

    def test_unknown_name_raises_key_error(self):
        """get_motor raises KeyError for unknown motor name."""
        with pytest.raises(KeyError, match="not found"):
            get_motor("ZZZ999")


# ---------------------------------------------------------------------------
# 7. thrust_at interpolation
# ---------------------------------------------------------------------------

class TestThrustAtInterpolation:
    """ThrustcurveMotor.thrust_at(t) linear interpolation."""

    # Simple 3-point motor: constant 50 N from 0 to 1 s
    CONSTANT_ENG = """\
; Constant thrust 50 N for 1 second
ConstantMotor 24 95 0 10.0 25.0 TestMfr
0.000 50.00
1.000 50.00
1.001 0.00
"""

    def test_at_known_point(self):
        """thrust_at at a data-point time returns exact value."""
        motors = parse_eng(self.CONSTANT_ENG)
        m = motors[0]
        assert abs(m.thrust_at(0.0) - 50.0) < 1e-9

    def test_interpolation_midpoint(self):
        """thrust_at midpoint of constant section returns ~50 N."""
        motors = parse_eng(self.CONSTANT_ENG)
        m = motors[0]
        assert abs(m.thrust_at(0.5) - 50.0) < 1e-6

    def test_before_ignition(self):
        """thrust_at t < 0 returns 0."""
        motors = parse_eng(self.CONSTANT_ENG)
        m = motors[0]
        assert m.thrust_at(-1.0) == 0.0

    def test_after_burnout(self):
        """thrust_at t > burn_time returns 0."""
        motors = parse_eng(self.CONSTANT_ENG)
        m = motors[0]
        assert m.thrust_at(10.0) == 0.0

    def test_thrust_at_triangle_peak(self):
        """Triangle motor: thrust_at(0.5) should be 100 N (peak)."""
        motors = parse_eng("""\
; Triangle
TriMotor 24 70 0 5.0 15.0 TestMfr
0.000 0.00
0.500 100.00
1.000 0.00
""")
        m = motors[0]
        assert abs(m.thrust_at(0.5) - 100.0) < 1e-6

    def test_thrust_at_triangle_quarter(self):
        """Triangle motor: at t=0.25, thrust = 50 N (linear rising ramp)."""
        motors = parse_eng("""\
; Triangle
TriMotor 24 70 0 5.0 15.0 TestMfr
0.000 0.00
0.500 100.00
1.000 0.00
""")
        m = motors[0]
        # Linear from 0 N at 0 s to 100 N at 0.5 s → at 0.25 s: 50 N
        assert abs(m.thrust_at(0.25) - 50.0) < 1e-6


# ---------------------------------------------------------------------------
# 8. to_dict serialisation
# ---------------------------------------------------------------------------

class TestMotorToDict:
    """to_dict produces JSON-serializable output with required keys."""

    def test_to_dict_keys(self):
        """to_dict must contain required keys."""
        m = get_motor("A8")
        d = m.to_dict()
        required_keys = {
            "name", "manufacturer", "diameter_mm", "length_mm",
            "propellant_mass_g", "total_mass_g", "delays_s",
            "total_impulse_ns", "average_thrust_n", "peak_thrust_n",
            "burn_time_s", "isp_s", "impulse_class", "n_thrust_points",
        }
        assert required_keys.issubset(set(d.keys())), (
            f"Missing keys: {required_keys - set(d.keys())}"
        )

    def test_to_dict_values_are_serializable(self):
        """to_dict values must be JSON-serializable (no numpy types)."""
        import json
        m = get_motor("G79")
        d = m.to_dict()
        # Should not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# 9. LLM tool round-trip
# ---------------------------------------------------------------------------

class TestMotorDatabaseLLMTool:
    """aero_motor_database LLM tool returns well-formed dicts."""

    def test_list_operation(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        result = aero_motor_database(operation="list")
        assert result["ok"] is True
        assert isinstance(result["motors"], list)
        assert result["n_motors"] > 0

    def test_list_filter_by_class(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        result = aero_motor_database(operation="list", impulse_class="G")
        assert result["ok"] is True
        for m in result["motors"]:
            assert m["impulse_class"] == "G"

    def test_get_operation(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        result = aero_motor_database(operation="get", name="A8")
        assert result["ok"] is True
        assert result["motor"]["name"] == "A8"
        assert "thrust_curve" in result["motor"]
        assert len(result["motor"]["thrust_curve"]) >= 2

    def test_get_unknown_name_returns_error(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        result = aero_motor_database(operation="get", name="XYZNOTEXIST")
        assert result["ok"] is False

    def test_parse_eng_operation(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        eng_str = """; My custom motor
CustomX 29 120 0 30.0 60.0 TestMfr
0.000 0.00
0.500 100.00
1.000 0.00
"""
        result = aero_motor_database(operation="parse_eng", eng_text=eng_str)
        assert result["ok"] is True
        assert result["n_motors"] == 1
        m = result["motors"][0]
        assert m["name"] == "CustomX"
        assert abs(m["total_impulse_ns"] - 50.0) < 0.1  # triangle = 50 Ns

    def test_classify_operation(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        result = aero_motor_database(operation="classify", total_impulse_ns=87.5)
        assert result["ok"] is True
        assert result["impulse_class"] == "G"  # 87.5 in 80.001-160 → G

    def test_unknown_operation_raises(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        with pytest.raises(ValueError, match="Unknown operation"):
            aero_motor_database(operation="foobar")

    def test_parse_eng_missing_param_raises(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        with pytest.raises(ValueError, match="eng_text"):
            aero_motor_database(operation="parse_eng")

    def test_classify_missing_impulse_raises(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_motor_database
        with pytest.raises(ValueError, match="total_impulse_ns"):
            aero_motor_database(operation="classify")
