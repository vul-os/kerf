"""
Tests for kerf_civil.sheets — plan-and-profile sheet production engine.

Oracle values
-------------
A 1000 m alignment at plan_scale=1000, sheet_length=250 m:
  - 4 sheets expected (1000 / 250 = 4)
  - station_interval=20 → ticks at 0, 20, 40, …, 250 on sheet 1

Station label formatting (metric):
  - sta=1234.56 → "1+234.56"
  - sta=0.0 → "0+000.00"

Elevation at sta=100 m with initial grade 2%: 0 + 0.02×100 = 2.0 m

References
----------
AASHTO Green Book (2011) Ch.2; FHWA Plans Preparation Manual (2012);
ODOT PPM (2023) Ch.300; CALTRANS PPM (2023) Ch.3.
"""
from __future__ import annotations

import json
import math
import asyncio

import pytest

from kerf_civil.sheets import (
    produce_sheets,
    sheet_set_to_dict,
    SheetSet,
    Sheet,
    _fmt_station,
    _va_elevation,
    _ha_interpolate_xy,
)
from kerf_civil.tools_parcels_pointcloud_sheets import (
    civil_plan_profile_sheets_spec,
    run_civil_plan_profile_sheets,
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


# ---------------------------------------------------------------------------
# Station label formatting
# ---------------------------------------------------------------------------

class TestStationLabel:
    def test_metric_zero(self):
        assert _fmt_station(0.0, "m") == "0+000.00"

    def test_metric_1000(self):
        assert _fmt_station(1000.0, "m") == "1+000.00"

    def test_metric_1234_56(self):
        # 1+234.56
        label = _fmt_station(1234.56, "m")
        assert label == "1+234.56"

    def test_metric_500(self):
        label = _fmt_station(500.0, "m")
        assert label == "0+500.00"

    def test_ft_100(self):
        # 100 ft → "1+00.00"
        label = _fmt_station(100.0, "ft")
        assert label == "1+00.00"

    def test_ft_12345_6(self):
        label = _fmt_station(12345.6, "ft")
        assert "123" in label  # major = 123


# ---------------------------------------------------------------------------
# Vertical alignment elevation interpolation
# ---------------------------------------------------------------------------

class TestVAElevation:
    def test_flat_grade(self):
        # 0% grade → all elevations equal datum
        va = [{"type": "tangent", "length": 500.0}]
        elev, grade = _va_elevation(va, datum_elev=10.0, initial_grade_pct=0.0, station=250.0)
        assert elev == pytest.approx(10.0)
        assert grade == pytest.approx(0.0)

    def test_2pct_grade(self):
        va = [{"type": "tangent", "length": 500.0}]
        elev, grade = _va_elevation(va, datum_elev=0.0, initial_grade_pct=2.0, station=100.0)
        assert elev == pytest.approx(2.0)

    def test_grade_change_curve(self):
        va = [
            {"type": "tangent", "length": 100.0},
            {"type": "curve", "length": 100.0, "grade_out_pct": 4.0},
        ]
        # At sta=100 (just at start of curve) → elev = 0 + 2%×100 = 2 m
        elev, _ = _va_elevation(va, datum_elev=0.0, initial_grade_pct=2.0, station=100.0)
        assert elev == pytest.approx(2.0, abs=0.1)

    def test_past_end_extrapolates(self):
        # Short alignment, query beyond end
        va = [{"type": "tangent", "length": 100.0}]
        elev, _ = _va_elevation(va, datum_elev=0.0, initial_grade_pct=1.0, station=200.0)
        assert elev == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# Horizontal alignment interpolation
# ---------------------------------------------------------------------------

class TestHAInterpolate:
    def test_tangent_straight(self):
        ha = [{"type": "tangent", "length": 1000.0}]
        x, y, brg = _ha_interpolate_xy(ha, station=500.0)
        # North-bearing tangent: x stays 0, y advances
        assert brg == pytest.approx(0.0)
        # x = 500*cos(90°) = 0, y = 500*sin(90°) = 500
        assert abs(x) < 1e-9
        assert y == pytest.approx(500.0)

    def test_zero_station(self):
        ha = [{"type": "tangent", "length": 1000.0}]
        x, y, brg = _ha_interpolate_xy(ha, station=0.0)
        assert x == pytest.approx(0.0)
        assert y == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# produce_sheets — structure
# ---------------------------------------------------------------------------

class TestProduceSheets:
    def test_returns_sheet_set(self):
        ss = produce_sheets(total_length=1000.0)
        assert isinstance(ss, SheetSet)

    def test_n_sheets_correct(self):
        # 1000 m / 250 m per sheet = 4 sheets
        ss = produce_sheets(
            total_length=1000.0,
            plan_scale=1000,
            sheet_length=250.0,
            station_interval=20.0,
        )
        assert ss.n_sheets == 4

    def test_sheet_count_partial(self):
        # 1100 m / 250 m → 5 sheets (4 full + 1 partial)
        ss = produce_sheets(total_length=1100.0, sheet_length=250.0)
        assert ss.n_sheets == 5

    def test_single_sheet_short_alignment(self):
        ss = produce_sheets(total_length=100.0, sheet_length=250.0)
        assert ss.n_sheets == 1

    def test_station_range_covers_full_alignment(self):
        ss = produce_sheets(total_length=500.0, sheet_length=200.0)
        # Last sheet should reach total_length
        assert ss.sheets[-1].sta_end == pytest.approx(500.0)

    def test_station_range_starts_at_zero(self):
        ss = produce_sheets(total_length=500.0)
        assert ss.sheets[0].sta_start == pytest.approx(0.0)

    def test_station_ticks_within_range(self):
        ss = produce_sheets(total_length=1000.0, sheet_length=250.0, station_interval=50.0)
        for sheet in ss.sheets:
            for tick in sheet.station_ticks:
                assert sheet.sta_start - 1e-6 <= tick.station <= sheet.sta_end + 1e-6

    def test_profile_points_match_ticks(self):
        ss = produce_sheets(total_length=500.0, sheet_length=250.0, station_interval=50.0)
        for sheet in ss.sheets:
            assert len(sheet.profile_points) == len(sheet.station_ticks)

    def test_match_lines_interior_sheets(self):
        ss = produce_sheets(total_length=1000.0, sheet_length=250.0)
        # Interior sheets should have 2 match lines (forward + back)
        for sheet in ss.sheets[1:-1]:
            assert len(sheet.match_lines) == 2

    def test_first_sheet_one_match_line(self):
        ss = produce_sheets(total_length=1000.0, sheet_length=250.0)
        assert len(ss.sheets[0].match_lines) == 1

    def test_last_sheet_one_match_line(self):
        ss = produce_sheets(total_length=1000.0, sheet_length=250.0)
        assert len(ss.sheets[-1].match_lines) == 1

    def test_single_sheet_no_match_lines(self):
        ss = produce_sheets(total_length=100.0, sheet_length=500.0)
        assert len(ss.sheets[0].match_lines) == 0

    def test_sheet_numbering(self):
        ss = produce_sheets(total_length=1000.0, sheet_length=250.0)
        for i, sheet in enumerate(ss.sheets):
            assert sheet.sheet_number == i + 1
            assert sheet.total_sheets == 4

    def test_alignment_polyline_populated(self):
        ss = produce_sheets(total_length=500.0, sheet_length=500.0, station_interval=100.0)
        sheet = ss.sheets[0]
        assert len(sheet.alignment_polyline) > 0
        for pt in sheet.alignment_polyline:
            assert "x" in pt and "y" in pt and "station" in pt

    def test_profile_datum_less_than_top(self):
        ss = produce_sheets(total_length=500.0, datum_elev=100.0, initial_grade_pct=2.0)
        for sheet in ss.sheets:
            assert sheet.profile_datum_elev < sheet.profile_top_elev

    def test_scale_fields(self):
        ss = produce_sheets(total_length=500.0, plan_scale=2000, profile_scale_v=100)
        assert ss.sheets[0].plan_scale == 2000
        assert ss.sheets[0].profile_scale_v == 100

    def test_title_block_fields(self):
        ss = produce_sheets(
            total_length=500.0,
            project_name="Test Road",
            alignment_name="CL-1",
            date="2026-06-05",
            designer="IP",
        )
        sheet = ss.sheets[0]
        assert sheet.project_name == "Test Road"
        assert sheet.alignment_name == "CL-1"
        assert sheet.date == "2026-06-05"
        assert sheet.designer == "IP"

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError, match="total_length"):
            produce_sheets(total_length=0.0)

    def test_units_ft(self):
        ss = produce_sheets(total_length=5000.0, units="ft", station_interval=100.0)
        assert ss.units == "ft"
        # Station labels use "+" notation
        tick = ss.sheets[0].station_ticks[0]
        assert "+" in tick.label


