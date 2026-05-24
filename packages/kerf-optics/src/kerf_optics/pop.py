"""
kerf_optics.pop — Physical-Optics Propagation (POP) / Beam Propagation Method (BPM).

Implements scalar-wave diffraction propagation of a complex monochromatic wavefront
U(x, y) using two complementary methods:

  1. Angular Spectrum Method (ASM) — Goodman "Introduction to Fourier Optics" §3.10
     Exact within the scalar-wave approximation. No paraxial requirement. Best for
     near-field / short propagation distances.

  2. Fresnel / Fraunhofer — Goodman §4.2–4.3
     Paraxial (Fresnel) or far-field (Fraunhofer) approximations.
     Fraunhofer uses a single FFT; Fresnel uses the convolution or transfer-function form.

Optical elements (thin):
  * gaussian_source    — TEM₀₀ Gaussian beam, real or complex-curved wavefront
  * thin_lens_phase    — multiply by exp(−iπ(x²+y²)/(λf))  (quadratic phase)
  * circular_aperture  — hard-edge circ(r/R) mask

Validation oracles (closed-form):
  * gaussian_waist_analytic(z)  →  w(z) = w0·√(1+(z/zR)²)
  * airy_first_null(lam_m, f, D)  →  r_null = 1.22·λ·f/D
  * parseval_energy(U, dx)  →  ∫|U|² dA  (should be invariant under propagation)

References
----------
- Goodman, J.W., "Introduction to Fourier Optics", 3rd ed. (Roberts, 2005):
    §3.7  Transfer function of free space (angular spectrum)
    §4.2  The Fresnel approximation
    §4.3  The Fraunhofer approximation
- Born & Wolf, "Principles of Optics", 7th ed., §8.8 (Fraunhofer diffraction)
- Siegman, "Lasers", §17  (Gaussian beam, q-parameter)
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------

def make_grid(
    N: int,
    dx: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (x, y) coordinate grids for an N×N array with pixel pitch dx.

    The grid is centred at zero: coordinates run from −(N/2)·dx to +(N/2−1)·dx.

    Parameters
    ----------
    N  : number of pixels per side (should be a power of 2 for FFT efficiency)
    dx : pixel pitch (metres)

    Returns
    -------
    x, y : 2-D meshgrids of shape (N, N), dtype float64
    """
    coords = (np.arange(N) - N // 2) * dx
    x, y = np.meshgrid(coords, coords, indexing="xy")
    return x, y


def make_freq_grid(
    N: int,
    dx: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (fx, fy) spatial-frequency grids for an N×N FFT.

    The frequency grid matches np.fft.fftfreq, then is fftshifted to centre
    DC at (N//2, N//2).

    Parameters
    ----------
    N  : array size (pixels per side)
    dx : spatial-domain pixel pitch (metres)

    Returns
    -------
    fx, fy : 2-D meshgrids in cycles/metre (1/m)
    """
    df = 1.0 / (N * dx)
    freqs = np.fft.fftshift(np.fft.fftfreq(N)) / dx
    fx, fy = np.meshgrid(freqs, freqs, indexing="xy")
    return fx, fy


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def gaussian_source(
    x: np.ndarray,
    y: np.ndarray,
    w0: float,
    lambda_m: float,
    z_from_waist: float = 0.0,
    A: float = 1.0,
) -> np.ndarray:
    """Generate a TEM₀₀ Gaussian beam field at a transverse plane.

    The complex field at distance z from the waist is (Siegman §17, Goodman §5.2):

        U(x, y; z) = A · (w0/w(z))
                     · exp(−r²/w(z)²)
                     · exp(−i·k·r²/(2·R(z)))
                     · exp(i·k·z − i·ζ(z))

    where
        r²    = x² + y²
        k     = 2π/λ
        zR    = π·w0²/λ   (Rayleigh length)
        w(z)  = w0·√(1+(z/zR)²)
        R(z)  = z·(1+(zR/z)²)  (∞ at z=0)
        ζ(z)  = arctan(z/zR)   (Gouy phase)

    The global propagation phase exp(i·k·z) is dropped (it is a uniform piston
    that cancels in intensity); the Gouy phase is included.

    Parameters
    ----------
    x, y          : coordinate grids (m), shape (N, N)
    w0            : beam waist radius (1/e² field) in metres
    lambda_m      : vacuum wavelength in metres
    z_from_waist  : distance from the waist (m); 0 = at waist
    A             : field amplitude (default 1)

    Returns
    -------
    U : complex64 ndarray of shape (N, N) — the field amplitude
    """
    k = 2.0 * math.pi / lambda_m
    zR = math.pi * w0 ** 2 / lambda_m
    r2 = x * x + y * y

    if abs(z_from_waist) < 1e-30:
        # At the waist: pure Gaussian, no wavefront curvature, no Gouy
        U = A * np.exp(-r2 / w0 ** 2).astype(np.complex128)
    else:
        z = z_from_waist
        w_z = w0 * math.sqrt(1.0 + (z / zR) ** 2)
        R_z = z * (1.0 + (zR / z) ** 2)
        gouy = math.atan2(z, zR)          # ζ(z) = arctan(z/zR)

        # Amplitude envelope (1/e² in field → 1/e⁴ in intensity)
        amp = A * (w0 / w_z) * np.exp(-r2 / w_z ** 2)
        # Quadratic wavefront phase (converging or diverging)
        phase = -k * r2 / (2.0 * R_z) - gouy
        U = (amp * np.exp(1j * phase)).astype(np.complex128)

    return U


# ---------------------------------------------------------------------------
# Optical elements (phase screens)
# ---------------------------------------------------------------------------

def thin_lens_phase(
    x: np.ndarray,
    y: np.ndarray,
    f: float,
    lambda_m: float,
) -> np.ndarray:
    """Quadratic phase factor for a thin ideal lens of focal length f.

    A positive thin lens applies the phase (Goodman §5.2, eq. 5-8):

        t_L(x, y) = exp(−i·π·(x²+y²) / (λ·f))

    Multiplying the incoming field U by t_L transforms a plane wave into a
    converging spherical wave focused at distance f.

    Parameters
    ----------
    x, y     : coordinate grids (m)
    f        : focal length (m); positive = converging
    lambda_m : vacuum wavelength (m)

    Returns
    -------
    t_L : complex128 ndarray matching x/y shape
    """
    k = 2.0 * math.pi / lambda_m
    r2 = x * x + y * y
    return np.exp(-1j * (k / (2.0 * f)) * r2)


def circular_aperture(
    x: np.ndarray,
    y: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Hard-edge circular aperture mask: 1 inside radius, 0 outside.

    Parameters
    ----------
    x, y   : coordinate grids (m)
    radius : aperture radius (m)

    Returns
    -------
    mask : float64 ndarray, values in {0.0, 1.0}
    """
    r = np.sqrt(x * x + y * y)
    return (r <= radius).astype(np.float64)


def annular_aperture(
    x: np.ndarray,
    y: np.ndarray,
    r_inner: float,
    r_outer: float,
) -> np.ndarray:
    """Annular (ring) aperture: 1 inside [r_inner, r_outer], 0 elsewhere.

    Parameters
    ----------
    x, y    : coordinate grids (m)
    r_inner : inner radius (m)
    r_outer : outer radius (m)

    Returns
    -------
    mask : float64 ndarray
    """
    if r_inner < 0 or r_outer <= r_inner:
        raise ValueError(
            f"require 0 <= r_inner < r_outer; got r_inner={r_inner}, r_outer={r_outer}"
        )
    r = np.sqrt(x * x + y * y)
    return ((r >= r_inner) & (r <= r_outer)).astype(np.float64)


# ---------------------------------------------------------------------------
# Angular Spectrum Method  (Goodman §3.10)
# ---------------------------------------------------------------------------

def propagate_angular_spectrum(
    U_in: np.ndarray,
    dx: float,
    z: float,
    lambda_m: float,
    evanescent_cutoff: bool = True,
) -> np.ndarray:
    """Propagate a complex field U_in by distance z via the Angular Spectrum Method.

    The angular spectrum transfer function (Goodman eq. 3-68) is:

        H(fx, fy) = exp(i·k·z·√(1 − (λ·fx)² − (λ·fy)²))
                    for  (λ·fx)² + (λ·fy)² ≤ 1  (propagating waves)
                    = 0  otherwise (evanescent waves suppressed)

    This is the exact scalar-wave free-space propagator — no paraxial approximation.
    It is equivalent to the Rayleigh-Sommerfeld diffraction integral for scalar fields.

    Algorithm:
        1. FFT(U_in) → A(fx, fy)          [angular spectrum]
        2. multiply by H(fx, fy)           [phase-shift per plane wave]
        3. IFFT → U_out                    [output field]

    Parameters
    ----------
    U_in            : input complex field, shape (N, N)
    dx              : spatial pixel pitch (m)
    z               : propagation distance (m); positive = forward
    lambda_m        : vacuum wavelength (m)
    evanescent_cutoff : if True, zero out evanescent components (|λf| > 1)

    Returns
    -------
    U_out : propagated complex field, shape (N, N), dtype complex128

    Notes
    -----
    For numerical accuracy, the field should be zero-padded if U_in has
    significant amplitude near the edges (wrap-around artefact).
    The pixel pitch dx determines the maximum spatial frequency 1/(2·dx).
    For propagating waves to be correctly sampled, require dx < λ/2 at minimum;
    in practice dx ≈ λ/4 or smaller is preferred for narrow-angle beams.

    Reference: Goodman §3.10, eq. 3-68 and 3-69.
    """
    N = U_in.shape[0]
    if U_in.shape[1] != N:
        raise ValueError(f"U_in must be square; got shape {U_in.shape}")

    k = 2.0 * math.pi / lambda_m
    fx, fy = make_freq_grid(N, dx)

    # Compute (λ·f)² for the evanescent test
    lf2 = (lambda_m * fx) ** 2 + (lambda_m * fy) ** 2

    # Transfer function H(fx, fy)
    # For propagating components: sqrt argument is positive
    prop_mask = lf2 <= 1.0
    kz = np.where(prop_mask, np.sqrt(np.maximum(1.0 - lf2, 0.0)) * k, 0.0)
    H = np.where(prop_mask, np.exp(1j * kz * z), 0.0)

    # Angular spectrum propagation: IFFT(FFT(U) · H)
    # Use fftshift / ifftshift to align frequency-domain with make_freq_grid convention
    A = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(U_in)))
    A_propagated = A * H
    U_out = np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(A_propagated)))

    return U_out.astype(np.complex128)


