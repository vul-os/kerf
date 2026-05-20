"""
Tests for textile export functions.

Covers SVG, WIF, CSV, and JSON outputs from weave/knit/draft objects.
"""

from __future__ import annotations

import json
import pytest

from kerf_textiles.weave import plain_weave, twill_weave
from kerf_textiles.knit import jersey_knit, rib_knit
from kerf_textiles.draft import canonical_plain_draft, canonical_twill_draft
from kerf_textiles.export import (
    weave_to_svg,
    knit_to_svg,
    draft_to_wif,
    draft_from_wif,
    matrix_to_csv,
    weave_to_json,
    knit_to_json,
)


class TestWeaveToSvg:
    def test_returns_string(self):
        pw = plain_weave()
        svg = weave_to_svg(pw)
        assert isinstance(svg, str)

    def test_is_valid_svg_fragment(self):
        pw = plain_weave()
        svg = weave_to_svg(pw)
        assert svg.startswith("<svg")
        assert "</svg>" in svg

    def test_cell_count(self):
        """SVG should contain one <rect> per cell."""
        tw = twill_weave(over=2, under=1)
        svg = weave_to_svg(tw)
        # 3×3 = 9 rects
        assert svg.count("<rect") == 9

    def test_custom_cell_size(self):
        pw = plain_weave()
        svg = weave_to_svg(pw, cell_px=20)
        assert 'width="40"' in svg  # 2 cols × 20px


class TestKnitToSvg:
    def test_returns_svg(self):
        jk = jersey_knit(needles=4, courses=3)
        svg = knit_to_svg(jk)
        assert svg.startswith("<svg")
        assert "</svg>" in svg

    def test_cell_count(self):
        jk = jersey_knit(needles=4, courses=3)
        svg = knit_to_svg(jk)
        assert svg.count("<rect") == 12


class TestMatrixToCsv:
    def test_bool_matrix(self):
        matrix = [[True, False], [False, True]]
        csv = matrix_to_csv(matrix)
        lines = csv.splitlines()
        assert lines[0] == "1,0"
        assert lines[1] == "0,1"

    def test_stitch_matrix(self):
        matrix = [["loop", "tuck"], ["miss", "loop"]]
        csv = matrix_to_csv(matrix)
        assert "loop" in csv
        assert "tuck" in csv


class TestWeaveToJson:
    def test_returns_valid_json(self):
        pw = plain_weave()
        js = weave_to_json(pw)
        data = json.loads(js)
        assert data["name"] == "plain"

    def test_contains_float_stats(self):
        pw = plain_weave()
        data = json.loads(weave_to_json(pw))
        assert "float_stats" in data
        assert "warp_mean_float" in data["float_stats"]

    def test_analytic_values_in_json(self):
        pw = plain_weave()
        data = json.loads(weave_to_json(pw))
        assert data["analytic_warp_mean_float"] == 1.0


class TestKnitToJson:
    def test_returns_valid_json(self):
        jk = jersey_knit()
        js = knit_to_json(jk)
        data = json.loads(js)
        assert data["name"] == "jersey"

    def test_contains_density_stats(self):
        jk = jersey_knit()
        data = json.loads(knit_to_json(jk))
        assert "density_stats" in data
        assert "density_within_1pct" in data["density_stats"]


class TestWifExport:
    def test_wif_structure(self):
        d = canonical_plain_draft()
        wif = draft_to_wif(d)
        assert "[WIF]" in wif
        assert "[THREADING]" in wif
        assert "[TREADLING]" in wif
        assert "[TIEUP]" in wif
        assert "Shafts=2" in wif
        assert "Treadles=2" in wif

    def test_threading_entries(self):
        d = canonical_plain_draft()
        wif = draft_to_wif(d)
        # Should have 1-based indices for each end
        assert "1=1" in wif  # end 1 → shaft 1
        assert "2=2" in wif  # end 2 → shaft 2

    def test_roundtrip_plain(self):
        d = canonical_plain_draft()
        wif = draft_to_wif(d)
        d2 = draft_from_wif(wif)
        assert d2.threading == d.threading
        assert d2.treadling == d.treadling
        assert d2.tie_up == d.tie_up

    def test_roundtrip_twill(self):
        d = canonical_twill_draft(over=2, under=1)
        wif = draft_to_wif(d)
        d2 = draft_from_wif(wif)
        assert d2.threading == d.threading
        assert d2.tie_up == d.tie_up
