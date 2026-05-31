"""
Tests for kerf_cad_core.optics.telecentricity_check.

Test plan
---------
 1. object_telecentric_stop_at_front_focal_plane
    Stop placed at front focal plane (rear FP of single lens) → chief ray
    parallel in object space → object_telecentric = True.

 2. stop_at_front_focal_plane_exact_angle_near_zero
    Numerical check: |chief_ray_angle_object_deg| < 0.5 for telecentric config.

 3. object_telecentric_mag_variation_small
    Object-space telecentric system → magnification variation with image-plane
    shift is near zero.

 4. non_telecentric_stop_at_first_surface
    Stop at first surface, finite conjugate → NOT object-space telecentric.

 5. non_telecentric_angle_nonzero
    Chief-ray angle in object space > 0.5 deg for non-telecentric system.

 6. non_telecentric_mag_variation_significant
    Non-telecentric system shows measurable magnification variation (> 0%).

 7. image_telecentric_doubly_telecentric
    Two-lens relay with stop at shared focal plane → image-space telecentric.

 8. image_telecentric_angle_near_zero
    Numerical: |chief_ray_angle_image_deg| < 0.5 for doubly-telecentric.

 9. doubly_telecentric_symmetric_system
    Symmetric two-lens relay → both_telecentric = True.

10. report_dataclass_fields
    TelecentricityReport has all required fields.

11. to_dict_ok_key
    to_dict() returns {"ok": True, ...} with all expected keys.

12. honest_caveat_present
    honest_caveat field is a non-empty string.

13. object_telecentric_not_image_telecentric_single_lens
    Single lens with stop at rear focal plane → object_telecentric=True,
    image_telecentric=False (single-lens cannot be doubly telecentric).

14. error_missing_surfaces
    Returns error dict for lens_system_dict without 'surfaces'.

15. error_empty_surfaces
    Returns error dict for empty surfaces list.

16. error_bad_surface
    Returns error dict for surface missing required field.

17. error_bad_field_height
    Returns error dict for field_height_mm <= 0.

18. error_bad_focus_shift
    Returns error dict for focus_shift_mm <= 0.

19. error_stop_out_of_range
    Returns error dict for stop_surface_index >= len(surfaces).

20. tool_happy_path
    LLM tool optics_compute_telecentricity returns ok JSON.

21. tool_missing_lens_system
    LLM tool returns error for missing lens_system_dict.

22. tool_bad_json
    LLM tool handles invalid JSON input gracefully.

23. tool_with_field_height_kwarg
    LLM tool accepts optional field_height_mm kwarg.

24. tool_with_focus_shift_kwarg
    LLM tool accepts optional focus_shift_mm kwarg.

25. field_height_invariance
    Chief-ray angle scales linearly with field height (paraxial linearity).
    For non-telecentric system: angle(2H) = 2 * angle(H).

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §3.
Smith, W.J. -- "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008, §5.4.
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.6.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.telecentricity_check import (
    TelecentricityReport,
    compute_telecentricity,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# BK7 biconvex singlet, f ≈ 48.4 mm (Hecht §6.4 oracle)
_BK7_SURFACES = [
    {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168, "k": 0.0},
    {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0, "k": 0.0},
]


def _report(
    surfaces: list[dict],
    stop_idx: int = 0,
    obj_dist: float | None = None,
    field: float = 10.0,
    fshift: float = 0.5,
) -> TelecentricityReport:
    """Helper to compute telecentricity and assert it's a valid report."""
    lens: dict = {"surfaces": surfaces, "stop_surface_index": stop_idx}
    if obj_dist is not None:
        lens["object_distance_mm"] = obj_dist
    r = compute_telecentricity(lens, field_height_mm=field, focus_shift_mm=fshift)
    assert isinstance(r, TelecentricityReport), f"Expected TelecentricityReport, got {r!r}"
    return r


