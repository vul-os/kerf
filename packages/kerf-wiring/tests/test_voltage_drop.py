"""
Tests for NEC 2023 voltage-drop calculator (kerf_wiring.voltage_drop).

All expected values are verified against NEC 2023 Chapter 9 Table 8 resistance
data and the formulas in NEC §215.2(A)(1)(b).

DEPTH BAR cases (from spec):
  12AWG Cu, 100ft, 15A, 120V single-phase:
    V_drop = 2 × 15 × (100/1000) × 1.93 = 5.79V  (4.83% of 120V → EXCEEDS 3%)
  4AWG Cu, 200ft, 100A, 480V single-phase:
    V_drop = 2 × 100 × (200/1000) × 0.308 = 12.32V  (2.57% of 480V → within 3%)
"""
from __future__ import annotations

import math
import pytest
from kerf_wiring.voltage_drop import (
    VoltageDropResult,
    compute_voltage_drop,
    _get_resistance,
    _temperature_correct,
    _TABLE_8,
)


# ---------------------------------------------------------------------------
# Unit tests — table lookup and temperature correction
# ---------------------------------------------------------------------------

class TestTable8Lookup:
    def test_known_cu_values(self):
        """Spot-check NEC Ch9 Table 8 resistance values (Cu)."""
        assert _get_resistance("14", "Cu") == pytest.approx(3.07, rel=1e-4)
        assert _get_resistance("12", "Cu") == pytest.approx(1.93, rel=1e-4)
        assert _get_resistance("10", "Cu") == pytest.approx(1.21, rel=1e-4)
        assert _get_resistance("8", "Cu") == pytest.approx(0.764, rel=1e-4)
        assert _get_resistance("6", "Cu") == pytest.approx(0.491, rel=1e-4)
        assert _get_resistance("4", "Cu") == pytest.approx(0.308, rel=1e-4)
        assert _get_resistance("2", "Cu") == pytest.approx(0.194, rel=1e-4)
        assert _get_resistance("1/0", "Cu") == pytest.approx(0.122, rel=1e-4)
        assert _get_resistance("4/0", "Cu") == pytest.approx(0.0608, rel=1e-4)
        assert _get_resistance("500", "Cu") == pytest.approx(0.0258, rel=1e-4)

    def test_known_al_values(self):
        assert _get_resistance("12", "Al") == pytest.approx(3.18, rel=1e-4)
        assert _get_resistance("4/0", "Al") == pytest.approx(0.100, rel=1e-4)

    def test_al_not_available_for_14awg(self):
        with pytest.raises(ValueError, match="not rated"):
            _get_resistance("14", "Al")

    def test_unknown_size_raises(self):
        with pytest.raises(ValueError, match="not in NEC 2023 Chapter 9 Table 8"):
            _get_resistance("99", "Cu")


class TestTemperatureCorrection:
    def test_at_reference_temp_unchanged(self):
        """R(24 °C) should equal table value (T_ref = 75 °F ≈ 24 °C)."""
        r = _get_resistance("12", "Cu")
        assert _temperature_correct(r, "Cu", 24.0) == pytest.approx(r, rel=1e-6)

    def test_75c_higher_than_ref(self):
        """Resistance at 75 °C must be > table value (positive α)."""
        r = _get_resistance("12", "Cu")
        r75 = _temperature_correct(r, "Cu", 75.0)
        assert r75 > r

    def test_known_correction_12awg_cu_75c(self):
        """
        R_ref(12 Cu) = 1.93 Ω/1000ft at 24 °C.
        α_Cu = 0.00323/°C.
        R(75) = 1.93 × (1 + 0.00323 × (75 - 24)) = 1.93 × 1.16473 ≈ 2.248
        """
        r_ref = 1.93
        expected = r_ref * (1.0 + 0.00323 * (75.0 - 24.0))
        assert _temperature_correct(r_ref, "Cu", 75.0) == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# End-to-end NEC table-verified cases
# ---------------------------------------------------------------------------

