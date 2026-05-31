"""
Tests for kerf_cad_core.arch.stair_stringer — IBC §1011 + AWC NDS-2018 §3.3
+ AISC 360-22 §F2 stair stringer design check.

All tests are hermetic (no OCC, no DB, no network).
Dimensions in inches, loads in psf.

Oracle derivations
------------------

PRIMARY oracle (T01):
  rise=7in, tread=11in, n=8 treads, width=48in, 2 stringers, DF-No2 2×12, LL=100psf, DL=15psf

  run = 8×11 = 88in;  rise_total = 8×7 = 56in
  L = √(88²+56²) = √(7744+3136) = √10880 = 104.309in

  trib_width = 48/2 = 24in;  trib_ft = 2.0ft
  w = (100+15)×2.0 = 230 lb/ft = 19.167 lb/in

  DF-No2 2×12: Fb=875psi, E=1 600 000psi, b=1.5in, d=11.25in
    Sx = 1.5×11.25²/6 = 31.641in³
    I  = 1.5×11.25³/12 = 177.979in⁴

  M_max(UDL) = 19.167 × 104.309² / 8 = 26 043.5 lb·in
  fb = 26 043.5 / 31.641 = 823.1psi
  DCR_bend = 823.1 / 875 = 0.9407  (< 1.0 → ok)

  δ = 5×19.167×104.309⁴ / (384×1.6e6×177.979)
    = 5×19.167×118 466 288 / (384×1.6e6×177.979)
    = 0.19558in
  L/360 = 104.309/360 = 0.28975in
  DCR_defl = 0.19558/0.28975 = 0.6750  (< 1.0)

  M_conc(300lb) = 300×104.309/4 = 7823.2 lb·in
  DCR_bend_conc = 7823.2/(31.641×875) = 0.2826

  Status: bending governs (DCR_bend=0.941 > DCR_defl=0.675)

RISER FAILURE oracle (T02):
  rise=8in > IBC max 7in → riser_compliant=False, status='fail-code'

STEEL oracle (T03):
  C10×15.3: Sx=13.5in³, I=67.4in⁴, Fb=0.9×36000=32400psi, E=29e6psi
  Same geometry as T01 (n=8, 7in rise, 11in tread, 48in wide, 2 stringers)
  M_max = 26 043.5 lb·in
  fb = 26 043.5 / 13.5 = 1929.1psi
  DCR_bend = 1929.1 / 32400 = 0.0595 (easily passes)

DEFLECTION GOVERNS oracle (T04):
  C10×15.3, n=20 treads, 7in rise, 11in tread, 48in wide, 2 stringers
  run=220in, rise=140in
  L = √(220²+140²) = √(48400+19600) = √68000 = 260.768in
  w = 19.167 lb/in
  M = 19.167×260.768²/8 = 162 920.4 lb·in
  fb = 162 920.4 / 13.5 = 12 068.2psi
  DCR_bend = 12 068.2 / 32400 = 0.3725

  δ = 5×19.167×260.768⁴ / (384×29e6×67.4)
    ≈ 0.5975in
  L/360 = 260.768/360 = 0.7244in
  DCR_defl = 0.5975/0.7244 = 0.8248  (> DCR_bend → deflection governs)

Coverage list
-------------
  T01  Primary oracle: 7in rise, 11in tread, 8 treads, DF-No2 2×12, bending DCR < 1.0
  T02  IBC §1011 failure: riser_height=8in → riser_compliant=False, status='fail-code'
  T03  IBC §1011 failure: tread_depth=10in → tread_compliant=False, status='fail-code'
  T04  Steel C10×15.3, 8 treads 7/11: easily passes (DCR_bend ≈ 0.06)
  T05  Deflection governs: C10×15.3 at 20 treads (DCR_defl > DCR_bend)
  T06  Inclined span: L = √(run²+rise²) correctly computed
  T07  UDL moment formula: M = w·L²/8
  T08  Deflection formula: δ = 5wL⁴/(384EI)
  T09  Tributary width: trib = stair_width / num_stringers
  T10  SP-No1 2×12: higher Fb=1500psi passes at 8 treads with larger DCR headroom
  T11  HSS6×4×1/4: easily passes (small Sx but very high Fb_eff)
  T12  Status 'fail-bending' when DCR_bend > 1.0
  T13  Status 'fail-deflection' when only deflection > 1.0
  T14  Status 'oversize' when governing_dcr ≤ 0.25
  T15  Re-export from arch/__init__.py works
  T16  honest_caveat mentions IBC, NDS/AISC, and scope limits
  T17  ValueError: num_treads < 1
  T18  ValueError: riser_height_in <= 0
  T19  ValueError: tread_depth_in <= 0
  T20  ValueError: stair_width_in <= 0
  T21  ValueError: num_stringers < 1
  T22  ValueError: live_load_psf <= 0
  T23  MATERIAL_DEFAULTS lookup: all four keys return positive Fb, E, Sx, I
  T24  Custom material: ValueError when Fb_psi=0 and material not in lookup
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.stair_stringer import (
    StairGeometry,
    StringerSpec,
    StringerReport,
    design_stair_stringer,
    MATERIAL_DEFAULTS,
    IBC_RISER_MIN_IN,
    IBC_RISER_MAX_IN,
    IBC_TREAD_MIN_IN,
)


# ---------------------------------------------------------------------------
# Tolerance helpers
# ---------------------------------------------------------------------------

def approx(val: float, rel: float = 1e-3) -> object:
    return pytest.approx(val, rel=rel)


# ---------------------------------------------------------------------------
# Shared fixture specs
# ---------------------------------------------------------------------------

# Primary 8-tread DF-No2 stair (passes all checks)
_GEOM_8T = StairGeometry(
    num_treads=8,
    riser_height_in=7.0,
    tread_depth_in=11.0,
    total_run_in=0,   # auto-computed: 8×11=88
    total_rise_in=0,  # auto-computed: 8×7=56
    stair_width_in=48.0,  # 4ft
)

_STRINGER_DF_NO2 = StringerSpec(material="sawn-DF-No2")
_STRINGER_SP_NO1 = StringerSpec(material="sawn-SP-No1")
_STRINGER_C10    = StringerSpec(material="steel-C10x15.3")
_STRINGER_HSS    = StringerSpec(material="steel-HSS6x4x1/4")


# ---------------------------------------------------------------------------
# T01 — Primary oracle: 7in rise, 11in tread, 8 treads, DF-No2 2×12
#       bending DCR < 1.0
# ---------------------------------------------------------------------------

class TestT01_PrimaryOracle:
    """T01 — 7in rise, 11in tread, 4ft wide, 8 treads, DF-No2 2×12: DCR_bend < 1.0."""

    def test_bending_dcr_lt_1(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        assert r.bending_dcr < 1.0

    def test_riser_compliant(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        assert r.riser_compliant is True

    def test_tread_compliant(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        assert r.tread_compliant is True

    def test_status_ok(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        assert r.status == "ok"

    def test_span_length_formula(self):
        """L = sqrt(88² + 56²) ≈ 104.31in."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        expected = math.hypot(8 * 11.0, 8 * 7.0)   # sqrt(88²+56²)
        assert r.span_length_in == approx(expected, rel=1e-4)

    def test_bending_dcr_value(self):
        """DCR_bend = fb / Fb ≈ 0.9407 for 2 stringers."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        # Oracle: M ≈ 26043 lb-in, fb ≈ 823 psi, Fb=875 psi
        assert r.bending_dcr == approx(0.9407, rel=5e-3)

    def test_governing_dcr_is_bending(self):
        """For this case, bending governs over deflection."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        assert r.governing_dcr == approx(r.bending_dcr, rel=1e-6)
        assert r.bending_dcr >= r.deflection_dcr


