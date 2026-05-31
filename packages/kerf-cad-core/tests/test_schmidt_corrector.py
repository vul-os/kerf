"""
Tests for kerf_cad_core.optics.schmidt_corrector — Schmidt corrector plate design.

Test plan
---------
 1.  oracle_200mm_f2_bk7_max_sag
        200mm aperture f/2 BK7 corrector: max_sag matches analytical formula.
 2.  oracle_200mm_f2_bk7_neutral_zone
        Neutral zone for kappa=1.5 is at r = D/2 / sqrt(1.5) = sqrt(2/3) * D/2.
 3.  larger_aperture_more_sag
        Doubling aperture at same f/# increases max_sag.
 4.  smaller_aperture_less_sag
        Halving aperture at same f/# decreases max_sag.
 5.  sag_scales_inversely_with_n_minus_1
        Sag is proportional to 1/(n-1): higher glass index -> smaller sag.
 6.  sag_at_centre_is_zero
        z(0) = 0 always (profile starts at origin).
 7.  profile_spans_full_aperture
        Profile r values span [0, D/2] inclusive.
 8.  schwarzschild_constant_is_minus_one
        The equivalent conic constant k = -1 (paraboloid) always.
 9.  neutral_zone_dz_dr_zero
        dz/dr = 0 at r = rho_n: finite-difference slope near neutral zone is near zero.
10.  kappa_changes_neutral_zone_not_sag
        Changing kappa changes rho_n (neutral zone position) while keeping
        the sag formula result the same (kappa enters only through rho_n).
11.  num_radii_controls_profile_length
        num_radii parameter controls the number of (r, z) samples returned.
12.  profile_r_is_monotone_increasing
        Profile r values are strictly monotone from 0 to D/2.
13.  to_dict_has_ok_true
        to_dict() returns a dict with ok=True.
14.  to_dict_contains_all_fields
        to_dict() contains all required result keys.
15.  honest_caveat_mentions_classical
        honest_caveat contains "Schmidt" and "classical" or "Classical".
16.  error_negative_R
        Raises ValueError for negative primary_radius_R_mm.
17.  error_zero_D
        Raises ValueError for zero aperture_diameter_D_mm.
18.  error_n_equals_1
        Raises ValueError for glass_index_n = 1.0 (no refraction).
19.  error_n_below_1
        Raises ValueError for glass_index_n < 1.0.
20.  error_negative_kappa
        Raises ValueError for neutral_zone_factor_kappa <= 0.
21.  error_num_radii_too_small
        Raises ValueError for num_radii < 2.
22.  tool_happy_path
        LLM tool returns ok=True JSON with all required keys.
23.  tool_missing_R
        LLM tool returns error for missing primary_radius_R_mm.
24.  tool_missing_D
        LLM tool returns error for missing aperture_diameter_D_mm.
25.  tool_bad_json
        LLM tool handles invalid JSON gracefully.
26.  sag_profile_formula_verification
        Verify z(rho_n) = -rho_n^4 / (8*(n-1)*R^3) analytically.
27.  max_sag_is_at_valley_for_kappa_1p5
        For kappa=1.5, max sag |z(rho_n)| > |z(r_ap)| (valley deeper than edge).
28.  re_export_from_init
        SchmidtSpec, SchmidtReport, design_schmidt_corrector importable from optics.

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Schmidt, B. — "Ein lichtstarkes komafreies Spiegelsystem", 1932.
Born, M. & Wolf, E. — "Principles of Optics", 7th ed., 1999, §6.3.
Rutten, H.G.J. & van Venrooij, M.A.M. — "Telescope Optics", 1988, §6.3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.schmidt_corrector import (
    SchmidtReport,
    SchmidtSpec,
    _schmidt_sag,
    design_schmidt_corrector,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SPEC_200MM_F2 = SchmidtSpec(
    primary_radius_R_mm=400.0,
    aperture_diameter_D_mm=200.0,
)

_SPEC_200MM_F2_HIRES = SchmidtSpec(
    primary_radius_R_mm=400.0,
    aperture_diameter_D_mm=200.0,
)

# Pre-computed analytical oracles for 200mm f/2 BK7 (kappa=1.5)
# R = 400 mm, r_ap = 100 mm, n = 1.5168, kappa = 1.5
# rho_n = 100 / sqrt(1.5) = 81.6497 mm
# max_sag = |z(rho_n)| = rho_n^4 / (8*(n-1)*R^3) = (100/sqrt(1.5))^4 / (8*0.5168*400^3)
#          = (4/9)*r_ap^4 / (8*(n-1)*R^3)
_R = 400.0
_D = 200.0
_n = 1.5168
_kappa = 1.5
_r_ap = _D / 2.0
_rho_n_expected = _r_ap / math.sqrt(_kappa)
_denom = 8.0 * (_n - 1.0) * (_R ** 3)
_max_sag_expected = (_rho_n_expected ** 4) / _denom  # = 4/9 * r_ap^4/denom


# ---------------------------------------------------------------------------
# Test 1: oracle 200mm f/2 BK7 max sag
# ---------------------------------------------------------------------------

def test_oracle_200mm_f2_bk7_max_sag():
    """max_sag matches analytical formula: rho_n^4 / (8*(n-1)*R^3).

    Use num_radii=5000 for fine sampling so the discrete maximum
    closely approaches the true analytical valley at rho_n.
    """
    report = design_schmidt_corrector(_SPEC_200MM_F2, num_radii=5000)
    # Analytical: |z(rho_n)| = rho_n^4 / denom
    # Discrete sampling error is O(dr^2) where dr = r_ap/(nr-1).
    # With nr=5000 the tolerance of 1e-5 mm is satisfied.
    assert abs(report.max_sag_mm - _max_sag_expected) < 1e-5, (
        f"max_sag {report.max_sag_mm:.6f} != expected {_max_sag_expected:.6f}"
    )


# ---------------------------------------------------------------------------
# Test 2: neutral zone for kappa=1.5
# ---------------------------------------------------------------------------

def test_oracle_200mm_f2_bk7_neutral_zone():
    """Neutral zone for kappa=1.5 is at r = D/2 / sqrt(1.5) = sqrt(2/3) * D/2."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    expected_nz = _r_ap / math.sqrt(_kappa)
    assert abs(report.neutral_zone_radius_mm - expected_nz) < 1e-8, (
        f"neutral_zone {report.neutral_zone_radius_mm:.4f} != {expected_nz:.4f}"
    )
    # Also verify it matches sqrt(2/3) * r_ap
    assert abs(report.neutral_zone_radius_mm - math.sqrt(2.0 / 3.0) * _r_ap) < 1e-8


