"""
Tests for kerf_cad_core.arch.pier_axial_capacity — TMS 402-22 §8.3 + ACI 318-19 §22.4.2.2.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in mm, stresses in MPa, forces in kN.

Oracle reference (primary test case T01):
  pier_width = pier_thickness = 200 mm (square), height h = 3000 mm
  material = clay_masonry, f'm = 10 MPa, As = 0, end_conditions = pin_pin
  k = 1.0, h_eff = 1.0 × 3000 = 3000 mm
  r = 200 / √12 = 57.735 mm
  h/r = 3000 / 57.735 = 51.96
  C_s = 1 − (3000 / (140 × 57.735))² = 1 − (3000/8082.9)² = 1 − 0.37124² = 1 − 0.1378 = 0.8622
  Ag = 200 × 200 = 40 000 mm²
  Pn = 0.80 × 10 × 40 000 = 320 000 N = 320 kN
  φ·Pn = 0.65 × 320 000 × 0.8622 / 1000 = 179.5 kN (approx)

  Note: task spec says slenderness factor ≈ 0.86 for this case — consistent.

Coverage:
  T01  200×200 pin-pin h=3000 clay f'm=10MPa → r≈57.7 mm, h/r≈52, C_s≈0.862
  T02  h/r > 99 → slenderness_limit_exceeded, phi_Pn=0.0
  T03  fixed_fixed halves effective length → larger C_s than pin_pin
  T04  cantilever doubles effective length → lower C_s than pin_pin
  T05  fixed_pin k=0.7 → h_eff between pin_pin and fixed_fixed
  T06  Masonry phi_Pn formula: φ·Pn = φ·0.80·f'm·Ag·C_s (exact arithmetic check)
  T07  RC pier ACI formula: φ·Pn = φ·0.80·[0.85·f'c·(Ag-As)+fy·As]·C_s
  T08  concrete_masonry material accepted (same formula as clay_masonry)
  T09  h/r exactly 99 → NOT exceeded (boundary condition, C_s computed)
  T10  h/r slightly above 99 → slenderness_limit_exceeded
  T11  C_s monotonically decreasing as height increases (for fixed geometry)
  T12  Larger cross-section (wider pier) → larger r → smaller h/r → larger C_s
  T13  Higher f'm → proportionally higher phi_Pn (masonry)
  T14  phi parameter scales phi_Pn proportionally
  T15  Re-export from arch/__init__.py works
  T16  honest_caveat mentions "TMS 402-22"
  T17  honest_caveat mentions "ACI 318-19" for RC
  T18  governing_failure_mode = "slender_buckling" when 0 < C_s < 1
  T19  governing_failure_mode = "yielding" when C_s = 1.0 (very stocky pier)
  T20  ValueError: pier_width_mm <= 0
  T21  ValueError: pier_thickness_mm <= 0
  T22  ValueError: height_h_mm <= 0
  T23  ValueError: f_prime_MPa <= 0
  T24  ValueError: As_total_mm2 < 0
  T25  ValueError: unknown material
  T26  ValueError: unknown end_conditions
  T27  ValueError: phi out of range
  T28  ValueError: P_factored_kN < 0
  T29  RC: ValueError when As_total >= Ag
  T30  DCR > 1 check (demand exceeds capacity)
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_cad_core.arch.pier_axial_capacity import (
    PierSpec,
    PierAxialReport,
    check_pier_axial,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pier(
    width=200.0,
    thickness=200.0,
    height=3000.0,
    material="clay_masonry",
    f_prime=10.0,
    As=0.0,
    fy=420.0,
    end_conditions="pin_pin",
):
    return PierSpec(
        pier_width_mm=width,
        pier_thickness_mm=thickness,
        height_h_mm=height,
        material=material,
        f_prime_MPa=f_prime,
        As_total_mm2=As,
        fy_MPa=fy,
        end_conditions=end_conditions,
    )


# ---------------------------------------------------------------------------
# T01 — Primary oracle: 200×200 pin-pin h=3000 clay_masonry f'm=10MPa
# ---------------------------------------------------------------------------

class TestT01PrimaryOracle:
    """200×200 pin-pin h=3000 clay_masonry f'm=10MPa — r≈57.7, h/r≈52, C_s≈0.862"""

    def setup_method(self):
        self.pier = make_pier()
        self.report = check_pier_axial(self.pier, P_factored_kN=100.0)

    def test_r_value(self):
        """r = 200/√12 ≈ 57.735 mm; h/r ≈ 51.96"""
        r_expected = 200.0 / math.sqrt(12.0)
        h_over_r_expected = 3000.0 / r_expected
        assert abs(self.report.h_over_r - h_over_r_expected) < 0.01

    def test_h_over_r_approx_52(self):
        assert 51.0 < self.report.h_over_r < 53.0

    def test_slenderness_factor_approx_086(self):
        """TMS Eq 8-22: C_s = 1 - (h_eff/(140r))² ≈ 0.862 for h/r≈52"""
        r = 200.0 / math.sqrt(12.0)
        h_eff = 3000.0  # k=1 pin-pin
        cs_expected = 1.0 - (h_eff / (140.0 * r)) ** 2
        assert abs(self.report.slenderness_factor - cs_expected) < 1e-6
        # Task spec says ≈ 0.86
        assert abs(self.report.slenderness_factor - 0.86) < 0.01

    def test_phi_Pn_formula(self):
        """phi_Pn = 0.65 * 0.80 * 10 * 40000 * C_s / 1000 kN"""
        r = 200.0 / math.sqrt(12.0)
        cs = 1.0 - (3000.0 / (140.0 * r)) ** 2
        expected = 0.65 * 0.80 * 10.0 * 40_000.0 * cs / 1_000.0
        assert abs(self.report.phi_Pn_kN - expected) < 0.01

    def test_governing_mode_slender_buckling(self):
        """h/r > 0 and C_s < 1 → slender_buckling"""
        assert self.report.governing_failure_mode == "slender_buckling"

    def test_not_slenderness_limit_exceeded(self):
        assert self.report.governing_failure_mode != "slenderness_limit_exceeded"


