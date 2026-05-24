"""
Gaussian beam propagation — complex beam parameter (q-parameter) formalism.

Convention
----------
The complex beam parameter q at a cross-section satisfies:

    1/q = 1/R − i·λ/(π·n·w²)

where
    R  = wavefront radius of curvature (positive = diverging, ∞ at waist)
    w  = beam radius at 1/e² intensity (field radius)
    n  = refractive index of the medium
    λ  = vacuum wavelength (metres)

For a Gaussian beam propagating from its waist (w0, z=0):

    w(z)  = w0 · √(1 + (z/zR)²)
    R(z)  = z · (1 + (zR/z)²)      (undefined at z=0; → ∞)
    q(z)  = z + i·zR               with  zR = π·n·w0²/λ

ABCD propagation:
    q_out = (A·q + B) / (C·q + D)

M² (beam quality factor):
    Real beam:  far-field half-angle θ_real = M²·λ/(π·w0_real)
    M² = 1 for a perfect Gaussian (TEM₀₀).

References
----------
- Siegman, "Lasers", Chapter 17
- ISO 11146-1:2021 (beam widths, divergence angles)
- Self, S.A., Appl. Opt. 22, 658 (1983) — fibre coupling overlap integrals
"""

from __future__ import annotations

import cmath
import math
from typing import NamedTuple

import numpy as np


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def _nm_to_m(lambda_nm: float) -> float:
    """Convert wavelength from nm to metres."""
    return lambda_nm * 1e-9


# ---------------------------------------------------------------------------
# Complex beam parameter construction
# ---------------------------------------------------------------------------

def q_from_waist_and_distance(w0: float, z: float, lambda_nm: float, n: float = 1.0) -> complex:
    """Build q from beam waist w0 and distance z from the waist.

    Parameters
    ----------
    w0        : beam waist radius (1/e² field radius) in metres
    z         : distance from the waist in metres (+ = propagation direction)
    lambda_nm : vacuum wavelength in nanometres
    n         : refractive index of the medium

    Returns
    -------
    q : complex beam parameter (metres)
    """
    lam = _nm_to_m(lambda_nm)
    zR = math.pi * n * w0 ** 2 / lam
    return complex(z, zR)


def q_from_w_R(w: float, R: float, lambda_nm: float, n: float = 1.0) -> complex:
    """Build q from beam radius w and wavefront radius R at a given plane.

    Parameters
    ----------
    w         : beam radius (1/e² field) in metres at the plane
    R         : wavefront radius of curvature in metres
                (use math.inf or a very large number for a collimated beam)
    lambda_nm : vacuum wavelength in nanometres
    n         : refractive index

    Returns
    -------
    q : complex beam parameter (metres)
    """
    lam = _nm_to_m(lambda_nm)
    if math.isinf(R):
        inv_q = complex(0.0, -lam / (math.pi * n * w ** 2))
    else:
        inv_q = complex(1.0 / R, -lam / (math.pi * n * w ** 2))
    return 1.0 / inv_q


# ---------------------------------------------------------------------------
# Beam parameter extractions
# ---------------------------------------------------------------------------

def beam_radius(q: complex, lambda_nm: float, n: float = 1.0) -> float:
    """Extract the beam radius w from the complex beam parameter q.

    From  Im(1/q) = −λ/(π·n·w²)  →  w = √(−λ / (π·n·Im(1/q)))

    Parameters
    ----------
    q         : complex beam parameter (metres)
    lambda_nm : vacuum wavelength in nanometres
    n         : refractive index

    Returns
    -------
    w : beam radius (1/e² field) in metres
    """
    lam = _nm_to_m(lambda_nm)
    inv_q = 1.0 / q
    im_inv_q = inv_q.imag
    if im_inv_q >= 0.0:
        raise ValueError(
            f"Im(1/q) must be negative for a physical Gaussian beam; got {im_inv_q}"
        )
    return math.sqrt(-lam / (math.pi * n * im_inv_q))


