"""
Tests for kerf_cad_core.optics.pupil_diagram -- spot diagrams and pupil illumination maps.

Test plan
---------
1.  stigmatic_rms_near_zero         -- flat surface: y-RMS spot ~ 0 (stigmatic)
2.  stigmatic_intercepts_single_pt  -- all y-intercepts within 1e-4 mm of chief ray
3.  bk7_biconvex_onaxis_finite_rms  -- BK7 biconvex on-axis: y-RMS > 0 (spherical aberr)
4.  bk7_biconvex_14deg_rms_larger   -- y-RMS at 14 deg > y-RMS at 0 deg (coma grows)
5.  field_angle_extremes_rms        -- y-RMS at max field > y-RMS at 0 for singlet
6.  chief_ray_zero_pupil            -- chief_ray_y_mm is finite after trace
7.  n_rays_traced_positive          -- at least one ray traced per field
8.  intercepts_count_consistent     -- n_rays_traced == len(intercepts_mm)
9.  surviving_pupils_count          -- surviving pupil coords count == n_rays_traced
10. exit_pupil_pos_finite            -- exit_pupil_pos_mm is finite
11. rms_list_length                  -- len(rms_spot_size_per_field) == len(field_angles)
12. to_dict_ok_key                   -- to_dict() has ok=True
13. to_dict_spots_length             -- to_dict() spots_per_field has correct length
14. honest_flag_present              -- report includes honest_flag string
15. error_empty_surfaces             -- error dict for empty surfaces
16. error_missing_field              -- error dict for missing surface field
17. error_bad_field_angles           -- error dict for non-list field_angles_deg
18. error_zero_aperture              -- error dict for aperture_radius_mm=0
19. error_n_object_lt_1              -- error dict for n_object < 1
20. error_n_rays_zero                -- error dict for n_rays_per_field=0
21. pupil_grid_unit_disk             -- all pupil coords within unit disk
22. rms_nonneg                       -- all RMS values >= 0
23. max_dist_ge_rms                  -- max_ray_distance >= rms for all fields
24. on_axis_chief_y_near_zero        -- chief_ray_y_mm near 0 for 0-deg field
25. bk7_14deg_y_rms_range            -- BK7 14deg y-RMS in plausible range
26. seidel_coma_ratio                -- y-RMS(14deg)/y-RMS(0deg) >> 1 for BK7 singlet
27. multiple_field_angles            -- handles [0, 5, 10, 14] correctly
28. single_field_zero                -- single field = 0 works
29. efl_in_report                    -- EFL_mm in report matches paraxial_properties
30. tool_happy_path                  -- LLM tool returns ok JSON with spots_per_field
31. tool_missing_surfaces            -- LLM tool returns error for missing surfaces
32. tool_bad_json                    -- LLM tool handles invalid JSON
33. tool_optional_kwargs             -- tool accepts n_rays_per_field and aperture

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §8.2.
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §5.7.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.lens_stack_trace import paraxial_properties
from kerf_cad_core.optics.pupil_diagram import (
    PupilDiagramReport,
    SpotFieldData,
    _pupil_grid,
    compute_pupil_diagram,
)
from kerf_cad_core.optics.tools import run_pupil_diagram


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# BK7 biconvex singlet: R1=+50mm, R2=-50mm, n=1.5168, t=5mm
# followed by a flat exit (air) surface
_BK7_SURFACES = [
    {"c": 1.0 / 50.0,  "t": 5.0, "n": 1.5168},
    {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
]


# ---------------------------------------------------------------------------
# 1. stigmatic_rms_near_zero
# ---------------------------------------------------------------------------

def test_stigmatic_rms_near_zero():
    """
    A single flat surface (c=0) acts like free space; all meridional rays at
    field angle 0 with varying height trace to the same image point → y-RMS ~ 0.

    Flat surface: c=0, t=50mm, n=1.0 (identity propagation in air).
    """
    flat = [{"c": 0.0, "t": 50.0, "n": 1.0}]
    result = compute_pupil_diagram(flat, [0.0], n_rays_per_field=64)
    assert isinstance(result, PupilDiagramReport)
    assert result.spots_per_field[0].rms_spot_y_mm < 1e-6, (
        f"Expected near-zero y-RMS for flat stack, got {result.spots_per_field[0].rms_spot_y_mm}"
    )


# ---------------------------------------------------------------------------
# 2. stigmatic_intercepts_single_pt
# ---------------------------------------------------------------------------

def test_stigmatic_intercepts_single_pt():
    """
    For a flat (c=0) on-axis stack all y-intercepts should cluster at one point.
    """
    flat = [{"c": 0.0, "t": 50.0, "n": 1.0}]
    result = compute_pupil_diagram(flat, [0.0], n_rays_per_field=49)
    assert isinstance(result, PupilDiagramReport)
    sfd = result.spots_per_field[0]
    ys = [pt[1] for pt in sfd.intercepts_mm]
    spread = max(ys) - min(ys) if len(ys) > 1 else 0.0
    assert spread < 1e-4, f"Expected tight y-cluster, spread={spread}"


# ---------------------------------------------------------------------------
# 3. bk7_biconvex_onaxis_finite_rms
# ---------------------------------------------------------------------------

def test_bk7_biconvex_onaxis_finite_rms():
    """
    BK7 biconvex singlet on-axis: spherical aberration means y-RMS > 0.
    """
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    rms_y = result.spots_per_field[0].rms_spot_y_mm
    assert math.isfinite(rms_y)
    assert rms_y > 0.0, "Expected non-zero y-RMS for BK7 singlet (spherical aberration)"


# ---------------------------------------------------------------------------
# 4. bk7_biconvex_14deg_rms_larger
# ---------------------------------------------------------------------------

def test_bk7_biconvex_14deg_rms_larger():
    """
    Meridional y-RMS at 14° must be strictly larger than at 0° (coma grows).
    """
    result = compute_pupil_diagram(
        _BK7_SURFACES, [0.0, 14.0], aperture_radius_mm=5.0, n_rays_per_field=100
    )
    assert isinstance(result, PupilDiagramReport)
    rms_y_0 = result.spots_per_field[0].rms_spot_y_mm
    rms_y_14 = result.spots_per_field[1].rms_spot_y_mm
    assert rms_y_14 > rms_y_0, (
        f"Expected y-RMS(14°) > y-RMS(0°), got {rms_y_14:.6f} vs {rms_y_0:.6f}"
    )


# ---------------------------------------------------------------------------
# 5. field_angle_extremes_rms
# ---------------------------------------------------------------------------

def test_field_angle_extremes_rms():
    """
    y-RMS at max field (14°) must exceed y-RMS at 0° for a singlet.
    Intermediate angles may fluctuate slightly (finite sampling).
    """
    angles = [0.0, 5.0, 10.0, 14.0]
    result = compute_pupil_diagram(
        _BK7_SURFACES, angles, aperture_radius_mm=5.0, n_rays_per_field=80
    )
    assert isinstance(result, PupilDiagramReport)
    rms_y_list = [sfd.rms_spot_y_mm for sfd in result.spots_per_field]
    assert rms_y_list[-1] >= rms_y_list[0], (
        f"y-RMS at 14° ({rms_y_list[-1]:.4f}) should be >= y-RMS at 0° ({rms_y_list[0]:.4f})"
    )


# ---------------------------------------------------------------------------
# 6. chief_ray_zero_pupil
# ---------------------------------------------------------------------------

def test_chief_ray_zero_pupil():
    """
    The chief-ray y intercept (py=0 pupil) should be finite.
    """
    result = compute_pupil_diagram(
        _BK7_SURFACES, [5.0], aperture_radius_mm=5.0, n_rays_per_field=25
    )
    assert isinstance(result, PupilDiagramReport)
    sfd = result.spots_per_field[0]
    assert math.isfinite(sfd.chief_ray_y_mm)


# ---------------------------------------------------------------------------
# 7. n_rays_traced_positive
# ---------------------------------------------------------------------------

def test_n_rays_traced_positive():
    """At least one ray must be traced per field angle."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0, 5.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    for sfd in result.spots_per_field:
        assert sfd.n_rays_traced > 0


