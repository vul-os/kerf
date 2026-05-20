"""
Analytic oracles for weave generators.

DoD requirements covered:
  1. plain-weave float-length matches the analytic formula (mean_float == 1.0)
  2. 2/1 twill produces the canonical diagonal stagger
  3. Satin has correct interlacement pattern
  4. Jacquard reconstructs from draft correctly
"""

from __future__ import annotations

import math
import pytest

from kerf_textiles.weave import plain_weave, twill_weave, satin_weave, jacquard_from_draft


# ---------------------------------------------------------------------------
# Plain weave
# ---------------------------------------------------------------------------

class TestPlainWeave:
    def test_repeat_size(self):
        pw = plain_weave()
        assert pw.repeat_warp == 2
        assert pw.repeat_weft == 2

    def test_cell_matrix_shape(self):
        pw = plain_weave()
        assert len(pw.cell_matrix) == 2
        assert all(len(row) == 2 for row in pw.cell_matrix)

    def test_checkerboard_pattern(self):
        """Plain weave must be a checkerboard: (r+c) % 2 == 0 → True."""
        pw = plain_weave()
        for r, row in enumerate(pw.cell_matrix):
            for c, val in enumerate(row):
                expected = (r + c) % 2 == 0
                assert val == expected, f"cell[{r}][{c}]: expected {expected}, got {val}"

    def test_warp_mean_float_analytic(self):
        """
        Analytic oracle: plain weave warp mean float == 1.0.

        Every warp thread interlaces on every pick → float length of 1.
        """
        pw = plain_weave()
        assert pw.float_stats["warp_mean_float"] == pytest.approx(1.0, abs=1e-9)

    def test_weft_mean_float_analytic(self):
        """Analytic oracle: plain weave weft mean float == 1.0."""
        pw = plain_weave()
        assert pw.float_stats["weft_mean_float"] == pytest.approx(1.0, abs=1e-9)

    def test_analytic_stored_values(self):
        pw = plain_weave()
        assert pw.analytic_warp_mean_float == 1.0
        assert pw.analytic_weft_mean_float == 1.0

    def test_sampled_matches_analytic(self):
        """Sampled float lengths must match stored analytic values."""
        pw = plain_weave()
        assert pw.float_stats["warp_mean_float"] == pytest.approx(
            pw.analytic_warp_mean_float, abs=1e-9
        )
        assert pw.float_stats["weft_mean_float"] == pytest.approx(
            pw.analytic_weft_mean_float, abs=1e-9
        )

    def test_tile_raster_is_tiled(self):
        pw = plain_weave()
        # Default tiling: 4×4 repeats of a 2×2 matrix → 8×8
        assert len(pw.tile_raster) == 8
        assert len(pw.tile_raster[0]) == 8

    def test_vector_paths_count(self):
        pw = plain_weave()
        # 2×2 matrix → 4 paths
        assert len(pw.vector_paths) == 4

    def test_vector_paths_labels(self):
        pw = plain_weave()
        for path in pw.vector_paths:
            assert path[2] in ("over", "under")


# ---------------------------------------------------------------------------
# Twill weave — 2/1 right-hand
# ---------------------------------------------------------------------------

