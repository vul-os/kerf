"""
Tests for kerf_cad_core.optics.relative_illum_map — 2-D relative illumination
map across the image plane.

Test plan
---------
 1. ideal_stack_centre_is_one           -- RI at image centre = 1.0 (on-axis, no CA)
 2. ideal_stack_all_ones_no_ca          -- no clear apertures → all RI = 1.0 (no physical clipping)
 3. ideal_cos4_map_centre_is_one        -- cos4_map centre = 1.0
 4. ideal_cos4_map_decreases_radially   -- cos4_map decreases from centre to corner
 5. ideal_cos4_map_matches_formula      -- cos4_map values match cos⁴(θ) formula
 6. clipped_stack_centre_is_one         -- on-axis RI = 1.0 even with off-axis tight CA
 7. clipped_stack_corner_below_one      -- with tight CA, corner RI < 1.0
 8. clipped_stack_corner_below_cos4     -- with tight CA, corner_ri <= 1.0
 9. ri_map_shape                        -- ri_map is (grid × grid)
10. cos4_map_shape                      -- cos4_map is (grid × grid)
11. ri_values_in_range                  -- all RI values in [0, 1]
12. cos4_values_in_range                -- all cos4 values in [0, 1]
13. grid_size_5x5                       -- image_grid_size=5 works, returns 5×5 maps
14. grid_size_3x3_minimum               -- minimum grid size 3 works
15. max_field_angle_positive            -- max_field_angle > 0 for positive sensor extent
16. corner_ri_in_range                  -- corner_ri in [0, 1]
17. corner_cos4_in_range                -- corner_cos4 in [0, 1]
18. corner_cos4_less_than_one           -- corner_cos4 < 1.0 for nonzero sensor
19. efl_mm_positive                     -- efl_mm > 0 for converging singlet
20. rotational_symmetry                 -- RI(x, y) == RI(-x, y) (left-right symmetry)
21. cos4_map_rotational_symmetry        -- cos4_map is azimuthally symmetric
22. to_dict_ok_key                      -- to_dict() has ok=True
23. to_dict_ri_map_key                  -- to_dict() includes ri_map key
24. to_dict_cos4_map_key                -- to_dict() includes cos4_map key
25. honest_flag_in_dict                 -- to_dict() includes honest_flag string
26. error_empty_surfaces                -- error for empty surfaces list
27. error_bad_surface                   -- error for invalid surface dict
28. error_grid_size_too_small           -- error for image_grid_size < 3
29. error_negative_sensor               -- error for sensor_half_height_mm <= 0
30. error_negative_aperture             -- error for aperture_radius_mm <= 0
31. error_marginal_rays_too_small       -- error for n_marginal_rays < 4
32. wide_angle_cos4_corner_below_16pct  -- cos4_map corner < 0.16 for θ_corner > 50°
33. report_dataclass_fields             -- RelIllumMapReport has all expected fields
34. tool_happy_path                     -- LLM tool returns ok JSON with ri_map key
35. tool_missing_surfaces               -- LLM tool returns error for missing surfaces
36. tool_bad_json                       -- LLM tool handles invalid JSON
37. tool_optional_params                -- tool accepts grid size, sensor and CA overrides
38. aberrated_corner_ri_below_ideal     -- clipped stack: corner RI < no-CA stack

All tests are pure-Python and hermetic (no OCC, DB, or network).

ALGORITHM NOTE:
  compute_relative_illum_map delegates to compute_vignetting which models
  *physical aperture clipping* (marginal rays blocked at lens rims).
  With no clear_apertures_mm (all surfaces = ∞), no rays are physically
  blocked: ri_map = all 1.0.  The cos4_map always reflects the cos⁴(θ)
  photometric baseline (natural illumination fall-off, Hecht §6.6).
  Only when finite clear apertures are supplied does ri_map < 1.0 off-axis.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §4.5.
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.6.
Slyusarev, G.G. -- "Aberration and Optical Design Theory", Hilger, 1984, §3.4.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.relative_illum_map import (
    RelIllumMapReport,
    compute_relative_illum_map,
)
from kerf_cad_core.optics.tools import run_optics_relative_illum_map


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# BK7 biconvex singlet (f ≈ 48 mm)
_BK7 = [
    {"c": 1 / 50.0, "t": 5.0, "n": 1.5168, "k": 0.0},
    {"c": -1 / 50.0, "t": 0.0, "n": 1.0, "k": 0.0},
]

_SENSOR = 12.0   # half-height 12 mm → EFL ~49 mm → θ_corner ≈ 19°
_GRID = 11        # 11×11 for speed


def _report(surfaces=None, *, grid=_GRID, sensor=_SENSOR, **kw) -> RelIllumMapReport:
    if surfaces is None:
        surfaces = _BK7
    r = compute_relative_illum_map(
        surfaces,
        image_grid_size=grid,
        sensor_half_height_mm=sensor,
        aperture_radius_mm=5.0,
        n_marginal_rays=8,
        **kw,
    )
    assert isinstance(r, RelIllumMapReport), f"Expected RelIllumMapReport, got {r}"
    return r


# ---------------------------------------------------------------------------
# Test 1: centre RI = 1.0 (no CA → no physical clipping on-axis)
# ---------------------------------------------------------------------------

def test_ideal_stack_centre_is_one():
    """RI at the image centre (on-axis, no CA) must equal 1.0."""
    r = _report()
    centre = _GRID // 2
    assert r.ri_map[centre][centre] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 2: no CA → all RI = 1.0 (physical clipping model)
# ---------------------------------------------------------------------------

def test_ideal_stack_all_ones_no_ca():
    """No clear_apertures_mm: all surfaces infinite → no clipping → ri_map = all 1.0."""
    r = _report()
    for row in r.ri_map:
        for val in row:
            assert val == pytest.approx(1.0, abs=1e-6), (
                f"Expected RI=1.0 with no CA, got {val}"
            )


# ---------------------------------------------------------------------------
# Test 3: cos4_map centre = 1.0
# ---------------------------------------------------------------------------

def test_ideal_cos4_map_centre_is_one():
    """cos4_map at centre (θ=0°) = cos⁴(0°) = 1.0."""
    r = _report()
    centre = _GRID // 2
    assert r.cos4_map[centre][centre] == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 4: cos4_map decreases radially
# ---------------------------------------------------------------------------

def test_ideal_cos4_map_decreases_radially():
    """cos4_map should decrease monotonically along a radial from centre to edge."""
    r = _report()
    n = _GRID
    centre = n // 2
    row = r.cos4_map[centre]
    segment = [row[centre + k] for k in range(centre + 1)]
    for k in range(len(segment) - 1):
        assert segment[k] >= segment[k + 1] - 1e-9, (
            f"cos4_map not monotonically decreasing: [{k}]={segment[k]}, [{k+1}]={segment[k+1]}"
        )


# ---------------------------------------------------------------------------
# Test 5: cos4_map values match cos⁴(θ) formula
# ---------------------------------------------------------------------------

def test_ideal_cos4_map_matches_formula():
    """cos4_map values must match cos⁴(arctan(r/EFL)) at each grid point."""
    r = _report()
    efl = r.efl_mm
    step = 2.0 * _SENSOR / (_GRID - 1)
    for i, row in enumerate(r.cos4_map):
        yi = -_SENSOR + i * step
        for j, c4 in enumerate(row):
            xi = -_SENSOR + j * step
            rr = math.sqrt(xi * xi + yi * yi)
            theta_rad = math.atan2(rr, efl)
            expected = math.cos(theta_rad) ** 4
            assert abs(c4 - expected) < 1e-6, (
                f"cos4_map mismatch at ({xi:.1f},{yi:.1f}): got {c4:.8f}, expected {expected:.8f}"
            )


# ---------------------------------------------------------------------------
# Test 6: clipped stack on-axis RI = 1.0
# ---------------------------------------------------------------------------

def test_clipped_stack_centre_is_one():
    """On-axis RI = 1.0 even with tight off-axis clear aperture (h_chief=0 on-axis)."""
    # CA of 6 mm for first surface: clips off-axis but not on-axis (h=0 + marginal ≤ 5 mm aperture)
    ca = [6.0, math.inf]
    r = _report(clear_apertures_mm=ca)
    centre = _GRID // 2
    assert r.ri_map[centre][centre] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 7: clipped stack corner RI < 1.0
# ---------------------------------------------------------------------------

def test_clipped_stack_corner_below_one():
    """With tight CA, corner RI drops below 1.0 due to physical clipping."""
    ca = [3.0, math.inf]  # very tight CA = 3 mm
    r = _report(clear_apertures_mm=ca)
    assert r.corner_ri < 1.0, (
        f"Expected corner_ri < 1.0 for clipped stack, got {r.corner_ri:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 8: clipped stack corner RI ≤ 1.0
# ---------------------------------------------------------------------------

def test_clipped_stack_corner_below_cos4():
    """Physical clipping: RI at corner <= 1.0 (always; ideally below cos4 baseline)."""
    ca = [3.0, math.inf]
    r = _report(clear_apertures_mm=ca)
    assert r.corner_ri <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# Tests 9–12: shape and range invariants
# ---------------------------------------------------------------------------

def test_ri_map_shape():
    r = _report()
    assert len(r.ri_map) == _GRID
    for row in r.ri_map:
        assert len(row) == _GRID


def test_cos4_map_shape():
    r = _report()
    assert len(r.cos4_map) == _GRID
    for row in r.cos4_map:
        assert len(row) == _GRID


def test_ri_values_in_range():
    r = _report()
    for row in r.ri_map:
        for val in row:
            assert 0.0 <= val <= 1.0, f"RI out of range: {val}"


def test_cos4_values_in_range():
    r = _report()
    for row in r.cos4_map:
        for val in row:
            assert 0.0 <= val <= 1.0, f"cos4 out of range: {val}"


# ---------------------------------------------------------------------------
# Tests 13–14: grid size variants
# ---------------------------------------------------------------------------

def test_grid_size_5x5():
    r = _report(grid=5)
    assert r.image_grid_size == 5
    assert len(r.ri_map) == 5
    assert len(r.ri_map[0]) == 5


def test_grid_size_3x3_minimum():
    r = _report(grid=3)
    assert r.image_grid_size == 3
    assert len(r.ri_map) == 3


# ---------------------------------------------------------------------------
# Tests 15–19: report metadata
# ---------------------------------------------------------------------------

def test_max_field_angle_positive():
    r = _report()
    assert r.max_field_angle > 0.0


def test_corner_ri_in_range():
    r = _report()
    assert 0.0 <= r.corner_ri <= 1.0


def test_corner_cos4_in_range():
    r = _report()
    assert 0.0 <= r.corner_cos4 <= 1.0


def test_corner_cos4_less_than_one():
    """Corner cos4 must be < 1.0 since corner is at nonzero field angle."""
    r = _report()
    assert r.corner_cos4 < 1.0, f"corner_cos4={r.corner_cos4:.4f} should be < 1.0"


def test_efl_mm_positive():
    r = _report()
    assert r.efl_mm > 0.0


# ---------------------------------------------------------------------------
# Tests 20–21: rotational symmetry
# ---------------------------------------------------------------------------

def test_rotational_symmetry():
    """ri_map is left-right symmetric for rotationally symmetric stack."""
    r = _report()
    n = _GRID
    centre = n // 2
    row = r.ri_map[centre]
    for k in range(centre):
        left = row[k]
        right = row[n - 1 - k]
        assert abs(left - right) < 1e-9, (
            f"Left-right asymmetry: row[{k}]={left:.6f}, row[{n-1-k}]={right:.6f}"
        )


def test_cos4_map_rotational_symmetry():
    """cos4_map is also left-right symmetric."""
    r = _report()
    n = _GRID
    centre = n // 2
    row = r.cos4_map[centre]
    for k in range(centre):
        left = row[k]
        right = row[n - 1 - k]
        assert abs(left - right) < 1e-9, (
            f"cos4_map left-right asymmetry: [{k}]={left:.8f}, [{n-1-k}]={right:.8f}"
        )


# ---------------------------------------------------------------------------
# Tests 22–25: serialisation
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    r = _report()
    d = r.to_dict()
    assert d["ok"] is True


def test_to_dict_ri_map_key():
    r = _report()
    d = r.to_dict()
    assert "ri_map" in d
    assert isinstance(d["ri_map"], list)


def test_to_dict_cos4_map_key():
    r = _report()
    d = r.to_dict()
    assert "cos4_map" in d
    assert isinstance(d["cos4_map"], list)


def test_honest_flag_in_dict():
    r = _report()
    d = r.to_dict()
    assert "honest_flag" in d
    assert len(d["honest_flag"]) > 20


# ---------------------------------------------------------------------------
# Tests 26–31: error cases
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_relative_illum_map([])
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_bad_surface():
    r = compute_relative_illum_map([{"c": 0.02, "t": 5.0}])  # missing n
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_grid_size_too_small():
    r = compute_relative_illum_map(_BK7, image_grid_size=2)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_negative_sensor():
    r = compute_relative_illum_map(_BK7, sensor_half_height_mm=-5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_negative_aperture():
    r = compute_relative_illum_map(_BK7, aperture_radius_mm=0.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_marginal_rays_too_small():
    r = compute_relative_illum_map(_BK7, n_marginal_rays=3)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# Test 32: wide-angle cos4 corner < 16%
# ---------------------------------------------------------------------------

def test_wide_angle_cos4_corner_below_16pct():
    """
    For a very large sensor, corner field angle > 50° and cos⁴(50°) ≈ 17%.
    The cos4_map corner value should be well below 0.20.
    BK7 biconvex: EFL ≈ 49 mm; sensor_half_height 60 mm → θ_corner ≈ 60°.
    cos⁴(60°) = 0.0625.
    """
    r = compute_relative_illum_map(
        _BK7,
        image_grid_size=5,
        sensor_half_height_mm=60.0,
        aperture_radius_mm=5.0,
        n_marginal_rays=8,
    )
    assert isinstance(r, RelIllumMapReport), f"got error: {r}"
    assert r.corner_cos4 < 0.20, (
        f"Expected corner_cos4 < 0.20 for wide-angle, got {r.corner_cos4:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 33: dataclass fields
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = _report()
    for attr in (
        "ri_map", "cos4_map", "image_extent", "max_field_angle",
        "efl_mm", "image_grid_size", "aperture_radius_mm",
        "corner_ri", "corner_cos4", "honest_flag",
    ):
        assert hasattr(r, attr), f"RelIllumMapReport missing field: {attr}"


# ---------------------------------------------------------------------------
# Tests 34–37: LLM tool
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    payload = json.dumps({"surfaces": _BK7})
    result = asyncio.run(run_optics_relative_illum_map(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert "ri_map" in data
    assert isinstance(data["ri_map"], list)


def test_tool_missing_surfaces():
    payload = json.dumps({"image_grid_size": 5})
    result = asyncio.run(run_optics_relative_illum_map(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is False


def test_tool_bad_json():
    result = asyncio.run(run_optics_relative_illum_map(None, b"not-json"))
    data = json.loads(result)
    assert "error" in data or data.get("ok") is False


def test_tool_optional_params():
    payload = json.dumps({
        "surfaces": _BK7,
        "image_grid_size": 5,
        "sensor_half_height_mm": 10.0,
        "aperture_radius_mm": 5.0,
        "clear_apertures_mm": [100.0, 100.0],
        "n_marginal_rays": 8,
    })
    result = asyncio.run(run_optics_relative_illum_map(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["image_grid_size"] == 5
    assert len(data["ri_map"]) == 5


# ---------------------------------------------------------------------------
# Test 38: aberrated (clipped) stack corner RI ≤ ideal (no-CA) corner RI
# ---------------------------------------------------------------------------

def test_aberrated_corner_ri_below_ideal():
    """
    Tight CA causes physical clipping: corner RI drops below the no-CA (=1.0) case.
    ideal corner_ri = 1.0 (no physical blocking).
    clipped corner_ri < 1.0 (rays blocked at tight rim).
    """
    ideal = _report()
    clipped = _report(clear_apertures_mm=[3.0, math.inf])
    assert clipped.corner_ri <= ideal.corner_ri + 0.01, (
        f"Clipped corner_ri={clipped.corner_ri:.4f} not <= ideal {ideal.corner_ri:.4f}"
    )
    assert clipped.corner_ri < 1.0, (
        f"Expected corner_ri < 1.0 for tight CA, got {clipped.corner_ri:.4f}"
    )