def _two_lens_relay(f: float) -> list[dict]:
    """Build a doubly-telecentric two-lens relay surface list."""
    return [
        {"c": 1.0 / f, "t": f, "n": 1.0},    # Lens 1
        {"c": 0.0, "t": f, "n": 1.0},          # Stop plane at z=f
        {"c": 1.0 / f, "t": 0.0, "n": 1.0},   # Lens 2 at z=2f
    ]


# ---------------------------------------------------------------------------
# Test 1: Object-space telecentric — stop at rear focal plane of single lens
# ---------------------------------------------------------------------------

def test_object_telecentric_stop_at_front_focal_plane():
    """
    Single lens with stop placed at the rear focal plane (z=f behind lens):
    The entrance pupil is at infinity → chief rays in object space are
    horizontal → object_telecentric = True (Smith MOE §5.4).
    """
    f = 100.0
    surfaces = [
        {"c": 1.0 / f, "t": f, "n": 1.0},   # Lens power at z=0, gap=f
        {"c": 0.0, "t": 0.0, "n": 1.0},       # Stop plane at z=f
    ]
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 1,
        "object_distance_mm": 5000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=10.0)
    assert isinstance(r, TelecentricityReport)
    assert r.object_telecentric, (
        f"Expected object-space telecentric, got angle={r.chief_ray_angle_object_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 2: Chief-ray angle near zero for object-space telecentric
# ---------------------------------------------------------------------------

def test_stop_at_front_focal_plane_exact_angle_near_zero():
    """Chief-ray angle in object space should be < 0.5 deg for telecentric config."""
    f = 50.0
    surfaces = [
        {"c": 1.0 / f, "t": f, "n": 1.0},
        {"c": 0.0, "t": 0.0, "n": 1.0},
    ]
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 1,
        "object_distance_mm": 5000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=5.0)
    assert abs(r.chief_ray_angle_object_deg) < 0.5, (
        f"Object-space chief-ray angle too large: {r.chief_ray_angle_object_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 3: Object-space telecentric — small magnification variation
# ---------------------------------------------------------------------------

def test_object_telecentric_mag_variation_small():
    """
    For an object-space telecentric system, magnification variation with
    image-plane focus shift should be near zero.
    """
    f = 100.0
    surfaces = [
        {"c": 1.0 / f, "t": f, "n": 1.0},
        {"c": 0.0, "t": 0.0, "n": 1.0},
    ]
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 1,
        "object_distance_mm": 5000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=10.0, focus_shift_mm=1.0)
    assert r.object_telecentric
    if math.isfinite(r.max_magnification_variation_pct):
        assert r.max_magnification_variation_pct < 1.0, (
            f"Telecentric mag variation too large: {r.max_magnification_variation_pct:.4f}%"
        )


# ---------------------------------------------------------------------------
# Test 4: Non-telecentric — stop at first surface, finite conjugate
# ---------------------------------------------------------------------------

def test_non_telecentric_stop_at_first_surface():
    """
    Stop at first surface with finite object distance → chief ray NOT parallel
    to axis in object space → not object-space telecentric.
    """
    r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=200.0, field=10.0)
    assert not r.object_telecentric, (
        f"Expected NOT object-telecentric, angle={r.chief_ray_angle_object_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 5: Non-telecentric — chief-ray angle is above threshold
# ---------------------------------------------------------------------------

def test_non_telecentric_angle_nonzero():
    """Chief-ray angle in object space is well above 0.5 deg for non-telecentric."""
    r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=100.0, field=10.0)
    # u_obj = -field/obj_dist = -10/100 = -0.1 rad = -5.73 deg → clearly not telecentric
    assert abs(r.chief_ray_angle_object_deg) > 0.5, (
        f"Expected large chief-ray angle, got {r.chief_ray_angle_object_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 6: Non-telecentric — magnification variation is significant
# ---------------------------------------------------------------------------

def test_non_telecentric_mag_variation_significant():
    """Non-telecentric system: magnification varies with focus shift (> 0%)."""
    r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=200.0, field=10.0, fshift=2.0)
    assert not r.object_telecentric
    if math.isfinite(r.max_magnification_variation_pct):
        assert r.max_magnification_variation_pct > 0.0, (
            f"Expected non-zero mag variation, got {r.max_magnification_variation_pct:.4f}%"
        )


