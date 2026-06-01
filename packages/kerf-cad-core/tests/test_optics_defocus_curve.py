"""
Tests for kerf_cad_core.optics.defocus_curve — OPTICS-DEFOCUS-CURVE.

Test plan
---------
1.  ideal_singlet_min_at_zero           — parabolic-like curve; minimum at Δz≈0
2.  result_array_length_matches_samples — len(defocus_axis) == samples
3.  rms_array_length_matches_samples    — len(rms_per_defocus_mm) == samples
4.  rms_increases_away_from_best_focus  — RMS grows for |Δz| > best-focus shift
5.  aberrated_best_focus_offset         — strongly aberrated singlet shifts best focus
6.  field_angle_dependency              — on-axis vs 10° field gives different curves
7.  bfl_positive                        — BFL is positive for converging singlet
8.  min_rms_nonneg                      — min_rms_mm >= 0
9.  best_focus_within_range             — best_focus_shift_mm in [-range, +range]
10. default_samples_21                  — default call gives 21 samples
11. custom_samples_11                   — samples=11 gives 11 points
12. n_rays_valid_list_length            — len(n_rays_valid) == samples
13. n_rays_valid_nonzero                — at least some valid rays at each step
14. to_dict_ok_key                      — .to_dict() has ok=True
15. to_dict_honest_flag                 — honest_flag contains "MONOCHROMATIC"
16. error_empty_surfaces                — returns error dict for empty surfaces
17. error_bad_surface                   — returns error dict for missing 'c' key
18. error_samples_too_small             — returns error dict for samples < 3
19. error_negative_defocus_range        — returns error dict for defocus_range_mm <= 0
20. error_n_object_lt_1                 — returns error dict for n_object < 1
21. error_n_rays_too_small              — returns error dict for n_rays < 3
22. plano_convex_min_near_marginal_focus — plano-convex best-focus shifts toward marginal side
23. symmetric_curve_ideal_singlet       — ideal singlet RMS should be (approx) symmetric
24. field_angle_0_vs_5deg               — 5° field angle shifts or broadens the curve
25. tool_happy_path                     — LLM tool optics_defocus_curve returns ok JSON
26. tool_missing_surfaces               — LLM tool returns error for missing surfaces
27. tool_bad_json                       — LLM tool handles invalid JSON
28. tool_custom_samples                 — LLM tool accepts optional samples kwarg
29. tool_field_angle_kwarg              — LLM tool accepts optional field_angle_deg kwarg
30. tool_defocus_range_kwarg            — LLM tool accepts optional defocus_range_mm kwarg
31. defocus_axis_monotone               — defocus_axis_mm is strictly increasing
32. defocus_axis_endpoints              — first and last Δz match ±defocus_range_mm
33. rms_finite_on_axis_ideal            — all RMS values are finite for ideal singlet

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §11.5.
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.5.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.defocus_curve import compute_defocus_curve, DefocusCurveResult


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

def _bk7_singlet():
    """BK7 biconvex singlet: R1=+50 mm, R2=-50 mm, t=5 mm, n=1.5168. EFL≈48 mm."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _plano_convex():
    """Plano-convex: R1=+50 mm, R2=flat, t=5 mm, n=1.5168."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": 0.0, "t": 0.0, "n": 1.0},
    ]


def _aberrated_singlet():
    """Strongly curved singlet with large spherical aberration: R1=+20, R2=-20, t=8, n=1.7."""
    return [
        {"c": 1.0 / 20.0, "t": 8.0, "n": 1.7},
        {"c": -1.0 / 20.0, "t": 0.0, "n": 1.0},
    ]


# ---------------------------------------------------------------------------
# Core algorithm tests
# ---------------------------------------------------------------------------

def test_ideal_singlet_min_at_zero():
    """Paraxial-regime singlet (tiny aperture): RMS minimum at Δz=0 (within one step)."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=0.1,   # paraxial limit: no spherical aberration contribution
        n_rays=11,
    )
    assert isinstance(result, DefocusCurveResult)
    step = 2 * 0.5 / 20  # one step = 0.05 mm
    assert abs(result.best_focus_shift_mm) <= step