# ---------------------------------------------------------------------------
# Fresnel propagation  (Goodman §4.2)
# ---------------------------------------------------------------------------

def propagate_fresnel(
    U_in: np.ndarray,
    dx: float,
    z: float,
    lambda_m: float,
) -> np.ndarray:
    """Propagate a complex field by distance z using the Fresnel approximation.

    The Fresnel approximation (Goodman §4.2, eq. 4-17) gives the diffracted
    field as a convolution with the Fresnel impulse response:

        h(x, y; z) = (exp(ikz) / iλz) · exp(iπ(x²+y²)/(λz))

    Equivalently, using the transfer function form (eq. 4-20):

        H_F(fx, fy) = exp(ikz) · exp(−iπλz(fx²+fy²))

    This is the paraxial limit of the angular spectrum transfer function,
    valid when z >> (x² + y²)^(3/2) / λ (Fresnel number criterion).

    Implementation uses the transfer-function (spectrum-domain) form:
        U_out = IFFT( FFT(U_in) · H_F )

    Parameters
    ----------
    U_in     : input complex field, shape (N, N)
    dx       : spatial pixel pitch (m)
    z        : propagation distance (m)
    lambda_m : vacuum wavelength (m)

    Returns
    -------
    U_out : propagated field, shape (N, N), complex128

    Reference: Goodman §4.2, eq. 4-20.
    """
    N = U_in.shape[0]
    k = 2.0 * math.pi / lambda_m
    fx, fy = make_freq_grid(N, dx)

    # Fresnel transfer function (dropping the global phase exp(ikz))
    H_F = np.exp(-1j * math.pi * lambda_m * z * (fx ** 2 + fy ** 2))

    A = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(U_in)))
    U_out = np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(A * H_F)))

    return U_out.astype(np.complex128)


