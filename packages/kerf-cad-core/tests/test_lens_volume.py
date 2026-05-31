"""
Tests for kerf_cad_core.optics.lens_volume — glass volume and weight of singlet lens.

Test plan
---------
 1.  plano_convex_sag1                  — R1=100, R2=inf: sag1 ≈ 0.7843 mm ±0.1%
 2.  plano_convex_edge_thickness        — edge_thickness = ct − sag1 ≈ 4.2157 mm
 3.  plano_convex_volume                — V ≈ 2261.6 mm³ ±2%
 4.  plano_convex_weight                — weight ≈ 5.677 g ±2%
 5.  plano_convex_lens_form             — lens_form == "plano_convex"
 6.  biconvex_symmetric_sags_equal      — R1=+100, R2=-100: sag1 == sag2 (symmetric)
 7.  biconvex_symmetric_volume_lt_plano — symmetric biconvex has less volume than plano-convex
                                          (two caps removed vs one)
 8.  biconvex_symmetric_lens_form       — lens_form == "biconvex"
 9.  biconvex_symmetric_edge_thinner    — edge_thickness < ct (convex surfaces thin edge)
10.  biconcave_edge_thicker             — R1=-100, R2=+100: edge_thickness > ct
11.  biconcave_volume_gt_cylinder       — biconcave V > cylinder (caps add material)
12.  biconcave_lens_form                — lens_form == "biconcave"
13.  meniscus_form                      — R1=+100, R2=+200: lens_form == "meniscus"
14.  flat_flat_volume                   — R1=inf, R2=inf: V = π·r²·ct exactly (cylinder)
15.  flat_flat_lens_form                — lens_form == "plano_plano"
16.  density_scaling                    — doubling density doubles weight exactly
17.  volume_scales_with_thickness       — doubling ct roughly doubles V (for small sags)
18.  error_zero_thickness               — ct=0 → ok=False
19.  error_negative_thickness           — ct=-1 → ok=False
20.  error_zero_aperture                — CA_r=0 → ok=False
21.  error_aperture_exceeds_radius      — CA_r > |R1| → ok=False
22.  error_bad_type                     — passing dict instead of spec → ok=False
23.  report_has_all_fields              — all LensVolumeReport fields present
24.  to_dict_ok_key                     — to_dict()["ok"] is True + all expected keys
25.  sag2_zero_for_plano                — R2=inf → sag2_mm == 0.0
26.  weight_units_consistent            — volume_mm3 × density_g_per_mm3 == weight_g
27.  plano_concave_volume_gt_cylinder   — plano-concave V > cylinder
28.  plano_concave_lens_form            — lens_form == "plano_concave"
29.  biconvex_volume_exact              — biconvex V = cylinder - 2×cap1 (symmetric)
30.  honest_caveat_mentions_spherical   — honest_caveat mentions spherical / aspheric
31.  tool_plano_convex_happy_path       — LLM tool returns ok=True, sag1 ≈ 0.7843
32.  tool_biconvex_happy_path           — LLM tool biconvex returns lens_form "biconvex"
33.  tool_missing_required_field        — LLM tool missing radius_R1_mm → ok=False
34.  tool_bad_json                      — LLM tool invalid JSON → ok=False
35.  tool_custom_density                — LLM tool with SF11 density (4.74) → heavier

All tests are pure-Python, hermetic (no OCC, DB, or network).

References
----------
Smith, W.J. — "Modern Optical Engineering", 4th ed., §13.3.
Mahajan, V.N. — "Optical Imaging and Aberrations", §1.2.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.lens_volume import (
    SingletLensSpec,
    LensVolumeReport,
    compute_lens_volume,
    _sagitta,
    _spherical_cap_volume,
    _classify_lens_form,
)
from kerf_cad_core.optics.tools import run_compute_lens_volume


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INF = 1e18  # "flat" surface sentinel


def _spec(R1=100.0, R2=_INF, ct=5.0, ca=12.5, density=2.51):
    return SingletLensSpec(
        radius_R1_mm=R1,
        radius_R2_mm=R2,
        center_thickness_mm=ct,
        clear_aperture_radius_mm=ca,
        glass_density_g_cm3=density,
    )


def _run_tool(args: dict) -> dict:
    return json.loads(asyncio.run(run_compute_lens_volume(None, json.dumps(args).encode())))


# Plano-convex oracle values (analytically derived)
_R1 = 100.0
_CA = 12.5
_CT = 5.0
_DENSITY = 2.51  # g/cm³ = BK7

_SAG1_EXPECTED = _R1 - math.sqrt(_R1 ** 2 - _CA ** 2)        # 0.78427...
_CAP1_VOL = math.pi * _SAG1_EXPECTED ** 2 * (3 * _R1 - _SAG1_EXPECTED) / 3
_CYL_VOL = math.pi * _CA ** 2 * _CT
_V_PLANO_CONVEX = _CYL_VOL - _CAP1_VOL
_W_PLANO_CONVEX = _V_PLANO_CONVEX * _DENSITY * 1e-3


# ---------------------------------------------------------------------------
# 1. plano_convex_sag1
# ---------------------------------------------------------------------------

def test_plano_convex_sag1():
    """R1=100, R2=inf, CA=12.5: sag1 = R1 - sqrt(R1² - r²) ≈ 0.7843 mm."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport), f"Expected report, got: {report}"
    assert report.sag1_mm == pytest.approx(_SAG1_EXPECTED, rel=1e-3), (
        f"sag1 = {report.sag1_mm:.6f}; expected ≈ {_SAG1_EXPECTED:.6f}"
    )


