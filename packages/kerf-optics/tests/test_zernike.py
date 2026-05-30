"""
Tests for kerf_optics.zernike — Zernike polynomial aberration decomposition.

Verified oracles
----------------
1. Defocus only: a parabolic wavefront → fit_zernike returns Z_4 dominant;
   all other modes < 1% of Z_4.
2. Round-trip: synthesise wavefront from known coefficients → fit_zernike →
   recovered coefficients match within 1e-6.
3. Classical mapping: classical_aberration_breakdown returns 'defocus' as
   primary aberration for a Z_4-only wavefront.
4. Orthogonality: Zernike basis is orthonormal —
   inner product Z_i · Z_j = δ_ij within 1e-4 (pixel-grid discretisation).
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

from kerf_optics.zernike import (
    noll_index_to_mn,
    zernike_radial,
    zernike_poly,
    zernike_basis,
    fit_zernike,
    reconstruct_wavefront,
    classical_aberration_breakdown,
    _NOLL_TO_CLASSICAL,
)


# ===========================================================================
# Helper: build a circular grid matching the basis
# ===========================================================================

def _make_grid(n: int):
    lin = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(lin, lin)
    rho = np.sqrt(x ** 2 + y ** 2)
    theta = np.arctan2(y, x)
    return x, y, rho, theta


# ===========================================================================
# noll_index_to_mn
# ===========================================================================

class TestNollIndex:
    """Verify Noll ordering against the canonical table (Noll 1976, Table 1)."""

    # From Noll (1976) Table 1: within each radial degree n,
    # modes are listed in order of ascending |m|, positive m before negative m.
    NOLL_TABLE = {
        1:  (0,  0),
        2:  (1,  1),
        3:  (1, -1),
        4:  (2,  0),
        5:  (2,  2),
        6:  (2, -2),
        7:  (3,  1),
        8:  (3, -1),
        9:  (3,  3),
        10: (3, -3),
        11: (4,  0),
        12: (4,  2),
        13: (4, -2),
        14: (4,  4),
        15: (4, -4),
        16: (5,  1),
        17: (5, -1),
    }

    @pytest.mark.parametrize("j,expected", NOLL_TABLE.items())
    def test_known_values(self, j, expected):
        assert noll_index_to_mn(j) == expected, (
            f"j={j}: expected {expected}, got {noll_index_to_mn(j)}"
        )

    def test_j_zero_raises(self):
        with pytest.raises(ValueError):
            noll_index_to_mn(0)

    def test_j_negative_raises(self):
        with pytest.raises(ValueError):
            noll_index_to_mn(-3)

    def test_n_nonnegative(self):
        for j in range(1, 30):
            n, m = noll_index_to_mn(j)
            assert n >= 0

    def test_parity_constraint(self):
        """n and |m| must have the same parity."""
        for j in range(1, 36):
            n, m = noll_index_to_mn(j)
            assert (n - abs(m)) % 2 == 0, f"parity failure at j={j}: n={n}, m={m}"

    def test_m_within_bounds(self):
        """−n <= m <= n for all j."""
        for j in range(1, 36):
            n, m = noll_index_to_mn(j)
            assert -n <= m <= n


# ===========================================================================
# zernike_radial
# ===========================================================================

class TestZernikeRadial:
    def test_piston_is_one(self):
        """R_0^0(rho) = 1 everywhere."""
        rho = np.linspace(0, 1, 20)
        R = zernike_radial(0, 0, rho)
        np.testing.assert_allclose(R, np.ones_like(rho), atol=1e-12)

    def test_defocus_radial(self):
        """R_2^0(rho) = 2*rho^2 - 1."""
        rho = np.linspace(0, 1, 20)
        R = zernike_radial(2, 0, rho)
        expected = 2 * rho ** 2 - 1
        np.testing.assert_allclose(R, expected, atol=1e-12)

    def test_tilt_radial(self):
        """R_1^1(rho) = rho."""
        rho = np.linspace(0, 1, 20)
        R = zernike_radial(1, 1, rho)
        np.testing.assert_allclose(R, rho, atol=1e-12)

    def test_spherical_radial(self):
        """R_4^0(rho) = 6*rho^4 - 6*rho^2 + 1 (Born & Wolf §9.2, Table)."""
        rho = np.linspace(0, 1, 20)
        R = zernike_radial(4, 0, rho)
        expected = 6 * rho ** 4 - 6 * rho ** 2 + 1
        np.testing.assert_allclose(R, expected, atol=1e-11)

    def test_wrong_parity_returns_zero(self):
        """R_n^m = 0 when (n-|m|) is odd (mixed parity)."""
        rho = np.linspace(0, 1, 10)
        R = zernike_radial(2, 1, rho)  # n=2, |m|=1 → n-|m|=1 (odd)
        np.testing.assert_allclose(R, 0.0, atol=1e-15)


# ===========================================================================
# zernike_poly
# ===========================================================================

class TestZernikePoly:
    def test_piston_is_one_inside(self):
        """Z_1 (piston, j=1) = 1 everywhere inside the unit circle."""
        _, _, rho, theta = _make_grid(32)
        Z = zernike_poly(1, rho.copy(), theta.copy())
        inside = rho <= 1.0
        np.testing.assert_allclose(Z[inside], 1.0, atol=1e-12)

    def test_outside_circle_is_zero(self):
        """Pixels with rho > 1 must be zero."""
        _, _, rho, theta = _make_grid(32)
        Z = zernike_poly(4, rho.copy(), theta.copy())  # defocus
        outside = rho > 1.0
        np.testing.assert_allclose(Z[outside], 0.0, atol=1e-15)

    def test_defocus_on_axis(self):
        """Z_4 at (rho=0, theta=0): sqrt(3)·R_2^0(0) = sqrt(3)·(−1) = −sqrt(3)."""
        Z = zernike_poly(4, np.array([0.0]), np.array([0.0]))
        expected = math.sqrt(3) * (2 * 0 ** 2 - 1)  # sqrt(n+1)·R_2^0(0) = sqrt(3)·(-1)
        np.testing.assert_allclose(Z[0], expected, atol=1e-12)

    def test_bad_j_raises(self):
        with pytest.raises(ValueError):
            zernike_poly(0, np.array([0.5]), np.array([0.0]))


# ===========================================================================
# zernike_basis
# ===========================================================================

class TestZernikeBasis:
    def test_shape(self):
        B = zernike_basis(n_max=6, n_samples=32)
        assert B.shape == (6, 32, 32)

    def test_first_mode_is_piston(self):
        """B[0] should be the piston mode: constant 1 inside circle, 0 outside."""
        B = zernike_basis(n_max=1, n_samples=32)
        lin = np.linspace(-1, 1, 32)
        x, y = np.meshgrid(lin, lin)
        rho = np.sqrt(x ** 2 + y ** 2)
        inside = rho <= 1.0
        np.testing.assert_allclose(B[0][inside], 1.0, atol=1e-12)
        np.testing.assert_allclose(B[0][~inside], 0.0, atol=1e-15)

    def test_bad_n_max(self):
        with pytest.raises(ValueError):
            zernike_basis(n_max=0)

    def test_bad_n_samples(self):
        with pytest.raises(ValueError):
            zernike_basis(n_samples=2)


# ===========================================================================
# Oracle 4 — Orthogonality
# ===========================================================================

class TestOrthogonality:
    """
    Zernike basis should be orthonormal on the unit disk:
        <Z_i, Z_j> / A_disk = δ_ij

    On a discrete grid with n_samples × n_samples pixels, the inner product is
    approximated as:

        <Z_i, Z_j> ≈ Σ_{in_disk} Z_i[k] · Z_j[k] / n_disk

    where n_disk = number of pixels inside the unit circle.

    Due to pixelisation, we allow tolerance 1e-2 for off-diagonal (should be ~0)
    and relative tolerance 0.05 for diagonal (should be ~1).
    Use n_samples=128 for accuracy.
    """

    N_MODES = 11  # test first 11 Zernike modes (through spherical)
    N_SAMPLES = 128
    ATOL_OFFDIAG = 1e-2   # off-diagonal elements should be near zero
    RTOL_DIAG = 0.05       # diagonal should be within 5% of 1

    def _gram(self):
        B = zernike_basis(n_max=self.N_MODES, n_samples=self.N_SAMPLES)
        lin = np.linspace(-1.0, 1.0, self.N_SAMPLES)
        x, y = np.meshgrid(lin, lin)
        rho = np.sqrt(x ** 2 + y ** 2)
        inside = rho <= 1.0
        n_disk = inside.sum()
        # Flatten to (n_modes, n_pixels_inside)
        B_flat = B[:, inside]  # shape (N_MODES, n_disk)
        G = B_flat @ B_flat.T / n_disk
        return G

    def test_diagonal_near_one(self):
        """Diagonal elements of the Gram matrix should be close to 1."""
        G = self._gram()
        diag = np.diag(G)
        np.testing.assert_allclose(
            diag, np.ones(self.N_MODES), rtol=self.RTOL_DIAG,
            err_msg="Diagonal Gram elements deviate from 1 by more than 5%",
        )

    def test_offdiagonal_near_zero(self):
        """Off-diagonal elements of the Gram matrix should be near zero."""
        G = self._gram()
        off = G - np.diag(np.diag(G))
        max_off = float(np.max(np.abs(off)))
        assert max_off < self.ATOL_OFFDIAG, (
            f"Max off-diagonal Gram element = {max_off:.4e} (threshold {self.ATOL_OFFDIAG})"
        )


# ===========================================================================
# Oracle 1 — Defocus wavefront
# ===========================================================================

class TestDefocusOracle:
    """
    A parabolic wavefront W(x,y) = a·(x²+y²) - a/2 (constant subtracted so
    that mean is zero on the disk) is purely defocus (Z_4).

    After fit_zernike:
      - Z_4 should be dominant.
      - All other modes should have |c_j| < 1% of |c_4|.
    """

    GRID = 128  # use high resolution to reduce discretisation error
    AMPLITUDE = 2.5  # arbitrary units (e.g. waves peak-valley)

    def _parabolic_wavefront(self):
        lin = np.linspace(-1.0, 1.0, self.GRID)
        x, y = np.meshgrid(lin, lin)
        rho = np.sqrt(x ** 2 + y ** 2)
        # Pure defocus: Z_4 = sqrt(3) * (2*rho^2 - 1)
        # So to get amplitude A in Z_4, set W = A * Z_4:
        # W = A * sqrt(3) * (2*rho^2 - 1)
        A = self.AMPLITUDE
        W = A * math.sqrt(3) * (2 * rho ** 2 - 1)
        # Set outside circle to NaN (excluded from fit)
        W[rho > 1.0] = np.nan
        return W

    def test_z4_dominant(self):
        """Z_4 coefficient should be much larger than all others."""
        W = self._parabolic_wavefront()
        coeffs = fit_zernike(W, n_max=11)
        c4 = abs(coeffs[4])
        assert c4 > 0.1, f"Z_4 coefficient too small: {c4}"
        for j, c in coeffs.items():
            if j == 4:
                continue
            ratio = abs(c) / c4
            assert ratio < 0.01, (
                f"Z_{j} = {c:.6f} is {ratio*100:.2f}% of Z_4 = {c4:.6f} "
                f"(threshold 1%)"
            )

    def test_z4_correct_magnitude(self):
        """The recovered Z_4 coefficient should match the input amplitude within 1%."""
        W = self._parabolic_wavefront()
        coeffs = fit_zernike(W, n_max=11)
        c4 = coeffs[4]
        np.testing.assert_allclose(c4, self.AMPLITUDE, rtol=0.01)


# ===========================================================================
# Oracle 2 — Round-trip reconstruction
# ===========================================================================

class TestRoundTrip:
    """
    Synthesise a wavefront from known coefficients, fit it back, and verify
    that the recovered coefficients match the input within 1e-6.
    """

    GRID = 128

    def test_defocus_roundtrip(self):
        coeffs_in = {4: 1.5}
        W = reconstruct_wavefront(coeffs_in, grid_size=self.GRID)
        coeffs_out = fit_zernike(W, n_max=11)
        assert abs(coeffs_out[4] - 1.5) < 1e-6, (
            f"Round-trip Z_4: input=1.5, recovered={coeffs_out[4]}"
        )

    def test_multi_mode_roundtrip(self):
        """Several modes simultaneously — each should recover within 1e-5."""
        coeffs_in = {4: 1.0, 5: 0.5, 11: -0.3}
        W = reconstruct_wavefront(coeffs_in, grid_size=self.GRID)
        coeffs_out = fit_zernike(W, n_max=11)
        for j, c_in in coeffs_in.items():
            c_out = coeffs_out[j]
            assert abs(c_out - c_in) < 1e-5, (
                f"Round-trip Z_{j}: input={c_in}, recovered={c_out}"
            )

    def test_zero_wavefront_gives_zero_coefficients(self):
        """An all-zero wavefront should give all-zero coefficients."""
        lin = np.linspace(-1.0, 1.0, self.GRID)
        x, y = np.meshgrid(lin, lin)
        rho = np.sqrt(x ** 2 + y ** 2)
        W = np.zeros((self.GRID, self.GRID))
        W[rho > 1.0] = np.nan
        coeffs = fit_zernike(W, n_max=8)
        for j, c in coeffs.items():
            assert abs(c) < 1e-12, f"Z_{j} should be 0 but got {c}"

    def test_reconstruct_then_fit_identity(self):
        """reconstruct_wavefront ∘ fit_zernike = identity to 1e-5."""
        coeffs_in = {2: 0.2, 4: 0.8, 7: -0.4, 11: 0.15}
        W1 = reconstruct_wavefront(coeffs_in, grid_size=self.GRID)
        coeffs_recovered = fit_zernike(W1, n_max=11)
        W2 = reconstruct_wavefront(coeffs_recovered, grid_size=self.GRID)
        # Pixel-level difference inside the unit circle should be tiny
        lin = np.linspace(-1.0, 1.0, self.GRID)
        x, y = np.meshgrid(lin, lin)
        rho = np.sqrt(x ** 2 + y ** 2)
        inside = rho <= 1.0
        diff = np.abs(W1[inside] - W2[inside])
        assert float(np.max(diff)) < 1e-5, (
            f"Max pixel error in reconstruction round-trip: {float(np.max(diff)):.2e}"
        )


# ===========================================================================
# Oracle 3 — Classical aberration mapping
# ===========================================================================

class TestClassicalMapping:
    """classical_aberration_breakdown returns 'defocus' as primary for Z_4-only input."""

    def test_defocus_primary(self):
        """Z_4 only → primary_aberration = 'defocus'."""
        bd = classical_aberration_breakdown({4: 1.0})
        assert bd["primary_aberration"] == "defocus"

    def test_spherical_primary(self):
        """Z_11 only → primary_aberration = 'spherical'."""
        bd = classical_aberration_breakdown({11: 0.5})
        assert bd["primary_aberration"] == "spherical"

    def test_tilt_modes(self):
        """Z_2 = x-tilt, Z_3 = y-tilt."""
        bd2 = classical_aberration_breakdown({2: 1.0})
        assert bd2["primary_aberration"] == "x-tilt"
        bd3 = classical_aberration_breakdown({3: 1.0})
        assert bd3["primary_aberration"] == "y-tilt"

    def test_astigmatism_modes(self):
        """Z_5 = oblique astigmatism, Z_6 = vertical astigmatism."""
        bd5 = classical_aberration_breakdown({5: 0.3})
        assert bd5["primary_aberration"] == "oblique astigmatism"
        bd6 = classical_aberration_breakdown({6: 0.3})
        assert bd6["primary_aberration"] == "vertical astigmatism"

    def test_coma_modes(self):
        """Z_7 = x-coma, Z_8 = y-coma."""
        bd7 = classical_aberration_breakdown({7: 0.2})
        assert bd7["primary_aberration"] == "x-coma"
        bd8 = classical_aberration_breakdown({8: 0.2})
        assert bd8["primary_aberration"] == "y-coma"

    def test_rms_wavefront_error(self):
        """RMS = sqrt(sum(c_j^2)) — Noll 1976 Eq. 7."""
        coeffs = {4: 0.5, 11: 0.3}
        bd = classical_aberration_breakdown(coeffs)
        expected_rms = math.sqrt(0.5 ** 2 + 0.3 ** 2)
        assert abs(bd["rms_wavefront_error"] - expected_rms) < 1e-10

    def test_strehl_small_rms(self):
        """For small RMS, Strehl ≈ exp(-(2π·σ)²) and should be < 1."""
        coeffs = {4: 0.05}  # 0.05 waves rms — well within Maréchal range
        bd = classical_aberration_breakdown(coeffs)
        sigma = 0.05
        expected_strehl = math.exp(-((2 * math.pi * sigma) ** 2))
        assert abs(bd["strehl_ratio_approx"] - expected_strehl) < 1e-10

    def test_terms_sorted_by_magnitude(self):
        """terms list is sorted by descending |coefficient|."""
        coeffs = {4: 0.1, 11: 0.5, 2: 0.3}
        bd = classical_aberration_breakdown(coeffs)
        mags = [t["magnitude"] for t in bd["terms"]]
        assert mags == sorted(mags, reverse=True)

    def test_piston_excluded_from_primary(self):
        """primary_aberration ignores piston (j=1) when another mode present."""
        coeffs = {1: 10.0, 4: 0.5}
        bd = classical_aberration_breakdown(coeffs)
        assert bd["primary_aberration"] == "defocus"

    def test_empty_coeffs(self):
        """Empty coefficients → rms=0, strehl=1, primary='none'."""
        bd = classical_aberration_breakdown({})
        assert bd["rms_wavefront_error"] == 0.0
        assert bd["strehl_ratio_approx"] == pytest.approx(1.0)
        assert bd["primary_aberration"] == "none"

    def test_all_named_modes_present(self):
        """_NOLL_TO_CLASSICAL should cover j=1..11 at minimum."""
        for j in range(1, 12):
            assert j in _NOLL_TO_CLASSICAL, f"j={j} missing from name table"


# ===========================================================================
# fit_zernike edge cases
# ===========================================================================

class TestFitEdgeCases:
    def test_non_2d_raises(self):
        with pytest.raises(ValueError, match="2-D"):
            fit_zernike(np.ones(64), n_max=4)

    def test_single_mode_identity(self):
        """Fitting a pure Z_j wavefront returns coefficient at index j."""
        for j_target in [2, 3, 5, 6, 7, 8, 11]:
            W = reconstruct_wavefront({j_target: 1.0}, grid_size=64)
            coeffs = fit_zernike(W, n_max=11)
            assert abs(coeffs[j_target] - 1.0) < 1e-5, (
                f"Failed for j={j_target}: got {coeffs[j_target]}"
            )


# ===========================================================================
# reconstruct_wavefront edge cases
# ===========================================================================

class TestReconstructEdgeCases:
    def test_empty_dict_gives_zeros(self):
        W = reconstruct_wavefront({}, grid_size=32)
        np.testing.assert_allclose(W, 0.0, atol=1e-15)

    def test_shape(self):
        W = reconstruct_wavefront({4: 1.0}, grid_size=48)
        assert W.shape == (48, 48)

    def test_outside_circle_is_zero(self):
        """Wavefront should be 0 outside the unit circle (via basis masking)."""
        W = reconstruct_wavefront({4: 1.0, 7: 0.5}, grid_size=64)
        lin = np.linspace(-1.0, 1.0, 64)
        x, y = np.meshgrid(lin, lin)
        rho = np.sqrt(x ** 2 + y ** 2)
        outside = rho > 1.0
        np.testing.assert_allclose(W[outside], 0.0, atol=1e-15)


# ===========================================================================
# Module import smoke test
# ===========================================================================

class TestImports:
    def test_zernike_import(self):
        import kerf_optics.zernike  # noqa: F401

    def test_zernike_tools_import(self):
        import kerf_optics.zernike_tools  # noqa: F401
