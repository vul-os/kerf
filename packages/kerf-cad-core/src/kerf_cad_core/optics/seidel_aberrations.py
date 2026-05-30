"""
kerf_cad_core.optics.seidel_aberrations — third-order Seidel aberration coefficients
for a sequential lens stack.

Public API
----------
seidel_coefficients(surfaces, aperture=1.0, field_angle_deg=5.0) -> SeidelReport
    Compute the five Seidel third-order aberration sums for a lens stack.

Theory (Welford 1986 §6.2 / Born & Wolf §5.3)
-----------------------------------------------
Two paraxial rays are traced: the *marginal ray* (on-axis object, full aperture)
and the *chief ray* (edge-of-field object, through centre of the aperture stop).

At each surface j the refraction invariants are:

    A_j    = n_j  * i_j         marginal-ray refraction invariant
    Abar_j = n_j  * ibar_j      chief-ray refraction invariant
    H      = n * u * ybar - n * ubar * y   Lagrange / Smith-Helmholtz invariant
                                            (constant across all surfaces)

where i = u + y * c  (paraxial angle of incidence, Welford §3.3 sign convention)

Per-surface Seidel contributions (Welford 1986 §6.2, eqs. 6.1-6.5):

    SI_j   = -A^2    * h * delta(u/n)   [spherical aberration]
    SII_j  = -A*Abar * h * delta(u/n)   [coma]
    SIII_j = -Abar^2 * h * delta(u/n)   [astigmatism]
    SIV_j  = -H^2    * delta(c/n)       [field curvature, Petzval]
    SV_j   = (SIII_j + SIV_j) * Abar/A [distortion]

where:
    delta(u/n) = (u'/n')_j - (u/n)_j   [reduced angle change across surface]
    delta(c/n) = c_j * (1/n_j' - 1/n_j)
    h          = marginal ray height at surface j

Total wavefront aberration (primary, in waves at lambda=550 nm):
    Reported as sqrt(SI^2+SII^2+SIII^2+SIV^2+SV^2) / (8*lambda) as a scalar.

HONEST FLAG / SCOPE
--------------------
This module computes ONLY third-order (Seidel) aberrations via the paraxial
ray-trace. Real systems require Hopkins' exact wavefront difference (finite ray -
reference sphere) for higher-order aberrations.  In particular:

  * High-aperture systems (F/# < ~3) will show significant 5th-order terms
    not captured here.
  * Aspheric surfaces reduce Seidel but introduce higher-order wavefront error
    not modelled by this method.
  * Chromatic aberrations (axial + lateral) are outside the Seidel framework
    (monochromatic only).
  * Zernike decomposition of the wavefront requires finite-ray OPD tracing
    (not implemented here).

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §6.2 (Seidel aberration sums), §3.3 (paraxial nu-form trace).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
    §5.3 (third-order aberration coefficients, eqs. 5.3.14-5.3.18).
Kingslake, R. -- "Lens Design Fundamentals", Academic Press, 1978.

Units: lengths in mm, angles in radians.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import _paraxial_refract, _paraxial_transfer


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("c", "t", "n"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
        err = _guard(f"surface[{idx}].{fld}", s[fld])
        if err:
            return err
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SeidelReport:
    """
    Third-order Seidel aberration coefficients for a lens stack.

    Coefficients follow Welford (1986) §6.2 sign convention.
    A standard positive (converging) singlet in air has S_I > 0
    (under-corrected spherical aberration; marginal rays focus closer
    than the paraxial focal point).

    Attributes
    ----------
    S_I   : float  Spherical aberration sum.
    S_II  : float  Coma sum.
    S_III : float  Astigmatism sum.
    S_IV  : float  Field curvature (Petzval) sum.
    S_V   : float  Distortion sum.
    H     : float  Lagrange (Smith-Helmholtz) invariant.
    per_surface : list of per-surface contribution dicts.
    total_wavefront_aberration_waves : float
        Scalar wavefront error in waves at 550 nm: RSS(SI..SV) / (8*lambda).
        Third-order only; higher-order contributions not included.
    """

    S_I: float = 0.0
    S_II: float = 0.0
    S_III: float = 0.0
    S_IV: float = 0.0
    S_V: float = 0.0
    H: float = 0.0
    per_surface: list = field(default_factory=list)
    total_wavefront_aberration_waves: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "S_I": self.S_I,
            "S_II": self.S_II,
            "S_III": self.S_III,
            "S_IV": self.S_IV,
            "S_V": self.S_V,
            "H_lagrange": self.H,
            "per_surface": self.per_surface,
            "total_wavefront_aberration_waves": self.total_wavefront_aberration_waves,
            "honest_flag": (
                "Third-order (Seidel) only. "
                "Higher-order aberrations require Hopkins finite-ray OPD. "
                "Monochromatic; chromatic aberrations excluded."
            ),
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_LAMBDA_REF_MM = 550e-6  # 550 nm reference wavelength in mm


def seidel_coefficients(
    surfaces: list[dict],
    aperture: float = 1.0,
    field_angle_deg: float = 5.0,
    n_object: float = 1.0,
) -> SeidelReport | dict:
    """
    Compute the five Seidel third-order aberration coefficients for a
    sequential lens stack using a dual paraxial-ray trace.

    Algorithm (Welford 1986 §6.2)
    ------------------------------
    1. Trace the *marginal ray*: h_m = aperture, u_m = 0 (collimated input).
       This defines the aperture-height h and angle u at each surface.

    2. Trace the *chief ray*: h_c = 0, u_c = tan(field_angle_deg) at the
       first surface (stop at first surface, i.e., chief ray height = 0
       at surface 0).  This defines the chief-ray height ybar and angle ubar.

    3. At each surface compute the Seidel sum contributions per Welford (1986)
       §6.2 / Born & Wolf §5.3.

    Parameters
    ----------
    surfaces : list of surface dicts (c, t, n, optional k).
        Same format as trace_lens_stack.  Lengths in mm, c in mm^-1.
    aperture : float
        Marginal ray height at first surface (mm). Default 1.0 mm.
    field_angle_deg : float
        Chief-ray angle at the first surface (degrees). Default 5 deg.
    n_object : float
        Refractive index of object space (default 1.0 = air).

    Returns
    -------
    SeidelReport  on success.
    dict {ok: False, reason: ...}  on input error.

    References
    ----------
    Welford (1986) §6.2 (Seidel sums); §3.3 (paraxial nu-form trace).
    Born & Wolf (1999) §5.3 (aberration coefficients, eqs. 5.3.14-5.3.18).
    """
    # ---- Validate inputs ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    for nm, val, pos in [
        ("aperture", aperture, True),
        ("n_object", n_object, True),
    ]:
        e = _guard(nm, val, positive=pos)
        if e:
            return _err(e)

    e = _guard("field_angle_deg", field_angle_deg)
    if e:
        return _err(e)

    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # ---- Marginal ray trace (h_m=aperture, u_m=0) --------------------------
    h_m = float(aperture)
    u_m = 0.0
    n = float(n_object)

    marginal: list[tuple[float, float, float]] = []  # (h, u_before, u_after)

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])
        u_m_prime = _paraxial_refract(h_m, u_m, n, n_prime, c)
        marginal.append((h_m, u_m, u_m_prime))
        h_m = _paraxial_transfer(h_m, u_m_prime, t)
        u_m = u_m_prime
        n = n_prime

    # ---- Chief ray trace (h_c=0 at first surface, u_c=field_angle) --------
    # Stop assumed at first surface (entrance pupil = first surface).
    h_c = 0.0
    u_c = math.tan(math.radians(float(field_angle_deg)))
    n = float(n_object)

    chief: list[tuple[float, float, float]] = []  # (ybar, ubar_before, ubar_after)

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])
        u_c_prime = _paraxial_refract(h_c, u_c, n, n_prime, c)
        chief.append((h_c, u_c, u_c_prime))
        h_c = _paraxial_transfer(h_c, u_c_prime, t)
        u_c = u_c_prime
        n = n_prime

    # ---- Lagrange invariant H ----------------------------------------------
    # H = n * (u * ybar - ubar * y) -- constant across all surfaces (Welford §3.6).
    # Evaluate at object space (before first surface):
    # marginal: h = aperture, u = 0; chief: h_c = 0, u_c = field angle
    n0 = float(n_object)
    h_m0, u_m0, _ = marginal[0]
    h_c0, u_c0, _ = chief[0]
    # H = n0 * (u_m0 * h_c0 - u_c0 * h_m0)
    H = n0 * (u_m0 * h_c0 - u_c0 * h_m0)

    # ---- Accumulate Seidel sums -------------------------------------------
    S_I = S_II = S_III = S_IV = S_V = 0.0
    per_surface = []

    n_in = float(n_object)
    for idx, surf in enumerate(surfaces):
        c = float(surf["c"])
        n_out = float(surf["n"])

        h, u_in, u_out = marginal[idx]
        ybar, ubar_in, ubar_out = chief[idx]

        # Paraxial angle of incidence (Welford §3.3: i = u + h*c)
        i_m = u_in + h * c        # marginal AOI before refraction
        i_c = ubar_in + ybar * c  # chief AOI before refraction

        # Refraction invariants A = n*i, Abar = n*ibar (Welford §6.2)
        A = n_in * i_m
        Abar = n_in * i_c

        # Reduced angle change delta(u/n) across surface
        delta_un = u_out / n_out - u_in / n_in

        # Petzval curvature change delta(c/n) = c * (1/n' - 1/n)
        delta_cn = c * (1.0 / n_out - 1.0 / n_in)

        # Per-surface Seidel contributions (Welford 1986 §6.2, eqs. 6.1-6.5)
        # Positive S_I => under-corrected spherical aberration (converging singlet)
        si   = -(A ** 2) * h * delta_un
        sii  = -(A * Abar) * h * delta_un
        siii = -(Abar ** 2) * h * delta_un
        siv  = -(H ** 2) * delta_cn
        # S_V = (SIII + SIV) * Abar/A, guard for A near zero (flat/non-refracting surface)
        if abs(A) > 1e-15:
            sv = (siii + siv) * (Abar / A)
        else:
            sv = 0.0

        S_I   += si
        S_II  += sii
        S_III += siii
        S_IV  += siv
        S_V   += sv

        per_surface.append({
            "surface": idx,
            "c_mm_inv": c,
            "n_in": n_in,
            "n_out": n_out,
            "h_mm": h,
            "ybar_mm": ybar,
            "A": A,
            "Abar": Abar,
            "delta_un": delta_un,
            "delta_cn": delta_cn,
            "SI_contrib": si,
            "SII_contrib": sii,
            "SIII_contrib": siii,
            "SIV_contrib": siv,
            "SV_contrib": sv,
        })

        n_in = n_out

    # ---- Total wavefront aberration (scalar, in waves at 550 nm) ----------
    # RSS of all five primary aberration sums, divided by 8*lambda (wave-optics scaling)
    rss = math.sqrt(S_I**2 + S_II**2 + S_III**2 + S_IV**2 + S_V**2)
    total_wfe_waves = rss / (8.0 * _LAMBDA_REF_MM)

    return SeidelReport(
        S_I=S_I,
        S_II=S_II,
        S_III=S_III,
        S_IV=S_IV,
        S_V=S_V,
        H=H,
        per_surface=per_surface,
        total_wavefront_aberration_waves=total_wfe_waves,
    )
