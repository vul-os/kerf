"""
Tests for kerf_cad_core.civil.alignment — horizontal + vertical road curves.

All tests are hermetic: pure-Python, no OCC, no DB, no network, no disk I/O.
Run with:
    python -m pytest packages/kerf-cad-core/tests/test_civil_alignment.py -q -p no:cacheprovider

Numeric tolerances are tight to confirm the formulas are correctly
implemented, not just approximately plausible.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.civil.alignment import (
    HorizontalCurveResult,
    SpiralCurveResult,
    VerticalCurveResult,
    compute_horizontal_curve,
    compute_spiral_curve,
    compute_vertical_curve,
    elevation_at,
    format_station,
    parse_station,
    station_add,
)
from kerf_cad_core.civil.alignment_tools import (
    run_align_horizontal,
    run_align_spiral,
    run_align_station_at,
    run_align_vertical,
)


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        ctx = ProjectCtx.__new__(ProjectCtx)
        ctx.project_id = "00000000-0000-0000-0000-000000000001"
        return ctx
    except Exception:
        return object()


# ===========================================================================
# 1  Stationing helpers
# ===========================================================================

class TestStationParsing:
    def test_parse_plus_notation(self):
        assert parse_station("12+34.56") == pytest.approx(1234.56)

    def test_parse_zero_minor(self):
        assert parse_station("10+00.00") == pytest.approx(1000.0)

    def test_parse_plain_float(self):
        assert parse_station("500.00") == pytest.approx(500.0)

    def test_parse_invalid_nan(self):
        assert math.isnan(parse_station("bad+value"))

    def test_format_roundtrip(self):
        # Station strings are formatted to centimetre resolution (2dp),
        # so round-trip tolerance is 0.005 m.
        assert parse_station(format_station(1234.56)) == pytest.approx(1234.56, abs=0.005)

    def test_format_station_string(self):
        assert format_station(1234.56) == "12+34.56"

    def test_format_station_zero(self):
        assert format_station(0.0) == "0+00.00"

    def test_station_add_crossing_hundred(self):
        # 12+34 + 100 m = 13+34
        sta = parse_station("12+34.00")
        new_sta = station_add(sta, 100.0)
        assert format_station(new_sta) == "13+34.00"

    def test_station_add_simple(self):
        assert station_add(500.0, 250.0) == pytest.approx(750.0)


# ===========================================================================
# 2  Horizontal circular curve — geometry
# ===========================================================================

class TestHorizontalCircularCurve:
    def _curve(self, delta_deg=30.0, radius_m=300.0, sta_pi_m=1000.0, speed=0.0):
        return compute_horizontal_curve(
            delta_deg=delta_deg,
            radius_m=radius_m,
            sta_pi_m=sta_pi_m,
            design_speed_kmh=speed,
        )

    def test_arc_length_equals_R_theta(self):
        c = self._curve(delta_deg=60.0, radius_m=200.0)
        expected = 200.0 * math.radians(60.0)
        assert c.arc_length_m == pytest.approx(expected, rel=1e-9)

    def test_pt_equals_pc_plus_L(self):
        c = self._curve(delta_deg=45.0, radius_m=150.0, sta_pi_m=2000.0)
        assert c.sta_pt_m == pytest.approx(c.sta_pc_m + c.arc_length_m, rel=1e-9)

    def test_tangent_length(self):
        c = self._curve(delta_deg=30.0, radius_m=300.0, sta_pi_m=1000.0)
        expected_T = 300.0 * math.tan(math.radians(15.0))
        assert c.tangent_length_m == pytest.approx(expected_T, rel=1e-9)

    def test_long_chord(self):
        c = self._curve(delta_deg=90.0, radius_m=100.0, sta_pi_m=500.0)
        expected_C = 2.0 * 100.0 * math.sin(math.radians(45.0))
        assert c.long_chord_m == pytest.approx(expected_C, rel=1e-9)

    def test_external_distance(self):
        c = self._curve(delta_deg=60.0, radius_m=200.0, sta_pi_m=800.0)
        expected_E = 200.0 * (1.0 / math.cos(math.radians(30.0)) - 1.0)
        assert c.external_m == pytest.approx(expected_E, rel=1e-9)

    def test_middle_ordinate(self):
        c = self._curve(delta_deg=60.0, radius_m=200.0)
        expected_M = 200.0 * (1.0 - math.cos(math.radians(30.0)))
        assert c.middle_ordinate_m == pytest.approx(expected_M, rel=1e-9)

    def test_degree_of_curve(self):
        c = self._curve(radius_m=573.0)
        assert c.degree_of_curve_deg == pytest.approx(5729.578 / 573.0, rel=1e-5)

    def test_ok_true_on_valid_input(self):
        c = self._curve()
        assert c.ok is True

    def test_station_strings_centimetre_resolution(self):
        # Station strings are formatted to 2dp (centimetre resolution).
        c = self._curve(delta_deg=30.0, radius_m=300.0, sta_pi_m=1000.0)
        assert parse_station(c.sta_pc) == pytest.approx(c.sta_pc_m, abs=0.005)
        assert parse_station(c.sta_pt) == pytest.approx(c.sta_pt_m, abs=0.005)

    def test_superelevation_nonzero_with_speed(self):
        c = self._curve(delta_deg=30.0, radius_m=150.0, speed=80.0)
        assert c.ok is True
        assert c.side_friction > 0.0
        assert c.superelevation >= 0.0

    def test_superelevation_clamped_below_e_max(self):
        # Tight curve + high speed → superelevation must not exceed 0.12
        c = self._curve(delta_deg=60.0, radius_m=50.0, speed=120.0)
        assert c.superelevation <= 0.12 + 1e-9

    def test_superelevation_zero_when_no_speed(self):
        c = self._curve(speed=0.0)
        assert c.superelevation == 0.0


# ===========================================================================
# 3  Horizontal circular curve — error cases
# ===========================================================================

class TestHorizontalCurveErrors:
    def test_radius_zero(self):
        c = compute_horizontal_curve(delta_deg=30.0, radius_m=0.0, sta_pi_m=1000.0)
        assert c.ok is False
        assert "radius" in c.reason.lower()

    def test_radius_negative(self):
        c = compute_horizontal_curve(delta_deg=30.0, radius_m=-100.0, sta_pi_m=1000.0)
        assert c.ok is False
        assert "radius" in c.reason.lower()

    def test_delta_zero(self):
        c = compute_horizontal_curve(delta_deg=0.0, radius_m=200.0, sta_pi_m=1000.0)
        assert c.ok is False

    def test_delta_360(self):
        c = compute_horizontal_curve(delta_deg=360.0, radius_m=200.0, sta_pi_m=1000.0)
        assert c.ok is False

    def test_negative_design_speed(self):
        c = compute_horizontal_curve(
            delta_deg=30.0, radius_m=200.0, sta_pi_m=1000.0, design_speed_kmh=-10.0
        )
        assert c.ok is False


# ===========================================================================
# 4  Spiral (clothoid) curve
# ===========================================================================

class TestSpiralCurve:
    def _spiral(self, delta_deg=40.0, radius_m=300.0, spiral_length_m=60.0, sta_pi_m=2500.0):
        return compute_spiral_curve(
            delta_deg=delta_deg,
            radius_m=radius_m,
            spiral_length_m=spiral_length_m,
            sta_pi_m=sta_pi_m,
        )

    def test_ok_on_valid_input(self):
        s = self._spiral()
        assert s.ok is True

    def test_spiral_angle(self):
        # θs = Ls / (2·R)
        s = self._spiral(radius_m=300.0, spiral_length_m=60.0)
        expected_theta_s = 60.0 / (2.0 * 300.0)  # radians
        assert math.radians(s.spiral_angle_deg) == pytest.approx(expected_theta_s, rel=1e-9)

    def test_sta_st_equals_sta_ts_plus_total_length(self):
        s = self._spiral()
        total = 2.0 * s.spiral_length_m + s.circular_arc_length_m
        assert s.sta_st_m == pytest.approx(s.sta_ts_m + total, rel=1e-9)

    def test_circular_arc_formula(self):
        # Lc = R · (Δ - 2·θs)
        s = self._spiral(delta_deg=40.0, radius_m=300.0, spiral_length_m=60.0)
        theta_s = 60.0 / (2.0 * 300.0)
        expected_lc = 300.0 * (math.radians(40.0) - 2.0 * theta_s)
        assert s.circular_arc_length_m == pytest.approx(expected_lc, rel=1e-9)

    def test_spiral_too_long_error(self):
        # spiral angle 2θs exceeds delta → error
        s = compute_spiral_curve(
            delta_deg=10.0,
            radius_m=300.0,
            spiral_length_m=200.0,  # θs = 200/(2*300) ≈ 19° > 5°
            sta_pi_m=1000.0,
        )
        assert s.ok is False
        assert "spiral angle" in s.reason.lower() or "exceed" in s.reason.lower()

    def test_invalid_radius(self):
        s = compute_spiral_curve(
            delta_deg=30.0, radius_m=0.0, spiral_length_m=50.0, sta_pi_m=1000.0
        )
        assert s.ok is False


# ===========================================================================
# 5  Vertical parabolic curve
# ===========================================================================

class TestVerticalCurve:
    def _vc(self, G1=0.04, G2=-0.02, sta_pvi_m=1000.0, L=200.0, elev_pvi=100.0, ssd=0.0):
        return compute_vertical_curve(
            grade1=G1,
            grade2=G2,
            sta_pvi_m=sta_pvi_m,
            curve_length_m=L,
            elev_pvi_m=elev_pvi,
            stopping_sight_distance_m=ssd,
        )

    def test_ok_on_valid_input(self):
        vc = self._vc()
        assert vc.ok is True

    def test_pvc_pvt_stations(self):
        vc = self._vc(sta_pvi_m=1000.0, L=200.0)
        assert vc.sta_pvc_m == pytest.approx(900.0, rel=1e-9)
        assert vc.sta_pvt_m == pytest.approx(1100.0, rel=1e-9)

    def test_elevation_at_pvc_matches_grade1(self):
        # e_PVC = e_PVI - G1·(L/2)
        vc = self._vc(G1=0.04, sta_pvi_m=1000.0, L=200.0, elev_pvi=100.0)
        expected_pvc = 100.0 - 0.04 * 100.0
        assert vc.elev_pvc_m == pytest.approx(expected_pvc, rel=1e-9)

    def test_elevation_at_pvt_matches_grade2(self):
        vc = self._vc(G2=-0.02, sta_pvi_m=1000.0, L=200.0, elev_pvi=100.0)
        expected_pvt = 100.0 + (-0.02) * 100.0
        assert vc.elev_pvt_m == pytest.approx(expected_pvt, rel=1e-9)

    def test_k_value_formula(self):
        # K = L / (100·|G2-G1|); k_value is rounded to 4dp in the result
        vc = self._vc(G1=0.04, G2=-0.02, L=200.0)
        A_pct = abs(-0.02 - 0.04) * 100.0   # = 6.0%
        expected_k = 200.0 / A_pct
        assert vc.k_value == pytest.approx(expected_k, abs=1e-4)

    def test_crest_classification(self):
        vc = self._vc(G1=0.04, G2=-0.02)
        assert vc.curve_type == "CREST"

    def test_sag_classification(self):
        vc = self._vc(G1=-0.03, G2=0.02)
        assert vc.curve_type == "SAG"

    def test_high_point_station_formula(self):
        # x_hl = G1·L / (G1 - G2)
        G1, G2, L = 0.04, -0.02, 200.0
        vc = self._vc(G1=G1, G2=G2, sta_pvi_m=1000.0, L=L)
        x_hl = G1 * L / (G1 - G2)
        expected_sta_hl = vc.sta_pvc_m + x_hl
        assert vc.has_high_low_point is True
        assert vc.sta_hl_m == pytest.approx(expected_sta_hl, rel=1e-9)

    def test_high_point_elevation(self):
        G1, G2, L = 0.04, -0.02, 200.0
        vc = self._vc(G1=G1, G2=G2, sta_pvi_m=1000.0, L=L, elev_pvi=100.0)
        x_hl = G1 * L / (G1 - G2)
        expected_elev = vc.elev_pvc_m + G1 * x_hl + (G2 - G1) / (2.0 * L) * x_hl ** 2
        assert vc.elev_hl_m == pytest.approx(expected_elev, rel=1e-9)

    def test_no_high_low_when_same_sign_grades(self):
        vc = self._vc(G1=0.02, G2=0.04)
        assert vc.has_high_low_point is False

    def test_tangent_when_equal_grades(self):
        vc = self._vc(G1=0.03, G2=0.03)
        assert vc.curve_type == "TANGENT"

    def test_ssd_crest_check_fails_tight(self):
        # Tight crest + long SSD → K < K_min
        vc = compute_vertical_curve(
            grade1=0.05,
            grade2=-0.05,
            sta_pvi_m=1000.0,
            curve_length_m=50.0,
            elev_pvi_m=100.0,
            stopping_sight_distance_m=200.0,
        )
        assert vc.ok is True
        assert vc.ssd_ok is False

    def test_ssd_sag_ok_long_curve(self):
        vc = compute_vertical_curve(
            grade1=-0.04,
            grade2=0.04,
            sta_pvi_m=1000.0,
            curve_length_m=500.0,
            elev_pvi_m=100.0,
            stopping_sight_distance_m=100.0,
        )
        assert vc.ssd_ok is True

    def test_invalid_curve_length_zero(self):
        vc = compute_vertical_curve(
            grade1=0.04, grade2=-0.02,
            sta_pvi_m=1000.0, curve_length_m=0.0, elev_pvi_m=100.0
        )
        assert vc.ok is False


# ===========================================================================
# 6  elevation_at — arbitrary station query
# ===========================================================================

class TestElevationAt:
    def test_pvc_returns_pvc_elevation(self):
        result = elevation_at(
            sta_pvc_m=900.0, elev_pvc_m=96.0,
            grade1=0.04, grade2=-0.02,
            curve_length_m=200.0, query_sta_m=900.0,
        )
        assert result["ok"] is True
        assert result["elevation_m"] == pytest.approx(96.0, rel=1e-9)

    def test_pvt_elevation(self):
        G1, G2, L = 0.04, -0.02, 200.0
        e_pvc = 96.0
        result = elevation_at(
            sta_pvc_m=900.0, elev_pvc_m=e_pvc,
            grade1=G1, grade2=G2,
            curve_length_m=L, query_sta_m=1100.0,
        )
        expected = e_pvc + G1 * L + (G2 - G1) / (2.0 * L) * L ** 2
        assert result["ok"] is True
        assert result["elevation_m"] == pytest.approx(expected, rel=1e-9)

    def test_outside_curve_error(self):
        result = elevation_at(
            sta_pvc_m=900.0, elev_pvc_m=96.0,
            grade1=0.04, grade2=-0.02,
            curve_length_m=200.0, query_sta_m=1200.0,
        )
        assert result["ok"] is False
        assert "outside" in result["reason"].lower()

    def test_mid_curve_elevation(self):
        G1, G2, L = 0.03, -0.03, 200.0
        e_pvc = 100.0
        x = 100.0
        expected = e_pvc + G1 * x + (G2 - G1) / (2.0 * L) * x ** 2
        result = elevation_at(
            sta_pvc_m=0.0, elev_pvc_m=e_pvc,
            grade1=G1, grade2=G2,
            curve_length_m=L, query_sta_m=100.0,
        )
        assert result["ok"] is True
        assert result["elevation_m"] == pytest.approx(expected, rel=1e-9)


# ===========================================================================
# 7  Tool wrappers (async, JSON round-trip)
# ===========================================================================

class TestAlignHorizontalTool:
    def test_valid_call(self):
        ctx = _ctx()
        args = json.dumps({"delta_deg": 30.0, "radius_m": 300.0, "sta_pi": "10+00.00"})
        out = json.loads(_run(run_align_horizontal(ctx, args.encode())))
        assert out["ok"] is True
        assert "arc_length_m" in out

    def test_invalid_radius(self):
        ctx = _ctx()
        args = json.dumps({"delta_deg": 30.0, "radius_m": -5.0, "sta_pi": "10+00.00"})
        out = json.loads(_run(run_align_horizontal(ctx, args.encode())))
        assert out["ok"] is False

    def test_missing_radius(self):
        ctx = _ctx()
        args = json.dumps({"delta_deg": 30.0, "sta_pi": "10+00.00"})
        out = json.loads(_run(run_align_horizontal(ctx, args.encode())))
        assert out["ok"] is False

    def test_invalid_sta_string(self):
        ctx = _ctx()
        args = json.dumps({"delta_deg": 30.0, "radius_m": 300.0, "sta_pi": "notastation"})
        out = json.loads(_run(run_align_horizontal(ctx, args.encode())))
        assert out["ok"] is False


class TestAlignVerticalTool:
    def test_valid_call(self):
        ctx = _ctx()
        args = json.dumps({
            "grade1": 0.04, "grade2": -0.02,
            "sta_pvi": "10+00.00", "elev_pvi_m": 100.0,
            "curve_length_m": 200.0,
        })
        out = json.loads(_run(run_align_vertical(ctx, args.encode())))
        assert out["ok"] is True
        assert out["curve_type"] == "CREST"

    def test_ssd_check_included(self):
        ctx = _ctx()
        args = json.dumps({
            "grade1": 0.04, "grade2": -0.04,
            "sta_pvi": "10+00.00", "elev_pvi_m": 100.0,
            "curve_length_m": 40.0,
            "stopping_sight_distance_m": 200.0,
        })
        out = json.loads(_run(run_align_vertical(ctx, args.encode())))
        assert out["ok"] is True
        assert "ssd_ok" in out

    def test_zero_curve_length_error(self):
        ctx = _ctx()
        args = json.dumps({
            "grade1": 0.04, "grade2": -0.02,
            "sta_pvi": "10+00.00", "elev_pvi_m": 100.0,
            "curve_length_m": 0.0,
        })
        out = json.loads(_run(run_align_vertical(ctx, args.encode())))
        assert out["ok"] is False


class TestAlignStationAtTool:
    def test_valid_query(self):
        ctx = _ctx()
        args = json.dumps({
            "sta_pvc": "09+00.00", "elev_pvc_m": 96.0,
            "grade1": 0.04, "grade2": -0.02,
            "curve_length_m": 200.0, "query_sta": "10+00.00",
        })
        out = json.loads(_run(run_align_station_at(ctx, args.encode())))
        assert out["ok"] is True
        assert "elevation_m" in out

    def test_out_of_range_station(self):
        ctx = _ctx()
        args = json.dumps({
            "sta_pvc": "09+00.00", "elev_pvc_m": 96.0,
            "grade1": 0.04, "grade2": -0.02,
            "curve_length_m": 200.0, "query_sta": "15+00.00",
        })
        out = json.loads(_run(run_align_station_at(ctx, args.encode())))
        assert out["ok"] is False
