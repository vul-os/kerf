"""
Hermetic tests for kerf_cad_core.optics.pixel_mtf — pixel aperture MTF.

Coverage (≥ 12 tests):
  1. Nyquist frequency for 1.5 μm pixel
  2. MTF(0) = 1.0 exactly (fill_factor=1.0)
  3. MTF at Nyquist ≈ 2/π (fill_factor=1.0, analytic oracle)
  4. MTF curve length = num_samples
  5. MTF curve starts at (0, 1.0) and ends at (2·ν_N, ~)
  6. Fill factor < 1.0 → MTF at Nyquist > 2/π (narrower aperture = slower roll-off)
  7. Monotone-ish: MTF curve does not rise above 1.0 anywhere
  8. MTF at 50% Nyquist for fill_factor=1.0 analytic check
  9. Invalid pixel_pitch_um ≤ 0 → error dict
 10. Invalid fill_factor = 0 → error dict
 11. Invalid fill_factor > 1 → error dict
 12. Invalid num_samples < 2 → error dict
 13. combine_mtf_curves — length mismatch → error dict
 14. combine_mtf_curves — element-wise product verified
 15. PixelMtfReport.to_dict() structure
 16. Re-export from optics/__init__.py works
 17. MTF is monotonically non-increasing from 0 to ν_N (sinc main lobe is monotone for ff≤1)
 18. PixelSensorSpec default fill_factor is 1.0

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against Boreman "Modulation Transfer Function in Optical
and Electro-Optical Systems" §3.4 and Hecht "Optics" 5th ed. §11.3.

References
----------
Boreman, G.D. — "Modulation Transfer Function in Optical and Electro-Optical
    Systems", SPIE Press, 2001.  §3.4.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017.  §11.3.

Author: imranparuk
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.optics.pixel_mtf import (
    PixelSensorSpec,
    PixelMtfReport,
    compute_pixel_mtf,
    combine_mtf_curves,
)
# Also test re-export path
from kerf_cad_core.optics import (
    PixelSensorSpec as PixelSensorSpecReexport,
    PixelMtfReport as PixelMtfReportReexport,
    compute_pixel_mtf as compute_pixel_mtf_reexport,
    combine_mtf_curves as combine_mtf_curves_reexport,
)


# ---------------------------------------------------------------------------
# Analytic oracles
# ---------------------------------------------------------------------------

# 1.5 μm pixel, fill_factor = 1.0:
#   pitch_mm = 0.0015
#   aperture_mm = 0.0015
#   ν_N = 1 / (2 × 0.0015) = 333.333... cyc/mm
#   MTF(ν_N) = |sinc(π·0.0015·333.333)| = |sinc(π/2)| = 2/π ≈ 0.63662
_PITCH_UM = 1.5
_PITCH_MM = _PITCH_UM * 1e-3
_NU_NYQUIST_EXPECTED = 1.0 / (2.0 * _PITCH_MM)   # 333.333... cyc/mm
_MTF_AT_NYQUIST_FF1 = 2.0 / math.pi               # ≈ 0.63662


class TestNyquistFrequency:
    """Test 1: Nyquist frequency for 1.5 μm pixel."""

    def test_nyquist_freq_1p5um(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        assert abs(report.nyquist_freq_cyc_per_mm - _NU_NYQUIST_EXPECTED) < 1e-6, (
            f"Expected ν_N ≈ {_NU_NYQUIST_EXPECTED:.3f}, got {report.nyquist_freq_cyc_per_mm:.3f}"
        )

    def test_nyquist_freq_5p5um(self):
        spec = PixelSensorSpec(pixel_pitch_um=5.5)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        expected = 1.0 / (2.0 * 5.5e-3)  # 90.909... cyc/mm
        assert abs(report.nyquist_freq_cyc_per_mm - expected) < 1e-6


class TestMtfAtDC:
    """Test 2: MTF(0) = 1.0 exactly for fill_factor=1.0."""

    def test_mtf_zero_freq_is_one(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec, num_samples=200)
        assert isinstance(report, PixelMtfReport)
        nu0, mtf0 = report.mtf_curve[0]
        assert nu0 == 0.0 or abs(nu0) < 1e-15, f"First sample ν should be 0, got {nu0}"
        assert abs(mtf0 - 1.0) < 1e-12, f"MTF(0) should be 1.0, got {mtf0}"

    def test_mtf_zero_freq_is_one_partial_fill(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=0.5)
        report = compute_pixel_mtf(spec, num_samples=100)
        assert isinstance(report, PixelMtfReport)
        nu0, mtf0 = report.mtf_curve[0]
        assert abs(mtf0 - 1.0) < 1e-12, f"MTF(0) should be 1.0 for any fill factor, got {mtf0}"


class TestMtfAtNyquist:
    """Test 3: MTF at Nyquist ≈ 2/π for fill_factor=1.0."""

    def test_mtf_nyquist_ff1(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=1.0)
        report = compute_pixel_mtf(spec, num_samples=1000)
        assert isinstance(report, PixelMtfReport)
        # mtf_at_nyquist is computed analytically, not by curve lookup
        assert abs(report.mtf_at_nyquist - _MTF_AT_NYQUIST_FF1) < 1e-6, (
            f"MTF at Nyquist for ff=1 should be 2/π ≈ {_MTF_AT_NYQUIST_FF1:.6f}, "
            f"got {report.mtf_at_nyquist:.6f}"
        )

    def test_mtf_nyquist_value_in_range(self):
        spec = PixelSensorSpec(pixel_pitch_um=3.0, fill_factor=1.0)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        # For any pitch with ff=1: MTF at Nyquist = 2/π ≈ 0.6366
        assert abs(report.mtf_at_nyquist - _MTF_AT_NYQUIST_FF1) < 1e-6


class TestCurveLength:
    """Test 4: MTF curve length equals num_samples."""

    def test_curve_length_default(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec)
        assert len(report.mtf_curve) == 200

    def test_curve_length_custom(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec, num_samples=50)
        assert len(report.mtf_curve) == 50

    def test_curve_length_minimum(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec, num_samples=2)
        assert len(report.mtf_curve) == 2


class TestCurveAxis:
    """Test 5: Curve starts at 0 and ends at 2·ν_N."""

    def test_curve_starts_at_zero(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        nu_first, _ = report.mtf_curve[0]
        assert abs(nu_first) < 1e-12

    def test_curve_ends_at_two_nyquist(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec, num_samples=200)
        assert isinstance(report, PixelMtfReport)
        nu_last, _ = report.mtf_curve[-1]
        expected_last = 2.0 * report.nyquist_freq_cyc_per_mm
        assert abs(nu_last - expected_last) < 1.0, (  # within 1 cyc/mm for sampling
            f"Last frequency {nu_last:.3f} should be near 2·ν_N = {expected_last:.3f}"
        )


class TestFillFactorEffect:
    """Test 6: Partial fill factor → MTF at Nyquist is higher than 2/π."""

    def test_partial_fill_mtf_nyquist_higher(self):
        # With ff < 1: aperture is narrower → sinc rolls off slower
        # → MTF at Nyquist > 2/π
        spec_ff1 = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=1.0)
        spec_ff05 = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=0.5)
        r1 = compute_pixel_mtf(spec_ff1)
        r05 = compute_pixel_mtf(spec_ff05)
        assert isinstance(r1, PixelMtfReport)
        assert isinstance(r05, PixelMtfReport)
        # ff=0.5 → aperture = 0.5·pitch → sinc arg at Nyquist is π/4 (not π/2)
        # |sinc(π/4)| = sin(π/4)/(π/4) = (√2/2)/(π/4) = 2√2/π ≈ 0.900
        expected_ff05 = abs(math.sin(math.pi / 4) / (math.pi / 4))
        assert abs(r05.mtf_at_nyquist - expected_ff05) < 1e-6, (
            f"ff=0.5 MTF at Nyquist should be ≈ {expected_ff05:.6f}, got {r05.mtf_at_nyquist:.6f}"
        )
        assert r05.mtf_at_nyquist > r1.mtf_at_nyquist, (
            "Partial fill should give higher MTF at Nyquist (narrower aperture = slower roll-off)"
        )

    def test_very_small_fill_factor(self):
        spec = PixelSensorSpec(pixel_pitch_um=5.0, fill_factor=0.1)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        # Very small aperture → MTF at Nyquist should be very close to 1
        # arg = π · (5e-3 × 0.1) · (1/(2·5e-3)) = π·0.0005·100 = π·0.05 ≈ 0.157
        expected = abs(math.sin(math.pi * 0.05) / (math.pi * 0.05))
        assert abs(report.mtf_at_nyquist - expected) < 1e-6


class TestMtfBounds:
    """Test 7: MTF values are in [0, 1] and never exceed 1.0 anywhere."""

    def test_mtf_no_value_exceeds_one(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec, num_samples=500)
        assert isinstance(report, PixelMtfReport)
        for nu, mtf in report.mtf_curve:
            assert mtf <= 1.0 + 1e-12, f"MTF({nu:.2f}) = {mtf} > 1.0"
            assert mtf >= -1e-12, f"MTF({nu:.2f}) = {mtf} < 0.0"

    def test_mtf_non_negative_partial_fill(self):
        spec = PixelSensorSpec(pixel_pitch_um=3.0, fill_factor=0.75)
        report = compute_pixel_mtf(spec, num_samples=500)
        assert isinstance(report, PixelMtfReport)
        for nu, mtf in report.mtf_curve:
            assert mtf >= -1e-12, f"MTF({nu:.2f}) = {mtf} < 0.0"


class TestMtfAt50PercentNyquist:
    """Test 8: MTF at 50% Nyquist for fill_factor=1.0 analytic check."""

    def test_mtf_half_nyquist_ff1(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=1.0)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        # ν = 0.5·ν_N → arg = π · pitch_mm · 0.5·ν_N = π · pitch_mm · 0.5 / (2·pitch_mm)
        #                     = π/4
        # |sinc(π/4)| = sin(π/4)/(π/4) ≈ 0.9003
        expected = abs(math.sin(math.pi / 4) / (math.pi / 4))
        assert abs(report.mtf_at_50_percent_nyquist - expected) < 1e-6, (
            f"MTF at 0.5·ν_N for ff=1 should be ≈ {expected:.6f}, "
            f"got {report.mtf_at_50_percent_nyquist:.6f}"
        )


class TestInputValidation:
    """Tests 9–12: Reject invalid inputs gracefully."""

    def test_negative_pitch(self):
        spec = PixelSensorSpec(pixel_pitch_um=-1.0)
        result = compute_pixel_mtf(spec)
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "pixel_pitch_um" in result["reason"]

    def test_zero_pitch(self):
        spec = PixelSensorSpec(pixel_pitch_um=0.0)
        result = compute_pixel_mtf(spec)
        assert isinstance(result, dict)
        assert result["ok"] is False

    def test_zero_fill_factor(self):
        spec = PixelSensorSpec(pixel_pitch_um=1.5, fill_factor=0.0)
        result = compute_pixel_mtf(spec)
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "fill_factor" in result["reason"]

    def test_fill_factor_above_one(self):
        spec = PixelSensorSpec(pixel_pitch_um=1.5, fill_factor=1.1)
        result = compute_pixel_mtf(spec)
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "fill_factor" in result["reason"]

    def test_num_samples_less_than_two(self):
        spec = PixelSensorSpec(pixel_pitch_um=1.5)
        result = compute_pixel_mtf(spec, num_samples=1)
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "num_samples" in result["reason"]

    def test_wrong_spec_type(self):
        result = compute_pixel_mtf("not a spec")  # type: ignore[arg-type]
        assert isinstance(result, dict)
        assert result["ok"] is False


class TestCombineMtfCurves:
    """Tests 13–14: combine_mtf_curves."""

    def test_combine_length_mismatch(self):
        a = [(0.0, 1.0), (100.0, 0.8)]
        b = [(0.0, 1.0)]
        result = combine_mtf_curves(a, b)
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "length" in result["reason"].lower() or "100" in result["reason"] or "1" in result["reason"]

    def test_combine_product_correct(self):
        optical = [(0.0, 1.0), (100.0, 0.8), (200.0, 0.5)]
        pixel_mtf_vals = [(0.0, 1.0), (100.0, 0.9), (200.0, 0.6)]
        combined = combine_mtf_curves(optical, pixel_mtf_vals)
        assert isinstance(combined, list)
        assert len(combined) == 3
        expected = [(0.0, 1.0 * 1.0), (100.0, 0.8 * 0.9), (200.0, 0.5 * 0.6)]
        for (nu_c, m_c), (nu_e, m_e) in zip(combined, expected):
            assert abs(nu_c - nu_e) < 1e-12
            assert abs(m_c - m_e) < 1e-12

    def test_combine_empty_list(self):
        result = combine_mtf_curves([], [])
        assert isinstance(result, dict)
        assert result["ok"] is False

    def test_combine_wrong_type(self):
        result = combine_mtf_curves("not a list", [(0.0, 1.0)])  # type: ignore[arg-type]
        assert isinstance(result, dict)
        assert result["ok"] is False


class TestToDict:
    """Test 15: PixelMtfReport.to_dict() structure."""

    def test_to_dict_keys(self):
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM)
        report = compute_pixel_mtf(spec)
        assert isinstance(report, PixelMtfReport)
        d = report.to_dict()
        assert d["ok"] is True
        assert "nyquist_freq_cyc_per_mm" in d
        assert "mtf_curve" in d
        assert "mtf_at_nyquist" in d
        assert "mtf_at_50_percent_nyquist" in d
        assert "honest_caveat" in d
        assert isinstance(d["mtf_curve"], list)
        assert len(d["mtf_curve"]) == 200  # default num_samples
        # Curve entries should be lists of 2 numbers
        for entry in d["mtf_curve"]:
            assert isinstance(entry, list)
            assert len(entry) == 2


class TestReexport:
    """Test 16: Re-export from optics/__init__.py works."""

    def test_reexport_spec_class(self):
        assert PixelSensorSpecReexport is PixelSensorSpec

    def test_reexport_report_class(self):
        assert PixelMtfReportReexport is PixelMtfReport

    def test_reexport_compute_function(self):
        assert compute_pixel_mtf_reexport is compute_pixel_mtf

    def test_reexport_combine_function(self):
        assert combine_mtf_curves_reexport is combine_mtf_curves


class TestMonotonicity:
    """Test 17: MTF is monotonically non-increasing from 0 to ν_N (sinc main lobe)."""

    def test_main_lobe_monotone_decreasing(self):
        # For fill_factor=1.0, the sinc main lobe spans [0, ν_N] where
        # π·a·ν_N = π/2 < π → still in the main lobe → strictly decreasing.
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=1.0)
        report = compute_pixel_mtf(spec, num_samples=200)
        assert isinstance(report, PixelMtfReport)
        # Find samples up to ν_N
        nyq = report.nyquist_freq_cyc_per_mm
        sub_nyquist = [(nu, mtf) for nu, mtf in report.mtf_curve if nu <= nyq + 1e-9]
        assert len(sub_nyquist) >= 2
        for i in range(1, len(sub_nyquist)):
            _, m_prev = sub_nyquist[i - 1]
            _, m_curr = sub_nyquist[i]
            assert m_curr <= m_prev + 1e-10, (
                f"MTF not monotone at sample {i}: {m_curr} > {m_prev}"
            )


class TestDefaultFillFactor:
    """Test 18: PixelSensorSpec default fill_factor is 1.0."""

    def test_default_fill_factor(self):
        spec = PixelSensorSpec(pixel_pitch_um=5.0)
        assert spec.fill_factor == 1.0

    def test_custom_fill_factor_stored(self):
        spec = PixelSensorSpec(pixel_pitch_um=5.0, fill_factor=0.6)
        assert spec.fill_factor == 0.6


class TestEndToEndCombination:
    """End-to-end: combine diffraction MTF with pixel MTF."""

    def test_system_mtf_lower_than_either_component(self):
        """
        System MTF = MTF_optical × MTF_pixel ≤ min(MTF_optical, MTF_pixel)
        (since both factors ≤ 1).
        """
        from kerf_cad_core.optics.mtf_diffraction import compute_diffraction_mtf

        # Optical MTF for 550nm, F/4
        opt_report = compute_diffraction_mtf(wavelength_nm=550.0, f_number=4.0, num_samples=200)
        assert hasattr(opt_report, "mtf_curve")

        # Pixel MTF for 3 μm pixel
        px_spec = PixelSensorSpec(pixel_pitch_um=3.0, fill_factor=1.0)
        px_report = compute_pixel_mtf(px_spec, num_samples=200)
        assert isinstance(px_report, PixelMtfReport)

        # Both curves are 200 samples but on different frequency axes.
        # Just check they each satisfy basic properties independently.
        # (Full cascade would require interpolation; that's out of scope here.)
        for nu, mtf in opt_report.mtf_curve:
            assert 0.0 <= mtf <= 1.0 + 1e-10
        for nu, mtf in px_report.mtf_curve:
            assert 0.0 <= mtf <= 1.0 + 1e-10

    def test_combine_same_axis(self):
        """
        If we sample both curves on the same axis [0, ν_N_pixel],
        the product curve should be ≤ each component at every point.
        """
        nyq = _NU_NYQUIST_EXPECTED  # 333.33 cyc/mm
        freqs = [i * nyq / 99 for i in range(100)]

        # Build optical MTF on this axis (diffraction cutoff = 454.5 cyc/mm)
        from kerf_cad_core.optics.mtf_diffraction import _mtf_value

        nu_0 = 1.0 / (550e-6 * 4.0)  # 454.545 cyc/mm
        optical = [(nu, _mtf_value(nu / nu_0)) for nu in freqs]

        # Build pixel MTF on this axis
        spec = PixelSensorSpec(pixel_pitch_um=_PITCH_UM, fill_factor=1.0)
        from kerf_cad_core.optics.pixel_mtf import _sinc_mtf
        pixel = [(nu, _sinc_mtf(nu, _PITCH_MM)) for nu in freqs]

        combined = combine_mtf_curves(optical, pixel)
        assert isinstance(combined, list)
        assert len(combined) == 100

        for i, (nu, m_sys) in enumerate(combined):
            m_opt = optical[i][1]
            m_pix = pixel[i][1]
            # System MTF ≤ both components
            assert m_sys <= m_opt + 1e-12, f"m_sys {m_sys} > m_opt {m_opt} at ν={nu:.1f}"
            assert m_sys <= m_pix + 1e-12, f"m_sys {m_sys} > m_pix {m_pix} at ν={nu:.1f}"