# ---------------------------------------------------------------------------
# Fraunhofer propagation  (Goodman §4.3)
# ---------------------------------------------------------------------------

def propagate_fraunhofer(
    U_in: np.ndarray,
    dx: float,
    z: float,
    lambda_m: float,
) -> tuple[np.ndarray, float]:
    """Compute the Fraunhofer (far-field) diffraction pattern.

    The Fraunhofer approximation (Goodman §4.3, eq. 4-25) gives:

        U_out(x, y) = (exp(ikz)·exp(iπr²/(λz))) / (iλz)
                      · ∫∫ U_in(ξ, η) · exp(−i2π(ξx + ηy)/(λz)) dξ dη

    The output is (up to a quadratic phase factor) the Fourier transform of U_in,
    evaluated at spatial frequencies fx = x/(λz), fy = y/(λz).

    The output grid has pixel pitch  dx_out = λz / (N·dx_in).

    Parameters
    ----------
    U_in     : input complex field, shape (N, N), at pupil plane
    dx       : input pixel pitch (m)
    z        : propagation distance (m)
    lambda_m : vacuum wavelength (m)

    Returns
    -------
    U_out   : Fraunhofer field, shape (N, N), complex128
              Includes the (1/(iλz))·exp(iπr²/(λz)) phase prefactor so that
              |U_out|² is the correct intensity distribution at the observation plane.
    dx_out  : output pixel pitch (m) = λz/(N·dx)

    Notes
    -----
    The Fraunhofer approximation is valid when the Fresnel number
        NF = a²/(λz)  << 1,   where a = half-aperture size = (N/2)·dx.
    For a circular aperture of diameter D and focal length f, the first Airy
    null falls at  r_null = 1.22·λ·f/D  (Goodman §4.4, eq. 4-33).

    Reference: Goodman §4.3, eq. 4-25.
    """
    N = U_in.shape[0]
    k = 2.0 * math.pi / lambda_m

    # Output pixel pitch from the Fourier-scaling relation (Goodman §4.3)
    dx_out = lambda_m * z / (N * dx)

    # Output coordinate grids (centred)
    x_out_1d = (np.arange(N) - N // 2) * dx_out
    x_out, y_out = np.meshgrid(x_out_1d, x_out_1d, indexing="xy")
    r2_out = x_out ** 2 + y_out ** 2

    # The Fourier transform of U_in (evaluated at fx = x/(λz), fy = y/(λz))
    # via FFT with fftshift alignment
    FT = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(U_in))) * (dx ** 2)

    # Fraunhofer prefactor: (1/(iλz)) · exp(iπr²/(λz))
    # The (1/(iλz)) sets the amplitude normalisation; exp(iπr²/(λz)) is the
    # quadratic phase of the observation plane.
    prefactor = (1.0 / (1j * lambda_m * z)) * np.exp(1j * math.pi * r2_out / (lambda_m * z))
    U_out = prefactor * FT

    return U_out.astype(np.complex128), float(dx_out)


