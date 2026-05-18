"""test_liberty.py — pytest suite for kerf_silicon.liberty.

Run with:
    PYTHONPATH=packages/kerf-core/src:packages/kerf-silicon/src \
        python3 -m pytest packages/kerf-silicon/tests/test_liberty.py -x
"""
from __future__ import annotations

import os
import pathlib

import pytest

from kerf_silicon.liberty import (
    LibertyLibrary,
    Cell,
    Pin,
    TimingArc,
    LUTable,
    parse,
    parse_file,
)
from kerf_silicon.liberty.parser import ParseError

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
INV1_LIB = FIXTURES / "inv_1.lib"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pin(cell: Cell, name: str) -> Pin:
    for p in cell.pins:
        if p.name == name:
            return p
    raise KeyError(f"pin {name!r} not found in cell {cell.name!r}")


# ---------------------------------------------------------------------------
# Fixture: round-trip parse
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def inv1() -> LibertyLibrary:
    return parse_file(INV1_LIB)


# ---------------------------------------------------------------------------
# Top-level library
# ---------------------------------------------------------------------------

class TestLibrary:
    def test_returns_liberty_library(self, inv1):
        assert isinstance(inv1, LibertyLibrary)

    def test_library_name(self, inv1):
        assert inv1.name == "sky130_fd_sc_hd__tt_025C_1v80"

    def test_library_has_one_cell(self, inv1):
        assert len(inv1.cells) == 1

    def test_library_pos_recorded(self, inv1):
        # line is zero-based; library keyword starts on a non-zero line
        assert inv1.pos is not None
        assert inv1.pos.line >= 0
        assert inv1.pos.col >= 0

    def test_operating_conditions_parsed(self, inv1):
        assert len(inv1.operating_conditions) == 1
        oc = inv1.operating_conditions[0]
        assert oc.name == "sky130_fd_sc_hd__tt_025C_1v80"
        assert oc.process == pytest.approx(1.0)
        assert oc.temperature == pytest.approx(25.0)
        assert oc.voltage == pytest.approx(1.8)

    def test_lu_table_template_parsed(self, inv1):
        assert len(inv1.lu_table_templates) == 1
        tmpl = inv1.lu_table_templates[0]
        assert tmpl.name == "delay_template"
        assert tmpl.variable_1 == "input_net_transition"
        assert tmpl.variable_2 == "total_output_net_capacitance"


# ---------------------------------------------------------------------------
# Cell
# ---------------------------------------------------------------------------

class TestCell:
    def test_cell_name(self, inv1):
        cell = inv1.cells[0]
        assert cell.name == "sky130_fd_sc_hd__inv_1"

    def test_cell_area(self, inv1):
        cell = inv1.cells[0]
        assert cell.area == pytest.approx(4.6)

    def test_cell_leakage_power(self, inv1):
        cell = inv1.cells[0]
        assert cell.cell_leakage_power == pytest.approx(0.00314)

    def test_cell_has_two_pins(self, inv1):
        cell = inv1.cells[0]
        assert len(cell.pins) == 2

    def test_cell_pos_recorded(self, inv1):
        cell = inv1.cells[0]
        assert cell.pos is not None

    def test_cell_timing_arcs_flat_view(self, inv1):
        cell = inv1.cells[0]
        arcs = cell.timing_arcs
        assert len(arcs) == 1  # only pin Y has a timing arc


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

class TestPins:
    def test_pin_a_exists(self, inv1):
        cell = inv1.cells[0]
        pin_a = _get_pin(cell, "A")
        assert pin_a is not None

    def test_pin_a_direction_input(self, inv1):
        cell = inv1.cells[0]
        pin_a = _get_pin(cell, "A")
        assert pin_a.direction == "input"

    def test_pin_a_capacitance(self, inv1):
        cell = inv1.cells[0]
        pin_a = _get_pin(cell, "A")
        assert pin_a.capacitance == pytest.approx(0.0023)

    def test_pin_y_exists(self, inv1):
        cell = inv1.cells[0]
        pin_y = _get_pin(cell, "Y")
        assert pin_y is not None

    def test_pin_y_direction_output(self, inv1):
        cell = inv1.cells[0]
        pin_y = _get_pin(cell, "Y")
        assert pin_y.direction == "output"

    def test_pin_y_function(self, inv1):
        cell = inv1.cells[0]
        pin_y = _get_pin(cell, "Y")
        assert pin_y.function == "!A"

    def test_pin_y_has_one_timing_arc(self, inv1):
        cell = inv1.cells[0]
        pin_y = _get_pin(cell, "Y")
        assert len(pin_y.timing_arcs) == 1

    def test_pin_pos_recorded(self, inv1):
        cell = inv1.cells[0]
        pin_a = _get_pin(cell, "A")
        assert pin_a.pos is not None


# ---------------------------------------------------------------------------
# Timing arcs
# ---------------------------------------------------------------------------