class TestComputeVoltageDrop:

    # ------------------------------------------------------------------
    # CASE 1 (DEPTH BAR): 12AWG Cu, 100ft, 15A, 120V, single-phase
    # R_ref = 1.93 Ω/1000ft at 24 °C (Table 8)
    # V_drop = 2 × 15 × 100/1000 × 1.93 = 5.79 V  (4.83% of 120V)
    # ------------------------------------------------------------------
    def test_12awg_cu_100ft_15a_120v_single_no_temp_correction(self):
        """Depth-bar check at table reference temp (24 °C ≈ 75 °F)."""
        result = compute_voltage_drop(
            awg="12", material="Cu",
            run_length_ft=100.0, current_amps=15.0,
            voltage=120.0, phase="single",
            conductor_temp_c=24.0,  # no temperature correction
        )
        # V_drop = 2 × 15 × 100/1000 × 1.93 = 5.79 V
        assert result.v_drop_volts == pytest.approx(5.79, abs=0.01)
        assert result.v_drop_percent == pytest.approx(5.79 / 120.0 * 100, abs=0.05)
        assert not result.within_3_percent, "4.8% should exceed 3% limit"
        assert result.within_5_percent, "4.8% should be within 5% limit"

    def test_12awg_cu_100ft_15a_120v_single_exceeds_3pct(self):
        """Standard 75 °C default — drop is even higher (exceeds 3% and 5%)."""
        result = compute_voltage_drop(
            awg="12", material="Cu",
            run_length_ft=100.0, current_amps=15.0,
            voltage=120.0, phase="single",
            conductor_temp_c=75.0,
        )
        assert result.v_drop_percent > 3.0
        assert not result.within_3_percent
        # at 5.6%+ it also exceeds 5%
        assert not result.within_5_percent

    # ------------------------------------------------------------------
    # CASE 2 (DEPTH BAR): 4AWG Cu, 200ft, 100A, 480V, single-phase
    # R_ref = 0.308 Ω/1000ft
    # V_drop = 2 × 100 × 200/1000 × 0.308 = 12.32V (2.57% of 480V → within 3%)
    # ------------------------------------------------------------------
    def test_4awg_cu_200ft_100a_480v_single_within_3pct(self):
        """Depth-bar: 4AWG Cu, 200ft, 100A, 480V — within 3%."""
        result = compute_voltage_drop(
            awg="4", material="Cu",
            run_length_ft=200.0, current_amps=100.0,
            voltage=480.0, phase="single",
            conductor_temp_c=24.0,
        )
        assert result.v_drop_volts == pytest.approx(12.32, abs=0.02)
        assert result.v_drop_percent == pytest.approx(12.32 / 480.0 * 100.0, abs=0.05)
        assert result.within_3_percent, "2.57% should be within 3% branch limit"
        assert result.within_5_percent

    # ------------------------------------------------------------------
    # CASE 3: 3-phase, 10AWG Cu, 150ft, 20A, 208V
    # R_ref(10 Cu) = 1.21 Ω/1000ft at 24 °C
    # V_drop = sqrt(3) × 20 × 150/1000 × 1.21 ≈ 6.29V  (~3% of 208V)
    # ------------------------------------------------------------------
    def test_10awg_cu_3phase_150ft_20a_208v(self):
        result = compute_voltage_drop(
            awg="10", material="Cu",
            run_length_ft=150.0, current_amps=20.0,
            voltage=208.0, phase="three",
            conductor_temp_c=24.0,
        )
        expected_v = math.sqrt(3) * 20.0 * (150.0 / 1000.0) * 1.21
        assert result.v_drop_volts == pytest.approx(expected_v, rel=1e-5)
        expected_pct = expected_v / 208.0 * 100.0
        assert result.v_drop_percent == pytest.approx(expected_pct, abs=0.01)

    # ------------------------------------------------------------------
    # CASE 4: 3% boundary check
    # ------------------------------------------------------------------
    def test_exactly_3pct_boundary(self):
        """Check that a drop just below 3% passes and 1% over fails."""
        # 6AWG Cu, 3-phase, 50A, 480V at ref temp
        r_ref = 0.491  # Ω/1000ft
        target_v = 480.0 * 0.03  # 14.4V
        # L that gives exactly 3%: L = target_v / (sqrt(3) * I * r_per_ft)
        L = target_v / (math.sqrt(3) * 50.0 * (r_ref / 1000.0))

        # Slightly under 3% — must pass
        result_under = compute_voltage_drop(
            awg="6", material="Cu",
            run_length_ft=L * 0.999, current_amps=50.0,
            voltage=480.0, phase="three",
            conductor_temp_c=24.0,
        )
        assert result_under.within_3_percent, "run just under 3% should be within limit"

        # Slightly over 3% — must fail
        result_over = compute_voltage_drop(
            awg="6", material="Cu",
            run_length_ft=L * 1.01, current_amps=50.0,
            voltage=480.0, phase="three",
            conductor_temp_c=24.0,
        )
        assert not result_over.within_3_percent, "1% over 3% boundary should fail"

    # ------------------------------------------------------------------
    # CASE 5: Aluminium conductor — 2AWG Al, 100ft, 50A, 120V single-phase
    # R_ref(2 Al) = 0.319 Ω/1000ft
    # V_drop = 2 × 50 × 100/1000 × 0.319 = 3.19V  (2.66% → within 3%)
    # ------------------------------------------------------------------
    def test_2awg_al_100ft_50a_120v(self):
        result = compute_voltage_drop(
            awg="2", material="Al",
            run_length_ft=100.0, current_amps=50.0,
            voltage=120.0, phase="single",
            conductor_temp_c=24.0,
        )
        assert result.v_drop_volts == pytest.approx(3.19, abs=0.01)
        assert result.within_3_percent

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    def test_invalid_awg_raises(self):
        with pytest.raises(ValueError, match="not in NEC 2023 Chapter 9 Table 8"):
            compute_voltage_drop("99", "Cu", 100, 15, 120)

    def test_invalid_material_raises(self):
        with pytest.raises(ValueError, match="material must be"):
            compute_voltage_drop("12", "Fe", 100, 15, 120)  # type: ignore

    def test_invalid_phase_raises(self):
        with pytest.raises(ValueError, match="phase must be"):
            compute_voltage_drop("12", "Cu", 100, 15, 120, phase="delta")  # type: ignore

    def test_negative_length_raises(self):
        with pytest.raises(ValueError, match="run_length_ft must be > 0"):
            compute_voltage_drop("12", "Cu", -10, 15, 120)

    def test_zero_current_raises(self):
        with pytest.raises(ValueError, match="current_amps must be > 0"):
            compute_voltage_drop("12", "Cu", 100, 0, 120)

    def test_zero_voltage_raises(self):
        with pytest.raises(ValueError, match="voltage must be > 0"):
            compute_voltage_drop("12", "Cu", 100, 15, 0)

    def test_al_below_awg12_raises(self):
        with pytest.raises(ValueError, match="not rated"):
            compute_voltage_drop("14", "Al", 100, 15, 120)

    # ------------------------------------------------------------------
    # Notes content checks
    # ------------------------------------------------------------------
    def test_honest_flag_note_present(self):
        """DC-only honest-flag note must appear in every result."""
        result = compute_voltage_drop("12", "Cu", 100, 15, 120)
        assert any("AC reactance" in n for n in result.notes)
        assert any("DC resistance only" in n for n in result.notes)

    def test_nec_215_2_note_present(self):
        result = compute_voltage_drop("12", "Cu", 100, 15, 120)
        assert any("215.2" in n for n in result.notes)

    def test_large_conductor_xl_warning(self):
        """1/0 AWG should trigger X_L advisory note."""
        result = compute_voltage_drop("1/0", "Cu", 200, 100, 480)
        assert any("inductive reactance" in n for n in result.notes)

    def test_small_conductor_no_xl_warning(self):
        """12 AWG should NOT trigger the X_L advisory."""
        result = compute_voltage_drop("12", "Cu", 100, 15, 120)
        assert not any("inductive reactance" in n for n in result.notes)

    def test_exceeds_3pct_note_present(self):
        result = compute_voltage_drop("12", "Cu", 100, 15, 120)
        assert any("EXCEEDS" in n and "3%" in n for n in result.notes)

    def test_within_limit_no_exceed_note(self):
        # 4AWG, 200ft, 100A, 480V is within both limits (at reference temp)
        result = compute_voltage_drop("4", "Cu", 200, 100, 480, conductor_temp_c=24.0)
        assert not any("EXCEEDS NEC §215.2 3%" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Regression guard — Table 8 spot-check
# ---------------------------------------------------------------------------

class TestTable8Integrity:
    @pytest.mark.parametrize("awg,cu_r,al_r", [
        ("14",  3.07,  None),
        ("12",  1.93,  3.18),
        ("10",  1.21,  2.00),
        ("8",   0.764, 1.26),
        ("6",   0.491, 0.808),
        ("4",   0.308, 0.508),
        ("2",   0.194, 0.319),
        ("1/0", 0.122, 0.201),
        ("4/0", 0.0608, 0.100),
        ("500", 0.0258, 0.0424),
    ])
    def test_table8_values(self, awg, cu_r, al_r):
        stored_cu, stored_al = _TABLE_8[awg]
        assert stored_cu == pytest.approx(cu_r, rel=1e-4), f"Cu mismatch for {awg}"
        if al_r is not None:
            assert stored_al == pytest.approx(al_r, rel=1e-4), f"Al mismatch for {awg}"
