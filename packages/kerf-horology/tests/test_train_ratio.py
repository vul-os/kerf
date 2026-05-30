"""Tests for kerf_horology.train_ratio — gear-train ratio calculator.

Reference: George Daniels, *Watchmaking* (1981) §6.1; De Carle (1995).

Test oracles
------------
All numeric oracles are derived from first principles (no measurement):

  BPH = barrel_RPH × total_ratio × escape_teeth × 2

  where:
    total_ratio = Π (wheel_i.teeth / following_pinion_i.leaves)

The task spec cites a 4-stage ETA 2824-2-like train (barrel 80t, center 80/12,
third 75/10, fourth 70/8, escape 15/7).  That specific train produces:

  total_ratio = (80/12) × (80/10) × (75/8) × (70/7) = 5000
  BPH at 1/8 RPH = 0.125 × 5000 × 15 × 2 = 18 750 BPH

The task oracle of "≈3650" and "28800 BPH at 1/8 RPH" cannot be satisfied
simultaneously with integer tooth counts — a discrepancy noted in inline
comments.  Tests are written against the PHYSICALLY CORRECT values.
"""

from __future__ import annotations

import math
import pytest

from kerf_horology.train_ratio import (
    Wheel,
    StageRatio,
    TrainResult,
    compute_train_ratios,
    compute_beat_rate,
    design_train_for_beat_rate,
    power_reserve_estimate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _eta_like_wheels_4stage():
    """4-stage ETA 2824-2-like train (escape pinion = 7).

    Stages:
        barrel(80)→center_pinion(12) = 80/12 = 6.6667
        center_wheel(80)→third_pinion(10) = 80/10 = 8
        third_wheel(75)→fourth_pinion(8) = 75/8 = 9.375
        fourth_wheel(70)→escape_pinion(7) = 70/7 = 10

    Total ratio = 6.6667 × 8 × 9.375 × 10 = 5000
    Beat rate at 1/8 RPH = 0.125 × 5000 × 15 × 2 = 18 750 BPH
    """
    return [
        Wheel(name="barrel",       teeth=80, pinion_leaves=None),
        Wheel(name="center_wheel", teeth=80, pinion_leaves=12),
        Wheel(name="third_wheel",  teeth=75, pinion_leaves=10),
        Wheel(name="fourth_wheel", teeth=70, pinion_leaves=8),
        Wheel(name="escape_wheel", teeth=15, pinion_leaves=7),
    ]


# ---------------------------------------------------------------------------
# 1. Wheel dataclass validation
# ---------------------------------------------------------------------------

class TestWheel:
    def test_basic_construction(self):
        w = Wheel("center_wheel", teeth=80, pinion_leaves=12)
        assert w.name == "center_wheel"
        assert w.teeth == 80
        assert w.pinion_leaves == 12

    def test_no_pinion_barrel(self):
        w = Wheel("barrel", teeth=80, pinion_leaves=None)
        assert w.pinion_leaves is None

    def test_zero_teeth_raises(self):
        with pytest.raises(ValueError, match="teeth must be"):
            Wheel("bad", teeth=0)

    def test_negative_pinion_raises(self):
        with pytest.raises(ValueError, match="pinion_leaves must be"):
            Wheel("bad", teeth=80, pinion_leaves=0)


# ---------------------------------------------------------------------------
# 2. compute_train_ratios — stage arithmetic
# ---------------------------------------------------------------------------

class TestComputeTrainRatios:
    def test_stage_count(self, _wheels=None):
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        # 4 wheels with pinion_leaves → 4 stages
        assert len(result.stages) == 4

    def test_stage_ratios_arithmetic(self):
        """Each stage ratio = driving_teeth / driven_pinion_leaves."""
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        expected_ratios = [80 / 12, 80 / 10, 75 / 8, 70 / 7]
        for stage, expected in zip(result.stages, expected_ratios):
            assert abs(stage.ratio - expected) < 1e-9, (
                f"Stage {stage.driving_wheel}→{stage.driven_pinion}: "
                f"expected {expected:.6f}, got {stage.ratio:.6f}"
            )

    def test_total_ratio_product(self):
        """Total ratio = product of stage ratios (exact)."""
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        product = math.prod(s.ratio for s in result.stages)
        assert abs(result.total_ratio - product) < 1e-9

    def test_eta_like_total_ratio(self):
        """4-stage ETA-like train: total ratio = (80/12)*(80/10)*(75/8)*(70/7) = 5000."""
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        assert abs(result.total_ratio - 5000.0) < 1e-9, (
            f"Expected 5000.0, got {result.total_ratio}"
        )

    def test_arbor_speeds_barrel(self):
        """Barrel arbor speed equals the input barrel_rev_per_hr."""
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=0.125)
        assert abs(result.arbor_speeds_rev_per_hr["barrel"] - 0.125) < 1e-12

    def test_arbor_speeds_escape_wheel(self):
        """Escape wheel speed = barrel_speed × total_ratio."""
        wheels = _eta_like_wheels_4stage()
        barrel_rph = 1 / 8
        result = compute_train_ratios(wheels, barrel_rev_per_hr=barrel_rph)
        expected_escape_speed = barrel_rph * result.total_ratio
        got = result.arbor_speeds_rev_per_hr["escape_wheel"]
        assert abs(got - expected_escape_speed) < 1e-9

    def test_beat_rate_eta_like(self):
        """ETA-like train at 1/8 RPH: beat rate = 5000 * 0.125 * 15 * 2 = 18 750 BPH."""
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        assert abs(result.beat_rate_bph - 18750.0) < 1e-6

    def test_is_valid_flag(self):
        """Valid ETA-like train: is_valid should be True (no errors)."""
        wheels = _eta_like_wheels_4stage()
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        assert result.is_valid, f"Unexpected errors: {result.validation_errors}"

    def test_needs_at_least_2_wheels(self):
        with pytest.raises(ValueError, match="at least 2"):
            compute_train_ratios([Wheel("only", 15, None)])

    def test_no_pinion_escape_wheel_passthrough(self):
        """Escape wheel with pinion_leaves=None: its speed equals the driving wheel's speed."""
        wheels = [
            Wheel("barrel",       80, None),
            Wheel("center_wheel", 80, 10),
            Wheel("escape_wheel", 15, None),  # no pinion — passthrough
        ]
        result = compute_train_ratios(wheels, barrel_rev_per_hr=0.1)
        # Only 1 stage (barrel→center); escape inherits center speed
        assert len(result.stages) == 1
        assert abs(result.stages[0].ratio - 80 / 10) < 1e-9
        center_speed = 0.1 * (80 / 10)
        assert abs(result.arbor_speeds_rev_per_hr["escape_wheel"] - center_speed) < 1e-12