class TestTwillWeave:
    def setup_method(self):
        self.tw = twill_weave(over=2, under=1, direction="RH")

    def test_repeat_size(self):
        assert self.tw.repeat_warp == 3
        assert self.tw.repeat_weft == 3

    def test_cell_matrix_shape(self):
        m = self.tw.cell_matrix
        assert len(m) == 3
        assert all(len(row) == 3 for row in m)

    def test_canonical_diagonal_stagger(self):
        """
        2/1 RH twill canonical cell matrix:
          row 0: T T F   (over 2 starting at col 0)
          row 1: F T T   (stagger +1 right)
          row 2: T F T   (stagger +1 right again)
        """
        m = self.tw.cell_matrix
        # Row 0: columns 0,1 True; column 2 False
        assert m[0][0] is True
        assert m[0][1] is True
        assert m[0][2] is False
        # Row 1: stagger right by 1 → columns 1,2 True; column 0 False
        assert m[1][0] is False
        assert m[1][1] is True
        assert m[1][2] is True
        # Row 2: stagger right by 1 → column 2,0 True; column 1 False
        assert m[2][0] is True
        assert m[2][1] is False
        assert m[2][2] is True

    def test_warp_mean_float_analytic(self):
        """
        Analytic oracle: 2/1 twill warp mean float == 2.0.

        Each warp thread floats over 2 consecutive wefts before interlacing.
        """
        assert self.tw.float_stats["warp_mean_float"] == pytest.approx(2.0, abs=1e-9)

    def test_weft_mean_float_analytic(self):
        """Analytic oracle: 2/1 twill weft mean float == 1.0."""
        assert self.tw.float_stats["weft_mean_float"] == pytest.approx(1.0, abs=1e-9)

    def test_analytic_stored_values(self):
        assert self.tw.analytic_warp_mean_float == 2.0
        assert self.tw.analytic_weft_mean_float == 1.0

    def test_sampled_matches_analytic(self):
        assert self.tw.float_stats["warp_mean_float"] == pytest.approx(
            self.tw.analytic_warp_mean_float, abs=1e-9
        )
        assert self.tw.float_stats["weft_mean_float"] == pytest.approx(
            self.tw.analytic_weft_mean_float, abs=1e-9
        )

    def test_left_hand_direction(self):
        """LH twill should be the mirror of RH — diagonal goes the other way."""
        lh = twill_weave(over=2, under=1, direction="LH")
        rh = twill_weave(over=2, under=1, direction="RH")
        # They should differ (not identical)
        assert lh.cell_matrix != rh.cell_matrix

    def test_3_1_twill(self):
        """3/1 twill: repeat=4, warp float=3, weft float=1."""
        tw = twill_weave(over=3, under=1)
        assert tw.repeat_warp == 4
        assert tw.float_stats["warp_mean_float"] == pytest.approx(3.0, abs=1e-9)
        assert tw.float_stats["weft_mean_float"] == pytest.approx(1.0, abs=1e-9)

    def test_2_2_twill(self):
        """2/2 twill: repeat=4, warp float=2, weft float=2."""
        tw = twill_weave(over=2, under=2)
        assert tw.repeat_warp == 4
        assert tw.float_stats["warp_mean_float"] == pytest.approx(2.0, abs=1e-9)
        assert tw.float_stats["weft_mean_float"] == pytest.approx(2.0, abs=1e-9)

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            twill_weave(over=0, under=1)
        with pytest.raises(ValueError):
            twill_weave(over=1, under=0)

    def test_name_contains_direction(self):
        assert "RH" in self.tw.name
        lh = twill_weave(over=2, under=1, direction="LH")
        assert "LH" in lh.name


# ---------------------------------------------------------------------------
# Satin weave
# ---------------------------------------------------------------------------

