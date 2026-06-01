"""
Tests for kerf_cad_core.civil.corridor_sheet_generator and
kerf_cad_core.civil.corridor_sheet_tools.

All tests are hermetic: pure-Python, no OCC, no DB, no network.
Disk I/O is limited to temporary files (cleaned up with try/finally).

Run with:
    python -m pytest packages/kerf-cad-core/tests/test_corridor_sheets.py -q -p no:cacheprovider

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile

import pytest

from kerf_cad_core.civil.corridor_sheet_generator import (
    CorridorSheetSpec,
    CorridorSpec,
    HorizontalAlignmentSpec,
    VerticalAlignmentSpec,
    generate_corridor_sheets,
    _sample_stations,
    _design_elevation_at,
    _ground_elevation_at,
    _build_cross_section,
    _build_plan_view,
    _build_profile_view,
)
from kerf_cad_core.civil.corridor_sheet_tools import run_civil_generate_corridor_sheets
from kerf_cad_core.geom.io.dxf import read_dxf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        ctx = ProjectCtx.__new__(ProjectCtx)
        ctx.project_id = "00000000-0000-0000-0000-000000000002"
        return ctx
    except Exception:
        return object()


def _basic_spec(
    start: float = 0.0,
    end: float = 200.0,
    interval: float = 20.0,
    output_path: str = "",
) -> CorridorSheetSpec:
    """Minimal valid spec for a 200 m straight corridor."""
    corridor = CorridorSpec(
        name="TEST",
        start_station_m=start,
        end_station_m=end,
        horizontal=HorizontalAlignmentSpec(
            waypoints=[(0.0, 0.0), (end - start, 0.0)]
        ),
        vertical=VerticalAlignmentSpec(
            pvi_stations=[start, (start + end) / 2, end],
            pvi_elevations=[100.0, 102.0, 101.0],
        ),
        half_carriageway_m=3.65,
        cut_slope_ratio=1.5,
        fill_slope_ratio=2.0,
        design_elevation_at_start_m=100.0,
    )
    return CorridorSheetSpec(
        corridor=corridor,
        station_interval_m=interval,
        scale_horizontal=200.0,
        scale_vertical=50.0,
        output_path=output_path,
    )


# ===========================================================================
# 1  Station sampling
# ===========================================================================

class TestStationSampling:
    def test_basic_count(self):
        spec = _basic_spec(start=0.0, end=100.0, interval=20.0)
        stations = _sample_stations(spec)
        # Expected: 0, 20, 40, 60, 80, 100 = 6 stations
        assert len(stations) == 6

    def test_start_and_end_included(self):
        spec = _basic_spec(start=10.0, end=90.0, interval=25.0)
        stations = _sample_stations(spec)
        assert stations[0] == pytest.approx(10.0, abs=1e-6)
        assert stations[-1] == pytest.approx(90.0, abs=1e-6)

    def test_interval_respected(self):
        spec = _basic_spec(start=0.0, end=200.0, interval=50.0)
        stations = _sample_stations(spec)
        for i in range(len(stations) - 1):
            gap = stations[i + 1] - stations[i]
            # Gap should be ≤ interval (last gap may be smaller)
            assert gap <= 50.0 + 1e-6

    def test_single_station_at_start_equals_end(self):
        spec = _basic_spec(start=0.0, end=1.0, interval=100.0)
        stations = _sample_stations(spec)
        # At minimum start and end should be present
        assert 0.0 in [pytest.approx(s, abs=1e-6) for s in stations] or stations[0] == pytest.approx(0.0, abs=1e-6)
        assert stations[-1] == pytest.approx(1.0, abs=1e-6)


# ===========================================================================
# 2  Design elevation interpolation
# ===========================================================================

class TestDesignElevation:
    def test_at_first_pvi(self):
        spec = _basic_spec()
        # PVI at station 0.0 → elevation 100.0
        elev = _design_elevation_at(0.0, spec)
        assert elev == pytest.approx(100.0, abs=1e-3)

    def test_at_last_pvi(self):
        spec = _basic_spec()
        # PVI at station 200.0 → elevation 101.0
        elev = _design_elevation_at(200.0, spec)
        assert elev == pytest.approx(101.0, abs=1e-3)

    def test_midpoint_interpolation(self):
        spec = _basic_spec()
        # PVI at 100.0 → elevation 102.0
        elev = _design_elevation_at(100.0, spec)
        assert elev == pytest.approx(102.0, abs=1e-3)

    def test_between_first_and_mid_pvi(self):
        spec = _basic_spec()
        # Between 0.0 (100.0) and 100.0 (102.0) at station 50.0 → 101.0
        elev = _design_elevation_at(50.0, spec)
        assert elev == pytest.approx(101.0, abs=1e-3)

    def test_no_pvi_data_returns_start_elevation(self):
        corridor = CorridorSpec(
            start_station_m=0.0,
            end_station_m=100.0,
            design_elevation_at_start_m=55.0,
        )
        spec = CorridorSheetSpec(corridor=corridor)
        elev = _design_elevation_at(50.0, spec)
        assert elev == pytest.approx(55.0, abs=1e-6)


# ===========================================================================
# 3  Ground elevation (synthetic)
# ===========================================================================

class TestGroundElevation:
    def test_ground_above_design_on_average(self):
        # Over a full cycle the sinusoid averages to 0, so the +0.3 offset
        # dominates and ground should be above design on average.
        design = 100.0
        samples = [_ground_elevation_at(s, design) for s in range(0, 100)]
        avg = sum(samples) / len(samples)
        assert avg > design

    def test_ground_varies_along_corridor(self):
        design = 100.0
        eg_values = {_ground_elevation_at(s, design) for s in range(0, 200, 5)}
        # Should have multiple distinct values (not flat)
        assert len(eg_values) > 1


# ===========================================================================
# 4  Plan view entity generation
# ===========================================================================

class TestPlanView:
    def test_returns_non_empty_entities(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_plan_view(stations, spec, (0.0, 0.0))
        assert len(entities) > 0

    def test_contains_centreline_polyline(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_plan_view(stations, spec, (0.0, 0.0))
        layer_names = {e["layer"] for e in entities}
        assert "CIVIL-PLAN-ALIGN" in layer_names

    def test_contains_edge_strings(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_plan_view(stations, spec, (0.0, 0.0))
        layer_names = {e["layer"] for e in entities}
        assert "CIVIL-PLAN-EDGE" in layer_names

    def test_station_ticks_present(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_plan_view(stations, spec, (0.0, 0.0))
        ticks = [e for e in entities if e["layer"] == "CIVIL-PLAN-STATION"]
        # One tick per station
        assert len(ticks) == len(stations)


# ===========================================================================
# 5  Profile view entity generation
# ===========================================================================

class TestProfileView:
    def test_returns_non_empty(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_profile_view(stations, spec, (0.0, 0.0))
        assert len(entities) > 0

    def test_finished_grade_layer_present(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_profile_view(stations, spec, (0.0, 0.0))
        layers = {e["layer"] for e in entities}
        assert "CIVIL-PROFILE-FG" in layers

    def test_existing_ground_layer_present(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_profile_view(stations, spec, (0.0, 0.0))
        layers = {e["layer"] for e in entities}
        assert "CIVIL-PROFILE-EG" in layers

    def test_grade_stubs_count(self):
        spec = _basic_spec()
        stations = _sample_stations(spec)
        entities = _build_profile_view(stations, spec, (0.0, 0.0))
        grade_stubs = [e for e in entities if e["layer"] == "CIVIL-PROFILE-GRADE"]
        assert len(grade_stubs) == len(stations)


# ===========================================================================
# 6  Cross-section entity generation
# ===========================================================================

class TestCrossSection:
    def test_returns_entities_for_single_station(self):
        spec = _basic_spec()
        entities = _build_cross_section(50.0, spec, (0.0, 0.0))
        assert len(entities) > 0

    def test_road_layer_present(self):
        spec = _basic_spec()
        entities = _build_cross_section(50.0, spec, (0.0, 0.0))
        layers = {e["layer"] for e in entities}
        assert "CIVIL-XS-ROAD" in layers

    def test_slope_layer_present(self):
        spec = _basic_spec()
        entities = _build_cross_section(50.0, spec, (0.0, 0.0))
        layers = {e["layer"] for e in entities}
        assert "CIVIL-XS-SLOPE" in layers

    def test_ground_layer_present(self):
        spec = _basic_spec()
        entities = _build_cross_section(50.0, spec, (0.0, 0.0))
        layers = {e["layer"] for e in entities}
        assert "CIVIL-XS-GROUND" in layers

    def test_symmetry_left_right_slopes(self):
        """Both a left and a right slope polyline are drawn."""
        spec = _basic_spec()
        entities = _build_cross_section(50.0, spec, (0.0, 0.0))
        slopes = [e for e in entities if e["layer"] == "CIVIL-XS-SLOPE"]
        assert len(slopes) == 2


# ===========================================================================
# 7  Full generate_corridor_sheets — DXF file output
# ===========================================================================

class TestGenerateCorridorSheets:
    def test_produces_valid_dxf_file(self):
        spec = _basic_spec(end=200.0, interval=50.0)
        result = generate_corridor_sheets(spec)
        try:
            assert os.path.isfile(result.dxf_path)
            # File should be non-empty
            assert os.path.getsize(result.dxf_path) > 100
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_dxf_can_be_read_back(self):
        spec = _basic_spec(end=200.0, interval=50.0)
        result = generate_corridor_sheets(spec)
        try:
            parsed = read_dxf(result.dxf_path)
            assert isinstance(parsed["entities"], list)
            assert len(parsed["entities"]) > 0
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_station_count_matches_interval(self):
        spec = _basic_spec(start=0.0, end=100.0, interval=25.0)
        result = generate_corridor_sheets(spec)
        try:
            # Expected stations: 0, 25, 50, 75, 100 = 5
            assert len(result.stations_drawn) == 5
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_total_length_m_correct(self):
        spec = _basic_spec(start=50.0, end=350.0, interval=50.0)
        result = generate_corridor_sheets(spec)
        try:
            assert result.total_length_m == pytest.approx(300.0, abs=1e-6)
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_num_sheets_at_least_one(self):
        spec = _basic_spec(end=200.0, interval=20.0)
        result = generate_corridor_sheets(spec)
        try:
            assert result.num_sheets >= 1
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_num_sheets_increases_with_length(self):
        spec_short = _basic_spec(end=200.0, interval=20.0, output_path="")
        spec_long = _basic_spec(end=2000.0, interval=20.0, output_path="")
        r_short = generate_corridor_sheets(spec_short)
        r_long = generate_corridor_sheets(spec_long)
        try:
            # A longer corridor with more stations should produce >= sheets
            assert r_long.num_sheets >= r_short.num_sheets
        finally:
            for p in [r_short.dxf_path, r_long.dxf_path]:
                if os.path.isfile(p):
                    os.unlink(p)

    def test_dxf_contains_civil_plan_align_layer(self):
        spec = _basic_spec(end=100.0, interval=25.0)
        result = generate_corridor_sheets(spec)
        try:
            parsed = read_dxf(result.dxf_path)
            layer_names = set(parsed["layers"])
            assert "CIVIL-PLAN-ALIGN" in layer_names
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_dxf_contains_all_expected_layers(self):
        spec = _basic_spec(end=100.0, interval=25.0)
        result = generate_corridor_sheets(spec)
        try:
            parsed = read_dxf(result.dxf_path)
            layer_names = set(parsed["layers"])
            for lyr in [
                "CIVIL-PLAN-ALIGN",
                "CIVIL-PLAN-EDGE",
                "CIVIL-PROFILE-FG",
                "CIVIL-PROFILE-EG",
                "CIVIL-XS-ROAD",
                "CIVIL-XS-SLOPE",
            ]:
                assert lyr in layer_names, f"missing layer: {lyr}"
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_custom_output_path(self):
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            out = f.name
        try:
            spec = _basic_spec(end=100.0, interval=50.0, output_path=out)
            result = generate_corridor_sheets(spec)
            assert result.dxf_path == out
            assert os.path.isfile(out)
        finally:
            if os.path.isfile(out):
                os.unlink(out)

    def test_honest_caveat_non_empty(self):
        spec = _basic_spec(end=100.0, interval=50.0)
        result = generate_corridor_sheets(spec)
        try:
            assert isinstance(result.honest_caveat, str)
            assert len(result.honest_caveat) > 20
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_end_before_start_raises(self):
        spec = _basic_spec(start=200.0, end=100.0, interval=20.0)
        with pytest.raises(ValueError, match="end_station_m"):
            generate_corridor_sheets(spec)

    def test_zero_interval_raises(self):
        spec = _basic_spec(end=100.0, interval=0.0)
        with pytest.raises(ValueError, match="station_interval_m"):
            generate_corridor_sheets(spec)

    def test_with_explicit_pvi_data(self):
        corridor = CorridorSpec(
            name="GRADE_TEST",
            start_station_m=0.0,
            end_station_m=500.0,
            horizontal=HorizontalAlignmentSpec(waypoints=[(0, 0), (500, 0)]),
            vertical=VerticalAlignmentSpec(
                pvi_stations=[0.0, 100.0, 250.0, 400.0, 500.0],
                pvi_elevations=[50.0, 53.0, 51.0, 54.0, 52.0],
            ),
            half_carriageway_m=4.0,
        )
        spec = CorridorSheetSpec(corridor=corridor, station_interval_m=50.0)
        result = generate_corridor_sheets(spec)
        try:
            assert result.total_length_m == pytest.approx(500.0, abs=1e-6)
            assert len(result.stations_drawn) == 11  # 0..500 step 50
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)

    def test_curved_horizontal_alignment(self):
        """L-shaped corridor: two segments at right angle."""
        corridor = CorridorSpec(
            name="CURVE_TEST",
            start_station_m=0.0,
            end_station_m=200.0,
            horizontal=HorizontalAlignmentSpec(
                waypoints=[(0, 0), (100, 0), (100, 100)]
            ),
            half_carriageway_m=3.65,
        )
        spec = CorridorSheetSpec(corridor=corridor, station_interval_m=50.0)
        result = generate_corridor_sheets(spec)
        try:
            parsed = read_dxf(result.dxf_path)
            assert len(parsed["entities"]) > 0
        finally:
            if os.path.isfile(result.dxf_path):
                os.unlink(result.dxf_path)


# ===========================================================================
# 8  LLM tool wrapper tests
# ===========================================================================

class TestCorridorSheetsTool:
    def test_valid_minimal_call(self):
        ctx = _ctx()
        args = json.dumps({"end_station_m": 200.0})
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        try:
            assert out["ok"] is True
            assert "dxf_path" in out
            assert out["num_sheets"] >= 1
            assert out["total_length_m"] == pytest.approx(200.0, abs=1e-3)
        finally:
            path = out.get("dxf_path", "")
            if path and os.path.isfile(path):
                os.unlink(path)

    def test_missing_end_station_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"start_station_m": 0.0})
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        assert out["ok"] is False

    def test_end_before_start_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"start_station_m": 500.0, "end_station_m": 100.0})
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        assert out["ok"] is False

    def test_zero_interval_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"end_station_m": 200.0, "station_interval_m": 0.0})
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        assert out["ok"] is False

    def test_with_pvi_data(self):
        ctx = _ctx()
        args = json.dumps({
            "end_station_m": 300.0,
            "station_interval_m": 50.0,
            "pvi_stations": [0.0, 150.0, 300.0],
            "pvi_elevations": [100.0, 103.0, 101.0],
        })
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        try:
            assert out["ok"] is True
            assert out["total_length_m"] == pytest.approx(300.0, abs=1e-3)
        finally:
            path = out.get("dxf_path", "")
            if path and os.path.isfile(path):
                os.unlink(path)

    def test_pvi_length_mismatch_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "end_station_m": 200.0,
            "pvi_stations": [0.0, 100.0],
            "pvi_elevations": [100.0],   # mismatch
        })
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        assert out["ok"] is False

    def test_stations_drawn_list_populated(self):
        ctx = _ctx()
        args = json.dumps({"end_station_m": 100.0, "station_interval_m": 25.0})
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        try:
            assert out["ok"] is True
            assert isinstance(out["stations_drawn"], list)
            assert len(out["stations_drawn"]) >= 4  # 0, 25, 50, 75, 100
        finally:
            path = out.get("dxf_path", "")
            if path and os.path.isfile(path):
                os.unlink(path)

    def test_honest_caveat_in_output(self):
        ctx = _ctx()
        args = json.dumps({"end_station_m": 100.0})
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        try:
            assert out["ok"] is True
            assert "honest_caveat" in out
            assert len(out["honest_caveat"]) > 20
        finally:
            path = out.get("dxf_path", "")
            if path and os.path.isfile(path):
                os.unlink(path)

    def test_with_horizontal_waypoints(self):
        ctx = _ctx()
        args = json.dumps({
            "end_station_m": 200.0,
            "station_interval_m": 50.0,
            "horizontal_waypoints": [[0, 0], [100, 50], [200, 0]],
        })
        out = json.loads(_run(run_civil_generate_corridor_sheets(ctx, args.encode())))
        try:
            assert out["ok"] is True
        finally:
            path = out.get("dxf_path", "")
            if path and os.path.isfile(path):
                os.unlink(path)

    def test_invalid_json_returns_error(self):
        ctx = _ctx()
        raw = _run(run_civil_generate_corridor_sheets(ctx, b"not json{"))
        out = json.loads(raw)
        # err_payload returns {"error": ..., "code": ...}; json.dumps returns {"ok": false, ...}
        # Either shape should indicate failure
        is_err = (out.get("ok") is False) or ("error" in out) or ("errors" in out)
        assert is_err, f"Expected error response, got: {out}"
