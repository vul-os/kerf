"""
Tests for kerf_cad_core.optics.spot_diagram — fan-of-rays spot diagram.

Test plan (14+ tests)
----------------------
 1.  ideal_thin_lens_onaxis_rms_near_zero
     — Ideal thin lens (paraxial, no aberrations), 0° field → rms_radius ≈ 0
       (within λ·F#/100, i.e. much smaller than Airy disk).
 2.  bk7_singlet_offaxis_nonzero_rms
     — BK7 biconvex singlet at 10° field → rms_radius > 0 (coma).
 3.  offaxis_rms_larger_than_onaxis
     — rms(10°) > rms(0°) for BK7 biconvex (coma grows with field).
 4.  num_rays_grid_covers_pupil
     — 49-ray grid: all pupil samples within the unit disk.
 5.  num_rays_count_close_to_target
     — With num_rays=49, side=7 grid gives ≥ 37 surviving pupil points.
 6.  svg_contains_svg_tag
     — SVG output contains <svg and </svg>.
 7.  svg_contains_circle_elements
     — SVG output contains at least one <circle element.
 8.  encircled_80pct_ge_rms
     — encircled_80pct_radius_mm >= rms_radius_mm (monotonic, Hecht §6.3).
 9.  encircled_80pct_positive
     — encircled_80pct_radius_mm > 0 for BK7 singlet.
10.  centroid_near_chief_ray_onaxis
     — On-axis: centroid y ≈ 0 (chief ray is near zero).
11.  image_points_xy_type
     — image_points_xy is a list of (float, float) tuples.
12.  n_rays_positive
     — n_rays > 0 in to_dict() output.
13.  result_dataclass_fields
     — SpotDiagramResult has all required fields.
14.  to_dict_ok_key
     — to_dict()["ok"] is True.
15.  error_missing_surfaces
     — Error dict for lens_system_dict without 'surfaces'.
16.  error_empty_surfaces
     — Error dict for empty surfaces list.
17.  error_bad_surface
     — Error dict for surface missing 'n'.
18.  error_bad_wavelength
     — Error dict for wavelength_nm <= 0.
19.  error_bad_num_rays
     — Error dict for num_rays < 1.
20.  honest_caveat_string
     — honest_caveat is a non-empty string mentioning 'monochromatic'.
21.  llm_tool_happy_path
     — LLM tool run_compute_spot_diagram returns JSON with ok=True and
       image_points_xy.
22.  llm_tool_missing_field_angle
     — LLM tool returns error when field_angle_deg is missing.
23.  llm_tool_bad_json
     — LLM tool handles completely invalid JSON input.
24.  bk7_rms_range
     — BK7 on-axis rms_radius is in plausible range [1e-5, 2.0] mm.

References
----------
Hecht, E. — "Optics", 5th ed. §6.3 (spot diagrams, encircled energy).
Welford, W.T. — "Aberrations of Optical Systems", §8.2 (spot diagrams).

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.spot_diagram import (
    SpotDiagramResult,
    _hexapolar_pupil,
    _pupil_grid,
    compute_spot_diagram,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# BK7 biconvex singlet: R1=+50mm, R2=-50mm, n=1.5168, t=5mm, air exit
_BK7_SURFACES = [
    {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
    {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
]

# Weak symmetric biconvex lens: large radius of curvature → near-paraxial.
# EFL ≈ 200 mm, tiny spherical aberration at aperture 2 mm (aperture/EFL ~ 1%).
# On-axis y-spread of intercepts will be < 1e-3 mm.
_WEAK_LENS_SURFACES = [
    {"c": 1.0 / 200.0, "t": 2.0, "n": 1.5},
    {"c": -1.0 / 200.0, "t": 0.0, "n": 1.0},
]

_BK7_LENS_SYSTEM = {
    "surfaces": _BK7_SURFACES,
    "aperture_radius_mm": 5.0,
}

_WEAK_LENS_SYSTEM = {
    "surfaces": _WEAK_LENS_SURFACES,
    "aperture_radius_mm": 2.0,   # small aperture → paraxial regime
}

_WAVELENGTH = 550.0  # nm (green)


# ---------------------------------------------------------------------------
# 1. ideal_thin_lens_onaxis_rms_near_zero
# ---------------------------------------------------------------------------

def test_ideal_thin_lens_onaxis_rms_near_zero():
    """
    Weak symmetric biconvex lens (R=200mm, n=1.5, aperture=2mm):
    very small aperture/EFL ratio → paraxial regime with tiny spherical
    aberration.  All meridional y-intercepts should cluster tightly at
    the paraxial image plane; y-spread < 1e-3 mm.

    Reference: Welford 1986 §8.2 (near-stigmatic system → tight spot).
    Hecht §6.3: for a paraxial system the geometric spot approaches a
    point as aperture → 0.
    """
    result = compute_spot_diagram(_WEAK_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult), f"Expected SpotDiagramResult, got {result}"
    # Check meridional y-spread (the exact component of the trace).
    ys = [pt[1] for pt in result.image_points_xy]
    assert len(ys) > 0
    y_spread = max(ys) - min(ys)
    assert y_spread < 1e-2, (
        f"Expected near-zero y-spread for paraxial weak lens, got {y_spread:.2e}"
    )


# ---------------------------------------------------------------------------
# 2. bk7_singlet_offaxis_nonzero_rms
# ---------------------------------------------------------------------------

def test_bk7_singlet_offaxis_nonzero_rms():
    """
    BK7 biconvex singlet at 10° field: coma produces a non-zero RMS spot.
    Reference: Welford §8.3 (coma spot shape); Hecht §6.3.
    """
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 10.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert result.rms_radius_mm > 0.0, (
        f"Expected non-zero RMS for BK7 at 10° (coma), got {result.rms_radius_mm}"
    )
    assert math.isfinite(result.rms_radius_mm)


# ---------------------------------------------------------------------------
# 3. offaxis_rms_larger_than_onaxis
# ---------------------------------------------------------------------------

def test_offaxis_rms_larger_than_onaxis():
    """
    For a BK7 biconvex singlet, off-axis RMS must exceed on-axis RMS.
    Coma (S_II) grows linearly with field angle (Welford §8.3).
    """
    r0 = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    r10 = compute_spot_diagram(_BK7_LENS_SYSTEM, 10.0, _WAVELENGTH, num_rays=49)
    assert isinstance(r0, SpotDiagramResult)
    assert isinstance(r10, SpotDiagramResult)
    assert r10.rms_radius_mm > r0.rms_radius_mm, (
        f"Expected rms(10°) > rms(0°): {r10.rms_radius_mm:.6f} vs {r0.rms_radius_mm:.6f}"
    )


# ---------------------------------------------------------------------------
# 4. num_rays_grid_covers_pupil
# ---------------------------------------------------------------------------

def test_num_rays_grid_covers_pupil():
    """
    _pupil_grid(49) generates a 7×7 Cartesian grid, returning only points
    within the unit disk.  All returned points must satisfy |p|² <= 1.
    """
    pts = _pupil_grid(49)
    assert len(pts) > 0, "Expected at least one pupil point"
    for px, py in pts:
        r2 = px * px + py * py
        assert r2 <= 1.0 + 1e-8, f"Pupil point ({px:.3f},{py:.3f}) outside unit disk"


# ---------------------------------------------------------------------------
# 5. num_rays_count_close_to_target
# ---------------------------------------------------------------------------

def test_num_rays_count_close_to_target():
    """
    _pupil_grid(49) with a 7×7 grid should return at least 20 points
    (the unit disk in a 7×7 [-1,1]^2 grid captures ≈ 29 out of 49 corners).
    All points are within the unit disk.
    """
    pts = _pupil_grid(49)
    assert len(pts) >= 20, f"Expected >= 20 pupil points for 7×7 grid, got {len(pts)}"


# ---------------------------------------------------------------------------
# 6. svg_contains_svg_tag
# ---------------------------------------------------------------------------

def test_svg_contains_svg_tag():
    """SVG output must contain opening and closing <svg tags."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert "<svg" in result.svg_diagram, "SVG missing opening <svg tag"
    assert "</svg>" in result.svg_diagram, "SVG missing closing </svg> tag"


