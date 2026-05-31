"""
kerf_cad_core.optics.zernike_fit — Zernike polynomial wavefront fitting.

Fits the first 15 Noll-ordered Zernike polynomial coefficients to a sampled
wavefront W(ρ, θ) over a unit-disk (circular) pupil using least-squares
regression (numpy.linalg.lstsq).

Public API
----------
ZernikeFitReport
    Dataclass holding coefficients, RMS residual, dominant aberration name,
    coefficient names, and an honest caveat string.

fit_zernike_wavefront(samples, num_terms=15) -> ZernikeFitReport
    Fit Noll-ordered Zernike polynomials Z_1..Z_num_terms to wavefront
    samples.  Returns a ZernikeFitReport.

Noll (1976) ordering and formulas
-----------------------------------
Index j (1-based), (n, m) radial/azimuthal degree, and formula.

  j=1  (n=0, m=0)   Z_1  = 1                                          [piston]
  j=2  (n=1, m=+1)  Z_2  = 2ρ cos θ                                   [tip]
  j=3  (n=1, m=-1)  Z_3  = 2ρ sin θ                                   [tilt]
  j=4  (n=2, m=0)   Z_4  = √3 (2ρ²−1)                                 [defocus]
  j=5  (n=2, m=-2)  Z_5  = √6 ρ² sin 2θ                               [astig_45]
  j=6  (n=2, m=+2)  Z_6  = √6 ρ² cos 2θ                               [astig_0]
  j=7  (n=3, m=-1)  Z_7  = √8 (3ρ³−2ρ) sin θ                         [coma_y]
  j=8  (n=3, m=+1)  Z_8  = √8 (3ρ³−2ρ) cos θ                         [coma_x]
  j=9  (n=3, m=-3)  Z_9  = √8 ρ³ sin 3θ                               [trefoil_y]
  j=10 (n=3, m=+3)  Z_10 = √8 ρ³ cos 3θ                               [trefoil_x]
  j=11 (n=4, m=0)   Z_11 = √5 (6ρ⁴−6ρ²+1)                            [spherical]
  j=12 (n=4, m=+2)  Z_12 = √10 (4ρ⁴−3ρ²) cos 2θ                      [secondary_astig_0]
  j=13 (n=4, m=-2)  Z_13 = √10 (4ρ⁴−3ρ²) sin 2θ                      [secondary_astig_45]
  j=14 (n=4, m=+4)  Z_14 = √10 ρ⁴ cos 4θ                              [tetrafoil_x]
  j=15 (n=4, m=-4)  Z_15 = √10 ρ⁴ sin 4θ                              [tetrafoil_y]

Normalisation: Noll (1976) uses orthonormal polynomials over the unit disk
such that ∫∫ Z_j² dA = π (integral over the unit-disk area π).

In the orthonormal convention used here (from Noll 1976 eq. 1-2):
  ∫∫_disk Z_j Z_k dA = π δ_{jk}

So the norm factor N_n for radial degree n, azimuthal m is:
  N_n = √(n+1)       for m = 0
  N_n = √(2(n+1))    for m ≠ 0

This matches the prefactors above (see Noll 1976 Table 1).

Honest scope
------------
- Unit-disk pupil only; no pupil stretching or obscuration modelling.
- First 15 terms (Noll j=1..15); higher-order fitting requires extending
  _ZERNIKE_FUNCS.
- Requires ≥ num_terms samples; raises ValueError for under-determined system.
- Least-squares solution: numpy.linalg.lstsq (QR factorisation + SVD fallback).
- Dominant aberration = argmax(|c_j|) for j ≥ 2 (piston excluded).
- RMS residual in the same units as W (typically waves or metres).
- Born & Wolf §9.2 uses a different normalisation; the present module
  follows Noll (1976) "Zernike polynomials and atmospheric turbulence".

References
----------
Noll, R.J. (1976) "Zernike polynomials and atmospheric turbulence",
    J. Opt. Soc. Am. 66, 207-211.
Born, M. & Wolf, E. (1999) "Principles of Optics", 7th ed., §9.2.
Wyant, J.C. & Creath, K. (1992) "Basic wavefront aberration theory for optical
    testing", Applied Optics and Optical Engineering XI, ch. 1.

Units: ρ ∈ [0, 1] (normalised pupil radius), θ ∈ [0, 2π) (rad).
       W in waves (preferred) or any consistent unit.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Noll-ordered Zernike basis functions  (j = 1 .. 15)
# ---------------------------------------------------------------------------

def _z01(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_1 = 1  (piston)."""
    return np.ones_like(rho)