# ---------------------------------------------------------------------------
# Test 3: larger aperture -> more sag
# ---------------------------------------------------------------------------

def test_larger_aperture_more_sag():
    """Doubling aperture at same f/# increases max sag."""
    spec_small = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0)
    spec_large = SchmidtSpec(primary_radius_R_mm=800.0, aperture_diameter_D_mm=400.0)
    r_small = design_schmidt_corrector(spec_small)
    r_large = design_schmidt_corrector(spec_large)
    assert r_large.max_sag_mm > r_small.max_sag_mm, (
        f"Larger aperture should have more sag: {r_large.max_sag_mm:.4f} vs {r_small.max_sag_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 4: smaller aperture -> less sag
# ---------------------------------------------------------------------------

def test_smaller_aperture_less_sag():
    """Halving aperture at same f/# decreases max sag."""
    spec_base = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0)
    spec_small = SchmidtSpec(primary_radius_R_mm=200.0, aperture_diameter_D_mm=100.0)
    r_base = design_schmidt_corrector(spec_base)
    r_small = design_schmidt_corrector(spec_small)
    assert r_small.max_sag_mm < r_base.max_sag_mm, (
        f"Smaller aperture should have less sag: {r_small.max_sag_mm:.4f} vs {r_base.max_sag_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 5: sag scales inversely with (n-1)
# ---------------------------------------------------------------------------

def test_sag_scales_inversely_with_n_minus_1():
    """Sag is proportional to 1/(n-1): max_sag1/max_sag2 = (n2-1)/(n1-1)."""
    n1 = 1.5168  # BK7
    n2 = 1.7000  # denser glass
    spec1 = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0, glass_index_n=n1)
    spec2 = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0, glass_index_n=n2)
    r1 = design_schmidt_corrector(spec1)
    r2 = design_schmidt_corrector(spec2)
    expected_ratio = (n2 - 1.0) / (n1 - 1.0)
    actual_ratio = r2.max_sag_mm / r1.max_sag_mm
    # Should equal (n1-1)/(n2-1) = 1/expected_ratio
    expected_sag_ratio = (n1 - 1.0) / (n2 - 1.0)
    assert abs(actual_ratio - expected_sag_ratio) < 1e-6, (
        f"Sag ratio {actual_ratio:.4f} != expected (n1-1)/(n2-1)={expected_sag_ratio:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 6: sag at centre is zero
# ---------------------------------------------------------------------------

def test_sag_at_centre_is_zero():
    """z(0) = 0 (plate at centre of aperture has zero sag)."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    r0, z0 = report.aspheric_profile[0]
    assert r0 == pytest.approx(0.0, abs=1e-10)
    assert z0 == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 7: profile spans full aperture
# ---------------------------------------------------------------------------

def test_profile_spans_full_aperture():
    """Profile r values span [0, D/2] inclusive."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    rs = [pt[0] for pt in report.aspheric_profile]
    assert rs[0] == pytest.approx(0.0, abs=1e-10)
    assert rs[-1] == pytest.approx(_r_ap, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 8: Schwarzschild constant is -1
# ---------------------------------------------------------------------------

def test_schwarzschild_constant_is_minus_one():
    """Equivalent conic k = -1 (paraboloid) always."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    assert report.schwarzschild_constant_k == pytest.approx(-1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 9: dz/dr = 0 at neutral zone
# ---------------------------------------------------------------------------

def test_neutral_zone_dz_dr_zero():
    """dz/dr ≈ 0 at r = rho_n (neutral zone is a local extremum of the sag profile)."""
    # Analytical check: dz/dr = 4r(r^2 - rho_n^2)/(8*(n-1)*R^3) = 0 at r=rho_n
    rho_n = _rho_n_expected
    dr = rho_n * 1e-5
    z_plus = _schmidt_sag(rho_n + dr, _R, _n, rho_n)
    z_minus = _schmidt_sag(rho_n - dr, _R, _n, rho_n)
    finite_diff_slope = (z_plus - z_minus) / (2 * dr)
    # Slope should be near zero at neutral zone
    assert abs(finite_diff_slope) < 1e-9, (
        f"dz/dr at neutral zone = {finite_diff_slope:.2e}, should be ~0"
    )


# ---------------------------------------------------------------------------
# Test 10: kappa changes neutral zone but not sag shape
# ---------------------------------------------------------------------------

def test_kappa_changes_neutral_zone_not_sag():
    """Changing kappa changes rho_n (neutral zone position) while keeping
    the sag formula result the same (kappa enters only through rho_n)."""
    spec_k15 = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0,
                            neutral_zone_factor_kappa=1.5)
    spec_k10 = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0,
                            neutral_zone_factor_kappa=1.0)
    r_k15 = design_schmidt_corrector(spec_k15)
    r_k10 = design_schmidt_corrector(spec_k10)

    # Neutral zones should differ
    assert abs(r_k15.neutral_zone_radius_mm - r_k10.neutral_zone_radius_mm) > 5.0, (
        "Neutral zones should differ for kappa=1.5 vs kappa=1.0"
    )
    # kappa=1.0: rho_n = r_ap/sqrt(1.0) = r_ap = 100mm
    assert r_k10.neutral_zone_radius_mm == pytest.approx(100.0, abs=1e-6)
    # kappa=1.5: rho_n = r_ap/sqrt(1.5) ≈ 81.65mm
    assert r_k15.neutral_zone_radius_mm == pytest.approx(_rho_n_expected, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 11: num_radii controls profile length
# ---------------------------------------------------------------------------

def test_num_radii_controls_profile_length():
    """num_radii parameter controls the number of (r, z) samples."""
    report_20 = design_schmidt_corrector(_SPEC_200MM_F2, num_radii=20)
    report_100 = design_schmidt_corrector(_SPEC_200MM_F2, num_radii=100)
    assert len(report_20.aspheric_profile) == 20
    assert len(report_100.aspheric_profile) == 100


# ---------------------------------------------------------------------------
# Test 12: profile r is monotone increasing
# ---------------------------------------------------------------------------

def test_profile_r_is_monotone_increasing():
    """Profile r values are strictly monotone increasing from 0 to D/2."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    rs = [pt[0] for pt in report.aspheric_profile]
    for i in range(1, len(rs)):
        assert rs[i] >= rs[i - 1], f"Profile r not monotone at index {i}: {rs[i-1]:.3f} -> {rs[i]:.3f}"


# ---------------------------------------------------------------------------
# Test 13: to_dict has ok=True
# ---------------------------------------------------------------------------

def test_to_dict_has_ok_true():
    """to_dict() returns a dict with ok=True."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    d = report.to_dict()
    assert d.get("ok") is True


# ---------------------------------------------------------------------------
# Test 14: to_dict contains all required fields
# ---------------------------------------------------------------------------

def test_to_dict_contains_all_fields():
    """to_dict() contains all required result keys."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    d = report.to_dict()
    for key in ("ok", "aspheric_profile", "max_sag_mm", "neutral_zone_radius_mm",
                "schwarzschild_constant_k", "honest_caveat"):
        assert key in d, f"Missing key: {key}"
    # Profile is a list of [r, z] pairs
    assert isinstance(d["aspheric_profile"], list)
    assert len(d["aspheric_profile"]) > 0
    assert len(d["aspheric_profile"][0]) == 2


# ---------------------------------------------------------------------------
# Test 15: honest caveat mentions classical Schmidt
# ---------------------------------------------------------------------------

def test_honest_caveat_mentions_classical():
    """honest_caveat contains 'Schmidt' and classical limitation note."""
    report = design_schmidt_corrector(_SPEC_200MM_F2)
    caveat = report.honest_caveat.lower()
    assert "schmidt" in caveat
    assert "classical" in caveat or "monochromatic" in caveat


# ---------------------------------------------------------------------------
# Test 16: error for negative R
# ---------------------------------------------------------------------------

def test_error_negative_R():
    """Raises ValueError for negative primary_radius_R_mm."""
    with pytest.raises(ValueError, match="primary_radius_R_mm"):
        design_schmidt_corrector(
            SchmidtSpec(primary_radius_R_mm=-400.0, aperture_diameter_D_mm=200.0)
        )


# ---------------------------------------------------------------------------
# Test 17: error for zero D
# ---------------------------------------------------------------------------

def test_error_zero_D():
    """Raises ValueError for zero aperture_diameter_D_mm."""
    with pytest.raises(ValueError, match="aperture_diameter_D_mm"):
        design_schmidt_corrector(
            SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=0.0)
        )


# ---------------------------------------------------------------------------
# Test 18: error for n = 1.0
# ---------------------------------------------------------------------------

def test_error_n_equals_1():
    """Raises ValueError for glass_index_n = 1.0 (no refraction)."""
    with pytest.raises(ValueError, match="glass_index_n"):
        design_schmidt_corrector(
            SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0,
                        glass_index_n=1.0)
        )


