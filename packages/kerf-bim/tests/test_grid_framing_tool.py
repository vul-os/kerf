"""
Dispatch tests for bim_make_grid and bim_make_framing LLM tools.

Oracles
-------
regular 3-bay × 2-bay grid  — produces 4 col-lines, 3 row-lines, 12 intersections
custom grid                  — two explicit column positions at 0 m and 5 m
framing 3×2 regular, 1 storey — 12 columns (4 × 3), 17 beams
"""
from __future__ import annotations

import asyncio
import json
import pytest

from kerf_bim.tools.grid_framing import (
    _make_grid_spec,
    run_bim_make_grid,
    _make_framing_spec,
    run_bim_make_framing,
    TOOLS,
)


def _run(coro):
    return asyncio.run(coro)


def _call_grid(payload: dict) -> dict:
    return json.loads(_run(run_bim_make_grid(payload, None)))


def _call_framing(payload: dict) -> dict:
    return json.loads(_run(run_bim_make_framing(payload, None)))


# ---------------------------------------------------------------------------
# Spec smoke tests
# ---------------------------------------------------------------------------

class TestSpec:
    def test_grid_spec_name(self):
        assert _make_grid_spec.name == "bim_make_grid"

    def test_framing_spec_name(self):
        assert _make_framing_spec.name == "bim_make_framing"

    def test_tools_list_length(self):
        assert len(TOOLS) == 2

    def test_tools_names(self):
        names = [t[0] for t in TOOLS]
        assert "bim_make_grid" in names
        assert "bim_make_framing" in names


# ---------------------------------------------------------------------------
# bim_make_grid — regular mode
# ---------------------------------------------------------------------------

class TestMakeGridRegular:
    def _result(self, **kw) -> dict:
        return _call_grid({"mode": "regular", **kw})

    def test_ok(self):
        r = self._result(n_cols=3, n_rows=2, bay_width_m=6.0, bay_depth_m=6.0)
        assert r.get("ok") is True

    def test_col_line_count(self):
        r = self._result(n_cols=3, n_rows=2, bay_width_m=6.0, bay_depth_m=6.0)
        assert r["n_col_lines"] == 4   # 3 bays → 4 lines

    def test_row_line_count(self):
        r = self._result(n_cols=3, n_rows=2, bay_width_m=6.0, bay_depth_m=6.0)
        assert r["n_row_lines"] == 3   # 2 bays → 3 lines

    def test_intersection_count(self):
        r = self._result(n_cols=3, n_rows=2, bay_width_m=6.0, bay_depth_m=6.0)
        assert r["n_intersections"] == 12

    def test_bay_widths_reported_in_metres(self):
        r = self._result(n_cols=3, n_rows=2, bay_width_m=6.0, bay_depth_m=6.0)
        assert r["bay_widths_m"] == pytest.approx([6.0, 6.0, 6.0])

    def test_bay_depths_reported_in_metres(self):
        r = self._result(n_cols=3, n_rows=2, bay_width_m=6.0, bay_depth_m=6.0)
        assert r["bay_depths_m"] == pytest.approx([6.0, 6.0])

    def test_intersection_structure(self):
        r = self._result(n_cols=2, n_rows=1, bay_width_m=5.0, bay_depth_m=4.0)
        isects = r["intersections"]
        # First intersection should be col A, row 1 at origin
        a1 = next(i for i in isects if i["col"] == "A" and i["row"] == "1")
        assert a1["x_m"] == pytest.approx(0.0)
        assert a1["y_m"] == pytest.approx(0.0)

    def test_intersection_b1_coords(self):
        r = self._result(n_cols=2, n_rows=1, bay_width_m=5.0, bay_depth_m=4.0)
        isects = r["intersections"]
        b1 = next(i for i in isects if i["col"] == "B" and i["row"] == "1")
        assert b1["x_m"] == pytest.approx(5.0)

    def test_ifc_dict_present(self):
        r = self._result(n_cols=2, n_rows=1, bay_width_m=5.0, bay_depth_m=4.0)
        assert "ifc_dict" in r
        assert r["ifc_dict"]["kind"] == "grid"

    def test_origin_offset(self):
        r = _call_grid({
            "mode": "regular",
            "n_cols": 1, "n_rows": 1,
            "bay_width_m": 6.0, "bay_depth_m": 6.0,
            "origin_x": 2.0, "origin_y": 3.0,
        })
        isects = r["intersections"]
        a1 = next(i for i in isects if i["col"] == "A" and i["row"] == "1")
        assert a1["x_m"] == pytest.approx(2.0)
        assert a1["y_m"] == pytest.approx(3.0)

    def test_default_mode_is_regular(self):
        r = _call_grid({"n_cols": 2, "n_rows": 2, "bay_width_m": 6.0, "bay_depth_m": 6.0})
        assert r.get("ok") is True
        assert r["n_col_lines"] == 3


