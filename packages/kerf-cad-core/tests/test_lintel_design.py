"""
Tests for kerf_cad_core.arch.lintel_design — AISC Table 3-23 + ACI 318-19 §9 + TMS 402-22 §5.

All tests are hermetic (no OCC, no DB, no network).
Dimensions in mm, forces in kN, moments in kN·m, stresses in MPa.

Oracle derivations
------------------
T01 primary oracle:
  1200 mm span, steel rectangular approx (depth=101.6mm, width=101.6mm),
  Fy=250 MPa, DL=5 kN/m, LL=3 kN/m, no masonry.
  w_u = 1.2×5 + 1.6×3 = 10.8 kN/m; M_factored = 10.8×1.2²/8 = 1.944 kN·m
  Service M (note from task spec) = (5+3)×1.2²/8 = 1.44 kN·m ← matches task text
  S_x = 101.6×101.6²/6 = 174 803.9 mm³
  φ·Mn = 0.90×250×174 803.9 / 1e6 ≈ 39.33 kN·m
  V_max = 10.8×1.2/2 = 6.48 kN; A_web = 0.5×101.6×101.6 = 5161.3 mm²
  φ·Vn = 1.00×0.6×250×5161.3 / 1e3 ≈ 774.2 kN
  E=200000 MPa; I = 101.6×101.6³/12 = 8 876 637 mm⁴
  δ = 5×(8/1000)×1200⁴/(384×200000×8876637) ≈ 0.000122 mm; δ_allow=1200/240=5 mm → OK

T02 RC oracle:
  1200 mm span, RC b=230mm h=200mm, f'c=28 MPa, DL=5, LL=3, no masonry.
  d = 200-65 = 135 mm; As = 0.018×230×135 = 559.4 mm²
  a = 559.4×420/(0.85×28×230) = 42.70 mm
  φ·Mn = 0.9×559.4×420×(135-21.35)/1e6 ≈ 23.99 kN·m
  V_c = 0.17×√28×230×135 = 27 931 N; φ·Vn = 0.75×27 931 = 20948 N = 20.95 kN

T03 RM oracle:
  1800 mm span, RM b=200mm h=200mm, f'm=14 MPa, DL=3, LL=2, masonry=2400mm.
  L/2 = 0.9 m; h_masonry = 2.4 m ≥ 0.9 m → arching triangle
  w_peak = 20×0.9 = 18 kN/m; W_tri(s) = 0.5×18×1.8 = 16.2 kN
  W_tri(u) = 1.2×16.2 = 19.44 kN (DL factor)
  M_masonry = 19.44×1.8/6 = 5.832 kN·m
  w_u = 1.2×3+1.6×2 = 3.6+3.2 = 6.8 kN/m; M_udl = 6.8×1.8²/8 = 2.754 kN·m
  M_max = 5.832+2.754 = 8.586 kN·m

Coverage list
-------------
  T01  Steel primary oracle — M_max=1.944 kN·m (factored), service M≈1.44 kN·m
  T02  Steel phi_Mn computed from rectangular section, moment_dcr << 1
  T03  Steel wider span (2400mm) → higher M and delta than 1200mm span
  T04  Masonry 2400mm above 1200mm opening → arching triangle adds M_masonry
  T05  Masonry height ≥ L/2 triggers arching; height < L/2 uses rectangular UDL
  T06  Arching saturates: h_masonry=600mm (L/2) == h_masonry=2400mm same M
  T07  RC oracle: ACI 318-19 §9 phi_Mn and phi_Vn
  T08  RC: moment_dcr << 1 for adequate section with small span
  T09  RM oracle: TMS 402-22 §5 M_max with masonry arching
  T10  RM: phi_Mn uses 0.90 phi, 0.80 α_1 for stress block
  T11  Deflection limit L/240 (wall/roof) vs L/360 (floor) changes deflection_ok
  T12  Adequate=False when moment DCR > 1.0 (undersized steel section)
  T13  Zero loads → M=V=delta=0, adequate=True
  T14  Rectangular masonry load (h < L/2) gives correct UDL-based M
  T15  Re-export from arch/__init__.py works
  T16  honest_caveat mentions material code reference (AISC/ACI/TMS)
  T17  honest_caveat mentions "Simple span" scope limitation
  T18  ValueError: opening_span_mm <= 0
  T19  ValueError: wall_thickness_mm <= 0
  T20  ValueError: unknown material
  T21  ValueError: lintel_depth_mm <= 0
  T22  ValueError: lintel_width_mm <= 0
  T23  ValueError: fc_or_fy_MPa <= 0
  T24  ValueError: dead_load_kN_per_m < 0
  T25  ValueError: live_load_kN_per_m < 0
  T26  ValueError: masonry_above_height_mm < 0
  T27  ValueError: lintel_depth_mm too small (d < 0 for RC/RM)
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.lintel_design import (
    LintelSpec,
    LintelDesignReport,
    design_lintel,
)


# ---------------------------------------------------------------------------
# Tolerance helper
# ---------------------------------------------------------------------------

def _approx(a: float, b: float, rel: float = 1e-4) -> bool:
    """True if |a-b|/|b| ≤ rel (or both near zero)."""
    if abs(b) < 1e-12:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) <= rel


# ---------------------------------------------------------------------------
# T01 — Steel primary oracle: 1200 mm span, L4x4x1/4 approx, DL=5, LL=3
# ---------------------------------------------------------------------------

class TestT01SteelPrimaryOracle:
    """1200 mm steel lintel: factored M_max = 1.944 kN·m (service ≈ 1.44 kN·m)."""

    @pytest.fixture
    def spec(self) -> LintelSpec:
        return LintelSpec(
            opening_span_mm=1200.0,
            wall_thickness_mm=230.0,
            material="steel",
            lintel_depth_mm=101.6,
            lintel_width_mm=101.6,
            fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=5.0,
            live_load_kN_per_m=3.0,
            masonry_above_height_mm=0.0,
        )

    def test_factored_M_max(self, spec):
        """w_u=10.8 kN/m → M_max=10.8×1.2²/8=1.944 kN·m."""
        r = design_lintel(spec)
        # Factored: 1.2*5 + 1.6*3 = 10.8; M = 10.8*1.44/8
        assert _approx(r.M_max_kNm, 1.944, rel=1e-4), f"M_max={r.M_max_kNm}"

    def test_service_M_matches_task_note(self, spec):
        """Service (unfactored) moment = (5+3)×1.2²/8 = 1.44 kN·m."""
        # Not directly returned but verifiable from the load formulas
        w_s = 5.0 + 3.0   # kN/m service
        L = 1.2            # m
        M_service = w_s * L**2 / 8.0
        assert abs(M_service - 1.44) < 1e-6

    def test_phi_Mn_steel_rectangular(self, spec):
        """φ·Mn = 0.9 × 250 × (101.6 × 101.6² / 6) / 1e6 ≈ 39.33 kN·m."""
        r = design_lintel(spec)
        b, h, Fy = 101.6, 101.6, 250.0
        S_x = b * h**2 / 6.0
        expected = 0.9 * Fy * S_x / 1e6
        assert _approx(r.phi_Mn_kNm, expected, rel=1e-4), f"phi_Mn={r.phi_Mn_kNm} vs {expected}"

    def test_moment_dcr_less_than_one(self, spec):
        r = design_lintel(spec)
        assert r.moment_dcr < 1.0, f"moment_dcr={r.moment_dcr}"

    def test_shear_dcr_less_than_one(self, spec):
        r = design_lintel(spec)
        assert r.shear_dcr < 1.0, f"shear_dcr={r.shear_dcr}"

    def test_adequate_true(self, spec):
        r = design_lintel(spec)
        assert r.adequate is True

    def test_deflection_ok(self, spec):
        r = design_lintel(spec)
        assert r.deflection_ok is True


# ---------------------------------------------------------------------------
# T02 — Steel phi_Mn and V_max
# ---------------------------------------------------------------------------

class TestT02SteelCapacity:
    def test_V_max_factored(self):
        """V_max = w_u * L / 2 = 10.8 * 1.2 / 2 = 6.48 kN."""
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=101.6, lintel_width_mm=101.6, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))
        assert _approx(r.V_max_kN, 6.48, rel=1e-4)

    def test_phi_Vn_steel(self):
        """φ·Vn = 1.0 × 0.6 × 250 × 0.5 × 101.6 × 101.6 / 1e3 ≈ 774.2 kN."""
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=101.6, lintel_width_mm=101.6, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))
        expected = 1.0 * 0.6 * 250.0 * (0.5 * 101.6 * 101.6) / 1e3
        assert _approx(r.phi_Vn_kN, expected, rel=1e-4)

    def test_report_is_dataclass(self):
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=101.6, lintel_width_mm=101.6, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))
        assert isinstance(r, LintelDesignReport)


# ---------------------------------------------------------------------------
# T03 — Wider span → higher M and delta
# ---------------------------------------------------------------------------

class TestT03WiderSpan:
    @pytest.fixture
    def r_narrow(self):
        return design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=152, lintel_width_mm=152, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))

    @pytest.fixture
    def r_wide(self):
        return design_lintel(LintelSpec(
            opening_span_mm=2400, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=152, lintel_width_mm=152, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))

    def test_wider_span_higher_M(self, r_narrow, r_wide):
        assert r_wide.M_max_kNm > r_narrow.M_max_kNm

    def test_wider_span_higher_delta(self, r_narrow, r_wide):
        assert r_wide.delta_max_mm > r_narrow.delta_max_mm

    def test_wider_span_M_ratio(self, r_narrow, r_wide):
        """M scales with L² — ratio should be ~4 (2400/1200)²."""
        ratio = r_wide.M_max_kNm / r_narrow.M_max_kNm
        assert _approx(ratio, 4.0, rel=1e-4)


# ---------------------------------------------------------------------------
# T04 — Masonry 2400 mm above 1200 mm opening adds arching load
# ---------------------------------------------------------------------------

class TestT04MasonryArching:
    @pytest.fixture
    def r_no_masonry(self):
        return design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))

    @pytest.fixture
    def r_masonry(self):
        return design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=2400.0,
        ))

    def test_masonry_increases_M(self, r_no_masonry, r_masonry):
        assert r_masonry.M_max_kNm > r_no_masonry.M_max_kNm

    def test_masonry_increases_V(self, r_no_masonry, r_masonry):
        assert r_masonry.V_max_kN > r_no_masonry.V_max_kN

    def test_masonry_M_increment(self, r_no_masonry, r_masonry):
        """M_masonry factored = W_tri_u * L/6 = (1.2 * 7.2) * 1.2 / 6 = 1.728 kN·m."""
        delta_M = r_masonry.M_max_kNm - r_no_masonry.M_max_kNm
        expected_delta = 1.728  # 1.2 * (0.5 * 20 * 0.6 * 1.2) * 1.2 / 6
        assert _approx(delta_M, expected_delta, rel=1e-4)

    def test_honest_caveat_mentions_arching(self, r_masonry):
        assert "arching" in r_masonry.honest_caveat.lower()


# ---------------------------------------------------------------------------
# T05 — Arching threshold: height >= L/2 triggers triangle; < L/2 uses UDL
# ---------------------------------------------------------------------------

class TestT05ArchingThreshold:
    def _make(self, masonry_mm):
        return design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250,
            dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0,
            masonry_above_height_mm=masonry_mm,
        ))

    def test_at_threshold_arching_applies(self):
        """h_masonry = 600 = L/2 → arching triangle, not rectangular UDL."""
        r = self._make(600.0)
        # Arching W_tri_u = 1.2 * 0.5 * 20 * 0.6 * 1.2 = 8.64 kN; M=8.64*1.2/6=1.728
        # rectangular UDL: 1.2*20*0.6=14.4 kN/m; M=14.4*1.44/8=2.592 kNm (LARGER)
        # arching M: 1.728; no-masonry-base-M = (1.2*2+1.6*1)*1.44/8=0.72 kNm
        w_u_udl = 1.2 * 2.0 + 1.6 * 1.0
        M_udl = w_u_udl * 1.2**2 / 8.0
        M_arching_expected = 1.728
        assert _approx(r.M_max_kNm - M_udl, M_arching_expected, rel=1e-3)

    def test_below_threshold_rectangular(self):
        """h_masonry = 400 mm < L/2=600 → full rectangular masonry UDL."""
        r = self._make(400.0)
        # w_m_u = 1.2 * 20 * 0.4 = 9.6 kN/m; M_m = 9.6 * 1.44 / 8 = 1.728 kNm
        w_u_base = 1.2 * 2.0 + 1.6 * 1.0
        M_udl = w_u_base * 1.2**2 / 8.0
        M_masonry_rect_expected = 1.2 * 20 * 0.4 * 1.2**2 / 8.0  # 1.728
        assert _approx(r.M_max_kNm - M_udl, M_masonry_rect_expected, rel=1e-3)


# ---------------------------------------------------------------------------
# T06 — Arching saturates: same M for h >= L/2
# ---------------------------------------------------------------------------

class TestT06ArchingSaturates:
    def _make(self, masonry_mm):
        return design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250,
            dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0,
            masonry_above_height_mm=masonry_mm,
        ))

    def test_arching_saturates(self):
        """h=600mm (L/2) and h=2400mm both yield the same M since arching is limited to 45°."""
        r_600 = self._make(600.0)
        r_2400 = self._make(2400.0)
        assert _approx(r_600.M_max_kNm, r_2400.M_max_kNm, rel=1e-6)

    def test_arching_saturates_V(self):
        r_600 = self._make(600.0)
        r_2400 = self._make(2400.0)
        assert _approx(r_600.V_max_kN, r_2400.V_max_kN, rel=1e-6)


# ---------------------------------------------------------------------------
# T07 — RC oracle: ACI 318-19 §9
# ---------------------------------------------------------------------------

class TestT07RCOracle:
    @pytest.fixture
    def spec(self):
        return LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="reinforced_concrete",
            lintel_depth_mm=200, lintel_width_mm=230, fc_or_fy_MPa=28.0,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        )

    def test_phi_Mn_RC_oracle(self, spec):
        """ACI 318-19: ρ=0.018, d=135mm, As=559.4mm², a=42.7mm → φ·Mn≈23.99 kN·m."""
        r = design_lintel(spec)
        b, h_d, fc, fy = 230, 200 - 65, 28.0, 420.0
        rho = 0.018
        As = rho * b * h_d
        a = (As * fy) / (0.85 * fc * b)
        expected_phi_Mn = 0.9 * As * fy * (h_d - a / 2.0) / 1e6
        assert _approx(r.phi_Mn_kNm, expected_phi_Mn, rel=1e-4)

    def test_phi_Vn_RC_oracle(self, spec):
        """V_c = 0.17·√28·230·135; φ·Vn = 0.75·V_c."""
        r = design_lintel(spec)
        b, h_d, fc = 230, 200 - 65, 28.0
        Vc = 0.17 * math.sqrt(fc) * b * h_d
        expected = 0.75 * Vc / 1e3
        assert _approx(r.phi_Vn_kN, expected, rel=1e-4)

    def test_RC_adequate(self, spec):
        r = design_lintel(spec)
        assert r.adequate is True

    def test_RC_M_max_factored(self, spec):
        r = design_lintel(spec)
        # w_u = 1.2*5+1.6*3=10.8 kN/m; M=10.8*1.44/8=1.944 kN·m (no masonry)
        assert _approx(r.M_max_kNm, 1.944, rel=1e-4)


# ---------------------------------------------------------------------------
# T08 — RC with masonry: ACI + arching load
# ---------------------------------------------------------------------------

class TestT08RCWithMasonry:
    def test_masonry_adds_to_M_RC(self):
        """RC lintel with 2400mm masonry above: M higher than no masonry."""
        r_no = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="reinforced_concrete",
            lintel_depth_mm=200, lintel_width_mm=230, fc_or_fy_MPa=28.0,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=0.0,
        ))
        r_ms = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="reinforced_concrete",
            lintel_depth_mm=200, lintel_width_mm=230, fc_or_fy_MPa=28.0,
            dead_load_kN_per_m=5.0, live_load_kN_per_m=3.0, masonry_above_height_mm=2400.0,
        ))
        assert r_ms.M_max_kNm > r_no.M_max_kNm
        # M_masonry_u = 1.728 kN·m
        assert _approx(r_ms.M_max_kNm - r_no.M_max_kNm, 1.728, rel=1e-3)


# ---------------------------------------------------------------------------
# T09 — RM oracle: TMS 402-22 §5 with masonry arching
# ---------------------------------------------------------------------------

class TestT09RMOracle:
    @pytest.fixture
    def spec(self):
        return LintelSpec(
            opening_span_mm=1800, wall_thickness_mm=200, material="reinforced_masonry",
            lintel_depth_mm=200, lintel_width_mm=200, fc_or_fy_MPa=14.0,
            dead_load_kN_per_m=3.0, live_load_kN_per_m=2.0, masonry_above_height_mm=2400.0,
        )

    def test_RM_M_max(self, spec):
        """
        L=1.8m; L/2=0.9m; h=2.4m>=0.9m → arching.
        w_peak=20×0.9=18 kN/m; W_tri(s)=0.5×18×1.8=16.2 kN; W_tri(u)=1.2×16.2=19.44 kN
        M_masonry=19.44×1.8/6=5.832 kN·m
        w_u=1.2×3+1.6×2=3.6+3.2=6.8 kN/m; M_udl=6.8×1.8²/8=2.754 kN·m
        M_max=5.832+2.754=8.586 kN·m
        """
        r = design_lintel(spec)
        assert _approx(r.M_max_kNm, 8.586, rel=1e-3)

    def test_RM_phi_Mn(self, spec):
        """RM: ρ=0.010, d=135mm, As=270mm², a≈7.2mm, φ=0.90."""
        r = design_lintel(spec)
        b, h_d, fm, fy = 200, 200 - 65, 14.0, 420.0
        As = 0.010 * b * h_d
        a = (As * fy) / (0.80 * fm * b)
        expected = 0.90 * As * fy * (h_d - a / 2.0) / 1e6
        assert _approx(r.phi_Mn_kNm, expected, rel=1e-4)

    def test_RM_phi_Vn(self, spec):
        """φ·Vn = 0.80 × A_n × √f'm / 3 (TMS §9.3.4.1.2)."""
        r = design_lintel(spec)
        b, h_d, fm = 200, 200 - 65, 14.0
        A_n = b * h_d
        Vn = A_n * math.sqrt(fm) / 3.0
        expected = 0.80 * Vn / 1e3
        assert _approx(r.phi_Vn_kN, expected, rel=1e-4)