# ---------------------------------------------------------------------------
# 3. compute_beat_rate — closed-form formula
# ---------------------------------------------------------------------------

class TestComputeBeatRate:
    def test_28800_bph_at_1_8_rph(self):
        """BPH = 1/8 × 7680 × 15 × 2 = 28 800 (exact)."""
        bph = compute_beat_rate(
            escape_wheel_teeth=15,
            train_ratio_to_escape=7680,
            mainspring_revolutions_per_hour=1 / 8,
        )
        assert abs(bph - 28800.0) < 1e-6

    def test_18000_bph_low_speed(self):
        """18 000 BPH vintage movement: ratio=4800 at 1/8 RPH."""
        bph = compute_beat_rate(15, 4800, 1 / 8)
        assert abs(bph - 18000.0) < 1e-6

    def test_36000_bph_high_beat(self):
        """36 000 BPH high-beat: ratio=9600 at 1/8 RPH."""
        bph = compute_beat_rate(15, 9600, 1 / 8)
        assert abs(bph - 36000.0) < 1e-6

    def test_formula_linearity_with_ratio(self):
        """Doubling the train ratio doubles the BPH."""
        bph1 = compute_beat_rate(15, 4000, 0.15)
        bph2 = compute_beat_rate(15, 8000, 0.15)
        assert abs(bph2 - 2 * bph1) < 1e-9

    def test_invalid_teeth_raises(self):
        with pytest.raises(ValueError, match="escape_wheel_teeth"):
            compute_beat_rate(0, 7680, 1 / 8)

    def test_invalid_ratio_raises(self):
        with pytest.raises(ValueError, match="train_ratio_to_escape"):
            compute_beat_rate(15, 0, 1 / 8)

    def test_invalid_barrel_speed_raises(self):
        with pytest.raises(ValueError, match="mainspring_revolutions_per_hour"):
            compute_beat_rate(15, 7680, 0)