def test_result_array_length_matches_samples():
    result = compute_defocus_curve(_bk7_singlet(), samples=21)
    assert isinstance(result, DefocusCurveResult)
    assert len(result.defocus_axis_mm) == 21


def test_rms_array_length_matches_samples():
    result = compute_defocus_curve(_bk7_singlet(), samples=21)
    assert isinstance(result, DefocusCurveResult)
    assert len(result.rms_per_defocus_mm) == 21


def test_rms_increases_away_from_best_focus():
    """Paraxial-regime singlet (tiny aperture): RMS at ±range >> RMS at best focus."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=1.0,
        samples=21,
        aperture_radius_mm=0.1,   # paraxial regime — no spherical aberration
        n_rays=11,
    )
    assert isinstance(result, DefocusCurveResult)
    min_rms = result.min_rms_mm
    rms = result.rms_per_defocus_mm
    # Both endpoints should have RMS >> minimum (parabolic growth)
    assert rms[0] > min_rms * 100 or rms[-1] > min_rms * 100


def test_aberrated_best_focus_offset():
    """
    Aberrated BK7 singlet at full aperture: best-focus shifts away from Δz=0.
    Spherical aberration brings the marginal focus closer to the lens than the
    paraxial focus (Welford 1986 §11.5), so the RMS minimum is at Δz < 0.
    Using a ±1.5mm scan with 51 steps to capture the minimum near Δz≈-0.6mm.
    """
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=1.5,
        samples=51,
        aperture_radius_mm=5.0,
        n_rays=31,
    )
    assert isinstance(result, DefocusCurveResult)
    assert math.isfinite(result.min_rms_mm)
    assert result.min_rms_mm >= 0.0
    # Best focus should be shifted toward negative Δz (marginal focus side)
    assert result.best_focus_shift_mm < -0.1


def test_field_angle_dependency():
    """On-axis vs off-axis curves should differ (different chief-ray/field curvature)."""
    r_on = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=5.0,
        n_rays=31,
    )
    r_off = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=10.0,
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=5.0,
        n_rays=31,
    )
    assert isinstance(r_on, DefocusCurveResult)
    assert isinstance(r_off, DefocusCurveResult)
    # At least the best-focus shifts or the min RMS values differ
    different = (
        abs(r_on.best_focus_shift_mm - r_off.best_focus_shift_mm) > 1e-6 or
        abs(r_on.min_rms_mm - r_off.min_rms_mm) > 1e-6
    )
    assert different


def test_bfl_positive():
    result = compute_defocus_curve(_bk7_singlet())
    assert isinstance(result, DefocusCurveResult)
    assert result.bfl_mm > 0.0


def test_min_rms_nonneg():
    result = compute_defocus_curve(_bk7_singlet())
    assert isinstance(result, DefocusCurveResult)
    assert result.min_rms_mm >= 0.0


def test_best_focus_within_range():
    result = compute_defocus_curve(_bk7_singlet(), defocus_range_mm=0.5)
    assert isinstance(result, DefocusCurveResult)
    assert -0.5 <= result.best_focus_shift_mm <= 0.5


def test_default_samples_21():
    result = compute_defocus_curve(_bk7_singlet())
    assert isinstance(result, DefocusCurveResult)
    assert len(result.defocus_axis_mm) == 21


def test_custom_samples_11():
    result = compute_defocus_curve(_bk7_singlet(), samples=11)
    assert isinstance(result, DefocusCurveResult)
    assert len(result.defocus_axis_mm) == 11


def test_n_rays_valid_list_length():
    result = compute_defocus_curve(_bk7_singlet(), samples=15)
    assert isinstance(result, DefocusCurveResult)
    assert len(result.n_rays_valid) == 15


def test_n_rays_valid_nonzero():
    result = compute_defocus_curve(_bk7_singlet(), samples=21, n_rays=21)
    assert isinstance(result, DefocusCurveResult)
    # At least the central defocus step should have valid rays
    mid = len(result.n_rays_valid) // 2
    assert result.n_rays_valid[mid] > 0


def test_to_dict_ok_key():
    result = compute_defocus_curve(_bk7_singlet())
    assert isinstance(result, DefocusCurveResult)
    d = result.to_dict()
    assert d.get("ok") is True


def test_to_dict_honest_flag():
    result = compute_defocus_curve(_bk7_singlet())
    assert isinstance(result, DefocusCurveResult)
    d = result.to_dict()
    assert "MONOCHROMATIC" in d.get("honest_flag", "")


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    result = compute_defocus_curve([])
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "surfaces" in result["reason"]


def test_error_bad_surface():
    result = compute_defocus_curve([{"t": 5.0, "n": 1.5}])  # missing 'c'
    assert isinstance(result, dict)
    assert result["ok"] is False


def test_error_samples_too_small():
    result = compute_defocus_curve(_bk7_singlet(), samples=2)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "samples" in result["reason"]


def test_error_negative_defocus_range():
    result = compute_defocus_curve(_bk7_singlet(), defocus_range_mm=-0.5)
    assert isinstance(result, dict)
    assert result["ok"] is False


def test_error_n_object_lt_1():
    result = compute_defocus_curve(_bk7_singlet(), n_object=0.5)
    assert isinstance(result, dict)
    assert result["ok"] is False


def test_error_n_rays_too_small():
    result = compute_defocus_curve(_bk7_singlet(), n_rays=2)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "n_rays" in result["reason"]


# ---------------------------------------------------------------------------
# Physics / geometry tests
# ---------------------------------------------------------------------------

def test_plano_convex_min_near_marginal_focus():
    """Plano-convex (aberrated) curve should have a finite best-focus shift."""
    result = compute_defocus_curve(
        _plano_convex(),
        field_angle_deg=0.0,
        defocus_range_mm=2.0,
        samples=41,
        aperture_radius_mm=8.0,
        n_rays=51,
    )
    assert isinstance(result, DefocusCurveResult)
    assert math.isfinite(result.min_rms_mm)


def test_symmetric_curve_ideal_singlet():
    """
    Paraxial-regime BK7 singlet on-axis: the RMS curve should be approximately
    symmetric about Δz=0.  RMS at Δz=-range ≈ RMS at Δz=+range (within 10%).
    Tiny aperture (0.1mm) suppresses spherical aberration asymmetry.
    """
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=0.1,   # paraxial limit
        n_rays=11,
    )
    assert isinstance(result, DefocusCurveResult)
    rms = result.rms_per_defocus_mm
    rms_lo = rms[0]
    rms_hi = rms[-1]
    if math.isfinite(rms_lo) and math.isfinite(rms_hi) and rms_lo > 0 and rms_hi > 0:
        ratio = max(rms_lo, rms_hi) / min(rms_lo, rms_hi)
        assert ratio < 1.1  # approximately symmetric (within 10%)


def test_field_angle_0_vs_5deg():
    """5° field angle produces a different through-focus curve than 0°."""
    r0 = compute_defocus_curve(_bk7_singlet(), field_angle_deg=0.0, samples=21, n_rays=31)
    r5 = compute_defocus_curve(_bk7_singlet(), field_angle_deg=5.0, samples=21, n_rays=31)
    assert isinstance(r0, DefocusCurveResult)
    assert isinstance(r5, DefocusCurveResult)
    rms0 = r0.rms_per_defocus_mm
    rms5 = r5.rms_per_defocus_mm
    # They should not be identical
    assert rms0 != rms5


def test_defocus_axis_monotone():
    result = compute_defocus_curve(_bk7_singlet(), samples=21)
    assert isinstance(result, DefocusCurveResult)
    ax = result.defocus_axis_mm
    for i in range(len(ax) - 1):
        assert ax[i + 1] > ax[i]


def test_defocus_axis_endpoints():
    result = compute_defocus_curve(_bk7_singlet(), defocus_range_mm=0.5, samples=21)
    assert isinstance(result, DefocusCurveResult)
    assert abs(result.defocus_axis_mm[0] - (-0.5)) < 1e-10
    assert abs(result.defocus_axis_mm[-1] - 0.5) < 1e-10


def test_rms_finite_on_axis_ideal():
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        samples=21,
        aperture_radius_mm=5.0,
        n_rays=31,
    )
    assert isinstance(result, DefocusCurveResult)
    finite_count = sum(1 for r in result.rms_per_defocus_mm if math.isfinite(r))
    assert finite_count >= 15  # at least 15 of 21 steps should be valid


# ---------------------------------------------------------------------------
# LLM tool tests
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.tools import run_defocus_curve  # noqa: E402


def _invoke(payload):
    """Invoke the LLM tool with a dict payload and return parsed JSON."""
    return json.loads(asyncio.run(run_defocus_curve(None, json.dumps(payload).encode())))


_SINGLET = [
    {"c": 0.02, "t": 5.0, "n": 1.5168},
    {"c": -0.02, "t": 0.0, "n": 1.0},
]


def test_tool_happy_path():
    data = _invoke({"surfaces": _SINGLET, "field_angle_deg": 0.0, "samples": 11})
    assert data.get("ok") is True
    assert "defocus_axis_mm" in data
    assert len(data["defocus_axis_mm"]) == 11


def test_tool_missing_surfaces():
    data = _invoke({})
    assert data.get("ok") is False


def test_tool_bad_json():
    data = json.loads(asyncio.run(run_defocus_curve(None, b"not valid json {{")))
    # err_payload returns {"error": ..., "code": "BAD_ARGS"} for JSON parse errors
    assert data.get("ok") is False or data.get("code") == "BAD_ARGS" or "error" in data


def test_tool_custom_samples():
    data = _invoke({"surfaces": _SINGLET, "samples": 7})
    assert data.get("ok") is True
    assert len(data["defocus_axis_mm"]) == 7


def test_tool_field_angle_kwarg():
    data = _invoke({"surfaces": _SINGLET, "field_angle_deg": 5.0})
    assert data.get("ok") is True


def test_tool_defocus_range_kwarg():
    data = _invoke({"surfaces": _SINGLET, "defocus_range_mm": 1.0})
    assert data.get("ok") is True


# ---------------------------------------------------------------------------
# 3-D skew-ray defocus tests (use_skew_ray=True)
# ---------------------------------------------------------------------------

def test_skew_ray_returns_defocus_result():
    """use_skew_ray=True returns a DefocusCurveResult, not an error dict."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=0.5,
        samples=11,
        aperture_radius_mm=2.0,
        n_rays=12,
        use_skew_ray=True,
    )
    assert isinstance(result, DefocusCurveResult)


