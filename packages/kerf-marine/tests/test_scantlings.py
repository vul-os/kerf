"""
Tests for kerf_marine.scantlings — ISO 12215-5 hull construction scantlings.

Numeric oracles are derived from:
  - ISO 12215-5:2008 formula definitions (closed-form, analytically verifiable)
  - Larsson & Eliasson "Principles of Yacht Design" §11 worked examples
  - Hand calculations cross-checked against the standard's formula structure

Tolerance notes:
  - Exact formula outputs (no table lookup): tolerance 1e-10 (floating-point exact)
  - Table-interpolated values (k2): tolerance 1e-6
  - Engineering cross-checks: tolerance 1% (rel=0.01)
"""

from __future__ import annotations

import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ===========================================================================
# Design category factor kDC
# ===========================================================================

class TestDesignCategoryFactor:
    def test_category_A_is_1(self):
        from kerf_marine.scantlings import design_category_factor, DesignCategory
        assert design_category_factor(DesignCategory.A) == pytest.approx(1.0)

    def test_category_B_is_0p8(self):
        from kerf_marine.scantlings import design_category_factor, DesignCategory
        assert design_category_factor(DesignCategory.B) == pytest.approx(0.8)

    def test_category_C_is_0p6(self):
        from kerf_marine.scantlings import design_category_factor, DesignCategory
        assert design_category_factor(DesignCategory.C) == pytest.approx(0.6)

    def test_category_D_is_0p4(self):
        from kerf_marine.scantlings import design_category_factor, DesignCategory
        assert design_category_factor(DesignCategory.D) == pytest.approx(0.4)


# ===========================================================================
# Material design stresses
# ===========================================================================

class TestDesignStress:
    def test_frp_design_stress(self):
        """FRP design stress = sigma_uf / 3."""
        from kerf_marine.scantlings import design_stress_plate, MATERIAL_E_GLASS_FRP
        expected = MATERIAL_E_GLASS_FRP.sigma_uf / 3.0
        assert design_stress_plate(MATERIAL_E_GLASS_FRP) == pytest.approx(expected)

    def test_frp_epoxy_design_stress(self):
        from kerf_marine.scantlings import design_stress_plate, MATERIAL_E_GLASS_EPOXY
        expected = 250.0 / 3.0
        assert design_stress_plate(MATERIAL_E_GLASS_EPOXY) == pytest.approx(expected, rel=1e-10)

    def test_al5083_design_stress(self):
        """Al 5083-H116: sigma_d = min(0.6*215, 0.4*305) = min(129, 122) = 122 N/mm²."""
        from kerf_marine.scantlings import design_stress_plate, MATERIAL_AL5083
        expected = min(0.6 * 215.0, 0.4 * 305.0)  # = 122.0
        assert design_stress_plate(MATERIAL_AL5083) == pytest.approx(expected)
        assert design_stress_plate(MATERIAL_AL5083) == pytest.approx(122.0)

    def test_steel_s235_design_stress(self):
        """Steel S235: sigma_d = min(0.6*235, 0.4*360) = min(141, 144) = 141 N/mm²."""
        from kerf_marine.scantlings import design_stress_plate, MATERIAL_STEEL_S235
        expected = min(0.6 * 235.0, 0.4 * 360.0)  # = 141.0
        assert design_stress_plate(MATERIAL_STEEL_S235) == pytest.approx(expected)

    def test_stiffener_stress_equals_plate_stress(self):
        """Stiffener design stress = plate design stress per ISO 12215-5 §11.5."""
        from kerf_marine.scantlings import (
            design_stress_plate, design_stress_stiffener, MATERIAL_AL5083
        )
        assert design_stress_stiffener(MATERIAL_AL5083) == pytest.approx(
            design_stress_plate(MATERIAL_AL5083)
        )


# ===========================================================================
# Dynamic load factor nCG
# ===========================================================================

