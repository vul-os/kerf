"""
Tests for kerf_cad_core.fatigue.sn_corpus — ASTM/BS7608 S-N corpus (T-100d).

Verifies:
  1. All five curves are present: ASTM-A36, ASTM-A572-50, Al-6061-T6,
     BS7608-B, BS7608-C.
  2. Each curve's Basquin fit converges to the published anchor points to
     within 1% relative error (|σ_fit − σ_published| / σ_published ≤ 0.01).
  3. Basquin exponent b is negative.
  4. SNcurve.sigma_a() and N_cycles() are consistent inverses.
  5. list_curves() returns all five names.
  6. get_curve() returns the correct SNcurve or raises KeyError for unknown.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.fatigue.sn_corpus import (
    SNcurve,
    SN_CORPUS,
    get_curve,
    list_curves,
)


# ---------------------------------------------------------------------------
# Expected corpus membership
# ---------------------------------------------------------------------------

_EXPECTED_NAMES = {"ASTM-A36", "ASTM-A572-50", "Al-6061-T6", "BS7608-B", "BS7608-C"}


class TestCorpusMembership:
    def test_all_expected_curves_present(self):
        actual = set(SN_CORPUS.keys())
        assert _EXPECTED_NAMES <= actual, (
            f"Missing curves: {_EXPECTED_NAMES - actual}"
        )

    def test_list_curves_returns_all(self):
        names = list_curves()
        assert isinstance(names, list)
        assert set(names) >= _EXPECTED_NAMES

    def test_get_curve_returns_snc(self):
        for name in _EXPECTED_NAMES:
            curve = get_curve(name)
            assert isinstance(curve, SNcurve)

    def test_get_curve_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            get_curve("NONEXISTENT-MATERIAL-XYZ")


# ---------------------------------------------------------------------------
# Basquin exponent sanity
# ---------------------------------------------------------------------------

class TestBasquinExponent:
    @pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
    def test_b_is_negative(self, name):
        curve = get_curve(name)
        assert curve.b < 0, (
            f"{name}: Basquin exponent b={curve.b} must be negative"
        )

    @pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
    def test_Sf_prime_positive(self, name):
        curve = get_curve(name)
        assert curve.Sf_prime > 0, (
            f"{name}: Sf_prime={curve.Sf_prime} must be positive"
        )


# ---------------------------------------------------------------------------
# 1% convergence to published anchor points
# ---------------------------------------------------------------------------

_TOL = 0.01  # 1% relative tolerance


def _relative_err(fit: float, published: float) -> float:
    return abs(fit - published) / published


@pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
class TestBasquinFitAnchor1:
    """Low-life anchor: Basquin fit must reproduce σ₁ at 2N₁ to within 1%."""

    def test_sigma_at_anchor1(self, name):
        curve = get_curve(name)
        sigma_fit = curve.sigma_a(curve.two_N_anchor1)
        rel_err = _relative_err(sigma_fit, curve.sigma_anchor1)
        assert rel_err <= _TOL, (
            f"{name} anchor1: fit={sigma_fit/1e6:.3f} MPa, "
            f"published={curve.sigma_anchor1/1e6:.3f} MPa, "
            f"rel_err={rel_err:.4f} > {_TOL}"
        )


@pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
class TestBasquinFitAnchor2:
    """High-life anchor: Basquin fit must reproduce σ₂ at 2N₂ to within 1%."""

    def test_sigma_at_anchor2(self, name):
        curve = get_curve(name)
        sigma_fit = curve.sigma_a(curve.two_N_anchor2)
        rel_err = _relative_err(sigma_fit, curve.sigma_anchor2)
        assert rel_err <= _TOL, (
            f"{name} anchor2: fit={sigma_fit/1e6:.3f} MPa, "
            f"published={curve.sigma_anchor2/1e6:.3f} MPa, "
            f"rel_err={rel_err:.4f} > {_TOL}"
        )


# ---------------------------------------------------------------------------
# Round-trip: sigma_a ↔ N_cycles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
class TestRoundTrip:
    """sigma_a(2N) and N_cycles(σ) must be consistent inverses (< 0.01% error)."""

    def test_round_trip_from_sigma(self, name):
        curve = get_curve(name)
        # Pick a midpoint 2N between the two anchors (geometric mean)
        two_N_mid = math.sqrt(curve.two_N_anchor1 * curve.two_N_anchor2)
        sigma_mid = curve.sigma_a(two_N_mid)
        N_back = curve.N_cycles(sigma_mid)
        two_N_back = N_back * 2.0
        rel_err = abs(two_N_back - two_N_mid) / two_N_mid
        assert rel_err < 1e-6, (
            f"{name}: round-trip 2N error {rel_err:.2e} > 1e-6"
        )


# ---------------------------------------------------------------------------
# Specific published-value spot checks
# ---------------------------------------------------------------------------

class TestPublishedSpotChecks:
    """Spot-check key data points for each curve against the published sources."""

    def test_a36_anchor1_345MPa(self):
        """ASTM-A36: σ(2N=2000) ≈ 345 MPa within 1%."""
        curve = get_curve("ASTM-A36")
        sigma = curve.sigma_a(2.0e3)
        assert abs(sigma - 345e6) / 345e6 < _TOL

    def test_a36_anchor2_165MPa(self):
        """ASTM-A36: σ(2N=2×10⁶) ≈ 165 MPa within 1%."""
        curve = get_curve("ASTM-A36")
        sigma = curve.sigma_a(2.0e6)
        assert abs(sigma - 165e6) / 165e6 < _TOL

    def test_a572_anchor1_430MPa(self):
        """ASTM-A572-50: σ(2N=2000) ≈ 430 MPa within 1%."""
        curve = get_curve("ASTM-A572-50")
        sigma = curve.sigma_a(2.0e3)
        assert abs(sigma - 430e6) / 430e6 < _TOL

    def test_a572_anchor2_207MPa(self):
        """ASTM-A572-50: σ(2N=2×10⁶) ≈ 207 MPa within 1%."""
        curve = get_curve("ASTM-A572-50")
        sigma = curve.sigma_a(2.0e6)
        assert abs(sigma - 207e6) / 207e6 < _TOL

    def test_al6061_anchor1_310MPa(self):
        """Al-6061-T6: σ(2N=2000) ≈ 310 MPa within 1%."""
        curve = get_curve("Al-6061-T6")
        sigma = curve.sigma_a(2.0e3)
        assert abs(sigma - 310e6) / 310e6 < _TOL

    def test_al6061_anchor2_96MPa(self):
        """Al-6061-T6: σ(2N=2×10⁷) ≈ 96 MPa within 1%."""
        curve = get_curve("Al-6061-T6")
        sigma = curve.sigma_a(2.0e7)
        assert abs(sigma - 96e6) / 96e6 < _TOL

    def test_bs7608b_anchor1_100MPa(self):
        """BS7608-B: σ(2N=2×10⁵) ≈ 100 MPa within 1%."""
        curve = get_curve("BS7608-B")
        sigma = curve.sigma_a(2.0e5)
        assert abs(sigma - 100e6) / 100e6 < _TOL

    def test_bs7608b_anchor2_632MPa(self):
        """BS7608-B: σ(2N=2×10⁷) ≈ 63.2 MPa within 1%."""
        curve = get_curve("BS7608-B")
        sigma = curve.sigma_a(2.0e7)
        assert abs(sigma - 63.2e6) / 63.2e6 < _TOL

    def test_bs7608c_anchor1_78MPa(self):
        """BS7608-C: σ(2N=2×10⁵) ≈ 78 MPa within 1%."""
        curve = get_curve("BS7608-C")
        sigma = curve.sigma_a(2.0e5)
        assert abs(sigma - 78e6) / 78e6 < _TOL

    def test_bs7608c_anchor2_50MPa(self):
        """BS7608-C: σ(2N=2×10⁷) ≈ 50 MPa within 1%."""
        curve = get_curve("BS7608-C")
        sigma = curve.sigma_a(2.0e7)
        assert abs(sigma - 50e6) / 50e6 < _TOL


# ---------------------------------------------------------------------------
# Fatigue __init__ re-export
# ---------------------------------------------------------------------------

class TestFatigueInitExport:
    def test_sn_corpus_re_exported_from_fatigue(self):
        from kerf_cad_core.fatigue import SN_CORPUS, get_curve as gc, list_curves as lc
        assert isinstance(SN_CORPUS, dict)
        assert callable(gc)
        assert callable(lc)