def wavefront_radius(q: complex) -> float:
    """Extract the wavefront radius of curvature R from q.

    From  Re(1/q) = 1/R.

    Returns math.inf when Re(1/q) is zero (collimated beam at waist).
    """
    re_inv_q = (1.0 / q).real
    if abs(re_inv_q) < 1e-30:
        return math.inf
    return 1.0 / re_inv_q


def rayleigh_length(w0: float, lambda_nm: float, n: float = 1.0) -> float:
    """Rayleigh length zR = π·n·w0²/λ.

    The distance from the waist at which the beam area doubles (w = √2·w0).

    Parameters
    ----------
    w0        : beam waist radius in metres
    lambda_nm : vacuum wavelength in nanometres
    n         : refractive index

    Returns
    -------
    zR : Rayleigh length in metres
    """
    lam = _nm_to_m(lambda_nm)
    return math.pi * n * w0 ** 2 / lam


class WaistResult(NamedTuple):
    w0: float    # beam waist radius (metres)
    z: float     # distance from waist to the current plane (metres)
    zR: float    # Rayleigh length (metres)


def beam_waist_from_q(q: complex, lambda_nm: float, n: float = 1.0) -> WaistResult:
    """Recover waist radius w0 and distance z from q.

    q(z) = z + i·zR  →  z = Re(q), zR = Im(q), w0 = √(λ·zR / (π·n))

    Parameters
    ----------
    q         : complex beam parameter (metres)
    lambda_nm : vacuum wavelength in nanometres
    n         : refractive index

    Returns
    -------
    WaistResult(w0, z, zR)
    """
    lam = _nm_to_m(lambda_nm)
    z = q.real
    zR = q.imag
    if zR <= 0.0:
        raise ValueError(f"Im(q) = zR must be positive; got {zR}")
    w0 = math.sqrt(lam * zR / (math.pi * n))
    return WaistResult(w0=w0, z=z, zR=zR)


# ---------------------------------------------------------------------------
# ABCD propagation of q
# ---------------------------------------------------------------------------

def propagate_q(q: complex, M: np.ndarray) -> complex:
    """Propagate q through an ABCD system.

    q_out = (A·q + B) / (C·q + D)

    Parameters
    ----------
    q : input complex beam parameter (metres)
    M : 2×2 ABCD matrix [[A, B], [C, D]]

    Returns
    -------
    q_out : output complex beam parameter (metres)
    """
    A = complex(M[0, 0])
    B = complex(M[0, 1])
    C = complex(M[1, 0])
    D = complex(M[1, 1])
    denom = C * q + D
    if abs(denom) < 1e-30:
        raise ValueError("ABCD denominator (C·q + D) is zero; degenerate system")
    return (A * q + B) / denom


# ---------------------------------------------------------------------------
# Predefined ABCD matrices for Gaussian optics
# (using standard physical ABCD convention with absolute distances,
#  not the (y, nu) reduced-angle form used in ray_transfer.py)
# ---------------------------------------------------------------------------

def M_gaussian_free(d: float) -> np.ndarray:
    """Free-space propagation of distance d (any medium; n absorbed into q).

    In the q-parameter convention, free-space distance d in a uniform medium
    maps q → q + d.  The ABCD matrix is [[1, d], [0, 1]].
    """
    if d < 0:
        raise ValueError(f"propagation distance d must be >= 0, got {d}")
    return np.array([[1.0, float(d)],
                     [0.0, 1.0]], dtype=float)


def M_gaussian_thin_lens(f: float) -> np.ndarray:
    """Thin lens of focal length f.  q convention: [[1, 0], [-1/f, 1]]."""
    if f == 0:
        raise ValueError("focal length f must not be zero")
    return np.array([[1.0,    0.0],
                     [-1.0 / f, 1.0]], dtype=float)