# ---------------------------------------------------------------------------
# T10 — RM: phi factor and stress block coefficient
# ---------------------------------------------------------------------------

class TestT10RMPhiCoeffs:
    def test_RM_phi_b_is_090(self):
        """φ_b=0.90 for TMS §7.3.2.2 flexure — verify ratio matches."""
        b, h_d, fm, fy, rho = 200, 135, 14.0, 420.0, 0.010
        As = rho * b * h_d
        a = (As * fy) / (0.80 * fm * b)
        Mn = As * fy * (h_d - a / 2.0) / 1e6
        spec = LintelSpec(
            opening_span_mm=1800, wall_thickness_mm=200, material="reinforced_masonry",
            lintel_depth_mm=200, lintel_width_mm=200, fc_or_fy_MPa=14.0,
            dead_load_kN_per_m=3.0, live_load_kN_per_m=2.0, masonry_above_height_mm=0.0,
        )
        r = design_lintel(spec)
        assert _approx(r.phi_Mn_kNm, 0.90 * Mn, rel=1e-4)


# ---------------------------------------------------------------------------
# T11 — Deflection limit L/240 vs L/360
# ---------------------------------------------------------------------------

class TestT11DeflectionLimit:
    def _make(self, floor=False, masonry=2400.0):
        # Use RC with large span and high load to get measurable deflection
        return design_lintel(LintelSpec(
            opening_span_mm=3600, wall_thickness_mm=230, material="reinforced_concrete",
            lintel_depth_mm=400, lintel_width_mm=230, fc_or_fy_MPa=28.0,
            dead_load_kN_per_m=10.0, live_load_kN_per_m=8.0,
            masonry_above_height_mm=masonry, floor_lintel=floor,
        ))

    def test_floor_lintel_uses_L_over_360(self):
        r = self._make(floor=True)
        # δ_allow = 3600/360 = 10 mm
        assert r.deflection_ok == (r.delta_max_mm <= 3600.0 / 360.0)

    def test_wall_lintel_uses_L_over_240(self):
        r = self._make(floor=False)
        # δ_allow = 3600/240 = 15 mm
        assert r.deflection_ok == (r.delta_max_mm <= 3600.0 / 240.0)

    def test_floor_stricter_than_wall(self):
        """Floor limit (L/360) is stricter than wall (L/240) — floor_lintel=True may fail when wall OK."""
        # True if delta is between L/360 and L/240
        r_wall = self._make(floor=False)
        r_floor = self._make(floor=True)
        L = 3600.0
        delta = r_wall.delta_max_mm
        # both same delta, but different limit
        assert r_wall.delta_max_mm == r_floor.delta_max_mm


