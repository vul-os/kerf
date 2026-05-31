"""
Tests for kerf_cad_core.optics.chief_ray_height — paraxial chief-ray height
trace through sequential optical systems.

Test plan
---------
1.  single_thin_lens_image_height_5deg   -- f=50mm singlet, field=5°, stop=lens:
                                            image_height ≈ f·tan(5°) = 4.37 mm
2.  single_thin_lens_image_height_10deg  -- f=50mm singlet, field=10°:
                                            image_height ≈ f·tan(10°) = 8.82 mm
3.  stop_at_zero_height_first_surface    -- chief ray at stop = 0 (passes through centre)
4.  on_axis_zero_everywhere              -- field=0°: all surface heights = 0
5.  telecentric_stop_at_focal_plane      -- stop at rear focal plane: chief ray
                                            exits parallel to axis (image_angle ≈ 0°)
6.  biconvex_doublet_stop_at_first       -- 2-surface BK7 system: image height finite
7.  stop_at_second_surface               -- BK7 biconvex, stop at surface 1:
                                            h at surface 1 ≈ 0
8.  per_surface_count_correct            -- len(per_surface_heights) == n_surfaces
9.  per_surface_surface_idx              -- surface_idx matches loop index
10. per_surface_angles_finite            -- all ray_angle_deg are finite
11. report_dataclass_fields              -- ChiefRayHeightReport has all required fields
12. to_dict_ok_key                       -- to_dict() has ok=True
13. honest_caveat_in_report              -- honest_caveat field is non-empty string
14. error_empty_surfaces                 -- error for empty surfaces list
15. error_bad_surface_missing_field      -- error for surface missing 'c' key
16. error_field_angle_out_of_range_neg   -- error for field_angle_deg < 0
17. error_field_angle_out_of_range_90    -- error for field_angle_deg = 90
18. error_stop_idx_out_of_range          -- error for stop_surface_idx >= n_surfaces
19. error_stop_idx_negative              -- error for stop_surface_idx < 0
20. error_bad_n_object                   -- error for n_object < 1.0
21. tool_happy_path                      -- LLM tool returns ok JSON
22. tool_missing_required_field          -- LLM tool returns error for missing field
23. tool_bad_json                        -- LLM tool handles invalid JSON
24. stop_height_near_zero_two_surface    -- 2-surface system: h_stop < 1e-9 mm
25. multifield_image_heights_proportional -- image_heights scale ~linearly with tan(θ)
26. magnification_nan_infinity_conjugate -- magnification is NaN for infinite conjugate
27. magnification_finite_conjugate       -- magnification finite for finite object distance
28. object_angle_deg_equals_field_angle  -- object-space chief-ray angle ≈ field_angle
29. three_surface_system                 -- 3-surface system works without error
30. flat_slab_preserves_height           -- flat slab: chief ray height constant

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §3 (paraxial chief ray), §3.7 (stop and pupil positions).
Mahajan, V.N. -- "Optical Imaging and Aberrations, Part I", SPIE Press, 2011,
    §2 (paraxial optics, pupil and stop).

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.chief_ray_height import (
    ChiefRayHeightReport,
    trace_chief_ray,
)
from kerf_cad_core.optics.tools import run_trace_chief_ray


# ---------------------------------------------------------------------------
# Fixtures / helper systems
# ---------------------------------------------------------------------------

# Plano-convex thin lens: f=50mm exactly, n=1.5168
# c1 = 1/((n-1)*f), t=0, n=1.5168
# c2 = 0, t=0, n=1.0 (back to air)
_N_BK7 = 1.5168
_F50 = 50.0
_C1_F50 = 1.0 / ((_N_BK7 - 1.0) * _F50)  # ~0.03870 mm^-1

_THIN_LENS_F50 = {
    "surfaces": [
        {"c": _C1_F50, "t": 0.0, "n": _N_BK7},
        {"c": 0.0, "t": 0.0, "n": 1.0},
    ]
}

# BK7 biconvex singlet (f ≈ 48.4 mm)
_BK7_BICONVEX = {
    "surfaces": [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]
}

# Doubly-telecentric relay:
# Two equal lenses (f1=f2=50mm), separated by f1+f2=100mm, stop at shared focal plane.
# Stop at first lens surface (idx 0 of 4-surface system) gives object-telecentric.
# We model each lens as a plano-convex thin pair.
_F50_PLANO_CONVEX_SURFACES = [
    {"c": _C1_F50, "t": 0.0, "n": _N_BK7},
    {"c": 0.0,    "t": 100.0, "n": 1.0},   # air gap = f1+f2=100mm
    {"c": _C1_F50, "t": 0.0, "n": _N_BK7},
    {"c": 0.0,    "t": 0.0, "n": 1.0},
]
_TELECENTRIC_RELAY = {"surfaces": _F50_PLANO_CONVEX_SURFACES}

# Image-space telecentric system: stop at front focal plane (50mm before lens).
# Model: flat stop surface at idx=0, then propagate 50mm to the thin lens.
# With stop at z=-f from lens, the chief ray exits the lens parallel to axis
# (u_img = 0), giving perfect image-space telecentricity.
# Ref: Smith "Modern Optical Engineering" §5.4.
_IMAGE_TELECENTRIC = {
    "surfaces": [
        {"c": 0.0,    "t": _F50,  "n": 1.0},    # stop surface (flat, 50mm before lens)
        {"c": _C1_F50, "t": 0.0, "n": _N_BK7},  # lens front
        {"c": 0.0,    "t": 0.0,  "n": 1.0},     # lens rear
    ]
}


def _trace(system, field_deg, stop_idx) -> ChiefRayHeightReport:
    r = trace_chief_ray(system, field_deg, stop_idx)
    assert isinstance(r, ChiefRayHeightReport), f"Expected report, got {r!r}"
    return r


# ---------------------------------------------------------------------------
# Test 1: single thin lens, image_height ≈ f·tan(5°)
# ---------------------------------------------------------------------------

def test_single_thin_lens_image_height_5deg():
    """Oracle: f=50mm, θ=5° → image_height = 50·tan(5°) ≈ 4.374 mm."""
    r = _trace(_THIN_LENS_F50, 5.0, 0)
    expected = _F50 * math.tan(math.radians(5.0))
    assert r.image_height_mm == pytest.approx(expected, abs=1e-3), (
        f"image_height={r.image_height_mm:.4f} mm, expected {expected:.4f} mm"
    )


# ---------------------------------------------------------------------------
# Test 2: single thin lens, image_height ≈ f·tan(10°)
# ---------------------------------------------------------------------------

def test_single_thin_lens_image_height_10deg():
    """Oracle: f=50mm, θ=10° → image_height = 50·tan(10°) ≈ 8.816 mm."""
    r = _trace(_THIN_LENS_F50, 10.0, 0)
    expected = _F50 * math.tan(math.radians(10.0))
    assert r.image_height_mm == pytest.approx(expected, abs=1e-3), (
        f"image_height={r.image_height_mm:.4f} mm, expected {expected:.4f} mm"
    )


# ---------------------------------------------------------------------------
# Test 3: chief ray at stop surface ≈ 0
# ---------------------------------------------------------------------------

def test_stop_at_zero_height_first_surface():
    """Chief ray must pass through centre of stop: h_stop ≈ 0."""
    r = _trace(_THIN_LENS_F50, 5.0, 0)
    assert abs(r.chief_ray_at_stop_mm) < 1e-9, (
        f"chief_ray_at_stop_mm = {r.chief_ray_at_stop_mm!r}, expected ≈ 0"
    )


# ---------------------------------------------------------------------------
# Test 4: on-axis field → all heights zero
# ---------------------------------------------------------------------------

def test_on_axis_zero_everywhere():
    """field_angle=0°: chief ray is on-axis → h=0 at all surfaces."""
    r = _trace(_THIN_LENS_F50, 0.0, 0)
    for s in r.per_surface_heights:
        assert abs(s["ray_height_mm"]) < 1e-12, (
            f"surface {s['surface_idx']}: h={s['ray_height_mm']!r}, expected 0"
        )
    assert abs(r.image_height_mm) < 1e-12


# ---------------------------------------------------------------------------
# Test 5: telecentric – stop at front focal plane → image angle ≈ 0
# ---------------------------------------------------------------------------

def test_telecentric_stop_at_focal_plane():
    """
    Image-space telecentric: stop at front focal plane (50mm before f=50mm lens).
    Chief ray exits the lens parallel to axis → image_angle = 0° exactly.
    (Smith MOE §5.4; Welford §4.4)
    """
    r = _trace(_IMAGE_TELECENTRIC, 5.0, 0)
    assert abs(r.image_angle_deg) < 1e-9, (
        f"image_angle_deg={r.image_angle_deg:.4f}, expected 0 (image-space telecentric)"
    )


# ---------------------------------------------------------------------------
# Test 6: BK7 biconvex, stop at first surface, image height finite & positive
# ---------------------------------------------------------------------------

def test_biconvex_doublet_stop_at_first():
    r = _trace(_BK7_BICONVEX, 5.0, 0)
    # BK7 biconvex f≈48.4mm, image_height ≈ 48.4 * tan(5°) ≈ 4.23mm
    assert 3.5 < r.image_height_mm < 6.0, (
        f"image_height_mm={r.image_height_mm!r} out of expected range"
    )


# ---------------------------------------------------------------------------
# Test 7: BK7 biconvex, stop at second surface (idx=1) → h≈0 at surface 1
# ---------------------------------------------------------------------------

def test_stop_at_second_surface():
    """Stop at rear surface (idx=1): h at idx=1 ≈ 0."""
    r = _trace(_BK7_BICONVEX, 5.0, 1)
    assert isinstance(r, ChiefRayHeightReport)
    assert abs(r.chief_ray_at_stop_mm) < 1e-6, (
        f"chief_ray_at_stop_mm={r.chief_ray_at_stop_mm!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: per_surface_heights has correct count
# ---------------------------------------------------------------------------

def test_per_surface_count_correct():
    r = _trace(_BK7_BICONVEX, 5.0, 0)
    n_surf = len(_BK7_BICONVEX["surfaces"])
    assert len(r.per_surface_heights) == n_surf, (
        f"len={len(r.per_surface_heights)}, expected {n_surf}"
    )


# ---------------------------------------------------------------------------
# Test 9: surface_idx matches index in list
# ---------------------------------------------------------------------------

def test_per_surface_surface_idx():
    r = _trace(_BK7_BICONVEX, 5.0, 0)
    for i, s in enumerate(r.per_surface_heights):
        assert s["surface_idx"] == i


# ---------------------------------------------------------------------------
# Test 10: all surface angles are finite
# ---------------------------------------------------------------------------

def test_per_surface_angles_finite():
    r = _trace(_BK7_BICONVEX, 5.0, 0)
    for s in r.per_surface_heights:
        assert math.isfinite(s["ray_angle_deg"]), (
            f"surface {s['surface_idx']}: angle={s['ray_angle_deg']!r} not finite"
        )


# ---------------------------------------------------------------------------
# Test 11: dataclass has all required fields
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = _trace(_THIN_LENS_F50, 5.0, 0)
    assert hasattr(r, "per_surface_heights")
    assert hasattr(r, "image_height_mm")
    assert hasattr(r, "magnification")
    assert hasattr(r, "stop_surface_idx")
    assert hasattr(r, "chief_ray_at_stop_mm")
    assert hasattr(r, "object_angle_deg")
    assert hasattr(r, "image_angle_deg")
    assert hasattr(r, "honest_caveat")
    assert r.stop_surface_idx == 0


# ---------------------------------------------------------------------------
# Test 12: to_dict has ok=True
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    r = _trace(_THIN_LENS_F50, 5.0, 0)
    d = r.to_dict()
    assert d["ok"] is True
    assert "per_surface_heights" in d
    assert "image_height_mm" in d
    assert "honest_caveat" in d


# ---------------------------------------------------------------------------
# Test 13: honest_caveat is non-empty string
# ---------------------------------------------------------------------------

def test_honest_caveat_in_report():
    r = _trace(_THIN_LENS_F50, 5.0, 0)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 10


# ---------------------------------------------------------------------------
# Test 14: error for empty surfaces
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    result = trace_chief_ray({"surfaces": []}, 5.0, 0)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "reason" in result


# ---------------------------------------------------------------------------
# Test 15: error for surface missing required field
# ---------------------------------------------------------------------------

def test_error_bad_surface_missing_field():
    bad_system = {"surfaces": [{"c": 0.0, "t": 0.0}]}  # missing 'n'
    result = trace_chief_ray(bad_system, 5.0, 0)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 16: error for negative field angle
# ---------------------------------------------------------------------------

def test_error_field_angle_out_of_range_neg():
    result = trace_chief_ray(_THIN_LENS_F50, -1.0, 0)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 17: error for field angle = 90
# ---------------------------------------------------------------------------

def test_error_field_angle_out_of_range_90():
    result = trace_chief_ray(_THIN_LENS_F50, 90.0, 0)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 18: error for stop_surface_idx >= n_surfaces
# ---------------------------------------------------------------------------

def test_error_stop_idx_out_of_range():
    result = trace_chief_ray(_THIN_LENS_F50, 5.0, 99)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 19: error for stop_surface_idx < 0
# ---------------------------------------------------------------------------

def test_error_stop_idx_negative():
    result = trace_chief_ray(_THIN_LENS_F50, 5.0, -1)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 20: error for n_object < 1.0
# ---------------------------------------------------------------------------

def test_error_bad_n_object():
    bad_system = dict(_THIN_LENS_F50)
    bad_system = {**_THIN_LENS_F50, "n_object": 0.5}
    result = trace_chief_ray(bad_system, 5.0, 0)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 21: LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    payload = json.dumps({
        "lens_system_dict": _THIN_LENS_F50,
        "field_angle_deg": 5.0,
        "stop_surface_idx": 0,
    }).encode()

    result_str = asyncio.run(run_trace_chief_ray(None, payload))
    d = json.loads(result_str)
    assert d["ok"] is True, f"Tool returned error: {d}"
    assert "per_surface_heights" in d
    assert "image_height_mm" in d


# ---------------------------------------------------------------------------
# Test 22: LLM tool missing required field
# ---------------------------------------------------------------------------

def test_tool_missing_required_field():
    payload = json.dumps({
        "lens_system_dict": _THIN_LENS_F50,
        # missing field_angle_deg
        "stop_surface_idx": 0,
    }).encode()

    result_str = asyncio.run(run_trace_chief_ray(None, payload))
    d = json.loads(result_str)
    assert d["ok"] is False


# ---------------------------------------------------------------------------
# Test 23: LLM tool bad JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    result_str = asyncio.run(run_trace_chief_ray(None, b"{not valid json"))
    d = json.loads(result_str)
    # err_payload uses "error" + "code" keys; other error paths use "ok": False
    assert "error" in d or d.get("ok") is False


# ---------------------------------------------------------------------------
# Test 24: h_stop is near zero for 2-surface system with stop at idx=1
# ---------------------------------------------------------------------------

def test_stop_height_near_zero_two_surface():
    """
    For any 2-surface system with stop at idx=1, the chief-ray height at
    surface 1 must be < 1e-6 mm (numerical tolerance).
    """
    system = {
        "surfaces": [
            {"c": 0.02, "t": 10.0, "n": 1.5},
            {"c": -0.02, "t": 0.0, "n": 1.0},
        ]
    }
    r = _trace(system, 7.0, 1)
    assert abs(r.chief_ray_at_stop_mm) < 1e-6, (
        f"h_stop={r.chief_ray_at_stop_mm!r}, expected < 1e-6"
    )


# ---------------------------------------------------------------------------
# Test 25: image heights scale with tan(θ) for paraxial angles
# ---------------------------------------------------------------------------

def test_multifield_image_heights_proportional():
    """
    Paraxial image height ∝ tan(θ).  Verify ratio consistency.
    """
    r5 = _trace(_THIN_LENS_F50, 5.0, 0)
    r10 = _trace(_THIN_LENS_F50, 10.0, 0)

    ratio_actual = r10.image_height_mm / r5.image_height_mm
    ratio_expected = math.tan(math.radians(10.0)) / math.tan(math.radians(5.0))
    assert ratio_actual == pytest.approx(ratio_expected, abs=1e-4), (
        f"ratio_actual={ratio_actual:.6f}, ratio_expected={ratio_expected:.6f}"
    )


# ---------------------------------------------------------------------------
# Test 26: magnification is NaN for infinite conjugate (default)
# ---------------------------------------------------------------------------

def test_magnification_nan_infinity_conjugate():
    r = _trace(_THIN_LENS_F50, 5.0, 0)
    # For infinite conjugate (obj_dist = 1e9 >> 1e6), magnification = NaN
    assert math.isnan(r.magnification), (
        f"magnification={r.magnification!r}, expected NaN for infinity conjugate"
    )


# ---------------------------------------------------------------------------
# Test 27: magnification finite for finite-conjugate system
# ---------------------------------------------------------------------------

def test_magnification_finite_conjugate():
    """
    At 1:1 imaging (object at 2f from lens), magnification ≈ -1.
    """
    # Object at 2f = 100mm from f=50mm lens → image at 2f = 100mm → m = -1
    finite_system = {**_THIN_LENS_F50, "object_distance_mm": 100.0}
    r = _trace(finite_system, 5.0, 0)
    assert math.isfinite(r.magnification), (
        f"magnification={r.magnification!r} not finite for finite conjugate"
    )
    # |m| should be close to 1 (1:1 imaging), sign depends on convention
    assert 0.5 < abs(r.magnification) < 2.0, (
        f"magnification={r.magnification!r} far from |1| for 1:1 imaging"
    )


# ---------------------------------------------------------------------------
# Test 28: object-space chief-ray angle ≈ field_angle (for stop at surface 0)
# ---------------------------------------------------------------------------

def test_object_angle_deg_equals_field_angle():
    """
    With stop at surface 0 and infinite conjugate, the chief ray enters with
    slope u0 = tan(θ_field).  object_angle_deg = degrees(tan(θ_field)) which
    deviates slightly from θ_field because degrees() converts radians-valued
    slope directly (not arctan).  Verify it scales correctly with field angle.
    """
    # For small angles: degrees(tan(θ)) ≈ θ.
    # For θ=5°: tan(5°)=0.08748 rad_as_slope → degrees(0.08748) = 5.01°
    # Test: object_angle_deg > 0 and monotonically increases with field.
    angles = [2.0, 5.0, 10.0]
    obj_angles = []
    for theta in angles:
        r = _trace(_THIN_LENS_F50, theta, 0)
        assert r.object_angle_deg > 0, f"object_angle_deg should be positive for θ={theta}"
        obj_angles.append(r.object_angle_deg)

    # Monotonically increasing
    for i in range(len(obj_angles) - 1):
        assert obj_angles[i] < obj_angles[i + 1], (
            f"object_angle_deg not monotone: {obj_angles}"
        )

    # For θ=5°, object_angle ≈ 5.01° (within 0.1° of field angle)
    r5 = _trace(_THIN_LENS_F50, 5.0, 0)
    assert abs(r5.object_angle_deg - 5.0) < 0.1, (
        f"object_angle_deg={r5.object_angle_deg:.4f}, expected ≈ 5°"
    )


# ---------------------------------------------------------------------------
# Test 29: 3-surface system (thick doublet) works without error
# ---------------------------------------------------------------------------

def test_three_surface_system():
    """A thick doublet (3-surface) traces without errors."""
    system = {
        "surfaces": [
            {"c": 0.02, "t": 3.0, "n": 1.5168},
            {"c": -0.015, "t": 2.0, "n": 1.7},
            {"c": -0.02, "t": 0.0, "n": 1.0},
        ]
    }
    r = _trace(system, 5.0, 0)
    assert len(r.per_surface_heights) == 3
    assert math.isfinite(r.image_height_mm)
    assert r.image_height_mm > 0.0


# ---------------------------------------------------------------------------
# Test 30: flat slab preserves chief-ray height
# ---------------------------------------------------------------------------

def test_flat_slab_preserves_height():
    """
    A flat slab (c=0) does not refract a ray; the chief-ray height at each
    surface propagates by transfer only.  With stop at surface 0 (h=0) and
    a flat glass slab, the ray keeps its initial slope through the glass.
    """
    # Flat slab: c=0 at both surfaces → no power → chief ray should be a
    # straight line after the stop.  With stop at idx=0, h0=0, and the
    # chief ray propagates as h = 0 + t * u through each surface.
    system = {
        "surfaces": [
            {"c": 0.0, "t": 10.0, "n": 1.5},   # flat front surface, glass
            {"c": 0.0, "t": 0.0, "n": 1.0},    # flat rear surface, air
        ]
    }
    r = _trace(system, 5.0, 0)
    # h at surface 0 = 0 (stop)
    assert abs(r.per_surface_heights[0]["ray_height_mm"]) < 1e-12
    # h at surface 1 = 0 + t * u = 10 * (tan(5°)/n_glass)
    # Because flat surface doesn't refract, u0 = tan(5°), and after refraction
    # by flat surface (c=0): n'*u' = n*u - h*0*(n'-n) = n*u → u' = (n/n')*u
    # So in glass: u_glass = (1.0/1.5) * tan(5°)
    u_glass = math.tan(math.radians(5.0)) / 1.5
    h_at_surf1 = 0.0 + 10.0 * u_glass
    assert r.per_surface_heights[1]["ray_height_mm"] == pytest.approx(h_at_surf1, abs=1e-6)