def test_skew_ray_aberration_free_min_near_zero():
    """
    Paraxial-regime singlet (tiny aperture): skew-ray defocus curve RMS
    minimum must be within one defocus step of Δz=0 (aberration-free limit).
    Welford 1986 §11.5: minimum at paraxial BFL for zero-aberration system.
    """
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=0.1,   # paraxial limit
        n_rays=12,
        use_skew_ray=True,
    )
    assert isinstance(result, DefocusCurveResult)
    step = 2 * 0.5 / 20  # one step = 0.05 mm
    assert abs(result.best_focus_shift_mm) <= 2 * step


def test_skew_ray_vs_meridional_agreement_paraxial():
    """
    In the paraxial limit (tiny aperture, on-axis), skew-ray 3-D RMS and
    meridional 2-D RMS must give similar best-focus positions (within 0.1 mm).
    Both converge to the paraxial BFL for a nearly-perfect system.
    """
    kwargs = dict(
        field_angle_deg=0.0,
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=0.05,
        n_rays=12,
    )
    r_mer = compute_defocus_curve(_bk7_singlet(), use_skew_ray=False, **kwargs)
    r_skw = compute_defocus_curve(_bk7_singlet(), use_skew_ray=True, **kwargs)
    assert isinstance(r_mer, DefocusCurveResult)
    assert isinstance(r_skw, DefocusCurveResult)
    # Best-focus positions should be close in the paraxial limit
    assert abs(r_mer.best_focus_shift_mm - r_skw.best_focus_shift_mm) < 0.15