def M_gaussian_thick_lens(f: float, d: float, n_lens: float = 1.5) -> np.ndarray:
    """Thick lens approximated as refraction–propagation–refraction.

    Uses a symmetric biconvex lens with |R1| = |R2| = R derived from the
    lensmaker's equation  1/f = (n-1)[1/R1 − 1/R2]  →  R = 2(n-1)f
    for an equiconvex lens.

    Parameters
    ----------
    f      : focal length in metres
    d      : centre thickness in metres
    n_lens : refractive index of the glass (default 1.5)

    Returns
    -------
    2×2 ABCD matrix
    """
    if f == 0:
        raise ValueError("focal length must not be zero")
    if d < 0:
        raise ValueError("thickness d must be >= 0")
    # Equiconvex: R = 2*(n-1)*f  (R1 = R, R2 = -R)
    R = 2.0 * (n_lens - 1.0) * f
    if abs(R) < 1e-14:
        raise ValueError("degenerate thick lens (R ≈ 0)")
    # Refraction at surface 1 (air→glass): power P1 = (n-1)/R
    P1 = (n_lens - 1.0) / R
    # Refraction at surface 2 (glass→air): power P2 = -(n-1)/(-R) = (n-1)/R
    P2 = (n_lens - 1.0) / R
    M_r1 = np.array([[1.0, 0.0], [-P1, 1.0]], dtype=float)
    M_prop = np.array([[1.0, d / n_lens], [0.0, 1.0]], dtype=float)
    M_r2 = np.array([[1.0, 0.0], [-P2, 1.0]], dtype=float)
    return M_r2 @ M_prop @ M_r1


def M_gaussian_planar_interface(n1: float, n2: float) -> np.ndarray:
    """Planar (flat) dielectric interface from medium n1 to n2.

    For a Gaussian beam, a flat interface changes the q parameter:
    q_glass = q_air · (n2/n1).  The ABCD representation is [[1, 0], [0, n1/n2]].

    (Siegman "Lasers" §20.1)
    """
    if n1 <= 0 or n2 <= 0:
        raise ValueError("refractive indices must be positive")
    return np.array([[1.0, 0.0],
                     [0.0, n1 / n2]], dtype=float)


def M_gaussian_curved_interface(R: float, n1: float, n2: float) -> np.ndarray:
    """Curved dielectric interface of radius R from n1 to n2.

    Power P = (n2 - n1) / (R · n2).  ABCD = [[1, 0], [-P, n1/n2]].
    """
    if n1 <= 0 or n2 <= 0:
        raise ValueError("refractive indices must be positive")
    if R == 0:
        return M_gaussian_planar_interface(n1, n2)
    P = (n2 - n1) / (R * n2)
    return np.array([[1.0, 0.0],
                     [-P,  n1 / n2]], dtype=float)


# ---------------------------------------------------------------------------
# M² beam quality
# ---------------------------------------------------------------------------

def m2_divergence_angle(w0_real: float, lambda_nm: float, M2: float = 1.0) -> float:
    """Far-field half-angle divergence for a beam with quality factor M².

    θ_real = M²·λ / (π·w0_real)

    Parameters
    ----------
    w0_real   : measured beam waist radius in metres
    lambda_nm : vacuum wavelength in nanometres
    M2        : beam quality factor (≥ 1; perfect Gaussian → M²=1)

    Returns
    -------
    θ : half-angle divergence in radians
    """
    lam = _nm_to_m(lambda_nm)
    return M2 * lam / (math.pi * w0_real)


def m2_embedded_waist(w0_real: float, M2: float) -> float:
    """Embedded Gaussian (ideal) waist for a beam of quality M².

    The real beam with M²≠1 embeds an ideal Gaussian of waist:
        w0_embedded = w0_real / M

    Parameters
    ----------
    w0_real : measured beam waist radius in metres
    M2      : beam quality factor (≥ 1)

    Returns
    -------
    w0_embedded : embedded waist radius in metres
    """
    if M2 < 1.0:
        raise ValueError(f"M² must be >= 1 (physical beam); got {M2}")
    return w0_real / math.sqrt(M2)