class TestTimingArc:
    @pytest.fixture
    def arc(self, inv1) -> TimingArc:
        cell = inv1.cells[0]
        pin_y = _get_pin(cell, "Y")
        return pin_y.timing_arcs[0]

    def test_related_pin(self, arc):
        assert arc.related_pin == "A"

    def test_timing_type(self, arc):
        assert arc.timing_type == "combinational"

    def test_timing_sense(self, arc):
        assert arc.timing_sense == "negative_unate"

    def test_cell_rise_present(self, arc):
        assert arc.cell_rise is not None

    def test_cell_fall_present(self, arc):
        assert arc.cell_fall is not None

    def test_rise_transition_present(self, arc):
        assert arc.rise_transition is not None

    def test_fall_transition_present(self, arc):
        assert arc.fall_transition is not None

    def test_cell_rise_template(self, arc):
        assert arc.cell_rise.template == "delay_template"

    def test_cell_rise_values_non_empty(self, arc):
        assert len(arc.cell_rise.values) > 0

    def test_cell_rise_values_count(self, arc):
        # 3 rows × 3 cols = 9 values
        assert len(arc.cell_rise.values) == 9

    def test_cell_rise_first_value(self, arc):
        assert arc.cell_rise.values[0] == pytest.approx(0.1)

    def test_cell_fall_values_non_empty(self, arc):
        assert len(arc.cell_fall.values) > 0

    def test_arc_pos_recorded(self, arc):
        assert arc.pos is not None


# ---------------------------------------------------------------------------
# LU Table
# ---------------------------------------------------------------------------

class TestLUTable:
    @pytest.fixture
    def cell_rise(self, inv1) -> LUTable:
        cell = inv1.cells[0]
        pin_y = _get_pin(cell, "Y")
        return pin_y.timing_arcs[0].cell_rise

    def test_template_name(self, cell_rise):
        assert cell_rise.template == "delay_template"

    def test_values_are_floats(self, cell_rise):
        for v in cell_rise.values:
            assert isinstance(v, float)

    def test_values_all_positive(self, cell_rise):
        assert all(v > 0 for v in cell_rise.values)

    def test_pos_recorded(self, cell_rise):
        assert cell_rise.pos is not None


# ---------------------------------------------------------------------------
# Comment handling
# ---------------------------------------------------------------------------

class TestComments:
    def test_block_comment_ignored(self):
        src = """
/* This is a library-level block comment */
library (test_comments) {
    /* Another comment */
    cell (buf_1) {
        area : 2.0; /* inline comment */
        pin (A) { direction : input; }
        pin (Y) { direction : output; function : "A"; }
    }
}
"""
        lib = parse(src)
        assert lib.name == "test_comments"
        assert lib.cells[0].area == pytest.approx(2.0)

    def test_line_comment_ignored(self):
        src = """
library (test_line_comments) { // line comment after brace
    cell (and2_1) {
        area : 3.5; // area value
        pin (A) { direction : input; } // input pin
        pin (B) { direction : input; }
        pin (Y) { direction : output; function : "A B"; }
    } // end cell
} // end library
"""
        lib = parse(src)
        assert lib.name == "test_line_comments"
        assert lib.cells[0].area == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Nested braces
# ---------------------------------------------------------------------------

class TestNestedBraces:
    def test_deep_nesting_handled(self):
        """Unknown nested groups must be skipped without parse error."""
        src = """
library (test_deep) {
    cell (nand2_1) {
        area : 5.1;
        /* deeply nested unknown group */
        leakage_power () {
            value : 0.001;
            when : "!A B";
            pg_type : primary_power;
        }
        pin (A) { direction : input; }
        pin (B) { direction : input; }
        pin (Y) {
            direction : output;
            function : "!(A B)";
            timing () {
                related_pin : "A";
                cell_rise (delay_template) {
                    values ("0.1, 0.2");
                }
            }
        }
    }
}
"""
        lib = parse(src)
        assert lib.cells[0].area == pytest.approx(5.1)
        pin_y = _get_pin(lib.cells[0], "Y")
        assert pin_y.function == "!(A B)"
        assert len(pin_y.timing_arcs[0].cell_rise.values) == 2

    def test_multiple_cells(self):
        src = """
library (multi) {
    cell (inv_1) {
        area : 4.6;
        pin (A) { direction : input; }
        pin (Y) { direction : output; function : "!A"; }
    }
    cell (buf_1) {
        area : 6.4;
        pin (A) { direction : input; }
        pin (Y) { direction : output; function : "A"; }
    }
}
"""
        lib = parse(src)
        assert len(lib.cells) == 2
        names = {c.name for c in lib.cells}
        assert names == {"inv_1", "buf_1"}


# ---------------------------------------------------------------------------
# AST source positions
# ---------------------------------------------------------------------------

class TestSourcePositions:
    def test_library_pos_line_col_are_ints(self, inv1):
        assert isinstance(inv1.pos.line, int)
        assert isinstance(inv1.pos.col, int)

    def test_cell_pos_is_after_library_pos(self, inv1):
        cell = inv1.cells[0]
        assert cell.pos.line > inv1.pos.line

    def test_pin_pos_is_after_cell_pos(self, inv1):
        cell = inv1.cells[0]
        pin_a = _get_pin(cell, "A")
        assert pin_a.pos.line > cell.pos.line

    def test_source_pos_repr(self, inv1):
        # SourcePos repr is "line:col" (1-based)
        r = repr(inv1.pos)
        assert ":" in r


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError):
            parse("")

    def test_missing_library_keyword_raises(self):
        with pytest.raises(ParseError):
            parse("not_a_library (foo) { }")

    def test_parse_file_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_file("/nonexistent/path/to/file.lib")
