"""
Analytic oracles for knit generators.

DoD requirements covered:
  - jersey stitch density matches gauge·courses to 1%
  - rib structure has correct repeat pattern
  - interlock alternates beds correctly
  - custom stitch notation validates
"""

from __future__ import annotations

import math
import pytest

from kerf_textiles.knit import jersey_knit, rib_knit, interlock_knit, custom_knit


# ---------------------------------------------------------------------------
# Jersey knit
# ---------------------------------------------------------------------------

class TestJerseyKnit:
    def test_all_loop_stitches(self):
        result = jersey_knit(needles=10, courses=10)
        for row in result.cell_matrix:
            assert all(s == "loop" for s in row)

    def test_density_within_1pct(self):
        """
        Analytic oracle: jersey stitch density = gauge × courses_per_cm.

        The computed density (loops / area_cm²) must match the analytic
        value to within 1%.
        """
        gauge = 5.0
        courses_per_cm = 7.0
        result = jersey_knit(needles=100, courses=100, gauge=gauge, courses_per_cm=courses_per_cm)
        stats = result.density_stats
        assert stats["density_within_1pct"], (
            f"density error {stats['relative_error']:.4%} > 1%: "
            f"computed={stats['computed_stitch_density']:.4f}, "
            f"analytic={stats['analytic_stitch_density']:.4f}"
        )

    def test_density_formula_exact(self):
        """
        For all-loop jersey, computed density == gauge * courses_per_cm exactly.

        computed = (needles * courses) / (width * height)
                 = (n * c) / ((n/gauge) * (c/cpc))
                 = gauge * cpc
        """
        gauge = 5.0
        cpc = 7.0
        result = jersey_knit(needles=50, courses=50, gauge=gauge, courses_per_cm=cpc)
        stats = result.density_stats
        assert stats["computed_stitch_density"] == pytest.approx(gauge * cpc, rel=1e-9)

    def test_various_gauge_density(self):
        """Density oracle must hold for a range of gauge/cpc combinations."""
        for gauge, cpc in [(3.0, 5.0), (7.0, 10.0), (12.0, 14.0), (0.5, 1.0)]:
            result = jersey_knit(needles=100, courses=100, gauge=gauge, courses_per_cm=cpc)
            stats = result.density_stats
            assert stats["density_within_1pct"], (
                f"gauge={gauge}, cpc={cpc}: error={stats['relative_error']:.4%}"
            )

    def test_matrix_shape(self):
        result = jersey_knit(needles=6, courses=8)
        assert len(result.cell_matrix) == 8
        assert all(len(row) == 6 for row in result.cell_matrix)

    def test_stats_keys(self):
        result = jersey_knit()
        required = {
            "needles", "courses", "loop_count", "tuck_count", "miss_count",
            "gauge", "courses_per_cm", "fabric_width_cm", "fabric_height_cm",
            "computed_stitch_density", "analytic_stitch_density",
            "relative_error", "density_within_1pct",
        }
        assert required.issubset(result.density_stats.keys())

    def test_name(self):
        result = jersey_knit()
        assert result.name == "jersey"

    def test_repeat_dimensions(self):
        result = jersey_knit()
        assert result.repeat_needles == 1
        assert result.repeat_courses == 1


# ---------------------------------------------------------------------------
# Rib knit
# ---------------------------------------------------------------------------

class TestRibKnit:
    def test_1x1_rib_pattern(self):
        """1×1 rib: alternating loop/miss."""
        result = rib_knit(knit_count=1, purl_count=1, needles=6, courses=4)
        for row in result.cell_matrix:
            for i, stitch in enumerate(row):
                expected = "loop" if i % 2 == 0 else "miss"
                assert stitch == expected, f"needle {i}: expected {expected}, got {stitch}"

    def test_2x2_rib_pattern(self):
        """2×2 rib: two loop then two miss."""
        result = rib_knit(knit_count=2, purl_count=2, needles=8, courses=4)
        for row in result.cell_matrix:
            for i, stitch in enumerate(row):
                expected = "loop" if (i % 4) < 2 else "miss"
                assert stitch == expected, f"needle {i}: expected {expected}, got {stitch}"

    def test_repeat_width(self):
        result = rib_knit(knit_count=2, purl_count=3)
        assert result.repeat_needles == 5

    def test_name(self):
        result = rib_knit(knit_count=1, purl_count=1)
        assert "rib_1x1" in result.name

    def test_loop_count_proportion(self):
        """1×1 rib: exactly half the stitches are loops."""
        result = rib_knit(knit_count=1, purl_count=1, needles=8, courses=8)
        total = sum(len(row) for row in result.cell_matrix)
        loops = result.density_stats["loop_count"]
        assert loops == total // 2

    def test_density_stats_present(self):
        result = rib_knit()
        assert "density_within_1pct" in result.density_stats


# ---------------------------------------------------------------------------
# Interlock knit
# ---------------------------------------------------------------------------

class TestInterlockKnit:
    def test_alternating_courses(self):
        """Interlock alternates bed-A and bed-B courses."""
        result = interlock_knit(needles=8, courses=4)
        row_a = result.cell_matrix[0]
        row_b = result.cell_matrix[1]
        # row_a: loop miss loop miss ...
        for i, s in enumerate(row_a):
            expected = "loop" if i % 2 == 0 else "miss"
            assert s == expected
        # row_b: miss loop miss loop ...
        for i, s in enumerate(row_b):
            expected = "miss" if i % 2 == 0 else "loop"
            assert s == expected

    def test_beds_are_complementary(self):
        """Bed A and bed B are complementary — every position has a loop on one bed."""
        result = interlock_knit(needles=8, courses=4)
        row_a = result.cell_matrix[0]
        row_b = result.cell_matrix[1]
        for a, b in zip(row_a, row_b):
            assert (a == "loop") != (b == "loop"), "beds must be complementary"

    def test_repeat_dimensions(self):
        result = interlock_knit()
        assert result.repeat_needles == 2
        assert result.repeat_courses == 2

    def test_courses_alternate_for_full_matrix(self):
        result = interlock_knit(needles=4, courses=6)
        for i in range(0, 6, 2):
            assert result.cell_matrix[i] == result.cell_matrix[0]
        for i in range(1, 6, 2):
            assert result.cell_matrix[i] == result.cell_matrix[1]

    def test_name(self):
        assert interlock_knit().name == "interlock"


# ---------------------------------------------------------------------------
# Custom knit
# ---------------------------------------------------------------------------

class TestCustomKnit:
    def test_basic_custom(self):
        notation = [
            ["loop", "tuck", "miss"],
            ["miss", "loop", "tuck"],
        ]
        result = custom_knit(notation)
        assert result.name == "custom"
        assert result.cell_matrix == notation

    def test_loop_tuck_miss_counts(self):
        notation = [
            ["loop", "loop", "tuck"],
            ["miss", "loop", "miss"],
        ]
        result = custom_knit(notation)
        assert result.density_stats["loop_count"] == 3
        assert result.density_stats["tuck_count"] == 1
        assert result.density_stats["miss_count"] == 2

    def test_invalid_stitch_type(self):
        with pytest.raises(ValueError, match="not in"):
            custom_knit([["loop", "knit"]])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            custom_knit([])

    def test_repeat_tracks_matrix(self):
        notation = [["loop"] * 5] * 3
        result = custom_knit(notation)
        assert result.repeat_needles == 5
        assert result.repeat_courses == 3

    def test_density_stats_present(self):
        result = custom_knit([["loop", "miss"], ["tuck", "loop"]])
        assert "relative_error" in result.density_stats
