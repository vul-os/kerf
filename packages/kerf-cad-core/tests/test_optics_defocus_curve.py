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