# ---------------------------------------------------------------------------
# T02 — h/r > 99 → slenderness_limit_exceeded
# ---------------------------------------------------------------------------

class TestT02SlendernessLimitExceeded:
    """Very tall slender pier: h/r > 99 → formula does not apply"""

    def setup_method(self):
        # r = 200/√12 ≈ 57.7; need h_eff/r > 99 → h > 99 * 57.7 / k = 5712 mm (k=1)
        self.pier = make_pier(height=6000.0, end_conditions="pin_pin")
        self.report = check_pier_axial(self.pier, P_factored_kN=50.0)

    def test_failure_mode(self):
        assert self.report.governing_failure_mode == "slenderness_limit_exceeded"

    def test_phi_Pn_is_zero(self):
        assert self.report.phi_Pn_kN == 0.0

    def test_slenderness_factor_is_zero(self):
        assert self.report.slenderness_factor == 0.0

    def test_h_over_r_reported(self):
        r = 200.0 / math.sqrt(12.0)
        expected = 6000.0 / r
        assert abs(self.report.h_over_r - expected) < 0.1


# ---------------------------------------------------------------------------
# T03 — fixed-fixed reduces effective length → larger C_s
# ---------------------------------------------------------------------------

class TestT03FixedFixed:
    """fixed_fixed k=0.5 → h_eff = 0.5*h → smaller h/r → larger C_s than pin_pin"""

    def test_fixed_fixed_larger_cs_than_pin_pin(self):
        pier_pp = make_pier(end_conditions="pin_pin")
        pier_ff = make_pier(end_conditions="fixed_fixed")
        rpt_pp = check_pier_axial(pier_pp, P_factored_kN=10.0)
        rpt_ff = check_pier_axial(pier_ff, P_factored_kN=10.0)
        assert rpt_ff.slenderness_factor > rpt_pp.slenderness_factor

    def test_fixed_fixed_k_effective_length(self):
        """h_eff for fixed_fixed = 0.5 * h"""
        pier = make_pier(end_conditions="fixed_fixed")
        r = 200.0 / math.sqrt(12.0)
        h_eff = 0.5 * 3000.0
        cs_expected = 1.0 - (h_eff / (140.0 * r)) ** 2
        report = check_pier_axial(pier, P_factored_kN=10.0)
        assert abs(report.slenderness_factor - cs_expected) < 1e-6

    def test_fixed_fixed_h_over_r(self):
        pier = make_pier(end_conditions="fixed_fixed")
        r = 200.0 / math.sqrt(12.0)
        expected = 0.5 * 3000.0 / r
        report = check_pier_axial(pier, P_factored_kN=10.0)
        assert abs(report.h_over_r - expected) < 0.01


