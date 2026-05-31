"""
Tests for kerf_cad_core.gdt.datum_shift_check — ASME Y14.5-2018 §4.5 + §7.3.5.

All tests are pure-Python, hermetic — no OCC, no DB, no network.

Coverage:
  - DatumFeatureSpec construction and validation
  - compute_datum_shift: MMC, LMC, RFS modifiers
  - bonus zero when measured == MMC exactly
  - bonus zero when measured == LMC exactly
  - LMC modifier reversal (departure from LMC boundary)
  - multi-datum scenario (independent per-datum computation)
  - DatumShiftReport structure and to_dict()
  - error handling (bad inputs)
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.gdt.datum_shift_check import (
    DatumFeatureSpec,
    DatumShiftReport,
    compute_datum_shift,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(
    *,
    datum_letter: str = "A",
    mmc_size_mm: float = 10.0,
    lmc_size_mm: float = 10.5,
    measured_size_mm: float = 10.3,
    material_condition_modifier: str = "MMC",
) -> DatumFeatureSpec:
    return DatumFeatureSpec(
        datum_letter=datum_letter,
        mmc_size_mm=mmc_size_mm,
        lmc_size_mm=lmc_size_mm,
        measured_size_mm=measured_size_mm,
        material_condition_modifier=material_condition_modifier,
    )


# ---------------------------------------------------------------------------
# Test 1: Canonical MMC hole datum — task-specified oracle
# Hole datum MMC=10.0, LMC=10.5, measured=10.3, base_tol=0.5
# Expected: bonus=0.3, total=0.8
# ---------------------------------------------------------------------------

class TestCanonicalMMCHoleDatum:
    """Task-specified oracle: MMC=10.0, LMC=10.5, measured=10.3, base_tol=0.5."""

    def test_bonus_is_0_3(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.bonus_shift_mm, 0.3, abs_tol=1e-9)

    def test_total_is_0_8(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.total_available_tolerance_mm, 0.8, abs_tol=1e-9)

    def test_base_tolerance_preserved(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.base_tolerance_zone_mm, 0.5, abs_tol=1e-9)

    def test_shift_allowed_true(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.shift_allowed is True

    def test_datum_letter_preserved(self):
        datum = _spec(datum_letter="B", mmc_size_mm=10.0, lmc_size_mm=10.5,
                      measured_size_mm=10.3, material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.datum_letter == "B"


# ---------------------------------------------------------------------------
# Test 2: RFS modifier — bonus is always zero
# ---------------------------------------------------------------------------

class TestRFSModifier:
    """RFS: shift = 0 regardless of how far measured departs from MMC/LMC."""

    def test_rfs_bonus_zero_nominal(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="RFS")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.bonus_shift_mm == 0.0

    def test_rfs_total_equals_base(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="RFS")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.total_available_tolerance_mm, 0.5, abs_tol=1e-9)

    def test_rfs_shift_allowed_false(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                      material_condition_modifier="RFS")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.shift_allowed is False

    def test_rfs_bonus_zero_extreme_departure(self):
        """Even if measured is far from MMC, RFS still gives zero shift."""
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=15.0, measured_size_mm=14.9,
                      material_condition_modifier="RFS")
        report = compute_datum_shift(datum, base_position_tolerance_mm=1.0)
        assert report.bonus_shift_mm == 0.0
        assert math.isclose(report.total_available_tolerance_mm, 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Test 3: Measured at MMC exactly — bonus must be zero
# ---------------------------------------------------------------------------

class TestMeasuredAtMMCExactly:
    """When measured == MMC, departure = 0, so bonus_shift = 0."""

    def test_measured_equals_mmc_bonus_zero(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.0,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.bonus_shift_mm == 0.0

    def test_measured_equals_mmc_total_equals_base(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.0,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.total_available_tolerance_mm, 0.5, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Test 4: LMC modifier — departure from LMC boundary
# ---------------------------------------------------------------------------

class TestLMCModifier:
    """LMC: shift = |measured - lmc_size|."""

    def test_lmc_bonus_correct(self):
        # measured=10.2, lmc=10.5 → departure = 0.3
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.2,
                      material_condition_modifier="LMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.bonus_shift_mm, 0.3, abs_tol=1e-9)

    def test_lmc_total_correct(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.2,
                      material_condition_modifier="LMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert math.isclose(report.total_available_tolerance_mm, 0.8, abs_tol=1e-9)

    def test_lmc_shift_allowed_true(self):
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.2,
                      material_condition_modifier="LMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.shift_allowed is True

    def test_lmc_measured_at_lmc_boundary_zero_bonus(self):
        """When measured == lmc_size, departure = 0, bonus = 0."""
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.5,
                      material_condition_modifier="LMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert report.bonus_shift_mm == 0.0
        assert math.isclose(report.total_available_tolerance_mm, 0.5, abs_tol=1e-9)

    def test_lmc_reversal_uses_lmc_not_mmc(self):
        """LMC modifier measures departure from LMC — not from MMC.
        For same measured=10.3 with LMC=10.5:
          LMC bonus = |10.3 - 10.5| = 0.2
          MMC bonus = |10.3 - 10.0| = 0.3
        They must differ.
        """
        datum_mmc = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                          material_condition_modifier="MMC")
        datum_lmc = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.3,
                          material_condition_modifier="LMC")
        report_mmc = compute_datum_shift(datum_mmc, base_position_tolerance_mm=0.5)
        report_lmc = compute_datum_shift(datum_lmc, base_position_tolerance_mm=0.5)
        # MMC bonus = 0.3; LMC bonus = 0.2
        assert math.isclose(report_mmc.bonus_shift_mm, 0.3, abs_tol=1e-9)
        assert math.isclose(report_lmc.bonus_shift_mm, 0.2, abs_tol=1e-9)
        assert not math.isclose(report_mmc.bonus_shift_mm, report_lmc.bonus_shift_mm,
                                abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Test 5: Multi-datum DRF — independent computation per datum
# ---------------------------------------------------------------------------

class TestMultiDatumIndependence:
    """Secondary / tertiary datums computed independently per §4.5."""

    def test_two_datums_independent(self):
        datum_a = _spec(datum_letter="A", mmc_size_mm=20.0, lmc_size_mm=21.0,
                        measured_size_mm=20.5, material_condition_modifier="MMC")
        datum_b = _spec(datum_letter="B", mmc_size_mm=10.0, lmc_size_mm=10.5,
                        measured_size_mm=10.3, material_condition_modifier="MMC")
        report_a = compute_datum_shift(datum_a, base_position_tolerance_mm=0.2)
        report_b = compute_datum_shift(datum_b, base_position_tolerance_mm=0.5)
        # Datum A: bonus = |20.5 - 20.0| = 0.5; total = 0.7
        assert math.isclose(report_a.bonus_shift_mm, 0.5, abs_tol=1e-9)
        assert math.isclose(report_a.total_available_tolerance_mm, 0.7, abs_tol=1e-9)
        # Datum B: bonus = |10.3 - 10.0| = 0.3; total = 0.8
        assert math.isclose(report_b.bonus_shift_mm, 0.3, abs_tol=1e-9)
        assert math.isclose(report_b.total_available_tolerance_mm, 0.8, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Test 6: DatumShiftReport structure
# ---------------------------------------------------------------------------

class TestDatumShiftReportStructure:
    """Check report attributes and to_dict()."""

    def test_to_dict_keys(self):
        datum = _spec()
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        d = report.to_dict()
        assert "datum_letter" in d
        assert "base_tolerance_zone_mm" in d
        assert "bonus_shift_mm" in d
        assert "total_available_tolerance_mm" in d
        assert "shift_allowed" in d
        assert "code_section" in d
        assert "honest_caveat" in d

    def test_code_section_mentions_y14_5(self):
        datum = _spec()
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert "Y14.5" in report.code_section

    def test_honest_caveat_non_empty(self):
        datum = _spec()
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert len(report.honest_caveat) > 20

    def test_report_is_dataclass(self):
        datum = _spec()
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        assert isinstance(report, DatumShiftReport)


# ---------------------------------------------------------------------------
# Test 7: Error handling — invalid inputs
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Invalid inputs must raise ValueError."""

    def test_invalid_material_condition_modifier(self):
        with pytest.raises(ValueError, match="material_condition_modifier"):
            DatumFeatureSpec(
                datum_letter="A",
                mmc_size_mm=10.0,
                lmc_size_mm=10.5,
                measured_size_mm=10.3,
                material_condition_modifier="INVALID",
            )

    def test_zero_mmc_size(self):
        with pytest.raises(ValueError, match="mmc_size_mm"):
            DatumFeatureSpec(
                datum_letter="A",
                mmc_size_mm=0.0,
                lmc_size_mm=10.5,
                measured_size_mm=10.3,
                material_condition_modifier="MMC",
            )

    def test_zero_base_tolerance(self):
        datum = _spec()
        with pytest.raises(ValueError, match="base_position_tolerance_mm"):
            compute_datum_shift(datum, base_position_tolerance_mm=0.0)

    def test_negative_base_tolerance(self):
        datum = _spec()
        with pytest.raises(ValueError, match="base_position_tolerance_mm"):
            compute_datum_shift(datum, base_position_tolerance_mm=-0.1)

    def test_empty_datum_letter(self):
        with pytest.raises(ValueError, match="datum_letter"):
            DatumFeatureSpec(
                datum_letter="",
                mmc_size_mm=10.0,
                lmc_size_mm=10.5,
                measured_size_mm=10.3,
                material_condition_modifier="MMC",
            )


