"""
Tests for kerf_cad_core.optics.coma_compute — OPTICS-COMA-COMPUTE.

Test plan
---------
1.  flat_surface_coma_zero              -- afocal flat stack returns coma=0
2.  aplanatic_coma_zero                 -- afocal two-surface flat stack returns coma=0
3.  biconvex_coma_nonzero               -- BK7 biconvex at field > 0 gives finite coma
4.  biconvex_14deg_coma_above_1um       -- depth bar: coma > 1 μm at 14°
5.  onaxis_coma_near_zero               -- coma at 0° field is near zero
6.  field_angle_scaling_linear          -- total_coma scales ~ linearly with field angle
7.  tan_coma_three_times_sag            -- tangential_coma == 3 × sagittal_coma
8.  total_coma_nonneg                   -- total_coma >= 0 for all valid fields
9.  seidel_match_small_field            -- Seidel match < 50% at 5° field
10. seidel_prediction_nonneg            -- seidel_prediction_mm >= 0
11. coma_increases_with_aperture        -- larger aperture → larger coma
12. report_has_all_fields               -- ComaReport has per_field, S_II, aperture_radius_mm
13. per_field_has_all_keys              -- per-field dict has all required keys
14. to_dict_ok_true                     -- to_dict() returns ok=True
15. honest_flag_present                 -- honest_flag in to_dict()
16. honest_flag_mentions_third_order    -- honest_flag mentions "Third-order"
17. error_empty_stack                   -- error dict for empty stack
18. error_bad_surface                   -- error dict for missing 'n'
19. error_bad_n                         -- error dict for n < 1
20. error_bad_aperture                  -- error dict for aperture=0
21. error_bad_n_pupil_rays              -- error dict for n_pupil_rays=2
22. error_empty_field_list              -- error dict for empty field_angles_deg
23. multiple_field_angles               -- multiple field angles in one call
24. n_rays_valid_positive               -- n_rays_valid > 0 for valid stack
25. seidel_S_II_stored                  -- S_II stored in report equals seidel_coefficients result
26. tool_happy_path                     -- LLM tool returns ok JSON
27. tool_missing_surfaces               -- LLM tool error for missing surfaces
28. tool_missing_field_angles           -- LLM tool error for missing field_angles_deg
29. tool_bad_json                       -- LLM tool error for invalid JSON
30. tool_optional_n_pupil_rays          -- LLM tool accepts n_pupil_rays kwarg
31. tool_optional_aperture              -- LLM tool accepts aperture_radius_mm kwarg
32. cooke_triplet_coma_finite           -- Cooke triplet coma is finite
33. single_surface_coma_finite          -- single refracting surface gives finite coma

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §11.4.
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., 1999, §5.3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.coma_compute import ComaReport, compute_coma
from kerf_cad_core.optics.seidel_aberrations import seidel_coefficients


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Thin equiconvex singlet: n=1.5, f=100 mm
_N = 1.5
_R = 100.0
EQUICONVEX_SINGLET = [
    {"c": 1.0 / _R, "t": 0.0, "n": _N},
    {"c": -1.0 / _R, "t": 0.0, "n": 1.0},
]

# BK7 biconvex: R=±50 mm, t=5 mm, n=1.5168
BK7_BICONVEX = [
    {"c": 1.0 / 50.0, "t": 5.0, "n": 1.5168},
    {"c": -1.0 / 50.0, "t": 0.0, "n": 1.0},
]

# Flat single surface (c=0 → zero power → afocal)
FLAT_SURFACE = [{"c": 0.0, "t": 0.0, "n": 1.5}]

# Cooke triplet (thin-lens approx): crown f=+75 / flint f=-39 / crown f=+75
_NC, _NF = 1.523, 1.617


def _thin(power: float, n: float) -> list[dict]:
    c = power / (2.0 * (n - 1.0))
    return [{"c": c, "t": 0.0, "n": n}, {"c": -c, "t": 0.0, "n": 1.0}]


COOKE_TRIPLET = _thin(1.0 / 75.0, _NC) + _thin(-1.0 / 39.0, _NF) + _thin(1.0 / 75.0, _NC)


def _run_tool(args: dict) -> dict:
    from kerf_cad_core.optics.tools import run_optics_compute_coma
    return json.loads(asyncio.run(run_optics_compute_coma(None, json.dumps(args).encode())))


# ---------------------------------------------------------------------------
# 1. Flat surface → afocal → coma = 0
# ---------------------------------------------------------------------------

def test_flat_surface_coma_zero():
    # Flat single surface: zero power, afocal → compute_coma returns 0 by convention
    r = compute_coma(FLAT_SURFACE, [5.0], n_pupil_rays=8, aperture_radius_mm=1.0)
    assert isinstance(r, ComaReport)
    fp = r.per_field[0]
    assert fp.total_coma_mm == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# 2. Aplanatic flat two-surface system → afocal → coma = 0
# ---------------------------------------------------------------------------

def test_aplanatic_coma_zero():
    flat2 = [{"c": 0.0, "t": 0.0, "n": 1.5}, {"c": 0.0, "t": 0.0, "n": 1.0}]
    r = compute_coma(flat2, [5.0], n_pupil_rays=8, aperture_radius_mm=1.0)
    assert isinstance(r, ComaReport)
    fp = r.per_field[0]
    assert fp.total_coma_mm == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# 3. BK7 biconvex at non-zero field → finite nonzero coma
# ---------------------------------------------------------------------------

def test_biconvex_coma_nonzero():
    r = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=5.0)
    assert isinstance(r, ComaReport)
    fp = r.per_field[0]
    assert math.isfinite(fp.total_coma_mm), f"total_coma not finite: {fp.total_coma_mm}"
    assert fp.total_coma_mm > 0.0, f"Expected nonzero coma, got {fp.total_coma_mm}"


# ---------------------------------------------------------------------------
# 4. Depth bar: BK7 biconvex at 14° → coma > 1 μm
# ---------------------------------------------------------------------------

def test_biconvex_14deg_coma_above_1um():
    r = compute_coma(BK7_BICONVEX, [14.0], aperture_radius_mm=5.0)
    fp = r.per_field[0]
    assert math.isfinite(fp.total_coma_mm), "total_coma must be finite at 14°"
    assert fp.total_coma_mm > 1e-3, (
        f"Depth bar failed: coma at 14° should be > 1 μm (1e-3 mm), "
        f"got {fp.total_coma_mm:.6f} mm"
    )


# ---------------------------------------------------------------------------
# 5. On-axis (0°) coma → near zero (y_chief=0 → seidel_pred=0 → coma≈0)
# ---------------------------------------------------------------------------

def test_onaxis_coma_near_zero():
    r = compute_coma(BK7_BICONVEX, [0.0], aperture_radius_mm=5.0)
    fp = r.per_field[0]
    assert math.isfinite(fp.total_coma_mm)
    assert abs(fp.total_coma_mm) < 1e-3, f"On-axis coma should be near zero, got {fp.total_coma_mm}"


# ---------------------------------------------------------------------------
# 6. Field-angle scaling: coma at 10° > coma at 5° (linear scaling)
# ---------------------------------------------------------------------------

def test_field_angle_scaling_linear():
    # Use BK7 which has well-conditioned coma (strong S_II, 3rd-order dominates at ≤10°)
    r5  = compute_coma(BK7_BICONVEX, [5.0],  aperture_radius_mm=5.0)
    r10 = compute_coma(BK7_BICONVEX, [10.0], aperture_radius_mm=5.0)
    c5  = r5.per_field[0].total_coma_mm
    c10 = r10.per_field[0].total_coma_mm
    if c5 > 1e-8:
        # Doubling field should roughly double coma (tan(θ) scaling)
        ratio = c10 / c5
        assert 1.5 < ratio < 4.0, f"Field scaling ratio not in [1.5, 4.0]: {ratio}"


# ---------------------------------------------------------------------------
# 7. Tangential coma == 3 × sagittal coma (by construction, Welford §11.4)
# ---------------------------------------------------------------------------

def test_tan_coma_three_times_sag():
    r = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=5.0)
    fp = r.per_field[0]
    if fp.tangential_coma_mm > 1e-8:
        ratio = fp.tangential_coma_mm / fp.sagittal_coma_mm
        assert abs(ratio - 3.0) < 0.01, f"tan/sag ratio should be exactly 3.0, got {ratio}"


# ---------------------------------------------------------------------------
# 8. total_coma >= 0 for all valid fields
# ---------------------------------------------------------------------------

def test_total_coma_nonneg():
    r = compute_coma(BK7_BICONVEX, [0.0, 5.0, 10.0, 14.0], aperture_radius_mm=5.0)
    for fp in r.per_field:
        if math.isfinite(fp.total_coma_mm):
            assert fp.total_coma_mm >= 0.0, f"total_coma < 0 at {fp.field_angle_deg}°"


# ---------------------------------------------------------------------------
# 9. Seidel match within 50% at 5° field
# ---------------------------------------------------------------------------

def test_seidel_match_small_field():
    # Use BK7 where 3rd-order dominates and Seidel formula converges well
    r = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=5.0)
    fp = r.per_field[0]
    if math.isfinite(fp.seidel_match_fraction):
        assert fp.seidel_match_fraction < 0.10, (
            f"Seidel match fraction at 5° (BK7) should be < 10%, got {fp.seidel_match_fraction:.4f}"
        )


# ---------------------------------------------------------------------------
# 10. seidel_prediction_mm >= 0
# ---------------------------------------------------------------------------

def test_seidel_prediction_nonneg():
    r = compute_coma(BK7_BICONVEX, [5.0, 10.0], aperture_radius_mm=5.0)
    for fp in r.per_field:
        if math.isfinite(fp.seidel_prediction_mm):
            assert fp.seidel_prediction_mm >= 0.0


# ---------------------------------------------------------------------------
# 11. Larger aperture → larger coma
# ---------------------------------------------------------------------------

def test_coma_increases_with_aperture():
    r1 = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=1.0)
    r2 = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=5.0)
    c1 = r1.per_field[0].total_coma_mm
    c2 = r2.per_field[0].total_coma_mm
    if c1 > 1e-10:
        assert c2 > c1, f"Larger aperture should give larger coma: c1={c1:.6f}, c2={c2:.6f}"


# ---------------------------------------------------------------------------
# 12. ComaReport has expected attributes
# ---------------------------------------------------------------------------

def test_report_has_all_fields():
    r = compute_coma(BK7_BICONVEX, [5.0])
    assert isinstance(r, ComaReport)
    assert hasattr(r, "per_field")
    assert hasattr(r, "S_II")
    assert hasattr(r, "aperture_radius_mm")
    assert hasattr(r, "honest_flag")


# ---------------------------------------------------------------------------
# 13. per-field dict has all required keys
# ---------------------------------------------------------------------------

def test_per_field_has_all_keys():
    r = compute_coma(BK7_BICONVEX, [5.0])
    d = r.per_field[0].to_dict()
    for key in (
        "field_angle_deg", "tangential_coma_mm", "sagittal_coma_mm",
        "total_coma_mm", "seidel_prediction_mm", "chief_ray_y_mm", "n_rays_valid",
    ):
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 14. to_dict() returns ok=True
# ---------------------------------------------------------------------------

def test_to_dict_ok_true():
    r = compute_coma(BK7_BICONVEX, [5.0])
    d = r.to_dict()
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 15. honest_flag in to_dict()
# ---------------------------------------------------------------------------

def test_honest_flag_present():
    r = compute_coma(BK7_BICONVEX, [5.0])
    d = r.to_dict()
    assert "honest_flag" in d
    assert len(d["honest_flag"]) > 10


# ---------------------------------------------------------------------------
# 16. honest_flag mentions "Third-order"
# ---------------------------------------------------------------------------

def test_honest_flag_mentions_third_order():
    r = compute_coma(BK7_BICONVEX, [5.0])
    d = r.to_dict()
    assert "Third-order" in d["honest_flag"] or "third-order" in d["honest_flag"]


# ---------------------------------------------------------------------------
# 17. Error: empty stack
# ---------------------------------------------------------------------------

def test_error_empty_stack():
    r = compute_coma([], [5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "stack" in r["reason"]


# ---------------------------------------------------------------------------
# 18. Error: bad surface (missing 'n')
# ---------------------------------------------------------------------------

def test_error_bad_surface():
    r = compute_coma([{"c": 0.01, "t": 0.0}], [5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 19. Error: n < 1
# ---------------------------------------------------------------------------

def test_error_bad_n():
    r = compute_coma([{"c": 0.01, "t": 0.0, "n": 0.5}], [5.0])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 20. Error: aperture_radius_mm = 0
# ---------------------------------------------------------------------------

def test_error_bad_aperture():
    r = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=0.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 21. Error: n_pupil_rays < 4
# ---------------------------------------------------------------------------

def test_error_bad_n_pupil_rays():
    r = compute_coma(BK7_BICONVEX, [5.0], n_pupil_rays=2)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 22. Error: empty field list
# ---------------------------------------------------------------------------

def test_error_empty_field_list():
    r = compute_coma(BK7_BICONVEX, [])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 23. Multiple field angles in one call
# ---------------------------------------------------------------------------

def test_multiple_field_angles():
    r = compute_coma(BK7_BICONVEX, [0.0, 5.0, 10.0, 14.0], aperture_radius_mm=5.0)
    assert isinstance(r, ComaReport)
    assert len(r.per_field) == 4
    for fp in r.per_field:
        assert math.isfinite(fp.total_coma_mm)


# ---------------------------------------------------------------------------
# 24. n_rays_valid > 0 for a valid stack
# ---------------------------------------------------------------------------

def test_n_rays_valid_positive():
    r = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=5.0)
    assert r.per_field[0].n_rays_valid > 0


# ---------------------------------------------------------------------------
# 25. S_II in report matches seidel_coefficients
# ---------------------------------------------------------------------------

def test_seidel_S_II_stored():
    ap = 5.0
    r = compute_coma(BK7_BICONVEX, [5.0], aperture_radius_mm=ap)
    seidel = seidel_coefficients(BK7_BICONVEX, aperture=ap, field_angle_deg=5.0)
    assert math.isfinite(r.S_II)
    assert r.S_II == pytest.approx(seidel.S_II, rel=1e-8)


# ---------------------------------------------------------------------------
# 26. LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    d = _run_tool({
        "surfaces": BK7_BICONVEX,
        "field_angles_deg": [5.0, 10.0],
        "aperture_radius_mm": 5.0,
    })
    assert d["ok"] is True
    assert "per_field" in d
    assert len(d["per_field"]) == 2
    assert math.isfinite(d["per_field"][0]["total_coma_mm"])


# ---------------------------------------------------------------------------
# 27. LLM tool: missing surfaces
# ---------------------------------------------------------------------------

def test_tool_missing_surfaces():
    d = _run_tool({"field_angles_deg": [5.0]})
    assert d["ok"] is False
    assert "surfaces" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 28. LLM tool: missing field_angles_deg
# ---------------------------------------------------------------------------

def test_tool_missing_field_angles():
    d = _run_tool({"surfaces": BK7_BICONVEX})
    assert d["ok"] is False
    assert "field_angles_deg" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 29. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    from kerf_cad_core.optics.tools import run_optics_compute_coma
    result = json.loads(asyncio.run(run_optics_compute_coma(None, b"{bad json")))
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error response, got: {result}"


# ---------------------------------------------------------------------------
# 30. LLM tool accepts n_pupil_rays kwarg
# ---------------------------------------------------------------------------

def test_tool_optional_n_pupil_rays():
    d = _run_tool({
        "surfaces": BK7_BICONVEX,
        "field_angles_deg": [5.0],
        "n_pupil_rays": 8,
    })
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 31. LLM tool accepts aperture_radius_mm kwarg
# ---------------------------------------------------------------------------

def test_tool_optional_aperture():
    d = _run_tool({
        "surfaces": BK7_BICONVEX,
        "field_angles_deg": [5.0],
        "aperture_radius_mm": 3.0,
    })
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 32. Cooke triplet coma is finite
# ---------------------------------------------------------------------------

def test_cooke_triplet_coma_finite():
    r = compute_coma(COOKE_TRIPLET, [5.0], aperture_radius_mm=2.0)
    assert isinstance(r, ComaReport)
    fp = r.per_field[0]
    assert math.isfinite(fp.total_coma_mm), f"Cooke triplet coma not finite: {fp.total_coma_mm}"


# ---------------------------------------------------------------------------
# 33. Single refracting surface coma is finite
# ---------------------------------------------------------------------------

def test_single_surface_coma_finite():
    single = [{"c": 0.02, "t": 0.0, "n": 1.5}]
    r = compute_coma(single, [5.0], aperture_radius_mm=1.0)
    assert isinstance(r, ComaReport)
    fp = r.per_field[0]
    assert math.isfinite(fp.total_coma_mm), f"Single surface coma not finite: {fp.total_coma_mm}"
