"""
Hermetic tests for kerf_cad_core.heatxfer — general heat-transfer engineering.

Coverage:
  transfer.composite_wall          — series resistance, contact layers
  transfer.cylindrical_shell       — radial conduction
  transfer.spherical_shell         — radial conduction
  transfer.nusselt_flat_plate      — laminar / turbulent / mixed regimes
  transfer.nusselt_pipe_dittus_boelter — turbulent pipe, heating/cooling
  transfer.nusselt_pipe_laminar    — Hausen laminar entry-length
  transfer.nusselt_cylinder_churchill_bernstein — external cylinder
  transfer.nusselt_natural_vertical_plate — Churchill-Chu natural convection
  transfer.radiation_two_surface   — two-surface gray radiation
  transfer.fin_efficiency_straight — rectangular fin η, ε
  transfer.fin_efficiency_pin      — pin fin η, ε
  transfer.fin_array_resistance    — fin array R
  transfer.lmtd_heat_exchanger     — LMTD counter/parallel
  transfer.effectiveness_ntu       — ε-NTU counter/parallel/crossflow
  transfer.lumped_capacitance      — transient Biot check + T(t)
  tools.*                          — LLM wrapper happy paths + error paths

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against Incropera, 7th ed. hand-calculations.

References
----------
Incropera, F.P. et al., "Fundamentals of Heat and Mass Transfer", 7th ed.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
import warnings

import pytest

from kerf_cad_core.heatxfer.transfer import (
    composite_wall,
    cylindrical_shell,
    spherical_shell,
    nusselt_flat_plate,
    nusselt_pipe_dittus_boelter,
    nusselt_pipe_laminar,
    nusselt_cylinder_churchill_bernstein,
    nusselt_natural_vertical_plate,
    radiation_two_surface,
    fin_efficiency_straight,
    fin_efficiency_pin,
    fin_array_resistance,
    lmtd_heat_exchanger,
    effectiveness_ntu,
    lumped_capacitance,
)
from kerf_cad_core.heatxfer.tools import (
    run_composite_wall,
    run_cylindrical_shell,
    run_spherical_shell,
    run_nusselt_flat_plate,
    run_nusselt_pipe_dittus,
    run_nusselt_pipe_laminar,
    run_nusselt_cylinder_cb,
    run_nusselt_natural_vplate,
    run_radiation_two_surface,
    run_fin_straight,
    run_fin_pin,
    run_fin_array_resistance,
    run_lmtd,
    run_effectiveness_ntu,
    run_lumped_capacitance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIGMA = 5.670374419e-8  # Stefan-Boltzmann (W m⁻² K⁻⁴)
REL = 1e-6  # relative tolerance for floating-point checks


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
# 1. composite_wall
# ===========================================================================

class TestCompositeWall:

    def test_single_material_layer(self):
        """Single slab: R = t/(kA), Q = ΔT/R."""
        k, t, T_hot, T_cold = 1.0, 0.1, 400.0, 300.0
        res = composite_wall([{"k": k, "t": t}], T_hot, T_cold)
        assert res["ok"] is True
        R_expected = t / (k * 1.0)
        Q_expected = (T_hot - T_cold) / R_expected
        assert abs(res["Q_W"] - Q_expected) / abs(Q_expected) < REL
        assert abs(res["R_total"] - R_expected) / R_expected < REL

    def test_two_material_layers_series(self):
        """Two layers in series: R_total = R1 + R2."""
        layers = [{"k": 2.0, "t": 0.05}, {"k": 0.5, "t": 0.1}]
        res = composite_wall(layers, 500.0, 300.0)
        assert res["ok"] is True
        R1 = 0.05 / 2.0
        R2 = 0.1 / 0.5
        R_total = R1 + R2
        Q_expected = 200.0 / R_total
        assert abs(res["Q_W"] - Q_expected) / abs(Q_expected) < REL

    def test_contact_resistance_layer(self):
        """Contact resistance layer: R = R_contact / A."""
        layers = [
            {"k": 50.0, "t": 0.01},
            {"R_contact": 1e-4},
            {"k": 50.0, "t": 0.01},
        ]
        res = composite_wall(layers, 400.0, 300.0)
        assert res["ok"] is True
        assert len(res["layer_resistances"]) == 3
        R_contact = 1e-4 / 1.0
        assert abs(res["layer_resistances"][1] - R_contact) / R_contact < REL

    def test_interface_temperatures_count(self):
        """Three layers → two interface temperatures."""
        layers = [{"k": 1.0, "t": 0.1}, {"k": 2.0, "t": 0.2}, {"k": 0.5, "t": 0.05}]
        res = composite_wall(layers, 600.0, 300.0)
        assert res["ok"] is True
        assert len(res["T_interfaces"]) == 2

    def test_interface_temperature_value(self):
        """For two equal-k, equal-t layers: interface T is exactly midpoint ΔT."""
        layers = [{"k": 1.0, "t": 0.1}, {"k": 1.0, "t": 0.1}]
        res = composite_wall(layers, 400.0, 300.0)
        assert res["ok"] is True
        # Both layers same R, so interface T = (T_hot + T_cold)/2
        assert abs(res["T_interfaces"][0] - 350.0) < 1e-9

    def test_empty_layers_returns_error(self):
        res = composite_wall([], 400.0, 300.0)
        assert res["ok"] is False

    def test_missing_k_returns_error(self):
        res = composite_wall([{"t": 0.1}], 400.0, 300.0)
        assert res["ok"] is False

    def test_negative_k_returns_error(self):
        res = composite_wall([{"k": -1.0, "t": 0.1}], 400.0, 300.0)
        assert res["ok"] is False


# ===========================================================================
# 2. cylindrical_shell
# ===========================================================================

class TestCylindricalShell:

    def test_formula_check(self):
        """Q = 2π k L (T_i - T_o) / ln(r_o/r_i)."""
        ri, ro, k, Ti, To, L = 0.05, 0.10, 50.0, 500.0, 300.0, 1.0
        res = cylindrical_shell(ri, ro, k, Ti, To, L)
        assert res["ok"] is True
        ln_r = math.log(ro / ri)
        Q_expected = 2.0 * math.pi * k * L * (Ti - To) / ln_r
        assert abs(res["Q_W"] - Q_expected) / abs(Q_expected) < REL

    def test_q_per_m_equals_Q_over_L(self):
        """q_per_m = Q / L."""
        res = cylindrical_shell(0.05, 0.10, 50.0, 500.0, 300.0, L=2.5)
        assert res["ok"] is True
        assert abs(res["q_per_m"] - res["Q_W"] / 2.5) / abs(res["q_per_m"]) < REL

    def test_r_outer_le_r_inner_returns_error(self):
        res = cylindrical_shell(0.10, 0.05, 50.0, 500.0, 300.0)
        assert res["ok"] is False

    def test_negative_k_returns_error(self):
        res = cylindrical_shell(0.05, 0.10, -1.0, 500.0, 300.0)
        assert res["ok"] is False

    def test_default_length_is_1m(self):
        """Default L=1 should give q_per_m = Q_W."""
        res = cylindrical_shell(0.05, 0.10, 50.0, 400.0, 300.0)
        assert res["ok"] is True
        assert abs(res["q_per_m"] - res["Q_W"]) < 1e-9


# ===========================================================================
# 3. spherical_shell
# ===========================================================================

class TestSphericalShell:

    def test_formula_check(self):
        """Q = 4π k r_i r_o (T_i - T_o) / (r_o - r_i)."""
        ri, ro, k, Ti, To = 0.05, 0.10, 10.0, 500.0, 300.0
        res = spherical_shell(ri, ro, k, Ti, To)
        assert res["ok"] is True
        Q_expected = 4.0 * math.pi * k * ri * ro * (Ti - To) / (ro - ri)
        assert abs(res["Q_W"] - Q_expected) / abs(Q_expected) < REL

    def test_r_outer_le_r_inner_returns_error(self):
        res = spherical_shell(0.1, 0.05, 10.0, 500.0, 300.0)
        assert res["ok"] is False

    def test_resistance_formula(self):
        """R = (r_o - r_i) / (4π k r_i r_o)."""
        ri, ro, k = 0.03, 0.07, 15.0
        res = spherical_shell(ri, ro, k, 400.0, 300.0)
        assert res["ok"] is True
        R_expected = (ro - ri) / (4.0 * math.pi * k * ri * ro)
        assert abs(res["R_cond"] - R_expected) / R_expected < REL


# ===========================================================================
# 4. nusselt_flat_plate
# ===========================================================================

class TestNusseltFlatPlate:

    def test_laminar_formula(self):
        """Nu_lam = 0.664 Re^0.5 Pr^(1/3) for Re=1e5, Pr=0.71."""
        Re, Pr = 1e5, 0.71
        res = nusselt_flat_plate(Re, Pr, regime="laminar")
        assert res["ok"] is True
        Nu_expected = 0.664 * Re ** 0.5 * Pr ** (1.0 / 3.0)
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_turbulent_formula(self):
        """Nu_turb = 0.037 Re^(4/5) Pr^(1/3) for Re=1e6."""
        Re, Pr = 1e6, 0.71
        res = nusselt_flat_plate(Re, Pr, regime="turbulent")
        assert res["ok"] is True
        Nu_expected = 0.037 * Re ** (4.0 / 5.0) * Pr ** (1.0 / 3.0)
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_mixed_formula(self):
        """Nu_mixed = (0.037 Re^(4/5) - 871) Pr^(1/3) for Re=5e6."""
        Re, Pr = 5e6, 0.71
        res = nusselt_flat_plate(Re, Pr, regime="mixed")
        assert res["ok"] is True
        Nu_expected = (0.037 * Re ** (4.0 / 5.0) - 871.0) * Pr ** (1.0 / 3.0)
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_auto_selects_laminar_for_low_Re(self):
        res = nusselt_flat_plate(1e5, 0.71, regime="auto")
        assert res["ok"] is True
        assert res["regime"] == "laminar"

    def test_auto_selects_mixed_for_high_Re(self):
        res = nusselt_flat_plate(1e7, 0.71, regime="auto")
        assert res["ok"] is True
        assert res["regime"] == "mixed"

    def test_unknown_regime_returns_error(self):
        res = nusselt_flat_plate(1e5, 0.71, regime="supersonic")
        assert res["ok"] is False

    def test_invalid_Re_returns_error(self):
        res = nusselt_flat_plate(-100.0, 0.71)
        assert res["ok"] is False


# ===========================================================================
# 5. nusselt_pipe_dittus_boelter
# ===========================================================================

class TestNusseltPipeDittusBoelter:

    def test_heating_n04(self):
        """Nu = 0.023 Re^0.8 Pr^0.4 for heating."""
        Re, Pr = 50000.0, 0.71
        res = nusselt_pipe_dittus_boelter(Re, Pr, heating=True)
        assert res["ok"] is True
        Nu_expected = 0.023 * Re ** 0.8 * Pr ** 0.4
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL
        assert res["n"] == 0.4

    def test_cooling_n03(self):
        """Nu = 0.023 Re^0.8 Pr^0.3 for cooling."""
        Re, Pr = 50000.0, 5.0
        res = nusselt_pipe_dittus_boelter(Re, Pr, heating=False)
        assert res["ok"] is True
        Nu_expected = 0.023 * Re ** 0.8 * Pr ** 0.3
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL
        assert res["n"] == 0.3

    def test_invalid_Re_returns_error(self):
        res = nusselt_pipe_dittus_boelter(-1.0, 0.71)
        assert res["ok"] is False

    def test_heating_gives_higher_Nu_than_cooling(self):
        """Higher exponent on Pr for heating (0.4 > 0.3) → larger Nu when Pr > 1."""
        Re, Pr = 30000.0, 5.0
        Nu_h = nusselt_pipe_dittus_boelter(Re, Pr, heating=True)["Nu"]
        Nu_c = nusselt_pipe_dittus_boelter(Re, Pr, heating=False)["Nu"]
        assert Nu_h > Nu_c


# ===========================================================================
# 6. nusselt_pipe_laminar
# ===========================================================================

class TestNusseltPipeLaminar:

    def test_fully_developed_limit(self):
        """For very large L/D (large Gz denominator), Nu → 3.66 asymptote."""
        # With large L_D, Gz = Re·Pr/L_D → 0, Nu → 3.66
        res = nusselt_pipe_laminar(Re_D=500.0, Pr=7.0, L_D=10000.0)
        assert res["ok"] is True
        assert abs(res["Nu"] - 3.66) < 0.05  # within 5% of 3.66

    def test_hausen_formula_check(self):
        """Verify Hausen formula at a specific point."""
        Re, Pr, LD = 1000.0, 5.0, 50.0
        Gz = (1.0 / LD) * Re * Pr
        Nu_expected = 3.66 + 0.065 * Gz / (1.0 + 0.04 * Gz ** (2.0 / 3.0))
        res = nusselt_pipe_laminar(Re, Pr, LD)
        assert res["ok"] is True
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_graetz_number_correct(self):
        """Gz = (D/L) Re Pr = Re Pr / (L/D)."""
        Re, Pr, LD = 800.0, 4.0, 20.0
        res = nusselt_pipe_laminar(Re, Pr, LD)
        assert res["ok"] is True
        Gz_expected = Re * Pr / LD
        assert abs(res["Gz"] - Gz_expected) / Gz_expected < REL

    def test_negative_Re_returns_error(self):
        res = nusselt_pipe_laminar(-100.0, 5.0, 50.0)
        assert res["ok"] is False


# ===========================================================================
# 7. nusselt_cylinder_churchill_bernstein
# ===========================================================================

class TestNusseltCylinderChurchillBernstein:

    def test_formula_known_value(self):
        """Verify against known Incropera example (Re=4000, Pr=0.71 air)."""
        Re, Pr = 4000.0, 0.71
        term1 = 0.62 * Re ** 0.5 * Pr ** (1.0 / 3.0)
        denom = (1.0 + (0.4 / Pr) ** (2.0 / 3.0)) ** 0.25
        bracket = 1.0 + (Re / 282000.0) ** (5.0 / 8.0)
        Nu_expected = 0.3 + (term1 / denom) * bracket ** (4.0 / 5.0)
        res = nusselt_cylinder_churchill_bernstein(Re, Pr)
        assert res["ok"] is True
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_increases_with_Re(self):
        """Nu should increase with increasing Re (larger velocity → more convection)."""
        Pr = 0.71
        Nu1 = nusselt_cylinder_churchill_bernstein(1e3, Pr)["Nu"]
        Nu2 = nusselt_cylinder_churchill_bernstein(1e5, Pr)["Nu"]
        assert Nu2 > Nu1

    def test_invalid_Pr_returns_error(self):
        res = nusselt_cylinder_churchill_bernstein(1e4, -1.0)
        assert res["ok"] is False


# ===========================================================================
# 8. nusselt_natural_vertical_plate
# ===========================================================================

class TestNusseltNaturalVerticalPlate:

    def test_laminar_formula_check(self):
        """Verify laminar Churchill-Chu formula at Ra=1e6, Pr=0.71."""
        Ra, Pr = 1e6, 0.71
        psi = (1.0 + (0.492 / Pr) ** (9.0 / 16.0))
        Nu_expected = 0.68 + 0.670 * Ra ** 0.25 / psi ** (4.0 / 9.0)
        res = nusselt_natural_vertical_plate(Ra, Pr, regime="laminar")
        assert res["ok"] is True
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_all_formula_check(self):
        """Verify composite Churchill-Chu formula at Ra=1e8, Pr=0.71."""
        Ra, Pr = 1e8, 0.71
        psi = (1.0 + (0.492 / Pr) ** (9.0 / 16.0))
        Nu_sqrt = 0.825 + 0.387 * Ra ** (1.0 / 6.0) / psi ** (8.0 / 27.0)
        Nu_expected = Nu_sqrt ** 2
        res = nusselt_natural_vertical_plate(Ra, Pr, regime="all")
        assert res["ok"] is True
        assert abs(res["Nu"] - Nu_expected) / Nu_expected < REL

    def test_nu_increases_with_Ra(self):
        """Larger Ra (stronger buoyancy) → larger Nu."""
        Pr = 0.71
        Nu1 = nusselt_natural_vertical_plate(1e4, Pr)["Nu"]
        Nu2 = nusselt_natural_vertical_plate(1e8, Pr)["Nu"]
        assert Nu2 > Nu1

    def test_unknown_regime_returns_error(self):
        res = nusselt_natural_vertical_plate(1e6, 0.71, regime="turbulent")
        assert res["ok"] is False


# ===========================================================================
# 9. radiation_two_surface
# ===========================================================================

class TestRadiationTwoSurface:

    def test_blackbody_surfaces(self):
        """Blackbody (eps=1): R_surf=0, Q = A1 F12 σ (T1^4 - T2^4)."""
        T1, T2 = 1000.0, 500.0
        A1, A2, F12 = 1.0, 1.0, 1.0
        res = radiation_two_surface(T1, T2, 1.0, 1.0, A1, A2, F12)
        assert res["ok"] is True
        Q_expected = A1 * F12 * _SIGMA * (T1 ** 4 - T2 ** 4)
        assert abs(res["Q_12_W"] - Q_expected) / abs(Q_expected) < REL

    def test_direction_of_heat_transfer(self):
        """Q > 0 when T1 > T2 (net from 1 to 2)."""
        res = radiation_two_surface(800.0, 400.0, 0.8, 0.8, 1.0, 1.0, 1.0)
        assert res["ok"] is True
        assert res["Q_12_W"] > 0.0

    def test_zero_view_factor(self):
        """F12=0 → Q=0."""
        res = radiation_two_surface(1000.0, 300.0, 0.9, 0.9, 1.0, 1.0, 0.0)
        assert res["ok"] is True
        assert res["Q_12_W"] == 0.0

    def test_emissivity_zero_returns_error(self):
        res = radiation_two_surface(800.0, 400.0, 0.0, 0.8, 1.0, 1.0, 1.0)
        assert res["ok"] is False

    def test_blackbody_emissive_power(self):
        """Eb = σ T^4."""
        T1, T2 = 600.0, 400.0
        res = radiation_two_surface(T1, T2, 0.8, 0.8, 1.0, 1.0, 1.0)
        assert res["ok"] is True
        assert abs(res["Eb1_Wm2"] - _SIGMA * T1 ** 4) / (_SIGMA * T1 ** 4) < REL
        assert abs(res["Eb2_Wm2"] - _SIGMA * T2 ** 4) / (_SIGMA * T2 ** 4) < REL

    def test_negative_T1_returns_error(self):
        res = radiation_two_surface(-100.0, 400.0, 0.8, 0.8, 1.0, 1.0, 1.0)
        assert res["ok"] is False


# ===========================================================================
# 10. fin_efficiency_straight
# ===========================================================================

class TestFinEfficiencyStraight:

    def test_adiabatic_formula(self):
        """η_f = tanh(mL) / (mL)  for adiabatic tip."""
        L, t, k, h = 0.05, 0.002, 200.0, 50.0
        m = math.sqrt(2.0 * h / (k * t))
        mL = m * L
        eta_expected = math.tanh(mL) / mL
        res = fin_efficiency_straight(L, t, k, h, tip="adiabatic")
        assert res["ok"] is True
        assert abs(res["eta_f"] - eta_expected) / eta_expected < REL

    def test_convective_tip_uses_corrected_length(self):
        """Convective tip: L_c = L + t/2."""
        L, t, k, h = 0.05, 0.004, 200.0, 50.0
        res = fin_efficiency_straight(L, t, k, h, tip="convective")
        assert res["ok"] is True
        assert abs(res["L_c"] - (L + t / 2.0)) / (L + t / 2.0) < REL

    def test_efficiency_between_0_and_1(self):
        res = fin_efficiency_straight(0.05, 0.002, 50.0, 100.0)
        assert res["ok"] is True
        assert 0.0 < res["eta_f"] <= 1.0

    def test_high_k_approaches_eta_1(self):
        """Very high k → m → 0 → η_f → 1."""
        res = fin_efficiency_straight(0.05, 0.002, 1e9, 50.0)
        assert res["ok"] is True
        assert abs(res["eta_f"] - 1.0) < 1e-4

    def test_effectiveness_formula(self):
        """ε_f = η_f × 2 L_c / t."""
        L, t, k, h = 0.05, 0.002, 200.0, 50.0
        res = fin_efficiency_straight(L, t, k, h)
        assert res["ok"] is True
        eps_expected = res["eta_f"] * 2.0 * res["L_c"] / t
        assert abs(res["eps_f"] - eps_expected) / eps_expected < REL

    def test_invalid_tip_returns_error(self):
        res = fin_efficiency_straight(0.05, 0.002, 200.0, 50.0, tip="rounded")
        assert res["ok"] is False


# ===========================================================================
# 11. fin_efficiency_pin
# ===========================================================================

class TestFinEfficiencyPin:

    def test_pin_fin_formula(self):
        """η_f = tanh(mL_c)/(mL_c), m=sqrt(4h/(kD)), L_c=L+D/4."""
        L, D, k, h = 0.05, 0.004, 200.0, 50.0
        L_c = L + D / 4.0
        m = math.sqrt(4.0 * h / (k * D))
        mLc = m * L_c
        eta_expected = math.tanh(mLc) / mLc
        res = fin_efficiency_pin(L, D, k, h)
        assert res["ok"] is True
        assert abs(res["eta_f"] - eta_expected) / eta_expected < REL

    def test_effectiveness_formula(self):
        """ε_f = η_f × 4 L_c / D."""
        L, D, k, h = 0.05, 0.004, 200.0, 50.0
        res = fin_efficiency_pin(L, D, k, h)
        assert res["ok"] is True
        eps_expected = res["eta_f"] * 4.0 * res["L_c"] / D
        assert abs(res["eps_f"] - eps_expected) / eps_expected < REL

    def test_efficiency_between_0_and_1(self):
        res = fin_efficiency_pin(0.05, 0.004, 100.0, 200.0)
        assert res["ok"] is True
        assert 0.0 < res["eta_f"] <= 1.0

    def test_negative_D_returns_error(self):
        res = fin_efficiency_pin(0.05, -0.004, 200.0, 50.0)
        assert res["ok"] is False


# ===========================================================================
# 12. fin_array_resistance
# ===========================================================================

class TestFinArrayResistance:

    def test_formula_check(self):
        """η_overall = 1 - N A_fin/A_tot (1-η_f), R = 1/(η_ov h A_tot)."""
        N, eta_f, A_fin, A_base, h, A_total = 10, 0.8, 0.01, 0.005, 50.0, 0.105
        eta_overall_expected = 1.0 - (N * A_fin / A_total) * (1.0 - eta_f)
        R_expected = 1.0 / (eta_overall_expected * h * A_total)
        res = fin_array_resistance(N, eta_f, A_fin, A_base, h, A_total)
        assert res["ok"] is True
        assert abs(res["R_array"] - R_expected) / R_expected < REL
        assert abs(res["eta_overall"] - eta_overall_expected) / eta_overall_expected < REL

    def test_perfect_fins_reduces_to_bare_surface(self):
        """η_f = 1 → η_overall = 1 → R = 1/(h A_total)."""
        N, h, A_fin, A_base, A_total = 5, 100.0, 0.02, 0.01, 0.11
        res = fin_array_resistance(N, 1.0, A_fin, A_base, h, A_total)
        assert res["ok"] is True
        assert abs(res["eta_overall"] - 1.0) < 1e-9
        assert abs(res["R_array"] - 1.0 / (h * A_total)) / (1.0 / (h * A_total)) < REL

    def test_invalid_eta_f_returns_error(self):
        res = fin_array_resistance(10, -0.1, 0.01, 0.005, 50.0, 0.1)
        assert res["ok"] is False

    def test_invalid_N_returns_error(self):
        res = fin_array_resistance(0, 0.8, 0.01, 0.005, 50.0, 0.1)
        assert res["ok"] is False


# ===========================================================================
# 13. lmtd_heat_exchanger
# ===========================================================================

class TestLMTDHeatExchanger:

    def test_counter_flow_lmtd(self):
        """Counter-flow LMTD: ΔT1=T_h_in-T_c_out, ΔT2=T_h_out-T_c_in."""
        T_h_in, T_h_out = 380.0, 320.0
        T_c_in, T_c_out = 290.0, 340.0
        U, A = 500.0, 2.0
        dT1 = T_h_in - T_c_out   # 380 - 340 = 40
        dT2 = T_h_out - T_c_in   # 320 - 290 = 30
        LMTD_expected = (dT1 - dT2) / math.log(dT1 / dT2)
        Q_expected = U * A * LMTD_expected
        res = lmtd_heat_exchanger(T_h_in, T_h_out, T_c_in, T_c_out, U, A, flow="counter")
        assert res["ok"] is True
        assert abs(res["LMTD_K"] - LMTD_expected) / LMTD_expected < REL
        assert abs(res["Q_W"] - Q_expected) / Q_expected < REL

    def test_parallel_flow_lmtd(self):
        """Parallel-flow LMTD: ΔT1=T_h_in-T_c_in, ΔT2=T_h_out-T_c_out."""
        T_h_in, T_h_out = 380.0, 340.0
        T_c_in, T_c_out = 290.0, 320.0
        U, A = 500.0, 2.0
        dT1 = T_h_in - T_c_in   # 380 - 290 = 90
        dT2 = T_h_out - T_c_out  # 340 - 320 = 20
        LMTD_expected = (dT1 - dT2) / math.log(dT1 / dT2)
        res = lmtd_heat_exchanger(T_h_in, T_h_out, T_c_in, T_c_out, U, A, flow="parallel")
        assert res["ok"] is True
        assert abs(res["LMTD_K"] - LMTD_expected) / LMTD_expected < REL

    def test_equal_delta_T_uses_exact_lmtd(self):
        """When ΔT1 == ΔT2, LMTD = ΔT."""
        T_h_in, T_h_out = 400.0, 350.0
        T_c_in, T_c_out = 300.0, 350.0
        # counter: dT1 = 400-350=50, dT2=350-300=50
        res = lmtd_heat_exchanger(T_h_in, T_h_out, T_c_in, T_c_out, 200.0, 1.0, flow="counter")
        assert res["ok"] is True
        assert abs(res["LMTD_K"] - 50.0) < 1e-9

    def test_counter_flow_more_effective_than_parallel(self):
        """Counter-flow LMTD > parallel-flow LMTD for same duty, same flow rates.

        Both arrangements with feasible temperatures — counter-flow achieves
        higher cold-side outlet (more heat recovery) for the same LMTD area.
        We simply verify both calls succeed and counter-flow LMTD is higher
        with temperatures that produce positive ΔT on both ends.
        """
        U, A = 300.0, 1.5
        # Counter-flow: ΔT1=380-340=40, ΔT2=320-290=30 → LMTD≈34.7
        res_cf = lmtd_heat_exchanger(380.0, 320.0, 290.0, 340.0, U, A, flow="counter")
        # Parallel-flow: ΔT1=380-290=90, ΔT2=320-330 → infeasible; use different outlet
        # Parallel with T_c_out=315 (< T_h_out=320): ΔT1=380-290=90, ΔT2=320-315=5 → LMTD≈29.5
        res_par = lmtd_heat_exchanger(380.0, 320.0, 290.0, 315.0, U, A, flow="parallel")
        assert res_cf["ok"] is True
        assert res_par["ok"] is True
        assert res_cf["LMTD_K"] > res_par["LMTD_K"]

    def test_unknown_flow_returns_error(self):
        res = lmtd_heat_exchanger(380.0, 320.0, 290.0, 340.0, 500.0, 2.0, flow="spiral")
        assert res["ok"] is False

    def test_invalid_U_returns_error(self):
        res = lmtd_heat_exchanger(380.0, 320.0, 290.0, 340.0, -500.0, 2.0)
        assert res["ok"] is False


# ===========================================================================
# 14. effectiveness_ntu
# ===========================================================================

class TestEffectivenessNTU:

    def test_counter_flow_general(self):
        """ε = (1 - exp(-NTU(1-Cr))) / (1 - Cr exp(-NTU(1-Cr))) for Cr < 1."""
        Cmin, Cmax, NTU = 1000.0, 2000.0, 2.0
        Cr = Cmin / Cmax
        exp_term = math.exp(-NTU * (1.0 - Cr))
        eps_expected = (1.0 - exp_term) / (1.0 - Cr * exp_term)
        res = effectiveness_ntu(Cmin, Cmax, NTU, flow="counter")
        assert res["ok"] is True
        assert abs(res["epsilon"] - eps_expected) / eps_expected < REL

    def test_counter_flow_Cr_equals_1(self):
        """Special case Cr=1: ε = NTU/(NTU+1)."""
        Cmin, Cmax, NTU = 1500.0, 1500.0, 3.0
        eps_expected = NTU / (NTU + 1.0)
        res = effectiveness_ntu(Cmin, Cmax, NTU, flow="counter")
        assert res["ok"] is True
        assert abs(res["epsilon"] - eps_expected) / eps_expected < REL

    def test_parallel_flow_formula(self):
        """ε = (1 - exp(-NTU(1+Cr))) / (1+Cr) for parallel flow."""
        Cmin, Cmax, NTU = 1000.0, 2000.0, 1.5
        Cr = Cmin / Cmax
        eps_expected = (1.0 - math.exp(-NTU * (1.0 + Cr))) / (1.0 + Cr)
        res = effectiveness_ntu(Cmin, Cmax, NTU, flow="parallel")
        assert res["ok"] is True
        assert abs(res["epsilon"] - eps_expected) / eps_expected < REL

    def test_counter_flow_higher_epsilon_than_parallel(self):
        """Counter-flow should be more effective than parallel for same NTU, Cr."""
        Cmin, Cmax, NTU = 1000.0, 2000.0, 2.0
        eps_counter = effectiveness_ntu(Cmin, Cmax, NTU, flow="counter")["epsilon"]
        eps_parallel = effectiveness_ntu(Cmin, Cmax, NTU, flow="parallel")["epsilon"]
        assert eps_counter > eps_parallel

    def test_epsilon_bounded_0_to_1(self):
        res = effectiveness_ntu(500.0, 1000.0, 10.0, flow="counter")
        assert res["ok"] is True
        assert 0.0 <= res["epsilon"] <= 1.0

    def test_Cmin_greater_than_Cmax_returns_error(self):
        res = effectiveness_ntu(2000.0, 1000.0, 2.0)
        assert res["ok"] is False

    def test_unknown_flow_returns_error(self):
        res = effectiveness_ntu(1000.0, 2000.0, 2.0, flow="shell-and-tube")
        assert res["ok"] is False

    def test_crossflow_formula(self):
        """Verify cross-flow unmixed formula (Incropera 11.31) at specific point."""
        Cmin, Cmax, NTU = 1000.0, 2000.0, 2.0
        Cr = Cmin / Cmax
        eps_expected = 1.0 - math.exp(
            (NTU ** 0.22 / Cr) * (math.exp(-Cr * NTU ** 0.78) - 1.0)
        )
        res = effectiveness_ntu(Cmin, Cmax, NTU, flow="crossflow_unmixed")
        assert res["ok"] is True
        assert abs(res["epsilon"] - eps_expected) / eps_expected < REL


# ===========================================================================
# 15. lumped_capacitance
# ===========================================================================

class TestLumpedCapacitance:

    def test_temperature_at_t0_equals_Ti(self):
        """At t=0: T(0) = T_i."""
        res = lumped_capacitance(
            T_i=400.0, T_inf=300.0, h=10.0, A_s=0.01,
            rho=2700.0, V=1e-4, c_p=900.0, t=0.0
        )
        assert res["ok"] is True
        assert abs(res["T_t_K"] - 400.0) < 1e-9

    def test_temperature_decays_toward_T_inf(self):
        """T(t) should be between T_i and T_inf for t > 0."""
        res = lumped_capacitance(
            T_i=400.0, T_inf=300.0, h=10.0, A_s=0.01,
            rho=2700.0, V=1e-4, c_p=900.0, t=100.0
        )
        assert res["ok"] is True
        assert 300.0 < res["T_t_K"] < 400.0

    def test_temperature_formula(self):
        """T(t) = T_inf + (T_i - T_inf) exp(-t/τ)."""
        T_i, T_inf, h, A_s, rho, V, c_p, t = 500.0, 300.0, 20.0, 0.02, 8000.0, 5e-4, 500.0, 50.0
        tau_expected = rho * V * c_p / (h * A_s)
        T_expected = T_inf + (T_i - T_inf) * math.exp(-t / tau_expected)
        res = lumped_capacitance(T_i, T_inf, h, A_s, rho, V, c_p, t)
        assert res["ok"] is True
        assert abs(res["T_t_K"] - T_expected) / T_expected < REL
        assert abs(res["tau_s"] - tau_expected) / tau_expected < REL

    def test_theta_formula(self):
        """θ = exp(-t/τ)."""
        res = lumped_capacitance(
            T_i=400.0, T_inf=300.0, h=10.0, A_s=0.01,
            rho=2700.0, V=1e-4, c_p=900.0, t=50.0
        )
        assert res["ok"] is True
        theta_from_T = (res["T_t_K"] - 300.0) / (400.0 - 300.0)
        assert abs(res["theta"] - theta_from_T) < 1e-9

    def test_Biot_number_computed_with_k(self):
        """Bi = h * L_c / k."""
        h, A_s, V, k = 10.0, 0.06, 1e-4, 200.0
        Lc = V / A_s
        Bi_expected = h * Lc / k
        res = lumped_capacitance(
            T_i=400.0, T_inf=300.0, h=h, A_s=A_s,
            rho=2700.0, V=V, c_p=900.0, t=100.0, k=k
        )
        assert res["ok"] is True
        assert abs(res["Bi"] - Bi_expected) / Bi_expected < REL

    def test_Biot_none_without_k(self):
        """Bi should be None when k is not provided."""
        res = lumped_capacitance(
            T_i=400.0, T_inf=300.0, h=10.0, A_s=0.01,
            rho=2700.0, V=1e-4, c_p=900.0, t=50.0
        )
        assert res["ok"] is True
        assert res["Bi"] is None

    def test_high_Biot_emits_warning(self):
        """Bi > 0.1 should emit a warning (Incropera §5.3 criterion)."""
        # Large h, small k → Bi >> 0.1
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = lumped_capacitance(
                T_i=400.0, T_inf=300.0, h=10000.0, A_s=0.01,
                rho=2700.0, V=1e-4, c_p=900.0, t=10.0,
                k=1.0  # k=1 W/mK, Bi >> 0.1
            )
        assert res["ok"] is True  # still returns, just warns
        assert len(w) == 1
        assert "Bi" in str(w[0].message) or "lumped" in str(w[0].message).lower()

    def test_negative_t_returns_error(self):
        res = lumped_capacitance(
            T_i=400.0, T_inf=300.0, h=10.0, A_s=0.01,
            rho=2700.0, V=1e-4, c_p=900.0, t=-1.0
        )
        assert res["ok"] is False

    def test_Q_total_formula(self):
        """Q = m c_p (T_i - T(t)) = ρ V c_p (T_i - T(t))."""
        T_i, T_inf, h, A_s, rho, V, c_p, t = 500.0, 300.0, 20.0, 0.02, 8000.0, 5e-4, 500.0, 100.0
        res = lumped_capacitance(T_i, T_inf, h, A_s, rho, V, c_p, t)
        assert res["ok"] is True
        Q_expected = rho * V * c_p * (T_i - res["T_t_K"])
        assert abs(res["Q_total_J"] - Q_expected) / abs(Q_expected) < REL


# ===========================================================================
# 16. LLM tool wrappers — happy paths and error paths
# ===========================================================================

class TestToolWrappers:

    def test_run_composite_wall_happy_path(self):
        ctx = _ctx()
        raw = _run(run_composite_wall(ctx, _args(
            layers=[{"k": 1.0, "t": 0.1}], T_hot=400.0, T_cold=300.0
        )))
        d = _ok(raw)
        assert d["Q_W"] > 0

    def test_run_composite_wall_missing_layers(self):
        ctx = _ctx()
        raw = _run(run_composite_wall(ctx, _args(T_hot=400.0, T_cold=300.0)))
        _err_response(raw)

    def test_run_cylindrical_shell_happy_path(self):
        ctx = _ctx()
        raw = _run(run_cylindrical_shell(ctx, _args(
            r_inner=0.05, r_outer=0.10, k=50.0, T_inner=500.0, T_outer=300.0
        )))
        d = _ok(raw)
        assert d["Q_W"] > 0

    def test_run_spherical_shell_happy_path(self):
        ctx = _ctx()
        raw = _run(run_spherical_shell(ctx, _args(
            r_inner=0.05, r_outer=0.10, k=10.0, T_inner=500.0, T_outer=300.0
        )))
        d = _ok(raw)
        assert d["R_cond"] > 0

    def test_run_nusselt_flat_plate_happy_path(self):
        ctx = _ctx()
        raw = _run(run_nusselt_flat_plate(ctx, _args(Re_L=1e5, Pr=0.71)))
        d = _ok(raw)
        assert d["Nu"] > 0

    def test_run_nusselt_pipe_dittus_happy_path(self):
        ctx = _ctx()
        raw = _run(run_nusselt_pipe_dittus(ctx, _args(Re_D=50000.0, Pr=0.71)))
        d = _ok(raw)
        assert d["Nu"] > 0

    def test_run_nusselt_pipe_laminar_happy_path(self):
        ctx = _ctx()
        raw = _run(run_nusselt_pipe_laminar(ctx, _args(Re_D=800.0, Pr=5.0, L_D=50.0)))
        d = _ok(raw)
        assert d["Nu"] >= 3.66

    def test_run_nusselt_cylinder_cb_happy_path(self):
        ctx = _ctx()
        raw = _run(run_nusselt_cylinder_cb(ctx, _args(Re_D=4000.0, Pr=0.71)))
        d = _ok(raw)
        assert d["Nu"] > 0

    def test_run_nusselt_natural_vplate_happy_path(self):
        ctx = _ctx()
        raw = _run(run_nusselt_natural_vplate(ctx, _args(Ra_L=1e6, Pr=0.71)))
        d = _ok(raw)
        assert d["Nu"] > 0

    def test_run_radiation_two_surface_happy_path(self):
        ctx = _ctx()
        raw = _run(run_radiation_two_surface(ctx, _args(
            T1=1000.0, T2=500.0, eps1=0.9, eps2=0.9, A1=1.0, A2=1.0, F12=1.0
        )))
        d = _ok(raw)
        assert d["Q_12_W"] > 0

    def test_run_fin_straight_happy_path(self):
        ctx = _ctx()
        raw = _run(run_fin_straight(ctx, _args(L=0.05, t=0.002, k=200.0, h=50.0)))
        d = _ok(raw)
        assert 0 < d["eta_f"] <= 1.0

    def test_run_fin_pin_happy_path(self):
        ctx = _ctx()
        raw = _run(run_fin_pin(ctx, _args(L=0.05, D=0.004, k=200.0, h=50.0)))
        d = _ok(raw)
        assert 0 < d["eta_f"] <= 1.0

    def test_run_fin_array_resistance_happy_path(self):
        ctx = _ctx()
        raw = _run(run_fin_array_resistance(ctx, _args(
            N=10, eta_f=0.8, A_fin=0.01, A_base=0.005, h=50.0, A_total=0.105
        )))
        d = _ok(raw)
        assert d["R_array"] > 0

    def test_run_lmtd_counter_flow_happy_path(self):
        ctx = _ctx()
        raw = _run(run_lmtd(ctx, _args(
            T_h_in=380.0, T_h_out=320.0, T_c_in=290.0, T_c_out=340.0,
            U=500.0, A=2.0, flow="counter"
        )))
        d = _ok(raw)
        assert d["Q_W"] > 0

    def test_run_effectiveness_ntu_happy_path(self):
        ctx = _ctx()
        raw = _run(run_effectiveness_ntu(ctx, _args(
            C_min=1000.0, C_max=2000.0, NTU=2.0, flow="counter"
        )))
        d = _ok(raw)
        assert 0 < d["epsilon"] <= 1.0

    def test_run_lumped_capacitance_happy_path(self):
        ctx = _ctx()
        raw = _run(run_lumped_capacitance(ctx, _args(
            T_i=400.0, T_inf=300.0, h=10.0, A_s=0.01,
            rho=2700.0, V=1e-4, c_p=900.0, t=100.0
        )))
        d = _ok(raw)
        assert 300.0 < d["T_t_K"] < 400.0

    def test_run_lumped_capacitance_bad_json(self):
        ctx = _ctx()
        raw = _run(run_lumped_capacitance(ctx, b"not json at all"))
        _err_response(raw)

    def test_run_radiation_two_surface_missing_field(self):
        ctx = _ctx()
        raw = _run(run_radiation_two_surface(ctx, _args(
            T1=1000.0, T2=500.0, eps1=0.9, eps2=0.9, A1=1.0
            # missing A2, F12
        )))
        _err_response(raw)

    def test_run_lmtd_missing_U(self):
        ctx = _ctx()
        raw = _run(run_lmtd(ctx, _args(
            T_h_in=380.0, T_h_out=320.0, T_c_in=290.0, T_c_out=340.0, A=2.0
        )))
        _err_response(raw)


# ===========================================================================
# 17. CITABLE REFERENCE CASES — known numeric answers from the literature
#
# Each case below has an answer that can be cross-checked against a published
# worked example or an exact analytic closed form. These are the
# production-confidence anchors for the heatxfer module.
#
# Primary reference:
#   Incropera, F.P., DeWitt, D.P., Bergman, T.L., Lavine, A.S.,
#   "Fundamentals of Heat and Mass Transfer", 6th/7th ed., Wiley.
# ===========================================================================

class TestCitableReferenceCases:

    def test_ref_cylindrical_shell_analytic_closed_form(self):
        """Incropera eq. 3.27 closed form (analytic truth).

        Pipe insulation: r_i=0.05 m, r_o=0.10 m, k=0.05 W/m·K, L=1 m,
        T_i=400 K, T_o=200 K.
            q = 2π k L ΔT / ln(r_o/r_i)
              = 2π(0.05)(1)(200) / ln(2) = 90.6472 W
        """
        res = cylindrical_shell(0.05, 0.10, 0.05, 400.0, 200.0, 1.0)
        assert res["ok"] is True
        q_exact = 2.0 * math.pi * 0.05 * 1.0 * 200.0 / math.log(2.0)
        assert q_exact == pytest.approx(90.6472, abs=1e-3)
        assert res["Q_W"] == pytest.approx(q_exact, rel=1e-9)

    def test_ref_spherical_shell_analytic_closed_form(self):
        """Incropera eq. 3.35 closed form (analytic truth).

        r_i=0.05 m, r_o=0.10 m, k=10 W/m·K, ΔT=200 K.
            q = 4π k r_i r_o ΔT / (r_o - r_i)
              = 4π(10)(0.05)(0.10)(200) / 0.05 = 2513.2741 W
        """
        res = spherical_shell(0.05, 0.10, 10.0, 500.0, 300.0)
        assert res["ok"] is True
        q_exact = 4.0 * math.pi * 10.0 * 0.05 * 0.10 * 200.0 / 0.05
        assert q_exact == pytest.approx(2513.2741, abs=1e-2)
        assert res["Q_W"] == pytest.approx(q_exact, rel=1e-9)

    def test_ref_churchill_bernstein_incropera_ex_7_7(self):
        """Incropera Example 7.7 (cross-flow over a cylinder).

        Air over a circular cylinder: Re_D ≈ 6071, Pr ≈ 0.7.
        Churchill-Bernstein gives Nu_D ≈ 40.6 (Incropera 6th ed Ex 7.7).
        """
        res = nusselt_cylinder_churchill_bernstein(6071.0, 0.7)
        assert res["ok"] is True
        assert res["Nu"] == pytest.approx(40.6, abs=0.5)

    def test_ref_natural_convection_vplate_incropera_ex_9_2(self):
        """Incropera Example 9.2 (free convection, vertical plate).

        Ra_L ≈ 1.813e9, Pr ≈ 0.69. Churchill-Chu composite ('all')
        correlation yields Nu_L ≈ 147 (Incropera 6th ed Ex 9.2).
        """
        res = nusselt_natural_vertical_plate(1.813e9, 0.69, regime="all")
        assert res["ok"] is True
        assert res["Nu"] == pytest.approx(147.0, abs=1.5)

    def test_ref_effectiveness_ntu_counterflow_Cr0(self):
        """ε-NTU analytic truth: Cr→0 (phase-change side) counterflow.

        For Cr = 0, ε = 1 - exp(-NTU) for all arrangements
        (Incropera Table 11.4). NTU=1 → ε = 1 - e⁻¹ = 0.632121.
        """
        res = effectiveness_ntu(1000.0, 1.0e12, 1.0, flow="counter")
        assert res["ok"] is True
        assert res["epsilon"] == pytest.approx(1.0 - math.exp(-1.0), rel=1e-4)

    def test_ref_effectiveness_ntu_counterflow_Cr1(self):
        """ε-NTU analytic truth: Cr=1 counterflow (Incropera 11.29a).

        ε = NTU / (1 + NTU). NTU=2 → ε = 2/3 = 0.666667.
        """
        res = effectiveness_ntu(1500.0, 1500.0, 2.0, flow="counter")
        assert res["ok"] is True
        assert res["epsilon"] == pytest.approx(2.0 / 3.0, rel=1e-9)

    def test_ref_lmtd_balanced_counterflow_analytic(self):
        """LMTD analytic truth: balanced counterflow ΔT1 = ΔT2.

        When the two terminal ΔT are equal, ΔT_lm = ΔT (l'Hôpital limit).
        T_h_in=400, T_h_out=350, T_c_in=300, T_c_out=350:
            ΔT1 = 400-350 = 50, ΔT2 = 350-300 = 50  → LMTD = 50 K
            Q = U A LMTD = 200·1·50 = 10000 W.
        """
        res = lmtd_heat_exchanger(400.0, 350.0, 300.0, 350.0, 200.0, 1.0,
                                  flow="counter")
        assert res["ok"] is True
        assert res["LMTD_K"] == pytest.approx(50.0, abs=1e-9)
        assert res["Q_W"] == pytest.approx(10000.0, rel=1e-9)

    def test_ref_lumped_capacitance_one_time_constant(self):
        """Lumped-capacitance analytic truth (Incropera §5.3).

        At t = τ, θ = (T-T∞)/(Ti-T∞) = e⁻¹ = 0.367879.
        Ti=400 K, T∞=300 K → T(τ) = 300 + 100·e⁻¹ = 336.788 K.
        """
        # Choose params so τ is exactly known: τ = ρ V cp / (h A_s)
        rho, V, cp, h, A_s = 1000.0, 1e-3, 1000.0, 100.0, 1.0
        tau = rho * V * cp / (h * A_s)  # = 10 s
        res = lumped_capacitance(T_i=400.0, T_inf=300.0, h=h, A_s=A_s,
                                 rho=rho, V=V, c_p=cp, t=tau)
        assert res["ok"] is True
        assert res["tau_s"] == pytest.approx(tau, rel=1e-9)
        assert res["theta"] == pytest.approx(math.exp(-1.0), rel=1e-9)
        assert res["T_t_K"] == pytest.approx(300.0 + 100.0 * math.exp(-1.0),
                                             rel=1e-9)

    def test_ref_dittus_boelter_textbook_form(self):
        """Dittus-Boelter exact form check (Incropera eq. 8.60).

        Re_D=10000, Pr=0.707 (air), heating (n=0.4):
            Nu = 0.023·10000^0.8·0.707^0.4 = 31.732
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = nusselt_pipe_dittus_boelter(10000.0, 0.707, heating=True)
        assert res["ok"] is True
        nu_exact = 0.023 * 10000.0 ** 0.8 * 0.707 ** 0.4
        assert nu_exact == pytest.approx(31.732, abs=1e-2)
        assert res["Nu"] == pytest.approx(nu_exact, rel=1e-9)

    def test_ref_fin_efficiency_known_mLc(self):
        """Straight-fin efficiency analytic truth (Incropera eq. 3.86).

        η_f = tanh(mL_c)/(mL_c). For mL_c = 1: η_f = tanh(1) = 0.761594.
        Pick L,t,k,h so that m·L = 1 exactly:
            m = sqrt(2h/(k·t)); choose 2h/(k·t) = 1 → m = 1, L_c = 1.
        h=50, k=100, t=2·h/k = 1.0 → m = sqrt(2·50/(100·1)) = 1.0; L=1.
        """
        res = fin_efficiency_straight(L=1.0, t=1.0, k=100.0, h=50.0,
                                      tip="adiabatic")
        assert res["ok"] is True
        assert res["mL_c"] == pytest.approx(1.0, rel=1e-9)
        assert res["eta_f"] == pytest.approx(math.tanh(1.0), rel=1e-9)
        assert res["eta_f"] == pytest.approx(0.7615942, abs=1e-6)
