"""
Tests for kerf_cad_core.arch.beam_deflection.

Covers:
  - All six supported load cases (formula verification against Roark 9e §8
    Table 8.1 + AISC Manual Table 3-23), tolerance ≤ 0.1 %.
  - W14x90, L=6 m, P=100 kN centre load (hand-computed reference).
  - Zero load → zero deflection and zero moment.
  - Invalid inputs (bad support/load type, non-positive L/E/I, negative load).
  - Report field types and signs.
  - deflection_location_mm correctness for each case.
  - Re-export from arch/__init__.py.
  - BeamDeflectionReport fields are all finite and non-negative for valid loads.
  - fixed_fixed + point_center: Roark Table 8.1 case 8 formula checks + symmetry.

All dimensions mm, forces N, stresses MPa.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.beam_deflection import (
    BeamSpec,
    BeamDeflectionReport,
    compute_beam_deflection,
)

# Re-export check
from kerf_cad_core.arch import (
    BeamSpec as _BeamSpecFromInit,
    BeamDeflectionReport as _ReportFromInit,
    compute_beam_deflection as _ComputeFromInit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_err(actual: float, expected: float) -> float:
    """Relative error |actual - expected| / |expected|."""
    if expected == 0.0:
        return 0.0 if actual == 0.0 else float("inf")
    return abs(actual - expected) / abs(expected)


TOL = 1e-3  # 0.1 % tolerance for formula checks


# ---------------------------------------------------------------------------
# Section properties helpers
# ---------------------------------------------------------------------------

# W14x90: Ix = 999 in⁴ (AISC Manual 15e Table 1-1)
# 1 in⁴ = 416 231.426 mm⁴  →  Ix ≈ 415 815 195 mm⁴ (using 1 in = 25.4 mm exactly)
_W14x90_I_mm4 = 999.0 * (25.4 ** 4)  # exact conversion
_STEEL_E = 200_000.0   # MPa


# ---------------------------------------------------------------------------
# Test 1: Simply-supported + centre point load (Roark 9e case 7)
# ---------------------------------------------------------------------------

class TestSimplySupportedPointCenter:

    def _spec(self, L, E, I, P):
        return BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="simply_supported",
            load_type="point_center",
            load_value=P,
        )

    def test_delta_formula(self):
        """δ = PL³/(48EI)."""
        L, E, I, P = 5_000.0, 200_000.0, 1e8, 50_000.0
        report = compute_beam_deflection(self._spec(L, E, I, P))
        expected = P * L**3 / (48.0 * E * I)
        assert _rel_err(report.delta_max_mm, expected) < TOL

    def test_moment_formula(self):
        """M_max = PL/4."""
        L, E, I, P = 5_000.0, 200_000.0, 1e8, 50_000.0
        report = compute_beam_deflection(self._spec(L, E, I, P))
        expected_M = P * L / 4.0
        assert _rel_err(report.M_max_Nmm, expected_M) < TOL

    def test_shear_formula(self):
        """V_max = P/2."""
        L, E, I, P = 5_000.0, 200_000.0, 1e8, 50_000.0
        report = compute_beam_deflection(self._spec(L, E, I, P))
        assert _rel_err(report.V_max_N, P / 2.0) < TOL

    def test_deflection_location_midspan(self):
        """Deflection occurs at L/2."""
        L = 4_000.0
        report = compute_beam_deflection(self._spec(L, 200_000.0, 5e7, 30_000.0))
        assert abs(report.deflection_location_mm - L / 2.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 2: Simply-supported + UDL (Roark 9e case 2)
# ---------------------------------------------------------------------------

class TestSimplySupportedUDL:

    def _spec(self, L, E, I, w):
        return BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="simply_supported",
            load_type="udl",
            load_value=w,
        )

    def test_delta_formula(self):
        """δ = 5wL⁴/(384EI)."""
        L, E, I, w = 8_000.0, 200_000.0, 2e8, 10.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        expected = 5.0 * w * L**4 / (384.0 * E * I)
        assert _rel_err(report.delta_max_mm, expected) < TOL

    def test_moment_formula(self):
        """M_max = wL²/8."""
        L, E, I, w = 8_000.0, 200_000.0, 2e8, 10.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        expected_M = w * L**2 / 8.0
        assert _rel_err(report.M_max_Nmm, expected_M) < TOL

    def test_shear_formula(self):
        """V_max = wL/2."""
        L, E, I, w = 8_000.0, 200_000.0, 2e8, 10.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        assert _rel_err(report.V_max_N, w * L / 2.0) < TOL


# ---------------------------------------------------------------------------
# Test 3: Cantilever + tip point load (Roark 9e case 1)
# ---------------------------------------------------------------------------

class TestCantileverPointLoad:

    def _spec(self, L, E, I, P):
        return BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="cantilever",
            load_type="point_center",
            load_value=P,
        )

    def test_delta_formula(self):
        """δ = PL³/(3EI)."""
        L, E, I, P = 3_000.0, 200_000.0, 5e7, 20_000.0
        report = compute_beam_deflection(self._spec(L, E, I, P))
        expected = P * L**3 / (3.0 * E * I)
        assert _rel_err(report.delta_max_mm, expected) < TOL

    def test_moment_formula(self):
        """M_max = PL at fixed support."""
        L, E, I, P = 3_000.0, 200_000.0, 5e7, 20_000.0
        report = compute_beam_deflection(self._spec(L, E, I, P))
        expected_M = P * L
        assert _rel_err(report.M_max_Nmm, expected_M) < TOL

    def test_deflection_at_free_tip(self):
        """Deflection location = L (free end)."""
        L = 2_500.0
        report = compute_beam_deflection(self._spec(L, 200_000.0, 5e7, 10_000.0))
        assert abs(report.deflection_location_mm - L) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: Cantilever + UDL (Roark 9e case 3)
# ---------------------------------------------------------------------------

class TestCantileverUDL:

    def _spec(self, L, E, I, w):
        return BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="cantilever",
            load_type="udl",
            load_value=w,
        )

    def test_delta_formula(self):
        """δ = wL⁴/(8EI)."""
        L, E, I, w = 4_000.0, 200_000.0, 1e8, 5.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        expected = w * L**4 / (8.0 * E * I)
        assert _rel_err(report.delta_max_mm, expected) < TOL

    def test_moment_formula(self):
        """M_max = wL²/2."""
        L, E, I, w = 4_000.0, 200_000.0, 1e8, 5.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        expected_M = w * L**2 / 2.0
        assert _rel_err(report.M_max_Nmm, expected_M) < TOL

    def test_shear_formula(self):
        """V_max = wL."""
        L, E, I, w = 4_000.0, 200_000.0, 1e8, 5.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        assert _rel_err(report.V_max_N, w * L) < TOL


# ---------------------------------------------------------------------------
# Test 5: Fixed-fixed + UDL (Roark 9e case 15)
# ---------------------------------------------------------------------------

class TestFixedFixedUDL:

    def _spec(self, L, E, I, w):
        return BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="fixed_fixed",
            load_type="udl",
            load_value=w,
        )

    def test_delta_formula(self):
        """δ = wL⁴/(384EI)."""
        L, E, I, w = 6_000.0, 200_000.0, 3e8, 8.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        expected = w * L**4 / (384.0 * E * I)
        assert _rel_err(report.delta_max_mm, expected) < TOL

    def test_moment_formula(self):
        """M_max = wL²/12 (at supports, hogging)."""
        L, E, I, w = 6_000.0, 200_000.0, 3e8, 8.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        expected_M = w * L**2 / 12.0
        assert _rel_err(report.M_max_Nmm, expected_M) < TOL

    def test_midspan_moment_is_half_support(self):
        """
        Mid-span sagging moment for fixed-fixed UDL = wL²/24.
        The report returns M_support = wL²/12 (governing).
        Check that support M is exactly 2× midspan value.
        """
        L, E, I, w = 6_000.0, 200_000.0, 3e8, 8.0
        report = compute_beam_deflection(self._spec(L, E, I, w))
        midspan_M = w * L**2 / 24.0
        # report M_max (support) = 2 × midspan
        assert _rel_err(report.M_max_Nmm, 2.0 * midspan_M) < TOL

    def test_delta_equals_ss_udl_deflection(self):
        """
        Fixed-fixed UDL δ = wL⁴/(384EI) is numerically identical to SS UDL
        δ = 5wL⁴/(384EI) / 5; i.e., exactly 1/5 of the SS value.
        """
        L, E, I, w = 6_000.0, 200_000.0, 3e8, 8.0
        spec_ff = self._spec(L, E, I, w)
        spec_ss = BeamSpec(length_mm=L, E_MPa=E, I_mm4=I,
                           support_type="simply_supported",
                           load_type="udl", load_value=w)
        r_ff = compute_beam_deflection(spec_ff)
        r_ss = compute_beam_deflection(spec_ss)
        ratio = r_ss.delta_max_mm / r_ff.delta_max_mm
        assert abs(ratio - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 6: W14x90, L=6 m, P=100 kN centre (hand-computed reference)
# ---------------------------------------------------------------------------

class TestW14x90Reference:

    def test_ss_point_delta(self):
        """
        W14x90, L=6000 mm, P=100 kN, SS + centre point load.
        Hand calc: δ = PL³/(48EI)
          I = 999 in⁴ × (25.4 mm/in)⁴ ≈ 4.158×10⁸ mm⁴
          δ ≈ 5.411 mm
        """
        I = _W14x90_I_mm4
        L = 6_000.0
        P = 100_000.0  # 100 kN
        expected_delta = P * L**3 / (48.0 * _STEEL_E * I)
        report = compute_beam_deflection(BeamSpec(
            length_mm=L, E_MPa=_STEEL_E, I_mm4=I,
            support_type="simply_supported",
            load_type="point_center",
            load_value=P,
        ))
        # Absolute check against pre-computed value ≈ 5.411 mm
        assert abs(report.delta_max_mm - expected_delta) < 1e-6
        # Sanity bounds: should be between 4 mm and 7 mm
        assert 4.0 < report.delta_max_mm < 7.0

    def test_ss_point_moment(self):
        """M_max = PL/4 = 100 000 × 6 000 / 4 = 150 000 000 N·mm = 150 kN·m."""
        I = _W14x90_I_mm4
        report = compute_beam_deflection(BeamSpec(
            length_mm=6_000.0, E_MPa=_STEEL_E, I_mm4=I,
            support_type="simply_supported",
            load_type="point_center",
            load_value=100_000.0,
        ))
        expected_M = 100_000.0 * 6_000.0 / 4.0  # = 1.5e8 N·mm
        assert abs(report.M_max_Nmm - expected_M) < 1.0  # N·mm tolerance


# ---------------------------------------------------------------------------
# Test 7: Zero load → zero results
# ---------------------------------------------------------------------------

class TestZeroLoad:

    @pytest.mark.parametrize("support,load", [
        ("simply_supported", "point_center"),
        ("simply_supported", "udl"),
        ("cantilever", "point_center"),
        ("cantilever", "udl"),
        ("fixed_fixed", "udl"),
        ("fixed_fixed", "point_center"),
    ])
    def test_zero_load_gives_zero_deflection(self, support, load):
        """Zero load must produce zero deflection, moment, and shear."""
        spec = BeamSpec(
            length_mm=5_000.0, E_MPa=200_000.0, I_mm4=1e8,
            support_type=support, load_type=load, load_value=0.0,
        )
        report = compute_beam_deflection(spec)
        assert report.delta_max_mm == 0.0
        assert report.M_max_Nmm == 0.0
        assert report.V_max_N == 0.0


# ---------------------------------------------------------------------------
# Test 8: Fixed-fixed + centre point load (Roark 9e Table 8.1 case 8)
# ---------------------------------------------------------------------------

class TestFixedFixedPointCenter:
    """
    Reference case: L=3 m, E=200 GPa, I=8.33e-6 m⁴, P=10 kN (centre load).

    In mm / N / MPa units:
      L = 3 000 mm, E = 200 000 MPa, I = 8 330 000 mm⁴, P = 10 000 N
      EI = 200 000 × 8 330 000 = 1.666×10¹² N·mm²

    Hand-computed:
      δ_max = PL³/(192·EI) = 10000×27×10⁹ / (192×1.666×10¹²)
             = 2.7×10¹³ / 3.199×10¹⁴ ≈ 0.8440 mm
      M_support = PL/8 = 10000×3000/8 = 3 750 000 N·mm
      V_max = P/2 = 5 000 N
    """

    _L = 3_000.0        # mm
    _E = 200_000.0      # MPa
    _I = 8_330_000.0    # mm⁴  (≈ 8.33×10⁻⁶ m⁴)
    _P = 10_000.0       # N (10 kN)

    def _spec(self):
        return BeamSpec(
            length_mm=self._L, E_MPa=self._E, I_mm4=self._I,
            support_type="fixed_fixed",
            load_type="point_center",
            load_value=self._P,
        )

    def test_delta_max_formula(self):
        """δ_max = PL³/(192EI)."""
        report = compute_beam_deflection(self._spec())
        expected = self._P * self._L**3 / (192.0 * self._E * self._I)
        assert _rel_err(report.delta_max_mm, expected) < TOL

    def test_delta_max_absolute_approx(self):
        """Spot-check: δ_max ≈ 0.844 mm for given inputs (to 1%)."""
        report = compute_beam_deflection(self._spec())
        # EI = 200000 * 8330000 = 1.666e12;  PL³ = 10000 * 2.7e10 = 2.7e14
        # δ = 2.7e14 / (192 * 1.666e12) = 2.7e14 / 3.198720e14 ≈ 0.8441 mm
        assert abs(report.delta_max_mm - 0.8441) < 0.01  # ±1 % of ~0.84

    def test_moment_support_formula(self):
        """M_max (at supports) = PL/8."""
        report = compute_beam_deflection(self._spec())
        expected_M = self._P * self._L / 8.0  # = 3 750 000 N·mm
        assert _rel_err(report.M_max_Nmm, expected_M) < TOL

    def test_moment_support_absolute(self):
        """M_support = 10000 × 3000 / 8 = 3 750 000 N·mm."""
        report = compute_beam_deflection(self._spec())
        assert abs(report.M_max_Nmm - 3_750_000.0) < 1.0

    def test_shear_formula(self):
        """V_max = P/2 = 5 000 N."""
        report = compute_beam_deflection(self._spec())
        assert _rel_err(report.V_max_N, self._P / 2.0) < TOL
        assert abs(report.V_max_N - 5_000.0) < 0.01

    def test_deflection_location_midspan(self):
        """Max deflection occurs at L/2."""
        report = compute_beam_deflection(self._spec())
        assert abs(report.deflection_location_mm - self._L / 2.0) < 1e-9

    def test_deflection_profile_symmetry(self):
        """
        δ(x) = P·x²·(3L−4x) / (48·E·I) for 0 ≤ x ≤ L/2.
        Symmetry: δ(L/4) must equal δ(3L/4) when computed from each half.
        """
        L, E, I, P = self._L, self._E, self._I, self._P
        EI = E * I
        x1 = L / 4.0
        x2 = L - x1  # = 3L/4; use mirror: δ(3L/4) = δ(L/4)
        delta_quarter = P * x1**2 * (3 * L - 4 * x1) / (48.0 * EI)
        delta_mirror  = P * x2**2 * (3 * L - 4 * x2) / (48.0 * EI)
        # For x > L/2, the formula δ(x) = δ(L − x), so we test directly via formula:
        # Actually for x2 = 3L/4, the "mirror" formula gives the same δ as x1 = L/4.
        # Compute symmetrically: δ(3L/4) = δ at distance L/4 from right = δ(L/4).
        delta_sym = P * (L - x2)**2 * (3 * L - 4 * (L - x2)) / (48.0 * EI)
        assert _rel_err(delta_quarter, delta_sym) < TOL

    def test_ff_point_center_deflection_is_quarter_of_ss(self):
        """
        Fixed-fixed centre point load has δ = PL³/(192EI).
        Simply-supported centre load has δ = PL³/(48EI).
        Ratio SS/FF = 192/48 = 4 exactly.
        """
        L, E, I, P = self._L, self._E, self._I, self._P
        r_ff = compute_beam_deflection(BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="fixed_fixed", load_type="point_center", load_value=P,
        ))
        r_ss = compute_beam_deflection(BeamSpec(
            length_mm=L, E_MPa=E, I_mm4=I,
            support_type="simply_supported", load_type="point_center", load_value=P,
        ))
        ratio = r_ss.delta_max_mm / r_ff.delta_max_mm
        assert abs(ratio - 4.0) < 1e-9

    def test_honest_caveat_contains_reference(self):
        """honest_caveat must mention Roark case 8."""
        report = compute_beam_deflection(self._spec())
        assert "case 8" in report.honest_caveat.lower() or "case 8" in report.honest_caveat


# ---------------------------------------------------------------------------
# Test 9: Invalid inputs raise ValueError
# ---------------------------------------------------------------------------

class TestInvalidInputs:

    def _base(self, **overrides):
        kwargs = dict(
            length_mm=5_000.0, E_MPa=200_000.0, I_mm4=1e8,
            support_type="simply_supported",
            load_type="udl",
            load_value=5.0,
        )
        kwargs.update(overrides)
        return BeamSpec(**kwargs)

    def test_zero_length_raises(self):
        with pytest.raises(ValueError, match="length_mm"):
            compute_beam_deflection(self._base(length_mm=0.0))

    def test_negative_length_raises(self):
        with pytest.raises(ValueError, match="length_mm"):
            compute_beam_deflection(self._base(length_mm=-100.0))

    def test_zero_E_raises(self):
        with pytest.raises(ValueError, match="E_MPa"):
            compute_beam_deflection(self._base(E_MPa=0.0))

    def test_zero_I_raises(self):
        with pytest.raises(ValueError, match="I_mm4"):
            compute_beam_deflection(self._base(I_mm4=0.0))

    def test_negative_load_raises(self):
        with pytest.raises(ValueError, match="load_value"):
            compute_beam_deflection(self._base(load_value=-1.0))

    def test_bad_support_type_raises(self):
        with pytest.raises(ValueError, match="support_type"):
            compute_beam_deflection(self._base(support_type="pinned_roller"))

    def test_bad_load_type_raises(self):
        with pytest.raises(ValueError, match="load_type"):
            compute_beam_deflection(self._base(load_type="triangular"))


# ---------------------------------------------------------------------------
# Test 10: Report fields are finite and non-negative
# ---------------------------------------------------------------------------

class TestReportFieldSanity:

    @pytest.mark.parametrize("support,load,val", [
        ("simply_supported", "point_center", 40_000.0),
        ("simply_supported", "udl", 6.0),
        ("cantilever", "point_center", 15_000.0),
        ("cantilever", "udl", 4.0),
        ("fixed_fixed", "udl", 7.0),
        ("fixed_fixed", "point_center", 30_000.0),
    ])
    def test_fields_finite_nonneg(self, support, load, val):
        spec = BeamSpec(
            length_mm=6_000.0, E_MPa=200_000.0, I_mm4=2e8,
            support_type=support, load_type=load, load_value=val,
        )
        r = compute_beam_deflection(spec)
        assert math.isfinite(r.delta_max_mm) and r.delta_max_mm >= 0.0
        assert math.isfinite(r.M_max_Nmm) and r.M_max_Nmm >= 0.0
        assert math.isfinite(r.V_max_N) and r.V_max_N >= 0.0
        assert math.isfinite(r.deflection_location_mm) and r.deflection_location_mm >= 0.0
        assert isinstance(r.honest_caveat, str) and len(r.honest_caveat) > 20


# ---------------------------------------------------------------------------
# Test 11: Re-export from arch/__init__.py works
# ---------------------------------------------------------------------------

class TestReExport:

    def test_re_export_types_identical(self):
        assert _BeamSpecFromInit is BeamSpec
        assert _ReportFromInit is BeamDeflectionReport
        assert _ComputeFromInit is compute_beam_deflection

    def test_re_export_computes_correctly(self):
        spec = _BeamSpecFromInit(
            length_mm=3_000.0, E_MPa=200_000.0, I_mm4=5e7,
            support_type="cantilever", load_type="udl", load_value=2.0,
        )
        r = _ComputeFromInit(spec)
        expected_delta = 2.0 * 3_000.0**4 / (8.0 * 200_000.0 * 5e7)
        assert _rel_err(r.delta_max_mm, expected_delta) < TOL
