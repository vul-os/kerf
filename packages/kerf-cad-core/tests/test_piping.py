"""
Hermetic tests for kerf_cad_core.piping — ASME B31.3 process piping calculations.

Coverage:
  process.schedule_lookup          — NPS/schedule table lookup
  process.required_wall_thickness  — B31.3 Eq. (3a) wall sizing
  process.pressure_drop            — Darcy-Weisbach single-phase
  process.allowable_span           — deflection + stress span limits
  process.thermal_expansion        — ΔL = L·α·ΔT
  process.guided_cantilever_leg    — minimum leg length for flexibility
  process.expansion_stress_check   — two-anchor guided-cantilever stress
  tools.*                          — LLM tool wrappers (happy + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas are verified algebraically against ASME B31.3 hand-calcs.

References
----------
ASME B31.3-2022 — Process Piping
ASME B36.10M-2018 — Welded and Seamless Wrought Steel Pipe
Crane TP-410 — Flow of Fluids
MSS SP-69 — Pipe Hangers and Supports

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.piping.process import (
    schedule_lookup,
    required_wall_thickness,
    pressure_drop,
    allowable_span,
    thermal_expansion,
    guided_cantilever_leg,
    expansion_stress_check,
)
from kerf_cad_core.piping.tools import (
    run_pipe_schedule_lookup,
    run_pipe_wall_thickness,
    run_pipe_pressure_drop,
    run_pipe_allowable_span,
    run_pipe_thermal_expansion,
    run_pipe_guided_cantilever_leg,
    run_pipe_expansion_stress,
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


REL = 1e-6  # relative tolerance for float comparisons


# ===========================================================================
# 1. schedule_lookup
# ===========================================================================

class TestScheduleLookup:

    def test_nps4_sch40_od(self):
        """NPS 4 Schedule 40: OD = 114.3 mm per ASME B36.10M."""
        res = schedule_lookup("4", "40")
        assert res["ok"] is True
        assert abs(res["OD_mm"] - 114.3) < 1e-6

    def test_nps4_sch40_wall(self):
        """NPS 4 Schedule 40: wall = 6.02 mm per ASME B36.10M."""
        res = schedule_lookup("4", "40")
        assert res["ok"] is True
        assert abs(res["wall_mm"] - 6.02) < 1e-6

    def test_nps4_sch40_id(self):
        """NPS 4 Schedule 40: ID = OD - 2*wall."""
        res = schedule_lookup("4", "40")
        assert res["ok"] is True
        expected_id = 114.3 - 2 * 6.02
        assert abs(res["ID_mm"] - expected_id) < 1e-6

    def test_nps2_sch80_wall(self):
        """NPS 2 Schedule 80: wall = 5.54 mm."""
        res = schedule_lookup("2", "80")
        assert res["ok"] is True
        assert abs(res["wall_mm"] - 5.54) < 1e-6

    def test_metric_conversion_consistent(self):
        """OD_m, wall_m, ID_m must be exactly OD_mm/1000, wall_mm/1000, ID_mm/1000."""
        res = schedule_lookup("6", "40")
        assert res["ok"] is True
        assert abs(res["OD_m"] - res["OD_mm"] * 1e-3) < 1e-12
        assert abs(res["wall_m"] - res["wall_mm"] * 1e-3) < 1e-12
        assert abs(res["ID_m"] - res["ID_mm"] * 1e-3) < 1e-12

    def test_nps_float_input(self):
        """Float NPS input 4.0 should resolve to '4' entry."""
        res = schedule_lookup(4.0, "40")
        assert res["ok"] is True
        assert abs(res["OD_mm"] - 114.3) < 1e-6

    def test_unknown_nps_returns_error(self):
        """NPS 99 is not in the table — must return ok=False."""
        res = schedule_lookup("99", "40")
        assert res["ok"] is False
        assert "reason" in res

    def test_unknown_schedule_returns_error(self):
        """Schedule 999 is not in the table for NPS 4."""
        res = schedule_lookup("4", "999")
        assert res["ok"] is False
        assert "reason" in res

    def test_nps_xxs_available(self):
        """XXS schedule must be available for NPS 2."""
        res = schedule_lookup("2", "XXS")
        assert res["ok"] is True
        assert res["wall_mm"] > 0

    def test_id_positive(self):
        """Inside diameter must be positive for all valid lookups."""
        res = schedule_lookup("1", "40")
        assert res["ok"] is True
        assert res["ID_mm"] > 0


# ===========================================================================
# 2. required_wall_thickness — ASME B31.3 Eq. (3a)
# ===========================================================================

class TestWallThickness:

    # Hand-calc reference:
    # P=3.0 MPa, D=0.1143 m (NPS4), S=138 MPa (A106 Gr.B at 200°C),
    # E=1.0, W=1.0, Y=0.4, c_corr=0, c_mill=0
    # t_m = 3e6 * 0.1143 / (2*(138e6*1*1 + 3e6*0.4))
    #      = 342900 / (2*(138e6 + 1.2e6))
    #      = 342900 / (2*139.2e6)
    #      = 342900 / 278400000
    #      ≈ 1.231e-3 m = 1.231 mm

    _P = 3.0e6
    _D = 0.1143
    _S = 138.0e6

    def test_t_design_algebraic(self):
        """Verify t_design against ASME B31.3 Eq. (3a) hand-calc."""
        P, D, S = self._P, self._D, self._S
        t_expected = P * D / (2.0 * (S * 1.0 * 1.0 + P * 0.4))
        res = required_wall_thickness(P, D, S)
        assert res["ok"] is True
        assert abs(res["t_design_m"] - t_expected) / t_expected < REL

    def test_corrosion_allowance_adds_to_t_required(self):
        """c_corr must be added to t_required directly."""
        c = 0.003  # 3 mm
        res_no_c = required_wall_thickness(self._P, self._D, self._S)
        res_with_c = required_wall_thickness(self._P, self._D, self._S, c_corr=c)
        assert res_with_c["ok"] is True
        diff = res_with_c["t_required_m"] - res_no_c["t_required_m"]
        assert abs(diff - c) < 1e-10

    def test_mill_tolerance_increases_t_required(self):
        """c_mill = 0.125 must increase t_required: t_req = t_design/0.875."""
        res_no_mill = required_wall_thickness(self._P, self._D, self._S)
        res_mill = required_wall_thickness(self._P, self._D, self._S, c_mill=0.125)
        assert res_mill["ok"] is True
        expected = res_no_mill["t_design_m"] / (1.0 - 0.125)
        assert abs(res_mill["t_required_m"] - expected) / expected < REL

    def test_erw_joint_factor_increases_thickness(self):
        """ERW joint E=0.85 must require more wall than seamless E=1.0."""
        t_seamless = required_wall_thickness(self._P, self._D, self._S, E=1.0)["t_required_m"]
        t_erw = required_wall_thickness(self._P, self._D, self._S, E=0.85)["t_required_m"]
        assert t_erw > t_seamless

    def test_zero_pressure_gives_zero_t_design(self):
        """P=0 → t_design = 0 (only allowances remain)."""
        res = required_wall_thickness(0.0, self._D, self._S, c_corr=0.0, c_mill=0.0)
        assert res["ok"] is True
        assert res["t_design_m"] == 0.0

    def test_mm_conversion_consistent(self):
        """t_required_mm must equal t_required_m * 1000."""
        res = required_wall_thickness(self._P, self._D, self._S)
        assert abs(res["t_required_mm"] - res["t_required_m"] * 1e3) < 1e-9

    def test_negative_pressure_returns_error(self):
        res = required_wall_thickness(-1e6, self._D, self._S)
        assert res["ok"] is False

    def test_invalid_E_factor_returns_error(self):
        res = required_wall_thickness(self._P, self._D, self._S, E=1.5)
        assert res["ok"] is False

    def test_invalid_Y_coefficient_returns_error(self):
        res = required_wall_thickness(self._P, self._D, self._S, Y=1.0)
        assert res["ok"] is False

    def test_invalid_c_mill_returns_error(self):
        res = required_wall_thickness(self._P, self._D, self._S, c_mill=1.0)
        assert res["ok"] is False

    def test_higher_pressure_needs_thicker_wall(self):
        """Doubling pressure must increase required wall thickness."""
        t1 = required_wall_thickness(1e6, self._D, self._S)["t_required_m"]
        t2 = required_wall_thickness(2e6, self._D, self._S)["t_required_m"]
        assert t2 > t1

    def test_higher_allowable_stress_allows_thinner_wall(self):
        """Higher S must allow thinner required wall."""
        t_low_S = required_wall_thickness(self._P, self._D, 100e6)["t_required_m"]
        t_high_S = required_wall_thickness(self._P, self._D, 200e6)["t_required_m"]
        assert t_high_S < t_low_S


# ===========================================================================
# 3. pressure_drop — Darcy-Weisbach
# ===========================================================================

class TestPressureDrop:

    # Hand-calc reference (turbulent):
    # Water, D_i=0.1023 m (NPS4 Sch40 ID), L=100 m, Q=0.01 m³/s
    # A = π/4 * 0.1023² = 8.219e-3 m²
    # V = 0.01 / 8.219e-3 = 1.217 m/s
    # Re = 1000 * 1.217 * 0.1023 / 1e-3 = 124,499
    # ε/D = 46e-6 / 0.1023 = 4.497e-4
    # (Colebrook will give f ≈ 0.0195 at these conditions)

    _Q = 0.01
    _rho = 1000.0
    _mu = 1.0e-3
    _D_i = 0.1023
    _L = 100.0

    def test_returns_ok(self):
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        assert res["ok"] is True

    def test_velocity_formula(self):
        """V = Q / (π/4 * D_i²)."""
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        A = math.pi / 4.0 * self._D_i ** 2
        V_expected = self._Q / A
        assert abs(res["velocity_m_s"] - V_expected) / V_expected < REL

    def test_reynolds_formula(self):
        """Re = ρ·V·D_i / μ."""
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        A = math.pi / 4.0 * self._D_i ** 2
        V = self._Q / A
        Re_expected = self._rho * V * self._D_i / self._mu
        assert abs(res["Re"] - Re_expected) / Re_expected < REL

    def test_darcy_formula(self):
        """ΔP = f·(L/D_i)·(ρ·V²/2) must match hand-calc."""
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        A = math.pi / 4.0 * self._D_i ** 2
        V = self._Q / A
        f = res["friction_factor"]
        dP_expected = f * (self._L / self._D_i) * (self._rho * V ** 2 / 2.0)
        assert abs(res["dP_Pa"] - dP_expected) / dP_expected < REL

    def test_unit_conversions(self):
        """dP_kPa = dP_Pa/1000 and dP_bar = dP_Pa/1e5."""
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        assert abs(res["dP_kPa"] - res["dP_Pa"] * 1e-3) < 1e-6
        assert abs(res["dP_bar"] - res["dP_Pa"] * 1e-5) < 1e-9

    def test_fittings_increase_pressure_drop(self):
        """Adding fittings equivalent length must increase ΔP."""
        res_no_fit = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        res_fit = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L, fittings_Le=20.0)
        assert res_fit["dP_Pa"] > res_no_fit["dP_Pa"]

    def test_laminar_regime_f_equals_64_over_Re(self):
        """For Re < 2300 (laminar), Darcy f = 64/Re."""
        # Force laminar: very small Q, large viscosity
        Q_lam = 1e-6
        mu_lam = 0.1  # 100x water viscosity
        res = pressure_drop(Q_lam, self._rho, mu_lam, self._D_i, self._L)
        assert res["ok"] is True
        assert res["flow_regime"] == "laminar"
        Re = res["Re"]
        f_expected = 64.0 / Re
        assert abs(res["friction_factor"] - f_expected) / f_expected < 1e-6

    def test_turbulent_flow_regime_label(self):
        """High Re flow must be labelled turbulent."""
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L)
        assert res["flow_regime"] == "turbulent"

    def test_negative_Q_returns_error(self):
        res = pressure_drop(-0.01, self._rho, self._mu, self._D_i, self._L)
        assert res["ok"] is False

    def test_negative_rho_returns_error(self):
        res = pressure_drop(self._Q, -1.0, self._mu, self._D_i, self._L)
        assert res["ok"] is False

    def test_L_eff_equals_L_plus_fittings(self):
        """L_eff_m must equal L + fittings_Le."""
        Le = 15.0
        res = pressure_drop(self._Q, self._rho, self._mu, self._D_i, self._L, fittings_Le=Le)
        assert abs(res["L_eff_m"] - (self._L + Le)) < 1e-10


# ===========================================================================
# 4. allowable_span
# ===========================================================================

class TestAllowableSpan:

    # NPS 4 Sch40: D_o=0.1143, D_i=0.1023 m
    # Carbon steel: rho_pipe=7850 kg/m³, E=200e9 Pa, S_allow=138e6 Pa
    # Water-filled: rho_fluid=1000

    _D_o = 0.1143
    _D_i = 0.1023
    _rho_pipe = 7850.0
    _rho_fluid = 1000.0
    _E = 200.0e9
    _S_allow = 138.0e6

    def test_returns_ok(self):
        res = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow)
        assert res["ok"] is True

    def test_governing_is_minimum(self):
        """L_allowable_m must be the minimum of the two span limits."""
        res = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow)
        assert res["L_allowable_m"] == min(res["L_deflection_m"], res["L_stress_m"])

    def test_governing_label(self):
        """governing must match which criterion is smaller."""
        res = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow)
        if res["L_deflection_m"] <= res["L_stress_m"]:
            assert res["governing"] == "deflection"
        else:
            assert res["governing"] == "stress"

    def test_deflection_formula(self):
        """Verify L_deflection = (384·E·I·δ/(5·w))^0.25."""
        res = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow, deflection_limit=0.0254)
        I = res["I_m4"]
        w = res["w_N_per_m"]
        L_expected = (384.0 * self._E * I * 0.0254 / (5.0 * w)) ** 0.25
        assert abs(res["L_deflection_m"] - L_expected) / L_expected < REL

    def test_stress_formula(self):
        """Verify L_stress = √(8·S_allow·Z/w)."""
        res = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow)
        Z = res["Z_m3"]
        w = res["w_N_per_m"]
        L_expected = math.sqrt(8.0 * self._S_allow * Z / w)
        assert abs(res["L_stress_m"] - L_expected) / L_expected < REL

    def test_larger_deflection_limit_increases_deflection_span(self):
        """Allowing more deflection must increase deflection-limited span."""
        res1 = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                              self._E, self._S_allow, deflection_limit=0.0127)
        res2 = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                              self._E, self._S_allow, deflection_limit=0.0254)
        assert res2["L_deflection_m"] > res1["L_deflection_m"]

    def test_D_i_ge_D_o_returns_error(self):
        res = allowable_span(0.10, 0.12, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow)
        assert res["ok"] is False

    def test_EI_Nm2_consistent(self):
        """EI_Nm2 must equal E * I."""
        res = allowable_span(self._D_o, self._D_i, self._rho_pipe, self._rho_fluid,
                             self._E, self._S_allow)
        assert abs(res["EI_Nm2"] - self._E * res["I_m4"]) / res["EI_Nm2"] < REL

    def test_gas_pipe_lighter_allows_longer_span(self):
        """A gas-filled pipe (rho_fluid≈0) must allow longer span than water-filled."""
        res_water = allowable_span(self._D_o, self._D_i, self._rho_pipe, 1000.0,
                                   self._E, self._S_allow)
        res_gas = allowable_span(self._D_o, self._D_i, self._rho_pipe, 1.2,
                                 self._E, self._S_allow)
        assert res_gas["L_allowable_m"] > res_water["L_allowable_m"]


# ===========================================================================
# 5. thermal_expansion
# ===========================================================================

class TestThermalExpansion:

    def test_basic_formula(self):
        """ΔL = L·α·ΔT for carbon steel pipe."""
        L, alpha, T_inst, T_op = 50.0, 11.7e-6, 20.0, 200.0
        res = thermal_expansion(L, alpha, T_inst, T_op)
        assert res["ok"] is True
        dL_expected = L * alpha * (T_op - T_inst)
        assert abs(res["delta_L_m"] - dL_expected) / dL_expected < REL

    def test_mm_conversion(self):
        """delta_L_mm must equal delta_L_m * 1000."""
        res = thermal_expansion(10.0, 12e-6, 20.0, 150.0)
        assert abs(res["delta_L_mm"] - res["delta_L_m"] * 1e3) < 1e-9

    def test_negative_delta_T_gives_contraction(self):
        """T_operating < T_install must yield negative ΔL (contraction)."""
        res = thermal_expansion(20.0, 11.7e-6, 100.0, 20.0)
        assert res["ok"] is True
        assert res["delta_L_m"] < 0.0

    def test_zero_delta_T(self):
        """T_operating == T_install → ΔL = 0."""
        res = thermal_expansion(20.0, 11.7e-6, 20.0, 20.0)
        assert res["ok"] is True
        assert res["delta_L_m"] == 0.0

    def test_longer_pipe_expands_more(self):
        """Doubling pipe length must double ΔL."""
        dL1 = thermal_expansion(10.0, 11.7e-6, 20.0, 200.0)["delta_L_m"]
        dL2 = thermal_expansion(20.0, 11.7e-6, 20.0, 200.0)["delta_L_m"]
        assert abs(dL2 / dL1 - 2.0) < 1e-9

    def test_higher_alpha_expands_more(self):
        """SS316 (α=16e-6) expands more than carbon steel (α=11.7e-6) at same ΔT."""
        dL_cs = thermal_expansion(50.0, 11.7e-6, 20.0, 200.0)["delta_L_m"]
        dL_ss = thermal_expansion(50.0, 16.0e-6, 20.0, 200.0)["delta_L_m"]
        assert dL_ss > dL_cs

    def test_negative_L_returns_error(self):
        res = thermal_expansion(-1.0, 11.7e-6, 20.0, 200.0)
        assert res["ok"] is False

    def test_negative_alpha_returns_error(self):
        res = thermal_expansion(10.0, -1e-6, 20.0, 200.0)
        assert res["ok"] is False

    def test_delta_T_reported(self):
        """delta_T must equal T_operating - T_install."""
        T_inst, T_op = 15.0, 250.0
        res = thermal_expansion(10.0, 11.7e-6, T_inst, T_op)
        assert abs(res["delta_T"] - (T_op - T_inst)) < 1e-9


# ===========================================================================
# 6. guided_cantilever_leg
# ===========================================================================

class TestGuidedCantileverLeg:

    # NPS 4 Sch40: D_o=0.1143, t=6.02e-3 m
    # E=200e9 Pa, S_allow=207e6 Pa (typical expansion allowable for CS)
    # delta=25e-3 m (25 mm thermal growth)

    _D_o = 0.1143
    _t = 6.02e-3
    _E = 200.0e9
    _S_allow = 207.0e6
    _delta = 0.025

    def test_returns_ok(self):
        res = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, self._delta)
        assert res["ok"] is True

    def test_leg_length_formula(self):
        """L_leg = √(3·E·I·δ / (S_allow·Z)) algebraic check."""
        D_i = self._D_o - 2.0 * self._t
        I = math.pi / 64.0 * (self._D_o ** 4 - D_i ** 4)
        Z = I / (self._D_o / 2.0)
        L_expected = math.sqrt(3.0 * self._E * I * self._delta / (self._S_allow * Z))
        res = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, self._delta)
        assert abs(res["L_leg_m"] - L_expected) / L_expected < REL

    def test_larger_delta_needs_longer_leg(self):
        """More displacement to absorb must require a longer leg."""
        L1 = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, 0.010)["L_leg_m"]
        L2 = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, 0.025)["L_leg_m"]
        assert L2 > L1

    def test_higher_allowable_stress_shorter_leg(self):
        """Higher S_allow means less restriction → shorter minimum leg."""
        L_low = guided_cantilever_leg(self._D_o, self._t, self._E, 100e6, self._delta)["L_leg_m"]
        L_high = guided_cantilever_leg(self._D_o, self._t, self._E, 200e6, self._delta)["L_leg_m"]
        assert L_high < L_low

    def test_leg_length_mm_consistent(self):
        """L_leg_mm must equal L_leg_m * 1000."""
        res = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, self._delta)
        assert abs(res["L_leg_mm"] - res["L_leg_m"] * 1e3) < 1e-6

    def test_t_ge_half_D_o_returns_error(self):
        res = guided_cantilever_leg(0.10, 0.06, self._E, self._S_allow, self._delta)
        assert res["ok"] is False

    def test_negative_delta_returns_error(self):
        res = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, -0.01)
        assert res["ok"] is False

    def test_stress_at_L_leg_equals_S_allow(self):
        """Stress back-calculated at L_leg must equal S_allow (within tolerance)."""
        res = guided_cantilever_leg(self._D_o, self._t, self._E, self._S_allow, self._delta)
        assert abs(res["sigma_at_L_Pa"] - self._S_allow) / self._S_allow < 1e-5


# ===========================================================================
# 7. expansion_stress_check
# ===========================================================================

class TestExpansionStressCheck:

    _params = dict(
        delta_x=0.020,  # 20 mm x-growth
        delta_y=0.015,  # 15 mm y-growth
        delta_z=0.0,
        L_x=3.0,
        L_y=4.0,
        E=200.0e9,
        D_o=0.1143,
        t=6.02e-3,
        S_allow=207.0e6,
    )

    def test_returns_ok(self):
        res = expansion_stress_check(**self._params)
        assert res["ok"] is True

    def test_sigma_x_formula(self):
        """σ_x = 3·E·I·δ_x / (L_x²·Z) algebraic check."""
        p = self._params
        D_i = p["D_o"] - 2.0 * p["t"]
        I = math.pi / 64.0 * (p["D_o"] ** 4 - D_i ** 4)
        Z = I / (p["D_o"] / 2.0)
        sx_expected = 3.0 * p["E"] * I * p["delta_x"] / (p["L_x"] ** 2 * Z)
        res = expansion_stress_check(**p)
        assert abs(res["sigma_x_Pa"] - sx_expected) / sx_expected < REL

    def test_sigma_E_srss(self):
        """σ_E = √(σ_x² + σ_y² + σ_z²) SRSS check."""
        res = expansion_stress_check(**self._params)
        srss = math.sqrt(res["sigma_x_Pa"] ** 2 + res["sigma_y_Pa"] ** 2 + res["sigma_z_Pa"] ** 2)
        assert abs(res["sigma_E_Pa"] - srss) / max(srss, 1.0) < 1e-9

    def test_zero_displacements_gives_zero_stress(self):
        """No displacement → zero expansion stress, always passes."""
        p = dict(self._params)
        p["delta_x"] = 0.0
        p["delta_y"] = 0.0
        p["delta_z"] = 0.0
        res = expansion_stress_check(**p)
        assert res["ok"] is True
        assert res["sigma_E_Pa"] == 0.0
        assert res["pass_fail"] is True

    def test_large_displacement_fails(self):
        """Very large displacement with short legs must fail the stress check."""
        p = dict(self._params)
        p["delta_x"] = 0.5   # 500 mm — extreme
        p["L_x"] = 1.0        # short leg
        res = expansion_stress_check(**p)
        assert res["ok"] is True
        assert res["pass_fail"] is False

    def test_safety_factor_is_S_allow_over_sigma_E(self):
        """safety_factor must equal S_allow / σ_E."""
        res = expansion_stress_check(**self._params)
        if res["sigma_E_Pa"] > 0:
            sf_expected = self._params["S_allow"] / res["sigma_E_Pa"]
            assert abs(res["safety_factor"] - sf_expected) / sf_expected < REL

    def test_safety_factor_infinite_for_zero_stress(self):
        """With zero displacement safety_factor must be infinite."""
        p = dict(self._params)
        p["delta_x"] = p["delta_y"] = p["delta_z"] = 0.0
        res = expansion_stress_check(**p)
        assert math.isinf(res["safety_factor"])

    def test_invalid_t_returns_error(self):
        p = dict(self._params)
        p["t"] = p["D_o"]  # t >= D_o/2
        res = expansion_stress_check(**p)
        assert res["ok"] is False

    def test_negative_delta_returns_error(self):
        p = dict(self._params)
        p["delta_x"] = -0.01
        res = expansion_stress_check(**p)
        assert res["ok"] is False


# ===========================================================================
# 8. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_schedule_lookup_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_schedule_lookup(ctx, _args(nominal_size_in="4", schedule="40")))
        d = _ok_tool(raw)
        assert d["OD_mm"] == pytest.approx(114.3)

    def test_schedule_lookup_tool_unknown_nps(self):
        ctx = _ctx()
        raw = _run(run_pipe_schedule_lookup(ctx, _args(nominal_size_in="99", schedule="40")))
        _err_tool(raw)

    def test_schedule_lookup_tool_missing_arg(self):
        ctx = _ctx()
        raw = _run(run_pipe_schedule_lookup(ctx, _args(nominal_size_in="4")))
        _err_tool(raw)

    def test_wall_thickness_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_wall_thickness(ctx, _args(P=3e6, D=0.1143, S=138e6)))
        d = _ok_tool(raw)
        assert d["t_required_m"] > 0

    def test_wall_thickness_tool_missing_P(self):
        ctx = _ctx()
        raw = _run(run_pipe_wall_thickness(ctx, _args(D=0.1143, S=138e6)))
        _err_tool(raw)

    def test_wall_thickness_tool_bad_json(self):
        ctx = _ctx()
        raw = _run(run_pipe_wall_thickness(ctx, b"not json"))
        _err_tool(raw)

    def test_pressure_drop_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_pressure_drop(ctx, _args(
            Q=0.01, rho=1000.0, mu=1e-3, D_i=0.1023, L=100.0
        )))
        d = _ok_tool(raw)
        assert d["dP_Pa"] > 0
        assert d["Re"] > 0

    def test_pressure_drop_tool_missing_rho(self):
        ctx = _ctx()
        raw = _run(run_pipe_pressure_drop(ctx, _args(Q=0.01, mu=1e-3, D_i=0.1023, L=100.0)))
        _err_tool(raw)

    def test_allowable_span_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_allowable_span(ctx, _args(
            D_o=0.1143, D_i=0.1023, rho_pipe=7850.0, rho_fluid=1000.0,
            E=200e9, S_allow=138e6
        )))
        d = _ok_tool(raw)
        assert d["L_allowable_m"] > 0

    def test_allowable_span_tool_missing_E(self):
        ctx = _ctx()
        raw = _run(run_pipe_allowable_span(ctx, _args(
            D_o=0.1143, D_i=0.1023, rho_pipe=7850.0, rho_fluid=1000.0, S_allow=138e6
        )))
        _err_tool(raw)

    def test_thermal_expansion_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_thermal_expansion(ctx, _args(
            L=50.0, alpha=11.7e-6, T_install=20.0, T_operating=200.0
        )))
        d = _ok_tool(raw)
        assert d["delta_L_mm"] > 0

    def test_thermal_expansion_tool_missing_alpha(self):
        ctx = _ctx()
        raw = _run(run_pipe_thermal_expansion(ctx, _args(
            L=50.0, T_install=20.0, T_operating=200.0
        )))
        _err_tool(raw)

    def test_guided_cantilever_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_guided_cantilever_leg(ctx, _args(
            D_o=0.1143, t=6.02e-3, E=200e9, S_allow=207e6, delta=0.025
        )))
        d = _ok_tool(raw)
        assert d["L_leg_m"] > 0

    def test_guided_cantilever_tool_missing_delta(self):
        ctx = _ctx()
        raw = _run(run_pipe_guided_cantilever_leg(ctx, _args(
            D_o=0.1143, t=6.02e-3, E=200e9, S_allow=207e6
        )))
        _err_tool(raw)

    def test_expansion_stress_tool_happy(self):
        ctx = _ctx()
        raw = _run(run_pipe_expansion_stress(ctx, _args(
            delta_x=0.020, delta_y=0.015, delta_z=0.0,
            L_x=3.0, L_y=4.0, E=200e9, D_o=0.1143, t=6.02e-3, S_allow=207e6
        )))
        d = _ok_tool(raw)
        assert "pass_fail" in d
        assert isinstance(d["pass_fail"], bool)

    def test_expansion_stress_tool_bad_json(self):
        ctx = _ctx()
        raw = _run(run_pipe_expansion_stress(ctx, b"{invalid json"))
        _err_tool(raw)

    def test_expansion_stress_tool_missing_S_allow(self):
        ctx = _ctx()
        raw = _run(run_pipe_expansion_stress(ctx, _args(
            delta_x=0.020, delta_y=0.015, delta_z=0.0,
            L_x=3.0, L_y=4.0, E=200e9, D_o=0.1143, t=6.02e-3
        )))
        _err_tool(raw)


# ===========================================================================
# REFERENCE CASES — asserted against citable known answers
#   ASME B31.3 Eq. (3a)            — pressure-design wall thickness
#   Crane TP-410 / Darcy-Weisbach  — incompressible flow
#   Hagen-Poiseuille (closed form) — laminar exactness anchor
# 1 psi = 6894.757 Pa, 1 in = 0.0254 m.
# ===========================================================================

PSI = 6894.757
IN = 0.0254


class TestReferenceCases:

    def test_ref_b31_3_eq3a_nps8(self):
        """ASME B31.3 §304.1.2 Eq.(3a): t = P·D/(2(S·E·W + P·Y)).
        NPS 8 (D=8.625 in), P=2000 psi, S=20000 psi, E=W=1, Y=0.4:
          t = 2000·8.625 / (2(20000 + 2000·0.4))
            = 17250 / 41600 = 0.41466 in = 10.532 mm.
        """
        res = required_wall_thickness(
            P=2000 * PSI, D=8.625 * IN, S=20000 * PSI, E=1.0, W=1.0, Y=0.4)
        assert res["ok"] is True
        t_in = res["t_design_m"] / IN
        assert abs(t_in - 0.41466) < 1e-4, f"t={t_in} in (expect 0.41466)"

    def test_ref_b31_3_corrosion_and_mill(self):
        """Eq.(3a) gross wall = t_m/(1 - c_mill) + c_corr.
        12.5% mill under-tolerance (ASTM A106) + 3 mm CA on the NPS8 case:
          t_req = 0.0105324/(1-0.125) + 0.003 = 0.0150370 m.
        """
        res = required_wall_thickness(
            P=2000 * PSI, D=8.625 * IN, S=20000 * PSI,
            c_corr=0.003, c_mill=0.125)
        assert abs(res["t_required_m"] - 0.0150370) < 5e-6

    def test_ref_hagen_poiseuille_laminar_exact(self):
        """Laminar Darcy-Weisbach must reduce exactly to Hagen-Poiseuille:
        ΔP = 128·μ·L·Q/(π·D⁴).
        Oil ρ=900, μ=0.1 Pa·s, D=0.05 m, V=0.5 m/s, L=10 m → Re=225,
        f=64/Re=0.28444, ΔP = 6400 Pa exactly.
        """
        D_i, V = 0.05, 0.5
        Q = V * math.pi / 4.0 * D_i ** 2
        res = pressure_drop(Q=Q, rho=900.0, mu=0.1, D_i=D_i, L=10.0,
                            roughness=0.0)
        assert res["flow_regime"] == "laminar"
        assert abs(res["Re"] - 225.0) < 1e-6
        assert abs(res["friction_factor"] - 64.0 / 225.0) < 1e-9
        assert abs(res["dP_Pa"] - 6400.0) < 1e-6

    def test_ref_colebrook_turbulent_moody(self):
        """Colebrook-White anchor (Moody chart): water D=0.1 m, V=2 m/s,
        ρ=1000, μ=1e-3 → Re=2.0e5; ε=46 µm (commercial steel) →
        Darcy f ≈ 0.01861 (matches Moody chart / Swamee-Jain ~1%).
        """
        D_i, V = 0.1, 2.0
        Q = V * math.pi / 4.0 * D_i ** 2
        res = pressure_drop(Q=Q, rho=1000.0, mu=1e-3, D_i=D_i, L=1.0,
                            roughness=46e-6)
        assert abs(res["Re"] - 2.0e5) < 1.0
        assert abs(res["friction_factor"] - 0.018613) < 5e-4

    def test_ref_thermal_expansion_carbon_steel(self):
        """Free thermal growth ΔL = L·α·ΔT.  Carbon steel α=11.7e-6 /°C,
        L=30 m, 20→200 °C (ΔT=180):  ΔL = 30·11.7e-6·180 = 0.06318 m.
        """
        res = thermal_expansion(L=30.0, alpha=11.7e-6,
                                T_install=20.0, T_operating=200.0)
        assert abs(res["delta_L_m"] - 0.06318) < 1e-6

    def test_ref_pipe_section_properties_nps6_sch40(self):
        """Hollow circular section (ASME B36.10M NPS 6 Sch 40):
        D_o=168.3 mm, wall=7.11 mm → D_i=154.08 mm.
          I = π/64·(D_o⁴ - D_i⁴) = 1.1716e-5 m⁴
          Z = I/(D_o/2) = 1.3923e-4 m³  (matches steel-pipe tables).
        """
        Do, w = 0.1683, 0.00711
        res = allowable_span(
            D_o=Do, D_i=Do - 2 * w, rho_pipe=7850.0, rho_fluid=1000.0,
            E=200e9, S_allow=138e6)
        assert abs(res["I_m4"] - 1.1716e-5) / 1.1716e-5 < 2e-3
        assert abs(res["Z_m3"] - 1.3923e-4) / 1.3923e-4 < 2e-3
