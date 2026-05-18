"""
Tests for T-113: structural grid + framing.

DoD: a 3-bay × 2-storey frame snaps to a grid + IFC-exports correctly.
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.grid import (
    GridAxis,
    StructuralGrid,
    GridValidationError,
    make_grid,
    make_regular_grid,
    grid_to_ifc_dict,
)
from kerf_bim.framing import (
    ColumnMember,
    BeamMember,
    ConnectionNode,
    RebarAttachment,
    FramingLayout,
    FramingValidationError,
    make_column_at,
    make_beam_between,
    make_frame_on_grid,
    framing_to_ifc_dict,
)


# =============================================================================
# Grid
# =============================================================================

class TestGridAxis:
    def test_basic_axis(self):
        a = GridAxis(name="A", coordinate=0.0)
        assert a.name == "A"
        assert a.coordinate == 0.0

    def test_empty_name_raises(self):
        with pytest.raises(GridValidationError):
            GridAxis(name="", coordinate=0.0)


class TestStructuralGrid:
    def _make_3x2_grid(self) -> StructuralGrid:
        return make_regular_grid(
            name="Main Grid",
            bays_x=3, bay_width=7200.0,
            bays_y=2, bay_depth=6000.0,
        )

    def test_column_axis_count(self):
        grid = self._make_3x2_grid()
        assert len(grid.column_axes) == 4   # A, B, C, D

    def test_row_axis_count(self):
        grid = self._make_3x2_grid()
        assert len(grid.row_axes) == 3      # 1, 2, 3

    def test_intersection_count(self):
        grid = self._make_3x2_grid()
        intersections = grid.intersections()
        assert len(intersections) == 4 * 3  # 12 intersections

    def test_column_labels(self):
        grid = self._make_3x2_grid()
        labels = [a.name for a in grid.column_axes]
        assert "A" in labels and "B" in labels and "C" in labels and "D" in labels

    def test_row_labels(self):
        grid = self._make_3x2_grid()
        labels = [a.name for a in grid.row_axes]
        assert "1" in labels and "2" in labels and "3" in labels

    def test_intersection_coordinates(self):
        grid = self._make_3x2_grid()
        x, y = grid.intersection("B", "2")
        assert abs(x - 7200.0) < 1e-6   # B is at x=7200
        assert abs(y - 6000.0) < 1e-6   # row 2 is at y=6000

    def test_intersection_origin_applied(self):
        grid = make_regular_grid(
            bays_x=2, bay_width=6000.0, bays_y=1, bay_depth=6000.0,
            origin=[1000.0, 2000.0],
        )
        x, y = grid.intersection("A", "1")
        assert abs(x - 1000.0) < 1e-6
        assert abs(y - 2000.0) < 1e-6

    def test_missing_col_axis_raises(self):
        grid = self._make_3x2_grid()
        with pytest.raises(GridValidationError):
            grid.intersection("Z", "1")

    def test_missing_row_axis_raises(self):
        grid = self._make_3x2_grid()
        with pytest.raises(GridValidationError):
            grid.intersection("A", "99")

    def test_bay_widths(self):
        grid = self._make_3x2_grid()
        widths = grid.bay_widths
        assert len(widths) == 3
        for w in widths:
            assert abs(w - 7200.0) < 1e-6

    def test_bay_depths(self):
        grid = self._make_3x2_grid()
        depths = grid.bay_depths
        assert len(depths) == 2
        for d in depths:
            assert abs(d - 6000.0) < 1e-6

    def test_axis_names(self):
        grid = self._make_3x2_grid()
        names = grid.axis_names()
        assert "columns" in names and "rows" in names
        assert len(names["columns"]) == 4
        assert len(names["rows"]) == 3

    def test_irregular_grid(self):
        grid = make_grid(
            "Irregular",
            column_positions=[("A", 0), ("B", 5000), ("C", 11000)],
            row_positions=[("1", 0), ("2", 7200)],
        )
        x, y = grid.intersection("C", "2")
        assert abs(x - 11000.0) < 1e-6
        assert abs(y - 7200.0) < 1e-6

    def test_grid_ifc_dict_keys(self):
        grid = self._make_3x2_grid()
        d = grid_to_ifc_dict(grid)
        for key in ("kind", "name", "origin", "rotation_deg",
                    "column_axes", "row_axes", "intersections"):
            assert key in d

    def test_grid_ifc_dict_kind(self):
        grid = self._make_3x2_grid()
        assert grid_to_ifc_dict(grid)["kind"] == "grid"

    def test_grid_ifc_intersection_count(self):
        grid = self._make_3x2_grid()
        d = grid_to_ifc_dict(grid)
        assert len(d["intersections"]) == 12


# =============================================================================
# Framing — columns and beams
# =============================================================================

class TestColumnMember:
    def _grid(self) -> StructuralGrid:
        return make_regular_grid(bays_x=3, bay_width=7200, bays_y=2, bay_depth=6000)

    def test_make_column_at(self):
        grid = self._grid()
        col = make_column_at(grid, "A", "1")
        assert col.x == pytest.approx(0.0)
        assert col.y == pytest.approx(0.0)

    def test_column_at_b2(self):
        grid = self._grid()
        col = make_column_at(grid, "B", "2")
        assert col.x == pytest.approx(7200.0)
        assert col.y == pytest.approx(6000.0)

    def test_invalid_axis_raises(self):
        grid = self._grid()
        with pytest.raises(FramingValidationError):
            make_column_at(grid, "Z", "1")

    def test_column_attributes(self):
        grid = self._grid()
        col = make_column_at(grid, "A", "1", height_mm=3600.0, section="W250x73")
        assert col.height_mm == pytest.approx(3600.0)
        assert col.section == "W250x73"


class TestBeamMember:
    def _grid(self) -> StructuralGrid:
        return make_regular_grid(bays_x=3, bay_width=7200, bays_y=2, bay_depth=6000)

    def test_make_beam_between(self):
        grid = self._grid()
        bm = make_beam_between(grid, "A", "1", "B", "1", level_z_mm=3600.0)
        assert abs(bm.length_mm - 7200.0) < 1e-6

    def test_beam_y_direction(self):
        grid = self._grid()
        bm = make_beam_between(grid, "A", "1", "A", "2", level_z_mm=3600.0)
        assert abs(bm.length_mm - 6000.0) < 1e-6

    def test_invalid_axis_raises(self):
        grid = self._grid()
        with pytest.raises(FramingValidationError):
            make_beam_between(grid, "Z", "1", "A", "1")


# =============================================================================
# T-113 DoD: 3-bay × 2-storey frame
# =============================================================================

class TestFrameOnGrid:
    def _3bay_2storey(self) -> FramingLayout:
        grid = make_regular_grid(
            name="3-bay Grid",
            bays_x=3, bay_width=7200.0,
            bays_y=2, bay_depth=6000.0,
        )
        return make_frame_on_grid(grid, storey_heights=[3600.0, 3600.0])

    def test_column_count(self):
        """3-bay × 2-storey: 4×3 = 12 intersections × 2 storeys = 24 columns."""
        layout = self._3bay_2storey()
        assert len(layout.columns) == 24

    def test_beam_count(self):
        """Per storey: 3 X-bays × 3 rows = 9 X-beams; 2 Y-bays × 4 cols = 8 Y-beams.
        Total per storey = 17; × 2 storeys = 34."""
        layout = self._3bay_2storey()
        assert len(layout.beams) == 34

    def test_connection_count(self):
        layout = self._3bay_2storey()
        assert len(layout.connections) == len(layout.columns)

    def test_column_snapped_to_grid(self):
        """Every column x,y must match a grid intersection."""
        grid = make_regular_grid(bays_x=3, bay_width=7200.0, bays_y=2, bay_depth=6000.0)
        layout = make_frame_on_grid(grid, storey_heights=[3600.0])
        valid_xs = {0.0, 7200.0, 14400.0, 21600.0}
        valid_ys = {0.0, 6000.0, 12000.0}
        for col in layout.columns:
            assert col.x in valid_xs, f"Column x={col.x} not on grid"
            assert col.y in valid_ys, f"Column y={col.y} not on grid"

    def test_beam_connects_adjacent_columns(self):
        """Every X-beam must span exactly one bay width."""
        grid = make_regular_grid(bays_x=3, bay_width=7200.0, bays_y=2, bay_depth=6000.0)
        layout = make_frame_on_grid(grid, storey_heights=[3600.0])
        x_beams = [bm for bm in layout.beams if "X" in bm.id]
        for bm in x_beams:
            assert abs(bm.length_mm - 7200.0) < 1e-6

    def test_ifc_dict_keys(self):
        layout = self._3bay_2storey()
        d = framing_to_ifc_dict(layout)
        for key in ("kind", "name", "grid", "columns", "beams", "connections"):
            assert key in d

    def test_ifc_dict_kind(self):
        layout = self._3bay_2storey()
        assert framing_to_ifc_dict(layout)["kind"] == "framing"

    def test_ifc_dict_column_keys(self):
        layout = self._3bay_2storey()
        d = framing_to_ifc_dict(layout)
        for col_d in d["columns"]:
            for key in ("name", "level", "position", "width",
                        "depth", "height", "section", "material"):
                assert key in col_d, f"Missing key '{key}' in column dict"

    def test_ifc_dict_beam_keys(self):
        layout = self._3bay_2storey()
        d = framing_to_ifc_dict(layout)
        for bm_d in d["beams"]:
            for key in ("name", "level", "start", "end",
                        "width", "height", "section", "material"):
                assert key in bm_d, f"Missing key '{key}' in beam dict"

    def test_storey_heights(self):
        """Column heights match the specified storey heights."""
        grid = make_regular_grid(bays_x=2, bay_width=6000.0, bays_y=1, bay_depth=6000.0)
        layout = make_frame_on_grid(grid, storey_heights=[3000.0, 4000.0])
        s1_cols = [c for c in layout.columns if c.base_level == "L1"]
        s2_cols = [c for c in layout.columns if c.base_level == "L2"]
        for c in s1_cols:
            assert abs(c.height_mm - 3000.0) < 1e-6
        for c in s2_cols:
            assert abs(c.height_mm - 4000.0) < 1e-6

    def test_no_storeys_raises(self):
        grid = make_regular_grid(bays_x=2, bay_width=6000.0, bays_y=1, bay_depth=6000.0)
        with pytest.raises(FramingValidationError):
            make_frame_on_grid(grid, storey_heights=[])


# =============================================================================
# Rebar attachment
# =============================================================================

class TestRebarAttachment:
    def test_designation(self):
        r = RebarAttachment(bar_count=8, bar_diameter_mm=20.0, tie_spacing_mm=200.0)
        assert "8" in r.designation()
        assert "20" in r.designation()

    def test_column_with_rebar(self):
        grid = make_regular_grid(bays_x=1, bay_width=6000.0, bays_y=1, bay_depth=6000.0)
        rebar = RebarAttachment(bar_count=8, bar_diameter_mm=20.0)
        col = make_column_at(
            grid, "A", "1",
            section="400×400", material="concrete_reinforced",
            width_mm=400.0, depth_mm=400.0,
        )
        col.rebar = rebar
        assert col.rebar is not None
        d = framing_to_ifc_dict(FramingLayout(
            name="Test", grid=grid, columns=[col], beams=[], connections=[]
        ))
        col_d = d["columns"][0]
        assert col_d["rebar"] is not None
        assert "T20" in col_d["rebar"]