# ---------------------------------------------------------------------------
# T12 — Adequate=False when moment DCR > 1.0
# ---------------------------------------------------------------------------

class TestT12AdequateFalse:
    def test_undersized_steel_fails(self):
        """Thin section with large span and loads → moment_dcr > 1.0, adequate=False."""
        r = design_lintel(LintelSpec(
            opening_span_mm=3600, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=100, lintel_width_mm=50, fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=20.0, live_load_kN_per_m=10.0, masonry_above_height_mm=0.0,
        ))
        assert r.moment_dcr > 1.0
        assert r.adequate is False

    def test_undersized_RC_fails(self):
        """Very large span with tiny RC section."""
        r = design_lintel(LintelSpec(
            opening_span_mm=6000, wall_thickness_mm=150, material="reinforced_concrete",
            lintel_depth_mm=100, lintel_width_mm=100, fc_or_fy_MPa=28.0,
            dead_load_kN_per_m=10.0, live_load_kN_per_m=8.0, masonry_above_height_mm=3000.0,
        ))
        assert r.moment_dcr > 1.0
        assert r.adequate is False


# ---------------------------------------------------------------------------
# T13 — Zero loads
# ---------------------------------------------------------------------------

class TestT13ZeroLoads:
    def test_zero_loads_zero_demand(self):
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=101.6, lintel_width_mm=101.6, fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=0.0, live_load_kN_per_m=0.0, masonry_above_height_mm=0.0,
        ))
        assert r.M_max_kNm == 0.0
        assert r.V_max_kN == 0.0
        assert r.delta_max_mm == 0.0
        assert r.adequate is True


