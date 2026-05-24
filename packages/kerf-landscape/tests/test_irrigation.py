"""Tests for kerf_landscape.irrigation — irrigation zone scheduling module."""

import math
import pytest
from kerf_landscape.irrigation import (
    head_spacing,
    zone_flow_demand,
    irrigation_schedule,
    water_audit,
)


# ---------------------------------------------------------------------------
# head_spacing
# ---------------------------------------------------------------------------

def test_head_spacing_spray_no_wind():
    r = head_spacing("spray", design_wind_speed_mph=0.0)
    assert r["ok"] is True
    assert r["head_type"] == "spray"
    # No wind → Kw=1.0 → max_spacing = throw_radius
    assert abs(r["throw_radius_ft"] - r["max_spacing_ft"]) < 1e-9
    assert r["wind_factor"] == pytest.approx(1.0)


def test_head_spacing_rotor_wind():
    r = head_spacing("rotor", design_wind_speed_mph=10.0)
    assert r["ok"] is True
    # Kw = 1 - 0.03*10 = 0.7
    assert r["wind_factor"] == pytest.approx(0.7)
    expected_spacing = 45.0 * 0.7
    assert r["max_spacing_ft"] == pytest.approx(expected_spacing, rel=1e-6)


def test_head_spacing_drip():
    r = head_spacing("drip")
    assert r["ok"] is True
    assert r["throw_radius_ft"] == pytest.approx(0.0)


def test_head_spacing_unknown_type():
    r = head_spacing("mist")
    assert r["ok"] is False


def test_head_spacing_high_wind_clamped():
    # Kw = 1 - 0.03*50 = -0.5 → clamped to 0.5
    r = head_spacing("spray", design_wind_speed_mph=50.0)
    assert r["wind_factor"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# zone_flow_demand
# ---------------------------------------------------------------------------

def test_zone_flow_demand_gpm_per_head():
    r = zone_flow_demand(head_count=4, head_type="spray", gpm_per_head=0.5)
    assert r["ok"] is True
    assert r["total_flow_gpm"] == pytest.approx(2.0)
    # L/min = 2.0 * 3.785… rounded to 3dp
    assert r["total_flow_lpm"] == pytest.approx(2.0 * 3.785411784, rel=1e-3)


def test_zone_flow_demand_area_method():
    # Area-based: Q = PR * A_ft2 / 96.25
    # 100 m² = 1076.39 ft²; PR=1.5 in/hr
    r = zone_flow_demand(head_count=6, head_type="spray",
                         zone_area_m2=100.0, precip_rate_in_hr=1.5)
    assert r["ok"] is True
    expected_gpm = 1.5 * (100.0 * 10.7639) / 96.25
    assert r["total_flow_gpm"] == pytest.approx(expected_gpm, rel=1e-4)


def test_zone_flow_demand_run_time():
    # target_precip=1.0 in, PR=1.5 in/hr → t=0.667 hr = 40 min
    r = zone_flow_demand(head_count=4, head_type="spray",
                         precip_rate_in_hr=1.5, target_precip_in=1.0,
                         zone_area_m2=100.0)
    assert r["ok"] is True
    assert r["run_time_min"] == pytest.approx(40.0, rel=1e-5)
    assert r["applied_depth_mm"] == pytest.approx(25.4, rel=1e-5)


def test_zone_flow_demand_zero_heads():
    r = zone_flow_demand(head_count=0)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# irrigation_schedule
# ---------------------------------------------------------------------------

def test_irrigation_schedule_basic():
    zones = [
        {"name": "Front Lawn",  "head_type": "rotor",  "precip_rate_in_hr": 0.6},
        {"name": "Back Beds",   "head_type": "spray",  "precip_rate_in_hr": 1.5},
        {"name": "Drip Zones",  "head_type": "drip",   "precip_rate_in_hr": 0.5},
    ]
    r = irrigation_schedule(zones, controller_start_h=5.0, et_mm_per_week=25.0)
    assert r["ok"] is True
    assert len(r["schedule"]) == 3
    assert r["schedule"][0]["zone"] == "Front Lawn"
    # All run times are positive
    for s in r["schedule"]:
        assert s["run_time_min"] > 0


def test_irrigation_schedule_sequential_start_times():
    zones = [
        {"name": "Z1", "head_type": "spray", "precip_rate_in_hr": 1.5},
        {"name": "Z2", "head_type": "spray", "precip_rate_in_hr": 1.5},
    ]
    r = irrigation_schedule(zones, controller_start_h=6.0, et_mm_per_week=30.0)
    assert r["ok"] is True
    # Second zone must start after first
    t1 = r["schedule"][0]["start_time"]
    t2 = r["schedule"][1]["start_time"]
    assert t1 < t2  # lexicographic comparison works for HH:MM


def test_irrigation_schedule_window_flag():
    # Very low precip rate → very long run times
    zones = [{"name": f"Z{i}", "head_type": "drip", "precip_rate_in_hr": 0.01}
             for i in range(10)]
    r = irrigation_schedule(zones, et_mm_per_week=25.0)
    assert r["ok"] is True
    assert r["window_exceeded"] is True


def test_irrigation_schedule_empty_zones():
    r = irrigation_schedule([])
    assert r["ok"] is False


def test_irrigation_schedule_invalid_days():
    zones = [{"name": "Z1", "head_type": "spray"}]
    r = irrigation_schedule(zones, days_per_week=0)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# water_audit
# ---------------------------------------------------------------------------

def test_water_audit_good_uniformity():
    # All readings equal → DU = 100 %
    r = water_audit([10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    assert r["ok"] is True
    assert r["du_lq_pct"] == pytest.approx(100.0, rel=1e-5)
    assert r["rating"] == "good"


def test_water_audit_poor_uniformity():
    # Some very low readings
    readings = [1.0, 2.0, 3.0, 4.0, 20.0, 20.0, 20.0, 20.0]
    r = water_audit(readings)
    assert r["ok"] is True
    assert r["du_lq_pct"] < 70.0  # should be poor or marginal


def test_water_audit_too_few_readings():
    r = water_audit([10.0, 12.0, 9.0])
    assert r["ok"] is False


def test_water_audit_all_zero():
    r = water_audit([0.0, 0.0, 0.0, 0.0])
    assert r["ok"] is False


def test_water_audit_known_du():
    # n=4 → n_lq = 4//4 = 1 → lower_q = [5.0]; mean_lq = 5.0
    # mean_all = (5+8+12+15)/4 = 10.0
    # DU = 5.0/10.0 * 100 = 50 %
    r = water_audit([5.0, 8.0, 12.0, 15.0])
    assert r["ok"] is True
    assert r["du_lq_pct"] == pytest.approx(50.0, rel=1e-5)
    assert r["rating"] in ("marginal", "poor")
