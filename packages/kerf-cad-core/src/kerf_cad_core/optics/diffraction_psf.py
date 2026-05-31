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
MONOCHROMATIC — polychromatic PSF requires integrating I(r,λ) over spectral
  weighting W(λ) — not implemented.
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
