"""
test_grain_direction.py — pytest suite for kerf_woodworking.grain_direction.

DoD coverage:
  1.  select_grain_direction('door_stile') → 'length'.
  2.  select_grain_direction('door_rail') → 'length'.
  3.  select_grain_direction('door_panel') → 'length'.
  4.  select_grain_direction('table_top') → 'length'.
  5.  select_grain_direction('shelf') → 'length'.
  6.  select_grain_direction('back_panel') → 'none'.
  7.  select_grain_direction('mdf_panel') → 'none'.
  8.  grain_match_panels with book_match returns paired panels.
  9.  grain_match_panels with slip_match returns paired panels.
  10. grain_match_panels with 1 panel returns empty list (no pair possible).
  11. figure_type_properties returns movement_rating for plain_sawn.
  12. Unknown part_kind returns default direction 'length'.
  13. grain_match_panels with odd count returns floor(n/2) pairs.

References: Hoadley (2000); Stanley (2010); KCMA 2021.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.grain_direction import (
    FigureType,
    FigureIntensity,
    GrainPattern,
    select_grain_direction,
    grain_match_panels,
    figure_type_properties,
    SPECIES_PROPERTIES,
)
from kerf_woodworking.cabinet_cut_list import CutListItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(part_id: str, grain_direction: str = "length") -> CutListItem:
    return CutListItem(
        part_id=part_id,
        material='oak_3/4"',
        length_mm=762.0,
        width_mm=300.0,
        thickness_mm=19.05,
        grain_direction=grain_direction,
        count=1,
        edge_banding="none",
    )


# ---------------------------------------------------------------------------
# Test 1–7: select_grain_direction
# ---------------------------------------------------------------------------

class TestSelectGrainDirection:
    # --- Test 1: door_stile → length ---
    def test_door_stile_is_length(self):
        """Door stile grain runs along the long axis (structural)."""
        assert select_grain_direction("door_stile") == "length"

    # --- Test 2: door_rail → length ---
    def test_door_rail_is_length(self):
        """Door rail grain runs along the long axis."""
        assert select_grain_direction("door_rail") == "length"

    # --- Test 3: door_panel → length ---
    def test_door_panel_is_length(self):
        """Door panel grain is vertical (length) when door is hung."""
        assert select_grain_direction("door_panel") == "length"

    # --- Test 4: table_top → length ---
    def test_table_top_is_length(self):
        """Table top grain runs along table length for structural stiffness."""
        assert select_grain_direction("table_top") == "length"

    # --- Test 5: shelf → length ---
    def test_shelf_is_length(self):
        """Shelf grain runs along span for bending resistance."""
        assert select_grain_direction("shelf") == "length"

    # --- Test 6: back_panel → none ---
    def test_back_panel_is_none(self):
        """Back panel (plywood) has no preferred grain direction."""
        assert select_grain_direction("back_panel") == "none"

    # --- Test 7: mdf_panel → none ---
    def test_mdf_panel_is_none(self):
        """MDF is isotropic — no grain direction."""
        assert select_grain_direction("mdf_panel") == "none"

    # --- Test 12: Unknown part kind → default 'length' ---
    def test_unknown_part_kind_defaults_to_length(self):
        """Unknown part kind should return default 'length' (conservative)."""
        direction = select_grain_direction("xyzzy_unknown_part_42")
        assert direction == "length"

    def test_drawer_front_is_length(self):
        """Drawer front grain runs horizontally (length direction)."""
        assert select_grain_direction("drawer_front") == "length"

    def test_case_insensitive(self):
        """Part kind lookup should be case-insensitive."""
        assert select_grain_direction("Door_Stile") == "length"
        assert select_grain_direction("TABLE_TOP") == "length"


# ---------------------------------------------------------------------------
# Test 8–10 & 13: grain_match_panels
# ---------------------------------------------------------------------------

class TestGrainMatchPanels:
    # --- Test 8: book_match returns pairs ---
    def test_book_match_returns_pairs(self):
        """book_match with 4 panels should return 2 pairs."""
        panels = [_make_panel(f"P{i}") for i in range(4)]
        pairs = grain_match_panels(panels, match_kind="book_match")
        assert len(pairs) == 2
        for pa, pb in pairs:
            assert pa != pb

    # --- Test 9: slip_match returns pairs ---
    def test_slip_match_returns_pairs(self):
        """slip_match with 4 panels should return 2 pairs."""
        panels = [_make_panel(f"P{i}") for i in range(4)]
        pairs = grain_match_panels(panels, match_kind="slip_match")
        assert len(pairs) == 2

    # --- Test 10: Single panel → empty list ---
    def test_single_panel_no_pair(self):
        """1 panel cannot form a pair — should return empty list."""
        panels = [_make_panel("P0")]
        pairs = grain_match_panels(panels)
        assert pairs == []

    # --- Test 13: Odd count returns floor(n/2) pairs ---
    def test_odd_count_panels(self):
        """5 panels → 2 pairs (one leftover)."""
        panels = [_make_panel(f"P{i}") for i in range(5)]
        pairs = grain_match_panels(panels, match_kind="book_match")
        assert len(pairs) == 2   # floor(5/2) = 2

    def test_panels_with_none_grain_excluded(self):
        """Panels with grain_direction='none' should not be matched."""
        panels = [
            _make_panel("P0", "length"),
            _make_panel("P1", "none"),    # excluded
            _make_panel("P2", "length"),
            _make_panel("P3", "length"),
        ]
        pairs = grain_match_panels(panels)
        # 3 matchable panels (P0, P2, P3) → 1 pair
        assert len(pairs) == 1

    def test_invalid_match_kind_raises(self):
        """Invalid match_kind should raise ValueError."""
        panels = [_make_panel("P0"), _make_panel("P1")]
        with pytest.raises(ValueError, match="match_kind"):
            grain_match_panels(panels, match_kind="invalid_kind")

    def test_random_match_returns_pairs(self):
        """random match with 6 panels → 3 pairs."""
        panels = [_make_panel(f"P{i}") for i in range(6)]
        pairs = grain_match_panels(panels, match_kind="random")
        assert len(pairs) == 3


# ---------------------------------------------------------------------------
# Test 11: figure_type_properties
# ---------------------------------------------------------------------------

class TestFigureTypeProperties:
    # --- Test 11: plain_sawn properties ---
    def test_plain_sawn_has_movement_rating(self):
        """plain_sawn figure should have movement_rating."""
        props = figure_type_properties(FigureType.PLAIN_SAWN)
        assert "movement_rating" in props
        assert props["movement_rating"] == "high"

    def test_quarter_sawn_stability(self):
        """quarter_sawn should have highest stability rating."""
        props = figure_type_properties(FigureType.QUARTER_SAWN)
        assert "stability" in props
        assert "highest" in props["stability"].lower()

    def test_rift_sawn_notes_mention_hoadley(self):
        """rift_sawn notes should reference Hoadley (2000)."""
        props = figure_type_properties(FigureType.RIFT_SAWN)
        assert "Hoadley" in props.get("notes", "")

    def test_unknown_figure_type_returns_dict(self):
        """Unknown figure type should return a dict, not raise."""
        props = figure_type_properties("unknown_figure")
        assert isinstance(props, dict)
        assert "movement_rating" in props


# ---------------------------------------------------------------------------
# GrainPattern dataclass
# ---------------------------------------------------------------------------

class TestGrainPattern:
    def test_grain_pattern_instantiation(self):
        """GrainPattern must instantiate with all fields."""
        gp = GrainPattern(
            species="red_oak",
            figure_type=FigureType.QUARTER_SAWN,
            figure_intensity=FigureIntensity.PRONOUNCED,
            movement_rating="low",
            notes="Quarter-sawn oak with visible ray fleck.",
        )
        assert gp.species == "red_oak"
        assert gp.figure_type == FigureType.QUARTER_SAWN
        assert gp.figure_intensity == FigureIntensity.PRONOUNCED

    def test_species_properties_known_species(self):
        """SPECIES_PROPERTIES should include red_oak, walnut, maple_hard."""
        for species in ("red_oak", "walnut", "maple_hard"):
            assert species in SPECIES_PROPERTIES, f"Missing species: {species}"