# ---------------------------------------------------------------------------
# 4. design_train_for_beat_rate — inverse design
# ---------------------------------------------------------------------------

class TestDesignTrainForBeatRate:
    def _check_design(self, target_bph: float, tol: float = 0.05) -> None:
        wheels = design_train_for_beat_rate(target_bph, mainspring_rev_per_hr=1 / 8)
        result = compute_train_ratios(wheels, barrel_rev_per_hr=1 / 8)
        deviation = abs(result.beat_rate_bph - target_bph) / target_bph
        assert deviation <= tol, (
            f"Target {target_bph} BPH: achieved {result.beat_rate_bph:.0f} BPH, "
            f"deviation {deviation*100:.1f}% > {tol*100}%"
        )
        assert result.is_valid, f"Design for {target_bph} has errors: {result.validation_errors}"
        # Must return at least barrel + escape_wheel = 2 wheels
        assert len(wheels) >= 2

    def test_design_18000_bph(self):
        """18 000 BPH (vintage): design_train returns valid train within 5%."""
        self._check_design(18000.0)

    def test_design_21600_bph(self):
        """21 600 BPH: design_train returns valid train within 5%."""
        self._check_design(21600.0)

    def test_design_28800_bph(self):
        """28 800 BPH (ETA 2824-2 rate): design_train returns valid train within 5%."""
        self._check_design(28800.0)

    def test_design_36000_bph_higher_ratio(self):
        """36 000 BPH high-beat: returned train must have higher ratio than 28 800 BPH design."""
        w28 = design_train_for_beat_rate(28800, mainspring_rev_per_hr=1 / 8)
        w36 = design_train_for_beat_rate(36000, mainspring_rev_per_hr=1 / 8)
        r28 = compute_train_ratios(w28, barrel_rev_per_hr=1 / 8)
        r36 = compute_train_ratios(w36, barrel_rev_per_hr=1 / 8)
        assert r36.total_ratio > r28.total_ratio, (
            f"36000 BPH ratio {r36.total_ratio:.0f} should be > 28800 BPH ratio {r28.total_ratio:.0f}"
        )
        # 36000 design also within 5%
        deviation = abs(r36.beat_rate_bph - 36000) / 36000
        assert deviation <= 0.05, (
            f"36000 BPH design achieved {r36.beat_rate_bph:.0f} BPH ({deviation*100:.1f}% off)"
        )

    def test_design_barrel_has_no_pinion(self):
        """The first wheel in a designed train (barrel) must have pinion_leaves=None."""
        wheels = design_train_for_beat_rate(28800, mainspring_rev_per_hr=1 / 8)
        assert wheels[0].pinion_leaves is None, "Barrel must not have a pinion."

    def test_design_escape_wheel_has_pinion(self):
        """The escape wheel in a designed train must have a pinion (driven by last wheel)."""
        wheels = design_train_for_beat_rate(28800, mainspring_rev_per_hr=1 / 8)
        assert wheels[-1].name == "escape_wheel"
        assert wheels[-1].pinion_leaves is not None, (
            "Escape wheel must have pinion_leaves set by design function."
        )

    def test_design_pinion_leaves_in_range(self):
        """All designed pinion leaves must be in the practical Daniels range [6, 12]."""
        wheels = design_train_for_beat_rate(28800, mainspring_rev_per_hr=1 / 8)
        for w in wheels:
            if w.pinion_leaves is not None:
                assert 6 <= w.pinion_leaves <= 12, (
                    f"Pinion leaves {w.pinion_leaves} for '{w.name}' outside [6, 12]."
                )

    def test_design_invalid_bph_raises(self):
        with pytest.raises(ValueError, match="target_bph"):
            design_train_for_beat_rate(0)

    def test_design_invalid_barrel_speed_raises(self):
        with pytest.raises(ValueError, match="mainspring_rev_per_hr"):
            design_train_for_beat_rate(28800, mainspring_rev_per_hr=0)


