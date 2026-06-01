"""
kerf_cad_core.optics.seidel_coma — third-order Seidel coma coefficient S_II
for a sequential thin-lens system from surface paraxial parameters.

Public API
----------
compute_seidel_coma(lens_system_dict, wavelength_nm=550, field_angle_deg=5.0,
                    compare_seidel_to_finite_ray=False)
    -> SeidelComaReport | dict

compare_seidel_vs_finite_ray_coma(surfaces, field_height_mm,
                                   num_pupil_samples=64)
    -> ComaCompareReport | dict

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
from kerf_cad_core.optics.coma_compute import compute_finite_ray_coma


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
    finite_ray_W131 : float or None
        Finite-ray OPD W_131 RMS (waves) from Zernike Z_7 fitting via
        compute_finite_ray_coma().  None when compare_seidel_to_finite_ray=False
        or when finite-ray trace fails.
    residual_higher_order_W131 : float or None
        Signed residual: finite_ray_W131 − coma_waves_at_lambda.
        Positive = higher-order coma present beyond Seidel prediction.
        None when finite_ray_W131 is None.
    comparison_caveat : str or None
        Scope note for the comparison.  None when compare_seidel_to_finite_ray=False.
    honest_caveat : str
        Scope and limitations statement.
    """

    S_II: float = 0.0
    coma_waves_at_lambda: float = 0.0
    dominant_surface_idx: int = -1
    per_surface_contributions: list = field(default_factory=list)
    finite_ray_W131: "float | None" = None
    residual_higher_order_W131: "float | None" = None
    comparison_caveat: "str | None" = None
    honest_caveat: str = (
        "Third-order (Seidel) coma only. "
        "Higher-order coma (Hopkins 5th-order, oblique spherical aberration) "
        "is now available via compute_finite_ray_coma() — call "
        "compute_seidel_coma(..., compare_seidel_to_finite_ray=True) or "
        "compare_seidel_vs_finite_ray_coma() for direct head-to-head comparison. "
        "Monochromatic; chromatic coma excluded. "
        "No defocus residual computed. "
        "Stop assumed at first surface."
    )

    def to_dict(self) -> dict:
        d: dict = {
            "ok": True,
            "S_II": self.S_II,
            "coma_waves_at_lambda": self.coma_waves_at_lambda,
            "dominant_surface_idx": self.dominant_surface_idx,
            "per_surface_contributions": self.per_surface_contributions,
            "honest_caveat": self.honest_caveat,
        }
        if self.finite_ray_W131 is not None:
            d["finite_ray_W131"] = self.finite_ray_W131
        if self.residual_higher_order_W131 is not None:
            d["residual_higher_order_W131"] = self.residual_higher_order_W131
        if self.comparison_caveat is not None:
            d["comparison_caveat"] = self.comparison_caveat
        return d


