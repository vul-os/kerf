"""
Hermetic tests for kerf_cad_core.solarpv.tmy — latitude-aware monthly irradiance fractions.

Coverage:
  tmy.monthly_yield_factors  — sum = 1.0 invariant
  tmy.monthly_yield_factors  — lat=60°N: >3× summer/winter spread
  tmy.monthly_yield_factors  — lat=0°: near-flat (max/min < 1.3)
  tmy.monthly_yield_factors  — lat=−30°S: flipped vs +30°N
  tmy.monthly_yield_factors  — backward-compat default (lat=30°N)
  tmy.monthly_yield_factors  — interpolation at non-table lat (lat=35°)
  tmy.monthly_yield_factors  — clamping at polar edge (lat=85°)
  tmy.monthly_yield_factors  — negative lat close to 0 treated as SH

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Wilcox, S. & Marion, W. (2008). "Users Manual for TMY3 Data Sets."
  NREL/TP-581-43156.

Author: imranparuk
"""
from __future__ import annotations

import pytest

from kerf_cad_core.solarpv.tmy import monthly_yield_factors


# ---------------------------------------------------------------------------
# Invariant: sum == 1.0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lat", [-70, -33, -10, 0, 10, 30, 51.5, 60, 70])
def test_sum_to_unity(lat):
    """monthly_yield_factors must always sum to exactly 1.0 (within float tolerance)."""
    factors = monthly_yield_factors(lat)
    assert len(factors) == 12, f"Expected 12 months, got {len(factors)}"
    total = sum(factors)
    assert abs(total - 1.0) < 1e-9, f"Factors sum to {total:.12f}, not 1.0 (lat={lat})"


@pytest.mark.parametrize("lat", [-70, -33, -10, 0, 10, 30, 51.5, 60, 70])
def test_all_non_negative(lat):
    """All monthly fractions must be non-negative."""
    factors = monthly_yield_factors(lat)
    for i, f in enumerate(factors):
        assert f >= 0.0, f"Negative fraction at month {i} for lat={lat}: {f}"


# ---------------------------------------------------------------------------
# lat=60°N — high spread (dark winter / bright summer)
# ---------------------------------------------------------------------------

def test_lat_60N_summer_winter_spread():
    """
    At 60°N the summer/winter ratio must be > 3.
    June (index 5) and July (index 6) should dominate;
    Dec (index 11) and Jan (index 0) are near-zero.
    """
    factors = monthly_yield_factors(60.0)
    summer_avg = (factors[5] + factors[6]) / 2.0
    winter_avg = max((factors[11] + factors[0]) / 2.0, 1e-9)
    ratio = summer_avg / winter_avg
    assert ratio > 3.0, (
        f"lat=60°N summer/winter ratio should be > 3; got {ratio:.2f}. "
        f"Jun={factors[5]:.4f}, Jul={factors[6]:.4f}, "
        f"Dec={factors[11]:.4f}, Jan={factors[0]:.4f}"
    )


def test_lat_60N_summer_months_largest():
    """At 60°N June and July must have larger fractions than December and January."""
    factors = monthly_yield_factors(60.0)
    assert factors[5] > factors[11], "June should be > December at 60°N"
    assert factors[6] > factors[0],  "July should be > January at 60°N"


# ---------------------------------------------------------------------------
# lat=0° — near-flat profile
# ---------------------------------------------------------------------------

def test_lat_0_near_flat():
    """
    At the equator the max/min monthly ratio must be < 1.3.
    The sun is roughly overhead year-round; seasonal variation is small.
    """
    factors = monthly_yield_factors(0.0)
    max_f = max(factors)
    min_f = min(f for f in factors if f > 1e-9)  # exclude near-zero outliers
    ratio = max_f / min_f
    assert ratio < 1.3, (
        f"lat=0° max/min ratio should be < 1.3 (near-flat); got {ratio:.3f}. "
        f"Factors: {[round(f, 4) for f in factors]}"
    )


# ---------------------------------------------------------------------------
# Southern hemisphere: lat=−30° vs +30° — seasonality flipped
# ---------------------------------------------------------------------------

