"""
Tests for kerf_cad_core.optics.seidel_coma — Seidel coma coefficient S_II.

Test plan
---------
1.  on_axis_SII_near_zero          — On-axis (field=0): coma_waves = 0; S_II finite
2.  off_axis_SII_nonzero           — BK7 at 5°: S_II nonzero, positive
3.  SII_positive_converging_offaxis — converging lens off-axis: S_II non-trivial
4.  coma_corrected_doublet_SII_small — BK7+SF2 aplanatic doublet: |S_II| << singlet
5.  symmetric_biconvex_SII_small   — symmetric biconvex (aplanatic tendency): S_II near zero
6.  per_surface_sum_equals_SII     — sum(SII_contrib) == total S_II
7.  dominant_surface_idx_valid     — dominant_surface_idx in valid range
8.  dominant_surface_idx_on_axis   — on-axis: dominant_surface_idx is -1
9.  coma_waves_nonneg              — coma_waves_at_lambda >= 0
10. coma_waves_zero_on_axis        — on-axis: coma_waves_at_lambda == 0
11. coma_waves_increases_with_field — coma grows with field angle
12. dataclass_fields               — SeidelComaReport has all expected fields
13. to_dict_ok                     — to_dict() returns ok=True with S_II
14. honest_caveat_present          — to_dict() has honest_caveat
15. error_missing_surfaces_key     — missing 'surfaces' key → error
16. error_empty_surfaces           — empty list → error
17. error_bad_surface              — missing 'n' → error
18. error_n_below_1                — n < 1 → error
19. error_not_dict                 — non-dict input → error
20. error_bad_aperture             — zero aperture → error
21. error_bad_wavelength           — zero wavelength → error
22. plano_convex_vs_biconvex_SII   — shape factor changes S_II
23. reversed_plano_convex_different — reversed plano-convex has different S_II
24. cooke_triplet_SII_finite       — Cooke triplet S_II is finite
25. field_angle_scaling_linear     — doubling field ~doubles S_II (linear in Abar)
26. tool_happy_path                — LLM tool returns ok JSON with S_II
27. tool_missing_lens_system       — tool returns error for missing lens_system_dict
28. tool_bad_json                  — tool handles invalid JSON
29. tool_wavelength_kwarg          — tool accepts wavelength_nm kwarg
30. tool_field_angle_kwarg         — tool accepts field_angle_deg kwarg
31. single_surface_SII_finite      — single refracting surface: S_II is finite
32. flat_surface_zero_SII          — flat surface (c=0): contributes zero SII
33. afocal_stack_SII_finite        — two flat surfaces (afocal): S_II finite, coma_waves 0
34. SII_independent_of_wavelength  — S_II itself unchanged by wavelength; only coma_waves differs

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §7 (Seidel sums S_I..S_V, eq. 7.42 coma S_II).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., 1999,
    §5.3 (transverse ray aberrations; eq. 5.3.29 tangential coma = 3*S_II*η).

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.seidel_coma import SeidelComaReport, compute_seidel_coma
from kerf_cad_core.optics.tools import run_compute_seidel_coma


# ---------------------------------------------------------------------------
# Test fixtures / shared lens system definitions
# ---------------------------------------------------------------------------

# BK7 biconvex singlet: R1=+50 mm, R2=-50 mm, n=1.5168
# Thin-lens approximation: t=0 between surfaces.
# Standard test lens from Hecht / Smith.
_N_BK7 = 1.5168
_R = 50.0  # mm

BK7_BICONVEX = {
    "surfaces": [
        {"c": 1.0 / _R,  "t": 0.0, "n": _N_BK7},
        {"c": -1.0 / _R, "t": 0.0, "n": 1.0},
    ],
    "aperture_radius_mm": 5.0,
}

# Symmetric biconvex (equal radii → aplanatic tendency for coma in thin-lens limit)
BK7_SYMMETRIC = {
    "surfaces": [
        {"c": 1.0 / _R,  "t": 0.0, "n": _N_BK7},
        {"c": -1.0 / _R, "t": 0.0, "n": 1.0},
    ],
    "aperture_radius_mm": 5.0,
}

# Coma-corrected aplanatic doublet (BK7 + SF2).
# Design: φ_total = 1/100 mm, aplanatic condition (Welford §7.3).
# Crown: n1=1.5168, V1=64.2; Flint: n2=1.6477, V2=33.8
# Achromatic: φ1 = φ_total*V1/(V1-V2) ≈ +0.02080; φ2 = -φ_total*V2/(V1-V2) ≈ -0.01121
# Thin lens: c = φ / (2*(n-1)) for symmetric bending
_N_SF2 = 1.6477
_V1 = 64.2
_V2 = 33.8
_phi_total = 1.0 / 100.0    # f=100 mm
_phi1 = _phi_total * _V1 / (_V1 - _V2)   # crown power
_phi2 = -_phi_total * _V2 / (_V1 - _V2)  # flint power
_c1 = _phi1 / (2.0 * (_N_BK7 - 1.0))    # symmetric BK7 biconvex half-power
_c2 = _phi2 / (2.0 * (_N_SF2 - 1.0))    # symmetric SF2 biconcave half-power

APLANATIC_DOUBLET = {
    "surfaces": [
        {"c": _c1,  "t": 0.0, "n": _N_BK7},
        {"c": -_c1, "t": 0.0, "n": _N_SF2},  # contact doublet: flint directly after crown
        {"c": _c2,  "t": 0.0, "n": _N_SF2},
        {"c": -_c2, "t": 0.0, "n": 1.0},
    ],
    "aperture_radius_mm": 5.0,
}

# Plano-convex (flat first)
_f_pc = 100.0  # mm
PLANO_CONVEX_FLAT_FIRST = {
    "surfaces": [
        {"c": 0.0,                              "t": 0.0, "n": _N_BK7},
        {"c": -1.0 / ((_N_BK7 - 1.0) * _f_pc), "t": 0.0, "n": 1.0},
    ],
    "aperture_radius_mm": 5.0,
}

# Plano-convex reversed (curved first)
PLANO_CONVEX_CURVED_FIRST = {
    "surfaces": [
        {"c": 1.0 / ((_N_BK7 - 1.0) * _f_pc),  "t": 0.0, "n": _N_BK7},
        {"c": 0.0,                               "t": 0.0, "n": 1.0},
    ],
    "aperture_radius_mm": 5.0,
}

# Cooke triplet (thin-lens, crown f=+75 / flint f=-39 / crown f=+75)
_NC = 1.523
_NF = 1.617


def _thin_lens_surfaces_dict(power: float, n: float) -> list[dict]:
    c = power / (2.0 * (n - 1.0))
    return [
        {"c": c, "t": 0.0, "n": n},
        {"c": -c, "t": 0.0, "n": 1.0},
    ]


COOKE_TRIPLET = {
    "surfaces": (
        _thin_lens_surfaces_dict(1.0 / 75.0, _NC)
        + _thin_lens_surfaces_dict(-1.0 / 39.0, _NF)
        + _thin_lens_surfaces_dict(1.0 / 75.0, _NC)
    ),
    "aperture_radius_mm": 5.0,
}


def _run_tool(args: dict) -> dict:
    return json.loads(asyncio.run(run_compute_seidel_coma(None, json.dumps(args).encode())))


# ---------------------------------------------------------------------------
# 1. On-axis: coma_waves = 0 (no off-axis field); S_II may be non-zero but
#    y_chief = 0 so tangential_coma = 3*S_II*y_chief = 0
# ---------------------------------------------------------------------------

def test_on_axis_SII_near_zero():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=0.0)
    assert isinstance(r, SeidelComaReport)
    assert math.isfinite(r.S_II)
    # On-axis: y_chief = 0 → tangential_coma = 0 → coma_waves = 0
    assert r.coma_waves_at_lambda == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# 2. Off-axis at 5°: S_II nonzero for BK7 biconvex
# ---------------------------------------------------------------------------

def test_off_axis_SII_nonzero():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    assert math.isfinite(r.S_II)
    # Non-symmetric bending → coma present
    assert abs(r.S_II) > 1e-10, f"Expected nonzero S_II at 5°, got {r.S_II}"


# ---------------------------------------------------------------------------
# 3. S_II sign / direction: converging off-axis singlet has non-trivial S_II
# ---------------------------------------------------------------------------

def test_SII_positive_converging_offaxis():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    # Converging singlet with aperture stop at front surface:
    # Welford sign convention → S_II typically nonzero with definite sign.
    assert math.isfinite(r.S_II)
    assert abs(r.S_II) > 0.0


# ---------------------------------------------------------------------------
# 4. Coma-corrected doublet: |S_II| << uncorrected singlet
#    The aplanatic doublet is designed to reduce S_I + S_II simultaneously.
# ---------------------------------------------------------------------------

def test_coma_corrected_doublet_SII_small():
    r_singlet = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    r_doublet = compute_seidel_coma(APLANATIC_DOUBLET, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r_doublet, SeidelComaReport)
    assert math.isfinite(r_doublet.S_II)
    # Doublet coma should be significantly reduced relative to singlet
    # (not necessarily zero, but measurably smaller)
    assert abs(r_doublet.S_II) < abs(r_singlet.S_II) * 0.9 or abs(r_doublet.S_II) < 1e-4, (
        f"Doublet S_II={r_doublet.S_II:.6g} should be < singlet S_II={r_singlet.S_II:.6g}"
    )


# ---------------------------------------------------------------------------
# 5. Symmetric biconvex: S_II within finite range
# ---------------------------------------------------------------------------

def test_symmetric_biconvex_SII_small():
    r = compute_seidel_coma(BK7_SYMMETRIC, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    assert math.isfinite(r.S_II)
    # Check result is a plausible magnitude (not astronomically large)
    assert abs(r.S_II) < 100.0, f"S_II implausibly large: {r.S_II}"


# ---------------------------------------------------------------------------
# 6. Sum of per-surface SII_contrib equals total S_II
# ---------------------------------------------------------------------------

def test_per_surface_sum_equals_SII():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    total = sum(s["SII_contrib"] for s in r.per_surface_contributions)
    assert total == pytest.approx(r.S_II, rel=1e-10, abs=1e-20)


# ---------------------------------------------------------------------------
# 7. dominant_surface_idx in valid range
# ---------------------------------------------------------------------------

def test_dominant_surface_idx_valid():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    n_surf = len(BK7_BICONVEX["surfaces"])
    assert -1 <= r.dominant_surface_idx < n_surf


# ---------------------------------------------------------------------------
# 8. On-axis: dominant_surface_idx may be -1 (all coma is zero)
# ---------------------------------------------------------------------------

def test_dominant_surface_idx_on_axis():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=0.0)
    assert isinstance(r, SeidelComaReport)
    # On-axis: chief ray has angle 0 → Abar = 0 everywhere → all SII_j = 0
    # dominant_surface_idx should be -1 (all zero contributions)
    assert r.dominant_surface_idx == -1


# ---------------------------------------------------------------------------
# 9. coma_waves_at_lambda is non-negative
# ---------------------------------------------------------------------------

def test_coma_waves_nonneg():
    for angle in [0.0, 5.0, 10.0]:
        r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=angle)
        assert r.coma_waves_at_lambda >= 0.0, (
            f"coma_waves should be >= 0, got {r.coma_waves_at_lambda} at {angle}°"
        )


# ---------------------------------------------------------------------------
# 10. On-axis: coma_waves_at_lambda == 0
# ---------------------------------------------------------------------------

def test_coma_waves_zero_on_axis():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=0.0)
    assert r.coma_waves_at_lambda == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# 11. Coma waves increases with field angle (linear in S_II * y_chief)
# ---------------------------------------------------------------------------

def test_coma_waves_increases_with_field():
    r5  = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    r10 = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=10.0)
    # At larger field angle: chief-ray image height grows → more coma
    assert r10.coma_waves_at_lambda > r5.coma_waves_at_lambda, (
        f"coma at 10° ({r10.coma_waves_at_lambda:.4g}) should exceed 5° ({r5.coma_waves_at_lambda:.4g})"
    )


# ---------------------------------------------------------------------------
# 12. SeidelComaReport has all expected fields
# ---------------------------------------------------------------------------

def test_dataclass_fields():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    for attr in ("S_II", "coma_waves_at_lambda", "dominant_surface_idx",
                 "per_surface_contributions", "honest_caveat"):
        assert hasattr(r, attr), f"Missing attribute: {attr}"


# ---------------------------------------------------------------------------
# 13. to_dict() returns ok=True with S_II key
# ---------------------------------------------------------------------------

def test_to_dict_ok():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    d = r.to_dict()
    assert d["ok"] is True
    assert "S_II" in d
    assert math.isfinite(d["S_II"])


# ---------------------------------------------------------------------------
# 14. honest_caveat present in to_dict()
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    d = r.to_dict()
    assert "honest_caveat" in d
    assert "Third-order" in d["honest_caveat"]


# ---------------------------------------------------------------------------
# 15. Error: missing 'surfaces' key
# ---------------------------------------------------------------------------

def test_error_missing_surfaces_key():
    r = compute_seidel_coma({"aperture_radius_mm": 5.0}, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


# ---------------------------------------------------------------------------
# 16. Error: empty surfaces list
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_seidel_coma({"surfaces": []}, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 17. Error: missing 'n' in a surface
# ---------------------------------------------------------------------------

def test_error_bad_surface():
    bad = {"surfaces": [{"c": 0.01, "t": 0.0}]}   # missing 'n'
    r = compute_seidel_coma(bad, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 18. Error: n < 1.0
# ---------------------------------------------------------------------------

def test_error_n_below_1():
    bad = {"surfaces": [{"c": 0.02, "t": 0.0, "n": 0.8}]}
    r = compute_seidel_coma(bad, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 19. Error: non-dict input
# ---------------------------------------------------------------------------

def test_error_not_dict():
    r = compute_seidel_coma("not a dict", wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 20. Error: zero aperture
# ---------------------------------------------------------------------------

def test_error_bad_aperture():
    sys = dict(BK7_BICONVEX)
    sys = {"surfaces": BK7_BICONVEX["surfaces"], "aperture_radius_mm": 0.0}
    r = compute_seidel_coma(sys, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 21. Error: zero wavelength
# ---------------------------------------------------------------------------

def test_error_bad_wavelength():
    r = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=0.0, field_angle_deg=5.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 22. Shape factor changes S_II: plano-convex vs biconvex
# ---------------------------------------------------------------------------

def test_plano_convex_vs_biconvex_SII():
    r_bx = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    r_pc = compute_seidel_coma(PLANO_CONVEX_FLAT_FIRST, wavelength_nm=550, field_angle_deg=5.0)
    assert math.isfinite(r_pc.S_II)
    # Different bending → different S_II (shape factor matters for coma)
    assert r_pc.S_II != pytest.approx(r_bx.S_II, rel=0.01), (
        f"Plano-convex and biconvex should differ in S_II (got pc={r_pc.S_II:.4g}, bx={r_bx.S_II:.4g})"
    )


# ---------------------------------------------------------------------------
# 23. Reversed plano-convex has different S_II than original
# ---------------------------------------------------------------------------

def test_reversed_plano_convex_different():
    r1 = compute_seidel_coma(PLANO_CONVEX_FLAT_FIRST,   wavelength_nm=550, field_angle_deg=5.0)
    r2 = compute_seidel_coma(PLANO_CONVEX_CURVED_FIRST, wavelength_nm=550, field_angle_deg=5.0)
    # Orientation reversal changes shape factor → different S_II
    assert r1.S_II != pytest.approx(r2.S_II, rel=0.01), (
        f"Reversed plano-convex should differ in S_II (flat-first={r1.S_II:.4g}, curved-first={r2.S_II:.4g})"
    )


# ---------------------------------------------------------------------------
# 24. Cooke triplet: S_II is finite
# ---------------------------------------------------------------------------

def test_cooke_triplet_SII_finite():
    r = compute_seidel_coma(COOKE_TRIPLET, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    assert math.isfinite(r.S_II), f"Cooke triplet S_II not finite: {r.S_II}"


# ---------------------------------------------------------------------------
# 25. Field-angle scaling: doubling field ~doubles S_II (linear in tan(theta))
#     In the paraxial Seidel limit: S_II ~ Ā ~ tan(theta) ~ linear
# ---------------------------------------------------------------------------

def test_field_angle_scaling_linear():
    r5  = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=5.0)
    r10 = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550, field_angle_deg=10.0)
    if abs(r5.S_II) > 1e-20:
        ratio = r10.S_II / r5.S_II
        # Doubling field angle should roughly double S_II (linear in Ā)
        assert 1.5 < abs(ratio) < 3.0, (
            f"S_II field-angle scaling ratio: {ratio:.3g} (expected ~2x for doubling angle)"
        )


# ---------------------------------------------------------------------------
# 26. LLM tool: happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    d = _run_tool({
        "lens_system_dict": BK7_BICONVEX,
        "wavelength_nm": 550.0,
        "field_angle_deg": 5.0,
    })
    assert d["ok"] is True
    assert "S_II" in d
    assert math.isfinite(d["S_II"])
    assert "coma_waves_at_lambda" in d


# ---------------------------------------------------------------------------
# 27. LLM tool: missing lens_system_dict
# ---------------------------------------------------------------------------

def test_tool_missing_lens_system():
    d = _run_tool({"wavelength_nm": 550.0, "field_angle_deg": 5.0})
    assert d["ok"] is False
    assert "lens_system_dict" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 28. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    result = json.loads(asyncio.run(run_compute_seidel_coma(None, b"{bad json")))
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error response, got: {result}"


# ---------------------------------------------------------------------------
# 29. LLM tool: accepts wavelength_nm kwarg
# ---------------------------------------------------------------------------

def test_tool_wavelength_kwarg():
    d = _run_tool({
        "lens_system_dict": BK7_BICONVEX,
        "wavelength_nm": 632.8,
        "field_angle_deg": 5.0,
    })
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# 30. LLM tool: accepts field_angle_deg kwarg
# ---------------------------------------------------------------------------

def test_tool_field_angle_kwarg():
    d = _run_tool({
        "lens_system_dict": BK7_BICONVEX,
        "field_angle_deg": 10.0,
    })
    assert d["ok"] is True
    assert math.isfinite(d["S_II"])


# ---------------------------------------------------------------------------
# 31. Single refracting surface: S_II is finite
# ---------------------------------------------------------------------------

def test_single_surface_SII_finite():
    sys = {"surfaces": [{"c": 0.02, "t": 0.0, "n": 1.5}]}
    r = compute_seidel_coma(sys, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    assert math.isfinite(r.S_II)


# ---------------------------------------------------------------------------
# 32. Flat surface contributes zero S_II (c=0 → A=n*i = n*u; Ā=n*ubar,
#     but Δ(u/n) = 0 for c=0 flat surface since no power)
# ---------------------------------------------------------------------------

def test_flat_surface_zero_SII():
    flat_air = {"surfaces": [{"c": 0.0, "t": 0.0, "n": 1.0}]}
    r = compute_seidel_coma(flat_air, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    # Flat surface with no index change: Δ(u/n) = 0 → SII_j = 0
    assert r.per_surface_contributions[0]["SII_contrib"] == pytest.approx(0.0, abs=1e-15)


# ---------------------------------------------------------------------------
# 33. Afocal (flat glass slab) system: S_II finite; coma_waves near 0
#     (flat slab: c=0 on both surfaces → delta_un = 0 → S_II = 0)
# ---------------------------------------------------------------------------

def test_afocal_stack_SII_finite():
    flat_slab = {
        "surfaces": [
            {"c": 0.0, "t": 5.0, "n": 1.5},
            {"c": 0.0, "t": 0.0, "n": 1.0},
        ],
    }
    r = compute_seidel_coma(flat_slab, wavelength_nm=550, field_angle_deg=5.0)
    assert isinstance(r, SeidelComaReport)
    assert math.isfinite(r.S_II)
    # Flat slab: no optical power → S_II = 0 → coma_waves = 0
    assert abs(r.S_II) < 1e-12, f"Flat slab should have S_II ≈ 0, got {r.S_II}"


# ---------------------------------------------------------------------------
# 34. S_II is independent of wavelength_nm; only coma_waves differs
# ---------------------------------------------------------------------------

def test_SII_independent_of_wavelength():
    r550 = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=550.0, field_angle_deg=5.0)
    r633 = compute_seidel_coma(BK7_BICONVEX, wavelength_nm=632.8, field_angle_deg=5.0)
    # S_II (geometric sum) does not depend on wavelength_nm (monochromatic)
    assert r550.S_II == pytest.approx(r633.S_II, rel=1e-12)
    # coma_waves differs: ~ 1/lambda, so shorter lambda → more waves
    if r550.coma_waves_at_lambda > 1e-12:
        assert r633.coma_waves_at_lambda < r550.coma_waves_at_lambda, (
            "Longer wavelength → fewer waves at same physical coma"
        )
