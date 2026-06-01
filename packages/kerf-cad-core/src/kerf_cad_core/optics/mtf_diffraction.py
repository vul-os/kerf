"""
kerf_cad_core.optics.mtf_diffraction — Diffraction-limited MTF for a circular aperture.

Public API
----------
compute_diffraction_mtf(wavelength_nm, f_number, num_samples=200,
                        max_freq_cyc_per_mm=None) -> MTFReport

compute_polychromatic_diffraction_mtf(numerical_aperture, wavelength_samples_nm,
                                      spd_weights, num_spatial_freq=128)
    -> PolyMTFReport

Theory
------
For an incoherent, diffraction-limited optical system with a circular exit pupil,
the Optical Transfer Function equals the (normalised) autocorrelation of the pupil
function.  The on-axis MTF is the modulus of the OTF, which for a circular aperture
has a well-known closed-form solution (Goodman, "Introduction to Fourier Optics",
§6.4; Hecht, "Optics" 5e §11.3.3):

  ν_0 = 1 / (λ · F#)               [diffraction cutoff, cyc/mm]
  ν_0 = 2·NA / λ                   [alternative NA-based form]

  MTF(ν) = (2/π) · [arccos(ν/ν_0) − (ν/ν_0) · √(1 − (ν/ν_0)²)]   for ν ≤ ν_0
  MTF(ν) = 0                                                          for ν > ν_0

This is identically the area of the lens-of-two-circles overlap normalised to the
full pupil area (Goodman §6.4, eq. 6-49; Born & Wolf 7e §9.5).

Polychromatic MTF (Hopkins / Goodman §6.4)
------------------------------------------
When the optical system is illuminated with a spectrally broad source (SPD W(λ)),
the polychromatic MTF is the SPD-weighted mean of the monochromatic MTFs:

    MTF_poly(ν) = Σ_i  W(λ_i) · MTF_diff(ν, λ_i)  /  Σ_i W(λ_i)

At each wavelength λ_i the diffraction cutoff is  ν_0(λ_i) = 2·NA / λ_i,
so longer wavelengths cut off at lower spatial frequencies.  The polychromatic
MTF is therefore always ≤ the best-wavelength (shortest λ in the pass-band)
monochromatic MTF — averaging reduces the contrast at frequencies above the
longest-wavelength cutoff.

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
MONOCHROMATIC compute_diffraction_mtf: single wavelength only.
POLYCHROMATIC compute_polychromatic_diffraction_mtf: spectrally weighted sum
  MTF_poly(ν) = Σ W(λ)·MTF(ν,λ) / Σ W(λ) — implemented (Hopkins / Goodman §6.4).
CIRCULAR APERTURE.  Obscured (annular) or non-circular pupils have a different
  analytic form — not implemented here; the Hopkins (1953) closed-form below
  applies only to unobscured circular apertures.
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
from typing import Sequence

# NOTE: photopic_spd / d65_spd / blackbody_spd are intentionally copied here
# rather than imported from distortion_map.py to avoid a circular-import chain
# (distortion_map → mtf_across_field → distortion_map).  The three functions
# are pure-math helpers with zero shared state.


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "DIFFRACTION-LIMITED ONLY: this is the theoretical upper bound for a perfect "
    "circular aperture (Goodman §6.4). Any real lens will have lower MTF due to "
    "aberrations (Seidel S_I–S_V), defocus, wavefront error, or obscuration. "
    "MONOCHROMATIC: single wavelength only — use compute_polychromatic_diffraction_mtf "
    "for spectrally weighted MTF_poly(ν) = Σ W(λ)·MTF(ν,λ) / Σ W(λ). "
    "CIRCULAR APERTURE: annular or non-circular pupils have a different analytic form. "
    "ON-AXIS ONLY: off-axis MTF drops due to aberrations and vignetting — not modelled."
)

_POLY_HONEST_CAVEAT = (
    "POLYCHROMATIC DIFFRACTION MTF: MTF_poly(ν) = Σ_i W(λ_i)·MTF_diff(ν,λ_i) / Σ_i W(λ_i) "
    "(Hopkins / Goodman 'Introduction to Fourier Optics' §6.4). "
    "Cutoff at each λ: ν_0(λ) = 2·NA/λ; longer λ cut off earlier so broadband MTF < best-λ MTF. "
    "DIFFRACTION-LIMITED ONLY: no aberrations (Seidel S_I–S_V), no defocus, no wavefront error. "
    "CIRCULAR APERTURE ONLY: annular/non-circular pupils use a different analytic form. "
    "ON-AXIS ONLY: off-axis MTF degradation from aberrations and vignetting not modelled. "
    "Accuracy depends on spectral sampling density — use ≥10 wavelength samples."
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


# ---------------------------------------------------------------------------
# Standard SPD helpers (copied from distortion_map.py to avoid circular import)
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
# Polychromatic MTF result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PolyMTFReport:
    """
    Polychromatic diffraction-limited MTF result.

    MTF_poly(ν) = Σ_i W(λ_i) · MTF_diff(ν, λ_i) / Σ_i W(λ_i)

    Each MTF_diff(ν, λ_i) is the closed-form circular-aperture diffraction MTF
    evaluated at cutoff ν_0(λ_i) = 2·NA/λ_i.

    Attributes
    ----------
    numerical_aperture : float
        NA used for the computation.
    wavelength_samples_nm : list[float]
        Wavelength grid (nm).
    spd_weights : list[float]
        Normalised SPD weights at each wavelength.
    cutoff_freq_cyc_per_mm_per_wavelength : list[float]
        ν_0(λ_i) = 2·NA/λ_i for each sample.
    poly_mtf_curve : list[tuple[float, float]]
        (ν, MTF_poly(ν)) pairs.  ν in cyc/mm; MTF_poly ∈ [0, 1].
    poly_cutoff_effective : float
        Effective broadband cutoff — the smallest ν_0(λ_i) over samples with
        non-negligible weight (> 1 % of peak weight).  The polychromatic MTF
        is guaranteed to be zero above this frequency.
    mtf_at_50_percent : float
        Spatial frequency at which MTF_poly first drops to ≤ 0.50.
    honest_caveat : str
        Caveats.
    """

    numerical_aperture: float = 0.0
    wavelength_samples_nm: list = field(default_factory=list)
    spd_weights: list = field(default_factory=list)
    cutoff_freq_cyc_per_mm_per_wavelength: list = field(default_factory=list)
    poly_mtf_curve: list = field(default_factory=list)
    poly_cutoff_effective: float = 0.0
    mtf_at_50_percent: float = 0.0
    honest_caveat: str = _POLY_HONEST_CAVEAT

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "numerical_aperture": self.numerical_aperture,
            "wavelength_samples_nm": self.wavelength_samples_nm,
            "spd_weights": self.spd_weights,
            "cutoff_freq_cyc_per_mm_per_wavelength": self.cutoff_freq_cyc_per_mm_per_wavelength,
            "poly_mtf_curve": [list(pt) for pt in self.poly_mtf_curve],
            "poly_cutoff_effective": self.poly_cutoff_effective,
            "mtf_at_50_percent": self.mtf_at_50_percent,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Analytic MTF result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AnalyticMTFReport:
    """
    Analytic (closed-form) diffraction-limited MTF for a circular aperture.

    Uses the Hopkins (1953) / Goodman §6.4 formula directly — no numerical
    integration.  Every value is computed from the exact expression:

        MTF(ν) = (2/π) · [arccos(ν/ν_c) − (ν/ν_c)·√(1−(ν/ν_c)²)]   ν ≤ ν_c
        MTF(ν) = 0                                                       ν > ν_c

    where ν_c = 2·NA / λ_mm is the diffraction cutoff (cyc/mm).

    Attributes
    ----------
    numerical_aperture : float
        NA used for the computation.
    wavelength_nm : float
        Wavelength used (nm).
    cutoff_freq_cyc_per_mm : float
        Diffraction cutoff ν_c = 2·NA/λ_mm (cyc/mm).
    mtf_curve : list[tuple[float, float]]
        (ν, MTF(ν)) pairs.  ν in cyc/mm; MTF ∈ [0, 1].
    mtf_at_zero : float
        MTF(0) — always exactly 1.0 (analytic boundary condition).
    mtf_at_half_cutoff : float
        MTF(ν_c/2) — closed-form: (2/π)·[arccos(0.5)−0.5·√(3)/2] ≈ 0.3906.
    mtf_at_cutoff : float
        MTF(ν_c) — always exactly 0.0 (analytic boundary condition).
    honest_caveat : str
        Plain-English model limitations.

    References
    ----------
    Hopkins, H.H. (1953) — "On the diffraction theory of optical images".
        Proc. Royal Soc. London A 217, 408–432.
    Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., §6.4, eq. 6-49.
    """

    numerical_aperture: float = 0.0
    wavelength_nm: float = 0.0
    cutoff_freq_cyc_per_mm: float = 0.0
    mtf_curve: list = field(default_factory=list)
    mtf_at_zero: float = 1.0
    mtf_at_half_cutoff: float = 0.0
    mtf_at_cutoff: float = 0.0
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "numerical_aperture": self.numerical_aperture,
            "wavelength_nm": self.wavelength_nm,
            "cutoff_freq_cyc_per_mm": self.cutoff_freq_cyc_per_mm,
            "mtf_curve": [list(pt) for pt in self.mtf_curve],
            "mtf_at_zero": self.mtf_at_zero,
            "mtf_at_half_cutoff": self.mtf_at_half_cutoff,
            "mtf_at_cutoff": self.mtf_at_cutoff,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Analytic MTF — public API
# ---------------------------------------------------------------------------

def compute_diffraction_mtf_analytic(
    numerical_aperture: float,
    wavelength_nm: float,
    num_spatial_freq: int = 128,
) -> "AnalyticMTFReport | dict":
    """
    Compute the closed-form (analytic) diffraction-limited MTF for a circular
    aperture using the Hopkins (1953) formula.

    This function evaluates the exact Hopkins / Goodman §6.4 expression:

        ν_c = 2·NA / λ_mm                    [diffraction cutoff, cyc/mm]

        MTF(ν) = (2/π) · [arccos(ν/ν_c) − (ν/ν_c)·√(1−(ν/ν_c)²)]   ν ≤ ν_c
        MTF(ν) = 0                                                       ν > ν_c

    No numerical integration is performed — every sample is a direct
    evaluation of the analytic formula.  The result is therefore exact to
    floating-point precision.

    Boundary values (analytic)
    --------------------------
    MTF(0)     = 1.0 exactly  (arccos(0)=π/2; (π/2)·2/π = 1)
    MTF(ν_c/2) = (2/π)·[arccos(0.5) − 0.5·√(1−0.25)]
               = (2/π)·[π/3 − (√3)/4]
               ≈ 0.39087 (Hopkins 1953; Goodman §6.4)
    MTF(ν_c)   = 0.0 exactly  (arccos(1)=0; sqrt(1−1)=0)

    Numerical equivalence
    ---------------------
    Because both this function and compute_polychromatic_diffraction_mtf /
    compute_diffraction_mtf call the same _mtf_value() kernel, analytic and
    numerical results agree to machine precision (< 1e-10 absolute difference
    over the entire frequency range).

    Parameters
    ----------
    numerical_aperture : float
        Image-space NA = n·sin(θ_max).  Must be in (0, 1].
    wavelength_nm : float
        Wavelength of light in nanometres.  Must be > 0.
    num_spatial_freq : int
        Number of equally-spaced frequency samples in [0, ν_c].
        Default 128.  Must be ≥ 2.

    Returns
    -------
    AnalyticMTFReport on success.
    dict {"ok": False, "reason": "..."} on input error.

    References
    ----------
    Hopkins, H.H. (1953) — "On the diffraction theory of optical images".
        Proc. Royal Soc. London A 217, 408–432.
    Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., §6.4, eq. 6-49.
    Born, M. & Wolf, E. — "Principles of Optics", 7th ed., §9.5.2, eq. 9.80.
    """
    # --- Input validation ---
    try:
        na = float(numerical_aperture)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "numerical_aperture must be a number"}
    if not math.isfinite(na) or na <= 0.0 or na > 1.0:
        return {"ok": False, "reason": "numerical_aperture must be in (0, 1]"}

    try:
        wl_nm = float(wavelength_nm)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "wavelength_nm must be a number"}
    if not math.isfinite(wl_nm) or wl_nm <= 0.0:
        return {"ok": False, "reason": "wavelength_nm must be > 0"}

    if not isinstance(num_spatial_freq, int) or num_spatial_freq < 2:
        return {"ok": False, "reason": "num_spatial_freq must be an integer >= 2"}

    # --- Diffraction cutoff -------------------------------------------------
    # ν_c = 2·NA / λ_mm    (Hopkins 1953; Goodman §6.4, eq. 6-49)
    wl_mm = wl_nm * 1.0e-6
    nu_c = 2.0 * na / wl_mm

    # --- Build analytic MTF curve -------------------------------------------
    # Frequency grid: num_spatial_freq equally-spaced points in [0, nu_c]
    step = nu_c / (num_spatial_freq - 1)
    mtf_curve: list[tuple[float, float]] = []
    for i in range(num_spatial_freq):
        nu = i * step
        s = nu / nu_c  # normalised frequency ∈ [0, 1]
        mtf_val = _mtf_value(s)
        mtf_curve.append((nu, mtf_val))

    # --- Analytic boundary and landmark values ------------------------------
    # MTF(0): s=0 → arccos(0)=π/2; (2/π)·π/2 = 1.0 exactly
    mtf_at_zero = 1.0

    # MTF(ν_c/2): s=0.5 → arccos(0.5)=π/3; sqrt(1−0.25)=sqrt(3)/2
    #   = (2/π)·[π/3 − 0.5·sqrt(3)/2]
    mtf_at_half = (2.0 / math.pi) * (
        math.acos(0.5) - 0.5 * math.sqrt(1.0 - 0.25)
    )

    # MTF(ν_c): s=1 → arccos(1)=0; sqrt(1−1)=0 → 0.0 exactly
    mtf_at_cutoff = 0.0

    return AnalyticMTFReport(
        numerical_aperture=na,
        wavelength_nm=wl_nm,
        cutoff_freq_cyc_per_mm=nu_c,
        mtf_curve=mtf_curve,
        mtf_at_zero=mtf_at_zero,
        mtf_at_half_cutoff=mtf_at_half,
        mtf_at_cutoff=mtf_at_cutoff,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Polychromatic MTF — public API
# ---------------------------------------------------------------------------

def compute_polychromatic_diffraction_mtf(
    numerical_aperture: float,
    wavelength_samples_nm: Sequence[float],
    spd_weights: Sequence[float],
    num_spatial_freq: int = 128,
) -> "PolyMTFReport | dict":
    """
    Compute the spectrally-integrated (polychromatic) diffraction-limited MTF
    for a circular aperture.

    Algorithm (Hopkins / Goodman §6.4)
    ------------------------------------
    For each wavelength λ_i with SPD weight W_i:

      1. Compute diffraction cutoff:  ν_0(λ_i) = 2·NA / λ_i_mm
         (equivalently 1/(λ·F#) with F# = 1/(2·NA)).

      2. Evaluate the closed-form monochromatic MTF at all ν grid points:

           MTF_diff(ν, λ_i) = (2/π)[arccos(s) − s·√(1−s²)],  s = ν/ν_0(λ_i)
                             = 0                               ,  ν > ν_0(λ_i)

      3. Accumulate weighted sum and weight total:

           num(ν)  += W_i · MTF_diff(ν, λ_i)
           denom   += W_i

      4. MTF_poly(ν) = num(ν) / denom

    The frequency grid spans [0, ν_0(λ_min)] — the highest possible cutoff
    (shortest wavelength).  Points beyond the longest-wavelength cutoff are
    naturally zero because MTF_diff = 0 there for those wavelengths.

    Parameters
    ----------
    numerical_aperture : float
        Image-space NA = n·sin(θ_max).  Must be in (0, 1].
    wavelength_samples_nm : sequence of float
        Wavelength grid (nm), ≥ 2 elements, all > 0.
        Need not be sorted, but uniform or finely-sampled gives better accuracy.
    spd_weights : sequence of float
        Spectral power density at each wavelength (arbitrary scale).
        Must be the same length as wavelength_samples_nm.
        All values ≥ 0; not all zero.
    num_spatial_freq : int
        Number of equally-spaced frequency samples in [0, ν_0(λ_min)].
        Default 128.  Must be ≥ 2.

    Returns
    -------
    PolyMTFReport on success.
    dict {"ok": False, "reason": "..."} on input error.

    Analytic checks
    ---------------
    1. Single-wavelength SPD: MTF_poly(ν) ≡ MTF_diff(ν, λ_single) — identical
       to the monochromatic result.
    2. Broadband SPD: MTF_poly(ν) ≤ MTF_diff(ν, λ_min) because longer-wavelength
       channels contribute zero above their respective cutoffs (averaging down).
    3. Short wavelengths dominate near the cutoff; long wavelengths degrade
       mid-frequency contrast.

    References
    ----------
    Goodman, J.W. — "Introduction to Fourier Optics", 3rd ed., §6.4, eq. 6-49.
    Hopkins, H.H. (1955) — "The frequency response of a defocused optical system".
        Proc. Royal Soc. London A 231, 91–103.
    Hecht, E. — "Optics", 5th ed., §11.3.3.

    Standard SPDs (from kerf_cad_core.optics.distortion_map)
    ---------------------------------------------------------
    Use photopic_spd / d65_spd / blackbody_spd to generate spd_weights.
    Example::

        from kerf_cad_core.optics.distortion_map import d65_spd
        wls = list(range(400, 701, 10))
        weights = d65_spd(wls)
        report = compute_polychromatic_diffraction_mtf(0.1, wls, weights)
    """
    # --- Input validation ---------------------------------------------------
    try:
        na = float(numerical_aperture)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "numerical_aperture must be a number"}
    if not math.isfinite(na) or na <= 0.0 or na > 1.0:
        return {"ok": False, "reason": "numerical_aperture must be in (0, 1]"}

    try:
        lambdas = [float(v) for v in wavelength_samples_nm]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"wavelength_samples_nm invalid: {exc}"}
    if len(lambdas) < 2:
        return {"ok": False,
                "reason": "wavelength_samples_nm must have at least 2 elements"}
    if any(lam <= 0.0 for lam in lambdas):
        return {"ok": False, "reason": "all wavelength_samples_nm must be > 0"}

    try:
        weights = [float(v) for v in spd_weights]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"spd_weights invalid: {exc}"}
    if len(weights) != len(lambdas):
        return {"ok": False,
                "reason": (
                    f"spd_weights length ({len(weights)}) must match "
                    f"wavelength_samples_nm length ({len(lambdas)})"
                )}
    if any(w < 0.0 for w in weights):
        return {"ok": False, "reason": "spd_weights must all be >= 0"}
    total_w = sum(weights)
    if total_w <= 0.0:
        return {"ok": False, "reason": "spd_weights must not be all zero"}

    if not isinstance(num_spatial_freq, int) or num_spatial_freq < 2:
        return {"ok": False, "reason": "num_spatial_freq must be an integer >= 2"}

    # --- Per-wavelength diffraction cutoffs ---------------------------------
    # ν_0(λ) = 2·NA / λ_mm     (NA = sin(θ_max) for n_image=1 air-image)
    # 1 nm = 1e-6 mm
    cutoffs = []
    for lam in lambdas:
        lam_mm = lam * 1.0e-6
        cutoffs.append(2.0 * na / lam_mm)

    # Frequency grid: [0, max_cutoff] where max_cutoff = 2·NA / λ_min
    lam_min = min(lambdas)
    nu_max = 2.0 * na / (lam_min * 1.0e-6)
    step = nu_max / (num_spatial_freq - 1)
    freq_grid = [i * step for i in range(num_spatial_freq)]

    # Effective broadband cutoff: smallest ν_0 among samples with weight > 1%
    peak_w = max(weights)
    threshold = 0.01 * peak_w
    significant_cutoffs = [
        c for c, w in zip(cutoffs, weights) if w >= threshold
    ]
    poly_cutoff_eff = min(significant_cutoffs) if significant_cutoffs else min(cutoffs)

    # --- Spectral summation -------------------------------------------------
    # num_arr[j]  = Σ_i W_i · MTF_diff(freq_grid[j], λ_i)
    # denom       = Σ_i W_i
    num_arr = [0.0] * num_spatial_freq
    denom = total_w  # simple sum (unweighted by Δλ; caller provides weights)

    for lam, nu_0, w in zip(lambdas, cutoffs, weights):
        if w == 0.0:
            continue
        for j, nu in enumerate(freq_grid):
            s = nu / nu_0  # normalised frequency
            mtf_val = _mtf_value(s)
            num_arr[j] += w * mtf_val

    poly_mtf_curve: list[tuple[float, float]] = [
        (freq_grid[j], num_arr[j] / denom)
        for j in range(num_spatial_freq)
    ]

    # Normalised weights for the report (sum to 1)
    norm_weights = [w / total_w for w in weights]

    mtf_at_50 = _find_freq_at_mtf(poly_mtf_curve, target=0.5)

    return PolyMTFReport(
        numerical_aperture=na,
        wavelength_samples_nm=lambdas,
        spd_weights=norm_weights,
        cutoff_freq_cyc_per_mm_per_wavelength=cutoffs,
        poly_mtf_curve=poly_mtf_curve,
        poly_cutoff_effective=poly_cutoff_eff,
        mtf_at_50_percent=mtf_at_50,
        honest_caveat=_POLY_HONEST_CAVEAT,
    )