# ---------------------------------------------------------------------------
# bim_make_grid — custom mode
# ---------------------------------------------------------------------------

class TestMakeGridCustom:
    def test_custom_mode_ok(self):
        r = _call_grid({
            "mode": "custom",
            "column_coords": [0.0, 5.0, 12.0],
            "row_coords": [0.0, 4.0],
        })
        assert r.get("ok") is True

    def test_custom_col_line_count(self):
        r = _call_grid({
            "mode": "custom",
            "column_coords": [0.0, 5.0, 12.0],
            "row_coords": [0.0, 4.0],
        })
        assert r["n_col_lines"] == 3

    def test_custom_row_line_count(self):
        r = _call_grid({
            "mode": "custom",
            "column_coords": [0.0, 5.0, 12.0],
            "row_coords": [0.0, 4.0],
        })
        assert r["n_row_lines"] == 2

    def test_custom_missing_column_coords(self):
        r = _call_grid({"mode": "custom", "row_coords": [0.0, 4.0]})
        assert "error" in r

    def test_custom_missing_row_coords(self):
        r = _call_grid({"mode": "custom", "column_coords": [0.0, 5.0]})
        assert "error" in r

    def test_custom_intersection_b2_coords(self):
        r = _call_grid({
            "mode": "custom",
            "column_coords": [0.0, 5.0],
            "row_coords": [0.0, 4.0],
        })
        isects = r["intersections"]
        b2 = next(i for i in isects if i["col"] == "B" and i["row"] == "2")
        assert b2["x_m"] == pytest.approx(5.0)
        assert b2["y_m"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# bim_make_framing
# ---------------------------------------------------------------------------

class TestMakeFraming:
    def _result(self, **kw) -> dict:
        return _call_framing({"n_cols": 3, "n_rows": 2, "bay_width_m": 6.0, "bay_depth_m": 6.0, **kw})

    def test_ok(self):
        r = self._result(storey_heights_m=[4.0])
        assert r.get("ok") is True

    def test_column_count_one_storey(self):
        """3-bay-X × 2-bay-Y → 4 × 3 = 12 intersections × 1 storey = 12 columns."""
        r = self._result(storey_heights_m=[4.0])
        assert r["n_columns"] == 12

    def test_beam_count_one_storey(self):
        """Per storey: 3 X-bays × 3 rows = 9 X-beams; 2 Y-bays × 4 cols = 8 Y-beams = 17."""
        r = self._result(storey_heights_m=[4.0])
        assert r["n_beams"] == 17

    def test_total_members(self):
        r = self._result(storey_heights_m=[4.0])
        assert r["total_members"] == r["n_columns"] + r["n_beams"]

    def test_storey_count(self):
        r = self._result(storey_heights_m=[3.0, 3.0, 3.0])
        assert r["n_storeys"] == 3

    def test_ifc_dict_present(self):
        r = self._result(storey_heights_m=[4.0])
        assert "ifc_dict" in r
        assert r["ifc_dict"]["kind"] == "framing"

    def test_default_storey(self):
        r = _call_framing({})
        assert r.get("ok") is True
        assert r["n_storeys"] == 1

    def test_custom_sections(self):
        r = _call_framing({
            "n_cols": 2, "n_rows": 1,
            "bay_width_m": 5.0, "bay_depth_m": 5.0,
            "storey_heights_m": [4.0],
            "column_section": "UC203x203x46",
            "beam_section": "UB254x102x22",
        })
        assert r.get("ok") is True