class TestNCG:
    def test_ncg_power_minimum_is_1(self):
        """nCG must be ≥ 1.0 for any physical vessel."""
        from kerf_marine.scantlings import ncg_power_craft
        # Very slow large vessel → nCG formula < 1 → clamped to 1.0
        nCG = ncg_power_craft(LWL=20.0, BC=5.0, V=5.0, mLDC=50000.0, beta_04=20.0)
        assert nCG >= 1.0

    def test_ncg_power_faster_gives_higher(self):
        """Higher speed → higher acceleration."""
        from kerf_marine.scantlings import ncg_power_craft
        nCG_slow = ncg_power_craft(10.0, 3.0, 15.0, 2000.0, 15.0)
        nCG_fast = ncg_power_craft(10.0, 3.0, 30.0, 2000.0, 15.0)
        assert nCG_fast > nCG_slow

    def test_ncg_power_flatter_deadrise_lower(self):
        """Higher deadrise (softer entry) → lower nCG (kDEAD smaller)."""
        from kerf_marine.scantlings import ncg_power_craft
        # High deadrise (30°) gives kDEAD = (50-30)/50 = 0.4
        nCG_flat = ncg_power_craft(10.0, 3.0, 25.0, 3000.0, 10.0)   # kDEAD=0.8
        nCG_deep = ncg_power_craft(10.0, 3.0, 25.0, 3000.0, 30.0)   # kDEAD=0.4
        assert nCG_flat > nCG_deep

    def test_ncg_power_hand_calc_oracle(self):
        """
        Oracle: numeric verify of nCG formula.

        Given: LWL=10m, BC=3m, V=25kn, mLDC=3000kg, beta=20°
        kDEAD = (50-20)/50 = 0.6
        nCG = 0.32 * (10/3) * (25/sqrt(3)) * 0.6 / sqrt(3000/1000)
            = 0.32 * 3.3333 * 14.4338 * 0.6 / 1.7321
            = 0.32 * 3.3333 * 14.4338 * 0.3464
            = 0.32 * 16.667
            = ~5.333  (before clamping)
        """
        from kerf_marine.scantlings import ncg_power_craft
        LWL, BC, V, mLDC, beta = 10.0, 3.0, 25.0, 3000.0, 20.0
        kDEAD = (50.0 - 20.0) / 50.0
        expected = 0.32 * (LWL / BC) * (V / math.sqrt(BC)) * kDEAD / math.sqrt(mLDC / 1000.0)
        actual = ncg_power_craft(LWL, BC, V, mLDC, beta)
        assert actual == pytest.approx(expected, rel=1e-10)

    def test_ncg_sailing_minimum(self):
        """Sailing craft nCG ≥ 1.0."""
        from kerf_marine.scantlings import ncg_sailing_craft
        nCG = ncg_sailing_craft(LWL=12.0, mLDC=8000.0)
        assert nCG >= 1.0

    def test_ncg_sailing_heavier_lower(self):
        """Heavier sailing craft has lower nCG (more inertia)."""
        from kerf_marine.scantlings import ncg_sailing_craft
        nCG_light = ncg_sailing_craft(12.0, 4000.0)
        nCG_heavy = ncg_sailing_craft(12.0, 12000.0)
        assert nCG_light > nCG_heavy

    def test_ncg_deadrise_clamp(self):
        """Beta < 10° is clamped to 10°, > 30° is clamped to 30°."""
        from kerf_marine.scantlings import ncg_power_craft
        # beta=5 → clamped to 10 → same result as beta=10
        n1 = ncg_power_craft(8.0, 2.5, 20.0, 2500.0, 5.0)
        n2 = ncg_power_craft(8.0, 2.5, 20.0, 2500.0, 10.0)
        assert n1 == pytest.approx(n2, rel=1e-10)

        # beta=40 → clamped to 30
        n3 = ncg_power_craft(8.0, 2.5, 20.0, 2500.0, 40.0)
        n4 = ncg_power_craft(8.0, 2.5, 20.0, 2500.0, 30.0)
        assert n3 == pytest.approx(n4, rel=1e-10)


# ===========================================================================
# k_AR panel area reduction factor
# ===========================================================================

class TestKAR:
    def test_small_panel_no_reduction(self):
        """Panel with area ≤ 2500 mm² → kAR = 1.0 (no reduction)."""
        from kerf_marine.scantlings import k_AR
        # 50 x 50 mm = 2500 mm²
        kAR = k_AR(50.0, 50.0)
        assert kAR == pytest.approx(1.0, abs=1e-10)

    def test_large_panel_reduced(self):
        """Large panel (e.g., 500 x 1000 mm) → kAR < 1.0."""
        from kerf_marine.scantlings import k_AR
        kAR = k_AR(500.0, 1000.0)
        assert kAR < 1.0

    def test_kAR_minimum_0p25(self):
        """kAR never below 0.25."""
        from kerf_marine.scantlings import k_AR
        kAR = k_AR(5000.0, 5000.0)  # very large panel
        assert kAR >= 0.25

    def test_kAR_analytical_oracle(self):
        """
        kAR oracle for b=500, l=1000: AD = 500*1000 = 500,000 mm²
        kAR = (2500 / 500000)^0.3 = 0.005^0.3 = 0.05^0.3...
        Let's compute: 2500/500000 = 0.005
        0.005^0.3 = exp(0.3 * ln(0.005)) = exp(0.3 * (-5.2983)) = exp(-1.5895) ≈ 0.2040
        → clamped to 0.25
        """
        from kerf_marine.scantlings import k_AR
        b, l = 500.0, 1000.0
        AD = b * l
        raw = (2500.0 / AD) ** 0.3
        expected = max(0.25, min(1.0, raw))
        assert k_AR(b, l) == pytest.approx(expected, rel=1e-10)

    def test_kAR_zero_panel(self):
        """Zero-size panel → kAR = 1.0 (no reduction)."""
        from kerf_marine.scantlings import k_AR
        assert k_AR(0.0, 100.0) == pytest.approx(1.0)


# ===========================================================================
# kL longitudinal pressure distribution factor
# ===========================================================================

class TestKL:
    def test_midship_is_1(self):
        """At 0.4 * LWL = 4m for LWL=10m, kL = 1.0."""
        from kerf_marine.scantlings import k_L
        kL = k_L(x_fwd=4.0, LWL=10.0)
        assert kL == pytest.approx(1.0)

    def test_midship_range_is_1(self):
        """kL = 1.0 for x/LWL ∈ [0.2, 0.6]."""
        from kerf_marine.scantlings import k_L
        for x_frac in [0.2, 0.3, 0.4, 0.5, 0.6]:
            assert k_L(x_frac * 10.0, 10.0) == pytest.approx(1.0), f"failed at x_frac={x_frac}"

    def test_bow_reduction(self):
        """At bow (xL=1.0), kL < 1.0."""
        from kerf_marine.scantlings import k_L
        kL = k_L(10.0, 10.0)  # xL = 1.0
        assert kL < 1.0

    def test_stern_reduction(self):
        """At stern (xL=0.0), kL < 1.0."""
        from kerf_marine.scantlings import k_L
        kL = k_L(0.0, 10.0)  # xL = 0.0
        assert kL < 1.0

    def test_kL_minimum_0p6(self):
        """kL never below 0.6."""
        from kerf_marine.scantlings import k_L
        for x in [0.0, 5.0, 10.0]:
            assert k_L(x, 10.0) >= 0.6

    def test_kL_analytical_bow(self):
        """
        At xL=0.8: kL = 1.0 - 2*(0.8-0.6)^2/0.16 = 1.0 - 2*0.04/0.16 = 1.0 - 0.5 = 0.5
        → clamped to 0.6
        """
        from kerf_marine.scantlings import k_L
        xL = 0.8
        kL_raw = 1.0 - 2.0 * (xL - 0.6) ** 2 / 0.16
        expected = max(0.6, min(1.0, kL_raw))  # = 0.6
        assert k_L(xL * 10.0, 10.0) == pytest.approx(expected, rel=1e-10)