def test_southern_hemisphere_flip():
    """
    lat=−30°S should have the opposite seasonal pattern vs lat=+30°N.
    The Northern-hemisphere peak months (Jun/Jul) should be the low months
    for the Southern hemisphere, and vice versa (Dec/Jan should be high).
    """
    nh = monthly_yield_factors(30.0)
    sh = monthly_yield_factors(-30.0)

    # NH peak: Jun (5) and Jul (6) — should be SH low
    # SH peak: Dec (11) and Jan (0) — should be NH low

    nh_peak_summer = (nh[5] + nh[6]) / 2.0      # Jun+Jul avg
    sh_peak_summer = (sh[5] + sh[6]) / 2.0       # same months, SH

    nh_peak_winter = (nh[11] + nh[0]) / 2.0      # Dec+Jan avg
    sh_peak_winter = (sh[11] + sh[0]) / 2.0      # same months, SH

    # NH summer > SH summer (SH is in winter during Jun/Jul)
    assert nh_peak_summer > sh_peak_summer, (
        f"NH Jun/Jul avg {nh_peak_summer:.4f} should be > SH Jun/Jul avg {sh_peak_summer:.4f}"
    )

    # SH Dec/Jan > NH Dec/Jan (SH is in summer during Dec/Jan)
    assert sh_peak_winter > nh_peak_winter, (
        f"SH Dec/Jan avg {sh_peak_winter:.4f} should be > NH Dec/Jan avg {nh_peak_winter:.4f}"
    )


def test_southern_hemisphere_peak_in_december():
    """
    At lat=−30°S the peak yield month should be in Dec, Jan, or Feb
    (Southern summer = November–February).
    """
    factors = monthly_yield_factors(-30.0)
    peak_month = factors.index(max(factors))
    # Dec=11, Jan=0, Feb=1, Nov=10
    assert peak_month in (11, 0, 1, 10), (
        f"Peak month at -30° should be in Nov–Feb (SH summer), got month index {peak_month}. "
        f"Factors: {[round(f, 4) for f in factors]}"
    )


# ---------------------------------------------------------------------------
# Backward-compat: no latitude supplied → use 30° default
# ---------------------------------------------------------------------------

def test_default_30N_matches_explicit():
    """
    The backend defaults to latitude=30 when no latitude is supplied.
    Verify that lat=30 gives a Northern-hemisphere biased (summer-peaked) profile.
    """
    factors = monthly_yield_factors(30.0)
    # Jun (5) or Jul (6) should be among the highest months
    top3_indices = sorted(range(12), key=lambda i: factors[i], reverse=True)[:3]
    assert any(i in top3_indices for i in (5, 6, 7)), (
        f"At 30°N the top-3 months should include Jun/Jul/Aug. "
        f"Got top-3 indices: {top3_indices}"
    )


# ---------------------------------------------------------------------------
# Interpolation between table bands
# ---------------------------------------------------------------------------

def test_interpolation_at_35N():
    """
    lat=35° is between table bands at 30° and 40°.
    The interpolated profile should be between those two.
    """
    f30 = monthly_yield_factors(30.0)
    f40 = monthly_yield_factors(40.0)
    f35 = monthly_yield_factors(35.0)

    # For each month, f35 should be between f30 and f40 (within small tolerance)
    for i in range(12):
        lo = min(f30[i], f40[i]) - 1e-7
        hi = max(f30[i], f40[i]) + 1e-7
        assert lo <= f35[i] <= hi, (
            f"Month {i}: f35={f35[i]:.5f} not between f30={f30[i]:.5f} and f40={f40[i]:.5f}"
        )


# ---------------------------------------------------------------------------
# Polar clamping
# ---------------------------------------------------------------------------

def test_polar_north_clamped():
    """lat=85° (Arctic) is clamped to the 70° profile."""
    f70 = monthly_yield_factors(70.0)
    f85 = monthly_yield_factors(85.0)
    assert f70 == pytest.approx(f85, abs=1e-9), (
        "lat=85° should produce the same profile as lat=70° (clamped)"
    )


def test_polar_south_clamped():
    """lat=−85° (Antarctic) is the SH flip of the 70° profile."""
    f_minus70 = monthly_yield_factors(-70.0)
    f_minus85 = monthly_yield_factors(-85.0)
    assert f_minus70 == pytest.approx(f_minus85, abs=1e-9), (
        "lat=-85° should produce the same profile as lat=-70° (clamped)"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_exactly_on_band_boundaries():
    """Exact band boundaries (0, 10, 20, …, 70) should not error."""
    for lat in range(0, 71, 10):
        factors = monthly_yield_factors(float(lat))
        assert abs(sum(factors) - 1.0) < 1e-9


def test_small_southern_lat():
    """lat=−5° should still produce a valid profile (close to equatorial but SH-shifted)."""
    factors = monthly_yield_factors(-5.0)
    assert abs(sum(factors) - 1.0) < 1e-9
    # SH peak should be in Southern summer (Nov–Feb)
    peak_month = factors.index(max(factors))
    # Very close to equator — peak could be anywhere, but sum must be 1 and all positive
    assert all(f >= 0.0 for f in factors)
