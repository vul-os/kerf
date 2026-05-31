"""
kerf_cad_core.optics.fno_working — Working F-Number for Finite-Conjugate Systems.

The *nominal* f-number N = f/D describes a lens focused at infinity.  When
the lens is focused at a finite object distance, the physical aperture still
has diameter D but the image-side conjugate moves farther away than f, which
makes the cone of light at the sensor slower.  The *working* f-number N_w
accounts for this light-collection loss.

Formula (Hecht "Optics" 5e §6.4 / Smith "Modern Optical Engineering" 4e §4.5):

    N_w = N · (1 + |m|)

where m = image-to-object magnification (m = −s_i / s_o; negative for real
inverted images).

Equivalently:

    N_w = N · (1 − m)      when the sign convention is m ≤ 0 for real images

Both forms are equivalent because |m| = −m for real images (m < 0).

Special cases:
  * m = 0  (infinity focus): N_w = N.  No exposure penalty.
  * m = −1 (1:1 macro, life-size): N_w = 2N.  Two-stop penalty (factor 4
    reduction in image irradiance vs. infinity focus).
  * m = −0.5 (1:2, half life-size): N_w = 1.5N.  ~1.17-stop penalty.

Image irradiance is proportional to 1/N_w² (Hecht §5.5, Lambertian source):

    E_image ∝ 1 / N_w²

Exposure-loss relative to infinity focus:

    loss_stops = log₂((N_w / N)²) = 2 · log₂(N_w / N) = 2 · log₂(1 + |m|)

Honest caveat
-------------
This formula is the *thin-lens* (symmetric-pupil) working f-number.  Real
lenses are NOT pupil-symmetric: pupil magnification p = D_exit / D_entrance
differs from 1.  For asymmetric lenses (retrofocus, telephoto, macro lenses
with floating elements) the correct formula is:

    N_w = (1/p) · N · (1 + |m|/p)    [Smith MOE §4.5, exact form]

or equivalently defined via the image-side numerical aperture.  The correction
is of order (p − 1) and can reach 0.5–1 stop for extreme retrofocus designs.
Pupil-position measurement requires a physical aperture-stop trace that is
beyond the scope of this module.

Units: dimensionless (f-numbers, magnification, stops).

References
----------
Hecht, E. — "Optics", 5th ed. (2017), §6.4.
Smith, W.J. — "Modern Optical Engineering", 4th ed. (2008), §4.5.
Ray, S.F. — "Applied Photographic Optics", 3rd ed. (2002), §2.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FnoWorkingSpec:
    """
    Input specification for working f-number computation.

    Attributes
    ----------
    nominal_f_number : float
        The lens's nominal (infinity-focus) f-number N = f/D.  Must be > 0.
        Examples: 1.4, 2.8, 4.0, 8.0.
    magnification : float
        Transverse image-to-object magnification m = −s_i / s_o.
        Convention: m is negative for real (inverted) images.
        Common values:
          0.0   — infinity focus (no extension)
         −0.1   — 1:10 reduction (e.g. close-focus portrait)
         −0.5   — 1:2, half life-size macro
         −1.0   — 1:1, life-size macro
         −2.0   — 2:1, 2× magnification (photomacrography)
        Positive m is physically valid for virtual or aerial images but
        unusual in still photography.
    """

    nominal_f_number: float
    magnification: float


@dataclass
class FnoWorkingReport:
    """
    Output report from compute_working_fno.

    Attributes
    ----------
    nominal_f_number : float
        Input nominal f-number N.
    working_f_number : float
        Effective f-number at the given magnification:
        N_w = N · (1 + |m|).
    exposure_loss_stops : float
        Number of photographic stops lost relative to infinity focus:
        loss = 2 · log₂(1 + |m|) = 2 · log₂(N_w / N).
        Zero at m=0 (infinity).  Positive = less light reaches the sensor.
    image_irradiance_factor : float
        Relative image irradiance compared to infinity-focus shot at the
        same nominal f-number.  factor = (N / N_w)² = 1/(1+|m|)².
        At m=0: factor=1.0.  At m=−1 (1:1): factor=0.25 (−2 stops).
    honest_caveat : str
        Plain-English limitations string.
    """

    nominal_f_number: float
    working_f_number: float
    exposure_loss_stops: float
    image_irradiance_factor: float
    honest_caveat: str = field(default="", repr=False)

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "nominal_f_number": self.nominal_f_number,
            "working_f_number": self.working_f_number,
            "exposure_loss_stops": self.exposure_loss_stops,
            "image_irradiance_factor": self.image_irradiance_factor,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Honest caveat string
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Thin-lens (symmetric-pupil) approximation: N_w = N*(1+|m|).  "
    "For asymmetric lenses (retrofocus, telephoto, macro lenses with "
    "floating elements) the pupil magnification p = D_exit/D_entrance "
    "differs from 1.  The exact formula (Smith MOE §4.5) is "
    "N_w = (1/p)*N*(1+|m|/p), introducing a correction of order (p−1).  "
    "This can reach 0.5–1 stop error for extreme retrofocus designs.  "
    "Pupil-position measurement requires a physical aperture-stop trace.  "
    "Formula valid for any m in [−∞, ∞]; practically m in [−3, 0] covers "
    "infinity-focus through 3× magnification macro."
)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_working_fno(spec: FnoWorkingSpec) -> FnoWorkingReport:
    """
    Compute the working f-number for a finite-conjugate optical system.

    Algorithm (Hecht §6.4 / Smith MOE §4.5):

        N_w = N · (1 + |m|)
        image_irradiance_factor = (N / N_w)²  =  1 / (1 + |m|)²
        exposure_loss_stops = 2 · log₂(N_w / N)  =  2 · log₂(1 + |m|)

    Parameters
    ----------
    spec : FnoWorkingSpec
        Input specification.

    Returns
    -------
    FnoWorkingReport
        All computed values.

    Raises
    ------
    ValueError
        If nominal_f_number is not strictly positive.
    """
    N = float(spec.nominal_f_number)
    m = float(spec.magnification)

    if N <= 0.0:
        raise ValueError(f"nominal_f_number must be > 0, got {N}")

    abs_m = abs(m)

    # Working f-number: N_w = N * (1 + |m|)
    N_w = N * (1.0 + abs_m)

    # Relative image irradiance: E ∝ 1/N_w² → factor = (N/N_w)² = 1/(1+|m|)²
    factor = (N / N_w) ** 2

    # Exposure loss in photographic stops: loss = log2(E_inf/E_m) = log2(N_w/N)²
    # = 2*log2(N_w/N) = 2*log2(1 + |m|)
    if abs_m == 0.0:
        loss_stops = 0.0
    else:
        loss_stops = 2.0 * math.log2(1.0 + abs_m)

    return FnoWorkingReport(
        nominal_f_number=N,
        working_f_number=N_w,
        exposure_loss_stops=loss_stops,
        image_irradiance_factor=factor,
        honest_caveat=_HONEST_CAVEAT,
    )
