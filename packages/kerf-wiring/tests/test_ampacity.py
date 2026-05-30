"""
Tests for NEC 2023 ampacity calculator (kerf_wiring.ampacity).

All expected values are verified against NFPA 70-2023 Table 310.16 and
correction-factor formulas in §310.15(B)(2)(a) and §310.15(B)(3)(a).
"""
from __future__ import annotations

import math
import pytest
from kerf_wiring.ampacity import (
    AmpacityResult,
    compute_ampacity,
    _ambient_correction,
    _bundling_factor,
    TABLE_310_16,
)


# ---------------------------------------------------------------------------
# Unit tests — correction factor formulas
# ---------------------------------------------------------------------------

class TestAmbientCorrectionFactor:
    def test_reference_30c_is_unity(self):
        """NEC §310.15(B)(2)(a): at 30 °C ambient the factor must be 1.0."""
        cf = _ambient_correction(90, 30.0)
        assert cf == pytest.approx(1.0, abs=1e-9)

    def test_40c_ambient_90c_insulation(self):
        """NEC §310.15(B)(2)(a): 90 °C insulation, 40 °C ambient → 0.91."""
        # sqrt((90-40)/(90-30)) = sqrt(50/60) ≈ 0.9129
        cf = _ambient_correction(90, 40.0)
        assert cf == pytest.approx(math.sqrt(50 / 60), rel=1e-6)
        assert cf == pytest.approx(0.9129, abs=0.0005)

    def test_50c_ambient_90c_insulation(self):
        """NEC §310.15(B)(2)(a): 90 °C insulation, 50 °C ambient → 0.82."""
        # sqrt((90-50)/(90-30)) = sqrt(40/60) ≈ 0.8165
        cf = _ambient_correction(90, 50.0)
        assert cf == pytest.approx(math.sqrt(40 / 60), rel=1e-6)
        assert cf == pytest.approx(0.8165, abs=0.0005)

    def test_ambient_equals_rating_raises(self):
        with pytest.raises(ValueError, match="unusable"):
            _ambient_correction(90, 90.0)

    def test_ambient_above_rating_raises(self):
        with pytest.raises(ValueError):
            _ambient_correction(75, 80.0)


class TestBundlingFactor:
    def test_1_conductor(self):
        assert _bundling_factor(1) == 1.00

    def test_3_conductors(self):
        assert _bundling_factor(3) == 1.00

    def test_4_conductors(self):
        """NEC Table 310.15(B)(3)(a): 4–6 conductors → 0.80."""
        assert _bundling_factor(4) == 0.80

    def test_6_conductors(self):
        assert _bundling_factor(6) == 0.80

    def test_7_conductors(self):
        assert _bundling_factor(7) == 0.70

    def test_9_conductors(self):
        assert _bundling_factor(9) == 0.70

    def test_10_conductors(self):
        assert _bundling_factor(10) == 0.50

    def test_20_conductors(self):
        assert _bundling_factor(20) == 0.50

    def test_21_conductors(self):
        assert _bundling_factor(21) == 0.45


# ---------------------------------------------------------------------------
# Integration tests — compute_ampacity end-to-end NEC table-verified cases
# ---------------------------------------------------------------------------