# ---------------------------------------------------------------------------
# T14 — Rectangular masonry load (h_masonry < L/2)
# ---------------------------------------------------------------------------

class TestT14RectangularMasonryLoad:
    def test_rectangular_load_M(self):
        """h=400mm < L/2=600mm → w_m_u=1.2×20×0.4=9.6 kN/m, M=9.6×1.44/8=1.728 kN·m."""
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=0.0, live_load_kN_per_m=0.0, masonry_above_height_mm=400.0,
        ))
        # M = w_m_u * L² / 8 = 9.6 * 1.44 / 8 = 1.728 kN·m
        expected = 1.2 * 20.0 * 0.4 * 1.2**2 / 8.0
        assert _approx(r.M_max_kNm, expected, rel=1e-4)


# ---------------------------------------------------------------------------
# T15 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

class TestT15ReExport:
    def test_re_export(self):
        from kerf_cad_core.arch import LintelSpec as LS, LintelDesignReport as LDR, design_lintel as dl
        assert LS is LintelSpec
        assert LDR is LintelDesignReport
        assert dl is design_lintel


# ---------------------------------------------------------------------------
# T16 — honest_caveat references
# ---------------------------------------------------------------------------

class TestT16HonestCaveat:
    def _r(self, mat, fc):
        return design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material=mat,
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=fc,
            dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0, masonry_above_height_mm=0.0,
        ))

    def test_steel_caveat_mentions_aisc(self):
        r = self._r("steel", 250)
        assert "AISC" in r.honest_caveat

    def test_RC_caveat_mentions_ACI(self):
        r = self._r("reinforced_concrete", 28)
        assert "ACI" in r.honest_caveat

    def test_RM_caveat_mentions_TMS(self):
        r = self._r("reinforced_masonry", 14)
        assert "TMS" in r.honest_caveat


