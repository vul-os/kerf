"""
kerf_cad_core.optics.coma_compute — comatic aberration metrics from a lens stack.

Public API
----------
compute_coma(stack, field_angles_deg, n_pupil_rays=16,
             aperture_radius_mm=1.0, n_object=1.0) -> ComaReport | dict

Theory (Welford 1986 §11.4 / Born & Wolf §5.3)
-----------------------------------------------
Coma is the second Seidel aberration (S_II).  For a ray at pupil rim (ρ=1) and
field height η in the tangential plane, the transverse aberration is (Welford
1986 §11.4, Born & Wolf §5.3 eq. 5.3.29):

    Tangential coma  = 3 * S_II * η      (mean displacement of upper/lower rim rays)
    Sagittal  coma   =     S_II * η      (displacement of sagittal rim rays)

where S_II is the Seidel coma coefficient and η is the chief-ray image height.
The relationship tangential = 3 × sagittal defines the "comatic flare".

Algorithm
---------
1.  Establish the paraxial focal plane: trace a marginal ray (h=aperture_mm,
    u=0) and record the paraxial image distance d_img.
2.  For each field angle θ_f:
    a.  Compute the paraxial chief-ray image height y₀ by propagating a chief
        ray (h=0 at first surface, u=tan θ_f) through the system paraxially and
        then projecting to d_img.
    b.  Trace N rim rays at heights h_k = aperture_mm * cos(φ_k) and angles
        u_k = tan(θ_f) using exact meridional Snell (trace_lens_stack).
    c.  Propagate each rim ray to d_img by continuing the exact ray: take the
        last surface (Y_last, L_out, M_out) from the meridional trace and
        compute Y_img = Y_last + (M_out/L_out) * d_img.
    d.  Tangential coma = |mean_y_tang - y₀|  where mean_y_tang is the mean of
        Y_img for tangential-fan rays (|sin(φ_k)| < 0.5, i.e. near φ=0 or π).
        This equals 3 * |S_II| * |y₀| in the Seidel limit (Welford §11.4).
    e.  Sagittal coma = tangential_coma / 3 (exact equality in Seidel limit;
        Welford §11.4 eq. 11.4.4).
    f.  total_coma = sqrt(tangential² + sagittal²).
    g.  Seidel prediction = 3 * |S_II| * |y₀| (Born & Wolf §5.3 eq. 5.3.29).
    h.  seidel_match_fraction = |total_coma - seidel_pred_total| / seidel_pred_total.

Depth bar (OPTICS-COMA-COMPUTE)
--------------------------------
* Flat surfaces (c=0, zero power): afocal stack → coma = 0 (no image plane).
* BK7 biconvex (R=±50 mm, t=5 mm, n=1.5168) at 14° field, 5 mm aperture:
  total_coma > 1 μm (1e-3 mm).
* Field-angle scaling: coma scales linearly with |tan(θ)| (small-angle limit).
* Seidel match: |total_coma - seidel_pred| / seidel_pred < 0.25 at ≤ 5° field
  (3rd-order dominates; factor-3 relationship between tangential and sagittal).

HONEST FLAG
-----------
This module computes ONLY third-order (Seidel) coma.  Higher-order coma
(Hopkins 5th-order, oblique spherical aberration) requires a full Hopkins
finite-ray OPD analysis (not implemented here).  The Seidel prediction is
3rd-order only and degrades for:
  * Large field angles (> ~10° for fast systems)
  * Fast (low f/#) systems where 5th-order terms dominate
  * Aspheric surfaces that introduce higher-order wavefront error

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §11.4 (comatic aberration, tangential and sagittal coma, flare length,
    eq. 11.4.4 tangential coma = 3 × sagittal coma).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
    §5.3 (transverse ray aberrations from Seidel wavefront coefficients,
    eq. 5.3.29 coma aberration; tangential/sagittal decomposition).

Units: lengths in mm, angles in radians.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    trace_lens_stack,
    _paraxial_refract,
    _paraxial_transfer,
)
from kerf_cad_core.optics.seidel_aberrations import seidel_coefficients


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


def _paraxial_image_distance(
    surfaces: list[dict],
    aperture_mm: float,
    n_object: float,
) -> float:
    """
    Paraxial image distance from a marginal ray (h=aperture_mm, u=0).

    Returns the distance from the last surface vertex to the paraxial focus.
    Returns math.inf for afocal/zero-power stacks.
    """
    h = aperture_mm
    u = 0.0
    n = n_object
    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_p = float(surf["n"])
        u_p = _paraxial_refract(h, u, n, n_p, c)
        h = _paraxial_transfer(h, u_p, t)
        u = u_p
        n = n_p
    if abs(u) < 1e-18:
        return math.inf
    return -h / u


def _paraxial_chief_image_height(
    surfaces: list[dict],
    field_angle_deg: float,
    n_object: float,
    img_dist: float,
) -> float:
    """
    Paraxial chief-ray image height at the focal plane (img_dist from last surface).

    Chief ray: h=0 at first surface (stop at first surface), u = tan(field_angle_deg).
    """
    u_c = math.tan(math.radians(field_angle_deg))
    h_c = 0.0
    n = n_object
    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_p = float(surf["n"])
        u_c_p = _paraxial_refract(h_c, u_c, n, n_p, c)
        h_c = _paraxial_transfer(h_c, u_c_p, t)
        u_c = u_c_p
        n = n_p
    return h_c + u_c * img_dist


def _propagate_to_imgplane(last_mer: dict, img_dist: float) -> float | None:
    """
    Propagate the exact meridional ray from the last surface to the focal plane.

    last_mer  : last entry in meridional_surfaces from trace_lens_stack.
    img_dist  : paraxial image distance from last surface vertex (mm).

    Returns the Y intercept at the focal plane, or None if the ray failed.
    """
    Y = last_mer.get("Y_mm")
    L = last_mer.get("L_out")
    M = last_mer.get("M_out")
    if Y is None or L is None or M is None:
        return None
    if not (math.isfinite(Y) and math.isfinite(L) and math.isfinite(M)):
        return None
    if abs(L) < 1e-15:
        return None
    return Y + (M / L) * img_dist


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ComaFieldPoint:
    """
    Coma metrics at a single field angle.

    Attributes
    ----------
    field_angle_deg       : float  Field angle (degrees).
    tangential_coma_mm    : float  Mean Y-displacement of tangential-fan rim rays
                                   from chief-ray image point (mm).  Equals
                                   3 * |S_II| * |y₀| in the Seidel limit
                                   (Welford 1986 §11.4).
    sagittal_coma_mm      : float  Sagittal coma = tangential_coma / 3 (mm).
    total_coma_mm         : float  sqrt(tangential² + sagittal²) (mm).
    seidel_prediction_mm  : float  3 * |S_II| * |y₀| (mm); Born & Wolf §5.3 eq. 5.3.29.
    seidel_match_fraction : float  |total_coma - seidel_pred_total| / seidel_pred_total;
                                   math.nan when seidel_pred < 1e-15.
    chief_ray_y_mm        : float  Paraxial chief-ray image height y₀ (mm).
    n_rays_valid          : int    Number of rim rays successfully traced.
    """

    field_angle_deg: float = 0.0
    tangential_coma_mm: float = 0.0
    sagittal_coma_mm: float = 0.0
    total_coma_mm: float = 0.0
    seidel_prediction_mm: float = 0.0
    seidel_match_fraction: float = math.nan
    chief_ray_y_mm: float = 0.0
    n_rays_valid: int = 0

    def to_dict(self) -> dict:
        return {
            "field_angle_deg": self.field_angle_deg,
            "tangential_coma_mm": self.tangential_coma_mm,
            "sagittal_coma_mm": self.sagittal_coma_mm,
            "total_coma_mm": self.total_coma_mm,
            "seidel_prediction_mm": self.seidel_prediction_mm,
            "seidel_match_fraction": (
                self.seidel_match_fraction
                if math.isfinite(self.seidel_match_fraction)
                else None
            ),
            "chief_ray_y_mm": self.chief_ray_y_mm,
            "n_rays_valid": self.n_rays_valid,
        }


@dataclass
class ComaReport:
    """
    Coma aberration report for a lens stack across multiple field angles.

    Attributes
    ----------
    per_field             : list[ComaFieldPoint]
    aperture_radius_mm    : float  Entrance-pupil rim radius used.
    S_II                  : float  Seidel coma coefficient from paraxial trace.
    honest_flag           : str    Scope and limitations.
    """

    per_field: list = field(default_factory=list)
    aperture_radius_mm: float = 1.0
    S_II: float = 0.0
    honest_flag: str = (
        "Third-order (Seidel) coma only. "
        "Higher-order coma (Hopkins 5th-order, oblique spherical aberration) "
        "requires finite-ray OPD analysis (not implemented). "
        "Monochromatic; chromatic coma excluded. "
        "Stop assumed at first surface."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "aperture_radius_mm": self.aperture_radius_mm,
            "S_II": self.S_II,
            "per_field": [fp.to_dict() for fp in self.per_field],
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_coma(
    stack: list[dict],
    field_angles_deg: list[float],
    n_pupil_rays: int = 16,
    aperture_radius_mm: float = 1.0,
    n_object: float = 1.0,
) -> "ComaReport | dict":
    """
    Compute coma aberration metrics for each field angle in a lens stack.

    Algorithm (Welford 1986 §11.4 / Born & Wolf §5.3)
    ---------------------------------------------------
    1.  Establish the paraxial focal plane by tracing a marginal ray
        (h=aperture_radius_mm, u=0) paraxially.
    2.  For each field angle:
        a.  Compute paraxial chief-ray image height y₀ (stop at first surface).
        b.  Trace N rim rays at h_k = aperture_radius_mm * cos(φ_k),
            u_k = tan(θ_f) using exact meridional Snell (trace_lens_stack).
        c.  Propagate each ray to the paraxial focal plane using the last-
            surface meridional exit direction.
        d.  Tangential coma = |mean_Y_tang − y₀| for rays with |sin(φ)| < 0.5
            (tangential fan, near φ = 0 or π; Welford §11.4).
        e.  Sagittal coma = tangential_coma / 3 (Welford §11.4 eq. 11.4.4).
        f.  total_coma = sqrt(tan² + sag²).
        g.  Seidel prediction = 3 × |S_II| × |y₀| (Born & Wolf §5.3 eq. 5.3.29).

    Parameters
    ----------
    stack : list of surface dicts
        Each dict: c (mm^-1), t (mm), n (>= 1.0), optional k.
    field_angles_deg : list of float
        Field angles in degrees. 0 = on-axis.
    n_pupil_rays : int
        Number of rim rays per field (default 16). Must be >= 4.
    aperture_radius_mm : float
        Entrance-pupil rim radius (mm). Default 1.0.
    n_object : float
        Refractive index of object space. Default 1.0.

    Returns
    -------
    ComaReport  on success.
    dict {ok: False, reason: ...}  on input error.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
        §11.4 (comatic flare length, tangential and sagittal coma).
    Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., Cambridge, 1999,
        §5.3 (transverse ray aberrations from Seidel coefficients,
        eq. 5.3.29 tangential/sagittal coma).
    """
    # ---- Input validation ---------------------------------------------------
    if not isinstance(stack, list) or len(stack) == 0:
        return _err("stack must be a non-empty list of surface dicts")

    for idx, s in enumerate(stack):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    if not isinstance(field_angles_deg, list) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")

    e = _guard("aperture_radius_mm", aperture_radius_mm, positive=True)
    if e:
        return _err(e)
    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    try:
        n_pupil_rays = int(n_pupil_rays)
    except (TypeError, ValueError):
        return _err("n_pupil_rays must be an integer")
    if n_pupil_rays < 4:
        return _err("n_pupil_rays must be >= 4")

    ap = float(aperture_radius_mm)
    n0 = float(n_object)

    # ---- Paraxial image distance -------------------------------------------
    img_dist = _paraxial_image_distance(stack, ap, n0)
    if not math.isfinite(img_dist):
        # Afocal / zero-power stack: coma undefined in Seidel sense.
        # Return zero coma for all field angles (no comatic flare without a focus).
        per_field_zero = []
        for ang in field_angles_deg:
            try:
                ang_f = float(ang)
            except (TypeError, ValueError):
                return _err(f"field_angle {ang!r} must be a number")
            per_field_zero.append(ComaFieldPoint(
                field_angle_deg=ang_f,
                tangential_coma_mm=0.0,
                sagittal_coma_mm=0.0,
                total_coma_mm=0.0,
                seidel_prediction_mm=0.0,
                seidel_match_fraction=math.nan,
                chief_ray_y_mm=0.0,
                n_rays_valid=0,
            ))
        return ComaReport(per_field=per_field_zero, aperture_radius_mm=ap, S_II=0.0)

    # ---- Seidel S_II -------------------------------------------------------
    # S_II embeds the aperture height h at each surface via A = n*i = n*(u + h*c).
    # Evaluate at 5° reference so the chief-ray contribution is non-zero.
    # Welford 1986 §6.2.
    _ref_field = 5.0
    seidel_ref = seidel_coefficients(
        stack, aperture=ap, field_angle_deg=_ref_field, n_object=n0
    )
    S_II = seidel_ref.S_II if not isinstance(seidel_ref, dict) else 0.0

    # ---- Pupil azimuth angles ----------------------------------------------
    azimuths = [2.0 * math.pi * k / n_pupil_rays for k in range(n_pupil_rays)]

    # ---- Per-field computation ---------------------------------------------
    per_field: list[ComaFieldPoint] = []

    for ang_deg in field_angles_deg:
        try:
            ang_deg = float(ang_deg)
        except (TypeError, ValueError):
            return _err(f"field_angle {ang_deg!r} must be a number")

        # Paraxial chief-ray image height at focal plane
        y_chief = _paraxial_chief_image_height(stack, ang_deg, n0, img_dist)
        u_field = math.tan(math.radians(ang_deg))

        # Trace rim rays and propagate to paraxial focal plane
        tang_y_vals: list[float] = []
        n_valid = 0

        for phi in azimuths:
            # Meridional height of this pupil ray: h = ap * cos(phi)
            # The angle stays at u_field (we sample the pupil in height, not angle).
            ray_h = ap * math.cos(phi)

            result = trace_lens_stack(
                stack, ray_h=ray_h, ray_u=u_field, n_object=n0
            )
            if not result.get("ok"):
                continue

            mer = result.get("meridional_surfaces")
            if not mer:
                continue
            Y_img = _propagate_to_imgplane(mer[-1], img_dist)
            if Y_img is None:
                continue

            n_valid += 1

            # Tangential fan: |sin(phi)| < 0.5 selects rays near φ=0 or φ=π
            if abs(math.sin(phi)) < 0.5:
                tang_y_vals.append(Y_img)

        if n_valid == 0 or len(tang_y_vals) == 0:
            per_field.append(ComaFieldPoint(
                field_angle_deg=ang_deg,
                tangential_coma_mm=math.nan,
                sagittal_coma_mm=math.nan,
                total_coma_mm=math.nan,
                seidel_prediction_mm=0.0,
                seidel_match_fraction=math.nan,
                chief_ray_y_mm=y_chief,
                n_rays_valid=n_valid,
            ))
            continue

        # Tangential coma = |mean(Y_tang) - y_chief|  (Welford §11.4)
        tan_coma = abs(sum(tang_y_vals) / len(tang_y_vals) - y_chief)

        # Sagittal coma = tangential / 3  (Welford §11.4 eq. 11.4.4)
        sag_coma = tan_coma / 3.0

        total_coma = math.sqrt(tan_coma ** 2 + sag_coma ** 2)

        # Seidel prediction for tangential coma:
        #   tangential_coma_seidel = 3 * |S_II| * |y_chief|
        # (Born & Wolf §5.3 eq. 5.3.29; S_II already encodes aperture height h
        # at each surface via A = n*(u + h*c).)
        seidel_pred_tan = 3.0 * abs(S_II) * abs(y_chief)
        seidel_pred_sag = seidel_pred_tan / 3.0
        seidel_pred_total = math.sqrt(seidel_pred_tan ** 2 + seidel_pred_sag ** 2)

        if seidel_pred_total > 1e-15:
            match_frac = abs(total_coma - seidel_pred_total) / seidel_pred_total
        else:
            match_frac = math.nan

        per_field.append(ComaFieldPoint(
            field_angle_deg=ang_deg,
            tangential_coma_mm=tan_coma,
            sagittal_coma_mm=sag_coma,
            total_coma_mm=total_coma,
            seidel_prediction_mm=seidel_pred_tan,   # tangential Seidel (diagnostic)
            seidel_match_fraction=match_frac,
            chief_ray_y_mm=y_chief,
            n_rays_valid=n_valid,
        ))

    return ComaReport(
        per_field=per_field,
        aperture_radius_mm=ap,
        S_II=S_II,
    )
