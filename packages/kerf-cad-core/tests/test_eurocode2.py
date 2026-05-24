"""
tests/test_eurocode2.py — EN 1992-1-1 (Eurocode 2) concrete design tests.

All calculations verified against:
  Mosley, Bungey & Hulse "Reinforced Concrete Design to Eurocode 2", 7th ed.
  EN 1992-1-1:2004 equations.

Units: SI (mm, MPa, kN, kN·m).

Author: imranparuk
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.concrete.eurocode2 import (
    EC2_GAMMA_C,
    EC2_GAMMA_S,
    EC2_ALPHA_CC,
    EC2_STRENGTH_CLASSES,
    ec2_design_strengths,
    ec2_flexure,
    ec2_shear_design,
    ec2_punching_shear,
    _fcd,
    _fyd,
    _lambda_eta,
    _xu_limit,
    _rho_min_beam_ec2,
    _rho_max_beam_ec2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def close(a, b, rel=0.01):
    """Check a ≈ b within rel relative tolerance."""
    return abs(a - b) / max(abs(b), 1e-9) <= rel


# ---------------------------------------------------------------------------
# Partial factors and constants
# ---------------------------------------------------------------------------

class TestPartialFactors:
    def test_gamma_C(self):
        assert EC2_GAMMA_C == pytest.approx(1.5)

    def test_gamma_S(self):
        assert EC2_GAMMA_S == pytest.approx(1.15)

    def test_alpha_cc_default(self):
        assert EC2_ALPHA_CC == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# fcd and fyd helpers
# ---------------------------------------------------------------------------

class TestDesignStrengths:
    def test_fcd_C30(self):
        # fcd = 1.0 * 30 / 1.5 = 20 MPa
        assert _fcd(30) == pytest.approx(20.0)

    def test_fcd_C25(self):
        assert _fcd(25) == pytest.approx(25.0 / 1.5, rel=1e-6)

    def test_fyd_500(self):
        # fyd = 500 / 1.15 ≈ 434.78 MPa
        assert _fyd(500) == pytest.approx(500.0 / 1.15, rel=1e-6)

    def test_fcd_with_alpha_085(self):
        # Some NADs use alpha_cc = 0.85
        assert _fcd(30, alpha_cc=0.85) == pytest.approx(0.85 * 30 / 1.5, rel=1e-6)

    def test_ec2_design_strengths_returns_dict(self):
        r = ec2_design_strengths(30, 500)
        assert "fcd_MPa" in r
        assert "fyd_MPa" in r
        assert r["fcd_MPa"] == pytest.approx(20.0)
        assert r["fyd_MPa"] == pytest.approx(500.0 / 1.15, rel=1e-4)


# ---------------------------------------------------------------------------
# Stress-block factors λ and η
# ---------------------------------------------------------------------------

class TestStressBlockFactors:
    def test_fck_leq_50_lambda(self):
        lam, eta = _lambda_eta(30)
        assert lam == pytest.approx(0.8)

    def test_fck_leq_50_eta(self):
        _, eta = _lambda_eta(30)
        assert eta == pytest.approx(1.0)

    def test_fck_60_lambda(self):
        # λ = 0.8 − (60−50)/400 = 0.8 − 0.025 = 0.775
        lam, _ = _lambda_eta(60)
        assert lam == pytest.approx(0.775)

    def test_fck_60_eta(self):
        # η = 1.0 − (60−50)/200 = 1.0 − 0.05 = 0.95
        _, eta = _lambda_eta(60)
        assert eta == pytest.approx(0.95)

    def test_xu_limit_low_strength(self):
        assert _xu_limit(30) == pytest.approx(0.45)

    def test_xu_limit_high_strength(self):
        assert _xu_limit(60) == pytest.approx(0.35)


# ---------------------------------------------------------------------------
# Strength classes table
# ---------------------------------------------------------------------------

class TestStrengthClassTable:
    def test_C30_fck(self):
        assert EC2_STRENGTH_CLASSES["C30/37"]["fck"] == 30

    def test_C30_fctm(self):
        assert EC2_STRENGTH_CLASSES["C30/37"]["fctm"] == pytest.approx(2.9)

    def test_C30_Ecm(self):
        assert EC2_STRENGTH_CLASSES["C30/37"]["Ecm"] == pytest.approx(32_000)

    def test_C90_exists(self):
        assert "C90/105" in EC2_STRENGTH_CLASSES

    def test_all_14_classes(self):
        # C12/15 … C90/105 = 14 classes
        assert len(EC2_STRENGTH_CLASSES) == 14


# ---------------------------------------------------------------------------
# Minimum / maximum steel ratios
# ---------------------------------------------------------------------------

class TestSteelRatios:
    def test_rho_min_C30_500(self):
        # fctm ≈ 0.3*30^(2/3) = 0.3*9.655 = 2.897; 0.26*2.897/500 = 0.001506
        rho_min = _rho_min_beam_ec2(30, 500)
        assert rho_min > 0.0013
        assert rho_min < 0.003

    def test_rho_max(self):
        assert _rho_max_beam_ec2() == pytest.approx(0.04)


# ---------------------------------------------------------------------------
# Flexure — textbook validation
# Beam: b=300 mm, d=500 mm, fck=30 MPa, fyk=500 MPa, MEd=300 kN·m
# Expected As ≈ 1500–1600 mm² (Mosley/Bungey/Hulse textbook range)
# ---------------------------------------------------------------------------

class TestFlexureTextbook:
    """Textbook benchmark: MBH7 §4.5, C30/37, B500, 300×500 beam at 300 kN·m."""

    @pytest.fixture
    def result(self):
        return ec2_flexure(b=300, d=500, fck=30, fyk=500, MEd=300)

    def test_As_in_textbook_range(self, result):
        As = result["As_req_mm2"]
        # Textbook gives ~1509–1600 mm² depending on assumptions
        assert 1450 <= As <= 1700, f"As={As:.0f} mm² outside textbook range [1450, 1700]"

    def test_As_within_1pct_of_reference(self, result):
        # High-precision reference: K = 300e6/(300*500²*20) = 0.2000
        # z/d = 0.5 + sqrt(0.25 - 0.2/1.0*(1/2)) ... use exact formula
        # fcd = 20 MPa, fyd = 434.78 MPa
        # K = 300e6/(300*500*500*20) = 0.2000
        # u = 1 - sqrt(1 - 2*0.2/1.0) = 1 - sqrt(0.6) = 1 - 0.7746 = 0.2254
        # z/d = 1 - 0.2254/2 = 0.8873 → z = 443.6 mm
        # As = 300e6 / (434.78 * 443.6) = 300e6 / 192860 = 1555 mm²
        fyd = 500 / 1.15
        K = 300e6 / (300 * 500**2 * 20)
        u = 1.0 - math.sqrt(1.0 - 2.0 * K / 1.0)   # eta=1
        z = (1.0 - u / 2.0) * 500
        z = min(z, 0.95 * 500)
        As_ref = 300e6 / (fyd * z)
        assert close(result["As_req_mm2"], As_ref, rel=0.01), (
            f"As={result['As_req_mm2']:.1f} vs ref={As_ref:.1f} (>1%)"
        )

    def test_singly_reinforced(self, result):
        assert result["doubly_reinforced"] is False

    def test_K_value(self, result):
        # K = 300e6 / (300 * 500² * 20) = 0.200
        assert result["K"] == pytest.approx(0.200, rel=0.001)

    def test_ductility_ok(self, result):
        assert result["ductility_ok"] is True

    def test_xu_d_below_limit(self, result):
        assert result["xu_d"] < 0.45

    def test_no_warnings(self, result):
        assert result["warnings"] == []


class TestFlexureDoublyReinforced:
    """Large moment that exceeds K' forces doubly-reinforced."""

    def test_doubly_reinforced_triggered(self):
        # Very large moment relative to section → K > K'
        # K' ≈ η·0.45·0.8·(1 - 0.45·0.8/2) = 1.0·0.36·(1-0.18) = 0.2952
        # Use MEd that gives K > 0.2952
        # K = MEd*1e6 / (300*500²*20); K=0.35 → MEd = 0.35*300*500²*20/1e6=525 kN·m
        r = ec2_flexure(b=300, d=500, fck=30, fyk=500, MEd=525, d2=50)
        assert r["doubly_reinforced"] is True

    def test_compression_steel_positive(self):
        r = ec2_flexure(b=300, d=500, fck=30, fyk=500, MEd=525, d2=50)
        assert r["As2_req_mm2"] > 0

    def test_tension_steel_larger(self):
        r = ec2_flexure(b=300, d=500, fck=30, fyk=500, MEd=525, d2=50)
        assert r["As_req_mm2"] > r["As2_req_mm2"]


