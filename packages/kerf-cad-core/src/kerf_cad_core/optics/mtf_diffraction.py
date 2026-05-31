"""
kerf_cad_core.optics.mtf_diffraction — Diffraction-limited MTF for a circular aperture.

Public API
----------
compute_diffraction_mtf(wavelength_nm, f_number, num_samples=200,
                        max_freq_cyc_per_mm=None) -> MTFReport

Theory
------
For an incoherent, diffraction-limited optical system with a circular exit pupil,
the Optical Transfer Function equals the (normalised) autocorrelation of the pupil
function.  The on-axis MTF is the modulus of the OTF, which for a circular aperture
has a well-known closed-form solution (Goodman, "Introduction to Fourier Optics",
§6.4; Hecht, "Optics" 5e §11.3.3):

  ν_0 = 1 / (λ · F#)               [diffraction cutoff, cyc/mm]

  MTF(ν) = (2/π) · [arccos(ν/ν_0) − (ν/ν_0) · √(1 − (ν/ν_0)²)]   for ν ≤ ν_0
  MTF(ν) = 0                                                          for ν > ν_0

This is identically the area of the lens-of-two-circles overlap normalised to the
full pupil area (Goodman §6.4, eq. 6-49; Born & Wolf 7e §9.5).

Inputs
------
  wavelength_nm  : wavelength of light in nanometres (e.g. 550 for green light).
  f_number       : system F-number (f/#, > 0).
  num_samples    : number of frequency samples in [0, ν_0] (default 200).
  max_freq_cyc_per_mm : upper frequency limit for the output curve.  If None,
                        defaults to 1.05 × ν_0 so the zero-crossing is visible.

Outputs (MTFReport dataclass)
------
  cutoff_freq_cyc_per_mm : diffraction cutoff ν_0 (cyc/mm).
  mtf_curve              : list of (ν, MTF(ν)) tuples.
  mtf_at_50_percent      : spatial frequency at which MTF ≈ 0.5 (Nyquist test).
  honest_caveat          : plain-English summary of what this model does NOT cover.

Honest flags
------------
DIFFRACTION-LIMITED ONLY.  This model assumes a perfect, aberration-free,
  defocus-free system.  Any real lens will have lower MTF than this curve.
  Aberrations (Seidel coefficients S_I–S_V), defocus, wavefront error, and sensor
  MTF are NOT modelled.
MONOCHROMATIC.  The polychromatic MTF requires integrating MTF(λ) over the spectral
  weighting function — not implemented here.
CIRCULAR APERTURE.  Obscured (annular) or non-circular pupils have a different
  analytic form — not implemented.
ON-AXIS (ZERO FIELD ANGLE).  The closed-form expression is valid only on the
  optical axis.  Off-axis MTF drops due to aberrations and vignetting.

References
----------
Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., Roberts & Co., 2005.
    §6.4, eq. 6-49:  closed-form OTF for a diffraction-limited circular aperture.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017.
    §11.3.3:  diffraction-limited MTF and the pupil autocorrelation.
Born, M. & Wolf, E. — "Principles of Optics", 7th ed., Cambridge, 1999.
    §9.5.2, eq. 9.80:  incoherent OTF = normalised pupil autocorrelation.

Units: spatial frequencies in cyc/mm, wavelength in nm (converted internally to mm).
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "DIFFRACTION-LIMITED ONLY: this is the theoretical upper bound for a perfect "
    "circular aperture (Goodman §6.4). Any real lens will have lower MTF due to "
    "aberrations (Seidel S_I–S_V), defocus, wavefront error, or obscuration. "
    "MONOCHROMATIC: polychromatic MTF = ∫W(λ)·MTF(λ)dλ — not implemented. "
    "CIRCULAR APERTURE: annular or non-circular pupils have a different analytic form. "
    "ON-AXIS ONLY: off-axis MTF drops due to aberrations and vignetting — not modelled."
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MTFReport:
    """
    Diffraction-limited MTF result for a circular aperture.

    Attributes
    ----------
    cutoff_freq_cyc_per_mm : float
        Diffraction cutoff frequency ν_0 = 1/(λ·F#) in cyc/mm.
    mtf_curve : list[tuple[float, float]]
        Sequence of (ν, MTF(ν)) pairs.  ν is in cyc/mm; MTF ∈ [0, 1].
    mtf_at_50_percent : float
        Spatial frequency (cyc/mm) at which MTF first drops to ≤ 0.50.
        Useful as a Nyquist / system bandwidth metric.
    honest_caveat : str
        Plain-English description of model limitations.
    """
    cutoff_freq_cyc_per_mm: float
    mtf_curve: list[tuple[float, float]] = field(default_factory=list)
    mtf_at_50_percent: float = 0.0
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "cutoff_freq_cyc_per_mm": self.cutoff_freq_cyc_per_mm,
            "mtf_curve": [list(pt) for pt in self.mtf_curve],
            "mtf_at_50_percent": self.mtf_at_50_percent,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def _mtf_value(nu_normalised: float) -> float:
    """
    Closed-form diffraction-limited MTF for a circular aperture at normalised
    spatial frequency s = ν/ν_0.

    MTF(s) = (2/π) · [arccos(s) − s · √(1 − s²)]   for 0 ≤ s ≤ 1
    MTF(s) = 0                                         for s > 1

    Source: Goodman "Introduction to Fourier Optics" §6.4, eq. 6-49;
            Hecht "Optics" 5e §11.3.3.

    Parameters
    ----------
    nu_normalised : float
        s = ν / ν_0.  Must be ≥ 0.

    Returns
    -------
    float in [0, 1].
    """
    if nu_normalised <= 0.0:
        return 1.0
    if nu_normalised >= 1.0:
        return 0.0
    s = nu_normalised
    # Clamp to avoid domain errors due to floating-point
    s = max(0.0, min(1.0, s))
    return (2.0 / math.pi) * (math.acos(s) - s * math.sqrt(1.0 - s * s))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_diffraction_mtf(
    wavelength_nm: float,
    f_number: float,
    num_samples: int = 200,
    max_freq_cyc_per_mm: float | None = None,
) -> "MTFReport | dict":
    """
    Compute the diffraction-limited Modulation Transfer Function MTF(ν) for a
    circular aperture.

    Parameters
    ----------
    wavelength_nm : float
        Wavelength of light in nanometres (nm).  E.g. 550 for green light.
        Must be > 0.
    f_number : float
        System F-number (f/#).  Must be > 0.  E.g. 4 for f/4.
    num_samples : int
        Number of equally-spaced frequency samples in [0, max_freq_cyc_per_mm].
        Default 200.  Must be ≥ 2.
    max_freq_cyc_per_mm : float | None
        Upper frequency limit for the output curve (cyc/mm).
        If None, defaults to 1.05 × ν_0 so the zero-crossing is visible.
        Must be > 0 if provided.

    Returns
    -------
    MTFReport on success.
    dict {"ok": False, "reason": "..."} on input error.

    Analytic oracle
    ---------------
    λ = 550 nm, F/4:
      ν_0 = 1/(550e-6 mm · 4) = 454.545... cyc/mm
      MTF(0)        = 1.0 exactly
      MTF(ν_0)      = 0.0 exactly
      MTF(ν_0/2)    = (2/π)[arccos(0.5) − 0.5·√(1−0.25)]
                    = (2/π)[π/3 − 0.5·(√3/2)]
                    ≈ 0.3906 (Goodman §6.4)

    References
    ----------
    Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., §6.4, eq. 6-49.
    Hecht, E. — "Optics", 5th ed., §11.3.3.
    """
    # --- Input validation ---
    try:
        wl_nm = float(wavelength_nm)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "wavelength_nm must be a number"}
    if not math.isfinite(wl_nm) or wl_nm <= 0.0:
        return {"ok": False, "reason": "wavelength_nm must be > 0"}

    try:
        fn = float(f_number)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "f_number must be a number"}
    if not math.isfinite(fn) or fn <= 0.0:
        return {"ok": False, "reason": "f_number must be > 0"}

    if not isinstance(num_samples, int) or num_samples < 2:
        return {"ok": False, "reason": "num_samples must be an integer >= 2"}

    if max_freq_cyc_per_mm is not None:
        try:
            max_freq_cyc_per_mm = float(max_freq_cyc_per_mm)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "max_freq_cyc_per_mm must be a number"}
        if not math.isfinite(max_freq_cyc_per_mm) or max_freq_cyc_per_mm <= 0.0:
            return {"ok": False, "reason": "max_freq_cyc_per_mm must be > 0"}

    # --- Core calculation ---
    # Convert wavelength from nm to mm: 1 nm = 1e-6 mm
    wl_mm = wl_nm * 1.0e-6

    # Diffraction cutoff: ν_0 = 1 / (λ_mm · F#)
    # Derivation: the pupil diameter D = f / F#; the OTF cutoff for incoherent
    # illumination is ν_0 = D / (λ · f) = 1 / (λ · F#).
    # (Goodman §6.4, eq. 6-49; Born & Wolf §9.5.2)
    nu_0 = 1.0 / (wl_mm * fn)

    # Frequency axis: [0, max_freq]
    freq_max = max_freq_cyc_per_mm if max_freq_cyc_per_mm is not None else 1.05 * nu_0

    step = freq_max / (num_samples - 1)
    frequencies = [i * step for i in range(num_samples)]

    # Build MTF curve
    mtf_curve: list[tuple[float, float]] = []
    for nu in frequencies:
        s = nu / nu_0  # normalised frequency
        mtf_val = _mtf_value(s)
        mtf_curve.append((nu, mtf_val))

    # Find ν at which MTF ≈ 0.50 (linear interpolation between samples)
    mtf_at_50 = _find_freq_at_mtf(mtf_curve, target=0.5)

    return MTFReport(
        cutoff_freq_cyc_per_mm=nu_0,
        mtf_curve=mtf_curve,
        mtf_at_50_percent=mtf_at_50,
        honest_caveat=_HONEST_CAVEAT,
    )


def _find_freq_at_mtf(
    mtf_curve: list[tuple[float, float]],
    target: float,
) -> float:
    """
    Linear-interpolate the spatial frequency at which MTF first drops to *target*.

    Returns the frequency at the first sample pair where the MTF crosses *target*,
    or 0.0 if the MTF never reaches the target value.
    """
    for i in range(len(mtf_curve) - 1):
        nu_lo, m_lo = mtf_curve[i]
        nu_hi, m_hi = mtf_curve[i + 1]
        if m_lo >= target >= m_hi:
            if abs(m_lo - m_hi) < 1e-15:
                return nu_lo
            t = (m_lo - target) / (m_lo - m_hi)
            return nu_lo + t * (nu_hi - nu_lo)
    # MTF never crosses target within the sampled range
    return 0.0