class TestComputeAmpacity:

    # ------------------------------------------------------------------
    # CASE 1: 12 AWG Cu THHN (90 °C) at 30 °C ambient, no bundle → 30 A
    # NEC Table 310.16: 12 AWG Cu 90 °C column = 30 A.
    # Ambient CF at 30 °C = 1.00; bundle factor for 1 cond = 1.00.
    # Expected: 30 × 1.00 × 1.00 = 30.0 A
    # ------------------------------------------------------------------
    def test_12awg_cu_90c_baseline(self):
        r = compute_ampacity("12", "Cu", 90, 30.0, 1, "conduit")
        assert isinstance(r, AmpacityResult)
        assert r.base_ampacity_a == 30.0
        assert r.ambient_correction_factor == pytest.approx(1.0, abs=1e-9)
        assert r.bundling_factor == 1.00
        assert r.derated_ampacity_a == pytest.approx(30.0, abs=0.01)

    # ------------------------------------------------------------------
    # CASE 2: 12 AWG Cu THHN bundled with 4 conductors → 24 A
    # 30 A × 0.80 (NEC Table 310.15(B)(3)(a), 4–6 conductors) = 24.0 A
    # ------------------------------------------------------------------
    def test_12awg_cu_90c_bundle4(self):
        r = compute_ampacity("12", "Cu", 90, 30.0, 4, "conduit")
        assert r.bundling_factor == 0.80
        assert r.derated_ampacity_a == pytest.approx(24.0, abs=0.01)

    # ------------------------------------------------------------------
    # CASE 3: 12 AWG Cu THHN at 40 °C ambient → ≈ 27.3 A
    # 30 A × sqrt((90-40)/(90-30)) = 30 × 0.9129 ≈ 27.39 A
    # ------------------------------------------------------------------
    def test_12awg_cu_90c_ambient40(self):
        r = compute_ampacity("12", "Cu", 90, 40.0, 1, "conduit")
        assert r.ambient_correction_factor == pytest.approx(math.sqrt(50 / 60), rel=1e-5)
        assert r.derated_ampacity_a == pytest.approx(30.0 * math.sqrt(50 / 60), abs=0.01)
        # NEC tables round this to 27.3 A
        assert r.derated_ampacity_a == pytest.approx(27.39, abs=0.05)

    # ------------------------------------------------------------------
    # CASE 4: 4/0 AWG Cu THHN baseline → 260 A  (large cable verification)
    # NEC Table 310.16: 4/0 AWG Cu 90 °C = 260 A
    # ------------------------------------------------------------------
    def test_4_0awg_cu_90c_baseline(self):
        r = compute_ampacity("4/0", "Cu", 90, 30.0, 1, "conduit")
        assert r.base_ampacity_a == 260.0
        assert r.derated_ampacity_a == pytest.approx(260.0, abs=0.01)

    # ------------------------------------------------------------------
    # CASE 5: 1/0 AWG Cu THHN bundled 9 conductors at 40 °C ambient
    # Base: 170 A (NEC Table 310.16, 1/0 Cu 90 °C)
    # Ambient CF: sqrt((90-40)/(90-30)) ≈ 0.9129
    # Bundle CF: 0.70 (7–9 conductors, NEC Table 310.15(B)(3)(a))
    # Expected: 170 × 0.9129 × 0.70 ≈ 108.64 A
    # ------------------------------------------------------------------
    def test_1_0awg_cu_90c_bundle9_ambient40(self):
        r = compute_ampacity("1/0", "Cu", 90, 40.0, 9, "conduit")
        assert r.base_ampacity_a == 170.0
        assert r.bundling_factor == 0.70
        expected = 170.0 * math.sqrt(50 / 60) * 0.70
        assert r.derated_ampacity_a == pytest.approx(expected, abs=0.05)

    # ------------------------------------------------------------------
    # CASE 6: Aluminum 2/0 AWG THHN 90 °C baseline → 150 A
    # NEC Table 310.16: 2/0 AWG Al 90 °C = 150 A
    # Honest-flag check: Al note must appear in result.notes
    # ------------------------------------------------------------------
    def test_2_0awg_al_90c_baseline(self):
        r = compute_ampacity("2/0", "Al", 90, 30.0, 1, "conduit")
        assert r.base_ampacity_a == 150.0
        assert r.derated_ampacity_a == pytest.approx(150.0, abs=0.01)
        assert any("78%" in n for n in r.notes), \
            "Aluminum honest-flag note (78%) must appear in notes"

    # ------------------------------------------------------------------
    # CASE 7: 8 AWG Cu at 75 °C insulation rating → 50 A
    # NEC Table 310.16: 8 AWG Cu 75 °C column = 50 A
    # ------------------------------------------------------------------
    def test_8awg_cu_75c_baseline(self):
        r = compute_ampacity("8", "Cu", 75, 30.0, 1, "conduit")
        assert r.base_ampacity_a == 50.0
        assert r.derated_ampacity_a == pytest.approx(50.0, abs=0.01)

    # ------------------------------------------------------------------
    # CASE 8: kcmil 500 Cu THHN → 430 A
    # NEC Table 310.16: 500 kcmil Cu 90 °C = 430 A
    # ------------------------------------------------------------------
    def test_500kcmil_cu_90c_baseline(self):
        r = compute_ampacity("500", "Cu", 90, 30.0, 1, "conduit")
        assert r.base_ampacity_a == 430.0
        assert r.derated_ampacity_a == pytest.approx(430.0, abs=0.01)

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------
    def test_invalid_awg_raises(self):
        with pytest.raises(ValueError, match="not in NEC Table 310.16"):
            compute_ampacity("99", "Cu", 90, 30.0, 1)

    def test_invalid_material_raises(self):
        with pytest.raises(ValueError, match="material must be"):
            compute_ampacity("12", "Fe", 90, 30.0, 1)  # type: ignore

    def test_invalid_insulation_raises(self):
        with pytest.raises(ValueError, match="insulation_temp_c"):
            compute_ampacity("12", "Cu", 85, 30.0, 1)  # type: ignore

    def test_aluminum_below_awg12_raises(self):
        with pytest.raises(ValueError, match="not rated"):
            compute_ampacity("14", "Al", 90, 30.0, 1)

    def test_ambient_exceeds_rating_raises(self):
        with pytest.raises(ValueError, match="unusable"):
            compute_ampacity("12", "Cu", 90, 95.0, 1)

    def test_free_air_returns_note(self):
        r = compute_ampacity("12", "Cu", 90, 30.0, 1, "free_air")
        assert any("Table 310.17" in n for n in r.notes)

    def test_cable_tray_same_as_conduit(self):
        r_conduit = compute_ampacity("12", "Cu", 90, 30.0, 1, "conduit")
        r_tray = compute_ampacity("12", "Cu", 90, 30.0, 1, "cable_tray")
        assert r_conduit.derated_ampacity_a == r_tray.derated_ampacity_a

    def test_110_14c_advisory_present_for_90c(self):
        r = compute_ampacity("12", "Cu", 90, 30.0, 1, "conduit")
        assert any("110.14" in n for n in r.notes), \
            "NEC 110.14(C) terminal advisory must appear for 90 °C insulation"

    def test_combined_derate_notes_present(self):
        r = compute_ampacity("12", "Cu", 90, 40.0, 6, "conduit")
        assert any("310.15(B)(2)(a)" in n for n in r.notes)
        assert any("310.15(B)(3)(a)" in n for n in r.notes)


# ---------------------------------------------------------------------------
# Spot-check TABLE_310_16 key values (regression guard)
# ---------------------------------------------------------------------------

class TestTable310_16Integrity:
    @pytest.mark.parametrize("awg,col_90cu,col_90al", [
        ("14",  25,   0),
        ("12",  30,  25),
        ("10",  40,  35),
        ("8",   55,  45),
        ("6",   75,  60),
        ("4",   95,  75),
        ("3",  110,  85),
        ("2",  130, 100),
        ("1",  150, 115),
        ("1/0",170, 135),
        ("2/0",195, 150),
        ("3/0",225, 175),
        ("4/0",260, 205),
    ])
    def test_90c_column(self, awg, col_90cu, col_90al):
        row = TABLE_310_16[awg]
        assert row[2] == col_90cu, f"Cu 90°C mismatch for AWG {awg}"
        assert row[5] == col_90al, f"Al 90°C mismatch for AWG {awg}"