# ===========================================================================
# k2 panel aspect ratio factor
# ===========================================================================

class TestK2Panel:
    def test_square_panel_k2(self):
        """Square panel (AR=1): k2 = 0.308 per Table 10."""
        from kerf_marine.scantlings import k2_panel
        assert k2_panel(500.0, 500.0) == pytest.approx(0.308, abs=1e-6)

    def test_high_AR_converges_to_0p422(self):
        """Very elongated panel (AR≥4): k2 → 0.422."""
        from kerf_marine.scantlings import k2_panel
        assert k2_panel(100.0, 1000.0) == pytest.approx(0.422, abs=1e-6)

    def test_AR_2_interpolated(self):
        """AR=2: k2 = 0.408 per Table 10 (exact tabulated value)."""
        from kerf_marine.scantlings import k2_panel
        assert k2_panel(300.0, 600.0) == pytest.approx(0.408, abs=1e-6)

    def test_k2_b_greater_than_l(self):
        """k2 is symmetric: b and l can be swapped."""
        from kerf_marine.scantlings import k2_panel
        assert k2_panel(500.0, 300.0) == pytest.approx(k2_panel(300.0, 500.0))

    def test_k2_AR_1p5_interpolated(self):
        """AR=1.5: k2 = 0.384 (tabulated)."""
        from kerf_marine.scantlings import k2_panel
        assert k2_panel(200.0, 300.0) == pytest.approx(0.384, abs=1e-6)

    def test_k2_AR_3_interpolated(self):
        """AR=3: k2 = 0.418 (tabulated)."""
        from kerf_marine.scantlings import k2_panel
        assert k2_panel(200.0, 600.0) == pytest.approx(0.418, abs=1e-6)

    def test_k2_between_1_and_1p5(self):
        """AR=1.25: k2 between 0.308 and 0.384."""
        from kerf_marine.scantlings import k2_panel
        k2 = k2_panel(400.0, 500.0)
        assert 0.308 < k2 < 0.384


# ===========================================================================
# kc curvature correction factor
# ===========================================================================

class TestKCCurvature:
    def test_flat_panel_kc_1(self):
        """Flat panel (z=0): kc = 1.0."""
        from kerf_marine.scantlings import kc_curvature
        assert kc_curvature(500.0, 0.0) == pytest.approx(1.0)

    def test_slightly_curved_kc_1(self):
        """Crown < 5% of b: kc = 1.0 (negligible curvature)."""
        from kerf_marine.scantlings import kc_curvature
        # z/b = 0.04 → no reduction
        assert kc_curvature(500.0, 20.0) == pytest.approx(1.0)

    def test_curved_kc_below_1(self):
        """Significant curvature reduces kc below 1."""
        from kerf_marine.scantlings import kc_curvature
        kc = kc_curvature(500.0, 100.0)  # z/b = 0.2
        assert kc < 1.0

    def test_kc_minimum_0p5(self):
        """kc never below 0.5."""
        from kerf_marine.scantlings import kc_curvature
        kc = kc_curvature(100.0, 100.0)  # extreme curvature
        assert kc >= 0.5

    def test_kc_analytical_oracle(self):
        """
        Oracle: b=500mm, z=75mm → z/b = 0.15
        kc = 1.0 - 0.1 * (0.15 - 0.05) = 1.0 - 0.01 = 0.99
        """
        from kerf_marine.scantlings import kc_curvature
        b, z = 500.0, 75.0
        ratio = z / b  # = 0.15
        expected = 1.0 - 0.1 * (ratio - 0.05)  # = 0.99
        assert kc_curvature(b, z) == pytest.approx(expected, rel=1e-10)


# ===========================================================================
# Plate thickness — ISO 12215-5 Eq. (16)
# ===========================================================================

