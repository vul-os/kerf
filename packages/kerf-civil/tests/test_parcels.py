"""
Tests for kerf_civil.parcels — parcel subdivision engine.

Oracle values
-------------
A 60 m × 30 m rectangle (1 800 m²):
  - 3 equal-width lots → each ≈ 600 m² (20 m × 30 m)
  - target_area=450 m² → 4 lots of ≈ 450 m², with remainder absorbed

ROW dedication of 5 m → net area = 60 × 25 = 1 500 m²

Setback of 2 m → buildable = (20-4) × (30-4) = 16 × 26 = 416 m² per lot
  (inset from all four sides; actual result from Sutherland-Hodgman clip)

References
----------
ISO 19152 LADM; ASCE Surveying Engineering subdivision design;
Sutherland & Hodgman (1974) CACM 17(1).
"""
from __future__ import annotations

import json
import math
import pytest
import asyncio

from kerf_civil.parcels import (
    subdivide_parcel,
    SubdivisionResult,
    _shoelace_area,
    _area,
    _perimeter,
    _inset_polygon,
    _ensure_ccw,
)
from kerf_civil.tools_parcels_pointcloud_sheets import (
    civil_parcel_subdivide_spec,
    run_civil_parcel_subdivide,
)


def _ctx():
    try:
        from kerf_civil._compat import ProjectCtx
    except ImportError:
        from types import SimpleNamespace
        return SimpleNamespace(pool=None)
    return ProjectCtx()


def _call(handler, payload):
    raw = asyncio.run(handler(payload, _ctx()))
    return json.loads(raw)


# 60 × 30 m rectangular parcel, CCW
RECT_60x30 = [
    [0.0, 0.0],
    [60.0, 0.0],
    [60.0, 30.0],
    [0.0, 30.0],
]

# Smaller square 40×40
SQUARE_40 = [
    [0.0, 0.0],
    [40.0, 0.0],
    [40.0, 40.0],
    [0.0, 40.0],
]


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

class TestGeometryPrimitives:
    def test_shoelace_ccw_positive(self):
        # CCW square [0,0],[1,0],[1,1],[0,1]
        pts = [(0, 0), (1, 0), (1, 1), (0, 1)]
        assert _shoelace_area(pts) == pytest.approx(1.0)

    def test_shoelace_cw_negative(self):
        pts = [(0, 0), (0, 1), (1, 1), (1, 0)]
        assert _shoelace_area(pts) < 0

    def test_area_rect(self):
        pts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        assert _area(pts) == pytest.approx(50.0)

    def test_perimeter_rect(self):
        pts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        assert _perimeter(pts) == pytest.approx(30.0)

    def test_ensure_ccw(self):
        cw = [(0, 0), (0, 1), (1, 1), (1, 0)]
        ccw = _ensure_ccw(cw)
        assert _shoelace_area(ccw) > 0

    def test_inset_polygon_shrinks(self):
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        inset = _inset_polygon(pts, 1.0)
        # Inset by 1 m → area should be 8×8 = 64 m² (approx, convex)
        assert _area(inset) < _area(pts)
        assert _area(inset) > 0

    def test_inset_polygon_zero_dist(self):
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        inset = _inset_polygon(pts, 0.0)
        assert _area(inset) == pytest.approx(_area(pts), rel=1e-6)


# ---------------------------------------------------------------------------
# Engine: subdivide_parcel — equal_width
# ---------------------------------------------------------------------------

class TestSubdivideEqualWidth:
    def test_3_lots_rect(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, strategy="equal_width")
        assert isinstance(result, SubdivisionResult)
        assert result.n_lots == 3
        assert result.strategy == "equal_width"

    def test_lot_areas_sum_to_parent(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, strategy="equal_width")
        total = sum(lot.area_m2 for lot in result.lots)
        # Lots should sum to the net developable area (no ROW here)
        assert total == pytest.approx(result.parent_area_m2, rel=0.05)

    def test_individual_lot_area(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, strategy="equal_width")
        # Each lot ≈ 1800/3 = 600 m²
        for lot in result.lots:
            assert lot.area_m2 == pytest.approx(600.0, rel=0.05)

    def test_lot_polygon_closed(self):
        result = subdivide_parcel(RECT_60x30, n_lots=4, strategy="equal_width")
        for lot in result.lots:
            assert len(lot.polygon) >= 3

    def test_lot_frontage_positive(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, strategy="equal_width")
        for lot in result.lots:
            assert lot.frontage_m > 0

    def test_buildable_smaller_than_lot(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, setback_m=3.0, strategy="equal_width")
        for lot in result.lots:
            assert lot.buildable_area_m2 < lot.area_m2

    def test_parent_area_correct(self):
        result = subdivide_parcel(RECT_60x30, n_lots=2, strategy="equal_width")
        assert result.parent_area_m2 == pytest.approx(1800.0, rel=0.01)

    def test_statistics(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, strategy="equal_width")
        assert result.min_lot_area_m2 <= result.mean_lot_area_m2 <= result.max_lot_area_m2

    def test_single_lot(self):
        result = subdivide_parcel(RECT_60x30, n_lots=1, strategy="equal_width")
        assert result.n_lots == 1
        assert result.lots[0].area_m2 == pytest.approx(1800.0, rel=0.01)


