"""
kerf_cad_core.optics.piston_tip_tilt — Piston/Tip/Tilt/Defocus wavefront analysis.

Extracts the four rigid-body / focus alignment Zernike components from a sampled
wavefront W(ρ,θ) and reports each in units of waves at the specified wavelength.

These are the most common alignment-quality metrics in optical-shop testing:

  Z₁ (j=1)  piston   — global OPD offset; indicates axial path-length difference
  Z₂ (j=2)  tip      — wavefront tilt about y-axis (x-tilt); 2ρ cosθ term
  Z₃ (j=3)  tilt     — wavefront tilt about x-axis (y-tilt); 2ρ sinθ term
  Z₄ (j=4)  defocus  — longitudinal focus error; √3(2ρ²−1) term

Rigid-body alignment correction removes exactly these four terms before measuring
higher-order optical quality.  This module reuses the existing fit_zernike_wavefront
engine and filters down to the first four coefficients.

Public API
----------
PistonTipTiltReport
    Dataclass with piston_waves, tip_waves, tilt_waves, defocus_waves,
    residual_rms_waves, dominant_misalignment, honest_caveat.

analyze_wavefront_alignment(wavefront_samples, wavelength_nm) -> PistonTipTiltReport
    Fit Zernike j=1..4 to the sampled wavefront; divide by wavelength_nm to
    express in waves; classify dominant misalignment.

References
----------
Hecht, E. (2017) "Optics", 5th ed., §11.3.
Born, M. & Wolf, E. (1999) "Principles of Optics", 7th ed., §9.2.
Wyant, J.C. & Creath, K. (1992) "Basic wavefront aberration theory for optical
    testing", Applied Optics and Optical Engineering XI, ch.1.
Noll, R.J. (1976) "Zernike polynomials and atmospheric turbulence",
    J. Opt. Soc. Am. 66, 207-211.

Honest scope
------------
- Circular unit-disk pupil only (ρ ∈ [0,1], no central obscuration, no elliptical aperture).
- Alignment analysis only: fits Z₁..Z₄ and reports them.  Correcting these four
  terms removes rigid-body misalignment (piston, tip, tilt, defocus) but does NOT
  remove higher-order optical aberrations (coma, astigmatism, spherical, etc.).
- W input must be in nanometres (nm); wavelength_nm is the reference wavelength.
- Requires ≥ 4 samples (under-determined system raises ValueError).
- The Zernike fit uses least-squares (numpy.linalg.lstsq); orthonormal Noll basis.

Author: imranparuk
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from kerf_cad_core.optics.zernike_fit import fit_zernike_wavefront

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DOMINANT_NAMES: list[str] = ["piston", "tip", "tilt", "defocus"]

_HONEST_CAVEAT = (
    "Alignment analysis scope: fits Noll Z₁..Z₄ (piston, tip, tilt, defocus) only. "
    "Assumes a circular unit-disk pupil (ρ ∈ [0,1]); no central obscuration or "
    "elliptical aperture. Corrects rigid-body alignment errors (piston = axial OPD "
    "offset, tip/tilt = wavefront tilt, defocus = longitudinal focus shift); does "
    "NOT correct higher-order aberrations (coma Z₇/Z₈, astigmatism Z₅/Z₆, spherical "
    "Z₁₁, etc.) which require the full Zernike decomposition via fit_zernike_wavefront. "
    "Input W must be in nanometres; wavelength_nm is the reference wavelength at which "
    "waves are reported. Dominant misalignment = argmax(|c_j|) for j=1..4; 'none' "
    "when all four coefficients are below 0.001 waves; 'higher_order' not possible "
    "from this 4-term analysis — use fit_zernike_wavefront for residual breakdown. "
    "References: Hecht §11.3; Born & Wolf §9.2; Wyant & Creath (1992); Noll (1976)."
)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class PistonTipTiltReport:
    """
    Result of piston/tip/tilt/defocus alignment analysis on a sampled wavefront.

    All wave values are in units of waves at wavelength_nm.

    Attributes
    ----------
    piston_waves : float
        Zernike Z₁ (j=1) coefficient in waves.  Represents a constant OPD
        offset (axial path-length difference) across the pupil.

    tip_waves : float
        Zernike Z₂ (j=2) coefficient in waves.  Wavefront tilt about the y-axis
        (x-direction tilt); Z₂ = 2ρ cosθ (Noll 1976).

    tilt_waves : float
        Zernike Z₃ (j=3) coefficient in waves.  Wavefront tilt about the x-axis
        (y-direction tilt); Z₃ = 2ρ sinθ (Noll 1976).

    defocus_waves : float
        Zernike Z₄ (j=4) coefficient in waves.  Longitudinal focus error;
        Z₄ = √3(2ρ²−1) (Noll 1976).

    residual_rms_waves : float
        RMS of (W_measured − W_fitted_4_terms) in waves.  Non-zero residual
        indicates higher-order aberration content beyond Z₁..Z₄.

    dominant_misalignment : str
        Which of the four alignment terms has the largest |coefficient| in waves.
        One of: "piston", "tip", "tilt", "defocus", "none" (all < 0.001 waves).
        "higher_order" is NOT returned by this analysis; use fit_zernike_wavefront
        to characterise higher-order residuals.

    honest_caveat : str
        Plain-text scope limitations.
    """

    piston_waves: float = 0.0
    tip_waves: float = 0.0
    tilt_waves: float = 0.0
    defocus_waves: float = 0.0
    residual_rms_waves: float = 0.0
    dominant_misalignment: str = "none"
    honest_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "piston_waves": self.piston_waves,
            "tip_waves": self.tip_waves,
            "tilt_waves": self.tilt_waves,
            "defocus_waves": self.defocus_waves,
            "residual_rms_waves": self.residual_rms_waves,
            "dominant_misalignment": self.dominant_misalignment,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_wavefront_alignment(
    wavefront_samples: Sequence[tuple[float, float, float]],
    wavelength_nm: float,
) -> PistonTipTiltReport:
    """
    Extract piston (Z₁), tip (Z₂), tilt (Z₃), and defocus (Z₄) Zernike
    components from a sampled wavefront.

    Parameters
    ----------
    wavefront_samples : sequence of (rho, theta, W_nm)
        Each element is a 3-tuple:
          rho   : float in [0, 1] — normalised pupil radius.
          theta : float in radians — pupil angle.
          W_nm  : float — wavefront OPD at this point in nanometres (nm).
        At least 4 samples required (minimum for a 4-term fit).

    wavelength_nm : float
        Reference wavelength in nanometres.  All wave values in the returned
        report are divided by this value: waves = coefficient_nm / wavelength_nm.
        Must be > 0.

    Returns
    -------
    PistonTipTiltReport

    Raises
    ------
    ValueError
        If wavelength_nm <= 0.
        If fewer than 4 samples are provided.
        If samples are malformed (propagated from fit_zernike_wavefront).
    TypeError
        If samples contain non-numeric values.
    """
    if wavelength_nm <= 0.0:
        raise ValueError(
            f"wavelength_nm must be positive, got {wavelength_nm}"
        )

    # Fit first 4 Noll-ordered Zernike terms only.
    # fit_zernike_wavefront raises ValueError for under-determined system (<4 samples).
    fit_report = fit_zernike_wavefront(list(wavefront_samples), num_terms=4)

    # Extract and convert from nm to waves.
    coeffs = fit_report.coefficients  # [c1, c2, c3, c4] in nm
    piston_waves = coeffs[0] / wavelength_nm
    tip_waves = coeffs[1] / wavelength_nm
    tilt_waves = coeffs[2] / wavelength_nm
    defocus_waves = coeffs[3] / wavelength_nm
    residual_rms_waves = fit_report.rms_residual_waves / wavelength_nm

    # Classify dominant misalignment: argmax(|c_j|) for j=1..4.
    abs_waves = [abs(piston_waves), abs(tip_waves), abs(tilt_waves), abs(defocus_waves)]
    max_abs = max(abs_waves)

    _THRESHOLD = 1e-3  # 0.001 waves — below this, call it "none"
    if max_abs < _THRESHOLD:
        dominant = "none"
    else:
        dominant = _DOMINANT_NAMES[abs_waves.index(max_abs)]

    return PistonTipTiltReport(
        piston_waves=piston_waves,
        tip_waves=tip_waves,
        tilt_waves=tilt_waves,
        defocus_waves=defocus_waves,
        residual_rms_waves=residual_rms_waves,
        dominant_misalignment=dominant,
        honest_caveat=_HONEST_CAVEAT,
    )