def _z02(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_2 = 2 ρ cos θ  (tip, x-tilt)."""
    return 2.0 * rho * np.cos(theta)


def _z03(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_3 = 2 ρ sin θ  (tilt, y-tilt)."""
    return 2.0 * rho * np.sin(theta)


def _z04(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_4 = √3 (2ρ²−1)  (defocus)."""
    return math.sqrt(3.0) * (2.0 * rho ** 2 - 1.0)


def _z05(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_5 = √6 ρ² sin 2θ  (oblique astigmatism, 45°)."""
    return math.sqrt(6.0) * rho ** 2 * np.sin(2.0 * theta)


def _z06(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_6 = √6 ρ² cos 2θ  (vertical astigmatism, 0°)."""
    return math.sqrt(6.0) * rho ** 2 * np.cos(2.0 * theta)


def _z07(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_7 = √8 (3ρ³−2ρ) sin θ  (vertical coma)."""
    return math.sqrt(8.0) * (3.0 * rho ** 3 - 2.0 * rho) * np.sin(theta)


def _z08(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_8 = √8 (3ρ³−2ρ) cos θ  (horizontal coma)."""
    return math.sqrt(8.0) * (3.0 * rho ** 3 - 2.0 * rho) * np.cos(theta)


def _z09(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_9 = √8 ρ³ sin 3θ  (oblique trefoil)."""
    return math.sqrt(8.0) * rho ** 3 * np.sin(3.0 * theta)


def _z10(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_10 = √8 ρ³ cos 3θ  (vertical trefoil)."""
    return math.sqrt(8.0) * rho ** 3 * np.cos(3.0 * theta)


def _z11(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_11 = √5 (6ρ⁴−6ρ²+1)  (primary spherical aberration)."""
    return math.sqrt(5.0) * (6.0 * rho ** 4 - 6.0 * rho ** 2 + 1.0)


def _z12(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_12 = √10 (4ρ⁴−3ρ²) cos 2θ  (secondary astigmatism, 0°)."""
    return math.sqrt(10.0) * (4.0 * rho ** 4 - 3.0 * rho ** 2) * np.cos(2.0 * theta)


def _z13(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_13 = √10 (4ρ⁴−3ρ²) sin 2θ  (secondary astigmatism, 45°)."""
    return math.sqrt(10.0) * (4.0 * rho ** 4 - 3.0 * rho ** 2) * np.sin(2.0 * theta)


def _z14(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_14 = √10 ρ⁴ cos 4θ  (vertical tetrafoil)."""
    return math.sqrt(10.0) * rho ** 4 * np.cos(4.0 * theta)


def _z15(rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Z_15 = √10 ρ⁴ sin 4θ  (oblique tetrafoil)."""
    return math.sqrt(10.0) * rho ** 4 * np.sin(4.0 * theta)


# Ordered list of (function, human name) for j = 1 .. 15
_ZERNIKE_FUNCS: list[tuple] = [
    (_z01, "piston"),
    (_z02, "tip"),
    (_z03, "tilt"),
    (_z04, "defocus"),
    (_z05, "astigmatism_45"),
    (_z06, "astigmatism_0"),
    (_z07, "coma_y"),
    (_z08, "coma_x"),
    (_z09, "trefoil_y"),
    (_z10, "trefoil_x"),
    (_z11, "spherical"),
    (_z12, "secondary_astig_0"),
    (_z13, "secondary_astig_45"),
    (_z14, "tetrafoil_x"),
    (_z15, "tetrafoil_y"),
]

_MAX_TERMS = len(_ZERNIKE_FUNCS)  # 15


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ZernikeFitReport:
    """
    Result of fitting Zernike polynomial coefficients to a sampled wavefront.

    Attributes
    ----------
    coefficients : list[float]
        Fitted Zernike coefficients [c_1, c_2, ..., c_N] in Noll order.
        c_1 is the piston term; c_4 is defocus; c_11 is primary spherical.
        Units: same as the W values passed to fit_zernike_wavefront.
    rms_residual_waves : float
        RMS of (W_measured − W_fitted) across all sample points.
        If input W is in waves, this is the fit residual in waves.
    dominant_aberration : str
        Name of the Zernike term with the largest |c_j| for j >= 2
        (piston j=1 excluded as it is a global phase offset and not an
        optical aberration).
    coefficient_names : list[str]
        Human-readable names for each coefficient in the same order as
        `coefficients`.  Example: ["piston", "tip", "tilt", "defocus", ...].
    honest_caveat : str
        Plain-text description of limitations of this fit.
    """

    coefficients: list[float] = field(default_factory=list)
    rms_residual_waves: float = 0.0
    dominant_aberration: str = "piston"
    coefficient_names: list[str] = field(default_factory=list)
    honest_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "coefficients": self.coefficients,
            "rms_residual_waves": self.rms_residual_waves,
            "dominant_aberration": self.dominant_aberration,
            "coefficient_names": self.coefficient_names,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Public fit function
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Zernike fit scope: first 15 Noll-ordered terms only (j=1..15); "
    "higher-order aberrations (j>15) are aliased into the residual. "
    "Unit-disk pupil assumed; no central obscuration or elliptical aperture. "
    "Dominant aberration excludes piston (j=1) as it is a global phase offset. "
    "RMS residual in the same units as input W. "
    "References: Noll (1976) J. Opt. Soc. Am. 66 207-211; "
    "Born & Wolf (1999) Principles of Optics §9.2; "
    "Wyant & Creath (1992) Applied Optics and Optical Engineering XI ch.1."
)


def fit_zernike_wavefront(
    samples: Sequence[tuple[float, float, float]],
    num_terms: int = 15,
) -> ZernikeFitReport:
    """
    Fit Zernike polynomial coefficients to sampled wavefront data.

    Parameters
    ----------
    samples : sequence of (rho, theta, W)
        Each element is a 3-tuple:
          rho   : float in [0, 1] — normalised pupil radius.
          theta : float in radians — pupil angle.
          W     : float — wavefront value at this point (waves or consistent unit).
        Samples outside the unit disk (rho > 1) are silently included in the
        fit; it is the caller's responsibility to filter them if required.

    num_terms : int, optional (default 15)
        Number of Zernike terms to fit.  Must be in [1, 15].
        The first `num_terms` Noll-ordered polynomials Z_1..Z_{num_terms}
        are used as the basis.

    Returns
    -------
    ZernikeFitReport

    Raises
    ------
    ValueError
        If len(samples) < num_terms (under-determined system).
        If num_terms < 1 or num_terms > 15.
    TypeError
        If samples is not a sequence of 3-tuples/lists of numbers.
    """
    # ---- validation --------------------------------------------------------
    if not 1 <= num_terms <= _MAX_TERMS:
        raise ValueError(
            f"num_terms must be in [1, {_MAX_TERMS}], got {num_terms}"
        )

    n_samples = len(samples)  # type: ignore[arg-type]
    if n_samples < num_terms:
        raise ValueError(
            f"Under-determined system: {n_samples} samples < {num_terms} Zernike terms. "
            f"Provide at least {num_terms} samples for a {num_terms}-term fit."
        )

    # ---- build design matrix A and observation vector w --------------------
    try:
        pts = [(float(s[0]), float(s[1]), float(s[2])) for s in samples]
    except (TypeError, IndexError, ValueError) as exc:
        raise TypeError(
            f"samples must be a sequence of (rho, theta, W) 3-tuples: {exc}"
        ) from exc

    rho_arr = np.array([p[0] for p in pts], dtype=np.float64)
    theta_arr = np.array([p[1] for p in pts], dtype=np.float64)
    w_arr = np.array([p[2] for p in pts], dtype=np.float64)

    # Design matrix: shape (n_samples, num_terms)
    A = np.empty((n_samples, num_terms), dtype=np.float64)
    for j in range(num_terms):
        func, _ = _ZERNIKE_FUNCS[j]
        A[:, j] = func(rho_arr, theta_arr)

    # ---- least-squares solve -----------------------------------------------
    # rcond=None uses machine-epsilon based cutoff (numpy default post 1.14)
    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(A, w_arr, rcond=None)

    # ---- RMS residual -------------------------------------------------------
    w_fitted = A @ coeffs
    residual = w_arr - w_fitted
    rms_residual = float(np.sqrt(np.mean(residual ** 2)))

    # ---- dominant aberration (exclude j=1 piston) --------------------------
    dominant_aberration = "piston"
    if num_terms >= 2:
        abs_coeffs = np.abs(coeffs[1:])  # j=2..num_terms (0-indexed: 1..)
        dom_idx = int(np.argmax(abs_coeffs)) + 1  # +1 to skip piston
        _, dominant_aberration = _ZERNIKE_FUNCS[dom_idx]

    # ---- assemble report ---------------------------------------------------
    coeff_names = [_ZERNIKE_FUNCS[j][1] for j in range(num_terms)]

    return ZernikeFitReport(
        coefficients=[float(c) for c in coeffs],
        rms_residual_waves=rms_residual,
        dominant_aberration=dominant_aberration,
        coefficient_names=coeff_names,
        honest_caveat=_HONEST_CAVEAT,
    )