# ---------------------------------------------------------------------------
# Test 8: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases: large values, floating-point precision."""

    def test_large_feature_mmc(self):
        """Large shaft datum at MMC, measured slightly above MMC."""
        datum = _spec(datum_letter="C", mmc_size_mm=100.0, lmc_size_mm=99.5,
                      measured_size_mm=99.8, material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.1)
        # MMC bonus = |99.8 - 100.0| = 0.2
        assert math.isclose(report.bonus_shift_mm, 0.2, abs_tol=1e-9)
        assert math.isclose(report.total_available_tolerance_mm, 0.3, abs_tol=1e-9)

    def test_full_departure_to_lmc_with_mmc_modifier(self):
        """Measured at LMC boundary with MMC modifier — maximum possible bonus."""
        datum = _spec(mmc_size_mm=10.0, lmc_size_mm=10.5, measured_size_mm=10.5,
                      material_condition_modifier="MMC")
        report = compute_datum_shift(datum, base_position_tolerance_mm=0.5)
        # Full tolerance range departure: |10.5 - 10.0| = 0.5
        assert math.isclose(report.bonus_shift_mm, 0.5, abs_tol=1e-9)
        assert math.isclose(report.total_available_tolerance_mm, 1.0, abs_tol=1e-9)

    def test_datum_letter_normalised_uppercase(self):
        """Lower-case datum letter is normalised to upper-case."""
        datum = DatumFeatureSpec(
            datum_letter="a",
            mmc_size_mm=10.0,
            lmc_size_mm=10.5,
            measured_size_mm=10.3,
            material_condition_modifier="mmc",
        )
        assert datum.datum_letter == "A"
        assert datum.material_condition_modifier == "MMC"

    def test_from_dict_round_trip(self):
        """DatumFeatureSpec.from_dict preserves all values."""
        datum = _spec(datum_letter="D", mmc_size_mm=15.0, lmc_size_mm=15.8,
                      measured_size_mm=15.4, material_condition_modifier="LMC")
        d = datum.to_dict()
        datum2 = DatumFeatureSpec.from_dict(d)
        assert datum2.datum_letter == datum.datum_letter
        assert datum2.mmc_size_mm == datum.mmc_size_mm
        assert datum2.lmc_size_mm == datum.lmc_size_mm
        assert datum2.measured_size_mm == datum.measured_size_mm
        assert datum2.material_condition_modifier == datum.material_condition_modifier
