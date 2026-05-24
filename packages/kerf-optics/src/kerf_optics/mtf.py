"""
kerf_optics.mtf — Modulation Transfer Function (MTF) from an optical system.

Public API
----------
diffraction_limited_mtf(f_number, lambda_nm, spatial_freq_lpmm) -> float
    Diffraction-limited (incoherent) MTF for a circular aperture at a given
    spatial frequency (line pairs / mm at the image plane).

geometric_mtf(spot_radii_mm, spatial_freq_lpmm) -> list[float]
    Geometric (ray-based) MTF estimated from the RMS spot size.

mtf_from_lens_system(system, object_distance, f_number, lambda_nm,
                     spatial_freqs_lpmm, n_rays) -> MTFResult
    Compute the diffraction-limited and geometric MTF curves for a LensSystem.

MTFResult
    Holds spatial frequency axis, diffraction-limited MTF, and geometric MTF.

Background
----------
The (incoherent, polychromatic) MTF for a circular diffraction-limited aperture
(the Optical Transfer Function |OTF|) is given by the Fourier transform of the
point spread function.  For a perfect circular aperture of diameter D and
focal length f, the cut-off frequency is:

    ν_cutoff = D / (λ·f) = 1 / (λ · f/#)    [cycles/mm at image plane]

The normalized spatial frequency:

    s = ν / ν_cutoff  ∈ [0, 1]

The diffraction-limited MTF (Eq. 9.3, Goodman "Introduction to Fourier Optics"):

    MTF_DL(s) = (2/π) · [arccos(s) − s · √(1 − s²)]   for s ∈ [0, 1]
              = 0                                        for s > 1

Geometric (ray-based) MTF approximation via the RMS spot radius r_rms:

    MTF_geo(ν) ≈ exp(−(π · r_rms · ν)²)

This is the Gaussian approximation to the OTF from the geometric spot blur.
(Hopkins, "The frequency response of a defocused optical system", PRSA, 1955;
 Mahajan, "Aberrations of optical images", Opt. Eng., 2013.)

References
----------
- Goodman, J.W., "Introduction to Fourier Optics", 3rd ed., §6.4 (2005).
- Smith, W.J., "Modern Optical Engineering", 4th ed., §3.7 (2008).
- Mahajan, V.N., "Optical Imaging and Aberrations", Part I (SPIE Press, 1998).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Diffraction-limited MTF (circular aperture)
# ---------------------------------------------------------------------------

def diffraction_limited_mtf(
    f_number: float,
    lambda_nm: float,
    spatial_freq_lpmm: float,
) -> float:
    """
    Diffraction-limited incoherent MTF for a circular aperture.

    Parameters
    ----------
    f_number         : f/# = focal_length / aperture_diameter (dimensionless)
    lambda_nm        : wavelength in nanometres
    spatial_freq_lpmm: spatial frequency in line pairs per millimetre (lp/mm)

    Returns
    -------
    float : MTF value in [0, 1] at the given spatial frequency.
            Returns 0 for spatial frequencies above the diffraction cut-off.

    Notes
    -----
    Cut-off frequency: ν_c = 1 / (λ·f/#) [cycles/mm]
    Normalised frequency: s = ν / ν_c
    MTF_DL(s) = (2/π) · [arccos(s) − s·√(1−s²)]  for s ≤ 1; else 0.
    """
    if f_number <= 0:
        raise ValueError(f"f_number must be > 0; got {f_number}")
    if lambda_nm <= 0:
        raise ValueError(f"lambda_nm must be > 0; got {lambda_nm}")
    if spatial_freq_lpmm < 0:
        raise ValueError(f"spatial_freq_lpmm must be >= 0; got {spatial_freq_lpmm}")

    lam_mm = lambda_nm * 1e-6  # nm → mm
    nu_cutoff = 1.0 / (lam_mm * f_number)  # lp/mm

    s = spatial_freq_lpmm / nu_cutoff
    if s >= 1.0:
        return 0.0

    # MTF_DL formula (Goodman §6.4)
    mtf = (2.0 / math.pi) * (math.acos(s) - s * math.sqrt(1.0 - s * s))
    return float(np.clip(mtf, 0.0, 1.0))


def diffraction_cutoff_lpmm(f_number: float, lambda_nm: float) -> float:
    """
    Diffraction cut-off spatial frequency in lp/mm.

    ν_cutoff = 1 / (λ [mm] · f/#)

    Parameters
    ----------
    f_number  : f/# = focal_length / aperture_diameter
    lambda_nm : wavelength in nanometres

    Returns
    -------
    float : cut-off frequency in lp/mm
    """
    if f_number <= 0:
        raise ValueError(f"f_number must be > 0; got {f_number}")
    if lambda_nm <= 0:
        raise ValueError(f"lambda_nm must be > 0; got {lambda_nm}")
    lam_mm = lambda_nm * 1e-6
    return 1.0 / (lam_mm * f_number)


# ---------------------------------------------------------------------------
# Geometric MTF (Gaussian spot approximation)
# ---------------------------------------------------------------------------

def geometric_mtf_gaussian(
    rms_spot_mm: float,
    spatial_freq_lpmm: float,
) -> float:
    """
    Geometric MTF from RMS spot radius using the Gaussian approximation.

    MTF_geo(ν) = exp(−(π · r_rms · ν)²)

    This approximation is accurate when the spot is well-approximated by a
    Gaussian profile (small aberrations, paraxial regime).

    Parameters
    ----------
    rms_spot_mm       : RMS spot radius in millimetres
    spatial_freq_lpmm : spatial frequency in lp/mm

    Returns
    -------
    float : geometric MTF value in [0, 1]
    """
    if rms_spot_mm < 0:
        raise ValueError(f"rms_spot_mm must be >= 0; got {rms_spot_mm}")
    exponent = (math.pi * rms_spot_mm * spatial_freq_lpmm) ** 2
    return float(math.exp(-exponent))


# ---------------------------------------------------------------------------
# MTFResult
# ---------------------------------------------------------------------------

@dataclass
class MTFResult:
    """Output of mtf_from_lens_system()."""

    spatial_freqs_lpmm: list
    """Spatial frequency axis in lp/mm."""

    mtf_diffraction_limited: list
    """Diffraction-limited MTF values (circular aperture, monochromatic)."""

    mtf_geometric: list
    """Geometric MTF values (Gaussian spot approximation)."""

    f_number: float
    """f/# used for diffraction-limited calculation."""

    lambda_nm: float
    """Wavelength in nm used for diffraction-limited MTF."""

    rms_spot_mm: float
    """RMS spot radius in mm (from paraxial ray trace)."""

    cutoff_freq_lpmm: float
    """Diffraction cut-off frequency in lp/mm."""

    efl_m: Optional[float] = None
    """Effective focal length of the system (m), or None for afocal systems."""

    def to_dict(self) -> dict:
        return {
            "spatial_freqs_lpmm": self.spatial_freqs_lpmm,
            "mtf_diffraction_limited": [round(v, 6) for v in self.mtf_diffraction_limited],
            "mtf_geometric": [round(v, 6) for v in self.mtf_geometric],
            "f_number": self.f_number,
            "lambda_nm": self.lambda_nm,
            "rms_spot_mm": self.rms_spot_mm,
            "cutoff_freq_lpmm": round(self.cutoff_freq_lpmm, 2),
            "efl_m": self.efl_m,
        }

    @property
    def mtf_50lpmm(self) -> float:
        """Interpolated MTF value at 50 lp/mm (a common camera resolution benchmark)."""
        return self._interp_at(50.0)

    @property
    def mtf_100lpmm(self) -> float:
        """Interpolated MTF value at 100 lp/mm."""
        return self._interp_at(100.0)

    def _interp_at(self, freq: float) -> float:
        """Linear interpolation of diffraction-limited MTF at a given frequency."""
        freqs = np.array(self.spatial_freqs_lpmm)
        vals = np.array(self.mtf_diffraction_limited)
        if freq <= freqs[0]:
            return float(vals[0])
        if freq >= freqs[-1]:
            return float(vals[-1])
        return float(np.interp(freq, freqs, vals))


# ---------------------------------------------------------------------------
# MTF from a LensSystem
# ---------------------------------------------------------------------------

def mtf_from_lens_system(
    system,
    object_distance_m: float,
    f_number: float,
    lambda_nm: float = 550.0,
    spatial_freqs_lpmm: Optional[Sequence[float]] = None,
    n_rays: int = 11,
) -> MTFResult:
    """
    Compute the MTF for a LensSystem.

    Computes both:
    1. Diffraction-limited MTF — based on the system f/# and wavelength.
    2. Geometric MTF — from the paraxial RMS spot radius at the image plane.

    Parameters
    ----------
    system            : LensSystem
    object_distance_m : object distance in metres (positive = real object)
    f_number          : aperture f/# = focal_length / aperture_diameter
    lambda_nm         : wavelength in nanometres (default 550 nm)
    spatial_freqs_lpmm: spatial frequency axis in lp/mm.
                        Default: 10 equally spaced from 0 to 1.1× cut-off.
    n_rays            : number of marginal rays for RMS spot estimation.

    Returns
    -------
    MTFResult

    Raises
    ------
    ValueError if f_number <= 0 or lambda_nm <= 0.
    """
    from kerf_optics.ray_transfer import image_distance, spot_radius_at_plane

    if f_number <= 0:
        raise ValueError(f"f_number must be > 0; got {f_number}")
    if lambda_nm <= 0:
        raise ValueError(f"lambda_nm must be > 0; got {lambda_nm}")

    # System EFL
    M = system.system_matrix()
    C = M[1, 0]
    efl_m: Optional[float] = None
    if abs(C) > 1e-14:
        efl_m = -1.0 / C

    # Image distance
    try:
        di_m = image_distance(M, object_distance_m)
    except Exception:
        di_m = efl_m or 1.0

    # RMS spot radius at image plane
    # Use marginal rays at a range of heights: (y0 ∈ ±aperture_r, u0=0)
    # Aperture radius = EFL / (2 * f_number), default if EFL unknown: 0.01 m
    efl_for_aperture = abs(efl_m) if efl_m is not None else 0.1
    aperture_r = efl_for_aperture / (2.0 * f_number)
    ys = np.linspace(-aperture_r, aperture_r, n_rays)
    rays = [(float(y), 0.0) for y in ys]

    from kerf_optics.lens_system import FreeSpace
    from kerf_optics.ray_transfer import M_free

    # Add free-space to image plane for ray-trace
    matrices = system._flat_matrices() + [M_free(max(di_m, 0.0))]
    rms_spot_m = spot_radius_at_plane(rays, matrices)
    rms_spot_mm = rms_spot_m * 1000.0  # m → mm

    # Diffraction cut-off
    nu_c = diffraction_cutoff_lpmm(f_number, lambda_nm)

    # Default spatial frequency axis: 0 to 1.2× cut-off, 50 points
    if spatial_freqs_lpmm is None:
        spatial_freqs_lpmm = list(np.linspace(0.0, 1.2 * nu_c, 50))

    freqs = list(spatial_freqs_lpmm)
    mtf_dl = [diffraction_limited_mtf(f_number, lambda_nm, nu) for nu in freqs]
    mtf_geo = [geometric_mtf_gaussian(rms_spot_mm, nu) for nu in freqs]

    return MTFResult(
        spatial_freqs_lpmm=freqs,
        mtf_diffraction_limited=mtf_dl,
        mtf_geometric=mtf_geo,
        f_number=f_number,
        lambda_nm=lambda_nm,
        rms_spot_mm=rms_spot_mm,
        cutoff_freq_lpmm=nu_c,
        efl_m=efl_m,
    )