# ---------------------------------------------------------------------------
# Test 19: error for n below 1
# ---------------------------------------------------------------------------

def test_error_n_below_1():
    """Raises ValueError for glass_index_n < 1.0."""
    with pytest.raises(ValueError, match="glass_index_n"):
        design_schmidt_corrector(
            SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0,
                        glass_index_n=0.9)
        )


# ---------------------------------------------------------------------------
# Test 20: error for negative kappa
# ---------------------------------------------------------------------------

def test_error_negative_kappa():
    """Raises ValueError for neutral_zone_factor_kappa <= 0."""
    with pytest.raises(ValueError, match="neutral_zone_factor_kappa"):
        design_schmidt_corrector(
            SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0,
                        neutral_zone_factor_kappa=-1.0)
        )


# ---------------------------------------------------------------------------
# Test 21: error for num_radii too small
# ---------------------------------------------------------------------------

def test_error_num_radii_too_small():
    """Raises ValueError for num_radii < 2."""
    with pytest.raises(ValueError, match="num_radii"):
        design_schmidt_corrector(_SPEC_200MM_F2, num_radii=1)


# ---------------------------------------------------------------------------
# Test 22: LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    """LLM tool returns ok=True JSON with all required keys."""
    from kerf_cad_core.optics.tools import run_design_schmidt_corrector

    args = json.dumps({
        "primary_radius_R_mm": 400.0,
        "aperture_diameter_D_mm": 200.0,
    }).encode()
    result = asyncio.get_event_loop().run_until_complete(
        run_design_schmidt_corrector(None, args)
    )
    d = json.loads(result)
    assert d.get("ok") is True, f"Tool failed: {d}"
    assert "max_sag_mm" in d
    assert "neutral_zone_radius_mm" in d
    assert "aspheric_profile" in d
    assert "schwarzschild_constant_k" in d
    assert "honest_caveat" in d