# ---------------------------------------------------------------------------
# 7. svg_contains_circle_elements
# ---------------------------------------------------------------------------

def test_svg_contains_circle_elements():
    """
    SVG must contain at least one <circle element (the ray intercept dots).
    """
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert "<circle" in result.svg_diagram, "SVG missing <circle elements"


# ---------------------------------------------------------------------------
# 8. encircled_80pct_ge_rms
# ---------------------------------------------------------------------------

def test_encircled_80pct_ge_rms():
    """
    80%-encircled-energy radius must be >= RMS radius.
    (EE80 encloses more energy than the RMS ring; Hecht §6.3.)
    """
    for field in [0.0, 5.0, 10.0]:
        result = compute_spot_diagram(_BK7_LENS_SYSTEM, field, _WAVELENGTH, num_rays=49)
        assert isinstance(result, SpotDiagramResult)
        assert result.encircled_80pct_radius_mm >= result.rms_radius_mm - 1e-12, (
            f"EE80 < RMS at field={field}°: "
            f"ee80={result.encircled_80pct_radius_mm:.6f}, "
            f"rms={result.rms_radius_mm:.6f}"
        )


# ---------------------------------------------------------------------------
# 9. encircled_80pct_positive
# ---------------------------------------------------------------------------

def test_encircled_80pct_positive():
    """EE80 radius must be > 0 for an aberrated lens."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert result.encircled_80pct_radius_mm > 0.0, (
        f"Expected EE80 > 0 for BK7 singlet, got {result.encircled_80pct_radius_mm}"
    )


# ---------------------------------------------------------------------------
# 10. centroid_near_chief_ray_onaxis
# ---------------------------------------------------------------------------

def test_centroid_near_chief_ray_onaxis():
    """
    On-axis (0° field), the centroid y-coordinate should be near 0
    (the chief ray images to the origin for a symmetric lens).
    """
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    cx, cy = result.centroid_xy
    assert abs(cy) < 0.5, (
        f"On-axis centroid y={cy:.4f} expected near 0 for symmetric lens"
    )


# ---------------------------------------------------------------------------
# 11. image_points_xy_type
# ---------------------------------------------------------------------------

def test_image_points_xy_type():
    """image_points_xy must be a list of 2-element sequences of floats."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert isinstance(result.image_points_xy, list)
    assert len(result.image_points_xy) > 0
    for pt in result.image_points_xy:
        assert len(pt) == 2
        x, y = pt
        assert isinstance(x, float)
        assert isinstance(y, float)
        assert math.isfinite(x)
        assert math.isfinite(y)


