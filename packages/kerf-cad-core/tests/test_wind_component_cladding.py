"""
Tests for kerf_cad_core.arch.wind_component_cladding — ASCE 7-22 §30.3 C&C.

Test philosophy:
  • Oracle calculations: hand-derived using ASCE 7-22 Fig 30.3-2A/C anchors
    and the log-linear interpolation formula.
  • All numeric assertions use absolute tolerances (abs=) since results are
    engineering quantities in psf.

Reference quick-calc:
  V=115 mph, Exposure C, h=30 ft, Kzt=1.0, Kd=0.85
  α=9.5, zg=900 ft
  Kh = 2.01 × (30/900)^(2/9.5) = 2.01 × (0.03333)^(0.21053)
     = 2.01 × 0.4988... ≈ 0.8643 (≈0.8643 per tables)  [z≥15 ft ok]
  qh = 0.00256 × 0.8643 × 1.0 × 0.85 × 115² = 0.00256 × 0.8643 × 0.85 × 13225
     ≈ 0.00256 × 0.8643 × 11241.25 ≈ 24.86 psf

  Zone_4_wall_edge, A=24 ft² (4×6 window):
    t = log10(24/10)/log10(500/10) = log10(2.4)/log10(50) = 0.3802/1.6990 ≈ 0.2238
    GCp_pos = 1.0 + (0.8 - 1.0)*0.2238 = 1.0 - 0.0448 = +0.9552 ≈ +0.955
    GCp_neg = -1.1 + (-0.8 - (-1.1))*0.2238 = -1.1 + 0.3*0.2238 = -1.1 + 0.0671 = -1.0329 ≈ -1.033

  p_positive = qh * (GCp_pos + 0.18) = 24.86 * (0.9552 + 0.18) = 24.86 * 1.1352 ≈ 28.22 psf
  p_negative = qh * (GCp_neg - 0.18) = 24.86 * (-1.0329 - 0.18) = 24.86 * (-1.2129) ≈ -30.17 psf
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.wind_load_asce7 import WindSiteSpec, BuildingSpec
from kerf_cad_core.arch.wind_component_cladding import (
    ComponentSpec,
    WindCCPressureReport,
    compute_wind_cc_pressure,
    _interpolate_gcp,
    _GCP_ANCHORS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _site(V=115.0, exp="C", Kzt=1.0, rc="II"):
    return WindSiteSpec(V_basic_mph=V, exposure_category=exp, K_zt=Kzt, risk_category=rc)


def _bldg(h=30.0, L=50.0, W=40.0, enc="enclosed"):
    return BuildingSpec(mean_height_h_ft=h, length_ft=L, width_ft=W, enclosure=enc)


def _comp(area=24.0, zone="Zone_4_wall_edge", ctype="wall"):
    return ComponentSpec(area_ft2=area, zone=zone, component_type=ctype)


# ---------------------------------------------------------------------------
# 1. Reference oracle: 4'×6' window in Zone 4, V=115 mph, Exp C, h=30 ft
# ---------------------------------------------------------------------------

class TestZone4WindowOracle:
    """Window 4'×6' = 24 ft²; Zone_4_wall_edge; V=115 mph; h=30 ft."""

    def setup_method(self):
        self.r = compute_wind_cc_pressure(_site(), _bldg(), _comp())

    def test_qh_magnitude(self):
        # qh should be about 25–31 psf for V=115, Exp C, h=30 ft
        assert 22.0 < self.r.qz_psf < 33.0

    def test_GCp_pos_approx(self):
        # GCp_pos ≈ +0.955 (log interpolation at 24 ft² in [10,500])
        assert abs(self.r.GCp_positive - 0.955) < 0.01

    def test_GCp_neg_approx(self):
        # GCp_neg ≈ -1.033
        assert abs(self.r.GCp_negative - (-1.033)) < 0.01

    def test_GCp_pos_in_range(self):
        # must be between 0.8 (at 500 ft²) and 1.0 (at 10 ft²)
        assert 0.8 <= self.r.GCp_positive <= 1.0

    def test_GCp_neg_in_range(self):
        # must be between -1.1 (at 10 ft²) and -0.8 (at 500 ft²)  — magnitude decreasing
        assert -1.1 <= self.r.GCp_negative <= -0.8

    def test_p_design_positive_uses_GCpi(self):
        # p_pos = qh*(GCp_pos + 0.18) — should be larger than qh*GCp_pos alone
        assert self.r.p_design_positive_psf > self.r.qz_psf * self.r.GCp_positive

    def test_p_design_negative_uses_GCpi(self):
        # p_neg = qh*(GCp_neg - 0.18) — magnitude is larger than qh*|GCp_neg| alone
        assert self.r.p_design_negative_psf < self.r.qz_psf * self.r.GCp_negative

    def test_p_design_positive_psf_range(self):
        # hand: ≈ 28 psf ± 4
        assert 22.0 < self.r.p_design_positive_psf < 36.0

    def test_p_design_negative_psf_range(self):
        # hand: ≈ -30 psf ± 5
        assert -40.0 < self.r.p_design_negative_psf < -22.0

    def test_LRFD_label(self):
        assert self.r.ASD_or_LRFD == "LRFD"

    def test_code_section_contains_30_3(self):
        combined = " ".join(self.r.code_section)
        assert "30.3" in combined

    def test_GCpi_embedded_in_caveat(self):
        assert "GCpi" in self.r.honest_caveat or "±0.18" in self.r.honest_caveat


# ---------------------------------------------------------------------------
# 2. Effective-area reduction: larger area → smaller |GCp|
# ---------------------------------------------------------------------------

class TestEffectiveAreaReduction:

    def test_larger_area_smaller_GCp_pos(self):
        r_small = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=10.0))
        r_large = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=300.0))
        assert r_small.GCp_positive > r_large.GCp_positive

    def test_larger_area_smaller_GCp_neg_magnitude(self):
        r_small = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=10.0))
        r_large = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=300.0))
        assert abs(r_small.GCp_negative) > abs(r_large.GCp_negative)

    def test_area_at_10_ft2_gives_anchor_value(self):
        r = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=10.0))
        # Zone_4_wall_edge anchor at 10 ft²: GCp_pos=1.0, GCp_neg=-1.1
        assert abs(r.GCp_positive - 1.0) < 1e-9
        assert abs(r.GCp_negative - (-1.1)) < 1e-9

    def test_area_at_500_ft2_gives_anchor_value_wall(self):
        r = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=500.0))
        # Zone_4_wall_edge anchor at 500 ft²: GCp_pos=0.8, GCp_neg=-0.8
        assert abs(r.GCp_positive - 0.8) < 1e-9
        assert abs(r.GCp_negative - (-0.8)) < 1e-9

    def test_area_beyond_max_clamps_to_anchor(self):
        r = compute_wind_cc_pressure(_site(), _bldg(), _comp(area=1000.0))
        # Same as 500 ft²
        assert abs(r.GCp_positive - 0.8) < 1e-9
        assert abs(r.GCp_negative - (-0.8)) < 1e-9


# ---------------------------------------------------------------------------
# 3. Zone ordering: higher zones have higher |GCp_neg|
# ---------------------------------------------------------------------------

class TestZoneOrdering:

    def _run(self, zone, ctype):
        return compute_wind_cc_pressure(
            _site(), _bldg(), ComponentSpec(area_ft2=10.0, zone=zone, component_type=ctype)
        )

    def test_wall_corner_higher_neg_than_edge(self):
        r_edge = self._run("Zone_4_wall_edge", "wall")
        r_corner = self._run("Zone_5_corner_wall", "wall")
        assert abs(r_corner.GCp_negative) > abs(r_edge.GCp_negative)

    def test_wall_edge_higher_neg_than_interior(self):
        r_int = self._run("Zone_1_interior_wall", "wall")
        r_edge = self._run("Zone_4_wall_edge", "wall")
        # Zone 1 and Zone 4 share the same negative anchor (-1.1) per Fig 30.3-2A;
        # they differ only in positive.
        assert abs(r_edge.GCp_negative) >= abs(r_int.GCp_negative)

    def test_roof_corner_highest_neg(self):
        r1 = self._run("Zone_1_roof_interior", "roof")
        r2 = self._run("Zone_2_roof_edge", "roof")
        r3 = self._run("Zone_3_roof_corner", "roof")
        assert abs(r3.GCp_negative) > abs(r2.GCp_negative) > abs(r1.GCp_negative)

    def test_roof_corner_GCp_neg_at_10ft2(self):
        r = self._run("Zone_3_roof_corner", "roof")
        # Zone_3_roof_corner GCp_neg at 10 ft² = -2.8
        assert abs(r.GCp_negative - (-2.8)) < 1e-9

    def test_roof_corner_produces_highest_design_suction(self):
        r_wall = compute_wind_cc_pressure(
            _site(), _bldg(), ComponentSpec(area_ft2=10.0, zone="Zone_5_corner_wall", component_type="wall")
        )
        r_roof = compute_wind_cc_pressure(
            _site(), _bldg(), ComponentSpec(area_ft2=10.0, zone="Zone_3_roof_corner", component_type="roof")
        )
        # Roof corner (-2.8 GCp) should produce more suction than wall corner (-1.4 GCp)
        assert r_roof.p_design_negative_psf < r_wall.p_design_negative_psf


# ---------------------------------------------------------------------------
# 4. GCpi: verify internal pressure effect is ±0.18 of qh
# ---------------------------------------------------------------------------

class TestGCpiEffect:

    def test_p_pos_equals_qh_times_GCp_plus_018(self):
        r = compute_wind_cc_pressure(_site(), _bldg(), _comp())
        expected = r.qz_psf * (r.GCp_positive + 0.18)
        # Tolerance accounts for rounding of stored qz_psf and GCp to 4 dp
        assert abs(r.p_design_positive_psf - expected) < 0.01

    def test_p_neg_equals_qh_times_GCp_minus_018(self):
        r = compute_wind_cc_pressure(_site(), _bldg(), _comp())
        expected = r.qz_psf * (r.GCp_negative - 0.18)
        # Tolerance accounts for rounding of stored qz_psf and GCp to 4 dp
        assert abs(r.p_design_negative_psf - expected) < 0.01


# ---------------------------------------------------------------------------
# 5. Wind speed sensitivity: higher V → higher pressures (monotone)
# ---------------------------------------------------------------------------

class TestWindSpeedMonotone:

    def test_higher_V_higher_p_pos(self):
        r_low = compute_wind_cc_pressure(_site(V=90.0), _bldg(), _comp())
        r_hi = compute_wind_cc_pressure(_site(V=150.0), _bldg(), _comp())
        assert r_hi.p_design_positive_psf > r_low.p_design_positive_psf

    def test_higher_V_higher_suction_magnitude(self):
        r_low = compute_wind_cc_pressure(_site(V=90.0), _bldg(), _comp())
        r_hi = compute_wind_cc_pressure(_site(V=150.0), _bldg(), _comp())
        assert abs(r_hi.p_design_negative_psf) > abs(r_low.p_design_negative_psf)


# ---------------------------------------------------------------------------
# 6. Exposure category sensitivity: D (coastal) > C > B for same V
# ---------------------------------------------------------------------------

class TestExposureSensitivity:

    def test_exposure_D_higher_qh_than_B(self):
        rB = compute_wind_cc_pressure(_site(exp="B"), _bldg(), _comp())
        rC = compute_wind_cc_pressure(_site(exp="C"), _bldg(), _comp())
        rD = compute_wind_cc_pressure(_site(exp="D"), _bldg(), _comp())
        assert rD.qz_psf > rC.qz_psf > rB.qz_psf


# ---------------------------------------------------------------------------
# 7. Roof zones with area reduction
# ---------------------------------------------------------------------------

class TestRoofZoneAreaReduction:

    def test_roof_zone2_area_at_10ft2_anchor(self):
        r = compute_wind_cc_pressure(
            _site(), _bldg(),
            ComponentSpec(area_ft2=10.0, zone="Zone_2_roof_edge", component_type="roof")
        )
        assert abs(r.GCp_negative - (-1.8)) < 1e-9

    def test_roof_zone2_area_at_100ft2_anchor(self):
        r = compute_wind_cc_pressure(
            _site(), _bldg(),
            ComponentSpec(area_ft2=100.0, zone="Zone_2_roof_edge", component_type="roof")
        )
        assert abs(r.GCp_negative - (-1.1)) < 1e-9

    def test_roof_area_beyond_100ft2_clamps(self):
        r = compute_wind_cc_pressure(
            _site(), _bldg(),
            ComponentSpec(area_ft2=500.0, zone="Zone_2_roof_edge", component_type="roof")
        )
        # Beyond 100 ft², clamps to -1.1
        assert abs(r.GCp_negative - (-1.1)) < 1e-9


# ---------------------------------------------------------------------------
# 8. Validation / error cases
# ---------------------------------------------------------------------------

class TestValidationErrors:

    def test_negative_V_raises(self):
        with pytest.raises(ValueError, match="V_basic_mph"):
            compute_wind_cc_pressure(_site(V=-1.0), _bldg(), _comp())

    def test_invalid_exposure_raises(self):
        with pytest.raises(ValueError, match="exposure_category"):
            compute_wind_cc_pressure(_site(exp="E"), _bldg(), _comp())

    def test_negative_area_raises(self):
        with pytest.raises(ValueError, match="area_ft2"):
            compute_wind_cc_pressure(_site(), _bldg(), _comp(area=-1.0))

    def test_invalid_zone_raises(self):
        with pytest.raises(ValueError, match="zone"):
            compute_wind_cc_pressure(_site(), _bldg(), _comp(zone="Zone_99_bogus"))

    def test_invalid_component_type_raises(self):
        with pytest.raises(ValueError, match="component_type"):
            compute_wind_cc_pressure(
                _site(), _bldg(),
                ComponentSpec(area_ft2=24.0, zone="Zone_4_wall_edge", component_type="parapet")
            )

    def test_roof_type_with_wall_zone_raises(self):
        with pytest.raises(ValueError):
            compute_wind_cc_pressure(
                _site(), _bldg(),
                ComponentSpec(area_ft2=24.0, zone="Zone_4_wall_edge", component_type="roof")
            )

    def test_wall_type_with_roof_zone_raises(self):
        with pytest.raises(ValueError):
            compute_wind_cc_pressure(
                _site(), _bldg(),
                ComponentSpec(area_ft2=24.0, zone="Zone_2_roof_edge", component_type="wall")
            )

    def test_Kzt_less_than_1_raises(self):
        with pytest.raises(ValueError, match="K_zt"):
            compute_wind_cc_pressure(_site(Kzt=0.5), _bldg(), _comp())

    def test_zero_height_raises(self):
        with pytest.raises(ValueError, match="mean_height_h_ft"):
            compute_wind_cc_pressure(_site(), _bldg(h=0.0), _comp())


# ---------------------------------------------------------------------------
# 9. High-rise warning embedded in caveat
# ---------------------------------------------------------------------------

class TestHighRiseWarning:

    def test_h_above_60ft_embeds_warning(self):
        r = compute_wind_cc_pressure(_site(), _bldg(h=70.0), _comp())
        assert "60 ft" in r.honest_caveat or "§30.3" in r.honest_caveat

    def test_h_at_60ft_no_warning(self):
        r = compute_wind_cc_pressure(_site(), _bldg(h=60.0), _comp())
        assert "WARNING" not in r.honest_caveat


# ---------------------------------------------------------------------------
# 10. Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

class TestArchInitExports:

    def test_imports_via_arch(self):
        from kerf_cad_core.arch import (
            CCComponentSpec, WindCCPressureReport, compute_wind_cc_pressure as fn
        )
        r = fn(
            WindSiteSpec(V_basic_mph=100.0, exposure_category="C"),
            BuildingSpec(mean_height_h_ft=20.0, length_ft=40.0, width_ft=30.0),
            CCComponentSpec(area_ft2=20.0, zone="Zone_1_interior_wall", component_type="wall"),
        )
        assert isinstance(r, WindCCPressureReport)
        assert r.qz_psf > 0


# ---------------------------------------------------------------------------
# 11. All six zones callable without error
# ---------------------------------------------------------------------------

class TestAllZonesCallable:

    @pytest.mark.parametrize("zone,ctype", [
        ("Zone_1_interior_wall", "wall"),
        ("Zone_4_wall_edge", "wall"),
        ("Zone_5_corner_wall", "wall"),
        ("Zone_1_roof_interior", "roof"),
        ("Zone_2_roof_edge", "roof"),
        ("Zone_3_roof_corner", "roof"),
    ])
    def test_zone_runs(self, zone, ctype):
        r = compute_wind_cc_pressure(
            _site(), _bldg(),
            ComponentSpec(area_ft2=30.0, zone=zone, component_type=ctype)
        )
        assert r.qz_psf > 0
        assert r.p_design_positive_psf > 0
        assert r.p_design_negative_psf < 0
        assert "30.3" in " ".join(r.code_section)


# ---------------------------------------------------------------------------
# 12. _interpolate_gcp unit tests
# ---------------------------------------------------------------------------

class TestInterpolateGcp:

    def test_at_min_area_returns_anchor_10(self):
        assert _interpolate_gcp(1.0, 0.8, 10.0, 500.0) == 1.0

    def test_at_max_area_returns_anchor_max(self):
        assert _interpolate_gcp(1.0, 0.8, 500.0, 500.0) == 0.8

    def test_below_min_area_clamps_to_anchor_10(self):
        assert _interpolate_gcp(1.0, 0.8, 5.0, 500.0) == 1.0

    def test_above_max_area_clamps_to_anchor_max(self):
        assert _interpolate_gcp(1.0, 0.8, 1000.0, 500.0) == 0.8

    def test_midpoint_area_log_interpolated(self):
        # log10(mid) = (log10(10) + log10(500)) / 2 = (1 + 2.699) / 2 = 1.8495
        # mid = 10^1.8495 ≈ 70.7
        mid_area = math.sqrt(10.0 * 500.0)  # geometric mean ≈ 70.71
        result = _interpolate_gcp(1.0, 0.8, mid_area, 500.0)
        assert abs(result - 0.9) < 0.001  # exactly halfway in log space → 0.9
