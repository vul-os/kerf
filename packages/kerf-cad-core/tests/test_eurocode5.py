"""
tests/test_eurocode5.py — EC5 (EN 1995-1-1) timber design tests.

Coverage:
  kmod                — EN 1995-1-1 Table 3.1 values
  strength_class      — EN 338 / EN 14080 characteristic data
  design_strengths    — fd = kmod × fk / γM
  beam_bending_check  — §6.1.6 σm,d ≤ fm,d × kh
  combined_nm_check   — §6.2.4 interaction equations
  column_buckling     — §6.3.2 λ_rel + kc + check
  shear_check         — §6.1.7 τd ≤ kcr·fv,d
  LLM tool wrappers   — all seven tools, happy path + error paths

Validation against published examples:
  - Solid C24, b=100, h=200, L=4m, q=2 kN/m — bending SC2 medium → pass
  - Glulam GL28h column, b=140, h=140, L=3m — kc + capacity

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against Porteous & Kermani "Structural Timber Design to Eurocode 5"
(2nd ed., 2013) and EN 1995-1-1 hand calculations.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.struct.eurocode5 import (
    EC5_GAMMA_M_SOLID,
    EC5_GAMMA_M_GLULAM,
    EC5_GAMMA_M_LVL,
    kmod,
    strength_class,
    design_strengths,
    beam_bending_check,
    combined_nm_check,
    column_buckling,
    shear_check,
    run_ec5_strength_class,
    run_ec5_kmod,
    run_ec5_design_strength,
    run_ec5_beam_bending,
    run_ec5_combined_nm,
    run_ec5_column_buckling,
    run_ec5_shear,
)

REL = 1e-6


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


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is False, f"Expected ok=False, got: {d}"
    return d


# ===========================================================================
# 1. Partial factors
# ===========================================================================

class TestPartialFactors:

    def test_solid_gamma_m(self):
        assert EC5_GAMMA_M_SOLID == pytest.approx(1.3)

    def test_glulam_gamma_m(self):
        assert EC5_GAMMA_M_GLULAM == pytest.approx(1.25)

    def test_lvl_gamma_m(self):
        assert EC5_GAMMA_M_LVL == pytest.approx(1.2)


# ===========================================================================
# 2. kmod — EN 1995-1-1 Table 3.1
# ===========================================================================

class TestKmod:

    def test_sc1_permanent(self):
        r = kmod(1, "permanent")
        assert r["ok"] is True
        assert r["kmod"] == pytest.approx(0.60)

    def test_sc1_medium(self):
        r = kmod(1, "medium")
        assert r["ok"] is True
        assert r["kmod"] == pytest.approx(0.80)

    def test_sc2_short(self):
        r = kmod(2, "short")
        assert r["ok"] is True
        assert r["kmod"] == pytest.approx(0.90)

    def test_sc3_permanent(self):
        r = kmod(3, "permanent")
        assert r["ok"] is True
        assert r["kmod"] == pytest.approx(0.50)

    def test_sc3_medium(self):
        r = kmod(3, "medium")
        assert r["ok"] is True
        assert r["kmod"] == pytest.approx(0.65)

    def test_sc3_instantaneous(self):
        r = kmod(3, "instantaneous")
        assert r["ok"] is True
        assert r["kmod"] == pytest.approx(0.90)

    def test_invalid_service_class(self):
        r = kmod(4, "medium")
        assert r["ok"] is False
        assert "service_class" in r["reason"]

    def test_invalid_load_duration(self):
        r = kmod(2, "seismic")
        assert r["ok"] is False
        assert "seismic" in r["reason"]

    def test_sc1_sc2_same_kmod(self):
        """EN 1995-1-1 Table 3.1: SC1 and SC2 share identical kmod values."""
        for ld in ("permanent", "long_term", "medium", "short", "instantaneous"):
            assert kmod(1, ld)["kmod"] == pytest.approx(kmod(2, ld)["kmod"])


# ===========================================================================
# 3. Strength classes
# ===========================================================================

class TestStrengthClass:

    def test_c24_fm_k(self):
        r = strength_class("C24")
        assert r["ok"] is True
        assert r["fm_k"] == pytest.approx(24.0)

    def test_c24_fc0_k(self):
        r = strength_class("C24")
        assert r["fc0_k"] == pytest.approx(21.0)

    def test_c24_fv_k(self):
        r = strength_class("C24")
        assert r["fv_k"] == pytest.approx(4.0)

    def test_c24_E0_mean(self):
        r = strength_class("C24")
        assert r["E0_mean"] == pytest.approx(11000.0)

    def test_c24_E0_05(self):
        r = strength_class("C24")
        assert r["E0_05"] == pytest.approx(7400.0)

    def test_c24_rho_k(self):
        r = strength_class("C24")
        assert r["rho_k"] == pytest.approx(350.0)

    def test_c24_gamma_M_solid(self):
        r = strength_class("C24")
        assert r["gamma_M"] == pytest.approx(EC5_GAMMA_M_SOLID)

    def test_gl28h_gamma_M_glulam(self):
        r = strength_class("GL28h")
        assert r["ok"] is True
        assert r["gamma_M"] == pytest.approx(EC5_GAMMA_M_GLULAM)

    def test_gl28h_fm_k(self):
        r = strength_class("GL28h")
        assert r["fm_k"] == pytest.approx(28.0)

    def test_gl28h_fc0_k(self):
        r = strength_class("GL28h")
        assert r["fc0_k"] == pytest.approx(26.5)

    def test_gl32h_E0_mean(self):
        r = strength_class("GL32h")
        assert r["ok"] is True
        assert r["E0_mean"] == pytest.approx(13700.0)

    def test_d40_fm_k(self):
        r = strength_class("D40")
        assert r["ok"] is True
        assert r["fm_k"] == pytest.approx(40.0)

    def test_case_insensitive_c24(self):
        r = strength_class("c24")
        assert r["ok"] is True
        assert r["fm_k"] == pytest.approx(24.0)

    def test_unknown_class_returns_error(self):
        r = strength_class("C99")
        assert r["ok"] is False
        assert "C99" in r["reason"]

    def test_all_softwood_classes_present(self):
        for sc in ("C14", "C16", "C18", "C20", "C22", "C24", "C27", "C30", "C35", "C40", "C45", "C50"):
            r = strength_class(sc)
            assert r["ok"] is True, f"{sc} failed"

    def test_all_hardwood_classes_present(self):
        for sc in ("D30", "D35", "D40", "D50", "D60", "D70"):
            r = strength_class(sc)
            assert r["ok"] is True, f"{sc} failed"

    def test_all_glulam_classes_present(self):
        for sc in ("GL24h", "GL28h", "GL32h"):
            r = strength_class(sc)
            assert r["ok"] is True, f"{sc} failed"


# ===========================================================================
# 4. Design strengths
# ===========================================================================

class TestDesignStrengths:

    def test_c24_sc2_medium_fm_d(self):
        """
        C24: kmod(SC2, medium)=0.80, γM=1.3, fm_k=24 →
        fm,d = 0.80 × 24 / 1.3 = 14.769231 N/mm²
        """
        r = design_strengths("C24", 2, "medium")
        assert r["ok"] is True
        expected_fmd = 0.80 * 24.0 / 1.3
        assert r["fm_d"] == pytest.approx(expected_fmd, rel=REL)

    def test_c24_sc2_medium_fc0d(self):
        r = design_strengths("C24", 2, "medium")
        expected = 0.80 * 21.0 / 1.3
        assert r["fc0_d"] == pytest.approx(expected, rel=REL)

    def test_c24_sc2_medium_fvd(self):
        r = design_strengths("C24", 2, "medium")
        expected = 0.80 * 4.0 / 1.3
        assert r["fv_d"] == pytest.approx(expected, rel=REL)

    def test_c24_sc2_medium_E0mean_d(self):
        """E0mean_d = E0mean / γM (no kmod on stiffness)."""
        r = design_strengths("C24", 2, "medium")
        expected = 11000.0 / 1.3
        assert r["E0mean_d"] == pytest.approx(expected, rel=REL)

    def test_gl28h_sc2_medium_fm_d(self):
        """GL28h: γM=1.25, kmod=0.80 → fm,d = 0.80×28/1.25 = 17.92"""
        r = design_strengths("GL28h", 2, "medium")
        assert r["ok"] is True
        expected = 0.80 * 28.0 / 1.25
        assert r["fm_d"] == pytest.approx(expected, rel=REL)

    def test_invalid_class_returns_error(self):
        r = design_strengths("C99", 2, "medium")
        assert r["ok"] is False

    def test_invalid_service_class_returns_error(self):
        r = design_strengths("C24", 5, "medium")
        assert r["ok"] is False

    def test_kmod_field_in_result(self):
        r = design_strengths("C24", 1, "short")
        assert r["kmod"] == pytest.approx(0.90)

    def test_gamma_M_field_in_result(self):
        r = design_strengths("C24", 1, "short")
        assert r["gamma_M"] == pytest.approx(EC5_GAMMA_M_SOLID)


# ===========================================================================
# 5. Beam bending check  §6.1.6
# ===========================================================================

class TestBeamBending:

    # ---- Reference example: Porteous & Kermani / Trada ----
    # Solid C24, b=100mm, h=200mm, simply supported, L=4m, q=2 kN/m.
    # γQ=1.5 (variable), γG=1.35 (permanent/self-weight).
    # M_d = 1.5 × q × L²/8 = 1.5 × 2 × 16/8 = 6 kN·m  (characteristic ULS)
    # fm,d(SC2 medium) = 0.80×24/1.3 = 14.769 N/mm²
    # Wy = 100×200²/6 = 666667 mm³
    # σm,d = 6e6/666667 = 9.0 N/mm²
    # h=200 ≥ 150 → kh=1.0 → fm,d,eff=14.769
    # Utilization = 9.0/14.769 = 0.609 → PASS
    # ------------------------------------------------------------

    def test_c24_beam_reference_sigma_md(self):
        fm_d = design_strengths("C24", 2, "medium")["fm_d"]
        r = beam_bending_check(6.0, 100.0, 200.0, fm_d)
        assert r["ok"] is True
        assert r["sigma_md_MPa"] == pytest.approx(9.0, rel=REL)

    def test_c24_beam_reference_kh_is_1(self):
        fm_d = design_strengths("C24", 2, "medium")["fm_d"]
        r = beam_bending_check(6.0, 100.0, 200.0, fm_d)
        assert r["kh"] == pytest.approx(1.0)

    def test_c24_beam_reference_passes(self):
        fm_d = design_strengths("C24", 2, "medium")["fm_d"]
        r = beam_bending_check(6.0, 100.0, 200.0, fm_d)
        assert r["pass_"] is True
        assert r["utilization"] == pytest.approx(9.0 / (fm_d * 1.0), rel=REL)

    def test_kh_applied_for_small_section(self):
        """h=100mm < 150mm → kh = (150/100)^0.2 = 1.084 > 1.0."""
        fm_d = 14.0  # N/mm²
        r = beam_bending_check(1.0, 50.0, 100.0, fm_d)
        assert r["ok"] is True
        kh_expected = min((150.0 / 100.0) ** 0.2, 1.3)
        assert r["kh"] == pytest.approx(kh_expected, rel=REL)

    def test_kh_capped_at_1_3(self):
        """Very small h → kh capped at 1.3."""
        fm_d = 14.0
        r = beam_bending_check(0.001, 10.0, 10.0, fm_d)
        assert r["ok"] is True
        assert r["kh"] == pytest.approx(1.3)

    def test_fail_when_overstressed(self):
        fm_d = 5.0  # very low design strength
        r = beam_bending_check(10.0, 100.0, 200.0, fm_d)
        assert r["ok"] is True
        assert r["pass_"] is False
        assert len(r["warnings"]) > 0

    def test_kh_override(self):
        fm_d = 14.0
        r = beam_bending_check(1.0, 50.0, 80.0, fm_d, kh_override=1.15)
        assert r["kh"] == pytest.approx(1.15)

    def test_wy_formula(self):
        """Wy = b·h²/6."""
        b, h = 120.0, 240.0
        r = beam_bending_check(5.0, b, h, 15.0)
        assert r["Wy_mm3"] == pytest.approx(b * h ** 2 / 6.0, rel=REL)

    def test_invalid_b_returns_error(self):
        r = beam_bending_check(5.0, 0.0, 200.0, 14.0)
        assert r["ok"] is False

    def test_invalid_h_returns_error(self):
        r = beam_bending_check(5.0, 100.0, -1.0, 14.0)
        assert r["ok"] is False


# ===========================================================================
# 6. Combined N + M  §6.2.4
# ===========================================================================

class TestCombinedNM:

    def test_tension_linear_interaction(self):
        """Eq. 6.17: σt/ft + σm/fm ≤ 1."""
        r = combined_nm_check(5.0, 14.0, 4.0, 14.0, tension=True)
        assert r["ok"] is True
        expected = 5.0 / 14.0 + 4.0 / 14.0
        assert r["interaction"] == pytest.approx(expected, rel=REL)

    def test_compression_buckling_interaction(self):
        """Eq. 6.23: (σc/(kc·fc))² + σm/fm ≤ 1."""
        kc = 0.8
        r = combined_nm_check(5.0, 14.0, 3.0, 14.0, tension=False, kc=kc)
        assert r["ok"] is True
        expected = (5.0 / (kc * 14.0)) ** 2 + 3.0 / 14.0
        assert r["interaction"] == pytest.approx(expected, rel=REL)

    def test_pass_low_loads(self):
        r = combined_nm_check(2.0, 14.0, 2.0, 14.0)
        assert r["ok"] is True
        assert r["pass_"] is True
        assert r["interaction"] < 1.0

    def test_fail_high_loads(self):
        r = combined_nm_check(14.0, 14.0, 14.0, 14.0)
        assert r["ok"] is True
        assert r["pass_"] is False

    def test_kc_1_in_tension_mode(self):
        """In tension mode kc should not matter (linear formula)."""
        r1 = combined_nm_check(4.0, 12.0, 3.0, 12.0, tension=True, kc=1.0)
        r2 = combined_nm_check(4.0, 12.0, 3.0, 12.0, tension=True, kc=0.6)
        assert r1["interaction"] == pytest.approx(r2["interaction"], rel=REL)

    def test_invalid_fc0d_returns_error(self):
        r = combined_nm_check(5.0, 0.0, 3.0, 14.0)
        assert r["ok"] is False

    def test_invalid_kc_returns_error(self):
        r = combined_nm_check(5.0, 14.0, 3.0, 14.0, kc=0.0)
        assert r["ok"] is False

    def test_kc_above_1_returns_error(self):
        r = combined_nm_check(5.0, 14.0, 3.0, 14.0, kc=1.1)
        assert r["ok"] is False


# ===========================================================================
# 7. Column buckling  §6.3.2
# ===========================================================================

class TestColumnBuckling:

    # ---- Reference example: GL28h column, b=140, h=140, L=3m ----
    # fc0,k=26.5, E0,05=10200; βc=0.1 (glulam)
    # i = 140/√12 = 40.415 mm (square section → i_y = i_z = same)
    # L_eff = 3000 mm (pin-pin)
    # λ_rel = (3000/40.415)·√(26.5/10200)/π
    #       = 74.23·0.05098/π = 74.23·0.01623 = 1.205  (approx)
    # k = 0.5·[1 + 0.1·(1.205-0.3) + 1.205²] = 0.5·[1+0.0905+1.452] = 1.271
    # kc = 1/(1.271 + √(1.271²-1.205²)) = 1/(1.271+√(0.0666)) = 1/(1.271+0.258) = 0.654
    # ---------------------------------------------------------------------------

    def test_gl28h_column_lambda_rel(self):
        r = column_buckling(
            L_mm=3000, b_mm=140, h_mm=140,
            fc0_k=26.5, E0_05=10200,
            fc0_d=1.0,    # not tested here
            sigma_c0d=0.1,
            beta_c=0.1,
        )
        assert r["ok"] is True
        i = 140.0 / math.sqrt(12.0)
        lam_expected = (3000.0 / i) * math.sqrt(26.5 / 10200.0) / math.pi
        assert r["lambda_rel_z"] == pytest.approx(lam_expected, rel=1e-4)

    def test_gl28h_column_kc_value(self):
        r = column_buckling(
            L_mm=3000, b_mm=140, h_mm=140,
            fc0_k=26.5, E0_05=10200,
            fc0_d=17.0, sigma_c0d=5.0,
            beta_c=0.1,
        )
        assert r["ok"] is True
        i = 140.0 / math.sqrt(12.0)
        lam = (3000.0 / i) * math.sqrt(26.5 / 10200.0) / math.pi
        k = 0.5 * (1.0 + 0.1 * (lam - 0.3) + lam ** 2)
        kc_expected = 1.0 / (k + math.sqrt(k ** 2 - lam ** 2))
        assert r["kc"] == pytest.approx(kc_expected, rel=1e-4)

    def test_gl28h_column_passes_with_low_stress(self):
        """σc,0,d=5 N/mm², fc,0,d=17 → kc·fc,0,d > 5 → PASS."""
        r = column_buckling(
            L_mm=3000, b_mm=140, h_mm=140,
            fc0_k=26.5, E0_05=10200,
            fc0_d=17.0, sigma_c0d=5.0,
            beta_c=0.1,
        )
        assert r["ok"] is True
        assert r["pass_"] is True

    def test_square_section_same_lambda_both_axes(self):
        """Square section → λ_rel_y == λ_rel_z."""
        r = column_buckling(3000, 140, 140, 26.5, 10200, 17.0, 5.0, beta_c=0.1)
        assert r["lambda_rel_y"] == pytest.approx(r["lambda_rel_z"], rel=REL)

    def test_rectangular_weak_axis_governs(self):
        """b < h → z-axis (breadth) is weaker, smaller kc."""
        r = column_buckling(3000, 90, 140, 24.0, 7400, 12.0, 4.0, beta_c=0.2)
        assert r["ok"] is True
        assert r["kc_z"] <= r["kc_y"]

    def test_kc_between_0_and_1(self):
        r = column_buckling(4000, 100, 200, 21.0, 7400, 12.0, 5.0)
        assert r["ok"] is True
        assert 0.0 < r["kc"] <= 1.0

    def test_very_short_column_kc_near_1(self):
        """Very short column → λ_rel ≤ 0.3 → kc = 1.0."""
        r = column_buckling(100, 140, 140, 26.5, 10200, 17.0, 5.0, beta_c=0.1)
        assert r["ok"] is True
        assert r["kc"] == pytest.approx(1.0, rel=1e-3)

    def test_fail_high_stress(self):
        """σc,0,d > kc·fc,0,d → FAIL."""
        r = column_buckling(5000, 100, 100, 16.0, 4700, 8.0, 10.0)
        assert r["ok"] is True
        assert r["pass_"] is False
        assert any("FAIL" in w for w in r["warnings"])

    def test_k_e_effective_length(self):
        """Fix-pin k_e=0.7 → shorter effective length → higher kc vs pin-pin."""
        r_pp = column_buckling(3000, 100, 100, 21.0, 7400, 12.0, 5.0, k_e=1.0)
        r_fp = column_buckling(3000, 100, 100, 21.0, 7400, 12.0, 5.0, k_e=0.7)
        assert r_fp["kc"] > r_pp["kc"]

    def test_beta_c_solid_vs_glulam(self):
        """βc=0.2 (solid) → more conservative kc than βc=0.1 (glulam)."""
        r_solid = column_buckling(3000, 140, 140, 26.5, 10200, 17.0, 5.0, beta_c=0.2)
        r_glulam = column_buckling(3000, 140, 140, 26.5, 10200, 17.0, 5.0, beta_c=0.1)
        assert r_solid["kc"] <= r_glulam["kc"]

    def test_invalid_L_returns_error(self):
        r = column_buckling(0, 100, 100, 21.0, 7400, 12.0, 5.0)
        assert r["ok"] is False

    def test_invalid_b_returns_error(self):
        r = column_buckling(3000, -50, 100, 21.0, 7400, 12.0, 5.0)
        assert r["ok"] is False


# ===========================================================================
# 8. Shear check  §6.1.7
# ===========================================================================

class TestShearCheck:

    def test_solid_timber_kcr_0_67(self):
        """Default kcr=0.67 for solid timber."""
        r = shear_check(4.0, 100.0, 200.0, 4.0 * 0.80 / 1.3)
        assert r["ok"] is True
        assert r["kcr"] == pytest.approx(0.67)

    def test_tau_d_formula(self):
        """τd = 1.5·Vd / (b·h)."""
        V_kN, b, h = 5.0, 100.0, 200.0
        r = shear_check(V_kN, b, h, 3.0)
        assert r["ok"] is True
        expected = 1.5 * (V_kN * 1e3) / (b * h)
        assert r["tau_d_MPa"] == pytest.approx(expected, rel=REL)

    def test_pass_low_shear(self):
        """Low shear force → pass."""
        fv_d = 0.80 * 4.0 / 1.3  # C24 SC2 medium
        r = shear_check(1.0, 100.0, 200.0, fv_d)
        assert r["ok"] is True
        assert r["pass_"] is True

    def test_fail_high_shear(self):
        """High shear → fail."""
        r = shear_check(50.0, 50.0, 100.0, 1.0)
        assert r["ok"] is True
        assert r["pass_"] is False
        assert any("FAIL" in w for w in r["warnings"])

    def test_kcr_1_glulam(self):
        """Glulam: kcr=1.0."""
        r = shear_check(3.0, 140.0, 280.0, 3.5 * 0.80 / 1.25, kcr=1.0)
        assert r["ok"] is True
        assert r["kcr"] == pytest.approx(1.0)

    def test_fv_d_eff_formula(self):
        fv_d, kcr = 2.46, 0.67
        r = shear_check(2.0, 100.0, 200.0, fv_d, kcr=kcr)
        assert r["fv_d_eff_MPa"] == pytest.approx(fv_d * kcr, rel=REL)

    def test_utilization_ratio(self):
        """utilization = τd / (kcr·fv,d)."""
        V_kN, b, h, fv_d, kcr = 3.0, 100.0, 200.0, 2.5, 0.67
        r = shear_check(V_kN, b, h, fv_d, kcr=kcr)
        tau = 1.5 * (V_kN * 1e3) / (b * h)
        expected = tau / (kcr * fv_d)
        assert r["utilization"] == pytest.approx(expected, rel=REL)

    def test_invalid_b_returns_error(self):
        r = shear_check(5.0, 0.0, 200.0, 3.0)
        assert r["ok"] is False

    def test_invalid_kcr_returns_error(self):
        r = shear_check(5.0, 100.0, 200.0, 3.0, kcr=0.0)
        assert r["ok"] is False


# ===========================================================================
# 9. Published reference case: C24 beam
# ===========================================================================

class TestC24BeamReferenceCase:
    """
    Porteous & Kermani §4.x worked example / Trada EC5 guide.

    Solid timber C24, b=100 mm, h=200 mm, L=4 m, simply supported.
    UDL q=2 kN/m (characteristic variable).  γQ=1.5 → qd=3 kN/m.
    M_d = 3×4²/8 = 6 kN·m
    Service class 2, load duration = medium.

    fm,k=24, kmod=0.80, γM=1.3  →  fm,d=14.769 N/mm²
    Wy = 100×200²/6 = 666 667 mm³
    σm,d = 6×10⁶/666667 = 9.000 N/mm²
    kh = 1.0 (h≥150)
    Utilization = 9.000/14.769 = 0.609  →  PASS

    Shear at support: Vd = qd×L/2 = 3×4/2 = 6 kN
    τd = 1.5×6000/(100×200) = 0.450 N/mm²
    fv,d = kmod×fv,k/γM = 0.80×4/1.3 = 2.462 N/mm²
    kcr·fv,d = 0.67×2.462 = 1.649 N/mm²
    τd/fv,d,eff = 0.450/1.649 = 0.273  →  PASS
    """

    def _ds(self):
        return design_strengths("C24", 2, "medium")

    def test_fm_d_value(self):
        ds = self._ds()
        assert ds["fm_d"] == pytest.approx(0.80 * 24.0 / 1.3, rel=1e-5)

    def test_bending_sigma_md_equals_9(self):
        ds = self._ds()
        r = beam_bending_check(6.0, 100.0, 200.0, ds["fm_d"])
        assert r["sigma_md_MPa"] == pytest.approx(9.0, rel=REL)

    def test_bending_utilization(self):
        ds = self._ds()
        fm_d = ds["fm_d"]
        r = beam_bending_check(6.0, 100.0, 200.0, fm_d)
        # utilization = sigma_md / fm_d = 9.0 / fm_d (uses the stored fm_d)
        assert r["utilization"] == pytest.approx(9.0 / fm_d, rel=REL)

    def test_bending_passes(self):
        ds = self._ds()
        r = beam_bending_check(6.0, 100.0, 200.0, ds["fm_d"])
        assert r["pass_"] is True

    def test_shear_tau_d(self):
        ds = self._ds()
        r = shear_check(6.0, 100.0, 200.0, ds["fv_d"])
        assert r["tau_d_MPa"] == pytest.approx(0.45, rel=REL)

    def test_shear_passes(self):
        ds = self._ds()
        r = shear_check(6.0, 100.0, 200.0, ds["fv_d"])
        assert r["pass_"] is True

    def test_shear_utilization(self):
        ds = self._ds()
        fv_d = ds["fv_d"]
        r = shear_check(6.0, 100.0, 200.0, fv_d)
        expected_util = 0.45 / (0.67 * fv_d)
        assert r["utilization"] == pytest.approx(expected_util, rel=REL)


# ===========================================================================
# 10. Published reference case: GL28h column
# ===========================================================================

class TestGL28hColumnReferenceCase:
    """
    GL28h column, b=h=140 mm (square), L=3 m, pin-pin.
    fc0,k=26.5 N/mm², E0,05=10 200 N/mm², βc=0.1 (glulam).

    i = 140/√12 = 40.415 mm
    λ_rel = (3000/40.415)·√(26.5/10200)/π

    Design values (SC2, medium): kmod=0.80, γM=1.25
    fc0,d = 0.80×26.5/1.25 = 16.96 N/mm²
    """

    def test_fc0_d_value(self):
        ds = design_strengths("GL28h", 2, "medium")
        assert ds["fc0_d"] == pytest.approx(0.80 * 26.5 / 1.25, rel=REL)

    def test_kc_positive_and_le_1(self):
        ds = design_strengths("GL28h", 2, "medium")
        r = column_buckling(3000, 140, 140, 26.5, 10200,
                            ds["fc0_d"], sigma_c0d=5.0, beta_c=0.1)
        assert r["ok"] is True
        assert 0.0 < r["kc"] <= 1.0

    def test_kc_fc0d_capacity(self):
        """kc·fc,0,d should be the usable capacity."""
        ds = design_strengths("GL28h", 2, "medium")
        fc0d = ds["fc0_d"]
        r = column_buckling(3000, 140, 140, 26.5, 10200,
                            fc0d, sigma_c0d=0.1, beta_c=0.1)
        # kc_fc0d_MPa is independently rounded; compare via formula
        expected_cap = r["kc"] * fc0d
        assert r["kc_fc0d_MPa"] == pytest.approx(expected_cap, rel=1e-5)

    def test_lambda_rel_formula(self):
        ds = design_strengths("GL28h", 2, "medium")
        r = column_buckling(3000, 140, 140, 26.5, 10200,
                            ds["fc0_d"], sigma_c0d=5.0, beta_c=0.1)
        i = 140.0 / math.sqrt(12.0)
        expected_lam = (3000.0 / i) * math.sqrt(26.5 / 10200.0) / math.pi
        assert r["lambda_rel_z"] == pytest.approx(expected_lam, rel=1e-4)

    def test_design_passes_moderate_load(self):
        """σc,0,d=8 N/mm² with GL28h 140×140 3m should pass."""
        ds = design_strengths("GL28h", 2, "medium")
        r = column_buckling(3000, 140, 140, 26.5, 10200,
                            ds["fc0_d"], sigma_c0d=8.0, beta_c=0.1)
        assert r["ok"] is True
        assert r["pass_"] is True


# ===========================================================================
# 11. LLM tool wrappers
# ===========================================================================

class TestLLMTools:

    def test_ec5_strength_class_happy(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_strength_class(ctx, _args(name="C24"))))
        assert d["fm_k"] == pytest.approx(24.0)

    def test_ec5_strength_class_gl28h(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_strength_class(ctx, _args(name="GL28h"))))
        assert d["gamma_M"] == pytest.approx(EC5_GAMMA_M_GLULAM)

    def test_ec5_strength_class_unknown(self):
        ctx = _ctx()
        _err(_run(run_ec5_strength_class(ctx, _args(name="C99"))))

    def test_ec5_strength_class_missing_name(self):
        ctx = _ctx()
        _err(_run(run_ec5_strength_class(ctx, _args())))

    def test_ec5_kmod_happy(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_kmod(ctx, _args(service_class=2, load_duration="medium"))))
        assert d["kmod"] == pytest.approx(0.80)

    def test_ec5_kmod_sc3_permanent(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_kmod(ctx, _args(service_class=3, load_duration="permanent"))))
        assert d["kmod"] == pytest.approx(0.50)

    def test_ec5_kmod_invalid_sc(self):
        ctx = _ctx()
        _err(_run(run_ec5_kmod(ctx, _args(service_class=9, load_duration="medium"))))

    def test_ec5_kmod_missing_sc(self):
        ctx = _ctx()
        _err(_run(run_ec5_kmod(ctx, _args(load_duration="medium"))))

    def test_ec5_design_strength_happy(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_design_strength(ctx, _args(
            strength_class="C24", service_class=2, load_duration="medium"
        ))))
        assert d["fm_d"] == pytest.approx(0.80 * 24.0 / 1.3, rel=1e-5)

    def test_ec5_design_strength_missing_sc(self):
        ctx = _ctx()
        _err(_run(run_ec5_design_strength(ctx, _args(
            service_class=2, load_duration="medium"
        ))))

    def test_ec5_beam_bending_happy(self):
        ctx = _ctx()
        ds = design_strengths("C24", 2, "medium")
        d = _ok(_run(run_ec5_beam_bending(ctx, _args(
            M_d_kNm=6.0, b_mm=100.0, h_mm=200.0, fm_d=ds["fm_d"]
        ))))
        assert d["pass_"] is True
        assert d["sigma_md_MPa"] == pytest.approx(9.0, rel=REL)

    def test_ec5_beam_bending_missing_M(self):
        ctx = _ctx()
        _err(_run(run_ec5_beam_bending(ctx, _args(
            b_mm=100.0, h_mm=200.0, fm_d=14.0
        ))))

    def test_ec5_beam_bending_bad_json(self):
        ctx = _ctx()
        raw = _run(run_ec5_beam_bending(ctx, b"bad-json"))
        d = json.loads(raw)
        # err_payload returns {"code": ..., "error": ...} or {"ok": False, ...}
        assert d.get("ok") is False or "error" in d or "code" in d

    def test_ec5_combined_nm_happy_compression(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_combined_nm(ctx, _args(
            sigma_c0d=5.0, fc0_d=14.0, sigma_md=3.0, fm_d=14.0, kc=0.8
        ))))
        expected = (5.0 / (0.8 * 14.0)) ** 2 + 3.0 / 14.0
        assert d["interaction"] == pytest.approx(expected, rel=REL)

    def test_ec5_combined_nm_tension_mode(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_combined_nm(ctx, _args(
            sigma_c0d=5.0, fc0_d=14.0, sigma_md=3.0, fm_d=14.0, tension=True
        ))))
        expected = 5.0 / 14.0 + 3.0 / 14.0
        assert d["interaction"] == pytest.approx(expected, rel=REL)

    def test_ec5_combined_nm_missing_field(self):
        ctx = _ctx()
        _err(_run(run_ec5_combined_nm(ctx, _args(
            sigma_c0d=5.0, fc0_d=14.0, fm_d=14.0  # missing sigma_md
        ))))

    def test_ec5_column_buckling_happy(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_column_buckling(ctx, _args(
            L_mm=3000, b_mm=140, h_mm=140,
            fc0_k=26.5, E0_05=10200,
            fc0_d=16.96, sigma_c0d=5.0, beta_c=0.1
        ))))
        assert 0.0 < d["kc"] <= 1.0
        assert "lambda_rel_z" in d

    def test_ec5_column_buckling_missing_field(self):
        ctx = _ctx()
        _err(_run(run_ec5_column_buckling(ctx, _args(
            L_mm=3000, b_mm=140, h_mm=140,
            fc0_k=26.5, E0_05=10200,
            fc0_d=16.96
            # missing sigma_c0d
        ))))

    def test_ec5_shear_happy(self):
        ctx = _ctx()
        ds = design_strengths("C24", 2, "medium")
        d = _ok(_run(run_ec5_shear(ctx, _args(
            V_d_kN=6.0, b_mm=100.0, h_mm=200.0, fv_d=ds["fv_d"]
        ))))
        assert d["pass_"] is True
        assert d["tau_d_MPa"] == pytest.approx(0.45, rel=REL)

    def test_ec5_shear_glulam_kcr(self):
        ctx = _ctx()
        d = _ok(_run(run_ec5_shear(ctx, _args(
            V_d_kN=3.0, b_mm=140.0, h_mm=280.0, fv_d=2.24, kcr=1.0
        ))))
        assert d["kcr"] == pytest.approx(1.0)

    def test_ec5_shear_missing_field(self):
        ctx = _ctx()
        _err(_run(run_ec5_shear(ctx, _args(
            b_mm=100.0, h_mm=200.0, fv_d=2.5  # missing V_d_kN
        ))))

    def test_ec5_shear_bad_json(self):
        ctx = _ctx()
        raw = _run(run_ec5_shear(ctx, b"not-json"))
        d = json.loads(raw)
        # err_payload returns {"code": ..., "error": ...} or {"ok": False, ...}
        assert d.get("ok") is False or "error" in d or "code" in d
