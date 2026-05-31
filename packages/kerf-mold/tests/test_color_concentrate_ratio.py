"""
Tests for kerf_mold.color_concentrate_ratio.

Oracle values:
  - 100 g shot, target 1 % pigment, masterbatch at 40 % pigment:
      LDR = 1/40 × 100 = 2.5 %
      MB per shot = 100 × 0.025 = 2.5 g
      MB per kg natural = 1000 × 0.025 / 0.975 ≈ 25.641 g/kg
  - LDR 0.2 % → high streaking risk (< 0.5 % threshold)
  - LDR 10 % → high streaking risk (> 8 %) + cost-waste warning
  - Short residence (<5 s) + low L/D → mixing index low → moderate risk
"""

from __future__ import annotations

import math
import pytest

from kerf_mold.color_concentrate_ratio import (
    ColorConcentrateSpec,
    ShotSpec,
    ColorRatioReport,
    LDR_MIN_SPI_PCT,
    LDR_MAX_SPI_PCT,
    LDR_LOW_RISK_PCT,
    LDR_COST_WASTE_PCT,
    MIXING_INDEX_ADEQUATE,
    MIXING_INDEX_POOR,
    compute_color_ratio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conc(
    pigment_pct: float = 40.0,
    rec_ldr: float = 2.5,
    carrier: str = "PP",
    melt_c: float = 220.0,
) -> ColorConcentrateSpec:
    return ColorConcentrateSpec(
        pigment_loading_in_masterbatch_pct=pigment_pct,
        recommended_let_down_pct=rec_ldr,
        carrier_resin=carrier,
        melting_temp_C=melt_c,
    )


def _make_shot(
    shot_g: float = 100.0,
    target_pct: float = 1.0,
    residence_s: float = 30.0,
    l_over_d: float = 20.0,
) -> ShotSpec:
    return ShotSpec(
        shot_weight_g=shot_g,
        target_pigment_loading_pct=target_pct,
        barrel_residence_time_s=residence_s,
        screw_L_over_D=l_over_d,
    )


# ---------------------------------------------------------------------------
# T1 — Oracle: 100g shot, 1% target, 40% MB → LDR=2.5%, MB=2.5g
# ---------------------------------------------------------------------------

class TestOracleNominalCase:
    def setup_method(self):
        self.report = compute_color_ratio(_make_conc(), _make_shot())

    def test_let_down_ratio_exact(self):
        assert abs(self.report.let_down_ratio_pct - 2.5) < 1e-9

    def test_masterbatch_per_shot_exact(self):
        assert abs(self.report.masterbatch_per_shot_g - 2.5) < 1e-9

    def test_masterbatch_per_kg_natural(self):
        # 1000 × 0.025 / 0.975 ≈ 25.6410...
        expected = 1000.0 * 0.025 / 0.975
        assert abs(self.report.masterbatch_per_kg_natural - expected) < 1e-4

    def test_return_type(self):
        assert isinstance(self.report, ColorRatioReport)

    def test_has_honest_caveat(self):
        assert len(self.report.honest_caveat) > 50


# ---------------------------------------------------------------------------
# T2 — Mixing index formula correctness
# ---------------------------------------------------------------------------

class TestMixingIndex:
    def test_known_value_ld20_30s(self):
        # mixing_index = 1 - exp(-30 × 20 / 200) = 1 - exp(-3) ≈ 0.9502
        # report rounds to 6 dp, so tolerance is 5e-7
        report = compute_color_ratio(_make_conc(), _make_shot(residence_s=30.0, l_over_d=20.0))
        expected = 1.0 - math.exp(-30.0 * 20.0 / 200.0)
        assert abs(report.mixing_index_estimate - expected) < 5e-7

    def test_known_value_ld20_10s(self):
        # mixing_index = 1 - exp(-10 × 20 / 200) = 1 - exp(-1) ≈ 0.6321
        report = compute_color_ratio(_make_conc(), _make_shot(residence_s=10.0, l_over_d=20.0))
        expected = 1.0 - math.exp(-10.0 * 20.0 / 200.0)
        assert abs(report.mixing_index_estimate - expected) < 5e-7

    def test_mixing_index_in_unit_range(self):
        # At res=100, L/D=30 the raw value 1-exp(-15) ≈ 0.9999997 rounds to 1.0 at
        # 6 dp, so we accept [0, 1] inclusive; the key check is it is never negative
        # and never greater than 1.
        for res, ld in [(1.0, 5.0), (5.0, 20.0), (100.0, 30.0)]:
            report = compute_color_ratio(
                _make_conc(), _make_shot(residence_s=res, l_over_d=ld)
            )
            assert 0.0 < report.mixing_index_estimate <= 1.0


# ---------------------------------------------------------------------------
# T3 — Low-risk classification
# ---------------------------------------------------------------------------

class TestLowRisk:
    def test_nominal_case_low_risk(self):
        # LDR 2.5%, residence 30s L/D 20 → mixing_index ≈ 0.950 → low risk
        report = compute_color_ratio(_make_conc(), _make_shot())
        assert report.color_streaking_risk == "low"

    def test_1pct_target_25pct_mb_ld24(self):
        # LDR = 1/25 × 100 = 4%, residence 40s L/D 24
        # mixing = 1 - exp(-40 × 24 / 200) = 1 - exp(-4.8) ≈ 0.9918 → low
        conc = _make_conc(pigment_pct=25.0, rec_ldr=4.0)
        shot = _make_shot(residence_s=40.0, l_over_d=24.0)
        report = compute_color_ratio(conc, shot)
        assert report.let_down_ratio_pct == pytest.approx(4.0, abs=1e-9)
        assert report.color_streaking_risk == "low"


# ---------------------------------------------------------------------------
# T4 — Very dilute let-down → high streaking risk
# ---------------------------------------------------------------------------

class TestVeryDiluteLDR:
    def setup_method(self):
        # target 0.08%, MB at 40% → LDR = 0.2% < 0.5% threshold
        self.report = compute_color_ratio(
            _make_conc(pigment_pct=40.0),
            _make_shot(target_pct=0.08, residence_s=30.0),
        )

    def test_ldr_value(self):
        assert abs(self.report.let_down_ratio_pct - 0.2) < 1e-9

    def test_high_risk(self):
        assert self.report.color_streaking_risk == "high"

    def test_warning_mentions_critically_low(self):
        combined = " ".join(self.report.warnings).lower()
        assert "critically low" in combined or "low" in combined

    def test_warning_mentions_threshold(self):
        # Should mention the 0.5% threshold or the value
        combined = " ".join(self.report.warnings)
        assert "0.5" in combined or "0.2" in combined


# ---------------------------------------------------------------------------
# T5 — Heavy let-down → cost waste warning + high risk
# ---------------------------------------------------------------------------

class TestHeavyLDR:
    def setup_method(self):
        # target 4%, MB at 40% → LDR = 10% > 8% → high risk + cost-waste warning
        self.report = compute_color_ratio(
            _make_conc(pigment_pct=40.0, rec_ldr=2.5),
            _make_shot(target_pct=4.0, residence_s=30.0),
        )

    def test_ldr_value(self):
        assert abs(self.report.let_down_ratio_pct - 10.0) < 1e-9

    def test_high_risk(self):
        assert self.report.color_streaking_risk == "high"

    def test_cost_waste_warning_present(self):
        combined = " ".join(self.report.warnings).lower()
        assert "cost" in combined or "waste" in combined or "mechanical" in combined

    def test_masterbatch_per_shot(self):
        # 100g shot × 10% = 10g
        assert abs(self.report.masterbatch_per_shot_g - 10.0) < 1e-9


# ---------------------------------------------------------------------------
# T6 — Short residence + low L/D → low mixing index → moderate risk
# ---------------------------------------------------------------------------

class TestShortResidenceLowLD:
    def setup_method(self):
        # residence 3s, L/D 10 → mixing_index = 1 - exp(-3×10/200) = 1 - exp(-0.15) ≈ 0.139
        # LDR = 1/40 × 100 = 2.5% (in SPI range) but mixing_index < 0.80 → moderate
        self.report = compute_color_ratio(
            _make_conc(),
            _make_shot(residence_s=3.0, l_over_d=10.0),
        )

    def test_mixing_index_low(self):
        expected = 1.0 - math.exp(-3.0 * 10.0 / 200.0)
        # report rounds to 6 dp; tolerance is 5e-7
        assert abs(self.report.mixing_index_estimate - expected) < 5e-7
        assert self.report.mixing_index_estimate < MIXING_INDEX_ADEQUATE

    def test_moderate_streaking_risk(self):
        assert self.report.color_streaking_risk == "moderate"

    def test_mixing_warning_present(self):
        combined = " ".join(self.report.warnings).lower()
        assert "mixing" in combined

    def test_ldr_still_correct(self):
        assert abs(self.report.let_down_ratio_pct - 2.5) < 1e-9


# ---------------------------------------------------------------------------
# T7 — LDR just above SPI 5% → moderate risk + SPI warning
# ---------------------------------------------------------------------------

class TestSlightlyOverSpiMax:
    def setup_method(self):
        # target 1.5%, MB at 25% → LDR = 6%
        self.report = compute_color_ratio(
            _make_conc(pigment_pct=25.0, rec_ldr=2.0),
            _make_shot(target_pct=1.5, residence_s=30.0),
        )

    def test_ldr_value(self):
        assert abs(self.report.let_down_ratio_pct - 6.0) < 1e-9

    def test_moderate_risk(self):
        # 6% > 5% but < 8% → moderate
        assert self.report.color_streaking_risk == "moderate"

    def test_spi_warning(self):
        combined = " ".join(self.report.warnings)
        assert "5" in combined or "SPI" in combined


# ---------------------------------------------------------------------------
# T8 — LDR just below SPI 1% → moderate risk
# ---------------------------------------------------------------------------

class TestMarginalLowLDR:
    def setup_method(self):
        # target 0.3%, MB 40% → LDR = 0.75% (in 0.5–1% marginal zone)
        self.report = compute_color_ratio(
            _make_conc(pigment_pct=40.0, rec_ldr=2.5),
            _make_shot(target_pct=0.3, residence_s=30.0),
        )

    def test_ldr_value(self):
        assert abs(self.report.let_down_ratio_pct - 0.75) < 1e-9

    def test_moderate_risk(self):
        assert self.report.color_streaking_risk == "moderate"

    def test_spi_minimum_warning(self):
        combined = " ".join(self.report.warnings)
        assert "1" in combined or "minimum" in combined


# ---------------------------------------------------------------------------
# T9 — Carrier resin compatibility warning always emitted
# ---------------------------------------------------------------------------

def test_carrier_resin_warning_always_present():
    report = compute_color_ratio(_make_conc(carrier="LDPE"), _make_shot())
    combined = " ".join(report.warnings)
    assert "LDPE" in combined or "carrier" in combined.lower()


# ---------------------------------------------------------------------------
# T10 — masterbatch_per_kg_natural formula check
# ---------------------------------------------------------------------------

def test_mb_per_kg_natural_formula():
    # LDR = 3% → MB per kg natural = 1000 × 0.03 / 0.97 ≈ 30.928
    conc = _make_conc(pigment_pct=40.0)
    shot = _make_shot(target_pct=1.2, shot_g=50.0)  # LDR = 1.2/40×100 = 3%
    report = compute_color_ratio(conc, shot)
    assert abs(report.let_down_ratio_pct - 3.0) < 1e-9
    expected = 1000.0 * 0.03 / 0.97
    assert abs(report.masterbatch_per_kg_natural - expected) < 1e-4


# ---------------------------------------------------------------------------
# T11 — Validation errors
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_pigment_pct_zero(self):
        with pytest.raises(ValueError):
            ColorConcentrateSpec(
                pigment_loading_in_masterbatch_pct=0.0,
                recommended_let_down_pct=2.5,
                carrier_resin="PP",
                melting_temp_C=220.0,
            )

    def test_pigment_pct_100(self):
        with pytest.raises(ValueError):
            ColorConcentrateSpec(
                pigment_loading_in_masterbatch_pct=100.0,
                recommended_let_down_pct=2.5,
                carrier_resin="PP",
                melting_temp_C=220.0,
            )

    def test_shot_weight_zero(self):
        with pytest.raises(ValueError):
            ShotSpec(
                shot_weight_g=0.0,
                target_pigment_loading_pct=1.0,
                barrel_residence_time_s=30.0,
            )

    def test_residence_zero(self):
        with pytest.raises(ValueError):
            ShotSpec(
                shot_weight_g=100.0,
                target_pigment_loading_pct=1.0,
                barrel_residence_time_s=0.0,
            )

    def test_negative_melting_temp(self):
        with pytest.raises(ValueError):
            ColorConcentrateSpec(
                pigment_loading_in_masterbatch_pct=40.0,
                recommended_let_down_pct=2.5,
                carrier_resin="PP",
                melting_temp_C=-10.0,
            )


# ---------------------------------------------------------------------------
# T12 — Supplier LDR deviation warning
# ---------------------------------------------------------------------------

def test_supplier_ldr_deviation_warning():
    # computed LDR = 2.5%, supplier says 10% → >50% deviation → warning
    conc = _make_conc(pigment_pct=40.0, rec_ldr=10.0)
    report = compute_color_ratio(conc, _make_shot())
    combined = " ".join(report.warnings)
    assert "deviate" in combined.lower() or "supplier" in combined.lower() or "50" in combined


# ---------------------------------------------------------------------------
# T13 — Different shot weights scale MB linearly
# ---------------------------------------------------------------------------

def test_mb_scales_linearly_with_shot_weight():
    conc = _make_conc(pigment_pct=40.0)
    report_100 = compute_color_ratio(conc, _make_shot(shot_g=100.0))
    report_200 = compute_color_ratio(conc, _make_shot(shot_g=200.0))
    assert abs(report_200.masterbatch_per_shot_g - 2.0 * report_100.masterbatch_per_shot_g) < 1e-9
    # LDR should be identical (shot weight doesn't affect LDR)
    assert abs(report_200.let_down_ratio_pct - report_100.let_down_ratio_pct) < 1e-9


# ---------------------------------------------------------------------------
# T14 — Higher MB pigment loading → lower LDR
# ---------------------------------------------------------------------------

def test_higher_mb_loading_lower_ldr():
    shot = _make_shot(target_pct=1.0)
    conc_20 = _make_conc(pigment_pct=20.0)
    conc_50 = _make_conc(pigment_pct=50.0)
    report_20 = compute_color_ratio(conc_20, shot)
    report_50 = compute_color_ratio(conc_50, shot)
    # LDR at 20% = 5%; LDR at 50% = 2%
    assert abs(report_20.let_down_ratio_pct - 5.0) < 1e-9
    assert abs(report_50.let_down_ratio_pct - 2.0) < 1e-9
    assert report_50.let_down_ratio_pct < report_20.let_down_ratio_pct


# ---------------------------------------------------------------------------
# T15 — Very good mixing (high L/D + long residence) → mixing_index close to 1
# ---------------------------------------------------------------------------

def test_high_ld_long_residence_mixing_near_1():
    shot = _make_shot(residence_s=120.0, l_over_d=30.0)
    report = compute_color_ratio(_make_conc(), shot)
    # 1 - exp(-120*30/200) = 1 - exp(-18) ≈ 0.9999999848
    assert report.mixing_index_estimate > 0.99


# ---------------------------------------------------------------------------
# T16 — Poor mixing (very short residence) generates poor mixing warning
# ---------------------------------------------------------------------------

def test_poor_mixing_warning():
    # residence 1s, L/D 5 → mixing_index = 1 - exp(-5/200) ≈ 0.0247 → very poor
    shot = _make_shot(residence_s=1.0, l_over_d=5.0)
    report = compute_color_ratio(_make_conc(), shot)
    assert report.mixing_index_estimate < MIXING_INDEX_POOR
    combined = " ".join(report.warnings).lower()
    assert "poor" in combined or "back-pressure" in combined or "mixing" in combined