# ---------------------------------------------------------------------------
# ComaCompareReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class ComaCompareReport:
    """
    Head-to-head comparison of Seidel third-order coma vs finite-ray OPD coma.

    Attributes
    ----------
    seidel_W131_waves : float
        Seidel third-order W_131 RMS (waves at wavelength_mm) computed from
        compute_seidel_coma().  Equals |3·S_II·y_chief| / (8·λ).
    finite_ray_W131_waves : float
        Finite-ray OPD W_131 RMS (waves) from Zernike Z_7 fitting via
        compute_finite_ray_coma().  Captures higher-order coma contributions.
    residual_W131_waves : float
        Signed residual: finite_ray_W131_waves − seidel_W131_waves.
        Positive = finite-ray OPD predicts more coma than Seidel (higher-order
        contributions present).  Negative = Seidel over-predicts (partial
        cancellation by higher-order terms).
    residual_fraction : float
        residual_W131_waves / seidel_W131_waves.  math.nan when
        seidel_W131_waves < 1e-15.
    seidel_S_II : float
        Raw Seidel coma sum Σ S_II_j (mm²), from the paraxial dual-ray trace.
    finite_ray_zernike_Z7 : float
        Fitted Noll Z_7 coefficient (mm) from the finite-ray OPD analysis.
    n_rays_valid : int
        Number of pupil sample rays successfully traced in the finite-ray pass.
    field_height_mm : float
        Off-axis image field height used for the comparison (mm).
    wavelength_mm : float
        Wavelength used for OPD-to-waves conversion (mm).
    comparison_caveat : str
        Scope and limitations of the comparison.
    """

    seidel_W131_waves: float = 0.0
    finite_ray_W131_waves: float = 0.0
    residual_W131_waves: float = 0.0
    residual_fraction: float = math.nan
    seidel_S_II: float = 0.0
    finite_ray_zernike_Z7: float = 0.0
    n_rays_valid: int = 0
    field_height_mm: float = 0.0
    wavelength_mm: float = 0.000550
    comparison_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "seidel_W131_waves": self.seidel_W131_waves,
            "finite_ray_W131_waves": self.finite_ray_W131_waves,
            "residual_W131_waves": self.residual_W131_waves,
            "residual_fraction": (
                self.residual_fraction
                if math.isfinite(self.residual_fraction)
                else None
            ),
            "seidel_S_II": self.seidel_S_II,
            "finite_ray_zernike_Z7": self.finite_ray_zernike_Z7,
            "n_rays_valid": self.n_rays_valid,
            "field_height_mm": self.field_height_mm,
            "wavelength_mm": self.wavelength_mm,
            "comparison_caveat": self.comparison_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_seidel_coma(
    lens_system_dict: dict,
    wavelength_nm: float = 550.0,
    field_angle_deg: float = 5.0,
    compare_seidel_to_finite_ray: bool = False,
    finite_ray_num_pupil_samples: int = 64,
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
    8. Optionally (compare_seidel_to_finite_ray=True) call
       compute_finite_ray_coma() and populate finite_ray_W131,
       residual_higher_order_W131, and comparison_caveat fields.

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
    compare_seidel_to_finite_ray : bool
        If True, additionally call compute_finite_ray_coma() and populate
        finite_ray_W131, residual_higher_order_W131, and comparison_caveat
        fields on the returned SeidelComaReport.  Default False.
    finite_ray_num_pupil_samples : int
        Number of pupil samples for the finite-ray OPD pass (default 64).
        Ignored when compare_seidel_to_finite_ray=False.

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

    report = SeidelComaReport(
        S_II=S_II,
        coma_waves_at_lambda=coma_waves,
        dominant_surface_idx=dominant_surface_idx,
        per_surface_contributions=per_surface_contributions,
    )

    # ---- Optional finite-ray OPD comparison ---------------------------------
    if compare_seidel_to_finite_ray:
        _COMPARE_CAVEAT = (
            "Seidel-vs-finite-ray comparison: Seidel W_131 is third-order only "
            "(Welford §7 eq. 7.42 / Born & Wolf §5.3 eq. 5.3.29); "
            "finite-ray W_131 fitted from Zernike Z_7 (Noll 1976 coma_y) via "
            "3-D skew ray OPD (compute_finite_ray_coma, Welford §5.5 / Born & Wolf §9.2). "
            "Residual = finite_ray_W131 − seidel_W131 (waves). "
            "Positive residual = higher-order coma present. "
            "Monochromatic; stop at first surface; aspheric higher-order terms not modelled."
        )
        if not math.isfinite(img_dist):
            # Afocal stack: finite-ray OPD undefined
            report.finite_ray_W131 = None
            report.residual_higher_order_W131 = None
            report.comparison_caveat = (
                "Afocal stack: no paraxial focus; finite-ray OPD undefined."
            )
        else:
            opd_result = compute_finite_ray_coma(
                surfaces=surfaces,
                field_height_mm=y_chief,
                num_pupil_samples=finite_ray_num_pupil_samples,
                aperture_radius_mm=ap,
                n_object=n0,
                wavelength_mm=lam_mm,
            )
            if not isinstance(opd_result, dict):
                finite_rms = opd_result.wave_aberration_W131_rms_waves
                residual = finite_rms - coma_waves
                report.finite_ray_W131 = finite_rms
                report.residual_higher_order_W131 = residual
                report.comparison_caveat = _COMPARE_CAVEAT
            else:
                # finite-ray trace failed (e.g. too few valid rays or TIR)
                report.finite_ray_W131 = None
                report.residual_higher_order_W131 = None
                report.comparison_caveat = (
                    _COMPARE_CAVEAT
                    + f" [finite-ray trace failed: {opd_result.get('reason', 'unknown')}]"
                )

    return report


# ---------------------------------------------------------------------------
# Head-to-head comparison function
# ---------------------------------------------------------------------------

def compare_seidel_vs_finite_ray_coma(
    surfaces: list,
    field_height_mm: float,
    num_pupil_samples: int = 64,
    aperture_radius_mm: float = 1.0,
    n_object: float = 1.0,
    wavelength_nm: float = 550.0,
) -> "ComaCompareReport | dict":
    """
    Direct head-to-head comparison of Seidel third-order coma vs finite-ray
    OPD coma for a sequential lens stack at a given image field height.

    Computes both the Seidel S_II prediction (paraxial dual-ray trace, Welford
    §7 eq. 7.42) and the finite-ray OPD W_131 (Zernike Z_7, compute_finite_ray_coma,
    Welford §5.5 / Born & Wolf §9.2), then reports both values and the
    signed residual (finite_ray − seidel).

    Parameters
    ----------
    surfaces : list of surface dicts
        Each dict: c (mm^-1), t (mm), n (>= 1.0), optional k.
    field_height_mm : float
        Off-axis image field height (mm).  A small angle is derived from
        field_height_mm / paraxial_image_distance.
    num_pupil_samples : int
        Number of pupil rays for finite-ray OPD analysis (default 64).
    aperture_radius_mm : float
        Entrance-pupil rim radius (mm).  Default 1.0.
    n_object : float
        Refractive index of object space.  Default 1.0.
    wavelength_nm : float
        Reference wavelength (nm).  Default 550.

    Returns
    -------
    ComaCompareReport  on success.
    dict {ok: False, reason: ...}  on input error or afocal stack.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
        §7 (Seidel sums, eq. 7.42 coma S_II) and §5.5 (finite-ray OPD).
    Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
        §5.3 (eq. 5.3.29 tangential coma) and §9.2 (Zernike OPD expansion).
    Noll, R.J. (1976) "Zernike polynomials and atmospheric turbulence",
        J. Opt. Soc. Am. 66, 207-211.
    """
    # ---- Input validation ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list of surface dicts")
    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    e = _guard("field_height_mm", field_height_mm)
    if e:
        return _err(e)
    e = _guard("aperture_radius_mm", aperture_radius_mm, positive=True)
    if e:
        return _err(e)
    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")
    e = _guard("wavelength_nm", wavelength_nm, positive=True)
    if e:
        return _err(e)

    ap = float(aperture_radius_mm)
    n0 = float(n_object)
    fh = float(field_height_mm)
    lam_mm = float(wavelength_nm) * 1e-6  # nm → mm

    # ---- Derive field angle from field height / paraxial image distance ------
    h_m = ap
    u_m = 0.0
    n_cur = n0
    for surf in surfaces:
        c_s = float(surf["c"])
        t_s = float(surf["t"])
        n_n = float(surf["n"])
        u_m = _paraxial_refract(h_m, u_m, n_cur, n_n, c_s)
        h_m = _paraxial_transfer(h_m, u_m, t_s)
        n_cur = n_n

    if abs(u_m) < 1e-18:
        return _err("afocal stack: no paraxial focus; comparison undefined")
    img_dist = -h_m / u_m

    field_angle_deg = math.degrees(math.atan(abs(fh) / abs(img_dist))) if abs(img_dist) > 1e-10 else 0.0

    # ---- Seidel S_II ---------------------------------------------------------
    lens_dict = {
        "surfaces": surfaces,
        "aperture_radius_mm": ap,
        "n_object": n0,
    }
    seidel_report = compute_seidel_coma(
        lens_dict,
        wavelength_nm=wavelength_nm,
        field_angle_deg=field_angle_deg,
        compare_seidel_to_finite_ray=False,
    )
    if isinstance(seidel_report, dict):
        return seidel_report  # propagate error

    seidel_waves = seidel_report.coma_waves_at_lambda

    # ---- Finite-ray OPD W_131 -----------------------------------------------
    opd_result = compute_finite_ray_coma(
        surfaces=surfaces,
        field_height_mm=fh,
        num_pupil_samples=num_pupil_samples,
        aperture_radius_mm=ap,
        n_object=n0,
        wavelength_mm=lam_mm,
    )
    if isinstance(opd_result, dict):
        return opd_result  # propagate error (e.g. too few rays, TIR)

    finite_waves = opd_result.wave_aberration_W131_rms_waves
    residual = finite_waves - seidel_waves
    if seidel_waves > 1e-15:
        residual_frac = residual / seidel_waves
    else:
        residual_frac = math.nan

    _CAVEAT = (
        "Seidel vs finite-ray head-to-head: "
        "Seidel W_131 (waves) = |3·S_II·y_chief|/(8·λ), paraxial dual-ray trace "
        "(Welford §7 eq. 7.42 / Born & Wolf §5.3 eq. 5.3.29); "
        "finite-ray W_131 (waves) = |Z_7 coefficient|/λ from 3-D skew ray OPD, "
        "Zernike Z_7 projection (Welford §5.5 / Born & Wolf §9.2 / Noll 1976). "
        "Residual = finite_ray − seidel (waves). "
        "Positive: higher-order coma (5th-order Hopkins, oblique spherical) dominates. "
        "Negative: Seidel over-predicts (partial cancellation by higher-order terms). "
        "Monochromatic; stop at first surface; aspheric higher-order terms not modelled by skew tracer."
    )

    return ComaCompareReport(
        seidel_W131_waves=seidel_waves,
        finite_ray_W131_waves=finite_waves,
        residual_W131_waves=residual,
        residual_fraction=residual_frac,
        seidel_S_II=seidel_report.S_II,
        finite_ray_zernike_Z7=opd_result.zernike_Z7_coeff,
        n_rays_valid=opd_result.n_rays_valid,
        field_height_mm=fh,
        wavelength_mm=lam_mm,
        comparison_caveat=_CAVEAT,
    )
