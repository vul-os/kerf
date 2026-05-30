"""
Tests for kerf_cad_core.optics.chromatic_focus — Longitudinal chromatic aberration
via Sellmeier dispersion.

Test plan
---------
1.  bk7_sellmeier_nF            -- BK7 n at 486 nm ≈ 1.5224 (Schott data sheet)
2.  bk7_sellmeier_nd            -- BK7 n at 587 nm ≈ 1.5168
3.  bk7_sellmeier_nC            -- BK7 n at 656 nm ≈ 1.5143
4.  bk7_v_number_approx_64      -- BK7 Abbe number (n_d-1)/(n_F-n_C) ≈ 64.2 ±0.5
5.  f2_v_number_approx_36       -- F2 Abbe number ≈ 36.4 ±0.5
6.  sf6_v_number_approx_25      -- SF6 Abbe number ≈ 25.4 ±1
7.  bk7_singlet_v_matches       -- compute_chromatic_focus V_number ≈ 64.2 for BK7 singlet
8.  bk7_singlet_lca_sign        -- LCA (F−C) negative for positive BK7 singlet (blue shorter)
9.  bk7_singlet_lca_magnitude   -- |LCA| ≈ f/V for BK7 singlet f=100 mm → ~1.56 mm ±20%
10. sf6_singlet_high_lca        -- SF6 singlet has higher |LCA| than BK7 singlet
11. achromat_bk7_f2_lca_small   -- BK7+F2 achromatic doublet LCA < 0.1 mm for f≈100 mm
12. per_wavelength_keys         -- report has keys for each requested wavelength
13. three_wavelength_ordering   -- BFL increases from F→d→C (blue shorter for positive lens)
14. report_dataclass_fields     -- ChromaticReport has all expected attributes
15. to_dict_ok_key              -- to_dict() has ok=True
16. honest_flag_in_dict         -- to_dict() includes honest_flag with 'lateral' caveat
17. error_empty_stack           -- empty stack returns {"ok": False}
18. error_bad_glass             -- unknown glass returns {"ok": False}
19. error_zero_radius           -- R1=0 returns {"ok": False}
20. error_bad_wavelength        -- negative wavelength returns {"ok": False}
21. error_afocal_stack          -- afocal doublet returns {"ok": False} or finite report
22. multi_element_no_v_number   -- V_number is None for two-element stack
23. custom_wavelengths          -- custom wavelength list returns correct key count
24. lca_percent_nonneg          -- lca_percent is non-negative
25. mean_bfl_finite             -- mean_BFL_mm is finite and positive
26. k5_singlet_v_approx_59      -- K5 singlet V ≈ 59.5 ±1
27. bk10_singlet_v_approx_67    -- BK10 singlet V ≈ 66.9 ±1
28. sf11_v_number_approx_25     -- SF11 Abbe number ≈ 25.4 ±1 (dense flint)
29. single_wavelength_lca_zero  -- single wavelength: lca_FC ≈ 0 (F and C map to same wl)
30. tool_happy_path             -- LLM tool returns ok JSON for BK7 singlet
31. tool_missing_stack          -- LLM tool returns error for missing stack
32. tool_bad_json               -- LLM tool handles invalid JSON
33. tool_custom_wavelengths     -- LLM tool accepts wavelengths_nm override
34. tool_two_element_achromat   -- LLM tool happy path for BK7+F2 doublet

All tests are pure-Python, hermetic (no OCC, DB, or network).

References
----------
Hecht, E. — "Optics", 5th ed., §6.3.
Welford, W.T. — "Aberrations of Optical Systems", §6.5.
Schott AG — Optical Glass Data Sheets, 2023 edition.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.chromatic_focus import (
    GLASS_SELLMEIER,
    ChromaticReport,
    LensElement,
    compute_chromatic_focus,
    sellmeier_n,
)
from kerf_cad_core.optics.tools import run_compute_chromatic_focus


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _bk7_singlet(f_mm: float = 100.0) -> list[LensElement]:
    """Symmetric biconvex BK7 thin singlet with nominal focal length f_mm.

    For a symmetric biconvex: R = 2*(n_d-1)*f.
    """
    n_d_bk7 = 1.5168
    R = 2.0 * (n_d_bk7 - 1.0) * f_mm  # ≈ 103.36 mm
    return [LensElement(glass="BK7", R1=R, R2=-R, separation_mm=0.0)]


def _achromat_bk7_f2(f_mm: float = 100.0) -> list[LensElement]:
    """
    Achromatic doublet BK7 (crown) + F2 (flint) using the Abbe doublet condition.

    Achromatic condition (Hecht §6.3):
        phi1 / V1 + phi2 / V2 = 0   and   phi1 + phi2 = phi_total
    =>  phi1 = phi_total * V1 / (V1 - V2)
        phi2 = -phi_total * V2 / (V1 - V2)

    Element thin-lens power phi = (n-1)*(1/R1 - 1/R2).
    For a symmetric element: R = 2*(n-1)/phi.

    Uses n_d values for element power computation; Sellmeier handles the rest.
    """
    phi_total = 1.0 / f_mm  # mm^-1
    # Abbe numbers from Schott: V_BK7 ≈ 64.17, V_F2 ≈ 36.43
    V1, V2 = 64.17, 36.43
    n1 = 1.51680  # BK7 n_d
    n2 = 1.62004  # F2  n_d
    phi1 = phi_total * V1 / (V1 - V2)
    phi2 = -phi_total * V2 / (V1 - V2)
    R1_crown = 2.0 * (n1 - 1.0) / phi1
    R1_flint = 2.0 * (n2 - 1.0) / phi2
    return [
        LensElement(glass="BK7", R1=R1_crown, R2=-R1_crown, separation_mm=0.0),
        LensElement(glass="F2",  R1=R1_flint, R2=-R1_flint, separation_mm=0.0),
    ]


def _run_tool(args: dict) -> dict:
    return json.loads(asyncio.run(run_compute_chromatic_focus(None, json.dumps(args).encode())))


# ---------------------------------------------------------------------------
# 1. BK7 n_F (486 nm) ≈ 1.5224
# ---------------------------------------------------------------------------

def test_bk7_sellmeier_nF():
    n = sellmeier_n("BK7", 0.48613)
    assert n == pytest.approx(1.5224, abs=0.001), f"BK7 n_F = {n}"


# ---------------------------------------------------------------------------
# 2. BK7 n_d (587 nm) ≈ 1.5168
# ---------------------------------------------------------------------------

def test_bk7_sellmeier_nd():
    n = sellmeier_n("BK7", 0.58756)
    assert n == pytest.approx(1.5168, abs=0.001), f"BK7 n_d = {n}"


# ---------------------------------------------------------------------------
# 3. BK7 n_C (656 nm) ≈ 1.5143
# ---------------------------------------------------------------------------

def test_bk7_sellmeier_nC():
    n = sellmeier_n("BK7", 0.65627)
    assert n == pytest.approx(1.5143, abs=0.001), f"BK7 n_C = {n}"


# ---------------------------------------------------------------------------
# 4. BK7 Abbe V-number ≈ 64.2
# ---------------------------------------------------------------------------

def test_bk7_v_number_approx_64():
    n_F = sellmeier_n("BK7", 0.48613)
    n_d = sellmeier_n("BK7", 0.58756)
    n_C = sellmeier_n("BK7", 0.65627)
    V = (n_d - 1.0) / (n_F - n_C)
    assert V == pytest.approx(64.2, abs=0.5), f"BK7 V = {V}"


# ---------------------------------------------------------------------------
# 5. F2 Abbe V-number ≈ 36.4
# ---------------------------------------------------------------------------

def test_f2_v_number_approx_36():
    n_F = sellmeier_n("F2", 0.48613)
    n_d = sellmeier_n("F2", 0.58756)
    n_C = sellmeier_n("F2", 0.65627)
    V = (n_d - 1.0) / (n_F - n_C)
    assert V == pytest.approx(36.4, abs=0.5), f"F2 V = {V}"


# ---------------------------------------------------------------------------
# 6. SF6 Abbe V-number ≈ 25.4
# ---------------------------------------------------------------------------

def test_sf6_v_number_approx_25():
    n_F = sellmeier_n("SF6", 0.48613)
    n_d = sellmeier_n("SF6", 0.58756)
    n_C = sellmeier_n("SF6", 0.65627)
    V = (n_d - 1.0) / (n_F - n_C)
    assert V == pytest.approx(25.4, abs=1.0), f"SF6 V = {V}"


# ---------------------------------------------------------------------------
# 7. BK7 singlet V_number ≈ 64.2
# ---------------------------------------------------------------------------

def test_bk7_singlet_v_matches():
    r = compute_chromatic_focus(_bk7_singlet(100.0))
    assert isinstance(r, ChromaticReport)
    assert r.V_number is not None
    assert r.V_number == pytest.approx(64.2, abs=0.5), f"Singlet V = {r.V_number}"


# ---------------------------------------------------------------------------
# 8. BK7 singlet LCA sign — blue focuses shorter → lca_FC < 0
# ---------------------------------------------------------------------------

def test_bk7_singlet_lca_sign():
    r = compute_chromatic_focus(_bk7_singlet(100.0))
    assert isinstance(r, ChromaticReport)
    # F-line (486 nm) focus is CLOSER than C-line (656 nm) → BFL(F) < BFL(C) → LCA < 0
    assert r.lca_FC_mm < 0.0, f"Expected lca_FC < 0 for positive BK7 singlet, got {r.lca_FC_mm}"


# ---------------------------------------------------------------------------
# 9. BK7 singlet |LCA| ≈ f / V ≈ 1.56 mm  (±20%)
# ---------------------------------------------------------------------------

def test_bk7_singlet_lca_magnitude():
    f = 100.0
    r = compute_chromatic_focus(_bk7_singlet(f))
    assert isinstance(r, ChromaticReport)
    expected = f / r.V_number  # type: ignore[operator]
    # The thin-lens LCA formula is approximate; exact = BFL_F − BFL_C
    assert abs(r.lca_FC_mm) == pytest.approx(expected, rel=0.20), (
        f"|LCA|={abs(r.lca_FC_mm):.4f} mm, expected ~{expected:.4f} mm"
    )


# ---------------------------------------------------------------------------
# 10. SF6 singlet has higher |LCA| than BK7 (lower V-number)
# ---------------------------------------------------------------------------

def test_sf6_singlet_high_lca():
    n_d_sf6 = sellmeier_n("SF6", 0.58756)
    R = 2.0 * (n_d_sf6 - 1.0) * 100.0
    sf6 = [LensElement(glass="SF6", R1=R, R2=-R, separation_mm=0.0)]
    r_bk7 = compute_chromatic_focus(_bk7_singlet(100.0))
    r_sf6 = compute_chromatic_focus(sf6)
    assert isinstance(r_sf6, ChromaticReport)
    assert abs(r_sf6.lca_FC_mm) > abs(r_bk7.lca_FC_mm), (
        f"SF6 |LCA|={abs(r_sf6.lca_FC_mm):.4f} should > BK7 |LCA|={abs(r_bk7.lca_FC_mm):.4f}"
    )


# ---------------------------------------------------------------------------
# 11. BK7+F2 achromatic doublet LCA < 0.1 mm
# ---------------------------------------------------------------------------

def test_achromat_bk7_f2_lca_small():
    r = compute_chromatic_focus(_achromat_bk7_f2(100.0))
    assert isinstance(r, ChromaticReport)
    # Achromatic doublet: F and C foci coincide → |LCA| << single-element LCA
    assert abs(r.lca_FC_mm) < 0.10, (
        f"Achromat |LCA| = {abs(r.lca_FC_mm):.6f} mm should be < 0.1 mm"
    )


# ---------------------------------------------------------------------------
# 12. per_wavelength keys present
# ---------------------------------------------------------------------------

def test_per_wavelength_keys():
    wls = [450.0, 550.0, 650.0]
    r = compute_chromatic_focus(_bk7_singlet(), wavelengths_nm=wls)
    assert isinstance(r, ChromaticReport)
    assert len(r.per_wavelength_focal) == 3
    for w in wls:
        assert w in r.per_wavelength_focal


# ---------------------------------------------------------------------------
# 13. BFL increases from F (486) to d (587) to C (656) for positive lens
# ---------------------------------------------------------------------------

def test_three_wavelength_ordering():
    r = compute_chromatic_focus(_bk7_singlet())
    assert isinstance(r, ChromaticReport)
    bfl_F = r.per_wavelength_focal[486.0]
    bfl_d = r.per_wavelength_focal[587.0]
    bfl_C = r.per_wavelength_focal[656.0]
    assert bfl_F < bfl_d < bfl_C, (
        f"Expected BFL(F) < BFL(d) < BFL(C), got {bfl_F:.4f} < {bfl_d:.4f} < {bfl_C:.4f}"
    )


# ---------------------------------------------------------------------------
# 14. ChromaticReport has all expected attributes
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    r = compute_chromatic_focus(_bk7_singlet())
    assert isinstance(r, ChromaticReport)
    for attr in (
        "per_wavelength_focal", "lca_FC_mm", "lca_percent",
        "V_number", "mean_BFL_mm", "honest_flag",
    ):
        assert hasattr(r, attr), f"Missing attribute: {attr}"


# ---------------------------------------------------------------------------
# 15. to_dict() returns ok=True
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    r = compute_chromatic_focus(_bk7_singlet())
    assert isinstance(r, ChromaticReport)
    d = r.to_dict()
    assert d["ok"] is True
    assert "lca_FC_mm" in d
    assert "per_wavelength_focal_mm" in d


# ---------------------------------------------------------------------------
# 16. honest_flag includes 'lateral' caveat
# ---------------------------------------------------------------------------

def test_honest_flag_in_dict():
    r = compute_chromatic_focus(_bk7_singlet())
    assert isinstance(r, ChromaticReport)
    d = r.to_dict()
    assert "honest_flag" in d
    # Must mention that chromatic lateral aberration is not computed
    assert "lateral" in d["honest_flag"].lower() or "transverse" in d["honest_flag"].lower()


# ---------------------------------------------------------------------------
# 17. Error: empty stack
# ---------------------------------------------------------------------------

def test_error_empty_stack():
    r = compute_chromatic_focus([])
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "stack" in r["reason"]


# ---------------------------------------------------------------------------
# 18. Error: unknown glass
# ---------------------------------------------------------------------------

def test_error_bad_glass():
    elem = LensElement(glass="N-BK7-UNKNOWN", R1=100.0, R2=-100.0)
    r = compute_chromatic_focus([elem])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 19. Error: R1 = 0
# ---------------------------------------------------------------------------

def test_error_zero_radius():
    elem = LensElement(glass="BK7", R1=0.0, R2=-100.0)
    r = compute_chromatic_focus([elem])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 20. Error: negative wavelength
# ---------------------------------------------------------------------------

def test_error_bad_wavelength():
    r = compute_chromatic_focus(_bk7_singlet(), wavelengths_nm=[-100.0])
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 21. Afocal stack: either error or valid (no crash)
# ---------------------------------------------------------------------------

def test_afocal_or_error():
    # Build a doublet where phi1 + phi2 ≈ 0 (identical elements, opposite sign)
    R = 100.0
    stack = [
        LensElement(glass="BK7", R1=R, R2=-R, separation_mm=0.0),
        LensElement(glass="BK7", R1=-R, R2=R, separation_mm=0.0),
    ]
    r = compute_chromatic_focus(stack)
    # Must not raise; either error dict or a valid report (floating-point residual)
    assert isinstance(r, (ChromaticReport, dict))


# ---------------------------------------------------------------------------
# 22. Multi-element stack: V_number is None
# ---------------------------------------------------------------------------

def test_multi_element_no_v_number():
    r = compute_chromatic_focus(_achromat_bk7_f2())
    assert isinstance(r, ChromaticReport)
    assert r.V_number is None, f"Expected V_number=None for doublet, got {r.V_number}"


# ---------------------------------------------------------------------------
# 23. Custom wavelength list returns correct key count
# ---------------------------------------------------------------------------

def test_custom_wavelengths():
    wls = [400.0, 500.0, 600.0, 700.0]
    r = compute_chromatic_focus(_bk7_singlet(), wavelengths_nm=wls)
    assert isinstance(r, ChromaticReport)
    assert len(r.per_wavelength_focal) == 4


# ---------------------------------------------------------------------------
# 24. lca_percent is non-negative
# ---------------------------------------------------------------------------

def test_lca_percent_nonneg():
    r = compute_chromatic_focus(_bk7_singlet())
    assert isinstance(r, ChromaticReport)
    assert r.lca_percent >= 0.0


# ---------------------------------------------------------------------------
# 25. mean_BFL_mm is finite and positive for converging singlet
# ---------------------------------------------------------------------------

def test_mean_bfl_finite():
    r = compute_chromatic_focus(_bk7_singlet(100.0))
    assert isinstance(r, ChromaticReport)
    assert math.isfinite(r.mean_BFL_mm)
    assert r.mean_BFL_mm > 0.0


# ---------------------------------------------------------------------------
# 26. K5 Abbe V-number ≈ 59.5
# ---------------------------------------------------------------------------

def test_k5_singlet_v_approx_59():
    n_F = sellmeier_n("K5", 0.48613)
    n_d = sellmeier_n("K5", 0.58756)
    n_C = sellmeier_n("K5", 0.65627)
    V = (n_d - 1.0) / (n_F - n_C)
    assert V == pytest.approx(59.5, abs=1.0), f"K5 V = {V}"


# ---------------------------------------------------------------------------
# 27. BK10 Abbe V-number ≈ 66.9
# ---------------------------------------------------------------------------

def test_bk10_singlet_v_approx_67():
    n_F = sellmeier_n("BK10", 0.48613)
    n_d = sellmeier_n("BK10", 0.58756)
    n_C = sellmeier_n("BK10", 0.65627)
    V = (n_d - 1.0) / (n_F - n_C)
    assert V == pytest.approx(66.9, abs=1.0), f"BK10 V = {V}"


# ---------------------------------------------------------------------------
# 28. SF11 Abbe V-number ≈ 25.4 (dense flint)
# ---------------------------------------------------------------------------

def test_sf11_v_number_approx_25():
    n_F = sellmeier_n("SF11", 0.48613)
    n_d = sellmeier_n("SF11", 0.58756)
    n_C = sellmeier_n("SF11", 0.65627)
    V = (n_d - 1.0) / (n_F - n_C)
    assert V == pytest.approx(25.4, abs=1.0), f"SF11 V = {V}"


# ---------------------------------------------------------------------------
# 29. Single wavelength: lca_FC ≈ 0 (F and C both map to the single available wl)
# ---------------------------------------------------------------------------

def test_single_wavelength_lca():
    r = compute_chromatic_focus(_bk7_singlet(), wavelengths_nm=[550.0])
    assert isinstance(r, ChromaticReport)
    # Both wl_F and wl_C resolve to 550 nm → lca_FC = 0
    assert abs(r.lca_FC_mm) < 1e-10


# ---------------------------------------------------------------------------
# 30. LLM tool happy path — BK7 singlet
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    n_d = 1.5168
    R = 2.0 * (n_d - 1.0) * 100.0
    d = _run_tool({
        "stack": [{"glass": "BK7", "R1": R, "R2": -R, "separation_mm": 0.0}],
    })
    assert d["ok"] is True
    assert "lca_FC_mm" in d
    assert math.isfinite(d["lca_FC_mm"])
    assert "V_number" in d
    assert d["V_number"] == pytest.approx(64.2, abs=0.5)


# ---------------------------------------------------------------------------
# 31. LLM tool: missing stack
# ---------------------------------------------------------------------------

def test_tool_missing_stack():
    d = _run_tool({"wavelengths_nm": [486, 587, 656]})
    assert d["ok"] is False
    assert "stack" in d.get("reason", "")


# ---------------------------------------------------------------------------
# 32. LLM tool: invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    result = json.loads(asyncio.run(run_compute_chromatic_focus(None, b"{bad json")))
    is_error = (result.get("ok") is False) or ("error" in result) or ("code" in result)
    assert is_error, f"Expected error response, got: {result}"


# ---------------------------------------------------------------------------
# 33. LLM tool: custom wavelengths
# ---------------------------------------------------------------------------

def test_tool_custom_wavelengths():
    n_d = 1.5168
    R = 2.0 * (n_d - 1.0) * 100.0
    d = _run_tool({
        "stack": [{"glass": "BK7", "R1": R, "R2": -R}],
        "wavelengths_nm": [450.0, 550.0, 650.0],
    })
    assert d["ok"] is True
    assert len(d["per_wavelength_focal_mm"]) == 3


# ---------------------------------------------------------------------------
# 34. LLM tool: BK7+F2 achromatic doublet
# ---------------------------------------------------------------------------

def test_tool_two_element_achromat():
    V1, V2 = 64.17, 36.43
    n1, n2 = 1.51680, 1.62004
    f = 100.0
    phi_total = 1.0 / f
    phi1 = phi_total * V1 / (V1 - V2)
    phi2 = -phi_total * V2 / (V1 - V2)
    R1_crown = 2.0 * (n1 - 1.0) / phi1
    R1_flint = 2.0 * (n2 - 1.0) / phi2
    d = _run_tool({
        "stack": [
            {"glass": "BK7", "R1": R1_crown, "R2": -R1_crown, "separation_mm": 0.0},
            {"glass": "F2",  "R1": R1_flint, "R2": -R1_flint, "separation_mm": 0.0},
        ],
    })
    assert d["ok"] is True
    assert abs(d["lca_FC_mm"]) < 0.10, (
        f"Achromat LCA via tool: {d['lca_FC_mm']:.6f} mm — should be < 0.1 mm"
    )
    assert d["V_number"] is None  # two-element: no scalar V_number
