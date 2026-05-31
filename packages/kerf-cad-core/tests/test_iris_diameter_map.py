"""
Tests for kerf_cad_core.optics.iris_diameter_map — OPTICS-IRIS-DIAMETER-MAP.

Test plan
----------
 1.  f4_50mm_diameter_exact           — EFL=50 mm, f/4: D = 12.5 mm
 2.  f14_50mm_diameter_exact          — EFL=50 mm, f/1.4: D ~= 35.714 mm
 3.  f14_fast_diameter_value          — 50mm/1.4 computed from surface data
 4.  f28_100mm_diameter               — 100 mm f/2.8: D = 35.714... mm
 5.  all_clear_no_clip                — all surfaces clear → clipped=False
 6.  tight_ca_clips_flag              — tight CA → clipped=True
 7.  clearance_ratio_gt1_passes       — clearance_ratio > 1 when h < CA_radius
 8.  clearance_ratio_lt1_clips        — clearance_ratio < 1 when h > CA_radius
 9.  stop_at_second_surface           — stop_surface_index=1 runs without error
10.  explicit_efl_overrides_computed  — target_efl_mm bypasses surface trace
11.  report_has_correct_fno           — effective_f_number == efl/iris_d
12.  report_has_surface_count         — len(surface_clearance_check) == n_surfaces
13.  no_ca_supplied_nan_ratio         — omitting clear_apertures_mm → ratio NaN
14.  error_empty_surfaces             — returns error for empty surfaces list
15.  error_bad_f_number               — f# <= 0 returns error
16.  error_stop_index_oob             — stop_surface_index out of range errors
17.  error_ca_length_mismatch         — CA list wrong length errors
18.  error_negative_efl_override      — target_efl_mm <= 0 errors
19.  tool_happy_path_f4               — LLM tool: f/4, 50 mm EFL
20.  tool_missing_lens_system         — LLM tool: missing lens_system_dict errors
21.  tool_missing_f_number            — LLM tool: missing target_f_number errors
22.  tool_bad_json                    — LLM tool: invalid JSON errors
23.  tool_explicit_efl                — LLM tool: target_efl_mm accepted
24.  threshold_exactly_at_095_flags   — h = 0.951 * CA_radius → flagged=True
25.  threshold_exactly_below_095_ok   — h = 0.949 * CA_radius → flagged=False

Oracle values:
  EFL=50 mm, f/4  → D = 12.5 mm   (Welford §3.4: D = EFL/N)
  EFL=50 mm, f/1.4 → D = 50/1.4 ≈ 35.714 mm

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.4.
Smith, W.J. — "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008, §6.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §6.4.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.iris_diameter_map import (
    IrisDiameterReport,
    IrisMapSpec,
    compute_iris_diameter,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _bk7_biconvex():
    """BK7 biconvex singlet: R1=+50, R2=-50, t=5 mm, n=1.5168.  EFL ~48.4 mm."""
    return [
        {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _thin_singlet_50mm():
    """
    Thin singlet chosen so EFL = 50 mm exactly (paraxial).
    R1=+50, R2=-50, t→0, n=1.5: 1/EFL = (n-1)(1/R1 - 1/R2) = 0.5*(1/50+1/50)=0.02 → EFL=50 mm.
    """
    return [
        {"c": 1.0 / 50.0, "t": 0.0, "n": 1.5},
        {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
    ]


def _thin_singlet_100mm():
    """Thin singlet: R1=+100, R2=-100, n=1.5 → EFL=100 mm."""
    return [
        {"c": 1.0 / 100.0, "t": 0.0, "n": 1.5},
        {"c": -1.0 / 100.0, "t": 0.0, "n": 1.0},
    ]


def _make_spec(surfaces, fno, *, ca=None, stop=0, efl_override=None, n_obj=1.0):
    lsd: dict = {"surfaces": surfaces, "stop_surface_index": stop, "n_object": n_obj}
    if ca is not None:
        lsd["clear_apertures_mm"] = ca
    kwargs: dict = {}
    if efl_override is not None:
        kwargs["target_efl_mm"] = efl_override
    return IrisMapSpec(lens_system_dict=lsd, target_f_number=fno, **kwargs)


# ---------------------------------------------------------------------------
# 1. Oracle: EFL=50 mm, f/4 → D = 12.5 mm
# ---------------------------------------------------------------------------

def test_f4_50mm_diameter_exact():
    """D = EFL / f# = 50 / 4 = 12.5 mm exactly."""
    spec = _make_spec(_thin_singlet_50mm(), 4.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    assert r.iris_diameter_mm == pytest.approx(12.5, rel=1e-4)


# ---------------------------------------------------------------------------
# 2. Oracle: EFL=50 mm, f/1.4 → D ≈ 35.714 mm
# ---------------------------------------------------------------------------

def test_f14_50mm_diameter_exact():
    """D = 50 / 1.4 = 35.714... mm (oracle)."""
    spec = _make_spec(_thin_singlet_50mm(), 1.4)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    expected = 50.0 / 1.4
    assert r.iris_diameter_mm == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. Fast f/1.4 lens: D computed from BK7 surface data (EFL ~48.4 mm)
# ---------------------------------------------------------------------------

def test_f14_fast_diameter_value():
    """Fast f/1.4: iris diameter computed from surface-derived EFL."""
    spec = _make_spec(_bk7_biconvex(), 1.4)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    # EFL for BK7 biconvex ~48.4 mm → D ~34.6 mm; just verify reasonable range
    assert 30.0 < r.iris_diameter_mm < 40.0
    assert r.effective_f_number == pytest.approx(1.4, rel=1e-4)


# ---------------------------------------------------------------------------
# 4. f/2.8 on 100 mm EFL lens
# ---------------------------------------------------------------------------

def test_f28_100mm_diameter():
    """100 mm / 2.8 = 35.714... mm."""
    spec = _make_spec(_thin_singlet_100mm(), 2.8)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    expected = 100.0 / 2.8
    assert r.iris_diameter_mm == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# 5. All surfaces clear → clipped=False
# ---------------------------------------------------------------------------

def test_all_clear_no_clip():
    """Generous CAs (50 mm diameter) → no surface clips the marginal ray."""
    ca = [50.0, 50.0]   # 50 mm diameter = 25 mm radius; far exceeds iris
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=ca)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    assert r.clipped is False
    for rec in r.surface_clearance_check:
        assert rec["flagged"] is False