# ---------------------------------------------------------------------------
# 2. plano_convex_edge_thickness
# ---------------------------------------------------------------------------

def test_plano_convex_edge_thickness():
    """Edge thickness = ct - sag1 for plano-convex."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    expected_et = _CT - _SAG1_EXPECTED
    assert report.edge_thickness_mm == pytest.approx(expected_et, rel=1e-4), (
        f"edge_thickness = {report.edge_thickness_mm:.4f}; expected {expected_et:.4f}"
    )
    assert report.edge_thickness_mm > 0.0, "Edge thickness must be positive"


# ---------------------------------------------------------------------------
# 3. plano_convex_volume
# ---------------------------------------------------------------------------

def test_plano_convex_volume():
    """Plano-convex: V = cylinder - cap1 (exact formula)."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    assert report.volume_mm3 == pytest.approx(_V_PLANO_CONVEX, rel=0.001), (
        f"V = {report.volume_mm3:.2f} mm³; expected {_V_PLANO_CONVEX:.2f} mm³"
    )
    # Also within 2% of the analytically correct value
    assert abs(report.volume_mm3 - _V_PLANO_CONVEX) / _V_PLANO_CONVEX < 0.02


# ---------------------------------------------------------------------------
# 4. plano_convex_weight
# ---------------------------------------------------------------------------

def test_plano_convex_weight():
    """Weight = volume × density (g/mm³)."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    assert report.weight_g == pytest.approx(_W_PLANO_CONVEX, rel=0.001), (
        f"weight = {report.weight_g:.4f} g; expected {_W_PLANO_CONVEX:.4f} g"
    )


# ---------------------------------------------------------------------------
# 5. plano_convex_lens_form
# ---------------------------------------------------------------------------

def test_plano_convex_lens_form():
    """R1=+100, R2=inf → lens_form == 'plano_convex'."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    assert report.lens_form == "plano_convex", f"Got: {report.lens_form}"


# ---------------------------------------------------------------------------
# 6. biconvex_symmetric_sags_equal
# ---------------------------------------------------------------------------

def test_biconvex_symmetric_sags_equal():
    """Symmetric biconvex R1=+100, R2=-100: sag1 == sag2."""
    spec = _spec(R1=100.0, R2=-100.0)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    assert report.sag1_mm == pytest.approx(report.sag2_mm, rel=1e-6), (
        f"sag1={report.sag1_mm:.6f} != sag2={report.sag2_mm:.6f} for symmetric biconvex"
    )
    # Both should equal the single-surface sag
    assert report.sag1_mm == pytest.approx(_SAG1_EXPECTED, rel=1e-4)


# ---------------------------------------------------------------------------
# 7. biconvex_symmetric_volume_lt_plano
# ---------------------------------------------------------------------------