# ---------------------------------------------------------------------------
# Test 7: Image-space telecentric — two-lens relay with stop at midpoint
# ---------------------------------------------------------------------------

def test_image_telecentric_doubly_telecentric():
    """
    Two-lens relay with equal focal lengths and stop at the shared focal plane
    is doubly telecentric.  Image-space angle should be near zero
    (Smith MOE §5.4; the system satisfies both u_obj=0 and u_img=0).
    """
    f = 80.0
    surfaces = _two_lens_relay(f)
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 1,
        "object_distance_mm": 8000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=10.0)
    assert isinstance(r, TelecentricityReport)
    assert r.image_telecentric, (
        f"Expected image-space telecentric (doubly-telecentric relay), "
        f"got image angle={r.chief_ray_angle_image_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 8: Image-space telecentric — chief-ray angle near zero
# ---------------------------------------------------------------------------

def test_image_telecentric_angle_near_zero():
    """Numerical check: image-space chief-ray angle < 0.5 deg for doubly-telecentric."""
    f = 100.0
    surfaces = _two_lens_relay(f)
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 1,
        "object_distance_mm": 10_000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=10.0)
    assert abs(r.chief_ray_angle_image_deg) < 0.5, (
        f"Image-space chief-ray angle too large: {r.chief_ray_angle_image_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 9: Doubly telecentric — both flags True
# ---------------------------------------------------------------------------

def test_doubly_telecentric_symmetric_system():
    """Symmetric two-lens relay: both_telecentric = True."""
    f = 60.0
    surfaces = _two_lens_relay(f)
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 1,
        "object_distance_mm": 6000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=5.0)
    assert isinstance(r, TelecentricityReport)
    assert r.both_telecentric, (
        f"Expected doubly-telecentric, obj={r.chief_ray_angle_object_deg:.4f} deg, "
        f"img={r.chief_ray_angle_image_deg:.4f} deg"
    )


# ---------------------------------------------------------------------------
# Test 10: TelecentricityReport dataclass fields
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    """TelecentricityReport has all required fields."""
    r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=200.0)
    assert hasattr(r, "chief_ray_angle_object_deg")
    assert hasattr(r, "chief_ray_angle_image_deg")
    assert hasattr(r, "object_telecentric")
    assert hasattr(r, "image_telecentric")
    assert hasattr(r, "both_telecentric")
    assert hasattr(r, "max_magnification_variation_pct")
    assert hasattr(r, "honest_caveat")


# ---------------------------------------------------------------------------
# Test 11: to_dict() returns ok=True with expected keys
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    """to_dict() returns {'ok': True, ...} with all expected keys."""
    r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=200.0)
    d = r.to_dict()
    assert d["ok"] is True
    for key in (
        "chief_ray_angle_object_deg",
        "chief_ray_angle_image_deg",
        "object_telecentric",
        "image_telecentric",
        "both_telecentric",
        "max_magnification_variation_pct",
        "honest_caveat",
    ):
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Test 12: honest_caveat is present and non-empty
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    """honest_caveat field is a non-empty string describing scope."""
    r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=200.0)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 20


# ---------------------------------------------------------------------------
# Test 13: Single lens telecentric implies NOT image-telecentric
# ---------------------------------------------------------------------------

