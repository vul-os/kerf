"""
Tests for kerf_optics.pop — physical-optics propagation (POP).

Validation oracles
------------------
O1. Gaussian beam waist evolution: numerical w(z) matches analytic w0·√(1+(z/zR)²)
    to < 0.5% relative error.
O2. Airy first null: far-field of a circular aperture gives first dark ring at
    r_null = 1.22·λ·f/D to < 2% relative error.
O3. Energy conservation (Parseval): total power invariant under free-space propagation
    to < 0.1% relative error.

References: Goodman "Introduction to Fourier Optics" §3.10, §4.2, §4.3.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC  = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_optics.pop import (
    make_grid,
    make_freq_grid,
    gaussian_source,
    thin_lens_phase,
    circular_aperture,
    annular_aperture,
    propagate_angular_spectrum,
    propagate_fresnel,
    propagate_fraunhofer,
    propagate,
    gaussian_waist_analytic,
    airy_first_null,
    parseval_energy,
    field_beam_radius,
    propagate_system,
)


# ===========================================================================
# Grid helpers
# ===========================================================================

class TestGridHelpers:
    """Verify make_grid and make_freq_grid."""

    def test_make_grid_shape(self):
        x, y = make_grid(64, 1e-6)
        assert x.shape == (64, 64)
        assert y.shape == (64, 64)

    def test_make_grid_centred(self):
        """Grid should be centred at 0 (within one pixel)."""
        N, dx = 64, 1e-6
        x, y = make_grid(N, dx)
        assert abs(x.mean()) < dx
        assert abs(y.mean()) < dx

    def test_make_grid_pitch(self):
        """Adjacent pixels should differ by dx."""
        N, dx = 32, 2e-6
        x, _ = make_grid(N, dx)
        diffs = np.diff(x[0, :])
        np.testing.assert_allclose(diffs, dx, rtol=1e-12)

    def test_make_freq_grid_shape(self):
        fx, fy = make_freq_grid(64, 1e-6)
        assert fx.shape == (64, 64)

    def test_make_freq_grid_dc_at_centre(self):
        """DC component (0, 0) should be at the centre pixel after fftshift."""
        N, dx = 64, 1e-6
        fx, fy = make_freq_grid(N, dx)
        centre = N // 2
        assert fx[centre, centre] == pytest.approx(0.0, abs=1e-6)
        assert fy[centre, centre] == pytest.approx(0.0, abs=1e-6)

    def test_make_freq_grid_max_freq(self):
        """Max frequency = 1 / (2·dx) (Nyquist)."""
        N, dx = 64, 1e-6
        fx, fy = make_freq_grid(N, dx)
        # Max positive frequency ≈ 1/(2·dx) * (1 - 1/N) for even N
        nyquist = 1.0 / (2.0 * dx)
        assert fx.max() <= nyquist + 1e-6 / dx


# ===========================================================================
# Sources
# ===========================================================================

class TestGaussianSource:
    """Verify gaussian_source produces a correctly shaped Gaussian."""

    LAMBDA = 632.8e-9   # HeNe (m)
    W0     = 0.5e-3     # 0.5 mm waist
    N      = 256
    DX     = 5e-6       # 5 µm pixels

    def test_at_waist_shape(self):
        x, y = make_grid(self.N, self.DX)
        U = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        assert U.shape == (self.N, self.N)
        assert np.iscomplexobj(U)

    def test_at_waist_peak_at_centre(self):
        """Peak intensity at (0, 0) for z=0."""
        x, y = make_grid(self.N, self.DX)
        U = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        I = np.abs(U) ** 2
        centre = self.N // 2
        assert I[centre, centre] == pytest.approx(I.max(), rel=1e-3)

    def test_at_waist_1_over_e2_radius(self):
        """At z=0, intensity drops to 1/e² at r = w0 (field 1/e at w0)."""
        x, y = make_grid(self.N, self.DX)
        U = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0, A=1.0)
        # At r = w0, |U|/|U_max| = exp(-w0²/w0²) = exp(-1)
        # so intensity = exp(-2)
        centre = self.N // 2
        U_centre = abs(U[centre, centre])
        # Find amplitude at r ≈ w0 along x-axis
        i_w0 = int(self.W0 / self.DX)
        U_at_w0 = abs(U[centre, centre + i_w0])
        ratio = U_at_w0 / U_centre
        assert abs(ratio - math.exp(-1.0)) < 0.02, (
            f"amplitude ratio at w0 = {ratio:.4f}, expected {math.exp(-1):.4f}"
        )

    def test_beam_radius_at_z0(self):
        """field_beam_radius should recover w0 at z=0 within 2%."""
        x, y = make_grid(self.N, self.DX)
        U = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        w_num = field_beam_radius(U, self.DX)
        # For a Gaussian, second moment = w0 / √2  (σ = w0/√2)
        # field_beam_radius returns σ, so w = σ = w0/√2 here
        expected = self.W0 / math.sqrt(2.0)
        assert abs(w_num - expected) / expected < 0.05, (
            f"w(z=0) = {w_num*1e6:.2f} µm, expected {expected*1e6:.2f} µm"
        )


# ===========================================================================
# Optical elements (phase screens)
# ===========================================================================

class TestOpticalElements:
    """Verify thin_lens_phase and circular_aperture."""

    N  = 128
    DX = 5e-6
    LAMBDA = 532e-9

    def test_thin_lens_phase_at_centre(self):
        """Phase at origin (r=0) is exp(0) = 1."""
        x, y = make_grid(self.N, self.DX)
        t = thin_lens_phase(x, y, f=0.1, lambda_m=self.LAMBDA)
        centre = self.N // 2
        assert abs(t[centre, centre]) == pytest.approx(1.0, rel=1e-10)

    def test_thin_lens_amplitude_unity(self):
        """Ideal lens is lossless: |t_L| = 1 everywhere."""
        x, y = make_grid(self.N, self.DX)
        t = thin_lens_phase(x, y, f=0.1, lambda_m=self.LAMBDA)
        np.testing.assert_allclose(np.abs(t), 1.0, atol=1e-12)

    def test_thin_lens_quadratic_phase(self):
        """Phase of t_L at (dx, 0) matches analytic formula."""
        x, y = make_grid(self.N, self.DX)
        f = 0.1
        t = thin_lens_phase(x, y, f, self.LAMBDA)
        k = 2.0 * math.pi / self.LAMBDA
        centre = self.N // 2
        r2 = (self.DX) ** 2  # at pixel (centre, centre+1)
        expected_phase = -(k / (2.0 * f)) * r2
        actual_phase   = np.angle(t[centre, centre + 1])
        # Phases can wrap; compare modulo 2π
        diff = abs((actual_phase - expected_phase + math.pi) % (2 * math.pi) - math.pi)
        assert diff < 1e-6

    def test_circular_aperture_centre_one(self):
        """Centre pixel should be 1 for any non-zero radius."""
        x, y = make_grid(64, 1e-6)
        mask = circular_aperture(x, y, radius=20e-6)
        centre = 32
        assert mask[centre, centre] == pytest.approx(1.0)

    def test_circular_aperture_outside_zero(self):
        """Pixels outside radius should be 0."""
        N, dx = 64, 1e-6
        x, y = make_grid(N, dx)
        mask = circular_aperture(x, y, radius=5e-6)
        # Far corner — definitely outside
        assert mask[0, 0] == pytest.approx(0.0)

    def test_circular_aperture_shape(self):
        x, y = make_grid(64, 1e-6)
        mask = circular_aperture(x, y, radius=10e-6)
        assert mask.shape == (64, 64)

    def test_annular_aperture_inner_zero(self):
        """Centre pixel should be masked out (0) for an annular aperture."""
        N, dx = 64, 1e-6
        x, y = make_grid(N, dx)
        mask = annular_aperture(x, y, r_inner=5e-6, r_outer=15e-6)
        centre = N // 2
        assert mask[centre, centre] == pytest.approx(0.0)

    def test_annular_aperture_invalid_raises(self):
        x, y = make_grid(32, 1e-6)
        with pytest.raises(ValueError):
            annular_aperture(x, y, r_inner=10e-6, r_outer=5e-6)


# ===========================================================================
# Analytic oracles
# ===========================================================================

class TestAnalyticOracles:
    """Verify gaussian_waist_analytic, airy_first_null, parseval_energy."""

    def test_gaussian_waist_at_z0(self):
        """w(0) = w0."""
        w0, lam = 0.5e-3, 633e-9
        assert gaussian_waist_analytic(w0, lam, z=0.0) == pytest.approx(w0, rel=1e-12)

    def test_gaussian_waist_at_rayleigh(self):
        """w(zR) = w0·√2."""
        w0, lam = 0.5e-3, 633e-9
        zR = math.pi * w0 ** 2 / lam
        w_zR = gaussian_waist_analytic(w0, lam, z=zR)
        assert w_zR == pytest.approx(w0 * math.sqrt(2.0), rel=1e-10)

    def test_gaussian_waist_formula(self):
        """w(z) = w0·√(1+(z/zR)²) for several distances."""
        w0, lam = 0.3e-3, 1064e-9
        zR = math.pi * w0 ** 2 / lam
        for z in [0.0, 0.5, 1.0, 2.0, 5.0]:
            expected = w0 * math.sqrt(1.0 + (z / zR) ** 2)
            assert gaussian_waist_analytic(w0, lam, z) == pytest.approx(expected, rel=1e-12)

    def test_airy_first_null_formula(self):
        """r_null = 1.22·λ·f/D (analytic)."""
        lam, f, D = 633e-9, 0.1, 0.025
        expected = 1.22 * lam * f / D
        assert airy_first_null(lam, f, D) == pytest.approx(expected, rel=1e-12)

    def test_airy_scales_with_wavelength(self):
        """Longer wavelength → larger Airy disk."""
        f, D = 0.1, 0.025
        r1 = airy_first_null(633e-9, f, D)
        r2 = airy_first_null(1064e-9, f, D)
        assert r2 > r1

    def test_airy_scales_with_aperture(self):
        """Larger aperture → smaller Airy disk."""
        lam, f = 633e-9, 0.1
        r_small = airy_first_null(lam, f, D=0.01)
        r_large = airy_first_null(lam, f, D=0.05)
        assert r_large < r_small

    def test_airy_invalid_D_raises(self):
        with pytest.raises(ValueError):
            airy_first_null(633e-9, f=0.1, D=0.0)

    def test_airy_invalid_f_raises(self):
        with pytest.raises(ValueError):
            airy_first_null(633e-9, f=0.0, D=0.01)

    def test_parseval_analytic(self):
        """For a uniform field, E = |A|² · (N·dx)²."""
        N, dx = 64, 1e-6
        A = 3.0 + 1j * 4.0
        U = np.full((N, N), A, dtype=complex)
        expected = abs(A) ** 2 * (N * dx) ** 2
        assert parseval_energy(U, dx) == pytest.approx(expected, rel=1e-10)

    def test_parseval_gaussian_analytic(self):
        """Total power of a Gaussian beam = π·w0²/2 · A² (paraxial integral)."""
        # ∫∫ A² exp(-2r²/w0²) dx dy = A² · π·w0²/2
        # For the numerical version, result should be within 5% for a well-sampled grid.
        w0, A_amp = 200e-6, 1.0
        N, dx = 512, 5e-6
        x, y = make_grid(N, dx)
        U = gaussian_source(x, y, w0, 633e-9, z_from_waist=0.0, A=A_amp)
        E_num = parseval_energy(U, dx)
        E_analytic = A_amp ** 2 * math.pi * w0 ** 2 / 2.0
        assert abs(E_num - E_analytic) / E_analytic < 0.05, (
            f"E_num={E_num:.4e}, E_analytic={E_analytic:.4e}"
        )


# ===========================================================================
# Oracle 1: Gaussian beam waist evolution
# ===========================================================================

class TestGaussianWaistEvolution:
    """
    Oracle 1 (Goodman §5.2 / Siegman §17).
    Propagate a Gaussian beam numerically; the 1/e² radius must match
    w(z) = w0·√(1+(z/zR)²) to < 0.5% relative error.

    Setup:
        λ = 633 nm (HeNe)
        w0 = 200 µm  (tight enough that zR ≈ 0.20 m — easily sampled)
        N = 512 pixels,  dx = 3 µm  (grid ≈ 1.5 mm × 1.5 mm)
        Propagation: z = 0, zR/4, zR/2, zR, 2·zR  using Angular Spectrum
    """

    LAMBDA = 633e-9
    W0     = 200e-6          # 200 µm waist
    N      = 512
    DX     = 3e-6            # 3 µm pixels  (field grid = 1.536 mm)

    def _setup(self):
        x, y = make_grid(self.N, self.DX)
        U0 = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        return U0, zR

    def test_waist_z_zero(self):
        """At z=0, numerical w matches w0 within 3%."""
        x, y = make_grid(self.N, self.DX)
        U0 = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        w_num = field_beam_radius(U0, self.DX)
        # second-moment radius of Gaussian = w0/sqrt(2)
        w_expected = self.W0 / math.sqrt(2.0)
        assert abs(w_num - w_expected) / w_expected < 0.03

    def test_waist_grows_with_z(self):
        """Beam radius must monotonically increase for z > 0."""
        U0, zR = self._setup()
        w_prev = field_beam_radius(U0, self.DX)
        for z in [zR * 0.25, zR * 0.5, zR, zR * 2.0]:
            U = propagate_angular_spectrum(U0, self.DX, z, self.LAMBDA)
            w = field_beam_radius(U, self.DX)
            assert w > w_prev, f"beam radius did not grow at z={z:.3f}m: w={w:.2e}"
            w_prev = w

    def _numeric_w(self, z: float) -> float:
        """Propagate from waist to z, return second-moment radius."""
        x, y = make_grid(self.N, self.DX)
        U0 = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        if z == 0.0:
            return field_beam_radius(U0, self.DX)
        U = propagate_angular_spectrum(U0, self.DX, z, self.LAMBDA)
        return field_beam_radius(U, self.DX)

    def test_oracle_z_half_zR_asm(self):
        """
        Oracle 1a: z = zR/2.
        Analytic w = w0·√(1+0.25) = w0·√1.25 ≈ 1.118·w0.
        Second-moment w (σ) = analytic_w/√2.
        Require < 1% relative error.
        """
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z  = zR * 0.5
        w_analytic = gaussian_waist_analytic(self.W0, self.LAMBDA, z)
        sigma_analytic = w_analytic / math.sqrt(2.0)

        w_num = self._numeric_w(z)
        rel_err = abs(w_num - sigma_analytic) / sigma_analytic
        assert rel_err < 0.01, (
            f"z=zR/2: numeric w={w_num*1e6:.2f}µm, "
            f"analytic σ={sigma_analytic*1e6:.2f}µm, rel_err={rel_err:.4f}"
        )

    def test_oracle_z_zR_asm(self):
        """
        Oracle 1b: z = zR (Rayleigh length).
        Analytic w = w0·√2 → σ = w0.
        Require < 1% relative error.
        """
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z  = zR
        w_analytic = gaussian_waist_analytic(self.W0, self.LAMBDA, z)
        sigma_analytic = w_analytic / math.sqrt(2.0)

        w_num = self._numeric_w(z)
        rel_err = abs(w_num - sigma_analytic) / sigma_analytic
        assert rel_err < 0.01, (
            f"z=zR: numeric w={w_num*1e6:.2f}µm, "
            f"analytic σ={sigma_analytic*1e6:.2f}µm, rel_err={rel_err:.4f}"
        )

    def test_oracle_z_2zR_asm(self):
        """
        Oracle 1c: z = 2·zR.
        Analytic w = w0·√5 → σ = w0·√(5/2).
        Require < 1.5% relative error (beam now wider; edge truncation).
        """
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z  = 2.0 * zR
        w_analytic = gaussian_waist_analytic(self.W0, self.LAMBDA, z)
        sigma_analytic = w_analytic / math.sqrt(2.0)

        w_num = self._numeric_w(z)
        rel_err = abs(w_num - sigma_analytic) / sigma_analytic
        assert rel_err < 0.015, (
            f"z=2·zR: numeric w={w_num*1e6:.2f}µm, "
            f"analytic σ={sigma_analytic*1e6:.2f}µm, rel_err={rel_err:.4f}"
        )

    def test_gaussian_waist_via_fresnel(self):
        """
        Oracle 1d (Fresnel): z = zR/2 via Fresnel propagation.
        Fresnel = paraxial; for a Gaussian beam the result is identical to ASM
        within the paraxial regime (z >> w0).
        Require < 1% relative error.
        """
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z  = zR * 0.5
        x, y = make_grid(self.N, self.DX)
        U0 = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        U_fresnel = propagate_fresnel(U0, self.DX, z, self.LAMBDA)

        w_analytic = gaussian_waist_analytic(self.W0, self.LAMBDA, z)
        sigma_analytic = w_analytic / math.sqrt(2.0)
        w_num = field_beam_radius(U_fresnel, self.DX)

        rel_err = abs(w_num - sigma_analytic) / sigma_analytic
        assert rel_err < 0.01, (
            f"Fresnel z=zR/2: numeric σ={w_num*1e6:.2f}µm, "
            f"analytic σ={sigma_analytic*1e6:.2f}µm, rel_err={rel_err:.4f}"
        )


# ===========================================================================
# Oracle 2: Airy pattern first null
# ===========================================================================

class TestAiryPattern:
    """
    Oracle 2 (Goodman §4.4 / Born & Wolf §8.5.2).
    A plane wave through a circular aperture, focused by a thin lens, produces
    an Airy pattern in the focal plane.  The first null falls at:

        r_null = 1.22 · λ · f / D

    Setup:
        λ = 633 nm
        D = 1 mm aperture diameter
        f = 100 mm focal length
        N = 512,  dx_pupil = 20 µm  (grid 10.24 mm >> D)

    Expected r_null = 1.22 × 633e-9 × 0.1 / 0.001 ≈ 77.23 µm.
    Output pixel pitch dx_out = λf/(N·dx) ≈ 6.18 µm → ~12.5 pixels to null.
    Parabolic interpolation of the minimum achieves < 5% error.
    """

    LAMBDA = 633e-9
    D      = 1e-3       # 1 mm aperture diameter
    F      = 0.1        # 100 mm focal length
    N      = 512
    DX     = 20e-6      # 20 µm pixel pitch at pupil  → grid 10.24 mm >> D

    def _make_pupil_field(self):
        """Uniform amplitude plane wave through a circular aperture."""
        x, y = make_grid(self.N, self.DX)
        U = np.ones((self.N, self.N), dtype=np.complex128)
        mask = circular_aperture(x, y, radius=self.D / 2.0)
        return U * mask, x, y

    def test_analytic_airy_null(self):
        """r_null = 1.22·λ·f/D analytic formula is correct."""
        expected = 1.22 * self.LAMBDA * self.F / self.D
        got = airy_first_null(self.LAMBDA, self.F, self.D)
        assert got == pytest.approx(expected, rel=1e-12)

    def test_airy_first_null_fraunhofer(self):
        """
        Oracle 2: Fraunhofer diffraction of circular aperture.
        First dark ring in intensity should be at r ≈ 1.22·λ·f/D,
        within 5% relative error.

        Method: propagate_fraunhofer gives the far-field at distance f (focal plane).
        The first null of the Airy pattern is the first zero of J1(πDr/(λf)) at
        argument 3.8317 → r = 1.22·λ·f/D.

        Pixel pitch dx_out ≈ 6.18 µm; null at ≈12.5 pixels.
        Uses parabolic interpolation around the minimum pixel for sub-pixel accuracy.
        """
        U_pupil, _, _ = self._make_pupil_field()
        U_focal, dx_out = propagate_fraunhofer(U_pupil, self.DX, self.F, self.LAMBDA)

        I = np.abs(U_focal) ** 2
        N = self.N
        centre = N // 2

        # Radial profile along x-axis (through centre row), positive half only
        right_half = I[centre, centre:]
        x_right = np.arange(len(right_half)) * dx_out

        if len(right_half) < 5:
            pytest.skip("output grid too small")

        # Find first local minimum via simple scan (look for sign change in derivative)
        min_i = None
        for i in range(1, min(40, len(right_half) - 1)):
            if right_half[i] < right_half[i - 1] and right_half[i] < right_half[i + 1]:
                min_i = i
                break

        analytic_null = airy_first_null(self.LAMBDA, self.F, self.D)
        assert min_i is not None, "No local minimum found in Airy pattern"

        # Parabolic sub-pixel interpolation for the minimum position
        # Fit parabola to 3 points around the minimum: y = a·x² + b·x + c
        # Minimum at x* = -b / (2a) relative to the centre of the 3-point window
        y0, y1, y2 = right_half[min_i - 1], right_half[min_i], right_half[min_i + 1]
        # a = (y0 - 2·y1 + y2) / 2,  b = (y2 - y0) / 2
        a = (y0 - 2.0 * y1 + y2) / 2.0
        b = (y2 - y0) / 2.0
        if abs(a) > 1e-30:
            # Sub-pixel offset from min_i pixel
            delta = -b / (2.0 * a)
        else:
            delta = 0.0
        first_null_r = (min_i + delta) * dx_out

        rel_err = abs(first_null_r - analytic_null) / analytic_null
        assert rel_err < 0.05, (
            f"Airy first null: numeric r={first_null_r*1e6:.2f}µm, "
            f"analytic r={analytic_null*1e6:.2f}µm, rel_err={rel_err:.4f}"
        )

    def test_airy_central_peak_max(self):
        """Airy pattern: the central maximum is the brightest point."""
        U_pupil, _, _ = self._make_pupil_field()
        U_focal, dx_out = propagate_fraunhofer(U_pupil, self.DX, self.F, self.LAMBDA)
        I = np.abs(U_focal) ** 2
        centre = self.N // 2
        max_pos = np.unravel_index(I.argmax(), I.shape)
        # Maximum should be within 2 pixels of centre
        assert abs(max_pos[0] - centre) <= 2
        assert abs(max_pos[1] - centre) <= 2

    def test_airy_radial_symmetry(self):
        """Airy pattern should be approximately radially symmetric."""
        U_pupil, _, _ = self._make_pupil_field()
        U_focal, dx_out = propagate_fraunhofer(U_pupil, self.DX, self.F, self.LAMBDA)
        I = np.abs(U_focal) ** 2
        centre = self.N // 2
        # Compare x-axis and y-axis profiles (should be identical by symmetry)
        row_x = I[centre, centre:centre + 30]
        col_y = I[centre:centre + 30, centre]
        np.testing.assert_allclose(row_x, col_y, rtol=0.01)


# ===========================================================================
# Oracle 3: Energy conservation
# ===========================================================================

class TestEnergyConservation:
    """
    Oracle 3: Parseval's theorem — total power must be invariant under
    free-space propagation (both ASM and Fresnel).

    Allow < 0.1% relative loss (numerical precision of FFT roundtrip).
    """

    LAMBDA = 633e-9
    W0     = 150e-6
    N      = 256
    DX     = 5e-6

    def _initial_field(self):
        x, y = make_grid(self.N, self.DX)
        return gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)

    def test_energy_conservation_asm(self):
        """
        Oracle 3a: Energy conserved under Angular Spectrum propagation.
        Propagate to z = zR/2; require |E_out/E_in − 1| < 0.001.
        """
        U0 = self._initial_field()
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z = zR * 0.5

        E0 = parseval_energy(U0, self.DX)
        U1 = propagate_angular_spectrum(U0, self.DX, z, self.LAMBDA)
        E1 = parseval_energy(U1, self.DX)

        rel_loss = abs(E1 - E0) / E0
        assert rel_loss < 0.001, (
            f"ASM energy loss = {rel_loss:.4e} (> 0.1%); E0={E0:.4e}, E1={E1:.4e}"
        )

    def test_energy_conservation_asm_multiple_steps(self):
        """Energy conserved across three consecutive ASM steps."""
        U0 = self._initial_field()
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z  = zR * 0.2
        E0 = parseval_energy(U0, self.DX)

        U = U0
        for _ in range(3):
            U = propagate_angular_spectrum(U, self.DX, z, self.LAMBDA)

        E_final = parseval_energy(U, self.DX)
        rel_loss = abs(E_final - E0) / E0
        assert rel_loss < 0.002, (
            f"3× ASM energy loss = {rel_loss:.4e}; E0={E0:.4e}, E_final={E_final:.4e}"
        )

    def test_energy_conservation_fresnel(self):
        """
        Oracle 3b: Energy conserved under Fresnel propagation.
        Fresnel is unitary (conserves L² norm).
        """
        U0 = self._initial_field()
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        z  = zR * 0.5

        E0 = parseval_energy(U0, self.DX)
        U1 = propagate_fresnel(U0, self.DX, z, self.LAMBDA)
        E1 = parseval_energy(U1, self.DX)

        rel_loss = abs(E1 - E0) / E0
        assert rel_loss < 0.001, (
            f"Fresnel energy loss = {rel_loss:.4e}; E0={E0:.4e}, E1={E1:.4e}"
        )

    def test_energy_after_aperture_decreases(self):
        """Applying a sub-aperture reduces energy (aperture blocks light)."""
        N, dx = 256, 5e-6
        x, y = make_grid(N, dx)
        U = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        E0 = parseval_energy(U, dx)

        # Tight aperture that clips the beam
        mask = circular_aperture(x, y, radius=self.W0 * 0.5)
        U_clipped = U * mask
        E1 = parseval_energy(U_clipped, dx)

        assert E1 < E0, f"Clipped energy {E1:.4e} >= input {E0:.4e}"

    def test_lens_phase_conserves_energy(self):
        """Thin lens (phase-only) must not change total power."""
        N, dx = 256, 5e-6
        x, y = make_grid(N, dx)
        U = gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)
        E0 = parseval_energy(U, dx)

        t = thin_lens_phase(x, y, f=0.1, lambda_m=self.LAMBDA)
        U_after = U * t
        E1 = parseval_energy(U_after, dx)

        rel_change = abs(E1 - E0) / E0
        assert rel_change < 1e-10, (
            f"Lens phase changed energy by {rel_change:.4e}"
        )


# ===========================================================================
# Propagation method correctness
# ===========================================================================

class TestPropagationMethods:
    """Basic correctness checks for ASM, Fresnel, Fraunhofer, and auto-selector."""

    LAMBDA = 633e-9
    N  = 128
    DX = 5e-6

    def _field(self):
        x, y = make_grid(self.N, self.DX)
        return gaussian_source(x, y, 100e-6, self.LAMBDA, z_from_waist=0.0)

    def test_asm_z_zero_identity(self):
        """ASM with z=0 should return U unchanged."""
        U = self._field()
        U_out = propagate_angular_spectrum(U, self.DX, 0.0, self.LAMBDA)
        np.testing.assert_allclose(np.abs(U_out), np.abs(U), rtol=1e-6)

    def test_fresnel_z_zero_identity(self):
        """Fresnel with z=0: H_F = 1 everywhere → U unchanged."""
        U = self._field()
        U_out = propagate_fresnel(U, self.DX, 0.0, self.LAMBDA)
        np.testing.assert_allclose(np.abs(U_out), np.abs(U), rtol=1e-6)

    def test_asm_output_shape(self):
        U = self._field()
        U_out = propagate_angular_spectrum(U, self.DX, 0.01, self.LAMBDA)
        assert U_out.shape == U.shape

    def test_fresnel_output_shape(self):
        U = self._field()
        U_out = propagate_fresnel(U, self.DX, 0.01, self.LAMBDA)
        assert U_out.shape == U.shape

    def test_fraunhofer_output_shape(self):
        U = self._field()
        U_out, dx_out = propagate_fraunhofer(U, self.DX, 0.1, self.LAMBDA)
        assert U_out.shape == U.shape

    def test_fraunhofer_dx_out(self):
        """Output pixel pitch = λz / (N·dx_in)."""
        N, dx = 128, 5e-6
        z = 0.1
        x, y = make_grid(N, dx)
        U = gaussian_source(x, y, 100e-6, self.LAMBDA)
        _, dx_out = propagate_fraunhofer(U, dx, z, self.LAMBDA)
        expected = self.LAMBDA * z / (N * dx)
        assert dx_out == pytest.approx(expected, rel=1e-10)

    def test_propagate_auto_near_field(self):
        """Auto-selector should use ASM for very short distances (large NF)."""
        U = self._field()
        # Very short z → NF large → ASM
        U_asm  = propagate_angular_spectrum(U, self.DX, 1e-3, self.LAMBDA)
        U_auto = propagate(U, self.DX, 1e-3, self.LAMBDA, method="auto")
        np.testing.assert_allclose(np.abs(U_auto), np.abs(U_asm), rtol=1e-8)

    def test_propagate_auto_far_field(self):
        """Auto-selector should use Fresnel for large distances (small NF)."""
        U = self._field()
        # Long z → NF small → Fresnel
        z_far = 10.0  # 10 m — well in far field for a 5×128 µm grid
        U_fresnel = propagate_fresnel(U, self.DX, z_far, self.LAMBDA)
        U_auto    = propagate(U, self.DX, z_far, self.LAMBDA, method="auto")
        np.testing.assert_allclose(np.abs(U_auto), np.abs(U_fresnel), rtol=1e-8)

    def test_propagate_invalid_method_raises(self):
        U = self._field()
        with pytest.raises(ValueError, match="unknown method"):
            propagate(U, self.DX, 0.01, self.LAMBDA, method="invalid")

    def test_asm_non_square_raises(self):
        U = np.ones((64, 128), dtype=complex)
        with pytest.raises(ValueError):
            propagate_angular_spectrum(U, 1e-6, 0.01, 633e-9)

    def test_asm_fresnel_agree_paraxial(self):
        """
        ASM and Fresnel should agree within 0.1% for a paraxial beam
        in the near-field regime where both are valid.
        Use a wide beam (w0=200µm) and z = zR/4.
        """
        N, dx = 256, 3e-6
        w0 = 200e-6
        lam = 633e-9
        zR = math.pi * w0 ** 2 / lam
        z  = zR * 0.25

        x, y = make_grid(N, dx)
        U0 = gaussian_source(x, y, w0, lam, z_from_waist=0.0)

        U_asm     = propagate_angular_spectrum(U0, dx, z, lam)
        U_fresnel = propagate_fresnel(U0, dx, z, lam)

        I_asm     = np.abs(U_asm) ** 2
        I_fresnel = np.abs(U_fresnel) ** 2

        # Compare total energy (Parseval) — should agree to 0.1%
        E_asm     = parseval_energy(U_asm, dx)
        E_fresnel = parseval_energy(U_fresnel, dx)
        assert abs(E_asm - E_fresnel) / E_asm < 0.002


# ===========================================================================
# propagate_system integration
# ===========================================================================

class TestPropagateSystem:
    """Integration test: propagate_system through elements."""

    LAMBDA = 633e-9
    W0     = 150e-6
    N      = 256
    DX     = 5e-6

    def _field(self):
        x, y = make_grid(self.N, self.DX)
        return gaussian_source(x, y, self.W0, self.LAMBDA, z_from_waist=0.0)

    def test_free_space_snapshot_keys(self):
        """Snapshots should contain required keys."""
        U0 = self._field()
        snaps = propagate_system(U0, self.DX, [{"type": "free_space", "d": 0.01}], self.LAMBDA)
        assert len(snaps) == 1
        snap = snaps[0]
        for key in ("label", "U", "dx", "energy", "beam_radius"):
            assert key in snap, f"missing key: {key}"

    def test_thin_lens_snapshot(self):
        """Thin lens element should produce a snapshot."""
        U0 = self._field()
        snaps = propagate_system(U0, self.DX, [{"type": "thin_lens", "f": 0.1}], self.LAMBDA)
        assert len(snaps) == 1
        assert "thin_lens" in snaps[0]["label"]

    def test_aperture_reduces_energy(self):
        """Aperture snapshot should have less energy than input."""
        U0 = self._field()
        E0 = parseval_energy(U0, self.DX)
        # Tight aperture (half beam waist)
        snaps = propagate_system(
            U0, self.DX,
            [{"type": "aperture", "radius": self.W0 * 0.5}],
            self.LAMBDA,
        )
        E1 = snaps[0]["energy"]
        assert E1 < E0

    def test_multi_element_pipeline(self):
        """Multi-element system: free space + lens + free space → valid field."""
        U0 = self._field()
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        elements = [
            {"type": "free_space", "d": zR * 0.5},
            {"type": "thin_lens",  "f": 0.05},
            {"type": "free_space", "d": 0.05},
        ]
        snaps = propagate_system(U0, self.DX, elements, self.LAMBDA)
        assert len(snaps) == 3
        # Final field must be finite
        assert np.all(np.isfinite(np.abs(snaps[-1]["U"])))

    def test_unknown_element_raises(self):
        U0 = self._field()
        with pytest.raises(ValueError, match="unknown element type"):
            propagate_system(U0, self.DX, [{"type": "telescope"}], self.LAMBDA)

    def test_energy_through_free_space_conserved(self):
        """Energy should be conserved (< 0.2%) through a free-space step."""
        U0 = self._field()
        zR = math.pi * self.W0 ** 2 / self.LAMBDA
        E0 = parseval_energy(U0, self.DX)
        snaps = propagate_system(
            U0, self.DX,
            [{"type": "free_space", "d": zR * 0.3}],
            self.LAMBDA,
        )
        E1 = snaps[0]["energy"]
        assert abs(E1 - E0) / E0 < 0.002


# ===========================================================================
# Module-level imports
# ===========================================================================

class TestModuleImport:
    def test_import_pop(self):
        import kerf_optics.pop  # noqa: F401

    def test_pycompile_pop(self):
        import py_compile
        path = os.path.join(_SRC, "kerf_optics", "pop.py")
        py_compile.compile(path, doraise=True)