def test_biconvex_symmetric_volume_lt_plano():
    """Biconvex removes two caps → less volume than plano-convex (one cap)."""
    plano_report = compute_lens_volume(_spec(R1=100.0, R2=_INF))
    biconvex_report = compute_lens_volume(_spec(R1=100.0, R2=-100.0))
    assert isinstance(plano_report, LensVolumeReport)
    assert isinstance(biconvex_report, LensVolumeReport)
    assert biconvex_report.volume_mm3 < plano_report.volume_mm3, (
        f"biconvex V ({biconvex_report.volume_mm3:.2f}) should be < "
        f"plano-convex V ({plano_report.volume_mm3:.2f})"
    )
    # Volume difference should be one additional cap
    diff = plano_report.volume_mm3 - biconvex_report.volume_mm3
    assert diff == pytest.approx(_CAP1_VOL, rel=0.001), (
        f"Volume difference {diff:.2f} should equal V_cap1 {_CAP1_VOL:.2f}"
    )


# ---------------------------------------------------------------------------
# 8. biconvex_symmetric_lens_form
# ---------------------------------------------------------------------------

def test_biconvex_symmetric_lens_form():
    """R1=+100, R2=-100 → lens_form == 'biconvex'."""
    report = compute_lens_volume(_spec(R1=100.0, R2=-100.0))
    assert isinstance(report, LensVolumeReport)
    assert report.lens_form == "biconvex", f"Got: {report.lens_form}"


# ---------------------------------------------------------------------------
# 9. biconvex_symmetric_edge_thinner
# ---------------------------------------------------------------------------

def test_biconvex_symmetric_edge_thinner():
    """Biconvex: both convex surfaces thin the edge → edge_thickness < ct."""
    report = compute_lens_volume(_spec(R1=100.0, R2=-100.0))
    assert isinstance(report, LensVolumeReport)
    assert report.edge_thickness_mm < _CT, (
        f"Biconvex edge_thickness ({report.edge_thickness_mm:.4f}) "
        f"should be < center_thickness ({_CT})"
    )
    # Edge should equal ct - sag1 - sag2 = ct - 2*sag1 (symmetric)
    expected_et = _CT - 2.0 * _SAG1_EXPECTED
    assert report.edge_thickness_mm == pytest.approx(expected_et, rel=1e-4)


# ---------------------------------------------------------------------------
# 10. biconcave_edge_thicker
# ---------------------------------------------------------------------------

def test_biconcave_edge_thicker():
    """Biconcave R1=-100, R2=+100: concave surfaces add material → edge_thickness > ct."""
    spec = _spec(R1=-100.0, R2=100.0)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    assert report.edge_thickness_mm > _CT, (
        f"Biconcave edge_thickness ({report.edge_thickness_mm:.4f}) "
        f"should be > center_thickness ({_CT})"
    )
    # Edge should equal ct + sag1 + sag2 = ct + 2*sag1 (symmetric concave)
    expected_et = _CT + 2.0 * _SAG1_EXPECTED
    assert report.edge_thickness_mm == pytest.approx(expected_et, rel=1e-4)


# ---------------------------------------------------------------------------
# 11. biconcave_volume_gt_cylinder
# ---------------------------------------------------------------------------

def test_biconcave_volume_gt_cylinder():
    """Biconcave: concave surfaces add caps → V > cylinder(r, ct)."""
    spec = _spec(R1=-100.0, R2=100.0)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    assert report.volume_mm3 > _CYL_VOL, (
        f"Biconcave V ({report.volume_mm3:.2f}) should be > cylinder ({_CYL_VOL:.2f})"
    )
    # Volume should equal cylinder + 2 × cap (symmetric)
    expected_V = _CYL_VOL + 2.0 * _CAP1_VOL
    assert report.volume_mm3 == pytest.approx(expected_V, rel=0.001)


# ---------------------------------------------------------------------------
# 12. biconcave_lens_form
# ---------------------------------------------------------------------------

def test_biconcave_lens_form():
    """R1=-100, R2=+100 → lens_form == 'biconcave'."""
    report = compute_lens_volume(_spec(R1=-100.0, R2=100.0))
    assert isinstance(report, LensVolumeReport)
    assert report.lens_form == "biconcave", f"Got: {report.lens_form}"


# ---------------------------------------------------------------------------
# 13. meniscus_form
# ---------------------------------------------------------------------------

