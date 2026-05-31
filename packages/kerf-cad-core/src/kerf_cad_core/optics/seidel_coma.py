"""
kerf_cad_core.optics.seidel_coma — third-order Seidel coma coefficient S_II
for a sequential thin-lens system from surface paraxial parameters.

Public API
----------
compute_seidel_coma(lens_system_dict, wavelength_nm=550, field_angle_deg=5.0)
    -> SeidelComaReport | dict

Theory (Welford "Aberrations of Optical Systems" §7 / Born & Wolf §5.3)
-----------------------------------------------------------------------
The second Seidel aberration sum S_II (coma) is computed by a dual paraxial-ray
trace through a sequential lens stack:

  Marginal ray : height h at each surface, angle u; determines A = n*i.
  Chief ray    : height ybar at each surface, angle ubar; determines Ā = n*ibar.

At each surface j:

    i_j    = u_j + h_j * c_j          (paraxial angle of incidence, marginal)
    ibar_j = ubar_j + ybar_j * c_j    (paraxial angle of incidence, chief)
    A_j    = n_j * i_j                 (marginal refraction invariant)
    Ā_j    = n_j * ibar_j              (chief refraction invariant)

Per-surface coma contribution (Welford 1986 §7 eq. 7.42):

    S_II_j = -A_j * Ā_j * h_j * Δ(u/n)_j

where Δ(u/n)_j = (u_j'/n_j') - (u_j/n_j) is the reduced-angle change at
surface j.  The total Seidel coma coefficient is:

    S_II = Σ_j S_II_j

Coma in physical units (transverse ray aberration):
  tangential_coma = 3 * S_II * η      (Welford §11.4; Born & Wolf §5.3 eq. 5.3.29)
  where η = chief-ray image height.

Converting to waves:
  coma_waves = tangential_coma / (8 * lambda)     (rms wavefront units)

For the dominant-surface index we report the surface with the largest
|S_II_j| contribution.

HONEST FLAG / SCOPE
--------------------
* Third-order (Seidel) only.  Higher-order coma (Hopkins 5th-order, oblique
  spherical aberration) requires a Hopkins finite-ray OPD analysis.
* Monochromatic; chromatic coma (lateral colour) is NOT computed.
* Paraxial Seidel sums are exact for thin lenses and good approximations
  for thick lenses at moderate apertures (F/# >= 3).
* No defocus residual computed.
* Aperture stop assumed at the first surface (chief-ray height = 0 there).

References
----------
Welford, W.T.  "Aberrations of Optical Systems", Adam Hilger, 1986.
    §7 (Seidel aberrations, eq. 7.42 coma sum S_II).
    §3.3 (paraxial nu-form trace, sign conventions).
Born, M. & Wolf, E.  "Principles of Optics", 7th ed., Cambridge, 1999.
    §5.3 (transverse ray aberrations from Seidel coefficients;
          eq. 5.3.29 tangential coma = 3 * S_II * η).
Kingslake, R.  "Lens Design Fundamentals", Academic Press, 1978.

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
# Reference wavelength
# ---------------------------------------------------------------------------

_LAMBDA_REF_MM = 550e-6   # 550 nm in mm (default reference wavelength)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SeidelComaReport:
    """
    Third-order Seidel coma coefficient S_II for a sequential lens stack.

    Follows Welford (1986) §7 sign convention.

    Attributes
    ----------
    S_II : float
        Total Seidel coma sum (Welford §7 eq. 7.42, Σ S_II_j).
        Units: mm² (same as other Seidel coefficients, lengths in mm).
        Positive S_II = coma present; sign encodes direction relative to
        Welford §6.2 / Born & Wolf §5.3 sign convention.
    coma_waves_at_lambda : float
        |tangential_coma| / (8 * lambda), in waves at the reference
        wavelength, at the given field angle.  Equals
        |3 * S_II * y_chief| / (8 * lambda) (Born & Wolf §5.3 eq. 5.3.29).
        Zero when field_angle_deg == 0 (no off-axis coma on-axis).
    dominant_surface_idx : int
        Zero-based index of the surface with the largest |S_II_j|
        contribution.  -1 if no surface contributes (all zero).
    per_surface_contributions : list[dict]
        Per-surface breakdown: keys include surface, c_mm_inv, n_in,
        n_out, h_mm, ybar_mm, A, Abar, delta_un, SII_contrib.
    honest_caveat : str
        Scope and limitations statement.
    """

    S_II: float = 0.0
    coma_waves_at_lambda: float = 0.0
    dominant_surface_idx: int = -1
    per_surface_contributions: list = field(default_factory=list)
    honest_caveat: str = (
        "Third-order (Seidel) coma only. "
        "Higher-order coma (Hopkins 5th-order, oblique spherical aberration) "
        "requires finite-ray OPD analysis (not implemented). "
        "Monochromatic; chromatic coma excluded. "
        "No defocus residual computed. "
        "Stop assumed at first surface."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "S_II": self.S_II,
            "coma_waves_at_lambda": self.coma_waves_at_lambda,
            "dominant_surface_idx": self.dominant_surface_idx,
            "per_surface_contributions": self.per_surface_contributions,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_seidel_coma(
    lens_system_dict: dict,
    wavelength_nm: float = 550.0,
    field_angle_deg: float = 5.0,
) -> "SeidelComaReport | dict":
    """
    Compute the third-order Seidel coma coefficient S_II for a sequential
    thin-lens system from the surface paraxial parameters.

    Algorithm (Welford 1986 §7 eq. 7.42 / Born & Wolf §5.3)
    --------------------------------------------------------
    1. Parse surfaces list from lens_system_dict['surfaces'].
    2. Trace the *marginal ray* (h = aperture_radius_mm, u = 0) paraxially.
    3. Trace the *chief ray*  (ybar = 0 at first surface, u = tan(theta))
       with stop assumed at the first surface.
    4. At each surface compute:
          A_j    = n_j * (u_j + h_j * c_j)      [marginal refraction invariant]
          Ā_j    = n_j * (ubar_j + ybar_j * c_j) [chief refraction invariant]
          S_II_j = -A_j * Ā_j * h_j * Δ(u/n)_j
    5. Sum over all surfaces: S_II = Σ S_II_j.
    6. Compute coma in waves:
          y_chief = chief-ray image height at paraxial focal plane
          tangential_coma = 3 * S_II * y_chief
          coma_waves = |tangential_coma| / (8 * lambda)
    7. Find dominant surface: argmax_j |S_II_j|.

    Parameters
    ----------
    lens_system_dict : dict
        Must contain key 'surfaces': list of surface dicts, each with:
          c  : curvature 1/R (mm^-1). 0 = flat.
          t  : thickness to next surface (mm). Last surface may be 0.
          n  : refractive index of medium after this surface (>= 1.0).
        Optional top-level keys:
          aperture_radius_mm : marginal ray height at first surface (mm,
                               default 1.0).
          n_object           : refractive index of object space (default 1.0).
    wavelength_nm : float
        Reference wavelength for coma_waves_at_lambda (nm, default 550).
    field_angle_deg : float
        Chief-ray field angle at first surface (degrees, default 5.0).
        Use 0 for on-axis (S_II will be nonzero but chief-ray image height = 0,
        so coma_waves = 0).

    Returns
    -------
    SeidelComaReport  on success.
    dict {ok: False, reason: ...}  on input error.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
        §7 (Seidel aberration sums, eq. 7.42 coma S_II).
    Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
        §5.3 (eq. 5.3.29 tangential coma = 3 * S_II * η).
    """
    # ---- Parse top-level dict -----------------------------------------------
    if not isinstance(lens_system_dict, dict):
        return _err("lens_system_dict must be a dict")
    if "surfaces" not in lens_system_dict:
        return _err("lens_system_dict must contain key 'surfaces'")

    surfaces = lens_system_dict["surfaces"]
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    # ---- Optional parameters ------------------------------------------------
    aperture_radius_mm = lens_system_dict.get("aperture_radius_mm", 1.0)
    n_object = lens_system_dict.get("n_object", 1.0)

    e = _guard("aperture_radius_mm", aperture_radius_mm, positive=True)
    if e:
        return _err(e)
    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # ---- wavelength ---------------------------------------------------------
    e = _guard("wavelength_nm", wavelength_nm, positive=True)
    if e:
        return _err(e)

    # ---- field angle --------------------------------------------------------
    e = _guard("field_angle_deg", field_angle_deg)
    if e:
        return _err(e)

    ap = float(aperture_radius_mm)
    n0 = float(n_object)
    lam_mm = float(wavelength_nm) * 1e-6  # nm → mm

    # ---- Marginal ray trace (h = ap, u = 0) --------------------------------
    h_m = ap
    u_m = 0.0
    n_cur = n0

    marginal_data: list[tuple[float, float, float]] = []  # (h, u_before, u_after)

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_next = float(surf["n"])
        u_m_prime = _paraxial_refract(h_m, u_m, n_cur, n_next, c)
        marginal_data.append((h_m, u_m, u_m_prime))
        h_m = _paraxial_transfer(h_m, u_m_prime, t)
        u_m = u_m_prime
        n_cur = n_next

    # ---- Chief ray trace (ybar = 0 at first surface, u_c = tan(theta)) -----
    # Stop at first surface (Welford §6.2 convention).
    h_c = 0.0
    u_c = math.tan(math.radians(float(field_angle_deg)))
    n_cur = n0

    chief_data: list[tuple[float, float, float]] = []  # (ybar, ubar_before, ubar_after)

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_next = float(surf["n"])
        u_c_prime = _paraxial_refract(h_c, u_c, n_cur, n_next, c)
        chief_data.append((h_c, u_c, u_c_prime))
        h_c = _paraxial_transfer(h_c, u_c_prime, t)
        u_c = u_c_prime
        n_cur = n_next

    # ---- Paraxial image distance (for coma_waves computation) ---------------
    # After the last surface: image distance = -h_m / u_m  (from last surface).
    # If u_m ≈ 0 the stack is afocal; y_chief = h_c (already at any plane).
    if abs(u_m) > 1e-18:
        img_dist = -h_m / u_m
    else:
        img_dist = math.inf

    # Chief-ray image height at the focal plane
    if math.isfinite(img_dist):
        y_chief = h_c + u_c * img_dist
    else:
        y_chief = h_c   # afocal: no well-defined image height

    # ---- Accumulate S_II ----------------------------------------------------
    S_II = 0.0
    per_surface_contributions: list[dict] = []

    n_in = n0
    for idx, surf in enumerate(surfaces):
        c = float(surf["c"])
        n_out = float(surf["n"])

        h, u_in, u_out = marginal_data[idx]
        ybar, ubar_in, ubar_out = chief_data[idx]

        # Paraxial angle of incidence (Welford §3.3: i = u + h*c)
        i_m   = u_in   + h    * c    # marginal
        i_c   = ubar_in + ybar * c    # chief

        # Refraction invariants A = n*i, Ā = n*ibar
        A    = n_in * i_m
        Abar = n_in * i_c

        # Reduced-angle change Δ(u/n) = u'/n' - u/n
        delta_un = u_out / n_out - u_in / n_in

        # Per-surface S_II (Welford 1986 §7 eq. 7.42)
        sii = -(A * Abar) * h * delta_un

        S_II += sii

        per_surface_contributions.append({
            "surface": idx,
            "c_mm_inv": c,
            "n_in": n_in,
            "n_out": n_out,
            "h_mm": h,
            "ybar_mm": ybar,
            "A": A,
            "Abar": Abar,
            "delta_un": delta_un,
            "SII_contrib": sii,
        })

        n_in = n_out

    # ---- Dominant surface ---------------------------------------------------
    if per_surface_contributions:
        dominant_surface_idx = max(
            range(len(per_surface_contributions)),
            key=lambda j: abs(per_surface_contributions[j]["SII_contrib"]),
        )
        # If all contributions are zero (e.g. on-axis flat system), set to -1
        if abs(per_surface_contributions[dominant_surface_idx]["SII_contrib"]) < 1e-30:
            dominant_surface_idx = -1
    else:
        dominant_surface_idx = -1

    # ---- Coma in waves (Born & Wolf §5.3 eq. 5.3.29) -----------------------
    # tangential_coma = 3 * S_II * y_chief   (mm)
    # coma_waves = |tangential_coma| / (8 * lambda)
    tangential_coma_mm = 3.0 * S_II * y_chief
    coma_waves = abs(tangential_coma_mm) / (8.0 * lam_mm)

    return SeidelComaReport(
        S_II=S_II,
        coma_waves_at_lambda=coma_waves,
        dominant_surface_idx=dominant_surface_idx,
        per_surface_contributions=per_surface_contributions,
    )
