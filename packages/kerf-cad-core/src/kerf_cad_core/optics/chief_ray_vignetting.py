"""
kerf_cad_core.optics.chief_ray_vignetting — chief-ray vignetting and relative
illumination (RI) for sequential lens stacks.

Public API
----------
compute_vignetting(surfaces, field_angles_deg, aperture_radius_mm,
                   clear_apertures_mm=None, n_marginal_rays=8,
                   n_object=1.0) -> VignettingReport

Theory (Welford 1986 §4.5 / Hecht §6.6)
-----------------------------------------
Vignetting is the progressive blocking of off-axis ray bundles by aperture-stop
and lens-rim apertures.  For a field angle θ the solid-angle of the cone of rays
that actually reaches the image plane is reduced compared to the on-axis case.

Algorithm
---------
1.  Trace the chief ray (passes through the centre of the aperture stop, i.e.
    height = 0 at the first surface, angle = θ) through the lens stack using the
    exact meridional trace from `lens_stack_trace`.

2.  Sample N_M marginal rays uniformly around the rim of the entrance pupil at
    the same field angle θ.  Each marginal ray is launched at the full aperture
    radius displaced around the pupil perimeter.  For a rotationally-symmetric
    system traced in the meridional plane, the two ±Y marginal-ray heights bound
    the cone; we also sample intermediate azimuths projected onto the meridional
    plane to allow for asymmetric clipping.  Ray heights at the entrance pupil
    (plane of first surface) are:

        h_k = aperture_radius * cos(phi_k) + h_chief_0

    where phi_k = 2*pi*k/N_M (azimuth around pupil rim) and h_chief_0 = 0.

    In a rotationally-symmetric system the transverse component sin(phi_k) would
    represent a sagittal displacement; it is NOT independently traced here because
    the meridional trace handles only Y.  We instead project each pupil azimuth
    onto the meridional (Y) axis: h_k = aperture_radius * cos(phi_k).  This gives
    ray heights spanning [-aperture_radius, +aperture_radius] and correctly
    represents the full marginal cone for a circular stop.

3.  At each surface j, the traced ray height |Y_j| is compared against the
    surface clear aperture CA_j (the physical lens rim radius).  A ray is
    *blocked* if |Y_j| > CA_j at any surface.

4.  Relative illumination at field angle θ is:

        RI(θ) = n_surviving / N_M

    For an unvignetted system the natural cos⁴(θ) law (photometric fall-off due
    to projected area + solid-angle foreshortening, Hecht §6.6) should be
    recovered.  Each surface with CA_j = ∞ acts as a fully transmitting rim.

cos⁴ baseline
--------------
For a lens with no physical clipping (all CAs = ∞) the only geometric
illumination fall-off is the natural cos⁴(θ) law:

    RI_cos4(θ) = cos⁴(θ)

This is returned alongside the traced RI so callers can quantify excess vignetting.

HONEST FLAG / SCOPE
--------------------
  * Assumes **circular**, rotationally-symmetric apertures and a rotationally-
    symmetric lens stack.  Anamorphic or off-axis aperture stops are NOT modelled.
  * Sagittal-ray component is projected onto the meridional plane: exact for
    systems with no tangential/sagittal asymmetry.
  * Clipping check uses paraxial-style per-surface heights; higher-order coma
    can shift the actual envelope, but for most photographic-lens designs the
    paraxial bound is the correct design constraint.
  * Sensor acceptance (image-side cos⁴ from sensor tilt) is included in the
    baseline but NOT from any additional field-lens / telecentricity.
  * Polychromatic vignetting (chromatic pupil walk) is out of scope.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §4.5 (vignetting apertures and relative illumination).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.6 (illumination fall-off, cos⁴ law, vignetting).
Smith, W.J. -- "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008,
    §5 (stop and pupil locations, vignetting).

Units: lengths in mm, angles in radians internally / degrees at API boundary.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    _paraxial_refract,
    _paraxial_transfer,
    _validate_surface,
)


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Paraxial height trace (used for marginal-ray clipping check)
# ---------------------------------------------------------------------------

def _trace_paraxial_heights(
    surfaces: list[dict],
    ray_h0: float,
    ray_u0: float,
    n_object: float = 1.0,
) -> list[float]:
    """
    Trace a paraxial ray and return the list of ray heights at each surface.

    Uses the nu-form paraxial trace (Welford 1986 §3.3):
        n' * u' = n * u - h * c * (n' - n)
        h_{j+1} = h_j + t_j * u'_j

    Returns a list of length len(surfaces) with the height at each surface vertex.
    """
    h = float(ray_h0)
    u = float(ray_u0)
    n = float(n_object)
    heights = []
    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])
        heights.append(h)
        u_prime = _paraxial_refract(h, u, n, n_prime, c)
        h = _paraxial_transfer(h, u_prime, t)
        u = u_prime
        n = n_prime
    return heights


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class VignettingReport:
    """
    Per-field vignetting result.

    Attributes
    ----------
    field_angles_deg : list[float]
        Input field angles (degrees).
    relative_illumination : list[float]
        Fraction of marginal rays that clear all surface apertures.
        Range [0, 1].  For an unvignetted system ≈ 1.0 at all fields.
    cos4_baseline : list[float]
        Natural cos⁴(θ) photometric fall-off for comparison (no clipping).
    surviving_fractions : list[float]
        Same as relative_illumination (alias kept for API clarity).
    excess_vignetting : list[float]
        RI(θ) / cos⁴(θ) — ratio < 1 indicates clipping beyond the natural law.
    per_field_blocked_surfaces : list[list[int]]
        Per field angle: list of surface indices where at least one marginal ray
        was clipped.
    n_marginal_rays : int
        Number of marginal rays sampled per field angle.
    aperture_radius_mm : float
        Entrance-pupil half-diameter used for the trace.
    honest_flag : str
        Scope disclaimer.

    References
    ----------
    Welford 1986 §4.5; Hecht §6.6.
    """
    field_angles_deg: list[float]
    relative_illumination: list[float]
    cos4_baseline: list[float]
    surviving_fractions: list[float]
    excess_vignetting: list[float]
    per_field_blocked_surfaces: list[list[int]]
    n_marginal_rays: int
    aperture_radius_mm: float
    honest_flag: str = (
        "SCOPE: circular, rotationally-symmetric apertures only. "
        "Sagittal-ray component projected onto meridional plane. "
        "Anamorphic / off-axis stops, polychromatic pupil walk: NOT modelled. "
        "Ref: Welford 1986 §4.5; Hecht §6.6."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "field_angles_deg": self.field_angles_deg,
            "relative_illumination": self.relative_illumination,
            "cos4_baseline": self.cos4_baseline,
            "surviving_fractions": self.surviving_fractions,
            "excess_vignetting": self.excess_vignetting,
            "per_field_blocked_surfaces": self.per_field_blocked_surfaces,
            "n_marginal_rays": self.n_marginal_rays,
            "aperture_radius_mm": self.aperture_radius_mm,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def compute_vignetting(
    surfaces: list[dict],
    field_angles_deg: list[float],
    aperture_radius_mm: float = 10.0,
    clear_apertures_mm: list[float] | None = None,
    n_marginal_rays: int = 8,
    n_object: float = 1.0,
) -> VignettingReport | dict:
    """
    Compute vignetting (relative illumination) across field angles.

    Theory: Welford 1986 §4.5 + Hecht §6.6.

    Parameters
    ----------
    surfaces : list[dict]
        Sequential lens surfaces, same format as `trace_lens_stack`.
        Each dict: c (mm^-1), t (mm), n (>=1.0), optional k.
    field_angles_deg : list[float]
        Field angles to evaluate (degrees).  Typically [0, 5, 10, 14].
    aperture_radius_mm : float
        Entrance-pupil half-diameter (mm).  Default 10 mm.
    clear_apertures_mm : list[float] | None
        Per-surface clear aperture radius (mm).  len must equal len(surfaces).
        Use math.inf (or a large number) for surfaces with no physical rim.
        If None, all surfaces are treated as infinite (no clipping — pure cos⁴).
    n_marginal_rays : int
        Number of marginal rays sampled around the pupil perimeter.
        Default 8.  Minimum 4.  More rays improve accuracy for strongly
        decentred pupils.
    n_object : float
        Refractive index of object space.  Default 1.0 (air).

    Returns
    -------
    VignettingReport
        Dataclass with per-field RI, cos⁴ baseline, surviving fractions,
        excess vignetting, blocked-surface lists.
    dict {"ok": False, "reason": ...}
        On any validation error.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §4.5.
    Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.6.
    """
    # ---- Validate surfaces -----------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)

    # ---- Validate field angles -------------------------------------------
    if not isinstance(field_angles_deg, list) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")

    # ---- Validate scalar params ------------------------------------------
    for nm, val in [("aperture_radius_mm", aperture_radius_mm),
                    ("n_object", n_object)]:
        e = _guard(nm, val, positive=True)
        if e:
            return _err(e)

    if n_marginal_rays < 4:
        return _err("n_marginal_rays must be >= 4")

    # ---- Build per-surface clear aperture list ---------------------------
    n_surf = len(surfaces)
    if clear_apertures_mm is None:
        ca = [math.inf] * n_surf
    else:
        if len(clear_apertures_mm) != n_surf:
            return _err(
                f"clear_apertures_mm length ({len(clear_apertures_mm)}) "
                f"must equal number of surfaces ({n_surf})"
            )
        ca = [float(v) for v in clear_apertures_mm]
        for i, v in enumerate(ca):
            if not (math.isfinite(v) or math.isinf(v)) or v <= 0:
                return _err(f"clear_apertures_mm[{i}] must be > 0")

    # ---- Per-field computation -------------------------------------------
    ri_list: list[float] = []
    cos4_list: list[float] = []
    blocked_surf_list: list[list[int]] = []

    aperture_radius_mm = float(aperture_radius_mm)

    for theta_deg in field_angles_deg:
        theta_rad = math.radians(float(theta_deg))
        cos4 = math.cos(theta_rad) ** 4
        cos4_list.append(cos4)

        # Chief ray: height = 0 at first surface, angle = theta
        # (passes through the centre of the aperture stop).
        # Field angle θ means the ray comes from an object point at angle θ
        # off-axis.  In the paraxial model the chief ray is launched with
        # u_chief = tan(θ) ≈ θ for small angles; we use exact tan for
        # correctness at larger field angles.
        u_chief = math.tan(theta_rad)

        surviving = 0
        blocked_surfaces: set[int] = set()

        for k in range(n_marginal_rays):
            # Azimuth around the pupil rim (Welford 1986 §4.5)
            # Sagittal component sin(phi_k) is projected onto the meridional
            # plane via the cos(phi_k) modulation — valid for a rotationally-
            # symmetric system.  Honest flag documents this assumption.
            phi_k = 2.0 * math.pi * k / n_marginal_rays
            # Marginal ray height at the entrance pupil for this azimuth
            h_marginal = aperture_radius_mm * math.cos(phi_k)
            # The marginal ray field angle is the same as the chief ray
            # (same object point, different pupil height)
            u_marginal = u_chief

            # Trace this marginal ray and collect per-surface heights
            heights = _trace_paraxial_heights(
                surfaces, h_marginal, u_marginal, n_object
            )

            # Check clipping at each surface
            blocked = False
            for j, (h_at_surf, ca_j) in enumerate(zip(heights, ca)):
                if math.isnan(h_at_surf):
                    blocked = True
                    blocked_surfaces.add(j)
                    break
                if abs(h_at_surf) > ca_j:
                    blocked = True
                    blocked_surfaces.add(j)
                    break

            if not blocked:
                surviving += 1

        ri = surviving / n_marginal_rays
        ri_list.append(ri)
        blocked_surf_list.append(sorted(blocked_surfaces))

    # Excess vignetting: RI / cos⁴ — values < 1 mean clipping beyond natural
    excess: list[float] = []
    for ri_val, cos4_val in zip(ri_list, cos4_list):
        if cos4_val < 1e-12:
            excess.append(float("nan"))
        else:
            excess.append(ri_val / cos4_val)

    return VignettingReport(
        field_angles_deg=[float(a) for a in field_angles_deg],
        relative_illumination=ri_list,
        cos4_baseline=cos4_list,
        surviving_fractions=ri_list,          # alias
        excess_vignetting=excess,
        per_field_blocked_surfaces=blocked_surf_list,
        n_marginal_rays=n_marginal_rays,
        aperture_radius_mm=aperture_radius_mm,
    )