# ---------------------------------------------------------------------------
# 8. intercepts_count_consistent
# ---------------------------------------------------------------------------

def test_intercepts_count_consistent():
    """n_rays_traced must equal len(intercepts_mm)."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    sfd = result.spots_per_field[0]
    assert sfd.n_rays_traced == len(sfd.intercepts_mm)


# ---------------------------------------------------------------------------
# 9. surviving_pupils_count
# ---------------------------------------------------------------------------

def test_surviving_pupils_count():
    """surviving pupil coords length must equal n_rays_traced."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    sfd = result.spots_per_field[0]
    assert len(sfd.pupil_coords_surviving) == sfd.n_rays_traced


# ---------------------------------------------------------------------------
# 10. exit_pupil_pos_finite
# ---------------------------------------------------------------------------

def test_exit_pupil_pos_finite():
    """exit_pupil_pos_mm must be finite."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0])
    assert isinstance(result, PupilDiagramReport)
    assert math.isfinite(result.exit_pupil_pos_mm)


# ---------------------------------------------------------------------------
# 11. rms_list_length
# ---------------------------------------------------------------------------

def test_rms_list_length():
    """rms_spot_size_per_field length must equal number of field angles."""
    angles = [0.0, 5.0, 10.0]
    result = compute_pupil_diagram(_BK7_SURFACES, angles)
    assert isinstance(result, PupilDiagramReport)
    assert len(result.rms_spot_size_per_field) == len(angles)


# ---------------------------------------------------------------------------
# 12. to_dict_ok_key
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    """PupilDiagramReport.to_dict() must have ok=True."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0])
    assert isinstance(result, PupilDiagramReport)
    d = result.to_dict()
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 13. to_dict_spots_length
# ---------------------------------------------------------------------------

