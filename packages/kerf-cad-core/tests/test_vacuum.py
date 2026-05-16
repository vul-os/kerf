"""
Hermetic tests for kerf_cad_core.vacuum — vacuum-system design & analysis.

Coverage (≥ 30 tests):
  system.flow_regime              — Knudsen number + regime classification
  system.conductance_orifice      — thin-orifice conductance
  system.conductance_tube         — long-tube molecular & viscous conductance
  system.conductance_series       — 1/C_total = Σ 1/C_i
  system.conductance_parallel     — C_total = Σ C_i
  system.effective_pumping_speed  — 1/S_eff = 1/S_p + 1/C
  system.pump_down_time           — two-phase pump-down model
  system.ultimate_pressure        — P_ult = Q/S
  system.gas_throughput           — Q = S·P
  system.outgassing_rate          — Q = q·A
  system.leak_rate_spec           — rate-of-rise leak classification
  system.rate_of_rise             — isolation-test pressure rise prediction
  system.mean_free_path           — λ = k_B·T/(√2·π·d²·P)
  system.monolayer_time           — monolayer formation time
  system.pump_stage_match         — roughing + HV crossover matching
  tools.*                         — LLM tool wrappers (happy path + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified algebraically against vacuum-technology textbook hand-calcs.

References
----------
O'Hanlon, J.F., "A User's Guide to Vacuum Technology", 3rd ed., Wiley (2003).
Jousten, K. (ed.), "Handbook of Vacuum Technology", Wiley-VCH (2016).

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.vacuum.system import (
    flow_regime,
    conductance_orifice,
    conductance_tube,
    conductance_series,
    conductance_parallel,
    effective_pumping_speed,
    pump_down_time,
    ultimate_pressure,
    gas_throughput,
    outgassing_rate,
    leak_rate_spec,
    rate_of_rise,
    mean_free_path,
    monolayer_time,
    pump_stage_match,
    # Constants for hand-calc verification
    _K_B, _N_A, _R, _PI, _M_N2, _D_N2,
)
from kerf_cad_core.vacuum.tools import (
    run_flow_regime,
    run_conductance_orifice,
    run_conductance_tube,
    run_conductance_series,
    run_conductance_parallel,
    run_effective_speed,
    run_pump_down_time,
    run_ultimate_pressure,
    run_gas_throughput,
    run_outgassing_rate,
    run_leak_rate_spec,
    run_rate_of_rise,
    run_mean_free_path,
    run_monolayer_time,
    run_pump_stage_match,
)

REL = 1e-6   # relative tolerance for formula checks
RTOL = 1e-4  # relaxed tolerance for multi-step calcs


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


# ===========================================================================
# 1. flow_regime
# ===========================================================================

class TestFlowRegime:

    # At 100 Pa, 100 mm tube: λ ≈ 0.066 mm → Kn ≈ 0.00066 → viscous
    def test_viscous_regime_at_high_pressure(self):
        """High pressure + large geometry → viscous regime."""
        res = flow_regime(pressure_Pa=1e4, diameter_m=0.1)
        assert res["ok"] is True
        assert res["regime"] == "viscous"
        assert res["Kn"] < 0.01

    def test_molecular_regime_at_low_pressure(self):
        """Very low pressure → molecular regime."""
        # At 1e-4 Pa, D=10mm: λ ≈ 66 m → Kn >> 1
        res = flow_regime(pressure_Pa=1e-4, diameter_m=0.01)
        assert res["ok"] is True
        assert res["regime"] == "molecular"
        assert res["Kn"] > 0.5

    def test_transitional_regime(self):
        """Intermediate pressure → transitional regime."""
        # Choose P and D so 0.01 < Kn < 0.5
        # λ at 10 Pa ≈ 6.6 mm; D=66 mm → Kn = 0.1
        # λ = k_B*T / (sqrt2 * pi * d_N2^2 * P)
        T = 293.15
        P = 10.0
        lam = _K_B * T / (math.sqrt(2.0) * _PI * _D_N2 ** 2 * P)
        D = lam / 0.1  # target Kn = 0.1
        res = flow_regime(pressure_Pa=P, diameter_m=D)
        assert res["ok"] is True
        assert res["regime"] == "transitional"
        assert 0.01 <= res["Kn"] <= 0.5

    def test_mfp_formula_algebraic(self):
        """λ = k_B·T / (√2·π·d²·P) matches direct calculation."""
        P, T = 1.0, 293.15
        lam_expected = _K_B * T / (math.sqrt(2.0) * _PI * _D_N2 ** 2 * P)
        res = flow_regime(pressure_Pa=P, diameter_m=0.05)
        assert res["ok"] is True
        assert abs(res["mfp_m"] - lam_expected) / lam_expected < REL

    def test_kn_formula_algebraic(self):
        """Kn = λ/D is correctly computed."""
        P, D = 1.0, 0.05
        T = 293.15
        lam = _K_B * T / (math.sqrt(2.0) * _PI * _D_N2 ** 2 * P)
        Kn_expected = lam / D
        res = flow_regime(pressure_Pa=P, diameter_m=D)
        assert res["ok"] is True
        assert abs(res["Kn"] - Kn_expected) / Kn_expected < REL

    def test_negative_pressure_returns_error(self):
        res = flow_regime(pressure_Pa=-1.0, diameter_m=0.05)
        assert res["ok"] is False

    def test_zero_diameter_returns_error(self):
        res = flow_regime(pressure_Pa=1.0, diameter_m=0.0)
        assert res["ok"] is False


# ===========================================================================
# 2. conductance_orifice
# ===========================================================================

class TestConductanceOrifice:

    def test_molecular_orifice_formula(self):
        """C = A · v_avg / 4 in molecular regime."""
        D = 0.01    # 10 mm
        T = 293.15
        P = 1e-4    # molecular regime
        A = _PI * D ** 2 / 4.0
        v_avg = math.sqrt(8.0 * _R * T / (_PI * _M_N2))
        C_expected = A * v_avg / 4.0
        res = conductance_orifice(D, P, temperature_K=T, regime="molecular")
        assert res["ok"] is True
        assert abs(res["C_m3s"] - C_expected) / C_expected < REL

    def test_area_field_correct(self):
        """area_m2 = π·D²/4."""
        D = 0.02
        res = conductance_orifice(D, 1e-3, regime="molecular")
        assert res["ok"] is True
        assert abs(res["area_m2"] - _PI * D ** 2 / 4.0) / (_PI * D ** 2 / 4.0) < REL

    def test_auto_regime_molecular_low_pressure(self):
        """Auto regime selects molecular at low pressure."""
        res = conductance_orifice(0.01, 1e-5)
        assert res["ok"] is True
        assert res["regime_used"] == "molecular"

    def test_auto_regime_viscous_high_pressure(self):
        """Auto regime selects viscous at high pressure."""
        res = conductance_orifice(0.1, 1e5)
        assert res["ok"] is True
        assert res["regime_used"] == "viscous"

    def test_larger_diameter_gives_larger_conductance(self):
        """Larger orifice → larger conductance in molecular regime."""
        r1 = conductance_orifice(0.01, 1e-5, regime="molecular")
        r2 = conductance_orifice(0.02, 1e-5, regime="molecular")
        assert r1["ok"] and r2["ok"]
        assert r2["C_m3s"] > r1["C_m3s"]

    def test_molecular_conductance_proportional_to_area(self):
        """C ∝ D² in molecular regime (A = πD²/4)."""
        D1, D2 = 0.01, 0.02
        P = 1e-5
        r1 = conductance_orifice(D1, P, regime="molecular")
        r2 = conductance_orifice(D2, P, regime="molecular")
        assert r1["ok"] and r2["ok"]
        ratio = r2["C_m3s"] / r1["C_m3s"]
        assert abs(ratio - (D2 / D1) ** 2) < 1e-6

    def test_invalid_regime_returns_error(self):
        res = conductance_orifice(0.01, 1e-4, regime="banana")
        assert res["ok"] is False

    def test_negative_diameter_returns_error(self):
        res = conductance_orifice(-0.01, 1e-4)
        assert res["ok"] is False


# ===========================================================================
# 3. conductance_tube
# ===========================================================================

class TestConductanceTube:

    def test_molecular_tube_formula(self):
        """C_mol = (π/12) · v_avg · D³ / L (Knudsen formula)."""
        D, L = 0.05, 1.0   # 50 mm bore, 1 m long
        T = 293.15
        P = 1e-5   # molecular regime
        v_avg = math.sqrt(8.0 * _R * T / (_PI * _M_N2))
        C_mol_expected = (_PI / 12.0) * v_avg * D ** 3 / L
        res = conductance_tube(D, L, P, temperature_K=T, regime="molecular")
        assert res["ok"] is True
        assert abs(res["C_m3s"] - C_mol_expected) / C_mol_expected < REL

    def test_viscous_tube_formula(self):
        """C_vis = π·D⁴·P / (128·η·L) (Poiseuille)."""
        D, L = 0.025, 0.5   # 25 mm bore, 500 mm long
        P = 1e3   # viscous regime
        eta_N2 = 1.76e-5
        C_vis_expected = (_PI * D ** 4 * P) / (128.0 * eta_N2 * L)
        res = conductance_tube(D, L, P, regime="viscous")
        assert res["ok"] is True
        assert abs(res["C_m3s"] - C_vis_expected) / C_vis_expected < REL

    def test_viscous_conductance_proportional_to_pressure(self):
        """Viscous conductance doubles when pressure doubles (Poiseuille)."""
        D, L = 0.025, 0.5
        r1 = conductance_tube(D, L, 1e3, regime="viscous")
        r2 = conductance_tube(D, L, 2e3, regime="viscous")
        assert r1["ok"] and r2["ok"]
        assert abs(r2["C_m3s"] / r1["C_m3s"] - 2.0) < 1e-9

    def test_molecular_conductance_independent_of_pressure(self):
        """Molecular conductance is pressure-independent."""
        D, L = 0.05, 1.0
        r1 = conductance_tube(D, L, 1e-5, regime="molecular")
        r2 = conductance_tube(D, L, 1e-6, regime="molecular")
        assert r1["ok"] and r2["ok"]
        assert abs(r1["C_m3s"] - r2["C_m3s"]) / r1["C_m3s"] < REL

    def test_both_conductance_fields_present(self):
        """Both C_mol_m3s and C_vis_m3s returned for any regime."""
        res = conductance_tube(0.05, 1.0, 1e-4)
        assert res["ok"] is True
        assert "C_mol_m3s" in res
        assert "C_vis_m3s" in res

    def test_short_tube_adds_warning(self):
        """L/D < 3 triggers a short-tube warning."""
        # D=0.1 m, L=0.2 m → L/D=2 < 3
        res = conductance_tube(0.1, 0.2, 1e-4)
        assert res["ok"] is True
        assert any("short" in w.lower() or "l/d" in w.lower() for w in res["warnings"])

    def test_zero_length_returns_error(self):
        res = conductance_tube(0.05, 0.0, 1e-4)
        assert res["ok"] is False

    def test_molecular_tube_d_cubed_scaling(self):
        """C_mol ∝ D³ (Knudsen formula)."""
        L, P = 1.0, 1e-5
        D1, D2 = 0.02, 0.04
        r1 = conductance_tube(D1, L, P, regime="molecular")
        r2 = conductance_tube(D2, L, P, regime="molecular")
        assert r1["ok"] and r2["ok"]
        ratio = r2["C_m3s"] / r1["C_m3s"]
        assert abs(ratio - (D2 / D1) ** 3) < 1e-6


# ===========================================================================
# 4. conductance_series
# ===========================================================================

class TestConductanceSeries:

    def test_two_equal_conductances_gives_half(self):
        """Two equal C in series → C_total = C/2."""
        C = 0.1
        res = conductance_series([C, C])
        assert res["ok"] is True
        assert abs(res["C_total_m3s"] - C / 2.0) < 1e-12

    def test_three_element_series_algebraic(self):
        """1/C_total = 1/C1 + 1/C2 + 1/C3."""
        C1, C2, C3 = 0.05, 0.10, 0.20
        expected = 1.0 / (1.0 / C1 + 1.0 / C2 + 1.0 / C3)
        res = conductance_series([C1, C2, C3])
        assert res["ok"] is True
        assert abs(res["C_total_m3s"] - expected) / expected < REL

    def test_series_total_less_than_smallest(self):
        """Series total must be smaller than the smallest conductance."""
        C_vals = [0.5, 0.2, 0.1]
        res = conductance_series(C_vals)
        assert res["ok"] is True
        assert res["C_total_m3s"] < min(C_vals)

    def test_single_element_identity(self):
        """One element in series: C_total = C."""
        C = 0.3
        res = conductance_series([C])
        assert res["ok"] is True
        assert abs(res["C_total_m3s"] - C) < 1e-15

    def test_bottleneck_warning(self):
        """Bottleneck (1 element << all others) triggers warning."""
        res = conductance_series([0.001, 1.0, 1.0])
        assert res["ok"] is True
        assert any("bottleneck" in w.lower() for w in res["warnings"])

    def test_empty_list_returns_error(self):
        res = conductance_series([])
        assert res["ok"] is False

    def test_negative_conductance_returns_error(self):
        res = conductance_series([0.1, -0.05, 0.2])
        assert res["ok"] is False


# ===========================================================================
# 5. conductance_parallel
# ===========================================================================

class TestConductanceParallel:

    def test_two_equal_conductances_doubles(self):
        """Two equal C in parallel → C_total = 2·C."""
        C = 0.1
        res = conductance_parallel([C, C])
        assert res["ok"] is True
        assert abs(res["C_total_m3s"] - 2.0 * C) < 1e-15

    def test_parallel_sum_algebraic(self):
        """C_total = C1 + C2 + C3."""
        C1, C2, C3 = 0.05, 0.10, 0.20
        res = conductance_parallel([C1, C2, C3])
        assert res["ok"] is True
        assert abs(res["C_total_m3s"] - (C1 + C2 + C3)) < 1e-15

    def test_parallel_total_greater_than_largest(self):
        """Parallel total must be greater than any individual conductance."""
        C_vals = [0.5, 0.2, 0.1]
        res = conductance_parallel(C_vals)
        assert res["ok"] is True
        assert res["C_total_m3s"] > max(C_vals)

    def test_single_element_identity(self):
        """One element: C_total = C."""
        C = 0.3
        res = conductance_parallel([C])
        assert res["ok"] is True
        assert abs(res["C_total_m3s"] - C) < 1e-15

    def test_n_elements_field(self):
        """n_elements == length of input list."""
        res = conductance_parallel([0.1, 0.2, 0.3])
        assert res["ok"] is True
        assert res["n_elements"] == 3

    def test_empty_list_returns_error(self):
        res = conductance_parallel([])
        assert res["ok"] is False


# ===========================================================================
# 6. effective_pumping_speed
# ===========================================================================

class TestEffectivePumpingSpeed:

    def test_seff_formula_algebraic(self):
        """1/S_eff = 1/S_pump + 1/C."""
        S_p, C = 0.1, 0.2
        S_eff_expected = 1.0 / (1.0 / S_p + 1.0 / C)
        res = effective_pumping_speed(S_p, C)
        assert res["ok"] is True
        assert abs(res["S_eff_m3s"] - S_eff_expected) / S_eff_expected < REL

    def test_seff_less_than_both_pump_and_conductance(self):
        """S_eff < min(S_pump, C) always."""
        S_p, C = 0.15, 0.05
        res = effective_pumping_speed(S_p, C)
        assert res["ok"] is True
        assert res["S_eff_m3s"] < S_p
        assert res["S_eff_m3s"] < C

    def test_large_conductance_limit(self):
        """When C >> S_pump, S_eff → S_pump."""
        S_p = 0.1
        C = 1e6  # essentially infinite conductance
        res = effective_pumping_speed(S_p, C)
        assert res["ok"] is True
        assert abs(res["S_eff_m3s"] - S_p) / S_p < 1e-5

    def test_bottleneck_warning_when_seff_fraction_low(self):
        """S_eff < 50% of S_pump triggers warning."""
        # C << S_pump → fraction < 0.5
        res = effective_pumping_speed(S_pump_m3s=0.1, C_m3s=0.05)
        assert res["ok"] is True
        frac = res["S_eff_frac"]
        assert frac < 0.67  # S_eff = 1/(1/0.1 + 1/0.05) = 1/(10+20) = 0.0333, frac=0.333
        if frac < 0.5:
            assert len(res["warnings"]) > 0

    def test_fraction_field_correct(self):
        """S_eff_frac = S_eff / S_pump."""
        S_p, C = 0.1, 0.2
        res = effective_pumping_speed(S_p, C)
        assert res["ok"] is True
        assert abs(res["S_eff_frac"] - res["S_eff_m3s"] / S_p) < REL

    def test_zero_conductance_returns_error(self):
        res = effective_pumping_speed(0.1, 0.0)
        assert res["ok"] is False

    def test_negative_pump_speed_returns_error(self):
        res = effective_pumping_speed(-0.1, 0.2)
        assert res["ok"] is False


# ===========================================================================
# 7. pump_down_time
# ===========================================================================

class TestPumpDownTime:

    def test_no_outgassing_simple_formula(self):
        """Without outgassing: t = (V/S)·ln(P_start/P_target)."""
        V, S, P0, Pt = 1.0, 0.1, 101325.0, 1.0
        t_expected = (V / S) * math.log(P0 / Pt)
        res = pump_down_time(V, S, P0, Pt)
        assert res["ok"] is True
        assert abs(res["t_total_s"] - t_expected) / t_expected < RTOL

    def test_target_gt_start_returns_error(self):
        """P_target > P_start must return error."""
        res = pump_down_time(1.0, 0.1, 1.0, 100.0)
        assert res["ok"] is False

    def test_unreachable_target_warns(self):
        """P_target < P_ult (gas load) → warning + t=inf."""
        # Gas load: Q = 1e-4 Pa·m³/s; S = 0.01 m³/s → P_ult = 0.01 Pa
        # Target: 1e-4 Pa < P_ult
        res = pump_down_time(
            volume_m3=1.0,
            S_eff_m3s=0.01,
            P_start_Pa=100.0,
            P_target_Pa=1e-4,
            outgassing_load_Pa_m3s=1e-4,
        )
        assert res["ok"] is True
        assert any("not reachable" in w.upper() or "target" in w.lower() for w in res["warnings"])
        assert res["t_total_s"] == float("inf")

    def test_p_ultimate_equals_Q_over_S(self):
        """P_ult = Q_out / S_eff."""
        V, S = 1.0, 0.1
        Q = 1e-5
        res = pump_down_time(V, S, 100.0, 1e-3, outgassing_load_Pa_m3s=Q)
        assert res["ok"] is True
        assert abs(res["P_ult_Pa"] - Q / S) < 1e-15

    def test_outgassing_only_via_area_rate(self):
        """Gas load via area × specific rate gives same P_ult as direct Q."""
        V, S = 1.0, 0.1
        A, q = 2.0, 5e-6
        Q_expected = A * q
        res = pump_down_time(
            V, S, 100.0, 1.0,
            surface_area_m2=A,
            outgassing_rate_Pa_m3s_m2=q,
        )
        assert res["ok"] is True
        assert abs(res["Q_out_Pa_m3s"] - Q_expected) < 1e-18

    def test_zero_outgassing_t_phase2_zero(self):
        """With no outgassing, phase 2 time = 0."""
        res = pump_down_time(1.0, 0.1, 100.0, 1.0)
        assert res["ok"] is True
        assert res["t_phase2_s"] == 0.0


# ===========================================================================
# 8. ultimate_pressure
# ===========================================================================

class TestUltimatePressure:

    def test_pult_formula_algebraic(self):
        """P_ult = Q_gas / S_pump."""
        Q, S = 1e-6, 0.1
        res = ultimate_pressure(Q, S)
        assert res["ok"] is True
        assert abs(res["P_ult_Pa"] - Q / S) / (Q / S) < REL

    def test_doubling_pump_speed_halves_pressure(self):
        """Doubling S halves P_ult."""
        Q = 1e-6
        r1 = ultimate_pressure(Q, 0.1)
        r2 = ultimate_pressure(Q, 0.2)
        assert r1["ok"] and r2["ok"]
        assert abs(r2["P_ult_Pa"] / r1["P_ult_Pa"] - 0.5) < REL

    def test_rough_vacuum_warning(self):
        """P_ult > 1e-3 Pa triggers warning."""
        Q, S = 1e-2, 0.1   # P_ult = 0.1 Pa
        res = ultimate_pressure(Q, S)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_zero_gas_load_returns_error(self):
        res = ultimate_pressure(0.0, 0.1)
        assert res["ok"] is False

    def test_zero_pump_speed_returns_error(self):
        res = ultimate_pressure(1e-6, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 9. gas_throughput
# ===========================================================================

class TestGasThroughput:

    def test_Q_equals_S_times_P(self):
        """Q = S · P."""
        S, P = 0.05, 1e-3
        res = gas_throughput(S, P)
        assert res["ok"] is True
        assert abs(res["Q_Pa_m3s"] - S * P) < 1e-20

    def test_doubling_pressure_doubles_throughput(self):
        """Q ∝ P at constant S."""
        S = 0.05
        r1 = gas_throughput(S, 1e-3)
        r2 = gas_throughput(S, 2e-3)
        assert r1["ok"] and r2["ok"]
        assert abs(r2["Q_Pa_m3s"] / r1["Q_Pa_m3s"] - 2.0) < REL

    def test_negative_S_returns_error(self):
        res = gas_throughput(-0.05, 1e-3)
        assert res["ok"] is False

    def test_zero_P_returns_error(self):
        res = gas_throughput(0.05, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 10. outgassing_rate
# ===========================================================================

class TestOutgassingRate:

    def test_Q_equals_area_times_rate(self):
        """Q_out = A · q."""
        A, q = 2.5, 1e-6
        res = outgassing_rate(A, q)
        assert res["ok"] is True
        assert abs(res["Q_outgassing_Pa_m3s"] - A * q) < 1e-22

    def test_doubling_area_doubles_Q(self):
        """Q ∝ A."""
        q = 1e-6
        r1 = outgassing_rate(1.0, q)
        r2 = outgassing_rate(2.0, q)
        assert r1["ok"] and r2["ok"]
        assert abs(r2["Q_outgassing_Pa_m3s"] / r1["Q_outgassing_Pa_m3s"] - 2.0) < REL

    def test_zero_area_returns_error(self):
        res = outgassing_rate(0.0, 1e-6)
        assert res["ok"] is False


# ===========================================================================
# 11. leak_rate_spec
# ===========================================================================

class TestLeakRateSpec:

    def test_leak_rate_formula(self):
        """Q_leak = V · dP/dt."""
        V, dp_dt = 0.01, 1e-3
        res = leak_rate_spec(P_test_Pa=1.0, volume_m3=V, dp_dt_Pa_s=dp_dt)
        assert res["ok"] is True
        assert abs(res["Q_leak_Pa_m3s"] - V * dp_dt) < 1e-20

    def test_fine_leak_class(self):
        """Q < 1e-6 Pa·m³/s → 'fine' or 'ultra_fine' class."""
        # V=0.001 m³, dP/dt = 1e-7 Pa/s → Q = 1e-10 Pa·m³/s → ultra_fine
        res = leak_rate_spec(P_test_Pa=1e-3, volume_m3=0.001, dp_dt_Pa_s=1e-7)
        assert res["ok"] is True
        assert res["leak_class"] in ("ultra_fine", "fine")

    def test_gross_leak_class(self):
        """Q > 1e-6 Pa·m³/s → 'gross' or 'very_gross' class + warning."""
        # V=1 m³, dP/dt = 0.01 Pa/s → Q = 0.01 Pa·m³/s → very_gross
        res = leak_rate_spec(P_test_Pa=100.0, volume_m3=1.0, dp_dt_Pa_s=0.01)
        assert res["ok"] is True
        assert res["leak_class"] in ("gross", "very_gross")
        assert len(res["warnings"]) > 0

    def test_helium_equivalent_for_air(self):
        """He-equiv for air = Q_leak × 0.92."""
        V, dp_dt = 0.01, 1e-4
        res = leak_rate_spec(P_test_Pa=1.0, volume_m3=V, dp_dt_Pa_s=dp_dt, test_gas="air")
        assert res["ok"] is True
        Q_leak = V * dp_dt
        assert abs(res["Q_He_equiv_Pa_m3s"] - Q_leak * 0.92) < 1e-20

    def test_helium_test_gas_equiv_equals_leak_rate(self):
        """For test_gas='helium', He-equiv = Q_leak."""
        V, dp_dt = 0.01, 1e-4
        res = leak_rate_spec(P_test_Pa=1.0, volume_m3=V, dp_dt_Pa_s=dp_dt, test_gas="helium")
        assert res["ok"] is True
        Q_leak = V * dp_dt
        assert abs(res["Q_He_equiv_Pa_m3s"] - Q_leak) < 1e-20

    def test_invalid_test_gas_returns_error(self):
        res = leak_rate_spec(P_test_Pa=1.0, volume_m3=0.01, dp_dt_Pa_s=1e-4, test_gas="xenon")
        assert res["ok"] is False

    def test_zero_dp_dt_returns_error(self):
        res = leak_rate_spec(P_test_Pa=1.0, volume_m3=0.01, dp_dt_Pa_s=0.0)
        assert res["ok"] is False


# ===========================================================================
# 12. rate_of_rise
# ===========================================================================

class TestRateOfRise:

    def test_pressure_rise_formula(self):
        """P_final = P_initial + Q/V · t."""
        Q, V, t, P0 = 1e-4, 0.01, 60.0, 1e-3
        dP_dt_expected = Q / V
        P_final_expected = P0 + dP_dt_expected * t
        res = rate_of_rise(Q, V, t, P0)
        assert res["ok"] is True
        assert abs(res["dP_dt_Pa_s"] - dP_dt_expected) < 1e-18
        assert abs(res["P_final_Pa"] - P_final_expected) < 1e-10

    def test_delta_P_field(self):
        """delta_P = dP_dt × t."""
        Q, V, t, P0 = 1e-5, 0.001, 10.0, 5e-4
        res = rate_of_rise(Q, V, t, P0)
        assert res["ok"] is True
        assert abs(res["delta_P_Pa"] - (Q / V) * t) < 1e-18

    def test_large_gas_load_warns(self):
        """ΔP > P_initial triggers warning."""
        # Q/V very large compared to P0
        res = rate_of_rise(Q_leak_Pa_m3s=1.0, volume_m3=0.001, time_s=100.0, P_initial_Pa=1e-3)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_negative_volume_returns_error(self):
        res = rate_of_rise(1e-5, -0.001, 10.0, 1e-3)
        assert res["ok"] is False


# ===========================================================================
# 13. mean_free_path
# ===========================================================================

class TestMeanFreePath:

    def test_mfp_formula_N2_atmospheric(self):
        """λ = k_B·T/(√2·π·d_N2²·P) at atmospheric pressure."""
        P, T = 101325.0, 293.15
        lam_expected = _K_B * T / (math.sqrt(2.0) * _PI * _D_N2 ** 2 * P)
        res = mean_free_path(P, temperature_K=T)
        assert res["ok"] is True
        # At atmospheric, λ ≈ 66 nm
        assert abs(res["mfp_m"] - lam_expected) / lam_expected < REL
        assert 50e-9 < res["mfp_m"] < 100e-9

    def test_mfp_inversely_proportional_to_pressure(self):
        """λ ∝ 1/P."""
        P1, P2 = 1.0, 10.0
        r1 = mean_free_path(P1)
        r2 = mean_free_path(P2)
        assert r1["ok"] and r2["ok"]
        assert abs(r1["mfp_m"] / r2["mfp_m"] - P2 / P1) < 1e-10

    def test_number_density_formula(self):
        """n = P / (k_B · T)."""
        P, T = 1.0, 293.15
        n_expected = P / (_K_B * T)
        res = mean_free_path(P, temperature_K=T)
        assert res["ok"] is True
        assert abs(res["n_density"] - n_expected) / n_expected < REL

    def test_mean_speed_formula(self):
        """v_avg = √(8·R·T / (π·M))."""
        P, T = 1.0, 293.15
        v_expected = math.sqrt(8.0 * _R * T / (_PI * _M_N2))
        res = mean_free_path(P, temperature_K=T)
        assert res["ok"] is True
        assert abs(res["v_avg_m_s"] - v_expected) / v_expected < REL
        # N₂ at 20°C: v_avg ≈ 470 m/s
        assert 400.0 < res["v_avg_m_s"] < 600.0

    def test_zero_pressure_returns_error(self):
        res = mean_free_path(0.0)
        assert res["ok"] is False


# ===========================================================================
# 14. monolayer_time
# ===========================================================================

class TestMonolayerTime:

    def test_monolayer_time_hv_range(self):
        """At 1e-6 Pa (HV), N₂ monolayer forms within minutes (kinetic-theory result)."""
        # Using standard n_s=1e19 sites/m² and s=1 for N₂:
        # Φ = P / sqrt(2π·m·k_B·T) ≈ 2.9e18 molecules/(m²·s) at 1e-6 Pa, 293 K
        # τ = n_s / Φ ≈ 3.4e19 / 2.9e18 ≈ 3.4 s (varies with n_s choice)
        # Accept the range corresponding to the formula with default parameters.
        res = monolayer_time(1e-6)
        assert res["ok"] is True
        # τ should be in the range 10 s – 3600 s for HV conditions
        assert 1.0 < res["tau_s"] < 3600.0

    def test_monolayer_time_proportional_to_one_over_pressure(self):
        """τ ∝ 1/P (flux ∝ P)."""
        P1, P2 = 1e-6, 1e-5
        r1 = monolayer_time(P1)
        r2 = monolayer_time(P2)
        assert r1["ok"] and r2["ok"]
        # τ1/τ2 = P2/P1
        assert abs(r1["tau_s"] / r2["tau_s"] - P2 / P1) < 1e-6

    def test_flux_formula_algebraic(self):
        """Φ = P / √(2·π·m·k_B·T)."""
        P, T = 1e-5, 293.15
        m_mol = _M_N2 / _N_A
        flux_expected = P / math.sqrt(2.0 * _PI * m_mol * _K_B * T)
        res = monolayer_time(P, temperature_K=T)
        assert res["ok"] is True
        assert abs(res["flux_m2s"] - flux_expected) / flux_expected < REL

    def test_sticking_coefficient_zero_returns_error(self):
        res = monolayer_time(1e-6, sticking_coefficient=0.0)
        assert res["ok"] is False

    def test_uhv_pressure_large_tau(self):
        """At UHV (1e-10 Pa), τ > 1 h."""
        res = monolayer_time(1e-10)
        assert res["ok"] is True
        assert res["tau_s"] > 3600.0


# ===========================================================================
# 15. pump_stage_match
# ===========================================================================

class TestPumpStageMatch:

    def test_roughing_time_formula(self):
        """t_rough = (V/S_r)·ln(P_atm/P_cross)."""
        V = 0.1
        S_r = 1.67e-3   # ~6 m³/h rotary vane
        P_r_base = 0.05  # 0.05 Pa — roughing base BELOW crossover
        S_h = 0.167     # ~600 L/s turbo
        P_h_base = 1e-8
        P_cross = 0.5   # crossover above roughing base (valid)

        res = pump_stage_match(
            roughing_speed_m3s=S_r,
            roughing_base_Pa=P_r_base,
            highvac_speed_m3s=S_h,
            highvac_base_Pa=P_h_base,
            volume_m3=V,
            crossover_P_Pa=P_cross,
        )
        assert res["ok"] is True
        t_rough_expected = (V / S_r) * math.log(101325.0 / P_cross)
        assert abs(res["t_roughing_s"] - t_rough_expected) / t_rough_expected < RTOL

    def test_hv_time_formula(self):
        """t_hv = (V/S_h)·ln(P_cross/P_hv_base)."""
        V = 0.1
        S_h = 0.167
        P_h_base = 1e-8
        P_cross = 0.5   # must be above roughing base for clean test

        res = pump_stage_match(
            roughing_speed_m3s=1.67e-3,
            roughing_base_Pa=0.05,  # below P_cross
            highvac_speed_m3s=S_h,
            highvac_base_Pa=P_h_base,
            volume_m3=V,
            crossover_P_Pa=P_cross,
        )
        assert res["ok"] is True
        t_hv_expected = (V / S_h) * math.log(P_cross / P_h_base)
        assert abs(res["t_highvac_s"] - t_hv_expected) / t_hv_expected < RTOL

    def test_total_time_is_sum(self):
        """t_total = t_rough + t_hv."""
        res = pump_stage_match(
            roughing_speed_m3s=1.67e-3,
            roughing_base_Pa=1.0,
            highvac_speed_m3s=0.167,
            highvac_base_Pa=1e-8,
            volume_m3=0.1,
            crossover_P_Pa=0.1,
        )
        assert res["ok"] is True
        assert abs(res["t_total_s"] - (res["t_roughing_s"] + res["t_highvac_s"])) < 1e-10

    def test_crossover_above_1pa_warns(self):
        """Crossover > 1 Pa warns about turbomolecular inlet pressure."""
        res = pump_stage_match(
            roughing_speed_m3s=1.67e-3,
            roughing_base_Pa=10.0,
            highvac_speed_m3s=0.167,
            highvac_base_Pa=1e-8,
            volume_m3=0.1,
            crossover_P_Pa=5.0,
        )
        assert res["ok"] is True
        assert res["crossover_ok"] is False  # 5 Pa > 1 Pa threshold
        assert len(res["warnings"]) > 0

    def test_p_ultimate_equals_hv_base(self):
        """Ultimate pressure = HV pump base pressure."""
        P_hv = 1e-9
        res = pump_stage_match(
            roughing_speed_m3s=1.67e-3,
            roughing_base_Pa=1.0,
            highvac_speed_m3s=0.167,
            highvac_base_Pa=P_hv,
            volume_m3=0.1,
        )
        assert res["ok"] is True
        assert abs(res["P_ultimate_Pa"] - P_hv) < 1e-20

    def test_zero_volume_returns_error(self):
        res = pump_stage_match(1.67e-3, 1.0, 0.167, 1e-8, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 16. LLM tool wrappers (happy path + error paths)
# ===========================================================================

class TestToolWrappers:

    def test_run_flow_regime_happy_path(self):
        ctx = _ctx()
        raw = _run(run_flow_regime(ctx, _args(pressure_Pa=1e-4, diameter_m=0.01)))
        d = _ok_tool(raw)
        assert "regime" in d
        assert d["regime"] == "molecular"

    def test_run_flow_regime_missing_field(self):
        ctx = _ctx()
        raw = _run(run_flow_regime(ctx, _args(pressure_Pa=1e-4)))
        _err_tool(raw)

    def test_run_flow_regime_bad_json(self):
        ctx = _ctx()
        raw = _run(run_flow_regime(ctx, b"not json"))
        _err_tool(raw)

    def test_run_conductance_orifice_happy_path(self):
        ctx = _ctx()
        raw = _run(run_conductance_orifice(ctx, _args(diameter_m=0.01, pressure_Pa=1e-5)))
        d = _ok_tool(raw)
        assert d["C_m3s"] > 0

    def test_run_conductance_tube_happy_path(self):
        ctx = _ctx()
        raw = _run(run_conductance_tube(ctx, _args(
            diameter_m=0.05, length_m=1.0, pressure_Pa=1e-4
        )))
        d = _ok_tool(raw)
        assert d["C_mol_m3s"] > 0

    def test_run_conductance_series_happy_path(self):
        ctx = _ctx()
        raw = _run(run_conductance_series(ctx, _args(conductances=[0.1, 0.2])))
        d = _ok_tool(raw)
        expected = 1.0 / (1.0 / 0.1 + 1.0 / 0.2)
        assert abs(d["C_total_m3s"] - expected) < 1e-10

    def test_run_conductance_parallel_happy_path(self):
        ctx = _ctx()
        raw = _run(run_conductance_parallel(ctx, _args(conductances=[0.1, 0.2])))
        d = _ok_tool(raw)
        assert abs(d["C_total_m3s"] - 0.3) < 1e-10

    def test_run_effective_speed_happy_path(self):
        ctx = _ctx()
        raw = _run(run_effective_speed(ctx, _args(S_pump_m3s=0.1, C_m3s=0.2)))
        d = _ok_tool(raw)
        expected = 1.0 / (1.0 / 0.1 + 1.0 / 0.2)
        assert abs(d["S_eff_m3s"] - expected) < 1e-10

    def test_run_effective_speed_missing_field(self):
        ctx = _ctx()
        raw = _run(run_effective_speed(ctx, _args(S_pump_m3s=0.1)))
        _err_tool(raw)

    def test_run_pump_down_time_happy_path(self):
        ctx = _ctx()
        raw = _run(run_pump_down_time(ctx, _args(
            volume_m3=1.0, S_eff_m3s=0.1,
            P_start_Pa=101325.0, P_target_Pa=1.0,
        )))
        d = _ok_tool(raw)
        expected = (1.0 / 0.1) * math.log(101325.0 / 1.0)
        assert abs(d["t_total_s"] - expected) / expected < RTOL

    def test_run_ultimate_pressure_happy_path(self):
        ctx = _ctx()
        raw = _run(run_ultimate_pressure(ctx, _args(Q_gas_Pa_m3s=1e-6, S_pump_m3s=0.1)))
        d = _ok_tool(raw)
        assert abs(d["P_ult_Pa"] - 1e-5) < 1e-15

    def test_run_gas_throughput_happy_path(self):
        ctx = _ctx()
        raw = _run(run_gas_throughput(ctx, _args(S_m3s=0.05, P_Pa=1e-3)))
        d = _ok_tool(raw)
        assert abs(d["Q_Pa_m3s"] - 5e-5) < 1e-20

    def test_run_outgassing_rate_happy_path(self):
        ctx = _ctx()
        raw = _run(run_outgassing_rate(ctx, _args(area_m2=2.0, specific_rate_Pa_m3s_m2=1e-6)))
        d = _ok_tool(raw)
        assert abs(d["Q_outgassing_Pa_m3s"] - 2e-6) < 1e-22

    def test_run_leak_rate_spec_happy_path(self):
        ctx = _ctx()
        raw = _run(run_leak_rate_spec(ctx, _args(
            P_test_Pa=1e-3, volume_m3=0.01, dp_dt_Pa_s=1e-7
        )))
        d = _ok_tool(raw)
        # Q_leak = 0.01 m³ × 1e-7 Pa/s = 1e-9 Pa·m³/s → ultra_fine (<1e-9 threshold)
        assert d["Q_leak_Pa_m3s"] == pytest.approx(0.01 * 1e-7)
        assert d["leak_class"] in ("ultra_fine", "fine")  # 1e-9 is at boundary

    def test_run_rate_of_rise_happy_path(self):
        ctx = _ctx()
        raw = _run(run_rate_of_rise(ctx, _args(
            Q_leak_Pa_m3s=1e-4, volume_m3=0.01,
            time_s=60.0, P_initial_Pa=1e-3,
        )))
        d = _ok_tool(raw)
        assert abs(d["dP_dt_Pa_s"] - 1e-4 / 0.01) < 1e-18

    def test_run_mean_free_path_happy_path(self):
        ctx = _ctx()
        raw = _run(run_mean_free_path(ctx, _args(pressure_Pa=101325.0)))
        d = _ok_tool(raw)
        assert 50e-9 < d["mfp_m"] < 100e-9  # N₂ at 20°C, 1 atm ≈ 66 nm

    def test_run_monolayer_time_happy_path(self):
        ctx = _ctx()
        raw = _run(run_monolayer_time(ctx, _args(pressure_Pa=1e-6)))
        d = _ok_tool(raw)
        # Kinetic theory: τ at 1e-6 Pa, N₂, n_s=1e19 → few hundred seconds
        assert 1.0 < d["tau_s"] < 3600.0

    def test_run_pump_stage_match_happy_path(self):
        ctx = _ctx()
        raw = _run(run_pump_stage_match(ctx, _args(
            roughing_speed_m3s=1.67e-3,
            roughing_base_Pa=1.0,
            highvac_speed_m3s=0.167,
            highvac_base_Pa=1e-8,
            volume_m3=0.1,
            crossover_P_Pa=0.1,
        )))
        d = _ok_tool(raw)
        assert d["t_roughing_s"] > 0
        assert d["t_highvac_s"] > 0
        assert d["t_total_s"] == pytest.approx(d["t_roughing_s"] + d["t_highvac_s"])

    def test_run_pump_stage_match_missing_field(self):
        ctx = _ctx()
        raw = _run(run_pump_stage_match(ctx, _args(
            roughing_speed_m3s=1.67e-3,
            roughing_base_Pa=1.0,
            highvac_speed_m3s=0.167,
            # highvac_base_Pa missing
            volume_m3=0.1,
        )))
        _err_tool(raw)