# ---------------------------------------------------------------------------
# 6. Tight CA forces clip flag
# ---------------------------------------------------------------------------

def test_tight_ca_clips_flag():
    """CA diameter = 10 mm → radius 5 mm; iris stop radius = 12.5/2 = 6.25 mm → clips."""
    ca = [10.0, 10.0]   # 5 mm radius, iris D=12.5 → h=6.25 mm at stop → 6.25 > 0.95*5=4.75
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=ca)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    assert r.clipped is True


# ---------------------------------------------------------------------------
# 7. clearance_ratio > 1 when h < CA_radius
# ---------------------------------------------------------------------------

def test_clearance_ratio_gt1_passes():
    """Ratio = CA_radius / h > 1 when CA_radius > h."""
    ca = [50.0, 50.0]
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=ca)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    for rec in r.surface_clearance_check:
        assert rec["clearance_ratio"] > 1.0


# ---------------------------------------------------------------------------
# 8. clearance_ratio < 1 when h > CA_radius
# ---------------------------------------------------------------------------

def test_clearance_ratio_lt1_clips():
    """CA radius (4 mm) < marginal ray height at stop (6.25 mm) → ratio < 1."""
    ca = [8.0, 8.0]   # 4 mm radius
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=ca)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    # Stop surface (idx 0) h = iris_d/2 = 6.25 mm; CA_radius=4 mm → ratio=4/6.25=0.64
    stop_rec = r.surface_clearance_check[0]
    assert stop_rec["clearance_ratio"] < 1.0


