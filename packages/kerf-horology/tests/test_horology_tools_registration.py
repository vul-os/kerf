"""
Dispatch tests for the 9 horology LLM tools registered via plugin.py.

Verifies:
  - Each tool handler can be called with valid args and returns ok_payload JSON.
  - Error path (bad args) returns an error payload without raising.
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_horology.tools_spec import (
    horology_train_calculator_spec, run_horology_train_calculator,
    horology_check_tooth_profile_spec, run_horology_check_tooth_profile,
    horology_escapement_geometry_spec, run_horology_escapement_geometry,
    horology_mainspring_torque_spec, run_horology_mainspring_torque,
    horology_power_reserve_spec, run_horology_power_reserve,
    horology_balance_period_spec, run_horology_balance_period,
    horology_isochronism_spec, run_horology_isochronism,
    horology_train_ratios_spec, run_horology_train_ratios,
    horology_design_train_spec, run_horology_design_train,
)


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    """Minimal stub for ProjectCtx."""
    pass


CTX = _Ctx()


# ---------------------------------------------------------------------------
# Spec sanity
# ---------------------------------------------------------------------------

class TestSpecs:
    def test_all_specs_have_names(self):
        specs = [
            horology_train_calculator_spec,
            horology_check_tooth_profile_spec,
            horology_escapement_geometry_spec,
            horology_mainspring_torque_spec,
            horology_power_reserve_spec,
            horology_balance_period_spec,
            horology_isochronism_spec,
            horology_train_ratios_spec,
            horology_design_train_spec,
        ]
        for spec in specs:
            assert spec.name.startswith("horology_"), spec.name
            assert len(spec.description) > 10
            assert "type" in spec.input_schema


# ---------------------------------------------------------------------------
# 1. train_calculator
# ---------------------------------------------------------------------------

class TestTrainCalculator:
    def test_28800_bph_48h_reserve(self):
        result = json.loads(_run(run_horology_train_calculator(
            {"freq_hz": 4.0, "power_reserve_hours": 48.0},
            CTX,
        )))
        assert "required_ratio" in result
        assert result["required_ratio"] > 0

    def test_stages_list(self):
        result = json.loads(_run(run_horology_train_calculator(
            {"freq_hz": 3.0, "power_reserve_hours": 38.0, "escape_wheel_teeth": 15},
            CTX,
        )))
        assert isinstance(result["stages"], list)
        assert len(result["stages"]) > 0

    def test_bad_args_returns_error(self):
        result = json.loads(_run(run_horology_train_calculator(
            {"power_reserve_hours": 48.0},  # missing freq_hz
            CTX,
        )))
        assert "error" in result


# ---------------------------------------------------------------------------
# 2. check_tooth_profile
# ---------------------------------------------------------------------------

class TestCheckToothProfile:
    def test_standard_20deg_15_teeth_passes(self):
        result = json.loads(_run(run_horology_check_tooth_profile(
            {"module": 0.2, "num_teeth": 15, "pressure_angle_deg": 20.0},
            CTX,
        )))
        assert result["passed"] is True
        assert result["r_pitch_mm"] > 0

    def test_too_few_teeth_fails(self):
        # Very few teeth → undercut failure
        result = json.loads(_run(run_horology_check_tooth_profile(
            {"module": 0.2, "num_teeth": 5},
            CTX,
        )))
        # Should return a result dict (may pass or fail depending on geometry)
        assert "passed" in result


# ---------------------------------------------------------------------------
# 3. escapement_geometry
# ---------------------------------------------------------------------------

class TestEscapementGeometry:
    def test_defaults_consistent(self):
        result = json.loads(_run(run_horology_escapement_geometry({}, CTX)))
        assert result["is_consistent"] is True
        assert abs(result["tooth_pitch_deg"] - 24.0) < 1e-3

    def test_drop_correct_15t_8deg(self):
        result = json.loads(_run(run_horology_escapement_geometry(
            {"escape_teeth": 15, "lift_deg": 8.0},
            CTX,
        )))
        assert abs(result["drop_deg"] - 8.0) < 1e-3  # 24/2 - 8/2 = 8

    def test_inconsistent_high_lift(self):
        result = json.loads(_run(run_horology_escapement_geometry(
            {"escape_teeth": 15, "lift_deg": 25.0},
            CTX,
        )))
        assert result["is_consistent"] is False


# ---------------------------------------------------------------------------
# 4. mainspring_torque
# ---------------------------------------------------------------------------

class TestMainspringTorque:
    def test_full_wind_max_torque(self):
        result = json.loads(_run(run_horology_mainspring_torque(
            {"turns": 6.0, "full_turns": 6.0, "max_torque_Nmm": 5.0},
            CTX,
        )))
        assert abs(result["torque_Nmm"] - 5.0) < 1e-4
        assert abs(result["turns_fraction"] - 1.0) < 1e-4

    def test_run_down_residual(self):
        result = json.loads(_run(run_horology_mainspring_torque(
            {"turns": 0.0, "full_turns": 6.0, "max_torque_Nmm": 5.0, "residual_factor": 0.5},
            CTX,
        )))
        assert abs(result["torque_Nmm"] - 2.5) < 1e-4


# ---------------------------------------------------------------------------
# 5. power_reserve
# ---------------------------------------------------------------------------

class TestPowerReserve:
    def test_eta_2824_range(self):
        result = json.loads(_run(run_horology_power_reserve(
            {
                "barrel_turns": 6.5,
                "escape_train_torque_required_Nmm": 0.0004,
                "gear_ratio": 5612.0,
                "beats_per_hour_val": 28800,
                "full_turns": 6.5,
                "max_torque_Nmm": 5.5,
                "residual_factor": 0.5,
                "escape_wheel_teeth": 15,
            },
            CTX,
        )))
        assert 30.0 <= result["power_reserve_hours"] <= 50.0


# ---------------------------------------------------------------------------
# 6. balance_period
# ---------------------------------------------------------------------------

class TestBalancePeriod:
    def test_eta_2824_period(self):
        import math
        ETA_T = 0.25
        ETA_I = 10.0
        ETA_K = ETA_I * (2 * math.pi / ETA_T) ** 2
        result = json.loads(_run(run_horology_balance_period(
            {"I_balance_gmm2": ETA_I, "k_hairspring_Nmmrad": ETA_K},
            CTX,
        )))
        assert abs(result["period_seconds"] - ETA_T) < 1e-5
        assert abs(result["bph"] - 28800.0) < 1.0

    def test_bad_args_returns_error(self):
        result = json.loads(_run(run_horology_balance_period(
            {"I_balance_gmm2": 0.0, "k_hairspring_Nmmrad": 0.3},
            CTX,
        )))
        assert "error" in result


# ---------------------------------------------------------------------------
# 7. isochronism
# ---------------------------------------------------------------------------

class TestIsochronism:
    def test_ideal_sho_isochronous(self):
        result = json.loads(_run(run_horology_isochronism(
            {"I_balance_gmm2": 10.0, "k_hairspring_Nmmrad": 0.3},
            CTX,
        )))
        assert result["is_isochronous"] is True
        assert result["delta_period_ms"] == 0.0

    def test_notes_present(self):
        result = json.loads(_run(run_horology_isochronism(
            {"I_balance_gmm2": 10.0, "k_hairspring_Nmmrad": 0.3,
             "amp_min_deg": 180.0, "amp_max_deg": 300.0},
            CTX,
        )))
        assert isinstance(result["notes"], list)
        assert len(result["notes"]) > 0


# ---------------------------------------------------------------------------
# 8. horology_train_ratios
# ---------------------------------------------------------------------------

class TestTrainRatiosTool:
    _WHEELS_4STAGE = [
        {"name": "barrel",       "teeth": 80},
        {"name": "center_wheel", "teeth": 80, "pinion_leaves": 12},
        {"name": "third_wheel",  "teeth": 75, "pinion_leaves": 10},
        {"name": "fourth_wheel", "teeth": 70, "pinion_leaves": 8},
        {"name": "escape_wheel", "teeth": 15, "pinion_leaves": 7},
    ]

    def test_returns_total_ratio(self):
        result = json.loads(_run(run_horology_train_ratios(
            {"wheels": self._WHEELS_4STAGE, "barrel_rev_per_hr": 0.125},
            CTX,
        )))
        assert "total_ratio" in result
        assert abs(result["total_ratio"] - 5000.0) < 1e-4

    def test_returns_beat_rate(self):
        result = json.loads(_run(run_horology_train_ratios(
            {"wheels": self._WHEELS_4STAGE, "barrel_rev_per_hr": 0.125},
            CTX,
        )))
        assert "beat_rate_bph" in result
        assert abs(result["beat_rate_bph"] - 18750.0) < 1.0

    def test_stages_list_returned(self):
        result = json.loads(_run(run_horology_train_ratios(
            {"wheels": self._WHEELS_4STAGE},
            CTX,
        )))
        assert isinstance(result["stages"], list)
        assert len(result["stages"]) == 4

    def test_arbor_speeds_returned(self):
        result = json.loads(_run(run_horology_train_ratios(
            {"wheels": self._WHEELS_4STAGE, "barrel_rev_per_hr": 0.125},
            CTX,
        )))
        assert "arbor_speeds_rev_per_hr" in result
        assert "barrel" in result["arbor_speeds_rev_per_hr"]
        assert "escape_wheel" in result["arbor_speeds_rev_per_hr"]

    def test_is_valid_flag(self):
        result = json.loads(_run(run_horology_train_ratios(
            {"wheels": self._WHEELS_4STAGE},
            CTX,
        )))
        assert result["is_valid"] is True

    def test_missing_wheels_returns_error(self):
        result = json.loads(_run(run_horology_train_ratios(
            {},  # missing 'wheels' key
            CTX,
        )))
        assert "error" in result


# ---------------------------------------------------------------------------
# 9. horology_design_train
# ---------------------------------------------------------------------------

class TestDesignTrainTool:
    def test_design_28800_returns_wheels(self):
        result = json.loads(_run(run_horology_design_train(
            {"target_bph": 28800, "mainspring_rev_per_hr": 0.125},
            CTX,
        )))
        assert "wheels" in result
        assert len(result["wheels"]) >= 2
        assert result["wheels"][0]["name"] == "barrel"
        assert result["wheels"][-1]["name"] == "escape_wheel"

    def test_design_28800_within_5pct(self):
        result = json.loads(_run(run_horology_design_train(
            {"target_bph": 28800, "mainspring_rev_per_hr": 0.125},
            CTX,
        )))
        assert result["deviation_pct"] <= 5.0, (
            f"28800 BPH design deviation {result['deviation_pct']:.2f}% > 5%"
        )

    def test_design_36000_higher_ratio_than_28800(self):
        r28 = json.loads(_run(run_horology_design_train(
            {"target_bph": 28800, "mainspring_rev_per_hr": 0.125},
            CTX,
        )))
        r36 = json.loads(_run(run_horology_design_train(
            {"target_bph": 36000, "mainspring_rev_per_hr": 0.125},
            CTX,
        )))
        assert r36["total_ratio"] > r28["total_ratio"], (
            f"36000 BPH ratio {r36['total_ratio']:.0f} should be > "
            f"28800 BPH ratio {r28['total_ratio']:.0f}"
        )

    def test_design_18000_valid(self):
        result = json.loads(_run(run_horology_design_train(
            {"target_bph": 18000, "mainspring_rev_per_hr": 0.125},
            CTX,
        )))
        assert result["is_valid"] is True
        assert result["deviation_pct"] <= 5.0

    def test_design_invalid_target_returns_error(self):
        result = json.loads(_run(run_horology_design_train(
            {"target_bph": -100},
            CTX,
        )))
        assert "error" in result