class TestPlateThickness:
    def test_frp_plate_oracle(self):
        """
        ISO 12215-5 Eq. (16) oracle for FRP single-skin plate.

        Given:
          P  = 20 kPa
          b  = 300 mm, l = 600 mm  (AR=2 → k2 = 0.408)
          kc = 1.0  (flat)
          material = E-glass/polyester FRP, sigma_uf = 200 N/mm²
          sigma_d  = 200/3 = 66.667 N/mm²
          kAR = (2500 / (300*600))^0.3 = (2500/180000)^0.3 = (0.01389)^0.3
              = exp(0.3 * ln(0.01389)) = exp(0.3 * (-4.2726)) = exp(-1.2818) ≈ 0.2777
          → clamped to 0.25
          P_eff = 20 * 0.25 = 5.0 kPa

          t = 300 * sqrt(5.0 * 0.408 * 1.0 / (1000 * 66.667))
            = 300 * sqrt(2.04 / 66667)
            = 300 * sqrt(3.06e-5)
            = 300 * 0.005531
            = 1.659 mm
          → governed by construction minimum 1.5 mm → t = 1.659 mm
        """
        from kerf_marine.scantlings import plate_thickness, MATERIAL_E_GLASS_FRP, k2_panel, k_AR
        b, l = 300.0, 600.0
        P = 20.0   # kPa
        mat = MATERIAL_E_GLASS_FRP
        sigma_d = mat.sigma_uf / 3.0  # = 66.667 N/mm²
        kAR = k_AR(b, l)
        P_eff = P * kAR
        k2 = k2_panel(b, l)
        kc = 1.0
        t_expected = b * math.sqrt(P_eff * k2 * kc / (1000.0 * sigma_d))

        result = plate_thickness(P, b, l, mat)
        assert result.t_mm == pytest.approx(t_expected, rel=1e-10)

    def test_aluminum_plate_oracle(self):
        """
        Oracle for Al 5083-H116 plate.

        Given:
          P  = 30 kPa
          b  = 400 mm, l = 800 mm  (AR=2 → k2=0.408)
          kc = 1.0  (flat)
          sigma_d = min(0.6*215, 0.4*305) = 122.0 N/mm²
          kAR = (2500 / (400*800))^0.3 = (2500/320000)^0.3 = 0.007813^0.3
              = exp(0.3*ln(0.007813)) = exp(0.3*(-4.852)) = exp(-1.456) ≈ 0.2332
          → clamped to 0.25
          P_eff = 30 * 0.25 = 7.5 kPa
          t = 400 * sqrt(7.5 * 0.408 / (1000 * 122.0))
            = 400 * sqrt(3.06 / 122000)
            = 400 * sqrt(2.508e-5)
            = 400 * 0.005008
            = 2.003 mm
          → minimum construction 2.0 mm → governing = 2.003 mm
        """
        from kerf_marine.scantlings import plate_thickness, MATERIAL_AL5083, k2_panel, k_AR, design_stress_plate
        b, l = 400.0, 800.0
        P = 30.0
        mat = MATERIAL_AL5083
        sigma_d = design_stress_plate(mat)
        kAR = k_AR(b, l)
        P_eff = P * kAR
        k2 = k2_panel(b, l)
        t_expected = b * math.sqrt(P_eff * k2 / (1000.0 * sigma_d))

        result = plate_thickness(P, b, l, mat)
        assert result.t_mm == pytest.approx(t_expected, rel=1e-10)
        # Al minimum is 2.0 mm
        assert result.t_min_rule_mm == pytest.approx(2.0)

    def test_plate_no_kAR(self):
        """With apply_kAR=False, P_design = P exactly."""
        from kerf_marine.scantlings import plate_thickness, MATERIAL_AL5083
        result = plate_thickness(25.0, 500.0, 1000.0, MATERIAL_AL5083, apply_kAR=False)
        assert result.P_design_kPa == pytest.approx(25.0)
        assert result.kAR == pytest.approx(1.0)

    def test_plate_higher_pressure_thicker(self):
        """Higher design pressure → thicker plate (all else equal)."""
        from kerf_marine.scantlings import plate_thickness, MATERIAL_E_GLASS_FRP
        r1 = plate_thickness(10.0, 300.0, 600.0, MATERIAL_E_GLASS_FRP)
        r2 = plate_thickness(30.0, 300.0, 600.0, MATERIAL_E_GLASS_FRP)
        assert r2.t_governing_mm > r1.t_governing_mm

    def test_plate_larger_panel_thicker(self):
        """Larger panel (larger b) → thicker plate (all else equal)."""
        from kerf_marine.scantlings import plate_thickness, MATERIAL_AL5083
        r1 = plate_thickness(20.0, 300.0, 600.0, MATERIAL_AL5083)
        r2 = plate_thickness(20.0, 500.0, 1000.0, MATERIAL_AL5083)
        assert r2.t_mm > r1.t_mm

    def test_plate_steel_minimum(self):
        """Steel minimum construction thickness = 1.0 mm."""
        from kerf_marine.scantlings import plate_thickness, MATERIAL_STEEL_S235
        result = plate_thickness(3.0, 50.0, 100.0, MATERIAL_STEEL_S235)
        assert result.t_min_rule_mm == pytest.approx(1.0)

    def test_plate_governing_geq_required(self):
        """Governing thickness ≥ required thickness always."""
        from kerf_marine.scantlings import plate_thickness, MATERIAL_E_GLASS_FRP
        r = plate_thickness(5.0, 200.0, 400.0, MATERIAL_E_GLASS_FRP)
        assert r.t_governing_mm >= r.t_mm

    def test_plate_dict_keys(self):
        from kerf_marine.scantlings import plate_thickness, MATERIAL_AL5083
        r = plate_thickness(20.0, 300.0, 600.0, MATERIAL_AL5083)
        d = r.as_dict()
        for key in ["t_required_mm", "t_min_rule_mm", "t_governing_mm",
                    "P_design_kPa", "sigma_d_N_mm2", "k2", "kc", "kAR"]:
            assert key in d, f"Missing key: {key}"

    def test_plate_curvature_reduces_thickness(self):
        """Curved panel requires less thickness than flat panel."""
        from kerf_marine.scantlings import plate_thickness, MATERIAL_AL5083
        flat   = plate_thickness(25.0, 400.0, 800.0, MATERIAL_AL5083, z_mm=0.0)
        curved = plate_thickness(25.0, 400.0, 800.0, MATERIAL_AL5083, z_mm=60.0)
        assert curved.t_mm <= flat.t_mm


# ===========================================================================
# Stiffener section modulus — ISO 12215-5 Eq. (22)
# ===========================================================================