# ---------------------------------------------------------------------------
# Engine: subdivide_parcel — target_area
# ---------------------------------------------------------------------------

class TestSubdivideTargetArea:
    def test_lots_near_target(self):
        target = 450.0
        result = subdivide_parcel(RECT_60x30, target_area_m2=target, strategy="target_area")
        # Most lots should be within 30% of target
        for lot in result.lots[:-1]:  # last lot absorbs remainder
            assert lot.area_m2 == pytest.approx(target, rel=0.30)

    def test_areas_sum_to_parent(self):
        result = subdivide_parcel(RECT_60x30, target_area_m2=400.0, strategy="target_area")
        total = sum(lot.area_m2 for lot in result.lots)
        assert total == pytest.approx(result.parent_area_m2, rel=0.05)

    def test_multiple_lots_produced(self):
        result = subdivide_parcel(SQUARE_40, target_area_m2=200.0, strategy="target_area")
        assert result.n_lots >= 2  # 1600 m² / 200 = 8 lots


# ---------------------------------------------------------------------------
# ROW dedication
# ---------------------------------------------------------------------------

class TestROWDedication:
    def test_row_polygon_exists(self):
        result = subdivide_parcel(RECT_60x30, n_lots=3, row_width_m=5.0, strategy="equal_width")
        assert result.row is not None
        assert result.row.width_m == 5.0
        assert result.row.area_m2 > 0

    def test_row_reduces_net_area(self):
        result_no_row = subdivide_parcel(RECT_60x30, n_lots=3, strategy="equal_width")
        result_row = subdivide_parcel(RECT_60x30, n_lots=3, row_width_m=5.0, strategy="equal_width")
        assert result_row.net_developable_area_m2 < result_no_row.net_developable_area_m2

    def test_row_area_approx(self):
        # ROW strip: 60 × 5 = 300 m²
        result = subdivide_parcel(RECT_60x30, n_lots=3, row_width_m=5.0, strategy="equal_width")
        assert result.row.area_m2 == pytest.approx(300.0, rel=0.10)

    def test_no_row(self):
        result = subdivide_parcel(RECT_60x30, n_lots=2, row_width_m=0.0, strategy="equal_width")
        assert result.row is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_too_few_vertices_raises(self):
        with pytest.raises(ValueError, match="3 vertices"):
            subdivide_parcel([[0, 0], [10, 0]], n_lots=2, strategy="equal_width")

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="unknown strategy"):
            subdivide_parcel(RECT_60x30, n_lots=2, strategy="bogus")

    def test_equal_width_no_n_lots_raises(self):
        with pytest.raises((ValueError, TypeError)):
            subdivide_parcel(RECT_60x30, strategy="equal_width")

    def test_target_area_no_target_raises(self):
        with pytest.raises(ValueError, match="target_area_m2"):
            subdivide_parcel(RECT_60x30, strategy="target_area")


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

class TestParcelTool:
    def test_spec_name(self):
        assert civil_parcel_subdivide_spec.name == "civil_parcel_subdivide"

    def test_spec_required(self):
        assert "boundary" in civil_parcel_subdivide_spec.input_schema["required"]

    def test_tool_equal_width(self):
        result = _call(run_civil_parcel_subdivide, {
            "boundary": RECT_60x30,
            "strategy": "equal_width",
            "n_lots": 3,
            "setback_m": 2.0,
        })
        assert result.get("ok") is True
        assert result["n_lots"] == 3
        assert len(result["lots"]) == 3
        for lot in result["lots"]:
            assert "polygon" in lot
            assert "buildable_polygon" in lot
            assert lot["area_m2"] > 0
            assert lot["buildable_area_m2"] < lot["area_m2"]

    def test_tool_target_area(self):
        result = _call(run_civil_parcel_subdivide, {
            "boundary": SQUARE_40,
            "strategy": "target_area",
            "target_area_m2": 400.0,
        })
        assert result.get("ok") is True
        assert result["n_lots"] >= 2

    def test_tool_with_row(self):
        result = _call(run_civil_parcel_subdivide, {
            "boundary": RECT_60x30,
            "strategy": "equal_width",
            "n_lots": 3,
            "row_width_m": 5.0,
        })
        assert result.get("ok") is True
        assert result["row"] is not None
        assert result["row"]["area_m2"] > 0

    def test_tool_bad_boundary(self):
        result = _call(run_civil_parcel_subdivide, {
            "boundary": [[0, 0], [10, 0]],  # only 2 points
            "strategy": "equal_width",
            "n_lots": 2,
        })
        assert "error" in result

    def test_tool_summary_keys(self):
        result = _call(run_civil_parcel_subdivide, {
            "boundary": RECT_60x30,
            "strategy": "equal_width",
            "n_lots": 4,
        })
        assert result.get("ok") is True
        for key in ["parent_area_m2", "net_developable_area_m2",
                    "min_lot_area_m2", "max_lot_area_m2", "mean_lot_area_m2",
                    "total_buildable_area_m2"]:
            assert key in result, f"Missing key: {key}"
