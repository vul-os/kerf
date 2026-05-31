"""
Tests for composite positional tolerance evaluation (ASME Y14.5-2018 §10.5).

Covers:
  - 4-hole pattern at nominal: pass both tiers
  - Single hole off by small amount: pass both tiers (within tolerances)
  - Single hole off by 0.3 mm: violates FRTZF (t=0.2) but passes PLTZF (t=1.0)
  - Entire pattern shifted 0.5 mm: violates PLTZF, passes FRTZF (relative OK)
  - MMC bonus calculation
  - Edge cases: spec validation, single feature, zero centroid shift
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.gdt.composite_position import (
    FeaturePoint,
    CompositePositionSpec,
    CompositePositionReport,
    check_composite_position,
    _dist3,
    _centroid,
    _mmc_bonus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_4hole_pattern(
    nominal_shift: tuple[float, float, float] = (0.0, 0.0, 0.0),
    measured_offsets: list[tuple[float, float, float]] | None = None,
    feature_size_mm: float = 10.0,
    mmc_size_mm: float | None = None,
) -> list[FeaturePoint]:
    """
    Create a 4-hole bolt-circle pattern at corners of a 20×20 mm square,
    centred at origin, with optional per-feature measured offsets.
    """
    nominals = [
        (10.0, 10.0, 0.0),
        (-10.0, 10.0, 0.0),
        (-10.0, -10.0, 0.0),
        (10.0, -10.0, 0.0),
    ]
    if measured_offsets is None:
        measured_offsets = [(0.0, 0.0, 0.0)] * 4
    features = []
    for i, (nx, ny, nz) in enumerate(nominals):
        mx, my, mz = measured_offsets[i]
        # Apply nominal_shift to simulated "whole pattern moved"
        meas = (
            nx + nominal_shift[0] + mx,
            ny + nominal_shift[1] + my,
            nz + nominal_shift[2] + mz,
        )
        features.append(
            FeaturePoint(
                feature_id=f"H{i + 1}",
                nominal_xyz_mm=(nx, ny, nz),
                measured_xyz_mm=meas,
                feature_size_mm=feature_size_mm,
                mmc_size_mm=mmc_size_mm,
            )
        )
    return features


# ---------------------------------------------------------------------------
# 1. FeaturePoint dataclass
# ---------------------------------------------------------------------------

class TestFeaturePoint:
    def test_basic_construction(self):
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(10.0, 5.0, 0.0),
            measured_xyz_mm=(10.05, 5.0, 0.0),
            feature_size_mm=8.0,
        )
        assert fp.feature_id == "H1"
        assert fp.nominal_xyz_mm == (10.0, 5.0, 0.0)
        assert fp.measured_xyz_mm == (10.05, 5.0, 0.0)
        assert fp.feature_size_mm == 8.0
        assert fp.mmc_size_mm is None

    def test_with_mmc_size(self):
        fp = FeaturePoint(
            feature_id="H2",
            nominal_xyz_mm=(0.0, 0.0, 0.0),
            measured_xyz_mm=(0.0, 0.0, 0.0),
            feature_size_mm=10.2,
            mmc_size_mm=10.0,
        )
        assert fp.mmc_size_mm == 10.0

    def test_empty_feature_id_raises(self):
        with pytest.raises(ValueError, match="feature_id must not be empty"):
            FeaturePoint(
                feature_id="   ",
                nominal_xyz_mm=(0.0, 0.0, 0.0),
                measured_xyz_mm=(0.0, 0.0, 0.0),
                feature_size_mm=5.0,
            )

    def test_negative_feature_size_raises(self):
        with pytest.raises(ValueError, match="feature_size_mm must be"):
            FeaturePoint(
                feature_id="H1",
                nominal_xyz_mm=(0.0, 0.0, 0.0),
                measured_xyz_mm=(0.0, 0.0, 0.0),
                feature_size_mm=-1.0,
            )

    def test_wrong_xyz_length_raises(self):
        with pytest.raises(ValueError, match="3 elements"):
            FeaturePoint(
                feature_id="H1",
                nominal_xyz_mm=(0.0, 0.0),  # type: ignore[arg-type]
                measured_xyz_mm=(0.0, 0.0, 0.0),
                feature_size_mm=5.0,
            )

    def test_to_dict_round_trip(self):
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(1.0, 2.0, 3.0),
            measured_xyz_mm=(1.1, 2.0, 3.0),
            feature_size_mm=9.8,
            mmc_size_mm=9.5,
        )
        d = fp.to_dict()
        fp2 = FeaturePoint.from_dict(d)
        assert fp2.feature_id == fp.feature_id
        assert fp2.nominal_xyz_mm == fp.nominal_xyz_mm
        assert fp2.measured_xyz_mm == fp.measured_xyz_mm
        assert fp2.feature_size_mm == fp.feature_size_mm
        assert fp2.mmc_size_mm == fp.mmc_size_mm


# ---------------------------------------------------------------------------
# 2. CompositePositionSpec validation
# ---------------------------------------------------------------------------

class TestCompositePositionSpec:
    def test_frtzf_greater_than_pltzf_raises(self):
        features = _make_4hole_pattern()
        with pytest.raises(ValueError, match="lower_frtzf_tolerance_mm"):
            CompositePositionSpec(
                features=features,
                upper_pltzf_tolerance_mm=0.2,
                lower_frtzf_tolerance_mm=0.5,  # violates §10.5.1 Note 2
                datums_pltzf=["A", "B", "C"],
                datums_frtzf=["A"],
            )

    def test_zero_pltzf_tolerance_raises(self):
        features = _make_4hole_pattern()
        with pytest.raises(ValueError, match="upper_pltzf_tolerance_mm must be > 0"):
            CompositePositionSpec(
                features=features,
                upper_pltzf_tolerance_mm=0.0,
                lower_frtzf_tolerance_mm=0.1,
            )

    def test_empty_features_raises(self):
        with pytest.raises(ValueError, match="features list must contain"):
            CompositePositionSpec(
                features=[],
                upper_pltzf_tolerance_mm=1.0,
                lower_frtzf_tolerance_mm=0.2,
            )

    def test_to_dict_round_trip(self):
        features = _make_4hole_pattern()
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
            datums_pltzf=["A", "B", "C"],
            datums_frtzf=["A"],
            mmc_modifier=False,
        )
        d = spec.to_dict()
        spec2 = CompositePositionSpec.from_dict(d)
        assert spec2.upper_pltzf_tolerance_mm == spec.upper_pltzf_tolerance_mm
        assert spec2.lower_frtzf_tolerance_mm == spec.lower_frtzf_tolerance_mm
        assert spec2.datums_pltzf == spec.datums_pltzf
        assert spec2.datums_frtzf == spec.datums_frtzf
        assert len(spec2.features) == len(spec.features)


# ---------------------------------------------------------------------------
# 3. Core scenario: 4-hole pattern at nominal → pass both tiers
# ---------------------------------------------------------------------------

class TestPassBothTiers:
    def test_nominal_4hole_passes_pltzf(self):
        """All 4 holes at nominal: PLTZF deviation = 0 → pass."""
        features = _make_4hole_pattern()
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
            datums_pltzf=["A", "B", "C"],
            datums_frtzf=["A"],
        )
        report = check_composite_position(spec)
        assert report.overall_pass
        assert report.pltzf_violations == []
        assert report.frtzf_violations == []

    def test_nominal_4hole_zero_deviations(self):
        features = _make_4hole_pattern()
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.max_pltzf_deviation_mm == pytest.approx(0.0, abs=1e-9)
        assert report.max_frtzf_deviation_mm == pytest.approx(0.0, abs=1e-9)
        assert report.pltzf_centroid_shift_mm == pytest.approx(0.0, abs=1e-9)

    def test_tiny_offsets_both_pass(self):
        """Each hole 0.05 mm off: both PLTZF(1.0) and FRTZF(0.2) pass."""
        offsets = [(0.05, 0.0, 0.0), (-0.05, 0.0, 0.0),
                   (0.0, 0.05, 0.0), (0.0, -0.05, 0.0)]
        features = _make_4hole_pattern(measured_offsets=offsets)
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.overall_pass
        assert report.max_pltzf_deviation_mm == pytest.approx(2 * 0.05, abs=1e-6)


# ---------------------------------------------------------------------------
# 4. One hole off by 0.3 mm: violates FRTZF (0.2) but passes PLTZF (1.0)
# ---------------------------------------------------------------------------

class TestOneholeFrtzfViolation:
    def test_single_hole_030mm_off(self):
        """
        H1 displaced 0.3 mm in X.
        PLTZF: diametral dev = 2×0.3 = 0.6 mm ≤ 1.0 mm → pass
        FRTZF after centroid shift: centroid shifts by 0.3/4 = 0.075 mm;
          H1 residual deviation = 2×(0.3 − 0.075) = 2×0.225 = 0.45 mm > 0.2 → FAIL
        """
        offsets = [(0.3, 0.0, 0.0), (0.0, 0.0, 0.0),
                   (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
        features = _make_4hole_pattern(measured_offsets=offsets)
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert not report.overall_pass
        assert report.pltzf_violations == []          # PLTZF passes (0.6 < 1.0)
        assert len(report.frtzf_violations) > 0       # FRTZF fails
        frtzf_ids = [fid for fid, _ in report.frtzf_violations]
        assert "H1" in frtzf_ids

    def test_pltzf_deviation_value_correct(self):
        """Verify the PLTZF max deviation is 2×0.3 = 0.6 mm."""
        offsets = [(0.3, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3
        features = _make_4hole_pattern(measured_offsets=offsets)
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.max_pltzf_deviation_mm == pytest.approx(0.6, abs=1e-6)

    def test_frtzf_centroid_shift_correct(self):
        """Centroid shifts by 0.3/4 = 0.075 mm in X when only H1 is off by 0.3."""
        offsets = [(0.3, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3
        features = _make_4hole_pattern(measured_offsets=offsets)
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.pltzf_centroid_shift_mm == pytest.approx(0.075, abs=1e-6)


# ---------------------------------------------------------------------------
# 5. Entire pattern shifted 0.5 mm: violates PLTZF but passes FRTZF
# ---------------------------------------------------------------------------

class TestWholePatterShifted:
    def test_pattern_shifted_05mm_fails_pltzf(self):
        """
        Entire pattern shifts 0.5 mm in X (rigid translation).
        PLTZF: each hole deviates 2×0.5 = 1.0 mm from nominal.
          With tolerance = 0.8 mm → 1.0 > 0.8 → all 4 violate PLTZF.
        FRTZF: centroid removed → residual dev = 0 for every hole → pass.
        """
        features = _make_4hole_pattern(nominal_shift=(0.5, 0.0, 0.0))
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=0.8,   # 0.8 < 1.0 diametral → PLTZF fails
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert not report.overall_pass
        assert len(report.pltzf_violations) == 4   # all holes fail PLTZF
        assert report.frtzf_violations == []        # FRTZF passes (relative OK)

    def test_pattern_shifted_frtzf_devs_zero(self):
        """After centroid removal a rigid shift leaves zero FRTZF deviation."""
        features = _make_4hole_pattern(nominal_shift=(0.5, 0.3, 0.0))
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=2.0,   # large enough to pass PLTZF too
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.overall_pass
        assert report.max_frtzf_deviation_mm == pytest.approx(0.0, abs=1e-9)

    def test_centroid_shift_reported(self):
        """pltzf_centroid_shift_mm should equal the rigid shift distance."""
        shift = (0.5, 0.0, 0.0)
        features = _make_4hole_pattern(nominal_shift=shift)
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=2.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.pltzf_centroid_shift_mm == pytest.approx(0.5, abs=1e-9)

    def test_pattern_shifted_tight_pltzf_passes_with_larger_tol(self):
        """Same rigid shift but with PLTZF tolerance large enough → overall pass."""
        features = _make_4hole_pattern(nominal_shift=(0.2, 0.0, 0.0))
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,   # 2×0.2=0.4 < 1.0 → pass
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.overall_pass
        assert report.pltzf_violations == []
        assert report.frtzf_violations == []


# ---------------------------------------------------------------------------
# 6. MMC bonus calculation
# ---------------------------------------------------------------------------

class TestMMCBonus:
    def test_mmc_bonus_zero_when_at_mmc(self):
        """feature_size == mmc_size → bonus = 0."""
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(0.0, 0.0, 0.0),
            measured_xyz_mm=(0.0, 0.0, 0.0),
            feature_size_mm=10.0,
            mmc_size_mm=10.0,
        )
        assert _mmc_bonus(fp) == pytest.approx(0.0)

    def test_mmc_bonus_positive_when_larger(self):
        """Hole measured 0.3 mm larger than MMC → bonus = 0.3 mm."""
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(0.0, 0.0, 0.0),
            measured_xyz_mm=(0.4, 0.0, 0.0),
            feature_size_mm=10.3,
            mmc_size_mm=10.0,
        )
        assert _mmc_bonus(fp) == pytest.approx(0.3, abs=1e-9)

    def test_mmc_bonus_none_means_zero(self):
        """No mmc_size_mm provided → bonus = 0 regardless of feature_size."""
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(0.0, 0.0, 0.0),
            measured_xyz_mm=(0.0, 0.0, 0.0),
            feature_size_mm=12.0,
            mmc_size_mm=None,
        )
        assert _mmc_bonus(fp) == 0.0

    def test_mmc_bonus_applied_allows_larger_deviation(self):
        """
        Without MMC bonus: 0.3 mm shift → diametral dev = 0.6 mm > 0.4 → PLTZF fail.
        With MMC bonus of 0.3 mm: effective tol = 0.4 + 0.3 = 0.7 mm > 0.6 → PLTZF pass.
        """
        offsets = [(0.3, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3
        # Without bonus
        features_no_bonus = _make_4hole_pattern(
            measured_offsets=offsets,
            feature_size_mm=10.3,
            mmc_size_mm=10.0,
        )
        spec_no_bonus = CompositePositionSpec(
            features=features_no_bonus,
            upper_pltzf_tolerance_mm=0.4,
            lower_frtzf_tolerance_mm=0.2,
            mmc_modifier=False,
        )
        report_no_bonus = check_composite_position(spec_no_bonus)
        assert len(report_no_bonus.pltzf_violations) > 0  # H1 fails without bonus

        # With bonus (same features, same tolerances)
        features_bonus = _make_4hole_pattern(
            measured_offsets=offsets,
            feature_size_mm=10.3,
            mmc_size_mm=10.0,
        )
        spec_bonus = CompositePositionSpec(
            features=features_bonus,
            upper_pltzf_tolerance_mm=0.4,
            lower_frtzf_tolerance_mm=0.2,
            mmc_modifier=True,
        )
        report_bonus = check_composite_position(spec_bonus)
        assert report_bonus.pltzf_violations == []  # H1 passes with bonus

    def test_mmc_bonus_applied_to_frtzf_too(self):
        """MMC bonus also widens the FRTZF tolerance zone."""
        offsets = [(0.3, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3
        # frtzf_dev for H1 ≈ 2×(0.3−0.075) = 0.45 mm
        # Without bonus: 0.45 > 0.2 → FRTZF fails
        # With bonus = 0.3: effective FRTZF tol = 0.2 + 0.3 = 0.5 > 0.45 → FRTZF pass
        features = _make_4hole_pattern(
            measured_offsets=offsets,
            feature_size_mm=10.3,
            mmc_size_mm=10.0,
        )
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
            mmc_modifier=True,
        )
        report = check_composite_position(spec)
        assert report.frtzf_violations == []

    def test_mmc_bonus_clamps_at_zero_not_negative(self):
        """feature_size < mmc_size → bonus clamped to 0 (can't have negative bonus)."""
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(0.0, 0.0, 0.0),
            measured_xyz_mm=(0.0, 0.0, 0.0),
            feature_size_mm=9.8,   # smaller than MMC (unlikely for a hole, but tested)
            mmc_size_mm=10.0,
        )
        assert _mmc_bonus(fp) == 0.0