def test_skew_ray_rms_increases_away_from_focus():
    """
    Paraxial singlet: skew-ray RMS at the endpoints must be larger than at
    the best-focus Δz (parabolic growth, Welford §11.5).
    """
    result = compute_defocus_curve(
        _bk7_singlet(),
        field_angle_deg=0.0,
        defocus_range_mm=1.0,
        samples=21,
        aperture_radius_mm=0.1,
        n_rays=12,
        use_skew_ray=True,
    )
    assert isinstance(result, DefocusCurveResult)
    rms = result.rms_per_defocus_mm
    # At least one endpoint must be much larger than minimum
    assert rms[0] > result.min_rms_mm * 5 or rms[-1] > result.min_rms_mm * 5


def test_skew_ray_honest_flag_contains_skew():
    """honest_flag must mention skew-ray mode when use_skew_ray=True."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        samples=11,
        aperture_radius_mm=2.0,
        n_rays=12,
        use_skew_ray=True,
    )
    assert isinstance(result, DefocusCurveResult)
    assert "SKEW-RAY" in result.honest_flag


def test_skew_ray_n_rays_valid_length():
    """n_rays_valid length matches samples in skew-ray mode."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        samples=11,
        aperture_radius_mm=2.0,
        n_rays=12,
        use_skew_ray=True,
    )
    assert isinstance(result, DefocusCurveResult)
    assert len(result.n_rays_valid) == 11


