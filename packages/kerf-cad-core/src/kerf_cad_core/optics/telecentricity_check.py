"""
kerf_cad_core.optics.telecentricity_check — paraxial chief-ray telecentricity
analysis for sequential optical systems.

Public API
----------
compute_telecentricity(lens_system_dict, field_height_mm=10.0, focus_shift_mm=0.5)
    -> TelecentricityReport

Theory (Welford "Aberrations of Optical Systems" §3; Smith "Modern Optical
Engineering" §5.4)
--------------------------------------------------------------------
A *telecentric* optical system is one in which the chief ray (the ray from an
off-axis object point that passes through the centre of the aperture stop) is
parallel to the optical axis in one or both conjugate spaces.

Object-space telecentric
~~~~~~~~~~~~~~~~~~~~~~~~
Chief rays in object space are parallel to the optical axis (u_obj = 0).
This is achieved by placing the aperture stop in the *front focal plane* of
the optical system.  As a result, magnification is invariant with defocus
(focus shift) in object space — the image size does not change as the object
moves slightly away from the nominal conjugate.  Critical in machine vision
(dimensional measurement) and lithography.

Condition: the chief-ray angle u_obj = 0 in object space.

Image-space telecentric
~~~~~~~~~~~~~~~~~~~~~~~
Chief rays in image space are parallel to the optical axis (u_img = 0).
Achieved by placing the aperture stop in the *rear focal plane*.  The exit
pupil is at infinity.  Image magnification is invariant with defocus in image
space.  Used in telecentric illumination and telecentrically-corrected
projection objectives.

Condition: the chief-ray angle u_img = 0 in image space.

Both telecentric (doubly telecentric)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Stop between front and rear focal planes of each sub-group such that both
entrance and exit pupils are at infinity.  A symmetric two-lens relay
(f1+f2 gap = f1+f2, stop at shared focal plane) achieves this.  All machine-
vision lenses with parfocal magnification are doubly telecentric.

Algorithm (paraxial, Welford §3 nu-form)
-----------------------------------------
The lens_system_dict provides:
  - surfaces : list of {c, t, n, k} dicts (standard sequential format)
  - stop_surface_index : index of the aperture stop surface (default 0)
  - object_distance_mm : distance from object plane to first surface (default ~∞)
  - n_object : refractive index of object space (default 1.0)

Chief-ray initial conditions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The chief ray must satisfy h_stop = 0 at the aperture stop surface.
We use paraxial superposition (linearity) to solve for u_obj directly:

  Ray A: object height = H (field_height_mm), object angle = 0
         At first surface: h0_A = H + obj_dist * 0 = H, u0_A = 0.
         Trace through lens → h_A_at_stop.

  Ray B: object height = 0, object angle = 1 (unit slope)
         At first surface: h0_B = 0 + obj_dist * 1 = obj_dist, u0_B = 1.
         Trace through lens → h_B_at_stop.

  Combined (H, u_obj = alpha):
         h_at_stop = h_A_at_stop + alpha * h_B_at_stop = 0
         alpha = u_obj = -h_A_at_stop / h_B_at_stop

  Object-space chief-ray angle = alpha (radians), converted to degrees.

  Once u_obj = alpha is found:
    h0 = H + obj_dist * alpha   (height at first surface)
    u0 = alpha                  (slope, unchanged in air until lens)

  Trace this ray through all surfaces → image-space angle = u_after[-1].

Magnification variation with focus shift
------------------------------------------
We compute the paraxial lateral magnification at ±focus_shift_mm/2 by
propagating a unit marginal ray and evaluating the image height at the
shifted image plane.  The percentage variation:

    mag_variation_pct = 100 * |m(+Δ/2) - m(-Δ/2)| / |m(0)|

For a perfectly telecentric system this approaches 0%.

HONEST CAVEAT
--------------
  * Paraxial (first-order) analysis only.
  * Stop modelled as thin plane (h=0 exactly at the stop surface vertex).
  * The 0.5° threshold is conventional; tighter machine-vision systems may
    require < 0.05°.
  * Only spherical/conic surfaces; higher-order aspheric terms do not affect
    the paraxial chief-ray angle.
  * Magnification variation uses the paraxial nu-form marginal-ray formula;
    valid for well-corrected systems near the paraxial image plane.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §3 (paraxial ray tracing, nu-form), §4.4 (stop and pupil theory).
Smith, W.J. -- "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008,
    §5.4 (telecentric optics, chief-ray angle, magnification invariance).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.6 (stops, pupils, telecentric designs).
Kingslake, R. -- "Lens Design Fundamentals", Academic Press, 1978,
    §5.1 (telecentric and quasi-telecentric designs).

Units: lengths in mm, angles in degrees at API boundary (radians internally).

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    _paraxial_refract,
    _paraxial_transfer,
    _validate_surface,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Chief-ray angle below which the system is considered telecentric (degrees).
# Conventional threshold for machine-vision / metrology lenses.
_TELECENTRIC_THRESHOLD_DEG: float = 0.5


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


def _paraxial_trace_surfaces(
    surfaces: list[dict],
    h0: float,
    u0: float,
    n_object: float = 1.0,
    stop_index: int | None = None,
) -> tuple[list[float], list[float], float]:
    """
    Trace a paraxial ray through all surfaces.

    Parameters
    ----------
    surfaces : list of surface dicts (c, t, n, optional k)
    h0 : ray height at first surface
    u0 : ray slope at first surface (in object-space medium)
    n_object : refractive index of object space
    stop_index : if not None, return h at this surface index in the list

    Returns
    -------
    (heights, angles_after, final_image_distance_mm)
    heights[j]       = height at surface j BEFORE refraction
    angles_after[j]  = slope AFTER refraction at surface j
    final_image_distance_mm = -h_last / u_last (from last surface; inf if u_last≈0)
    """
    h = float(h0)
    u = float(u0)
    n = float(n_object)
    heights: list[float] = []
    angles_after: list[float] = []

    for surf in surfaces:
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])
        heights.append(h)
        u_prime = _paraxial_refract(h, u, n, n_prime, c)
        angles_after.append(u_prime)
        h = _paraxial_transfer(h, u_prime, t)
        u = u_prime
        n = n_prime

    # Image distance from last surface
    if abs(u) < 1e-18:
        img_dist = math.inf
    else:
        img_dist = -h / u

    return heights, angles_after, img_dist


def _solve_chief_ray(
    surfaces: list[dict],
    field_height_mm: float,
    stop_surface_index: int,
    object_distance_mm: float,
    n_object: float,
) -> tuple[float, float, float]:
    """
    Solve for the chief-ray parameters.

    The chief ray starts from an object point at (h=field_height_mm, z=-object_distance_mm).
    It must pass through h=0 at the aperture stop surface (index stop_surface_index).

    Using paraxial superposition:
      Ray A: object height=H, object slope=0
             At first surface: h0_A = H + obj_dist * 0 = H, u0_A = 0
      Ray B: object height=0, object slope=1 (unit slope)
             At first surface: h0_B = obj_dist * 1 = obj_dist, u0_B = 1

      Combined with object slope alpha:
             h_at_stop = h_A_at_stop + alpha * h_B_at_stop = 0
             alpha = u_obj = -h_A_at_stop / h_B_at_stop

    Returns
    -------
    (u_obj, h0, u0)
    u_obj : chief-ray angle in object space (radians)
    h0    : chief-ray height at first surface
    u0    : chief-ray slope at first surface (= u_obj for air object space)
    """
    H = float(field_height_mm)
    obj_dist = float(object_distance_mm)

    # ── Ray A: obj height=H, obj slope=0 ──
    h0_A = H  # H + obj_dist * 0
    u0_A = 0.0
    heights_A, _, _ = _paraxial_trace_surfaces(
        surfaces, h0_A, u0_A, n_object
    )
    h_A_stop = heights_A[stop_surface_index]

    # ── Ray B: obj height=0, obj slope=1 ──
    h0_B = obj_dist   # 0 + obj_dist * 1
    u0_B = 1.0
    heights_B, _, _ = _paraxial_trace_surfaces(
        surfaces, h0_B, u0_B, n_object
    )
    h_B_stop = heights_B[stop_surface_index]

    # ── Solve: alpha = u_obj ──
    if abs(h_B_stop) < 1e-18:
        # Degenerate: stop is at infinity for ray B — use u_obj=0
        u_obj = 0.0
    else:
        u_obj = -h_A_stop / h_B_stop

    # Chief-ray at first surface
    h0 = H + obj_dist * u_obj
    u0 = u_obj   # slope in object space (air) = slope at first surface

    return u_obj, h0, u0


# ---------------------------------------------------------------------------
# TelecentricityReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class TelecentricityReport:
    """
    Paraxial chief-ray telecentricity analysis result.

    Attributes
    ----------
    chief_ray_angle_object_deg : float
        Chief-ray angle in object space (degrees).  The angle the chief ray
        makes with the optical axis at the object plane.
        |angle| < 0.5° → object-space telecentric.
    chief_ray_angle_image_deg : float
        Chief-ray angle in image space (degrees).  The slope of the chief ray
        as it exits the last surface toward the image plane.
        |angle| < 0.5° → image-space telecentric.
    object_telecentric : bool
        True when |chief_ray_angle_object_deg| < TELECENTRIC_THRESHOLD_DEG (0.5°).
    image_telecentric : bool
        True when |chief_ray_angle_image_deg| < TELECENTRIC_THRESHOLD_DEG (0.5°).
    both_telecentric : bool
        True when both object_telecentric and image_telecentric are True.
    max_magnification_variation_pct : float
        Maximum percentage change in paraxial magnification over ±focus_shift_mm/2
        image-plane defocus.  Near zero for object-space telecentric systems;
        non-zero otherwise.
    honest_caveat : str
        Scope disclaimer (paraxial only; threshold; approximations).
    """
    chief_ray_angle_object_deg: float
    chief_ray_angle_image_deg: float
    object_telecentric: bool
    image_telecentric: bool
    both_telecentric: bool
    max_magnification_variation_pct: float
    honest_caveat: str = (
        "SCOPE: Paraxial (first-order) analysis only. "
        "Stop modelled as thin plane; chief ray forced through h=0 at stop surface. "
        "Telecentric threshold: |angle| < 0.5 degrees (conventional). "
        "Aspheric surface terms do not affect first-order chief-ray angle. "
        "Magnification variation uses thin-lens paraxial formula (nu-form). "
        "Infinite-conjugate objects approximated by large finite object distance. "
        "Ref: Welford (1986) §3,§4.4; Smith MOE §5.4; Hecht §6.6."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "chief_ray_angle_object_deg": self.chief_ray_angle_object_deg,
            "chief_ray_angle_image_deg": self.chief_ray_angle_image_deg,
            "object_telecentric": self.object_telecentric,
            "image_telecentric": self.image_telecentric,
            "both_telecentric": self.both_telecentric,
            "max_magnification_variation_pct": self.max_magnification_variation_pct,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def compute_telecentricity(
    lens_system_dict: dict,
    field_height_mm: float = 10.0,
    focus_shift_mm: float = 0.5,
) -> "TelecentricityReport | dict":
    """
    Compute the telecentricity of a sequential optical system.

    Parameters
    ----------
    lens_system_dict : dict
        Dictionary describing the optical system.  Required keys:

        surfaces : list of dicts
            Sequential surface list.  Each dict: c (mm^-1), t (mm), n (≥1).
            Optional: k (conic constant, default 0).
        stop_surface_index : int (optional, default 0)
            Index of the surface at whose vertex the aperture stop sits.
            0 = stop at the first surface.
        object_distance_mm : float (optional)
            Distance from object plane to first surface vertex (mm, > 0).
            If omitted, the object is treated as at infinity (approximated by
            10 000 × |EFL| mm).
        n_object : float (optional, default 1.0)
            Refractive index of object space.

    field_height_mm : float
        Height of the off-axis field point (mm).  Must be > 0.  Default 10 mm.

    focus_shift_mm : float
        Defocus range ±(focus_shift_mm/2) for magnification variation (mm).
        Must be > 0.  Default 0.5 mm.

    Returns
    -------
    TelecentricityReport
        Dataclass with chief-ray angles, telecentric flags, and magnification
        variation estimate.
    dict {"ok": False, "reason": "..."}
        On any validation error.

    Theory
    ------
    The chief ray is solved via paraxial superposition (Welford 1986 §3):

    1.  Ray A from (H, 0) in object space; Ray B from (0, 1) in object space.
        Both traced to the stop surface.
    2.  Object-space chief-ray angle u_obj = -h_A_at_stop / h_B_at_stop.
    3.  u_obj determines h0 at the first surface and the full chief-ray trace.
    4.  Image-space angle = u_after[-1] from the full trace.
    5.  |angle_deg| < 0.5° → telecentric.

    References
    ----------
    Welford (1986) §3, §4.4; Smith "Modern Optical Engineering" §5.4;
    Hecht §6.6; Kingslake (1978) §5.1.
    """
    # ── Validate lens_system_dict ─────────────────────────────────────────
    if not isinstance(lens_system_dict, dict):
        return _err("lens_system_dict must be a dict")

    surfaces = lens_system_dict.get("surfaces")
    if surfaces is None:
        return _err("lens_system_dict must contain 'surfaces' key")
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)

    n_surfs = len(surfaces)

    # stop_surface_index
    stop_idx_raw = lens_system_dict.get("stop_surface_index", 0)
    try:
        stop_surface_index = int(stop_idx_raw)
    except (TypeError, ValueError):
        return _err("stop_surface_index must be an integer")
    if stop_surface_index < 0 or stop_surface_index >= n_surfs:
        return _err(
            f"stop_surface_index {stop_surface_index} out of range [0, {n_surfs - 1}]"
        )

    # n_object
    n_object_raw = lens_system_dict.get("n_object", 1.0)
    e = _guard("n_object", n_object_raw)
    if e:
        return _err(e)
    n_object = float(n_object_raw)
    if n_object < 1.0:
        return _err("n_object must be >= 1.0")

    # field_height_mm
    e = _guard("field_height_mm", field_height_mm, positive=True)
    if e:
        return _err(e)

    # focus_shift_mm
    e = _guard("focus_shift_mm", focus_shift_mm, positive=True)
    if e:
        return _err(e)

    field_height_mm = float(field_height_mm)
    focus_shift_mm = float(focus_shift_mm)

    # object_distance_mm — derive or use provided
    obj_dist_raw = lens_system_dict.get("object_distance_mm", None)

    # Derive EFL for infinite-object approximation
    h_marg, u_marg_after, _bfl = _paraxial_trace_surfaces(
        surfaces, h0=1.0, u0=0.0, n_object=n_object
    )
    u_final_marg = u_marg_after[-1]
    if abs(u_final_marg) < 1e-18:
        efl = 100.0   # fallback
    else:
        efl = abs(-1.0 / u_final_marg)

    if obj_dist_raw is None:
        # Infinite-conjugate: approximate with large finite distance
        object_distance_mm = max(10_000.0 * efl, 1_000_000.0)
    else:
        e = _guard("object_distance_mm", obj_dist_raw, positive=True)
        if e:
            return _err(e)
        object_distance_mm = float(obj_dist_raw)

    # ── Solve for chief-ray ────────────────────────────────────────────────
    u_obj, h0_chief, u0_chief = _solve_chief_ray(
        surfaces, field_height_mm, stop_surface_index,
        object_distance_mm, n_object,
    )

    # Object-space chief-ray angle = u_obj (in radians)
    chief_ray_angle_object_rad = u_obj
    chief_ray_angle_object_deg = math.degrees(u_obj)

    # ── Trace chief ray through all surfaces ───────────────────────────────
    _, u_chief_after, _ = _paraxial_trace_surfaces(
        surfaces, h0=h0_chief, u0=u0_chief, n_object=n_object,
    )
    chief_ray_angle_image_rad = u_chief_after[-1]
    chief_ray_angle_image_deg = math.degrees(chief_ray_angle_image_rad)

    # ── Telecentric flags ──────────────────────────────────────────────────
    threshold = _TELECENTRIC_THRESHOLD_DEG
    object_telecentric = abs(chief_ray_angle_object_deg) < threshold
    image_telecentric = abs(chief_ray_angle_image_deg) < threshold
    both_telecentric = object_telecentric and image_telecentric

    # ── Magnification variation with image-plane focus shift ───────────────
    # Trace a marginal ray from the axial object point at z = -object_distance_mm:
    # h_obj = 0, u_obj = 1/object_distance_mm (maps to unit off-axis height at obj).
    # At first surface: h0 = 0 + obj_dist * (1/obj_dist) = 1.
    # Actually use a canonical marginal ray: h0 = 1/obj_dist * obj_dist = 1,
    # u0 = 1/obj_dist.
    # The image height at the nominal focus is h_image = h_last + bfl * u_last.
    # Magnification = h_image / (object_height = 1).

    u_marg_obj = 1.0 / object_distance_mm
    h0_marg = object_distance_mm * u_marg_obj  # = 1.0
    heights_marg, u_after_marg, bfl_marg = _paraxial_trace_surfaces(
        surfaces, h0=h0_marg, u0=u_marg_obj, n_object=n_object,
    )

    h_last_marg = heights_marg[-1]
    u_img_marg = u_after_marg[-1]

    def _mag_at_shift(shift_mm: float) -> float:
        if not math.isfinite(bfl_marg):
            return math.inf
        h_image = h_last_marg + (bfl_marg + shift_mm) * u_img_marg
        # object height = 1 mm (unit object)
        return h_image

    delta = focus_shift_mm / 2.0
    m_nom = _mag_at_shift(0.0)
    if not math.isfinite(m_nom) or abs(m_nom) < 1e-18:
        mag_variation_pct = float("nan")
    else:
        m_plus = _mag_at_shift(delta)
        m_minus = _mag_at_shift(-delta)
        if not math.isfinite(m_plus) or not math.isfinite(m_minus):
            mag_variation_pct = float("nan")
        else:
            mag_variation_pct = 100.0 * abs(m_plus - m_minus) / abs(m_nom)

    return TelecentricityReport(
        chief_ray_angle_object_deg=chief_ray_angle_object_deg,
        chief_ray_angle_image_deg=chief_ray_angle_image_deg,
        object_telecentric=object_telecentric,
        image_telecentric=image_telecentric,
        both_telecentric=both_telecentric,
        max_magnification_variation_pct=mag_variation_pct,
    )
