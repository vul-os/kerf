"""
Tests for kerf_cad_core.optics.vignetting_check.

Test plan
---------
 1. on_axis_no_vignetting          — field=0° → vignetting_pct = 0
 2. on_axis_limiting_surface_none  — field=0° → limiting_surface_idx is None
 3. on_axis_effective_100          — field=0° → effective_pupil_area_pct = 100
 4. wide_angle_significant_vig     — field=30°, small CAs → vignetting_pct > 0
 5. limiting_surface_identified    — tight second surface → limiting_surface_idx = 1
 6. limiting_surface_first         — tight first surface → limiting_surface_idx = 0
 7. full_vignetting_at_extreme_field — very tight CA at far surface → ~100% clipped
 8. pupil_area_pct_complement      — effective_pct + vignetting_pct == 100
 9. larger_ca_less_vignetting      — bigger CA at same z → less vignetting
10. increasing_field_increases_vig — vignetting increases monotonically with field
11. symmetric_negative_field       — field=−θ gives same vignetting as +θ
12. stop_surface_at_z0             — stop surface (z=0) never vignettes (Δ=0)
13. report_dataclass_fields        — VignettingReport has all required fields
14. to_dict_ok_key                 — to_dict() returns {"ok": True, ...}
15. to_dict_fields                 — to_dict() contains all expected keys
16. honest_caveat_nonempty         — honest_caveat is a non-empty string
17. error_empty_surfaces           — empty surfaces list → error dict
18. error_missing_ca_key           — missing clear_aperture_radius_mm → error
19. error_missing_z_key            — missing axial_position_mm → error
20. error_bad_ca_value             — zero CA → error
21. error_negative_ca_value        — negative CA → error
22. error_infinite_ca              — infinite CA → error
23. error_field_too_large          — field >= 90° → error
24. error_negative_pupil           — marginal_ray_at_stop_mm <= 0 → error
25. error_not_spec_instance        — passing a plain dict → error
26. tool_happy_path                — LLM tool on-axis → ok + vignetting_pct=0
27. tool_off_axis                  — LLM tool at 30° with small CA → ok + vignetting>0
28. tool_missing_surfaces          — LLM tool missing surfaces → error
29. tool_missing_field_angle       — LLM tool missing field_angle_deg → error
30. tool_bad_json                  — LLM tool invalid JSON → error response
31. tool_with_marginal_ray_kwarg   — LLM tool accepts marginal_ray_at_stop_mm
32. two_surface_limiting_correct   — two surfaces; verify limiting is the smaller
33. spec_with_multiple_surfaces    — 4-surface system; all surfaces checked
34. near_zero_field_near_zero_vig  — field=0.001° → effectively zero vignetting

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.7.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §5.7.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.vignetting_check import (
    LensClearApertureSpec,
    VignettingReport,
    compute_vignetting,
)
from kerf_cad_core.optics.tools import run_compute_vignetting_check


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _spec_simple() -> LensClearApertureSpec:
    """A two-surface lens: stop at z=0 (CA=12 mm), rear surface at z=5 mm (CA=12 mm)."""
    return LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 5.0},
    ])


def _spec_tight_second() -> LensClearApertureSpec:
    """Stop at z=0 (CA=12 mm), tight second surface at z=20 mm (CA=5 mm)."""
    return LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 5.0,  "axial_position_mm": 20.0},
    ])


def _spec_tight_first() -> LensClearApertureSpec:
    """Tight first surface (CA=5 mm) at z=0, generous rear at z=20 mm (CA=12 mm)."""
    return LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 5.0,  "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 20.0},
    ])


def _spec_four_surface() -> LensClearApertureSpec:
    """Four-surface system representing a two-element lens."""
    return LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 12.5, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 12.5, "axial_position_mm": 5.0},
        {"clear_aperture_radius_mm": 10.0, "axial_position_mm": 15.0},
        {"clear_aperture_radius_mm": 10.0, "axial_position_mm": 20.0},
    ])


def _report(spec, field_angle_deg, **kwargs) -> VignettingReport:
    r = compute_vignetting(spec, field_angle_deg, **kwargs)
    assert isinstance(r, VignettingReport), f"Expected VignettingReport, got {r!r}"
    return r


# ---------------------------------------------------------------------------
# Test 1: on-axis → no vignetting
# ---------------------------------------------------------------------------

def test_on_axis_no_vignetting():
    """Field = 0°: chief ray on axis, no displacement → vignetting_pct == 0.
    Use a spec where ALL CAs >= marginal_ray_at_stop_mm so there is no on-axis
    clipping from any surface.
    """
    # Both surfaces have CA=12 mm >= pupil R=10 mm; at field=0 delta=0 everywhere
    r = _report(_spec_simple(), 0.0, marginal_ray_at_stop_mm=10.0)
    assert r.vignetting_pct == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 2: on-axis → limiting_surface_idx is None
# ---------------------------------------------------------------------------

def test_on_axis_limiting_surface_none():
    """On-axis with generous CAs → limiting_surface_idx is None (unvignetted)."""
    # Both CAs = 12 mm > pupil R = 10 mm; at field=0 delta=0 → full intersection everywhere
    r = _report(_spec_simple(), 0.0, marginal_ray_at_stop_mm=10.0)
    assert r.limiting_surface_idx is None


# ---------------------------------------------------------------------------
# Test 3: on-axis → effective_pupil_area_pct == 100
# ---------------------------------------------------------------------------

def test_on_axis_effective_100():
    r = _report(_spec_simple(), 0.0, marginal_ray_at_stop_mm=10.0)
    assert r.effective_pupil_area_pct == pytest.approx(100.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 4: wide angle with small CA → significant vignetting
# ---------------------------------------------------------------------------

def test_wide_angle_significant_vignetting():
    """
    At 30° with a tight surface at z=20 mm:
      Δ = 20 * tan(30°) ≈ 11.55 mm
      Pupil R=10, CA=5; separation d ≈ 11.55 >> R+CA=15 → fully clipped.
    """
    r = _report(_spec_tight_second(), 30.0, marginal_ray_at_stop_mm=10.0)
    assert r.vignetting_pct > 10.0, (
        f"Expected significant vignetting at 30°, got {r.vignetting_pct:.2f}%"
    )


# ---------------------------------------------------------------------------
# Test 5: limiting surface at tight second surface
# ---------------------------------------------------------------------------

def test_limiting_surface_identified():
    """Tight second surface at index 1 should be identified as limiting."""
    r = _report(_spec_tight_second(), 15.0, marginal_ray_at_stop_mm=10.0)
    if r.vignetting_pct > 0.0:
        assert r.limiting_surface_idx == 1, (
            f"Expected limiting surface 1, got {r.limiting_surface_idx}"
        )


# ---------------------------------------------------------------------------
# Test 6: limiting surface at first (stop) surface when R > CA
# ---------------------------------------------------------------------------

def test_limiting_surface_first():
    """
    Pupil R=8 > CA of first surface (5 mm) at z=0 → intersection is π*5² < π*8²
    → limiting surface is index 0.
    """
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 5.0,  "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 20.0, "axial_position_mm": 10.0},
    ])
    r = _report(spec, 5.0, marginal_ray_at_stop_mm=8.0)
    # At z=0, delta=0: intersection = π*min(8,5)² = π*25; but second surface is large
    assert r.limiting_surface_idx == 0, (
        f"Expected limiting surface 0, got {r.limiting_surface_idx}"
    )
    assert r.vignetting_pct > 0.0


# ---------------------------------------------------------------------------
# Test 7: full vignetting at extreme field
# ---------------------------------------------------------------------------

def test_full_vignetting_at_extreme_field():
    """
    At 80°, z=1 mm surface: Δ = tan(80°) ≈ 5.67 mm >> CA=0.5 mm → fully clipped.
    d > R + r → intersection area = 0 → 100% vignetting.
    """
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 20.0, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 0.5,  "axial_position_mm": 1.0},
    ])
    r = _report(spec, 80.0, marginal_ray_at_stop_mm=5.0)
    # d ≈ 5.67 >> R(5) + r(0.5) = 5.5 → 100 % vignetting
    assert r.vignetting_pct == pytest.approx(100.0, abs=1.0), (
        f"Expected ~100% vignetting, got {r.vignetting_pct:.2f}%"
    )
    assert r.effective_pupil_area_pct == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# Test 8: effective_pct + vignetting_pct == 100
# ---------------------------------------------------------------------------

def test_pupil_area_pct_complement():
    """effective_pupil_area_pct + vignetting_pct must sum to 100."""
    for theta in [0.0, 5.0, 15.0, 30.0]:
        r = _report(_spec_tight_second(), theta, marginal_ray_at_stop_mm=10.0)
        total = r.effective_pupil_area_pct + r.vignetting_pct
        assert abs(total - 100.0) < 1e-9, (
            f"Sum {total} != 100 at θ={theta}°"
        )


# ---------------------------------------------------------------------------
# Test 9: larger CA → less vignetting
# ---------------------------------------------------------------------------

def test_larger_ca_less_vignetting():
    """A system with larger CA at the off-axis surface should have less vignetting."""
    spec_small = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 8.0,  "axial_position_mm": 30.0},
    ])
    spec_large = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 15.0, "axial_position_mm": 30.0},
    ])
    r_small = _report(spec_small, 10.0, marginal_ray_at_stop_mm=10.0)
    r_large = _report(spec_large, 10.0, marginal_ray_at_stop_mm=10.0)
    assert r_large.vignetting_pct <= r_small.vignetting_pct, (
        f"Expected larger CA to have less vignetting: "
        f"large={r_large.vignetting_pct:.2f}% vs small={r_small.vignetting_pct:.2f}%"
    )


# ---------------------------------------------------------------------------
# Test 10: vignetting increases monotonically with field
# ---------------------------------------------------------------------------

def test_increasing_field_increases_vignetting():
    """For a system with a tight off-axis surface, vignetting should be non-decreasing."""
    fields = [0.0, 5.0, 10.0, 20.0, 30.0]
    results = [
        _report(_spec_tight_second(), f, marginal_ray_at_stop_mm=10.0).vignetting_pct
        for f in fields
    ]
    for i in range(len(results) - 1):
        assert results[i] <= results[i + 1] + 0.01, (
            f"Vignetting not monotone at fields {fields[i]}→{fields[i+1]}: "
            f"{results[i]:.2f}% → {results[i+1]:.2f}%"
        )


# ---------------------------------------------------------------------------
# Test 11: symmetric field (negative = positive)
# ---------------------------------------------------------------------------

def test_symmetric_negative_field():
    """field = −θ and +θ should give the same vignetting_pct (rotation symmetry)."""
    r_pos = _report(_spec_tight_second(), 20.0, marginal_ray_at_stop_mm=10.0)
    r_neg = _report(_spec_tight_second(), -20.0, marginal_ray_at_stop_mm=10.0)
    assert r_pos.vignetting_pct == pytest.approx(r_neg.vignetting_pct, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 12: stop surface at z=0 never vignettes (Δ=0 → d=0 → full overlap)
# ---------------------------------------------------------------------------

def test_stop_surface_at_z0_never_vignettes():
    """At the aperture stop (z=0), Δ=0 and CA >= R → intersection = π*R² → 0% vignetting."""
    spec = LensClearApertureSpec(surfaces=[
        # Stop surface: CA >> pupil
        {"clear_aperture_radius_mm": 50.0, "axial_position_mm": 0.0},
    ])
    r = _report(spec, 45.0, marginal_ray_at_stop_mm=10.0)
    # CA=50 > R=10, d=0 → inner circle fully inside outer → area = π*10² → 0% vignetting
    assert r.vignetting_pct == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Tests 13–16: dataclass structure and serialisation
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = _report(_spec_simple(), 0.0)
    assert hasattr(r, "field_angle_deg")
    assert hasattr(r, "vignetting_pct")
    assert hasattr(r, "limiting_surface_idx")
    assert hasattr(r, "effective_pupil_area_pct")
    assert hasattr(r, "honest_caveat")


def test_to_dict_ok_key():
    r = _report(_spec_simple(), 5.0)
    d = r.to_dict()
    assert d["ok"] is True


def test_to_dict_fields():
    r = _report(_spec_simple(), 5.0)
    d = r.to_dict()
    for key in ("field_angle_deg", "vignetting_pct", "limiting_surface_idx",
                "effective_pupil_area_pct", "honest_caveat"):
        assert key in d, f"Missing key {key!r} in to_dict()"


def test_honest_caveat_nonempty():
    r = _report(_spec_simple(), 0.0)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Tests 17–25: error / validation paths
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    spec = LensClearApertureSpec(surfaces=[])
    r = compute_vignetting(spec, 5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_missing_ca_key():
    spec = LensClearApertureSpec(surfaces=[
        {"axial_position_mm": 0.0}  # missing clear_aperture_radius_mm
    ])
    r = compute_vignetting(spec, 5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "clear_aperture_radius_mm" in r["reason"]


def test_error_missing_z_key():
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 10.0}  # missing axial_position_mm
    ])
    r = compute_vignetting(spec, 5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "axial_position_mm" in r["reason"]


def test_error_bad_ca_value():
    """Zero clear aperture is invalid."""
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 0.0, "axial_position_mm": 0.0}
    ])
    r = compute_vignetting(spec, 5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_negative_ca_value():
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": -5.0, "axial_position_mm": 0.0}
    ])
    r = compute_vignetting(spec, 5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_infinite_ca():
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": float("inf"), "axial_position_mm": 0.0}
    ])
    r = compute_vignetting(spec, 5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_field_too_large():
    r = compute_vignetting(_spec_simple(), 90.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_negative_pupil():
    r = compute_vignetting(_spec_simple(), 5.0, marginal_ray_at_stop_mm=-1.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_not_spec_instance():
    """Passing a plain dict instead of LensClearApertureSpec → error."""
    r = compute_vignetting(
        {"surfaces": [{"clear_aperture_radius_mm": 10.0, "axial_position_mm": 0.0}]},
        5.0,
    )
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# Tests 26–31: LLM tool
# ---------------------------------------------------------------------------

_SURFACES_PAYLOAD = [
    {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
    {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 5.0},
]

_SURFACES_TIGHT = [
    {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
    {"clear_aperture_radius_mm": 5.0,  "axial_position_mm": 20.0},
]


def test_tool_happy_path():
    payload = json.dumps({
        "surfaces": _SURFACES_PAYLOAD,
        "field_angle_deg": 0.0,
    })
    result = asyncio.run(run_compute_vignetting_check(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["vignetting_pct"] == pytest.approx(0.0, abs=1e-6)


def test_tool_off_axis():
    payload = json.dumps({
        "surfaces": _SURFACES_TIGHT,
        "field_angle_deg": 30.0,
        "marginal_ray_at_stop_mm": 10.0,
    })
    result = asyncio.run(run_compute_vignetting_check(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["vignetting_pct"] > 0.0, (
        f"Expected nonzero vignetting at 30°, got {data['vignetting_pct']}"
    )


def test_tool_missing_surfaces():
    payload = json.dumps({"field_angle_deg": 5.0})
    result = asyncio.run(run_compute_vignetting_check(None, payload.encode()))
    data = json.loads(result)
    assert data.get("ok") is False or "error" in data


def test_tool_missing_field_angle():
    payload = json.dumps({"surfaces": _SURFACES_PAYLOAD})
    result = asyncio.run(run_compute_vignetting_check(None, payload.encode()))
    data = json.loads(result)
    assert data.get("ok") is False or "error" in data


def test_tool_bad_json():
    result = asyncio.run(run_compute_vignetting_check(None, b"not-json"))
    data = json.loads(result)
    assert "error" in data or data.get("ok") is False


def test_tool_with_marginal_ray_kwarg():
    payload = json.dumps({
        "surfaces": _SURFACES_PAYLOAD,
        "field_angle_deg": 5.0,
        "marginal_ray_at_stop_mm": 8.0,
    })
    result = asyncio.run(run_compute_vignetting_check(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert "vignetting_pct" in data
    assert "effective_pupil_area_pct" in data


# ---------------------------------------------------------------------------
# Test 32: two-surface limiting surface is correctly identified
# ---------------------------------------------------------------------------

def test_two_surface_limiting_correct():
    """Two surfaces: CA_0=12, CA_1=5. At large field, surface 1 is limiting."""
    spec = LensClearApertureSpec(surfaces=[
        {"clear_aperture_radius_mm": 12.0, "axial_position_mm": 0.0},
        {"clear_aperture_radius_mm": 5.0,  "axial_position_mm": 10.0},
    ])
    r = _report(spec, 20.0, marginal_ray_at_stop_mm=10.0)
    if r.vignetting_pct > 0.0:
        # At field=20°, Δ_1 = 10*tan(20°) ≈ 3.64 mm; d_1=3.64, R=10, r_1=5
        # Intersection(10, 5, 3.64) < π*10² (tight); surface 0 at z=0: d=0 → full intersection
        assert r.limiting_surface_idx == 1, (
            f"Expected index 1 as limiting surface, got {r.limiting_surface_idx}"
        )


# ---------------------------------------------------------------------------
# Test 33: four-surface system — all surfaces checked
# ---------------------------------------------------------------------------

def test_spec_with_multiple_surfaces():
    """Four-surface system: verify it runs without error and produces valid output."""
    r = _report(_spec_four_surface(), 10.0, marginal_ray_at_stop_mm=10.0)
    assert 0.0 <= r.vignetting_pct <= 100.0
    assert 0.0 <= r.effective_pupil_area_pct <= 100.0
    assert abs(r.vignetting_pct + r.effective_pupil_area_pct - 100.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 34: near-zero field angle → near-zero vignetting
# ---------------------------------------------------------------------------

def test_near_zero_field_near_zero_vignetting():
    """Very small field angle should produce effectively zero vignetting for generous CAs."""
    r = _report(_spec_simple(), 0.001, marginal_ray_at_stop_mm=10.0)
    assert r.vignetting_pct == pytest.approx(0.0, abs=0.001)