def test_meniscus_form():
    """R1=+100, R2=+200 (same-sign, both centres to the right) → 'meniscus'."""
    # Both R positive: front convex, rear concave toward image
    # This is a positive meniscus (converging meniscus, thicker at centre)
    spec = _spec(R1=100.0, R2=200.0)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    assert report.lens_form == "meniscus", f"Got: {report.lens_form}"


# ---------------------------------------------------------------------------
# 14. flat_flat_volume
# ---------------------------------------------------------------------------

def test_flat_flat_volume():
    """R1=inf, R2=inf (window/plate): V == π·r²·ct exactly."""
    spec = _spec(R1=_INF, R2=_INF)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    expected_V = math.pi * _CA ** 2 * _CT
    assert report.volume_mm3 == pytest.approx(expected_V, rel=1e-10), (
        f"Flat-flat V = {report.volume_mm3:.6f}; expected {expected_V:.6f}"
    )


# ---------------------------------------------------------------------------
# 15. flat_flat_lens_form
# ---------------------------------------------------------------------------

def test_flat_flat_lens_form():
    """R1=inf, R2=inf → lens_form == 'plano_plano'."""
    report = compute_lens_volume(_spec(R1=_INF, R2=_INF))
    assert isinstance(report, LensVolumeReport)
    assert report.lens_form == "plano_plano", f"Got: {report.lens_form}"


# ---------------------------------------------------------------------------
# 16. density_scaling
# ---------------------------------------------------------------------------

def test_density_scaling():
    """Doubling density should exactly double weight, not change volume."""
    r1 = compute_lens_volume(_spec(density=2.51))
    r2 = compute_lens_volume(_spec(density=5.02))
    assert isinstance(r1, LensVolumeReport) and isinstance(r2, LensVolumeReport)
    assert r1.volume_mm3 == pytest.approx(r2.volume_mm3, rel=1e-10), "Volume should not change"
    assert r2.weight_g == pytest.approx(r1.weight_g * 2.0, rel=1e-10), "Weight should double"


# ---------------------------------------------------------------------------
# 17. volume_scales_with_thickness
# ---------------------------------------------------------------------------

def test_volume_scales_with_thickness():
    """
    Doubling center thickness should approximately double V when sag << ct.
    For R1=100, r=12.5, ct=5: sag1=0.784 << ct=5, so cap contribution is small.
    """
    r1 = compute_lens_volume(_spec(ct=5.0))
    r2 = compute_lens_volume(_spec(ct=10.0))
    assert isinstance(r1, LensVolumeReport) and isinstance(r2, LensVolumeReport)
    # V ≈ π·r²·ct for thin-cap lenses: doubling ct → V increases by ~π·r²·5 (the added cylinder)
    # More precisely: V(10) - V(5) = π·r²·(10-5) = cylinder of 5mm
    extra_cylinder = math.pi * _CA ** 2 * 5.0
    assert (r2.volume_mm3 - r1.volume_mm3) == pytest.approx(extra_cylinder, rel=0.001), (
        f"Volume increase {r2.volume_mm3 - r1.volume_mm3:.2f} should ≈ {extra_cylinder:.2f}"
    )


# ---------------------------------------------------------------------------
# 18. error_zero_thickness
# ---------------------------------------------------------------------------

def test_error_zero_thickness():
    """center_thickness_mm = 0 should return ok=False."""
    spec = _spec(ct=0.0)
    result = compute_lens_volume(spec)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "center_thickness" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 19. error_negative_thickness
# ---------------------------------------------------------------------------

def test_error_negative_thickness():
    """center_thickness_mm < 0 should return ok=False."""
    spec = _spec(ct=-1.0)
    result = compute_lens_volume(spec)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 20. error_zero_aperture
# ---------------------------------------------------------------------------

def test_error_zero_aperture():
    """clear_aperture_radius_mm = 0 should return ok=False."""
    spec = _spec(ca=0.0)
    result = compute_lens_volume(spec)
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 21. error_aperture_exceeds_radius
# ---------------------------------------------------------------------------