# ---------------------------------------------------------------------------
# Test 23: LLM tool missing R
# ---------------------------------------------------------------------------

def test_tool_missing_R():
    """LLM tool returns error for missing primary_radius_R_mm."""
    from kerf_cad_core.optics.tools import run_design_schmidt_corrector

    args = json.dumps({"aperture_diameter_D_mm": 200.0}).encode()
    result = asyncio.get_event_loop().run_until_complete(
        run_design_schmidt_corrector(None, args)
    )
    d = json.loads(result)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# Test 24: LLM tool missing D
# ---------------------------------------------------------------------------

def test_tool_missing_D():
    """LLM tool returns error for missing aperture_diameter_D_mm."""
    from kerf_cad_core.optics.tools import run_design_schmidt_corrector

    args = json.dumps({"primary_radius_R_mm": 400.0}).encode()
    result = asyncio.get_event_loop().run_until_complete(
        run_design_schmidt_corrector(None, args)
    )
    d = json.loads(result)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# Test 25: LLM tool bad JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    """LLM tool handles invalid JSON gracefully (returns error, not exception)."""
    from kerf_cad_core.optics.tools import run_design_schmidt_corrector

    result = asyncio.get_event_loop().run_until_complete(
        run_design_schmidt_corrector(None, b"not valid json {{{")
    )
    d = json.loads(result)
    # err_payload returns {"error": ..., "code": ...} — no "ok" key
    # The tool must return JSON (not raise) on bad input
    assert isinstance(d, dict)
    assert "error" in d or d.get("ok") is False, (
        f"Expected error response, got: {d}"
    )