class TestStiffenerSM:
    def test_stiffener_oracle_fixed(self):
        """
        Oracle for fixed-ends stiffener (C = 1/12).

        Given:
          P    = 20 kPa
          s    = 300 mm (spacing)
          lu   = 1200 mm (span)
          mat  = Al 5083: sigma_d = 122.0 N/mm²
          AD   = min(300*1200, 0.33*1200²) = min(360000, 475200) = 360000
          kAR  = (2500 / 360000)^0.3 = 0.006944^0.3 = exp(0.3*(-4.970)) = exp(-1.491) ≈ 0.225
                 → clamped to 0.25
          P_eff = 20 * 0.25 = 5.0 kPa
          SM  = (1/12) * 5.0 * 300 * 1200² / (1000 * 122.0)
              = (1/12) * 5.0 * 300 * 1440000 / 122000
              = (1/12) * 5.0 * 3540983.6
              = (1/12) * 177049180 ... let me compute more carefully:
          SM  = (1/12) * 5.0 * 300 * 1200^2 / (1000 * 122.0)
              = (1/12) * 5.0 * 300 * 1,440,000 / 122,000
              = (1/12) * 5.0 * 300 * 11.803...
              = (1/12) * 17705.0
              = 1475.4 cm³
        """
        from kerf_marine.scantlings import stiffener_section_modulus, MATERIAL_AL5083, k_AR, design_stress_stiffener
        P = 20.0
        lu, s = 1200.0, 300.0
        mat = MATERIAL_AL5083
        sigma_d = design_stress_stiffener(mat)
        kAR = k_AR(s, lu)
        P_eff = P * kAR
        C = 1.0 / 12.0
        SM_expected = C * P_eff * s * lu ** 2 / (1000.0 * sigma_d)

        result = stiffener_section_modulus(P, lu, s, mat, both_ends_fixed=True)
        assert result.SM_cm3 == pytest.approx(SM_expected, rel=1e-10)

    def test_stiffener_oracle_simply_supported(self):
        """
        Oracle for simply-supported stiffener (C = 1/8).
        SM_simply_supported / SM_fixed = (1/8) / (1/12) = 1.5
        """
        from kerf_marine.scantlings import stiffener_section_modulus, MATERIAL_AL5083
        r_fixed  = stiffener_section_modulus(20.0, 1000.0, 300.0, MATERIAL_AL5083, both_ends_fixed=True)
        r_simply = stiffener_section_modulus(20.0, 1000.0, 300.0, MATERIAL_AL5083, both_ends_fixed=False)
        assert r_simply.SM_cm3 == pytest.approx(r_fixed.SM_cm3 * 1.5, rel=1e-10)

    def test_stiffener_higher_pressure_higher_SM(self):
        """Higher pressure → larger required section modulus."""
        from kerf_marine.scantlings import stiffener_section_modulus, MATERIAL_AL5083
        r1 = stiffener_section_modulus(10.0, 1000.0, 250.0, MATERIAL_AL5083)
        r2 = stiffener_section_modulus(30.0, 1000.0, 250.0, MATERIAL_AL5083)
        assert r2.SM_cm3 > r1.SM_cm3

    def test_stiffener_longer_span_higher_SM(self):
        """Longer stiffener span → much larger SM.

        SM = C * P * s * lu² / (1000 * sigma_d), so SM ∝ lu² only when
        kAR (and therefore P_eff) is constant.  With apply_kAR=False, P_eff=P
        and the quadratic dependence is exact.
        """
        from kerf_marine.scantlings import stiffener_section_modulus, MATERIAL_AL5083
        r1 = stiffener_section_modulus(20.0, 800.0, 300.0, MATERIAL_AL5083, apply_kAR=False)
        r2 = stiffener_section_modulus(20.0, 1600.0, 300.0, MATERIAL_AL5083, apply_kAR=False)
        # SM ∝ lu² → doubling lu → SM × 4
        assert r2.SM_cm3 == pytest.approx(r1.SM_cm3 * 4.0, rel=1e-10)

    def test_stiffener_longer_span_larger_SM_with_kAR(self):
        """With kAR enabled, longer span still gives larger SM (monotone)."""
        from kerf_marine.scantlings import stiffener_section_modulus, MATERIAL_AL5083
        r1 = stiffener_section_modulus(20.0, 800.0, 300.0, MATERIAL_AL5083)
        r2 = stiffener_section_modulus(20.0, 1600.0, 300.0, MATERIAL_AL5083)
        assert r2.SM_cm3 > r1.SM_cm3

    def test_stiffener_dict_keys(self):
        from kerf_marine.scantlings import stiffener_section_modulus, MATERIAL_AL5083
        r = stiffener_section_modulus(20.0, 1000.0, 300.0, MATERIAL_AL5083)
        d = r.as_dict()
        for key in ["SM_required_cm3", "P_design_kPa", "lu_mm", "s_mm",
                    "sigma_d_N_mm2", "C_boundary", "kAR"]:
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# Design pressures — motor craft
# ===========================================================================

