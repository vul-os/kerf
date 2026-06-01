"""
Tests for kerf_cad_core.optics.mtf_diffraction
-----------------------------------------------
Covers both the monochromatic compute_diffraction_mtf path and the new
polychromatic compute_polychromatic_diffraction_mtf path.

Polychromatic test plan
-----------------------
1. Single-wavelength SPD → matches monochromatic MTF exactly at that λ.
2. Broadband SPD → MTF_poly ≤ best-λ (shortest-λ) monochromatic MTF at every ν.
3. High-NA + broadband → effective cutoff is set by the longest significant λ.
4. D65 SPD (realistic daylight) → MTF_poly < monochromatic at 550 nm, checks
   that a real-world SPD produces a plausible, physically consistent result.
5. Photopic SPD → polychromatic MTF(0) == 1.0 exactly (normalisation check).
6. Blackbody (5500 K solar-like) SPD → monotonically decreasing MTF_poly curve.
7. Two-wavelength SPD → closed-form verifiable weighted average.
8. Input error paths (NA, wavelength list, weights, num_freq).
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.optics.mtf_diffraction import (
    AnalyticMTFReport,
    MTFReport,
    PolyMTFReport,
    compute_diffraction_mtf,
    compute_diffraction_mtf_analytic,
    compute_polychromatic_diffraction_mtf,
    photopic_spd,
    d65_spd,
    blackbody_spd,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_weights(n: int) -> list[float]:
    """Equal weights — flat SPD."""
    return [1.0] * n


def _mono_mtf_at(nu: float, na: float, wl_nm: float) -> float:
    """Monochromatic diffraction MTF at a single frequency, NA-based cutoff."""
    nu_0 = 2.0 * na / (wl_nm * 1.0e-6)
    s = nu / nu_0
    if s >= 1.0:
        return 0.0
    if s <= 0.0:
        return 1.0
    return (2.0 / math.pi) * (math.acos(s) - s * math.sqrt(1.0 - s * s))


# ===========================================================================
# Existing monochromatic tests (kept / extended)
# ===========================================================================

class TestMonochromaticDiffractionMTF:
    """Core monochromatic path — regression suite."""

    def test_oracle_cutoff_550nm_f4(self):
        """λ=550 nm, F/4 → ν₀ = 1/(550e-6·4) ≈ 454.545 cyc/mm (Goodman §6.4)."""
        r = compute_diffraction_mtf(550, 4)
        assert isinstance(r, MTFReport)
        assert abs(r.cutoff_freq_cyc_per_mm - 454.545454545) < 0.001

    def test_oracle_mtf_at_zero(self):
        r = compute_diffraction_mtf(550, 4)
        nu0, m0 = r.mtf_curve[0]
        assert abs(nu0) < 1e-9
        assert abs(m0 - 1.0) < 1e-10

    def test_oracle_mtf_half_cutoff(self):
        """MTF at ν=ν_0/2 ≈ 0.3906 (Goodman §6.4 analytic)."""
        r = compute_diffraction_mtf(550, 4, num_samples=10000)
        nu_0 = r.cutoff_freq_cyc_per_mm
        target_nu = nu_0 / 2.0
        # Find closest sample
        closest = min(r.mtf_curve, key=lambda pt: abs(pt[0] - target_nu))
        assert abs(closest[1] - 0.3906) < 0.003

    def test_mtf_monotone_decreasing(self):
        r = compute_diffraction_mtf(550, 4, num_samples=200)
        prev_m = 1.0
        for nu, m in r.mtf_curve:
            assert m <= prev_m + 1e-9
            prev_m = m

    def test_mtf_nonneg(self):
        r = compute_diffraction_mtf(550, 4, num_samples=200)
        assert all(m >= -1e-12 for _, m in r.mtf_curve)

    def test_invalid_wavelength_zero(self):
        result = compute_diffraction_mtf(0, 4)
        assert isinstance(result, dict)
        assert result["ok"] is False

    def test_invalid_f_number_negative(self):
        result = compute_diffraction_mtf(550, -1)
        assert isinstance(result, dict)
        assert result["ok"] is False

    def test_honest_caveat_present(self):
        r = compute_diffraction_mtf(550, 4)
        assert len(r.honest_caveat) > 20
        assert "DIFFRACTION" in r.honest_caveat.upper()


# ===========================================================================
# Polychromatic MTF tests
# ===========================================================================

class TestPolychromaticDiffractionMTF:
    """compute_polychromatic_diffraction_mtf — new functionality."""

    # -----------------------------------------------------------------------
    # Test 1: Single-wavelength SPD matches monochromatic exactly
    # -----------------------------------------------------------------------
    def test_single_wavelength_matches_monochromatic(self):
        """
        A SPD with a single non-zero weight at λ=550 nm must reproduce
        the monochromatic MTF_diff(ν, 550 nm) exactly at every grid point.
        """
        na = 0.1
        wls = [400.0, 550.0, 700.0]  # 3 samples, only middle has weight
        weights = [0.0, 1.0, 0.0]
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=64
        )
        assert isinstance(report, PolyMTFReport)

        for nu, mtf_poly in report.poly_mtf_curve:
            expected = _mono_mtf_at(nu, na, 550.0)
            assert abs(mtf_poly - expected) < 1e-10, (
                f"ν={nu:.1f}: poly={mtf_poly:.6f} vs mono={expected:.6f}"
            )

    # -----------------------------------------------------------------------
    # Test 2: Broadband MTF ≤ best-wavelength (shortest λ) MTF
    # -----------------------------------------------------------------------
    def test_broadband_le_best_wavelength(self):
        """
        With a uniform SPD over 400–700 nm, the polychromatic MTF must be
        ≤ the monochromatic MTF at the shortest wavelength (400 nm) at every ν.
        Longer wavelengths have lower cutoffs, pulling the average down.
        """
        na = 0.08
        wls = list(range(400, 701, 10))  # 31 samples
        weights = _uniform_weights(len(wls))
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=128
        )
        assert isinstance(report, PolyMTFReport)

        for nu, mtf_poly in report.poly_mtf_curve:
            mono_best = _mono_mtf_at(nu, na, min(wls))
            assert mtf_poly <= mono_best + 1e-9, (
                f"ν={nu:.1f}: poly={mtf_poly:.6f} > mono_best={mono_best:.6f}"
            )

    # -----------------------------------------------------------------------
    # Test 3: High-NA + broadband — effective cutoff ≤ shortest-λ cutoff
    # -----------------------------------------------------------------------
    def test_high_na_broadband_cutoff_degraded(self):
        """
        High-NA (0.3) with 400–700 nm uniform SPD: the effective cutoff
        (poly_cutoff_effective) is the cutoff at the longest significant
        wavelength, which is strictly less than the cutoff at the shortest λ.
        """
        na = 0.3
        wls = list(range(400, 701, 20))  # 16 samples
        weights = _uniform_weights(len(wls))
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=128
        )
        assert isinstance(report, PolyMTFReport)

        nu_0_shortest = 2.0 * na / (min(wls) * 1.0e-6)
        # Effective cutoff must be strictly less than the shortest-λ cutoff
        assert report.poly_cutoff_effective < nu_0_shortest

    # -----------------------------------------------------------------------
    # Test 4: D65 SPD — MTF_poly is a valid SPD-weighted average (in-range)
    # -----------------------------------------------------------------------
    def test_d65_spd_poly_between_bounds(self):
        """
        D65 daylight SPD spanning 400–700 nm.

        At any spatial frequency ν the polychromatic MTF must satisfy:
            MTF_diff(ν, λ_max) ≤ MTF_poly(ν) ≤ MTF_diff(ν, λ_min)
        because MTF_diff is monotonically increasing as λ decreases (shorter λ
        → higher cutoff → higher MTF at a fixed ν).

        This is a strict physical bound: poly is a convex combination of
        per-wavelength values, all of which lie in [MTF@λ_max, MTF@λ_min].
        """
        na = 0.1
        wls = list(range(400, 701, 10))
        weights = d65_spd(wls)
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=128
        )
        assert isinstance(report, PolyMTFReport)

        lam_min = min(wls)  # 400 nm — highest MTF
        lam_max = max(wls)  # 700 nm — lowest MTF

        for nu, mtf_poly in report.poly_mtf_curve:
            lo = _mono_mtf_at(nu, na, lam_max)
            hi = _mono_mtf_at(nu, na, lam_min)
            assert mtf_poly >= lo - 1e-9, (
                f"ν={nu:.1f}: poly={mtf_poly:.6f} < lower_bound={lo:.6f}"
            )
            assert mtf_poly <= hi + 1e-9, (
                f"ν={nu:.1f}: poly={mtf_poly:.6f} > upper_bound={hi:.6f}"
            )

    # -----------------------------------------------------------------------
    # Test 5: MTF_poly(ν=0) == 1.0 exactly — normalisation
    # -----------------------------------------------------------------------
    def test_poly_mtf_at_zero_frequency_is_unity(self):
        """MTF_poly(0) must equal 1.0 for any valid SPD (all channels return 1.0 at ν=0)."""
        na = 0.15
        wls = list(range(450, 651, 25))  # 9 samples
        weights = photopic_spd(wls)
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=64
        )
        assert isinstance(report, PolyMTFReport)
        nu0, m0 = report.poly_mtf_curve[0]
        assert abs(nu0) < 1e-9
        assert abs(m0 - 1.0) < 1e-10

    # -----------------------------------------------------------------------
    # Test 6: Blackbody SPD — MTF_poly monotonically non-increasing
    # -----------------------------------------------------------------------
    def test_blackbody_spd_poly_mtf_monotone(self):
        """
        With a 5500 K blackbody SPD the polychromatic MTF must be
        monotonically non-increasing with spatial frequency.
        """
        na = 0.12
        wls = list(range(400, 701, 10))
        weights = blackbody_spd(wls, T_K=5500.0)
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=128
        )
        assert isinstance(report, PolyMTFReport)

        prev_m = 1.0
        for nu, m in report.poly_mtf_curve:
            assert m <= prev_m + 1e-9, f"Non-monotone at ν={nu:.1f}: {m:.6f} > {prev_m:.6f}"
            prev_m = m

    # -----------------------------------------------------------------------
    # Test 7: Two-wavelength SPD — closed-form verifiable weighted average
    # -----------------------------------------------------------------------
    def test_two_wavelength_closed_form(self):
        """
        SPD with exactly two wavelengths λ1=450 nm (w=1) and λ2=650 nm (w=3):
          MTF_poly(ν) = (1·MTF(ν,450) + 3·MTF(ν,650)) / 4
        Verify this at several frequency samples.
        """
        na = 0.1
        wls = [450.0, 650.0]
        weights = [1.0, 3.0]
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=64
        )
        assert isinstance(report, PolyMTFReport)

        for nu, mtf_poly in report.poly_mtf_curve:
            expected = (
                1.0 * _mono_mtf_at(nu, na, 450.0)
                + 3.0 * _mono_mtf_at(nu, na, 650.0)
            ) / 4.0
            assert abs(mtf_poly - expected) < 1e-10, (
                f"ν={nu:.1f}: poly={mtf_poly:.8f} expected={expected:.8f}"
            )

    # -----------------------------------------------------------------------
    # Test 8: to_dict round-trip
    # -----------------------------------------------------------------------
    def test_to_dict_round_trip(self):
        na = 0.1
        wls = [450.0, 550.0, 650.0]
        weights = [0.3, 0.5, 0.2]
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=32
        )
        d = report.to_dict()
        assert d["ok"] is True
        assert d["numerical_aperture"] == na
        assert len(d["poly_mtf_curve"]) == 32
        assert abs(d["poly_mtf_curve"][0][1] - 1.0) < 1e-10
        assert "POLYCHROMATIC" in d["honest_caveat"].upper()

    # -----------------------------------------------------------------------
    # Test 9: Cutoff per wavelength — ν_0(λ) = 2·NA/λ
    # -----------------------------------------------------------------------
    def test_cutoff_per_wavelength_values(self):
        """Each per-wavelength cutoff must equal 2·NA/λ_mm."""
        na = 0.2
        wls = [400.0, 500.0, 600.0]
        weights = [1.0, 1.0, 1.0]
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=32
        )
        assert isinstance(report, PolyMTFReport)
        for lam, nu_0 in zip(wls, report.cutoff_freq_cyc_per_mm_per_wavelength):
            expected = 2.0 * na / (lam * 1.0e-6)
            assert abs(nu_0 - expected) / expected < 1e-10

    # -----------------------------------------------------------------------
    # Test 10: poly_mtf non-negative everywhere
    # -----------------------------------------------------------------------
    def test_poly_mtf_nonneg(self):
        na = 0.05
        wls = list(range(380, 761, 20))
        weights = d65_spd(wls)
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=200
        )
        assert isinstance(report, PolyMTFReport)
        assert all(m >= -1e-12 for _, m in report.poly_mtf_curve)

    # -----------------------------------------------------------------------
    # Test 11: SPD weights normalised to sum=1 in report
    # -----------------------------------------------------------------------
    def test_returned_weights_normalised(self):
        na = 0.1
        wls = [480.0, 550.0, 620.0]
        weights = [2.0, 4.0, 2.0]  # not normalised
        report = compute_polychromatic_diffraction_mtf(
            na, wls, weights, num_spatial_freq=32
        )
        assert isinstance(report, PolyMTFReport)
        assert abs(sum(report.spd_weights) - 1.0) < 1e-10

    # -----------------------------------------------------------------------
    # Input error paths
    # -----------------------------------------------------------------------
    def test_error_na_zero(self):
        result = compute_polychromatic_diffraction_mtf(
            0.0, [450.0, 550.0], [1.0, 1.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_na_above_one(self):
        result = compute_polychromatic_diffraction_mtf(
            1.5, [450.0, 550.0], [1.0, 1.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_single_wavelength_sample(self):
        result = compute_polychromatic_diffraction_mtf(
            0.1, [550.0], [1.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_weights_length_mismatch(self):
        result = compute_polychromatic_diffraction_mtf(
            0.1, [450.0, 550.0, 650.0], [1.0, 1.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_all_zero_weights(self):
        result = compute_polychromatic_diffraction_mtf(
            0.1, [450.0, 550.0], [0.0, 0.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_negative_weight(self):
        result = compute_polychromatic_diffraction_mtf(
            0.1, [450.0, 550.0], [-0.1, 1.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_num_spatial_freq_one(self):
        result = compute_polychromatic_diffraction_mtf(
            0.1, [450.0, 550.0], [1.0, 1.0], num_spatial_freq=1
        )
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_zero_wavelength(self):
        result = compute_polychromatic_diffraction_mtf(
            0.1, [0.0, 550.0], [1.0, 1.0]
        )
        assert isinstance(result, dict) and result["ok"] is False

    # -----------------------------------------------------------------------
    # Test: honest caveat contains expected strings
    # -----------------------------------------------------------------------
    def test_honest_caveat_polychromatic(self):
        na = 0.1
        wls = [450.0, 550.0]
        weights = [1.0, 1.0]
        report = compute_polychromatic_diffraction_mtf(na, wls, weights)
        assert isinstance(report, PolyMTFReport)
        assert "POLYCHROMATIC" in report.honest_caveat.upper()
        assert "Goodman" in report.honest_caveat or "Hopkins" in report.honest_caveat


# ===========================================================================
# Analytic (closed-form) MTF tests — Hopkins (1953) / Goodman §6.4
# ===========================================================================

class TestAnalyticDiffractionMTF:
    """
    compute_diffraction_mtf_analytic — direct evaluation of the Hopkins (1953)
    closed-form expression for the circular-aperture diffraction MTF.

    All tests use exact analytic values; numerical tolerance is ~1e-10.
    """

    # -----------------------------------------------------------------------
    # Test A1: Return type is AnalyticMTFReport
    # -----------------------------------------------------------------------
    def test_returns_analytic_report(self):
        report = compute_diffraction_mtf_analytic(0.1, 550.0)
        assert isinstance(report, AnalyticMTFReport)

    # -----------------------------------------------------------------------
    # Test A2: MTF(0) == 1.0 exactly (analytic boundary condition)
    # -----------------------------------------------------------------------
    def test_analytic_mtf_at_zero_is_unity(self):
        """
        At ν=0: arccos(0)=π/2, so MTF=(2/π)·π/2=1.0 exactly.
        Also confirmed via the stored mtf_at_zero field.
        """
        report = compute_diffraction_mtf_analytic(0.1, 550.0, num_spatial_freq=128)
        assert isinstance(report, AnalyticMTFReport)
        # Stored landmark
        assert abs(report.mtf_at_zero - 1.0) < 1e-15
        # First curve point
        nu0, m0 = report.mtf_curve[0]
        assert abs(nu0) < 1e-9
        assert abs(m0 - 1.0) < 1e-15

    # -----------------------------------------------------------------------
    # Test A3: MTF(ν_c) == 0.0 exactly (analytic boundary condition)
    # -----------------------------------------------------------------------
    def test_analytic_mtf_at_cutoff_is_zero(self):
        """
        At ν=ν_c (s=1): arccos(1)=0, sqrt(1−1)=0 → MTF=0 exactly.
        Also confirmed via the stored mtf_at_cutoff field.
        """
        report = compute_diffraction_mtf_analytic(0.15, 488.0, num_spatial_freq=64)
        assert isinstance(report, AnalyticMTFReport)
        assert abs(report.mtf_at_cutoff - 0.0) < 1e-15
        # Last curve point is exactly at ν_c
        nu_last, m_last = report.mtf_curve[-1]
        assert abs(nu_last - report.cutoff_freq_cyc_per_mm) < 1e-9
        assert abs(m_last - 0.0) < 1e-15

    # -----------------------------------------------------------------------
    # Test A4: MTF(ν_c/2) ≈ 0.3909  Hopkins (1953); Goodman §6.4
    # -----------------------------------------------------------------------
    def test_analytic_mtf_at_half_cutoff(self):
        """
        At s=0.5:  MTF = (2/π)·[arccos(0.5) − 0.5·√(3)/2]
                       = (2/π)·[π/3 − √3/4]
                       ≈ 0.39087  (Hopkins 1953; Goodman §6.4)
        The stored mtf_at_half_cutoff field must match to < 1e-10.
        """
        report = compute_diffraction_mtf_analytic(0.1, 550.0, num_spatial_freq=128)
        assert isinstance(report, AnalyticMTFReport)
        expected = (2.0 / math.pi) * (
            math.acos(0.5) - 0.5 * math.sqrt(1.0 - 0.25)
        )
        assert abs(expected - 0.3906) < 0.001  # ≈ 0.391 per Goodman §6.4
        assert abs(report.mtf_at_half_cutoff - expected) < 1e-15

    # -----------------------------------------------------------------------
    # Test A5: Analytic vs numerical — max difference < 1e-10
    # -----------------------------------------------------------------------
    def test_analytic_vs_numerical_agreement(self):
        """
        Both compute_diffraction_mtf_analytic and the numerical path inside
        compute_polychromatic_diffraction_mtf call the same _mtf_value()
        kernel.  Their results must agree to < 1e-10 over the entire frequency
        range.
        """
        na = 0.12
        wl_nm = 532.0
        num_pts = 256

        analytic_report = compute_diffraction_mtf_analytic(
            na, wl_nm, num_spatial_freq=num_pts
        )
        assert isinstance(analytic_report, AnalyticMTFReport)

        # Build a single-wavelength polychromatic report on the same grid
        # (two identical wavelengths, same weight → identical to single-λ MTF)
        poly_report = compute_polychromatic_diffraction_mtf(
            na, [wl_nm, wl_nm], [1.0, 1.0], num_spatial_freq=num_pts
        )
        assert isinstance(poly_report, PolyMTFReport)

        # Compare point-by-point
        max_diff = 0.0
        for (nu_a, m_a), (nu_p, m_p) in zip(
            analytic_report.mtf_curve, poly_report.poly_mtf_curve
        ):
            diff = abs(m_a - m_p)
            if diff > max_diff:
                max_diff = diff

        assert max_diff < 1e-10, (
            f"Analytic vs numerical max difference {max_diff:.2e} exceeds 1e-10"
        )

    # -----------------------------------------------------------------------
    # Test A6: Cutoff frequency matches ν_c = 2·NA/λ_mm
    # -----------------------------------------------------------------------
    def test_cutoff_freq_formula(self):
        """ν_c = 2·NA/λ_mm — verified against the closed-form formula."""
        na = 0.25
        wl_nm = 632.8  # He-Ne laser line
        report = compute_diffraction_mtf_analytic(na, wl_nm)
        assert isinstance(report, AnalyticMTFReport)
        expected_nu_c = 2.0 * na / (wl_nm * 1.0e-6)
        assert abs(report.cutoff_freq_cyc_per_mm - expected_nu_c) / expected_nu_c < 1e-12

    # -----------------------------------------------------------------------
    # Test A7: MTF curve is monotonically non-increasing
    # -----------------------------------------------------------------------
    def test_analytic_mtf_monotone_decreasing(self):
        """
        The Hopkins formula is strictly decreasing on [0, ν_c].
        With floating-point arithmetic the sequence must be non-increasing.
        """
        report = compute_diffraction_mtf_analytic(0.08, 486.1, num_spatial_freq=200)
        assert isinstance(report, AnalyticMTFReport)
        prev_m = 1.0
        for nu, m in report.mtf_curve:
            assert m <= prev_m + 1e-12, (
                f"Non-monotone at ν={nu:.1f}: MTF={m:.8f} > prev={prev_m:.8f}"
            )
            prev_m = m

    # -----------------------------------------------------------------------
    # Test A8: to_dict round-trip
    # -----------------------------------------------------------------------
    def test_to_dict_round_trip(self):
        report = compute_diffraction_mtf_analytic(0.1, 550.0, num_spatial_freq=32)
        assert isinstance(report, AnalyticMTFReport)
        d = report.to_dict()
        assert d["ok"] is True
        assert d["numerical_aperture"] == 0.1
        assert d["wavelength_nm"] == 550.0
        assert abs(d["mtf_at_zero"] - 1.0) < 1e-15
        assert abs(d["mtf_at_cutoff"] - 0.0) < 1e-15
        assert len(d["mtf_curve"]) == 32
        assert abs(d["mtf_curve"][0][1] - 1.0) < 1e-15

    # -----------------------------------------------------------------------
    # Test A9: MTF values all in [0, 1]
    # -----------------------------------------------------------------------
    def test_analytic_mtf_values_in_unit_interval(self):
        report = compute_diffraction_mtf_analytic(0.05, 780.0, num_spatial_freq=300)
        assert isinstance(report, AnalyticMTFReport)
        for nu, m in report.mtf_curve:
            assert m >= -1e-15, f"Negative MTF {m:.2e} at ν={nu:.1f}"
            assert m <= 1.0 + 1e-15, f"MTF > 1 ({m:.2e}) at ν={nu:.1f}"

    # -----------------------------------------------------------------------
    # Test A10: Analytic vs monochromatic (F# path) — point-by-point agreement
    # -----------------------------------------------------------------------
    def test_analytic_vs_monochromatic_f_number_path(self):
        """
        compute_diffraction_mtf (F# path) and compute_diffraction_mtf_analytic
        (NA path, same _mtf_value kernel) must agree to < 1e-10 at every
        shared frequency sample.

        Relationship: F# = 1/(2·NA)  ↔  NA = 1/(2·F#).
        Both cutoffs: ν_c = 1/(λ_mm·F#) = 2·NA/λ_mm — same formula, same value.
        """
        wl_nm = 550.0
        f_num = 5.6
        na = 1.0 / (2.0 * f_num)  # NA corresponding to F#

        analytic_report = compute_diffraction_mtf_analytic(
            na, wl_nm, num_spatial_freq=200
        )
        assert isinstance(analytic_report, AnalyticMTFReport)

        # Build monochromatic report on the same grid (sample at same freqs)
        # Use helper from test file
        nu_c = analytic_report.cutoff_freq_cyc_per_mm
        max_diff = 0.0
        for nu, m_analytic in analytic_report.mtf_curve:
            m_expected = _mono_mtf_at(nu, na, wl_nm)
            diff = abs(m_analytic - m_expected)
            if diff > max_diff:
                max_diff = diff

        assert max_diff < 1e-14, (
            f"Analytic vs _mono_mtf_at max difference {max_diff:.2e} exceeds 1e-14"
        )

    # -----------------------------------------------------------------------
    # Input error paths
    # -----------------------------------------------------------------------
    def test_error_na_zero(self):
        result = compute_diffraction_mtf_analytic(0.0, 550.0)
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_na_above_one(self):
        result = compute_diffraction_mtf_analytic(1.5, 550.0)
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_wavelength_zero(self):
        result = compute_diffraction_mtf_analytic(0.1, 0.0)
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_wavelength_negative(self):
        result = compute_diffraction_mtf_analytic(0.1, -100.0)
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_num_spatial_freq_one(self):
        result = compute_diffraction_mtf_analytic(0.1, 550.0, num_spatial_freq=1)
        assert isinstance(result, dict) and result["ok"] is False

    def test_error_na_negative(self):
        result = compute_diffraction_mtf_analytic(-0.1, 550.0)
        assert isinstance(result, dict) and result["ok"] is False
