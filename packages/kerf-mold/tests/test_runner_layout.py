"""
Tests for kerf_mold.runner_layout — MOLD-RUNNER-LAYOUT

Covers:
  - Single cavity: trivial layout
  - 4-cavity 2×2 symmetric: balance == 1.0 (natural balance)
  - 8-cavity row: balance < 1.0, artificial_balance_required == True
  - Beaumont 2007 §6.5 diameter sizing
  - LLM tool round-trip (mold_generate_runner_layout)
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_mold.runner_layout import (
    generate_runner_layout,
    beaumont_runner_diameter,
    RunnerLayout,
    RunnerSegment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


class _Ctx:
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# Beaumont 2007 §6.5 diameter formula
# ---------------------------------------------------------------------------

class TestBeaumontDiameter:
    def test_formula_positive_weight(self):
        """D = max(W^0.25 + 0.5, table_lookup), capped at 10 mm."""
        d = beaumont_runner_diameter(10.0)
        # Formula gives ~2.28; table gives 3.2 for 10 g; result should be >= formula
        formula_val = 10.0 ** 0.25 + 0.5
        assert d >= formula_val - 0.1  # at least the formula value
        assert d <= 10.0  # never exceeds cap

    def test_small_weight_minimum_diameter(self):
        """Very light parts get at least 2.0 mm runner."""
        d = beaumont_runner_diameter(0.1)
        assert d >= 2.0

    def test_heavy_part_capped_at_10mm(self):
        """Parts >≈ 1000 g: diameter capped at 10 mm."""
        d = beaumont_runner_diameter(2000.0)
        assert d <= 10.0

    def test_medium_weight_in_range(self):
        """50 g part: diameter should be in [3.5, 6.0] mm per Beaumont Table 6.5."""
        d = beaumont_runner_diameter(50.0)
        assert 3.5 <= d <= 6.0

    def test_100g_within_table_range(self):
        """100 g part: Beaumont Table 6.5 gives ~5.5 mm."""
        d = beaumont_runner_diameter(100.0)
        assert 4.5 <= d <= 7.0

    def test_zero_weight_raises(self):
        with pytest.raises(ValueError):
            beaumont_runner_diameter(0.0)

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError):
            beaumont_runner_diameter(-5.0)


# ---------------------------------------------------------------------------
# Single cavity — trivial layout
# ---------------------------------------------------------------------------

class TestSingleCavity:
    def _layout(self):
        return generate_runner_layout(
            cavity_positions=[[50.0, 0.0]],
            part_weights=[20.0],
            sprue_position=[0.0, 0.0],
        )

    def test_single_segment(self):
        layout = self._layout()
        assert len(layout.runner_segments) == 1

    def test_balance_score_one(self):
        layout = self._layout()
        assert layout.balance_score == 1.0

    def test_naturally_balanced(self):
        layout = self._layout()
        assert layout.naturally_balanced is True

    def test_artificial_balance_not_required(self):
        layout = self._layout()
        assert layout.artificial_balance_required is False

    def test_n_cavities(self):
        layout = self._layout()
        assert layout.n_cavities == 1

    def test_diameter_sensible(self):
        layout = self._layout()
        d = list(layout.diameters.values())[0]
        assert 2.0 <= d <= 10.0

    def test_pressure_drop_positive(self):
        layout = self._layout()
        assert layout.pressure_drop_estimate > 0.0

    def test_cold_runner_warning(self):
        """Warning must state cold-runner scope."""
        layout = self._layout()
        combined = " ".join(layout.warnings).lower()
        assert "cold" in combined or "hot" in combined


# ---------------------------------------------------------------------------
# 4-cavity 2×2 symmetric — should be naturally balanced
# ---------------------------------------------------------------------------

class TestFourCavitySymmetric:
    """
    2×2 grid centred on origin:
      (-30, -30), (30, -30), (-30, 30), (30, 30)
    Sprue at (0, 0).  Equal branch lengths → naturally balanced.
    """

    _CAVS = [
        [-30.0, -30.0],
        [30.0, -30.0],
        [-30.0, 30.0],
        [30.0, 30.0],
    ]
    _SPRUE = [0.0, 0.0]
    _WEIGHTS = [25.0, 25.0, 25.0, 25.0]

    def _layout(self):
        return generate_runner_layout(
            cavity_positions=self._CAVS,
            part_weights=self._WEIGHTS,
            sprue_position=self._SPRUE,
        )

    def test_balance_score_one(self):
        """Symmetric 2×2 grid must achieve balance == 1.0."""
        layout = self._layout()
        assert layout.balance_score == pytest.approx(1.0, abs=1e-4), \
            f"Expected balance=1.0, got {layout.balance_score}"

    def test_naturally_balanced_flag(self):
        layout = self._layout()
        assert layout.naturally_balanced is True

    def test_no_artificial_balance_needed(self):
        layout = self._layout()
        assert layout.artificial_balance_required is False

    def test_four_segments_or_more(self):
        """Tree has at least 4 segments (one per cavity leaf)."""
        layout = self._layout()
        assert len(layout.runner_segments) >= 4

    def test_n_cavities(self):
        layout = self._layout()
        assert layout.n_cavities == 4

    def test_all_diameters_equal(self):
        """Equal weights → all diameters should be the same."""
        layout = self._layout()
        diams = list(layout.diameters.values())
        assert max(diams) - min(diams) < 0.5  # within rounding

    def test_pressure_drop_finite(self):
        layout = self._layout()
        assert math.isfinite(layout.pressure_drop_estimate)
        assert layout.pressure_drop_estimate > 0.0


# ---------------------------------------------------------------------------
# 8-cavity row — artificial balance required
# ---------------------------------------------------------------------------

class TestEightCavityRow:
    """
    8 cavities in a horizontal row: x=[-175, -125, -75, -25, 25, 75, 125, 175], y=0.
    Sprue at (0, 0).
    Spine-and-branch runner → far cavities have longer paths → unbalanced.
    """

    _CAVS = [[x, 0.0] for x in [-175, -125, -75, -25, 25, 75, 125, 175]]
    _SPRUE = [0.0, 0.0]
    _WEIGHTS = [30.0] * 8

    def _layout(self):
        return generate_runner_layout(
            cavity_positions=self._CAVS,
            part_weights=self._WEIGHTS,
            sprue_position=self._SPRUE,
        )

    def test_balance_score_below_one(self):
        """8-cavity row: balance < 1.0 (spine paths from sprue differ)."""
        layout = self._layout()
        assert layout.balance_score < 1.0, \
            f"Expected balance < 1.0 for row layout, got {layout.balance_score}"

    def test_artificial_balance_flagged(self):
        layout = self._layout()
        assert layout.artificial_balance_required is True

    def test_naturally_balanced_false(self):
        layout = self._layout()
        assert layout.naturally_balanced is False

    def test_warning_message_present(self):
        """Warning should mention artificial balance."""
        layout = self._layout()
        combined = " ".join(layout.warnings).lower()
        assert "artificial balance" in combined or "balance" in combined

    def test_n_cavities(self):
        layout = self._layout()
        assert layout.n_cavities == 8

    def test_eight_leaf_segments(self):
        """At least 8 leaf segments (one per cavity)."""
        layout = self._layout()
        assert len(layout.runner_segments) >= 8


# ---------------------------------------------------------------------------
# Mixed weights — diameter sizing variation
# ---------------------------------------------------------------------------

class TestMixedWeights:
    def test_heavier_cavity_gets_larger_runner(self):
        """Cavity with 200 g part weight should get a larger runner than 10 g."""
        d_light = beaumont_runner_diameter(10.0)
        d_heavy = beaumont_runner_diameter(200.0)
        assert d_heavy > d_light

    def test_two_cavity_unequal_weights(self):
        """Two cavities with different weights: layout generates, diameters valid."""
        layout = generate_runner_layout(
            cavity_positions=[[-50.0, 0.0], [50.0, 0.0]],
            part_weights=[10.0, 200.0],
            sprue_position=[0.0, 0.0],
        )
        assert layout.n_cavities == 2
        diams = list(layout.diameters.values())
        assert all(2.0 <= d <= 10.0 for d in diams)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_empty_cavity_positions_raises(self):
        with pytest.raises(ValueError):
            generate_runner_layout([], [10.0], [0.0, 0.0])

    def test_mismatched_weights_raises(self):
        with pytest.raises(ValueError):
            generate_runner_layout([[0, 0], [10, 0]], [10.0], [0.0, 0.0])

    def test_zero_weight_raises(self):
        with pytest.raises(ValueError):
            generate_runner_layout([[10.0, 0.0]], [0.0], [0.0, 0.0])

    def test_mismatched_gate_positions_raises(self):
        with pytest.raises(ValueError):
            generate_runner_layout(
                [[0, 0], [10, 0]],
                [10.0, 10.0],
                [0.0, 0.0],
                gate_positions=[[0, 0]],  # only 1 gate for 2 cavities
            )


# ---------------------------------------------------------------------------
# LLM tool round-trip
# ---------------------------------------------------------------------------

class TestRunnerLayoutTool:
    def test_basic_four_cavity(self):
        from kerf_mold.runner_layout_tool import run_mold_generate_runner_layout

        args = {
            "cavity_positions": [[-30, -30], [30, -30], [-30, 30], [30, 30]],
            "part_weights": [25.0, 25.0, 25.0, 25.0],
            "sprue_position": [0.0, 0.0],
        }
        result = json.loads(_run(run_mold_generate_runner_layout(args, CTX)))
        assert result.get("ok") is True
        assert result["n_cavities"] == 4
        assert result["balance_score"] == pytest.approx(1.0, abs=1e-4)
        assert result["naturally_balanced"] is True
        assert result["artificial_balance_required"] is False
        assert len(result["runner_segments"]) >= 4

    def test_eight_cavity_row_flagged(self):
        from kerf_mold.runner_layout_tool import run_mold_generate_runner_layout

        args = {
            "cavity_positions": [[x, 0] for x in [-175, -125, -75, -25, 25, 75, 125, 175]],
            "part_weights": [30.0] * 8,
            "sprue_position": [0.0, 0.0],
        }
        result = json.loads(_run(run_mold_generate_runner_layout(args, CTX)))
        assert result.get("ok") is True
        assert result["balance_score"] < 1.0
        assert result["artificial_balance_required"] is True

    def test_single_cavity(self):
        from kerf_mold.runner_layout_tool import run_mold_generate_runner_layout

        args = {
            "cavity_positions": [[50.0, 0.0]],
            "part_weights": [15.0],
            "sprue_position": [0.0, 0.0],
        }
        result = json.loads(_run(run_mold_generate_runner_layout(args, CTX)))
        assert result.get("ok") is True
        assert result["balance_score"] == 1.0

    def test_missing_cavity_positions_returns_error(self):
        from kerf_mold.runner_layout_tool import run_mold_generate_runner_layout

        args = {
            "part_weights": [10.0],
            "sprue_position": [0.0, 0.0],
        }
        result = json.loads(_run(run_mold_generate_runner_layout(args, CTX)))
        assert result.get("ok") is not True
        assert "error" in result

    def test_response_includes_reference(self):
        from kerf_mold.runner_layout_tool import run_mold_generate_runner_layout

        args = {
            "cavity_positions": [[0, 0]],
            "part_weights": [10.0],
            "sprue_position": [0.0, 0.0],
        }
        result = json.loads(_run(run_mold_generate_runner_layout(args, CTX)))
        assert "Beaumont" in result.get("reference", "")

    def test_cold_runner_warning_present(self):
        from kerf_mold.runner_layout_tool import run_mold_generate_runner_layout

        args = {
            "cavity_positions": [[30, 0]],
            "part_weights": [20.0],
            "sprue_position": [0.0, 0.0],
        }
        result = json.loads(_run(run_mold_generate_runner_layout(args, CTX)))
        warnings_text = " ".join(result.get("warnings", [])).lower()
        assert "cold" in warnings_text or "hot" in warnings_text

    def test_plugin_registration(self):
        """mold_generate_runner_layout is registered by plugin.register()."""
        from kerf_mold.plugin import register
        from fastapi import FastAPI

        class _MockReg:
            def __init__(self):
                self.registered = {}
            def register(self, name, spec, handler):
                self.registered[name] = (spec, handler)

        class _MockCtx:
            def __init__(self):
                self.tools = _MockReg()

        app = FastAPI()
        ctx = _MockCtx()
        _run(register(app, ctx))
        assert "mold_generate_runner_layout" in ctx.tools.registered