def test_error_aperture_exceeds_radius():
    """CA_r > |R1| makes sagitta imaginary → ok=False."""
    # R1=10, CA_r=15 → R1² - r² < 0
    spec = _spec(R1=10.0, ca=15.0, ct=5.0)
    result = compute_lens_volume(spec)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "radius of curvature" in result["reason"].lower() or "exceeds" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 22. error_bad_type
# ---------------------------------------------------------------------------

def test_error_bad_type():
    """Passing a dict instead of SingletLensSpec returns ok=False."""
    result = compute_lens_volume({"radius_R1_mm": 100})  # type: ignore[arg-type]
    assert isinstance(result, dict)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 23. report_has_all_fields
# ---------------------------------------------------------------------------

def test_report_has_all_fields():
    """LensVolumeReport has all expected attributes."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    for attr in (
        "volume_mm3",
        "weight_g",
        "edge_thickness_mm",
        "sag1_mm",
        "sag2_mm",
        "lens_form",
        "honest_caveat",
    ):
        assert hasattr(report, attr), f"Missing attribute: {attr}"


# ---------------------------------------------------------------------------
# 24. to_dict_ok_key
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    """to_dict() returns ok=True with all expected keys."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    d = report.to_dict()
    assert d["ok"] is True
    for key in (
        "volume_mm3",
        "weight_g",
        "edge_thickness_mm",
        "sag1_mm",
        "sag2_mm",
        "lens_form",
        "honest_caveat",
    ):
        assert key in d, f"Missing key in to_dict(): {key}"


# ---------------------------------------------------------------------------
# 25. sag2_zero_for_plano
# ---------------------------------------------------------------------------

def test_sag2_zero_for_plano():
    """R2=inf → sag2_mm == 0.0 (flat surface contributes no cap)."""
    report = compute_lens_volume(_spec(R2=_INF))
    assert isinstance(report, LensVolumeReport)
    assert report.sag2_mm == 0.0, f"sag2 for flat surface should be 0.0, got {report.sag2_mm}"


# ---------------------------------------------------------------------------
# 26. weight_units_consistent
# ---------------------------------------------------------------------------

