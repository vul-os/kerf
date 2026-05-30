"""
Tests for kerf_cad_core.optics.seidel_aberrations -- Seidel third-order aberrations.

Test plan
---------
1.  thin_singlet_SI_sign        -- S_I > 0 for equiconvex lens (Welford sign convention)
2.  thin_singlet_SI_magnitude   -- S_I within plausible range for aperture=5 mm, f=100 mm
3.  thin_singlet_SII_nonzero    -- S_II nonzero at 5 deg field (coma exists)
4.  thin_singlet_SV_finite      -- S_V computed without NaN/inf
5.  flat_surface_zero_SI        -- flat surface (c=0) contributes zero SI
6.  flat_surface_zero_SIV       -- flat surface contributes zero SIV
7.  lagrange_invariant_nonzero  -- H is non-zero for nonzero aperture and field
8.  per_surface_sum_equals_total -- sum of per_surface SI_contrib = total S_I
9.  field_angle_scaling_SII     -- S_II scales with field angle (coma scales ~linearly)
10. field_angle_scaling_SIII    -- S_III scales with field angle squared
11. field_angle_scaling_SV      -- S_V scales with field angle cubed (approximately)
12. aperture_scaling_SI         -- S_I scales with aperture (SI ~ h^3 in paraxial limit)
13. plano_convex_vs_equiconvex  -- bending factor changes S_I
14. error_empty_surfaces        -- returns error dict for empty list
15. error_bad_surface           -- returns error dict for missing field
16. error_negative_n            -- returns error dict for n < 1
17. error_zero_aperture         -- returns error dict for aperture=0
18. report_dataclass_fields     -- SeidelReport has all five + H + total_wfe
19. to_dict_ok_key              -- SeidelReport.to_dict() has ok=True
20. honest_flag_in_dict         -- to_dict() includes honest_flag string
21. total_wfe_nonneg            -- total_wavefront_aberration_waves >= 0
22. cooke_triplet_SI_computed   -- Cooke triplet S_I is finite
23. cooke_triplet_SII_computed  -- Cooke triplet S_II is finite
24. plano_convex_vs_reversed    -- reversed plano-convex has different S_I
25. tool_happy_path             -- LLM tool returns ok JSON with S_I key
26. tool_missing_surfaces       -- LLM tool returns error for missing surfaces
27. tool_bad_json               -- LLM tool handles invalid JSON
28. tool_aperture_kwarg         -- tool accepts optional aperture kwarg
29. tool_field_angle_kwarg      -- tool accepts optional field_angle_deg kwarg
30. single_surface_SI_finite    -- single refracting surface SI is finite
31. chief_ray_zero_h_at_stop    -- chief ray height at first surface is exactly 0
32. SIV_zero_when_H_zero        -- S_IV is zero when field angle = 0 (H = 0)
33. SIV_petzval_flat_zero       -- flat surface contributes zero SIV

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §6.2, §6.4.
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., 1999, §5.3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.seidel_aberrations import SeidelReport, seidel_coefficients
from kerf_cad_core.optics.tools import run_seidel_aberrations


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

# Thin equiconvex singlet: n=1.5, f=100 mm, equal radii ±100 mm.
# 1/f = (n-1)*(1/R1 - 1/R2) = 0.5 * (1/100 + 1/100) = 0.01 => f=100 mm
_N = 1.5
_R = 100.0  # mm
_C1 = 1.0 / _R
_C2 = -1.0 / _R

EQUICONVEX_SINGLET = [
    {"c": _C1, "t": 0.0, "n": _N},
    {"c": _C2, "t": 0.0, "n": 1.0},
]

# Plano-convex, flat first: c1=0, c2=-1/((n-1)*f)=-1/50
PLANO_CONVEX_FLAT_FIRST = [
    {"c": 0.0, "t": 0.0, "n": _N},
    {"c": -1.0 / ((_N - 1.0) * 100.0), "t": 0.0, "n": 1.0},
]

# Plano-convex, curved first (reversed): c1=+1/50, c2=0
PLANO_CONVEX_CURVED_FIRST = [
    {"c": 1.0 / ((_N - 1.0) * 100.0), "t": 0.0, "n": _N},
    {"c": 0.0, "t": 0.0, "n": 1.0},
]


def _thin_lens_surfaces(power: float, n: float) -> list[dict]:
    """Two-surface symmetric thin lens element in air."""
    c = power / (2.0 * (n - 1.0))
    return [
        {"c": c, "t": 0.0, "n": n},
        {"c": -c, "t": 0.0, "n": 1.0},
    ]


# Cooke triplet (thin-lens approx): crown f=+75 / flint f=-39 / crown f=+75
_NC = 1.523
_NF = 1.617
COOKE_TRIPLET = (
    _thin_lens_surfaces(1.0 / 75.0, _NC)
    + _thin_lens_surfaces(-1.0 / 39.0, _NF)
    + _thin_lens_surfaces(1.0 / 75.0, _NC)
)


def _run_tool(args: dict) -> dict:
    return json.loads(asyncio.run(run_seidel_aberrations(None, json.dumps(args).encode())))


# ---------------------------------------------------------------------------
# 1. S_I sign: equiconvex singlet should have S_I > 0 (Welford convention)
# ---------------------------------------------------------------------------

def test_thin_singlet_SI_sign():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    assert isinstance(r, SeidelReport)
    # In Welford (1986) §6.2 convention, a standard converging singlet in air has S_I > 0
    # (marginal rays focus closer than paraxial focus = positive under-correction).
    assert r.S_I > 0.0, f"Expected S_I > 0 for equiconvex singlet, got {r.S_I}"


# ---------------------------------------------------------------------------
# 2. S_I magnitude is finite and in a plausible range
# ---------------------------------------------------------------------------

def test_thin_singlet_SI_magnitude():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=0.0)
    assert math.isfinite(r.S_I)
    assert math.isfinite(r.S_II)
    assert abs(r.S_I) < 10.0, f"S_I implausibly large: {r.S_I}"
    assert abs(r.S_I) > 0.0, "S_I should be nonzero for a refracting surface"


# ---------------------------------------------------------------------------
# 3. S_II nonzero at field angle (coma)
# ---------------------------------------------------------------------------

def test_thin_singlet_SII_nonzero():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    assert math.isfinite(r.S_II)
    assert abs(r.S_II) > 0.0, "S_II (coma) should be nonzero at 5 deg field"


# ---------------------------------------------------------------------------
# 4. S_V is finite
# ---------------------------------------------------------------------------

def test_thin_singlet_SV_finite():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    assert math.isfinite(r.S_V), f"S_V is not finite: {r.S_V}"


# ---------------------------------------------------------------------------
# 5. Flat surface contributes zero S_I
# ---------------------------------------------------------------------------

def test_flat_surface_zero_SI():
    flat = [{"c": 0.0, "t": 0.0, "n": 1.0}]
    r = seidel_coefficients(flat, aperture=1.0, field_angle_deg=5.0)
    assert isinstance(r, SeidelReport)
    assert r.S_I == pytest.approx(0.0, abs=1e-15)


# ---------------------------------------------------------------------------
# 6. Flat surface contributes zero S_IV
# ---------------------------------------------------------------------------

def test_flat_surface_zero_SIV():
    flat = [{"c": 0.0, "t": 0.0, "n": 1.5}, {"c": 0.0, "t": 0.0, "n": 1.0}]
    r = seidel_coefficients(flat, aperture=1.0, field_angle_deg=5.0)
    assert r.S_IV == pytest.approx(0.0, abs=1e-15)


# ---------------------------------------------------------------------------
# 7. Lagrange invariant H is nonzero for nonzero aperture and field
# ---------------------------------------------------------------------------

def test_lagrange_invariant_nonzero():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    assert abs(r.H) > 0.0, f"H should be nonzero, got {r.H}"


# ---------------------------------------------------------------------------
# 8. Sum of per-surface SI_contrib equals total S_I
# ---------------------------------------------------------------------------

def test_per_surface_sum_equals_total_SI():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    total = sum(s["SI_contrib"] for s in r.per_surface)
    assert total == pytest.approx(r.S_I, rel=1e-10)


# ---------------------------------------------------------------------------
# 9. S_II scales with field angle (~linear for 3rd order)
# ---------------------------------------------------------------------------

def test_field_angle_scaling_SII():
    r1 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    r2 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=10.0)
    if abs(r1.S_II) > 1e-20:
        ratio = r2.S_II / r1.S_II
        # Doubling field should roughly double S_II (Abar ~ field, so SII ~ field^1)
        assert 1.5 < abs(ratio) < 3.0, f"S_II field scaling ratio: {ratio}"


# ---------------------------------------------------------------------------
# 10. S_III scales with field angle squared
# ---------------------------------------------------------------------------

def test_field_angle_scaling_SIII():
    r1 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    r2 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=10.0)
    if abs(r1.S_III) > 1e-20:
        ratio = r2.S_III / r1.S_III
        # Doubling field -> ~4x S_III (Abar^2 ~ field^2)
        assert 3.0 < abs(ratio) < 6.0, f"S_III field^2 scaling ratio: {ratio}"


# ---------------------------------------------------------------------------
# 11. S_V approximate field-cubed scaling
# ---------------------------------------------------------------------------

def test_field_angle_scaling_SV():
    r1 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    r2 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=10.0)
    if abs(r1.S_V) > 1e-20:
        ratio = r2.S_V / r1.S_V
        # Doubling field -> ~8x S_V (distortion is cubic in field)
        assert 5.0 < abs(ratio) < 11.0, f"S_V field^3 scaling ratio: {ratio}"


# ---------------------------------------------------------------------------
# 12. S_I increases with aperture
# ---------------------------------------------------------------------------

def test_aperture_scaling_SI():
    r1 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=2.0, field_angle_deg=0.5)
    r2 = seidel_coefficients(EQUICONVEX_SINGLET, aperture=4.0, field_angle_deg=0.5)
    if abs(r1.S_I) > 1e-20:
        # |S_I| should increase significantly with aperture
        assert abs(r2.S_I) > abs(r1.S_I) * 1.5, \
            f"S_I should increase with aperture: r1={r1.S_I}, r2={r2.S_I}"


# ---------------------------------------------------------------------------
# 13. Plano-convex vs equiconvex: bending changes S_I
# ---------------------------------------------------------------------------

def test_plano_convex_vs_equiconvex():
    r_eq = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=0.5)
    r_pc = seidel_coefficients(PLANO_CONVEX_FLAT_FIRST, aperture=5.0, field_angle_deg=0.5)
    assert math.isfinite(r_pc.S_I)
    assert r_pc.S_I != pytest.approx(r_eq.S_I, rel=0.01), \
        "Plano-convex and equiconvex should have different S_I (shape factor matters)"


# ---------------------------------------------------------------------------
# 14. Error: empty surfaces list
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = seidel_coefficients([], aperture=1.0, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


# ---------------------------------------------------------------------------
# 15. Error: missing 'n' field in surface
# ---------------------------------------------------------------------------

def test_error_bad_surface():
    bad = [{"c": 0.01, "t": 0.0}]  # missing 'n'
    r = seidel_coefficients(bad, aperture=1.0, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 16. Error: n < 1.0
# ---------------------------------------------------------------------------

def test_error_negative_n():
    bad = [{"c": 0.01, "t": 0.0, "n": 0.5}]
    r = seidel_coefficients(bad, aperture=1.0, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 17. Error: zero aperture
# ---------------------------------------------------------------------------

def test_error_zero_aperture():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=0.0, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 18. SeidelReport has all expected attributes
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=1.0, field_angle_deg=5.0)
    assert isinstance(r, SeidelReport)
    for attr in ("S_I", "S_II", "S_III", "S_IV", "S_V", "H",
                 "total_wavefront_aberration_waves", "per_surface"):
        assert hasattr(r, attr), f"Missing attribute: {attr}"


# ---------------------------------------------------------------------------
# 19. to_dict() returns ok=True with expected keys
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=1.0, field_angle_deg=5.0)
    d = r.to_dict()
    assert d["ok"] is True
    assert "S_I" in d
    assert "S_V" in d


# ---------------------------------------------------------------------------
# 20. honest_flag present in to_dict()
# ---------------------------------------------------------------------------

def test_honest_flag_in_dict():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=1.0, field_angle_deg=5.0)
    d = r.to_dict()
    assert "honest_flag" in d
    assert "Third-order" in d["honest_flag"]


# ---------------------------------------------------------------------------
# 21. total_wavefront_aberration_waves >= 0
# ---------------------------------------------------------------------------

def test_total_wfe_nonneg():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    assert r.total_wavefront_aberration_waves >= 0.0


# ---------------------------------------------------------------------------
# 22. Cooke triplet S_I is finite
# ---------------------------------------------------------------------------

def test_cooke_triplet_SI_computed():
    r = seidel_coefficients(COOKE_TRIPLET, aperture=5.0, field_angle_deg=5.0)
    assert isinstance(r, SeidelReport)
    assert math.isfinite(r.S_I), f"Cooke triplet S_I not finite: {r.S_I}"


# ---------------------------------------------------------------------------
# 23. Cooke triplet S_II is finite
# ---------------------------------------------------------------------------

def test_cooke_triplet_SII_computed():
    r = seidel_coefficients(COOKE_TRIPLET, aperture=5.0, field_angle_deg=5.0)
    assert math.isfinite(r.S_II), f"Cooke triplet S_II not finite: {r.S_II}"


# ---------------------------------------------------------------------------
# 24. Reversed plano-convex has different S_I than original
# ---------------------------------------------------------------------------

def test_plano_convex_vs_reversed():
    r1 = seidel_coefficients(PLANO_CONVEX_FLAT_FIRST, aperture=5.0, field_angle_deg=0.5)
    r2 = seidel_coefficients(PLANO_CONVEX_CURVED_FIRST, aperture=5.0, field_angle_deg=0.5)
    assert r1.S_I != pytest.approx(r2.S_I, rel=0.01), \
        "Reversed plano-convex should differ in S_I (shape factor dependence)"


# ---------------------------------------------------------------------------
# 25. LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    d = _run_tool({"surfaces": EQUICONVEX_SINGLET, "aperture": 1.0, "field_angle_deg": 5.0})
    assert d["ok"] is True
    assert "S_I" in d
    assert "S_V" in d
    assert math.isfinite(d["S_I"])


# ---------------------------------------------------------------------------
# 26. LLM tool: missing surfaces
# ---------------------------------------------------------------------------

def test_tool_missing_surfaces():
    d = _run_tool({"aperture": 1.0})
    assert d["ok"] is False
    assert "surfaces" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 27. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    # err_payload returns {"error": ..., "code": "BAD_ARGS"} for parse errors
    result = json.loads(asyncio.run(run_seidel_aberrations(None, b"{bad json")))
    # Either {"ok": False} or {"error": ..., "code": "BAD_ARGS"} are acceptable errors
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error response, got: {result}"


# ---------------------------------------------------------------------------
# 28. LLM tool accepts aperture kwarg
# ---------------------------------------------------------------------------

def test_tool_aperture_kwarg():
    d = _run_tool({"surfaces": EQUICONVEX_SINGLET, "aperture": 2.0})
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 29. LLM tool accepts field_angle_deg kwarg
# ---------------------------------------------------------------------------

def test_tool_field_angle_kwarg():
    d = _run_tool({"surfaces": EQUICONVEX_SINGLET, "field_angle_deg": 10.0})
    assert d["ok"] is True
    assert math.isfinite(d["S_II"])


# ---------------------------------------------------------------------------
# 30. Single refracting surface: S_I is finite
# ---------------------------------------------------------------------------

def test_single_surface_SI_finite():
    r = seidel_coefficients([{"c": 0.02, "t": 0.0, "n": 1.5}], aperture=1.0, field_angle_deg=0.5)
    assert isinstance(r, SeidelReport)
    assert math.isfinite(r.S_I)


# ---------------------------------------------------------------------------
# 31. Chief ray height at first surface = 0 (stop at first surface)
# ---------------------------------------------------------------------------

def test_chief_ray_zero_h_at_stop():
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=5.0)
    assert r.per_surface[0]["ybar_mm"] == 0.0


# ---------------------------------------------------------------------------
# 32. S_IV = 0 when field angle = 0 (H = 0)
# ---------------------------------------------------------------------------

def test_SIV_zero_when_H_zero():
    # field_angle=0 => chief ray angle=0 => H=0 => SIV=0
    r = seidel_coefficients(EQUICONVEX_SINGLET, aperture=5.0, field_angle_deg=0.0)
    assert r.H == pytest.approx(0.0, abs=1e-15)
    assert r.S_IV == pytest.approx(0.0, abs=1e-15)


# ---------------------------------------------------------------------------
# 33. Flat surface contributes zero S_IV per-surface
# ---------------------------------------------------------------------------

def test_SIV_petzval_flat_zero():
    flat_glass = [{"c": 0.0, "t": 0.0, "n": 1.5}]
    r = seidel_coefficients(flat_glass, aperture=1.0, field_angle_deg=5.0)
    assert r.per_surface[0]["SIV_contrib"] == pytest.approx(0.0, abs=1e-15)