def test_object_telecentric_not_image_telecentric_single_lens():
    """
    Glass plano-convex lens (BK7, f=100 mm) with stop at the rear focal plane:
    object_telecentric=True (stop at rear FP → entrance pupil at infinity),
    image_telecentric=False (chief ray acquires slope through the glass).

    Uses a real glass surface (n_glass > 1) so refraction is non-zero.
    Surface 0: curved (c=1/R, n=n_glass=1.5), thickness 1 mm.
    Surface 1: flat exit surface (c=0, n=1.0), gap = f to stop.
    Surface 2: flat stop plane.
    """
    n_glass = 1.5
    f_lens = 100.0
    R = (n_glass - 1) * f_lens  # R = 50 mm for n=1.5, f=100
    surfaces = [
        {"c": 1.0 / R, "t": 1.0, "n": n_glass},
        {"c": 0.0, "t": f_lens, "n": 1.0},
        {"c": 0.0, "t": 0.0, "n": 1.0},
    ]
    lens = {
        "surfaces": surfaces,
        "stop_surface_index": 2,  # stop at rear focal plane
        "object_distance_mm": 5000.0,
    }
    r = compute_telecentricity(lens, field_height_mm=10.0)
    assert isinstance(r, TelecentricityReport)
    # Chief ray in object space should be near horizontal (object-space telecentric)
    assert r.object_telecentric, (
        f"Expected object-space telecentric, angle={r.chief_ray_angle_object_deg:.4f} deg"
    )
    # Chief ray in image space has non-zero angle (single-lens, not doubly telecentric)
    assert not r.image_telecentric, (
        f"Expected NOT image-telecentric for single glass lens, "
        f"img_angle={r.chief_ray_angle_image_deg:.4f} deg"
    )
    assert not r.both_telecentric


# ---------------------------------------------------------------------------
# Test 14: Error — missing surfaces
# ---------------------------------------------------------------------------

def test_error_missing_surfaces():
    """Returns error dict for lens_system_dict without 'surfaces'."""
    r = compute_telecentricity({"stop_surface_index": 0})
    assert isinstance(r, dict)
    assert r.get("ok") is False
    assert "surfaces" in r.get("reason", "").lower()


# ---------------------------------------------------------------------------
# Test 15: Error — empty surfaces
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    """Returns error dict for empty surfaces list."""
    r = compute_telecentricity({"surfaces": []})
    assert isinstance(r, dict)
    assert r.get("ok") is False


# ---------------------------------------------------------------------------
# Test 16: Error — bad surface (missing required field)
# ---------------------------------------------------------------------------

def test_error_bad_surface():
    """Returns error dict for surface missing required field 'n'."""
    r = compute_telecentricity({"surfaces": [{"c": 0.0, "t": 5.0}]})
    assert isinstance(r, dict)
    assert r.get("ok") is False


# ---------------------------------------------------------------------------
# Test 17: Error — field_height_mm <= 0
# ---------------------------------------------------------------------------

def test_error_bad_field_height():
    """Returns error dict for field_height_mm <= 0."""
    r = compute_telecentricity({"surfaces": _BK7_SURFACES}, field_height_mm=0.0)
    assert isinstance(r, dict)
    assert r.get("ok") is False


# ---------------------------------------------------------------------------
# Test 18: Error — focus_shift_mm <= 0
# ---------------------------------------------------------------------------

def test_error_bad_focus_shift():
    """Returns error dict for focus_shift_mm <= 0."""
    r = compute_telecentricity({"surfaces": _BK7_SURFACES}, focus_shift_mm=-1.0)
    assert isinstance(r, dict)
    assert r.get("ok") is False


# ---------------------------------------------------------------------------
# Test 19: Error — stop_surface_index out of range
# ---------------------------------------------------------------------------

def test_error_stop_out_of_range():
    """Returns error dict for stop_surface_index >= len(surfaces)."""
    r = compute_telecentricity({
        "surfaces": _BK7_SURFACES,
        "stop_surface_index": 5,
    })
    assert isinstance(r, dict)
    assert r.get("ok") is False


# ---------------------------------------------------------------------------
# Test 20: LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    """LLM tool optics_compute_telecentricity returns ok JSON."""
    from kerf_cad_core.optics.tools import run_compute_telecentricity

    payload = json.dumps({
        "lens_system_dict": {
            "surfaces": _BK7_SURFACES,
            "stop_surface_index": 0,
            "object_distance_mm": 200.0,
        },
        "field_height_mm": 5.0,
    })
    result_str = asyncio.get_event_loop().run_until_complete(
        run_compute_telecentricity(None, payload.encode())
    )
    result = json.loads(result_str)
    assert result.get("ok") is True
    assert "chief_ray_angle_object_deg" in result
    assert "object_telecentric" in result


