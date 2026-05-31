"""
Tests for kerf_cad_core.optics.zernike_fit — Zernike polynomial wavefront fitting.

Test plan
---------
 1. pure_defocus_recovers_coefficient    — W = c4 * Z4(ρ,θ); fit recovers c4, rms < 1e-10
 2. pure_spherical_recovers_coefficient  — W = c11 * Z11(ρ,θ); fit recovers c11, rms < 1e-10
 3. pure_tip_dominant                    — W = 0.3 * Z2(ρ,θ); dominant = "tip"
 4. pure_tilt_dominant                   — W = 0.4 * Z3(ρ,θ); dominant = "tilt"
 5. tilt_plus_noise_dominant             — W = 0.5*Z3 + small_noise; dominant in {tip, tilt}
 6. noisy_fit_rms_positive               — noisy wavefront → rms_residual > 0
 7. underdetermined_raises               — < num_terms samples → ValueError
 8. underdetermined_exactly_one_sample   — 1 sample for 15-term fit → ValueError
 9. pure_astigmatism_45                  — dominant = "astigmatism_45"
10. pure_coma_y                          — dominant = "coma_y"
11. pure_trefoil_x                       — dominant = "trefoil_x"
12. zero_wavefront_all_zero_coefficients — W=0 → all coefficients ≈ 0, rms ≈ 0
13. coefficient_count_matches_num_terms  — num_terms=6 → len(coefficients) = 6
14. coefficient_names_correct_order      — first 4 names = piston/tip/tilt/defocus
15. report_to_dict_ok_key                — to_dict() has ok=True
16. piston_excluded_from_dominant        — pure piston still gives dominant ≠ "piston"
17. fit_four_terms_only                  — num_terms=4, recovers defocus with 4 coeffs
18. rms_residual_nonzero_partial_fit     — 3-term fit to 4-aberration wavefront → rms > 0
19. num_terms_out_of_range               — num_terms=0 → ValueError
20. num_terms_too_large                  — num_terms=16 → ValueError
21. invalid_sample_not_3tuple            — sample with 2 elements → TypeError
22. samples_not_a_list                   — bad samples type → TypeError
23. honest_caveat_present                — honest_caveat is a non-empty string
24. defocus_coefficient_index            — c_4 (index 3) matches recovered defocus
25. spherical_coefficient_index         — c_11 (index 10) matches recovered spherical
26. multi_aberration_dominant_largest    — c_coma = 0.4, c_defocus = 0.1 → dominant = coma_y
27. fit_over_large_grid                  — 200-sample polar grid, rms < 1e-10 for pure Z6
28. tool_happy_path                      — LLM tool returns ok=True JSON
29. tool_missing_samples                 — LLM tool returns ok=False for missing samples
30. tool_bad_json                        — LLM tool returns ok=False for invalid JSON
31. tool_under_determined                — LLM tool returns ok=False for < num_terms samples
32. tool_num_terms_kwarg                 — LLM tool accepts num_terms=4

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Noll, R.J. (1976) "Zernike polynomials and atmospheric turbulence",
    J. Opt. Soc. Am. 66, 207-211.
Born, M. & Wolf, E. (1999) "Principles of Optics", 7th ed., §9.2.
Wyant, J.C. & Creath, K. (1992) "Basic wavefront aberration theory for optical
    testing", Applied Optics and Optical Engineering XI, ch. 1.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest
import numpy as np

from kerf_cad_core.optics.zernike_fit import (
    ZernikeFitReport,
    fit_zernike_wavefront,
    _ZERNIKE_FUNCS,
    _MAX_TERMS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _polar_grid(n: int = 50) -> list[tuple[float, float]]:
    """Generate n uniform polar samples inside the unit disk."""
    rng = np.random.default_rng(42)
    rho = np.sqrt(rng.uniform(0, 1, n))  # uniform over disk area
    theta = rng.uniform(0, 2 * math.pi, n)
    return [(float(r), float(t)) for r, t in zip(rho, theta)]


def _eval_zernike(j: int, rho: float, theta: float) -> float:
    """Evaluate the j-th Noll Zernike polynomial (1-indexed) at (rho, theta)."""
    func, _ = _ZERNIKE_FUNCS[j - 1]
    rho_arr = np.array([rho])
    theta_arr = np.array([theta])
    return float(func(rho_arr, theta_arr)[0])


def _pure_wavefront(j: int, coeff: float, n: int = 80) -> list[tuple[float, float, float]]:
    """Generate n samples of W = coeff * Z_j(rho, theta)."""
    pts = _polar_grid(n)
    samples = []
    for rho, theta in pts:
        w = coeff * _eval_zernike(j, rho, theta)
        samples.append((rho, theta, w))
    return samples


# ---------------------------------------------------------------------------
# Tests 1-4: Pure single-term wavefronts
# ---------------------------------------------------------------------------

def test_pure_defocus_recovers_coefficient():
    """W = c4 * Z4(ρ,θ); fit must recover c4 ≈ 0.7 with rms < 1e-10."""
    c4 = 0.7
    samples = _pure_wavefront(j=4, coeff=c4, n=100)
    report = fit_zernike_wavefront(samples, num_terms=15)
    assert abs(report.coefficients[3] - c4) < 1e-8, (
        f"Expected c4 ≈ {c4}, got {report.coefficients[3]}"
    )
    assert report.rms_residual_waves < 1e-10, (
        f"Expected rms < 1e-10, got {report.rms_residual_waves}"
    )


def test_pure_spherical_recovers_coefficient():
    """W = c11 * Z11(ρ,θ); fit must recover c11 ≈ 0.5 with rms < 1e-10."""
    c11 = 0.5
    samples = _pure_wavefront(j=11, coeff=c11, n=100)
    report = fit_zernike_wavefront(samples, num_terms=15)
    assert abs(report.coefficients[10] - c11) < 1e-8, (
        f"Expected c11 ≈ {c11}, got {report.coefficients[10]}"
    )
    assert report.rms_residual_waves < 1e-10, (
        f"Expected rms < 1e-10, got {report.rms_residual_waves}"
    )


def test_pure_tip_dominant():
    """W = 0.3 * Z2(ρ,θ) → dominant_aberration == 'tip'."""
    samples = _pure_wavefront(j=2, coeff=0.3, n=80)
    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration == "tip", (
        f"Expected 'tip', got {report.dominant_aberration!r}"
    )


def test_pure_tilt_dominant():
    """W = 0.4 * Z3(ρ,θ) → dominant_aberration == 'tilt'."""
    samples = _pure_wavefront(j=3, coeff=0.4, n=80)
    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration == "tilt", (
        f"Expected 'tilt', got {report.dominant_aberration!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: Tilt + small noise → dominant in {tip, tilt}
# ---------------------------------------------------------------------------

def test_tilt_plus_noise_dominant():
    """W = 0.5 * Z3 + small noise → dominant_aberration in {tip, tilt}."""
    rng = np.random.default_rng(7)
    n = 100
    pts = _polar_grid(n)
    noise_scale = 0.01  # much smaller than tilt amplitude
    samples = []
    for rho, theta in pts:
        w = 0.5 * _eval_zernike(3, rho, theta) + rng.normal(0, noise_scale)
        samples.append((rho, theta, float(w)))

    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration in ("tip", "tilt"), (
        f"Expected 'tip' or 'tilt', got {report.dominant_aberration!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: Noisy fit rms > 0
# ---------------------------------------------------------------------------

def test_noisy_fit_rms_positive():
    """A wavefront with independent noise should yield rms_residual > 0."""
    rng = np.random.default_rng(99)
    n = 50
    pts = _polar_grid(n)
    # Random wavefront — not a pure Zernike polynomial
    samples = [(rho, theta, float(rng.normal(0, 0.2))) for rho, theta in pts]
    report = fit_zernike_wavefront(samples)
    assert report.rms_residual_waves > 0, (
        f"Expected rms > 0, got {report.rms_residual_waves}"
    )


# ---------------------------------------------------------------------------
# Tests 7-8: Under-determined system raises ValueError
# ---------------------------------------------------------------------------

def test_underdetermined_raises():
    """Providing < num_terms samples must raise ValueError."""
    samples = [(0.5, 0.0, 0.0)] * 14  # only 14 for a 15-term fit
    with pytest.raises(ValueError, match="Under-determined"):
        fit_zernike_wavefront(samples, num_terms=15)


def test_underdetermined_exactly_one_sample():
    """1 sample for 15-term fit must raise ValueError."""
    samples = [(0.3, 1.0, 0.1)]
    with pytest.raises(ValueError, match="Under-determined"):
        fit_zernike_wavefront(samples, num_terms=15)


# ---------------------------------------------------------------------------
# Tests 9-11: Other dominant aberrations
# ---------------------------------------------------------------------------

def test_pure_astigmatism_45_dominant():
    """W = 0.6 * Z5 → dominant_aberration == 'astigmatism_45'."""
    samples = _pure_wavefront(j=5, coeff=0.6, n=80)
    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration == "astigmatism_45", (
        f"Expected 'astigmatism_45', got {report.dominant_aberration!r}"
    )


def test_pure_coma_y_dominant():
    """W = 0.5 * Z7 → dominant_aberration == 'coma_y'."""
    samples = _pure_wavefront(j=7, coeff=0.5, n=80)
    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration == "coma_y", (
        f"Expected 'coma_y', got {report.dominant_aberration!r}"
    )


def test_pure_trefoil_x_dominant():
    """W = 0.4 * Z10 → dominant_aberration == 'trefoil_x'."""
    samples = _pure_wavefront(j=10, coeff=0.4, n=80)
    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration == "trefoil_x", (
        f"Expected 'trefoil_x', got {report.dominant_aberration!r}"
    )


# ---------------------------------------------------------------------------
# Test 12: Zero wavefront
# ---------------------------------------------------------------------------

def test_zero_wavefront_all_zero_coefficients():
    """W = 0 everywhere → all coefficients ≈ 0, rms ≈ 0."""
    pts = _polar_grid(60)
    samples = [(rho, theta, 0.0) for rho, theta in pts]
    report = fit_zernike_wavefront(samples)
    for i, c in enumerate(report.coefficients):
        assert abs(c) < 1e-12, f"Expected c[{i}] ≈ 0, got {c}"
    assert report.rms_residual_waves < 1e-12


# ---------------------------------------------------------------------------
# Tests 13-14: Report structure
# ---------------------------------------------------------------------------

def test_coefficient_count_matches_num_terms():
    """num_terms=6 → len(coefficients) == 6."""
    pts = _polar_grid(30)
    samples = [(rho, theta, 0.1) for rho, theta in pts]
    report = fit_zernike_wavefront(samples, num_terms=6)
    assert len(report.coefficients) == 6
    assert len(report.coefficient_names) == 6


def test_coefficient_names_correct_order():
    """First 4 coefficient names must be piston, tip, tilt, defocus."""
    pts = _polar_grid(30)
    samples = [(rho, theta, 0.0) for rho, theta in pts]
    report = fit_zernike_wavefront(samples, num_terms=15)
    assert report.coefficient_names[:4] == ["piston", "tip", "tilt", "defocus"]


# ---------------------------------------------------------------------------
# Test 15: to_dict() has ok=True
# ---------------------------------------------------------------------------

def test_report_to_dict_ok_key():
    """ZernikeFitReport.to_dict() must include ok=True."""
    samples = _pure_wavefront(j=4, coeff=0.2, n=30)
    report = fit_zernike_wavefront(samples)
    d = report.to_dict()
    assert d["ok"] is True


# ---------------------------------------------------------------------------
# Test 16: Piston excluded from dominant
# ---------------------------------------------------------------------------

def test_piston_excluded_from_dominant():
    """W = 1.0 * Z1(piston) only; dominant must exclude piston and name
    the next-largest non-piston term.  With purely piston wavefront all
    non-piston coefficients should be ~0, but dominant must still be some
    non-piston name."""
    samples = _pure_wavefront(j=1, coeff=1.0, n=80)
    report = fit_zernike_wavefront(samples)
    # piston is recovered; dominant aberration must NOT be piston
    assert report.dominant_aberration != "piston", (
        "dominant_aberration must exclude piston (j=1)"
    )


# ---------------------------------------------------------------------------
# Tests 17-18: Partial fit
# ---------------------------------------------------------------------------

def test_fit_four_terms_only():
    """num_terms=4 with pure defocus wavefront → recovers 4 coefficients."""
    c4 = 0.9
    samples = _pure_wavefront(j=4, coeff=c4, n=50)
    report = fit_zernike_wavefront(samples, num_terms=4)
    assert len(report.coefficients) == 4
    assert abs(report.coefficients[3] - c4) < 1e-8


def test_rms_residual_nonzero_partial_fit():
    """3-term fit to a wavefront with 4 active aberrations must leave rms > 0."""
    pts = _polar_grid(60)
    samples = []
    for rho, theta in pts:
        w = (
            0.2 * _eval_zernike(2, rho, theta)
            + 0.3 * _eval_zernike(3, rho, theta)
            + 0.4 * _eval_zernike(4, rho, theta)
            + 0.5 * _eval_zernike(11, rho, theta)  # this term won't be fitted
        )
        samples.append((rho, theta, float(w)))

    report = fit_zernike_wavefront(samples, num_terms=3)
    assert report.rms_residual_waves > 1e-6, (
        f"Expected rms > 1e-6 for partial fit, got {report.rms_residual_waves}"
    )


# ---------------------------------------------------------------------------
# Tests 19-22: Error conditions
# ---------------------------------------------------------------------------

def test_num_terms_out_of_range_zero():
    """num_terms=0 → ValueError."""
    samples = _pure_wavefront(j=1, coeff=1.0, n=20)
    with pytest.raises(ValueError):
        fit_zernike_wavefront(samples, num_terms=0)


def test_num_terms_too_large():
    """num_terms=16 → ValueError (only 15 terms implemented)."""
    samples = _pure_wavefront(j=1, coeff=1.0, n=20)
    with pytest.raises(ValueError):
        fit_zernike_wavefront(samples, num_terms=16)


def test_invalid_sample_not_3tuple():
    """Sample with 2 elements → TypeError."""
    samples = [(0.5, 1.0)] * 20  # type: ignore[list-item]
    with pytest.raises(TypeError):
        fit_zernike_wavefront(samples)  # type: ignore[arg-type]


def test_samples_not_a_list_of_3():
    """Sample element is a scalar → TypeError."""
    samples = [0.5] * 20  # type: ignore[list-item]
    with pytest.raises(TypeError):
        fit_zernike_wavefront(samples)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 23: Honest caveat present
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    """honest_caveat must be a non-empty string."""
    samples = _pure_wavefront(j=4, coeff=0.5, n=30)
    report = fit_zernike_wavefront(samples)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 20


# ---------------------------------------------------------------------------
# Tests 24-25: Coefficient indices match Noll ordering
# ---------------------------------------------------------------------------

def test_defocus_coefficient_index():
    """c_4 is at index 3 (0-indexed) and matches the known defocus amplitude."""
    c4 = 1.23
    samples = _pure_wavefront(j=4, coeff=c4, n=100)
    report = fit_zernike_wavefront(samples)
    assert report.coefficient_names[3] == "defocus"
    assert abs(report.coefficients[3] - c4) < 1e-8


def test_spherical_coefficient_index():
    """c_11 is at index 10 (0-indexed) and matches the known spherical amplitude."""
    c11 = 0.88
    samples = _pure_wavefront(j=11, coeff=c11, n=100)
    report = fit_zernike_wavefront(samples)
    assert report.coefficient_names[10] == "spherical"
    assert abs(report.coefficients[10] - c11) < 1e-8


# ---------------------------------------------------------------------------
# Test 26: Multi-aberration dominant is the largest
# ---------------------------------------------------------------------------

def test_multi_aberration_dominant_largest():
    """W = 0.1*Z4(defocus) + 0.4*Z7(coma_y) → dominant = 'coma_y'."""
    pts = _polar_grid(100)
    samples = []
    for rho, theta in pts:
        w = (
            0.1 * _eval_zernike(4, rho, theta)
            + 0.4 * _eval_zernike(7, rho, theta)
        )
        samples.append((rho, theta, float(w)))

    report = fit_zernike_wavefront(samples)
    assert report.dominant_aberration == "coma_y", (
        f"Expected 'coma_y', got {report.dominant_aberration!r}"
    )


# ---------------------------------------------------------------------------
# Test 27: Large polar grid fit
# ---------------------------------------------------------------------------

def test_fit_over_large_grid_pure_z6():
    """200-sample polar grid, W = 0.75 * Z6(astigmatism_0), rms < 1e-10."""
    c6 = 0.75
    samples = _pure_wavefront(j=6, coeff=c6, n=200)
    report = fit_zernike_wavefront(samples)
    assert abs(report.coefficients[5] - c6) < 1e-8
    assert report.rms_residual_waves < 1e-10


# ---------------------------------------------------------------------------
# Tests 28-32: LLM tool integration
# ---------------------------------------------------------------------------

def _make_tool_samples(j: int, coeff: float, n: int = 30) -> list:
    """Return samples as JSON-serialisable list of [rho, theta, W]."""
    raw = _pure_wavefront(j=j, coeff=coeff, n=n)
    return [[r, t, w] for r, t, w in raw]


def test_tool_happy_path():
    """LLM tool run_fit_zernike_wavefront returns ok=True with a coefficient list."""
    from kerf_cad_core.optics.tools import run_fit_zernike_wavefront

    sample_list = _make_tool_samples(j=4, coeff=0.6, n=40)
    payload = json.dumps({"samples": sample_list, "num_terms": 15})

    result = asyncio.get_event_loop().run_until_complete(
        run_fit_zernike_wavefront(None, payload.encode())
    )
    data = json.loads(result)
    assert data.get("ok") is True, f"Expected ok=True, got {data}"
    assert "coefficients" in data
    assert len(data["coefficients"]) == 15
    assert "dominant_aberration" in data
    assert "rms_residual_waves" in data


def test_tool_missing_samples():
    """LLM tool returns ok=False when 'samples' is absent."""
    from kerf_cad_core.optics.tools import run_fit_zernike_wavefront

    payload = json.dumps({"num_terms": 15})
    result = asyncio.get_event_loop().run_until_complete(
        run_fit_zernike_wavefront(None, payload.encode())
    )
    data = json.loads(result)
    assert data.get("ok") is False


def test_tool_bad_json():
    """LLM tool returns an error payload for malformed JSON (no ok=True)."""
    from kerf_cad_core.optics.tools import run_fit_zernike_wavefront

    result = asyncio.get_event_loop().run_until_complete(
        run_fit_zernike_wavefront(None, b"{not valid json}")
    )
    data = json.loads(result)
    # err_payload returns {error: ..., code: ...}; ok=True must NOT be present
    assert data.get("ok") is not True


def test_tool_under_determined():
    """LLM tool returns ok=False when samples < num_terms."""
    from kerf_cad_core.optics.tools import run_fit_zernike_wavefront

    # Only 5 samples for a 15-term fit
    sample_list = [[0.5 * i / 5, 0.0, 0.0] for i in range(5)]
    payload = json.dumps({"samples": sample_list, "num_terms": 15})
    result = asyncio.get_event_loop().run_until_complete(
        run_fit_zernike_wavefront(None, payload.encode())
    )
    data = json.loads(result)
    assert data.get("ok") is False
    assert "Under-determined" in data.get("reason", "")


def test_tool_num_terms_kwarg():
    """LLM tool respects num_terms=4 and returns 4 coefficients."""
    from kerf_cad_core.optics.tools import run_fit_zernike_wavefront

    sample_list = _make_tool_samples(j=4, coeff=0.5, n=30)
    payload = json.dumps({"samples": sample_list, "num_terms": 4})
    result = asyncio.get_event_loop().run_until_complete(
        run_fit_zernike_wavefront(None, payload.encode())
    )
    data = json.loads(result)
    assert data.get("ok") is True
    assert len(data["coefficients"]) == 4
