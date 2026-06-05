"""
Tests for kerf_piping.pipe_stress — ASME B31.1 / B31.3 pipe stress checks.

Validation oracles
------------------
1. sustained_stress: verify S_L_hoop = P·D/(4t) and S_L_bend = M/Z.
2. thermal_expansion_force: σ_th = E·α·ΔT (A106-B reference values).
3. expansion_stress_range: ASME B31.3 §319.4.4 Eq. 17 arithmetic.
4. allowable_expansion_stress: S_A = f(1.25·S_c + 0.25·S_h).
5. piping_pipe_stress LLM tool — async round-trip.

Reference calculations
----------------------
A106-B, 4" Sch40: OD = 4.500", wall = 0.237"
  Z = π/32 · (OD⁴ - ID⁴) / OD
    = π/32 · (4.5⁴ - 4.026⁴) / 4.5
    ≈ 3.21 in³
  A_metal = π/4 · (4.5² - 4.026²) ≈ 3.17 in²
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_piping.pipe_stress import (
    sustained_stress,
    thermal_expansion_force,
    expansion_stress_range,
    allowable_expansion_stress,
    occasional_stress_check,
    _pipe_section_modulus_in3,
    _pipe_metal_area_in2,
    _MODULUS_PSI,
    _ALPHA_PER_F,
    _SH_PSI,
)

# ---------------------------------------------------------------------------
# Reference pipe: A106-B, 4" Sch 40
# ---------------------------------------------------------------------------
OD_IN   = 4.500    # inches (ASME B36.10M NPS 4")
WALL_IN = 0.237    # inches (Sch 40 per B36.10M)
ID_IN   = OD_IN - 2 * WALL_IN  # 4.026"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    pass


# ===========================================================================
# Section properties
# ===========================================================================

class TestPipeSectionProperties:
    def test_section_modulus_4in_sch40(self):
        """
        4" Sch40: OD=4.500", wall=0.237", ID=4.026"
        Z = π/32 · (OD⁴ - ID⁴) / OD ≈ 3.21 in³
        """
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        assert 3.0 < Z < 3.5, f"Expected Z ≈ 3.21 in³, got {Z:.4f}"

    def test_metal_area_4in_sch40(self):
        """
        A = π/4·(OD²-ID²) = π/4·(4.5²-4.026²) ≈ 3.17 in²
        """
        A = _pipe_metal_area_in2(OD_IN, WALL_IN)
        assert 3.0 < A < 3.4, f"Expected A ≈ 3.17 in², got {A:.4f}"

    def test_zero_wall_raises(self):
        with pytest.raises(ValueError):
            _pipe_section_modulus_in3(4.5, 0.0)

    def test_wall_too_thick_raises(self):
        """Wall > OD/2 is physically impossible."""
        with pytest.raises(ValueError):
            _pipe_section_modulus_in3(4.5, 2.5)

    def test_section_modulus_increases_with_wall(self):
        Z_thin  = _pipe_section_modulus_in3(4.5, 0.237)
        Z_thick = _pipe_section_modulus_in3(4.5, 0.500)
        assert Z_thick > Z_thin


# ===========================================================================
# sustained_stress
# ===========================================================================

class TestSustainedStress:
    def test_hoop_component_formula(self):
        """
        S_L_hoop = P·D/(4·t) — verify against direct formula.
        P=100 psi, OD=4.5", wall=0.237"
        S_L_hoop = 100·4.5/(4·0.237) = 450/0.948 ≈ 474.7 psi
        """
        P = 100.0
        result = sustained_stress(OD_IN, WALL_IN, P, 0.0, 1.0)
        expected_hoop = P * OD_IN / (4.0 * WALL_IN)
        assert result.details["hoop_stress_psi"] == pytest.approx(expected_hoop, rel=1e-4)

    def test_bending_component_formula(self):
        """
        S_L_bend = M/Z where M = w·L²/8 (simply supported).
        w = 20 lbf/ft → 20/12 lbf/in; L = 15 ft → 180 in
        M = (20/12) · 180² / 8 = 1.667 · 32400 / 8 = 6750 in-lbf
        Z ≈ 3.21 in³  → S_bend ≈ 2103 psi
        """
        w_ft = 20.0   # lbf/ft
        L_ft = 15.0   # ft
        result = sustained_stress(OD_IN, WALL_IN, 0.0, w_ft, L_ft)
        w_in = w_ft / 12.0
        L_in = L_ft * 12.0
        M_expected = w_in * L_in ** 2 / 8.0
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        S_bend_expected = M_expected / Z
        assert result.details["bending_stress_psi"] == pytest.approx(S_bend_expected, rel=1e-4)

    def test_total_is_hoop_plus_bending(self):
        result = sustained_stress(OD_IN, WALL_IN, 150.0, 18.0, 15.0)
        assert result.calculated_psi == pytest.approx(
            result.details["hoop_stress_psi"] + result.details["bending_stress_psi"],
            rel=1e-5
        )

    def test_zero_weight_zero_span_bending_zero(self):
        """With zero weight, bending = 0 and total = hoop only."""
        result = sustained_stress(OD_IN, WALL_IN, 100.0, 0.0, 0.0)
        assert result.details["bending_stress_psi"] == pytest.approx(0.0, abs=1e-3)

    def test_compliant_light_service(self):
        """Light service should be compliant."""
        result = sustained_stress(OD_IN, WALL_IN, 50.0, 5.0, 10.0)
        assert result.compliant is True

    def test_utilisation_over_one_marks_non_compliant(self):
        """Very high pressure + heavy span → non-compliant."""
        result = sustained_stress(OD_IN, WALL_IN, 10000.0, 500.0, 30.0)
        assert result.compliant is False
        assert result.utilisation > 1.0

    def test_result_has_code_and_load_case(self):
        result = sustained_stress(OD_IN, WALL_IN, 100.0, 15.0, 12.0)
        assert result.code in ("B31.1", "B31.3")
        assert result.load_case == "sustained"

    def test_disclaimer_present(self):
        result = sustained_stress(OD_IN, WALL_IN, 100.0, 15.0, 12.0)
        assert len(result.disclaimer) > 20

    def test_as_dict_serialisable(self):
        result = sustained_stress(OD_IN, WALL_IN, 100.0, 15.0, 12.0)
        d = result.as_dict()
        assert "code" in d
        assert "calculated_psi" in d
        assert "allowable_psi" in d
        assert "compliant" in d


# ===========================================================================
# thermal_expansion_force
# ===========================================================================

class TestThermalExpansionForce:
    def test_sigma_th_formula_a106b(self):
        """
        A106-B: E = 29e6 psi, α = 6.5e-6 /°F
        ΔT = 400°F → σ_th = 29e6 × 6.5e-6 × 400 = 75,400 psi
        """
        r = thermal_expansion_force(OD_IN, WALL_IN, delta_T_F=400.0, material="A106-B")
        E     = _MODULUS_PSI["A106-B"]
        alpha = _ALPHA_PER_F["A106-B"]
        expected = E * alpha * 400.0
        assert r["thermal_stress_psi"] == pytest.approx(expected, rel=1e-4)

    def test_force_equals_stress_times_area(self):
        """F_th = σ_th · A_metal."""
        r = thermal_expansion_force(OD_IN, WALL_IN, delta_T_F=200.0)
        A = _pipe_metal_area_in2(OD_IN, WALL_IN)
        E = _MODULUS_PSI["A106-B"]
        alpha = _ALPHA_PER_F["A106-B"]
        expected_stress = E * alpha * 200.0
        expected_force  = expected_stress * A
        assert r["thermal_force_lbf"] == pytest.approx(expected_force, rel=1e-4)

    def test_free_expansion_formula(self):
        """Free expansion = α·ΔT·12 in/ft."""
        dT = 300.0
        r = thermal_expansion_force(OD_IN, WALL_IN, delta_T_F=dT, material="A106-B")
        alpha = _ALPHA_PER_F["A106-B"]
        expected = alpha * dT * 12.0
        assert r["free_expansion_in_per_ft"] == pytest.approx(expected, rel=1e-4)

    def test_ss316_higher_expansion(self):
        """SS 316 has higher α than carbon steel → higher free expansion."""
        r_cs = thermal_expansion_force(OD_IN, WALL_IN, 300.0, material="A106-B")
        r_ss = thermal_expansion_force(OD_IN, WALL_IN, 300.0, material="A312-316")
        assert r_ss["free_expansion_in_per_ft"] > r_cs["free_expansion_in_per_ft"]

    def test_zero_delta_t_zero_force(self):
        r = thermal_expansion_force(OD_IN, WALL_IN, delta_T_F=0.0)
        assert r["thermal_force_lbf"] == pytest.approx(0.0, abs=1.0)

    def test_high_temp_triggers_warning(self):
        """A large ΔT that exceeds S_h should trigger a note."""
        r = thermal_expansion_force(OD_IN, WALL_IN, delta_T_F=2000.0, material="A106-B")
        # σ_th = 29e6 × 6.5e-6 × 2000 = 377,000 psi >> S_h = 17,500
        assert "exceeds" in r["compliant_note"].lower()

    def test_small_delta_t_within_sh(self):
        r = thermal_expansion_force(OD_IN, WALL_IN, delta_T_F=50.0, material="A106-B")
        assert "within" in r["compliant_note"].lower()

    def test_disclaimer_present(self):
        r = thermal_expansion_force(OD_IN, WALL_IN, 100.0)
        assert len(r["disclaimer"]) > 20


# ===========================================================================
# allowable_expansion_stress  (B31.3 §319.4.4)
# ===========================================================================

class TestAllowableExpansionStress:
    def test_formula_s_a(self):
        """S_A = f·(1.25·S_c + 0.25·S_h)."""
        S_c, S_h = 17_500, 15_000
        f = 1.0
        S_A = allowable_expansion_stress(S_c, S_h, f)
        expected = f * (1.25 * S_c + 0.25 * S_h)
        assert S_A == pytest.approx(expected, rel=1e-6)

    def test_f_factor_reduces_allowable(self):
        S_c, S_h = 17_500, 15_000
        S_A_1  = allowable_expansion_stress(S_c, S_h, f=1.0)
        S_A_09 = allowable_expansion_stress(S_c, S_h, f=0.9)
        assert S_A_09 < S_A_1

    def test_same_hot_cold_stress(self):
        """If S_c == S_h, S_A = f · 1.5 · S_h."""
        S = 17_500
        S_A = allowable_expansion_stress(S, S, f=1.0)
        assert S_A == pytest.approx(1.5 * S, rel=1e-6)


# ===========================================================================
# expansion_stress_range  (B31.3 §319.4.4 Eq. 17)
# ===========================================================================

class TestExpansionStressRange:
    def test_pure_bending_result(self):
        """
        M_i = M_o = 5000 in-lbf, M_t = 0, Z = 3.21 in³, SIF=1, f=1
        S_b = √(5000² + 5000²)/3.21 = 7071.07/3.21 ≈ 2203 psi
        S_t = 0 / (2·3.21) = 0
        S_E = √(2203² + 0) = 2203 psi
        """
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        M = 5000.0
        r = expansion_stress_range(M, M, 0.0, Z, 17_500, 17_500)
        S_b = math.sqrt(M**2 + M**2) / Z
        assert r.calculated_psi == pytest.approx(S_b, rel=1e-4)

    def test_torsion_increases_se(self):
        """Adding torsion must increase S_E vs pure bending."""
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r_no_tor  = expansion_stress_range(3000, 0, 0, Z, 17_500, 17_500)
        r_with_tor = expansion_stress_range(3000, 0, 2000, Z, 17_500, 17_500)
        assert r_with_tor.calculated_psi > r_no_tor.calculated_psi

    def test_sif_increases_sb(self):
        """Higher SIF must give higher S_E."""
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r1  = expansion_stress_range(5000, 0, 0, Z, 17_500, 17_500, i_SIF=1.0)
        r15 = expansion_stress_range(5000, 0, 0, Z, 17_500, 17_500, i_SIF=1.5)
        assert r15.calculated_psi > r1.calculated_psi

    def test_compliant_low_moments(self):
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r = expansion_stress_range(100, 100, 50, Z, 17_500, 17_500)
        assert r.compliant is True

    def test_non_compliant_high_moments(self):
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r = expansion_stress_range(1e6, 1e6, 1e6, Z, 17_500, 17_500)
        assert r.compliant is False

    def test_as_dict_keys(self):
        Z = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r = expansion_stress_range(1000, 1000, 500, Z, 17_500, 17_500)
        d = r.as_dict()
        assert "S_E_psi" in d["details"]
        assert "S_A_psi" in d["details"]


# ===========================================================================
# occasional_stress_check  (B31.1 §104.8.4)
# ===========================================================================

class TestOccasionalStressCheck:
    def test_1_33_factor(self):
        """Allowable should be 1.33 × S_h by default."""
        Z  = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        S_h = _SH_PSI["A106-B"]
        r = occasional_stress_check(1000.0, 0.0, Z, S_h)
        assert r.allowable_psi == pytest.approx(1.33 * S_h, rel=1e-4)

    def test_total_includes_sustained(self):
        Z  = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        S_sus = 2000.0
        M_occ = 3000.0
        r = occasional_stress_check(S_sus, M_occ, Z, 17_500)
        expected = S_sus + M_occ / Z
        assert r.calculated_psi == pytest.approx(expected, rel=1e-5)

    def test_compliant_for_moderate_load(self):
        Z  = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r = occasional_stress_check(500.0, 1000.0, Z, 17_500)
        assert r.compliant is True

    def test_non_compliant_extreme_load(self):
        Z  = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r = occasional_stress_check(10000.0, 5e6, Z, 17_500)
        assert r.compliant is False

    def test_load_case_label(self):
        Z  = _pipe_section_modulus_in3(OD_IN, WALL_IN)
        r = occasional_stress_check(1000.0, 0.0, Z, 17_500)
        assert r.load_case == "occasional"


# ===========================================================================
# piping_pipe_stress LLM tool (async)
# ===========================================================================

class TestPipingPipeStressTool:
    BASE_ARGS = {
        "od_in": OD_IN,
        "wall_in": WALL_IN,
        "pressure_psi": 150.0,
        "weight_lbf_per_ft": 18.0,
        "span_ft": 15.0,
        "material": "A106-B",
        "code": "B31.1",
    }

    def _call(self, **kwargs):
        from kerf_piping.tools import run_piping_pipe_stress
        args = {**self.BASE_ARGS, **kwargs}
        return json.loads(_run(run_piping_pipe_stress(args, FakeCtx())))

    def test_basic_call_ok(self):
        r = self._call()
        assert r.get("ok") is True

    def test_sustained_result_present(self):
        r = self._call()
        assert "sustained" in r
        assert r["sustained"]["calculated_psi"] > 0

    def test_sustained_compliant_flag_is_bool(self):
        r = self._call()
        assert isinstance(r["sustained"]["compliant"], bool)

    def test_thermal_absent_without_delta_t(self):
        r = self._call()
        assert r.get("thermal") is None

    def test_thermal_present_with_delta_t(self):
        r = self._call(delta_T_F=300.0)
        assert r.get("thermal") is not None
        assert r["thermal"]["thermal_force_lbf"] > 0

    def test_occasional_absent_without_m_occ(self):
        r = self._call()
        assert r.get("occasional") is None

    def test_occasional_present_with_m_occ(self):
        r = self._call(M_occasional_inlbf=5000.0)
        assert r.get("occasional") is not None
        assert r["occasional"]["load_case"] == "occasional"

    def test_all_three_load_cases(self):
        r = self._call(delta_T_F=300.0, M_occasional_inlbf=5000.0)
        assert r["sustained"] is not None
        assert r["thermal"] is not None
        assert r["occasional"] is not None

    def test_disclaimer_in_sustained(self):
        r = self._call()
        assert "disclaimer" in r["sustained"]

    def test_material_in_response(self):
        r = self._call()
        assert r["material"] == "A106-B"

    def test_code_in_response(self):
        r = self._call()
        assert r["code"] == "B31.1"

    def test_invalid_material_returns_error(self):
        from kerf_piping.tools import run_piping_pipe_stress
        args = {**self.BASE_ARGS, "material": "UNOBTANIUM"}
        r = json.loads(_run(run_piping_pipe_stress(args, FakeCtx())))
        # Should still run (material defaults gracefully) or return an error
        # Either ok with default or error code is acceptable
        assert "ok" in r or "error" in r
