"""
kerf_cad_core.optics.pixel_mtf — Pixel aperture MTF for imaging sensors.

Public API
----------
compute_pixel_mtf(spec, num_samples=200) -> PixelMtfReport

Theory
------
A finite-sized pixel acts as a rectangular aperture integrator over the
incident irradiance.  For a pixel pitch *p* (mm) and fill-factor *f* ∈(0,1],
the effective aperture width is:

    a = p · f     (mm)

The pixel aperture OTF is the Fourier transform of a rect function of width *a*,
which gives the 1-D MTF along either image axis (Boreman §3.4; Hecht §11.3):

    MTF_pixel(ν) = |sinc(π · a · ν)|
                 = |sin(π · a · ν) / (π · a · ν)|

At DC (ν = 0): MTF = 1.0 exactly.
At the pixel Nyquist frequency ν_N = 1/(2p): the argument is π/2, giving
    MTF_pixel(ν_N) = |sinc(π/2)| = 2/π ≈ 0.6366.

The sampling (Nyquist) limit caps the detectable spatial frequency:
    ν_N = 1 / (2 · p)    [cyc/mm]

Spatial frequencies above ν_N alias — they CANNOT be recovered.  The curve is
sampled from 0 to 2·ν_N to show the alias region (MTF meaningful only for ν ≤ ν_N).

Combining with system MTF
--------------------------
For incoherent imaging, the end-to-end MTF is the product of all independent
MTF contributors (Boreman §2.1):

    MTF_system(ν) = MTF_optical(ν) · MTF_pixel(ν) · MTF_defocus(ν) · ...

This module provides only the pixel-aperture contribution.  Use
`compute_diffraction_mtf` for the optical (diffraction-limited) contribution
and multiply the two curves sample-by-sample at the same frequency axis.

Honest limitations
------------------
PIXEL APERTURE ONLY.  This model captures the spatial-averaging roll-off of
a rectangular pixel aperture only.  The following sensor MTF contributions
are NOT modelled:

  * Silicon carrier diffusion MTF (lateral diffusion of photo-generated
    carriers blurs the response; requires solving the minority-carrier diffusion
    equation as a function of pixel depth and substrate doping — Boreman §3.4,
    Hecht §11.3).
  * Inter-pixel crosstalk (electrical or optical) — requires Monte-Carlo
    carrier-transport or FDTD simulations.
  * Anti-aliasing (optical low-pass) filter MTF — separate measurement.
  * Bayer CFA demosaicing resolution loss — wavelength-dependent, algorithm-dependent.
  * Charge transfer inefficiency in CCD readout.
  * Non-square pixels (requires separate H/V decomposition).
  * 2-D sensor MTF (this model is 1-D; for a square pixel the same sinc
    applies along each axis independently, so 2-D MTF = MTF_x · MTF_y).

FILL FACTOR MODEL.  fill_factor represents the fraction of the pixel pitch that
collects light.  It is assumed to be a flat-topped rect aperture.  Micro-lens
efficiency, CMOS metal-layer shadowing, and QE variations within the pixel are
not modelled.

References
----------
Boreman, G.D. — "Modulation Transfer Function in Optical and Electro-Optical
    Systems", SPIE Press, 2001.  §3.4: Detector MTF, §2.1: cascade MTF product.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017.  §11.3: system MTF.
Holst, G.C. & Lomheim, T.S. — "CMOS/CCD Sensors and Camera Systems", 2007.
    §5.3: pixel MTF including diffusion.

Units: pixel pitch in micrometres (μm), spatial frequencies in cyc/mm.
Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "PIXEL APERTURE ONLY (Boreman §3.4 / Hecht §11.3). "
    "Models sinc roll-off from a rect aperture of width = pixel_pitch × fill_factor. "
    "NOT modelled: silicon carrier-diffusion MTF (minority-carrier lateral spread vs. "
    "pixel depth — Boreman §3.4); inter-pixel electrical/optical crosstalk; "
    "anti-aliasing filter MTF; Bayer CFA demosaicing loss; charge-transfer "
    "inefficiency; non-square pixel (this is 1-D). "
    "Frequencies above the Nyquist limit ν_N = 1/(2p) ALIAS and cannot be recovered — "
    "the MTF curve is shown beyond ν_N for completeness only."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PixelSensorSpec:
    """
    Specification for a single rectangular image sensor pixel.

    Attributes
    ----------
    pixel_pitch_um : float
        Centre-to-centre pixel pitch in micrometres (μm).  Must be > 0.
        E.g. 1.5 for a modern smartphone pixel, 5.5 for a scientific sensor.
    fill_factor : float
        Fraction of the pixel area that actively collects light (0 < ff ≤ 1).
        Modelled as the aperture-to-pitch ratio for a flat-topped rect aperture.
        Default 1.0 (100% fill: the entire pixel pitch is active).
        Back-illuminated CMOS sensors are typically 0.95–1.0; front-illuminated
        CMOS sensors are typically 0.3–0.7 (Holst & Lomheim §5.3).
    """
    pixel_pitch_um: float
    fill_factor: float = 1.0


@dataclass
class PixelMtfReport:
    """
    Pixel aperture MTF result for a sensor with the given pitch and fill factor.

    Attributes
    ----------
    nyquist_freq_cyc_per_mm : float
        Pixel Nyquist frequency ν_N = 1/(2·p) in cyc/mm.
        Spatial frequencies above this limit alias.
    mtf_curve : list[tuple[float, float]]
        Sequence of (ν, MTF(ν)) pairs.  ν is in cyc/mm; MTF ∈ [0, 1].
        Sampled from 0 to 2·ν_N.
    mtf_at_nyquist : float
        MTF value at exactly ν_N (the Nyquist frequency).
        For fill_factor=1: MTF(ν_N) = |sinc(π/2)| = 2/π ≈ 0.6366.
    mtf_at_50_percent_nyquist : float
        MTF value at 0.5·ν_N (half Nyquist).  Useful diagnostic.
    honest_caveat : str
        Plain-English description of model limitations.
    """
    nyquist_freq_cyc_per_mm: float
    mtf_curve: list[tuple[float, float]] = field(default_factory=list)
    mtf_at_nyquist: float = 0.0
    mtf_at_50_percent_nyquist: float = 0.0
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "nyquist_freq_cyc_per_mm": self.nyquist_freq_cyc_per_mm,
            "mtf_curve": [list(pt) for pt in self.mtf_curve],
            "mtf_at_nyquist": self.mtf_at_nyquist,
            "mtf_at_50_percent_nyquist": self.mtf_at_50_percent_nyquist,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def _sinc_mtf(nu: float, aperture_mm: float) -> float:
    """
    Compute pixel aperture MTF = |sinc(π · aperture_mm · ν)|.

    The sinc here is the unnormalised form:
        sinc(x) = sin(x) / x   for x ≠ 0,   sinc(0) = 1

    so that:
        MTF_pixel(ν) = |sin(π · a · ν) / (π · a · ν)|

    At ν = 0 this is defined to be 1.0 (limit).

    Parameters
    ----------
    nu : float
        Spatial frequency (cyc/mm).
    aperture_mm : float
        Pixel aperture width a = pitch · fill_factor (mm).

    Returns
    -------
    float in [0, 1].
    """
    if nu <= 0.0 or aperture_mm <= 0.0:
        return 1.0
    x = math.pi * aperture_mm * nu
    if abs(x) < 1e-14:
        return 1.0
    return abs(math.sin(x) / x)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_pixel_mtf(
    spec: PixelSensorSpec,
    num_samples: int = 200,
) -> "PixelMtfReport | dict":
    """
    Compute the pixel aperture Modulation Transfer Function MTF(ν) for a sensor
    described by *spec*.

    Parameters
    ----------
    spec : PixelSensorSpec
        Pixel pitch (μm) and fill factor.
    num_samples : int
        Number of equally-spaced frequency samples in [0, 2·ν_N].
        Default 200.  Must be ≥ 2.

    Returns
    -------
    PixelMtfReport on success.
    dict {"ok": False, "reason": "..."} on input error.

    Analytic oracles
    ----------------
    p = 1.5 μm, ff = 1.0:
        ν_N = 1 / (2 × 0.0015 mm) = 333.333 cyc/mm
        a = 0.0015 mm
        MTF(0)    = 1.0 exactly
        MTF(ν_N)  = |sinc(π · 0.0015 · 333.333)| = |sinc(π/2)| = 2/π ≈ 0.63662

    p = 5.5 μm, ff = 0.7:
        a = 0.0055 × 0.7 = 0.00385 mm
        ν_N = 90.909 cyc/mm
        MTF(ν_N) = |sinc(π · 0.00385 · 90.909)| = |sinc(0.35π)| > 2/π
        (smaller aperture → slower roll-off → higher MTF at Nyquist)

    References
    ----------
    Boreman, G.D. — "Modulation Transfer Function in Optical and Electro-Optical
        Systems", SPIE Press, 2001.  §3.4, §2.1.
    Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017.  §11.3.
    """
    # --- Input validation ---
    if not isinstance(spec, PixelSensorSpec):
        return {"ok": False, "reason": "spec must be a PixelSensorSpec instance"}

    try:
        pitch_um = float(spec.pixel_pitch_um)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "pixel_pitch_um must be a number"}
    if not math.isfinite(pitch_um) or pitch_um <= 0.0:
        return {"ok": False, "reason": "pixel_pitch_um must be > 0"}

    try:
        ff = float(spec.fill_factor)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "fill_factor must be a number"}
    if not math.isfinite(ff) or ff <= 0.0 or ff > 1.0:
        return {"ok": False, "reason": "fill_factor must be in (0, 1]"}

    if not isinstance(num_samples, int) or num_samples < 2:
        return {"ok": False, "reason": "num_samples must be an integer >= 2"}

    # --- Core calculation ---
    # Convert pitch from μm to mm
    pitch_mm = pitch_um * 1.0e-3

    # Effective aperture width (mm)
    aperture_mm = pitch_mm * ff

    # Nyquist frequency: ν_N = 1 / (2 · pitch)
    nu_nyquist = 1.0 / (2.0 * pitch_mm)

    # Sample from 0 to 2·ν_N
    freq_max = 2.0 * nu_nyquist
    step = freq_max / (num_samples - 1)
    frequencies = [i * step for i in range(num_samples)]

    # Build MTF curve
    mtf_curve: list[tuple[float, float]] = []
    for nu in frequencies:
        mtf_val = _sinc_mtf(nu, aperture_mm)
        mtf_curve.append((nu, mtf_val))

    # MTF at Nyquist
    mtf_at_nyquist = _sinc_mtf(nu_nyquist, aperture_mm)

    # MTF at 50% Nyquist
    mtf_at_half_nyquist = _sinc_mtf(0.5 * nu_nyquist, aperture_mm)

    return PixelMtfReport(
        nyquist_freq_cyc_per_mm=nu_nyquist,
        mtf_curve=mtf_curve,
        mtf_at_nyquist=mtf_at_nyquist,
        mtf_at_50_percent_nyquist=mtf_at_half_nyquist,
        honest_caveat=_HONEST_CAVEAT,
    )


def combine_mtf_curves(
    optical_mtf: list[tuple[float, float]],
    pixel_mtf: list[tuple[float, float]],
) -> "list[tuple[float, float]] | dict":
    """
    Combine an optical MTF curve and a pixel aperture MTF curve by pointwise
    multiplication (incoherent cascade, Boreman §2.1):

        MTF_total(ν) = MTF_optical(ν) · MTF_pixel(ν)

    The two curves must have the same frequency axis (same length and same
    frequency values at each index).

    Parameters
    ----------
    optical_mtf : list[tuple[float, float]]
        (ν, MTF_optical(ν)) pairs from compute_diffraction_mtf or similar.
    pixel_mtf : list[tuple[float, float]]
        (ν, MTF_pixel(ν)) pairs from compute_pixel_mtf.

    Returns
    -------
    list[tuple[float, float]] — combined MTF curve on the same frequency axis.
    dict {"ok": False, "reason": "..."} on input error.

    Note
    ----
    The caller is responsible for ensuring the curves share the same frequency
    axis.  If the axes differ, interpolate one curve to match the other before
    combining.  This helper performs a strict element-wise product and will
    return an error if the two lists have different lengths.
    """
    if not isinstance(optical_mtf, list) or not isinstance(pixel_mtf, list):
        return {"ok": False, "reason": "both inputs must be lists of (freq, mtf) tuples"}
    if len(optical_mtf) != len(pixel_mtf):
        return {
            "ok": False,
            "reason": (
                f"optical_mtf has {len(optical_mtf)} points but pixel_mtf has "
                f"{len(pixel_mtf)} — they must share the same frequency axis"
            ),
        }
    if len(optical_mtf) == 0:
        return {"ok": False, "reason": "MTF curves must be non-empty"}

    combined: list[tuple[float, float]] = []
    for (nu_o, m_o), (nu_p, m_p) in zip(optical_mtf, pixel_mtf):
        combined.append((nu_o, m_o * m_p))
    return combined