def test_to_dict_spots_length():
    """to_dict() spots_per_field length must match field angles count."""
    angles = [0.0, 7.0]
    result = compute_pupil_diagram(_BK7_SURFACES, angles)
    d = result.to_dict()
    assert len(d["spots_per_field"]) == len(angles)


# ---------------------------------------------------------------------------
# 14. honest_flag_present
# ---------------------------------------------------------------------------

def test_honest_flag_present():
    """PupilDiagramReport.honest_flag must be a non-empty string with key terms."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0])
    assert isinstance(result, PupilDiagramReport)
    assert isinstance(result.honest_flag, str)
    assert len(result.honest_flag) > 10
    assert "Monochromatic" in result.honest_flag


# ---------------------------------------------------------------------------
# 15. error_empty_surfaces
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    """Empty surface list must return error dict."""
    result = compute_pupil_diagram([], [0.0])
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 16. error_missing_field
# ---------------------------------------------------------------------------

def test_error_missing_field():
    """Surface missing required field 'n' must return error dict."""
    bad = [{"c": 0.02, "t": 5.0}]  # no 'n'
    result = compute_pupil_diagram(bad, [0.0])
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "n" in result["reason"]


# ---------------------------------------------------------------------------
# 17. error_bad_field_angles
# ---------------------------------------------------------------------------

def test_error_bad_field_angles():
    """Non-list field_angles_deg must return error dict."""
    result = compute_pupil_diagram(_BK7_SURFACES, "bad")
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 18. error_zero_aperture
# ---------------------------------------------------------------------------

def test_error_zero_aperture():
    """aperture_radius_mm=0 must return error dict."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], aperture_radius_mm=0.0)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 19. error_n_object_lt_1
# ---------------------------------------------------------------------------

