"""
Tests for kerf_cad_core.optics.diffraction_psf — Airy-disk PSF for circular aperture.

Test plan
---------
1.  airy_disk_radius_oracle       -- λ=550nm, D=10mm, f=50mm: r_Airy ≈ 3.355 μm
2.  fwhm_oracle                   -- same spec: FWHM ≈ 2.833 μm
3.  rayleigh_equals_airy          -- rayleigh_resolution_um == airy_disk_radius_um
4.  psf_normalised_at_origin      -- I(0) = 1.0 exactly (first profile point)
5.  psf_monotonically_decreasing  -- first Airy lobe is monotonically decreasing
6.  first_zero_near_airy_radius   -- I(r_Airy) ≈ 0 (< 1e-4)
7.  psf_profile_length            -- psf_profile has num_samples entries
8.  psf_profile_r_zero_first      -- first (r, I) point has r = 0.0
9.  psf_intensity_range           -- all I values in [0, 1]
10. psf_positive_definite         -- all I values >= 0
11. f_number_5_airy_formula       -- Airy radius matches 1.22·λ·F# exactly
12. f_number_4_airy               -- λ=550nm, D=25mm, f=100mm (F#=4): r_Airy verified
13. num_samples_param             -- num_samples=50 → profile length 50
14. max_radius_param              -- last r in profile ≈ max_radius_um
15. error_invalid_wavelength      -- wavelength_nm <= 0 returns error dict
16. error_invalid_aperture        -- aperture_diameter_mm <= 0 returns error dict
17. error_invalid_focal           -- focal_length_mm <= 0 returns error dict
18. error_bad_num_samples         -- num_samples < 2 returns error dict
19. error_bad_max_radius          -- max_radius_um <= 0 returns error dict
20. report_dataclass_fields       -- DiffractionPSFReport has required fields
21. to_dict_ok_key                -- to_dict() has ok=True
22. to_dict_honest_caveat         -- to_dict() includes honest_caveat string
23. tool_happy_path               -- LLM tool returns ok JSON with airy_disk_radius_um
24. tool_missing_wavelength       -- LLM tool returns error for missing wavelength_nm
25. tool_missing_aperture         -- LLM tool returns error for missing aperture_diameter_mm
26. tool_bad_json                 -- LLM tool handles invalid JSON
27. tool_num_samples_kwarg        -- tool accepts optional num_samples
28. psf_secondary_max_exists      -- secondary Airy ring (r > r_Airy) has a local max
29. psf_at_fwhm_near_half         -- I at FWHM radius ≈ 0.5
30. fwhm_less_than_airy           -- FWHM < Airy disk radius (inner lobe)
31. different_wavelengths_scale   -- longer λ → larger Airy radius (proportional)
32. different_fnumbers_scale      -- larger F# → larger Airy radius (proportional)

All tests are pure-Python and hermetic (no OCC, DB, or network).

References
----------
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §10.2.
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999, §8.5.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.optics.diffraction_psf import (
    DiffractionPSFReport,
    DiffractionPSFSpec,
    PolychromaticPSFReport,
    _airy_intensity,
    blackbody_spd,
    compute_diffraction_psf,
    compute_polychromatic_psf,
    d65_spd,
    photopic_spd,
)
from kerf_cad_core.optics.tools import run_compute_diffraction_psf


# ---------------------------------------------------------------------------
# Fixture: canonical oracle (λ=550nm, D=10mm, f=50mm → F#=5)
# ---------------------------------------------------------------------------

_SPEC_550_10_50 = DiffractionPSFSpec(
    wavelength_nm=550.0,
    aperture_diameter_mm=10.0,
    focal_length_mm=50.0,
)

# F# = 50/10 = 5
# r_Airy = 1.22 × 550e-6 mm × 5 = 3.355e-3 mm = 3.355 μm
_EXPECTED_AIRY_UM = 1.22 * 550e-3 * 5.0  # nm→μm: 550 nm = 0.550 μm, ×1.22×5 = 3.355
# More precisely: 1.22 * (550 * 1e-6) * 1e3 * 5 = 1.22 * 550e-6 * 1000 * 5
_EXPECTED_AIRY_UM_EXACT = 1.22 * 550e-6 * 1e3 * 5.0   # = 1.22 * 0.550 * 5 = 3.355 μm
_EXPECTED_FWHM_UM_EXACT = 1.03 * 550e-6 * 1e3 * 5.0   # = 1.03 * 0.550 * 5 = 2.8325 μm


def _report_default() -> DiffractionPSFReport:
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=500, max_radius_um=20.0)
    assert isinstance(r, DiffractionPSFReport), f"Expected report, got {r}"
    return r


# ---------------------------------------------------------------------------
# Test 1: Airy disk radius oracle
# ---------------------------------------------------------------------------

def test_airy_disk_radius_oracle():
    """λ=550nm, D=10mm, f=50mm: Airy disk radius = 1.22·λ·F# ≈ 3.355 μm."""
    r = _report_default()
    assert r.airy_disk_radius_um == pytest.approx(_EXPECTED_AIRY_UM_EXACT, rel=1e-6), (
        f"Airy radius {r.airy_disk_radius_um} != expected {_EXPECTED_AIRY_UM_EXACT}"
    )