class TestFlexureMinimumSteel:
    def test_very_small_moment_uses_min_steel(self):
        # MEd = 5 kN·m — computed As will be below As_min
        r = ec2_flexure(b=300, d=500, fck=30, fyk=500, MEd=5)
        assert "As_req" in str(r["warnings"]) or r["As_req_mm2"] > 0
        rho_min = _rho_min_beam_ec2(30, 500)
        As_min = rho_min * 300 * 500
        assert r["As_req_mm2"] >= As_min * 0.999


class TestFlexureHighStrength:
    def test_xu_limit_035_for_fck_60(self):
        r = ec2_flexure(b=400, d=600, fck=60, fyk=500, MEd=400)
        assert r["xu_d_limit"] == pytest.approx(0.35)


# ---------------------------------------------------------------------------
# Shear — VRd,c formula validation
# Same beam: bw=300, d=500, fck=30, fyk=500, As_l=1555 mm²
# ---------------------------------------------------------------------------

class TestShearNoReinforcement:
    """Validate VRd,c against hand calculation to <1%."""

    @pytest.fixture
    def result(self):
        return ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=100, As_l=1555
        )

    def _reference_VRdc(self) -> float:
        """Hand-calculated VRd,c (N)."""
        bw, d, fck = 300, 500, 30
        As_l = 1555
        CRd_c = 0.18 / 1.5          # = 0.12
        k = min(1.0 + math.sqrt(200.0 / d), 2.0)
        rho_l = min(As_l / (bw * d), 0.02)
        VRd_c_N = CRd_c * k * (100.0 * rho_l * fck) ** (1.0 / 3.0) * bw * d
        v_min = 0.035 * k ** 1.5 * fck ** 0.5
        VRd_c_min_N = v_min * bw * d
        return max(VRd_c_N, VRd_c_min_N)

    def test_VRd_c_formula_within_1pct(self, result):
        ref = self._reference_VRdc() / 1000.0   # kN
        assert close(result["VRd_c_kN"], ref, rel=0.01), (
            f"VRd,c={result['VRd_c_kN']:.2f} kN vs ref={ref:.2f} kN"
        )

    def test_CRd_c_value(self, result):
        assert result["CRd_c"] == pytest.approx(0.18 / 1.5, rel=1e-6)

    def test_k_size_factor(self, result):
        # d=500: k = 1 + sqrt(200/500) = 1 + 0.6325 = 1.6325
        k_ref = 1.0 + math.sqrt(200.0 / 500.0)
        assert result["k"] == pytest.approx(k_ref, rel=1e-5)

    def test_k_capped_at_2(self):
        # Very small d → k should be capped at 2
        r = ec2_shear_design(bw=100, d=50, fck=30, fyk=500, VEd=10, As_l=200)
        assert r["k"] == pytest.approx(2.0)

    def test_rho_l_value(self, result):
        rho_ref = 1555.0 / (300.0 * 500.0)
        assert result["rho_l"] == pytest.approx(rho_ref, rel=1e-5)

    def test_VRd_c_positive(self, result):
        assert result["VRd_c_kN"] > 0

    def test_no_stirrup_VRd_equals_VRdc(self, result):
        # Asw_s=0: VRd,kN should equal VRd,c
        assert result["VRd_kN"] == pytest.approx(result["VRd_c_kN"])

    def test_warning_if_VEd_exceeds_VRdc(self):
        # Force VEd >> VRd,c
        r = ec2_shear_design(bw=300, d=500, fck=30, fyk=500, VEd=500, As_l=1555)
        assert any("shear reinforcement required" in w for w in r["warnings"])