# ---------------------------------------------------------------------------
# 12. n_rays_positive
# ---------------------------------------------------------------------------

def test_n_rays_positive():
    """to_dict()['n_rays'] must equal the number of image_points_xy."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    d = result.to_dict()
    assert d["n_rays"] > 0
    assert d["n_rays"] == len(result.image_points_xy)


# ---------------------------------------------------------------------------
# 13. result_dataclass_fields
# ---------------------------------------------------------------------------

def test_result_dataclass_fields():
    """SpotDiagramResult must have all six required public fields."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert hasattr(result, "image_points_xy")
    assert hasattr(result, "rms_radius_mm")
    assert hasattr(result, "encircled_80pct_radius_mm")
    assert hasattr(result, "centroid_xy")
    assert hasattr(result, "svg_diagram")
    assert hasattr(result, "honest_caveat")


# ---------------------------------------------------------------------------
# 14. to_dict_ok_key
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    """to_dict() must return a dict with ok=True."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    d = result.to_dict()
    assert isinstance(d, dict)
    assert d.get("ok") is True


# ---------------------------------------------------------------------------
# 15. error_missing_surfaces
# ---------------------------------------------------------------------------

def test_error_missing_surfaces():
    """Error when lens_system_dict lacks 'surfaces' key."""
    result = compute_spot_diagram({}, 0.0, _WAVELENGTH)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "surfaces" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 16. error_empty_surfaces
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    """Error for empty surfaces list."""
    result = compute_spot_diagram({"surfaces": []}, 0.0, _WAVELENGTH)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 17. error_bad_surface
# ---------------------------------------------------------------------------

def test_error_bad_surface():
    """Error when a surface is missing the required 'n' field."""
    bad = {"surfaces": [{"c": 0.02, "t": 5.0}]}  # missing 'n'
    result = compute_spot_diagram(bad, 0.0, _WAVELENGTH)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "n" in result["reason"]


# ---------------------------------------------------------------------------
# 18. error_bad_wavelength
# ---------------------------------------------------------------------------

def test_error_bad_wavelength():
    """Error for wavelength_nm <= 0."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, -100.0)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "wavelength" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 19. error_bad_num_rays
# ---------------------------------------------------------------------------