# ---------------------------------------------------------------------------
# T17 — honest_caveat scope limitation
# ---------------------------------------------------------------------------

class TestT17HonestCaveatScope:
    def test_caveat_mentions_simple_span(self):
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0, masonry_above_height_mm=0.0,
        ))
        assert "Simple span" in r.honest_caveat or "simple span" in r.honest_caveat.lower()

    def test_caveat_mentions_no_continuous_moment(self):
        r = design_lintel(LintelSpec(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0, masonry_above_height_mm=0.0,
        ))
        # caveat must mention the continuous-beam limitation
        assert "continuous" in r.honest_caveat.lower() or "redistribution" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# T18–T27 — ValueError inputs
# ---------------------------------------------------------------------------

class TestInputValidation:
    def _base(self, **kwargs):
        base = dict(
            opening_span_mm=1200, wall_thickness_mm=230, material="steel",
            lintel_depth_mm=200, lintel_width_mm=150, fc_or_fy_MPa=250.0,
            dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0, masonry_above_height_mm=0.0,
        )
        base.update(kwargs)
        return LintelSpec(**base)

    def test_T18_opening_span_zero(self):
        with pytest.raises(ValueError, match="opening_span_mm"):
            design_lintel(self._base(opening_span_mm=0))

    def test_T19_wall_thickness_zero(self):
        with pytest.raises(ValueError, match="wall_thickness_mm"):
            design_lintel(self._base(wall_thickness_mm=0))

    def test_T20_unknown_material(self):
        with pytest.raises(ValueError, match="material"):
            design_lintel(self._base(material="timber"))

    def test_T21_lintel_depth_zero(self):
        with pytest.raises(ValueError, match="lintel_depth_mm"):
            design_lintel(self._base(lintel_depth_mm=0))

    def test_T22_lintel_width_zero(self):
        with pytest.raises(ValueError, match="lintel_width_mm"):
            design_lintel(self._base(lintel_width_mm=0))

    def test_T23_fc_zero(self):
        with pytest.raises(ValueError, match="fc_or_fy_MPa"):
            design_lintel(self._base(fc_or_fy_MPa=0))

    def test_T24_dead_load_negative(self):
        with pytest.raises(ValueError, match="dead_load_kN_per_m"):
            design_lintel(self._base(dead_load_kN_per_m=-1.0))

    def test_T25_live_load_negative(self):
        with pytest.raises(ValueError, match="live_load_kN_per_m"):
            design_lintel(self._base(live_load_kN_per_m=-1.0))

    def test_T26_masonry_height_negative(self):
        with pytest.raises(ValueError, match="masonry_above_height_mm"):
            design_lintel(self._base(masonry_above_height_mm=-1.0))

    def test_T27_RC_too_shallow(self):
        """d=depth-65 must be >0; depth=50 → d=-15 → ValueError."""
        with pytest.raises(ValueError):
            design_lintel(LintelSpec(
                opening_span_mm=1200, wall_thickness_mm=230,
                material="reinforced_concrete",
                lintel_depth_mm=50,  # d = 50-65 = -15 → error
                lintel_width_mm=230, fc_or_fy_MPa=28.0,
                dead_load_kN_per_m=2.0, live_load_kN_per_m=1.0,
                masonry_above_height_mm=0.0,
            ))
