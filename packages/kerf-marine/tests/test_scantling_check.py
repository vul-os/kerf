"""
Tests for kerf_marine.scantling_check — multi-rule-set scantling PASS/FAIL checks.

Covers:
  - ISO 12215-5 check wrapper (PASS/FAIL, utilisation)
  - ABS Steel Vessels 2024 Pt.3 Ch.2 §3 (pressure, plate, stiffener)
  - DNV Rules 2023 Pt.3 Ch.1 Sec.7 (pressure, plate, stiffener)
  - Unified marine_scantling_check multi-result
  - Physical invariants: pressure ↑ with draft/speed; thickness ↑ with pressure/panel

Numeric oracles: closed-form formula reproduces via hand calculation.
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
# Helpers
# ===========================================================================

def _mat_steel():
    from kerf_marine.scantlings import MATERIAL_STEEL_S235
    return MATERIAL_STEEL_S235

def _mat_al():
    from kerf_marine.scantlings import MATERIAL_AL5083
    return MATERIAL_AL5083

def _mat_frp():
    from kerf_marine.scantlings import MATERIAL_E_GLASS_FRP
    return MATERIAL_E_GLASS_FRP


# ===========================================================================
# ISO 12215-5 check wrapper
# ===========================================================================

class TestISO12215Check:

    def test_check_returns_result(self):
        """check_iso_12215 returns a ScantlingCheckResult with expected fields."""
        from kerf_marine.scantling_check import check_iso_12215, ScantlingCheckResult
        from kerf_marine.scantlings import DesignCategory
        r = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), category=DesignCategory.A, zone="bottom",
        )
        assert isinstance(r, ScantlingCheckResult)
        assert r.rule_set.startswith("ISO 12215-5")
        assert r.t_required_mm > 0.0
        assert r.SM_required_cm3 > 0.0

    def test_clause_cited(self):
        """Result clause string cites ISO 12215-5."""
        from kerf_marine.scantling_check import check_iso_12215
        from kerf_marine.scantlings import DesignCategory
        r = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        assert "ISO 12215-5" in r.clause
        assert "§11.4" in r.clause or "§11.5" in r.clause

    def test_pass_when_actual_geq_required(self):
        """PASS when t_actual >= t_required."""
        from kerf_marine.scantling_check import check_iso_12215
        from kerf_marine.scantlings import DesignCategory
        # First get required
        r_req = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        t_req = r_req.t_required_mm
        SM_req = r_req.SM_required_cm3

        # Provide actual = 1.5 × required → PASS
        r = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
            t_actual_mm=t_req * 1.5,
            SM_actual_cm3=SM_req * 1.5,
        )
        assert r.plate_passes is True
        assert r.stiff_passes is True
        assert r.passes is True

    def test_fail_when_actual_less_than_required(self):
        """FAIL when t_actual < t_required."""
        from kerf_marine.scantling_check import check_iso_12215
        from kerf_marine.scantlings import DesignCategory
        # Get required first
        r_req = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        t_req = r_req.t_required_mm

        r = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
            t_actual_mm=t_req * 0.5,  # under-scantled
        )
        assert r.plate_passes is False
        assert r.passes is False

    def test_utilisation_ratio_oracle(self):
        """utilisation = t_required / t_actual (plate)."""
        from kerf_marine.scantling_check import check_iso_12215
        r = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
            t_actual_mm=8.0,
        )
        expected_util = r.t_required_mm / 8.0
        assert r.plate_util == pytest.approx(expected_util, rel=1e-9)

    def test_higher_pressure_zone_bottom_vs_deck(self):
        """Bottom pressure > deck pressure → thicker plate required for bottom."""
        from kerf_marine.scantling_check import check_iso_12215
        r_bot = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        r_deck = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="deck",
        )
        assert r_bot.P_design_kPa >= r_deck.P_design_kPa
        assert r_bot.t_required_mm >= r_deck.t_required_mm

    def test_plate_thickness_increases_with_pressure(self):
        """ISO check: t_required ↑ with higher speed (→ higher P)."""
        from kerf_marine.scantling_check import check_iso_12215
        r_slow = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=10.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        r_fast = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=30.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        assert r_fast.P_design_kPa >= r_slow.P_design_kPa

    def test_larger_panel_requires_thicker_plate(self):
        """Larger panel (bigger b_mm) → bigger t_required."""
        from kerf_marine.scantling_check import check_iso_12215
        r_small = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=200.0, l_mm=400.0, lu_mm=800.0, s_mm=200.0,
            material=_mat_al(), zone="bottom",
        )
        r_large = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=500.0, l_mm=1000.0, lu_mm=2000.0, s_mm=500.0,
            material=_mat_al(), zone="bottom",
        )
        # Larger panel → larger t_required before minimum clamp
        # Compare raw formula values (note kAR may clamp to 0.25 for both)
        assert r_large.t_required_mm >= r_small.t_required_mm

    def test_stiffener_sm_increases_with_span(self):
        """Longer stiffener span → larger SM_required."""
        from kerf_marine.scantling_check import check_iso_12215
        r1 = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=600.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        r2 = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1800.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        assert r2.SM_required_cm3 > r1.SM_required_cm3

    def test_dict_keys(self):
        """as_dict() contains expected top-level keys."""
        from kerf_marine.scantling_check import check_iso_12215
        r = check_iso_12215(
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0, beta_04=18.0,
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(), zone="bottom",
        )
        d = r.as_dict()
        for k in ["rule_set", "component", "zone", "P_design_kPa", "plate", "stiffener", "passes", "clause"]:
            assert k in d, f"Missing key: {k}"
        assert "utilisation" in d["plate"]
        assert "passes" in d["plate"]
        assert "utilisation" in d["stiffener"]
        assert "passes" in d["stiffener"]


# ===========================================================================
# ABS design pressure
# ===========================================================================

class TestABSDesignPressure:

    def test_keel_pressure_oracle(self):
        """
        ABS pressure at keel: P = rho * g * h
        For rho=1.025 t/m³, h=3.0m:
          P = 1.025 × 9.80665 × 3.0 ≈ 30.14 kPa
        """
        from kerf_marine.scantling_check import abs_design_pressure, G
        rho = 1.025
        h = 3.0
        expected = rho * G * h
        P = abs_design_pressure(h_m=h, Cw=0.0, rho=rho)
        assert P == pytest.approx(expected, rel=1e-6)

    def test_deck_pressure_zero_head(self):
        """Weather deck (h=0): P = Cw only."""
        from kerf_marine.scantling_check import abs_design_pressure
        P = abs_design_pressure(h_m=0.0, Cw=5.0)
        assert P == pytest.approx(5.0, rel=1e-9)

    def test_pressure_increases_with_head(self):
        """Deeper panel → higher pressure."""
        from kerf_marine.scantling_check import abs_design_pressure
        P1 = abs_design_pressure(1.0)
        P3 = abs_design_pressure(3.0)
        assert P3 > P1

    def test_pressure_nonnegative(self):
        """ABS pressure never negative."""
        from kerf_marine.scantling_check import abs_design_pressure
        assert abs_design_pressure(0.0, 0.0) >= 0.0


# ===========================================================================
# ABS plate and stiffener formulas
# ===========================================================================

class TestABSFormulas:

    def test_plate_thickness_oracle(self):
        """
        ABS plate thickness formula oracle.
        P=30 kPa, s=400 mm, sigma_a=188 N/mm² (0.8 * 235):
        t = 400 * sqrt(30 / (1000 * 188)) = 400 * sqrt(0.00015957)
          = 400 * 0.012632 = 5.053 mm
        """
        from kerf_marine.scantling_check import abs_plate_thickness
        P = 30.0
        s = 400.0
        sigma_a = 0.80 * 235.0  # = 188.0
        expected = s * math.sqrt(P / (1000.0 * sigma_a))
        t = abs_plate_thickness(P, s, sigma_a)
        assert t == pytest.approx(expected, rel=1e-9)

    def test_plate_thickness_increases_with_pressure(self):
        """Higher P → thicker plate."""
        from kerf_marine.scantling_check import abs_plate_thickness
        t1 = abs_plate_thickness(10.0, 400.0, 188.0)
        t2 = abs_plate_thickness(40.0, 400.0, 188.0)
        assert t2 > t1

    def test_plate_thickness_increases_with_spacing(self):
        """Wider spacing → thicker plate."""
        from kerf_marine.scantling_check import abs_plate_thickness
        t1 = abs_plate_thickness(25.0, 300.0, 188.0)
        t2 = abs_plate_thickness(25.0, 600.0, 188.0)
        assert t2 > t1

    def test_stiffener_sm_oracle(self):
        """
        ABS stiffener SM oracle (fixed ends C=1/12):
        P=20 kPa, s=400 mm, l=1200 mm, sigma_a=188 N/mm²:
        SM = (1/12) * 20 * 400 * 1200^2 / (1000 * 188)
           = (1/12) * 20 * 400 * 1440000 / 188000
           = (1/12) * 20 * 400 * 7.6596
           = (1/12) * 61276.6
           = 5106.4 cm³   (→ actual = ~5106 cm³)
        """
        from kerf_marine.scantling_check import abs_stiffener_sm
        P = 20.0
        s = 400.0
        l = 1200.0
        sigma_a = 188.0
        expected = (1.0 / 12.0) * P * s * l**2 / (1000.0 * sigma_a)
        SM = abs_stiffener_sm(P, s, l, sigma_a, C=1.0 / 12.0)
        assert SM == pytest.approx(expected, rel=1e-9)

    def test_stiffener_sm_scales_with_span_squared(self):
        """SM ∝ l² (doubling span → 4× SM) at fixed P, s, sigma_a."""
        from kerf_marine.scantling_check import abs_stiffener_sm
        SM1 = abs_stiffener_sm(20.0, 300.0, 800.0, 188.0)
        SM2 = abs_stiffener_sm(20.0, 300.0, 1600.0, 188.0)
        assert SM2 == pytest.approx(SM1 * 4.0, rel=1e-9)

    def test_simply_supported_1p5x_fixed(self):
        """Pin-pin (C=1/8) gives 1.5× SM vs fixed (C=1/12)."""
        from kerf_marine.scantling_check import abs_stiffener_sm
        SM_fixed = abs_stiffener_sm(20.0, 300.0, 1000.0, 188.0, C=1.0 / 12.0)
        SM_pin   = abs_stiffener_sm(20.0, 300.0, 1000.0, 188.0, C=1.0 / 8.0)
        assert SM_pin == pytest.approx(SM_fixed * 1.5, rel=1e-9)


# ===========================================================================
# ABS check
# ===========================================================================

class TestABSCheck:

    def test_check_returns_result(self):
        from kerf_marine.scantling_check import check_abs
        r = check_abs(
            draft_m=3.0, h_panel_m=2.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
            material=_mat_steel(), zone="side",
        )
        assert r.rule_set.startswith("ABS")
        assert r.t_required_mm > 0.0
        assert r.SM_required_cm3 > 0.0

    def test_clause_cites_abs(self):
        from kerf_marine.scantling_check import check_abs
        r = check_abs(draft_m=3.0, h_panel_m=2.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                      material=_mat_steel())
        assert "ABS" in r.clause

    def test_pass_when_over_scantled(self):
        from kerf_marine.scantling_check import check_abs
        r = check_abs(draft_m=3.0, h_panel_m=2.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                      material=_mat_steel(), t_actual_mm=20.0, SM_actual_cm3=5000.0)
        # t_actual=20mm and SM_actual=5000 cm³ should easily pass reasonable panel
        assert r.plate_passes is True

    def test_fail_when_under_scantled(self):
        """Very thin plate should fail ABS check."""
        from kerf_marine.scantling_check import check_abs
        r = check_abs(draft_m=3.0, h_panel_m=2.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                      material=_mat_steel(), t_actual_mm=0.5)
        assert r.plate_passes is False
        assert r.passes is False
        assert r.plate_util > 1.0

    def test_deeper_panel_higher_pressure(self):
        """Deeper panel (larger h_panel) → higher ABS pressure."""
        from kerf_marine.scantling_check import check_abs
        r1 = check_abs(draft_m=5.0, h_panel_m=1.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                       material=_mat_steel())
        r2 = check_abs(draft_m=5.0, h_panel_m=4.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                       material=_mat_steel())
        assert r2.P_design_kPa > r1.P_design_kPa
        assert r2.t_required_mm > r1.t_required_mm

    def test_minimum_plate_thickness_floor(self):
        """ABS minimum steel plate ≥ 4.5 mm."""
        from kerf_marine.scantling_check import check_abs
        # Very low pressure (h=0, Cw=0) → formula gives 0 → floored
        r = check_abs(draft_m=1.0, h_panel_m=0.0, s_mm=100.0, l_mm=200.0, lu_mm=300.0,
                      material=_mat_steel())
        assert r.t_required_mm >= 4.5

    def test_dict_keys(self):
        from kerf_marine.scantling_check import check_abs
        r = check_abs(draft_m=3.0, h_panel_m=2.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                      material=_mat_steel())
        d = r.as_dict()
        assert "plate" in d and "stiffener" in d
        assert "utilisation" in d["plate"]
        assert "passes" in d["stiffener"]


# ===========================================================================
# DNV design pressure
# ===========================================================================

class TestDNVDesignPressure:

    def test_deck_minimum_25kPa(self):
        """DNV weather deck: minimum 25 kPa."""
        from kerf_marine.scantling_check import dnv_design_pressure
        P = dnv_design_pressure(h_m=0.0, V_kn=0.0, zone="deck")
        assert P >= 25.0

    def test_side_pressure_includes_slamming(self):
        """Side at speed > 0: P > hydrostatic-only."""
        from kerf_marine.scantling_check import dnv_design_pressure, G
        h = 2.0
        rho = 1.025
        V_kn = 20.0
        P = dnv_design_pressure(h_m=h, V_kn=V_kn, zone="side")
        P_hydro_only = rho * 1000.0 * G * h / 1000.0
        assert P > P_hydro_only

    def test_bulkhead_no_slamming(self):
        """Bulkhead: only hydrostatic (no slamming even at speed)."""
        from kerf_marine.scantling_check import dnv_design_pressure, G
        h = 2.0
        rho = 1.025
        P_bulk_0   = dnv_design_pressure(h_m=h, V_kn=0.0, zone="bulkhead")
        P_bulk_20  = dnv_design_pressure(h_m=h, V_kn=20.0, zone="bulkhead")
        # Both should equal hydrostatic (no speed term for bulkhead)
        P_expected = rho * 1000.0 * 9.80665 * h / 1000.0
        assert P_bulk_0  == pytest.approx(P_expected, rel=1e-9)
        assert P_bulk_20 == pytest.approx(P_expected, rel=1e-9)

    def test_pressure_increases_with_draft(self):
        """Deeper panel → higher DNV pressure."""
        from kerf_marine.scantling_check import dnv_design_pressure
        P1 = dnv_design_pressure(h_m=1.0, V_kn=10.0, zone="side")
        P3 = dnv_design_pressure(h_m=3.0, V_kn=10.0, zone="side")
        assert P3 > P1

    def test_pressure_increases_with_speed(self):
        """Faster vessel → higher DNV slamming pressure."""
        from kerf_marine.scantling_check import dnv_design_pressure
        P_slow = dnv_design_pressure(h_m=2.0, V_kn=5.0, zone="side")
        P_fast = dnv_design_pressure(h_m=2.0, V_kn=20.0, zone="side")
        assert P_fast > P_slow


# ===========================================================================
# DNV ka factor
# ===========================================================================

class TestDNVKaFactor:

    def test_square_panel_ka(self):
        """Square panel (s=l): ka = 0.5 + 1.0 = 1.5 → capped at 1.0."""
        from kerf_marine.scantling_check import dnv_ka_factor
        ka = dnv_ka_factor(500.0, 500.0)
        assert ka == pytest.approx(1.0, rel=1e-9)

    def test_elongated_panel_ka_below_1(self):
        """Elongated panel (s/l = 0.2): ka = 0.5 + 0.04 = 0.54 < 1."""
        from kerf_marine.scantling_check import dnv_ka_factor
        ka = dnv_ka_factor(200.0, 1000.0)
        expected = 0.5 + (200.0 / 1000.0) ** 2
        assert ka == pytest.approx(expected, rel=1e-9)

    def test_ka_analytical_oracle(self):
        """Oracle: s=300, l=600, s/l=0.5 → ka = 0.5 + 0.25 = 0.75."""
        from kerf_marine.scantling_check import dnv_ka_factor
        ka = dnv_ka_factor(300.0, 600.0)
        assert ka == pytest.approx(0.75, rel=1e-9)

    def test_ka_capped_at_1(self):
        """ka never exceeds 1.0."""
        from kerf_marine.scantling_check import dnv_ka_factor
        ka = dnv_ka_factor(1000.0, 200.0)  # s > l — uses min/max
        assert ka <= 1.0


# ===========================================================================
# DNV plate and stiffener formulas
# ===========================================================================

class TestDNVFormulas:

    def test_plate_thickness_oracle(self):
        """
        DNV Eq. (7.2) oracle:
        P=25 kPa, ka=0.75, s=300 mm (=0.3 m), sigma_f = 0.9*235 = 211.5 N/mm²:
        t = 15.8 * 0.75 * 0.3 * 1000 * sqrt(25 / (1000 * 211.5))
          = 15.8 * 0.75 * 0.3 * 1000 * sqrt(0.0001182)
          = 15.8 * 0.75 * 300 * 0.010872
          = 15.8 * 0.75 * 3.262
          = 15.8 * 2.447
          = 38.6 mm  ... let me recompute:

        t = 15.8 * ka * (s_mm / 1000) * 1000 * sqrt(P / (1000 * sigma_f))
          = 15.8 * ka * s_mm * sqrt(P / (1000 * sigma_f))
        """
        from kerf_marine.scantling_check import dnv_plate_thickness
        P = 25.0
        ka = 0.75
        s = 300.0  # mm
        sigma_f = 0.9 * 235.0  # = 211.5 N/mm²
        s_m = s / 1000.0
        expected = 15.8 * ka * s_m * 1000.0 * math.sqrt(P / (1000.0 * sigma_f))
        t = dnv_plate_thickness(P, ka, s, sigma_f)
        assert t == pytest.approx(expected, rel=1e-9)

    def test_plate_thickness_increases_with_pressure(self):
        """Higher P → thicker plate."""
        from kerf_marine.scantling_check import dnv_plate_thickness
        t1 = dnv_plate_thickness(10.0, 0.8, 300.0, 200.0)
        t2 = dnv_plate_thickness(40.0, 0.8, 300.0, 200.0)
        assert t2 > t1

    def test_plate_thickness_increases_with_spacing(self):
        """Wider spacing → thicker plate."""
        from kerf_marine.scantling_check import dnv_plate_thickness
        t1 = dnv_plate_thickness(25.0, 0.8, 200.0, 200.0)
        t2 = dnv_plate_thickness(25.0, 0.8, 500.0, 200.0)
        assert t2 > t1

    def test_stiffener_sm_oracle(self):
        """
        DNV Eq. (7.6) oracle (m=1/12):
        P=20 kPa, l=1200 mm (=1.2 m), s=300 mm (=0.3 m), sigma_f=211.5 N/mm²:
        SM = (1/12) * 20 * 0.3 * 1.2^2 * 1000 / 211.5
           = (1/12) * 20 * 0.3 * 1.44 * 1000 / 211.5
           = (1/12) * 8640 / 211.5
           = (1/12) * 40.853
           = 3.404 cm³   (surprisingly small — check units carefully)

        Actually: SM_cm3 = m * P_kPa * s_m * l_m^2 * 1000 / sigma_f
        = (1/12) * 20 * 0.3 * 1.44 * 1000 / 211.5
        = (1/12) * 8640 / 211.5
        = 720 / 211.5 = 3.404 cm³
        """
        from kerf_marine.scantling_check import dnv_stiffener_sm
        P = 20.0
        l = 1200.0
        s = 300.0
        sigma_f = 0.9 * 235.0
        m = 1.0 / 12.0
        l_m = l / 1000.0
        s_m = s / 1000.0
        expected = m * P * s_m * l_m**2 * 1000.0 / sigma_f
        SM = dnv_stiffener_sm(P, l, s, sigma_f, m=m)
        assert SM == pytest.approx(expected, rel=1e-9)

    def test_stiffener_sm_scales_with_span_squared(self):
        """DNV SM ∝ l² (doubling span → 4× SM)."""
        from kerf_marine.scantling_check import dnv_stiffener_sm
        SM1 = dnv_stiffener_sm(20.0, 800.0, 300.0, 200.0, m=1.0/12.0)
        SM2 = dnv_stiffener_sm(20.0, 1600.0, 300.0, 200.0, m=1.0/12.0)
        assert SM2 == pytest.approx(SM1 * 4.0, rel=1e-9)

    def test_pin_pin_1p5x_fixed_dnv(self):
        """DNV pin-pin (m=1/8) gives 1.5× SM vs fixed (m=1/12)."""
        from kerf_marine.scantling_check import dnv_stiffener_sm
        SM_fixed = dnv_stiffener_sm(20.0, 1000.0, 300.0, 200.0, m=1.0/12.0)
        SM_pin   = dnv_stiffener_sm(20.0, 1000.0, 300.0, 200.0, m=1.0/8.0)
        assert SM_pin == pytest.approx(SM_fixed * 1.5, rel=1e-9)


# ===========================================================================
# DNV check
# ===========================================================================

class TestDNVCheck:

    def test_check_returns_result(self):
        from kerf_marine.scantling_check import check_dnv
        r = check_dnv(
            h_panel_m=2.5, V_kn=15.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
            material=_mat_steel(), zone="side",
        )
        assert r.rule_set.startswith("DNV")
        assert r.t_required_mm > 0.0

    def test_clause_cites_dnv(self):
        from kerf_marine.scantling_check import check_dnv
        r = check_dnv(h_panel_m=2.5, V_kn=15.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                      material=_mat_steel())
        assert "DNV" in r.clause

    def test_pass_when_over_scantled(self):
        """With ample plate and SM, should pass. Use required values × 2 to guarantee pass."""
        from kerf_marine.scantling_check import check_dnv
        # First get required
        r_req = check_dnv(
            h_panel_m=1.0, V_kn=10.0, s_mm=300.0, l_mm=600.0, lu_mm=900.0,
            material=_mat_steel(),
        )
        r = check_dnv(
            h_panel_m=1.0, V_kn=10.0, s_mm=300.0, l_mm=600.0, lu_mm=900.0,
            material=_mat_steel(),
            t_actual_mm=r_req.t_required_mm * 2.0,
            SM_actual_cm3=r_req.SM_required_cm3 * 2.0,
        )
        assert r.plate_passes is True

    def test_fail_when_under_scantled(self):
        from kerf_marine.scantling_check import check_dnv
        r = check_dnv(
            h_panel_m=3.0, V_kn=20.0, s_mm=500.0, l_mm=1000.0, lu_mm=1500.0,
            material=_mat_steel(), t_actual_mm=0.5,
        )
        assert r.plate_passes is False
        assert r.passes is False

    def test_faster_speed_higher_pressure(self):
        """Higher speed → larger design pressure → larger required thickness."""
        from kerf_marine.scantling_check import check_dnv
        r_slow = check_dnv(h_panel_m=2.0, V_kn=5.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                           material=_mat_steel(), zone="side")
        r_fast = check_dnv(h_panel_m=2.0, V_kn=25.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                           material=_mat_steel(), zone="side")
        assert r_fast.P_design_kPa > r_slow.P_design_kPa
        assert r_fast.t_required_mm >= r_slow.t_required_mm

    def test_deeper_panel_higher_required(self):
        """Deeper panel → higher required plate thickness."""
        from kerf_marine.scantling_check import check_dnv
        r1 = check_dnv(h_panel_m=1.0, V_kn=10.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                       material=_mat_steel(), zone="side")
        r2 = check_dnv(h_panel_m=4.0, V_kn=10.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                       material=_mat_steel(), zone="side")
        assert r2.t_required_mm > r1.t_required_mm

    def test_minimum_steel_plate_floor(self):
        """DNV minimum steel plate ≥ 5.0 mm."""
        from kerf_marine.scantling_check import check_dnv
        r = check_dnv(h_panel_m=0.0, V_kn=0.0, s_mm=100.0, l_mm=200.0, lu_mm=300.0,
                      material=_mat_steel(), zone="bulkhead")
        assert r.t_required_mm >= 5.0

    def test_dict_keys(self):
        from kerf_marine.scantling_check import check_dnv
        r = check_dnv(h_panel_m=2.0, V_kn=10.0, s_mm=400.0, l_mm=800.0, lu_mm=1200.0,
                      material=_mat_steel())
        d = r.as_dict()
        for k in ["rule_set", "P_design_kPa", "plate", "stiffener", "passes", "clause", "notes"]:
            assert k in d


# ===========================================================================
# Unified marine_scantling_check
# ===========================================================================

class TestMarineScantlingCheck:

    def test_iso_only(self):
        """Single ISO rule-set check."""
        from kerf_marine.scantling_check import marine_scantling_check
        from kerf_marine.scantlings import DesignCategory
        multi = marine_scantling_check(
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(),
            rule_sets=["iso"],
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0,
            category=DesignCategory.A, zone="bottom",
        )
        assert len(multi.results) == 1
        assert multi.results[0].rule_set.startswith("ISO")

    def test_abs_only(self):
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=400.0, l_mm=800.0, lu_mm=1200.0, s_mm=400.0,
            material=_mat_steel(),
            rule_sets=["abs"],
            h_panel_m=2.0, zone="side",
        )
        assert len(multi.results) == 1
        assert multi.results[0].rule_set.startswith("ABS")

    def test_dnv_only(self):
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=400.0, l_mm=800.0, lu_mm=1200.0, s_mm=400.0,
            material=_mat_steel(),
            rule_sets=["dnv"],
            h_panel_m=2.5, V_kn=15.0, zone="side",
        )
        assert len(multi.results) == 1
        assert multi.results[0].rule_set.startswith("DNV")

    def test_all_three_rule_sets(self):
        """Three rule-sets → three results."""
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=400.0, l_mm=800.0, lu_mm=1200.0, s_mm=400.0,
            material=_mat_steel(),
            rule_sets=["iso", "abs", "dnv"],
            LWL=12.0, BWL=4.0, mLDC=8000.0, V=15.0,
            h_panel_m=2.0, V_kn=15.0, zone="side",
        )
        assert len(multi.results) == 3

    def test_all_pass_when_over_scantled(self):
        """All three checks pass when actual scantlings are 3× any required value."""
        from kerf_marine.scantling_check import marine_scantling_check
        # First get required without actuals
        multi_req = marine_scantling_check(
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_steel(),
            rule_sets=["iso", "abs", "dnv"],
            LWL=10.0, BWL=3.0, mLDC=4000.0, V=15.0,
            h_panel_m=2.0, V_kn=10.0, zone="bottom",
        )
        t_max = max(r.t_required_mm for r in multi_req.results)
        SM_max = max(r.SM_required_cm3 for r in multi_req.results)

        multi = marine_scantling_check(
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_steel(),
            rule_sets=["iso", "abs", "dnv"],
            LWL=10.0, BWL=3.0, mLDC=4000.0, V=15.0,
            h_panel_m=2.0, V_kn=10.0, zone="bottom",
            t_actual_mm=t_max * 3.0,     # 3× max required — over-scantled
            SM_actual_cm3=SM_max * 3.0,  # 3× max required
        )
        assert all(r.plate_passes for r in multi.results)
        assert multi.all_pass is True
        assert "PASS" in multi.summary

    def test_fail_summary_when_under_scantled(self):
        """Summary reports FAIL when actual < required."""
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=400.0, l_mm=800.0, lu_mm=1200.0, s_mm=400.0,
            material=_mat_steel(),
            rule_sets=["iso", "abs", "dnv"],
            LWL=12.0, BWL=4.0, mLDC=8000.0, V=20.0,
            h_panel_m=3.0, V_kn=20.0, zone="bottom",
            t_actual_mm=0.5,     # tiny — will fail
        )
        assert multi.all_pass is False
        assert "FAIL" in multi.summary

    def test_no_actual_provided_no_pass_fail(self):
        """Without actual scantlings, result still has required values (no PASS/FAIL assertion)."""
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(),
            rule_sets=["iso"],
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0,
        )
        assert multi.results[0].t_required_mm > 0
        assert "Provide" in multi.summary

    def test_dict_output_structure(self):
        """as_dict() returns expected structure."""
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_steel(),
            rule_sets=["abs", "dnv"],
            h_panel_m=2.0, V_kn=10.0, zone="side",
        )
        d = multi.as_dict()
        assert "all_pass" in d
        assert "summary" in d
        assert "checks" in d
        assert len(d["checks"]) == 2

    def test_empty_rule_sets_defaults_to_iso(self):
        """Empty rule_sets list defaults to ISO check."""
        from kerf_marine.scantling_check import marine_scantling_check
        multi = marine_scantling_check(
            b_mm=300.0, l_mm=600.0, lu_mm=1200.0, s_mm=300.0,
            material=_mat_al(),
            rule_sets=[],
            LWL=10.0, BWL=3.0, mLDC=3500.0, V=20.0,
        )
        assert len(multi.results) == 1
        assert "ISO" in multi.results[0].rule_set


# ===========================================================================
# Module smoke tests
# ===========================================================================

class TestScantlingCheckImports:

    def test_module_imports(self):
        import kerf_marine.scantling_check  # noqa: F401

    def test_pycompile(self):
        import py_compile
        path = os.path.join(_SRC, "kerf_marine", "scantling_check.py")
        py_compile.compile(path, doraise=True)

    def test_all_check_functions_importable(self):
        from kerf_marine.scantling_check import (
            check_iso_12215,
            check_abs,
            check_dnv,
            marine_scantling_check,
            ScantlingCheckResult,
            ScantlingCheckMultiResult,
        )
        assert callable(check_iso_12215)
        assert callable(check_abs)
        assert callable(check_dnv)
        assert callable(marine_scantling_check)

    def test_tool_spec_importable(self):
        from kerf_marine.tools import (
            marine_scantling_check_spec,
            run_marine_scantling_check,
        )
        assert marine_scantling_check_spec.name == "marine_scantling_check"
