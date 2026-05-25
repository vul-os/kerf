"""
Dispatch tests for the landscape_irrigation_schedule LLM tool.

Verifies that the tool (which was in tools.py but unregistered in plugin.py)
dispatches correctly for all four modes: schedule, head_spacing, zone_flow, audit.
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_landscape.tools import landscape_irrigation_spec, run_landscape_irrigation


def _run(coro):
    return asyncio.run(coro)


def _ctx():
    try:
        from kerf_landscape._compat import ProjectCtx
    except ImportError:
        from types import SimpleNamespace
        return SimpleNamespace(pool=None, project_id=None)
    return ProjectCtx()


def _call(payload: dict) -> dict:
    raw = _run(run_landscape_irrigation(_ctx(), json.dumps(payload).encode()))
    return json.loads(raw)


class TestIrrigationToolSpec:
    def test_spec_name(self):
        assert landscape_irrigation_spec.name == "landscape_irrigation_schedule"

    def test_spec_required_mode(self):
        schema = landscape_irrigation_spec.input_schema
        assert "mode" in schema.get("properties", {})
        assert "mode" in schema.get("required", [])


class TestIrrigationHeadSpacing:
    def test_spray_no_wind(self):
        result = _call({"mode": "head_spacing", "head_type": "spray"})
        assert result.get("ok") is True
        assert result["head_type"] == "spray"
        assert result["throw_radius_ft"] > 0

    def test_rotor_with_wind(self):
        result = _call({"mode": "head_spacing", "head_type": "rotor", "wind_mph": 10.0})
        assert result.get("ok") is True
        # wind factor = 1 - 0.03*10 = 0.7
        assert result["wind_factor"] == pytest.approx(0.7)

    def test_drip_head(self):
        result = _call({"mode": "head_spacing", "head_type": "drip"})
        assert result.get("ok") is True


class TestIrrigationZoneFlow:
    def test_zone_flow_basic(self):
        result = _call({
            "mode": "zone_flow",
            "head_type": "spray",
            "head_count": 4,
            "gpm_per_head": 0.5,
        })
        assert result.get("ok") is True
        assert result["total_flow_gpm"] == pytest.approx(2.0)

    def test_zone_flow_area_method(self):
        result = _call({
            "mode": "zone_flow",
            "head_type": "spray",
            "head_count": 6,
            "zone_area_m2": 100.0,
            "precip_rate_in_hr": 1.5,
            "target_precip_in": 1.0,
        })
        assert result.get("ok") is True
        assert result["run_time_min"] == pytest.approx(40.0, rel=0.01)

    def test_zone_flow_missing_head_count(self):
        result = _call({
            "mode": "zone_flow",
            "head_type": "spray",
        })
        assert "error" in result


class TestIrrigationSchedule:
    def test_schedule_basic(self):
        result = _call({
            "mode": "schedule",
            "zones": [
                {"name": "Front Lawn", "head_type": "rotor", "precip_rate_in_hr": 0.75},
                {"name": "Back Bed", "head_type": "drip", "precip_rate_in_hr": 2.0},
            ],
            "et_mm_per_week": 25.0,
            "days_per_week": 3,
        })
        assert result.get("ok") is True
        assert "schedule" in result
        assert len(result["schedule"]) == 2

    def test_schedule_empty_zones_error(self):
        result = _call({"mode": "schedule", "zones": []})
        assert "error" in result


class TestIrrigationAudit:
    def test_audit_basic(self):
        # 4 equal readings → DU = 100% (perfect uniformity)
        result = _call({
            "mode": "audit",
            "catch_can_readings": [100.0, 100.0, 100.0, 100.0],
        })
        assert result.get("ok") is True
        assert result["du_lq_pct"] == pytest.approx(100.0, abs=1.0)

    def test_audit_non_uniform(self):
        result = _call({
            "mode": "audit",
            "catch_can_readings": [80.0, 60.0, 100.0, 40.0],
        })
        assert result.get("ok") is True
        assert 0 < result["du_lq_pct"] < 100.0

    def test_audit_bad_args(self):
        result = _call({"mode": "audit", "catch_can_readings": "not-a-list"})
        assert "error" in result


class TestIrrigationBadArgs:
    def test_unknown_mode(self):
        result = _call({"mode": "teleport"})
        assert "error" in result

    def test_bad_json(self):
        raw = _run(run_landscape_irrigation(_ctx(), b"not-json"))
        result = json.loads(raw)
        assert "error" in result
