"""
Hermetic tests for kerf_cad_core.firesafety — fire-protection engineering.

Coverage (≥30 tests):
  fire.sprinkler_hydraulic_demand  — K-factor flow, NFPA 13 density/area, HW friction
  fire.fire_pump_sizing            — NFPA 20 rated/150%/churn points
  fire.water_supply_adequacy       — supply curve, adequate/inadequate
  fire.egress_analysis             — occupant load, exit capacity, travel limits
  fire.design_fire_tsquared        — Q=αt², growth classes, HRR
  fire.detector_activation_time    — Alpert ceiling-jet, RTI activation
  fire.smoke_control_exhaust       — NFPA 92 plume mass flow
  fire.fire_resistance_heat_transfer — steady-state 1-D conduction
  fire.required_fire_rating        — IBC rating table
  tools.*                          — LLM tool wrappers (happy path + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network, no fixtures.
Formulas verified against NFPA/SFPE hand-calculations.

References
----------
NFPA 13 (2022), NFPA 20 (2022), NFPA 92 (2021), NFPA 101 (2021)
SFPE Handbook of Fire Protection Engineering, 5th ed.
Alpert, R.L. (1972) "Calculation of Response Time of Ceiling-Mounted Fire Detectors"

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.firesafety.fire import (
    sprinkler_hydraulic_demand,
    fire_pump_sizing,
    water_supply_adequacy,
    egress_analysis,
    design_fire_tsquared,
    detector_activation_time,
    smoke_control_exhaust,
    fire_resistance_heat_transfer,
    required_fire_rating,
    _hazen_williams_loss_psi,
)
from kerf_cad_core.firesafety.tools import (
    run_sprinkler_hydraulic_demand,
    run_fire_pump_sizing,
    run_water_supply_adequacy,
    run_egress_analysis,
    run_design_fire_tsquared,
    run_detector_activation_time,
    run_smoke_control_exhaust,
    run_fire_resistance_heat_transfer,
    run_required_fire_rating,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


REL = 1e-4  # relative tolerance


# ===========================================================================
# 1. Hazen-Williams internal helper
# ===========================================================================

class TestHazenWilliams:

    def test_zero_flow_returns_zero(self):
        loss = _hazen_williams_loss_psi(0.0, 4.026, 100.0)
        assert loss == 0.0

    def test_zero_length_returns_zero(self):
        loss = _hazen_williams_loss_psi(100.0, 4.026, 0.0)
        assert loss == 0.0

    def test_known_loss_algebraic(self):
        """Verify: 4.52 × Q^1.85 / (C^1.85 × d^4.87) × L."""
        Q, d, L, C = 200.0, 4.026, 100.0, 120.0
        expected = 4.52 * Q ** 1.85 / (C ** 1.85 * d ** 4.87) * L
        result = _hazen_williams_loss_psi(Q, d, L, C)
        assert abs(result - expected) / expected < REL

    def test_higher_flow_gives_more_loss(self):
        loss1 = _hazen_williams_loss_psi(100.0, 4.026, 100.0)
        loss2 = _hazen_williams_loss_psi(200.0, 4.026, 100.0)
        assert loss2 > loss1

    def test_longer_pipe_gives_more_loss(self):
        loss1 = _hazen_williams_loss_psi(150.0, 3.0, 50.0)
        loss2 = _hazen_williams_loss_psi(150.0, 3.0, 100.0)
        assert abs(loss2 / loss1 - 2.0) < REL


# ===========================================================================
# 2. sprinkler_hydraulic_demand
# ===========================================================================

class TestSprinklerHydraulicDemand:

    def test_light_hazard_basic(self):
        """Light hazard: density 0.10 gpm/ft², area 1500 ft², hose 100 gpm."""
        res = sprinkler_hydraulic_demand(
            "light_hazard", k_factor=5.6, pipe_d_inch=4.026, pipe_length_ft=200.0
        )
        assert res["ok"] is True
        assert abs(res["density_gpm_ft2"] - 0.10) < 1e-9
        assert abs(res["design_area_ft2"] - 1500.0) < 1e-9
        assert abs(res["remote_area_flow_gpm"] - 150.0) < 1e-9
        assert res["hose_stream_gpm"] == 100.0
        assert res["total_demand_gpm"] == 250.0

    def test_ordinary_hazard_group_2_density(self):
        res = sprinkler_hydraulic_demand(
            "ordinary_hazard_group_2", k_factor=8.0, pipe_d_inch=4.0, pipe_length_ft=100.0
        )
        assert res["ok"] is True
        assert abs(res["density_gpm_ft2"] - 0.20) < 1e-9
        assert abs(res["design_area_ft2"] - 1500.0) < 1e-9

    def test_extra_hazard_hose_stream_500(self):
        res = sprinkler_hydraulic_demand(
            "extra_hazard_group_1", k_factor=11.2, pipe_d_inch=6.0, pipe_length_ft=150.0
        )
        assert res["ok"] is True
        assert res["hose_stream_gpm"] == 500.0

    def test_k_factor_flow_formula(self):
        """Verify Q = K√P at min sprinkler pressure."""
        res = sprinkler_hydraulic_demand(
            "ordinary_hazard_group_1", k_factor=5.6, pipe_d_inch=4.026, pipe_length_ft=0.0
        )
        assert res["ok"] is True
        K = res["k_factor"]
        P = res["min_sprinkler_p_psi"]
        # Q at a single head = K√P; validate against density × tributary area
        q_head = K * math.sqrt(P)
        # q_head should match density × 130 ft²/head (typical tributary area)
        density = res["density_gpm_ft2"]
        q_expected = density * 130.0
        assert abs(q_head - q_expected) / q_expected < 0.01

    def test_density_override(self):
        res = sprinkler_hydraulic_demand(
            "light_hazard", k_factor=5.6, pipe_d_inch=4.0, pipe_length_ft=0.0,
            density_override=0.15
        )
        assert res["ok"] is True
        assert abs(res["density_gpm_ft2"] - 0.15) < 1e-9

    def test_elevation_adds_to_source_pressure(self):
        res_flat = sprinkler_hydraulic_demand(
            "business" if False else "light_hazard",
            k_factor=5.6, pipe_d_inch=4.0, pipe_length_ft=100.0,
            elevation_diff_ft=0.0
        )
        res_elev = sprinkler_hydraulic_demand(
            "light_hazard",
            k_factor=5.6, pipe_d_inch=4.0, pipe_length_ft=100.0,
            elevation_diff_ft=20.0
        )
        assert res_elev["ok"] is True
        assert abs(res_elev["elevation_head_psi"] - 20.0 * 0.434) < 1e-6
        assert res_elev["source_pressure_psi"] > res_flat["source_pressure_psi"]

    def test_invalid_occupancy_returns_error(self):
        res = sprinkler_hydraulic_demand(
            "unknown_class", k_factor=5.6, pipe_d_inch=4.0, pipe_length_ft=100.0
        )
        assert res["ok"] is False

    def test_negative_k_factor_returns_error(self):
        res = sprinkler_hydraulic_demand(
            "light_hazard", k_factor=-5.6, pipe_d_inch=4.0, pipe_length_ft=100.0
        )
        assert res["ok"] is False


# ===========================================================================
# 3. fire_pump_sizing
# ===========================================================================

class TestFirePumpSizing:

    def test_150pct_flow_point(self):
        """NFPA 20: 150% flow point = 1.5 × rated flow."""
        res = fire_pump_sizing(500.0, 100.0)
        assert res["ok"] is True
        assert abs(res["flow_150pct_gpm"] - 750.0) < 1e-9

    def test_65pct_head_at_150pct_flow(self):
        """NFPA 20: min head at 150% flow = 0.65 × rated head."""
        res = fire_pump_sizing(500.0, 100.0)
        assert res["ok"] is True
        assert abs(res["min_head_at_150pct_psi"] - 65.0) < 1e-9

    def test_churn_max_140pct(self):
        """NFPA 20: churn (shutoff) pressure ≤ 1.40 × rated."""
        res = fire_pump_sizing(500.0, 100.0)
        assert res["ok"] is True
        assert abs(res["churn_max_head_psi"] - 140.0) < 1e-9

    def test_nominal_churn_120pct(self):
        """Nominal churn ≈ 1.20 × rated (typical fire pump)."""
        res = fire_pump_sizing(250.0, 80.0)
        assert res["ok"] is True
        assert abs(res["nominal_churn_head_psi"] - 96.0) < 1e-9

    def test_small_pump_warns(self):
        """Flow < 25 gpm triggers warning."""
        res = fire_pump_sizing(10.0, 50.0)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_negative_flow_returns_error(self):
        res = fire_pump_sizing(-100.0, 80.0)
        assert res["ok"] is False

    def test_zero_head_returns_error(self):
        res = fire_pump_sizing(250.0, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 4. water_supply_adequacy
# ===========================================================================

class TestWaterSupplyAdequacy:

    def test_adequate_supply(self):
        """High static/residual supply easily meets low demand."""
        res = water_supply_adequacy(
            static_pressure_psi=80.0,
            residual_pressure_psi=60.0,
            residual_flow_gpm=1000.0,
            required_flow_gpm=400.0,
            required_pressure_psi=40.0,
        )
        assert res["ok"] is True
        assert res["supply_adequate"] is True
        assert res["pressure_margin_psi"] > 0

    def test_inadequate_supply_flags_warning(self):
        """Low supply fails when demand is high."""
        res = water_supply_adequacy(
            static_pressure_psi=50.0,
            residual_pressure_psi=20.0,
            residual_flow_gpm=200.0,
            required_flow_gpm=800.0,
            required_pressure_psi=45.0,
        )
        assert res["ok"] is True
        assert res["supply_adequate"] is False
        assert any("INADEQUATE" in w for w in res["warnings"])

    def test_available_pressure_formula(self):
        """P(Q) = Ps - (Ps - Pr) × (Q/Qr)^1.85."""
        Ps, Pr, Qr = 80.0, 55.0, 1000.0
        Q_req = 600.0
        expected = Ps - (Ps - Pr) * (Q_req / Qr) ** 1.85
        res = water_supply_adequacy(
            static_pressure_psi=Ps,
            residual_pressure_psi=Pr,
            residual_flow_gpm=Qr,
            required_flow_gpm=Q_req,
            required_pressure_psi=30.0,
        )
        assert res["ok"] is True
        assert abs(res["available_pressure_psi"] - expected) / expected < REL

    def test_residual_ge_static_returns_error(self):
        res = water_supply_adequacy(60.0, 70.0, 500.0, 300.0, 40.0)
        assert res["ok"] is False

    def test_zero_residual_flow_returns_error(self):
        res = water_supply_adequacy(80.0, 50.0, 0.0, 300.0, 40.0)
        assert res["ok"] is False


# ===========================================================================
# 5. egress_analysis
# ===========================================================================

class TestEgressAnalysis:

    def test_occupant_load_business(self):
        """Business OLF = 100 ft²/person → 5000 ft² = 50 persons."""
        res = egress_analysis(
            floor_area_ft2=5000.0,
            occupancy_type="business",
            num_exits=2,
            exit_widths_in=[44.0, 44.0],
            travel_distance_ft=150.0,
        )
        assert res["ok"] is True
        assert res["occupant_load"] == 50

    def test_occupant_load_assembly_concentrated(self):
        """Assembly concentrated OLF = 7 ft²/person → 700 ft² = 100 persons."""
        res = egress_analysis(
            floor_area_ft2=700.0,
            occupancy_type="assembly_concentrated",
            num_exits=2,
            exit_widths_in=[44.0, 44.0],
            travel_distance_ft=100.0,
        )
        assert res["ok"] is True
        assert res["occupant_load"] == 100

    def test_required_exits_for_large_occupant_load(self):
        """Occupant load > 500 requires >= 3 exits."""
        res = egress_analysis(
            floor_area_ft2=7000.0,
            occupancy_type="assembly_concentrated",
            num_exits=3,
            exit_widths_in=[44.0, 44.0, 44.0],
            travel_distance_ft=180.0,
        )
        assert res["ok"] is True
        assert res["required_exits"] >= 3

    def test_insufficient_exit_count_warns(self):
        """Providing fewer exits than required generates a warning."""
        # occupant load = 5000/7 ≈ 715 → requires 3 exits
        res = egress_analysis(
            floor_area_ft2=5000.0,
            occupancy_type="assembly_concentrated",
            num_exits=2,
            exit_widths_in=[44.0, 44.0],
            travel_distance_ft=150.0,
        )
        assert res["ok"] is True
        assert any("nsufficient" in w or "exit" in w.lower() for w in res["warnings"])

    def test_egress_capacity_exceeded_warns(self):
        """Narrow exits with large OL generates EGRESS_CAPACITY_EXCEEDED warning."""
        # 5000 / 7 ≈ 715 persons; stair factor 0.3 in/person → need 215 total inches
        res = egress_analysis(
            floor_area_ft2=5000.0,
            occupancy_type="assembly_concentrated",
            num_exits=2,
            exit_widths_in=[28.0, 28.0],  # only 56 total inches → ~187 persons
            travel_distance_ft=100.0,
            exit_component="stair",
        )
        assert res["ok"] is True
        assert any("EGRESS CAPACITY" in w for w in res["warnings"])

    def test_travel_distance_exceeded_warns(self):
        """Travel distance over limit generates a warning."""
        res = egress_analysis(
            floor_area_ft2=2000.0,
            occupancy_type="business",
            num_exits=2,
            exit_widths_in=[36.0, 36.0],
            travel_distance_ft=250.0,  # > 200 ft limit for business
        )
        assert res["ok"] is True
        assert not res["travel_distance_ok"]
        assert any("Travel distance" in w for w in res["warnings"])

    def test_dead_end_exceeded_warns(self):
        """Dead-end > 20 ft generates warning."""
        res = egress_analysis(
            floor_area_ft2=2000.0,
            occupancy_type="business",
            num_exits=2,
            exit_widths_in=[36.0, 36.0],
            travel_distance_ft=100.0,
            dead_end_ft=30.0,
        )
        assert res["ok"] is True
        assert not res["dead_end_ok"]

    def test_time_to_egress_increases_with_travel_distance(self):
        r1 = egress_analysis(2000.0, "business", 2, [44.0, 44.0], 50.0)
        r2 = egress_analysis(2000.0, "business", 2, [44.0, 44.0], 200.0)
        assert r2["time_to_egress_s"] > r1["time_to_egress_s"]

    def test_invalid_occupancy_type_returns_error(self):
        res = egress_analysis(2000.0, "spaceship", 2, [44.0, 44.0], 100.0)
        assert res["ok"] is False

    def test_wrong_exit_width_list_length_returns_error(self):
        res = egress_analysis(2000.0, "business", 2, [44.0], 100.0)
        assert res["ok"] is False


# ===========================================================================
# 6. design_fire_tsquared
# ===========================================================================

class TestDesignFireTsquared:

    def test_medium_fire_at_300s_is_1MW(self):
        """Medium growth: t=300 s → Q ≈ 1000 kW (1 MW) by definition."""
        res = design_fire_tsquared(300.0, growth_class="medium")
        assert res["ok"] is True
        assert abs(res["hrr_kw"] - 1000.0) / 1000.0 < 0.01

    def test_slow_fire_at_600s_is_1MW(self):
        """Slow growth: t=600 s → Q ≈ 1000 kW."""
        res = design_fire_tsquared(600.0, growth_class="slow")
        assert res["ok"] is True
        assert abs(res["hrr_kw"] - 1000.0) / 1000.0 < 0.01

    def test_fast_fire_at_150s_is_1MW(self):
        """Fast growth: t=150 s → Q ≈ 1000 kW."""
        res = design_fire_tsquared(150.0, growth_class="fast")
        assert res["ok"] is True
        assert abs(res["hrr_kw"] - 1000.0) / 1000.0 < 0.01

    def test_ultra_fast_at_75s_is_1MW(self):
        """Ultra-fast growth: t=75 s → Q ≈ 1000 kW."""
        res = design_fire_tsquared(75.0, growth_class="ultra_fast")
        assert res["ok"] is True
        assert abs(res["hrr_kw"] - 1000.0) / 1000.0 < 0.01

    def test_quadratic_growth(self):
        """Doubling time should quadruple HRR (Q = αt²)."""
        r1 = design_fire_tsquared(100.0, growth_class="medium")
        r2 = design_fire_tsquared(200.0, growth_class="medium")
        assert r2["ok"] is True
        ratio = r2["hrr_kw"] / r1["hrr_kw"]
        assert abs(ratio - 4.0) < REL

    def test_zero_time_gives_zero_hrr(self):
        res = design_fire_tsquared(0.0, growth_class="fast")
        assert res["ok"] is True
        assert res["hrr_kw"] == 0.0

    def test_max_hrr_cap(self):
        """HRR should be capped at max_hrr_kw."""
        res = design_fire_tsquared(500.0, growth_class="fast", max_hrr_kw=1000.0)
        assert res["ok"] is True
        assert res["hrr_kw"] <= 1000.0
        assert res["hrr_kw_capped"] is True

    def test_alpha_override(self):
        alpha = 0.05
        t = 100.0
        res = design_fire_tsquared(t, alpha_override=alpha)
        assert res["ok"] is True
        assert abs(res["hrr_kw"] - alpha * t ** 2) < 1e-9

    def test_time_to_1mw_formula(self):
        """time_to_1MW = √(1000/α); slow reaches 1 MW at 600 s, fast at 150 s."""
        for gc, t_ref in [("slow", 600.0), ("fast", 150.0)]:
            res = design_fire_tsquared(0.0, growth_class=gc)
            assert abs(res["time_to_1MW_s"] - t_ref) < 0.01, (
                f"{gc}: expected {t_ref}, got {res['time_to_1MW_s']}"
            )

    def test_invalid_growth_class_returns_error(self):
        res = design_fire_tsquared(100.0, growth_class="explosive")
        assert res["ok"] is False

    def test_negative_time_returns_error(self):
        res = design_fire_tsquared(-10.0, growth_class="medium")
        assert res["ok"] is False


# ===========================================================================
# 7. detector_activation_time
# ===========================================================================

class TestDetectorActivationTime:

    def test_near_axis_ceiling_jet_temp(self):
        """Near-axis (r/H <= 0.18): ΔT = 16.9 × Q^(2/3) / H^(5/3)."""
        Q, H, r = 500.0, 5.0, 0.5  # r/H = 0.1 → near axis
        res = detector_activation_time(
            hrr_kw=Q, ceiling_height_m=H, radial_distance_m=r,
            rti=100.0, detector_temp_c=74.0
        )
        assert res["ok"] is True
        delta_T_expected = 16.9 * Q ** (2.0 / 3.0) / H ** (5.0 / 3.0)
        assert abs(res["ceiling_jet_temp_c"] - (20.0 + delta_T_expected)) < 0.1

    def test_off_axis_ceiling_jet_temp(self):
        """Off-axis (r/H > 0.18): ΔT = 5.38 × (Q/r)^(2/3) / H."""
        Q, H, r = 500.0, 3.0, 2.0  # r/H = 0.667
        res = detector_activation_time(
            hrr_kw=Q, ceiling_height_m=H, radial_distance_m=r,
            rti=100.0, detector_temp_c=74.0
        )
        assert res["ok"] is True
        delta_T_expected = 5.38 * (Q / r) ** (2.0 / 3.0) / H
        assert abs(res["ceiling_jet_temp_c"] - (20.0 + delta_T_expected)) < 0.1

    def test_high_hrr_activates_detector(self):
        """Large fire should activate standard sprinkler at typical spacing."""
        res = detector_activation_time(
            hrr_kw=2000.0, ceiling_height_m=3.0, radial_distance_m=1.5,
            rti=100.0, detector_temp_c=74.0, ambient_temp_c=20.0
        )
        assert res["ok"] is True
        assert res["activated"] is True
        assert res["time_to_activation_s"] is not None

    def test_low_hrr_does_not_activate(self):
        """Very small fire, high-temp detector: should not activate."""
        res = detector_activation_time(
            hrr_kw=5.0, ceiling_height_m=10.0, radial_distance_m=5.0,
            rti=200.0, detector_temp_c=141.0, ambient_temp_c=20.0
        )
        assert res["ok"] is True
        assert res["activated"] is False
        assert any("not reach" in w.lower() or "not activate" in w.lower() or "not" in w.lower() for w in res["warnings"])

    def test_detector_temp_le_ambient_returns_error(self):
        res = detector_activation_time(
            hrr_kw=500.0, ceiling_height_m=5.0, radial_distance_m=1.0,
            rti=100.0, detector_temp_c=10.0, ambient_temp_c=20.0
        )
        assert res["ok"] is False

    def test_negative_hrr_returns_error(self):
        res = detector_activation_time(
            hrr_kw=-100.0, ceiling_height_m=5.0, radial_distance_m=1.0,
            rti=100.0, detector_temp_c=74.0
        )
        assert res["ok"] is False


# ===========================================================================
# 8. smoke_control_exhaust
# ===========================================================================

class TestSmokeControlExhaust:

    def test_exhaust_positive_for_valid_inputs(self):
        res = smoke_control_exhaust(
            hrr_kw=2000.0, atrium_height_m=15.0, smoke_layer_height_m=6.0
        )
        assert res["ok"] is True
        assert res["exhaust_airflow_cfm"] > 0
        assert res["exhaust_airflow_m3_s"] > 0
        assert res["plume_mass_flow_kg_s"] > 0

    def test_nfpa92_plume_formula(self):
        """Verify NFPA 92 Eq. A.2: Mp = 0.071 × Qc^(1/3) × z^(5/3) + 0.0018 × Qc."""
        Q, H, z = 1500.0, 12.0, 5.0
        Qc = 0.70 * Q
        expected_Mp = 0.071 * Qc ** (1.0 / 3.0) * z ** (5.0 / 3.0) + 0.0018 * Qc
        res = smoke_control_exhaust(Q, H, z)
        assert res["ok"] is True
        assert abs(res["plume_mass_flow_kg_s"] - expected_Mp) / expected_Mp < REL

    def test_higher_hrr_increases_exhaust(self):
        r1 = smoke_control_exhaust(500.0, 10.0, 4.0)
        r2 = smoke_control_exhaust(2000.0, 10.0, 4.0)
        assert r2["exhaust_airflow_cfm"] > r1["exhaust_airflow_cfm"]

    def test_higher_interface_increases_exhaust(self):
        """Higher smoke layer = more air entrained = more exhaust needed."""
        r1 = smoke_control_exhaust(1000.0, 15.0, 3.0)
        r2 = smoke_control_exhaust(1000.0, 15.0, 8.0)
        assert r2["exhaust_airflow_cfm"] > r1["exhaust_airflow_cfm"]

    def test_cfm_m3s_conversion(self):
        """1 m³/s = 2118.88 cfm."""
        res = smoke_control_exhaust(1000.0, 10.0, 4.0)
        assert res["ok"] is True
        assert abs(res["exhaust_airflow_cfm"] / res["exhaust_airflow_m3_s"] - 2118.88) < 0.1

    def test_smoke_layer_ge_atrium_height_returns_error(self):
        res = smoke_control_exhaust(1000.0, 10.0, 10.0)
        assert res["ok"] is False

    def test_smoke_layer_at_top_returns_error(self):
        res = smoke_control_exhaust(1000.0, 10.0, 12.0)
        assert res["ok"] is False


# ===========================================================================
# 9. fire_resistance_heat_transfer
# ===========================================================================

class TestFireResistanceHeatTransfer:

    def test_gypsum_assembly_heat_flux(self):
        """5/8-in gypsum board (16mm, k=0.17 W/mK) — verify heat flux formula."""
        layers = [{"name": "gypsum", "thickness_mm": 16.0, "conductivity_W_mK": 0.17}]
        res = fire_resistance_heat_transfer(
            layers, fire_side_temp_c=927.0, ambient_temp_c=20.0
        )
        assert res["ok"] is True
        # R_layer = 0.016 / 0.17
        R_layer = 0.016 / 0.17
        R_total = 0.13 + R_layer + 0.04
        q_expected = (927.0 - 20.0) / R_total
        assert abs(res["heat_flux_W_m2"] - q_expected) / q_expected < REL

    def test_double_gypsum_lower_flux(self):
        """Two layers of gypsum give lower heat flux than one layer."""
        single = [{"name": "g", "thickness_mm": 16.0, "conductivity_W_mK": 0.17}]
        double = [
            {"name": "g1", "thickness_mm": 16.0, "conductivity_W_mK": 0.17},
            {"name": "g2", "thickness_mm": 16.0, "conductivity_W_mK": 0.17},
        ]
        r1 = fire_resistance_heat_transfer(single)
        r2 = fire_resistance_heat_transfer(double)
        assert r2["heat_flux_W_m2"] < r1["heat_flux_W_m2"]

    def test_temperature_profile_decreasing(self):
        """Temperature should decrease monotonically from hot to cold side."""
        layers = [
            {"name": "concrete", "thickness_mm": 150.0, "conductivity_W_mK": 1.7},
        ]
        res = fire_resistance_heat_transfer(layers)
        assert res["ok"] is True
        temps = res["layer_temps_c"]
        for i in range(len(temps) - 1):
            assert temps[i] >= temps[i + 1], f"Temperature not monotone at index {i}"

    def test_astm_e119_limit_warning(self):
        """Very thin, high-conductivity layer should trigger ASTM E119 warning."""
        layers = [{"name": "steel", "thickness_mm": 5.0, "conductivity_W_mK": 50.0}]
        res = fire_resistance_heat_transfer(layers, fire_side_temp_c=927.0, ambient_temp_c=20.0)
        assert res["ok"] is True
        assert any("E119" in w or "unexposed" in w.lower() for w in res["warnings"])

    def test_fire_side_le_ambient_returns_error(self):
        layers = [{"name": "g", "thickness_mm": 16.0, "conductivity_W_mK": 0.17}]
        res = fire_resistance_heat_transfer(layers, fire_side_temp_c=10.0, ambient_temp_c=20.0)
        assert res["ok"] is False

    def test_empty_layers_returns_error(self):
        res = fire_resistance_heat_transfer([])
        assert res["ok"] is False


# ===========================================================================
# 10. required_fire_rating
# ===========================================================================

class TestRequiredFireRating:

    def test_business_low_rise_1hr_floors(self):
        """Business low-rise (≤4 stories) → 1-hr floor rating."""
        res = required_fire_rating("business", 2)
        assert res["ok"] is True
        assert res["required_floor_hr"] == 1.0
        assert res["is_high_rise"] is False

    def test_healthcare_high_rise_3hr(self):
        """Healthcare high-rise → 3-hr bearing wall, 3-hr floor."""
        res = required_fire_rating("healthcare", 8)
        assert res["ok"] is True
        assert res["is_high_rise"] is True
        assert res["required_bearing_wall_hr"] == 3.0
        assert res["required_floor_hr"] == 3.0

    def test_sprinkler_credit_reduces_rating(self):
        """Sprinkler credit reduces rating by 1 hr (min 0)."""
        r_ns = required_fire_rating("business", 5, sprinklered=False)
        r_s = required_fire_rating("business", 5, sprinklered=True)
        assert r_s["required_floor_hr"] == max(0.0, r_ns["required_floor_hr"] - 1.0)

    def test_high_rise_without_sprinklers_warns(self):
        """High-rise not sprinklered should warn."""
        res = required_fire_rating("residential", 6, sprinklered=False)
        assert res["ok"] is True
        assert any("sprinkler" in w.lower() or "high-rise" in w.lower() for w in res["warnings"])

    def test_invalid_occupancy_returns_error(self):
        res = required_fire_rating("spaceship", 2)
        assert res["ok"] is False

    def test_stories_less_than_1_returns_error(self):
        res = required_fire_rating("business", 0)
        assert res["ok"] is False


# ===========================================================================
# 11. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_run_sprinkler_hydraulic_demand_happy_path(self):
        ctx = _ctx()
        raw = _run(run_sprinkler_hydraulic_demand(ctx, _args(
            occupancy_class="ordinary_hazard_group_1",
            k_factor=5.6,
            pipe_d_inch=4.026,
            pipe_length_ft=150.0,
        )))
        d = _ok_tool(raw)
        assert d["total_demand_gpm"] > 0

    def test_run_sprinkler_missing_k_factor(self):
        ctx = _ctx()
        raw = _run(run_sprinkler_hydraulic_demand(ctx, _args(
            occupancy_class="light_hazard",
            pipe_d_inch=4.0,
            pipe_length_ft=100.0,
        )))
        _err_tool(raw)

    def test_run_fire_pump_sizing_happy_path(self):
        ctx = _ctx()
        raw = _run(run_fire_pump_sizing(ctx, _args(
            rated_flow_gpm=500.0, rated_head_psi=100.0
        )))
        d = _ok_tool(raw)
        assert d["flow_150pct_gpm"] == 750.0

    def test_run_fire_pump_sizing_bad_json(self):
        ctx = _ctx()
        raw = _run(run_fire_pump_sizing(ctx, b"not-json{{"))
        _err_tool(raw)

    def test_run_water_supply_adequacy_happy_path(self):
        ctx = _ctx()
        raw = _run(run_water_supply_adequacy(ctx, _args(
            static_pressure_psi=80.0,
            residual_pressure_psi=60.0,
            residual_flow_gpm=1000.0,
            required_flow_gpm=400.0,
            required_pressure_psi=40.0,
        )))
        d = _ok_tool(raw)
        assert d["supply_adequate"] is True

    def test_run_egress_analysis_happy_path(self):
        ctx = _ctx()
        raw = _run(run_egress_analysis(ctx, _args(
            floor_area_ft2=5000.0,
            occupancy_type="business",
            num_exits=2,
            exit_widths_in=[44.0, 44.0],
            travel_distance_ft=150.0,
        )))
        d = _ok_tool(raw)
        assert d["occupant_load"] == 50

    def test_run_design_fire_tsquared_happy_path(self):
        ctx = _ctx()
        raw = _run(run_design_fire_tsquared(ctx, _args(time_s=300.0, growth_class="medium")))
        d = _ok_tool(raw)
        assert abs(d["hrr_kw"] - 1000.0) / 1000.0 < 0.01

    def test_run_design_fire_tsquared_missing_time(self):
        ctx = _ctx()
        raw = _run(run_design_fire_tsquared(ctx, _args(growth_class="fast")))
        _err_tool(raw)

    def test_run_detector_activation_time_happy_path(self):
        ctx = _ctx()
        raw = _run(run_detector_activation_time(ctx, _args(
            hrr_kw=2000.0,
            ceiling_height_m=3.0,
            radial_distance_m=1.5,
            rti=100.0,
            detector_temp_c=74.0,
        )))
        d = _ok_tool(raw)
        assert d["ceiling_jet_temp_c"] > 20.0

    def test_run_smoke_control_exhaust_happy_path(self):
        ctx = _ctx()
        raw = _run(run_smoke_control_exhaust(ctx, _args(
            hrr_kw=2000.0,
            atrium_height_m=15.0,
            smoke_layer_height_m=6.0,
        )))
        d = _ok_tool(raw)
        assert d["exhaust_airflow_cfm"] > 0

    def test_run_fire_resistance_heat_transfer_happy_path(self):
        ctx = _ctx()
        raw = _run(run_fire_resistance_heat_transfer(ctx, _args(
            assembly_layers=[
                {"name": "gypsum", "thickness_mm": 16.0, "conductivity_W_mK": 0.17}
            ]
        )))
        d = _ok_tool(raw)
        assert d["heat_flux_W_m2"] > 0

    def test_run_required_fire_rating_happy_path(self):
        ctx = _ctx()
        raw = _run(run_required_fire_rating(ctx, _args(
            occupancy_group="business",
            building_height_stories=3,
        )))
        d = _ok_tool(raw)
        assert d["required_floor_hr"] >= 0

    def test_run_required_fire_rating_missing_stories(self):
        ctx = _ctx()
        raw = _run(run_required_fire_rating(ctx, _args(occupancy_group="business")))
        _err_tool(raw)
