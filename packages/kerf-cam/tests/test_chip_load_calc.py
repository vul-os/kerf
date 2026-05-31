"""
Tests for kerf_cam.chip_load_calc — chip load and chip-thinning calculator.

References
----------
* MH 31e §1136
* Sandvik CoroPlus Technical Guide (2024) — Milling feed-per-tooth
* Stephenson-Agapiou §6 — Radial chip thinning
"""

from __future__ import annotations

import math
import pytest

from kerf_cam.chip_load_calc import (
    ChipLoadReport,
    MillingOpSpec,
    compute_chip_load,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_spec(**kwargs) -> MillingOpSpec:
    """Build a MillingOpSpec with sensible defaults, overridden by kwargs."""
    defaults = dict(
        tool_diameter_mm=12.0,
        num_flutes=2,
        spindle_rpm=5000.0,
        feed_mm_per_min=1000.0,
        radial_engagement_mm=6.0,   # half-width (ae = D/2)
        axial_depth_mm=3.0,
        tool_material="carbide",
        work_material="aluminium",
    )
    defaults.update(kwargs)
    return MillingOpSpec(**defaults)


# ---------------------------------------------------------------------------
# T1 — basic fz formula (the spec-mandated golden value)
#
# D=12, z=2, n=5000, Vf=1000, ae=6 (= D/2)
# fz = 1000 / (5000 × 2) = 0.1 mm/tooth  (exact)
# ---------------------------------------------------------------------------

class TestBasicFzFormula:
    def test_chip_load_exact_golden_value(self):
        """fz = 1000 / (5000 × 2) = 0.1 mm/tooth within 1e-9."""
        spec = _make_spec(
            tool_diameter_mm=12.0,
            num_flutes=2,
            spindle_rpm=5000.0,
            feed_mm_per_min=1000.0,
            radial_engagement_mm=6.0,  # ae = D/2 → Krad = 1.0
            axial_depth_mm=3.0,
        )
        report = compute_chip_load(spec)
        assert abs(report.chip_load_per_tooth_mm - 0.1) < 1e-9

    def test_chip_load_per_tooth_is_vf_over_n_z(self):
        """Generic fz = Vf / (n × z) holds for arbitrary inputs."""
        Vf, n, z = 800.0, 3000.0, 4
        expected_fz = Vf / (n * z)
        spec = _make_spec(
            feed_mm_per_min=Vf,
            spindle_rpm=n,
            num_flutes=z,
            radial_engagement_mm=6.0,  # ae = D/2, Krad=1
        )
        report = compute_chip_load(spec)
        assert abs(report.chip_load_per_tooth_mm - expected_fz) < 1e-9


# ---------------------------------------------------------------------------
# T2 — chip thinning factor: Krad
# ---------------------------------------------------------------------------

class TestChipThinningFactor:
    def test_slot_cut_krad_is_1(self):
        """Full-width slot (ae = D): chip_thinning_factor == 1.0."""
        spec = _make_spec(radial_engagement_mm=12.0)  # ae == D
        report = compute_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(1.0, abs=1e-9)

    def test_half_width_krad_is_1(self):
        """ae = D/2: Krad = 1.0 (boundary — ae >= D/2 branch)."""
        spec = _make_spec(radial_engagement_mm=6.0)   # ae == D/2
        report = compute_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(1.0, abs=1e-9)

    def test_quarter_width_krad_gt_1(self):
        """ae = D/4: chip_thinning_factor > 1 (thinning increases effective chip)."""
        spec = _make_spec(radial_engagement_mm=3.0)   # ae == D/4
        report = compute_chip_load(spec)
        assert report.chip_thinning_factor > 1.0

    def test_quarter_width_krad_formula(self):
        """ae = D/4: Krad = D / (2·sqrt(D·ae − ae²)) computed analytically.

        Tolerance is abs=1e-6 because the implementation rounds krad to 6
        decimal places before storing it in the report.
        """
        D, ae = 12.0, 3.0
        expected_krad = D / (2.0 * math.sqrt(D * ae - ae * ae))
        spec = _make_spec(tool_diameter_mm=D, radial_engagement_mm=ae)
        report = compute_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(expected_krad, abs=1e-6)

    def test_tenth_width_krad_large(self):
        """ae = D/10: Krad >> 1 — strong thinning at very low radial engagement.

        Tolerance is abs=1e-6 because the implementation rounds krad to 6 dp.
        """
        D, ae = 12.0, 1.2  # ae = D/10
        expected_krad = D / (2.0 * math.sqrt(D * ae - ae * ae))
        spec = _make_spec(tool_diameter_mm=D, radial_engagement_mm=ae)
        report = compute_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(expected_krad, abs=1e-6)
        assert report.chip_thinning_factor > 1.5   # significantly > 1

    def test_ae_equals_D_krad_is_1(self):
        """ae = D exactly: Krad = 1.0 (full slot)."""
        spec = _make_spec(radial_engagement_mm=12.0)
        report = compute_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# T3 — actual chip load = fz × Krad
# ---------------------------------------------------------------------------

class TestActualChipLoad:
    def test_actual_chip_load_equals_fz_times_krad(self):
        """actual_chip_load_mm ≈ chip_load_per_tooth_mm × chip_thinning_factor.

        The implementation computes fz_actual = fz * krad internally with full
        floating-point precision before rounding to 9 decimal places.  The
        stored chip_thinning_factor field is separately rounded to 6 dp, so
        multiplying the two stored fields can differ from actual_chip_load_mm
        by up to ~1e-7.  We use abs=1e-6 tolerance here.
        """
        spec = _make_spec(radial_engagement_mm=3.0)   # ae = D/4, Krad > 1
        report = compute_chip_load(spec)
        expected = report.chip_load_per_tooth_mm * report.chip_thinning_factor
        assert abs(report.actual_chip_load_mm - expected) < 1e-6

    def test_no_thinning_at_half_width(self):
        """ae = D/2: actual == fz (Krad = 1)."""
        spec = _make_spec(radial_engagement_mm=6.0)
        report = compute_chip_load(spec)
        assert report.actual_chip_load_mm == pytest.approx(
            report.chip_load_per_tooth_mm, abs=1e-9
        )


# ---------------------------------------------------------------------------
# T4 — MRR
# ---------------------------------------------------------------------------

class TestMRR:
    def test_mrr_formula(self):
        """MRR = ae × ap × Vf / 1000 [cm³/min]."""
        ae, ap, Vf = 6.0, 3.0, 1000.0
        expected_mrr = ae * ap * Vf / 1000.0
        spec = _make_spec(
            radial_engagement_mm=ae,
            axial_depth_mm=ap,
            feed_mm_per_min=Vf,
        )
        report = compute_chip_load(spec)
        assert report.mrr_cm3_per_min == pytest.approx(expected_mrr, rel=1e-9)

    def test_mrr_units_positive(self):
        """MRR is always > 0 for valid inputs."""
        report = compute_chip_load(_make_spec())
        assert report.mrr_cm3_per_min > 0.0


# ---------------------------------------------------------------------------
# T5 — Compliance / recommended range
# ---------------------------------------------------------------------------

class TestCompliance:
    def test_carbide_aluminium_compliant(self):
        """0.1 mm/tooth with carbide on aluminium should be compliant (0.05–0.15)."""
        spec = _make_spec(
            tool_material="carbide",
            work_material="aluminium",
            radial_engagement_mm=6.0,   # Krad = 1 → actual = fz
        )
        report = compute_chip_load(spec)
        # fz = 0.1, which is in [0.05, 0.15]
        assert report.compliant is True
        assert report.recommended_min_mm == pytest.approx(0.05)
        assert report.recommended_max_mm == pytest.approx(0.15)

    def test_carbide_steel_compliant(self):
        """0.1 mm/tooth carbide on steel is in the 0.05–0.20 range."""
        spec = _make_spec(
            tool_material="carbide",
            work_material="steel_1018",
            radial_engagement_mm=6.0,
        )
        report = compute_chip_load(spec)
        assert report.compliant is True

    def test_hss_steel_range(self):
        """HSS on steel has 0.03–0.12 range."""
        spec = _make_spec(tool_material="HSS", work_material="steel")
        report = compute_chip_load(spec)
        assert report.recommended_min_mm == pytest.approx(0.03)
        assert report.recommended_max_mm == pytest.approx(0.12)

    def test_unknown_work_material_gives_none(self):
        """Unknown work material → recommended_min/max = None, compliant = None."""
        spec = _make_spec(work_material="unobtainium")
        report = compute_chip_load(spec)
        assert report.recommended_min_mm is None
        assert report.recommended_max_mm is None
        assert report.compliant is None

    def test_empty_work_material_gives_none(self):
        """Empty work_material → ranges None."""
        spec = _make_spec(work_material="")
        report = compute_chip_load(spec)
        assert report.recommended_min_mm is None
        assert report.compliant is None

    def test_aluminum_us_spelling_resolves(self):
        """'aluminum_6061' (US spelling) maps to aluminium class."""
        spec = _make_spec(
            tool_material="carbide",
            work_material="aluminum_6061",
            radial_engagement_mm=6.0,
        )
        report = compute_chip_load(spec)
        assert report.recommended_min_mm == pytest.approx(0.05)
        assert report.recommended_max_mm == pytest.approx(0.15)

    def test_noncompliant_fz_too_high(self):
        """Very high feed rate → fz_actual exceeds max → compliant = False."""
        # fz = 10000 / (1000 × 1) = 10 mm/tooth >> 0.15
        spec = _make_spec(
            feed_mm_per_min=10000.0,
            spindle_rpm=1000.0,
            num_flutes=1,
            radial_engagement_mm=6.0,   # Krad = 1
            tool_material="carbide",
            work_material="aluminium",
        )
        report = compute_chip_load(spec)
        assert report.compliant is False

    def test_noncompliant_fz_too_low(self):
        """Very low fz → actual chip load below min → compliant = False."""
        # fz = 1 / (5000 × 4) = 0.00005 mm/tooth << 0.05
        spec = _make_spec(
            feed_mm_per_min=1.0,
            spindle_rpm=5000.0,
            num_flutes=4,
            radial_engagement_mm=6.0,
            tool_material="carbide",
            work_material="aluminium",
        )
        report = compute_chip_load(spec)
        assert report.compliant is False


# ---------------------------------------------------------------------------
# T6 — Return type and honest caveat
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_chip_load_report(self):
        """compute_chip_load always returns a ChipLoadReport instance."""
        report = compute_chip_load(_make_spec())
        assert isinstance(report, ChipLoadReport)

    def test_honest_caveat_is_non_empty_string(self):
        """honest_caveat must be a non-empty string."""
        report = compute_chip_load(_make_spec())
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 0

    def test_honest_caveat_mentions_circular_engagement(self):
        """Caveat must mention the circular-arc-of-engagement assumption."""
        report = compute_chip_load(_make_spec())
        assert "circular" in report.honest_caveat.lower()

    def test_honest_caveat_mentions_no_climb_distinction(self):
        """Caveat must mention no climb/conventional distinction."""
        caveat_lower = report = compute_chip_load(_make_spec()).honest_caveat.lower()
        assert "climb" in caveat_lower or "conventional" in caveat_lower

    def test_honest_caveat_mentions_deflection(self):
        """Caveat must mention tool deflection."""
        report = compute_chip_load(_make_spec())
        assert "deflection" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# T7 — Validation / error handling
# ---------------------------------------------------------------------------

class TestValidation:
    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="tool_diameter_mm"):
            MillingOpSpec(
                tool_diameter_mm=0.0, num_flutes=2, spindle_rpm=5000.0,
                feed_mm_per_min=1000.0, radial_engagement_mm=3.0,
                axial_depth_mm=3.0, tool_material="carbide",
            )

    def test_zero_flutes_raises(self):
        with pytest.raises(ValueError, match="num_flutes"):
            MillingOpSpec(
                tool_diameter_mm=12.0, num_flutes=0, spindle_rpm=5000.0,
                feed_mm_per_min=1000.0, radial_engagement_mm=3.0,
                axial_depth_mm=3.0, tool_material="carbide",
            )

    def test_ae_exceeds_diameter_raises(self):
        with pytest.raises(ValueError, match="radial_engagement_mm"):
            MillingOpSpec(
                tool_diameter_mm=12.0, num_flutes=2, spindle_rpm=5000.0,
                feed_mm_per_min=1000.0, radial_engagement_mm=13.0,
                axial_depth_mm=3.0, tool_material="carbide",
            )

    def test_negative_ae_raises(self):
        with pytest.raises(ValueError, match="radial_engagement_mm"):
            MillingOpSpec(
                tool_diameter_mm=12.0, num_flutes=2, spindle_rpm=5000.0,
                feed_mm_per_min=1000.0, radial_engagement_mm=-1.0,
                axial_depth_mm=3.0, tool_material="carbide",
            )

    def test_zero_axial_depth_raises(self):
        with pytest.raises(ValueError, match="axial_depth_mm"):
            MillingOpSpec(
                tool_diameter_mm=12.0, num_flutes=2, spindle_rpm=5000.0,
                feed_mm_per_min=1000.0, radial_engagement_mm=6.0,
                axial_depth_mm=0.0, tool_material="carbide",
            )

    def test_invalid_tool_material_raises(self):
        with pytest.raises(ValueError, match="tool_material"):
            MillingOpSpec(
                tool_diameter_mm=12.0, num_flutes=2, spindle_rpm=5000.0,
                feed_mm_per_min=1000.0, radial_engagement_mm=6.0,
                axial_depth_mm=3.0, tool_material="diamond",
            )


# ---------------------------------------------------------------------------
# T8 — ceramic tool material
# ---------------------------------------------------------------------------

class TestCeramicTool:
    def test_ceramic_aluminium_range(self):
        """ceramic on aluminium has 0.10–0.30 mm/tooth range."""
        spec = _make_spec(tool_material="ceramic", work_material="aluminium")
        report = compute_chip_load(spec)
        assert report.recommended_min_mm == pytest.approx(0.10)
        assert report.recommended_max_mm == pytest.approx(0.30)