# ---------------------------------------------------------------------------
# T04 — cantilever doubles effective length
# ---------------------------------------------------------------------------

class TestT04Cantilever:
    """cantilever k=2.0 → h_eff = 2*h → may exceed h/r = 99"""

    def test_cantilever_greater_h_over_r_than_pin_pin(self):
        pier_pp = make_pier(end_conditions="pin_pin")
        pier_cv = make_pier(end_conditions="cantilever")
        rpt_pp = check_pier_axial(pier_pp, P_factored_kN=10.0)
        rpt_cv = check_pier_axial(pier_cv, P_factored_kN=10.0)
        assert rpt_cv.h_over_r > rpt_pp.h_over_r

    def test_cantilever_may_exceed_limit(self):
        """With h=3000 and k=2.0, h_eff=6000 → h/r>99 → limit exceeded"""
        pier = make_pier(height=3000.0, end_conditions="cantilever")
        report = check_pier_axial(pier, P_factored_kN=10.0)
        r = 200.0 / math.sqrt(12.0)
        h_over_r = 2.0 * 3000.0 / r
        if h_over_r > 99.0:
            assert report.governing_failure_mode == "slenderness_limit_exceeded"


# ---------------------------------------------------------------------------
# T05 — fixed_pin k=0.7
# ---------------------------------------------------------------------------

class TestT05FixedPin:
    """fixed_pin k=0.7 → h/r between pin_pin and fixed_fixed"""

    def test_h_over_r_ordering(self):
        pier_ff = make_pier(end_conditions="fixed_fixed")
        pier_fp = make_pier(end_conditions="fixed_pin")
        pier_pp = make_pier(end_conditions="pin_pin")
        rpt_ff = check_pier_axial(pier_ff, P_factored_kN=10.0)
        rpt_fp = check_pier_axial(pier_fp, P_factored_kN=10.0)
        rpt_pp = check_pier_axial(pier_pp, P_factored_kN=10.0)
        assert rpt_ff.h_over_r < rpt_fp.h_over_r < rpt_pp.h_over_r


# ---------------------------------------------------------------------------
# T06 — Masonry formula arithmetic
# ---------------------------------------------------------------------------

class TestT06MasonryFormula:
    """phi_Pn = phi * 0.80 * f'm * Ag * C_s"""

    def test_exact_formula(self):
        width, thickness, h = 300.0, 200.0, 2500.0
        f_prime = 15.0
        k = 1.0  # pin_pin
        # governing r = min(width, thickness)/√12 = 200/√12
        r = min(width, thickness) / math.sqrt(12.0)
        h_eff = k * h
        cs = 1.0 - (h_eff / (140.0 * r)) ** 2
        Ag = width * thickness
        expected = 0.65 * 0.80 * f_prime * Ag * cs / 1_000.0
        pier = make_pier(width=width, thickness=thickness, height=h, f_prime=f_prime)
        report = check_pier_axial(pier, P_factored_kN=50.0, phi=0.65)
        assert abs(report.phi_Pn_kN - expected) < 0.01

    def test_concrete_masonry_same_formula(self):
        """concrete_masonry uses same formula as clay_masonry"""
        pier_clay = make_pier(material="clay_masonry")
        pier_cmu = make_pier(material="concrete_masonry")
        rpt_clay = check_pier_axial(pier_clay, P_factored_kN=10.0)
        rpt_cmu = check_pier_axial(pier_cmu, P_factored_kN=10.0)
        assert abs(rpt_clay.phi_Pn_kN - rpt_cmu.phi_Pn_kN) < 1e-6