# ---------------------------------------------------------------------------
# Test 21: LLM tool — missing lens_system_dict
# ---------------------------------------------------------------------------

def test_tool_missing_lens_system():
    """LLM tool returns error for missing lens_system_dict."""
    from kerf_cad_core.optics.tools import run_compute_telecentricity

    payload = json.dumps({"field_height_mm": 5.0})
    result_str = asyncio.get_event_loop().run_until_complete(
        run_compute_telecentricity(None, payload.encode())
    )
    result = json.loads(result_str)
    assert result.get("ok") is False


# ---------------------------------------------------------------------------
# Test 22: LLM tool — invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    """LLM tool handles invalid JSON gracefully (returns error payload)."""
    from kerf_cad_core.optics.tools import run_compute_telecentricity

    result_str = asyncio.get_event_loop().run_until_complete(
        run_compute_telecentricity(None, b"not-valid-json{{{")
    )
    result = json.loads(result_str)
    # err_payload returns {"error": ..., "code": ...}; error responses vary by tool
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error payload, got {result}"


# ---------------------------------------------------------------------------
# Test 23: LLM tool — accepts field_height_mm kwarg
# ---------------------------------------------------------------------------

def test_tool_with_field_height_kwarg():
    """LLM tool accepts optional field_height_mm kwarg."""
    from kerf_cad_core.optics.tools import run_compute_telecentricity

    payload = json.dumps({
        "lens_system_dict": {
            "surfaces": _BK7_SURFACES,
            "object_distance_mm": 300.0,
        },
        "field_height_mm": 15.0,
    })
    result_str = asyncio.get_event_loop().run_until_complete(
        run_compute_telecentricity(None, payload.encode())
    )
    result = json.loads(result_str)
    assert result.get("ok") is True


# ---------------------------------------------------------------------------
# Test 24: LLM tool — accepts focus_shift_mm kwarg
# ---------------------------------------------------------------------------

def test_tool_with_focus_shift_kwarg():
    """LLM tool accepts optional focus_shift_mm kwarg."""
    from kerf_cad_core.optics.tools import run_compute_telecentricity

    payload = json.dumps({
        "lens_system_dict": {
            "surfaces": _BK7_SURFACES,
            "object_distance_mm": 300.0,
        },
        "focus_shift_mm": 2.0,
    })
    result_str = asyncio.get_event_loop().run_until_complete(
        run_compute_telecentricity(None, payload.encode())
    )
    result = json.loads(result_str)
    assert result.get("ok") is True


# ---------------------------------------------------------------------------
# Test 25: Field-height invariance — linear scaling of chief-ray angle
# ---------------------------------------------------------------------------

def test_field_height_invariance():
    """
    Chief-ray angle scales linearly with field height (paraxial linearity).
    For a non-telecentric system: angle(2H) = 2 * angle(H).
    """
    def _angle(fh: float) -> float:
        r = _report(_BK7_SURFACES, stop_idx=0, obj_dist=150.0, field=fh)
        return r.chief_ray_angle_object_deg

    angle_5 = _angle(5.0)
    angle_10 = _angle(10.0)
    angle_20 = _angle(20.0)

    # angle must be non-zero (non-telecentric)
    assert abs(angle_5) > 0.5, f"Expected non-zero angle at field=5: {angle_5}"

    # Angle should scale proportionally with field height (paraxial linearity)
    assert abs(angle_10 / angle_5 - 2.0) < 0.01, (
        f"Expected 2x scaling: angle(10)={angle_10:.4f}, angle(5)={angle_5:.4f}"
    )
    assert abs(angle_20 / angle_5 - 4.0) < 0.01, (
        f"Expected 4x scaling: angle(20)={angle_20:.4f}, angle(5)={angle_5:.4f}"
    )