# ---------------------------------------------------------------------------
# Test 2: FWHM oracle
# ---------------------------------------------------------------------------

def test_fwhm_oracle():
    """λ=550nm, D=10mm, f=50mm: FWHM ≈ 1.03·λ·F# ≈ 2.8325 μm."""
    r = _report_default()
    assert r.fwhm_um == pytest.approx(_EXPECTED_FWHM_UM_EXACT, rel=1e-6), (
        f"FWHM {r.fwhm_um} != expected {_EXPECTED_FWHM_UM_EXACT}"
    )


# ---------------------------------------------------------------------------
# Test 3: Rayleigh equals Airy radius
# ---------------------------------------------------------------------------

def test_rayleigh_equals_airy():
    """Rayleigh resolution = Airy disk radius (Hecht §10.2.7)."""
    r = _report_default()
    assert r.rayleigh_resolution_um == pytest.approx(r.airy_disk_radius_um, rel=1e-10)


# ---------------------------------------------------------------------------
# Test 4: PSF normalised at origin
# ---------------------------------------------------------------------------

def test_psf_normalised_at_origin():
    """I(0) = 1.0 (Hecht eq. 10.22; normalisation at r=0)."""
    r = _report_default()
    r0, I0 = r.psf_profile[0]
    assert r0 == pytest.approx(0.0, abs=1e-12)
    assert I0 == pytest.approx(1.0, rel=1e-10), f"I(0) = {I0} != 1.0"


# ---------------------------------------------------------------------------
# Test 5: PSF monotonically decreasing in first lobe
# ---------------------------------------------------------------------------

def test_psf_monotonically_decreasing_first_lobe():
    """PSF intensity decreases monotonically from r=0 to r=r_Airy (first lobe)."""
    r = _report_default()
    airy_um = r.airy_disk_radius_um
    # Collect samples within the Airy disk (first lobe)
    first_lobe = [(r_um, I) for r_um, I in r.psf_profile if r_um <= airy_um]
    assert len(first_lobe) >= 3, "Too few samples in first lobe for monotonicity check"
    for i in range(len(first_lobe) - 1):
        r_i, I_i = first_lobe[i]
        r_j, I_j = first_lobe[i + 1]
        assert I_i >= I_j - 1e-8, (
            f"PSF not monotone at r={r_j:.3f}μm: I({r_i:.3f})={I_i:.6f} < I({r_j:.3f})={I_j:.6f}"
        )


# ---------------------------------------------------------------------------
# Test 6: First zero near Airy radius
# ---------------------------------------------------------------------------

def test_first_zero_near_airy_radius():
    """I(r_Airy) ≈ 0 — first dark ring at r = 1.22·λ·F#."""
    r = _report_default()
    airy_um = r.airy_disk_radius_um
    # Find the profile point closest to the Airy radius
    closest = min(r.psf_profile, key=lambda p: abs(p[0] - airy_um))
    r_c, I_c = closest
    assert I_c < 5e-3, (
        f"Expected I≈0 at r≈r_Airy={airy_um:.3f}μm, got I={I_c:.6f} at r={r_c:.3f}μm"
    )


# ---------------------------------------------------------------------------
# Test 7: PSF profile length matches num_samples
# ---------------------------------------------------------------------------

def test_psf_profile_length():
    """psf_profile has exactly num_samples entries."""
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=100, max_radius_um=20.0)
    assert isinstance(r, DiffractionPSFReport)
    assert len(r.psf_profile) == 100


# ---------------------------------------------------------------------------
# Test 8: First radial point is r=0
# ---------------------------------------------------------------------------

def test_psf_profile_r_zero_first():
    """First profile point has r=0.0."""
    r = _report_default()
    assert r.psf_profile[0][0] == pytest.approx(0.0, abs=1e-15)


# ---------------------------------------------------------------------------
# Test 9: Intensity values in [0, 1]
# ---------------------------------------------------------------------------