class TestShearWithReinforcement:
    """Stirrup-based VRd,s checks."""

    def test_VRd_s_positive(self):
        # Asw/s = 0.5 mm²/mm (e.g. 2×100 mm² legs / 400 mm spacing)
        r = ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=150,
            As_l=1555, Asw_s=0.5, theta_deg=21.8
        )
        assert r["VRd_s_kN"] > 0

    def test_VRd_s_formula(self):
        # VRd,s = (Asw/s) * z * fywd * cot(theta)
        Asw_s = 0.5
        theta = math.radians(21.8)
        z = 0.9 * 500
        fywd = 500 / 1.15
        VRd_s_ref = Asw_s * z * fywd * (1.0 / math.tan(theta)) / 1000.0

        r = ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=150,
            As_l=1555, Asw_s=Asw_s, theta_deg=21.8
        )
        assert close(r["VRd_s_kN"], VRd_s_ref, rel=0.01)

    def test_theta_out_of_range_clamped(self):
        r = ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=100,
            As_l=1555, Asw_s=0.3, theta_deg=10
        )
        assert any("21.8" in w for w in r["warnings"])

    def test_VRd_max_computed(self):
        r = ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=100,
            As_l=1555, Asw_s=0.5
        )
        assert r["VRd_max_kN"] > 0

    def test_Asw_s_min_positive(self):
        r = ec2_shear_design(bw=300, d=500, fck=30, fyk=500, VEd=100, As_l=1555)
        assert r["Asw_s_min"] > 0

    def test_adequate_flag_true_when_sufficient(self):
        r = ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=50,
            As_l=1555, Asw_s=1.0
        )
        assert r["adequate"] is True

    def test_adequate_flag_false_when_insufficient(self):
        r = ec2_shear_design(
            bw=300, d=500, fck=30, fyk=500, VEd=2000,
            As_l=1555, Asw_s=0.01
        )
        assert r["adequate"] is False