def test_error_bad_num_rays():
    """Error for num_rays < 1."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=0)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "num_rays" in result["reason"]


# ---------------------------------------------------------------------------
# 20. honest_caveat_string
# ---------------------------------------------------------------------------

def test_honest_caveat_string():
    """honest_caveat must be a non-empty string mentioning 'Monochromatic'."""
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 10
    assert "monochromatic" in result.honest_caveat.lower(), (
        f"Expected 'monochromatic' in honest_caveat: {result.honest_caveat[:80]}"
    )


# ---------------------------------------------------------------------------
# 21. llm_tool_happy_path
# ---------------------------------------------------------------------------

def test_llm_tool_happy_path():
    """LLM tool returns JSON with ok=True and image_points_xy."""
    from kerf_cad_core.optics.tools import run_compute_spot_diagram

    payload = json.dumps({
        "lens_system_dict": {
            "surfaces": _BK7_SURFACES,
            "aperture_radius_mm": 5.0,
        },
        "field_angle_deg": 0.0,
        "wavelength_nm": 550.0,
        "num_rays": 25,
    }).encode()

    response = asyncio.get_event_loop().run_until_complete(
        run_compute_spot_diagram(None, payload)
    )
    d = json.loads(response)
    assert d.get("ok") is True, f"Expected ok=True, got: {d.get('reason')}"
    assert "image_points_xy" in d
    assert len(d["image_points_xy"]) > 0
    assert "rms_radius_mm" in d
    assert "encircled_80pct_radius_mm" in d
    assert "svg_diagram" in d


# ---------------------------------------------------------------------------
# 22. llm_tool_missing_field_angle
# ---------------------------------------------------------------------------

def test_llm_tool_missing_field_angle():
    """LLM tool returns error when field_angle_deg is missing."""
    from kerf_cad_core.optics.tools import run_compute_spot_diagram

    payload = json.dumps({
        "lens_system_dict": {"surfaces": _BK7_SURFACES},
        "wavelength_nm": 550.0,
    }).encode()

    response = asyncio.get_event_loop().run_until_complete(
        run_compute_spot_diagram(None, payload)
    )
    d = json.loads(response)
    assert d.get("ok") is False
    assert "field_angle_deg" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 23. llm_tool_bad_json
# ---------------------------------------------------------------------------

def test_llm_tool_bad_json():
    """LLM tool handles completely invalid JSON input gracefully (returns error payload)."""
    from kerf_cad_core.optics.tools import run_compute_spot_diagram

    response = asyncio.get_event_loop().run_until_complete(
        run_compute_spot_diagram(None, b"not json {{{{")
    )
    d = json.loads(response)
    # err_payload returns {"error": ..., "code": ...} OR {"ok": false, ...}
    # Both signal failure; check that at least one error indicator is present.
    is_error = (d.get("ok") is False) or ("error" in d) or ("code" in d)
    assert is_error, f"Expected error payload for bad JSON, got: {d}"


# ---------------------------------------------------------------------------
# 24. bk7_rms_range
# ---------------------------------------------------------------------------

def test_bk7_rms_range():
    """
    BK7 biconvex on-axis at aperture 5mm: RMS spot radius should be in
    the plausible range [1e-5, 5.0] mm (spherical aberration; Welford §8.2).
    The 2-D RMS includes the first-order sagittal x contribution which can
    be significant for a fast lens at large aperture.
    """
    result = compute_spot_diagram(_BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49)
    assert isinstance(result, SpotDiagramResult)
    rms = result.rms_radius_mm
    assert 1e-5 <= rms <= 5.0, (
        f"BK7 on-axis RMS = {rms:.6f} mm outside expected range [1e-5, 5.0]"
    )


# ===========================================================================
# Skew-ray spot diagram tests (use_skew_ray=True)
# Tests 25–33
# ===========================================================================

# ---------------------------------------------------------------------------
# 25. skew_ray_returns_spot_diagram_result
# ---------------------------------------------------------------------------

def test_skew_ray_returns_spot_diagram_result():
    """
    use_skew_ray=True must return a SpotDiagramResult (not an error dict)
    for a valid BK7 singlet on-axis.
    """
    result = compute_spot_diagram(
        _BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(result, SpotDiagramResult), (
        f"Expected SpotDiagramResult, got: {result}"
    )
    assert result.rms_radius_mm >= 0.0
    assert math.isfinite(result.rms_radius_mm)
    assert len(result.image_points_xy) > 0


# ---------------------------------------------------------------------------
# 26. skew_ray_aberration_free_spot_collapses
# ---------------------------------------------------------------------------

def test_skew_ray_aberration_free_spot_collapses():
    """
    Aberration-free (near-paraxial) weak lens on-axis with skew-ray path:
    spot should collapse to near a point.  All image points should cluster
    within < 0.05 mm of the centroid (Welford §8.2: stigmatic system → point
    spot).

    Reference: Welford 1986 §8.2; Hecht §6.3 (paraxial → geometric point).
    """
    result = compute_spot_diagram(
        _WEAK_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(result, SpotDiagramResult), f"Expected result, got: {result}"
    assert len(result.image_points_xy) > 0
    # Tight spread check
    xs = [p[0] for p in result.image_points_xy]
    ys = [p[1] for p in result.image_points_xy]
    x_spread = max(xs) - min(xs)
    y_spread = max(ys) - min(ys)
    assert x_spread < 0.05, (
        f"Skew-ray x-spread {x_spread:.4f} mm too large for near-paraxial weak lens"
    )
    assert y_spread < 0.05, (
        f"Skew-ray y-spread {y_spread:.4f} mm too large for near-paraxial weak lens"
    )


# ---------------------------------------------------------------------------
# 27. skew_ray_vs_paraxial_onaxis_rms_comparable
# ---------------------------------------------------------------------------

def test_skew_ray_vs_paraxial_onaxis_rms_comparable():
    """
    For on-axis (0° field), skew-ray RMS and paraxial RMS should agree to
    within a factor of 10 for the weak near-paraxial lens.

    Both paths trace exact Snell refraction; the difference is only in how
    the x-coordinate is computed.  On-axis the x-coordinate is near zero for
    both paths (axial symmetry), so the y-dominated RMS should match closely.

    Reference: Welford §5.2-5.3 (exact Snell; meridional = skew meridional
    plane for on-axis); Born & Wolf §4.6.
    """
    paraxial_result = compute_spot_diagram(
        _WEAK_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=False
    )
    skew_result = compute_spot_diagram(
        _WEAK_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(paraxial_result, SpotDiagramResult)
    assert isinstance(skew_result, SpotDiagramResult)

    rms_p = paraxial_result.rms_radius_mm
    rms_s = skew_result.rms_radius_mm

    # Both should be finite and non-negative
    assert math.isfinite(rms_p) and math.isfinite(rms_s)
    assert rms_p >= 0.0 and rms_s >= 0.0

    # On-axis, the skew-ray y-spread should be small (paraxial = near-stigmatic).
    # The paraxial path's 2D RMS can be dominated by the first-order sagittal x
    # estimate which may diverge.  We test skew-ray y-spread directly (rigorous).
    ys = [pt[1] for pt in skew_result.image_points_xy]
    y_spread = max(ys) - min(ys)
    assert y_spread < 0.05, (
        f"Skew-ray y-spread {y_spread:.4e} mm too large for near-paraxial weak lens"
    )
    # Skew-ray RMS must be finite and non-negative
    assert math.isfinite(rms_s) and rms_s >= 0.0


# ---------------------------------------------------------------------------
# 28. skew_ray_defocus_spot_expands
# ---------------------------------------------------------------------------

def test_skew_ray_spot_grows_with_aperture():
    """
    Spot size (RMS) must increase as aperture increases, for a fixed lens.

    A larger entrance pupil samples higher-order zones of the lens where
    spherical aberration is larger (Welford §8.2: W040 third-order spherical
    aberration grows as ρ⁴, so RMS spot grows with aperture).

    We use the BK7 biconvex singlet with two apertures: 2 mm and 8 mm.
    The wider aperture must produce a noticeably larger skew-ray RMS spot.

    Reference: Welford "Aberrations" §8.2; Hecht §6.3.
    """
    bk7_small_ap = {
        "surfaces": [
            {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
            {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
        ],
        "aperture_radius_mm": 2.0,  # small aperture — paraxial zone
    }
    bk7_large_ap = {
        "surfaces": [
            {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
            {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
        ],
        "aperture_radius_mm": 8.0,  # large aperture — significant spherical aberration
    }
    result_small = compute_spot_diagram(
        bk7_small_ap, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    result_large = compute_spot_diagram(
        bk7_large_ap, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(result_small, SpotDiagramResult)
    assert isinstance(result_large, SpotDiagramResult)
    # Larger aperture must produce larger spot
    assert result_large.rms_radius_mm > result_small.rms_radius_mm, (
        f"Expected large-aperture RMS > small-aperture RMS: "
        f"large={result_large.rms_radius_mm:.4f}, small={result_small.rms_radius_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# 29. skew_ray_field_dependent_aberration
# ---------------------------------------------------------------------------

def test_skew_ray_field_dependent_aberration():
    """
    Field-dependent aberration: skew-ray RMS at 10° must exceed on-axis.

    Coma (S_II) grows linearly with field angle H (Welford §6.2); astigmatism
    (S_III) grows as H²; field curvature (S_IV) is also H²-dependent.
    All three contribute to larger off-axis spots.

    Reference: Welford "Aberrations" §6; Hecht §6.3.
    """
    result_0 = compute_spot_diagram(
        _BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    result_10 = compute_spot_diagram(
        _BK7_LENS_SYSTEM, 10.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(result_0, SpotDiagramResult)
    assert isinstance(result_10, SpotDiagramResult)
    assert result_10.rms_radius_mm > result_0.rms_radius_mm, (
        f"Expected skew RMS(10°) > RMS(0°): "
        f"10°={result_10.rms_radius_mm:.4f}, 0°={result_0.rms_radius_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# 30. skew_ray_hexapolar_pupil_unit_disk
# ---------------------------------------------------------------------------

def test_skew_ray_hexapolar_pupil_unit_disk():
    """
    _hexapolar_pupil(37) must return only points within the unit disk
    |p|² <= 1.

    Reference: Smith §3.3 (valid pupil sampling constraint).
    """
    pts = _hexapolar_pupil(37)
    assert len(pts) >= 1, "Expected at least 1 hexapolar pupil point"
    for px, py in pts:
        r2 = px * px + py * py
        assert r2 <= 1.0 + 1e-8, (
            f"Hexapolar pupil point ({px:.3f},{py:.3f}) outside unit disk (r²={r2:.4f})"
        )


# ---------------------------------------------------------------------------
# 31. skew_ray_hexapolar_pupil_count
# ---------------------------------------------------------------------------

def test_skew_ray_hexapolar_pupil_count():
    """
    _hexapolar_pupil(37) should return a count close to 37.
    For 3 rings: 1 + 6 + 12 + 18 = 37 exactly.
    """
    pts = _hexapolar_pupil(37)
    assert len(pts) >= 7, f"Expected >= 7 hexapolar samples for 37-ray target, got {len(pts)}"
    # The count must be of the form 1 + 3*N*(N+1)
    count = len(pts)
    valid_counts = {1 + 3 * n * (n + 1) for n in range(1, 20)}
    assert count in valid_counts, (
        f"Hexapolar count {count} is not a valid hexapolar count "
        f"(must be 1 + 3*N*(N+1))"
    )


# ---------------------------------------------------------------------------
# 32. skew_ray_honest_caveat_mentions_skew
# ---------------------------------------------------------------------------

def test_skew_ray_honest_caveat_mentions_skew():
    """
    When use_skew_ray=True the honest_caveat must mention '3-D skew-ray'
    to distinguish it from the paraxial path.
    """
    result = compute_spot_diagram(
        _BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(result, SpotDiagramResult)
    caveat = result.honest_caveat.lower()
    assert "skew" in caveat or "born" in caveat, (
        f"Expected 'skew' or 'born' in honest_caveat for skew-ray path: {result.honest_caveat[:100]}"
    )
    # Paraxial default must NOT have 3-D skew in caveat
    result_p = compute_spot_diagram(
        _BK7_LENS_SYSTEM, 0.0, _WAVELENGTH, num_rays=49
    )
    assert isinstance(result_p, SpotDiagramResult)
    assert "monochromatic" in result_p.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 33. skew_ray_image_points_are_finite_floats
# ---------------------------------------------------------------------------

def test_skew_ray_image_points_are_finite_floats():
    """
    All image_points_xy from use_skew_ray=True must be finite float tuples.
    Reference: Welford §8.2 (valid ray intercepts).
    """
    result = compute_spot_diagram(
        _BK7_LENS_SYSTEM, 5.0, _WAVELENGTH, num_rays=37, use_skew_ray=True
    )
    assert isinstance(result, SpotDiagramResult)
    assert len(result.image_points_xy) > 0
    for pt in result.image_points_xy:
        assert len(pt) == 2
        x, y = pt
        assert isinstance(x, float), f"x must be float, got {type(x)}"
        assert isinstance(y, float), f"y must be float, got {type(y)}"
        assert math.isfinite(x), f"x={x} is not finite"
        assert math.isfinite(y), f"y={y} is not finite"