# ---------------------------------------------------------------------------
# 9. Stop at second surface (index 1)
# ---------------------------------------------------------------------------

def test_stop_at_second_surface():
    """stop_surface_index=1 should run without error and produce a valid report."""
    spec = _make_spec(_bk7_biconvex(), 4.0, stop=1)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    assert r.iris_diameter_mm > 0.0
    assert len(r.surface_clearance_check) == 2


# ---------------------------------------------------------------------------
# 10. Explicit EFL override bypasses surface trace
# ---------------------------------------------------------------------------

def test_explicit_efl_overrides_computed():
    """Supply target_efl_mm=50.0 regardless of surface data → D=12.5 at f/4."""
    # Using BK7 biconvex (EFL ~48.4) but overriding to 50.0
    spec = _make_spec(_bk7_biconvex(), 4.0, efl_override=50.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    assert r.efl_mm == pytest.approx(50.0, rel=1e-9)
    assert r.iris_diameter_mm == pytest.approx(12.5, rel=1e-9)


# ---------------------------------------------------------------------------
# 11. effective_f_number == efl / iris_diameter_mm
# ---------------------------------------------------------------------------

def test_report_has_correct_fno():
    """effective_f_number must equal efl / iris_diameter_mm."""
    spec = _make_spec(_thin_singlet_50mm(), 4.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    expected_fno = r.efl_mm / r.iris_diameter_mm
    assert r.effective_f_number == pytest.approx(expected_fno, rel=1e-9)


# ---------------------------------------------------------------------------
# 12. surface_clearance_check has one entry per surface
# ---------------------------------------------------------------------------

def test_report_has_surface_count():
    """surface_clearance_check length equals number of surfaces."""
    spec = _make_spec(_bk7_biconvex(), 4.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    assert len(r.surface_clearance_check) == len(_bk7_biconvex())


# ---------------------------------------------------------------------------
# 13. No CA supplied → clearance_ratio is NaN
# ---------------------------------------------------------------------------

def test_no_ca_supplied_nan_ratio():
    """When clear_apertures_mm is omitted, all clearance_ratio values are NaN."""
    spec = _make_spec(_thin_singlet_50mm(), 4.0)  # no ca kwarg
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    for rec in r.surface_clearance_check:
        assert math.isnan(rec["clearance_ratio"])
    assert r.clipped is False


# ---------------------------------------------------------------------------
# 14. Error: empty surfaces list
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    lsd = {"surfaces": []}
    spec = IrisMapSpec(lens_system_dict=lsd, target_f_number=4.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


# ---------------------------------------------------------------------------
# 15. Error: bad f_number (<= 0)
# ---------------------------------------------------------------------------

def test_error_bad_f_number():
    spec = _make_spec(_thin_singlet_50mm(), 0.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "target_f_number" in r["reason"]


# ---------------------------------------------------------------------------
# 16. Error: stop_surface_index out of range
# ---------------------------------------------------------------------------

def test_error_stop_index_oob():
    spec = _make_spec(_thin_singlet_50mm(), 4.0, stop=99)
    r = compute_iris_diameter(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "stop_surface_index" in r["reason"]


# ---------------------------------------------------------------------------
# 17. Error: clear_apertures_mm length mismatch
# ---------------------------------------------------------------------------

def test_error_ca_length_mismatch():
    # 2 surfaces but only 1 CA entry
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=[30.0])
    r = compute_iris_diameter(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "clear_apertures_mm" in r["reason"]


# ---------------------------------------------------------------------------
# 18. Error: target_efl_mm <= 0
# ---------------------------------------------------------------------------

def test_error_negative_efl_override():
    spec = _make_spec(_thin_singlet_50mm(), 4.0, efl_override=-50.0)
    r = compute_iris_diameter(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# LLM tool tests
# ---------------------------------------------------------------------------

from kerf_cad_core.optics.tools import run_compute_iris_diameter_map  # noqa: E402


def _invoke(payload: dict) -> dict:
    return json.loads(
        asyncio.run(run_compute_iris_diameter_map(None, json.dumps(payload).encode()))
    )


_THIN_50 = [
    {"c": 0.02, "t": 0.0, "n": 1.5},
    {"c": -0.02, "t": 0.0, "n": 1.0},
]


# ---------------------------------------------------------------------------
# 19. Tool happy path f/4, 50 mm EFL
# ---------------------------------------------------------------------------

def test_tool_happy_path_f4():
    """Tool: thin singlet 50 mm, f/4 → iris = 12.5 mm."""
    data = _invoke({
        "lens_system_dict": {"surfaces": _THIN_50},
        "target_f_number": 4.0,
    })
    assert data.get("ok") is True
    assert data["iris_diameter_mm"] == pytest.approx(12.5, rel=1e-4)
    assert data["clipped"] is False


# ---------------------------------------------------------------------------
# 20. Tool missing lens_system_dict
# ---------------------------------------------------------------------------

def test_tool_missing_lens_system():
    data = _invoke({"target_f_number": 4.0})
    assert data.get("ok") is False


# ---------------------------------------------------------------------------
# 21. Tool missing target_f_number
# ---------------------------------------------------------------------------

def test_tool_missing_f_number():
    data = _invoke({"lens_system_dict": {"surfaces": _THIN_50}})
    assert data.get("ok") is False


# ---------------------------------------------------------------------------
# 22. Tool bad JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    raw = asyncio.run(run_compute_iris_diameter_map(None, b"not valid {{{"))
    data = json.loads(raw)
    assert data.get("ok") is False or data.get("code") == "BAD_ARGS" or "error" in data


# ---------------------------------------------------------------------------
# 23. Tool explicit EFL accepted
# ---------------------------------------------------------------------------

def test_tool_explicit_efl():
    data = _invoke({
        "lens_system_dict": {"surfaces": _THIN_50},
        "target_f_number": 4.0,
        "target_efl_mm": 50.0,
    })
    assert data.get("ok") is True
    assert data["efl_mm"] == pytest.approx(50.0, rel=1e-9)
    assert data["iris_diameter_mm"] == pytest.approx(12.5, rel=1e-9)


# ---------------------------------------------------------------------------
# 24. Exactly-at-threshold: h = 0.951 × CA_radius → flagged=True
# ---------------------------------------------------------------------------

def test_threshold_exactly_at_095_flags():
    """
    D = 50/4 = 12.5 mm → h_stop = 6.25 mm.
    Set CA_radius such that h = 0.951 × CA_radius:
      CA_radius = 6.25 / 0.951 ≈ 6.572 mm → CA_diam ≈ 13.143 mm.
    """
    ca_r = 6.25 / 0.951
    ca_d = ca_r * 2.0
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=[ca_d, ca_d])
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    # h at stop = 6.25 mm, CA_radius = 6.572 mm → 6.25 > 0.95*6.572=6.243 → flagged
    stop_rec = r.surface_clearance_check[0]
    assert stop_rec["flagged"] is True
    assert r.clipped is True


# ---------------------------------------------------------------------------
# 25. Just below threshold: h = 0.949 × CA_radius → flagged=False
# ---------------------------------------------------------------------------

def test_threshold_exactly_below_095_ok():
    """
    D = 50/4 = 12.5 mm → h_stop = 6.25 mm.
    Set CA_radius = 6.25 / 0.949 ≈ 6.586 mm → CA_diam ≈ 13.171 mm.
    h = 0.949 × CA_radius < 0.95 × CA_radius → not flagged.
    """
    ca_r = 6.25 / 0.949
    ca_d = ca_r * 2.0
    spec = _make_spec(_thin_singlet_50mm(), 4.0, ca=[ca_d, ca_d])
    r = compute_iris_diameter(spec)
    assert isinstance(r, IrisDiameterReport)
    stop_rec = r.surface_clearance_check[0]
    # 6.25 < 0.95 * 6.586 = 6.257 → not flagged (just barely OK)
    assert stop_rec["flagged"] is False
    assert r.clipped is False