def focused_spot_size(M2: float, lambda_nm: float, NA: float) -> float:
    """Diffraction-limited focused spot radius for a beam of quality M².

    w_spot = M²·λ / (π·NA)

    This is the 1/e² radius at the focused spot for a beam limited by the
    numerical aperture NA.

    Parameters
    ----------
    M2        : beam quality factor (≥ 1)
    lambda_nm : vacuum wavelength in nanometres
    NA        : numerical aperture of the focusing optic

    Returns
    -------
    w_spot : focused spot radius in metres
    """
    if NA <= 0 or NA > 1.0:
        raise ValueError(f"NA must be in (0, 1]; got {NA}")
    lam = _nm_to_m(lambda_nm)
    return M2 * lam / (math.pi * NA)


# ---------------------------------------------------------------------------
# Higher-level helpers
# ---------------------------------------------------------------------------

def beam_after_lens(
    w_in: float,
    R_in: float,
    f: float,
    lambda_nm: float,
    n: float = 1.0,
) -> tuple[complex, float, float]:
    """Propagate a Gaussian beam through a thin lens.

    Parameters
    ----------
    w_in      : beam radius (1/e² field) at the lens input plane (metres)
    R_in      : wavefront radius of curvature at the lens (metres); use math.inf
                for a collimated (plane-wave) beam
    f         : thin-lens focal length (metres)
    lambda_nm : vacuum wavelength (nanometres)
    n         : refractive index of the medium

    Returns
    -------
    (q_out, w_out, R_out)
        q_out : complex beam parameter just after the lens
        w_out : beam radius after the lens (same plane, lenses are thin)
        R_out : wavefront radius of curvature after the lens
    """
    q_in = q_from_w_R(w_in, R_in, lambda_nm, n)
    M = M_gaussian_thin_lens(f)
    q_out = propagate_q(q_in, M)
    w_out = beam_radius(q_out, lambda_nm, n)
    R_out = wavefront_radius(q_out)
    return q_out, w_out, R_out


def fibre_coupling_efficiency(
    w_beam: float,
    w_fibre_MFD: float,
    misalignment_um: float,
    theta_misalign_mrad: float,
    lambda_nm: float,
) -> float:
    """Analytic overlap integral of two Gaussian modes.

    Computes the power coupling efficiency η between a free-space Gaussian
    beam and a single-mode fibre, accounting for lateral offset and angular
    tilt misalignment.

    Both beams are described by their 1/e² field radii.  The fibre mode field
    diameter (MFD) convention is MFD = 2·w_fibre.

    Analytic result (Self 1983, Snyder & Love):

        η = (2·w1·w2 / (w1²+w2²)) ²
            · exp(−2·d²/(w1²+w2²))
            · exp(−(π·(w1·w2)·θ/λ)² · 2/(w1²+w2²))

    where d = lateral misalignment, θ = angular misalignment.

    Parameters
    ----------
    w_beam          : beam 1/e² radius in metres
    w_fibre_MFD     : fibre mode field diameter in metres (MFD = 2·w_fibre)
    misalignment_um : lateral offset between beam and fibre core axes (µm)
    theta_misalign_mrad : angular tilt misalignment (mrad)
    lambda_nm       : vacuum wavelength (nanometres)

    Returns
    -------
    η : coupling efficiency in [0, 1]
    """
    lam = _nm_to_m(lambda_nm)
    w1 = w_beam
    w2 = w_fibre_MFD / 2.0  # convert MFD to radius
    d = misalignment_um * 1e-6
    theta = theta_misalign_mrad * 1e-3  # radians

    w1sq = w1 ** 2
    w2sq = w2 ** 2
    denom = w1sq + w2sq

    # Mode overlap amplitude squared (perfect alignment, matched waists → 1)
    overlap_amp = (2.0 * w1 * w2 / denom) ** 2

    # Lateral misalignment penalty
    lat_penalty = math.exp(-2.0 * d ** 2 / denom)

    # Angular misalignment penalty
    # From the overlap integral: phase factor from tilt = π·w_eff·θ/λ
    # combined: exp(−(π·w1·w2·θ / λ)² · 2/(w1²+w2²))
    ang_penalty = math.exp(-(math.pi * w1 * w2 * theta / lam) ** 2 * 2.0 / denom)

    eta = overlap_amp * lat_penalty * ang_penalty
    return min(max(eta, 0.0), 1.0)  # clamp to [0,1] for floating-point safety