class TestSatinWeave:
    def test_5_shaft_satin(self):
        sat = satin_weave(shafts=5, move=2)
        assert sat.repeat_warp == 5
        assert sat.repeat_weft == 5

    def test_exactly_one_interlacement_per_row(self):
        """
        Warp-faced satin: exactly one False (warp-under) per row.

        Each row has one pick where the weft goes over one warp — the single
        interlacement per weft course.
        """
        sat = satin_weave(shafts=5, move=2)
        for r, row in enumerate(sat.cell_matrix):
            n_under = sum(1 for v in row if not v)
            assert n_under == 1, f"row {r} has {n_under} warp-under cells (expected 1)"

    def test_exactly_one_interlacement_per_col(self):
        """
        Warp-faced satin: exactly one False (warp-under) per column.

        Each warp end has one interlacement (goes under one weft) per repeat.
        """
        sat = satin_weave(shafts=5, move=2)
        n_rows = len(sat.cell_matrix)
        for c in range(5):
            n_under = sum(1 for r in range(n_rows) if not sat.cell_matrix[r][c])
            assert n_under == 1, f"col {c} has {n_under} warp-under cells (expected 1)"

    def test_warp_float_analytic(self):
        """
        Analytic oracle: 5-shaft warp-faced satin warp mean float == 4.0.

        Each warp thread floats over shafts-1=4 consecutive wefts before
        going under one weft (the one interlacement per repeat).
        """
        sat = satin_weave(shafts=5, move=2)
        assert sat.float_stats["warp_mean_float"] == pytest.approx(4.0, abs=1e-9)

    def test_weft_float_analytic(self):
        """
        Analytic oracle: warp-faced satin weft float == 1.0.

        The weft is mostly hidden — it only goes over one warp per row.
        """
        sat = satin_weave(shafts=5, move=2)
        assert sat.float_stats["weft_mean_float"] == pytest.approx(1.0, abs=1e-9)

    def test_8_shaft_satin(self):
        sat = satin_weave(shafts=8, move=3)
        assert sat.analytic_warp_mean_float == 7.0
        assert sat.float_stats["warp_mean_float"] == pytest.approx(7.0, abs=1e-9)

    def test_invalid_gcd(self):
        with pytest.raises(ValueError, match="gcd"):
            satin_weave(shafts=6, move=3)  # gcd(6,3)=3 ≠ 1

    def test_invalid_move_range(self):
        with pytest.raises(ValueError):
            satin_weave(shafts=5, move=1)  # move must be > 1

    def test_too_few_shafts(self):
        with pytest.raises(ValueError):
            satin_weave(shafts=3, move=2)


# ---------------------------------------------------------------------------
# Jacquard from draft
# ---------------------------------------------------------------------------

class TestJacquardFromDraft:
    def _plain_draft_args(self):
        """Draft arguments that should produce plain weave."""
        threading = [0, 1, 0, 1]
        treadling = [0, 1, 0, 1]
        tie_up = [
            [True, False],   # shaft 0 → treadle 0
            [False, True],   # shaft 1 → treadle 1
        ]
        return threading, treadling, tie_up

    def test_plain_from_jacquard(self):
        """Jacquard with plain-weave draft must produce a checkerboard."""
        threading, treadling, tie_up = self._plain_draft_args()
        result = jacquard_from_draft(threading, treadling, tie_up)
        m = result.cell_matrix
        for r, row in enumerate(m):
            for c, val in enumerate(row):
                expected = (r + c) % 2 == 0
                assert val == expected, f"cell[{r}][{c}]: expected {expected}, got {val}"

    def test_shape(self):
        threading, treadling, tie_up = self._plain_draft_args()
        result = jacquard_from_draft(threading, treadling, tie_up)
        assert len(result.cell_matrix) == len(treadling)
        assert len(result.cell_matrix[0]) == len(threading)

    def test_all_over(self):
        """If all tie_up entries are True, all cells should be True."""
        threading = [0, 0, 0]
        treadling = [0, 0]
        tie_up = [[True]]
        result = jacquard_from_draft(threading, treadling, tie_up)
        for row in result.cell_matrix:
            assert all(row)

    def test_all_under(self):
        threading = [0, 0, 0]
        treadling = [0, 0]
        tie_up = [[False]]
        result = jacquard_from_draft(threading, treadling, tie_up)
        for row in result.cell_matrix:
            assert not any(row)

    def test_invalid_shaft_index(self):
        with pytest.raises(ValueError, match="shaft"):
            jacquard_from_draft([0, 5], [0], [[True]])

    def test_invalid_treadle_index(self):
        with pytest.raises(ValueError, match="treadle"):
            jacquard_from_draft([0], [0, 5], [[True, True]])

    def test_float_stats_present(self):
        threading, treadling, tie_up = self._plain_draft_args()
        result = jacquard_from_draft(threading, treadling, tie_up)
        assert "warp_mean_float" in result.float_stats
        assert "weft_mean_float" in result.float_stats