# ---------------------------------------------------------------------------
# Auto-selector: ASM for near-field, Fresnel for far-field
# ---------------------------------------------------------------------------

def propagate(
    U_in: np.ndarray,
    dx: float,
    z: float,
    lambda_m: float,
    method: str = "auto",
) -> np.ndarray:
    """Propagate U_in by distance z, choosing the best method automatically.

    Method selection (when method='auto'):
        * z == 0  → return U_in unchanged
        * Fresnel number NF = (N·dx/2)² / (λ·z) > 10  → Angular Spectrum (near-field)
        * NF ≤ 10  → Fresnel transfer function (paraxial, far-field)

    The transition criterion keeps the sampling adequate in both regimes.

    Parameters
    ----------
    U_in     : input field, shape (N, N), complex
    dx       : pixel pitch (m)
    z        : propagation distance (m)
    lambda_m : vacuum wavelength (m)
    method   : 'auto' | 'asm' | 'fresnel'

    Returns
    -------
    U_out : propagated field, shape (N, N), complex128
    """
    if z == 0.0:
        return U_in.astype(np.complex128)

    N = U_in.shape[0]
    half_aperture = (N * dx) / 2.0
    NF = half_aperture ** 2 / (lambda_m * abs(z))

    if method == "auto":
        method = "asm" if NF > 10.0 else "fresnel"

    if method == "asm":
        return propagate_angular_spectrum(U_in, dx, z, lambda_m)
    elif method == "fresnel":
        return propagate_fresnel(U_in, dx, z, lambda_m)
    else:
        raise ValueError(f"unknown method: {method!r}; choose 'auto', 'asm', or 'fresnel'")


# ---------------------------------------------------------------------------
# Analytic validation oracles
# ---------------------------------------------------------------------------

def gaussian_waist_analytic(
    w0: float,
    lambda_m: float,
    z: float,
    n: float = 1.0,
) -> float:
    """Analytic Gaussian beam waist at distance z from the waist.

    w(z) = w0 · √(1 + (z/zR)²),   zR = π·n·w0²/λ

    Parameters
    ----------
    w0       : beam waist radius (m)
    lambda_m : vacuum wavelength (m)
    z        : distance from waist (m)
    n        : refractive index (default 1.0)

    Returns
    -------
    w : beam radius at z (m)
    """
    zR = math.pi * n * w0 ** 2 / lambda_m
    return w0 * math.sqrt(1.0 + (z / zR) ** 2)


def airy_first_null(
    lambda_m: float,
    f: float,
    D: float,
) -> float:
    """Radius of the first dark ring (Airy disk) for a circular aperture.

    For a plane wave of wavelength λ focused by a lens of focal length f and
    diameter D, the first Airy null falls at:

        r_null = 1.22 · λ · f / D

    (Goodman §4.4, eq. 4-33; Born & Wolf §8.5.2)

    Parameters
    ----------
    lambda_m : wavelength (m)
    f        : focal length (m)
    D        : aperture diameter (m)

    Returns
    -------
    r_null : first Airy null radius (m)
    """
    if D <= 0:
        raise ValueError(f"aperture diameter D must be > 0; got {D}")
    if f <= 0:
        raise ValueError(f"focal length f must be > 0; got {f}")
    return 1.22 * lambda_m * f / D


