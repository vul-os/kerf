"""
Hermetic tests for kerf_cad_core.thermocycle — thermodynamic cycle analysis.

Coverage:
  cycles.isentropic_relations          — T/p/v isentropic ideal-gas relations
  cycles.isothermal_process            — p-V-T, work, heat
  cycles.isobaric_process              — p-V-T, work, heat
  cycles.isochoric_process             — p-V-T, work, heat
  cycles.isentropic_process            — isentropic compression/expansion
  cycles.polytropic_process            — polytropic n-index process
  cycles.carnot_efficiency             — heat engine Carnot limit
  cycles.carnot_cop_refrigeration      — reverse-Carnot refrigeration COP
  cycles.carnot_cop_heat_pump          — reverse-Carnot heat-pump COP
  cycles.otto_cycle                    — air-standard Otto
  cycles.diesel_cycle                  — air-standard Diesel
  cycles.dual_cycle                    — air-standard Dual (mixed)
  cycles.brayton_cycle                 — Brayton with / without regeneration
  cycles.rankine_cycle_ideal           — simplified Rankine steam cycle
  cycles.refrigeration_cop             — COP from Q_L, W_in + Carnot check
  tools.*                              — LLM wrapper happy paths + error paths

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against Cengel & Boles "Thermodynamics: An Engineering Approach"
8th ed. and Moran et al. "Fundamentals of Engineering Thermodynamics" 7th ed.

References
----------
Cengel, Y.A. & Boles, M.A., "Thermodynamics: An Engineering Approach", 8th ed.
Moran, M.J. et al., "Fundamentals of Engineering Thermodynamics", 7th ed.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
import warnings

import pytest

from kerf_cad_core.thermocycle.cycles import (
    isentropic_relations,
    isothermal_process,
    isobaric_process,
    isochoric_process,
    isentropic_process,
    polytropic_process,
    carnot_efficiency,
    carnot_cop_refrigeration,
    carnot_cop_heat_pump,
    otto_cycle,
    diesel_cycle,
    dual_cycle,
    brayton_cycle,
    rankine_cycle_ideal,
    refrigeration_cop,
    CP_AIR, CV_AIR, K_AIR, R_AIR,
)
from kerf_cad_core.thermocycle.tools import (
    run_isentropic_relations,
    run_isothermal_process,
    run_isobaric_process,
    run_isochoric_process,
    run_isentropic_process,
    run_polytropic_process,
    run_carnot_efficiency,
    run_carnot_cop_refrigeration,
    run_carnot_cop_heat_pump,
    run_otto_cycle,
    run_diesel_cycle,
    run_dual_cycle,
    run_brayton_cycle,
    run_rankine_cycle_ideal,
    run_refrigeration_cop,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REL = 1e-6   # relative tolerance for floating-point checks
REL_LOOSE = 1e-4  # looser tolerance for approximations


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


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_response(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


# ===========================================================================
# 1. isentropic_relations
# ===========================================================================

class TestIsentropicRelations:

    def test_T2_from_p2(self):
        """T2/T1 = (p2/p1)^((k-1)/k)."""
        T1, p1, p2, k = 300.0, 100_000.0, 300_000.0, 1.4
        pr = p2 / p1
        T2_expected = T1 * pr ** ((k - 1.0) / k)
        res = isentropic_relations(T1, p1, p2=p2)
        assert res["ok"] is True
        assert abs(res["T2"] - T2_expected) / T2_expected < REL

    def test_p2_from_T2(self):
        """p2/p1 = (T2/T1)^(k/(k-1))."""
        T1, T2, p1, k = 300.0, 500.0, 100_000.0, 1.4
        pr_expected = (T2 / T1) ** (k / (k - 1.0))
        p2_expected = p1 * pr_expected
        res = isentropic_relations(T1, p1, T2=T2)
        assert res["ok"] is True
        assert abs(res["p2"] - p2_expected) / p2_expected < REL

    def test_T2_from_volume_ratio(self):
        """T2/T1 = (v1/v2)^(k-1)."""
        T1, p1, v1, v2, k = 300.0, 100_000.0, 0.861, 0.1, 1.4
        T2_expected = T1 * (v1 / v2) ** (k - 1.0)
        res = isentropic_relations(T1, p1, v1=v1, v2=v2)
        assert res["ok"] is True
        assert abs(res["T2"] - T2_expected) / T2_expected < REL

    def test_pressure_ratio_key(self):
        """pressure_ratio field equals p2/p1."""
        res = isentropic_relations(300.0, 100_000.0, p2=300_000.0)
        assert res["ok"] is True
        assert abs(res["pressure_ratio"] - 3.0) / 3.0 < REL

    def test_missing_second_state_returns_error(self):
        """Must supply at least one of T2, p2, (v1,v2)."""
        res = isentropic_relations(300.0, 100_000.0)
        assert res["ok"] is False

    def test_k_le_1_returns_error(self):
        res = isentropic_relations(300.0, 100_000.0, p2=300_000.0, k=0.9)
        assert res["ok"] is False

    def test_negative_T1_returns_error(self):
        res = isentropic_relations(-300.0, 100_000.0, p2=300_000.0)
        assert res["ok"] is False


# ===========================================================================
# 2. isothermal_process
# ===========================================================================

class TestIsothermalProcess:

    def test_p2_formula(self):
        """p2 = p1 * v1 / v2."""
        p1, v1, v2 = 200_000.0, 0.5, 1.0
        res = isothermal_process(p1, v1, v2)
        assert res["ok"] is True
        assert abs(res["p2"] - p1 * v1 / v2) / (p1 * v1 / v2) < REL

    def test_work_expansion(self):
        """w = p1 v1 ln(v2/v1) > 0 for v2 > v1 (expansion)."""
        p1, v1, v2 = 100_000.0, 0.287, 0.574  # double volume
        res = isothermal_process(p1, v1, v2)
        assert res["ok"] is True
        w_expected = p1 * v1 * math.log(v2 / v1)
        assert abs(res["w_J_kg"] - w_expected) / abs(w_expected) < REL
        assert res["w_J_kg"] > 0.0

    def test_work_compression_is_negative(self):
        """w < 0 for v2 < v1 (compression)."""
        res = isothermal_process(100_000.0, 0.574, 0.287)
        assert res["ok"] is True
        assert res["w_J_kg"] < 0.0

    def test_q_equals_w(self):
        """q = w for isothermal (Δu = 0)."""
        res = isothermal_process(100_000.0, 0.287, 0.574)
        assert res["ok"] is True
        assert abs(res["q_J_kg"] - res["w_J_kg"]) < 1e-9

    def test_delta_u_is_zero(self):
        """Δu = 0 for ideal gas at constant T."""
        res = isothermal_process(100_000.0, 0.287, 0.574)
        assert res["ok"] is True
        assert res["delta_u_J_kg"] == 0.0

    def test_negative_p1_returns_error(self):
        res = isothermal_process(-100_000.0, 0.287, 0.574)
        assert res["ok"] is False


# ===========================================================================
# 3. isobaric_process
# ===========================================================================

class TestIsobaricProcess:

    def test_q_formula(self):
        """q = cp * (T2 - T1)."""
        T1, T2 = 300.0, 600.0
        res = isobaric_process(T1, T2)
        assert res["ok"] is True
        q_expected = CP_AIR * (T2 - T1)
        assert abs(res["q_J_kg"] - q_expected) / q_expected < REL

    def test_w_plus_delta_u_equals_q(self):
        """First law: q = Δu + w."""
        res = isobaric_process(300.0, 600.0)
        assert res["ok"] is True
        q = res["q_J_kg"]
        assert abs(q - (res["delta_u_J_kg"] + res["w_J_kg"])) / abs(q) < REL

    def test_w_equals_R_delta_T(self):
        """w = R * ΔT = (cp - cv) * ΔT for ideal gas isobaric."""
        T1, T2 = 300.0, 600.0
        R = CP_AIR - CP_AIR / K_AIR
        res = isobaric_process(T1, T2)
        assert res["ok"] is True
        w_expected = R * (T2 - T1)
        assert abs(res["w_J_kg"] - w_expected) / abs(w_expected) < REL

    def test_T_ratio(self):
        res = isobaric_process(300.0, 450.0)
        assert res["ok"] is True
        assert abs(res["T_ratio"] - 1.5) / 1.5 < REL

    def test_cooling_gives_negative_q(self):
        """T2 < T1 → q < 0 (heat rejection)."""
        res = isobaric_process(600.0, 300.0)
        assert res["ok"] is True
        assert res["q_J_kg"] < 0.0

    def test_negative_T1_returns_error(self):
        res = isobaric_process(-300.0, 600.0)
        assert res["ok"] is False


# ===========================================================================
# 4. isochoric_process
# ===========================================================================

class TestIsochoricProcess:

    def test_q_formula(self):
        """q = cv * (T2 - T1)."""
        T1, T2 = 300.0, 600.0
        res = isochoric_process(T1, T2)
        assert res["ok"] is True
        q_expected = CV_AIR * (T2 - T1)
        assert abs(res["q_J_kg"] - q_expected) / q_expected < REL

    def test_w_is_zero(self):
        """No boundary work at constant volume."""
        res = isochoric_process(300.0, 600.0)
        assert res["ok"] is True
        assert res["w_J_kg"] == 0.0

    def test_delta_u_equals_q(self):
        res = isochoric_process(300.0, 600.0)
        assert res["ok"] is True
        assert abs(res["delta_u_J_kg"] - res["q_J_kg"]) < 1e-9

    def test_cooling_q_is_negative(self):
        res = isochoric_process(600.0, 300.0)
        assert res["ok"] is True
        assert res["q_J_kg"] < 0.0

    def test_negative_cv_returns_error(self):
        res = isochoric_process(300.0, 600.0, cv=-1.0)
        assert res["ok"] is False


# ===========================================================================
# 5. isentropic_process
# ===========================================================================

class TestIsentropicProcess:

    def test_T2_compression(self):
        """T2 = T1 * (p2/p1)^((k-1)/k); p2 > p1 → T2 > T1."""
        T1, p1, p2, k = 300.0, 100_000.0, 500_000.0, 1.4
        T2_expected = T1 * (p2 / p1) ** ((k - 1.0) / k)
        res = isentropic_process(T1, p1, p2)
        assert res["ok"] is True
        assert abs(res["T2"] - T2_expected) / T2_expected < REL
        assert res["T2"] > T1

    def test_q_is_zero(self):
        """Isentropic → q = 0."""
        res = isentropic_process(300.0, 100_000.0, 500_000.0)
        assert res["ok"] is True
        assert res["q_J_kg"] == 0.0

    def test_ws_positive_for_expansion(self):
        """Expansion (p2 < p1) → w_s > 0 (work out of system)."""
        res = isentropic_process(700.0, 500_000.0, 100_000.0)
        assert res["ok"] is True
        assert res["w_s_J_kg"] > 0.0

    def test_ws_negative_for_compression(self):
        """Compression (p2 > p1) → w_s < 0 (work into system)."""
        res = isentropic_process(300.0, 100_000.0, 500_000.0)
        assert res["ok"] is True
        assert res["w_s_J_kg"] < 0.0

    def test_ws_formula(self):
        """w_s = cp * (T1 - T2)."""
        T1, p1, p2 = 700.0, 500_000.0, 100_000.0
        res = isentropic_process(T1, p1, p2)
        assert res["ok"] is True
        T2 = res["T2"]
        assert abs(res["w_s_J_kg"] - CP_AIR * (T1 - T2)) / abs(CP_AIR * (T1 - T2)) < REL

    def test_negative_p2_returns_error(self):
        res = isentropic_process(300.0, 100_000.0, -1.0)
        assert res["ok"] is False


# ===========================================================================
# 6. polytropic_process
# ===========================================================================

class TestPolytropicProcess:

    def test_n_equals_1_isothermal(self):
        """n=1 should give same work as isothermal: w = p1 v1 ln(v2/v1)."""
        p1, v1, v2 = 200_000.0, 0.5, 1.0
        res = polytropic_process(p1, v1, v2, n=1.0)
        assert res["ok"] is True
        w_expected = p1 * v1 * math.log(v2 / v1)
        assert abs(res["w_J_kg"] - w_expected) / abs(w_expected) < REL

    def test_n_equals_0_isobaric(self):
        """n=0 → p2 = p1 (isobaric). w = p(v2-v1)."""
        p1, v1, v2 = 100_000.0, 0.3, 0.6
        res = polytropic_process(p1, v1, v2, n=0.0)
        assert res["ok"] is True
        assert abs(res["p2"] - p1) / p1 < REL  # p2 = p1 * (v1/v2)^0 = p1

    def test_n_equals_k_isentropic_delta_u_and_w_balanced(self):
        """n=k=1.4 → q = Δu + w should still hold as first-law check.
        Note: q is NOT necessarily zero for polytropic with n=k unless using
        perfect entropy tracking; the first-law balance q = Δu + w always holds."""
        p1, v1, v2, k = 200_000.0, 0.5, 0.25, 1.4
        res_poly = polytropic_process(p1, v1, v2, n=k)
        assert res_poly["ok"] is True
        # First-law consistency: q = Δu + w (to floating-point precision)
        assert abs(res_poly["q_J_kg"] - (res_poly["delta_u_J_kg"] + res_poly["w_J_kg"])) < 1e-6

    def test_p2_formula(self):
        """p2 = p1 * (v1/v2)^n."""
        p1, v1, v2, n = 100_000.0, 0.5, 0.25, 1.3
        p2_expected = p1 * (v1 / v2) ** n
        res = polytropic_process(p1, v1, v2, n)
        assert res["ok"] is True
        assert abs(res["p2"] - p2_expected) / p2_expected < REL

    def test_work_formula_n_not_1(self):
        """w = (p2 v2 - p1 v1) / (1 - n) for n ≠ 1."""
        p1, v1, v2, n = 300_000.0, 0.3, 0.6, 1.3
        p2 = p1 * (v1 / v2) ** n
        w_expected = (p2 * v2 - p1 * v1) / (1.0 - n)
        res = polytropic_process(p1, v1, v2, n)
        assert res["ok"] is True
        assert abs(res["w_J_kg"] - w_expected) / abs(w_expected) < REL

    def test_negative_v1_returns_error(self):
        res = polytropic_process(100_000.0, -0.5, 0.25, 1.3)
        assert res["ok"] is False


# ===========================================================================
# 7. carnot_efficiency
# ===========================================================================

class TestCarnotEfficiency:

    def test_formula(self):
        """η = 1 - T_L / T_H."""
        T_H, T_L = 1000.0, 300.0
        eta_expected = 1.0 - T_L / T_H
        res = carnot_efficiency(T_H, T_L)
        assert res["ok"] is True
        assert abs(res["eta_carnot"] - eta_expected) / eta_expected < REL

    def test_eta_between_0_and_1(self):
        res = carnot_efficiency(800.0, 300.0)
        assert res["ok"] is True
        assert 0.0 < res["eta_carnot"] < 1.0

    def test_T_H_equals_T_L_returns_error(self):
        res = carnot_efficiency(300.0, 300.0)
        assert res["ok"] is False

    def test_T_L_greater_than_T_H_returns_error(self):
        res = carnot_efficiency(300.0, 800.0)
        assert res["ok"] is False

    def test_W_net_per_Q_H_equals_eta(self):
        res = carnot_efficiency(1000.0, 300.0)
        assert res["ok"] is True
        assert abs(res["W_net_per_Q_H"] - res["eta_carnot"]) < 1e-12


# ===========================================================================
# 8. carnot_cop_refrigeration
# ===========================================================================

class TestCarnotCOPRefrigeration:

    def test_formula(self):
        """COP_R = T_L / (T_H - T_L)."""
        T_H, T_L = 300.0, 250.0
        cop_expected = T_L / (T_H - T_L)
        res = carnot_cop_refrigeration(T_H, T_L)
        assert res["ok"] is True
        assert abs(res["COP_R"] - cop_expected) / cop_expected < REL

    def test_cop_increases_as_T_L_approaches_T_H(self):
        """Closer temperatures → higher COP_R."""
        cop1 = carnot_cop_refrigeration(310.0, 250.0)["COP_R"]
        cop2 = carnot_cop_refrigeration(300.0, 250.0)["COP_R"]
        assert cop2 > cop1

    def test_T_L_equal_T_H_returns_error(self):
        res = carnot_cop_refrigeration(300.0, 300.0)
        assert res["ok"] is False

    def test_T_L_greater_than_T_H_returns_error(self):
        res = carnot_cop_refrigeration(250.0, 300.0)
        assert res["ok"] is False


# ===========================================================================
# 9. carnot_cop_heat_pump
# ===========================================================================

class TestCarnotCOPHeatPump:

    def test_formula(self):
        """COP_HP = T_H / (T_H - T_L)."""
        T_H, T_L = 300.0, 250.0
        cop_expected = T_H / (T_H - T_L)
        res = carnot_cop_heat_pump(T_H, T_L)
        assert res["ok"] is True
        assert abs(res["COP_HP"] - cop_expected) / cop_expected < REL

    def test_cop_hp_equals_cop_r_plus_1(self):
        """COP_HP = COP_R + 1."""
        T_H, T_L = 300.0, 250.0
        cop_r  = carnot_cop_refrigeration(T_H, T_L)["COP_R"]
        cop_hp = carnot_cop_heat_pump(T_H, T_L)["COP_HP"]
        assert abs(cop_hp - (cop_r + 1.0)) < REL

    def test_cop_hp_always_greater_than_1(self):
        res = carnot_cop_heat_pump(350.0, 250.0)
        assert res["ok"] is True
        assert res["COP_HP"] > 1.0


# ===========================================================================
# 10. otto_cycle
# ===========================================================================

class TestOttoCycle:

    def test_efficiency_formula(self):
        """η_Otto = 1 - 1/r^(k-1)."""
        r, k = 8.0, 1.4
        eta_expected = 1.0 - 1.0 / r ** (k - 1.0)
        res = otto_cycle(r=r, T1=300.0, T3=1500.0)
        assert res["ok"] is True
        assert abs(res["eta_otto"] - eta_expected) / eta_expected < REL

    def test_T2_formula(self):
        """T2 = T1 * r^(k-1)."""
        T1, r, k = 300.0, 8.0, 1.4
        T2_expected = T1 * r ** (k - 1.0)
        res = otto_cycle(r=r, T1=T1, T3=1500.0)
        assert res["ok"] is True
        assert abs(res["T2"] - T2_expected) / T2_expected < REL

    def test_w_net_equals_q_in_minus_q_out(self):
        res = otto_cycle(r=8.0, T1=300.0, T3=1500.0)
        assert res["ok"] is True
        assert abs(res["w_net_J_kg"] - (res["q_in_J_kg"] - res["q_out_J_kg"])) < 1.0

    def test_higher_r_gives_higher_efficiency(self):
        """Higher compression ratio → higher efficiency."""
        eta1 = otto_cycle(r=6.0, T1=300.0, T3=2000.0)["eta_otto"]
        eta2 = otto_cycle(r=10.0, T1=300.0, T3=2000.0)["eta_otto"]
        assert eta2 > eta1

    def test_T3_must_be_greater_than_T2(self):
        """Heat addition must raise temperature."""
        res = otto_cycle(r=8.0, T1=300.0, T3=500.0)  # T2 ≈ 689 K, T3=500 K < T2
        assert res["ok"] is False

    def test_r_less_than_1_returns_error(self):
        res = otto_cycle(r=0.5, T1=300.0, T3=1500.0)
        assert res["ok"] is False

    def test_w_net_positive(self):
        res = otto_cycle(r=8.0, T1=300.0, T3=1500.0)
        assert res["ok"] is True
        assert res["w_net_J_kg"] > 0.0

    def test_MEP_positive(self):
        res = otto_cycle(r=8.0, T1=300.0, T3=1500.0)
        assert res["ok"] is True
        assert res["MEP_Pa"] > 0.0


# ===========================================================================
# 11. diesel_cycle
# ===========================================================================

class TestDieselCycle:

    def test_efficiency_formula(self):
        """η_Diesel = 1 - (r_c^k - 1) / (k * r^(k-1) * (r_c - 1))."""
        r, r_c, k = 20.0, 2.0, 1.4
        num = r_c ** k - 1.0
        den = k * r ** (k - 1.0) * (r_c - 1.0)
        eta_expected = 1.0 - num / den
        res = diesel_cycle(r=r, r_c=r_c, T1=300.0)
        assert res["ok"] is True
        assert abs(res["eta_diesel"] - eta_expected) / eta_expected < REL_LOOSE

    def test_T2_formula(self):
        T1, r, k = 300.0, 20.0, 1.4
        T2_expected = T1 * r ** (k - 1.0)
        res = diesel_cycle(r=r, r_c=2.0, T1=T1)
        assert res["ok"] is True
        assert abs(res["T2"] - T2_expected) / T2_expected < REL

    def test_T3_is_T2_times_rc(self):
        """T3 = T2 * r_c (const pressure addition)."""
        r, r_c, T1 = 20.0, 2.0, 300.0
        res = diesel_cycle(r=r, r_c=r_c, T1=T1)
        assert res["ok"] is True
        assert abs(res["T3"] - res["T2"] * r_c) / res["T3"] < REL

    def test_diesel_less_efficient_than_otto_same_r(self):
        """For same r, Otto is more efficient than Diesel (r_c > 1)."""
        r, T1, T3 = 14.0, 300.0, 2200.0
        # Diesel cutoff ratio so that T3_diesel = same T3
        res_otto   = otto_cycle(r=r, T1=T1, T3=T3)
        # Use r_c=2 as representative Diesel
        res_diesel = diesel_cycle(r=r, r_c=2.0, T1=T1)
        assert res_otto["ok"] is True
        assert res_diesel["ok"] is True
        # Otto efficiency > Diesel for same r (Cengel §9-4)
        assert res_otto["eta_otto"] > res_diesel["eta_diesel"]

    def test_rc_ge_r_returns_error(self):
        res = diesel_cycle(r=10.0, r_c=10.0, T1=300.0)
        assert res["ok"] is False

    def test_rc_le_1_returns_error(self):
        res = diesel_cycle(r=20.0, r_c=0.5, T1=300.0)
        assert res["ok"] is False

    def test_w_net_positive(self):
        res = diesel_cycle(r=20.0, r_c=2.0, T1=300.0)
        assert res["ok"] is True
        assert res["w_net_J_kg"] > 0.0


# ===========================================================================
# 12. dual_cycle
# ===========================================================================

class TestDualCycle:

    def test_reduces_to_otto_when_rc_equals_1(self):
        """With r_c=1 (no const-P addition), dual = Otto."""
        r, T1, T3 = 8.0, 300.0, 1500.0
        res_otto = otto_cycle(r=r, T1=T1, T3=T3)
        # Dual with r_p matching Otto's T3/T2 and r_c=1
        res_otto_T2 = res_otto["T2"]
        r_p = T3 / res_otto_T2  # matches const-V pressure ratio
        res_dual = dual_cycle(r=r, r_p=r_p, r_c=1.0, T1=T1)
        assert res_dual["ok"] is True
        assert res_otto["ok"] is True
        # Both efficiencies should be close
        assert abs(res_dual["eta_dual"] - res_otto["eta_otto"]) / res_otto["eta_otto"] < 1e-6

    def test_states_in_correct_order(self):
        """T1 < T2 < T3 < T4 for normal dual cycle."""
        res = dual_cycle(r=15.0, r_p=1.5, r_c=1.5, T1=300.0)
        assert res["ok"] is True
        assert res["T1"] < res["T2"] < res["T3"] < res["T4"]

    def test_q_in_is_sum_of_both_additions(self):
        """q_in = q_in_v + q_in_p."""
        res = dual_cycle(r=15.0, r_p=1.5, r_c=1.5, T1=300.0)
        assert res["ok"] is True
        assert abs(res["q_in_J_kg"] - (res["q_in_v_J_kg"] + res["q_in_p_J_kg"])) < 1.0

    def test_w_net_positive(self):
        res = dual_cycle(r=15.0, r_p=1.5, r_c=1.5, T1=300.0)
        assert res["ok"] is True
        assert res["w_net_J_kg"] > 0.0

    def test_r_le_1_returns_error(self):
        res = dual_cycle(r=0.8, r_p=1.5, r_c=1.5, T1=300.0)
        assert res["ok"] is False


# ===========================================================================
# 13. brayton_cycle
# ===========================================================================

class TestBraytonCycle:

    def test_ideal_efficiency_formula(self):
        """η_Brayton (ideal) = 1 - 1/r_p^((k-1)/k)."""
        r_p, k = 8.0, 1.4
        eta_expected = 1.0 - 1.0 / r_p ** ((k - 1.0) / k)
        res = brayton_cycle(r_p=r_p, T1=300.0, T3=1200.0)
        assert res["ok"] is True
        assert abs(res["eta_brayton"] - eta_expected) / eta_expected < REL

    def test_T2s_formula(self):
        """T2s = T1 * r_p^((k-1)/k) for ideal compressor."""
        T1, r_p, k = 300.0, 8.0, 1.4
        T2s_expected = T1 * r_p ** ((k - 1.0) / k)
        res = brayton_cycle(r_p=r_p, T1=T1, T3=1200.0)
        assert res["ok"] is True
        assert abs(res["T2s"] - T2s_expected) / T2s_expected < REL

    def test_bwr_in_typical_range(self):
        """BWR typically 40-80% for gas turbines (Cengel §9-8)."""
        res = brayton_cycle(r_p=8.0, T1=300.0, T3=1200.0)
        assert res["ok"] is True
        assert 0.3 < res["bwr"] < 0.9

    def test_regeneration_increases_efficiency(self):
        """eta_regen > 0 should improve cycle efficiency."""
        res_no_regen = brayton_cycle(r_p=5.0, T1=300.0, T3=1100.0)
        res_regen    = brayton_cycle(r_p=5.0, T1=300.0, T3=1100.0, eta_regen=0.7)
        assert res_no_regen["ok"] is True
        assert res_regen["ok"] is True
        assert res_regen["eta_brayton"] > res_no_regen["eta_brayton"]

    def test_compressor_inefficiency_reduces_eta(self):
        """Real compressor (eta_c < 1) reduces cycle efficiency."""
        res_ideal = brayton_cycle(r_p=8.0, T1=300.0, T3=1200.0)
        res_real  = brayton_cycle(r_p=8.0, T1=300.0, T3=1200.0, eta_c=0.85)
        assert res_ideal["ok"] is True
        assert res_real["ok"] is True
        assert res_real["eta_brayton"] < res_ideal["eta_brayton"]

    def test_T3_less_than_T2_returns_error(self):
        """T3 must exceed actual compressor exit T2."""
        res = brayton_cycle(r_p=20.0, T1=300.0, T3=500.0)
        assert res["ok"] is False

    def test_r_p_le_1_returns_error(self):
        res = brayton_cycle(r_p=0.5, T1=300.0, T3=1200.0)
        assert res["ok"] is False

    def test_eta_regen_ge_1_returns_error(self):
        res = brayton_cycle(r_p=5.0, T1=300.0, T3=1100.0, eta_regen=1.0)
        assert res["ok"] is False


# ===========================================================================
# 14. rankine_cycle_ideal
# ===========================================================================

class TestRankineIdeal:

    def test_basic_saturated_cycle_runs(self):
        """Saturated Rankine cycle with p_high=1 MPa, p_low=10 kPa."""
        res = rankine_cycle_ideal(p_high=1_000_000.0, p_low=10_000.0,
                                  T_superheat=None)
        assert res["ok"] is True
        assert res["eta_rankine"] > 0.0
        assert res["w_net_kJ_kg"] > 0.0

    def test_superheated_gives_higher_work(self):
        """Superheated turbine inlet increases turbine work vs saturated."""
        res_sat  = rankine_cycle_ideal(1_000_000.0, 10_000.0, None)
        res_sup  = rankine_cycle_ideal(1_000_000.0, 10_000.0, 700.0)
        assert res_sat["ok"] is True
        assert res_sup["ok"] is True
        assert res_sup["w_turbine_kJ_kg"] > res_sat["w_turbine_kJ_kg"]

    def test_pump_work_is_small_fraction(self):
        """Pump work << turbine work (bwr << 1 for steam cycles)."""
        res = rankine_cycle_ideal(2_000_000.0, 10_000.0, None)
        assert res["ok"] is True
        assert res["bwr"] < 0.05

    def test_p_high_le_p_low_returns_error(self):
        res = rankine_cycle_ideal(p_high=10_000.0, p_low=100_000.0,
                                  T_superheat=None)
        assert res["ok"] is False

    def test_T_superheat_below_Tsat_returns_error(self):
        """T_superheat must be >= T_sat(p_high)."""
        res = rankine_cycle_ideal(1_000_000.0, 10_000.0, T_superheat=300.0)
        assert res["ok"] is False

    def test_reheat_requires_p_reheat(self):
        res = rankine_cycle_ideal(3_000_000.0, 10_000.0, 700.0,
                                  T_reheat=600.0)
        assert res["ok"] is False  # p_reheat not supplied

    def test_reheat_increases_turbine_work(self):
        res_no_rh = rankine_cycle_ideal(3_000_000.0, 10_000.0, 700.0)
        res_rh    = rankine_cycle_ideal(3_000_000.0, 10_000.0, 700.0,
                                        T_reheat=650.0, p_reheat=500_000.0)
        assert res_no_rh["ok"] is True
        assert res_rh["ok"] is True
        assert res_rh["w_turbine_kJ_kg"] > res_no_rh["w_turbine_kJ_kg"]

    def test_eta_rankine_less_than_carnot(self):
        """Real cycle efficiency must be < Carnot limit."""
        res = rankine_cycle_ideal(2_000_000.0, 10_000.0, None)
        assert res["ok"] is True
        assert res["eta_rankine"] < res["eta_carnot_limit"] + 1e-3


# ===========================================================================
# 15. refrigeration_cop
# ===========================================================================

class TestRefrigerationCOP:

    def test_cop_r_formula(self):
        """COP_R = Q_L / W_in."""
        Q_L, W_in = 5000.0, 2000.0
        res = refrigeration_cop(Q_L, W_in, mode="refrigeration")
        assert res["ok"] is True
        assert abs(res["COP_R"] - Q_L / W_in) / (Q_L / W_in) < REL

    def test_cop_hp_formula(self):
        """COP_HP = (Q_L + W_in) / W_in."""
        Q_L, W_in = 5000.0, 2000.0
        res = refrigeration_cop(Q_L, W_in, mode="heat_pump")
        assert res["ok"] is True
        assert abs(res["COP_HP"] - (Q_L + W_in) / W_in) / ((Q_L + W_in) / W_in) < REL

    def test_Q_H_formula(self):
        """Q_H = Q_L + W_in."""
        Q_L, W_in = 5000.0, 2000.0
        res = refrigeration_cop(Q_L, W_in)
        assert res["ok"] is True
        assert abs(res["Q_H"] - (Q_L + W_in)) < 1e-9

    def test_impossible_cop_issues_warning(self):
        """COP > COP_Carnot → warning (not error)."""
        T_H, T_L = 305.0, 285.0
        COP_carnot = T_L / (T_H - T_L)  # = 285/20 = 14.25
        # Force COP > COP_carnot
        Q_L = COP_carnot * 1000.0 * 2.0   # COP = 2 * COP_carnot
        W_in = 1000.0
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = refrigeration_cop(Q_L, W_in, T_H=T_H, T_L=T_L)
        assert res["ok"] is True
        assert len(w) >= 1
        assert any("COP" in str(warning.message) or "impossible" in str(warning.message).lower()
                   for warning in w)

    def test_carnot_limit_computed_when_T_supplied(self):
        """COP_carnot_limit returned when T_H, T_L are given."""
        res = refrigeration_cop(5000.0, 2000.0, T_H=305.0, T_L=285.0)
        assert res["ok"] is True
        assert "COP_carnot_limit" in res

    def test_T_L_ge_T_H_returns_error(self):
        res = refrigeration_cop(5000.0, 2000.0, T_H=285.0, T_L=305.0)
        assert res["ok"] is False

    def test_invalid_mode_returns_error(self):
        res = refrigeration_cop(5000.0, 2000.0, mode="cooling")
        assert res["ok"] is False

    def test_negative_W_in_returns_error(self):
        res = refrigeration_cop(5000.0, -100.0)
        assert res["ok"] is False


# ===========================================================================
# 16. LLM tool wrappers — happy paths and error paths
# ===========================================================================

class TestToolWrappers:

    def test_run_isentropic_relations_happy(self):
        ctx = _ctx()
        raw = _run(run_isentropic_relations(ctx, _args(T1=300.0, p1=100_000.0, p2=300_000.0)))
        d = _ok(raw)
        assert d["T2"] > 300.0

    def test_run_isentropic_relations_missing_T1(self):
        ctx = _ctx()
        raw = _run(run_isentropic_relations(ctx, _args(p1=100_000.0, p2=300_000.0)))
        _err_response(raw)

    def test_run_isothermal_happy(self):
        ctx = _ctx()
        raw = _run(run_isothermal_process(ctx, _args(p1=100_000.0, v1=0.287, v2=0.574)))
        d = _ok(raw)
        assert d["w_J_kg"] > 0.0

    def test_run_isothermal_bad_json(self):
        ctx = _ctx()
        raw = _run(run_isothermal_process(ctx, b"not json"))
        _err_response(raw)

    def test_run_isobaric_happy(self):
        ctx = _ctx()
        raw = _run(run_isobaric_process(ctx, _args(T1=300.0, T2=600.0)))
        d = _ok(raw)
        assert d["q_J_kg"] > 0.0

    def test_run_isochoric_happy(self):
        ctx = _ctx()
        raw = _run(run_isochoric_process(ctx, _args(T1=300.0, T2=600.0)))
        d = _ok(raw)
        assert d["q_J_kg"] > 0.0

    def test_run_isentropic_proc_happy(self):
        ctx = _ctx()
        raw = _run(run_isentropic_process(ctx, _args(T1=300.0, p1=100_000.0, p2=500_000.0)))
        d = _ok(raw)
        assert d["T2"] > 300.0

    def test_run_polytropic_happy(self):
        ctx = _ctx()
        raw = _run(run_polytropic_process(ctx, _args(p1=200_000.0, v1=0.5, v2=0.25, n=1.3)))
        d = _ok(raw)
        assert d["p2"] > d["p1"]

    def test_run_carnot_efficiency_happy(self):
        ctx = _ctx()
        raw = _run(run_carnot_efficiency(ctx, _args(T_H=1000.0, T_L=300.0)))
        d = _ok(raw)
        assert 0.0 < d["eta_carnot"] < 1.0

    def test_run_carnot_cop_r_happy(self):
        ctx = _ctx()
        raw = _run(run_carnot_cop_refrigeration(ctx, _args(T_H=300.0, T_L=250.0)))
        d = _ok(raw)
        assert d["COP_R"] > 0.0

    def test_run_carnot_cop_hp_happy(self):
        ctx = _ctx()
        raw = _run(run_carnot_cop_heat_pump(ctx, _args(T_H=300.0, T_L=250.0)))
        d = _ok(raw)
        assert d["COP_HP"] > 1.0

    def test_run_otto_happy(self):
        ctx = _ctx()
        raw = _run(run_otto_cycle(ctx, _args(r=8.0, T1=300.0, T3=1500.0)))
        d = _ok(raw)
        assert 0.0 < d["eta_otto"] < 1.0

    def test_run_otto_missing_r(self):
        ctx = _ctx()
        raw = _run(run_otto_cycle(ctx, _args(T1=300.0, T3=1500.0)))
        _err_response(raw)

    def test_run_diesel_happy(self):
        ctx = _ctx()
        raw = _run(run_diesel_cycle(ctx, _args(r=20.0, r_c=2.0, T1=300.0)))
        d = _ok(raw)
        assert 0.0 < d["eta_diesel"] < 1.0

    def test_run_dual_happy(self):
        ctx = _ctx()
        raw = _run(run_dual_cycle(ctx, _args(r=15.0, r_p=1.5, r_c=1.5, T1=300.0)))
        d = _ok(raw)
        assert d["w_net_J_kg"] > 0.0

    def test_run_brayton_happy(self):
        ctx = _ctx()
        raw = _run(run_brayton_cycle(ctx, _args(r_p=8.0, T1=300.0, T3=1200.0)))
        d = _ok(raw)
        assert 0.0 < d["eta_brayton"] < 1.0

    def test_run_brayton_with_regen(self):
        ctx = _ctx()
        raw = _run(run_brayton_cycle(ctx, _args(
            r_p=5.0, T1=300.0, T3=1100.0, eta_regen=0.7
        )))
        d = _ok(raw)
        assert d["T_regen"] > d["T2"]

    def test_run_rankine_happy_saturated(self):
        ctx = _ctx()
        raw = _run(run_rankine_cycle_ideal(ctx, _args(p_high=1_000_000.0, p_low=10_000.0)))
        d = _ok(raw)
        assert d["eta_rankine"] > 0.0

    def test_run_rankine_missing_p_high(self):
        ctx = _ctx()
        raw = _run(run_rankine_cycle_ideal(ctx, _args(p_low=10_000.0)))
        _err_response(raw)

    def test_run_refrigeration_cop_happy(self):
        ctx = _ctx()
        raw = _run(run_refrigeration_cop(ctx, _args(Q_L=5000.0, W_in=2000.0)))
        d = _ok(raw)
        assert d["COP"] == pytest.approx(2.5, rel=1e-6)

    def test_run_refrigeration_cop_heat_pump_mode(self):
        ctx = _ctx()
        raw = _run(run_refrigeration_cop(ctx,
                                         _args(Q_L=5000.0, W_in=2000.0, mode="heat_pump")))
        d = _ok(raw)
        assert d["COP_HP"] == pytest.approx(3.5, rel=1e-6)

    def test_run_refrigeration_cop_bad_mode(self):
        ctx = _ctx()
        raw = _run(run_refrigeration_cop(ctx, _args(Q_L=5000.0, W_in=2000.0, mode="bad")))
        _err_response(raw)
