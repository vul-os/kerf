"""
Tests for kerf_cad_core.optics.sagitta_arrow_chart — OPTICS-SAGITTA-ARROW-CHART.

Test plan
---------
1.  sphere_R50_at_r10_sagitta          — z = R - √(R²−r²) ≈ 1.0102 (within 1e-6)
2.  paraboloid_k_minus1_z_r2_over_2R   — k=-1: z = r²/(2R) exactly (within 1e-10)
3.  sphere_z_monotone_increasing       — z(r) is strictly increasing for r > 0
4.  aspheric_a2_increases_max_sag      — adding a₂=0.001 increases max_sagitta
5.  aspheric_contribution_sign         — aspheric_contribution ~ a₂·r⁴ at edge
6.  svg_has_svg_tag                    — svg_chart contains '<svg'
7.  svg_has_polyline                   — svg_chart contains '<polyline'
8.  svg_has_viewBox                    — svg_chart contains 'viewBox'
9.  num_samples_length                 — sagitta_samples has num_samples+1 entries
10. r_zero_z_zero                      — first sample r=0, z=0 for any surface
11. r_equals_aperture_at_last_sample   — last sample r == clear_aperture_radius_mm
12. aperture_edge_90deg_sphere         — r=R sphere: z=R (surface vertex), within numerical
13. conic_only_sagitta_correct_sphere  — pure sphere (no aspheric): conic_only == max_sag
14. parabola_formula_multiple_r        — paraboloid z(r)=r²/(2R) at several r values
15. error_zero_radius                  — radius_mm=0 returns error dict
16. error_negative_aperture            — clear_aperture_radius_mm<=0 returns error
17. error_domain_violation             — aperture beyond domain returns error
18. error_num_samples_too_small        — num_samples<2 returns error
19. to_dict_ok_key                     — to_dict() returns ok=True
20. honest_caveat_zernike_not_impl     — honest_caveat mentions Zernike
21. tool_happy_path                    — LLM tool returns ok JSON with svg_chart
22. tool_missing_field                 — missing radius_mm returns ok=False
23. tool_bad_json                      — invalid JSON returns error payload
24. tool_num_samples_kwarg             — num_samples accepted by tool
25. hyperboloid_k_lt_minus1            — hyperboloid k=-2 sagitta < paraboloid
26. oblate_k_gt_0                      — oblate ellipsoid k=1 sagitta > sphere
27. svg_arrow_markers_present          — SVG contains arrow polygons for non-trivial surface
28. conic_only_matches_manual_sphere   — manual R=100, r=20: z_conic = 100-√(10000-400)

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.3.
ISO 10110-12:2019 — Aspheric surface specification.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.sagitta_arrow_chart import (
    AsphericSurfaceSpec,
    SagittaArrowChartResult,
    compute_sagitta_arrow_chart,
    _conic_sag,
    _aspheric_term,
    _sagitta,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _sphere_spec(R: float = 50.0, R_ap: float = 10.0) -> AsphericSurfaceSpec:
    return AsphericSurfaceSpec(
        radius_mm=R,
        conic_k=0.0,
        aspheric_coeffs=[],
        clear_aperture_radius_mm=R_ap,
    )


def _paraboloid_spec(R: float = 50.0, R_ap: float = 10.0) -> AsphericSurfaceSpec:
    return AsphericSurfaceSpec(
        radius_mm=R,
        conic_k=-1.0,
        aspheric_coeffs=[],
        clear_aperture_radius_mm=R_ap,
    )


def _invoke_tool(payload: dict) -> dict:
    """Call the LLM tool and return parsed JSON result."""
    from kerf_cad_core.optics.tools import run_compute_sagitta_arrow_chart
    return json.loads(asyncio.run(run_compute_sagitta_arrow_chart(None, json.dumps(payload).encode())))


# ---------------------------------------------------------------------------
# Test 1: Sphere R=50mm at r=10mm — sagitta ≈ 1.010204...
# ---------------------------------------------------------------------------

def test_sphere_R50_at_r10_sagitta():
    """
    For a sphere R=50, z(10) = 50 - √(50²−10²) = 50 - √(2400) ≈ 1.010205...
    Welford §3.3 formula: z = c·r²/(1+√(1−c²r²)) for k=0.
    """
    R = 50.0
    r = 10.0
    # Analytical: z = R - sqrt(R^2 - r^2)
    z_expected = R - math.sqrt(R * R - r * r)

    spec = _sphere_spec(R, r)
    result = compute_sagitta_arrow_chart(spec, num_samples=100)
    assert isinstance(result, SagittaArrowChartResult)

    # Find sample closest to r=10 (should be the last sample)
    r_last, z_last = result.sagitta_samples[-1]
    assert abs(r_last - r) < 1e-12
    assert abs(z_last - z_expected) < 1e-6, (
        f"z(10) = {z_last:.9f}, expected {z_expected:.9f} (sphere R=50)"
    )


# ---------------------------------------------------------------------------
# Test 2: Paraboloid k=-1 → z = r²/(2R) exactly
# ---------------------------------------------------------------------------

def test_paraboloid_k_minus1_z_r2_over_2R():
    """
    For k=-1 (paraboloid): z = c·r²/(1+1) = c·r²/2 = r²/(2R) exactly.
    This cancels the square root term since (1+k)=0 → discriminant=1 → sqrt=1.
    """
    R = 50.0
    r = 10.0
    z_expected = r * r / (2.0 * R)  # = 1.0 exactly

    spec = _paraboloid_spec(R, r)
    result = compute_sagitta_arrow_chart(spec, num_samples=100)
    assert isinstance(result, SagittaArrowChartResult)

    r_last, z_last = result.sagitta_samples[-1]
    assert abs(r_last - r) < 1e-12
    assert abs(z_last - z_expected) < 1e-10, (
        f"Paraboloid z(10) = {z_last:.12f}, expected {z_expected:.12f}"
    )


# ---------------------------------------------------------------------------
# Test 3: Sagitta monotone increasing for sphere
# ---------------------------------------------------------------------------

def test_sphere_z_monotone_increasing():
    """z(r) should be strictly increasing for a convex surface (R > 0, k=0)."""
    spec = _sphere_spec(R=50.0, R_ap=20.0)
    result = compute_sagitta_arrow_chart(spec, num_samples=50)
    assert isinstance(result, SagittaArrowChartResult)
    samples = result.sagitta_samples
    for i in range(1, len(samples)):
        assert samples[i][1] >= samples[i - 1][1], (
            f"z not monotone at index {i}: z[{i}]={samples[i][1]} < z[{i-1}]={samples[i-1][1]}"
        )


# ---------------------------------------------------------------------------
# Test 4: Adding aspheric coefficient increases max sagitta
# ---------------------------------------------------------------------------

def test_aspheric_a2_increases_max_sag():
    """
    A positive a₀ (r⁴ term) should increase the sagitta above the pure conic.
    """
    R_ap = 15.0
    spec_conic = AsphericSurfaceSpec(
        radius_mm=50.0, conic_k=0.0, aspheric_coeffs=[], clear_aperture_radius_mm=R_ap,
    )
    spec_asph = AsphericSurfaceSpec(
        radius_mm=50.0, conic_k=0.0, aspheric_coeffs=[0.001], clear_aperture_radius_mm=R_ap,
    )
    res_conic = compute_sagitta_arrow_chart(spec_conic, num_samples=50)
    res_asph = compute_sagitta_arrow_chart(spec_asph, num_samples=50)
    assert isinstance(res_conic, SagittaArrowChartResult)
    assert isinstance(res_asph, SagittaArrowChartResult)
    assert res_asph.max_sagitta_mm > res_conic.max_sagitta_mm


# ---------------------------------------------------------------------------
# Test 5: Aspheric contribution ~ a₀·r⁴ at aperture edge
# ---------------------------------------------------------------------------

def test_aspheric_contribution_sign():
    """
    aspheric_contribution = max_sag - conic_only_sag ≈ a₀·r⁴ at the edge.
    With a₀=0.001 and r=10, expected contribution ≈ 0.001·10000 = 10 mm.
    """
    a0 = 0.001
    R_ap = 10.0
    spec = AsphericSurfaceSpec(
        radius_mm=200.0, conic_k=0.0, aspheric_coeffs=[a0], clear_aperture_radius_mm=R_ap,
    )
    result = compute_sagitta_arrow_chart(spec, num_samples=50)
    assert isinstance(result, SagittaArrowChartResult)
    expected_contrib = a0 * R_ap ** 4  # = 10.0
    assert abs(result.aspheric_contribution_mm - expected_contrib) < 1e-6


# ---------------------------------------------------------------------------
# Test 6: SVG contains <svg tag
# ---------------------------------------------------------------------------

def test_svg_has_svg_tag():
    spec = _sphere_spec()
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, SagittaArrowChartResult)
    assert "<svg" in result.svg_chart


# ---------------------------------------------------------------------------
# Test 7: SVG contains <polyline
# ---------------------------------------------------------------------------

def test_svg_has_polyline():
    spec = _sphere_spec()
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, SagittaArrowChartResult)
    assert "<polyline" in result.svg_chart


# ---------------------------------------------------------------------------
# Test 8: SVG contains viewBox attribute
# ---------------------------------------------------------------------------

def test_svg_has_viewBox():
    spec = _sphere_spec()
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, SagittaArrowChartResult)
    assert "viewBox" in result.svg_chart


# ---------------------------------------------------------------------------
# Test 9: Number of samples = num_samples + 1 (r=0 included)
# ---------------------------------------------------------------------------

def test_num_samples_length():
    spec = _sphere_spec(R=50.0, R_ap=20.0)
    for n in (10, 25, 50):
        result = compute_sagitta_arrow_chart(spec, num_samples=n)
        assert isinstance(result, SagittaArrowChartResult)
        assert len(result.sagitta_samples) == n + 1


# ---------------------------------------------------------------------------
# Test 10: First sample at r=0, z=0
# ---------------------------------------------------------------------------

def test_r_zero_z_zero():
    """z(0) = 0 for any valid surface (conic + aspheric)."""
    spec = AsphericSurfaceSpec(
        radius_mm=50.0, conic_k=-1.5, aspheric_coeffs=[1e-4, -2e-6],
        clear_aperture_radius_mm=10.0,
    )
    result = compute_sagitta_arrow_chart(spec, num_samples=30)
    assert isinstance(result, SagittaArrowChartResult)
    r0, z0 = result.sagitta_samples[0]
    assert abs(r0) < 1e-12
    assert abs(z0) < 1e-12


# ---------------------------------------------------------------------------
# Test 11: Last sample r == clear_aperture_radius_mm
# ---------------------------------------------------------------------------

def test_r_equals_aperture_at_last_sample():
    R_ap = 17.5
    spec = AsphericSurfaceSpec(
        radius_mm=100.0, conic_k=0.0, aspheric_coeffs=[],
        clear_aperture_radius_mm=R_ap,
    )
    result = compute_sagitta_arrow_chart(spec, num_samples=40)
    assert isinstance(result, SagittaArrowChartResult)
    r_last, _ = result.sagitta_samples[-1]
    assert abs(r_last - R_ap) < 1e-12


# ---------------------------------------------------------------------------
# Test 12: Sphere r=R edge: z = R - √(R²-R²) = R ... wait, that's r=R exactly
# which makes the discriminant = 1 - c²R² = 1 - 1 = 0 → z = cR²/2 = R/2.
# Actually z = R - √(R²-R²) only applies to the geometric formula. The conic
# formula at r=R:  z = c·R²/(1+0) = 1/R · R² / 1 = R
# Let's verify: c=1/R, k=0, r=R → discriminant = 1-1=0 → z = cR²/(1+0) = R
# Actually R - sqrt(R²-R²) = R - 0 = R ✓ — both formulas agree.
# ---------------------------------------------------------------------------

def test_aperture_edge_equals_R_for_hemisphere():
    """
    For a sphere with R=aperture_radius (hemisphere): z at edge = R.
    z = c·R²/(1+√(1-c²R²)) = (1/R)·R²/(1+0) = R.
    """
    R = 20.0
    spec = AsphericSurfaceSpec(
        radius_mm=R, conic_k=0.0, aspheric_coeffs=[],
        clear_aperture_radius_mm=R,  # hemisphere: aperture = radius
    )
    result = compute_sagitta_arrow_chart(spec, num_samples=50)
    assert isinstance(result, SagittaArrowChartResult)
    r_last, z_last = result.sagitta_samples[-1]
    assert abs(r_last - R) < 1e-12
    assert abs(z_last - R) < 1e-6, (
        f"Hemisphere z at r=R: got {z_last:.6f}, expected {R:.6f}"
    )


# ---------------------------------------------------------------------------
# Test 13: Pure conic (no aspheric): conic_only_sagitta_mm == max_sagitta_mm
# ---------------------------------------------------------------------------

def test_conic_only_sagitta_correct_sphere():
    """With no aspheric coefficients, conic_only_sagitta_mm = max_sagitta_mm."""
    spec = _sphere_spec(R=80.0, R_ap=15.0)
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, SagittaArrowChartResult)
    assert abs(result.conic_only_sagitta_mm - result.max_sagitta_mm) < 1e-10
    assert abs(result.aspheric_contribution_mm) < 1e-10


# ---------------------------------------------------------------------------
# Test 14: Paraboloid formula at multiple r values
# ---------------------------------------------------------------------------

def test_parabola_formula_multiple_r():
    """Verify z = r²/(2R) at r=5, 10, 15, 20 for paraboloid k=-1."""
    R = 100.0
    R_ap = 20.0
    spec = _paraboloid_spec(R=R, R_ap=R_ap)
    result = compute_sagitta_arrow_chart(spec, num_samples=200)
    assert isinstance(result, SagittaArrowChartResult)

    # Find samples closest to r=5, 10, 15, 20
    samples_dict = {round(r, 6): z for r, z in result.sagitta_samples}
    for r_test in (5.0, 10.0, 15.0, 20.0):
        # Find nearest sample
        nearest_r = min(samples_dict.keys(), key=lambda x: abs(x - r_test))
        if abs(nearest_r - r_test) < 0.12:  # within half a step (step = 20/200 = 0.1)
            z_expected = nearest_r ** 2 / (2.0 * R)
            assert abs(samples_dict[nearest_r] - z_expected) < 1e-8, (
                f"Paraboloid z({nearest_r:.2f}) = {samples_dict[nearest_r]:.9f}, "
                f"expected {z_expected:.9f}"
            )


# ---------------------------------------------------------------------------
# Test 15: Error on zero radius
# ---------------------------------------------------------------------------

def test_error_zero_radius():
    spec = AsphericSurfaceSpec(
        radius_mm=0.0, conic_k=0.0, aspheric_coeffs=[],
        clear_aperture_radius_mm=10.0,
    )
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert "radius_mm" in result.get("reason", "")


# ---------------------------------------------------------------------------
# Test 16: Error on non-positive aperture
# ---------------------------------------------------------------------------

def test_error_negative_aperture():
    spec = AsphericSurfaceSpec(
        radius_mm=50.0, conic_k=0.0, aspheric_coeffs=[],
        clear_aperture_radius_mm=-5.0,
    )
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, dict)
    assert result.get("ok") is False


# ---------------------------------------------------------------------------
# Test 17: Error on domain violation (r > domain limit)
# ---------------------------------------------------------------------------

def test_error_domain_violation():
    """
    For k=2 (oblate ellipsoid), domain limit: (1+k)c²r² ≤ 1.
    With R=10, k=2: limit at r² = R²/3 → r < 5.77 mm.
    Requesting aperture=6 should trigger error.
    """
    spec = AsphericSurfaceSpec(
        radius_mm=10.0, conic_k=2.0, aspheric_coeffs=[],
        clear_aperture_radius_mm=6.0,  # exceeds domain for k=2, R=10
    )
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert "radicand" in result.get("reason", "").lower() or "domain" in result.get("reason", "").lower()


# ---------------------------------------------------------------------------
# Test 18: Error on num_samples too small
# ---------------------------------------------------------------------------

def test_error_num_samples_too_small():
    spec = _sphere_spec()
    result = compute_sagitta_arrow_chart(spec, num_samples=1)
    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert "num_samples" in result.get("reason", "")


# ---------------------------------------------------------------------------
# Test 19: to_dict returns ok=True
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    spec = _sphere_spec()
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, SagittaArrowChartResult)
    d = result.to_dict()
    assert d.get("ok") is True


# ---------------------------------------------------------------------------
# Test 20: honest_caveat mentions Zernike
# ---------------------------------------------------------------------------

def test_honest_caveat_zernike_not_impl():
    spec = _sphere_spec()
    result = compute_sagitta_arrow_chart(spec)
    assert isinstance(result, SagittaArrowChartResult)
    assert "Zernike" in result.honest_caveat


# ---------------------------------------------------------------------------
# Test 21: LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    payload = {
        "radius_mm": 50.0,
        "conic_k": 0.0,
        "aspheric_coeffs": [],
        "clear_aperture_radius_mm": 10.0,
    }
    data = _invoke_tool(payload)
    assert data.get("ok") is True
    assert "svg_chart" in data
    assert "sagitta_samples" in data
    assert "max_sagitta_mm" in data


# ---------------------------------------------------------------------------
# Test 22: LLM tool missing required field
# ---------------------------------------------------------------------------

def test_tool_missing_field():
    payload = {
        "conic_k": 0.0,
        "aspheric_coeffs": [],
        "clear_aperture_radius_mm": 10.0,
        # radius_mm missing
    }
    data = _invoke_tool(payload)
    assert data.get("ok") is False


# ---------------------------------------------------------------------------
# Test 23: LLM tool bad JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    from kerf_cad_core.optics.tools import run_compute_sagitta_arrow_chart
    data = json.loads(asyncio.run(run_compute_sagitta_arrow_chart(None, b"not valid {{{ json")))
    assert data.get("ok") is False or data.get("code") == "BAD_ARGS" or "error" in data


# ---------------------------------------------------------------------------
# Test 24: LLM tool accepts num_samples
# ---------------------------------------------------------------------------

def test_tool_num_samples_kwarg():
    payload = {
        "radius_mm": 50.0,
        "conic_k": 0.0,
        "aspheric_coeffs": [],
        "clear_aperture_radius_mm": 10.0,
        "num_samples": 20,
    }
    data = _invoke_tool(payload)
    assert data.get("ok") is True
    assert len(data["sagitta_samples"]) == 21  # num_samples + 1


# ---------------------------------------------------------------------------
# Test 25: Hyperboloid k < -1 sagitta < paraboloid at same r
# ---------------------------------------------------------------------------

def test_hyperboloid_k_lt_minus1():
    """
    Hyperboloid (k=-2) has less sag than paraboloid (k=-1) for the same R and r.
    (More negative k → flatter near vertex.)
    """
    R = 100.0
    R_ap = 10.0
    spec_hyp = AsphericSurfaceSpec(
        radius_mm=R, conic_k=-2.0, aspheric_coeffs=[],
        clear_aperture_radius_mm=R_ap,
    )
    spec_par = _paraboloid_spec(R=R, R_ap=R_ap)
    res_hyp = compute_sagitta_arrow_chart(spec_hyp)
    res_par = compute_sagitta_arrow_chart(spec_par)
    assert isinstance(res_hyp, SagittaArrowChartResult)
    assert isinstance(res_par, SagittaArrowChartResult)
    assert res_hyp.max_sagitta_mm < res_par.max_sagitta_mm


# ---------------------------------------------------------------------------
# Test 26: Oblate ellipsoid k > 0 has more sag than sphere
# ---------------------------------------------------------------------------

def test_oblate_k_gt_0():
    """
    Oblate ellipsoid (k=+0.5) has more sag than sphere (k=0) for the same R and r.
    """
    R = 50.0
    R_ap = 10.0
    spec_oblate = AsphericSurfaceSpec(
        radius_mm=R, conic_k=0.5, aspheric_coeffs=[],
        clear_aperture_radius_mm=R_ap,
    )
    spec_sphere = _sphere_spec(R=R, R_ap=R_ap)
    res_oblate = compute_sagitta_arrow_chart(spec_oblate)
    res_sphere = compute_sagitta_arrow_chart(spec_sphere)
    assert isinstance(res_oblate, SagittaArrowChartResult)
    assert isinstance(res_sphere, SagittaArrowChartResult)
    assert res_oblate.max_sagitta_mm > res_sphere.max_sagitta_mm


# ---------------------------------------------------------------------------
# Test 27: SVG arrow markers present for non-trivial surface with enough samples
# ---------------------------------------------------------------------------

def test_svg_arrow_markers_present():
    """
    With 50 samples, index 5, 10, 15, … should produce arrow polygon markers.
    The SVG should contain at least one <polygon (arrowhead).
    """
    spec = _sphere_spec(R=50.0, R_ap=20.0)
    result = compute_sagitta_arrow_chart(spec, num_samples=50)
    assert isinstance(result, SagittaArrowChartResult)
    assert "<polygon" in result.svg_chart


# ---------------------------------------------------------------------------
# Test 28: Manual sphere R=100, r=20: z = R - √(R²-r²) = 100 - √9600
# ---------------------------------------------------------------------------

def test_conic_only_matches_manual_sphere():
    """
    Sphere R=100mm, r=20mm: z = 100 - √(10000 - 400) = 100 - √9600 ≈ 2.0408...
    """
    R = 100.0
    r = 20.0
    z_expected = R - math.sqrt(R * R - r * r)

    spec = _sphere_spec(R=R, R_ap=r)
    result = compute_sagitta_arrow_chart(spec, num_samples=200)
    assert isinstance(result, SagittaArrowChartResult)

    r_last, z_last = result.sagitta_samples[-1]
    assert abs(z_last - z_expected) < 1e-6, (
        f"z(20) = {z_last:.9f}, expected {z_expected:.9f} (sphere R=100)"
    )
    # conic_only == max_sagitta for pure sphere
    assert abs(result.conic_only_sagitta_mm - z_expected) < 1e-6