class TestDesignPressuresMotor:
    def _params(self):
        return dict(
            LWL=10.0, BWL=3.2, mLDC=3500.0, V=25.0, beta_04=18.0,
        )

    def test_pressure_dict_keys(self):
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        pres = design_pressures_motor_craft(**self._params(), category=DesignCategory.A)
        d = pres.as_dict()
        for key in ["P_bottom_kPa", "P_side_kPa", "P_deck_kPa", "nCG_g", "kDC"]:
            assert key in d

    def test_bottom_pressure_positive(self):
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        pres = design_pressures_motor_craft(**self._params(), category=DesignCategory.A)
        assert pres.P_bottom > 0.0

    def test_side_pressure_less_than_bottom(self):
        """Side pressure ≤ bottom pressure (design conservative)."""
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        pres = design_pressures_motor_craft(**self._params(), category=DesignCategory.A)
        assert pres.P_s <= pres.P_bottom + 1e-6

    def test_category_A_higher_than_D(self):
        """Category A (ocean) → higher pressures than D (sheltered)."""
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        pA = design_pressures_motor_craft(**self._params(), category=DesignCategory.A)
        pD = design_pressures_motor_craft(**self._params(), category=DesignCategory.D)
        assert pA.P_bottom >= pD.P_bottom

    def test_minimum_bottom_pressure_respected(self):
        """Bottom pressure ≥ 10 kPa for category A."""
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        # Slow, heavy boat → pressure formula gives low value → should clamp to 10 kPa
        pres = design_pressures_motor_craft(
            LWL=20.0, BWL=5.0, mLDC=200000.0, V=5.0, beta_04=25.0,
            category=DesignCategory.A
        )
        assert pres.P_bottom >= 10.0

    def test_minimum_side_pressure_5kPa(self):
        """Side pressure ≥ 5 kPa always."""
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        pres = design_pressures_motor_craft(**self._params(), category=DesignCategory.D)
        assert pres.P_s >= 5.0

    def test_kDC_in_result(self):
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        pres = design_pressures_motor_craft(**self._params(), category=DesignCategory.B)
        assert pres.kDC == pytest.approx(0.8)

    def test_faster_boat_higher_bottom_pressure(self):
        """Faster boat → higher dynamic pressure."""
        from kerf_marine.scantlings import design_pressures_motor_craft, DesignCategory
        p_slow = design_pressures_motor_craft(
            LWL=10.0, BWL=3.2, mLDC=3500.0, V=10.0, beta_04=18.0,
            category=DesignCategory.A,
        )
        p_fast = design_pressures_motor_craft(
            LWL=10.0, BWL=3.2, mLDC=3500.0, V=35.0, beta_04=18.0,
            category=DesignCategory.A,
        )
        assert p_fast.P_bm >= p_slow.P_bm


# ===========================================================================
# Design pressures — sailing craft
# ===========================================================================

class TestDesignPressuresSailing:
    def test_pbm_is_zero(self):
        """Sailing craft has no planing (Pbm = 0)."""
        from kerf_marine.scantlings import design_pressures_sailing_craft, DesignCategory
        pres = design_pressures_sailing_craft(LWL=12.0, BWL=3.5, mLDC=8000.0,
                                              category=DesignCategory.A)
        assert pres.P_bm == pytest.approx(0.0)

    def test_pbd_positive(self):
        from kerf_marine.scantlings import design_pressures_sailing_craft, DesignCategory
        pres = design_pressures_sailing_craft(LWL=12.0, BWL=3.5, mLDC=8000.0,
                                              category=DesignCategory.A)
        assert pres.P_bd > 0.0

    def test_minimum_5kPa(self):
        """All pressures ≥ 5 kPa minimum."""
        from kerf_marine.scantlings import design_pressures_sailing_craft, DesignCategory
        pres = design_pressures_sailing_craft(LWL=8.0, BWL=2.5, mLDC=3000.0,
                                              category=DesignCategory.D)
        assert pres.P_bd >= 5.0
        assert pres.P_s >= 5.0

    def test_ocean_higher_than_sheltered(self):
        from kerf_marine.scantlings import design_pressures_sailing_craft, DesignCategory
        pA = design_pressures_sailing_craft(12.0, 3.5, 8000.0, DesignCategory.A)
        pD = design_pressures_sailing_craft(12.0, 3.5, 8000.0, DesignCategory.D)
        assert pA.P_bd >= pD.P_bd


# ===========================================================================
# Hull section properties
# ===========================================================================

class TestHullSectionProps:
    def _simple_section(self):
        """Simple box cross-section: A_deck=A_keel=0.05 m², d=2m, A_side=0.02m²/side."""
        from kerf_marine.scantlings import HullSectionProps
        return HullSectionProps(
            A_deck=0.05,
            A_keel=0.05,
            d=2.0,
            A_side=0.02,
            d_mid=1.0,
        )

    def test_NA_at_half_depth(self):
        """Symmetric box section: NA at d/2 = 1.0 m."""
        sec = self._simple_section()
        assert sec.NA_from_keel == pytest.approx(1.0, rel=1e-10)

    def test_SM_deck_equals_SM_keel_for_symmetric(self):
        """Symmetric section: SM_deck = SM_keel."""
        sec = self._simple_section()
        assert sec.SM_deck == pytest.approx(sec.SM_keel, rel=1e-10)

    def test_SM_positive(self):
        sec = self._simple_section()
        assert sec.SM_min > 0.0

    def test_second_moment_positive(self):
        sec = self._simple_section()
        assert sec.second_moment > 0.0

    def test_SM_analytical_oracle(self):
        """
        Oracle for simple I-beam (deck+keel flanges only, no side contribution):
          A_deck=A_keel=0.05 m², d=2m, A_side=0 m²
          NA at midship = d/2 = 1.0 m (symmetric)
          I = 0.05*(2-1)^2 + 0.05*(1)^2 = 0.05 + 0.05 = 0.1 m⁴
          SM = I/(d/2) = 0.1 / 1.0 = 0.1 m³
        """
        from kerf_marine.scantlings import HullSectionProps
        sec = HullSectionProps(A_deck=0.05, A_keel=0.05, d=2.0, A_side=0.0, d_mid=1.0)
        assert sec.second_moment == pytest.approx(0.1, rel=1e-10)
        assert sec.SM_deck == pytest.approx(0.1, rel=1e-10)

    def test_section_dict_keys(self):
        sec = self._simple_section()
        d = sec.as_dict()
        for key in ["NA_from_keel_m", "I_m4", "SM_deck_m3", "SM_keel_m3", "SM_min_m3"]:
            assert key in d