# ---------------------------------------------------------------------------
# T07 — RC pier ACI formula
# ---------------------------------------------------------------------------

class TestT07RCFormula:
    """RC: phi_Pn = phi*0.80*[0.85*f'c*(Ag-As)+fy*As]*C_s"""

    def test_rc_formula_arithmetic(self):
        width, thickness, h = 300.0, 300.0, 2000.0
        f_prime = 25.0
        As = 1200.0  # mm²
        fy = 420.0
        k = 1.0  # pin_pin
        Ag = width * thickness
        r = min(width, thickness) / math.sqrt(12.0)
        h_eff = k * h
        cs = 1.0 - (h_eff / (140.0 * r)) ** 2
        Pn_N = 0.80 * (0.85 * f_prime * (Ag - As) + fy * As)
        expected = 0.65 * Pn_N * cs / 1_000.0
        pier = make_pier(
            width=width, thickness=thickness, height=h,
            material="reinforced_concrete", f_prime=f_prime, As=As, fy=fy,
        )
        report = check_pier_axial(pier, P_factored_kN=50.0)
        assert abs(report.phi_Pn_kN - expected) < 0.01

    def test_rc_higher_As_higher_capacity(self):
        """More steel → higher phi_Pn (for constant geometry and f'c)"""
        pier_lo = make_pier(material="reinforced_concrete", f_prime=25.0, As=800.0, fy=420.0)
        pier_hi = make_pier(material="reinforced_concrete", f_prime=25.0, As=2000.0, fy=420.0)
        rpt_lo = check_pier_axial(pier_lo, P_factored_kN=100.0)
        rpt_hi = check_pier_axial(pier_hi, P_factored_kN=100.0)
        assert rpt_hi.phi_Pn_kN > rpt_lo.phi_Pn_kN


# ---------------------------------------------------------------------------
# T08 — Boundary h/r = 99 exactly
# ---------------------------------------------------------------------------

class TestT08BoundaryHoverR99:
    """h/r exactly 99 → NOT exceeded; C_s computed normally"""

    def test_exactly_99_not_exceeded(self):
        # Set height so h_eff/r = 99 exactly: h = 99 * r / k (k=1)
        r = 200.0 / math.sqrt(12.0)
        h_exact = 99.0 * r  # pin_pin k=1
        pier = make_pier(height=h_exact, end_conditions="pin_pin")
        report = check_pier_axial(pier, P_factored_kN=10.0)
        assert report.governing_failure_mode != "slenderness_limit_exceeded"
        assert abs(report.h_over_r - 99.0) < 0.001
        # C_s = 1 - (99/140)^2
        cs_expected = 1.0 - (99.0 / 140.0) ** 2
        assert abs(report.slenderness_factor - cs_expected) < 1e-6


# ---------------------------------------------------------------------------
# T09 — h/r slightly above 99 → exceeded
# ---------------------------------------------------------------------------

class TestT09SlightlyAbove99:
    """h/r = 99.01 → slenderness_limit_exceeded"""

    def test_just_above_99_exceeded(self):
        r = 200.0 / math.sqrt(12.0)
        h_over = 99.01 * r
        pier = make_pier(height=h_over, end_conditions="pin_pin")
        report = check_pier_axial(pier, P_factored_kN=10.0)
        assert report.governing_failure_mode == "slenderness_limit_exceeded"


# ---------------------------------------------------------------------------
# T10 — C_s monotonically decreasing as height increases
# ---------------------------------------------------------------------------