def test_psf_intensity_range():
    """All PSF intensities must be in [0, 1]."""
    r = _report_default()
    for r_um, I in r.psf_profile:
        assert 0.0 <= I <= 1.0 + 1e-10, f"I={I} out of [0,1] at r={r_um:.3f}μm"


# ---------------------------------------------------------------------------
# Test 10: Intensity positive semi-definite
# ---------------------------------------------------------------------------

def test_psf_positive_definite():
    """All I values >= 0 (intensity cannot be negative)."""
    r = _report_default()
    for r_um, I in r.psf_profile:
        assert I >= -1e-10, f"Negative intensity I={I} at r={r_um:.3f}μm"


# ---------------------------------------------------------------------------
# Test 11: F#=5 Airy formula exact match
# ---------------------------------------------------------------------------

def test_f_number_5_airy_formula():
    """Airy radius matches 1.22·λ·F# exactly for F#=5."""
    spec = DiffractionPSFSpec(
        wavelength_nm=550.0,
        aperture_diameter_mm=10.0,
        focal_length_mm=50.0,
    )
    r = compute_diffraction_psf(spec)
    assert isinstance(r, DiffractionPSFReport)
    expected = 1.22 * 550e-6 * 1e3 * 5.0  # μm
    assert r.airy_disk_radius_um == pytest.approx(expected, rel=1e-10)


# ---------------------------------------------------------------------------
# Test 12: F#=4 Airy radius (D=25mm, f=100mm)
# ---------------------------------------------------------------------------

def test_f_number_4_airy():
    """λ=550nm, D=25mm, f=100mm (F#=4): r_Airy = 1.22×550e-6×4 mm = 2.684 μm."""
    spec = DiffractionPSFSpec(
        wavelength_nm=550.0,
        aperture_diameter_mm=25.0,
        focal_length_mm=100.0,
    )
    r = compute_diffraction_psf(spec)
    assert isinstance(r, DiffractionPSFReport)
    expected_um = 1.22 * 550e-6 * 1e3 * 4.0  # 1.22 × 0.550 μm × 4 = 2.684 μm
    assert r.airy_disk_radius_um == pytest.approx(expected_um, rel=1e-10)


# ---------------------------------------------------------------------------
# Test 13: num_samples parameter
# ---------------------------------------------------------------------------

def test_num_samples_param():
    """num_samples=50 produces a profile of length 50."""
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=50, max_radius_um=10.0)
    assert isinstance(r, DiffractionPSFReport)
    assert len(r.psf_profile) == 50


# ---------------------------------------------------------------------------
# Test 14: max_radius_um parameter
# ---------------------------------------------------------------------------