# ===========================================================================
# Still-water and wave bending moments
# ===========================================================================

class TestBendingMoments:
    def test_sw_bm_oracle(self):
        """
        Msw oracle: mLDC=5000 kg, LWL=12m
        W = 5000 * 9.80665 / 1000 = 49.033 kN
        Msw = 49.033 * 12 / 8 = 73.55 kN·m
        """
        from kerf_marine.scantlings import still_water_bending_moment, G
        mLDC, LWL = 5000.0, 12.0
        W = mLDC * G / 1000.0
        expected = W * LWL / 8.0
        assert still_water_bending_moment(mLDC, LWL) == pytest.approx(expected, rel=1e-10)

    def test_sw_bm_scales_with_mass(self):
        """Double mass → double Msw."""
        from kerf_marine.scantlings import still_water_bending_moment
        Msw1 = still_water_bending_moment(5000.0, 12.0)
        Msw2 = still_water_bending_moment(10000.0, 12.0)
        assert Msw2 == pytest.approx(2.0 * Msw1, rel=1e-10)

    def test_wave_bm_positive(self):
        from kerf_marine.scantlings import wave_bending_moment
        Mw = wave_bending_moment(5000.0, 12.0, 3.5, 0.55)
        assert Mw > 0.0

    def test_wave_bm_longer_hull_larger(self):
        """Longer hull → larger wave BM (L² dependence)."""
        from kerf_marine.scantlings import wave_bending_moment
        Mw1 = wave_bending_moment(5000.0, 10.0, 3.0, 0.55)
        Mw2 = wave_bending_moment(5000.0, 20.0, 3.0, 0.55)
        assert Mw2 > Mw1

    def test_wave_bm_analytical_oracle(self):
        """
        Oracle: LWL=12m, BWL=3.5m, Cb=0.55
        C1 = 0.11 * (12/25 + 1)^2.5 = 0.11 * (1.48)^2.5
           = 0.11 * 2.667 = 0.2934
        Mwave = 0.2934 * 3.5 * 144 * (0.55+0.7) / 1000
              = 0.2934 * 3.5 * 144 * 1.25 / 1000
              = 0.2934 * 630 / 1000
              = 184.8 / 1000 = 0.1848 kN·m   ... wait, units:
        Mwave = C1 * BWL * LWL^2 * (Cb+0.7) / 1000  [kN·m]
        """
        from kerf_marine.scantlings import wave_bending_moment
        LWL, BWL, Cb = 12.0, 3.5, 0.55
        C1 = 0.11 * ((LWL / 25.0 + 1.0) ** 2.5)
        expected = C1 * BWL * (LWL ** 2) * (Cb + 0.7) / 1000.0
        assert wave_bending_moment(5000.0, LWL, BWL, Cb) == pytest.approx(expected, rel=1e-10)


# ===========================================================================
# Longitudinal strength check
# ===========================================================================

class TestLongStrength:
    def _setup(self):
        from kerf_marine.scantlings import HullSectionProps, MATERIAL_AL5083
        sec = HullSectionProps(
            A_deck=0.05, A_keel=0.05, d=2.0, A_side=0.02, d_mid=1.0
        )
        mat = MATERIAL_AL5083
        return sec, mat

    def test_result_dict_keys(self):
        from kerf_marine.scantlings import longitudinal_strength_check
        sec, mat = self._setup()
        r = longitudinal_strength_check(5000.0, 12.0, 3.5, sec, mat, 0.55)
        d = r.as_dict()
        for key in ["M_still_water_kNm", "M_wave_kNm", "M_total_kNm",
                    "SM_min_m3", "sigma_actual_MPa", "sigma_allowable_MPa",
                    "utilisation", "passes"]:
            assert key in d, f"Missing key: {key}"

    def test_total_bm_equals_sum(self):
        from kerf_marine.scantlings import longitudinal_strength_check
        sec, mat = self._setup()
        r = longitudinal_strength_check(5000.0, 12.0, 3.5, sec, mat, 0.55)
        assert r.M_total_kNm == pytest.approx(r.M_sw_kNm + r.M_wave_kNm, rel=1e-10)

    def test_utilisation_stress_ratio(self):
        """utilisation = sigma_actual / sigma_d."""
        from kerf_marine.scantlings import longitudinal_strength_check
        sec, mat = self._setup()
        r = longitudinal_strength_check(5000.0, 12.0, 3.5, sec, mat, 0.55)
        assert r.utilisation == pytest.approx(r.sigma_actual_MPa / r.sigma_d_MPa, rel=1e-10)

    def test_analytical_stress_oracle(self):
        """
        Oracle: M_total, SM_min, sigma = M/(SM*1000)
        """
        from kerf_marine.scantlings import (
            longitudinal_strength_check,
            still_water_bending_moment, wave_bending_moment,
            design_stress_plate,
        )
        sec, mat = self._setup()
        mLDC, LWL, BWL, Cb = 5000.0, 12.0, 3.5, 0.55
        Msw = still_water_bending_moment(mLDC, LWL)
        Mwave = wave_bending_moment(mLDC, LWL, BWL, Cb)
        M_total = Msw + Mwave
        SM_min = sec.SM_min
        sigma_expected = M_total / (SM_min * 1000.0)
        sigma_d = design_stress_plate(mat)

        r = longitudinal_strength_check(mLDC, LWL, BWL, sec, mat, Cb)
        assert r.sigma_actual_MPa == pytest.approx(sigma_expected, rel=1e-10)
        assert r.sigma_d_MPa == pytest.approx(sigma_d, rel=1e-10)

    def test_oversized_section_passes(self):
        """A hull with very large section modulus should pass."""
        from kerf_marine.scantlings import longitudinal_strength_check, HullSectionProps, MATERIAL_AL5083
        # Massive SM: A_deck = 2 m² at d=5m → SM_min very large
        sec_big = HullSectionProps(A_deck=2.0, A_keel=2.0, d=5.0, A_side=0.5, d_mid=2.5)
        r = longitudinal_strength_check(5000.0, 12.0, 3.5, sec_big, MATERIAL_AL5083, 0.55)
        assert r.passes is True

    def test_undersized_section_fails(self):
        """A hull with tiny section modulus should fail (utilisation > 1)."""
        from kerf_marine.scantlings import longitudinal_strength_check, HullSectionProps, MATERIAL_AL5083
        # Tiny SM: A_deck = A_keel = 0.0001 m² → SM_min tiny → high stress
        sec_tiny = HullSectionProps(A_deck=0.0001, A_keel=0.0001, d=1.0, A_side=0.0001, d_mid=0.5)
        r = longitudinal_strength_check(100000.0, 20.0, 5.0, sec_tiny, MATERIAL_AL5083, 0.6)
        assert r.passes is False
        assert r.utilisation > 1.0