# ---------------------------------------------------------------------------
# With vertical alignment
# ---------------------------------------------------------------------------

class TestSheetsWithVerticalAlignment:
    def test_proposed_elevation_at_start(self):
        ss = produce_sheets(
            total_length=500.0,
            datum_elev=50.0,
            initial_grade_pct=0.0,
            station_interval=100.0,
            sheet_length=600.0,
        )
        first_pt = ss.sheets[0].profile_points[0]
        assert first_pt.proposed_elev == pytest.approx(50.0, abs=0.01)

    def test_proposed_elevation_with_grade(self):
        ss = produce_sheets(
            total_length=500.0,
            datum_elev=0.0,
            initial_grade_pct=2.0,  # 2% uphill
            station_interval=100.0,
            sheet_length=600.0,
        )
        # At sta=100 m: elev = 0 + 0.02*100 = 2.0 m
        pt_100 = next(p for p in ss.sheets[0].profile_points if abs(p.station - 100.0) < 1e-3)
        assert pt_100.proposed_elev == pytest.approx(2.0, abs=0.05)

    def test_existing_ground_interpolated(self):
        existing = [(0.0, 10.0), (500.0, 20.0)]
        ss = produce_sheets(
            total_length=500.0,
            existing_ground=existing,
            sheet_length=600.0,
            station_interval=100.0,
        )
        # At sta=100 m, existing elev should be interpolated between 10 and 20
        # linear: 10 + (100/500)*(20-10) = 12.0
        pt_100 = next(p for p in ss.sheets[0].profile_points if abs(p.station - 100.0) < 1e-3)
        assert pt_100.existing_elev == pytest.approx(12.0, abs=0.1)

    def test_no_existing_ground_is_none(self):
        ss = produce_sheets(total_length=500.0, sheet_length=600.0, station_interval=100.0)
        for pt in ss.sheets[0].profile_points:
            assert pt.existing_elev is None


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------