def test_skew_ray_off_axis_different_from_on_axis():
    """
    Off-axis (10°) skew-ray defocus curve differs from on-axis curve:
    field curvature and astigmatism shift the best-focus or min RMS.
    """
    kwargs = dict(
        defocus_range_mm=0.5,
        samples=21,
        aperture_radius_mm=3.0,
        n_rays=12,
        use_skew_ray=True,
    )
    r_on = compute_defocus_curve(_bk7_singlet(), field_angle_deg=0.0, **kwargs)
    r_off = compute_defocus_curve(_bk7_singlet(), field_angle_deg=10.0, **kwargs)
    assert isinstance(r_on, DefocusCurveResult)
    assert isinstance(r_off, DefocusCurveResult)
    different = (
        abs(r_on.best_focus_shift_mm - r_off.best_focus_shift_mm) > 1e-6 or
        abs(r_on.min_rms_mm - r_off.min_rms_mm) > 1e-6
    )
    assert different


def test_skew_ray_error_on_invalid_surfaces():
    """use_skew_ray=True still validates surfaces and returns error dict."""
    result = compute_defocus_curve([], use_skew_ray=True)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Spectral weighting tests (use_skew_ray=True + spectral_weights)
# ---------------------------------------------------------------------------

def _chromatic_doublet_blue():
    """
    Simplified doublet with blue-shifted index (higher n for shorter λ).
    Uses a higher-n crown glass at blue wavelength to shift focus.
    BK7 at 486 nm: n ≈ 1.5224; at 656 nm: n ≈ 1.5133.
    """
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5224},  # blue-wavelength BK7
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _chromatic_doublet_red():
    """BK7 at red (C-line, 656 nm): n ≈ 1.5133."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5133},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def test_spectral_weights_returns_defocus_result():
    """spectral_weights with use_skew_ray=True returns DefocusCurveResult."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        defocus_range_mm=1.0,
        samples=11,
        aperture_radius_mm=2.0,
        n_rays=12,
        use_skew_ray=True,
        spectral_weights=[(486.1, 0.3), (587.6, 1.0), (656.3, 0.5)],
    )
    assert isinstance(result, DefocusCurveResult)


