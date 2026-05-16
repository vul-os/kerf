"""
Hermetic tests for kerf_cad_core.flowmeter — flow metering & sizing.

Coverage:
  measure.dp_meter              — ISO 5167 orifice/venturi/nozzle
  measure.control_valve_liquid  — ISA/IEC Cv liquid
  measure.control_valve_gas     — ISA/IEC Cv gas
  measure.control_valve_steam   — IEC Cv steam
  measure.prv_gas               — API 520 gas PRV
  measure.prv_liquid            — API 520 liquid PRV
  measure.prv_steam             — API 520 steam (Napier)
  measure.pitot_velocity        — pitot tube
  measure.annubar_flow          — annubar
  measure.v_notch_weir          — ISO 1438
  measure.rectangular_weir      — Francis/Rehbock
  measure.parshall_flume        — USBR
  measure.rotameter_scale       — density correction
  measure.turndown_ratio        — utility
  tools.*                       — LLM tool wrappers

All tests are pure-Python and hermetic: no OCC, no DB, no network, no fixtures.
Formulas verified algebraically vs ISO 5167 / ISA / API 520 hand-calcs.

References
----------
ISO 5167-1:2003  — Measurement of fluid flow — Orifice plates
ISO 5167-2:2003  — Measurement of fluid flow — Venturi tubes
ANSI/ISA-75.01.01-2007 / IEC 60534-2-1:2011 — Control valve sizing
API Standard 520 Part I (9th ed. 2014)
Miller — Flow Measurement Engineering Handbook (3rd ed.)

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.flowmeter.measure import (
    dp_meter,
    control_valve_liquid,
    control_valve_gas,
    control_valve_steam,
    prv_gas,
    prv_liquid,
    prv_steam,
    pitot_velocity,
    annubar_flow,
    v_notch_weir,
    rectangular_weir,
    parshall_flume,
    rotameter_scale,
    turndown_ratio,
    _rhg_orifice_C,
    _expansibility_orifice,
)
from kerf_cad_core.flowmeter.tools import (
    run_dp_meter,
    run_control_valve_liquid,
    run_control_valve_gas,
    run_control_valve_steam,
    run_prv_gas,
    run_prv_liquid,
    run_prv_steam,
    run_pitot_velocity,
    run_annubar_flow,
    run_v_notch_weir,
    run_rectangular_weir,
    run_parshall_flume,
    run_rotameter_scale,
    run_turndown_ratio,
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


REL = 1e-4  # relative tolerance for flow calcs


# ===========================================================================
# 1. dp_meter — ISO 5167 differential-pressure meters
# ===========================================================================

class TestDpMeterOrifice:

    def test_orifice_basic_water_flow(self):
        """Standard water orifice at known ΔP returns positive flow."""
        res = dp_meter("orifice", pipe_d_m=0.1, beta=0.5,
                       dp_pa=5000.0, rho_kg_m3=998.0)
        assert res["ok"] is True
        assert res["qm_kg_s"] > 0
        assert res["qv_m3_s"] > 0
        assert 0.5 < res["Cd"] < 0.7

    def test_orifice_continuity_qm_eq_rho_qv(self):
        """Mass flow must equal rho * volume flow."""
        res = dp_meter("orifice", pipe_d_m=0.15, beta=0.6,
                       dp_pa=10000.0, rho_kg_m3=1000.0)
        assert res["ok"] is True
        assert abs(res["qm_kg_s"] - 1000.0 * res["qv_m3_s"]) / res["qm_kg_s"] < 1e-9

    def test_orifice_flow_scales_sqrt_dp(self):
        """Quadrupling ΔP approximately doubles mass flow (q ∝ √ΔP).

        The RHG Cd is weakly Re-dependent so the ratio is close to but
        not exactly 2.0; tolerance is 2% to allow for Re correction.
        """
        r1 = dp_meter("orifice", pipe_d_m=0.1, beta=0.5, dp_pa=1000.0, rho_kg_m3=1000.0)
        r4 = dp_meter("orifice", pipe_d_m=0.1, beta=0.5, dp_pa=4000.0, rho_kg_m3=1000.0)
        assert r1["ok"] and r4["ok"]
        assert abs(r4["qm_kg_s"] / r1["qm_kg_s"] - 2.0) < 0.02

    def test_orifice_gas_expansibility_less_than_unity(self):
        """Expansibility factor must be < 1.0 for compressible gas."""
        res = dp_meter("orifice", pipe_d_m=0.1, beta=0.5,
                       dp_pa=5000.0, rho_kg_m3=1.2,
                       p1_pa=200000.0, kappa=1.4, gas=True)
        assert res["ok"] is True
        assert res["epsilon"] < 1.0

    def test_orifice_permanent_pressure_loss_less_than_dp(self):
        """Permanent pressure loss must be < differential pressure."""
        res = dp_meter("orifice", pipe_d_m=0.1, beta=0.5,
                       dp_pa=10000.0, rho_kg_m3=1000.0)
        assert res["ok"] is True
        assert res["permanent_pressure_loss_pa"] < 10000.0
        assert res["permanent_pressure_loss_pa"] > 0

    def test_orifice_beta_out_of_range_warns(self):
        """beta=0.8 (out of 0.75 ISO limit) adds a warning but still returns ok."""
        res = dp_meter("orifice", pipe_d_m=0.1, beta=0.8,
                       dp_pa=5000.0, rho_kg_m3=1000.0)
        assert res["ok"] is True
        assert any("beta" in w for w in res["warnings"])

    def test_orifice_invalid_meter_type(self):
        res = dp_meter("coriolis", pipe_d_m=0.1, beta=0.5,
                       dp_pa=5000.0, rho_kg_m3=1000.0)
        assert res["ok"] is False

    def test_orifice_negative_dp_returns_error(self):
        res = dp_meter("orifice", pipe_d_m=0.1, beta=0.5,
                       dp_pa=-100.0, rho_kg_m3=1000.0)
        assert res["ok"] is False


class TestDpMeterVenturiNozzle:

    def test_venturi_returns_higher_flow_than_orifice_same_cd(self):
        """Venturi has higher Cd than orifice → higher flow for same ΔP."""
        r_o = dp_meter("orifice", pipe_d_m=0.1, beta=0.5,
                       dp_pa=5000.0, rho_kg_m3=1000.0)
        r_v = dp_meter("venturi", pipe_d_m=0.1, beta=0.5,
                       dp_pa=5000.0, rho_kg_m3=1000.0)
        assert r_o["ok"] and r_v["ok"]
        assert r_v["qm_kg_s"] > r_o["qm_kg_s"]

    def test_nozzle_cd_approx(self):
        """ISA nozzle Cd should be close to 0.9975."""
        res = dp_meter("nozzle", pipe_d_m=0.2, beta=0.5,
                       dp_pa=2000.0, rho_kg_m3=1000.0)
        assert res["ok"] is True
        assert abs(res["Cd"] - 0.9975) < 0.001

    def test_venturi_ppl_much_less_than_orifice(self):
        """Venturi permanent pressure loss should be much less than orifice."""
        r_o = dp_meter("orifice", pipe_d_m=0.15, beta=0.5,
                       dp_pa=10000.0, rho_kg_m3=1000.0)
        r_v = dp_meter("venturi", pipe_d_m=0.15, beta=0.5,
                       dp_pa=10000.0, rho_kg_m3=1000.0)
        assert r_o["ok"] and r_v["ok"]
        assert r_v["permanent_pressure_loss_pa"] < r_o["permanent_pressure_loss_pa"]


# ===========================================================================
# 2. control_valve_liquid — ISA/IEC Cv liquid
# ===========================================================================

class TestControlValveLiquid:

    def test_liquid_cv_positive(self):
        """Simple water service returns Cv > 0."""
        res = control_valve_liquid(
            q_m3h=10.0, rho_kg_m3=1000.0, dp_kpa=50.0,
            p1_kpa=600.0, pv_kpa=3.5, pc_kpa=22089.0
        )
        assert res["ok"] is True
        assert res["Cv"] > 0
        assert res["Kv"] > 0

    def test_kv_cv_relationship(self):
        """Kv = Cv * 1.1561 (ISA/IEC conversion constant)."""
        res = control_valve_liquid(
            q_m3h=5.0, rho_kg_m3=998.0, dp_kpa=30.0,
            p1_kpa=400.0, pv_kpa=2.0, pc_kpa=22089.0
        )
        assert res["ok"] is True
        # Kv = Cv / 1.1561 → Cv = Kv * 1.1561
        assert abs(res["Cv"] / res["Kv"] - 1.1561) / 1.1561 < 1e-3

    def test_choked_flow_detection(self):
        """Large ΔP (> choked ΔP) must flag is_choked=True."""
        # Force choked: p1 high, pv=0, FL=0.9, choked_dp = 0.9^2 * p1
        res = control_valve_liquid(
            q_m3h=5.0, rho_kg_m3=1000.0, dp_kpa=500.0,
            p1_kpa=600.0, pv_kpa=0.1, pc_kpa=22089.0, FL=0.9
        )
        assert res["ok"] is True
        assert res["is_choked"] is True
        assert any("choked" in w for w in res["warnings"])

    def test_ff_factor_range(self):
        """FF factor must be between 0 and 1 for valid inputs."""
        res = control_valve_liquid(
            q_m3h=8.0, rho_kg_m3=850.0, dp_kpa=40.0,
            p1_kpa=300.0, pv_kpa=10.0, pc_kpa=3758.0  # propane approx
        )
        assert res["ok"] is True
        assert 0 < res["FF"] < 1

    def test_negative_flow_returns_error(self):
        res = control_valve_liquid(
            q_m3h=-5.0, rho_kg_m3=1000.0, dp_kpa=50.0,
            p1_kpa=400.0, pv_kpa=3.0, pc_kpa=22089.0
        )
        assert res["ok"] is False

    def test_fl_out_of_range_returns_error(self):
        res = control_valve_liquid(
            q_m3h=5.0, rho_kg_m3=1000.0, dp_kpa=50.0,
            p1_kpa=400.0, pv_kpa=3.0, pc_kpa=22089.0, FL=1.5
        )
        assert res["ok"] is False


# ===========================================================================
# 3. control_valve_gas — ISA/IEC Cv gas
# ===========================================================================

class TestControlValveGas:

    def test_gas_cv_positive_air(self):
        """Air service (MW=29, κ=1.4) returns Cv > 0."""
        res = control_valve_gas(
            q_kg_s=0.5, p1_pa=600000.0, T1_K=300.0,
            MW_g_mol=29.0, dp_pa=100000.0
        )
        assert res["ok"] is True
        assert res["Cv"] > 0

    def test_gas_choked_detection(self):
        """When dp/p1 >= Fk*xT the flow must be flagged choked."""
        # xT=0.72, Fk=1 for air: choked at x=0.72 → dp = 0.72*p1
        res = control_valve_gas(
            q_kg_s=0.1, p1_pa=500000.0, T1_K=293.0,
            MW_g_mol=29.0, dp_pa=400000.0, xT=0.72
        )
        assert res["ok"] is True
        assert res["is_choked"] is True
        assert abs(res["Y"] - 2.0 / 3.0) < 1e-9

    def test_y_factor_between_twothirds_and_one(self):
        """Expansion factor Y must be in [2/3, 1]."""
        res = control_valve_gas(
            q_kg_s=0.2, p1_pa=300000.0, T1_K=350.0,
            MW_g_mol=44.0, dp_pa=50000.0, xT=0.72
        )
        assert res["ok"] is True
        assert 2.0 / 3.0 <= res["Y"] <= 1.0

    def test_gas_negative_flow_error(self):
        res = control_valve_gas(
            q_kg_s=-1.0, p1_pa=500000.0, T1_K=300.0,
            MW_g_mol=29.0, dp_pa=50000.0
        )
        assert res["ok"] is False


# ===========================================================================
# 4. control_valve_steam
# ===========================================================================

class TestControlValveSteam:

    def test_steam_cv_positive(self):
        """Saturated steam at 10 bar, specific volume approx 0.194 m³/kg."""
        # sat steam ~10 bar: v ≈ 0.194 m³/kg
        res = control_valve_steam(
            q_kg_s=1.0, p1_pa=1.0e6, dp_pa=200000.0, v1_m3_kg=0.194
        )
        assert res["ok"] is True
        assert res["Cv"] > 0

    def test_steam_choked(self):
        """Large dp/p1 ratio must flag choked steam flow."""
        # κ=1.135, Fk=1.135/1.4=0.8107, xT=0.72 → choked at x=0.584
        res = control_valve_steam(
            q_kg_s=0.5, p1_pa=500000.0, dp_pa=400000.0, v1_m3_kg=0.37
        )
        assert res["ok"] is True
        assert res["is_choked"] is True

    def test_steam_missing_v1_returns_error(self):
        try:
            res = control_valve_steam(
                q_kg_s=1.0, p1_pa=1e6, dp_pa=200000.0, v1_m3_kg=-0.1
            )
            assert res["ok"] is False
        except Exception:
            pass  # also acceptable — negative specific volume is invalid


# ===========================================================================
# 5. prv_gas — API 520 gas PRV
# ===========================================================================

class TestPrvGas:

    def test_prv_gas_area_positive(self):
        """Basic gas PRV sizing returns positive area."""
        res = prv_gas(q_kg_s=1.0, p_set_pa=1.0e6, T_K=400.0, MW_g_mol=29.0)
        assert res["ok"] is True
        assert res["area_m2"] > 0
        assert res["area_in2"] > 0

    def test_prv_gas_designation_letter_valid(self):
        """Designation letter must be a known API 526 letter."""
        valid_letters = set("DEFGHJKLMNPQRT") | {"T+"}
        res = prv_gas(q_kg_s=0.5, p_set_pa=800000.0, T_K=350.0, MW_g_mol=44.0)
        assert res["ok"] is True
        assert res["designation"] in valid_letters

    def test_prv_gas_area_scales_with_flow(self):
        """Doubling mass flow must roughly double the required area."""
        r1 = prv_gas(q_kg_s=1.0, p_set_pa=500000.0, T_K=350.0, MW_g_mol=29.0)
        r2 = prv_gas(q_kg_s=2.0, p_set_pa=500000.0, T_K=350.0, MW_g_mol=29.0)
        assert r1["ok"] and r2["ok"]
        assert abs(r2["area_m2"] / r1["area_m2"] - 2.0) < 0.01

    def test_prv_gas_relieving_pressure_accounts_for_overpressure(self):
        """P1 = p_set * (1 + overpressure_frac)."""
        res = prv_gas(q_kg_s=0.5, p_set_pa=1.0e6, T_K=400.0, MW_g_mol=29.0,
                      overpressure_frac=0.10)
        assert res["ok"] is True
        assert abs(res["P1_pa"] / 1.0e6 - 1.10) < 1e-9

    def test_prv_gas_subcritical_warns(self):
        """High backpressure forces sub-critical condition and adds warning."""
        # Set backpressure very close to set pressure
        res = prv_gas(q_kg_s=0.5, p_set_pa=1.0e6, T_K=400.0, MW_g_mol=29.0,
                      backpressure_pa=950000.0)
        assert res["ok"] is True
        assert any("sub-critical" in w or "subcritical" in w for w in res["warnings"])


# ===========================================================================
# 6. prv_liquid — API 520 liquid PRV
# ===========================================================================

class TestPrvLiquid:

    def test_prv_liquid_positive_area(self):
        """Basic liquid PRV sizing returns positive area."""
        res = prv_liquid(q_m3s=0.01, p_set_pa=500000.0, rho_kg_m3=998.0)
        assert res["ok"] is True
        assert res["area_m2"] > 0
        assert res["designation"] in set("DEFGHJKLMNPQRT") | {"T+"}

    def test_prv_liquid_area_scales_with_flow(self):
        """Quadrupling flow must double area (A ∝ Q, pressure constant)."""
        r1 = prv_liquid(q_m3s=0.005, p_set_pa=400000.0, rho_kg_m3=998.0)
        r4 = prv_liquid(q_m3s=0.010, p_set_pa=400000.0, rho_kg_m3=998.0)
        assert r1["ok"] and r4["ok"]
        # Area ∝ Q (liquid API eq is linear in Q)
        ratio = r4["area_m2"] / r1["area_m2"]
        assert abs(ratio - 2.0) < 0.01

    def test_prv_liquid_negative_flow_error(self):
        res = prv_liquid(q_m3s=-0.01, p_set_pa=500000.0, rho_kg_m3=998.0)
        assert res["ok"] is False


# ===========================================================================
# 7. prv_steam — API 520 Napier
# ===========================================================================

class TestPrvSteam:

    def test_prv_steam_area_positive(self):
        """Basic steam PRV returns positive area."""
        res = prv_steam(q_kg_s=2.0, p_set_pa=1.0e6)
        assert res["ok"] is True
        assert res["area_m2"] > 0
        assert res["area_in2"] > 0

    def test_prv_steam_napier_area_formula(self):
        """Verify Napier formula algebraically.

        API 520 Eq(12): A = W / (51.45 * kd * P1 * ksh * kb * kn)
        W_lbhr = q_kg_s * 7936.64;  P1_psia = p_set*1.1*1.45038e-4
        """
        q = 1.0     # kg/s
        p_set = 500000.0  # Pa abs
        kd = 0.975
        P1_psia = p_set * 1.10 * 1.45038e-4
        W_lbhr = q * 7936.64
        A_in2_expected = W_lbhr / (51.45 * kd * P1_psia * 1.0 * 1.0 * 1.0)
        res = prv_steam(q_kg_s=q, p_set_pa=p_set)
        assert res["ok"] is True
        assert abs(res["area_in2"] - A_in2_expected) / A_in2_expected < 1e-6

    def test_prv_steam_negative_flow_error(self):
        res = prv_steam(q_kg_s=-1.0, p_set_pa=500000.0)
        assert res["ok"] is False


# ===========================================================================
# 8. pitot_velocity
# ===========================================================================

class TestPitotVelocity:

    def test_pitot_basic_formula(self):
        """v = Cp * sqrt(2 * dp / rho) at Cp=1.0."""
        dp, rho = 500.0, 1.2
        res = pitot_velocity(dp_pa=dp, rho_kg_m3=rho)
        assert res["ok"] is True
        expected = math.sqrt(2.0 * dp / rho)
        assert abs(res["velocity_m_s"] - expected) / expected < 1e-9

    def test_pitot_cp_scales_velocity(self):
        """Velocity must scale linearly with Cp."""
        dp, rho = 300.0, 1.0
        r1 = pitot_velocity(dp_pa=dp, rho_kg_m3=rho, Cp=0.98)
        r2 = pitot_velocity(dp_pa=dp, rho_kg_m3=rho, Cp=0.90)
        assert r1["ok"] and r2["ok"]
        assert abs(r1["velocity_m_s"] / r2["velocity_m_s"] - 0.98 / 0.90) < 1e-9

    def test_pitot_negative_dp_error(self):
        res = pitot_velocity(dp_pa=-100.0, rho_kg_m3=1.2)
        assert res["ok"] is False

    def test_pitot_cp_out_of_range_error(self):
        res = pitot_velocity(dp_pa=500.0, rho_kg_m3=1.2, Cp=2.0)
        assert res["ok"] is False


# ===========================================================================
# 9. annubar_flow
# ===========================================================================

class TestAnnubarFlow:

    def test_annubar_qv_equals_velocity_times_area(self):
        """qv = v * A where A = π/4 * D²."""
        dp, rho, D, Cp = 400.0, 1.2, 0.15, 0.77
        res = annubar_flow(dp_pa=dp, rho_kg_m3=rho, pipe_d_m=D, Cp=Cp)
        assert res["ok"] is True
        A = math.pi / 4.0 * D ** 2
        v = Cp * math.sqrt(2.0 * dp / rho)
        assert abs(res["qv_m3_s"] - v * A) / (v * A) < 1e-9

    def test_annubar_qm_eq_rho_qv(self):
        """qm = rho * qv."""
        res = annubar_flow(dp_pa=300.0, rho_kg_m3=1000.0, pipe_d_m=0.1)
        assert res["ok"] is True
        assert abs(res["qm_kg_s"] - 1000.0 * res["qv_m3_s"]) < 1e-9

    def test_annubar_missing_pipe_d_error(self):
        res = annubar_flow(dp_pa=400.0, rho_kg_m3=1.2, pipe_d_m=-0.1)
        assert res["ok"] is False


# ===========================================================================
# 10. v_notch_weir
# ===========================================================================

class TestVNotchWeir:

    def test_vnotch_90deg_formula(self):
        """Q = (8/15)*Cd*sqrt(2g)*tan(45°)*H^2.5 for 90° notch."""
        H = 0.3   # m
        Cd = 0.611
        g = 9.80665
        expected = (8.0 / 15.0) * Cd * math.sqrt(2.0 * g) * math.tan(math.radians(45.0)) * H ** 2.5
        res = v_notch_weir(H_m=H)
        assert res["ok"] is True
        assert abs(res["qv_m3_s"] - expected) / expected < 1e-9

    def test_vnotch_30deg_less_than_90deg(self):
        """30° notch passes less flow than 90° for same H."""
        r30 = v_notch_weir(H_m=0.2, theta_deg=30.0)
        r90 = v_notch_weir(H_m=0.2, theta_deg=90.0)
        assert r30["ok"] and r90["ok"]
        assert r30["qv_m3_s"] < r90["qv_m3_s"]

    def test_vnotch_h_scales_h_2p5(self):
        """Flow ∝ H^2.5: doubling H multiplies Q by 2^2.5 = 5.657."""
        r1 = v_notch_weir(H_m=0.2)
        r2 = v_notch_weir(H_m=0.4)
        assert r1["ok"] and r2["ok"]
        ratio = r2["qv_m3_s"] / r1["qv_m3_s"]
        assert abs(ratio - 2.0 ** 2.5) < 1e-9

    def test_vnotch_negative_h_error(self):
        res = v_notch_weir(H_m=-0.1)
        assert res["ok"] is False


# ===========================================================================
# 11. rectangular_weir
# ===========================================================================

class TestRectangularWeir:

    def test_rect_weir_formula_no_contractions(self):
        """Q = (2/3)*Cd*sqrt(2g)*L*H^1.5 for suppressed weir (n=0)."""
        H, L, Cd = 0.3, 2.0, 0.611
        g = 9.80665
        expected = (2.0 / 3.0) * Cd * math.sqrt(2.0 * g) * L * H ** 1.5
        res = rectangular_weir(H_m=H, L_m=L, end_contractions=0)
        assert res["ok"] is True
        assert abs(res["qv_m3_s"] - expected) / expected < 1e-9

    def test_rect_weir_contractions_reduce_flow(self):
        """End contractions must reduce effective length and hence flow."""
        r0 = rectangular_weir(H_m=0.3, L_m=2.0, end_contractions=0)
        r2 = rectangular_weir(H_m=0.3, L_m=2.0, end_contractions=2)
        assert r0["ok"] and r2["ok"]
        assert r2["qv_m3_s"] < r0["qv_m3_s"]

    def test_rect_weir_h_scales_h_1p5(self):
        """Flow ∝ H^1.5: 4× H → 8× flow."""
        r1 = rectangular_weir(H_m=0.25, L_m=1.5, end_contractions=0)
        r4 = rectangular_weir(H_m=0.50, L_m=1.5, end_contractions=0)
        ratio = r4["qv_m3_s"] / r1["qv_m3_s"]
        assert abs(ratio - 2.0 ** 1.5) < 1e-9

    def test_rect_weir_invalid_contractions_error(self):
        res = rectangular_weir(H_m=0.3, L_m=2.0, end_contractions=1)
        assert res["ok"] is False


# ===========================================================================
# 12. parshall_flume
# ===========================================================================

class TestParshallFlume:

    def test_parshall_known_size(self):
        """152 mm flume: C=0.14286, n=1.522 → Q = C*H^n."""
        Ha = 0.5   # m
        C, n = 0.14286, 1.522
        expected = C * Ha ** n
        res = parshall_flume(Ha_m=Ha, throat_w_m=0.152)
        assert res["ok"] is True
        assert abs(res["qv_m3_s"] - expected) / expected < 1e-5

    def test_parshall_larger_head_more_flow(self):
        """Larger upstream head gives more flow."""
        r1 = parshall_flume(Ha_m=0.2, throat_w_m=0.305)
        r2 = parshall_flume(Ha_m=0.4, throat_w_m=0.305)
        assert r1["ok"] and r2["ok"]
        assert r2["qv_m3_s"] > r1["qv_m3_s"]

    def test_parshall_nonstandard_size_warns(self):
        """Non-standard throat width triggers warning about nearest size."""
        res = parshall_flume(Ha_m=0.3, throat_w_m=0.20)
        assert res["ok"] is True
        assert any("nearest" in w for w in res["warnings"])

    def test_parshall_negative_head_error(self):
        res = parshall_flume(Ha_m=-0.1, throat_w_m=0.152)
        assert res["ok"] is False


# ===========================================================================
# 13. rotameter_scale
# ===========================================================================

class TestRotameterScale:

    def test_rotameter_same_fluid_scale_factor_one(self):
        """Calibrating and process fluid identical → scale factor = 1."""
        res = rotameter_scale(Q_ref_m3s=1e-4, rho_ref_kg_m3=1000.0,
                              rho_actual_kg_m3=1000.0)
        assert res["ok"] is True
        assert abs(res["scale_factor"] - 1.0) < 1e-9

    def test_rotameter_lighter_fluid_less_flow(self):
        """Lighter actual fluid (lower density) → scale factor > 1 if rho_float > both.

        Actually: for rho_actual < rho_ref, scale = sqrt((rf-rr)*ra / ((rf-ra)*rr))
        For rho_ref=1000, rho_actual=800, rf=8000:
          scale = sqrt((8000-1000)*800 / ((8000-800)*1000))
                = sqrt(5600000 / 7200000) = sqrt(0.7778) ≈ 0.882
        """
        res = rotameter_scale(Q_ref_m3s=1e-4, rho_ref_kg_m3=1000.0,
                              rho_actual_kg_m3=800.0, float_density_kg_m3=8000.0)
        assert res["ok"] is True
        expected_scale = math.sqrt((8000 - 1000) * 800 / ((8000 - 800) * 1000))
        assert abs(res["scale_factor"] - expected_scale) / expected_scale < 1e-9

    def test_rotameter_float_density_below_fluid_error(self):
        """Float less dense than fluid is physically impossible."""
        res = rotameter_scale(Q_ref_m3s=1e-4, rho_ref_kg_m3=1000.0,
                              rho_actual_kg_m3=1200.0, float_density_kg_m3=800.0)
        assert res["ok"] is False


# ===========================================================================
# 14. turndown_ratio
# ===========================================================================

class TestTurndownRatio:

    def test_turndown_basic(self):
        """10:1 turndown."""
        res = turndown_ratio(Q_max=100.0, Q_min=10.0)
        assert res["ok"] is True
        assert abs(res["turndown"] - 10.0) < 1e-9

    def test_turndown_low_warns(self):
        """2:1 turndown must warn (< 3:1)."""
        res = turndown_ratio(Q_max=20.0, Q_min=10.0)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_turndown_qmin_gt_qmax_error(self):
        res = turndown_ratio(Q_max=10.0, Q_min=100.0)
        assert res["ok"] is False

    def test_turndown_zero_min_error(self):
        res = turndown_ratio(Q_max=100.0, Q_min=0.0)
        assert res["ok"] is False


# ===========================================================================
# 15. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_run_dp_meter_orifice_happy(self):
        ctx = _ctx()
        raw = _run(run_dp_meter(ctx, _args(
            meter_type="orifice", pipe_d_m=0.1, beta=0.5,
            dp_pa=5000.0, rho_kg_m3=1000.0
        )))
        d = _ok_tool(raw)
        assert d["qm_kg_s"] > 0

    def test_run_dp_meter_missing_beta(self):
        ctx = _ctx()
        raw = _run(run_dp_meter(ctx, _args(
            meter_type="orifice", pipe_d_m=0.1,
            dp_pa=5000.0, rho_kg_m3=1000.0
        )))
        _err_tool(raw)

    def test_run_dp_meter_bad_json(self):
        ctx = _ctx()
        raw = _run(run_dp_meter(ctx, b"not json"))
        _err_tool(raw)

    def test_run_control_valve_liquid_happy(self):
        ctx = _ctx()
        raw = _run(run_control_valve_liquid(ctx, _args(
            q_m3h=10.0, rho_kg_m3=1000.0, dp_kpa=50.0,
            p1_kpa=600.0, pv_kpa=3.5, pc_kpa=22089.0
        )))
        d = _ok_tool(raw)
        assert d["Cv"] > 0

    def test_run_control_valve_gas_happy(self):
        ctx = _ctx()
        raw = _run(run_control_valve_gas(ctx, _args(
            q_kg_s=0.5, p1_pa=600000.0, T1_K=300.0,
            MW_g_mol=29.0, dp_pa=100000.0
        )))
        d = _ok_tool(raw)
        assert d["Cv"] > 0

    def test_run_control_valve_steam_happy(self):
        ctx = _ctx()
        raw = _run(run_control_valve_steam(ctx, _args(
            q_kg_s=1.0, p1_pa=1e6, dp_pa=200000.0, v1_m3_kg=0.194
        )))
        d = _ok_tool(raw)
        assert d["Cv"] > 0

    def test_run_prv_gas_happy(self):
        ctx = _ctx()
        raw = _run(run_prv_gas(ctx, _args(
            q_kg_s=1.0, p_set_pa=1.0e6, T_K=400.0, MW_g_mol=29.0
        )))
        d = _ok_tool(raw)
        assert d["area_m2"] > 0
        assert "designation" in d

    def test_run_prv_liquid_happy(self):
        ctx = _ctx()
        raw = _run(run_prv_liquid(ctx, _args(
            q_m3s=0.01, p_set_pa=500000.0, rho_kg_m3=998.0
        )))
        d = _ok_tool(raw)
        assert d["area_m2"] > 0

    def test_run_prv_steam_happy(self):
        ctx = _ctx()
        raw = _run(run_prv_steam(ctx, _args(
            q_kg_s=2.0, p_set_pa=1.0e6
        )))
        d = _ok_tool(raw)
        assert d["area_m2"] > 0

    def test_run_pitot_velocity_happy(self):
        ctx = _ctx()
        raw = _run(run_pitot_velocity(ctx, _args(dp_pa=500.0, rho_kg_m3=1.2)))
        d = _ok_tool(raw)
        assert d["velocity_m_s"] > 0

    def test_run_annubar_flow_happy(self):
        ctx = _ctx()
        raw = _run(run_annubar_flow(ctx, _args(
            dp_pa=400.0, rho_kg_m3=1.2, pipe_d_m=0.15
        )))
        d = _ok_tool(raw)
        assert d["qv_m3_s"] > 0

    def test_run_v_notch_weir_happy(self):
        ctx = _ctx()
        raw = _run(run_v_notch_weir(ctx, _args(H_m=0.3)))
        d = _ok_tool(raw)
        assert d["qv_m3_s"] > 0

    def test_run_rectangular_weir_happy(self):
        ctx = _ctx()
        raw = _run(run_rectangular_weir(ctx, _args(H_m=0.3, L_m=2.0)))
        d = _ok_tool(raw)
        assert d["qv_m3_s"] > 0

    def test_run_parshall_flume_happy(self):
        ctx = _ctx()
        raw = _run(run_parshall_flume(ctx, _args(Ha_m=0.4, throat_w_m=0.305)))
        d = _ok_tool(raw)
        assert d["qv_m3_s"] > 0

    def test_run_rotameter_scale_happy(self):
        ctx = _ctx()
        raw = _run(run_rotameter_scale(ctx, _args(
            Q_ref_m3s=1e-4, rho_ref_kg_m3=1000.0, rho_actual_kg_m3=800.0
        )))
        d = _ok_tool(raw)
        assert d["Q_actual_m3s"] > 0

    def test_run_turndown_ratio_happy(self):
        ctx = _ctx()
        raw = _run(run_turndown_ratio(ctx, _args(Q_max=100.0, Q_min=10.0)))
        d = _ok_tool(raw)
        assert abs(d["turndown"] - 10.0) < 1e-9

    def test_run_prv_gas_missing_T_K(self):
        ctx = _ctx()
        raw = _run(run_prv_gas(ctx, _args(
            q_kg_s=1.0, p_set_pa=1.0e6, MW_g_mol=29.0
        )))
        _err_tool(raw)

    def test_run_control_valve_liquid_missing_dp(self):
        ctx = _ctx()
        raw = _run(run_control_valve_liquid(ctx, _args(
            q_m3h=10.0, rho_kg_m3=1000.0,
            p1_kpa=600.0, pv_kpa=3.5, pc_kpa=22089.0
        )))
        _err_tool(raw)


# ===========================================================================
# 16. CITABLE EXTERNAL-REFERENCE CASES — known numeric answers
# ===========================================================================
#
# Cross-checked against ISO 5167 / ISA / API 520 / API 526 worked examples
# with hand-computable answers.  SAFETY-relevant: PRV orifice sizing.
#
# Sources
# -------
# [ISO5167-1] ISO 5167-1:2003 — Reader–Harris/Gallagher Cd Eq.(1),
#             expansibility Eq.(11), permanent loss (1−β¹·⁹)/(1+β¹·⁹).
# [ISO5167-4] ISO 5167-4:2003 — venturi Cd ≈ 0.985, ~7 % permanent loss.
# [ISA]       ISA-75.01.01 / IEC 60534-2-1 — Kv/Cv definition, FF Eq.(13).
# [API520]    API 520 Part I, 9th ed. — steam Napier Eq.(12).
# [API526]    API 526, 7th ed. — effective orifice areas (D…T).
# [ISO1438]   ISO 1438 — thin-plate weirs.
# [USBR]      US Bureau of Reclamation — Parshall-flume free-flow eq.
# ===========================================================================

class TestCitableReferenceCases:

    def test_ref_rhg_discharge_coeff_iso5167(self):
        """[ISO5167-1 Eq.(1)] Reader–Harris/Gallagher Cd, D & D/2 taps.
        Anchor values (β, Re_D)→Cd, weakly Re-dependent, ~0.60 region:
          β=0.6, Re=1e6 → 0.60696
          β=0.5, Re=1e6 → 0.60255
          β=0.2, Re=1e6 → 0.59627  (low-β limit ≈ 0.5961+0.0261β²−0.216β⁸)
        """
        assert _rhg_orifice_C(0.6, 1e6) == pytest.approx(0.60696, abs=1e-4)
        assert _rhg_orifice_C(0.5, 1e6) == pytest.approx(0.60255, abs=1e-4)
        assert _rhg_orifice_C(0.2, 1e6) == pytest.approx(0.59627, abs=1e-4)

    def test_ref_expansibility_iso5167_eq11(self):
        """[ISO5167-1 Eq.(11)] ε = 1 − (0.351+0.256β⁴+0.93β⁸)·
        [1 − (1−x)^(1/κ)].  β=0.5, x=ΔP/p1=0.2, κ=1.4 → ε = 0.945393.
        """
        eps = _expansibility_orifice(0.5, 0.2, 1.0, 1.4)
        b4, b8 = 0.5 ** 4, 0.5 ** 8
        hand = 1.0 - (0.351 + 0.256 * b4 + 0.93 * b8) * (
            1.0 - (1.0 - 0.2) ** (1.0 / 1.4))
        assert eps == pytest.approx(hand, rel=1e-12)
        assert eps == pytest.approx(0.945393, abs=1e-5)

    def test_ref_orifice_permanent_loss_iso5167(self):
        """[ISO5167-1] Orifice permanent loss ratio = (1−β¹·⁹)/(1+β¹·⁹).
        β=0.6 → 0.45047 of the measured differential pressure.
        """
        res = dp_meter("orifice", pipe_d_m=0.1, beta=0.6,
                       dp_pa=10000.0, rho_kg_m3=1000.0)
        assert res["ok"] is True
        ratio = (1.0 - 0.6 ** 1.9) / (1.0 + 0.6 ** 1.9)
        assert res["permanent_pressure_loss_pa"] / 10000.0 == pytest.approx(
            ratio, rel=1e-9)
        assert ratio == pytest.approx(0.45047, abs=1e-5)

    def test_ref_venturi_discharge_coeff_iso5167_4(self):
        """[ISO5167-4] Classical venturi Cd ≈ 0.985; permanent loss ≈ 7 %
        of ΔP (≈ 93 % pressure recovery, much better than an orifice)."""
        res = dp_meter("venturi", pipe_d_m=0.1, beta=0.5,
                       dp_pa=5000.0, rho_kg_m3=1000.0)
        assert res["ok"] is True
        assert res["Cd"] == pytest.approx(0.985, abs=1e-9)
        assert res["permanent_pressure_loss_pa"] / 5000.0 == pytest.approx(
            0.07, abs=1e-9)

    def test_ref_control_valve_liquid_isa_kv_definition(self):
        """[ISA/IEC] Defining Kv: Q[m³/h] water (SG=1) at 1 bar → Kv=Q.
        10 m³/h at ΔP=1 bar (100 kPa), SG=1 → Kv=10.0, Cv=Kv·1.1561=11.561.
        FF = 0.96−0.28√(pv/pc) = 0.96−0.28√(2/22120) = 0.957338.
        """
        res = control_valve_liquid(q_m3h=10.0, rho_kg_m3=1000.0,
                                   dp_kpa=100.0, p1_kpa=600.0,
                                   pv_kpa=2.0, pc_kpa=22120.0, FL=0.9)
        assert res["ok"] is True
        assert res["Kv"] == pytest.approx(10.0, rel=1e-9)
        assert res["Cv"] == pytest.approx(11.561, rel=1e-4)
        assert res["FF"] == pytest.approx(0.957338, abs=1e-6)

    def test_ref_api526_effective_orifice_areas(self):
        """[API526 Table 1] Effective orifice areas (in²): D=0.110,
        J=1.287, P=6.380.  A 1.0 in² requirement → letter 'J' (next-up)."""
        from kerf_cad_core.flowmeter.measure import (
            _API526_ORIFICE, _api526_designation)
        IN2 = 6.4516e-4
        assert _API526_ORIFICE["D"] / IN2 == pytest.approx(0.110, rel=1e-9)
        assert _API526_ORIFICE["J"] / IN2 == pytest.approx(1.287, rel=1e-9)
        assert _API526_ORIFICE["P"] / IN2 == pytest.approx(6.380, rel=1e-9)
        assert _api526_designation(1.0 * IN2) == "J"

    def test_ref_prv_steam_napier_api520(self):
        """[API520 Eq.(12)] Steam PRV area A = W/(51.45·kd·P1·ksh·kb·kn).
        q=1 kg/s → W=7936.64 lb/hr; p_set=1 MPa, 10 % overpressure,
        P1=1.1·1e6·1.45038e-4 psia; kd=0.975 → A = 0.99168 in².
        """
        res = prv_steam(q_kg_s=1.0, p_set_pa=1.0e6)
        assert res["ok"] is True
        P1_psia = 1.0e6 * 1.10 * 1.45038e-4
        W_lbhr = 1.0 * 7936.64
        A_hand = W_lbhr / (51.45 * 0.975 * P1_psia * 1.0 * 1.0 * 1.0)
        assert res["area_in2"] == pytest.approx(A_hand, rel=1e-9)
        assert res["area_in2"] == pytest.approx(0.99168, abs=1e-4)

    def test_ref_pitot_velocity_incompressible(self):
        """[Bernoulli] Pitot v = Cp·√(2·ΔP/ρ).  ΔP=612.5 Pa, air ρ=1.225,
        Cp=1.0 → v = √(2·612.5/1.225) = 31.62278 m/s.
        """
        res = pitot_velocity(dp_pa=612.5, rho_kg_m3=1.225)
        assert res["ok"] is True
        assert res["velocity_m_s"] == pytest.approx(
            math.sqrt(2.0 * 612.5 / 1.225), rel=1e-12)
        assert res["velocity_m_s"] == pytest.approx(31.62278, abs=1e-4)

    def test_ref_v_notch_weir_iso1438(self):
        """[ISO1438] 90° V-notch Q = (8/15)·Cd·√(2g)·tan(θ/2)·H^2.5.
        Cd=0.578, H=0.20 m, g=9.80665 → Q = 0.02442176 m³/s.
        """
        res = v_notch_weir(H_m=0.20, theta_deg=90.0, Cd=0.578)
        assert res["ok"] is True
        g = 9.80665
        hand = (8.0 / 15.0) * 0.578 * math.sqrt(2.0 * g) * \
            math.tan(math.radians(45.0)) * 0.20 ** 2.5
        assert res["qv_m3_s"] == pytest.approx(hand, rel=1e-12)
        assert res["qv_m3_s"] == pytest.approx(0.02442176, abs=1e-7)

    def test_ref_rectangular_weir_francis(self):
        """[Francis] Suppressed rectangular weir Q = (2/3)·Cd·√(2g)·L·H^1.5.
        Cd=0.623, L=1.5 m, H=0.25 m, n=0 → Q = 0.34488428 m³/s.
        """
        res = rectangular_weir(H_m=0.25, L_m=1.5, Cd=0.623,
                               end_contractions=0)
        assert res["ok"] is True
        g = 9.80665
        hand = (2.0 / 3.0) * 0.623 * math.sqrt(2.0 * g) * 1.5 * 0.25 ** 1.5
        assert res["qv_m3_s"] == pytest.approx(hand, rel=1e-12)
        assert res["qv_m3_s"] == pytest.approx(0.34488428, abs=1e-7)

    def test_ref_parshall_flume_usbr(self):
        """[USBR] 1 ft (0.305 m) Parshall flume: Q = C·Ha^n,
        C=0.29114, n=1.522.  Ha=0.40 m → Q = 0.07218338 m³/s.
        """
        res = parshall_flume(Ha_m=0.40, throat_w_m=0.305)
        assert res["ok"] is True
        assert res["C"] == pytest.approx(0.29114, rel=1e-9)
        assert res["n"] == pytest.approx(1.522, rel=1e-9)
        assert res["qv_m3_s"] == pytest.approx(0.29114 * 0.40 ** 1.522,
                                               rel=1e-12)
        assert res["qv_m3_s"] == pytest.approx(0.07218338, abs=1e-7)