# ---------------------------------------------------------------------------
# Punching shear
# ---------------------------------------------------------------------------

class TestPunchingShear:
    """EN 1992-1-1 §6.4 punching shear."""

    @pytest.fixture
    def result(self):
        # Interior 400×400 column, d=200 mm, fck=30, rho_l=0.005, VEd=500 kN
        return ec2_punching_shear(
            bw=400, bh=400, d=200, fck=30, fyk=500,
            VEd=500, As_avg=0.005
        )

    def test_u1_formula(self, result):
        # u1 = 2*(400+400) + 2*pi*2*200 = 1600 + 2513.3 = 4113.3 mm
        u1_ref = 2.0 * (400 + 400) + 2.0 * math.pi * 2.0 * 200
        assert result["u1_mm"] == pytest.approx(u1_ref, rel=1e-6)

    def test_VRd_c_positive(self, result):
        assert result["VRd_c_kN"] > 0

    def test_vRd_c_formula(self, result):
        d = 200
        bw = bh = 400
        fck = 30
        rho_l = 0.005
        CRd_c = 0.18 / 1.5
        k = min(1.0 + math.sqrt(200 / d), 2.0)
        vRd_c = CRd_c * k * (100 * rho_l * fck) ** (1.0 / 3.0)
        v_min = 0.035 * k**1.5 * fck**0.5
        vRd_c = max(vRd_c, v_min)
        u1 = 2 * (bw + bh) + 2 * math.pi * 2 * d
        VRd_c_ref = vRd_c * u1 * d / 1000
        assert close(result["VRd_c_kN"], VRd_c_ref, rel=0.01)

    def test_beta_scales_VEd(self):
        r1 = ec2_punching_shear(400, 400, 200, 30, 500, 500, 0.005, beta=1.0)
        r2 = ec2_punching_shear(400, 400, 200, 30, 500, 500, 0.005, beta=1.15)
        assert r2["VEd_eff_kN"] == pytest.approx(1.15 * r1["VEd_eff_kN"], rel=1e-6)

    def test_adequate_small_VEd(self):
        r = ec2_punching_shear(400, 400, 200, 30, 500, 50, 0.005)
        assert r["adequate"] is True

    def test_inadequate_large_VEd(self):
        r = ec2_punching_shear(400, 400, 100, 30, 500, 5000, 0.005)
        assert r["adequate"] is False
        assert any("punching shear inadequate" in w for w in r["warnings"])


# ---------------------------------------------------------------------------
# Integration: flexure + shear for the same beam
# ---------------------------------------------------------------------------

class TestIntegration:
    """Consistent check using the textbook benchmark beam throughout."""

    def test_flexure_As_consistent_with_shear_rho(self):
        flex = ec2_flexure(b=300, d=500, fck=30, fyk=500, MEd=300)
        As = flex["As_req_mm2"]
        shear = ec2_shear_design(bw=300, d=500, fck=30, fyk=500, VEd=100, As_l=As)
        # rho_l in shear should match As/(bw*d)
        rho_expected = As / (300 * 500)
        assert shear["rho_l"] == pytest.approx(min(rho_expected, 0.02), rel=1e-4)