class TestSheetSetToDict:
    def test_returns_dict(self):
        ss = produce_sheets(total_length=500.0)
        d = sheet_set_to_dict(ss)
        assert isinstance(d, dict)

    def test_json_serialisable(self):
        ss = produce_sheets(total_length=500.0)
        d = sheet_set_to_dict(ss)
        # Should not raise
        serialised = json.dumps(d)
        assert len(serialised) > 0

    def test_dict_keys(self):
        ss = produce_sheets(total_length=500.0)
        d = sheet_set_to_dict(ss)
        for key in ["total_length_m", "n_sheets", "sheets", "alignment_name", "units"]:
            assert key in d

    def test_sheet_dict_keys(self):
        ss = produce_sheets(total_length=500.0)
        d = sheet_set_to_dict(ss)
        sh = d["sheets"][0]
        for key in ["sheet_number", "total_sheets", "sta_start", "sta_end",
                    "station_ticks", "alignment_polyline", "match_lines",
                    "profile_band", "profile_datum_elev", "profile_top_elev"]:
            assert key in sh, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# LLM tool: civil_plan_profile_sheets
# ---------------------------------------------------------------------------

class TestPlanProfileSheetsTool:
    def test_spec_name(self):
        assert civil_plan_profile_sheets_spec.name == "civil_plan_profile_sheets"

    def test_spec_required(self):
        assert "total_length" in civil_plan_profile_sheets_spec.input_schema["required"]

    def test_basic_call(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 500.0,
            "sheet_length": 250.0,
            "station_interval": 50.0,
        })
        assert result.get("ok") is True
        assert result["n_sheets"] == 2
        assert len(result["sheets"]) == 2

    def test_with_ha_elements(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 300.0,
            "alignment_elements": [
                {"type": "tangent", "length": 150.0},
                {"type": "arc", "length": 150.0, "radius": 500.0, "delta_deg": 17.2},
            ],
            "sheet_length": 400.0,
            "station_interval": 50.0,
        })
        assert result.get("ok") is True
        assert result["n_sheets"] == 1

    def test_with_va_elements(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 300.0,
            "vertical_elements": [
                {"type": "tangent", "length": 150.0},
                {"type": "curve", "length": 100.0, "grade_out_pct": 3.0},
                {"type": "tangent", "length": 50.0},
            ],
            "datum_elev": 100.0,
            "initial_grade_pct": 1.0,
            "sheet_length": 400.0,
            "station_interval": 50.0,
        })
        assert result.get("ok") is True
        # Proposed elevations should increase from 100 m
        band = result["sheets"][0]["profile_band"]
        first_elev = band[0]["proposed_elev"]
        assert first_elev == pytest.approx(100.0, abs=0.1)

    def test_with_existing_ground(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 200.0,
            "existing_ground": [[0, 50.0], [100, 55.0], [200, 52.0]],
            "sheet_length": 300.0,
            "station_interval": 50.0,
        })
        assert result.get("ok") is True
        band = result["sheets"][0]["profile_band"]
        # All points should have existing_elev set
        for pt in band:
            assert pt["existing_elev"] is not None

    def test_profile_band_keys(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 200.0,
            "sheet_length": 300.0,
            "station_interval": 50.0,
        })
        assert result.get("ok") is True
        pt = result["sheets"][0]["profile_band"][0]
        for key in ["station", "station_label", "proposed_elev", "grade_pct"]:
            assert key in pt

    def test_match_lines_multi_sheet(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 600.0,
            "sheet_length": 200.0,
            "station_interval": 50.0,
        })
        assert result.get("ok") is True
        assert result["n_sheets"] == 3
        # Middle sheet should have match lines
        mid_sheet = result["sheets"][1]
        assert len(mid_sheet["match_lines"]) == 2

    def test_title_block(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 300.0,
            "project_name": "Highway 1",
            "alignment_name": "CL-MAIN",
            "date": "2026-06-05",
            "designer": "IP",
            "sheet_length": 400.0,
        })
        assert result.get("ok") is True
        sh = result["sheets"][0]
        assert sh["project_name"] == "Highway 1"
        assert sh["alignment_name"] == "CL-MAIN"

    def test_invalid_length(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": -100.0,
        })
        assert "error" in result

    def test_units_ft(self):
        result = _call(run_civil_plan_profile_sheets, {
            "total_length": 5000.0,
            "units": "ft",
            "station_interval": 100.0,
            "sheet_length": 1000.0,
        })
        assert result.get("ok") is True
        assert result["units"] == "ft"
        tick = result["sheets"][0]["station_ticks"][0]
        assert "+" in tick["label"]
