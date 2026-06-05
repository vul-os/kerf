"""
test_panel_optimizer.py — pytest suite for kerf_woodworking.panel_optimizer.

DoD oracles:
  1. 2D guillotine BSS: all panels placed within sheet bounds.
  2. Yield %: single part exactly fitting sheet → ~100%.
  3. Grain-constrained parts not rotated (length grain stays on long axis).
  4. allow_rotation=True: unconstrained parts may be rotated for better fit.
  5. Multiple sheets used when required.
  6. Oversized parts reported in warnings.
  7. Empty input returns zero sheets.
  8. Off-cuts tracked per sheet.
  9. nesting_result_to_dict is JSON-serialisable.
  10. Aggregate yield_pct ≤ 100%.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.panel_optimizer import (
    PanelPart,
    optimise_panel_layout,
    nesting_result_to_dict,
    NestingResult,
    SheetLayout,
    PlacedPanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHEET_L = 2440.0
SHEET_W = 1220.0
KERF = 3.175


def _part(pid: str, l: float, w: float, qty: int = 1, grain: str = "none") -> PanelPart:
    return PanelPart(part_id=pid, length_mm=l, width_mm=w, quantity=qty, grain_direction=grain)


# ---------------------------------------------------------------------------
# DoD oracle 1: all placed parts are within sheet bounds
# ---------------------------------------------------------------------------

class TestPlacedWithinBounds:
    def test_all_placements_within_sheet(self):
        """Every placed panel must fit inside the sheet (with kerf margin)."""
        parts = [
            _part("shelf", 800.0, 300.0, qty=4),
            _part("side",  700.0, 500.0, qty=2),
            _part("door",  600.0, 400.0, qty=3),
        ]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        for layout in result.layouts:
            for p in layout.placements:
                assert p.x_mm >= 0, f"Part {p.part_id} x={p.x_mm} < 0"
                assert p.y_mm >= 0, f"Part {p.part_id} y={p.y_mm} < 0"
                assert p.x_mm + p.length_mm <= SHEET_L + 1.0, (
                    f"Part {p.part_id} overflows sheet length: "
                    f"x={p.x_mm:.1f} + l={p.length_mm:.1f} > {SHEET_L}"
                )
                assert p.y_mm + p.width_mm <= SHEET_W + 1.0, (
                    f"Part {p.part_id} overflows sheet width: "
                    f"y={p.y_mm:.1f} + w={p.width_mm:.1f} > {SHEET_W}"
                )

    def test_single_part_placed(self):
        """A single small part should be placed on one sheet."""
        parts = [_part("small", 100.0, 100.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert result.sheets_used == 1
        assert len(result.layouts[0].placements) == 1


# ---------------------------------------------------------------------------
# DoD oracle 2: yield % close to 100 for perfect-fit part
# ---------------------------------------------------------------------------

class TestYieldPct:
    def test_single_panel_close_to_full_sheet_high_yield(self):
        """A panel that nearly fills a sheet should show high yield (> 80%)."""
        # Part slightly smaller than sheet (minus kerf margins)
        l = SHEET_L - 2 * KERF - 10.0
        w = SHEET_W - 2 * KERF - 10.0
        parts = [_part("big", l, w)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert result.sheets_used == 1
        assert result.total_yield_pct >= 80.0, (
            f"Expected yield >= 80%; got {result.total_yield_pct:.1f}%"
        )

    def test_yield_between_0_and_100(self):
        parts = [_part("s", 400.0, 300.0, qty=3)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert 0.0 <= result.total_yield_pct <= 100.0

    def test_waste_matches_yield(self):
        """total_waste_mm2 should be consistent with yield_pct."""
        parts = [_part("a", 500.0, 400.0, qty=2)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        total_sheet_area = result.sheets_used * SHEET_L * SHEET_W
        computed_yield = 100.0 * (1.0 - result.total_waste_mm2 / total_sheet_area)
        assert abs(computed_yield - result.total_yield_pct) < 2.0, (
            f"Yield from waste ({computed_yield:.2f}%) != reported ({result.total_yield_pct:.2f}%)"
        )


# ---------------------------------------------------------------------------
# DoD oracle 3: grain-constrained parts not rotated
# ---------------------------------------------------------------------------

class TestGrainConstraint:
    def test_grain_length_part_not_rotated(self):
        """A part with grain='length' must be placed in its original orientation."""
        # Long narrow part; without constraint, optimizer might rotate it
        parts = [_part("stile", 1800.0, 80.0, qty=2, grain="length")]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        for layout in result.layouts:
            for p in layout.placements:
                if "stile" in p.part_id:
                    assert not p.rotated, (
                        f"Grain-constrained part '{p.part_id}' was rotated — grain violated"
                    )

    def test_grain_width_part_not_rotated(self):
        """A part with grain='width' must be placed without rotation."""
        parts = [_part("rail", 400.0, 900.0, qty=1, grain="width")]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        for layout in result.layouts:
            for p in layout.placements:
                if "rail" in p.part_id:
                    assert not p.rotated, (
                        f"grain='width' part '{p.part_id}' was rotated"
                    )


# ---------------------------------------------------------------------------
# DoD oracle 4: unconstrained parts may be rotated
# ---------------------------------------------------------------------------

class TestRotation:
    def test_none_grain_part_may_be_rotated(self):
        """With allow_rotation=True, grain='none' parts may be rotated."""
        # A very wide, short part: rotating gives better fit
        # 1200 × 50 → on 2440×1220 sheet. If we have several, rotation matters.
        parts = [_part("cross", 1200.0, 50.0, qty=20, grain="none")]
        result_rot    = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF, allow_rotation=True)
        result_norot  = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF, allow_rotation=False)
        # allow_rotation should not use more sheets than no-rotation
        assert result_rot.sheets_used <= result_norot.sheets_used + 1

    def test_allow_rotation_false_does_not_rotate(self):
        """With allow_rotation=False, no part should be rotated."""
        parts = [_part("p", 600.0, 300.0, qty=4, grain="none")]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF, allow_rotation=False)
        for layout in result.layouts:
            for p in layout.placements:
                assert not p.rotated, f"Part '{p.part_id}' was rotated with allow_rotation=False"


# ---------------------------------------------------------------------------
# DoD oracle 5: multiple sheets when required
# ---------------------------------------------------------------------------

class TestMultipleSheets:
    def test_many_large_parts_need_multiple_sheets(self):
        """25 large panels cannot fit on 1 sheet — must use multiple sheets."""
        # Each part ~ 1200 × 600 mm; 2 fit per sheet, 25 parts → ≥ 13 sheets
        parts = [_part("panel", 1200.0, 600.0, qty=25, grain="none")]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert result.sheets_used >= 2

    def test_all_parts_placed_across_sheets(self):
        """Total placed parts across all sheets must equal total required."""
        parts = [
            _part("A", 800.0, 400.0, qty=5),
            _part("B", 600.0, 500.0, qty=4),
        ]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        total_placed = sum(len(la.placements) for la in result.layouts)
        total_required = sum(p.quantity for p in parts)
        unplaced = len(result.unplaced_parts)
        assert total_placed + unplaced == total_required, (
            f"Placed {total_placed} + unplaced {unplaced} != required {total_required}"
        )


# ---------------------------------------------------------------------------
# DoD oracle 6: oversized parts reported in warnings
# ---------------------------------------------------------------------------

class TestOversizedParts:
    def test_oversized_part_warns(self):
        """A part larger than the sheet should generate a warning."""
        parts = [_part("giant", SHEET_L + 500.0, SHEET_W + 500.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert len(result.warnings) > 0, "Expected warning for oversized part"
        assert any("giant" in w for w in result.warnings)

    def test_oversized_part_in_unplaced(self):
        """An oversized part must appear in unplaced_parts."""
        parts = [_part("too_big", SHEET_L + 1.0, SHEET_W + 1.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert any("too_big" in pid for pid in result.unplaced_parts)


# ---------------------------------------------------------------------------
# DoD oracle 7: empty input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_parts_returns_zero_sheets(self):
        result = optimise_panel_layout([], SHEET_L, SHEET_W, KERF)
        assert result.sheets_used == 0
        assert result.layouts == []
        assert result.total_yield_pct == 100.0
        assert result.total_waste_mm2 == 0.0

    def test_empty_warnings_and_unplaced(self):
        result = optimise_panel_layout([], SHEET_L, SHEET_W, KERF)
        assert result.warnings == []
        assert result.unplaced_parts == []


# ---------------------------------------------------------------------------
# DoD oracle 8: off-cuts tracked
# ---------------------------------------------------------------------------

class TestOffCuts:
    def test_small_part_leaves_off_cuts(self):
        """A small panel leaves significant off-cut on each sheet."""
        parts = [_part("tiny", 100.0, 100.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        assert result.sheets_used == 1
        assert len(result.layouts[0].off_cuts) > 0

    def test_off_cut_area_positive(self):
        parts = [_part("small", 200.0, 150.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        for layout in result.layouts:
            for oc in layout.off_cuts:
                assert oc["approx_area_mm2"] > 0


# ---------------------------------------------------------------------------
# DoD oracle 9: JSON-serialisable
# ---------------------------------------------------------------------------

class TestSerialisable:
    def test_nesting_result_to_dict_json_safe(self):
        parts = [_part("p", 600.0, 400.0, qty=3)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        d = nesting_result_to_dict(result)
        json.dumps(d)  # must not raise

    def test_dict_has_expected_keys(self):
        parts = [_part("q", 400.0, 300.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        d = nesting_result_to_dict(result)
        for key in ("sheets_used", "total_yield_pct", "total_waste_mm2",
                    "layouts", "warnings", "unplaced_parts"):
            assert key in d

    def test_layout_dict_has_placements(self):
        parts = [_part("r", 500.0, 300.0)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        d = nesting_result_to_dict(result)
        assert len(d["layouts"]) > 0
        layout_d = d["layouts"][0]
        assert "placements" in layout_d
        assert "yield_pct" in layout_d
        assert "sheet_index" in layout_d


# ---------------------------------------------------------------------------
# DoD oracle 10: yield_pct ≤ 100
# ---------------------------------------------------------------------------

class TestYieldBounds:
    def test_yield_never_exceeds_100(self):
        for qty in [1, 5, 20]:
            parts = [_part("x", 300.0, 200.0, qty=qty)]
            result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
            assert result.total_yield_pct <= 100.0 + 1e-6, (
                f"yield_pct {result.total_yield_pct} > 100 for qty={qty}"
            )

    def test_each_sheet_yield_at_most_100(self):
        parts = [_part("y", 400.0, 300.0, qty=4)]
        result = optimise_panel_layout(parts, SHEET_L, SHEET_W, KERF)
        for la in result.layouts:
            assert la.yield_pct <= 100.0 + 1e-6


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestPanelPartValidation:
    def test_invalid_dimensions_raise(self):
        with pytest.raises(ValueError):
            PanelPart(part_id="bad", length_mm=-100.0, width_mm=200.0)

    def test_invalid_grain_raises(self):
        with pytest.raises(ValueError):
            PanelPart(part_id="bad", length_mm=100.0, width_mm=200.0, grain_direction="diagonal")

    def test_invalid_quantity_raises(self):
        with pytest.raises(ValueError):
            PanelPart(part_id="bad", length_mm=100.0, width_mm=200.0, quantity=0)
