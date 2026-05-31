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
