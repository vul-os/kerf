"""
Tests for kerf_cad_core.optics.petzval_curvature — Petzval field curvature.

Test plan
---------
 1.  bk7_singlet_petzval_sum_value    — P ≈ 0.013657 mm⁻¹ for BK7 R1=+50/R2=−50 (within 1%)
 2.  bk7_singlet_petzval_radius       — R_P ≈ 73.2 mm (within 1%)
 3.  flat_field_condition             — doublet with P=0 verified (Σφ/n=0 condition)
 4.  plano_surface_zero_contribution  — |R|=1e18 surface contributes 0 to P
 5.  symmetric_doublet_reduces_P      — cemented crown+flint reduces |P| vs single crown lens
 6.  single_surface_refraction        — single glass/air surface contribution correct
 7.  field_flatness_score_flat        — P=0 → score = 1.0
 8.  field_flatness_score_decay       — P=0.01 → score ≈ 0.5
 9.  field_flatness_score_large_P     — very large P → score near 0
10.  per_surface_sum_equals_total     — sum of per_surface.contribution == petzval_sum
11.  per_surface_plano_flag           — is_plano=True for R=1e18 surface
12.  negative_R_contribution_sign     — R2=-50 gives positive contribution for n_after < n_before
13.  petzval_radius_inf_when_P_zero   — R_P = math.inf when P = 0
14.  error_empty_surfaces             — empty list → ok=False
15.  error_missing_surfaces_key       — dict without 'surfaces' → ok=False
16.  error_not_dict                   — non-dict input → ok=False
17.  error_bad_n_before               — n_before < 1.0 → ok=False
18.  error_missing_field              — surface missing 'radius_mm' → ok=False
19.  report_dataclass_fields          — PetzvalReport has all expected attributes
20.  to_dict_ok_key                   — to_dict() returns {ok: True}
21.  honest_caveat_present            — honest_caveat non-empty string
22.  three_element_triplet_P_finite   — Cooke-style triplet P is finite
23.  tool_happy_path                  — LLM tool returns ok JSON
24.  tool_missing_surfaces            — LLM tool returns ok=False for missing surfaces
25.  tool_bad_json                    — LLM tool handles invalid JSON gracefully
26.  petzval_sum_additive             — P(A+B) = P(A) + P(B) for independent surfaces

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Hecht, E. — "Optics", 5th ed. (2017), §6.3.2.
Born, M. & Wolf, E. — "Principles of Optics", 7th ed. (1999), §4.5.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.petzval_curvature import PetzvalReport, compute_petzval_curvature
from kerf_cad_core.optics.tools import run_compute_petzval_curvature


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Single thin BK7 lens in air: R1=+50 mm, R2=−50 mm, n=1.5168.
# Oracle: P = (n−1)/(n·50) + (1−n)/(n·(−50))
#           = 0.5168/(1.5168·50) + (−0.5168)/(1.5168·(−50))
#           = 0.5168/75.84 + 0.5168/75.84
#           = 0.006814 + 0.006814
#           = 0.013628 mm⁻¹  → R_P ≈ 73.4 mm
# Hecht eq. 6.69 gives P ≈ 1/(n·f) = 1/(1.5168·48.3) ≈ 0.01366  (thin-lens approx)
_N_BK7 = 1.5168
_R1_BK7 = 50.0   # mm
_R2_BK7 = -50.0  # mm

BK7_SINGLET = {
    "surfaces": [
        {"radius_mm": _R1_BK7, "n_index_before": 1.0,    "n_index_after": _N_BK7},
        {"radius_mm": _R2_BK7, "n_index_before": _N_BK7, "n_index_after": 1.0},
    ]
}


def _petzval_sum_manual(surfaces: list[dict]) -> float:
    """Manually compute Petzval sum for verification."""
    P = 0.0
    for s in surfaces:
        R = float(s["radius_mm"])
        nb = float(s["n_index_before"])
        na = float(s["n_index_after"])
        if abs(R) < 1e15:
            P += (na - nb) / (nb * na * R)
    return P


def _run_tool(args: dict) -> dict:
    return json.loads(asyncio.run(run_compute_petzval_curvature(None, json.dumps(args).encode())))


# ---------------------------------------------------------------------------
# 1. BK7 singlet Petzval sum value: P ≈ 0.013657 mm⁻¹  (within 1%)
# ---------------------------------------------------------------------------

def test_bk7_singlet_petzval_sum_value():
    r = compute_petzval_curvature(BK7_SINGLET)
    assert isinstance(r, PetzvalReport)
    # Hand-calculation:
    # surf1: (1.5168 - 1.0) / (1.0 * 1.5168 * 50.0) = 0.5168 / 75.84 = 0.006814
    # surf2: (1.0 - 1.5168) / (1.5168 * 1.0 * (-50.0)) = -0.5168 / -75.84 = 0.006814
    # total P ≈ 0.013628 mm⁻¹
    expected = 2 * ((_N_BK7 - 1.0) / (1.0 * _N_BK7 * _R1_BK7))
    assert abs(r.petzval_sum - expected) < abs(expected) * 0.001, (
        f"P = {r.petzval_sum:.6f}, expected ≈ {expected:.6f}"
    )


# ---------------------------------------------------------------------------
# 2. BK7 singlet Petzval radius: R_P ≈ 73.2 mm  (within 1%)
# ---------------------------------------------------------------------------

def test_bk7_singlet_petzval_radius():
    r = compute_petzval_curvature(BK7_SINGLET)
    assert isinstance(r, PetzvalReport)
    assert math.isfinite(r.petzval_radius_mm)
    # R_P = 1/P; expected ≈ 73.4 mm
    expected_Rp = 1.0 / _petzval_sum_manual(BK7_SINGLET["surfaces"])
    assert abs(r.petzval_radius_mm - expected_Rp) < abs(expected_Rp) * 0.01, (
        f"R_P = {r.petzval_radius_mm:.2f} mm, expected ≈ {expected_Rp:.2f} mm"
    )
    # Hecht oracle: R_P should be in range [70, 76] mm for this lens
    assert 70.0 < r.petzval_radius_mm < 78.0, (
        f"R_P = {r.petzval_radius_mm:.2f} mm outside expected range"
    )


# ---------------------------------------------------------------------------
# 3. Flat-field condition: P = 0 for a compensated doublet
#
# Petzval condition (Hecht §6.3.2): Σ φ_i / n_i = 0
# For two thin lenses cemented in air:
#   φ1/n1 + φ2/n2 = 0
# where φ_i = (n_i−1)*(1/R1_i − 1/R2_i).
# Design: crown (n1=1.5) with φ1 > 0 and flint (n2=1.7) with φ2 chosen
#   to satisfy φ2 = -φ1 * n2/n1.
#
# For simplicity: use a single-surface model.
# A single air-glass refraction (n1=1, n2=n) followed by a glass-air
# refraction (n1=n, n2=1) with the SAME R but with an intermediate
# glass-air refractive crossing that exactly cancels gives P=0.
#
# Easier: use the Petzval condition directly for a two-lens system.
# If φ_A = (n_A−1)*(1/R1_A − 1/R2_A) and φ_B = (n_B−1)*(1/R1_B − 1/R2_B)
# then P = φ_A/n_A + φ_B/n_B (for thin lenses in contact, Hecht §6.3.2).
# Choose:  n_A=1.5, φ_A=0.01; n_B=1.7; φ_B = -φ_A*n_B/n_A = -0.01*1.7/1.5
# Then φ_B/n_B = -(φ_A/n_A) → P = 0.
# ---------------------------------------------------------------------------

def _make_thin_lens_surfaces(phi: float, n_glass: float, n_before: float = 1.0) -> list[dict]:
    """
    Produce two-surface thin-lens in air with optical power phi (mm^-1) and
    glass index n_glass, using a symmetric (equiconvex) bending:
      phi = (n_glass - n_before)*(1/R1 - 1/R2), with R1=-R2=R.
      phi = (n_glass - n_before)*2/R  =>  R = 2*(n_glass-n_before)/phi
    """
    if abs(phi) < 1e-20:
        # Zero-power element: use very large radii
        return [
            {"radius_mm": 1e18, "n_index_before": n_before,   "n_index_after": n_glass},
            {"radius_mm": 1e18, "n_index_before": n_glass,    "n_index_after": 1.0},
        ]
    R = 2.0 * (n_glass - n_before) / phi  # R for symmetric bending
    return [
        {"radius_mm":  R, "n_index_before": n_before,  "n_index_after": n_glass},
        {"radius_mm": -R, "n_index_before": n_glass,   "n_index_after": 1.0},
    ]


def test_flat_field_condition():
    """
    Construct a compensated doublet where P = Σ φ_i/n_i = 0 (Petzval condition).
    Use φ_A/n_A + φ_B/n_B = 0  →  φ_B = -φ_A * n_B / n_A.
    """
    n_A = 1.5
    n_B = 1.7
    phi_A = 1.0 / 100.0   # positive power: 100 mm focal length
    phi_B = -phi_A * n_B / n_A  # cancels Petzval contribution

    surfaces_A = _make_thin_lens_surfaces(phi_A, n_A)
    surfaces_B = _make_thin_lens_surfaces(phi_B, n_B)
    all_surfaces = surfaces_A + surfaces_B

    r = compute_petzval_curvature({"surfaces": all_surfaces})
    assert isinstance(r, PetzvalReport)
    # P should be zero (or very close) for this design
    assert abs(r.petzval_sum) < 1e-10, (
        f"Expected P≈0 for compensated doublet, got P = {r.petzval_sum:.2e}"
    )
    assert not math.isfinite(r.petzval_radius_mm) or abs(r.petzval_radius_mm) > 1e14
    assert r.field_flatness_score > 0.9999


# ---------------------------------------------------------------------------
# 4. Plano surface contributes 0
# ---------------------------------------------------------------------------

def test_plano_surface_zero_contribution():
    system = {
        "surfaces": [
            {"radius_mm": 1e18, "n_index_before": 1.0, "n_index_after": 1.5},
            {"radius_mm": -50.0, "n_index_before": 1.5, "n_index_after": 1.0},
        ]
    }
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    # First surface is plano → contribution = 0
    plano_contrib = r.per_surface_contributions[0]["contribution"]
    assert plano_contrib == pytest.approx(0.0, abs=1e-20)
    # Second surface is curved → contribution != 0
    curved_contrib = r.per_surface_contributions[1]["contribution"]
    assert abs(curved_contrib) > 1e-6


# ---------------------------------------------------------------------------
# 5. Symmetric doublet reduces |P| vs single crown lens
# ---------------------------------------------------------------------------

def test_symmetric_doublet_reduces_P():
    # Crown lens alone (n=1.5)
    crown_only = {
        "surfaces": [
            {"radius_mm": 50.0,  "n_index_before": 1.0, "n_index_after": 1.5},
            {"radius_mm": -50.0, "n_index_before": 1.5, "n_index_after": 1.0},
        ]
    }
    # Same crown + compensating flint element (n=1.7, negative power)
    # Flint with R3=+60, R4=−60 gives a negative-power element
    doublet = {
        "surfaces": [
            {"radius_mm":  50.0, "n_index_before": 1.0, "n_index_after": 1.5},
            {"radius_mm": -50.0, "n_index_before": 1.5, "n_index_after": 1.0},
            {"radius_mm":  60.0, "n_index_before": 1.0, "n_index_after": 1.7},
            {"radius_mm": -60.0, "n_index_before": 1.7, "n_index_after": 1.0},
        ]
    }
    r_crown = compute_petzval_curvature(crown_only)
    r_doublet = compute_petzval_curvature(doublet)
    assert isinstance(r_crown, PetzvalReport)
    assert isinstance(r_doublet, PetzvalReport)
    # The high-index flint contributes positive P (both R positive and negative)
    # but in a crown+flint doublet the flint sign combination reduces total |P|
    # compared to crown alone (by design).
    # Here the flint is a positive element (R3>0, R4<0) but with higher n;
    # Petzval sum of crown (0.0136) > doublet sum with partial compensation.
    # At minimum, the doublet P should be finite.
    assert math.isfinite(r_doublet.petzval_sum)
    # If we use a *negative* flint element (R>0, n_after < n_before path)
    # we get real compensation — verify this separately:
    doublet_neg = {
        "surfaces": [
            {"radius_mm":  50.0,  "n_index_before": 1.0,  "n_index_after": 1.5},
            {"radius_mm": -50.0,  "n_index_before": 1.5,  "n_index_after": 1.0},
            {"radius_mm": -200.0, "n_index_before": 1.0,  "n_index_after": 1.7},
            {"radius_mm":  200.0, "n_index_before": 1.7,  "n_index_after": 1.0},
        ]
    }
    r_dn = compute_petzval_curvature(doublet_neg)
    assert isinstance(r_dn, PetzvalReport)
    assert abs(r_dn.petzval_sum) < abs(r_crown.petzval_sum), (
        f"Doublet with negative flint should reduce |P|: "
        f"crown={r_crown.petzval_sum:.5f}, doublet={r_dn.petzval_sum:.5f}"
    )


# ---------------------------------------------------------------------------
# 6. Single surface refraction — verify formula directly
# ---------------------------------------------------------------------------

def test_single_surface_refraction():
    n_before = 1.0
    n_after = 1.5
    R = 30.0  # mm
    expected = (n_after - n_before) / (n_before * n_after * R)
    system = {
        "surfaces": [
            {"radius_mm": R, "n_index_before": n_before, "n_index_after": n_after}
        ]
    }
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    assert r.petzval_sum == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------------------
# 7. Field flatness score = 1.0 when P = 0
# ---------------------------------------------------------------------------

def test_field_flatness_score_flat():
    # Use exact P=0 setup
    n_A = 1.5
    n_B = 1.7
    phi_A = 1.0 / 100.0
    phi_B = -phi_A * n_B / n_A
    surfaces_A = _make_thin_lens_surfaces(phi_A, n_A)
    surfaces_B = _make_thin_lens_surfaces(phi_B, n_B)
    r = compute_petzval_curvature({"surfaces": surfaces_A + surfaces_B})
    assert isinstance(r, PetzvalReport)
    assert r.field_flatness_score == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 8. Field flatness score ≈ 0.5 at |P| = 0.01 mm⁻¹
# ---------------------------------------------------------------------------

def test_field_flatness_score_decay():
    # |P| = 0.01 → score = 1/(1+0.01*100) = 1/2 = 0.5
    # Create a surface with known contribution P = 0.01 mm⁻¹
    # (n_after - n_before) / (n_before * n_after * R) = 0.01
    # Let n_before=1, n_after=1.5: 0.5/(1.5*R) = 0.01 → R = 0.5/0.015 = 33.33 mm
    n_before = 1.0
    n_after = 1.5
    P_target = 0.01  # mm⁻¹
    R = (n_after - n_before) / (n_before * n_after * P_target)
    system = {"surfaces": [{"radius_mm": R, "n_index_before": n_before, "n_index_after": n_after}]}
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    assert r.petzval_sum == pytest.approx(P_target, rel=1e-9)
    assert r.field_flatness_score == pytest.approx(0.5, rel=1e-9)


# ---------------------------------------------------------------------------
# 9. Field flatness score approaches 0 for very large P
# ---------------------------------------------------------------------------

def test_field_flatness_score_large_P():
    # Very small R (tightly curved) → large P → score near 0
    system = {"surfaces": [{"radius_mm": 0.01, "n_index_before": 1.0, "n_index_after": 2.0}]}
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    assert r.field_flatness_score < 0.01


# ---------------------------------------------------------------------------
# 10. Sum of per-surface contributions equals petzval_sum
# ---------------------------------------------------------------------------

def test_per_surface_sum_equals_total():
    r = compute_petzval_curvature(BK7_SINGLET)
    assert isinstance(r, PetzvalReport)
    total_from_parts = sum(s["contribution"] for s in r.per_surface_contributions)
    assert total_from_parts == pytest.approx(r.petzval_sum, rel=1e-12)


# ---------------------------------------------------------------------------
# 11. is_plano=True for |R|=1e18 surface
# ---------------------------------------------------------------------------

def test_per_surface_plano_flag():
    system = {
        "surfaces": [
            {"radius_mm": 1e18, "n_index_before": 1.0, "n_index_after": 1.5},
            {"radius_mm": -50.0, "n_index_before": 1.5, "n_index_after": 1.0},
        ]
    }
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    assert r.per_surface_contributions[0]["is_plano"] is True
    assert r.per_surface_contributions[1]["is_plano"] is False


# ---------------------------------------------------------------------------
# 12. Negative R contribution sign
# ---------------------------------------------------------------------------

def test_negative_R_contribution_sign():
    # For a glass-to-air surface (n_before > n_after) with negative R (convex exit):
    # delta_n = n_after - n_before < 0; R < 0
    # contrib = delta_n / (n_before * n_after * R) = (neg)/(pos * pos * neg) = pos
    n_before = 1.5168
    n_after = 1.0
    R = -50.0
    expected = (n_after - n_before) / (n_before * n_after * R)
    assert expected > 0, "Expected positive contribution for glass→air exit surface with R<0"
    system = {
        "surfaces": [
            {"radius_mm": R, "n_index_before": n_before, "n_index_after": n_after}
        ]
    }
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    assert r.petzval_sum == pytest.approx(expected, rel=1e-12)
    assert r.petzval_sum > 0


# ---------------------------------------------------------------------------
# 13. petzval_radius_mm = math.inf when P = 0
# ---------------------------------------------------------------------------

def test_petzval_radius_inf_when_P_zero():
    # Two surfaces with equal and opposite contributions
    # surf1: contrib = +c
    # surf2: contrib = -c
    # So total P = 0
    # surf1: n_before=1, n_after=1.5, R=+30 → contrib = 0.5/(1.5*30) = 0.01111
    # surf2: want contrib = -0.01111
    #   (n_after - n_before)/(n_before * n_after * R) = -0.01111
    #   let n_before=1.5, n_after=1 → delta_n=-0.5; R such that -0.5/(1.5*R) = -0.01111
    #   R = 0.5/(1.5*0.01111) = 30.0 mm
    # surf2: n_before=1.5, n_after=1.0, R=+30 → (1-1.5)/(1.5*1*30) = -0.5/45 = -0.01111  ✓
    system = {
        "surfaces": [
            {"radius_mm": 30.0, "n_index_before": 1.0, "n_index_after": 1.5},
            {"radius_mm": 30.0, "n_index_before": 1.5, "n_index_after": 1.0},
        ]
    }
    r = compute_petzval_curvature(system)
    assert isinstance(r, PetzvalReport)
    # P should be zero
    assert abs(r.petzval_sum) < 1e-20
    assert not math.isfinite(r.petzval_radius_mm) or r.petzval_radius_mm > 1e25


# ---------------------------------------------------------------------------
# 14. Error: empty surfaces list
# ---------------------------------------------------------------------------

def test_error_empty_surfaces():
    r = compute_petzval_curvature({"surfaces": []})
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 15. Error: missing 'surfaces' key
# ---------------------------------------------------------------------------

def test_error_missing_surfaces_key():
    r = compute_petzval_curvature({"not_surfaces": []})
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "surfaces" in r["reason"]


# ---------------------------------------------------------------------------
# 16. Error: non-dict input
# ---------------------------------------------------------------------------

def test_error_not_dict():
    r = compute_petzval_curvature([{"radius_mm": 50.0, "n_index_before": 1.0, "n_index_after": 1.5}])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 17. Error: n_before < 1.0
# ---------------------------------------------------------------------------

def test_error_bad_n_before():
    r = compute_petzval_curvature({
        "surfaces": [
            {"radius_mm": 50.0, "n_index_before": 0.5, "n_index_after": 1.5}
        ]
    })
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 18. Error: missing 'radius_mm' field
# ---------------------------------------------------------------------------

def test_error_missing_field():
    r = compute_petzval_curvature({
        "surfaces": [
            {"n_index_before": 1.0, "n_index_after": 1.5}  # no radius_mm
        ]
    })
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "radius_mm" in r["reason"]


# ---------------------------------------------------------------------------
# 19. PetzvalReport has all expected attributes
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = compute_petzval_curvature(BK7_SINGLET)
    assert isinstance(r, PetzvalReport)
    for attr in ("petzval_sum", "petzval_radius_mm", "field_flatness_score",
                 "per_surface_contributions", "honest_caveat"):
        assert hasattr(r, attr), f"PetzvalReport missing attribute: {attr}"


# ---------------------------------------------------------------------------
# 20. to_dict() returns {ok: True} with expected keys
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    r = compute_petzval_curvature(BK7_SINGLET)
    d = r.to_dict()
    assert d["ok"] is True
    assert "petzval_sum_mm_inv" in d
    assert "petzval_radius_mm" in d
    assert "field_flatness_score" in d
    assert "per_surface_contributions" in d
    assert "honest_caveat" in d


# ---------------------------------------------------------------------------
# 21. honest_caveat is a non-empty string
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    r = compute_petzval_curvature(BK7_SINGLET)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 20
    # Should mention astigmatism (key caveat from Hecht §6.3.2)
    assert "astigmatism" in r.honest_caveat.lower() or "astigmat" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 22. Cooke-style triplet Petzval sum is finite
# ---------------------------------------------------------------------------

def test_three_element_triplet_P_finite():
    # Cooke triplet thin-lens approximation: crown / flint / crown in air
    # Crown (n=1.523, f=+75): phi=1/75
    # Flint (n=1.617, f=-39): phi=-1/39
    # Crown (n=1.523, f=+75): phi=1/75
    N_C = 1.523
    N_F = 1.617
    s1 = _make_thin_lens_surfaces(1.0 / 75.0, N_C)
    s2 = _make_thin_lens_surfaces(-1.0 / 39.0, N_F)
    s3 = _make_thin_lens_surfaces(1.0 / 75.0, N_C)
    r = compute_petzval_curvature({"surfaces": s1 + s2 + s3})
    assert isinstance(r, PetzvalReport)
    assert math.isfinite(r.petzval_sum)
    assert math.isfinite(r.field_flatness_score)


# ---------------------------------------------------------------------------
# 23. LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    args = {
        "surfaces": BK7_SINGLET["surfaces"]
    }
    d = _run_tool(args)
    assert d["ok"] is True
    assert "petzval_sum_mm_inv" in d
    assert math.isfinite(d["petzval_sum_mm_inv"])
    assert d["petzval_sum_mm_inv"] > 0.0  # converging singlet → P > 0


# ---------------------------------------------------------------------------
# 24. LLM tool: missing surfaces
# ---------------------------------------------------------------------------

def test_tool_missing_surfaces():
    d = _run_tool({})
    assert d["ok"] is False
    assert "surfaces" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 25. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    result = json.loads(asyncio.run(run_compute_petzval_curvature(None, b"{bad json")))
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error response, got: {result}"


# ---------------------------------------------------------------------------
# 26. Petzval sum is additive: P(A + B) = P(A) + P(B)
# ---------------------------------------------------------------------------

def test_petzval_sum_additive():
    # Build two independent surface sets
    s_A = [{"radius_mm": 50.0,  "n_index_before": 1.0, "n_index_after": 1.5}]
    s_B = [{"radius_mm": -80.0, "n_index_before": 1.5, "n_index_after": 1.0}]
    s_AB = s_A + s_B

    r_A = compute_petzval_curvature({"surfaces": s_A})
    r_B = compute_petzval_curvature({"surfaces": s_B})
    r_AB = compute_petzval_curvature({"surfaces": s_AB})

    assert isinstance(r_A, PetzvalReport)
    assert isinstance(r_B, PetzvalReport)
    assert isinstance(r_AB, PetzvalReport)

    expected_P = r_A.petzval_sum + r_B.petzval_sum
    assert r_AB.petzval_sum == pytest.approx(expected_P, rel=1e-12)