def test_error_n_object_lt_1():
    """n_object < 1 must return error dict."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], n_object=0.5)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 20. error_n_rays_zero
# ---------------------------------------------------------------------------

def test_error_n_rays_zero():
    """n_rays_per_field=0 must return error dict."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], n_rays_per_field=0)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 21. pupil_grid_unit_disk
# ---------------------------------------------------------------------------

def test_pupil_grid_unit_disk():
    """All pupil-grid points must be within the unit disk."""
    pts = _pupil_grid(200)
    assert len(pts) > 0
    for px, py in pts:
        assert px * px + py * py <= 1.0 + 1e-8, f"Point ({px},{py}) outside unit disk"


# ---------------------------------------------------------------------------
# 22. rms_nonneg
# ---------------------------------------------------------------------------

def test_rms_nonneg():
    """All RMS spot sizes must be >= 0."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0, 5.0, 14.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    for rms in result.rms_spot_size_per_field:
        assert rms >= 0.0
    for sfd in result.spots_per_field:
        assert sfd.rms_spot_y_mm >= 0.0


# ---------------------------------------------------------------------------
# 23. max_dist_ge_rms
# ---------------------------------------------------------------------------

def test_max_dist_ge_rms():
    """max_ray_distance >= rms_spot_radius for all field angles."""
    result = compute_pupil_diagram(
        _BK7_SURFACES, [0.0, 5.0, 10.0], aperture_radius_mm=5.0
    )
    assert isinstance(result, PupilDiagramReport)
    for sfd in result.spots_per_field:
        assert sfd.max_ray_distance_mm >= sfd.rms_spot_radius_mm - 1e-12


# ---------------------------------------------------------------------------
# 24. on_axis_chief_y_near_zero
# ---------------------------------------------------------------------------

def test_on_axis_chief_y_near_zero():
    """
    For 0-degree field angle, the chief ray (py=0) should trace to a
    small y near zero (on-axis source images on-axis).
    """
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    sfd = result.spots_per_field[0]
    assert abs(sfd.chief_ray_y_mm) < 0.1, (
        f"On-axis chief ray y={sfd.chief_ray_y_mm:.4f} expected near 0"
    )


# ---------------------------------------------------------------------------
# 25. bk7_14deg_y_rms_range
# ---------------------------------------------------------------------------

def test_bk7_14deg_y_rms_range():
    """
    BK7 biconvex at 14 deg, aperture 5mm: meridional y-RMS should be in
    0.001..5 mm range.  This is a plausibility check (comatic spot size
    for a singlet without correction: Welford 1986 §8.3).
    """
    result = compute_pupil_diagram(
        _BK7_SURFACES, [14.0], aperture_radius_mm=5.0, n_rays_per_field=100
    )
    assert isinstance(result, PupilDiagramReport)
    rms_y = result.spots_per_field[0].rms_spot_y_mm
    assert 0.001 <= rms_y <= 5.0, f"BK7 14° y-RMS={rms_y:.6f}mm not in expected range [0.001, 5.0]"


# ---------------------------------------------------------------------------
# 26. seidel_coma_ratio
# ---------------------------------------------------------------------------

def test_seidel_coma_ratio():
    """
    Meridional y-RMS at 14° / y-RMS at 0° should be > 2 for a BK7 singlet
    with aperture 5mm, confirming coma growth with field angle (Welford 1986 §8.2).

    The y-only spread isolates the meridional aberration signal; the full 2-D
    RMS includes the first-order sagittal x contribution which is nearly
    constant across field angles.
    """
    result = compute_pupil_diagram(
        _BK7_SURFACES, [0.0, 14.0], aperture_radius_mm=5.0, n_rays_per_field=100
    )
    assert isinstance(result, PupilDiagramReport)
    rms_y_0 = result.spots_per_field[0].rms_spot_y_mm
    rms_y_14 = result.spots_per_field[1].rms_spot_y_mm

    assert rms_y_0 > 1e-9, "On-axis y-RMS should be > 0 (spherical aberration)"
    ratio = rms_y_14 / rms_y_0
    assert ratio > 2.0, (
        f"Expected meridional coma ratio > 2, got {ratio:.2f} "
        f"(y_rms_0={rms_y_0:.6f}, y_rms_14={rms_y_14:.6f})"
    )


# ---------------------------------------------------------------------------
# 27. multiple_field_angles
# ---------------------------------------------------------------------------

def test_multiple_field_angles():
    """Report for [0, 5, 10, 14] has four entries in correct order."""
    angles = [0.0, 5.0, 10.0, 14.0]
    result = compute_pupil_diagram(_BK7_SURFACES, angles, aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    assert len(result.spots_per_field) == 4
    for i, sfd in enumerate(result.spots_per_field):
        assert abs(sfd.field_angle_deg - angles[i]) < 1e-9


# ---------------------------------------------------------------------------
# 28. single_field_zero
# ---------------------------------------------------------------------------

def test_single_field_zero():
    """Single field angle = 0 works without error."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0], aperture_radius_mm=5.0)
    assert isinstance(result, PupilDiagramReport)
    assert len(result.spots_per_field) == 1