def parseval_energy(
    U: np.ndarray,
    dx: float,
) -> float:
    """Total integrated power (energy) of a complex field U on a grid with pitch dx.

    Parseval's theorem guarantees that the power is conserved under free-space
    propagation (unitary transformation).

    E = Σ |U(x,y)|² · dx²  ≈  ∫∫ |U(x,y)|² dx dy

    Parameters
    ----------
    U  : complex field array, shape (N, M)
    dx : pixel pitch (m) — assumed equal in x and y

    Returns
    -------
    E : total power (W·m² / (W/m²) = dimensionless if U is normalised to √W/m)
    """
    return float(np.sum(np.abs(U) ** 2) * dx ** 2)


# ---------------------------------------------------------------------------
# Beam radius from field (numerical w(z) estimator)
# ---------------------------------------------------------------------------

def field_beam_radius(
    U: np.ndarray,
    dx: float,
) -> float:
    """Estimate the 1/e² field radius of U from the second-moment width (D4σ / 4).

    Uses the ISO 11146 definition: w = 2·σ  where σ² is the second spatial moment
    of the intensity distribution:

        σ² = ∫∫ r² · |U|² dA / ∫∫ |U|² dA

    For a Gaussian, this gives exactly the 1/e² field radius.

    Parameters
    ----------
    U  : complex field, shape (N, N)
    dx : pixel pitch (m)

    Returns
    -------
    w : 1/e² field radius (m)
    """
    N = U.shape[0]
    x_1d = (np.arange(N) - N // 2) * dx
    x, y = np.meshgrid(x_1d, x_1d, indexing="xy")
    r2 = x * x + y * y

    I = np.abs(U) ** 2
    I_total = np.sum(I)
    if I_total < 1e-30:
        return 0.0

    sigma2 = np.sum(r2 * I) / I_total
    return float(math.sqrt(sigma2))   # σ = 1/e² radius for Gaussian


# ---------------------------------------------------------------------------
# Convenience: propagate through a sequence of elements
# ---------------------------------------------------------------------------

def propagate_system(
    U_in: np.ndarray,
    dx: float,
    elements: list[dict],
    lambda_m: float,
) -> list[dict]:
    """Propagate a field through a sequence of optical elements and spaces.

    Each element is a dict with key 'type' and type-specific parameters:

        {'type': 'free_space',  'd': <metres>}
        {'type': 'free_space',  'd': <metres>, 'method': 'asm'|'fresnel'}
        {'type': 'thin_lens',   'f': <metres>}
        {'type': 'aperture',    'radius': <metres>}

    Returns a list of snapshot dicts — one for each element — each containing:
        'label'     : str description
        'U'         : complex field after this element, shape (N, N)
        'dx'        : pixel pitch (unchanged unless Fraunhofer scaling used)
        'energy'    : total power (Parseval integral)
        'beam_radius': estimated 1/e² field radius (m)

    Parameters
    ----------
    U_in     : input field, shape (N, N), complex
    dx       : pixel pitch (m)
    elements : list of element dicts
    lambda_m : vacuum wavelength (m)

    Returns
    -------
    snapshots : list of dicts (one per element + final state)
    """
    U = U_in.astype(np.complex128)
    x, y = make_grid(U.shape[0], dx)

    snapshots = []

    for elem in elements:
        etype = elem["type"]

        if etype == "free_space":
            d = float(elem["d"])
            method = elem.get("method", "auto")
            U = propagate(U, dx, d, lambda_m, method=method)
            label = f"free_space(d={d:.4g}m)"

        elif etype == "thin_lens":
            f = float(elem["f"])
            U = U * thin_lens_phase(x, y, f, lambda_m)
            label = f"thin_lens(f={f:.4g}m)"

        elif etype == "aperture":
            radius = float(elem["radius"])
            mask = circular_aperture(x, y, radius)
            U = U * mask
            label = f"aperture(r={radius:.4g}m)"

        else:
            raise ValueError(f"unknown element type: {etype!r}")

        snapshots.append({
            "label": label,
            "U": U.copy(),
            "dx": dx,
            "energy": parseval_energy(U, dx),
            "beam_radius": field_beam_radius(U, dx),
        })

    return snapshots