# ---------------------------------------------------------------------------
# 7. Single feature (degenerate pattern)
# ---------------------------------------------------------------------------

class TestSingleFeature:
    def test_single_feature_at_nominal(self):
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(5.0, 5.0, 0.0),
            measured_xyz_mm=(5.0, 5.0, 0.0),
            feature_size_mm=8.0,
        )
        spec = CompositePositionSpec(
            features=[fp],
            upper_pltzf_tolerance_mm=0.5,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert report.overall_pass
        assert report.max_pltzf_deviation_mm == pytest.approx(0.0, abs=1e-9)
        assert report.max_frtzf_deviation_mm == pytest.approx(0.0, abs=1e-9)

    def test_single_feature_off_violates_pltzf(self):
        fp = FeaturePoint(
            feature_id="H1",
            nominal_xyz_mm=(5.0, 5.0, 0.0),
            measured_xyz_mm=(5.6, 5.0, 0.0),   # 0.6 mm off → diametral = 1.2 > 1.0
            feature_size_mm=8.0,
        )
        spec = CompositePositionSpec(
            features=[fp],
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.5,
        )
        report = check_composite_position(spec)
        assert not report.overall_pass
        assert len(report.pltzf_violations) == 1
        # FRTZF: single feature → centroid = itself → deviation = 0
        assert report.frtzf_violations == []


# ---------------------------------------------------------------------------
# 8. Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_to_dict_keys(self):
        features = _make_4hole_pattern()
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        d = report.to_dict()
        assert "pltzf_violations" in d
        assert "frtzf_violations" in d
        assert "overall_pass" in d
        assert "max_pltzf_deviation_mm" in d
        assert "max_frtzf_deviation_mm" in d
        assert "pltzf_centroid_shift_mm" in d
        assert "honest_caveat" in d

    def test_honest_caveat_present(self):
        features = _make_4hole_pattern()
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        assert "positional" in report.honest_caveat.lower()
        assert "FRTZF" in report.honest_caveat or "frtzf" in report.honest_caveat.lower()

    def test_violation_tuples_contain_feature_id_and_deviation(self):
        """Each violation entry is (feature_id: str, deviation: float)."""
        offsets = [(0.6, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3  # H1 off by 0.6mm
        features = _make_4hole_pattern(measured_offsets=offsets)
        spec = CompositePositionSpec(
            features=features,
            upper_pltzf_tolerance_mm=1.0,   # passes PLTZF (diametral = 1.2 > 1.0 → WAIT 2×0.6=1.2>1.0)
            lower_frtzf_tolerance_mm=0.2,
        )
        report = check_composite_position(spec)
        # PLTZF: 2×0.6 = 1.2 > 1.0 → H1 fails PLTZF
        pltzf_ids = [v[0] for v in report.pltzf_violations]
        assert "H1" in pltzf_ids
        for fid, dev in report.pltzf_violations:
            assert isinstance(fid, str)
            assert isinstance(dev, float)
            assert dev > 0


# ---------------------------------------------------------------------------
# 9. Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_dist3_known_values(self):
        assert _dist3((0, 0, 0), (3, 4, 0)) == pytest.approx(5.0)
        assert _dist3((1, 1, 1), (1, 1, 1)) == pytest.approx(0.0)
        assert _dist3((0, 0, 0), (1, 1, 1)) == pytest.approx(math.sqrt(3))

    def test_centroid_symmetric_pattern(self):
        pts = [(1.0, 1.0, 0.0), (-1.0, 1.0, 0.0),
               (-1.0, -1.0, 0.0), (1.0, -1.0, 0.0)]
        c = _centroid(pts)
        assert c == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)

    def test_centroid_offset_pattern(self):
        pts = [(2.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
        c = _centroid(pts)
        assert c == pytest.approx((3.0, 0.0, 0.0), abs=1e-9)