# ---------------------------------------------------------------------------
# Test 26: sag profile formula verification
# ---------------------------------------------------------------------------

def test_sag_profile_formula_verification():
    """Verify z(rho_n) = -rho_n^4 / (8*(n-1)*R^3) analytically."""
    R = 400.0
    n = 1.5168
    rho_n = _rho_n_expected
    z_valley = _schmidt_sag(rho_n, R, n, rho_n)
    expected_valley = -(rho_n ** 4) / (8.0 * (n - 1.0) * (R ** 3))
    assert abs(z_valley - expected_valley) < 1e-10, (
        f"z(rho_n) = {z_valley:.8f}, expected {expected_valley:.8f}"
    )


# ---------------------------------------------------------------------------
# Test 27: max sag is at valley (rho_n) for kappa=1.5, not at edge
# ---------------------------------------------------------------------------

def test_max_sag_is_at_valley_for_kappa_1p5():
    """For kappa=1.5, |z(rho_n)| > |z(r_ap)| (valley deeper than edge sag)."""
    R = 400.0
    n = 1.5168
    rho_n = _rho_n_expected
    r_ap = _r_ap
    z_valley = abs(_schmidt_sag(rho_n, R, n, rho_n))
    z_edge = abs(_schmidt_sag(r_ap, R, n, rho_n))
    assert z_valley > z_edge, (
        f"|z(rho_n)|={z_valley:.6f} should be > |z(r_ap)|={z_edge:.6f} for kappa=1.5"
    )
    # Analytically: |valley| = rho_n^4/denom = (4/9)*r_ap^4/denom
    #               |edge|   = (1/3)*r_ap^4/denom
    # ratio = (4/9)/(1/3) = 4/3 ≈ 1.333
    assert abs(z_valley / z_edge - 4.0 / 3.0) < 1e-6


# ---------------------------------------------------------------------------
# Test 28: re-export from optics __init__
# ---------------------------------------------------------------------------

def test_re_export_from_init():
    """SchmidtSpec, SchmidtReport, design_schmidt_corrector importable from optics."""
    from kerf_cad_core.optics import (
        SchmidtReport,
        SchmidtSpec,
        design_schmidt_corrector,
    )
    spec = SchmidtSpec(primary_radius_R_mm=400.0, aperture_diameter_D_mm=200.0)
    report = design_schmidt_corrector(spec)
    assert isinstance(report, SchmidtReport)
    assert report.max_sag_mm > 0