# ---------------------------------------------------------------------------
# 29. efl_in_report
# ---------------------------------------------------------------------------

def test_efl_in_report():
    """EFL_mm in report must match paraxial_properties EFL."""
    result = compute_pupil_diagram(_BK7_SURFACES, [0.0])
    assert isinstance(result, PupilDiagramReport)
    props = paraxial_properties(_BK7_SURFACES)
    assert abs(result.EFL_mm - props["EFL_mm"]) < 1e-6


# ---------------------------------------------------------------------------
# 30. tool_happy_path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    """LLM tool run_pupil_diagram returns ok JSON with spots_per_field."""
    args = json.dumps({
        "surfaces": _BK7_SURFACES,
        "field_angles_deg": [0.0, 5.0],
        "aperture_radius_mm": 5.0,
        "n_rays_per_field": 50,
    }).encode()

    result_str = asyncio.get_event_loop().run_until_complete(
        run_pupil_diagram(None, args)
    )
    d = json.loads(result_str)
    assert d.get("ok") is True
    assert "spots_per_field" in d
    assert len(d["spots_per_field"]) == 2


# ---------------------------------------------------------------------------
# 31. tool_missing_surfaces
# ---------------------------------------------------------------------------

def test_tool_missing_surfaces():
    """LLM tool returns error when surfaces is missing."""
    args = json.dumps({"field_angles_deg": [0.0]}).encode()
    result_str = asyncio.get_event_loop().run_until_complete(
        run_pupil_diagram(None, args)
    )
    d = json.loads(result_str)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# 32. tool_bad_json
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    """LLM tool handles invalid JSON without raising.
    err_payload returns {"error": ..., "code": "BAD_ARGS"} for parse errors."""
    result_str = asyncio.get_event_loop().run_until_complete(
        run_pupil_diagram(None, b"not json{{")
    )
    d = json.loads(result_str)
    is_error = (d.get("ok") is False) or ("error" in d) or ("code" in d)
    assert is_error, f"Expected error response, got: {d}"


# ---------------------------------------------------------------------------
# 33. tool_optional_kwargs
# ---------------------------------------------------------------------------

def test_tool_optional_kwargs():
    """LLM tool accepts optional n_rays_per_field and aperture_radius_mm."""
    args = json.dumps({
        "surfaces": _BK7_SURFACES,
        "field_angles_deg": [0.0],
        "n_rays_per_field": 25,
        "aperture_radius_mm": 3.0,
        "n_object": 1.0,
    }).encode()
    result_str = asyncio.get_event_loop().run_until_complete(
        run_pupil_diagram(None, args)
    )
    d = json.loads(result_str)
    assert d.get("ok") is True
    assert abs(d["aperture_radius_mm"] - 3.0) < 1e-9
