"""
kerf_cad_core.optics.distortion_map — geometric distortion map for a lens stack.

Public API
----------
compute_distortion_map(surfaces, field_angles_deg, aperture_mm=1.0,
                       n_object=1.0) -> DistortionMapReport

Computes the geometric (tangential) distortion of a lens stack as a function
of field angle.

Algorithm (Hecht §5.6 / Welford 1986 §6.3)
--------------------------------------------
For each field angle θ in field_angles_deg:

  1. Trace the *chief ray* through the stack: the chief ray enters the first
     surface at height y=0 (stop at first surface) and travels at angle θ
     in object space.  The exact meridional tracer (_trace_ray_off_axis from
     mtf_across_field) is used with ray_h=0 and the BFL determined from the
     collimated marginal-ray paraxial trace.  This ensures the image plane is
     correctly placed at the paraxial back focal distance (not the chief-ray
     focus, which differs from the marginal focus due to field curvature).

  2. The *actual image height* y_actual is the meridional image-plane intercept
     of the chief ray at the paraxial BFL plane.

  3. The *ideal paraxial image height* is:
         y_paraxial = f_eff * tan(θ)
     where f_eff (EFL) is derived from the collimated marginal-ray trace via
     paraxial_properties.

  4. *Distortion* (in percent) is:
         D(θ) = (y_actual - y_paraxial) / |y_paraxial| × 100

     Sign convention (Hecht §5.6 / ISO 9039):
       barrel     → D < 0  (actual image height < paraxial ideal; image
                             is compressed at the edges)
       pincushion → D > 0  (actual image height > paraxial ideal; image
                             is stretched at the edges)
     At θ=0: y_paraxial=0 → distortion is defined as 0.

  5. Distortion kind is classified as:
       "barrel"     if all non-trivial D values are negative.
       "pincushion" if all non-trivial D values are positive.
       "mixed"      if both positive and negative D appear (e.g. telephoto).
       "none"       if |D| < 0.05 % everywhere (well-corrected stack).

Seidel cross-check (Welford 1986 §6.3)
----------------------------------------
For a single thin lens the Seidel S_V coefficient predicts the third-order
distortion.  The additive distortion in image height from S_V is:

    Δy_seidel = S_V * tan²(θ)       (Welford §6.3, reduced form)

giving:

    D_seidel(θ) = S_V * tan²(θ) / |y_paraxial| × 100
                = S_V * |tan(θ)| / |EFL| × 100

This is returned as seidel_distortion_percent for comparison.  The third-order
prediction is accurate only for small field angles; at moderate fields higher-
order terms dominate.

DEPTH BAR
---------
For an ideal stigmatic stack (equiconvex symmetric singlet at small field):
  distortion < 2% — S_V ≈ 0 by bending symmetry (Welford §6.4).

For a real BK7 biconvex singlet at moderate field (20 deg):
  |distortion| > 5% is typical for an uncorrected singlet with high S_V.

HONEST FLAGS
------------
* Monochromatic only.  Polychromatic distortion (lateral chromatic component)
  requires integrating D(θ, λ) over the spectral band — out of scope.
* Tangential (meridional) distortion only.  For rotationally symmetric systems
  the sagittal distortion is identical by symmetry, but off-axis astigmatism
  can produce a small difference that is not captured here.
* The chief ray is traced from *infinity* (collimated input).  For finite
  conjugates the field angle should be the half-field angle at the object.
* Aperture stop assumed at first surface (chief ray height = 0 there).

References
----------
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §5.6 (geometric distortion).
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986,
    §6.3 (Seidel S_V distortion coefficient),
    §3.3 (paraxial nu-form trace),
    §5   (exact meridional ray trace).

Units: lengths in mm, angles in degrees / radians as noted.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import paraxial_properties
from kerf_cad_core.optics.mtf_across_field import _trace_ray_off_axis
from kerf_cad_core.optics.seidel_aberrations import seidel_coefficients


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False,
           finite: bool = True) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if finite and not math.isfinite(v):
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
class DistortionMapReport:
    """
    Geometric distortion map for a lens stack.

    Follows Hecht §5.6 / Welford 1986 §6.3 sign convention:
      barrel distortion    → distortion_percent < 0
      pincushion distortion → distortion_percent > 0

    Attributes
    ----------
    field_angles_deg    : list[float]  Field angles in degrees.
    y_actual_mm         : list[float]  Chief-ray image-plane intercepts (mm).
    y_paraxial_mm       : list[float]  Ideal paraxial image heights f*tan(θ) (mm).
    distortion_percent  : list[float]  (y_actual - y_paraxial)/|y_paraxial| × 100.
    max_distortion_pct  : float        Max |distortion| across all field angles.
    kind                : str          "barrel" | "pincushion" | "mixed" | "none".
    EFL_mm              : float        Effective focal length used for y_paraxial.
    seidel_distortion_percent : list[float]
        Third-order Seidel S_V additive prediction (Welford §6.3).
    honest_flag         : str          Caveats / limitations.
    """

    field_angles_deg: list = field(default_factory=list)
    y_actual_mm: list = field(default_factory=list)
    y_paraxial_mm: list = field(default_factory=list)
    distortion_percent: list = field(default_factory=list)
    max_distortion_pct: float = 0.0
    kind: str = "none"
    EFL_mm: float = 0.0
    seidel_distortion_percent: list = field(default_factory=list)
    honest_flag: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "field_angles_deg": self.field_angles_deg,
            "y_actual_mm": self.y_actual_mm,
            "y_paraxial_mm": self.y_paraxial_mm,
            "distortion_percent": self.distortion_percent,
            "max_distortion_pct": self.max_distortion_pct,
            "kind": self.kind,
            "EFL_mm": self.EFL_mm,
            "seidel_distortion_percent": self.seidel_distortion_percent,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_DISTORTION_THRESHOLD_PCT = 0.05  # below this magnitude → "none"


def compute_distortion_map(
    surfaces: list[dict],
    field_angles_deg: list[float],
    aperture_mm: float = 1.0,
    n_object: float = 1.0,
) -> DistortionMapReport | dict:
    """
    Compute the geometric distortion map for a lens stack.

    Traces the chief ray at each field angle and compares the actual image
    height with the ideal paraxial prediction f*tan(θ).

    Algorithm (Hecht §5.6 / Welford 1986 §6.3):
      1. Obtain EFL and BFL from a collimated marginal-ray trace via
         paraxial_properties.
      2. For each field angle θ, trace the chief ray (height=0 at first
         surface, angle=θ) to the paraxial image plane using the exact
         meridional tracer (_trace_ray_off_axis, ray_h=0, BFL from step 1).
      3. Compare y_actual (meridional trace) with y_paraxial = EFL * tan(θ).
      4. Compute distortion percent and classify the distortion type.

    Parameters
    ----------
    surfaces : list of surface dicts (c, t, n, optional k).
        Same format as trace_lens_stack.  Lengths in mm, c in mm^-1.
    field_angles_deg : list of float
        Field angles in degrees to evaluate.  0 deg is on-axis (D=0).
    aperture_mm : float
        Marginal ray height used for Seidel cross-check and paraxial EFL.
        Default 1.0 mm.
    n_object : float
        Refractive index of object space (default 1.0 = air).

    Returns
    -------
    DistortionMapReport on success.
    dict {ok: False, reason: ...} on input error.

    References
    ----------
    Hecht §5.6 (geometric distortion, barrel / pincushion).
    Welford (1986) §6.3 (S_V Seidel distortion coefficient).
    """
    # ---- Validate inputs ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    if not isinstance(field_angles_deg, (list, tuple)) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")

    for i, ang in enumerate(field_angles_deg):
        e = _guard(f"field_angles_deg[{i}]", ang)
        if e:
            return _err(e)

    e = _guard("aperture_mm", aperture_mm, positive=True)
    if e:
        return _err(e)

    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)

    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # ---- EFL and BFL from paraxial properties (marginal ray) ---------------
    # BFL is the paraxial image distance from the last surface for a
    # collimated (on-axis) input ray.  The image plane is placed here.
    props = paraxial_properties(surfaces, n_object=float(n_object))
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")

    efl = props["EFL_mm"]
    bfl = props["BFL_mm"]
    if not math.isfinite(efl) or abs(efl) < 1e-12:
        return _err(f"EFL is not usable (EFL={efl} mm); cannot compute y_paraxial")
    if not math.isfinite(bfl):
        return _err(f"BFL is not usable (BFL={bfl} mm); cannot place image plane")

    # ---- Seidel S_V at a representative field angle for cross-check --------
    # Use first non-zero field angle; fall back to 5 deg if all are zero.
    ref_field = next(
        (a for a in field_angles_deg if abs(float(a)) > 1e-6),
        5.0,
    )
    seidel_result = seidel_coefficients(
        surfaces,
        aperture=float(aperture_mm),
        field_angle_deg=float(ref_field),
        n_object=float(n_object),
    )
    sv_valid = not isinstance(seidel_result, dict)  # SeidelReport vs error dict
    sv_coeff = seidel_result.S_V if sv_valid else 0.0

    # ---- Trace chief ray at each field angle --------------------------------
    # Chief ray: ray_h=0 (height at first surface = 0, stop at first surface),
    # field angle determines the ray direction.  BFL positions the image plane.
    # Algorithm: _trace_ray_off_axis(surfaces, ray_h=0, field_angle_rad,
    #                                n_object, paraxial_image_dist=BFL)
    # This is the same trace used by the MTF module for the chief-ray intercept.
    field_angles_out: list[float] = []
    y_actual: list[float] = []
    y_paraxial: list[float] = []
    distortion_pct: list[float] = []
    seidel_pct: list[float] = []

    for ang_deg in field_angles_deg:
        ang_rad = math.radians(float(ang_deg))
        tan_ang = math.tan(ang_rad)

        # Ideal paraxial image height: y_p = EFL * tan(θ)  (Hecht §5.6)
        y_p = efl * tan_ang

        # At θ=0: distortion is 0 by definition
        if abs(y_p) < 1e-12:
            field_angles_out.append(float(ang_deg))
            y_actual.append(0.0)
            y_paraxial.append(0.0)
            distortion_pct.append(0.0)
            seidel_pct.append(0.0)
            continue

        # Chief ray: height=0 at first surface, direction = field angle.
        # _trace_ray_off_axis traces using exact Snell + Newton-Raphson
        # (Welford 1986 §5) and propagates to paraxial_image_dist=BFL.
        y_act_val = _trace_ray_off_axis(
            surfaces,
            ray_h=0.0,
            field_angle_rad=float(ang_rad),
            n_object=float(n_object),
            paraxial_image_dist=float(bfl),
        )

        if y_act_val is None or math.isnan(y_act_val):
            field_angles_out.append(float(ang_deg))
            y_actual.append(math.nan)
            y_paraxial.append(y_p)
            distortion_pct.append(math.nan)
            seidel_pct.append(math.nan)
            continue

        # Distortion percent (Hecht §5.6 / ISO 9039 definition):
        #   D = (y_actual - y_paraxial) / |y_paraxial| × 100
        d_pct = (y_act_val - y_p) / abs(y_p) * 100.0

        # Seidel third-order additive prediction (Welford §6.3):
        #   Δy_seidel = S_V * tan²(θ)
        #   D_seidel = Δy_seidel / |y_paraxial| × 100
        #            = S_V * |tan(θ)| / |EFL| × 100
        if sv_valid:
            delta_y_seidel = sv_coeff * tan_ang * tan_ang
            s_pct = delta_y_seidel / abs(y_p) * 100.0
        else:
            s_pct = 0.0

        field_angles_out.append(float(ang_deg))
        y_actual.append(y_act_val)
        y_paraxial.append(y_p)
        distortion_pct.append(d_pct)
        seidel_pct.append(s_pct)

    # ---- Classify distortion kind -----------------------------------------
    valid_d = [d for d in distortion_pct
               if math.isfinite(d) and abs(d) >= _DISTORTION_THRESHOLD_PCT]
    if not valid_d:
        kind = "none"
        max_dist = max((abs(d) for d in distortion_pct if math.isfinite(d)),
                       default=0.0)
    else:
        max_dist = max(abs(d) for d in valid_d)
        has_neg = any(d < 0.0 for d in valid_d)
        has_pos = any(d > 0.0 for d in valid_d)
        if has_neg and has_pos:
            kind = "mixed"
        elif has_neg:
            kind = "barrel"
        else:
            kind = "pincushion"

    honest_flag = (
        "Monochromatic only; polychromatic distortion (lateral chromatic component) "
        "requires integrating D(theta, lambda) over spectral band — not implemented. "
        "Tangential (meridional) distortion only; for rotationally symmetric stacks "
        "the sagittal distortion is identical, but astigmatism-induced differences "
        "are not captured. "
        "Chief ray traced from infinity; aperture stop assumed at first surface. "
        "Seidel S_V prediction is third-order only and valid only at small field angles."
    )

    return DistortionMapReport(
        field_angles_deg=field_angles_out,
        y_actual_mm=y_actual,
        y_paraxial_mm=y_paraxial,
        distortion_percent=distortion_pct,
        max_distortion_pct=max_dist,
        kind=kind,
        EFL_mm=efl,
        seidel_distortion_percent=seidel_pct,
        honest_flag=honest_flag,
    )
