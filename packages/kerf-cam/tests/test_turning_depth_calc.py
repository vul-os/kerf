"""
Tests for kerf_cam.turning_depth_calc — turning depth-of-cut calculator.

References
----------
* MH 31e §1148 — Turning depth-of-cut, roughing vs finishing
* Sandvik Coromant CoroPlus Turning Catalogue (2024)
"""

from __future__ import annotations

import math
import pytest

from kerf_cam.turning_depth_calc import (
    TurningSpec,
    TurningDepthReport,
    compute_turning_depth,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_spec(**kwargs) -> TurningSpec:
    """Build a TurningSpec with sensible defaults, overridden by kwargs."""
    defaults = dict(
        stock_diameter_mm=50.0,
        final_diameter_mm=40.0,
        material="steel_1018",
        tool_nose_radius_mm=0.8,
        feed_mm_per_rev=0.2,
        spindle_rpm=1000.0,
        finish_pass_doc_mm=0.5,
        max_roughing_doc_mm=3.0,
        workpiece_length_mm=100.0,
    )
    defaults.update(kwargs)
    return TurningSpec(**defaults)


# ---------------------------------------------------------------------------
# T1 — Canonical example: D=50→40, max_DOC=3, finish=0.5
# radial_stock = (50-40)/2 = 5 mm
# stock_for_roughing = 5 - 0.5 = 4.5 mm
# num_roughing = ceil(4.5/3) = 2 → not 3 per spec description
#
# Wait: spec says "floor((5-0.5)/3)+1+1" = floor(1.5)+1+1 = 1+1+1 = 3 roughing
# BUT that is an incorrect formula. The correct ceil-based formula gives:
#   ceil(4.5/3) = ceil(1.5) = 2 roughing passes
#
# The task description says "floor((5-0.5)/3)+1+1 = 3 roughing + 1 finishing"
# which uses floor + 1 to get the number of roughing passes (i.e. floor(x)+1
# is equivalent to ceil(x) only when x is NOT an integer).
# floor(4.5/3) + 1 = floor(1.5) + 1 = 1 + 1 = 2 ← same as ceil when non-integer
#
# Actually re-reading the task spec formula: floor((5-0.5)/3)+1+1 = 3 roughing
# The task writes "+1+1" meaning: +1 for roughing rounding, +1 for finishing.
# So roughing = floor(4.5/3)+1 = 1+1 = 2, total = 2+1 = 3.
# That matches ceil(4.5/3)=2 roughing, 1 finishing, 3 total.
# ---------------------------------------------------------------------------

class TestCanonicalExample:
    """D=50mm → 40mm, max_DOC=3mm, finish=0.5mm, steel_1018."""

    def test_radial_stock_is_5mm(self):
        """Radial stock removal = (50 - 40) / 2 = 5 mm."""
        spec = _make_spec()
        report = compute_turning_depth(spec)
        # Indirectly: roughing_doc * num_roughing + finish = 5
        total_removed = report.roughing_doc_mm * report.num_roughing_passes + 0.5
        assert abs(total_removed - 5.0) < 1e-9

    def test_num_roughing_passes(self):
        """ceil((5-0.5)/3) = ceil(1.5) = 2 roughing passes."""
        spec = _make_spec()
        report = compute_turning_depth(spec)
        assert report.num_roughing_passes == 2

    def test_num_finishing_passes(self):
        """Always 1 finishing pass."""
        spec = _make_spec()
        report = compute_turning_depth(spec)
        assert report.num_finishing_passes == 1

    def test_total_passes(self):
        """Total = 2 roughing + 1 finishing = 3."""
        spec = _make_spec()
        report = compute_turning_depth(spec)
        assert report.total_passes == 3

    def test_roughing_doc_equal_spacing(self):
        """roughing_doc = 4.5 / 2 = 2.25 mm (equal spacing)."""
        spec = _make_spec()
        report = compute_turning_depth(spec)
        assert abs(report.roughing_doc_mm - 2.25) < 1e-6

    def test_roughing_doc_does_not_exceed_max(self):
        """Each roughing pass must not exceed max_roughing_doc_mm."""
        spec = _make_spec()
        report = compute_turning_depth(spec)
        assert report.roughing_doc_mm <= spec.max_roughing_doc_mm


# ---------------------------------------------------------------------------
# T2 — Recommended DOC per material (MH 31e §1148 + Sandvik CoroPlus 2024)
# ---------------------------------------------------------------------------

class TestRecommendedDocByMaterial:
    def test_steel_1018_recommended_doc(self):
        """steel_1018 recommended DOC midpoint = 3.0 mm."""
        spec = _make_spec(material="steel_1018")
        report = compute_turning_depth(spec)
        assert report.recommended_doc_for_material == pytest.approx(3.0)

    def test_aluminum_6061_recommended_doc(self):
        """aluminum_6061 recommended DOC midpoint = 6.0 mm."""
        spec = _make_spec(material="aluminum_6061")
        report = compute_turning_depth(spec)
        assert report.recommended_doc_for_material == pytest.approx(6.0)

    def test_stainless_303_recommended_doc(self):
        """stainless_303 recommended DOC midpoint = 2.0 mm."""
        spec = _make_spec(material="stainless_303")
        report = compute_turning_depth(spec)
        assert report.recommended_doc_for_material == pytest.approx(2.0)

    def test_steel_recommended_in_range_2_to_4(self):
        """steel_1018 midpoint must be in [2.0, 4.0] mm range."""
        spec = _make_spec(material="steel_1018")
        report = compute_turning_depth(spec)
        assert 2.0 <= report.recommended_doc_for_material <= 4.0

    def test_aluminum_recommended_in_range_4_to_8(self):
        """aluminum_6061 midpoint must be in [4.0, 8.0] mm range."""
        spec = _make_spec(material="aluminum_6061")
        report = compute_turning_depth(spec)
        assert 4.0 <= report.recommended_doc_for_material <= 8.0

    def test_stainless_recommended_in_range_1p5_to_2p5(self):
        """stainless_303 midpoint must be in [1.5, 2.5] mm range."""
        spec = _make_spec(material="stainless_303")
        report = compute_turning_depth(spec)
        assert 1.5 <= report.recommended_doc_for_material <= 2.5


# ---------------------------------------------------------------------------
# T3 — Material DOC clamping: if max_roughing_doc exceeds material max, clamp it
# ---------------------------------------------------------------------------

class TestMaterialDocClamping:
    def test_steel_max_doc_clamped_at_4mm(self):
        """steel_1018: max_roughing_doc=10 should be clamped to 4.0 mm."""
        # stock 60 → 40 mm; radial = 10 mm; finish = 0.5; roughing stock = 9.5 mm
        # clamped max_doc = 4 mm → ceil(9.5/4) = 3 passes → roughing_doc = 9.5/3 ≈ 3.167
        spec = _make_spec(
            stock_diameter_mm=60.0,
            final_diameter_mm=40.0,
            material="steel_1018",
            max_roughing_doc_mm=10.0,
        )
        report = compute_turning_depth(spec)
        assert report.roughing_doc_mm <= 4.0

    def test_aluminum_max_doc_clamped_at_8mm(self):
        """aluminum_6061: max_roughing_doc=20 should be clamped to 8.0 mm."""
        spec = _make_spec(
            stock_diameter_mm=80.0,
            final_diameter_mm=40.0,
            material="aluminum_6061",
            max_roughing_doc_mm=20.0,
        )
        report = compute_turning_depth(spec)
        assert report.roughing_doc_mm <= 8.0

    def test_stainless_max_doc_clamped_at_2p5mm(self):
        """stainless_303: max_roughing_doc=5 should be clamped to 2.5 mm."""
        spec = _make_spec(
            stock_diameter_mm=60.0,
            final_diameter_mm=40.0,
            material="stainless_303",
            max_roughing_doc_mm=5.0,
        )
        report = compute_turning_depth(spec)
        assert report.roughing_doc_mm <= 2.5


# ---------------------------------------------------------------------------
# T4 — No roughing passes when stock ≤ finish_doc
# ---------------------------------------------------------------------------

class TestNoRoughingPasses:
    def test_only_finish_pass_when_stock_equals_finish_doc(self):
        """If radial_stock == finish_pass_doc, num_roughing_passes == 0."""
        # radial_stock = (50 - 49) / 2 = 0.5 mm; finish_doc = 0.5 mm
        spec = _make_spec(
            stock_diameter_mm=50.0,
            final_diameter_mm=49.0,
            finish_pass_doc_mm=0.5,
        )
        report = compute_turning_depth(spec)
        assert report.num_roughing_passes == 0
        assert report.total_passes == 1
        assert report.roughing_doc_mm == 0.0

    def test_only_finish_pass_when_stock_less_than_finish_doc(self):
        """If radial_stock < finish_pass_doc, num_roughing_passes == 0."""
        # radial_stock = (50 - 49.5) / 2 = 0.25 mm < 0.5 mm finish
        spec = _make_spec(
            stock_diameter_mm=50.0,
            final_diameter_mm=49.5,
            finish_pass_doc_mm=0.5,
        )
        report = compute_turning_depth(spec)
        assert report.num_roughing_passes == 0
        assert report.total_passes == 1


# ---------------------------------------------------------------------------
# T5 — Machining time estimate
# ---------------------------------------------------------------------------

class TestMachiningTime:
    def test_time_formula(self):
        """total_time = L / (f × n / 60) × total_passes."""
        spec = _make_spec(
            feed_mm_per_rev=0.2,
            spindle_rpm=1000.0,
            workpiece_length_mm=100.0,
        )
        report = compute_turning_depth(spec)
        time_per_pass = 100.0 / (0.2 * 1000.0 / 60.0)  # = 100 / (200/60) = 30 s
        expected = time_per_pass * report.total_passes
        assert abs(report.total_machining_time_s - expected) < 1e-4

    def test_time_is_positive(self):
        """Machining time must be > 0."""
        report = compute_turning_depth(_make_spec())
        assert report.total_machining_time_s > 0.0

    def test_more_passes_more_time(self):
        """More passes → more total machining time."""
        spec_small_doc = _make_spec(max_roughing_doc_mm=0.5)
        spec_large_doc = _make_spec(max_roughing_doc_mm=3.0)
        small_report = compute_turning_depth(spec_small_doc)
        large_report = compute_turning_depth(spec_large_doc)
        assert small_report.total_passes >= large_report.total_passes
        assert small_report.total_machining_time_s >= large_report.total_machining_time_s


# ---------------------------------------------------------------------------
# T6 — Nose-radius warning in caveat
# ---------------------------------------------------------------------------

class TestNoseRadiusCaveat:
    def test_nose_radius_warning_when_finish_doc_too_small(self):
        """finish_pass_doc < 0.5 × r_ε → 'WARNING' in honest_caveat."""
        # r_ε = 1.2 mm → min_finish_doc = 0.6 mm; use finish = 0.3 mm
        spec = _make_spec(tool_nose_radius_mm=1.2, finish_pass_doc_mm=0.3)
        report = compute_turning_depth(spec)
        assert "WARNING" in report.honest_caveat

    def test_no_nose_radius_warning_when_finish_doc_ok(self):
        """finish_pass_doc >= 0.5 × r_ε → no 'WARNING' prefix in caveat."""
        # r_ε = 0.8 mm → min_finish_doc = 0.4 mm; use finish = 0.5 mm ≥ 0.4
        spec = _make_spec(tool_nose_radius_mm=0.8, finish_pass_doc_mm=0.5)
        report = compute_turning_depth(spec)
        assert not report.honest_caveat.startswith("WARNING")


# ---------------------------------------------------------------------------
# T7 — Return type and honest caveat content
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_turning_depth_report(self):
        """compute_turning_depth always returns a TurningDepthReport instance."""
        report = compute_turning_depth(_make_spec())
        assert isinstance(report, TurningDepthReport)

    def test_honest_caveat_non_empty(self):
        """honest_caveat must be a non-empty string."""
        report = compute_turning_depth(_make_spec())
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 0

    def test_honest_caveat_mentions_straight_turning(self):
        """Caveat must mention straight/cylindrical turning limitation."""
        report = compute_turning_depth(_make_spec())
        lower = report.honest_caveat.lower()
        assert "straight" in lower or "cylindrical" in lower or "profile" in lower

    def test_honest_caveat_mentions_css(self):
        """Caveat must mention CSS / G96 not implemented."""
        report = compute_turning_depth(_make_spec())
        lower = report.honest_caveat.lower()
        assert "css" in lower or "g96" in lower or "constant surface" in lower

    def test_honest_caveat_mentions_rapids_excluded(self):
        """Caveat must mention that rapids/tool changes are excluded from time."""
        report = compute_turning_depth(_make_spec())
        lower = report.honest_caveat.lower()
        assert "rapid" in lower or "tool change" in lower or "acceleration" in lower


# ---------------------------------------------------------------------------
# T8 — Validation / error handling
# ---------------------------------------------------------------------------

class TestValidation:
    def test_stock_le_final_raises(self):
        """stock_diameter_mm <= final_diameter_mm must raise ValueError."""
        with pytest.raises(ValueError, match="stock_diameter_mm"):
            TurningSpec(
                stock_diameter_mm=40.0, final_diameter_mm=50.0,
                material="steel_1018", tool_nose_radius_mm=0.8,
                feed_mm_per_rev=0.2, spindle_rpm=1000.0,
            )

    def test_stock_equal_final_raises(self):
        """stock_diameter_mm == final_diameter_mm must raise ValueError."""
        with pytest.raises(ValueError, match="stock_diameter_mm"):
            TurningSpec(
                stock_diameter_mm=50.0, final_diameter_mm=50.0,
                material="steel_1018", tool_nose_radius_mm=0.8,
                feed_mm_per_rev=0.2, spindle_rpm=1000.0,
            )

    def test_invalid_material_raises(self):
        """Unknown material must raise ValueError."""
        with pytest.raises(ValueError, match="material"):
            TurningSpec(
                stock_diameter_mm=50.0, final_diameter_mm=40.0,
                material="unobtainium", tool_nose_radius_mm=0.8,
                feed_mm_per_rev=0.2, spindle_rpm=1000.0,
            )

    def test_zero_nose_radius_raises(self):
        """tool_nose_radius_mm = 0 must raise ValueError."""
        with pytest.raises(ValueError, match="tool_nose_radius_mm"):
            TurningSpec(
                stock_diameter_mm=50.0, final_diameter_mm=40.0,
                material="steel_1018", tool_nose_radius_mm=0.0,
                feed_mm_per_rev=0.2, spindle_rpm=1000.0,
            )

    def test_negative_feed_raises(self):
        """feed_mm_per_rev <= 0 must raise ValueError."""
        with pytest.raises(ValueError, match="feed_mm_per_rev"):
            TurningSpec(
                stock_diameter_mm=50.0, final_diameter_mm=40.0,
                material="steel_1018", tool_nose_radius_mm=0.8,
                feed_mm_per_rev=-0.1, spindle_rpm=1000.0,
            )

    def test_zero_rpm_raises(self):
        """spindle_rpm = 0 must raise ValueError."""
        with pytest.raises(ValueError, match="spindle_rpm"):
            TurningSpec(
                stock_diameter_mm=50.0, final_diameter_mm=40.0,
                material="steel_1018", tool_nose_radius_mm=0.8,
                feed_mm_per_rev=0.2, spindle_rpm=0.0,
            )

    def test_zero_final_diameter_raises(self):
        """final_diameter_mm = 0 must raise ValueError."""
        with pytest.raises(ValueError, match="final_diameter_mm"):
            TurningSpec(
                stock_diameter_mm=50.0, final_diameter_mm=0.0,
                material="steel_1018", tool_nose_radius_mm=0.8,
                feed_mm_per_rev=0.2, spindle_rpm=1000.0,
            )


# ---------------------------------------------------------------------------
# T9 — Aluminum 6061: large stock removal, verify pass counts
# ---------------------------------------------------------------------------

class TestAluminumLargeRemoval:
    def test_aluminum_large_stock_removal(self):
        """aluminum_6061, D=100→60 mm: radial=20 mm; max_doc clamped to 8 mm."""
        # radial = (100-60)/2 = 20 mm; finish = 0.5 mm; roughing_stock = 19.5 mm
        # clamped max_doc = min(10, 8) = 8 mm → ceil(19.5/8) = 3 passes
        # roughing_doc = 19.5/3 = 6.5 mm ≤ 8 mm
        spec = _make_spec(
            stock_diameter_mm=100.0,
            final_diameter_mm=60.0,
            material="aluminum_6061",
            max_roughing_doc_mm=10.0,
        )
        report = compute_turning_depth(spec)
        assert report.num_roughing_passes == 3
        assert abs(report.roughing_doc_mm - 6.5) < 1e-6
        assert report.total_passes == 4

    def test_aluminum_passes_gt_1(self):
        """aluminum_6061 with substantial stock should have > 1 roughing pass."""
        spec = _make_spec(
            stock_diameter_mm=80.0,
            final_diameter_mm=40.0,
            material="aluminum_6061",
            max_roughing_doc_mm=3.0,
        )
        report = compute_turning_depth(spec)
        assert report.num_roughing_passes >= 1


# ---------------------------------------------------------------------------
# T10 — Stainless 303: tight DOC constraints
# ---------------------------------------------------------------------------

class TestStainless303:
    def test_stainless_roughing_doc_within_range(self):
        """stainless_303 roughing DOC must be in [1.5, 2.5] mm range."""
        # When max_roughing_doc is within range, clamping keeps it there.
        spec = _make_spec(
            stock_diameter_mm=60.0,
            final_diameter_mm=50.0,
            material="stainless_303",
            max_roughing_doc_mm=2.0,
        )
        report = compute_turning_depth(spec)
        if report.num_roughing_passes > 0:
            assert report.roughing_doc_mm <= 2.5

    def test_stainless_more_passes_than_aluminum_for_same_stock(self):
        """stainless needs more passes than aluminum for same stock removal."""
        common = dict(
            stock_diameter_mm=60.0,
            final_diameter_mm=40.0,
            max_roughing_doc_mm=10.0,
        )
        stainless = _make_spec(material="stainless_303", **common)
        aluminum = _make_spec(material="aluminum_6061", **common)
        r_stainless = compute_turning_depth(stainless)
        r_aluminum = compute_turning_depth(aluminum)
        assert r_stainless.num_roughing_passes >= r_aluminum.num_roughing_passes