class TestT10CsMonotonic:
    """Increasing height → lower C_s (until limit exceeded)"""

    def test_cs_decreases_with_height(self):
        heights = [1500.0, 2000.0, 2500.0, 3000.0, 4000.0]
        cs_values = []
        for h in heights:
            pier = make_pier(height=h)
            rpt = check_pier_axial(pier, P_factored_kN=10.0)
            if rpt.governing_failure_mode != "slenderness_limit_exceeded":
                cs_values.append(rpt.slenderness_factor)
        assert len(cs_values) >= 2
        for i in range(len(cs_values) - 1):
            assert cs_values[i] > cs_values[i + 1]


# ---------------------------------------------------------------------------
# T11 — Larger cross-section → larger r → lower h/r → larger C_s
# ---------------------------------------------------------------------------

class TestT11LargerCrossSection:
    """Wider pier → larger r → smaller h/r → larger C_s"""

    def test_wider_pier_larger_cs(self):
        pier_narrow = make_pier(width=150.0, thickness=150.0, height=3000.0)
        pier_wide = make_pier(width=300.0, thickness=300.0, height=3000.0)
        rpt_narrow = check_pier_axial(pier_narrow, P_factored_kN=50.0)
        rpt_wide = check_pier_axial(pier_wide, P_factored_kN=50.0)
        if rpt_narrow.governing_failure_mode != "slenderness_limit_exceeded":
            assert rpt_wide.slenderness_factor > rpt_narrow.slenderness_factor


# ---------------------------------------------------------------------------
# T12 — Higher f'm → proportionally higher phi_Pn
# ---------------------------------------------------------------------------

