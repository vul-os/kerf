"""
Tests for kerf_optics.tolerancing and kerf_optics.mtf.

Analytic oracles:
  1. Sensitivity: perturbing EFL by Δ gives merit change ≈ Δ/f² (thin-lens approximation).
  2. Monte Carlo: 1000 trials → mean merit near nominal for small tolerances.
  3. MTF cut-off: ν_c = 1/(λ·f/#) — exact formula.
  4. MTF at DC (0 lp/mm): always 1.0.
  5. MTF at cut-off: approaches 0.
  6. Gaussian MTF spot: MTF(0) = 1, decreasing exponential.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_optics.tolerancing import (
    ToleranceParam,
    SensitivityResult,
    MonteCarloResult,
    sensitivity_analysis,
    monte_carlo_tolerancing,
    merit_efl,
    merit_rms_spot,
    merit_bfd,
)
from kerf_optics.mtf import (
    diffraction_limited_mtf,
    diffraction_cutoff_lpmm,
    geometric_mtf_gaussian,
    mtf_from_lens_system,
    MTFResult,
)
from kerf_optics.lens_system import LensSystem, ThinLens, FreeSpace


# ===========================================================================
# Helper: simple single-thin-lens system
# ===========================================================================

def _single_lens_system(f: float = 0.1, do: float = 0.2) -> LensSystem:
    """FreeSpace(do) → ThinLens(f)"""
    return LensSystem([FreeSpace(do), ThinLens(f)])


# ===========================================================================
# ToleranceParam validation
# ===========================================================================

class TestToleranceParam:
    def test_basic_construction(self):
        p = ToleranceParam(element_index=1, param_name="f", nominal=0.1, delta=0.002)
        assert p.element_index == 1
        assert p.param_name == "f"
        assert p.nominal == pytest.approx(0.1)
        assert p.delta == pytest.approx(0.002)

    def test_negative_delta_raises(self):
        with pytest.raises(ValueError, match="delta must be >= 0"):
            ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=-0.001)

    def test_zero_delta_ok(self):
        p = ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.0)
        assert p.delta == 0.0

    def test_no_nominal(self):
        """nominal=None is allowed (resolved at analysis time)."""
        p = ToleranceParam(element_index=0, param_name="f", delta=0.005)
        assert p.nominal is None


# ===========================================================================
# merit_efl helper
# ===========================================================================

class TestMeritFunctions:
    def test_merit_efl_at_nominal(self):
        """merit_efl at the exact target should be 0."""
        system = LensSystem([ThinLens(0.1)])
        fn = merit_efl(0.1)
        assert fn(system) == pytest.approx(0.0, abs=1e-12)

    def test_merit_efl_off_target(self):
        """merit_efl with EFL=0.1, target=0.2 → 0.1."""
        system = LensSystem([ThinLens(0.1)])
        fn = merit_efl(0.2)
        assert fn(system) == pytest.approx(0.1, rel=1e-9)

    def test_merit_bfd_at_nominal(self):
        """BFD of thin lens = f."""
        system = LensSystem([ThinLens(0.1)])
        fn = merit_bfd(0.1)
        assert fn(system) == pytest.approx(0.0, abs=1e-12)

    def test_merit_rms_spot_finite(self):
        """RMS spot should be a finite non-negative float."""
        f, do = 0.1, 0.2
        di = f * do / (do - f)
        system = LensSystem([FreeSpace(do), ThinLens(f), FreeSpace(di)])
        rays = [(0.001, 0.0), (-0.001, 0.0), (0.0, 0.001)]
        fn = merit_rms_spot(rays)
        spot = fn(system)
        assert math.isfinite(spot)
        assert spot >= 0.0

    def test_merit_rms_spot_changes_with_propagation(self):
        """RMS spot changes depending on how far past the lens we propagate."""
        f = 0.1
        # Use on-axis ray with non-zero height — should focus to zero at BFD
        rays = [(0.001, 0.0)]  # single marginal ray
        # At BFD (= f for collimated object), height → 0
        system_at_bfd = LensSystem([ThinLens(f), FreeSpace(f)])
        system_underprop = LensSystem([ThinLens(f), FreeSpace(f * 0.5)])
        fn = merit_rms_spot(rays)
        spot_bfd = fn(system_at_bfd)
        spot_under = fn(system_underprop)
        # At BFD, height is 0 (spot = 0); before focus it's non-zero
        assert spot_bfd < spot_under


# ===========================================================================
# Sensitivity analysis
# ===========================================================================

class TestSensitivityAnalysis:
    def test_returns_sensitivity_result(self):
        system = _single_lens_system(f=0.1, do=0.2)
        params = [ToleranceParam(element_index=1, param_name="f", nominal=0.1, delta=0.005)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        assert isinstance(result, SensitivityResult)

    def test_merit_nominal_zero_at_target_efl(self):
        """If we target the nominal EFL, merit_nominal = 0."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        assert result.merit_nominal == pytest.approx(0.0, abs=1e-12)

    def test_delta_plus_sign(self):
        """
        For merit_efl(target=0.1) and f=0.1, perturbing f by +Δ gives EFL=0.105.
        merit(+Δ) = |0.105 − 0.1| = 0.005.
        So delta_plus = 0.005 − 0.0 = 0.005.
        """
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        assert result.delta_plus[0] == pytest.approx(0.005, rel=1e-9)

    def test_delta_minus_sign(self):
        """
        merit(−Δ) = |0.095 − 0.1| = 0.005.  delta_minus = 0.005.
        """
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        assert result.delta_minus[0] == pytest.approx(0.005, rel=1e-9)

    def test_rss_budget_single_param(self):
        """RSS budget for a single parameter = max(|δ+|, |δ-|)."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        expected_rss = max(abs(result.delta_plus[0]), abs(result.delta_minus[0]))
        assert result.rss_budget == pytest.approx(expected_rss, rel=1e-9)

    def test_two_params_rss(self):
        """RSS for two parameters = √(max_abs_1² + max_abs_2²)."""
        system = LensSystem([FreeSpace(0.2), ThinLens(0.1)])
        params = [
            ToleranceParam(element_index=0, param_name="d", nominal=0.2, delta=0.002),
            ToleranceParam(element_index=1, param_name="f", nominal=0.1, delta=0.005),
        ]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        m1 = max(abs(result.delta_plus[0]), abs(result.delta_minus[0]))
        m2 = max(abs(result.delta_plus[1]), abs(result.delta_minus[1]))
        expected_rss = math.sqrt(m1 ** 2 + m2 ** 2)
        assert result.rss_budget == pytest.approx(expected_rss, rel=1e-9)

    def test_worst_param_index(self):
        """worst_param_index returns the index with the largest sensitivity."""
        system = LensSystem([FreeSpace(0.2), ThinLens(0.1)])
        params = [
            # Small perturbation to d: should have small merit change
            ToleranceParam(element_index=0, param_name="d", nominal=0.2, delta=0.0001),
            # Large perturbation to f: larger merit change
            ToleranceParam(element_index=1, param_name="f", nominal=0.1, delta=0.02),
        ]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        assert result.worst_param_index == 1

    def test_sensitivity_table_sorted(self):
        """sensitivity_table() returns rows sorted by max_abs_sensitivity descending."""
        system = LensSystem([FreeSpace(0.2), ThinLens(0.1)])
        params = [
            ToleranceParam(element_index=0, param_name="d", nominal=0.2, delta=0.001),
            ToleranceParam(element_index=1, param_name="f", nominal=0.1, delta=0.01),
        ]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        table = result.sensitivity_table()
        senses = [row["max_abs_sensitivity"] for row in table]
        assert senses == sorted(senses, reverse=True)

    def test_nominal_auto_resolved(self):
        """When nominal=None, it is read from the element at analysis time."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", delta=0.005)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        # Nominal should have been resolved to 0.1
        assert params[0].nominal == pytest.approx(0.1, rel=1e-9)

    def test_zero_delta_gives_zero_change(self):
        """Zero tolerance → zero merit change."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.0)]
        result = sensitivity_analysis(system, params, merit_efl(0.1))
        assert result.delta_plus[0] == pytest.approx(0.0, abs=1e-14)
        assert result.delta_minus[0] == pytest.approx(0.0, abs=1e-14)


# ===========================================================================
# Monte Carlo tolerancing
# ===========================================================================

class TestMonteCarloTolerancing:
    def test_returns_monte_carlo_result(self):
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100)
        assert isinstance(result, MonteCarloResult)

    def test_n_trials_count(self):
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100)
        assert result.n_trials == 100
        assert len(result.merit_values) == 100

    def test_merit_values_non_negative(self):
        """merit_efl returns |EFL - target| ≥ 0."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100)
        assert all(v >= 0 for v in result.merit_values)

    def test_zero_tolerance_all_at_nominal(self):
        """Zero tolerances → all trials give nominal merit."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.0)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=50)
        assert all(abs(v - result.merit_nominal) < 1e-12 for v in result.merit_values)

    def test_reproducible_with_seed(self):
        """Same seed → same results."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        r1 = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100, seed=42)
        r2 = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100, seed=42)
        assert r1.merit_values == r2.merit_values

    def test_different_seeds_differ(self):
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        r1 = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100, seed=1)
        r2 = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=100, seed=2)
        assert r1.merit_values != r2.merit_values

    def test_statistics_consistent(self):
        """mean, std, p05, p95 are consistent with merit_values."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=200, seed=42)
        arr = np.array(result.merit_values)
        assert result.mean == pytest.approx(float(np.mean(arr)), rel=1e-9)
        assert result.best == pytest.approx(float(np.min(arr)), rel=1e-9)
        assert result.worst == pytest.approx(float(np.max(arr)), rel=1e-9)

    def test_p05_le_mean_le_p95(self):
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=200, seed=7)
        assert result.p05 <= result.mean + 1e-10
        assert result.mean <= result.p95 + 1e-10

    def test_yield_within_delta(self):
        """With very generous merit_tolerance, yield should be near 100%."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.001)]
        result = monte_carlo_tolerancing(
            system, params, merit_efl(0.1), n_trials=200,
            merit_tolerance=1.0,  # generous
        )
        assert result.yield_within_delta > 0.95

    def test_yield_tight_tolerance(self):
        """With very tight merit_tolerance, yield should be lower."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.01)]
        result = monte_carlo_tolerancing(
            system, params, merit_efl(0.1), n_trials=500,
            merit_tolerance=0.0001,  # very tight
        )
        # With delta=0.01 on f=0.1 (10%), most trials will exceed 0.0001 m merit change
        assert result.yield_within_delta < 1.0

    def test_normal_distribution(self):
        """distribution='normal' runs without error."""
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(
            system, params, merit_efl(0.1), n_trials=100, distribution="normal"
        )
        assert len(result.merit_values) == 100

    def test_invalid_distribution_raises(self):
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        with pytest.raises(ValueError, match="distribution must be"):
            monte_carlo_tolerancing(system, params, merit_efl(0.1), distribution="gaussian_weird")

    def test_summary_has_all_keys(self):
        system = LensSystem([ThinLens(0.1)])
        params = [ToleranceParam(element_index=0, param_name="f", nominal=0.1, delta=0.005)]
        result = monte_carlo_tolerancing(system, params, merit_efl(0.1), n_trials=50)
        s = result.summary()
        for key in ("n_trials", "merit_nominal", "mean", "std", "p05", "p95",
                    "worst", "best", "yield_within_delta"):
            assert key in s


# ===========================================================================
# Diffraction-limited MTF
# ===========================================================================

class TestDiffractionLimitedMTF:
    def test_dc_is_one(self):
        """MTF at 0 spatial frequency (DC) should be 1."""
        mtf = diffraction_limited_mtf(f_number=4.0, lambda_nm=550.0, spatial_freq_lpmm=0.0)
        assert mtf == pytest.approx(1.0, abs=1e-10)

    def test_above_cutoff_is_zero(self):
        """MTF above diffraction cut-off = 0."""
        # Cut-off for f/4, λ=550 nm:
        # ν_c = 1/(550e-6 mm × 4) = 1/(0.0022) = 454.5 lp/mm
        nu_c = diffraction_cutoff_lpmm(4.0, 550.0)
        mtf = diffraction_limited_mtf(4.0, 550.0, nu_c * 1.01)
        assert mtf == 0.0

    def test_at_cutoff_approaches_zero(self):
        """MTF at exactly cut-off = 0."""
        nu_c = diffraction_cutoff_lpmm(4.0, 550.0)
        mtf = diffraction_limited_mtf(4.0, 550.0, nu_c)
        assert mtf == pytest.approx(0.0, abs=1e-10)

    def test_monotone_decreasing(self):
        """MTF decreases monotonically with spatial frequency."""
        nu_c = diffraction_cutoff_lpmm(4.0, 550.0)
        freqs = np.linspace(0.0, nu_c * 0.99, 20)
        mtfs = [diffraction_limited_mtf(4.0, 550.0, nu) for nu in freqs]
        for i in range(1, len(mtfs)):
            assert mtfs[i] <= mtfs[i - 1] + 1e-10

    def test_cutoff_formula(self):
        """ν_cutoff = 1/(λ·f/#) in lp/mm.

        f/4, λ=550 nm → 550e-6 mm × 4 = 2.2e-3 mm → ν_c = 454.5 lp/mm.
        """
        nu_c = diffraction_cutoff_lpmm(4.0, 550.0)
        lam_mm = 550.0e-6
        expected = 1.0 / (lam_mm * 4.0)
        assert nu_c == pytest.approx(expected, rel=1e-9)

    def test_larger_f_number_lower_cutoff(self):
        """Higher f/# → lower diffraction cut-off (larger blur)."""
        nu_c_f4 = diffraction_cutoff_lpmm(4.0, 550.0)
        nu_c_f8 = diffraction_cutoff_lpmm(8.0, 550.0)
        assert nu_c_f8 < nu_c_f4

    def test_shorter_wavelength_higher_cutoff(self):
        """Shorter λ → higher cut-off."""
        nu_c_550 = diffraction_cutoff_lpmm(4.0, 550.0)
        nu_c_450 = diffraction_cutoff_lpmm(4.0, 450.0)
        assert nu_c_450 > nu_c_550

    def test_mid_frequency_value(self):
        """At s=0.5, MTF_DL = (2/π)[arccos(0.5) - 0.5·√(1-0.25)]
                              = (2/π)[π/3 - 0.5·√(0.75)]."""
        nu_c = diffraction_cutoff_lpmm(4.0, 550.0)
        nu_half = nu_c * 0.5
        mtf = diffraction_limited_mtf(4.0, 550.0, nu_half)
        s = 0.5
        expected = (2.0 / math.pi) * (math.acos(s) - s * math.sqrt(1.0 - s * s))
        assert mtf == pytest.approx(expected, rel=1e-9)

    def test_invalid_f_number_raises(self):
        with pytest.raises(ValueError, match="f_number"):
            diffraction_limited_mtf(-1.0, 550.0, 100.0)

    def test_invalid_lambda_raises(self):
        with pytest.raises(ValueError, match="lambda_nm"):
            diffraction_limited_mtf(4.0, 0.0, 100.0)

    def test_negative_freq_raises(self):
        with pytest.raises(ValueError, match="spatial_freq_lpmm"):
            diffraction_limited_mtf(4.0, 550.0, -10.0)


# ===========================================================================
# Geometric MTF (Gaussian)
# ===========================================================================

class TestGeometricMTFGaussian:
    def test_zero_spot_at_dc(self):
        """MTF at 0 freq = 1 (exp(0) = 1)."""
        mtf = geometric_mtf_gaussian(rms_spot_mm=0.01, spatial_freq_lpmm=0.0)
        assert mtf == pytest.approx(1.0, abs=1e-14)

    def test_zero_spot_all_freqs_one(self):
        """Zero spot radius → MTF = 1 at all spatial frequencies."""
        for nu in [0.0, 10.0, 100.0, 500.0]:
            mtf = geometric_mtf_gaussian(0.0, nu)
            assert mtf == pytest.approx(1.0, abs=1e-14)

    def test_decreasing_with_frequency(self):
        """MTF_geo is monotone decreasing."""
        freqs = np.linspace(0.0, 200.0, 20)
        mtfs = [geometric_mtf_gaussian(0.01, nu) for nu in freqs]
        for i in range(1, len(mtfs)):
            assert mtfs[i] <= mtfs[i - 1] + 1e-12

    def test_analytic_value(self):
        """MTF_geo(ν) = exp(−(π·r·ν)²).
        r=0.01 mm, ν=50 lp/mm → exp(−(π·0.01·50)²) = exp(−(0.5π)²).
        """
        r, nu = 0.01, 50.0
        expected = math.exp(-(math.pi * r * nu) ** 2)
        mtf = geometric_mtf_gaussian(r, nu)
        assert mtf == pytest.approx(expected, rel=1e-9)

    def test_negative_spot_raises(self):
        with pytest.raises(ValueError, match="rms_spot_mm"):
            geometric_mtf_gaussian(-0.001, 100.0)


# ===========================================================================
# MTFResult and mtf_from_lens_system
# ===========================================================================

class TestMTFFromLensSystem:
    def _system(self, f=0.1, do=0.3):
        return _single_lens_system(f, do)

    def test_returns_mtf_result(self):
        system = self._system()
        result = mtf_from_lens_system(system, object_distance_m=0.3, f_number=4.0)
        assert isinstance(result, MTFResult)

    def test_dc_mtf_is_one(self):
        """MTF at 0 lp/mm should be 1.0."""
        system = self._system()
        result = mtf_from_lens_system(
            system, object_distance_m=0.3, f_number=4.0,
            spatial_freqs_lpmm=[0.0, 50.0, 100.0]
        )
        assert result.mtf_diffraction_limited[0] == pytest.approx(1.0, abs=1e-10)

    def test_mtf_above_cutoff_is_zero(self):
        """MTF at twice the cut-off frequency should be 0."""
        system = self._system()
        nu_c = diffraction_cutoff_lpmm(4.0, 550.0)
        result = mtf_from_lens_system(
            system, object_distance_m=0.3, f_number=4.0,
            spatial_freqs_lpmm=[nu_c * 2.0]
        )
        assert result.mtf_diffraction_limited[0] == 0.0

    def test_cutoff_freq_stored(self):
        """cutoff_freq_lpmm is computed and stored."""
        system = self._system()
        result = mtf_from_lens_system(system, object_distance_m=0.3, f_number=4.0)
        expected_cutoff = diffraction_cutoff_lpmm(4.0, 550.0)
        assert result.cutoff_freq_lpmm == pytest.approx(expected_cutoff, rel=1e-9)

    def test_efl_stored(self):
        """efl_m is stored for a powered system."""
        system = self._system(f=0.1)
        result = mtf_from_lens_system(system, object_distance_m=0.3, f_number=4.0)
        assert result.efl_m == pytest.approx(0.1, rel=1e-9)

    def test_rms_spot_nonnegative(self):
        system = self._system()
        result = mtf_from_lens_system(system, object_distance_m=0.3, f_number=4.0)
        assert result.rms_spot_mm >= 0.0

    def test_geometric_mtf_dc_is_one(self):
        """Geometric MTF at 0 lp/mm = 1."""
        system = self._system()
        result = mtf_from_lens_system(
            system, object_distance_m=0.3, f_number=4.0,
            spatial_freqs_lpmm=[0.0, 50.0]
        )
        assert result.mtf_geometric[0] == pytest.approx(1.0, abs=1e-10)

    def test_spatial_freqs_len_matches_mtf_len(self):
        system = self._system()
        freqs = [0.0, 50.0, 100.0, 150.0]
        result = mtf_from_lens_system(
            system, object_distance_m=0.3, f_number=4.0,
            spatial_freqs_lpmm=freqs
        )
        assert len(result.mtf_diffraction_limited) == len(freqs)
        assert len(result.mtf_geometric) == len(freqs)

    def test_to_dict_has_all_keys(self):
        system = self._system()
        result = mtf_from_lens_system(system, object_distance_m=0.3, f_number=4.0)
        d = result.to_dict()
        for key in ("spatial_freqs_lpmm", "mtf_diffraction_limited", "mtf_geometric",
                    "f_number", "lambda_nm", "rms_spot_mm", "cutoff_freq_lpmm"):
            assert key in d

    def test_mtf_50lpmm_property(self):
        """mtf_50lpmm interpolates correctly from the computed curve."""
        system = self._system()
        result = mtf_from_lens_system(
            system, object_distance_m=0.3, f_number=4.0,
            spatial_freqs_lpmm=list(np.linspace(0.0, 200.0, 50))
        )
        mtf_at_50 = result.mtf_50lpmm
        assert 0.0 <= mtf_at_50 <= 1.0

    def test_invalid_f_number_raises(self):
        system = self._system()
        with pytest.raises(ValueError, match="f_number"):
            mtf_from_lens_system(system, object_distance_m=0.3, f_number=0.0)

    def test_invalid_lambda_raises(self):
        system = self._system()
        with pytest.raises(ValueError, match="lambda_nm"):
            mtf_from_lens_system(system, object_distance_m=0.3, f_number=4.0, lambda_nm=-550.0)

    def test_custom_wavelength_changes_cutoff(self):
        """Shorter wavelength → higher cut-off → MTF non-zero at higher frequencies."""
        system = self._system()
        nu_c_550 = diffraction_cutoff_lpmm(4.0, 550.0)
        nu_c_450 = diffraction_cutoff_lpmm(4.0, 450.0)
        assert nu_c_450 > nu_c_550


# ===========================================================================
# Module import smoke tests
# ===========================================================================

class TestModuleImports:
    def test_tolerancing_import(self):
        import kerf_optics.tolerancing  # noqa: F401

    def test_mtf_import(self):
        import kerf_optics.mtf  # noqa: F401
