"""
Tests for kerf_cad_core.arch.bearing_wall_axial — ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in mm, stresses in MPa, forces in kN/m.

Oracle reference (primary test case T01):
  wall_thickness_t_mm = 200 mm, wall_height_h_mm = 3000 mm
  material = "concrete", f_prime_MPa = 25 MPa
  end_conditions = "pin_pin" → k = 1.0
  eccentricity_e_mm = 0 (e ≤ t/6 = 33.33 mm ✓)
  phi = 0.65

  k·lc / (32·t) = 1.0×3000 / (32×200) = 0.46875
  slenderness_factor = 1 − 0.46875² = 0.780273...
  Ag = 200 × 1000 = 200 000 mm²/m
  Pn = 0.55 × 25 × 200 000 × 0.780273 / 1000 = 2145.75 kN/m
  φ·Pn = 0.65 × 2145.75 = 1394.74 kN/m

  For P = 1000 kN/m: DCR = 1000 / 1394.74 ≈ 0.717 → adequate

Coverage:
  T01  Primary oracle: 200mm wall, h=3000mm, fc=25MPa, pin-pin, P=1000kN/m
       → slenderness_factor≈0.780273, φ·Pn≈1394.74 kN/m, DCR≈0.717, adequate
  T02  P=1000kN/m → DCR < 1.0, adequate=True
  T03  Cantilever (k=2.0) reduces φ·Pn significantly vs pin-pin
  T04  fixed_fixed (k=0.8) gives larger φ·Pn than pin_pin for same geometry
  T05  e > t/6 → governing_check = "large_eccentricity_method_required"
  T06  e > t/6 → adequate = False and phi_Pn_kN_per_m = 0
  T07  e ≤ t/6 → eccentricity OK, proceeds to capacity calculation
  T08  clay_masonry material → TMS 402-22 §8.3 formula; r=t/√12
  T09  concrete_masonry material → same TMS formula as clay_masonry
  T10  Masonry oracle: 200mm, h=3000mm, f'm=10MPa, pin-pin → φ·Pn≈896.7 kN/m
  T11  TMS h_eff/r > 99 → slenderness_limit_exceeded, φ·Pn=0, adequate=False
  T12  TMS h_eff/r exactly 99 → NOT exceeded (boundary condition, C_s computed)
  T13  DCR > 1.0 → governing_check = "dcr_exceeded", adequate = False
  T14  P=0 → DCR=0, adequate=True (zero load case)
  T15  reinforced_concrete material accepted; As_per_m flagged in caveat but not credited
  T16  Re-export from arch/__init__.py works
  T17  honest_caveat mentions "ACI 318-19"
  T18  honest_caveat mentions "TMS 402-22" for masonry
  T19  slenderness_factor monotonically decreasing as height increases
  T20  larger k (cantilever) → smaller slenderness_factor than smaller k (pin-pin)
  T21  phi parameter scales φ·Pn proportionally
  T22  higher f_prime_MPa → proportionally higher φ·Pn (linearity)
  T23  ValueError: wall_thickness_t_mm <= 0
  T24  ValueError: wall_height_h_mm <= 0
  T25  ValueError: wall_length_lw_m <= 0
  T26  ValueError: f_prime_MPa <= 0
  T27  ValueError: As_per_m < 0
  T28  ValueError: unknown material
  T29  ValueError: unknown end_conditions
  T30  ValueError: phi out of range (> 1.0)
  T31  ValueError: phi <= 0
  T32  ValueError: P_factored_kN_per_m < 0
  T33  ValueError: eccentricity_e_mm < 0
  T34  e > t/6 AND P > φ·Pn_equivalent → governing_check includes large_eccentricity
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.bearing_wall_axial import (
    BearingWallSpec,
    BearingWallReport,
    check_bearing_wall,
)


# ---------------------------------------------------------------------------
# Helper: expected φ·Pn for ACI §11.5.3.1 (concrete)
# ---------------------------------------------------------------------------

def _aci_phi_pn(t_mm: float, h_mm: float, fc_MPa: float, k: float, phi: float) -> float:
    """Compute ACI §11.5.3.1 φ·Pn (kN/m) directly."""
    Ag = t_mm * 1_000.0  # mm²/m
    slend = max(0.0, 1.0 - (k * h_mm / (32.0 * t_mm)) ** 2)
    return phi * 0.55 * fc_MPa * Ag * slend / 1_000.0


def _tms_phi_pn(t_mm: float, h_mm: float, fm_MPa: float, k: float, phi: float) -> float:
    """Compute TMS 402-22 §8.3 φ·Pn (kN/m) directly (rectangular section)."""
    r = t_mm / math.sqrt(12.0)
    h_eff = k * h_mm
    h_over_r = h_eff / r
    if h_over_r > 99.0:
        return 0.0
    Ag = t_mm * 1_000.0
    slend = max(0.0, 1.0 - (h_eff / (140.0 * r)) ** 2)
    return phi * 0.80 * fm_MPa * Ag * slend / 1_000.0


# ---------------------------------------------------------------------------
# T01: Primary oracle (ACI §11.5.3.1, concrete, pin-pin)
# ---------------------------------------------------------------------------

class TestT01PrimaryOracle:
    def setup_method(self):
        self.spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        self.P = 1000.0
        self.report = check_bearing_wall(self.spec, self.P)

    def test_slenderness_factor(self):
        # k·lc/(32·t) = 1.0×3000/(32×200) = 0.46875; factor = 1 - 0.46875^2
        expected = 1.0 - (0.46875 ** 2)
        assert abs(self.report.slenderness_factor - expected) < 1e-9

    def test_phi_pn(self):
        expected = _aci_phi_pn(200.0, 3000.0, 25.0, 1.0, 0.65)
        assert abs(self.report.phi_Pn_kN_per_m - expected) < 0.01

    def test_phi_pn_approx_1394(self):
        # Task spec states ~1394.6 kN/m; exact is ~1394.74 kN/m
        assert 1394.0 < self.report.phi_Pn_kN_per_m < 1396.0

    def test_dcr_approx_0_717(self):
        expected_dcr = 1000.0 / _aci_phi_pn(200.0, 3000.0, 25.0, 1.0, 0.65)
        assert abs(self.report.dcr - expected_dcr) < 0.001

    def test_adequate_true(self):
        assert self.report.adequate is True

    def test_governing_check_ok(self):
        assert self.report.governing_check == "OK"

    def test_is_bearing_wall_report(self):
        assert isinstance(self.report, BearingWallReport)


# ---------------------------------------------------------------------------
# T02: P=1000 kN/m adequate check
# ---------------------------------------------------------------------------

class TestT02AdequacyDCR:
    def test_dcr_less_than_one(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 1000.0)
        assert report.dcr < 1.0
        assert report.adequate is True


# ---------------------------------------------------------------------------
# T03: Cantilever end condition reduces φ·Pn
# ---------------------------------------------------------------------------

class TestT03Cantilever:
    def test_cantilever_lower_phi_pn_than_pin_pin(self):
        spec_pp = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        spec_cant = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="cantilever",
        )
        report_pp = check_bearing_wall(spec_pp, 100.0)
        report_cant = check_bearing_wall(spec_cant, 100.0)
        assert report_cant.phi_Pn_kN_per_m < report_pp.phi_Pn_kN_per_m

    def test_cantilever_phi_pn_value(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="cantilever",
        )
        report = check_bearing_wall(spec, 100.0)
        expected = _aci_phi_pn(200.0, 3000.0, 25.0, 2.0, 0.65)
        assert abs(report.phi_Pn_kN_per_m - expected) < 0.01
        # Oracle: ~216.5 kN/m
        assert 210.0 < report.phi_Pn_kN_per_m < 225.0


# ---------------------------------------------------------------------------
# T04: fixed_fixed gives larger φ·Pn than pin_pin
# ---------------------------------------------------------------------------

class TestT04FixedFixed:
    def test_fixed_fixed_larger_phi_pn(self):
        spec_pp = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        spec_ff = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="fixed_fixed",
        )
        report_pp = check_bearing_wall(spec_pp, 100.0)
        report_ff = check_bearing_wall(spec_ff, 100.0)
        assert report_ff.phi_Pn_kN_per_m > report_pp.phi_Pn_kN_per_m

    def test_fixed_fixed_phi_pn_value(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="fixed_fixed",
        )
        report = check_bearing_wall(spec, 100.0)
        expected = _aci_phi_pn(200.0, 3000.0, 25.0, 0.8, 0.65)
        assert abs(report.phi_Pn_kN_per_m - expected) < 0.01
        # Oracle: ~1536.1 kN/m
        assert 1530.0 < report.phi_Pn_kN_per_m < 1545.0


# ---------------------------------------------------------------------------
# T05: Large eccentricity → governing_check flag
# ---------------------------------------------------------------------------

class TestT05LargeEccentricity:
    def test_e_greater_than_t_over_6_flag(self):
        # t=200mm → t/6 = 33.33mm; e=40mm > 33.33mm
        # phi_Pn is set to 0 when large eccentricity, so dcr=inf → combined flag
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
            eccentricity_e_mm=40.0,
        )
        report = check_bearing_wall(spec, 100.0)
        assert "large_eccentricity" in report.governing_check

    def test_governing_check_large_eccentricity_string(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
            eccentricity_e_mm=50.0,
        )
        report = check_bearing_wall(spec, 0.0)
        assert "large_eccentricity" in report.governing_check


# ---------------------------------------------------------------------------
# T06: Large eccentricity → adequate=False and phi_Pn=0
# ---------------------------------------------------------------------------

class TestT06LargeEccentricityAdequacy:
    def test_adequate_false(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
            eccentricity_e_mm=40.0,
        )
        report = check_bearing_wall(spec, 100.0)
        assert report.adequate is False
        assert report.phi_Pn_kN_per_m == 0.0


# ---------------------------------------------------------------------------
# T07: e exactly equal to t/6 → NOT large eccentricity
# ---------------------------------------------------------------------------

class TestT07EccentricityBoundary:
    def test_e_exactly_t_over_6_ok(self):
        # t=180mm → t/6 = 30mm exactly
        spec = BearingWallSpec(
            wall_thickness_t_mm=180.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
            eccentricity_e_mm=30.0,  # exactly t/6
        )
        report = check_bearing_wall(spec, 100.0)
        # e == t/6 is the boundary: NOT large eccentricity (e > t/6 is the threshold)
        assert "large_eccentricity" not in report.governing_check
        assert report.phi_Pn_kN_per_m > 0.0


# ---------------------------------------------------------------------------
# T08: clay_masonry → TMS 402-22 §8.3 formula
# ---------------------------------------------------------------------------

class TestT08ClayMasonry:
    def test_clay_masonry_uses_tms_formula(self):
        # For clay masonry the TMS formula differs from ACI §11.5.3.1
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 100.0)
        expected = _tms_phi_pn(200.0, 3000.0, 10.0, 1.0, 0.65)
        assert abs(report.phi_Pn_kN_per_m - expected) < 0.01

    def test_clay_masonry_caveat_mentions_tms(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 100.0)
        assert "TMS 402-22" in report.honest_caveat


# ---------------------------------------------------------------------------
# T09: concrete_masonry → same TMS formula as clay_masonry
# ---------------------------------------------------------------------------

class TestT09ConcreteMasonry:
    def test_concrete_masonry_equal_to_clay_masonry(self):
        # Same formula; same numbers (just different material tag)
        spec_clay = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=12.0,
            end_conditions="pin_pin",
        )
        spec_cmu = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete_masonry",
            f_prime_MPa=12.0,
            end_conditions="pin_pin",
        )
        r_clay = check_bearing_wall(spec_clay, 100.0)
        r_cmu = check_bearing_wall(spec_cmu, 100.0)
        assert abs(r_clay.phi_Pn_kN_per_m - r_cmu.phi_Pn_kN_per_m) < 1e-9


# ---------------------------------------------------------------------------
# T10: Masonry oracle: 200mm, h=3000mm, f'm=10MPa, pin-pin
# ---------------------------------------------------------------------------

class TestT10MasonryOracle:
    def test_masonry_phi_pn(self):
        # r = 200/√12 ≈ 57.735; h_eff = 3000; h_eff/r ≈ 51.96
        # C_s = 1 - (3000/(140×57.735))² ≈ 0.8622
        # φ·Pn = 0.65 × 0.80 × 10 × 200000 × 0.8622 / 1000 ≈ 896.7 kN/m
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 500.0)
        expected = _tms_phi_pn(200.0, 3000.0, 10.0, 1.0, 0.65)
        assert abs(report.phi_Pn_kN_per_m - expected) < 0.1
        # Approx 896.7 kN/m
        assert 890.0 < report.phi_Pn_kN_per_m < 905.0


# ---------------------------------------------------------------------------
# T11: TMS h_eff/r > 99 → slenderness_limit_exceeded
# ---------------------------------------------------------------------------

class TestT11TMSSlendernessLimit:
    def test_slenderness_limit_exceeded(self):
        # t=100mm, h=large (e.g. h=60000mm), pin-pin → h_eff/r >> 99
        # r = 100/√12 ≈ 28.87; h_eff = 60000; h/r ≈ 2078 >> 99
        spec = BearingWallSpec(
            wall_thickness_t_mm=100.0,
            wall_height_h_mm=60_000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 0.0)
        assert report.governing_check == "slenderness_limit_exceeded"
        assert report.phi_Pn_kN_per_m == 0.0
        assert report.adequate is False

    def test_slenderness_limit_exceeded_slenderness_factor_zero(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=100.0,
            wall_height_h_mm=60_000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 0.0)
        assert report.slenderness_factor == 0.0


# ---------------------------------------------------------------------------
# T12: TMS h_eff/r exactly 99 → NOT exceeded
# ---------------------------------------------------------------------------

class TestT12TMSSlendernessExactBoundary:
    def test_h_over_r_exactly_99_not_exceeded(self):
        # r = t/√12; need h_eff/r = 99 exactly → h = 99 × r / k
        # For t=200mm, k=1.0: r=200/√12≈57.735; h=99×57.735=5715.8mm
        t = 200.0
        k = 1.0
        r = t / math.sqrt(12.0)
        h = 99.0 * r / k  # exactly h_eff/r = 99
        spec = BearingWallSpec(
            wall_thickness_t_mm=t,
            wall_height_h_mm=h,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 0.0)
        assert report.governing_check != "slenderness_limit_exceeded"
        assert report.phi_Pn_kN_per_m > 0.0
        # slenderness factor at h/r=99: 1 - (99/140)^2 = 1 - 0.5002 = 0.4998
        expected_slend = max(0.0, 1.0 - (99.0 / 140.0) ** 2)
        assert abs(report.slenderness_factor - expected_slend) < 1e-9


# ---------------------------------------------------------------------------
# T13: DCR > 1.0 → governing_check = "dcr_exceeded"
# ---------------------------------------------------------------------------

class TestT13DCRExceeded:
    def test_dcr_exceeded(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        # φ·Pn ≈ 1394.74 kN/m; P=2000 kN/m >> capacity
        report = check_bearing_wall(spec, 2000.0)
        assert report.dcr > 1.0
        assert report.adequate is False
        assert report.governing_check == "dcr_exceeded"


# ---------------------------------------------------------------------------
# T14: P=0 → DCR=0, adequate=True
# ---------------------------------------------------------------------------

class TestT14ZeroLoad:
    def test_zero_load_dcr_zero(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 0.0)
        assert report.dcr == 0.0
        assert report.adequate is True
        assert report.governing_check == "OK"


# ---------------------------------------------------------------------------
# T15: reinforced_concrete accepted; caveat flags rebar not credited
# ---------------------------------------------------------------------------

class TestT15ReinforcedConcrete:
    def test_rc_accepted(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="reinforced_concrete",
            f_prime_MPa=30.0,
            As_per_m=500.0,
            fy_MPa=420.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 500.0)
        assert isinstance(report, BearingWallReport)
        # Uses ACI §11.5.3.1 (plain-wall formula — As not credited)
        expected = _aci_phi_pn(200.0, 3000.0, 30.0, 1.0, 0.65)
        assert abs(report.phi_Pn_kN_per_m - expected) < 0.01

    def test_rc_caveat_mentions_as_not_credited(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="reinforced_concrete",
            f_prime_MPa=30.0,
            As_per_m=500.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 500.0)
        # Caveat must mention that rebar is not credited
        caveat_lower = report.honest_caveat.lower()
        assert "not credited" in caveat_lower or "not credit" in caveat_lower


# ---------------------------------------------------------------------------
# T16: Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

class TestT16ReExport:
    def test_reexport(self):
        from kerf_cad_core.arch import (
            BearingWallSpec as BWSpec,
            BearingWallReport as BWReport,
            check_bearing_wall as cbw,
        )
        spec = BWSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        report = cbw(spec, 500.0)
        assert isinstance(report, BWReport)
        assert report.phi_Pn_kN_per_m > 0.0


# ---------------------------------------------------------------------------
# T17: honest_caveat mentions "ACI 318-19"
# ---------------------------------------------------------------------------

class TestT17CaveatACI:
    def test_caveat_mentions_aci(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 500.0)
        assert "ACI 318-19" in report.honest_caveat


# ---------------------------------------------------------------------------
# T18: honest_caveat mentions "TMS 402-22" for masonry
# ---------------------------------------------------------------------------

class TestT18CaveatTMS:
    def test_caveat_mentions_tms(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="clay_masonry",
            f_prime_MPa=10.0,
            end_conditions="pin_pin",
        )
        report = check_bearing_wall(spec, 100.0)
        assert "TMS 402-22" in report.honest_caveat


# ---------------------------------------------------------------------------
# T19: Slenderness factor decreases as height increases
# ---------------------------------------------------------------------------

class TestT19SlendernessMonotone:
    def test_slenderness_factor_decreasing(self):
        heights = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        factors = []
        for h in heights:
            spec = BearingWallSpec(
                wall_thickness_t_mm=200.0,
                wall_height_h_mm=h,
                wall_length_lw_m=5.0,
                material="concrete",
                f_prime_MPa=25.0,
                end_conditions="pin_pin",
            )
            report = check_bearing_wall(spec, 100.0)
            factors.append(report.slenderness_factor)
        # Each subsequent factor must be <= previous
        for i in range(1, len(factors)):
            assert factors[i] <= factors[i - 1], (
                f"factors[{i}]={factors[i]} is not <= factors[{i-1}]={factors[i-1]}"
            )


# ---------------------------------------------------------------------------
# T20: Larger k → smaller slenderness_factor
# ---------------------------------------------------------------------------

class TestT20KFactorEffect:
    def test_larger_k_smaller_slenderness_factor(self):
        t, h, fc = 200.0, 3000.0, 25.0
        checks = [
            ("fixed_fixed", 0.8),
            ("pin_pin", 1.0),
            ("cantilever", 2.0),
        ]
        factors = []
        for end_cond, _ in checks:
            spec = BearingWallSpec(
                wall_thickness_t_mm=t,
                wall_height_h_mm=h,
                wall_length_lw_m=5.0,
                material="concrete",
                f_prime_MPa=fc,
                end_conditions=end_cond,
            )
            report = check_bearing_wall(spec, 100.0)
            factors.append(report.slenderness_factor)
        # fixed_fixed (k=0.8) > pin_pin (k=1.0) > cantilever (k=2.0)
        assert factors[0] > factors[1] > factors[2]


# ---------------------------------------------------------------------------
# T21: phi scales φ·Pn proportionally
# ---------------------------------------------------------------------------

class TestT21PhiScaling:
    def test_phi_scales_phi_pn(self):
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        r1 = check_bearing_wall(spec, 100.0, phi=0.65)
        r2 = check_bearing_wall(spec, 100.0, phi=0.70)
        ratio = r2.phi_Pn_kN_per_m / r1.phi_Pn_kN_per_m
        assert abs(ratio - 0.70 / 0.65) < 1e-9


# ---------------------------------------------------------------------------
# T22: Higher f'c → proportionally higher φ·Pn
# ---------------------------------------------------------------------------

class TestT22FcProportionality:
    def test_fc_linear(self):
        spec25 = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        spec50 = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=50.0,
            end_conditions="pin_pin",
        )
        r25 = check_bearing_wall(spec25, 100.0)
        r50 = check_bearing_wall(spec50, 100.0)
        ratio = r50.phi_Pn_kN_per_m / r25.phi_Pn_kN_per_m
        assert abs(ratio - 2.0) < 1e-9


# ---------------------------------------------------------------------------
# T23-T33: ValueError cases
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def _base_spec(self, **kwargs) -> dict:
        d = dict(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
        )
        d.update(kwargs)
        return d

    def test_T23_wall_thickness_zero(self):
        with pytest.raises(ValueError, match="wall_thickness_t_mm"):
            spec = BearingWallSpec(**self._base_spec(wall_thickness_t_mm=0.0))
            check_bearing_wall(spec, 100.0)

    def test_T23_wall_thickness_negative(self):
        with pytest.raises(ValueError, match="wall_thickness_t_mm"):
            spec = BearingWallSpec(**self._base_spec(wall_thickness_t_mm=-1.0))
            check_bearing_wall(spec, 100.0)

    def test_T24_wall_height_zero(self):
        with pytest.raises(ValueError, match="wall_height_h_mm"):
            spec = BearingWallSpec(**self._base_spec(wall_height_h_mm=0.0))
            check_bearing_wall(spec, 100.0)

    def test_T25_wall_length_zero(self):
        with pytest.raises(ValueError, match="wall_length_lw_m"):
            spec = BearingWallSpec(**self._base_spec(wall_length_lw_m=0.0))
            check_bearing_wall(spec, 100.0)

    def test_T26_fc_zero(self):
        with pytest.raises(ValueError, match="f_prime_MPa"):
            spec = BearingWallSpec(**self._base_spec(f_prime_MPa=0.0))
            check_bearing_wall(spec, 100.0)

    def test_T27_as_negative(self):
        with pytest.raises(ValueError, match="As_per_m"):
            spec = BearingWallSpec(**self._base_spec(As_per_m=-1.0))
            check_bearing_wall(spec, 100.0)

    def test_T28_unknown_material(self):
        with pytest.raises(ValueError, match="material"):
            spec = BearingWallSpec(**self._base_spec(material="steel"))
            check_bearing_wall(spec, 100.0)

    def test_T29_unknown_end_conditions(self):
        with pytest.raises(ValueError, match="end_conditions"):
            spec = BearingWallSpec(**self._base_spec(end_conditions="free_free"))
            check_bearing_wall(spec, 100.0)

    def test_T30_phi_too_large(self):
        with pytest.raises(ValueError, match="phi"):
            spec = BearingWallSpec(**self._base_spec())
            check_bearing_wall(spec, 100.0, phi=1.1)

    def test_T31_phi_zero(self):
        with pytest.raises(ValueError, match="phi"):
            spec = BearingWallSpec(**self._base_spec())
            check_bearing_wall(spec, 100.0, phi=0.0)

    def test_T32_p_factored_negative(self):
        with pytest.raises(ValueError, match="P_factored"):
            spec = BearingWallSpec(**self._base_spec())
            check_bearing_wall(spec, -1.0)

    def test_T33_eccentricity_negative(self):
        with pytest.raises(ValueError, match="eccentricity_e_mm"):
            spec = BearingWallSpec(**self._base_spec(eccentricity_e_mm=-5.0))
            check_bearing_wall(spec, 100.0)


# ---------------------------------------------------------------------------
# T34: e > t/6 AND demand > capacity-equivalent → large_eccentricity governing
# ---------------------------------------------------------------------------

class TestT34LargeEccentricityAndHighLoad:
    def test_large_ecc_with_high_load_governing_check(self):
        # e=40mm > t/6=33.33mm; large eccentricity governs
        spec = BearingWallSpec(
            wall_thickness_t_mm=200.0,
            wall_height_h_mm=3000.0,
            wall_length_lw_m=5.0,
            material="concrete",
            f_prime_MPa=25.0,
            end_conditions="pin_pin",
            eccentricity_e_mm=40.0,
        )
        report = check_bearing_wall(spec, 2000.0)
        # phi_Pn is 0 (large ecc), dcr is inf
        assert report.phi_Pn_kN_per_m == 0.0
        assert report.dcr == float("inf")
        assert report.adequate is False
        # governing check includes large_eccentricity
        assert "large_eccentricity" in report.governing_check