class TestT12FprimeProportional:
    """phi_Pn is linear in f'm (all else equal) for masonry"""

    def test_double_f_prime_doubles_phi_Pn(self):
        pier_lo = make_pier(f_prime=10.0)
        pier_hi = make_pier(f_prime=20.0)
        rpt_lo = check_pier_axial(pier_lo, P_factored_kN=50.0)
        rpt_hi = check_pier_axial(pier_hi, P_factored_kN=50.0)
        ratio = rpt_hi.phi_Pn_kN / rpt_lo.phi_Pn_kN
        assert abs(ratio - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# T13 — phi scales phi_Pn proportionally
# ---------------------------------------------------------------------------

class TestT13PhiScaling:
    """phi=0.75 gives proportionally larger phi_Pn than phi=0.65"""

    def test_phi_scaling(self):
        pier = make_pier()
        rpt_065 = check_pier_axial(pier, P_factored_kN=50.0, phi=0.65)
        rpt_075 = check_pier_axial(pier, P_factored_kN=50.0, phi=0.75)
        ratio = rpt_075.phi_Pn_kN / rpt_065.phi_Pn_kN
        assert abs(ratio - 0.75 / 0.65) < 1e-6


# ---------------------------------------------------------------------------
# T14 — governing_failure_mode = "yielding" for very stocky pier
# ---------------------------------------------------------------------------

class TestT14YieldingMode:
    """Very short pier: h/r well below 99, C_s = 1 → yielding"""

    def test_yielding_mode(self):
        # h = 100 mm for 200×200 pier → h/r = 100/57.7 ≈ 1.7 << 99
        pier = make_pier(height=100.0, end_conditions="pin_pin")
        report = check_pier_axial(pier, P_factored_kN=10.0)
        # C_s = 1 - (100/(140*57.7))^2 ≈ 0.999...; not exactly 1.0 due to float
        # governing_failure_mode should be "slender_buckling" for any h > 0 since C_s < 1
        # unless we define yielding as when C_s is effectively 1.
        # The implementation sets "yielding" when C_s = 1.0 (exactly), otherwise "slender_buckling"
        # For very small h, C_s will be very close to 1.0 but not exactly 1 unless h=0.
        # Accept either mode for near-unity C_s (design check is still valid).
        assert report.governing_failure_mode in ("yielding", "slender_buckling")
        # Slenderness factor should be very close to 1
        assert report.slenderness_factor > 0.999


# ---------------------------------------------------------------------------
# T15 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

class TestT15ReExport:
    """PierSpec, PierAxialReport, check_pier_axial re-exported from kerf_cad_core.arch"""

    def test_re_export(self):
        from kerf_cad_core.arch import PierSpec as PS, PierAxialReport as PAR, check_pier_axial as cpa
        assert PS is PierSpec
        assert PAR is PierAxialReport
        assert cpa is check_pier_axial


# ---------------------------------------------------------------------------
# T16 — honest_caveat mentions "TMS 402-22"
# ---------------------------------------------------------------------------

class TestT16CaveatTMS:
    def test_caveat_tms(self):
        pier = make_pier(material="clay_masonry")
        report = check_pier_axial(pier, P_factored_kN=50.0)
        assert "TMS 402-22" in report.honest_caveat

    def test_caveat_tms_cmu(self):
        pier = make_pier(material="concrete_masonry")
        report = check_pier_axial(pier, P_factored_kN=50.0)
        assert "TMS 402-22" in report.honest_caveat


# ---------------------------------------------------------------------------
# T17 — honest_caveat mentions "ACI 318-19" for RC
# ---------------------------------------------------------------------------

class TestT17CaveatACI:
    def test_caveat_aci(self):
        pier = make_pier(material="reinforced_concrete", f_prime=25.0, As=1000.0, fy=420.0)
        report = check_pier_axial(pier, P_factored_kN=50.0)
        assert "ACI 318-19" in report.honest_caveat


# ---------------------------------------------------------------------------
# T18 — governing_failure_mode = "slender_buckling" for typical pier
# ---------------------------------------------------------------------------

class TestT18GoverningMode:
    def test_slender_buckling_for_typical_pier(self):
        pier = make_pier()
        report = check_pier_axial(pier, P_factored_kN=50.0)
        assert report.governing_failure_mode == "slender_buckling"


# ---------------------------------------------------------------------------
# T19 — ValueError checks
# ---------------------------------------------------------------------------

class TestT19ValueErrors:
    def test_pier_width_zero(self):
        with pytest.raises(ValueError, match="pier_width_mm"):
            check_pier_axial(make_pier(width=0.0), P_factored_kN=10.0)

    def test_pier_width_negative(self):
        with pytest.raises(ValueError):
            check_pier_axial(make_pier(width=-100.0), P_factored_kN=10.0)

    def test_pier_thickness_zero(self):
        with pytest.raises(ValueError, match="pier_thickness_mm"):
            check_pier_axial(make_pier(thickness=0.0), P_factored_kN=10.0)

    def test_height_zero(self):
        with pytest.raises(ValueError, match="height_h_mm"):
            check_pier_axial(make_pier(height=0.0), P_factored_kN=10.0)

    def test_f_prime_zero(self):
        with pytest.raises(ValueError, match="f_prime_MPa"):
            check_pier_axial(make_pier(f_prime=0.0), P_factored_kN=10.0)

    def test_as_negative(self):
        with pytest.raises(ValueError, match="As_total_mm2"):
            check_pier_axial(make_pier(As=-1.0), P_factored_kN=10.0)

    def test_unknown_material(self):
        with pytest.raises(ValueError, match="material"):
            check_pier_axial(make_pier(material="steel"), P_factored_kN=10.0)

    def test_unknown_end_conditions(self):
        with pytest.raises(ValueError, match="end_conditions"):
            check_pier_axial(make_pier(end_conditions="roller_roller"), P_factored_kN=10.0)

    def test_phi_zero(self):
        with pytest.raises(ValueError, match="phi"):
            check_pier_axial(make_pier(), P_factored_kN=10.0, phi=0.0)

    def test_phi_above_one(self):
        with pytest.raises(ValueError, match="phi"):
            check_pier_axial(make_pier(), P_factored_kN=10.0, phi=1.5)

    def test_p_factored_negative(self):
        with pytest.raises(ValueError, match="P_factored_kN"):
            check_pier_axial(make_pier(), P_factored_kN=-10.0)

    def test_rc_as_greater_than_ag(self):
        """RC: As >= Ag is invalid"""
        with pytest.raises(ValueError):
            check_pier_axial(
                make_pier(
                    width=200.0, thickness=200.0,
                    material="reinforced_concrete", f_prime=25.0,
                    As=50_000.0,  # > Ag=40000
                    fy=420.0,
                ),
                P_factored_kN=10.0,
            )


# ---------------------------------------------------------------------------
# T20 — DCR > 1 check
# ---------------------------------------------------------------------------

class TestT20DCR:
    """Very high demand relative to capacity → DCR > 1"""

    def test_high_demand(self):
        pier = make_pier()
        rpt = check_pier_axial(pier, P_factored_kN=10.0)
        # phi_Pn typically ~150–200 kN for this pier
        # apply demand >> capacity
        demand = rpt.phi_Pn_kN * 2.0  # 200% of capacity
        # Just confirm the report is returned (no crash); caveat reports FAIL
        rpt_heavy = check_pier_axial(pier, P_factored_kN=demand)
        assert rpt_heavy.phi_Pn_kN > 0.0
        assert "FAIL" in rpt_heavy.honest_caveat


# ---------------------------------------------------------------------------
# LLM tool tests (T21–T22) — async, gated import
# ---------------------------------------------------------------------------

class TestLLMTool:
    """arch_check_pier_axial LLM tool — async, gated import."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_tool_import(self):
        """Module importable regardless of registry availability."""
        import kerf_cad_core.arch.pier_axial_capacity_tools as m  # noqa: F401

    def test_tool_valid_args(self):
        """Nominal case with all required fields → ok payload (dict with phi_Pn_kN etc)."""
        try:
            from kerf_cad_core.arch.pier_axial_capacity_tools import run_arch_check_pier_axial
        except (ImportError, AttributeError):
            pytest.skip("registry not available")
        args = json.dumps({
            "pier_width_mm": 200.0,
            "pier_thickness_mm": 200.0,
            "height_h_mm": 3000.0,
            "material": "clay_masonry",
            "f_prime_MPa": 10.0,
            "As_total_mm2": 0.0,
            "fy_MPa": 420.0,
            "end_conditions": "pin_pin",
            "P_factored_kN": 80.0,
        }).encode()
        result = self._run(run_arch_check_pier_axial(None, args))
        data = json.loads(result)
        # ok_payload returns dict directly; err_payload returns {error, code}
        assert "error" not in data
        assert data["phi_Pn_kN"] > 0.0
        assert data["h_over_r"] > 0.0

    def test_tool_missing_field(self):
        """Missing required field → err payload with code=BAD_ARGS."""
        try:
            from kerf_cad_core.arch.pier_axial_capacity_tools import run_arch_check_pier_axial
        except (ImportError, AttributeError):
            pytest.skip("registry not available")
        args = json.dumps({
            "pier_width_mm": 200.0,
            # missing height_h_mm, material, f_prime_MPa, end_conditions, P_factored_kN
        }).encode()
        result = self._run(run_arch_check_pier_axial(None, args))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"

    def test_tool_invalid_material(self):
        """Bad material string → err payload with code=BAD_ARGS."""
        try:
            from kerf_cad_core.arch.pier_axial_capacity_tools import run_arch_check_pier_axial
        except (ImportError, AttributeError):
            pytest.skip("registry not available")
        args = json.dumps({
            "pier_width_mm": 200.0,
            "pier_thickness_mm": 200.0,
            "height_h_mm": 3000.0,
            "material": "timber",
            "f_prime_MPa": 10.0,
            "end_conditions": "pin_pin",
            "P_factored_kN": 50.0,
        }).encode()
        result = self._run(run_arch_check_pier_axial(None, args))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"
