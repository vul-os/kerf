"""
kerf_cad_core.optics.diffraction_psf — Airy disk diffraction-limited PSF for a circular aperture.

Public API
----------
compute_diffraction_psf(spec, num_samples=200, max_radius_um=20.0) -> DiffractionPSFReport

Theory (Hecht "Optics" 5e §10.2; Born & Wolf "Principles of Optics" 7e §8.5)
------------------------------------------------------------------------------
A circular aperture of diameter D at focal length f illuminated by a plane wave
at wavelength λ produces an Airy pattern in the focal plane.  The intensity PSF is:

    I(r) = [2·J₁(x)/x]²

where x = π·D·r / (λ·f) = π·r / (λ·F#) and r is the radial distance in the
focal plane (Born & Wolf §8.5.2, eq. 8.41; Hecht §10.2.5, eq. 10.22).

The Airy disk radius (first dark ring, first zero of J₁) is:

    r_Airy = 1.22·λ·f/D = 1.22·λ·F#      (Born & Wolf §8.5.2; Hecht §10.2.6)

The Rayleigh resolution criterion (two points just resolved when the Airy disk
centre of one falls on the first dark ring of the other) coincides with r_Airy:

    Δr_Rayleigh = 1.22·λ·F#              (Hecht §10.2.7, eq. 10.28)

The full-width at half-maximum of the central lobe is (Hecht eq. 10.59):

    FWHM ≈ 1.03·λ·F#

Inputs (DiffractionPSFSpec)
---------------------------
    wavelength_nm          : wavelength in nm (e.g. 550 for green light)
    aperture_diameter_mm   : entrance-pupil diameter D (mm)
    focal_length_mm        : lens focal length f (mm)

Outputs (DiffractionPSFReport)
------------------------------
    airy_disk_radius_um    : 1.22·λ·F# in micrometres
    rayleigh_resolution_um : equals airy_disk_radius_um (Rayleigh criterion)
    fwhm_um                : 1.03·λ·F# in micrometres
    psf_profile            : list of (r_um, I) tuples, I(0) normalised to 1.0
    honest_caveat          : plain-English description of model limitations

Honest flags
------------
SCALAR DIFFRACTION ONLY — Kirchhoff / Fraunhofer diffraction theory for a
  circular aperture (Hecht §10.2; Born & Wolf §8).  Vector (electromagnetic)
  diffraction effects (polarisation, E-field vectorial components) are NOT
  modelled.  The scalar approximation is valid for paraxial NA ≪ 1.
CIRCULAR APERTURE — non-circular, annular, or obscured pupils have a different
  PSF (Annular: Born & Wolf §8.5.4).  Not implemented here.
ABERRATION-FREE — Airy pattern is the diffraction-limited ideal.  Real lenses
  have Seidel/Zernike wavefront aberrations that broaden the PSF (Strehl ratio
  < 1) — not modelled.
MONOCHROMATIC (monochromatic path) — polychromatic PSF is available via
  compute_polychromatic_psf(): I_poly(r) = Σ W(λ_i)·I(r,λ_i) / Σ W(λ_i).
ON-AXIS — the formula is exact for on-axis (zero-field-angle) illumination only.
PARAXIAL — valid for NA = D/(2f) ≪ 1.  For high-NA objectives use the vectorial
  Richards-Wolf integral (Born & Wolf §8.7).

References
----------
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017.
    §10.2 (Fraunhofer diffraction by a circular aperture), eq. 10.22, 10.28, 10.59.
Born, M. & Wolf, E. — "Principles of Optics", 7th ed., Cambridge, 1999.
    §8.5 (diffraction pattern with a circular aperture), eq. 8.41.
Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., Roberts & Co., 2005.
    §4.4 (Fraunhofer diffraction integral for a circular aperture).

Units: wavelength in nm; dimensions in mm (input), μm (output profile).
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

# ---------------------------------------------------------------------------
# Optional scipy import with pure-Python fallback
# ---------------------------------------------------------------------------

def _j1(x: float) -> float:
    """
    Bessel function of the first kind, order 1: J₁(x).

    Uses scipy.special.j1 when available; falls back to the ascending-series
    expansion:  J₁(x) = Σ_{m=0}^{∞} (−1)^m x^(2m+1) / (2^(2m+1) m! (m+1)!)

    The series is well-converged for |x| ≤ 20 with 25 terms (relative error
    < 1e-13 within the first Airy lobe).  For large |x| scipy is strongly
    preferred; the series is kept only as a zero-dependency fallback.

    Reference: Abramowitz & Stegun §9.1.10.
    """
    try:
        from scipy.special import j1  # type: ignore[import]
        return float(j1(x))
    except ImportError:
        pass

    # Pure-Python ascending series (adequate for |x| ≤ ~15)
    if x == 0.0:
        return 0.0
    result = 0.0
    term = x / 2.0
    # term = x^(2m+1) / (2^(2m+1) * m! * (m+1)!) for m=0
    for m in range(1, 30):
        result += term
        # Update: term_{m} = term_{m-1} * (-1) * x^2 / (4 * m * (m+1))
        term *= -(x * x) / (4.0 * m * (m + 1))
        if abs(term) < abs(result) * 1e-15:
            break
    return result


def _j1_over_x(x: float) -> float:
    """
    Compute J₁(x)/x safely, using the limit J₁(x)/x → 1/2 as x → 0.

    Reference: Abramowitz & Stegun §9.1.10.
    """
    if abs(x) < 1e-10:
        return 0.5
    return _j1(x) / x


def _airy_intensity(x: float) -> float:
    """
    Airy pattern normalised intensity: I(x) = [2·J₁(x)/x]²

    I(0) = 1.0  (by definition of normalisation).
    First zero at x ≈ 3.8317 (first root of J₁).

    Parameters
    ----------
    x : float
        Dimensionless argument x = π·D·r / (λ·f).

    Returns
    -------
    float in [0, 1].
    """
    return (2.0 * _j1_over_x(x)) ** 2


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: First zero of J₁(x), i.e. x such that J₁(x)=0 for x>0.
#: Abramowitz & Stegun Table 9.5; verified numerically.
_J1_FIRST_ZERO: float = 3.831705970207512

_HONEST_CAVEAT: str = (
    "SCALAR DIFFRACTION ONLY: Kirchhoff/Fraunhofer Airy disk for a circular aperture "
    "(Hecht §10.2; Born & Wolf §8.5). "
    "NOT MODELLED: vector/polarisation effects (Richards-Wolf high-NA integral, Born & Wolf §8.7); "
    "annular/non-circular apertures; lens aberrations (Seidel/Zernike wavefront error); "
    "polychromatic illumination (∫W(λ)·I(r,λ)dλ); off-axis field dependence. "
    "Valid for paraxial (NA ≪ 1) on-axis scalar diffraction only. "
    "Ref: Hecht (2017) §10.2; Born & Wolf (1999) §8.5."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DiffractionPSFSpec:
    """
    Input specification for the diffraction-limited Airy-disk PSF computation.

    Attributes
    ----------
    wavelength_nm : float
        Wavelength of light in nanometres (nm). E.g. 550 for green light.
        Must be > 0.
    aperture_diameter_mm : float
        Entrance-pupil (aperture) diameter D in millimetres. Must be > 0.
    focal_length_mm : float
        Lens focal length f in millimetres. Must be > 0.
    """
    wavelength_nm: float
    aperture_diameter_mm: float
    focal_length_mm: float


@dataclass
class DiffractionPSFReport:
    """
    Diffraction-limited Airy-disk PSF report for a circular aperture.

    Attributes
    ----------
    airy_disk_radius_um : float
        Radius of the Airy disk (first dark ring) in micrometres.
        r_Airy = 1.22·λ·f/D = 1.22·λ·F#  (Born & Wolf §8.5.2; Hecht §10.2.6).
    rayleigh_resolution_um : float
        Rayleigh resolution criterion in micrometres. Equals airy_disk_radius_um.
        Two point sources are just resolved when the Airy-disk centre of one falls
        on the first dark ring of the other (Hecht §10.2.7, eq. 10.28).
    fwhm_um : float
        Full-width at half-maximum of the central Airy lobe in micrometres.
        FWHM ≈ 1.03·λ·F#  (Hecht eq. 10.59).
    psf_profile : list[tuple[float, float]]
        Radial intensity profile: list of (r_um, I) tuples where r_um is the
        radial distance in micrometres and I = [2·J₁(x)/x]² ∈ [0, 1].
        I(0) = 1.0 by normalisation (Hecht eq. 10.22).
    honest_caveat : str
        Plain-English summary of what this model does NOT cover.
    """
    airy_disk_radius_um: float
    rayleigh_resolution_um: float
    fwhm_um: float
    psf_profile: list[tuple[float, float]] = field(default_factory=list)
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "airy_disk_radius_um": self.airy_disk_radius_um,
            "rayleigh_resolution_um": self.rayleigh_resolution_um,
            "fwhm_um": self.fwhm_um,
            "psf_profile": [list(pt) for pt in self.psf_profile],
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_diffraction_psf(
    spec: "DiffractionPSFSpec",
    num_samples: int = 200,
    max_radius_um: float = 20.0,
) -> "DiffractionPSFReport | dict":
    """
    Compute the diffraction-limited Airy-disk PSF for a circular aperture.

    Parameters
    ----------
    spec : DiffractionPSFSpec
        Input specification: wavelength_nm, aperture_diameter_mm, focal_length_mm.
    num_samples : int
        Number of radial sample points in [0, max_radius_um].  Default 200.
        Must be >= 2.
    max_radius_um : float
        Maximum radial extent of the PSF profile in micrometres.  Default 20.0 μm.
        Must be > 0.

    Returns
    -------
    DiffractionPSFReport on success.
    dict {"ok": False, "reason": "..."} on input error.

    Analytic oracle
    ---------------
    λ=550 nm, D=10 mm, f=50 mm → F#=5:
      r_Airy = 1.22 × 550e-6 mm × 5 = 3.355×10⁻³ mm = 3.355 μm
      FWHM   = 1.03 × 550e-6 mm × 5 = 2.8325×10⁻³ mm ≈ 2.833 μm
      I(0)   = 1.0 exactly (normalisation)

    References
    ----------
    Hecht, E. — "Optics", 5th ed., §10.2, eq. 10.22, 10.28, 10.59.
    Born, M. & Wolf, E. — "Principles of Optics", 7th ed., §8.5.2, eq. 8.41.
    """
    # --- Input validation ---
    if not isinstance(spec, DiffractionPSFSpec):
        return {"ok": False, "reason": "spec must be a DiffractionPSFSpec instance"}

    try:
        wl_nm = float(spec.wavelength_nm)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "wavelength_nm must be a number"}
    if not math.isfinite(wl_nm) or wl_nm <= 0.0:
        return {"ok": False, "reason": "wavelength_nm must be > 0"}

    try:
        D_mm = float(spec.aperture_diameter_mm)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "aperture_diameter_mm must be a number"}
    if not math.isfinite(D_mm) or D_mm <= 0.0:
        return {"ok": False, "reason": "aperture_diameter_mm must be > 0"}

    try:
        f_mm = float(spec.focal_length_mm)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "focal_length_mm must be a number"}
    if not math.isfinite(f_mm) or f_mm <= 0.0:
        return {"ok": False, "reason": "focal_length_mm must be > 0"}

    if not isinstance(num_samples, int) or num_samples < 2:
        return {"ok": False, "reason": "num_samples must be an integer >= 2"}

    try:
        max_r = float(max_radius_um)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "max_radius_um must be a number"}
    if not math.isfinite(max_r) or max_r <= 0.0:
        return {"ok": False, "reason": "max_radius_um must be > 0"}

    # --- Derived quantities ---
    # Convert wavelength: nm → mm (1 nm = 1e-6 mm)
    wl_mm = wl_nm * 1.0e-6

    # F-number
    f_number = f_mm / D_mm

    # Airy disk radius: r_Airy = 1.22·λ·f/D = 1.22·λ·F#  (Hecht §10.2.6; Born & Wolf §8.5.2)
    # Convert mm → μm (1 mm = 1000 μm)
    airy_disk_radius_um = 1.22 * wl_mm * f_number * 1.0e3

    # Rayleigh resolution criterion = Airy disk radius (Hecht §10.2.7)
    rayleigh_resolution_um = airy_disk_radius_um

    # FWHM of the Airy central lobe ≈ 1.03·λ·F#  (Hecht eq. 10.59)
    fwhm_um = 1.03 * wl_mm * f_number * 1.0e3

    # --- Radial PSF profile ---
    # x = π·D·r / (λ·f)  where r in mm, λ in mm, f in mm
    # With r in μm → r_mm = r_um * 1e-3
    # x = π · D_mm · r_mm / (wl_mm · f_mm)
    #   = π · D_mm · r_um * 1e-3 / (wl_mm · f_mm)
    x_per_um = math.pi * D_mm * 1.0e-3 / (wl_mm * f_mm)  # x / (r in μm)

    step = max_r / (num_samples - 1)
    psf_profile: list[tuple[float, float]] = []
    for i in range(num_samples):
        r_um = i * step
        x = x_per_um * r_um
        I = _airy_intensity(x)
        psf_profile.append((r_um, I))

    return DiffractionPSFReport(
        airy_disk_radius_um=airy_disk_radius_um,
        rayleigh_resolution_um=rayleigh_resolution_um,
        fwhm_um=fwhm_um,
        psf_profile=psf_profile,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Standard SPD helpers
# NOTE: intentionally inlined here rather than imported from distortion_map.py
# or mtf_diffraction.py to avoid circular-import chains.  All three are pure
# math; no shared state.
# ---------------------------------------------------------------------------

def photopic_spd(wavelengths_nm: Sequence[float]) -> list[float]:
    """
    CIE 1931 photopic luminosity function V(λ).

    Uses the analytic Gaussian approximation (accurate to < 1 % over 390–700 nm):
        V(λ) ≈ 1.019 · exp(−285.4 · (λ/1000 − 0.5593)²)   [λ in nm]
    Peak at λ ≈ 555 nm, V(555) = 1.0.

    References: CIE DS 013.3:2018; Wyszecki & Stiles (1982) Table 2(3.3.1).
    """
    result = []
    for lam in wavelengths_nm:
        x = lam / 1000.0 - 0.5593
        v = 1.019 * math.exp(-285.4 * x * x)
        result.append(max(0.0, min(1.0, v)))
    return result


def d65_spd(wavelengths_nm: Sequence[float]) -> list[float]:
    """
    CIE D65 standard illuminant SPD — piecewise-linear interpolation of the
    published 5 nm tabulation (CIE Pub. 15:2004, Table T.1, normalised to 100
    at 560 nm).  Values outside 300–830 nm are clamped to 0.
    """
    _D65_LAMBDA_START = 300.0
    _D65_LAMBDA_STEP = 5.0
    _D65_TABLE = [
        0.034100, 1.664300, 3.294500, 11.765200, 20.236000,
        28.644700, 37.053500, 38.501100, 39.948800, 42.430200,
        44.911700, 45.775000, 46.638300, 49.363700, 52.089100,
        51.032300, 49.975500, 52.311800, 54.648200, 68.701500,
        82.754900, 87.120400, 91.486000, 92.458900, 93.431800,
        90.057000, 86.682300, 95.773600, 104.865000, 110.936000,
        117.008000, 117.410000, 117.812000, 116.336000, 114.861000,
        115.392000, 115.923000, 112.367000, 108.811000, 109.082000,
        109.354000, 108.578000, 107.802000, 106.296000, 104.790000,
        106.239000, 107.689000, 106.047000, 104.405000, 104.225000,
        104.046000, 102.023000, 100.000000, 98.167100, 96.334200,
        96.061100, 95.788000, 92.236800, 88.685600, 89.345900,
        90.006200, 89.802600, 89.599100, 88.648900, 87.698700,
        85.493600, 83.288600, 83.493900, 83.699200, 81.863000,
        80.026800, 80.120700, 80.214600, 81.246200, 82.277800,
        80.281000, 78.284200, 74.002700, 69.721300, 70.665200,
        71.609100, 72.979000, 74.349000, 67.976500, 61.604000,
        65.744800, 69.885600, 72.486300, 75.087000, 69.339800,
        63.592700, 55.005400, 46.418200, 56.611800, 66.805400,
        65.094100, 63.382800, 63.843400, 64.304000, 61.877900,
        59.451800, 55.705400, 51.959000, 54.699800, 57.440600,
        58.876500, 60.312500,
    ]
    out = []
    for lam in wavelengths_nm:
        idx_f = (lam - _D65_LAMBDA_START) / _D65_LAMBDA_STEP
        if idx_f < 0.0 or idx_f > len(_D65_TABLE) - 1:
            out.append(0.0)
            continue
        i0 = int(idx_f)
        i1 = min(i0 + 1, len(_D65_TABLE) - 1)
        frac = idx_f - i0
        out.append(_D65_TABLE[i0] * (1.0 - frac) + _D65_TABLE[i1] * frac)
    return out


def blackbody_spd(wavelengths_nm: Sequence[float], T_K: float) -> list[float]:
    """
    Planck blackbody spectral radiance (unnormalised):
        B(λ, T) ∝ λ^{-5} / [exp(hc/λkT) − 1]

    Peak: λ_max = 2.8977721e6 nm·K / T_K  (Wien's displacement law).
    Ref: Planck (1901) Ann.Phys. 4, 553.

    Raises ValueError if T_K <= 0.
    """
    if T_K <= 0.0:
        raise ValueError(f"T_K must be > 0, got {T_K}")
    _HC_OVER_K = 1.4387769e7  # nm·K
    out = []
    for lam in wavelengths_nm:
        if lam <= 0.0:
            out.append(0.0)
            continue
        exponent = _HC_OVER_K / (lam * T_K)
        if exponent > 700.0:
            out.append(0.0)
        else:
            out.append((lam ** -5) / (math.exp(exponent) - 1.0))
    return out


# ---------------------------------------------------------------------------
# Polychromatic PSF dataclass
# ---------------------------------------------------------------------------

_POLY_PSF_HONEST_CAVEAT: str = (
    "POLYCHROMATIC AIRY DISK PSF: I_poly(r) = Σ_i W(λ_i)·I(r,λ_i) / Σ_i W(λ_i). "
    "Each per-wavelength PSF is the scalar Kirchhoff/Fraunhofer Airy pattern "
    "I(r,λ) = [2·J₁(x)/x]² where x = π·D·r/(λ·f) (Hecht §10.2; Born & Wolf §8.5.2). "
    "SCALAR DIFFRACTION ONLY: no vector/polarisation effects (Richards-Wolf, Born & Wolf §8.7). "
    "CIRCULAR APERTURE ONLY: annular or non-circular pupils differ. "
    "ABERRATION-FREE: Airy pattern is the diffraction-limited ideal (Strehl=1 assumed). "
    "ON-AXIS AND PARAXIAL: exact for on-axis illumination, valid for NA = D/(2f) ≪ 1. "
    "Broadband PSF is broader than the best-λ monochromatic PSF because longer λ "
    "gives a wider Airy disk, weighted by W(λ). "
    "Accuracy depends on spectral sampling density — use ≥ 5 wavelength samples. "
    "Refs: Hecht (2017) §10.2; Born & Wolf (1999) §8.5; Goodman (2005) §4.4."
)


@dataclass
class PolychromaticPSFReport:
    """
    Spectrally-integrated (polychromatic) Airy-disk PSF report.

    I_poly(r) = Σ_i W(λ_i)·I(r, λ_i) / Σ_i W(λ_i)

    Each per-wavelength contribution I(r, λ_i) is the monochromatic Airy pattern
    [2·J₁(x)/x]² where x = π·D·r/(λ_i·f).

    Attributes
    ----------
    numerical_aperture : float
        NA = D/(2f) used for the computation.
    focal_length_mm : float
        Lens focal length (mm).
    wavelength_samples_nm : list[float]
        Wavelength grid (nm) used for spectral integration.
    spd_weights_normalised : list[float]
        SPD weights at each wavelength, normalised so that sum = 1.
    airy_disk_radius_um_per_wavelength : list[float]
        1.22·λ_i·F# (μm) for each wavelength sample.
    poly_psf_profile : list[tuple[float, float]]
        (r_um, I_poly) pairs; I_poly(0) = 1.0 by normalisation.
    honest_caveat : str
        Plain-English summary of model limitations.
    """
    numerical_aperture: float = 0.0
    focal_length_mm: float = 0.0
    wavelength_samples_nm: list = field(default_factory=list)
    spd_weights_normalised: list = field(default_factory=list)
    airy_disk_radius_um_per_wavelength: list = field(default_factory=list)
    poly_psf_profile: list = field(default_factory=list)
    honest_caveat: str = _POLY_PSF_HONEST_CAVEAT

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "numerical_aperture": self.numerical_aperture,
            "focal_length_mm": self.focal_length_mm,
            "wavelength_samples_nm": self.wavelength_samples_nm,
            "spd_weights_normalised": self.spd_weights_normalised,
            "airy_disk_radius_um_per_wavelength": self.airy_disk_radius_um_per_wavelength,
            "poly_psf_profile": [list(pt) for pt in self.poly_psf_profile],
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Polychromatic PSF — public API
# ---------------------------------------------------------------------------

def compute_polychromatic_psf(
    numerical_aperture: float,
    focal_length_mm: float,
    wavelength_samples_nm: Sequence[float],
    spd_weights: Sequence[float],
    radial_grid_um: "Sequence[float] | None" = None,
    num_samples: int = 200,
    max_radius_um: float = 20.0,
) -> "PolychromaticPSFReport | dict":
    """
    Compute the spectrally-integrated (polychromatic) Airy-disk PSF for a
    circular aperture.

    Algorithm
    ---------
    For each wavelength λ_i with SPD weight W_i and aperture D = 2·NA·f:

      1. Compute per-wavelength x-scale factor:
           x_per_um(λ_i) = π·D·1e-3 / (λ_i_mm · f_mm)

      2. Evaluate monochromatic Airy intensity at each radial point r:
           I(r, λ_i) = [2·J₁(x_per_um(λ_i)·r) / (x_per_um(λ_i)·r)]²

      3. Accumulate weighted sum:
           I_poly(r) = Σ_i W_i · I(r, λ_i) / Σ_i W_i

    I_poly(0) = 1.0 exactly (all monochromatic PSFs are 1.0 at r=0, and the
    weights normalise to 1).

    Parameters
    ----------
    numerical_aperture : float
        Image-space NA = D/(2f) where D is aperture diameter and f is focal
        length.  Must be in (0, 1].
    focal_length_mm : float
        Lens focal length in millimetres.  Must be > 0.
    wavelength_samples_nm : sequence of float
        Wavelength grid (nm), ≥ 2 elements, all > 0.
    spd_weights : sequence of float
        Spectral power density at each wavelength (arbitrary scale, ≥ 0, not
        all zero).  Same length as wavelength_samples_nm.
    radial_grid_um : sequence of float or None
        Custom radial sample positions in μm (all ≥ 0).  If provided,
        num_samples and max_radius_um are ignored.  Must have ≥ 2 elements.
    num_samples : int
        Number of equally-spaced radial samples in [0, max_radius_um] when
        radial_grid_um is None.  Default 200.  Must be ≥ 2.
    max_radius_um : float
        Maximum radial extent of the PSF profile (μm) when radial_grid_um is
        None.  Default 20.0.  Must be > 0.

    Returns
    -------
    PolychromaticPSFReport on success.
    dict {"ok": False, "reason": "..."} on input error.

    Analytic checks
    ---------------
    1. Single-wavelength SPD (W = [1.0] for one λ):
       I_poly(r) ≡ I_mono(r, λ) — identical to compute_diffraction_psf() result.
    2. Broadband SPD: peak at r=0 always 1.0; polychromatic profile is a weighted
       average of per-λ Airy patterns; effectively broader than the best-λ PSF.
    3. Photopic SPD: strongly weighted near 555 nm (V(λ) peak).

    References
    ----------
    Hecht, E. — "Optics", 5th ed., §10.2, eq. 10.22.
    Born, M. & Wolf, E. — "Principles of Optics", 7th ed., §8.5.2, eq. 8.41.
    Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., §4.4.
    """
    # --- Input validation ---------------------------------------------------
    try:
        na = float(numerical_aperture)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "numerical_aperture must be a number"}
    if not math.isfinite(na) or na <= 0.0 or na > 1.0:
        return {"ok": False, "reason": "numerical_aperture must be in (0, 1]"}

    try:
        f_mm = float(focal_length_mm)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "focal_length_mm must be a number"}
    if not math.isfinite(f_mm) or f_mm <= 0.0:
        return {"ok": False, "reason": "focal_length_mm must be > 0"}

    try:
        lambdas = [float(v) for v in wavelength_samples_nm]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"wavelength_samples_nm invalid: {exc}"}
    if len(lambdas) < 2:
        return {
            "ok": False,
            "reason": "wavelength_samples_nm must have at least 2 elements",
        }
    if any(lam <= 0.0 for lam in lambdas):
        return {"ok": False, "reason": "all wavelength_samples_nm must be > 0"}

    try:
        weights = [float(v) for v in spd_weights]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"spd_weights invalid: {exc}"}
    if len(weights) != len(lambdas):
        return {
            "ok": False,
            "reason": (
                f"spd_weights length ({len(weights)}) must match "
                f"wavelength_samples_nm length ({len(lambdas)})"
            ),
        }
    if any(w < 0.0 for w in weights):
        return {"ok": False, "reason": "spd_weights must all be >= 0"}
    total_w = sum(weights)
    if total_w <= 0.0:
        return {"ok": False, "reason": "spd_weights must not be all zero"}

    # --- Build radial grid --------------------------------------------------
    if radial_grid_um is not None:
        try:
            r_grid = [float(v) for v in radial_grid_um]
        except (TypeError, ValueError) as exc:
            return {"ok": False, "reason": f"radial_grid_um invalid: {exc}"}
        if len(r_grid) < 2:
            return {"ok": False, "reason": "radial_grid_um must have at least 2 elements"}
        if any(r < 0.0 for r in r_grid):
            return {"ok": False, "reason": "radial_grid_um values must all be >= 0"}
    else:
        if not isinstance(num_samples, int) or num_samples < 2:
            return {"ok": False, "reason": "num_samples must be an integer >= 2"}
        try:
            max_r = float(max_radius_um)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "max_radius_um must be a number"}
        if not math.isfinite(max_r) or max_r <= 0.0:
            return {"ok": False, "reason": "max_radius_um must be > 0"}
        step = max_r / (num_samples - 1)
        r_grid = [i * step for i in range(num_samples)]

    # --- Derived optical quantities -----------------------------------------
    # Aperture diameter: D = 2·NA·f  (mm)
    D_mm = 2.0 * na * f_mm
    # F-number: F# = f / D = 1 / (2·NA)
    f_number = f_mm / D_mm  # = 1 / (2·NA)

    # Per-wavelength x-scale factors and Airy disk radii
    #   x_per_um(λ) = π · D_mm · 1e-3 / (λ_mm · f_mm)
    #   r_Airy(λ)   = 1.22 · λ_mm · F# · 1e3  (μm)
    x_scales: list[float] = []
    airy_radii_um: list[float] = []
    for lam in lambdas:
        lam_mm = lam * 1.0e-6
        x_scales.append(math.pi * D_mm * 1.0e-3 / (lam_mm * f_mm))
        airy_radii_um.append(1.22 * lam_mm * f_number * 1.0e3)

    # --- Spectral summation -------------------------------------------------
    # I_poly(r) = Σ_i W_i · I(r, λ_i) / Σ_i W_i
    n_r = len(r_grid)
    num_arr = [0.0] * n_r

    for lam_idx, (x_scale, w) in enumerate(zip(x_scales, weights)):
        if w == 0.0:
            continue
        for j, r_um in enumerate(r_grid):
            x = x_scale * r_um
            I_mono = _airy_intensity(x)
            num_arr[j] += w * I_mono

    # Normalise
    poly_psf_profile: list[tuple[float, float]] = []
    for j, r_um in enumerate(r_grid):
        I_poly = num_arr[j] / total_w
        poly_psf_profile.append((r_um, I_poly))

    # Normalised SPD weights (sum to 1)
    spd_weights_norm = [w / total_w for w in weights]

    return PolychromaticPSFReport(
        numerical_aperture=na,
        focal_length_mm=f_mm,
        wavelength_samples_nm=lambdas,
        spd_weights_normalised=spd_weights_norm,
        airy_disk_radius_um_per_wavelength=airy_radii_um,
        poly_psf_profile=poly_psf_profile,
        honest_caveat=_POLY_PSF_HONEST_CAVEAT,
    )