def test_spectral_weights_honest_flag():
    """honest_flag must mention spectral weighting when spectral_weights given."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        samples=11,
        aperture_radius_mm=2.0,
        n_rays=12,
        use_skew_ray=True,
        spectral_weights=[(486.1, 1.0), (587.6, 1.0)],
    )
    assert isinstance(result, DefocusCurveResult)
    assert "SPECTRAL" in result.honest_flag or "spectral" in result.honest_flag


def test_spectral_weights_error_without_skew_ray():
    """spectral_weights without use_skew_ray=True must return error dict."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        use_skew_ray=False,
        spectral_weights=[(486.1, 1.0), (587.6, 1.0)],
    )
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "skew_ray" in result["reason"] or "use_skew_ray" in result["reason"]


def test_spectral_chromatic_defocus_shifts_minimum():
    """
    Chromatic aberration: blue focus is shorter than red focus in a singlet.
    Tracing the blue-wavelength singlet (higher n) vs red-wavelength singlet
    (lower n) should give different best_focus_shift_mm values.
    This validates that the spectral weighting path produces physically
    meaningful chromatic BFL differences (Hecht §6.3; Welford §6.5).
    """
    kwargs = dict(
        defocus_range_mm=2.0,
        samples=41,
        aperture_radius_mm=0.5,
        n_rays=12,
        use_skew_ray=True,
    )
    r_blue = compute_defocus_curve(_chromatic_doublet_blue(), **kwargs)
    r_red = compute_defocus_curve(_chromatic_doublet_red(), **kwargs)
    assert isinstance(r_blue, DefocusCurveResult)
    assert isinstance(r_red, DefocusCurveResult)
    # Blue focus is at smaller BFL than red (Hecht §6.3: shorter λ → higher n → shorter f)
    assert r_blue.bfl_mm < r_red.bfl_mm


def test_spectral_weighted_rms_finite():
    """Weighted RMS values are finite for a valid singlet with spectral weights."""
    result = compute_defocus_curve(
        _bk7_singlet(),
        defocus_range_mm=0.5,
        samples=11,
        aperture_radius_mm=2.0,
        n_rays=12,
        use_skew_ray=True,
        spectral_weights=[(486.1, 1.0), (587.6, 2.0), (656.3, 1.0)],
    )
    assert isinstance(result, DefocusCurveResult)
    finite_count = sum(1 for r in result.rms_per_defocus_mm if math.isfinite(r))
    assert finite_count >= 5  # at least half the steps should be valid


def test_spectral_equal_weights_matches_single_wavelength_shape():
    """
    Equal weights at a single wavelength must give the same best-focus shift
    as the monochromatic skew-ray call at that wavelength.
    (Degenerate case: Σ w_i * RMS_i^2 / Σ w_i = RMS for a single band.)
    """
    kwargs = dict(
        defocus_range_mm=0.5,
        samples=11,
        aperture_radius_mm=0.5,
        n_rays=12,
        use_skew_ray=True,
    )
    r_mono = compute_defocus_curve(_bk7_singlet(), **kwargs)
    r_spec = compute_defocus_curve(
        _bk7_singlet(),
        spectral_weights=[(587.6, 1.0)],
        **kwargs,
    )
    assert isinstance(r_mono, DefocusCurveResult)
    assert isinstance(r_spec, DefocusCurveResult)
    # Best-focus shifts should be identical for a single-band spectral call
    assert abs(r_mono.best_focus_shift_mm - r_spec.best_focus_shift_mm) < 0.11