def test_weight_units_consistent():
    """weight_g == volume_mm3 × density_g_per_mm3 (unit consistency check)."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    density_g_mm3 = _DENSITY * 1e-3  # g/cm³ → g/mm³
    expected_weight = report.volume_mm3 * density_g_mm3
    assert report.weight_g == pytest.approx(expected_weight, rel=1e-6)


# ---------------------------------------------------------------------------
# 27. plano_concave_volume_gt_cylinder
# ---------------------------------------------------------------------------

def test_plano_concave_volume_gt_cylinder():
    """Plano-concave (R1=-100, R2=inf): concave front adds material → V > cylinder."""
    spec = _spec(R1=-100.0, R2=_INF)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    assert report.volume_mm3 > _CYL_VOL, (
        f"Plano-concave V ({report.volume_mm3:.2f}) should be > cylinder ({_CYL_VOL:.2f})"
    )
    expected_V = _CYL_VOL + _CAP1_VOL
    assert report.volume_mm3 == pytest.approx(expected_V, rel=0.001)


# ---------------------------------------------------------------------------
# 28. plano_concave_lens_form
# ---------------------------------------------------------------------------

def test_plano_concave_lens_form():
    """R1=-100, R2=inf → lens_form == 'plano_concave'."""
    report = compute_lens_volume(_spec(R1=-100.0, R2=_INF))
    assert isinstance(report, LensVolumeReport)
    assert report.lens_form == "plano_concave", f"Got: {report.lens_form}"


# ---------------------------------------------------------------------------
# 29. biconvex_volume_exact
# ---------------------------------------------------------------------------

def test_biconvex_volume_exact():
    """Symmetric biconvex V = cylinder − 2·V_cap1 exactly."""
    spec = _spec(R1=100.0, R2=-100.0)
    report = compute_lens_volume(spec)
    assert isinstance(report, LensVolumeReport)
    expected_V = _CYL_VOL - 2.0 * _CAP1_VOL
    assert report.volume_mm3 == pytest.approx(expected_V, rel=1e-6), (
        f"biconvex V = {report.volume_mm3:.4f}; expected {expected_V:.4f}"
    )


# ---------------------------------------------------------------------------
# 30. honest_caveat_mentions_spherical
# ---------------------------------------------------------------------------

def test_honest_caveat_mentions_spherical():
    """honest_caveat should mention 'spherical' and 'aspheric'."""
    report = compute_lens_volume(_spec())
    assert isinstance(report, LensVolumeReport)
    caveat_lower = report.honest_caveat.lower()
    assert "spherical" in caveat_lower, "honest_caveat should mention 'spherical'"
    assert "aspheric" in caveat_lower, "honest_caveat should mention 'aspheric'"


# ---------------------------------------------------------------------------
# 31. tool_plano_convex_happy_path
# ---------------------------------------------------------------------------

def test_tool_plano_convex_happy_path():
    """LLM tool optics_compute_lens_volume: plano-convex returns ok=True, sag1 correct."""
    d = _run_tool({
        "radius_R1_mm": 100.0,
        "radius_R2_mm": 1e18,
        "center_thickness_mm": 5.0,
        "clear_aperture_radius_mm": 12.5,
        "glass_density_g_cm3": 2.51,
    })
    assert d["ok"] is True, f"Tool returned: {d}"
    assert d["sag1_mm"] == pytest.approx(_SAG1_EXPECTED, rel=1e-3)
    assert d["volume_mm3"] == pytest.approx(_V_PLANO_CONVEX, rel=0.001)
    assert d["weight_g"] == pytest.approx(_W_PLANO_CONVEX, rel=0.001)
    assert d["lens_form"] == "plano_convex"
    assert "honest_caveat" in d


# ---------------------------------------------------------------------------
# 32. tool_biconvex_happy_path
# ---------------------------------------------------------------------------

def test_tool_biconvex_happy_path():
    """LLM tool: biconvex lens returns lens_form 'biconvex' and ok=True."""
    d = _run_tool({
        "radius_R1_mm": 100.0,
        "radius_R2_mm": -100.0,
        "center_thickness_mm": 5.0,
        "clear_aperture_radius_mm": 12.5,
    })
    assert d["ok"] is True, f"Tool returned: {d}"
    assert d["lens_form"] == "biconvex"
    assert d["volume_mm3"] > 0.0
    assert d["weight_g"] > 0.0
    # Symmetric → sag1 == sag2
    assert d["sag1_mm"] == pytest.approx(d["sag2_mm"], rel=1e-6)


# ---------------------------------------------------------------------------
# 33. tool_missing_required_field
# ---------------------------------------------------------------------------

def test_tool_missing_required_field():
    """LLM tool: missing radius_R1_mm → ok=False."""
    d = _run_tool({
        "radius_R2_mm": -100.0,
        "center_thickness_mm": 5.0,
        "clear_aperture_radius_mm": 12.5,
    })
    assert d["ok"] is False
    assert "radius_R1_mm" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 34. tool_bad_json
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    """LLM tool: invalid JSON returns an error response."""
    result = json.loads(asyncio.run(run_compute_lens_volume(None, b"{bad json")))
    is_error = result.get("ok") is False or "error" in result or "code" in result
    assert is_error, f"Expected error, got: {result}"


# ---------------------------------------------------------------------------
# 35. tool_custom_density
# ---------------------------------------------------------------------------

def test_tool_custom_density():
    """LLM tool: using SF11 density (4.74 g/cm³) yields heavier lens than BK7 (2.51)."""
    bk7 = _run_tool({
        "radius_R1_mm": 100.0,
        "radius_R2_mm": 1e18,
        "center_thickness_mm": 5.0,
        "clear_aperture_radius_mm": 12.5,
        "glass_density_g_cm3": 2.51,
    })
    sf11 = _run_tool({
        "radius_R1_mm": 100.0,
        "radius_R2_mm": 1e18,
        "center_thickness_mm": 5.0,
        "clear_aperture_radius_mm": 12.5,
        "glass_density_g_cm3": 4.74,
    })
    assert bk7["ok"] is True
    assert sf11["ok"] is True
    # Same geometry → same volume
    assert bk7["volume_mm3"] == pytest.approx(sf11["volume_mm3"], rel=1e-6)
    # SF11 density/BK7 density ≈ 4.74/2.51
    weight_ratio = sf11["weight_g"] / bk7["weight_g"]
    assert weight_ratio == pytest.approx(4.74 / 2.51, rel=1e-4)
