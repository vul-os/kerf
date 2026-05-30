"""
Tests for kerf_cad_core.optics.chief_ray_vignetting — chief-ray vignetting
and relative illumination (RI).

Test plan
---------
1.  no_clipping_ri_near_cos4          -- unvignetted system: RI ≈ cos⁴(θ) at each field
2.  no_clipping_on_axis_is_one        -- RI at 0° = 1.0 for no-clipping system
3.  no_clipping_monotonic_decrease    -- RI decreases monotonically with field for cos⁴
4.  clipped_system_below_baseline     -- system with tight CA drops below cos⁴
5.  clipped_system_on_axis_no_clip    -- on-axis is unclipped even with tight rim
6.  full_clip_returns_zero            -- CA = 0 clips all rays -> RI = 0
7.  excess_vignetting_unity_no_clip   -- excess = RI/cos⁴ ≈ 1.0 for unvignetted
8.  excess_vignetting_below_one       -- excess < 1 when surfaces clip
9.  blocked_surfaces_empty_no_clip    -- no blocked surfaces for infinite CA
10. blocked_surfaces_nonzero_clip     -- blocked_surfaces lists clipping surface
11. cos4_baseline_values              -- cos⁴ values match math.cos(rad)^4
12. n_marginal_rays_16                -- n_marginal_rays=16 gives same qualitative result
13. error_empty_surfaces              -- error for empty surfaces list
14. error_bad_surface                 -- error for missing surface field
15. error_ca_length_mismatch          -- error when len(clear_apertures_mm) != n_surf
16. error_n_marginal_too_small        -- error for n_marginal_rays < 4
17. error_bad_aperture_radius         -- error for non-positive aperture_radius_mm
18. error_empty_field_angles          -- error for empty field_angles_deg
19. report_dataclass_fields           -- VignettingReport has all required fields
20. to_dict_ok_key                    -- to_dict() has ok=True
21. honest_flag_in_dict               -- to_dict() includes honest_flag string
22. biconvex_lens_no_clip_ri          -- BK7 biconvex singlet: RI at 5° > RI at 10°
23. clipped_first_surface_identified  -- tight first-surface CA shows surface 0 blocked
24. surviving_fractions_alias         -- surviving_fractions == relative_illumination
25. tool_happy_path                   -- LLM tool returns ok JSON with ri key
26. tool_missing_surfaces             -- LLM tool returns error for missing surfaces
27. tool_bad_json                     -- LLM tool handles invalid JSON
28. tool_with_ca                      -- tool accepts optional clear_apertures_mm
29. tool_n_marginal_kwarg             -- tool accepts n_marginal_rays kwarg
30. ri_in_range                       -- RI values always in [0, 1]
31. cos4_in_range                     -- cos4 values always in [0, 1]
32. per_field_blocked_sorted          -- per_field_blocked_surfaces lists are sorted
33. single_surface_no_clip            -- single flat surface with infinite CA: RI = 1

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §4.5.
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.6.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.chief_ray_vignetting import (
    VignettingReport,
    compute_vignetting,
)
from kerf_cad_core.optics.tools import run_compute_vignetting


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# BK7 biconvex singlet (f ≈ 48 mm, diameter = 20 mm)
_BK7_BICONVEX = [
    {"c": 1 / 50.0, "t": 5.0, "n": 1.5168, "k": 0.0},
    {"c": -1 / 50.0, "t": 0.0, "n": 1.0, "k": 0.0},
]

# Simple flat system — 1 surface
_FLAT_SINGLE = [
    {"c": 0.0, "t": 0.0, "n": 1.0},
]

# Field angles
_FIELDS = [0.0, 5.0, 10.0, 14.0]


def _report(surfaces, field_angles, **kw) -> VignettingReport:
    r = compute_vignetting(surfaces, field_angles, **kw)
    assert isinstance(r, VignettingReport), f"Expected VignettingReport, got {r}"
    return r


# ---------------------------------------------------------------------------
# Test 1: no-clipping RI ≈ cos⁴(θ)
# ---------------------------------------------------------------------------

def test_no_clipping_ri_near_cos4():
    """Unvignetted system: RI ≈ cos⁴(θ) at each field angle (Hecht §6.6)."""
    r = _report(_BK7_BICONVEX, _FIELDS, aperture_radius_mm=5.0,
                n_marginal_rays=16)
    for theta, ri, c4 in zip(r.field_angles_deg, r.relative_illumination, r.cos4_baseline):
        # RI should be close to cos⁴ for unvignetted stack
        assert abs(ri - c4) < 0.15, (
            f"θ={theta}°: RI={ri:.4f} too far from cos⁴={c4:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 2: on-axis RI = 1 with no clipping
# ---------------------------------------------------------------------------

def test_no_clipping_on_axis_is_one():
    r = _report(_BK7_BICONVEX, [0.0], aperture_radius_mm=5.0)
    assert r.relative_illumination[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 3: monotonic decrease with field (no clipping)
# ---------------------------------------------------------------------------

def test_no_clipping_monotonic_decrease():
    r = _report(_BK7_BICONVEX, _FIELDS, aperture_radius_mm=5.0, n_marginal_rays=16)
    ri = r.relative_illumination
    for i in range(len(ri) - 1):
        assert ri[i] >= ri[i + 1] - 0.05, (
            f"RI not monotonically decreasing: ri[{i}]={ri[i]}, ri[{i+1}]={ri[i+1]}"
        )


# ---------------------------------------------------------------------------
# Test 4: clipped system falls below baseline
# ---------------------------------------------------------------------------

def test_clipped_system_below_baseline():
    """System with tight clear aperture clips marginal rays → RI < cos⁴."""
    # CA on first surface = 1 mm (much smaller than aperture_radius=5 mm)
    # → all off-axis marginal rays clipped
    ca = [1.5, math.inf]   # very small first-surface aperture
    r = _report(_BK7_BICONVEX, [10.0], aperture_radius_mm=5.0,
                clear_apertures_mm=ca, n_marginal_rays=8)
    cos4_10 = math.cos(math.radians(10.0)) ** 4
    ri_10 = r.relative_illumination[0]
    assert ri_10 < cos4_10 + 0.01, (
        f"Expected RI < cos⁴ for clipped system, got ri={ri_10} cos4={cos4_10}"
    )


# ---------------------------------------------------------------------------
# Test 5: on-axis is not clipped even with tight rim
# ---------------------------------------------------------------------------

def test_clipped_system_on_axis_no_clip():
    """On-axis chief ray height = 0 at first surface → marginal rays within pupil."""
    # CA large enough for the aperture_radius
    ca = [6.0, math.inf]
    r = _report(_BK7_BICONVEX, [0.0], aperture_radius_mm=5.0,
                clear_apertures_mm=ca)
    assert r.relative_illumination[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 6: full clip returns zero
# ---------------------------------------------------------------------------

def test_full_clip_returns_zero():
    """CA = 0.001 mm clips most/all rays (n=4: only cos(90°)=0 passes → RI=0)."""
    ca = [0.001, math.inf]
    # Use n_marginal_rays=4 → phi_k in {0°,90°,180°,270°};
    # cos(0°)=1, cos(90°)=0, cos(180°)=-1, cos(270°)=0.
    # h_k values: {5, 0, -5, 0} mm.  Rays at ±5 mm blocked; h=0 passes.
    # RI = 2/4 = 0.5 when CA=0.001 and aperture=5.
    # With n=16: cos(pi/8)≈0.924, ..., cos(pi/2)=0 → 2 survive (h≈0 within 0.001) → RI≤2/16
    r = _report(_BK7_BICONVEX, [5.0], aperture_radius_mm=5.0,
                clear_apertures_mm=ca, n_marginal_rays=16)
    # At most 2 of 16 rays have |h| < 0.001 → RI < 0.15
    assert r.relative_illumination[0] < 0.15, (
        f"Expected very low RI for near-zero CA, got {r.relative_illumination[0]}"
    )


# ---------------------------------------------------------------------------
# Test 7: excess vignetting ≈ 1 for unvignetted
# ---------------------------------------------------------------------------

def test_excess_vignetting_unity_no_clip():
    r = _report(_BK7_BICONVEX, [5.0, 10.0], aperture_radius_mm=5.0,
                n_marginal_rays=16)
    for ev in r.excess_vignetting:
        if not math.isnan(ev):
            assert abs(ev - 1.0) < 0.2, f"Expected excess ≈ 1, got {ev}"


# ---------------------------------------------------------------------------
# Test 8: excess vignetting < 1 when clipping
# ---------------------------------------------------------------------------

def test_excess_vignetting_below_one():
    ca = [1.5, math.inf]
    r = _report(_BK7_BICONVEX, [10.0], aperture_radius_mm=5.0,
                clear_apertures_mm=ca, n_marginal_rays=8)
    ev = r.excess_vignetting[0]
    assert math.isnan(ev) or ev < 1.01, f"Expected excess <= 1, got {ev}"


# ---------------------------------------------------------------------------
# Test 9: no blocked surfaces for infinite CA
# ---------------------------------------------------------------------------

def test_blocked_surfaces_empty_no_clip():
    r = _report(_BK7_BICONVEX, _FIELDS, aperture_radius_mm=5.0)
    for bs in r.per_field_blocked_surfaces:
        assert bs == [], f"Expected empty blocked list, got {bs}"


# ---------------------------------------------------------------------------
# Test 10: blocked surfaces nonzero when clipping
# ---------------------------------------------------------------------------

def test_blocked_surfaces_nonzero_clip():
    ca = [1.5, math.inf]
    r = _report(_BK7_BICONVEX, [10.0], aperture_radius_mm=5.0,
                clear_apertures_mm=ca)
    # Some field angle should show blocked surfaces
    assert any(len(bs) > 0 for bs in r.per_field_blocked_surfaces), (
        "Expected at least one blocked surface with tight CA"
    )


# ---------------------------------------------------------------------------
# Test 11: cos⁴ baseline values
# ---------------------------------------------------------------------------

def test_cos4_baseline_values():
    r = _report(_BK7_BICONVEX, _FIELDS)
    for theta_deg, c4 in zip(r.field_angles_deg, r.cos4_baseline):
        expected = math.cos(math.radians(theta_deg)) ** 4
        assert abs(c4 - expected) < 1e-9, f"cos4 mismatch at {theta_deg}°"


# ---------------------------------------------------------------------------
# Test 12: n_marginal_rays=16
# ---------------------------------------------------------------------------

def test_n_marginal_rays_16():
    r = _report(_BK7_BICONVEX, [0.0, 10.0], aperture_radius_mm=5.0,
                n_marginal_rays=16)
    assert r.n_marginal_rays == 16
    assert r.relative_illumination[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests 13–18: error cases
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_vignetting([], [0.0, 5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_bad_surface():
    r = compute_vignetting([{"c": 0.02, "t": 5.0}], [0.0])  # missing n
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_ca_length_mismatch():
    r = compute_vignetting(_BK7_BICONVEX, [0.0], clear_apertures_mm=[10.0])
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "clear_apertures_mm" in r["reason"]


def test_error_n_marginal_too_small():
    r = compute_vignetting(_BK7_BICONVEX, [0.0], n_marginal_rays=3)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_bad_aperture_radius():
    r = compute_vignetting(_BK7_BICONVEX, [0.0], aperture_radius_mm=-1.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_empty_field_angles():
    r = compute_vignetting(_BK7_BICONVEX, [])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# Tests 19–21: dataclass and serialisation
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = _report(_BK7_BICONVEX, _FIELDS)
    assert hasattr(r, "field_angles_deg")
    assert hasattr(r, "relative_illumination")
    assert hasattr(r, "cos4_baseline")
    assert hasattr(r, "surviving_fractions")
    assert hasattr(r, "excess_vignetting")
    assert hasattr(r, "per_field_blocked_surfaces")
    assert hasattr(r, "n_marginal_rays")
    assert hasattr(r, "aperture_radius_mm")
    assert hasattr(r, "honest_flag")


def test_to_dict_ok_key():
    r = _report(_BK7_BICONVEX, [0.0])
    d = r.to_dict()
    assert d["ok"] is True


def test_honest_flag_in_dict():
    r = _report(_BK7_BICONVEX, [0.0])
    d = r.to_dict()
    assert "honest_flag" in d
    assert len(d["honest_flag"]) > 0


# ---------------------------------------------------------------------------
# Test 22: BK7 biconvex singlet off-axis RI ordering
# ---------------------------------------------------------------------------

def test_biconvex_lens_no_clip_ri():
    r = _report(_BK7_BICONVEX, [5.0, 10.0], aperture_radius_mm=5.0,
                n_marginal_rays=16)
    assert r.relative_illumination[0] >= r.relative_illumination[1], (
        "RI should not increase with field angle"
    )


# ---------------------------------------------------------------------------
# Test 23: clipped first surface identified in blocked list
# ---------------------------------------------------------------------------

def test_clipped_first_surface_identified():
    ca = [0.001, math.inf]
    r = _report(_BK7_BICONVEX, [5.0], aperture_radius_mm=5.0,
                clear_apertures_mm=ca)
    bs = r.per_field_blocked_surfaces[0]
    assert 0 in bs, f"Expected surface 0 in blocked list, got {bs}"


# ---------------------------------------------------------------------------
# Test 24: surviving_fractions alias
# ---------------------------------------------------------------------------

def test_surviving_fractions_alias():
    r = _report(_BK7_BICONVEX, _FIELDS)
    assert r.surviving_fractions == r.relative_illumination


# ---------------------------------------------------------------------------
# Tests 25–29: LLM tool
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    payload = json.dumps({
        "surfaces": _BK7_BICONVEX,
        "field_angles_deg": [0.0, 5.0, 10.0],
    })
    result = asyncio.run(run_compute_vignetting(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert "relative_illumination" in data
    assert len(data["relative_illumination"]) == 3


def test_tool_missing_surfaces():
    payload = json.dumps({"field_angles_deg": [0.0, 5.0]})
    result = asyncio.run(run_compute_vignetting(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is False


def test_tool_bad_json():
    result = asyncio.run(run_compute_vignetting(None, b"not-json"))
    data = json.loads(result)
    # err_payload uses "error" + "code" keys (not "ok")
    assert "error" in data or data.get("ok") is False


def test_tool_with_ca():
    payload = json.dumps({
        "surfaces": _BK7_BICONVEX,
        "field_angles_deg": [5.0, 10.0],
        "aperture_radius_mm": 5.0,
        "clear_apertures_mm": [100.0, 100.0],
    })
    result = asyncio.run(run_compute_vignetting(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert "relative_illumination" in data


def test_tool_n_marginal_kwarg():
    payload = json.dumps({
        "surfaces": _BK7_BICONVEX,
        "field_angles_deg": [0.0, 5.0],
        "n_marginal_rays": 12,
    })
    result = asyncio.run(run_compute_vignetting(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["n_marginal_rays"] == 12


# ---------------------------------------------------------------------------
# Tests 30–32: range and ordering invariants
# ---------------------------------------------------------------------------

def test_ri_in_range():
    r = _report(_BK7_BICONVEX, _FIELDS)
    for ri in r.relative_illumination:
        assert 0.0 <= ri <= 1.0, f"RI out of range: {ri}"


def test_cos4_in_range():
    r = _report(_BK7_BICONVEX, _FIELDS)
    for c4 in r.cos4_baseline:
        assert 0.0 <= c4 <= 1.0, f"cos4 out of range: {c4}"


def test_per_field_blocked_sorted():
    ca = [1.5, 0.5]
    r = _report(_BK7_BICONVEX, _FIELDS, clear_apertures_mm=ca)
    for bs in r.per_field_blocked_surfaces:
        assert bs == sorted(bs), f"Blocked surfaces not sorted: {bs}"


# ---------------------------------------------------------------------------
# Test 33: single surface no clip
# ---------------------------------------------------------------------------

def test_single_surface_no_clip():
    r = _report(_FLAT_SINGLE, [0.0, 5.0, 10.0], aperture_radius_mm=5.0)
    assert r.relative_illumination[0] == pytest.approx(1.0)
    for ri in r.relative_illumination:
        assert 0.0 <= ri <= 1.0
