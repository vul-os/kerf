"""
Tests for kerf_cad_core.arch.wind_load_asce7.

Covers ASCE 7-22 §26–27 Directional Procedure for MWFRS wall pressures.

Verification method:
  Reference values computed by hand / from ASCE 7-22 Commentary examples:

  Example A (Exposure C, V=115 mph, h=30 ft, L=B=60 ft):
    α=9.5, zg=900 ft
    z_eff = max(30, 15) = 30 ft
    Kz  = 2.01 · (30/900)^(2/9.5)
        = 2.01 · (0.03333)^(0.21053)
        = 2.01 · exp(0.21053 · ln(0.03333))
        = 2.01 · exp(0.21053 · (−3.4012))
        = 2.01 · exp(−0.71606)
        = 2.01 · 0.4888
        ≈ 0.9825   [ASCE 7-22 Table 26.10-1 gives ~0.98 at z=30ft Exp C]
    qz  = 0.00256 · 0.9825 · 1.0 · 0.85 · 115²
        = 0.00256 · 0.9825 · 0.85 · 13225
        = 0.00256 · 0.9825 · 11241.25
        ≈ 28.3 psf   [target: ~28–30 psf; acceptance: ≤ 5% of 29 psf]

  ASCE 7 published tables give qz ≈ 29 psf at h=30 ft, Exp C, V=115 mph
  (with Kd=0.85, G=0.85).  Precise value depends on exact Kz rounding;
  our formula is exact ASCE 7-22 Eq 26.10-1.

  total_drag = qz · G · (Cp_w + |Cp_l|) = qz · 0.85 · (0.8 + 0.5) = qz · 1.105

12+ tests in total.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.wind_load_asce7 import (
    WindSiteSpec,
    BuildingSpec,
    WindPressureReport,
    compute_wind_load,
    _compute_kz,
    _leeward_cp,
    _EXPOSURE_PARAMS,
    _KD_BUILDING,
    _G_RIGID,
)

# Re-export check from arch/__init__.py
from kerf_cad_core.arch import (
    WindSiteSpec as _WindSiteFromInit,
    WindBuildingSpec as _WindBuildingFromInit,
    WindPressureReport as _WindReportFromInit,
    compute_wind_load as _ComputeFromInit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_err(actual: float, expected: float) -> float:
    if expected == 0.0:
        return 0.0 if actual == 0.0 else float("inf")
    return abs(actual - expected) / abs(expected)


TOL = 0.05   # 5% tolerance for formula checks vs published ASCE 7 tables


# ---------------------------------------------------------------------------
# Test 1: Kz formula — Exposure C, z=30 ft
# ---------------------------------------------------------------------------

def test_kz_exposure_c_z30():
    """Kz at z=30 ft, Exposure C should be ≈ 0.98 per ASCE 7-22 Table 26.10-1."""
    alpha, zg = _EXPOSURE_PARAMS["C"]  # 9.5, 900
    kz = _compute_kz(30.0, alpha, zg)
    # ASCE 7-22 Table 26.10-1 gives 0.98 at z=30 ft, Exp C
    assert abs(kz - 0.98) < 0.02, f"Kz={kz:.4f} expected ≈0.98 at z=30ft Exp C"


# ---------------------------------------------------------------------------
# Test 2: Kz formula — Exposure C, z=15 ft (floor)
# ---------------------------------------------------------------------------

def test_kz_exposure_c_floor():
    """Kz at z<15 ft should equal Kz at z=15 ft (floor per §26.10 footnote)."""
    alpha, zg = _EXPOSURE_PARAMS["C"]
    kz_at5  = _compute_kz(5.0, alpha, zg)
    kz_at15 = _compute_kz(15.0, alpha, zg)
    assert kz_at5 == kz_at15, "Kz should be floored at z=15 ft"
    # Table 26.10-1: Kz≈0.85 at z=15 ft, Exp C
    assert abs(kz_at15 - 0.85) < 0.03, f"Kz={kz_at15:.4f} expected ≈0.85 at z=15ft Exp C"


# ---------------------------------------------------------------------------
# Test 3: Kz Exposure B < Exposure C < Exposure D at same height
# ---------------------------------------------------------------------------

def test_kz_exposure_ordering():
    """Exposure B (urban) → lower Kz → lower qz than C or D at same height."""
    z = 30.0
    alpha_b, zg_b = _EXPOSURE_PARAMS["B"]
    alpha_c, zg_c = _EXPOSURE_PARAMS["C"]
    alpha_d, zg_d = _EXPOSURE_PARAMS["D"]
    kz_b = _compute_kz(z, alpha_b, zg_b)
    kz_c = _compute_kz(z, alpha_c, zg_c)
    kz_d = _compute_kz(z, alpha_d, zg_d)
    assert kz_b < kz_c < kz_d, (
        f"Expected Kz_B < Kz_C < Kz_D at z=30ft; got {kz_b:.4f}, {kz_c:.4f}, {kz_d:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 4: qz formula — V=115 mph, Exposure C, h=30 ft (core reference)
# ---------------------------------------------------------------------------

def test_qz_v115_exp_c_h30():
    """
    V=115 mph, Exposure C, h=30 ft: qz should be ≈ 28–30 psf.
    ASCE 7-22 reference value ≈ 29 psf.
    """
    site = WindSiteSpec(V_basic_mph=115.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    report = compute_wind_load(site, bldg)
    # Accept ±5% of 29 psf
    assert _rel_err(report.qz_psf, 29.0) < 0.05, (
        f"qz={report.qz_psf:.2f} psf; expected ≈29 psf (±5%)"
    )
    assert report.Kz > 0.9, f"Kz={report.Kz:.4f} should be ≈ 0.98"


# ---------------------------------------------------------------------------
# Test 5: Exposure B → lower Kz → lower qz than Exposure C
# ---------------------------------------------------------------------------

def test_exposure_b_lower_than_c():
    """Exposure B (suburban) gives lower qz than Exposure C at same V and h."""
    site_b = WindSiteSpec(V_basic_mph=115.0, exposure_category="B")
    site_c = WindSiteSpec(V_basic_mph=115.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    rep_b = compute_wind_load(site_b, bldg)
    rep_c = compute_wind_load(site_c, bldg)
    assert rep_b.qz_psf < rep_c.qz_psf, (
        f"Exp B qz={rep_b.qz_psf:.2f} should be < Exp C qz={rep_c.qz_psf:.2f}"
    )
    assert rep_b.Kz < rep_c.Kz, "Kz_B should be < Kz_C"


# ---------------------------------------------------------------------------
# Test 6: Cp values for L/B = 1 (square building)
# ---------------------------------------------------------------------------

def test_cp_square_building():
    """For L/B = 1, Cp_windward = 0.8, Cp_leeward = −0.5 per Fig 27.4-1."""
    site = WindSiteSpec(V_basic_mph=115.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    report = compute_wind_load(site, bldg)
    assert report.Cp_windward == pytest.approx(0.8, abs=1e-6)
    assert report.Cp_leeward  == pytest.approx(-0.5, abs=1e-4)
    assert report.L_over_B == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Test 7: Total drag = qz · G · (Cp_w + |Cp_l|) = qz · G · 1.3 for L/B=1
# ---------------------------------------------------------------------------

def test_total_drag_L_B_equals_1():
    """
    For L/B=1 (Cp_l = −0.5): total_drag = qz · G · 1.3.
    task spec states drag = qz · 1.3, but with G=0.85: drag = qz · 0.85 · 1.3.
    """
    site = WindSiteSpec(V_basic_mph=115.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    report = compute_wind_load(site, bldg)
    expected_drag = report.qz_psf * _G_RIGID * (0.8 + 0.5)  # G · 1.3
    assert report.total_drag_psf == pytest.approx(expected_drag, rel=1e-4), (
        f"total_drag={report.total_drag_psf:.4f}, expected {expected_drag:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 8: Leeward Cp interpolation — L/B = 2 → Cp_l = −0.3
# ---------------------------------------------------------------------------

def test_leeward_cp_L_B_2():
    """At L/B = 2, leeward Cp = −0.3 per ASCE 7-22 Fig 27.4-1."""
    assert _leeward_cp(2.0) == pytest.approx(-0.3, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 9: Leeward Cp — L/B = 4+ → Cp_l = −0.2
# ---------------------------------------------------------------------------

def test_leeward_cp_L_B_4plus():
    """At L/B ≥ 4, leeward Cp = −0.2 per ASCE 7-22 Fig 27.4-1."""
    assert _leeward_cp(4.0) == pytest.approx(-0.2, abs=1e-6)
    assert _leeward_cp(6.0) == pytest.approx(-0.2, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 10: Leeward Cp — interpolation between L/B=1 and L/B=2
# ---------------------------------------------------------------------------

def test_leeward_cp_interpolation():
    """At L/B = 1.5, leeward Cp should interpolate between −0.5 and −0.3 → −0.4."""
    cp = _leeward_cp(1.5)
    assert cp == pytest.approx(-0.4, abs=1e-6), f"Cp_l at L/B=1.5 = {cp:.4f}, expected −0.4"


# ---------------------------------------------------------------------------
# Test 11: Higher V → higher qz (quadratic dependence)
# ---------------------------------------------------------------------------

def test_qz_scales_quadratically_with_V():
    """qz ∝ V²: doubling V should quadruple qz."""
    site_100 = WindSiteSpec(V_basic_mph=100.0, exposure_category="C")
    site_200 = WindSiteSpec(V_basic_mph=200.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    rep_100 = compute_wind_load(site_100, bldg)
    rep_200 = compute_wind_load(site_200, bldg)
    ratio = rep_200.qz_psf / rep_100.qz_psf
    assert abs(ratio - 4.0) < 0.001, f"qz ratio = {ratio:.4f}; expected 4.0 (quadratic in V)"


# ---------------------------------------------------------------------------
# Test 12: Topographic factor K_zt > 1.0 amplifies qz
# ---------------------------------------------------------------------------

def test_kzt_amplifies_qz():
    """K_zt = 1.3 (hilltop) should increase qz by exactly 30%."""
    site_flat  = WindSiteSpec(V_basic_mph=115.0, exposure_category="C", K_zt=1.0)
    site_hill  = WindSiteSpec(V_basic_mph=115.0, exposure_category="C", K_zt=1.3)
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    rep_flat = compute_wind_load(site_flat, bldg)
    rep_hill = compute_wind_load(site_hill, bldg)
    expected_ratio = 1.3
    actual_ratio   = rep_hill.qz_psf / rep_flat.qz_psf
    assert abs(actual_ratio - expected_ratio) < 1e-4, (
        f"K_zt=1.3 should give qz×1.3; ratio={actual_ratio:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 13: Risk Category IV documentation (V from correct map is user's job)
# ---------------------------------------------------------------------------

def test_risk_category_iv_documented():
    """Risk Category IV should be accepted and echoed in caveat."""
    site = WindSiteSpec(
        V_basic_mph=140.0,   # higher speed for RC IV (typical hurricane zone)
        exposure_category="D",
        risk_category="IV",
    )
    bldg = BuildingSpec(mean_height_h_ft=50.0, length_ft=100.0, width_ft=50.0)
    report = compute_wind_load(site, bldg)
    assert "IV" in report.honest_caveat
    assert report.qz_psf > 0


# ---------------------------------------------------------------------------
# Test 14: Exposure D → highest Kz → highest qz
# ---------------------------------------------------------------------------

def test_exposure_d_highest_qz():
    """Exposure D (coastal) gives highest qz for same V and h."""
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    reps = {}
    for exp in ("B", "C", "D"):
        site = WindSiteSpec(V_basic_mph=115.0, exposure_category=exp)
        reps[exp] = compute_wind_load(site, bldg)
    assert reps["B"].qz_psf < reps["C"].qz_psf < reps["D"].qz_psf


# ---------------------------------------------------------------------------
# Test 15: Invalid inputs raise ValueError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("V, exp, h, L, W", [
    (0.0,   "C", 30.0, 60.0, 60.0),   # V=0
    (-10.0, "C", 30.0, 60.0, 60.0),   # V<0
    (115.0, "A", 30.0, 60.0, 60.0),   # bad exposure
    (115.0, "C", 0.0,  60.0, 60.0),   # h=0
    (115.0, "C", 30.0, 0.0,  60.0),   # L=0
    (115.0, "C", 30.0, 60.0, 0.0),    # W=0
])
def test_invalid_inputs_raise(V, exp, h, L, W):
    """Invalid inputs must raise ValueError."""
    site = WindSiteSpec(V_basic_mph=V, exposure_category=exp)
    bldg = BuildingSpec(mean_height_h_ft=h, length_ft=L, width_ft=W)
    with pytest.raises(ValueError):
        compute_wind_load(site, bldg)


# ---------------------------------------------------------------------------
# Test 16: Re-export from arch/__init__.py works
# ---------------------------------------------------------------------------

def test_reexport_from_init():
    """arch/__init__.py must re-export WindSiteSpec, WindBuildingSpec, etc."""
    site = _WindSiteFromInit(V_basic_mph=115.0, exposure_category="C")
    bldg = _WindBuildingFromInit(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    report = _ComputeFromInit(site, bldg)
    assert isinstance(report, _WindReportFromInit)
    assert report.qz_psf > 0


# ---------------------------------------------------------------------------
# Test 17: Report fields sanity
# ---------------------------------------------------------------------------

def test_report_fields_sanity():
    """All numeric report fields must be finite and positive where expected."""
    site = WindSiteSpec(V_basic_mph=115.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    r = compute_wind_load(site, bldg)
    assert math.isfinite(r.qz_psf) and r.qz_psf > 0
    assert math.isfinite(r.Kz) and r.Kz > 0
    assert math.isfinite(r.p_windward_psf) and r.p_windward_psf > 0
    assert math.isfinite(r.p_leeward_psf)  and r.p_leeward_psf > 0
    assert math.isfinite(r.total_drag_psf) and r.total_drag_psf > 0
    assert r.Cp_windward > 0    # windward is positive pressure
    assert r.Cp_leeward  < 0    # leeward is suction
    assert len(r.code_section) >= 5
    assert len(r.honest_caveat) > 50


# ---------------------------------------------------------------------------
# Test 18: Very tall building (z=200 ft) has higher Kz than short building
# ---------------------------------------------------------------------------

def test_kz_increases_with_height():
    """Higher buildings have higher Kz (not capped for z < zg)."""
    alpha, zg = _EXPOSURE_PARAMS["C"]
    kz_30  = _compute_kz(30.0,  alpha, zg)
    kz_200 = _compute_kz(200.0, alpha, zg)
    assert kz_200 > kz_30, f"Kz at 200ft={kz_200:.4f} should exceed Kz at 30ft={kz_30:.4f}"


# ---------------------------------------------------------------------------
# Test 19: p_windward + p_leeward ≈ total_drag
# ---------------------------------------------------------------------------

def test_pressure_components_sum_to_drag():
    """total_drag should equal p_windward_psf + p_leeward_psf."""
    site = WindSiteSpec(V_basic_mph=115.0, exposure_category="C")
    bldg = BuildingSpec(mean_height_h_ft=30.0, length_ft=60.0, width_ft=60.0)
    r = compute_wind_load(site, bldg)
    assert r.total_drag_psf == pytest.approx(r.p_windward_psf + r.p_leeward_psf, rel=1e-4)
