"""
Tests for kerf_cad_core.optics.mtf_diffraction — OPTICS-MTF-DIFFRACTION-LIMITED.

Test plan
---------
1.  cutoff_freq_oracle_550nm_f4         — λ=550nm, F/4: ν_0=1/(550e-6·4)=454.5 cyc/mm (within 0.1%)
2.  mtf_at_zero_is_one                  — MTF(0) = 1.0 exactly
3.  mtf_at_cutoff_is_zero               — MTF(ν_0) = 0.0 exactly
4.  mtf_at_half_cutoff_analytic         — MTF(ν_0/2) = (2/π)[π/3 − (1/2)·(√3/2)] ≈ 0.391 (within 0.1%)
5.  mtf_is_monotone_decreasing          — every sample ≤ previous
6.  curve_length_matches_num_samples    — len(mtf_curve) == num_samples
7.  default_curve_length_200            — default num_samples gives 200 points
8.  frequencies_non_negative            — all ν values in curve are ≥ 0
9.  mtf_values_in_unit_range            — all MTF values in [0, 1]
10. max_freq_clamps_curve               — explicit max_freq_cyc_per_mm is respected
11. mtf_at_50_percent_within_range      — mtf_at_50_percent is between 0 and ν_0
12. to_dict_ok_key                      — MTFReport.to_dict() has ok=True
13. to_dict_has_honest_caveat           — honest_caveat contains "DIFFRACTION-LIMITED"
14. honest_caveat_mentions_aberrations  — caveat mentions aberrations
15. shorter_wavelength_higher_cutoff    — ν_0(450nm) > ν_0(650nm)
16. smaller_fnumber_higher_cutoff       — ν_0(f/2) > ν_0(f/4)
17. mtf_above_cutoff_is_zero            — MTF(1.5·ν_0) = 0.0
18. error_nonpositive_wavelength        — returns error for wavelength_nm <= 0
19. error_nonpositive_fnumber           — returns error for f_number <= 0
20. error_few_samples                   — returns error for num_samples < 2
21. error_bad_max_freq                  — returns error for max_freq_cyc_per_mm <= 0
22. tool_happy_path                     — LLM tool returns ok JSON with cutoff_freq
23. tool_missing_wavelength             — LLM tool returns error for missing wavelength_nm
24. tool_missing_fnumber                — LLM tool returns error for missing f_number
25. tool_bad_json                       — LLM tool handles invalid JSON
26. tool_custom_num_samples             — LLM tool accepts optional num_samples
27. tool_custom_max_freq                — LLM tool accepts optional max_freq_cyc_per_mm
28. cutoff_formula_various_configs      — verify ν_0=1/(λ·F#) for several (λ, F#) pairs
29. mtf_curve_first_freq_is_zero        — first sample is at ν=0
30. re_export_from_optics_init          — compute_diffraction_mtf importable from optics package
31. mtf_at_75_percent_of_cutoff         — MTF(0.75·ν_0) is between 0 and 0.391 (not above half)
32. mtf_at_25_percent_of_cutoff         — MTF(0.25·ν_0) > MTF(0.5·ν_0) (monotone check)

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., Roberts & Co., 2005. §6.4.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017. §11.3.3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.mtf_diffraction import (
    MTFReport,
    compute_diffraction_mtf,
    _mtf_value,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

WL_NM = 550.0     # green light
F_NUM = 4.0       # f/4

# Expected cutoff: ν_0 = 1 / (550e-6 mm · 4) = 454.545... cyc/mm
NU_0_EXPECTED = 1.0 / (550e-6 * 4.0)


def _default_report() -> MTFReport:
    result = compute_diffraction_mtf(WL_NM, F_NUM)
    assert isinstance(result, MTFReport), f"Expected MTFReport, got {result!r}"
    return result


# ---------------------------------------------------------------------------
# Test 1 — cutoff frequency oracle
# ---------------------------------------------------------------------------

def test_cutoff_freq_oracle_550nm_f4():
    """λ=550nm, F/4: ν_0=1/(550e-6·4)=454.545 cyc/mm (within 0.1%)."""
    r = _default_report()
    rel_err = abs(r.cutoff_freq_cyc_per_mm - NU_0_EXPECTED) / NU_0_EXPECTED
    assert rel_err < 1e-3, (
        f"cutoff_freq_cyc_per_mm={r.cutoff_freq_cyc_per_mm:.4f}, "
        f"expected≈{NU_0_EXPECTED:.4f}, rel_err={rel_err:.2e}"
    )


# ---------------------------------------------------------------------------
# Test 2 — MTF(0) = 1.0 exactly
# ---------------------------------------------------------------------------

def test_mtf_at_zero_is_one():
    """The closed-form expression gives MTF(0) = 1.0 by convention."""
    assert _mtf_value(0.0) == 1.0


# ---------------------------------------------------------------------------
# Test 3 — MTF(ν_0) = 0 exactly
# ---------------------------------------------------------------------------

def test_mtf_at_cutoff_is_zero():
    """At s=1 (ν=ν_0), MTF must be exactly 0."""
    assert _mtf_value(1.0) == 0.0
    assert _mtf_value(1.5) == 0.0


def test_mtf_at_cutoff_is_zero_via_curve():
    """
    The sample nearest ν_0 should have MTF close to 0.
    Note: with default max_freq=1.05·ν_0 no sample lands exactly on ν_0, so
    the nearest sample may be a few steps short of the cutoff; use a loose
    tolerance of 5e-3 (well under 1% of the [0,1] range).
    """
    r = compute_diffraction_mtf(WL_NM, F_NUM, num_samples=201)
    assert isinstance(r, MTFReport)
    nu_0 = r.cutoff_freq_cyc_per_mm
    closest = min(r.mtf_curve, key=lambda pt: abs(pt[0] - nu_0))
    assert abs(closest[1]) < 5e-3, (
        f"MTF at ν≈ν_0 expected ≈0, got {closest[1]:.2e}"
    )


# ---------------------------------------------------------------------------
# Test 4 — MTF(ν_0/2) analytic value
# ---------------------------------------------------------------------------

def test_mtf_at_half_cutoff_analytic():
    """
    MTF(0.5·ν_0) = (2/π)[arccos(0.5) − 0.5·√(1−0.25)]
                  = (2/π)[π/3 − 0.5·(√3/2)]
                  ≈ 0.3906

    Reference: Goodman §6.4, canonical value.
    """
    s = 0.5
    analytic = (2.0 / math.pi) * (math.acos(s) - s * math.sqrt(1.0 - s * s))
    computed = _mtf_value(s)
    rel_err = abs(computed - analytic) / analytic
    assert rel_err < 1e-3, (
        f"MTF(0.5·ν_0)={computed:.6f}, analytic={analytic:.6f}, rel_err={rel_err:.2e}"
    )
    # Also check the absolute value is close to 0.391
    assert abs(analytic - 0.3906) < 5e-4, (
        f"analytic={analytic:.6f}, expected ≈0.3906"
    )


# ---------------------------------------------------------------------------
# Test 5 — Monotone decreasing
# ---------------------------------------------------------------------------

def test_mtf_is_monotone_decreasing():
    """MTF must be non-increasing across the whole frequency range."""
    r = _default_report()
    for i in range(1, len(r.mtf_curve)):
        nu_prev, m_prev = r.mtf_curve[i - 1]
        nu_curr, m_curr = r.mtf_curve[i]
        assert m_curr <= m_prev + 1e-12, (
            f"MTF non-monotone at ν={nu_curr:.3f}: MTF({nu_prev:.3f})={m_prev:.6f} "
            f"< MTF({nu_curr:.3f})={m_curr:.6f}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Curve length matches num_samples
# ---------------------------------------------------------------------------

def test_curve_length_matches_num_samples():
    for n in (10, 50, 200):
        r = compute_diffraction_mtf(WL_NM, F_NUM, num_samples=n)
        assert isinstance(r, MTFReport)
        assert len(r.mtf_curve) == n, f"num_samples={n}, len={len(r.mtf_curve)}"


# ---------------------------------------------------------------------------
# Test 7 — Default curve length is 200
# ---------------------------------------------------------------------------

def test_default_curve_length_200():
    r = _default_report()
    assert len(r.mtf_curve) == 200


# ---------------------------------------------------------------------------
# Test 8 — Frequencies non-negative
# ---------------------------------------------------------------------------

def test_frequencies_non_negative():
    r = _default_report()
    for nu, _ in r.mtf_curve:
        assert nu >= 0.0, f"negative frequency ν={nu}"


# ---------------------------------------------------------------------------
# Test 9 — MTF values in [0, 1]
# ---------------------------------------------------------------------------

def test_mtf_values_in_unit_range():
    r = _default_report()
    for nu, m in r.mtf_curve:
        assert 0.0 <= m <= 1.0 + 1e-12, (
            f"MTF out of [0,1] at ν={nu:.3f}: MTF={m:.6f}"
        )


# ---------------------------------------------------------------------------
# Test 10 — max_freq_cyc_per_mm clamps the curve
# ---------------------------------------------------------------------------

def test_max_freq_clamps_curve():
    max_f = 200.0
    r = compute_diffraction_mtf(WL_NM, F_NUM, num_samples=50, max_freq_cyc_per_mm=max_f)
    assert isinstance(r, MTFReport)
    # Last frequency in the curve should equal max_f
    assert abs(r.mtf_curve[-1][0] - max_f) < 1e-9, (
        f"last freq={r.mtf_curve[-1][0]:.6f}, expected {max_f}"
    )


# ---------------------------------------------------------------------------
# Test 11 — mtf_at_50_percent within range [0, ν_0]
# ---------------------------------------------------------------------------

def test_mtf_at_50_percent_within_range():
    r = _default_report()
    assert 0.0 <= r.mtf_at_50_percent <= r.cutoff_freq_cyc_per_mm, (
        f"mtf_at_50_percent={r.mtf_at_50_percent:.3f} outside "
        f"[0, {r.cutoff_freq_cyc_per_mm:.3f}]"
    )


# ---------------------------------------------------------------------------
# Test 12 — to_dict has ok=True
# ---------------------------------------------------------------------------

def test_to_dict_ok_key():
    r = _default_report()
    d = r.to_dict()
    assert d.get("ok") is True


# ---------------------------------------------------------------------------
# Test 13 — honest_caveat contains "DIFFRACTION-LIMITED"
# ---------------------------------------------------------------------------

def test_to_dict_has_honest_caveat():
    r = _default_report()
    assert "DIFFRACTION-LIMITED" in r.honest_caveat


# ---------------------------------------------------------------------------
# Test 14 — caveat mentions aberrations
# ---------------------------------------------------------------------------

def test_honest_caveat_mentions_aberrations():
    r = _default_report()
    assert "aberration" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 15 — shorter wavelength → higher cutoff
# ---------------------------------------------------------------------------

def test_shorter_wavelength_higher_cutoff():
    r_blue = compute_diffraction_mtf(450.0, F_NUM)
    r_red  = compute_diffraction_mtf(650.0, F_NUM)
    assert isinstance(r_blue, MTFReport)
    assert isinstance(r_red, MTFReport)
    assert r_blue.cutoff_freq_cyc_per_mm > r_red.cutoff_freq_cyc_per_mm


# ---------------------------------------------------------------------------
# Test 16 — smaller F-number → higher cutoff
# ---------------------------------------------------------------------------

def test_smaller_fnumber_higher_cutoff():
    r_f2 = compute_diffraction_mtf(WL_NM, 2.0)
    r_f4 = compute_diffraction_mtf(WL_NM, 4.0)
    assert isinstance(r_f2, MTFReport)
    assert isinstance(r_f4, MTFReport)
    assert r_f2.cutoff_freq_cyc_per_mm > r_f4.cutoff_freq_cyc_per_mm


# ---------------------------------------------------------------------------
# Test 17 — MTF above cutoff is zero
# ---------------------------------------------------------------------------

def test_mtf_above_cutoff_is_zero():
    # _mtf_value with s > 1
    assert _mtf_value(1.5) == 0.0
    assert _mtf_value(2.0) == 0.0


# ---------------------------------------------------------------------------
# Test 18 — error for non-positive wavelength
# ---------------------------------------------------------------------------

def test_error_nonpositive_wavelength():
    r = compute_diffraction_mtf(-10.0, F_NUM)
    assert isinstance(r, dict)
    assert r.get("ok") is False
    r2 = compute_diffraction_mtf(0.0, F_NUM)
    assert isinstance(r2, dict)
    assert r2.get("ok") is False


# ---------------------------------------------------------------------------
# Test 19 — error for non-positive f_number
# ---------------------------------------------------------------------------

def test_error_nonpositive_fnumber():
    r = compute_diffraction_mtf(WL_NM, -1.0)
    assert isinstance(r, dict)
    assert r.get("ok") is False
    r2 = compute_diffraction_mtf(WL_NM, 0.0)
    assert isinstance(r2, dict)
    assert r2.get("ok") is False


# ---------------------------------------------------------------------------
# Test 20 — error for num_samples < 2
# ---------------------------------------------------------------------------

def test_error_few_samples():
    r = compute_diffraction_mtf(WL_NM, F_NUM, num_samples=1)
    assert isinstance(r, dict)
    assert r.get("ok") is False


# ---------------------------------------------------------------------------
# Test 21 — error for max_freq <= 0
# ---------------------------------------------------------------------------

def test_error_bad_max_freq():
    r = compute_diffraction_mtf(WL_NM, F_NUM, max_freq_cyc_per_mm=-5.0)
    assert isinstance(r, dict)
    assert r.get("ok") is False
    r2 = compute_diffraction_mtf(WL_NM, F_NUM, max_freq_cyc_per_mm=0.0)
    assert isinstance(r2, dict)
    assert r2.get("ok") is False


# ---------------------------------------------------------------------------
# Test 22 — LLM tool happy path
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    from kerf_cad_core.optics.tools import run_diffraction_mtf

    async def _run():
        payload = json.dumps({"wavelength_nm": 550.0, "f_number": 4.0})
        return await run_diffraction_mtf(None, payload.encode())

    out = asyncio.get_event_loop().run_until_complete(_run())
    d = json.loads(out)
    assert d.get("ok") is True
    assert "cutoff_freq_cyc_per_mm" in d
    assert abs(d["cutoff_freq_cyc_per_mm"] - NU_0_EXPECTED) / NU_0_EXPECTED < 1e-3


# ---------------------------------------------------------------------------
# Test 23 — LLM tool missing wavelength_nm
# ---------------------------------------------------------------------------

def test_tool_missing_wavelength():
    from kerf_cad_core.optics.tools import run_diffraction_mtf

    async def _run():
        payload = json.dumps({"f_number": 4.0})
        return await run_diffraction_mtf(None, payload.encode())

    out = asyncio.get_event_loop().run_until_complete(_run())
    d = json.loads(out)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# Test 24 — LLM tool missing f_number
# ---------------------------------------------------------------------------

def test_tool_missing_fnumber():
    from kerf_cad_core.optics.tools import run_diffraction_mtf

    async def _run():
        payload = json.dumps({"wavelength_nm": 550.0})
        return await run_diffraction_mtf(None, payload.encode())

    out = asyncio.get_event_loop().run_until_complete(_run())
    d = json.loads(out)
    assert d.get("ok") is False


# ---------------------------------------------------------------------------
# Test 25 — LLM tool invalid JSON
# ---------------------------------------------------------------------------

def test_tool_bad_json():
    from kerf_cad_core.optics.tools import run_diffraction_mtf

    async def _run():
        return await run_diffraction_mtf(None, b"not-valid-json{{{")

    out = asyncio.get_event_loop().run_until_complete(_run())
    d = json.loads(out)
    # err_payload returns {"error": ..., "code": "BAD_ARGS"} for JSON parse errors
    assert d.get("ok") is False or d.get("code") == "BAD_ARGS" or "error" in d


# ---------------------------------------------------------------------------
# Test 26 — LLM tool accepts optional num_samples
# ---------------------------------------------------------------------------

def test_tool_custom_num_samples():
    from kerf_cad_core.optics.tools import run_diffraction_mtf

    async def _run():
        payload = json.dumps({"wavelength_nm": 550.0, "f_number": 4.0, "num_samples": 50})
        return await run_diffraction_mtf(None, payload.encode())

    out = asyncio.get_event_loop().run_until_complete(_run())
    d = json.loads(out)
    assert d.get("ok") is True
    assert len(d["mtf_curve"]) == 50


# ---------------------------------------------------------------------------
# Test 27 — LLM tool accepts optional max_freq_cyc_per_mm
# ---------------------------------------------------------------------------

def test_tool_custom_max_freq():
    from kerf_cad_core.optics.tools import run_diffraction_mtf

    async def _run():
        payload = json.dumps({
            "wavelength_nm": 550.0,
            "f_number": 4.0,
            "max_freq_cyc_per_mm": 300.0,
        })
        return await run_diffraction_mtf(None, payload.encode())

    out = asyncio.get_event_loop().run_until_complete(_run())
    d = json.loads(out)
    assert d.get("ok") is True
    # Last frequency should be ≈ 300.0
    last_freq = d["mtf_curve"][-1][0]
    assert abs(last_freq - 300.0) < 1e-6, f"last_freq={last_freq}"


# ---------------------------------------------------------------------------
# Test 28 — cutoff formula for various (λ, F#) pairs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wl_nm,fn", [
    (486.0, 2.8),   # F-line, f/2.8
    (656.0, 8.0),   # C-line, f/8
    (400.0, 1.4),   # near-UV, fast lens
    (1000.0, 11.0), # near-IR, slow lens
])
def test_cutoff_formula_various_configs(wl_nm, fn):
    """ν_0 = 1/(λ_mm · F#) for any (λ, F#) pair."""
    r = compute_diffraction_mtf(wl_nm, fn)
    assert isinstance(r, MTFReport)
    expected_nu_0 = 1.0 / (wl_nm * 1e-6 * fn)
    rel_err = abs(r.cutoff_freq_cyc_per_mm - expected_nu_0) / expected_nu_0
    assert rel_err < 1e-10, (
        f"wl={wl_nm}nm, F/{fn}: ν_0={r.cutoff_freq_cyc_per_mm:.4f}, "
        f"expected={expected_nu_0:.4f}, rel_err={rel_err:.2e}"
    )


# ---------------------------------------------------------------------------
# Test 29 — first sample is at ν=0
# ---------------------------------------------------------------------------

def test_mtf_curve_first_freq_is_zero():
    r = _default_report()
    nu_first, m_first = r.mtf_curve[0]
    assert nu_first == 0.0
    assert m_first == 1.0


# ---------------------------------------------------------------------------
# Test 30 — re-export from optics/__init__.py
# ---------------------------------------------------------------------------

def test_re_export_from_optics_init():
    from kerf_cad_core.optics import compute_diffraction_mtf as cdf, MTFReport as R  # noqa: F401
    assert callable(cdf)
    r = cdf(550.0, 4.0)
    assert isinstance(r, R)


# ---------------------------------------------------------------------------
# Test 31 — MTF(0.75·ν_0) < MTF(0.5·ν_0)  (monotone, well below 0.5)
# ---------------------------------------------------------------------------

def test_mtf_at_75_percent_of_cutoff():
    m_50 = _mtf_value(0.5)
    m_75 = _mtf_value(0.75)
    assert m_75 < m_50, f"MTF(0.75)={m_75:.4f} >= MTF(0.5)={m_50:.4f}"
    assert m_75 > 0.0, "MTF(0.75·ν_0) should be positive"


# ---------------------------------------------------------------------------
# Test 32 — MTF(0.25·ν_0) > MTF(0.5·ν_0)
# ---------------------------------------------------------------------------

def test_mtf_at_25_percent_of_cutoff():
    m_25 = _mtf_value(0.25)
    m_50 = _mtf_value(0.5)
    assert m_25 > m_50, f"MTF(0.25)={m_25:.4f} should be > MTF(0.5)={m_50:.4f}"