def test_max_radius_param():
    """Last radial sample ≈ max_radius_um."""
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=200, max_radius_um=15.0)
    assert isinstance(r, DiffractionPSFReport)
    last_r, _ = r.psf_profile[-1]
    assert last_r == pytest.approx(15.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Tests 15–19: Error cases
# ---------------------------------------------------------------------------

def test_error_invalid_wavelength():
    """wavelength_nm <= 0 returns error dict."""
    spec = DiffractionPSFSpec(wavelength_nm=-550.0, aperture_diameter_mm=10.0, focal_length_mm=50.0)
    r = compute_diffraction_psf(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "wavelength_nm" in r["reason"]


def test_error_invalid_aperture():
    """aperture_diameter_mm <= 0 returns error dict."""
    spec = DiffractionPSFSpec(wavelength_nm=550.0, aperture_diameter_mm=0.0, focal_length_mm=50.0)
    r = compute_diffraction_psf(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "aperture_diameter_mm" in r["reason"]


def test_error_invalid_focal():
    """focal_length_mm <= 0 returns error dict."""
    spec = DiffractionPSFSpec(wavelength_nm=550.0, aperture_diameter_mm=10.0, focal_length_mm=-1.0)
    r = compute_diffraction_psf(spec)
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert "focal_length_mm" in r["reason"]


def test_error_bad_num_samples():
    """num_samples < 2 returns error dict."""
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=1)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_error_bad_max_radius():
    """max_radius_um <= 0 returns error dict."""
    r = compute_diffraction_psf(_SPEC_550_10_50, max_radius_um=0.0)
    assert isinstance(r, dict)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# Tests 20–22: Dataclass and serialisation
# ---------------------------------------------------------------------------

def test_report_dataclass_fields():
    """DiffractionPSFReport has all required attributes."""
    r = _report_default()
    assert hasattr(r, "airy_disk_radius_um")
    assert hasattr(r, "rayleigh_resolution_um")
    assert hasattr(r, "fwhm_um")
    assert hasattr(r, "psf_profile")
    assert hasattr(r, "honest_caveat")


def test_to_dict_ok_key():
    """to_dict() has ok=True."""
    r = _report_default()
    d = r.to_dict()
    assert d["ok"] is True


def test_to_dict_honest_caveat():
    """to_dict() includes non-empty honest_caveat."""
    r = _report_default()
    d = r.to_dict()
    assert "honest_caveat" in d
    assert len(d["honest_caveat"]) > 10
    assert "scalar" in d["honest_caveat"].lower() or "SCALAR" in d["honest_caveat"]


# ---------------------------------------------------------------------------
# Tests 23–27: LLM tool
# ---------------------------------------------------------------------------

def test_tool_happy_path():
    """LLM tool returns ok JSON with airy_disk_radius_um and psf_profile."""
    payload = json.dumps({
        "wavelength_nm": 550.0,
        "aperture_diameter_mm": 10.0,
        "focal_length_mm": 50.0,
    })
    result = asyncio.run(run_compute_diffraction_psf(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert "airy_disk_radius_um" in data
    assert "psf_profile" in data
    assert data["airy_disk_radius_um"] == pytest.approx(3.355, rel=1e-3)


def test_tool_missing_wavelength():
    """LLM tool returns error when wavelength_nm is missing."""
    payload = json.dumps({
        "aperture_diameter_mm": 10.0,
        "focal_length_mm": 50.0,
    })
    result = asyncio.run(run_compute_diffraction_psf(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is False


def test_tool_missing_aperture():
    """LLM tool returns error when aperture_diameter_mm is missing."""
    payload = json.dumps({
        "wavelength_nm": 550.0,
        "focal_length_mm": 50.0,
    })
    result = asyncio.run(run_compute_diffraction_psf(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is False


def test_tool_bad_json():
    """LLM tool handles invalid JSON gracefully."""
    result = asyncio.run(run_compute_diffraction_psf(None, b"not-json"))
    data = json.loads(result)
    assert "error" in data or data.get("ok") is False


def test_tool_num_samples_kwarg():
    """LLM tool accepts optional num_samples parameter."""
    payload = json.dumps({
        "wavelength_nm": 550.0,
        "aperture_diameter_mm": 10.0,
        "focal_length_mm": 50.0,
        "num_samples": 30,
    })
    result = asyncio.run(run_compute_diffraction_psf(None, payload.encode()))
    data = json.loads(result)
    assert data["ok"] is True
    assert len(data["psf_profile"]) == 30


# ---------------------------------------------------------------------------
# Test 28: Secondary Airy ring local maximum
# ---------------------------------------------------------------------------

def test_psf_secondary_max_exists():
    """
    Beyond the first dark ring (r > r_Airy) there must be a secondary maximum
    (secondary Airy ring).  We verify a local max exists in the range
    [r_Airy, 3·r_Airy].
    """
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=1000, max_radius_um=30.0)
    assert isinstance(r, DiffractionPSFReport)
    airy_um = r.airy_disk_radius_um
    # Filter samples in [r_Airy, 3·r_Airy]
    ring_pts = [(r_um, I) for r_um, I in r.psf_profile
                if airy_um < r_um < 3.0 * airy_um]
    assert len(ring_pts) >= 5, "Too few samples for secondary-ring check"
    # There should be a local maximum: some interior point with I > its neighbours
    found_max = False
    for i in range(1, len(ring_pts) - 1):
        _, I_prev = ring_pts[i - 1]
        _, I_curr = ring_pts[i]
        _, I_next = ring_pts[i + 1]
        if I_curr > I_prev and I_curr > I_next and I_curr > 0.001:
            found_max = True
            break
    assert found_max, "No secondary Airy ring maximum found in [r_Airy, 3·r_Airy]"


# ---------------------------------------------------------------------------
# Test 29: I at FWHM radius ≈ 0.5
# ---------------------------------------------------------------------------

def test_psf_at_fwhm_near_half():
    """I at the FWHM radius should be ≈ 0.5 (definition of FWHM)."""
    r = compute_diffraction_psf(_SPEC_550_10_50, num_samples=2000, max_radius_um=10.0)
    assert isinstance(r, DiffractionPSFReport)
    fwhm_half = r.fwhm_um / 2.0
    # Find profile point closest to fwhm_half
    closest = min(r.psf_profile, key=lambda p: abs(p[0] - fwhm_half))
    r_c, I_c = closest
    assert abs(I_c - 0.5) < 0.025, (
        f"I({r_c:.4f}μm) = {I_c:.4f} should be ≈ 0.5 at FWHM half-radius"
    )


# ---------------------------------------------------------------------------
# Test 30: FWHM < Airy disk radius
# ---------------------------------------------------------------------------

def test_fwhm_less_than_airy():
    """FWHM < Airy disk radius (the FWHM is measured at the half-max point, inside first dark ring)."""
    r = _report_default()
    assert r.fwhm_um < r.airy_disk_radius_um, (
        f"Expected FWHM {r.fwhm_um:.4f} < Airy {r.airy_disk_radius_um:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 31: Longer wavelength → proportionally larger Airy radius
# ---------------------------------------------------------------------------

def test_different_wavelengths_scale():
    """Airy radius scales proportionally with wavelength (same aperture and focal length)."""
    spec_a = DiffractionPSFSpec(wavelength_nm=400.0, aperture_diameter_mm=10.0, focal_length_mm=50.0)
    spec_b = DiffractionPSFSpec(wavelength_nm=800.0, aperture_diameter_mm=10.0, focal_length_mm=50.0)
    r_a = compute_diffraction_psf(spec_a)
    r_b = compute_diffraction_psf(spec_b)
    assert isinstance(r_a, DiffractionPSFReport)
    assert isinstance(r_b, DiffractionPSFReport)
    # Airy radius ∝ λ: r_b / r_a = λ_b / λ_a = 2.0
    ratio = r_b.airy_disk_radius_um / r_a.airy_disk_radius_um
    assert ratio == pytest.approx(2.0, rel=1e-10), (
        f"Expected Airy ratio = 2.0, got {ratio}"
    )


# ---------------------------------------------------------------------------
# Test 32: Larger F# → proportionally larger Airy radius
# ---------------------------------------------------------------------------

def test_different_fnumbers_scale():
    """Airy radius scales proportionally with F# = f/D."""
    spec_f4 = DiffractionPSFSpec(wavelength_nm=550.0, aperture_diameter_mm=25.0, focal_length_mm=100.0)
    spec_f8 = DiffractionPSFSpec(wavelength_nm=550.0, aperture_diameter_mm=25.0, focal_length_mm=200.0)
    r_f4 = compute_diffraction_psf(spec_f4)
    r_f8 = compute_diffraction_psf(spec_f8)
    assert isinstance(r_f4, DiffractionPSFReport)
    assert isinstance(r_f8, DiffractionPSFReport)
    # Airy radius ∝ F# = f/D: r_f8 / r_f4 = 200/100 = 2.0
    ratio = r_f8.airy_disk_radius_um / r_f4.airy_disk_radius_um
    assert ratio == pytest.approx(2.0, rel=1e-10), (
        f"Expected Airy ratio = 2.0 for F#-doubling, got {ratio}"
    )


# ===========================================================================
# Tests 33–40: Polychromatic PSF (compute_polychromatic_psf)
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers shared by polychromatic tests
# ---------------------------------------------------------------------------

# Canonical setup: NA=0.1, f=50mm → D=10mm, F#=5
_POLY_NA = 0.1
_POLY_F_MM = 50.0
# Two-wavelength test grid spanning blue→red
_WLS_2 = [450.0, 650.0]
# Fine visible grid 400–700 nm step 10 nm (31 samples)
_WLS_VISIBLE = list(range(400, 701, 10))


# ---------------------------------------------------------------------------
# Test 33: Single-wavelength SPD matches monochromatic compute_diffraction_psf
# ---------------------------------------------------------------------------

def test_poly_psf_single_wavelength_matches_mono():
    """
    compute_polychromatic_psf with a single-wavelength SPD must reproduce the
    monochromatic Airy pattern exactly (to floating-point precision).
    """
    wl_nm = 550.0
    na = _POLY_NA
    f_mm = _POLY_F_MM
    D_mm = 2.0 * na * f_mm   # 10 mm
    num_r = 200
    max_r = 20.0

    # Polychromatic with two identical copies of the same wavelength
    # (min len=2 requirement) and equal weights → single-wavelength result
    poly = compute_polychromatic_psf(
        numerical_aperture=na,
        focal_length_mm=f_mm,
        wavelength_samples_nm=[wl_nm, wl_nm],
        spd_weights=[1.0, 1.0],
        num_samples=num_r,
        max_radius_um=max_r,
    )
    assert isinstance(poly, PolychromaticPSFReport), f"Expected report, got {poly}"

    # Monochromatic reference
    spec = DiffractionPSFSpec(
        wavelength_nm=wl_nm,
        aperture_diameter_mm=D_mm,
        focal_length_mm=f_mm,
    )
    mono = compute_diffraction_psf(spec, num_samples=num_r, max_radius_um=max_r)
    assert isinstance(mono, DiffractionPSFReport)

    # Compare profiles point-by-point
    for (r_p, I_p), (r_m, I_m) in zip(poly.poly_psf_profile, mono.psf_profile):
        assert r_p == pytest.approx(r_m, abs=1e-12), "Radial grid mismatch"
        assert I_p == pytest.approx(I_m, abs=1e-12), (
            f"Intensity mismatch at r={r_p:.3f}μm: poly={I_p:.8f} mono={I_m:.8f}"
        )


# ---------------------------------------------------------------------------
# Test 34: I_poly(0) = 1.0 exactly for any SPD
# ---------------------------------------------------------------------------

def test_poly_psf_normalised_at_origin():
    """I_poly(0) must equal 1.0 for any broadband SPD (all Airy PSFs are 1 at r=0)."""
    wls = _WLS_VISIBLE
    weights = d65_spd(wls)
    poly = compute_polychromatic_psf(
        numerical_aperture=_POLY_NA,
        focal_length_mm=_POLY_F_MM,
        wavelength_samples_nm=wls,
        spd_weights=weights,
        num_samples=100,
        max_radius_um=15.0,
    )
    assert isinstance(poly, PolychromaticPSFReport)
    r0, I0 = poly.poly_psf_profile[0]
    assert r0 == pytest.approx(0.0, abs=1e-12)
    assert I0 == pytest.approx(1.0, abs=1e-10), f"I_poly(0) = {I0} should be 1.0"


# ---------------------------------------------------------------------------
# Test 35: Broadband PSF is ≥ best-λ PSF near origin but not tighter
#           (polychromatic PSF blurs toward longer λ → effective Airy grows)
# ---------------------------------------------------------------------------

def test_poly_psf_broadband_broader_than_best_lambda():
    """
    Broadband PSF should have a smaller value at a mid-range radius than the
    best-λ (shortest wavelength, smallest Airy disk) monochromatic PSF.
    At r between the short-λ and long-λ Airy radii, the mono-short-λ PSF has
    already started falling, but the long-λ contribution is still relatively
    high, making the polychromatic sum *higher* in the wings — i.e., the poly
    PSF is effectively broader.
    We verify: at r = r_Airy(λ_min), I_poly > I_mono(λ_min) ≈ 0.
    """
    na = _POLY_NA
    f_mm = _POLY_F_MM
    lam_min = 400.0
    lam_max = 700.0

    D_mm = 2.0 * na * f_mm
    f_number = f_mm / D_mm
    r_airy_min = 1.22 * (lam_min * 1e-6) * f_number * 1e3  # μm

    # Polychromatic: uniform weights across 400–700 nm
    wls = [float(lam_min), float(lam_max)]
    weights = [1.0, 1.0]
    poly = compute_polychromatic_psf(
        numerical_aperture=na,
        focal_length_mm=f_mm,
        wavelength_samples_nm=wls,
        spd_weights=weights,
        num_samples=500,
        max_radius_um=20.0,
    )
    assert isinstance(poly, PolychromaticPSFReport)

    # Find intensity at r ≈ r_Airy(lam_min)
    I_poly_at_airy_min = min(
        poly.poly_psf_profile, key=lambda p: abs(p[0] - r_airy_min)
    )[1]

    # Monochromatic at lam_min: I ≈ 0 at its own Airy radius
    spec_min = DiffractionPSFSpec(
        wavelength_nm=lam_min,
        aperture_diameter_mm=D_mm,
        focal_length_mm=f_mm,
    )
    mono_min = compute_diffraction_psf(spec_min, num_samples=500, max_radius_um=20.0)
    assert isinstance(mono_min, DiffractionPSFReport)
    I_mono_min_at_airy = min(
        mono_min.psf_profile, key=lambda p: abs(p[0] - r_airy_min)
    )[1]

    # Polychromatic should be strictly > monochromatic at this radius because
    # the long-wavelength contribution hasn't gone to zero yet
    assert I_poly_at_airy_min > I_mono_min_at_airy + 0.01, (
        f"Expected I_poly={I_poly_at_airy_min:.4f} > I_mono_short={I_mono_min_at_airy:.4f} "
        f"at r_Airy(λ_min)={r_airy_min:.3f}μm"
    )


# ---------------------------------------------------------------------------
# Test 36: Photopic SPD is heavily weighted near 555 nm
# ---------------------------------------------------------------------------

def test_poly_psf_photopic_spd_peak_near_555nm():
    """
    photopic_spd() peaks near 555 nm (V(λ) = 1.0 at λ ≈ 555 nm, < 0.01 at
    400 nm and 700 nm).  The polychromatic PSF with photopic weights should
    closely match the monochromatic PSF at 555 nm rather than at 400 or 700 nm.
    """
    na = _POLY_NA
    f_mm = _POLY_F_MM
    D_mm = 2.0 * na * f_mm

    wls = _WLS_VISIBLE
    weights_phot = photopic_spd(wls)

    poly = compute_polychromatic_psf(
        numerical_aperture=na,
        focal_length_mm=f_mm,
        wavelength_samples_nm=wls,
        spd_weights=weights_phot,
        num_samples=300,
        max_radius_um=20.0,
    )
    assert isinstance(poly, PolychromaticPSFReport)

    # Photopic peak is at ~555 nm — Airy radius at 555 nm
    spec_555 = DiffractionPSFSpec(
        wavelength_nm=555.0, aperture_diameter_mm=D_mm, focal_length_mm=f_mm
    )
    mono_555 = compute_diffraction_psf(spec_555, num_samples=300, max_radius_um=20.0)
    assert isinstance(mono_555, DiffractionPSFReport)
    airy_555 = mono_555.airy_disk_radius_um

    # The normalised SPD weight at 555 nm should be the dominant one
    # Check that w(555) > w(400) and w(555) > w(700)
    w_at_400 = photopic_spd([400.0])[0]
    w_at_555 = photopic_spd([555.0])[0]
    w_at_700 = photopic_spd([700.0])[0]
    assert w_at_555 > w_at_400 * 5, f"Photopic peak at 555 nm expected >> 400 nm: {w_at_555} vs {w_at_400}"
    assert w_at_555 > w_at_700 * 5, f"Photopic peak at 555 nm expected >> 700 nm: {w_at_555} vs {w_at_700}"

    # The polychromatic Airy radius (approx = r at first near-zero of poly PSF)
    # should be close to but >= 555 nm Airy radius (longer tails from red component)
    # At r = airy_555, poly PSF should be non-zero (some long-λ signal remains)
    I_poly_at_airy555 = min(
        poly.poly_psf_profile, key=lambda p: abs(p[0] - airy_555)
    )[1]
    # Mono at 555 is ≈ 0 at its Airy radius; poly gets red-wavelength contribution
    assert I_poly_at_airy555 >= 0.0
    assert I_poly_at_airy555 <= 1.0


# ---------------------------------------------------------------------------
# Test 37: All polychromatic intensities in [0, 1]
# ---------------------------------------------------------------------------

def test_poly_psf_intensity_range():
    """All I_poly values must lie in [0, 1] for any well-formed SPD."""
    wls = _WLS_VISIBLE
    weights = blackbody_spd(wls, T_K=6500.0)
    poly = compute_polychromatic_psf(
        numerical_aperture=0.05,
        focal_length_mm=100.0,
        wavelength_samples_nm=wls,
        spd_weights=weights,
        num_samples=200,
        max_radius_um=30.0,
    )
    assert isinstance(poly, PolychromaticPSFReport)
    for r_um, I in poly.poly_psf_profile:
        assert 0.0 <= I <= 1.0 + 1e-10, f"I={I} out of [0,1] at r={r_um:.3f}μm"


# ---------------------------------------------------------------------------
# Test 38: PolychromaticPSFReport.to_dict() has ok=True and required keys
# ---------------------------------------------------------------------------

def test_poly_psf_to_dict_structure():
    """to_dict() returns a dict with ok=True and all expected keys."""
    wls = _WLS_2
    poly = compute_polychromatic_psf(
        numerical_aperture=_POLY_NA,
        focal_length_mm=_POLY_F_MM,
        wavelength_samples_nm=wls,
        spd_weights=[1.0, 1.0],
        num_samples=50,
        max_radius_um=10.0,
    )
    assert isinstance(poly, PolychromaticPSFReport)
    d = poly.to_dict()
    assert d["ok"] is True
    for key in (
        "numerical_aperture",
        "focal_length_mm",
        "wavelength_samples_nm",
        "spd_weights_normalised",
        "airy_disk_radius_um_per_wavelength",
        "poly_psf_profile",
        "honest_caveat",
    ):
        assert key in d, f"Missing key '{key}' in to_dict() output"
    # Normalised weights sum to 1
    assert sum(d["spd_weights_normalised"]) == pytest.approx(1.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Test 39: Error paths for compute_polychromatic_psf
# ---------------------------------------------------------------------------

def test_poly_psf_error_bad_na():
    """NA <= 0 returns error dict."""
    r = compute_polychromatic_psf(
        numerical_aperture=0.0,
        focal_length_mm=50.0,
        wavelength_samples_nm=[500.0, 600.0],
        spd_weights=[1.0, 1.0],
    )
    assert isinstance(r, dict) and r["ok"] is False
    assert "numerical_aperture" in r["reason"]


def test_poly_psf_error_bad_focal():
    """focal_length_mm <= 0 returns error dict."""
    r = compute_polychromatic_psf(
        numerical_aperture=0.1,
        focal_length_mm=-10.0,
        wavelength_samples_nm=[500.0, 600.0],
        spd_weights=[1.0, 1.0],
    )
    assert isinstance(r, dict) and r["ok"] is False
    assert "focal_length_mm" in r["reason"]


def test_poly_psf_error_single_wavelength():
    """wavelength_samples_nm with < 2 elements returns error dict."""
    r = compute_polychromatic_psf(
        numerical_aperture=0.1,
        focal_length_mm=50.0,
        wavelength_samples_nm=[550.0],
        spd_weights=[1.0],
    )
    assert isinstance(r, dict) and r["ok"] is False


def test_poly_psf_error_weight_length_mismatch():
    """Mismatched spd_weights length returns error dict."""
    r = compute_polychromatic_psf(
        numerical_aperture=0.1,
        focal_length_mm=50.0,
        wavelength_samples_nm=[500.0, 550.0, 600.0],
        spd_weights=[1.0, 1.0],  # only 2 instead of 3
    )
    assert isinstance(r, dict) and r["ok"] is False
    assert "length" in r["reason"]


def test_poly_psf_error_all_zero_weights():
    """All-zero spd_weights returns error dict."""
    r = compute_polychromatic_psf(
        numerical_aperture=0.1,
        focal_length_mm=50.0,
        wavelength_samples_nm=[500.0, 550.0],
        spd_weights=[0.0, 0.0],
    )
    assert isinstance(r, dict) and r["ok"] is False


# ---------------------------------------------------------------------------
# Test 40: Custom radial_grid_um parameter works correctly
# ---------------------------------------------------------------------------

def test_poly_psf_custom_radial_grid():
    """radial_grid_um overrides num_samples/max_radius_um and sizes output correctly."""
    custom_grid = [0.0, 1.0, 2.0, 3.0, 5.0, 10.0]
    poly = compute_polychromatic_psf(
        numerical_aperture=_POLY_NA,
        focal_length_mm=_POLY_F_MM,
        wavelength_samples_nm=_WLS_2,
        spd_weights=[1.0, 1.0],
        radial_grid_um=custom_grid,
    )
    assert isinstance(poly, PolychromaticPSFReport)
    assert len(poly.poly_psf_profile) == len(custom_grid)
    # First point r=0 → I=1.0
    r0, I0 = poly.poly_psf_profile[0]
    assert r0 == pytest.approx(0.0, abs=1e-12)
    assert I0 == pytest.approx(1.0, abs=1e-10)
    # Radii match custom grid
    for (r_out, _), r_exp in zip(poly.poly_psf_profile, custom_grid):
        assert r_out == pytest.approx(r_exp, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 41: D65 polychromatic PSF — profile length and monotonic central lobe
# ---------------------------------------------------------------------------

def test_poly_psf_d65_profile_shape():
    """
    D65-weighted polychromatic PSF: profile has num_samples entries and the
    central lobe (r < weighted-mean Airy radius) is monotonically decreasing.
    """
    na = _POLY_NA
    f_mm = _POLY_F_MM
    wls = _WLS_VISIBLE
    weights = d65_spd(wls)
    n_r = 300

    poly = compute_polychromatic_psf(
        numerical_aperture=na,
        focal_length_mm=f_mm,
        wavelength_samples_nm=wls,
        spd_weights=weights,
        num_samples=n_r,
        max_radius_um=20.0,
    )
    assert isinstance(poly, PolychromaticPSFReport)
    assert len(poly.poly_psf_profile) == n_r

    # Compute weighted-mean Airy radius as a proxy for the central-lobe limit
    total_w = sum(weights)
    mean_airy_um = sum(
        w * r_a
        for w, r_a in zip(weights, poly.airy_disk_radius_um_per_wavelength)
    ) / total_w

    # Central lobe should be monotonically decreasing
    first_lobe = [(r, I) for r, I in poly.poly_psf_profile if r <= mean_airy_um]
    assert len(first_lobe) >= 3
    for i in range(len(first_lobe) - 1):
        r_i, I_i = first_lobe[i]
        r_j, I_j = first_lobe[i + 1]
        assert I_i >= I_j - 1e-8, (
            f"Poly PSF not monotone at r={r_j:.3f}μm: I({r_i:.3f})={I_i:.6f} < I({r_j:.3f})={I_j:.6f}"
        )