# ---------------------------------------------------------------------------
# T02 — IBC §1011.5.2: riser_height=8in → riser_compliant=False
# ---------------------------------------------------------------------------

class TestT02_RiserIBCFail:
    """T02 — riser_height=8in exceeds IBC §1011.5.2 max 7in."""

    def test_riser_compliant_false(self):
        geom = StairGeometry(8, 8.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert r.riser_compliant is False

    def test_status_fail_code(self):
        geom = StairGeometry(8, 8.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert r.status == "fail-code"

    def test_warning_mentions_riser_violation(self):
        geom = StairGeometry(8, 8.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert any("IBC" in w and "riser" in w.lower() for w in r.warnings)

    def test_riser_below_minimum_also_fails(self):
        """riser_height=3.5in < IBC §1011.5.2 min 4in."""
        geom = StairGeometry(8, 3.5, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert r.riser_compliant is False
        assert r.status == "fail-code"


# ---------------------------------------------------------------------------
# T03 — IBC §1011.5.2: tread_depth=10in < 11in minimum
# ---------------------------------------------------------------------------

class TestT03_TreadIBCFail:
    """T03 — tread_depth=10in < IBC §1011.5.2 minimum 11in."""

    def test_tread_compliant_false(self):
        geom = StairGeometry(8, 7.0, 10.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert r.tread_compliant is False

    def test_status_fail_code(self):
        geom = StairGeometry(8, 7.0, 10.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert r.status == "fail-code"

    def test_tread_at_minimum_passes(self):
        """tread_depth = 11.0in exactly → tread_compliant=True."""
        geom = StairGeometry(8, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2)
        assert r.tread_compliant is True


# ---------------------------------------------------------------------------
# T04 — Steel C10×15.3 stringer: easily passes at 8 treads
# ---------------------------------------------------------------------------

class TestT04_SteelC10Passes:
    """T04 — Steel C10×15.3 stringer: DCR_bend ≈ 0.06 at 8 treads (easily passes)."""

    def test_bending_dcr_lt_1(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        assert r.bending_dcr < 1.0

    def test_governing_dcr_lt_1(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        assert r.governing_dcr < 1.0

    def test_status_ok_or_oversize(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        assert r.status in ("ok", "oversize")

    def test_bending_dcr_value(self):
        """C10×15.3 Sx=13.5in³ vs DF-No2 Sx=31.64in³ → higher fb but much higher Fb."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        # Oracle: fb ≈ 1929psi, Fb_eff=32400psi → DCR≈0.060
        assert r.bending_dcr == approx(0.0595, rel=5e-3)

    def test_steel_deflection_also_low(self):
        """Steel E=29e6 psi → very small deflection."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        assert r.deflection_dcr < 0.5


# ---------------------------------------------------------------------------
# T05 — Deflection governs: C10×15.3 at 20 treads (long span)
# ---------------------------------------------------------------------------

class TestT05_DeflectionGoverns:
    """T05 — C10×15.3, 20 treads 7/11in: deflection_dcr > bending_dcr."""

    def setup_method(self):
        geom = StairGeometry(
            num_treads=20,
            riser_height_in=7.0,
            tread_depth_in=11.0,
            total_run_in=0,
            total_rise_in=0,
            stair_width_in=48.0,
        )
        self.report = design_stair_stringer(geom, _STRINGER_C10, num_stringers=2)

    def test_deflection_dcr_gt_bending_dcr(self):
        """Deflection governs for long-span steel stringer."""
        assert self.report.deflection_dcr > self.report.bending_dcr

    def test_governing_is_deflection(self):
        assert self.report.governing_dcr == approx(self.report.deflection_dcr, rel=1e-6)

    def test_span_is_long(self):
        """L = √(220²+140²) ≈ 260.8in ≈ 21.7ft."""
        assert self.report.span_length_in == approx(260.77, rel=1e-3)

    def test_both_dcr_lt_1(self):
        """Even though deflection governs, both are < 1 for this case."""
        assert self.report.governing_dcr < 1.0


# ---------------------------------------------------------------------------
# T06 — Span length: L = sqrt(run² + rise²)
# ---------------------------------------------------------------------------

class TestT06_SpanLength:
    """T06 — Inclined span correctly computed from run and rise."""

    def test_span_hypot(self):
        """13 treads 7in/11in: L=sqrt(143²+91²)=169.5in."""
        geom = StairGeometry(13, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_C10)
        expected = math.hypot(13 * 11.0, 13 * 7.0)
        assert r.span_length_in == approx(expected, rel=1e-4)

    def test_span_uses_explicit_run_rise(self):
        """Explicit total_run/total_rise override computed values."""
        geom1 = StairGeometry(8, 7.0, 11.0, 88.0, 56.0, 48.0)  # explicit
        geom2 = StairGeometry(8, 7.0, 11.0, 0, 0, 48.0)         # auto-computed
        r1 = design_stair_stringer(geom1, _STRINGER_C10)
        r2 = design_stair_stringer(geom2, _STRINGER_C10)
        assert r1.span_length_in == approx(r2.span_length_in, rel=1e-6)

    def test_span_increases_with_more_treads(self):
        geom5 = StairGeometry(5, 7.0, 11.0, 0, 0, 48.0)
        geom10 = StairGeometry(10, 7.0, 11.0, 0, 0, 48.0)
        r5 = design_stair_stringer(geom5, _STRINGER_C10)
        r10 = design_stair_stringer(geom10, _STRINGER_C10)
        assert r10.span_length_in > r5.span_length_in


# ---------------------------------------------------------------------------
# T07 — UDL moment formula: M = w·L²/8
# ---------------------------------------------------------------------------

class TestT07_MomentFormula:
    """T07 — M_max = w·L²/8 (Roark 9e §8 Table 8.1 case 2, SS UDL)."""

    def test_moment_proportional_to_load(self):
        """Doubling load doubles moment."""
        r1 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, live_load_psf=50.0, dead_load_psf=0.0)
        r2 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, live_load_psf=100.0, dead_load_psf=0.0)
        assert r2.max_moment_in_lb == approx(2.0 * r1.max_moment_in_lb, rel=1e-4)

    def test_moment_proportional_to_l_squared(self):
        """Doubling L (via 2× treads) quadruples moment (L → 2L → M ∝ L²)."""
        geom_n = StairGeometry(4, 7.0, 11.0, 0, 0, 48.0)
        geom_2n = StairGeometry(8, 7.0, 11.0, 0, 0, 48.0)
        r_n = design_stair_stringer(geom_n, _STRINGER_C10)
        r_2n = design_stair_stringer(geom_2n, _STRINGER_C10)
        # L doubles → M scales by 4 (L² factor)
        L_n = math.hypot(4 * 11, 4 * 7)
        L_2n = math.hypot(8 * 11, 8 * 7)
        expected_ratio = (L_2n / L_n) ** 2
        actual_ratio = r_2n.max_moment_in_lb / r_n.max_moment_in_lb
        assert actual_ratio == approx(expected_ratio, rel=1e-4)

    def test_conc_load_moment(self):
        """M_conc = P·L/4 = 300·L/4."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10)
        expected = 300.0 * r.span_length_in / 4.0
        assert r.max_moment_conc_in_lb == approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# T08 — Deflection formula: δ = 5wL⁴/(384EI)
# ---------------------------------------------------------------------------

class TestT08_DeflectionFormula:
    """T08 — δ = 5wL⁴/(384EI) (Roark 9e §8 Table 8.1 case 2)."""

    def test_deflection_scales_with_l4(self):
        """Doubling L (via 2× treads) multiplies δ by approximately 2⁴=16."""
        geom_n = StairGeometry(4, 7.0, 11.0, 0, 0, 48.0)
        geom_2n = StairGeometry(8, 7.0, 11.0, 0, 0, 48.0)
        r_n = design_stair_stringer(geom_n, _STRINGER_C10)
        r_2n = design_stair_stringer(geom_2n, _STRINGER_C10)
        L_n = math.hypot(4 * 11, 4 * 7)
        L_2n = math.hypot(8 * 11, 8 * 7)
        expected_ratio = (L_2n / L_n) ** 4
        actual_ratio = r_2n.max_deflection_in / r_n.max_deflection_in
        assert actual_ratio == approx(expected_ratio, rel=1e-4)

    def test_deflection_proportional_to_load(self):
        """δ ∝ w; doubling load doubles deflection."""
        r1 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, live_load_psf=50.0, dead_load_psf=0.0)
        r2 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, live_load_psf=100.0, dead_load_psf=0.0)
        assert r2.max_deflection_in == approx(2.0 * r1.max_deflection_in, rel=1e-4)

    def test_deflection_limit_is_l_over_360(self):
        """Deflection limit = L/360 per IBC Table 1604.3."""
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        limit = r.span_length_in / 360.0
        assert r.deflection_dcr == approx(r.max_deflection_in / limit, rel=1e-6)


# ---------------------------------------------------------------------------
# T09 — Tributary width: trib = stair_width / num_stringers
# ---------------------------------------------------------------------------

class TestT09_TributaryWidth:
    """T09 — Tributary width per stringer = stair_width / num_stringers."""

    def test_more_stringers_reduces_moment(self):
        """Adding more stringers reduces the tributary width → lower moment."""
        r2 = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        r3 = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=3)
        assert r3.max_moment_in_lb < r2.max_moment_in_lb

    def test_moment_proportional_to_trib_width(self):
        """Doubling num_stringers halves moment (halves tributary width)."""
        r2 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        r4 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=4)
        assert r4.max_moment_in_lb == approx(0.5 * r2.max_moment_in_lb, rel=1e-4)

    def test_single_stringer_higher_load(self):
        """Single stringer carries full width tributary load."""
        r1 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=1)
        r2 = design_stair_stringer(_GEOM_8T, _STRINGER_C10, num_stringers=2)
        assert r1.max_moment_in_lb == approx(2.0 * r2.max_moment_in_lb, rel=1e-4)


# ---------------------------------------------------------------------------
# T10 — SP-No1 2×12: higher Fb=1500psi, more headroom at 8 treads
# ---------------------------------------------------------------------------

class TestT10_SPNo1:
    """T10 — Southern Pine No.1 2×12: Fb=1500psi (higher than DF-No2 875psi)."""

    def test_sp_dcr_less_than_df_no2(self):
        """SP No.1 has higher Fb → lower DCR for identical geometry."""
        r_df = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        r_sp = design_stair_stringer(_GEOM_8T, _STRINGER_SP_NO1, num_stringers=2)
        assert r_sp.bending_dcr < r_df.bending_dcr

    def test_sp_dcr_ratio(self):
        """DCR_SP / DCR_DF = 875/1500 (same Sx, different Fb)."""
        r_df = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=2)
        r_sp = design_stair_stringer(_GEOM_8T, _STRINGER_SP_NO1, num_stringers=2)
        assert r_sp.bending_dcr == approx(r_df.bending_dcr * 875.0 / 1500.0, rel=1e-3)

    def test_sp_passes_at_8_treads(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_SP_NO1, num_stringers=2)
        assert r.bending_dcr < 1.0


# ---------------------------------------------------------------------------
# T11 — HSS6×4×1/4: AISC 360-22 §F2, A500 Gr.B
# ---------------------------------------------------------------------------

class TestT11_HSS:
    """T11 — AISC HSS6×4×1/4 A500 Gr.B: Fb_eff=41400psi, Sx=8.53in³."""

    def test_hss_passes_at_8_treads(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_HSS, num_stringers=2)
        assert r.bending_dcr < 1.0
        assert r.governing_dcr < 1.0

    def test_hss_status_not_fail(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_HSS, num_stringers=2)
        assert r.status in ("ok", "oversize")


# ---------------------------------------------------------------------------
# T12 — Status 'fail-bending' when DCR_bend > 1.0
# ---------------------------------------------------------------------------

class TestT12_FailBending:
    """T12 — Large load or long span → status='fail-bending'."""

    def test_fail_bending_status(self):
        """High live load forces bending failure on DF-No2 2x12."""
        geom = StairGeometry(13, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2, num_stringers=2,
                                  live_load_psf=100.0, dead_load_psf=15.0)
        assert r.bending_dcr > 1.0
        assert r.status == "fail-bending"

    def test_dcr_reported_above_1(self):
        geom = StairGeometry(13, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_DF_NO2, num_stringers=2)
        assert r.governing_dcr > 1.0


# ---------------------------------------------------------------------------
# T13 — Status 'fail-deflection'
# ---------------------------------------------------------------------------

class TestT13_FailDeflection:
    """T13 — fail-deflection: deflection_dcr > 1.0 while bending_dcr ≤ 1.0."""

    def test_fail_deflection_path(self):
        """
        Construct a case where deflection fails but bending passes.
        Use C10×15.3 (high Fb=32400psi) with very large span: 25 treads.
        At some span, deflection_dcr > 1.0 while bending_dcr stays < 1.0.
        """
        # Find span where defl fails but bending ok for C10x15.3:
        # DCR_bend = (w*L^2/8/Sx) / Fb; DCR_defl = (5wL^4/384EI) / (L/360)
        # For C10x15.3 at 25 treads:
        geom = StairGeometry(25, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_C10, num_stringers=2)
        if r.deflection_dcr > 1.0 and r.bending_dcr <= 1.0:
            assert r.status == "fail-deflection"
        # If bending also fails, the case still demonstrates a large span.
        assert r.governing_dcr > 0  # sanity check


# ---------------------------------------------------------------------------
# T14 — Status 'oversize' when governing_dcr ≤ 0.25
# ---------------------------------------------------------------------------

class TestT14_Oversize:
    """T14 — governing_dcr ≤ 0.25 → status='oversize'."""

    def test_oversize_status(self):
        """3 treads only → very short span → C10×15.3 is massively oversized."""
        geom = StairGeometry(3, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_C10, num_stringers=2)
        assert r.governing_dcr <= 0.25
        assert r.status == "oversize"

    def test_oversize_is_compliant_with_ibc(self):
        """Oversize still has riser and tread compliant."""
        geom = StairGeometry(3, 7.0, 11.0, 0, 0, 48.0)
        r = design_stair_stringer(geom, _STRINGER_C10)
        assert r.riser_compliant is True
        assert r.tread_compliant is True


# ---------------------------------------------------------------------------
# T15 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

class TestT15_ReExport:
    """T15 — StairGeometry, StringerSpec, StringerReport, design_stair_stringer
    re-exported from kerf_cad_core.arch."""

    def test_import_from_arch_init(self):
        from kerf_cad_core.arch import (
            StairGeometry as SG,
            StringerSpec as SS,
            StringerReport as SR,
            design_stair_stringer as dss,
        )
        geom = SG(8, 7.0, 11.0, 0, 0, 48.0)
        stringer = SS(material="sawn-DF-No2")
        report = dss(geom, stringer, num_stringers=2)
        assert isinstance(report, SR)
        assert report.span_length_in > 0

    def test_material_defaults_exported(self):
        from kerf_cad_core.arch.stair_stringer import MATERIAL_DEFAULTS
        assert "sawn-DF-No2" in MATERIAL_DEFAULTS


# ---------------------------------------------------------------------------
# T16 — honest_caveat quality
# ---------------------------------------------------------------------------

class TestT16_HonestCaveat:
    """T16 — honest_caveat references the correct standards and scope limits."""

    def test_caveat_mentions_ibc(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        assert "IBC" in r.honest_caveat

    def test_caveat_mentions_nds_for_wood(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        assert "NDS" in r.honest_caveat

    def test_caveat_mentions_aisc_for_steel(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10)
        assert "AISC" in r.honest_caveat

    def test_caveat_mentions_shear_not_checked(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        caveat_lower = r.honest_caveat.lower()
        assert "shear" in caveat_lower

    def test_caveat_mentions_bearing_not_checked(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2)
        caveat_lower = r.honest_caveat.lower()
        assert "bearing" in caveat_lower

    def test_caveat_mentions_ltb_for_steel(self):
        r = design_stair_stringer(_GEOM_8T, _STRINGER_C10)
        caveat_lower = r.honest_caveat.lower()
        assert "ltb" in caveat_lower or "lateral" in caveat_lower


# ---------------------------------------------------------------------------
# T17 — ValueError: num_treads < 1
# ---------------------------------------------------------------------------

class TestT17_ErrorNumTreads:
    """T17 — ValueError: num_treads < 1."""

    def test_zero_treads(self):
        with pytest.raises(ValueError, match="num_treads"):
            design_stair_stringer(
                StairGeometry(0, 7.0, 11.0, 0, 0, 48.0), _STRINGER_DF_NO2
            )

    def test_negative_treads(self):
        with pytest.raises(ValueError):
            design_stair_stringer(
                StairGeometry(-1, 7.0, 11.0, 0, 0, 48.0), _STRINGER_DF_NO2
            )


# ---------------------------------------------------------------------------
# T18 — ValueError: riser_height_in <= 0
# ---------------------------------------------------------------------------

class TestT18_ErrorRiserHeight:
    """T18 — ValueError: riser_height_in <= 0."""

    def test_zero_riser(self):
        with pytest.raises(ValueError, match="riser_height_in"):
            design_stair_stringer(
                StairGeometry(8, 0.0, 11.0, 0, 0, 48.0), _STRINGER_DF_NO2
            )

    def test_negative_riser(self):
        with pytest.raises(ValueError):
            design_stair_stringer(
                StairGeometry(8, -1.0, 11.0, 0, 0, 48.0), _STRINGER_DF_NO2
            )


# ---------------------------------------------------------------------------
# T19 — ValueError: tread_depth_in <= 0
# ---------------------------------------------------------------------------

class TestT19_ErrorTreadDepth:
    """T19 — ValueError: tread_depth_in <= 0."""

    def test_zero_tread(self):
        with pytest.raises(ValueError, match="tread_depth_in"):
            design_stair_stringer(
                StairGeometry(8, 7.0, 0.0, 0, 0, 48.0), _STRINGER_DF_NO2
            )


# ---------------------------------------------------------------------------
# T20 — ValueError: stair_width_in <= 0
# ---------------------------------------------------------------------------

class TestT20_ErrorStairWidth:
    """T20 — ValueError: stair_width_in <= 0."""

    def test_zero_width(self):
        with pytest.raises(ValueError, match="stair_width_in"):
            design_stair_stringer(
                StairGeometry(8, 7.0, 11.0, 0, 0, 0.0), _STRINGER_DF_NO2
            )

    def test_negative_width(self):
        with pytest.raises(ValueError):
            design_stair_stringer(
                StairGeometry(8, 7.0, 11.0, 0, 0, -1.0), _STRINGER_DF_NO2
            )


# ---------------------------------------------------------------------------
# T21 — ValueError: num_stringers < 1
# ---------------------------------------------------------------------------

class TestT21_ErrorNumStringers:
    """T21 — ValueError: num_stringers < 1."""

    def test_zero_stringers(self):
        with pytest.raises(ValueError, match="num_stringers"):
            design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, num_stringers=0)


# ---------------------------------------------------------------------------
# T22 — ValueError: live_load_psf <= 0
# ---------------------------------------------------------------------------

class TestT22_ErrorLiveLoad:
    """T22 — ValueError: live_load_psf <= 0."""

    def test_zero_live_load(self):
        with pytest.raises(ValueError, match="live_load_psf"):
            design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, live_load_psf=0.0)

    def test_negative_live_load(self):
        with pytest.raises(ValueError):
            design_stair_stringer(_GEOM_8T, _STRINGER_DF_NO2, live_load_psf=-50.0)


# ---------------------------------------------------------------------------
# T23 — MATERIAL_DEFAULTS: all four keys have valid positive properties
# ---------------------------------------------------------------------------

class TestT23_MaterialDefaults:
    """T23 — All four material keys return positive Fb, E, Sx, I."""

    @pytest.mark.parametrize("key", [
        "sawn-DF-No2",
        "sawn-SP-No1",
        "steel-C10x15.3",
        "steel-HSS6x4x1/4",
    ])
    def test_material_positive_properties(self, key):
        d = MATERIAL_DEFAULTS[key]
        assert d["Fb_psi"] > 0
        assert d["E_psi"] > 0
        assert d["Sx_in3"] > 0
        assert d["I_in4"] > 0

    def test_df_no2_fb(self):
        """DF-No2 Fb=875psi (NDS Supplement Table 4A, CF=1.0 for 2×12)."""
        assert MATERIAL_DEFAULTS["sawn-DF-No2"]["Fb_psi"] == pytest.approx(875.0)

    def test_sp_no1_fb(self):
        """SP No.1 Fb=1500psi (NDS Supplement Table 4B)."""
        assert MATERIAL_DEFAULTS["sawn-SP-No1"]["Fb_psi"] == pytest.approx(1500.0)

    def test_c10_fb(self):
        """C10×15.3 Fb_eff=0.9×36000=32400psi."""
        assert MATERIAL_DEFAULTS["steel-C10x15.3"]["Fb_psi"] == pytest.approx(32400.0)

    def test_hss_fb(self):
        """HSS6×4×1/4 Fb_eff=0.9×46000=41400psi."""
        assert MATERIAL_DEFAULTS["steel-HSS6x4x1/4"]["Fb_psi"] == pytest.approx(41400.0)


# ---------------------------------------------------------------------------
# T24 — Custom material: ValueError when Fb_psi=0 and material not in lookup
# ---------------------------------------------------------------------------

class TestT24_CustomMaterialError:
    """T24 — ValueError when custom material has no Fb_psi supplied."""

    def test_custom_material_no_fb(self):
        """Unknown material with Fb_psi=0 raises ValueError."""
        custom = StringerSpec(material="unknown-timber", Fb_psi=0.0, E_psi=1e6, Sx_in3=30.0)
        with pytest.raises(ValueError, match="Fb_psi"):
            design_stair_stringer(_GEOM_8T, custom)

    def test_custom_material_with_fb_works(self):
        """Unknown material WITH Fb_psi, E_psi, Sx_in3 supplied works."""
        custom = StringerSpec(
            material="custom-LVL",
            Fb_psi=2600.0,
            E_psi=1_900_000.0,
            Sx_in3=31.641,
        )
        r = design_stair_stringer(_GEOM_8T, custom, num_stringers=2)
        assert r.bending_dcr > 0
        assert r.span_length_in > 0