# ---------------------------------------------------------------------------
# 5. power_reserve_estimate
# ---------------------------------------------------------------------------

class TestPowerReserveEstimate:
    def test_standard_train_38_to_55_hours(self):
        """Standard ETA-like train with 5% friction → 38–55 hours power reserve.

        Derivation:
            barrel_turns_per_hr = 28800 / (15 × 2 × 7680) = 0.125 RPH
            effective_turns = 6.5 × 0.95 = 6.175
            hours = 6.175 / 0.125 = 49.4 h  → in [38, 55] ✓
        """
        pr = power_reserve_estimate(
            mainspring_torque_Nmm=5.5,
            barrel_turns=6.5,
            escape_wheel_teeth=15,
            total_train_ratio=7680,
            beats_per_hour=28800,
            train_friction_coefficient=0.05,
        )
        assert 38 <= pr <= 55, f"Expected 38–55h, got {pr:.2f}h"

    def test_no_friction_longer_reserve(self):
        """With zero friction the reserve is longer than with 5% friction."""
        pr_0 = power_reserve_estimate(
            mainspring_torque_Nmm=5.5, barrel_turns=6.5,
            total_train_ratio=7680, beats_per_hour=28800,
            train_friction_coefficient=0.0,
        )
        pr_5 = power_reserve_estimate(
            mainspring_torque_Nmm=5.5, barrel_turns=6.5,
            total_train_ratio=7680, beats_per_hour=28800,
            train_friction_coefficient=0.05,
        )
        assert pr_0 > pr_5

    def test_more_barrel_turns_longer_reserve(self):
        """More barrel turns → longer power reserve (proportional)."""
        pr_6 = power_reserve_estimate(5.0, barrel_turns=6.0, total_train_ratio=7680,
                                      beats_per_hour=28800)
        pr_8 = power_reserve_estimate(5.0, barrel_turns=8.0, total_train_ratio=7680,
                                      beats_per_hour=28800)
        assert pr_8 > pr_6

    def test_invalid_torque_raises(self):
        with pytest.raises(ValueError, match="mainspring_torque_Nmm"):
            power_reserve_estimate(mainspring_torque_Nmm=0)

    def test_invalid_barrel_turns_raises(self):
        with pytest.raises(ValueError, match="barrel_turns"):
            power_reserve_estimate(mainspring_torque_Nmm=5.0, barrel_turns=0)

    def test_exact_formula(self):
        """Verify power_reserve_estimate against analytical formula.

        With no friction:
            barrel_turns_per_hr = BPH / (escape_teeth × 2 × ratio)
            reserve = barrel_turns / barrel_turns_per_hr
        """
        turns = 7.0
        ratio = 7680
        bph = 28800
        teeth = 15
        barrel_turns_per_hr = bph / (teeth * 2 * ratio)
        expected = turns / barrel_turns_per_hr  # no friction
        got = power_reserve_estimate(
            mainspring_torque_Nmm=5.0,
            barrel_turns=turns,
            escape_wheel_teeth=teeth,
            total_train_ratio=ratio,
            beats_per_hour=bph,
            train_friction_coefficient=0.0,
        )
        assert abs(got - expected) < 1e-9