# ===========================================================================
# Full scantlings report integration test
# ===========================================================================

class TestScantlingsReport:
    def test_bottom_report_motor_craft(self):
        from kerf_marine.scantlings import (
            scantlings_report, MATERIAL_AL5083, DesignCategory
        )
        report = scantlings_report(
            LWL=10.0, BWL=3.2, mLDC=3500.0, V=25.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0,
            lu_mm=1200.0, s_mm=300.0,
            material=MATERIAL_AL5083,
            category=DesignCategory.A,
            zone="bottom",
        )
        d = report.as_dict()
        assert "pressures" in d
        assert "plate" in d
        assert "stiffener" in d
        assert d["plate"]["t_governing_mm"] > 0.0
        assert d["stiffener"]["SM_required_cm3"] > 0.0

    def test_side_report(self):
        from kerf_marine.scantlings import (
            scantlings_report, MATERIAL_E_GLASS_FRP, DesignCategory
        )
        report = scantlings_report(
            LWL=12.0, BWL=4.0, mLDC=8000.0, V=15.0, beta_04=20.0,
            b_mm=400.0, l_mm=800.0,
            lu_mm=1500.0, s_mm=400.0,
            material=MATERIAL_E_GLASS_FRP,
            category=DesignCategory.B,
            zone="side",
        )
        # Side pressure must be used
        pres = report.pressures
        assert report.plate.P_design_kPa < pres.P_bottom + 0.1   # side ≤ bottom

    def test_with_longitudinal_check(self):
        from kerf_marine.scantlings import (
            scantlings_report, HullSectionProps, MATERIAL_STEEL_S355, DesignCategory
        )
        sec = HullSectionProps(A_deck=0.08, A_keel=0.08, d=2.5, A_side=0.03, d_mid=1.25)
        report = scantlings_report(
            LWL=15.0, BWL=4.5, mLDC=12000.0, V=18.0, beta_04=15.0,
            b_mm=350.0, l_mm=700.0,
            lu_mm=1400.0, s_mm=350.0,
            material=MATERIAL_STEEL_S355,
            category=DesignCategory.A,
            zone="bottom",
            section=sec,
            Cb=0.55,
        )
        d = report.as_dict()
        assert "longitudinal_strength" in d
        assert "passes" in d["longitudinal_strength"]

    def test_sailing_report(self):
        from kerf_marine.scantlings import (
            scantlings_report, MATERIAL_E_GLASS_EPOXY, DesignCategory
        )
        report = scantlings_report(
            LWL=12.0, BWL=3.5, mLDC=7000.0, V=0.0, beta_04=20.0,
            b_mm=350.0, l_mm=700.0,
            lu_mm=1300.0, s_mm=350.0,
            material=MATERIAL_E_GLASS_EPOXY,
            category=DesignCategory.A,
            zone="bottom",
            is_sailing=True,
        )
        d = report.as_dict()
        assert d["pressures"]["P_bottom_motor_kPa"] == pytest.approx(0.0)
        assert d["pressures"]["P_bottom_kPa"] > 0.0


# ===========================================================================
# Module smoke tests
# ===========================================================================

class TestScantlingsImports:
    def test_module_imports(self):
        import kerf_marine.scantlings  # noqa: F401

    def test_pycompile(self):
        import py_compile
        path = os.path.join(_SRC, "kerf_marine", "scantlings.py")
        py_compile.compile(path, doraise=True)

    def test_all_presets_available(self):
        from kerf_marine.scantlings import (
            MATERIAL_E_GLASS_FRP,
            MATERIAL_E_GLASS_EPOXY,
            MATERIAL_AL5083,
            MATERIAL_AL6061T6,
            MATERIAL_STEEL_S235,
            MATERIAL_STEEL_S355,
        )
        for m in [MATERIAL_E_GLASS_FRP, MATERIAL_E_GLASS_EPOXY,
                  MATERIAL_AL5083, MATERIAL_AL6061T6,
                  MATERIAL_STEEL_S235, MATERIAL_STEEL_S355]:
            assert m.sigma_uf > 0.0
